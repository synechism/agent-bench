#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${PI_CODING_AGENT_DIR:-${HOME:-/home/agent}/.pi/agent}"
BASE_URL="${PI_DEEPSEEK_BASE_URL:-https://api.deepseek.com}"
MODEL_ID="${PI_DEEPSEEK_MODEL:-deepseek-v4-pro}"

mkdir -p "$CONFIG_DIR"
cat >"$CONFIG_DIR/models.json" <<JSON
{
  "providers": {
    "deepseek": {
      "baseUrl": "${BASE_URL}",
      "api": "openai-completions",
      "apiKey": "\$DEEPSEEK_API_KEY",
      "compat": {
        "supportsDeveloperRole": false
      },
      "models": [
        {
          "id": "${MODEL_ID}",
          "name": "DeepSeek V4 Pro",
          "contextWindow": 1000000,
          "maxTokens": 384000,
          "input": ["text"],
          "reasoning": true,
          "cost": {
            "input": 1.74,
            "output": 3.48,
            "cacheRead": 0.145,
            "cacheWrite": 0
          },
          "compat": {
            "requiresReasoningContentOnAssistantMessages": true,
            "thinkingFormat": "deepseek",
            "reasoningEffortMap": {
              "minimal": "high",
              "low": "high",
              "medium": "high",
              "high": "high",
              "xhigh": "max"
            }
          }
        }
      ]
    }
  }
}
JSON

exec pi "$@"
