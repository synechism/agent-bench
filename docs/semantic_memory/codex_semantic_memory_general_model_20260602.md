# Codex Semantic Memory Consumption - General Model - 2026-06-02

This note is the general answer we should use to guide the next phase. The
Redis runs are evidence, but the model below is intended to apply across Codex
coding tasks, not only to one benchmark family.

## Thesis

Codex semantic memory consumption should be understood as a state machine, not
as a single context-size number.

At each step, the agent has:

- a fixed instruction envelope,
- task and environment context,
- a carried transcript of model-authored items and environment-authored items,
- client-side state deciding what transcript material to resend,
- provider-side behavior that may affect caching/latency/cost but is not
  directly observable as semantic memory unless it changes request contents.

The important question is therefore:

```text
What semantic object was created, who created it, when did it first become
model-visible, how long did it remain visible, and was it later transformed,
dropped, summarized, or used?
```

## Observable State Machine

For Codex, the visible loop is:

```text
1. request assembly
   static instructions + tool schema + task + carried transcript

2. model decision
   assistant text, tool calls, patches, plans, final messages

3. environment execution
   shell output, file snippets, test logs, patch results

4. transcript capture
   call records and outputs become structured conversation items

5. next request materialization
   newly captured items appear in the next request input array

6. accumulation or memory management
   items either continue to be replayed, disappear, or are replaced by a
   summary-like item

7. later use
   the model relies on, ignores, corrupts, or re-derives the retained material
```

The representative Codex runs mainly exercised steps 1-5 and showed append-only
carried transcript behavior. They did not yet force a clear step-6 compaction
boundary.

## What "The Agent Wants To Remember" Means

There are two different decisions that can look like one:

- The model decides what to inspect, edit, or test by emitting tool calls.
- The Codex client decides what prior transcript items to put into the next
  request.

The request traces do not expose an internal model signal like "retain this
memory." The observable proxy for model intent is tool choice: the model asks
for information, that information becomes environment output, and the client
usually carries that output forward. So the model's memory influence is
indirect unless we observe explicit assistant summaries, todo state, or
compaction messages.

## The Full-Picture View

For every turn, we want a ledger with these fields:

| Step | Question | Evidence |
| --- | --- | --- |
| Request input | What did the model see? | `prompt_payloads.jsonl`, `semantic_context_timeline.jsonl` |
| Model action | What did it choose to do? | response items when captured, structured events, tool call items in next request |
| Environment result | What new semantic material was produced? | `structured_events_observed.jsonl`, tool output items |
| Next context | What became model-visible? | new `input` items in request `N + 1` |
| Retention | Did it stay visible? | call/output identities across later requests |
| Transformation | Was it summarized or rewritten? | disappearance of call IDs plus new assistant/system summary items |
| Use | Did the model actually rely on it? | task behavior, sentinel probes, later edits/tests |

This separates visible memory consumption from task success. A fact can be
visible and unused, absent but re-derived, present but corrupted, or compressed
into a summary.

## Current Evidence From Codex Runs

The current representative suite shows:

- first carried memory appears in request 2,
- tool call/output records first become visible in request `N + 1`,
- file knowledge is carried as literal tool output text,
- patch attempts can be carried as `custom_tool_call` and
  `custom_tool_call_output`,
- occasional assistant text is carried as `assistant_memory`,
- no carried-memory items were dropped before the final request in these runs.

That supports the transcript-replay model, but it does not yet characterize
compaction or semantic fidelity under pressure.

## Avoiding Overfit

The next experiments should vary task shape, not just task size:

| Axis | Why it matters |
| --- | --- |
| Empty/no-tool tasks | Measures static prompt floor and startup envelope. |
| Read-only tasks | Isolates file/tool output memory without edit noise. |
| Patch-heavy tasks | Measures edit/patch transcript pressure. |
| Test-heavy tasks | Measures noisy log retention and failure-loop behavior. |
| Long-horizon tasks | Forces possible dropping or compaction. |
| Sentinel-fact tasks | Tests literal retention and later use. |
| Distractor-heavy tasks | Tests whether useful facts survive irrelevant output. |
| Re-derivation tasks | Separates memory from repeated lookup behavior. |

The goal is not to find a single compression point. The goal is to describe the
policy surface: when memory is literal replay, when it becomes summary, when it
is dropped, and whether the model can still use the information.

## Recommended Experiment Set

1. **Static envelope baseline**
   Run empty and tiny no-tool tasks across sessions. Confirm fixed prompt,
   tool schema, environment context, and window ID behavior.

2. **Read-only sentinel sweep**
   Create files with unique sentinel facts at known offsets. Ask Codex to read
   some, then perform unrelated work, then use those facts later. Track whether
   each sentinel is literally present, summarized, absent, or used.

3. **Output pressure ramp**
   Force controlled outputs of 5k, 25k, 100k, 250k, and larger chunks. Watch
   for first disappearance of earlier call IDs, request-kind/window changes, or
   summary-like assistant items.

4. **Noisy log loop**
   Produce long test logs with a few important failure lines. Measure whether
   the exact failure lines remain visible, get summarized, or are re-fetched.

5. **Patch/edit pressure**
   Use tasks that require repeated failed patches and large diffs. This tests
   whether edit attempts are carried differently from shell output.

6. **Use-after-distance probe**
   After many intervening turns, ask the model to modify code based on an early
   sentinel. Score visible retention separately from correct use.

## Acceptance Criteria For A General Answer

We have a full-picture explanation when we can answer these across task types:

- What is the static floor per request?
- What semantic item types can enter carried memory?
- What event creates each item type?
- Does each item first appear on the next request or later?
- How long does each item remain visible?
- What triggers dropping, summarization, or window changes?
- Are summaries model-authored, client-authored, or otherwise injected?
- Which retained facts are actually used later?
- How do output size, item count, task type, and tool choice affect growth?

## Current Tooling

Two Codex-specific tools now cover the first half of this picture:

```bash
python -m analysis.codex_memory_lifecycle runs/<codex_run_id>
python -m analysis.codex_turn_ledger runs/<codex_run_id>
```

`codex_memory_lifecycle` answers item retention: first seen, last seen,
dropped, and largest contributors.

`codex_turn_ledger` answers state transitions: request-visible memory,
observed events after that request, and new memory materialized in the next
request.

The sentinel/fidelity scorer can say whether a known fact was present,
transformed, absent, and successfully used:

```bash
python -m analysis.sentinel_fidelity runs/<codex_sentinel_run_id>
```

See `codex_sentinel_probe_20260602.md` for the first result. In that run, all
five facts were visible through the final request, the distractor output was
also retained literally, and Codex used the facts correctly without a
command-level re-read after the noise step.

See `codex_sentinel_pressure32_20260602.md` for the first pressure-ramp
follow-up. That run showed a new general mechanism: raw environment output does
not necessarily become semantic memory. Codex bounded the noisy command with a
tool-call output cap, so about 53.9k original output tokens became about 16.2k
chars of retained tool output.

The next remaining tooling gap is a pressure-ramp runner that varies output
shape, not just raw output size, until compaction or dropping is observed.
