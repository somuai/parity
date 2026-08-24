"""One-command fixture-free reconciliation and observability export."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.api.service import ProductionRunExecutor, SnapshotStore


REPO_ROOT = Path(__file__).resolve().parent.parent


def run_and_store(*, live: bool = False) -> dict:
    """Replay the canonical run, or explicitly refresh it through live providers."""

    snapshot = ProductionRunExecutor(REPO_ROOT, live=live)()
    SnapshotStore(REPO_ROOT / "results").rotate(snapshot)
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live",
        action="store_true",
        help="use real MiniLM/Groq calls and replace the canonical evaluation",
    )
    args = parser.parse_args()
    snapshot = run_and_store(live=args.live)
    print(json.dumps(snapshot["summary"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
