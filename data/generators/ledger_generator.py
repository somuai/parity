"""
Generates data/holdout/internal_ledger.csv — the mirror of bank_generator.py,
applying ledger-side perturbations to the same shared truth set.

TODO (Codex Data Engineer agent, Phase 1): MANY_TO_ONE is approximated the
same way ONE_TO_MANY is on the bank side — implement the real N-invoices-to-
one-settlement merge so Tier 2 has a genuine grouping problem to solve.
"""
import csv
import json
from pathlib import Path
from decimal import Decimal

from config.schema import ExceptionType
from data.generators.exception_taxonomy import corrupt_reference

HOLDOUT_DIR = Path("data/holdout")


def generate():
    with open(HOLDOUT_DIR / "truth.json") as f:
        truth = json.load(f)

    rows = []
    for t in truth:
        exc = ExceptionType(t["exception_type"])
        if exc == ExceptionType.ORPHAN and t["perturb_side"] == "ledger":
            continue

        amount = Decimal(t["amount"])
        reference = t["reference"]
        emit_duplicate = False

        if t["perturb_side"] == "ledger":
            if exc == ExceptionType.MISSING_REFERENCE:
                reference = corrupt_reference(reference)
            elif exc == ExceptionType.PARTIAL_REFUND:
                amount = (amount * Decimal("0.7")).quantize(Decimal("0.01"))  # ledger shows pre-refund amount
            elif exc == ExceptionType.DUPLICATE_ENTRY:
                emit_duplicate = True
            elif exc == ExceptionType.MANY_TO_ONE:
                # Approximation — see module TODO.
                pass

        row = {
            "record_id": f"ledger_{t['true_id']}",
            "reference": reference,
            "amount": str(amount),
            "txn_date": t["txn_date"],
            "description": f"Invoice - {t['counterparty']}",
            "counterparty": t["counterparty"],
        }
        rows.append(row)
        if emit_duplicate:
            rows.append(dict(row, record_id=f"ledger_{t['true_id']}_dup"))

    with open(HOLDOUT_DIR / "internal_ledger.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["record_id", "reference", "amount", "txn_date", "description", "counterparty"])
        writer.writeheader()
        writer.writerows(rows)

    return rows


if __name__ == "__main__":
    rows = generate()
    print(f"Generated {len(rows)} ledger rows -> {HOLDOUT_DIR/'internal_ledger.csv'}")
