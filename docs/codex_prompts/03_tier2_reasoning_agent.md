# Codex prompt — Phase 3: Tier 2 Reasoning Matcher agent

Fresh session. **Spawns 3 subagents in parallel** — this is genuinely
parallelizable work (three independent signal scorers that don't depend on
each other's output until fusion), which is exactly the case OpenAI's own
guidance says subagents are worth their token cost for.

---

You are the **Tier 2 Reasoning Matcher agent** for Parity, coordinating
three subagents. Read `AGENTS.md` first — rules 2, 3, and 7 all bind this
phase (grounding required, budget ceilings, no false positives even here).
Then read PRD Section 5 and Section 8 (Phase 3 row).

**Launch this session with network access enabled** (the Groq model check
and every adjudicator call need it, and it's off by default):
```
codex --sandbox workspace-write -c sandbox_workspace_write.network_access=true
```

**Context:** Tier 1 has already resolved the clean + in-window-timing-lag
records (see Phase 2's report). Everything else — partial refunds,
duplicates, missing/corrupted references, FX rounding, one-to-many,
many-to-one, and true orphans — lands here.

**If you're running this in parallel with Phase 2** (separate worktree,
Tier 1 not merged yet): don't wait. Develop and unit-test all three
subagents directly against pairs drawn from the frozen held-out set
(`data/holdout/`) — every record has a known `true_id` and exception type
in `truth.json`, so you can construct valid candidate pairs yourself
without needing Tier 1's actual leftover list. Stub the final
`engine/tier2_reasoning.py` orchestration (the part that wires "Tier 1's
unmatched output" through the signals) with a placeholder that reads
directly from `truth.json` instead. Flag this stub clearly in your report
— the integration session after all parallel branches merge will replace
it with the real wiring, and needs to know exactly what's stubbed.

**Spawn 3 subagents in parallel, each scoped to one file, none touching the
others' files:**

**Subagent A — Amount & timing signal** (`engine/signals_numeric.py`)
- Given a candidate bank/ledger pair, compute a normalized amount-delta
  score (0=identical, 1=wildly different) and a timing-delta score against
  the expected settlement cycle.
- Handle FEE_DEDUCTION (net vs. gross should score as *plausibly* matching
  if the delta is consistent with a reasonable fee %, not just any delta)
  and FX_ROUNDING (small deltas should score as near-identical, not
  penalized as if they were real mismatches).
- Output: a pure function, no LLM calls, no side effects. Deterministic and
  unit-testable on its own.

**Subagent B — Semantic signal** (`engine/signals_semantic.py`)
- Given a candidate pair's `description` and `counterparty` fields, compute
  an embedding similarity score (use `sentence-transformers`, a small model
  — this doesn't need a large one for short narration strings).
- Also implement `corrupt_reference`-aware fuzzy string matching
  (Levenshtein or similar) as a second semantic-adjacent signal, since typo'd
  references need this in addition to embedding similarity on description.

**Subagent C — LLM adjudicator** (`engine/adjudicator.py`)
- First, verify the two configured models are actually still live:
  `curl https://api.groq.com/openai/v1/models` with the key from `.env`.
  Groq's lineup changes often — don't build against a model that's been
  deprecated since this prompt was written.
- **Do the arithmetic in Python, not the LLM.** For ONE_TO_MANY/MANY_TO_ONE
  candidates, compute whether the group sums match (within the same
  tolerance Tier 1 uses) *before* calling the model, and pass the result in
  as a stated fact ("sums match within ₹0.02"). The LLM's job is to
  adjudicate the qualitative fit — is this a plausible split given the
  description/timing pattern — never to do the addition itself. This is
  the single biggest hallucination risk in this subagent if skipped.
- **Tier the model call the same way Parity tiers its matching:** try
  `GROQ_MODEL_FAST` (`llama-3.1-8b-instant`) first for the residual case.
  Escalate to `GROQ_MODEL_REASONING` (`openai/gpt-oss-120b` by default —
  OpenAI's own open-weight model, Apache 2.0, hosted free on Groq; swap to
  `qwen/qwen3.6-27b` if availability or rate limits don't cooperate) only
  when the fast pass returns "uncertain" or its confidence is below a
  threshold you define and log. Record which tier actually answered each
  record — this is worth surfacing in the eval report, not just internal
  plumbing.
- **Use native structured-output/JSON mode (constrained decoding), not a
  "please respond in JSON" text instruction.** Both configured models
  support this — confirm in the response schema you define, and reject
  (retry once, then fall back to the exception book) if a response doesn't
  validate. A response that merely "looks like JSON" is not the same
  guarantee as schema-constrained output, and AGENTS.md rule 3 needs the
  stronger guarantee.
- **Suppress chain-of-thought output on the reasoning-tier model.** Both
  `gpt-oss-120b` and `qwen/qwen3.6-27b` are reasoning-tagged and emit
  thinking tokens by default — set `include_reasoning: false` (gpt-oss) or
  `reasoning_effort: "none"` (Qwen) so the response is the clean structured
  verdict, not a wall of deliberation you'd have to strip out yourself.
- **Verify `gpt-oss-120b`'s actual free-tier rate limits separately from
  `llama-3.1-8b-instant`'s** — larger models on Groq sometimes carry
  tighter per-minute limits than small ones, not the same ceiling. Check
  console.groq.com/docs/rate-limits per model, not once for "Groq" as a
  whole, since this changes how often escalating to the reasoning tier is
  affordable mid-run.
- Groq's free tier is rate-limited (~30 requests/min on-demand at time of
  writing — verify current numbers at console.groq.com/docs/rate-limits
  since these change). Add basic retry-with-backoff on 429s. For the
  held-out set's bulk evaluation run specifically, consider Groq's Batch
  Processing tier instead of on-demand — it isn't bound by the same
  per-minute ceiling. Keep on-demand for the live app's interactive rerun
  path, where a judge is waiting on a response.
- **Must check `LLM_CALL_BUDGET_PER_RUN` / `TOKEN_BUDGET_PER_RUN` from
  `.env` before every call and fail loudly, not silently truncate, if
  exceeded** (AGENTS.md rule 7).
- The prompt to the LLM must include the actual signal scores and record
  fields, not just a vague "do these match?" — the rationale it returns
  must cite those specific values (AGENTS.md rule 3).
- Handle ONE_TO_MANY / MANY_TO_ONE grouping: design the function signature
  to accept a list of records on either side, not just a 1:1 pair — the
  pre-computed sum-check above feeds into this.

**After all three report back, you (the coordinating session) do the
merge:**
- Write `engine/confidence.py` — fuses the three signals into one
  confidence score and applies the bands from PRD Section 5: ≥0.9 auto-
  accept, 0.6-0.9 auto-accept-but-surfaced, <0.6 → exception book.
- Write `engine/tier2_reasoning.py` wiring Tier 1's unmatched output through
  all three signals → adjudicator → confidence → final `MatchDecision` or
  `ExceptionRecord`.
- Write `tests/test_tier2.py` against the held-out set (never regenerate
  it — AGENTS.md rule 1).

**Exit gate:**
```
pytest tests/test_tier2.py -v
```
must show ≥90% cumulative match rate (Tier 1 + Tier 2 combined), with
precision/recall reported, and every single decision — matched or
exception — carrying a rationale that cites real signal values. Spot-check
5 decisions by hand against `truth.json` before declaring this phase done;
a passing test suite that's checking the wrong thing is worse than no
tests.

Report back: cumulative match rate, precision/recall, false-positive cost
estimate, LLM calls used vs. budget, and 2-3 example rationales so a human
can sanity-check the grounding quality.
