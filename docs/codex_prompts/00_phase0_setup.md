# Codex prompt — Phase 0: Setup & API confirmation

Fresh session. No subagents — this is deliberately small.

---

You are setting up Parity for its first working session. Read
`AGENTS.md` in full before doing anything — it has hard rules that apply
to every later phase too.

**Launch this session with network access enabled** — `sandbox_mode` in
`.codex/config.toml` defaults `network_access` to off, and both `make
setup` (installs deps) and the API confirmation step need it:
```
codex --sandbox workspace-write -c sandbox_workspace_write.network_access=true
```

**Goal:** confirm the repo is correctly set up and the Razorpay test-mode
Settlement Recon API is reachable, before any matching code gets written.

**Steps:**
1. Run `make setup` to install dependencies.
2. Confirm `.env` exists and is filled in (if not, stop and tell the user
   to copy `.env.example` to `.env` and fill in their Razorpay test-mode
   keys from the Dashboard — Settings → API Keys → Test Mode. Do not
   fabricate placeholder keys and continue; a fake key will fail silently
   in a confusing way later).
3. Run `python3 scripts/confirm_api_connection.py`.
4. If it fails, diagnose using the error message's own guidance (test vs.
   live key prefix, network reachability, test-mode account activity) —
   don't guess blindly.
5. If it passes, report the item count and confirm readiness for Phase 1.

**Exit gate:** `confirm_api_connection.py` prints `Phase 0 gate: PASSED.`

**Do not** touch `data/generators/`, `engine/`, or `eval/` in this session
— those are later phases.
