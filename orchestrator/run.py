"""Execute ONE isolated run end-to-end.

This is the main entry point for a single cell in the run matrix.
It:
 1. Reads the manifest
 2. Sets up the sandbox (Docker or local)
 3. Starts the measurement layer (sampler, execsnoop, shims)
 4. Invokes the agent via its adapter
 5. Tears down, collects artifacts, writes summary

Usage:
    python -m orchestrator.run <manifest.json>
    # or within Docker:
    harness run /runs/<run_id>/manifest.json
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from orchestrator.config import RunManifest


SECRET_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH")


def _load_adapter(agent_name: str):
    """Dynamically import the adapter module by agent name."""
    import importlib
    mod = importlib.import_module(f"adapters.{agent_name}")
    # Each adapter module exposes a class named <Agent>Adapter
    class_name = "".join(part.capitalize() for part in agent_name.split("_")) + "Adapter"
    return getattr(mod, class_name)()


def _setup_shims(shim_dir: Path) -> dict[str, str]:
    """Create symlinks in the shim dir for all observed tool binaries.

    Returns env vars to prepend the shim dir to PATH.
    """
    shim_dir.mkdir(parents=True, exist_ok=True)

    source_template = Path(__file__).resolve().parents[1] / "measure" / "shims" / "_template.sh"
    if not source_template.exists():
        source_template = Path("/opt/shims/_template.sh")
    if not source_template.exists():
        raise FileNotFoundError("could not locate measure/shims/_template.sh or /opt/shims/_template.sh")
    template = shim_dir / "_template.sh"
    shutil.copy2(source_template, template)
    template.chmod(0o755)

    tools = [
        "rg", "grep", "cat", "head", "tail", "find", "git",
        "make", "cmake", "cargo", "go", "rustc", "gcc", "clang",
        "pytest", "python", "python3", "node", "npm", "npx",
        "ls", "cp", "mv", "rm", "mkdir", "chmod",
        "bash", "sh", "zsh",
        "curl", "wget",
        "docker",
        "awk", "sed", "sort", "uniq", "wc",
        "jq", "yq",
        "tsc", "eslint", "prettier",
        "pip", "poetry",
        "java", "javac", "mvn", "gradle",
    ]

    for tool in tools:
        real = shutil.which(tool)
        if real and not (shim_dir / tool).exists():
            (shim_dir / tool).symlink_to(template.resolve())

    return {
        "PATH": f"{shim_dir}:{os.environ.get('PATH', '')}",
        "SHIM_DIR": str(shim_dir),
    }


def _timeout_s(manifest: RunManifest) -> int:
    timeout = manifest.task.oracle.get("timeout_s")
    if isinstance(timeout, int) and timeout > 0:
        return timeout
    return 1800


def _expand_adapter_env(adapter) -> dict[str, str]:
    expanded_env: dict[str, str] = {}
    for key, val in adapter.env().items():
        match = re.fullmatch(r"\$\{([^}]+)\}", val)
        if match and match.group(1) not in os.environ:
            continue
        expanded_env[key] = os.path.expandvars(val)
    return expanded_env


def _looks_like_full_sha(ref: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{40}", ref))


def _git_clone_command(repo_url: str, commit: str, codebase_dir: Path) -> tuple[list[str], str]:
    base = ["git", "clone", "--quiet", "--filter=blob:none"]
    if not _looks_like_full_sha(commit):
        return (
            [
                *base,
                "--depth",
                "1",
                "--branch",
                commit,
                "--single-branch",
                "--no-checkout",
                repo_url,
                str(codebase_dir),
            ],
            "partial_shallow_ref",
        )
    return ([*base, "--no-checkout", repo_url, str(codebase_dir)], "partial_blobless")


def _clone_remote_codebase(repo_url: str, commit: str, codebase_dir: Path, events_log: Path) -> None:
    cmd, strategy = _git_clone_command(repo_url, commit, codebase_dir)
    try:
        subprocess.run(cmd, check=True)
        _write_event(events_log, "codebase_clone_strategy", {"strategy": strategy})
    except subprocess.CalledProcessError:
        if codebase_dir.exists():
            shutil.rmtree(codebase_dir)
        subprocess.run(
            ["git", "clone", "--quiet", "--no-checkout", repo_url, str(codebase_dir)],
            check=True,
        )
        _write_event(
            events_log,
            "codebase_clone_strategy",
            {"strategy": "full_clone_fallback", "failed_strategy": strategy},
        )


def _wrap_with_strace(agent_cmd: list[str], run_dir: Path, events_log: Path) -> list[str]:
    """Trace child execve calls for exact argv capture when strace is available."""
    if os.environ.get("HARNESS_STRACE_EXEC", "1") == "0":
        _write_event(events_log, "strace_exec_disabled", {"reason": "HARNESS_STRACE_EXEC=0"})
        return agent_cmd

    strace = shutil.which("strace")
    if not strace:
        _write_event(events_log, "strace_exec_unavailable", {"reason": "strace_not_found"})
        return agent_cmd

    log_path = (run_dir / "strace_exec.log").resolve()
    _write_event(events_log, "strace_exec_enabled", {"path": str(log_path)})
    return [
        strace,
        "-f",
        "-qq",
        "-ttt",
        "-s",
        "4096",
        "-e",
        "trace=execve",
        "-o",
        str(log_path),
        "--",
        *agent_cmd,
    ]


def _prepare_codebase(manifest: RunManifest, run_dir: Path, events_log: Path) -> Path:
    """Create the per-run checkout used as the agent worktree."""
    codebase_dir = run_dir / "codebase"
    if codebase_dir.exists():
        _write_event(events_log, "codebase_reused", {"path": str(codebase_dir)})
        return codebase_dir

    repo_url = manifest.codebase.repo_url
    if repo_url == "builtin:empty":
        codebase_dir.mkdir(parents=True)
        (codebase_dir / "README.md").write_text(
            "# Empty Baseline Codebase\n\n"
            "This repository exists only so benchmark agents have a valid worktree.\n"
        )
        subprocess.run(["git", "-C", str(codebase_dir), "init", "--quiet"], check=True)
        subprocess.run(["git", "-C", str(codebase_dir), "add", "README.md"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(codebase_dir),
                "-c",
                "user.name=Agent Harness",
                "-c",
                "user.email=agent-harness@example.invalid",
                "commit",
                "--quiet",
                "-m",
                "Create empty baseline codebase",
            ],
            check=True,
        )
        _write_event(events_log, "codebase_builtin_created", {"kind": "empty"})
        return codebase_dir

    if repo_url == "builtin:semantic-memory-sentinel-v1":
        _create_semantic_memory_sentinel_codebase(codebase_dir)
        _write_event(events_log, "codebase_builtin_created", {"kind": "semantic_memory_sentinel_v1"})
        return codebase_dir

    if repo_url == "builtin:frontend-figma-app-v1":
        _create_frontend_figma_app_codebase(codebase_dir)
        _write_event(events_log, "codebase_builtin_created", {"kind": "frontend_figma_app_v1"})
        return codebase_dir

    _write_event(
        events_log,
        "codebase_checkout_start",
        {"repo_url": repo_url, "commit": manifest.codebase.commit},
    )

    if Path(repo_url).expanduser().exists():
        shutil.copytree(Path(repo_url).expanduser(), codebase_dir, symlinks=True)
    else:
        _clone_remote_codebase(repo_url, manifest.codebase.commit, codebase_dir, events_log)

    subprocess.run(
        [
            "git",
            "-c",
            "advice.detachedHead=false",
            "-C",
            str(codebase_dir),
            "checkout",
            "--quiet",
            manifest.codebase.commit,
        ],
        check=True,
    )
    _write_event(events_log, "codebase_checkout_end", {"path": str(codebase_dir)})
    return codebase_dir


def _create_semantic_memory_sentinel_codebase(codebase_dir: Path) -> None:
    codebase_dir.mkdir(parents=True)
    (codebase_dir / "sentinels").mkdir()
    (codebase_dir / "many_facts").mkdir()
    (codebase_dir / "distance_noise").mkdir()
    (codebase_dir / "distractors").mkdir()
    (codebase_dir / "scripts").mkdir()

    facts = {
        "alpha": "ALPHA-7F3C-ORCHID",
        "bravo": "BRAVO-18473-HARBOR",
        "charlie": "CHARLIE-/vortex/quartz",
        "delta": "DELTA-rotate_checksum_91",
        "echo": "ECHO-ultramarine-42",
    }
    fact_lines = []
    for name, value in facts.items():
        (codebase_dir / "sentinels" / f"{name}.txt").write_text(
            f"# Sentinel {name}\n\n"
            "This file contains one canonical memory-probe value.\n"
            f"SENTINEL_{name.upper()}={value}\n"
            "Do not confuse this value with decoys in distractor files.\n"
        )
        fact_lines.append(f"- `{name}` -> `{value}`")

    (codebase_dir / "README.md").write_text(
        "# Semantic Memory Sentinel Probe\n\n"
        "This tiny repository is used to study agent semantic-memory consumption.\n"
        "The `sentinels/` directory contains canonical facts. The `distractors/`\n"
        "directory and `scripts/emit_noise.py` create irrelevant context pressure.\n\n"
        "Facts:\n" + "\n".join(fact_lines) + "\n"
    )

    (codebase_dir / "MEMORY_PROBE.md").write_text(
        "# Memory Probe Instructions\n\n"
        "1. Inspect the files in `sentinels/` and identify the five canonical values.\n"
        "2. Before writing `answers.json`, run `python scripts/emit_noise.py --chunks 8`.\n"
        "3. After the noise step, fill `answers.json` from memory if possible.\n"
        "4. Run `python scripts/verify_answers.py`.\n\n"
        "The point of this repository is not difficulty; it is observability. The\n"
        "run artifacts let us compare literal visibility, re-reading, and later use.\n"
    )

    (codebase_dir / "answers.json").write_text(
        "{\n"
        "  \"alpha\": \"\",\n"
        "  \"bravo\": \"\",\n"
        "  \"charlie\": \"\",\n"
        "  \"delta\": \"\",\n"
        "  \"echo\": \"\"\n"
        "}\n"
    )
    (codebase_dir / "expected_answers.json").write_text(
        json.dumps(facts, indent=2, sort_keys=True) + "\n"
    )

    emit_noise = '''#!/usr/bin/env python3
from __future__ import annotations

import argparse
import random


DECOYS = [
    "ALPHA-0000-DECOY",
    "BRAVO-99999-DECOY",
    "CHARLIE-/wrong/path",
    "DELTA-rotate_checksum_00",
    "ECHO-monochrome-00",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks", type=int, default=8)
    parser.add_argument("--lines-per-chunk", type=int, default=80)
    args = parser.parse_args()

    random.seed(20260602)
    for chunk in range(args.chunks):
        print(f"NOISE_CHUNK_BEGIN {chunk:02d}")
        for line in range(args.lines_per_chunk):
            decoy = DECOYS[(chunk + line) % len(DECOYS)]
            salt = random.randrange(10_000_000, 99_999_999)
            print(
                f"noise chunk={chunk:02d} line={line:03d} decoy={decoy} "
                f"payload={salt:x}-{salt * 17:x}-{salt * 31:x}"
            )
        print(f"NOISE_CHUNK_END {chunk:02d}")


if __name__ == "__main__":
    main()
'''
    verify_answers = '''#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


EXPECTED = {
    "alpha": "ALPHA-7F3C-ORCHID",
    "bravo": "BRAVO-18473-HARBOR",
    "charlie": "CHARLIE-/vortex/quartz",
    "delta": "DELTA-rotate_checksum_91",
    "echo": "ECHO-ultramarine-42",
}


def main() -> int:
    path = Path("answers.json")
    if not path.exists():
        print("answers.json missing")
        return 2
    try:
        actual = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        print(f"answers.json invalid JSON: {exc}")
        return 2

    errors = []
    for key, expected in EXPECTED.items():
        if actual.get(key) != expected:
            errors.append(f"{key}: expected {expected!r}, got {actual.get(key)!r}")
    if errors:
        print("SENTINEL_VERIFY_FAIL")
        for error in errors:
            print(error)
        return 1
    print("SENTINEL_VERIFY_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''
    (codebase_dir / "scripts" / "emit_noise.py").write_text(emit_noise)
    (codebase_dir / "scripts" / "verify_answers.py").write_text(verify_answers)
    (codebase_dir / "scripts" / "emit_noise.py").chmod(0o755)
    (codebase_dir / "scripts" / "verify_answers.py").chmod(0o755)

    many_facts = {
        "fact_01": "MF01-ION-7301",
        "fact_02": "MF02-QUARTZ-9146",
        "fact_03": "MF03-VECTOR-2085",
        "fact_04": "MF04-EMBER-6519",
        "fact_05": "MF05-CIPHER-4820",
        "fact_06": "MF06-HARBOR-3394",
        "fact_07": "MF07-MATRIX-7712",
        "fact_08": "MF08-NOVA-1268",
        "fact_09": "MF09-ORBIT-5903",
        "fact_10": "MF10-PULSE-4471",
        "fact_11": "MF11-QUANTA-8826",
        "fact_12": "MF12-RIFT-3057",
        "fact_13": "MF13-SIGNAL-6744",
        "fact_14": "MF14-TENSOR-2199",
        "fact_15": "MF15-UMBRA-7630",
        "fact_16": "MF16-VELVET-4182",
        "fact_17": "MF17-WARDEN-9521",
        "fact_18": "MF18-XENON-6073",
        "fact_19": "MF19-YONDER-1840",
        "fact_20": "MF20-ZENITH-5368",
        "fact_21": "MF21-AXIOM-7254",
        "fact_22": "MF22-BEACON-3916",
        "fact_23": "MF23-CASCADE-8402",
        "fact_24": "MF24-DRIFT-2675",
    }
    positions = ("begin", "middle", "end")
    for index, (key, value) in enumerate(many_facts.items(), start=1):
        position = positions[(index - 1) % len(positions)]
        sentinel_line = {"begin": 6, "middle": 45, "end": 82}[position]
        lines = [
            f"# Many-file sentinel {key}",
            f"POSITION={position}",
            "Only the line beginning MANY_SENTINEL is canonical.",
        ]
        for line_no in range(1, 90):
            if line_no == sentinel_line:
                lines.append(f"MANY_SENTINEL {key}={value}")
            else:
                lines.append(
                    f"line={line_no:03d} decoy={key}-DECOY-{line_no:03d} "
                    f"payload={index * 1000 + line_no:06d} canonical=false"
                )
        (codebase_dir / "many_facts" / f"{key}_{position}.txt").write_text("\n".join(lines) + "\n")

    (codebase_dir / "many_answers.json").write_text(
        "{\n"
        + ",\n".join(f'  "{key}": ""' for key in many_facts)
        + "\n}\n"
    )

    many_hashes = {key: hashlib.sha256(value.encode()).hexdigest() for key, value in many_facts.items()}
    verify_many = f'''#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


EXPECTED_HASHES = {json.dumps(many_hashes, indent=4, sort_keys=True)}


def main() -> int:
    path = Path("many_answers.json")
    if not path.exists():
        print("many_answers.json missing")
        return 2
    try:
        actual = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        print(f"many_answers.json invalid JSON: {{exc}}")
        return 2

    errors = []
    for key, expected_hash in EXPECTED_HASHES.items():
        value = actual.get(key)
        if not isinstance(value, str):
            errors.append(f"{{key}}: missing or non-string")
            continue
        digest = hashlib.sha256(value.encode()).hexdigest()
        if digest != expected_hash:
            errors.append(f"{{key}}: hash mismatch for value {{value!r}}")
    extra = sorted(set(actual) - set(EXPECTED_HASHES))
    if extra:
        errors.append(f"unexpected keys: {{extra}}")
    if errors:
        print("MANY_SENTINEL_VERIFY_FAIL")
        for error in errors:
            print(error)
        return 1
    print("MANY_SENTINEL_VERIFY_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''
    emit_many_distractors = '''#!/usr/bin/env python3
from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=24)
    parser.add_argument("--lines-per-round", type=int, default=50)
    args = parser.parse_args()

    for round_index in range(args.rounds):
        print(f"MANY_DISTRACTOR_ROUND_BEGIN {round_index:02d}")
        for line in range(args.lines_per_round):
            print(
                f"distractor round={round_index:02d} line={line:03d} "
                f"decoy=MF{(line % 24) + 1:02d}-NOT-CANONICAL-{round_index:02d}-{line:03d} "
                f"payload={round_index * 100000 + line:08d}"
            )
        print(f"MANY_DISTRACTOR_ROUND_END {round_index:02d}")


if __name__ == "__main__":
    main()
'''
    (codebase_dir / "scripts" / "verify_many_answers.py").write_text(verify_many)
    (codebase_dir / "scripts" / "emit_many_distractors.py").write_text(emit_many_distractors)
    (codebase_dir / "scripts" / "verify_many_answers.py").chmod(0o755)
    (codebase_dir / "scripts" / "emit_many_distractors.py").chmod(0o755)

    for idx in range(1, 81):
        lines = [
            f"# Distance noise file {idx:02d}",
            "This file is intentionally irrelevant to the sentinel facts.",
        ]
        for line_no in range(120):
            lines.append(
                f"distance_noise={idx:02d} line={line_no:03d} "
                f"decoy=MF{((idx + line_no) % 24) + 1:02d}-DISTANCE-DECOY-{idx:02d}-{line_no:03d} "
                f"payload={idx * 100000 + line_no:08d}"
            )
        (codebase_dir / "distance_noise" / f"noise_{idx:02d}.txt").write_text("\n".join(lines) + "\n")

    for idx in range(1, 7):
        lines = [
            f"# Distractor file {idx}",
            "These lines contain decoys and repeated irrelevant text.",
        ]
        for line_no in range(120):
            lines.append(
                f"distractor={idx:02d} line={line_no:03d} "
                f"decoy=NOT_A_SENTINEL_{idx}_{line_no} "
                "text=The canonical answer is not on this line."
            )
        (codebase_dir / "distractors" / f"noise_{idx:02d}.txt").write_text("\n".join(lines) + "\n")

    subprocess.run(["git", "-C", str(codebase_dir), "init", "--quiet"], check=True)
    subprocess.run(["git", "-C", str(codebase_dir), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(codebase_dir),
            "-c",
            "user.name=Agent Harness",
            "-c",
            "user.email=agent-harness@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "Create semantic memory sentinel probe",
        ],
        check=True,
    )


def _create_frontend_figma_app_codebase(codebase_dir: Path) -> None:
    codebase_dir.mkdir(parents=True)
    (codebase_dir / "src").mkdir()
    (codebase_dir / "tests").mkdir()
    (codebase_dir / "docs").mkdir()

    (codebase_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "figma-memory-e2e-app",
                "version": "0.1.0",
                "private": True,
                "type": "module",
                "scripts": {
                    "dev": "vite --host 127.0.0.1",
                    "build": "vite build",
                    "test:e2e": "playwright test",
                    "test": "npm run build && npm run test:e2e",
                },
                "dependencies": {},
                "devDependencies": {
                    "@playwright/test": "^1.44.0",
                    "typescript": "^5.4.5",
                    "vite": "^5.2.12",
                },
            },
            indent=2,
        )
        + "\n"
    )
    (codebase_dir / "index.html").write_text(
        "\n".join(
            [
                '<!doctype html>',
                '<html lang="en">',
                "  <head>",
                '    <meta charset="UTF-8" />',
                '    <meta name="viewport" content="width=device-width, initial-scale=1.0" />',
                "    <title>Figma Memory E2E App</title>",
                "  </head>",
                "  <body>",
                '    <main id="app"></main>',
                '    <script type="module" src="/src/main.ts"></script>',
                "  </body>",
                "</html>",
            ]
        )
        + "\n"
    )
    (codebase_dir / "src" / "main.ts").write_text(
        "\n".join(
            [
                "import './styles.css';",
                "",
                "const app = document.querySelector<HTMLDivElement>('#app');",
                "",
                "if (!app) {",
                "  throw new Error('Missing #app root');",
                "}",
                "",
                "app.innerHTML = `",
                '  <section class="shell" aria-labelledby="page-title">',
                '    <p class="eyebrow">Figma MCP benchmark scaffold</p>',
                '    <h1 id="page-title">Replace this scaffold with the Figma-derived app.</h1>',
                '    <p class="summary">The benchmark task should extract design details, implement the interface, and verify it with Playwright.</p>',
                '    <button type="button">Primary action</button>',
                "  </section>",
                "`;",
                "",
            ]
        )
    )
    (codebase_dir / "src" / "styles.css").write_text(
        "\n".join(
            [
                ":root {",
                "  color: #1f2937;",
                "  background: #f8fafc;",
                "  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;",
                "}",
                "",
                "* {",
                "  box-sizing: border-box;",
                "}",
                "",
                "body {",
                "  margin: 0;",
                "}",
                "",
                ".shell {",
                "  min-height: 100vh;",
                "  display: grid;",
                "  align-content: center;",
                "  gap: 16px;",
                "  max-width: 760px;",
                "  margin: 0 auto;",
                "  padding: 48px 24px;",
                "}",
                "",
                ".eyebrow {",
                "  margin: 0;",
                "  color: #0f766e;",
                "  font-size: 0.78rem;",
                "  font-weight: 700;",
                "  text-transform: uppercase;",
                "}",
                "",
                "h1 {",
                "  margin: 0;",
                "  font-size: clamp(2rem, 6vw, 4.5rem);",
                "  line-height: 1;",
                "}",
                "",
                ".summary {",
                "  margin: 0;",
                "  max-width: 56ch;",
                "  color: #475569;",
                "  font-size: 1.05rem;",
                "  line-height: 1.6;",
                "}",
                "",
                "button {",
                "  width: fit-content;",
                "  border: 0;",
                "  border-radius: 6px;",
                "  background: #111827;",
                "  color: white;",
                "  padding: 12px 16px;",
                "  font: inherit;",
                "  font-weight: 700;",
                "}",
                "",
            ]
        )
    )
    (codebase_dir / "playwright.config.ts").write_text(
        "\n".join(
            [
                "import { defineConfig, devices } from '@playwright/test';",
                "",
                "export default defineConfig({",
                "  testDir: './tests',",
                "  timeout: 30_000,",
                "  use: {",
                "    baseURL: 'http://127.0.0.1:4173',",
                "    trace: 'retain-on-failure',",
                "  },",
                "  webServer: {",
                "    command: 'npm run build && npx vite preview --host 127.0.0.1 --port 4173',",
                "    url: 'http://127.0.0.1:4173',",
                "    reuseExistingServer: false,",
                "    timeout: 120_000,",
                "  },",
                "  projects: [",
                "    { name: 'chromium-desktop', use: { ...devices['Desktop Chrome'] } },",
                "    { name: 'mobile-webkit-shape', use: { ...devices['iPhone 14'] } },",
                "  ],",
                "});",
                "",
            ]
        )
    )
    (codebase_dir / "tests" / "app.spec.ts").write_text(
        "\n".join(
            [
                "import { expect, test } from '@playwright/test';",
                "",
                "test('renders the implemented app shell', async ({ page }) => {",
                "  await page.goto('/');",
                "  await expect(page.locator('#app')).toBeVisible();",
                "  await expect(page.getByRole('heading')).toBeVisible();",
                "});",
                "",
            ]
        )
    )
    (codebase_dir / "docs" / "implementation-notes.md").write_text(
        "# Implementation Notes\n\n"
        "Use this file to record Figma extraction notes, implementation decisions, "
        "and Playwright verification results.\n"
    )
    (codebase_dir / "README.md").write_text(
        "# Figma Memory E2E App\n\n"
        "A small frontend scaffold for semantic-memory instrumentation. The benchmark "
        "task should replace the starter UI with a Figma-derived app and verify it "
        "with Playwright.\n"
    )

    subprocess.run(["git", "-C", str(codebase_dir), "init", "--quiet"], check=True)
    subprocess.run(["git", "-C", str(codebase_dir), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(codebase_dir),
            "-c",
            "user.name=Agent Harness",
            "-c",
            "user.email=agent-harness@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "Create frontend figma app scaffold",
        ],
        check=True,
    )


def _start_kernel_exec_logger(exec_log: Path, events_log: Path) -> subprocess.Popen | None:
    """Start bpftrace or bcc exec logging when available."""
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        _write_event(events_log, "execsnoop_unavailable", {"reason": "requires_root"})
        return None

    try:
        from measure.execsnoop_wrap import find_bpftrace, run_bpftrace_snoop

        if find_bpftrace():
            proc = run_bpftrace_snoop(exec_log)
            time.sleep(0.15)
            if proc.poll() is not None:
                _write_event(
                    events_log,
                    "execsnoop_failed",
                    {"method": "bpftrace", "returncode": proc.returncode},
                )
            else:
                _write_event(events_log, "execsnoop_started", {"method": "bpftrace"})
                return proc
    except Exception as exc:
        _write_event(events_log, "execsnoop_failed", {"method": "bpftrace", "error": str(exc)})

    try:
        from measure.execsnoop_wrap import find_execsnoop, run_execsnoop_bcc

        if find_execsnoop():
            proc = run_execsnoop_bcc(exec_log)
            time.sleep(0.15)
            if proc.poll() is not None:
                _write_event(
                    events_log,
                    "execsnoop_failed",
                    {"method": "bcc", "returncode": proc.returncode},
                )
            else:
                _write_event(events_log, "execsnoop_started", {"method": "bcc"})
                return proc
    except Exception as exc:
        _write_event(events_log, "execsnoop_failed", {"method": "bcc", "error": str(exc)})

    return None


def _start_fallback_exec_logger(
    exec_log: Path,
    events_log: Path,
    root_pid: int,
) -> subprocess.Popen | None:
    try:
        from measure.execsnoop_wrap import fallback_audit

        proc = fallback_audit(exec_log, root_pid)
        _write_event(events_log, "execsnoop_started", {"method": "fallback"})
        return proc
    except Exception as exc:
        _write_event(events_log, "execsnoop_failed", {"method": "fallback", "error": str(exc)})
        return None


def _stop_process(proc: subprocess.Popen | None, timeout: float = 5.0) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _find_free_tcp_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _wait_for_tcp(host: str, port: int, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def _api_observer_enabled() -> bool:
    return os.environ.get("HARNESS_API_OBSERVER", "1") not in {"0", "false", "False", "no"}


def _redact_url_for_log(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "<redacted>" if parts.query else "", ""))


def _api_observer_upstream(agent: str, env: dict[str, str]) -> tuple[str, str] | None:
    if agent == "claude_code":
        upstream = os.environ.get("HARNESS_API_OBSERVER_UPSTREAM") or env.get("ANTHROPIC_BASE_URL")
        if upstream:
            return "anthropic", upstream.rstrip("/")
    if agent == "codex":
        upstream = (
            os.environ.get("HARNESS_API_OBSERVER_UPSTREAM")
            or env.get("CODEX_PROVIDER_BASE_URL")
            or env.get("OPENAI_BASE_URL")
        )
        if upstream:
            return "openai", upstream.rstrip("/")
    if agent == "pi":
        upstream = (
            os.environ.get("HARNESS_API_OBSERVER_UPSTREAM")
            or env.get("PI_DEEPSEEK_BASE_URL")
            or "https://api.deepseek.com"
        )
        if upstream:
            return "openai", upstream.rstrip("/")
    return None


def _rewrite_command_arg_url(command: list[str], original: str, replacement: str) -> list[str]:
    rewritten: list[str] = []
    for arg in command:
        rewritten.append(arg.replace(original, replacement))
    return rewritten


def _configure_api_observer(
    agent: str,
    run_dir: Path,
    env: dict[str, str],
    agent_cmd: list[str],
    events_log: Path,
) -> tuple[subprocess.Popen | None, list[str]]:
    if not _api_observer_enabled():
        _write_event(events_log, "api_observer_disabled", {"reason": "HARNESS_API_OBSERVER=0"})
        return None, agent_cmd

    upstream_info = _api_observer_upstream(agent, env)
    if upstream_info is None:
        _write_event(events_log, "api_observer_unavailable", {"reason": "no_supported_upstream"})
        return None, agent_cmd

    provider, upstream = upstream_info
    host = "127.0.0.1"
    port = _find_free_tcp_port(host)
    proxy_base = f"http://{host}:{port}"
    log_path = (run_dir / "api_requests.jsonl").resolve()
    ready_path = (run_dir / "api_observer_ready.json").resolve()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "measure.api_observer_proxy",
            "--listen-host",
            host,
            "--port",
            str(port),
            "--upstream",
            upstream,
            "--provider",
            provider,
            "--log",
            str(log_path),
            "--ready-file",
            str(ready_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    if not _wait_for_tcp(host, port):
        _stop_process_group(proc, timeout=2)
        _write_event(events_log, "api_observer_failed", {"reason": "proxy_not_ready"})
        return None, agent_cmd

    if agent == "claude_code":
        env["HARNESS_API_OBSERVER_UPSTREAM"] = upstream
        env["ANTHROPIC_BASE_URL"] = proxy_base
    elif agent == "codex":
        proxy_provider_base = proxy_base
        if upstream.rstrip("/").endswith("/v1") and not proxy_provider_base.endswith("/v1"):
            proxy_provider_base = f"{proxy_provider_base}/v1"
        env["HARNESS_API_OBSERVER_UPSTREAM"] = upstream
        if env.get("CODEX_PROVIDER_BASE_URL"):
            env["CODEX_PROVIDER_BASE_URL"] = proxy_provider_base
            agent_cmd = _rewrite_command_arg_url(agent_cmd, upstream, proxy_provider_base)
        elif env.get("OPENAI_BASE_URL"):
            env["OPENAI_BASE_URL"] = proxy_provider_base
    elif agent == "pi":
        env["HARNESS_API_OBSERVER_UPSTREAM"] = upstream
        env["PI_DEEPSEEK_BASE_URL"] = proxy_base

    _write_event(
        events_log,
        "api_observer_started",
        {
            "pid": proc.pid,
            "provider": provider,
            "proxy_base": proxy_base,
            "upstream": _redact_url_for_log(upstream),
            "log": str(log_path),
        },
    )
    return proc, agent_cmd


def _write_api_usage_summary(run_dir: Path, events_log: Path) -> None:
    path = run_dir / "api_requests.jsonl"
    if not path.exists():
        return
    requests = 0
    responses = 0
    errors = 0
    request_bytes = 0
    response_bytes = 0
    duration_s = 0.0
    models: dict[str, int] = {}
    statuses: dict[str, int] = {}
    providers: dict[str, int] = {}
    tool_names: dict[str, int] = {}
    input_chars = 0
    instruction_chars = 0
    system_chars = 0
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            provider = str(record.get("provider", "unknown"))
            providers[provider] = providers.get(provider, 0) + 1
            event = record.get("event")
            if event == "api_request":
                requests += 1
                request_bytes += int(record.get("request_bytes", 0) or 0)
                payload = record.get("json") or {}
                model = payload.get("model")
                if model:
                    models[str(model)] = models.get(str(model), 0) + 1
                for key in ("input", "messages"):
                    input_summary = payload.get(key) or {}
                    if isinstance(input_summary.get("by_semantic_layer"), dict):
                        input_chars += sum(
                            int((rec or {}).get("chars", 0) or 0)
                            for rec in input_summary["by_semantic_layer"].values()
                        )
                        continue
                    for item in input_summary.get("messages", []):
                        input_chars += int((item.get("content") or {}).get("chars", 0) or 0)
                instruction_chars += int((payload.get("instructions") or {}).get("chars", 0) or 0)
                system_chars += int((payload.get("system") or {}).get("chars", 0) or 0)
                for name in (payload.get("tools") or {}).get("names", []):
                    tool_names[str(name)] = tool_names.get(str(name), 0) + 1
            elif event == "api_response":
                responses += 1
                response_bytes += int(record.get("response_bytes", 0) or 0)
                duration_s += float(record.get("duration_s", 0.0) or 0.0)
                status = str(record.get("status", "unknown"))
                statuses[status] = statuses.get(status, 0) + 1
            elif event == "api_error":
                errors += 1
                duration_s += float(record.get("duration_s", 0.0) or 0.0)

    summary = {
        "observer": "api_observer_proxy",
        "request_count": requests,
        "response_count": responses,
        "error_count": errors,
        "request_bytes": request_bytes,
        "response_bytes": response_bytes,
        "network_wait_s_observed": round(duration_s, 6),
        "models": dict(sorted(models.items())),
        "statuses": dict(sorted(statuses.items())),
        "providers": dict(sorted(providers.items())),
        "tool_names": dict(sorted(tool_names.items())),
        "prompt_like_chars": {
            "instructions": instruction_chars,
            "system": system_chars,
            "input_or_messages": input_chars,
        },
        "raw_log": "api_requests.jsonl",
    }
    (run_dir / "api_usage.json").write_text(json.dumps(summary, indent=2) + "\n")
    _write_event(events_log, "api_usage_written", {"path": str(run_dir / "api_usage.json")})


def _stop_process_group(proc: subprocess.Popen | None, timeout: float = 10.0) -> None:
    if proc is None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        _stop_process(proc, timeout=timeout)
        return

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            try:
                os.killpg(proc.pid, 0)
            except ProcessLookupError:
                return
        time.sleep(0.1)

    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def _observe_stream(
    stream,
    stream_name: str,
    plain_log: Path,
    observed_log: Path,
    started_monotonic: float,
) -> None:
    line_index = 0
    with plain_log.open("w") as plain_f, observed_log.open("a") as observed_f:
        for line in stream:
            plain_f.write(line)
            plain_f.flush()

            stripped = line.strip()
            record = None
            if stripped.startswith("{"):
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    record = None
            if record is not None:
                now = datetime.now(timezone.utc)
                observed_f.write(
                    json.dumps(
                        {
                            "observer_ts": now.isoformat(),
                            "observer_epoch_s": now.timestamp(),
                            "observer_monotonic_s": time.monotonic() - started_monotonic,
                            "stream": stream_name,
                            "line_index": line_index,
                            "record": record,
                        }
                    )
                    + "\n"
                )
                observed_f.flush()
            line_index += 1
    stream.close()


def _run_docker(manifest: RunManifest, run_dir: Path, adapter) -> int:
    """Execute the agent inside a Docker container.

    Returns the agent's exit code.
    """
    agent_image = adapter.docker_image()
    run_dir.mkdir(parents=True, exist_ok=True)
    run_dir_abs = run_dir.resolve()
    agent_home = (run_dir / "agent_home").resolve()
    agent_home.mkdir(parents=True, exist_ok=True)
    _seed_agent_home(agent_home)
    inner_manifest_path = run_dir / "manifest.docker_inner.json"
    inner_manifest = copy.deepcopy(manifest)
    inner_manifest.sandbox = "local"
    inner_manifest_path.write_text(inner_manifest.model_dump_json(indent=2))

    cmd = [
        "docker", "run",
        "--rm",
        "--init",
        "--name", manifest.run_id,
        "--volume", f"{run_dir_abs}:/runs/{manifest.run_id}",
        "--volume", f"{agent_home}:/home/agent",
        "--workdir", f"/runs/{manifest.run_id}",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--env", "HOME=/home/agent",
        "--env", "CODEX_HOME=/home/agent/.codex",
    ]
    prompt_ablations_dir = (Path.cwd() / "prompt_ablations").resolve()
    if prompt_ablations_dir.exists():
        cmd.extend(["--volume", f"{prompt_ablations_dir}:/prompt_ablations:ro"])
    if manifest.caps.cpu_cores:
        cmd.extend(["--cpus", str(manifest.caps.cpu_cores)])
    if manifest.caps.memory_mb:
        cmd.extend(["--memory", f"{manifest.caps.memory_mb}m"])

    for key, val in _expand_adapter_env(adapter).items():
        cmd.extend(["--env", f"{key}={val}"])
    for key in (
        "HARNESS_STRACE_EXEC",
        "HARNESS_CAPTURE_TOOL_OUTPUT",
        "HARNESS_API_OBSERVER",
        "HARNESS_API_OBSERVER_UPSTREAM",
        "HARNESS_API_OBSERVER_CAPTURE_PROMPTS",
        "HARNESS_API_OBSERVER_CAPTURE_CHARS",
        "HARNESS_TRACE_EXPORT",
        "HARNESS_TRACE_HTML",
        "CLAUDE_TRACE",
        "CLAUDE_TRACE_LOG_NAME",
    ):
        if key in os.environ:
            cmd.extend(["--env", f"{key}={os.environ[key]}"])

    cmd.extend([agent_image, f"/runs/{manifest.run_id}/{inner_manifest_path.name}"])

    with (run_dir / "docker_run.json").open("w") as f:
        json.dump({"command": _redact_docker_command(cmd), "image": agent_image}, f, indent=2)
    _write_docker_image_metadata(agent_image, run_dir)

    result = subprocess.run(cmd, capture_output=False)
    _scrub_agent_home(agent_home)
    return result.returncode


def _is_secret_env_key(key: str) -> bool:
    upper = key.upper()
    return any(marker in upper for marker in SECRET_ENV_MARKERS)


def _redact_docker_command(cmd: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next_env = False
    for item in cmd:
        if redact_next_env:
            if "=" in item:
                key, _value = item.split("=", 1)
                redacted.append(f"{key}=<redacted>" if _is_secret_env_key(key) else item)
            else:
                redacted.append(item)
            redact_next_env = False
            continue
        redacted.append(item)
        if item == "--env":
            redact_next_env = True
    return redacted


def _scrub_agent_home(agent_home: Path) -> None:
    """Remove volatile identity/auth state from persisted per-run homes."""
    for path in (
        agent_home / ".codex" / "auth.json",
        agent_home / ".claude" / "auth.json",
    ):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    claude_json = agent_home / ".claude.json"
    if claude_json.exists():
        claude_json.write_text("{}\n")


def _copy_if_exists(src: Path, dst: Path) -> None:
    if not src.exists() or dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copytree_if_exists(src: Path, dst: Path) -> None:
    if not src.exists() or dst.exists():
        return
    shutil.copytree(src, dst, symlinks=True)


def _seed_agent_home(agent_home: Path) -> None:
    """Seed a per-run writable home with config needed by agent CLIs.

    We avoid mounting the host config directories read-only because several
    CLIs write caches/session metadata under their home dirs even in ephemeral
    mode. Copy only config/instruction/plugin-like files; auth remains env-based.
    """
    host_home = Path.home()

    host_codex = host_home / ".codex"
    dst_codex = agent_home / ".codex"
    for name in ("config.toml", "models_catalog.json"):
        _copy_if_exists(host_codex / name, dst_codex / name)
    for name in ("plugins", "skills"):
        _copytree_if_exists(host_codex / name, dst_codex / name)

    host_claude = host_home / ".claude"
    dst_claude = agent_home / ".claude"
    for name in ("settings.json", "settings.local.json", "CLAUDE.md"):
        _copy_if_exists(host_claude / name, dst_claude / name)
    for name in ("skills", "agents", "commands", "plugins"):
        _copytree_if_exists(host_claude / name, dst_claude / name)
    claude_json = agent_home / ".claude.json"
    if not claude_json.exists():
        claude_json.write_text("{}\n")


def _write_docker_image_metadata(agent_image: str, run_dir: Path) -> None:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", agent_image],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        (run_dir / "docker_image.json").write_text(json.dumps({"error": str(exc)}, indent=2))
        return
    if result.returncode == 0:
        (run_dir / "docker_image.json").write_text(result.stdout)
    else:
        (run_dir / "docker_image.json").write_text(
            json.dumps({"returncode": result.returncode, "stderr": result.stderr}, indent=2)
        )


def _run_local(manifest: RunManifest, run_dir: Path, adapter) -> int:
    """Execute the agent locally on the host machine.

    Starts the measurement layer, runs the agent, collects results.
    This gives more fine-grained control over what's being measured.
    """
    run_dir.mkdir(parents=True, exist_ok=True)

    exec_log = (run_dir / "exec_log.jsonl").resolve()
    proc_csv = (run_dir / "proc_timeseries.csv").resolve()
    events_log = run_dir / "events.jsonl"
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    structured_observed_path = run_dir / "structured_events_observed.jsonl"

    # Record start event
    _write_event(events_log, "run_start", {"run_id": manifest.run_id})
    codebase_dir = _prepare_codebase(manifest, run_dir, events_log)

    # Set up PATH shims
    shim_dir = (run_dir / "shims").resolve()
    shim_env = _setup_shims(shim_dir)

    updated_env = os.environ.copy()
    updated_env.update(shim_env)
    updated_env.update(_expand_adapter_env(adapter))
    updated_env["EXEC_SHIM_LOG"] = str(exec_log)
    updated_env["CGROUP_BASE"] = str((run_dir / "cgroups").resolve())
    updated_env["HARNESS_CAPTURE_TOOL_OUTPUT"] = os.environ.get("HARNESS_CAPTURE_TOOL_OUTPUT", "1")
    updated_env["NO_COLOR"] = "1"

    # Apply memory cap if configured
    if manifest.caps.memory_mb:
        # Use cgroup v2 to cap memory for this run
        cg_base = f"/sys/fs/cgroup/bench-{manifest.run_id}"
        try:
            os.makedirs(cg_base, exist_ok=True)
            max_bytes = manifest.caps.memory_mb * 1024 * 1024
            (Path(cg_base) / "memory.max").write_text(str(max_bytes))
            # Move our PID into the cgroup
            (Path(cg_base) / "cgroup.procs").write_text(str(os.getpid()))
        except (PermissionError, OSError):
            print("WARNING: could not set memory cgroup cap", file=sys.stderr)

    # Build agent command
    task_spec = type("TaskSpec", (), {
        "kind": manifest.task.kind.value,
        "prompt": manifest.task.prompt,
        "repo_path": str(codebase_dir),
        "workdir": str(codebase_dir),
    })()

    agent_cmd = adapter.local_command(task_spec)
    api_observer_proc, agent_cmd = _configure_api_observer(
        manifest.agent,
        run_dir,
        updated_env,
        agent_cmd,
        events_log,
    )
    try:
        from measure.agent_context import write_agent_context

        context = write_agent_context(
            run_dir / "agent_context.json",
            manifest.agent,
            agent_cmd,
            codebase_dir,
            updated_env,
        )
        _write_event(
            events_log,
            "agent_context_written",
            {
                "path": str(run_dir / "agent_context.json"),
                "available_counts": context.get("available_counts", {}),
            },
        )
    except Exception as exc:
        _write_event(events_log, "agent_context_failed", {"error": str(exc)})

    launch_cmd = _wrap_with_strace(agent_cmd, run_dir, events_log)
    timeout_s = _timeout_s(manifest)

    execsnoop_proc = _start_kernel_exec_logger(exec_log, events_log)
    sampler_proc = None

    sample_start = time.time()
    timed_out = False
    exit_code = 127

    stream_started = time.monotonic()
    try:
        agent_proc = subprocess.Popen(
            launch_cmd,
            env=updated_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(codebase_dir),
            start_new_session=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except FileNotFoundError as exc:
        _write_event(events_log, "agent_start_failed", {"cmd": launch_cmd, "error": str(exc)})
        _stop_process(execsnoop_proc)
        _stop_process_group(api_observer_proc, timeout=2)
        _write_api_usage_summary(run_dir, events_log)
        return 127

    observer_threads = [
        threading.Thread(
            target=_observe_stream,
            args=(agent_proc.stdout, "stdout", stdout_path, structured_observed_path, stream_started),
            daemon=True,
        ),
        threading.Thread(
            target=_observe_stream,
            args=(agent_proc.stderr, "stderr", stderr_path, structured_observed_path, stream_started),
            daemon=True,
        ),
    ]
    for thread in observer_threads:
        thread.start()
    _write_event(
        events_log,
        "stream_observer_started",
        {"path": str(structured_observed_path)},
    )

    _write_event(
        events_log,
        "agent_started",
        {"pid": agent_proc.pid, "cmd": agent_cmd, "launch_cmd": launch_cmd},
    )

    if execsnoop_proc is not None and execsnoop_proc.poll() is not None:
        _write_event(
            events_log,
            "execsnoop_exited_early",
            {"returncode": execsnoop_proc.returncode},
        )
        execsnoop_proc = None

    if execsnoop_proc is None:
        execsnoop_proc = _start_fallback_exec_logger(exec_log, events_log, agent_proc.pid)

    sampler_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "measure.proc_sampler",
            str(agent_proc.pid),
            str(proc_csv),
            "--interval",
            "0.25",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _write_event(events_log, "sampler_started", {"pid": sampler_proc.pid})

    try:
        exit_code = agent_proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _stop_process_group(agent_proc)
        exit_code = agent_proc.wait()
        _write_event(events_log, "agent_timed_out", {"timeout_s": timeout_s})

    sample_end = time.time()
    _stop_process_group(agent_proc)
    for thread in observer_threads:
        thread.join(timeout=5)

    if sampler_proc is not None:
        try:
            sampler_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _stop_process(sampler_proc)

    _stop_process(execsnoop_proc)
    _stop_process_group(api_observer_proc, timeout=2)
    _write_api_usage_summary(run_dir, events_log)

    _write_event(events_log, "run_end", {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "wall_time_s": sample_end - sample_start,
    })

    # Convert CSV to parquet if we have data
    if proc_csv.exists() and proc_csv.stat().st_size > 0:
        try:
            from measure.proc_sampler import csv_to_parquet

            csv_to_parquet(proc_csv, run_dir / "proc_timeseries.parquet")
            _write_event(events_log, "parquet_written", {"path": str(run_dir / "proc_timeseries.parquet")})
        except Exception as exc:
            _write_event(events_log, "parquet_failed", {"error": str(exc)})

    return exit_code


def _write_event(events_log: Path, event_type: str, data: dict) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        **data,
    }
    with open(events_log, "a") as f:
        f.write(json.dumps(record) + "\n")


def run_one(manifest_path: Path) -> int:
    """Execute a single run from its manifest."""
    manifest = RunManifest.model_validate_json(manifest_path.read_text())
    manifest.started_at = datetime.now(timezone.utc).isoformat()

    run_dir = manifest_path.parent
    adapter = _load_adapter(manifest.agent)
    manifest.agent_version = getattr(adapter, "version", manifest.agent_version)
    manifest.agent_capabilities = vars(getattr(adapter, "capabilities", {}))
    manifest.hostname = socket.gethostname()
    try:
        from measure.host_info import collect_host_info

        manifest.hardware = collect_host_info()
    except Exception as exc:
        manifest.caveats.append(f"host_info_unavailable: {exc}")

    if manifest.sandbox == "docker":
        exit_code = _run_docker(manifest, run_dir, adapter)
    else:
        exit_code = _run_local(manifest, run_dir, adapter)

    manifest.completed_at = datetime.now(timezone.utc).isoformat()
    with open(manifest_path, "w") as f:
        f.write(manifest.model_dump_json(indent=2))

    try:
        from analysis.summarize import summarize_run

        summary = summarize_run(run_dir)
        summary["exit_code"] = exit_code
    except Exception as exc:
        summary = {
            "run_id": manifest.run_id,
            "agent": manifest.agent,
            "task": manifest.task.name,
            "codebase": manifest.codebase.repo_url,
            "exit_code": exit_code,
            "summary_error": str(exc),
            "started_at": manifest.started_at,
            "completed_at": manifest.completed_at,
        }
    with open(run_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    return exit_code


def main() -> None:
    p = argparse.ArgumentParser(description="Execute one isolated benchmark run")
    p.add_argument("manifest", type=Path, help="Path to manifest.json for this run")
    args = p.parse_args()

    exit_code = run_one(args.manifest)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
