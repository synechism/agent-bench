PYTHON ?= python3
PIP ?= $(PYTHON) -m pip

.PHONY: install build-base build test lint clean matrix dry-run redis-linux dry-run-redis-linux summarize aggregate

install:
	$(PIP) install -e ".[dev]"

build-base:
	docker build -t agent-harness/base:latest -f docker/base.Dockerfile .

build: build-base
	docker build -t agent-harness/claude_code:latest -f docker/claude_code.Dockerfile .
	docker build -t agent-harness/codex:latest -f docker/codex.Dockerfile .
	docker build -t agent-harness/pi:latest -f docker/pi.Dockerfile .
	docker build -t agent-harness/opencode:latest -f docker/opencode.Dockerfile .

matrix:
	$(PYTHON) -m orchestrator.matrix --config harness_configs/harness_config.json

dry-run:
	$(PYTHON) -m orchestrator.matrix --config harness_configs/harness_config.json --dry-run

redis-linux:
	$(PYTHON) -m orchestrator.matrix --config harness_configs/harness_config_redis_linux.json

dry-run-redis-linux:
	$(PYTHON) -m orchestrator.matrix --config harness_configs/harness_config_redis_linux.json --dry-run

summarize:
	$(PYTHON) -m analysis.summarize $(RUN_DIR)

aggregate:
	$(PYTHON) -m analysis.aggregate runs/

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m mypy .

test:
	$(PYTHON) -m pytest -v

clean:
	rm -rf runs/* __pycache__ .pytest_cache

docker-clean:
	docker rm -f $$(docker ps -aq --filter "name=agent-harness") 2>/dev/null || true
