# Codex vs. Claude Code Context Growth Plots - 2026-06-04

This report plots the matched representative task runs at the level of model API requests. Each point is one request captured in `prompt_payloads.jsonl`; the x-axis is elapsed wall-clock time from the first captured request in that run.

## Definitions

- `context_tokens`: sum of `semantic_layers[*].approx_tokens` for the request. This is a semantic approximation of context-window occupancy, not a provider billing counter.
- `active_tools`: count of top-level tools advertised to the model on that request.
- `skill_headers_loaded`: count of skill names visible in the developer/skills inventory text.
- `active_skills`: count of visible `Skill` tool invocations in the request context.

## Plots

![Context window size](context_window_tokens.svg)

![Active tools](active_tools.svg)

![Skill headers loaded](skill_headers_loaded.svg)

![Active skills](active_skills.svg)

## Summary Table

| task | agent | requests | duration min | peak context toks | tool counts | skill header counts | active skill counts |
| --- | --- | ---: | ---: | ---: | --- | --- | --- |
| Empty baseline | Codex | 1 | 0.00 | 12,304 | [12] | [5] | [0] |
| Empty baseline | Claude Code | 2 | 0.00 | 21,273 | [0, 27] | [0, 13] | [0] |
| Redis GETEX QA | Codex | 23 | 2.16 | 20,459 | [12] | [5] | [0] |
| Redis GETEX QA | Claude Code | 17 | 2.29 | 34,205 | [0, 27] | [0, 13] | [0] |
| Redis GETEX tests | Codex | 112 | 9.05 | 40,401 | [12] | [5] | [0] |
| Redis GETEX tests | Claude Code | 28 | 4.08 | 68,505 | [0, 17, 27] | [0, 13] | [0] |
| Redis EXPIRE feature | Codex | 57 | 5.95 | 38,717 | [12] | [5] | [0] |
| Redis EXPIRE feature | Claude Code | 63 | 10.62 | 67,361 | [0, 17, 27] | [0, 13] | [0] |

## Interpretation Notes

- Claude Code has an initial title/metadata-style request with no tools before the main agent request. That request is included because it is a real captured model request; the main-agent context jump appears immediately after it.
- Codex advertises a stable 12-tool surface in these representative runs. Claude Code alternates between a 27-tool main-agent surface and a 17-tool reduced surface in the more complex runs.
- Skill headers are available-context, not actual skill activation. In these matched runs, the skill inventory is loaded, but actual skill activation remains zero.
- The CSV next to this report includes layer-level token columns and `body_approx_tokens` so the semantic total can be audited against raw request-body size.

## Data

- Raw time series: `context_growth_timeseries.csv`
