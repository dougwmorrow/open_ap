# UDM Pipeline — Claude Skills Plan

This document captures the skill set we've installed and how to use them across the project's planning and implementation phases.

## What we did

Per D46 (skill evaluation) and D48 (project-local skill installation), we authored five project-specific skills in `.claude/skills/` rather than installing third-party Superpowers content. The reasoning:

1. **OSS approval gate**: third-party Superpowers content (github.com/obra/superpowers, MIT license) requires our org's open-source approval. Authoring our own bypasses that bottleneck.
2. **Tighter integration**: project-local skills can reference our specific D-numbers, edge case series (M/S/I/N/P/G/D/F/V), runbook conventions, and the six-step deep dive cycle.
3. **Reversibility**: if Superpowers is approved later, we can supplement; if not, we still have the discipline.
4. **No duplication**: our `03_DECISIONS.md` already implements ADR conventions; our `04_EDGE_CASES.md` is the audit trail; our `06_TESTING.md` is the test discipline. Skills should layer ON TOP of these, not duplicate them.

## Installed skills

| Skill | File | Purpose |
|---|---|---|
| **udm-planning** | `.claude/skills/udm-planning/SKILL.md` | Decompose a Phase round into 2-5 minute tasks with verification |
| **udm-brainstorm** | `.claude/skills/udm-brainstorm/SKILL.md` | Force at-least-3 alternatives before locking a design choice |
| **udm-edge-case-validator** | `.claude/skills/udm-edge-case-validator/SKILL.md` | Walk M/S/I/N/P/G/D/F/V series against an artifact |
| **udm-decision-recorder** | `.claude/skills/udm-decision-recorder/SKILL.md` | Enforce D-number / status / rationale / **pillar mapping (D61)** / **risk delta (D61)** structure |
| **udm-runbook-author** | `.claude/skills/udm-runbook-author/SKILL.md` | Enforce When/Pre-flight/Procedure/Validation/Rollback for new runbooks |
| **udm-data-engineer-review** | `.claude/skills/udm-data-engineer-review/SKILL.md` | Review CDC/SCD2/Polars/Parquet/BCP for non-idiomatic patterns and bugs |
| **udm-checks-and-balances** | `.claude/skills/udm-checks-and-balances/SKILL.md` | 5-gate validation orchestration (D55); Gate 5 includes risk delta + backlog surfacing per D61 |
| **udm-round-closeout** | `.claude/skills/udm-round-closeout/SKILL.md` | End-of-round aggregate doc updates: HANDOFF, CURRENT_STATE, BACKLOG, RISKS, NORTH_STAR, 00_OVERVIEW, 02_PHASES (per D60) |

All under MIT-equivalent project-local terms (no external dependencies).

## Canonical Context Load (CCL) — required before invoking any skill (per D62)

Every skill invocation (whether by main Claude or a subagent) MUST be preceded by the Canonical Context Load — Stage 1 (Orientation: NORTH_STAR / HANDOFF / CURRENT_STATE / CHECKS_AND_BALANCES) and Stage 2 (Risk + Backlog awareness: RISKS / BACKLOG / _validation_log) reads. The full doctrine is in `MULTI_AGENT_GUIDE.md` § Canonical Context Load. Each skill's own SKILL.md also documents its task-specific Stage 3 reads.

If invoking a skill from a subagent context, the subagent's CCL responsibility is hard-required by its agent definition (first `Read` must hit a Stage 1 doc). Trace audit confirms compliance.

## When to invoke each

```
Phase 1 Round 1 (Database Schema) — current
├── udm-planning at round start (already done implicitly via PHASE_1_DEEP_DIVE_PLAN.md)
├── udm-edge-case-validator on phase1/01_database_schema.md before DBA review
├── udm-data-engineer-review on every stored procedure body
├── udm-decision-recorder when D45 sub-decisions need adjustment
└── udm-brainstorm if open items 1-8 surface ambiguity

Phase 1 Round 2 (Configuration) — next
├── udm-planning at round start
├── udm-brainstorm when GPG strategy alternatives need exploration
├── udm-decision-recorder for config-related D-numbers
└── udm-edge-case-validator on completed Round 2 doc

Phase 1 Round 3 (Core Modules) — next big work
├── udm-data-engineer-review on every CDC / SCD2 / Parquet module
├── udm-edge-case-validator before merging each module
├── udm-runbook-author for any operational scripts
└── (TODO: add udm-tdd skill when we start writing tests)

Phase 1 Round 4 (Tools) — operator-facing
├── udm-runbook-author for every operator tool
├── udm-edge-case-validator on each tool
└── udm-data-engineer-review for tools that touch pipeline data flow

Phase 1 Round 5 (Tests) — validation discipline
├── (TODO: add udm-test-author skill — covers Tier 1/2/3/4/5)
└── udm-edge-case-validator: every edge case ID in register has a test

Phase 1 Round 6 (Deployment) — go-live
├── udm-runbook-author for deployment runbook
└── udm-data-engineer-review for any deployment script that exercises pipeline
```

## Skill-to-doc mapping

| Skill | Primary docs it reads from | Primary docs it writes to |
|---|---|---|
| udm-planning | `02_PHASES.md`, `PHASE_1_DEEP_DIVE_PLAN.md`, `phase1/00_phase_overview.md` | New per-round task trees |
| udm-brainstorm | `03_DECISIONS.md` (existing), `04_EDGE_CASES.md`, architecture docs | Outputs alternatives → input to udm-decision-recorder |
| udm-edge-case-validator | `04_EDGE_CASES.md`, the artifact under review | Output: gap list → input to fixes |
| udm-decision-recorder | `03_DECISIONS.md`, the brainstorm output | Appends new D-number entry to `03_DECISIONS.md` + cross-doc updates |
| udm-runbook-author | `05_RUNBOOKS.md` template patterns | Appends new RB-N entry to `05_RUNBOOKS.md` |
| udm-data-engineer-review | CLAUDE.md (project root), `01_ARCHITECTURE.md`, the code/SQL under review | Action items to fix the artifact |

## How they compose

A typical Round flow uses skills in this order:

```
1. udm-planning at round start → produce task tree
2. For each task that resolves an open question:
   2a. udm-brainstorm → enumerate options
   2b. udm-decision-recorder → capture chosen option as D-number
3. For each artifact produced:
   3a. udm-data-engineer-review → check against patterns
   3b. udm-edge-case-validator → walk relevant series
   3c. Iterate until ✅
4. For each operational procedure:
   4a. udm-runbook-author → enforce structure
5. Round acceptance: validate all artifacts pass all skill checks
```

## Skills NOT yet authored

| Future skill | Trigger to author it |
|---|---|
| **udm-tdd** | Phase 1 Round 5 (Tests) starts — TDD discipline for our 5-tier pyramid |
| **udm-systematic-debugging** | First production bug after Phase 4 — methodology for incidents |
| **udm-power-bi-query-builder** | Phase 6 starts — Power BI dashboard authoring |
| **udm-ddl-validator** | Phase 1 Round 2 if schema changes are frequent |

These are deferred until the work demands them.

## Anti-patterns to avoid with skills

1. **Don't invoke a skill for trivial tasks.** A 1-minute fix doesn't need udm-planning.
2. **Don't skip skills to save time on important changes.** A 🔴 bug found by udm-edge-case-validator after merging costs more than skipping the validator.
3. **Don't duplicate skill output across docs.** udm-brainstorm output goes into the brainstorm conversation; the recommended option becomes a D-number; the rejected options are not separately documented.
4. **Don't use a skill on a question already answered.** Check `03_DECISIONS.md` first before brainstorming.
5. **Don't author new skills until 2-3 invocations validate the need.** Speculative skill authoring is over-engineering.

## Validation: does this plan make sense?

The reflection agent identified two project-level risks:
- **Plan over-specification vs zero code execution** — skills don't address this directly; that's the "Round 0.5 spike" recommendation in `ROUND_1_REVIEW.md`
- **Round 1 has real bugs (SP-1 atomicity, undefined SPs)** — udm-data-engineer-review and udm-edge-case-validator would catch both; the lesson is to invoke them BEFORE locking, not after

These skills add discipline and reduce the chance of similar issues in subsequent rounds. They do not replace the need for code execution feedback (which is what Round 0.5 spike provides).

## Maintenance of skills themselves

- Skill SKILL.md files version-controlled with the repo
- Updated when patterns change (e.g. a new edge case series prefix would require updating udm-edge-case-validator)
- Quarterly review during MAINTENANCE.md cycle

## Future: third-party Superpowers if approved

If/when OSS approval lands for `obra/superpowers`:

1. Install via `/plugin install superpowers@claude-plugins-official`
2. Compare its planning / brainstorm modules to ours; keep the more useful one
3. Adopt its TDD module wholesale (we don't have that yet)
4. Adopt its systematic-debugging module wholesale
5. Document the supplement in MAINTENANCE.md § Development Tooling

For now, project-local is sufficient.
