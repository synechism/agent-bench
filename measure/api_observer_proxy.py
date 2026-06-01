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


def _summarize_messages(messages: Any) -> dict[str, Any]:
    if not isinstance(messages, list):
        return {"count": 0}

    by_role: dict[str, int] = {}
    message_summaries: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            message_summaries.append({"index": index, "shape": type(message).__name__})
            continue
        role = str(message.get("role", "unknown"))
        by_role[role] = by_role.get(role, 0) + 1
        content = _content_text(message.get("content"))
        summary = {
            "index": index,
            "role": role,
            "content": _textish_size_and_hash(content),
        }
        if "type" in message:
            summary["type"] = message.get("type")
        message_summaries.append(summary)

    return {
        "count": len(messages),
        "by_role": by_role,
        "messages": message_summaries,
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
        "schema": _json_size_and_hash(tools),
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
        summary["instructions"] = _textish_size_and_hash(data.get("instructions"))
    if "system" in data:
        summary["system"] = _textish_size_and_hash(data.get("system"))
    if "messages" in data:
        summary["messages"] = _summarize_messages(data.get("messages"))
    if "input" in data:
        summary["input"] = _summarize_messages(data.get("input"))
    if "tools" in data:
        summary["tools"] = _summarize_tools(data.get("tools"))

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
