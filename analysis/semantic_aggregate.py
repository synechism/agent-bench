"""Aggregate semantic context metrics across runs.

This is the cross-run layer for semantic memory work. Per-run artifacts answer
"what was in this prompt?"; this script answers "what patterns do we see across
task types?"
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(errors="replace"))
    except json.JSONDecodeError:
        return {}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _bytes_to_mb(value: int | float | None) -> float:
    return round(float(value or 0) / 1024 / 1024, 1)


def _task_success(summary: dict[str, Any]) -> bool | None:
    outcome = summary.get("outcome") or {}
    if "task_success" in outcome:
        return bool(outcome["task_success"])
    if "exit_code" in summary:
        return summary.get("exit_code") == 0
    return None


def _max_delta_request(timeline: list[dict[str, Any]], layer: str) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_delta = 0
    for rec in timeline:
        deltas = rec.get("semantic_layer_delta_chars") or {}
        delta = int(deltas.get(layer) or 0)
        if delta > best_delta:
            best_delta = delta
            best = rec
    return best


def _top_outputs(summary: dict[str, Any], limit: int = 5) -> list[str]:
    outputs = summary.get("largest_tool_outputs_at_max_body_request") or []
    labels: list[str] = []
    for item in outputs[:limit]:
        command = item.get("call_capture")
        if isinstance(command, str):
            command = command.replace("\n", " ")
        label = command or str(item.get("tool_name") or "unknown")
        labels.append(f"{int(item.get('output_chars') or 0)} chars: {label[:180]}")
    return labels


def _row_for_run(run_dir: Path) -> dict[str, Any] | None:
    summary = _load_json(run_dir / "summary.json")
    semantic = _load_json(run_dir / "semantic_context_summary.json")
    if not summary or not semantic:
        return None

    manifest = summary.get("manifest") or {}
    task = manifest.get("task") or {}
    behavior = summary.get("behavior") or {}
    run_peak = (behavior.get("run_peak") or {}) if isinstance(behavior, dict) else {}
    agent_isolated = (
        behavior.get("run_peak_agent_isolated") if isinstance(behavior, dict) else None
    ) or _load_json(run_dir / "resource_hotspots.json").get("run_peak_agent_isolated") or {}
    max_req = semantic.get("max_semantic_request") or {}
    max_body = semantic.get("max_body_request") or {}
    memory_vs_static = max_req.get("memory_vs_static") or {}
    layers = max_req.get("semantic_layer_chars") or {}
    timeline = _load_jsonl(run_dir / "semantic_context_timeline.jsonl")
    tool_output_growth = _max_delta_request(timeline, "tool_output_memory")
    total_growth = max(0, int(max_req.get("semantic_total_chars") or 0) - int((timeline[0] if timeline else {}).get("semantic_total_chars") or 0))

    return {
        "run_id": run_dir.name,
        "agent": manifest.get("agent"),
        "task_kind": task.get("kind"),
        "task": task.get("name"),
        "codebase": task.get("codebase"),
        "success": _task_success(summary),
        "exit_code": summary.get("exit_code"),
        "wall_time_s": summary.get("wall_time_s"),
        "tool_invocations": summary.get("tool_invocations"),
        "api_requests": semantic.get("request_count"),
        "window_count": len(semantic.get("window_ids") or {}),
        "compaction_seen": any(
            str(kind).lower().startswith("compact")
            for kind in (semantic.get("request_kinds") or {}).keys()
        ),
        "capture_present": semantic.get("capture_present"),
        "full_peak_pss_mb": _bytes_to_mb(summary.get("peak_tree_pss")),
        "agent_isolated_peak_pss_mb": _bytes_to_mb(agent_isolated.get("peak_tree_pss")),
        "max_body_approx_tokens": max_body.get("body_approx_tokens"),
        "max_semantic_approx_tokens": max_req.get("semantic_total_approx_tokens"),
        "max_semantic_chars": max_req.get("semantic_total_chars"),
        "static_prompt_chars": memory_vs_static.get("static_prompt_chars"),
        "carried_memory_chars": memory_vs_static.get("carried_memory_chars"),
        "file_or_tool_output_chars": memory_vs_static.get("file_or_tool_output_chars"),
        "assistant_reasoning_chars": memory_vs_static.get("assistant_reasoning_chars"),
        "base_instructions_chars": layers.get("base_instructions"),
        "tool_schema_chars": layers.get("tool_schema"),
        "developer_context_chars": layers.get("developer_context"),
        "user_or_task_chars": layers.get("user_or_task"),
        "tool_call_memory_chars": layers.get("tool_call_memory"),
        "tool_output_memory_chars": layers.get("tool_output_memory"),
        "semantic_growth_chars": total_growth,
        "max_tool_output_delta_request": (
            tool_output_growth.get("request_index") if tool_output_growth else None
        ),
        "max_tool_output_delta_chars": (
            (tool_output_growth.get("semantic_layer_delta_chars") or {}).get("tool_output_memory")
            if tool_output_growth
            else None
        ),
        "largest_retained_tool_outputs": _top_outputs(semantic),
        "prompt_payload_report": str(run_dir / "prompt_payload_report.md")
        if (run_dir / "prompt_payload_report.md").exists()
        else None,
    }


def collect_rows(run_dirs: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run_dir in sorted(run_dirs):
        if not run_dir.is_dir():
            continue
        row = _row_for_run(run_dir)
        if row:
            rows.append(row)
    return rows


def _numeric_stats(values: list[float]) -> dict[str, float]:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return {"count": 0, "median": 0, "max": 0, "min": 0}
    return {
        "count": len(clean),
        "median": median(clean),
        "max": max(clean),
        "min": min(clean),
    }


def build_rollups(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[f"{row.get('agent')}|{row.get('task_kind')}|{row.get('task')}"].append(row)

    rollups: dict[str, Any] = {}
    metrics = [
        "api_requests",
        "tool_invocations",
        "full_peak_pss_mb",
        "agent_isolated_peak_pss_mb",
        "max_semantic_approx_tokens",
        "static_prompt_chars",
        "carried_memory_chars",
        "file_or_tool_output_chars",
        "semantic_growth_chars",
    ]
    for key, group in sorted(groups.items()):
        rollups[key] = {
            "runs": len(group),
            "successes": sum(1 for row in group if row.get("success") is True),
            "metrics": {
                metric: _numeric_stats([row.get(metric) for row in group])
                for metric in metrics
            },
            "run_ids": [row["run_id"] for row in group],
        }
    return rollups


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        path.write_text("")
        return
    fieldnames = [
        "run_id",
        "agent",
        "task_kind",
        "task",
        "codebase",
        "success",
        "wall_time_s",
        "api_requests",
        "tool_invocations",
        "window_count",
        "compaction_seen",
        "capture_present",
        "full_peak_pss_mb",
        "agent_isolated_peak_pss_mb",
        "max_semantic_approx_tokens",
        "static_prompt_chars",
        "carried_memory_chars",
        "file_or_tool_output_chars",
        "assistant_reasoning_chars",
        "semantic_growth_chars",
        "base_instructions_chars",
        "tool_schema_chars",
        "tool_call_memory_chars",
        "tool_output_memory_chars",
        "max_tool_output_delta_request",
        "max_tool_output_delta_chars",
        "prompt_payload_report",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _md_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| run | task | ok | reqs | tools | max semantic toks | static chars | carried chars | file/tool chars | isolated MB | compaction |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{row['run_id']}`",
                    f"{row.get('task_kind')}/{row.get('task')}",
                    str(row.get("success")),
                    str(row.get("api_requests")),
                    str(row.get("tool_invocations")),
                    str(row.get("max_semantic_approx_tokens")),
                    str(row.get("static_prompt_chars")),
                    str(row.get("carried_memory_chars")),
                    str(row.get("file_or_tool_output_chars")),
                    str(row.get("agent_isolated_peak_pss_mb")),
                    str(row.get("compaction_seen")),
                ]
            )
            + " |"
        )
    return lines


def _write_markdown(rows: list[dict[str, Any]], rollups: dict[str, Any], path: Path) -> None:
    lines: list[str] = []
    lines.append("# Semantic Context Aggregate")
    lines.append("")
    lines.append("This report aggregates semantic context-window measurements across runs.")
    lines.append("")
    lines.append(f"- Runs included: {len(rows)}")
    lines.append("")
    if rows:
        lines.extend(_md_table(rows))
        lines.append("")

    lines.append("## Rollups")
    lines.append("")
    for key, rollup in rollups.items():
        lines.append(f"### `{key}`")
        lines.append("")
        lines.append(f"- runs: {rollup['runs']}; successes: {rollup['successes']}")
        metric_bits = []
        for metric, stats in rollup["metrics"].items():
            if not stats.get("count"):
                continue
            metric_bits.append(f"{metric}: median {stats['median']:.1f}, max {stats['max']:.1f}")
        lines.append(f"- {', '.join(metric_bits)}")
        lines.append(f"- run ids: `{', '.join(rollup['run_ids'])}`")
        lines.append("")

    lines.append("## Largest Retained Tool Outputs")
    lines.append("")
    for row in rows:
        outputs = row.get("largest_retained_tool_outputs") or []
        if not outputs:
            continue
        lines.append(f"### `{row['run_id']}`")
        lines.append("")
        for output in outputs:
            lines.append(f"- {output}")
        if row.get("prompt_payload_report"):
            lines.append(f"- prompt report: `{row['prompt_payload_report']}`")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def write_semantic_aggregate(run_dirs: list[Path], output_prefix: Path) -> dict[str, Any]:
    rows = collect_rows(run_dirs)
    rollups = build_rollups(rows)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    json_path = output_prefix.with_suffix(".json")
    csv_path = output_prefix.with_suffix(".csv")
    md_path = output_prefix.with_suffix(".md")

    json_path.write_text(
        json.dumps({"runs": rows, "rollups": rollups}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_csv(rows, csv_path)
    _write_markdown(rows, rollups, md_path)

    return {
        "run_count": len(rows),
        "json": str(json_path),
        "csv": str(csv_path),
        "markdown": str(md_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate semantic context metrics")
    parser.add_argument(
        "run_dirs",
        nargs="*",
        type=Path,
        help="Run directories. Defaults to all runs/* directories with semantic artifacts.",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=Path("runs"),
        help="Runs directory used when no explicit run dirs are provided.",
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=Path("docs/semantic_memory/semantic_context_aggregate"),
        help="Output prefix; .json/.csv/.md are written.",
    )
    args = parser.parse_args()

    run_dirs = args.run_dirs
    if not run_dirs:
        run_dirs = [
            path.parent
            for path in sorted(args.runs_dir.glob("*/semantic_context_summary.json"))
        ]

    result = write_semantic_aggregate(run_dirs, args.output_prefix)
    print(f"Wrote semantic aggregate for {result['run_count']} runs")
    print(f"  json: {result['json']}")
    print(f"  csv: {result['csv']}")
    print(f"  markdown: {result['markdown']}")


if __name__ == "__main__":
    main()
