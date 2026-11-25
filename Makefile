# CareLedger developer commands (native, no Docker). On Windows use scripts\*.ps1 directly;
# this Makefile wraps the same steps for macOS/Linux shells. Python always runs from backend/.venv.
ifeq ($(OS),Windows_NT)
  VENV_BIN := backend/.venv/Scripts
else
  VENV_BIN := backend/.venv/bin
endif
PY := $(abspath $(VENV_BIN))/python
PS := powershell -NoProfile -ExecutionPolicy Bypass -File

.PHONY: help setup up down migrate seed test test-backend test-frontend e2e lint typecheck format gen-client

help:
	@echo "setup | up | down | migrate | seed | test | e2e | lint | typecheck | format | gen-client"

ifeq ($(OS),Windows_NT)
setup:         ## venv, deps, database, migrations, seed
	$(PS) scripts/setup.ps1
up:            ## Garnet + API + worker + web
	$(PS) scripts/dev.ps1
down:
	$(PS) scripts/dev.ps1 -Stop
else
setup:
	python3.12 -m venv backend/.venv
	$(PY) -m pip install -e "backend[dev]"
	cd frontend && npm ci
	cd backend && $(PY) -m alembic upgrade head && $(PY) -m seed
up:
	@echo "Start Postgres 16 and a Redis-compatible server, then in separate terminals:"
	@echo "  cd backend && $(PY) -m uvicorn app.main:app --reload --port 8000"
	@echo "  cd backend && $(PY) -m celery -A app.jobs.worker worker --loglevel=info"
	@echo "  cd frontend && npm run dev"
down:
	@echo "Stop the terminals started by 'make up'."
endif

migrate:
	cd backend && $(PY) -m alembic upgrade head

seed:          ## Deterministic, idempotent synthetic data
	cd backend && $(PY) -m alembic upgrade head && $(PY) -m seed

test: test-backend test-frontend

test-backend:  ## Needs PostgreSQL on localhost:5432
	cd backend && $(PY) -m pytest --cov --cov-report=term-missing:skip-covered

test-frontend:
	cd frontend && npm test

e2e:           ## Needs the running, seeded stack
	cd frontend && npm run test:e2e

lint:
	cd backend && $(PY) -m ruff check . && $(PY) -m ruff format --check .
	cd frontend && npm run lint && npm run format:check

typecheck:
	cd backend && $(PY) -m mypy
	cd frontend && npm run typecheck

format:
	cd backend && $(PY) -m ruff check --fix . && $(PY) -m ruff format .
	cd frontend && npm run format

gen-client:    ## Regenerate the typed TS client from FastAPI's OpenAPI spec
	cd backend && $(PY) -m app.export_openapi ../frontend/openapi.json
	cd frontend && npm run gen:client
