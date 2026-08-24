from __future__ import annotations

from datetime import date
from decimal import Decimal
import json

import pytest

from config.schema import (
    CanonicalRecord,
    ExceptionRecord,
    ExceptionType,
    MatchDecision,
    Source,
)
from engine.audit import AuditStore
from eval.exception_book import build_exception_book, write_exception_book


def _record(
    record_id: str,
    source: Source,
    amount: str,
) -> CanonicalRecord:
    return CanonicalRecord(
        record_id=record_id,
        source=source,
        amount=Decimal(amount),
        txn_date=date(2026, 1, 2),
        reference="pay_123",
        description="Settlement pay_123",
        counterparty="Acme",
    )


def _decision() -> MatchDecision:
    return MatchDecision(
        record_ids=["bank_1", "ledger_1"],
        tier=2,
        confidence=0.93,
        rationale=(
            "records=['bank_1', 'ledger_1']; amount_delta=0.0200; "
            "timing_delta=0.0000; semantic_similarity=0.9100"
        ),
        signal_scores={
            "amount_delta": 0.02,
            "timing_delta": 0.0,
            "semantic_similarity": 0.91,
        },
    )


def test_audit_store_persists_full_payload_and_queries_every_source_id(tmp_path):
    decision = _decision()
    exception = ExceptionRecord(
        record_ids=["ledger_dup"],
        reason_code=ExceptionType.DUPLICATE_ENTRY,
        reason_detail=(
            "ledger_dup repeats ledger_1 with reference='pay_123', amount=₹70.00."
        ),
        estimated_amount_at_risk=Decimal("70.00"),
    )

    database = tmp_path / "audit.sqlite3"
    with AuditStore(database) as store:
        audit_ids = store.persist_all([decision], [exception])

        assert audit_ids == [1, 2]
        assert store.count() == 2
        assert store.audited_record_ids() == {"bank_1", "ledger_1", "ledger_dup"}
        bank_entry = store.get_by_record_id("bank_1")[0]
        duplicate_entry = store.get_by_record_id("ledger_dup")[0]
        assert bank_entry["entry_type"] == "match_decision"
        assert bank_entry["record_ids"] == decision.record_ids
        assert bank_entry["signal_scores"] == decision.signal_scores
        assert bank_entry["payload"] == decision.model_dump(mode="json")
        assert duplicate_entry["entry_type"] == "exception_record"
        assert duplicate_entry["reason_code"] == "duplicate_entry"
        assert duplicate_entry["estimated_amount_at_risk"] == "70.00"
        assert duplicate_entry["signal_scores"] == exception.signal_scores
        assert "signal_scores_json" not in duplicate_entry
        assert duplicate_entry["payload"] == exception.model_dump(mode="json")
        store.verify_record_coverage({"bank_1", "ledger_1", "ledger_dup"})
        with pytest.raises(RuntimeError, match="missing_source"):
            store.verify_record_coverage({"bank_1", "missing_source"})

    # The audit trail remains queryable after reopening the SQLite file.
    with AuditStore(database) as reopened:
        assert reopened.get_by_record_id("ledger_1")[0]["audit_id"] == 1


def test_audit_store_rejects_ungrounded_or_untraceable_entries():
    with AuditStore(":memory:") as store:
        with pytest.raises(ValueError, match="rationale"):
            store.persist_decision(_decision().model_copy(update={"rationale": ""}))
        with pytest.raises(ValueError, match="source record ID"):
            store.persist_exception(
                ExceptionRecord(
                    record_ids=[],
                    reason_code=ExceptionType.ORPHAN,
                    reason_detail="No bank candidate exists for ledger_9.",
                )
            )
        assert store.count() == 0


def test_persist_all_rolls_back_the_whole_run_when_one_entry_is_invalid():
    invalid_exception = ExceptionRecord(
        record_ids=[],
        reason_code=ExceptionType.ORPHAN,
        reason_detail="No source IDs were supplied by the matching run.",
    )
    with AuditStore(":memory:") as store:
        with pytest.raises(ValueError, match="source record ID"):
            store.persist_all([_decision()], [invalid_exception])
        assert store.count() == 0


def test_audit_coverage_is_scoped_to_one_run():
    with AuditStore(":memory:") as store:
        store.persist_all([_decision()], [], run_id="run-a")
        store.persist_all(
            [],
            [
                ExceptionRecord(
                    record_ids=["bank_1"],
                    reason_code=ExceptionType.ORPHAN,
                    reason_detail="No ledger candidate exists for bank_1 in run-b.",
                )
            ],
            run_id="run-b",
        )

        assert len(store.get_by_record_id("bank_1")) == 2
        assert len(store.get_by_record_id("bank_1", run_id="run-b")) == 1
        with pytest.raises(RuntimeError, match="ledger_1"):
            store.verify_record_coverage(
                {"bank_1", "ledger_1"},
                run_id="run-b",
            )


def test_exception_book_separates_leakage_and_documents_amount_sources(tmp_path):
    records = {
        record.record_id: record
        for record in [
            _record("ledger_dup", Source.LEDGER, "70.00"),
            _record("bank_refund", Source.BANK, "100.00"),
            _record("ledger_refund", Source.LEDGER, "70.00"),
            _record("bank_orphan", Source.BANK, "500.00"),
        ]
    }
    exceptions = [
        ExceptionRecord(
            record_ids=["ledger_dup"],
            reason_code=ExceptionType.DUPLICATE_ENTRY,
            reason_detail="ledger_dup duplicates ledger_1 at amount=₹70.00.",
        ),
        ExceptionRecord(
            record_ids=["bank_refund", "ledger_refund"],
            reason_code=ExceptionType.PARTIAL_REFUND,
            reason_detail=(
                "bank_refund=₹100.00 vs ledger_refund=₹70.00; refund_ratio=0.70."
            ),
        ),
        ExceptionRecord(
            record_ids=["bank_orphan"],
            reason_code=ExceptionType.ORPHAN,
            reason_detail=(
                "No ledger candidate exists for bank_orphan, reference='pay_123'."
            ),
            estimated_amount_at_risk=Decimal("500.00"),
        ),
        ExceptionRecord(
            record_ids=["bank_fx", "ledger_fx"],
            reason_code=ExceptionType.FX_ROUNDING,
            reason_detail="bank_fx vs ledger_fx differs by ₹0.02 due to FX rounding.",
            estimated_amount_at_risk=Decimal("0.02"),
        ),
    ]

    book = build_exception_book(exceptions, records)
    assert book["total_entries"] == 4
    assert book["leakage"] == {
        "entry_count": 2,
        "total_amount_at_risk_inr": "100.00",
    }
    assert book["non_leakage"] == {
        "entry_count": 2,
        "total_amount_at_risk_inr": "500.02",
    }
    duplicate = book["groups"]["duplicate_entry"]["entries"][0]
    refund = book["groups"]["partial_refund"]["entries"][0]
    orphan = book["groups"]["orphan"]["entries"][0]
    assert duplicate["estimated_amount_at_risk_inr"] == "70.00"
    assert duplicate["amount_source"] == "derived_record_evidence"
    assert refund["estimated_amount_at_risk_inr"] == "30.00"
    assert refund["risk_classification"] == "leakage"
    assert orphan["risk_classification"] == "non_leakage"
    assert "review-only" in orphan["classification_reason"]

    output = tmp_path / "results" / "exception_book.json"
    assert write_exception_book(exceptions, output, records) == book
    assert json.loads(output.read_text(encoding="utf-8")) == book


def test_leakage_capable_entry_without_supported_amount_is_not_counted():
    exception = ExceptionRecord(
        record_ids=["missing_duplicate"],
        reason_code=ExceptionType.DUPLICATE_ENTRY,
        reason_detail="missing_duplicate duplicates a row absent from the source lookup.",
    )
    book = build_exception_book([exception], source_records={})
    entry = book["groups"]["duplicate_entry"]["entries"][0]
    assert book["leakage"]["entry_count"] == 0
    assert book["leakage"]["total_amount_at_risk_inr"] == "0"
    assert book["non_leakage"]["entry_count"] == 1
    assert entry["amount_source"] == "unavailable"
    assert entry["risk_classification"] == "non_leakage"


@pytest.mark.parametrize(
    "reason_detail",
    ["", "Could not match", "UNRESOLVED.", "manual review required"],
)
def test_exception_book_rejects_empty_or_generic_reason_detail(reason_detail):
    exception = ExceptionRecord(
        record_ids=["ledger_9"],
        reason_code=ExceptionType.MISSING_REFERENCE,
        reason_detail=reason_detail,
    )
    with pytest.raises(ValueError, match="generic reason_detail"):
        build_exception_book([exception])
