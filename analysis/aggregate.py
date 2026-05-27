"""Aggregate N runs → distributions + per-category attribution charts.

Input: runs/ directory with N subdirectories (each with summary.json).
Output:
  - aggregate.json: median, p90, max per (agent × task × modality) cell
  - charts/ (if matplotlib available): distribution plots, category breakdowns
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from math import ceil
from pathlib import Path
from statistics import median
from typing import Any


METRIC_NAMES = (
    "peak_tree_pss",
    "peak_tree_uss",
    "peak_tree_rss",
    "wall_time_s",
    "files_grepped",
    "tool_invocations",
    "observed_subprocesses",
)

BASELINE_ADJUSTED_METRICS = (
    "peak_tree_pss",
    "peak_tree_uss",
    "peak_tree_rss",
    "wall_time_s",
)


def load_all_summaries(runs_dir: Path) -> list[dict]:
    summaries = []
    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        summary_path = run_dir / "summary.json"
        if summary_path.exists():
            with open(summary_path) as f:
                summaries.append(json.load(f))
    return summaries


def group_by_cell(summaries: list[dict]) -> dict[str, list[dict]]:
    """Group summaries by (agent, task, codebase, memory_cap) key."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for s in summaries:
        m = s.get("manifest", {})
        agent = m.get("agent", "unknown")
        task = m.get("task", {}).get("name", "unknown")
        codebase = m.get("codebase", {}).get("repo_url", "unknown").split("/")[-1]
        cap = m.get("caps", {}).get("memory_mb") or "nocap"
        key = f"{agent}|{task}|{codebase}|{cap}"
        groups[key].append(s)
    return dict(groups)


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"median": 0, "p90": 0, "max": 0, "min": 0, "count": 0}
    sv = sorted(values)
    n = len(sv)
    return {
        "median": float(median(sv)),
        "p90": sv[min(n - 1, max(0, ceil(n * 0.9) - 1))],
        "max": sv[-1],
        "min": sv[0],
        "count": n,
    }


def _cap_key(summary: dict) -> str:
    cap = summary.get("manifest", {}).get("caps", {}).get("memory_mb")
    return str(cap or "nocap")


def _agent_key(summary: dict) -> str:
    return str(summary.get("manifest", {}).get("agent", "unknown"))


def _task_kind(summary: dict) -> str:
    return str(summary.get("manifest", {}).get("task", {}).get("kind", ""))


def _task_name(summary: dict) -> str:
    return str(summary.get("manifest", {}).get("task", {}).get("name", "unknown"))


def _is_baseline_summary(summary: dict) -> bool:
    task_name = _task_name(summary)
    codebase = summary.get("manifest", {}).get("task", {}).get("codebase")
    return (
        _task_kind(summary) == "baseline"
        or task_name in {"empty_baseline", "empty_task"}
        or codebase == "empty_baseline"
    )


def _summary_success(summary: dict) -> bool:
    outcome = summary.get("outcome") or {}
    if "task_success" in outcome:
        return bool(outcome["task_success"])
    exit_code = summary.get("exit_code")
    return exit_code == 0


def build_baseline_map(summaries: list[dict]) -> dict[tuple[str, str], dict[str, Any]]:
    """Index successful empty-task baselines by (agent, memory_cap)."""
    candidates: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    run_ids: dict[tuple[str, str], list[str]] = defaultdict(list)

    for summary in summaries:
        if not _is_baseline_summary(summary) or not _summary_success(summary):
            continue
        if not summary.get("peak_tree_pss"):
            continue
        key = (_agent_key(summary), _cap_key(summary))
        run_ids[key].append(str(summary.get("run_id", "unknown")))
        for metric in BASELINE_ADJUSTED_METRICS:
            value = summary.get(metric)
            if value is not None:
                candidates[key][metric].append(float(value))

    baselines: dict[tuple[str, str], dict[str, Any]] = {}
    for key, metrics in candidates.items():
        baselines[key] = {
            "agent": key[0],
            "cap": key[1],
            "run_ids": run_ids[key],
            "metrics": {
                metric: _stats(values)["median"]
                for metric, values in metrics.items()
                if values
            },
        }
    return baselines


def _outcome_rollup(summaries: list[dict]) -> dict[str, Any]:
    failure_phases: dict[str, int] = defaultdict(int)
    success = 0
    oracle_success = 0
    oracle_failed = 0
    timed_out = 0

    for summary in summaries:
        outcome = summary.get("outcome") or {}
        if _summary_success(summary):
            success += 1
        else:
            phase = outcome.get("failure_phase") or "unknown"
            failure_phases[phase] += 1
        if outcome.get("oracle_success") is True:
            oracle_success += 1
        elif outcome.get("oracle_success") is False:
            oracle_failed += 1
        if outcome.get("timed_out"):
            timed_out += 1

    return {
        "success": success,
        "failed": len(summaries) - success,
        "success_rate": success / len(summaries) if summaries else 0,
        "oracle_success": oracle_success,
        "oracle_failed": oracle_failed,
        "timed_out": timed_out,
        "failure_phases": dict(sorted(failure_phases.items())),
    }


def aggregate_cell(summaries: list[dict], baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compute median, p90, max for key metrics across N reps."""

    if not summaries:
        return {}
    metrics: dict[str, list[float]] = {metric: [] for metric in METRIC_NAMES}
    adjusted_metrics: dict[str, list[float]] = {
        metric: [] for metric in BASELINE_ADJUSTED_METRICS
    }
    categories: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    is_baseline = all(_is_baseline_summary(summary) for summary in summaries)
    baseline_metrics = baseline.get("metrics", {}) if baseline and not is_baseline else {}

    for s in summaries:
        for metric in metrics:
            if metric == "observed_subprocesses":
                val = (s.get("tool_events") or {}).get("observed_subprocesses", 0)
            else:
                val = s.get(metric, 0)
            if val is not None:
                metrics[metric].append(float(val))
            if metric in adjusted_metrics and metric in baseline_metrics and val is not None:
                adjusted_metrics[metric].append(max(0.0, float(val) - baseline_metrics[metric]))

        for cat, data in s.get("categories", {}).items():
            categories[cat]["peak_pss"].append(float(data.get("peak_pss", 0)))
            categories[cat]["peak_uss"].append(float(data.get("peak_uss", 0)))

    result: dict[str, Any] = {
        "n_reps": len(summaries),
        "metrics": {m: _stats(vals) for m, vals in metrics.items()},
        "categories": {
            cat: {
                "peak_pss": _stats(vals["peak_pss"]),
                "peak_uss": _stats(vals["peak_uss"]),
            }
            for cat, vals in categories.items()
        },
        # First rep's manifest for metadata
        "agent": summaries[0].get("manifest", {}).get("agent", "unknown"),
        "task": summaries[0].get("manifest", {}).get("task", {}).get("name", "unknown"),
        "outcomes": _outcome_rollup(summaries),
        "baseline": {
            "used": bool(baseline_metrics),
            "agent": baseline.get("agent") if baseline else None,
            "cap": baseline.get("cap") if baseline else None,
            "run_ids": baseline.get("run_ids", []) if baseline else [],
            "metrics": baseline_metrics,
        },
        "metrics_minus_baseline": {
            metric: _stats(values) for metric, values in adjusted_metrics.items()
        },
    }

    return result


def print_cell_table(cell_key: str, result: dict) -> None:
    """Pretty-print one cell's aggregate results."""
    print(f"\n{'='*70}")
    print(f"  {cell_key}  (n={result['n_reps']})")
    print(f"{'='*70}")

    m = result["metrics"]
    pss = m["peak_tree_pss"]
    outcomes = result.get("outcomes", {})

    def mb(b: float) -> str:
        return f"{b / 1024 / 1024:.0f} MB" if b > 0 else "N/A"

    print(f"  Success       | {outcomes.get('success', 0)}/{result['n_reps']} "
          f"({outcomes.get('success_rate', 0):.0%})")
    print(f"  Peak Tree PSS | median: {mb(pss['median']):>8s}  "
          f"p90: {mb(pss['p90']):>8s}  max: {mb(pss['max']):>8s}")
    print(f"  Peak Tree USS | median: {mb(m['peak_tree_uss']['median']):>8s}  "
          f"max: {mb(m['peak_tree_uss']['max']):>8s}")
    print(f"  Wall Time     | median: {m['wall_time_s']['median']:.0f}s  "
          f"p90: {m['wall_time_s']['p90']:.0f}s  max: {m['wall_time_s']['max']:.0f}s")
    print(f"  Files Grepped | median: {m['files_grepped']['median']:.0f}  "
          f"max: {m['files_grepped']['max']:.0f}")
    print(f"  Agent Tools   | median: {m['tool_invocations']['median']:.0f}  "
          f"max: {m['tool_invocations']['max']:.0f}")
    print(f"  Observed Proc | median: {m['observed_subprocesses']['median']:.0f}  "
          f"max: {m['observed_subprocesses']['max']:.0f}")

    if result.get("baseline", {}).get("used"):
        adjusted = result["metrics_minus_baseline"]
        print(f"  PSS Over Base | median: {mb(adjusted['peak_tree_pss']['median']):>8s}  "
              f"max: {mb(adjusted['peak_tree_pss']['max']):>8s}")
        print(f"  Wall Over Base| median: {adjusted['wall_time_s']['median']:.0f}s  "
              f"max: {adjusted['wall_time_s']['max']:.0f}s")

    if outcomes.get("failure_phases"):
        failures = ", ".join(
            f"{phase}={count}" for phase, count in outcomes["failure_phases"].items()
        )
        print(f"  Failures      | {failures}")

    if result["categories"]:
        print("\n  --- Per-Category Peak PSS (median) ---")
        for cat, data in sorted(result["categories"].items()):
            p = data["peak_pss"]
            if p["median"] > 0:
                print(f"  {cat:<30s} median: {mb(p['median']):>8s}  max: {mb(p['max']):>8s}")


def plot_distributions(aggregated: dict[str, dict], output_dir: Path) -> None:
    """Generate distribution plots (matplotlib required)."""
    try:
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("matplotlib not available — skipping charts")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    # Chart 1: Peak Tree PSS across agents for test modality
    agents = set()
    test_data: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for key, result in aggregated.items():
        agent = result.get("agent", "unknown")
        agents.add(agent)
        pss = result["metrics"]["peak_tree_pss"]
        if pss["median"] > 0:
            test_data[agent].append((key, pss["median"]))

    if len(agents) >= 2:
        fig, ax = plt.subplots(figsize=(10, 6))
        x = np.arange(len(agents))
        agent_medians = []
        agent_maxs = []
        agent_names = sorted(agents)

        for agent in agent_names:
            points = test_data.get(agent, [])
            medians = [p[1] / 1024 / 1024 for p in points]
            agent_medians.append(np.median(medians) if medians else 0)
            agent_maxs.append(np.max(medians) if medians else 0)

        ax.bar(x, agent_medians, label="Median", color="steelblue")
        ax.bar(x, [a_m - a_med for a_m, a_med in zip(agent_maxs, agent_medians)],
               bottom=agent_medians, label="Max (additional)", color="lightcoral", alpha=0.6)
        ax.set_xticks(x)
        ax.set_xticklabels(agent_names)
        ax.set_ylabel("Peak Tree PSS (MB)")
        ax.set_title("Agent Peak Memory Usage — Test Suite Modality")
        ax.legend()
        fig.tight_layout()
        fig.savefig(output_dir / "peak_pss_by_agent.png", dpi=150)
        plt.close(fig)
        print(f"  Chart saved: {output_dir / 'peak_pss_by_agent.png'}")


def main() -> None:
    p = argparse.ArgumentParser(description="Aggregate N benchmark runs into distributions")
    p.add_argument("runs_dir", type=Path, help="Path to runs/ directory")
    p.add_argument("--output", "-o", type=Path, default=None,
                   help="Output path for aggregate JSON")
    p.add_argument("--charts-dir", type=Path, default=None,
                   help="Output directory for charts")
    args = p.parse_args()

    summaries = load_all_summaries(args.runs_dir)
    print(f"Loaded {len(summaries)} run summaries from {args.runs_dir}")

    groups = group_by_cell(summaries)
    print(f"Grouped into {len(groups)} cells (agent × task × codebase × cap)")

    baselines = build_baseline_map(summaries)
    print(f"Found {len(baselines)} successful baseline cells")

    aggregated = {}
    for key, group in sorted(groups.items()):
        first = group[0]
        baseline = baselines.get((_agent_key(first), _cap_key(first)))
        result = aggregate_cell(group, baseline=baseline)
        aggregated[key] = result
        print_cell_table(key, result)

    # Save
    output = args.output or (args.runs_dir / "aggregate.json")
    with open(output, "w") as f:
        json.dump(aggregated, f, indent=2, default=str)
    print(f"\nAggregate written to {output}")

    # Charts
    charts = args.charts_dir or (args.runs_dir / "charts")
    plot_distributions(aggregated, charts)


if __name__ == "__main__":
    main()
