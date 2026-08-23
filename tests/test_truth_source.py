import json

import pytest

from config.schema import ExceptionType
from data.generators import truth_source


def test_truth_group_id_is_present_only_for_grouped_cases(tmp_path, monkeypatch):
    root = tmp_path / "holdout"
    monkeypatch.setattr(truth_source, "OUT_DIR", root)
    monkeypatch.setattr(
        truth_source,
        "TARGET_DISTRIBUTION",
        {ExceptionType.ONE_TO_MANY: 1, ExceptionType.NONE: 1},
    )

    rows = truth_source.generate_truth(n=2)
    grouped = next(row for row in rows if row["exception_type"] == "one_to_many")
    clean = next(row for row in rows if row["exception_type"] == "none")

    assert grouped["group_id"] == f"group_{grouped['true_id']}"
    assert clean["group_id"] is None
    assert json.loads((root / "truth.json").read_text()) == rows


def test_truth_generation_refuses_to_overwrite_frozen_holdout(tmp_path, monkeypatch):
    root = tmp_path / "holdout"
    root.mkdir()
    truth_path = root / "truth.json"
    truth_path.write_text("existing")
    (root / "HOLDOUT_HASH.txt").write_text("frozen")
    monkeypatch.setattr(truth_source, "OUT_DIR", root)

    with pytest.raises(RuntimeError, match="Refusing to regenerate frozen holdout"):
        truth_source.generate_truth()

    assert truth_path.read_text() == "existing"
