# Semantic Memory Layer Comparison - Codex And Claude Code - 2026-06-02

This report combines the Codex representative semantic-memory summary with the
fresh Claude Code observer-export run. The goal is to make the model-visible
memory layers explicit: what is static prompt/tooling, what is carried
conversation history, and what is retained file/tool output.

## Source Runs

Codex representative batch:

```text
runs/20260601T202331_codex_empty_baseline_empty_task_nocap_rep0
runs/20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0
runs/20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0
runs/20260601T202331_codex_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0
```

Fresh Claude Code trace-export batch:

```text
runs/20260602T131620_claude_code_empty_baseline_empty_task_nocap_rep0
runs/20260602T131620_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0
runs/20260602T131620_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0
runs/20260602T131620_claude_code_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0
```

The Claude Code batch also produced Claude Trace-compatible UI artifacts from
our observer logs:

```text
runs/20260602T131620_claude_code_*/.claude-trace/observer_api_trace.jsonl
runs/20260602T131620_claude_code_*/.claude-trace/observer_api_trace.html
```

These are observer-export artifacts, not live `CLAUDE_TRACE=1` interception.
Live Claude Trace wrapping remains blocked for current native Claude Code, but
the exported JSONL/HTML has one pair per observed API request/response and all
counts matched.

## Layer Model

The model-visible context can be understood as:

```text
static prompt
  = base/system instructions
  + developer/skills/project context
  + advertised tool schemas
  + task framing

carried memory
  = assistant text
  + visible reasoning/thinking blocks
  + tool call records
  + tool/file output records
```

The most important empirical finding is that "memory of files" is not a hidden
file cache in the observed request path. It is usually literal retained tool
output: `Read`, `Grep`, `Bash`, `sed`, test output, source snippets, and diffs
replayed into later model requests.

## Codex Summary

Codex has a lower static floor and more API turns in this representative batch.

| task | requests | max approx toks | static chars | carried chars | file/tool chars |
| --- | ---: | ---: | ---: | ---: | ---: |
| empty baseline | 1 | 12,302 | 49,208 | 0 | 0 |
| Redis GETEX QA | 23 | 20,456 | 49,451 | 32,371 | 28,478 |
| Redis GETEX tests | 112 | 40,398 | 49,482 | 112,107 | 82,403 |
| Redis EXPIRE feature | 57 | 38,714 | 49,551 | 105,304 | 68,386 |

Codex empty-baseline static floor:

| static layer | chars |
| --- | ---: |
| tool schema | 22,423 |
| base instructions | 21,437 |
| developer context | 4,997 |
| environment/task | 351 |

At the largest request, carried-memory shares were:

| task | static share | carried share | file/tool share of carried |
| --- | ---: | ---: | ---: |
| empty baseline | 100.0% | 0.0% | 0.0% |
| Redis GETEX QA | 60.4% | 39.6% | 88.0% |
| Redis GETEX tests | 30.6% | 69.4% | 73.5% |
| Redis EXPIRE feature | 32.0% | 68.0% | 64.9% |

Interpretation: Codex starts around 49k chars of fixed prompt/tooling. Longer
tasks become carried-history dominated, and most carried history is retained
tool/file output.

## Claude Code Summary

Claude Code has a larger fixed floor and heavier individual requests. The fresh
trace-export batch completed 4/4 cells with no API errors or trace-count
mismatches.

| task | requests | max approx toks | static chars | carried chars | file/tool chars |
| --- | ---: | ---: | ---: | ---: | ---: |
| empty baseline | 2 | 21,432 | 85,088 | 0 | 0 |
| Redis GETEX QA | 17 | 36,007 | 87,561 | 49,252 | 27,686 |
| Redis GETEX tests | 28 | 73,220 | 41,149 | 232,857 | 213,689 |
| Redis EXPIRE feature | 63 | 72,416 | 92,254 | 177,182 | 87,314 |

Claude Code empty-baseline static floor:

| static layer | chars |
| --- | ---: |
| tool schema | 74,427 |
| system instructions | 6,063 |
| developer/skills context | 4,180 |
| user/task context | 418 |

At the largest request, carried-memory shares were:

| task | static share | carried share | file/tool share of carried |
| --- | ---: | ---: | ---: |
| empty baseline | 99.3% | 0.0% | 0.0% |
| Redis GETEX QA | 60.8% | 34.2% | 56.2% |
| Redis GETEX tests | 14.0% | 79.5% | 91.8% |
| Redis EXPIRE feature | 31.8% | 61.2% | 49.3% |

The GETEX tests run is the clearest example of tool-output-dominated memory:
the largest request was about 292.9k chars, with about 213.7k chars of
tool/file output.

## Claude Code Layer Breakdown At Largest Requests

| layer | GETEX QA | GETEX tests | EXPIRE feature |
| --- | ---: | ---: | ---: |
| system instructions | 6,515 | 3,477 | 6,488 |
| tool schema | 74,427 | 30,932 | 74,427 |
| developer context | 5,988 | 5,831 | 10,611 |
| user/task context | 631 | 909 | 728 |
| assistant text | 611 | 916 | 1,816 |
| tool call memory | 4,308 | 11,122 | 50,919 |
| tool output memory | 27,686 | 213,689 | 87,314 |
| reasoning/thinking memory | 16,647 | 7,130 | 37,133 |

The EXPIRE feature task shows that Claude Code also keeps substantial visible
reasoning/tool-call memory: about 37.1k chars of reasoning/thinking blocks and
50.9k chars of tool-call records at the largest request.

## Cross-Agent Findings

| metric | Codex | Claude Code |
| --- | ---: | ---: |
| empty static floor | 49,208 chars | 85,088 chars |
| empty approx tokens | 12,302 | 21,432 |
| empty tool schema | 22,423 chars | 74,427 chars |
| GETEX QA max approx tokens | 20,456 | 36,007 |
| GETEX tests max approx tokens | 40,398 | 73,220 |
| EXPIRE feature max approx tokens | 38,714 | 72,416 |

Key conclusions:

1. Claude Code's fixed semantic floor is much larger, primarily because of its
   tool schema. Its main request advertises a large tool surface even for an
   empty task.
2. Codex uses more turns on these runs, while Claude Code tends to send heavier
   requests.
3. Both agents retain file knowledge mainly by replaying tool outputs into
   future requests.
4. Claude Code exposes additional visible layers that are smaller or absent in
   the Codex Responses payloads: skill inventory/developer context and
   reasoning/thinking blocks.
5. Repeated tool-schema serialization is a major hidden cost. In the fresh
   Claude EXPIRE feature run, serialized tool schema totaled about 3.99M chars
   across requests, with about 3.88M chars repeated overhead.

## What We Can And Cannot Claim

We can claim:

- Exactly what strings and structured blocks were sent in model API requests.
- How much of the request body belonged to static prompt/tooling versus carried
  memory.
- Which retained tool outputs dominated the context window.
- Whether observer-exported trace pairs matched API request counts.

We cannot claim:

- The model's internal neural memory state.
- Provider-side hidden cache behavior beyond visible request fields.
- That live Claude Trace can wrap current native Claude Code. It still cannot;
  the usable trace UI path is observer-exported JSONL/HTML.

