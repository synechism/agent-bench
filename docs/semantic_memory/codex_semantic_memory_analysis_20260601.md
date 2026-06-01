# Semantic Memory Consumption Analysis - Codex Representative Batch - 2026-06-01

This report interprets the Codex semantic-context experiment, focusing on what
is actually inside the model context window and how that context grows over
time.

Source aggregate:

```text
docs/semantic_memory/codex_representative_aggregate_20260601.md
docs/semantic_memory/codex_representative_aggregate_20260601.json
docs/semantic_memory/codex_representative_aggregate_20260601.csv
```

Fresh runs:

```text
runs/20260601T202331_codex_empty_baseline_empty_task_nocap_rep0
runs/20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0
runs/20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0
runs/20260601T202331_codex_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0
```

## Executive Summary

Codex semantic memory has two layers with very different behavior:

1. A large fixed prompt floor of roughly 49k chars per request.
2. A growing carried-history layer dominated by retained tool outputs and file
   snippets.

The fixed layer is present even for the empty task. It consists mostly of base
instructions, developer context, task framing, and model-visible tool schemas.

The growing layer is not mainly assistant prose or hidden reasoning. In the
representative Redis runs, 65-88% of carried memory at the largest request came
from tool outputs, mostly `sed`, `rg`, test-file snippets, source-code snippets,
and build/test command output.

No compaction occurred in any run. All four runs stayed in one context window.

## Context Layers

At each model request, Codex sends a Responses API payload whose semantic memory
can be viewed as:

```text
base instructions
+ tool schema
+ developer/context instructions
+ user task
+ assistant messages
+ tool calls
+ tool outputs / file snippets
+ JSON envelope and metadata
```

For these experiments, the important distinction is:

```text
static prompt = base instructions + tool schema + developer context + task framing
carried memory = assistant messages + tool calls + tool outputs
file memory = tool outputs, especially command/file-read results
```

## The 49k Static Floor

The empty baseline lets us inspect the fixed prompt floor without any tool
history. The 49,208 chars are not all system prompt.

Breakdown:

| layer | chars | share |
| --- | ---: | ---: |
| tool schema | 22,423 | 45.6% |
| base instructions | 21,437 | 43.6% |
| developer context | 4,997 | 10.2% |
| environment + task | 351 | 0.7% |

Interpretation:

- The largest single layer is the model-visible tool schema, not the base
  prompt.
- Base instructions are still very large at 21.4k chars.
- Developer context is mostly skill/permission instructions.
- The actual benchmark task text is tiny by comparison.

### Base Instructions Breakdown

The base instruction string is 21,437 chars. Major sections:

| section | chars |
| --- | ---: |
| Design instructions | 5,661 |
| Formatting rules | 2,242 |
| Editing constraints | 2,006 |
| Final answer instructions | 1,794 |
| Personality | 1,733 |
| Intermediary updates | 1,662 |
| Build with empathy | 1,339 |
| Working with the user | 1,319 |
| Engineering judgment | 1,053 |
| Autonomy and persistence | 855 |
| General | 806 |
| Special user requests | 704 |
| Frontend guidance heading | 108 |
| Preamble | 155 |

This base prompt is broad because it includes general coding-agent behavior,
frontend guidance, editing rules, collaboration policy, formatting rules, and
final-response policy. For backend-only Redis tasks, the frontend/design
sections are semantically unused but still occupy context.

### Developer Context Breakdown

The developer-context input item is 4,997 chars:

| item | chars |
| --- | ---: |
| permissions instructions | 362 |
| skills instructions | 4,598 |

The skills block lists available skills and the rules for when/how to load
them. In this Redis batch it mostly acts as static overhead; the tasks did not
need any of those skills.

### Tool Schema Breakdown

The tool schema block is 22,423 chars and advertises 12 tools:

| tool | schema chars |
| --- | ---: |
| multi_agent_v1 | 11,946 |
| mcp__deepwiki | 2,819 |
| exec_command | 2,189 |
| request_user_input | 1,425 |
| apply_patch | 850 |
| list_mcp_resource_templates | 757 |
| write_stdin | 709 |
| list_mcp_resources | 669 |
| update_plan | 664 |
| read_mcp_resource | 552 |
| view_image | 390 |
| web_search | 51 |

The main conclusion is that the tool menu is expensive. `multi_agent_v1` alone
is larger than the entire developer context and more than half of all tool
schema chars. For Redis tasks, many advertised tools are never used, but their
schemas are still present in every request.

## Results

| task | API requests | tool calls | max semantic approx tokens | static chars | carried chars | file/tool-output chars |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| empty baseline | 1 | 0 | 12,302 | 49,208 | 0 | 0 |
| Redis QA | 23 | 27 | 20,456 | 49,451 | 32,371 | 28,478 |
| Redis test-writing | 112 | 123 | 40,398 | 49,482 | 112,107 | 82,403 |
| Redis feature | 57 | 65 | 38,714 | 49,551 | 105,304 | 68,386 |

### Percentages At Largest Request

| task | static share | carried-memory share | file/tool-output share of carried memory |
| --- | ---: | ---: | ---: |
| empty baseline | 100.0% | 0.0% | 0.0% |
| Redis QA | 60.4% | 39.6% | 88.0% |
| Redis test-writing | 30.6% | 69.4% | 73.5% |
| Redis feature | 32.0% | 68.0% | 64.9% |

Interpretation:

- Short investigation tasks are still dominated by the static prompt floor.
- Longer test/feature tasks become dominated by carried memory.
- The carried memory is mostly retained file/tool output, not assistant prose.

## Growth Pattern

The static prompt is nearly constant per request:

```text
baseline: 49,208 chars
Redis QA: 49,451 chars
Redis tests: 49,482 chars
Redis feature: 49,551 chars
```

What changes is carried memory:

```text
Redis QA:
  request 1: 0 carried chars
  request 10: 16,293 carried chars
  request 20: 29,199 carried chars
  request 23: 32,371 carried chars

Redis test-writing:
  request 1: 0 carried chars
  request 50: 66,241 carried chars
  request 100: 103,975 carried chars
  request 112: 112,107 carried chars

Redis feature:
  request 1: 0 carried chars
  request 20: 49,658 carried chars
  request 40: 90,921 carried chars
  request 57: 105,304 carried chars
```

The growth is roughly linear in the number of turns because Codex keeps prior
tool calls and outputs in the prompt. It does not summarize or compact during
these runs.

Approximate carried-memory growth rate:

```text
Redis QA: ~1,471 chars per request after the first
Redis test-writing: ~1,010 chars per request after the first
Redis feature: ~1,880 chars per request after the first
```

The feature task has the highest growth rate because it mixes exploration,
editing, build output, and validation output. The test-writing task has the
largest total carried memory because it loops for many more requests.

## What "Memory Of Files" Means Here

For Codex, memory of explored files is concrete and inspectable. It appears as
`function_call_output` items in the next model requests.

Examples from the largest retained outputs:

```text
Redis QA:
- sed -n '1713,1810p' src/db.c
- sed -n '342,440p' src/t_string.c
- sed -n '44,100p' src/db.c
- sed -n '600,660p' src/expire.c

Redis test-writing:
- sed -n '340,450p' ./src/t_string.c
- sed -n '570,660p' ./tests/unit/expire.tcl
- sed -n '250,310p' ./tests/unit/pubsub.tcl
- sed -n '550,620p' ./tests/support/server.tcl

Redis feature:
- sed -n '250,604p' tests/unit/expire.tcl
- sed -n '80,250p' tests/unit/expire.tcl
- make distclean && make ... | tail -20
- sed -n '460,540p' src/expire.c
- sed -n '496,580p' src/expire.c
```

This is the key semantic-memory conclusion: Codex retains file knowledge by
retaining command outputs. The model does not have a separate explicit file
cache in the observed prompt path; it has a replayed transcript of what tools
showed it.

## Repeated Static Overhead

The fixed prompt floor is not only large once; it is resent on every model
request.

For the test-writing task:

```text
base instructions serialized across run: 2,400,944 chars
tool schema serialized across run: 2,511,376 chars
unique base instructions: 21,437 chars
unique tool schema: 22,423 chars
```

For the feature task:

```text
base instructions serialized across run: 1,221,909 chars
tool schema serialized across run: 1,278,111 chars
unique base instructions: 21,437 chars
unique tool schema: 22,423 chars
```

Interpretation:

- A single request has a ~49k char floor.
- Long-running tasks pay that floor repeatedly.
- Prompt caching may reduce provider-side compute cost if supported, but the
  model request still semantically contains the same static material each turn.
- This makes number of turns a direct multiplier on static prompt overhead.

## Process Memory Versus Semantic Memory

The feature task shows why semantic memory must be separated from process
memory.

```text
Redis feature full process-tree peak: 520.0 MB
Redis feature agent-isolated peak: 165.0 MB
```

The full peak was mostly Redis build/compiler processes. After excluding
build/test/package spans, the agent-isolated peak is close to the other Codex
runs.

Semantic memory tells a different story:

```text
Redis feature max semantic request: ~38.7k rough tokens
Redis test-writing max semantic request: ~40.4k rough tokens
```

The feature task looked biggest in OS memory because it compiled Redis. The
test-writing task looked slightly bigger semantically because it accumulated a
longer prompt transcript.

## Compaction And Context Swapping

No compaction or context-window swap occurred:

```text
empty baseline: 1 window, request kind turn
Redis QA: 1 window, request kind turn
Redis test-writing: 1 window, request kind turn
Redis feature: 1 window, request kind turn
```

This means the current observed Codex behavior is plain transcript growth, not
summary-based memory management.

Important implication: for these tasks, semantic memory is easy to audit. We do
not yet need to reason about lossy summaries or swapped context layers. For
larger Linux tasks, or if we force a smaller context window, compaction should
become the next thing to investigate.

## Behavioral Conclusions

1. Codex is transcript-memory oriented.

   It carries forward the tool transcript: calls, arguments, and outputs. File
   memory is the retained transcript of shell/file observations.

2. The static prompt/tooling layer is large enough to matter.

   Before any useful task-specific exploration, the model receives roughly 12k
   rough tokens. This includes the full tool menu and instruction stack.

3. Tool-output retention is the main growing semantic cost.

   In all non-baseline runs, file/tool output is the largest component of
   carried memory. Assistant messages are small.

4. Test-writing tasks can be worse than feature tasks semantically.

   Test-writing required many small exploratory steps and accumulated the
   largest context. Feature implementation used more process memory due to
   compilation, but not more semantic memory than the test-writing loop.

5. Shell-oriented harnesses make semantic memory highly inspectable.

   Since Codex primarily learns files through shell outputs, we can identify
   exactly which commands caused memory growth and which file snippets remain in
   context.

6. Build/test commands must be split into two notions of cost.

   Build/test processes dominate OS memory, but their semantic contribution is
   only the captured command output that gets fed back to the model.

## Hypotheses For Cross-Agent Comparison

These are hypotheses to test next against Claude Code and Pi:

1. Claude Code may have a larger or different fixed floor if skills, agents, or
   system prompt sections are loaded eagerly.

2. Claude Code may retain richer structured tool state than Codex, or it may
   summarize more aggressively depending on the harness.

3. Pi should have a smaller fixed floor and likely fewer retained tool artifacts
   if it is lazier and uses fewer tools.

4. If all three agents use the same model route, differences in semantic memory
   should mostly come from harness prompt design, tool schema breadth, and
   history-retention policy.

## Recommended Next Experiments

1. Run the same representative batch for Claude Code and Pi.

   Keep tasks identical so we can compare fixed prompt floor, tool schema size,
   carried memory, and file/tool-output retention.

2. Force a smaller context limit for Codex.

   This should trigger compaction and let us inspect what Codex chooses to keep
   or summarize.

3. Add a tool-output retention report.

   We already know largest retained outputs. The next step is to classify them:
   source file reads, test-file reads, search output, build output, failing test
   output, successful test output.

4. Separate "semantic usefulness" from "semantic volume."

   Some large snippets are genuinely useful. Others are duplicated, too broad,
   or only retained because the agent read a large region. We need a later
   metric for whether retained memory was later referenced or edited.

## Bottom Line

For Codex on this representative Redis batch, semantic memory consumption is
not mysterious. It is mostly:

```text
~49k chars static prompt floor
+ growing replayed tool transcript
+ especially retained command outputs containing file snippets
```

The dominant research question is therefore not "which process used memory?"
but "which prompt/harness policy decides what tool outputs stay in the
transcript, for how long, and in what form?"
