# Instrumentation Findings - 2026-05-29

This note summarizes the completed Docker runs from `20260529T151312_*`, plus
the Codex/DeepSeek compatibility smoke at `20260529T154714_*`.

## Run Validity

- Valid completed rows: 10.
- Complete Claude rows: 7/7, all on `deepseek-v4-pro[1m]`.
- Complete Codex rows: 3 useful rows from the interrupted mixed-model run
  (`empty_task`, `redis_getex_expired_event`, `redis_getex_expired_event_tests`).
- Invalid row: `20260529T151312_codex_redis_expire_options...` was manually
  stopped after we noticed Codex was still using `gpt-5.5`.
- Codex + `deepseek-v4-pro` smoke failed before task work. The configured Codex
  provider is Azure Responses API, and Azure returned 404 for a deployment named
  `deepseek-v4-pro`. A direct DeepSeek OpenAI-compatible probe also failed
  because current Codex CLI rejects `wire_api = "chat"` and DeepSeek does not
  expose `/responses`.

## Headline Pattern

Most completed tasks stayed near each agent's startup/runtime floor. Claude's
baseline was about 282 MB PSS, and most Claude QA/test/Linux feature rows stayed
near 280-284 MB. Codex's baseline and completed Redis rows stayed near 156-158 MB.

The outlier was Claude on `redis_expire_conditional_options`: 697 MB peak PSS,
486 seconds wall time, 66 model-level tool calls, 1,948 total tool/subprocess
events, and 137 grepped file arguments. The peak was attributed to the Redis
build/test burst, not ordinary search: the top non-agent spans were `bash`,
`make -j15`, and nested `make`, all around 463 MB PSS.

## Per-Run Metrics

| Agent | Task | Peak PSS MB | Wall s | Model tool calls | Tool/subprocess events | Files grepped | Zero-match searches | Reads later edited | Output MB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| claude_code | empty_task | 281.8 | 3.8 | 0 | 6 | 1 | 2 | 0 | 0.004 |
| claude_code | linux_proc_thread_self | 279.6 | 207.1 | 28 | 35 | 1 | 2 | 0 | 0.006 |
| claude_code | linux_string_get_size_return_length | 283.8 | 114.5 | 21 | 34 | 1 | 2 | 0 | 0.009 |
| claude_code | linux_string_get_size_tests | 280.8 | 288.9 | 18 | 31 | 1 | 2 | 0 | 0.009 |
| claude_code | redis_expire_conditional_options | 697.4 | 485.6 | 66 | 1948 | 137 | 28 | 0 | 1.054 |
| claude_code | redis_getex_expired_event | 284.1 | 113.1 | 32 | 37 | 1 | 2 | 0 | 0.006 |
| claude_code | redis_getex_expired_event_tests | 280.7 | 210.2 | 48 | 53 | 1 | 2 | 0 | 0.005 |
| codex | empty_task | 156.2 | 2.6 | 0 | 33 | 0 | 0 | 0 | 0.003 |
| codex | redis_getex_expired_event | 158.0 | 121.5 | 19 | 115 | 17 | 4 | 0 | 0.412 |
| codex | redis_getex_expired_event_tests | 155.9 | 105.2 | 29 | 153 | 49 | 8 | 1 | 0.630 |

## Tool-Use Shape

Claude model-level calls across valid rows:

- Total: 213
- Most common: `Read` 86, `Grep` 79, `Bash` 11, `Edit` 13, plus task/subagent
  bookkeeping.
- The heavy Redis feature run used `Grep` 25, `Read` 24, `Bash` 9, `Edit` 3,
  and one subagent call.

Codex model-level calls across completed valid rows:

- Total: 48
- Most common command roots: `nl` 14, `rg` 13, `sed` 12, `git` 4, `runtest` 2.
- The Redis test-writing row read the file it later edited
  (`tests/unit/type/string.tcl`) and attempted a focused test, which failed
  because the container lacks Tcl.

Subprocess totals show a different story from model-level calls:

- Claude: 2,144 total tool/subprocess events across valid rows, dominated by
  the Redis build: `rm` 385, `gcc` 366, `cat` 342, `sed` 213, `awk` 188.
- Codex: 301 total tool/subprocess events across completed rows, dominated by
  shell-wrapped commands: `bash` 120, `git` 79, `sed` 52.

## What Triggered Expense

The clear trigger we can observe today is not "search in general"; it is a
model decision to build Redis. In the heavy Claude feature run, the assistant
issued a `Bash` tool call for `make -j$(nproc)`, after which the process tree
fanned out into `make`, `gcc`, `sh`, `sed`, `awk`, `rm`, and related build
helpers. That one build/test phase accounts for the only >600 MB memory peak
seen in this batch.

Search and reads still matter for workflow quality. The Redis feature task had
28 zero/low-output searches and 137 grepped file arguments. Codex's completed
Redis test-writing task had 8 zero-match/low-output searches and 49 grepped
file arguments. These are small memory events compared with build/test, but
they explain time and context churn.

## Context And Prompt Surface

Claude stream init exposes the loaded prompt/tool surface directly:

- Tools: 28 loaded tools, including `Bash`, `Read`, `Grep`, `Edit`, `Glob`,
  `Task`, `Agent`, web tools, task-management tools, and workflow tools.
- Skills: 12 loaded skills from the Claude environment.
- Slash commands: 23 loaded slash commands.
- Project/home inventory: the harness detected two home setting files and no
  project skills/agents/commands in these Docker runs.

Codex context capture currently shows one copied config file and no project
Codex config, plugins, or skills. Codex also performs startup plugin discovery:
even baseline runs include git activity against the OpenAI plugins repository.

## Remaining Observability Gaps

- Structured agent events still do not carry timestamps, so
  `decision_trace_summary.json` remains a coverage report. We can count
  assistant events and tool calls, but precise model-event-to-process-span joins
  need either timestamped stream events or a wrapper observer that timestamps
  stdout JSONL as it arrives.
- Claude exact tool calls are now recovered from `tool_use` blocks. Codex exact
  commands are now recovered from JSON `command_execution` items.
- Some shim-derived search metrics include command-internal `grep` calls from
  build/configure scripts. The derived metrics are useful, but high-confidence
  "model intentionally searched" should prefer structured model-level tool calls
  where available.
