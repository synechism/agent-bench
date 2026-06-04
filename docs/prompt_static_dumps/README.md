# Static Prompt Dumps

This folder contains readable dumps of static prompt pieces captured from agent request payloads.

Each child folder splits a captured request into instruction/system text, developer or skills context, task/environment messages, and tool schema/descriptions.

## Snapshots

| folder | source run | model | request | instructions/system chars | tool schema chars | note |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `codex_empty_baseline_20260601` | `20260601T202331_codex_empty_baseline_empty_task_nocap_rep0` | `moonbridge` | 1 | 21,437 | 22,423 | clean Codex no-tool baseline |
| `codex_gpt55_distance60_request1_20260603` | `20260603T173458_codex_semantic_memory_sentinel_semantic_memory_sentinel_distance_60_nocap_rep0` | `gpt-5.5` | 1 | 21,335 | 7,324 | later Codex sentinel setup |
| `claude_code_empty_baseline_main_request_20260602` | `20260602T131620_claude_code_empty_baseline_empty_task_nocap_rep0` | `deepseek-v4-pro` | 2 | 6,063 | 74,427 | Main empty-baseline Claude Code request. Request 1 is a small no-tool title/metadata request; request 2 is the full agent prompt with the 27-tool schema. |
| `claude_code_expire_reduced_schema_request5_20260602` | `20260602T131620_claude_code_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0` | `deepseek-v4-flash` | 5 | 3,474 | 30,932 | Reduced-schema Claude Code request from the EXPIRE feature run. This is the 17-tool deepseek-v4-flash request shape that appeared alongside the full 27-tool deepseek-v4-pro schema. |

For Claude Code, request 1 in the empty baseline is a small no-tool title/metadata request. The main agent prompt begins on request 2, where the full 27-tool schema appears.

For Codex, request 1 is already the main request shape in these captured baselines.
