# Figma Frontend E2E Semantic-Memory Experiment

This experiment is intended to push the agents through a longer cross-domain
workflow than the Redis tasks: design extraction, implementation, dependency
installation, and browser-level validation.

## What This Tests

- Whether MCP tools are added to the model-visible tool surface.
- Whether design-oriented skills or skill headers are loaded only when the task
  creates a reason to use them.
- Whether Claude Code changes active tool count only for subagent scopes or also
  for MCP/design phases.
- Whether Codex keeps a constant base surface, adds deferred tools, or changes
  skill/context layers when the task crosses into frontend and Playwright work.
- How the active context window evolves across a longer horizon with design
  notes, generated code, npm output, build output, and Playwright output.

## Added Benchmark Pack

Run config:

```bash
python -m orchestrator.matrix --config harness_configs/harness_config_semantic_figma_frontend_e2e.json --dry-run
python -m orchestrator.matrix --config harness_configs/harness_config_semantic_figma_frontend_e2e.json
```

Task:

- `tasks/feature/frontend_figma_design_to_playwright_app.json`

Codebase:

- `frontend_figma_app`
- Built from `builtin:frontend-figma-app-v1`
- Minimal Vite/TypeScript/Playwright scaffold with starter app, test file, and
  `docs/implementation-notes.md`.

## Required Figma MCP Setup

The task intentionally requires the agent to prove that Figma MCP tools are
available before implementation. If Figma MCP is missing, the expected outcome
is `FIGMA_MCP_UNAVAILABLE.md`, which is useful as a failed setup diagnostic but
not as a complete semantic-memory run.

For Claude Code, provide a Claude MCP config via:

```bash
export CLAUDE_MCP_CONFIG=/home/abhi/agent-harness-bench/docs/semantic_memory/figma_mcp_configs/claude_figma_remote_mcp.json
export CLAUDE_STRICT_MCP_CONFIG=1
export FIGMA_FILE_URL='https://www.figma.com/file/...'
export FIGMA_NODE_ID='optional-node-id'
```

For Codex, the harness supports a streamable HTTP MCP server:

```bash
export CODEX_MCP_FIGMA_URL='https://.../mcp'
export CODEX_MCP_FIGMA_URL='https://mcp.figma.com/mcp'
export FIGMA_FILE_URL='https://www.figma.com/file/...'
export FIGMA_NODE_ID='optional-node-id'
```

The host machine has also been configured with the remote Figma MCP server:

```bash
claude mcp add --scope user --transport http figma https://mcp.figma.com/mcp
codex mcp add figma --url https://mcp.figma.com/mcp
```

As of setup time, Claude reports the server as `Needs authentication` and
Codex lists it as enabled but not logged in. Complete the client OAuth/login
step before running the benchmark against a private or team Figma file.

## Analysis Plan

After the run, produce the same plots as the Redis comparison:

- time/request index vs exact input tokens
- time/request index vs active tools
- time/request index vs skill headers loaded
- time/request index vs active skill invocations

Then add two extra event overlays:

- Figma/MCP phase: first request where Figma MCP tools appear or are invoked.
- Playwright phase: first npm/build/test/browser-related subprocess or tool
  output.

The key thing to watch is whether active tools change because of MCP injection,
subagent delegation, or both. In the Redis traces, Claude Code's `27 -> 17 -> 27`
tool-count pattern aligned with Explore subagents. This task is designed to test
whether a richer, MCP-heavy workflow introduces additional tool-surface changes.
