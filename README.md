# Parity

<p align="center">
  <img src="frontend/public/brand/parity-logo-a1.png" width="180" alt="Parity ledger-seal logo">
</p>

Parity is a restrained financial-reconciliation investigator built for the
Razorpay AI Buildathon 2026, Track 04. It compares a frozen bank statement
with an internal ledger, finds matches it can substantiate, and flags the
rest in a reason-coded exception book. It never moves money or acts on a
merchant's behalf.

## Verified result

These are the results of the fixture-free live evaluation captured on
2026-08-24. It used the real MiniLM sentence-transformers encoder and live
Groq adjudication over the immutable held-out set.

| Metric | Fresh live result |
|---|---:|
| Truth transactions | 300 |
| Source records processed | 628 |
| Tier 1 matches | 219 |
| Tier 2 matches | 53 |
| Total matched | 272 |
| Match rate | **90.67%** |
| Precision | **100.00%** |
| Recall over 296 resolvable truths | **91.89%** |
| False-positive decisions / cost | **0 / ₹0.00** |
| Live wall time / throughput | 582.706 s / 1.078 records/s |
| Groq usage | 207 / 500 calls; 89,966 / 200,000 tokens |

The accounting is intentionally explicit: 263 truth transactions are
matched-only and 37 appear in the exception book, so those exclusive sets
sum to 300. Nine duplicate cases appear in both views because the valid
bank/ledger pair is matched while the extra duplicate source row is flagged.
The exception report therefore contains 38 source-level entries representing
37 truth transactions.

The exception book keeps two money figures separate:

| Classification | Entries | Amount |
|---|---:|---:|
| Evidence-supported leakage | 13 | **₹12,428.63** |
| Review-only, not claimed as leakage | 25 | **₹5,356.66** |

The live run encountered Groq free-tier pressure: 140 rate-limit responses,
61 retry attempts, one retried transport error, and 13 candidates ultimately
returned to the exception book rather than guessed. The reported precision
remained 100%.

The frozen hash is
`2aacac85b9d15cc186c63b2ceb1557767c99b3dfacd9931e4655a3fd7f9d8154`.
`make demo` verifies that hash, reruns deterministic Tier 1, regrades the
captured live Tier 2 decisions, and republishes the audit/results. It makes no
new LLM calls. `make eval-tier2-live` is the explicit, network-dependent
command for refreshing the canonical live artifact.

## Hosted app

The FastAPI backend and React frontend are one Render service. The interface
uses Razorpay's open-source Blade design system rather than copied colors.

- **Live app:** [https://parity-1go2.onrender.com](https://parity-1go2.onrender.com)
- **Health:** [https://parity-1go2.onrender.com/api/health](https://parity-1go2.onrender.com/api/health)

Render's free instance sleeps after 15 minutes idle. A first request can take
30–60 seconds to wake; this is expected.

## Quickstart

Prerequisites: Python 3.12, Node/npm, and GNU Make. Razorpay test-mode keys
are required for the connectivity gate. A Groq key is required only for an
explicit live refresh, not for the reproducible canonical demo.

```bash
git clone https://github.com/somuai/parity.git
cd parity
cp .env.example .env
# Add RAZORPAY_TEST_KEY_ID, RAZORPAY_TEST_KEY_SECRET, and GROQ_API_KEY to .env.

make setup
make confirm-api
make demo
```

Expected `make demo` result: 272/300 matched, 90.67% match rate, 100.00%
precision, 91.89% recall, and ₹0.00 false-positive cost.

To run the app locally:

```bash
make run-backend   # http://localhost:8000
make run-frontend  # http://localhost:5173, proxies /api to FastAPI
```

To perform a new live evaluation with real embeddings and Groq calls:

```bash
make eval-tier2-live
```

That command can produce a different conservative match count when Groq's
free-tier capacity is unavailable; failed adjudications are reason-coded
exceptions, never silent matches. The checked-in canonical artifact exists so
the panel can reproduce the submitted claim without depending on a provider's
minute-by-minute availability.

`make confirm-api` validates authentication, pagination, response shape, INR
amount direction, and empty-account behavior for Razorpay's test-mode
Settlement Recon API. The Razorpay feed is not silently included in the
graded precision/recall claim: the labeled evaluation is bank-versus-ledger.

## Status and hardening disposition

| Area | Status |
|---|---|
| Data freeze | Complete; evaluator checks the immutable hash before metrics |
| Tier 1 | Complete; empty references, zero amounts, sign mismatches, and duplicate references fail closed |
| Tier 2 | Complete; grouped arithmetic runs in Python before any LLM call, missing semantic evidence degrades confidence, and provider failures become exceptions |
| Evaluation | Complete; structural truth checks prevent single-sided, duplicated, or unknown record IDs from earning credit |
| Audit and exception book | Complete; run-scoped exact coverage and separate leakage/non-leakage totals |
| Hosted app | Complete; canonical replay powers `/api/rerun`, with an outcome digest comparison rather than a match-rate-only comparison |
| Security/API hardening | Complete for submission blockers; secrets are ignored, Render secrets use `sync: false`, Groq input is delimited as untrusted, and Razorpay responses are strictly validated |
| Phase 5 review | Complete; number-changing and demo-crashing findings fixed |
| Phase 6 reproduction | Complete; a new clone reproduced the canonical outcome digest and every pitch metric |
| Deferred: Razorpay third leg | Connectivity and validation only; a labeled three-source reconciliation claim is not made |
| Deferred: rerun authorization | `/api/rerun` is unauthenticated, but it is now a deterministic, zero-LLM canonical replay; admin auth and durable cooldown remain deployment work |
| Deferred: artifact transactionality | JSON files are atomically replaced and carry run IDs, but the multi-file publication is not one database transaction |
| Deferred: API polish | Explicit FastAPI response models, bundle splitting, and consolidation of the empty `observability/` package are maintainability work |
| Deferred: dependency closure | Direct Python packages, CPU torch, the embedding model revision, and npm lockfile are pinned; the entire transitive Python graph is not hash-locked |
| Deferred: frontend dependency advisories | `npm audit --omit=dev` reports Blade's moderate `ts-deepmerge` advisory; the offered fix downgrades Blade, so this remains documented pending an upstream-compatible release. The separate high advisory is build-time/dev-only |
| Deferred: history cleanup | Phase-boundary file ownership is documented, but published git history will not be rewritten merely to make phase attribution prettier |

## Architecture and evidence

- [Actual architecture](docs/architecture.md)
- [Five-minute pitch script](docs/pitch_script.md)
- [Original product requirements](PRD.md)
- [Canonical live result](results/canonical_eval.json)
- [Current evaluator report](results/current_run.json)
- [Exception book](results/exception_book.json)

## Repository map

```text
config/schema.py                  canonical record and decision contracts
clients/razorpay_client.py        strict test-mode Settlement Recon client
data/holdout/                     immutable labeled bank/ledger evaluation set
engine/tier1_deterministic.py     fail-closed deterministic matcher
engine/tier2_reasoning.py         residual signals, adjudication, fusion
engine/audit.py                   run-scoped SQLite audit trail
eval/phase3_live.py               structural grader and metrics
eval/exception_book.py            reason-coded leakage/review report
app/                              FastAPI API and static frontend host
frontend/                         React + Razorpay Blade interface
results/canonical_eval.json       captured fixture-free live evaluation
```

Parity *finds* and *flags*. It does not claim to recover funds, post entries,
or resolve exceptions on a merchant's behalf.
