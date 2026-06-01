"""Pi adapter.

Pi is a lightweight terminal coding harness. For DeepSeek experiment runs, the
Docker image uses a small wrapper that writes a per-run Pi ``models.json`` and
then invokes the public ``@earendil-works/pi-coding-agent`` CLI.
"""

from __future__ import annotations

from adapters.base import AgentAdapter, AgentCapabilities, TaskSpec


class PiAdapter(AgentAdapter):
    name = "pi"
    version = "0.78.0-deepseek-v4"
    capabilities = AgentCapabilities(
        headless=True,
        pin_model=True,
        pin_temperature=False,
        pin_seed=False,
    )

    def docker_image(self) -> str:
        return "agent-harness/pi:latest"

    def env(self) -> dict[str, str]:
        return {
            "DEEPSEEK_API_KEY": "${DEEPSEEK_API_KEY}",
            "PI_DEEPSEEK_BASE_URL": "${PI_DEEPSEEK_BASE_URL}",
            "PI_DEEPSEEK_MODEL": "${PI_DEEPSEEK_MODEL}",
            "PI_CODING_AGENT_DIR": "${PI_CODING_AGENT_DIR}",
            "PI_TELEMETRY": "0",
            "NO_COLOR": "1",
        }

    def pin_flags(self) -> list[str]:
        return [
            "--model", "deepseek/deepseek-v4-pro",
            "--thinking", "high",
        ]

    def build_command(self, task: TaskSpec) -> list[str]:
        return [
            "pi-with-deepseek",
            *self.pin_flags(),
            "--print",
            "--mode", "json",
            "--no-session",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-themes",
            "--tools", "read,bash,edit,write,grep,find,ls",
            task.prompt,
        ]

    def local_command(self, task: TaskSpec) -> list[str]:
        return self.build_command(task)
