import csv
import json
from pathlib import Path

import pytest

from config.schema import ExceptionType
from data.generators import validate_coverage


SMALL_DISTRIBUTION = {
    ExceptionType.NONE: 1,
    ExceptionType.ONE_TO_MANY: 1,
    ExceptionType.MANY_TO_ONE: 1,
    ExceptionType.ORPHAN: 1,
}


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "record_id",
                "reference",
                "amount",
                "txn_date",
                "description",
                "counterparty",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def _source_row(record_id: str, amount: str) -> dict[str, str]:
    return {
        "record_id": record_id,
        "reference": f"ref_{record_id}",
        "amount": amount,
        "txn_date": "2026-07-01",
        "description": record_id,
        "counterparty": "Customer",
    }


def _valid_small_holdout(tmp_path: Path) -> Path:
    root = tmp_path / "holdout"
    root.mkdir()
    truth = [
        {"true_id": "txn_0001", "group_id": None, "amount": "1.00", "exception_type": "none"},
        {"true_id": "txn_0002", "group_id": "group_txn_0002", "amount": "10.00", "exception_type": "one_to_many"},
        {"true_id": "txn_0003", "group_id": "group_txn_0003", "amount": "9.00", "exception_type": "many_to_one"},
        {"true_id": "txn_0004", "group_id": None, "amount": "4.00", "exception_type": "orphan"},
    ]
    (root / "truth.json").write_text(json.dumps(truth))
    _write_csv(
        root / "bank_statement.csv",
        [
            _source_row("bank_txn_0001", "1.00"),
            _source_row("bank_txn_0002_part_1", "4.00"),
            _source_row("bank_txn_0002_part_2", "6.00"),
            _source_row("bank_txn_0003", "9.00"),
        ],
    )
    _write_csv(
        root / "internal_ledger.csv",
        [
            _source_row("ledger_txn_0001", "1.00"),
            _source_row("ledger_txn_0002", "10.00"),
            _source_row("ledger_txn_0003_invoice_01", "4.00"),
            _source_row("ledger_txn_0003_invoice_02", "5.00"),
            _source_row("ledger_txn_0004", "4.00"),
        ],
    )
    return root


def test_validate_coverage_accepts_valid_taxonomy_and_groups(tmp_path, monkeypatch):
    root = _valid_small_holdout(tmp_path)
    monkeypatch.setattr(validate_coverage, "TARGET_DISTRIBUTION", SMALL_DISTRIBUTION)

    assert validate_coverage.validate_coverage(root) == SMALL_DISTRIBUTION


def test_validate_coverage_reports_specific_count_mismatch(tmp_path, monkeypatch):
    root = _valid_small_holdout(tmp_path)
    expected = dict(SMALL_DISTRIBUTION)
    expected[ExceptionType.NONE] = 2
    monkeypatch.setattr(validate_coverage, "TARGET_DISTRIBUTION", expected)

    with pytest.raises(
        validate_coverage.CoverageValidationError,
        match=r"Count mismatch for none: expected 2, actual 1",
    ):
        validate_coverage.validate_coverage(root)


def test_validate_coverage_rejects_invalid_group_sum(tmp_path, monkeypatch):
    root = _valid_small_holdout(tmp_path)
    monkeypatch.setattr(validate_coverage, "TARGET_DISTRIBUTION", SMALL_DISTRIBUTION)
    ledger_path = root / "internal_ledger.csv"
    rows = list(csv.DictReader(ledger_path.open(newline="")))
    rows[3]["amount"] = "4.99"
    _write_csv(ledger_path, rows)

    with pytest.raises(
        validate_coverage.CoverageValidationError,
        match=r"Group group_txn_0003 amount mismatch",
    ):
        validate_coverage.validate_coverage(root)


def test_validate_coverage_rejects_record_missing_from_both_sides(tmp_path, monkeypatch):
    root = _valid_small_holdout(tmp_path)
    monkeypatch.setattr(validate_coverage, "TARGET_DISTRIBUTION", SMALL_DISTRIBUTION)
    ledger_path = root / "internal_ledger.csv"
    rows = [
        row
        for row in csv.DictReader(ledger_path.open(newline=""))
        if row["record_id"] != "ledger_txn_0004"
    ]
    _write_csv(ledger_path, rows)

    with pytest.raises(
        validate_coverage.CoverageValidationError,
        match=r"Truth record txn_0004 is missing from both bank and ledger",
    ):
        validate_coverage.validate_coverage(root)
