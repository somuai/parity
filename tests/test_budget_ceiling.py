from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from engine.adjudicator import BudgetExceededError, LLMBudget, adjudicate
from config.schema import CanonicalRecord, Source


def _record(record_id: str, source: Source) -> CanonicalRecord:
    return CanonicalRecord(
        record_id=record_id,
        source=source,
        amount=Decimal("100.00"),
        txn_date=date(2026, 8, 24),
        reference="pay_budget",
        description="Budget ceiling fixture",
        counterparty="Budget Merchant",
    )


def test_env_call_ceiling_stops_adjudicator_before_second_request(monkeypatch):
    """A deliberately undersized per-run ceiling must fail loudly."""

    monkeypatch.setenv("LLM_CALL_BUDGET_PER_RUN", "1")
    monkeypatch.setenv("TOKEN_BUDGET_PER_RUN", "200000")

    class Response:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "verdict": "uncertain",
                                    "confidence": 0.5,
                                    "rationale": "Signals require escalation.",
                                }
                            )
                        }
                    }
                ],
                "usage": {"total_tokens": 20},
            }

    class Session:
        def __init__(self):
            self.requests = 0

        def post(self, *_args, **_kwargs):
            self.requests += 1
            return Response()

    session = Session()
    budget = LLMBudget.from_env()
    with pytest.raises(BudgetExceededError, match="call budget exhausted"):
        adjudicate(
            [_record("bank_budget", Source.BANK)],
            [_record("ledger_budget", Source.LEDGER)],
            {"amount_delta": 0.0, "timing_delta": 0.0, "semantic": 1.0},
            budget=budget,
            api_key="test-key-not-real",
            live_model_ids={"openai/gpt-oss-20b", "openai/gpt-oss-120b"},
            fast_model="openai/gpt-oss-20b",
            reasoning_model="openai/gpt-oss-120b",
            session=session,
            max_rate_limit_retries=0,
        )

    assert budget.call_limit == 1
    assert budget.calls_used == session.requests == 1
