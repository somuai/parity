import csv
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from data.generators import bank_generator


def _truth_item(**overrides):
    item = {
        "true_id": "txn_split_01",
        "group_id": "group_txn_split_01",
        "reference": "pay_split_01",
        "amount": "100.01",
        "txn_date": "2026-07-01",
        "counterparty": "Customer_split",
        "is_international": False,
        "exception_type": "one_to_many",
        "perturb_side": "bank",
    }
    item.update(overrides)
    return item


def _set_temp_holdout(monkeypatch, tmp_path, truth):
    holdout_dir = tmp_path / "holdout"
    holdout_dir.mkdir()
    (holdout_dir / "truth.json").write_text(json.dumps(truth))
    monkeypatch.setattr(bank_generator, "HOLDOUT_DIR", holdout_dir)
    return holdout_dir


def test_one_to_many_emits_deterministic_cent_exact_settlement_parts(
    monkeypatch, tmp_path
):
    truth_item = _truth_item()
    holdout_dir = _set_temp_holdout(monkeypatch, tmp_path, [truth_item])

    first_rows = bank_generator.generate()
    second_rows = bank_generator.generate()

    assert first_rows == second_rows
    assert len(first_rows) in {2, 3}
    assert [row["record_id"] for row in first_rows] == [
        f"bank_{truth_item['true_id']}_part_{index}"
        for index in range(1, len(first_rows) + 1)
    ]
    assert all(Decimal(row["amount"]) > 0 for row in first_rows)
    assert all(
        Decimal(row["amount"]) == Decimal(row["amount"]).quantize(Decimal("0.01"))
        for row in first_rows
    )
    assert sum(Decimal(row["amount"]) for row in first_rows) == Decimal("100.01")
    assert [date.fromisoformat(row["txn_date"]) for row in first_rows] == [
        date(2026, 7, 1) + timedelta(days=2 * index)
        for index in range(1, len(first_rows) + 1)
    ]
    assert all(row["reference"] == truth_item["reference"] for row in first_rows)

    with (holdout_dir / "bank_statement.csv").open(newline="") as csv_file:
        assert list(csv.DictReader(csv_file)) == second_rows


def test_one_to_many_uses_international_settlement_cycle(monkeypatch, tmp_path):
    truth_item = _truth_item(is_international=True)
    _set_temp_holdout(monkeypatch, tmp_path, [truth_item])

    rows = bank_generator.generate()

    assert [date.fromisoformat(row["txn_date"]) for row in rows] == [
        date(2026, 7, 1) + timedelta(days=7 * index)
        for index in range(1, len(rows) + 1)
    ]


def test_generate_refuses_to_overwrite_frozen_holdout(monkeypatch, tmp_path):
    holdout_dir = _set_temp_holdout(monkeypatch, tmp_path, [_truth_item()])
    bank_csv = holdout_dir / "bank_statement.csv"
    bank_csv.write_text("existing bank data")
    (holdout_dir / "HOLDOUT_HASH.txt").write_text("frozen")

    with pytest.raises(RuntimeError, match="Refusing to regenerate frozen holdout"):
        bank_generator.generate()

    assert bank_csv.read_text() == "existing bank data"
