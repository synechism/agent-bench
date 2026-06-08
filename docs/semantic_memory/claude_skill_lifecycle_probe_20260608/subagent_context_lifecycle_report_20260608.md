# Claude Code Subagent Context Lifecycle Report

Date: 2026-06-08

Source under inspection: `/tmp/claude-code-source`

Companion source dump:
`docs/semantic_memory/claude_skill_lifecycle_probe_20260608/context_dumps/06_claude_code_subagent_source_excerpts.md`

## Executive Summary

Claude Code subagents are not OS subprocesses in the simple "spawn a separate
CLI" sense. In the normal `Agent` tool path, they are in-process query loops
created by `AgentTool.call()`, given a fresh `ToolUseContext`, a selected agent
definition, an agent-specific system prompt, a tool pool, and an initial user
message containing the parent-written prompt. The parent does not automatically
copy its full conversation into these normal/fresh subagents. It briefs them by
writing the context into the `prompt` argument.

There is a second path: fork subagents. When the fork feature is enabled and
the model omits `subagent_type`, `AgentTool.call()` routes to a synthetic
`FORK_AGENT`. Forks are explicitly designed to inherit the parent context:
they receive the parent's rendered system prompt, the parent's exact tool array,
and the parent's message history as `forkContextMessages`. The fork then appends
a special child directive message. This path exists to keep noisy intermediate
work out of the parent context while maximizing prompt-cache reuse.

The decisive split is:

- `Agent({ subagent_type: "Explore", prompt: "..." })` means fresh specialist:
  new agent system prompt, new initial message, filtered/resolved tools, no
  parent conversation unless the parent put it in the prompt.
- `Agent({ prompt: "..." })` with fork enabled means context-inheriting fork:
  parent system prompt, parent messages, parent tools, cloned context state, and
  a fork-specific directive.

## What The Parent Model Sees

The parent model can spawn subagents because the `Agent` tool schema is in its
tool list. The schema includes `description`, `prompt`, optional
`subagent_type`, optional model override, optional background execution, and
optional worktree isolation. The exact schema is built in
`src/tools/AgentTool/AgentTool.tsx` around the `baseInputSchema` and
`fullInputSchema`.

The parent also receives prose instructions for when and how to use `Agent`.
Those instructions come from `src/tools/AgentTool/prompt.ts`. They tell the
model that the tool launches specialized agents, explain available agent types,
and state that fresh agents need a complete briefing. If fork mode is active,
the prompt also tells the model that omitting `subagent_type` forks itself and
that the fork inherits context.

The list of available agent types can be injected in two ways:

- Inline inside the `Agent` tool description.
- As an `agent_listing_delta` attachment rendered into a
  `<system-reminder>`-style message.

The newer attachment path exists because dynamic agent listings embedded in the
tool description change the serialized tool schema and bust prompt cache. The
code comment says this dynamic list accounted for about 10.2% of fleet
cache-creation tokens. This is directly analogous to the skill-listing behavior
we have been studying: a model-visible inventory is supplied separately from
the full implementation/body of the thing being invoked.

## How Agent Definitions Are Loaded

Agent definitions come from three pools:

- Built-in agents from `getBuiltInAgents()`, such as `general-purpose`,
  `statusline-setup`, and conditionally `Explore` / `Plan`.
- Plugin agents loaded by `loadPluginAgents()`.
- Custom markdown agents loaded from `.claude/agents` directories.

The custom markdown loader searches managed policy settings, user settings, and
project `.claude/agents` directories up to the repo boundary. The active list is
then filtered for availability, MCP requirements, permission denials, and
allowed-agent restrictions.

A parsed agent definition contains the fields that matter for subagent
construction: `agentType`, `whenToUse`, `tools`, `disallowedTools`, optional
`skills`, optional MCP servers, optional hooks, optional memory scope, model,
permission mode, max turns, background flag, and isolation mode.

## Causal Path: Normal Fresh Subagent

The normal flow starts when the parent model emits an `Agent` tool call with a
`subagent_type`, or when fork mode is off and `subagent_type` is omitted, in
which case Claude Code defaults to `general-purpose`.

1. The model emits an `Agent` tool call.

   The parent model does not directly instantiate a worker. It outputs a tool
   use block whose input includes `description`, `prompt`, and optionally
   `subagent_type`, `model`, `run_in_background`, `isolation`, `cwd`, or name
   fields.

2. `AgentTool.call()` resolves the agent type.

   The code computes:

   ```ts
   const effectiveType =
     subagent_type ?? (isForkSubagentEnabled() ? undefined : GENERAL_PURPOSE_AGENT.agentType)
   ```

   If `effectiveType` is defined, this is the normal fresh-agent path. Claude
   Code searches `toolUseContext.options.agentDefinitions.activeAgents` for the
   requested type. If the type is missing or denied by permissions, the tool
   call fails.

3. Claude Code builds the child system prompt.

   For a normal subagent, Claude Code calls `selectedAgent.getSystemPrompt()`,
   then passes that prompt through `enhanceSystemPromptWithEnvDetails()`.
   This is where the child receives the specialist role prompt plus environment
   details. This is not the parent's full current context.

4. Claude Code creates the child prompt message.

   For a normal subagent:

   ```ts
   promptMessages = [createUserMessage({ content: prompt })]
   ```

   This is the key semantic boundary. The only task-specific context injected
   into a fresh subagent is the string the parent put in `prompt`, plus any
   agent-defined hooks, preloaded skills, MCP instructions, memory/user/system
   context, and environment/system prompt layers that `runAgent()` adds later.

5. Claude Code assembles the worker tool pool.

   `AgentTool.call()` constructs `workerPermissionContext` using the child
   agent's permission mode and calls `assembleToolPool(...)`. Then `runAgent()`
   filters that pool through `resolveAgentTools(...)` unless the fork path set
   `useExactTools`.

   This means normal subagents do not merely inherit the parent's active tools.
   They get a worker tool pool resolved from their own definition and runtime
   permissions.

6. Claude Code chooses sync or async execution.

   The tool runs async if `run_in_background` is true, the agent definition has
   `background: true`, coordinator mode is active, fork mode forces async, or
   assistant/proactive modes force async. Otherwise it runs foreground/sync and
   the parent waits for the result.

7. `runAgent()` creates the child query context.

   `runAgent()` merges `forkContextMessages` if present; for normal subagents
   it is absent, so the initial message list is only `promptMessages` at this
   stage. Then it resolves user/system context, omits some parent CLAUDE.md/git
   context for certain read-only agents, resolves tools, runs `SubagentStart`
   hooks, preloads any agent-frontmatter skills, initializes agent-specific MCP
   servers, and creates a child `ToolUseContext` with `createSubagentContext()`.

8. The child query loop starts.

   Finally, `runAgent()` calls `query({ messages: initialMessages,
   systemPrompt: agentSystemPrompt, userContext, systemContext,
   toolUseContext: agentToolUseContext, querySource, maxTurns })`.

   This is the actual model call loop for the subagent. Its messages and
   outputs are recorded to the sidechain transcript using
   `recordSidechainTranscript(...)`.

## Causal Path: Fork Subagent

Forks are the context-inheriting version of subagents.

Fork mode is guarded by `isForkSubagentEnabled()`. When enabled, omitting
`subagent_type` routes to a synthetic `FORK_AGENT` instead of defaulting to
`general-purpose`. The source comments explicitly state the intended behavior:
the child inherits the parent's full conversation context and system prompt,
and all agent spawns run in the background.

The fork path changes three critical inputs:

1. It uses the parent's rendered system prompt.

   `AgentTool.call()` prefers `toolUseContext.renderedSystemPrompt`. That value
   is set at parent turn start in the REPL after building the effective system
   prompt. The code avoids recomputing the parent prompt because feature gates
   or dynamic state could produce different bytes and break prompt cache.

2. It passes the parent messages as `forkContextMessages`.

   `runAgentParams` sets:

   ```ts
   forkContextMessages: isForkPath ? toolUseContext.messages : undefined
   ```

   In `runAgent()`, those messages are filtered for incomplete tool calls and
   prepended:

   ```ts
   const initialMessages = [...contextMessages, ...promptMessages]
   ```

3. It uses the parent's exact tool list.

   For fork children, `availableTools` is set to `toolUseContext.options.tools`
   and `useExactTools: true` is passed. Inside `runAgent()`, `useExactTools`
   bypasses normal tool resolution and inherits the parent's thinking config and
   noninteractive setting. The comments say this is for byte-identical API
   prefixes and prompt cache hits.

The fork-specific prompt message is built by `buildForkedMessages(...)`. It
clones the parent assistant message that contained the `Agent` tool call,
creates placeholder tool results for all tool_use blocks in that assistant
message, then appends a child directive. The placeholder text is deliberately
identical across forks so that parallel fork requests share as much prompt
prefix as possible.

The child directive is also explicit: it tells the child it is a forked worker,
not the main agent; not to spawn subagents; to use tools directly; and to report
in a constrained format beginning with `Scope:`.

## How Context Is Injected Into The Child

There are four context injection channels, and they behave differently.

### 1. System Prompt

Fresh subagent:

- Uses the selected agent's own system prompt.
- Enhanced with environment details.
- May include agent memory if the agent definition has a memory scope.

Fork subagent:

- Uses the parent agent's already rendered system prompt.
- This is byte-preserving and designed for cache reuse.

### 2. Messages

Fresh subagent:

- Starts with a single user message containing the `prompt` argument.
- Does not inherit parent conversation by default.
- Parent must manually summarize or copy necessary context into `prompt`.

Fork subagent:

- Starts with parent messages, filtered to avoid incomplete tool calls.
- Then appends the fork-specific assistant/tool_result/directive messages.
- This gives the child the parent conversation history as model-visible input.

### 3. Tools

Fresh subagent:

- Receives tools assembled under the child agent's permission mode.
- Then filtered by the child agent definition's `tools` and
  `disallowedTools`.
- Async agents receive further filtering because they cannot show normal
  permission UI.

Fork subagent:

- Receives the parent's exact tools.
- Uses `useExactTools` to avoid tool filtering and preserve cache-compatible
  request prefixes.

### 4. Runtime State

Both fresh and fork subagents get a child `ToolUseContext` via
`createSubagentContext()`. This clones or resets mutable state:

- Clones `readFileState`.
- Creates fresh nested-memory/skill-discovery tracking sets.
- Clones content replacement state by default so forked children make identical
  tool-result replacement decisions and preserve cache hits.
- Gives the child its own `agentId`.
- Gives the child its own query tracking chain with incremented depth.
- Stubs most UI mutation callbacks.
- For async agents, makes `setAppState` a no-op but keeps
  `setAppStateForTasks` wired to the root store so background tasks and shell
  cleanup still work.

## Hooks, Skills, MCP, And Memory Inside Subagents

Subagents have their own lifecycle hooks. `runAgent()` executes
`SubagentStart` hooks before the child query begins. Any additional context
emitted by those hooks is appended to `initialMessages` as a hook additional
context attachment.

Subagents can also preload skills if their agent definition declares a
`skills` array. `runAgent()` resolves each skill name against registered skill
commands, loads each prompt with `skill.getPromptForCommand('', toolUseContext)`,
and appends a meta user message containing the skill loading metadata and skill
content. This is distinct from ordinary skill discovery and from the parent
model deciding to call the `Skill` tool.

Agent-specific MCP servers are initialized after skill preload. These servers
are additive to the parent's MCP clients. Their tools are fetched, deduplicated
with the resolved agent tools, and then placed into the child context's
`options.tools`.

Persistent memory for an agent is loaded through the agent definition's
`getSystemPrompt()` path when the agent has a `memory` field. The loader can
append memory prompt text to the agent system prompt.

## What The Parent Gets Back

For a foreground/sync subagent, the parent waits for the child's `runAgent()`
iterator. The child messages are accumulated, progress is streamed, and
`finalizeAgentTool(...)` extracts the final assistant text into the `Agent` tool
result. The user does not directly see the child conversation unless the parent
relays it.

For an async/background subagent, `AgentTool.call()` registers a local agent
task, starts `runAsyncAgentLifecycle(...)` in a detached async closure, and
immediately returns an `async_launched` result containing an `agentId`,
description, prompt, and output file path. Completion arrives later as a task
notification. If the agent was named, the parent can use `SendMessage` to
continue it while it is running.

In both cases, subagent messages are recorded as sidechain transcripts. The main
thread's context does not automatically absorb every child tool call. The parent
gets either the final result or a notification, which is the context-window
savings mechanism.

## Architectural Interpretation

Claude Code uses subagents as context-shaping devices, not just parallel
workers.

Normal subagents are context sinks: the parent chooses a specialist, writes a
self-contained brief, and lets the child spend tokens on search/tool output.
Only the child's final report needs to return to the parent. This keeps raw
exploration output out of the parent context.

Fork subagents are context-preserving branches: the child gets the parent
conversation and exact cache-sensitive request prefix, then performs a scoped
directive in the background. This is closer to branching the current conversation
than creating a fresh specialist. The design intentionally trades a larger child
input context for parent-context cleanliness and cache reuse.

The practical rule is:

- Fresh subagent: "Here is everything you need. Go investigate independently."
- Fork subagent: "You already know everything I know. Go do this scoped branch
  without polluting my context."

This distinction is the core causal answer for "how the parent injects context
into the subagent." It either injects context semantically through the prompt
string, or structurally through `forkContextMessages`, inherited system prompt,
and exact tools.

## POC-Relevant Skeleton

A Mastra-style POC should model the same split:

```ts
type AgentDefinition = {
  name: string
  description: string
  instructions: string
  tools: Record<string, Tool>
  model?: string
  maxTurns?: number
}

async function spawnFreshSubagent(parent, def, prompt) {
  const childMessages = [{ role: 'user', content: prompt }]
  const childTools = resolveToolsForAgent(def, parent.runtimeTools)
  return runAgentLoop({
    system: renderAgentSystem(def),
    messages: childMessages,
    tools: childTools,
    parentTaskSink: parent.taskRegistry,
  })
}

async function forkSubagent(parent, directive) {
  const childMessages = [
    ...filterIncompleteToolCalls(parent.messages),
    ...buildForkDirectiveMessages(parent.lastAssistantMessage, directive),
  ]
  return runAgentLoop({
    system: parent.renderedSystemPrompt,
    messages: childMessages,
    tools: parent.tools,
    cacheKeyCompatible: true,
    parentTaskSink: parent.taskRegistry,
  })
}
```

The POC should preserve these concepts:

- A registry of agent definitions.
- A model-visible `Agent` tool.
- A "fresh" path with no inherited conversation.
- A "fork" path with inherited messages/system/tools.
- A child context object that isolates mutable state but keeps selected root
  callbacks for task registration and notifications.
- Sidechain transcripts so parent context receives summaries/results, not full
  child tool noise.

## Source Map

- `src/tools/AgentTool/AgentTool.tsx`: model-facing schema, tool-call routing,
  normal vs fork path, async/sync launch, worktree handling.
- `src/tools/AgentTool/runAgent.ts`: child query setup, prompt/message merge,
  context construction, hooks, preloaded skills, MCP, transcript recording.
- `src/tools/AgentTool/forkSubagent.ts`: fork feature gate, synthetic fork
  agent, fork message construction, fork child directive.
- `src/utils/forkedAgent.ts`: shared `createSubagentContext()` isolation helper
  and generic forked-agent runner used by background services.
- `src/tools/AgentTool/prompt.ts`: model-visible `Agent` usage instructions,
  agent listing behavior, fork guidance.
- `src/utils/attachments.ts` and `src/utils/messages.ts`: agent listing delta
  attachment construction and rendering into model-visible reminder text.
- `src/tools/AgentTool/loadAgentsDir.ts` and
  `src/utils/markdownConfigLoader.ts`: agent definition discovery from built-in,
  plugin, managed, user, and project markdown sources.

