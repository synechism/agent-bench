"""Build a Codex turn ledger from prompt captures and observed events.

The lifecycle report tracks carried items inside model requests. This joins
that request-level view with Codex's structured event stream so each turn can
be read as a state transition:

request N visible context -> observed agent/tool events -> request N+1 additions
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


MEMORY_TYPES = {
    "assistant",
    "message",
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


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _item_chars(item: dict[str, Any]) -> int:
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    return int(meta.get("chars") or 0)


def _item_sha(item: dict[str, Any]) -> str:
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    return str(meta.get("sha256") or "")


def _item_identity(item: dict[str, Any]) -> str:
    item_type = str(item.get("type") or "unknown")
    call_id = item.get("call_id")
    if call_id:
        return f"{item_type}:{call_id}:{_item_sha(item)}"
    return (
        f"{item_type}:{item.get('role')}:{item.get('semantic_layer')}:"
        f"{_item_sha(item)}:{item.get('index')}:{item.get('block_index')}"
    )


def _is_memory_item(item: dict[str, Any]) -> bool:
    layer = str(item.get("semantic_layer") or "")
    item_type = str(item.get("type") or "")
    if layer.endswith("_memory") or "memory" in layer:
        return True
    return item_type in MEMORY_TYPES and layer not in {"developer_context", "user_or_task"}


def _items(request: dict[str, Any]) -> list[dict[str, Any]]:
    input_payload = request.get("input") if isinstance(request.get("input"), dict) else {}
    items = input_payload.get("items") if isinstance(input_payload, dict) else []
    return [item for item in items if isinstance(item, dict)]


def _body_chars(request: dict[str, Any]) -> int:
    body = request.get("body") if isinstance(request.get("body"), dict) else {}
    return int(body.get("chars") or request.get("request_bytes") or 0)


def _short(value: Any, limit: int = 180) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\r", "").replace("\n", " ")
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _call_command(item: dict[str, Any]) -> str | None:
    capture = item.get("capture")
    if not isinstance(capture, str):
        return None
    try:
        outer = json.loads(capture)
    except json.JSONDecodeError:
        return _short(capture)
    if not isinstance(outer, dict):
        return None
    args = outer.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return _short(args)
    if isinstance(args, dict) and args.get("cmd") is not None:
        return str(args.get("cmd"))
    if isinstance(args, str):
        return _short(args)
    return None


def _new_memory_items(requests: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    seen: set[str] = set()
    out: dict[int, list[dict[str, Any]]] = {}
    for fallback_index, request in enumerate(requests, start=1):
        request_index = int(request.get("request_index") or fallback_index)
        new_items: list[dict[str, Any]] = []
        for item in _items(request):
            if not _is_memory_item(item):
                continue
            item_id = _item_identity(item)
            if item_id in seen:
                continue
            seen.add(item_id)
            new_items.append(item)
        out[request_index] = new_items
    return out


def _events_by_interval(run_dir: Path, requests: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    events = _load_jsonl(run_dir / "structured_events_observed.jsonl")
    request_times: list[tuple[int, datetime]] = []
    for fallback_index, request in enumerate(requests, start=1):
        ts = _parse_ts(request.get("ts"))
        if ts is not None:
            request_times.append((int(request.get("request_index") or fallback_index), ts))
    request_times.sort(key=lambda item: item[1])

    by_request: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if not request_times:
        return by_request

    for event in events:
        event_ts = _parse_ts(event.get("observer_ts"))
        if event_ts is None:
            continue
        owner = request_times[0][0]
        for index, (_, request_ts) in enumerate(request_times):
            next_ts = request_times[index + 1][1] if index + 1 < len(request_times) else None
            if event_ts >= request_ts and (next_ts is None or event_ts < next_ts):
                owner = request_times[index][0]
                break
        by_request[owner].append(event)
    return by_request


def _event_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    record_types: Counter[str] = Counter()
    item_types: Counter[str] = Counter()
    completed_tools = 0
    completed_tool_output_chars = 0
    completed_agent_message_chars = 0
    completed_items: list[dict[str, Any]] = []

    for event in events:
        record = event.get("record") if isinstance(event.get("record"), dict) else {}
        record_type = str(record.get("type") or "unknown")
        record_types[record_type] += 1
        item = record.get("item") if isinstance(record.get("item"), dict) else {}
        if item:
            item_type = str(item.get("type") or "unknown")
            item_types[item_type] += 1
            if record_type == "item.completed":
                if item_type == "command_execution":
                    completed_tools += 1
                    completed_tool_output_chars += len(str(item.get("aggregated_output") or ""))
                    completed_items.append(
                        {
                            "type": item_type,
                            "id": item.get("id"),
                            "exit_code": item.get("exit_code"),
                            "command": _short(item.get("command")),
                            "output_chars": len(str(item.get("aggregated_output") or "")),
                            "output_preview": _short(item.get("aggregated_output")),
                            "ts": event.get("observer_ts"),
                        }
                    )
                elif item_type == "agent_message":
                    text = str(item.get("text") or "")
                    completed_agent_message_chars += len(text)
                    completed_items.append(
                        {
                            "type": item_type,
                            "id": item.get("id"),
                            "text_chars": len(text),
                            "text_preview": _short(text),
                            "ts": event.get("observer_ts"),
                        }
                    )

    return {
        "event_count": len(events),
        "record_types": dict(sorted(record_types.items())),
        "item_types": dict(sorted(item_types.items())),
        "completed_tool_count": completed_tools,
        "completed_tool_output_chars": completed_tool_output_chars,
        "completed_agent_message_chars": completed_agent_message_chars,
        "completed_item_samples": completed_items[:12],
    }


def _new_memory_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    type_counts: Counter[str] = Counter()
    layer_chars: dict[str, int] = defaultdict(int)
    tool_pairs: dict[str, dict[str, Any]] = {}
    assistant_chars = 0

    for item in items:
        item_type = str(item.get("type") or "unknown")
        layer = str(item.get("semantic_layer") or "unknown")
        chars = _item_chars(item)
        type_counts[item_type] += 1
        layer_chars[layer] += chars
        if layer == "assistant_memory":
            assistant_chars += chars
        call_id = item.get("call_id")
        if call_id:
            rec = tool_pairs.setdefault(
                str(call_id),
                {
                    "call_id": str(call_id),
                    "tool_name": None,
                    "command": None,
                    "call_chars": 0,
                    "output_chars": 0,
                    "output_preview": None,
                },
            )
            if item_type in {"function_call", "custom_tool_call", "local_shell_call"}:
                rec["tool_name"] = item.get("name")
                rec["command"] = _short(_call_command(item))
                rec["call_chars"] = chars
            elif item_type in {"function_call_output", "custom_tool_call_output"}:
                rec["output_chars"] = chars
                rec["output_preview"] = _short(item.get("capture"))

    pairs = sorted(
        tool_pairs.values(),
        key=lambda rec: int(rec.get("call_chars") or 0) + int(rec.get("output_chars") or 0),
        reverse=True,
    )
    return {
        "item_count": len(items),
        "chars": sum(_item_chars(item) for item in items),
        "type_counts": dict(sorted(type_counts.items())),
        "layer_chars": dict(sorted(layer_chars.items())),
        "assistant_chars": assistant_chars,
        "tool_pairs": pairs,
        "top_tool_pairs": pairs[:10],
    }


def derive_turn_ledger(run_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    requests = _load_jsonl(run_dir / "prompt_payloads.jsonl")
    if not requests:
        raise FileNotFoundError(f"No prompt payload records found at {run_dir / 'prompt_payloads.jsonl'}")

    new_by_request = _new_memory_items(requests)
    events_by_request = _events_by_interval(run_dir, requests)
    ledger: list[dict[str, Any]] = []

    for fallback_index, request in enumerate(requests, start=1):
        request_index = int(request.get("request_index") or fallback_index)
        memory_items = [item for item in _items(request) if _is_memory_item(item)]
        next_new_items = new_by_request.get(request_index + 1, [])
        event_summary = _event_summary(events_by_request.get(request_index, []))
        next_memory_summary = _new_memory_summary(next_new_items)
        ledger.append(
            {
                "request_index": request_index,
                "request_id": request.get("request_id"),
                "ts": request.get("ts"),
                "model": request.get("model"),
                "path": request.get("path"),
                "request_kind": request.get("request_kind"),
                "window_id": request.get("window_id"),
                "body_chars": _body_chars(request),
                "visible_memory_item_count": len(memory_items),
                "visible_memory_chars": sum(_item_chars(item) for item in memory_items),
                "observed_events_after_request": event_summary,
                "new_memory_materialized_in_next_request": {
                    **next_memory_summary,
                    "next_request_index": request_index + 1 if request_index < len(requests) else None,
                },
            }
        )

    total_new_chars = sum(
        int((record.get("new_memory_materialized_in_next_request") or {}).get("chars") or 0)
        for record in ledger
    )
    summary = {
        "run_id": run_dir.name,
        "request_count": len(requests),
        "turn_count": len(ledger),
        "total_new_memory_materialized_chars": total_new_chars,
        "total_completed_tool_output_chars": sum(
            int((record.get("observed_events_after_request") or {}).get("completed_tool_output_chars") or 0)
            for record in ledger
        ),
        "total_completed_agent_message_chars": sum(
            int((record.get("observed_events_after_request") or {}).get("completed_agent_message_chars") or 0)
            for record in ledger
        ),
        "max_materialization_turn": max(
            ledger,
            key=lambda record: int(
                (record.get("new_memory_materialized_in_next_request") or {}).get("chars") or 0
            ),
        )
        if ledger
        else None,
        "interpretation": (
            "Each ledger row should be read as visible context for request N, "
            "then events observed after that request, then new memory first "
            "materialized in request N+1. This is a general transition view, "
            "not a task-specific conclusion."
        ),
    }
    return ledger, summary


def write_turn_ledger(run_dir: Path) -> dict[str, Any]:
    ledger, summary = derive_turn_ledger(run_dir)
    with (run_dir / "codex_turn_ledger.jsonl").open("w", encoding="utf-8") as f:
        for record in ledger:
            f.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
    with (run_dir / "codex_turn_ledger_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True, ensure_ascii=False)
    _write_markdown(run_dir, ledger, summary)
    return summary


def _fmt(value: Any) -> str:
    return f"{int(value or 0):,}"


def _write_markdown(run_dir: Path, ledger: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    lines = [
        f"# Codex Turn Ledger - {run_dir.name}",
        "",
        "Each row is a state transition: request-visible memory, observed events",
        "after that request, and new memory first materialized in the following",
        "request.",
        "",
        "## Summary",
        "",
        f"- Requests: {_fmt(summary.get('request_count'))}",
        f"- New memory materialized: {_fmt(summary.get('total_new_memory_materialized_chars'))} chars",
        f"- Completed tool output observed: {_fmt(summary.get('total_completed_tool_output_chars'))} chars",
        f"- Completed agent message text observed: {_fmt(summary.get('total_completed_agent_message_chars'))} chars",
        "",
        "## Timeline",
        "",
        "| request | visible memory chars | events | tool output chars after request | agent text chars after request | new memory chars in next request | new memory types |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for record in ledger:
        events = record.get("observed_events_after_request") or {}
        new_memory = record.get("new_memory_materialized_in_next_request") or {}
        lines.append(
            "| "
            f"{record.get('request_index')} | "
            f"{_fmt(record.get('visible_memory_chars'))} | "
            f"{_fmt(events.get('event_count'))} | "
            f"{_fmt(events.get('completed_tool_output_chars'))} | "
            f"{_fmt(events.get('completed_agent_message_chars'))} | "
            f"{_fmt(new_memory.get('chars'))} | "
            f"`{json.dumps(new_memory.get('type_counts') or {}, sort_keys=True)}` |"
        )

    max_turn = summary.get("max_materialization_turn") or {}
    max_new = max_turn.get("new_memory_materialized_in_next_request") or {}
    lines.extend(
        [
            "",
            "## Largest Materialization",
            "",
            f"- Request {max_turn.get('request_index')} produced {_fmt(max_new.get('chars'))} chars first visible in request {max_new.get('next_request_index')}.",
        ]
    )
    for pair in max_new.get("top_tool_pairs") or []:
        total = int(pair.get("call_chars") or 0) + int(pair.get("output_chars") or 0)
        label = pair.get("command") or pair.get("output_preview") or pair.get("call_id")
        lines.append(f"- {_fmt(total)} chars; {_short(label)}")

    (run_dir / "codex_turn_ledger.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Codex request/event/next-context turn ledgers")
    parser.add_argument("run_dirs", nargs="+", type=Path)
    args = parser.parse_args()

    for run_dir in args.run_dirs:
        summary = write_turn_ledger(run_dir)
        print(f"Wrote Codex turn ledger for {run_dir}")
        print(f"  requests: {summary['request_count']}")
        print(f"  new memory chars: {summary['total_new_memory_materialized_chars']}")


if __name__ == "__main__":
    main()
