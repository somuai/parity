import json
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from config.schema import CanonicalRecord, Source
from data.generators.freeze_holdout import compute_holdout_hash
from engine.normalize import load_holdout_records, load_records
from engine.tier1_deterministic import match_tier1

HOLDOUT_DIR = Path("data/holdout")


def _record(
    record_id: str,
    source: Source,
    *,
    amount: str = "100.00",
    txn_date: date = date(2026, 7, 1),
    reference: str | None = "pay_exact",
) -> CanonicalRecord:
    return CanonicalRecord(
        record_id=record_id,
        source=source,
        amount=Decimal(amount),
        txn_date=txn_date,
        reference=reference,
        description="test",
    )


def _true_id(record_id: str, source: str, truth_ids: set[str]) -> str:
    source_suffix = record_id.removeprefix(f"{source}_")
    matches = [
        true_id
        for true_id in truth_ids
        if source_suffix == true_id or source_suffix.startswith(f"{true_id}_")
    ]
    assert len(matches) == 1, f"{record_id} resolved to {matches}"
    return matches[0]


def test_normalize_maps_csv_fields_to_canonical_records(tmp_path):
    csv_path = tmp_path / "bank.csv"
    csv_path.write_text(
        "record_id,reference,amount,txn_date,description,counterparty\n"
        "bank_1,pay_1,125.50,2026-07-03,Settlement,Customer A\n"
    )

    records = load_records(csv_path, Source.BANK)

    assert records == [
        CanonicalRecord(
            record_id="bank_1",
            source=Source.BANK,
            amount=Decimal("125.50"),
            txn_date=date(2026, 7, 3),
            reference="pay_1",
            description="Settlement",
            counterparty="Customer A",
        )
    ]


@pytest.mark.parametrize("lag_days", [0, 1, 2, 3, 4, 6, 7, 8, 9])
def test_tier1_accepts_only_documented_settlement_cycle_lags(lag_days):
    ledger_date = date(2026, 7, 1)
    bank = _record(
        "bank_1", Source.BANK, txn_date=ledger_date + timedelta(days=lag_days)
    )
    ledger = _record("ledger_1", Source.LEDGER, txn_date=ledger_date)

    decisions, unmatched_bank, unmatched_ledger = match_tier1([bank], [ledger])

    assert len(decisions) == 1
    assert unmatched_bank == []
    assert unmatched_ledger == []


@pytest.mark.parametrize("lag_days", [-1, 5, 10])
def test_tier1_rejects_dates_outside_documented_cycles(lag_days):
    ledger_date = date(2026, 7, 1)
    bank = _record(
        "bank_1", Source.BANK, txn_date=ledger_date + timedelta(days=lag_days)
    )
    ledger = _record("ledger_1", Source.LEDGER, txn_date=ledger_date)

    decisions, unmatched_bank, unmatched_ledger = match_tier1([bank], [ledger])

    assert decisions == []
    assert unmatched_bank == [bank]
    assert unmatched_ledger == [ledger]


def test_tier1_enforces_amount_reference_and_grounded_rationale():
    bank = _record("bank_1", Source.BANK, amount="100.00", reference="pay_123")
    at_limit = _record(
        "ledger_1", Source.LEDGER, amount="99.00", reference="pay_123"
    )

    decisions, _, _ = match_tier1([bank], [at_limit])

    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.tier == 1
    assert decision.confidence == 1.0
    assert "bank='pay_123', ledger='pay_123'" in decision.rationale
    assert "bank=₹100.00, ledger=₹99.00, delta=₹1.00" in decision.rationale
    assert "bank=2026-07-01, ledger=2026-07-01, bank_lag_days=0" in decision.rationale

    outside_limit = at_limit.model_copy(update={"amount": Decimal("98.99")})
    wrong_reference = at_limit.model_copy(update={"reference": "pay_other"})
    assert match_tier1([bank], [outside_limit])[0] == []
    assert match_tier1([bank], [wrong_reference])[0] == []


def test_tier1_refuses_ambiguous_duplicate_candidates():
    bank = _record("bank_1", Source.BANK)
    ledger_a = _record("ledger_1", Source.LEDGER)
    ledger_b = _record("ledger_1_dup", Source.LEDGER)

    decisions, unmatched_bank, unmatched_ledger = match_tier1(
        [bank], [ledger_a, ledger_b]
    )

    assert decisions == []
    assert unmatched_bank == [bank]
    assert unmatched_ledger == [ledger_a, ledger_b]


def test_heldout_match_rate_and_zero_false_positives():
    stored_hash = (HOLDOUT_DIR / "HOLDOUT_HASH.txt").read_text().strip()
    assert compute_holdout_hash(HOLDOUT_DIR) == stored_hash

    bank_records, ledger_records = load_holdout_records(HOLDOUT_DIR)
    decisions, unmatched_bank, unmatched_ledger = match_tier1(
        bank_records, ledger_records
    )
    truth = json.loads((HOLDOUT_DIR / "truth.json").read_text())
    truth_by_id = {item["true_id"]: item for item in truth}
    truth_ids = set(truth_by_id)

    false_positives = []
    matched_exception_types: Counter[str] = Counter()
    matched_true_ids: set[str] = set()
    for decision in decisions:
        assert decision.tier == 1
        assert decision.rationale
        assert len(decision.record_ids) == 2
        bank_id, ledger_id = decision.record_ids
        bank_true_id = _true_id(bank_id, "bank", truth_ids)
        ledger_true_id = _true_id(ledger_id, "ledger", truth_ids)
        if bank_true_id != ledger_true_id:
            false_positives.append((bank_id, ledger_id))
        else:
            matched_true_ids.add(bank_true_id)
            matched_exception_types[truth_by_id[bank_true_id]["exception_type"]] += 1

    # A match decision resolves two source records. Using all emitted source
    # rows as the denominator remains meaningful when group cases expand one
    # truth item into multiple bank or ledger rows.
    total_source_rows = len(bank_records) + len(ledger_records)
    resolved_source_rows = len(decisions) * 2
    match_rate = resolved_source_rows / total_source_rows
    unmatched_exception_types = Counter(
        item["exception_type"]
        for item in truth
        if item["true_id"] not in matched_true_ids
    )

    print(f"Tier 1 match rate: {match_rate:.2%} ({resolved_source_rows}/{total_source_rows})")
    print(f"False positives: {len(false_positives)}")
    print(f"Matched by exception type: {dict(sorted(matched_exception_types.items()))}")
    print(f"Left for Tier 2: {dict(sorted(unmatched_exception_types.items()))}")

    assert 0.55 <= match_rate <= 0.70
    assert false_positives == []
    assert len(unmatched_bank) + len(unmatched_ledger) == total_source_rows - resolved_source_rows
