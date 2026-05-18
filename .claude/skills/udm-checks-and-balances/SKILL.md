---
name: udm-checks-and-balances
description: Enforces the deep-dive validation cycle (steps 2-5 — Validate Plan / QA / Edge Cases / Validate Edge Cases) before any artifact is declared complete or any decision flipped to 🟢 Locked. Use BEFORE merging schema doc changes, BEFORE flipping decisions to Locked, BEFORE closing any round, BEFORE removing items from CURRENT_STATE pending list. Catches the failure mode where artifacts get produced and then immediately marked "done" without independent verification.
---

# UDM Checks and Balances

The discipline that prevents "produced means validated." Every significant artifact passes through this skill before it's considered complete.

## When to invoke

This skill is triggered by ANY of:

- Before a 🟡 → 🟢 decision status change in `03_DECISIONS.md`
- Before a Round acceptance criterion is declared met
- Before a phase deliverable is marked ✅ in `02_PHASES.md`
- Before a runbook is added to the active set in `05_RUNBOOKS.md`
- Before a stored procedure body is locked
- Before pending items leave `CURRENT_STATE.md`'s pending list
- After making any v2/v3 iteration on a doc (the most common skip point)

## Canonical Context Load (CCL) — required before invoking this skill (per D62)

Whoever invokes this skill (main agent or subagent) MUST have performed the Canonical Context Load (per `docs/migration/MULTI_AGENT_GUIDE.md` § Canonical Context Load) before applying this skill's discipline.

- **Stage 0 — Routing manifest** (recommended-not-mandatory; added 2026-05-15 per D62 amendment + D.2 INDEX.md per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.3): `docs/migration/INDEX.md` — read FIRST when uncertain which downstream Stage 1+2+3 docs your task actually needs. Skip when: you already know which Stage 1+2+3 docs to load (typical for recurring task patterns).
- **Stage 1 — Orientation** (mandatory, 4 reads): `NORTH_STAR.md`, `HANDOFF.md`, `CURRENT_STATE.md`, `CHECKS_AND_BALANCES.md` (this very doc — re-read with the eye of an enforcer)
- **Stage 2 — Risk + Backlog awareness** (mandatory): `RISKS.md`, `BACKLOG.md`, `_validation_log.md`
- **Stage 2.5 — Polish queue skim** (recommended; introduced 2026-05-12 per D113): `POLISH_QUEUE.md` ← skim 🟡 Open P-N items. **Gate 1 (cross-reference) findings that are cosmetic-only** (stale supersession crumbs, status-render badge drift, stale dates, missing P-N awareness in cited cascade docs) **should be proposed as P-numbers for POLISH_QUEUE.md, NOT as B-numbers for BACKLOG.md**. Distinguishing test: does fixing change a decision body / runbook / SP / tool spec / pipeline code? If YES → B-number per Gate 1 7c convention; if NO → P-number candidate (note in gate findings with proposed P-text + closure target; round-close-out cascade absorbs). Avoids polluting BACKLOG WSJF view with cosmetic items per D113.
- **Stage 3 — Task-specific reads for this skill**: the artifact under review + the artifact's dependent docs (e.g., `01_ARCHITECTURE.md` if schema; `06_TESTING.md` if tests)
- **Stage 4 — Reference-on-demand**: grep `03_DECISIONS.md` (D-number), `04_EDGE_CASES.md` (series), `05_RUNBOOKS.md` (RB-number)

For Gate 2 specifically: spawn `udm-design-reviewer` agent — it performs its own CCL (Stage 1+2 hard-required by its operating model). If you launch the agent without including the CCL invocation clause in the prompt, you've bypassed the discipline.

If invoked from a subagent context, the subagent's CCL responsibility is hard-required (per agent definition — first `Read` must hit a Stage 1 doc).

## The five validation gates

Each gate must produce a written outcome (✅ pass / 🟡 partial / 🔴 fail). All five must be ✅ before the artifact is considered validated.

### Gate 1: Cross-reference validation

Goal: verify the artifact is consistent with the rest of the doc set.

```
For the artifact under review, walk these checks:
- Does it cite the right D-numbers from 03_DECISIONS.md?
- Does any decision it cites contradict it?
- Does any other doc (architecture, runbook, edge case) need updating to match this artifact?
- Are referenced sections in OTHER docs still accurate after this change?
```

Output: a list of cross-doc updates required. If non-empty, those updates must land before validation proceeds.

### Gate 2: Quality assurance (independent review)

Goal: an independent agent or reviewer confirms the artifact is correct.

```
- Spawn the udm-design-reviewer agent on the artifact
- OR get a second engineer to review
- Surface bugs / design issues / non-idiomatic patterns
- Each finding categorized: ✅ correct / 🟡 concern / 🔴 bug
```

Output: review report. 🔴 items block validation.

### Gate 3: Edge case enumeration

Goal: walk the M/S/I/N/P/G/D/F/V series and catalog applicability.

```
For each series:
- For each edge case in the series:
  - Does this artifact address it? (✅ Yes — and how)
  - Does this artifact create a NEW related case? (🆕 — add to register)
  - Is the case not applicable here? (⚪ Not applicable, with reason)
  - Is the case addressed elsewhere? (➡️ Reference)
- If GAP: 🔴 — add new edge case to register OR explicitly defer with rationale
```

Output: edge case coverage report. 🔴 gaps require either new register entries or documented deferrals.

### Gate 4: Edge case validation

Goal: each addressed edge case has a tangible verification — a test, a constraint, a runbook step, or documented behavior.

```
For each ✅ in Gate 3:
- Is there a Tier 1 or Tier 2 test covering this?
- If not test: is there a CHECK constraint, UNIQUE index, or stored procedure that enforces?
- If not enforcement: is there a runbook procedure that handles?
- If none of the above: it's not actually addressed; downgrade to 🟡 or 🔴
```

Output: addressed-but-unverified items. Each must either be verified, deferred (with rationale + new entry), or have a test/runbook/constraint added.

### Gate 5: Idempotency / regression / risk check (D15 + D61)

Goal: confirm the artifact doesn't break previously-validated work, doesn't violate the master idempotency invariant (D15), and surfaces any new delivery risks.

```
- For schema changes: do existing decisions still hold? E.g., adding a column shouldn't break I3 dedup pattern
- For procedure changes: does same input → same output? Does retry produce no extra writes?
- For decision changes: does any superseded decision properly link to the replacement? Are downstream artifacts updated?
- For runbook changes: are pre-flight, validation, and rollback complete?

D61 risk surfacing:
- Does this artifact create new delivery risk? (Distinct from technical edge cases — risks are about delivering the project)
- Does it mitigate any existing risk in RISKS.md? Cite R-number
- Does it escalate or de-escalate any existing risk?
- For each new risk: propose R-number, likelihood × impact score, owner, mitigation
```

Output: regression report + risk delta report. 🔴 = artifact regresses something already validated; must fix before locking. Risk delta is informational (rarely 🔴 unless the new risk is critical).

## Backlog-surfacing (per D61)

Every gate's 🟡 finding includes a proposed B-number for `BACKLOG.md`:

```
🟡 finding: <description>
  Proposed BACKLOG entry: B<NEXT_AVAILABLE>, COD=<1-5>, JS=<1-5>, WSJF=<calc>
```

Round close-out (per D60) uses these proposals to append directly to BACKLOG.md without re-deriving the items.

## Output structure

```markdown
# Validation Report: <artifact name>
## Date: <date>
## Reviewer: <agent or human>

### Gate 1: Cross-reference
- [ ] No contradictions with locked decisions
- [ ] All cited D-numbers are correct
- [ ] Cross-doc updates: <list>
Status: ✅ / 🟡 / 🔴

### Gate 2: Quality assurance
- [ ] Independent review completed
- [ ] No 🔴 findings, OR all 🔴 findings resolved
- [ ] 🟡 findings documented for follow-up
Status: ✅ / 🟡 / 🔴

### Gate 3: Edge case enumeration
- M-series walked: ...
- S-series walked: ...
- I-series walked: ...
- (etc. for N, P, G, D, F, V)
- New edge cases identified: <list>
- Gaps: <list>
Status: ✅ / 🟡 / 🔴

### Gate 4: Edge case validation
- Verified via tests: <list>
- Verified via constraints/SPs: <list>
- Verified via runbooks: <list>
- Unverified (still 🟡): <list with action>
Status: ✅ / 🟡 / 🔴

### Gate 5: Idempotency / regression
- D15 master invariant preserved
- No previously-validated artifact regressed
- Idempotency property preserved on retry
Status: ✅ / 🟡 / 🔴

## Overall verdict
- ALL ✅: artifact validated; can proceed to lock
- Any 🟡: validate-with-followups (track in CURRENT_STATE)
- Any 🔴: blocked; must fix before declaring complete

## Action items
1. <follow-up #1>
2. <follow-up #2>
```

## Hard rules

1. **Validation must precede status flip.** If a decision is 🟡 → 🟢, this skill ran first. If it didn't, the decision is 🔴 with status mismatch.
2. **Independent review.** Gate 2 cannot be done by the same agent that produced the artifact. Self-review = no review.
3. **All five gates run.** Skipping a gate to save time is a documented anti-pattern.
4. **Every gate's output is recorded.** Validation has artifacts, not just claims.
5. **🟡 ≠ ✅.** Partial validation is partial; track in CURRENT_STATE.
6. **🔴 blocks lock.** No exceptions. If urgency requires moving forward, supersede the decision (new D-number) rather than skipping validation.

## Anti-patterns

- ❌ "I made the change; it looks right" — not a validation pass
- ❌ Self-reviewing your own artifact under Gate 2
- ❌ "Edge case X doesn't apply" without writing the reason
- ❌ Marking ✅ at a gate just to clear the gate
- ❌ Skipping Gate 4 because Gate 3 was painful
- ❌ Locking a decision without having actually walked the gates
- ❌ Running gates serially when they could be parallel (Gates 1 + 2 are independent)

## Composition with other skills / agents

| Use this skill TO TRIGGER | Other skill / agent |
|---|---|
| Gate 2 (QA) | `udm-design-reviewer` agent (independent) |
| Gate 3 (Edge case enumeration) | `udm-edge-case-validator` skill |
| Gate 4 (Edge case validation) | `udm-test-author` agent (for test-based verification) |
| Gate 5 (idempotency) | Tier 2 property-based tests, when they exist |

This skill is the orchestrator; it doesn't replace those.

## Examples of when to invoke

- ✅ "I just rewrote SP-1 to fix the I3 race condition. Run checks-and-balances before declaring D49 Locked."
- ✅ "Round 2 (Configuration) draft is ready. Run checks-and-balances before round acceptance."
- ✅ "Adding a new edge case S15. Run checks-and-balances to confirm it's properly cross-referenced and has a test."
- ❌ "I added one comment to a docstring. Don't need to run checks-and-balances." (Correct — trivial changes don't need this overhead.)

## Why this skill exists

After 14+ rounds of planning, the project produced 49 decisions, 23 tables, 11 runbooks, 5+ skills, and 2 custom agents. **The reflection agent in round 13 found 8 critical bugs that had been "validated" simply because they were written down.** This skill exists to prevent that pattern from recurring. Validation is a separate step from production.

## Second-pass validation (D56)

When first-pass returns 🔴, the iteration cycle is:

1. **First-pass** runs all 5 gates. Documents 🔴 + 🟡 in `_validation_log.md`.
2. **Producer applies fixes** to address 🔴.
3. **Second-pass** (mandatory per D56) — INDEPENDENT agent runs all 5 gates again. Confirms fixes work; verifies no NEW 🔴 introduced.
4. **Status flip 🟡 → 🟢 ONLY after second-pass** returns clean.

**Independence is non-negotiable**: producer ≠ first-pass agent ≠ second-pass agent. Self-review at any layer = no validation.

**Cross-reference required**: second-pass entry in `_validation_log.md` cites the first-pass entry's date and agentId.

**When second-pass not required**:
- First-pass returned ALL ✅ with no 🔴 (only 🟡 follow-ups) — second-pass optional
- Trivial edits (typos, formatting, editorial re-org)

If second-pass finds NEW 🔴, iterate: third-pass, fourth-pass, etc., **per D72 convergence rule (locked 2026-05-10)**:
- Cycle ceiling: max 10 cycles per round
- Convergence: 3 consecutive cycles returning CLEAN → cycle terminates; artifact may flip 🟡 → 🟢
- Counting: each parallel multi-agent batch (e.g., 4-agent deep validation) counts as ONE cycle
- Reset: any "not clean" cycle resets consecutive-clean counter to 0
- Escalation: 10 cycles without 3-in-a-row clean → architectural review

In practice convergence happens by third or fourth cycle; the 10-cycle ceiling is a safety bound. Multi-agent parallel validation composes with D56 — use it when single-agent cycles seem to have plateaued without convergence (D56 third-pass clean is no longer sufficient evidence of convergence; need 3 consecutive clean cycles per D72).

## Tracking

Each invocation should write a row to `docs/migration/_validation_log.md` (created on first use):

```markdown
| Date | Artifact | Gates passed | Notes |
|---|---|---|---|
| 2026-05-09 | phase1/01_database_schema.md v2 | 5/5 ✅ | All ROUND_1_REVIEW issues fixed and verified |
```

Pattern: produce → validate → record → lock. Always in that order.
