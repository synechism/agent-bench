# Codex Sentinel Pressure Probe - 32 Chunks - 2026-06-02

This run repeats the sentinel/fidelity probe with a larger requested distractor
output:

```text
python scripts/emit_noise.py --chunks 32
```

The purpose was to start pressure-ramping beyond the 8-chunk baseline and watch
for compaction, dropping, re-reading, or degraded fact use.

## Source Run

```text
runs/20260602T145959_codex_semantic_memory_sentinel_semantic_memory_sentinel_pressure_32_nocap_rep0
```

The run used the same local Azure-provider observer path as the 8-chunk
baseline:

```bash
CODEX_MODEL_PROVIDER=azure \
CODEX_PROVIDER_BASE_URL=https://cronwell-codex-2.openai.azure.com/openai/v1 \
CODEX_PROVIDER_ENV_KEY=AZURE_API_KEY \
CODEX_PROVIDER_WIRE_API=responses \
HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1 \
HARNESS_API_OBSERVER_CAPTURE_CHARS=1000000 \
python -m orchestrator.matrix \
  --config harness_configs/harness_config_semantic_codex_sentinel_pressure32_local.json
```

## Results

| metric | 8-chunk baseline | 32-chunk pressure |
| --- | ---: | ---: |
| API requests | 7 | 6 |
| API errors | 0 | 0 |
| carried-memory items | 38 | 30 |
| max visible carried-memory chars | 58,509 | 27,658 |
| largest single materialization | 42,619 | 17,841 |
| retained noise output chars | 40,154 | 16,156 |
| answers correct | true | true |
| all facts visible in final request | true | true |
| sentinel re-read after noise | false | false |
| dropped/compacted items observed | false | false |

## Key Finding

The 32-chunk run did not simply create 4x more semantic memory than the
8-chunk run. Instead, Codex bounded the noisy tool output. The retained tool
call for the noise command included:

```text
python scripts/emit_noise.py --chunks 32
```

with tool-call arguments that included:

```text
max_output_tokens: 4000
```

The retained tool output reported an original token count of 53,880, but only
about 16.2k chars were carried into later requests. This means the semantic
context did not receive the full environment output.

This is an important general behavior: semantic memory consumption is governed
not only by what the environment produces, but also by the agent/tool interface
policy for how much output to admit into the transcript.

## Interpretation

The earlier model was:

```text
tool output -> carried transcript -> next request
```

The pressure run refines it:

```text
tool output produced by environment
  -> tool-output capture/truncation policy
  -> carried transcript item
  -> next request
```

In this run, Codex still retained the sentinel facts literally, kept them
visible through the final request, and used them correctly without re-reading
the sentinel files after the noise command. No compaction boundary was observed.

## What This Changes

For pressure experiments, increasing raw command output is not enough. We must
distinguish:

- raw environment output size,
- tool-captured output size,
- model-visible carried output size,
- final request retention,
- later task use.

The 32-chunk run suggests Codex can reduce semantic consumption before
compaction by limiting tool output admission. To force a true context pressure
boundary, the next probe should create many medium-sized outputs across many
separate tool calls, or require useful sentinel facts to be embedded in later
parts of bounded outputs where truncation may hide them.

## Next Pressure Variant

A better next ramp is not simply `--chunks 128`. It should vary output shape:

- many separate files read one at a time,
- facts placed near beginning, middle, and end of outputs,
- distractor facts that share prefixes with true facts,
- mandatory use-after-distance checks after many separate tool outputs.

That will tell us whether Codex retains facts because they are early and small,
because they are repeated in patches/final answers, or because the tool-output
budget preserved them.
