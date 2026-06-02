# Semantic Context Aggregate

This report aggregates semantic context-window measurements across runs.

- Runs included: 4

| run | task | ok | reqs | tools | max semantic toks | static chars | carried chars | file/tool chars | isolated MB | compaction |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `20260602T000448_claude_code_empty_baseline_empty_task_nocap_rep0` | baseline/empty_task | True | 2 | 0 | 21272 | 85088 | 0 | 0 | 287.0 | False |
| `20260602T000448_claude_code_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0` | feature/redis_expire_conditional_options | True | 36 | 51 | 68150 | 90189 | 182408 | 109102 | 298.7 | False |
| `20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0` | qa/redis_getex_expired_event | True | 18 | 20 | 28769 | 87107 | 27966 | 14377 | 283.3 | False |
| `20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0` | tests/redis_getex_expired_event_tests | True | 25 | 37 | 38885 | 88556 | 66981 | 34626 | 282.0 | False |

## Rollups

### `claude_code|baseline|empty_task`

- runs: 1; successes: 1
- api_requests: median 2.0, max 2.0, tool_invocations: median 0.0, max 0.0, full_peak_pss_mb: median 287.0, max 287.0, agent_isolated_peak_pss_mb: median 287.0, max 287.0, max_semantic_approx_tokens: median 21272.0, max 21272.0, static_prompt_chars: median 85088.0, max 85088.0, carried_memory_chars: median 0.0, max 0.0, file_or_tool_output_chars: median 0.0, max 0.0, semantic_growth_chars: median 83610.0, max 83610.0
- run ids: `20260602T000448_claude_code_empty_baseline_empty_task_nocap_rep0`

### `claude_code|feature|redis_expire_conditional_options`

- runs: 1; successes: 1
- api_requests: median 36.0, max 36.0, tool_invocations: median 51.0, max 51.0, full_peak_pss_mb: median 719.0, max 719.0, agent_isolated_peak_pss_mb: median 298.7, max 298.7, max_semantic_approx_tokens: median 68150.0, max 68150.0, static_prompt_chars: median 90189.0, max 90189.0, carried_memory_chars: median 182408.0, max 182408.0, file_or_tool_output_chars: median 109102.0, max 109102.0, semantic_growth_chars: median 270809.0, max 270809.0
- run ids: `20260602T000448_claude_code_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0`

### `claude_code|qa|redis_getex_expired_event`

- runs: 1; successes: 1
- api_requests: median 18.0, max 18.0, tool_invocations: median 20.0, max 20.0, full_peak_pss_mb: median 283.3, max 283.3, agent_isolated_peak_pss_mb: median 283.3, max 283.3, max_semantic_approx_tokens: median 28769.0, max 28769.0, static_prompt_chars: median 87107.0, max 87107.0, carried_memory_chars: median 27966.0, max 27966.0, file_or_tool_output_chars: median 14377.0, max 14377.0, semantic_growth_chars: median 113382.0, max 113382.0
- run ids: `20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0`

### `claude_code|tests|redis_getex_expired_event_tests`

- runs: 1; successes: 1
- api_requests: median 25.0, max 25.0, tool_invocations: median 37.0, max 37.0, full_peak_pss_mb: median 282.0, max 282.0, agent_isolated_peak_pss_mb: median 282.0, max 282.0, max_semantic_approx_tokens: median 38885.0, max 38885.0, static_prompt_chars: median 88556.0, max 88556.0, carried_memory_chars: median 66981.0, max 66981.0, file_or_tool_output_chars: median 34626.0, max 34626.0, semantic_growth_chars: median 153821.0, max 153821.0
- run ids: `20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0`

## Largest Retained Tool Outputs

### `20260602T000448_claude_code_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0`

- 29242 chars: {"id": "call_00_7TZ3Av8Us8nWDyC4YnLE3505", "input": {"file_path": "/runs/20260602T000448_claude_code_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0/codebase/
- 23185 chars: {"id": "call_02_aExupT69OcRq44ZNExv22310", "input": {"file_path": "/runs/20260602T000448_claude_code_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0/codebase/
- 12986 chars: {"id": "call_00_UAU7zJQxWE6QUhoae2AD7038", "input": {"command": "git diff", "description": "Review all changes"}, "name": "Bash"}
- 6963 chars: {"id": "call_01_zBVNzua2b26PRu5y54bS3225", "input": {"context": 2, "output_mode": "content", "path": "/runs/20260602T000448_claude_code_redis_expire_options_base_redis_expire_condi
- 6904 chars: {"id": "call_01_GiOlhdBazxHDDETWfkph3518", "input": {"file_path": "/runs/20260602T000448_claude_code_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0/codebase/
- prompt report: `runs/20260602T000448_claude_code_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0/prompt_payload_report.md`

### `20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0`

- 4590 chars: {"id": "call_00_FUTmftlSeQtiNEr6hqCY4532", "input": {"file_path": "/runs/20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0/codebase/src
- 2028 chars: {"id": "call_00_2NkfntGHCK1CofivfLbv0696", "input": {"file_path": "/runs/20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0/codebase/src
- 1785 chars: {"id": "call_00_dX1KgNqjiSTdZNJdbYqm3906", "input": {"file_path": "/runs/20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0/codebase/src
- 1715 chars: {"id": "call_00_qrOD9OQc7br6gPbVBDgZ4448", "input": {"file_path": "/runs/20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0/codebase/src
- 1133 chars: {"id": "call_00_fTWPASJQgq5eBtgbAedd2004", "input": {"file_path": "/runs/20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0/codebase/src
- prompt report: `runs/20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0/prompt_payload_report.md`

### `20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0`

- 4982 chars: {"id": "call_01_SiHP8NHTbjoui6wx1Tfl7189", "input": {"file_path": "/runs/20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0/codeba
- 4425 chars: {"id": "call_00_SqO6spBNuqH1Hf8D2imN1454", "input": {"file_path": "/runs/20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0/codeba
- 3794 chars: {"id": "call_02_VoeVQnrDDLtSHrCPJEmJ7912", "input": {"path": "/runs/20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0/codebase", 
- 3353 chars: {"id": "call_00_IRTsomHaKgdAkUXWSvAe2976", "input": {"file_path": "/runs/20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0/codeba
- 2702 chars: {"id": "call_01_CbXMZWiOgRaRW2R1DEzE1325", "input": {"file_path": "/runs/20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0/codeba
- prompt report: `runs/20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0/prompt_payload_report.md`
