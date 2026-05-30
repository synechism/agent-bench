"""Derive behavioral tool spans from raw run logs.

This module turns the existing low-level signals into an analysis-friendly
timeline: one row per tool/process span with command semantics and sampled
resource rollups.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shlex
from collections import defaultdict
from datetime import datetime
from os.path import basename
from pathlib import Path
from typing import Any


SHELL_TOOLS = {"bash", "sh", "zsh"}
AGENT_TOOLS = {"claude", "codex", "node", "deno", "pi", "opencode", "strace"}
BOOTSTRAP_MARKERS = (
    ".oh-my-zsh",
    ".zcompdump",
    ".pyenv",
    "shell-snapshots",
    "zstyle",
    "compinit",
    "CLAUDE_CODE_EXECPATH",
)

STRACE_EXEC_START_RE = re.compile(
    r'^\s*(?P<pid>\d+)\s+(?P<ts>\d+(?:\.\d+)?)\s+'
    r'execve\("(?P<exe>(?:\\.|[^"])*)",\s+(?P<argv>\[.*\]),\s+.*$'
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def parse_iso_epoch(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def run_time_bounds(run_dir: Path) -> dict[str, float | None]:
    events = load_jsonl(run_dir / "events.jsonl")
    bounds: dict[str, float | None] = {
        "run_start": None,
        "agent_started": None,
        "sampler_started": None,
        "run_end": None,
    }
    for event in events:
        name = event.get("event")
        if name in bounds:
            bounds[name] = parse_iso_epoch(event.get("ts"))
    return bounds


def _decode_c_string(value: str) -> str:
    try:
        return ast.literal_eval(f'"{value}"')
    except (SyntaxError, ValueError):
        return value


def _parse_argv_array(value: str) -> list[str]:
    try:
        argv = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return []
    if not isinstance(argv, list):
        return []
    return [str(arg) for arg in argv]


def shell_inner_command(tool: str, argv_text: str) -> str:
    if tool not in SHELL_TOOLS:
        return argv_text
    try:
        parts = shlex.split(argv_text)
    except ValueError:
        parts = argv_text.split()
    for flag in ("-c", "-lc", "-ec"):
        if flag in parts:
            idx = parts.index(flag)
            if idx + 1 < len(parts):
                return parts[idx + 1]
    return argv_text


def command_tool(command: str, fallback: str = "unknown") -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    if not parts:
        return fallback
    return basename(parts[0])


def classify_command(tool: str, argv_text: str) -> str:
    inner = shell_inner_command(tool, argv_text)
    inner_tool = command_tool(inner, tool) if tool in SHELL_TOOLS else tool
    lower = inner.lower()
    base = inner_tool.lower()

    if tool in AGENT_TOOLS or base in AGENT_TOOLS:
        return "agent_runtime"
    if _is_bootstrap_command(inner):
        return "bootstrap"
    if base == "git":
        if re.search(r"\b(grep)\b", lower):
            return "search"
        return "vcs"
    if base in {"rg", "grep", "find", "fd"}:
        return "search"
    if base in {"cat", "head", "tail", "less", "more", "sed", "awk", "ls", "wc", "stat"}:
        if " -i" in f" {inner} " or re.search(r"\b(sponge|tee)\b", lower):
            return "edit"
        return "read"
    if base in {"make", "cmake", "gcc", "clang", "cc", "g++", "ld", "rustc", "go", "javac"}:
        if "test" in lower or "runtest" in lower:
            return "test"
        return "build"
    if base in {"pytest", "jest", "vitest", "runtest"} or "runtest" in lower:
        return "test"
    if base.endswith((".py", ".pl", ".rb", ".sh")):
        return "script"
    if base in {"python", "python3", "perl", "ruby"}:
        if any(marker in lower for marker in ("write_text", "open(", "sed -i", "perl -pi")):
            return "edit"
        return "script"
    if base in {"npm", "npx", "pip", "poetry", "cargo", "apt", "apt-get"}:
        if " test" in lower:
            return "test"
        return "package"
    if base in {"cp", "mv", "rm", "mkdir", "chmod", "touch", "tee", "patch"}:
        return "edit"
    if tool in SHELL_TOOLS or base in SHELL_TOOLS:
        return "shell"
    if base in {"curl", "wget"}:
        return "network"
    return "other"


def _is_bootstrap_command(command: str) -> bool:
    return any(marker in command for marker in BOOTSTRAP_MARKERS)


def _span_kind(source: str, tool: str, argv_text: str) -> str:
    if source in {"codex_transcript", "claude_shell_command", "strace_shell_command"}:
        return "high_level_tool"
    if tool in AGENT_TOOLS:
        return "agent_process"
    if _is_bootstrap_command(argv_text):
        return "bootstrap"
    return "subprocess"


def _span_role(kind: str, category: str) -> str:
    if kind == "agent_process" or category == "agent_runtime":
        return "agent_runtime"
    if category == "bootstrap":
        return "bootstrap"
    if category in {
        "build",
        "test",
        "script",
        "vcs",
        "search",
        "read",
        "edit",
        "package",
        "network",
    }:
        return category
    if category == "shell":
        return "shell_wrapper"
    if kind == "high_level_tool":
        return "agent_tool"
    return "unknown"


def _load_exec_log_spans(run_dir: Path) -> list[dict[str, Any]]:
    starts: dict[int, dict[str, Any]] = {}
    spans: list[dict[str, Any]] = []
    for rec in load_jsonl(run_dir / "exec_log.jsonl"):
        if rec.get("source") != "shim" or "tool" not in rec or "pid" not in rec:
            continue
        pid = int(rec["pid"])
        if "start" in rec:
            starts[pid] = rec
            continue
        if "end" not in rec:
            continue
        start = starts.pop(pid, None)
        if not start:
            continue
        tool = str(start.get("tool", rec.get("tool", "unknown")))
        argv_text = str(start.get("argv", ""))
        spans.append(
            {
                "source": "shim",
                "tool": tool,
                "argv": argv_text,
                "command": shell_inner_command(tool, argv_text),
                "pid": pid,
                "start_ts": float(start["start"]),
                "end_ts": float(rec["end"]),
                "exit_code": rec.get("exit"),
                "stdout_bytes": rec.get("stdout_bytes"),
                "stderr_bytes": rec.get("stderr_bytes"),
            }
        )
    for pid, start in starts.items():
        tool = str(start.get("tool", "unknown"))
        argv_text = str(start.get("argv", ""))
        spans.append(
            {
                "source": "shim",
                "tool": tool,
                "argv": argv_text,
                "command": shell_inner_command(tool, argv_text),
                "pid": pid,
                "start_ts": float(start["start"]),
                "end_ts": None,
                "exit_code": None,
                "stdout_bytes": None,
                "stderr_bytes": None,
            }
        )
    return spans


def _extract_claude_shell_command(argv: list[str]) -> str | None:
    for arg in argv:
        match = re.search(r"(?:^|&& )eval (?P<command>.+?) < /dev/null", arg, re.S)
        if not match:
            continue
        command = match.group("command").strip()
        try:
            decoded = ast.literal_eval(command)
        except (SyntaxError, ValueError):
            return command
        return decoded if isinstance(decoded, str) else command
    return None


def _load_strace_shell_spans(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "strace_exec.log"
    if not path.exists():
        return []

    spans: list[dict[str, Any]] = []
    seen: set[tuple[int, float, str]] = set()
    for line in path.read_text(errors="replace").splitlines():
        match = STRACE_EXEC_START_RE.match(line)
        if not match:
            continue
        pid = int(match.group("pid"))
        ts = float(match.group("ts"))
        exe = _decode_c_string(match.group("exe"))
        argv = _parse_argv_array(match.group("argv"))
        if not argv:
            continue

        exe_base = basename(exe)
        argv0 = basename(argv[0])
        tool = argv0 or exe_base
        argv_text = shlex.join(argv[1:]) if len(argv) > 1 else ""
        command = None
        source = None

        if tool in SHELL_TOOLS and any(flag in argv for flag in ("-c", "-lc", "-ec")):
            command = shell_inner_command(tool, shlex.join(argv[1:]))
            source = "strace_shell_command"
        else:
            claude_command = _extract_claude_shell_command(argv)
            if claude_command:
                command = claude_command
                tool = command_tool(command)
                argv_text = command
                source = "claude_shell_command"

        if not source or not command:
            continue
        if _is_bootstrap_command(command):
            continue
        key = (pid, round(ts, 6), command)
        if key in seen:
            continue
        seen.add(key)
        spans.append(
            {
                "source": source,
                "tool": tool,
                "argv": argv_text,
                "command": command,
                "executable": exe,
                "pid": pid,
                "start_ts": ts,
                "end_ts": None,
                "exit_code": None,
            }
        )
    return spans


def _load_existing_tool_events(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "tool_events.jsonl"
    if not path.exists():
        return []
    return load_jsonl(path)


def _load_proc(run_dir: Path):
    ts_path = run_dir / "proc_timeseries.parquet"
    if not ts_path.exists():
        ts_path = run_dir / "proc_timeseries.csv"
    if not ts_path.exists():
        return None

    import pandas as pd

    return pd.read_parquet(ts_path) if ts_path.suffix == ".parquet" else pd.read_csv(ts_path)


def _build_parent_map(df) -> dict[int, set[int]]:
    by_parent: dict[int, set[int]] = defaultdict(set)
    for rec in df[["pid", "ppid"]].drop_duplicates().itertuples(index=False):
        by_parent[int(rec.ppid)].add(int(rec.pid))
    return by_parent


def _pid_descendants(by_parent: dict[int, set[int]], root_pid: int) -> set[int]:
    seen: set[int] = set()
    stack = [root_pid]
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        stack.extend(by_parent.get(pid, set()))
    return seen


def _rollup_span_resources(
    df,
    span: dict[str, Any],
    sampler_epoch: float | None,
    by_parent: dict[int, set[int]] | None,
    descendants_cache: dict[int, set[int]],
) -> dict[str, Any]:
    pid = span.get("pid")
    if not pid or df is None or df.empty:
        return {
            "start_s": None,
            "end_s": None,
            "duration_s": None,
            "start_time_source": "unknown",
            "end_time_source": "unknown",
            "peak_pss": 0,
            "peak_uss": 0,
            "peak_rss": 0,
            "peak_sampled_at": None,
            "cpu_total_s": 0.0,
            "sampled_processes": 0,
        }

    pid = int(pid)
    if pid not in descendants_cache:
        descendants_cache[pid] = _pid_descendants(by_parent or {}, pid)
    descendants = descendants_cache[pid]
    if not descendants:
        descendants = {pid}

    start_ts = span.get("start_ts")
    end_ts = span.get("end_ts")
    start_s = float(start_ts - sampler_epoch) if start_ts is not None and sampler_epoch else None
    end_s = float(end_ts - sampler_epoch) if end_ts is not None and sampler_epoch else None

    window = df[df["pid"].isin(descendants)]
    if start_s is not None:
        window = window[window["ts"] >= max(0, start_s - 0.05)]
    if end_s is not None:
        window = window[window["ts"] <= end_s + 0.05]

    if window.empty:
        return {
            "start_s": start_s,
            "end_s": end_s,
            "duration_s": (end_s - start_s) if start_s is not None and end_s is not None else None,
            "start_time_source": "exact" if start_s is not None else "unknown",
            "end_time_source": "exact" if end_s is not None else "unknown",
            "peak_pss": 0,
            "peak_uss": 0,
            "peak_rss": 0,
            "peak_sampled_at": None,
            "cpu_total_s": 0.0,
            "sampled_processes": 0,
        }

    inferred_start = float(window["ts"].min()) if start_s is None else start_s
    inferred_end = float(window["ts"].max()) if end_s is None else end_s
    tick_totals = window.groupby("ts").agg(
        pss=("pss", "sum"),
        uss=("uss", "sum"),
        rss=("rss", "sum"),
    )
    peak_ts = float(tick_totals["pss"].idxmax())

    clk_tck = os.sysconf(os.sysconf_names.get("SC_CLK_TCK", "SC_CLK_TCK"))
    cpu_ticks = 0
    for _, proc_rows in window.groupby(["pid", "starttime"]):
        cpu_start = int((proc_rows["utime"] + proc_rows["stime"]).min())
        cpu_end = int((proc_rows["utime"] + proc_rows["stime"]).max())
        cpu_ticks += max(0, cpu_end - cpu_start)

    return {
        "start_s": round(inferred_start, 3),
        "end_s": round(inferred_end, 3),
        "duration_s": round(max(0.0, inferred_end - inferred_start), 3),
        "start_time_source": "exact" if start_s is not None else "inferred_from_proc",
        "end_time_source": "exact" if end_s is not None else "inferred_from_proc",
        "peak_pss": int(tick_totals["pss"].max()),
        "peak_uss": int(tick_totals["uss"].max()),
        "peak_rss": int(tick_totals["rss"].max()),
        "peak_sampled_at": peak_ts,
        "cpu_total_s": round(cpu_ticks / clk_tck, 3),
        "sampled_processes": int(window["pid"].nunique()),
    }


def _dedupe_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preferred_source = {
        "strace_shell_command": 0,
        "claude_shell_command": 0,
        "shim": 1,
        "proc_observed": 2,
    }
    spans = sorted(
        spans,
        key=lambda s: (
            int(s.get("pid") or -1),
            round(float(s.get("start_ts") or 0), 3),
            preferred_source.get(str(s.get("source")), 10),
            str(s.get("command") or s.get("argv") or ""),
        ),
    )
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    for span in spans:
        pid = int(span.get("pid") or -1)
        start_ms = int(round(float(span.get("start_ts") or 0) * 1000))
        command = str(span.get("command") or span.get("argv") or span.get("tool") or "")
        key = (pid, start_ms, command)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(span)
    return deduped


def _run_peak_ts(df) -> float | None:
    if df is None or df.empty:
        return None
    ticks = df.groupby("ts").agg(total_pss=("pss", "sum"))
    return float(ticks["total_pss"].idxmax())


def _is_active_at_peak(span: dict[str, Any], peak_ts: float | None) -> bool:
    if peak_ts is None or span.get("start_s") is None:
        return False
    start = float(span["start_s"])
    end = span.get("end_s")
    return start - 0.05 <= peak_ts and (end is None or peak_ts <= float(end) + 0.05)


def _overlap_count(span: dict[str, Any], spans: list[dict[str, Any]]) -> int:
    start = span.get("start_s")
    end = span.get("end_s")
    pid = span.get("pid")
    if start is None or end is None:
        return 0
    start_f = float(start)
    end_f = float(end)
    count = 0
    for other in spans:
        if other is span or other.get("pid") == pid or other.get("start_s") is None:
            continue
        other_start = float(other["start_s"])
        if other_start < start_f or other_start > end_f:
            continue
        other_end = other.get("end_s")
        if other_end is None or float(other_end) <= end_f + 0.05:
            count += 1
    return count


def _attribution_confidence(span: dict[str, Any]) -> str:
    source = span.get("source")
    if source == "proc_observed":
        return "low"
    if int(span.get("sampled_processes") or 0) == 0:
        return "low"
    if span.get("possible_over_attribution"):
        return "medium"
    if span.get("end_time_source") != "exact":
        return "medium"
    return "high"


def _add_attribution_metadata(spans: list[dict[str, Any]], peak_ts: float | None) -> None:
    for span in spans:
        kind = str(span.get("kind", ""))
        category = str(span.get("category", "unknown"))
        sampled_processes = int(span.get("sampled_processes") or 0)
        overlapping = _overlap_count(span, spans)
        includes_descendants = sampled_processes > 1
        is_nested_parent = includes_descendants and overlapping > 0
        span["span_role"] = _span_role(kind, category)
        span["active_at_peak"] = _is_active_at_peak(span, peak_ts)
        span["includes_descendants"] = includes_descendants
        span["is_nested_parent"] = is_nested_parent
        span["overlapping_inner_span_count"] = overlapping
        span["possible_over_attribution"] = bool(
            is_nested_parent
            and category in {"agent_runtime", "shell", "build", "test", "script", "vcs"}
        )
        span["attribution_confidence"] = _attribution_confidence(span)


def derive_tool_spans(run_dir: Path) -> list[dict[str, Any]]:
    bounds = run_time_bounds(run_dir)
    sampler_epoch = bounds.get("sampler_started") or bounds.get("agent_started")
    proc_df = _load_proc(run_dir)
    by_parent = _build_parent_map(proc_df) if proc_df is not None and not proc_df.empty else None
    descendants_cache: dict[int, set[int]] = {}
    peak_ts = _run_peak_ts(proc_df)

    spans = []
    spans.extend(_load_exec_log_spans(run_dir))
    spans.extend(_load_strace_shell_spans(run_dir))
    exact_pids = {int(span["pid"]) for span in spans if span.get("pid") is not None}

    # Preserve proc-observed events for long-lived tools missed by exact logs.
    for event in _load_existing_tool_events(run_dir):
        if event.get("source") != "proc_observed":
            continue
        if event.get("pid") is not None and int(event["pid"]) in exact_pids:
            continue
        spans.append(
            {
                "source": "proc_observed",
                "tool": event.get("tool", "unknown"),
                "argv": "",
                "command": str(event.get("tool", "unknown")),
                "pid": event.get("pid"),
                "start_ts": (
                    sampler_epoch + float(event["first_seen_s"])
                    if sampler_epoch and "first_seen_s" in event
                    else None
                ),
                "end_ts": (
                    sampler_epoch + float(event["last_seen_s"])
                    if sampler_epoch and "last_seen_s" in event
                    else None
                ),
                "exit_code": None,
            }
        )

    spans = _dedupe_spans(spans)
    enriched: list[dict[str, Any]] = []
    for idx, span in enumerate(spans, start=1):
        tool = str(span.get("tool") or "unknown")
        argv_text = str(span.get("argv") or "")
        command = str(span.get("command") or shell_inner_command(tool, argv_text))
        category = classify_command(tool, argv_text or command)
        resource = _rollup_span_resources(
            proc_df,
            span,
            sampler_epoch,
            by_parent,
            descendants_cache,
        )
        source = str(span.get("source", "unknown"))
        enriched.append(
            {
                "span_id": f"span-{idx:05d}",
                "source": source,
                "kind": _span_kind(source, tool, argv_text or command),
                "tool": tool,
                "category": category,
                "argv": argv_text,
                "command": command,
                "pid": span.get("pid"),
                "start_ts": span.get("start_ts"),
                "end_ts": span.get("end_ts"),
                "start_s": resource["start_s"],
                "end_s": resource["end_s"],
                "duration_s": resource["duration_s"],
                "start_time_source": resource["start_time_source"],
                "end_time_source": resource["end_time_source"],
                "exit_code": span.get("exit_code"),
                "stdout_bytes": span.get("stdout_bytes"),
                "stderr_bytes": span.get("stderr_bytes"),
                "peak_pss": resource["peak_pss"],
                "peak_uss": resource["peak_uss"],
                "peak_rss": resource["peak_rss"],
                "peak_sampled_at": resource["peak_sampled_at"],
                "cpu_total_s": resource["cpu_total_s"],
                "sampled_processes": resource["sampled_processes"],
            }
        )
    _add_attribution_metadata(enriched, peak_ts)
    return enriched


def write_tool_spans(run_dir: Path) -> list[dict[str, Any]]:
    spans = derive_tool_spans(run_dir)
    out_path = run_dir / "tool_spans.jsonl"
    with out_path.open("w") as f:
        for span in spans:
            f.write(json.dumps(span) + "\n")
    return spans


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive behavioral tool spans for a run")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    spans = write_tool_spans(args.run_dir)
    print(f"Wrote {len(spans)} spans to {args.run_dir / 'tool_spans.jsonl'}")


if __name__ == "__main__":
    main()
