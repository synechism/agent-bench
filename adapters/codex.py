"""Codex (OpenAI) adapter.

Codex is OpenAI's coding agent. Open source, CLI via npm.
Headless mode: `codex exec <prompt>` (non-interactive, runs to completion).

Verified flags (from `codex exec --help`, May 2026):
  -m, --model <MODEL>          model the agent should use
  --dangerously-bypass-approvals-and-sandbox   auto-approve all tool calls
  --json                        print events as JSONL to stdout
  --skip-git-repo-check         allow running outside a git repo
  --ephemeral                   don't persist session files
  -c, --config <key=value>      override config.toml values (e.g. -c model="deepseek-v4-pro")

Supports Azure via ~/.codex/config.toml [model_providers.azure] section.
Supports /model slash command to switch models interactively.
Wire API: "responses" (configured in config.toml).

Not available (recorded as caveat): temperature, max-turns.
"""

from __future__ import annotations

import os

from adapters.base import AgentAdapter, AgentCapabilities, TaskSpec


DEFAULT_CODEX_MODEL = "gpt-5.5"


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
        return "agent-harness/codex:latest"

    def env(self) -> dict[str, str]:
        return {
            "OPENAI_API_KEY": "${OPENAI_API_KEY}",
            "AZURE_API_KEY": "${AZURE_API_KEY}",     # for Azure users
            "ANTHROPIC_AUTH_TOKEN": "${ANTHROPIC_AUTH_TOKEN}",  # for custom provider probes
            "CODEX_MODEL": "${CODEX_MODEL}",
            "CODEX_MODEL_PROVIDER": "${CODEX_MODEL_PROVIDER}",
            "CODEX_PROVIDER_BASE_URL": "${CODEX_PROVIDER_BASE_URL}",
            "CODEX_PROVIDER_ENV_KEY": "${CODEX_PROVIDER_ENV_KEY}",
            "CODEX_PROVIDER_WIRE_API": "${CODEX_PROVIDER_WIRE_API}",
            "NO_COLOR": "1",
        }

    def pin_flags(self) -> list[str]:
        flags = ["-m", os.environ.get("CODEX_MODEL", DEFAULT_CODEX_MODEL)]
        provider = os.environ.get("CODEX_MODEL_PROVIDER")
        if provider:
            flags.extend(["-c", f'model_provider="{provider}"'])
        provider_base_url = os.environ.get("CODEX_PROVIDER_BASE_URL")
        if provider and provider_base_url:
            flags.extend(["-c", f'model_providers.{provider}.base_url="{provider_base_url}"'])
        provider_env_key = os.environ.get("CODEX_PROVIDER_ENV_KEY")
        if provider and provider_env_key:
            flags.extend(["-c", f'model_providers.{provider}.env_key="{provider_env_key}"'])
        provider_wire_api = os.environ.get("CODEX_PROVIDER_WIRE_API")
        if provider and provider_wire_api:
            flags.extend(["-c", f'model_providers.{provider}.wire_api="{provider_wire_api}"'])
        return flags

    def build_command(self, task: TaskSpec) -> list[str]:
        return [
            "codex", "exec",
            *self.pin_flags(),
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            "--ephemeral",
            "--json",
            task.prompt,
        ]

    def local_command(self, task: TaskSpec) -> list[str]:
        return self.build_command(task)
