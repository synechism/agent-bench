# Prompt Ablation Experiment Report - 2026-06-01

This report summarizes the first prompt-swap ablations across Claude Code and
Codex, both still routed to DeepSeek V4 Pro in Docker.

The goal was to separate three causes of agent behavior:

1. base model,
2. system/base prompt,
3. harness/tooling layer.

The previous standardized DeepSeek runs already controlled the base model as
much as our harness can. These ablations start isolating the prompt and tool
surface.

## Prompt Sources

We cloned the two relevant public repos into `/tmp/agent-harness-src` for local
inspection:

- `Piebald-AI/claude-code-system-prompts`
- `openai/codex`

The prompt files used by the harness now live in:

- `prompt_ablations/codex_default_base_instructions.md`
- `prompt_ablations/claude_code_curated_system_prompt.md`

The Codex prompt file is copied from:

```text
openai/codex/codex-rs/protocol/src/prompts/base_instructions/default.md
```

The Claude prompt file is a curated bundle assembled from selected fragments in
Piebald's extracted Claude Code prompt inventory. It focuses on core
software-engineering behavior and Bash/Grep/Read/Edit/Write routing guidance,
not the entire 110+ string inventory.

## Harness Changes

New adapter controls:

- Codex: `CODEX_MODEL_INSTRUCTIONS_FILE=/prompt_ablations/...`
- Claude Code: `CLAUDE_SYSTEM_PROMPT_FILE=/prompt_ablations/...`
- Claude Code: `CLAUDE_TOOLS=...`
- Claude Code: `CLAUDE_DISABLE_SLASH_COMMANDS=1`

Docker now mounts the repo's `prompt_ablations/` directory read-only at
`/prompt_ablations` so prompt files can be used inside isolated runs.

## Ablation Cells

Baseline references:

- Codex baseline: `20260601T130454_codex_*`
- Claude baseline: `20260601T133859_claude_code_*`
- Pi baseline: `20260601T153943_pi_*`

Prompt ablations:

- Codex with Claude-style prompt:
  `20260601T170649_codex_*`
- Claude with Codex prompt:
  `20260601T171103_claude_code_*`
- Claude with Codex prompt and minimal tools:
  `20260601T172003_claude_code_*`

Smoke checks:

- Codex with Claude prompt:
  `20260601T170603_codex_empty_baseline_empty_task_nocap_rep0`
- Claude with Codex prompt:
  `20260601T170626_claude_code_empty_baseline_empty_task_nocap_rep0`

All ablation cells succeeded with exit code `0`.

## Results

| Label | Task | Success | Wall | PSS | Tools | API | API Wait | Payload |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| baseline_codex | empty_task | yes | 7.9s | 164.0 MB | 0 | 1 | 2.8s | 0.1 MB |
| codex_cc_prompt | empty_task | yes | 6.4s | 161.8 MB | 0 | 1 | 1.7s | 0.0 MB |
| baseline_claude | empty_task | yes | 3.6s | 279.4 MB | 0 | 2 | 6.0s | 0.1 MB |
| claude_codex_prompt | empty_task | yes | 3.9s | 273.5 MB | 0 | 2 | 5.4s | 0.1 MB |
| claude_codex_prompt_min_tools | empty_task | yes | 2.8s | 282.3 MB | 0 | 2 | 4.6s | 0.0 MB |
| baseline_pi | empty_task | yes | 2.8s | 162.9 MB | 0 | 1 | 2.2s | 0.0 MB |
| baseline_codex | redis_getex_expired_event_tests | yes | 377.6s | 163.4 MB | 68 | 72 | 363.8s | 9.1 MB |
| codex_cc_prompt | redis_getex_expired_event_tests | yes | 164.5s | 169.0 MB | 26 | 17 | 142.9s | 2.4 MB |
| baseline_claude | redis_getex_expired_event_tests | yes | 315.2s | 287.0 MB | 55 | 16 | 319.9s | 3.5 MB |
| claude_codex_prompt | redis_getex_expired_event_tests | yes | 220.9s | 284.9 MB | 30 | 29 | 308.8s | 5.2 MB |
| claude_codex_prompt_min_tools | redis_getex_expired_event_tests | yes | 194.0s | 284.2 MB | 30 | 22 | 194.7s | 2.4 MB |
| baseline_pi | redis_getex_expired_event_tests | yes | 104.0s | 164.0 MB | 21 | 15 | 102.6s | 2.4 MB |
| baseline_codex | linux_string_get_size_return_length | yes | 53.0s | 212.1 MB | 6 | 4 | 47.3s | 0.7 MB |
| codex_cc_prompt | linux_string_get_size_return_length | yes | 30.8s | 213.1 MB | 6 | 5 | 24.2s | 0.4 MB |
| baseline_claude | linux_string_get_size_return_length | yes | 263.2s | 287.0 MB | 38 | 29 | 262.6s | 4.6 MB |
| claude_codex_prompt | linux_string_get_size_return_length | yes | 244.0s | 292.8 MB | 38 | 39 | 244.5s | 6.6 MB |
| claude_codex_prompt_min_tools | linux_string_get_size_return_length | yes | 150.5s | 270.8 MB | 24 | 19 | 152.2s | 2.3 MB |
| baseline_pi | linux_string_get_size_return_length | yes | 133.8s | 172.2 MB | 20 | 15 | 129.9s | 2.6 MB |

## Interpretation

### 1. Prompt matters a lot for turn count and wall time

Codex with the Claude-style prompt became much more concise on
`redis_getex_expired_event_tests`:

- API requests: `72 -> 17`
- tool calls: `68 -> 26`
- wall time: `377.6s -> 164.5s`
- API payload: `9.1 MB -> 2.4 MB`

The same Codex harness, model route, and tool layer behaved very differently
with a different base prompt. That is real prompt-layer causality.

### 2. Runtime baseline is not prompt-driven

Claude stayed around a 270-280 MB empty-task baseline across prompt variants:

- baseline Claude: `279.4 MB`
- Claude with Codex prompt: `273.5 MB`
- Claude with Codex prompt and minimal tools: `282.3 MB`

Codex stayed around 162-164 MB:

- baseline Codex: `164.0 MB`
- Codex with Claude-style prompt: `161.8 MB`

So the baseline memory gap is mostly harness/runtime architecture, not system
prompt text.

### 3. Claude's tool/runtime layer remains visible after prompt replacement

Replacing Claude's system prompt with Codex's base prompt improved wall time on
both real probes, but did not make Claude look like Codex:

- `redis_getex_expired_event_tests`: `315.2s -> 220.9s`
- `linux_string_get_size_return_length`: `263.2s -> 244.0s`

Peak PSS barely moved:

- Redis test: `287.0 MB -> 284.9 MB`
- Linux return length: `287.0 MB -> 292.8 MB`

This says the hidden/non-prompt harness layer still matters: Claude's process
tree, event loop, tool plumbing, and model request strategy remain Claude-like
even under a Codex prompt.

### 4. Restricting Claude's tool surface helped more than prompt replacement alone

Claude with Codex prompt plus `CLAUDE_TOOLS=Bash,Edit,Read,Write` and
`CLAUDE_DISABLE_SLASH_COMMANDS=1` moved closer to Codex/Pi behavior:

- Redis test wall time: `220.9s -> 194.0s`
- Linux return-length wall time: `244.0s -> 150.5s`
- Linux tool calls: `38 -> 24`
- Linux API requests: `39 -> 19`
- Linux PSS: `292.8 MB -> 270.8 MB`

This suggests the model-visible tool menu is causal, not just descriptive. When
Claude cannot use `Grep`, `Glob`, task tools, slash-command skills, and broader
workflow tools, it shifts toward Bash-mediated search and a smaller action loop.

### 5. The minimal Claude variant still did not become Pi or Codex

Even after prompt and tool restriction, Claude remained much heavier than Pi on
the Linux return-length probe:

- Claude minimal: `150.5s`, `270.8 MB`
- Pi baseline: `133.8s`, `172.2 MB`

That remaining gap is likely runtime/harness architecture: Claude Code's
process, event stream, session machinery, and DeepSeek Anthropic-compatible
message path.

## Tool Behavior Notes

Redis test, Codex with Claude-style prompt:

- First-class Codex commands dropped from `67` to `25`.
- Shell/read/search spans also dropped.
- Repeated failures without detected edits dropped from `3` to `0`.

Redis test, Claude minimal tool surface:

- API-advertised tools were only `Bash`, `Edit`, `Read`, `Write`.
- Actual subprocesses shifted toward shell tools: `grep`, `head`, `rg`, `git`.
- Zero-match searches rose to `23`, because search moved out of Claude's
  structured `Grep` tool and into shell-visible commands.

Linux return-length, Claude minimal tool surface:

- Build-related spans still appeared: `gcc`, `make`, `sh`, `rm`, `mkdir`.
- This confirms that prompt/tool ablations can reduce turns, but repo build
  behavior still controls peak memory when the agent decides to verify via
  compilation.

## Causal Takeaway

The differences are not one thing.

| Cause | Evidence |
|---|---|
| Base model | Controlled as DeepSeek V4 Pro, but behavior still differed substantially. |
| Base prompt | Codex changed dramatically under the Claude-style prompt. |
| Tool surface | Claude got faster/lighter when restricted to Bash/Edit/Read/Write. |
| Runtime architecture | Claude's empty-task PSS stayed ~280 MB regardless of prompt. |
| Project build fanout | Linux/Redis build subprocesses still created memory peaks under prompt swaps. |

Best current model:

```text
base model
  + base prompt pressure
  + model-visible tool schema
  + harness runtime/session machinery
  + repo build/test fanout
  = observed resource behavior
```

The prompt is a strong behavioral driver. The prompt is not the whole story.
Tool surface and runtime architecture are independently measurable causes.

## Recommended Next Runs

1. Repeat the same ablations on `redis_expire_conditional_options`, the biggest
   memory hotspot.
2. Run N=3 for the two short probes here to separate prompt effects from run
   variance.
3. Add a Pi prompt ablation if Pi supports an equivalent base prompt override.
4. Split Claude minimal into two cells:
   - Codex prompt only,
   - native Claude prompt plus minimal tools.

That fourth run would isolate whether the observed Claude improvement came more
from Codex instructions or from disabling Claude's broader tool surface.
