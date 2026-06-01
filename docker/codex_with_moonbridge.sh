#!/usr/bin/env bash
set -euo pipefail

if [[ "${CODEX_DEEPSEEK_MOONBRIDGE:-0}" != "1" && "${CODEX_DEEPSEEK_MOONBRIDGE:-}" != "true" ]]; then
  exec codex "$@"
fi

CODEX_HOME_DIR="${CODEX_HOME:-${HOME}/.codex}"
mkdir -p "$CODEX_HOME_DIR"

DEEPSEEK_TOKEN="${DEEPSEEK_API_KEY:-${ANTHROPIC_AUTH_TOKEN:-}}"
if [[ -z "$DEEPSEEK_TOKEN" ]]; then
  echo "codex-with-moonbridge: DEEPSEEK_API_KEY or ANTHROPIC_AUTH_TOKEN is required" >&2
  exit 2
fi

MOONBRIDGE_BIN="${MOONBRIDGE_BIN:-/usr/local/bin/moonbridge}"
MOONBRIDGE_MODEL="${MOONBRIDGE_DEEPSEEK_MODEL:-deepseek-v4-pro}"
MOONBRIDGE_ADDR="${CODEX_MOONBRIDGE_ADDR:-127.0.0.1:38440}"
CODEX_BASE_URL="${CODEX_PROVIDER_BASE_URL:-http://${MOONBRIDGE_ADDR}/v1}"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/codex-moonbridge.XXXXXX")"
CONFIG_FILE="${WORK_DIR}/config.yml"
MOONBRIDGE_LOG="${WORK_DIR}/moonbridge.log"

cleanup() {
  local status=$?
  if [[ -n "${MOONBRIDGE_PID:-}" ]] && kill -0 "$MOONBRIDGE_PID" >/dev/null 2>&1; then
    kill "$MOONBRIDGE_PID" >/dev/null 2>&1 || true
    wait "$MOONBRIDGE_PID" >/dev/null 2>&1 || true
  fi
  rm -rf "$WORK_DIR"
  exit "$status"
}
trap cleanup EXIT INT TERM

cat > "$CONFIG_FILE" <<EOF_CONFIG
mode: "Transform"

log:
  level: "info"
  format: "text"

server:
  addr: "${MOONBRIDGE_ADDR}"

models:
  deepseek-v4-pro:
    context_window: 1000000
    max_output_tokens: 384000
    default_reasoning_level: "high"
    supported_reasoning_levels:
      - effort: "high"
        description: "High reasoning effort"
      - effort: "xhigh"
        description: "Extra high reasoning effort"
    supports_reasoning_summaries: true
    default_reasoning_summary: "auto"
    extensions:
      deepseek_v4:
        enabled: true
  deepseek-v4-flash:
    context_window: 1000000
    max_output_tokens: 384000
    default_reasoning_level: "high"
    supported_reasoning_levels:
      - effort: "high"
        description: "High reasoning effort"
      - effort: "xhigh"
        description: "Extra high reasoning effort"
    supports_reasoning_summaries: true
    default_reasoning_summary: "auto"
    extensions:
      deepseek_v4:
        enabled: true

providers:
  deepseek:
    base_url: "https://api.deepseek.com/anthropic"
    api_key: "${DEEPSEEK_TOKEN}"
    offers:
      - model: deepseek-v4-pro
      - model: deepseek-v4-flash

routes:
  moonbridge:
    model: "${MOONBRIDGE_MODEL}"
    provider: deepseek

defaults:
  model: moonbridge
  max_tokens: 65536
EOF_CONFIG

MODEL_ALIAS="$("$MOONBRIDGE_BIN" --config "$CONFIG_FILE" --print-codex-model)"
"$MOONBRIDGE_BIN" \
  --config "$CONFIG_FILE" \
  --print-codex-config "$MODEL_ALIAS" \
  --codex-base-url "$CODEX_BASE_URL" \
  --codex-home "$CODEX_HOME_DIR" \
  > "${CODEX_HOME_DIR}/config.toml"

"$MOONBRIDGE_BIN" --config "$CONFIG_FILE" >"$MOONBRIDGE_LOG" 2>&1 &
MOONBRIDGE_PID=$!

for _ in $(seq 1 200); do
  if curl -fsS "http://${MOONBRIDGE_ADDR}/v1/models" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$MOONBRIDGE_PID" >/dev/null 2>&1; then
    echo "codex-with-moonbridge: Moon Bridge exited before becoming ready" >&2
    sed -n '1,160p' "$MOONBRIDGE_LOG" >&2 || true
    exit 3
  fi
  sleep 0.1
done

if ! curl -fsS "http://${MOONBRIDGE_ADDR}/v1/models" >/dev/null 2>&1; then
  echo "codex-with-moonbridge: Moon Bridge did not become ready at ${MOONBRIDGE_ADDR}" >&2
  sed -n '1,160p' "$MOONBRIDGE_LOG" >&2 || true
  exit 3
fi

codex "$@"
