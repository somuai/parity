.PHONY: setup confirm-api gen-data eval-data demo test

setup:
	pip install -r requirements.txt --break-system-packages

confirm-api:
	python3 scripts/confirm_api_connection.py

gen-data:
	python3 -m data.generators.truth_source
	python3 -m data.generators.bank_generator
	python3 -m data.generators.ledger_generator

# Full pipeline: generate held-out data, run the matching engine, print the
# metrics report. This is the command a stranger cloning the repo should be
# able to run to reproduce every number in the pitch.
demo: gen-data
	python3 -m eval.harness

test:
	pytest tests/ -v

# Local run of the hosted app (Phase 4+). Two processes: backend on :8000,
# frontend dev server on :5173 proxying /api to it. For production, the
# frontend is built once (`cd frontend && npm run build`) and FastAPI
# serves the static output directly -- see render.yaml.
run-backend:
	uvicorn app.main:app --reload --port 8000

run-frontend:
	cd frontend && npm install && npm run dev

build-frontend:
	cd frontend && npm install && npm run build
