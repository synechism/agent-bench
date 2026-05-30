"""Capture agent prompt/config/skill context for causal analysis.

This is intentionally best-effort and conservative: it records inventories,
hashes, counts, and small non-secret metadata so we can correlate tool behavior
with the surrounding agent context without copying API keys or large private
files into run artifacts.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH")


def _sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _file_summary(path: Path, root: Path | None = None) -> dict[str, Any]:
    rel = str(path)
    if root is not None:
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = str(path)
    try:
        stat = path.stat()
    except OSError:
        return {"path": rel, "error": "stat_failed"}
    return {
        "path": rel,
        "bytes": stat.st_size,
        "sha256": _sha256(path),
    }


def _safe_env(env: dict[str, str]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, value in sorted(env.items()):
        if any(marker in key.upper() for marker in SECRET_MARKERS):
            safe[key] = "<redacted>"
        elif key in {
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_MODEL",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
            "CLAUDE_CODE_SUBAGENT_MODEL",
            "CLAUDE_CODE_EFFORT_LEVEL",
            "OPENAI_BASE_URL",
            "CODEX_HOME",
            "HOME",
            "NO_COLOR",
        }:
            safe[key] = value
    return safe


def _run_version(binary: str, args: list[str] | None = None) -> dict[str, Any]:
    exe = shutil.which(binary)
    if not exe:
        return {"binary": binary, "available": False}
    cmd = [exe, *(args or ["--version"])]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"binary": binary, "available": True, "error": str(exc)}
    return {
        "binary": binary,
        "path": exe,
        "returncode": result.returncode,
        "stdout": result.stdout.strip()[:1000],
        "stderr": result.stderr.strip()[:1000],
    }


def _inventory_dir(path: Path, root: Path | None = None, limit: int = 200) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "files": []}
    files = []
    all_files = sorted(p for p in path.rglob("*") if p.is_file())
    for child in all_files[:limit]:
        files.append(_file_summary(child, root or path))
    return {
        "path": str(path),
        "exists": True,
        "file_count": len(all_files),
        "files": files,
        "truncated": len(files) >= limit,
    }


def _component_inventory(path: Path, root: Path | None = None, kind: str = "component") -> dict[str, Any]:
    """Summarize prompt/skill/plugin components without copying their content.

    Directory-shaped systems usually use one directory per skill/plugin. Some
    systems use one markdown/json file per command/agent. We record both shapes
    so later analysis can distinguish "46 files under skills/" from "8 skills".
    """
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "kind": kind,
            "component_count": 0,
            "components": [],
        }

    components: list[dict[str, Any]] = []
    for child in sorted(path.iterdir()):
        if child.name.startswith("."):
            continue
        if child.is_dir():
            skill_file = child / "SKILL.md"
            components.append(
                {
                    "name": child.name,
                    "type": "directory",
                    "file_count": sum(1 for p in child.rglob("*") if p.is_file()),
                    "has_skill_md": skill_file.exists(),
                    "skill_md": _file_summary(skill_file, root or path) if skill_file.exists() else None,
                }
            )
        elif child.is_file():
            components.append(
                {
                    "name": child.name,
                    "type": "file",
                    "file": _file_summary(child, root or path),
                }
            )

    return {
        "path": str(path),
        "exists": True,
        "kind": kind,
        "component_count": len(components),
        "skill_md_count": sum(1 for item in components if item.get("has_skill_md")),
        "components": components[:200],
        "truncated": len(components) > 200,
    }


def _project_instruction_files(workdir: Path) -> list[dict[str, Any]]:
    names = [
        "CLAUDE.md",
        "AGENTS.md",
        ".cursorrules",
        ".windsurfrules",
        ".github/copilot-instructions.md",
    ]
    return [_file_summary(workdir / name, workdir) for name in names if (workdir / name).exists()]


def _claude_context(home: Path, workdir: Path) -> dict[str, Any]:
    claude_home = home / ".claude"
    project_claude = workdir / ".claude"
    inventories = {
        "home_settings": [
            _file_summary(path, claude_home)
            for path in [
                home / ".claude.json",
                claude_home / "settings.json",
                claude_home / "settings.local.json",
                claude_home / "CLAUDE.md",
            ]
            if path.exists()
        ],
        "project_settings": [
            _file_summary(path, workdir)
            for path in [
                workdir / ".claude" / "settings.json",
                workdir / ".claude" / "settings.local.json",
            ]
            if path.exists()
        ],
        "home_skills": _component_inventory(claude_home / "skills", claude_home, "skills"),
        "home_agents": _component_inventory(claude_home / "agents", claude_home, "agents"),
        "home_commands": _component_inventory(claude_home / "commands", claude_home, "commands"),
        "project_skills": _component_inventory(project_claude / "skills", workdir, "skills"),
        "project_agents": _component_inventory(project_claude / "agents", workdir, "agents"),
        "project_commands": _component_inventory(project_claude / "commands", workdir, "commands"),
    }
    counts = _loaded_counts(inventories)
    return {
        "versions": [_run_version("claude")],
        "load_observability": {
            "available_context_recorded": True,
            "actual_model_context_observed": False,
            "note": (
                "This records installed/available prompt, skill, agent, and command context. "
                "Structured agent logs or a prompt observer are required to prove which items "
                "were actually loaded into the model context for a specific turn."
            ),
        },
        "prompt_reference": {
            "kind": "external_inventory",
            "repository": "Piebald-AI/claude-code-system-prompts",
            "note": (
                "Use this version-indexed prompt inventory to map the installed Claude "
                "Code version to known system prompt/tool/subagent prompt fragments."
            ),
        },
        "inventories": inventories,
        "available_counts": counts,
        "loaded_counts": counts,
    }


def _codex_context(home: Path, workdir: Path, env: dict[str, str]) -> dict[str, Any]:
    codex_home = Path(env.get("CODEX_HOME", str(home / ".codex"))).expanduser()
    inventories = {
        "config_files": [
            _file_summary(path, codex_home)
            for path in [
                codex_home / "config.toml",
                codex_home / "models_catalog.json",
                codex_home / "auth.json",
            ]
            if path.exists()
        ],
        "plugins": _component_inventory(codex_home / "plugins", codex_home, "plugins"),
        "skills": _component_inventory(codex_home / "skills", codex_home, "skills"),
        "project_codex": _inventory_dir(workdir / ".codex", workdir),
    }
    counts = _loaded_counts(inventories)
    return {
        "versions": [_run_version("codex")],
        "load_observability": {
            "available_context_recorded": True,
            "actual_model_context_observed": False,
            "note": (
                "This records installed/available Codex config, plugins, and skills. "
                "Structured JSONL event logs are needed to determine which entries were "
                "actually used during a specific run."
            ),
        },
        "inventories": inventories,
        "available_counts": counts,
        "loaded_counts": counts,
    }


def _generic_context(agent: str, home: Path, workdir: Path) -> dict[str, Any]:
    dot_home = home / f".{agent}"
    dot_project = workdir / f".{agent}"
    inventories = {
        "home_agent_dir": _inventory_dir(dot_home, home),
        "project_agent_dir": _inventory_dir(dot_project, workdir),
    }
    counts = _loaded_counts(inventories)
    return {
        "versions": [_run_version(agent)],
        "load_observability": {
            "available_context_recorded": True,
            "actual_model_context_observed": False,
        },
        "inventories": inventories,
        "available_counts": counts,
        "loaded_counts": counts,
    }


def _loaded_counts(inventories: dict[str, Any]) -> dict[str, int]:
    counts = {}
    for name, inventory in inventories.items():
        if isinstance(inventory, list):
            counts[name] = len(inventory)
        elif isinstance(inventory, dict):
            if "component_count" in inventory:
                counts[name] = int(inventory.get("component_count", 0))
            else:
                counts[name] = int(inventory.get("file_count", len(inventory.get("files", []))))
    return counts


def collect_agent_context(
    agent: str,
    command: list[str],
    workdir: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    home = Path(env.get("HOME", os.environ.get("HOME", "~"))).expanduser()
    context: dict[str, Any] = {
        "agent": agent,
        "command": command,
        "env": _safe_env(env),
        "project_instruction_files": _project_instruction_files(workdir),
        "causal_questions": [
            "Which system/developer/project prompts were in scope?",
            "Which skill/plugin/subagent inventories were available?",
            "Which model/backend configuration was active?",
            "Which observer logs can explain why a tool was called?",
        ],
    }

    if agent == "claude_code":
        context.update(_claude_context(home, workdir))
    elif agent == "codex":
        context.update(_codex_context(home, workdir, env))
    else:
        context.update(_generic_context(agent, home, workdir))

    return context


def write_agent_context(
    out_path: Path,
    agent: str,
    command: list[str],
    workdir: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    context = collect_agent_context(agent, command, workdir, env)
    with out_path.open("w") as f:
        json.dump(context, f, indent=2)
    return context
