"""
FastAPI backend for Parity's hosted app.

Scaffolded here with just health + static mounting so Phase 4's backend
subagent has a running start. The real endpoints (/api/summary,
/api/records, /api/records/{id}, /api/rerun) are that subagent's job --
see docs/codex_prompts/04_audit_observability_agent.md.
"""
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Parity")


@app.get("/api/health")
def health():
    return {"status": "ok"}


# TODO (Phase 4, Subagent B): implement these against engine/ and eval/ output.
# @app.get("/api/summary") ...
# @app.get("/api/records") ...
# @app.get("/api/records/{record_id}") ...
# @app.post("/api/rerun") ...


# Mount the built frontend last, so /api/* routes above take priority over
# the SPA's catch-all static serving.
_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
