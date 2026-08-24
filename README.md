# Parity

Autonomous financial reconciliation investigator — built for the Razorpay AI
Buildathon 2026, Track 04 (AI Finance Controller).

Ingests a real Razorpay test-mode settlement feed, a synthetic bank
statement, and a synthetic internal ledger. Auto-resolves what it can match
with confidence, and produces an honest exception book for what it can't —
with a specific reason for every entry, never a generic catch-all.

Full architecture, data model, and evaluation methodology: see
[`PRD.md`](./PRD.md).

## Status

| Phase | Status | Codex prompt |
|---|---|---|
| 0 — Setup & API confirmation | Scaffolded — run `make confirm-api` with your own test-mode keys | `docs/codex_prompts/00_phase0_setup.md` |
| 1 — Data layer | Truth source + bank/ledger generators working; one-to-many/many-to-one grouping still approximated (TODOs in `data/generators/`) | `01_data_engineer_agent.md` |
| 2 — Tier 1 deterministic matcher | Complete — 219/300 deterministic matches, zero false positives | `02_tier1_matcher_agent.md` |
| 3 — Tier 2 reasoning matcher | Complete — 97.33% cumulative live match rate, 100% precision | `03_tier2_reasoning_agent.md` |
| 4 — Audit trail + hosted app + observability | Implemented locally; Render dashboard connection pending | `04_audit_observability_agent.md` |
| 5 — Hardening review | Not started | `05_hardening_review_agent.md` |
| 6 — Fixes, docs & repro | Not started | `06_docs_pitch_agent.md` |

Run each phase as its own fresh Codex session — see
[`docs/codex_prompts/INDEX.md`](./docs/codex_prompts/INDEX.md) for the full
table, recommended approval policy per phase, and which phases spawn
subagents. Also see [`docs/codex_prompts/PARALLEL_EXECUTION.md`](./docs/codex_prompts/PARALLEL_EXECUTION.md)
for running Phases 2-4 concurrently in separate git worktrees.

## Hosted app

Not a screen recording — a real, clickable app a judge can try themselves.
FastAPI backend, React frontend built with Razorpay's own open-source
**Blade** design system (`@razorpay/blade`, MIT-licensed — the same system
behind RazorSense), deployed free on Render via `render.yaml`.

No Streamlit, no separate frontend host: one FastAPI service serves both
the API and the built frontend static files, which keeps it to a single
free Render web service with no CORS to configure.

**Read before judging a slow first load:** Render's free tier sleeps the
service after 15 minutes with no traffic and takes 30-60 seconds to wake on
the next visit. That's expected, not a bug — worth saying in the pitch
video too, so nobody assumes the link is broken.

**Live URL:** pending the one-time GitHub repository and Render Blueprint
connection. The deployment definition is ready in `render.yaml`; this line
must be replaced with the verified `onrender.com` URL after the dashboard
deploy succeeds.

## Why Groq, not Anthropic, for the Tier 2 adjudicator

Anthropic's API has no ongoing free tier — only a small one-time trial
credit, which a batch reconciliation job would burn through fast. Groq's
free tier is genuinely free indefinitely (no card, rate-limited rather than
credit-limited), so that's what `engine/adjudicator.py` calls. See
`.env.example` for setup.

## Quickstart

```bash
cp .env.example .env        # fill in your Razorpay test-mode + Groq keys
make setup
make confirm-api            # Phase 0 gate — must pass before continuing
make demo                    # verify hash, run real pipeline, write audit/results

# Once Phase 4 lands, run the app locally in two terminals:
make run-backend             # FastAPI on :8000
make run-frontend            # Vite dev server on :5173, proxies /api to it
```

## Repo layout

```
config/schema.py              canonical record schema, shared across all sources
clients/razorpay_client.py    Settlement Recon API wrapper (test mode)
data/generators/              synthetic bank + ledger generation, shared truth source
data/holdout/                 generated data lands here (gitignored except .gitkeep)
engine/                       Tier 1 + Tier 2 matching logic (Phase 2, 3)
eval/                         metrics harness + exception book (Phase 4)
observability/                logging, cost/rate tracking (Phase 4)
app/main.py                   FastAPI backend, serves API + built frontend (Phase 4)
frontend/                     React + Blade UI (Phase 4)
render.yaml                   Render deployment blueprint (Phase 4)
scripts/confirm_api_connection.py   Phase 0 gate
docs/codex_prompts/           scoped prompts for each Codex build-role
```

## Held-out set scope (read before grading match rate)

The gradable, precision/recall-labeled held-out set is a **two-source**
problem: synthetic bank statement vs. synthetic internal ledger, both
perturbed from one shared ground truth (`data/generators/truth_source.py`).
The real Razorpay test-mode settlement feed is a third, **un-labeled** leg
used only for the live demo batch — we can't control or label real API
output, so it's not part of the graded claim. This is a scope decision, not
a limitation we're hiding.
