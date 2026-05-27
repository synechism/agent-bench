"""Codex (OpenAI) adapter.

Codex is OpenAI's coding agent. Open source, CLI via npm.
Headless mode: `codex exec <prompt>` (non-interactive, runs to completion).

Verified flags (from `codex exec --help`, May 2026):
  -m, --model <MODEL>          model the agent should use
  --dangerously-bypass-approvals-and-sandbox   auto-approve all tool calls
  --json                        print events as JSONL to stdout
  --skip-git-repo-check         allow running outside a git repo
  --ephemeral                   don't persist session files
  -c, --config <key=value>      override config.toml values (e.g. -c model="gpt-5.5")

Supports Azure via ~/.codex/config.toml [model_providers.azure] section.
Supports /model slash command to switch models interactively.
Wire API: "responses" (configured in config.toml).

Not available (recorded as caveat): temperature, max-turns.
"""

from __future__ import annotations

from adapters.base import AgentAdapter, AgentCapabilities, TaskSpec


class CodexAdapter(AgentAdapter):
    name = "codex"
    version = "0.1.0"
    capabilities = AgentCapabilities(
        headless=True,
        pin_model=True,
        pin_temperature=False,   # Codex does not expose temperature in CLI
        pin_seed=False,           # Codex does not expose seed
    )

    def docker_image(self) -> str:
        return f"agent-harness/codex:{self.version}"

    def env(self) -> dict[str, str]:
        return {
            "OPENAI_API_KEY": "${OPENAI_API_KEY}",
            "AZURE_API_KEY": "${AZURE_API_KEY}",     # for Azure users
            "NO_COLOR": "1",
        }

    def pin_flags(self) -> list[str]:
        return [
            "-m", "gpt-5.5",
        ]

    def build_command(self, task: TaskSpec) -> list[str]:
        return [
            "codex", "exec",
            *self.pin_flags(),
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            "--ephemeral",
            task.prompt,
        ]

    def local_command(self, task: TaskSpec) -> list[str]:
        return self.build_command(task)
