.PHONY: setup confirm-api gen-data eval-data eval-tier2-live demo test

PYTHON ?= python3.12
VENV := .venv
RUN := $(VENV)/bin/python

$(RUN):
	$(PYTHON) -m venv $(VENV)

setup: $(RUN)
	$(RUN) -m pip install --upgrade pip
	$(RUN) -m pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu
	$(RUN) -m pip install -r requirements.txt
	cd frontend && npm ci

confirm-api:
	$(RUN) scripts/confirm_api_connection.py

gen-data:
	$(RUN) -m data.generators.truth_source
	$(RUN) -m data.generators.bank_generator
	$(RUN) -m data.generators.ledger_generator

# Deterministic canonical replay: verifies the immutable hash and Tier 1,
# regrades the captured live Tier 2 decisions, and republishes audit/results.
demo:
	$(RUN) -m eval.harness

test:
	$(RUN) -m pytest tests/ -v

# Explicit canonical refresh: frozen hash + real MiniLM + live Groq.
eval-tier2-live:
	$(RUN) -m eval.harness --live

# Local run of the hosted app (Phase 4+). Two processes: backend on :8000,
# frontend dev server on :5173 proxying /api to it. For production, the
# frontend is built once (`cd frontend && npm run build`) and FastAPI
# serves the static output directly -- see render.yaml.
run-backend:
	$(RUN) -m uvicorn app.main:app --reload --port 8000

run-frontend:
	cd frontend && npm install && npm run dev

build-frontend:
	cd frontend && npm install && npm run build
