# Semantic Memory Report

This directory contains the semantic-memory investigation artifacts. The core
question is: what semantic material is actually visible to the agent model over
time, where does it come from, and how does it enter or leave the context
window?

The current answer for Codex is that semantic memory is mostly a structured
transcript pipeline:

```text
static prompt/tool envelope
  + task/environment context
  + admitted tool calls and tool outputs
  + occasional assistant/reasoning items
  -> next model request input
```

We have measured literal request payloads. We have not measured provider-hidden
state or neural/internal memory.

## 1. Static Context Floor

The first experiment measured the empty-task baseline and representative Codex
runs with API prompt capture enabled. This gave us the fixed request floor
before any tool interaction.

Codex empty-baseline static floor:

| layer | chars |
| --- | ---: |
| tool schema | 22,423 |
| base instructions | 21,437 |
| developer/skills/context | 4,997 |
| task/environment | 351 |
| total static floor | 49,208 |

This means an empty Codex run already sends roughly 49k chars before any useful
task memory appears. The largest fixed components are the advertised tool
schema and the base instructions. Skills/developer context are smaller but
still material.

The key interpretation: when we talk about "memory pressure," the model does
not start from zero. It starts from a large static envelope that is reserialized
with each request.

## 2. Growth Over Representative Tasks

The next experiment ran Codex on an empty task and three Redis tasks:

```text
runs/20260601T202331_codex_empty_baseline_empty_task_nocap_rep0
runs/20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0
runs/20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0
runs/20260601T202331_codex_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0
```

At max request size:

| task | requests | max approx tokens | static chars | carried chars | file/tool chars |
| --- | ---: | ---: | ---: | ---: | ---: |
| empty baseline | 1 | 12,302 | 49,208 | 0 | 0 |
| Redis GETEX QA | 23 | 20,456 | 49,451 | 32,371 | 28,478 |
| Redis GETEX tests | 112 | 40,398 | 49,482 | 112,107 | 82,403 |
| Redis EXPIRE feature | 57 | 38,714 | 49,551 | 105,304 | 68,386 |

The important shift is that long tasks become carried-history dominated. In the
GETEX tests run, carried memory reached 112,107 chars. In the EXPIRE feature
run, carried memory reached 105,304 chars.

Most of that carried history was file/tool output: source snippets, test files,
grep results, patch results, build output, and test logs. So "file memory" is
not a hidden cache in the observed request path. It is usually literal text
from tool outputs replayed into later requests.

## 3. Lifecycle: When New Memory Enters

We then added `analysis.codex_memory_lifecycle` to track item identity across
requests. This showed the timing rule:

```text
model emits tool call during request N response
tool runs in the environment
tool call + admitted output first appear in request N+1 input
```

In the representative Codex runs:

| run | requests | first memory request | carried items | retained to final | dropped/compacted |
| --- | ---: | ---: | ---: | ---: | --- |
| empty baseline | 1 | none | 0 | 0 | false |
| Redis GETEX QA | 23 | 2 | 55 | 55 | false |
| Redis GETEX tests | 112 | 2 | 257 | 257 | false |
| Redis EXPIRE feature | 57 | 2 | 149 | 149 | false |

We did not observe any carried item disappearing before the final request in
these runs. That means these traces show accumulation, not compaction.

The semantic unit of carried memory is a Responses API item:

- `function_call` for shell/tool calls,
- `function_call_output` for command/file/test output,
- `custom_tool_call` / `custom_tool_call_output` for patch operations,
- occasional assistant messages,
- in some runs, visible reasoning/summary-like items.

The model influences memory indirectly by deciding what to inspect or edit. The
client/tool layer decides what gets carried into the next request.

## 4. Turn Ledger: The State Machine View

We then added `analysis.codex_turn_ledger` to join request payloads with Codex
structured events. This reframed memory consumption as a state transition:

```text
request N visible context
  -> observed agent/tool events after request N
  -> new material first visible in request N+1
```

This gives the full-picture row we want for every turn:

| step | question | evidence |
| --- | --- | --- |
| request input | what did the model see? | `prompt_payloads.jsonl` |
| model action | what did it choose to do? | tool-call items, structured events |
| environment result | what semantic material was produced? | tool outputs, logs, patches |
| next context | what became model-visible? | new request `input` items |
| retention | did it stay visible? | item identities across requests |
| use | did the model rely on it? | final edits, verifier, behavior |

This is the general model we should use going forward. A single char count is
not enough; we need to track creation, admission, materialization, retention,
transformation, and later use.

## 5. Sentinel Fidelity Probe

To avoid overfitting to Redis, we added a task-agnostic built-in codebase:
`semantic_memory_sentinel`.

It contains:

- five sentinel files with canonical facts,
- distractor files with decoys,
- a noise generator,
- a verifier for `answers.json`.

The first sentinel run used 8 chunks of noise:

```text
runs/20260602T142734_codex_semantic_memory_sentinel_semantic_memory_sentinel_probe_nocap_rep0
```

Results:

| metric | value |
| --- | ---: |
| API requests | 7 |
| carried-memory items | 38 |
| max visible carried-memory chars | 58,509 |
| largest single materialization | 42,619 |
| answers correct | true |
| all facts visible in final request | true |
| sentinel re-read after noise | false |
| dropped/compacted items observed | false |

Interpretation: Codex read the facts as tool outputs, carried them literally
through the noise phase, did not command-level re-read the sentinel files after
the noise step, and used the facts correctly.

This gave us a cleaner general statement than the Redis tasks: retained facts
can remain literally visible and usable across intervening distractor output.

## 6. Pressure Ramp: Raw Output Is Not Semantic Memory

We then ran a 32-chunk pressure variant:

```text
runs/20260602T145959_codex_semantic_memory_sentinel_semantic_memory_sentinel_pressure_32_nocap_rep0
```

Comparison:

| metric | 8 chunks | 32 chunks |
| --- | ---: | ---: |
| API requests | 7 | 6 |
| carried-memory items | 38 | 30 |
| max visible carried-memory chars | 58,509 | 27,658 |
| largest single materialization | 42,619 | 17,841 |
| retained noise output chars | 40,154 | 16,156 |
| answers correct | true | true |
| all facts visible in final request | true | true |
| sentinel re-read after noise | false | false |
| dropped/compacted items observed | false | false |

This was the first surprising pressure result. More raw output did not produce
more semantic memory. Codex/tooling bounded the noisy command output with:

```text
max_output_tokens: 4000
```

The environment reported about 53,880 original output tokens, but only about
16.2k chars were retained in the model-visible transcript.

This refines the model:

```text
environment output produced
  -> tool-output admission/truncation policy
  -> carried transcript item
  -> next request context
```

So raw command output, captured tool output, model-visible carried output, and
later usable memory are distinct things.

## 7. Many-File Probe: Output Shape Matters

The next probe changed the pressure shape from one large command to many
separate fact observations:

```text
runs/20260603T155817_codex_semantic_memory_sentinel_semantic_memory_sentinel_many_files_nocap_rep0
```

It used 24 separate files under `many_facts/`, with one canonical
`MANY_SENTINEL key=value` fact per file. The verifier checked hashes rather
than exposing literal expected values.

Results:

| metric | value |
| --- | ---: |
| API requests | 31 |
| carried-memory items | 78 |
| carried items retained to final | 78 |
| max visible carried-memory chars | 77,439 |
| max request body chars | 118,559 |
| answers correct | true |
| all 24 facts visible in final request | true |
| re-read after distractor step | false |
| dropped/compacted items observed | false |

This run added two new observations:

1. Codex adapted its retrieval strategy. It read the first fact file more
   broadly, then switched to narrow `rg --line-number '^MANY_SENTINEL ' ...`
   commands for later files. That reduced context growth.
2. Many separate facts across many turns were still retained literally through
   the final request. We still did not observe compaction or dropping.

The many-file run is stronger than the earlier sentinel runs because facts were
spread across 24 files and 31 API requests.

## Current Interpretation

Our current Codex model is:

1. Codex starts with a large static floor, roughly 49k chars in the empty
   baseline.
2. The static floor is dominated by tool schema and base instructions.
3. New carried memory first appears on request 2.
4. Tool calls and admitted outputs first become visible on request `N + 1`.
5. Longer tasks become dominated by carried transcript rather than static
   prompt.
6. File knowledge is mostly literal retained tool output.
7. Patch attempts and assistant messages can also become carried memory.
8. In all observed Codex runs so far, carried memory was retained through the
   final request; we have not observed dropping or compaction.
9. Raw environment output is filtered by tool-output admission limits before it
   becomes semantic memory.
10. Sentinel probes show retained facts can remain both visible and usable
    through distractor output.
11. Codex can reduce semantic pressure by choosing narrower retrieval commands,
    not only by relying on tool-output truncation.

The most accurate short version:

```text
Codex semantic memory is a carried structured transcript. The model chooses
what to inspect; the tool/client layer controls how much result text is admitted;
the next request materializes admitted items; later behavior depends on whether
those items remain visible, are summarized, are dropped, or are re-derived.
```

## What We Still Do Not Know

We have not yet found the compaction boundary. We still need to identify:

- when call IDs disappear from later requests,
- whether disappeared items are replaced by summaries,
- whether those summaries are model-authored or client-authored,
- whether facts beyond output truncation boundaries are recoverable,
- whether many medium-sized outputs stress memory differently from one huge
  output,
- whether retained facts are ignored or corrupted under heavier distraction.

The next best experiment is not simply bigger output. It should vary output
shape:

- many separate medium-sized tool outputs,
- sentinel facts near the beginning, middle, and end of outputs,
- decoys sharing prefixes with real facts,
- delayed use-after-distance checks,
- repeated turns until either item dropping or summary replacement appears.

## Artifact Index

- `instrumentation_plan_20260601.md`: what we measure and how prompt/context
  capture works.
- `codex_semantic_memory_analysis_20260601.md`: early Codex interpretation.
- `codex_representative_aggregate_20260601.md`: compact aggregate table and
  largest retained tool outputs.
- `codex_representative_aggregate_20260601.json`: machine-readable aggregate.
- `codex_semantic_memory_lifecycle_20260602.md`: Codex lifecycle analysis.
- `codex_semantic_memory_general_model_20260602.md`: state-machine model and
  experiment matrix.
- `codex_sentinel_probe_20260602.md`: first sentinel/fidelity probe.
- `codex_sentinel_pressure32_20260602.md`: pressure-ramp follow-up.
- `codex_sentinel_many_files_20260603.md`: many-file output-shape probe.
- `claude_code_semantic_memory_analysis_20260602.md`: Claude Code analysis.
- `claude_representative_aggregate_20260602.md`: Claude Code aggregate.
- `claude_representative_aggregate_20260602.json`: machine-readable Claude
  aggregate.
- `codex_claude_semantic_memory_comparison_20260602.md`: Codex/Claude
  comparison.

## Commands

Future semantic aggregate outputs:

```bash
python -m analysis.semantic_aggregate \
  --output-prefix docs/semantic_memory/semantic_context_aggregate
```

Codex lifecycle, turn-ledger, and sentinel scoring:

```bash
python -m analysis.codex_memory_lifecycle runs/<codex_run_id>
python -m analysis.codex_turn_ledger runs/<codex_run_id>
python -m analysis.sentinel_fidelity runs/<codex_sentinel_run_id>
```

Claude Trace-compatible UI path from observer logs:

```bash
HARNESS_TRACE_EXPORT=1 python -m analysis.summarize runs/<run_id>
python -m analysis.claude_trace_export runs/<run_id> --html
```

The generated `.claude-trace/observer_api_trace.jsonl` reuses only sanitized
captures already present in `api_requests.jsonl`; it does not add a new capture
surface.
