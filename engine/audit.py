"""SQLite-backed audit trail for reconciliation outcomes.

The audit store deliberately persists the complete Pydantic payload as JSON
*and* normalizes record identifiers into a join table.  The JSON preserves the
original decision without lossy schema translation; the join table makes the
answer to "what happened to record X?" an indexed query rather than a scan.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Iterator

from config.schema import ExceptionRecord, MatchDecision


_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_entries (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_type TEXT NOT NULL CHECK (entry_type IN ('match_decision', 'exception_record')),
    tier INTEGER,
    confidence REAL,
    rationale TEXT,
    signal_scores_json TEXT,
    reason_code TEXT,
    reason_detail TEXT,
    estimated_amount_at_risk TEXT,
    payload_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_entry_records (
    audit_id INTEGER NOT NULL REFERENCES audit_entries(audit_id) ON DELETE CASCADE,
    record_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (audit_id, record_id)
);

CREATE INDEX IF NOT EXISTS idx_audit_entry_records_record_id
    ON audit_entry_records(record_id);
"""


class AuditStore:
    """Persist and query complete reconciliation decisions in SQLite.

    The store owns one connection and is safe to use as a context manager.
    ``check_same_thread=False`` plus an internal lock allows FastAPI's worker
    threads to share a store while each multi-entry write remains atomic.
    """

    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        if self.database != ":memory:":
            Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(
            self.database,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        if self.database != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def __enter__(self) -> "AuditStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                self._connection.execute("BEGIN")
                yield self._connection
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def persist_decision(self, decision: MatchDecision) -> int:
        """Persist one grounded match decision and return its audit ID."""

        with self._transaction() as connection:
            return self._insert_decision(connection, decision)

    def persist_exception(self, exception: ExceptionRecord) -> int:
        """Persist one specific exception and return its audit ID."""

        with self._transaction() as connection:
            return self._insert_exception(connection, exception)

    def persist_all(
        self,
        decisions: Iterable[MatchDecision],
        exceptions: Iterable[ExceptionRecord],
    ) -> list[int]:
        """Atomically persist a reconciliation run's complete output."""

        decision_list = list(decisions)
        exception_list = list(exceptions)
        with self._transaction() as connection:
            audit_ids = [
                self._insert_decision(connection, decision)
                for decision in decision_list
            ]
            audit_ids.extend(
                self._insert_exception(connection, exception)
                for exception in exception_list
            )
        return audit_ids

    def get_by_record_id(self, record_id: str) -> list[dict[str, Any]]:
        """Return every audit outcome containing ``record_id`` in write order."""

        if not record_id.strip():
            raise ValueError("record_id must not be empty")
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT DISTINCT entries.*
                FROM audit_entries AS entries
                JOIN audit_entry_records AS records
                  ON records.audit_id = entries.audit_id
                WHERE records.record_id = ?
                ORDER BY entries.audit_id
                """,
                (record_id,),
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def iter_entries(self) -> list[dict[str, Any]]:
        """Return all audit entries in deterministic insertion order."""

        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM audit_entries ORDER BY audit_id"
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def count(self) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) AS count FROM audit_entries"
            ).fetchone()
        return int(row["count"])

    def audited_record_ids(self) -> set[str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT DISTINCT record_id FROM audit_entry_records"
            ).fetchall()
        return {str(row["record_id"]) for row in rows}

    def verify_record_coverage(self, expected_record_ids: Iterable[str]) -> None:
        """Fail loudly if any expected source record lacks an audit outcome."""

        expected = set(expected_record_ids)
        missing = expected - self.audited_record_ids()
        if missing:
            raise RuntimeError(
                "Audit trail is missing source record IDs: "
                + ", ".join(sorted(missing))
            )

    @staticmethod
    def _validate_record_ids(record_ids: Sequence[str]) -> None:
        if not record_ids:
            raise ValueError("Audit entries must contain at least one source record ID")
        if any(not record_id.strip() for record_id in record_ids):
            raise ValueError("Audit source record IDs must not be empty")
        if len(set(record_ids)) != len(record_ids):
            raise ValueError("Audit source record IDs must be unique within an entry")

    @classmethod
    def _insert_decision(
        cls,
        connection: sqlite3.Connection,
        decision: MatchDecision,
    ) -> int:
        cls._validate_record_ids(decision.record_ids)
        if not decision.rationale.strip():
            raise ValueError("MatchDecision rationale must not be empty")
        payload = decision.model_dump(mode="json")
        cursor = connection.execute(
            """
            INSERT INTO audit_entries (
                entry_type, tier, confidence, rationale, signal_scores_json,
                payload_json, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "match_decision",
                decision.tier,
                decision.confidence,
                decision.rationale,
                _json_dumps(payload["signal_scores"]),
                _json_dumps(payload),
                _utc_now(),
            ),
        )
        audit_id = int(cursor.lastrowid)
        cls._insert_record_ids(connection, audit_id, decision.record_ids)
        return audit_id

    @classmethod
    def _insert_exception(
        cls,
        connection: sqlite3.Connection,
        exception: ExceptionRecord,
    ) -> int:
        cls._validate_record_ids(exception.record_ids)
        if not exception.reason_detail.strip():
            raise ValueError("ExceptionRecord reason_detail must not be empty")
        payload = exception.model_dump(mode="json")
        cursor = connection.execute(
            """
            INSERT INTO audit_entries (
                entry_type, reason_code, reason_detail,
                estimated_amount_at_risk, payload_json, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "exception_record",
                exception.reason_code.value,
                exception.reason_detail,
                payload["estimated_amount_at_risk"],
                _json_dumps(payload),
                _utc_now(),
            ),
        )
        audit_id = int(cursor.lastrowid)
        cls._insert_record_ids(connection, audit_id, exception.record_ids)
        return audit_id

    @staticmethod
    def _insert_record_ids(
        connection: sqlite3.Connection,
        audit_id: int,
        record_ids: Sequence[str],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO audit_entry_records (audit_id, record_id, position)
            VALUES (?, ?, ?)
            """,
            (
                (audit_id, record_id, position)
                for position, record_id in enumerate(record_ids)
            ),
        )

    @staticmethod
    def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["record_ids"] = json.loads(result["payload_json"])["record_ids"]
        result["payload"] = json.loads(result.pop("payload_json"))
        signal_scores_json = result.pop("signal_scores_json")
        result["signal_scores"] = (
            json.loads(signal_scores_json) if signal_scores_json is not None else None
        )
        return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = ["AuditStore"]
