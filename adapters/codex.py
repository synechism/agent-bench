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
DeepSeek V4 can be enabled for experiment runs with
CODEX_DEEPSEEK_MOONBRIDGE=1. The Docker image wrapper starts Moon Bridge,
generates a per-run Codex config, and leaves the user's host Codex config alone.
Prompt ablations can set CODEX_MODEL_INSTRUCTIONS_FILE to replace the Codex base
instructions through Codex's model_instructions_file config.

Not available (recorded as caveat): temperature, max-turns.
"""

from __future__ import annotations

import os

from adapters.base import AgentAdapter, AgentCapabilities, TaskSpec


DEFAULT_CODEX_MODEL = "gpt-5.5"
MOONBRIDGE_MODEL = "moonbridge"


class CodexAdapter(AgentAdapter):
    name = "codex"
    version = "0.135.0"
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
            "DEEPSEEK_API_KEY": "${DEEPSEEK_API_KEY}",
            "CODEX_MODEL": "${CODEX_MODEL}",
            "CODEX_MODEL_PROVIDER": "${CODEX_MODEL_PROVIDER}",
            "CODEX_PROVIDER_BASE_URL": "${CODEX_PROVIDER_BASE_URL}",
            "CODEX_PROVIDER_ENV_KEY": "${CODEX_PROVIDER_ENV_KEY}",
            "CODEX_PROVIDER_WIRE_API": "${CODEX_PROVIDER_WIRE_API}",
            "CODEX_DEEPSEEK_MOONBRIDGE": "${CODEX_DEEPSEEK_MOONBRIDGE}",
            "CODEX_MOONBRIDGE_ADDR": "${CODEX_MOONBRIDGE_ADDR}",
            "MOONBRIDGE_DEEPSEEK_MODEL": "${MOONBRIDGE_DEEPSEEK_MODEL}",
            "CODEX_MODEL_INSTRUCTIONS_FILE": "${CODEX_MODEL_INSTRUCTIONS_FILE}",
            "CODEX_DEVELOPER_INSTRUCTIONS": "${CODEX_DEVELOPER_INSTRUCTIONS}",
            "CODEX_INCLUDE_PERMISSIONS_INSTRUCTIONS": "${CODEX_INCLUDE_PERMISSIONS_INSTRUCTIONS}",
            "CODEX_INCLUDE_SKILL_INSTRUCTIONS": "${CODEX_INCLUDE_SKILL_INSTRUCTIONS}",
            "CODEX_MCP_FIGMA_URL": "${CODEX_MCP_FIGMA_URL}",
            "CODEX_MCP_FIGMA_TOKEN_ENV_VAR": "${CODEX_MCP_FIGMA_TOKEN_ENV_VAR}",
            "FIGMA_FILE_URL": "${FIGMA_FILE_URL}",
            "FIGMA_NODE_ID": "${FIGMA_NODE_ID}",
            "FIGMA_API_TOKEN": "${FIGMA_API_TOKEN}",
            "NO_COLOR": "1",
        }

    def _use_moonbridge(self) -> bool:
        return os.environ.get("CODEX_DEEPSEEK_MOONBRIDGE", "").lower() in {"1", "true", "yes"}

    def pin_flags(self) -> list[str]:
        default_model = MOONBRIDGE_MODEL if self._use_moonbridge() else DEFAULT_CODEX_MODEL
        flags = ["-m", os.environ.get("CODEX_MODEL", default_model)]
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
        model_instructions_file = os.environ.get("CODEX_MODEL_INSTRUCTIONS_FILE")
        if model_instructions_file:
            flags.extend(["-c", f'model_instructions_file="{model_instructions_file}"'])
        developer_instructions = os.environ.get("CODEX_DEVELOPER_INSTRUCTIONS")
        if developer_instructions:
            flags.extend(["-c", f"developer_instructions={developer_instructions!r}"])
        include_permissions = os.environ.get("CODEX_INCLUDE_PERMISSIONS_INSTRUCTIONS")
        if include_permissions:
            flags.extend(["-c", f"include_permissions_instructions={include_permissions.lower()}"])
        include_skills = os.environ.get("CODEX_INCLUDE_SKILL_INSTRUCTIONS")
        if include_skills:
            flags.extend(["-c", f"include_skill_instructions={include_skills.lower()}"])
        figma_mcp_url = os.environ.get("CODEX_MCP_FIGMA_URL")
        if figma_mcp_url:
            flags.extend(["-c", f'mcp_servers.figma.url="{figma_mcp_url}"'])
        figma_token_env = os.environ.get("CODEX_MCP_FIGMA_TOKEN_ENV_VAR")
        if figma_mcp_url and figma_token_env:
            flags.extend(["-c", f'mcp_servers.figma.bearer_token_env_var="{figma_token_env}"'])
        return flags

    def build_command(self, task: TaskSpec) -> list[str]:
        binary = "codex-with-moonbridge" if self._use_moonbridge() else "codex"
        return [
            binary, "exec",
            *self.pin_flags(),
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            "--ephemeral",
            "--json",
            task.prompt,
        ]

    def local_command(self, task: TaskSpec) -> list[str]:
        return self.build_command(task)
