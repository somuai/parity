"""HTTP routes for the read-mostly observability API."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from dotenv import load_dotenv

from app.api.service import APIService, RerunInProgressError, SnapshotNotFoundError
from clients.razorpay_client import RazorpayPayloadError, RazorpayReconClient


router = APIRouter(prefix="/api")
PUBLIC_RECON_SAMPLE_LIMIT = 5


def _service(request: Request) -> APIService:
    return request.app.state.api_service


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/razorpay/recon")
def razorpay_recon(
    year: int | None = None,
    month: int | None = None,
) -> dict[str, Any]:
    """Read the merchant's current Test Mode reconciliation feed.

    This endpoint deliberately returns a separately labelled, *unlabeled*
    source. It never enters the frozen bank/ledger evaluator or changes any
    match-rate, precision, recall, or exception-book metric.
    """

    now = datetime.now(timezone.utc)
    selected_year = year if year is not None else now.year
    selected_month = month if month is not None else now.month
    if not 1 <= selected_month <= 12:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="month must be between 1 and 12",
        )

    # Render supplies environment variables. Loading the untracked local
    # file makes the same read-only endpoint useful during local development.
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    try:
        client = RazorpayReconClient()
        raw_items = client.fetch_settlement_recon(selected_year, selected_month)
        payment_items = client.fetch_recent_payments(PUBLIC_RECON_SAMPLE_LIMIT)
        records = [
            {
                "id": record.record_id,
                "type": str(raw.get("type") or "unknown"),
                "amount_inr": str(record.amount),
                "txn_date": record.txn_date.isoformat(),
                "reference": record.reference,
                "description": record.description,
                "counterparty": record.counterparty,
                "fees_deducted_inr": (
                    str(record.fees_deducted)
                    if record.fees_deducted is not None
                    else None
                ),
            }
            for raw in raw_items
            for record in [client.to_canonical(raw)]
        ]
    except (RuntimeError, RazorpayPayloadError):
        # Do not expose credentials or raw provider errors in a public route.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Razorpay Test Mode feed is unavailable. Verify Test Mode "
                "credentials and try again."
            ),
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Razorpay Test Mode feed could not be fetched safely.",
        ) from None

    return {
        "source": "razorpay_test_mode",
        "evaluation_scope": "unlabeled_live_source_not_in_heldout_metrics",
        "year": selected_year,
        "month": selected_month,
        "validated_rows": len(records),
        # This is a public demo endpoint. A small normalized sample proves the
        # live integration without exposing an account's complete payment
        # history from the hosted page.
        "sample_limit": PUBLIC_RECON_SAMPLE_LIMIT,
        "records": records[:PUBLIC_RECON_SAMPLE_LIMIT],
        "recent_payment_activity": [
            {
                "id": str(raw.get("id")),
                "amount_inr": str(raw["amount"] / 100),
                "status": str(raw["status"]),
                "created_at": datetime.fromtimestamp(
                    int(raw["created_at"]), tz=timezone.utc
                ).isoformat(),
            }
            for raw in payment_items[:PUBLIC_RECON_SAMPLE_LIMIT]
        ],
        "empty_message": (
            "Connected, but no settled Test Mode transactions were returned for "
            f"{selected_year}-{selected_month:02d}. Test Mode payments can be "
            "captured without ever producing settlement Recon rows; recent payment "
            "activity is shown separately below."
            if not records
            else None
        ),
    }


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
