# System Prompt Investigation - 2026-05-31

This note records what we can currently say about prompt/context causes behind
the Claude Code and Codex behavior in the latest Redis/Linux matrix runs.

## What We Investigated

Run context came from the completed observer batch:

- Claude run example:
  `runs/20260529T183728_claude_code_empty_baseline_empty_task_nocap_rep0/agent_context.json`
- Codex run example:
  `runs/20260529T183728_codex_empty_baseline_empty_task_nocap_rep0/agent_context.json`

Installed agent versions:

- Claude Code: `2.1.156 (Claude Code)`
- Codex CLI: `codex-cli 0.135.0`

Prompt/source references checked:

- Claude Code prompt inventory:
  `Piebald-AI/claude-code-system-prompts`, tag `v2.1.156`,
  commit `b48f2fd7b1c63fe857f3672563d0b9c601926a20`
- Codex source:
  `openai/codex`, tag `rust-v0.135.0`,
  commit `4daceea869704f9f35e0a3949fc34711ef978a4e`

The installed Claude and Codex packages both ship mostly as native binaries in
our Docker images. Local `strings` inspection did not produce reliable full
prompt text. For Claude, the practical reference is the versioned external
prompt inventory. For Codex, the exact source tag contains the model catalog and
prompt assembly code.

## What Was Actually In Scope

The latest matrix runs did not have project-specific instruction files or
skills loaded by our harness.

Claude Code recorded available context:

- `home_settings`: 2
- `project_settings`: 0
- `home_skills`: 0
- `home_agents`: 0
- `home_commands`: 0
- `project_skills`: 0
- `project_agents`: 0
- `project_commands`: 0

Codex recorded available context:

- `config_files`: 1
- `plugins`: 0
- `skills`: 0
- `project_codex`: 0

Important interpretation: this means the observed behavior is primarily coming
from the base agent prompt, built-in tool descriptions, model behavior, and the
user task prompt. It is not explained by extra project skills, command packs, or
repo-local instruction files.

## Codex Effective Prompt Observations

Codex has a useful local debugger:

```bash
codex -m gpt-5.5 --dangerously-bypass-approvals-and-sandbox \
  debug prompt-input "Empty baseline run. Do not inspect files, do not run tools, and do not edit anything. Reply exactly BASELINE_OK."
```

In our Docker image this rendered three model-visible input messages:

- a developer permissions block
- an environment context block
- the user task prompt

The permissions block told the model that sandboxing was `danger-full-access`,
network access was enabled, and approval policy was `never`. That removes most
friction from running local shell commands.

The debug command does not print the base model instructions in the JSON input
list. Codex sends those separately as the Responses API `instructions` field.
The source confirms this path:

- `codex-rs/core/src/session/mod.rs` resolves base instructions from config,
  conversation history, or the selected model catalog entry.
- `codex-rs/core/src/client.rs` passes `prompt.base_instructions.text` as the
  request instructions.
- `codex-rs/models-manager/models.json` contains the `gpt-5.5` base
  instructions used by our `-m gpt-5.5` runs.

Behaviorally relevant Codex base-instruction themes:

- Prefer `rg`/`rg --files` for search.
- Read the codebase first and follow existing patterns.
- Persist until the task is handled end to end.
- Run appropriate verification when changes are made.
- Use `apply_patch` for manual edits.
- Parallelize independent tool calls when possible.

This matches our observed Codex style: shell-heavy exploration with `rg`,
`sed`/`nl`, `git`, edits through patching, and a tendency to keep verifying
after failures.

## Claude Code Prompt Inventory Findings

Claude Code v2.1.156 maps cleanly to the external prompt inventory tag
`v2.1.156`. That inventory contains hundreds of fragments, including base
software-engineering instructions, tool descriptions, reminders, subagent
prompts, and optional skill prompts. The repository itself warns that the exact
session prompt can vary with configuration and conditional sections.

Behaviorally relevant Claude fragments in that version:

- Ambiguous/generic user requests are interpreted as software-engineering work
  in the current working directory.
- Local reversible actions such as editing files and running tests are allowed.
- Outcomes should be reported truthfully, including failed or skipped tests.
- Plan completion can trigger a direct verification reminder.
- Bash guidance says to prefer dedicated tools for read-only search/read style
  work.
- Grep guidance routes search tasks through Claude's `Grep` tool instead of
  shell `grep`/`rg`.
- Edit guidance prefers editing existing files and read-before-edit behavior.
- Bash guidance allows independent shell commands to be issued in parallel.

This matches our observed Claude style: many structured `Grep`/`Read`/`Edit`
events, fewer raw shell search commands than Codex, and substantial verification
after implementation.

Claude's `--debug-file` did not expose the raw effective prompt in our quick
probe. It logged runtime/debug lifecycle details, but not the full request body.
To prove the exact system prompt sent to the model, we need an API-level
observer or a supported Claude debug mode that emits the outbound request
payload.

## Behavioral Conclusions

The strongest prompt-level explanation is not "the prompt tells the agent to
run expensive commands." It is more subtle:

- The prompts tell both agents to treat requests as coding tasks, inspect the
  repo, make local changes, and verify work.
- Claude's tool descriptions shape *which* tools it uses: built-in `Grep`,
  `Read`, and `Edit` rather than shell `rg`/`sed` for many actions.
- Codex's base instructions shape *which* shell commands it uses: especially
  `rg`/`rg --files` for search and patch-based editing.
- Permission/developer context tells Codex it is allowed to run commands without
  asking, so it has little reason to avoid local verification.
- No loaded skills explain the latest matrix behavior. Skills were effectively
  absent in these runs.

The most expensive observed behavior, especially Claude's Redis memory spike,
is still best explained as:

1. prompt pressure to verify the completed task,
2. model/agent choice of a broad build/test command,
3. project build system fanout, such as `make -j$(nproc)`,
4. missing container dependencies causing some verification attempts to fail or
   expand.

We did not find a Claude or Codex prompt fragment that explicitly says to run
`make -j$(nproc)` or maximize build parallelism. That detail appears to be a
model/tool-use heuristic, not a direct prompt instruction.

## What This Means For Causal Research

We can now separate likely causes:

- Base/system prompt causes broad tendencies: inspect, edit, verify, persist.
- Tool descriptions cause tool routing: Claude built-ins versus Codex shell
  commands.
- Permissions context causes autonomy: fewer pauses before local commands.
- Model priors likely cause concrete command choices: `make`, `make test`,
  parallelism level, repeated failed verification strategy.
- Harness/task design causes verification demand: our tasks ask for real fixes
  against real repos, so build/test attempts are natural rather than inherently
  wasteful.

The next causal step should be ablation, not optimization:

- Run the same task with an added instruction like "use at most two build jobs"
  and compare memory peaks.
- Run the same task with "do not run full project test suites; write or run only
  targeted tests" and compare command choice.
- Run the same task with Claude `--bare` and no auto-discovery, then compare
  tool routing and verification.
- Run Codex with a temporary `model_instructions_file` that removes persistence
  and verification pressure, then compare behavior.
- Use the implemented API request observer/proxy for both agents where their
  base URL can be configured. It captures redacted outbound request metadata:
  instruction hash, tool list, tool schema names, system/developer/user message
  sizes, model, base URL route, and request timestamps.

That observer gives us the missing proof layer for supported routes: not just
"this prompt inventory existed," but "this exact prompt/tool set was sent for
this run."
