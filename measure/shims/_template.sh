#!/bin/bash
# PATH-shim template: symlink as rg, grep, cat, make, pytest, cargo, node, python, ...
# Prepend the shim dir to PATH; each invocation records tool name, argv, pid, start/end ts.
#
# The shim execs the real binary and records exit code and timing.
# If per-process cgroups are enabled, it also writes $$ to the cgroup cgroup.procs
# before exec so the kernel can track memory.peak and cpu.stat.
#
# Agents that call binaries by absolute path bypass this — execsnoop is the safety net.

TOOL="$(basename "$0")"
SHIM_DIR="$(dirname "$0")"
ORIGINAL_PATH="$PATH"

# Find the real binary: skip the shim dir itself, take the first match in remaining PATH
_find_real() {
    local search_path="$ORIGINAL_PATH"
    search_path="${search_path//$SHIM_DIR:}"
    search_path="${search_path//:$SHIM_DIR}"
    PATH="$search_path" command -v "$TOOL" 2>/dev/null || true
}

_json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\r'/\\r}"
    s="${s//$'\t'/\\t}"
    printf '%s' "$s"
}

REAL="$(_find_real)"
if [ -z "$REAL" ]; then
    echo "shim: could not find real binary for $TOOL" >&2
    exit 127
fi

START=$(date +%s.%N)

# Log invocation start
if [ -n "${EXEC_SHIM_LOG:-}" ]; then
    TOOL_JSON="$(_json_escape "$TOOL")"
    ARGV_JSON="$(_json_escape "$*")"
    echo "{\"tool\":\"$TOOL_JSON\",\"argv\":\"$ARGV_JSON\",\"pid\":$$,\"start\":$START,\"source\":\"shim\"}" >> "$EXEC_SHIM_LOG"
fi

# Optional: place this process in a per-tool cgroup for kernel-accurate peak tracking
if [ -n "${CGROUP_BASE:-}" ] && [ -d "$CGROUP_BASE" ]; then
    CG="$CGROUP_BASE/bench-$TOOL-$$"
    mkdir -p "$CG" 2>/dev/null
    echo $$ > "$CG/cgroup.procs" 2>/dev/null || true
fi

# Execute the real binary
"$REAL" "$@"
CODE=$?

# Log invocation end
END=$(date +%s.%N)
if [ -n "${EXEC_SHIM_LOG:-}" ]; then
    TOOL_JSON="$(_json_escape "$TOOL")"
    echo "{\"tool\":\"$TOOL_JSON\",\"pid\":$$,\"end\":$END,\"exit\":$CODE,\"source\":\"shim\"}" >> "$EXEC_SHIM_LOG"
fi

exit $CODE
