"""Claude Code adapter.

Claude Code is a Node.js/TypeScript CLI. Source available.
Headless mode: `claude -p <prompt>` (one-shot, prints to stdout, exits).
Local variant: invokes the same CLI with optional --model override.

Verified flags (from `claude --help`, May 2026):
  -p, --print             non-interactive, prints and exits
  --model <model>         model alias or full name (e.g. 'opus', 'claude-opus-4-7')
  --max-budget-usd <amt>   cap API spend (only with -p)
  --dangerously-skip-permissions   auto-approve all tool calls
  --output-format <fmt>    text (default), json, stream-json
  --no-session-persistence  don't save session to disk (only with -p)

Not available (recorded as caveat): temperature, seed, max-turns.
"""

from __future__ import annotations

from adapters.base import AgentAdapter, AgentCapabilities, TaskSpec


class ClaudeCodeAdapter(AgentAdapter):
    name = "claude_code"
    version = "1.0.0"
    capabilities = AgentCapabilities(
        headless=True,
        pin_model=True,
        pin_temperature=False,    # Claude Code does not expose temperature
        pin_seed=False,            # Claude Code does not expose seed
    )

    def docker_image(self) -> str:
        return f"agent-harness/claude_code:{self.version}"

    def env(self) -> dict[str, str]:
        return {
            "ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}",
            "NO_COLOR": "1",
        }

    def pin_flags(self) -> list[str]:
        return [
            "--model", "claude-opus-4-7",
        ]

    def build_command(self, task: TaskSpec) -> list[str]:
        return [
            "claude",
            "-p", task.prompt,
            *self.pin_flags(),
            "--max-budget-usd", "5",
            "--dangerously-skip-permissions",
            "--no-session-persistence",
        ]

    def local_command(self, task: TaskSpec) -> list[str]:
        return self.build_command(task)
