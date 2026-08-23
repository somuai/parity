# Codex prompt index — Parity

Run each phase as a **fresh Codex session**, scoped to that phase's prompt
file only. Don't carry conversation context between phases — narrow context
in, a checked artifact + report out. This is the sub-agent discipline
applied at the session level, on top of the in-session subagents some
phases spawn internally (noted below).

| Phase | Prompt file | Review level | Subagents? | Exit gate |
|---|---|---|---|---|
| 0 — Setup | `00_phase0_setup.md` | Review everything | No — tiny task | Live API call succeeds |
| 1 — Data layer | `01_data_engineer_agent.md` | Lighter touch OK (contained, well-tested pattern) | Optional, 2 parallel (one-to-many / many-to-one) | Taxonomy coverage validator passes, hash written |
| 2 — Tier 1 matcher | `02_tier1_matcher_agent.md` | Lighter touch OK | No — deliberately small | ≥55% match rate, zero false positives |
| 3 — Tier 2 matcher | `03_tier2_reasoning_agent.md` | Review everything (LLM-in-the-loop code deserves it) | Yes, 3 parallel (amount/timing signal, semantic signal, LLM adjudicator) | ≥90% cumulative match rate, all decisions grounded |
| 4 — Audit + hosted app + observability | `04_audit_observability_agent.md` | Review everything | Yes, 3 parallel (audit/exception book, FastAPI backend, Blade frontend) | Full run reproducible, budget ceiling enforced, live Render URL responds |
| 5 — Hardening review | `05_hardening_review_agent.md` | Review everything, read-only pass | Yes, 6 parallel (security / correctness / race conditions / missing tests / API compat / maintainability) | Prioritized report produced, no edits yet |
| 6 — Docs + repro | `06_docs_pitch_agent.md` | Lighter touch OK | No | Fresh clone reproduces every pitch number |

**On the "Review level" column, and why it says this instead of a specific
flag name:** an earlier version of this table pinned exact
`approval_policy` values (`untrusted`, `on-failure`, etc.) — values your own
Codex build had confirmed as valid in one session, then rejected outright
as an unsupported *field* in a later session ("approval_policy is no longer
supported; remove this setting"). That's the config schema changing
between sessions, not a mistake to re-guess a third time. Pinning a
fast-moving field in a committed table just breaks again the same way next
time it changes.

The durable instruction instead: **use whatever your current Codex build's
approval-control flag actually is** (run `codex --help` to check — the most
recently confirmed example was `--ask-for-approval on-request` alongside
`--sandbox workspace-write`, but verify before trusting that) — set to the
most conservative option your version offers ("review everything") for
Phases 0, 3, 4, and 5, and looser ("lighter touch OK") for Phases 1, 2, and
6 once you've watched them run correctly once. Never use a full-auto /
no-approval mode on this repo — AGENTS.md rule 6 (money-adjacent code
shouldn't self-approve its own edits).

**Subagent discipline** (per OpenAI's own guidance): only spawn subagents
for genuinely parallel, independent work — never for small tasks, since
subagents burn more tokens than a single-agent run. Phases 3, 4, and 5
below spawn them because the sub-tasks truly don't depend on each other;
Phases 0, 2, and 6 don't, because splitting them would just add token
overhead for no speed gain.

The hard rules that matter across every phase already live in `AGENTS.md`
directly — that's the correct place for them, confirmed against Codex's
actual docs. (An earlier draft said to "seed Codex's memory feature" with
these first; that described a feature that doesn't work that way — Codex's
Memories are auto-generated background session summaries, off by default,
not something you manually seed. Nothing to do differently, just don't
look for that step.)

Phase 5's 6 parallel subagents need `[agents] max_threads` in
`.codex/config.toml` set above the default of 6 — already done (set to 8)
so that phase doesn't hit the ceiling with zero headroom.

**Want to run Phases 2, 3, and 4 at the same time instead of one after
another?** See `PARALLEL_EXECUTION.md` — it covers the git worktree setup,
which parts of Phase 3/4 can develop against mocks before Phase 2 is done,
and the integration session that has to happen before Phase 5.
