# Checks and Balances Discipline

This document defines the validation discipline that every significant artifact in this project must pass through before being considered complete. It exists because the project's first 13 rounds produced bugs that could have been caught with a routine validation step, but that step was skipped.

## The principle

> Producing an artifact is not the same as validating it.

After every meaningful change — a schema doc update, a new decision, a runbook addition, a phase round acceptance — the artifact must be validated independently before it is declared complete or moved out of pending state.

## Why this discipline matters

After 14 planning rounds, the reflection agent (round 13) reviewed `phase1/01_database_schema.md` v1 and identified 8 critical issues including:
- A concurrency race condition in SP-1 (`PiiVault_GetOrCreateToken`) — the lookup-then-INSERT pattern would have produced duplicate tokens under load
- A partition function time-bomb (PipelineLog stops accepting INSERTs at end of 2026 without a rollover job)
- An idempotency gap in PiiTokenizationBatch (no UNIQUE constraint)
- Missing tables for D40 (SchemaContract) and P2 (OrphanedTokenLog)

All 8 of these issues would have been caught by a routine validation step at the time the schema doc was first produced. They weren't, because validation wasn't a routine step.

This discipline makes validation a routine step.

## Canonical Context Load (CCL) required before validation (per D62)

Before invoking this discipline (or any of its constituent gates), the agent / skill / human running validation MUST perform the **Canonical Context Load** documented in `MULTI_AGENT_GUIDE.md` § Canonical Context Load. CCL is a precondition to operating under this discipline.

- **Stage 1 — Orientation** (mandatory, 4 reads): `NORTH_STAR.md`, `HANDOFF.md`, `CURRENT_STATE.md`, this document (`CHECKS_AND_BALANCES.md`)
- **Stage 2 — Risk + Backlog awareness** (mandatory): `RISKS.md`, `BACKLOG.md`, `_validation_log.md`
- **Stage 2.5 — Polish-queue skim** (optional but recommended at round close-out): `POLISH_QUEUE.md` ← cosmetic / readability tracker (P-numbers); skim to convert any 🟡 items the closing round's work touches into ⚫ CLOSED rows; NOT part of artifact-correctness validation (P-items are by construction NOT load-bearing on correctness)
- **Stage 3 — Task-specific reads**: the artifact under review (or the artifact set, when reviewing related artifacts together) plus its dependent docs (e.g., `01_ARCHITECTURE.md` for schema; `06_TESTING.md` for tests)
- **Stage 4 — Reference-on-demand**: grep `03_DECISIONS.md` (D-numbers), `04_EDGE_CASES.md` (series IDs), `05_RUNBOOKS.md` (RB-numbers)

**Verification rule**: the validator's first content-substantive tool call (`Read` or `Grep` with content output) MUST hit a Stage 1 doc. Glob-only or filesystem-listing calls before Stage 1 do not violate the rule. Tool-trace audit confirms compliance at round close-out.

**Self-edit fallback**: if a Stage 1 doc IS the artifact under review (e.g., editing NORTH_STAR.md itself, or editing this discipline doc), the Stage 1 reads still run BEFORE the edit; the artifact-as-target is then read again under Stage 3 with intent-to-edit framing. The first read counts toward CCL compliance.

## The five gates

Every artifact passes through five gates before being considered complete. The gates are ordered but can be parallelized where independent.

### Gate 1 — Cross-reference

Verify the artifact is consistent with the rest of the doc set.

| Check | Pass criterion |
|---|---|
| Does it cite the right D-numbers? | All cited decisions match status / scope in `03_DECISIONS.md` |
| Does any cited decision contradict it? | No contradictions |
| Are other docs that reference this still accurate? | Cross-doc updates listed and applied |
| If superseding a prior artifact, is the supersession clean? | Old artifact marked ⚫; new one references the chain |
| **D105 SQL naming standards check (added 2026-05-11)** — does the artifact introduce or reference any NEW stored procedure or view DB object? | Every NEW SP object name matches `General.{schema}.Proc{ProcedureName}`; every NEW SP file name matches `{schema}_Proc{ProcedureName}.sql`; every NEW view object name matches `General.{schema}.Vw{ViewName}`; every NEW view file name matches `{schema}_Vw{ViewName}.sql`. Pre-D105 SP/view names cited unchanged (grandfather clause per D92) are NOT flagged. See `CLAUDE.md` § "SQL Naming Standards (D105 — MANDATORY)" + `03_DECISIONS.md` D105. |
| **D103 Claude Code security model check (added 2026-05-11)** — does the artifact introduce or reference any credential path, `.env` file, GPG file, or SSH key? | Every NEW credential path appears in BOTH `.claudeignore` (documentation) AND `.claude/settings.local.json` `permissions.deny` (enforcement); credential paths live OUTSIDE `/debi`; `.env` references use `/etc/pipeline/.env` (canonical per D103, legacy `/debi/.env` flagged for B182 migration); `PiiVault.EncryptedPlaintext` uses AES-256-GCM per D102. See `docs/migration/SECURITY_MODEL.md` for the canonical 13-layer model. |

### Gate 2 — Quality assurance (independent review)

A second pair of eyes confirms correctness.

| Approach | When to use |
|---|---|
| Invoke `udm-design-reviewer` agent | Code, schema, runbook artifacts |
| Spawn a generic reflection agent | Architecture / strategy artifacts |
| Get a human reviewer | When stakes are highest (PII, vault, financial logic) |

Mandatory: review must produce a structured report with categorized findings (✅ / 🟡 / 🔴). 🔴 items block validation.

### Gate 3 — Edge case enumeration

Walk the M/S/I/N/P/G/D/F/V series. For each:

| Outcome | Meaning |
|---|---|
| ✅ Addressed | This artifact handles the case (specify how) |
| 🆕 New case | Walking surfaced a new edge case; add to register |
| ⚪ Not applicable | Doesn't apply here (specify reason) |
| ➡️ Addressed elsewhere | Reference the doc/section that handles it |
| 🔴 Gap | Should be addressed but isn't (must fix or document deferral) |

### Gate 4 — Edge case validation

For every ✅ from Gate 3, the case has a tangible verification:

| Verification type | Example |
|---|---|
| Tier 1 / Tier 2 test | `tests/unit/test_filter_null_pks.py` proves P0-4 enforcement |
| CHECK constraint | `CK_PiiVault_Status` enforces D45.6 status enum |
| UNIQUE index | `UX_PiiTokenizationBatch_Identity` proves I3 mitigation |
| Stored procedure | SP-1's UPDLOCK + HOLDLOCK pattern proves I3 (vault) |
| Runbook step | RB-9 step "verify ack" proves F18 mitigation |

If a case is "addressed" but not actually verified, downgrade to 🟡 and add a follow-up.

### Gate 5 — Idempotency / regression

Verify the artifact preserves the master idempotency invariant (D15) and doesn't regress previously-validated work.

| Check | Question |
|---|---|
| D15 invariant | Does this artifact's behavior produce zero net writes on identical-input retry? |
| Decision regression | Is any locked decision contradicted? |
| Cross-table regression | Does this break a constraint or pattern in another table? |
| Runbook regression | Does this invalidate a runbook procedure? |

## Output of validation

A validation pass produces an entry in `docs/migration/_validation_log.md` with this structure:

```markdown
## <date>: <artifact path>

| Gate | Status | Notes |
|---|---|---|
| 1: Cross-reference | ✅ | <list of cross-doc updates applied> |
| 2: QA | ✅ | <reviewer; key findings; resolution> |
| 3: Edge case enumeration | ✅ | <series walked; new cases added>: <count> |
| 4: Edge case validation | ✅ | <verifications>: <count> |
| 5: Idempotency | ✅ | <D15 preserved; no regressions> |

**Overall**: ✅ Validated; <decision/round/runbook> can be locked.
**Follow-ups**: <list, if any>
```

Validation log entries are append-only — never edit or delete. They are the audit trail for "this artifact was validated" claims.

## Status semantics revisited

| Status | Meaning |
|---|---|
| 🟡 Proposed | Artifact exists; validation has NOT occurred |
| 🟢 Locked | Artifact validated through all 5 gates; no 🔴 |
| 🟡 Validated-with-follow-ups | All 5 gates passed but 🟡 items tracked in CURRENT_STATE |
| 🔴 Blocked | Validation found 🔴; must fix before lock |
| ⚫ Superseded | Replaced by a newer artifact (link forward) |

The most important invariant: **🟢 Locked means validated**. If an artifact is 🟢 without an entry in `_validation_log.md`, that's a status mismatch and must be corrected.

## Anti-patterns this discipline catches

- ❌ "I made the change; declaring it locked." — Self-review skipped
- ❌ "Edge case X doesn't apply." (no reason given) — Gate 3 incomplete
- ❌ "Tests will be added later." — Gate 4 deferred without tracking
- ❌ "We discussed it, so it's locked." — Validation not separate from discussion
- ❌ Plowing forward to next round before validating current — Compounding debt

## Second-pass validation (D56)

When first-pass validation finds 🔴 blockers, fixes are applied. **Per D56, those fixes must receive an independent second-pass validation before the artifact is locked.**

### Why second-pass is mandatory after 🔴

The most common failure mode of fix-then-declare-done:
- First-pass identifies 🔴 X
- Producer applies fix Y to address X
- Producer declares "X is fixed; we're done"

Two failure modes invisible to the producer:
1. **Fix Y doesn't actually solve X** — pattern is similar but the bug is still latent
2. **Fix Y introduces NEW 🔴 Z** — the fix accidentally breaks something else

Both happen routinely. The reflection-agent-on-Round-1-v2 caught a bug introduced by a fix to the v1 SP-1 lookup-then-INSERT issue — the v2 fix interacted badly with the Status-flip pattern from D45.6.

### Second-pass discipline

| Step | Required? |
|---|---|
| Independent reviewer (different agent than first-pass) | YES |
| All 5 gates re-walked, not just the failing ones | YES |
| Specifically verify the 🔴 fixes work | YES |
| Specifically verify no NEW 🔴 from the fixes | YES |
| Idempotency / regression re-check (Gate 5) | YES |
| Append separate entry to `_validation_log.md` | YES |
| Cross-reference first-pass and second-pass entries | YES |
| Status flip 🟡 → 🟢 | After second-pass returns clean |

### Second-pass output structure

```markdown
## <date> — <artifact path> (SECOND-PASS)

**Reviewer**: independent second-pass agent
**Trigger**: post-fix validation per D56
**First-pass entry**: <date and agentId of first-pass>
**Fixes applied between passes**: <list>

### Re-walked gates
| Gate | Status | Notes |
| 1 | ✅ | <verification of cross-doc fixes> |
| 2 | ✅ | <verification of fix correctness> |
| 3 | ✅ | <re-walked series, new cases?> |
| 4 | 🟡 | <test deferrals tracked> |
| 5 | ✅ | <regression check; no new 🔴> |

### Verdict
- ✅ Locked: artifact ready for downstream consumers
- 🟡 Validated-with-followups: 🟡 items tracked in CURRENT_STATE
- 🔴 Still blocked: list new issues; another fix-validate cycle required

### Action items
1. <minor 🟡 polish — non-blocking>
```

### When second-pass NOT required

- First-pass returned ALL ✅ with only 🟡 follow-ups (no 🔴 ever existed) — second-pass is optional but encouraged for high-stakes artifacts (PII, financial, regulatory)
- Trivial edits (typos, formatting)
- Editorial re-org without behavior changes

### Iterative validation cycles (per D72 termination rule — added 2026-05-10)

If a validation cycle (single agent OR parallel multi-agent batch) finds 🔴:
1. Document those 🔴 in the cycle's entry
2. Apply fixes
3. Run a NEW cycle (different agent / fresh agents)
4. Iterate per D72 convergence rule (below)

**D72 termination rule** (locked 2026-05-10):
- **Cycle definition**: one cycle = one independent review pass (single agent OR parallel multi-agent batch)
- **Cycle ceiling**: max 10 cycles per round before mandatory architectural-review escalation
- **Convergence rule**: **3 consecutive cycles returning CLEAN** (no 🔴, only backlog-eligible 🟡) → cycle terminates; artifact may flip 🟡 → 🟢 Locked
- **Counting rule**: each parallel multi-agent batch counts as ONE cycle
- **Reset rule**: any "not clean" cycle resets the consecutive-clean counter to 0
- **Escalation rule**: if the 10th cycle still hasn't produced 3 consecutive clean cycles, escalate to architectural review

Round 2 + Round 3 evidence: standard D56 single-agent sequential passes have structural blind spots (Pitfall #9 cross-table column-name-lift sub-class). Multi-agent parallel validation (introduced 2026-05-10 in Round 3) is a structural fix for that blind spot. D72 codifies how the two compose: keep iterating until 3 clean in a row, or escalate at 10.

In practice this rarely goes beyond third- or fourth-cycle. If it does, the underlying design has bigger issues than incremental fixes can resolve — architectural review path is the escape valve.

## When to skip (the only exceptions)

- **Trivial edits**: typo fixes, formatting changes, renaming for consistency. No new behavior, no new decision, no new constraint. These don't need validation.
- **Documentation re-organization**: moving a section between docs without changing content. Track via git commit; no validation log entry needed.
- **Editorial corrections**: clarifying wording without changing meaning.

If unsure whether a change is trivial: it isn't. Validate.

## Application to past artifacts

The retrospective gap: 49 decisions are 🟢 Locked but no validation log exists for them. The realistic remediation:

1. Going forward (mandatory): every new artifact and every status change runs the gates.
2. Backward-looking (optional, prioritized): when an existing 🟢 decision is referenced in new work, run a quick retroactive validation pass on it. Build the validation log incrementally rather than retroactively in bulk.

Don't try to validate all 49 decisions in a backfill pass — that's its own project. Validate as the work touches them.

## Integration with other skills / agents

| Skill / agent | Role in validation |
|---|---|
| `udm-checks-and-balances` skill | Orchestrates the five gates |
| `udm-design-reviewer` agent | Gate 2 (independent QA) |
| `udm-edge-case-validator` skill | Gate 3 (edge case walk) |
| `udm-test-author` agent | Gate 4 (test-based verification) |
| `udm-decision-recorder` skill | Updates `03_DECISIONS.md` after validation |
| `udm-runbook-author` skill | Final structure check on runbooks |

The orchestration:

```
Artifact ready → invoke udm-checks-and-balances
                      ↓
                 Gate 1: cross-reference (manual or via skill output)
                      ↓
                 Gate 2: spawn udm-design-reviewer or general agent
                      ↓
                 Gate 3: invoke udm-edge-case-validator
                      ↓
                 Gate 4: invoke udm-test-author for test gaps
                      ↓
                 Gate 5: regression check (manual)
                      ↓
                 All ✅ → write _validation_log.md entry → flip status to 🟢
                 Any 🔴 → block, fix, re-validate
```

## Round close-out (D60) + Pattern F post-cascade audit (D89-D91)

Per-artifact validation (this skill) is the ENTRY discipline. **Round close-out is the EXIT discipline** — applied at the end of each round, after all per-artifact validations have run, to ensure aggregate documents (HANDOFF.md, CURRENT_STATE.md, BACKLOG.md, RISKS.md, NORTH_STAR.md, 00_OVERVIEW.md) reflect the round's outcomes.

Without round close-out, HANDOFF.md and similar living docs drift from reality after every round. The discipline:

```
Per-artifact validation (this doc — udm-checks-and-balances) → produces validation log entries
   ↓
Round close-out (udm-round-closeout) → updates aggregate docs; appends to HANDOFF round history
   ↓
Pattern F post-cascade audit (D89-D91; per Section 9 of udm-round-closeout) → independent verification of cascade work
   ↓
Round complete; next round can begin
```

**Independence requirement**: round close-out reviewer ≠ round's primary producer. Same independence pattern as D55/D56.

**Pattern F discipline (D89/D90/D91)** is the round-level analog of Gate 2 (independent QA). Added 2026-05-11 per R28 + Pitfall #11 — Round 6 close-out cascade shipped 7 structural gaps despite extensive artifact-level validation; producer-self-attestation at round level had no Gate-2 equivalent. Pattern F structure:
- **Layer 1 deterministic script** (`tools/verify_cascade.py`) — Triggers C (stale references) / D (forward-cite resolution) / F (aggregate-doc Round-N freshness). 100% deterministic; zero agent variance.
- **Layer 2 paired-judgment agents** (`udm-cascade-auditor` × 2 instances) — Triggers A (D-acceptance substantiation) / B (B-item closure-target audit) / E (CLAUDE.md convention registration). Invoked as PAIR — never single instance per D89 hard rule. Findings compared; agreement → cycle clean; disagreement → cascade fix-cycle.

Pattern F is mandatory at every round close-out before round 🟢 lock. **🟢 Locked 2026-05-11 post-Round-7 first-production invocation** — paired-agent Layer 2 surfaced 5-8 cascade gaps producer reflection + 8 cycles of artifact-level Pattern E validation missed (B146-B155 BACKLOG silent omission; Stage 1 NORTH_STAR D-list stale; cascade-doc Round 7 status drift; etc.). 4-event Pattern F evidence base extending at Round 8 close-out (R6 retroactive + R6 unscoped + R7 first-production + R8 close-out); 8-event cascade-audit specialty 0% false-clean post-Round-8. R28 score reduced Medium×High=6 🔴 → Low×Medium=2 ⚪ post-mitigation. D89/D90/D91 thesis empirically substantiated.

See `.claude/skills/udm-round-closeout/SKILL.md` for the full close-out checklist (now 10 sections — Section 9 = Pattern F; Section 10 = self-improvement loop per D95). See `docs/migration/MULTI_AGENT_GUIDE.md` § Pattern F for doctrine.

## Round close-out + Self-improvement loop (D95-D99 — added 2026-05-11 post-Round-8)

After Section 9 (Pattern F) completes clean, the close-out cascade runs Section 10 (self-improvement loop per D95) before round 🟢 lock. The loop runs ONCE per round close-out (NOT per cycle) and consists of:

1. `udm-retrospective-collector` (8.A) — auto-appends per-reviewer-event rows to `_reviewer_effectiveness.md`
2. `udm-specialty-tuner` (8.B) — propose specialty refinements
3. `udm-subclass-accumulator` (8.C) — propose new Pitfall #9 sub-classes at 2-event evidence
4. `udm-producer-checklist-evolver` (8.D) — propose producer Gate 1 strengthening
5. `udm-cycle-cadence-optimizer` (8.E) — propose per-tier cadence calibration (Tier α/β/γ/δ per D97)
6. `udm-cascade-audit-evolver` (8.G — B143 implementation) — propose Pattern F trigger evolution
7. **User reviews proposed deltas in ONE session per round; approves YES/NO per delta** → `udm-agent-prompt-versioner` (8.F) applies approved batch with semver versioning + archive (per D98)

Hard rule per D95: NO autonomous prompt-rewrite — human review preserved at every batch-apply. Bounded compute (close-out only, NOT per cycle). Reversibility per D98 (every prompt change has archived predecessor; auto-revert on regression at next round close-out).

See `docs/migration/SELF_IMPROVEMENT_DISCIPLINE.md` for the full discipline + escape conditions (FREEZE the loop). See `phase1/08_sub_agent_self_improvement.md` for the Round 8 spec doc.

## Cadence of enforcement

| Trigger | Run gates? |
|---|---|
| Decision flip 🟡 → 🟢 | YES (mandatory) |
| Round acceptance criterion met | YES (mandatory) |
| Phase deliverable marked ✅ | YES (mandatory) |
| New runbook added | YES (mandatory) |
| New stored procedure body | YES (mandatory) |
| Round v2 / v3 iteration | YES (this is where we keep skipping) |
| Trivial edits / typo fixes | NO |
| Editorial re-organization | NO |

## Why this is in the project

This document and the corresponding skill exist because the user (rightly) flagged that the project was producing artifacts faster than it was validating them. The 8 issues found by the reflection agent in round 13 would have been caught at production time if this discipline had been in place from round 1. The discipline is now in place.

## Owner

The discipline is owned by the pipeline lead. Operationally:
- Each artifact owner runs the gates before declaring complete
- Each phase lead reviews `_validation_log.md` at round closeout
- Discipline gaps surfaced in retrospective become items in this doc

## Related decisions

- D55 (this discipline) — to be added to `03_DECISIONS.md`
- D15 (master idempotency invariant) — gate 5 enforces this
- D17 (idempotency ledger) — gate 4 verifies via tests
- D45-D49 (Phase 1 Round 1 work) — should have run gates; the v2 iteration is where we apply retroactively
