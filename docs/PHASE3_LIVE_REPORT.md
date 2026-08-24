# Canonical fixture-free live evaluation

This report supersedes the earlier Phase 3 run. The submission canonical was
refreshed after Phase 6 hardening on 2026-08-24 with the exact underlying
command for `make eval-tier2-live`:

```bash
.venv/bin/python -m eval.harness --live
```

It used the real pinned `sentence-transformers/all-MiniLM-L6-v2` encoder for
all 77 residual candidates and live Groq structured-output adjudication. It
used no fixture encoder, offline adjudicator, or lexical fallback. The frozen
hash remained
`2aacac85b9d15cc186c63b2ceb1557767c99b3dfacd9931e4655a3fd7f9d8154`.

## Results

| Metric | Canonical live result |
|---|---:|
| Truth transactions | 300 |
| Source rows | 628 |
| Resolvable truth transactions | 296 |
| Tier 1 matched | 219 |
| Tier 2 matched | 53 |
| Cumulative correct matches | 272 |
| Match rate | 90.67% |
| Precision | 100.00% |
| Recall | 91.89% |
| False-positive decisions / cost | 0 / ₹0.00 |
| Wall time / throughput | 582.706 s / 1.078 rows/s |

Exclusive truth accounting is 263 matched-only plus 37 represented in the
exception book, totaling 300. Nine duplicate truths appear in both
non-exclusive views because the legitimate pair is matched and the extra
source row is separately flagged. There are 38 source-level exception rows.

The exception book separates 13 evidence-supported leakage entries totaling
₹12,428.63 from 25 review-only entries totaling ₹5,356.66.

## Model and provider telemetry

| Telemetry | Canonical live result |
|---|---:|
| Real MiniLM evaluations | 77 |
| Lexical/test semantic evaluations | 0 |
| Final fast-tier answers | 9 |
| Final reasoning-tier answers | 55 |
| Groq attempts | 207 / 500 |
| Tokens | 89,966 / 200,000 |
| Rate-limit hits / retries | 140 / 61 |
| Transport errors / retries | 1 / 1 |
| Capacity fallbacks | 66 |
| Structured validation retries | 0 |
| Adjudication failures routed to exceptions | 13 |

This is an intentionally conservative provider-pressure result. Candidates
that exhausted valid adjudication did not receive a match. The checked-in
`results/canonical_eval.json` captures this live outcome. `make demo` verifies
the hash, reruns Tier 1, and regrades that capture deterministically without
making new provider calls.
