# Codex prompt — Phase 4: Audit, Hosted App & Observability agent

Fresh session. **Spawns 3 subagents in parallel** — audit/exception-book,
the FastAPI backend, and the Blade/React frontend are independent
consumers of Tier 1+2's output, touching different files. Deployment
happens after all three merge, by the coordinator, not a subagent (it's a
one-shot sequential step, not parallelizable).

---

You are the **Audit, Hosted App & Observability agent** for Parity,
coordinating three subagents. Read `AGENTS.md` first, then PRD Section 6
(evaluation & observability) and Section 8 (Phase 4 row).

**Launch this session with network access enabled** (`npm install` for
the frontend, and the actual Render deploy step, both need it):
```
codex --sandbox workspace-write -c sandbox_workspace_write.network_access=true
```

**Context:** Tier 1 and Tier 2 (Phases 2-3) now produce `MatchDecision` and
`ExceptionRecord` objects for every held-out record. This phase makes that
output auditable, reportable, cost-bounded, and — new — actually visitable
by a judge at a live URL, not just screen-recorded. No Streamlit: this is a
real FastAPI backend plus a React frontend built with Razorpay's own
Blade design system (`@razorpay/blade`, MIT-licensed, `npm i @razorpay/blade`),
deployed free on Render.

**If you're running this in parallel with Phases 2/3** (separate worktree,
neither merged yet): `config/schema.py`'s `MatchDecision` and
`ExceptionRecord` are already frozen from Phase 0 — construct a handful of
representative mock instances yourself (a few auto-accepts, a few
exceptions across different reason codes) and build all three subagents
against those. Note in your report exactly which parts were built against
mocks so the integration session knows what still needs re-verifying
against real data.

**Spawn 3 subagents in parallel:**

**Subagent A — Audit trail & exception book** (`engine/audit.py`,
`eval/exception_book.py`)
- `engine/audit.py`: persist every `MatchDecision` and `ExceptionRecord`
  with a full trail back to source record IDs — SQLite is enough, no need
  for anything heavier at this scale. Every entry must be queryable by
  record ID, so "why did record X get matched/flagged" has a real answer.
- `eval/exception_book.py`: generate the exception report — grouped by
  `reason_code`, each entry showing the specific reason detail (AGENTS.md
  rule 4 — no generic reasons allowed through). Separately total
  `estimated_amount_at_risk` for entries that represent real leakage
  (duplicate entries, unclaimed refunds) vs. entries that don't (timing
  lag, FX rounding) — these must NOT be summed together into one number;
  the PRD's pitch (Section 2) depends on keeping "real leakage" separate
  from "just needs a human eyeball." Output as JSON — this is what the
  backend subagent will serve.

**Subagent B — FastAPI backend** (`app/main.py`, `app/api/`)
- Thin API layer over the existing `engine/` and `eval/` modules — no new
  matching logic here, just endpoints:
  - `GET /api/summary` — match rate by tier, leakage vs. non-leakage
    totals (from Subagent A's exception book), current budget spend.
  - `GET /api/records` — every held-out record with its confidence band
    and tier, for the scatter view.
  - `GET /api/records/{id}` — one record's full signal breakdown (amount/
    timing/semantic scores) and the adjudicator's rationale, for the
    drill-down view.
  - `POST /api/rerun` — re-triggers the held-out batch and returns both
    the new and previous run's match rates, for the reproducibility check.
  - `GET /api/health` — plain liveness check (used by the deploy step
    below to confirm the Render service is actually up, not just building).
- No database needed: read/write precomputed JSON under `data/holdout/`
  and a `results/` directory — Render's free Postgres expires after 30
  days and this app doesn't need persistence beyond one deploy cycle.
- Mount the frontend's built static files (see Subagent C) from this same
  FastAPI app with `StaticFiles`, so the whole thing is **one** Render
  service, not two — simpler, no CORS to configure, fewer free-tier slots
  used.

**Subagent C — Frontend** (`frontend/`, React + `@razorpay/blade`)
- `npm i @razorpay/blade` (MIT-licensed, real Razorpay design system — not
  a color-matched imitation). If Codex has the Blade MCP server available
  (`npx -y @razorpay/blade-mcp@latest`, see Razorpay's own MCP docs), use
  it to generate Blade-compliant components directly instead of
  hand-rolling markup against the docs.
- **Every color, gradient, and spacing value must come from Blade's own
  theme tokens, never hand-copied hex codes from looking at the RazorSense
  page.** Blade ships real token files at `packages/blade/tokens/theme` in
  the `razorpay/blade` repo — at least two named themes exist
  (`grayTheme`, `midNightTheme`) — consume these through
  `BladeProvider`/`bladeTheme` (already wired in `frontend/src/main.jsx`)
  and reference token names in components, not literal values. This is
  what makes "matches RazorSense exactly" a true claim instead of an
  approximation — if Blade updates its palette, this stays correct
  automatically.
- Five views, each earning its place because it makes the system's
  reasoning visible rather than just asserting a result — this is the
  whole point of hosting it live instead of a screen recording:
  1. **Confidence scatter** — every record as a colored dot by confidence
     band. RazorSense's own emotional-state language (Calm / Joyful /
     Caution / Regret) maps naturally onto match confidence — use it
     deliberately rather than inventing a new color scheme: high
     confidence auto-match reads as Calm/Joyful, medium as Caution, an
     exception as Regret. Pull the actual colors for each state from
     Blade's tokens, not a guessed equivalent. This is a real reuse of
     Razorpay's own design system logic, not a coincidence to gloss over.
  2. **Click-to-explain drill-down** — select any record (calls
     `/api/records/{id}`), show the three signal scores as a small bar
     chart plus the adjudicator's grounded one-line rationale.
  3. **Live budget meter** — LLM calls/tokens used vs. ceiling (from
     `/api/summary`).
  4. **Leak vs. non-leak split** — two prominent numbers, not one blended
     percentage, pulled directly from `/api/summary` — don't recompute the
     split client-side, or the two could silently disagree.
  5. **Reproducibility check** — a button hitting `POST /api/rerun`,
     displaying both runs' match rates side by side with a pass/fail
     badge.
- Build output (`npm run build`) lands where Subagent B's `StaticFiles`
  mount expects it — coordinate the path with Subagent B rather than
  guessing.

**After all three report back, you (coordinator) do the integration and deployment:**

1. Verify every record produced by Tier 1/2 has a corresponding audit
   entry — nothing should fall through ungrounded.
2. Confirm the budget ceiling actually stops a run: deliberately lower
   `LLM_CALL_BUDGET_PER_RUN` below what the held-out set needs and verify
   it fails loudly rather than silently going over.
3. Write `render.yaml` at the repo root (Render's blueprint format) — one
   free web service, Python runtime, build command installs deps and runs
   `npm run build` in `frontend/`, start command runs the FastAPI app.
4. Deploy: connect the repo on Render (dashboard.render.com > New > Blueprint),
   confirm the free service comes up, and hit `/api/health` on the live
   URL. **This step needs your own Render account and a git remote pushed
   somewhere Render can pull from (GitHub) — Codex can write the config,
   but the actual "connect repo" click happens in Render's dashboard, not
   the CLI.**
5. Note the live URL in `README.md` and mention plainly that the free
   instance sleeps after 15 minutes idle (30-60s cold start on first hit)
   — say this upfront rather than letting a judge think it's broken.

**Exit gate:**
- Full run reproducible from `make demo` locally.
- Budget ceiling test (the deliberate-overload check above) passes.
- Exception book shows the leakage/non-leakage split as two separate totals.
- Live Render URL responds on `/api/health` and the frontend loads and
  renders real data from a real held-out run — not mocked, not localhost-only.

Report back: the leakage total vs. non-leakage total from a real held-out
run, confirmation the budget ceiling test passed, and the live URL.
