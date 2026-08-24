"""
Canonical record schema — every source (Razorpay settlement, bank statement,
internal ledger) gets normalized into this shape before matching starts.

Owned by: Data Engineer agent (Phase 1)
Consumed by: Tier 1 + Tier 2 matchers (Phase 2, 3)
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class Source(str, Enum):
    RAZORPAY = "razorpay"
    BANK = "bank"
    LEDGER = "ledger"


class ExceptionType(str, Enum):
    """Injected into synthetic bank/ledger generators (Phase 1).
    Razorpay-side noise is whatever the real test-mode API actually returns —
    not injected, just handled.
    """
    NONE = "none"                      # clean, should Tier-1 match
    TIMING_LAG = "timing_lag"          # T+2 / T+7 settlement cycle offset
    FEE_DEDUCTION = "fee_deduction"    # net != gross
    PARTIAL_REFUND = "partial_refund"
    DUPLICATE_ENTRY = "duplicate_entry"
    MISSING_REFERENCE = "missing_reference"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    FX_ROUNDING = "fx_rounding"
    ORPHAN = "orphan"                  # true exception — no match exists anywhere


class CanonicalRecord(BaseModel):
    record_id: str = Field(..., description="Source-prefixed, e.g. bank_00042")
    source: Source
    amount: Decimal = Field(..., description="Normalized to INR, signed")
    txn_date: date
    reference: Optional[str] = Field(None, description="Payment ID / UTR / invoice no.")
    description: str = Field("", description="Free-text narration — semantic signal input")
    counterparty: Optional[str] = None
    fees_deducted: Optional[Decimal] = Field(None, description="Settlement/bank rows only")

    # Ground-truth only — present in the held-out set, NEVER available to the
    # matching engine at inference time. Used only by the eval harness.
    _ground_truth_match_id: Optional[str] = None
    _ground_truth_exception_type: Optional[ExceptionType] = None

    @field_validator("record_id")
    @classmethod
    def _nonempty_record_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("record_id must not be blank")
        return normalized

    @field_validator("reference", "counterparty", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        return normalized or None


class MatchDecision(BaseModel):
    """Output of Tier 1 or Tier 2 for one candidate pair/group."""
    record_ids: list[str]
    tier: int                          # 1 or 2
    confidence: float                  # 0.0-1.0, see engine/confidence.py bands
    rationale: str                     # required — no ungrounded decisions
    signal_scores: dict[str, float] = Field(default_factory=dict)  # amount/timing/semantic


class ExceptionRecord(BaseModel):
    """One entry in the exception book — never a generic catch-all."""
    record_ids: list[str]
    reason_code: ExceptionType
    reason_detail: str                 # human-readable, specific
    estimated_amount_at_risk: Optional[Decimal] = None  # only set if this is real leakage,
                                                          # not just a timing/formatting gap
    tier: int = 2
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    signal_scores: dict[str, float] = Field(default_factory=dict)
    semantic_backend: Optional[str] = None
    adjudicator_tier: Optional[str] = None
    adjudicator_model: Optional[str] = None
