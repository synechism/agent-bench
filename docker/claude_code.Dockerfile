# Claude Code agent image
FROM agent-harness/base:latest

# Install Claude Code CLI (Node.js)
# Use the published npm package or local source checkout
ARG CLAUDE_VERSION=latest
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_VERSION}

# Claude Code needs a home directory for config
ENV HOME=/root
ENV CLAUDE_CODE_HEADLESS=1
ENV NO_COLOR=1

RUN mkdir -p /root/.claude

# Verify the binary exists
RUN claude --version || echo "WARNING: claude --version failed"
