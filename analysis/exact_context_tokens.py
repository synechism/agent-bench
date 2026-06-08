"""Backfill exact provider input-token counts for captured representative runs.

Claude Code requests are already Anthropic Messages shaped, so they can be sent
directly to the provider count_tokens endpoint. Codex requests were captured
before Moonbridge converted OpenAI Responses payloads to Anthropic Messages, so
this script replays each captured Codex request through Moonbridge with a local
fake upstream, captures the converted Anthropic request, and counts that.

The output intentionally stores only hashes and counts, not prompt bodies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCENARIO_OUT_DIRS = {
    "redis": ROOT / "docs" / "semantic_memory" / "context_growth_plots_20260604",
    "frontend_plugin": ROOT
    / "docs"
    / "semantic_memory"
    / "context_growth_plots_frontend_plugin_20260605",
    "frontend_package_plugin": ROOT
    / "docs"
    / "semantic_memory"
    / "context_growth_plots_frontend_package_plugin_20260608",
}


@dataclass(frozen=True)
class RunSpec:
    agent: str
    run_dir: Path


REDIS_RUNS = [
    RunSpec(
        "Codex",
        ROOT / "runs" / "20260601T202331_codex_empty_baseline_empty_task_nocap_rep0",
    ),
    RunSpec(
        "Codex",
        ROOT
        / "runs"
        / "20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0",
    ),
    RunSpec(
        "Codex",
        ROOT
        / "runs"
        / "20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0",
    ),
    RunSpec(
        "Codex",
        ROOT
        / "runs"
        / "20260601T202331_codex_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0",
    ),
    RunSpec(
        "Claude Code",
        ROOT / "runs" / "20260602T131620_claude_code_empty_baseline_empty_task_nocap_rep0",
    ),
    RunSpec(
        "Claude Code",
        ROOT
        / "runs"
        / "20260602T131620_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0",
    ),
    RunSpec(
        "Claude Code",
        ROOT
        / "runs"
        / "20260602T131620_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0",
    ),
    RunSpec(
        "Claude Code",
        ROOT
        / "runs"
        / "20260602T131620_claude_code_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0",
    ),
]

FRONTEND_PLUGIN_RUNS = [
    RunSpec(
        "Codex",
        ROOT
        / "runs"
        / "20260605T142450_codex_frontend_plugin_app_frontend_plugin_design_to_playwright_app_nocap_rep0",
    ),
    RunSpec(
        "Claude Code",
        ROOT
        / "runs"
        / "20260605T143603_claude_code_frontend_plugin_app_frontend_plugin_design_to_playwright_app_nocap_rep0",
    ),
]

FRONTEND_PACKAGE_PLUGIN_RUNS = [
    RunSpec(
        "Codex",
        ROOT
        / "runs"
        / "20260608T014957_codex_frontend_package_plugin_app_frontend_package_plugin_ops_console_nocap_rep0",
    ),
    RunSpec(
        "Claude Code",
        ROOT
        / "runs"
        / "20260608T014957_claude_code_frontend_package_plugin_app_frontend_package_plugin_ops_console_nocap_rep0",
    ),
]

SCENARIO_RUNS = {
    "redis": REDIS_RUNS,
    "frontend_plugin": FRONTEND_PLUGIN_RUNS,
    "frontend_package_plugin": FRONTEND_PACKAGE_PLUGIN_RUNS,
}


class CaptureState:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.records: list[dict[str, Any]] = []

    def clear(self) -> None:
        with self.condition:
            self.records.clear()

    def append(self, record: dict[str, Any]) -> None:
        with self.condition:
            self.records.append(record)
            self.condition.notify_all()

    def wait_one(self, timeout: float = 20) -> dict[str, Any]:
        deadline = time.time() + timeout
        with self.condition:
            while not self.records:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError("timed out waiting for Moonbridge upstream request")
                self.condition.wait(remaining)
            return self.records[-1]


CAPTURE = CaptureState()


class FakeAnthropicHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _fmt: str, *_args: Any) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = {}
        CAPTURE.append({"path": self.path, "body": payload})
        if payload.get("stream"):
            self._write_stream(payload)
        else:
            self._write_json(payload)

    def _write_stream(self, payload: dict[str, Any]) -> None:
        model = str(payload.get("model") or "deepseek-v4-pro")
        events = [
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_fake",
                        "type": "message",
                        "role": "assistant",
                        "model": model,
                        "content": [],
                        "usage": {"input_tokens": 1, "output_tokens": 0},
                    },
                },
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "OK"},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 1},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
        data = "".join(
            f"event: {event}\ndata: {json.dumps(body, separators=(',', ':'))}\n\n"
            for event, body in events
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def _write_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(
            {
                "id": "msg_fake",
                "type": "message",
                "role": "assistant",
                "model": payload.get("model") or "deepseek-v4-pro",
                "content": [{"type": "text", "text": "OK"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            separators=(",", ":"),
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _sha_json(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_api_requests(run_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    request_index = 0
    for line in (run_dir / "api_requests.jsonl").read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("event") != "api_request":
            continue
        request_index += 1
        record["_request_index"] = request_index
        if "count_tokens" in str(record.get("path") or ""):
            continue
        rows.append(record)
    return rows


def _captured_body(record: dict[str, Any]) -> dict[str, Any]:
    capture = record.get("request_body_capture") or {}
    if capture.get("capture_truncated"):
        raise ValueError(f"request {record.get('request_id')} capture is truncated")
    return json.loads(str(capture.get("capture") or "{}"))


def _body_capture_truncated(record: dict[str, Any]) -> bool:
    return bool((record.get("request_body_capture") or {}).get("capture_truncated"))


def _claude_stdout_usage_counts(run_dir: Path) -> dict[int, int]:
    """Return exact observed input-token totals keyed by request index.

    Claude Code emits assistant-message usage to stdout. For this harness shape,
    request 1 is a small title/metadata generation that does not appear as an
    assistant message; each unique assistant message id after that maps to the
    next captured generation request. The total active context for that request
    is the non-cached input plus cache read/creation input.
    """

    path = run_dir / "stdout.log"
    if not path.exists():
        return {}

    counts: dict[int, int] = {}
    seen_ids: set[str] = set()
    assistant_index = 0
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("type") != "assistant":
            continue
        message = row.get("message") or {}
        message_id = str(message.get("id") or "")
        if not message_id or message_id in seen_ids:
            continue
        seen_ids.add(message_id)
        assistant_index += 1
        usage = message.get("usage") or {}
        total = (
            int(usage.get("input_tokens") or 0)
            + int(usage.get("cache_read_input_tokens") or 0)
            + int(usage.get("cache_creation_input_tokens") or 0)
        )
        if total:
            counts[assistant_index + 1] = total
    return counts


def _count_tokens(body: dict[str, Any], headers: dict[str, Any] | None = None) -> int:
    base = os.environ.get("ANTHROPIC_BASE_URL")
    token = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("DEEPSEEK_API_KEY")
    if not base or not token:
        raise RuntimeError("ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN/DEEPSEEK_API_KEY are required")

    url = base.rstrip("/") + "/v1/messages/count_tokens?beta=true"
    data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("content-type", "application/json")
    request.add_header("x-api-key", token)
    header_source = headers or {}
    version = (
        header_source.get("anthropic-version")
        or header_source.get("Anthropic-Version")
        or "2023-06-01"
    )
    beta = header_source.get("anthropic-beta") or header_source.get("Anthropic-Beta")
    request.add_header("anthropic-version", str(version))
    if beta:
        request.add_header("anthropic-beta", str(beta))

    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return int(payload["input_tokens"])
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"count_tokens failed after retries: {last_error}")


def _start_fake_upstream() -> tuple[ThreadingHTTPServer, int]:
    port = _free_port()
    server = ThreadingHTTPServer(("0.0.0.0", port), FakeAnthropicHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def _moonbridge_config(fake_port: int) -> str:
    return f"""
mode: "Transform"
log:
  level: "error"
  format: "text"
server:
  addr: "0.0.0.0:38440"
models:
  deepseek-v4-pro:
    context_window: 1000000
    max_output_tokens: 384000
    default_reasoning_level: "high"
    supported_reasoning_levels:
      - effort: "high"
        description: "High reasoning effort"
      - effort: "xhigh"
        description: "Extra high reasoning effort"
    supports_reasoning_summaries: true
    default_reasoning_summary: "auto"
    extensions:
      deepseek_v4:
        enabled: true
  deepseek-v4-flash:
    context_window: 1000000
    max_output_tokens: 384000
    default_reasoning_level: "high"
    supported_reasoning_levels:
      - effort: "high"
        description: "High reasoning effort"
      - effort: "xhigh"
        description: "Extra high reasoning effort"
    supports_reasoning_summaries: true
    default_reasoning_summary: "auto"
    extensions:
      deepseek_v4:
        enabled: true
providers:
  fake:
    base_url: "http://host.docker.internal:{fake_port}"
    api_key: "dummy"
    offers:
      - model: deepseek-v4-pro
      - model: deepseek-v4-flash
routes:
  moonbridge:
    model: "deepseek-v4-pro"
    provider: fake
defaults:
  model: moonbridge
  max_tokens: 65536
"""


class Moonbridge:
    def __init__(self, fake_port: int) -> None:
        self.port = _free_port()
        self.temp_dir = tempfile.TemporaryDirectory(prefix="moonbridge-count-")
        self.log_path = Path(self.temp_dir.name) / "moonbridge.log"
        self.log_file = self.log_path.open("w")
        config_path = Path(self.temp_dir.name) / "config.yml"
        config_path.write_text(_moonbridge_config(fake_port))
        self.proc = subprocess.Popen(
            [
                "docker",
                "run",
                "--rm",
                "--add-host=host.docker.internal:host-gateway",
                "-p",
                f"127.0.0.1:{self.port}:38440",
                "-v",
                f"{self.temp_dir.name}:/cfg:ro",
                "--entrypoint",
                "moonbridge",
                "agent-harness/codex:latest",
                "--config",
                "/cfg/config.yml",
            ],
            stdout=subprocess.DEVNULL,
            stderr=self.log_file,
        )
        self._wait_ready()
        CAPTURE.clear()

    def close(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)
        self.log_file.close()
        self.temp_dir.cleanup()

    def _wait_ready(self) -> None:
        url = f"http://127.0.0.1:{self.port}/v1/models"
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("Moonbridge exited before becoming ready")
            try:
                with urllib.request.urlopen(url, timeout=2):
                    return
            except Exception:
                time.sleep(0.2)
        raise TimeoutError("Moonbridge did not become ready")

    def convert(self, body: dict[str, Any]) -> dict[str, Any]:
        CAPTURE.clear()
        url = f"http://127.0.0.1:{self.port}/v1/responses"
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        request = urllib.request.Request(url, data=data, method="POST")
        request.add_header("content-type", "application/json")
        request.add_header("authorization", "Bearer dummy")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                response_body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
        try:
            captured = CAPTURE.wait_one()
        except TimeoutError as exc:
            log_tail = self.log_path.read_text(errors="replace")[-4000:]
            raise TimeoutError(
                f"{exc}; moonbridge response={response_body[:1000]!r}; log_tail={log_tail!r}"
            ) from exc
        return captured["body"]


def _existing(path: Path) -> dict[tuple[str, int], dict[str, Any]]:
    if not path.exists():
        return {}
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("exact_input_tokens"):
            out[(str(row["run_id"]), int(row["request_index"]))] = row
    return out


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for row in sorted(rows, key=lambda r: (str(r["run_id"]), int(r["request_index"]))):
            f.write(json.dumps(row, sort_keys=True) + "\n")


def backfill(
    run_specs: list[RunSpec], out_path: Path, limit: int | None = None
) -> list[dict[str, Any]]:
    rows_by_key = _existing(out_path)
    work_done = 0

    def save_progress() -> None:
        _write_rows(out_path, list(rows_by_key.values()))

    for spec in run_specs:
        records = _load_api_requests(spec.run_dir)
        if spec.agent != "Claude Code":
            continue
        stdout_usage_counts = _claude_stdout_usage_counts(spec.run_dir)
        for record in records:
            request_index = int(record["_request_index"])
            key = (spec.run_dir.name, request_index)
            if key in rows_by_key:
                continue
            if _body_capture_truncated(record) and request_index in stdout_usage_counts:
                exact = stdout_usage_counts[request_index]
                rows_by_key[key] = {
                    "agent": spec.agent,
                    "run_id": spec.run_dir.name,
                    "request_index": request_index,
                    "request_id": record.get("request_id"),
                    "path": record.get("path"),
                    "method": "anthropic_response_usage_from_stdout",
                    "source_body_sha256": (record.get("request_body_capture") or {}).get(
                        "sha256"
                    ),
                    "counted_body_sha256": "",
                    "exact_input_tokens": exact,
                }
                save_progress()
                work_done += 1
                print(
                    f"counted {spec.agent} {spec.run_dir.name} request {request_index}: "
                    f"{exact} (stdout usage)"
                )
                if limit and work_done >= limit:
                    return list(rows_by_key.values())
                continue
            body = _captured_body(record)
            exact = _count_tokens(body, record.get("headers") or {})
            rows_by_key[key] = {
                "agent": spec.agent,
                "run_id": spec.run_dir.name,
                "request_index": request_index,
                "request_id": record.get("request_id"),
                "path": record.get("path"),
                "method": "anthropic_count_tokens",
                "source_body_sha256": (record.get("request_body_capture") or {}).get("sha256"),
                "counted_body_sha256": _sha_json(body),
                "exact_input_tokens": exact,
            }
            save_progress()
            work_done += 1
            print(f"counted {spec.agent} {spec.run_dir.name} request {request_index}: {exact}")
            if limit and work_done >= limit:
                return list(rows_by_key.values())

    codex_specs = [spec for spec in run_specs if spec.agent == "Codex"]
    if codex_specs:
        fake_server, fake_port = _start_fake_upstream()
        moonbridge: Moonbridge | None = None
        try:
            moonbridge = Moonbridge(fake_port)
            for spec in codex_specs:
                for record in _load_api_requests(spec.run_dir):
                    request_index = int(record["_request_index"])
                    key = (spec.run_dir.name, request_index)
                    if key in rows_by_key:
                        continue
                    body = _captured_body(record)
                    converted = moonbridge.convert(body)
                    exact = _count_tokens(converted)
                    rows_by_key[key] = {
                        "agent": spec.agent,
                        "run_id": spec.run_dir.name,
                        "request_index": request_index,
                        "request_id": record.get("request_id"),
                        "path": record.get("path"),
                        "method": "moonbridge_transform_then_anthropic_count_tokens",
                        "source_body_sha256": (record.get("request_body_capture") or {}).get("sha256"),
                        "counted_body_sha256": _sha_json(converted),
                        "exact_input_tokens": exact,
                    }
                    save_progress()
                    work_done += 1
                    print(f"counted {spec.agent} {spec.run_dir.name} request {request_index}: {exact}")
                    if limit and work_done >= limit:
                        return list(rows_by_key.values())
        finally:
            if moonbridge is not None:
                moonbridge.close()
            fake_server.shutdown()
            fake_server.server_close()

    return list(rows_by_key.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIO_RUNS),
        default="redis",
        help="Captured run set to count.",
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    out_path = SCENARIO_OUT_DIRS[args.scenario] / "exact_context_tokens.jsonl"
    rows = backfill(SCENARIO_RUNS[args.scenario], out_path, limit=args.limit)
    _write_rows(out_path, rows)
    print(f"Wrote {len(rows)} exact token rows to {out_path}")


if __name__ == "__main__":
    main()
