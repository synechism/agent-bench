# Codex Semantic Memory Consumption Lifecycle - 2026-06-02

This report focuses only on Codex. It goes one level below the aggregate
semantic-memory summaries by tracking when each carried transcript item first
enters the next model request.

For the broader task-agnostic model and next experiment matrix, see
`codex_semantic_memory_general_model_20260602.md`.

## Core Finding

In the observed Codex runs, semantic memory consumption is built by transcript
replay. The model does not emit a separate visible instruction saying which
memories to retain. Instead, when the model asks for a tool call, the harness
executes it and appends both the `function_call` record and the
`function_call_output` record to the `input` array of the next
`/v1/responses` request. Those records then remain visible on later requests
until compaction or dropping occurs.

## Run Summary

| run | requests | first memory request | carried items | retained to final | dropped/compacted | max visible memory chars | largest addition chars |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `20260601T202331_codex_empty_baseline_empty_task_nocap_rep0` | 1 | None | 0 | 0 | False | 0 | 0 |
| `20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0` | 23 | 2 | 55 | 55 | False | 32,371 | 4,520 |
| `20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0` | 112 | 2 | 257 | 257 | False | 112,107 | 5,174 |
| `20260601T202331_codex_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0` | 57 | 2 | 149 | 149 | False | 105,304 | 15,020 |

## What Answers The User's Questions

- **When does Codex include new memories?** In these traces, the first carried memory appears on request 2. More generally, new tool-call and tool-output records first become model-visible on request `N + 1`, after the model requested the tool during request `N`'s response and the harness executed it.
- **Why does it include them?** The visible evidence points to harness transcript assembly, not a separate model-side retention decision. Codex influences memory indirectly by choosing which tools to call and how much output to produce.
- **When does it add to the context window?** The addition happens before the next model API request is sent, as new `input` array items. Request-body growth tracks the newly replayed call/output chars plus JSON serialization overhead.
- **What is the semantic unit of memory?** For these Codex payloads, the practical unit is a Responses API item: `function_call`/`custom_tool_call` for the action the model chose, `function_call_output`/`custom_tool_call_output` for observed terminal/file/test/patch output, and occasional assistant messages. File knowledge is just text inside those output items.
- **What does "want" mean here?** The traces do not expose an internal preference signal saying "retain this memory." The visible causal chain is: the model wants information or an edit, emits a tool call, receives output, and the client carries that transcript forward.

## Strongest Example

The highest-memory run was `20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0`.

- First visible in request 10 (generated after request 9): 4,686 chars; sed -n '340,450p' ./src/t_string.c
- First visible in request 11 (generated after request 10): 3,259 chars; sed -n '570,660p' ./tests/unit/expire.tcl
- First visible in request 12 (generated after request 11): 2,743 chars; sed -n '250,310p' ./tests/unit/pubsub.tcl
- First visible in request 90 (generated after request 89): 2,725 chars; sed -n '550,620p' ./tests/support/server.tcl
- First visible in request 73 (generated after request 72): 2,553 chars; sed -n '470,530p' ./tests/support/server.tcl
- First visible in request 7 (generated after request 6): 2,515 chars; grep -n "EXPIRED\|expired\|DEL\|delete\|__keyevent\|notify\|notify-keyspace\|keyspace" ./tests/unit/pubsub.tcl | head -30
- First visible in request 36 (generated after request 35): 2,505 chars; sed -n '40,95p' ./src/notify.c
- First visible in request 17 (generated after request 16): 2,279 chars; *** Begin Patch *** Update File: ./tests/unit/expire.tcl @@ test {GETEX propagate as to replica as PERSIST, DEL, or nothing} test {GETEX propagate as to replica as PERSIST, DEL, or nothing} { # In the above

## Interpretation

This lets us separate two decisions that are easy to conflate:

- The model decides to inspect something by issuing a tool call.
- The Codex client/harness decides to carry the resulting transcript forward by sending prior call/output items in the next request.

So the observed semantic memory stack is layered as static prompt/tool schema
plus an append-only carried transcript. In these representative Codex runs,
no dropped carried-memory items were observed before the final request, so we
did not catch a compaction boundary. To study compaction directly, the next
experiment should force longer runs with intentionally large tool outputs and
then look for the first request where earlier call IDs disappear or are
replaced by a summary-like item.
