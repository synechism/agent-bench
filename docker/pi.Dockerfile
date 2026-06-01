# Pi coding agent image
FROM agent-harness/base:latest

# Pi is distributed as an npm CLI package and currently requires modern Node.
ARG PI_VERSION=0.78.0
RUN npm install -g n && \
    n 22.19.0 && \
    hash -r && \
    npm install -g @earendil-works/pi-coding-agent@${PI_VERSION}

COPY docker/pi_with_deepseek.sh /usr/local/bin/pi-with-deepseek
RUN chmod +x /usr/local/bin/pi-with-deepseek

ENV HOME=/root
ENV NO_COLOR=1
ENV PI_TELEMETRY=0

RUN pi --version || echo "WARNING: pi --version failed"
