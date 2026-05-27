from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Any


def _read_first_existing(paths: list[Path]) -> str | None:
    for path in paths:
        try:
            return path.read_text().strip()
        except (FileNotFoundError, PermissionError, OSError):
            continue
    return None


def _read_meminfo() -> dict[str, int]:
    result: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, raw_value = line.split(":", 1)
            parts = raw_value.split()
            if parts:
                result[key] = int(parts[0]) * 1024
    except (FileNotFoundError, PermissionError, ValueError):
        pass
    return result


def _cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except (FileNotFoundError, PermissionError, IndexError):
        pass
    return platform.processor() or "unknown"


def _cgroup_relative_path() -> str:
    try:
        for line in Path("/proc/self/cgroup").read_text().splitlines():
            parts = line.split(":")
            if len(parts) == 3 and (parts[1] == "" or "memory" in parts[1]):
                return parts[2].lstrip("/")
    except (FileNotFoundError, PermissionError):
        pass
    return ""


def _cgroup_path() -> Path:
    rel = _cgroup_relative_path()
    return Path("/sys/fs/cgroup") / rel


def _parse_cgroup_value(value: str | None) -> int | str | None:
    if value is None or value == "":
        return None
    if value == "max":
        return "max"
    try:
        return int(value)
    except ValueError:
        return value


def _collect_cgroup_info() -> dict[str, Any]:
    path = _cgroup_path()
    cpu_max = _read_first_existing([path / "cpu.max"])
    result: dict[str, Any] = {
        "path": str(path),
        "memory_max_bytes": _parse_cgroup_value(_read_first_existing([path / "memory.max"])),
        "memory_current_bytes": _parse_cgroup_value(_read_first_existing([path / "memory.current"])),
        "memory_swap_max_bytes": _parse_cgroup_value(_read_first_existing([path / "memory.swap.max"])),
        "cpuset_cpus": _read_first_existing([path / "cpuset.cpus.effective", path / "cpuset.cpus"]),
        "cpu_max": cpu_max,
    }

    if cpu_max:
        parts = cpu_max.split()
        if len(parts) == 2 and parts[0] != "max":
            try:
                quota_us = int(parts[0])
                period_us = int(parts[1])
                result["cpu_quota_cores"] = quota_us / period_us
            except (ValueError, ZeroDivisionError):
                pass
    return result


def _collect_gpu_info() -> list[dict[str, Any]]:
    query = "name,uuid,memory.total,driver_version,pci.bus_id"
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                f"--query-gpu={query}",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []

    gpus: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 5:
            continue
        name, uuid, memory_total_mib, driver_version, pci_bus_id = parts
        try:
            memory_total = int(memory_total_mib)
        except ValueError:
            memory_total = 0
        gpus.append(
            {
                "name": name,
                "uuid": uuid,
                "memory_total_mib": memory_total,
                "driver_version": driver_version,
                "pci_bus_id": pci_bus_id,
            }
        )
    return gpus


def collect_host_info() -> dict[str, Any]:
    """Collect benchmark-host metadata that can affect resource comparisons."""
    meminfo = _read_meminfo()
    swap_total = meminfo.get("SwapTotal", 0)
    return {
        "system": {
            "platform": platform.platform(),
            "kernel": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "cpu": {
            "model": _cpu_model(),
            "logical_count": os.cpu_count(),
        },
        "memory": {
            "mem_total_bytes": meminfo.get("MemTotal", 0),
            "mem_available_bytes": meminfo.get("MemAvailable", 0),
            "swap_total_bytes": swap_total,
            "swap_enabled": swap_total > 0,
        },
        "cgroup": _collect_cgroup_info(),
        "gpus": _collect_gpu_info(),
    }
