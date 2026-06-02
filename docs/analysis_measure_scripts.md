# Analysis And Measurement Scripts

This document explains how the scripts in `measure/` and `analysis/` fit
together. The short version:

```text
orchestrator.run
  -> measure/* records raw signals during one agent run
  -> analysis/summarize.py derives summary.json
       -> analysis/tool_spans.py derives tool_spans.jsonl
      -> analysis/hotspots.py derives resource_hotspots.json + phase_summary.json
      -> analysis/behavior_metrics.py derives behavior_metrics.json
      -> analysis/decision_trace.py derives decision_trace.jsonl
      -> analysis/semantic_context.py derives semantic_context_*.jsonl/json
      -> analysis/prompt_payloads.py derives prompt_payloads.jsonl + prompt_payload_report.md
      -> analysis/semantic_aggregate.py compares semantic metrics across runs
  -> analysis/aggregate.py combines many summary.json files across runs
```

The measurement layer is intentionally redundant. Some agents expose structured
tool calls, some only expose shell traces, and short-lived subprocesses can be
missed by `/proc` sampling. The harness combines all available signals and
marks attribution confidence where possible.

## Run Artifacts

A normal run directory looks like:

```text
runs/<run_id>/
  manifest.json
  events.jsonl
  stdout.log
  stderr.log
  structured_events_observed.jsonl
  agent_context.json
  api_requests.jsonl
  api_usage.json
  exec_log.jsonl
  strace_exec.log
  proc_timeseries.csv
  proc_timeseries.parquet
  tool_events.jsonl
  tool_spans.jsonl
  behavior_metrics.json
  resource_hotspots.json
  phase_summary.json
  decision_trace.jsonl
  decision_trace_summary.json
  semantic_context_timeline.jsonl
  semantic_context_summary.json
  prompt_payloads.jsonl
  prompt_payload_report.md
  .claude-trace/observer_api_trace.jsonl
  summary.json
```

Not every artifact exists for every run. For example, `strace_exec.log` requires
`strace`; eBPF exec logging requires root; `api_requests.jsonl` requires a
supported model API upstream; structured event logs require the agent to emit
JSONL-like events.

## Measurement Scripts

### `measure/proc_sampler.py`

Samples the agent process tree through `/proc`.

Inputs:

- root PID of the agent process tree
- output path, usually `proc_timeseries.csv`
- optional `--interval`, default `0.25` seconds
- optional `--parquet` output path

Outputs:

- one CSV row per sampled process per tick
- columns: `ts`, `pid`, `ppid`, `comm`, `pss`, `uss`, `rss`, `utime`, `stime`,
  `num_threads`, `starttime`
- optional parquet copy for faster analysis

What it measures:

- `PSS`: proportional set size, best default for shared-memory-aware memory
- `USS`: unique set size, process-private memory
- `RSS`: resident set size, useful but double-counts shared pages
- CPU ticks from `/proc/<pid>/stat`
- process tree shape through parent/child relationships

Limitations:

- Sampling can miss very short-lived processes.
- A 250 ms interval is good enough for run-level peaks but not exact exec
  accounting.
- This is why shims, strace, and execsnoop also exist.

Manual use:

```bash
python -m measure.proc_sampler <root_pid> runs/<run_id>/proc_timeseries.csv --parquet runs/<run_id>/proc_timeseries.parquet
```

### `measure/execsnoop_wrap.py`

Logs process spawns independently from `/proc` sampling.

Modes:

- `bpftrace`: uses the `sys_enter_execve` tracepoint.
- `execsnoop`: uses BCC execsnoop and converts its output to JSONL.
- `fallback`: recursively polls `/proc/<pid>/task/<pid>/children`.
- `auto`: tries bpftrace, then BCC execsnoop, then fallback.

Outputs:

- appends JSONL records to `exec_log.jsonl`
- records include timestamp, PID, PPID, command name, argv when available, and
  source

How `orchestrator.run` uses it:

- root-capable local runs try eBPF/BCC first
- non-root runs record an `execsnoop_unavailable` event and later start the
  fallback logger after the agent PID exists

Limitations:

- eBPF/BCC require privileges and host support.
- The fallback sees new PIDs but not full argv.
- Docker/container setups may limit visibility depending on privileges.

Manual use:

```bash
python -m measure.execsnoop_wrap runs/<run_id>/exec_log.jsonl --root-pid <pid> --method auto
```

### `measure/shims/_template.sh`

PATH shim template used to intercept common command-line tools.

How it works:

- `orchestrator.run` creates a per-run `shims/` directory.
- It symlinks common tools like `rg`, `git`, `make`, `pytest`, `python`,
  `node`, `bash`, and `sh` to this template.
- The shim finds the real binary later in `PATH`, logs invocation start/end to
  `exec_log.jsonl`, then executes the real command.

Logged fields:

- `tool`
- `argv`
- `pid`
- start/end timestamps
- exit code
- optional stdout/stderr byte counts when `HARNESS_CAPTURE_TOOL_OUTPUT=1`

Strengths:

- Gives exact start/end and exit code for commands that go through `PATH`.
- Can optionally capture output volume without changing the visible command
  output.

Limitations:

- Absolute-path tool calls bypass shims.
- Shell builtins do not appear as separate shim records.
- eBPF, strace, and transcript parsing fill those gaps.

### `measure/api_observer_proxy.py`

Redacting HTTP proxy for model API instrumentation.

What it captures:

- request/response counts
- status codes and errors
- observed model names
- request and response byte counts
- network wait time
- prompt-like character counts
- semantic layer sizes for OpenAI Responses API requests and Anthropic-style
  Claude `messages` requests
- per-input item type/role/layer counts
- advertised tool schema names
- in default mode, hashes and sizes of request bodies, not raw prompt/response
  text

Outputs:

- raw redacted event log: `api_requests.jsonl`
- aggregate summary written by `orchestrator.run`: `api_usage.json`
- readiness file: `api_observer_ready.json`

How `orchestrator.run` uses it:

- starts the proxy on a free localhost port
- rewrites the agent's API base URL to point to the proxy
- forwards traffic to the real upstream
- writes `api_usage.json` after the run ends

Important caveats:

- By default this is metadata instrumentation, not full prompt capture.
- For controlled open-source benchmark runs, set
  `HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1` and optionally
  `HARNESS_API_OBSERVER_CAPTURE_CHARS=<n>` to store sanitized prompt captures
  alongside the size/hash summaries.
- In capture mode, the proxy stores both semantic-field captures and a
  sanitized full request-body capture. This lets us inspect the exact
  API wrapper an agent sent, not only the extracted prompt strings.
- Codex may appear as `moonbridge` because Codex talks to a local bridge, which
  then routes to DeepSeek.
- Claude Code uses Anthropic-style payloads. The observer splits top-level
  `system`, `tools`, `messages`, assistant `tool_use` blocks, user
  `tool_result` blocks, and thinking blocks into semantic layers.
- Claude and Pi usually expose the final upstream model name directly.

Manual use:

```bash
python -m measure.api_observer_proxy \
  --listen-host 127.0.0.1 \
  --port 38441 \
  --upstream https://api.deepseek.com \
  --provider openai \
  --log runs/<run_id>/api_requests.jsonl \
  --ready-file runs/<run_id>/api_observer_ready.json
```

### Semantic Capture Env Vars

Use these only for controlled benchmark codebases where storing prompt text is
acceptable:

```bash
HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1
HARNESS_API_OBSERVER_CAPTURE_CHARS=200000
```

The proxy redacts obvious API-key/token/password/bearer patterns, but this is
still meant as an opt-in research mode.

### `measure/agent_context.py`

Captures available prompt/config/skill context for causal analysis.

Outputs:

- `agent_context.json`

What it records:

- command used to launch the agent
- non-secret model/provider environment variables
- project instruction files like `AGENTS.md` or `CLAUDE.md`
- agent versions
- available skills, commands, agents, plugins, extensions, prompt templates,
  and config files
- file sizes and hashes, not file contents

Agent-specific inventories:

- Claude Code: `.claude` settings, skills, agents, commands, and known external
  prompt inventory reference
- Codex: `CODEX_HOME`, config, model catalog, plugins, skills, project `.codex`
- Pi: Pi agent directory, models/settings, extensions, skills, prompt templates,
  themes
- generic agents: home/project dot-directories

Important caveat:

- This records what was available, not proof of what the model actually loaded.
  The API observer and structured event logs are needed to connect available
  context to actual run behavior.

### `measure/host_info.py`

Collects host metadata that can affect resource comparisons.

Outputs:

- embedded into `manifest.hardware`

Fields:

- platform, kernel, machine, Python version
- CPU model and logical core count
- total/available memory and swap status
- cgroup memory/CPU limits
- GPU name, UUID, memory, driver, and PCI bus ID via `nvidia-smi`

Use:

```python
from measure.host_info import collect_host_info
```

### `measure/cgroup.py`

Helpers for cgroup-based resource measurement.

What it provides:

- resolve the current process/container cgroup path
- create per-tool cgroups
- read `memory.peak`
- read `cpu.stat`
- clean up cgroup directories

Current status:

- The shim has support for placing each tool process in a per-tool cgroup when
  `CGROUP_BASE` is set.
- This is useful for future kernel-accurate per-tool peak memory, but current
  analysis still primarily uses `/proc` sampling plus shim/strace/observer
  evidence.

## Analysis Scripts

### `analysis/semantic_context.py`

Derives semantic context-window usage from `api_requests.jsonl`.

Outputs:

- `semantic_context_timeline.jsonl`
- `semantic_context_summary.json`

What it measures:

- base instruction chars/tokens
- system instruction chars/tokens
- tool schema chars/tokens
- developer/project context chars/tokens
- user task chars/tokens
- assistant/reasoning memory chars/tokens
- tool-call and tool-output memory chars/tokens
- file/tool-output contribution to carried context
- repeated static overhead from resending the same instruction/tool schema
- request-by-request context growth and deltas

Manual use:

```bash
python -m analysis.semantic_context runs/<run_id>
```

### `analysis/prompt_payloads.py`

Turns captured API requests into a prompt transcript.

Inputs:

- `runs/<run_id>/api_requests.jsonl`
- works best when `HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1` was enabled

Outputs:

- `prompt_payloads.jsonl`: one JSON object per model request with captured base
  instructions, tool schema, raw request body when available, and every input
  item/message block's captured payload.
- `prompt_payload_report.md`: readable markdown report with de-duplicated static
  blocks and per-request input items.

This is the script to use for the CTO question, "what exactly was in every
prompt?" `semantic_context.py` says how much each layer weighed;
`prompt_payloads.py` shows the strings that made up those layers.

Manual use:

```bash
python -m analysis.prompt_payloads runs/<run_id>
```

### `analysis/claude_trace_export.py`

Converts the harness observer log into Claude Trace's request/response-pair
JSONL shape.

Inputs:

- `runs/<run_id>/api_requests.jsonl`
- sanitized full request-body captures when they exist

Outputs:

- `.claude-trace/observer_api_trace.jsonl`

Notes:

- The exporter does not capture any new prompt text. It only reuses sanitized
  observer captures that already exist in `api_requests.jsonl`.
- Response bodies are not available from the harness observer today, so the
  exported response body contains response-size metadata instead of streamed
  model content.
- Set `HARNESS_TRACE_EXPORT=1` during `analysis.summarize` or a benchmark run
  to generate this artifact and add count validation under
  `summary.json["trace_artifacts"]`.
- Set `HARNESS_TRACE_HTML=1` as well to ask the installed `claude-trace` CLI to
  generate `.claude-trace/observer_api_trace.html`.

Manual use:

```bash
python -m analysis.claude_trace_export runs/<run_id>
python -m analysis.claude_trace_export runs/<run_id> --html
```

### `analysis/semantic_aggregate.py`

Aggregates semantic context metrics across runs so we can see patterns by task
type instead of inspecting one run at a time.

Inputs:

- run directories containing `summary.json` and `semantic_context_summary.json`

Outputs:

- `<prefix>.json`: full row data and rollups
- `<prefix>.csv`: spreadsheet-friendly row table
- `<prefix>.md`: readable summary with largest retained tool outputs

Important columns:

- `static_prompt_chars`: repeated base instructions, tool schema, task framing,
  and developer context at the largest request
- `carried_memory_chars`: history carried forward in the context window
- `file_or_tool_output_chars`: retained command output/file snippets
- `semantic_growth_chars`: growth from first request to largest request
- `agent_isolated_peak_pss_mb`: process-memory peak with build/test/package
  spans filtered out

Manual use:

```bash
python -m analysis.semantic_aggregate \
  --output-prefix docs/semantic_memory/semantic_context_aggregate
```

This is the primary artifact for semantic memory analysis. It complements
process memory rather than replacing it.

### `analysis/summarize.py`

Main single-run summary entry point.

Inputs:

- `runs/<run_id>/`
- expects any available raw artifacts: `manifest.json`, `proc_timeseries.*`,
  `exec_log.jsonl`, `strace_exec.log`, stdout/stderr logs, `events.jsonl`,
  `api_usage.json`, and `agent_context.json`

Outputs:

- `summary.json`
- also triggers downstream derived artifacts:
  - `tool_events.jsonl`
  - `tool_spans.jsonl`
  - `resource_hotspots.json`
  - `phase_summary.json`
  - `behavior_metrics.json`
  - `decision_trace.jsonl`
  - `decision_trace_summary.json`
  - `.claude-trace/observer_api_trace.jsonl` when `HARNESS_TRACE_EXPORT=1`

Key summary fields:

- peak tree PSS/USS/RSS
- wall time
- category-level memory attribution
- tool invocation counts
- files grepped/read
- API usage
- trace artifacts and observer/trace count validation when enabled
- agent context counts
- outcome classification
- top behavior/hotspot snippets

Tool event sources:

- structured Claude/Pi/Codex JSONL tool events
- Codex transcript command lines
- shim `exec_log.jsonl`
- strace `execve` records
- `/proc`-observed fallback subprocesses

Outcome classification:

- setup/checkout failure
- agent start failure
- timeout
- agent execution failure
- oracle success/failure when task oracle provides expected output or exit code

Manual use:

```bash
python -m analysis.summarize runs/<run_id>
```

### `analysis/tool_spans.py`

Builds the main analysis timeline: one span per command/tool/process.

Inputs:

- `exec_log.jsonl`
- `strace_exec.log`
- `tool_events.jsonl`
- `proc_timeseries.csv` or `proc_timeseries.parquet`
- `events.jsonl`

Output:

- `tool_spans.jsonl`

Each span includes:

- `span_id`
- source, kind, tool, category, role
- command/argv
- PID
- start/end time
- duration
- exit code
- stdout/stderr byte counts when known
- peak PSS/USS/RSS during the span
- CPU total
- sampled process fanout
- attribution confidence flags

Categories:

- `agent_runtime`
- `bootstrap`
- `search`
- `read`
- `edit`
- `vcs`
- `build`
- `test`
- `script`
- `package`
- `network`
- `shell`
- `other`

Attribution confidence:

- `high`: exact timing, sampled process data, no over-attribution warning
- `medium`: exact-ish but potentially nested or missing exact end time
- `low`: proc-observed fallback or no sampled process data

Important detail:

- Spans roll up descendants. A parent shell/build/test span can include child
  process memory, so spans can overlap. `possible_over_attribution` warns about
  this.

Manual use:

```bash
python -m analysis.tool_spans runs/<run_id>
```

### `analysis/hotspots.py`

Finds expensive spans and peak-time context.

Inputs:

- run directory
- uses existing `tool_spans.jsonl` or creates it
- uses `proc_timeseries.*`

Outputs:

- `resource_hotspots.json`
- `phase_summary.json`
- refreshes `behavior_metrics.json`

`resource_hotspots.json` includes:

- run-level peak time and peak PSS
- top processes at peak
- spans active at peak
- top memory spans
- top non-agent memory spans
- top high-confidence non-agent memory spans
- top wall-time spans
- top CPU spans
- top process-fanout spans
- duplicate commands
- first edit/test spans
- failed spans

`phase_summary.json` groups spans by category and records:

- span count
- peak PSS
- wall time sum
- CPU sum
- confidence counts
- possible over-attribution count

Manual use:

```bash
python -m analysis.hotspots runs/<run_id>
```

### `analysis/behavior_metrics.py`

Derives higher-level agent behavior metrics from `tool_spans.jsonl`.

Inputs:

- run directory
- `tool_spans.jsonl` or raw logs if spans must be regenerated
- git diff from `runs/<run_id>/codebase`
- structured file-access events when available
- Codex transcript output summaries when available

Output:

- `behavior_metrics.json`

Metrics:

- searches with zero matches
- searches with excessive matches
- reads of files later edited
- tests that failed then passed
- repeated failures with no detected edit between attempts
- command output volume
- coverage information for the metrics above

Search thresholds:

- excessive output bytes: `64 KiB`
- excessive output lines: `200`

Caveats:

- Output-volume coverage depends on shim output capture or transcript
  recoverability.
- Repeated-failure detection requires source-edit timestamps; otherwise it is
  intentionally conservative.
- Noise filters remove bootstrap/config checks that would otherwise pollute the
  metrics.

Manual use:

```bash
python -m analysis.behavior_metrics runs/<run_id>
```

### `analysis/decision_trace.py`

Builds a best-effort trace from observed model/assistant events to tool spans.

Inputs:

- `structured_events_observed.jsonl` when available
- otherwise structured JSONL from `stdout.log` and `stderr.log`
- `tool_spans.jsonl`

Outputs:

- `decision_trace.jsonl`
- `decision_trace_summary.json`

For each non-agent/non-bootstrap span, it records:

- span identity and command
- previous timestamped assistant event
- previous timestamped structured tool event
- whether a trigger was observed
- trigger confidence

Trigger confidence values:

- `timestamped_structured_tool_event`
- `timestamped_structured_assistant_event`
- `unobserved`

Caveat:

- This is evidence, not proof. It links the latest observable structured event
  before a command, but it cannot see hidden harness state or model internals.

Manual use:

```bash
python -m analysis.decision_trace runs/<run_id>
```

### `analysis/aggregate.py`

Aggregates many `summary.json` files into cell-level distributions.

Inputs:

- `runs/` directory containing run subdirectories with `summary.json`

Outputs:

- `runs/aggregate.json` by default, or `--output`
- optional charts under `runs/charts/` or `--charts-dir`

Grouping key:

- agent
- task
- codebase
- memory cap

Metrics aggregated:

- peak tree PSS/USS/RSS
- wall time
- files grepped
- tool invocations
- observed subprocesses

Statistics:

- median
- p90
- max
- min
- count

Additional logic:

- successful empty-task baselines are indexed by agent and memory cap
- non-baseline cells get baseline-adjusted memory/wall-time metrics
- success rates, oracle failures, timeouts, and failure phases are rolled up

Manual use:

```bash
python -m analysis.aggregate runs --output runs/aggregate.json
```

With charts:

```bash
python -m analysis.aggregate runs --charts-dir runs/charts
```

## Practical Workflows

### Reprocess One Run

```bash
python -m analysis.summarize runs/<run_id>
```

This is usually enough. It regenerates the main summary plus spans, hotspots,
behavior metrics, and decision traces.

### Rebuild Just Hotspot/Behavior Artifacts

```bash
python -m analysis.tool_spans runs/<run_id>
python -m analysis.hotspots runs/<run_id>
python -m analysis.behavior_metrics runs/<run_id>
python -m analysis.decision_trace runs/<run_id>
```

Use this when changing analysis logic and wanting to avoid touching the broader
summary.

### Aggregate A Full Matrix

```bash
python -m analysis.aggregate runs --output runs/aggregate.json
```

This assumes each run already has `summary.json`.

## Reading The Numbers Correctly

Use PSS as the main memory metric.

- RSS is familiar but over-counts shared pages.
- USS is useful for process-private memory but can understate shared runtimes.
- PSS is the best default for comparing agent process trees.

Treat per-span memory as attribution, not perfect ownership.

- Parent shell/build/test spans can include descendant processes.
- Overlapping spans can double-represent the same underlying memory if summed.
- Prefer top spans and peak-time active spans over naive total sums.
- Check `attribution_confidence` and `possible_over_attribution`.

Separate agent loop cost from project verification cost.

- Tool/API count reductions often reduce wall time.
- Peak memory can still be dominated by `make`, `gcc`, `ld`, `pytest`, or other
  repo-specific build/test fanout.
- This is exactly what showed up in the Redis hotspot ablations.

Use observer data to explain harness/prompt/tool surface differences.

- `api_usage.json` tells us which model names, prompt-like fields, and tool
  schemas were actually sent to the model-facing API.
- `agent_context.json` tells us what local prompts/skills/plugins were
  available.
- `decision_trace.jsonl` connects visible assistant/tool events to process
  spans when structured timestamps exist.

## Known Gaps

- `/proc` sampling can miss short-lived subprocesses.
- PATH shims miss absolute-path commands.
- eBPF exec tracing may be unavailable without privileges.
- Docker may limit what host-level tracing can see.
- The observer records redacted metadata, not raw prompt text.
- `agent_context.json` records available context, not guaranteed loaded context.
- Some agents expose richer structured events than others, so decision-trace
  coverage is agent-dependent.
