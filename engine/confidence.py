"""Confidence fusion and routing for Tier 2 reconciliation decisions.

The inputs deliberately use match-oriented scores (one means strong evidence)
even though the numeric signal module exposes deltas (zero means identical).
Keeping that conversion at the orchestration boundary makes the weighted sum
auditable and prevents accidentally treating a large delta as good evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class ConfidenceBand(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class ConfidenceResult:
    score: float
    band: ConfidenceBand
    route: Literal["auto_accept", "accept_and_surface", "exception"]
    components: dict[str, float]


WEIGHTS = {
    "amount": 0.25,
    "timing": 0.15,
    "semantic": 0.25,
    "adjudicator": 0.35,
}


def _unit_interval(name: str, value: float) -> float:
    numeric = float(value)
    if not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1; got {value!r}")
    return numeric


def confidence_band(score: float) -> ConfidenceBand:
    """Apply the exact PRD Section 5 thresholds."""
    value = _unit_interval("confidence", score)
    if value >= 0.9:
        return ConfidenceBand.HIGH
    if value >= 0.6:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW


def fuse_confidence(
    *,
    amount_delta: float,
    timing_delta: float,
    semantic_similarity: float | None,
    semantic_reliability: float = 1.0,
    adjudicator_verdict: Literal["yes", "no", "uncertain"],
    adjudicator_confidence: float,
) -> ConfidenceResult:
    """Fuse independent signals into an auditable confidence score.

    A model confidence is never evidence by itself: a ``no`` verdict maps to
    zero adjudicator support and an ``uncertain`` verdict receives only half
    of its stated confidence.  Consequently, strong deterministic signals can
    surface an uncertain case for review but cannot turn a model rejection
    into a high-confidence automatic match.
    """
    amount = 1.0 - _unit_interval("amount_delta", amount_delta)
    timing = 1.0 - _unit_interval("timing_delta", timing_delta)
    reliability = _unit_interval("semantic_reliability", semantic_reliability)
    semantic = (
        0.0
        if semantic_similarity is None
        else _unit_interval("semantic_similarity", semantic_similarity) * reliability
    )
    model_confidence = _unit_interval(
        "adjudicator_confidence", adjudicator_confidence
    )

    if adjudicator_verdict == "yes":
        adjudicator = model_confidence
    elif adjudicator_verdict == "uncertain":
        adjudicator = model_confidence * 0.5
    elif adjudicator_verdict == "no":
        adjudicator = 0.0
    else:
        raise ValueError(f"Unsupported adjudicator verdict: {adjudicator_verdict!r}")

    components = {
        "amount": amount,
        "timing": timing,
        "semantic": semantic,
        "adjudicator": adjudicator,
        "semantic_reliability": reliability,
    }
    score = round(
        sum(components[name] * weight for name, weight in WEIGHTS.items()),
        6,
    )
    # A qualitative rejection is a veto, not merely a weak fourth vote.  This
    # preserves the PRD's "never guessed" safety posture even when amount,
    # timing, and semantic evidence happen to look superficially strong.
    if adjudicator_verdict == "no":
        score = min(score, 0.599999)
    band = confidence_band(score)
    route: Literal["auto_accept", "accept_and_surface", "exception"]
    if band is ConfidenceBand.HIGH:
        route = "auto_accept"
    elif band is ConfidenceBand.MEDIUM:
        route = "accept_and_surface"
    else:
        route = "exception"
    return ConfidenceResult(score, band, route, components)
