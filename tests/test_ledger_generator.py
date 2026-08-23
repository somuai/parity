import csv
import json
from decimal import Decimal

import pytest

from data.generators import ledger_generator


def _truth_item(true_id: str, amount: str, exception_type: str = "many_to_one") -> dict:
    return {
        "true_id": true_id,
        "group_id": f"group_{true_id}" if exception_type == "many_to_one" else None,
        "reference": f"pay_{true_id}",
        "amount": amount,
        "txn_date": "2026-07-15",
        "counterparty": "Customer_1",
        "is_international": False,
        "exception_type": exception_type,
        "perturb_side": "ledger" if exception_type == "many_to_one" else "neither",
    }


def _write_truth(holdout_dir, truth):
    holdout_dir.mkdir()
    (holdout_dir / "truth.json").write_text(json.dumps(truth))


def test_many_to_one_emits_deterministic_positive_cent_exact_invoice_rows(
    tmp_path, monkeypatch
):
    holdout_dir = tmp_path / "holdout"
    truth_item = _truth_item("txn_0042", "100.01")
    _write_truth(holdout_dir, [truth_item])
    monkeypatch.setattr(ledger_generator, "HOLDOUT_DIR", holdout_dir)

    first_rows = ledger_generator.generate()
    first_csv = (holdout_dir / "internal_ledger.csv").read_text()
    second_rows = ledger_generator.generate()

    assert len(first_rows) in {2, 3}
    assert first_rows == second_rows
    assert first_csv == (holdout_dir / "internal_ledger.csv").read_text()
    assert sum(Decimal(row["amount"]) for row in first_rows) == Decimal("100.01")
    assert all(Decimal(row["amount"]) > 0 for row in first_rows)
    assert all(Decimal(row["amount"]).as_tuple().exponent == -2 for row in first_rows)
    assert [row["record_id"] for row in first_rows] == [
        f"ledger_txn_0042_invoice_{index:02d}"
        for index in range(1, len(first_rows) + 1)
    ]
    assert len({row["reference"] for row in first_rows}) == len(first_rows)

    with (holdout_dir / "internal_ledger.csv").open(newline="") as ledger_file:
        assert list(csv.DictReader(ledger_file)) == first_rows


def test_non_grouped_truth_item_still_emits_one_ledger_row(tmp_path, monkeypatch):
    holdout_dir = tmp_path / "holdout"
    _write_truth(holdout_dir, [_truth_item("txn_0001", "12.34", "none")])
    monkeypatch.setattr(ledger_generator, "HOLDOUT_DIR", holdout_dir)

    rows = ledger_generator.generate()

    assert len(rows) == 1
    assert rows[0]["record_id"] == "ledger_txn_0001"
    assert rows[0]["amount"] == "12.34"


def test_generate_refuses_to_overwrite_frozen_holdout(tmp_path, monkeypatch):
    holdout_dir = tmp_path / "holdout"
    _write_truth(holdout_dir, [_truth_item("txn_0042", "100.01")])
    ledger_path = holdout_dir / "internal_ledger.csv"
    ledger_path.write_text("existing frozen content\n")
    (holdout_dir / "HOLDOUT_HASH.txt").write_text("frozen-hash\n")
    monkeypatch.setattr(ledger_generator, "HOLDOUT_DIR", holdout_dir)

    with pytest.raises(RuntimeError, match="Refusing to regenerate frozen holdout"):
        ledger_generator.generate()

    assert ledger_path.read_text() == "existing frozen content\n"
