"""Claude Code adapter.

Claude Code is a Node.js/TypeScript CLI. Source available.
Headless mode: `claude -p <prompt>` (one-shot, prints to stdout, exits).
Local variant: invokes the same CLI with optional --model override.

Verified flags (from `claude --help`, May 2026):
  -p, --print             non-interactive, prints and exits
  --model <model>         model alias or full name
  --max-budget-usd <amt>   cap API spend (only with -p)
  --dangerously-skip-permissions   auto-approve all tool calls
  --output-format <fmt>    text (default), json, stream-json
  --include-hook-events     include hook lifecycle events in stream-json output
  --no-session-persistence  don't save session to disk (only with -p)
  --system-prompt-file <path> replace the default system prompt for ablation runs
  --append-system-prompt-file <path> append an extra system prompt for steering runs
  --tools <tools>            restrict available built-in tools

This benchmark environment runs Claude Code against DeepSeek V4 through the
Anthropic-compatible endpoint configured in the host environment:
  ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
  ANTHROPIC_MODEL=deepseek-v4-pro[1m]

Not available (recorded as caveat): temperature, seed, max-turns.
"""

from __future__ import annotations

import os

from adapters.base import AgentAdapter, AgentCapabilities, TaskSpec


CLAUDE_CODE_MODEL = "deepseek-v4-pro[1m]"


class ClaudeCodeAdapter(AgentAdapter):
    name = "claude_code"
    version = "2.1.156-deepseek-v4"
    capabilities = AgentCapabilities(
        headless=True,
        pin_model=True,
        pin_temperature=False,    # Claude Code does not expose temperature
        pin_seed=False,            # Claude Code does not expose seed
    )

    def docker_image(self) -> str:
        return "agent-harness/claude_code:latest"

    def env(self) -> dict[str, str]:
        return {
            # API-key users.
            "ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}",
            # DeepSeek / Anthropic-compatible gateway users.
            "ANTHROPIC_AUTH_TOKEN": "${ANTHROPIC_AUTH_TOKEN}",
            "ANTHROPIC_BASE_URL": "${ANTHROPIC_BASE_URL}",
            "ANTHROPIC_MODEL": "${ANTHROPIC_MODEL}",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "${ANTHROPIC_DEFAULT_OPUS_MODEL}",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "${ANTHROPIC_DEFAULT_SONNET_MODEL}",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "${ANTHROPIC_DEFAULT_HAIKU_MODEL}",
            "CLAUDE_CODE_SUBAGENT_MODEL": "${CLAUDE_CODE_SUBAGENT_MODEL}",
            "CLAUDE_CODE_EFFORT_LEVEL": "${CLAUDE_CODE_EFFORT_LEVEL}",
            "CLAUDE_SYSTEM_PROMPT_FILE": "${CLAUDE_SYSTEM_PROMPT_FILE}",
            "CLAUDE_APPEND_SYSTEM_PROMPT_FILE": "${CLAUDE_APPEND_SYSTEM_PROMPT_FILE}",
            "CLAUDE_TOOLS": "${CLAUDE_TOOLS}",
            "CLAUDE_BARE": "${CLAUDE_BARE}",
            "CLAUDE_DISABLE_SLASH_COMMANDS": "${CLAUDE_DISABLE_SLASH_COMMANDS}",
            "NO_COLOR": "1",
        }

    def pin_flags(self) -> list[str]:
        return [
            "--model", CLAUDE_CODE_MODEL,
        ]

    def build_command(self, task: TaskSpec) -> list[str]:
        command = [
            "claude",
            "-p", task.prompt,
            *self.pin_flags(),
            "--max-budget-usd", "5",
            "--dangerously-skip-permissions",
            "--no-session-persistence",
            "--output-format", "stream-json",
            "--include-hook-events",
            "--verbose",
        ]
        system_prompt_file = os.environ.get("CLAUDE_SYSTEM_PROMPT_FILE")
        if system_prompt_file:
            command.extend(["--system-prompt-file", system_prompt_file])
        append_system_prompt_file = os.environ.get("CLAUDE_APPEND_SYSTEM_PROMPT_FILE")
        if append_system_prompt_file:
            command.extend(["--append-system-prompt-file", append_system_prompt_file])
        tools = os.environ.get("CLAUDE_TOOLS")
        if tools is not None and tools != "":
            command.extend(["--tools", tools])
        if os.environ.get("CLAUDE_BARE", "").lower() in {"1", "true", "yes"}:
            command.append("--bare")
        if os.environ.get("CLAUDE_DISABLE_SLASH_COMMANDS", "").lower() in {"1", "true", "yes"}:
            command.append("--disable-slash-commands")
        return command

    def local_command(self, task: TaskSpec) -> list[str]:
        return self.build_command(task)
