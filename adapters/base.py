from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TaskSpec:
    kind: str  # "qa" | "feature" | "tests"
    prompt: str
    repo_path: str
    workdir: str


@dataclass
class InvocationResult:
    exit_code: int
    stdout_path: str
    stderr_path: str


@dataclass
class AgentCapabilities:
    """What the agent supports — recorded in manifest for caveat tracking."""

    headless: bool = True
    pin_model: bool = True
    pin_temperature: bool = True
    pin_seed: bool = False


class AgentAdapter(ABC):
    """Every agent implements this contract.

    Adding an agent = writing one of these + a Dockerfile (or local install script).
    The measurement layer to the right of this is entirely agent-agnostic.
    """

    name: str
    version: str
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)

    @abstractmethod
    def docker_image(self) -> str:
        """Tag of the prebuilt image containing this agent + measurement tooling."""

    @abstractmethod
    def env(self) -> dict[str, str]:
        """Auth + config. API keys injected from secrets, NEVER hard-coded."""

    @abstractmethod
    def pin_flags(self) -> list[str]:
        """Flags that pin model + temperature/seed for reproducibility.
        If the agent can't pin, record that as a known caveat in the manifest."""

    @abstractmethod
    def build_command(self, task: TaskSpec) -> list[str]:
        """The NON-INTERACTIVE command that runs `task` to completion and exits.

        This is the per-agent unknown — verify it exists for all agents on day 1.
        """

    def install_command(self) -> list[str]:
        """Optional: command to install the agent in the sandbox.
        Override if the agent can't be pre-baked into the Docker image."""
        return ["echo", "agent pre-installed in image"]

    def local_command(self, task: TaskSpec) -> list[str]:
        """Variant of build_command for local (non-Docker) execution.
        Default: same as build_command. Override if local invocation differs."""
        return self.build_command(task)
