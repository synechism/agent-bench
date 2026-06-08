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

## Superpowers Hook Implementation

The exact hook code is dumped in `context_dumps/04_superpowers_hook_implementation.md`. Conceptually, Superpowers implements the bootstrap as a normal Claude Code `SessionStart` plugin hook:

```text
plugin install exposes superpowers/.claude-plugin/plugin.json
  -> Claude Code loads the plugin's hooks/hooks.json
  -> hooks.json registers a SessionStart command hook
  -> matcher is startup|clear|compact
  -> async is false, so Claude Code waits for it before proceeding
  -> command runs "${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.cmd" session-start
  -> run-hook.cmd is a cross-platform wrapper
  -> wrapper executes hooks/session-start
  -> session-start reads skills/using-superpowers/SKILL.md
  -> wraps that full markdown body in an <EXTREMELY_IMPORTANT> block
  -> prints JSON containing hookSpecificOutput.additionalContext
  -> Claude Code adds that additionalContext to the next model request
```

The implementation is deliberately simple. The plugin does not call the model, does not inspect the user's prompt, and does not choose `brainstorming` itself. It only injects the full `using-superpowers` instructions at session start. Those instructions tell the model that it has Superpowers and must use relevant skills via the generic `Skill` tool. The later `superpowers:brainstorming` invocation is still model-mediated: the model reads the hook-injected bootstrap plus skill headers plus user prompt, then emits `Skill({ skill: "superpowers:brainstorming", ... })`.

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

## Source-Code Instrumentation

I cloned the inspectable Claude Code source at commit `6f6f12b37f529488b10e53928dd5508bb93535c7` into `/tmp/claude-code-source` and added an opt-in JSONL probe gated by `CLAUDE_CODE_SKILL_LIFECYCLE_LOG`. The patch is saved at `source_instrumentation/claude_code_skill_lifecycle_probe.patch`.

The key source path is:

```text
enabled plugin settings
  -> loadAllPluginsCacheOnly()
  -> getPluginSkills()
  -> loadSkillsFromDirectory()
  -> createPluginCommand()
  -> getSkillListingAttachments()
  -> formatCommandsWithinBudget()
  -> model sees names/descriptions
  -> SkillTool.validateInput()
  -> SkillTool.call()
  -> processPromptSlashCommand()
  -> getMessagesForPromptSlashCommand()
  -> command.getPromptForCommand()
  -> full SKILL.md body becomes a synthetic user message
  -> addInvokedSkill() preserves it for compaction restore
```

Concrete code sites:

| source file | role |
| --- | --- |
| `src/utils/plugins/pluginLoader.ts` | Reads enabled marketplace plugins and resolves each plugin from installed/cache paths. |
| `src/utils/plugins/loadPluginCommands.ts` | Reads plugin `skills/*/SKILL.md`, parses frontmatter, and creates prompt commands. |
| `src/skills/loadSkillsDir.ts` | Equivalent loader for user/project `.claude/skills/*/SKILL.md`. |
| `src/tools/SkillTool/prompt.ts` | Formats the model-visible skill listing under an 8000-char default budget. |
| `src/utils/attachments.ts` | Emits the skill-listing attachment once per agent for newly visible skills. |
| `src/utils/sessionStart.ts` and `src/utils/hooks.ts` | Execute `SessionStart` hooks and inject returned `additionalContext`. |
| `src/tools/SkillTool/SkillTool.ts` | Validates and dispatches model `Skill(...)` calls. |
| `src/utils/processUserInput/processSlashCommand.tsx` | Expands the selected skill into full prompt text and registers it as invoked. |

## Full Causal Mechanism

The stronger source-backed answer is that Claude Code has two different registries:

1. **Tool registry:** TypeScript `Tool` objects such as `SkillTool`, `BashTool`, `Read`, and `Edit`. `src/tools.ts` imports `SkillTool` and includes it in `getAllBaseTools()`, so the model can emit a `tool_use` block named `Skill`.
2. **Skill/command registry:** prompt-command objects built from bundled skills, `.claude/skills/*/SKILL.md`, plugins, and MCP skills. Plugin skills are read by `src/utils/plugins/loadPluginCommands.ts`; local skill directories are read by `src/skills/loadSkillsDir.ts`; both become `Command` objects with metadata plus an async `getPromptForCommand()` function that expands the full body only on invocation.

The important separation is: the model sees the **Skill tool schema** and a **skill listing**, not every full skill body. The body is loaded only after a model-emitted `Skill` call names a specific skill.

### 1. Tool Availability

`src/tools.ts` is the built-in tool source of truth:

```ts
export function getAllBaseTools(): Tools {
  return [
    AgentTool,
    TaskOutputTool,
    BashTool,
    ...
    AskUserQuestionTool,
    SkillTool,
    EnterPlanModeTool,
    ...
  ]
}
```

`src/services/api/claude.ts` serializes the current `tools` array into API schemas on each model request:

```ts
const toolSchemas = await Promise.all(
  filteredTools.map(tool => toolToAPISchema(tool, ...)),
)
const allTools = [...toolSchemas, ...extraToolSchemas]
...
return {
  messages: addCacheBreakpoints(messagesForAPI, ...),
  system,
  tools: allTools,
  tool_choice: options.toolChoice,
  ...
}
```

`src/utils/api.ts` shows what a normal tool schema contains: `name`, `description`, and `input_schema`, with a session-scoped schema cache to avoid recomputing unstable descriptions locally. This does not mean the model has hidden persistent state; it means the client rebuilds and sends request parameters, with provider-side prompt caching possible for repeated prefixes.

### 2. Skill Metadata Loading

Plugin skills are loaded by scanning enabled plugins, reading `SKILL.md`, parsing frontmatter, and constructing prompt commands:

```text
getPluginSkills()
  -> loadAllPluginsCacheOnly()
  -> loadSkillsFromDirectory()
  -> parseFrontmatter(SKILL.md)
  -> createPluginCommand()
```

The resulting command stores the metadata (`description`, `whenToUse`, `allowedTools`, `model`, etc.) and a lazy body expander:

```ts
async getPromptForCommand(args, context) {
  let finalContent = config.isSkillMode
    ? `Base directory for this skill: ${dirname(file.filePath)}\n\n${content}`
    : content
  ...
  return [{ type: 'text', text: finalContent }]
}
```

That is the code-level answer to “where are skills stored?” Before invocation, they are local `Command` objects in memoized command registries (`loadAllCommands`, `getCommands`, `getSkillToolCommands`). Their full markdown is held client-side as command content/closures, not automatically inserted into the model prompt.

### 3. Skill Listing Injection

`src/utils/attachments.ts` decides whether to announce skill headers:

```text
getSkillListingAttachments()
  -> getSkillToolCommands(cwd)
  -> filter out skills already sent for this agent
  -> formatCommandsWithinBudget(newSkills, contextWindowTokens)
  -> attachment type: skill_listing
```

`src/utils/messages.ts` turns that attachment into a model-visible system-reminder user message:

```text
The following skills are available for use with the Skill tool:

- superpowers:brainstorming: ...
- superpowers:writing-plans: ...
```

This is why Superpowers increases visible skill headers at startup but does not load every Superpowers skill body.

### 4. The Actual Trigger

The actual trigger for `superpowers:brainstorming` is a model output, not a hard-coded string match. In the successful Superpowers run, the assistant explicitly reasoned that the available `superpowers:brainstorming` skill matched the user request and emitted:

```json
{"id":"call_00_ccgM9cHbJHMkwPKLWvbT4106","input":{"args":"Brainstorm a small feature for this empty repository: a tiny CLI that stores short notes. Keep it brief and stop after brainstorming/design — no implementation.","skill":"superpowers:brainstorming"},"name":"Skill"}
```

The full excerpt is saved at `model_output_evidence/brainstorm_skill_tool_use_request1.md`.

So the word `brainstorm` matters semantically because it helps the model choose the advertised brainstorming skill. It is not the direct loader. The direct loader event is the assistant `tool_use` block named `Skill` with `input.skill = "superpowers:brainstorming"`.

### 5. Tool Dispatch

`src/query.ts` captures streamed assistant `tool_use` blocks:

```ts
const msgToolUseBlocks = message.message.content.filter(
  content => content.type === 'tool_use',
) as ToolUseBlock[]
toolUseBlocks.push(...msgToolUseBlocks)
```

After the assistant response, `query.ts` sends those blocks through `runTools(...)`:

```ts
const toolUpdates = runTools(
  toolUseBlocks,
  assistantMessages,
  canUseTool,
  toolUseContext,
)
```

`src/services/tools/toolOrchestration.ts` partitions tool calls and executes them serially or concurrently. `src/services/tools/toolExecution.ts` resolves the model-provided name back to the local tool object:

```ts
const toolName = toolUse.name
let tool = findToolByName(toolUseContext.options.tools, toolName)
...
const result = await tool.call(callInput, context, canUseTool, assistantMessage, ...)
```

For `name = "Skill"`, this invokes `SkillTool.call()`.

### 6. Body Expansion And Storage

Inside `src/tools/SkillTool/SkillTool.ts`, `SkillTool.call()` resolves the requested command and calls `processPromptSlashCommand(...)`. That path reaches `getMessagesForPromptSlashCommand()` in `src/utils/processUserInput/processSlashCommand.tsx`, which does the critical expansion:

```ts
const result = await command.getPromptForCommand(args, context)
...
addInvokedSkill(command.name, skillPath, skillContent, agentId)
```

`SkillTool.call()` returns those expanded messages as `newMessages`. `src/services/tools/toolExecution.ts` then appends `result.newMessages` to the tool-result stream, and `src/query.ts` appends all tool results into the next turn state:

```ts
messages: [...messagesForQuery, ...assistantMessages, ...toolResults]
```

That is how the loaded skill body enters the next model request: it becomes a synthetic user/meta message in conversation history. It is not “stored inside the model”; it is stored in the client transcript and resent on subsequent stateless API calls until compaction or pruning changes the transcript.

### 7. Compaction Preservation

`addInvokedSkill()` stores invoked bodies in process state:

```ts
STATE.invokedSkills.set(`${agentId ?? ''}:${skillName}`, {
  skillName,
  skillPath,
  content,
  invokedAt: Date.now(),
  agentId,
})
```

When compaction runs, `src/services/compact/compact.ts` creates an `invoked_skills` attachment from this state. `src/utils/messages.ts` renders that attachment as:

```text
The following skills were invoked in this session. Continue to follow these guidelines:

### Skill: ...
```

So invoked skill bodies have two persistence paths: normal conversation history before compaction, and the `invoked_skills` attachment after compaction.

### Dispatch Probe Patch

I added a second focused source patch at `source_instrumentation/claude_code_tool_dispatch_probe.patch`. It logs the missing middle of the lifecycle when `CLAUDE_CODE_SKILL_LIFECYCLE_LOG` is set:

- `model_tool_use_blocks_captured`: `query.ts` saw a model-emitted tool call.
- `tool_execution_loop_start`: `query.ts` is about to run tool calls.
- `run_tools_orchestration_start` / `run_tools_orchestration_batch`: `runTools()` partitioned the calls.
- `tool_dispatch_lookup`: `toolExecution.ts` resolved the model tool name to a local `Tool` object.
- `tool_call_enter`: the local `Tool.call()` is about to execute.
- `tool_call_returned`: `Tool.call()` returned, including whether it produced `newMessages`.
- `tool_new_messages_enqueued`: expanded skill body messages are being queued into the tool-result stream.
- `tool_results_appended_to_next_turn_state`: `query.ts` appended assistant messages and tool results into the next request state.

After adding this patch, the source CLI startup path still runs with `bun run src/entrypoints/cli.tsx --version`. A targeted `bun build` of the touched query/tool files still fails on the same unrelated source-package dependency gaps noted below (`protectedNamespace.js`, `sharp`, Bedrock/Vertex SDK packages, etc.), so the dispatch patch is saved for the next source-backed end-to-end run rather than claimed as a fully built artifact.

The instrumented source confirmed the architecture strongly:

- At startup, Claude Code reads each installed plugin skill's `SKILL.md` to parse frontmatter and metadata. In our local setup this found `frontend-design:frontend-design` plus 14 `superpowers:*` skills.
- The initial model-facing skill listing is metadata only. A direct source probe formatted 15 skill headers into 2,763 chars, including `superpowers:brainstorming` as a one-line description.
- The full `superpowers:brainstorming` body is not inserted by plugin discovery. A direct source probe loaded it only when `getPromptForCommand()` was called for that skill; the expanded body was 10,490 chars after adding the base-directory prefix and arguments.
- Superpowers' unconditional startup payload is separate: its `SessionStart` hook returns `additionalContext` containing `using-superpowers`. The source CLI startup probe measured 5,632 chars for that hook context.
- The word `brainstorm` itself is not a hard-coded source trigger. The source exposes skill headers and hook instructions; the model decides to call `Skill("superpowers:brainstorming")`; only then does the tool load the body.

I also made Superpowers persistent in local Claude Code plugin config, not just session-scoped:

```text
~/.claude/plugins/known_marketplaces.json
~/.claude/plugins/installed_plugins.json
~/.claude/settings.json
```

The persistent install enables `superpowers@superpowers-local` and points it at `/home/abhi/.claude/plugins/cache/superpowers-local/5.1.0`.

Validation notes:

- `bun run src/entrypoints/cli.tsx --version` works from the source tree.
- Full `bun run typecheck` and `bun run build` fail on unrelated upstream/source-package issues such as missing private/generated modules and optional dependencies. The instrumented source still runs far enough for direct loader probes and CLI startup probes.
- A real source-backed model call emitted plugin/frontmatter and hook lifecycle events, then hung before streaming output from the model endpoint; I stopped it rather than leave a dangling process.

## Data

- `skill_lifecycle_timeline.csv`
- `skill_lifecycle_summary.json`
- `context_dumps/01_session_start_hook_using_superpowers.md` - exact `SessionStart` hook additional context injected by Superpowers.
- `context_dumps/02_initial_skill_inventory_request1.md` - exact request-1 developer/skills inventory after Superpowers is exposed.
- `context_dumps/03_loaded_brainstorming_skill_tool_result.md` - exact synthetic user/tool-result text loaded after `Skill(superpowers:brainstorming)`.
- `context_dumps/04_superpowers_hook_implementation.md` - exact Superpowers hook declaration, wrapper, and session-start script.
- `model_output_evidence/brainstorm_skill_tool_use_request1.md` - exact assistant `tool_use` evidence that triggered the skill load.
- `source_instrumentation/claude_code_skill_lifecycle_probe.patch` - opt-in source patch.
- `source_instrumentation/claude_code_tool_dispatch_probe.patch` - focused opt-in patch for the model-output-to-tool-dispatch-to-next-turn path.
- `source_instrumentation/source_cli_startup_probe.jsonl` - source CLI startup evidence for plugin frontmatter and `SessionStart` hook injection.
- `source_instrumentation/direct_skill_listing_probe.jsonl` - direct source evidence for skill-listing formatting.
- `source_instrumentation/direct_skill_body_probe.jsonl` - direct source evidence for full `superpowers:brainstorming` body loading.
