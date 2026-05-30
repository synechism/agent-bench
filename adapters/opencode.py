"""OpenCode adapter.

OpenCode is an open-source CLI coding agent.
Headless mode: `opencode run <prompt>` or similar. Verify on day 1.
"""

from __future__ import annotations

from adapters.base import AgentAdapter, AgentCapabilities, TaskSpec


class OpenCodeAdapter(AgentAdapter):
    name = "opencode"
    version = "0.1.0"
    capabilities = AgentCapabilities(
        headless=True,  # day-1 validation gate — verify
        pin_model=True,
        pin_temperature=True,
        pin_seed=False,
    )

    def docker_image(self) -> str:
        return "agent-harness/opencode:latest"

    def env(self) -> dict[str, str]:
        return {
            "OPENAI_API_KEY": "${OPENAI_API_KEY}",
            "ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}",
            "NO_COLOR": "1",
        }

    def pin_flags(self) -> list[str]:
        return [
            "--model", "claude-sonnet-4-6",
            "--temperature", "0.0",
        ]

    def build_command(self, task: TaskSpec) -> list[str]:
        return [
            "opencode",
            "run",
            *self.pin_flags(),
            "--yes",
            "--max-turns", "50",
            task.prompt,
        ]

    def local_command(self, task: TaskSpec) -> list[str]:
        return self.build_command(task)
