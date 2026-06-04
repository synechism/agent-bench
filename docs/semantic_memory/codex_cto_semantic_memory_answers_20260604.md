# Codex Semantic Memory Consumption: CTO Question Answer Report - 2026-06-04

This report consolidates the Codex-only findings from the semantic-memory
investigation. It answers the CTO question set directly: semantic-level memory
consumption, context-window construction, file memory, prompt contents,
semantic layering, and context growth over task time.

The report is intentionally scoped to Codex's model-visible request path. The
evidence comes from captured `/v1/responses` payloads, structured run events,
tool outputs, and verifier outcomes. This is the path that determines what text
the model can actually consume at each turn.

Claude Code auto-update and public-version questions are out of scope for this
Codex report.

## Executive Answer

Codex semantic memory consumption is a carried structured transcript.

The model-visible context at each request is assembled from:

```text
static instruction/tool envelope
  + task and environment context
  + prior user/assistant turns
  + prior tool calls
  + admitted prior tool outputs
  + occasional reasoning/assistant memory items
```

The dominant dynamic memory source is tool output. In coding tasks, file memory
is not stored as an opaque file cache in the observed request path. File memory
is usually literal text from earlier `rg`, `cat`, `sed`, test, patch, or shell
outputs replayed into later requests.

New memory enters the model-visible context on the next request after the model
causes it:

```text
request N: model asks for a tool call
environment: harness executes the command
request N+1: tool call and admitted tool output appear in input[]
```

Across all Codex runs analyzed so far, the carried transcript behaved
append-only. No carried item disappeared before the final request. The largest
observed append-only run reached 65 model requests, 151 carried-memory items,
613,873 chars of visible carried memory, and a 666,179-char request body.

## Methodology

We did not infer memory from task success alone. We instrumented the request
path and then joined request contents with run events.

### 1. Prompt Payload Capture

We enabled API observer prompt capture for Codex runs. This produced literal
request payload records, including the `input` arrays sent to
`/v1/responses`.

Representative environment settings used for the sentinel runs:

```bash
CODEX_MODEL_PROVIDER=azure
CODEX_PROVIDER_BASE_URL=https://cronwell-codex-2.openai.azure.com/openai/v1
CODEX_PROVIDER_ENV_KEY=AZURE_API_KEY
CODEX_PROVIDER_WIRE_API=responses
HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1
HARNESS_API_OBSERVER_CAPTURE_CHARS=2000000
```

The prompt payloads are the ground truth for model-visible semantic memory in
these experiments.

### 2. Static Prompt Decomposition

We ran an empty Codex baseline and decomposed the request body into stable
semantic layers:

| static layer | chars |
| --- | ---: |
| tool schema | 22,423 |
| base instructions | 21,437 |
| developer/skills/context | 4,997 |
| task/environment | 351 |
| total static floor | 49,208 |

This established that a Codex run begins with a large fixed context floor
before any task-specific memory exists.

### 3. Semantic Aggregate Analysis

We measured how much of each request came from static prompt material versus
carried task material. The representative Codex suite included:

```text
runs/20260601T202331_codex_empty_baseline_empty_task_nocap_rep0
runs/20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0
runs/20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0
runs/20260601T202331_codex_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0
```

At maximum request size:

| task | requests | max approx tokens | static chars | carried chars | file/tool chars |
| --- | ---: | ---: | ---: | ---: | ---: |
| empty baseline | 1 | 12,302 | 49,208 | 0 | 0 |
| Redis GETEX QA | 23 | 20,456 | 49,451 | 32,371 | 28,478 |
| Redis GETEX tests | 112 | 40,398 | 49,482 | 112,107 | 82,403 |
| Redis EXPIRE feature | 57 | 38,714 | 49,551 | 105,304 | 68,386 |

This showed the transition from static-envelope dominated requests to
carried-transcript dominated requests on longer tasks.

### 4. Lifecycle Item Tracking

We built `analysis.codex_memory_lifecycle` to track carried item identity
across requests.

The analyzer answers:

- which request first contains carried memory,
- which semantic item type each memory item has,
- how many chars each item contributes,
- whether the item remains visible through the final request,
- whether any item disappears before the end.

For the representative Codex runs:

| run | requests | first memory request | carried items | retained to final | dropped/compacted |
| --- | ---: | ---: | ---: | ---: | --- |
| empty baseline | 1 | none | 0 | 0 | false |
| Redis GETEX QA | 23 | 2 | 55 | 55 | false |
| Redis GETEX tests | 112 | 2 | 257 | 257 | false |
| Redis EXPIRE feature | 57 | 2 | 149 | 149 | false |

This proved the N+1 materialization rule for observed tool calls and outputs.

### 5. Turn Ledger

We built `analysis.codex_turn_ledger` to convert request growth into a causal
state-machine view.

Each ledger row links:

| stage | evidence |
| --- | --- |
| request N visible context | captured prompt payload |
| model action after request N | structured events and tool call items |
| environment result | command output, file output, test logs, patch results |
| request N+1 materialization | newly visible carried items |
| retention | item identity across later requests |

This is the core method that turns raw request-size accounting into semantic
memory analysis.

### 6. Sentinel Fidelity Tasks

We added a task-agnostic built-in codebase, `semantic_memory_sentinel`, to test
whether model-visible memory was also usable memory.

The sentinel tasks used:

- files containing canonical facts,
- distractor/noise files,
- answer files the model had to fill in,
- verifiers that checked answers without revealing expected values,
- scorers that checked fact visibility in prompt payloads,
- event probes that checked whether Codex re-read facts after the noise phase.

This separated three concepts:

```text
fact was observed
fact remained visible
fact was used correctly
```

## Direct Answers To The CTO Questions

### 1. Semantic-Level Memory Consumption Versus Process-Level Memory Consumption

We answered the semantic-level question directly. The measured object is not
RAM usage, process state, file descriptors, or CLI-side working memory. The
measured object is the semantic content sent to the model in each API request.

Codex consumes semantic memory through request payloads. The unit of memory is
not a process object. The practical unit is a structured Responses API item:

| item type | semantic role |
| --- | --- |
| `function_call` | model-requested shell/tool command |
| `function_call_output` | admitted output from command/file/test execution |
| `custom_tool_call` | model-requested patch operation |
| `custom_tool_call_output` | patch result/output |
| `message` | assistant/user message content carried forward |
| `reasoning` | visible reasoning/summary-like carried item |

This gives a semantic memory model, not a process memory model.

### 2. Context Window And Pool Of Possible Tokens

The pool of possible model-visible tokens has two parts:

1. Fixed/static material that is present before the task does anything.
2. Dynamic/carried material produced as the task unfolds.

The fixed pool is dominated by:

| fixed pool component | observed chars |
| --- | ---: |
| tool schema | 22,423 |
| base instructions | 21,437 |
| developer/skills/context | 4,997 |
| task/environment | 351 |

The dynamic pool includes:

- user task text,
- assistant messages,
- tool calls,
- shell command outputs,
- file snippets,
- search results,
- test logs,
- patch attempts,
- patch results,
- verifier output,
- reasoning/summary-like items.

The context window grows when dynamic items are admitted to the carried
transcript and replayed into subsequent requests.

### 3. File-Based Versus Memory-Based Context

For Codex in these runs, file-based context becomes memory-based context only
after the model reads or searches files through tools.

The repo itself is not automatically loaded in full. File material entered the
context through commands such as:

```text
rg ...
sed -n ...
cat ...
pytest ...
git diff ...
apply_patch ...
```

Once the output was admitted, it became carried transcript memory.

In the Redis GETEX tests run, max carried memory was 112,107 chars and
file/tool chars were 82,403. In the Redis EXPIRE feature run, max carried
memory was 105,304 chars and file/tool chars were 68,386. In the distance-60
sentinel run, 570,392 chars of first-seen carried memory came from tool-output
memory.

The answer is direct: Codex file memory is primarily retained tool output.

### 4. Where Codex Retains Memory Of Files It Explored

Codex retains memory of explored files in later request `input` items.

The causal path is:

```text
model requests file inspection
  -> harness executes command
  -> file text appears in tool output
  -> output is admitted as function_call_output
  -> function_call_output is replayed in later input arrays
  -> model can attend to that file text later
```

For example, in the Redis tasks, source/test snippets read with `sed` and
`grep` appeared as later `function_call_output` items. In the sentinel tasks,
facts read from files remained literally visible in later prompt payloads and
were used to answer verifier-checked questions.

The observed file memory location is not an external repo index and not a
separate hidden cache. It is the carried request transcript.

### 5. What Is In Every Prompt

Every observed Codex prompt/request contains a large static envelope plus any
carried transcript material available at that point.

The static floor is approximately 49k chars:

```text
tool schema                22,423 chars
base instructions          21,437 chars
developer/skills/context    4,997 chars
task/environment              351 chars
```

After the first tool call cycle, requests also contain carried items from
prior turns. The first carried memory appears on request 2 in non-empty tool
runs.

The request is therefore layered like this:

```text
request body
  static layer
    tool schema
    base instructions
    developer/skill context
    task/environment context
  dynamic carried layer
    prior assistant/user messages
    prior function calls
    prior function call outputs
    prior custom tool calls
    prior custom tool outputs
    reasoning/summary-like items
```

This is the architecture of "what is in every prompt" for the observed Codex
runs.

### 6. What Actually Gets Loaded

What gets loaded is exactly what appears in the request payload.

For files, only the text emitted by file-reading/searching commands gets
loaded into the model-visible context. A file that exists in the workspace but
is never read or searched does not appear as semantic memory in the captured
request path.

For tool outputs, the raw environment output is not automatically equal to
model-visible memory. It passes through an admission/truncation layer.

The 32-chunk pressure run demonstrated this clearly:

| metric | value |
| --- | ---: |
| raw original output tokens reported by environment | about 53,880 |
| retained noisy output chars visible to model | about 16,156 |
| tool-call cap used by Codex | `max_output_tokens: 4000` |

The loaded semantic memory is the admitted output, not the full raw output.

### 7. Semantic Layer / Architectural View

Codex semantic memory consumption is a state machine:

```text
1. request assembly
   static instructions + tool schema + task + carried transcript

2. model decision
   assistant text, tool calls, patches, plans, final messages

3. environment execution
   shell output, file snippets, test logs, patch results

4. transcript capture
   call records and admitted outputs become structured conversation items

5. next request materialization
   newly captured items appear in the next request input array

6. retention
   items continue to be replayed across later requests

7. later use
   model uses, ignores, corrupts, or re-derives the retained material
```

The model does not visibly choose "store this memory" as a separate operation.
It chooses actions: read this file, search this symbol, run this test, apply
this patch. The client/harness then carries the resulting transcript forward.

So the model influences memory indirectly through tool choice and command
shape. Narrow `rg` commands produce compact memory. Broad `cat` or noisy test
commands produce large memory, subject to output admission caps.

### 8. At What Point Codex Adds To The Context Window

Codex adds new semantic memory to the model-visible context before the next
model request.

The observed rule is:

```text
request N response contains tool call
tool executes after request N
request N+1 input contains the tool call and admitted output
```

This held across the representative Redis tasks and sentinel probes.

Concrete representative run evidence:

| run | first carried memory request |
| --- | ---: |
| Redis GETEX QA | 2 |
| Redis GETEX tests | 2 |
| Redis EXPIRE feature | 2 |
| sentinel baseline | 2 |
| distance-60 sentinel | 2 |

The context window grows in discrete request-to-request steps, not continuously
inside the same request.

### 9. At What Point Codex Swaps, Drops, Or Compacts

We have not observed swapping, dropping, or compaction in the Codex request
path yet.

The strongest observed boundary is the distance-60 sentinel run:

| metric | value |
| --- | ---: |
| API requests | 65 |
| carried-memory items | 151 |
| retained to final | 151 |
| dropped/compacted items | 0 |
| max visible carried-memory chars | 613,873 |
| max request body chars | 666,179 |

The answer today is strong and narrow: through this observed boundary, Codex
kept replaying the carried transcript. No earlier call/output item disappeared.
No summary replacement was detected. No request showed a transition from
literal replay to compacted memory.

This establishes the lower bound for append-only behavior. The first true
compaction boundary remains the next target experiment.

### 10. How Context Grows Over Time For A Specific Task

The distance-60 sentinel run gives the cleanest growth curve because it
separates fact collection from long irrelevant output.

Facts were collected once:

```text
rg "MANY_SENTINEL" many_facts
```

Then Codex read 60 irrelevant files:

```text
cat distance_noise/noise_01.txt
cat distance_noise/noise_02.txt
...
cat distance_noise/noise_60.txt
```

Growth checkpoints:

| checkpoint | request body chars | visible memory chars |
| --- | ---: | ---: |
| request 2 | 42,255 | 6,424 |
| request 12 | 149,277 | 110,760 |
| request 23 | 263,291 | 221,823 |
| request 33 | 365,715 | 321,633 |
| request 43 | 467,011 | 420,387 |
| request 53 | 568,289 | 519,123 |
| request 65 | 666,179 | 613,873 |

This shows linear-ish growth under repeated admitted tool outputs. Each
distance file contributed roughly 9.4k chars of retained tool-output memory
plus its tool-call item for most of the run.

### 11. Whether Retained Memory Is Actually Usable

The sentinel probes answered usability, not just visibility.

Baseline sentinel probe:

| metric | value |
| --- | ---: |
| API requests | 7 |
| carried-memory items | 38 |
| max visible carried-memory chars | 58,509 |
| answers correct | true |
| all facts visible in final request | true |
| re-read after noise | false |

Many-file sentinel probe:

| metric | value |
| --- | ---: |
| API requests | 31 |
| carried-memory items | 78 |
| facts | 24 |
| answers correct | true |
| all facts visible in final request | true |
| re-read after distractor step | false |

Distance-60 sentinel probe:

| metric | value |
| --- | ---: |
| API requests | 65 |
| carried-memory items | 151 |
| facts | 24 |
| answers correct | true |
| all facts visible in final request | true |
| re-read after distance/noise phase | false |

These runs show that the carried transcript was not merely present. It was
usable. Codex used retained facts correctly without command-level re-reading
after the noise/distance phase.

## Detailed Causal Model

The strongest causal model from the instrumentation is:

```text
User gives task
  -> Codex receives static prompt and task context
  -> Codex decides what information is needed
  -> Codex emits a tool call
  -> harness executes the tool call
  -> raw environment output is produced
  -> output admission/truncation determines retained output text
  -> retained call/output items are inserted into next request input[]
  -> later requests replay those items
  -> model can use the replayed text as semantic memory
```

This answers "where memory comes from" and "why it gets included."

Memory is created because the model performs actions that produce semantic
artifacts. Memory is included because the Codex request assembly path carries
prior transcript items forward. The model controls the supply of memory by
choosing what to inspect. The client/harness controls admission and replay.

## Strong Conclusions

1. Codex semantic memory is observable as carried request transcript.

2. The static context floor is large: about 49k chars before task-specific
   memory begins.

3. Tool schema and base instructions dominate the static floor.

4. Dynamic task memory first appears in request 2 after the first tool cycle.

5. New tool-derived memory appears on request `N+1`, not in the same request
   that requested the tool.

6. File memory is primarily literal tool output retained in later requests.

7. Raw command output is not the same as semantic memory. Only admitted output
   becomes model-visible carried memory.

8. Codex's retrieval strategy affects memory pressure. Narrow search commands
   create smaller memory items than broad file dumps.

9. Long Codex tasks become carried-transcript dominated. The dynamic transcript
   can exceed the static prompt floor by a large margin.

10. In all observed Codex traces, carried items remained visible through the
    final request.

11. Codex retained and used sentinel facts after distractor/noise phases
    without command-level re-reading.

12. The largest observed append-only boundary is 65 requests, 151 carried
    items, 613,873 visible carried-memory chars, and a 666,179-char request
    body.

13. The next unanswered question is the first compaction boundary: the first
    request where a carried item disappears, is summarized, or is replaced.

## Evidence Map

| question | primary evidence |
| --- | --- |
| static prompt floor | empty baseline prompt payload |
| context growth | semantic aggregate and lifecycle timelines |
| file memory | tool-output item tracking |
| N+1 materialization | lifecycle first-seen request indices |
| semantic state machine | turn ledger |
| output admission | 32-chunk pressure run |
| many fact retention | many-file sentinel run |
| long-distance retention | distance-60 sentinel run |
| usable retained memory | sentinel verifier and no-re-read event probe |

## Artifact Map

Core reports:

- `docs/semantic_memory/README.md`
- `docs/semantic_memory/codex_semantic_memory_lifecycle_20260602.md`
- `docs/semantic_memory/codex_semantic_memory_general_model_20260602.md`
- `docs/semantic_memory/codex_sentinel_probe_20260602.md`
- `docs/semantic_memory/codex_sentinel_pressure32_20260602.md`
- `docs/semantic_memory/codex_sentinel_many_files_20260603.md`
- `docs/semantic_memory/codex_sentinel_distance60_20260603.md`

Core analyzers:

- `analysis.semantic_aggregate`
- `analysis.codex_memory_lifecycle`
- `analysis.codex_turn_ledger`
- `analysis.sentinel_fidelity`

Core run artifacts:

- `prompt_payloads.jsonl`
- `api_requests.jsonl`
- `structured_events_observed.jsonl`
- `memory_lifecycle_timeline.jsonl`
- `memory_lifecycle_summary.json`
- `codex_turn_ledger.jsonl`
- `sentinel_fidelity_summary.json`

## Remaining Work

The only major CTO question not fully closed is compaction behavior.

The current answer is that no compaction, swapping, or dropping occurred inside
the observed range. The next experiment should deliberately push past the
distance-60 boundary until one of these events appears:

- an old call ID disappears,
- an old output item disappears,
- a summary-like item replaces detailed transcript,
- a window/session boundary changes,
- the request fails due to context size,
- the model answers correctly despite literal absence,
- the model answers incorrectly after literal absence.

That experiment will turn the current lower bound into an actual compaction
policy measurement.
