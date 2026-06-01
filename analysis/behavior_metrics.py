"""Higher-level behavioral metrics derived from tool spans and run artifacts."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from collections import defaultdict
from os.path import basename
from pathlib import Path
from typing import Any

from analysis.tool_spans import load_jsonl, write_tool_spans


SEARCH_CATEGORIES = {"search"}
READ_CATEGORIES = {"read", "search"}
TEST_CATEGORIES = {"test"}
EXCESSIVE_OUTPUT_BYTES = 64 * 1024
EXCESSIVE_MATCH_LINES = 200
NOISE_COMMAND_MARKERS = (
    ".pyenv",
    ".zcompdump",
    ".oh-my-zsh",
    ".make-cflags",
    ".make-ldflags",
    ".nvm",
    "/home/abhi/.nvm",
    "<stdatomic.h>",
    "conftest",
    "foo.c",
    "ARGV[1]",
    "^lts/",
    "lts/*",
    "^v24.",
    "/bin:.*/home",
    "<tmp>",
    "uname -s",
    "uname -m",
    "type ${CC",
    "type ${CXX",
    "pkg-config --exists",
)


def _safe_split(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _normalize_command(command: str) -> str:
    parts = _safe_split(command)
    if not parts:
        return command.strip()
    normalized = []
    for part in parts:
        if part.startswith("/tmp/") or part.startswith("tests/tmp/"):
            normalized.append("<tmp>")
        elif part.isdigit():
            normalized.append("<n>")
        else:
            normalized.append(part)
    return " ".join(normalized)


def _load_changed_files(run_dir: Path) -> list[str]:
    codebase = run_dir / "codebase"
    if not codebase.exists():
        return []
    try:
        result = subprocess.run(
            ["git", "-C", str(codebase), "diff", "--name-only"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return []
    if result.returncode not in (0, 1):
        return []
    return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())


def _normalize_repo_path(run_dir: Path, value: str | None) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    codebase = (run_dir / "codebase").resolve()
    try:
        path = Path(raw)
        if path.is_absolute():
            return str(path.resolve().relative_to(codebase))
    except (OSError, ValueError):
        pass

    for marker in ("/codebase/", "codebase/"):
        if marker in raw:
            return raw.split(marker, 1)[1].lstrip("/")
    return raw.lstrip("./")


def _load_structured_file_accesses(run_dir: Path) -> dict[str, set[str]]:
    path = run_dir / "structured_events_observed.jsonl"
    if not path.exists():
        return {"reads": set(), "edits": set()}

    reads: set[str] = set()
    edits: set[str] = set()
    read_tools = {"Read"}
    edit_tools = {"Edit", "MultiEdit", "Write", "NotebookEdit"}

    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            observed = json.loads(line)
        except json.JSONDecodeError:
            continue
        record = observed.get("record")
        if not isinstance(record, dict):
            continue

        if record.get("type") == "tool_execution_start":
            tool_name = str(record.get("toolName") or "")
            tool_input = record.get("args") if isinstance(record.get("args"), dict) else {}
            file_path = _normalize_repo_path(
                run_dir,
                tool_input.get("path") or tool_input.get("file_path"),
            )
            if not file_path:
                continue
            if tool_name == "read":
                reads.add(file_path)
            elif tool_name in {"edit", "write"}:
                edits.add(file_path)
            continue

        message = record.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "tool_use":
                continue
            tool_name = str(item.get("name") or "")
            tool_input = item.get("input") if isinstance(item.get("input"), dict) else {}
            file_path = _normalize_repo_path(run_dir, tool_input.get("file_path"))
            if not file_path:
                continue
            if tool_name in read_tools:
                reads.add(file_path)
            elif tool_name in edit_tools:
                edits.add(file_path)

    return {"reads": reads, "edits": edits}


def _looks_like_file(arg: str) -> bool:
    if not arg or arg.startswith("-"):
        return False
    if any(ch in arg for ch in "*[]{}|;$`"):
        return False
    if arg in {".", ".."}:
        return False
    return "/" in arg or "." in basename(arg)


def _files_from_command(command: str) -> list[str]:
    files: list[str] = []
    parts = _safe_split(command)
    for arg in parts[1:]:
        if _looks_like_file(arg):
            files.append(arg.lstrip("./"))
    return files


def _is_metric_noise(span: dict[str, Any]) -> bool:
    if span.get("category") == "bootstrap" or span.get("span_role") == "bootstrap":
        return True
    command = str(span.get("command") or "")
    return any(marker in command for marker in NOISE_COMMAND_MARKERS)


def _is_task_test_span(span: dict[str, Any]) -> bool:
    if _is_metric_noise(span):
        return False
    command = str(span.get("command") or "").lower()
    tool = str(span.get("tool") or "").lower()
    return (
        "runtest" in command
        or "pytest" in command
        or " test" in command
        or tool in {"pytest", "runtest", "jest", "vitest"}
    )


def _parse_codex_transcript_outputs(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Best-effort high-level command output summaries from Codex stderr transcripts."""
    path = run_dir / "stderr.log"
    if not path.exists():
        return {}

    lines = path.read_text(errors="replace").splitlines()
    blocks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    idx = 0
    while idx < len(lines) - 1:
        if lines[idx].strip() != "exec":
            idx += 1
            continue

        raw_line = lines[idx + 1].strip()
        if " in " not in raw_line:
            idx += 1
            continue
        raw_command = raw_line.split(" in ", 1)[0]
        command = _shell_inner_command(raw_command)
        status_idx = idx + 2
        status = lines[status_idx].strip() if status_idx < len(lines) else ""
        output_start = status_idx + 1 if status.endswith(":") else status_idx

        output_lines: list[str] = []
        cursor = output_start
        while cursor < len(lines):
            marker = lines[cursor].strip()
            if marker in {"exec", "codex", "user"}:
                break
            if marker.startswith("2026-") and " WARN " in marker:
                break
            output_lines.append(lines[cursor])
            cursor += 1

        output_text = "\n".join(output_lines)
        blocks[command].append(
            {
                "stdout_bytes": len(output_text.encode("utf-8")),
                "stdout_line_count": len([line for line in output_lines if line.strip()]),
                "status": status,
            }
        )
        idx = cursor
    return dict(blocks)


def _shell_inner_command(raw_command: str) -> str:
    parts = _safe_split(raw_command)
    for flag in ("-c", "-lc", "-ec"):
        if flag in parts:
            idx = parts.index(flag)
            if idx + 1 < len(parts):
                return parts[idx + 1]
    return raw_command


def _span_output_summary(span: dict[str, Any], transcript_outputs: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    stdout_bytes = span.get("stdout_bytes")
    stderr_bytes = span.get("stderr_bytes")
    stdout_lines = span.get("stdout_line_count")
    source = "span"

    if stdout_bytes is None and stderr_bytes is None:
        command = str(span.get("command") or "")
        candidates = transcript_outputs.get(command) or []
        if candidates:
            rec = candidates.pop(0)
            stdout_bytes = rec.get("stdout_bytes")
            stdout_lines = rec.get("stdout_line_count")
            stderr_bytes = 0
            source = "codex_transcript"

    total = int(stdout_bytes or 0) + int(stderr_bytes or 0)
    return {
        "stdout_bytes": int(stdout_bytes or 0),
        "stderr_bytes": int(stderr_bytes or 0),
        "stdout_line_count": int(stdout_lines or 0),
        "total_output_bytes": total,
        "output_source": source if total else None,
    }


def _span_sort_key(span: dict[str, Any]) -> float:
    value = span.get("start_s")
    return float(value) if value is not None else 1e18


def _source_edit_spans(spans: list[dict[str, Any]], changed_files: set[str]) -> list[dict[str, Any]]:
    if not changed_files:
        return []
    edits: list[dict[str, Any]] = []
    for span in spans:
        if span.get("category") != "edit":
            continue
        command = str(span.get("command") or "")
        if any(path in command for path in changed_files):
            edits.append(span)
    return sorted(edits, key=_span_sort_key)


def derive_behavior_metrics(run_dir: Path, spans: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if spans is None:
        span_path = run_dir / "tool_spans.jsonl"
        spans = load_jsonl(span_path) if span_path.exists() else write_tool_spans(run_dir)

    changed_files = set(_load_changed_files(run_dir))
    transcript_outputs = _parse_codex_transcript_outputs(run_dir)
    structured_file_accesses = _load_structured_file_accesses(run_dir)

    search_zero: list[dict[str, Any]] = []
    search_excessive: list[dict[str, Any]] = []
    read_files: set[str] = set(structured_file_accesses["reads"])
    noise_span_count = 0
    output_known_count = 0
    output_total_bytes = 0
    outputs_by_category: dict[str, int] = defaultdict(int)
    enriched_outputs: dict[str, dict[str, Any]] = {}

    for span in sorted(spans, key=_span_sort_key):
        span_id = str(span.get("span_id"))
        category = str(span.get("category", "unknown"))
        command = str(span.get("command") or "")
        output = _span_output_summary(span, transcript_outputs)
        enriched_outputs[span_id] = output
        is_noise = _is_metric_noise(span)
        if is_noise:
            noise_span_count += 1
        if output["total_output_bytes"]:
            output_known_count += 1
            output_total_bytes += output["total_output_bytes"]
            outputs_by_category[category] += output["total_output_bytes"]

        if category in READ_CATEGORIES and not is_noise:
            for file_path in _files_from_command(command):
                normalized = _normalize_repo_path(run_dir, file_path)
                if normalized:
                    read_files.add(normalized)

        if category in SEARCH_CATEGORIES and not is_noise:
            exit_code = span.get("exit_code")
            if exit_code == 1 or (
                output["output_source"] and output["stdout_line_count"] == 0 and exit_code in (0, None)
            ):
                search_zero.append(_brief_span(span, output))
            if (
                output["total_output_bytes"] >= EXCESSIVE_OUTPUT_BYTES
                or output["stdout_line_count"] >= EXCESSIVE_MATCH_LINES
            ):
                search_excessive.append(_brief_span(span, output))

    read_later_edited = sorted(path for path in read_files if path in changed_files)
    source_edits = _source_edit_spans(spans, changed_files)

    test_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for span in sorted(spans, key=_span_sort_key):
        if span.get("category") in TEST_CATEGORIES and _is_task_test_span(span):
            test_history[_normalize_command(str(span.get("command") or ""))].append(span)

    tests_failed_then_passed = []
    for command, history in test_history.items():
        saw_failure = False
        for span in history:
            exit_code = span.get("exit_code")
            if exit_code not in (None, 0):
                saw_failure = True
            elif exit_code == 0 and saw_failure:
                tests_failed_then_passed.append(
                    {"command": command, "passing_span": _brief_span(span, enriched_outputs.get(str(span.get("span_id")), {}))}
                )
                break

    repeated_failures = _repeated_failures_without_detected_edit(spans, source_edits)

    return {
        "coverage": {
            "output_known_span_count": output_known_count,
            "total_span_count": len(spans),
            "output_known_fraction": round(output_known_count / len(spans), 4) if spans else 0,
            "changed_files_available": bool(changed_files),
            "source_edit_span_count": len(source_edits),
            "structured_read_file_count": len(structured_file_accesses["reads"]),
            "structured_edit_file_count": len(structured_file_accesses["edits"]),
            "metric_noise_span_count": noise_span_count,
        },
        "searches_with_zero_matches": {
            "count": len(search_zero),
            "examples": search_zero[:25],
        },
        "searches_with_excessive_matches": {
            "count": len(search_excessive),
            "threshold_stdout_bytes": EXCESSIVE_OUTPUT_BYTES,
            "threshold_stdout_lines": EXCESSIVE_MATCH_LINES,
            "examples": search_excessive[:25],
        },
        "reads_of_files_later_edited": {
            "count": len(read_later_edited),
            "files": read_later_edited[:100],
        },
        "tests_failed_then_passed": {
            "count": len(tests_failed_then_passed),
            "examples": tests_failed_then_passed[:25],
        },
        "repeated_failures_without_detected_edit": {
            "count": len(repeated_failures),
            "examples": repeated_failures[:25],
            "caveat": (
                "Uses detected source-edit spans only; not evaluated when no source-edit "
                "timestamps are available."
            ),
        },
        "command_output_volume": {
            "known_span_count": output_known_count,
            "total_output_bytes": output_total_bytes,
            "total_output_mb": round(output_total_bytes / 1024 / 1024, 3),
            "by_category_bytes": dict(sorted(outputs_by_category.items())),
        },
    }


def _brief_span(span: dict[str, Any], output: dict[str, Any] | None = None) -> dict[str, Any]:
    output = output or {}
    return {
        "span_id": span.get("span_id"),
        "tool": span.get("tool"),
        "category": span.get("category"),
        "span_role": span.get("span_role"),
        "attribution_confidence": span.get("attribution_confidence"),
        "start_s": span.get("start_s"),
        "exit_code": span.get("exit_code"),
        "command": span.get("command"),
        "stdout_bytes": output.get("stdout_bytes", span.get("stdout_bytes")),
        "stderr_bytes": output.get("stderr_bytes", span.get("stderr_bytes")),
        "stdout_line_count": output.get("stdout_line_count"),
    }


def _repeated_failures_without_detected_edit(
    spans: list[dict[str, Any]],
    source_edits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not source_edits:
        return []

    edit_times = [float(span["start_s"]) for span in source_edits if span.get("start_s") is not None]
    failures_by_command: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for span in spans:
        if _is_metric_noise(span):
            continue
        exit_code = span.get("exit_code")
        if exit_code in (None, 0):
            continue
        command = _normalize_command(str(span.get("command") or ""))
        failures_by_command[command].append(span)

    repeated: list[dict[str, Any]] = []
    for command, failures in failures_by_command.items():
        failures = sorted(failures, key=_span_sort_key)
        for prev, curr in zip(failures, failures[1:]):
            prev_t = prev.get("start_s")
            curr_t = curr.get("start_s")
            if prev_t is None or curr_t is None:
                continue
            had_edit = any(float(prev_t) < edit_t < float(curr_t) for edit_t in edit_times)
            if not had_edit:
                repeated.append(
                    {
                        "command": command,
                        "previous_failure": _brief_span(prev),
                        "next_failure": _brief_span(curr),
                    }
                )
                break
    return repeated


def write_behavior_metrics(run_dir: Path, spans: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    metrics = derive_behavior_metrics(run_dir, spans)
    with (run_dir / "behavior_metrics.json").open("w") as f:
        json.dump(metrics, f, indent=2)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive useful behavioral metrics for a run")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    metrics = write_behavior_metrics(args.run_dir)
    print(f"Wrote behavior metrics to {args.run_dir / 'behavior_metrics.json'}")
    for key in (
        "searches_with_zero_matches",
        "searches_with_excessive_matches",
        "reads_of_files_later_edited",
        "tests_failed_then_passed",
        "repeated_failures_without_detected_edit",
    ):
        print(f"  {key}: {metrics[key]['count']}")
    output = metrics["command_output_volume"]
    print(f"  command_output_volume: {output['total_output_mb']} MB across {output['known_span_count']} spans")


if __name__ == "__main__":
    main()
