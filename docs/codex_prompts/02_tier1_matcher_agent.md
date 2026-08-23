# Codex prompt — Phase 2: Tier 1 Deterministic Matcher agent

Fresh session. No subagents — this task is small and sequential by nature.

---

You are the **Tier 1 Matcher agent** for Parity. Read `AGENTS.md` first
— rule 2 (zero false positives) governs this entire phase. Then read PRD
Section 5 ("Matching engine design") and Section 8 (Phase 2 row).

**What already exists:** `data/holdout/` is frozen (verify
`HOLDOUT_HASH.txt` exists and matches before you start — if it doesn't,
stop and report it, don't regenerate the data yourself). `config/schema.py`
has `CanonicalRecord` and `MatchDecision`.

**Your job:**

1. Write `engine/normalize.py` — loads `bank_statement.csv` and
   `internal_ledger.csv`, maps each row into `CanonicalRecord` (source
   field set accordingly).
2. Write `engine/tier1_deterministic.py` — for every bank record, look for
   a ledger record with:
   - exact `reference` match, AND
   - `amount` within ±₹1 (rounding only, nothing else), AND
   - `txn_date` within the real settlement cycle window (see
     `apply_timing_lag`'s bounds in `exception_taxonomy.py` for what
     "expected" lag looks like — Tier 1 should accept only the *expected*
     T+2/T+7 window, not arbitrary lag; anything outside that expected
     window is Tier 2's problem, not Tier 1's).
   Anything not meeting all three exactly is left unmatched — passed
   through to Tier 2, never guessed on here.
3. Every match produced must be a `MatchDecision` with `tier=1` and a
   `rationale` string stating the exact reference/amount/date values that
   matched.
4. Write `tests/test_tier1.py` against the held-out set: assert match rate
   is between 55-70% (the clean + timing-lag-within-window records), and
   assert **zero** false positives — cross-check every Tier 1 match against
   `truth.json`'s `true_id` linkage.

**Exit gate:**
```
pytest tests/test_tier1.py -v
```
must show match rate in the 55-70% band and 0 false positives. If match
rate is higher than 70%, check whether you've accidentally loosened the
tolerance windows — that's the most common way this rule gets violated
without anyone noticing.

**Do not** touch `data/`, or start writing Tier 2 logic — leave everything
Tier 1 doesn't resolve untouched for the next phase.

Report back: match rate, false positive count (must be 0), and which
exception types Tier 1 correctly left for Tier 2 vs. any it shouldn't have.
