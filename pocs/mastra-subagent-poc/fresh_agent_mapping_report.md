# Fresh Subagent Mapping Report

Date: 2026-06-08

This report explains how the Mastra subagent POC mirrors Claude Code's fresh
subagent path. The fork path is present in the POC only as a comparison point;
the primary target is the normal Claude Code call shape:

```text
Agent({ subagent_type: "...", prompt: "..." })
```

## Short Answer

The POC mimics Claude Code's fresh subagent setup as closely as possible at the
semantic/context-construction layer:

- the parent selects a named child agent type;
- the parent writes a self-contained prompt/brief;
- the child receives its own system prompt, not the parent's rendered system
  prompt;
- the child receives only one initial user message containing the parent brief;
- the child gets a child-specific tool set, not a blind copy of the parent's
  tools;
- parent conversation history is not automatically copied into the child;
- child runtime state is isolated from the parent, except for explicitly cloned
  operational state that Claude Code also carries across, such as read/cache
  state.

The main caveat is that the default runnable demo is deterministic and local. It
models the context payloads without making real model calls. The Mastra agent
definitions are present too, and `src/mastra/delegation.ts` shows how to apply
the same fresh-agent context policy to real Mastra supervisor delegation.

## Claude Code Behavior Being Mirrored

In Claude Code, a normal/fresh subagent is created when the parent calls the
`Agent` tool with a `subagent_type`, for example:

```text
Agent({
  subagent_type: "general-purpose",
  prompt: "Investigate this bounded question and return concise findings."
})
```

The important semantic fact is that this child is not a continuation of the
parent's full context. The parent must brief it. Claude Code builds the child
context from several separate layers:

1. The selected agent definition.
2. The selected agent's own system prompt.
3. A single initial user message containing the `prompt` string.
4. A resolved child tool pool.
5. Child `ToolUseContext` state.
6. Skill/plugin/agent/memory layers that are available to that child scope.

The parent's previous messages are not automatically inserted into a fresh
subagent. If the child needs something the parent learned earlier, the parent
has to put that information in the prompt.

## POC Structure

The POC lives in this folder:

```text
pocs/mastra-subagent-poc/
```

The main files are:

```text
src/runtime.ts
src/registry.ts
src/mastra/agents.ts
src/mastra/tools.ts
src/mastra/delegation.ts
src/poc.ts
registry/agents/*.md
registry/skills/**/SKILL.md
registry/hooks/*.json
artifacts/subagent-poc-run.json
```

The two relevant entry points are:

```typescript
spawnFreshSubagent(...)
forkSubagent(...)
```

`spawnFreshSubagent(...)` is the important one for fresh-agent behavior.
`forkSubagent(...)` exists to prove the contrast with the context-inheriting
path.

## Fresh Agent Mapping

| Claude Code fresh-agent concept | POC implementation |
| --- | --- |
| Parent emits `Agent` tool call with `subagent_type` | Caller invokes `spawnFreshSubagent({ agentType, prompt })` |
| Agent registry lookup | `agentRegistry` in `src/runtime.ts` |
| Selected agent definition | `AgentDefinition` with `id`, `description`, `instructions`, `tools`, `maxTurns` |
| Child system prompt | `definition.instructions` |
| Initial child messages | `[{ role: "user", content: args.prompt }]` |
| Parent-written brief | `args.prompt` |
| No inherited parent conversation | `parentContextVisible: false` and no `parent.messages` in fresh child messages |
| Child tool pool | `definition.tools` |
| Isolated child context | `createSubagentContext(...)` clones messages/tools/state containers |
| Agent registry loading | `loadRuntimeRegistry(...)` scans `registry/agents/*.md` |
| Skill header discovery | `discoverSkills(...)` scans `registry/skills/**/SKILL.md` |
| Hook context injection | `runDeclarativeHooks(...)` injects matching `SubagentStart` hook context |
| Child run loop | `runDeterministicChild(...)` for the local demo |

The core POC code is:

```typescript
export async function spawnFreshSubagent(args: {
  parent: ParentContext;
  agentType: keyof typeof agentRegistry;
  prompt: string;
}): Promise<SubagentTranscript> {
  const definition = agentRegistry[args.agentType];
  const agentId = createAgentId(definition.id);
  const messages: Message[] = [{ role: "user", content: args.prompt }];
  const childContext = createSubagentContext({
    agentId,
    agentType: definition.id,
    mode: "fresh",
    systemPrompt: definition.instructions,
    messages,
    tools: definition.tools,
    parentReadFileState: new Map([["parent-read-cache", "cloned"]]),
    parentContextVisible: false,
  });
}
```

That is the key semantic mirror: the fresh child gets specialist instructions,
one parent-authored user message, and child-resolved tools. It does not receive
the parent's message history.

## Agent Registry Loading

The POC now has a small filesystem registry under:

```text
registry/agents/
```

Each agent is a markdown file with frontmatter plus an instruction body:

```markdown
---
id: research-agent
description: Searches and summarizes relevant files from a self-contained brief.
tools:
  - inspect-repo
  - summarize-context
maxTurns: 4
---
You are a fresh research subagent loaded from the filesystem agent registry.
```

`loadRuntimeRegistry(...)` parses these files, resolves the listed tool ids
against known local tools, and merges the result over the in-memory fallback
registry. That gives the POC the same basic shape as Claude Code's agent
definition loading: agent behavior is data-defined and selected by type.

## Why The Parent Context Is Not In The Fresh Child

The demo parent context includes messages:

```typescript
messages: [
  { role: "user", content: "Investigate how Claude Code injects context..." },
  { role: "assistant", content: "I found AgentTool.tsx..." },
]
```

Those messages are intentionally not passed into `spawnFreshSubagent(...)`.
Instead, the child gets:

```typescript
[{ role: "user", content: args.prompt }]
```

The generated artifact confirms this:

```json
"fresh": {
  "mode": "fresh",
  "messages": [
    {
      "role": "user",
      "content": "Research the Claude Code AgentTool path..."
    }
  ],
  "toolNames": ["inspect-repo", "summarize-context"]
}
```

That mirrors Claude Code's causal boundary: parent history only reaches the
fresh subagent if the parent rewrites it into the subagent prompt.

## Tool Surface Mapping

Claude Code fresh subagents do not necessarily inherit the parent's exact tools.
Claude Code resolves the child tool pool from the child agent definition,
permission mode, denied tools, MCP availability, and runtime constraints.

The POC models that with `definition.tools`:

```typescript
"research-agent": {
  tools: {
    "inspect-repo": inspectRepo,
    "summarize-context": summarizeContext,
  }
}
```

This is why the fresh child receives `inspect-repo` and `summarize-context`
from the research-agent definition, not from an exact copy of the parent.

The fork demo is different on purpose:

```typescript
tools: args.parent.tools
```

That contrast makes the fresh behavior easier to see.

## System Prompt Mapping

Claude Code fresh subagents use the selected agent's own system prompt, enhanced
with environment/runtime details. They do not use the parent's rendered system
prompt.

The POC mirrors this with:

```typescript
systemPrompt: definition.instructions
```

The demo agents in `src/mastra/agents.ts` define role-specific instruction
strings:

```typescript
export const researcherInstructions = `You are a fresh research subagent.
You receive only the prompt supplied by the parent plus your own instructions.
Do not assume you have seen the parent conversation. Report concise findings.`;
```

That instruction is deliberately blunt because the POC is a context-behavior
probe, not a productized agent.

## Skill Discovery

The POC now discovers skills from:

```text
registry/skills/**/SKILL.md
```

It parses each skill's frontmatter:

```markdown
---
name: brainstorming
description: Use before creative feature or product design work...
---
```

Then it renders a Claude-style skill registry:

```text
The following skills are available for use with the Skill tool:

- superpowers:brainstorming: Use before creative feature or product design work...
- superpowers:systematic-debugging: Use when investigating a bug...
```

This intentionally models the header/discovery phase, not the full skill-body
loading phase. In Claude Code terms, this is the part where the child model sees
which skills exist and why it might call one. A future extension could add a
local `Skill` tool that loads the full `SKILL.md` body into the child transcript.

## Hook Injection

The POC now supports declarative hooks under:

```text
registry/hooks/*.json
```

Example:

```json
{
  "id": "demo-subagent-start",
  "event": "SubagentStart",
  "appliesTo": "subagent",
  "additionalContext": "Demo SubagentStart hook: this worker is scoped..."
}
```

When `spawnFreshSubagent(...)` constructs a child context, it runs:

```typescript
runDeclarativeHooks({
  hooks: runtime.hooks,
  event: "SubagentStart",
  scope: "subagent",
});
```

Matching hook context is injected into the child context and recorded in the
artifact as `hookIds` and `hookContext`. This mirrors the context-injection role
of Claude Code hooks without trying to execute arbitrary shell scripts.

## State Isolation Mapping

Claude Code creates a new child `ToolUseContext` for the subagent. The child has
its own agent id, transcript, tool context, local denial tracking, discovered
skill tracking, and query chain. Some operational state is copied or shared when
needed, such as read-file/cache state.

The POC represents this with:

```typescript
state: {
  readFileState: new Map(args.parentReadFileState),
  discoveredSkillNames: new Set(),
  parentContextVisible: args.parentContextVisible,
}
```

The important point is not that this is a full Claude Code state clone. It is
that the child receives a separate state object and a new agent id. The POC uses
`parentContextVisible` as an explicit marker for the semantic boundary we care
about.

## Mastra-Native Fresh Delegation

Mastra supervisor agents normally forward full conversation context to
subagents by default. That default is closer to Claude Code's fork behavior than
Claude Code's fresh `Agent({ subagent_type, prompt })` behavior.

To make real Mastra delegation behave like Claude Code fresh subagents, the POC
adds `claudeFreshDelegation`:

```typescript
export const claudeFreshDelegation = {
  messageFilter: ({ primitiveId }) => {
    console.log(
      `[delegation:fresh] ${primitiveId} receives 0 parent history messages`,
    );
    return [];
  },
  includeSubAgentToolResultsInModelContext: false,
} satisfies DelegationConfig;
```

This is the Mastra-native equivalent of the fresh-agent boundary. The parent can
still delegate, but the child receives only the delegation prompt and its own
agent instructions, not the full parent transcript.

## What The POC Does Not Fully Recreate

The POC intentionally does not recreate every Claude Code implementation detail.
It focuses on semantic context construction.

Not fully recreated:

- Claude Code's full tool permission system.
- MCP server initialization.
- dynamic skill body loading after the model calls the `Skill` tool.
- sidechain transcript persistence.
- arbitrary executable hooks. The POC supports declarative context hooks.
- prompt caching and byte-identical prefix behavior.
- live model loop behavior in the deterministic default run.
- exact Claude Code system prompts and internal attachment formatting.

These are implementation details we can add later if the POC becomes an
instrumentation harness. For the current goal, the main causal shape is present:
fresh subagents are separately scoped agents briefed through a single prompt.

## Why Fork Is Included But De-Emphasized

The POC includes `forkSubagent(...)` because it is the cleanest contrast case.
It shows the opposite policy:

- parent rendered system prompt is reused;
- parent messages are prepended;
- parent tools are copied exactly;
- a fork directive is appended;
- `parentContextVisible` is true.

That lets us inspect fresh and fork output side by side in
`artifacts/subagent-poc-run.json`. But for the user's current focus, fresh
subagents are the important path.

## Validation

Run:

```bash
npm run build
npm run poc
```

The last verified run produced:

```text
fresh:
  mode=fresh
  messageCount=1
  skillNames=superpowers:brainstorming,superpowers:systematic-debugging
  hookIds=demo-subagent-start
  parentContextVisible=false

fork:
  mode=fork
  messageCount=3
  parentContextVisible=true
```

The artifact is:

```text
artifacts/subagent-poc-run.json
```

## Bottom Line

The POC mirrors Claude Code's fresh subagent setup at the level that matters for
semantic memory/context consumption:

```text
parent model decides to delegate
  -> parent writes a bounded prompt
  -> runtime selects a child agent definition
  -> child receives child instructions
  -> child receives exactly one task message
  -> child receives child tools
  -> parent conversation is not copied
  -> child returns a compact result to parent
```

That is the behavior we need to reproduce before experimenting with richer
subagent orchestration in Mastra.
