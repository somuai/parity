"""One-command fixture-free reconciliation and observability export."""
from __future__ import annotations

import json
from pathlib import Path

from app.api.service import ProductionRunExecutor, SnapshotStore


REPO_ROOT = Path(__file__).resolve().parent.parent


def run_and_store() -> dict:
    """Run the real held-out pipeline and atomically publish its snapshot."""

    snapshot = ProductionRunExecutor(REPO_ROOT)()
    SnapshotStore(REPO_ROOT / "results").rotate(snapshot)
    return snapshot


def main() -> None:
    snapshot = run_and_store()
    print(json.dumps(snapshot["summary"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
