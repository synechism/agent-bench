"""Summarize a single run: join timeseries + exec/exit logs → per-category attribution.

Produces summary.json with:
- peak tree PSS, USS, RSS (sampled + kernel-peak if available)
- per-category breakdown (tool calling, test/build runners, agent runtime, ...)
- files_grepped count (derived from exec/shim logs)
- files_read count
- wall clock time
- API usage (if logged)

Category attribution logic:
  1. Load exec_log.jsonl → map every PID to a tool name and timing window
  2. Load proc_timeseries.parquet → for each sample tick, attribute each PID's
     PSS/USS to its category based on:
       - Is it a known tool binary? → "tool_calling" or "test_build_runner"
       - Is it the agent process itself? → "agent_runtime"
       - Is it a child of a tool? → inherited from parent tool category
       - Unknown? → "other"
  3. Sum across ticks → total consumption by category
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shlex
from collections import defaultdict
from datetime import UTC, datetime
from os.path import basename
from pathlib import Path


AGENT_PROCESS_NAMES = {"claude", "codex", "pi", "opencode", "node", "deno", "MainThread"}


def _classify_comm(comm: str) -> str:
    """Classify a process by its comm name (best-effort heuristic).

    These classifications are the starting point. The exec_log provides
    ground truth (actual argv) for exact tool identification.
    """
    test_build = {
        "pytest", "cargo", "make", "cmake", "gcc", "clang", "rustc",
        "go", "javac", "mvn", "gradle", "pip", "npm", "npx", "tsc",
        "eslint", "esbuild", "webpack", "jest", "vitest",
    }
    tools = {
        "rg", "grep", "cat", "head", "tail", "find", "git", "curl",
        "wget", "ls", "cp", "mv", "rm", "mkdir", "chmod", "awk", "sed",
        "sort", "uniq", "wc", "jq", "bash", "sh", "python", "python3",
        "node", "fd", "tree", "readlink", "stat", "diff",
    }
    agent_runtime = {
        "claude", "codex", "pi", "opencode", "node", "deno",
    }

    base = comm.lower().rstrip("0123456789-._")
    if base in test_build:
        return "test_build_runner"
    if base in tools:
        return "tool_calling"
    if base in agent_runtime:
        return "agent_runtime"
    return "other"


def _load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    if not path.exists():
        return records
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _load_manifest(run_dir: Path) -> dict:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text())
    except json.JSONDecodeError:
        return {}


def _shell_inner_command(argv: str) -> str:
    try:
        parts = shlex.split(argv)
    except ValueError:
        return argv

    for flag in ("-c", "-lc"):
        if flag in parts:
            idx = parts.index(flag)
            if idx + 1 < len(parts):
                return parts[idx + 1]
    return argv


def _tool_name_from_command(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    if not parts:
        return "unknown"
    return basename(parts[0])


def _parse_codex_transcript(run_dir: Path) -> list[dict]:
    """Recover shell commands from Codex's text transcript."""
    stderr_path = run_dir / "stderr.log"
    if not stderr_path.exists():
        return []

    events: list[dict] = []
    lines = stderr_path.read_text(errors="replace").splitlines()
    for idx, line in enumerate(lines[:-1]):
        if line.strip() != "exec":
            continue
        command_line = lines[idx + 1].strip()
        if " in " not in command_line:
            continue
        raw_command = command_line.split(" in ", 1)[0]
        inner_command = _shell_inner_command(raw_command)
        events.append(
            {
                "source": "codex_transcript",
                "tool": _tool_name_from_command(inner_command),
                "argv": inner_command,
                "raw": command_line,
            }
        )
    return events


def _parse_structured_tool_invocations(run_dir: Path) -> list[dict]:
    """Recover model-level tool calls from JSONL agent streams."""
    events: list[dict] = []
    for stream_name in ("stdout.log", "stderr.log"):
        path = run_dir / stream_name
        if not path.exists():
            continue
        for idx, line in enumerate(path.read_text(errors="replace").splitlines()):
            if not line.startswith("{"):
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            if rec.get("type") == "tool_execution_start":
                tool_name = str(rec.get("toolName") or "unknown")
                tool_args = rec.get("args") if isinstance(rec.get("args"), dict) else {}
                command = (
                    tool_args.get("command")
                    or tool_args.get("path")
                    or tool_args.get("pattern")
                    or tool_args.get("file_path")
                    or json.dumps(tool_args, sort_keys=True)
                )
                events.append(
                    {
                        "source": "pi_stream_tool",
                        "tool": tool_name,
                        "argv": str(command),
                        "raw": rec,
                        "stream": stream_name,
                        "line_index": idx,
                    }
                )
                continue

            message = rec.get("message")
            if isinstance(message, dict):
                for content in message.get("content") or []:
                    if not isinstance(content, dict) or content.get("type") != "tool_use":
                        continue
                    tool_name = str(content.get("name") or "unknown")
                    tool_input = content.get("input") if isinstance(content.get("input"), dict) else {}
                    command = tool_input.get("command") or tool_input.get("pattern") or tool_input.get("file_path") or ""
                    events.append(
                        {
                            "source": "claude_stream_tool",
                            "tool": tool_name,
                            "argv": str(command),
                            "raw": content,
                            "stream": stream_name,
                            "line_index": idx,
                        }
                    )

            item = rec.get("item")
            if not isinstance(item, dict) or rec.get("type") != "item.started":
                continue
            item_type = item.get("type")
            if item_type == "command_execution":
                command = str(item.get("command") or "")
                inner_command = _shell_inner_command(command)
                events.append(
                    {
                        "source": "codex_json_command",
                        "tool": _tool_name_from_command(inner_command),
                        "argv": inner_command,
                        "raw": item,
                        "stream": stream_name,
                        "line_index": idx,
                    }
                )
            elif item_type == "file_change":
                events.append(
                    {
                        "source": "codex_json_file_change",
                        "tool": "file_change",
                        "argv": "",
                        "raw": item,
                        "stream": stream_name,
                        "line_index": idx,
                    }
                )

    return events


def _parse_exec_log(run_dir: Path) -> list[dict]:
    events: list[dict] = []
    for rec in _load_jsonl(run_dir / "exec_log.jsonl"):
        tool = rec.get("tool")
        if not tool or "start" not in rec:
            continue
        events.append(
            {
                "source": rec.get("source", "exec_log"),
                "tool": tool,
                "argv": rec.get("argv", ""),
                "pid": rec.get("pid"),
                "ts": rec.get("start"),
            }
        )
    return events


_STRACE_EXEC_RE = re.compile(
    r'^\s*(?P<pid>\d+)\s+(?P<ts>\d+(?:\.\d+)?)\s+'
    r'execve\("(?P<exe>(?:\\.|[^"])*)",\s+(?P<argv>\[.*\]),\s+.*\)\s+=\s+(?P<result>.+)$'
)


def _decode_c_string(value: str) -> str:
    try:
        return ast.literal_eval(f'"{value}"')
    except (SyntaxError, ValueError):
        return value


def _parse_strace_exec(run_dir: Path) -> list[dict]:
    """Recover exact execve argv from a rootless strace wrapper."""
    path = run_dir / "strace_exec.log"
    if not path.exists():
        return []

    events: list[dict] = []
    for line in path.read_text(errors="replace").splitlines():
        match = _STRACE_EXEC_RE.match(line)
        if not match:
            continue
        if match.group("result").strip() != "0":
            continue

        exe = _decode_c_string(match.group("exe"))
        try:
            argv = ast.literal_eval(match.group("argv"))
        except (SyntaxError, ValueError):
            argv = [exe]
        if not isinstance(argv, list):
            argv = [exe]
        argv = [str(arg) for arg in argv]

        shell_command = _extract_claude_shell_command(argv)
        if shell_command:
            events.append(
                {
                    "source": "claude_shell_command",
                    "tool": _tool_name_from_command(shell_command),
                    "argv": shell_command,
                    "executable": exe,
                    "pid": int(match.group("pid")),
                    "ts": float(match.group("ts")),
                }
            )
            continue

        tool = basename(argv[0] if argv else exe)
        if tool in AGENT_PROCESS_NAMES or tool == "strace":
            continue
        if _is_strace_bootstrap_noise(run_dir, exe, argv):
            continue
        if _is_claude_internal_tool_exec(exe, argv):
            events.append(
                {
                    "source": "claude_internal_tool",
                    "tool": tool,
                    "argv": shlex.join(argv),
                    "executable": exe,
                    "pid": int(match.group("pid")),
                    "ts": float(match.group("ts")),
                }
            )
            continue

        events.append(
            {
                "source": "strace_execve",
                "tool": tool,
                "argv": shlex.join(argv),
                "executable": exe,
                "pid": int(match.group("pid")),
                "ts": float(match.group("ts")),
            }
        )
    return events


def _extract_claude_shell_command(argv: list[str]) -> str | None:
    """Extract the user command from Claude Code's shell wrapper, if present."""
    for arg in argv:
        match = re.search(r"(?:^|&& )eval (?P<command>.+?) < /dev/null", arg, re.S)
        if match:
            command = match.group("command").strip()
            try:
                decoded = ast.literal_eval(command)
            except (SyntaxError, ValueError):
                return command
            return decoded if isinstance(decoded, str) else command
    return None


def _is_claude_internal_tool_exec(exe: str, argv: list[str]) -> bool:
    if basename(exe) != "claude.exe" or not argv:
        return False
    tool = basename(str(argv[0]))
    if tool in AGENT_PROCESS_NAMES or tool == "claude.exe":
        return False
    return _classify_comm(tool) in {"tool_calling", "test_build_runner"}


def _is_strace_bootstrap_noise(run_dir: Path, exe: str, argv: list[str]) -> bool:
    run_dir_text = str(run_dir.resolve())
    if exe.startswith(f"{run_dir_text}/shims/"):
        return True
    joined = "\n".join([exe, *argv])
    noise_markers = (
        ".claude/shell-snapshots",
        ".oh-my-zsh",
        ".zcompdump",
        ".pyenv",
        "__pycache__",
        "CLAUDE_CODE_EXECPATH",
        "snapshot-zsh-",
    )
    return any(marker in joined for marker in noise_markers)


def _proc_observed_events(run_dir: Path) -> list[dict]:
    ts_path = run_dir / "proc_timeseries.parquet"
    if not ts_path.exists():
        ts_path = run_dir / "proc_timeseries.csv"
    if not ts_path.exists():
        return []

    import pandas as pd

    df = pd.read_parquet(ts_path) if ts_path.suffix == ".parquet" else pd.read_csv(ts_path)
    if df.empty:
        return []

    events: list[dict] = []
    grouped = df.groupby(["pid", "comm"], as_index=False).agg(
        first_seen_s=("ts", "min"),
        last_seen_s=("ts", "max"),
        peak_pss=("pss", "max"),
        peak_uss=("uss", "max"),
    )
    for rec in grouped.to_dict(orient="records"):
        comm = str(rec["comm"])
        if comm in AGENT_PROCESS_NAMES:
            continue
        category = _classify_comm(comm)
        if category not in {"tool_calling", "test_build_runner"}:
            continue
        events.append(
            {
                "source": "proc_observed",
                "tool": comm,
                "pid": int(rec["pid"]),
                "first_seen_s": float(rec["first_seen_s"]),
                "last_seen_s": float(rec["last_seen_s"]),
                "peak_pss": int(rec["peak_pss"]),
                "peak_uss": int(rec["peak_uss"]),
                "category": category,
            }
        )
    return events


def derive_tool_events(run_dir: Path) -> list[dict]:
    """Return best-available tool events for non-root and shimmed runs."""
    events = []
    events.extend(_parse_structured_tool_invocations(run_dir))
    events.extend(_parse_exec_log(run_dir))
    events.extend(_parse_codex_transcript(run_dir))
    events.extend(_parse_strace_exec(run_dir))
    events.extend(_proc_observed_events(run_dir))
    return events


def write_tool_events(run_dir: Path) -> list[dict]:
    events = derive_tool_events(run_dir)
    out_path = run_dir / "tool_events.jsonl"
    with out_path.open("w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    return events


def _extract_stdout(run_dir: Path) -> str:
    path = run_dir / "stdout.log"
    if not path.exists():
        return ""
    return path.read_text(errors="replace")


def _classify_outcome(manifest: dict, events: list[dict], exit_code: int | None, stdout: str) -> dict:
    event_names = {event.get("event") for event in events}
    run_end = next((event for event in reversed(events) if event.get("event") == "run_end"), {})
    timed_out = bool(run_end.get("timed_out", False))
    setup_ok = bool(
        {"codebase_checkout_end", "codebase_builtin_created", "codebase_reused"} & event_names
    )
    agent_started = "agent_started" in event_names

    failure_phase = None
    if not setup_ok:
        failure_phase = "setup_checkout"
    elif not agent_started:
        failure_phase = "agent_start"
    elif timed_out:
        failure_phase = "timeout"
    elif exit_code not in (None, 0):
        failure_phase = "agent_execution"

    oracle = manifest.get("task", {}).get("oracle", {})
    expected_text = oracle.get("expected_text")
    if expected_text:
        oracle_success = expected_text in stdout
    elif "pass_exit_code" in oracle:
        oracle_success = exit_code == oracle["pass_exit_code"]
    else:
        oracle_success = None

    task_success = exit_code == 0 and (oracle_success is not False)
    return {
        "setup_ok": setup_ok,
        "agent_started": agent_started,
        "agent_exit_code": exit_code,
        "timed_out": timed_out,
        "failure_phase": failure_phase,
        "oracle_success": oracle_success,
        "task_success": task_success,
    }


def _count_unique_file_args(events: list[dict]) -> int:
    file_reading_tools = {"rg", "grep", "cat", "head", "tail", "read", "fd", "sed"}
    seen_files: set[str] = set()
    for rec in events:
        tool = rec.get("tool", "")
        argv = rec.get("argv", "")
        if tool not in file_reading_tools or not argv:
            continue
        try:
            args = shlex.split(argv)
        except ValueError:
            args = argv.split()
        for arg in args[1:]:
            if arg and not arg.startswith("-") and not any(ch in arg for ch in "*[]{}|;$"):
                seen_files.add(arg)
    return len(seen_files)


def summarize_run(run_dir: Path) -> dict:
    """Produce per-category attribution for a single run."""
    summary: dict = {
        "run_id": run_dir.name,
        "peak_tree_pss": 0,
        "peak_tree_uss": 0,
        "peak_tree_rss": 0,
        "peak_sampled_at": None,
        "categories": defaultdict(lambda: {"peak_pss": 0, "peak_uss": 0, "total_cpu_s": 0.0}),
        "files_grepped": 0,
        "files_read": 0,
        "tool_invocations": 0,
        "wall_time_s": 0,
        "api_usage": {},
        "outcome": {},
        "tool_events": {
            "total": 0,
            "exact_invocations": 0,
            "observed_subprocesses": 0,
            "by_source": {},
            "by_tool": {},
        },
    }

    # Load manifest
    manifest = _load_manifest(run_dir)
    if manifest:
        summary["manifest"] = manifest

    # Load proc timeseries
    ts_path = run_dir / "proc_timeseries.parquet"
    if not ts_path.exists():
        ts_path = run_dir / "proc_timeseries.csv"

    if ts_path.exists():
        import pandas as pd
        if ts_path.suffix == ".parquet":
            df = pd.read_parquet(ts_path)
        else:
            df = pd.read_csv(ts_path)

        if not df.empty:
            # Per-tick tree totals
            ticks = df.groupby("ts").agg(
                total_pss=("pss", "sum"),
                total_uss=("uss", "sum"),
                total_rss=("rss", "sum"),
            ).reset_index()

            summary["peak_tree_pss"] = int(ticks["total_pss"].max())
            summary["peak_tree_uss"] = int(ticks["total_uss"].max())
            summary["peak_tree_rss"] = int(ticks["total_rss"].max())
            peak_row = ticks.loc[ticks["total_pss"].idxmax()]
            summary["peak_sampled_at"] = float(peak_row["ts"])

            if "ts" in df.columns and df["ts"].nunique() > 1:
                summary["wall_time_s"] = round(df["ts"].max() - df["ts"].min(), 1)

            # Per-category breakdown
            df["category"] = df["comm"].apply(_classify_comm)

            for cat, group in df.groupby("category"):
                tick_totals = group.groupby("ts").agg(
                    total_pss=("pss", "sum"),
                    total_uss=("uss", "sum"),
                )
                summary["categories"][cat] = {
                    "peak_pss": int(tick_totals["total_pss"].max()) if not tick_totals.empty else 0,
                    "peak_uss": int(tick_totals["total_uss"].max()) if not tick_totals.empty else 0,
                }

    tool_events = write_tool_events(run_dir)
    by_source: dict[str, int] = defaultdict(int)
    by_tool: dict[str, int] = defaultdict(int)
    high_level_exact_sources = {
        "codex_transcript",
        "codex_json_command",
        "codex_json_file_change",
        "claude_stream_tool",
        "claude_internal_tool",
        "claude_shell_command",
        "pi_stream_tool",
    }
    exact_subprocess_sources = {"shim", "execsnoop", "strace_execve"}
    exact_invocations = 0
    exact_subprocesses = 0
    exact_execve_subprocesses = 0
    observed_subprocesses = 0
    for event in tool_events:
        source = event.get("source", "unknown")
        tool = event.get("tool", "unknown")
        by_source[source] += 1
        by_tool[tool] += 1
        if source in high_level_exact_sources:
            exact_invocations += 1
        elif source in exact_subprocess_sources:
            exact_subprocesses += 1
        if source in {"claude_internal_tool", "strace_execve"}:
            exact_execve_subprocesses += 1
        elif source == "proc_observed":
            observed_subprocesses += 1

    summary["tool_invocations"] = exact_invocations
    summary["files_grepped"] = _count_unique_file_args(tool_events)
    summary["tool_events"] = {
        "total": len(tool_events),
        "exact_invocations": exact_invocations,
        "exact_subprocesses": exact_subprocesses,
        "exact_execve_subprocesses": exact_execve_subprocesses,
        "observed_subprocesses": observed_subprocesses,
        "by_source": dict(sorted(by_source.items())),
        "by_tool": dict(sorted(by_tool.items())),
    }

    try:
        from analysis.decision_trace import write_decision_trace
        from analysis.hotspots import write_hotspots
        from analysis.tool_spans import write_tool_spans

        tool_spans = write_tool_spans(run_dir)
        hotspots = write_hotspots(run_dir, tool_spans)
        decision_trace = write_decision_trace(run_dir, tool_spans)
        summary["behavior"] = {
            "tool_span_count": len(tool_spans),
            "top_memory_spans": hotspots.get("top_memory_spans", [])[:5],
            "top_non_agent_memory_spans": hotspots.get("top_non_agent_memory_spans", [])[:5],
            "top_high_confidence_non_agent_memory_spans": hotspots.get(
                "top_high_confidence_non_agent_memory_spans", []
            )[:5],
            "top_wall_time_spans": hotspots.get("top_wall_time_spans", [])[:5],
            "run_peak": hotspots.get("run_peak", {}),
            "behavior_summary": hotspots.get("behavior", {}),
            "derived_metrics": hotspots.get("derived_metrics", {}),
            "decision_trace": decision_trace,
        }
    except Exception as exc:
        summary["behavior"] = {"error": str(exc)}

    # Load API usage
    api_path = run_dir / "api_usage.json"
    if api_path.exists():
        with open(api_path) as f:
            summary["api_usage"] = json.load(f)

    agent_context_path = run_dir / "agent_context.json"
    if agent_context_path.exists():
        try:
            context = json.loads(agent_context_path.read_text())
            summary["agent_context"] = {
                "available_counts": context.get("available_counts", context.get("loaded_counts", {})),
                "loaded_counts": context.get("loaded_counts", {}),
                "load_observability": context.get("load_observability", {}),
                "project_instruction_files": context.get("project_instruction_files", []),
                "prompt_reference": context.get("prompt_reference"),
                "versions": context.get("versions", []),
            }
        except json.JSONDecodeError:
            summary["agent_context"] = {"error": "invalid_json"}

    events = _load_jsonl(run_dir / "events.jsonl")
    if events:
        summary["events"] = events

    exit_code = None
    if events:
        run_end = next((event for event in reversed(events) if event.get("event") == "run_end"), {})
        if "exit_code" in run_end:
            exit_code = run_end["exit_code"]
    stdout = _extract_stdout(run_dir)
    summary["outcome"] = _classify_outcome(manifest, events, exit_code, stdout)
    summary["exit_code"] = exit_code

    # Convert defaultdicts for JSON
    summary["categories"] = dict(summary["categories"])
    summary["summarized_at"] = datetime.now(UTC).isoformat()

    return summary


def main() -> None:
    p = argparse.ArgumentParser(description="Summarize a single benchmark run")
    p.add_argument("run_dir", type=Path, help="Path to runs/<run_id>/")
    p.add_argument("--output", "-o", type=Path, default=None,
                   help="Output path (default: <run_dir>/summary.json)")
    args = p.parse_args()

    summary = summarize_run(args.run_dir)
    output = args.output or (args.run_dir / "summary.json")
    with open(output, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Summary written to {output}")
    print(f"  Peak tree PSS: {summary['peak_tree_pss'] / 1024 / 1024:.1f} MB")
    print(f"  Peak tree USS: {summary['peak_tree_uss'] / 1024 / 1024:.1f} MB")
    print(f"  Files grepped: {summary['files_grepped']}")
    print(f"  Tool invocations: {summary['tool_invocations']}")
    for cat, data in summary["categories"].items():
        print(f"  {cat}: peak PSS={data['peak_pss'] / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
