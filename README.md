## Architecture

```
matrix builder
  -> one run per agent x task x codebase x cap x repetition
    -> adapter invokes the agent in headless mode
      -> measurement layer watches the agent root PID and descendants
        -> analysis summarizes one run
          -> aggregation compares cells and subtracts baselines
```

Each run writes:

```
runs/<run_id>/
  manifest.json
  agent_context.json
  docker_run.json
  docker_image.json
  stdout.log
  stderr.log
  events.jsonl
  exec_log.jsonl
  tool_events.jsonl
  decision_trace.jsonl
  decision_trace_summary.json
  proc_timeseries.csv
  proc_timeseries.parquet
  summary.json
  codebase/
```

## Measurement

Resource attribution is process-tree based. The runner starts the agent, records its root PID, and samples that PID plus descendants until the agent exits.

- `/proc` sampler: records PSS, USS, RSS, CPU counters, thread count, `comm`, `ppid`, and process start time at 0.25s intervals.
- PSS is the primary memory metric because it avoids RSS double-counting of shared pages.
- USS is recorded as the unique private footprint.
- PATH shims: per-run shims intercept common commands such as `rg`, `git`, `make`, `pytest`, `python`, `node`, and shell binaries, writing invocation records to that run’s `exec_log.jsonl`.
- Kernel exec tracing: if root-only `bpftrace`/BCC exec tracing is available, it records every `execve`.
- Rootless exec tracing: when `strace` is available, local runs wrap the agent with `strace -f -e trace=execve` and write exact argv to `strace_exec.log`.
- Non-root fallback: when eBPF is unavailable, the harness polls `/proc/<pid>/children` to observe descendants, and also parses transcripts/strace where possible.
- Transcript/trace attribution: Codex transcripts expose exact shell commands; Claude Code is attributed from strace, including shell commands and Claude's internal `claude.exe` tool launches.
- Host metadata: each manifest records CPU, RAM, swap, kernel, cgroup limits, and NVIDIA GPU inventory.
- Agent context: `agent_context.json` records the command, non-secret model/provider env,
  project instruction files, and available skill/plugin/agent inventories that may influence
  tool use. The artifact explicitly separates available context from actually observed loads.
- Structured agent streams: future Claude Code runs emit `stream-json`; future Codex runs emit
  JSONL events so we can join assistant decisions to the next subprocess/tool span.
- Docker metadata: Docker runs write `docker_run.json` and `docker_image.json` so container
  image identity is tied to the run.

Analysis combines these signals into:

- raw peak tree PSS/USS/RSS
- wall time
- per-category peak memory
- exact tool invocations when available
- observed subprocess counts when exact argv is unavailable
- outcome fields: `setup_ok`, `agent_started`, `agent_exit_code`, `timed_out`, `failure_phase`, `oracle_success`, `task_success`
- baseline-adjusted metrics in aggregate output

## Codebase Checkouts

Remote repositories are checked out per run for reproducibility. The runner uses partial/shallow clones when possible:

- tag/branch-like refs use `--filter=blob:none --depth 1 --branch <ref>`
- SHA-pinned refs use blobless partial clones
- full clone is retained as a fallback

This matters for large repositories such as Linux, where full history clone time would otherwise dominate iteration.

## Tasks And Oracles

Tasks live under `tasks/<kind>/*.json` and point at pinned codebases in `codebases/registry.yaml`.

Current task kinds:

- `baseline`: no-op runtime floor
- `qa`: investigate a bug and identify relevant files/root cause
- `tests`: write or run focused tests
- `feature`: implement a feature against an older checkout

## Current State

Verified local adapters:

- Claude Code using the DeepSeek Anthropic-compatible endpoint with `deepseek-v4-pro[1m]`
- Codex using `codex exec -m gpt-5.5`

Current benchmark packs include:

- empty baselines
- Redis GETEX expiration-event QA and test-writing tasks
- Redis EXPIRE `NX`/`XX`/`GT`/`LT` historical feature task
- Linux procfs `/proc/thread-self` QA task
- Linux `string_get_size()` test-writing task
- Linux `string_get_size()` v6.7 API backport task
- earlier FastAPI and ripgrep exploratory tasks

## Running

The most important commands are:

```bash
python -m orchestrator.matrix --config harness_config_redis_linux.json --dry-run
python -m orchestrator.matrix --config harness_config_redis_linux.json
python -m analysis.summarize runs/<run_id>
python -m analysis.hotspots runs/<run_id>
python -m analysis.behavior_metrics runs/<run_id>
python -m analysis.decision_trace runs/<run_id>
python -m analysis.aggregate runs --output runs/aggregate.json
```

`agents.md` is the operational notebook: adapter caveats, exact commands, VM details, run history, and next steps live there.

For the planned behavior/hotspot analysis layer, see [docs/instrumentation_plan.md](docs/instrumentation_plan.md).
