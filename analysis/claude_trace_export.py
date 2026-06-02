"""Export observer API logs to Claude Trace-compatible JSONL.

Claude Trace's HTML generator expects one request/response pair per JSONL line.
The harness API observer records separate request and response events keyed by
`request_id`; this module pairs those events without adding any new capture
surface. Request bodies are only reconstructed when sanitized prompt capture was
already enabled for the observer run.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT = ".claude-trace/observer_api_trace.jsonl"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records


def _iso_to_epoch_seconds(value: Any) -> float:
    if not isinstance(value, str):
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _request_url(record: dict[str, Any]) -> str:
    scheme = str(record.get("upstream_scheme") or "https")
    host = str(record.get("upstream_host") or "unknown")
    path = str(record.get("forward_path") or record.get("path") or "/")
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{scheme}://{host}{path}"


def _request_body(record: dict[str, Any]) -> tuple[Any, str | None]:
    body_capture = record.get("request_body_capture")
    if isinstance(body_capture, dict) and isinstance(body_capture.get("capture"), str):
        captured = body_capture["capture"]
        try:
            return json.loads(captured), None
        except json.JSONDecodeError:
            note = "request_body_capture was not complete JSON"
            if body_capture.get("capture_truncated"):
                note = "request_body_capture was truncated"
            return captured, note

    summary = record.get("json") if isinstance(record.get("json"), dict) else None
    if summary is not None:
        return {"_harness_summary_only": True, "summary": summary}, "request body was not captured"
    return None, "request body was not captured"


def _pair_record(
    request: dict[str, Any],
    response: dict[str, Any] | None,
    error: dict[str, Any] | None,
) -> dict[str, Any]:
    body, request_note = _request_body(request)
    pair: dict[str, Any] = {
        "request": {
            "timestamp": _iso_to_epoch_seconds(request.get("ts")),
            "method": request.get("method") or "POST",
            "url": _request_url(request),
            "headers": request.get("headers") if isinstance(request.get("headers"), dict) else {},
            "body": body,
        },
        "response": None,
        "logged_at": (response or error or request).get("ts") or request.get("ts"),
    }

    notes: list[str] = []
    if request_note:
        notes.append(request_note)

    if response is not None:
        pair["response"] = {
            "timestamp": _iso_to_epoch_seconds(response.get("ts")),
            "status_code": int(response.get("status") or 0),
            "headers": response.get("headers") if isinstance(response.get("headers"), dict) else {},
            "body": {
                "_harness_summary_only": True,
                "response_bytes": int(response.get("response_bytes") or 0),
                "note": "response body was not captured by the harness API observer",
            },
        }
    elif error is not None:
        pair["response"] = {
            "timestamp": _iso_to_epoch_seconds(error.get("ts")),
            "status_code": 0,
            "headers": {},
            "body": {
                "_harness_error": True,
                "error": error.get("error"),
                "duration_s": error.get("duration_s"),
            },
        }
    else:
        notes.append("ORPHANED_REQUEST - no matching response or error event")

    if notes:
        pair["note"] = "; ".join(notes)
    return pair


def build_claude_trace_pairs(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requests: dict[str, dict[str, Any]] = {}
    responses: dict[str, dict[str, Any]] = {}
    errors: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for record in records:
        request_id = record.get("request_id")
        if not request_id:
            continue
        request_id = str(request_id)
        event = record.get("event")
        if event == "api_request":
            if request_id not in requests:
                order.append(request_id)
            requests[request_id] = record
        elif event == "api_response":
            responses[request_id] = record
        elif event == "api_error":
            errors[request_id] = record

    return [
        _pair_record(requests[request_id], responses.get(request_id), errors.get(request_id))
        for request_id in order
    ]


def generate_claude_trace_html(jsonl_path: Path, html_path: Path | None = None) -> dict[str, Any]:
    output_path = html_path or jsonl_path.with_suffix(".html")
    claude_trace = shutil.which("claude-trace")
    if not claude_trace:
        if output_path.exists():
            return {
                "path": str(output_path),
                "generated": True,
                "reused_existing": True,
                "bytes": output_path.stat().st_size,
            }
        return {
            "path": str(output_path),
            "generated": False,
            "error": "claude-trace_not_found",
        }

    result = subprocess.run(
        [
            claude_trace,
            "--generate-html",
            str(jsonl_path),
            str(output_path),
            "--no-open",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return {
        "path": str(output_path),
        "generated": result.returncode == 0 and output_path.exists(),
        "returncode": result.returncode,
        "stdout": result.stdout[-1000:],
        "stderr": result.stderr[-1000:],
        "bytes": output_path.stat().st_size if output_path.exists() else 0,
    }


def write_claude_trace_export(
    run_dir: Path,
    output: Path | None = None,
    *,
    generate_html: bool = False,
) -> dict[str, Any]:
    api_log = run_dir / "api_requests.jsonl"
    output_path = output or (run_dir / DEFAULT_OUTPUT)
    records = _load_jsonl(api_log)
    pairs = build_claude_trace_pairs(records)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        for pair in pairs:
            f.write(json.dumps(pair, sort_keys=True) + "\n")

    response_pairs = sum(1 for pair in pairs if pair.get("response") is not None)
    try:
        output_rel = str(output_path.relative_to(run_dir))
    except ValueError:
        output_rel = str(output_path)
    summary = {
        "source": "api_observer_proxy",
        "format": "claude_trace_raw_pair_jsonl",
        "path": output_rel,
        "request_pairs": len(pairs),
        "response_pairs": response_pairs,
        "orphaned_pairs": len(pairs) - response_pairs,
        "bytes": output_path.stat().st_size if output_path.exists() else 0,
    }
    if generate_html:
        html_summary = generate_claude_trace_html(output_path)
        try:
            html_summary["path"] = str(Path(html_summary["path"]).relative_to(run_dir))
        except ValueError:
            pass
        summary["html"] = html_summary
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Export api_requests.jsonl to Claude Trace JSONL")
    parser.add_argument("run_dir", type=Path, help="Path to runs/<run_id>/")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output path")
    parser.add_argument(
        "--html",
        action="store_true",
        help="Also generate a Claude Trace HTML file",
    )
    args = parser.parse_args()

    summary = write_claude_trace_export(args.run_dir, args.output, generate_html=args.html)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
