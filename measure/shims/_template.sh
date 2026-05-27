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

# Find the real binary: skip the shim dir itself, take the first match in remaining PATH
_find_real() {
    local saved="$SHIM_DIR"
    # Temporarily remove shim dir from PATH to find the real binary
    PATH="${PATH//$saved:}"
    PATH="${PATH//:$saved}"
    command -v "$TOOL" 2>/dev/null || true
}

REAL="$(_find_real)"
if [ -z "$REAL" ]; then
    echo "shim: could not find real binary for $TOOL" >&2
    exit 127
fi

START=$(date +%s.%N)

# Log invocation start
if [ -n "${EXEC_SHIM_LOG:-}" ]; then
    echo "{\"tool\":\"$TOOL\",\"argv\":\"$*\",\"pid\":$$,\"start\":$START,\"source\":\"shim\"}" >> "$EXEC_SHIM_LOG"
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
    echo "{\"tool\":\"$TOOL\",\"pid\":$$,\"end\":$END,\"exit\":$CODE,\"source\":\"shim\"}" >> "$EXEC_SHIM_LOG"
fi

exit $CODE
