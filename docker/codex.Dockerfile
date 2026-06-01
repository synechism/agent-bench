FROM golang:1.25-bookworm AS moonbridge-builder

ARG MOONBRIDGE_COMMIT=1b99888d3dae889b79ee602cb875c7907f7e76f2
RUN git clone https://github.com/ZhiYi-R/moon-bridge.git /src/moon-bridge && \
    cd /src/moon-bridge && \
    git checkout ${MOONBRIDGE_COMMIT} && \
    go build -o /out/moonbridge ./cmd/moonbridge

# Codex (OpenAI) agent image
FROM agent-harness/base:latest

# Install Codex CLI
ARG CODEX_VERSION=0.135.0
RUN npm install -g @openai/codex@${CODEX_VERSION}

COPY --from=moonbridge-builder /out/moonbridge /usr/local/bin/moonbridge
COPY docker/codex_with_moonbridge.sh /usr/local/bin/codex-with-moonbridge
RUN chmod +x /usr/local/bin/moonbridge /usr/local/bin/codex-with-moonbridge

ENV HOME=/root
ENV NO_COLOR=1

RUN codex --version || echo "WARNING: codex --version failed"
