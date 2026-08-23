"""Validate the generated held-out set before it is frozen.

This validator treats ``truth.json`` as the label source. Group labels never
appear in the bank or ledger CSVs; source rows resolve to a group through the
deterministic record IDs emitted by the generators.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from config.schema import ExceptionType
from data.generators.exception_taxonomy import TARGET_DISTRIBUTION

HOLDOUT_DIR = Path("data/holdout")


class CoverageValidationError(ValueError):
    """Raised when held-out data cannot be graded reliably."""


def _load_json(path: Path) -> list[dict]:
    try:
        with path.open() as handle:
            value = json.load(handle)
    except FileNotFoundError as exc:
        raise CoverageValidationError(f"Missing required holdout file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CoverageValidationError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, list):
        raise CoverageValidationError(f"Expected a JSON list in {path}, got {type(value).__name__}")
    return value


def _load_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(newline="") as handle:
            return list(csv.DictReader(handle))
    except FileNotFoundError as exc:
        raise CoverageValidationError(f"Missing required holdout file: {path}") from exc


def _rows_for_true_id(rows: list[dict[str, str]], source: str, true_id: str) -> list[dict[str, str]]:
    base_id = f"{source}_{true_id}"
    return [
        row
        for row in rows
        if row.get("record_id") == base_id
        or row.get("record_id", "").startswith(f"{base_id}_")
    ]


def _amount_sum(rows: list[dict[str, str]], *, label: str) -> Decimal:
    try:
        return sum((Decimal(row["amount"]) for row in rows), Decimal("0"))
    except (InvalidOperation, KeyError) as exc:
        raise CoverageValidationError(f"Invalid amount in {label}: {exc}") from exc


def validate_coverage(holdout_dir: Path | None = None) -> dict[ExceptionType, int]:
    """Validate taxonomy counts and all truth-to-source relationships."""
    root = holdout_dir or HOLDOUT_DIR
    truth = _load_json(root / "truth.json")
    bank_rows = _load_csv(root / "bank_statement.csv")
    ledger_rows = _load_csv(root / "internal_ledger.csv")

    truth_ids: list[str] = []
    actual_counts: Counter[ExceptionType] = Counter()
    group_ids: set[str] = set()

    for index, item in enumerate(truth):
        try:
            true_id = item["true_id"]
            exception_type = ExceptionType(item["exception_type"])
        except KeyError as exc:
            raise CoverageValidationError(
                f"Truth row {index} is missing required field {exc.args[0]!r}"
            ) from exc
        except ValueError as exc:
            raise CoverageValidationError(
                f"Truth row {index} has unknown exception_type {item.get('exception_type')!r}"
            ) from exc
        truth_ids.append(true_id)
        actual_counts[exception_type] += 1

    duplicate_truth_ids = [item for item, count in Counter(truth_ids).items() if count > 1]
    if duplicate_truth_ids:
        raise CoverageValidationError(f"Duplicate true_id values: {duplicate_truth_ids}")

    for exception_type, expected in TARGET_DISTRIBUTION.items():
        actual = actual_counts[exception_type]
        if actual != expected:
            raise CoverageValidationError(
                f"Count mismatch for {exception_type.value}: expected {expected}, actual {actual}"
            )

    known_truth_ids = set(truth_ids)
    for source, rows in (("bank", bank_rows), ("ledger", ledger_rows)):
        seen_record_ids: set[str] = set()
        for row_number, row in enumerate(rows, start=2):
            record_id = row.get("record_id", "")
            if record_id in seen_record_ids:
                raise CoverageValidationError(f"Duplicate {source} record_id: {record_id}")
            seen_record_ids.add(record_id)
            prefix = f"{source}_"
            matching_ids = [
                true_id
                for true_id in known_truth_ids
                if record_id == f"{prefix}{true_id}"
                or record_id.startswith(f"{prefix}{true_id}_")
            ]
            if len(matching_ids) != 1:
                raise CoverageValidationError(
                    f"{source} row {row_number} record_id {record_id!r} resolves to "
                    f"{len(matching_ids)} truth rows"
                )

    for item in truth:
        true_id = item["true_id"]
        exception_type = ExceptionType(item["exception_type"])
        bank_group = _rows_for_true_id(bank_rows, "bank", true_id)
        ledger_group = _rows_for_true_id(ledger_rows, "ledger", true_id)

        if not bank_group and not ledger_group:
            raise CoverageValidationError(
                f"Truth record {true_id} is missing from both bank and ledger"
            )

        if exception_type == ExceptionType.ORPHAN:
            if (bool(bank_group) + bool(ledger_group)) != 1:
                raise CoverageValidationError(
                    f"Orphan {true_id} must appear on exactly one side; "
                    f"bank={len(bank_group)}, ledger={len(ledger_group)}"
                )
            continue

        if not bank_group or not ledger_group:
            raise CoverageValidationError(
                f"Non-orphan {true_id} is missing from one side; "
                f"bank={len(bank_group)}, ledger={len(ledger_group)}"
            )

        if exception_type not in {ExceptionType.ONE_TO_MANY, ExceptionType.MANY_TO_ONE}:
            if item.get("group_id") is not None:
                raise CoverageValidationError(
                    f"Non-grouped truth record {true_id} unexpectedly has group_id "
                    f"{item['group_id']!r}"
                )
            continue

        group_id = item.get("group_id")
        if not isinstance(group_id, str) or not group_id:
            raise CoverageValidationError(f"Grouped truth record {true_id} has no group_id")
        if group_id in group_ids:
            raise CoverageValidationError(f"Duplicate group_id {group_id!r}")
        group_ids.add(group_id)

        expected_amount = Decimal(item["amount"])
        if exception_type == ExceptionType.ONE_TO_MANY:
            many_rows, one_rows = bank_group, ledger_group
            many_side, one_side = "bank", "ledger"
        else:
            many_rows, one_rows = ledger_group, bank_group
            many_side, one_side = "ledger", "bank"

        if len(many_rows) not in {2, 3} or len(one_rows) != 1:
            raise CoverageValidationError(
                f"Group {group_id} ({exception_type.value}) has invalid cardinality: "
                f"{many_side}={len(many_rows)}, {one_side}={len(one_rows)}; expected 2-3:1"
            )
        many_amount = _amount_sum(many_rows, label=f"group {group_id} {many_side}")
        one_amount = _amount_sum(one_rows, label=f"group {group_id} {one_side}")
        if many_amount != expected_amount or one_amount != expected_amount:
            raise CoverageValidationError(
                f"Group {group_id} amount mismatch: truth={expected_amount}, "
                f"{many_side}={many_amount}, {one_side}={one_amount}"
            )

    return {exception_type: actual_counts[exception_type] for exception_type in TARGET_DISTRIBUTION}


def main() -> None:
    counts = validate_coverage()
    for exception_type, expected in TARGET_DISTRIBUTION.items():
        print(
            f"PASS {exception_type.value}: expected={expected} "
            f"actual={counts[exception_type]}"
        )
    print("PASS group integrity and source-row coverage")


if __name__ == "__main__":
    main()
