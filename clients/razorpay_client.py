"""Validated Razorpay Settlement Recon API client for the ungraded live leg."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
import os
from typing import Any

import requests

from config.schema import CanonicalRecord, Source


RAZORPAY_BASE_URL = "https://api.razorpay.com/v1"
MAX_PAGE_SIZE = 1000


class RazorpayPayloadError(RuntimeError):
    """Raised when a successful provider response is not safe to reconcile."""


def _required_nonempty_id(raw: Mapping[str, Any]) -> str:
    value = raw.get("entity_id") or raw.get("id")
    if not isinstance(value, str) or not value.strip():
        raise RazorpayPayloadError("Razorpay recon item is missing a stable entity ID")
    return value.strip()


def _paise(raw: Mapping[str, Any], name: str, *, required: bool = True) -> int:
    value = raw.get(name)
    if value is None and not required:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RazorpayPayloadError(
            f"Razorpay recon item field {name!r} must be non-negative integer paise"
        )
    return value


def _validate_item(raw: object) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise RazorpayPayloadError("Every Razorpay recon item must be an object")
    _required_nonempty_id(raw)
    amount = _paise(raw, "amount")
    debit = _paise(raw, "debit")
    credit = _paise(raw, "credit")
    if (debit > 0) == (credit > 0):
        raise RazorpayPayloadError(
            "Razorpay recon item must contain exactly one positive debit or credit"
        )
    if amount != max(debit, credit):
        raise RazorpayPayloadError(
            "Razorpay recon amount disagrees with its debit/credit direction"
        )
    settled_at = raw.get("settled_at")
    if isinstance(settled_at, bool) or not isinstance(settled_at, int) or settled_at <= 0:
        raise RazorpayPayloadError(
            "Razorpay recon item is missing a valid settled_at timestamp"
        )
    currency = raw.get("currency")
    if currency is not None and str(currency).upper() != "INR":
        raise RazorpayPayloadError(
            f"Unsupported Razorpay recon currency: {currency!r}"
        )
    if raw.get("fee") is not None:
        _paise(raw, "fee")
    return raw


class RazorpayReconClient:
    def __init__(
        self,
        key_id: str | None = None,
        key_secret: str | None = None,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.key_id = key_id or os.environ.get("RAZORPAY_TEST_KEY_ID")
        self.key_secret = key_secret or os.environ.get("RAZORPAY_TEST_KEY_SECRET")
        self.session = session or requests.Session()
        if not self.key_id or not self.key_secret:
            raise RuntimeError(
                "Missing RAZORPAY_TEST_KEY_ID / RAZORPAY_TEST_KEY_SECRET. "
                "Copy .env.example to .env and fill in your test-mode keys."
            )

    def fetch_settlement_recon(
        self,
        year: int,
        month: int,
        count: int = MAX_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        """Fetch every validated page; a valid empty collection returns ``[]``."""

        if not 1 <= month <= 12:
            raise ValueError("month must be between 1 and 12")
        if not 1 <= count <= MAX_PAGE_SIZE:
            raise ValueError(f"count must be between 1 and {MAX_PAGE_SIZE}")

        collected: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        skip = 0
        while True:
            response = self.session.get(
                f"{RAZORPAY_BASE_URL}/settlements/recon/combined",
                params={
                    "year": year,
                    "month": f"{month:02d}",
                    "count": count,
                    "skip": skip,
                },
                auth=(self.key_id, self.key_secret),
                timeout=15,
            )
            response.raise_for_status()
            try:
                body = response.json()
            except ValueError as exc:
                raise RazorpayPayloadError("Razorpay returned invalid JSON") from exc
            if not isinstance(body, Mapping) or not isinstance(body.get("items"), list):
                raise RazorpayPayloadError(
                    "Razorpay recon response must be an object containing an items array"
                )
            page = body["items"]
            for candidate in page:
                raw = dict(_validate_item(candidate))
                stable_id = _required_nonempty_id(raw)
                if stable_id in seen_ids:
                    raise RazorpayPayloadError(
                        f"Duplicate Razorpay entity ID across pages: {stable_id}"
                    )
                seen_ids.add(stable_id)
                collected.append(raw)
            if len(page) < count:
                break
            skip += count
        return collected

    def fetch_recent_payments(self, count: int = 5) -> list[dict[str, Any]]:
        """Return a small, validated Test Mode payment-activity sample.

        Payment activity is deliberately distinct from settlement reconciliation:
        a captured Test Mode payment is useful connection evidence but is not a
        settled bank row and must never enter the held-out evaluator.
        """
        if not 1 <= count <= MAX_PAGE_SIZE:
            raise ValueError(f"count must be between 1 and {MAX_PAGE_SIZE}")
        response = self.session.get(
            f"{RAZORPAY_BASE_URL}/payments",
            params={"count": count},
            auth=(self.key_id, self.key_secret),
            timeout=15,
        )
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as exc:
            raise RazorpayPayloadError("Razorpay returned invalid payment JSON") from exc
        if not isinstance(body, Mapping) or not isinstance(body.get("items"), list):
            raise RazorpayPayloadError("Razorpay payment response must contain an items array")
        safe: list[dict[str, Any]] = []
        for raw in body["items"]:
            if not isinstance(raw, Mapping):
                raise RazorpayPayloadError("Every Razorpay payment item must be an object")
            item = dict(raw)
            _required_nonempty_id(item)
            _paise(item, "amount")
            if str(item.get("currency") or "").upper() != "INR":
                raise RazorpayPayloadError("Unsupported Razorpay payment currency")
            if not isinstance(item.get("status"), str) or not item["status"].strip():
                raise RazorpayPayloadError("Razorpay payment is missing a status")
            created_at = item.get("created_at")
            if isinstance(created_at, bool) or not isinstance(created_at, int) or created_at <= 0:
                raise RazorpayPayloadError("Razorpay payment is missing a valid created_at")
            safe.append(item)
        return safe

    @staticmethod
    def to_canonical(raw: Mapping[str, Any]) -> CanonicalRecord:
        """Map one validated item into signed INR and settlement-date semantics."""

        item = _validate_item(raw)
        stable_id = _required_nonempty_id(item)
        debit = _paise(item, "debit")
        credit = _paise(item, "credit")
        signed_paise = credit - debit
        settled_at = int(item["settled_at"])
        fee = _paise(item, "fee", required=False)
        return CanonicalRecord(
            record_id=f"razorpay_{stable_id}",
            source=Source.RAZORPAY,
            amount=Decimal(signed_paise) / 100,
            txn_date=datetime.fromtimestamp(settled_at, tz=timezone.utc).date(),
            reference=item.get("payment_id") or item.get("order_id"),
            description=str(item.get("description") or item.get("type") or ""),
            counterparty=item.get("bank") or item.get("wallet") or None,
            fees_deducted=Decimal(fee) / 100 if fee else None,
        )


__all__ = ["RazorpayPayloadError", "RazorpayReconClient"]
