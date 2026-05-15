---
name: udm-progress-logger
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

- **Stage 1 — Orientation** (mandatory, 4 reads if not already done this session): `NORTH_STAR.md`, `HANDOFF.md`, `CURRENT_STATE.md`, `CHECKS_AND_BALANCES.md`
- **Stage 2 — Tracker awareness** (mandatory): `BACKLOG.md`, `_validation_log.md` — the two trackers always touched
- **Stage 2.5 — Conditional trackers** (read IF the completion touches them): `CODE_BUILD_STATUS.md` (if code module / tool / migration build — required per Hard Rule 7), `ONE_OFF_SCRIPTS.md` (if migration / one-time tool), `POLISH_QUEUE.md` (if cosmetic), `RISKS.md` (if risk delta), `03_DECISIONS.md` (if decision lock)
- **Stage 3 — The artifact** itself: the file(s) just built / edited (for line-anchor citations in the log entry)
- **Stage 4 — Reference-on-demand**: `MULTI_AGENT_GUIDE.md` § Canonical Context Load if CCL discipline questions arise

## The log-write checklist

Run all applicable items; produce a structured one-paragraph report at the end (NOT a separate doc).

### Step 1 — Identify which trackers the completion touches

For the completed work, determine which of these are touched:

| Completion type | Trackers updated |
|---|---|
| B-item closure | `BACKLOG.md` (strikethrough + ⚫ CLOSED date) + `_validation_log.md` (event row) |
| Fix-cycle landing (no B-number) | `_validation_log.md` only (cycle entry under round-cycle header) |
| Decision lock | `03_DECISIONS.md` (🟡 → 🟢) + `BACKLOG.md` (if B-item drove the decision) + `_validation_log.md` |
| Runbook authoring | `05_RUNBOOKS.md` (new RB-N) + `BACKLOG.md` (if B-item) + `_validation_log.md` |
| **Code module / tool / migration built** (REQUIRED tracker update — see hard rule 7 below) | **`CODE_BUILD_STATUS.md` (per-unit row state transition ⬜ → 🟡 → 🟢 → ✅)** + `ONE_OFF_SCRIPTS.md` (if migration / one-time tool per `udm-execution-classifier`) + `BACKLOG.md` (close B-item) + `_validation_log.md` |
| Edge case discovery | `04_EDGE_CASES.md` (new M/S/I/N/P/G/D/F/V/DP/T/SI entry) + `BACKLOG.md` (if B-item) + `_validation_log.md` |
| Risk surfaced | `RISKS.md` (new R-N) + `_validation_log.md` |
| Cosmetic / readability landed | `POLISH_QUEUE.md` (close P-N or add P-N) + `_validation_log.md` (low-touch row) |
| HANDOFF §8 directive landed | `HANDOFF.md` (§8 sub-class extension) + `_validation_log.md` |
| Skill / agent prompt evolution | `.claude/skills/<name>/SKILL.md` or `.claude/agents/<name>.md` + `_validation_log.md` (paired with `udm-agent-prompt-versioner` for semver) |

### Step 2 — Apply Pitfall #9.j status-render discipline

For every BACKLOG.md / RISKS.md / POLISH_QUEUE.md / ONE_OFF_SCRIPTS.md row touched:

- **Leading badge MUST match inline annotation**. If row had `(🟡 Open)` leading badge and is now closing, strike the whole row with `~~...~~` then append `— ⚫ CLOSED YYYY-MM-DD via <mechanism>`
- **Strikethrough preserves the body** — never delete; append-only audit trail per BACKLOG.md L139-145 + Pitfall #9.j
- **Closure mechanism is required** — cite the closing event (e.g., "via Pattern B3 cohort + B215 fix-application"; "via D108 path (b) acceptance"; "via cycle-2 design-review fix landed inline")
- **High-priority duplicate** — if the closing B-N also appears in a "## High priority" sorted-list at the top of BACKLOG.md, strike BOTH appearances per Pitfall #9.j 6-step audit Step 6

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

## Anti-patterns

- ❌ "I'll log this at round-close-out" — defeats the skill's purpose
- ❌ Writing the closure annotation in BACKLOG.md but skipping `_validation_log.md` — violates hard rule 4
- ❌ Striking a row without citing a closure mechanism — violates hard rule 3
- ❌ Logging "everything went well" without specific artifact paths + pass-counts — too thin for future audit
- ❌ Inventing a B-N or D-N number — verify against `BACKLOG.md` / `03_DECISIONS.md` first; if the number doesn't exist, this isn't the right closure event
- ❌ Logging trivial work (typo fixes, no-op edits) — skip; reserve the skill for substantive completions
- ❌ Re-running the skill mid-completion (before all sub-tasks land) — wait for the natural completion boundary

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
