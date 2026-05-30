# Behavioral Instrumentation Plan

This is the instrumentation plan for moving from "the run used X MB and made Y
tool calls" to "here is how the agent used the harness, which actions were
expensive, which tool patterns were effective, and where the memory went."

The raw meters we built today are the foundation:

- process-tree PSS/USS/RSS over time
- exact or observed subprocess/tool events
- stdout/stderr/transcript logs
- run manifests and task metadata
- summaries with total peak memory, wall time, and tool counts

The next layer should explain agent behavior in detail.

## Core Questions

The instrumentation should let us answer questions like:

- Which model/system-prompt/skill context was in scope when a costly tool call
  was made?
- Did a tool-heavy behavior come from a base-model response, a system prompt,
  a project instruction file, a skill/plugin, or harness/bootstrap behavior?
- Which exact tool calls caused the memory peak?
- Was the peak from the agent runtime, a search/read command, a build/test
  command, a package manager, a language server, or the harness itself?
- Did the agent issue many narrow searches, a few broad searches, repeated
  duplicate searches, or expensive whole-repo commands?
- Did tool calls produce useful signal, or did they return empty/noisy output?
- Did the agent inspect the right files before editing?
- Did the agent run tests before and after editing?
- Which skills, MCP servers, wrappers, shims, or adapter components were active?
- How much memory is fixed overhead versus task-specific tool activity?
- How do successful and failed runs differ behaviorally?

## Current Signals We Can Build On

Existing artifacts:

```text
runs/<run_id>/
  manifest.json
  stdout.log
  stderr.log
  structured_events_observed.jsonl
  events.jsonl
  exec_log.jsonl
  strace_exec.log
  tool_events.jsonl
  proc_timeseries.parquet
  summary.json
  agent_context.json
  docker_run.json
  docker_image.json
  codebase/
```

Current strengths:

- PSS/USS/RSS sampling gives the total memory shape of the agent process tree.
- `strace_exec.log` gives exact argv for subprocesses.
- shims give structured records for common commands when PATH interception
  catches them.
- Codex transcript parsing recovers high-level shell commands.
- Claude Code attribution from strace recovers shell wrapper commands and
  internal `claude.exe` tool launches.
- `tool_events.jsonl` already normalizes some of this into one event stream.
- `agent_context.json` records command/model env, project instruction files,
  and skill/plugin/agent inventories for causal analysis.
- `structured_events_observed.jsonl` timestamps structured stdout/stderr JSONL
  as it arrives, preserving the original stdout/stderr logs while adding
  observer wall-clock and monotonic timestamps.
- Docker runs record image/run metadata so container environment changes can be
  separated from agent behavior changes.

Current limitation:

- We count tools and measure total resource use, and new runs can join
  timestamped structured model/tool events to subprocess spans. Older runs
  remain coverage-only if they lack `structured_events_observed.jsonl`.
- We can observe the tool call and available surrounding context, but we cannot yet prove
  whether the trigger was base-model prior behavior, the agent system prompt,
  a loaded skill, or project instructions. Observer timestamps narrow the
  trigger window, but attribution still requires ablations.
- `agent_context.json` reports available skill/plugin/agent/command inventories.
  It does not claim those components were loaded into the model context unless
  the agent's structured event stream explicitly says so.

## Causal Context Instrumentation

The new question from Tom is not only "what was expensive?" but "what caused
the agent to choose that expensive action?"

For each run, write `agent_context.json` with:

- the exact headless command and pinned model flags
- non-secret model/provider environment such as base URLs and model aliases
- CLI version outputs
- project instruction files such as `CLAUDE.md` or `AGENTS.md`
- home/project skill, command, agent, plugin, and MCP-like inventories
- hashes and sizes for prompt/config files, not raw secrets
- an explicit `load_observability` field that separates available context from
  actually observed model-context loads

This lets us correlate later behavior with context features:

- number of skills/plugins available
- project instruction files present
- whether subagents or command packs were installed
- whether a known system-prompt inventory exists for the installed agent version
- whether the run used Docker image A or B

Known references:

- Claude Code: use the version-indexed
  `Piebald-AI/claude-code-system-prompts` inventory to map installed Claude
  Code versions to known system prompt/tool/subagent prompt fragments.
- Pi: use it as a deliberately lightweight contrast agent; fewer tools/prompts
  should make action triggers easier to inspect.
- DeepSeek-TUI: candidate Rust-based contrast agent for a smaller runtime and
  more inspectable source/behavior.

Observer layer now implemented:

- force structured agent logs where available (`--json`, `stream-json`, or
  equivalent). Future Claude runs now use `stream-json`; future Codex runs now
  use JSONL events.
- timestamp each structured stdout/stderr JSONL event at capture time in
  `structured_events_observed.jsonl`
- parse assistant/tool events immediately before each tool span
- join "assistant/tool event happened at T" to the next subprocess span
- produce `decision_trace.jsonl` and `decision_trace_summary.json` with
  observed trigger counts

Validated smoke:

- `20260529T175028_claude_code_empty_baseline_tool_observer_smoke_nocap_rep0`
  asked Claude to run exactly `pwd`.
- The observer timestamped 7 structured events, including the `Bash` tool_use
  at observer offset 4.301s.
- The decision trace linked that tool_use to the resulting `bash`/`cat`
  subprocess spans, with 3 observed triggers out of 9 non-bootstrap spans.

Next observer upgrade:

- record whether the trigger appears to be explicit user prompt text, project
  instruction text, tool output feedback, or agent/system policy phrasing
- add prompt/skill ablation runs to test whether loaded skills or command packs
  change tool-choice behavior

This will still be correlational rather than a proof of causality, but it gives
us a much sharper indicator than resource traces alone.

## Standardization And Contrast Agents

The next benchmark axis should keep the base model as fixed as each agent
allows. Claude Code is already pinned to the DeepSeek Anthropic-compatible
model alias used in this environment. Codex currently needs provider/config
work before it can honestly be called a DeepSeek run; simply changing `-m` is
not enough unless the CLI is pointed at a compatible backend. Record the model,
base URL, image, and CLI version in `agent_context.json` for every run so mixed
model runs are obvious instead of silently pooled.

Two useful contrast agents:

- Pi: lightweight, fewer built-in behaviors, useful for seeing whether broad
  searches/tool-heavy behavior is coming from model priors versus rich agent
  scaffolding.
- CodeWhale/DeepSeek-TUI: Rust/DeepSeek-oriented candidate for a smaller runtime
  and easier source-level inspection.

## Planned Analysis Artifacts

Add derived artifacts that sit on top of the raw logs:

```text
runs/<run_id>/
  timeline.jsonl
  tool_spans.jsonl
  tool_span_summary.json
  resource_hotspots.json
  phase_summary.json
  file_activity.json
  harness_components.json
  behavior_summary.json
  decision_trace.jsonl
  decision_trace_summary.json
```

### `timeline.jsonl`

A single chronological stream with normalized events:

- run setup, checkout, agent start, agent exit, oracle start/end
- high-level agent actions from transcripts where available
- tool/subprocess start and end
- model/API request start and end when available
- file edit events
- memory peak markers
- timeout, OOM, retry, and failure events

This becomes the thing we can read when asking, "what happened during this
run?"

### `tool_spans.jsonl`

One record per high-level tool action or subprocess span:

```json
{
  "span_id": "tool-00042",
  "parent_span_id": "agent-00001",
  "source": "codex_transcript|claude_shell_command|shim|strace_execve|proc_observed",
  "tool": "rg",
  "category": "search",
  "argv": "rg \"expireIfNeeded\" src tests",
  "start_ts": 123.45,
  "end_ts": 124.02,
  "duration_s": 0.57,
  "pid": 1234,
  "exit_code": 0,
  "phase": "investigation",
  "files_touched": ["src/db.c", "tests/unit/expire.tcl"],
  "stdout_bytes": 4096,
  "stderr_bytes": 0,
  "peak_pss": 18350080,
  "pss_delta_at_start": 1048576,
  "pss_delta_at_peak": 7340032
}
```

The key move is joining `proc_timeseries` to tool windows by PID, process tree,
and time range. This lets us say "this `make test` span produced the memory
peak" instead of only saying "the run peaked at 793 MB."

### `resource_hotspots.json`

Ranked lists of expensive behavior:

- top tool spans by peak PSS
- top tool spans by CPU time
- top tool spans by wall time
- top command families by total subprocess fanout
- top phases by memory peak
- commands active during the run-level memory peak
- processes alive at peak, grouped by category

Example output shape:

```json
{
  "run_peak": {
    "ts": 664.2,
    "peak_tree_pss": 831700000,
    "active_spans": ["tool-00071", "subproc-1532"],
    "dominant_category": "test"
  },
  "top_memory_spans": [
    {"span_id": "tool-00071", "tool": "make", "peak_pss": 790000000}
  ]
}
```

### `behavior_summary.json`

Higher-level behavioral features for cross-agent comparison:

- total searches, reads, edits, builds, tests, package-manager calls
- duplicate or near-duplicate searches
- broad searches that scan the whole repo
- commands with empty output
- commands with very large output
- number of files read before first edit
- time to first edit
- tests run before first edit
- tests run after final edit
- number of edit/test cycles
- number of failed commands and retries
- command fanout: high-level command count versus exact subprocess count

This is where we start comparing styles, not just resource totals.

### `decision_trace.jsonl`

One record per non-bootstrap tool span with the nearest preceding structured
assistant/tool event. New runs get observer timestamps even if the agent's raw
JSONL does not include timestamps:

```json
{
  "span_id": "span-00042",
  "tool": "rg",
  "category": "search",
  "command": "rg \"expireIfNeeded\" src tests",
  "previous_assistant_event": {"kind": "assistant", "text": "I'll search for..."},
  "trigger_observed": true,
  "trigger_confidence": "timestamped_structured_tool_event"
}
```

When observer timestamps are absent, this artifact becomes a coverage report.
That is still useful for older runs: it tells us whether the current agent
invocation gave enough observability to investigate triggers at all.

## Tool Semantics

We should classify commands beyond the executable name.

Search:

- `rg`, `grep`, `find`, `fd`, `git grep`
- classify query string, path scope, file globs, ignore behavior
- detect whole-repo searches versus targeted searches
- count empty searches and repeated searches

Read:

- `cat`, `sed -n`, `head`, `tail`, editor-read tools
- identify files and line ranges
- count unique files read and repeated reads

Edit:

- direct file writes from agent tools
- shell writes such as heredocs, `python - <<`, `perl -pi`, `sed -i`
- patch applications
- count files changed and lines changed

Build/test:

- `make`, `cargo test`, `pytest`, `npm test`, project-specific test runners
- parse target names where possible
- capture pass/fail, failed test names, and reruns
- separate build-only from test execution

VCS:

- `git diff`, `git status`, `git log`, `git show`, `git checkout`
- distinguish read-only inspection from mutation

Package/network:

- `pip`, `npm`, `cargo fetch`, `curl`, `wget`, `apt`
- important because these can dominate time, memory, and network variance

Shell/wrapper:

- `bash`, `sh`, `zsh`, agent shell wrappers
- extract the inner command so we do not mistake "bash" for the actual work

## Phase Attribution

Add phase labels so resource use is explainable:

- `setup_checkout`
- `agent_boot`
- `investigation`
- `editing`
- `build`
- `test`
- `oracle`
- `cleanup`

Initial phase inference can be heuristic:

- before first code edit: `investigation`
- command categories `build` and `test` override phase
- after first edit and before test: `editing`
- post-agent validation: `oracle`

Later we can improve this with adapter-specific transcript parsing.

## Skill And Harness Component Attribution

Tom's question about instrumentation should also cover the harness and agent
components, not only external tools.

Track these components separately:

- agent main process
- adapter wrapper
- shell wrapper
- PATH shim overhead
- strace overhead
- proc sampler overhead
- Docker/container runtime overhead
- MCP servers or agent skill processes
- language servers or background indexers
- oracle runner

For each component, record:

- process identity and command line
- parent/child relationship
- active time window
- peak PSS/USS/RSS
- CPU time
- subprocesses spawned

This lets us say whether memory is coming from the coding agent itself, a
skill/server it launched, a build/test process, or our measurement harness.

## Output And Result Semantics

Tool behavior is only meaningful if we know what came back.

For shell commands where we control stdout/stderr capture, record:

- stdout/stderr byte counts
- first and last few lines for diagnostics
- exit code
- timeout/signal status
- parsed count of search matches where easy
- parsed count of test failures where easy

For privacy and size, store full raw output in existing logs and put summaries
in `tool_spans.jsonl`.

Useful derived metrics:

- searches with zero matches
- searches with excessive matches
- reads of files that were later edited
- tests that failed then passed
- repeated failures with no changed files between attempts
- command output volume per successful task

First-pass status: these are now emitted in `behavior_metrics.json` and embedded
under `summary.json["behavior"]["derived_metrics"]`. Existing runs have partial
coverage: Codex output volume can be inferred from transcripts, while older
Claude runs lack per-command output byte counts. Future shimmed runs record
`stdout_bytes` and `stderr_bytes` when `HARNESS_CAPTURE_TOOL_OUTPUT=1`.
Each run also records coverage fields so reports can distinguish measured zeros
from unavailable signal.

Reliability caveat: these metrics intentionally filter common shell/bootstrap
and compiler-probe noise, but they are still behavioral indicators rather than
final scoring signals. In particular, `tests_failed_then_passed` only counts
task-like test commands, not configure/compiler probe failures. Repeated-failure
metrics are not evaluated unless source-edit timestamps are available.

## Joining Resource Data To Tool Spans

The basic algorithm:

1. Parse `strace_exec.log`, shim logs, and transcripts into candidate spans.
2. Deduplicate overlapping records for the same PID/start time/argv.
3. Build a process tree keyed by `(pid, starttime)` from `proc_timeseries`.
4. Assign each sampled process row to the innermost active tool span where
   possible.
5. Roll up PSS/USS/RSS and CPU by span, category, and phase.
6. Mark which spans were active at the global peak.
7. Emit hotspot and behavior summaries.

Some spans will not have exact end times at first. For those, infer an end time
from the last sampled timestamp for that PID or from the next transcript event.
Mark confidence explicitly.

## Model And API Behavior

To keep model choice from polluting the tool-behavior comparison, standardize
on `deepseek-v4-pro` wherever possible.

Instrumentation to add:

- model name, provider, API compatibility mode, and proxy route
- API request count and latency
- input/output/reasoning/cached tokens when available
- retry/rate-limit/error counts
- time spent waiting for model responses

This lets us split "agent was slow because it was thinking/API-bound" from
"agent was slow because it ran expensive local tools."

## Immediate Implementation Plan

1. Build `analysis/tool_spans.py`. **First pass implemented.**
   - Input: existing `tool_events.jsonl`, `strace_exec.log`,
     `proc_timeseries.parquet`, stdout/stderr/transcripts.
   - Output: `tool_spans.jsonl`.

2. Build `analysis/hotspots.py`. **First pass implemented.**
   - Input: `tool_spans.jsonl` and `proc_timeseries.parquet`.
   - Output: `resource_hotspots.json`, `phase_summary.json`.

3. Extend `analysis/summarize.py`. **First pass implemented.**
   - Include top memory spans, top wall-time spans, command categories, and
     active spans at peak in `summary.json`.

4. Add attribution confidence fields. **First pass implemented.**
   - `span_role`: coarse behavioral role such as `agent_runtime`, `build`,
     `test`, `search`, `read`, `edit`, `bootstrap`, or `shell_wrapper`.
   - `attribution_confidence`: `high`, `medium`, or `low`.
   - `active_at_peak`: whether the span was active at the run-level sampled
     memory peak.
   - `includes_descendants`: whether the span's memory rollup includes child
     processes.
   - `is_nested_parent`: whether the span overlaps inner spans and should be
     read as a parent/wrapper span.
   - `possible_over_attribution`: whether the span is useful for identifying
     what was active at peak, but may include descendants or overlapping work.

5. Add file/diff activity capture after each run.
   - `diff.patch`
   - `diff_stat.json`
   - `changed_files.json`
   - first edit timestamp if inferable

6. Add oracle phase events.
   - Even before a full oracle runner exists, reserve event names and summary
     fields so phase attribution does not need another redesign.

7. Add component attribution rules.
   - Identify sampler, strace, shims, adapter wrapper, agent process, MCP/skill
     servers, language servers, build/test runners, and shell wrappers.

## First Analyses To Run On Existing Data

Use the latest Claude and Codex Redis/Linux runs to produce:

- memory peak timeline for each run
- active command(s) at peak
- top 10 tool spans by peak PSS
- top 10 tool spans by wall time
- high-level tool commands versus exact subprocess fanout
- search/read/edit/build/test counts per task
- duplicate search counts
- files read before first edit
- test commands before and after edits

This gives Tom the "getting into the weeds" view without needing another full
benchmark run first.

## Reporting Shape

Each task report should have two layers.

Run-level table:

- success/failure
- peak PSS
- wall time
- high-level tool commands
- exact subprocesses
- model/API counts

Behavioral detail:

- what the agent did first
- files it inspected
- where it spent time
- what caused peak memory
- which tools dominated subprocess fanout
- whether tests/builds were run
- whether behavior was targeted or exploratory
- notable waste: duplicate searches, broad scans, repeated failed commands,
  huge outputs, package downloads, unnecessary full test suites

The result should read less like a profiler dump and more like a trace
analysis: "Claude found the right Redis files in three searches, then spent
most memory in `make test`; Codex performed more exploratory searches, generated
more subprocess fanout, and peaked during Linux test compilation."
