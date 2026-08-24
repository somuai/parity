"""Conservative, deterministic one-to-one bank/ledger matching."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal

from config.schema import CanonicalRecord, MatchDecision, Source

AMOUNT_TOLERANCE = Decimal("1.00")

# apply_timing_lag uses T+2 or T+7 with jitter [-1, 0, 0, 1, 2].
# Zero is retained for clean same-day records; five days is not a generated
# settlement-cycle outcome and is intentionally excluded.
EXPECTED_BANK_LAGS_DAYS = frozenset({0, 1, 2, 3, 4, 6, 7, 8, 9})


def _validate_sources(
    bank_records: list[CanonicalRecord], ledger_records: list[CanonicalRecord]
) -> None:
    invalid_bank = [record.record_id for record in bank_records if record.source != Source.BANK]
    invalid_ledger = [
        record.record_id for record in ledger_records if record.source != Source.LEDGER
    ]
    if invalid_bank or invalid_ledger:
        raise ValueError(
            "Tier 1 received records with incorrect sources: "
            f"bank_input={invalid_bank}, ledger_input={invalid_ledger}"
        )


def _is_candidate(bank: CanonicalRecord, ledger: CanonicalRecord) -> bool:
    if not bank.reference or bank.reference != ledger.reference:
        return False
    if abs(bank.amount - ledger.amount) > AMOUNT_TOLERANCE:
        return False
    bank_lag_days = (bank.txn_date - ledger.txn_date).days
    return bank_lag_days in EXPECTED_BANK_LAGS_DAYS


def match_tier1(
    bank_records: list[CanonicalRecord],
    ledger_records: list[CanonicalRecord],
) -> tuple[list[MatchDecision], list[CanonicalRecord], list[CanonicalRecord]]:
    """Return unambiguous matches and untouched residual records.

    A pair is accepted only when it is the sole eligible candidate for both
    records. This symmetric uniqueness check makes duplicate rows residuals
    instead of resolving them through arbitrary input order.
    """
    _validate_sources(bank_records, ledger_records)

    candidates: list[tuple[int, int]] = []
    bank_candidate_counts: Counter[int] = Counter()
    ledger_candidate_counts: Counter[int] = Counter()
    ledger_by_reference: dict[str, list[tuple[int, CanonicalRecord]]] = {}
    for ledger_index, ledger in enumerate(ledger_records):
        if ledger.reference:
            ledger_by_reference.setdefault(ledger.reference, []).append(
                (ledger_index, ledger)
            )

    for bank_index, bank in enumerate(bank_records):
        if not bank.reference:
            continue
        for ledger_index, ledger in ledger_by_reference.get(bank.reference, []):
            if _is_candidate(bank, ledger):
                candidates.append((bank_index, ledger_index))
                bank_candidate_counts[bank_index] += 1
                ledger_candidate_counts[ledger_index] += 1

    accepted_pairs = [
        pair
        for pair in candidates
        if bank_candidate_counts[pair[0]] == 1
        and ledger_candidate_counts[pair[1]] == 1
    ]

    decisions: list[MatchDecision] = []
    matched_bank_indexes: set[int] = set()
    matched_ledger_indexes: set[int] = set()
    for bank_index, ledger_index in accepted_pairs:
        bank = bank_records[bank_index]
        ledger = ledger_records[ledger_index]
        amount_delta = abs(bank.amount - ledger.amount)
        date_delta = (bank.txn_date - ledger.txn_date).days
        decisions.append(
            MatchDecision(
                record_ids=[bank.record_id, ledger.record_id],
                tier=1,
                confidence=1.0,
                rationale=(
                    f"Exact reference matched: bank={bank.reference!r}, "
                    f"ledger={ledger.reference!r}; amounts within ₹1.00: "
                    f"bank=₹{bank.amount}, ledger=₹{ledger.amount}, "
                    f"delta=₹{amount_delta}; dates within expected settlement "
                    f"cycle: bank={bank.txn_date.isoformat()}, "
                    f"ledger={ledger.txn_date.isoformat()}, "
                    f"bank_lag_days={date_delta}."
                ),
                signal_scores={
                    "reference_exact": 1.0,
                    "amount_delta": float(amount_delta),
                    "date_delta_days": float(date_delta),
                },
            )
        )
        matched_bank_indexes.add(bank_index)
        matched_ledger_indexes.add(ledger_index)

    unmatched_bank = [
        record
        for index, record in enumerate(bank_records)
        if index not in matched_bank_indexes
    ]
    unmatched_ledger = [
        record
        for index, record in enumerate(ledger_records)
        if index not in matched_ledger_indexes
    ]
    return decisions, unmatched_bank, unmatched_ledger
