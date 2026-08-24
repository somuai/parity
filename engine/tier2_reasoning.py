"""Tier 2 residual reconciliation orchestration.

The production entry point accepts Tier 1's unmatched records directly.  It
never reads ``truth.json`` or any ground-truth-only field.  Candidate groups
are formed from source-visible reference, counterparty, and narration signals,
then pass through numeric scoring, semantic scoring, adjudication, and
confidence fusion in that order.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Sequence

from config.schema import CanonicalRecord, ExceptionRecord, ExceptionType, MatchDecision
from engine.adjudicator import (
    AdjudicationError,
    AdjudicationResult,
    LLMBudget,
    Verdict,
    adjudicate,
    fetch_live_model_ids,
)
from engine.confidence import ConfidenceResult, fuse_confidence
from engine.signals_numeric import NumericSignalResult, score_numeric_signals
from engine.signals_semantic import (
    SemanticSignalResult,
    lexical_semantic_similarity,
    normalize_reference,
    normalize_text,
    record_semantic_text,
    reference_similarity,
    score_semantic_pair,
)


Adjudicator = Callable[..., AdjudicationResult]


@dataclass(frozen=True)
class CandidateGroup:
    bank_records: tuple[CanonicalRecord, ...]
    ledger_records: tuple[CanonicalRecord, ...]

    @property
    def record_ids(self) -> list[str]:
        return [
            *(record.record_id for record in self.bank_records),
            *(record.record_id for record in self.ledger_records),
        ]


@dataclass(frozen=True)
class Tier2RunResult:
    decisions: list[MatchDecision]
    exceptions: list[ExceptionRecord]
    calls_used: int
    tokens_used: int
    semantic_backend_counts: dict[str, int]
    answering_tier_counts: dict[str, int]
    answering_model_counts: dict[str, int]
    adjudication_failures: int


def build_candidate_groups(
    unmatched_bank: Sequence[CanonicalRecord],
    unmatched_ledger: Sequence[CanonicalRecord],
) -> list[CandidateGroup]:
    """Build bipartite connected components from source-visible evidence."""

    bank = tuple(unmatched_bank)
    ledger = tuple(unmatched_ledger)
    total = len(bank) + len(ledger)
    parent = list(range(total))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for bank_index, bank_record in enumerate(bank):
        for ledger_index, ledger_record in enumerate(ledger):
            if _candidate_edge(bank_record, ledger_record):
                union(bank_index, len(bank) + ledger_index)

    components: dict[int, tuple[list[CanonicalRecord], list[CanonicalRecord]]] = {}
    for index, record in enumerate(bank):
        component = components.setdefault(find(index), ([], []))
        component[0].append(record)
    for index, record in enumerate(ledger, start=len(bank)):
        component = components.setdefault(find(index), ([], []))
        component[1].append(record)

    groups = [
        CandidateGroup(
            tuple(sorted(bank_records, key=lambda record: record.record_id)),
            tuple(sorted(ledger_records, key=lambda record: record.record_id)),
        )
        for bank_records, ledger_records in components.values()
    ]
    return sorted(groups, key=lambda group: group.record_ids[0])


def reconcile_tier2(
    unmatched_bank: Sequence[CanonicalRecord],
    unmatched_ledger: Sequence[CanonicalRecord],
    *,
    adjudicator: Adjudicator = adjudicate,
    budget: LLMBudget | None = None,
    semantic_encoder: object | None = None,
    allow_lexical_fallback: bool = True,
    expected_cycle_days: int = 2,
) -> Tier2RunResult:
    """Reconcile Tier 1 residuals and return grounded matches/exceptions.

    ``adjudicator`` and ``semantic_encoder`` are injectable so the frozen-set
    regression suite is deterministic and offline.  Production callers retain
    the defaults and therefore use Groq plus the configured embedding model.
    """

    active_budget = budget or LLMBudget.from_env()
    # Resolve the catalog once per run.  Fetching it inside every residual
    # adjudication would add dozens of unnecessary network requests.
    live_model_ids = fetch_live_model_ids() if adjudicator is adjudicate else None
    decisions: list[MatchDecision] = []
    exceptions: list[ExceptionRecord] = []
    semantic_backends: Counter[str] = Counter()
    answering_tiers: Counter[str] = Counter()
    answering_models: Counter[str] = Counter()
    adjudication_failures = 0

    for original_group in build_candidate_groups(unmatched_bank, unmatched_ledger):
        if not original_group.bank_records or not original_group.ledger_records:
            exceptions.append(_one_sided_exception(original_group))
            continue

        group, duplicate_exceptions = _separate_duplicate_rows(original_group)
        exceptions.extend(duplicate_exceptions)
        numeric = score_numeric_signals(
            group.bank_records,
            group.ledger_records,
            expected_cycle_days=expected_cycle_days,
        )
        semantic = _score_group_semantics(
            group,
            encoder=semantic_encoder,
            allow_lexical_fallback=allow_lexical_fallback,
        )
        semantic_backends[semantic.backend] += 1
        semantic_evidence = max(
            semantic.semantic_similarity,
            semantic.reference_similarity or 0.0,
        )
        signal_scores = {
            **numeric.signal_scores,
            **semantic.as_signal_scores(),
            "semantic_evidence": semantic_evidence,
            "relative_amount_delta": float(numeric.relative_amount_delta),
            "fee_rate": float(numeric.fee_rate or Decimal("0")),
            "fee_plausible": float(numeric.fee_plausible),
            "fx_rounding_plausible": float(numeric.fx_rounding_plausible),
            "partial_refund_plausible": float(
                numeric.partial_refund_plausible
            ),
            "refund_ratio": float(numeric.refund_ratio or Decimal("0")),
            "sums_match_within_cent": float(numeric.sums_match_within_cent),
        }

        try:
            adjudicator_kwargs = {"budget": active_budget}
            if live_model_ids is not None:
                adjudicator_kwargs["live_model_ids"] = live_model_ids
            adjudication = adjudicator(
                group.bank_records,
                group.ledger_records,
                signal_scores,
                **adjudicator_kwargs,
            )
        except AdjudicationError as exc:
            adjudication_failures += 1
            reason_code = _specific_reason_code(group, numeric, semantic)
            exceptions.append(
                ExceptionRecord(
                    record_ids=group.record_ids,
                    reason_code=reason_code,
                    reason_detail=(
                        f"{_grounded_signal_summary(group, numeric, semantic)}; "
                        f"adjudication unavailable ({type(exc).__name__}), so the "
                        "candidate was conservatively flagged instead of guessed."
                    ),
                )
            )
            continue

        answering_tiers[adjudication.answering_tier] += 1
        answering_models[adjudication.answering_model] += 1

        verdict = _verdict_value(adjudication.verdict)
        fusion = fuse_confidence(
            amount_delta=numeric.amount_delta,
            timing_delta=numeric.timing_delta,
            semantic_similarity=semantic_evidence,
            adjudicator_verdict=verdict,
            adjudicator_confidence=adjudication.confidence,
        )
        rationale = _decision_rationale(
            group, numeric, semantic, adjudication, fusion
        )
        if fusion.route == "exception":
            exceptions.append(
                ExceptionRecord(
                    record_ids=group.record_ids,
                    reason_code=_specific_reason_code(group, numeric, semantic),
                    reason_detail=rationale,
                )
            )
            continue

        decisions.append(
            MatchDecision(
                record_ids=group.record_ids,
                tier=2,
                confidence=fusion.score,
                rationale=rationale,
                signal_scores=signal_scores,
            )
        )

    return Tier2RunResult(
        decisions=decisions,
        exceptions=exceptions,
        calls_used=active_budget.calls_used,
        tokens_used=active_budget.tokens_used,
        semantic_backend_counts=dict(semantic_backends),
        answering_tier_counts=dict(answering_tiers),
        answering_model_counts=dict(answering_models),
        adjudication_failures=adjudication_failures,
    )


def _candidate_edge(bank: CanonicalRecord, ledger: CanonicalRecord) -> bool:
    bank_counterparty = normalize_text(bank.counterparty)
    ledger_counterparty = normalize_text(ledger.counterparty)
    ref_score = reference_similarity(bank.reference, ledger.reference)
    if ref_score is not None and ref_score >= 0.75:
        return True
    bank_reference = normalize_reference(bank.reference)
    ledger_reference = normalize_reference(ledger.reference)
    if (
        min(len(bank_reference), len(ledger_reference)) >= 8
        and (
            bank_reference.startswith(ledger_reference)
            or ledger_reference.startswith(bank_reference)
        )
    ):
        return True
    lexical_score = lexical_semantic_similarity(
        record_semantic_text(bank), record_semantic_text(ledger)
    )
    return bool(
        bank_counterparty
        and bank_counterparty == ledger_counterparty
        and lexical_score >= 0.58
    )


def _score_group_semantics(
    group: CandidateGroup,
    *,
    encoder: object | None,
    allow_lexical_fallback: bool,
) -> SemanticSignalResult:
    pair = max(
        (
            (bank, ledger)
            for bank in group.bank_records
            for ledger in group.ledger_records
        ),
        key=lambda records: (
            reference_similarity(records[0].reference, records[1].reference) or 0.0,
            normalize_text(records[0].counterparty)
            == normalize_text(records[1].counterparty),
        ),
    )
    return score_semantic_pair(
        pair[0],
        pair[1],
        encoder=encoder,
        allow_lexical_fallback=allow_lexical_fallback,
    )


def _separate_duplicate_rows(
    group: CandidateGroup,
) -> tuple[CandidateGroup, list[ExceptionRecord]]:
    if len(group.bank_records) != 1 or len(group.ledger_records) < 2:
        return group, []
    by_fingerprint: dict[tuple[object, ...], list[CanonicalRecord]] = {}
    for record in group.ledger_records:
        fingerprint = (
            record.reference,
            record.amount,
            record.txn_date,
            normalize_text(record.description),
            normalize_text(record.counterparty),
        )
        by_fingerprint.setdefault(fingerprint, []).append(record)
    if len(by_fingerprint) != 1:
        return group, []

    ordered = sorted(group.ledger_records, key=lambda record: record.record_id)
    primary, extras = ordered[0], ordered[1:]
    exceptions = [
        ExceptionRecord(
            record_ids=[record.record_id],
            reason_code=ExceptionType.DUPLICATE_ENTRY,
            reason_detail=(
                f"Ledger record {record.record_id} duplicates {primary.record_id}: "
                f"reference={record.reference!r}, amount=₹{record.amount}, "
                f"txn_date={record.txn_date.isoformat()}, "
                f"counterparty={record.counterparty!r}."
            ),
        )
        for record in extras
    ]
    return CandidateGroup(group.bank_records, (primary,)), exceptions


def _one_sided_exception(group: CandidateGroup) -> ExceptionRecord:
    records = group.bank_records or group.ledger_records
    side = "ledger" if group.bank_records else "bank"
    amount = sum((record.amount for record in records), Decimal("0"))
    facts = ", ".join(
        f"{record.record_id}(reference={record.reference!r}, amount=₹{record.amount}, "
        f"date={record.txn_date.isoformat()})"
        for record in records
    )
    return ExceptionRecord(
        record_ids=group.record_ids,
        reason_code=ExceptionType.ORPHAN,
        reason_detail=(
            f"No candidate exists on the {side} side for {facts}; "
            f"one-sided total=₹{amount}."
        ),
        estimated_amount_at_risk=amount,
    )


def _specific_reason_code(
    group: CandidateGroup,
    numeric: NumericSignalResult,
    semantic: SemanticSignalResult,
) -> ExceptionType:
    if len(group.bank_records) > 1:
        return ExceptionType.ONE_TO_MANY
    if len(group.ledger_records) > 1:
        return ExceptionType.MANY_TO_ONE
    if numeric.fee_plausible:
        return ExceptionType.FEE_DEDUCTION
    if numeric.fx_rounding_plausible:
        return ExceptionType.FX_ROUNDING
    if numeric.partial_refund_plausible:
        return ExceptionType.PARTIAL_REFUND
    if semantic.reference_similarity is None or semantic.reference_similarity < 1.0:
        return ExceptionType.MISSING_REFERENCE
    return ExceptionType.ORPHAN


def _verdict_value(verdict: Verdict | str) -> str:
    return verdict.value if isinstance(verdict, Verdict) else str(verdict)


def _grounded_signal_summary(
    group: CandidateGroup,
    numeric: NumericSignalResult,
    semantic: SemanticSignalResult,
) -> str:
    return (
        f"records={group.record_ids}; totals=₹{numeric.left_total}/₹{numeric.right_total}; "
        f"absolute_amount_delta=₹{numeric.absolute_amount_delta}; "
        f"amount_delta={numeric.amount_delta:.4f} "
        f"({numeric.amount_classification}); timing_delta={numeric.timing_delta:.4f} "
        f"with observed_lag_days={list(numeric.observed_lag_days)} and "
        f"expected_lag_days={list(numeric.expected_lag_days)}; "
        f"semantic_similarity={semantic.semantic_similarity:.4f}; "
        f"reference_similarity={semantic.reference_similarity}; "
        f"partial_refund_plausible={numeric.partial_refund_plausible}; "
        f"refund_ratio={numeric.refund_ratio}; "
        f"semantic_backend={semantic.backend}"
    )


def _decision_rationale(
    group: CandidateGroup,
    numeric: NumericSignalResult,
    semantic: SemanticSignalResult,
    adjudication: AdjudicationResult,
    fusion: ConfidenceResult,
) -> str:
    return (
        f"{_grounded_signal_summary(group, numeric, semantic)}; "
        f"adjudicator={adjudication.answering_tier}/{adjudication.answering_model}, "
        f"verdict={_verdict_value(adjudication.verdict)}, "
        f"adjudicator_confidence={adjudication.confidence:.4f}; "
        f"fused_confidence={fusion.score:.4f}, band={fusion.band.value}, "
        f"route={fusion.route}. {adjudication.rationale}"
    )


__all__ = [
    "CandidateGroup",
    "Tier2RunResult",
    "build_candidate_groups",
    "reconcile_tier2",
]
