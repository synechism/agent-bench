# Semantic Memory Consumption Analysis - Claude Code Representative Batch - 2026-06-02

This report interprets the Claude Code semantic-context experiment. It focuses
on what Claude Code sends to the base model, how the context grows over time,
and how its semantic memory differs from Codex under the same DeepSeek-backed
Docker harness.

Source aggregate:

```text
docs/semantic_memory/claude_representative_aggregate_20260602.md
docs/semantic_memory/claude_representative_aggregate_20260602.json
docs/semantic_memory/claude_representative_aggregate_20260602.csv
```

Fresh runs:

```text
runs/20260602T000448_claude_code_empty_baseline_empty_task_nocap_rep0
runs/20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0
runs/20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0
runs/20260602T000448_claude_code_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0
```

## Method

We did not use unofficial Claude Code source for this pass, and the reported
numbers were not produced by Claude Trace. Instead, we used the same black-box
API observer that powers the rest of the harness and extended it to understand
Anthropic-style Claude payloads:

```text
top-level system
+ top-level tools
+ messages[]
+ assistant tool_use blocks
+ user tool_result blocks
+ thinking/redacted_thinking blocks
```

The run was Dockerized and sequential. Prompt capture was enabled with:

```bash
HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1
HARNESS_API_OBSERVER_CAPTURE_CHARS=500000
python -m orchestrator.matrix \
  --config harness_configs/harness_config_semantic_claude_representative.json
```

This gives us exact sanitized request bodies and per-layer sizes, while keeping
the experiment aligned with our process/resource measurement pipeline.

Claude Trace was evaluated after this report was written. With the current
`@anthropic-ai/claude-code@2.1.156` package, Claude Trace launches but fails
before the model call because Claude Code resolves to a native
`bin/claude.exe`, while Claude Trace injects a Node loader and expects a JS
entrypoint. The failed compatibility smoke run is:

```text
runs/20260602T003402_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0
```

It produced a zero-byte `.claude-trace` JSONL and the stderr error:

```text
TypeError [ERR_UNKNOWN_FILE_EXTENSION]: Unknown file extension ".exe"
```

So for current Claude Code, our HTTP observer is the reliable source of exact
request payloads. The exact prompt/body views are in each run's
`api_requests.jsonl`, `prompt_payloads.jsonl`, and `prompt_payload_report.md`.

## Executive Summary

Claude Code has a much larger semantic prompt floor than Codex:

```text
Claude Code empty baseline: ~85,088 chars, ~21,272 approx tokens
Codex empty baseline:       ~49,208 chars, ~12,302 approx tokens
```

The difference is mostly the Claude Code tool schema. Claude Code advertises 27
tools and sends about 74.4k chars of tool definitions in the main request. Codex
advertises fewer/lighter tools in this setup and sends about 22.4k chars of tool
schema.

After the fixed prompt floor, Claude Code context growth is dominated by
retained tool outputs and thinking/tool-call history. The large Redis feature
task reached about 272,597 semantic chars, or ~68,150 approx tokens, at its
largest request. Of that max request:

| layer | chars | share |
| --- | ---: | ---: |
| tool output memory | 109,102 | 40.0% |
| tool schema | 74,427 | 27.3% |
| tool call memory | 38,029 | 14.0% |
| thinking / compaction memory | 34,077 | 12.5% |
| developer context | 8,546 | 3.1% |
| system instructions | 6,488 | 2.4% |
| assistant text | 1,200 | 0.4% |
| user task/context | 728 | 0.3% |

No compaction occurred in the representative batch. The request payloads include
`thinking: {"type": "adaptive"}` and `context_management` with a clear-thinking
policy, but the observed context windows were retained rather than summarized.

## The 85k Static Floor

The main empty-baseline Claude Code request is the cleanest view of the fixed
prompt layer:

| layer | chars | share |
| --- | ---: | ---: |
| tool schema | 74,427 | 87.5% |
| system instructions | 6,063 | 7.1% |
| developer/skills context | 4,180 | 4.9% |
| user/task context | 418 | 0.5% |

Important detail: Claude Code makes a small title-generation request before the
main agent request. That first request is only about 1.5k semantic chars and has
no tool schema. The large floor starts on the second request, when the full
agent tool menu is available.

## What Is In The Claude Prompt?

For the main Redis feature request, the top-level `system` array has three
blocks:

| block | chars | notes |
| --- | ---: | --- |
| billing/header metadata | 85 | includes Claude Code version/entrypoint metadata |
| Claude Agent SDK identity | 62 | short identity sentence |
| software-engineering agent instructions | 6,117 | general coding-agent behavior, safety, tool-use policy |

The `messages` array then adds the benchmark task and a system-role developer
context block. In the feature run, that developer context was 4,180 chars on the
first main request and listed 13 available skills:

```text
deep-research, update-config, keybindings-help, verify, code-review,
simplify, fewer-permission-prompts, loop, claude-api, run, init, review,
security-review
```

Those skills are model-visible even when unused. The `Skill` tool itself is
also advertised in the tool schema, so Claude Code has both a skill inventory in
messages and a skill invocation mechanism in tools.

## Tool Schema Breakdown

The tool schema is the largest fixed component. In the main Claude request it is
about 74,427 chars across 27 tools.

Largest tool schemas in the Redis feature request:

| tool | schema chars |
| --- | ---: |
| Workflow | 20,328 |
| EnterPlanMode | 4,317 |
| AskUserQuestion | 4,199 |
| CronCreate | 4,029 |
| Agent | 3,757 |
| ScheduleWakeup | 3,687 |
| TaskUpdate | 3,510 |
| Grep | 3,224 |
| EnterWorktree | 3,047 |
| TaskCreate | 2,816 |
| Bash | 2,676 |

Interpretation:

- Claude Code's semantic floor is not primarily natural-language system prompt.
- The `Workflow` schema alone is nearly the size of Codex's entire tool schema.
- Several expensive tools are orchestration/lifecycle tools, not direct code
  editing tools.
- The tool menu is resent on every main model request, so the serialized cost is
  large even though the unique schema is static.

## Results

| task | API requests | tool calls | max semantic approx tokens | static chars | carried chars | file/tool-output chars |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| empty baseline | 2 | 0 | 21,272 | 85,088 | 0 | 0 |
| Redis QA | 18 | 20 | 28,769 | 87,107 | 27,966 | 14,377 |
| Redis test-writing | 25 | 37 | 38,885 | 88,556 | 66,981 | 34,626 |
| Redis feature | 36 | 51 | 68,150 | 90,189 | 182,408 | 109,102 |

The Redis feature task had the highest semantic and process footprint:

```text
wall time:                400.4s
full peak PSS:            719.0 MB
agent-isolated peak PSS:  298.7 MB
max semantic size:        272,597 chars
max semantic tokens:      ~68,150
```

The gap between full peak and agent-isolated peak is important. Full process
memory includes build/test processes. For semantic memory work, the
agent-isolated number is the better process-memory comparator.

## Growth Pattern

Claude Code starts with a small metadata/title request, then jumps to the full
agent prompt on request 2.

Redis feature context growth:

| request | total chars | static chars | carried chars | tool-output chars | thinking+assistant chars |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1,788 | 1,788 | 0 | 0 | 0 |
| 2 | 85,823 | 85,823 | 0 | 0 | 0 |
| 5 | 87,617 | 85,979 | 1,638 | 283 | 350 |
| 10 | 163,739 | 86,720 | 77,019 | 71,379 | 1,177 |
| 20 | 213,284 | 88,262 | 125,022 | 87,628 | 19,068 |
| 30 | 248,780 | 89,879 | 158,901 | 93,965 | 29,376 |
| 36 | 272,597 | 90,189 | 182,408 | 109,102 | 35,277 |

The sharp jump between requests 5 and 10 was caused by large retained file reads
and command output. Once a large `Read`, `Grep`, or `Bash` result is returned,
Claude Code keeps it in the conversation rather than replacing it with a compact
file memory abstraction.

## Tool Behavior

Tool calls by task:

| task | tools used |
| --- | --- |
| Redis QA | Grep 11, Read 6, TaskUpdate 2, TaskCreate 1 |
| Redis test-writing | Grep 21, Read 10, Glob 2, TaskUpdate 2, TaskCreate 1, Edit 1 |
| Redis feature | Grep 21, Bash 14, Read 6, Edit 6, TaskUpdate 2, TaskCreate 1, Glob 1 |

Largest retained outputs in the feature task:

| output | chars | source |
| --- | ---: | --- |
| full `src/expire.c` read | 29,242 | `Read` |
| full `tests/unit/expire.tcl` read | 23,185 | `Read` |
| `git diff` review | 12,986 | `Bash` |
| focused source/test snippets | ~6,900 each | `Grep`/`Read` |

This is the clearest semantic-memory finding for Claude Code: the retained file
memory is literal tool output. Claude Code does not just remember that it looked
at `expire.c`; it keeps the returned source text in the prompt history.

## Comparison To Codex

Same representative task set, both using the DeepSeek-backed setup:

| metric | Claude Code | Codex |
| --- | ---: | ---: |
| empty static floor | 85,088 chars | 49,208 chars |
| empty approx tokens | 21,272 | 12,302 |
| Redis feature max semantic tokens | 68,150 | 38,714 |
| Redis feature static chars | 90,189 | 49,551 |
| Redis feature carried chars | 182,408 | 105,304 |
| Redis feature tool-output chars | 109,102 | 68,386 |
| Redis feature tool calls | 51 | 65 |
| Redis feature API requests | 36 | 57 |
| Redis feature agent-isolated PSS | 298.7 MB | 165.0 MB |

Interpretation:

- Claude Code made fewer model requests and fewer tool calls on the feature
  task, but each request was semantically heavier.
- Claude Code's main prompt floor is about 1.7x Codex's floor.
- Claude Code's feature-task max context was about 1.8x Codex's max context.
- The difference is harness/tooling-layer driven, not only base-model driven:
  the prompt, tool schema, skill list, thinking blocks, and tool result format
  differ even when the backend model axis is standardized.

## Why Claude Behaves Differently

The observed behavior appears to come from four harness-layer choices:

1. Claude Code exposes a broad tool menu. The model sees workflow, cron,
   plan-mode, worktree, task-management, skill, web, notebook, bash, grep, read,
   edit, and write tools in every main request.
2. Claude Code carries a visible skill layer. The prompt includes a system-role
   skills inventory, and the model can call a `Skill` tool if it wants richer
   instructions.
3. Claude Code retains structured Anthropic tool history. Tool calls are
   assistant `tool_use` blocks; outputs are user `tool_result` blocks. Large
   file reads and diffs remain visible as literal text in later turns.
4. Claude Code uses adaptive thinking. Thinking blocks were present and grew to
   34,077 chars in the max feature request. These are smaller than tool outputs
   but still a real semantic-memory layer.

This supports the current hypothesis: memory behavior is not just "the model
likes to search." The harness changes what the model can see, what it is nudged
to do, and how much of each action is serialized back into the next prompt.

## Conclusions

For Claude Code, semantic memory consumption has three tiers:

```text
1. Static floor: mostly tool schema (~74k chars)
2. Harness context: system prompt + skills + task (~10-16k chars)
3. Working memory: retained tool calls, tool outputs, and thinking
```

The static floor is large enough that even an empty task costs ~21k approximate
tokens in the main request. On real tasks, working memory quickly dominates:
the Redis feature task carried 182k chars of history at the largest request,
with 109k chars of that coming from file/tool output.

The biggest unanswered question is not whether Claude Code retains file memory;
it clearly does. The next useful question is how much of that retention is
controllable by harness configuration: restricted tools, smaller read limits,
system prompt replacement/append ablations, or disabling selected workflow/skill
surfaces while holding the base model fixed.
