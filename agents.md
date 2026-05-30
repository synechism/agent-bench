# Agent Harness Resource Benchmarking Platform — Status & Context

This document is written for a future Claude instance picking up this project. It covers
motivation, architecture decisions, what's implemented, what's verified vs. placeholder,
and the exact next steps.

## What this project is

An agent-agnostic platform that faithfully measures coding agents' resource consumption
(RAM, CPU, disk I/O) and attributes it to the *specific subprocesses responsible* —
tool calls (rg, grep, make, cargo, pytest, ...), test/build runners, auxiliary models, etc.
Not just a single opaque "the agent used 4GB" number.

The CTO-level framing: the interesting measurement is per-subprocess attribution, not
total overhead. Cross-process consumption (distinct PIDs) is solvable agent-agnostically
and requires zero agent source changes. Intra-process attribution (conversation vs skills
vs in-process embeddings sharing one PID) requires per-agent heap profiling and is
explicitly deferred to week 3+.

## Design thesis (from the spec)

Six consumption categories split into two measurement problems:

| Category | Where it lives | Measurement technique |
|---|---|---|
| Tool calling (rg, cat, make, pytest, cargo) | Cross-process (distinct PIDs) | Process-tree accounting + spawn tracing |
| Test/build runners | Cross-process | Same — this is where OOMs live |
| Auxiliary models | Either (sidecar vs in-process) | Subprocess accounting if sidecar; ablation if in-process |
| In-memory embedding/indexing | Either | Same |
| Conversation/context memory | Intra-process (one PID) | Heap profiling OR ablation (deferred) |
| Skills | Intra-process | Ablation: toggle on/off, diff curve (deferred) |
| Runtime/language overhead | Baseline | Empty-task footprint = the floor |

**The all-agents-from-day-one decision is cheap** because the measurement layer is
PID-based and agent-blind. Cost scales with adapters, not architecture.

## Architecture

```
ORCHESTRATOR → iterates run matrix (agents × codebases × tasks × caps × N)
    ↓ dispatches one isolated run, or a bounded parallel batch for iteration
RUN (one VM/container)
    ├── ADAPTER (per-agent, the only agent-specific component)
    │     install + invoke + auth + pinning
    └── MEASUREMENT LAYER (agent-agnostic)
          • /proc sampler (PSS/USS/RSS tree, 0.25s interval)
          • execsnoop (bcc/bpftrace, catches every exec() regardless of lifetime)
          • PATH shims (intercepts tool invocations, records name+argv+timing)
          • per-proc cgroup (kernel-accurate memory.peak, week 2 upgrade)
    → writes runs/<run_id>/
ANALYSIS → join timeseries + exec/exit + events on (pid, ts)
        → per-category attribution → aggregate across N runs → distributions
```

## Adapter contract (`adapters/base.py`)

Every agent implements `AgentAdapter` (ABC):

```python
class AgentAdapter(ABC):
    name: str            # "claude_code" | "codex" | "pi" | "opencode"
    version: str         # pinned, recorded in manifest
    capabilities: AgentCapabilities  # headless, pin_model, pin_temperature, pin_seed

    docker_image() -> str          # prebuilt image tag
    env() -> dict[str, str]        # auth + config, secrets from host env
    pin_flags() -> list[str]       # model + temp/seed reproducibility flags
    build_command(TaskSpec) -> list[str]  # NON-INTERACTIVE command, runs to completion
    local_command(TaskSpec) -> list[str]  # variant for local (non-Docker) execution
```

Key design points:
- API keys are NEVER hard-coded. They use `${VAR}` syntax expanded at run time from the
  host environment.
- `pin_flags()` returns flags that pin model and reproducibility knobs. If an agent
  can't pin temperature or seed, that's recorded in `capabilities` as a caveat.
- `build_command()` must produce a non-interactive run that exits cleanly. This is the
  day-1 validation gate for every agent.

## What's built so far (May 2026)

### Project layout
```
agent-harness-bench/
├── pyproject.toml              # psutil, pandas, pyarrow, pydantic, typer, pyyaml, rich
├── harness_config.json         # default run matrix config
├── harness_config_redis_linux.json  # current Redis/Linux eval pack, Docker, parallel_jobs=1
├── Makefile                    # install, build, matrix, dry-run, summarize, aggregate
├── .gitignore                  # ignores runs/, __pycache__, *.parquet, *.csv, *.jsonl
├── README.md
├── agents.md                   # ← this file
│
├── adapters/
│   ├── __init__.py
│   ├── base.py                 # AgentAdapter ABC + TaskSpec, InvocationResult, AgentCapabilities
│   ├── claude_code.py          # claude -p <prompt> --model deepseek-v4-pro[1m] --output-format stream-json
│   ├── codex.py                # codex exec -m gpt-5.5 --json <prompt> (VERIFIED)
│   ├── pi.py                   # pi run --non-interactive (NOT YET VERIFIED)
│   └── opencode.py             # opencode run --yes (NOT YET VERIFIED)
│
├── measure/
│   ├── __init__.py
│   ├── proc_sampler.py         # /proc walker: PSS/USS/RSS + CPU tree → CSV → parquet
│   ├── execsnoop_wrap.py       # bpftrace → bcc execsnoop → Python fallback spawn logger
│   ├── cgroup.py               # cgroup v2 helpers: memory.peak, cpu.stat, resolve base path
│   └── shims/
│       └── _template.sh        # PATH-intercepting bash shim for per-tool attribution
│
├── orchestrator/
│   ├── __init__.py
│   ├── config.py               # Pydantic models: RunManifest, RunConfig, Caps, TaskDef, CodebaseRef
│   ├── matrix.py               # Cartesian product builder + sequential/parallel dispatcher
│   └── run.py                  # Single-run executor: Docker or local, starts measurement layer
│
├── docker/
│   ├── base.Dockerfile         # Ubuntu 24.04 + bpftrace + bcc + shims + Python harness
│   ├── claude_code.Dockerfile  # npm install @anthropic-ai/claude-code
│   ├── codex.Dockerfile        # npm install @openai/codex
│   ├── pi.Dockerfile           # npm install @earendil-works/pi-coding-agent (headless flags TBD)
│   └── opencode.Dockerfile     # npm install opencode-ai (placeholder — verify)
│
├── tasks/
│   ├── qa/
│   │   ├── redis_issue_12345.json
│   │   ├── redis_getex_expired_event.json
│   │   ├── linux_proc_thread_self.json
│   │   └── fastapi_routing_bug.json
│   ├── feature/
│   │   ├── redis_expire_conditional_options.json
│   │   ├── linux_string_get_size_return_length.json
│   │   └── ripgrep_add_max_filesize.json
│   └── tests/
│       ├── redis_getex_expired_event_tests.json
│       ├── linux_string_get_size_tests.json
│       └── redis_test_suite.json
│
├── codebases/
│   └── registry.yaml           # redis, historical Redis bases, linux_v6_6, fastapi, ripgrep, ...
│
└── analysis/
    ├── __init__.py
    ├── summarize.py            # One run → per-category attribution + files_grepped + peak PSS
    └── aggregate.py            # N runs → median/p90/max distributions + matplotlib charts
```

### Adapters: verified vs. placeholder

| Agent | Status | Headless command | Model pinning | Verified? |
|---|---|---|---|---|
| **Claude Code** | VERIFIED | `claude -p <prompt>` | `--model deepseek-v4-pro[1m]` | Yes — run on this machine |
| **Codex** | VERIFIED | `codex exec <prompt>` | `-m gpt-5.5` | Yes — run on this machine |
| **Pi** | NOT VERIFIED | `pi run --non-interactive` | `--model gemini-2.5-pro` | No — CLI existence unknown |
| **OpenCode** | NOT VERIFIED | `opencode run --yes` | `--model ...` | No — CLI existence unknown |

### Claude Code adapter details (verified)
- Binary: `/home/abhi/.nvm/versions/node/v24.16.0/bin/claude`
- Headless: `-p, --print` prints response and exits
- Model: `--model deepseek-v4-pro[1m]` in this benchmark environment
- Provider: DeepSeek V4 through `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`
- Auto-approve: `--dangerously-skip-permissions`
- Budget cap: `--max-budget-usd 5` (only works with -p)
- No session persistence: `--no-session-persistence`
- Structured observer output: `--output-format stream-json --include-hook-events --verbose`
- Not available: temperature, seed, max-turns
- Auth: `ANTHROPIC_AUTH_TOKEN` for the DeepSeek Anthropic-compatible endpoint, or
  `ANTHROPIC_API_KEY` for first-party Anthropic/API-key environments
- Caveat observed: using `--model claude-opus-4-7` while the host is configured for
  DeepSeek can trigger `content[].thinking must be passed back` failures after tool use.

### Codex adapter details (verified)
- Binary: `/home/abhi/.nvm/versions/node/v24.16.0/bin/codex`
- Headless: `codex exec <prompt>` (non-interactive, runs to completion)
- Model: `-m, --model gpt-5.5` (most powerful as of May 2026)
- Auto-approve: `--dangerously-bypass-approvals-and-sandbox`
- Skip git check: `--skip-git-repo-check`
- Ephemeral: `--ephemeral` (don't persist session files)
- JSON output: `--json` (events as JSONL to stdout)
- Config: `-c, --config <key=value>` overrides `~/.codex/config.toml`
- The user runs Codex through Azure OpenAI with a config.toml like:
  ```toml
  [model_providers.azure]
  name = "Azure OpenAI"
  base_url = "https://cronwell-codex-2.openai.azure.com/openai/v1"
  env_key = "AZURE_API_KEY"
  wire_api = "responses"
  ```
- Model migrations in config: `"gpt-5.3-codex" = "gpt-5.4"` (auto-upgrade)
- Interactive model switching: `/model` slash command
- Not available: temperature (must set in config, not CLI flag), max-turns

### Pi adapter (placeholder — needs verification)
- Assumed CLI: `pi run --non-interactive`
- Public package: `@earendil-works/pi-coding-agent`
- Installed in Docker with Node 22.19.0 because the package requires modern Node.
- Still needs a smoke test for exact non-interactive/headless flags before it enters the matrix.

### Causal context / observer instrumentation
- Every local inner run writes `agent_context.json` before launching the agent.
- It records exact command, non-secret model/provider env, CLI version output, project
  instruction files, and available skill/plugin/agent/command inventories.
- The file reports available context, not proven model-loaded context. Actual loads require
  structured event logs or a prompt observer.
- Claude Code now emits `stream-json`; Codex now emits JSONL events. The next parser should
  build `decision_trace.jsonl` by joining assistant text immediately before each tool call to
  `tool_spans.jsonl`.
- For Claude Code system-prompt attribution, map `claude --version` to the versioned prompt
  inventory in `Piebald-AI/claude-code-system-prompts`.

### Docker image validation (May 29, 2026)
- Built `agent-harness/base:latest`, `agent-harness/claude_code:latest`,
  `agent-harness/codex:latest`, `agent-harness/pi:latest`, and
  `agent-harness/opencode:latest` on the VM.
- Smoke-checked versions inside containers:
  - Claude Code: `2.1.156`
  - Codex CLI: `0.135.0`
  - Pi: `0.77.0`
- `harness_config_redis_linux.json` is set to Docker mode with `parallel_jobs=1`
  for robust sequential measurement.

### OpenCode adapter (placeholder — needs verification)
- Assumed CLI: `opencode run --yes`
- Open-source coding agent. npm package name TBD.
- Verify both the package name and the headless invocation on day 1.

## Measurement layer details

### proc_sampler.py
- Walks `/proc` every `interval` seconds (default 0.25s)
- Reads PSS, USS, RSS from `/proc/<pid>/smaps_rollup` (single rollup line, cheaper than full smaps)
- Reads comm, ppid, utime, stime, num_threads, starttime from `/proc/<pid>/stat`
- Handles comm fields with spaces/parens by splitting on last `)` character
- Builds process tree each tick (PIDs churn — safe approach)
- Writes CSV (fast append, human-readable); caller converts to parquet at run end
- Stops when root PID exits or on SIGTERM/SIGINT
- **Known gap**: 0.25s sampling misses ~50ms tool calls. strace/execsnoop/shims cover those.

### PATH shims (_template.sh)
- Symlinked as `rg`, `grep`, `cat`, `make`, `pytest`, `cargo`, `node`, `python`, etc.
- Each shim: logs (tool, argv, pid, start_ts), optionally places process in per-tool cgroup,
  execs the real binary, logs (end_ts, exit_code) on return.
- **Zero agent source changes required** — identical across all four agents.
- Finds the real binary by temporarily removing the shim dir from PATH and running `command -v`.
- **Caveat**: agents that call binaries by absolute path bypass PATH and skip the shim.
  execsnoop runs alongside as the safety net. Reconcile both logs in analysis.

### execsnoop_wrap.py
Three-tier fallback:
1. **bpftrace** (preferred): `tracepoint:syscalls:sys_enter_execve` — logs every exec()
   with argv, pid, ppid, timestamp. Runs for the duration of the run.
2. **bcc execsnoop** (fallback): `/usr/share/bcc/tools/execsnoop` — same capability,
   different implementation. Parse its output into jsonl.
3. **Python fallback** (last resort): polls `/proc/<pid>/children` recursively to detect
   new PIDs. Catches PIDs but NOT argv. Only for when neither bpftrace nor bcc are available.

### Rootless strace exact exec capture
- Local runs use `strace -f -qq -ttt -s 4096 -e trace=execve -o strace_exec.log -- <agent>`
  when `strace` is installed and `HARNESS_STRACE_EXEC` is not `0`.
- This is currently the exact-argv path on the benchmark VM because eBPF exec tracing needs root.
- `analysis/summarize.py` parses `strace_exec.log` into:
  - `claude_shell_command`: Claude Code shell-wrapper commands such as `make ... | tail ...`.
  - `claude_internal_tool`: Claude Code internal `claude.exe` launches with argv like `rg ...`.
  - `strace_execve`: exact subprocess execs that are not promoted to high-level tool commands.
- Strace adds overhead. Use it for exact accounting; rerun every compared agent under the same
  tracing mode before treating execve subprocess counts as cross-agent apples-to-apples numbers.

### cgroup.py (week 2 upgrade)
- Resolves cgroup base path generically via `/proc/<pid>/cgroup` — works with both
  cgroupfs v1, v2, and systemd.
- Creates per-tool per-process cgroup directories.
- Reads `memory.peak` (kernel-accurate peak memory, no sampling gap) and `cpu.stat`
  after process exit.
- This is the jump from "sampled estimate" to "ground truth" for cross-process categories.

## Task modalities

| Modality | What the agent does | Resource profile | Oracle |
|---|---|---|---|
| **qa** | Investigates which files are relevant to a bug | Tool-calling heavy (rg, grep, cat, git) | Ground-truth relevant files from the PR that fixed the issue |
| **feature** | Implements a feature from N-1 changelog | Tool + test/build mixed | Real diff from release N or release-N tests |
| **tests** | Runs the test suite | Dominated by test/build runners; where OOMs live | Exit code + known passing tests |

QA tasks are curated by: Claude reads codebase + mines long-discussion GitHub issues
(long threads are genuinely multi-file and have a known resolution).

Feature tasks use the "dial-back" method: checkout release N-1, read changelog for a
feature added in N, ask agent to implement it, score against real diff or release-N tests.

## Parallelism model

Sequential dispatch is still the cleanest mode for publication-quality comparisons:
`parallel_jobs=1` means one run owns the host at a time, so wall time and CPU are not
contended by another benchmark cell.

Parallel dispatch is now supported for iteration:

```bash
python -m orchestrator.matrix --config harness_config_redis_linux.json --jobs 2
```

This is measurement-safe for memory attribution because every cell has:
- its own run directory
- its own manifest and logs
- its own agent root PID
- its own `/proc` sampler scoped to that root PID and descendants
- its own PATH shim directory and `EXEC_SHIM_LOG`
- its own fallback descendant tracker

What gets noisier under `jobs > 1`:
- wall time
- CPU scheduling and CPU counters
- disk I/O and checkout time
- network/API latency under load
- shared page-cache effects

What remains meaningful:
- per-process sampled PSS/USS/RSS
- per-run peak tree memory
- exact tool calls when transcript/shim/execsnoop data exists
- observed subprocess counts
- outcome/setup/failure phase fields

Operational recommendation:
- Use `jobs=2` on this VM for quick Redis/Linux iteration.
- Use `jobs=1` for final numbers or when comparing wall time.
- If we later add cgroup CPU quotas or CPU affinity, parallel wall-time comparisons become
  more defensible, but still need a "contended run" caveat in the report.

## Faithfulness controls

- **Distributions, never point estimates**: N=5 reps per cell, inspect spread, adjust.
  Report median, p90, max. Max matters most — OOMs happen at the peak.
- **Control for API offloading**: log tokens (in/out/cached), API call count, network-wait
  seconds alongside local resource use via `api_usage.json`.
- **Normalize by task success**: every run needs a pass/fail oracle. Resource numbers
  only comparable across runs that succeeded.
- **Isolation**: for final runs, prefer one active cell per VM/container. For iteration,
  bounded parallelism is acceptable because attribution is per process tree, but mark wall
  time and CPU as contended.
- **Empty-task baseline**: each agent's runtime/language overhead = run with a no-op task.
  This is the floor — subtract it to see incremental cost.

## Data model

```
runs/<run_id>/
  manifest.json            # agent+version, task, codebase@commit, caps, seed, hardware
  proc_timeseries.parquet  # ts, pid, ppid, comm, pss, uss, rss, utime, stime, num_threads
  exec_log.jsonl           # every spawn: ts, pid, ppid, argv, source=shim|execsnoop
  strace_exec.log          # rootless exact execve trace when HARNESS_STRACE_EXEC is enabled
  exit_log.jsonl           # ts, pid, exit_code, ru_maxrss, ru_utime, ru_stime
  events.jsonl             # semantic markers (ablation toggles, phase boundaries)
  api_usage.json           # tokens in/out/cached, call count, network-wait seconds
  summary.json             # derived: peak tree PSS, per-category breakdown, files_grepped, success
  tool_events.jsonl        # normalized tool events from shims/transcripts/proc fallback
  orchestrator.log         # matrix child log for parallel dispatch
  stdout.log / stderr.log
```

`run_id` convention: `<timestamp>_<agent>_<codebase>_<task>_<mem-cap>_<rep>` — sortable, self-describing.

## Key edge cases handled

- **PID reuse**: key process identity on `(pid, starttime_from_stat_field_22)`, not pid alone.
- **comm with spaces/parens**: parse `/proc/<pid>/stat` on last `)` character.
- **Absolute-path tool calls bypass shims**: execsnoop is the safety net; reconcile both logs.
- **Claude Code internal tools bypass shell transcripts**: rootless strace catches `claude.exe`
  invocations where argv[0] is the actual tool, e.g. `rg`.
- **cgroup path differs by driver**: resolve generically via `/proc/<pid>/cgroup`.
- **Swap hides OOM pressure**: disable or measure, never ignore.
- **Page cache warmth varies between runs**: fix the policy (cold or warm) and record it.
- **Network-bound agents look artificially cheap**: api_usage.json controls for this.

## Next steps (prioritized)

### Immediate — day 1 validation gate
1. **Verify Pi CLI**: Does `pi` have a headless mode? If not, CTO conversation.
2. **Verify OpenCode CLI**: Does `opencode` have a headless mode? What's the npm package name?
3. **End-to-end smoke test**: Run one adapter through the full pipeline:
   ```
   python -m orchestrator.run runs/<test_run>/manifest.json
   ```
   Verify that the manifest, proc timeseries, exec log, events, and summary are all
   produced correctly.

### Week 1 — measurement layer end-to-end
4. **Test proc_sampler against a real agent run**: Run `claude -p "find all Python files"` and
   verify the sampled PSS tree matches `htop`/`docker stats` within a sane margin.
5. **Test PATH shims**: Set up the shim dir, run an agent, verify exec_log.jsonl shows
   tool invocations with correct (tool, argv, pid, timing).
6. **Test execsnoop**: Run bpftrace alongside, verify it catches at least one spawn
   the shims missed (e.g., an absolute-path call).
7. **Derive files_grepped**: On a small Q&A task, hand-count files grepped, verify the
   derived count from exec/shim logs matches.

### Week 2 — robustness + all agents + all modalities
8. **All four adapters live**: Get Pi and OpenCode adapters verified and running.
9. **Empty-task baselines**: Run each agent with a no-op prompt, chart the
   runtime/language overhead (Claude Code/TS vs Python agents).
10. **Three modalities on ≥2 codebases**: Fill out remaining task definitions.
11. **Memory cap failure modes**: Run test modality under intentional memory.max cap,
    characterize graceful degradation vs hard OOM crash.
12. **Repeated runs + aggregation**: Run N=5 reps per cell, produce first comparison
    chart (all four agents' peak tree PSS distributions on test modality,
    plus per-subprocess-category breakdown for one agent).

### Deferred (week 3+)
- Intra-process heap attribution (Node heap snapshots, Python memray)
- Full ablation matrix (conversation vs skills vs in-process embeddings)
- Heavier eBPF programs (hook sched_process_exit for ru_maxrss)
- Non-coding agents (Hermes, Openclaw)
- Linux kernel as a test codebase (needs 32GB+ RAM, not a day-1 target)

## Running locally vs Docker

Two paths exist in `orchestrator/run.py`:
- `_run_docker()`: Builds and runs the agent image in an isolated container with
  resource caps applied via Docker flags.
- `_run_local()`: Runs the agent directly on the host, starts the measurement layer
  (sampler, execsnoop, shims) as background processes, collects results.

Local execution gives more fine-grained control over measurement. Docker gives
stronger isolation guarantees. Both use the same adapter contract.

For local runs: the adapter's `local_command()` is invoked, the current process
becomes the cgroup root, and the agent process tree is monitored from the outside.

## Operational commands and notes from this VM

Current host facts:
- Hostname observed: `qwen-1xgpu`
- GPU: NVIDIA L40S, visible through `nvidia-smi`
- Python pinned locally via `.python-version`: `3.12.13`
- This repo is developed directly on the benchmark VM over SSH.

Install/check:

```bash
python -m pip install -e ".[dev]"
python -m ruff check .
python -m compileall -f analysis orchestrator measure adapters
```

Default matrix:

```bash
python -m orchestrator.matrix --config harness_config.json --dry-run
python -m orchestrator.matrix --config harness_config.json
```

Current Redis/Linux eval pack:

```bash
python -m orchestrator.matrix --config harness_config_redis_linux.json --dry-run
python -m orchestrator.matrix --config harness_config_redis_linux.json --jobs 2
```

Summaries and aggregates:

```bash
python -m analysis.summarize runs/<run_id>
python -m analysis.aggregate runs --output runs/aggregate.json --charts-dir runs/charts
```

Useful one-off inspection commands:

```bash
find runs -maxdepth 2 -name summary.json -printf '%h\n' | sort
git -C runs/<run_id>/codebase diff --stat
git -C runs/<run_id>/codebase diff --name-only
tail -40 runs/<run_id>/events.jsonl
head -20 runs/<run_id>/tool_events.jsonl
```

Parallel run behavior:
- Parallel matrix children write `orchestrator.log` so their output does not interleave.
- Each child is launched in its own process group; matrix-level timeout sends SIGTERM,
  waits briefly, then SIGKILLs the group if needed.
- Each local agent wrapper is also launched in its own process group. `orchestrator.run` tears
  that group down after normal exit/timeout so failed Claude/tool runs do not leave orphaned
  subprocesses behind.
- If a timeout kills `orchestrator.run`, the run may not have a final `summary.json`;
  inspect `orchestrator.log` and `events.jsonl`.

Large repo checkout behavior:
- `orchestrator.run` uses partial/shallow clones when possible.
- Linux tag tasks now use `git clone --filter=blob:none --depth 1 --branch v6.6`.
- SHA-pinned historical Redis bases use blobless partial clones.
- Full clone remains fallback if partial clone fails.

Redis/Linux run history:
- Full sequential-ish Redis/Linux pack took about an hour because the large feature cells
  dominated.
- First Claude pass missed exact tool argv for headless Claude and reported 0 exact tools.
- Fixed rootless strace + absolute shim paths + local process-group cleanup; clean Claude rerun
  prefix is `20260527T184018_claude_code_*`.
- New Claude Redis EXPIRE conditional-options feature: about 1443s wall, about 561 MB peak PSS,
  40 high-level agent tool commands, and 45515 exact execve subprocesses.
- Clean Codex rerun with the same rootless strace path is `20260527T193102_codex_*`.
- New Codex Redis EXPIRE conditional-options feature: about 981s wall, about 398 MB peak PSS,
  46 high-level agent tool commands, and 18512 exact execve subprocesses.
- New Claude Linux tasks: about 189s / 353s / 175s.
- New Codex Linux tasks: about 106s / 370s / 241s. The Codex
  `linux_string_get_size_tests` cell peaked around 4.4 GB PSS, likely from build/test activity.
- All 14 cells exited 0, but current `task_success` mostly means harness completion; the
  next needed step is a functional oracle runner that actually executes focused test/build
  commands and validates changed files.

Oracle philosophy:
- Do not require line-for-line equality with upstream patches.
- Upstream commits are grounding references and expected-scope hints.
- Prefer functional checks: focused regression tests, build targets, command output, then
  diff similarity as supporting evidence.

## How to add a new agent

1. Write `adapters/<agent>.py` implementing `AgentAdapter`
2. Write `docker/<agent>.Dockerfile` inheriting from `base`
3. Add the agent name to `harness_config.json` agents list
4. Run `make dry-run` to verify the matrix includes it
5. Verify the headless command on a trivial task before trust it for real runs

That's it. The measurement layer, orchestrator, and analysis need zero changes.
