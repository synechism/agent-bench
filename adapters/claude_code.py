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

This benchmark environment runs Claude Code against DeepSeek V4 through the
Anthropic-compatible endpoint configured in the host environment:
  ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
  ANTHROPIC_MODEL=deepseek-v4-pro[1m]

Not available (recorded as caveat): temperature, seed, max-turns.
"""

from __future__ import annotations

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
            "NO_COLOR": "1",
        }

    def pin_flags(self) -> list[str]:
        return [
            "--model", CLAUDE_CODE_MODEL,
        ]

    def build_command(self, task: TaskSpec) -> list[str]:
        return [
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

    def local_command(self, task: TaskSpec) -> list[str]:
        return self.build_command(task)
