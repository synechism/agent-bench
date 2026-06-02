"""Derive semantic context-window usage from observed model API requests.

This is intentionally orthogonal to process memory. It answers:

- what semantic layers were serialized into each model request?
- how did the prompt/context payload grow over time?
- how much was fixed harness prompt/tool schema vs carried conversation/tool
  output state?
- when did compaction or context-window generation changes appear?

It works best with new runs from `measure.api_observer_proxy`, especially when
`HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1` is enabled for controlled benchmark
repos. Older runs still get useful size/hash/timeline metrics.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


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


def _approx_tokens(chars: int | float | None) -> int:
    return (max(0, int(chars or 0)) + 3) // 4


def _layer_chars(payload: dict[str, Any]) -> dict[str, int]:
    layers = payload.get("semantic_layers")
    if isinstance(layers, dict):
        return {str(name): int((rec or {}).get("chars") or 0) for name, rec in layers.items()}

    # Back-compat for older observer logs. These logs summarized `input` like
    # chat messages, so we can separate static prompt/tool schema from broad
    # role buckets but not tool-output internals.
    result: dict[str, int] = {}
    instructions = payload.get("instructions")
    if isinstance(instructions, dict):
        result["base_instructions"] = int(instructions.get("chars") or 0)
    system = payload.get("system")
    if isinstance(system, dict):
        result["system_instructions"] = int(system.get("chars") or 0)
    tools = payload.get("tools")
    if isinstance(tools, dict):
        result["tool_schema"] = int((tools.get("schema") or {}).get("chars") or 0)
    input_payload = payload.get("input")
    if isinstance(input_payload, dict):
        for item in input_payload.get("messages") or []:
            if not isinstance(item, dict):
                continue
            chars = int((item.get("content") or {}).get("chars") or 0)
            role = str(item.get("role") or "unknown")
            item_type = str(item.get("type") or "")
            if role == "developer":
                layer = "developer_context"
            elif role == "user":
                layer = "user_or_task"
            elif role == "assistant":
                layer = "assistant_memory"
            elif item_type in {"function_call", "custom_tool_call"}:
                layer = "tool_call_memory"
            elif item_type in {"function_call_output", "custom_tool_call_output"}:
                layer = "tool_output_memory"
            else:
                layer = "other_input"
            result[layer] = result.get(layer, 0) + chars
    messages_payload = payload.get("messages")
    if isinstance(messages_payload, dict):
        for layer, rec in (messages_payload.get("by_semantic_layer") or {}).items():
            result[str(layer)] = result.get(str(layer), 0) + int((rec or {}).get("chars") or 0)
        if not messages_payload.get("by_semantic_layer"):
            for message in messages_payload.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                chars = int((message.get("content") or {}).get("chars") or 0)
                role = str(message.get("role") or "unknown")
                if role == "system":
                    layer = "developer_context"
                elif role == "assistant":
                    layer = "assistant_memory"
                elif role == "user":
                    layer = "user_or_task"
                else:
                    layer = "message_context"
                result[layer] = result.get(layer, 0) + chars
    return result


def _request_kind(record: dict[str, Any]) -> tuple[str | None, str | None]:
    headers = record.get("headers") if isinstance(record.get("headers"), dict) else {}
    metadata_raw = headers.get("x-codex-turn-metadata")
    if not isinstance(metadata_raw, str):
        return None, headers.get("x-codex-window-id") if isinstance(headers, dict) else None
    try:
        metadata = json.loads(metadata_raw)
    except json.JSONDecodeError:
        return None, headers.get("x-codex-window-id")
    return (
        str(metadata.get("request_kind")) if metadata.get("request_kind") else None,
        str(metadata.get("window_id")) if metadata.get("window_id") else headers.get("x-codex-window-id"),
    )


def _input_counts(payload: dict[str, Any]) -> dict[str, Any]:
    input_payload = payload.get("input") if isinstance(payload.get("input"), dict) else payload.get("messages")
    if not isinstance(input_payload, dict):
        return {"input_count": 0, "by_type": {}, "by_role": {}}
    return {
        "input_count": int(input_payload.get("count") or 0),
        "by_type": input_payload.get("by_type") or {},
        "by_role": input_payload.get("by_role") or {},
    }


def _hash_of(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, dict):
        return None
    if key == "tools":
        schema = value.get("schema")
        return str(schema.get("sha256")) if isinstance(schema, dict) and schema.get("sha256") else None
    return str(value.get("sha256")) if value.get("sha256") else None


def _has_captured_text(payload: dict[str, Any]) -> bool:
    if isinstance(payload.get("instructions"), dict) and payload["instructions"].get("capture"):
        return True
    if isinstance(payload.get("system"), dict) and payload["system"].get("capture"):
        return True
    input_payload = payload.get("input")
    if isinstance(input_payload, dict):
        for item in input_payload.get("items") or input_payload.get("messages") or []:
            content = item.get("payload") or item.get("content") if isinstance(item, dict) else None
            if isinstance(content, dict) and content.get("capture"):
                return True
            if isinstance(item, dict):
                for block in item.get("blocks") or []:
                    payload_summary = block.get("payload") if isinstance(block, dict) else None
                    if isinstance(payload_summary, dict) and payload_summary.get("capture"):
                        return True
    messages_payload = payload.get("messages")
    if isinstance(messages_payload, dict):
        for message in messages_payload.get("messages") or []:
            if not isinstance(message, dict):
                continue
            if isinstance(message.get("content"), dict) and message["content"].get("capture"):
                return True
            for block in message.get("blocks") or []:
                payload_summary = block.get("payload") if isinstance(block, dict) else None
                if isinstance(payload_summary, dict) and payload_summary.get("capture"):
                    return True
    return False


def _largest_tool_outputs(payload: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    calls: dict[str, dict[str, Any]] = {}
    outputs: list[dict[str, Any]] = []
    input_payload = payload.get("input")
    if isinstance(input_payload, dict) and isinstance(input_payload.get("items"), list):
        for item in input_payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            call_id = item.get("call_id")
            if not call_id:
                continue
            if item.get("type") in {"function_call", "custom_tool_call", "local_shell_call"}:
                calls[str(call_id)] = item
            elif item.get("type") in {"function_call_output", "custom_tool_call_output"}:
                outputs.append(item)
    messages_payload = payload.get("messages")
    if isinstance(messages_payload, dict):
        for message in messages_payload.get("messages") or []:
            if not isinstance(message, dict):
                continue
            for block in message.get("blocks") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("id"):
                    calls[str(block.get("id"))] = {
                        "call_id": block.get("id"),
                        "name": block.get("name"),
                        "payload": block.get("payload"),
                    }
                elif block.get("type") == "tool_result" and block.get("tool_use_id"):
                    outputs.append(
                        {
                            "call_id": block.get("tool_use_id"),
                            "type": "tool_result",
                            "payload": block.get("payload"),
                        }
                    )

    ranked: list[dict[str, Any]] = []
    for output in outputs:
        payload_summary = output.get("payload") if isinstance(output.get("payload"), dict) else {}
        call = calls.get(str(output.get("call_id"))) or {}
        call_payload = call.get("payload") if isinstance(call.get("payload"), dict) else {}
        ranked.append(
            {
                "call_id": output.get("call_id"),
                "tool_name": call.get("name"),
                "output_chars": int(payload_summary.get("chars") or 0),
                "output_approx_tokens": int(payload_summary.get("approx_tokens") or 0),
                "call_capture": call_payload.get("capture"),
                "output_capture_preview": (
                    str(payload_summary.get("capture"))[:1000]
                    if payload_summary.get("capture") is not None
                    else None
                ),
            }
        )

    return sorted(ranked, key=lambda item: item["output_chars"], reverse=True)[:limit]


def _memory_vs_static_layers(layers: dict[str, int]) -> dict[str, int]:
    static_names = {
        "base_instructions",
        "system_instructions",
        "tool_schema",
        "developer_context",
        "user_or_task",
    }
    memory_names = {
        "assistant_memory",
        "tool_call_memory",
        "tool_output_memory",
        "reasoning_or_compaction_memory",
        "message_context",
        "other_input",
    }
    static_chars = sum(chars for name, chars in layers.items() if name in static_names)
    memory_chars = sum(chars for name, chars in layers.items() if name in memory_names)
    return {
        "static_prompt_chars": static_chars,
        "carried_memory_chars": memory_chars,
        "file_or_tool_output_chars": int(layers.get("tool_output_memory", 0)),
        "assistant_reasoning_chars": int(layers.get("assistant_memory", 0))
        + int(layers.get("reasoning_or_compaction_memory", 0)),
    }


def derive_semantic_context(run_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    api_records = [
        record
        for record in _load_jsonl(run_dir / "api_requests.jsonl")
        if record.get("event") == "api_request"
    ]

    timeline: list[dict[str, Any]] = []
    previous_body_chars: int | None = None
    previous_layer_chars: dict[str, int] | None = None
    instruction_hashes: Counter[str] = Counter()
    system_hashes: Counter[str] = Counter()
    tool_schema_hashes: Counter[str] = Counter()
    request_kinds: Counter[str] = Counter()
    window_ids: Counter[str] = Counter()
    max_record: dict[str, Any] | None = None
    max_body_record: dict[str, Any] | None = None
    max_body_payload: dict[str, Any] | None = None
    totals_by_layer: dict[str, int] = defaultdict(int)

    for request_index, record in enumerate(api_records, start=1):
        payload = record.get("json") if isinstance(record.get("json"), dict) else {}
        layers = _layer_chars(payload)
        for name, chars in layers.items():
            totals_by_layer[name] += chars

        body_chars = int((payload.get("body") or {}).get("chars") or record.get("request_bytes") or 0)
        layer_total_chars = sum(layers.values())
        unclassified_serialization_chars = max(0, body_chars - layer_total_chars)
        semantic_tokens = _approx_tokens(layer_total_chars)
        request_kind, window_id = _request_kind(record)
        if request_kind:
            request_kinds[request_kind] += 1
        if window_id:
            window_ids[window_id] += 1
        instruction_hash = _hash_of(payload, "instructions")
        system_hash = _hash_of(payload, "system")
        tool_schema_hash = _hash_of(payload, "tools")
        if instruction_hash:
            instruction_hashes[instruction_hash] += 1
        if system_hash:
            system_hashes[system_hash] += 1
        if tool_schema_hash:
            tool_schema_hashes[tool_schema_hash] += 1

        layer_deltas = {}
        if previous_layer_chars is not None:
            all_layer_names = set(previous_layer_chars) | set(layers)
            layer_deltas = {
                name: int(layers.get(name, 0) - previous_layer_chars.get(name, 0))
                for name in sorted(all_layer_names)
            }

        record_out = {
            "request_index": request_index,
            "request_id": record.get("request_id"),
            "ts": record.get("ts"),
            "model": payload.get("model"),
            "path": record.get("path"),
            "request_kind": request_kind,
            "window_id": window_id,
            "request_bytes": int(record.get("request_bytes") or 0),
            "body_chars": body_chars,
            "body_delta_chars": None if previous_body_chars is None else body_chars - previous_body_chars,
            "semantic_layer_chars": layers,
            "semantic_layer_delta_chars": layer_deltas,
            "semantic_total_chars": layer_total_chars,
            "semantic_total_approx_tokens": semantic_tokens,
            "body_approx_tokens": _approx_tokens(body_chars),
            "memory_vs_static": {
                **_memory_vs_static_layers(layers),
                "unclassified_serialization_chars": unclassified_serialization_chars,
                "unclassified_serialization_note": (
                    "Bytes in the request body not assigned to a semantic layer. "
                    "Older api_requests logs did not break down ResponseItem tool "
                    "outputs, so file/tool memory may appear here until the run is "
                    "repeated with the upgraded observer."
                ),
            },
            "input": _input_counts(payload),
            "instructions_hash": instruction_hash,
            "system_hash": system_hash,
            "tool_schema_hash": tool_schema_hash,
            "capture_present": _has_captured_text(payload),
        }
        timeline.append(record_out)
        previous_body_chars = body_chars
        previous_layer_chars = layers
        if max_record is None or layer_total_chars > int(max_record["semantic_total_chars"]):
            max_record = record_out
        if max_body_record is None or body_chars > int(max_body_record["body_chars"]):
            max_body_record = record_out
            max_body_payload = payload

    unique_instruction_chars = 0
    unique_system_chars = 0
    unique_tool_schema_chars = 0
    seen_instruction_hashes: set[str] = set()
    seen_system_hashes: set[str] = set()
    seen_tool_hashes: set[str] = set()
    for record in timeline:
        if record.get("instructions_hash") and record["instructions_hash"] not in seen_instruction_hashes:
            seen_instruction_hashes.add(record["instructions_hash"])
            unique_instruction_chars += int(record["semantic_layer_chars"].get("base_instructions", 0))
        if record.get("system_hash") and record["system_hash"] not in seen_system_hashes:
            seen_system_hashes.add(record["system_hash"])
            unique_system_chars += int(record["semantic_layer_chars"].get("system_instructions", 0))
        if record.get("tool_schema_hash") and record["tool_schema_hash"] not in seen_tool_hashes:
            seen_tool_hashes.add(record["tool_schema_hash"])
            unique_tool_schema_chars += int(record["semantic_layer_chars"].get("tool_schema", 0))

    serialized_instruction_chars = sum(
        int(record["semantic_layer_chars"].get("base_instructions", 0)) for record in timeline
    )
    serialized_tool_schema_chars = sum(
        int(record["semantic_layer_chars"].get("tool_schema", 0)) for record in timeline
    )
    serialized_system_chars = sum(
        int(record["semantic_layer_chars"].get("system_instructions", 0)) for record in timeline
    )
    serialized_unclassified_chars = sum(
        int((record.get("memory_vs_static") or {}).get("unclassified_serialization_chars") or 0)
        for record in timeline
    )

    summary = {
        "run_id": run_dir.name,
        "request_count": len(timeline),
        "request_kinds": dict(sorted(request_kinds.items())),
        "window_ids": dict(sorted(window_ids.items())),
        "max_semantic_request": max_record,
        "max_body_request": max_body_record,
        "largest_tool_outputs_at_max_body_request": (
            _largest_tool_outputs(max_body_payload or {}) if max_body_payload else []
        ),
        "serialized_layer_chars": dict(sorted(totals_by_layer.items())),
        "serialized_layer_approx_tokens": {
            name: _approx_tokens(chars) for name, chars in sorted(totals_by_layer.items())
        },
        "repeated_static_overhead": {
            "unique_instruction_hashes": len(instruction_hashes),
            "unique_system_hashes": len(system_hashes),
            "unique_tool_schema_hashes": len(tool_schema_hashes),
            "serialized_instruction_chars": serialized_instruction_chars,
            "unique_instruction_chars": unique_instruction_chars,
            "repeated_instruction_chars": max(0, serialized_instruction_chars - unique_instruction_chars),
            "serialized_system_chars": serialized_system_chars,
            "unique_system_chars": unique_system_chars,
            "repeated_system_chars": max(0, serialized_system_chars - unique_system_chars),
            "serialized_tool_schema_chars": serialized_tool_schema_chars,
            "unique_tool_schema_chars": unique_tool_schema_chars,
            "repeated_tool_schema_chars": max(0, serialized_tool_schema_chars - unique_tool_schema_chars),
        },
        "serialized_unclassified_body_chars": serialized_unclassified_chars,
        "capture_present": any(record.get("capture_present") for record in timeline),
        "capture_note": (
            "Set HARNESS_API_OBSERVER_CAPTURE_PROMPTS=1 for controlled runs to "
            "store sanitized prompt snippets/fields in api_requests.jsonl. Without "
            "that, this report uses sizes, hashes, roles, item types, and layers."
        ),
    }
    return timeline, summary


def write_semantic_context(run_dir: Path) -> dict[str, Any]:
    timeline, summary = derive_semantic_context(run_dir)
    with (run_dir / "semantic_context_timeline.jsonl").open("w") as f:
        for record in timeline:
            f.write(json.dumps(record, sort_keys=True) + "\n")
    with (run_dir / "semantic_context_summary.json").open("w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive semantic context-window usage for a run")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    summary = write_semantic_context(args.run_dir)
    print(f"Wrote semantic context artifacts for {args.run_dir}")
    print(f"  requests: {summary['request_count']}")
    max_req = summary.get("max_semantic_request") or {}
    print(
        "  max semantic request: "
        f"{max_req.get('semantic_total_approx_tokens', 0)} approx tokens "
        f"({max_req.get('semantic_total_chars', 0)} chars)"
    )


if __name__ == "__main__":
    main()
