---
name: udm-round-closeout
description: Orchestrates the round close-out protocol — verifies all artifacts in the round were validated, updates aggregate docs (HANDOFF.md, CURRENT_STATE.md, BACKLOG.md, RISKS.md), appends round history, sweeps for cross-doc inconsistency. Use AT THE END of every Phase round (Phase 1 R1, R2, R3 ...) before declaring the round complete and before starting the next round. Distinct from udm-checks-and-balances (which is per-artifact validation); this is per-round aggregation.
---

# UDM Round Close-Out

Per-round meta-skill that runs AFTER all per-artifact validations have completed and BEFORE the next round starts. Ensures the round's state changes propagate to all aggregate documents (HANDOFF, CURRENT_STATE, BACKLOG, RISKS, NORTH_STAR) so a new agent/human picking up at any point has consistent context.

## When to invoke

- End of each Phase round (Phase 1 R1, R2, R3, R4, R5, R6, R7; subsequent phases too)
- Before declaring a round acceptance criterion met
- Before starting the next round
- Before stakeholder review of round deliverables
- After a major mid-round pivot (e.g., a 🔴 forced supersession of an earlier decision)

## When NOT to invoke

- Mid-round, between artifacts (use udm-checks-and-balances for per-artifact)
- For trivial doc edits (typo fixes don't trigger close-out)
- For research-only rounds where no decisions were locked

## Canonical Context Load (CCL) — required before invoking this skill (per D62)

Whoever invokes this skill (main agent or subagent) MUST have performed the Canonical Context Load (per `docs/migration/MULTI_AGENT_GUIDE.md` § Canonical Context Load) before applying this skill's discipline.

- **Stage 0 — Routing manifest** (recommended-not-mandatory; added 2026-05-15 per D62 amendment + D.2 INDEX.md per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.3): `docs/migration/INDEX.md` — read FIRST when uncertain which downstream Stage 1+2+3 docs your task actually needs. Skip when: you already know which Stage 1+2+3 docs to load (typical for recurring task patterns).
- **Stage 1 — Orientation** (mandatory, 4 reads): `NORTH_STAR.md`, `HANDOFF.md`, `CURRENT_STATE.md`, `CHECKS_AND_BALANCES.md`
- **Stage 2 — Risk + Backlog awareness** (mandatory): `RISKS.md`, `BACKLOG.md`, `_validation_log.md`
- **Stage 2.5 — Polish queue skim** (recommended; introduced 2026-05-12 per D113): `POLISH_QUEUE.md` ← skim P-N items the closing round touched; convert any 🟡 Open items the round's substantive work covered into ⚫ CLOSED rows inline; NOT part of artifact-correctness validation (P-items are by construction NOT load-bearing on correctness)
- **Stage 3 — Task-specific reads for this skill**: ALL aggregate docs that may need updating during close-out — `HANDOFF.md`, `CURRENT_STATE.md`, `BACKLOG.md`, `RISKS.md`, `NORTH_STAR.md`, `00_OVERVIEW.md`, `02_PHASES.md`, `MAINTENANCE.md`, `POLISH_QUEUE.md` (Stage 1 already covers HANDOFF / CURRENT_STATE / NORTH_STAR — re-read with intent to update); plus the round's `_validation_log.md` entries
- **Stage 4 — Reference-on-demand**: grep `03_DECISIONS.md` (D-number flips), `04_EDGE_CASES.md` (new cases), `05_RUNBOOKS.md` (new RBs)

If invoked from a subagent context, the subagent's CCL responsibility is hard-required (per agent definition — first `Read` must hit a Stage 1 doc).

**Independence note**: per D55+D56, the close-out reviewer must be a different agent than the round's primary producer. The CCL applies to whoever runs the close-out.

## The close-out checklist

Run all sections; produce a structured report.

### Section 1 — Per-artifact validation completeness

For every artifact produced or modified this round, verify:

- [ ] If it was a substantive change (new doc, new decision, schema DDL, runbook), it has a `_validation_log.md` entry
- [ ] If it was a trivial change (typo, formatting, editorial), it's documented in the round's commit message but doesn't need validation entry
- [ ] No artifact was declared 🟢 Locked without a validation log entry (per D55 + D56 hard rule)

If any artifact is 🟢 without a log entry: **block close-out**; either add the log entry OR revert status to 🟡.

### Section 2 — Decision log updates

- [ ] All decisions added this round have D-numbers in `03_DECISIONS.md`
- [ ] All decisions flipped 🟡 → 🟢 have validation log evidence
- [ ] All decisions superseded have ⚫ status with forward link to the new D-number
- [ ] No decision text contradicts another decision (cross-check against NORTH_STAR.md pillars)

### Section 3 — Edge case register updates

- [ ] Any new edge cases discovered this round added to `04_EDGE_CASES.md` with appropriate series prefix (M/S/I/N/P/G/D/F/V/DP/T/SI/SE/PL) — **14 canonical series total** (updated 2026-05-17 per B-408 atomic 4-skill series-list fix; was stale at 9 since Round 6 DP series addition)
- [ ] Status of existing edge cases updated if this round addressed or changed them
- [ ] Edge case → DDL/runbook/test mapping table is current (where applicable)

### Section 4 — Runbook consistency

- [ ] Any new runbooks follow the When/Pre-flight/Procedure/Validation/Rollback template
- [ ] Runbooks tested in dev where applicable (or marked "untested in dev — pending")
- [ ] Cross-references to runbooks (RB-N) are accurate across docs

### Section 5 — Backlog and risks

- [ ] Any 🟡 follow-ups discovered this round added to `BACKLOG.md` with B-numbers and WSJF scoring
- [ ] Any new delivery risks discovered added to `RISKS.md` with R-numbers and likelihood/impact scores
- [ ] Any closed backlog items moved to "Completed" section
- [ ] Any closed risks moved to "Closed" section

### Section 6 — Aggregate doc updates (THE CRITICAL PART)

This is what the close-out protocol exists to enforce:

#### CURRENT_STATE.md
- [ ] "Recently completed" section reflects this round's 🟢 locked items
- [ ] "Recent rounds" table appended with this round's row
- [ ] "What's pending decision" reflects current 🟡 items
- [ ] "In progress / next" section accurate

#### HANDOFF.md
- [ ] §3 "Locked vs in-flight" — any new 🟢 decisions added; superseded items removed; in-flight items updated
- [ ] §5 "Active risks" — top 5 reflects current RISKS.md state
- [ ] §7 "Skills and subagents" — new skills/agents added if any
- [ ] §8 "Pitfalls" — new lessons learned (3-5 sentence summary; full detail in validation log)
- [ ] §11 "Round history" (new section per D60) — one-line round summary appended
- [ ] §13 "Last updated" date current
- [ ] **§14 "Last updated" narrative** — prepend round-close-out event narrative with cumulative delta (mirrors udm-next-step-cascade Step 1.4 forward-motion discipline; matches "UNTOUCHED-AS-EXPECTED (reason)" requirement); added 2026-05-17 per B-415 closure + Cohort A Agent 54 RC-7 finding (forward-motion cascade enforced HANDOFF §14 update but round-closeout omitted; asymmetry was a discipline gap)

#### BACKLOG.md
- [ ] New B-numbered items appended for this round's 🟡 follow-ups
- [ ] Closed items moved to "Completed" section with closure date
- [ ] WSJF priority sections re-sorted if scores changed

#### POLISH_QUEUE.md (added 2026-05-12 per D113)
- [ ] Skim 🟡 Open P-N items; close any whose underlying cosmetic drift was cleaned up by this round's substantive work (e.g. a doc edit that incidentally refreshed a stale supersession crumb)
- [ ] Add new P-N items for any cosmetic drift surfaced during close-out (status-render mismatch, supersession-crumb absence, stale-date in self-references) that DOESN'T deserve a B-number
- [ ] Confirm closed P-N items have render-discipline-compliant body: strikethrough preserved + closure date + closure-mechanism line per Pitfall #9.j
- [ ] If a P-N item promoted to B-number (rare), strike the P-N row with the new B-number cited as closure mechanism

#### RISKS.md
- [ ] New R-numbered risks appended
- [ ] Mitigated risks moved to "Closed"
- [ ] Quarterly review date updated if reviewed this round

#### NORTH_STAR.md
- [ ] Decisions list updated if new locked decisions affect a pillar
- [ ] Per-phase contribution table reflects round changes
- [ ] No contradictions introduced (e.g., a new decision violates a pillar)

#### 00_OVERVIEW.md
- [ ] Document map reflects any new docs added this round
- [ ] Tier classification correct
- [ ] Document-map links work

### Section 7 — Cross-doc consistency sweep

Run quick checks for the most-common drift patterns:

- [ ] D-number citations consistent (CURRENT_STATE references match 03_DECISIONS)
- [ ] Status fields consistent (a decision marked 🟢 in 03_DECISIONS isn't 🟡 elsewhere)
- [ ] Item counts consistent (HANDOFF "N items in BACKLOG" matches actual BACKLOG length)
- [ ] Last-updated dates consistent across primary docs
- [ ] No "see [doc that doesn't exist]" references

### Section 8 — Validation log entry

- [ ] If close-out surfaced new findings, append a close-out entry to `_validation_log.md`
- [ ] Entry references all artifacts changed this round
- [ ] Entry confirms all 🟢 status flips have validation evidence

### Section 9 — Post-cascade audit (Pattern F, mandatory per D89; added 2026-05-11 post-Round-6)

Per Pattern F doctrine (`MULTI_AGENT_GUIDE.md` § Pattern F), the close-out cascade itself must pass an independent audit BEFORE the round can be declared 🟢 locked. Sections 1-8 above are the producer-side close-out work; Section 9 is the independent verification of that work, paralleling D55 Gate 2 at the round level.

**Sub-section 9.1 — Run Layer 1 (deterministic script)**:

- [ ] Invoke `python3 tools/verify_cascade.py` against the cascade output
- [ ] Capture exit code: 0 (clean) / 1 (🟡 only) / 2 (🔴 BLOCKING) per D74
- [ ] If exit code 2: fix all 🔴 findings; re-run; do not proceed to 9.2 until exit 0 or 1

Layer 1 covers 3 mechanical triggers (no agent variance):
- **Trigger C**: stale B-range / Round-N / count references
- **Trigger D**: forward-cite resolution (RB-* / SP-* / B-* / D-* / R-*)
- **Trigger F**: aggregate-doc Round-N status freshness (02_PHASES.md + PHASE_1_DEEP_DIVE_PLAN.md + HANDOFF §3 in-flight)

**Sub-section 9.2 — Run Layer 2 (paired-judgment agents)**:

- [ ] Spawn TWO independent `udm-cascade-auditor` instances in parallel (single Agent message, multiple tool calls)
- [ ] Both auditors perform CCL Stage 1+2 + Stage 3 (this round's artifacts) independently
- [ ] Compare the two reports finding-by-finding:
   - Agreement on ✅ findings → those triggers verified clean
   - Agreement on 🔴 / 🟡 findings → those gaps must be addressed before lock
   - Disagreement on any finding → flag for orchestrator judgment (default: treat as 🟡 unless one auditor's reasoning is provably stronger)

Layer 2 covers 3 judgment-class triggers:
- **Trigger A**: D-acceptance substantiation — every architectural-review-acceptance decision (D73 / D78 / D83 / D88 and future) has the cycle evidence the variant claim requires
- **Trigger B**: B-item closure-target audit — every "CLOSED" BACKLOG entry has its cited target docs actually reflecting the change
- **Trigger E**: CLAUDE.md convention registration — when round defines new conventions, CLAUDE.md is updated

**Sub-section 9.3 — Apply fixes for any 🔴 findings**:

- [ ] For each 🔴 finding, identify the canonical target doc and apply the fix
- [ ] Re-run Sub-section 9.1 (script) to verify Trigger C/D/F gaps are closed
- [ ] Re-spawn Sub-section 9.2 (paired agents) to verify Trigger A/B/E gaps are closed
- [ ] If second Pattern F audit ALSO returns 🔴 → architectural-review escalation per D73/D78/D83/D88 precedent (this is the cascade-level analog of math-infeasibility-acceptance)

**Sub-section 9.4 — Cycle ledger**:

- [ ] Pattern F audit counts as ONE cycle in the round's cycle ledger (per D72 counting rule)
- [ ] Append Pattern F findings to the round's `_validation_log.md` entry
- [ ] Append cascade-audit specialty event(s) to `_reviewer_effectiveness.md` (one per cascade-auditor instance, plus one for the script run)

**Hard rule**: a round cannot be declared 🟢 Locked while Pattern F shows 🔴. If you find yourself wanting to skip Pattern F "this once," that is the failure mode this discipline exists to prevent — the R6 close-out gaps were 100% in classes Pattern F would catch.

### Section 10 — Self-improvement loop invocation (per D95; added 2026-05-11 at Round 8 close-out)

After Section 9 (Pattern F) completes clean, the round-level discipline runs the self-improvement skill suite. Skills propose deltas; pipeline lead reviews once; `udm-agent-prompt-versioner` applies the approved batch. Loop runs ONCE per round close-out, NOT per cycle.

Hard rule per D95: NO autonomous prompt-rewrite — human review preserved at every batch-apply.

**Sub-section 10.1 — udm-retrospective-collector (8.A)**:
- [ ] First close-out skill. Append per-reviewer-event rows to `_reviewer_effectiveness.md` for this round's cycles. Required: every cycle's `agentId` + `specialty` + `mode` + `🔴/🟡 counts` + `wall-clock minutes` captured at cycle-spawn time
- [ ] Update trend tables (by-specialty catch rate; cumulative empirical findings list)
- [ ] If a Round-N cycle surfaced bugs in regions cleared by prior-round reviewers, apply backward-update rule (increment Subsequent + flip False-clean)

**Sub-section 10.2 — udm-specialty-tuner (8.B)**:
- [ ] Read ledger trends per specialty
- [ ] Apply threshold checks (false-clean > 25% → RETIRE-OR-PAIR; > 10% → REFINE; declining catch trend → EXHAUSTED-SURFACE)
- [ ] Emit `docs/migration/_agent_evolution/specialty-tuner-round<N>-<date>.md` with proposed deltas

**Sub-section 10.3 — udm-subclass-accumulator (8.C)**:
- [ ] Scan this round's 🔴 findings; classify against Pitfall #9 sub-classes 9.a-9.o (15 sub-classes total — updated 2026-05-17 per B-408 atomic fix; was stale at 9.a-9.j missing 9.k arithmetic-propagation + 9.l canonical-schema-detail + 9.m discipline-not-applied + 9.n convention-registration + 9.o anti-rationalization-clause compliance)
- [ ] Cluster unclassified findings; propose new sub-class candidates at ≥2-event evidence threshold
- [ ] Emit `docs/migration/_agent_evolution/subclass-accumulator-round<N>-<date>.md`

**Sub-section 10.4 — udm-producer-checklist-evolver (8.D)**:
- [ ] Identify producer-missable findings (could producer Gate 1 have caught them?)
- [ ] Cluster by missed sub-class; propose directive strengthening at ≥3 events / ≥2 rounds threshold
- [ ] Emit `docs/migration/_agent_evolution/producer-checklist-evolver-round<N>-<date>.md`

**Sub-section 10.5 — udm-cycle-cadence-optimizer (8.E)**:
- [ ] Compute artifact size + cycle count + Pattern E + sleeper-bug + Pattern F + carryover trend for this round
- [ ] Apply per-tier cadence analysis (Tier α/β/γ/δ per D97)
- [ ] Carryover-compounding monitor per B129 (3+ rounds monotonic rise → 🟡 alarm)
- [ ] Emit `docs/migration/_agent_evolution/cycle-cadence-optimizer-round<N>-<date>.md`

**Sub-section 10.6 — udm-cascade-audit-evolver (8.G)**:
- [ ] Read this round's Pattern F findings (Layer 1 + Layer 2)
- [ ] Classify each finding against existing Triggers A-F
- [ ] Cluster unmatched findings; propose new trigger candidates at ≥2-event evidence threshold
- [ ] Emit `docs/migration/_agent_evolution/cascade-audit-evolver-round<N>-<date>.md`

**Sub-section 10.7 — User-review session + udm-agent-prompt-versioner (8.F)**:
- [ ] Pipeline lead reviews ALL proposed deltas from 10.2-10.6 in ONE session
- [ ] Per delta: YES (apply) / NO (skip) decision documented inline in the session notes
- [ ] Skill 8.F invoked with approved batch (the N-of-M YES'd deltas)
- [ ] Per delta: skill verifies `before_text` matches current file content (abort 🔴 on drift); copies current `.claude/agents/<name>.md` to `_archive/<name>-v<prior>-<date>.md`; applies delta; bumps semver per change_type (MAJOR/MINOR/PATCH); appends changelog row to `docs/migration/_agent_evolution/<name>-changelog.md`
- [ ] Auto-revert path: if a delta applied at Round N close-out shows regression in Round N+1's first cycle, 8.F auto-reverts at Round N+1 close-out (copies prior version back; appends REVERT changelog row)

**Sub-section 10.8 — Cycle ledger**:
- [ ] Self-improvement loop counts as ONE cycle in the round's cycle ledger (combined invocation; not 7 separate cycles)
- [ ] Append self-improvement findings + applied-delta count to round's `_validation_log.md` entry
- [ ] Append 8.F changelog event(s) to `_reviewer_effectiveness.md` if any agent prompt was modified (track delta application as evidence for next round's specialty-tuner)

**Hard rule**: the self-improvement loop is bounded — runs at close-out only, NOT mid-round. Mid-round prompt edits violate D95 hard rule (human-in-the-loop preserved at every batch-apply, with batches anchored to round close-out cadence).

**Bounds (per SELF_IMPROVEMENT_DISCIPLINE.md § Bounds)**: FREEZE the loop if (1) specialty effectiveness declines 2 rounds in a row, OR (2) applied delta introduces fresh-instance bug class, OR (3) carryover items monotonically rising 3+ rounds, OR (4) user declines 50%+ deltas in 2 consecutive rounds, OR (5) skill output 🔴 cites locked D-number contradiction. Frozen loop documented inline at close-out; unfreeze requires D-numbered decision.

## Output structure

```markdown
# Round Close-Out Report: <round name>
## Date: <YYYY-MM-DD>
## Reviewer: <agent or human>

### Section 1: Per-artifact validation completeness
- Status: ✅ / 🔴
- Issues: <list>

### Section 2: Decision log updates
- Status: ✅ / 🟡 / 🔴
- Decisions added: <list>
- Decisions superseded: <list>
- Issues: <list>

### Section 3: Edge case register updates
- New edge cases: <list>
- Updated edge cases: <list>

### Section 4: Runbook consistency
- New runbooks: <list>
- Issues: <list>

### Section 5: Backlog and risks
- New B-items: <list>
- New R-items: <list>
- Closed items: <list>

### Section 6: Aggregate doc updates
- CURRENT_STATE.md: ✅ / 🟡 / 🔴 with notes
- HANDOFF.md: ✅ / 🟡 / 🔴 with notes (§3, §5, §7, §8, §11, §13 individually)
- BACKLOG.md: ✅ / 🟡 / 🔴
- RISKS.md: ✅ / 🟡 / 🔴
- NORTH_STAR.md: ✅ / 🟡 / 🔴
- 00_OVERVIEW.md: ✅ / 🟡 / 🔴

### Section 7: Cross-doc consistency
- Drift items found: <list>
- Status: ✅ / 🟡 / 🔴

### Section 8: Validation log
- Close-out entry appended: yes/no

### Section 9: Pattern F post-cascade audit
- Layer 1 (script) exit code: 0 / 1 / 2
- Layer 1 🔴 findings: <count>
- Layer 1 🟡 findings: <count>
- Layer 2 (paired agents) instance 1: PASS / FIXES-REQUIRED / BLOCKING
- Layer 2 (paired agents) instance 2: PASS / FIXES-REQUIRED / BLOCKING
- Layer 2 agreement: <count agreement / count disagreement>
- Overall Pattern F verdict: ✅ / 🟡 / 🔴
- Fixes applied this audit: <list>

## Overall verdict
- ALL ✅: round closed; cleared to start next round
- Any 🟡: close with follow-ups (track in BACKLOG)
- Any 🔴: BLOCKED; fix before declaring round complete

## Action items
1. <follow-up #1>
2. <follow-up #2>

## What changed this round (one-line summary for HANDOFF round history)

<one sentence — the round's biggest deliverable>
```

## Hard rules

1. **Don't skip aggregate doc updates.** "I'll update HANDOFF later" → it never happens. Round close-out IS when HANDOFF gets updated.
2. **Independent reviewer for the close-out itself**. The close-out IS a validation step (Gate-equivalent for the round); per D55/D56, the close-out reviewer should be a different agent than the round's primary producer.
3. **Append, don't overwrite.** Round history grows; old rounds stay visible. Same as `_validation_log.md`.
4. **One-line summary discipline.** The "what changed this round" output is ONE sentence. Force the writer to compress; if it can't be compressed, the round was too sprawling.
5. **🟢 lock requires close-out completion.** A round is not "Locked" until the close-out checklist is 100% green. Status mismatches between artifact-level 🟢 and round-level 🟢 are caught here.

## Anti-patterns

- ❌ Closing a round without updating HANDOFF.md
- ❌ Closing a round without verifying CURRENT_STATE matches 03_DECISIONS status
- ❌ Treating round close-out as "done when artifacts are done" — close-out is its own work
- ❌ Same agent producing the round's artifacts AND running the close-out (independence required)
- ❌ Multi-paragraph "what changed this round" summary — discipline of compression
- ❌ Skipping the cross-doc consistency sweep because "it looked fine"

## Composition

| Used in concert with | Role |
|---|---|
| `udm-checks-and-balances` skill | Runs FIRST, per artifact; close-out runs LAST, per round |
| `udm-decision-recorder` skill | Records D-numbers; close-out verifies they all landed |
| `udm-edge-case-validator` skill | Validates edge case coverage; close-out verifies register updated |
| `udm-runbook-author` skill | Authors runbooks; close-out verifies template adherence |
| `udm-design-reviewer` agent | Per-artifact QA; close-out is meta-QA |
| `udm-researcher` agent | Outputs findings; close-out verifies no orphan research output |

## Tracking

Each round close-out should produce an entry in `_validation_log.md` (or note "close-out clean — no validation issues" inline in the round's existing entry). Pattern: every round has a close-out trail in the audit log.

## Example invocations

- "Round 1 v3 schema is locked. Run round close-out before starting Round 2."
- "We just finished the PM-mindset / research agent round. Run close-out to make sure HANDOFF reflects the new state."
- "Phase 0 deliverables 0.11 + 0.12 just landed. Round close-out for the Phase 0 mini-cycle."

## When the discipline isn't worth it

A round consisting of a single trivial change (e.g., one typo fix) doesn't warrant the full close-out. Apply judgment:

- If round produced or changed 1-2 artifacts AND no status flips: skip; commit as trivial edit.
- If round produced or changed 3+ artifacts OR any status flip: run full close-out.

Default: run the full close-out unless the round is genuinely trivial.
