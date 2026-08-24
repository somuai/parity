# Parity architecture — what was built

This document describes the submitted system, not the proposal-era target.
The measured path is a labeled, two-source reconciliation between a synthetic
bank statement and internal ledger. A strict Razorpay test-mode client is a
separate connectivity gate; its unlabeled output is not included in the
precision/recall claim.

## Pipeline

```text
data/holdout/bank.csv ───┐
                         ├─> CanonicalRecord validation + normalization
data/holdout/ledger.csv ─┘                  │
                                            ▼
                              Tier 1 deterministic matcher
                           exact reference + amount/date bounds
                              │ matched       │ residual
                              ▼               ▼
                       grounded decision   Tier 2 candidate grouping
                                              │
                           ┌──────────────────┼──────────────────┐
                           ▼                  ▼                  ▼
                     amount/timing      semantic MiniLM     reference fuzzy
                     Python signals       embedding            signal
                           └──────────────────┬──────────────────┘
                                              ▼
                              Python group-sum/exception checks
                                      (before the LLM)
                                              ▼
                               tiered Groq JSON adjudication
                              fast 20B → reasoning 120B/fallback
                                              ▼
                                  confidence fusion + bands
                               ≥.90 accept | .60–.90 surface
                                      <.60 exception
                              ┌───────────────┴───────────────┐
                              ▼                               ▼
                       MatchDecision                   ExceptionRecord
                              └───────────────┬───────────────┘
                                              ▼
                         structural truth grader + SQLite audit trail
                              │                              │
                              ▼                              ▼
                  reason-coded exception JSON       current-run JSON
                              └──────────────┬───────────────┘
                                             ▼
                              FastAPI + React/Razorpay Blade
                                  one free Render service
```

## Contracts and fail-closed behavior

`config/schema.py` is the single record/decision contract. Identifiers are
trimmed, blank optional strings normalize to missing, and money remains
`Decimal` rather than binary floating point.

Tier 1 accepts only unambiguous pairs. It rejects zero amounts, opposite
signs, blank references, duplicate candidate references, and records outside
the configured amount/date bounds. Every accepted pair stores the exact
reference, rupee delta, and date delta in its rationale.

Tier 2 receives only residual records. Numeric signals distinguish exact/FX
rounding, bounded fee deductions, and the conjunctive partial-refund pattern.
For one-to-many and many-to-one groups, Python computes the totals and applies
Tier 1's ₹1.00 tolerance before any model request; a failing group cannot be
promoted by prose. MiniLM runs from a pinned model revision. If semantic
evidence is unavailable, fusion discounts that signal instead of inventing a
neutral value.

The adjudicator receives actual record fields and signal values inside an
explicit untrusted-data boundary, uses provider-enforced JSON structure, and
has a per-run call/token budget checked before each request. It retries
eligible 429/transport failures with backoff, escalates uncertain fast-model
answers, and routes exhausted or malformed cases to a specific exception.
Reasoning text is not requested or persisted.

## Evaluation integrity

The evaluator requires the stored and computed held-out hashes to equal the
literal submission hash before reporting any metric. A credited match must:

- contain known, unique source record IDs;
- contain at least one bank and one ledger record;
- map both sides to the same resolvable truth transaction; and
- not claim the same truth transaction twice.

Single-sided orphan decisions and unknown or duplicated IDs are false
positives. Precision, recall, match rate, and false-positive cost therefore
come from structure and `truth.json`, not from a decision's self-reported
label.

The canonical live artifact records one fixture-free run with real embeddings
and Groq responses. `make demo` does not pretend to be a new provider run: it
verifies the hash, reruns Tier 1, regrades the captured Tier 2 decisions, and
republishes all audit/results. It also hashes the complete ordered outcome and
evidence set, so the reproducibility check detects changed decisions even when
the aggregate match rate stays constant. `make eval-tier2-live` is the
explicit command that makes new external calls and replaces the canonical
artifact only after a valid complete run.

## Audit, reporting, and app

Every source row is covered by a run-scoped SQLite audit entry. Exact coverage
checks fail on missing, unexpected, or multiply audited record IDs. Match and
exception rows retain their tier, confidence, signal payload, backend/model,
and grounded rationale.

The exception book groups entries by specific reason code. It publishes
evidence-supported leakage separately from review-only exposure; the UI reads
those server-computed totals rather than recalculating them client-side.

FastAPI serves summary, records, record drill-down, rerun, and health routes.
It also serves the compiled React application from the same process. The UI
uses `@razorpay/blade` theme tokens for confidence states and spacing. The
rerun control performs two canonical replays and compares full outcome
digests.

## External integrations and boundaries

- **Razorpay:** `make confirm-api` authenticates against the test-mode
  Settlement Recon endpoint and validates pagination, empty lists, currency,
  direction, integer minor units, IDs, and settlement timestamps. This is a
  connectivity/contract check, not part of the labeled two-source grade.
- **Groq:** used only by an explicit live refresh. The submitted canonical run
  used `openai/gpt-oss-20b` as the fast tier and
  `openai/gpt-oss-120b` as the reasoning tier.
- **Hugging Face:** the MiniLM model revision is pinned; the canonical replay
  does not redownload it.
- **Render:** one free web service; secrets are entered in Render and marked
  `sync: false`. The instance sleeps after 15 minutes idle.

## Reproducible result boundary

The checked-in claim is tied to `results/canonical_eval.json`, the immutable
held-out hash, and the direct dependency pins. It does not claim a production
three-way Razorpay reconciliation, automatic remediation, durable hosted
storage, or stable results from a brand-new live provider run during a
capacity incident.
