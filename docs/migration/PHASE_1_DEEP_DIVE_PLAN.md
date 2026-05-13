# Phase 1 Deep Dive Plan

**Status**: 🟡 Proposed structure; awaiting user confirmation to begin

This document outlines the deep dive sequence for Phase 1 (Foundation Infrastructure). Following the deep dive cycle from `02_PHASES.md`, each sub-area gets its own complete plan, validation, QA, edge case enumeration, and edge case validation.

## Sub-areas of Phase 1

Phase 1 has **eight** sub-areas. Recommended sequence:

1. **Database Schema** — all DDL for `General.ops` tables, indexes, stored procedures
2. **Configuration** — `UdmTablesList` schema, `.env` structure, GPG/credentials, parity baseline
3. **Core Modules** — Python modules implementing the layers (parquet writer, tokenizer, ledger, etc.)
4. **Tools** — operator-facing CLI scripts
5. **Tests** — Tier 1 (unit) and Tier 2 (property-based) coverage
6. **Deployment** — how Phase 1 reaches dev/test/prod servers
7. **Schema Evolution Governance** — process for evolving Round 1 schema post-lock (SP signature changes, new tables, column additions, Automic job inventory amendments) without breaking dependent Rounds 2-4 specs
8. **Sub-Agent Self-Improvement Discipline** — meta-round; produces the skill suite that lets the validation system tune itself based on the `_reviewer_effectiveness.md` ledger evidence accumulated across Rounds 1-7

Each sub-area becomes one round of deep dive (eight rounds total for Phase 1). Within each round we go through the full cycle:

```
Round N (sub-area S):
  N.1 — PLAN: complete artifact list for S
  N.2 — VALIDATE: cross-reference against architecture, edge cases, runbooks
  N.3 — QA: peer review correctness
  N.4 — EDGE CASES: enumerate from M/S/I/N/P/G/D/F/V register
  N.5 — VALIDATE EDGE CASES: write tests / verify config / runbook check
  N.6 — SIGN-OFF: stakeholder approval, recorded in 03_DECISIONS.md
```

## Round 1 — Database Schema (highest priority, all other work depends on this)

### 1.1 Plan scope

Complete CREATE TABLE DDL with indexes, constraints, and stored procedures for:

| Table | Purpose | Estimated rows (7 years) |
|---|---|---|
| `General.ops.PipelineBatchSequence` | Sequence object for BatchId generation | n/a |
| `General.ops.PipelineEventLog` | Per-step event tracking | ~50M |
| `General.ops.PipelineLog` | Detailed narrative logging | ~5B (with retention purge) |
| `General.ops.PipelineExtraction` | Per-day extraction state (large tables) | ~500K |
| `General.ops.PipelineExecutionGate` | AM/PM cycle coordination | ~5K |
| `General.ops.PromotionLock` | Server failover lock | ~1K |
| `General.ops.MaintenanceWindow` | Scheduled outage suppression | ~500 |
| `General.ops.IdempotencyLedger` | Per-step status for crash recovery | ~50M |
| `General.ops.ParquetSnapshotRegistry` | Parquet file index | ~10M |
| `General.ops.ExtractionRangePolicy` | Date-range scheduler config | ~500 |
| `General.ops.LatenessProfile` | Empirical L_99 measurements | ~5K |
| `General.ops.DeleteEvaluationAudit` | Per-(date,batch) delete decisions | ~5M |
| `General.ops.ExtractionGapLog` | Documented extraction gaps | ~1K |
| `General.ops.ManualCorrectionLog` | Operator-driven Bronze writes | ~500 |
| `General.ops.ReconciliationLog` | P3-4 reconciliation results | ~50K |
| `General.ops.SCD2RepairLog` | R-6 repair tool actions | ~5K |
| `General.ops.PiiVault` | Plaintext-to-token mapping | ~50M |
| `General.ops.PiiTokenProvenance` | First-observation provenance | ~250M |
| `General.ops.PiiTokenizationBatch` | Per-batch tokenization audit | ~1.3M |
| `General.ops.PiiVaultAccessLog` | Decrypt audit trail | ~500K |
| `General.ops.CcpaDeletionLog` | Right-to-deletion audit | ~5K |
| `General.ops.TableEnablementLog` | Phase 4 per-table enablement | ~500 |
| `General.ops.HealthCheckLog` | Phase 6 health check results | ~10M |

Stored procedures:

- `PiiVault_GetOrCreateToken(@plaintext, @pii_type, @source) RETURNS @token`
- `PiiVault_Decrypt(@request_id, @token_list, @justification)` (audit-logged)
- `PiiVault_DecryptBulk(@request_id, @max_rows, @justification)` (audit-logged, bounded)
- `PipelineExecutionGate_AcquireProd(@cycle, @cycle_date) RETURNS @gate_id, @batch_id`
- `PipelineExecutionGate_AcquireTest(@cycle, @cycle_date) RETURNS @action ('exit'|'failover')`
- `PipelineExecutionGate_RequestCancellation(@cycle, @cycle_date, @requested_by, @reason)`
- `PipelineExecutionGate_AcknowledgeCancellation(@gate_id)`
- `IdempotencyLedger_StartStep(@batch_id, @source, @table, @event_type) RETURNS @action ('skip'|'proceed')`
- `IdempotencyLedger_CompleteStep(@batch_id, @source, @table, @event_type, @status)`
- `IdempotencyLedger_RecoveryStartupSweep(@max_age_minutes)`

Indexes (non-exhaustive; full design in 1.3):

- `PipelineEventLog`: `(BatchId)`, `(SourceName, TableName, EventType, StartedAt)`, `(Status, StartedAt)` for failure-detection queries
- `PipelineLog`: `(BatchId, CreatedAt)`, `(LogLevel, CreatedAt)` for retention purge
- `ParquetSnapshotRegistry`: `(SourceName, TableName, BatchId, BusinessDate)` UNIQUE, `(StorageTier, CreatedAt)`, `(SnowflakeStagePath)` filtered
- `PiiVault`: `(PiiType, SourceName, PlaintextHash)` UNIQUE INCLUDE Token
- ... (full list in 1.3)

Output: `docs/migration/phase1/01_database_schema.md` with complete DDL, indexes, and stored procedure definitions.

### 1.2 Plan validation

Validate against:
- `01_ARCHITECTURE.md` storage and encoding specs
- `03_DECISIONS.md` (D6, D11-D14, D17, D22, D26, D29, D30, D33, D34)
- `04_EDGE_CASES.md` — each table addresses specific edge cases (e.g., gate addresses F-series; ledger addresses I-series)
- `05_RUNBOOKS.md` — runbooks reference these tables, ensure they're addressable
- `07_LOGGING.md` — log table schemas align with `Layer`, `CycleType`, `CycleDate`, `ServerRole` requirements

Sign-off: DBA + Pipeline Architect + Compliance Officer.

### 1.3 Quality assurance

- DBA review: indexes appropriate, no missing FKs, naming conventions consistent
- Performance review: estimated query plans for the 5 most common operational queries
- Security review: TDE applied to vault tables; access permissions designed; audit trail mandatory
- Idempotency review: every UPSERT pattern verified to be idempotent; UNIQUE constraints prevent double-write
- Storage review: estimated row counts × row size = 7-year storage forecast

### 1.4 Edge case enumeration (database-schema relevant)

| ID | Description | Mitigation in schema |
|---|---|---|
| I3 | Two concurrent same-batch INSERTs to ledger | UNIQUE constraint on (BatchId, Source, Table, EventType) |
| I13 | Snapshot re-INSERT for same (pk, batch_id) | UNIQUE on registry |
| F4 | Failover claims gate while prod is recovering | sp_getapplock on (cycle, date); gate UNIQUE constraint |
| F15-F19 | Cancellation flow edge cases | Gate cancellation columns; documented state machine |
| V1-V10 | Vault provenance edge cases | Append-only tables; never DELETE |
| P3 | Vault corruption | Backup strategy documented; restore-test runbook |
| P5 | Plaintext leakage in logs | sensitive_data_filter on PipelineLog |
| ... | (full list of relevant cases) | (mapped to specific DDL features) |

### 1.5 Validate edge cases

For each edge case:
- Write a SQL test (e.g., "verify that two simultaneous INSERTs to ledger fail the second one")
- Document the test as part of the validation gate

### 1.6 Sign-off

DDL approved by DBA. Edge case tests pass. Stakeholder sign-off recorded.

---

## Round 2 — Configuration

**Status**: 🟢 Locked 2026-05-10 after 3-pass D56 convergence.

**Deliverable**: `phase1/02_configuration.md` (~50 KB, 7 sections). Covers `UdmTablesList` 29-column inventory + 6 new columns (D63), `.env` per-server structure, GPG envelope spec with TPM2 sealing (D64), cross-server parity baseline + drift severity tiers (D65), Automic 8-job frozen inventory + naming convention + gate-table contract (D66).

**Constituent decisions**: D63-D66.

---

## Round 3 — Core Modules

**Status**: 🟢 Locked 2026-05-10 via D73 architectural-review acceptance (Round 3 math-infeasibility precedent established).

**Deliverable**: `phase1/03_core_modules.md` (~80 KB, 10 sections). 17 Python module interface specs across 7 layers: § 1 Parquet (parquet_writer / parquet_replay / parquet_registry_client) + § 2 PII/vault (pii_tokenizer / pii_decryptor / vault_client) + § 3 Credentials+parity (credentials_loader / server_parity_verifier) + § 4 Idempotency+state (idempotency_ledger / extraction_state) + § 5 Scheduling (range_scheduler / lateness_profiler / gap_detector) + § 6 Observability (sensitive_data_filter / log_handler / event_tracker) + § 7 Snowflake (snowflake_uploader). Cross-cutting D67 Tier 0 discipline + D68 error class hierarchy + D69 cursor ownership + D70 6-tier test pyramid + D71 Snowflake auth flow.

**Constituent decisions**: D67-D73.

---

## Round 4 — Tools

**Status**: 🟢 Locked 2026-05-10 via D78 math-infeasibility architectural-review acceptance (paralleling D73).

**Deliverable**: `phase1/04_tools.md` (~85 KB, 11 CLI specs + cross-cutting CLI conventions + edge case mapping + validation gates). 11 operator CLI scripts wrapping Round 3 module interfaces: parquet_tier_review / parquet_verify / lateness_profile / decrypt_pii / detect_extraction_gaps / promote_test_to_prod / verify_server_parity / enforce_retention / process_ccpa_deletion / log_retention_cleanup / alert_dispatcher.

**Constituent decisions**: D74 (exit-code contract) + D75 (argument naming + actor TTY heuristic) + D76 (audit-row contract) + D77 (Tier 0 scaffold pattern) + D78 (Round 4 acceptance).

---

## Round 5 — Tests

**Status**: 🟢 Locked 2026-05-10 via D83 convergence-confirmed architectural-review acceptance (NEW PRECEDENT, distinct from Round 3 D73 + Round 4 D78 math-infeasibility).

**Deliverable**: `phase1/05_tests.md` (~75 KB, 12 sections). Per-module + per-tool test plans across 28 artifacts × 6-tier pyramid + B47-B107 systematic triage per D73 + D78. Extended `06_TESTING.md` from 5-tier → 6-tier (Tier 0 per D67).

**Constituent decisions**: D79 (test fixture canonical schema) + D80 (Tier-0-to-1 boundary) + D81 (Hypothesis budget + derandomize CI profile) + D82 (coverage thresholds — Tier 2 reframed to "100% properties pass shrinkage within budget" per R5C1-5 advisory) + D83 (Round 5 acceptance).

---

## Round 6 — Deployment

**Status**: 🟢 Locked 2026-05-10 via D88 convergence-confirmed architectural-review acceptance. Pattern F discipline (D89/D90/D91) **authored** 2026-05-11 in post-Round-6 retrospective per R28 — **🟡 Proposed; lock pending Round 7 first-production-invocation empirical evidence**.

**Deliverable**: `phase1/06_deployment.md` (~110 KB, 13 sections). Covers three-environment topology (dev/test/prod), immutable git-tag artifact contract (D84), atomic symlink-swap deploy mechanism, module startup sequence (D85 — closes B69), deployment cadence (D86), pre/post-deploy checklist contract (D87), Tier 0-5 smoke test deployment, Automic frozen-8 inventory activation, EventType family registration (CLI_* / CYCLE_* / DEPLOYMENT_* / MIGRATION_* / STARTUP_* — closes B86), 7-trigger cross-cutting fix workstream, RB-12 deployment runbook (closes B41), 22 new BACKLOG items B120-B141.

**Constituent decisions**: D84 (deployment artifact contract) + D85 (module startup sequence) + D86 (3-env cadence) + D87 (pre/post-deploy checklist) + D88 (Round 6 architectural-review acceptance). Post-retrospective Pattern F: D89 (Pattern F discipline) + D90 (cascade-auditor agent) + D91 (verify_cascade.py contract).

---

## Round 7 — Schema Evolution Governance

Process for evolving Round 1 schema artifacts post-lock without breaking dependent Rounds 2-4 specs. Encompasses:

- **SP signature evolution**: SP-4 `@AcknowledgmentOnly` (per B79), SP-10 `@CutoffOverride` + `@CategoryFilter` (per B93 + B94), anticipated CCPA SP authorship (per B01 / B81)
- **Automic job inventory amendments**: `JOB_PARQUET_VERIFY` + `JOB_LOG_CLEANUP` added to Round 2 § 5.1 frozen-8 (per B80)
- **New Phase 0 deliverable proposal**: ops-channel client (Slack / PagerDuty / email / SMTP) per B82 — currently 02_PHASES.md L48 has NO deliverable for ops-channel routing; Round 4 § 3.11 alert_dispatcher depends on this
- **Round 1 column-name reconciliations** flagged across Rounds 2-4 validations (e.g. RB-11 title clarification per B101 + B106)
- **Supersession discipline**: when Round 1 changes, what's the protocol to update Rounds 2-4 specs without re-opening locked artifacts?

Round 7 produces:
- `phase1/07_schema_evolution_governance.md` (~30-50 KB)
- Updated SP DDL for SP-4 + SP-10 + new CCPA SP
- Updated Round 2 § 5.1 Automic job inventory
- Updated 02_PHASES.md with new Phase 0 deliverable
- **First production Pattern F audit at close-out** (per D89 lock criteria — Round 7 close-out provided empirical evidence; D89/D90/D91 🟢 Locked 2026-05-11 at Round 7 first-production close-out per `_validation_log.md` 2026-05-11 Round 7 entry; extended at Round 8 second-production)

**Status**: 🟢 Locked 2026-05-11 via D94 math-infeasibility architectural-review acceptance (3rd math-infeasibility variant after D73/D78; distinct from D83/D88 convergence-confirmed). 8-cycle Pattern E campaign with sleeper-bug stress at cycle 5; trajectory 12+→5→1→0→1→0→3→0. Constituent D92 (forward-only additive schema evolution governance + SchemaContract supersession) + D93 (cross-doc cascade propagation requirement — formalizes Pattern F unscoped audit lesson) + D94 all 🟢. Round 8 (Sub-Agent Self-Improvement Discipline) next.

---

## Round 1.5 — Schema Documentation Supplements (NEW 2026-05-11; per D100 documentation-supplement-discipline pattern)

**Status**: 🟢 Locked 2026-05-11 via D101 math-infeasibility architectural-review acceptance (4th math-infeasibility variant after D73/D78/D94; distinct from D83/D88/D99 convergence-confirmed). 6-cycle Pattern E campaign trajectory 11→3→8 (22 cumulative 🔴 caught + fixed); 9-table ER canonical-source-drift comprehensive sweep deferred to **B173** as scope-exhausting per D72 ceiling math-infeasibility.

**Deliverable**: 5 supplement docs closing schema-story gaps identified in post-Round-8 reflection. Combined ~80 KB:
- G1 `phase1/01a_control_tables.md` (Round 1.5a, Tier β) — UdmTablesList + UdmTablesColumnsList trigger-tier doc; 35-col UdmTablesList + 12-col UdmTablesColumnsList canonical inventories; observability hooks
- G3+G4 `phase1/01b_bronze_stage_example_ddl.md` (Round 1.5b, Tier α) — canonical Bronze + Stage DDL example for DNA.osibank.ACCT
- G6 `phase1/01c_data_flow_walkthrough.md` (Round 1.5c, Tier β) — AM cycle end-to-end trace + observability annotations + 15-query dashboard catalog
- G5 `phase1/07a_schema_contract_examples.md` (Round 1.5d, Tier α) — 3 example SchemaContract row clusters for R7 SP-4/SP-10/SP-12 evolutions
- G2 `09_VISUALS.md` § ER diagrams (Round 1.5e, Tier α) — 5 Mermaid erDiagram blocks for control + PII + orchestration + reconciliation + lifecycle clusters

**Constituent decisions**: D100 (Documentation supplement discipline; Round-N.5 mini-round pattern; additive-only per D40+D92 forward-only) + D101 (Round 1.5 architectural-review acceptance via math-infeasibility variant).

**Carryover B-items**: B166 (SchemaName verification) + B167 (UpdateTrigger or Python audit) + B168 (table-retire runbook) + B169 (advisory lock UdmTablesList) + B170 (UNIQUE active SchemaContract) + B171 (SupersededBy circular-ref) + B172 (V-4 operator-facing supplement) + B173 (ER canonical sweep; largest deferred item) + B174 (SP-9 param name reconciliation) + B175 (01c § 7.1/7.2 prose update per B173). NEW edge case **I24** filed in 04_EDGE_CASES.md.

---

## Round 8 — Sub-Agent Self-Improvement Discipline

**Status**: 🟢 Locked 2026-05-11 via D99 convergence-confirmed architectural-review acceptance (3rd convergence-confirmed variant after R5 D83 + R6 D88; distinct from D73/D78/D94 math-infeasibility). 9-cycle Pattern E campaign; trajectory 5→1→3→2→0→0; sleeper-bug stress C5 + Pitfall #9.i fix-fresh-instance C7 + final-verify C9 clean. **PHASE 1 COMPLETE.** Phase 2 (Pilot Cutover) is next.

**Deliverable**: `phase1/08_sub_agent_self_improvement.md` (~60 KB, 14 sections) + 7 SKILL.md files at `.claude/skills/udm-{retrospective-collector,specialty-tuner,subclass-accumulator,producer-checklist-evolver,cycle-cadence-optimizer,agent-prompt-versioner,cascade-audit-evolver}/` + meta-doc `docs/migration/SELF_IMPROVEMENT_DISCIPLINE.md` + Section 10 added to `.claude/skills/udm-round-closeout/SKILL.md`.

**Constituent decisions**: D95 (umbrella discipline) + D96 (sub-class 9.j formalization per B144 2-event evidence base) + D97 (artifact-complexity tier mapping α/β/γ/δ) + D98 (agent prompt versioning semver convention) + D99 (Round 8 acceptance).

---

**Original plan (pre-execution, 2026-05-10)**:

**Position**: last Phase 1 round. Produces the skill suite that lets the validation system tune itself.

**Prerequisites**:
- `_reviewer_effectiveness.md` seeded (✅ done 2026-05-10 with Round 2 cycle 1 + Round 3 D72 cycles 4-9 + Round 4 D72 cycles 1-8 backfill)
- 2+ rounds of post-seed ledger data — so Round 5 + Round 6 + Round 7 must complete before Round 8 starts, providing 3+ rounds of post-seed evidence to learn from

**Concept**: today, when the validation system has a performance issue, the user identifies it → I propose → user approves → I implement. That's three round-trips per optimization. Round 8 inverts this: the system observes its own performance via the ledger, detects underperformance patterns, proposes refinements at round close-out, and user reviews proposed deltas (one approval instead of three).

### 8.1 Plan scope — SEVEN sub-areas (expanded from six; B143 added cascade-audit-evolver as 7th skill)

Seven skill artifacts + one meta-doc + one governance loop. **Implementation note**: original plan listed six sub-areas (8.A-8.F); during Round 6 retrospective B143 was raised as candidate 7th skill (`udm-cascade-audit-evolver`) for Pattern F's discipline-evolution counterpart to 8.C; B143 implemented at Round 8 as 8.G. Total skill count: 7.

| Sub-area | Skill | Behavior |
|---|---|---|
| 8.A | `udm-retrospective-collector` | Every reviewer agent's output ends with a ledger entry appended per `_reviewer_effectiveness.md` schema; removes orchestrator's manual ledger-append burden |
| 8.B | `udm-specialty-tuner` | At round close-out, reads ledger trends; identifies specialties with rising false-clean rate; proposes prompt refinements; outputs deltas to `docs/migration/_agent_evolution/<specialty>-<date>.md` for human review |
| 8.C | `udm-subclass-accumulator` | At round close-out, scans 🔴 findings; identifies bug patterns appearing 2+ times without matching existing Pitfall #9 sub-class; proposes new sub-class with first-evidence entry; updates HANDOFF §8 after approval |
| 8.D | `udm-producer-checklist-evolver` | At round close-out, identifies bug classes reviewers consistently caught that producer Gate 1 self-check missed; proposes adding them as explicit producer pre-flight items |
| 8.E | `udm-cycle-cadence-optimizer` | At round close-out, computes optimal cycle cadence per artifact-complexity tier based on ledger evidence; proposes ceiling tier + starting Pattern E vs single-agent split |
| 8.F | `udm-agent-prompt-versioner` | Every reviewer agent prompt gets a version number + change-log; prompt edits (from 8.B-8.E) require user approval; superseded versions archived for audit |

Plus: meta-doc `docs/migration/SELF_IMPROVEMENT_DISCIPLINE.md` (~15-25 KB) documenting the loop, its bounds, its escape conditions.

### 8.2 Plan validation

Validate Round 8 against existing discipline before implementation:
- No skill output contradicts a locked D-number (D55-D78 + any D79-D90 from Rounds 5-7)
- Self-improvement loop has bounded compute cost (skills run once per round close-out, not per cycle)
- Human-in-the-loop preserved (skills propose; user approves)
- Reversibility: every prompt change has a versioned predecessor archived
- Cross-doc consistency: `_reviewer_effectiveness.md` schema + HANDOFF §8 sub-class accumulator + skill outputs all reference each other

### 8.3 Quality assurance

- Skills produce structured Markdown deltas (not free-form recommendations) so review is mechanical
- Each skill emits a confidence score (HIGH / MEDIUM / LOW) based on sample size in the ledger
- Trend analyses use minimum-event thresholds (e.g. ≥5 events per specialty before recommendations)
- Meta-meta-feedback: if a skill's confidence is LOW for 3 consecutive rounds, the meta-discipline itself is flagged for human review (recursive D72-style escalation)

### 8.4 Edge case enumeration

| Series | Concern | Mitigation |
|---|---|---|
| M | Ledger sample size too small for trustworthy trends | Minimum-event threshold per specialty (≥5 events) before recommendations |
| S | Skill proposes change that contradicts a locked decision | Pre-flight check against `03_DECISIONS.md` before emitting; raise as 🔴 if conflict |
| I | Skill outputs are themselves un-validated | Skill outputs go through D55 5-gate validation like any other artifact |
| F | Self-improvement loop diverges (proposes worse changes over time) | Round-over-round catch-rate metric must trend up or stay flat; if declining 2 rounds in a row, freeze the loop and human-review |
| V | Prompt change introduces a fresh-instance bug class (Pitfall #9 recursion) | Mandatory post-deployment validation (Pattern E run on next round's first artifact) using both old and new prompt; compare findings |
| G | Skill itself contributes false-clean to the ledger | Skills are reviewer-class agents themselves; their outputs go in the ledger too (recursive measurement) |

### 8.5 Validate edge cases

Test each skill on Rounds 5 + 6 + 7 retrospective data (simulated dry-run mode) before going live. Track outputs for 1 round before proposals become actionable.

### 8.6 Sign-off

- Pipeline lead approves the 6 skill artifacts + meta-doc
- First "live" run of the loop at Round 9 close-out (or whatever follows Round 8 — likely Phase 2 round 1)
- Quarterly review of trend metrics per `MAINTENANCE.md`

### Estimated artifacts (per B143 expansion to 7 skills)

- 7 skill files at `.claude/skills/udm-<skill>/SKILL.md`: ~5-10 KB each = ~50 KB total
- 1 meta-doc `docs/migration/SELF_IMPROVEMENT_DISCIPLINE.md`: ~15-25 KB
- Updates to existing reviewer agent prompts (`.claude/agents/udm-*.md`): retrospective-append directive added
- Updates to `udm-round-closeout` skill: invoke 8.B-8.E at close-out
- Updates to HANDOFF §8 Pitfall #9: mechanism for ongoing additions (8.C automation hook)
- Updates to MULTI_AGENT_GUIDE.md § Pattern E: specialty rotation evidence-tier informed by ledger

Total estimated artifact: ~60-80 KB across skill suite + meta-doc + agent prompt edits.

### New decisions anticipated

- **D79+ (TBD)**: Self-improvement loop discipline (the meta-decision Round 8 produces; exact D-number depends on Rounds 5-7 decisions)
- Agent prompt versioning + supersession (8.F)
- Skill-to-skill chaining at round close-out (8.B-8.E invoked as a sequence)
- Trend-metric thresholds (minimum events, decline-detection, freeze conditions)

### Risk delta (anticipated)

- 🆕 NEW (anticipated): **R24** — Self-improvement loop introduces feedback-loop instability (Likelihood Low × Impact High = 3). Mitigation: trend-metric monitoring per 8.4 + freeze condition per 8.5. Reversibility per 8.F prompt versioning
- ⬇️ DE-ESCALATED (anticipated): **R03** (single-engineer bus factor) — once self-improvement loop is operational, agent quality is preserved across engineer turnover
- ⬇️ DE-ESCALATED (anticipated): **R11** (validation discipline drift) — self-improvement loop actively counteracts drift

### Pillar mapping (per D61)

- **Operationally stable** — discipline self-maintains; no manual optimization cycles
- **Audit-grade** — every prompt change versioned + decision-recorded
- **Traceability** — ledger trends back to every prompt iteration
- **$120K/year ceiling** — bounded compute (skills run at close-out, not per cycle)

(Full plan to be written when Round 7 completes.)

---

## Phase 1 acceptance criteria (gate to Phase 2)

- All Round 1-8 sign-offs in 03_DECISIONS.md
- Database schema deployed to dev/test/prod (parity verified)
- All Tier 1 + Tier 2 tests green
- Smoke test pipeline (no real data) runs end-to-end on dev
- Code review complete, all reviewer comments resolved
- Operational runbooks (RB-1 through RB-11) reviewed and tested in dev where applicable
- Power BI dashboards drafted (even if no data yet)
- All open 🔴 edge cases addressed; all 🟡 cases have a documented mitigation plan
- Round 7 schema evolution governance procedure documented; SP signature updates applied; Automic job inventory amendments landed
- Round 8 self-improvement skill suite operational; `_reviewer_effectiveness.md` updates auto-collected at round close-out; first proposed prompt-evolution delta surfaced to pipeline lead

Estimated effort: 4-6 calendar weeks for Phase 1 Rounds 1-6; **Rounds 7 + 8 add ~2-3 weeks** (Round 7 spans schema changes + propagation; Round 8 is meta-discipline with dry-run validation). Total Phase 1: ~6-9 calendar weeks once Round 1 begins.
