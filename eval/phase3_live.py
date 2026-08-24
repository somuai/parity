"""Fixture-free Phase 3 evaluation against the frozen held-out set.

Run with::

    python -m eval.phase3_live

Unlike ``tests/test_tier2.py``, this command requires the real
sentence-transformers model and live Groq access.  Ground truth is read only
after matching finishes and is used solely for metric calculation.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import time
from typing import Any, Sequence

from config.schema import CanonicalRecord, ExceptionType, MatchDecision, Source
from data.generators.freeze_holdout import compute_holdout_hash
from engine.adjudicator import LLMBudget
from engine.normalize import load_holdout_records
from engine.tier1_deterministic import match_tier1
from engine.tier2_reasoning import Tier2RunResult, reconcile_tier2


HOLDOUT_DIR = Path("data/holdout")


def true_id_for_record(record_id: str, truth_ids: set[str]) -> str:
    """Resolve generated source IDs to truth IDs for evaluation only."""

    without_source = record_id.split("_", 1)[1]
    matches = [
        true_id
        for true_id in truth_ids
        if without_source == true_id or without_source.startswith(f"{true_id}_")
    ]
    if len(matches) != 1:
        raise ValueError(f"{record_id} resolved to truth IDs {matches}")
    return matches[0]


def build_live_report(
    *,
    truth: list[dict[str, Any]],
    bank_records: Sequence[CanonicalRecord],
    ledger_records: Sequence[CanonicalRecord],
    tier1_decisions: Sequence[MatchDecision],
    tier2: Tier2RunResult,
    budget: LLMBudget,
    holdout_hash: str,
    elapsed_seconds: float,
) -> dict[str, Any]:
    """Compute transaction-level metrics without overlapping status buckets."""

    truth_by_id = {item["true_id"]: item for item in truth}
    truth_ids = set(truth_by_id)
    resolvable_ids = {
        true_id
        for true_id, item in truth_by_id.items()
        if item["exception_type"] != ExceptionType.ORPHAN.value
    }
    all_decisions = [*tier1_decisions, *tier2.decisions]
    correct_decisions: list[MatchDecision] = []
    false_positive_decisions: list[MatchDecision] = []
    matched_truth_ids: set[str] = set()
    for decision in all_decisions:
        decision_truth_ids = {
            true_id_for_record(record_id, truth_ids)
            for record_id in decision.record_ids
        }
        if len(decision_truth_ids) == 1:
            correct_decisions.append(decision)
            matched_truth_ids.update(decision_truth_ids)
        else:
            false_positive_decisions.append(decision)

    exception_truth_ids = {
        true_id_for_record(record_id, truth_ids)
        for exception in tier2.exceptions
        for record_id in exception.record_ids
    }
    source_records = {
        record.record_id: record for record in [*bank_records, *ledger_records]
    }
    false_positive_cost = sum(
        (
            abs(source_records[record_id].amount)
            for decision in false_positive_decisions
            for record_id in decision.record_ids
            if source_records[record_id].source is Source.BANK
        ),
        Decimal("0"),
    )
    true_positive_ids = matched_truth_ids & resolvable_ids
    false_positive_count = len(false_positive_decisions)
    precision_denominator = len(correct_decisions) + false_positive_count
    precision = (
        len(correct_decisions) / precision_denominator
        if precision_denominator
        else 0.0
    )
    recall = len(true_positive_ids) / len(resolvable_ids)
    match_rate = len(true_positive_ids) / len(truth)

    resolved_only = matched_truth_ids - exception_truth_ids
    neither = truth_ids - (matched_truth_ids | exception_truth_ids)
    examples = [decision.rationale for decision in tier2.decisions[:3]]
    exception_types = Counter(
        truth_by_id[true_id]["exception_type"] for true_id in exception_truth_ids
    )

    return {
        "run_kind": "fixture_free_live",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "holdout_hash": holdout_hash,
        "truth_transactions": len(truth),
        "resolvable_truth_transactions": len(resolvable_ids),
        "tier1_matched_truth_transactions": len(
            {
                true_id_for_record(record_id, truth_ids)
                for decision in tier1_decisions
                for record_id in decision.record_ids
            }
        ),
        "tier2_matched_truth_transactions": len(
            matched_truth_ids
            - {
                true_id_for_record(record_id, truth_ids)
                for decision in tier1_decisions
                for record_id in decision.record_ids
            }
        ),
        "matched_truth_transactions": len(matched_truth_ids),
        "correct_auto_matches": len(correct_decisions),
        "false_positive_decisions": false_positive_count,
        "match_rate": match_rate,
        "precision": precision,
        "recall": recall,
        "false_positive_cost_inr": str(false_positive_cost),
        "resolved_only_transactions": len(resolved_only),
        "exception_book_transactions": len(exception_truth_ids),
        "matched_and_exception_overlap": len(
            matched_truth_ids & exception_truth_ids
        ),
        "neither_matched_nor_exception": len(neither),
        "exception_truth_types": dict(sorted(exception_types.items())),
        "tier2_match_decisions": len(tier2.decisions),
        "tier2_exception_rows": len(tier2.exceptions),
        "semantic_backend_counts": tier2.semantic_backend_counts,
        "answering_tier_counts": tier2.answering_tier_counts,
        "answering_model_counts": tier2.answering_model_counts,
        "adjudication_failures": tier2.adjudication_failures,
        "llm_calls_used": budget.calls_used,
        "llm_call_budget": budget.call_limit,
        "llm_tokens_used": budget.tokens_used,
        "llm_token_budget": budget.token_limit,
        "rate_limit_hits": budget.rate_limit_hits,
        "rate_limit_retries": budget.rate_limit_retries,
        "validation_retries": budget.validation_retries,
        "reasoning_escalations": budget.reasoning_escalations,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "example_rationales": examples,
    }


def run_live_evaluation() -> dict[str, Any]:
    """Run Tier 1 + real Tier 2, then grade against untouched truth."""

    stored_hash = (HOLDOUT_DIR / "HOLDOUT_HASH.txt").read_text().strip()
    actual_hash = compute_holdout_hash(HOLDOUT_DIR)
    if actual_hash != stored_hash:
        raise RuntimeError(
            f"Frozen holdout hash mismatch: stored={stored_hash}, actual={actual_hash}"
        )

    bank_records, ledger_records = load_holdout_records(HOLDOUT_DIR)
    tier1, unmatched_bank, unmatched_ledger = match_tier1(
        bank_records, ledger_records
    )
    budget = LLMBudget.from_env()
    started = time.monotonic()
    tier2 = reconcile_tier2(
        unmatched_bank,
        unmatched_ledger,
        budget=budget,
        semantic_encoder=None,
        allow_lexical_fallback=False,
    )
    elapsed = time.monotonic() - started
    if tier2.semantic_backend_counts != {
        "sentence_transformers": sum(tier2.semantic_backend_counts.values())
    }:
        raise RuntimeError(
            "Live evaluation used a non-production semantic backend: "
            f"{tier2.semantic_backend_counts}"
        )

    truth = json.loads((HOLDOUT_DIR / "truth.json").read_text())
    return build_live_report(
        truth=truth,
        bank_records=bank_records,
        ledger_records=ledger_records,
        tier1_decisions=tier1,
        tier2=tier2,
        budget=budget,
        holdout_hash=actual_hash,
        elapsed_seconds=elapsed,
    )


def main() -> None:
    print(json.dumps(run_live_evaluation(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
