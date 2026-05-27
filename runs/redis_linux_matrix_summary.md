# Redis/Linux Matrix Summary

Source runs:
- `20260527T150854_*`
- `20260527T153846_*`

Baselines from the same batch:
- Claude Code empty task: 263.1 MB peak PSS, 4.0s wall
- Codex empty task: 130.4 MB peak PSS, 1.6s wall

| Agent | Task | Wall Time | Peak PSS | PSS Over Baseline | Exact Tools | Observed Subprocesses | Exit |
|---|---|---:|---:|---:|---:|---:|---:|
| claude_code | empty_task | 4.0s | 263.1 MB | 0.0 MB | 0 | 3 | 0 |
| claude_code | redis_getex_expired_event | 176.1s | 266.8 MB | 3.7 MB | 0 | 3 | 0 |
| claude_code | redis_getex_expired_event_tests | 174.3s | 265.7 MB | 2.6 MB | 0 | 3 | 0 |
| claude_code | redis_expire_conditional_options | 1257.8s | 647.3 MB | 384.2 MB | 0 | 128 | 0 |
| claude_code | linux_proc_thread_self | 132.4s | 263.2 MB | 0.1 MB | 0 | 5 | 0 |
| claude_code | linux_string_get_size_tests | 297.6s | 243.4 MB | 0.0 MB | 0 | 14 | 0 |
| claude_code | linux_string_get_size_return_length | 306.6s | 245.6 MB | 0.0 MB | 0 | 11 | 0 |
| codex | empty_task | 1.6s | 130.4 MB | 0.0 MB | 0 | 0 | 0 |
| codex | redis_getex_expired_event | 93.3s | 136.9 MB | 6.5 MB | 25 | 1 | 0 |
| codex | redis_getex_expired_event_tests | 366.0s | 804.2 MB | 673.8 MB | 60 | 152 | 0 |
| codex | redis_expire_conditional_options | 671.0s | 340.9 MB | 210.5 MB | 68 | 121 | 0 |
| codex | linux_proc_thread_self | 96.4s | 189.7 MB | 59.4 MB | 31 | 7 | 0 |
| codex | linux_string_get_size_tests | 200.5s | 181.1 MB | 50.8 MB | 20 | 20 | 0 |
| codex | linux_string_get_size_return_length | 151.5s | 189.7 MB | 59.4 MB | 33 | 22 | 0 |

Notes:
- Peak PSS is process-tree peak proportional set size.
- PSS Over Baseline subtracts that agent's empty-task peak PSS from the same batch.
- Exact tool counts come from shims/transcripts/exec tracing where available.
- Claude Code headless currently gives mostly observed subprocesses rather than exact tool argv.
- Codex exposes richer shell transcripts, so exact tool attribution is stronger for Codex runs.
