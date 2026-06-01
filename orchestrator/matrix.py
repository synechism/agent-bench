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
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from io import TextIOWrapper
from pathlib import Path

from orchestrator.config import RunConfig, RunManifest


@dataclass
class ActiveRun:
    index: int
    total: int
    cell: RunManifest
    manifest_path: Path
    run_dir: Path
    process: subprocess.Popen
    log_file: TextIOWrapper
    started_at: float


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


def _adapter_metadata(agent: str) -> tuple[str, dict[str, bool], list[str]]:
    try:
        import importlib

        mod = importlib.import_module(f"adapters.{agent}")
        class_name = "".join(part.capitalize() for part in agent.split("_")) + "Adapter"
        adapter = getattr(mod, class_name)()
        capabilities = asdict(adapter.capabilities)
        caveats = [
            name
            for name, supported in capabilities.items()
            if name != "headless" and not supported
        ]
        return adapter.version, capabilities, caveats
    except Exception as exc:
        return "unknown", {}, [f"adapter_metadata_unavailable: {exc}"]


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
        if task_data.get("codebase") and task_data["codebase"] != cb_name:
            continue

        agent_version, capabilities, caveats = _adapter_metadata(agent)

        from orchestrator.config import Caps, CodebaseRef, TaskDef, TaskKind

        manifest = RunManifest(
            run_id=RunManifest.make_run_id(agent, cb_name, task_name, cap, rep),
            agent=agent,
            agent_version=agent_version,
            agent_capabilities=capabilities,
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
            caveats=caveats,
        )
        cells.append(manifest)

    return cells


def _write_manifest(cell: RunManifest, config: RunConfig) -> Path:
    manifest_path = config.runs_dir / cell.run_id / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w") as f:
        f.write(cell.model_dump_json(indent=2))
    return manifest_path


def dispatch_sequential(cells: list[RunManifest], config: RunConfig) -> list[Path]:
    """Run cells one at a time. Simple, safe, no co-location risk."""
    results: list[Path] = []
    for i, cell in enumerate(cells):
        print(f"[{i+1}/{len(cells)}] {cell.run_id}")
        manifest_path = _write_manifest(cell, config)

        # Dispatch the run
        result = subprocess.run(
            [sys.executable, "-m", "orchestrator.run", str(manifest_path)],
            timeout=config.timeout_per_run,
        )
        if result.returncode != 0:
            print(f"  WARNING: run failed with exit code {result.returncode}")
        results.append(manifest_path.parent)
    return results


def _launch_cell(index: int, total: int, cell: RunManifest, config: RunConfig) -> ActiveRun:
    manifest_path = _write_manifest(cell, config)
    run_dir = manifest_path.parent
    log_path = run_dir / "orchestrator.log"
    log_file = log_path.open("w")
    process = subprocess.Popen(
        [sys.executable, "-m", "orchestrator.run", str(manifest_path)],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"[{index}/{total}] START pid={process.pid} {cell.run_id} log={log_path}")
    return ActiveRun(
        index=index,
        total=total,
        cell=cell,
        manifest_path=manifest_path,
        run_dir=run_dir,
        process=process,
        log_file=log_file,
        started_at=time.monotonic(),
    )


def _stop_active_run(active: ActiveRun) -> int:
    proc = active.process
    if proc.poll() is not None:
        return proc.returncode

    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return proc.wait()

    try:
        return proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return proc.wait()


def dispatch_parallel(cells: list[RunManifest], config: RunConfig, jobs: int) -> list[Path]:
    """Run up to ``jobs`` cells concurrently.

    Per-run measurement remains scoped to each agent root PID and run directory.
    Wall time and CPU metrics should be interpreted as contended when jobs > 1.
    """
    if jobs < 1:
        raise ValueError("jobs must be >= 1")
    if jobs == 1:
        return dispatch_sequential(cells, config)

    pending = list(enumerate(cells, start=1))
    active: list[ActiveRun] = []
    results: list[Path] = []
    total = len(cells)

    while pending or active:
        while pending and len(active) < jobs:
            index, cell = pending.pop(0)
            active.append(_launch_cell(index, total, cell, config))

        now = time.monotonic()
        for run in active[:]:
            rc = run.process.poll()
            timed_out = rc is None and now - run.started_at > config.timeout_per_run
            if timed_out:
                rc = _stop_active_run(run)
                print(f"[{run.index}/{run.total}] TIMEOUT rc={rc} {run.cell.run_id}")

            if rc is None:
                continue

            run.log_file.close()
            active.remove(run)
            results.append(run.run_dir)
            if rc != 0:
                print(f"[{run.index}/{run.total}] FAILED rc={rc} {run.cell.run_id}")
            else:
                print(f"[{run.index}/{run.total}] DONE {run.cell.run_id}")

        if pending or active:
            time.sleep(0.5)

    return results


def main() -> None:
    p = argparse.ArgumentParser(description="Build and dispatch the run matrix")
    p.add_argument("--config", type=Path, default=Path("harness_configs/harness_config.json"),
                   help="Path to harness config JSON")
    p.add_argument("--tasks-dir", type=Path, default=Path("tasks"),
                   help="Directory containing task definitions")
    p.add_argument("--registry", type=Path, default=Path("codebases/registry.yaml"),
                   help="Path to codebase registry")
    p.add_argument("--dry-run", action="store_true",
                   help="Print matrix without executing")
    p.add_argument("--jobs", type=int, default=None,
                   help="Number of cells to run concurrently (overrides config)")
    args = p.parse_args()

    if args.config.exists():
        config = RunConfig.model_validate_json(args.config.read_text())
    else:
        config = RunConfig()
    jobs = args.jobs if args.jobs is not None else config.parallel_jobs

    root = Path.cwd()
    tasks_dir = args.tasks_dir if args.tasks_dir.is_absolute() else root / args.tasks_dir
    registry_path = args.registry if args.registry.is_absolute() else root / args.registry
    cells = build_matrix(config, tasks_dir, registry_path)
    agents_in_matrix = {cell.agent for cell in cells}
    codebases_in_matrix = {cell.task.codebase for cell in cells}
    tasks_in_matrix = {cell.task.name for cell in cells}

    print(f"Matrix: {len(cells)} cells "
          f"({len(agents_in_matrix)} agents × {len(codebases_in_matrix)} task codebases "
          f"× {len(tasks_in_matrix)} tasks × {len(config.memory_caps)} caps "
          f"× {config.repetitions} reps, jobs={jobs})")

    if args.dry_run:
        for cell in cells:
            print(f"  {cell.run_id}")
        return

    results = dispatch_parallel(cells, config, jobs)
    print(f"Done. {len(results)} runs in {config.runs_dir}")


if __name__ == "__main__":
    main()
