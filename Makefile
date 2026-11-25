# CareLedger developer commands. Python tooling always runs from backend/.venv locally.
ifeq ($(OS),Windows_NT)
  VENV_BIN := backend/.venv/Scripts
else
  VENV_BIN := backend/.venv/bin
endif
PY := $(abspath $(VENV_BIN))/python
COMPOSE := docker compose

.PHONY: help up down logs migrate seed test test-backend test-frontend e2e lint typecheck format gen-client venv install

help:
	@echo "up | down | logs | migrate | seed | test | e2e | lint | typecheck | format | gen-client | install"

up:            ## Build and start db, redis, api, worker, web
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f api worker web

migrate:       ## Apply migrations inside the api container
	$(COMPOSE) exec api alembic upgrade head

seed:          ## Deterministic, idempotent synthetic data
	$(COMPOSE) exec api python -m seed

venv:
	python3.12 -m venv backend/.venv || py -3.12 -m venv backend/.venv

install: venv  ## Local dev install (backend venv + frontend node_modules)
	$(PY) -m pip install -e "backend[dev]"
	cd frontend && npm ci

test: test-backend test-frontend

test-backend:  ## Needs Postgres on localhost:5432 (make up, or docker compose up -d db)
	cd backend && $(PY) -m pytest --cov --cov-report=term-missing:skip-covered

test-frontend:
	cd frontend && npm test

e2e:           ## Needs the full stack running and seeded
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
