# Codex prompt — Phase 6: Fixes, Docs & Repro agent

Fresh session. No subagents — this is sequential, judgment-heavy work
(what to fix vs. defer, what the pitch actually says) that doesn't
parallelize well.

---

You are closing out Parity for submission. Read `AGENTS.md` first, then
Phase 5's hardening report (paste it into this session — it isn't saved to
a file automatically unless you saved it yourself).

**Your job, in order:**

1. **Work through Phase 5's report top-down.** Fix anything that would
   change a reported number or crash the demo. For anything you decide to
   defer (not everything needs fixing before Sept 5), note it explicitly in
   the README's Status table — don't just drop it silently.
2. **Generate a logo.** Install the `ip-as-logo` Codex skill
   (`npx skills@latest add s1dashu/ip-as-logo-skill`) — it reads repo
   context (README, design tokens) to infer product personality before
   generating, so make sure `README.md` and `frontend/`'s Blade token setup
   already read as "restrained, professional financial investigator" by
   this point, not just "fintech app," since the skill's default output
   leans cute/mascot-y (ghost-bot style) and this brand needs to sit closer
   to RazorSense's sleeker register. When it proposes 3 directions before
   committing, pick the most restrained one, not the most characterful —
   this is a financial tool, not a consumer app. Use Blade's actual theme
   token colors (see Phase 4, Subagent C) as the palette input, not a
   guessed equivalent. Once generated, add it to `README.md`'s header and
   to `frontend/src/App.jsx`.
3. **Full held-out re-run** after fixes: match rate, precision/recall,
   false-positive cost, throughput must all be re-verified, not assumed
   unchanged.
4. **Update `README.md`**: Status table reflects reality, Quickstart
   section tested by literally following it from a clean clone.
5. **Write `docs/architecture.md`** — a trimmed version of PRD Section 3
   (the pipeline diagram) plus what actually got built, for the panel to
   read alongside the repo.
6. **Write `docs/pitch_script.md`** — 5-minute structure: problem →
   architecture walkthrough → live run → exception book walkthrough
   (leading with the leakage figure per PRD Section 2, keeping "found/
   flagged" verb discipline per AGENTS.md rule 5) → one failure case
   handled gracefully. Every number in the script must trace to the fresh
   re-run in step 3 — no numbers from memory or an earlier run.
7. **Final reproducibility check**: from a genuinely clean clone (new
   directory, not this working copy), run `make setup && make confirm-api
   && make demo` and confirm the pitch script's numbers match exactly.

**Exit gate:** a clean clone reproduces every number in
`docs/pitch_script.md`. If it doesn't, the pitch script is wrong, not the
repo — fix the script to match reality, never the other way around.

Report back: final metrics, what was fixed vs. deferred from Phase 5, and
confirmation the clean-clone reproduction matched.
