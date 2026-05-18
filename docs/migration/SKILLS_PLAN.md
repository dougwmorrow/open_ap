# UDM Pipeline — Claude Skills Plan

This document captures the skill set we've installed and how to use them across the project's planning and implementation phases.

## §0. Planning session provenance

**RETROACTIVE BACKFILL per B-391 closure 2026-05-17** (authored BEFORE udm-planning-session-startup skill discipline was formalized 2026-05-15 per CLAUDE.md hard rule 13; Pitfall #9.m discipline-applied-retroactively). Original plan authored 2026-05-12 at commit `b73220c` (Initial Commit); this §0 section backfills the audit trail for which planning-discipline skills WOULD HAVE BEEN applied per the matrix at `docs/migration/PLANNING_DISCIPLINE.md` §2 for scope PS-9 SELF.

**Note on self-referential context**: this plan is itself about the skill suite (which skills to install + how to use them) — making it the SELF-IMPROVEMENT artifact PS-9 was designed for. The plan predates the planning-discipline skill suite by ~3 days (skill formalized 2026-05-15; plan authored 2026-05-12). The original 5 skills documented here grew to the 20+ skill catalogue currently maintained at `.claude/skills/` per Round 8 D95-D99 self-improvement framework. Plan still serves as the canonical "what we did + why" rationale for project-local skill authoring vs Superpowers third-party adoption (per D46 + D48 decisions cited L7).

**Scope**: PS-9 SELF (primary; skill suite installation + invocation guidance) + PS-8 D-N (secondary; documents D46 skill evaluation + D48 project-local skill installation decisions)

**Skills that WOULD HAVE BEEN invoked at session start** (per matrix lookup; not invoked at original authoring time because skill discipline didn't exist; recorded here for audit trail consistency):

| Skill | Rationale per matrix |
|---|---|
| `udm-producer-checklist-evolver` (skill) | PS-9 SELF mandatory at session start (per which family) — skill-suite installation IS a producer-checklist-evolution discipline (which skills should producers invoke at which times); plan §"When to invoke each" L37-60 IS the producer checklist for skill invocation |
| `udm-retrospective-collector` (skill) | PS-9 SELF mandatory at session start — would have surfaced empirical evidence for which skills are most impactful (this evidence base accumulated via `_reviewer_effectiveness.md` over Rounds 4-7 per Round 8 D95-D99 framework) |
| `udm-agent-prompt-versioner` (skill) | PS-9 SELF mandatory at session start — skill prompt changes are subject to semver discipline per Round 8 D98 (5 initial skills installed without semver baselining; subsequent skill versioning per `_agent_evolution/<name>-changelog.md`) |
| `udm-decision-recorder` (skill) | PS-8 D-N (secondary scope) mandatory — plan references D46 + D48 + D61 + D62 decisions; would have validated each decision is recorded in `03_DECISIONS.md` per canonical format |
| `udm-design-reviewer` (agent) | PS-8 D-N mandatory + PS-9 SELF conditional — architectural review for skill catalogue scope + non-trivial skill prompt changes |
| `udm-checks-and-balances` (skill/agent) | PS-8 D-N mandatory + PS-9 SELF conditional — 5-gate validation orchestration per D55 for D46/D48 decision attestation |
| `udm-cascade-audit-evolver` (skill) | PS-9 SELF conditional — fires for Pattern F changes; skill suite touches Pattern F audit coverage per Round 8 D89-D91 framework |
| `udm-brainstorm` (skill) | PS-8 D-N conditional — fires for multiple defensible options (D46 had 3 alternatives: Superpowers adoption / project-local authoring / hybrid; plan L7-12 documents the project-local choice rationale) |
| `udm-researcher` (agent) | PS-8 D-N conditional — primary-source grounding for D46 evaluation (Superpowers framework comparison; deferred to retroactive research at `_research/superpowers-framework-2026-05-15.md` per B-279 closure 2026-05-15) |
| `udm-gap-check` (skill) | Always-mandatory at attestation per CLAUDE.md hard rule 11 |
| `udm-progress-logger` (skill) | Always-mandatory throughout per CLAUDE.md hard rule 9 |

**Note**: This §0 section was added 2026-05-17 to satisfy hard rule 13 + the `check_planning_provenance` Mechanism C-1 pre-commit hook (introduced 2026-05-16 per B-275-class closure). Future revisions to this plan MUST update §0 per `udm-planning-session-startup` Step 5 contract; this backfill establishes the baseline audit trail.

## What we did

Per D46 (skill evaluation) and D48 (project-local skill installation), we authored five project-specific skills in `.claude/skills/` rather than installing third-party Superpowers content. The reasoning:

1. **OSS approval gate**: third-party Superpowers content (github.com/obra/superpowers, MIT license) requires our org's open-source approval. Authoring our own bypasses that bottleneck.
2. **Tighter integration**: project-local skills can reference our specific D-numbers, edge case series (M/S/I/N/P/G/D/F/V/DP/T/SI/SE), runbook conventions, and the six-step deep dive cycle.
3. **Reversibility**: if Superpowers is approved later, we can supplement; if not, we still have the discipline.
4. **No duplication**: our `03_DECISIONS.md` already implements ADR conventions; our `04_EDGE_CASES.md` is the audit trail; our `06_TESTING.md` is the test discipline. Skills should layer ON TOP of these, not duplicate them.

## Installed skills

| Skill | File | Purpose |
|---|---|---|
| **udm-planning** | `.claude/skills/udm-planning/SKILL.md` | Decompose a Phase round into 2-5 minute tasks with verification |
| **udm-brainstorm** | `.claude/skills/udm-brainstorm/SKILL.md` | Force at-least-3 alternatives before locking a design choice |
| **udm-edge-case-validator** | `.claude/skills/udm-edge-case-validator/SKILL.md` | Walk M/S/I/N/P/G/D/F/V/DP/T/SI/SE series against an artifact |
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
