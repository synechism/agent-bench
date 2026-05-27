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
import re
import shutil
import signal
import socket
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


def _setup_shims(shim_dir: Path) -> dict[str, str]:
    """Create symlinks in the shim dir for all observed tool binaries.

    Returns env vars to prepend the shim dir to PATH.
    """
    shim_dir.mkdir(parents=True, exist_ok=True)

    source_template = Path(__file__).resolve().parents[1] / "measure" / "shims" / "_template.sh"
    template = shim_dir / "_template.sh"
    shutil.copy2(source_template, template)
    template.chmod(0o755)

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

    for tool in tools:
        real = shutil.which(tool)
        if real and not (shim_dir / tool).exists():
            (shim_dir / tool).symlink_to(template.resolve())

    return {
        "PATH": f"{shim_dir}:{os.environ.get('PATH', '')}",
        "SHIM_DIR": str(shim_dir),
    }


def _timeout_s(manifest: RunManifest) -> int:
    timeout = manifest.task.oracle.get("timeout_s")
    if isinstance(timeout, int) and timeout > 0:
        return timeout
    return 1800


def _expand_adapter_env(adapter) -> dict[str, str]:
    expanded_env: dict[str, str] = {}
    for key, val in adapter.env().items():
        match = re.fullmatch(r"\$\{([^}]+)\}", val)
        if match and match.group(1) not in os.environ:
            continue
        expanded_env[key] = os.path.expandvars(val)
    return expanded_env


def _looks_like_full_sha(ref: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{40}", ref))


def _git_clone_command(repo_url: str, commit: str, codebase_dir: Path) -> tuple[list[str], str]:
    base = ["git", "clone", "--quiet", "--filter=blob:none"]
    if not _looks_like_full_sha(commit):
        return (
            [
                *base,
                "--depth",
                "1",
                "--branch",
                commit,
                "--single-branch",
                "--no-checkout",
                repo_url,
                str(codebase_dir),
            ],
            "partial_shallow_ref",
        )
    return ([*base, "--no-checkout", repo_url, str(codebase_dir)], "partial_blobless")


def _clone_remote_codebase(repo_url: str, commit: str, codebase_dir: Path, events_log: Path) -> None:
    cmd, strategy = _git_clone_command(repo_url, commit, codebase_dir)
    try:
        subprocess.run(cmd, check=True)
        _write_event(events_log, "codebase_clone_strategy", {"strategy": strategy})
    except subprocess.CalledProcessError:
        if codebase_dir.exists():
            shutil.rmtree(codebase_dir)
        subprocess.run(
            ["git", "clone", "--quiet", "--no-checkout", repo_url, str(codebase_dir)],
            check=True,
        )
        _write_event(
            events_log,
            "codebase_clone_strategy",
            {"strategy": "full_clone_fallback", "failed_strategy": strategy},
        )


def _wrap_with_strace(agent_cmd: list[str], run_dir: Path, events_log: Path) -> list[str]:
    """Trace child execve calls for exact argv capture when strace is available."""
    if os.environ.get("HARNESS_STRACE_EXEC", "1") == "0":
        _write_event(events_log, "strace_exec_disabled", {"reason": "HARNESS_STRACE_EXEC=0"})
        return agent_cmd

    strace = shutil.which("strace")
    if not strace:
        _write_event(events_log, "strace_exec_unavailable", {"reason": "strace_not_found"})
        return agent_cmd

    log_path = (run_dir / "strace_exec.log").resolve()
    _write_event(events_log, "strace_exec_enabled", {"path": str(log_path)})
    return [
        strace,
        "-f",
        "-qq",
        "-ttt",
        "-s",
        "4096",
        "-e",
        "trace=execve",
        "-o",
        str(log_path),
        "--",
        *agent_cmd,
    ]


def _prepare_codebase(manifest: RunManifest, run_dir: Path, events_log: Path) -> Path:
    """Create the per-run checkout used as the agent worktree."""
    codebase_dir = run_dir / "codebase"
    if codebase_dir.exists():
        _write_event(events_log, "codebase_reused", {"path": str(codebase_dir)})
        return codebase_dir

    repo_url = manifest.codebase.repo_url
    if repo_url == "builtin:empty":
        codebase_dir.mkdir(parents=True)
        (codebase_dir / "README.md").write_text(
            "# Empty Baseline Codebase\n\n"
            "This repository exists only so benchmark agents have a valid worktree.\n"
        )
        subprocess.run(["git", "-C", str(codebase_dir), "init", "--quiet"], check=True)
        subprocess.run(["git", "-C", str(codebase_dir), "add", "README.md"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(codebase_dir),
                "-c",
                "user.name=Agent Harness",
                "-c",
                "user.email=agent-harness@example.invalid",
                "commit",
                "--quiet",
                "-m",
                "Create empty baseline codebase",
            ],
            check=True,
        )
        _write_event(events_log, "codebase_builtin_created", {"kind": "empty"})
        return codebase_dir

    _write_event(
        events_log,
        "codebase_checkout_start",
        {"repo_url": repo_url, "commit": manifest.codebase.commit},
    )

    if Path(repo_url).expanduser().exists():
        shutil.copytree(Path(repo_url).expanduser(), codebase_dir, symlinks=True)
    else:
        _clone_remote_codebase(repo_url, manifest.codebase.commit, codebase_dir, events_log)

    subprocess.run(
        [
            "git",
            "-c",
            "advice.detachedHead=false",
            "-C",
            str(codebase_dir),
            "checkout",
            "--quiet",
            manifest.codebase.commit,
        ],
        check=True,
    )
    _write_event(events_log, "codebase_checkout_end", {"path": str(codebase_dir)})
    return codebase_dir


def _start_kernel_exec_logger(exec_log: Path, events_log: Path) -> subprocess.Popen | None:
    """Start bpftrace or bcc exec logging when available."""
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        _write_event(events_log, "execsnoop_unavailable", {"reason": "requires_root"})
        return None

    try:
        from measure.execsnoop_wrap import find_bpftrace, run_bpftrace_snoop

        if find_bpftrace():
            proc = run_bpftrace_snoop(exec_log)
            time.sleep(0.15)
            if proc.poll() is not None:
                _write_event(
                    events_log,
                    "execsnoop_failed",
                    {"method": "bpftrace", "returncode": proc.returncode},
                )
            else:
                _write_event(events_log, "execsnoop_started", {"method": "bpftrace"})
                return proc
    except Exception as exc:
        _write_event(events_log, "execsnoop_failed", {"method": "bpftrace", "error": str(exc)})

    try:
        from measure.execsnoop_wrap import find_execsnoop, run_execsnoop_bcc

        if find_execsnoop():
            proc = run_execsnoop_bcc(exec_log)
            time.sleep(0.15)
            if proc.poll() is not None:
                _write_event(
                    events_log,
                    "execsnoop_failed",
                    {"method": "bcc", "returncode": proc.returncode},
                )
            else:
                _write_event(events_log, "execsnoop_started", {"method": "bcc"})
                return proc
    except Exception as exc:
        _write_event(events_log, "execsnoop_failed", {"method": "bcc", "error": str(exc)})

    return None


def _start_fallback_exec_logger(
    exec_log: Path,
    events_log: Path,
    root_pid: int,
) -> subprocess.Popen | None:
    try:
        from measure.execsnoop_wrap import fallback_audit

        proc = fallback_audit(exec_log, root_pid)
        _write_event(events_log, "execsnoop_started", {"method": "fallback"})
        return proc
    except Exception as exc:
        _write_event(events_log, "execsnoop_failed", {"method": "fallback", "error": str(exc)})
        return None


def _stop_process(proc: subprocess.Popen | None, timeout: float = 5.0) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _stop_process_group(proc: subprocess.Popen | None, timeout: float = 10.0) -> None:
    if proc is None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        _stop_process(proc, timeout=timeout)
        return

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            try:
                os.killpg(proc.pid, 0)
            except ProcessLookupError:
                return
        time.sleep(0.1)

    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


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
        "--workdir", "/codebase",
        "--env-file", "/dev/null",  # env passed inline below
    ]

    for key, val in _expand_adapter_env(adapter).items():
        cmd.extend(["--env", f"{key}={val}"])

    cmd.append(agent_image)

    # The container entrypoint runs the harness entrypoint
    task_spec = {
        "kind": manifest.task.kind.value,
        "prompt": manifest.task.prompt,
        "repo_path": "/codebase",
        "workdir": "/codebase",
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

    exec_log = (run_dir / "exec_log.jsonl").resolve()
    proc_csv = (run_dir / "proc_timeseries.csv").resolve()
    events_log = run_dir / "events.jsonl"
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"

    # Record start event
    _write_event(events_log, "run_start", {"run_id": manifest.run_id})
    codebase_dir = _prepare_codebase(manifest, run_dir, events_log)

    # Set up PATH shims
    shim_dir = (run_dir / "shims").resolve()
    shim_env = _setup_shims(shim_dir)

    updated_env = os.environ.copy()
    updated_env.update(shim_env)
    updated_env.update(_expand_adapter_env(adapter))
    updated_env["EXEC_SHIM_LOG"] = str(exec_log)
    updated_env["CGROUP_BASE"] = str((run_dir / "cgroups").resolve())
    updated_env["NO_COLOR"] = "1"

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
        "repo_path": str(codebase_dir),
        "workdir": str(codebase_dir),
    })()

    agent_cmd = adapter.local_command(task_spec)
    launch_cmd = _wrap_with_strace(agent_cmd, run_dir, events_log)
    timeout_s = _timeout_s(manifest)

    execsnoop_proc = _start_kernel_exec_logger(exec_log, events_log)
    sampler_proc = None

    sample_start = time.time()
    timed_out = False
    exit_code = 127

    with stdout_path.open("w") as stdout_f, stderr_path.open("w") as stderr_f:
        try:
            agent_proc = subprocess.Popen(
                launch_cmd,
                env=updated_env,
                stdout=stdout_f,
                stderr=stderr_f,
                cwd=str(codebase_dir),
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            _write_event(events_log, "agent_start_failed", {"cmd": launch_cmd, "error": str(exc)})
            _stop_process(execsnoop_proc)
            return 127

        _write_event(
            events_log,
            "agent_started",
            {"pid": agent_proc.pid, "cmd": agent_cmd, "launch_cmd": launch_cmd},
        )

        if execsnoop_proc is not None and execsnoop_proc.poll() is not None:
            _write_event(
                events_log,
                "execsnoop_exited_early",
                {"returncode": execsnoop_proc.returncode},
            )
            execsnoop_proc = None

        if execsnoop_proc is None:
            execsnoop_proc = _start_fallback_exec_logger(exec_log, events_log, agent_proc.pid)

        sampler_proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "measure.proc_sampler",
                str(agent_proc.pid),
                str(proc_csv),
                "--interval",
                "0.25",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _write_event(events_log, "sampler_started", {"pid": sampler_proc.pid})

        try:
            exit_code = agent_proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            _stop_process_group(agent_proc)
            exit_code = agent_proc.wait()
            _write_event(events_log, "agent_timed_out", {"timeout_s": timeout_s})

    sample_end = time.time()
    _stop_process_group(agent_proc)

    if sampler_proc is not None:
        try:
            sampler_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _stop_process(sampler_proc)

    _stop_process(execsnoop_proc)

    _write_event(events_log, "run_end", {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "wall_time_s": sample_end - sample_start,
    })

    # Convert CSV to parquet if we have data
    if proc_csv.exists() and proc_csv.stat().st_size > 0:
        try:
            from measure.proc_sampler import csv_to_parquet

            csv_to_parquet(proc_csv, run_dir / "proc_timeseries.parquet")
            _write_event(events_log, "parquet_written", {"path": str(run_dir / "proc_timeseries.parquet")})
        except Exception as exc:
            _write_event(events_log, "parquet_failed", {"error": str(exc)})

    return exit_code


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
    manifest.agent_version = getattr(adapter, "version", manifest.agent_version)
    manifest.agent_capabilities = vars(getattr(adapter, "capabilities", {}))
    manifest.hostname = socket.gethostname()
    try:
        from measure.host_info import collect_host_info

        manifest.hardware = collect_host_info()
    except Exception as exc:
        manifest.caveats.append(f"host_info_unavailable: {exc}")

    if manifest.sandbox == "docker":
        exit_code = _run_docker(manifest, run_dir, adapter)
    else:
        exit_code = _run_local(manifest, run_dir, adapter)

    manifest.completed_at = datetime.now(timezone.utc).isoformat()
    with open(manifest_path, "w") as f:
        f.write(manifest.model_dump_json(indent=2))

    try:
        from analysis.summarize import summarize_run

        summary = summarize_run(run_dir)
        summary["exit_code"] = exit_code
    except Exception as exc:
        summary = {
            "run_id": manifest.run_id,
            "agent": manifest.agent,
            "task": manifest.task.name,
            "codebase": manifest.codebase.repo_url,
            "exit_code": exit_code,
            "summary_error": str(exc),
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
