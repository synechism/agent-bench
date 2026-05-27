"""Pydantic models for run configuration and manifest.

All config is declarative and serializable — runs can be reproduced from the manifest.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class TaskKind(str, Enum):
    baseline = "baseline"
    qa = "qa"
    feature = "feature"
    tests = "tests"


class Caps(BaseModel):
    """Resource caps applied to the run sandbox."""
    memory_mb: int | None = None    # memory.max in MB (None = no cap)
    cpu_cores: float | None = None  # CPU quota (None = no cap)
    disk_gb: int | None = None      # disk quota (None = no cap)


class CodebaseRef(BaseModel):
    """A pinned codebase checkout."""
    repo_url: str
    commit: str
    language: str  # inferred: python, rust, typescript, c, ...


class TaskDef(BaseModel):
    """Definition of a single task — what the agent is asked to do."""
    kind: TaskKind
    name: str
    prompt: str
    codebase: str                     # key into registry.yaml
    oracle: dict[str, Any] = Field(default_factory=dict)
    # For "baseline": oracle = {"expected_text": "BASELINE_OK"}
    # For "qa": oracle = {"relevant_files": [...]}
    # For "feature": oracle = {"diff_url": "...", "test_cmd": "..."}
    # For "tests": oracle = {"pass_exit_code": 0, "timeout_s": 600}


class RunManifest(BaseModel):
    """Immutable record of everything that defines a single run.

    This is the source of truth for analysis. Every field is pinned.
    """
    run_id: str
    agent: str
    agent_version: str
    agent_capabilities: dict[str, bool] = Field(default_factory=dict)
    task: TaskDef
    codebase: CodebaseRef
    caps: Caps = Field(default_factory=Caps)
    seed: int | None = None
    rep: int = 0                      # repetition index (0..N-1)

    # Environment
    hostname: str = ""
    hardware: dict[str, Any] = Field(default_factory=dict)  # CPU model, RAM, kernel version
    sandbox: str = "docker"           # "docker" | "local"

    # Timestamps filled at start/end
    started_at: str = ""
    completed_at: str = ""

    # Cached for analysis
    caveats: list[str] = Field(default_factory=list)

    @staticmethod
    def make_run_id(
        agent: str,
        codebase_name: str,
        task_name: str,
        memory_cap: int | None,
        rep: int,
    ) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        cap = f"mem{memory_cap}M" if memory_cap else "nocap"
        return f"{ts}_{agent}_{codebase_name}_{task_name}_{cap}_rep{rep}"


class RunConfig(BaseModel):
    """Top-level configuration for the benchmarking platform."""
    agents: list[str] = Field(default_factory=lambda: [
        "claude_code", "codex", "pi", "opencode"
    ])
    codebases: list[str] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list)
    memory_caps: list[int | None] = Field(default_factory=lambda: [None])
    repetitions: int = 5
    sandbox: str = "docker"
    runs_dir: Path = Path("runs")
    timeout_per_run: int = 1800  # 30 min default
    parallel_jobs: int = 1        # >1 runs cells concurrently; best for iteration

    # API token log (off by default)
    log_api_usage: bool = True
