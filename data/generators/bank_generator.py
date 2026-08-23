"""
Generates data/holdout/bank_statement.csv by applying bank-side perturbations
to the shared truth set (data/holdout/truth.json — run truth_source.py first).

Only records where PERTURB_SIDE == "bank" get modified from ground truth;
everything else passes through clean, so Tier 1 should catch it.
"""
import csv
import json
from datetime import date, timedelta
from pathlib import Path
from decimal import Decimal

from config.schema import ExceptionType
from data.generators.exception_taxonomy import (
    apply_timing_lag,
    apply_fee_deduction,
    apply_fx_rounding,
    settlement_cycle_offset,
)

HOLDOUT_DIR = Path("data/holdout")
CENT = Decimal("0.01")


def _split_one_to_many(transaction: dict) -> list[dict]:
    """Create deterministic, cent-exact settlement parts for one invoice."""
    true_id = transaction["true_id"]
    part_count = 2 + (sum(true_id.encode("utf-8")) % 2)
    amount = Decimal(transaction["amount"])

    if amount != amount.quantize(CENT):
        raise ValueError(
            f"ONE_TO_MANY amount for {true_id} is not cent-exact: {amount}"
        )

    total_cents = int(amount / CENT)
    if total_cents < part_count:
        raise ValueError(
            f"ONE_TO_MANY amount for {true_id} has {total_cents} cents, "
            f"too little for {part_count} positive parts"
        )

    cents_per_part, remainder = divmod(total_cents, part_count)
    origin_date = date.fromisoformat(transaction["txn_date"])
    cycle_days = settlement_cycle_offset(transaction["is_international"])
    rows = []

    for part_index in range(1, part_count + 1):
        part_cents = cents_per_part + (1 if part_index <= remainder else 0)
        part_amount = (Decimal(part_cents) * CENT).quantize(CENT)
        settlement_date = origin_date + timedelta(days=cycle_days * part_index)
        rows.append({
            "record_id": f"bank_{true_id}_part_{part_index}",
            "reference": transaction["reference"],
            "amount": str(part_amount),
            "txn_date": settlement_date.isoformat(),
            "description": (
                f"{transaction['counterparty']} settlement "
                f"part {part_index}/{part_count}"
            ),
            "counterparty": transaction["counterparty"],
        })

    return rows


def generate():
    hash_path = HOLDOUT_DIR / "HOLDOUT_HASH.txt"
    if hash_path.exists():
        raise RuntimeError(
            f"Refusing to regenerate frozen holdout: {hash_path} already exists"
        )

    with open(HOLDOUT_DIR / "truth.json") as f:
        truth = json.load(f)

    rows = []
    for t in truth:
        exc = ExceptionType(t["exception_type"])
        if exc == ExceptionType.ORPHAN and t["perturb_side"] == "bank":
            continue  # orphan on the bank side means it simply doesn't appear here

        amount = Decimal(t["amount"])
        txn_date = t["txn_date"]
        reference = t["reference"]

        if t["perturb_side"] == "bank":
            if exc == ExceptionType.TIMING_LAG:
                from datetime import date as _date
                txn_date = apply_timing_lag(_date.fromisoformat(txn_date), t["is_international"]).isoformat()
            elif exc == ExceptionType.FEE_DEDUCTION:
                amount, _fee = apply_fee_deduction(amount)
            elif exc == ExceptionType.FX_ROUNDING:
                amount = apply_fx_rounding(amount)
            elif exc == ExceptionType.ONE_TO_MANY:
                rows.extend(_split_one_to_many(t))
                continue

        rows.append({
            "record_id": f"bank_{t['true_id']}",
            "reference": reference,
            "amount": str(amount),
            "txn_date": txn_date,
            "description": f"{t['counterparty']} settlement",
            "counterparty": t["counterparty"],
        })

    with open(HOLDOUT_DIR / "bank_statement.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["record_id", "reference", "amount", "txn_date", "description", "counterparty"])
        writer.writeheader()
        writer.writerows(rows)

    return rows


if __name__ == "__main__":
    rows = generate()
    print(f"Generated {len(rows)} bank statement rows -> {HOLDOUT_DIR/'bank_statement.csv'}")
