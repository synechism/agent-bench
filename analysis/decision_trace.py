"""Build a best-effort decision trace from structured agent logs and tool spans.

The goal is causal *evidence*, not causal proof: for each expensive tool span,
record the latest observable assistant/model event before it. When an agent does
not emit timestamped structured events, the output says so explicitly.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from analysis.tool_spans import load_jsonl, write_tool_spans


TEXT_KEYS = {"text", "content", "message", "delta", "summary"}
TIME_KEYS = {"ts", "timestamp", "created_at", "time"}


def _parse_time(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        # Heuristic: structured logs may report ms.
        return float(value) / 1000.0 if float(value) > 10_000_000_000 else float(value)
    if not isinstance(value, str):
        return None
    try:
        return float(value)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _first_time(record: dict[str, Any]) -> float | None:
    for key in TIME_KEYS:
        if key in record:
            parsed = _parse_time(record[key])
            if parsed is not None:
                return parsed
    return None


def _walk_strings(value: Any, parent_key: str = "") -> list[str]:
    strings: list[str] = []
    if isinstance(value, str):
        if parent_key in TEXT_KEYS or len(value.split()) >= 3:
            strings.append(value)
    elif isinstance(value, dict):
        for key, child in value.items():
            strings.extend(_walk_strings(child, key))
    elif isinstance(value, list):
        for child in value:
            strings.extend(_walk_strings(child, parent_key))
    return strings


def _event_kind(record: dict[str, Any]) -> str:
    message = record.get("message")
    if isinstance(message, dict):
        for content in message.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "tool_use":
                return "tool"

    label = " ".join(
        str(record.get(key, ""))
        for key in ("type", "event", "name", "role", "kind")
        if record.get(key)
    ).lower()
    item = record.get("item")
    if isinstance(item, dict):
        item_type = str(item.get("type", "")).lower()
        role = str(item.get("role", "")).lower()
        if item_type in {"agent_message", "assistant_message"} or role == "assistant":
            return "assistant"
        if "tool" in item_type or "command" in item_type:
            return "tool"
    if "assistant" in label or record.get("role") == "assistant":
        return "assistant"
    if "tool" in label or "exec" in label or "command" in label:
        return "tool"
    if "system" in label:
        return "system"
    if "user" in label:
        return "user"
    return "other"


def _event_from_record(
    record: dict[str, Any],
    stream_name: str,
    line_index: int,
    ts: float | None = None,
    observer_monotonic_s: float | None = None,
) -> dict[str, Any]:
    strings = _walk_strings(record)
    return {
        "stream": stream_name,
        "line_index": line_index,
        "ts": ts if ts is not None else _first_time(record),
        "observer_monotonic_s": observer_monotonic_s,
        "kind": _event_kind(record),
        "event_type": record.get("type") or record.get("event") or record.get("name"),
        "text": "\n".join(strings)[:4000],
        "raw_keys": sorted(record.keys()),
    }


def _load_observed_structured_events(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "structured_events_observed.jsonl"
    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    for idx, line in enumerate(path.read_text(errors="replace").splitlines()):
        if not line.strip():
            continue
        try:
            observed = json.loads(line)
        except json.JSONDecodeError:
            continue
        record = observed.get("record")
        if not isinstance(record, dict):
            continue
        events.append(
            _event_from_record(
                record,
                str(observed.get("stream", "observed")),
                int(observed.get("line_index", idx)),
                _parse_time(observed.get("observer_epoch_s") or observed.get("observer_ts")),
                (
                    float(observed["observer_monotonic_s"])
                    if observed.get("observer_monotonic_s") is not None
                    else None
                ),
            )
        )
    return events


def _load_structured_events(run_dir: Path) -> list[dict[str, Any]]:
    observed_events = _load_observed_structured_events(run_dir)
    if observed_events:
        return observed_events

    events: list[dict[str, Any]] = []
    for stream_name in ("stdout.log", "stderr.log"):
        path = run_dir / stream_name
        if not path.exists():
            continue
        for idx, line in enumerate(path.read_text(errors="replace").splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append(_event_from_record(record, stream_name, idx))
    return events


def _previous_event(
    events: list[dict[str, Any]],
    span: dict[str, Any],
    kind: str | None = None,
) -> dict[str, Any] | None:
    span_ts = span.get("start_ts")
    if span_ts is None:
        return None
    candidates = [
        event for event in events
        if event.get("ts") is not None
        and float(event["ts"]) <= float(span_ts)
        and (kind is None or event.get("kind") == kind)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda event: float(event["ts"]))


def build_decision_trace(run_dir: Path, spans: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if spans is None:
        span_path = run_dir / "tool_spans.jsonl"
        spans = load_jsonl(span_path) if span_path.exists() else write_tool_spans(run_dir)

    structured_events = _load_structured_events(run_dir)
    timestamped = [event for event in structured_events if event.get("ts") is not None]
    records: list[dict[str, Any]] = []
    for span in sorted(spans, key=lambda item: float(item.get("start_s") or 1e18)):
        if span.get("category") in {"agent_runtime", "bootstrap"}:
            continue
        previous_assistant = _previous_event(timestamped, span, "assistant")
        previous_tool_event = _previous_event(timestamped, span, "tool")
        previous_event = previous_tool_event or previous_assistant
        records.append(
            {
                "span_id": span.get("span_id"),
                "tool": span.get("tool"),
                "category": span.get("category"),
                "command": span.get("command"),
                "start_s": span.get("start_s"),
                "duration_s": span.get("duration_s"),
                "peak_pss": span.get("peak_pss"),
                "previous_assistant_event": previous_assistant,
                "previous_structured_tool_event": previous_tool_event,
                "trigger_observed": previous_event is not None,
                "trigger_confidence": (
                    "timestamped_structured_tool_event"
                    if previous_tool_event
                    else "timestamped_structured_assistant_event"
                    if previous_assistant
                    else "unobserved"
                ),
            }
        )

    summary = {
        "structured_event_count": len(structured_events),
        "timestamped_structured_event_count": len(timestamped),
        "assistant_event_count": sum(1 for event in structured_events if event.get("kind") == "assistant"),
        "tool_event_count": sum(1 for event in structured_events if event.get("kind") == "tool"),
        "tool_span_count": len(spans),
        "decision_records": len(records),
        "trigger_observed_count": sum(1 for rec in records if rec["trigger_observed"]),
        "coverage_note": (
            "Timestamped structured agent events are used to join model-visible "
            "decisions to subprocess spans. New runs include observer timestamps "
            "from structured_events_observed.jsonl; older runs remain coverage-only."
        ),
    }
    return records, summary


def write_decision_trace(run_dir: Path, spans: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    records, summary = build_decision_trace(run_dir, spans)
    with (run_dir / "decision_trace.jsonl").open("w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    with (run_dir / "decision_trace_summary.json").open("w") as f:
        json.dump(summary, f, indent=2)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build model-decision-to-tool trace")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    summary = write_decision_trace(args.run_dir)
    print(f"Wrote {summary['decision_records']} records to {args.run_dir / 'decision_trace.jsonl'}")
    print(f"Observed triggers: {summary['trigger_observed_count']}")


if __name__ == "__main__":
    main()
