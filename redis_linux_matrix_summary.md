# Redis/Linux Matrix Summary

Source runs:
- Claude Code rerun with rootless strace exact exec capture: `20260527T184018_claude_code_*`
- Codex rerun with rootless strace exact exec capture: `20260527T193102_codex_*`

Baselines from the selected batches:
- Claude Code empty task: 270.0 MB peak PSS, 4.3s wall, 3 agent tool commands.
- Codex empty task: 160.5 MB peak PSS, 5.0s wall, 0 agent tool commands.

| Agent | Task | Wall Time | Peak PSS | PSS Over Baseline | Agent Tool Cmds | Exact Execve Subprocesses | Observed Subprocesses | Exit |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| claude_code | empty_task | 4.3s | 270.0 MB | 0.0 MB | 3 | 20 | 3 | 0 |
| claude_code | redis_getex_expired_event | 107.5s | 276.6 MB | 6.5 MB | 10 | 19 | 4 | 0 |
| claude_code | redis_getex_expired_event_tests | 213.4s | 278.1 MB | 8.0 MB | 31 | 42 | 4 | 0 |
| claude_code | redis_expire_conditional_options | 1443.0s | 560.5 MB | 290.5 MB | 40 | 45515 | 2274 | 0 |
| claude_code | linux_proc_thread_self | 189.2s | 404.3 MB | 134.3 MB | 15 | 27 | 5 | 0 |
| claude_code | linux_string_get_size_tests | 352.6s | 298.2 MB | 28.1 MB | 19 | 722 | 63 | 0 |
| claude_code | linux_string_get_size_return_length | 175.0s | 299.0 MB | 29.0 MB | 8 | 390 | 34 | 0 |
| codex | empty_task | 5.0s | 160.5 MB | 0.0 MB | 0 | 296 | 21 | 0 |
| codex | redis_getex_expired_event | 153.4s | 155.0 MB | 0.0 MB | 35 | 1029 | 81 | 0 |
| codex | redis_getex_expired_event_tests | 664.4s | 793.2 MB | 632.7 MB | 72 | 21115 | 1535 | 0 |
| codex | redis_expire_conditional_options | 981.3s | 397.5 MB | 236.9 MB | 46 | 18512 | 1210 | 0 |
| codex | linux_proc_thread_self | 106.2s | 180.9 MB | 20.3 MB | 24 | 494 | 64 | 0 |
| codex | linux_string_get_size_tests | 370.4s | 4417.6 MB | 4257.1 MB | 28 | 1072 | 145 | 0 |
| codex | linux_string_get_size_return_length | 241.3s | 185.8 MB | 25.2 MB | 44 | 1131 | 151 | 0 |

Notes:
- Peak PSS is process-tree peak proportional set size.
- PSS Over Baseline subtracts that agent's empty-task peak PSS from the selected batch and is floored at zero when the measured task peak is lower than the empty baseline.
- Agent Tool Cmds is the high-level exact tool-command count. For Codex it comes from the transcript. For Claude Code it now comes from rootless strace, including Claude shell commands and Claude's internal `claude.exe`-wrapped tool launches such as `rg`.
- Exact Execve Subprocesses is argv-level exec tracing from strace. Both selected batches were rerun with this tracing mode, so these counts are now comparable under the same measurement path.
- Observed Subprocesses is the sampled process-tree count from `proc_sampler`; it is useful as a fallback signal but does not carry exact argv.
- Both agents include rootless strace overhead in this table.
