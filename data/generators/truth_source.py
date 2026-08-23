"""
Generates the single source of truth that bank_generator.py and
ledger_generator.py both perturb independently. This is what makes the
exceptions realistic mismatches between two views of the same event,
rather than two unrelated random datasets.

Scope decision (documented, not hidden): the held-out, gradable eval set is
a two-source problem — bank statement vs. internal ledger, both synthetic,
both perturbed from this shared truth. The Razorpay leg is kept as real,
un-labeled, test-mode data used only for the live demo batch (Section 4 of
the PRD) — it's the "real signal" leg, not part of the graded held-out
claim, since we can't control or label real API output.

Each true transaction is pre-assigned an ExceptionType describing what will
go wrong *between bank and ledger* for that record, and which side gets
perturbed. bank_generator.py / ledger_generator.py read PERTURB_SIDE to
decide who applies the noise.
"""
import json
import random
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from config.schema import ExceptionType
from data.generators.exception_taxonomy import TARGET_DISTRIBUTION

OUT_DIR = Path("data/holdout")
random.seed(42)

# Which side (bank or ledger) gets perturbed for each exception type.
# This is a modeling decision, not arbitrary: fees are deducted before the
# bank sees the money (so FEE_DEDUCTION perturbs bank), but a manually
# entered ledger is where typos and missed entries usually happen (so
# MISSING_REFERENCE and duplicate manual entries perturb ledger).
PERTURB_SIDE: dict[ExceptionType, str] = {
    ExceptionType.NONE: "neither",
    ExceptionType.TIMING_LAG: "bank",           # settlement cycle delay hits bank timing
    ExceptionType.FEE_DEDUCTION: "bank",        # bank sees net, ledger recorded gross
    ExceptionType.PARTIAL_REFUND: "ledger",     # ledger not yet updated for partial refund
    ExceptionType.DUPLICATE_ENTRY: "ledger",    # manual double entry
    ExceptionType.MISSING_REFERENCE: "ledger",  # manual entry, typo'd reference
    ExceptionType.ONE_TO_MANY: "bank",          # one ledger invoice, split settlements
    ExceptionType.MANY_TO_ONE: "ledger",        # multiple invoices, one netted settlement
    ExceptionType.FX_ROUNDING: "bank",          # conversion happens at bank/gateway level
    ExceptionType.ORPHAN: "bank",               # exists on one side only, by definition
}


def generate_truth(n: int = 300) -> list[dict]:
    assert n == sum(TARGET_DISTRIBUTION.values()), "n must match exception_taxonomy distribution"

    plan: list[ExceptionType] = []
    for exc_type, count in TARGET_DISTRIBUTION.items():
        plan.extend([exc_type] * count)
    random.shuffle(plan)

    truth = []
    for idx, exc_type in enumerate(plan):
        txn_date = date(2026, 7, 1) + timedelta(days=random.randint(0, 45))
        truth.append({
            "true_id": f"txn_{idx:04d}",
            "reference": f"pay_{uuid.uuid4().hex[:14]}",
            "amount": str(Decimal(random.randint(500, 250000)) / 100),
            "txn_date": txn_date.isoformat(),
            "counterparty": random.choice(["Customer", "Vendor", "Subscriber"]) + f"_{idx}",
            "is_international": random.random() < 0.1,
            "exception_type": exc_type.value,
            "perturb_side": PERTURB_SIDE[exc_type],
        })

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "truth.json", "w") as f:
        json.dump(truth, f, indent=2)

    return truth


if __name__ == "__main__":
    truth = generate_truth()
    print(f"Generated {len(truth)} ground-truth transactions -> {OUT_DIR/'truth.json'}")
    from collections import Counter
    print("Exception distribution:", Counter(t["exception_type"] for t in truth))
