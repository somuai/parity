import hashlib

import pytest

from data.generators import freeze_holdout


def test_compute_holdout_hash_uses_fixed_names_content_and_boundaries(tmp_path):
    root = tmp_path / "holdout"
    root.mkdir()
    contents = {
        "truth.json": b"truth",
        "bank_statement.csv": b"bank",
        "internal_ledger.csv": b"ledger",
    }
    expected = hashlib.sha256()
    for filename, content in contents.items():
        (root / filename).write_bytes(content)
        expected.update(filename.encode())
        expected.update(b"\0")
        expected.update(content)
        expected.update(b"\0")

    assert freeze_holdout.compute_holdout_hash(root) == expected.hexdigest()


def test_freeze_validates_then_writes_hash_once(tmp_path, monkeypatch):
    root = tmp_path / "holdout"
    root.mkdir()
    for filename in freeze_holdout.HASHED_FILENAMES:
        (root / filename).write_text(filename)
    validation_calls = []
    monkeypatch.setattr(
        freeze_holdout,
        "validate_coverage",
        lambda path: validation_calls.append(path),
    )

    digest = freeze_holdout.freeze_holdout(root)

    assert validation_calls == [root]
    assert (root / freeze_holdout.HASH_FILENAME).read_text() == f"{digest}\n"
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        freeze_holdout.freeze_holdout(root)


def test_freeze_does_not_write_hash_when_validation_fails(tmp_path, monkeypatch):
    root = tmp_path / "holdout"
    root.mkdir()
    monkeypatch.setattr(
        freeze_holdout,
        "validate_coverage",
        lambda _path: (_ for _ in ()).throw(ValueError("bad coverage")),
    )

    with pytest.raises(ValueError, match="bad coverage"):
        freeze_holdout.freeze_holdout(root)

    assert not (root / freeze_holdout.HASH_FILENAME).exists()
