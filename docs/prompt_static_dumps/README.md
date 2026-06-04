# Codex Static Prompt Dumps

This folder contains readable dumps of the static prompt pieces captured from Codex request payloads.

Each child folder splits request 1 into base instructions, developer permissions/skills, task/environment messages, and tool schema/descriptions.

## Snapshots

| folder | source run | model | base chars | tool schema chars | developer/task input items |
| --- | --- | --- | ---: | ---: | ---: |
| `codex_empty_baseline_20260601` | `20260601T202331_codex_empty_baseline_empty_task_nocap_rep0` | `moonbridge` | 21,437 | 22,423 | 3 |
| `codex_gpt55_distance60_request1_20260603` | `20260603T173458_codex_semantic_memory_sentinel_semantic_memory_sentinel_distance_60_nocap_rep0` | `gpt-5.5` | 21,335 | 7,324 | 3 |

The `codex_gpt55_distance60_request1_20260603` snapshot matches the later sentinel runs used for the highest-pressure semantic-memory experiments. The earlier empty baseline is still useful because it is the cleanest no-tool baseline from the representative batch, but its tool schema hash differs from the later `gpt-5.5` runs.
