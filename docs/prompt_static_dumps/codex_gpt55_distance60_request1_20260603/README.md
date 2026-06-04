# Codex Static Prompt Dump - codex_gpt55_distance60_request1_20260603

This folder contains the static prompt pieces captured from request 1 of:

```text
runs/20260603T173458_codex_semantic_memory_sentinel_semantic_memory_sentinel_distance_60_nocap_rep0
```

Source artifact:

```text
runs/20260603T173458_codex_semantic_memory_sentinel_semantic_memory_sentinel_distance_60_nocap_rep0/prompt_payloads.jsonl
```

## Files

| file | contents |
| --- | --- |
| `01_base_instructions.md` | full captured base instruction string |
| `02_developer_permissions_and_skills.md` | developer-context input item, split into permissions and skill inventory/instructions |
| `03_task_and_environment.md` | user/environment/task messages from request 1 |
| `04_tool_schema.json` | full captured tool schema JSON advertised to the model |
| `05_tool_names_and_descriptions.md` | readable index of top-level tool names/descriptions plus nested namespace entries |

## Captured Sizes

| layer | chars | approx tokens | sha256 |
| --- | ---: | ---: | --- |
| base instructions | 21,335 | 5,334 | `c2a980bc28af132eb89e0b4c68ae884043faae83a1afd3fd4889f7e8a1ada7b0` |
| tool schema | 7,324 | 1,831 | `1f2eda85798da1d0bc04dd121d42a9ae2c7eaf274af7a9fafe1c7ef018b89abb` |
| input items | 3 | | |

The developer-context and task/environment blocks are stored as `input[]` message items rather than as the top-level `instructions` string.
