"""Write human-readable and machine-readable prompt payload captures.

This complements `analysis.semantic_context`: that script measures semantic
layers, while this one answers "what strings were actually present?" for runs
where the API observer had prompt capture enabled.
"""

from __future__ import annotations

import argparse
import json
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


def _capture(summary: Any) -> str | None:
    if isinstance(summary, dict) and isinstance(summary.get("capture"), str):
        return summary["capture"]
    return None


def _capture_meta(summary: Any) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {}
    return {
        "chars": int(summary.get("chars") or 0),
        "approx_tokens": int(summary.get("approx_tokens") or 0),
        "sha256": summary.get("sha256"),
        "capture_chars": int(summary.get("capture_chars") or 0),
        "capture_truncated": bool(summary.get("capture_truncated")),
    }


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


def _prompt_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    input_summary = payload.get("input")
    if not isinstance(input_summary, dict):
        return []
    items = input_summary.get("items") or input_summary.get("messages") or []
    if not isinstance(items, list):
        return []

    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        payload_summary = item.get("payload") or item.get("content")
        out.append(
            {
                "index": item.get("index"),
                "type": item.get("type"),
                "role": item.get("role"),
                "semantic_layer": item.get("semantic_layer"),
                "name": item.get("name"),
                "call_id": item.get("call_id"),
                "status": item.get("status"),
                "meta": _capture_meta(payload_summary),
                "capture": _capture(payload_summary),
            }
        )
    return out


def _extract_requests(run_dir: Path) -> list[dict[str, Any]]:
    records = [
        record
        for record in _load_jsonl(run_dir / "api_requests.jsonl")
        if record.get("event") == "api_request"
    ]

    requests: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        payload = record.get("json") if isinstance(record.get("json"), dict) else {}
        request_kind, window_id = _request_kind(record)
        raw_body = record.get("request_body_capture")
        tools_summary = payload.get("tools") if isinstance(payload.get("tools"), dict) else {}
        tool_schema_summary = tools_summary.get("schema") if isinstance(tools_summary, dict) else None
        input_summary = payload.get("input") if isinstance(payload.get("input"), dict) else {}
        requests.append(
            {
                "request_index": index,
                "request_id": record.get("request_id"),
                "ts": record.get("ts"),
                "path": record.get("path"),
                "request_kind": request_kind,
                "window_id": window_id,
                "request_bytes": int(record.get("request_bytes") or 0),
                "model": payload.get("model"),
                "body": payload.get("body"),
                "semantic_layers": payload.get("semantic_layers") or {},
                "instructions": {
                    **_capture_meta(payload.get("instructions")),
                    "capture": _capture(payload.get("instructions")),
                },
                "tools": {
                    "count": tools_summary.get("count"),
                    "names": tools_summary.get("names") or [],
                    "schema": {
                        **_capture_meta(tool_schema_summary),
                        "capture": _capture(tool_schema_summary),
                    },
                },
                "raw_request_body": raw_body if isinstance(raw_body, dict) else None,
                "input": {
                    "count": input_summary.get("count") or 0,
                    "by_type": input_summary.get("by_type") or {},
                    "by_role": input_summary.get("by_role") or {},
                    "items": _prompt_items(payload),
                },
            }
        )
    return requests


def _code_block(text: str | None, language: str = "text") -> str:
    if text is None:
        return "_No capture present._\n"
    longest = 0
    current = 0
    for char in text:
        if char == "`":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text}\n{fence}\n"


def _unique_blocks(requests: list[dict[str, Any]], dotted_path: tuple[str, ...]) -> list[dict[str, Any]]:
    by_hash: dict[str, dict[str, Any]] = {}
    for request in requests:
        node: Any = request
        for part in dotted_path:
            node = node.get(part) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            continue
        digest = node.get("sha256")
        if not digest or digest in by_hash:
            continue
        by_hash[str(digest)] = node
    return list(by_hash.values())


def _write_jsonl(requests: list[dict[str, Any]], path: Path) -> None:
    with path.open("w") as f:
        for request in requests:
            f.write(json.dumps(request, sort_keys=True, ensure_ascii=False) + "\n")


def _write_markdown(requests: list[dict[str, Any]], path: Path) -> None:
    lines: list[str] = []
    lines.append(f"# Prompt Payload Report - {path.parent.name}")
    lines.append("")
    lines.append(
        "This report is built from sanitized captures in `api_requests.jsonl`. "
        "It shows the strings Codex sent to the model API, organized by request "
        "and semantic layer. If a field is marked truncated, increase "
        "`HARNESS_API_OBSERVER_CAPTURE_CHARS` for the next run."
    )
    lines.append("")
    lines.append(f"- API requests: {len(requests)}")
    capture_count = sum(
        1
        for request in requests
        if request["instructions"].get("capture")
        or request["tools"]["schema"].get("capture")
        or any(item.get("capture") for item in request["input"]["items"])
    )
    lines.append(f"- Requests with semantic captures: {capture_count}")
    raw_count = sum(1 for request in requests if request.get("raw_request_body"))
    lines.append(f"- Requests with full raw-body captures: {raw_count}")
    lines.append("")

    lines.append("## Static Prompt Blocks")
    lines.append("")
    for block_index, block in enumerate(_unique_blocks(requests, ("instructions",)), start=1):
        lines.append(f"### Base Instructions {block_index}")
        lines.append("")
        lines.append(
            f"- chars: {block.get('chars', 0)}; approx tokens: {block.get('approx_tokens', 0)}; "
            f"sha256: `{block.get('sha256')}`; truncated: `{block.get('capture_truncated')}`"
        )
        lines.append("")
        lines.append(_code_block(block.get("capture")))
    for block_index, block in enumerate(_unique_blocks(requests, ("tools", "schema")), start=1):
        lines.append(f"### Tool Schema {block_index}")
        lines.append("")
        lines.append(
            f"- chars: {block.get('chars', 0)}; approx tokens: {block.get('approx_tokens', 0)}; "
            f"sha256: `{block.get('sha256')}`; truncated: `{block.get('capture_truncated')}`"
        )
        first_request = next(
            (
                request
                for request in requests
                if request["tools"]["schema"].get("sha256") == block.get("sha256")
            ),
            None,
        )
        names = (first_request or {}).get("tools", {}).get("names") or []
        if names:
            lines.append(f"- tool names: `{', '.join(str(name) for name in names)}`")
        lines.append("")
        lines.append(_code_block(block.get("capture"), "json"))

    lines.append("## Requests")
    lines.append("")
    for request in requests:
        body = request.get("body") if isinstance(request.get("body"), dict) else {}
        lines.append(f"### Request {request['request_index']}")
        lines.append("")
        lines.append(f"- request id: `{request.get('request_id')}`")
        lines.append(f"- timestamp: `{request.get('ts')}`")
        lines.append(f"- model/path: `{request.get('model')}` `{request.get('path')}`")
        lines.append(f"- request kind/window: `{request.get('request_kind')}` `{request.get('window_id')}`")
        lines.append(f"- body chars: {body.get('chars', request.get('request_bytes', 0))}")
        lines.append(f"- semantic layers: `{json.dumps(request.get('semantic_layers') or {}, sort_keys=True)}`")
        input_counts = {
            "count": request["input"].get("count"),
            "by_type": request["input"].get("by_type"),
            "by_role": request["input"].get("by_role"),
        }
        lines.append(f"- input counts: `{json.dumps(input_counts, sort_keys=True)}`")
        lines.append("")

        raw_body = request.get("raw_request_body")
        if isinstance(raw_body, dict):
            lines.append("#### Full Request Body")
            lines.append("")
            lines.append(
                f"- chars: {raw_body.get('chars', 0)}; sha256: `{raw_body.get('sha256')}`; "
                f"truncated: `{raw_body.get('capture_truncated')}`"
            )
            lines.append("")
            lines.append(_code_block(raw_body.get("capture"), "json"))

        lines.append("#### Input Items")
        lines.append("")
        for item in request["input"]["items"]:
            meta = item.get("meta") or {}
            heading = (
                f"item {item.get('index')} | {item.get('semantic_layer')} | "
                f"type={item.get('type')} role={item.get('role')}"
            )
            if item.get("name"):
                heading += f" name={item.get('name')}"
            if item.get("call_id"):
                heading += f" call_id={item.get('call_id')}"
            lines.append(f"##### {heading}")
            lines.append("")
            lines.append(
                f"- chars: {meta.get('chars', 0)}; approx tokens: {meta.get('approx_tokens', 0)}; "
                f"sha256: `{meta.get('sha256')}`; truncated: `{meta.get('capture_truncated')}`"
            )
            lines.append("")
            lines.append(_code_block(item.get("capture"), "json" if item.get("type") == "function_call" else "text"))
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def write_prompt_payloads(run_dir: Path) -> dict[str, Any]:
    requests = _extract_requests(run_dir)
    jsonl_path = run_dir / "prompt_payloads.jsonl"
    md_path = run_dir / "prompt_payload_report.md"
    _write_jsonl(requests, jsonl_path)
    _write_markdown(requests, md_path)
    return {
        "request_count": len(requests),
        "jsonl": str(jsonl_path),
        "markdown": str(md_path),
        "raw_body_capture_count": sum(1 for request in requests if request.get("raw_request_body")),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Write prompt payload reports for a captured run")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    summary = write_prompt_payloads(args.run_dir)
    print(f"Wrote prompt payload artifacts for {args.run_dir}")
    print(f"  requests: {summary['request_count']}")
    print(f"  raw body captures: {summary['raw_body_capture_count']}")
    print(f"  jsonl: {summary['jsonl']}")
    print(f"  markdown: {summary['markdown']}")


if __name__ == "__main__":
    main()
