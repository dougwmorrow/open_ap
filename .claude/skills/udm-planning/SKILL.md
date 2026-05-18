---
name: udm-planning
description: Decomposes a UDM pipeline phase round into 2-5 minute tasks with verification criteria. Use at the start of each round, when scoping a sub-area, or when work feels too big to estimate. Inspired by Superpowers `writing-plans` discipline (`obra/superpowers` v5.1.0 — https://github.com/obra/superpowers/blob/main/skills/writing-plans/SKILL.md ; MIT licensed); evolved for UDM with per-task D-number + edge-case citation requirements + 6-step deep dive cycle mapping (Plan → Validate → QA → Edge Cases → Validate Edge Cases → Sign-off) + CCL Stage 1+2 precondition. Upstream version produces saved markdown at `docs/superpowers/plans/<date>.md`; project version produces in-session task tree. See `docs/migration/_research/superpowers-framework-2026-05-15.md` §5 deep-dive comparison.
---

# UDM Round Planning

Use this skill when starting a Phase round (Phase 1 has six rounds; later phases will too) or when a sub-area of work feels large enough that you're estimating in days rather than tasks.

## How to use

When invoked with a round name (e.g. "Round 2 — Configuration"), produce a task tree following this structure:

```
ROUND <N> — <topic>
├── <Sub-area 1>
│   ├── Task 1.1: <2-5 min concrete action>
│   │   Files touched: <paths>
│   │   Verification: <how to confirm task is done>
│   │   Decisions referenced: <D-numbers from 03_DECISIONS.md>
│   │   Edge cases addressed: <IDs from 04_EDGE_CASES.md>
│   ├── Task 1.2: ...
│   └── ...
├── <Sub-area 2>
└── ROUND <N> ACCEPTANCE: <what proves the round is complete>
```

## Canonical Context Load (CCL) — required before invoking this skill (per D62)

Whoever invokes this skill (main agent or subagent) MUST have performed the Canonical Context Load (per `docs/migration/MULTI_AGENT_GUIDE.md` § Canonical Context Load) before decomposing a round.

- **Stage 0 — Routing manifest** (recommended-not-mandatory; added 2026-05-15 per D62 amendment + D.2 INDEX.md per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.3): `docs/migration/INDEX.md` — read FIRST when uncertain which downstream Stage 1+2+3 docs your task actually needs. Skip when: you already know which Stage 1+2+3 docs to load (typical for recurring task patterns).
- **Stage 1 — Orientation** (mandatory, 4 reads): `NORTH_STAR.md`, `HANDOFF.md`, `CURRENT_STATE.md`, `CHECKS_AND_BALANCES.md`
- **Stage 2 — Risk + Backlog awareness** (mandatory): `RISKS.md`, `BACKLOG.md`, `_validation_log.md`
- **Stage 3 — Task-specific reads for this skill**: `02_PHASES.md` (phase plan + deliverables); `PHASE_1_DEEP_DIVE_PLAN.md` (Phase 1 specifically); the current phase's `00_phase_overview.md` (e.g., `phase1/00_phase_overview.md` for Phase 1)
- **Stage 4 — Reference-on-demand**: grep `03_DECISIONS.md` for D-numbers the round implements; grep `04_EDGE_CASES.md` for series the round addresses

If invoked from a subagent context, the subagent's CCL responsibility is hard-required (per agent definition — first `Read` must hit a Stage 1 doc).

## Hard rules

1. **Tasks are 2-5 minutes each, not features.** "Add table X to schema doc" is a feature. "Write CREATE TABLE block for X.Y" is a task.
2. **Each task has explicit verification.** "Done when DBA review checklist item X passes." Or "Done when tests/test_Y.py::test_Z passes."
3. **Each task references the artifact path it touches.** No "the schema doc" — say `docs/migration/phase1/01_database_schema.md` line 230.
4. **Each task references a D-number or edge case ID** when it implements one. If no decision/edge case applies, that's a flag — does this task have a documented justification?
5. **Acceptance criterion for the round is concrete.** Not "round is done." Something like: "All 23 tables CREATE blocks present, all 10 SP bodies inline, all 8 open items resolved or escalated, DBA checklist 25/25 green."

## Six-step cycle integration

Each round follows the cycle. Map your task tree to:
- Tasks in step 1 (PLAN): drafting / writing
- Tasks in step 2 (VALIDATE): cross-reference checks against architecture, decisions, edge cases
- Tasks in step 3 (QA): peer review actions
- Tasks in step 4 (EDGE CASES): walk the M/S/I/N/P/G/D/F/V series, flag relevant ones
- Tasks in step 5 (VALIDATE EDGE CASES): write/verify tests for each
- Tasks in step 6 (SIGN-OFF): stakeholder approval, status flip in 03_DECISIONS.md

## Anti-patterns

- ❌ "Design Round 2 configuration" (too big; not a task)
- ❌ "Implement vault" (a feature; not a task)
- ❌ "Review with DBA" (not actionable from this side)
- ✅ "Write GPG key generation procedure as bullet list in 02_configuration.md § Credentials" (actionable, 2-5 min)
- ✅ "Add CHECK constraint test case for IdempotencyLedger.Status enum to tests/unit/test_ledger_status_constraints.py" (actionable, has verification)

## When NOT to use

- Don't use for ad-hoc fixes (just fix it)
- Don't use for individual bug investigations (use udm-systematic-debugging instead — when authored)
- Don't use for cross-phase work (use the architectural decision pattern via udm-decision-recorder)

## Output format

Return a markdown task tree (above) plus a concrete first task to begin. The user picks up from "first task" and works down.
