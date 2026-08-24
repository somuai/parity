from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil

from fastapi.testclient import TestClient
import pytest

from app.api.service import (
    APIService,
    ProductionRunExecutor,
    SnapshotStore,
    SnapshotValidationError,
)
from app.main import create_app


def _snapshot(run_id: str = "run-a", match_rate: float = 0.97) -> dict:
    summary = {
        "run_id": run_id,
        "timestamp_utc": "2026-08-24T00:00:00+00:00",
        "holdout_hash": "2aacac85b9d15cc186c63b2ceb1557767c99b3dfacd9931e4655a3fd7f9d8154",
        "outcome_digest": f"digest-{run_id}",
        "records_total": 2,
        "truth_transactions": 300,
        "match_rate": match_rate,
        "precision": 1.0,
        "recall": 0.98,
        "matches": {"tier1": 219, "tier2": 73, "total": 292},
        "exceptions": {
            "total": 8,
            "leakage": {"count": 4, "total_amount_at_risk_inr": "123.45"},
            "non_leakage": {"count": 4, "total_amount_at_risk_inr": "0"},
        },
        "budget": {
            "calls": {"used": 192, "limit": 500},
            "tokens": {"used": 127609, "limit": 200000},
        },
        "elapsed_seconds": 42.0,
    }
    return {
        "schema_version": 1,
        "run_id": run_id,
        "summary": summary,
        "records": [
            {
                "id": "bank_txn_0001",
                "source": "bank",
                "amount_inr": "70.00",
                "txn_date": "2026-08-01",
                "reference": "pay_1",
                "description": "partial refund",
                "counterparty": "Acme",
                "fees_deducted_inr": None,
                "status": "matched",
                "tier": 2,
                "confidence": 0.91,
                "confidence_band": "high",
                "rationale": (
                    "records=['bank_txn_0001','ledger_txn_0001']; "
                    "amount_delta=1.0000; semantic_similarity=0.8100; "
                    "partial_refund_plausible=True; fused_confidence=0.9100"
                ),
                "signal_scores": {
                    "amount_delta": 1.0,
                    "semantic_similarity": 0.81,
                    "partial_refund_plausible": 1.0,
                },
                "reason_code": None,
                "estimated_amount_at_risk_inr": None,
            },
            {
                "id": "ledger_txn_0001",
                "source": "ledger",
                "amount_inr": "100.00",
                "txn_date": "2026-08-01",
                "reference": "pay_1",
                "description": "invoice",
                "counterparty": "Acme",
                "fees_deducted_inr": None,
                "status": "matched",
                "tier": 2,
                "confidence": 0.91,
                "confidence_band": "high",
                "rationale": "same grounded decision",
                "signal_scores": {"amount_delta": 1.0, "semantic_similarity": 0.81},
                "reason_code": None,
                "estimated_amount_at_risk_inr": None,
            },
        ],
        "exception_book": {
            "leakage": {"entry_count": 4, "total_amount_at_risk_inr": "123.45"},
            "non_leakage": {"entry_count": 4, "total_amount_at_risk_inr": "0"},
        },
    }


@pytest.fixture
def store(tmp_path: Path) -> SnapshotStore:
    value = SnapshotStore(tmp_path / "results")
    value.rotate(_snapshot())
    return value


@pytest.fixture
def client(store: SnapshotStore, tmp_path: Path) -> TestClient:
    service = APIService(store, lambda: _snapshot("unused"))
    app = create_app(service=service, frontend_dist=tmp_path / "missing-dist")
    return TestClient(app)


def test_health_is_independent_of_snapshot(tmp_path: Path) -> None:
    empty_store = SnapshotStore(tmp_path / "empty")
    app = create_app(
        service=APIService(empty_store, lambda: _snapshot()),
        frontend_dist=tmp_path / "missing-dist",
    )
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_summary_exposes_tiers_budget_and_separate_risk_totals(
    client: TestClient,
) -> None:
    response = client.get("/api/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["matches"] == {"tier1": 219, "tier2": 73, "total": 292}
    assert body["exceptions"]["leakage"] == {
        "count": 4,
        "total_amount_at_risk_inr": "123.45",
    }
    assert body["exceptions"]["non_leakage"] == {
        "count": 4,
        "total_amount_at_risk_inr": "0",
    }
    assert body["budget"]["calls"] == {"used": 192, "limit": 500}


def test_records_and_detail_return_grounded_engine_values(client: TestClient) -> None:
    records_response = client.get("/api/records")
    detail_response = client.get("/api/records/bank_txn_0001")

    assert records_response.status_code == 200
    assert len(records_response.json()) == 2
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["tier"] == 2
    assert detail["confidence_band"] == "high"
    assert detail["signal_scores"]["partial_refund_plausible"] == 1.0
    assert "fused_confidence=0.9100" in detail["rationale"]
    assert client.get("/api/records/not-a-record").status_code == 404


def test_missing_snapshot_is_service_unavailable(tmp_path: Path) -> None:
    app = create_app(
        service=APIService(SnapshotStore(tmp_path / "empty"), lambda: _snapshot()),
        frontend_dist=tmp_path / "missing-dist",
    )

    response = TestClient(app).get("/api/summary")

    assert response.status_code == 503
    assert "No held-out result snapshot" in response.json()["detail"]


def test_rerun_rotates_snapshots_and_compares_match_rates(
    store: SnapshotStore, tmp_path: Path
) -> None:
    next_snapshot = _snapshot("run-b", 0.98)
    app = create_app(
        service=APIService(store, lambda: deepcopy(next_snapshot)),
        frontend_dist=tmp_path / "missing-dist",
    )

    response = TestClient(app).post("/api/rerun")

    assert response.status_code == 200
    assert response.json() == {
        "previous": {
            "run_id": "run-a",
            "match_rate": 0.97,
            "outcome_digest": "digest-run-a",
        },
        "current": {
            "run_id": "run-b",
            "match_rate": 0.98,
            "outcome_digest": "digest-run-b",
        },
        "reproducible": False,
        "match_rate_delta": pytest.approx(0.01),
    }
    assert store.load_current()["run_id"] == "run-b"
    assert store.load_previous()["run_id"] == "run-a"


def test_invalid_rerun_does_not_replace_current_snapshot(
    store: SnapshotStore, tmp_path: Path
) -> None:
    invalid = _snapshot("invalid")
    invalid["records"][0].pop("rationale")
    app = create_app(
        service=APIService(store, lambda: invalid),
        frontend_dist=tmp_path / "missing-dist",
    )

    with pytest.raises(SnapshotValidationError):
        TestClient(app).post("/api/rerun")

    assert store.load_current()["run_id"] == "run-a"
    assert store.load_previous() is None


def test_production_executor_replays_canonical_run_without_network(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    isolated = tmp_path / "clean-replay"
    shutil.copytree(repo_root / "data" / "holdout", isolated / "data" / "holdout")
    (isolated / "results").mkdir(parents=True)
    shutil.copy2(
        repo_root / "results" / "canonical_eval.json",
        isolated / "results" / "canonical_eval.json",
    )

    snapshot = ProductionRunExecutor(isolated)()

    summary = snapshot["summary"]
    assert summary["records_total"] == 628
    assert summary["truth_transactions"] == 300
    assert summary["matches"] == {"tier1": 219, "tier2": 53, "total": 272}
    assert summary["precision"] == 1.0
    assert summary["false_positive_cost_inr"] == "0"
    assert summary["audit"] == {"entries_written": 310, "records_covered": 628}
