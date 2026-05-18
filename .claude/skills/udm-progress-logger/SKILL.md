---
name: udm-progress-logger
version: v1.2.0
description: Logs the completion of substantive work to the canonical progress trackers (BACKLOG.md, _validation_log.md, ONE_OFF_SCRIPTS.md, POLISH_QUEUE.md, HANDOFF.md) IMMEDIATELY when the work completes. Use AFTER any agent / sub-agent / multi-agent team finishes substantive work — closing a B-item, landing a fix-cycle, locking a decision (D-number), authoring a runbook (RB-N), authoring a stored procedure (SP-N), building a tool, or completing a multi-unit build cohort. Distinct from udm-round-closeout (round-aggregate cadence) and udm-post-build-verify (test cadence) — this skill is the per-completion cadence that fills the mid-round tracker-drift gap. Per user-direction 2026-05-12 "make it a skill to ensure that all agents, sub-agents and multi-agent teams keep our progress tracked."
---

# UDM Progress Logger

Per-completion meta-skill that runs IMMEDIATELY when substantive work finishes — before the agent/sub-agent/team returns its summary, before the main agent moves to the next task, before any 🟢 status flip is claimed. Ensures the canonical trackers reflect reality at the moment the work lands, not at round-close-out (which is too late if the work changes 24+ hours of subsequent context).

## Why this skill exists (the gap it closes)

Empirical evidence from the 2026-05-12 build cycle (8-unit cohort B183/B184/B188/B189/B190/B193/B194/B195 + B215 fix-application):

- Build agents reported pass-counts in their summaries but did NOT update `BACKLOG.md` (close B-items) or `_validation_log.md` (event rows)
- `ONE_OFF_SCRIPTS.md` got updated inline only because `udm-execution-classifier` discipline forced it for migrations (B208 evidence)
- The main agent had to close B188 / B190 / B215 manually in a separate turn after the build cycle completed
- Risk: had the user not asked "what's next?", the closures might have been deferred to round-close-out, leaving BACKLOG.md / `_validation_log.md` stale for 24+ hours of subsequent context — a Pitfall #9.j (status-render drift) recurrence pattern

The discipline EXISTED in CLAUDE.md as a "Hard rule" (`🟢 Locked status WITHOUT a _validation_log.md entry is a status mismatch`) but was not operationalized as a skill. This skill operationalizes it for the moment-of-completion case.

## When to invoke

Mandatory invocation triggers (one of):

1. **B-item closure** — any agent/team just landed substantive work that closes a B-number in `BACKLOG.md`
2. **Fix-cycle landing** — an inline fix-application agent just resolved a 🔴/🟡 finding from a reviewer pass
3. **Build cohort completion** — Pattern B1 / B2 / B3 cohort just finished and `udm-post-build-verify` returned clean
4. **Decision lock** — a D-number just flipped 🟡 → 🟢 (paired with `udm-decision-recorder`)
5. **Runbook authoring** — a new RB-N just landed in `05_RUNBOOKS.md` (paired with `udm-runbook-author`)
6. **Tool / migration build** — a new executable artifact under `tools/` or `migrations/` reached 🟢 Build complete (paired with `udm-execution-classifier` for routing)
7. **Multi-agent team return** — a parallel cohort (≥2 sub-agents working concurrently) just returned with substantive deliverables

The trigger is ANY substantive completion; the skill is intentionally cheap so over-invocation has near-zero cost and under-invocation is the only failure mode.

## When NOT to invoke

- For purely exploratory reads (no state change)
- For typo / formatting / cosmetic-only edits (those route to `POLISH_QUEUE.md` via P-N, not to this skill — but a P-N closure DOES invoke this skill at completion)
- For tool calls that returned errors / aborted (no completion to log)
- For draft / WIP edits where the agent is mid-task (only at the natural completion boundary)

## Canonical Context Load (CCL) per D62

Whoever invokes this skill (the completing agent OR the main agent on its behalf) MUST have performed the Canonical Context Load before logging. If the completing agent didn't run a full CCL because it was a narrow-scope worker (e.g., a Pattern B build agent that read only its target spec), the MAIN agent assumes CCL responsibility and logs on the worker's behalf.

- **Stage 0 — Routing manifest** (recommended-not-mandatory; added 2026-05-15 per D62 amendment + D.2 INDEX.md per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.3): `docs/migration/INDEX.md` — read FIRST when uncertain which downstream Stage 1+2+3 docs your task actually needs. Skip when: you already know which Stage 1+2+3 docs to load (typical for recurring task patterns).
- **Stage 1 — Orientation** (mandatory, 4 reads if not already done this session): `NORTH_STAR.md`, `HANDOFF.md`, `CURRENT_STATE.md`, `CHECKS_AND_BALANCES.md`
- **Stage 2 — Tracker awareness** (mandatory): `BACKLOG.md`, `_validation_log.md` — the two trackers always touched
- **Stage 2.5 — Conditional trackers** (read IF the completion touches them): `CODE_BUILD_STATUS.md` (if code module / tool / migration build — required per Hard Rule 7), `ONE_OFF_SCRIPTS.md` (if migration / one-time tool), `POLISH_QUEUE.md` (if cosmetic), `RISKS.md` (if risk delta), `03_DECISIONS.md` (if decision lock)
- **Stage 3 — The artifact** itself: the file(s) just built / edited (for line-anchor citations in the log entry)
- **Stage 4 — Reference-on-demand**: `MULTI_AGENT_GUIDE.md` § Canonical Context Load if CCL discipline questions arise

## The log-write checklist

Run all applicable items; produce a structured one-paragraph report at the end (NOT a separate doc).

### Step 0 — Post-compaction tracker re-Read (MANDATORY at turn start before any Edit)

**Why this step exists**: in long sessions that span Claude Code conversation-compaction events, agents lose Read-state for large tracker files. The Edit tool requires a `Read` in the **current context** before allowing modification — but after compaction, the prior session's Read-state is reset. System-reminders explicitly flag this with text like `Note: <path> was read before the last conversation was summarized, but the contents are too large to include. Use Read tool if you need to access it.` Empirical first-event evidence (commit `db77516` 2026-05-16): parent agent attempted Edit on `docs/migration/BACKLOG.md` post-compaction WITHOUT a fresh Read; Edit tool returned `<error><tool_use_error>File has not been read yet. Read it first before writing to it.</tool_use_error></error>`; parent misread the error as success (skimming batched tool outputs) and proceeded several messages before discovering the failure via `git status`. By that time `CURRENT_STATE.md` had been prepended with claims of B-N closures that BACKLOG didn't yet reflect — temporary cross-tracker inconsistency. This step closes that gap by forcing a fresh Read + post-Edit verification cycle.

**Procedure**:

1. **Detection trigger (at turn start)**: scan all `<system-reminder>` blocks in the current turn for the canonical post-compaction phrase: `was read before the last conversation was summarized, but the contents are too large to include`. If found, enumerate the file path(s) named in the reminders. The trackers most commonly flagged are `docs/migration/CURRENT_STATE.md` and `docs/migration/BACKLOG.md` (both >25K tokens), but the trigger applies to ANY tracker the skill is about to Edit.

2. **Mandatory fresh-Read action (BEFORE any Edit)**: BEFORE the first Edit call on each named file, perform a fresh `Read` in the current context. For files small enough to read fully, do an unbounded Read. For files too large to read fully (typical of CURRENT_STATE.md / BACKLOG.md), do a targeted Read using `offset` + `limit` over the exact line range to be edited; AND/OR run a `Grep` over the file to confirm the `old_string` Edit anchor is present and unique. Never rely on prior-session Read-state.

3. **Post-Edit verification (after every Edit on a tracker file)**: after each successful-looking Edit tool call, run a one-line `Grep` to confirm the new content actually landed in the file (do NOT just trust the Edit tool's success message — `<error>` blocks in batched tool output can be skimmed past). Acceptable verification: `Grep` for a distinctive substring of the `new_string` text against the just-edited file; verdict must be ≥1 match. If the Grep returns zero matches, the Edit silently failed (most commonly due to stale-Read-state OR a non-unique `old_string`) — re-Read + retry.

4. **Anti-pattern explicitly named**: claiming "UPDATED" or closure status for a tracker in a downstream artifact (commit message body / `_validation_log.md` entry / `CURRENT_STATE.md` narrative prepend / cascade-complete report) BEFORE verifying the upstream tracker Edit actually landed is **Pitfall #9.k arithmetic-propagation drift via stale-Edit-state**. The propagation goes downstream-from-a-nonexistent-upstream-write. The fix discipline is **verification before claim**: every "UPDATED" assertion in downstream content must be preceded by the Grep verification in step 3.

5. **Composition**: Step 0 runs FIRST, BEFORE the per-build-type tracker walk in Step 1 + the Pitfall #9.j status-render discipline in Step 2 + the hard-rule checks in Step 3 + the `_validation_log.md` write in Step 4 + the report emit in Step 5. If Step 0 detection trigger fires zero post-compaction file flags, proceed directly to Step 1 (Step 0 is a no-op when no compaction occurred in the session — its cost is the trigger scan only).

### Step 1 — Identify which trackers the completion touches

For the completed work, determine which of these are touched:

| Completion type | Trackers updated |
|---|---|
| B-item closure | `BACKLOG.md` (strikethrough + ⚫ CLOSED date) + `_validation_log.md` (event row) |
| Fix-cycle landing (no B-number) | `_validation_log.md` only (cycle entry under round-cycle header) |
| Decision lock | `03_DECISIONS.md` (🟡 → 🟢) + `BACKLOG.md` (if B-item drove the decision) + `_validation_log.md` |
| Runbook authoring | `05_RUNBOOKS.md` (new RB-N) + `BACKLOG.md` (if B-item) + `_validation_log.md` |
| **Code module / tool / migration built** (REQUIRED tracker update — see hard rule 7 below) | **`CODE_BUILD_STATUS.md` (per-unit row state transition ⬜ → 🟡 → 🟢 → ✅)** + `ONE_OFF_SCRIPTS.md` (if migration / one-time tool per `udm-execution-classifier`) + `BACKLOG.md` (close B-item) + `_validation_log.md` |
| **NEW `tools/*.py` with ≥3 non-trivial public surfaces** (added 2026-05-17 per check_9n GLOSSARY-parity extension) | **`CLAUDE.md` Structure section row** AND **`GLOSSARY.md` public-surface entries** (per-name rows in module-surface table; per Step 10 + Pitfall #9.n discipline). Mechanically enforced by `tools/query_blindspots.py::check_9n_convention_registration` at commit-msg hook (BLOCKS if GLOSSARY missing for substantial tools). Trivial-wrapper tools (only `main`+`cli_main` surfaces) exempt from mechanical GLOSSARY-parity check but recommended for completeness |
| **NEW `tools/*.py` with `EVENT_TYPE = "CLI_*"` constant** (promoted from CONDITIONAL → MANDATORY 2026-05-17 per B189 closure cohort empirical-drift remediation) | **MANDATORY: when authoring a new `tools/*.py` with `EVENT_TYPE = 'CLI_*'` constant, CLAUDE.md L207 CLI_* family registry update is MANDATORY in the SAME COMMIT.** The L207 registry text (`**CLI_\*** (N tools) — ...`) must enumerate the new EventType + bump the count. Companion mechanical enforcement: `tools/pre_commit_checks.py::check_cli_registry_sync` (8th orchestrator check; just landed today; mechanically BLOCKS commit if L207 entry missing). Empirical anchor: B189 closure cohort 2026-05-17 surfaced 4-tool drift (3 B-317 cascade tools `CLI_CASCADE_CLASSIFIER` + `CLI_GENERATE_CASCADE_EVIDENCE` + `CLI_AUDIT_CASCADE_COMPLIANCE` + 1 B189 tool `CLI_IMPORT_PII_INVENTORY` absent from L207 for 1-5 days). Two-layer defense: producer-side (this row + `udm-step-10-verifier` Step 3) + harness-side (`check_cli_registry_sync` BLOCKS at hook time) |
| Edge case discovery | `04_EDGE_CASES.md` (new M/S/I/N/P/G/D/F/V/DP/T/SI entry) + `BACKLOG.md` (if B-item) + `_validation_log.md` |
| Risk surfaced | `RISKS.md` (new R-N) + `_validation_log.md` |
| Cosmetic / readability landed | `POLISH_QUEUE.md` (close P-N or add P-N) + `_validation_log.md` (low-touch row) |
| HANDOFF §8 directive landed | `HANDOFF.md` (§8 sub-class extension) + `_validation_log.md` |
| Substantive multi-tracker session event (mirror of CURRENT_STATE narrative for fresh-agent onboarding) | `HANDOFF.md` (`## §14. Last updated` section — prepend a dated parenthetical narrative entry matching the CURRENT_STATE.md L7 pattern; pre-existing dated entries demoted to "Earlier <date>:" lines below). SKIP when: edit is doc-only metadata polish, single-tracker P-N closure, or already-mirrored from a prior commit in the same session. Empirical anchor: commit `570ac67` (2026-05-16) is the canonical example of correct application (D114 lock prepended; prior entries demoted) |
| Skill / agent prompt evolution | `.claude/skills/<name>/SKILL.md` or `.claude/agents/<name>.md` + `_validation_log.md` (paired with `udm-agent-prompt-versioner` for semver) |

### Step 2 — Apply Pitfall #9.j status-render discipline

For every BACKLOG.md / RISKS.md / POLISH_QUEUE.md / ONE_OFF_SCRIPTS.md row touched:

- **Leading badge MUST match inline annotation**. If row had `(🟡 Open)` leading badge and is now closing, strike the whole row with `~~...~~` then append `— ⚫ CLOSED YYYY-MM-DD via <mechanism>`
- **Strikethrough preserves the body** — never delete; append-only audit trail per BACKLOG.md L139-145 + Pitfall #9.j
- **Closure mechanism is required** — cite the closing event (e.g., "via Pattern B3 cohort + B215 fix-application"; "via D108 path (b) acceptance"; "via cycle-2 design-review fix landed inline")
- **High-priority duplicate** — if the closing B-N also appears in a "## High priority" sorted-list at the top of BACKLOG.md, strike BOTH appearances per Pitfall #9.j 6-step audit Step 6
- **Partial closure** (added v1.2.0 per B-382 empirical precedent at D72 cycle-6 cohort 2026-05-17): when a B-N has been partially closed (e.g., X of Y locations applied; remaining tracked via separate B-N), the canonical leading badge is `(🟠 PARTIAL CLOSURE; <PRIORITY>; WSJF <N>)` matching the inline `🟠 PARTIAL CLOSURE YYYY-MM-DD (X of Y applied; Z deferred to B-NNN)` annotation. NOT `(🟡 Open ...)` (which would mis-suggest no progress) and NOT `(⚫ CLOSED ...)` (which would mis-suggest full closure). The 🟠 emoji distinguishes partial-state from canonical Open / CLOSED / Noticeable per BACKLOG.md status legend extension.

### Step 3 — Apply CLAUDE.md hard-rule discipline

CLAUDE.md "Validation discipline" section codifies two hard rules this skill enforces:

- **Hard rule 1**: 🟢 Locked status WITHOUT a `_validation_log.md` entry is a status mismatch — every 🟢 lock claimed in this completion MUST have a corresponding `_validation_log.md` row written in the same session
- **Hard rule 2**: 🟢 Lock on built code WITHOUT a classification entry in the appropriate tracker is a status mismatch — every code build reaching 🟢 MUST appear in `ONE_OFF_SCRIPTS.md` OR `phase1/02_configuration.md` § 5.1 (scheduled tools) per `udm-execution-classifier` routing

If either hard rule would be violated by claiming 🟢 right now, BLOCK the 🟢 claim until the tracker write lands. The skill returns the missing tracker row content for the agent to write before proceeding.

### Step 4 — Write the `_validation_log.md` row

Append a one-row entry (or short multi-row block for multi-unit cohorts) to `docs/migration/_validation_log.md` under the current round's section. The row format follows the existing append-only pattern:

```
### YYYY-MM-DD <agent or skill> — <completion summary>

- **Trigger**: <what initiated this completion> (B-N close / cycle-N fix / Pattern B cohort / etc.)
- **Artifacts touched**: <files edited; relative paths>
- **Outcome**: 🟢 / 🟡 / 🔴 + one-sentence description
- **Trackers updated**: BACKLOG.md (B-N → ⚫); ONE_OFF_SCRIPTS.md (entry added); HANDOFF.md (§ if applicable)
- **Test verification**: <pytest pass-counts if code; "N/A" if doc-only>
- **Carryovers**: <new B-N / R-N / P-N opened, if any>
```

Place the entry under the round's section, NOT at the file end. Round sections are typically dated; if no current-round section exists yet, create one.

### Step 4.5 — Arithmetic-propagation sweep (added v1.2.0 per Pitfall #9.k empirical recurrence across D72 6-cycle ladder 2026-05-17)

After the `_validation_log.md` row is written, BEFORE the report is produced: grep canonical narrative docs (CURRENT_STATE.md L7 + HANDOFF.md §14 + the very `_validation_log.md` entry being written) for stale counts / ranges / scores that this completion changes. Specifically:

| Change made in completion | Required arithmetic-propagation sweep | Why |
|---|---|---|
| New B-N opened (B-X) | grep "X NEW B-Ns" / "B-353 through B-Y" / "B-X-Y" range claims in CURRENT_STATE L7 + HANDOFF §14 + _validation_log most-recent event; update inline to reflect new range/count | Pitfall #9.k recurrence at commits `7cb7659` → `fe53b4c` (21→24 drift) + cycle-3 `114aa22` (4 instances at Phase A plan L24/L439/L453/L478 + 1 at _validation_log L26); 5+ instances across 2 cycles |
| B-N closed (B-X → ⚫) | grep "open B-N count" / "carryover X items" claims in HANDOFF §14 + CURRENT_STATE L7; update inline | Same Pitfall #9.k pattern; affects rolling counter narratives |
| R-N opened / re-scored / closed | grep OLD score (e.g., `R36 ⚪ 2`) across canonical docs + Phase A plan + related plan bodies; update inline to reflect new score consistently | Pitfall #9.k empirical at R36 re-score (⚪ 2 → 🟡 3 at `0da9bda`); Phase A plan §3.2 L178 + §7 L356 + §9.4 L426 + L507 retained stale ⚪ 2 for 2 cycles before cycle-3 caught + fixed |
| D-N opened / locked / superseded | grep "D-N count" / "D-N range" / D-N-supersedes-X claims; update inline | Closes future-state drift when D-N status transitions |
| New edge case series introduced (e.g., SE-N) | grep "X canonical series total" + "M/S/I/N/P/G/D/F/V/..." enumerations across ALL canonical doc anchor locations; cascade NEW series suffix to each | Pitfall #9.n cascade per B-382 empirical (14-location enumeration scope; 7+ additional locations surfaced post-hoc by cycle-3 gap-check → B-392) |
| §-row count change in a plan body | grep "TOTAL X rows" / "N items present" / "9 B-Ns" enumeration column claims; recount + update | Pitfall #9.k self-recurrence at Phase A plan §5 TOTAL row "12 B-Ns" vs 10 actual at cycle-3 |

**Verification mechanism**: after the inline updates, run a SECOND grep for the OLD value/count/range across the same scope; expected = 0 occurrences. Cite the verification step + grep result in the report.

**Why this Step exists**: D72 6-cycle ladder on Phase A plan (2026-05-17) empirically demonstrated that the skill's own work product (tracker narrative updates) is the highest-recurrence site for Pitfall #9.k arithmetic-propagation drift. Cycles 2+3 had 5+ instances; cycle-3 remediation introduced 3 more new instances (the "fix introduces same bug class" failure mode). This Step is the producer-side mechanical mitigation; it composes with `tools/pre_commit_checks.py` markdown_cross_refs (harness-side) but covers a different scope (cross-ref check verifies refs RESOLVE; this Step verifies refs are NUMERICALLY current).

### Step 5 — Produce the report

The skill's return value is a 4-6 line report:

```
PROGRESS LOGGED — <one-line summary of completion>

- Trackers updated: BACKLOG.md (B-N → ⚫ CLOSED YYYY-MM-DD); ONE_OFF_SCRIPTS.md (entry added); _validation_log.md (event row)
- Hard-rule checks: ✅ _validation_log row written; ✅ tracker classification entry present (or: ✅ N/A for doc-only completion)
- Carryovers: <any new B-N / R-N / P-N opened>
- Next-natural-action: **invoke `udm-gap-check` per CLAUDE.md discipline #11 hard rule** (mandatory before 🟢 status claim) — then main agent decides next task OR triggers `udm-round-closeout` if this was the round-final unit
```

Brief is the goal. The detail lives in `_validation_log.md`; the report exists for the main agent + user to confirm the discipline ran.

## Hard rules

1. **Log at the moment of completion, not later.** Deferring to round-close-out is exactly the gap this skill exists to close.
2. **Append-only.** Never delete prior tracker rows. Strikethrough + closure annotation is the canonical pattern (Pitfall #9.j).
3. **Closure mechanism MUST cite a real event.** "Closed because we wanted to" is not a mechanism. Acceptable mechanisms: "via Pattern B<N> cohort", "via D<N> acceptance", "via cycle-<N> reviewer fix", "via convergence-confirmed acceptance", "via user-direction `<verbatim quote>`".
4. **No 🟢 without a `_validation_log.md` row.** This is the existing CLAUDE.md hard rule; this skill operationalizes it.
5. **No build-code 🟢 without `ONE_OFF_SCRIPTS.md` OR scheduled-tools-registry classification.** Existing CLAUDE.md hard rule from `udm-execution-classifier` discipline.
6. **One skill invocation per completion event.** If a multi-unit cohort finishes, ONE invocation logs ALL units (multi-row block in `_validation_log.md`); not N invocations. **Partial cohort failure handling** (added 2026-05-12 per F-2 validation finding): if a multi-unit cohort partially fails (e.g., 3 of 5 units 🟢; 2 units 🔴), log the 🟢 units immediately with their canonical closure mechanism + log the 🔴 units in the same `_validation_log.md` block with `Outcome: 🔴` + open a B-N item per failing unit OR aggregate B-N if the failures share root cause. Do NOT defer the 🟢 logging while waiting for the 🔴 units to resolve — that's the gap this skill exists to close. The 🔴 units' B-N entries then become the natural carryover for the next session.
7. **No code-build 🟢 without `CODE_BUILD_STATUS.md` row state transition.** Every code module / tool / migration that reaches 🟢 Built MUST appear with its 🟢 build date + test pass-count in the corresponding `CODE_BUILD_STATUS.md` per-unit table (Round 4 tools / Round 3 modules / Migrations / etc.). State transitions ⬜ → 🟡 → 🟢 → ✅ are inline edits with date + mechanism. Authored 2026-05-12 per user-direction "tracking progress on completing the coding tasks" to fill the gap that hard rules 4 + 5 alone don't cover (B-N + ONE_OFF_SCRIPTS only catch one-off scripts; the broader codebase needs visibility into Round 3 modules + Round 4 tools + Round 6 modules + Phase 2+ extensions). The tracker is at `docs/migration/CODE_BUILD_STATUS.md`.
8. **No status transition without arithmetic-propagation sweep** (added v1.2.0 per D72 6-cycle ladder empirical evidence). Re-scoring an R-N (e.g., R36 ⚪ 2 → 🟡 3), opening/closing a B-N range, introducing a new edge case series, or transitioning a D-N status MUST be followed by Step 4.5 arithmetic-propagation sweep across CURRENT_STATE.md L7 + HANDOFF.md §14 + the most-recent `_validation_log.md` entry + any plan body that cites the OLD value. Skipping this sweep is the mechanical root cause of Pitfall #9.k arithmetic-propagation drift recurrence (5+ instances observed across cycles 2+3 of D72 6-cycle ladder on Phase A plan 2026-05-17 — the canonical empirical anchor).

## Anti-patterns

- ❌ "I'll log this at round-close-out" — defeats the skill's purpose
- ❌ Writing the closure annotation in BACKLOG.md but skipping `_validation_log.md` — violates hard rule 4
- ❌ Striking a row without citing a closure mechanism — violates hard rule 3
- ❌ Logging "everything went well" without specific artifact paths + pass-counts — too thin for future audit
- ❌ Inventing a B-N or D-N number — verify against `BACKLOG.md` / `03_DECISIONS.md` first; if the number doesn't exist, this isn't the right closure event
- ❌ Logging trivial work (typo fixes, no-op edits) — skip; reserve the skill for substantive completions
- ❌ Re-running the skill mid-completion (before all sub-tasks land) — wait for the natural completion boundary
- ❌ Writing the new `_validation_log.md` event entry WITHOUT refreshing the EXISTING CURRENT_STATE.md L7 + HANDOFF.md §14 narrative for inherited drift across multi-commit cascade (added v1.2.0 per cycle-6 cosmetic finding 2026-05-17 — narrative said "24 NEW B-Ns / R34-R37 / SE1-SE7" 5 commits after actual state became "40 NEW B-Ns / R34-R38 / SE1-SE10"; the "Earlier YYYY-MM-DD" prefix pattern preserves audit trail BUT the current-state narrative MUST reflect cumulative current state at each invocation, not just the per-completion delta)
- ❌ Skipping Step 4.5 arithmetic-propagation sweep when the completion touched a count / range / score / enumeration that has corresponding narrative references elsewhere (added v1.2.0 per Pitfall #9.k 5+ recurrence on D72 6-cycle ladder)

## Integration with existing skills

- **`udm-checks-and-balances`** — runs BEFORE this skill (per-artifact validation completes; this skill then logs the completion event)
- **`udm-post-build-verify`** — runs BEFORE this skill (tests pass; this skill then logs the build-complete event)
- **`udm-execution-classifier`** — runs IN PARALLEL with this skill for tool/migration builds (classifier handles tracker routing; this skill handles `_validation_log.md` write)
- **`udm-decision-recorder`** — runs BEFORE this skill for decision locks (recorder authors D-number; this skill logs the event)
- **`udm-runbook-author`** — runs BEFORE this skill for runbook authoring (author writes RB-N; this skill logs)
- **`udm-round-closeout`** — runs AT END OF ROUND, aggregating across multiple `_validation_log.md` entries that this skill produced over the round; this skill is what populates the aggregate for close-out to consume
- **`udm-agent-prompt-versioner`** — runs IN PARALLEL with this skill for skill/agent prompt updates (versioner handles semver; this skill logs)
- **`udm-gap-check`** (REQUIRED next step per CLAUDE.md discipline #11 hard rule 2026-05-12) — runs IMMEDIATELY AFTER this skill completes logging. This skill records the work; gap-check audits for drift the producer self-check missed. The Step 5 report's "Next-natural-action" line MUST recommend `udm-gap-check` invocation as the next step BEFORE any 🟢 status claim is made. 🟢 status WITHOUT a gap-check entry is a status mismatch (same severity as Hard Rule 4 _validation_log row).

## CCL self-check fallback (per D62 + B34)

If the agent invoking this skill realizes mid-procedure that CCL wasn't performed and re-loading the full CCL would blow the context budget for the current task:

1. AT MINIMUM read `HANDOFF.md` § 3 (locked vs in-flight) + `BACKLOG.md` (current state of the B-N being closed) + the artifact being completed
2. Note in the `_validation_log.md` row: "CCL self-edit fallback applied per D62 + B34 — Stage 1 partial; Stages 2-4 deferred to next CCL"
3. The skill still runs; the discipline is preserved; the audit trail records the shortcut

Full CCL is preferred; the self-edit fallback exists for narrow-context workers (Pattern B build agents typically operate under this fallback).

## Example invocation

After Pattern B3 cohort B188/B189/B190 build cycle + B215 fix-application landed:

```
INVOKE udm-progress-logger
  context: Pattern B3 cohort + B215 fix-application completed; pytest 283 pass + 12 skip + 0 fail; user-direction "Proceed with your recommended next steps. We've used UTC in the past."

OUTPUT:
PROGRESS LOGGED — B188 + B190 + B215 closed; build cohort + fix-application landed

- Trackers updated: BACKLOG.md (B188 → ⚫ CLOSED 2026-05-12 via Pattern B3 + B215 fix; B190 → same; B215 → ⚫ CLOSED via inline fix-application); _validation_log.md (event row for 8-unit cohort completion); ONE_OFF_SCRIPTS.md (entries already current per B208 inline updates)
- Hard-rule checks: ✅ _validation_log row written; ✅ ONE_OFF_SCRIPTS.md classification present for B193/B194/B195 migrations + B189 operator tool; ✅ scheduled-registry classification for B188 (JOB_LATENESS_MEASURE) + B190 (JOB_CAPACITY_BASELINE)
- Carryovers: B214 (sys.modules loader audit), B216 (gc.get_objects pattern), B211 (B184 monkey-patch refactor) — all remain open per their existing entries
- Next-natural-action: main agent decides next task; round-close-out NOT yet triggered (R1 still in progress)
```

## Where this skill lives in the broader discipline

Process-level skills the project uses (paths under `.claude/skills/`):

| Cadence | Skill | Triggers |
|---|---|---|
| Per-completion | **`udm-progress-logger`** (this skill) | ANY substantive work finishes |
| Per-artifact validation | `udm-checks-and-balances` | New artifact authored / locked |
| Per-build | `udm-post-build-verify` | Pattern B cycle Wave 3 finishes |
| Per-build classification | `udm-execution-classifier` | Tool / migration authored |
| Per-decision | `udm-decision-recorder` | D-number lock candidate |
| Per-runbook | `udm-runbook-author` | New RB-N candidate |
| Per-edge-case | `udm-edge-case-validator` | New edge case candidate |
| Per-round | `udm-round-closeout` | End of Phase round |
| Per-round skill-evolution | `udm-retrospective-collector` + `udm-specialty-tuner` + `udm-subclass-accumulator` + `udm-producer-checklist-evolver` + `udm-cycle-cadence-optimizer` + `udm-cascade-audit-evolver` + `udm-agent-prompt-versioner` | Section 10 of round-close-out cascade |
| As-needed | `udm-brainstorm` + `udm-planning` + `udm-data-engineer-review` | Open design questions / planning sessions |

This skill fills the gap between per-artifact (which validates) and per-round (which aggregates) — the moment-of-completion log-write.

---

Owner: pipeline lead (skill definition); every agent + sub-agent + multi-agent team that completes substantive work (skill invoker).

Authored 2026-05-12 per user-direction "make it a skill to ensure that all agents, sub-agents and multi-agent teams keep our progress tracked." Empirical gap evidence: 2026-05-12 8-unit build cohort closure pattern (main agent had to close B-items in a separate post-cohort turn after build agents themselves didn't update trackers).

## Changelog (per D98 semver discipline)

| Version | Date | Change | Trigger |
|---|---|---|---|
| v1.0.0 | 2026-05-12 | Initial authoring per user-direction (per-completion tracker-update skill) | Empirical 8-unit cohort tracker-drift evidence |
| v1.1.0 | 2026-05-17 | MINOR — directive strengthening: Step 1 table row for `tools/*.py` with `EVENT_TYPE = "CLI_*"` promoted from CONDITIONAL to MANDATORY (CLAUDE.md L207 CLI_* family registry update required in same commit). Companion to harness-side mechanical enforcement at `tools/pre_commit_checks.py::check_cli_registry_sync` (8th orchestrator check) landing same day. | B189 closure cohort 2026-05-17 surfaced 4-tool drift (3 B-317 cascade tools + 1 B189 tool absent from L207 for 1-5 days) — paired producer-side + harness-side defense per Option A plan |
| v1.2.0 | 2026-05-17 | MINOR — directive addition: (1) NEW Step 4.5 arithmetic-propagation sweep (after tracker updates, grep canonical narratives for stale counts/ranges/scores; update inline; verify with second grep returning 0 occurrences); (2) Step 2 Pitfall #9.j extended with `🟠 PARTIAL CLOSURE` convention for B-N partial-state per B-382 empirical precedent (X of Y locations applied; remainder via separate B-N); (3) NEW Hard rule 8 — no status transition without arithmetic-propagation sweep; (4) NEW anti-pattern — writing per-completion _validation_log entry without refreshing existing CURRENT_STATE/HANDOFF narrative for inherited drift across multi-commit cascade. | D72 6-cycle ladder on Phase A plan 2026-05-17 (cycles 1-6 spanning Agents 43-52; empirical evidence: 5+ instances of Pitfall #9.k arithmetic-propagation drift in the very tracker narrative updates the skill produces — specifically `7cb7659` → `fe53b4c` 21→24 drift + cycle-3 `114aa22` 4 instances at Phase A plan + 1 at _validation_log + R36 re-score stale-narrative across 3 plan locations through 2 cycles + Phase A plan §5 TOTAL "12 B-Ns" vs 10 actual). Cycle-3 remediation introduced 3 NEW instances ("fix introduces same bug class" pattern); cycle-6 cosmetic findings included 2 inherited-drift instances (B-382 badge + brainstorm-cohort narrative still cited 24 B-Ns 5 commits after state became 40 B-Ns). The arithmetic-propagation sweep + partial-closure convention + multi-commit narrative refresh discipline are the producer-side mechanical mitigations; compose with harness-side `tools/pre_commit_checks.py` markdown_cross_refs check which covers different scope (refs RESOLVE vs refs CURRENT). |
