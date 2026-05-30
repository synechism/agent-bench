"""Build behavioral hotspot summaries from derived tool spans."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from analysis.behavior_metrics import write_behavior_metrics
from analysis.tool_spans import load_jsonl, write_tool_spans


def _load_proc(run_dir: Path):
    ts_path = run_dir / "proc_timeseries.parquet"
    if not ts_path.exists():
        ts_path = run_dir / "proc_timeseries.csv"
    if not ts_path.exists():
        return None

    import pandas as pd

    return pd.read_parquet(ts_path) if ts_path.suffix == ".parquet" else pd.read_csv(ts_path)


def _mb(value: int | float | None) -> float:
    return round(float(value or 0) / 1024 / 1024, 1)


def _short_span(span: dict[str, Any]) -> dict[str, Any]:
    return {
        "span_id": span.get("span_id"),
        "source": span.get("source"),
        "kind": span.get("kind"),
        "span_role": span.get("span_role"),
        "tool": span.get("tool"),
        "category": span.get("category"),
        "attribution_confidence": span.get("attribution_confidence"),
        "possible_over_attribution": span.get("possible_over_attribution", False),
        "active_at_peak": span.get("active_at_peak", False),
        "includes_descendants": span.get("includes_descendants", False),
        "is_nested_parent": span.get("is_nested_parent", False),
        "overlapping_inner_span_count": span.get("overlapping_inner_span_count", 0),
        "command": span.get("command"),
        "pid": span.get("pid"),
        "start_s": span.get("start_s"),
        "duration_s": span.get("duration_s"),
        "exit_code": span.get("exit_code"),
        "peak_pss": span.get("peak_pss", 0),
        "peak_pss_mb": _mb(span.get("peak_pss")),
        "cpu_total_s": span.get("cpu_total_s", 0),
        "sampled_processes": span.get("sampled_processes", 0),
    }


def _top_spans(spans: list[dict[str, Any]], metric: str, limit: int = 10) -> list[dict[str, Any]]:
    ranked = sorted(spans, key=lambda span: float(span.get(metric) or 0), reverse=True)
    return [_short_span(span) for span in ranked[:limit] if float(span.get(metric) or 0) > 0]


def _non_agent_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        span for span in spans
        if span.get("category") != "agent_runtime" and span.get("kind") != "agent_process"
    ]


def _high_confidence_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [span for span in spans if span.get("attribution_confidence") == "high"]


def _run_peak(run_dir: Path, spans: list[dict[str, Any]]) -> dict[str, Any]:
    df = _load_proc(run_dir)
    if df is None or df.empty:
        return {}

    ticks = df.groupby("ts").agg(
        total_pss=("pss", "sum"),
        total_uss=("uss", "sum"),
        total_rss=("rss", "sum"),
    )
    peak_ts = float(ticks["total_pss"].idxmax())
    peak_pss = int(ticks.loc[peak_ts]["total_pss"])
    peak_rows = df[df["ts"] == peak_ts].copy()
    peak_processes = []
    for rec in peak_rows.sort_values("pss", ascending=False).head(15).to_dict(orient="records"):
        peak_processes.append(
            {
                "pid": int(rec["pid"]),
                "ppid": int(rec["ppid"]),
                "comm": str(rec["comm"]),
                "pss": int(rec["pss"]),
                "pss_mb": _mb(rec["pss"]),
                "uss": int(rec["uss"]),
                "rss": int(rec["rss"]),
                "num_threads": int(rec["num_threads"]),
            }
        )

    active_spans = []
    for span in spans:
        start = span.get("start_s")
        end = span.get("end_s")
        if start is None:
            continue
        if float(start) - 0.05 <= peak_ts and (end is None or peak_ts <= float(end) + 0.05):
            active_spans.append(span)
    active_spans = sorted(active_spans, key=lambda span: int(span.get("peak_pss") or 0), reverse=True)

    category_pss: dict[str, int] = defaultdict(int)
    for span in active_spans:
        category_pss[str(span.get("category", "unknown"))] += int(span.get("peak_pss") or 0)

    return {
        "peak_sampled_at": peak_ts,
        "peak_tree_pss": peak_pss,
        "peak_tree_pss_mb": _mb(peak_pss),
        "active_spans": [_short_span(span) for span in active_spans[:10]],
        "active_categories_by_span_peak_pss": {
            key: {"peak_pss": value, "peak_pss_mb": _mb(value)}
            for key, value in sorted(category_pss.items(), key=lambda item: item[1], reverse=True)
        },
        "top_processes_at_peak": peak_processes,
    }


def _behavior_summary(spans: list[dict[str, Any]]) -> dict[str, Any]:
    by_category = Counter(str(span.get("category", "unknown")) for span in spans)
    by_role = Counter(str(span.get("span_role", "unknown")) for span in spans)
    by_tool = Counter(str(span.get("tool", "unknown")) for span in spans)
    by_confidence = Counter(str(span.get("attribution_confidence", "unknown")) for span in spans)
    high_level = [span for span in spans if span.get("kind") == "high_level_tool"]
    subprocesses = [span for span in spans if span.get("kind") == "subprocess"]
    over_attributed = [span for span in spans if span.get("possible_over_attribution")]
    active_at_peak = [span for span in spans if span.get("active_at_peak")]

    commands_by_category: dict[str, Counter[str]] = defaultdict(Counter)
    for span in spans:
        category = str(span.get("category", "unknown"))
        command = str(span.get("command") or span.get("argv") or span.get("tool") or "")
        if command:
            commands_by_category[category][command] += 1

    duplicates = []
    for category, commands in commands_by_category.items():
        for command, count in commands.most_common():
            if count <= 1:
                continue
            duplicates.append({"category": category, "command": command, "count": count})

    first_edit = next(
        (span for span in sorted(spans, key=lambda s: float(s.get("start_s") or 1e18))
         if span.get("category") == "edit"),
        None,
    )
    first_test = next(
        (span for span in sorted(spans, key=lambda s: float(s.get("start_s") or 1e18))
         if span.get("category") == "test"),
        None,
    )

    return {
        "span_count": len(spans),
        "high_level_tool_count": len(high_level),
        "subprocess_span_count": len(subprocesses),
        "subprocess_fanout_per_high_level": (
            round(len(subprocesses) / len(high_level), 2) if high_level else None
        ),
        "by_category": dict(sorted(by_category.items())),
        "by_role": dict(sorted(by_role.items())),
        "by_attribution_confidence": dict(sorted(by_confidence.items())),
        "by_tool": dict(by_tool.most_common(25)),
        "possible_over_attribution_count": len(over_attributed),
        "active_at_peak_count": len(active_at_peak),
        "duplicate_commands": duplicates[:25],
        "first_edit": _short_span(first_edit) if first_edit else None,
        "first_test": _short_span(first_test) if first_test else None,
        "failed_spans": [
            _short_span(span)
            for span in spans
            if span.get("exit_code") not in (None, 0)
        ][:25],
    }


def build_hotspots(run_dir: Path, spans: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if spans is None:
        span_path = run_dir / "tool_spans.jsonl"
        spans = load_jsonl(span_path) if span_path.exists() else write_tool_spans(run_dir)

    summary = {
        "run_id": run_dir.name,
        "run_peak": _run_peak(run_dir, spans),
        "top_memory_spans": _top_spans(spans, "peak_pss"),
        "top_non_agent_memory_spans": _top_spans(_non_agent_spans(spans), "peak_pss"),
        "top_high_confidence_non_agent_memory_spans": _top_spans(
            _high_confidence_spans(_non_agent_spans(spans)),
            "peak_pss",
        ),
        "top_wall_time_spans": _top_spans(spans, "duration_s"),
        "top_cpu_spans": _top_spans(spans, "cpu_total_s"),
        "top_fanout_spans": _top_spans(spans, "sampled_processes"),
        "behavior": _behavior_summary(spans),
        "derived_metrics": write_behavior_metrics(run_dir, spans),
    }
    return summary


def write_hotspots(run_dir: Path, spans: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    summary = build_hotspots(run_dir, spans)
    with (run_dir / "resource_hotspots.json").open("w") as f:
        json.dump(summary, f, indent=2)

    phase_summary: dict[str, dict[str, Any]] = {}
    for span in spans or load_jsonl(run_dir / "tool_spans.jsonl"):
        phase = str(span.get("category", "unknown"))
        rec = phase_summary.setdefault(
            phase,
            {
                "span_count": 0,
                "peak_pss": 0,
                "wall_time_s": 0.0,
                "cpu_total_s": 0.0,
                "confidence_counts": {},
                "possible_over_attribution_count": 0,
            },
        )
        rec["span_count"] += 1
        rec["peak_pss"] = max(int(rec["peak_pss"]), int(span.get("peak_pss") or 0))
        rec["wall_time_s"] += float(span.get("duration_s") or 0)
        rec["cpu_total_s"] += float(span.get("cpu_total_s") or 0)
        confidence = str(span.get("attribution_confidence", "unknown"))
        rec["confidence_counts"][confidence] = rec["confidence_counts"].get(confidence, 0) + 1
        if span.get("possible_over_attribution"):
            rec["possible_over_attribution_count"] += 1
    for rec in phase_summary.values():
        rec["peak_pss_mb"] = _mb(rec["peak_pss"])
        rec["wall_time_s"] = round(float(rec["wall_time_s"]), 3)
        rec["cpu_total_s"] = round(float(rec["cpu_total_s"]), 3)

    with (run_dir / "phase_summary.json").open("w") as f:
        json.dump(dict(sorted(phase_summary.items())), f, indent=2)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build behavioral hotspot summaries")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    spans = write_tool_spans(args.run_dir)
    summary = write_hotspots(args.run_dir, spans)
    print(f"Wrote {len(spans)} spans to {args.run_dir / 'tool_spans.jsonl'}")
    print(f"Wrote hotspots to {args.run_dir / 'resource_hotspots.json'}")
    peak = summary.get("run_peak", {})
    if peak:
        print(f"Peak tree PSS: {peak.get('peak_tree_pss_mb')} MB at {peak.get('peak_sampled_at')}s")


if __name__ == "__main__":
    main()
