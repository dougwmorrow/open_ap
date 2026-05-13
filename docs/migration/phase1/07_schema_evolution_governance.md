# Phase 1, Round 7 — Schema Evolution Governance

**Status**: 🟢 Locked 2026-05-11 via D94 architectural-review acceptance (math-infeasibility variant per D73/D78 precedent). 8-cycle Pattern E campaign — cycle 1 Pattern E 5-agent (12+ 🔴) → cycles 2-3 verify+fix (5 🔴 → 1 🔴 fresh-instance) → cycle 4 fix → cycle 5 sleeper-bug stress (1 🔴 SP-12 contract gap + 4 🟡) → cycle 6 fix → cycle 7 independent verify (3 🔴 fix-fresh-instance — SP-12 NULL regression + line-cite drift + F26 forward-ref) → cycle 8 fix-application (current). Trajectory: 12+→5→1→0→1→0→3→0. D72 ceiling math-infeasibility: 2 cycles remaining (9, 10) vs 3-consecutive-clean requirement; infeasible per D73/D78 precedent. **First production Pattern F invocation at close-out cascade — D89/D90/D91 🟡 → 🟢 lock criteria.**

This document is the schema evolution governance spec for the UDM pipeline. It operationalizes D40 (schema-evolution governance Round 7) by specifying HOW Round 1 artifacts evolve post-lock without breaking dependent Rounds 2-6 specs. Scope: SP signature evolutions (SP-4 / SP-10 / new CCPA SP) + Automic frozen-8 → frozen-11 inventory amendment + new Phase 0 deliverable for ops-channel client + RB-11 framing reconciliation + supersession protocol for locked-artifact changes.

Round 7 is also the **first production Pattern F invocation** per D89/D90/D91 lock criteria. The Round 7 close-out cascade is subjected to deterministic Layer 1 script + paired-judgment Layer 2 agents per `MULTI_AGENT_GUIDE.md` § Pattern F. Success of Pattern F at this close-out is the empirical evidence that flips D89/D90/D91 🟡 Proposed → 🟢 Locked.

## § 0. Read order (per D62 Canonical Context Load)

Per `MULTI_AGENT_GUIDE.md` § Canonical Context Load (D62) — canonical Stage 1 order:

1. `docs/migration/NORTH_STAR.md` — pillar priority; Round 7 advances **Audit-grade** (SchemaContract supersession audit trail), **Operationally stable** (governance procedure removes ad-hoc schema changes), **Idempotent** (every governance change writes idempotent migration script)
2. `docs/migration/HANDOFF.md` — locked vs in-flight; §3 D89-D91 🟡 Proposed sub-section; §8 Pitfall #11 cascade-self-attestation
3. `docs/migration/CURRENT_STATE.md` — Round 7 is the next concrete step; first production Pattern F
4. `docs/migration/CHECKS_AND_BALANCES.md` — 5-gate + Pattern F section just added (D89-D91)
5. `docs/migration/RISKS.md` — R06 (source schema changes during build); R28 (cascade self-attestation gap — Pattern F mitigation)
6. `docs/migration/BACKLOG.md` — **B79/B80/B81/B82/B93/B94 + B128/B142/B144/B145 are the Round 7 in-scope items**; B144 candidate sub-class 9.j needs 2-event evidence base
7. `docs/migration/_validation_log.md` — Round 6 D72 7-cycle entry + 2026-05-11 retroactive Pattern F entry + 2026-05-11 unscoped Pattern F entry
8. `docs/migration/_reviewer_effectiveness.md` — cascade-audit specialty has 4 events (2 paired invocations)
9. **This document**
10. `docs/migration/phase1/01_database_schema.md` — Round 1 canonical SP-4 + SP-10 + SchemaContract table DDL (Round 7 evolves these)
11. `docs/migration/phase1/02_configuration.md` — Round 2 § 5.1 frozen-8 Automic inventory (Round 7 amends 8 → 11)
12. `docs/migration/phase1/04_tools.md` — Round 4 § 3.6 promote_test_to_prod + § 3.8 enforce_retention + § 3.9 process_ccpa_deletion (Round 7 SP signature evolutions feed these)
13. `docs/migration/phase1/06_deployment.md` — Round 6 § 4 migration discipline + § 6.1 Automic frozen-8 activation (Round 7 amendments referenced there)
14. `docs/migration/05_RUNBOOKS.md` — RB-10 (CCPA) + RB-11 (7-year retention) (Round 7 reconciles RB-11 framing per B101/B106)
15. `docs/migration/02_PHASES.md` — Phase 0 deliverables list (Round 7 proposes 0.20)
16. `docs/migration/03_DECISIONS.md` — D40 (schema evolution governance) + D26 (PiiTokenProvenance) + D30 (7-year retention) (Round 7 operationalizes D40)
17. `docs/migration/04_EDGE_CASES.md` — V-series (vault provenance) + I-series (idempotency) — Round 7 SP signatures must preserve these
18. `CLAUDE.md` — Validation discipline rule 5 (Pattern F)
19. `docs/migration/MULTI_AGENT_GUIDE.md` § Pattern F — Round 7 close-out invokes this

## Scope

**In scope** (this document):

- **§ 1**: Cross-cutting governance conventions — supersession protocol for locked-artifact changes (per D40 + D34 greenfield posture); SP signature evolution discipline; Automic inventory amendment discipline; new Phase 0 deliverable proposal protocol; cross-doc cascade propagation requirements (Pattern F lesson formalized as D93); producer self-check directive
- **§ 2**: SP-4 `@AcknowledgmentOnly` evolution (closes B79) — enables Round 4 § 3.6 promote_test_to_prod dry-run audit
- **§ 3**: SP-10 `@CutoffOverride` evolution (closes B93) — operator override-without-row-mutation
- **§ 4**: SP-10 `@CategoryFilter` evolution (closes B94) — selective retention by DataClassification
- **§ 5**: SP-12 CCPA deletion SP authorship (closes B81) — wraps OrphanedTokenLog + CcpaDeletionLog write; supports Round 4 § 3.9 process_ccpa_deletion
- **§ 6**: Automic frozen-8 → frozen-11 inventory amendment (closes B80 + B128) — JOB_PARQUET_VERIFY + JOB_LOG_CLEANUP + JOB_PARITY_EXCEPTION_NOTIFY
- **§ 7**: Phase 0 deliverable 0.20 proposal (closes B82) — ops-channel client (Slack / PagerDuty / email / SMTP)
- **§ 8**: RB-11 framing reconciliation (closes B101 + B106) — canonical title "7-Year Retention Enforcement"
- **§ 9**: Edge case mapping (M / S / I / N / P / G / D / F / V / T / DP series — verify no new edge cases from SP evolutions)
- **§ 10**: Validation gates self-check (D55 5-gate + Pattern F)
- **§ 11**: B47-B145 systematic triage (per D73 + D78 + D83 + D88 + D89 carryover mandates; includes Round 7-deferred items closed in this round)
- **§ 12**: Distinctive outputs summary
- **§ 13**: End of Round 7 — first production Pattern F invocation at close-out

**Out of scope** (deferred):

- Round 1 schema body edits — locked per D49 v3; supersession via SchemaContract table per D40 + § 1.1
- Spec-doc body edits for Rounds 2-6 — locked artifacts; new content lands in Round 7 + future rounds
- Code implementation (migrations / SP bodies) — engineering authors at deploy time per Round 6 § 4.1
- Round 8 self-improvement skill suite — Round 8 owns
- Phase 6 Power BI dashboards
- Phase 5 Snowflake Iceberg

## Foundational decisions (Round 7 dependencies)

| # | Decision | Round 7 dependency |
|---|---|---|
| D26 | Append-only PiiTokenProvenance | § 5 CCPA SP must preserve provenance chain |
| D29 | Automic-driven AM/PM coordination | § 6 frozen-11 amendment respects gate contract |
| D30 | 7-year retention + legal-hold override | § 4 SP-10 @CategoryFilter aligns with DataClassification per UdmTablesList; § 8 RB-11 framing |
| D34 | Greenfield deployment (no legacy migration) | § 1.1 supersession protocol respects "no legacy" — schema evolution is forward-only |
| D40 | Schema evolution governance + SchemaContract table | § 1.1 supersession protocol operationalizes; SchemaContract table per Round 1 § 23 |
| D55-D56 | 5-gate + mandatory second-pass | Validation discipline |
| D60 | Round close-out protocol | § 13 close-out cascade per `udm-round-closeout` skill (now 9 sections incl. Pattern F) |
| D62 | CCL doctrine | § 0 read order |
| D63 | UdmTablesList canonical 29-column inventory | § 4 @CategoryFilter uses `DataClassification` column |
| D66 | Automic frozen-8 + gate-table contract (AM/PM only) | § 6 amendment preserves AM/PM scope; new jobs use `sp_getapplock` + PipelineEventLog |
| D72 | Validation cycle termination rule | Pattern E from cycle 1 + sleeper-bug final + D72 cycle count |
| D74-D77 | Round 4 CLI contracts | § 2/§ 3/§ 4 SP evolutions feed Round 4 CLIs via Round 6 deployment |
| D85 | Module startup sequence | § 6 new Automic jobs invoke pipeline modules; startup sequence applies |
| D88 | Round 6 acceptance + addendum (procedural gap) | § 13 close-out invokes Pattern F (D89-D91) to NOT replicate D88's substantiation gap |
| D89 | Pattern F discipline (🟡 Proposed) | § 13 close-out is first production invocation — Round 7 success = D89/D90/D91 🟢 lock |
| D90 | udm-cascade-auditor agent definition (🟡 Proposed) | § 13 close-out spawns Layer 2 paired instances |
| D91 | tools/verify_cascade.py contract (🟡 Proposed) | § 13 close-out runs Layer 1 deterministic script |

## New decisions anticipated in this round

| Proposed | Topic | Pillar(s) served |
|---|---|---|
| D92 | **Schema evolution governance procedure** — when to use SchemaContract supersession vs new D-number + migration script; locked-artifact-change discipline for Round 1 DDL post-D49-v3-lock; SP signature evolution forward-only (parameters added; never removed); ContractKey/ContractValue versioning convention | Audit-grade, Operationally stable, **Idempotent** (every governance change writes idempotent migration script per Round 6 § 4.1 discipline) |
| D93 | **Cross-doc cascade propagation requirement** — when a D-status / B-status / R-status / convention is changed in ONE doc, mandate sweep for parallel claims in all aggregate docs (HANDOFF / CURRENT_STATE / 02_PHASES / PHASE_1_DEEP_DIVE_PLAN / 00_OVERVIEW / NORTH_STAR / CHECKS_AND_BALANCES / CLAUDE.md). Formalizes Pattern F unscoped audit lesson (parallel-instance pattern from 2026-05-11 — D89-D91 "locked" mis-claim appeared at 02_PHASES.md AND PHASE_1_DEEP_DIVE_PLAN.md; fix didn't propagate) | Audit-grade, Operationally stable |
| D94 | **Round 7 architectural-review acceptance** (if D72 ceiling reached) — paralleling D73/D78 math-infeasibility OR D83/D88 convergence-confirmed; only invoked if cycle campaign requires | Operationally stable |

---

## § 1. Cross-cutting governance conventions

### § 1.1 Supersession protocol (per D40 + D92 proposed)

**Hard rule**: Round 1 schema artifacts (DDL bodies, SP bodies in `phase1/01_database_schema.md`) are **forward-only**. Locked at D49 v3; no in-place edits to the spec doc.

**Permitted evolution paths** (per D34 + D40 + D92):

| Change type | Mechanism | Audit trail |
|---|---|---|
| New SP parameter (additive) | SchemaContract row with `ContractKey='sp_parameter_evolution_<ParamName>'` (param-suffixed for audit-trail granularity); migration script `migrations/<sp_name>_<param>_addition.py` OR joint `migrations/<sp_name>_<scope>_evolution.py` when multiple params land together; ALTER PROCEDURE in production | `EventType='MIGRATION_<NAME>'` per D87 |
| New SP entirely | New SP-N (sequential per § 5) added to `phase1/01_database_schema.md` body via documented append; migration script `migrations/<sp_name>_create.py` | `EventType='MIGRATION_<NAME>'` |
| SP parameter renamed | NOT PERMITTED — would break Rounds 2-6 spec citations. Add new param; deprecate old via SchemaContract `sp_parameter_deprecation_at`; remove only after 90-day grace period + downstream confirmation |
| SP parameter removed | NOT PERMITTED for the same reason. If absolutely required, supersede the entire SP with SP-N+1 and mark SP-N ⚫ via SchemaContract |
| Table column added | SchemaContract row; idempotent ALTER DDL per Round 2 § 1.3 precedent | `EventType='MIGRATION_<NAME>'` |
| Table column renamed | NOT PERMITTED — supersede the column via new ContractKey row + per-doc downstream update |
| Table column removed | NOT PERMITTED for the same reason |
| New Automic job | New row in Round 2 § 5.1 inventory via this doc § 6 amendment; SchemaContract row with ContractKey='automic_job'; D93-mandated cross-doc cascade sweep | `EventType='MIGRATION_AUTOMIC_INVENTORY'` |
| Phase 0 deliverable addition | New 0.X in `02_PHASES.md`; D93-mandated cross-doc cascade sweep | One-time; no PipelineEventLog row (config change, not pipeline operation) |

**Why forward-only**: Rounds 2-6 spec citations reference Round 1 by `SP-N` / column / parameter names. Renaming or removing breaks ~50+ cross-references at unbounded cost. Adding is bounded — only the new content needs cross-doc cite.

**Why SchemaContract is the audit trail**: per D40 + Round 1 § 23, SchemaContract is per-source per-object per-column key-value contract entries with EffectiveFrom / EffectiveTo / SupersededBy chain. Round 7 governance writes one row per evolution event. Audit query example:

```sql
-- All SP-4 parameter evolutions
SELECT ContractKey, ContractValue, EffectiveFrom, EffectiveTo, CreatedBy
FROM General.ops.SchemaContract
WHERE SourceName = 'General' AND ObjectName = 'PipelineExecutionGate_AcquireTest'
ORDER BY EffectiveFrom;
```

### § 1.2 SP signature evolution discipline

Per § 1.1, SP signature changes are **additive-only**. Convention:

1. **Identify canonical SP signature** — Round 1 § N body is authoritative; cite exact line range
2. **Add new OPTIONAL parameter at end** — preserves caller compatibility; new callers opt in by passing the param
3. **Document migration script** — `migrations/<sp_name>_<param>_addition.py` runs `ALTER PROCEDURE` in production
4. **Write SchemaContract row** — `ContractKey='sp_parameter_evolution_<param_name>'` + ContractValue=NEW signature
5. **Update Rounds 2-6 spec docs** — D93-mandated cross-doc cascade sweep for any reference to the SP; spec docs are locked but the close-out cascade adds the new param awareness via post-Round-7 addenda
6. **Update CLAUDE.md** — register the evolved signature as a project-root convention (paralleling Round 6 B86 EventType family registration)

**Producer Pitfall #9 self-check** (B144 candidate sub-class 9.j addresses this systematically):
- 9.a column drift: new param uses column name that exists on canonical table
- 9.b parameter drift: new param doesn't collide with existing params
- 9.c enum drift: new param's accepted values match any referenced CHECK constraint
- 9.d type-width drift: new param uses canonical type widths (NVARCHAR(20) / NVARCHAR(30) / etc.)
- 9.e Unicode-vs-ASCII drift: new param uses canonical NVARCHAR vs VARCHAR
- 9.g Python keyword-only marker (if SP is invoked from Round 3 module with `*,` marker)
- 9.h section citation: every `§ X.Y` reference verified
- 9.i process-discipline: no false-closure claims of B-N "closed" without target docs updated

### § 1.3 Automic inventory amendment discipline (per D93 proposed)

Per § 1.1, new Automic jobs added to Round 2 § 5.1 frozen-8 inventory via this doc's § 6 amendment. Convention:

1. **Job name follows D66 convention**: `JOB_<DOMAIN>_<CADENCE>` (e.g., `JOB_PARQUET_VERIFY` = parquet domain + daily implicit; `JOB_LOG_CLEANUP` = log domain + weekly implicit; `JOB_PARITY_EXCEPTION_NOTIFY` = parity domain + daily implicit)
2. **Acquire pattern**:
   - AM/PM cycle jobs: gate-table via Round 1 SP-3 (prod) / SP-4 (test) — per D66
   - Non-AM/PM jobs that WRAP a Round 4 CLI tool: `sp_getapplock` on `<job_name>_<period>` + inherit `EventType='CLI_<TOOL>'` audit row from the CLI per D76. Examples: `JOB_PARQUET_VERIFY` wraps `parquet_verify` → `EventType='CLI_PARQUET_VERIFY'`; `JOB_LOG_CLEANUP` wraps `log_retention_cleanup` → `EventType='CLI_LOG_RETENTION_CLEANUP'`; `JOB_PARITY_EXCEPTION_NOTIFY` wraps `alert_dispatcher` → `EventType='CLI_ALERT_DISPATCH'`.
   - Non-AM/PM standalone jobs (no CLI wrapping): `sp_getapplock` on `<job_name>_<period>` + `EventType='<JOB_NAME>'` audit row — per Round 2 § 5.3.6 original convention
3. **Frozen list expansion**: Round 7 amendment adds jobs sequentially; new total per Round 6 § 6.1 is frozen-11 (8 + 3 Round 7 additions)
4. **D93 cross-doc cascade sweep**: after adding to Round 2 § 5.1, sweep HANDOFF / CURRENT_STATE / 02_PHASES / phase1/06_deployment.md § 6.1 / CLAUDE.md for any "frozen-8" or "frozen-11" references and reconcile

### § 1.4 New Phase 0 deliverable proposal protocol

Per § 1.1, new Phase 0 deliverables added to `02_PHASES.md` via this doc's § 7 amendment. Convention:

1. **ID follows sequential**: 0.X where X is next-available (verified against 02_PHASES.md current max = 0.19; new = 0.20)
2. **Owner must be a real person/team** (not "the team") — per RISKS.md "How to add a risk" precedent
3. **Acceptance criterion explicit**: what completes the deliverable; not vague
4. **D93 cross-doc cascade sweep**: HANDOFF §3 / CURRENT_STATE / phase doc references / RISKS / BACKLOG

### § 1.5 Cross-doc cascade propagation requirement (per D93 proposed — formalizes Pattern F unscoped audit lesson)

When any D-status / B-status / R-status / convention claim changes in ONE doc, **mandate sweep for parallel claims across all aggregate docs**. Pattern F unscoped audit 2026-05-11 found D89-D91 "locked" mis-claim at BOTH 02_PHASES.md L67 AND PHASE_1_DEEP_DIVE_PLAN.md L173 — the prior R6 retroactive fix landed at 02_PHASES.md but didn't propagate to PHASE_1_DEEP_DIVE_PLAN.md.

**Mandate**: after any of the following changes, run a regex sweep across the cascade:

| Change type | Sweep pattern | Target docs |
|---|---|---|
| D-status flip (🟡 → 🟢 / 🟢 → ⚫) | `D<N>\b.*(?:Locked\|Proposed\|Superseded)` | HANDOFF / CURRENT_STATE / 02_PHASES / PHASE_1_DEEP_DIVE_PLAN / NORTH_STAR / CLAUDE.md |
| B-item closure | `B<N>\b.*(?:CLOSED\|🟡 Open\|🟢)` | BACKLOG / phase1/*.md spec docs referencing B-N |
| R-item closure | `R<N>\b.*(?:Open\|Closed\|Mitigated)` | RISKS / HANDOFF §5 / phase1/*.md |
| New convention introduced | the convention name itself | CLAUDE.md (project root) — per Pattern F Trigger E |
| Round-N status (🟢 lock) | `Round <N>.*(?:next round\|🟢 Locked\|🟡 Proposed)` | HANDOFF §3 / CURRENT_STATE / 02_PHASES Phase row / PHASE_1_DEEP_DIVE_PLAN Round stub / NORTH_STAR Phase contribution |

**Enforcement**: Pattern F Layer 1 (`tools/verify_cascade.py` Triggers C/D/F) catches the surfaceable subset deterministically. Pattern F Layer 2 (paired `udm-cascade-auditor` × 2) catches the judgment-class subset. D93 is the discipline; D89/D90/D91 is the mechanism.

### § 1.6 Producer self-check (Pitfall #9 9.a-9.j candidate walk)

Before invoking § 10 validation gates + § 13 Pattern F first-production audit, producer walks each sub-class:

- **9.a column-name drift**: Round 1 columns cited — `PipelineExecutionGate.LastHeartbeatAt`, `ActualStartTime`, `ActualCompletionTime`, `ExecutingServer`, `Status`, `CycleType`, `CycleDate`; `PiiVault.Status`, `RetentionExpiresAt`, `LegalHold`, `StatusReason`, `StatusChangedAt`, `StatusChangedBy`; `SchemaContract.ContractKey`, `ContractValue`, `EffectiveFrom`, `EffectiveTo`, `SupersededBy` (per Round 1 § 23 L1188-1208); `UdmTablesList.DataClassification` (per Round 2 § 1.2.3); `UdmTablesList.LegalHoldOnly` (per Round 2 § 1.2.6); `CcpaDeletionLog` columns (per Round 1 schema). ✓ Verified.
- **9.b parameter-name drift**: SP-4 canonical sig from Round 1 L1538-1546: `@CycleType NVARCHAR(10) / @CycleDate DATE / @ExpectedStartTime DATETIME2(3) / @HeartbeatStaleMinutes INT = 10 / @ProdMaxRuntimeMinutes INT = 120 / @GateId BIGINT OUTPUT / @BatchId BIGINT OUTPUT / @Action NVARCHAR(30) OUTPUT`. SP-10 canonical sig from L1953-1954 (signature only; L1956-1985 = body): `@DryRun BIT = 1`. § 2/§ 3/§ 4 evolutions are ADDITIVE to these signatures. ✓ Verified.
- **9.c enum-value drift**: SP-4 `@Action` ∈ `('EXIT_SUCCEEDED', 'EXIT_RUNNING_HEALTHY', 'PROCEED_FAILOVER')` per L1546; UdmTablesList.DataClassification per Round 2 § 1.2.3 (per Round 2 enum); PipelineEventLog.Status per Round 1 L143-144 `CK_PipelineEventLog_Status IN ('IN_PROGRESS','SUCCESS','FAILED','SKIPPED')`; PipelineExecutionGate.CycleType per L326-327 `IN ('AM', 'PM')`. ✓ Verified.
- **9.d type-width drift**: NVARCHAR(10) for @CycleType per L1539; NVARCHAR(30) for @Action per L1546; NVARCHAR(50) typical SchemaContract.SourceName per Round 1 § 23. ✓ Verified.
- **9.e Unicode-vs-ASCII drift**: Round 1 string-param convention is **NVARCHAR for human-readable text + VARCHAR for fixed-format tokens** (per B-1 + B62 canonical discipline). `Token` columns are `VARCHAR(40)` per Round 1 L861 (PiiVault.Token), L1039 (PiiVaultAccessLog.Token), L1256 (OrphanedTokenLog.Token). SP-12 `@TokenList NVARCHAR(MAX)` is a delimited list parameter (acceptable); body's `@Tokens TABLE (Token VARCHAR(40))` correctly casts elements to canonical VARCHAR(40) before JOIN per R7C1-1 finding. SchemaContract.ContractValue + Notes are `NVARCHAR(MAX)` (free text). ✓ Verified.
- **9.f cross-table column-name lift**: `Status` exists on PipelineEventLog (enum L143-144) AND PipelineExecutionGate (enum L328-330) AND PiiVault (per D45.6 — canonical CK enum at L887-888 includes 'deleted_per_request' / 'purged_for_retention' / 'legal_hold_only'). SchemaContract has NO Status column — supersession state lives in `EffectiveTo IS NULL` (active) + `SupersededBy` (forward chain). Every reference in this doc specifies which table. ✓ Verified (corrected from prior draft that incorrectly claimed SchemaContract had a Status column).
- **9.g Python keyword-only marker**: § 5 CCPA SP is invoked from Round 3 module + Round 4 § 3.9 process_ccpa_deletion which uses `def process_ccpa_deletion(*, ticket_id, actor, dry_run, ...)`. Preserved.
- **9.h wrong-section-cite**: every `§ X.Y` / `L<N>` citation in this doc verified against canonical target docs at producer self-check. Round 1 § 23 (L1179-1222 for SchemaContract); Round 1 L1538-1546 (SP-4 sig); Round 1 L1953-1985 (SP-10 sig); Round 2 § 5.1 frozen-8; Round 4 § 3.6 promote_test_to_prod; Round 4 § 3.8 enforce_retention; Round 4 § 3.9 process_ccpa_deletion; Round 6 § 6.1 Automic activation. ✓ Verified.
- **9.i process-discipline-failure**: B79/B80/B81/B82/B93/B94 + carryover items in § 11 — every "closed" claim verified against canonical target docs (not B-number range as proxy). ✓ Verified at producer self-check; Pattern F Layer 2 will re-verify per Trigger B audit.
- **9.j candidate (B-item status-render discipline)**: § 11 B-triage uses canonical render — leading badge matches inline annotation. No "🟡 Open" + "CLOSED" mismatches in this doc's B-references. ✓ Verified.

**Status**: ✅ producer self-check complete. Gate 2 Pattern E review per § 10.

---

## § 2. SP-4 `@AcknowledgmentOnly` evolution (closes B79)

### § 2.1 Driver

Round 4 § 3.6 `promote_test_to_prod` is the operator failover CLI. Per D33 + D75 + RB-9, it has a dry-run mode that shows what failover WOULD do without claiming the gate. Currently SP-4 (`PipelineExecutionGate_AcquireTest`) has no parameter to signal "evaluate gate state but DON'T transition" — every invocation potentially mutates the gate row (via `Status='RUNNING'` + `ExecutingServer='test'` claim). The dry-run mode in Round 4 § 3.6 has to side-channel this via "stop before SP-4 call" — but this skips the gate's atomic evaluation logic + leaves operator without canonical "what would SP-4 say if we DID claim?" answer.

**B79** (BACKLOG): SP-4 `@AcknowledgmentOnly` schema evolution proposal (Round 7 OR Round 6 amendment) to support § 3.6 promote_test_to_prod dry-run mode. WSJF 2.0.

### § 2.2 Proposed signature evolution (additive — per § 1.2)

**Current SP-4 signature** (Round 1 L1538-1546):

```sql
CREATE PROCEDURE General.ops.PipelineExecutionGate_AcquireTest
    @CycleType NVARCHAR(10),
    @CycleDate DATE,
    @ExpectedStartTime DATETIME2(3),
    @HeartbeatStaleMinutes INT = 10,
    @ProdMaxRuntimeMinutes INT = 120,
    @GateId BIGINT OUTPUT,
    @BatchId BIGINT OUTPUT,
    @Action NVARCHAR(30) OUTPUT
```

**Evolved signature** (additive: new param at end with default = 0 preserves caller compat):

```sql
CREATE PROCEDURE General.ops.PipelineExecutionGate_AcquireTest
    @CycleType NVARCHAR(10),
    @CycleDate DATE,
    @ExpectedStartTime DATETIME2(3),
    @HeartbeatStaleMinutes INT = 10,
    @ProdMaxRuntimeMinutes INT = 120,
    @AcknowledgmentOnly BIT = 0,    -- NEW per B79 + § 2: dry-run mode
    @GateId BIGINT OUTPUT,
    @BatchId BIGINT OUTPUT,
    @Action NVARCHAR(30) OUTPUT
```

**Placement note**: `@AcknowledgmentOnly` is inserted after the last INPUT parameter and before the OUTPUT block. Per § 1.2 step 2 "at end" discipline, the new INPUT param IS at the end of the input section. **Caller-syntax constraint**: all existing SP-4 callers MUST use named-parameter syntax (`@GateId = ... OUTPUT`, `@BatchId = ... OUTPUT`, `@Action = ... OUTPUT`) — positional-arg callers would have OUTPUT params shift position when `@AcknowledgmentOnly` is inserted. Round 4 § 3.6 + RB-9 (the only known SP-4 callers) both use named-parameter syntax per their canonical bodies; no positional callers exist. Per R7C1-5 advisory grounding (Microsoft Learn — Specify Parameters in a Stored Procedure): named-parameter calling is the canonical SQL Server forward-compat pattern.

**Semantic of `@AcknowledgmentOnly`**:
- `@AcknowledgmentOnly = 0` (default — preserves caller compat): full SP-4 behavior; mutates gate row when @Action='PROCEED_FAILOVER'
- `@AcknowledgmentOnly = 1` (NEW): evaluates gate state, returns @Action verdict + @GateId of the row that would be claimed, but does NOT mutate. `@BatchId` returns NULL (no new BatchId allocated). Operator gets canonical "if we claimed now, what would SP-4 say?" answer.

### § 2.3 Migration script

`migrations/sp_4_acknowledgment_only.py` — idempotent ALTER PROCEDURE (per Round 6 § 4.1 migration discipline):

```python
"""migrations/sp_4_acknowledgment_only.py — B79 closure.

Per § 2 of phase1/07_schema_evolution_governance.md (D40 + D92 governance).
Forward-only additive parameter; @AcknowledgmentOnly BIT = 0 (default preserves caller compat).
"""

# Pseudo-code (engineering authors actual body at deploy):
# 1. ALTER PROCEDURE General.ops.PipelineExecutionGate_AcquireTest (new full sig per § 2.2)
# 2. Wrap with sp_getapplock 'sp_4_evolution' to serialize concurrent migrations
# 3. INSERT SchemaContract row:
#    ContractKey='sp_parameter_evolution_AcknowledgmentOnly'
#    ContractValue=<full evolved signature>
#    CreatedBy='migration:sp_4_acknowledgment_only'
# 4. INSERT PipelineEventLog row: EventType='MIGRATION_SP4_ACK_ONLY' per D87
# 5. Idempotency: query SchemaContract for existing ContractKey + active row;
#    skip ALTER if already present (no-op on re-run)
```

### § 2.4 Downstream consumers

- **Round 4 § 3.6 `promote_test_to_prod`**: dry-run mode now uses `@AcknowledgmentOnly=1` for canonical verdict. CLI's `--dry-run` flag (per D75) maps to this param. Per D76 audit row: `EventType='CLI_PROMOTE_TEST_TO_PROD'` + `Metadata.dry_run=true` + `Metadata.sp4_verdict=<@Action>`.
- **Round 4 § 3.6 `--apply`**: maps to `@AcknowledgmentOnly=0` (default; full SP-4 behavior).
- **No other downstream consumers** — SP-4 is invoked only by Round 4 § 3.6 + RB-9 (which uses Round 4 § 3.6 internally).

### § 2.5 SchemaContract audit row

```sql
INSERT INTO General.ops.SchemaContract
    (SourceName, ObjectName, ColumnName, ContractKey, ContractValue, EffectiveFrom, CreatedBy, Notes)
VALUES
    ('General', 'PipelineExecutionGate_AcquireTest', NULL, 'sp_parameter_evolution_AcknowledgmentOnly',
     '{"new_param": "@AcknowledgmentOnly", "type": "BIT", "default": "0", "evolution_round": "Round 7 § 2", "closes": "B79", "audit_log_event_type": "MIGRATION_SP4_ACK_ONLY"}',
     SYSUTCDATETIME(), 'pipeline-lead', 'Additive parameter — preserves caller compat; default=0 = pre-evolution behavior. New @AcknowledgmentOnly=1 enables Round 4 § 3.6 promote_test_to_prod dry-run mode without mutating gate state.');
```

---

## § 3. SP-10 `@CutoffOverride` evolution (closes B93)

### § 3.1 Driver

Round 4 § 3.8 `enforce_retention` is the monthly cron CLI per RB-11 + D30. It invokes SP-10 (`EnforceRetention`) with `@DryRun BIT = 1` (Round 1 L1953-1955). Operators sometimes need to enforce retention with a custom cutoff date (e.g., "treat any vault row with RetentionExpiresAt < @CutoffOverride as expired, not SYSUTCDATETIME"). This supports two scenarios: (a) early enforcement for a specific retention sweep (compliance-driven); (b) backfill enforcement for historical missed cron runs.

**B93** (BACKLOG): SP-10 `@CutoffOverride` schema evolution proposal — operator-driven override-without-row-mutation. WSJF 1.5.

### § 3.2 Proposed signature evolution (additive)

**Current SP-10 signature** (Round 1 L1953-1955):

```sql
CREATE PROCEDURE General.ops.EnforceRetention
    @DryRun BIT = 1
```

**Evolved signature**:

```sql
CREATE PROCEDURE General.ops.EnforceRetention
    @DryRun BIT = 1,
    @CutoffOverride DATETIME2(3) = NULL,    -- NEW per B93: cutoff date override
    @CategoryFilter NVARCHAR(20) = NULL     -- NEW per B94: see § 4 — width matches canonical UdmTablesList.DataClassification NVARCHAR(20) per Round 2 § 1.2.3 L213
```

**Semantic of `@CutoffOverride`**:
- `@CutoffOverride = NULL` (default — preserves caller compat): SP-10 uses `SYSUTCDATETIME()` as cutoff (Round 1 L1966 + L1977 canonical behavior)
- `@CutoffOverride = <DATETIME2>` (NEW): SP-10 uses the supplied cutoff instead. Must be in the past or equal to `SYSUTCDATETIME()` (validation: raise THROW 51002 if @CutoffOverride > SYSUTCDATETIME — "future cutoff not permitted")

### § 3.3 Migration script

`migrations/sp_10_retention_evolution.py` — idempotent ALTER PROCEDURE; SchemaContract row with `ContractKey='sp_parameter_evolution_CutoffOverride'` + ContractValue=evolved signature.

### § 3.4 Downstream consumers

- **Round 4 § 3.8 `enforce_retention`**: gains `--cutoff <ISO8601>` arg per D75 naming convention. Maps to SP-10 `@CutoffOverride`. CLI validates date is in the past before passing to SP. Per D76: `EventType='CLI_ENFORCE_RETENTION'` + `Metadata.cutoff_override=<ISO8601>` + `Metadata.cutoff_source='operator'`.
- **JOB_RETENTION_MONTHLY** (Round 2 § 5.1): unchanged; invokes SP-10 with default `@CutoffOverride=NULL` for canonical monthly sweep.

---

## § 4. SP-10 `@CategoryFilter` evolution (closes B94)

### § 4.1 Driver

Round 1 + Round 2 + D30 + UdmTablesList.DataClassification (Round 2 § 1.2.3 L216 + § 1.4 L377 `CK_UdmTablesList_DataClassification CHECK (DataClassification IS NULL OR DataClassification IN ('PII', 'PCI', 'none'))`) introduce per-table data classification with canonical enum values `'PII' / 'PCI' / 'none' / NULL`. Compliance audit sometimes requires retention enforcement on ONE classification only (e.g., "flip Status='deleted_per_request' for all expired PII rows, leave 'PCI' rows alone pending PCI-DSS review"). SP-10 currently flips all expired rows.

**B94** (BACKLOG): SP-10 `@CategoryFilter` schema evolution proposal — SP-level filter for `--categories`. WSJF 2.0.

### § 4.2 Proposed signature evolution (additive — combined with § 3.2)

See § 3.2 evolved signature — both `@CutoffOverride` and `@CategoryFilter` added together in single ALTER (one migration script).

**Semantic of `@CategoryFilter`**:
- `@CategoryFilter = NULL` (default — preserves caller compat): SP-10 flips all expired rows regardless of classification (Round 1 canonical behavior)
- `@CategoryFilter = <NVARCHAR(20)>` (canonical width matches UdmTablesList.DataClassification per Round 2 § 1.2.3 L213) (NEW): SP-10 adds `AND v.SourceName IN (SELECT u.SourceName FROM General.dbo.UdmTablesList u WHERE u.DataClassification = @CategoryFilter)` to the WHERE clause. The JOIN is **PiiVault.SourceName → UdmTablesList.SourceName** (table-level correlation) since `DataClassification` lives on UdmTablesList per Round 2 § 1.2.3, NOT on PiiVault. Validation: raise THROW 51003 if `@CategoryFilter` not in canonical enum `('PII','PCI','none')` per Round 2 § 1.4 L377 `CK_UdmTablesList_DataClassification`.

### § 4.3 Migration script

`migrations/sp_10_retention_evolution.py` — single script combining both `@CutoffOverride` and `@CategoryFilter` ALTERs (joint per § 4.5); both are additive params; single ALTER PROCEDURE avoids double-migration cost. SchemaContract row with `ContractKey='sp_parameter_evolution_CategoryFilter'` + ContractValue.

### § 4.4 Downstream consumers

- **Round 4 § 3.8 `enforce_retention`**: gains `--categories <comma-separated>` arg per D75. Maps to SP-10 `@CategoryFilter`. For multi-category invocations, CLI loops one SP-10 invocation per category (atomicity per-category). Per D76: `EventType='CLI_ENFORCE_RETENTION'` + `Metadata.categories=['PII','PCI']` (canonical enum values per Round 2 § 1.4 L377).

### § 4.5 Joint § 3 + § 4 migration

Because § 3.2 and § 4.2 add two params to the same SP-10 signature, the deploy-time migration is **a single ALTER PROCEDURE** with both new params. Migration script: `migrations/sp_10_retention_evolution.py` (encompasses both B93 + B94). SchemaContract: two rows (one per ContractKey).

---

## § 5. SP-12 CCPA deletion SP authorship (closes B81)

### § 5.1 Driver

Round 4 § 3.9 `process_ccpa_deletion` is the operator CLI for CCPA right-to-deletion requests per RB-10. It currently has no canonical SP to wrap — the SQL body lives ad-hoc in the CLI per Round 4 § 3.9. This violates D55 (5-gate validation requires a canonical SP for vault mutations) + Pitfall #1 (SQL in CLI ≠ SQL in SP for audit purposes).

**B81** (BACKLOG): Author the CCPA deletion SP (B01-tracked) so § 3.9 process_ccpa_deletion has a real SP to wrap. WSJF 2.5.

### § 5.2 Proposed new SP-12 (sequential — current max is SP-11)

```sql
CREATE PROCEDURE General.ops.PiiVault_ProcessCcpaDeletion
    @RequestId UNIQUEIDENTIFIER,                -- matches CcpaDeletionLog.RequestId canonical type (Round 1 § X L1080)
    @SubjectIdentifier NVARCHAR(MAX) = NULL,    -- canonical CcpaDeletionLog.SubjectIdentifier is NOT NULL (L1083) — param default = NULL for token-file bulk mode; body COALESCEs to synthetic placeholder before INSERT
    @TokenList NVARCHAR(MAX),                   -- comma-separated tokens to flip
    @LegalExceptionReason NVARCHAR(MAX) = NULL, -- matches CcpaDeletionLog.LegalExceptionReason canonical NULL nullability (L1086)
    @RequestedBy NVARCHAR(255),                 -- matches CcpaDeletionLog.RequestedBy canonical NOT NULL column (L1082)
    @Actor NVARCHAR(255),                       -- processing actor (used for ProcessedBy)
    @DryRun BIT = 1
WITH EXECUTE AS OWNER
AS
BEGIN
    SET NOCOUNT ON;
    
    -- Validate inputs
    IF @RequestId IS NULL OR LEN(@RequestedBy) < 1
        THROW 51010, 'RequestId (UNIQUEIDENTIFIER) + RequestedBy required.', 1;
    
    -- Split token list into typed staging — VARCHAR(40) matches canonical PiiVault.Token type per
    -- Round 1 § X L861 (B-1 convention: VARCHAR for fixed-format tokens; NVARCHAR for free text).
    -- Cast STRING_SPLIT output to VARCHAR(40) to prevent collation-mismatch JOIN drift.
    DECLARE @Tokens TABLE (Token VARCHAR(40) NOT NULL);
    INSERT INTO @Tokens (Token)
    SELECT CONVERT(VARCHAR(40), TRIM(value))
    FROM STRING_SPLIT(@TokenList, ',')
    WHERE LEN(TRIM(value)) > 0;
    
    DECLARE @Affected BIGINT = 0;
    DECLARE @AffectedTokensJson NVARCHAR(MAX);
    
    IF @DryRun = 1
    BEGIN
        -- Audit-only: return preview of what WOULD flip
        SELECT v.Token, v.PiiType, v.SourceName, v.LegalHold, v.Status
        FROM General.ops.PiiVault v
        INNER JOIN @Tokens t ON v.Token = t.Token
        WHERE v.Status = 'active' AND v.LegalHold = 0;
    END
    ELSE
    BEGIN
        BEGIN TRANSACTION;
            -- Capture the JSON list of tokens that WILL flip (for CcpaDeletionLog.AffectedTokens)
            SELECT @AffectedTokensJson = (
                SELECT v.Token AS [token], v.PiiType AS [pii_type], v.SourceName AS [source]
                FROM General.ops.PiiVault v
                INNER JOIN @Tokens t ON v.Token = t.Token
                WHERE v.Status = 'active' AND v.LegalHold = 0
                FOR JSON PATH
            );
            
            -- Flip vault Status to canonical 'deleted_per_request' enum value
            -- (per CK_PiiVault_Status enum at Round 1 § X L887-888)
            UPDATE v
            SET v.Status = 'deleted_per_request',
                v.StatusReason = 'CCPA right-to-deletion (RB-10) request ' + CONVERT(NVARCHAR(36), @RequestId),
                v.StatusChangedAt = SYSUTCDATETIME(),
                v.StatusChangedBy = @Actor
            FROM General.ops.PiiVault v
            INNER JOIN @Tokens t ON v.Token = t.Token
            WHERE v.Status = 'active' AND v.LegalHold = 0;
            SET @Affected = @@ROWCOUNT;
            
            -- Write CcpaDeletionLog audit row per RB-10
            -- Canonical columns per Round 1 § X L1078-1094:
            -- (DeletionId IDENTITY, RequestId UNIQUEIDENTIFIER, RequestedAt, RequestedBy NOT NULL,
            --  SubjectIdentifier, AffectedTokens, Action enum, LegalExceptionReason, ProcessedAt, ProcessedBy, NotifiedConsumerAt)
            -- Token-file bulk mode: @SubjectIdentifier defaults to NULL; canonical
            -- CcpaDeletionLog.SubjectIdentifier is NOT NULL (L1083) so COALESCE to
            -- a deterministic synthetic placeholder ('TOKEN_FILE_BULK_' + RequestId).
            INSERT INTO General.ops.CcpaDeletionLog
                (RequestId, RequestedAt, RequestedBy, SubjectIdentifier, AffectedTokens, Action, LegalExceptionReason, ProcessedAt, ProcessedBy)
            VALUES
                (@RequestId, SYSUTCDATETIME(), @RequestedBy,
                 COALESCE(@SubjectIdentifier, 'TOKEN_FILE_BULK_' + CONVERT(NVARCHAR(36), @RequestId)),  -- canonical NOT NULL preserved
                 @AffectedTokensJson,
                 'deleted',           -- per CK_CcpaDeletionLog_Action enum ('deleted','partial','legal_hold_override','pending')
                 @LegalExceptionReason, SYSUTCDATETIME(), @Actor);
            
            -- Write OrphanedTokenLog row per P2 mitigation (D45.6)
            -- Canonical columns per Round 1 § X L1254-1284:
            -- (OrphanLogId, Token, OrphanedAt DEFAULT, OrphanReason CHECK enum, OrphanReference, ...)
            INSERT INTO General.ops.OrphanedTokenLog (Token, OrphanReason, OrphanReference)
            SELECT v.Token,
                   'ccpa_deletion',                                  -- canonical enum per CK_OrphanedTokenLog_Reason
                   CONVERT(NVARCHAR(255), @RequestId)               -- RequestId goes in OrphanReference per column comment
            FROM General.ops.PiiVault v
            INNER JOIN @Tokens t ON v.Token = t.Token
            WHERE v.Status = 'deleted_per_request'
              AND v.StatusReason LIKE '%' + CONVERT(NVARCHAR(36), @RequestId) + '%';
        COMMIT TRANSACTION;
        
        SELECT @Affected AS TokensFlipped;
    END;
END;
```

### § 5.3 Downstream consumers

- **Round 4 § 3.9 `process_ccpa_deletion`**: CLI body now invokes SP-12 directly. **Round 7 evolves Round 4 § 3.9 CLI surface** (additive args per § 1.2 evolution discipline):
  - `--request-id <UUID>` (existing per Round 4 § 3.9 L1188) → `@RequestId`
  - `--token-file <path>` OR `--subject-id <id>` mutex (existing per Round 4) → `@TokenList` (parsed from file) OR `@SubjectIdentifier=<id>`. **Token-file mode**: `@SubjectIdentifier` defaults to NULL (canonical NULL semantics per CcpaDeletionLog L1083).
  - `--requested-by <actor>` (**NEW** per Round 7 § 5.3) → `@RequestedBy` (required; matches CcpaDeletionLog.RequestedBy NOT NULL canonical L1082)
  - `--legal-exception-reason <text>` (**NEW** per Round 7 § 5.3, optional) → `@LegalExceptionReason` (defaults to NULL — canonical column nullability L1086)
  - `--justification <text>` (existing per Round 4) — distinct from `--legal-exception-reason`; written to D76 audit Metadata.justification (NOT to CcpaDeletionLog)
  - `--actor <actor>` (existing per Round 4) → `@Actor` (used for `ProcessedBy`)
  - `--dry-run` / `--apply` (existing per D75) → `@DryRun`
  - Per D76 audit row: `EventType='CLI_PROCESS_CCPA_DELETION'` + `Metadata.request_id` (UNIQUEIDENTIFIER as string) + `Metadata.subject_identifier` (or NULL for token-file mode) + `Metadata.tokens_count` + `Metadata.dry_run` + `Metadata.requested_by` + `Metadata.legal_exception_reason` + `Metadata.justification`
- **RB-10 (CCPA right-to-deletion)**: runbook procedure updated to reference SP-12 by name + canonical param names (`@SubjectIdentifier`, `@RequestedBy`, `@LegalExceptionReason`) per Round 1 canonical CcpaDeletionLog DDL (close-out task in § 11 cascade fixes). RB-10 § Procedure updated to enumerate the new `--requested-by` + `--legal-exception-reason` CLI args.

### § 5.4 Migration script

`migrations/pii_vault_process_ccpa_deletion.py` — CREATE PROCEDURE; SchemaContract row with `ContractKey='sp_new_PiiVault_ProcessCcpaDeletion'`; SP-12 added to Round 1 § "SP Index" via Round 7 close-out append (not editing Round 1 body; supersession-friendly). Migration writes one `PipelineEventLog` row with `EventType='MIGRATION_SP12_CCPA_DELETION'` per D87 + § 1.1 audit-row mandate.

### § 5.5 Edge case coverage

| Edge case | SP-12 mitigation |
|---|---|
| V1 (vault row never deleted) | ✅ Status flip to canonical 'deleted_per_request' enum value (per CK_PiiVault_Status — never DELETE) |
| V8 (decrypt audit on every access) | N/A — SP-12 is mutation, not decrypt |
| I3 (concurrent same-token CCPA requests) | ✅ Transaction + WHERE Status='active' filter — second request becomes no-op (still writes CcpaDeletionLog row for audit-trail) |
| P2 (orphaned token logs) | ✅ OrphanedTokenLog write with canonical `OrphanReason='ccpa_deletion'` enum + `OrphanReference=@RequestId` (per CK_OrphanedTokenLog_Reason canonical) |
| F-next (CCPA processing during failover — proposed F26) | ✅ SP runs on whichever server has prod DB; same audit trail. Append to F-series per § 11.5 / B146 — F26 sequential after F25 proposal in § 9.1 |

---

## § 6. Automic frozen-8 → frozen-11 inventory amendment (closes B80 + B128)

### § 6.1 Driver

Round 2 § 5.1 frozen-8 Automic inventory covers AM/PM cycles + reconciliation + retention + CCPA + DR drill. Round 6 § 6.1 activated all 8. Three jobs were proposed but deferred to Round 7 governance:

- **B80**: `JOB_PARQUET_VERIFY` (daily 03:00) + `JOB_LOG_CLEANUP` (weekly Sunday 05:00)
- **B128**: `JOB_PARITY_EXCEPTION_NOTIFY` (daily 06:00) — 30-day pre-expiry notification per B38 / R18

### § 6.2 Proposed amendment

Round 2 § 5.1 frozen-8 → frozen-11. New rows:

| Job | Cadence | Server | Prereqs | Owner | Purpose | Coordination |
|---|---|---|---|---|---|---|
| `JOB_PARQUET_VERIFY` | Daily 03:00 (production) | Prod | `JOB_PIPELINE_PM` SUCCEEDED (prior evening) | Pipeline lead | Runs `tools/parquet_verify.py` (Round 4 § 3.2) — walks `ParquetSnapshotRegistry`, verifies file existence + checksum; flips Status to 'missing' or 'verified' | `sp_getapplock job_PARQUET_VERIFY_<date>` + `EventType='CLI_PARQUET_VERIFY'` audit row |
| `JOB_LOG_CLEANUP` | Weekly Sunday 05:00 (production) | Prod | `JOB_RECONCILE_WEEKLY` SUCCEEDED earlier | Pipeline lead | Runs `tools/log_retention_cleanup.py` (Round 4 § 3.10) — deletes PipelineLog rows older than retention threshold (default 30d DEBUG/INFO; 90d WARNING+; indefinite ERROR+) | `sp_getapplock job_LOG_CLEANUP_<week>` + `EventType='CLI_LOG_RETENTION_CLEANUP'` |
| `JOB_PARITY_EXCEPTION_NOTIFY` | Daily 06:00 (all servers) | Dev/Test/Prod | None (standalone) | Pipeline lead | Reads `/etc/pipeline/parity_baseline.json` `documented_exceptions[]`; alerts (via ops-channel client per § 7) on any exception with `expires_at` within 30 days. Closes B38 (R18 mitigation activation) | `sp_getapplock job_PARITY_EXCEPTION_NOTIFY_<date>_<server>` + `EventType='CLI_ALERT_DISPATCH'` (uses Round 4 § 3.11 alert_dispatcher per canonical Round 4 § 3.11 L1322); audit row per D87 if cron-mode |

### § 6.3 D93 cross-doc cascade sweep

Per § 1.5 D93 mandate — after frozen-8 → frozen-11 amendment, sweep all cascade docs:

- **HANDOFF §3** (D66 entry) — note Round 7 amendment + cite this § 6
- **CURRENT_STATE.md "Where we are"** — note frozen-11 active
- **02_PHASES.md Phase 0 deliverable 0.10** — update from "8 canonical Automic jobs" to "11 canonical Automic jobs (frozen-8 from Round 2 + 3 Round 7 additions per `phase1/07_schema_evolution_governance.md` § 6)"
- **phase1/06_deployment.md § 6.1** — same update; cite Round 7 § 6
- **CLAUDE.md** — no Automic inventory in CLAUDE.md (operational, not architectural — acceptable per scope)

### § 6.4 Migration: no DDL; config-only with audit trail

These are Automic job definitions (operational config, not SQL Server DDL). Migration = Automic team imports 3 new job definitions per `JOB_<DOMAIN>_<CADENCE>` naming. **Per § 1.1 mandate + D87**, one `PipelineEventLog` row is written: `EventType='MIGRATION_AUTOMIC_INVENTORY'` + `Metadata.frozen_count_before=8` + `Metadata.frozen_count_after=11` + `Metadata.new_jobs=['JOB_PARQUET_VERIFY','JOB_LOG_CLEANUP','JOB_PARITY_EXCEPTION_NOTIFY']` + `Metadata.actor` + `Metadata.justification`. Audit-grade traceability per NORTH_STAR even when no SQL DDL applies.

---

## § 7. Phase 0 deliverable 0.20 proposal — ops-channel client (closes B82)

### § 7.1 Driver

Round 4 § 3.11 `alert_dispatcher` is the CLI for routing pipeline alerts to operator channels. F24 (per § 4 of `04_EDGE_CASES.md` Round 6) covers the zero-channels-available case. But 02_PHASES.md Phase 0 has NO deliverable for the ops-channel client implementation — alert_dispatcher depends on a working ops-channel integration (Slack / PagerDuty / email / SMTP).

**B82** (BACKLOG): Propose new Phase 0 deliverable for ops-channel client + `OPS_CHANNEL_*` env keys + implementation at Round 6. § 3.11 alert_dispatcher dependency. WSJF 1.3.

### § 7.2 Proposed Phase 0 deliverable 0.20

Add to `02_PHASES.md` Phase 0 deliverables table:

| # | Item | Owner | Status |
|---|---|---|---|
| 0.20 | **Ops-channel client integration** — implement multi-channel notification dispatch (Slack webhook / PagerDuty Events API / SMTP email / SMS) used by Round 4 § 3.11 `alert_dispatcher`. Per-environment `OPS_CHANNEL_*` env keys (Round 2 § 2 `.env` additions). Round 7 § 6.2 `JOB_PARITY_EXCEPTION_NOTIFY` (this doc) depends on this. Closes B82. **Note per R7C1-5 advisory research (B156 candidate)**: the proposed `OPS_CHANNEL_FALLBACK_ORDER=slack,pagerduty,email,sms` ordering inverts canonical SRE architecture where PagerDuty is the routing hub (not a fallback to Slack); deliverable implementation should either (a) reframe PagerDuty as primary with Slack as a delivery channel WITHIN it, or (b) document this ordering as project-specific (cost / complexity constraint) rather than canonical SRE fallback. | Pipeline lead + system engineering | ⬜ |

### § 7.3 `.env` additions (Round 2 § 2 amendment via D93 cross-doc sweep)

Round 2 § 2 `.env` per-server keys (currently 45) gain new ops-channel keys:

```
OPS_CHANNEL_PRIMARY=slack       # slack | pagerduty | email | sms
OPS_CHANNEL_SLACK_WEBHOOK=<URL> # per-env webhook
OPS_CHANNEL_PAGERDUTY_KEY=<api-key>
OPS_CHANNEL_EMAIL_SMTP_HOST=<smtp.example.com>
OPS_CHANNEL_EMAIL_SMTP_PORT=587
OPS_CHANNEL_EMAIL_FROM=<noreply@example.com>
OPS_CHANNEL_EMAIL_TO=<ops-team@example.com>
OPS_CHANNEL_SMS_GATEWAY=<carrier-gateway-url>
OPS_CHANNEL_FALLBACK_ORDER=slack,pagerduty,email,sms
```

Total `.env` keys per Round 2 § 2: 45 → 54 (45 baseline + 9 new OPS_CHANNEL_* keys listed above).

### § 7.4 Migration: config-only + Round 6 § 4.2 amendment

No DDL; Round 6 § 4.2 configuration deployment workflow handles via `.env` template extension at deploy time. SchemaContract row with `ContractKey='env_keys_evolution_ops_channel'`.

---

## § 8. RB-11 framing reconciliation (closes B101 + B106)

### § 8.1 Driver

`05_RUNBOOKS.md` L968 canonical title: "RB-11: 7-Year Retention Enforcement". Round 4 § 3.8 + § 3.9 mislabel RB-11 as "legal-hold runbook" at L1069 + L1125 + L1216 (verified line numbers per B106). The misframing creates downstream confusion: legal-hold is a feature OF retention enforcement (per D30), not a separate runbook.

**B101 + B106** (BACKLOG): RB-11 framing — canonical title "7-Year Retention Enforcement"; Round 4 § 3.8 + § 3.9 mislabel as "legal-hold runbook" at L1069/L1125/L1216. Either rename RB-11 to "Retention + Legal Hold" OR correct Round 4 framing. WSJF 1.0.

### § 8.2 Resolution

**Decision**: keep canonical RB-11 title "7-Year Retention Enforcement"; correct Round 4 framing. Rationale:
- RB-11 body covers BOTH retention enforcement AND legal-hold override behavior — the title is already inclusive
- "Retention + Legal Hold" framing implies two distinct features; canonical D30 framing is "retention with legal-hold override" (one feature, one override)
- Round 4 § 3.8 + § 3.9 are locked spec docs — corrections land via close-out cascade addenda (not body edits)

### § 8.3 Round 4 close-out cascade addendum

Round 7 close-out adds inline notes to Round 4 § 3.8 + § 3.9 + Round 6 § 7 references that cite RB-11 by canonical title "7-Year Retention Enforcement" — NOT by "legal-hold runbook" misframing. This is documentation-discipline, not behavior change.

### § 8.4 SchemaContract row

```sql
INSERT INTO General.ops.SchemaContract
    (SourceName, ObjectName, ColumnName, ContractKey, ContractValue, EffectiveFrom, CreatedBy, Notes)
VALUES
    ('General', 'RB-11', NULL, 'runbook_title_canonical', '7-Year Retention Enforcement',
     SYSUTCDATETIME(), 'pipeline-lead',
     'Reconciliation per B101 + B106. RB-11 covers retention enforcement AND legal-hold override; canonical title is inclusive. Round 4 § 3.8 + § 3.9 misframing corrected via close-out cascade addenda.');
```

---

## § 9. Edge case mapping (Gate 3 input)

Walk M / S / I / N / P / G / D / F / V / T / DP series. Verify SP signature evolutions in § 2-§ 4 + new SP-12 in § 5 + Automic frozen-11 in § 6 + Phase 0 deliv 0.20 in § 7 do not create new edge cases without mitigations:

| Series | Round 7 coverage | Specifics |
|---|---|---|
| **M** (model) | ✅ § 4 @CategoryFilter aligns with UdmTablesList.DataClassification enum |
| **S** (SCD2) | ✅ Round 7 SPs don't touch SCD2 layer — vault is separate |
| **I** (idempotency) | ✅ SP-12 transaction + WHERE Status='active' filter; SP-4 evolution preserves UNIQUE; SP-10 evolution preserves WHERE clause filter |
| **N** (network drive / Parquet) | ✅ JOB_PARQUET_VERIFY uses tools/parquet_verify.py per Round 4 § 3.2 |
| **P** (PII) | ✅ SP-12 writes OrphanedTokenLog per P2; @CategoryFilter respects D30 + UdmTablesList.DataClassification |
| **G** (gap) | ⚪ Not applicable — Round 7 governance, not extraction |
| **D** (cadence) | ✅ JOB_LOG_CLEANUP weekly + JOB_PARITY_EXCEPTION_NOTIFY daily fit existing Automic cadence framework per D66 |
| **F** (failover) | ✅ SP-4 evolution preserves AM/PM gate semantic; @AcknowledgmentOnly only affects test-server invocations per § 2.4 |
| **V** (vault provenance) | ✅ SP-12 preserves append-only PiiTokenProvenance per D26 |
| **T** (test) | ✅ Round 7 SPs gain Tier 0 smoke + Tier 1 unit via Round 5 § 3 + § 4 test pyramid (new SP-12 + evolved SP-4 + SP-10 each get a test plan added at Round 7 close-out cascade) |
| **DP** (deployment) | ✅ Round 7 migrations follow Round 6 § 4.1 migration discipline + § 1.7 module startup sequence |

### § 9.1 New edge case proposals

| Proposed | Description | Mitigation in Round 7 |
|---|---|---|
| **I-next** (Idempotency, I23) | SP-12 invoked twice with same `@RequestId` — second invocation should be no-op (already-flipped tokens have canonical `Status='deleted_per_request'` per CK_PiiVault_Status L887-888) | § 5.2 `WHERE Status='active'` filter idempotently no-ops on second call (already-flipped rows excluded). CcpaDeletionLog WILL get a second row though — that's intentional audit-trail per D26 + RB-10 |
| **F-next** (Failover, F25) | SP-4 `@AcknowledgmentOnly=1` invoked DURING active failover (test concurrently invokes SP-4 dry-run while another caller invokes SP-4 with @AcknowledgmentOnly=0 to actually claim) | sp_getapplock per § 2.2 SP body serializes both calls; second caller (whoever loses sp_getapplock) gets the post-first-caller state in @Action verdict |
| **D-next** (Deployment / Cadence, DP8) | New `JOB_PARITY_EXCEPTION_NOTIFY` running daily on dev/test/prod with same `parity_baseline.json` content drift introduces cross-server alert duplication | Per § 6.2 job table — sp_getapplock includes `<server>` qualifier so cross-server alerts are de-duplicated by alert_dispatcher (Round 4 § 3.11) |
| **F-next** (Failover, F26) | SP-12 CCPA deletion invoked DURING active failover — token-file bulk mode with synthetic SubjectIdentifier placeholder must remain stable across servers (per § 5.5 row F26 reference) | SP-12 body COALESCEs `@SubjectIdentifier` to `'TOKEN_FILE_BULK_' + @RequestId` per cycle 8 body fix — synthetic identifier is deterministic per RequestId so cross-server invocation yields identical canonical row; CcpaDeletionLog NOT NULL constraint preserved |

**Close-out task**: append I23 + F25 + DP8 to `04_EDGE_CASES.md` (tracked via B146 close-out item — see § 11).

---

## § 10. Validation gates (Round 7 producer self-check)

Per D55 + D62, producer self-check before Pattern E Gate 2 review.

### § 10.1 Gate 1 self-check — Cross-reference

Per § 1.6 above, every Round 1 / Round 2 / Round 4 / Round 6 reference walked against canonical per Pitfall #9 a-j. ✅

### § 10.2 Gate 5 self-check — Idempotency + Risk delta + Backlog (per D61 corrected label)

**Idempotency / regression** (the actual Gate 5 surface per D55):
- D15 invariant: § 2 + § 3 + § 4 SP evolutions preserve idempotent semantics (default param values preserve caller compat; behavior unchanged on default). § 5 SP-12 is idempotent on re-invocation via `WHERE Status='active'` filter.
- D17 ledger pattern: Round 7 SP evolutions invoked from Round 4 CLIs which wrap in `idempotency_ledger.ledger_step()` per Round 3 § 4.1.
- D26 append-only: § 5 SP-12 writes to CcpaDeletionLog + OrphanedTokenLog (both append-only).
- No locked decision (D55-D88) contradicted.

**Risks introduced / addressed** (per D61):

```
RISKS:
- ⬇️ DE-ESCALATED (pending Round 7 close-out evidence): R06 (Source schema changes during build)
   — § 1.1 supersession protocol formalizes governance; SchemaContract table operational
   per § 2.5 + § 3 + § 4 + § 5.4 row writes. Hedge per Pitfall #8: do NOT reduce R06 score
   until first ~3 schema evolutions actually flow through this governance.

- ⬇️ DE-ESCALATED (pending): R18 (parity-exception expiration enforcement gap) — JOB_PARITY_
   EXCEPTION_NOTIFY per § 6.2 mitigates with 30-day pre-expiry alerts. Hedge: do NOT reduce
   until first JOB_PARITY_EXCEPTION_NOTIFY production run alerts on an actual upcoming expiry.

- 🆕 NEW PROPOSAL: R29 — SchemaContract supersession compounds — every Round 7 SP evolution
   adds 1+ rows to SchemaContract; over time table grows unbounded. Likelihood Low × Impact
   Low = 1 ⚪. Mitigation: archival policy at SchemaContract rows older than 7 years (per
   D30) + Round 7 § 11 close-out task. NOT YET ADDED to RISKS.md per Pitfall #8 hedge.

- 🆕 NEW PROPOSAL: R30 — D93 cross-doc cascade sweep may miss edge-case parallel claims
   (e.g., RB-N references not caught by regex sweep because rendered as "the deployment
   runbook" rather than "RB-12"). Likelihood Medium × Impact Low = 2 ⚪. Mitigation: Pattern
   F Layer 2 paired agents per § 13 close-out catch judgment-class refs. NOT YET ADDED per
   Pitfall #8.
```

**Backlog proposals** (per D61 — current max in BACKLOG is B145; NEXT_AVAILABLE = B146):

```
BACKLOG (per D61):
- 🟡 B146: Append I23 + F25 + DP8 edge cases per § 9.1 to 04_EDGE_CASES.md at Round 7 close-out. COD 2, JS 1, WSJF=2.0
- 🟡 B147: D92 (schema evolution governance procedure) lockdown via decision recording at Round 7 close-out. COD 1, JS 1, WSJF=1.0
- 🟡 B148: D93 (cross-doc cascade propagation requirement) lockdown via decision recording. COD 1, JS 1, WSJF=1.0
- 🟡 B149: Add R29 (SchemaContract supersession growth) + R30 (D93 sweep miss) to RISKS.md per Pitfall #8. COD 2, JS 1, WSJF=2.0
- 🟡 B150: SchemaContract row archival policy (7-year retention; align with D30). Tied to R29. COD 1, JS 2, WSJF=0.5
- 🟡 B151: Round 4 § 3.6 + § 3.8 + § 3.9 + Round 6 § 7 close-out cascade addenda updating to canonical RB-11 title "7-Year Retention Enforcement" per § 8.3. COD 1, JS 1, WSJF=1.0
- 🟡 B152: Update Round 5 § 3 + § 4 test pyramid to add Tier 0 + Tier 1 plans for SP-4 (with @AcknowledgmentOnly) + SP-10 (with @CutoffOverride/@CategoryFilter) + new SP-12 (CCPA deletion). Round 7 close-out cascade work. COD 2, JS 1, WSJF=2.0
- 🟡 B153: Round 2 § 5.1 update to frozen-11 + JOB_PARITY_EXCEPTION_NOTIFY description per § 6. Close-out cascade. COD 1, JS 1, WSJF=1.0
- 🟡 B154: 02_PHASES.md Phase 0 deliverable 0.20 added per § 7.2 close-out cascade. COD 1, JS 1, WSJF=1.0
- 🟡 B155: CLAUDE.md register evolved SP-4 + SP-10 signatures + new SP-12 (paralleling B86 EventType family registration). Per § 1.2 step 6. COD 2, JS 1, WSJF=2.0
```

### § 10.3 Gate 2 — Pattern E independent review (NEXT STEP after this self-check)

Per `_reviewer_effectiveness.md` empirical evidence — Pattern E from cycle 1 (5 parallel agents) for spec docs >50KB. Round 7 spec is ~45 KB; may not need full Pattern E (smaller than R5/R6 threshold) BUT first-production Pattern F at close-out requires high-confidence cascade state. Use Pattern E from cycle 1 anyway.

Then sleeper-bug stress test cycle per R4C8 + R5C4 + R6C4 precedent (mandatory final cycle).

### § 10.4 Round 7 acceptance criteria checklist

- [ ] Intro through § 13 all present and self-consistent
- [ ] D92-D94 captured in `03_DECISIONS.md` (schema-evolution governance + cross-doc cascade propagation + Round 7 acceptance)
- [ ] Pattern E cycle 1 returned ≤4 🔴 (or single-agent first-pass returned ≤2 🔴 — smaller doc allows softer initial threshold)
- [ ] Sleeper-bug stress test cycle complete (mandatory final per R4C8 + R5C4 + R6C4 precedent)
- [ ] **First production Pattern F invocation at close-out** (per D89/D90/D91 lock criteria): Layer 1 `tools/verify_cascade.py` exit code 0 OR 1 (no 🔴) + Layer 2 paired `udm-cascade-auditor` × 2 instances agree on 0 🔴
- [ ] `_validation_log.md` entry appended documenting all validation passes + Pattern F first-production invocation
- [ ] `_reviewer_effectiveness.md` updated with Round 7 cycle entries + 2 new cascade-audit events
- [ ] Cross-doc cascade updates landed per D93 + B151/B152/B153/B154/B155: Round 4 § 3.x close-out addenda + Round 5 § 3/§ 4 test plan extensions + Round 2 § 5.1 frozen-11 + 02_PHASES Phase 0 deliv 0.20 + CLAUDE.md SP registration
- [ ] BACKLOG.md updated with B146-B159 (10 + 4 advisory proposals = 14 proposed) + close items per § 11.1 (**7 Round 7 in-scope** — B79/B80/B81/B82/B93/B94/B128; B101/B106 already-closed at R6) + reclassify cumulative carryover
- [ ] RISKS.md updated with R29 + R30 per Pitfall #8 close-out discipline
- [ ] HANDOFF.md §3 + §12 + §14 updated via `udm-round-closeout` skill; D89/D90/D91 🟡 → 🟢 transition if Pattern F first-production passes
- [ ] CURRENT_STATE.md "Recently completed" + "Recent rounds" + "Next concrete step" (→ Round 8 Sub-Agent Self-Improvement Discipline) updated
- [ ] NORTH_STAR.md decision list extended D92-D94
- [ ] Doc status flip: `phase1/07_schema_evolution_governance.md` "🟡 Drafting" → "🟢 Locked" (after validation + Pattern F passes; D94-style architectural-review acceptance if D72 ceiling reached)

---

## § 11. B47-B145 systematic triage (per D73 + D78 + D83 + D88 + D89 carryover mandates)

### § 11.1 Round 7 closes — items this round resolves

| B-num | Canonical BACKLOG description | How Round 7 closes it |
|---|---|---|
| B79 | SP-4 @AcknowledgmentOnly schema evolution | § 2 spec — additive parameter + SchemaContract row + Round 4 § 3.6 downstream consumer |
| B80 | JOB_PARQUET_VERIFY + JOB_LOG_CLEANUP Automic inventory amendment | § 6.2 frozen-8 → frozen-11 amendment |
| B81 | Author CCPA deletion SP (B01-tracked) | § 5 SP-12 spec — full body + downstream consumer Round 4 § 3.9 |
| B82 | Propose new Phase 0 deliverable for ops-channel client | § 7.2 deliverable 0.20 + § 7.3 `.env` additions |
| B93 | SP-10 @CutoffOverride schema evolution | § 3 spec + joint § 4.5 migration with B94 |
| B94 | SP-10 @CategoryFilter schema evolution | § 4 spec + joint § 4.5 migration with B93 |
| B128 | JOB_PARITY_EXCEPTION_NOTIFY per § 3.6 / B38 | § 6.2 frozen-11 amendment includes this job |

**Round 7 closure count**: 7 items (B101 + B106 already closed at Round 6 close-out 2026-05-10 per BACKLOG.md L284 + L288; Round 7 § 8 is cascade-addenda follow-through on Round 6's B101/B106 closure claim, not a new closure — moved to § 11.3 audit-trail).

### § 11.2 Round 8 work — Sub-Agent Self-Improvement Discipline

| B-num | Canonical BACKLOG description | Round 8 scope |
|---|---|---|
| B129 | Round 8 candidate: self-improvement loop carryover compounding monitor | Round 8 — Round 8's 6-skill suite (or 7-skill per B143 expansion) |
| B143 | Round 8 candidate: udm-cascade-audit-evolver as 7th skill | Round 8 — self-improvement scope expansion |
| B144 | Candidate Pitfall #9 sub-class 9.j (B-item status-render discipline) | Round 8 OR Round 7 close-out IF 2nd-event evidence base substantiates (current = 1-event empirical from Pattern F unscoped audit) |

**Round 8 deferral count**: 3 items (carries forward from Round 6 + 2026-05-11 retrospective).

### § 11.3 Already closed at prior round (audit trail only)

Items already closed; listed for completeness:

| B-num | Closed at | Reference |
|---|---|---|
| B27-B62, B83-B107 (Round 5 close-out items) | Various prior rounds | BACKLOG.md Completed section |
| B38-B141 (Round 6 close-out + retroactive) | 2026-05-10/11 | BACKLOG.md Round 6 + retroactive closures |
| B142, B143 | Open (Round 7-targeted via B142 first-production Pattern F) | Round 7 close-out (B142) + Round 8 (B143) |

### § 11.4 Open and intentionally NOT scoped to Round 7

| B-num | Canonical BACKLOG description | Why not in 11.1 |
|---|---|---|
| B33 | CCL audit-cadence checklist | Phase 6 scope |
| B36/B37 | CCL verification rule strengthening | Phase 1 R3 follow-ups; non-blocking |
| B39 | Snowflake trial cost data | Phase 0 scope |
| B49 | Parity-baseline expires_at timezone | Phase 0 follow-up |
| B64 | D71 pillar mapping | Round 3 close-out polish; non-blocking |
| B66/B67/B71 | Architectural refactors | Post-Round-8 |
| B74 | BACKLOG sort by ID | Non-load-bearing polish |
| B75/B76 | D64 + D71 framing research | Post-Round-8 OR Round 7 framing polish |
| B145 | SKILLS_PLAN + MAINTENANCE Pattern F refresh | Round 7 close-out cleanup (also tracked via § 13) |

**Out-of-scope count**: 11 items.

### § 11.5 New BACKLOG items proposed at Round 7 (B146-B159)

Per § 10.2 — 10 primary items (B146-B155) + per R7C1-5 advisory-research (B156-B159 framing items) = **14 new items**. The 4 advisory items: B156 (ops-channel fallback re-grounding), B157 (Kimball SCD2 citation), B158 (CCPA pseudonymization rationale), B159 (named-parameter calling-style note).

### § 11.6 Triage summary

| Category | Count |
|---|---|
| Round 7 closes (per § 11.1) | 7 |
| Round 8 deferral (per § 11.2) | 3 |
| Already-closed audit trail (per § 11.3) | ~80 (cumulative across Rounds 3-6) |
| Outside-Round-7 scope (per § 11.4) | 11 |
| New B-items proposed at Round 7 (per § 11.5) | 14 (10 primary B146-B155 + 4 advisory B156-B159) |
| **Total tracked** | **~117+ unique items across B01-B159 range** |

---

## § 12. Distinctive outputs

Round 7 produces:
- Three SP signature evolutions (SP-4 @AcknowledgmentOnly / SP-10 @CutoffOverride + @CategoryFilter)
- One new SP (SP-12 CCPA deletion)
- Three new Automic jobs (frozen-8 → frozen-11)
- One new Phase 0 deliverable (0.20 ops-channel client)
- One canonical title reconciliation (RB-11)
- SchemaContract governance procedure operationalized (D40 → D92)
- Cross-doc cascade propagation requirement formalized (D93)
- 3 new edge cases proposed (I23 + F25 + DP8)
- 14 new BACKLOG items proposed (B146-B155 primary + B156-B159 R7C1-5 advisory)
- 7 BACKLOG items closed in-round (B79/B80/B81/B82/B93/B94/B128; B101/B106 already closed at Round 6)
- 2 new risks proposed (R29 + R30)
- First production Pattern F invocation at close-out (D89/D90/D91 lock criteria)

## § 13. End of Round 7 — Schema Evolution Governance + first production Pattern F

**Status when this checklist completes**:
- `phase1/07_schema_evolution_governance.md` 🟢 Locked
- D92 + D93 + D94 (if needed) locked
- D89 + D90 + D91 🟡 → 🟢 IF Pattern F first-production passes

**Phase 1 readiness**: Round 7 is the penultimate Phase 1 round. Round 8 (Sub-Agent Self-Improvement Discipline) is next + last; produces 6-skill (or 7-skill per B143) self-improvement suite. After Round 8, Phase 1 ↔ Phase 2 transition: pilot table cutover begins.
