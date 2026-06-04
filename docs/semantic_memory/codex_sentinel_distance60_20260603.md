# Codex Sentinel Distance-60 Probe - 2026-06-03

This run tests delayed use after a long stretch of unrelated tool output. The
goal was to separate fact collection from fact use, then watch whether Codex
kept early facts literally visible while 60 irrelevant files were read one by
one.

## Source Run

```text
runs/20260603T173458_codex_semantic_memory_sentinel_semantic_memory_sentinel_distance_60_nocap_rep0
```

The run used the local Azure-provider observer path with prompt capture:

```bash
CODEX_MODEL_PROVIDER=azure \
CODEX_PROVIDER_BASE_URL=https://cronwell-codex-2.openai.azure.com/openai/v1 \
CODEX_PROVIDER_ENV_KEY=AZURE_API_KEY \
CODEX_PROVIDER_WIRE_API=responses \
HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1 \
HARNESS_API_OBSERVER_CAPTURE_CHARS=2000000 \
python -m orchestrator.matrix \
  --config harness_configs/harness_config_semantic_codex_sentinel_distance60_local.json
```

## Probe Design

The task used the 24-file `many_facts/` oracle, then required the agent to read
60 separate files under `distance_noise/` before writing `many_answers.json`.

The verifier checked the final answers using hashes rather than exposing the
literal expected values. The fidelity scorer checked three separate things:

- whether each fact was literally visible in captured prompt payloads,
- whether each answer was correct,
- whether Codex re-read the fact files after entering the noise phase.

## Results

| metric | value |
| --- | ---: |
| API requests | 65 |
| API errors | 0 |
| carried-memory items | 151 |
| carried items retained to final | 151 |
| dropped/compacted items observed | false |
| max visible carried-memory chars | 613,873 |
| max request body chars | 666,179 |
| largest single materialization | 13,658 |
| tool-output memory chars | 570,392 |
| new memory materialized | 613,873 |
| answers correct | true |
| all 24 facts visible in final request | true |
| re-read after distance/noise phase | false |

## Fact Visibility

All 24 facts were collected by one compact command:

```text
rg "MANY_SENTINEL" many_facts
```

That output first became visible in request 2. Every fact remained visible
through request 65, including the final request where the answers were written
and verified.

This matters because the facts were not re-derived after the distance phase.
The event probe observed one fact-read command before the noise phase and no
fact-file re-read after noise began.

## Distance Pressure

The pressure came from the intervening reads:

```text
cat distance_noise/noise_01.txt
cat distance_noise/noise_02.txt
...
cat distance_noise/noise_60.txt
```

Each early distance file added roughly 9.4k chars of tool-output memory plus
the corresponding tool-call item. The request payload grew steadily:

| checkpoint | request body chars | visible memory chars |
| --- | ---: | ---: |
| request 2 | 42,255 | 6,424 |
| request 12 | 149,277 | 110,760 |
| request 23 | 263,291 | 221,823 |
| request 33 | 365,715 | 321,633 |
| request 43 | 467,011 | 420,387 |
| request 53 | 568,289 | 519,123 |
| request 65 | 666,179 | 613,873 |

No carried item disappeared at any checkpoint.

## Memory Layer Breakdown

First-seen carried memory by semantic layer:

| layer | chars |
| --- | ---: |
| tool output memory | 570,392 |
| tool call memory | 22,622 |
| reasoning or compaction memory | 19,240 |
| assistant memory | 1,619 |

The run was overwhelmingly tool-output dominated. This confirms the same broad
shape as the Redis and sentinel runs, but at a much larger scale.

## Interpretation

This is the strongest Codex retention probe so far. It shows append-only
carried transcript behavior through:

- 65 model requests,
- 151 carried-memory items,
- 613,873 chars of visible carried memory,
- 666,179 chars in the largest captured request body,
- 60 unrelated distance reads between fact collection and final use.

The result does not prove Codex never compacts. It means our observed
compaction boundary is now above this run, or compaction was not triggered for
this payload shape. Within the captured request path, early facts remained
literal transcript text, not just latent model memory or a hidden summary.

The probe primarily tested long-distance retention, not hard fact acquisition:
Codex used a compact `rg` command that collected all 24 facts in one output.
That was an efficient strategy, and it kept the fact-bearing item small. The
real pressure came from unrelated tool output after that point.

## Updated Boundary

Before this run, the strongest many-turn sentinel evidence was:

| probe | requests | carried items | max carried chars | facts | final visible | re-read after noise | drops |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| 8-chunk sentinel | 7 | 38 | 58,509 | 5 | true | false | false |
| 32-chunk pressure | 6 | 30 | 27,658 | 5 | true | false | false |
| many-file sentinel | 31 | 78 | 77,439 | 24 | true | false | false |
| distance-60 sentinel | 65 | 151 | 613,873 | 24 | true | false | false |

The distance-60 run moves the lower bound for observed append-only behavior by
almost an order of magnitude in visible carried-memory chars.

## Remaining Gap

We still have not seen the first request where a previously carried item is
dropped, summarized, or replaced. The next useful probes should target that
boundary directly:

- larger distance runs, such as 120 or 180 noise files,
- larger per-file outputs that exceed the current 9.4k-char retained chunks,
- facts placed beyond output truncation boundaries,
- forced delayed use of different subsets after multiple distance phases,
- decoys introduced after the original facts to test conflict resolution.

The central open question is no longer whether Codex can carry facts through
ordinary task-length context. It can. The open question is what happens at the
first real transcript-management boundary.
