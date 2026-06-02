# Handoff - Agent Harness Bench

Last updated: 2026-06-02 UTC.

## Project Purpose

This repo benchmarks coding-agent harnesses under controlled, Dockerized
experiments. The core research question has shifted from only measuring process
memory to understanding semantic memory: what exactly gets sent to the base
model, how much of the context window is static prompt/tooling versus retained
file/tool output, and which harness-layer choices cause different behavior.

The primary agents studied so far are:

- Claude Code, usually pointed at the DeepSeek Anthropic-compatible endpoint.
- Codex, also standardized to DeepSeek for some runs.
- Pi, added as a lighter-weight comparison agent.

The main target repos are Redis and Linux. The current most-developed task set
is Redis-focused, with QA, feature, tests, and empty-baseline tasks.

## Current Architecture

Run flow:

```text
harness config
-> orchestrator.matrix expands cells
-> orchestrator.run creates per-run Docker/local sandbox
-> adapter launches agent
-> measure layer observes process, tools, API traffic, and agent context
-> analysis scripts produce summaries, hotspots, decision traces, semantic context
```

Important directories:

- `adapters/`: agent-specific launch commands and env mapping.
- `orchestrator/`: run/matrix execution.
- `measure/`: process sampler, API observer proxy, shims, agent-context capture.
- `analysis/`: summaries, hotspots, decision traces, semantic context, prompt payload extraction.
- `tasks/`: benchmark task definitions.
- `codebases.yaml`: repo/commit registry.
- `harness_configs/`: run matrices.
- `docs/`: stable reports and instrumentation docs.
- `runs/`: generated run artifacts.

## Measurement Layers

Process/resource measurement:

- `measure/proc_sampler.py` samples process tree RSS/PSS/USS over time.
- `analysis/hotspots.py` and `analysis/summarize.py` derive run peaks and
  agent-isolated peaks.
- Build/test subprocess memory can dwarf agent memory. For semantic-memory
  comparisons, prefer `run_peak_agent_isolated` / agent-isolated PSS.

Tool/behavior measurement:

- PATH shims record shell tool invocations and command output.
- Claude stream-json events are parsed for exact Claude tool calls.
- Codex tool calls are reconstructed from API payloads and command traces.
- Derived instrumentation includes search behavior, repeated failures, output
  volume, and file/tool-output retention.

Semantic-memory measurement:

- `measure/api_observer_proxy.py` forwards model API traffic and records
  sanitized request/response metadata.
- With `HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1`, it stores sanitized prompt
  snippets and raw request-body captures.
- `analysis/semantic_context.py` turns `api_requests.jsonl` into per-request
  semantic layer timelines.
- `analysis/prompt_payloads.py` writes `prompt_payloads.jsonl` and a readable
  `prompt_payload_report.md` showing what strings were in each request.
- `analysis/semantic_aggregate.py` rolls up semantic metrics across runs.

## Key Artifacts

Codex semantic analysis:

- `docs/semantic_memory/codex_semantic_memory_analysis_20260601.md`
- `docs/semantic_memory/codex_representative_aggregate_20260601.md`
- representative runs:
  - `runs/20260601T202331_codex_empty_baseline_empty_task_nocap_rep0`
  - `runs/20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0`
  - `runs/20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0`
  - `runs/20260601T202331_codex_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0`

Claude Code semantic analysis:

- `docs/semantic_memory/claude_code_semantic_memory_analysis_20260602.md`
- `docs/semantic_memory/claude_representative_aggregate_20260602.md`
- representative runs:
  - `runs/20260602T000448_claude_code_empty_baseline_empty_task_nocap_rep0`
  - `runs/20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0`
  - `runs/20260602T000448_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0`
  - `runs/20260602T000448_claude_code_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0`

Other reports:

- `docs/reports/deepseek_docker_agent_experiment_report_20260601.md`
- `docs/reports/prompt_ablation_experiment_report_20260601.md`
- `docs/system_prompt_investigation_20260531.md`
- `docs/analysis_measure_scripts.md`

## Important Findings So Far

Codex:

- Empty baseline static semantic floor is about 49k chars / 12.3k approx tokens.
- Static floor breakdown: tool schema about 22.4k chars, base instructions about
  21.4k chars, developer context about 5.0k chars.
- Growth is mostly retained tool output/file snippets, not assistant prose.
- No compaction occurred in the representative Codex batch.

Claude Code:

- Empty baseline main prompt floor is about 85k chars / 21.3k approx tokens.
- The biggest fixed component is tool schema: about 74.4k chars across 27 tools.
- Claude Code also exposes a visible skills layer in the model-visible context.
- Redis feature max context reached about 272.6k chars / 68.1k approx tokens.
- In the max Claude feature request, retained tool output was about 109k chars,
  tool-call memory about 38k chars, and thinking memory about 34k chars.
- No compaction occurred in the representative Claude batch.

Cross-agent:

- Claude Code made fewer API requests/tool calls than Codex on the Redis feature
  task, but each request was much heavier.
- The difference is strongly harness/tooling-layer driven: tool schema size,
  prompt layers, skill inventory, thinking blocks, and tool result retention all
  differ even when the backend model is standardized.

## Claude Trace Status

The user asked whether Claude Trace was used. It was not used for the main
Claude semantic report. The report used our API observer, which is currently the
reliable source of exact request payloads.

Claude Trace investigation:

- Repo inspected: `badlogic/lemmy/apps/claude-trace`.
- It wraps Claude Code by running `node --require <interceptor> <claude js entrypoint>`.
- Current Claude Code npm package in Docker is `@anthropic-ai/claude-code@2.1.156`.
- That package resolves `claude` to a native binary path:
  `/usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe`.
- Claude Trace currently fails against this package with:

```text
TypeError [ERR_UNKNOWN_FILE_EXTENSION]: Unknown file extension ".exe"
```

Failed compatibility smoke run:

- `runs/20260602T003402_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0`
- It created a zero-byte `.claude-trace` JSONL and exited before model calls.

Current working-tree changes include an opt-in Claude Trace wrapper:

- `docker/claude_code.Dockerfile` installs `@mariozechner/claude-trace`.
- `adapters/claude_code.py` supports `CLAUDE_TRACE=1`.
- `orchestrator/run.py` passes `CLAUDE_TRACE` and `CLAUDE_TRACE_LOG_NAME` into Docker.
- `harness_configs/harness_config_claude_trace_redis_getex.json` is a smoke config.

These changes compile, but live Claude Trace interception does not yet work with
native Claude Code. A future instance should either:

- adapt Claude Trace to wrap/intercept the native binary's network calls,
- find/use an older JS-based Claude Code package if compatible with the benchmark,
- or generate Claude Trace-compatible JSONL/HTML from our observer logs.

Do not treat the failed trace smoke run as a valid benchmark data point.

## Current Working Tree

At the time of this handoff, uncommitted changes include:

- Anthropic/Claude semantic parsing in:
  - `measure/api_observer_proxy.py`
  - `analysis/semantic_context.py`
  - `analysis/prompt_payloads.py`
- Claude Trace opt-in attempt in:
  - `adapters/claude_code.py`
  - `docker/claude_code.Dockerfile`
  - `orchestrator/run.py`
- Docs:
  - `docs/analysis_measure_scripts.md`
  - `docs/semantic_memory/README.md`
  - `docs/semantic_memory/claude_code_semantic_memory_analysis_20260602.md`
  - `docs/semantic_memory/claude_representative_aggregate_20260602.{md,json,csv}`
- New configs:
  - `harness_configs/harness_config_semantic_claude_representative.json`
  - `harness_configs/harness_config_claude_trace_redis_getex.json`

`py_compile` passed for the touched Python files after the latest edits.

## Useful Commands

Run Codex semantic representative batch:

```bash
HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1 \
HARNESS_API_OBSERVER_CAPTURE_CHARS=500000 \
python -m orchestrator.matrix \
  --config harness_configs/harness_config_semantic_codex_representative.json
```

Run Claude semantic representative batch:

```bash
HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1 \
HARNESS_API_OBSERVER_CAPTURE_CHARS=500000 \
python -m orchestrator.matrix \
  --config harness_configs/harness_config_semantic_claude_representative.json
```

Aggregate semantic runs:

```bash
python -m analysis.semantic_aggregate \
  runs/<run1> runs/<run2> \
  --output-prefix docs/semantic_memory/<name>
```

Derive per-run semantic artifacts manually:

```bash
python -m analysis.semantic_context runs/<run_id>
python -m analysis.prompt_payloads runs/<run_id>
```

Rebuild images after harness code changes:

```bash
docker build -t agent-harness/base:latest -f docker/base.Dockerfile .
docker build -t agent-harness/claude_code:latest -f docker/claude_code.Dockerfile .
```

## Next Steps

Highest priority:

1. Decide what to do with the Claude Trace path. The live wrapper is blocked by
   native Claude Code. The fastest path to a useful UI may be exporting our
   observer logs to Claude Trace JSONL format and using Claude Trace's HTML
   generator.
2. Re-run a trace/observer validation once the trace path is fixed. Confirm the
   trace JSONL has nonzero request/response pairs and that counts match
   `api_requests.jsonl`.
3. Cleanly separate benchmark-valid runs from failed instrumentation smoke runs.
   The `20260602T003402...` run is instrumentation-debug only.

Research next steps:

1. Run controlled ablations on Claude Code:
   - restricted tool lists,
   - disabled skills where possible,
   - smaller read/search output limits,
   - system-prompt replacement/append experiments.
2. Compare semantic layers across Claude Code, Codex, and Pi on the same tasks
   and same base model.
3. Expand Redis/Linux task set using ground-truth historical patches.
4. Add semantic metrics that separate:
   - static prompt,
   - available tool schema,
   - loaded skill inventory,
   - file/tool output,
   - assistant visible reasoning,
   - hidden/provider-side cache effects if observable.
5. Investigate whether any agent/harness actually compacts on longer tasks.

Engineering next steps:

1. Add a clear `trace_artifacts` section to `summary.json` when Claude Trace or
   any future trace UI is enabled.
2. Add tests/fixtures for Anthropic payload parsing in `measure/api_observer_proxy.py`.
3. Add an observer-log sanitizer audit before committing prompt captures.
4. Consider ignoring or moving large run-local prompt reports if repo size grows.
5. Avoid printing process command lines that include API keys or auth tokens.

## Progress Since Handoff

2026-06-02 follow-up:

- Chose the observer-export path as the practical Claude Trace path. The live
  Claude Trace wrapper remains blocked by native Claude Code, but observer logs
  can now be exported to Claude Trace-compatible JSONL.
- Added `analysis/claude_trace_export.py`, which converts `api_requests.jsonl`
  request/response events into `.claude-trace/observer_api_trace.jsonl`, with
  optional `--html` generation through the installed `claude-trace` CLI.
- Added `HARNESS_TRACE_EXPORT=1` support in `analysis.summarize`; summaries now
  include `trace_artifacts` with observer/trace count validation when trace
  export or live Claude Trace artifacts are present. `HARNESS_TRACE_HTML=1`
  also attempts HTML generation.
- Added tests for Anthropic block/layer parsing and observer-to-trace export.
- Validation on
  `runs/20260602T000448_claude_code_empty_baseline_empty_task_nocap_rep0`
  exported 2 request/response pairs and matched the 2 observer API requests.

## Caveats And Safety

- Do not use leaked/unofficial Claude Code source unless the user explicitly
  insists and legal/ethical concerns have been addressed.
- Do not print secrets. Some Docker/env commands can expose API tokens in
  process lists.
- The current user is developing on a resource-constrained VM with an NVIDIA
  L40S available.
- Docker is important for experiment isolation and should remain the default
  sandbox for benchmark runs.
- Sequential runs are slower but currently preferred for robust first-pass
  measurements.
