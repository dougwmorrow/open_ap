---
name: udm-runbook-author
description: Enforces the When → Pre-flight → Procedure → Validation → Rollback structure for new operational runbooks in 05_RUNBOOKS.md. Use when adding a runbook (RB-N) for a new failure scenario, recovery procedure, or routine operational task. Catches runbooks that skip critical pre-flight or rollback sections.
---

# UDM Runbook Author

Use this skill when adding a new operational runbook to `docs/migration/05_RUNBOOKS.md`.

## Canonical Context Load (CCL) — required before invoking this skill (per D62)

Whoever invokes this skill (main agent or subagent) MUST have performed the Canonical Context Load (per `docs/migration/MULTI_AGENT_GUIDE.md` § Canonical Context Load) before authoring a runbook.

- **Stage 0 — Routing manifest** (recommended-not-mandatory; added 2026-05-15 per D62 amendment + D.2 INDEX.md per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.3): `docs/migration/INDEX.md` — read FIRST when uncertain which downstream Stage 1+2+3 docs your task actually needs. Skip when: you already know which Stage 1+2+3 docs to load (typical for recurring task patterns).
- **Stage 1 — Orientation** (mandatory, 4 reads): `NORTH_STAR.md`, `HANDOFF.md`, `CURRENT_STATE.md`, `CHECKS_AND_BALANCES.md`
- **Stage 2 — Risk + Backlog awareness** (mandatory): `RISKS.md`, `BACKLOG.md`, `_validation_log.md`
- **Stage 3 — Task-specific reads for this skill**: `05_RUNBOOKS.md` (existing template + cross-references between RBs); the related D-number(s) in `03_DECISIONS.md` (the runbook should implement a locked decision)
- **Stage 4 — Reference-on-demand**: grep `04_EDGE_CASES.md` for series IDs the runbook addresses

If invoked from a subagent context, the subagent's CCL responsibility is hard-required (per agent definition — first `Read` must hit a Stage 1 doc).

## Output structure (mandatory)

```markdown
## RB-<N>: <short title>

**When**: <one-sentence description of the trigger condition>

### Pre-flight checks

```
1. <verification step — operator confirms condition is real, not transient>
2. <safety check — no other procedures in flight>
3. <scope check — confirm the scope of action>
4. <approval check — who must sign off, if applicable>
```

### Procedure

```
1. <atomic step with explicit command / SQL>
2. <next step>
3. ...
```

Every step:
- Has the exact command, SQL, or click sequence
- Has a single, clear outcome
- Has a clear "if this fails" path

### Validation

```
1. <how to confirm the procedure worked>
2. <metrics or queries that prove the desired state>
3. <wait period if state takes time to converge>
```

### Rollback

```
1. <how to undo if procedure went wrong>
2. <state to restore to>
```

### Related

- Runbooks: <other RB-numbers>
- Decisions: <D-numbers>
- Edge cases: <series IDs>
```

## Hard rules

1. **Pre-flight is mandatory.** Even routine procedures have pre-flight checks (e.g. "no other run in flight," "operator has approval"). If pre-flight is genuinely empty, write "None — this is a routine operation" so the operator knows it was considered.
2. **Procedure steps are atomic.** "Run script X" is too vague — what does the script do? What if it fails halfway? Either inline the SQL/commands or include the script's expected behavior.
3. **Validation is mandatory.** Without validation, operators don't know if they succeeded.
4. **Rollback is required.** "Cannot be rolled back" is acceptable but must be explicit. RB-7 Phase 6 cleanup is one-way; that's documented.
5. **Test in dev before merging.** A runbook that hasn't been exercised once is a wishlist, not a runbook. Reference the dev test in the doc.
6. **D105 SQL naming standards (MANDATORY)** — if the runbook authors a new SP or view (e.g. RB invoking a new diagnostic SP), the SP/view object name MUST be `General.{schema}.Proc{ProcedureName}` (or `Vw{ViewName}`); the file name MUST be `{schema}_Proc{ProcedureName}.sql` (or `{schema}_Vw{ViewName}.sql`). Pre-D105 SP names cited from existing code are grandfathered per D92 and stay unchanged. Flag any newly-introduced non-conformant name. See `CLAUDE.md` § "SQL Naming Standards (D105 — MANDATORY)".
7. **D103 Claude Code security model** — if the runbook touches credential storage, GPG decryption, `.env` access, or SSH-key handling, verify procedure steps use the canonical credential paths (`/etc/pipeline/.env`, `/etc/pipeline/credentials.json.gpg`, `~/.ssh/`, `~/.gnupg/`, etc. — NEVER inside `/debi`) and reference `docs/migration/SECURITY_MODEL.md` for the canonical defense model. If the runbook introduces a NEW credential path, that path MUST also be added to `.claudeignore` + `.claude/settings.local.json` `permissions.deny` as part of the runbook's pre-flight or merge checklist.

## Anti-patterns

- ❌ Procedure steps with no failure path
- ❌ Missing pre-flight (operator goes from idle → action with no checks)
- ❌ Validation that's "look at the dashboard" without specifying what to look at
- ❌ Rollback that says "follow RB-X" without confirming RB-X is the rollback
- ❌ Long prose between steps — keep procedural steps numbered and tight

## Required handoff sections

For runbooks that escalate (call RB-2 manual failover when auto-failover fails):
- Include explicit "if step X fails: STOP and call RB-Y" instructions
- Don't assume operators will know to escalate

## Common runbook categories

- **Cutover** (RB-1): one-time changes per table
- **Failover** (RB-2, RB-9): server/cycle promotion
- **Recovery** (RB-3, RB-6, RB-7, RB-8): post-failure restoration
- **Audit access** (RB-4, RB-10): authorized data access for inquiries
- **Routine ops** (RB-5, RB-11): backfill, retention, scheduled work

Identify the category before writing — missing rollback is more critical for cutover than for routine ops.

## Example

For a new runbook RB-12 covering "Vault DEK rotation":

Output the full structure above with:
- When: triggered by KEK rotation (annual)
- Pre-flight: verify KMS connectivity, no in-flight pipeline runs, backup vault state
- Procedure: generate new DEK via KMS, re-wrap existing DEK references, update PiiVault.PiiKeyVersion, etc.
- Validation: sample 100 tokens, decrypt with both old and new key version
- Rollback: revert vault PiiKeyVersion + delete new DEK from KMS
- Related: RB-6 (vault corruption), D6 (vault design), D27 (key parity)

Pre-flight inadequacy is the #1 cause of incidents from runbooks; this skill exists to prevent that.
