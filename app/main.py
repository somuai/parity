"""FastAPI entry point for Parity's single-service hosted application."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.api.service import APIService, ProductionRunExecutor, SnapshotStore


REPO_ROOT = Path(__file__).resolve().parent.parent


def create_app(
    *,
    service: APIService | None = None,
    frontend_dist: Path | None = None,
) -> FastAPI:
    """Create the app with injectable storage/execution for offline tests."""

    application = FastAPI(title="Parity", version="1.0.0")
    application.state.api_service = service or APIService(
        SnapshotStore(REPO_ROOT / "results"),
        ProductionRunExecutor(REPO_ROOT),
    )
    application.include_router(router)

    # API routes are registered first. The SPA mount must remain last so it
    # cannot intercept /api/* requests.
    static_dir = frontend_dist or REPO_ROOT / "frontend" / "dist"
    if static_dir.exists():
        application.mount(
            "/", StaticFiles(directory=str(static_dir), html=True), name="frontend"
        )
    return application


app = create_app()
