# Codex Sentinel Many-File Probe - 2026-06-03

This run tests a different pressure shape from the earlier sentinel probes. The
goal was not one huge output; it was many separate fact observations across
many turns.

## Source Run

```text
runs/20260603T155817_codex_semantic_memory_sentinel_semantic_memory_sentinel_many_files_nocap_rep0
```

The run used the local Azure-provider observer path with prompt capture:

```bash
CODEX_MODEL_PROVIDER=azure \
CODEX_PROVIDER_BASE_URL=https://cronwell-codex-2.openai.azure.com/openai/v1 \
CODEX_PROVIDER_ENV_KEY=AZURE_API_KEY \
CODEX_PROVIDER_WIRE_API=responses \
HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1 \
HARNESS_API_OBSERVER_CAPTURE_CHARS=1500000 \
python -m orchestrator.matrix \
  --config harness_configs/harness_config_semantic_codex_sentinel_many_files_local.json
```

## Probe Design

The built-in `semantic_memory_sentinel` codebase now also contains:

- 24 files under `many_facts/`,
- one `MANY_SENTINEL key=value` fact per file,
- sentinel placement near the beginning, middle, or end of each file,
- `many_answers.json`, initially blank,
- `scripts/emit_many_distractors.py`, which emits distractor output after fact
  collection,
- `scripts/verify_many_answers.py`, which verifies answers using hashes rather
  than literal expected values.

The verifier intentionally does not reveal the plain expected values.

## Results

| metric | value |
| --- | ---: |
| API requests | 31 |
| API errors | 0 |
| carried-memory items | 78 |
| carried items retained to final | 78 |
| dropped/compacted items observed | false |
| max visible carried-memory chars | 77,439 |
| max request body chars | 118,559 |
| largest single materialization | 42,351 |
| completed tool output observed | 96,424 |
| new memory materialized | 77,439 |
| answers correct | true |
| all facts visible in final request | true |
| re-read after distractor step | false |

## Fact Visibility

All 24 facts were correct and visible in the final request.

| fact range | first-visible behavior |
| --- | --- |
| `fact_01` | first visible in request 3 |
| `fact_02` ... `fact_24` | one additional fact became visible on each subsequent request through request 26 |
| all facts | last visible in request 31 |

The decreasing appearance counts are expected: earlier facts were present in
more later requests. For example, `fact_01` appeared 32 times, while `fact_24`
appeared 9 times.

## Tool Strategy

Codex did not read all 24 files as full file dumps. It adapted:

- It listed `many_facts/`.
- It read `fact_01_begin.txt` with `sed`, which admitted a 5,869-char output.
- It then used `rg --line-number '^MANY_SENTINEL ' ...` for most later files,
  producing compact one-line outputs.

That is itself a semantic-memory policy behavior. The model/tool loop reduced
future context pressure by choosing narrower extraction commands after seeing
the pattern.

## Interpretation

This run strengthens the general model:

```text
model decides how to inspect
  -> tool command shape controls output size
  -> tool-output admission controls retained size
  -> admitted output is replayed into future requests
```

The many-file probe produced 31 API requests and 78 carried-memory items, but
still no dropping or compaction. The transcript remained append-only for the
duration of the task.

The run also shows that Codex can preserve many separately observed facts
through a later distractor phase and use them correctly without a command-level
re-read. This is stronger than the first sentinel probe because the facts were
spread across 24 separate files and many requests.

## What Changed Compared To Prior Probes

| probe | requests | carried items | max carried chars | facts | final visible | re-read after noise | drops |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| 8-chunk sentinel | 7 | 38 | 58,509 | 5 | true | false | false |
| 32-chunk pressure | 6 | 30 | 27,658 | 5 | true | false | false |
| many-file sentinel | 31 | 78 | 77,439 | 24 | true | false | false |

The 32-chunk run demonstrated output-admission limits. The many-file run
demonstrated adaptive narrow retrieval and append-only retention across many
turns.

## Remaining Gap

We still have not observed the compaction boundary. The next probe should force
either:

- many more separate facts,
- repeated delayed use after additional unrelated tool calls,
- facts hidden beyond truncation boundaries,
- or multiple rounds where the model must preserve earlier facts while learning
  new conflicting decoys.

The most promising next shape is a multi-phase use-after-distance probe: collect
facts, do 50 unrelated tool calls, use a subset, do another 50 calls, then use a
different subset. That should reveal whether Codex eventually drops, summarizes,
or re-derives older transcript items.
