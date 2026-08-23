"""
Thin wrapper around Razorpay's Settlement Recon API (test mode).

Docs: https://razorpay.com/docs/api/settlements/fetch-recon/
Endpoint: GET /v1/settlements/recon/combined?year=YYYY&month=MM

Returns payments, refunds, transfers, and adjustments settled in a given
month — this is Parity's "real" leg. Bank statement and internal ledger
stay synthetic (see data/generators/).

Phase 0 exit criteria: run scripts/confirm_api_connection.py successfully
against your own test-mode keys before any matching code gets written.
"""
from __future__ import annotations
import os
import requests
from datetime import date
from decimal import Decimal
from typing import Any

from config.schema import CanonicalRecord, Source

RAZORPAY_BASE_URL = "https://api.razorpay.com/v1"


class RazorpayReconClient:
    def __init__(self, key_id: str | None = None, key_secret: str | None = None):
        self.key_id = key_id or os.environ.get("RAZORPAY_TEST_KEY_ID")
        self.key_secret = key_secret or os.environ.get("RAZORPAY_TEST_KEY_SECRET")
        if not self.key_id or not self.key_secret:
            raise RuntimeError(
                "Missing RAZORPAY_TEST_KEY_ID / RAZORPAY_TEST_KEY_SECRET. "
                "Copy .env.example to .env and fill in your test-mode keys "
                "from the Razorpay Dashboard (Settings > API Keys > Test Mode)."
            )

    def fetch_settlement_recon(self, year: int, month: int, count: int = 100) -> list[dict[str, Any]]:
        """Fetch combined settlement recon (payments/refunds/transfers/adjustments)
        for a given year/month. Test-mode keys only hit test-mode data."""
        resp = requests.get(
            f"{RAZORPAY_BASE_URL}/settlements/recon/combined",
            params={"year": year, "month": f"{month:02d}", "count": count},
            auth=(self.key_id, self.key_secret),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("items", [])

    @staticmethod
    def to_canonical(raw: dict[str, Any]) -> CanonicalRecord:
        """Map a raw Settlement Recon line item to the canonical schema."""
        return CanonicalRecord(
            record_id=f"razorpay_{raw.get('id', raw.get('entity_id', 'unknown'))}",
            source=Source.RAZORPAY,
            amount=Decimal(raw.get("amount", 0)) / 100,  # paise -> INR
            txn_date=date.fromtimestamp(raw.get("created_at", 0)) if raw.get("created_at") else date.today(),
            reference=raw.get("payment_id") or raw.get("order_id"),
            description=raw.get("description", "") or raw.get("type", ""),
            counterparty=raw.get("bank") or raw.get("wallet") or None,
            fees_deducted=(Decimal(raw.get("fee", 0)) / 100) if raw.get("fee") is not None else None,
        )
