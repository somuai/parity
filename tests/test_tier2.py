from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from config.schema import CanonicalRecord, ExceptionType, Source
from data.generators.freeze_holdout import compute_holdout_hash
from engine.adjudicator import (
    AdjudicationResult,
    BudgetExceededError,
    LLMBudget,
    Verdict,
    adjudicate,
    compute_group_sum_check,
    select_models,
)
from engine.confidence import ConfidenceBand, confidence_band, fuse_confidence
from engine.normalize import load_holdout_records
from engine.signals_numeric import score_numeric_signals
from engine.signals_semantic import reference_similarity, score_semantic_pair
from engine.tier1_deterministic import match_tier1
from engine.tier2_reasoning import reconcile_tier2
from eval.phase3_live import build_live_report


HOLDOUT_DIR = Path("data/holdout")


def _record(
    record_id: str,
    source: Source,
    *,
    amount: str = "100.00",
    txn_date: date = date(2026, 7, 1),
    reference: str | None = "pay_reference",
    description: str = "Customer A settlement",
    counterparty: str = "Customer A",
) -> CanonicalRecord:
    return CanonicalRecord(
        record_id=record_id,
        source=source,
        amount=Decimal(amount),
        txn_date=txn_date,
        reference=reference,
        description=description,
        counterparty=counterparty,
    )


class _FixedEncoder:
    semantic_backend = "fixed_test_encoder"

    def encode(self, sentences, *, normalize_embeddings=False):
        assert len(sentences) == 2
        return [[1.0, 0.0], [0.8, 0.6]]


def _offline_yes_adjudicator(left, right, signal_scores, *, budget):
    left_total, right_total, delta, sums_match = compute_group_sum_check(left, right)
    score_facts = ", ".join(
        f"{name}={value:.4f}" for name, value in sorted(signal_scores.items())
    )
    return AdjudicationResult(
        verdict=Verdict.YES,
        confidence=0.97,
        rationale=(
            f"Offline constrained-verdict fixture cites left="
            f"{[record.record_id for record in left]}, right="
            f"{[record.record_id for record in right]}, delta=₹{delta}, "
            f"signals: {score_facts}."
        ),
        answering_tier="fixture",
        answering_model="offline-structured-fixture",
        left_record_ids=[record.record_id for record in left],
        right_record_ids=[record.record_id for record in right],
        left_total=left_total,
        right_total=right_total,
        sum_delta=delta,
        sums_match=sums_match,
        sum_tolerance=Decimal("1.00"),
        signal_scores=dict(signal_scores),
        calls_used=budget.calls_used,
        tokens_used=budget.tokens_used,
    )


def _true_id(record_id: str, truth_ids: set[str]) -> str:
    without_source = record_id.split("_", 1)[1]
    matches = [
        true_id
        for true_id in truth_ids
        if without_source == true_id or without_source.startswith(f"{true_id}_")
    ]
    assert len(matches) == 1, f"{record_id} resolved to {matches}"
    return matches[0]


def test_numeric_signals_ground_fee_fx_and_group_arithmetic():
    ledger = _record("ledger_1", Source.LEDGER, amount="100.00")
    fee_bank = _record("bank_1", Source.BANK, amount="98.00")
    fee = score_numeric_signals(fee_bank, ledger)
    assert fee.fee_plausible
    assert fee.amount_classification == "inferred_fee"
    assert fee.amount_delta == pytest.approx(0.08)
    assert fee.grounded_details()["left_total"] == "98.00"

    fx_bank = _record("bank_2", Source.BANK, amount="100.03")
    fx = score_numeric_signals(fx_bank, ledger)
    assert fx.fx_rounding_plausible
    assert fx.amount_delta <= 0.05

    parts = [
        _record("bank_part_1", Source.BANK, amount="40.00"),
        _record("bank_part_2", Source.BANK, amount="60.00"),
    ]
    grouped = score_numeric_signals(parts, [ledger])
    assert grouped.sums_match_within_cent
    assert grouped.left_total == grouped.right_total == Decimal("100.00")


def test_partial_refund_signal_requires_every_gate_condition():
    ledger = _record(
        "ledger_refund",
        Source.LEDGER,
        amount="100.00",
        txn_date=date(2026, 7, 1),
        reference=" Pay Ref 123 ",
        counterparty="Customer A",
    )
    bank = _record(
        "bank_refund",
        Source.BANK,
        amount="70.00",
        txn_date=date(2026, 7, 3),
        reference="payref123",
        counterparty="Different name",
    )

    plausible = score_numeric_signals(bank, ledger)
    assert plausible.partial_refund_plausible is True
    assert plausible.refund_ratio == Decimal("0.70")
    assert plausible.fee_plausible is False
    assert plausible.grounded_details()["partial_refund_plausible"] is True
    assert plausible.grounded_details()["refund_ratio"] == "0.7"

    counterparty_match = score_numeric_signals(
        _record(
            "bank_counterparty",
            Source.BANK,
            amount="70.00",
            txn_date=date(2026, 7, 3),
            reference="different reference",
            counterparty="  CUSTOMER   A ",
        ),
        ledger,
    )
    assert counterparty_match.partial_refund_plausible is True

    unrelated = score_numeric_signals(
        _record(
            "bank_unrelated",
            Source.BANK,
            amount="70.00",
            txn_date=date(2026, 7, 3),
            reference="other",
            counterparty="Other party",
        ),
        ledger,
    )
    assert unrelated.partial_refund_plausible is False
    assert unrelated.refund_ratio is None

    late = score_numeric_signals(
        _record(
            "bank_late",
            Source.BANK,
            amount="70.00",
            txn_date=date(2026, 7, 6),
            reference="pay ref 123",
            counterparty="Other party",
        ),
        ledger,
    )
    assert late.partial_refund_plausible is False

    outside_ratio = score_numeric_signals(
        _record(
            "bank_small",
            Source.BANK,
            amount="59.99",
            txn_date=date(2026, 7, 3),
            reference="pay ref 123",
            counterparty="Other party",
        ),
        ledger,
    )
    assert outside_ratio.partial_refund_plausible is False

    standard_fee = score_numeric_signals(
        _record(
            "bank_fee",
            Source.BANK,
            amount="95.00",
            txn_date=date(2026, 7, 3),
            reference="pay ref 123",
            counterparty="Other party",
        ),
        ledger,
    )
    assert standard_fee.fee_plausible is True
    assert standard_fee.partial_refund_plausible is False


def test_semantic_signal_has_embedding_and_corrupt_reference_evidence():
    bank = _record("bank_1", Source.BANK, reference="pay_123456789")
    ledger = _record(
        "ledger_1",
        Source.LEDGER,
        reference="pay_1234567x9",
        description="Invoice - Customer A",
    )

    result = score_semantic_pair(bank, ledger, encoder=_FixedEncoder())

    assert result.embedding_similarity == pytest.approx(0.8)
    assert result.semantic_similarity == pytest.approx(0.8)
    assert result.reference_similarity == pytest.approx(11 / 12)
    assert result.backend == "fixed_test_encoder"
    assert result.model_name is None
    assert reference_similarity(None, ledger.reference) is None


def test_confidence_thresholds_and_no_verdict_veto():
    assert confidence_band(0.9) is ConfidenceBand.HIGH
    assert confidence_band(0.6) is ConfidenceBand.MEDIUM
    assert confidence_band(0.5999) is ConfidenceBand.LOW

    rejected = fuse_confidence(
        amount_delta=0,
        timing_delta=0,
        semantic_similarity=1,
        adjudicator_verdict="no",
        adjudicator_confidence=1,
    )
    assert rejected.band is ConfidenceBand.LOW
    assert rejected.route == "exception"


def test_adjudicator_model_fallback_group_sum_and_budget_guard():
    fast, reasoning = select_models(
        {"openai/gpt-oss-20b", "openai/gpt-oss-120b"},
        configured_fast="llama-3.1-8b-instant",
        configured_reasoning="openai/gpt-oss-120b",
    )
    assert fast == "openai/gpt-oss-20b"
    assert reasoning == "openai/gpt-oss-120b"

    bank = [_record("bank_1", Source.BANK, amount="40.00")]
    ledger = [
        _record("ledger_1", Source.LEDGER, amount="15.00"),
        _record("ledger_2", Source.LEDGER, amount="25.02"),
    ]
    totals = compute_group_sum_check(bank, ledger)
    assert totals == (
        Decimal("40.00"),
        Decimal("40.02"),
        Decimal("0.02"),
        True,
    )

    budget = LLMBudget(call_limit=1, token_limit=100)
    budget.reserve_call(100)
    with pytest.raises(BudgetExceededError, match="call budget exhausted"):
        budget.reserve_call(1)


def test_adjudicator_retries_validation_escalates_and_uses_strict_schema():
    class Response:
        status_code = 200
        headers = {}

        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": self.content}}],
                "usage": {"total_tokens": 20},
            }

    class Session:
        def __init__(self):
            self.responses = iter(
                [
                    Response("not valid json"),
                    Response(
                        json.dumps(
                            {
                                "verdict": "uncertain",
                                "confidence": 0.5,
                                "rationale": "Signals conflict.",
                            }
                        )
                    ),
                    Response(
                        json.dumps(
                            {
                                "verdict": "yes",
                                "confidence": 0.93,
                                "rationale": "Exact totals and references fit.",
                            }
                        )
                    ),
                ]
            )
            self.requests = []

        def post(self, url, **kwargs):
            self.requests.append((url, kwargs))
            return next(self.responses)

    session = Session()
    budget = LLMBudget(call_limit=5, token_limit=20_000)
    bank = [_record("bank_1", Source.BANK)]
    ledger = [_record("ledger_1", Source.LEDGER)]

    result = adjudicate(
        bank,
        ledger,
        {
            "amount_delta": 0.0,
            "timing_delta": 0.0,
            "semantic": 0.9,
            "fee_plausible": 0.0,
        },
        budget=budget,
        api_key="test-key-not-real",
        live_model_ids={"openai/gpt-oss-20b", "openai/gpt-oss-120b"},
        fast_model="openai/gpt-oss-20b",
        reasoning_model="openai/gpt-oss-120b",
        session=session,
        max_rate_limit_retries=0,
    )

    assert result.verdict is Verdict.YES
    assert result.answering_tier == "reasoning"
    assert result.answering_model == "openai/gpt-oss-120b"
    assert result.calls_used == budget.calls_used == 3
    assert result.tokens_used == budget.tokens_used == 60
    assert budget.validation_retries == 1
    assert budget.reasoning_escalations == 1
    assert budget.rate_limit_hits == 0
    assert "delta=₹0.00 against tolerance=₹1.00" in result.rationale
    assert "amount_delta=0.0000" in result.rationale
    assert [request[1]["json"]["model"] for request in session.requests] == [
        "openai/gpt-oss-20b",
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
    ]
    for _, request in session.requests:
        payload = request["json"]
        assert payload["response_format"]["type"] == "json_schema"
        assert payload["response_format"]["json_schema"]["strict"] is True
        assert payload["include_reasoning"] is False
        assert "Delta scores (amount_delta, timing_delta) use 0" in payload[
            "messages"
        ][0]["content"]


def test_adjudicator_names_partial_refund_finding_in_prompt():
    class Response:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "verdict": "yes",
                                    "confidence": 0.95,
                                    "rationale": (
                                        "Partial-refund signal and ratio support it."
                                    ),
                                }
                            )
                        }
                    }
                ],
                "usage": {"total_tokens": 20},
            }

    class Session:
        def __init__(self):
            self.request = None

        def post(self, url, **kwargs):
            self.request = kwargs
            return Response()

    session = Session()
    budget = LLMBudget(call_limit=2, token_limit=10_000)
    adjudicate(
        [_record("bank_refund", Source.BANK, amount="70.00")],
        [_record("ledger_refund", Source.LEDGER, amount="100.00")],
        {
            "amount_delta": 1.0,
            "timing_delta": 0.0,
            "partial_refund_plausible": 1.0,
            "refund_ratio": 0.70,
        },
        budget=budget,
        api_key="test-key-not-real",
        live_model_ids={"openai/gpt-oss-20b", "openai/gpt-oss-120b"},
        fast_model="openai/gpt-oss-20b",
        reasoning_model="openai/gpt-oss-120b",
        session=session,
        max_rate_limit_retries=0,
    )
    prompt = session.request["json"]["messages"][0]["content"]
    assert '"deterministic_partial_refund_finding"' in prompt
    assert '"partial_refund_plausible":true' in prompt
    assert '"refund_ratio":0.7' in prompt


def test_frozen_heldout_cumulative_gate_and_grounded_decisions():
    stored_hash = (HOLDOUT_DIR / "HOLDOUT_HASH.txt").read_text().strip()
    assert compute_holdout_hash(HOLDOUT_DIR) == stored_hash

    bank_records, ledger_records = load_holdout_records(HOLDOUT_DIR)
    tier1, unmatched_bank, unmatched_ledger = match_tier1(
        bank_records, ledger_records
    )
    budget = LLMBudget(call_limit=500, token_limit=200_000)
    tier2 = reconcile_tier2(
        unmatched_bank,
        unmatched_ledger,
        adjudicator=_offline_yes_adjudicator,
        budget=budget,
        semantic_encoder=_FixedEncoder(),
    )
    assert tier2.semantic_backend_counts == {"fixed_test_encoder": 77}

    truth = json.loads((HOLDOUT_DIR / "truth.json").read_text())
    truth_by_id = {item["true_id"]: item for item in truth}
    truth_ids = set(truth_by_id)
    resolvable_ids = {
        true_id
        for true_id, item in truth_by_id.items()
        if item["exception_type"] != ExceptionType.ORPHAN.value
    }

    true_positive_ids: set[str] = set()
    false_positive_decisions = []
    for decision in [*tier1, *tier2.decisions]:
        decision_true_ids = {
            _true_id(record_id, truth_ids) for record_id in decision.record_ids
        }
        if len(decision_true_ids) != 1:
            false_positive_decisions.append(decision)
        else:
            true_positive_ids.update(decision_true_ids)
        assert decision.rationale
        if decision.tier == 2:
            assert all(
                record_id in decision.rationale for record_id in decision.record_ids
            )
            assert "amount_delta=" in decision.rationale
            assert "timing_delta=" in decision.rationale
            assert "semantic_similarity=" in decision.rationale
            assert "fused_confidence=" in decision.rationale
        else:
            # Tier 1's Phase 2 contract grounds the exact input values through
            # its signal map and rationale; source-ID citation is the stricter
            # Tier 2 rule in PRD Section 5.
            assert decision.signal_scores["reference_exact"] == 1.0
            assert "delta=₹" in decision.rationale
            assert "bank_lag_days=" in decision.rationale

    for exception in tier2.exceptions:
        assert exception.reason_code in ExceptionType
        assert exception.reason_detail
        assert all(record_id in exception.reason_detail for record_id in exception.record_ids)

    tp = len(true_positive_ids & resolvable_ids)
    fp = len(false_positive_decisions)
    cumulative_match_rate = tp / len(truth)
    precision = tp / (tp + fp)
    recall = tp / len(resolvable_ids)
    source_records = {
        record.record_id: record for record in [*bank_records, *ledger_records]
    }
    false_positive_cost = sum(
        abs(source_records[record_id].amount)
        for decision in false_positive_decisions
        for record_id in decision.record_ids
        if source_records[record_id].source is Source.BANK
    )

    exception_codes = {
        _true_id(record_id, truth_ids): exception.reason_code
        for exception in tier2.exceptions
        for record_id in exception.record_ids
    }
    for true_id, reason_code in exception_codes.items():
        assert reason_code.value == truth_by_id[true_id]["exception_type"]

    print(
        f"Cumulative match rate: {cumulative_match_rate:.2%} "
        f"({tp}/{len(truth)})"
    )
    print(f"Precision: {precision:.2%}; recall: {recall:.2%}")
    print(f"False-positive cost estimate: ₹{false_positive_cost}")
    print(f"LLM calls used: {tier2.calls_used}/{budget.call_limit}")
    for decision in tier2.decisions[:3]:
        print(f"Example rationale: {decision.rationale}")

    assert cumulative_match_rate >= 0.90
    assert precision == 1.0
    assert recall == 1.0
    assert false_positive_cost == Decimal("0")
    assert tier2.calls_used == 0

    report = build_live_report(
        truth=truth,
        bank_records=bank_records,
        ledger_records=ledger_records,
        tier1_decisions=tier1,
        tier2=tier2,
        budget=budget,
        holdout_hash=stored_hash,
        elapsed_seconds=0.0,
    )
    assert report["resolved_only_transactions"] == 286
    assert report["exception_book_transactions"] == 14
    assert (
        report["resolved_only_transactions"]
        + report["exception_book_transactions"]
        + report["neither_matched_nor_exception"]
        == 300
    )
