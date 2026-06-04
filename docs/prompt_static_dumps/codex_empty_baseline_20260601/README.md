# Codex Static Prompt Dump - codex_empty_baseline_20260601

This folder contains the static prompt pieces captured from request 1 of:

```text
runs/20260601T202331_codex_empty_baseline_empty_task_nocap_rep0
```

Source artifact:

```text
runs/20260601T202331_codex_empty_baseline_empty_task_nocap_rep0/prompt_payloads.jsonl
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
| base instructions | 21,437 | 5,360 | `f6aefd86a73a8cf0ab004b2200664e143cfd9c4214a1082660b4dd3311c7303f` |
| tool schema | 22,423 | 5,606 | `a99d169906d9f615cb8712ac028df9cb8b3f14e4ddbd6d8ee8649d501b140bad` |
| input items | 3 | | |

The developer-context and task/environment blocks are stored as `input[]` message items rather than as the top-level `instructions` string.
