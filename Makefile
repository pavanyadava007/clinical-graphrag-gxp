PY ?= .venv/bin/python
export CGG_USER ?= pavan.dev

.PHONY: setup services gate oq iq pipeline evals results validation stop

setup:
	uv venv -p 3.11 .venv && uv pip install -p .venv -e ".[dev]"
	$(PY) scripts/init_env.py

services:
	docker compose -f infra/docker-compose.yml --env-file infra/.env up -d

gate:
	$(PY) -m ruff check . && $(PY) -m pytest -q

oq:
	CGG_OQ_RECORD=1 $(PY) -m pytest -q

iq:
	$(PY) scripts/iq_check.py

pipeline:
	scripts/run_pipeline.sh

evals:
	scripts/run_evals.sh

results:
	$(PY) scripts/make_results.py

validation:
	$(PY) -m cgg.cli validation-report

stop:
	docker compose -f infra/docker-compose.yml --env-file infra/.env stop
