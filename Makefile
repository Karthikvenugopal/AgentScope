PYTHON ?= python

.PHONY: install test lint docker-image demo dev frontend-check research-artifacts

install:
	$(PYTHON) -m pip install -e './backend[dev]'

test:
	$(PYTHON) -m pytest backend/tests

lint:
	$(PYTHON) -m ruff check backend
	$(PYTHON) -m mypy --config-file backend/pyproject.toml backend/app

docker-image:
	docker build --tag agentscope-runner:py312 --file docker/agent-runner.Dockerfile .

provider-image:
	docker compose --profile build build provider-image

demo:
	$(PYTHON) -m app.cli run --task incorrect_api_response --agent mock

dev:
	docker compose build backend frontend runner-image
	docker compose up -d --wait postgres
	docker compose --profile tools run --rm migrate
	docker compose up -d --wait backend frontend

frontend-check:
	cd frontend && npm run check-api && npm run typecheck && npm run lint && npm test && npm run build

research-artifacts:
	$(PYTHON) scripts/generate_research_artifacts.py
