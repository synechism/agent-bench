# Mastra Subagent POC

This POC mirrors the Claude Code subagent lifecycle described in
`../../docs/semantic_memory/claude_skill_lifecycle_probe_20260608/subagent_context_lifecycle_report_20260608.md`.

It demonstrates two different context paths:

- Fresh subagent: receives its own agent instructions and only the parent-written brief.
- Fork subagent: receives the parent rendered system prompt, parent messages, parent tools, and a fork directive.

## Files

- `src/mastra/agents.ts`: Mastra `Agent` definitions for a supervisor, research subagent, and verifier subagent.
- `src/mastra/delegation.ts`: Mastra-native delegation configs that emulate Claude fresh and fork context policies.
- `src/mastra/tools.ts`: Mastra `createTool()` examples shared by the POC.
- `src/registry.ts`: Filesystem registry loader for markdown agents, `SKILL.md` discovery, and declarative hooks.
- `src/runtime.ts`: Claude Code-style orchestration layer with `spawnFreshSubagent()` and `forkSubagent()`.
- `src/poc.ts`: Runnable demo that prints and writes the two child context payloads.
- `registry/agents/*.md`: Claude-style local agent definitions loaded at runtime.
- `registry/skills/**/SKILL.md`: Skill headers discovered and rendered into developer context.
- `registry/hooks/*.json`: Declarative hook context injected when its event/scope matches.
- `artifacts/subagent-poc-run.json`: Last deterministic run output.

## Claude Code Mapping

| Claude Code concept | POC location |
| --- | --- |
| `AgentTool.call()` selects fresh vs fork path | `spawnFreshSubagent()` / `forkSubagent()` in `src/runtime.ts` |
| Normal subagent prompt message | `spawnFreshSubagent()` creates one user message from `prompt` |
| Fork inherited messages | `forkSubagent()` prepends `parent.messages` |
| Parent rendered system prompt | `forkSubagent()` uses `parent.renderedSystemPrompt` |
| Agent-specific system prompt | `spawnFreshSubagent()` uses `definition.instructions` |
| Exact parent tools for fork | `forkSubagent()` uses `parent.tools` |
| Resolved child tools for fresh agent | `spawnFreshSubagent()` uses `definition.tools` |
| Child isolated context | `createSubagentContext()` clones message/tool/state containers |
| Agent registry loading | `loadRuntimeRegistry()` scans `registry/agents/*.md` |
| Skill discovery | `discoverSkills()` scans `registry/skills/**/SKILL.md` and renders skill headers |
| Subagent hooks | `runDeclarativeHooks()` injects matching `SubagentStart` hook context |

## Registry, Skills, And Hooks

The fresh subagent path now loads local runtime context before constructing the
child payload:

```text
registry/agents/*.md
  -> parse frontmatter and body
  -> resolve listed tool ids
  -> override/fill the in-memory agent registry

registry/skills/**/SKILL.md
  -> parse name and description frontmatter
  -> render "The following skills are available..." developer context

registry/hooks/*.json
  -> select hooks matching event/scope
  -> inject additional hook context into the child context
```

The default demo includes `demo-subagent-start`, which appears in the generated
artifact as `hookIds: ["demo-subagent-start"]`. This mirrors the idea of
Claude Code hook-driven context injection without trying to reproduce its whole
hook runtime.

## Mastra-Native Delegation Hook

Mastra supervisor agents delegate through tool-like subagent calls. Current Mastra
docs say subagents receive the full supervisor conversation by default. The
control point is `delegation.messageFilter`, which decides which parent messages
are forwarded to the child.

This POC adds two reusable configs in `src/mastra/delegation.ts`:

- `claudeFreshDelegation`: passes zero parent history messages, matching Claude Code's normal `Agent({ subagent_type, prompt })` path where the parent has to write a self-contained brief.
- `claudeForkDelegation`: passes all parent messages, matching Claude Code's fork path where the child receives inherited conversation context plus a directive.

These configs are meant for real Mastra calls such as:

```typescript
await supervisorAgent.generate("Delegate the investigation", {
  delegation: claudeFreshDelegation,
});
```

Run:

```bash
npm install
npm run build
npm run poc
```

The POC uses deterministic local runners for the default demo so it does not require an API key. The `src/mastra/index.ts` file also exports Mastra agents so the same agent definitions can be inspected in Mastra Studio with `npm run dev`.

To try real Mastra Studio calls, set a model provider key and optionally override the default model:

```bash
export OPENAI_API_KEY=...
export MASTRA_MODEL=openai/gpt-5-nano
npm run dev
```
