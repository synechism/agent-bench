# Redis/Linux Matrix Summary

Source runs:
- Claude Code rerun with rootless strace exact exec capture: `20260527T184018_claude_code_*`
- Codex comparison batch: `20260527T153846_codex_*`

Baselines from the selected batches:
- Claude Code empty task: 270.0 MB peak PSS, 4.3s wall, 3 agent tool commands.
- Codex empty task: 130.4 MB peak PSS, 1.6s wall, 0 agent tool commands.

| Agent | Task | Wall Time | Peak PSS | PSS Over Baseline | Agent Tool Cmds | Exact Execve Subprocesses | Observed Subprocesses | Exit |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| claude_code | empty_task | 4.3s | 270.0 MB | 0.0 MB | 3 | 20 | 3 | 0 |
| claude_code | redis_getex_expired_event | 107.5s | 276.6 MB | 6.5 MB | 10 | 19 | 4 | 0 |
| claude_code | redis_getex_expired_event_tests | 213.4s | 278.1 MB | 8.0 MB | 31 | 42 | 4 | 0 |
| claude_code | redis_expire_conditional_options | 1443.0s | 560.5 MB | 290.5 MB | 40 | 45515 | 2274 | 0 |
| claude_code | linux_proc_thread_self | 189.2s | 404.3 MB | 134.3 MB | 15 | 27 | 5 | 0 |
| claude_code | linux_string_get_size_tests | 352.6s | 298.2 MB | 28.1 MB | 19 | 722 | 63 | 0 |
| claude_code | linux_string_get_size_return_length | 175.0s | 299.0 MB | 29.0 MB | 8 | 390 | 34 | 0 |
| codex | empty_task | 1.6s | 130.4 MB | 0.0 MB | 0 | 0 | 0 | 0 |
| codex | redis_getex_expired_event | 93.3s | 136.9 MB | 6.5 MB | 25 | 0 | 1 | 0 |
| codex | redis_getex_expired_event_tests | 366.0s | 804.2 MB | 673.8 MB | 60 | 0 | 152 | 0 |
| codex | redis_expire_conditional_options | 671.0s | 340.9 MB | 210.5 MB | 68 | 0 | 121 | 0 |
| codex | linux_proc_thread_self | 96.4s | 189.7 MB | 59.4 MB | 31 | 0 | 7 | 0 |
| codex | linux_string_get_size_tests | 200.5s | 181.1 MB | 50.8 MB | 20 | 0 | 20 | 0 |
| codex | linux_string_get_size_return_length | 151.5s | 189.7 MB | 59.4 MB | 33 | 0 | 22 | 0 |

Notes:
- Peak PSS is process-tree peak proportional set size.
- PSS Over Baseline subtracts that agent's empty-task peak PSS from the selected batch.
- Agent Tool Cmds is the high-level exact tool-command count. For Codex it comes from the transcript. For Claude Code it now comes from rootless strace, including Claude shell commands and Claude's internal `claude.exe`-wrapped tool launches such as `rg`.
- Exact Execve Subprocesses is argv-level exec tracing from strace. It is populated for the new Claude Code rerun only; the older Codex comparison batch was not run under strace.
- Observed Subprocesses is the sampled process-tree count from `proc_sampler`; it is useful as a fallback signal but does not carry exact argv.
- Claude Code rows include strace overhead. Use this table to validate tool accounting and first-order resource shape; rerun Codex with strace too before treating exact execve subprocess counts as cross-agent comparable.
