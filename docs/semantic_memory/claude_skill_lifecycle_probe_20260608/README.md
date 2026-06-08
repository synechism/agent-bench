# Claude Code Skill Lifecycle Probe - 2026-06-08

This report compares a baseline Claude Code brainstorm prompt with the same prompt run after exposing the Superpowers plugin.

## Runs

| run | plugins | init skill count | hook events | requests | skill invocations | loaded skill bodies |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `20260608T145327_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 1 | 13 | 0 | 4 | - | - |
| `20260608T145440_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 2 | 27 | 2 | 6 | superpowers:brainstorming | brainstorming |
| `20260608T145906_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 2 | 27 | 2 | 7 | superpowers:brainstorming | brainstorming |

## Hook Findings

### `20260608T145327_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0`

No hook events were observed before session init.

### `20260608T145440_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0`

- `hook_started` `SessionStart:startup` injected 0 additional-context chars (0 raw stdout chars); skill frontmatter names seen: none.
- `hook_response` `SessionStart:startup` injected 5,632 additional-context chars (5,973 raw stdout chars); skill frontmatter names seen: ['using-superpowers'].

### `20260608T145906_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0`

- `hook_started` `SessionStart:startup` injected 0 additional-context chars (0 raw stdout chars); skill frontmatter names seen: none.
- `hook_response` `SessionStart:startup` injected 5,632 additional-context chars (5,973 raw stdout chars); skill frontmatter names seen: ['using-superpowers'].

## Request Timeline

| run | request | skill headers | Skill calls | loaded bodies | loaded body chars |
| --- | ---: | ---: | --- | --- | ---: |
| `20260608T145327_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 1 | 0 | - | - | 0 |
| `20260608T145327_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 2 | 14 | - | - | 0 |
| `20260608T145327_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 3 | 14 | - | - | 0 |
| `20260608T145327_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 4 | 14 | - | - | 0 |
| `20260608T145440_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 1 | 28 | - | - | 0 |
| `20260608T145440_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 2 | 28 | superpowers:brainstorming | brainstorming | 10,640 |
| `20260608T145440_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 3 | 28 | superpowers:brainstorming | brainstorming | 10,640 |
| `20260608T145440_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 4 | 28 | superpowers:brainstorming | brainstorming | 10,640 |
| `20260608T145440_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 5 | 28 | superpowers:brainstorming | brainstorming | 10,640 |
| `20260608T145440_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 6 | 28 | superpowers:brainstorming | brainstorming | 10,640 |
| `20260608T145906_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 1 | 28 | - | - | 0 |
| `20260608T145906_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 2 | 28 | superpowers:brainstorming | brainstorming | 10,577 |
| `20260608T145906_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 3 | 28 | superpowers:brainstorming | brainstorming | 10,577 |
| `20260608T145906_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 4 | 28 | superpowers:brainstorming | brainstorming | 10,577 |
| `20260608T145906_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 5 | 28 | superpowers:brainstorming | brainstorming | 10,577 |
| `20260608T145906_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 6 | 28 | superpowers:brainstorming | brainstorming | 10,577 |
| `20260608T145906_claude_code_empty_baseline_claude_brainstorm_skill_probe_nocap_rep0` | 7 | 28 | superpowers:brainstorming | brainstorming | 10,577 |

## Interpretation

- Without Superpowers, the prompt used the word `brainstorm`, but no `brainstorming` skill was advertised or invoked.
- With Superpowers exposed, Claude Code's plugin hook injected `using-superpowers` before the first model request. That hook text tells the model to invoke relevant skills before any response.
- The first Superpowers generation request already contained Superpowers skill headers, including `superpowers:brainstorming`, `superpowers:writing-plans`, and execution/review skills.
- The model then invoked the `Skill` tool with `skill=superpowers:brainstorming`. The next request contained the full brainstorming skill body as a user-role tool result, and that body remained in subsequent request context.
- In this one-shot prompt, `writing-plans` was advertised but not invoked because the task explicitly stopped after brainstorming and the brainstorming skill requires user approval before transitioning to planning.

## Source-Adjacent Instrumentation Note

I added a Node preload probe at `instrumentation/claude_skill_fs_probe.js` and harness support via `CLAUDE_SKILL_FS_PROBE=1`. The probe logs skill/plugin-looking file reads and short JavaScript call stacks when a normal Node process reads skill files.

Smoke test: the probe works inside the `agent-harness/claude_code:latest` image for a plain `node -e` read of `skills/brainstorming/SKILL.md`.

Claude Code run: the same probe did not produce a filesystem log during the real Claude Code run, even though `NODE_OPTIONS` reached the container. That means this Claude Code image is not exposing the relevant skill-load path through normal Node preload hooks. The next safe instrumentation layer is OS-level file-open tracing around the official CLI, or an authorized instrumentable build. I did not clone or run source described as leaked proprietary code.

## Data

- `skill_lifecycle_timeline.csv`
- `skill_lifecycle_summary.json`
