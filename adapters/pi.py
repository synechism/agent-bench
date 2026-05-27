"""Pi (Google DeepMind) adapter.

Pi is a coding agent framework. Verify CLI availability and headless mode on day 1.
If Pi has no public CLI, this adapter wraps a subprocess invocation of the known
entrypoint after installation.
"""

from __future__ import annotations

from adapters.base import AgentAdapter, AgentCapabilities, TaskSpec


class PiAdapter(AgentAdapter):
    name = "pi"
    version = "0.1.0"
    capabilities = AgentCapabilities(
        headless=True,  # day-1 validation gate — verify
        pin_model=True,
        pin_temperature=True,
        pin_seed=False,
    )

    def docker_image(self) -> str:
        return f"agent-harness/pi:{self.version}"

    def env(self) -> dict[str, str]:
        return {
            "GOOGLE_API_KEY": "${GOOGLE_API_KEY}",
            "NO_COLOR": "1",
        }

    def pin_flags(self) -> list[str]:
        return [
            "--model", "gemini-2.5-pro",
            "--temperature", "0.0",
        ]

    def build_command(self, task: TaskSpec) -> list[str]:
        return [
            "pi",
            "run",
            *self.pin_flags(),
            "--non-interactive",
            "--max-turns", "50",
            task.prompt,
        ]

    def local_command(self, task: TaskSpec) -> list[str]:
        return self.build_command(task)
