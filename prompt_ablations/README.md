# Prompt Ablation Files

These files are mounted read-only into Docker runs at `/prompt_ablations`.

- `codex_default_base_instructions.md`: copied from `openai/codex` at
  `codex-rs/protocol/src/prompts/base_instructions/default.md`.
- `claude_code_curated_system_prompt.md`: assembled from selected fragments in
  `Piebald-AI/claude-code-system-prompts`, focused on core software-engineering
  behavior and Bash/Grep/Read/Edit/Write routing guidance.

The ablation goal is to separate prompt effects from harness/tool-surface
effects. These are not exact full effective prompts for either agent; they are
controlled prompt replacements using publicly inspectable prompt sources.
