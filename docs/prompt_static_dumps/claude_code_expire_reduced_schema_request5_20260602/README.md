# Claude Code Static Prompt Dump - claude_code_expire_reduced_schema_request5_20260602

Reduced-schema Claude Code request from the EXPIRE feature run. This is the 17-tool deepseek-v4-flash request shape that appeared alongside the full 27-tool deepseek-v4-pro schema.

Source run:

```text
runs/20260602T131620_claude_code_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0
```

Source artifact:

```text
runs/20260602T131620_claude_code_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0/prompt_payloads.jsonl
```

Captured request: `5`

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
| system instructions | 3,474 | 869 | `9ead0b179321d147ca623784ec2494541be531913770608b9732e999a8f2b885` |
| tool schema | 30,932 | 7,733 | `6930e0a2d00797c2333eb300c753bd4c9f6a3cc21f6e842c0e4914e037d6ef07` |
| input/message items | 2 | | |

Model: `deepseek-v4-flash`

Tool count: `17`
