"""Execute ONE isolated run end-to-end.

This is the main entry point for a single cell in the run matrix.
It:
 1. Reads the manifest
 2. Sets up the sandbox (Docker or local)
 3. Starts the measurement layer (sampler, execsnoop, shims)
 4. Invokes the agent via its adapter
 5. Tears down, collects artifacts, writes summary

Usage:
    python -m orchestrator.run <manifest.json>
    # or within Docker:
    harness run /runs/<run_id>/manifest.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.config import RunManifest


def _load_adapter(agent_name: str):
    """Dynamically import the adapter module by agent name."""
    import importlib
    mod = importlib.import_module(f"adapters.{agent_name}")
    # Each adapter module exposes a class named <Agent>Adapter
    class_name = "".join(part.capitalize() for part in agent_name.split("_")) + "Adapter"
    return getattr(mod, class_name)()


def _setup_shims(workdir: str, shim_dir: Path) -> dict[str, str]:
    """Create symlinks in the shim dir for all observed tool binaries.

    Returns env vars to prepend the shim dir to PATH.
    """
    tools = [
        "rg", "grep", "cat", "head", "tail", "find", "git",
        "make", "cmake", "cargo", "go", "rustc", "gcc", "clang",
        "pytest", "python", "python3", "node", "npm", "npx",
        "ls", "cp", "mv", "rm", "mkdir", "chmod",
        "bash", "sh", "zsh",
        "curl", "wget",
        "docker",
        "awk", "sed", "sort", "uniq", "wc",
        "jq", "yq",
        "tsc", "eslint", "prettier",
        "pip", "poetry",
        "java", "javac", "mvn", "gradle",
    ]

    template = shim_dir / "_template.sh"
    for tool in tools:
        real = shutil.which(tool)
        if real and not (shim_dir / tool).exists():
            (shim_dir / tool).symlink_to(template)

    return {
        "PATH": f"{shim_dir}:{os.environ.get('PATH', '')}",
        "SHIM_DIR": str(shim_dir),
    }


def _run_docker(manifest: RunManifest, run_dir: Path, adapter) -> int:
    """Execute the agent inside a Docker container.

    Returns the agent's exit code.
    """
    agent_image = adapter.docker_image()
    run_dir.mkdir(parents=True, exist_ok=True)

    # Build docker run command
    cmd = [
        "docker", "run",
        "--rm",
        "--name", manifest.run_id,
        "--cpus", str(manifest.caps.cpu_cores) if manifest.caps.cpu_cores else "0",
        "--memory", f"{manifest.caps.memory_mb}m" if manifest.caps.memory_mb else "0",
        "--volume", f"{run_dir}:/runs/{manifest.run_id}",
        "--volume", f"{manifest.codebase.repo_url or '/dev/null'}:/codebase:ro",
        "--workdir", manifest.task.workdir or "/codebase",
        "--env-file", "/dev/null",  # env passed inline below
    ]

    for key, val in adapter.env().items():
        # Expand ${VAR} references from host environment
        expanded = os.path.expandvars(val)
        cmd.extend(["--env", f"{key}={expanded}"])

    cmd.append(agent_image)

    # The container entrypoint runs the harness entrypoint
    task_spec = {
        "kind": manifest.task.kind.value,
        "prompt": manifest.task.prompt,
        "repo_path": "/codebase",
        "workdir": manifest.task.workdir or "/codebase",
    }
    cmd.extend([
        "harness", "run-inner",
        "--manifest", f"/runs/{manifest.run_id}/manifest.json",
        "--task", json.dumps(task_spec),
    ])

    result = subprocess.run(cmd, capture_output=False)
    return result.returncode


def _run_local(manifest: RunManifest, run_dir: Path, adapter) -> int:
    """Execute the agent locally on the host machine.

    Starts the measurement layer, runs the agent, collects results.
    This gives more fine-grained control over what's being measured.
    """
    run_dir.mkdir(parents=True, exist_ok=True)

    exec_log = run_dir / "exec_log.jsonl"
    proc_csv = run_dir / "proc_timeseries.csv"
    events_log = run_dir / "events.jsonl"

    # Record start event
    _write_event(events_log, "run_start", {"run_id": manifest.run_id})

    # Start execsnoop in background
    execsnoop_proc = None
    try:
        from measure.execsnoop_wrap import find_bpftrace, run_bpftrace_snoop
        if find_bpftrace():
            execsnoop_proc = run_bpftrace_snoop(exec_log)
            _write_event(events_log, "execsnoop_started", {"method": "bpftrace"})
    except Exception:
        pass

    if execsnoop_proc is None:
        try:
            from measure.execsnoop_wrap import run_execsnoop_bcc, find_execsnoop
            if find_execsnoop():
                execsnoop_proc = run_execsnoop_bcc(exec_log)
                _write_event(events_log, "execsnoop_started", {"method": "bcc"})
        except Exception:
            _write_event(events_log, "execsnoop_failed", {})

    # Set up PATH shims
    shim_dir = run_dir / "shims"
    shim_dir.mkdir(exist_ok=True)
    shim_env = _setup_shims(str(run_dir), shim_dir)

    updated_env = os.environ.copy()
    updated_env.update(shim_env)
    updated_env["EXEC_SHIM_LOG"] = str(exec_log)
    updated_env["CGROUP_BASE"] = str(run_dir / "cgroups")

    # Apply memory cap if configured
    if manifest.caps.memory_mb:
        # Use cgroup v2 to cap memory for this run
        cg_base = f"/sys/fs/cgroup/bench-{manifest.run_id}"
        try:
            os.makedirs(cg_base, exist_ok=True)
            max_bytes = manifest.caps.memory_mb * 1024 * 1024
            (Path(cg_base) / "memory.max").write_text(str(max_bytes))
            # Move our PID into the cgroup
            (Path(cg_base) / "cgroup.procs").write_text(str(os.getpid()))
        except (PermissionError, OSError):
            print("WARNING: could not set memory cgroup cap", file=sys.stderr)

    # Build agent command
    task_spec = type("TaskSpec", (), {
        "kind": manifest.task.kind.value,
        "prompt": manifest.task.prompt,
        "repo_path": str(run_dir / "codebase"),
        "workdir": str(run_dir / "codebase"),
    })()

    agent_cmd = adapter.local_command(task_spec)

    # Start the /proc sampler in background
    agent_proc = subprocess.Popen(
        agent_cmd,
        env=updated_env,
        stdout=open(run_dir / "stdout.log", "w"),
        stderr=open(run_dir / "stderr.log", "w"),
        cwd=str(run_dir / "codebase"),
    )

    _write_event(events_log, "agent_started", {"pid": agent_proc.pid, "cmd": agent_cmd})

    # Start sampler
    from measure.proc_sampler import sample
    sample_start = time.time()

    try:
        agent_proc.wait(timeout=manifest.timeout_override or 1800)
    except subprocess.TimeoutExpired:
        agent_proc.kill()
        agent_proc.wait()
        _write_event(events_log, "agent_timed_out", {})

    sample_end = time.time()

    # Sampler runs inline (it watches the root PID and exits when it does)
    # For now, run a post-hoc sampling catch-up
    # In the real implementation, the sampler runs in a thread alongside agent_proc

    # Stop execsnoop
    if execsnoop_proc:
        execsnoop_proc.terminate()
        try:
            execsnoop_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            execsnoop_proc.kill()

    _write_event(events_log, "run_end", {
        "exit_code": agent_proc.returncode,
        "wall_time_s": sample_end - sample_start,
    })

    # Convert CSV to parquet if we have data
    if proc_csv.exists() and proc_csv.stat().st_size > 0:
        from measure.proc_sampler import csv_to_parquet
        csv_to_parquet(proc_csv, run_dir / "proc_timeseries.parquet")

    return agent_proc.returncode or 0


def _write_event(events_log: Path, event_type: str, data: dict) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        **data,
    }
    with open(events_log, "a") as f:
        f.write(json.dumps(record) + "\n")


def run_one(manifest_path: Path) -> int:
    """Execute a single run from its manifest."""
    manifest = RunManifest.model_validate_json(manifest_path.read_text())
    manifest.started_at = datetime.now(timezone.utc).isoformat()

    run_dir = manifest_path.parent
    adapter = _load_adapter(manifest.agent)

    if manifest.sandbox == "docker":
        exit_code = _run_docker(manifest, run_dir, adapter)
    else:
        exit_code = _run_local(manifest, run_dir, adapter)

    manifest.completed_at = datetime.now(timezone.utc).isoformat()
    with open(manifest_path, "w") as f:
        f.write(manifest.model_dump_json(indent=2))

    # Write a quick summary
    summary = {
        "run_id": manifest.run_id,
        "agent": manifest.agent,
        "task": manifest.task.name,
        "codebase": manifest.codebase.repo_url,
        "exit_code": exit_code,
        "started_at": manifest.started_at,
        "completed_at": manifest.completed_at,
    }
    with open(run_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    return exit_code


def main() -> None:
    p = argparse.ArgumentParser(description="Execute one isolated benchmark run")
    p.add_argument("manifest", type=Path, help="Path to manifest.json for this run")
    args = p.parse_args()

    exit_code = run_one(args.manifest)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
