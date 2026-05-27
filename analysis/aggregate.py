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
from pathlib import Path
from typing import Any


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


def aggregate_cell(summaries: list[dict]) -> dict[str, Any]:
    """Compute median, p90, max for key metrics across N reps."""

    if not summaries:
        return {}

    def _stats(values: list[float]) -> dict[str, float]:
        if not values:
            return {"median": 0, "p90": 0, "max": 0, "min": 0, "count": 0}
        sv = sorted(values)
        n = len(sv)
        return {
            "median": sv[n // 2],
            "p90": sv[int(n * 0.9)],
            "max": sv[-1],
            "min": sv[0],
            "count": n,
        }

    metrics = {
        "peak_tree_pss": [],
        "peak_tree_uss": [],
        "peak_tree_rss": [],
        "wall_time_s": [],
        "files_grepped": [],
        "tool_invocations": [],
    }
    categories: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for s in summaries:
        for metric in metrics:
            val = s.get(metric, 0)
            if val:
                metrics[metric].append(float(val))

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
    }

    return result


def print_cell_table(cell_key: str, result: dict) -> None:
    """Pretty-print one cell's aggregate results."""
    print(f"\n{'='*70}")
    print(f"  {cell_key}  (n={result['n_reps']})")
    print(f"{'='*70}")

    m = result["metrics"]
    pss = m["peak_tree_pss"]

    def mb(b: float) -> str:
        return f"{b / 1024 / 1024:.0f} MB" if b > 0 else "N/A"

    print(f"  Peak Tree PSS | median: {mb(pss['median']):>8s}  "
          f"p90: {mb(pss['p90']):>8s}  max: {mb(pss['max']):>8s}")
    print(f"  Peak Tree USS | median: {mb(m['peak_tree_uss']['median']):>8s}  "
          f"max: {mb(m['peak_tree_uss']['max']):>8s}")
    print(f"  Wall Time     | median: {m['wall_time_s']['median']:.0f}s  "
          f"p90: {m['wall_time_s']['p90']:.0f}s  max: {m['wall_time_s']['max']:.0f}s")
    print(f"  Files Grepped | median: {m['files_grepped']['median']:.0f}  "
          f"max: {m['files_grepped']['max']:.0f}")
    print(f"  Tool Calls    | median: {m['tool_invocations']['median']:.0f}  "
          f"max: {m['tool_invocations']['max']:.0f}")

    if result["categories"]:
        print(f"\n  --- Per-Category Peak PSS (median) ---")
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

    aggregated = {}
    for key, group in sorted(groups.items()):
        result = aggregate_cell(group)
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
