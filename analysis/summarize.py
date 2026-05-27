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
import json
from collections import defaultdict
from pathlib import Path


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
    }

    # Load manifest
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path) as f:
            summary["manifest"] = json.load(f)

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

    # Derive files_grepped from exec log
    exec_log = run_dir / "exec_log.jsonl"
    if exec_log.exists():
        seen_files: set[str] = set()
        tool_count = 0
        file_reading_tools = {"rg", "grep", "cat", "head", "tail", "read", "fd"}

        for line in exec_log.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            tool = rec.get("tool", "")
            if tool:
                tool_count += 1
                if tool in file_reading_tools and "argv" in rec:
                    # argv is a string of space-separated args; extract file paths
                    args = rec["argv"].split()
                    for arg in args:
                        if arg and not arg.startswith("-"):
                            seen_files.add(arg)

        summary["tool_invocations"] = tool_count // 2  # start + end entries
        summary["files_grepped"] = len(seen_files)

    # Load API usage
    api_path = run_dir / "api_usage.json"
    if api_path.exists():
        with open(api_path) as f:
            summary["api_usage"] = json.load(f)

    # Load events
    events_path = run_dir / "events.jsonl"
    if events_path.exists():
        events = []
        for line in events_path.read_text().splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        summary["events"] = events

    # Convert defaultdicts for JSON
    summary["categories"] = dict(summary["categories"])

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
