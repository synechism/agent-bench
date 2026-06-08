"""Extract Claude Code skill lifecycle events from captured runs.

This is intentionally prompt-body aware but source-code agnostic. It answers:

- which plugins/skills were advertised at session init
- which hooks injected skill context before the first model request
- which skill headers were visible in each request
- which Skill tool calls appeared in the request transcript
- which full skill bodies had been loaded into context
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    plugins: list[str]
    init_skills: list[str]
    hook_events: list[dict[str, Any]]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip() or not line.startswith("{"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _capture_to_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    stripped = value.strip()
    if stripped.startswith("["):
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            return value
        if isinstance(decoded, list):
            return "\n".join(part for part in decoded if isinstance(part, str))
    return value


def _skill_headers(text: str) -> list[str]:
    marker = "The following skills are available for use with the Skill tool:"
    if marker not in text:
        return []
    section = text.split(marker, 1)[1]
    names = re.findall(
        r"(?m)^\s*-\s+([a-z][a-z0-9_.-]*(?::[a-z][a-z0-9_.-]*)?):\s+",
        section,
    )
    return sorted(set(names))


def _skill_invocation(capture: str) -> str:
    try:
        payload = json.loads(capture)
    except json.JSONDecodeError:
        payload = {}
    skill = ((payload.get("input") or {}).get("skill") or "").strip()
    if skill:
        return str(skill)
    match = re.search(r'"skill"\s*:\s*"([^"]+)"', capture)
    return match.group(1) if match else "Skill"


def _loaded_skill_body(capture: str) -> tuple[str, str] | None:
    match = re.search(r"Base directory for this skill:\s+(\S+/skills/([^\s/]+))", capture)
    if match:
        return match.group(2), match.group(1)
    frontmatter = re.search(r"(?m)^name:\s*([a-z][a-z0-9_.-]*)\s*$", capture)
    if frontmatter and "SKILL.md" in capture:
        return frontmatter.group(1), ""
    return None


def summarize_stdout(run_dir: Path) -> RunSummary:
    plugins: list[str] = []
    init_skills: list[str] = []
    hook_events: list[dict[str, Any]] = []
    for row in _load_jsonl(run_dir / "stdout.log"):
        if row.get("type") == "system" and row.get("subtype") == "init":
            plugins = [
                f"{plugin.get('name')}:{plugin.get('path')}"
                for plugin in row.get("plugins") or []
            ]
            init_skills = list(row.get("skills") or [])
        if row.get("type") == "system" and str(row.get("subtype") or "").startswith("hook_"):
            stdout = str(row.get("stdout") or row.get("output") or "")
            context = stdout
            try:
                hook_payload = json.loads(stdout)
            except json.JSONDecodeError:
                hook_payload = {}
            if isinstance(hook_payload, dict):
                context = str(
                    ((hook_payload.get("hookSpecificOutput") or {}).get("additionalContext"))
                    or stdout
                )
            names = sorted(
                set(re.findall(r"(?m)^name:\s*([a-z][a-z0-9_.-]*)\s*$", context))
            )
            hook_events.append(
                {
                    "subtype": row.get("subtype"),
                    "hook_name": row.get("hook_name"),
                    "hook_event": row.get("hook_event"),
                    "stdout_chars": len(stdout),
                    "additional_context_chars": len(context),
                    "skill_names_injected": names,
                }
            )
    return RunSummary(run_dir.name, plugins, init_skills, hook_events)


def request_rows(run_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in _load_jsonl(run_dir / "prompt_payloads.jsonl"):
        if "count_tokens" in str(record.get("path") or ""):
            continue
        items = ((record.get("input") or {}).get("items") or [])
        headers: set[str] = set()
        invocations: list[str] = []
        loaded: dict[str, dict[str, Any]] = {}
        developer_chars = 0
        loaded_body_chars = 0

        for item in items:
            capture = _capture_to_text(item.get("capture"))
            if not capture:
                continue
            if item.get("semantic_layer") == "developer_context":
                developer_chars += len(capture)
                headers.update(_skill_headers(capture))
            if str(item.get("name") or "").lower() == "skill":
                invocations.append(_skill_invocation(capture))
            body = _loaded_skill_body(capture)
            if body:
                name, base_dir = body
                loaded[name] = {
                    "name": name,
                    "base_dir": base_dir,
                    "chars": len(capture),
                }
                loaded_body_chars += len(capture)

        rows.append(
            {
                "run_id": run_dir.name,
                "request_index": int(record.get("request_index") or 0),
                "timestamp": record.get("ts") or "",
                "tool_count": int((record.get("tools") or {}).get("count") or 0),
                "skill_header_count": len(headers),
                "skill_headers": ";".join(sorted(headers)),
                "skill_invocation_count": len(invocations),
                "skill_invocations": ";".join(invocations),
                "loaded_skill_body_count": len(loaded),
                "loaded_skill_bodies": ";".join(sorted(loaded)),
                "developer_context_chars": developer_chars,
                "loaded_skill_body_chars": loaded_body_chars,
            }
        )
    return rows


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "run_id",
        "request_index",
        "timestamp",
        "tool_count",
        "skill_header_count",
        "skill_headers",
        "skill_invocation_count",
        "skill_invocations",
        "loaded_skill_body_count",
        "loaded_skill_bodies",
        "developer_context_chars",
        "loaded_skill_body_chars",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(summary: list[RunSummary], rows: list[dict[str, Any]], path: Path) -> None:
    payload = {
        "runs": [
            {
                "run_id": item.run_id,
                "plugins": item.plugins,
                "init_skills": item.init_skills,
                "hook_events": item.hook_events,
            }
            for item in summary
        ],
        "requests": rows,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_report(summary: list[RunSummary], rows: list[dict[str, Any]], path: Path) -> None:
    lines = [
        "# Claude Code Skill Lifecycle Probe - 2026-06-08",
        "",
        "This report compares a baseline Claude Code brainstorm prompt with the same prompt run after exposing the Superpowers plugin.",
        "",
        "## Runs",
        "",
        "| run | plugins | init skill count | hook events | requests | skill invocations | loaded skill bodies |",
        "| --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for item in summary:
        series = [row for row in rows if row["run_id"] == item.run_id]
        invocations = sorted(
            {
                skill
                for row in series
                for skill in str(row["skill_invocations"]).split(";")
                if skill
            }
        )
        bodies = sorted(
            {
                skill
                for row in series
                for skill in str(row["loaded_skill_bodies"]).split(";")
                if skill
            }
        )
        lines.append(
            f"| `{item.run_id}` | {len(item.plugins)} | {len(item.init_skills)} | "
            f"{len(item.hook_events)} | {len(series)} | {', '.join(invocations) or '-'} | "
            f"{', '.join(bodies) or '-'} |"
        )

    lines.extend(
        [
            "",
            "## Hook Findings",
            "",
        ]
    )
    for item in summary:
        lines.append(f"### `{item.run_id}`")
        if not item.hook_events:
            lines.append("")
            lines.append("No hook events were observed before session init.")
            lines.append("")
            continue
        lines.append("")
        for hook in item.hook_events:
            lines.append(
                f"- `{hook['subtype']}` `{hook['hook_name']}` injected "
                f"{hook.get('additional_context_chars', hook['stdout_chars']):,} additional-context chars "
                f"({hook['stdout_chars']:,} raw stdout chars); skill frontmatter names seen: "
                f"{hook['skill_names_injected'] or 'none'}."
            )
        lines.append("")

    lines.extend(
        [
            "## Request Timeline",
            "",
            "| run | request | skill headers | Skill calls | loaded bodies | loaded body chars |",
            "| --- | ---: | ---: | --- | --- | ---: |",
        ]
    )
    for row in rows:
        lines.append(
            f"| `{row['run_id']}` | {row['request_index']} | {row['skill_header_count']} | "
            f"{row['skill_invocations'] or '-'} | {row['loaded_skill_bodies'] or '-'} | "
            f"{row['loaded_skill_body_chars']:,} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Without Superpowers, the prompt used the word `brainstorm`, but no `brainstorming` skill was advertised or invoked.",
            "- With Superpowers exposed, Claude Code's plugin hook injected `using-superpowers` before the first model request. That hook text tells the model to invoke relevant skills before any response.",
            "- The first Superpowers generation request already contained Superpowers skill headers, including `superpowers:brainstorming`, `superpowers:writing-plans`, and execution/review skills.",
            "- The model then invoked the `Skill` tool with `skill=superpowers:brainstorming`. The next request contained the full brainstorming skill body as a user-role tool result, and that body remained in subsequent request context.",
            "- In this one-shot prompt, `writing-plans` was advertised but not invoked because the task explicitly stopped after brainstorming and the brainstorming skill requires user approval before transitioning to planning.",
            "",
            "## Data",
            "",
            "- `skill_lifecycle_timeline.csv`",
            "- `skill_lifecycle_summary.json`",
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "docs" / "semantic_memory" / "claude_skill_lifecycle_probe_20260608",
    )
    args = parser.parse_args()

    run_dirs = [path if path.is_absolute() else ROOT / path for path in args.runs]
    summaries = [summarize_stdout(path) for path in run_dirs]
    rows = [row for path in run_dirs for row in request_rows(path)]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(rows, args.out_dir / "skill_lifecycle_timeline.csv")
    write_json(summaries, rows, args.out_dir / "skill_lifecycle_summary.json")
    write_report(summaries, rows, args.out_dir / "README.md")
    print(f"Wrote skill lifecycle report to {args.out_dir}")


if __name__ == "__main__":
    main()
