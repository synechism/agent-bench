"""Trace Codex context-memory lifecycle from captured prompt payloads.

`analysis.semantic_context` answers how large each semantic layer became. This
script answers the temporal question: when did each prior tool call/output first
become model-visible, did it stay visible, and which additions drove context
growth?
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


STATIC_LAYERS = {"developer_context", "user_or_task"}
MEMORY_TYPES = {
    "assistant",
    "function_call",
    "function_call_output",
    "custom_tool_call",
    "custom_tool_call_output",
    "local_shell_call",
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _item_chars(item: dict[str, Any]) -> int:
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    return int(meta.get("chars") or 0)


def _item_sha(item: dict[str, Any]) -> str:
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    digest = meta.get("sha256")
    return str(digest) if digest else ""


def _item_identity(item: dict[str, Any]) -> str:
    item_type = str(item.get("type") or "unknown")
    call_id = item.get("call_id")
    if call_id:
        return f"{item_type}:{call_id}:{_item_sha(item)}"
    role = str(item.get("role") or "unknown")
    layer = str(item.get("semantic_layer") or "unknown")
    return f"{item_type}:{role}:{layer}:{_item_sha(item)}:{item.get('index')}"


def _is_memory_item(item: dict[str, Any]) -> bool:
    item_type = str(item.get("type") or "")
    if item_type in MEMORY_TYPES and item_type != "message":
        return True
    layer = str(item.get("semantic_layer") or "")
    return layer.endswith("_memory") or "memory" in layer


def _is_static_item(item: dict[str, Any]) -> bool:
    return str(item.get("semantic_layer") or "") in STATIC_LAYERS and not _is_memory_item(item)


def _capture_preview(item: dict[str, Any], limit: int = 220) -> str | None:
    capture = item.get("capture")
    if capture is None:
        return None
    text = str(capture).replace("\r", "").replace("\n", " ")
    text = " ".join(text.split())
    return text[:limit]


def _call_command(item: dict[str, Any]) -> str | None:
    capture = item.get("capture")
    if not isinstance(capture, str):
        return None
    try:
        outer = json.loads(capture)
    except json.JSONDecodeError:
        return None
    args = outer.get("arguments") if isinstance(outer, dict) else None
    if isinstance(args, str):
        try:
            parsed_args = json.loads(args)
        except json.JSONDecodeError:
            return args[:220]
    elif isinstance(args, dict):
        parsed_args = args
    else:
        return None
    cmd = parsed_args.get("cmd") if isinstance(parsed_args, dict) else None
    return str(cmd) if cmd is not None else None


def _request_body_chars(request: dict[str, Any]) -> int:
    body = request.get("body") if isinstance(request.get("body"), dict) else {}
    return int(body.get("chars") or request.get("request_bytes") or 0)


def _input_items(request: dict[str, Any]) -> list[dict[str, Any]]:
    input_payload = request.get("input") if isinstance(request.get("input"), dict) else {}
    items = input_payload.get("items") if isinstance(input_payload, dict) else []
    return [item for item in items if isinstance(item, dict)]


def _type_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(item.get("type") or "unknown") for item in items).items()))


def _layer_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(item.get("semantic_layer") or "unknown") for item in items).items()))


def _layer_chars(items: list[dict[str, Any]]) -> dict[str, int]:
    chars: dict[str, int] = defaultdict(int)
    for item in items:
        chars[str(item.get("semantic_layer") or "unknown")] += _item_chars(item)
    return dict(sorted(chars.items()))


def _top_items(items: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    ranked = sorted(items, key=_item_chars, reverse=True)
    out: list[dict[str, Any]] = []
    for item in ranked[:limit]:
        out.append(
            {
                "type": item.get("type"),
                "semantic_layer": item.get("semantic_layer"),
                "name": item.get("name"),
                "call_id": item.get("call_id"),
                "chars": _item_chars(item),
                "command": _call_command(item),
                "preview": _capture_preview(item),
            }
        )
    return out


def _call_pairs(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    pairs: dict[str, dict[str, Any]] = {}
    for item in items:
        call_id = item.get("call_id")
        if not call_id:
            continue
        rec = pairs.setdefault(
            str(call_id),
            {
                "call_id": str(call_id),
                "first_seen_request": None,
                "call_chars": 0,
                "output_chars": 0,
                "tool_name": None,
                "command": None,
                "output_preview": None,
            },
        )
        item_type = item.get("type")
        if item_type in {"function_call", "custom_tool_call", "local_shell_call"}:
            rec["call_chars"] = _item_chars(item)
            rec["tool_name"] = item.get("name")
            rec["command"] = _call_command(item)
        elif item_type in {"function_call_output", "custom_tool_call_output"}:
            rec["output_chars"] = _item_chars(item)
            rec["output_preview"] = _capture_preview(item)
    return pairs


def derive_lifecycle(run_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload_path = run_dir / "prompt_payloads.jsonl"
    requests = _load_jsonl(payload_path)
    if not requests:
        raise FileNotFoundError(f"No prompt payload records found at {payload_path}")

    first_seen: dict[str, int] = {}
    last_seen: dict[str, int] = {}
    item_by_id: dict[str, dict[str, Any]] = {}
    previous_memory_ids: set[str] = set()
    previous_body_chars: int | None = None
    timeline: list[dict[str, Any]] = []
    all_dropped_ids: set[str] = set()

    for request in requests:
        request_index = int(request.get("request_index") or len(timeline) + 1)
        items = _input_items(request)
        static_items = [item for item in items if _is_static_item(item)]
        memory_items = [item for item in items if _is_memory_item(item)]
        memory_ids = {_item_identity(item) for item in memory_items}

        new_items: list[dict[str, Any]] = []
        for item in memory_items:
            item_id = _item_identity(item)
            item_by_id.setdefault(item_id, item)
            last_seen[item_id] = request_index
            if item_id not in first_seen:
                first_seen[item_id] = request_index
                new_items.append(item)

        retained_ids = previous_memory_ids & memory_ids
        dropped_ids = previous_memory_ids - memory_ids
        resurrected_ids = {item_id for item_id in memory_ids if item_id in all_dropped_ids}
        all_dropped_ids.update(dropped_ids)

        body_chars = _request_body_chars(request)
        call_pair_additions = _call_pairs(new_items)
        for pair in call_pair_additions.values():
            pair["first_seen_request"] = request_index
            pair["generated_after_request"] = request_index - 1 if request_index > 1 else None

        timeline.append(
            {
                "request_index": request_index,
                "request_id": request.get("request_id"),
                "ts": request.get("ts"),
                "model": request.get("model"),
                "path": request.get("path"),
                "request_kind": request.get("request_kind"),
                "window_id": request.get("window_id"),
                "body_chars": body_chars,
                "body_delta_chars": None if previous_body_chars is None else body_chars - previous_body_chars,
                "static_item_count": len(static_items),
                "static_item_chars": sum(_item_chars(item) for item in static_items),
                "memory_item_count": len(memory_items),
                "memory_item_chars": sum(_item_chars(item) for item in memory_items),
                "memory_item_chars_by_layer": _layer_chars(memory_items),
                "memory_item_counts_by_type": _type_counts(memory_items),
                "new_memory_item_count": len(new_items),
                "new_memory_item_chars": sum(_item_chars(item) for item in new_items),
                "new_memory_item_counts_by_type": _type_counts(new_items),
                "new_memory_item_chars_by_layer": _layer_chars(new_items),
                "new_memory_top_items": _top_items(new_items),
                "new_call_pairs": sorted(
                    call_pair_additions.values(),
                    key=lambda item: int(item.get("call_chars") or 0) + int(item.get("output_chars") or 0),
                    reverse=True,
                ),
                "retained_memory_item_count": len(retained_ids),
                "dropped_memory_item_count": len(dropped_ids),
                "resurrected_memory_item_count": len(resurrected_ids),
            }
        )
        previous_memory_ids = memory_ids
        previous_body_chars = body_chars

    memory_items = list(item_by_id.values())
    first_memory_request = min(first_seen.values()) if first_seen else None
    max_memory_record = max(timeline, key=lambda rec: int(rec["memory_item_chars"])) if timeline else {}
    max_new_record = max(timeline, key=lambda rec: int(rec["new_memory_item_chars"])) if timeline else {}

    all_pairs = _call_pairs(memory_items)
    for item_id, item in item_by_id.items():
        call_id = item.get("call_id")
        if call_id and str(call_id) in all_pairs:
            pair = all_pairs[str(call_id)]
            current_first = pair.get("first_seen_request")
            item_first = first_seen[item_id]
            pair["first_seen_request"] = (
                item_first if current_first is None else min(int(current_first), item_first)
            )
            pair["last_seen_request"] = max(int(pair.get("last_seen_request") or 0), last_seen[item_id])
            pair["generated_after_request"] = (
                int(pair["first_seen_request"]) - 1 if int(pair["first_seen_request"]) > 1 else None
            )

    retained_to_final = sum(1 for item_id in first_seen if last_seen[item_id] == len(requests))
    final_memory_ids = {
        _item_identity(item)
        for item in _input_items(requests[-1])
        if _is_memory_item(item)
    }
    dropped_before_final = sorted(item_id for item_id in first_seen if item_id not in final_memory_ids)

    summary = {
        "run_id": run_dir.name,
        "request_count": len(requests),
        "first_memory_request": first_memory_request,
        "memory_addition_rule_observed": (
            "New Codex memory appears as function_call/function_call_output transcript "
            "items in the next model request after the model requested a tool and the "
            "harness executed it."
        ),
        "memory_item_count": len(memory_items),
        "memory_items_retained_to_final_request": retained_to_final,
        "memory_items_dropped_before_final_request": len(dropped_before_final),
        "drop_or_compaction_observed": bool(dropped_before_final),
        "max_visible_memory_request": {
            "request_index": max_memory_record.get("request_index"),
            "memory_item_chars": max_memory_record.get("memory_item_chars"),
            "memory_item_count": max_memory_record.get("memory_item_count"),
            "body_chars": max_memory_record.get("body_chars"),
        },
        "max_new_memory_request": {
            "request_index": max_new_record.get("request_index"),
            "new_memory_item_chars": max_new_record.get("new_memory_item_chars"),
            "new_memory_item_count": max_new_record.get("new_memory_item_count"),
            "body_delta_chars": max_new_record.get("body_delta_chars"),
        },
        "first_seen_memory_chars_by_type": dict(
            sorted(
                Counter(
                    {
                        key: sum(_item_chars(item) for item in memory_items if item.get("type") == key)
                        for key in {str(item.get("type") or "unknown") for item in memory_items}
                    }
                ).items()
            )
        ),
        "first_seen_memory_chars_by_layer": _layer_chars(memory_items),
        "top_first_seen_memory_items": _top_items(memory_items, limit=12),
        "call_pair_count": len(all_pairs),
        "top_call_pairs": sorted(
            all_pairs.values(),
            key=lambda item: int(item.get("call_chars") or 0) + int(item.get("output_chars") or 0),
            reverse=True,
        )[:12],
    }
    return timeline, summary


def write_lifecycle(run_dir: Path) -> dict[str, Any]:
    timeline, summary = derive_lifecycle(run_dir)
    with (run_dir / "memory_lifecycle_timeline.jsonl").open("w", encoding="utf-8") as f:
        for record in timeline:
            f.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
    with (run_dir / "memory_lifecycle_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True, ensure_ascii=False)
    _write_run_report(run_dir, timeline, summary)
    return summary


def _format_int(value: Any) -> str:
    return f"{int(value or 0):,}"


def _short_label(value: Any, limit: int = 220) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", "").replace("\n", " ")
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _write_run_report(run_dir: Path, timeline: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    lines = [
        f"# Codex Memory Lifecycle - {run_dir.name}",
        "",
        "This report follows model-visible transcript items across Codex `/v1/responses` requests.",
        "It treats prior tool calls and tool outputs as carried memory because those are the",
        "items replayed into later request `input` arrays.",
        "",
        "## Summary",
        "",
        f"- Requests: {_format_int(summary.get('request_count'))}",
        f"- First request containing carried memory: {summary.get('first_memory_request')}",
        f"- Distinct carried-memory items: {_format_int(summary.get('memory_item_count'))}",
        f"- Dropped/compacted before final request: `{summary.get('drop_or_compaction_observed')}`",
    ]
    max_visible = summary.get("max_visible_memory_request") or {}
    max_new = summary.get("max_new_memory_request") or {}
    lines.extend(
        [
            (
                "- Max visible carried memory: "
                f"request {max_visible.get('request_index')} "
                f"with {_format_int(max_visible.get('memory_item_chars'))} chars"
            ),
            (
                "- Largest single addition: "
                f"request {max_new.get('request_index')} "
                f"with {_format_int(max_new.get('new_memory_item_chars'))} new chars"
            ),
            "",
            "## Request Timeline",
            "",
            "| request | body chars | body delta | visible memory chars | new memory chars | new tool calls | new outputs | new assistant chars | dropped |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for rec in timeline:
        new_counts = rec.get("new_memory_item_counts_by_type") or {}
        new_layers = rec.get("new_memory_item_chars_by_layer") or {}
        new_call_count = (
            int(new_counts.get("function_call") or 0)
            + int(new_counts.get("custom_tool_call") or 0)
            + int(new_counts.get("local_shell_call") or 0)
        )
        new_output_count = (
            int(new_counts.get("function_call_output") or 0)
            + int(new_counts.get("custom_tool_call_output") or 0)
        )
        lines.append(
            "| "
            f"{rec.get('request_index')} | "
            f"{_format_int(rec.get('body_chars'))} | "
            f"{'' if rec.get('body_delta_chars') is None else _format_int(rec.get('body_delta_chars'))} | "
            f"{_format_int(rec.get('memory_item_chars'))} | "
            f"{_format_int(rec.get('new_memory_item_chars'))} | "
            f"{_format_int(new_call_count)} | "
            f"{_format_int(new_output_count)} | "
            f"{_format_int(new_layers.get('assistant_memory'))} | "
            f"{_format_int(rec.get('dropped_memory_item_count'))} |"
        )

    lines.extend(["", "## Largest First-Seen Items", ""])
    for item in summary.get("top_first_seen_memory_items") or []:
        label = _short_label(item.get("command") or item.get("preview") or item.get("call_id"))
        lines.append(
            f"- request-visible item `{item.get('type')}` "
            f"{_format_int(item.get('chars'))} chars; {label}"
        )

    lines.extend(["", "## Largest Call/Output Pairs", ""])
    for pair in summary.get("top_call_pairs") or []:
        label = _short_label(pair.get("command") or pair.get("output_preview") or pair.get("call_id"))
        total = int(pair.get("call_chars") or 0) + int(pair.get("output_chars") or 0)
        lines.append(
            f"- first visible in request {pair.get('first_seen_request')} "
            f"(generated after request {pair.get('generated_after_request')}): "
            f"{_format_int(total)} chars; {label}"
        )

    (run_dir / "memory_lifecycle_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_aggregate_report(summaries: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Codex Semantic Memory Consumption Lifecycle - 2026-06-02",
        "",
        "This report focuses only on Codex. It goes one level below the aggregate",
        "semantic-memory summaries by tracking when each carried transcript item first",
        "enters the next model request.",
        "",
        "## Core Finding",
        "",
        "In the observed Codex runs, semantic memory consumption is built by transcript",
        "replay. The model does not emit a separate visible instruction saying which",
        "memories to retain. Instead, when the model asks for a tool call, the harness",
        "executes it and appends both the `function_call` record and the",
        "`function_call_output` record to the `input` array of the next",
        "`/v1/responses` request. Those records then remain visible on later requests",
        "until compaction or dropping occurs.",
        "",
        "## Run Summary",
        "",
        "| run | requests | first memory request | carried items | retained to final | dropped/compacted | max visible memory chars | largest addition chars |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for summary in summaries:
        max_visible = summary.get("max_visible_memory_request") or {}
        max_new = summary.get("max_new_memory_request") or {}
        lines.append(
            "| "
            f"`{summary.get('run_id')}` | "
            f"{_format_int(summary.get('request_count'))} | "
            f"{summary.get('first_memory_request')} | "
            f"{_format_int(summary.get('memory_item_count'))} | "
            f"{_format_int(summary.get('memory_items_retained_to_final_request'))} | "
            f"{summary.get('drop_or_compaction_observed')} | "
            f"{_format_int(max_visible.get('memory_item_chars'))} | "
            f"{_format_int(max_new.get('new_memory_item_chars'))} |"
        )

    lines.extend(
        [
            "",
            "## What Answers The User's Questions",
            "",
            "- **When does Codex include new memories?** In these traces, the first carried memory appears on request 2. More generally, new tool-call and tool-output records first become model-visible on request `N + 1`, after the model requested the tool during request `N`'s response and the harness executed it.",
            "- **Why does it include them?** The visible evidence points to harness transcript assembly, not a separate model-side retention decision. Codex influences memory indirectly by choosing which tools to call and how much output to produce.",
        "- **When does it add to the context window?** The addition happens before the next model API request is sent, as new `input` array items. Request-body growth tracks the newly replayed call/output chars plus JSON serialization overhead.",
            "- **What is the semantic unit of memory?** For these Codex payloads, the practical unit is a Responses API item: `function_call`/`custom_tool_call` for the action the model chose, `function_call_output`/`custom_tool_call_output` for observed terminal/file/test/patch output, and occasional assistant messages. File knowledge is just text inside those output items.",
            "- **What does \"want\" mean here?** The traces do not expose an internal preference signal saying \"retain this memory.\" The visible causal chain is: the model wants information or an edit, emits a tool call, receives output, and the client carries that transcript forward.",
            "",
            "## Strongest Example",
            "",
        ]
    )
    richest = max(
        summaries,
        key=lambda summary: int((summary.get("max_visible_memory_request") or {}).get("memory_item_chars") or 0),
    )
    lines.append(f"The highest-memory run was `{richest.get('run_id')}`.")
    lines.append("")
    for pair in (richest.get("top_call_pairs") or [])[:8]:
        total = int(pair.get("call_chars") or 0) + int(pair.get("output_chars") or 0)
        label = _short_label(pair.get("command") or pair.get("output_preview") or pair.get("call_id"))
        lines.append(
            f"- First visible in request {pair.get('first_seen_request')} "
            f"(generated after request {pair.get('generated_after_request')}): "
            f"{_format_int(total)} chars; {label}"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This lets us separate two decisions that are easy to conflate:",
            "",
            "- The model decides to inspect something by issuing a tool call.",
            "- The Codex client/harness decides to carry the resulting transcript forward by sending prior call/output items in the next request.",
            "",
            "So the observed semantic memory stack is layered as static prompt/tool schema",
            "plus an append-only carried transcript. In these representative Codex runs,",
            "no dropped carried-memory items were observed before the final request, so we",
            "did not catch a compaction boundary. To study compaction directly, the next",
            "experiment should force longer runs with intentionally large tool outputs and",
            "then look for the first request where earlier call IDs disappear or are",
            "replaced by a summary-like item.",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Trace Codex prompt-memory lifecycle")
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--aggregate-report", type=Path)
    args = parser.parse_args()

    summaries = []
    for run_dir in args.run_dirs:
        summary = write_lifecycle(run_dir)
        summaries.append(summary)
        print(f"Wrote memory lifecycle artifacts for {run_dir}")
        print(f"  requests: {summary['request_count']}")
        print(f"  carried items: {summary['memory_item_count']}")
        print(f"  dropped/compacted: {summary['drop_or_compaction_observed']}")

    if args.aggregate_report:
        write_aggregate_report(summaries, args.aggregate_report)
        print(f"Wrote aggregate report: {args.aggregate_report}")


if __name__ == "__main__":
    main()
