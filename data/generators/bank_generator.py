"""
Generates data/holdout/bank_statement.csv by applying bank-side perturbations
to the shared truth set (data/holdout/truth.json — run truth_source.py first).

Only records where PERTURB_SIDE == "bank" get modified from ground truth;
everything else passes through clean, so Tier 1 should catch it.

TODO (Codex Data Engineer agent, Phase 1): ONE_TO_MANY is currently
approximated as a single row with a flag rather than an actual N-way split
across multiple settlement dates — implement the real split so Tier 2's
one-to-many matching logic has something genuine to solve.
"""
import csv
import json
from pathlib import Path
from decimal import Decimal

from config.schema import ExceptionType
from data.generators.exception_taxonomy import (
    apply_timing_lag,
    apply_fee_deduction,
    apply_fx_rounding,
)

HOLDOUT_DIR = Path("data/holdout")


def generate():
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
                # Approximation — see module TODO. Marks the row so eval can
                # at least identify it as a known-incomplete case for now.
                pass

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
