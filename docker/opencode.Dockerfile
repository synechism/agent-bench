# OpenCode agent image
FROM agent-harness/base:latest

# Install OpenCode CLI
RUN npm install -g opencode-ai 2>/dev/null || \
    npm install -g @opencode/cli 2>/dev/null || \
    echo "WARNING: opencode npm package name TBD — verify on day 1"

ENV HOME=/root
ENV NO_COLOR=1

# RUN opencode --version || echo "WARNING: opencode --version failed"
