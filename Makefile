.PHONY: install build-base build test lint clean matrix dry-run summarize aggregate

install:
	pip install -e ".[dev]"

build-base:
	docker build -t agent-harness/base:latest -f docker/base.Dockerfile .

build: build-base
	docker build -t agent-harness/claude_code:latest -f docker/claude_code.Dockerfile .
	docker build -t agent-harness/codex:latest -f docker/codex.Dockerfile .
	docker build -t agent-harness/pi:latest -f docker/pi.Dockerfile .
	docker build -t agent-harness/opencode:latest -f docker/opencode.Dockerfile .

matrix:
	python -m orchestrator.matrix --config harness_config.json

dry-run:
	python -m orchestrator.matrix --config harness_config.json --dry-run

summarize:
	python -m analysis.summarize $(RUN_DIR)

aggregate:
	python -m analysis.aggregate runs/

lint:
	ruff check .
	mypy .

test:
	pytest -v

clean:
	rm -rf runs/* __pycache__ .pytest_cache

docker-clean:
	docker rm -f $$(docker ps -aq --filter "name=agent-harness") 2>/dev/null || true
