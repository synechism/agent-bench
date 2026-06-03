"""Score semantic-memory sentinel probe runs.

The sentinel probe separates four questions that are easy to blend together:

- Was a fact present in model-visible request context?
- Did it remain present at the final request?
- Did the agent re-read the source after the noise step?
- Did the final workspace artifact use the fact correctly?
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(errors="replace"))
    except json.JSONDecodeError:
        return {}


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
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _input_items(request: dict[str, Any]) -> list[dict[str, Any]]:
    input_payload = request.get("input") if isinstance(request.get("input"), dict) else {}
    items = input_payload.get("items") if isinstance(input_payload, dict) else []
    return [item for item in items if isinstance(item, dict)]


def _item_text(item: dict[str, Any]) -> str:
    capture = item.get("capture")
    return str(capture) if capture is not None else ""


def _item_chars(item: dict[str, Any]) -> int:
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    return int(meta.get("chars") or 0)


def _short(value: Any, limit: int = 180) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\r", "").replace("\n", " ")
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _event_item(event: dict[str, Any]) -> dict[str, Any]:
    record = event.get("record") if isinstance(event.get("record"), dict) else {}
    item = record.get("item") if isinstance(record.get("item"), dict) else {}
    return item


def _event_text(event: dict[str, Any]) -> str:
    item = _event_item(event)
    values = [
        item.get("command"),
        item.get("aggregated_output"),
        item.get("text"),
    ]
    return "\n".join(str(value) for value in values if value is not None)


def _command_text(event: dict[str, Any]) -> str:
    item = _event_item(event)
    return str(item.get("command") or "")


def _completed_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for event in events:
        record = event.get("record") if isinstance(event.get("record"), dict) else {}
        if record.get("type") == "item.completed":
            out.append(event)
    return out


def _fact_visibility(prompt_payloads: list[dict[str, Any]], expected: dict[str, str]) -> dict[str, Any]:
    final_request_index = int(prompt_payloads[-1].get("request_index") or len(prompt_payloads)) if prompt_payloads else 0
    visibility: dict[str, Any] = {}
    for key, value in expected.items():
        appearances: list[dict[str, Any]] = []
        for fallback_index, request in enumerate(prompt_payloads, start=1):
            request_index = int(request.get("request_index") or fallback_index)
            for item in _input_items(request):
                text = _item_text(item)
                if value not in text:
                    continue
                appearances.append(
                    {
                        "request_index": request_index,
                        "type": item.get("type"),
                        "semantic_layer": item.get("semantic_layer"),
                        "chars": _item_chars(item),
                        "call_id": item.get("call_id"),
                        "name": item.get("name"),
                    }
                )
        visibility[key] = {
            "value": value,
            "visible": bool(appearances),
            "first_visible_request": appearances[0]["request_index"] if appearances else None,
            "last_visible_request": appearances[-1]["request_index"] if appearances else None,
            "visible_in_final_request": bool(
                appearances and appearances[-1]["request_index"] == final_request_index
            ),
            "appearance_count": len(appearances),
            "appearances": appearances[:20],
        }
    return visibility


def _event_probe(
    events: list[dict[str, Any]],
    expected: dict[str, str],
    sentinel_files: list[str],
) -> dict[str, Any]:
    completed = _completed_events(events)
    first_noise_ts: datetime | None = None
    first_verify_ts: datetime | None = None
    read_events: list[dict[str, Any]] = []
    value_events: list[dict[str, Any]] = []
    verify_ok = False

    for event in completed:
        text = _event_text(event)
        cmd = _command_text(event)
        item = _event_item(event)
        item_type = str(item.get("type") or "")
        ts = _parse_ts(event.get("observer_ts"))
        if "emit_noise.py" in cmd and first_noise_ts is None:
            first_noise_ts = ts
        if "verify_answers.py" in cmd and first_verify_ts is None:
            first_verify_ts = ts
        if "SENTINEL_VERIFY_OK" in text:
            verify_ok = True
        is_command = item_type == "command_execution"
        mentions_sentinel_file = any(path in cmd for path in sentinel_files)
        if is_command and (mentions_sentinel_file or any(value in text for value in expected.values())):
            read_events.append(
                {
                    "ts": event.get("observer_ts"),
                    "command": _short(cmd),
                    "output_preview": _short(item.get("aggregated_output")),
                }
            )
        for key, value in expected.items():
            if value in text:
                value_events.append(
                    {
                        "key": key,
                        "item_type": item_type,
                        "ts": event.get("observer_ts"),
                        "command": _short(cmd),
                        "output_preview": _short(item.get("aggregated_output") or item.get("text")),
                    }
                )

    re_reads_after_noise = []
    if first_noise_ts is not None:
        for event in read_events:
            ts = _parse_ts(event.get("ts"))
            if ts is not None and ts > first_noise_ts:
                re_reads_after_noise.append(event)

    return {
        "first_noise_ts": first_noise_ts.isoformat() if first_noise_ts else None,
        "first_verify_ts": first_verify_ts.isoformat() if first_verify_ts else None,
        "verify_ok_in_events": verify_ok,
        "sentinel_read_event_count": len(read_events),
        "value_observation_event_count": len(value_events),
        "re_read_after_noise": bool(re_reads_after_noise),
        "re_read_after_noise_events": re_reads_after_noise[:12],
        "value_observation_events": value_events[:20],
    }


def score_sentinel_fidelity(run_dir: Path) -> dict[str, Any]:
    manifest = _load_json(run_dir / "manifest.json")
    oracle = ((manifest.get("task") or {}).get("oracle") or {}) if manifest else {}
    expected = oracle.get("expected") if isinstance(oracle.get("expected"), dict) else {}
    if not expected:
        raise ValueError(f"{run_dir} does not look like a sentinel probe run")

    codebase_dir = run_dir / "codebase"
    answer_path = codebase_dir / str(oracle.get("expected_answer_file") or "answers.json")
    actual = _load_json(answer_path)
    correctness = {
        key: {
            "expected": value,
            "actual": actual.get(key),
            "correct": actual.get(key) == value,
        }
        for key, value in expected.items()
    }
    prompt_payloads = _load_jsonl(run_dir / "prompt_payloads.jsonl")
    events = _load_jsonl(run_dir / "structured_events_observed.jsonl")
    visibility = _fact_visibility(prompt_payloads, expected)
    sentinel_files = [
        str(path)
        for path in oracle.get("sentinel_files", [])
        if isinstance(path, str)
    ]
    event_probe = _event_probe(events, expected, sentinel_files)

    summary = {
        "run_id": run_dir.name,
        "task": (manifest.get("task") or {}).get("name"),
        "answer_file": str(answer_path),
        "all_answers_correct": all(item["correct"] for item in correctness.values()),
        "correctness": correctness,
        "fact_visibility": visibility,
        "all_facts_visible_at_least_once": all(item["visible"] for item in visibility.values()),
        "all_facts_visible_in_final_request": all(
            item["visible_in_final_request"] for item in visibility.values()
        ),
        "event_probe": event_probe,
        "interpretation": {
            "literal_retention": (
                "A fact is literally retained when its expected value appears in prompt_payloads "
                "after first observation and especially in the final request."
            ),
            "usable_memory": (
                "A fact is usable when answers.json is correct; this may reflect retention or "
                "re-reading, so event_probe.re_read_after_noise must be considered separately."
            ),
        },
    }
    return summary


def write_sentinel_fidelity(run_dir: Path) -> dict[str, Any]:
    summary = score_sentinel_fidelity(run_dir)
    summary_path = run_dir / "sentinel_fidelity_summary.json"
    report_path = run_dir / "sentinel_fidelity_report.md"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    _write_report(report_path, summary)
    return summary


def _write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        f"# Sentinel Fidelity - {summary.get('run_id')}",
        "",
        f"- All answers correct: `{summary.get('all_answers_correct')}`",
        f"- All facts visible at least once: `{summary.get('all_facts_visible_at_least_once')}`",
        f"- All facts visible in final request: `{summary.get('all_facts_visible_in_final_request')}`",
        f"- Re-read after noise: `{(summary.get('event_probe') or {}).get('re_read_after_noise')}`",
        f"- Verify OK observed: `{(summary.get('event_probe') or {}).get('verify_ok_in_events')}`",
        "",
        "## Facts",
        "",
        "| key | correct | first visible | last visible | final visible | appearances |",
        "| --- | --- | ---: | ---: | --- | ---: |",
    ]
    correctness = summary.get("correctness") or {}
    visibility = summary.get("fact_visibility") or {}
    for key in sorted(correctness):
        corr = correctness[key]
        vis = visibility.get(key) or {}
        lines.append(
            "| "
            f"`{key}` | "
            f"`{corr.get('correct')}` | "
            f"{vis.get('first_visible_request')} | "
            f"{vis.get('last_visible_request')} | "
            f"`{vis.get('visible_in_final_request')}` | "
            f"{vis.get('appearance_count')} |"
        )

    event_probe = summary.get("event_probe") or {}
    if event_probe.get("re_read_after_noise_events"):
        lines.extend(["", "## Re-Reads After Noise", ""])
        for event in event_probe["re_read_after_noise_events"]:
            lines.append(f"- {event.get('ts')}: {event.get('command')}")

    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Score semantic-memory sentinel probe runs")
    parser.add_argument("run_dirs", nargs="+", type=Path)
    args = parser.parse_args()

    for run_dir in args.run_dirs:
        summary = write_sentinel_fidelity(run_dir)
        print(f"Wrote sentinel fidelity artifacts for {run_dir}")
        print(f"  all answers correct: {summary['all_answers_correct']}")
        print(f"  all facts visible in final request: {summary['all_facts_visible_in_final_request']}")
        print(f"  re-read after noise: {summary['event_probe']['re_read_after_noise']}")


if __name__ == "__main__":
    main()
