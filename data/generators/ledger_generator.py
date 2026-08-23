"""
Generates data/holdout/internal_ledger.csv — the mirror of bank_generator.py,
applying ledger-side perturbations to the same shared truth set.
"""
import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from config.schema import ExceptionType
from data.generators.exception_taxonomy import corrupt_reference

HOLDOUT_DIR = Path("data/holdout")
CENT = Decimal("0.01")


def _many_to_one_rows(truth_item: dict, amount: Decimal) -> list[dict]:
    """Split one settlement truth item into deterministic ledger invoices."""
    child_count = 2 + (hashlib.sha256(truth_item["true_id"].encode()).digest()[0] % 2)
    total_cents = int(amount / CENT)
    if amount <= 0 or amount != amount.quantize(CENT) or total_cents < child_count:
        raise ValueError(
            f"MANY_TO_ONE amount for {truth_item['true_id']} must be a positive, "
            f"cent-exact value of at least {child_count} cents; got {amount}"
        )

    base_cents, extra_cents = divmod(total_cents, child_count)
    rows = []
    for child_index in range(child_count):
        child_cents = base_cents + (1 if child_index < extra_cents else 0)
        rows.append({
            "record_id": f"ledger_{truth_item['true_id']}_invoice_{child_index + 1:02d}",
            "reference": f"{truth_item['reference']}_invoice_{child_index + 1:02d}",
            "amount": str(Decimal(child_cents) * CENT),
            "txn_date": truth_item["txn_date"],
            "description": (
                f"Invoice {child_index + 1}/{child_count} - "
                f"{truth_item['counterparty']}"
            ),
            "counterparty": truth_item["counterparty"],
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
                rows.extend(_many_to_one_rows(t, amount))
                continue

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
