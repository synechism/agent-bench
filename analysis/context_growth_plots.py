"""Plot request-level context growth for matched Codex and Claude Code runs.

The outputs are dependency-free SVGs plus a CSV. Each point is one captured API
request. Token counts come from the observer's semantic-layer token estimates,
not provider billing counters.
"""

from __future__ import annotations

import csv
import html
import json
import math
import re
import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCENARIO_OUT_DIRS = {
    "redis": ROOT / "docs" / "semantic_memory" / "context_growth_plots_20260604",
    "frontend_plugin": ROOT
    / "docs"
    / "semantic_memory"
    / "context_growth_plots_frontend_plugin_20260605",
}


@dataclass(frozen=True)
class RunSpec:
    agent: str
    task_key: str
    task_label: str
    run_dir: Path


REDIS_RUNS = [
    RunSpec(
        "Codex",
        "empty",
        "Empty baseline",
        ROOT / "runs" / "20260601T202331_codex_empty_baseline_empty_task_nocap_rep0",
    ),
    RunSpec(
        "Codex",
        "getex_event",
        "Redis GETEX QA",
        ROOT
        / "runs"
        / "20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0",
    ),
    RunSpec(
        "Codex",
        "getex_tests",
        "Redis GETEX tests",
        ROOT
        / "runs"
        / "20260601T202331_codex_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0",
    ),
    RunSpec(
        "Codex",
        "expire_options",
        "Redis EXPIRE feature",
        ROOT
        / "runs"
        / "20260601T202331_codex_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0",
    ),
    RunSpec(
        "Claude Code",
        "empty",
        "Empty baseline",
        ROOT / "runs" / "20260602T131620_claude_code_empty_baseline_empty_task_nocap_rep0",
    ),
    RunSpec(
        "Claude Code",
        "getex_event",
        "Redis GETEX QA",
        ROOT
        / "runs"
        / "20260602T131620_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_nocap_rep0",
    ),
    RunSpec(
        "Claude Code",
        "getex_tests",
        "Redis GETEX tests",
        ROOT
        / "runs"
        / "20260602T131620_claude_code_redis_getex_expire_event_base_redis_getex_expired_event_tests_nocap_rep0",
    ),
    RunSpec(
        "Claude Code",
        "expire_options",
        "Redis EXPIRE feature",
        ROOT
        / "runs"
        / "20260602T131620_claude_code_redis_expire_options_base_redis_expire_conditional_options_nocap_rep0",
    ),
]

FRONTEND_PLUGIN_RUNS = [
    RunSpec(
        "Codex",
        "frontend_plugin",
        "Frontend plugin E2E",
        ROOT
        / "runs"
        / "20260605T142450_codex_frontend_plugin_app_frontend_plugin_design_to_playwright_app_nocap_rep0",
    ),
    RunSpec(
        "Claude Code",
        "frontend_plugin",
        "Frontend plugin E2E",
        ROOT
        / "runs"
        / "20260605T143603_claude_code_frontend_plugin_app_frontend_plugin_design_to_playwright_app_nocap_rep0",
    ),
]

SCENARIO_RUNS = {
    "redis": REDIS_RUNS,
    "frontend_plugin": FRONTEND_PLUGIN_RUNS,
}

SCENARIO_TASK_ORDERS = {
    "redis": ["empty", "getex_event", "getex_tests", "expire_options"],
    "frontend_plugin": ["frontend_plugin"],
}

SCENARIO_TITLES = {
    "redis": "Codex vs. Claude Code Context Growth Plots - 2026-06-04",
    "frontend_plugin": "Frontend Plugin E2E Context Growth Plots - 2026-06-05",
}

SCENARIO_DESCRIPTIONS = {
    "redis": "matched representative task runs",
    "frontend_plugin": "matched long-horizon frontend/plugin implementation runs",
}
AGENT_COLORS = {
    "Codex": "#2563eb",
    "Claude Code": "#d97706",
}


METRICS = {
    "context_tokens": {
        "title": "Context Window Size",
        "subtitle": "exact provider input tokens",
        "y_label": "input tokens",
        "file": "context_window_tokens.svg",
    },
    "active_tools": {
        "title": "Active Tools Given To Model",
        "subtitle": "top-level tool schemas advertised",
        "y_label": "tools",
        "file": "active_tools.svg",
    },
    "skill_headers_loaded": {
        "title": "Skill Headers Loaded",
        "subtitle": "skill names visible in developer/skills inventory",
        "y_label": "skill headers",
        "file": "skill_headers_loaded.svg",
    },
    "active_skills": {
        "title": "Active Skills In Context",
        "subtitle": "visible Skill tool invocations or loaded skill bodies",
        "y_label": "active skills",
        "file": "active_skills.svg",
    },
}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        raise FileNotFoundError(path)
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def _load_exact_tokens(path: Path) -> dict[tuple[str, int], int]:
    exact: dict[tuple[str, int], int] = {}
    if not path.exists():
        return exact
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("exact_input_tokens"):
            exact[(str(row["run_id"]), int(row["request_index"]))] = int(
                row["exact_input_tokens"]
            )
    return exact


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _capture_to_text(capture: Any) -> str:
    if not isinstance(capture, str):
        return ""
    stripped = capture.strip()
    if stripped.startswith("["):
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            return capture
        if isinstance(decoded, list):
            return "\n".join(part for part in decoded if isinstance(part, str))
    return capture


def _developer_context_text(record: dict[str, Any]) -> str:
    parts: list[str] = []
    items = ((record.get("input") or {}).get("items") or [])
    for item in items:
        if item.get("semantic_layer") != "developer_context":
            continue
        text = _capture_to_text(item.get("capture"))
        if text:
            parts.append(text)
    return "\n".join(parts)


def _normalize_skill_name(name: str) -> str:
    return name.rsplit(":", 1)[-1]


def _skill_headers_loaded(record: dict[str, Any]) -> int:
    text = _developer_context_text(record)
    if not text:
        return 0

    sections: list[str] = []
    codex_marker = "### Available skills"
    if codex_marker in text:
        section = text.split(codex_marker, 1)[1]
        section = section.split("### How to use skills", 1)[0]
        sections.append(section)

    claude_marker = "The following skills are available for use with the Skill tool:"
    if claude_marker in text:
        sections.append(text.split(claude_marker, 1)[1])

    search_text = "\n".join(sections) if sections else text
    names = set(
        re.findall(
            r"(?m)^\s*-\s+([a-z][a-z0-9_.-]*(?::[a-z][a-z0-9_.-]*)?):\s+",
            search_text,
        )
    )
    return len(names)


def _active_skills(record: dict[str, Any]) -> int:
    items = ((record.get("input") or {}).get("items") or [])
    names: set[str] = set()
    invocation_count = 0
    for item in items:
        capture = _capture_to_text(item.get("capture"))
        tool_name = str(item.get("name") or "")
        if tool_name.lower() == "skill":
            invocation_count += 1
            match = re.search(r'"skill"\s*:\s*"([^"]+)"', capture)
            names.add(_normalize_skill_name(match.group(1)) if match else "Skill")

        base_dir = re.search(r"Base directory for this skill:\s+\S*/skills/([^/\s]+)", capture)
        if base_dir:
            names.add(_normalize_skill_name(base_dir.group(1)))

        frontmatter = re.search(r"(?m)^name:\s*([a-z][a-z0-9_.-]*)\s*$", capture)
        if frontmatter and ("SKILL.md" in capture or "# Frontend Design" in capture):
            names.add(_normalize_skill_name(frontmatter.group(1)))

    return len(names) if names else invocation_count


def _context_tokens(record: dict[str, Any]) -> int:
    layers = record.get("semantic_layers") or {}
    total = 0
    for layer in layers.values():
        if isinstance(layer, dict):
            total += int(layer.get("approx_tokens") or 0)
    return total


def collect_rows(run_specs: list[RunSpec], exact_token_path: Path) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    exact_tokens = _load_exact_tokens(exact_token_path)
    for spec in run_specs:
        records = _load_jsonl(spec.run_dir / "prompt_payloads.jsonl")
        if not records:
            continue
        start = _parse_ts(str(records[0]["ts"]))
        for record in records:
            if "count_tokens" in str(record.get("path") or ""):
                continue
            ts = _parse_ts(str(record["ts"]))
            layer_tokens = {
                key: int(value.get("approx_tokens") or 0)
                for key, value in (record.get("semantic_layers") or {}).items()
                if isinstance(value, dict)
            }
            semantic_approx_tokens = _context_tokens(record)
            exact_input_tokens = exact_tokens.get(
                (spec.run_dir.name, int(record.get("request_index") or 0))
            )
            output.append(
                {
                    "agent": spec.agent,
                    "task_key": spec.task_key,
                    "task_label": spec.task_label,
                    "run_id": spec.run_dir.name,
                    "request_index": int(record.get("request_index") or 0),
                    "timestamp": record.get("ts"),
                    "elapsed_seconds": (ts - start).total_seconds(),
                    "elapsed_minutes": (ts - start).total_seconds() / 60,
                    "context_tokens": exact_input_tokens
                    if exact_input_tokens is not None
                    else semantic_approx_tokens,
                    "semantic_approx_tokens": semantic_approx_tokens,
                    "exact_input_tokens": exact_input_tokens or "",
                    "context_tokens_source": "exact_provider_count"
                    if exact_input_tokens is not None
                    else "semantic_approx_chars_div_4",
                    "active_tools": int((record.get("tools") or {}).get("count") or 0),
                    "skill_headers_loaded": _skill_headers_loaded(record),
                    "active_skills": _active_skills(record),
                    "body_approx_tokens": int(((record.get("body") or {}).get("chars") or 0) / 4),
                    "system_or_base_tokens": layer_tokens.get("system_instructions", 0)
                    + layer_tokens.get("base_instructions", 0),
                    "developer_context_tokens": layer_tokens.get("developer_context", 0),
                    "tool_schema_tokens": layer_tokens.get("tool_schema", 0),
                    "user_or_task_tokens": layer_tokens.get("user_or_task", 0),
                    "assistant_memory_tokens": layer_tokens.get("assistant_memory", 0),
                    "reasoning_or_compaction_tokens": layer_tokens.get(
                        "reasoning_or_compaction_memory", 0
                    ),
                    "tool_call_memory_tokens": layer_tokens.get("tool_call_memory", 0),
                    "tool_output_memory_tokens": layer_tokens.get("tool_output_memory", 0),
                }
            )
    return output


def _nice_max(value: float) -> float:
    if value <= 0:
        return 1
    exponent = math.floor(math.log10(value))
    fraction = value / (10**exponent)
    if fraction <= 1:
        nice = 1
    elif fraction <= 2:
        nice = 2
    elif fraction <= 5:
        nice = 5
    else:
        nice = 10
    return nice * (10**exponent)


def _fmt_tick(value: float, metric: str) -> str:
    if metric == "context_tokens":
        if abs(value) >= 1000:
            return f"{value / 1000:.0f}k"
        return f"{value:.0f}"
    if value >= 10:
        return f"{value:.0f}"
    if value == int(value):
        return f"{int(value)}"
    return f"{value:.1f}"


def _path(points: list[tuple[float, float]]) -> str:
    if not points:
        return ""
    first, *rest = points
    commands = [f"M {first[0]:.2f} {first[1]:.2f}"]
    commands.extend(f"L {x:.2f} {y:.2f}" for x, y in rest)
    return " ".join(commands)


def _scale(value: float, domain_max: float, start: float, end: float, invert: bool = False) -> float:
    if domain_max <= 0:
        frac = 0
    else:
        frac = max(0.0, min(1.0, value / domain_max))
    if invert:
        return end - frac * (end - start)
    return start + frac * (end - start)


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "agent",
        "task_key",
        "task_label",
        "run_id",
        "request_index",
        "timestamp",
        "elapsed_seconds",
        "elapsed_minutes",
        "context_tokens",
        "semantic_approx_tokens",
        "exact_input_tokens",
        "context_tokens_source",
        "active_tools",
        "skill_headers_loaded",
        "active_skills",
        "body_approx_tokens",
        "system_or_base_tokens",
        "developer_context_tokens",
        "tool_schema_tokens",
        "user_or_task_tokens",
        "assistant_memory_tokens",
        "reasoning_or_compaction_tokens",
        "tool_call_memory_tokens",
        "tool_output_memory_tokens",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_metric_svg(
    rows: list[dict[str, Any]], metric: str, path: Path, task_order: list[str]
) -> None:
    cfg = METRICS[metric]
    width = 1280
    panel_cols = 1 if len(task_order) == 1 else 2
    panel_rows = max(1, math.ceil(len(task_order) / panel_cols))
    height = 640 if len(task_order) == 1 else 900
    margin = 36
    header = 92
    gap_x = 52
    gap_y = 76
    panel_w = (width - 2 * margin - gap_x * (panel_cols - 1)) / panel_cols
    panel_h = (height - header - margin - gap_y * (panel_rows - 1)) / panel_rows
    plot_left_pad = 74
    plot_bottom_pad = 46
    plot_top_pad = 42
    plot_right_pad = 20

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">'
    )
    parts.append("<style>")
    parts.append(
        "text{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"
        "'Segoe UI',sans-serif;fill:#111827} .muted{fill:#6b7280} "
        ".grid{stroke:#e5e7eb;stroke-width:1} .axis{stroke:#9ca3af;stroke-width:1.2} "
        ".line{fill:none;stroke-width:2.6;stroke-linejoin:round;stroke-linecap:round} "
        ".dot{stroke:white;stroke-width:1.2}"
    )
    parts.append("</style>")
    parts.append("<rect width='100%' height='100%' fill='#ffffff'/>")
    parts.append(
        f"<text x='{margin}' y='42' font-size='26' font-weight='700'>"
        f"{html.escape(str(cfg['title']))}</text>"
    )
    parts.append(
        f"<text x='{margin}' y='68' font-size='14' class='muted'>"
        f"Codex vs. Claude Code, request-level points over elapsed wall-clock time. "
        f"Y axis: {html.escape(str(cfg['subtitle']))}.</text>"
    )
    legend_x = width - margin - 240
    for i, (agent, color) in enumerate(AGENT_COLORS.items()):
        y = 38 + i * 26
        parts.append(f"<line x1='{legend_x}' y1='{y}' x2='{legend_x + 34}' y2='{y}' stroke='{color}' stroke-width='3'/>")
        parts.append(f"<circle cx='{legend_x + 17}' cy='{y}' r='4' fill='{color}'/>")
        parts.append(f"<text x='{legend_x + 46}' y='{y + 5}' font-size='14'>{html.escape(agent)}</text>")

    for idx, task_key in enumerate(task_order):
        col = idx % panel_cols
        row = idx // panel_cols
        panel_x = margin + col * (panel_w + gap_x)
        panel_y = header + row * (panel_h + gap_y)
        task_rows = [r for r in rows if r["task_key"] == task_key]
        task_label = task_rows[0]["task_label"] if task_rows else task_key
        x_max = max((float(r["elapsed_minutes"]) for r in task_rows), default=0)
        y_max_raw = max((float(r[metric]) for r in task_rows), default=0)
        x_max = _nice_max(max(x_max, 1.0))
        y_max = _nice_max(y_max_raw * 1.08)
        plot_x0 = panel_x + plot_left_pad
        plot_y0 = panel_y + plot_top_pad
        plot_x1 = panel_x + panel_w - plot_right_pad
        plot_y1 = panel_y + panel_h - plot_bottom_pad

        parts.append(
            f"<text x='{panel_x}' y='{panel_y + 20}' font-size='17' font-weight='700'>"
            f"{html.escape(str(task_label))}</text>"
        )
        parts.append(
            f"<text x='{panel_x}' y='{panel_y + 39}' font-size='12' class='muted'>"
            f"x: elapsed minutes from first request</text>"
        )

        for tick in [0, 0.5, 1]:
            x = plot_x0 + tick * (plot_x1 - plot_x0)
            x_value = tick * x_max
            parts.append(f"<line x1='{x:.2f}' y1='{plot_y0:.2f}' x2='{x:.2f}' y2='{plot_y1:.2f}' class='grid'/>")
            parts.append(
                f"<text x='{x:.2f}' y='{plot_y1 + 23:.2f}' font-size='11' text-anchor='middle' class='muted'>"
                f"{_fmt_tick(x_value, 'minutes')}</text>"
            )
        for tick in [0, 0.5, 1]:
            y = plot_y1 - tick * (plot_y1 - plot_y0)
            y_value = tick * y_max
            parts.append(f"<line x1='{plot_x0:.2f}' y1='{y:.2f}' x2='{plot_x1:.2f}' y2='{y:.2f}' class='grid'/>")
            parts.append(
                f"<text x='{plot_x0 - 10:.2f}' y='{y + 4:.2f}' font-size='11' text-anchor='end' class='muted'>"
                f"{_fmt_tick(y_value, metric)}</text>"
            )

        parts.append(f"<line x1='{plot_x0:.2f}' y1='{plot_y1:.2f}' x2='{plot_x1:.2f}' y2='{plot_y1:.2f}' class='axis'/>")
        parts.append(f"<line x1='{plot_x0:.2f}' y1='{plot_y0:.2f}' x2='{plot_x0:.2f}' y2='{plot_y1:.2f}' class='axis'/>")
        parts.append(
            f"<text x='{plot_x0 - 54:.2f}' y='{plot_y0 - 11:.2f}' font-size='11' class='muted'>"
            f"{html.escape(str(cfg['y_label']))}</text>"
        )

        for agent, color in AGENT_COLORS.items():
            series = sorted(
                [r for r in task_rows if r["agent"] == agent],
                key=lambda r: int(r["request_index"]),
            )
            scaled = [
                (
                    _scale(float(r["elapsed_minutes"]), x_max, plot_x0, plot_x1),
                    _scale(float(r[metric]), y_max, plot_y0, plot_y1, invert=True),
                )
                for r in series
            ]
            if scaled:
                parts.append(f"<path d='{_path(scaled)}' class='line' stroke='{color}'/>")
            dot_radius = 3.4 if len(scaled) <= 35 else 2.2
            for point, row_data in zip(scaled, series):
                x, y = point
                title = (
                    f"{agent}, request {row_data['request_index']}: "
                    f"{row_data[metric]} at {float(row_data['elapsed_minutes']):.2f} min"
                )
                parts.append(
                    f"<circle cx='{x:.2f}' cy='{y:.2f}' r='{dot_radius}' fill='{color}' "
                    f"class='dot'><title>{html.escape(title)}</title></circle>"
                )

    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n")


def _summary_table(rows: list[dict[str, Any]], task_order: list[str]) -> list[str]:
    lines = [
        "| task | agent | requests | duration min | peak context toks | tool counts | skill header counts | active skill counts |",
        "| --- | --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for task_key in task_order:
        for agent in AGENT_COLORS:
            series = [r for r in rows if r["task_key"] == task_key and r["agent"] == agent]
            if not series:
                continue
            task_label = series[0]["task_label"]
            duration = max(float(r["elapsed_minutes"]) for r in series)
            peak = max(int(r["context_tokens"]) for r in series)
            tools = sorted({int(r["active_tools"]) for r in series})
            headers = sorted({int(r["skill_headers_loaded"]) for r in series})
            active = sorted({int(r["active_skills"]) for r in series})
            lines.append(
                f"| {task_label} | {agent} | {len(series)} | {duration:.2f} | "
                f"{peak:,} | {tools} | {headers} | {active} |"
            )
    return lines


def _drop_table(rows: list[dict[str, Any]], task_order: list[str]) -> list[str]:
    lines = [
        "| task | agent | request transition | from tokens | to tokens | drop | interpretation |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for task_key in task_order:
        for agent in AGENT_COLORS:
            series = sorted(
                [r for r in rows if r["task_key"] == task_key and r["agent"] == agent],
                key=lambda r: int(r["request_index"]),
            )
            for prev, curr in zip(series, series[1:]):
                before = int(prev["context_tokens"])
                after = int(curr["context_tokens"])
                if after >= before:
                    continue
                if agent == "Claude Code" and int(curr["active_tools"]) == 17:
                    reason = "Main-agent prompt handed work to a reduced 17-tool Explore subagent."
                elif agent == "Claude Code" and int(curr["active_tools"]) == 27:
                    reason = "Explore subagent returned; parent retained the Agent result summary, not the full subagent transcript."
                else:
                    reason = "Active request context changed; inspect payload layers for details."
                lines.append(
                    f"| {curr['task_label']} | {agent} | {int(prev['request_index'])} -> {int(curr['request_index'])} | "
                    f"{before:,} | {after:,} | {before - after:,} | {reason} |"
                )
    if len(lines) == 2:
        lines.append("| none | none | - | - | - | - | No downward transitions in plotted generation requests. |")
    return lines


def write_report(
    rows: list[dict[str, Any]],
    path: Path,
    *,
    scenario: str,
    task_order: list[str],
) -> None:
    exact_rows = sum(1 for row in rows if row.get("context_tokens_source") == "exact_provider_count")
    if scenario == "redis":
        context_section_title = "Why The Context Line Drops"
        context_notes = [
            "The context window is measured per model request, not as a single global "
            "memory pool across every Claude Code worker. In these runs, the downward "
            "steps are Claude Code parent/subagent boundaries. The parent starts with "
            "the full 27-tool surface, delegates exploration to a reduced 17-tool "
            "Explore subagent whose own transcript grows, then receives a compact "
            "`Agent` tool result summary. The parent does not ingest the subagent's "
            "entire tool transcript.",
            "",
            "Mechanically, each model API call is a fresh request body. The model does "
            "not automatically keep the previous request's full prompt unless the "
            "agent sends that content again. So a subagent can spend many tokens while "
            "it is active, then the next parent request can be smaller because Claude "
            "Code resends only the parent transcript plus the subagent's summarized "
            "`Agent` result. This is a context-window drop, not a refund or erasure of "
            "tokens already spent.",
            "",
            "For billing and total work accounting, the subagent requests should still "
            "be counted. For active-context accounting, the drop is real because the "
            "parent request no longer contains the subagent's full working history. "
            "These are different measurements: active context window versus cumulative "
            "token consumption.",
            "",
            "The active-tools plot shows the same boundary. Claude Code parent requests "
            "advertise the full 27-tool surface. The Explore subagent requests advertise "
            "a reduced 17-tool surface: `Bash`, `CronCreate`, `CronDelete`, `CronList`, "
            "`EnterWorktree`, `ExitWorktree`, `Glob`, `Grep`, `Read`, `Skill`, "
            "`TaskCreate`, `TaskGet`, `TaskList`, `TaskStop`, `TaskUpdate`, `WebFetch`, "
            "and `WebSearch`. The reduced surface removes parent-level orchestration and "
            "editing tools such as `Agent`, `Edit`, `Write`, `Workflow`, plan-mode tools, "
            "notebook editing, and user-question tooling. So the tool-count dips are not "
            "random schema churn; they mark the subagent execution scope.",
        ]
        interpretation_notes = [
            "- Claude Code has an initial title/metadata-style request with no tools before the main agent request. "
            "That request is included because it is a real captured model request; the main-agent context jump appears immediately after it.",
            "- Codex advertises a stable 12-tool surface in these runs. Claude Code alternates between "
            "a 27-tool main-agent surface and a 17-tool reduced surface in the more complex runs.",
            "- Skill headers are available-context, not actual skill activation. In these matched runs, the skill inventory "
            "is loaded before the skill body is active. `active_skills` marks visible Skill-tool invocation or loaded "
            "skill-body evidence in the request context.",
        ]
    else:
        context_section_title = "Context And Skill Interpretation"
        context_notes = [
            "For this long-horizon frontend/plugin run, neither agent used Claude-style Explore subagents. "
            "The context line therefore mostly shows ordinary parent-thread growth: task prompt, static instructions, "
            "tool schemas, file reads, edits, build/test output, and the loaded frontend-design skill body.",
            "",
            "The active-tools plot is intentionally boring here: Codex advertises the same 12-tool surface on every "
            "request; Claude Code has one initial zero-tool title request and then advertises its 27-tool main-agent "
            "surface throughout. That makes this run useful as a control for skill activation without subagent tool-surface changes.",
            "",
            "The active-skills plot is the key event marker. Skill headers are visible from the start as inventory, "
            "but the skill body only becomes active after the agent explicitly opens or invokes `frontend-design`. "
            "Codex reads the `SKILL.md` body through a file/tool path; Claude Code invokes the `Skill` tool and receives "
            "a synthetic user message containing the plugin skill body.",
        ]
        interpretation_notes = [
            "- Claude Code has an initial title/metadata-style request with no tools before the main agent request. "
            "That request is included because it is a real captured model request.",
            "- Codex advertises a stable 12-tool surface in this run. Claude Code switches from the zero-tool title "
            "request to its 27-tool main-agent surface and stays there.",
            "- Skill headers are available-context, not actual skill activation. `active_skills` marks visible Skill-tool "
            "invocation or loaded skill-body evidence in the request context.",
        ]

    lines = [
        f"# {SCENARIO_TITLES[scenario]}",
        "",
        f"This report plots the {SCENARIO_DESCRIPTIONS[scenario]} at the level of model API requests. "
        "Each point is one request captured in `prompt_payloads.jsonl`; the x-axis is elapsed "
        "wall-clock time from the first captured request in that run. Provider `count_tokens` "
        "probe requests are excluded from the main plots because they are tokenizer checks, not "
        "generation/model-context turns.",
        "",
        "## Definitions",
        "",
        "- `context_tokens`: exact provider `input_tokens` from the Anthropic-compatible "
        "`count_tokens` endpoint when present. Codex requests are first replayed through Moonbridge "
        "to count the converted Anthropic/DeepSeek request. If an exact count is missing, the CSV "
        "marks the row as a semantic chars/4 fallback.",
        "- `active_tools`: count of top-level tools advertised to the model on that request.",
        "- `skill_headers_loaded`: count of skill names visible in the developer/skills inventory text.",
        "- `active_skills`: count of visible `Skill` tool invocations or loaded skill bodies in the request context.",
        f"- Exact coverage: {exact_rows}/{len(rows)} plotted generation requests have provider-counted input tokens.",
        "",
        "## Plots",
        "",
        "![Context window size](context_window_tokens.svg)",
        "",
        "![Active tools](active_tools.svg)",
        "",
        "![Skill headers loaded](skill_headers_loaded.svg)",
        "",
        "![Active skills](active_skills.svg)",
        "",
        "## Summary Table",
        "",
        *_summary_table(rows, task_order),
        "",
        f"## {context_section_title}",
        "",
        *context_notes,
        "",
        *_drop_table(rows, task_order),
        "",
        "## Interpretation Notes",
        "",
        *interpretation_notes,
        "- The CSV next to this report includes `semantic_approx_tokens`, layer-level approximate "
        "token columns, and `body_approx_tokens` so the exact total can be audited against the older "
        "semantic estimate and raw request-body size.",
        "",
        "## Data",
        "",
        "- Raw time series: `context_growth_timeseries.csv`",
        "- Exact token backfill: `exact_context_tokens.jsonl`",
    ]
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIO_RUNS),
        default="redis",
        help="Captured run set to plot.",
    )
    args = parser.parse_args()
    out_dir = SCENARIO_OUT_DIRS[args.scenario]
    exact_token_path = out_dir / "exact_context_tokens.jsonl"
    task_order = SCENARIO_TASK_ORDERS[args.scenario]

    out_dir.mkdir(parents=True, exist_ok=True)
    rows = collect_rows(SCENARIO_RUNS[args.scenario], exact_token_path)
    write_csv(rows, out_dir / "context_growth_timeseries.csv")
    for metric, cfg in METRICS.items():
        write_metric_svg(rows, metric, out_dir / str(cfg["file"]), task_order)
    write_report(
        rows,
        out_dir / "README.md",
        scenario=args.scenario,
        task_order=task_order,
    )
    print(f"Wrote {len(rows)} request rows to {out_dir}")


if __name__ == "__main__":
    main()
