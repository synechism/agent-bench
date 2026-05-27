# Codex (OpenAI) agent image
FROM agent-harness/base:latest

# Install Codex CLI
RUN npm install -g @openai/codex

ENV HOME=/root
ENV NO_COLOR=1

RUN codex --version || echo "WARNING: codex --version failed"
