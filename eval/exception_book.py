"""Build the honest, JSON-ready exception book used by the Phase 4 API."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

from config.schema import CanonicalRecord, ExceptionRecord, ExceptionType, Source


# Only these reason codes can establish real leakage, and even then only when
# there is a supportable amount.  Everything else remains human-review work.
_LEAKAGE_CAPABLE = frozenset(
    {ExceptionType.DUPLICATE_ENTRY, ExceptionType.PARTIAL_REFUND}
)
_GENERIC_DETAILS = frozenset(
    {
        "could not match",
        "unable to match",
        "unmatched",
        "unresolved",
        "unknown",
        "no match",
        "manual review required",
        "needs review",
        "review required",
    }
)


def build_exception_book(
    exceptions: Iterable[ExceptionRecord],
    source_records: Mapping[str, CanonicalRecord] | Iterable[CanonicalRecord] | None = None,
) -> dict[str, Any]:
    """Return exceptions grouped by reason with leakage kept separate.

    ``source_records`` is optional.  When supplied, it can support a
    deterministic amount for duplicate rows or a partial-refund delta when
    Tier 2 did not populate ``estimated_amount_at_risk``.  The output records
    where every amount came from; no unsupported amount is guessed.
    """

    record_lookup = _build_record_lookup(source_records)
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    totals = {
        "leakage": {"entry_count": 0, "total_amount_at_risk_inr": Decimal("0")},
        "non_leakage": {
            "entry_count": 0,
            "total_amount_at_risk_inr": Decimal("0"),
        },
    }

    for exception in exceptions:
        _validate_exception(exception)
        amount, amount_source = _supported_amount(exception, record_lookup)
        is_leakage = exception.reason_code in _LEAKAGE_CAPABLE and amount is not None
        classification = "leakage" if is_leakage else "non_leakage"
        if is_leakage:
            classification_reason = (
                f"{exception.reason_code.value} has a supportable amount-at-risk estimate."
            )
        elif exception.reason_code in _LEAKAGE_CAPABLE:
            classification_reason = (
                f"{exception.reason_code.value} is leakage-capable but has no "
                "supportable amount; excluded from leakage conservatively."
            )
        else:
            classification_reason = (
                f"{exception.reason_code.value} is review-only and is never "
                "classified as proven leakage."
            )

        entry = {
            "record_ids": list(exception.record_ids),
            "reason_code": exception.reason_code.value,
            "reason_detail": exception.reason_detail,
            "estimated_amount_at_risk_inr": str(amount) if amount is not None else None,
            "amount_source": amount_source,
            "risk_classification": classification,
            "classification_reason": classification_reason,
        }
        grouped[exception.reason_code.value].append(entry)
        totals[classification]["entry_count"] += 1
        if amount is not None:
            totals[classification]["total_amount_at_risk_inr"] += amount

    groups = {
        reason_code: {
            "entry_count": len(entries),
            "leakage_entry_count": sum(
                entry["risk_classification"] == "leakage" for entry in entries
            ),
            "non_leakage_entry_count": sum(
                entry["risk_classification"] == "non_leakage" for entry in entries
            ),
            "entries": entries,
        }
        for reason_code, entries in sorted(grouped.items())
    }
    return {
        "schema_version": 1,
        "total_entries": sum(group["entry_count"] for group in groups.values()),
        "leakage": _json_total(totals["leakage"]),
        "non_leakage": _json_total(totals["non_leakage"]),
        "groups": groups,
    }


def write_exception_book(
    exceptions: Iterable[ExceptionRecord],
    output_path: str | Path,
    source_records: Mapping[str, CanonicalRecord] | Iterable[CanonicalRecord] | None = None,
) -> dict[str, Any]:
    """Build and write an exception book, returning the same JSON-ready dict."""

    book = build_exception_book(exceptions, source_records)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(book, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return book


def _build_record_lookup(
    source_records: Mapping[str, CanonicalRecord] | Iterable[CanonicalRecord] | None,
) -> dict[str, CanonicalRecord]:
    if source_records is None:
        return {}
    if isinstance(source_records, Mapping):
        lookup = dict(source_records)
    else:
        lookup = {record.record_id: record for record in source_records}
    invalid = [record_id for record_id, record in lookup.items() if record.record_id != record_id]
    if invalid:
        raise ValueError(
            "source_records mapping keys must equal CanonicalRecord.record_id: "
            + ", ".join(sorted(invalid))
        )
    return lookup


def _validate_exception(exception: ExceptionRecord) -> None:
    if not exception.record_ids:
        raise ValueError("Exception entries must contain at least one source record ID")
    detail = " ".join(exception.reason_detail.lower().strip().rstrip(".").split())
    if not detail or detail in _GENERIC_DETAILS:
        raise ValueError(
            f"Exception {exception.record_ids} has generic reason_detail: "
            f"{exception.reason_detail!r}"
        )
    if exception.estimated_amount_at_risk is not None:
        if not exception.estimated_amount_at_risk.is_finite():
            raise ValueError("estimated_amount_at_risk must be finite")
        if exception.estimated_amount_at_risk < 0:
            raise ValueError("estimated_amount_at_risk must not be negative")


def _supported_amount(
    exception: ExceptionRecord,
    records: Mapping[str, CanonicalRecord],
) -> tuple[Decimal | None, str]:
    if exception.estimated_amount_at_risk is not None:
        return exception.estimated_amount_at_risk, "schema_field"

    involved = [records[record_id] for record_id in exception.record_ids if record_id in records]
    if len(involved) != len(exception.record_ids):
        return None, "unavailable"

    if exception.reason_code is ExceptionType.DUPLICATE_ENTRY and involved:
        return sum((abs(record.amount) for record in involved), Decimal("0")), (
            "derived_record_evidence"
        )

    if exception.reason_code is ExceptionType.PARTIAL_REFUND:
        bank_total = sum(
            (record.amount for record in involved if record.source is Source.BANK),
            Decimal("0"),
        )
        ledger_total = sum(
            (record.amount for record in involved if record.source is Source.LEDGER),
            Decimal("0"),
        )
        has_bank = any(record.source is Source.BANK for record in involved)
        has_ledger = any(record.source is Source.LEDGER for record in involved)
        if has_bank and has_ledger:
            return abs(bank_total - ledger_total), "derived_record_evidence"

    return None, "unavailable"


def _json_total(total: Mapping[str, int | Decimal]) -> dict[str, int | str]:
    return {
        "entry_count": int(total["entry_count"]),
        "total_amount_at_risk_inr": str(total["total_amount_at_risk_inr"]),
    }


__all__ = ["build_exception_book", "write_exception_book"]
