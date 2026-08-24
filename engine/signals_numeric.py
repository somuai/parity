"""Deterministic amount and timing signals for Tier 2 candidate groups.

The public scorer accepts a record, or a sequence of records, on either
side.  Supporting sequences here keeps the arithmetic for one-to-many and
many-to-one candidates in Python rather than delegating it to an LLM.

Both returned scores are *delta* scores: zero is the strongest agreement
and one is a severe disagreement.  The accompanying details contain the
actual values needed to ground a later match rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Sequence, Union

from config.schema import CanonicalRecord, Source
from engine.tier1_deterministic import EXPECTED_BANK_LAGS_DAYS


CENT = Decimal("0.01")
DEFAULT_FX_TOLERANCE = Decimal("0.05")
DEFAULT_FEE_RATE_MIN = Decimal("0.005")
DEFAULT_FEE_RATE_MAX = Decimal("0.05")
DEFAULT_FEE_RATE_TARGET = Decimal("0.02")
DEFAULT_WILD_RELATIVE_DELTA = Decimal("0.10")
DEFAULT_TIMING_MAX_DEVIATION_DAYS = 14
DEFAULT_PARTIAL_REFUND_RATIO_MIN = Decimal("0.60")
DEFAULT_PARTIAL_REFUND_RATIO_MAX = Decimal("0.95")


RecordGroup = Union[CanonicalRecord, Sequence[CanonicalRecord]]


@dataclass(frozen=True)
class NumericSignalResult:
    """Pure numeric evidence for one candidate pair/group.

    Decimal fields deliberately remain Decimal until a caller explicitly
    serializes them.  That prevents float conversion from changing sum and
    tolerance decisions by a cent.
    """

    amount_delta: float
    timing_delta: float
    left_total: Decimal
    right_total: Decimal
    absolute_amount_delta: Decimal
    relative_amount_delta: Decimal
    amount_classification: str
    fee_rate: Decimal | None
    explicit_fee_total: Decimal
    fee_plausible: bool
    fx_rounding_plausible: bool
    partial_refund_plausible: bool
    refund_ratio: Decimal | None
    sums_match_within_cent: bool
    observed_lag_days: tuple[int, ...]
    expected_lag_days: tuple[int, ...]
    timing_deviation_days: tuple[int, ...]

    @property
    def signal_scores(self) -> dict[str, float]:
        """Values in the shape consumed by ``MatchDecision.signal_scores``."""

        return {
            "amount_delta": self.amount_delta,
            "timing_delta": self.timing_delta,
        }

    def grounded_details(self) -> dict[str, object]:
        """Return JSON-friendly evidence without losing decimal precision."""

        return {
            "left_total": str(self.left_total),
            "right_total": str(self.right_total),
            "absolute_amount_delta": str(self.absolute_amount_delta),
            "relative_amount_delta": str(self.relative_amount_delta),
            "amount_classification": self.amount_classification,
            "fee_rate": None if self.fee_rate is None else str(self.fee_rate),
            "explicit_fee_total": str(self.explicit_fee_total),
            "fee_plausible": self.fee_plausible,
            "fx_rounding_plausible": self.fx_rounding_plausible,
            "partial_refund_plausible": self.partial_refund_plausible,
            "refund_ratio": (
                None if self.refund_ratio is None else str(self.refund_ratio)
            ),
            "sums_match_within_cent": self.sums_match_within_cent,
            "observed_lag_days": list(self.observed_lag_days),
            "expected_lag_days": list(self.expected_lag_days),
            "timing_deviation_days": list(self.timing_deviation_days),
        }


def score_numeric_signals(
    left: RecordGroup,
    right: RecordGroup,
    *,
    expected_cycle_days: int = 2,
    fx_tolerance: Decimal = DEFAULT_FX_TOLERANCE,
    fee_rate_min: Decimal = DEFAULT_FEE_RATE_MIN,
    fee_rate_max: Decimal = DEFAULT_FEE_RATE_MAX,
    fee_rate_target: Decimal = DEFAULT_FEE_RATE_TARGET,
    wild_relative_delta: Decimal = DEFAULT_WILD_RELATIVE_DELTA,
    timing_grace_days: int = 1,
    timing_max_deviation_days: int = DEFAULT_TIMING_MAX_DEVIATION_DAYS,
    partial_refund_ratio_min: Decimal = DEFAULT_PARTIAL_REFUND_RATIO_MIN,
    partial_refund_ratio_max: Decimal = DEFAULT_PARTIAL_REFUND_RATIO_MAX,
) -> NumericSignalResult:
    """Score amount and settlement timing for two candidate record groups.

    ``expected_cycle_days`` should be 2 for a domestic settlement and 7 for
    an international settlement.  An observed bank lag anywhere from the
    source transaction date through the end of that cycle is on-time.  For
    a split bank settlement, successive rows are expected in successive
    cycle windows (T+2, T+4, ... or T+7, T+14, ...).

    A fee is only deemed plausible when it is explicitly reconciled by a
    ``fees_deducted`` value or its inferred rate falls inside the supplied
    reasonable fee band.  Unrelated amount deltas do not receive the fee
    treatment.  Deltas within ``fx_tolerance`` receive a near-zero score.
    """

    left_records = _as_tuple(left, "left")
    right_records = _as_tuple(right, "right")
    _validate_parameters(
        expected_cycle_days=expected_cycle_days,
        fx_tolerance=fx_tolerance,
        fee_rate_min=fee_rate_min,
        fee_rate_max=fee_rate_max,
        fee_rate_target=fee_rate_target,
        wild_relative_delta=wild_relative_delta,
        timing_grace_days=timing_grace_days,
        timing_max_deviation_days=timing_max_deviation_days,
        partial_refund_ratio_min=partial_refund_ratio_min,
        partial_refund_ratio_max=partial_refund_ratio_max,
    )

    left_total = sum((record.amount for record in left_records), Decimal("0"))
    right_total = sum((record.amount for record in right_records), Decimal("0"))
    absolute_delta = abs(left_total - right_total)
    largest_magnitude = max(abs(left_total), abs(right_total))
    relative_delta = (
        Decimal("0")
        if absolute_delta == 0
        else (absolute_delta / largest_magnitude if largest_magnitude else Decimal("1"))
    )
    explicit_fee_total = sum(
        (
            abs(record.fees_deducted)
            for record in (*left_records, *right_records)
            if record.fees_deducted is not None
        ),
        Decimal("0"),
    )

    fee_rate = (
        absolute_delta / largest_magnitude
        if absolute_delta and largest_magnitude
        else None
    )
    explicit_fee_match = bool(explicit_fee_total) and (
        abs(absolute_delta - explicit_fee_total) <= CENT
    )
    inferred_fee_match = bool(
        fee_rate is not None and fee_rate_min <= fee_rate <= fee_rate_max
    )
    fee_plausible = explicit_fee_match or inferred_fee_match
    fx_rounding_plausible = 0 < absolute_delta <= fx_tolerance

    amount_delta, amount_classification = _amount_score(
        absolute_delta=absolute_delta,
        relative_delta=relative_delta,
        fee_rate=fee_rate,
        explicit_fee_match=explicit_fee_match,
        inferred_fee_match=inferred_fee_match,
        fx_tolerance=fx_tolerance,
        fee_rate_min=fee_rate_min,
        fee_rate_max=fee_rate_max,
        fee_rate_target=fee_rate_target,
        wild_relative_delta=wild_relative_delta,
    )

    observed_lags, expected_lags, deviations = _timing_evidence(
        left_records,
        right_records,
        expected_cycle_days=expected_cycle_days,
        timing_grace_days=timing_grace_days,
    )
    mean_deviation = Decimal(sum(deviations)) / Decimal(len(deviations))
    timing_delta = _clamp01(
        Decimal(mean_deviation) / Decimal(timing_max_deviation_days)
    )
    refund_ratio = (
        min(abs(left_total), abs(right_total)) / largest_magnitude
        if largest_magnitude
        else None
    )
    partial_refund_plausible = _partial_refund_gate(
        left_records,
        right_records,
        refund_ratio=refund_ratio,
        fee_plausible=fee_plausible,
        ratio_min=partial_refund_ratio_min,
        ratio_max=partial_refund_ratio_max,
    )

    return NumericSignalResult(
        amount_delta=amount_delta,
        timing_delta=timing_delta,
        left_total=left_total,
        right_total=right_total,
        absolute_amount_delta=absolute_delta,
        relative_amount_delta=relative_delta,
        amount_classification=amount_classification,
        fee_rate=fee_rate,
        explicit_fee_total=explicit_fee_total,
        fee_plausible=fee_plausible,
        fx_rounding_plausible=fx_rounding_plausible,
        partial_refund_plausible=partial_refund_plausible,
        refund_ratio=refund_ratio if partial_refund_plausible else None,
        sums_match_within_cent=absolute_delta <= CENT,
        observed_lag_days=observed_lags,
        expected_lag_days=expected_lags,
        timing_deviation_days=deviations,
    )


def _partial_refund_gate(
    left: tuple[CanonicalRecord, ...],
    right: tuple[CanonicalRecord, ...],
    *,
    refund_ratio: Decimal | None,
    fee_plausible: bool,
    ratio_min: Decimal,
    ratio_max: Decimal,
) -> bool:
    """Require every source-visible partial-refund condition at once.

    Partial refunds are a one-to-one residual shape. Grouped candidates remain
    governed by their Python sum check and cannot enter through this gate.
    """

    if len(left) != 1 or len(right) != 1 or refund_ratio is None:
        return False
    left_record, right_record = left[0], right[0]
    same_reference = bool(
        _normalize_reference(left_record.reference)
        and _normalize_reference(left_record.reference)
        == _normalize_reference(right_record.reference)
    )
    same_counterparty = bool(
        _normalize_counterparty(left_record.counterparty)
        and _normalize_counterparty(left_record.counterparty)
        == _normalize_counterparty(right_record.counterparty)
    )
    bank_lag_days = _bank_lag_days(left_record, right_record)
    date_in_settlement_window = (
        bank_lag_days is not None and bank_lag_days in EXPECTED_BANK_LAGS_DAYS
    )
    return bool(
        (same_reference or same_counterparty)
        and date_in_settlement_window
        and ratio_min <= refund_ratio <= ratio_max
        and not fee_plausible
    )


def _normalize_reference(value: str | None) -> str:
    return "" if value is None else "".join(value.split()).casefold()


def _normalize_counterparty(value: str | None) -> str:
    return "" if value is None else " ".join(value.split()).casefold()


def _bank_lag_days(
    left: CanonicalRecord, right: CanonicalRecord
) -> int | None:
    if left.source == Source.BANK and right.source != Source.BANK:
        return (left.txn_date - right.txn_date).days
    if right.source == Source.BANK and left.source != Source.BANK:
        return (right.txn_date - left.txn_date).days
    return None


def _amount_score(
    *,
    absolute_delta: Decimal,
    relative_delta: Decimal,
    fee_rate: Decimal | None,
    explicit_fee_match: bool,
    inferred_fee_match: bool,
    fx_tolerance: Decimal,
    fee_rate_min: Decimal,
    fee_rate_max: Decimal,
    fee_rate_target: Decimal,
    wild_relative_delta: Decimal,
) -> tuple[float, str]:
    if absolute_delta == 0:
        return 0.0, "exact"

    if absolute_delta <= fx_tolerance:
        # Keep even the edge of the documented FX band near-identical.
        return _clamp01((absolute_delta / fx_tolerance) * Decimal("0.05")), "fx_rounding"

    if explicit_fee_match:
        return 0.03, "explicit_fee_reconciliation"

    if inferred_fee_match and fee_rate is not None:
        # A 2% fee is the synthetic generator's representative center.  Rates
        # elsewhere in the reasonable 0.5%-5% band stay plausible but score
        # slightly less strongly; this never blesses an arbitrary delta.
        span = max(fee_rate_target - fee_rate_min, fee_rate_max - fee_rate_target)
        target_distance = abs(fee_rate - fee_rate_target) / span
        return _clamp01(Decimal("0.08") + Decimal("0.12") * target_distance), "inferred_fee"

    return _clamp01(relative_delta / wild_relative_delta), "unexplained_delta"


def _timing_evidence(
    left: tuple[CanonicalRecord, ...],
    right: tuple[CanonicalRecord, ...],
    *,
    expected_cycle_days: int,
    timing_grace_days: int,
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    left_bank = tuple(record for record in left if record.source == Source.BANK)
    right_bank = tuple(record for record in right if record.source == Source.BANK)

    if left_bank and not right_bank:
        bank_records, origin_records = left_bank, right
    elif right_bank and not left_bank:
        bank_records, origin_records = right_bank, left
    else:
        # The usual path is bank vs. ledger.  For other source combinations,
        # use the earlier side as the origin while retaining deterministic,
        # order-independent absolute lag evidence.
        left_origin = min(record.txn_date for record in left)
        right_origin = min(record.txn_date for record in right)
        observed = (abs((left_origin - right_origin).days),)
        deviation = max(0, observed[0] - expected_cycle_days - timing_grace_days)
        return observed, (expected_cycle_days,), (deviation,)

    origin_date = min(record.txn_date for record in origin_records)
    bank_dates = sorted(record.txn_date for record in bank_records)

    if len(bank_dates) > 1 and len(origin_records) == 1:
        # One-to-many settlement parts are scheduled over successive cycles.
        expected = tuple(
            expected_cycle_days * index for index in range(1, len(bank_dates) + 1)
        )
        observed = tuple((bank_date - origin_date).days for bank_date in bank_dates)
        deviations = tuple(
            max(0, abs(actual - target) - timing_grace_days)
            for actual, target in zip(observed, expected)
        )
        return observed, expected, deviations

    observed = tuple((bank_date - origin_date).days for bank_date in bank_dates)
    expected = tuple(expected_cycle_days for _ in bank_dates)
    # The source schema's dates are transaction dates, while a bank date can
    # be any point through the settlement window.  Negative lags and lags
    # beyond the cycle are deviations; [0, cycle] is on-time.
    deviations = tuple(
        (
            max(0, -lag - timing_grace_days)
            if lag < 0
            else max(0, lag - expected_cycle_days - timing_grace_days)
        )
        for lag in observed
    )
    return observed, expected, deviations


def _as_tuple(records: RecordGroup, side: str) -> tuple[CanonicalRecord, ...]:
    if isinstance(records, CanonicalRecord):
        return (records,)
    result = tuple(records)
    if not result:
        raise ValueError(f"{side} candidate group must contain at least one record")
    if not all(isinstance(record, CanonicalRecord) for record in result):
        raise TypeError(f"{side} candidate group must contain CanonicalRecord values")
    return result


def _validate_parameters(
    *,
    expected_cycle_days: int,
    fx_tolerance: Decimal,
    fee_rate_min: Decimal,
    fee_rate_max: Decimal,
    fee_rate_target: Decimal,
    wild_relative_delta: Decimal,
    timing_grace_days: int,
    timing_max_deviation_days: int,
    partial_refund_ratio_min: Decimal,
    partial_refund_ratio_max: Decimal,
) -> None:
    if expected_cycle_days < 0:
        raise ValueError("expected_cycle_days must be non-negative")
    if fx_tolerance <= 0:
        raise ValueError("fx_tolerance must be positive")
    if not (Decimal("0") <= fee_rate_min <= fee_rate_target <= fee_rate_max):
        raise ValueError("fee rates must satisfy 0 <= min <= target <= max")
    if fee_rate_min == fee_rate_max:
        raise ValueError("fee rate range must not be empty")
    if wild_relative_delta <= 0:
        raise ValueError("wild_relative_delta must be positive")
    if timing_grace_days < 0:
        raise ValueError("timing_grace_days must be non-negative")
    if timing_max_deviation_days <= 0:
        raise ValueError("timing_max_deviation_days must be positive")
    if not (
        Decimal("0") < partial_refund_ratio_min
        <= partial_refund_ratio_max < Decimal("1")
    ):
        raise ValueError(
            "partial refund ratios must satisfy 0 < min <= max < 1"
        )


def _clamp01(value: Decimal) -> float:
    return float(min(Decimal("1"), max(Decimal("0"), value)))
