# Pi (Google DeepMind) agent image
# NOTE: Verify installation method against actual Pi release artifacts on day 1.
FROM agent-harness/base:latest

# Pi is a Python-based agent. Install via pip if published, or from source.
# Placeholder — update once the install method is confirmed.
ARG PI_VERSION=latest
RUN pip3 install --break-system-packages pi-agent-cli 2>/dev/null || \
    echo "WARNING: pi-agent-cli not on PyPI — install from source or bundled binary"

ENV HOME=/root
ENV NO_COLOR=1

# RUN pi --version || echo "WARNING: pi --version failed"
