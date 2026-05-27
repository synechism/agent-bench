from __future__ import annotations

import argparse
import csv
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any


def read_smaps_rollup(pid: int) -> dict[str, int]:
    """Read PSS, RSS, USS from /proc/<pid>/smaps_rollup.

    PSS = proportional set size (shared pages divided by share count).
    USS = Private_Clean + Private_Dirty (pages unique to this process).
    RSS = resident set size (what htop/docker stats show; double-counts shared).
    """
    out: dict[str, int] = {"pss": 0, "uss": 0, "rss": 0}
    try:
        text = Path(f"/proc/{pid}/smaps_rollup").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return out

    for line in text.splitlines():
        if line.startswith("Pss:"):
            out["pss"] = int(line.split()[1]) * 1024  # kB -> bytes
        elif line.startswith("Rss:"):
            out["rss"] = int(line.split()[1]) * 1024
        elif line.startswith("Private_Clean:"):
            out["uss"] += int(line.split()[1]) * 1024
        elif line.startswith("Private_Dirty:"):
            out["uss"] += int(line.split()[1]) * 1024
    return out


def read_stat(pid: int) -> dict[str, Any]:
    
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return {}

    try:
        comm = raw[raw.index("(") + 1 : raw.rindex(")")]
        rest = raw[raw.rindex(")") + 2 :].split()
        return {
            "comm": comm,
            "ppid": int(rest[1]),
            "utime": int(rest[11]),
            "stime": int(rest[12]),
            "num_threads": int(rest[17]),
            "starttime": int(rest[19]),
        }
    except (ValueError, IndexError):
        return {}


def build_children_map() -> dict[int, list[int]]:
    """Scan /proc once and build pid -> [child pids] mapping."""
    children: dict[int, list[int]] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        st = read_stat(int(entry))
        if st:
            children.setdefault(st["ppid"], []).append(int(entry))
    return children


def descendants(root_pid: int, children: dict[int, list[int]]) -> list[int]:
    """Collect all PIDs in the process tree rooted at root_pid.

    Rebuilds children table each tick because processes are born and die constantly.
    """
    seen: list[int] = []
    stack = [root_pid]
    while stack:
        pid = stack.pop()
        seen.append(pid)
        stack.extend(children.get(pid, []))
    return seen


def sample(
    root_pid: int,
    out_csv: Path,
    interval: float = 0.25,
    stop_on_exit: bool = True,
) -> None:
    """Walk the process tree every `interval` seconds, writing one row per PID.

    Stops when the root PID exits (or on SIGTERM/SIGINT).
    0.25s sampling still misses ~50ms tool calls — execsnoop + exit-rusage cover those.
    """
    running = True

    def _handle(signum: int, frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    jiffy = os.sysconf(os.sysconf_names["SC_CLK_TCK"])

    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "ts", "pid", "ppid", "comm", "pss", "uss", "rss",
            "utime", "stime", "num_threads",
        ])
        t0 = time.time()

        while running:
            if stop_on_exit and not Path(f"/proc/{root_pid}").exists():
                break

            now = time.time() - t0
            children = build_children_map()
            for pid in descendants(root_pid, children):
                m, st = read_smaps_rollup(pid), read_stat(pid)
                if not st:
                    continue
                w.writerow([
                    f"{now:.3f}",
                    pid,
                    st["ppid"],
                    st["comm"],
                    m["pss"],
                    m["uss"],
                    m["rss"],
                    st["utime"],
                    st["stime"],
                    st["num_threads"],
                ])
            f.flush()
            time.sleep(interval)


def csv_to_parquet(csv_path: Path, parquet_path: Path) -> None:
    """Convert sampled CSV to parquet for efficient analysis."""
    import pandas as pd

    df = pd.read_csv(csv_path)
    df.to_parquet(parquet_path, index=False)


def main() -> None:
    p = argparse.ArgumentParser(description="Sample process tree resource usage")
    p.add_argument("root_pid", type=int, help="Root PID of the agent process tree")
    p.add_argument("out_csv", type=Path, help="Output CSV path")
    p.add_argument("--interval", type=float, default=0.25, help="Sampling interval in seconds")
    p.add_argument("--parquet", type=Path, default=None, help="Also convert to parquet at end")
    args = p.parse_args()

    sample(args.root_pid, args.out_csv, args.interval)
    if args.parquet:
        csv_to_parquet(args.out_csv, args.parquet)


if __name__ == "__main__":
    main()
