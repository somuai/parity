# Parity — five-minute pitch script

All figures below come from the fixture-free live run captured on 2026-08-24
in `results/canonical_eval.json`. Do not substitute proposal-era numbers.

## 0:00–0:45 — The problem

“Finance teams still reconcile bank receipts against their own ledger by
scanning rows and guessing which differences matter. Parity is a restrained
financial investigator: it finds matches it can support and flags everything
else with a specific reason. It never moves money, posts an entry, or claims
to recover funds.”

“For this evaluation I froze 300 labeled truth transactions, represented by
628 bank and ledger source records. The hash is checked before a metric can be
reported, so tuning cannot silently replace the test.”

## 0:45–1:50 — Architecture walkthrough

Show `docs/architecture.md`.

“Tier 1 is deliberately strict: exact normalized reference, bounded rupee
delta, and settlement-window timing. It found 219 matches. Blank references,
zero amounts, sign mismatches, and ambiguous duplicate references fail
closed.”

“The residual 77 candidates go through independent numeric, timing,
reference, and real MiniLM semantic signals. Group arithmetic is performed in
Python before the model. Groq first tries the fast 20-billion-parameter tier
and escalates uncertain cases to the 120-billion reasoning tier. The response
is schema-constrained, budgets are checked before every call, and every final
rationale cites the real records and signal values.”

“The Razorpay test-mode client is a strict live connectivity gate. It is not
mixed into the labeled bank-versus-ledger accuracy claim.”

## 1:50–2:45 — Reproduce the live result

Run:

```bash
make demo
```

“This verifies the frozen hash, reruns deterministic Tier 1, regrades the
captured fixture-free Tier 2 decisions, and republishes the audit and exception
reports. It is deterministic and makes zero new LLM calls. The explicit
network-dependent refresh command is `make eval-tier2-live`.”

Point to the terminal and app summary:

“The result is 272 of 300 truth transactions matched: 219 by Tier 1 and 53 by
Tier 2. That is a 90.67% match rate, 100.00% precision, and 91.89% recall over
296 resolvable truths. There were zero false-positive decisions, so the
false-positive cost estimate is ₹0.00.”

“The fixture-free run processed 628 source records in 582.706 seconds, or
1.078 records per second. It used 207 of the 500-call ceiling and 89,966 of
the 200,000-token ceiling.”

## 2:45–4:05 — Lead with the exception book

Open the leak-versus-review panel, then a duplicate entry.

“Parity flagged 13 entries with evidence-supported leakage totaling
₹12,428.63. Separately, it flagged 25 review-only entries totaling ₹5,356.66.
I do not blend those figures: the second number is attention exposure, not a
claim that money was lost.”

“There are 38 source-level exception entries representing 37 truth
transactions. The full accounting is 263 matched-only truths plus 37 truths
in the exception book, exactly 300. Nine duplicate cases appear in both views
because Parity matched the legitimate pair and separately flagged the extra
duplicate row.”

Click a matched partial-refund record such as transaction 0001.

“Here the nominal amounts are ₹410.79 and ₹287.55, a ₹123.24 difference. The
system does not wave that away: it cites a 0.7000 refund ratio, perfect 1.0000
reference similarity, 0.0000 timing delta, 0.7528 embedding similarity, and a
0.6975 fused confidence. That is accepted but surfaced, not hidden as an
ordinary exact match.”

## 4:05–4:40 — A failure handled gracefully

Open a provider-unavailable exception from the current report.

“The live run hit Groq's free-tier limits 140 times and performed 61 rate-limit
retry attempts. Thirteen candidates still could not obtain a valid answer.
They were not guessed into the match total: each landed in the exception book
with the Python arithmetic and available signal evidence preserved. That
conservatism is why precision stayed at 100%.”

“The reproducible demo uses the validated captured outcome, so a judge does
not inherit today's external rate-limit state. A fresh live refresh remains
available, explicit, and budget-bounded.”

## 4:40–5:00 — Close

“Parity makes verification capacity visible: 272 grounded matches, an honest
reason-coded remainder, ₹12,428.63 of evidence-supported leakage kept separate
from review-only exposure, and zero false-positive cost on the frozen set. The
hosted app lets you inspect any record rather than trust a headline number.”

Open [https://parity-1go2.onrender.com](https://parity-1go2.onrender.com).
Mention that Render's free service can take 30–60 seconds to wake after 15
minutes idle.

## Number traceability

| Pitch figure | Canonical source |
|---|---|
| 300 truth, 296 resolvable, 628 source rows | `results/canonical_eval.json` → `report`; held-out CSV row counts |
| 219 Tier 1, 53 Tier 2, 272 total | `report.tier1_matched_truth_transactions`, `tier2_matched_truth_transactions`, `matched_truth_transactions` |
| 90.67%, 100.00%, 91.89%, ₹0.00 | `report.match_rate`, `precision`, `recall`, `false_positive_cost_inr` |
| 582.706 s, 1.078 records/s | `report.elapsed_seconds`; 628 divided by elapsed time |
| 207/500 calls, 89,966/200,000 tokens | `report.llm_*` and `budget` |
| 13 / ₹12,428.63 leakage | `results/exception_book.json` → `leakage` |
| 25 / ₹5,356.66 review-only | `results/exception_book.json` → `non_leakage` |
| 263 + 37 accounting; 9 overlap; 38 entries | `report.resolved_only_transactions`, `exception_book_transactions`, `matched_and_exception_overlap`, `tier2_exception_rows` |
| 140 rate-limit hits, 61 retries, 13 adjudication failures | `report.rate_limit_hits`, `rate_limit_retries`, `adjudication_failures` |
| Partial-refund example values | first entry of `report.example_rationales` |
