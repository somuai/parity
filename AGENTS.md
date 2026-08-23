# AGENTS.md — Parity

Persistent instructions for every Codex session on this repo. Full spec is
`PRD.md` — read the relevant section before starting any phase, don't work
from this file alone.

## Goal (why this repo exists)

Close one finance-ops reconciliation loop across a 50+ record batch, report
a measured match rate and precision/recall against a held-out set, and
produce an honest exception book for anything unresolved. Every claim in
the final pitch must be reproducible by re-running the repo, not asserted.

## Hard rules (apply in every phase, no exceptions)

1. **Never regenerate or edit anything under `data/holdout/` once
   `HOLDOUT_HASH.txt` exists.** The eval harness must verify the hash before
   reporting any metric. If a phase needs different test data, add a new
   file — do not touch the frozen set. Regenerating it silently invalidates
   every number downstream.
2. **Tier 1 (deterministic matcher) must have zero false positives.** It is
   allowed to under-match (leave things for Tier 2) but never allowed to
   guess. If a change to Tier 1 raises its match rate but introduces even
   one false positive against the held-out labels, revert it.
3. **Every match decision — Tier 1 or Tier 2 — must carry a rationale
   referencing the specific signal values that produced it.** An
   unexplainable match is treated as a wrong match, per the PRD's grounding
   rule.
4. **Every exception book entry needs a specific reason code**, never a
   generic "could not match." If you can't determine a specific reason,
   that's a bug in the matcher, not an acceptable exception entry.
5. **Verb discipline in all docs/pitch copy: Parity *finds* and *flags*,
   never *recovers* or *resolves on the merchant's behalf*.** It's an
   investigator, not an actor — see PRD Section 1 (non-goals).
6. **Stay inside your phase's file scope** (see each phase prompt in
   `docs/codex_prompts/`). Don't fix something in a later phase's files
   because it's convenient — flag it in your report instead.
7. **Respect the budget ceilings in `.env`** (`LLM_CALL_BUDGET_PER_RUN`,
   `TOKEN_BUDGET_PER_RUN`). Any code that calls an LLM must check remaining
   budget first and fail loudly, not silently truncate, if exceeded.
8. **Everything in this build runs on free tiers — keep it that way.**
   Groq (Tier 2 adjudicator), Razorpay test mode, and Render (hosting) are
   all free, but each has real limits (Groq's rate limits, Render's free
   service sleeping after 15 min idle with no persistent DB). Don't
   introduce a dependency that quietly requires a paid tier — check before
   adding a new service or library.

## Conventions

- Python 3.12, pydantic v2 models in `config/schema.py` are the single
  source of truth for record shape — extend, don't duplicate.
- Every new module gets a matching test in `tests/`.
- Commit messages reference the phase (`[Phase 2] ...`).

## A correction on Codex's "Memories" feature

An earlier version of this file said to "seed Codex's memory feature"
with the five rules below before starting. That instruction described a
mechanism that doesn't exist: Codex's Memories feature is off by default,
and when on, it's Codex *auto-summarizing prior sessions* in the
background and writing that to `~/.codex/memories/` — there's no command
to manually inject specific facts into it. OpenAI's own docs are explicit
that required rules belong in AGENTS.md, not memory, since memory is a
generated recall layer, not a source of truth. Good news: the five rules
below already live in this file (rules 1-8 above), which is the actually-
correct place for them. Nothing to do differently here — just don't go
looking for a "seed memory" step, because it isn't a real one.

## Phase index

See `docs/codex_prompts/INDEX.md` for the full phase table, recommended
approval policy per phase, and which phases use subagents.
