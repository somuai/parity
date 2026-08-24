"""Snapshot persistence and live-run adapter for the hosted API.

Reads are deliberately served from immutable JSON snapshots. Only ``rerun``
invokes the existing Tier 1/Tier 2 engine; the API contains no matching rules.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from config.schema import CanonicalRecord, ExceptionRecord, MatchDecision


SNAPSHOT_SCHEMA_VERSION = 1
CURRENT_SNAPSHOT = "current_run.json"
PREVIOUS_SNAPSHOT = "previous_run.json"


class SnapshotNotFoundError(RuntimeError):
    """Raised when the app has not been seeded by a real run yet."""


class RerunInProgressError(RuntimeError):
    """Raised instead of starting overlapping, budget-consuming reruns."""


class SnapshotValidationError(ValueError):
    """Raised when an executor returns an incomplete API artifact."""


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def validate_snapshot(snapshot: Mapping[str, Any]) -> None:
    required_top_level = {
        "schema_version",
        "run_id",
        "summary",
        "records",
        "exception_book",
    }
    missing = required_top_level - snapshot.keys()
    if missing:
        raise SnapshotValidationError(f"snapshot missing fields: {sorted(missing)}")
    if snapshot["schema_version"] != SNAPSHOT_SCHEMA_VERSION:
        raise SnapshotValidationError(
            f"unsupported snapshot schema_version={snapshot['schema_version']!r}"
        )
    if not isinstance(snapshot["summary"], Mapping):
        raise SnapshotValidationError("snapshot summary must be an object")
    records = snapshot["records"]
    if not isinstance(records, list):
        raise SnapshotValidationError("snapshot records must be an array")
    record_ids: list[str] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise SnapshotValidationError("every record must be an object")
        missing_record_fields = {
            "id",
            "source",
            "status",
            "confidence_band",
            "rationale",
            "signal_scores",
        } - record.keys()
        if missing_record_fields:
            raise SnapshotValidationError(
                f"record missing fields: {sorted(missing_record_fields)}"
            )
        record_ids.append(str(record["id"]))
    if len(record_ids) != len(set(record_ids)):
        raise SnapshotValidationError("snapshot record IDs must be unique")


class SnapshotStore:
    """Atomically rotate current/previous result snapshots."""

    def __init__(self, results_dir: Path) -> None:
        self.results_dir = Path(results_dir)
        self.current_path = self.results_dir / CURRENT_SNAPSHOT
        self.previous_path = self.results_dir / PREVIOUS_SNAPSHOT

    def load_current(self) -> dict[str, Any]:
        if not self.current_path.exists():
            raise SnapshotNotFoundError(
                "No held-out result snapshot exists; run POST /api/rerun or seed "
                "results/current_run.json"
            )
        value = json.loads(self.current_path.read_text(encoding="utf-8"))
        validate_snapshot(value)
        return value

    def load_previous(self) -> dict[str, Any] | None:
        if not self.previous_path.exists():
            return None
        value = json.loads(self.previous_path.read_text(encoding="utf-8"))
        validate_snapshot(value)
        return value

    def rotate(self, snapshot: Mapping[str, Any]) -> dict[str, Any] | None:
        validate_snapshot(snapshot)
        previous: dict[str, Any] | None = None
        if self.current_path.exists():
            previous = self.load_current()
            _atomic_write_json(self.previous_path, previous)
        _atomic_write_json(self.current_path, snapshot)
        return previous


RunExecutor = Callable[[], dict[str, Any]]


class APIService:
    """Read snapshots and serialize costly live reruns."""

    def __init__(self, store: SnapshotStore, executor: RunExecutor) -> None:
        self.store = store
        self.executor = executor
        self._rerun_lock = threading.Lock()

    def summary(self) -> dict[str, Any]:
        return dict(self.store.load_current()["summary"])

    def records(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.store.load_current()["records"]]

    def record(self, record_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in self.records() if item["id"] == record_id),
            None,
        )

    def rerun(self) -> dict[str, Any]:
        if not self._rerun_lock.acquire(blocking=False):
            raise RerunInProgressError("A held-out rerun is already in progress")
        try:
            snapshot = self.executor()
            previous = self.store.rotate(snapshot)
        finally:
            self._rerun_lock.release()

        current_summary = snapshot["summary"]
        previous_summary = previous["summary"] if previous else None
        current_rate = float(current_summary["match_rate"])
        previous_rate = (
            float(previous_summary["match_rate"]) if previous_summary else None
        )
        return {
            "previous": (
                {"run_id": previous["run_id"], "match_rate": previous_rate}
                if previous
                else None
            ),
            "current": {"run_id": snapshot["run_id"], "match_rate": current_rate},
            "reproducible": (
                previous_rate is None or abs(current_rate - previous_rate) < 1e-12
            ),
            "match_rate_delta": (
                None if previous_rate is None else current_rate - previous_rate
            ),
        }


class ProductionRunExecutor:
    """Export a fixture-free held-out engine run into the API snapshot contract."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = Path(repo_root)

    def __call__(self) -> dict[str, Any]:
        # Late imports keep GET endpoints light and prevent model/network work.
        from data.generators.freeze_holdout import compute_holdout_hash
        from engine.adjudicator import LLMBudget
        from engine.audit import AuditStore
        from engine.normalize import load_holdout_records
        from engine.tier1_deterministic import match_tier1
        from engine.tier2_reasoning import reconcile_tier2
        from eval.exception_book import build_exception_book
        from eval.phase3_live import build_live_report

        holdout_dir = self.repo_root / "data" / "holdout"
        stored_hash = (
            holdout_dir / "HOLDOUT_HASH.txt"
        ).read_text(encoding="utf-8").strip()
        actual_hash = compute_holdout_hash(holdout_dir)
        if actual_hash != stored_hash:
            raise RuntimeError(
                f"Frozen holdout hash mismatch: stored={stored_hash}, actual={actual_hash}"
            )

        bank_records, ledger_records = load_holdout_records(holdout_dir)
        tier1, unmatched_bank, unmatched_ledger = match_tier1(
            bank_records, ledger_records
        )
        budget = LLMBudget.from_env()
        started = time.monotonic()
        tier2 = reconcile_tier2(
            unmatched_bank,
            unmatched_ledger,
            budget=budget,
            semantic_encoder=None,
            allow_lexical_fallback=False,
        )
        elapsed = time.monotonic() - started
        all_records = [*bank_records, *ledger_records]
        source_records = {record.record_id: record for record in all_records}
        exception_book = build_exception_book(tier2.exceptions, source_records)
        truth = json.loads(
            (holdout_dir / "truth.json").read_text(encoding="utf-8")
        )
        report = build_live_report(
            truth=truth,
            bank_records=bank_records,
            ledger_records=ledger_records,
            tier1_decisions=tier1,
            tier2=tier2,
            budget=budget,
            holdout_hash=actual_hash,
            elapsed_seconds=elapsed,
        )
        snapshot = build_snapshot(
            report=report,
            records=all_records,
            tier1_decisions=tier1,
            tier2_decisions=tier2.decisions,
            exceptions=tier2.exceptions,
            exception_book=exception_book,
        )
        results_dir = self.repo_root / "results"
        with AuditStore(results_dir / "audit.sqlite3") as audit_store:
            audit_ids = audit_store.persist_all(
                [*tier1, *tier2.decisions], tier2.exceptions
            )
            audit_store.verify_record_coverage(source_records)
        snapshot["summary"]["audit"] = {
            "entries_written": len(audit_ids),
            "records_covered": len(source_records),
        }
        _atomic_write_json(results_dir / "exception_book.json", exception_book)
        validate_snapshot(snapshot)
        return snapshot


_SIGNAL_PATTERN = re.compile(
    r"(?P<name>amount_delta|timing_delta|semantic_similarity|reference_similarity|"
    r"fused_confidence|partial_refund_plausible|refund_ratio)="
    r"(?P<value>None|True|False|-?\d+(?:\.\d+)?)"
)


def _exception_signals(detail: str) -> dict[str, float]:
    """Recover the named, grounded values carried by ExceptionRecord detail."""

    values: dict[str, float] = {}
    for match in _SIGNAL_PATTERN.finditer(detail):
        raw = match.group("value")
        if raw == "None":
            continue
        if raw in {"True", "False"}:
            values[match.group("name")] = float(raw == "True")
        else:
            values[match.group("name")] = float(raw)
    return values


def _confidence_band(confidence: float, *, exception: bool = False) -> str:
    if exception:
        return "exception"
    if confidence >= 0.9:
        return "high"
    if confidence >= 0.6:
        return "medium"
    return "exception"


def _base_record(record: CanonicalRecord) -> dict[str, Any]:
    return {
        "id": record.record_id,
        "source": record.source.value,
        "amount_inr": str(record.amount),
        "txn_date": record.txn_date.isoformat(),
        "reference": record.reference,
        "description": record.description,
        "counterparty": record.counterparty,
        "fees_deducted_inr": (
            str(record.fees_deducted) if record.fees_deducted is not None else None
        ),
    }


def build_snapshot(
    *,
    report: Mapping[str, Any],
    records: Sequence[CanonicalRecord],
    tier1_decisions: Sequence[MatchDecision],
    tier2_decisions: Sequence[MatchDecision],
    exceptions: Sequence[ExceptionRecord],
    exception_book: Mapping[str, Any],
) -> dict[str, Any]:
    """Join engine outputs for presentation without changing any decision."""

    exception_amounts = {
        record_id: entry["estimated_amount_at_risk_inr"]
        for group in exception_book.get("groups", {}).values()
        for entry in group.get("entries", [])
        for record_id in entry["record_ids"]
    }
    by_id: dict[str, dict[str, Any]] = {}
    for decision in [*tier1_decisions, *tier2_decisions]:
        for record_id in decision.record_ids:
            by_id[record_id] = {
                "status": "matched",
                "tier": decision.tier,
                "confidence": decision.confidence,
                "confidence_band": _confidence_band(decision.confidence),
                "rationale": decision.rationale,
                "signal_scores": decision.signal_scores,
                "reason_code": None,
                "estimated_amount_at_risk_inr": None,
            }
    for exception in exceptions:
        signals = _exception_signals(exception.reason_detail)
        confidence = signals.get("fused_confidence", 0.0)
        for record_id in exception.record_ids:
            if record_id in by_id:
                raise SnapshotValidationError(
                    f"record {record_id} appears in both a match and exception"
                )
            by_id[record_id] = {
                "status": "exception",
                "tier": 2,
                "confidence": confidence,
                "confidence_band": _confidence_band(confidence, exception=True),
                "rationale": exception.reason_detail,
                "signal_scores": signals,
                "reason_code": exception.reason_code.value,
                "estimated_amount_at_risk_inr": (
                    str(exception.estimated_amount_at_risk)
                    if exception.estimated_amount_at_risk is not None
                    else exception_amounts.get(record_id)
                ),
            }

    source_ids = {record.record_id for record in records}
    missing = source_ids - by_id.keys()
    unexpected = by_id.keys() - source_ids
    if missing or unexpected:
        raise SnapshotValidationError(
            "engine output does not cover held-out sources: "
            f"missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )

    api_records = [
        {**_base_record(record), **by_id[record.record_id]}
        for record in sorted(records, key=lambda item: item.record_id)
    ]
    leakage = exception_book["leakage"]
    non_leakage = exception_book["non_leakage"]
    run_id = f"heldout-{uuid4().hex[:12]}"
    summary = {
        "run_id": run_id,
        "timestamp_utc": report.get(
            "timestamp_utc", datetime.now(timezone.utc).isoformat()
        ),
        "holdout_hash": report["holdout_hash"],
        "records_total": len(api_records),
        "truth_transactions": report["truth_transactions"],
        "match_rate": report["match_rate"],
        "precision": report["precision"],
        "recall": report["recall"],
        "matches": {
            "tier1": report["tier1_matched_truth_transactions"],
            "tier2": report["tier2_matched_truth_transactions"],
            "total": report["matched_truth_transactions"],
        },
        "exceptions": {
            "total": exception_book["total_entries"],
            "leakage": {
                "count": leakage["entry_count"],
                "total_amount_at_risk_inr": leakage[
                    "total_amount_at_risk_inr"
                ],
            },
            "non_leakage": {
                "count": non_leakage["entry_count"],
                "total_amount_at_risk_inr": non_leakage[
                    "total_amount_at_risk_inr"
                ],
            },
        },
        "budget": {
            "calls": {
                "used": report["llm_calls_used"],
                "limit": report["llm_call_budget"],
            },
            "tokens": {
                "used": report["llm_tokens_used"],
                "limit": report["llm_token_budget"],
            },
        },
        "elapsed_seconds": report["elapsed_seconds"],
    }
    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "run_id": run_id,
        "summary": summary,
        "records": api_records,
        "exception_book": dict(exception_book),
    }
    validate_snapshot(snapshot)
    return snapshot


__all__ = [
    "APIService",
    "CURRENT_SNAPSHOT",
    "PREVIOUS_SNAPSHOT",
    "ProductionRunExecutor",
    "RerunInProgressError",
    "SNAPSHOT_SCHEMA_VERSION",
    "SnapshotNotFoundError",
    "SnapshotStore",
    "SnapshotValidationError",
    "build_snapshot",
    "validate_snapshot",
]
