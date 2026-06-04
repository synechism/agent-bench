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

Readable static prompt dumps for both agents are available under:

```text
docs/prompt_static_dumps/
```

For Claude Code, the two most useful dumps are:

```text
docs/prompt_static_dumps/claude_code_empty_baseline_main_request_20260602/
docs/prompt_static_dumps/claude_code_expire_reduced_schema_request5_20260602/
```

The first is the full 27-tool main-agent prompt shape. The second is the
17-tool reduced schema shape that appeared in the EXPIRE feature run.

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

## Extra Visible Claude Layers

Claude Code exposes two model-visible layers that are smaller or less prominent
in the observed Codex Responses payloads:

1. **Developer/skills context.** Claude Code includes a system-role message
   layer with skill inventory and harness guidance. In the empty baseline this
   layer was 4,180 chars. At the largest EXPIRE feature request it was 10,611
   chars. This means Claude's model-visible context contains not only the user
   task and tool schemas, but also a visible menu of higher-level skills and
   workflow affordances. The `Skill` tool is also advertised in the tool schema,
   so skills exist both as prompt-visible inventory and as an invocable
   mechanism.
2. **Reasoning/thinking memory.** Claude Code sends visible Anthropic
   `thinking` / `redacted_thinking`-style blocks back in later requests. In the
   EXPIRE feature run, reasoning/thinking memory reached 37,133 chars at the
   largest request. This is smaller than retained file/tool output, but it is
   large enough to be a real memory layer. It acts like self-authored working
   state: plans, intermediate reasoning, and task state that can consume context
   even when no new files are read.

These layers tell us that Claude Code's context window is not just "system
prompt plus tool results." It has a richer orchestration surface:

```text
Claude Code visible context
  = system instructions
  + developer/skills inventory
  + broad tool schema
  + task messages
  + assistant text
  + thinking blocks
  + tool_use records
  + tool_result records
```

The practical implication is that Claude can carry more semantic state than
Codex before considering file outputs at all. Some of that state is useful
guidance, but it is still prompt budget.

## Repeated Tool-Schema Serialization

The repeated tool-schema result deserves to be treated as a first-class
finding. It is not carried task memory, but it is model-visible context that is
resent with each request.

The accounting is:

```text
serialized tool schema chars
  = sum(tool schema chars sent on every request)

unique tool schema chars
  = sum(chars for distinct tool-schema hashes)

repeated tool schema overhead
  = serialized tool schema chars - unique tool schema chars
```

In the fresh Claude EXPIRE feature run:

| schema variant | requests | chars/request | total serialized chars | meaning |
| --- | ---: | ---: | ---: | --- |
| empty/no-tool schema | 3 | 2 | 6 | title/metadata or no-tool request shape |
| reduced tool schema | 11 | 30,932 | 340,252 | 17-tool `deepseek-v4-flash` request shape |
| full tool schema | 49 | 74,427 | 3,646,923 | 27-tool `deepseek-v4-pro` main agent shape |
| **total** | **63** |  | **3,987,181** |  |

Only 105,361 chars were unique schema text across the three variants. The
remaining 3,881,820 chars were repeated serialization of schema text that had
already appeared earlier in the run.

This matters in three separate ways:

1. **Per-request context tax.** The full Claude main-agent request starts with
   a 74,427-char tool-schema floor before file memory, assistant memory, or
   task-specific tool outputs are counted. At request 63 of the EXPIRE run, the
   tool schema alone was 27.3% of the largest request's semantic chars.
2. **Run-level cost multiplier.** A static schema looks like a one-time
   architectural feature when inspecting a single request, but across a long
   run it becomes millions of serialized chars. In the EXPIRE run, repeated
   schema text was larger than all retained task memory at any single turn.
3. **Tool-surface policy affects memory pressure.** The difference between the
   74,427-char full schema and the 30,932-char reduced schema is not task
   memory; it is exposed tool surface. That means restricting or simplifying
   tools can reduce semantic pressure even before changing the model's file
   reading behavior.

The same phenomenon exists for Codex, but the per-request tool schema is much
smaller in the representative setup:

| run | requests | tool schema variants | serialized schema chars | unique schema chars | repeated overhead |
| --- | ---: | --- | ---: | ---: | ---: |
| Claude GETEX QA | 17 | empty + full | 1,190,834 | 74,429 | 1,116,405 |
| Claude GETEX tests | 28 | empty + reduced + full | 1,307,811 | 105,361 | 1,202,450 |
| Claude EXPIRE feature | 63 | empty + reduced + full | 3,987,181 | 105,361 | 3,881,820 |
| Codex GETEX tests | 112 | 12-tool schema | 2,511,376 | 22,423 | 2,488,953 |
| Codex EXPIRE feature | 57 | 12-tool schema | 1,278,111 | 22,423 | 1,255,688 |

Both agents repeatedly serialize static tool schemas in the observed request
path. Codex did this too: in the EXPIRE feature run, the same 22,423-char
12-tool schema appeared on all 57 requests.

The difference is the size and shape of the repeated object:

```text
Codex repeats a compact execution/editing tool surface.
Claude repeats a broader behavioral/orchestration surface.
```

Claude's main schema is about 3.3x the size of the Codex schema in this batch.
That is why Claude looks so much more redundant at run level. It is not more
repetitive in principle; it is heavier per request.

The contents explain the size difference. Claude's full `tools[]` schema is not
just short function signatures. It contains long descriptions and JSON schemas
for 27 tools:

```text
Agent
AskUserQuestion
Bash
CronCreate / CronDelete / CronList
Edit
EnterPlanMode / ExitPlanMode
EnterWorktree / ExitWorktree
Glob
Grep
NotebookEdit
Read
ScheduleWakeup
Skill
TaskCreate / TaskGet / TaskList / TaskOutput / TaskStop / TaskUpdate
WebFetch / WebSearch
Workflow
Write
```

Several of these are not direct code-reading or code-editing tools. They are
workflow and orchestration capabilities. The largest individual definitions
include `Workflow`, `AskUserQuestion`, `EnterPlanMode`, `CronCreate`, `Agent`,
`ScheduleWakeup`, `TaskUpdate`, `Grep`, `EnterWorktree`, `TaskCreate`, and
`Bash`.

This means the repeated Claude schema is also repeated behavioral prompting.
Examples from the schema:

- `Workflow` explains when multi-agent orchestration is allowed, how to
  structure fan-out, and how to handle ultracode-style work.
- `Agent` describes subagent types and when delegation is appropriate.
- `Bash` tells the model to prefer dedicated file/search tools over shell
  commands like `grep`, `cat`, `sed`, and `awk`.
- `Read` describes line limits, line-numbered output, image/PDF/notebook
  handling, and when not to re-read files.
- `Skill` explains slash-command/skill invocation rules.

So the repeated schema is capability surface plus policy surface. Codex also
has policy in tool descriptions, but in these runs its schema was smaller and
less orchestration-heavy.

This also explains why repeated schema serialization felt hidden in the earlier
summary. It does not show up as "memory growth" inside a single request because
the schema is static. But it is still repeatedly present in the context window,
repeatedly serialized over the API boundary, and repeatedly competing with
dynamic memory for prompt budget.

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

1. Repeated tool-schema serialization is a major hidden cost. In the fresh
   Claude EXPIRE feature run, serialized tool schema totaled about 3.99M chars
   across requests, with about 3.88M chars of repeated schema text.
2. Claude Code's fixed semantic floor is much larger, primarily because of its
   tool schema. Its main request advertises a large tool surface even for an
   empty task.
3. Codex uses more turns on these runs, while Claude Code tends to send heavier
   requests.
4. Both agents retain file knowledge mainly by replaying tool outputs into
   future requests.
5. Claude Code exposes additional visible layers that are smaller or absent in
   the Codex Responses payloads: skill inventory/developer context and
   reasoning/thinking blocks.

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
