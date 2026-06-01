# Semantic Context Aggregate

This report aggregates semantic context-window measurements across runs.

- Runs included: 4

| run | task | ok | reqs | tools | max semantic toks | static chars | carried chars | file/tool chars | isolated MB | compaction |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `20260601T202331_codex_empty_baseline_empty_task_nocap_rep0` | baseline/empty_task | True | 1 | 0 | 12302 | 49208 | 0 | 0 | 170.0 | False |
| `20260601T202331_codex_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0` | feature/redis_expire_conditional_options | True | 57 | 65 | 38714 | 49551 | 105304 | 68386 | 165.0 | False |
| `20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0` | qa/redis_getex_expired_event | True | 23 | 27 | 20456 | 49451 | 32371 | 28478 | 167.1 | False |
| `20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0` | tests/redis_getex_expired_event_tests | True | 112 | 123 | 40398 | 49482 | 112107 | 82403 | 180.2 | False |

## Rollups

### `codex|baseline|empty_task`

- runs: 1; successes: 1
- api_requests: median 1.0, max 1.0, tool_invocations: median 0.0, max 0.0, full_peak_pss_mb: median 170.0, max 170.0, agent_isolated_peak_pss_mb: median 170.0, max 170.0, max_semantic_approx_tokens: median 12302.0, max 12302.0, static_prompt_chars: median 49208.0, max 49208.0, carried_memory_chars: median 0.0, max 0.0, file_or_tool_output_chars: median 0.0, max 0.0, semantic_growth_chars: median 0.0, max 0.0
- run ids: `20260601T202331_codex_empty_baseline_empty_task_nocap_rep0`

### `codex|feature|redis_expire_conditional_options`

- runs: 1; successes: 1
- api_requests: median 57.0, max 57.0, tool_invocations: median 65.0, max 65.0, full_peak_pss_mb: median 520.0, max 520.0, agent_isolated_peak_pss_mb: median 165.0, max 165.0, max_semantic_approx_tokens: median 38714.0, max 38714.0, static_prompt_chars: median 49551.0, max 49551.0, carried_memory_chars: median 105304.0, max 105304.0, file_or_tool_output_chars: median 68386.0, max 68386.0, semantic_growth_chars: median 105304.0, max 105304.0
- run ids: `20260601T202331_codex_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0`

### `codex|qa|redis_getex_expired_event`

- runs: 1; successes: 1
- api_requests: median 23.0, max 23.0, tool_invocations: median 27.0, max 27.0, full_peak_pss_mb: median 167.1, max 167.1, agent_isolated_peak_pss_mb: median 167.1, max 167.1, max_semantic_approx_tokens: median 20456.0, max 20456.0, static_prompt_chars: median 49451.0, max 49451.0, carried_memory_chars: median 32371.0, max 32371.0, file_or_tool_output_chars: median 28478.0, max 28478.0, semantic_growth_chars: median 32371.0, max 32371.0
- run ids: `20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0`

### `codex|tests|redis_getex_expired_event_tests`

- runs: 1; successes: 1
- api_requests: median 112.0, max 112.0, tool_invocations: median 123.0, max 123.0, full_peak_pss_mb: median 180.2, max 180.2, agent_isolated_peak_pss_mb: median 180.2, max 180.2, max_semantic_approx_tokens: median 40398.0, max 40398.0, static_prompt_chars: median 49482.0, max 49482.0, carried_memory_chars: median 112107.0, max 112107.0, file_or_tool_output_chars: median 82403.0, max 82403.0, semantic_growth_chars: median 112107.0, max 112107.0
- run ids: `20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0`

## Largest Retained Tool Outputs

### `20260601T202331_codex_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0`

- 13820 chars: {"arguments": "{\"cmd\": \"sed -n '250,604p' tests/unit/expire.tcl\"}", "call_id": "call_00_2egFFe7ZsRwL9pg2DNKn3805", "name": "exec_command"}
- 5305 chars: {"arguments": "{\"cmd\": \"sed -n '80,250p' tests/unit/expire.tcl\"}", "call_id": "call_00_JTNyVIKvsPFg14aiZznq3123", "name": "exec_command"}
- 4465 chars: {"arguments": "{\"cmd\": \"cd /runs/20260601T202331_codex_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0/codebase && make distclean 2>&1 && make -j$(nproc) M
- 3569 chars: {"arguments": "{\"cmd\": \"sed -n '460,540p' src/expire.c\"}", "call_id": "call_00_YMDlypxrTTNbEFTnTUpC6536", "name": "exec_command"}
- 3495 chars: {"arguments": "{\"cmd\": \"sed -n '496,580p' src/expire.c\"}", "call_id": "call_00_XGzzZcbFNyoVBds1BQnC9221", "name": "exec_command"}
- prompt report: `runs/20260601T202331_codex_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0/prompt_payload_report.md`

### `20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0`

- 4391 chars: {"arguments": "{\"cmd\": \"sed -n '1713,1810p' src/db.c\"}", "call_id": "call_00_ET_8Hc36GMqzoVra3CCLuEY5547", "name": "exec_command"}
- 4187 chars: {"arguments": "{\"cmd\": \"sed -n '342,440p' src/t_string.c\"}", "call_id": "call_00_t1boMMjcDgu52KPvOLvQ2253", "name": "exec_command"}
- 2853 chars: {"arguments": "{\"cmd\": \"sed -n '44,100p' src/db.c\"}", "call_id": "call_00_SzYPIsSqriKDN315zAwg0974", "name": "exec_command"}
- 2585 chars: {"arguments": "{\"cmd\": \"sed -n '1618,1680p' src/db.c\"}", "call_id": "call_00_ET_vKcw7pkYzkeZXr8dpuHW1695", "name": "exec_command"}
- 2523 chars: {"arguments": "{\"cmd\": \"sed -n '600,660p' src/expire.c\"}", "call_id": "call_00_5KHhTpBEvaq92bKTY04w5411", "name": "exec_command"}
- prompt report: `runs/20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0/prompt_payload_report.md`

### `20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0`

- 4554 chars: {"arguments": "{\"cmd\": \"sed -n '340,450p' ./src/t_string.c\"}", "call_id": "call_00_2pSeIpYgn5vSfDnB0RsH3475", "name": "exec_command"}
- 3120 chars: {"arguments": "{\"cmd\": \"sed -n '570,660p' ./tests/unit/expire.tcl\"}", "call_id": "call_01_ZvNwzd8jlbJDwUNljSIS4512", "name": "exec_command"}
- 2604 chars: {"arguments": "{\"cmd\": \"sed -n '250,310p' ./tests/unit/pubsub.tcl\"}", "call_id": "call_01_gfFlyAZXKMJRy8elXjVq9807", "name": "exec_command"}
- 2583 chars: {"arguments": "{\"cmd\": \"sed -n '550,620p' ./tests/support/server.tcl\"}", "call_id": "call_00_SPstpKG42lCfNqIX5trM6020", "name": "exec_command"}
- 2411 chars: {"arguments": "{\"cmd\": \"sed -n '470,530p' ./tests/support/server.tcl\"}", "call_id": "call_00_8E2kDc5lNMjnLGMAX4YC0858", "name": "exec_command"}
- prompt report: `runs/20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0/prompt_payload_report.md`
