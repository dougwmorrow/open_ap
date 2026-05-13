# Phase 1, Round 2 — Configuration

**Status**: 🟢 Locked (after first-pass + mandatory second-pass + third-pass per D56 iterative cycle — see `_validation_log.md` 2026-05-10 Round 2 entries; first non-meta round running with the full D55 + D56 + D60 + D61 + D62 discipline stack)

This document is the configuration spec for the UDM pipeline build. It covers five concrete sub-areas: (1) `General.dbo.UdmTablesList` canonical column inventory — pre-Phase-1 columns cataloged + new columns introduced by this build; (2) `.env` per-server file structure; (3) GPG-encrypted credential strategy; (4) cross-server parity baseline JSON; (5) Automic job definitions.

Round 2 is the design freeze that Phase 0 deliverables 0.11 (cross-server parity baseline — `BACKLOG.md` B12) and 0.12 (GPG-based credential strategy — `BACKLOG.md` B13) implement against. Round 3 (Core Modules) authors the Python loaders + helpers that consume these configs; Round 4 (Tools) authors the operator CLIs that audit them.

## Read order for this round (per D62 Canonical Context Load)

Agents and skills working on Round 2 perform CCL Stage 1+2 first per `MULTI_AGENT_GUIDE.md` § Canonical Context Load (mandated by D62). Reading order specific to Round 2:

1. `docs/migration/CURRENT_STATE.md` — confirm Round 2 is in flight; check pending items
2. `docs/migration/HANDOFF.md` — locked vs in-flight; Round 2 is the first non-meta application of the full discipline stack (D62 round close-out 2026-05-10)
3. `docs/migration/NORTH_STAR.md` — pillar priority for trade-offs; Round 2 primarily advances **Operationally stable** + **Audit-grade** + **Traceability** pillars
4. `docs/migration/CHECKS_AND_BALANCES.md` — 5-gate validation discipline + CCL preamble
5. `docs/migration/RISKS.md` — R03 (single-engineer Python expertise), R08 (cross-server parity drift), R10 (production hardware failure) are most-relevant to Round 2
6. `docs/migration/BACKLOG.md` — B02-B05, B07, B12-B14 are Round 2-adjacent (SQL Agent DDL, parity baseline, capacity baseline, GPG strategy)
7. `docs/migration/_validation_log.md` — past validation findings; the "risk-delta-without-register-update" pitfall (Pitfall #8) is fresh
8. **This document**
9. `docs/migration/03_DECISIONS.md` (search by D-number) — D6, D17, D27, D29 revised, D33, D34, D62 are foundational; D63-D66 will be added by this round
10. `CLAUDE.md` (project root) — existing `UdmTablesList` column reference (extensive — see § "Architecture Decisions"); `.env` location convention (`/debi/.env`); deployment requirements (`MALLOC_ARENA_MAX=2`, `mssql-tools18`)
11. `docs/migration/phase1/01_database_schema.md` — Round 1 schema (especially `PipelineExecutionGate` table + cancellation columns from D33; `IdempotencyLedger` from D17)

## Scope

**In scope** (this document):

- **§ 1**: `UdmTablesList` canonical column inventory — every existing pre-Phase-1 column cataloged + 6 new columns introduced by this build (`CDCMode`, `PiiColumnList`, `DataClassification`, `CohortAssignment`, `IsEnabled`, `LegalHoldOnly`); idempotent ALTER DDL; CHECK constraints
- **§ 2**: `.env` per-server file structure — canonical key set, per-server differences vs parity-required keys, sensitive-key handling (which keys reference GPG envelope)
- **§ 3**: GPG-encrypted credential envelope — file format, recipients, passphrase storage decision (TPM2 vs keyutils vs hardware token vs offline-passphrase, brainstormed via `udm-brainstorm`), Python decryption flow interface (impl deferred to R3), key rotation runbook (RB-12 stub)
- **§ 4**: Cross-server parity baseline JSON — schema definition, verification procedure interface (impl deferred to R4), drift severity classification (fatal / warning / informational), baseline maintenance cadence
- **§ 5**: Automic job definitions — full job inventory, naming convention, gate-table integration contract per job type, failover behavior consuming D33 cancellation flag
- **§ 6**: Edge case mapping — M / S / I / N / P / G / D / F / V series walk against Round 2 sub-areas
- **§ 7**: Validation gates — Gate 1-5 self-check + risk delta + backlog surfacing per D55+D61

**Out of scope** (deferred):

- Python implementation of `data_load/credentials_loader.py` (Round 3 — Core Modules)
- Python implementation of `tools/verify_server_parity.py` (Round 4 — Tools)
- Automic instance setup, agent installation, scheduler configuration (operations responsibility; Phase 0 deliverable 0.10)
- TPM2 / keyutils OS-level kernel configuration (sysadmin responsibility; Phase 0 deliverable 0.12 implementation)
- DBA review of `UdmTablesList` ALTER DDL (separate DBA checklist after this doc locks; D34 greenfield posture means even ALTERs are idempotent guards on a fresh build)
- `PipelineExecutionGate` and `IdempotencyLedger` table definitions (Round 1; this doc references them)

## Foundational decisions (Round 2 dependencies)

| # | Decision | Round 2 dependency |
|---|---|---|
| D27 | Cross-server parity (RHEL + Python pinned + library set + systemd unit identical across dev / test / prod) | § 4 baseline JSON encodes the parity contract; § 2 separates parity-required `.env` keys from per-server diffs |
| D29 (revised) | Automic-driven AM/PM gate coordination via `PipelineExecutionGate` table | § 5 job inventory + § 5.3 column-by-column gate-write contract per job type |
| D33 | Cooperative cancellation via gate flag column | § 5.4 failover behavior consumes `CancellationRequested` flag |
| D34 | Greenfield deployment — initial CREATE only, no ALTER paths from legacy | § 1.3 ALTER DDL uses `IF NOT EXISTS` guards so re-deploy is no-op; not an ALTER-from-legacy migration |
| D6 | In-house tokenization vault — `General.ops.PiiVault` | § 3 GPG envelope includes vault-DB connection string in addition to source-DB credentials |
| D17 | Idempotency ledger pattern with startup recovery sweep | § 5 every Automic job gates on ledger before any side-effecting action |
| D62 | Multi-agent discipline / Canonical Context Load | This § "Read order for this round" exists because of D62; agents reviewing this doc perform CCL first |

## New decisions proposed in this round

These will be captured via `udm-decision-recorder` skill (which per D62 reads `NORTH_STAR.md` to confirm canonical pillar names case-sensitively before recording):

| Proposed | Topic | Pillar(s) served (canonical from NORTH_STAR.md) |
|---|---|---|
| D63 | `UdmTablesList` new column inventory (`CDCMode`, `PiiColumnList`, `DataClassification`, `CohortAssignment`, `IsEnabled`, `LegalHoldOnly`) + idempotent ALTER DDL with CHECK constraints | **Audit-grade**, **Traceability** |
| D64 | GPG passphrase storage strategy (after `udm-brainstorm` ≥3 alternatives) — recommend TPM2 sealed against PCR set; rationale per NORTH_STAR conflict-resolution rubric | **Operationally stable**, **Audit-grade** |
| D65 | Parity drift severity classification — fatal (Python version, library SHAs, `MALLOC_ARENA_MAX`), warning (transient sysctl), informational (kernel patch level) | **Operationally stable**, **Idempotent** |
| D66 | Automic job inventory + `JOB_<DOMAIN>_<CADENCE>` naming convention + per-job-type gate-table acquire / cancel-check / release contract | **Operationally stable**, **Audit-grade** |

If brainstorm or design-review surfaces additional choice points, more D-numbers will follow (each must include the "Pillar(s) served" line per D61).

## Naming conventions (Round 2-specific)

- **`UdmTablesList` columns**: `PascalCase` (e.g. `CDCMode`, `PiiColumnList`) — consistent with existing column style; legacy SCD2 column block (`SCD2Mode`, `SCD2DateColumns`, etc. per `CLAUDE.md` SCD2-P1-d) already follows this
- **`.env` keys**: `UPPER_SNAKE_CASE` (e.g. `ORACLE_DNA_USER`, `BCP_BIN_PATH`, `PARQUET_OUTPUT_DIR`)
- **Automic jobs**: `JOB_<DOMAIN>_<CADENCE>` (e.g. `JOB_PIPELINE_AM`, `JOB_RETENTION_MONTHLY`, `JOB_PARITY_VERIFY`)
- **GPG file paths**: `/etc/pipeline/<purpose>.json.gpg` (e.g. `/etc/pipeline/credentials.json.gpg`)
- **Parity baseline JSON**: `/etc/pipeline/parity_baseline.json` — single file, versioned via internal `pipeline_version` field; hash recorded in this doc § 4
- **Stored-procedure / runbook references**: existing schemes from Round 1 (`<Subject>_<Verb>` for SPs; `RB-<N>` for runbooks)

## Common patterns

### Idempotent ALTER DDL (per D34 greenfield posture)

Even though this is a greenfield build, the `UdmTablesList` table likely already exists from prior pipeline iterations. Round 2's new-column ALTERs use this pattern so re-deploy is a no-op:

```sql
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('General.dbo.UdmTablesList')
      AND name = 'CDCMode'
)
ALTER TABLE General.dbo.UdmTablesList
ADD CDCMode NVARCHAR(20) NOT NULL DEFAULT 'change_detect';
```

Every ALTER block in § 1.3 uses this `IF NOT EXISTS` guard.

### Gate-table column contract (AM/PM jobs only — per D29 revised + D33)

**Scope correction** (per D56 second-pass on Round 2 — see `_validation_log.md`): `General.ops.PipelineExecutionGate` is scoped to AM/PM cycles only per Round 1's `CK_PipelineExecutionGate_CycleType CHECK (CycleType IN ('AM', 'PM'))` (`phase1/01_database_schema.md` L327). Only `JOB_PIPELINE_AM` and `JOB_PIPELINE_PM` interact with the gate table; other jobs use a different concurrency pattern (§ 5.3.6). All gate-table column references use **Round 1 canonical column names** — Round 2 does NOT introduce new columns to the gate table.

| Phase | Read | Write (Round 1 canonical names per `01_database_schema.md` L302-347) |
|---|---|---|
| Acquire | (handled by SP-3 / SP-4) | Set by SP: `Status` → 'STARTING'; `ActualStartTime`; `ExecutingServer` (CHECK: 'production' / 'test' only); `BatchId`; `LastHeartbeatAt` |
| Heartbeat | None | `LastHeartbeatAt = SYSUTCDATETIME()` (progress detail goes to `PipelineEventLog`, NOT a gate-row column) |
| Cancel-check | `CancellationRequested`, `CancellationReason` | `CancellationAcknowledgedAt` (on ack only) |
| Release | None | `Status` ('SUCCEEDED' / 'FAILED' / 'CANCELLED' / 'TIMEOUT'); `ActualCompletionTime`; `FailureReason` (NULL when SUCCEEDED) |

Specifics in § 5.3 (AM/PM lifecycle via SP-3/SP-4); § 5.3.6 covers non-AM/PM jobs' alternative pattern.

---

## § 1. `UdmTablesList` canonical column inventory

`General.dbo.UdmTablesList` is the per-table configuration registry — the pipeline reads it at startup to know which tables to process, how to extract them, how to tokenize PII, how to score SCD2 dedup, etc. This section enumerates the **pre-Phase-1 columns** (already in production today, reverse-engineered from `CLAUDE.md` § "Architecture Decisions" and SCD2-P1-d migration block) plus the **6 new columns introduced by this build**.

**Authoritative types**: the inferred types below match the design intent documented in `CLAUDE.md`. Before any ALTER DDL runs in dev / test / prod, the operator MUST confirm actual production types via `INFORMATION_SCHEMA.COLUMNS` against `General.dbo.UdmTablesList` and reconcile any drift. Drift is a 🔴 — surface to BACKLOG and pause Round 2 close-out until resolved.

### § 1.1 Pre-Phase-1 canonical column inventory (29 columns)

Grouped by purpose for readability; column ordinal positions in the production table are NOT specified here — see `INFORMATION_SCHEMA.COLUMNS` for authoritative ordering.

#### § 1.1.1 Source connection + extraction routing (12 columns)

| # | Column | Type | NULL | Default | Owner reference | Purpose |
|---|---|---|---|---|---|---|
| 1 | `SourceObjectName` | `NVARCHAR(128)` | NO | — | `CLAUDE.md` § Architecture Decisions | Source table or view name (e.g. `ACCT`) |
| 2 | `SourceServer` | `NVARCHAR(128)` | NO | — | `CLAUDE.md` | Linked-server name or DNS hostname for the source DB |
| 3 | `SourceDatabase` | `NVARCHAR(128)` | NO | — | `CLAUDE.md` | Source database name |
| 4 | `SourceSchemaName` | `NVARCHAR(128)` | NO | — | `CLAUDE.md` | Source schema name (e.g. `osibank` for DNA) |
| 5 | `SourceName` | `NVARCHAR(50)` | NO | — | `CLAUDE.md` | Source-system short code (`DNA`, `CCM`, `EPICOR`) — also the schema used in `UDM_Stage.*` and `UDM_Bronze.*` |
| 6 | `SourceAggregateColumnType` | `NVARCHAR(50)` | YES | `NULL` | `CLAUDE.md` | Datatype of `SourceAggregateColumnName` (large tables only); used by extractor to format WHERE-clause boundaries |
| 7 | `SourceAggregateColumnName` | `NVARCHAR(128)` | YES | `NULL` | `CLAUDE.md` | Date column used by windowed extraction (large tables); NULL for small tables |
| 8 | `FirstLoadDate` | `DATE` | YES | `NULL` | `CLAUDE.md` | Earliest date boundary for initial loads of large tables |
| 9 | `LookbackDays` | `INT` | YES | `NULL` | `CLAUDE.md`, D11 | Rolling re-extraction window in days (D11 empirical L_99) |
| 10 | `SourceIndexHint` | `NVARCHAR(255)` | YES | `NULL` | `CLAUDE.md`, E-3 | Oracle `INDEX(table idx)` hint string — when populated, routes to oracledb extractor (date-chunked); NULL routes to ConnectorX bulk extractor |
| 11 | `PartitionOn` | `NVARCHAR(128)` | YES | `NULL` | `CLAUDE.md` | ConnectorX `partition_on` column for parallel extraction |
| 12 | `StageLoadTool` | `NVARCHAR(20)` | YES | `NULL` | `CLAUDE.md` | `'Python'` to process via this pipeline; `NULL` to skip (permanent — distinct from `IsEnabled` introduced in § 1.2) |

#### § 1.1.2 Target-table naming (3 columns)

| # | Column | Type | NULL | Default | Owner reference | Purpose |
|---|---|---|---|---|---|---|
| 13 | `StageTableName` | `NVARCHAR(128)` | YES | `NULL` | `CLAUDE.md` § Table Naming Conventions | Custom override for `UDM_Stage.{SourceName}.{name}` (default = `SourceObjectName`) |
| 14 | `BronzeTableName` | `NVARCHAR(128)` | YES | `NULL` | `CLAUDE.md` | Custom override for `UDM_Bronze.{SourceName}.{name}` |
| 15 | `StripSuffix` | `BIT` | NO | `0` | SS-1 (migrations/strip_suffix_column.py) | When `1`, drop the trailing `_cdc` / `_scd2_python` suffix on Stage / Bronze names. Default preserves legacy disambiguation per the SS-1 Do-NOT rule |

#### § 1.1.3 Per-table thresholds (1 column)

| # | Column | Type | NULL | Default | Owner reference | Purpose |
|---|---|---|---|---|---|---|
| 16 | `MaxRowsPerDay` | `BIGINT` | YES | `NULL` | P1-13 (`extraction_guard_per_table.py`) | Per-table override for the daily-extraction growth guard. When set, the guard limit becomes `max(5× baseline, MaxRowsPerDay)` instead of `5× baseline` alone — lets growing tables (CARDTXN ~280k rows/day in 2024) bypass the 5× multiplier while still blocking Cartesian-class spikes |

#### § 1.1.4 SCD2 enhancement block (12 columns, all per migrations/scd2_phase1_config.py + migrations/scd2_expected_retention_days.py)

These columns drive the per-PK SCD2 waterfall (SCD2-R2-a), duplicate resolution (SCD2-R8), exclude-from-hash (SCD2-R10.2), and retention classification (SCD2-R2-b) covered in `CLAUDE.md`.

| # | Column | Type | NULL | Default | Owner reference | Purpose |
|---|---|---|---|---|---|---|
| 17 | `SCD2Mode` | `NVARCHAR(20)` | NO | `'incremental'` | SCD2-P1-d | Allowed values: `'incremental'` / `'full'` / `'none'`. Default preserves current pipeline behavior bit-for-bit |
| 18 | `SCD2DateColumns` | `NVARCHAR(MAX)` | YES | `NULL` | SCD2-R2-a | CSV waterfall (primary → tie-breakers) for per-row `UdmSourceBeginDate` (e.g. `'DATEOPENED,DATELASTMAINT'`). NULL → falls back to batch-level scalar |
| 19 | `SourceDeleteDateColumn` | `NVARCHAR(128)` | YES | `NULL` | SCD2-P1-d | Source-system column marking row deletion (informs delete-close path) |
| 20 | `DuplicateResolutionOrder` | `NVARCHAR(MAX)` | YES | `NULL` | SCD2-R8 | CSV with optional `ASC`/`DESC` suffix for deterministic dedup (default `DESC`). Example: `'DATELASTMAINT,UdmEffectiveDateTime'`. NULL → `unique(keep='last')` (arbitrary but stable) |
| 21 | `AllowDuplicates` | `BIT` | NO | `0` | SCD2-P1-d | When `1`, `_dedup_source_pks()` is bypassed (allow per-PK duplicates in extraction) |
| 22 | `PreserveDateTime` | `BIT` | NO | `0` | SCD2-P1-d | When `1`, preserve source datetime precision beyond ms-truncation in Bronze |
| 23 | `RepairChainAfter` | `DATETIME2(3)` | YES | `NULL` | SCD2-P1-d, SCD2-R6 | Cutoff for chain-repair scope used by `tools/repair_scd2.py` |
| 24 | `AllowGaps` | `BIT` | NO | `0` | SCD2-P1-d | When `1`, allow gaps in source-date chain (defaults to disallow per business-date chain invariant) |
| 25 | `ExcludeFromHash` | `NVARCHAR(MAX)` | YES | `NULL` | SCD2-R10.2 | CSV of column names to drop from row-hash input (e.g. DNA `'DATELASTMAINT'` to prevent phantom CDC updates). **Note**: first run on existing Bronze triggers a one-time mass-update wave (B-3-class behavior) |
| 26 | `DefaultBeginDate` | `DATE` | YES | `NULL` | SCD2-R2-a | Fallback for `UdmSourceBeginDate` when ALL `SCD2DateColumns` are NULL on a row |
| 27 | `ForceNewSegmentColumns` | `NVARCHAR(MAX)` | YES | `NULL` | SCD2-P1-d | CSV — when any listed column changes, force a new SCD2 segment even if row hash matches |
| 28 | `ExpectedRetentionDays` | `INT` | YES | `NULL` | SCD2-R2-b | Per-table retention horizon. Informs delete-close classification: "within retention" (expected purge, INFO) vs "exceeds retention" (anomalous delete, WARNING — ACTV September incident pattern) |

#### § 1.1.5 Reconciliation (1 column)

| # | Column | Type | NULL | Default | Owner reference | Purpose |
|---|---|---|---|---|---|---|
| 29 | `LastModifiedColumn` | `NVARCHAR(128)` | YES | `NULL` | LT-2 (`cdc/reconciliation/modified_sweep.py`) | Source-system modification-timestamp column for Tier-2 modified-date sweep. Typical DNA value: `'DATELASTMAINT'`. CCM and EPICOR have NULL — neither has the column. **Reliability caveat per LT-2**: sweep cannot detect rows whose update slipped past this column (future batch job written without the bump); Tier-3 reconciliation (`reconcile_active_pks`) and Tier-4 (`reconcile_aggregates`) are the safety nets |

### § 1.2 New columns introduced by this build (6 columns — per D63 proposal)

These columns are NET-NEW for the UDM pipeline build. Each cites its driver decision and the edge-case series it addresses.

#### § 1.2.1 `CDCMode`

| Field | Value |
|---|---|
| Type | `NVARCHAR(20)` |
| Nullable | NO |
| Default | `'change_detect'` |
| Allowed values | `'change_detect'` / `'parquet_snapshot'` |
| Driver | D2 (Stage layer dropped — Parquet snapshots replace it) + Phase 4 cutover plan (`02_PHASES.md` § Per-table cutover sequence) |
| Edge cases | F-series (per-table cutover doesn't break in-flight processing); D-series (cadence cutover must be atomic) |
| Purpose | Per-table flag for which CDC mode applies. The Phase 4 cutover changes this column atomically inside a transaction (`UPDATE UdmTablesList SET CDCMode = 'parquet_snapshot'` after Stage `_cdc_is_current = 0` close), so the first post-cutover pipeline run uses the new flow without coordination |
| Implementation note | Default `'change_detect'` preserves current pipeline behavior bit-for-bit on first deployment. Phase 4 flips per-table as cohorts soak |

#### § 1.2.2 `PiiColumnList`

| Field | Value |
|---|---|
| Type | `NVARCHAR(MAX)` |
| Nullable | YES |
| Default | `NULL` |
| Format | CSV of column names — e.g. `'SSN,EMAIL,PHONE'`; case-sensitive match against source column names |
| Driver | D6 (in-house tokenization vault) + D26 (append-only PiiTokenProvenance) |
| Edge cases | P-series (PII / encryption); P1 (deterministic encryption), P5 (no plaintext PII in logs), P8 (vault audit trail on decrypt), P9 (cross-source isolation) |
| Purpose | Pipeline reads this list before extraction. Each listed column gets tokenized via `PiiVault_GetOrCreateToken` (SP-1) before the row hits `_row_hash` computation. `NULL` = no tokenization (table has no PII columns) |
| Implementation note | Tokenization is row-level idempotent: same plaintext + same `SourceName` returns the same token (per D6 deterministic guarantee) |

#### § 1.2.3 `DataClassification`

| Field | Value |
|---|---|
| Type | `NVARCHAR(20)` |
| Nullable | YES |
| Default | `NULL` |
| Allowed values | `'PII'` / `'PCI'` / `'none'` / `NULL` (`NULL` = not yet classified) |
| Driver | D30 (7-year retention with legal-hold override; CCPA/CPRA/GLBA alignment) |
| Edge cases | D-series (retention differs by classification); P-series (PII handling tiers) |
| Purpose | Drives retention SLAs and audit reporting tiers. PII rows have CCPA right-to-deletion workflow (RB-10); PCI rows have GLBA-aligned retention; `'none'` rows follow default 7-year policy |
| Implementation note | `NULL` is allowed during onboarding (operator hasn't classified yet) but should not persist post-Phase-4. Phase 4 enablement checklist requires `DataClassification IS NOT NULL` before cohort assignment |

#### § 1.2.4 `CohortAssignment`

| Field | Value |
|---|---|
| Type | `NVARCHAR(50)` |
| Nullable | YES |
| Default | `NULL` |
| Format | Free-text tag (e.g. `'cohort-1-pilot'`, `'cohort-3-large'`, `'cohort-5-pii-heavy'`) |
| Driver | Phase 4 production-rollout soak protocol (`02_PHASES.md` § Per-table enablement) |
| Edge cases | F-series (cohort isolates blast radius during rollout); operational stability |
| Purpose | Cohort tag for Phase 4 rollout sequencing. Pipeline enables 5-10 tables per cohort with a 1-week soak before next cohort. `NULL` = not yet cohort-assigned |
| Implementation note | Cohort scheme is operator judgment — typical pattern is `cohort-N-<descriptor>` where N is rollout order |

#### § 1.2.5 `IsEnabled`

| Field | Value |
|---|---|
| Type | `BIT` |
| Nullable | NO |
| Default | `1` |
| Driver | Operational toggle (supports D29 revised + D33 cancellation flow) |
| Edge cases | F-series (disable a table without removing config); operational stability |
| Purpose | Operator switch — `0` = skip this table in pipeline runs; `1` = process. **Distinct from `StageLoadTool IS NULL`**: `StageLoadTool` is permanent skip semantics (this table has no pipeline ownership); `IsEnabled = 0` is transient (operator wants to pause this table) |
| Implementation note | Pipeline reads at every run start. Honors the toggle before claiming any `PipelineExecutionGate` row for the table. Audit trail: every `IsEnabled` flip writes a row to `General.ops.ManualCorrectionLog` (separate from `PipelineEventLog`) |

#### § 1.2.6 `LegalHoldOnly`

| Field | Value |
|---|---|
| Type | `BIT` |
| Nullable | NO |
| Default | `0` |
| Driver | D30 (legal-hold override) + RB-11 (retention enforcement) |
| Edge cases | P-series (PII retention); legal-hold case mirroring `PiiVault.Status = 'legal_hold_only'` |
| Purpose | When `1`, this table's data is held against the standard retention purge. RB-11 reads this column to decide which tables to skip during monthly retention enforcement runs |
| Implementation note | Pairs with `PiiVault.Status = 'legal_hold_only'` at the row level — table-level legal hold is the coarse-grained variant. Setting `LegalHoldOnly = 1` does NOT cascade to PiiVault rows automatically; both must be set when broad legal hold is required |

### § 1.3 Idempotent ALTER DDL for new columns

Each ALTER block uses the `IF NOT EXISTS` guard (per § "Common patterns" above and D34 greenfield posture) so re-deploy is a no-op. The DDL belongs in `migrations/udm_tables_list_phase1_columns.py` (per Round 6 deployment scope).

```sql
-- D63.1: CDCMode (per § 1.2.1)
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('General.dbo.UdmTablesList')
      AND name = 'CDCMode'
)
BEGIN
    ALTER TABLE General.dbo.UdmTablesList
    ADD CDCMode NVARCHAR(20) NOT NULL
        CONSTRAINT DF_UdmTablesList_CDCMode DEFAULT 'change_detect';
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID('General.dbo.UdmTablesList')
      AND name = 'CK_UdmTablesList_CDCMode'
)
BEGIN
    ALTER TABLE General.dbo.UdmTablesList
    ADD CONSTRAINT CK_UdmTablesList_CDCMode
        CHECK (CDCMode IN ('change_detect', 'parquet_snapshot'));
END;
GO

-- D63.2: PiiColumnList (per § 1.2.2)
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('General.dbo.UdmTablesList')
      AND name = 'PiiColumnList'
)
BEGIN
    ALTER TABLE General.dbo.UdmTablesList
    ADD PiiColumnList NVARCHAR(MAX) NULL;
END;
GO

-- D63.3: DataClassification (per § 1.2.3)
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('General.dbo.UdmTablesList')
      AND name = 'DataClassification'
)
BEGIN
    ALTER TABLE General.dbo.UdmTablesList
    ADD DataClassification NVARCHAR(20) NULL;
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE parent_object_id = OBJECT_ID('General.dbo.UdmTablesList')
      AND name = 'CK_UdmTablesList_DataClassification'
)
BEGIN
    ALTER TABLE General.dbo.UdmTablesList
    ADD CONSTRAINT CK_UdmTablesList_DataClassification
        CHECK (DataClassification IS NULL OR DataClassification IN ('PII', 'PCI', 'none'));
END;
GO

-- D63.4: CohortAssignment (per § 1.2.4)
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('General.dbo.UdmTablesList')
      AND name = 'CohortAssignment'
)
BEGIN
    ALTER TABLE General.dbo.UdmTablesList
    ADD CohortAssignment NVARCHAR(50) NULL;
END;
GO

-- D63.5: IsEnabled (per § 1.2.5)
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('General.dbo.UdmTablesList')
      AND name = 'IsEnabled'
)
BEGIN
    ALTER TABLE General.dbo.UdmTablesList
    ADD IsEnabled BIT NOT NULL
        CONSTRAINT DF_UdmTablesList_IsEnabled DEFAULT 1;
END;
GO

-- D63.6: LegalHoldOnly (per § 1.2.6)
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('General.dbo.UdmTablesList')
      AND name = 'LegalHoldOnly'
)
BEGIN
    ALTER TABLE General.dbo.UdmTablesList
    ADD LegalHoldOnly BIT NOT NULL
        CONSTRAINT DF_UdmTablesList_LegalHoldOnly DEFAULT 0;
END;
GO
```

**Pattern notes**:
- Every `ALTER ADD` separates column add from constraint add (two `IF NOT EXISTS` checks per column where a CHECK exists) — re-deploy safe in either order
- Named DEFAULT constraints (`DF_UdmTablesList_<col>`) allow targeted DROP in future migrations
- `GO` separates batches so the DEFAULT is committed before any post-step relies on it (some SQL Server linked-server / sysadmin pipelines run each batch as its own session — explicit `GO` avoids re-deploy weirdness)

### § 1.4 CHECK constraints (existing + new — full reconciliation)

This § lists ALL CHECK constraints that should exist on `UdmTablesList` after Round 2 lands. Verify each is present (or add via the ALTER blocks in § 1.3 for new ones).

| Constraint name | Predicate | Source | Status after Round 2 |
|---|---|---|---|
| `CK_UdmTablesList_SCD2Mode` | `SCD2Mode IN ('incremental', 'full', 'none')` | SCD2-P1-d migration (existing) | Confirm present; ADD via idempotent guard if missing |
| `CK_UdmTablesList_AllowDuplicates` | `AllowDuplicates IN (0, 1)` | BIT inherent (existing) | Inherent in BIT type; no explicit CHECK needed |
| `CK_UdmTablesList_StripSuffix` | `StripSuffix IN (0, 1)` | BIT inherent (existing) | Inherent in BIT type |
| `CK_UdmTablesList_CDCMode` | `CDCMode IN ('change_detect', 'parquet_snapshot')` | NEW per § 1.2.1 | Added by § 1.3 block |
| `CK_UdmTablesList_DataClassification` | `DataClassification IS NULL OR DataClassification IN ('PII', 'PCI', 'none')` | NEW per § 1.2.3 | Added by § 1.3 block |

A 🟡 follow-up: the SCD2-P1-d migration may not have explicit CHECK on `SCD2Mode`. Confirm via:

```sql
SELECT name, definition
FROM sys.check_constraints
WHERE parent_object_id = OBJECT_ID('General.dbo.UdmTablesList');
```

If `CK_UdmTablesList_SCD2Mode` is absent, add via the same idempotent-guard pattern as § 1.3.

### § 1.5 Cross-doc updates required

After this § locks, the following docs need pointer-updates so a fresh reader lands here for the canonical inventory:

| Doc | Update |
|---|---|
| `docs/migration/01_ARCHITECTURE.md` | Add reference to "UdmTablesList canonical inventory at `phase1/02_configuration.md` § 1" wherever existing text describes `UdmTablesList` |
| `docs/migration/phase1/01_database_schema.md` | References section (near doc top or bottom) points to `02_configuration.md` § 1 as the canonical column inventory; `01_database_schema.md` covers `General.ops` schema; `02_configuration.md` covers `General.dbo.UdmTablesList` |
| `CLAUDE.md` (project root) | No structural change — CLAUDE.md is the technical-history narrative; the formal spec lives in `02_configuration.md`. Optional: add a one-line pointer in CLAUDE.md § "Key Architecture Decisions" pointing to this doc |
| `docs/migration/02_PHASES.md` | Phase 0 deliverable 0.5 (column-schema reviewed by DBA) can cross-link to this § 1 once locked |
| `docs/migration/04_EDGE_CASES.md` | Where edge cases reference `UdmTablesList` columns (e.g. F-series), cite `02_configuration.md` § 1.1/§ 1.2 row for the column |

These updates happen at Round 2 close-out, not in this § itself.

---

## § 2. `.env` per-server file structure

The `.env` file lives at `/debi/.env` on every pipeline server (NOT project root — per `CLAUDE.md` "Gotchas"). It is read at process start before any DB connection or extraction. Sensitive values (passwords, private keys) reference the GPG envelope (§ 3); non-sensitive values live in `.env` as plaintext.

### § 2.1 Canonical key set (~45 keys)

Grouped by purpose. Authoritative — every key referenced by `config.py`, `sources.py`, `connections.py`, or any module in `data_load/` or `extract/` MUST appear here. Drift between code and this list is a 🔴 — caught by Round 1 v3 hardening + this doc's validation gate.

#### § 2.1.1 Source DB credentials (referenced by `sources.py`)

| Key | Type | Per-server? | Source | Purpose |
|---|---|---|---|---|
| `ORACLE_DNA_HOST` | string | YES | `.env` plaintext | Oracle DNA hostname or IP |
| `ORACLE_DNA_PORT` | int | YES | `.env` plaintext | Oracle listener port (default `1521`) |
| `ORACLE_DNA_SERVICE` | string | YES | `.env` plaintext | Oracle service name |
| `ORACLE_DNA_USER` | string | YES | `.env` plaintext | Read-only service account |
| `ORACLE_DNA_PASSWORD` | string | YES | **GPG envelope** | Service-account password — never plaintext in `.env` |
| `SQLSERVER_CCM_HOST` | string | YES | `.env` plaintext | CCM SQL Server hostname |
| `SQLSERVER_CCM_USER` | string | YES | `.env` plaintext | Read-only service account |
| `SQLSERVER_CCM_PASSWORD` | string | YES | **GPG envelope** | Service-account password |
| `SQLSERVER_EPICOR_HOST` | string | YES | `.env` plaintext | EPICOR SQL Server hostname |
| `SQLSERVER_EPICOR_USER` | string | YES | `.env` plaintext | Read-only service account |
| `SQLSERVER_EPICOR_PASSWORD` | string | YES | **GPG envelope** | Service-account password |

#### § 2.1.2 Target SQL Server (referenced by `connections.py`)

| Key | Type | Per-server? | Source | Purpose |
|---|---|---|---|---|
| `TARGET_SERVER` | string | YES | `.env` plaintext | Target SQL Server hostname (UDM_Stage / UDM_Bronze / General live here) |
| `TARGET_DB_STAGE` | string | NO (parity) | `.env` plaintext | Stage DB name (`UDM_Stage`) |
| `TARGET_DB_BRONZE` | string | NO (parity) | `.env` plaintext | Bronze DB name (`UDM_Bronze`) |
| `TARGET_DB_GENERAL` | string | NO (parity) | `.env` plaintext | Metadata DB name (`General`) |
| `TARGET_USER` | string | YES | `.env` plaintext | Pipeline service account |
| `TARGET_PASSWORD` | string | YES | **GPG envelope** | Service-account password |

#### § 2.1.3 Vault DB (NEW — per D6)

| Key | Type | Per-server? | Source | Purpose |
|---|---|---|---|---|
| `VAULT_DB_SERVER` | string | YES | `.env` plaintext | Vault SQL Server hostname (may equal `TARGET_SERVER` for single-server deployments) |
| `VAULT_DB_NAME` | string | NO (parity) | `.env` plaintext | Vault DB name — typically the same `General` DB since `PiiVault` lives in `General.ops` (per D45.1) |
| `VAULT_DB_USER` | string | YES | `.env` plaintext | Vault-only service account (least-privilege — can only call SP-1 through SP-N) |
| `VAULT_DB_PASSWORD` | string | YES | **GPG envelope** | Service-account password |
| `VAULT_GPG_KEY_ID` | string | NO (parity) | `.env` plaintext | GPG key ID (long-form fingerprint) used as PRIMARY recipient on the envelope |

#### § 2.1.4 Pipeline paths

| Key | Type | Per-server? | Source | Purpose |
|---|---|---|---|---|
| `CSV_OUTPUT_DIR` | path | NO (parity) | `.env` plaintext | BCP CSV staging dir (`/var/pipeline/csv`) |
| `PARQUET_OUTPUT_DIR` | path | NO (parity) | `.env` plaintext | Parquet output dir (`/mnt/pipeline-archive/parquet`) — network drive per D4 |
| `LOG_DIR` | path | NO (parity) | `.env` plaintext | Python log file directory (`/var/log/pipeline`) |
| `TMP_DIR` | path | NO (parity) | `.env` plaintext | Scratch directory for transient files |

#### § 2.1.5 External tools

| Key | Type | Per-server? | Source | Purpose |
|---|---|---|---|---|
| `BCP_BIN_PATH` | path | NO (parity) | `.env` plaintext | `/opt/mssql-tools18/bin/bcp` — version pinned per W-1 |
| `GPG_BIN_PATH` | path | NO (parity) | `.env` plaintext | `/usr/bin/gpg2` |
| `ORACLE_INSTANT_CLIENT_DIR` | path | NO (parity) | `.env` plaintext | Oracle 19c install path |
| `ODBC_DRIVER` | string | NO (parity) | `.env` plaintext | `'ODBC Driver 18 for SQL Server'` |

#### § 2.1.6 Tuning knobs (per `config.py`)

| Key | Type | Per-server? | Source | Purpose |
|---|---|---|---|---|
| `MAX_RSS_GB` | int | NO (parity) | `.env` plaintext | RSS ceiling per B-8 (default `48`) |
| `POLARS_BATCH_SIZE` | int | NO (parity) | `.env` plaintext | `write_csv(batch_size=4096)` per BCP CSV Contract |
| `OVERLAP_MINUTES` | int | NO (parity) | `.env` plaintext | Per V-7 (default `0`) |
| `SCD2_UPDATE_BATCH_SIZE` | int | NO (parity) | `.env` plaintext | Per B-2 (default `4000`, max `5000`) |
| `BCP_BATCH_SIZE` | int | NO (parity) | `.env` plaintext | BCP `-b` for Stage / staging loads (Bronze SCD2 uses `atomic=True` per E-3) |
| `WORKERS_DEFAULT` | int | NO (parity) | `.env` plaintext | Default `--workers` for orchestrator CLIs |
| `CDC_VERIFY_STRICT_ON_FAILURE` | bit | NO (parity) | `.env` plaintext | Per Phase 2 cdc_root_cause_blueprint (default `1`) |
| `CDC_VERIFY_MAX_CANDIDATES` | int | NO (parity) | `.env` plaintext | Per Phase 2 cdc_root_cause_blueprint (default `10000`) |

#### § 2.1.7 Operational tags

| Key | Type | Per-server? | Source | Purpose |
|---|---|---|---|---|
| `SERVER_ROLE` | string | YES | `.env` plaintext | `'dev'` / `'test'` / `'prod'` — informs gate-row owner |
| `SERVER_NAME` | string | YES | `.env` plaintext | Hostname literal (e.g. `'pipeline-prod-01'`) |
| `DEPLOY_VERSION` | string | YES (during rollout) | `.env` plaintext | semver (e.g. `'1.4.2'`) — set during deploy; reset on rollback |
| `AUDIT_LOG_LEVEL` | string | NO (parity) | `.env` plaintext | `'INFO'` in prod; `'DEBUG'` in dev — but per CCL discipline, log-level differences need risk evaluation |

#### § 2.1.8 Snowflake (per D3 + D5)

| Key | Type | Per-server? | Source | Purpose |
|---|---|---|---|---|
| `SNOWFLAKE_ACCOUNT` | string | YES (env-dependent) | `.env` plaintext | Snowflake account identifier |
| `SNOWFLAKE_WAREHOUSE` | string | YES | `.env` plaintext | Warehouse name (cost-tier-tagged) |
| `SNOWFLAKE_USER` | string | YES | `.env` plaintext | Service account |
| `SNOWFLAKE_PRIVATE_KEY_PATH` | path | YES | `.env` plaintext (path); key file itself is **GPG-decrypted from envelope** | Path to the decrypted RSA private key file (ephemeral; written to `/dev/shm/...` then deleted after Snowflake session establishes) |
| `SNOWFLAKE_DATABASE` | string | NO (parity for Bronze mirror) | `.env` plaintext | `'UDM_BRONZE_MIRROR'` |
| `SNOWFLAKE_SCHEMA` | string | NO (parity) | `.env` plaintext | Source schema per source system (DNA / CCM / EPICOR) |

### § 2.2 Per-server differences — what differs vs what MUST match (per D27)

D27 mandates strict parity across dev / test / prod for code-relevant config. Only operational tags and infrastructure addresses may differ; behavioral knobs (batch sizes, log levels, thresholds) MUST match exactly. § 4 parity baseline JSON encodes this contract.

| Bucket | Must match across all 3 servers? | Examples |
|---|---|---|
| Code-relevant tuning knobs | **YES — D27 invariant** | `POLARS_BATCH_SIZE`, `SCD2_UPDATE_BATCH_SIZE`, `MAX_RSS_GB`, `OVERLAP_MINUTES`, `CDC_VERIFY_STRICT_ON_FAILURE`, `CDC_VERIFY_MAX_CANDIDATES`, `BCP_BATCH_SIZE`, `WORKERS_DEFAULT` |
| Pipeline paths | **YES — D27 invariant** | `CSV_OUTPUT_DIR`, `PARQUET_OUTPUT_DIR`, `LOG_DIR`, `TMP_DIR`, `BCP_BIN_PATH`, `GPG_BIN_PATH`, `ORACLE_INSTANT_CLIENT_DIR` |
| Target DB names | YES (parity) | `TARGET_DB_STAGE`, `TARGET_DB_BRONZE`, `TARGET_DB_GENERAL`, `VAULT_DB_NAME`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA` |
| Audit / log level | **YES — D27 invariant**, BUT see exception | `AUDIT_LOG_LEVEL` (target: prod = `INFO`; dev = `DEBUG` is acceptable IF documented in parity baseline exceptions § 4.3) |
| Server-specific addresses | NO — expected to differ | `ORACLE_DNA_HOST`, `SQLSERVER_CCM_HOST`, `SQLSERVER_EPICOR_HOST`, `TARGET_SERVER`, `VAULT_DB_SERVER`, `SNOWFLAKE_ACCOUNT` |
| Operational tags | NO — expected to differ | `SERVER_ROLE`, `SERVER_NAME`, `DEPLOY_VERSION` |
| Service-account passwords | NO — different per env (security boundary) | All `*_PASSWORD` from GPG envelope |
| Service-account usernames | NO (typically differ per env) | `ORACLE_DNA_USER`, `SQLSERVER_CCM_USER`, etc. |

**Critical rule**: If a tuning knob has the SAME value in dev / test / prod but a different value would be reasonable in dev (e.g., smaller `MAX_RSS_GB` on a smaller dev box), the dev `.env` MUST still encode the production-equivalent value. Pipeline behavior MUST be identical across environments at the runtime-decision level. Smaller dev hardware is handled via fewer concurrent tables (`--workers 2` instead of `--workers 4`), not via different env-var values.

### § 2.3 Sensitive-key handling

Every key in the "GPG envelope" Source column above MUST come from the encrypted envelope (§ 3), NEVER plaintext in `.env`. The pipeline at startup:

1. Reads `.env` (plaintext keys + paths)
2. Decrypts `/etc/pipeline/credentials.json.gpg` (via `data_load/credentials_loader.py` per § 3.3)
3. Merges decrypted dict into the env-config namespace
4. **Sensitive keys are NEVER written to log files, NEVER passed through subprocess argv (BCP `-P` reads from a temp file, deleted post-call), NEVER cached in CSV / Parquet output**

**Validation rule** (Round 6 deployment): a pre-flight script runs on every server confirming no `*_PASSWORD` key has a plaintext value in `.env`. If found, deployment fails fast. Pattern: `grep -E '^[A-Z_]+_PASSWORD=' /debi/.env | grep -vE '=$|=GPG_SOURCED$'` returns empty.

`.env` placeholder pattern for sensitive keys:

```bash
# Sensitive — sourced from /etc/pipeline/credentials.json.gpg at process start
ORACLE_DNA_PASSWORD=GPG_SOURCED
SQLSERVER_CCM_PASSWORD=GPG_SOURCED
SQLSERVER_EPICOR_PASSWORD=GPG_SOURCED
TARGET_PASSWORD=GPG_SOURCED
VAULT_DB_PASSWORD=GPG_SOURCED
```

The literal string `GPG_SOURCED` is a sentinel — `credentials_loader.py` overwrites it with the decrypted value at runtime. If decryption fails, the loader raises FATAL — the pipeline does NOT fall back to the literal `GPG_SOURCED` string as a "password attempt" against any DB.

---

## § 3. GPG-encrypted credential strategy (B13 Phase 0 deliverable 0.12)

This § specifies the encrypted credential envelope, the passphrase-storage decision (D64 proposed via `udm-brainstorm`), the Python decryption flow interface (impl in R3), the key-rotation runbook (RB-12 stub), and the audit trail.

### § 3.1 GPG envelope spec

| Property | Value |
|---|---|
| File path | `/etc/pipeline/credentials.json.gpg` |
| Owner / mode | `pipeline:pipeline 0640` |
| Cipher algorithm | AES256 (`--cipher-algo AES256`) |
| Compression | ZIP (`--compress-algo ZIP`) |
| Hash | SHA512 (`--digest-algo SHA512`) |
| Recipients (--recipient) | (a) Pipeline service-account public key (primary — typical decrypt path); (b) Ops break-glass key (secondary — incident-response decrypt) |
| Format | OpenPGP binary (`.gpg`), NOT armor (`.asc`) — smaller |
| Plaintext content | JSON object — keys match `.env` `*_PASSWORD` / `SNOWFLAKE_PRIVATE_KEY` placeholder names; values are the actual secrets |

**Plaintext envelope structure** (JSON):

```json
{
  "schema_version": "1.0",
  "rotated_at": "2026-05-10T00:00:00Z",
  "credentials": {
    "ORACLE_DNA_PASSWORD": "...",
    "SQLSERVER_CCM_PASSWORD": "...",
    "SQLSERVER_EPICOR_PASSWORD": "...",
    "TARGET_PASSWORD": "...",
    "VAULT_DB_PASSWORD": "...",
    "SNOWFLAKE_PRIVATE_KEY_PEM": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
  }
}
```

**Generation procedure** (reproducible from a fresh RHEL VM):

```bash
# As pipeline operator on a secure jump host (NOT on pipeline servers):
gpg2 --import pipeline-service-account.pub
gpg2 --import ops-breakglass.pub

# Create plaintext payload (in tmpfs / shred-on-exit)
mktemp_creds=$(mktemp /dev/shm/creds.XXXXXX)
cat > "$mktemp_creds" <<'EOF'
{ "schema_version": "1.0", "rotated_at": "2026-05-10T00:00:00Z", "credentials": { ... } }
EOF

# Encrypt to envelope
gpg2 --output credentials.json.gpg \
     --recipient <pipeline-key-fingerprint> \
     --recipient <ops-breakglass-fingerprint> \
     --cipher-algo AES256 \
     --compress-algo ZIP \
     --digest-algo SHA512 \
     --encrypt "$mktemp_creds"

# Shred plaintext
shred -u "$mktemp_creds"

# Compute and record envelope hash for the parity baseline (§ 4)
sha256sum credentials.json.gpg
```

**Verification**: every pipeline server's startup logs the envelope's SHA-256 to `PipelineEventLog` (per § 3.5). Cross-server parity check (§ 4) compares this hash; mismatch is a 🔴 (fatal — different envelopes deployed across servers).

### § 3.2 Passphrase storage decision — `udm-brainstorm` ≥3 alternatives (D64 proposed)

**QUESTION**: How should the GPG passphrase be stored on each pipeline server such that `credentials_loader.py` can auto-decrypt `/etc/pipeline/credentials.json.gpg` at process start (no interactive input) while preserving audit-grade access controls?

**CONTEXT**:
- The passphrase unlocks the pipeline service-account private key (which then decrypts the envelope)
- Pipeline runs are Automic-scheduled AM/PM (D29 revised) — interactive unlock is unacceptable
- Loss of passphrase requires re-issuing the entire envelope (24+ hour ops procedure)
- Existing security infrastructure: RHEL servers with TPM2 hardware (per typical financial-services build), no HSM (D6 cost ceiling), no cloud KMS (D6 sovereign-data rule)
- Cost of being wrong: HIGH — passphrase leak compromises ALL source DB credentials
- Reversibility: HARD — once a passphrase strategy is operational, migrating to another is a key-rotation event (RB-12)

**OPTIONS** (4 enumerated; spec says ≥3):

#### Option A — TPM2 sealed against PCR set (RECOMMENDED)

- **Description**: Passphrase sealed in TPM2 NVRAM, unsealed only when boot-time PCR measurements match a known-good configuration (kernel, initrd, bootloader). `gpg2 --pinentry-mode loopback --passphrase-fd 0` reads the unsealed passphrase from a TPM2 tooling invocation (`tpm2_unseal`).
- **Pros**:
  - Hardware-rooted trust — passphrase is unreachable if disk is removed from chassis
  - PCR sealing means a tampered boot (e.g., evil-maid kernel swap) refuses to unseal
  - Standard RHEL-supported via `tpm2-tools` package (no novel OSS to approve)
  - No operator-in-the-loop at boot (Automic schedules run unattended)
- **Cons**:
  - Coupling to kernel + bootloader version — every patch requires re-sealing (RB-12 includes patch-day procedure)
  - Cross-server parity requires identical TPM2 PCR policy on dev / test / prod (more parity surface)
  - TPM2 hardware faults are catastrophic until break-glass recovery via secondary recipient
- **Cost**: Medium (procedure documentation + RB-12 + sysadmin onboarding)
- **Reversibility**: Hard (envelope rotation requires re-sealing)
- **Edge cases**: F-series (TPM2 fault → fallback to break-glass key); P-series (audit trail captures unseal events)
- **Decisions touched**: D27 (parity — PCR policy is parity-required); D54 (hooks — TPM2 unseal hook could go pre-pipeline-start)

#### Option B — Linux kernel keyring (`keyutils`)

- **Description**: Passphrase stored in the kernel session keyring (`request-key` mechanism). Loaded by a privileged daemon at boot; pipeline process reads via `keyctl print <id>`. Auto-flushed on reboot.
- **Pros**:
  - Pure software — no TPM hardware dependency (works on VMs without vTPM)
  - Lower coupling to boot path than TPM2
  - Simpler key-rotation (no PCR re-sealing)
- **Cons**:
  - Passphrase exists in plaintext in kernel RAM — root on the box reads it freely
  - No hardware attestation (a corrupted disk image with the keyring is unlocked anywhere it runs)
  - Boot-time loading mechanism (the daemon that populates the keyring) is itself a credential-handling point; chicken-and-egg
- **Cost**: Small (simpler than TPM2)
- **Reversibility**: Reversible (envelope rotation doesn't touch keyring code)
- **Edge cases**: F-series (server compromise immediately exposes passphrase)
- **Decisions touched**: D27 (parity — daemon setup is parity-required)

#### Option C — Hardware token (YubiKey) via `gpg-agent`

- **Description**: GPG private key resides on a YubiKey; passphrase entered on the YubiKey via touch-to-confirm. Pipeline gpg-agent talks to the YubiKey over USB.
- **Pros**:
  - Strongest hardware-rooted trust (private key never leaves the YubiKey)
  - Industry-standard for sensitive ops accounts
- **Cons**:
  - **Requires physical USB device on every pipeline server** — defeats Automic unattended schedule (no operator on console at 2 AM)
  - YubiKey loss → broken pipeline until replacement issued
  - Multi-server (3-server failover) needs 3 YubiKeys — cost + procurement
  - Touch-to-confirm contradicts unattended cycle
- **Cost**: Large (hardware procurement + procedure)
- **Reversibility**: Hard (key migration to new YubiKey is its own ceremony)
- **Edge cases**: F-series (YubiKey unplugged = pipeline stops)
- **Verdict**: **Incompatible with Automic unattended cycle (D29 revised + D33).** Listed for completeness; rejected.

#### Option D — Offline manual unlock at process start

- **Description**: Operator-on-call enters passphrase via `pinentry` once per AM/PM cycle; cached in `gpg-agent` for the cycle's duration; cleared at cycle end.
- **Pros**:
  - Simplest threat model — passphrase never persisted on disk
  - Standard `gpg-agent` workflow
- **Cons**:
  - Defeats unattended Automic schedule — operator must be on-shift 2× daily, weekends, holidays
  - 730 unlock events / year × 3 servers = 2,190 operator interactions / year — burnout + error-rate risk
- **Cost**: Small (no infra)
- **Reversibility**: Reversible
- **Verdict**: **Incompatible with operational stability pillar.** Rejected.

**RECOMMENDATION**: **Option A — TPM2 sealed against PCR set.**

**JUSTIFICATION** (per `NORTH_STAR.md` conflict-resolution rubric, walked in priority order):

1. **Audit-grade always wins**: TPM2 PCR-sealing gives auditable evidence that a passphrase unsealed event happened on a known-good system (PCR measurements in `tpm2_unseal` log). Option B (kernel keyring) has no such attestation.
2. **Traceability beats convenience**: TPM2 unseal events go to syslog with PCR values, integrating with the audit trail. Option D (manual unlock) leaves no record of who unlocked.
3. **Idempotent beats fast**: Sealed passphrase is the same byte stream every boot — idempotent. Option B has a daemon timing dependency.
4. **Operational stability beats cleverness**: TPM2 supports Automic unattended schedule (the entire D29 design depends on it). Options C + D are incompatible with unattended runs — rejected on this pillar alone.
5. **$120K/year ceiling**: TPM2 is included in standard RHEL server pricing — no incremental cost. Option C requires hardware procurement.

**NEXT STEPS** (if Option A locks as D64):
- Document TPM2 sealing procedure in `data_load/credentials_loader.py` interface (§ 3.3)
- Add PCR policy hash to parity baseline JSON (§ 4)
- Phase 0 deliverable 0.12 schedules the actual TPM2 setup on dev / test / prod servers
- RB-12 (§ 3.4) includes patch-day procedure (re-seal after kernel update)

**What would reverse this recommendation**:
- Discovery that TPM2 hardware on one or more pipeline servers is faulty / unsupported (forces fallback to Option B with risk acceptance documented)
- Compliance requirement for FIPS 140-2 Level 3 (would push toward Option C with operator-attended cycles — rare for ETL pipelines but possible for PCI workloads)

### § 3.3 Decryption flow inside Python — `data_load/credentials_loader.py` interface

Interface only — implementation deferred to Round 3 (per Phase 1 sub-area scope). Interface freezes the contract.

```python
# data_load/credentials_loader.py — interface signature (Round 3 implementation)

from typing import Literal, NewType

PassphraseSource = Literal["tpm2", "keyutils", "env", "file"]
CredentialsDict = NewType("CredentialsDict", dict)  # secrets — never log this

def load_credentials(
    envelope_path: str = "/etc/pipeline/credentials.json.gpg",
    passphrase_source: PassphraseSource = "tpm2",
    passphrase_file_path: str | None = None,  # only used when passphrase_source == "file"
) -> CredentialsDict:
    """Decrypt the GPG envelope and return the credentials dict.

    Args:
        envelope_path: Path to .gpg envelope (default per § 3.1).
        passphrase_source: How to retrieve the GPG passphrase. Default 'tpm2' per D64.
        passphrase_file_path: Path to passphrase file (only honored when source == 'file' — TEST USE ONLY).

    Returns:
        CredentialsDict mapping .env key names (e.g. 'ORACLE_DNA_PASSWORD') to plaintext values.

    Raises:
        CredentialsLoadError (FATAL — pipeline must not proceed):
            - Envelope file missing / unreadable
            - GPG decryption failed (wrong recipient / corrupted envelope)
            - Passphrase source returned empty / not found
            - JSON schema_version mismatch (env was rotated to a newer version this code doesn't understand)
            - Sensitive value contains the literal sentinel 'GPG_SOURCED' (loop / re-substitution bug)

    Side effects:
        - Writes ONE 'CREDENTIALS_LOAD' event to General.ops.PipelineEventLog (§ 3.5)
            with metadata { envelope_sha256, passphrase_source, key_id_used }
        - NEVER writes the plaintext credentials to any log
        - NEVER passes credentials through argv / environment of any subprocess

    Idempotency:
        - Multiple calls within one process return the same dict (cached after first decrypt)
        - On TPM2 unseal failure, NO RETRY — the loader is fail-fast
    """
```

**Implementation notes (for Round 3)**:
- Use `gpg2 --batch --pinentry-mode loopback --passphrase-fd 0 --decrypt envelope.gpg` via `subprocess.run` with `input=passphrase.encode()`
- Cache the decrypted dict at module level (one decrypt per process)
- Zero out the passphrase variable after `subprocess.run` returns (`del passphrase` plus best-effort `ctypes` memset where supported)
- For TPM2: shell out to `tpm2_unseal -c <handle>` and capture stdout; check return code; STDERR to PipelineLog as DEBUG
- For `SNOWFLAKE_PRIVATE_KEY_PEM`: write to `/dev/shm/snowflake_pk_<pid>` mode 0600, return the path in the dict, delete the file after Snowflake auth completes (a separate `release_snowflake_key()` function)

### § 3.4 Key-rotation runbook (RB-12 stub)

Full runbook authored via `udm-runbook-author` in a separate task once D64 locks. Outline:

**When**: KEK rotation (annual per industry standard for service-account keys); compromise event (immediate); recipient personnel change (within 24h).

**Pre-flight**:
1. Verify all 3 pipeline servers have GPG installed at the same version
2. Verify TPM2 is functional on all 3 servers (`tpm2_getcap properties-fixed`)
3. Verify no pipeline runs in flight (`PipelineExecutionGate` shows no `RUNNING` rows)
4. Backup current envelope: `cp /etc/pipeline/credentials.json.gpg /etc/pipeline/credentials.json.gpg.YYYYMMDD.bak`
5. Approval: security team sign-off + pipeline lead sign-off (logged via change-management ticket)

**Procedure** (per-server, repeated for dev → test → prod):
1. Generate new key pair offline on jump host
2. Re-encrypt envelope using old + new recipients (`gpg2 --encrypt -r <old> -r <new> ...`) — transitional dual-recipient phase
3. Deploy dual-recipient envelope to all 3 servers
4. Verify decrypt works on all 3 (run `credentials_loader.py` in test mode against each)
5. Issue new envelope encrypted to NEW recipient only
6. Deploy new-recipient-only envelope to all 3 servers
7. Run a no-op pipeline cycle on dev to verify
8. After 24-hour confidence window, revoke old recipient and shred old private key

**Validation**:
1. Run `tools/verify_server_parity.py` (§ 4) on all 3 servers — expect envelope SHA-256 to match
2. Query `PipelineEventLog WHERE EventType='CREDENTIALS_LOAD'` for the last 4 cycles — confirm all 3 servers using new key ID
3. Confirm break-glass key still functional via offline test

**Rollback**:
- During dual-recipient phase: revert envelope to `*.bak` file; revoke new recipient
- After single-recipient cutover: requires re-issuing dual-recipient envelope — emergency RB-12.1 sub-procedure

**Related**: RB-6 (vault corruption — adjacent recovery scenario), D6 (vault design), D27 (cross-server parity), D64 (TPM2 passphrase storage).

### § 3.5 Audit trail (per D26 append-only provenance)

Every `credentials_loader.load_credentials()` call writes ONE row to `General.ops.PipelineEventLog` with:

| Field | Value |
|---|---|
| `EventType` | `'CREDENTIALS_LOAD'` |
| `BatchId` | Current `PipelineBatchSequence` value |
| `TableName` | `NULL` (pipeline-wide event) |
| `SourceName` | `NULL` |
| `StartedAt` / `CompletedAt` | Loader entry / exit timestamps |
| `Status` | `'SUCCESS'` / `'FAILED'` |
| `Metadata` (JSON) | `{ "envelope_sha256": "<hash>", "envelope_rotated_at": "<from envelope>", "passphrase_source": "tpm2", "key_id_used": "<long-form fingerprint>" }` |

**Critical exclusions** — these MUST NOT appear in the audit row or any log:
- The passphrase value
- Any plaintext credential value
- The TPM2 PCR values (these are themselves sensitive — they reveal boot config)

**Verification rule**: SqlServerLogHandler's `sensitive_data_filter` (per P5) is configured to redact any string matching `*_PASSWORD=` or RSA private-key headers. Test the filter via a Tier 1 test (Round 5) that intentionally tries to log a fake password and asserts the filter redacted it.

---

## § 4. Cross-server parity baseline JSON (B12 Phase 0 deliverable 0.11)

Per D27, dev / test / prod servers MUST be bit-for-bit identical for code-relevant config. This § specifies the baseline JSON file that encodes the contract, the verification-procedure interface (impl in R4), the drift-severity classification (D65 proposed), and the baseline-maintenance cadence.

### § 4.1 Baseline JSON schema

File: `/etc/pipeline/parity_baseline.json` (mode `0644 root:root` — readable by pipeline, not writable). Format:

```json
{
  "schema_version": "1.0",
  "baseline_name": "pipeline-baseline-v1.0.0",
  "pinned_at": "2026-05-10T00:00:00Z",
  "pinned_by": "pipeline-lead",
  "pipeline_version": "1.0.0",

  "operating_system": {
    "distro": "RHEL",
    "version": "9.4",
    "kernel": "5.14.0-427.13.1.el9_4.x86_64",
    "kernel_match_policy": "major_minor"
  },

  "python": {
    "version": "3.12.11",
    "version_match_policy": "exact",
    "pip_freeze_sha256": "<sha256 of `pip freeze` output, deterministic ordering>",
    "pip_lockfile_path": "/etc/pipeline/python-deps.lock"
  },

  "native_libraries": {
    "oracle_instant_client_version": "19.21.0",
    "oracle_instant_client_dir": "/opt/oracle/instantclient_19_21",
    "odbc_driver_version": "18.3.2.1-1",
    "odbc_driver_name": "ODBC Driver 18 for SQL Server",
    "mssql_tools_version": "18.3.2.1-1",
    "mssql_tools_dir": "/opt/mssql-tools18",
    "gpg_version": "2.3.3-2.el9"
  },

  "env_vars_required": {
    "MALLOC_ARENA_MAX": "2",
    "ORACLE_HOME": "/opt/oracle/instantclient_19_21",
    "LD_LIBRARY_PATH": "/opt/oracle/instantclient_19_21:/opt/mssql-tools18/lib",
    "TZ": "America/Chicago"
  },

  "filesystem_layout": [
    {"path": "/debi/.env", "owner": "pipeline:pipeline", "mode": "0640", "must_exist": true},
    {"path": "/etc/pipeline/", "owner": "pipeline:pipeline", "mode": "0750", "must_exist": true},
    {"path": "/etc/pipeline/credentials.json.gpg", "owner": "pipeline:pipeline", "mode": "0640", "must_exist": true},
    {"path": "/etc/pipeline/parity_baseline.json", "owner": "root:root", "mode": "0644", "must_exist": true},
    {"path": "/var/pipeline/csv/", "owner": "pipeline:pipeline", "mode": "0750", "must_exist": true},
    {"path": "/var/log/pipeline/", "owner": "pipeline:pipeline", "mode": "0750", "must_exist": true},
    {"path": "/mnt/pipeline-archive/parquet/", "owner": "pipeline:pipeline", "mode": "0750", "must_exist": true}
  ],

  "systemd_unit": {
    "path": "/etc/systemd/system/pipeline.service",
    "sha256": "<hash of unit file>",
    "must_have_env_vars": ["MALLOC_ARENA_MAX=2"]
  },

  "tpm2": {
    "required": true,
    "pcr_policy_hash": "<hash from § 3.2 D64 TPM2 sealing setup>",
    "tpm2_tools_version": "5.2-3.el9"
  },

  "credentials_envelope": {
    "path": "/etc/pipeline/credentials.json.gpg",
    "sha256": "<hash from § 3.1 generation step>",
    "schema_version": "1.0",
    "recipient_count": 2,
    "primary_recipient_fingerprint": "<long-form fingerprint of pipeline service key>",
    "breakglass_recipient_fingerprint": "<long-form fingerprint of ops break-glass key>"
  },

  "udm_tables_list_schema": {
    "spec_doc": "docs/migration/phase1/02_configuration.md § 1",
    "expected_columns_sha256": "<hash computed from § 1.1 + § 1.2 column list>",
    "expected_check_constraints": [
      "CK_UdmTablesList_SCD2Mode",
      "CK_UdmTablesList_CDCMode",
      "CK_UdmTablesList_DataClassification"
    ]
  },

  "documented_exceptions": [
    {
      "key": "AUDIT_LOG_LEVEL",
      "dev_value": "DEBUG",
      "test_value": "INFO",
      "prod_value": "INFO",
      "rationale": "Dev allowed verbose logging for development troubleshooting; documented exception per § 2.2",
      "expires_at": "2027-01-01",
      "owner": "pipeline-lead"
    }
  ]
}
```

**Schema notes**:

- `schema_version` is the baseline JSON schema version (currently `"1.0"`); `pipeline_version` is the pipeline release that pinned this baseline. These are DIFFERENT (schema rarely changes; pipeline version bumps per release).
- Hashes (`*_sha256`) are computed at pinning time and compared at verification time. Mismatch is fatal (per § 4.3).
- `documented_exceptions` is the escape hatch for legitimate per-server differences. Every exception has an owner and an expiration; expired exceptions are auto-rejected (force re-review).
- `expected_columns_sha256` ties Round 2's § 1 inventory to the parity contract — drift between docs and production schema is fatal.
- `TZ` (added 2026-05-12 per D109 timezone pin): pins the OS timezone all three servers (dev / test / prod) must report. D109 schedule times (Prod 02:00 AM + 17:00 PM; Test 06:00 AM + 21:00 PM) are stated in LOCAL TIMEZONE; pinning `TZ` ensures dev/test/prod cron + Automic schedules fire at identical wall-clock moments. **Forward-only additive amendment per D92**: existing baselines captured pre-2026-05-12 do not contain `TZ`; `verify_server_parity.py` (R4 § 3.7) treats absent `TZ` as WARN-only for ≤30 days post-amendment, then ERROR. Value `"America/Chicago"` shown above is a PLACEHOLDER pending user confirmation of canonical project timezone post-cascade.

### § 4.2 Verification procedure interface — `tools/verify_server_parity.py` (impl in R4)

Interface only — implementation deferred to Round 4 (per Phase 1 sub-area scope). This freezes the contract.

```python
# tools/verify_server_parity.py — interface signature (Round 4 implementation)

from dataclasses import dataclass
from typing import Literal

Severity = Literal["fatal", "warning", "informational", "match"]

@dataclass
class ParityCheck:
    key: str  # e.g. "python.version", "credentials_envelope.sha256"
    expected: str
    actual: str
    severity: Severity
    exception_match: bool  # True if listed in documented_exceptions and not yet expired
    note: str | None = None

@dataclass
class ParityReport:
    server_name: str
    baseline_name: str
    baseline_pinned_at: str
    checks: list[ParityCheck]
    fatal_count: int
    warning_count: int
    informational_count: int
    match_count: int
    overall: Literal["pass", "warn", "fail"]

def verify_server_parity(
    baseline_path: str = "/etc/pipeline/parity_baseline.json",
    server_name: str | None = None,  # default: read from .env SERVER_NAME
    fail_on_warning: bool = False,
) -> ParityReport:
    """Compare current server state against baseline.

    Runs at every pipeline startup (per D27) — pipeline gates on result.

    Args:
        baseline_path: Path to baseline JSON (default per § 4.1).
        server_name: Server identifier (default: $SERVER_NAME from /debi/.env).
        fail_on_warning: When True, treats warnings as fatal (useful for strict ops mode).

    Returns:
        ParityReport with per-check status. Caller (`main_*.py`) inspects overall:
            - "pass" → continue pipeline run
            - "warn" → continue pipeline run; log WARNING to PipelineEventLog
            - "fail" → sys.exit(1) — pipeline must not proceed

    Side effects:
        - ONE 'PARITY_VERIFY' event written to General.ops.PipelineEventLog with full report as Metadata JSON
        - Detailed per-check log entries to PipelineLog (DEBUG level)
        - On 'fail', alert via configured ops channel (PagerDuty / email / Slack — operator-defined in Phase 0 deliverable 0.10)
    """
```

**Verification surface** (what `verify_server_parity` checks at runtime):

| Check | How |
|---|---|
| `operating_system.distro` + `.version` | `os-release` file |
| `operating_system.kernel` (match policy) | `uname -r` — strict / major_minor / major depending on `kernel_match_policy` |
| `python.version` | `sys.version_info` |
| `python.pip_freeze_sha256` | `sha256sum <(pip freeze \| sort)` |
| `native_libraries.*` | `rpm -q <pkg>` for each |
| `env_vars_required.*` | `os.environ.get(key) == expected` |
| `filesystem_layout.*` | `stat <path>` for owner / mode / existence |
| `systemd_unit.sha256` | `sha256sum /etc/systemd/system/pipeline.service` |
| `tpm2.*` | `tpm2_getcap properties-fixed` + PCR policy hash |
| `credentials_envelope.sha256` | `sha256sum /etc/pipeline/credentials.json.gpg` |
| `udm_tables_list_schema.expected_columns_sha256` | Query `INFORMATION_SCHEMA.COLUMNS` against `General.dbo.UdmTablesList`; sort by name; compute hash |
| `documented_exceptions` | For each exception: confirm value matches per-server expected; confirm `expires_at` > today |

### § 4.3 Drift severity classification (D65 proposed)

`udm-brainstorm` was NOT required for this — the categories follow naturally from the parity surface. Locking via `udm-decision-recorder` with pillar mapping: Operationally stable + Idempotent.

| Severity | Causes | Action | Examples |
|---|---|---|---|
| **🔴 Fatal** | Code execution would produce different results across servers | Pipeline refuses to start (`sys.exit(1)`); ops alert; deploy blocked | Python version mismatch; `MALLOC_ARENA_MAX` missing or wrong; library SHA mismatch; `systemd_unit.sha256` differs; `credentials_envelope.sha256` differs; `mssql-tools` major version mismatch; missing required filesystem path; TPM2 PCR policy hash differs |
| **🟡 Warning** | Code execution likely same, but drift indicates an upcoming risk OR a documented per-server exception is invoked | Pipeline starts but logs WARNING to PipelineEventLog + (optionally) ops channel; review at next quarterly parity check | Kernel patch level diff (point release); transient `sysctl` differences; documented exception invoked (e.g., `AUDIT_LOG_LEVEL` = `DEBUG` on dev) |
| **ℹ️ Informational** | Doesn't affect pipeline behavior; tracked for trend / audit | Logged for trend analysis at quarterly review; no immediate action | Server uptime; load average; recent kernel patch deploy timestamp |
| **✅ Match** | Server state matches baseline exactly | No action | All exact-match checks that pass |

**Rationale for "fatal" surface**: every fatal-tier item, if drifted, COULD produce silent data-correctness divergence between dev and prod. Example: `MALLOC_ARENA_MAX=2` is fatal per W-4 because absence leads to 10× memory bloat from glibc arena fragmentation — same code, same input, but prod OOMs and dev doesn't, masking the bug until production. The pipeline refusing to start is intentionally restrictive: D27 + audit-grade pillar > convenience.

### § 4.4 Baseline maintenance cadence

| Trigger | Cadence | Procedure |
|---|---|---|
| Python version upgrade | Per-upgrade | Re-pin in dev → confirm parity → propagate to test → confirm → propagate to prod → archive old baseline |
| `pip freeze` change (any library bump) | Per-upgrade | Same as above |
| Kernel major version upgrade | Per-upgrade | Same; plus TPM2 re-seal per § 3.2 (kernel measurement in PCR) |
| Native library upgrade (Oracle / ODBC / mssql-tools) | Per-upgrade | Same |
| `systemd_unit` edit | Per-edit | Same; hash updates atomically |
| Credentials envelope rotation | Per RB-12 | Hash updates as part of rotation procedure |
| `UdmTablesList` schema change | Per ALTER | Update `expected_columns_sha256` after ALTER; reverify all 3 servers |
| Documented exception expiry | Per-expiry | Review with owner; either renew (with new `expires_at`) or remove the exception (and fix the drift) |
| Quarterly parity review | Quarterly | Sysadmin + pipeline lead walk through baseline; expired exceptions; baseline integrity; informational trends |

**Owner**: pipeline lead approves; sysadmin executes the actual pin / propagate. Security team signs off on cipher / TPM2 / envelope changes.

**Archival**: prior baselines kept at `/etc/pipeline/parity_baseline.YYYYMMDD.json.bak` (mode `0644 root:root`) for audit trail per D26 append-only spirit. Never delete an archived baseline.

---

## § 5. Automic job definitions (D66 proposed)

This § enumerates every Automic job the pipeline build depends on, the `JOB_<DOMAIN>_<CADENCE>` naming convention, the per-job-type contract with the `PipelineExecutionGate` table (per D29 revised), the failover behavior (per D33 cooperative cancellation), and the cross-doc updates required.

### § 5.1 Job inventory

| Job name | Schedule | Server | Upstream | Downstream | Purpose | Concurrency mechanism |
|---|---|---|---|---|---|---|
| `JOB_PARITY_VERIFY` | Per pipeline start (synchronous prerequisite) | All | None | `JOB_PIPELINE_AM` / `JOB_PIPELINE_PM` | Runs `tools/verify_server_parity.py` (§ 4) — pipeline gates on result | Ephemeral; `PipelineEventLog` only (no gate row, no sp_getapplock — synchronous prerequisite check) |
| `JOB_PIPELINE_AM` | Daily 06:00 (prod schedule) | Prod (primary); Test (hot-standby) | `JOB_PARITY_VERIFY` ✅ | `JOB_PIPELINE_PM` | AM extraction cycle (small + large tables) | `PipelineExecutionGate (CycleType='AM', CycleDate=today)` via Round 1 **SP-3** (prod) / **SP-4** (test) |
| `JOB_PIPELINE_PM` | Daily 18:00 | Prod (primary); Test (hot-standby) | `JOB_PIPELINE_AM` SUCCEEDED + `JOB_PARITY_VERIFY` ✅ | (Tomorrow's `JOB_PIPELINE_AM`) | PM extraction cycle | `PipelineExecutionGate (CycleType='PM', CycleDate=today)` via SP-3 / SP-4 |
| `JOB_GAP_DETECT` | Hourly (every :15) | Prod | None | Operator alert | Per D22 hourly gap detector; queries `PipelineExtraction` for missing dates | Ephemeral; `PipelineEventLog` only |
| `JOB_RECONCILE_WEEKLY` | Weekly Sun 02:00 | Prod | Last completed `JOB_PIPELINE_PM` (Sat) | None | Tier 3 + Tier 4 reconciliation per `cdc/reconciliation/` | `sp_getapplock job_RECONCILE_WEEKLY_<week-start>` + `PipelineEventLog` (per § 5.3.6) |
| `JOB_RETENTION_MONTHLY` | Monthly 1st 02:00 | Prod | All `JOB_PIPELINE_*` for prior month SUCCEEDED | None | 7-year retention enforcement per D30 + RB-11; respects `UdmTablesList.LegalHoldOnly` (§ 1.2.6) | `sp_getapplock job_RETENTION_MONTHLY_<month-start>` + `PipelineEventLog` |
| `JOB_CCPA_PROCESS` | On-demand | Prod | Operator approval | Audit log | CCPA right-to-deletion per RB-10; respects `UdmTablesList.DataClassification='PII'` rows only (§ 1.2.3) | `sp_getapplock job_CCPA_PROCESS_<request-id>` + audit to `CcpaDeletionLog` |
| `JOB_FAILOVER_TEST` | Quarterly (DR drill) | Dev → Test → Prod sequence | Operator manual | Audit log | Per RB-7 DR drill — server failover Q1/Q3, data center loss Q2/Q4 | `sp_getapplock job_FAILOVER_TEST_<drill-date>` + drill log to `PipelineEventLog` |

**Total**: 8 jobs. Phase 0 deliverable 0.10 (Automic schedule) lands these into the operator's Automic instance.

### § 5.2 Naming convention

Pattern: `JOB_<DOMAIN>_<CADENCE>`.

| Component | Allowed values | Example |
|---|---|---|
| `DOMAIN` | `PIPELINE` / `RETENTION` / `RECONCILE` / `PARITY` / `GAP` / `CCPA` / `FAILOVER` | `PIPELINE`, `RETENTION` |
| `CADENCE` | `AM` / `PM` / `DAILY` / `HOURLY` / `WEEKLY` / `MONTHLY` / `QUARTERLY` / `ONDEMAND` / `VERIFY` | `AM`, `MONTHLY` |

**Hard rules**:
- No ad-hoc job names — every job must conform to this pattern (gate-table contract depends on parseability)
- Adding a new DOMAIN requires a D-number (new domain = new operational concept)
- Adding a new CADENCE is operator judgment; document in this § when first used

**Anti-pattern**: `JOB_GENERAL_TASK` (no domain), `JOB_AM_PIPELINE` (cadence-first ordering breaks alphabetical grouping in Automic UI).

### § 5.3 Gate-table integration contract (AM/PM only — per D29 revised + D33)

**Scope correction** (per D56 second-pass on Round 2 — see `_validation_log.md`): `General.ops.PipelineExecutionGate` is scoped to AM/PM cycles per Round 1's CHECK constraint (`CK_PipelineExecutionGate_CycleType IN ('AM','PM')`, `01_database_schema.md` L327). Only `JOB_PIPELINE_AM` and `JOB_PIPELINE_PM` use this contract. Other jobs use § 5.3.6.

**Round 1 canonical column names** (per `01_database_schema.md` L302-347): `GateId`, `CycleType`, `CycleDate`, `ExpectedStartTime`, `ActualStartTime`, `ActualCompletionTime`, `ExecutingServer` (CHECK: `'production'` / `'test'` only), `Status`, `BatchId`, `LastHeartbeatAt`, `FailureReason`, `CancellationRequested`, `CancellationRequestedAt`, `CancellationRequestedBy`, `CancellationReason`, `CancellationAcknowledgedAt`, `CreatedAt`. Round 2 does NOT add new gate columns — the failover + operational requirements are met by existing columns + `PipelineEventLog` for progress / result detail.

#### § 5.3.1 Acquire phase — invoke SP-3 (prod) or SP-4 (test)

Round 1 already authored the atomic gate-acquire procedures with `sp_getapplock` + `MERGE` + status-aware branching (per `01_database_schema.md` L1447-1523 SP-3; SP-4 follows). **Round 2 does NOT re-invent this pattern** — pipeline calls the SPs directly:

```python
# Production server invocation (Round 3 implementation; interface frozen here)
with cursor_for('General') as cur:
    cur.execute("""
        DECLARE @gate_id BIGINT, @batch_id BIGINT;
        EXEC General.ops.PipelineExecutionGate_AcquireProd
            @CycleType = ?,
            @CycleDate = ?,
            @ExpectedStartTime = ?,
            @GateId = @gate_id OUTPUT,
            @BatchId = @batch_id OUTPUT;
        SELECT @gate_id, @batch_id;
    """, cycle_type, cycle_date, expected_start)
    gate_id, batch_id = cur.fetchone()

# Test server invocation — returns action verdict
with cursor_for('General') as cur:
    cur.execute("""
        DECLARE @action NVARCHAR(30), @gate_id BIGINT, @batch_id BIGINT;
        EXEC General.ops.PipelineExecutionGate_AcquireTest
            @CycleType = ?,
            @CycleDate = ?,
            @ExpectedStartTime = ?,
            @GateId = @gate_id OUTPUT,
            @BatchId = @batch_id OUTPUT,
            @Action = @action OUTPUT;
        SELECT @action, @gate_id, @batch_id;
    """, cycle_type, cycle_date, expected_start)
    action, gate_id, batch_id = cur.fetchone()
# action ∈ {'EXIT_SUCCEEDED', 'EXIT_RUNNING_HEALTHY', 'PROCEED_FAILOVER'}
# SP-4 also accepts optional @HeartbeatStaleMinutes (default 10) and
# @ProdMaxRuntimeMinutes (default 120) — omit to use Round 1 defaults.
```

The SPs' `sp_getapplock` + transactional `MERGE` is the atomicity guarantee — no race window between INSERT and UPDATE; the transaction handles all status transitions atomically. **Do NOT inline a custom acquire pattern**; SP-3 / SP-4 are canonical per D34 + I3 mitigation pattern.

#### § 5.3.2 Heartbeat phase

Every 5 minutes during AM/PM execution, the pipeline writes a heartbeat:

```sql
UPDATE General.ops.PipelineExecutionGate
SET LastHeartbeatAt = SYSUTCDATETIME()
WHERE GateId = @GateId AND Status = 'RUNNING';
```

Progress detail (table count, throughput, error count) goes to `General.ops.PipelineEventLog` via the existing event-tracker (per `CLAUDE.md` OBS-5 commit pattern + OBS-7 JSON-merge metadata), NOT to a gate-row column. This decouples high-frequency progress logging from the gate's atomic-concurrency contract.

`LastHeartbeatAt` stale > 15 minutes is the failover trigger per D33 (§ 5.4).

#### § 5.3.3 Cancel-check phase (cooperative cancellation per D33)

Every heartbeat tick (5 min cadence), also read:

```sql
SELECT CancellationRequested, CancellationReason, CancellationRequestedBy
FROM General.ops.PipelineExecutionGate
WHERE GateId = @GateId;
```

If `CancellationRequested = 1`:
1. Finish the current table's atomic operation (don't abandon mid-BCP)
2. Log to `PipelineEventLog` with `EventType='CYCLE_CANCELLED'` and `Metadata = {CancellationReason, CancellationRequestedBy}`
3. Acknowledge: `UPDATE PipelineExecutionGate SET CancellationAcknowledgedAt = SYSUTCDATETIME() WHERE GateId = @GateId`
4. Move to Release phase with `Status = 'CANCELLED'`
5. Exit cleanly (return code 0 — operator-initiated, not failure)

The acknowledgment timestamp (`CancellationAcknowledgedAt`) closes the cooperative-cancel contract: the requester knows the request was received and the cycle ended cleanly.

#### § 5.3.4 Release phase

```sql
UPDATE General.ops.PipelineExecutionGate
SET Status = @final_status,            -- 'SUCCEEDED' / 'FAILED' / 'CANCELLED' / 'TIMEOUT'
    ActualCompletionTime = SYSUTCDATETIME(),
    FailureReason = @failure_message   -- NULL when SUCCEEDED; populated otherwise
WHERE GateId = @GateId AND Status IN ('RUNNING', 'STARTING');
```

Final cycle summary (table count, total rows, total duration, error list) goes to `PipelineEventLog` as a `TABLE_TOTAL`-style event row — NOT a gate-row column. Downstream Automic jobs read `Status='SUCCEEDED'` from the gate row to proceed (per § 5.1 Upstream column).

#### § 5.3.5 Per-AM/PM-cycle column matrix (gate-table semantics)

Only `JOB_PIPELINE_AM` and `JOB_PIPELINE_PM` interact with `PipelineExecutionGate`:

| Phase | Reads (gate columns) | Writes (gate columns) | Progress / result detail |
|---|---|---|---|
| Acquire | (via SP-3 / SP-4) | Set by SP-3/SP-4: `Status`, `ActualStartTime`, `ExecutingServer`, `BatchId`, `LastHeartbeatAt` | n/a |
| Heartbeat | None | `LastHeartbeatAt` | `PipelineEventLog` per-table phase rows |
| Cancel-check | `CancellationRequested`, `CancellationReason`, `CancellationRequestedBy` | `CancellationAcknowledgedAt` (on ack only) | `PipelineEventLog` event `'CYCLE_CANCELLED'` |
| Release | None | `Status`, `ActualCompletionTime`, `FailureReason` | `PipelineEventLog` `TABLE_TOTAL`-style summary |

**`ExecutingServer` value rule**: SP-3 sets to `'production'`; SP-4 sets to `'test'`. NEVER write hostnames (e.g. `$SERVER_NAME = 'pipeline-prod-01'` from `.env`) to this column — `CK_PipelineExecutionGate_ExecutingServer` rejects them. Hostnames are logged separately to `PipelineEventLog` for forensic detail.

#### § 5.3.6 Non-AM/PM jobs — concurrency without the gate table

`JOB_RECONCILE_WEEKLY`, `JOB_RETENTION_MONTHLY`, `JOB_CCPA_PROCESS`, `JOB_FAILOVER_TEST` do NOT use `PipelineExecutionGate` because Round 1's `CK_PipelineExecutionGate_CycleType IN ('AM','PM')` scopes the table. Expanding the CHECK would require editing Round 1 schema, which violates D34 greenfield posture (Round 1 schema is canonical CREATE TABLE).

Instead, non-AM/PM jobs use:

| Concern | Mechanism |
|---|---|
| Prevent concurrent runs of same job on same date | `sp_getapplock @Resource = N'job_<JOB_NAME>_<cycle_date>', @LockMode = 'Exclusive', @LockOwner = 'Session', @LockTimeout = 5000` (per W-8 — same idiom as `orchestration/table_lock.py`) |
| Job start / running / done lifecycle | `PipelineEventLog` rows; `EventType = '<JOB_NAME>'`; Status transitions `IN_PROGRESS → SUCCESS/FAILED` (per `CK_PipelineEventLog_Status` from Round 1 L143-144) |
| Idempotency (don't re-run within same BatchId) | `IdempotencyLedger` row (D17): `(BatchId, SourceName='__pipeline__', TableName='__job__', EventType='<JOB_NAME>')` UNIQUE prevents re-run |
| Operator cancellation | Operator flips an `IdempotencyLedger.Status` field OR drops a signal file in `$CSV_OUTPUT_DIR/cancel/<job_name>`; checked at long-running-job heartbeat |
| Progress detail | `PipelineEventLog.Metadata` JSON on the in-flight row; updated via OBS-7 JSON-merge pattern |
| Final result summary | `PipelineEventLog.Metadata` on the final SUCCESS/FAILED row (terminal Status per Round 1 enum) |

**Trade-off accepted**: non-AM/PM jobs don't get the hot-standby pattern (which is by design — these jobs only run on prod). The simpler concurrency mechanism (sp_getapplock + ledger + event log) covers their actual needs without expanding the AM/PM-scoped gate table.

#### § 5.3.7 Operator visibility for non-gate jobs

Operators querying "is this job currently running?" use:

```sql
-- Job currently running?
SELECT TOP 1 EventType, StartedAt, Status, EventDetail, Metadata
FROM General.ops.PipelineEventLog
WHERE EventType = 'JOB_RECONCILE_WEEKLY'
ORDER BY StartedAt DESC;
```

Power BI dashboard (D31) pivots `PipelineEventLog WHERE EventType LIKE 'JOB_%'` for a single-pane operational view alongside AM/PM gate-table state.

### § 5.4 Failover behavior (AM/PM only — per D29 revised + D33)

The hot-standby pattern applies ONLY to AM/PM cycles. Non-AM/PM jobs (§ 5.3.6) don't have hot-standby — they run on prod or not at all (operator-restartable). For AM/PM:

1. **Steady state**: Prod runs `JOB_PIPELINE_AM` / `PM`. Test is hot-standby — scheduled at the same time, but on `Acquire` (via SP-4) gets verdict `EXIT_RUNNING_HEALTHY` because prod's row shows `Status='RUNNING'` and `LastHeartbeatAt` < 15 min stale.
2. **Prod stalls**: Test's next heartbeat-cycle check finds prod's `LastHeartbeatAt` > 15 min stale.
3. **Test initiates failover**: Test writes `CancellationRequested = 1` on prod's gate row + `CancellationReason = 'Stale heartbeat from <test_server_name>'`.
4. **Cooperative cancellation window**: Test waits 15 min for prod's cooperative shutdown (per D33 — prod should ack via Status='CANCELLED').
5. **If prod acks**: test acquires the gate row (re-INSERT after prod's CANCELLED row, or update — Round 1 schema design choice; default: re-INSERT with same `(CycleType, CycleDate)` since CANCELLED is terminal).
6. **If prod does NOT ack within 15 min** (genuine zombie): test triggers RB-9 (operator-driven failover). RB-9 includes: ops verifies prod-server reachability (network); ops manually marks prod's gate row as `Status='FAILED'` with reason; test re-acquires.

**Why the 15-minute cooperative window**: D33's rationale — prod might be in a slow BCP that finishes in 5 more minutes. Aborting prematurely loses the partial work. The window also protects against false-positive heartbeat-stale events (transient network).

**Why NOT auto-failover without operator on RB-9**: aged historical incident — auto-failover on transient network flap led to split-brain where both servers wrote to UDM_Stage. RB-9 requires human-in-loop confirmation before forcing the gate.

### § 5.5 Cross-doc updates required

At Round 2 close-out, the following docs need pointer-updates:

| Doc | Update |
|---|---|
| `docs/migration/05_RUNBOOKS.md` RB-9 | Add cross-link to this § 5 for the job inventory + failover sequence; ensure RB-9 procedure matches § 5.4 |
| `docs/migration/phase1/01_database_schema.md` (`PipelineExecutionGate` section) | Add cross-link to § 5.3 for the column-by-column lifecycle contract |
| `docs/migration/02_PHASES.md` Phase 0 deliverable 0.10 (Automic schedule) | Cross-link to § 5.1 inventory as the source of truth |
| `docs/migration/02_PHASES.md` Phase 4 (production rollout) | Per-cohort enablement uses `UdmTablesList.CohortAssignment` (§ 1.2.4); cross-link |
| `docs/migration/04_EDGE_CASES.md` F-series | Where F-cases describe failover, cite § 5.4 |

---

## § 6. Edge case mapping (Gate 3 input)

Round 2 is a CONFIGURATION round — most pipeline-correctness edge cases (M, S, I-most, V) are addressed at the code layer (Rounds 3-4) and are merely REFERENCED here via `UdmTablesList` columns + `.env` keys + parity baseline hashes. This § marks which cases Round 2 directly addresses, which it enables for downstream rounds, and which are explicitly out of scope.

### § 6.1 M / S / I / N / P / G / D / F / V series walk

| Series | Round 2 status | Specifics |
|---|---|---|
| **M** (math / lookback / lateness) | ⚪ Referenced | `LookbackDays` (§ 1.1.1 col 9) inventoried; D11 empirical L_99 referenced in foundational-decisions table. Lateness math itself lives in `cdc/extraction_state.py` (Round 3); Round 2 doesn't change behavior |
| **S** (SCD2 reliability) | ⚪ Referenced | SCD2 enhancement block (§ 1.1.4 — 12 columns) inventoried; runtime semantics in `scd2/engine.py` are unchanged. New columns from § 1.2 don't touch SCD2 invariants |
| **I** (idempotency) | ✅ Addressed (partial) | I3 race-condition class: § 5.3.1 gate-table acquire uses the SAME try-INSERT + catch-on-UNIQUE idiom as SP-1 (vault). § 1.3 ALTER DDL is idempotent via `IF NOT EXISTS` guard (D34). Other I-cases addressed in pipeline logic — Round 3 scope |
| **N** (network drive / Parquet) | ✅ Addressed (parity surface) | `PARQUET_OUTPUT_DIR` parity-required (§ 2.1.4 + § 4.1 `filesystem_layout`); offsite replication target in B11 (deferred — Phase 0). Network drive availability monitoring is operations responsibility |
| **P** (PII / encryption) | ✅ Addressed (config layer) | P1 deterministic encryption enabled by `PiiColumnList` (§ 1.2.2) + D6 vault; P5 no-plaintext-PII enforced by `sensitive_data_filter` reading `.env` allow-list (§ 3.5); P8 vault audit log per D26 schema; P9 cross-source isolation via per-source service accounts in `.env` (§ 2.1.1) |
| **G** (gap detection / outage recovery) | ✅ Addressed (orchestration layer) | `JOB_GAP_DETECT` hourly per D22 (§ 5.1) reads `PipelineExtraction`; alerts on gap. Recovery procedures in Round 4 tools (`tools/detect_extraction_gaps.py`) |
| **D** (2x/day cadence) | ✅ Addressed (orchestration layer) | `JOB_PIPELINE_AM` / `JOB_PIPELINE_PM` (§ 5.1); gate contract § 5.3 enforces atomicity via `(CycleType, CycleDate)` UNIQUE |
| **F** (failover / cross-server parity) | ✅ Addressed (full coverage) | Failover sequence § 5.4 per D29 revised + D33 cancellation; parity baseline § 4 per D27. § 5.4's 15-minute cooperative-cancel window is the central F-series guarantee |
| **V** (vault provenance) | ✅ Addressed (config layer) | Vault DB credentials in `.env` (§ 2.1.3); GPG decryption audit trail (§ 3.5) writes one `CREDENTIALS_LOAD` event per process. Runtime `PiiVault_GetOrCreateToken` (SP-1) + `PiiVaultAccessLog` are Round 1 |

### § 6.2 New edge cases surfaced by Round 2

Round 2 SURFACES three new candidate edge cases. Each is proposed for `04_EDGE_CASES.md` F-series entry (cross-doc update at Round 2 close-out — tracked as B40):

| Proposed | Description | Mitigation in Round 2 |
|---|---|---|
| F (next) | GPG passphrase loss on a pipeline server (TPM2 hardware fault) blocks pipeline startup — pipeline cannot decrypt envelope | RB-12 break-glass key (§ 3.4); secondary `ops-breakglass` recipient on envelope (§ 3.1); failover to operational server with working TPM2 per § 5.4 |
| F (next+1) | Documented parity exception expires without renewal — parity check fatal-flags drift, pipeline refuses to start on `expires_at` rollover | § 4.4 quarterly maintenance cadence; 30-day pre-expiry notification mechanism (B38 — operational follow-up) |
| F (next+2) | Pipeline starts on a server with `MALLOC_ARENA_MAX` unset (per W-4 Do-NOT) — would cause 10× memory bloat from glibc arena fragmentation | § 4.3 FATAL severity — `JOB_PARITY_VERIFY` catches via `env_vars_required` check before any data extracted; pipeline `sys.exit(1)` |

Close-out task (B40): append three F-series rows to `docs/migration/04_EDGE_CASES.md` with next available IDs. Operator computes via `grep "^### F" 04_EDGE_CASES.md | tail -3` at close-out time.

---

## § 7. Validation gates (Round 2 producer self-check)

Per D55 + D62, this § is the producer self-check BEFORE invoking `udm-checks-and-balances` skill's Gate 2 (independent review by `udm-design-reviewer` per D56 independence). **Self-check is NOT validation — D55 hard rule.** This § lists what the producer (me) has verified, and what the independent reviewer needs to confirm or invalidate.

### § 7.1 Gate 1 self-check — Cross-reference

For each D-number cited in this doc:

| D# | Citation locations in this doc | Self-check |
|---|---|---|
| D2 | § 1.2.1 driver | ✅ Stage dropped per Parquet snapshots — consistent with `03_DECISIONS.md` D2 🟢 |
| D6 | § 1.2.2, § 2.1.3, foundational decisions | ✅ In-house vault — consistent with D6 🟢 |
| D11 | § 1.1.1 (LookbackDays) | ✅ Empirical L_99 — consistent |
| D17 | Foundational decisions | ✅ Idempotency ledger — consistent |
| D22 | § 5.1 (JOB_GAP_DETECT) | ✅ Hourly gap detector — consistent |
| D26 | § 3.5 audit trail | ✅ Append-only provenance — consistent |
| D27 | Foundational decisions, § 2.2, § 4 | ✅ Cross-server parity — § 4 is the operationalization |
| D29 revised | § 5 throughout | ✅ Automic gate-table — consistent |
| D30 | § 1.2.3, § 1.2.6, § 5.1 (JOB_RETENTION_MONTHLY) | ✅ Retention + legal hold — consistent |
| D33 | § 5.3.3, § 5.4 | ✅ Cooperative cancellation — consistent |
| D34 | § 1.3, § "Common patterns" | ✅ Greenfield (`IF NOT EXISTS` guards) — consistent |
| D45.1 | § 2.1.3 (vault in `General.ops`) | ✅ Schema-creation — consistent |
| D62 | § "Read order for this round" | ✅ CCL doctrine — this doc obeys |
| D63 – D66 (proposed) | § 1.2, § 3.2, § 4.3, § 5 | ✅ Each has "Pillar(s) served" per D61 |

For B-numbers:

| B# | Citation | Status |
|---|---|---|
| B11 | § 6.1 (offsite Parquet) | ✅ Active in BACKLOG.md (deferred) |
| B12 | This doc § 4 (parity baseline) | ✅ This doc IS the design freeze; Phase 0 implements |
| B13 | This doc § 3 (GPG strategy) | ✅ This doc IS the design freeze; Phase 0 implements |

For `CLAUDE.md` gotcha references (E-3, B-2, B-8, P0-1, P1-13, SS-1, SCD2-P1-d, SCD2-R2-a, SCD2-R2-b, SCD2-R8, SCD2-R10.2, LT-2, V-7, W-1, W-4): all resolve to `CLAUDE.md` § "Gotchas" / "Architecture Decisions" — verified via Grep.

Cross-doc updates listed in § 1.5 + § 5.5 are NOT YET APPLIED — those are close-out tasks per the Round 2 acceptance criteria checklist (§ 7.5).

**Status**: 🟡 Producer self-check done; **Gate 2 first-pass 2026-05-10 caught 3 🔴** (gate-table column drift; CycleType CHECK violation; § 5.3.1 bypassed SP-3) — fixes applied. **Mandatory D56 second-pass 2026-05-10 caught 2 NEW 🔴 introduced by the fixes** (third occurrence of fix-introduces-same-bug-class):
- 🔴 4 — § 5.3.1 SP-4 example used `@Verdict` but actual SP-4 parameter is `@Action` (`01_database_schema.md` L1544). **Fixed**: renamed `@Verdict`/`verdict` → `@Action`/`action` throughout the SP-4 Python example.
- 🔴 5 — § 5.3.6 rows referenced `PipelineEventLog` Status values (`STARTED`, `RUNNING`, `SUCCEEDED`) that violate `CK_PipelineEventLog_Status IN ('IN_PROGRESS','SUCCESS','FAILED','SKIPPED')` (L143-144). **Fixed**: row 2 now reads `IN_PROGRESS → SUCCESS/FAILED`; row 6 final row reads `SUCCESS/FAILED`.

Mandatory third-pass per D56 pending. See `_validation_log.md` 2026-05-10 Round 2 entries (first-pass + second-pass).

**Lesson** (candidate Pitfall #9 at close-out, strengthened by second-pass finding): producer Gate 1 self-check AND fix-cycle validation must include "every embedded SQL column / parameter / enum reference resolves against the canonical DDL in dependent docs". The discipline applies equally to original drafts AND to fixes that introduce new references. Three consecutive rounds have hit this pattern (D49 v2→v3 SP-1+UX; Round 2 first-pass column drift; Round 2 second-pass parameter+enum drift) — proves the pattern is a real failure mode worth its own Pitfall entry.

### § 7.2 Gate 5 self-check — Risk delta + Backlog surfacing (per D61)

**Per D62 Pitfall #8** (added to HANDOFF.md L174 during D62 round close-out): every risk-delta line in this § MUST be verified against `RISKS.md` BEFORE Round 2 locks. If R08 / R10 / R03 / R18 claims here don't match `RISKS.md` state, that's a 🔴 cross-reference gap.

**Risks introduced / addressed**:

```
RISKS (per D61):
- 🆕 NEW: R18 — Documented parity exceptions accumulate without expiration enforcement.
       Likelihood Low × Impact Medium = 2 ⚪ Document.
       Mitigation: § 4.4 quarterly review; B38 (30-day pre-expiry notification mechanism).
       Status: NOT YET ADDED to RISKS.md — close-out task per Pitfall #8 from D62 round.

- ⬇️ DE-ESCALATED (pending RISKS.md update): R08 — Cross-server parity drift across dev/test/prod.
       § 4 parity baseline JSON + verification procedure addresses directly.
       Currently L=Medium × I=Medium = 4 🟡 in RISKS.md.
       Proposed reduction: L=Low × I=Medium = 2 ⚪ — after Phase 0 deliv 0.11 lands and verifier runs in dev.
       (Don't reduce now; the design is documented but not yet operational — same caution as R12/D61.)

- ⬇️ DE-ESCALATED (pending): R10 — Production server hardware failure.
       § 5.4 failover sequence + § 4 parity baseline reduce mean-time-to-recovery.
       Currently L=Low × I=High = 3 🟡.
       Proposed reduction: L=Low × I=Medium = 2 ⚪ after RB-9 + § 5.4 procedures rehearsed in DR drill (B-21-adjacent).
       (Don't reduce now — same caution.)

- ⬇️ DE-ESCALATED (pending): R03 — Single-engineer Python expertise (bus factor).
       Formal § 1 + § 2 + § 3 + § 4 + § 5 specs reduce tribal-knowledge dependency.
       Currently L=Medium × I=High = 6 🟡.
       Proposed reduction: L=Medium × I=Medium = 4 🟡 after a second engineer onboards using this doc as primary reference.
       (Don't reduce now — needs evidence of successful onboarding.)
```

Per Pitfall #8: I'm explicitly NOT reducing R08 / R10 / R03 scores in `RISKS.md` during this round — only DOCUMENTING the proposed reductions here and at close-out. The actual register updates happen after the corresponding evidence lands (parity verifier running in dev; DR drill rehearsing failover; second engineer onboarded). This avoids the R12/D61 + R16/D62 pattern of declaring mitigation without substantiation.

**Backlog proposals** (per D61 — current max in BACKLOG.md after D62 close-out is **B37**; NEXT_AVAILABLE = **B38**):

```
BACKLOG (per D61):
- 🟡 B38: Author 30-day pre-expiry notification mechanism for parity-baseline documented_exceptions
       (cron job + email/Slack; cites R18); COD 2, JS 1, WSJF=2.0
- 🟡 B39: Phase 0 deliverable 0.6 — capture first month of Snowflake trial cost data;
       informs SNOWFLAKE_WAREHOUSE sizing in § 2.1.8; COD 4, JS 2, WSJF=2.0
- 🟡 B40: Append F-(next) / F-(next+1) / F-(next+2) edge cases to 04_EDGE_CASES.md F-series
       (per § 6.2); COD 2, JS 1, WSJF=2.0
- 🟡 B41: After D64 locks, author RB-12 in full per udm-runbook-author skill
       (§ 3.4 is only an outline); COD 3, JS 2, WSJF=1.5
- 🟡 B42: After D63 locks, ensure CK_UdmTablesList_SCD2Mode exists via § 1.4 reconciliation query
       — run against prod; COD 3, JS 1, WSJF=3.0
- 🟡 B43: Add R18 to RISKS.md (close-out task per Pitfall #8); COD 4, JS 1, WSJF=4.0
```

### § 7.3 Gate 2 — Independent review (NEXT STEP at Round 2 close-out)

Invocation pattern (per `udm-design-reviewer` agent definition + D62 CCL):

> Per `docs/migration/MULTI_AGENT_GUIDE.md` § Canonical Context Load (D62), perform the CCL before reviewing. Your first content-substantive `Read` MUST be on a Stage 1 doc. Review `docs/migration/phase1/02_configuration.md` for: (1) Gate 1 cross-reference correctness — every D-number cited resolves; every B-number cited matches `BACKLOG.md` state; pillar names byte-identical to NORTH_STAR canonical forms; (2) Gate 2 design soundness — D64 brainstorm completeness, TPM2 vs alternatives; (3) Gate 3 edge case coverage — series walk in § 6 complete; (4) Gate 4 verification — § 1.4 CHECK constraints + § 4 parity rules + § 5.3 gate contracts are tangible; (5) Gate 5 idempotency / regression / risk delta — D55 / D56 / D60 / D61 / D62 invariants preserved; risk-delta claims in § 7.2 match `RISKS.md` state per Pitfall #8; (6) backlog proposals (B38-B43) WSJF math correct.

Expected output: 5-gate validation report with overall verdict; **mandatory second-pass per D56 if 🔴**.

### § 7.4 Gate 3 + Gate 4 — Edge case enumeration + validation

Walked in § 6. § 6.1 shows series-by-series coverage; § 6.2 surfaces 3 new candidates (B40 to append at close-out). Each ✅ in § 6.1 has tangible verification:

| Edge case | Verification mechanism |
|---|---|
| I3 (concurrent same-key) at gate-acquire | § 5.3.1 try-INSERT + catch-on-UNIQUE on `PipelineExecutionGate (CycleType, CycleDate)` |
| N1 (Parquet path parity) | § 4.1 `filesystem_layout` rule; `verify_server_parity` (R4) checks at startup |
| P1, P5, P8, P9 (vault config) | § 2.1.3 vault DB creds; § 3.5 audit trail; § 2.1.1 per-source service accounts |
| G (gap detection) | § 5.1 JOB_GAP_DETECT hourly schedule |
| D (cadence) | § 5.1 JOB_PIPELINE_AM/PM schedule; § 5.3 gate atomicity |
| F (failover, parity, MALLOC_ARENA_MAX missing) | § 4.3 FATAL severity stops pipeline; § 5.4 failover procedure |

Per Gate 4: full unit/integration tests for these (Tier 1 `sensitive_data_filter` redaction test; Tier 2 idempotent `verify_server_parity` property test; etc.) are **Round 5 scope** per the phase plan. Test deferral is acceptable per Round 2 scope, tracked as a follow-up implicit in the Round 5 plan.

### § 7.5 Round 2 acceptance criteria checklist (will run at close-out)

- [ ] § 1 – § 7 all present and self-consistent
- [ ] D63 – D66 captured in `03_DECISIONS.md` via `udm-decision-recorder` (each cites canonical NORTH_STAR pillar names + cross-doc updates listed)
- [ ] `udm-design-reviewer` independent first-pass returned no 🔴 (mandatory second-pass per D56 if 🔴)
- [ ] `_validation_log.md` entry appended documenting both passes
- [ ] Cross-doc updates landed (§ 1.5 UdmTablesList pointers + § 5.5 Automic pointers + § 6.2 F-series edge cases per B40)
- [ ] `BACKLOG.md` updated with B38 – B43 (or however many emerge from review)
- [ ] `RISKS.md` updated with R18 added (per B43); R08 / R10 / R03 score changes ONLY if substantiating evidence has landed (per Pitfall #8)
- [ ] `HANDOFF.md` §3 + §12 + §14 updated via `udm-round-closeout`
- [ ] `CURRENT_STATE.md` "Recently completed" + "Recent rounds" + "Last updated" updated
- [ ] `NORTH_STAR.md` per-phase contribution table: confirm Phase 1 row already shows Operationally stable + Audit-grade pillars (no change expected — Round 2 advances them as expected)
- [ ] Doc status flip: `phase1/02_configuration.md` "🟡 Drafting" → "🟢 Locked"

---

## End of Round 2 — Configuration

**Status when this checklist completes**: 🟢 Locked, ready for Round 3 (Core Modules) to consume (a) `UdmTablesList` canonical column inventory + DDL (§ 1) when implementing column-aware loaders; (b) `.env` key set (§ 2) when implementing `data_load/credentials_loader.py` and other config consumers; (c) GPG envelope spec (§ 3) when implementing the loader's decrypt path; (d) parity baseline JSON (§ 4) when implementing `tools/verify_server_parity.py`; (e) Automic gate-table contract (§ 5) when implementing `orchestration/table_lock.py` and `pipeline_steps.py` cancellation hooks.
