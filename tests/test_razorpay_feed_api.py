from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.api.service import APIService, SnapshotStore
from app.main import create_app
from config.schema import CanonicalRecord, Source


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        service=APIService(SnapshotStore(tmp_path / "results"), lambda: {}),
        frontend_dist=tmp_path / "missing-dist",
    )
    return TestClient(app)


def test_razorpay_recon_is_a_sampled_unlabeled_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeRazorpayReconClient:
        def fetch_settlement_recon(self, year: int, month: int) -> list[dict]:
            assert (year, month) == (2026, 8)
            return [{"entity_id": f"txn_{index}", "type": "payment"} for index in range(6)]

        @staticmethod
        def to_canonical(raw: dict) -> CanonicalRecord:
            return CanonicalRecord(
                record_id=f"razorpay_{raw['entity_id']}",
                source=Source.RAZORPAY,
                amount=Decimal("125.00"),
                txn_date=date(2026, 8, 24),
                reference="order_test",
                description="Test Mode payment",
                counterparty=None,
            )

    monkeypatch.setattr("app.api.routes.RazorpayReconClient", FakeRazorpayReconClient)

    response = _client(tmp_path).get("/api/razorpay/recon?year=2026&month=8")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "razorpay_test_mode"
    assert body["evaluation_scope"] == "unlabeled_live_source_not_in_heldout_metrics"
    assert body["validated_rows"] == 6
    assert body["sample_limit"] == 5
    assert len(body["records"]) == 5
    assert body["records"][0]["amount_inr"] == "125.00"


def test_razorpay_recon_hides_credentials_when_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class UnavailableRazorpayReconClient:
        def __init__(self) -> None:
            raise RuntimeError("secret-key-must-not-appear")

    monkeypatch.setattr(
        "app.api.routes.RazorpayReconClient", UnavailableRazorpayReconClient
    )

    response = _client(tmp_path).get("/api/razorpay/recon")

    assert response.status_code == 503
    assert "secret-key-must-not-appear" not in response.json()["detail"]
