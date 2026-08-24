"""Load bank and ledger CSV rows into the canonical record schema."""
from __future__ import annotations

import csv
from pathlib import Path

from pydantic import ValidationError

from config.schema import CanonicalRecord, Source

HOLDOUT_DIR = Path("data/holdout")


def load_records(path: Path, source: Source) -> list[CanonicalRecord]:
    """Normalize one source CSV, failing with the source row on bad input."""
    records: list[CanonicalRecord] = []
    try:
        handle = path.open(newline="")
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Missing {source.value} input file: {path}") from exc

    with handle:
        for row_number, row in enumerate(csv.DictReader(handle), start=2):
            try:
                records.append(
                    CanonicalRecord(
                        record_id=row["record_id"],
                        source=source,
                        amount=row["amount"],
                        txn_date=row["txn_date"],
                        reference=row.get("reference") or None,
                        description=row.get("description", ""),
                        counterparty=row.get("counterparty") or None,
                        fees_deducted=row.get("fees_deducted") or None,
                    )
                )
            except (KeyError, ValidationError) as exc:
                raise ValueError(
                    f"Invalid {source.value} row {row_number} in {path}: {exc}"
                ) from exc
    return records


def load_holdout_records(
    holdout_dir: Path | None = None,
) -> tuple[list[CanonicalRecord], list[CanonicalRecord]]:
    """Load the frozen bank and ledger inputs without mutating them."""
    root = holdout_dir or HOLDOUT_DIR
    bank_records = load_records(root / "bank_statement.csv", Source.BANK)
    ledger_records = load_records(root / "internal_ledger.csv", Source.LEDGER)
    return bank_records, ledger_records
