"""Builds and dispatches the run matrix.

The matrix is the Cartesian product:
    agents × codebases × tasks × memory_caps × repetitions

Each cell is one isolated run. Cells are dispatched sequentially by default
or can be fanned out across VMs (never co-located).
"""

from __future__ import annotations

import argparse
import itertools
import json
import subprocess
import sys
from pathlib import Path

from orchestrator.config import RunConfig, RunManifest


def load_registry(registry_path: Path) -> dict:
    import yaml
    with open(registry_path) as f:
        return yaml.safe_load(f)


def load_tasks(tasks_dir: Path) -> list[dict]:
    tasks = []
    for kind_dir in tasks_dir.iterdir():
        if not kind_dir.is_dir():
            continue
        for task_file in kind_dir.glob("*.json"):
            with open(task_file) as f:
                data = json.load(f)
            data["kind"] = kind_dir.name
            tasks.append(data)
    return tasks


def build_matrix(config: RunConfig, tasks_dir: Path, registry_path: Path) -> list[RunManifest]:
    """Expand config into the flat list of runs to execute."""
    registry = load_registry(registry_path)
    task_defs = load_tasks(tasks_dir)

    # Filter to configured agents/tasks/codebases
    agents = config.agents
    codebases = config.codebases or list(registry.keys())
    task_names = config.tasks or [t["name"] for t in task_defs]

    cells: list[RunManifest] = []

    for agent, cb_name, task_name, cap, rep in itertools.product(
        agents,
        codebases,
        task_names,
        config.memory_caps,
        range(config.repetitions),
    ):
        if cb_name not in registry:
            print(f"WARNING: codebase '{cb_name}' not in registry, skipping", file=sys.stderr)
            continue

        cb_data = registry[cb_name]
        task_data = next((t for t in task_defs if t["name"] == task_name), None)
        if task_data is None:
            print(f"WARNING: task '{task_name}' not found, skipping", file=sys.stderr)
            continue

        from orchestrator.config import Caps, CodebaseRef, TaskDef, TaskKind

        manifest = RunManifest(
            run_id=RunManifest.make_run_id(agent, cb_name, task_name, cap, rep),
            agent=agent,
            agent_version="pinned-by-adapter",
            task=TaskDef(
                kind=TaskKind(task_data["kind"]),
                name=task_name,
                prompt=task_data["prompt"],
                codebase=cb_name,
                oracle=task_data.get("oracle", {}),
            ),
            codebase=CodebaseRef(
                repo_url=cb_data["repo_url"],
                commit=cb_data["commit"],
                language=cb_data.get("language", "unknown"),
            ),
            caps=Caps(memory_mb=cap),
            rep=rep,
            sandbox=config.sandbox,
            hardware={},
            caveats=[],
        )
        cells.append(manifest)

    return cells


def dispatch_sequential(cells: list[RunManifest], config: RunConfig) -> list[Path]:
    """Run cells one at a time. Simple, safe, no co-location risk."""
    results: list[Path] = []
    for i, cell in enumerate(cells):
        print(f"[{i+1}/{len(cells)}] {cell.run_id}")
        manifest_path = config.runs_dir / cell.run_id / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_path, "w") as f:
            f.write(cell.model_dump_json(indent=2))

        # Dispatch the run
        result = subprocess.run(
            [sys.executable, "-m", "orchestrator.run", str(manifest_path)],
            timeout=config.timeout_per_run,
        )
        if result.returncode != 0:
            print(f"  WARNING: run failed with exit code {result.returncode}")
        results.append(manifest_path.parent)
    return results


def main() -> None:
    p = argparse.ArgumentParser(description="Build and dispatch the run matrix")
    p.add_argument("--config", type=Path, default=Path("harness_config.json"),
                   help="Path to harness config JSON")
    p.add_argument("--tasks-dir", type=Path, default=Path("tasks"),
                   help="Directory containing task definitions")
    p.add_argument("--registry", type=Path, default=Path("codebases/registry.yaml"),
                   help="Path to codebase registry")
    p.add_argument("--dry-run", action="store_true",
                   help="Print matrix without executing")
    args = p.parse_args()

    if args.config.exists():
        config = RunConfig.model_validate_json(args.config.read_text())
    else:
        config = RunConfig()

    root = args.config.parent if args.config.exists() else Path.cwd()
    cells = build_matrix(config, root / args.tasks_dir, root / args.registry)

    print(f"Matrix: {len(cells)} cells "
          f"({len(config.agents)} agents × {len(config.codebases or ['?'])} codebases "
          f"× {len(config.tasks or ['?'])} tasks × {len(config.memory_caps)} caps "
          f"× {config.repetitions} reps)")

    if args.dry_run:
        for cell in cells:
            print(f"  {cell.run_id}")
        return

    results = dispatch_sequential(cells, config)
    print(f"Done. {len(results)} runs in {config.runs_dir}")


if __name__ == "__main__":
    main()
