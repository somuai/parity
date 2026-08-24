# Parity — Autonomous Financial Reconciliation Investigator
**Razorpay AI Buildathon 2026 — Track 04: AI Finance Controller**
Author: Somu (Soumyajit Ghosh) · Deadline: September 5, 2026 · Window: 14 days (Aug 22 – Sep 5)

---

## 0. The brief, verbatim requirements, and the bar

Track 04 asks for an agent that **closes one finance-ops loop across a 50+ record batch of synthetic data, reporting its match rate and the exceptions it could not resolve.** Their stated reason this track exists: verification capacity, not generation speed, is 2026's real bottleneck — reconciliation, settlement, and forecasting are still mostly manual. Example directions listed: multi-source reconciliation, settlement Q&A, cash forecasting, tax-line matching.

The bar, in their words: <cite index="9-1">"Throughput plus measured accuracy plus an honest exception list. One cherry-picked match proves nothing."</cite>

Parity targets the **multi-source reconciliation** direction. Every design decision below is pointed at that one sentence — not at a demo that looks impressive for five minutes, but at a report that survives someone re-running it.

---

## 1. Problem statement

A merchant's money can move through three records that should describe the same events and never quite do:

1. **Razorpay settlement report** (real, via test-mode Settlement Recon API) — what Razorpay says it paid out.
2. **Bank statement** (synthetic) — what actually hit the account.
3. **Internal ledger** (synthetic) — what the business's books say happened.

The submitted, labeled evaluation compares the frozen bank statement with the
internal ledger. Razorpay test mode is implemented as a strict live
connectivity/contract gate, not as a labeled third leg. Parity produces a
matched set with a confidence-scored trail back to source and an exception
book — the entries it refused to guess on, each with a specific reason.

**Non-goals:** no live money movement, no auto-remediation, no conversational interface, no forecasting. This is a verifier, not an actor — that distinction is the whole reason this is Track 04 and not Track 03.

---

## 2. The pitch (what the 5-minute video leads with)

Not only a match-rate percentage. The exception book itself is the story,
because the exceptions that represent evidence-supported leakage are the ones
worth a human's five minutes:

> *"On 300 frozen truth transactions, Parity found 272 grounded matches: a
> 90.67% match rate at 100% precision and 91.89% recall. It separately flagged
> 13 evidence-supported leakage entries totaling ₹12,428.63 and 25 review-only
> entries totaling ₹5,356.66. It did not blend the two figures or guess through
> provider failures."*

Every number in that pitch has to be real, reproducible from the repo, and separable in the report between "true leakage" (money genuinely at risk) and "needs a human eyeball but nothing's actually wrong" (a timing lag, a rounding difference). Conflating the two is the fastest way to lose credibility with a panel primed to distrust a single dramatic figure.

---

## 2.1 Positioning against Razorpay's own ecosystem

Two facts worth building the pitch around, not just the architecture:

- **The Settlement Recon API is a data feed, not a reconciliation engine.** It
  returns settlement data but does no cross-referencing against a merchant's
  own bank statement or internal ledger. The submitted Razorpay client proves
  authenticated, strict ingestion of that feed; integration as a labeled
  third reconciliation leg is explicitly deferred.
- **Razorpay's own Agent Studio announcement states that they want third-party builders creating specialized agents for their ecosystem, and names "automated tax reconciliation tools" as an explicit example.** Parity is a concrete instance of exactly that stated (but not yet shipped) direction — worth saying plainly in the pitch, since it's a real citable claim, not a stretch.

**UI differentiation:** the hosted app (Section 6) is built with `@razorpay/blade`, Razorpay's own open-source, MIT-licensed design system — the same system behind RazorSense — rather than a hand-matched color palette. RazorSense's own emotional-state language (Calm / Joyful / Caution / Regret) maps directly onto match confidence bands, which is a genuine reuse of their design logic, not a coincidence to gloss over in the pitch.

---

## 3. System architecture

```
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ Razorpay Recon    │   │ Bank Statement  │   │ Internal Ledger │
│ API (test mode,   │   │ (synthetic CSV, │   │ (synthetic CSV, │
│ real, live)        │   │ noise-injected) │   │ noise-injected) │
└────────┬─────────┘   └────────┬────────┘   └────────┬────────┘
         └───────────────┬───────┴──────────────┬───────┘
                          ▼                       
              ┌──────────────────────┐            
              │  Ingestion &          │            
              │  Normalization        │  → common schema, currency,
              │  (schema mapper)       │    timezone, ID canonicalization
              └──────────┬───────────┘            
                          ▼                       
              ┌──────────────────────┐            
              │  Tier 1 — Deterministic│  exact ref + amount + date
              │  Matcher               │  (tolerance window)
              └──────────┬───────────┘            
                    matched │ unmatched
                          ▼                       
              ┌──────────────────────┐            
              │  Tier 2 — Residual     │  three-signal fusion:
              │  Reasoning Matcher     │  amount-Δ, timing-Δ, semantic
              │  (embeddings + LLM)    │  similarity → confidence score
              └──────────┬───────────┘            
                 high/med confidence │ low confidence
                          ▼                       ▼
              ┌──────────────────────┐  ┌──────────────────────┐
              │  Confidence & Audit    │  │  Exception Book       │
              │  Trail Store            │  │  (reason-coded,       │
              │  (source-linked)        │  │  human-reviewable)    │
              └──────────┬───────────┘  └──────────┬───────────┘
                          ▼                          ▼
                    ┌────────────────────────────────────┐
                    │   Eval Harness + Observability        │
                    │   (match rate, precision/recall,      │
                    │   throughput, cost, drift alerts)      │
                    └──────────────────┬─────────────────┘
                                       ▼
                    ┌────────────────────────────────────┐
                    │   Hosted App (Render, free tier)      │
                    │   FastAPI + React/Blade — live,       │
                    │   clickable, not a screen recording    │
                    └────────────────────────────────────┘
```

The three-signal fusion in Tier 2 is a direct reapplication of the spatial/frequency/semantic voting pattern from SynthDoc — same fusion-of-independent-signals idea, applied to amount / timing / description similarity instead of pixel-level fraud signals.

---

## 4. Data model

**Common canonical record (post-normalization):**

| Field | Type | Notes |
|---|---|---|
| `record_id` | string | Source-prefixed, e.g. `bank_00042` |
| `source` | enum | `razorpay` \| `bank` \| `ledger` |
| `amount` | decimal | Normalized to INR, signed (credit/debit) |
| `txn_date` | date | Event date in source's own terms |
| `reference` | string | Payment ID, UTR, invoice no. — whatever the source calls it |
| `description` | string | Free-text narration, used for semantic signal |
| `counterparty` | string | Payer/payee name if present |
| `fees_deducted` | decimal, nullable | Only present on settlement/bank rows |

**Exception taxonomy to inject into the synthetic bank + ledger generators** (Razorpay side is real data, so its noise is whatever Razorpay actually returns):

1. Timing lag — settlement date vs. bank credit date offset by the real T+2 / T+7 cycle
2. Fee/adjustment deduction — net ≠ gross, must reconcile against Razorpay's own fee breakdown
3. Partial refund / partial capture
4. Duplicate entry (double-counted settlement line)
5. Missing or typo'd reference ID
6. One-to-many (one ledger invoice split across multiple settlements)
7. Many-to-one (multiple invoices netted into one settlement)
8. FX/currency rounding variance
9. Orphan record — genuinely present in one source only (the true, unresolvable exception)

Held-out labeled set: **300 synthetic truth transactions represented by 628
bank/ledger source rows**, with ground-truth labels frozen and hashed before
Tier-1/Tier-2 development. The Razorpay test-mode command is a live API
connectivity and response-contract check; no unlabeled API rows are counted in
the held-out accuracy claim.

---

## 5. Matching engine design

- **Tier 1 (deterministic):** exact match on `reference` + `amount` (± ₹1 rounding) + `txn_date` (± settlement-cycle window). Target: 55–70% matched, zero false positives — this tier must never guess.
- **Tier 2 (residual reasoning):** for unmatched records, compute three independent signals — amount-delta score, timing-delta score, semantic similarity of `description`/`counterparty` via embeddings — feed all three plus the candidate pair to an LLM adjudicator for a grounded yes/no/uncertain with a stated reason, then fuse into a single confidence score.
- **Confidence bands:** High (≥0.9) → auto-accept with logged rationale. Medium (0.6–0.9) → auto-accept but surfaced in a "review if you have 5 minutes" list. Low (<0.6) → **exception book**, never guessed.
- **Grounding rule:** every Tier-2 decision must cite the exact source record IDs and the signal values that drove it — no decision is accepted without a traceable rationale, because an unexplainable match is functionally the same failure as a wrong one.

---

## 6. Evaluation & observability

**Metrics reported (all computed against the frozen held-out set, never the tuning set):**
- Match rate (% matched, split by tier)
- Precision and recall on the held-out labels
- False-positive cost estimate (₹ sum of any incorrectly auto-matched records — target: as close to zero as the system can prove)
- Throughput (records/second, and wall-clock time for the full batch)
- Exception queue quality (% of exceptions with a specific, correct reason code vs. a generic catch-all)

**Observability, built in from Phase 2 onward, not bolted on at the end:**
- Structured logs for every match decision (record IDs in, signal scores, decision, confidence)
- A live, hosted app (FastAPI backend + React frontend built with Razorpay's own Blade design system, deployed free on Render — not a screen-recorded dashboard) showing match rate, exception queue, and per-tier breakdown, so a judge can visit the actual thing rather than watch a video of it
- Cost/rate tracking: LLM calls per record, token spend per batch, and a hard per-run budget ceiling so Tier 2 can't silently blow through Groq's free-tier rate limits mid-demo
- Drift check: re-running the held-out set after any Tier-2 prompt change must not regress precision — this is the eval gate between phases below

---

## 7. Codex build plan — agents, sub-agents, and roles

Rather than one long Codex session, the build is split into scoped roles, each with its own context, its own acceptance test, and a hard stop if its eval gate fails. This keeps each Codex session small enough to stay reliable and keeps failures contained to one phase instead of cascading.

| Role | Scope | Hands off to next role only if |
|---|---|---|
| **Data Engineer agent** | Synthetic bank + ledger generators, exception injection, held-out set freeze, real Settlement Recon API client | Schema validated, exception taxonomy coverage checklist passes, held-out labels hashed |
| **Tier-1 Matcher agent** | Deterministic exact-match engine | ≥55% match rate on held-out set, zero false positives |
| **Tier-2 Reasoning agent** | Embeddings + LLM adjudicator + confidence fusion | ≥90% cumulative match rate, precision/recall reported, grounding citations present on every decision |
| **Audit & Confidence agent** | Source-linked audit trail, confidence-band routing, exception book generator | Every resolved record traceable to source IDs; every exception has a non-generic reason code |
| **Eval/Observability agent** | Metrics harness, dashboard, cost/rate tracking, drift check | Full metrics report reproducible from a single command; budget ceiling enforced |
| **Docs/Repro agent** | README, architecture doc, pitch script, repo hygiene | A stranger can clone the repo and reproduce the reported numbers in one command |

Each role's Codex session starts from a fresh, scoped prompt (its row above), not the accumulated context of prior sessions — this is the "sub-agent" pattern: narrow context in, a checked artifact out, next role starts clean.

---

## 8. Phase-wise build plan (Aug 22 – Sep 5)

| Phase | Days | Work | Eval gate to proceed |
|---|---|---|---|
| **0 — Setup** | Aug 22 | Repo scaffold, Razorpay test-mode keys, schema contracts frozen, Codex role prompts written | Live test-mode API call to Settlement Recon succeeds |
| **1 — Data layer** | Aug 23–25 | Synthetic generators, exception injection, held-out set frozen + hashed | Taxonomy coverage checklist passes, held-out set untouched by any later tuning |
| **2 — Tier 1** | Aug 26–28 | Deterministic matcher | ≥55% match rate, zero false positives on held-out set |
| **3 — Tier 2** | Aug 29–31 | Fusion matcher + LLM adjudicator | ≥90% cumulative match rate, precision/recall logged, every decision grounded |
| **4 — Audit + Observability** | Sep 1–2 | Exception book, audit trail, dashboard, cost/rate ceilings | Full run reproducible; budget ceiling tested by intentionally overloading it |
| **5 — Hardening** | Sep 3–4 | Full held-out re-run, regression check, README, architecture doc, pitch video | Numbers in the pitch match a fresh clone-and-run |
| **6 — Submit** | Sep 5 | Final repo polish, application submission | — |

No phase starts until the previous one's gate passes — this is the "check limits" discipline: a phase that misses its bar gets fixed before new surface area is added, not patched around later.

---

## 9. Repo & submission checklist

- Public GitHub repo, one-command reproducible run (`make demo` or equivalent)
- README leading with the metrics table, not marketing copy
- Live Render URL in the README, working and reachable — not just a local screen recording
- Architecture doc (this document, trimmed) alongside the repo
- 5-minute pitch video: problem → architecture walkthrough → live app walkthrough (not just a recording — click through it) → exception book walkthrough → one failure handled gracefully
- Held-out set and tuning set clearly separated in the repo structure, so the "honest" claim is checkable, not just asserted

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| Synthetic data reads as unrealistic | Real settlement leg from test-mode API; exception taxonomy grounded in documented production reconciliation patterns |
| Tier 2 LLM cost/rate limits mid-demo | Hard per-run budget ceiling (Phase 4), tested by deliberately overloading it before submission; Groq free-tier limits checked in advance, not discovered live |
| Render free-tier cold start reads as broken | State it plainly in the README and the pitch video — a 30-60s wake-up on first visit is expected, not a bug |
| Scope creep into forecasting/Q&A | Non-goals locked in Section 1; those are separate track directions, not this build |
| Pitch overclaims what the system did | Verb discipline: Parity *finds* and *flags*, never *recovers* — it's an investigator, not an actor |
| Timeline slip | Each phase gate is a hard go/no-go; a missed gate cuts scope in Phase 5, not the eval rigor |

---

## 11. Success criteria (mapped directly to the track's bar)

- **Throughput:** reported records/sec on the full batch, not just "it ran"
- **Measured accuracy:** precision/recall on a held-out set the tuning process never touched
- **Honest exception list:** every unresolved record has a specific, non-generic reason — and the report states this plainly, with no cherry-picked single match standing in for the whole batch
