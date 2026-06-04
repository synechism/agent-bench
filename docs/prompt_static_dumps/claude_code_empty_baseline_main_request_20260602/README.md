# Claude Code Static Prompt Dump - claude_code_empty_baseline_main_request_20260602

Main empty-baseline Claude Code request. Request 1 is a small no-tool title/metadata request; request 2 is the full agent prompt with the 27-tool schema.

Source run:

```text
runs/20260602T131620_claude_code_empty_baseline_empty_task_nocap_rep0
```

Source artifact:

```text
runs/20260602T131620_claude_code_empty_baseline_empty_task_nocap_rep0/prompt_payloads.jsonl
```

Captured request: `2`

## Files

| file | contents |
| --- | --- |
| `01_system_instructions.md` | captured top-level Anthropic `system` blocks normalized as instructions |
| `02_developer_skills_context.md` | system-role developer/skills message items from `messages[]` |
| `03_task_and_reminders.md` | user/task/system-reminder message items from `messages[]` |
| `04_tool_schema.json` | full captured top-level `tools[]` JSON schema |
| `05_tool_names_and_descriptions.md` | readable index of tool names, descriptions, and parameter summaries |

## Captured Sizes

| layer | chars | approx tokens | sha256 |
| --- | ---: | ---: | --- |
| system instructions | 6,063 | 1,516 | `406e7e0e74e332775a9c9ecd984d4976111512e0883e30c358ee0589edb717d4` |
| tool schema | 74,427 | 18,607 | `01ca83c6c90fa159cf033023b8c64081f8e14575dc534372f561e813a1ed1c7e` |
| input/message items | 2 | | |

Model: `deepseek-v4-pro`

Tool count: `27`
