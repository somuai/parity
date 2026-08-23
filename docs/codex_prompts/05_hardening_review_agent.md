# Codex prompt — Phase 5: Hardening Review agent

Fresh session. **Spawns 6 subagents in parallel, read-only.** This phase
produces a report, not edits — fixes happen in a follow-up session once a
human has seen the prioritized list.

---

You are running a full hardening review of Parity before submission.
Read `AGENTS.md` first, then `PRD.md` end to end (not just one section —
this pass needs the whole system in view).

Review the entire repo against `main`. Spawn 6 subagents in parallel, each
reviewing the whole codebase through one lens, **none of them editing
files:**

1. **Security regressions** — API keys or secrets ever logged or printed;
   `.env` values reaching version control; the Groq/Razorpay clients
   handling malformed responses safely; the Render env vars set as
   `sync: false` in `render.yaml` rather than committed values.
2. **Correctness bugs** — does Tier 1 actually enforce zero false positives
   under edge cases (empty strings, duplicate references, zero amounts)?
   Does the confidence fusion in `engine/confidence.py` handle a missing
   signal (e.g., embedding model unavailable) by degrading safely rather
   than crashing or silently mis-scoring? Does the deterministic sum-check
   in `engine/adjudicator.py` actually run before the LLM call for
   ONE_TO_MANY/MANY_TO_ONE cases, or has it silently been left to the LLM?
3. **Race conditions / non-determinism** — does re-running `make demo`
   twice on the same frozen held-out set produce identical match rates?
   (It must — anything non-deterministic here undermines the whole
   "reproducible pitch numbers" claim.) Does the frontend's
   reproducibility-check button (Phase 4) actually call `/api/rerun` twice
   and compare, or does it fake the second run?
4. **Missing tests** — which modules in `engine/`, `eval/`, and
   `observability/` have no corresponding test file, or tests that don't
   actually assert against `truth.json` ground truth (a test that always
   passes regardless of correctness is worse than no test).
5. **API compatibility** — does the Razorpay client handle a test-mode
   account with zero settlement activity gracefully (empty list, not a
   crash)? Does `engine/adjudicator.py` handle a Groq rate-limit (429)
   response with actual backoff rather than treating it as a hard failure,
   and does it correctly fail over from `GROQ_MODEL_REASONING` to the
   fallback model if the primary one has been deprecated since Phase 3 was
   built?
6. **Maintainability** — is the file-scope discipline from each phase
   prompt actually respected (e.g., did Phase 3's subagents leak logic into
   files that weren't theirs)? Flag anything that will confuse whoever
   reads this repo cold, including the panel.

**Wait for all six subagents, then produce a single prioritized report** —
severity-ordered, each item naming the specific file/line and why it
matters for a finance-adjacent system specifically (a bug that would be
minor in a to-do app may not be minor here). Do not edit anything in this
session.

**Exit gate:** the report exists, is prioritized, and every item is
specific enough that a follow-up session could fix it without re-deriving
the finding.
