"""execsnoop wrapper — logs every exec() with argv, PID, PPID, timestamp.

Wraps the bcc/eBPF execsnoop tool (or bpftrace) to catch every subprocess spawn
regardless of lifetime. This is the safety net for:
1. Tool calls that live < 50ms (missed by /proc sampler)
2. Agents that call binaries by absolute path (bypass PATH shims)

Usage:
    python -m measure.execsnoop_wrap <out_jsonl> &
    EXECSNOOP_PID=$!
    ... run agent ...
    kill $EXECSNOOP_PID
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
from pathlib import Path

BPFTRACE_SCRIPT = """
tracepoint:syscalls:sys_enter_execve
{
    printf("{\\"ts\\":%llu,\\"pid\\":%d,\\"ppid\\":%d,\\"comm\\":\\"%s\\",\\"argv\\":\\"%s\\"}\\n",
           nsecs, pid, curtask->real_parent->pid, comm, str(args->filename));
}
"""


def find_bpftrace() -> str | None:
    return shutil.which("bpftrace")


def find_execsnoop() -> str | None:
    """Check for bcc execsnoop (typically at /usr/share/bcc/tools/execsnoop)."""
    for path in [
        "/usr/share/bcc/tools/execsnoop",
        "/usr/sbin/execsnoop",
    ]:
        if os.path.exists(path):
            return path
    return shutil.which("execsnoop-bpfcc") or shutil.which("execsnoop")


def run_bpftrace_snoop(out_jsonl: Path) -> subprocess.Popen:
    """Start bpftrace with the execve tracepoint script.

    Returns the Popen handle; caller must terminate it when the run ends.
    """
    if not find_bpftrace():
        raise RuntimeError("bpftrace not found — install bpftrace or bcc-tools")

    with out_jsonl.open("w") as f:
        proc = subprocess.Popen(
            ["bpftrace", "-e", BPFTRACE_SCRIPT],
            stdout=f,
            stderr=subprocess.DEVNULL,
        )
    return proc


def run_execsnoop_bcc(out_jsonl: Path) -> subprocess.Popen:
    """Start bcc execsnoop, transforming its output to jsonl.

    bcc execsnoop outputs TS-relative lines like:
    TIME(s) PARSENT COMM   PID    ARGS
    """
    exe = find_execsnoop()
    if not exe:
        raise RuntimeError("execsnoop not found — install bcc-tools")

    t0 = time.time()

    with out_jsonl.open("w") as f:
        proc = subprocess.Popen(
            [exe, "--timestamps"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        assert proc.stdout is not None
        # Skip header
        header = proc.stdout.readline()
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            parts = line.split()
            if len(parts) < 5:
                continue
            rec = {
                "ts": int((t0 + float(parts[0])) * 1e9),
                "pid": int(parts[3]),
                "ppid": int(parts[1]) if len(parts) > 1 else -1,
                "comm": parts[2],
                "argv": " ".join(parts[4:]),
                "source": "execsnoop",
            }
            f.write(json.dumps(rec) + "\n")
            f.flush()
    return proc


def fallback_audit(out_jsonl: Path, root_pid: int) -> subprocess.Popen:
    """Pure-Python fallback: poll /proc/<pid>/children of the root recursively.

    This is a best-effort audit that catches PIDs but NOT argv.
    Use only when neither bpftrace nor bcc are available.
    """
    # We sweep /proc periodically and log new PIDs we haven't seen.
    # This runs in a subprocess that writes to out_jsonl.
    script = f"""
import json, os, time, sys
seen = set()
root_pid = {root_pid}
out_path = "{out_jsonl}"
t0 = time.time()

def children_of(pid):
    try:
        return [int(c) for c in Path(f"/proc/{{pid}}/children").read_text().split()]
    except Exception:
        return []

def all_descendants(root):
    stack, result = [root], []
    while stack:
        pid = stack.pop()
        result.append(pid)
        stack.extend(children_of(pid))
    return result

with open(out_path, "w") as f:
    while Path(f"/proc/{{root_pid}}").exists():
        for pid in all_descendants(root_pid):
            if pid not in seen:
                seen.add(pid)
                rec = {{"ts": int((time.time() - t0) * 1e9), "pid": pid, "source": "audit_fallback"}}
                f.write(json.dumps(rec) + "\\n")
        f.flush()
        time.sleep(0.1)
"""
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Log every exec() during a run")
    p.add_argument("out_jsonl", type=Path, help="Output jsonl path")
    p.add_argument("--root-pid", type=int, default=0, help="Root PID for fallback mode")
    p.add_argument("--method", choices=["bpftrace", "execsnoop", "fallback", "auto"],
                   default="auto", help="Which method to use")
    args = p.parse_args()

    if args.method == "auto":
        if find_bpftrace():
            method = "bpftrace"
        elif find_execsnoop():
            method = "execsnoop"
        else:
            method = "fallback"
    else:
        method = args.method

    if method == "bpftrace":
        proc = run_bpftrace_snoop(args.out_jsonl)
    elif method == "execsnoop":
        proc = run_execsnoop_bcc(args.out_jsonl)
    else:
        proc = fallback_audit(args.out_jsonl, args.root_pid)

    def _cleanup(signum: int, frame: object) -> None:
        proc.terminate()
        proc.wait()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    # Wait until bpftrace/execsnoop exits (or we get killed)
    proc.wait()


if __name__ == "__main__":
    main()
