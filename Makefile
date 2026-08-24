.PHONY: setup confirm-api gen-data eval-data eval-tier2-live demo test

setup:
	pip install torch --index-url https://download.pytorch.org/whl/cpu --break-system-packages
	pip install -r requirements.txt --break-system-packages

confirm-api:
	python3 scripts/confirm_api_connection.py

gen-data:
	python3 -m data.generators.truth_source
	python3 -m data.generators.bank_generator
	python3 -m data.generators.ledger_generator

# Full fixture-free pipeline: verify the immutable held-out hash, run the
# matching engine, persist audit/exception/snapshot artifacts, print metrics.
# Never regenerate the frozen holdout as part of evaluation.
demo:
	python3 -m eval.harness

test:
	pytest tests/ -v

# Fixture-free Phase 3 gate: frozen hash + real MiniLM + live Groq.
eval-tier2-live:
	python3 -m eval.phase3_live

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
