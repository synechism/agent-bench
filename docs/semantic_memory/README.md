# Semantic Memory Docs

Canonical semantic-memory artifacts live here.

- `instrumentation_plan_20260601.md`: what we measure and how prompt/context
  capture works.
- `codex_semantic_memory_analysis_20260601.md`: CTO-facing interpretation of
  the Codex representative batch.
- `codex_representative_aggregate_20260601.md`: compact aggregate table and
  largest retained tool outputs.
- `codex_representative_aggregate_20260601.json`: machine-readable aggregate.

The older scratch aggregate and duplicate findings note were removed from the
repo root. Future semantic aggregate outputs should use:

```bash
python -m analysis.semantic_aggregate \
  --output-prefix docs/semantic_memory/semantic_context_aggregate
```
