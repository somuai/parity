from __future__ import annotations

from datetime import date

import pytest

from clients.razorpay_client import RazorpayPayloadError, RazorpayReconClient


def _item(entity_id: str, *, debit: int = 0, credit: int = 2500) -> dict:
    return {
        "entity_id": entity_id,
        "amount": max(debit, credit),
        "debit": debit,
        "credit": credit,
        "currency": "INR",
        "settled_at": 1_767_225_600,
        "created_at": 1,
        "payment_id": "pay_123",
        "type": "refund" if debit else "payment",
        "fee": 50,
    }


class _Response:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class _Session:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.params = []

    def get(self, _url, **kwargs):
        self.params.append(kwargs["params"])
        return _Response(next(self.pages))


def test_empty_activity_and_pagination_are_explicit_and_complete():
    empty = _Session([{"entity": "collection", "count": 0, "items": []}])
    assert RazorpayReconClient("key", "secret", session=empty).fetch_settlement_recon(
        2026, 8
    ) == []

    paged = _Session(
        [
            {"items": [_item("pay_a"), _item("pay_b")]},
            {"items": [_item("pay_c")]},
        ]
    )
    items = RazorpayReconClient(
        "key", "secret", session=paged
    ).fetch_settlement_recon(2026, 8, count=2)
    assert [item["entity_id"] for item in items] == ["pay_a", "pay_b", "pay_c"]
    assert [params["skip"] for params in paged.params] == [0, 2]


def test_canonical_mapping_preserves_direction_and_settlement_date():
    refund = RazorpayReconClient.to_canonical(
        _item("rfnd_1", debit=2500, credit=0)
    )
    payment = RazorpayReconClient.to_canonical(_item("pay_1"))

    assert refund.amount == -25
    assert payment.amount == 25
    assert refund.txn_date == date(2026, 1, 1)
    assert refund.fees_deducted == 0.5


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"items": None},
        {"items": [{}]},
        {"items": [{**_item("bad"), "debit": 2500, "credit": 2500}]},
    ],
)
def test_malformed_success_payload_fails_loudly(payload):
    client = RazorpayReconClient("key", "secret", session=_Session([payload]))
    with pytest.raises(RazorpayPayloadError):
        client.fetch_settlement_recon(2026, 8)
