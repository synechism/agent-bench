# DeepSeek Docker Agent Experiments - 2026-06-01

This report integrates the recent Dockerized benchmark runs for Claude Code,
Codex, and Pi, all routed to DeepSeek V4 Pro where possible. The goal is not
only to compare resource numbers, but to explain what the agent harness,
prompt, and tooling layers appear to be doing differently.

## Executive Summary

All three agents completed the Redis/Linux matrix successfully under Docker:

- Claude Code: `20260601T133859_claude_code_*`
- Codex via Moon Bridge: `20260601T130454_codex_*`
- Pi direct DeepSeek provider: `20260601T153943_pi_*`

The main finding is that standardizing the base model does not standardize the
behavior. Even with DeepSeek V4 Pro behind the agent, the harness layer strongly
changes:

- baseline resident memory,
- model-visible tool surface,
- how much context is serialized into API calls,
- whether the model reaches for built-in read/edit tools or shell commands,
- how aggressively it verifies work,
- how much project build/test fanout gets triggered.

Pi is the clearest evidence. It used the same Docker harness and DeepSeek target,
but had a much smaller tool surface and fewer turns. It was fastest on 4 of 6
real tasks and made about half as many API requests as Claude Code or Codex.
However, Pi still hit high memory on the Redis feature task because Redis build
and test activity dominated peak process-tree memory.

## Experimental Setup

All runs used the harness Docker path, not host-local agent execution. Each run
created an isolated `runs/<run_id>/codebase` checkout and collected:

- process-tree PSS/USS/RSS samples from `/proc`,
- shimmed subprocess/tool invocations,
- rootless `strace`/exec observations where available,
- structured agent stdout/stderr events,
- redacted API request/response metadata through the observer proxy,
- `agent_context.json` with non-secret environment, command, and available
  skill/plugin/config inventories.

Model routing:

| Agent | DeepSeek Route | Notes |
|---|---|---|
| Claude Code | Anthropic-compatible DeepSeek endpoint | Forced with `ANTHROPIC_MODEL`, all `ANTHROPIC_DEFAULT_*_MODEL`, and `CLAUDE_CODE_SUBAGENT_MODEL` set to `deepseek-v4-pro[1m]`. |
| Codex | Moon Bridge forwarding layer | Codex talks to local `moonbridge`; bridge routes to `deepseek-v4-pro`. The observer sees `moonbridge` at the local boundary. |
| Pi | Direct DeepSeek provider config | `pi-with-deepseek` writes Pi `models.json` and runs `--model deepseek/deepseek-v4-pro --thinking high`. |

Pi was configured deliberately as a lightweight contrast:

```text
--no-session
--no-extensions
--no-skills
--no-prompt-templates
--no-themes
--tools read,bash,edit,write,grep,find,ls
```

That makes Pi useful for isolating the harness/tooling layer: same task, same
Docker measurement layer, same target model family, fewer optional harness
surfaces.

## Results

All 21 selected runs completed with `exit_code=0`, task success true, and API
observer status `200`.

| Agent | Task | Wall | Peak PSS | Tool Calls | API Requests | API Wait | API Payload |
|---|---:|---:|---:|---:|---:|---:|---:|
| claude_code | empty_task | 3.6s | 279.4 MB | 0 | 2 | 6.0s | 0.1 MB |
| codex | empty_task | 7.9s | 164.0 MB | 0 | 1 | 2.8s | 0.1 MB |
| pi | empty_task | 2.8s | 162.9 MB | 0 | 1 | 2.2s | 0.0 MB |
| claude_code | redis_getex_expired_event | 144.6s | 283.5 MB | 15 | 13 | 171.4s | 2.1 MB |
| codex | redis_getex_expired_event | 139.7s | 169.7 MB | 31 | 21 | 132.4s | 2.5 MB |
| pi | redis_getex_expired_event | 101.7s | 172.5 MB | 20 | 14 | 100.5s | 1.7 MB |
| claude_code | redis_getex_expired_event_tests | 315.2s | 287.0 MB | 55 | 16 | 319.9s | 3.5 MB |
| codex | redis_getex_expired_event_tests | 377.6s | 163.4 MB | 68 | 72 | 363.8s | 9.1 MB |
| pi | redis_getex_expired_event_tests | 104.0s | 164.0 MB | 21 | 15 | 102.6s | 2.4 MB |
| claude_code | redis_expire_conditional_options | 664.7s | 699.0 MB | 152 | 82 | 914.6s | 18.9 MB |
| codex | redis_expire_conditional_options | 889.6s | 514.1 MB | 86 | 81 | 792.0s | 22.0 MB |
| pi | redis_expire_conditional_options | 300.2s | 628.0 MB | 57 | 48 | 254.8s | 8.0 MB |
| claude_code | linux_proc_thread_self | 177.2s | 283.8 MB | 25 | 14 | 178.8s | 2.6 MB |
| codex | linux_proc_thread_self | 90.4s | 213.1 MB | 29 | 14 | 83.1s | 1.5 MB |
| pi | linux_proc_thread_self | 123.6s | 197.3 MB | 25 | 13 | 122.2s | 2.1 MB |
| claude_code | linux_string_get_size_tests | 1034.2s | 292.8 MB | 70 | 67 | 967.6s | 22.5 MB |
| codex | linux_string_get_size_tests | 282.5s | 217.7 MB | 31 | 28 | 272.2s | 5.7 MB |
| pi | linux_string_get_size_tests | 259.7s | 306.2 MB | 11 | 8 | 258.3s | 4.9 MB |
| claude_code | linux_string_get_size_return_length | 263.2s | 287.0 MB | 38 | 29 | 262.6s | 4.6 MB |
| codex | linux_string_get_size_return_length | 53.0s | 212.1 MB | 6 | 4 | 47.3s | 0.7 MB |
| pi | linux_string_get_size_return_length | 133.8s | 172.2 MB | 20 | 15 | 129.9s | 2.6 MB |

Non-baseline aggregate:

| Agent | Mean Wall | Mean Peak PSS | Tool Calls | API Requests | API Wait | API Payload |
|---|---:|---:|---:|---:|---:|---:|
| claude_code | 433.2s | 355.5 MB | 355 | 221 | 2814.9s | 54.1 MB |
| codex | 305.5s | 248.4 MB | 251 | 220 | 1690.7s | 41.4 MB |
| pi | 170.5s | 273.4 MB | 154 | 113 | 968.3s | 21.7 MB |

Per-task winners:

| Task | Fastest | Lowest PSS | Fewest API Requests | Fewest Tool Calls |
|---|---|---|---|---|
| redis_getex_expired_event | pi | codex | claude_code | claude_code |
| redis_getex_expired_event_tests | pi | codex | pi | pi |
| redis_expire_conditional_options | pi | codex | pi | pi |
| linux_proc_thread_self | codex | pi | pi | claude_code |
| linux_string_get_size_tests | pi | codex | pi | pi |
| linux_string_get_size_return_length | codex | pi | codex | codex |

## What Explains The Differences?

### 1. Runtime Footprint

The empty-task baseline is the cleanest estimate of each harness runtime floor:

- Claude Code: 279.4 MB peak PSS
- Codex: 164.0 MB peak PSS
- Pi: 162.9 MB peak PSS

This is not task behavior yet; it is the cost of launching the agent runtime
with our Docker wrapper, auth/config, and observer plumbing. Claude Code starts
from a materially higher memory floor. That matters because any real task is
baseline plus incremental repo/tool/build work.

Interpretation: Claude Code's harness has a heavier resident runtime and/or
initial context machinery in this setup. Codex and Pi begin with similar
baselines, so their later differences come more from task behavior than startup
footprint.

### 2. Tool Surface

The API observer recorded very different model-visible tool menus:

| Agent | Advertised Tool Names |
|---|---:|
| Claude Code | 28 |
| Codex | 12 |
| Pi | 7 |

Claude advertised a broad menu: `Agent`, `Bash`, `Edit`, `Grep`, `Read`,
`Skill`, `Task*`, `Web*`, workflow/cron tools, notebook editing, and worktree
tools.

Codex advertised a smaller but shell-oriented surface: `exec_command`,
`write_stdin`, `apply_patch`, planning, MCP/resource tools, web search, image,
and user input.

Pi advertised only: `bash`, `edit`, `find`, `grep`, `ls`, `read`, `write`.

This appears to drive different action paths:

- Claude often uses structured `Grep`, `Read`, and `Edit` tools instead of raw
  shell search/read commands.
- Codex tends to inspect through shell commands such as `rg`, `sed`, `nl`, and
  `git`, then edits through patching.
- Pi has fewer possible moves, so it spends less time choosing among tool
  families and made fewer model/tool turns on these tasks.

### 3. Prompt And Context Serialization

The observer's prompt-like message counters differed sharply:

| Agent | Prompt-Like Input/Message Chars Across 7 Runs |
|---|---:|
| Claude Code | ~25.0M |
| Pi | ~5.6M |
| Codex | ~1.4M |

This is not a complete raw system prompt dump. For these routes,
`system_or_instructions` was not captured as nonzero, so the exact system prompt
text remains only partially observable. Still, the message/context payload
differences are large enough to matter.

Interpretation:

- Claude appears to send or replay much more model-visible context/tool state
  through its API traffic.
- Pi emits and consumes rich structured JSON, but has a smaller tool menu and
  lower request count.
- Codex's request payloads were the smallest in this matrix, even though it
  made almost as many requests as Claude.

This likely explains part of the API wait and wall-time differences. The model
is nominally standardized, but the actual request shape is not.

### 4. Base Prompt Tendencies

From the system-prompt investigation:

- Claude Code's prompt inventory emphasizes treating ambiguous requests as
  software engineering tasks, using dedicated read/search/edit tools, reporting
  verification honestly, and using built-in tool paths such as `Grep` and
  `Read`.
- Codex's effective prompt/developer context emphasizes inspecting the repo,
  preferring `rg`/`rg --files`, making focused edits, using `apply_patch`, and
  verifying after changes.
- Pi was configured with optional extensions, skills, prompt templates, and
  themes disabled. Its behavior is therefore a useful approximation of a
  thinner harness loop around the model plus a small tool set.

### 5. Verification Strategy And Project Build Fanout

The Redis conditional-expire task was the clearest memory hotspot:

- Claude Code: 699.0 MB
- Codex: 514.1 MB
- Pi: 628.0 MB

Pi being lightweight did not prevent a high peak here. That tells us the memory
hotspot was not only "agent runtime bloat." It was also Redis build/server/test
activity spawned by the agent.

This distinction matters:

- Harness choices drive how quickly and how often the agent reaches tools.
- Project commands determine how expensive those tool calls become.
- Heavy verification can erase the advantage of a small harness if it triggers
  high-fanout compilation or test processes.

### 6. Search And Retry Behavior

Behavior metrics from the selected runs:

| Agent | Zero-Match Searches | Excessive Searches | Reads Later Edited | Repeated Failures No Edit | Command Output |
|---|---:|---:|---:|---:|---:|
| Claude Code | 618 | 0 | 8 | 0 | 4.2 MB |
| Codex | 171 | 1 | 5 | 8 | 9.5 MB |
| Pi | 118 | 0 | 9 | 0 | 993.0 MB |

Interpretation:

- Claude's large zero-match count reflects repeated structured search behavior,
  especially on the Linux string-size test. This is a harness/tool-routing
  pattern, not necessarily a failure.
- Codex had more repeated failures without detected edits. That matches a
  shell-oriented loop where the agent retries commands or verification before
  changing source again.
- Pi's command-output number is currently inflated by its JSON event stream and
  thinking/tool deltas being visible on stdout. Until we split agent stream
  bytes from actual command output bytes, Pi's command-output metric should not
  be compared directly to Claude/Codex.

## What We Can Say Causally

Strong evidence:

- Docker isolation and the same task pack did not eliminate differences.
- Standardizing on DeepSeek V4 Pro did not eliminate differences.
- Tool menus, request shapes, and runtime baselines differ substantially.
- No optional workspace skills/plugins explain the latest matrix.
- Heavy repo commands, especially Redis build/test flows, dominate peak memory
  on the hardest feature task.

Likely explanation:

- Claude Code is shaped by a broad built-in agent/tool system and heavier
  context serialization. It does not literally load extra skills here, but it
  advertises a much broader tool/skill-capable surface.
- Codex is shaped by a shell-first engineering loop: inspect with `rg`/shell,
  patch, verify, retry. This tends to make its local process tree easy to
  observe and often memory-light, but can produce repeated command retries.
- Pi is shaped by a much smaller harness surface. It makes fewer model/tool
  turns and sends less total API payload than Claude/Codex, which explains its
  strong wall-time results. It still pays the full cost of whatever build/test
  command it chooses.

Not yet proven:

- The exact raw system prompt sent in every request. We have prompt inventory
  and request metadata, but not a perfect raw prompt dump for all providers.
- Whether the observed behavior is mostly prompt wording, tool schema shape, or
  model priors. The data points to all three, but separating them requires
  ablations.
- Whether the single-repetition timing order will hold statistically. These are
  strong directional runs, not final N=5 distributions.

## Recommended Next Experiments

These should be ablations, not optimizations. We are trying to explain the
behavior before changing it.

1. **Verification ablation**

   Add an instruction such as: "Use targeted tests only. Do not run full project
   builds unless a targeted test cannot exercise the change." Compare build/test
   spans, memory peaks, and success.

2. **Build parallelism ablation**

   Add: "Never use more than 2 build jobs." Compare Redis feature peak PSS. This
   directly tests whether memory spikes are mainly build fanout.

3. **Tool-surface ablation**

   Restrict Claude/Codex as much as possible toward a Pi-like read/edit/bash
   surface. If request count and wall time drop, tool menu breadth is causal.

4. **Prompt-pressure ablation**

   Reduce persistence/verification pressure in a controlled variant. Compare
   repeated searches, retries, and final success.

5. **Observer improvement**

   Split Pi stdout event-stream bytes from actual command output bytes, and
   capture Pi runtime `models.json` into `agent_context.json` after the wrapper
   writes it.

6. **Statistical rerun**

   Run N=3 or N=5 for the most informative tasks: Redis conditional-expire,
   Linux string tests, and one lighter Redis QA task.

## Reproduction Commands

Pi DeepSeek:

```bash
DEEPSEEK_API_KEY="$ANTHROPIC_AUTH_TOKEN" PI_DEEPSEEK_MODEL=deepseek-v4-pro \
  python -m orchestrator.matrix --config harness_config_redis_linux_pi_deepseek.json
```

Codex DeepSeek:

```bash
CODEX_DEEPSEEK_MOONBRIDGE=1 CODEX_MODEL=moonbridge \
  CODEX_PROVIDER_BASE_URL=http://127.0.0.1:38440/v1 \
  MOONBRIDGE_DEEPSEEK_MODEL=deepseek-v4-pro \
  python -m orchestrator.matrix --config harness_config_redis_linux_codex_deepseek.json
```

Claude Code DeepSeek pro-forced:

```bash
ANTHROPIC_MODEL='deepseek-v4-pro[1m]' \
ANTHROPIC_DEFAULT_OPUS_MODEL='deepseek-v4-pro[1m]' \
ANTHROPIC_DEFAULT_SONNET_MODEL='deepseek-v4-pro[1m]' \
ANTHROPIC_DEFAULT_HAIKU_MODEL='deepseek-v4-pro[1m]' \
CLAUDE_CODE_SUBAGENT_MODEL='deepseek-v4-pro[1m]' \
python -m orchestrator.matrix --config harness_config_redis_linux_claude_deepseek_pro.json
```

Primary detailed source report:

- `runs/redis_linux_matrix_summary_deepseek_with_pi_20260601.md`

