from __future__ import annotations

import json

from analysis.claude_trace_export import build_claude_trace_pairs, write_claude_trace_export


def test_build_claude_trace_pairs_uses_sanitized_request_capture() -> None:
    records = [
        {
            "event": "api_request",
            "request_id": "api-1",
            "ts": "2026-06-02T00:00:00+00:00",
            "method": "POST",
            "upstream_scheme": "https",
            "upstream_host": "api.example.test",
            "forward_path": "/v1/messages",
            "headers": {"authorization": "<redacted>"},
            "request_body_capture": {
                "capture": json.dumps(
                    {"model": "test", "messages": [{"role": "user", "content": "hi"}]}
                ),
                "capture_truncated": False,
            },
        },
        {
            "event": "api_response",
            "request_id": "api-1",
            "ts": "2026-06-02T00:00:01+00:00",
            "status": 200,
            "headers": {"content-type": "text/event-stream"},
            "response_bytes": 123,
        },
    ]

    pairs = build_claude_trace_pairs(records)

    assert len(pairs) == 1
    assert pairs[0]["request"]["url"] == "https://api.example.test/v1/messages"
    assert pairs[0]["request"]["body"]["messages"][0]["content"] == "hi"
    assert pairs[0]["response"]["status_code"] == 200
    assert pairs[0]["response"]["body"]["response_bytes"] == 123


def test_write_claude_trace_export_reports_count_match_shape(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    records = [
        {
            "event": "api_request",
            "request_id": "api-1",
            "ts": "2026-06-02T00:00:00+00:00",
            "method": "POST",
            "upstream_scheme": "https",
            "upstream_host": "api.example.test",
            "forward_path": "/v1/messages",
            "headers": {},
            "request_body_capture": {"capture": "{\"messages\":[]}", "capture_truncated": False},
        },
        {
            "event": "api_response",
            "request_id": "api-1",
            "ts": "2026-06-02T00:00:01+00:00",
            "status": 200,
            "headers": {},
            "response_bytes": 10,
        },
    ]
    with (run_dir / "api_requests.jsonl").open("w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")

    summary = write_claude_trace_export(run_dir)
    output = run_dir / summary["path"]

    assert summary["request_pairs"] == 1
    assert summary["response_pairs"] == 1
    assert output.exists()
    assert json.loads(output.read_text())["request"]["body"] == {"messages": []}
