# Codex Sentinel Fidelity Probe - 2026-06-02

This is the first task-agnostic probe for Codex semantic-memory fidelity. Unlike
the Redis representative suite, this run uses a synthetic built-in repository
with known sentinel facts, controlled distractor output, and a verifier.

## Source Run

```text
runs/20260602T142734_codex_semantic_memory_sentinel_semantic_memory_sentinel_probe_nocap_rep0
```

The run used local sandbox execution with the API observer routed through the
existing Azure Codex provider configuration. Prompt capture was enabled:

```bash
CODEX_MODEL_PROVIDER=azure \
CODEX_PROVIDER_BASE_URL=https://cronwell-codex-2.openai.azure.com/openai/v1 \
CODEX_PROVIDER_ENV_KEY=AZURE_API_KEY \
CODEX_PROVIDER_WIRE_API=responses \
HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1 \
HARNESS_API_OBSERVER_CAPTURE_CHARS=250000 \
python -m orchestrator.matrix \
  --config harness_configs/harness_config_semantic_codex_sentinel_local.json
```

## Probe Design

The built-in codebase `semantic_memory_sentinel` contains:

- five sentinel files with canonical facts,
- distractor files with decoys,
- `scripts/emit_noise.py`, which emits about 40k chars of irrelevant output,
- `scripts/verify_answers.py`, which checks `answers.json`.

The task asks Codex to read the sentinel facts, run the noise generator before
editing `answers.json`, then fill the answers and run the verifier, preferably
without re-reading the sentinel files.

## Results

| metric | value |
| --- | ---: |
| API requests | 7 |
| API errors | 0 |
| carried-memory items | 38 |
| max visible carried-memory chars | 58,509 |
| new memory materialized | 58,509 chars |
| largest single materialization | 42,619 chars |
| answers correct | true |
| all facts visible at least once | true |
| all facts visible in final request | true |
| sentinel re-read after noise | false |
| verifier observed OK | true |

The largest materialization happened after Codex ran:

```text
python scripts/emit_noise.py --chunks 8
```

That command produced about 40.2k chars of retained tool output and first
became visible in request 4.

## Fact Visibility

| fact | first visible | last visible | final visible | appearances |
| --- | ---: | ---: | --- | ---: |
| alpha | 3 | 7 | true | 10 |
| bravo | 3 | 7 | true | 10 |
| charlie | 3 | 7 | true | 10 |
| delta | 3 | 7 | true | 10 |
| echo | 3 | 7 | true | 10 |

The sentinel values first entered model-visible context as retained
`function_call_output` items after the sentinel files were read. They also
appeared in later materialized artifacts, including the patch to `answers.json`.

## Interpretation

This run gives us a cleaner general observation than the Redis tasks:

- Codex observed facts as file-read tool outputs.
- The facts became model-visible on the next request, not in the same request.
- A large distractor output was retained literally as tool output.
- The original sentinel facts stayed visible through the final request.
- Codex used the facts correctly without a command-level re-read after the noise
  step.

This is still below the compaction threshold: no carried items were dropped.
The next sentinel variant should increase noise volume until we see either
call-id disappearance, a summary-like replacement, or a failure to use facts
that were previously visible.

## Generated Artifacts

```text
runs/.../sentinel_fidelity_summary.json
runs/.../sentinel_fidelity_report.md
runs/.../memory_lifecycle_summary.json
runs/.../memory_lifecycle_report.md
runs/.../codex_turn_ledger_summary.json
runs/.../codex_turn_ledger.md
```

Relevant commands:

```bash
python -m analysis.sentinel_fidelity runs/<run_id>
python -m analysis.codex_memory_lifecycle runs/<run_id>
python -m analysis.codex_turn_ledger runs/<run_id>
```
