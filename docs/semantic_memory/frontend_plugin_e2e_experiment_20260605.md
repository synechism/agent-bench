# Frontend Plugin E2E Semantic-Memory Experiment

This is the no-auth replacement for the Figma MCP experiment. It removes Figma,
MCP, screenshots, and local design artifacts. The design pressure comes from
agent-visible design skills/plugins plus a product brief.

## Setup

Claude Code:

- Installed user plugin: `frontend-design@claude-plugins-official`.
- The harness now copies `~/.claude/plugins` into the per-run Docker home so the
  plugin can participate in benchmark runs.

Codex:

- Added local skill: `~/.codex/skills/frontend-design/SKILL.md`.
- The harness already copies `~/.codex/skills` into the per-run Docker home.

## Run

```bash
python -m orchestrator.matrix --config harness_configs/harness_config_semantic_frontend_plugin_e2e.json --dry-run
CODEX_DEEPSEEK_MOONBRIDGE=1 \
CODEX_MODEL=moonbridge \
CODEX_PROVIDER_BASE_URL=http://127.0.0.1:38440/v1 \
MOONBRIDGE_DEEPSEEK_MODEL=deepseek-v4-pro \
HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1 \
HARNESS_API_OBSERVER_CAPTURE_CHARS=300000 \
python -m orchestrator.matrix --config harness_configs/harness_config_semantic_frontend_plugin_e2e.json
```

The run compares Codex and Claude Code on:

- product brief to designed app
- implementation in a Vite/TypeScript scaffold
- Playwright desktop and mobile tests
- exact prompt/context growth over a longer frontend workflow
- active tool counts
- skill/plugin headers and active skill/plugin invocation signals

## Why This Helps

The Redis tasks rarely needed skills. This task gives both agents an explicit
reason to consume frontend design guidance and browser-test context. It should
show whether skill/plugin metadata remains static, whether skill bodies are
loaded on demand, and whether longer implementation/test cycles produce new
context-window behavior beyond the parent/subagent drops already observed in
Claude Code.

## Completed Run

The full Codex run completed under:

- `runs/20260605T142450_codex_frontend_plugin_app_frontend_plugin_design_to_playwright_app_nocap_rep0`

The first Claude Code attempt did not load the plugin because the adapter was
not yet passing `--plugin-dir`; after patching the adapter and rebuilding the
image, the plugin-backed Claude-only rerun completed under:

- `runs/20260605T143603_claude_code_frontend_plugin_app_frontend_plugin_design_to_playwright_app_nocap_rep0`

Both agents built the app and attempted Playwright verification. In both cases,
the app/test work reached the browser-launch stage, but Playwright execution was
blocked by missing Linux desktop libraries in the benchmark container. This is
still useful for semantic-memory analysis because the implementation and
verification attempts produced long parent-thread histories and skill/plugin
activation.

## Plot Outputs

Fresh exact-token plots for this scenario are in:

- `docs/semantic_memory/context_growth_plots_frontend_plugin_20260605/`

Generated artifacts:

- `context_window_tokens.svg`
- `active_tools.svg`
- `skill_headers_loaded.svg`
- `active_skills.svg`
- `context_growth_timeseries.csv`
- `exact_context_tokens.jsonl`

The exact-token backfill counted all 77 generation requests:

| agent | requests | peak input tokens | active tools | skill headers | active skills |
| --- | ---: | ---: | --- | --- | --- |
| Codex | 45 | 59,339 | `[12]` | `[6]` | `[0, 1]` |
| Claude Code | 32 | 58,489 | `[0, 27]` | `[0, 14]` | `[0, 1]` |

Interpretation: this run did not trigger Claude Code Explore subagents, so the
active-tool plot is mostly flat. That makes it a clean skill/plugin-consumption
case: skill headers are loaded before use, then `active_skills` flips on when
Codex reads `frontend-design/SKILL.md` and when Claude Code invokes the
`frontend-design:frontend-design` Skill tool and receives the synthetic skill
body message.
