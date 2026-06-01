# Semantic Memory Instrumentation Plan - 2026-06-01

This is the next measurement layer for the CTO question: not "which PID used
RAM?", but "what information was carried in the agent's model context window,
how did it grow, and which layers were responsible?"

## Goal

For one open-source agent first, Codex, we want request-by-request accounting of:

- base/system instructions
- developer/project context
- user task text
- tool schemas
- assistant messages and reasoning state
- tool calls and tool outputs
- file contents retained through tool outputs
- compaction/summarization events
- context-window growth over time

This is semantic memory. It is measured in serialized prompt chars and estimated
tokens, not OS RSS/PSS.

## Codex Source-Level Model

Codex is the best first target because its context pipeline is visible in the
open-source Rust code under `/tmp/agent-harness-src/codex`.

Key source path:

```text
/tmp/agent-harness-src/codex/codex-rs/core/src/context_manager/history.rs
/tmp/agent-harness-src/codex/codex-rs/core/src/session/turn.rs
/tmp/agent-harness-src/codex/codex-rs/core/src/client.rs
/tmp/agent-harness-src/codex/codex-rs/core/src/compact.rs
```

What the code shows:

- `ContextManager` stores the conversation as `ResponseItem`s. These are the
  model-visible history items: user messages, assistant messages, tool calls,
  tool outputs, reasoning blobs, compaction items, and contextual developer/user
  fragments.
- Before a model request, Codex calls `clone_history().for_prompt(...)`. That
  normalizes history, drops invalid call/output pairs, strips unsupported images,
  and returns the `ResponseItem` list that will be sampled.
- `build_prompt(...)` combines that history with base instructions and the
  model-visible tool specs.
- `ModelClient::build_responses_request(...)` serializes the final request:
  `instructions`, `input`, `tools`, reasoning config, service tier, prompt cache
  key, and other metadata.
- Function/tool outputs are truncated before being recorded into history using
  `truncate_function_output_payload(...)`. This is the main place where file
  reads and command outputs become bounded semantic memory rather than unbounded
  raw stdout.
- Token accounting is partly server-observed and partly estimated. Codex tracks
  last API token usage plus estimated bytes/tokens added after the last model
  response.
- Auto-compaction checks active context usage against
  `model_auto_compact_token_limit` and/or the model context window. If a limit
  is reached, Codex runs a compaction task and replaces history with a summary
  plus selected user messages.
- Compaction has two important modes:
  - pre-turn compaction can replace history with a summary and force full
    context reinjection next turn.
  - mid-turn compaction can inject initial context before the last user message
    so a tool loop can continue after summarization.

The practical interpretation: Codex memory is layered as:

```text
base instructions
+ tool schema menu
+ developer/project context
+ user task
+ accumulated model messages
+ accumulated tool calls
+ accumulated tool outputs, including file contents
+ reasoning/compaction artifacts
```

## Harness Changes Added

### Rich API Request Summaries

`measure/api_observer_proxy.py` now recognizes Responses API `input` arrays as
Codex `ResponseItem`s instead of treating them like generic chat messages.

For every model request it records:

- item count by `type`
- item count by `role`
- semantic layer totals
- per-item payload size and hash
- tool schema names and schema size
- base instruction size/hash
- approximate token counts using a simple chars/4 estimator

The normal mode still avoids raw prompt text.

### Opt-In Prompt Capture

For controlled benchmark repositories, enable sanitized prompt capture:

```bash
HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1
HARNESS_API_OBSERVER_CAPTURE_CHARS=200000
```

This adds sanitized `capture` fields to `api_requests.jsonl`. It is off by
default. The sanitizer redacts obvious API-key/token/password/bearer patterns,
but the intended use is still controlled open-source benchmark runs, not private
customer code.

Newer observer builds also record a sanitized full `request_body_capture` when
capture mode is enabled. That gives us the exact Responses API JSON envelope
Codex sent, including `instructions`, `input`, `tools`, reasoning settings,
stream flags, prompt cache key, and client metadata. The semantic field captures
remain useful because they split that envelope into human-sized prompt layers.

### Semantic Context Artifacts

New script:

```bash
python -m analysis.semantic_context runs/<run_id>
```

Outputs:

```text
runs/<run_id>/semantic_context_timeline.jsonl
runs/<run_id>/semantic_context_summary.json
```

The timeline has one row per model request with:

- request index, model, request kind, window id
- body chars and delta from previous request
- semantic layer chars and deltas
- static prompt chars vs carried memory chars
- file/tool-output chars
- input item counts by type and role
- instruction and tool-schema hashes
- whether prompt capture was present

The summary reports:

- max semantic request size
- serialized chars by layer across the whole run
- repeated static overhead from resending the same instructions/tool schema
- number of context-window ids and request kinds

For exact prompt-string inspection, run:

```bash
python -m analysis.prompt_payloads runs/<run_id>
```

Outputs:

```text
runs/<run_id>/prompt_payloads.jsonl
runs/<run_id>/prompt_payload_report.md
```

`prompt_payloads.jsonl` is the machine-readable answer to "what was in every
prompt?" It contains one record per API request with the captured base
instructions, tool schema, raw request body when available, and every
model-visible input item. `prompt_payload_report.md` is the readable version:
static prompt blocks are de-duplicated, and each request lists its user,
developer, assistant, tool-call, and tool-output strings.

In the Codex source, these strings are assembled as follows:

```text
ContextManager.items
  -> clone_history().for_prompt(...)
  -> build_prompt(input, tool_router, turn_context, base_instructions)
  -> ModelClient::build_responses_request(...)
  -> POST /v1/responses
```

Important source locations in the local Codex clone:

```text
/tmp/agent-harness-src/codex/codex-rs/core/src/context_manager/history.rs
/tmp/agent-harness-src/codex/codex-rs/core/src/session/turn.rs
/tmp/agent-harness-src/codex/codex-rs/core/src/client.rs
```

### Agent-Isolated Process Memory

`analysis.hotspots` now writes an additional process-memory view:

```text
resource_hotspots.json -> run_peak_agent_isolated
summary.json -> behavior.top_agent_isolated_memory_spans
```

This excludes build/test/package spans from the peak calculation by removing
sampled rows for PIDs under those spans during their active windows.

Reason: `make`, compilers, Redis tests, and package managers are real task
workload, but they swamp the signal when the research question is semantic agent
memory. We still keep the original process-tree peak for resource benchmarking;
the agent-isolated peak is the right view for context/memory behavior.

## What We Should Run Next

Run one Codex task with semantic capture enabled. Use Docker and the DeepSeek
Codex route as before, but keep the task narrow enough to finish before the
meeting.

Recommended first run:

```bash
HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1 \
HARNESS_API_OBSERVER_CAPTURE_CHARS=200000 \
python -m orchestrator.matrix harness_configs/harness_config_redis_linux_codex_deepseek.json
```

If time is tight, create a one-task config for:

```text
linux_string_get_size_return_length
```

If we want the most informative stress case, use:

```text
redis_expire_conditional_options
```

After the run:

```bash
python -m analysis.semantic_context runs/<run_id>
python -m analysis.hotspots runs/<run_id>
```

Then inspect:

```text
runs/<run_id>/semantic_context_summary.json
runs/<run_id>/semantic_context_timeline.jsonl
runs/<run_id>/resource_hotspots.json
```

## What This Will Let Us Say Tomorrow

For Codex, we should be able to answer:

- How large was the base instruction layer?
- How large was the repeated tool schema layer?
- How much of each request was actual carried history?
- How much carried history came from file/tool outputs?
- Which request first ballooned because of a file read or command output?
- Whether Codex compacted, switched context windows, or stayed in one growing
  window.
- Whether apparent memory spikes were agent context growth or project build/test
  processes.

This gets us much closer to the CTO's semantic question: not just "Codex used
X MB", but "Codex carried Y tokens of base prompt, Z tokens of tool/file memory,
and the context grew at these exact turns because of these exact tool results."

## Initial Validation Runs

After adding the instrumentation, the base and Codex Docker images were rebuilt
so Docker runs use the upgraded observer.

Capture smoke:

```text
runs/20260601T194703_codex_empty_baseline_empty_task_nocap_rep0
```

Result:

- 1 model request
- prompt capture present
- body size: 49,996 chars, about 12,499 tokens
- semantic total: 49,208 chars, about 12,302 tokens
- base instructions: 21,437 chars
- tool schema: 22,423 chars
- developer context: 4,997 chars
- user/task text: 351 chars

Real semantic-growth probe:

```text
runs/20260601T194734_codex_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0
```

Result:

- task succeeded
- 12 model requests
- 20 tool invocations
- peak process-tree PSS: 176.0 MB
- no build/test/package spans on this task, so agent-isolated peak was also
  176.0 MB
- max request body: 78,544 chars, about 19,636 tokens
- max semantic payload: 74,792 chars, about 18,698 tokens
- static prompt layer at max request: 49,451 chars
- carried memory at max request: 25,341 chars
- file/tool-output memory at max request: 22,232 chars
- context stayed in one Codex window id; no compaction occurred

Most useful interpretation from the Redis probe:

- The fixed Codex request floor is large: base instructions plus tool schema
  were about 43.9k chars before task/developer context.
- Context growth was mostly tool-output memory. It rose from 0 chars on request
  1 to 22,232 chars by request 12.
- Tool calls and tool outputs accumulated monotonically: request 12 contained
  20 `function_call` items and 20 `function_call_output` items.
- Assistant-message memory was tiny on this task: 131 chars at the max request.
- The context window did not swap or compact; the observed behavior was simple
  append-only growth within one window.

Largest retained tool outputs at the max request were:

- `sed -n '335,430p' src/t_string.c`: 4,041 chars
- `sed -n '1713,1800p' src/db.c`: 3,929 chars
- `rg -rn -i "getex" src/`: 3,113 chars
- `sed -n '620,660p' src/expire.c`: 1,740 chars
- `sed -n '1618,1650p' src/db.c`: 1,564 chars

So for this task, the "memory of files explored" is visible as retained command
outputs from `src/t_string.c`, `src/db.c`, `src/expire.c`, and grep/ripgrep
results. It is not an opaque process-memory guess anymore.

This is the shape of the answer we want for larger tasks too: distinguish the
large fixed prompt/tool menu, the task text, and the actual retained file/tool
memory that grows over the run.
