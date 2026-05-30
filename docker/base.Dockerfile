# Shared base image: Ubuntu + measurement tooling + PATH shims
# Every agent image inherits from this.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# System packages for measurement + common build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Measurement tooling
    procps \
    htop \
    bpftrace \
    bpfcc-tools \
    linux-tools-generic \
    # Build essentials (codebases need these)
    build-essential \
    git \
    curl \
    wget \
    ca-certificates \
    # Languages
    python3 \
    python3-pip \
    python3-venv \
    nodejs \
    npm \
    cargo \
    rustc \
    golang-go \
    # Utilities
    ripgrep \
    jq \
    yq \
    fd-find \
    tree \
    && rm -rf /var/lib/apt/lists/*

# Install Python harness
COPY pyproject.toml /app/pyproject.toml
COPY orchestrator/ /app/orchestrator/
COPY adapters/ /app/adapters/
COPY measure/ /app/measure/
COPY analysis/ /app/analysis/
RUN pip3 install --break-system-packages /app/

# Set up shim directory
COPY measure/shims/_template.sh /opt/shims/_template.sh
RUN chmod +x /opt/shims/_template.sh && \
    for tool in rg grep cat head tail find git make cmake cargo go rustc gcc clang \
                pytest python python3 node npm npx ls cp mv rm mkdir chmod \
                bash sh zsh curl wget awk sed sort uniq wc jq tsc pip java javac mvn; do \
        if command -v $tool >/dev/null 2>&1; then \
            ln -sf /opt/shims/_template.sh /opt/shims/$tool; \
        fi; \
    done

WORKDIR /codebase
ENTRYPOINT ["harness"]
