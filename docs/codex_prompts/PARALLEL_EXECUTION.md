# Parallel execution guide

Why this exists: naively running all 7 phase prompts "in parallel" breaks
the build — Phase 6 needs Phase 5's report, Phase 5 needs everything
merged, and Tier 2's real orchestration needs Tier 1's actual output.
This is the plan for what genuinely parallelizes and what doesn't.

## Sequential, blocking (do these one at a time, in order)

1. **Setup** — `.env` filled in, `codex` picks up `AGENTS.md` and
   `.codex/config.toml` automatically from the repo root.
2. **Phase 0** — API confirmation. Must pass for real before anything else.
3. **Phase 1** — data layer. Nothing downstream can be tested against real
   records until this is done and `HOLDOUT_HASH.txt` exists.

## Genuinely parallel (same time, separate worktrees)

Once Phase 1 is committed and tagged, `config/schema.py`'s
`CanonicalRecord`, `MatchDecision`, and `ExceptionRecord` are the frozen
interface contract everything else builds against. That's what makes the
next three tracks safe to run at once — treat the schema as append-only
during this block; a breaking change to it invalidates all three branches
simultaneously.

```bash
git worktree add ../parity-tier1 -b phase2-tier1
git worktree add ../parity-tier2 -b phase3-tier2
git worktree add ../parity-audit -b phase4-audit
```

- **Worktree A** (`02_tier1_matcher_agent.md`) — builds against real
  held-out data, no dependency on the other two.
- **Worktree B** (`03_tier2_reasoning_agent.md`) — builds and unit-tests
  its three internal subagents against pairs drawn directly from
  `truth.json`, stubbing the "read Tier 1's leftovers" wiring step. The
  prompt file itself now says this — no manual addition needed.
- **Worktree C** (`04_audit_observability_agent.md`) — builds the audit
  trail, FastAPI backend, and Blade frontend against a handful of
  hand-constructed mock `MatchDecision`/`ExceptionRecord` instances. Also
  already noted in the prompt file. Deployment to Render happens after
  merge, not inside this worktree.

Run all three at once — separate terminal tabs, separate `codex` sessions.
They don't touch each other's files, so there's nothing to conflict on
until merge.

## Sequential again (integration onward)

```bash
git checkout main
git merge phase2-tier1 phase3-tier2 phase4-audit
```

**Integration session (new, not one of the 7 phase prompts):** wire Tier
2's real orchestration to Tier 1's actual output, wire the dashboard/audit
trail to real decision flow, run `make demo`, and re-verify every exit gate
against the *real* integrated pipeline — mocked development passing is not
the same claim as integration passing. Treat any gap between the two as a
bug to fix here, not a detail to gloss over in the pitch.

Then, strictly in order:
4. **Phase 5** — hardening review (needs the merged, integrated whole).
5. **Phase 6** — fixes, docs, pitch (needs Phase 5's report and final
   verified numbers).

Clean up worktrees once merged:
```bash
git worktree remove ../parity-tier1
git worktree remove ../parity-tier2
git worktree remove ../parity-audit
```

## Net effect on the clock

Original day-by-day plan (PRD Section 8) was fully sequential, ~14 days.
Parallelizing the Tier-1/Tier-2/audit block compresses this to roughly
Phase 0-1 (~3 days) + the parallel block, bounded by whichever track takes
longest — realistically Tier 2 (~4 days) + integration (~1 day) +
hardening (~1-2 days) + docs (~1-2 days) ≈ 10-12 days, leaving real buffer
before the deadline instead of none.
