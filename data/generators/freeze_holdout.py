"""Validate and freeze the generated held-out dataset with one SHA-256."""
from __future__ import annotations

import hashlib
from pathlib import Path

from data.generators.validate_coverage import validate_coverage

HOLDOUT_DIR = Path("data/holdout")
HASHED_FILENAMES = (
    "truth.json",
    "bank_statement.csv",
    "internal_ledger.csv",
)
HASH_FILENAME = "HOLDOUT_HASH.txt"


def compute_holdout_hash(holdout_dir: Path | None = None) -> str:
    """Hash named files in a fixed order, including unambiguous boundaries."""
    root = holdout_dir or HOLDOUT_DIR
    digest = hashlib.sha256()
    for filename in HASHED_FILENAMES:
        path = root / filename
        try:
            content = path.read_bytes()
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Cannot freeze holdout; missing file: {path}") from exc
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def freeze_holdout(holdout_dir: Path | None = None) -> str:
    """Validate, hash, and exclusively create the freeze marker."""
    root = holdout_dir or HOLDOUT_DIR
    hash_path = root / HASH_FILENAME
    if hash_path.exists():
        raise FileExistsError(f"Refusing to overwrite frozen holdout hash: {hash_path}")

    validate_coverage(root)
    digest = compute_holdout_hash(root)
    with hash_path.open("x") as handle:
        handle.write(f"{digest}\n")
    return digest


def main() -> None:
    digest = freeze_holdout()
    print(f"Wrote {HOLDOUT_DIR / HASH_FILENAME}: {digest}")


if __name__ == "__main__":
    main()
