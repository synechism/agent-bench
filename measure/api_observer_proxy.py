"""Redacting HTTP forwarding proxy for model API instrumentation.

The proxy is intentionally narrow: it forwards requests to a configured
upstream API base URL and logs request/response metadata without prompt bodies,
API keys, or raw response content.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import ssl
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.parse import urlunsplit


HOP_BY_HOP_HEADERS = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

SECRET_HEADER_MARKERS = ("authorization", "api-key", "x-api-key", "token", "cookie", "secret")
MAX_LOGGED_ERROR_CHARS = 500
DEFAULT_CAPTURE_CHARS = 20_000
SECRET_VALUE_RE = re.compile(
    r"(?i)\b("
    r"sk-[a-z0-9_-]{16,}|"
    r"(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s,;]+|"
    r"bearer\s+[a-z0-9._~+/=-]{16,}"
    r")\b"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _json_size_and_hash(value: Any) -> dict[str, Any]:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "chars": len(serialized),
        "sha256": _sha256_text(serialized),
    }


def _textish_size_and_hash(value: Any) -> dict[str, Any]:
    if value is None:
        return {"chars": 0, "sha256": None}
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "chars": len(text),
        "sha256": _sha256_text(text),
    }


def _approx_tokens(chars: int) -> int:
    return (max(0, chars) + 3) // 4


def _capture_enabled() -> bool:
    return os.environ.get("HARNESS_API_OBSERVER_CAPTURE_PROMPTS", "").lower() in {
        "1",
        "true",
        "yes",
    }


def _capture_limit() -> int:
    raw = os.environ.get("HARNESS_API_OBSERVER_CAPTURE_CHARS")
    if not raw:
        return DEFAULT_CAPTURE_CHARS
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_CAPTURE_CHARS


def _sanitize_text(text: str) -> str:
    return SECRET_VALUE_RE.sub("<redacted-secret>", text)


def _maybe_capture(value: Any, *, limit: int | None = None) -> dict[str, Any]:
    if not _capture_enabled():
        return {}
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    text = _sanitize_text(text)
    max_chars = _capture_limit() if limit is None else max(0, limit)
    captured = text[:max_chars]
    return {
        "capture": captured,
        "capture_chars": len(captured),
        "capture_truncated": len(text) > len(captured),
    }


def _maybe_capture_raw_body(body: bytes) -> dict[str, Any]:
    if not _capture_enabled():
        return {}
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = body.decode("utf-8", errors="replace")
    sanitized = _sanitize_text(text)
    max_chars = _capture_limit()
    captured = sanitized[:max_chars]
    return {
        "request_body_capture": {
            "chars": len(sanitized),
            "sha256": _sha256_text(sanitized),
            "capture": captured,
            "capture_chars": len(captured),
            "capture_truncated": len(sanitized) > len(captured),
        }
    }


def _summary_with_capture(value: Any) -> dict[str, Any]:
    summary = _textish_size_and_hash(value)
    summary["approx_tokens"] = _approx_tokens(int(summary.get("chars") or 0))
    summary.update(_maybe_capture(value))
    return summary


def _content_text(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[Any] = []
        for item in value:
            if isinstance(item, dict):
                if "text" in item:
                    parts.append(item.get("text"))
                elif "input_text" in item:
                    parts.append(item.get("input_text"))
                else:
                    parts.append(item)
            else:
                parts.append(item)
        return parts
    return value


def _message_content_summary(content: Any) -> dict[str, Any]:
    textish = _content_text(content)
    return _summary_with_capture(textish)


def _anthropic_block_payload(block: dict[str, Any]) -> Any:
    block_type = str(block.get("type") or "unknown")
    if block_type == "text":
        return block.get("text")
    if block_type == "tool_use":
        return {
            "id": block.get("id"),
            "name": block.get("name"),
            "input": block.get("input"),
        }
    if block_type == "tool_result":
        return block.get("content")
    if block_type in {"thinking", "redacted_thinking"}:
        return block.get("thinking") or block.get("data") or block.get("text") or block
    if "content" in block:
        return _content_text(block.get("content"))
    if "text" in block:
        return block.get("text")
    return block


def _anthropic_block_layer(role: str, block_type: str) -> str:
    if block_type == "tool_result":
        return "tool_output_memory"
    if block_type in {"tool_use", "server_tool_use"}:
        return "tool_call_memory"
    if block_type in {"thinking", "redacted_thinking", "reasoning"}:
        return "reasoning_or_compaction_memory"
    if role == "assistant":
        return "assistant_memory"
    if role == "user":
        return "user_or_task"
    if role == "system":
        return "developer_context"
    return "message_context"


def _summarize_anthropic_blocks(role: str, content: Any) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]], dict[str, int]]:
    if isinstance(content, list):
        raw_blocks = content
    else:
        raw_blocks = [{"type": "text", "text": content}]

    blocks: list[dict[str, Any]] = []
    by_layer: dict[str, dict[str, int]] = {}
    by_type: dict[str, int] = {}
    for block_index, raw_block in enumerate(raw_blocks):
        if isinstance(raw_block, dict):
            block_type = str(raw_block.get("type") or "unknown")
            payload = _anthropic_block_payload(raw_block)
            summary: dict[str, Any] = {
                "index": block_index,
                "type": block_type,
                "semantic_layer": _anthropic_block_layer(role, block_type),
                "payload": _summary_with_capture(payload),
            }
            for key in ("id", "tool_use_id", "name", "is_error"):
                if key in raw_block and not isinstance(raw_block[key], (dict, list)):
                    summary[key] = raw_block[key]
        else:
            block_type = "text"
            summary = {
                "index": block_index,
                "type": block_type,
                "semantic_layer": _anthropic_block_layer(role, block_type),
                "payload": _summary_with_capture(raw_block),
            }

        by_type[block_type] = by_type.get(block_type, 0) + 1
        payload_summary = summary["payload"]
        layer = str(summary["semantic_layer"])
        layer_rec = by_layer.setdefault(layer, {"chars": 0, "approx_tokens": 0, "items": 0})
        layer_rec["chars"] += int(payload_summary.get("chars") or 0)
        layer_rec["approx_tokens"] += int(payload_summary.get("approx_tokens") or 0)
        layer_rec["items"] += 1
        blocks.append(summary)

    return blocks, by_layer, by_type


def _summarize_messages(messages: Any) -> dict[str, Any]:
    if not isinstance(messages, list):
        return {"count": 0}

    by_role: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_layer: dict[str, dict[str, int]] = {}
    message_summaries: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            message_summaries.append({"index": index, "shape": type(message).__name__})
            continue
        role = str(message.get("role", "unknown"))
        by_role[role] = by_role.get(role, 0) + 1
        content = message.get("content")
        blocks, block_layers, block_types = _summarize_anthropic_blocks(role, content)
        for block_type, count in block_types.items():
            by_type[block_type] = by_type.get(block_type, 0) + count
        for layer, rec in block_layers.items():
            layer_rec = by_layer.setdefault(layer, {"chars": 0, "approx_tokens": 0, "items": 0})
            layer_rec["chars"] += int(rec.get("chars") or 0)
            layer_rec["approx_tokens"] += int(rec.get("approx_tokens") or 0)
            layer_rec["items"] += int(rec.get("items") or 0)
        summary = {
            "index": index,
            "role": role,
            "content": _message_content_summary(content),
            "blocks": blocks,
        }
        layers = sorted(block_layers)
        summary["semantic_layer"] = layers[0] if len(layers) == 1 else "mixed"
        if "type" in message:
            summary["type"] = message.get("type")
        message_summaries.append(summary)

    return {
        "count": len(messages),
        "by_role": by_role,
        "by_type": dict(sorted(by_type.items())),
        "by_semantic_layer": dict(sorted(by_layer.items())),
        "messages": message_summaries,
    }


def _response_item_kind(item: dict[str, Any]) -> tuple[str, str]:
    item_type = str(item.get("type") or "unknown")
    role = str(item.get("role") or "unknown")
    if item_type == "message":
        if role == "developer":
            return "developer_context", role
        if role == "user":
            return "user_or_task", role
        if role == "assistant":
            return "assistant_memory", role
        return "message_context", role
    if item_type in {"function_call", "custom_tool_call", "local_shell_call"}:
        return "tool_call_memory", role
    if item_type in {"function_call_output", "custom_tool_call_output", "tool_search_output"}:
        return "tool_output_memory", role
    if item_type in {"reasoning", "compaction", "context_compaction"}:
        return "reasoning_or_compaction_memory", role
    return "other_input", role


def _response_item_payload(item: dict[str, Any]) -> Any:
    item_type = item.get("type")
    if item_type == "message":
        return _content_text(item.get("content"))
    if item_type in {"function_call", "custom_tool_call"}:
        return {
            "name": item.get("name"),
            "call_id": item.get("call_id"),
            "arguments": item.get("arguments") or item.get("input"),
        }
    if item_type == "local_shell_call":
        return item.get("action") or item
    if item_type in {"function_call_output", "custom_tool_call_output"}:
        return item.get("output") or item.get("content")
    if item_type in {"reasoning", "compaction", "context_compaction"}:
        return item.get("encrypted_content") or item.get("summary") or item.get("content")
    if "content" in item:
        return _content_text(item.get("content"))
    return item


def _summarize_response_input_items(items: Any) -> dict[str, Any]:
    """Summarize OpenAI Responses API `input` arrays.

    Codex sends `ResponseItem` objects rather than classic chat messages.
    The old role-only summary hid the expensive pieces: tool outputs, call
    arguments, encrypted reasoning blobs, and contextual developer messages.
    """
    if not isinstance(items, list):
        return {"count": 0}

    by_type: dict[str, int] = {}
    by_role: dict[str, int] = {}
    by_layer: dict[str, dict[str, int]] = {}
    item_summaries: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            item_summaries.append({"index": index, "shape": type(item).__name__})
            continue
        item_type = str(item.get("type") or "unknown")
        layer, role = _response_item_kind(item)
        by_type[item_type] = by_type.get(item_type, 0) + 1
        by_role[role] = by_role.get(role, 0) + 1
        payload = _response_item_payload(item)
        payload_summary = _summary_with_capture(payload)
        layer_rec = by_layer.setdefault(layer, {"chars": 0, "approx_tokens": 0, "items": 0})
        layer_rec["chars"] += int(payload_summary.get("chars") or 0)
        layer_rec["approx_tokens"] += int(payload_summary.get("approx_tokens") or 0)
        layer_rec["items"] += 1

        summary: dict[str, Any] = {
            "index": index,
            "type": item_type,
            "role": role,
            "semantic_layer": layer,
            "payload": payload_summary,
        }
        for key in ("call_id", "name", "status"):
            if key in item and not isinstance(item[key], (dict, list)):
                summary[key] = item[key]
        item_summaries.append(summary)

    return {
        "count": len(items),
        "by_type": dict(sorted(by_type.items())),
        "by_role": dict(sorted(by_role.items())),
        "by_semantic_layer": dict(sorted(by_layer.items())),
        "items": item_summaries,
    }


def _tool_name(tool: Any) -> str:
    if not isinstance(tool, dict):
        return type(tool).__name__
    if isinstance(tool.get("function"), dict) and tool["function"].get("name"):
        return str(tool["function"]["name"])
    if tool.get("name"):
        return str(tool["name"])
    if tool.get("type"):
        return str(tool["type"])
    return "unknown"


def _summarize_tools(tools: Any) -> dict[str, Any]:
    if not isinstance(tools, list):
        return {"count": 0, "names": []}
    names = [_tool_name(tool) for tool in tools]
    return {
        "count": len(tools),
        "names": sorted(set(names)),
        "schema": {**_json_size_and_hash(tools), "approx_tokens": _approx_tokens(len(json.dumps(tools, sort_keys=True, separators=(",", ":"), ensure_ascii=False))), **_maybe_capture(tools)},
    }


def _summarize_request_json(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"json_type": type(data).__name__, "body": _json_size_and_hash(data)}

    summary: dict[str, Any] = {
        "json_keys": sorted(str(key) for key in data.keys()),
    }
    for key in ("model", "max_tokens", "temperature", "stream", "reasoning_effort"):
        if key in data and not isinstance(data[key], (dict, list)):
            summary[key] = data[key]

    if "instructions" in data:
        summary["instructions"] = _summary_with_capture(data.get("instructions"))
    if "system" in data:
        summary["system"] = _summary_with_capture(data.get("system"))
    if "messages" in data:
        summary["messages"] = _summarize_messages(data.get("messages"))
    if "input" in data:
        input_value = data.get("input")
        if isinstance(input_value, list) and any(
            isinstance(item, dict) and "type" in item for item in input_value
        ):
            summary["input"] = _summarize_response_input_items(input_value)
        else:
            summary["input"] = _summarize_messages(input_value)
    if "tools" in data:
        summary["tools"] = _summarize_tools(data.get("tools"))

    semantic_layers: dict[str, dict[str, int]] = {}

    def add_layer(name: str, chars: int) -> None:
        rec = semantic_layers.setdefault(name, {"chars": 0, "approx_tokens": 0})
        rec["chars"] += chars
        rec["approx_tokens"] += _approx_tokens(chars)

    if isinstance(summary.get("instructions"), dict):
        add_layer("base_instructions", int(summary["instructions"].get("chars") or 0))
    if isinstance(summary.get("system"), dict):
        add_layer("system_instructions", int(summary["system"].get("chars") or 0))
    if isinstance(summary.get("tools"), dict):
        add_layer("tool_schema", int((summary["tools"].get("schema") or {}).get("chars") or 0))
    input_summary = summary.get("input")
    if isinstance(input_summary, dict):
        for layer, rec in (input_summary.get("by_semantic_layer") or {}).items():
            add_layer(str(layer), int(rec.get("chars") or 0))
    messages_summary = summary.get("messages")
    if isinstance(messages_summary, dict):
        for layer, rec in (messages_summary.get("by_semantic_layer") or {}).items():
            add_layer(str(layer), int(rec.get("chars") or 0))
    if semantic_layers:
        summary["semantic_layers"] = dict(sorted(semantic_layers.items()))

    summary["body"] = _json_size_and_hash(data)
    return summary


def _safe_headers(headers: Any) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, value in headers.items():
        lower = key.lower()
        if any(marker in lower for marker in SECRET_HEADER_MARKERS):
            safe[key] = "<redacted>"
        else:
            safe[key] = str(value)
    return safe


def _redact_url_for_log(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "<redacted>" if parts.query else "", ""))


def _combine_path(upstream_base: str, request_target: str) -> str:
    base = urlsplit(upstream_base)
    base_path = base.path.rstrip("/")
    target = request_target if request_target.startswith("/") else f"/{request_target}"
    if base_path and (target == base_path or target.startswith(f"{base_path}/")):
        return target
    if base_path.endswith("/v1") and target.startswith("/v1/"):
        target = target[len("/v1") :]
    return f"{base_path}{target}" if base_path else target


class ObservingProxy(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        upstream: str,
        provider: str,
        log_path: Path,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.upstream = upstream
        self.provider = provider
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def write_log(self, record: dict[str, Any]) -> None:
        with self.lock, self.log_path.open("a") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")


class ProxyHandler(BaseHTTPRequestHandler):
    server: ObservingProxy
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self._forward()

    def do_POST(self) -> None:
        self._forward()

    def do_PUT(self) -> None:
        self._forward()

    def do_DELETE(self) -> None:
        self._forward()

    def _forward(self) -> None:
        started = time.time()
        request_id = f"api-{time.time_ns()}"
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(content_length) if content_length else b""
        upstream_parts = urlsplit(self.server.upstream)
        target_path = _combine_path(self.server.upstream, self.path)
        request_summary: dict[str, Any] = {
            "request_id": request_id,
            "ts": _utc_now(),
            "event": "api_request",
            "provider": self.server.provider,
            "method": self.command,
            "upstream_scheme": upstream_parts.scheme,
            "upstream_host": upstream_parts.netloc,
            "path": self.path,
            "forward_path": target_path,
            "request_bytes": len(body),
            "headers": _safe_headers(self.headers),
        }
        if body:
            request_summary.update(_maybe_capture_raw_body(body))
            try:
                request_summary["json"] = _summarize_request_json(json.loads(body.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                request_summary["body"] = {
                    "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "parse_error": type(exc).__name__,
                }
        self.server.write_log(request_summary)

        try:
            conn_cls: type[http.client.HTTPConnection]
            conn_kwargs: dict[str, Any] = {"timeout": 600}
            if upstream_parts.scheme == "https":
                conn_cls = http.client.HTTPSConnection
                conn_kwargs["context"] = ssl.create_default_context()
            elif upstream_parts.scheme == "http":
                conn_cls = http.client.HTTPConnection
            else:
                raise ValueError(f"unsupported upstream scheme: {upstream_parts.scheme}")

            forward_headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in HOP_BY_HOP_HEADERS
            }
            forward_headers["Host"] = upstream_parts.netloc
            if body:
                forward_headers["Content-Length"] = str(len(body))

            conn = conn_cls(upstream_parts.netloc, **conn_kwargs)
            conn.request(self.command, target_path, body=body, headers=forward_headers)
            response = conn.getresponse()
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in HOP_BY_HOP_HEADERS:
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()

            response_bytes = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                response_bytes += len(chunk)
                self.wfile.write(chunk)
                self.wfile.flush()

            self.server.write_log(
                {
                    "request_id": request_id,
                    "ts": _utc_now(),
                    "event": "api_response",
                    "provider": self.server.provider,
                    "status": response.status,
                    "reason": response.reason,
                    "duration_s": round(time.time() - started, 6),
                    "response_bytes": response_bytes,
                    "headers": _safe_headers(dict(response.getheaders())),
                }
            )
            conn.close()
        except Exception as exc:
            self.server.write_log(
                {
                    "request_id": request_id,
                    "ts": _utc_now(),
                    "event": "api_error",
                    "provider": self.server.provider,
                    "duration_s": round(time.time() - started, 6),
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:MAX_LOGGED_ERROR_CHARS],
                }
            )
            message = f"proxy error: {type(exc).__name__}\n".encode()
            try:
                self.send_response(502)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(message)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(message)
            except OSError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a redacting API observer proxy")
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, default=None)
    args = parser.parse_args()

    server = ObservingProxy(
        (args.listen_host, args.port),
        ProxyHandler,
        upstream=args.upstream,
        provider=args.provider,
        log_path=args.log,
    )
    if args.ready_file:
        args.ready_file.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "host": args.listen_host,
                    "port": server.server_port,
                    "upstream": _redact_url_for_log(args.upstream),
                    "provider": args.provider,
                    "log": str(args.log),
                },
                indent=2,
            )
            + "\n"
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    sys.exit(0)


if __name__ == "__main__":
    main()
