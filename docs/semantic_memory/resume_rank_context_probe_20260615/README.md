# Resume Ranking Context Probe - 2026-06-15

This experiment compared Codex and Claude Code on the same document-heavy task:

> Read all 24 PDF resumes in `24-resumes/` and rank the strongest candidate for a role helping build investor pipelines.

The research question was not the candidate ranking itself. The goal was to observe how each agent built the model context window while processing many private files: which files were discovered, how PDFs were extracted, whether subagents were used, which tool outputs were carried forward, and whether context grew, dropped, or compacted.

The raw request captures contain resume-derived text and should be treated as local-only sensitive artifacts. This report intentionally describes process and sizes without reproducing candidate content.

## Runs

| Agent | Run ID | Wall time | Model requests | Agent tool calls | Result |
|---|---|---:|---:|---:|---|
| Codex | `20260615T195315_codex_resume_ranking_24_resume_investor_pipeline_rank_nocap_rep0` | 81.7s | 10 | 9 | exit 0 |
| Claude Code | `20260615T195514_claude_code_resume_ranking_24_resume_investor_pipeline_rank_nocap_rep0` | 93.1s | 9 | 13 | exit 0 |

Exact context-token counts are in `exact_context_tokens.jsonl`. For Claude Code, requests were counted directly with the Anthropic-compatible `count_tokens` endpoint. For Codex, captured OpenAI Responses requests were replayed through Moonbridge and then counted against the converted Anthropic/DeepSeek request shape.

An earlier Claude Code attempt with `claude-trace` enabled, `20260615T195447_claude_code_resume_ranking_24_resume_investor_pipeline_rank_nocap_rep0`, produced zero model requests because the trace wrapper failed on the packaged `.exe` launcher in Docker. It is excluded from this analysis. The successful Claude Code run still used the harness API observer, so request bodies, semantic layers, and exact context-token counts were captured.

## Main Findings

Both agents used a single main-agent loop. Codex did not invoke `multi_agent_v1`, and Claude Code did not invoke `Agent`. There was no observed fan-out into groups of resumes handled by subagents.

Both agents converted PDFs into text through shell/Python tooling, then let the extracted text enter the next model requests as tool-output memory. In this run, that memory was monotonic: each later request carried the earlier extraction outputs plus new ones. There was no observed compaction or dropping of resume text before the final answer.

Neither agent followed a `read one resume -> rank/update score -> read next resume` loop. Both followed a `discover/extract -> load resume text into context in batches -> rank after all 24 were available` pattern.

Codex initially tried to dump all 24 resumes in one Python/PyPDF2 command. That output was visibly truncated inside the tool result with a truncation marker, so the model did not receive the middle of that all-at-once extraction. Codex then repaired coverage by re-reading grouped ranges: resumes 6-12, 13-18, and 19-24.

Claude Code first extracted all 24 resumes into `/tmp/resumes.json` with `pdfplumber`, then read the JSON back in groups: 1-4, then 5-9, 10-14, 15-19, and 20-24. The last four group reads were issued together in one assistant step, so their outputs all entered the next request at once.

By the final model request, Codex was carrying about 139k chars of tool-output memory and had an exact input context of 43,280 tokens. Claude Code was carrying about 109k chars of tool-output memory and had an exact input context of 46,187 tokens.

## Context Growth

| Agent | First real context | Final context | Tool-output chars in final request | Growth shape |
|---|---:|---:|---:|---|
| Codex | 11,509 tokens | 43,280 tokens | 139,053 chars | Small setup growth, then four large jumps from resume text |
| Claude Code | 20,730 tokens after title request | 46,187 tokens | 109,353 chars | Large static main-agent request, then two major jumps from grouped resume reads |

Claude Code also made a small initial title/metadata-style request at 438 tokens with no tools. Its main-agent request began at 20,730 tokens because the Claude Code tool schema and system/developer context were already present. Codex started lower at 11,509 tokens.

## Codex Timeline

| Req | Exact tokens | Tool-output chars in context | New action | New output chars | Resume markers visible in new output |
|---:|---:|---:|---|---:|---|
| 1 | 11,509 | 0 | Initial model request | 0 | - |
| 2 | 11,773 | 430 | `ls 24-resumes/` | 430 | 1-24 |
| 3 | 11,907 | 532 | Check `pdftotext` availability | 102 | - |
| 4 | 12,245 | 1,119 | Check Python PDF libraries | 587 | - |
| 5 | 12,449 | 1,570 | `pip install PyPDF2` | 451 | - |
| 6 | 12,652 | 1,828 | `pip install --break-system-packages PyPDF2` | 258 | - |
| 7 | 21,763 | 41,673 | PyPDF2 loop over all 24 resumes | 39,845 | partial all-resume output; contained truncation marker |
| 8 | 28,733 | 74,206 | Re-read resumes 6-12 | 32,533 | 6-12 |
| 9 | 36,762 | 109,711 | Re-read resumes 13-18 | 35,505 | 13-18 |
| 10 | 43,280 | 139,053 | Re-read resumes 19-24 | 29,342 | 19-24 |

Interpretation: Codex used direct command output as its memory substrate. The first large extraction was too big for the agent/tool surface as returned to the model, so the middle was represented by a truncation marker rather than literal resume text. The later grouped reads were smaller, untruncated, and accumulated in subsequent context windows.

## Claude Code Timeline

| Req | Exact tokens | Tool-output chars in context | New action | New output chars | Resume markers visible in new output |
|---:|---:|---:|---|---:|---|
| 1 | 438 | 0 | Initial title/metadata-style request | 0 | - |
| 2 | 20,730 | 0 | Main-agent request with system/developer context and tools | 0 | - |
| 3 | 21,767 | 1,566 | List resumes and check basic tools | 1,566 | 1-24 |
| 4 | 22,133 | 1,598 | Check PDF libraries and `pdftotext` | 32 | - |
| 5 | 22,496 | 1,971 | Check installed PDF packages and try installing `pdfplumber` | 373 | - |
| 6 | 22,840 | 2,559 | Install `pdfplumber` with system override | 588 | - |
| 7 | 23,625 | 3,644 | Extract all 24 PDFs into `/tmp/resumes.json`; print extraction counts | 1,085 | 1-24 |
| 8 | 26,919 | 17,766 | Read resumes 1-4 from `/tmp/resumes.json` | 14,122 | 1-4 |
| 9 | 46,187 | 109,353 | Read resumes 5-9, 10-14, 15-19, and 20-24 | 91,587 | 5-24 |

Interpretation: Claude Code separated extraction from reading. The extraction command itself only put short per-resume extraction summaries into context. The real context growth happened when the agent printed grouped resume text back from `/tmp/resumes.json`. The final request received four grouped outputs at once, causing the largest jump.

## Ranking Process

Codex did not begin ranking after each resume or after each batch. Its visible sequence was:

1. Discover all 24 PDF filenames.
2. Check PDF extraction tooling.
3. Install `PyPDF2`.
4. Attempt one all-resume extraction.
5. Notice the output was truncated.
6. Re-read the missing/uncertain ranges in batches.
7. After the final batch, state that it had read all 24 resumes and then produce the analysis/ranking.

The decisive marker is the agent message after the first large extraction: "Good, I got a large chunk but some was truncated. Let me extract in batches to ensure I catch every resume fully." The ranking came after the final grouped extraction, not interleaved with individual file reads.

Claude Code also did not rank incrementally. Its visible sequence was:

1. Discover all 24 PDF filenames.
2. Check available PDF tooling.
3. Install `pdfplumber`.
4. Extract all 24 PDFs to `/tmp/resumes.json`, while only printing extraction counts.
5. Read resumes 1-4.
6. Decide to continue reading the remaining resumes rather than rank.
7. Read resumes 5-9, 10-14, 15-19, and 20-24 in one multi-tool assistant step.
8. After all grouped outputs returned, reason that all 24 had been read and then evaluate every resume against criteria before producing the final ranking.

The decisive marker is Claude Code's post-read reasoning: "Now I have all 24 resumes read. Let me analyze each one systematically for the role of helping build investor pipelines." That means the ranking pass was a separate final synthesis over accumulated context, not a rolling update after each resume.

The practical difference is how each agent staged evidence before ranking. Codex used stdout from direct extraction commands as its working memory and corrected a truncation failure with overlapping group reads. Claude Code used a temporary extracted-text JSON file as a local cache, then selectively printed groups into model context. In both cases, the model's actual ranking decision happened only after all resume text it intended to use had been serialized back into the prompt.

## What Entered The Context Window

For both agents, the model did not directly ingest PDF bytes. The PDFs were read by external tools, and only the text emitted by those tools entered model context as tool results.

Codex context contained:

- Stable base instructions and developer context on every request.
- A stable 12-tool schema on every request.
- Shell/Python command calls as `tool_call_memory`.
- The exact command outputs as `function_call_output` items.
- One large all-resume output with an internal truncation marker.
- Three subsequent grouped extraction outputs that filled in the missing ranges.

Claude Code context contained:

- A tiny first request before the main tool-enabled agent request.
- System and developer context plus the Claude Code tool schema from request 2 onward.
- Bash tool calls and Bash results as message blocks.
- Extraction-count summaries after writing `/tmp/resumes.json`.
- Grouped JSON-print outputs containing the actual extracted resume text.

## Delegation

No subagent delegation occurred.

Evidence:

- Codex advertised `multi_agent_v1`, but no captured tool call used it.
- Claude Code advertised `Agent`, but no captured tool call used it.
- Tool traces show only shell/Python/PDF-extraction work after startup.

This matters for the original question: on this resume-ranking task, neither harness naturally split 24 resumes into subagents. The grouping happened through shell commands inside one agent context, not through separate model contexts.

## Artifacts

- `context_growth_timeseries.csv`: exact-token and layer-level request series.
- `exact_context_tokens.jsonl`: exact provider input-token backfill.
- `context_window_tokens.svg`: request-level context growth plot.
- Raw local-sensitive artifacts:
  - `runs/20260615T195315_codex_resume_ranking_24_resume_investor_pipeline_rank_nocap_rep0/prompt_payloads.jsonl`
  - `runs/20260615T195514_claude_code_resume_ranking_24_resume_investor_pipeline_rank_nocap_rep0/prompt_payloads.jsonl`
  - `runs/*/prompt_payload_report.md`
  - `runs/*/api_requests.jsonl`
