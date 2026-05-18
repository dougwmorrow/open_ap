---
name: udm-decision-recorder
description: Enforces the D-number / status / rationale structure when adding a decision to 03_DECISIONS.md. Use when a design choice has been made and needs to be captured. Prevents lossy "we discussed and decided X" text from leaking into other docs without proper structure. Also handles supersession (decision changes its mind).
---

# UDM Decision Recorder

Use this skill whenever a design choice has been made that future-us would otherwise have to re-derive from context.

## When to use

- After resolving a brainstorm via udm-brainstorm
- When a stakeholder explicitly approves a design choice
- When superseding a prior decision
- When a runbook's procedure is changed (the rationale belongs in a decision)
- When a schema column is added/removed (the why belongs in a decision)

## Canonical Context Load (CCL) — required before invoking this skill (per D62)

Whoever invokes this skill (main agent or subagent) MUST have performed the Canonical Context Load (per `docs/migration/MULTI_AGENT_GUIDE.md` § Canonical Context Load) before recording a decision.

- **Stage 0 — Routing manifest** (recommended-not-mandatory; added 2026-05-15 per D62 amendment + D.2 INDEX.md per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.3): `docs/migration/INDEX.md` — read FIRST when uncertain which downstream Stage 1+2+3 docs your task actually needs. Skip when: you already know which Stage 1+2+3 docs to load (typical for recurring task patterns).
- **Stage 1 — Orientation** (mandatory, 4 reads): `NORTH_STAR.md` (re-read for canonical pillar names — case-sensitive: "Audit-grade", "Traceability", "Idempotent", "Operationally stable", "$120K/year ceiling"), `HANDOFF.md`, `CURRENT_STATE.md`, `CHECKS_AND_BALANCES.md`
- **Stage 2 — Risk + Backlog awareness** (mandatory): `RISKS.md` (for risk delta), `BACKLOG.md` (for B-number proposals), `_validation_log.md` (past validation findings)
- **Stage 2.5 — Polish queue awareness** (recommended; added 2026-05-12 per D113): `POLISH_QUEUE.md` — when a new D-number supersedes / touches existing docs, the cascade often leaves cosmetic crumbs (stale citations of the superseded D-number, status-render badge drift in downstream docs). The decision recorder should flag candidate P-N items for any cosmetic carryover that doesn't block the D-lock — document them in the proposed-cascade section so round-close-out absorbs them. (D107 → D109/D110 cascade was the canonical proof-case: multiple supersession crumbs across 8+ docs that warranted P-N tracking rather than B-N tracking.)
- **Stage 3 — Task-specific reads for this skill**:
  - `03_DECISIONS.md` — search to find max D-number (next D = max + 1; never reuse, never gap)
  - `HANDOFF.md` § "Locked vs in-flight" — to update on lock
  - The drivers / supersession context (e.g., the brainstorm output, the validation log entry that surfaced the decision)
- **Stage 4 — Reference-on-demand**: grep `04_EDGE_CASES.md` for series IDs the decision affects, `05_RUNBOOKS.md` for RBs that change

If invoked from a subagent context, the subagent's CCL responsibility is hard-required (per agent definition — first `Read` must hit a Stage 1 doc).

## Output: a complete D-number entry

```markdown
## D<N>: <short title>

**Status**: 🟡 Proposed | 🟢 Locked | ⚫ Superseded by D<M> | 🔴 Open
**Driver**: <what prompted this; cite a user message, agent finding, or upstream constraint>

**Pillar(s) served** (per D61): <one or more of: Audit-grade | Traceability | Idempotent | Operationally stable | $120K/year ceiling — use NORTH_STAR.md canonical forms exactly>

**Decision**: <the actual choice — what we are doing>

**Rationale**: <why; trade-offs considered; alternatives rejected>

**Trade-offs accepted**: <what we lose by this choice>

**Affects**:
- Decisions: <D-numbers this implements/conflicts with>
- Edge cases: <series IDs this addresses>
- Runbooks: <RB-numbers this enables/changes>
- Schema: <table or column impacts in 01_database_schema.md>
- Code modules: <if applicable>

**Reversibility**: <reversible / hard / one-way>

**Risk delta** (per D61): <new risk introduced (propose R-number) | risk mitigated (cite R-N) | none>

**See also**: <docs/sections that elaborate>

(if superseding)
**Supersedes**: D<M> (link explanation: what changed in the world that invalidated D<M>)
```

## D61 — pillar mapping requirement

Every new decision MUST include a "Pillar(s) served" line citing one or more of the 5 NORTH_STAR pillars. **Use canonical pillar names from NORTH_STAR.md exactly** (case-sensitive):
- Audit-grade
- Traceability
- Idempotent
- Operationally stable
- $120K/year ceiling

A decision that doesn't advance any pillar is suspect — re-evaluate scope.

For decisions D1-D60 (created before D61), pillar mapping is a backfill task tracked in BACKLOG (B16). New decisions from D62 onward must include the field.

## Hard rules

1. **Increment monotonically.** Next D-number = current max + 1. Never reuse.
2. **Never edit a 🟢 Locked decision in place.** Create a new D-number that supersedes; mark the old one ⚫ Superseded with forward link.
3. **Status starts 🟡 Proposed unless explicitly approved.** Don't lock prematurely.
4. **Rationale must reference trade-offs.** "We chose X" without "instead of Y because Z" is incomplete.
5. **Affects section is mandatory.** If you can't name what the decision affects, the decision is too vague to record.
6. **Reversibility is required.** Honest assessment: can we change our mind in a week / a month / a year? Decisions framed as reversible too often become irreversible by accumulated downstream commitments.
7. **D105 SQL naming standards (MANDATORY)** — if the decision introduces a NEW SP or view DB object name, that name MUST follow `General.{schema}.Proc{ProcedureName}` (procedures) or `General.{schema}.Vw{ViewName}` (views); proposed filenames MUST follow `{schema}_Proc{ProcedureName}.sql` / `{schema}_Vw{ViewName}.sql`. Pre-D105 grandfathered names (e.g. `General.ops.PiiVault_GetOrCreateToken`) are preserved per D92 forward-only and need not be flipped — but new SP/view names CANNOT bypass D105. Flag any draft decision text proposing a new SP/view name that doesn't conform. See `docs/migration/03_DECISIONS.md` D105 + `CLAUDE.md` § "SQL Naming Standards (D105 — MANDATORY)".
8. **D103 Claude Code security model** — if the decision touches credential storage, secret handling, file-mode policy, or AI-tool-accessibility, the proposed change MUST be consistent with the 13-layer defense model. Credentials live OUTSIDE `/debi`; deny rules in `.claude/settings.local.json` `permissions.deny` are the enforced layer. Mention `docs/migration/SECURITY_MODEL.md` as the canonical reference and verify any new credential path also appears in `.claudeignore` (documentation layer) AND `.claude/settings.local.json` (enforcement layer).

## Anti-patterns

- ❌ "We decided to use X" buried in a runbook step
- ❌ Editing a Locked decision's rationale because we learned more — instead, supersede
- ❌ Locking a decision before the affected docs are updated
- ❌ Decision text that doesn't say what was rejected
- ❌ Forgetting to update CURRENT_STATE.md when a 🟡 → 🟢 transition happens

## Cross-doc updates required when adding a decision

After writing the D-number entry:
1. Update `00_OVERVIEW.md` if the decision shifts a headline decision
2. Update `01_ARCHITECTURE.md` if the decision changes data flow / layers
3. Update `02_PHASES.md` if the decision adds/removes phase deliverables
4. Update `04_EDGE_CASES.md` if new edge cases are surfaced
5. Update `05_RUNBOOKS.md` if a runbook gains/loses procedure
6. Update `CURRENT_STATE.md` to reflect new pending or locked status
7. Update relevant phase's `00_phase_overview.md` if scope changes
8. **Update `HANDOFF.md` § "Locked vs in-flight" if the decision affects what's locked or in-flight (per D60)**
9. **Add to `BACKLOG.md` if the decision creates 🟡 follow-ups**
10. **Add to `RISKS.md` if the decision surfaces new delivery risk**

This skill should output the cross-doc update checklist alongside the D-number entry. **Round close-out (per D60) verifies these cross-doc updates actually landed.**

## Naming conventions

- D-numbers are sequential integers; no gaps even on supersession
- Sub-decisions use D<N>.<n> notation (e.g. D45.1, D45.2 for Round 1's foundational choices)
- Status emoji is mandatory — operators visually scan for 🔴

## Example superseding workflow

User: "Actually, let's drop the watchdog VM and use Automic instead."

Output:
1. Mark old D29 status ⚫ Superseded
2. Add new D29 (revised) with full rationale
3. List cross-doc updates: 02_PHASES.md (remove watchdog deliverable), 05_RUNBOOKS.md (RB-9 rewrite), 04_EDGE_CASES.md (F-series cancellation cases), CURRENT_STATE.md (status reflect)
4. Output the SQL/text changes needed for each affected doc
