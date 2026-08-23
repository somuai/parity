"""
Shared exception-injection logic. Both bank_generator.py and
ledger_generator.py import from here so the taxonomy stays consistent and
each exception type has a known, controllable frequency in the held-out set.

This is what makes the held-out precision/recall claim honest: we know
exactly which records were perturbed and how, so grading against them isn't
guesswork.
"""
import random
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from config.schema import ExceptionType

# Target distribution across a 300-record held-out set. Tune counts here,
# not ad hoc in the generator scripts, so the taxonomy coverage checklist
# (Phase 1 exit gate) has one source of truth.
TARGET_DISTRIBUTION: dict[ExceptionType, int] = {
    ExceptionType.NONE: 180,             # clean, Tier-1 should catch these
    ExceptionType.TIMING_LAG: 30,
    ExceptionType.FEE_DEDUCTION: 25,
    ExceptionType.PARTIAL_REFUND: 15,
    ExceptionType.DUPLICATE_ENTRY: 10,
    ExceptionType.MISSING_REFERENCE: 15,
    ExceptionType.ONE_TO_MANY: 8,
    ExceptionType.MANY_TO_ONE: 7,
    ExceptionType.FX_ROUNDING: 6,
    ExceptionType.ORPHAN: 4,              # true unresolvable exceptions
}
assert sum(TARGET_DISTRIBUTION.values()) == 300


def settlement_cycle_offset(is_international: bool = False) -> int:
    """Real Razorpay settlement cycle: T+2 domestic, T+7 international."""
    return 7 if is_international else 2


def apply_timing_lag(txn_date: date, is_international: bool = False) -> date:
    base = settlement_cycle_offset(is_international)
    jitter = random.choice([-1, 0, 0, 1, 2])  # occasional off-cycle settlement
    return txn_date + timedelta(days=base + jitter)


def apply_fee_deduction(gross: Decimal, fee_pct: Decimal = Decimal("0.02")) -> tuple[Decimal, Decimal]:
    """Returns (net_amount, fee_amount). Razorpay's own fee schedule varies by
    instrument; 2% is a representative placeholder for synthetic generation."""
    fee = (gross * fee_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return gross - fee, fee


def apply_fx_rounding(amount: Decimal) -> Decimal:
    """Small non-deterministic rounding drift to simulate FX conversion noise."""
    drift = Decimal(random.choice(["-0.03", "-0.01", "0.01", "0.02", "0.04"]))
    return (amount + drift).quantize(Decimal("0.01"))


def corrupt_reference(ref: str) -> str:
    """Simulate a typo'd or truncated reference ID."""
    if len(ref) < 4:
        return ref
    i = random.randint(0, len(ref) - 1)
    return ref[:i] + random.choice("abcdefghij0123456789") + ref[i + 1:]
