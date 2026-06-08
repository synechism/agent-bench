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

## What Superpowers Adds

Adding Superpowers does **not** cause Claude Code to load every Superpowers skill body into the first request. The observed layering is:

1. **Plugin discovery:** `--plugin-dir .../superpowers` makes Claude Code discover the plugin. The session `init` event then lists Superpowers skills as available user-invocable skills.
2. **Skill inventory/header load:** the model request gets names and descriptions for available skills. In this probe, visible skill headers rose from 14 without Superpowers to 28 with Superpowers. These are metadata entries, not full `SKILL.md` bodies.
3. **Startup hook injection:** Superpowers registers a `SessionStart` hook in `hooks/hooks.json`. That hook injects the full `using-superpowers` skill into the session before the first model request. In our run, the hook injected 5,632 chars of additional context. This is the main unconditional Superpowers startup cost.
4. **Model chooses a matching skill:** the first model request contains the user prompt, the skill inventory, and the injected `using-superpowers` instructions. The prompt says `Brainstorm...`, the inventory contains `superpowers:brainstorming`, and `using-superpowers` says relevant skills must be invoked before any response. The model then emits a `Skill` tool call for `superpowers:brainstorming`.
5. **Skill tool loads the full body:** after the `Skill` tool call, Claude Code returns a synthetic user/tool-result message containing the full `brainstorming` skill body. In this probe that body was about 10.6k chars, and it remained in context in every later request.

So the causal path we can support from instrumentation is:

```text
plugin directory exposed
  -> Claude Code advertises Superpowers skill headers
  -> SessionStart hook injects using-superpowers
  -> model semantically selects superpowers:brainstorming
  -> Skill tool resolves and inserts the full brainstorming skill body
  -> later stateless API requests resend that body as conversation history
```

This looks different from a hard-coded source-code trigger like "if prompt contains the word brainstorm, load the brainstorming file." The observed trigger is model-mediated: Claude Code exposes metadata and the `Skill` tool; the Superpowers hook strongly instructs the model to invoke relevant skills; the model chooses `superpowers:brainstorming`; the tool implementation then loads the body.

`superpowers:writing-plans`, `superpowers:executing-plans`, and related workflow skills were advertised as headers only. They were not loaded as full bodies in this one-shot probe. The `brainstorming` skill itself says the next terminal state is `writing-plans`, but only after a design/spec approval gate; our prompt explicitly stopped after the initial brainstorm/design response, so that transition did not happen.

## Context Cost

The context overhead in this probe breaks down into three visible buckets:

| layer | without Superpowers | with Superpowers | interpretation |
| --- | ---: | ---: | --- |
| Skill headers | 14 headers | 28 headers | Superpowers adds 14 advertised skills as names/descriptions. |
| Startup hook | 0 hook chars | 5,632 additional-context chars | Full `using-superpowers` skill is injected at session start. |
| Loaded skill body | 0 chars | about 10.6k chars after request 1 | Full `brainstorming` body appears only after the model invokes `Skill`. |

The important finding is that Superpowers has a real startup context cost, but it is not "all full skills every turn." It is full `using-superpowers` plus skill metadata at startup, then full bodies only for skills that are actually invoked.

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
