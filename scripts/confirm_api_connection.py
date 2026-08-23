#!/usr/bin/env python3
"""
Phase 0 exit gate: confirm the Settlement Recon API is reachable with your
test-mode keys before any matching code gets written.

Usage:
    cp .env.example .env          # fill in your test-mode keys
    pip install -r requirements.txt
    python scripts/confirm_api_connection.py

Expected output: a count of settlement line items for the current month
(likely 0 if your test account has no simulated settlements yet — that's
fine, a 200 response with an empty list still confirms the connection).
"""
import sys
from datetime import date
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, ".")
from clients.razorpay_client import RazorpayReconClient  # noqa: E402


def main():
    today = date.today()
    try:
        client = RazorpayReconClient()
    except RuntimeError as e:
        print(f"[FAIL] {e}")
        sys.exit(1)

    try:
        items = client.fetch_settlement_recon(year=today.year, month=today.month)
    except Exception as e:
        print(f"[FAIL] API call raised: {e}")
        print(
            "Check: (1) keys are TEST mode, not live — test keys start with "
            "rzp_test_. (2) your Razorpay account has test-mode simulated "
            "activity enabled. (3) network access to api.razorpay.com."
        )
        sys.exit(1)

    print(f"[OK] Connected. {len(items)} settlement line item(s) for {today.year}-{today.month:02d}.")
    if items:
        print("Sample item keys:", list(items[0].keys()))
    print("\nPhase 0 gate: PASSED. Proceed to Phase 1 (data layer).")


if __name__ == "__main__":
    main()
