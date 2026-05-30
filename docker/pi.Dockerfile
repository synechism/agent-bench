# Pi coding agent image
FROM agent-harness/base:latest

# Pi is distributed as an npm CLI package and currently requires modern Node.
ARG PI_VERSION=latest
RUN npm install -g n && \
    n 22.19.0 && \
    hash -r && \
    npm install -g @earendil-works/pi-coding-agent@${PI_VERSION}

ENV HOME=/root
ENV NO_COLOR=1

RUN pi --version || echo "WARNING: pi --version failed"
