"""HTTP routes for the read-mostly observability API."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from app.api.service import APIService, RerunInProgressError, SnapshotNotFoundError


router = APIRouter(prefix="/api")


def _service(request: Request) -> APIService:
    return request.app.state.api_service


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/summary")
def summary(request: Request) -> dict[str, Any]:
    try:
        return _service(request).summary()
    except SnapshotNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/records")
def records(request: Request) -> list[dict[str, Any]]:
    try:
        return _service(request).records()
    except SnapshotNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/records/{record_id}")
def record_detail(record_id: str, request: Request) -> dict[str, Any]:
    try:
        record = _service(request).record(record_id)
    except SnapshotNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown record ID: {record_id}")
    return record


@router.post("/rerun")
def rerun(request: Request) -> dict[str, Any]:
    try:
        return _service(request).rerun()
    except RerunInProgressError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

