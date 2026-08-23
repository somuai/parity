# Codex prompt — Data Engineer agent (Phase 1)

Paste this as a fresh Codex session, scoped to this role only. Don't carry
over context from other phases — narrow context in, a checked artifact out.

---

You are the **Data Engineer agent** for Parity, a financial reconciliation
system. Read `AGENTS.md` first for the hard rules that apply to every phase,
then `PRD.md` Sections 1, 4, and 8 (Phase 1 row) for this phase's context.

**Optional subagent split for step 1:** ONE_TO_MANY (bank-side split) and
MANY_TO_ONE (ledger-side merge) are independent of each other — different
files, no shared state beyond reading the same frozen `truth.json` schema.
If your Codex setup supports it, spawn two subagents in parallel, one per
grouping type, then merge and run the validator yourself once both report
back. If not, do them sequentially in the order below — the work is small
enough either way that this isn't a hard requirement.

**What already exists (don't rebuild, extend):**
- `config/schema.py` — canonical record schema, `ExceptionType` enum
- `clients/razorpay_client.py` — Settlement Recon API wrapper (test mode)
- `scripts/confirm_api_connection.py` — Phase 0 gate, already passing
- `data/generators/exception_taxonomy.py` — shared perturbation helpers and
  the target distribution (300 records across 9 exception types + clean)
- `data/generators/truth_source.py` — generates the shared ground-truth
  transaction set both bank and ledger perturb from
- `data/generators/bank_generator.py` / `ledger_generator.py` — working,
  but with two known gaps (see below)

**Your job, in order:**

1. **Implement real ONE_TO_MANY and MANY_TO_ONE grouping.** Currently these
   are approximated as single rows with a comment marking them incomplete
   (search for `TODO` in `bank_generator.py` and `ledger_generator.py`).
   ONE_TO_MANY: one ledger invoice should correspond to 2-3 separate bank
   settlement rows (e.g. a large payment settled across multiple T+2
   cycles) whose amounts sum to the ledger amount. MANY_TO_ONE: 2-3 ledger
   invoices should net into a single bank settlement row. Update
   `truth.json`'s schema to carry a `group_id` for these cases so the eval
   harness can grade group-level correctness, not just 1:1 matches.

2. **Write a taxonomy coverage validator** (`data/generators/validate_coverage.py`).
   It should load `truth.json`, `bank_statement.csv`, and `internal_ledger.csv`,
   and assert: every exception type in `TARGET_DISTRIBUTION` appears the
   expected number of times, group_ids resolve correctly for the one-to-many/
   many-to-one cases, and no row is silently missing from both sides (which
   would break grading, not test resilience). Fail loudly with a specific
   count mismatch, not a generic assertion error.

3. **Write the freeze/hash step** (`data/generators/freeze_holdout.py`). Once
   coverage validates, compute a SHA-256 hash of the three generated files
   (`truth.json`, `bank_statement.csv`, `internal_ledger.csv`) and write it
   to `data/holdout/HOLDOUT_HASH.txt`. This is what makes the "held-out set
   the tuning process never touched" claim checkable — Phase 2/3 work
   should never regenerate this data, only read it, and the eval harness
   should verify the hash matches before reporting any metric.

4. **Do not touch** `engine/`, `eval/`, or `observability/` — those are
   later phases' scope.

**Exit gate (must pass before this phase is done):**
```bash
python3 -m data.generators.truth_source
python3 -m data.generators.bank_generator
python3 -m data.generators.ledger_generator
python3 -m data.generators.validate_coverage   # must print PASS for every exception type
python3 -m data.generators.freeze_holdout      # writes HOLDOUT_HASH.txt
```

Report back: taxonomy coverage table (expected vs. actual count per
exception type), and the final hash written.
