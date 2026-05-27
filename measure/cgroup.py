"""Per-process cgroup helpers (week 2 upgrade).

Kernel-accurate peak memory via memory.peak, no sampling gap.
Put each subprocess in its own cgroup before exec, read memory.peak after exit.

Resolve cgroup base path generically via /proc/<pid>/cgroup — don't hard-code
the cgroup driver (cgroupfs vs systemd).
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_cgroup_base(root_pid: int, controller: str = "memory") -> str:
    """Find the cgroup base path for this container/process.

    Reads /proc/<root_pid>/cgroup to resolve the cgroupfs mount path regardless
    of whether Docker uses cgroupfs v1, v2, or systemd.
    Returns the directory containing controller files like memory.peak.
    """
    cgroup_path = None
    try:
        for line in Path(f"/proc/{root_pid}/cgroup").read_text().splitlines():
            parts = line.strip().split(":")
            if len(parts) < 3:
                continue
            controllers = parts[1]
            path = parts[2]
            if controller in controllers or controller == "":
                cgroup_path = path
                break
    except (FileNotFoundError, ProcessLookupError):
        pass

    if cgroup_path is None:
        return f"/sys/fs/cgroup/{controller}"

    # cgroup v2: single unified hierarchy, mount is /sys/fs/cgroup
    # cgroup v1: controller-specific, mount is /sys/fs/cgroup/<controller>
    for candidate in [
        f"/sys/fs/cgroup{cgroup_path}",
        f"/sys/fs/cgroup/{controller}{cgroup_path}",
    ]:
        if os.path.isdir(candidate):
            return candidate

    return f"/sys/fs/cgroup{cgroup_path}"


def create_tool_cgroup(
    base: str, tool: str, pid: int
) -> str | None:
    """Create a per-tool per-process cgroup directory.

    Returns the cgroup path if created, or None if not possible.
    The shim writes $$ to <cgroup>/cgroup.procs before exec.
    """
    cg_name = f"bench-{tool}-{pid}"
    cg_path = os.path.join(base, cg_name)
    try:
        os.makedirs(cg_path, exist_ok=True)
        return cg_path
    except (PermissionError, OSError):
        return None


def read_memory_peak(cg_path: str) -> int | None:
    """Read memory.peak from a cgroup (cgroup v2 only). Returns bytes or None."""
    peak_file = os.path.join(cg_path, "memory.peak")
    try:
        return int(Path(peak_file).read_text().strip())
    except (FileNotFoundError, PermissionError, ValueError):
        return None


def read_cpu_stat(cg_path: str) -> dict[str, int]:
    """Read cpu.stat from a cgroup (cgroup v2)."""
    stat_file = os.path.join(cg_path, "cpu.stat")
    result: dict[str, int] = {}
    try:
        for line in Path(stat_file).read_text().splitlines():
            key, val = line.strip().split()
            result[key] = int(val)
    except (FileNotFoundError, PermissionError, ValueError):
        pass
    return result


def cleanup_cgroup(cg_path: str) -> None:
    """Remove a cgroup directory after the process exits."""
    try:
        os.rmdir(cg_path)
    except OSError:
        pass
