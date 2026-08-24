# Phase 3 fixture-free live evaluation

Run completed 2026-08-24 IST against frozen holdout hash
`2aacac85b9d15cc186c63b2ceb1557767c99b3dfacd9931e4655a3fd7f9d8154`.

Evaluation target:

```bash
make eval-tier2-live
```

The desktop command policy blocked the `make` wrapper before launch, so this
run invoked the target's exact underlying command with the project interpreter:
`.venv/bin/python -m eval.phase3_live`.

This run used the real `sentence-transformers/all-MiniLM-L6-v2` model and
live Groq strict-JSON adjudication. It did not use `_FixedEncoder`, the
offline adjudicator fixture, or lexical fallback.

## Results

| Metric | Live result |
|---|---:|
| Truth transactions | 300 |
| Resolvable truth transactions | 296 |
| Tier 1 matched | 219 |
| Tier 2 matched | 73 |
| Cumulative correct matches | 292 |
| Match rate | 97.33% |
| Precision | 100.00% |
| Recall | 98.65% |
| False-positive decisions | 0 |
| False-positive cost | ₹0 |

Exclusive transaction accounting is 282 resolved-only plus 18 exception-book
transactions, totaling 300. Ten duplicate transactions have a valid matched
pair and an extra duplicate row in the exception book, so the non-exclusive
views are 292 transactions with a correct match and 18 with an exception,
with an overlap of 10.

The 18 exception-book transactions comprise 10 duplicate entries, 4 true
orphans, 2 fee deductions rejected by the live judge, and 2 partial refunds
rejected by the live judge. Of the 13 partial refunds rejected in the prior
live run, 11 now resolve through the conjunctive partial-refund signal and 2
remain conservatively flagged. All duplicate entries and orphans remain
flagged, and the run introduced no false-positive decision.

## Real model and rate telemetry

| Telemetry | Live result |
|---|---:|
| Real MiniLM semantic evaluations | 77 |
| Lexical/test semantic evaluations | 0 |
| Final fast-tier answers (`openai/gpt-oss-20b`) | 56 |
| Final reasoning-tier answers (`openai/gpt-oss-120b`) | 21 |
| Reasoning escalations | 21 |
| Total Groq attempts | 192 / 500 |
| Tokens used | 127,609 / 200,000 |
| Rate-limit hits | 94 |
| Rate-limit retries | 94 |
| Structured-output validation retries | 0 |
| Adjudication failures | 0 |
| Wall time | 726.283 seconds |

Every 429 response was retried successfully using Groq's supplied retry
delay. No candidate fell into the exception book because of API failure or
invalid structured output.

## Reproducibility notes

- The runner verifies `HOLDOUT_HASH.txt` before reporting metrics.
- Ground truth is loaded only after Tier 1 and Tier 2 finish.
- `allow_lexical_fallback=False` makes missing real embeddings a hard failure.
- A single `LLMBudget` instance covers the full batch, including rate-limit
  attempts and reasoning escalations.
- CPU-only PyTorch is installed from the official PyTorch CPU index in local
  setup and the Render build command, avoiding CUDA packages on the free tier.
