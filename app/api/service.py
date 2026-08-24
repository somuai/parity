"""Snapshot persistence and live-run adapter for the hosted API.

Reads are deliberately served from immutable JSON snapshots. Only ``rerun``
invokes the existing Tier 1/Tier 2 engine; the API contains no matching rules.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from config.schema import CanonicalRecord, ExceptionRecord, MatchDecision


SNAPSHOT_SCHEMA_VERSION = 1
CURRENT_SNAPSHOT = "current_run.json"
PREVIOUS_SNAPSHOT = "previous_run.json"
CANONICAL_EVAL = "canonical_eval.json"


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
        current_digest = current_summary.get("outcome_digest")
        previous_digest = previous_summary.get("outcome_digest") if previous_summary else None
        return {
            "previous": (
                {
                    "run_id": previous["run_id"],
                    "match_rate": previous_rate,
                    "outcome_digest": previous_digest,
                }
                if previous
                else None
            ),
            "current": {
                "run_id": snapshot["run_id"],
                "match_rate": current_rate,
                "outcome_digest": current_digest,
            },
            "reproducible": bool(
                previous_digest
                and current_digest
                and previous_digest == current_digest
            ),
            "match_rate_delta": (
                None if previous_rate is None else current_rate - previous_rate
            ),
        }


class ProductionRunExecutor:
    """Export a live refresh or deterministic canonical replay to a snapshot."""

    def __init__(self, repo_root: Path, *, live: bool = False) -> None:
        self.repo_root = Path(repo_root)
        self.live = live

    def __call__(self) -> dict[str, Any]:
        # Late imports keep GET endpoints light and prevent model/network work.
        from data.generators.freeze_holdout import compute_holdout_hash
        from engine.adjudicator import LLMBudget
        from engine.audit import AuditStore
        from engine.normalize import load_holdout_records
        from engine.tier1_deterministic import match_tier1
        from engine.tier2_reasoning import reconcile_tier2
        from eval.exception_book import build_exception_book
        from eval.phase3_live import EXPECTED_HOLDOUT_HASH, build_live_report

        holdout_dir = self.repo_root / "data" / "holdout"
        stored_hash = (
            holdout_dir / "HOLDOUT_HASH.txt"
        ).read_text(encoding="utf-8").strip()
        actual_hash = compute_holdout_hash(holdout_dir)
        if stored_hash != EXPECTED_HOLDOUT_HASH or actual_hash != EXPECTED_HOLDOUT_HASH:
            raise RuntimeError(
                "Frozen holdout hash mismatch: "
                f"expected={EXPECTED_HOLDOUT_HASH}, stored={stored_hash}, "
                f"actual={actual_hash}"
            )

        bank_records, ledger_records = load_holdout_records(holdout_dir)
        tier1, unmatched_bank, unmatched_ledger = match_tier1(
            bank_records, ledger_records
        )
        canonical_path = self.repo_root / "results" / CANONICAL_EVAL
        if self.live:
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
            canonical = None
        else:
            canonical = _load_canonical_eval(canonical_path, actual_hash)
            recorded_tier1 = canonical["tier1_decisions"]
            actual_tier1 = [decision.model_dump(mode="json") for decision in tier1]
            if actual_tier1 != recorded_tier1:
                raise RuntimeError(
                    "Tier 1 output drifted from the canonical live evaluation; "
                    "run make eval-tier2-live and review the changed metrics"
                )
            tier2 = _tier2_from_canonical(canonical["tier2"])
            budget = _budget_from_canonical(canonical["budget"])
            elapsed = float(canonical["report"]["elapsed_seconds"])
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
        if canonical is not None:
            _verify_canonical_metrics(report, canonical["report"])
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
                [*tier1, *tier2.decisions],
                tier2.exceptions,
                run_id=snapshot["run_id"],
            )
            audit_store.verify_record_coverage(
                source_records,
                run_id=snapshot["run_id"],
            )
        snapshot["summary"]["audit"] = {
            "entries_written": len(audit_ids),
            "records_covered": len(source_records),
        }
        _atomic_write_json(results_dir / "exception_book.json", exception_book)
        validate_snapshot(snapshot)
        if self.live:
            _atomic_write_json(
                canonical_path,
                _canonical_eval_payload(
                    holdout_hash=actual_hash,
                    tier1=tier1,
                    tier2=tier2,
                    budget=budget,
                    report=report,
                ),
            )
        return snapshot


def _canonical_eval_payload(
    *,
    holdout_hash: str,
    tier1: Sequence[MatchDecision],
    tier2: Any,
    budget: Any,
    report: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "holdout_hash": holdout_hash,
        "tier1_decisions": [decision.model_dump(mode="json") for decision in tier1],
        "tier2": {
            "decisions": [
                decision.model_dump(mode="json") for decision in tier2.decisions
            ],
            "exceptions": [
                exception.model_dump(mode="json") for exception in tier2.exceptions
            ],
            "calls_used": tier2.calls_used,
            "tokens_used": tier2.tokens_used,
            "semantic_backend_counts": tier2.semantic_backend_counts,
            "answering_tier_counts": tier2.answering_tier_counts,
            "answering_model_counts": tier2.answering_model_counts,
            "adjudication_failures": tier2.adjudication_failures,
        },
        "budget": {
            name: getattr(budget, name)
            for name in (
                "call_limit",
                "token_limit",
                "calls_used",
                "tokens_used",
                "rate_limit_hits",
                "rate_limit_retries",
                "validation_retries",
                "reasoning_escalations",
                "transport_error_hits",
                "transport_error_retries",
                "capacity_fallbacks",
            )
        },
        "report": dict(report),
    }


def _load_canonical_eval(path: Path, holdout_hash: str) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(
            f"Missing canonical live evaluation at {path}; run make eval-tier2-live"
        )
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise RuntimeError("Canonical live evaluation has an unsupported schema")
    if value.get("holdout_hash") != holdout_hash:
        raise RuntimeError("Canonical live evaluation does not match the frozen holdout")
    return value


def _tier2_from_canonical(payload: Mapping[str, Any]) -> Any:
    from engine.tier2_reasoning import Tier2RunResult

    return Tier2RunResult(
        decisions=[MatchDecision.model_validate(item) for item in payload["decisions"]],
        exceptions=[
            ExceptionRecord.model_validate(item) for item in payload["exceptions"]
        ],
        calls_used=int(payload["calls_used"]),
        tokens_used=int(payload["tokens_used"]),
        semantic_backend_counts=dict(payload["semantic_backend_counts"]),
        answering_tier_counts=dict(payload["answering_tier_counts"]),
        answering_model_counts=dict(payload["answering_model_counts"]),
        adjudication_failures=int(payload["adjudication_failures"]),
    )


def _budget_from_canonical(payload: Mapping[str, Any]) -> Any:
    from engine.adjudicator import LLMBudget

    return LLMBudget(**{name: int(value) for name, value in payload.items()})


_CANONICAL_METRIC_FIELDS = (
    "truth_transactions",
    "resolvable_truth_transactions",
    "tier1_matched_truth_transactions",
    "tier2_matched_truth_transactions",
    "matched_truth_transactions",
    "false_positive_decisions",
    "match_rate",
    "precision",
    "recall",
    "false_positive_cost_inr",
    "exception_book_transactions",
    "matched_and_exception_overlap",
    "neither_matched_nor_exception",
    "exception_truth_types",
    "semantic_backend_counts",
    "answering_tier_counts",
    "answering_model_counts",
    "adjudication_failures",
    "llm_calls_used",
    "llm_tokens_used",
)


def _verify_canonical_metrics(
    actual: Mapping[str, Any], expected: Mapping[str, Any]
) -> None:
    drift = {
        field: {"expected": expected.get(field), "actual": actual.get(field)}
        for field in _CANONICAL_METRIC_FIELDS
        if actual.get(field) != expected.get(field)
    }
    if drift:
        raise RuntimeError(f"Canonical replay metric drift: {drift}")


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
        signals = dict(exception.signal_scores)
        confidence = exception.confidence
        for record_id in exception.record_ids:
            if record_id in by_id:
                raise SnapshotValidationError(
                    f"record {record_id} appears in both a match and exception"
                )
            by_id[record_id] = {
                "status": "exception",
                "tier": exception.tier,
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
    outcome_payload = [
        {
            key: record[key]
            for key in (
                "id",
                "status",
                "tier",
                "confidence",
                "rationale",
                "signal_scores",
                "reason_code",
                "estimated_amount_at_risk_inr",
            )
        }
        for record in api_records
    ]
    outcome_digest = hashlib.sha256(
        json.dumps(
            outcome_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    leakage = exception_book["leakage"]
    non_leakage = exception_book["non_leakage"]
    run_id = f"heldout-{uuid4().hex[:12]}"
    summary = {
        "run_id": run_id,
        "timestamp_utc": report.get(
            "timestamp_utc", datetime.now(timezone.utc).isoformat()
        ),
        "holdout_hash": report["holdout_hash"],
        "outcome_digest": outcome_digest,
        "records_total": len(api_records),
        "truth_transactions": report["truth_transactions"],
        "match_rate": report["match_rate"],
        "precision": report["precision"],
        "recall": report["recall"],
        "false_positive_decisions": report["false_positive_decisions"],
        "false_positive_cost_inr": report["false_positive_cost_inr"],
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
        "throughput_source_records_per_second": round(
            len(api_records) / max(float(report["elapsed_seconds"]), 0.001),
            3,
        ),
        "semantic_backend_counts": report.get("semantic_backend_counts", {}),
        "answering_tier_counts": report.get("answering_tier_counts", {}),
        "answering_model_counts": report.get("answering_model_counts", {}),
        "adjudication_failures": report.get("adjudication_failures", 0),
        "rate_limit_hits": report.get("rate_limit_hits", 0),
        "rate_limit_retries": report.get("rate_limit_retries", 0),
        "validation_retries": report.get("validation_retries", 0),
        "reasoning_escalations": report.get("reasoning_escalations", 0),
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
