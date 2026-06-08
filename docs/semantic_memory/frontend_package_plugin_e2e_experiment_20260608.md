# Frontend Package/Plugin E2E Semantic-Memory Experiment

This experiment is a second long-horizon frontend benchmark. It increases
semantic-memory pressure beyond the coffee-roaster task by requiring multiple
third-party packages, unit tests, Playwright tests, and more than one
skill/plugin category when available.

## Task Shape

The task asks each agent to build an offline logistics command board for a
regional coastal-storm response team. The app must include:

- shelter supply levels
- vehicle dispatch priorities
- staff shift coverage
- incoming field requests
- a what-if planner for truck capacity and volunteer availability

The task explicitly requires package-backed behavior:

- Chart.js for a supply/capacity chart
- date-fns for timing
- zod for fixture/schema validation
- SortableJS for drag-and-drop dispatch ordering
- Fuse.js for fuzzy search
- lucide or lucide-static for icons
- Vitest for unit tests
- Playwright for browser tests

## Skill/Plugin Pressure

Each agent is instructed to inspect/use:

- `frontend-design`, if exposed
- a verification, browser-testing, run, or Playwright-related skill/plugin, if exposed

This should distinguish static skill inventory from actual skill-body/tool
consumption, while also producing a richer package/tool-call trace than the
single-skill coffee-roaster task.

## Run

```bash
python -m orchestrator.matrix --config harness_configs/harness_config_semantic_frontend_package_plugin_e2e.json --dry-run
CODEX_DEEPSEEK_MOONBRIDGE=1 \
CODEX_MODEL=moonbridge \
CODEX_PROVIDER_BASE_URL=http://127.0.0.1:38440/v1 \
MOONBRIDGE_DEEPSEEK_MODEL=deepseek-v4-pro \
HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1 \
HARNESS_API_OBSERVER_CAPTURE_CHARS=300000 \
CLAUDE_PLUGIN_DIR=/home/agent/.claude/plugins/cache/claude-plugins-official/frontend-design/unknown \
python -m orchestrator.matrix --config harness_configs/harness_config_semantic_frontend_package_plugin_e2e.json
```

If the combined matrix fails to load Claude's plugin, rerun the Claude cell with:

```bash
CLAUDE_PLUGIN_DIR=/home/agent/.claude/plugins/cache/claude-plugins-official/frontend-design/unknown \
HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1 \
HARNESS_API_OBSERVER_CAPTURE_CHARS=300000 \
python -m orchestrator.matrix --config harness_configs/harness_config_semantic_frontend_package_plugin_e2e_claude.json
```

## Completed Runs

The combined matrix completed two cells successfully:

| agent | run id | generation requests | outcome |
| --- | --- | ---: | --- |
| Codex | `20260608T014957_codex_frontend_package_plugin_app_frontend_package_plugin_ops_console_nocap_rep0` | 60 | Built the app, used both Codex skills, passed build and unit tests, wrote Playwright tests, hit the expected browser-library blocker. |
| Claude Code | `20260608T014957_claude_code_frontend_package_plugin_app_frontend_package_plugin_ops_console_nocap_rep0` | 71 | Built the app, invoked `frontend-design` and `verify`, passed build and unit tests, wrote Playwright tests, hit the expected browser-library blocker. |

Prompt capture was enabled for both cells. Codex stayed below the 300k request-body capture cap. Claude Code crossed that cap after request 54, but its stdout stream included exact per-generation response usage; those observed usage totals were used for the final 17 Claude context-token rows.

## Agent Outcomes

### Codex

Codex created a coastal storm response console with shelter supply charts, dispatch prioritization, shift coverage, request search, and a what-if planner. It installed and used `chart.js`, `date-fns`, `zod`, `sortablejs`, `fuse.js`, `lucide`, `vitest`, `@playwright/test`, and `@types/sortablejs`.

Codex discovered and read both available local skills:

- `frontend-design`
- `frontend-verification`

Verification result:

| check | result |
| --- | --- |
| Vite build | PASS |
| Vitest unit tests | PASS, 48/48 |
| Playwright tests | BLOCKED by missing `libglib-2.0.so.0` in the sandbox |

Nuance: Codex ran unit tests directly with `npx vitest run`; the final `package.json` did not include a `test:unit` script even though the task requested `npm run test:unit`.

### Claude Code

Claude Code created the same class of operations console and installed/used `chart.js`, `date-fns`, `zod`, `sortablejs`, `fuse.js`, `lucide-static`, `vitest`, `@playwright/test`, and `@types/sortablejs`.

Claude Code exposed and used plugin/skill layers visibly:

- `frontend-design:frontend-design`
- `verify`
- `run` was visible but not necessary as an explicit runtime path

Verification result:

| check | result |
| --- | --- |
| Vite build | PASS |
| Vitest unit tests | PASS, 68/68 |
| Playwright tests | BLOCKED by missing browser shared libraries, led by `libglib-2.0.so.0` |

Claude first hit test-suite separation issues: Vitest picked up the Playwright spec and one assertion/import was invalid. It then repaired the unit/E2E split with separate Vitest and Playwright configs and reached a clean unit-test pass before the browser-library blocker.

## Context-Growth Analysis

Generated artifacts:

- `docs/semantic_memory/context_growth_plots_frontend_package_plugin_20260608/README.md`
- `docs/semantic_memory/context_growth_plots_frontend_package_plugin_20260608/context_window_tokens.svg`
- `docs/semantic_memory/context_growth_plots_frontend_package_plugin_20260608/active_tools.svg`
- `docs/semantic_memory/context_growth_plots_frontend_package_plugin_20260608/skill_headers_loaded.svg`
- `docs/semantic_memory/context_growth_plots_frontend_package_plugin_20260608/active_skills.svg`
- `docs/semantic_memory/context_growth_plots_frontend_package_plugin_20260608/context_growth_timeseries.csv`
- `docs/semantic_memory/context_growth_plots_frontend_package_plugin_20260608/exact_context_tokens.jsonl`

Exact-token coverage is complete: 131/131 plotted generation requests have exact provider input-token totals. Codex requests were replayed through Moonbridge and counted after conversion. Claude requests were counted with the provider count endpoint where bodies were fully captured; the final 17 Claude requests use exact observed response usage from `stdout.log`.

Summary:

| agent | requests | duration min | peak context tokens | active tool counts | skill header counts | active skill counts |
| --- | ---: | ---: | ---: | --- | --- | --- |
| Codex | 60 | 8.82 | 71,011 | `[12]` | `[7]` | `[0, 1]` |
| Claude Code | 71 | 13.11 | 101,252 | `[0, 27]` | `[0, 14]` | `[0, 1, 2]` |

Interpretation:

- This task produced ordinary long-horizon parent-thread growth rather than the parent/subagent drops seen in earlier Redis tasks.
- Codex kept a stable 12-tool surface for every generation request.
- Claude Code had one initial zero-tool title request, then a stable 27-tool main-agent surface.
- Skill headers were present before active skill use; active skill counts rose only when the skill body/tool invocation entered the request context.
- Claude consumed a larger visible active context by the end of the run: about 101k input tokens versus Codex's about 71k.
