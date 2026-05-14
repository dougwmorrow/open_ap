# Phase 1, Round 1 — Database Schema

**Status**: 🟡 Draft for DBA + pipeline-team review

This document is the complete database schema spec for the UDM pipeline. All tables, indexes, and stored procedures live in the `General.ops` schema within the existing `General` database.

## Scope

- **23 tables** in `General.ops`
- **1 sequence object** (`PipelineBatchSequence`)
- **10 stored procedures** for vault, gate, ledger, retention operations
- **Edge case → DDL feature mapping** (which DDL constructs address which edge cases)
- **DBA review checklist**
- **7-year storage forecast** per table

## Foundational decisions (D45 sub-decisions)

| # | Decision | Rationale |
|---|---|---|
| D45.1 | `General.ops` is a new schema in the existing `General` database | Cleanly separates operational metadata from `dbo` (existing UdmTablesList etc.) |
| D45.2 | BIGINT IDENTITY for high-volume PKs; rowstore for targeted-update tables; partitioned columnstore for append-only high-volume | Storage efficiency + query performance |
| D45.3 | Single sequence `PipelineBatchSequence` for all BatchIds | Cross-table joins work; no race conditions |
| D45.4 | DATETIME2(3) for all datetimes | BCP CSV contract; SCD2-P1-f invariant |
| D45.5 | VARCHAR(64) for hashes | Full SHA-256 hex; B-1 |
| D45.6 | DELETE permission denied on audit tables. **v2 clarification**: PiiVault is the most-protected table; rows are NEVER physically DELETEd. Retention / CCPA deletion / legal hold flip the Status column instead. Audit tables (PiiTokenProvenance, PiiTokenizationBatch, PiiVaultAccessLog, CcpaDeletionLog, OrphanedTokenLog, ManualCorrectionLog, DeleteEvaluationAudit, ExtractionGapLog, ReconciliationLog, SCD2RepairLog, TableEnablementLog, SchemaContract) have DELETE denied at role level. | Append-only forever; PiiVault uses Status flip pattern |
| D45.7 | TDE enabled on `General` database | Deployment requirement, not in CREATE TABLE |
| D45.8 | SCHEMABINDING on stored procedures | Prevents schema drift from breaking procs |

## Naming conventions

- Tables: `PascalCase` (e.g. `PipelineEventLog`)
- Columns: `PascalCase` (e.g. `BatchId`, `EventType`)
- Indexes: `IX_<TableName>_<purpose>` (nonclustered), `UX_<TableName>_<purpose>` (unique), `CCI_<TableName>` (clustered columnstore)
- Constraints: `FK_<ChildTable>_<ParentTable>`, `CK_<TableName>_<purpose>`
- Stored procedures: `<Subject>_<Verb>` (e.g. `PiiVault_GetOrCreateToken`)
- Sequences: `<Purpose>Sequence` (e.g. `PipelineBatchSequence`)
- Schemas: lowercase `ops` for operational metadata

## Common patterns

### Append-only audit tables

Used for: `PiiVaultAccessLog`, `CcpaDeletionLog`, `ManualCorrectionLog`, `PiiTokenProvenance`, `PiiTokenizationBatch`, `DeleteEvaluationAudit`, `ExtractionGapLog`, `ReconciliationLog`, `SCD2RepairLog`, `TableEnablementLog`.

Each has:
- `<Entity>Id BIGINT IDENTITY PRIMARY KEY`
- `CreatedAt DATETIME2(3) NOT NULL DEFAULT SYSUTCDATETIME()`
- DELETE permission denied at the role level (deployment step)
- No UPDATE permission for rows beyond status fields where applicable

### Idempotency keys

Tables that receive INSERT-or-no-op patterns have a UNIQUE constraint on the natural idempotency key:

| Table | Idempotency key |
|---|---|
| `IdempotencyLedger` | `(BatchId, SourceName, TableName, EventType)` |
| `ParquetSnapshotRegistry` | `(SourceName, TableName, BatchId, BusinessDate)` |
| `PipelineExecutionGate` | `(CycleType, CycleDate)` |
| `PiiVault` (lookup) | `(PiiType, SourceName, PlaintextHash)` |
| `PiiTokenProvenance` | `(Token, SourceName, ObjectName, ColumnName, FilePath)` |
| `PipelineExtraction` | `(SourceName, TableName, DateValue, ExtractionAttempt)` |

A re-INSERT against the same key fails with constraint violation, which the calling code interprets as "no-op, already done."

### Status enums

Stored as `NVARCHAR(20)` with CHECK constraints for documentation:

| Table | Status values |
|---|---|
| `PipelineEventLog` | `IN_PROGRESS`, `SUCCESS`, `FAILED`, `SKIPPED` |
| `PipelineExtraction` | `SUCCESS`, `FAILED`, `IN_PROGRESS` |
| `PipelineExecutionGate` | `PENDING`, `STARTING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `TIMEOUT`, `CANCELLED` |
| `IdempotencyLedger` | `IN_PROGRESS`, `COMPLETED`, `FAILED` |
| `ParquetSnapshotRegistry` | `created`, `verified`, `replicated`, `archived`, `missing`, `purged`, `replication_failed` |
| `PiiVault` | `active`, `deleted_per_request`, `purged_for_retention`, `legal_hold_only` |

---

# Table specifications

Tables ordered by dependency (foundational first, dependent later).

## 0. Sequence: `PipelineBatchSequence`

**Purpose**: source of truth for `BatchId` values. Single sequence ensures monotonic ordering across all tables.

**Decisions**: D45.3.

```sql
CREATE SEQUENCE General.ops.PipelineBatchSequence
    AS BIGINT
    START WITH 1
    INCREMENT BY 1
    MINVALUE 1
    NO MAXVALUE
    NO CYCLE
    CACHE 100;  -- batched allocation reduces row locking
```

**Storage**: trivial. Sequence metadata only.

---

## 1. `PipelineEventLog`

**Purpose**: per-step event tracking. One row per pipeline step (extract, parquet write, scd2 promote, etc.). The "dashboard" layer of observability.

**Decisions addressed**: D17, D29 (cycle/server fields), D31 (Power BI source), D33.

**Edge cases addressed**: I1, I2, I3, I7, F4, F11, F18.

```sql
CREATE TABLE General.ops.PipelineEventLog (
    EventLogId        BIGINT IDENTITY(1,1) NOT NULL,
    BatchId           BIGINT          NOT NULL,
    TableName         NVARCHAR(255)   NULL,        -- NULL for pipeline-wide events
    SourceName        NVARCHAR(50)    NULL,        -- NULL for pipeline-wide events
    EventType         NVARCHAR(50)    NOT NULL,
    EventDetail       NVARCHAR(MAX)   NULL,
    StartedAt         DATETIME2(3)    NOT NULL,
    CompletedAt       DATETIME2(3)    NULL,
    DurationMs        BIGINT          NULL,
    Status            NVARCHAR(20)    NOT NULL DEFAULT 'IN_PROGRESS',
    ErrorMessage      NVARCHAR(MAX)   NULL,
    RowsProcessed     BIGINT          NULL,
    RowsInserted      BIGINT          NULL,
    RowsUpdated       BIGINT          NULL,
    RowsDeleted       BIGINT          NULL,
    RowsUnchanged     BIGINT          NULL,
    RowsBefore        BIGINT          NULL,
    RowsAfter         BIGINT          NULL,
    TableCreated      BIT             NOT NULL DEFAULT 0,
    Metadata          NVARCHAR(MAX)   NULL,        -- JSON
    RowsPerSecond     DECIMAL(18,2)   NULL,
    CycleType         NVARCHAR(10)    NULL,        -- 'AM' or 'PM'
    CycleDate         DATE            NULL,
    ServerRole        NVARCHAR(20)    NULL,        -- 'production' or 'test'
    CreatedAt         DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    
    CONSTRAINT PK_PipelineEventLog PRIMARY KEY CLUSTERED (EventLogId),
    CONSTRAINT CK_PipelineEventLog_Status CHECK (Status IN 
        ('IN_PROGRESS', 'SUCCESS', 'FAILED', 'SKIPPED')),
    CONSTRAINT CK_PipelineEventLog_CycleType CHECK 
        (CycleType IS NULL OR CycleType IN ('AM', 'PM')),
    CONSTRAINT CK_PipelineEventLog_ServerRole CHECK 
        (ServerRole IS NULL OR ServerRole IN ('production', 'test', 'dev'))
);

CREATE INDEX IX_PipelineEventLog_BatchId 
    ON General.ops.PipelineEventLog (BatchId)
    INCLUDE (EventType, Status, StartedAt);

CREATE INDEX IX_PipelineEventLog_TableEvent 
    ON General.ops.PipelineEventLog (SourceName, TableName, EventType, StartedAt DESC)
    INCLUDE (Status, DurationMs);

CREATE INDEX IX_PipelineEventLog_Failures 
    ON General.ops.PipelineEventLog (Status, StartedAt DESC)
    WHERE Status IN ('FAILED', 'SKIPPED');

CREATE INDEX IX_PipelineEventLog_Cycle 
    ON General.ops.PipelineEventLog (CycleType, CycleDate, ServerRole);
```

**Storage forecast**: ~50M rows × ~500 bytes = **~25 GB over 7 years**. Rowstore (PAGE compression).

---

## 2. `PipelineLog`

**Purpose**: detailed narrative logging. Many rows per step. Diagnostic trail joined to `PipelineEventLog` via `BatchId`.

**Decisions addressed**: D31 (Power BI source).

**Edge cases addressed**: P5 (sensitive data filter at source).

**High-volume design notes**:
- Estimated 5B rows over 7 years before retention purge
- Monthly partitioning by `CreatedAt` for efficient retention DELETE
- Partitioned clustered columnstore for compression (5-10× ratio)

```sql
-- Partition function: monthly windows from 2026 to 2040
CREATE PARTITION FUNCTION pf_PipelineLog_Monthly (DATETIME2(3))
AS RANGE RIGHT FOR VALUES (
    '2026-01-01', '2026-02-01', '2026-03-01', '2026-04-01', '2026-05-01', '2026-06-01',
    '2026-07-01', '2026-08-01', '2026-09-01', '2026-10-01', '2026-11-01', '2026-12-01'
    -- (extended via maintenance tool to roll forward each year)
);

CREATE PARTITION SCHEME ps_PipelineLog_Monthly 
AS PARTITION pf_PipelineLog_Monthly 
ALL TO ([PRIMARY]);

CREATE TABLE General.ops.PipelineLog (
    LogId             BIGINT IDENTITY(1,1) NOT NULL,
    BatchId           BIGINT          NOT NULL,
    TableName         NVARCHAR(255)   NULL,
    SourceName        NVARCHAR(50)    NULL,
    LogLevel          NVARCHAR(10)    NOT NULL,
    Module            NVARCHAR(255)   NOT NULL,
    FunctionName      NVARCHAR(255)   NULL,
    Message           NVARCHAR(MAX)   NOT NULL,
    ErrorType         NVARCHAR(255)   NULL,
    StackTrace        NVARCHAR(MAX)   NULL,
    Metadata          NVARCHAR(MAX)   NULL,
    CreatedAt         DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    CycleType         NVARCHAR(10)    NULL,
    CycleDate         DATE            NULL,
    ServerRole        NVARCHAR(20)    NULL,
    Layer             NVARCHAR(20)    NULL,
    
    CONSTRAINT CK_PipelineLog_LogLevel CHECK 
        (LogLevel IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    CONSTRAINT CK_PipelineLog_Layer CHECK 
        (Layer IS NULL OR Layer IN 
         ('extract', 'tokenize', 'parquet', 'registry', 'scd2', 
          'snowflake', 'gate', 'vault', 'health', 'ledger'))
) ON ps_PipelineLog_Monthly(CreatedAt);

-- Clustered columnstore on the partitioning column
CREATE CLUSTERED COLUMNSTORE INDEX CCI_PipelineLog 
    ON General.ops.PipelineLog
    ON ps_PipelineLog_Monthly(CreatedAt);

-- Nonclustered B-tree for BatchId-driven debugging queries
CREATE NONCLUSTERED INDEX IX_PipelineLog_BatchId 
    ON General.ops.PipelineLog (BatchId, CreatedAt);

-- Filtered nonclustered for high-severity scans
CREATE NONCLUSTERED INDEX IX_PipelineLog_Severe 
    ON General.ops.PipelineLog (LogLevel, CreatedAt DESC)
    WHERE LogLevel IN ('ERROR', 'CRITICAL');
```

**Storage forecast**: ~5B rows × ~300 bytes raw = ~1.5 TB rowstore equivalent. With partitioned clustered columnstore + retention (DEBUG/INFO 30 days, WARNING 90 days, ERROR/CRITICAL indefinite): **~150-250 GB on disk**.

**Retention purge implementation**: monthly job switches partitions out and drops them rather than DELETE — vastly faster, no log bloat.

---

## 3. `PipelineExtraction`

**Purpose**: per-day extraction state for large tables. Trust gate signal for delete detection.

**Decisions addressed**: D13, D14.

**Edge cases addressed**: G1, G2, G7, G10.

```sql
CREATE TABLE General.ops.PipelineExtraction (
    ExtractionId         BIGINT IDENTITY(1,1) NOT NULL,
    BatchId              BIGINT          NOT NULL,
    SourceName           NVARCHAR(50)    NOT NULL,
    TableName            NVARCHAR(255)   NOT NULL,
    DateValue            DATE            NOT NULL,
    Status               NVARCHAR(20)    NOT NULL DEFAULT 'IN_PROGRESS',
    StartedAt            DATETIME2(3)    NOT NULL,
    CompletedAt          DATETIME2(3)    NULL,
    EvaluatedAt          DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    RowsExtracted        BIGINT          NULL,
    IsReExtraction       BIT             NOT NULL DEFAULT 0,    -- D14
    ExtractionAttempt    INT             NOT NULL DEFAULT 1,    -- D14
    FailureReason        NVARCHAR(MAX)   NULL,
    
    CONSTRAINT PK_PipelineExtraction PRIMARY KEY CLUSTERED (ExtractionId),
    CONSTRAINT CK_PipelineExtraction_Status CHECK 
        (Status IN ('IN_PROGRESS', 'SUCCESS', 'FAILED'))
);

-- Idempotency: one row per (source, table, date, attempt)
CREATE UNIQUE INDEX UX_PipelineExtraction_Identity 
    ON General.ops.PipelineExtraction 
    (SourceName, TableName, DateValue, ExtractionAttempt);

-- Trust gate query (most-recent SUCCESS for date)
CREATE INDEX IX_PipelineExtraction_TrustGate 
    ON General.ops.PipelineExtraction 
    (SourceName, TableName, DateValue, Status, EvaluatedAt DESC)
    INCLUDE (BatchId, IsReExtraction, ExtractionAttempt);

-- Recent activity scan
CREATE INDEX IX_PipelineExtraction_Recent 
    ON General.ops.PipelineExtraction (BatchId)
    INCLUDE (SourceName, TableName, DateValue, Status);
```

**Storage forecast**: ~500K rows over 7 years (large tables × dates × attempts). **~250 MB**.

---

## 4. `PipelineExecutionGate`

**Purpose**: AM/PM cycle coordination between production and test pipelines (Automic-driven).

**Decisions addressed**: D29 (revised), D33.

**Edge cases addressed**: F3, F4, F11, F15-F20.

```sql
CREATE TABLE General.ops.PipelineExecutionGate (
    GateId                       BIGINT IDENTITY(1,1) NOT NULL,
    CycleType                    NVARCHAR(10)    NOT NULL,
    CycleDate                    DATE            NOT NULL,
    ExpectedStartTime            DATETIME2(3)    NOT NULL,
    ActualStartTime              DATETIME2(3)    NULL,
    ActualCompletionTime         DATETIME2(3)    NULL,
    ExecutingServer              NVARCHAR(20)    NULL,
    Status                       NVARCHAR(20)    NOT NULL DEFAULT 'PENDING',
    BatchId                      BIGINT          NULL,
    LastHeartbeatAt              DATETIME2(3)    NULL,
    FailureReason                NVARCHAR(MAX)   NULL,
    
    -- D33 cancellation columns
    CancellationRequested        BIT             NOT NULL DEFAULT 0,
    CancellationRequestedAt      DATETIME2(3)    NULL,
    CancellationRequestedBy      NVARCHAR(50)    NULL,
    CancellationReason           NVARCHAR(MAX)   NULL,
    CancellationAcknowledgedAt   DATETIME2(3)    NULL,
    
    CreatedAt                    DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    
    CONSTRAINT PK_PipelineExecutionGate PRIMARY KEY CLUSTERED (GateId),
    CONSTRAINT CK_PipelineExecutionGate_CycleType CHECK 
        (CycleType IN ('AM', 'PM')),
    CONSTRAINT CK_PipelineExecutionGate_Status CHECK 
        (Status IN ('PENDING', 'STARTING', 'RUNNING', 'SUCCEEDED', 
                    'FAILED', 'TIMEOUT', 'CANCELLED')),
    CONSTRAINT CK_PipelineExecutionGate_ExecutingServer CHECK 
        (ExecutingServer IS NULL OR ExecutingServer IN ('production', 'test'))
);

-- One gate row per cycle per date (atomic claim)
CREATE UNIQUE INDEX UX_PipelineExecutionGate_Cycle 
    ON General.ops.PipelineExecutionGate (CycleType, CycleDate);

-- Recent failures and stuck cycles
CREATE INDEX IX_PipelineExecutionGate_Status 
    ON General.ops.PipelineExecutionGate (Status, CycleDate DESC, CycleType);

-- Heartbeat staleness detection
CREATE INDEX IX_PipelineExecutionGate_Heartbeat 
    ON General.ops.PipelineExecutionGate (LastHeartbeatAt)
    WHERE Status IN ('STARTING', 'RUNNING');
```

**Storage forecast**: ~5K rows over 7 years (2 cycles/day × 365 × 7). **~5 MB**.

**See also** (per Round 2 close-out 2026-05-10): `phase1/02_configuration.md` § 5.3 documents the column-by-column lifecycle contract (Acquire via SP-3 / SP-4 — covered in § SP-3 + SP-4 below — Heartbeat / Cancel-check / Release) for AM/PM cycles; § 5.3.6 documents the non-AM/PM concurrency pattern (sp_getapplock + `PipelineEventLog` + `IdempotencyLedger`) used by `JOB_RECONCILE_WEEKLY`, `JOB_RETENTION_MONTHLY`, `JOB_CCPA_PROCESS`, `JOB_FAILOVER_TEST` — these jobs do NOT use this table because `CK_PipelineExecutionGate_CycleType IN ('AM','PM')`. For UdmTablesList canonical column inventory consumed alongside the gate table at runtime, see `phase1/02_configuration.md` § 1.

---

## 5. `PromotionLock`

**Purpose**: emergency lock for full server failover (RB-2). Distinct from per-table sp_getapplock.

**Decisions addressed**: D20.

**Edge cases addressed**: F11.

```sql
CREATE TABLE General.ops.PromotionLock (
    LockId          BIGINT IDENTITY(1,1) NOT NULL,
    LockedAt        DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    LockedBy        NVARCHAR(255)   NOT NULL,
    Reason          NVARCHAR(MAX)   NOT NULL,
    ReleasedAt      DATETIME2(3)    NULL,
    ReleasedBy      NVARCHAR(255)   NULL,
    Active          AS CASE WHEN ReleasedAt IS NULL THEN 1 ELSE 0 END PERSISTED,
    
    CONSTRAINT PK_PromotionLock PRIMARY KEY CLUSTERED (LockId)
);

-- Only one active lock at a time
CREATE UNIQUE INDEX UX_PromotionLock_OneActive 
    ON General.ops.PromotionLock (Active)
    WHERE Active = 1;

-- Recent locks audit query
CREATE INDEX IX_PromotionLock_Recent 
    ON General.ops.PromotionLock (LockedAt DESC);
```

**Storage forecast**: ~100 rows lifetime. Trivial.

---

## 6. `MaintenanceWindow`

**Purpose**: scheduled outage windows that suppress watchdog/failover logic.

**Decisions addressed**: F14 mitigation.

**Edge cases addressed**: F14.

```sql
CREATE TABLE General.ops.MaintenanceWindow (
    WindowId           BIGINT IDENTITY(1,1) NOT NULL,
    StartAt            DATETIME2(3)    NOT NULL,
    EndAt              DATETIME2(3)    NOT NULL,
    AffectedComponent  NVARCHAR(50)    NOT NULL,    -- 'production_pipeline', 'test_pipeline', 'all', etc.
    Reason             NVARCHAR(MAX)   NOT NULL,
    CreatedBy          NVARCHAR(255)   NOT NULL,
    CreatedAt          DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    
    CONSTRAINT PK_MaintenanceWindow PRIMARY KEY CLUSTERED (WindowId),
    CONSTRAINT CK_MaintenanceWindow_TimeRange CHECK (EndAt > StartAt)
);

-- Active maintenance window check (test pipeline reads this at startup)
CREATE INDEX IX_MaintenanceWindow_Active 
    ON General.ops.MaintenanceWindow (StartAt, EndAt)
    INCLUDE (AffectedComponent);
```

**Storage forecast**: ~500 rows over 7 years. Trivial.

---

## 7. `IdempotencyLedger`

**Purpose**: per-step status to enable crash recovery via short-circuit. Pattern 1 from Agent 3 idempotency research.

**Decisions addressed**: D17, D45 startup recovery sweep.

**Edge cases addressed**: I1, I2, I3, I19, F4.

```sql
CREATE TABLE General.ops.IdempotencyLedger (
    LedgerId           BIGINT IDENTITY(1,1) NOT NULL,
    BatchId            BIGINT          NOT NULL,
    SourceName         NVARCHAR(50)    NOT NULL,
    TableName          NVARCHAR(255)   NOT NULL,
    EventType          NVARCHAR(50)    NOT NULL,
    Status             NVARCHAR(20)    NOT NULL DEFAULT 'IN_PROGRESS',
    StartedAt          DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    CompletedAt       DATETIME2(3)    NULL,
    DurationMs         BIGINT          NULL,
    ErrorMessage       NVARCHAR(MAX)   NULL,
    RecoveryAction     NVARCHAR(50)    NULL,    -- 'STARTUP_SWEEP_FAILED', 'OPERATOR_ABANDONED', etc.
    
    CONSTRAINT PK_IdempotencyLedger PRIMARY KEY CLUSTERED (LedgerId),
    CONSTRAINT CK_IdempotencyLedger_Status CHECK 
        (Status IN ('IN_PROGRESS', 'COMPLETED', 'FAILED'))
);

-- Idempotency key: prevents double-write
CREATE UNIQUE INDEX UX_IdempotencyLedger_Key 
    ON General.ops.IdempotencyLedger 
    (BatchId, SourceName, TableName, EventType);

-- Stuck IN_PROGRESS detection (startup recovery sweep)
CREATE INDEX IX_IdempotencyLedger_Stuck 
    ON General.ops.IdempotencyLedger (Status, StartedAt)
    WHERE Status = 'IN_PROGRESS';

-- Per-batch status review
CREATE INDEX IX_IdempotencyLedger_Batch 
    ON General.ops.IdempotencyLedger (BatchId, EventType);
```

**Storage forecast**: ~50M rows × ~250 bytes = **~12 GB**. Rowstore + PAGE compression.

---

## 8. `ParquetSnapshotRegistry`

**Purpose**: index of every Parquet file written by the pipeline. Operational nerve center for the snapshot layer.

**Decisions addressed**: D25, D38.

**Edge cases addressed**: N1, N2, N3, N4, N5, N6, N7, N8.

```sql
CREATE TABLE General.ops.ParquetSnapshotRegistry (
    RegistryId           BIGINT IDENTITY(1,1) NOT NULL,
    SourceName           NVARCHAR(50)    NOT NULL,
    TableName            NVARCHAR(255)   NOT NULL,
    BatchId              BIGINT          NOT NULL,
    BusinessDate         DATE            NULL,        -- NULL for small tables
    
    -- File location
    NetworkDrivePath     NVARCHAR(1024)  NOT NULL,
    SnowflakeStagePath   NVARCHAR(1024)  NULL,
    SnowflakeUploadedAt  DATETIME2(3)    NULL,
    
    -- File metadata
    RowCount             BIGINT          NOT NULL,
    UncompressedBytes    BIGINT          NOT NULL,
    CompressedBytes      BIGINT          NOT NULL,
    SchemaHash           VARCHAR(64)     NOT NULL,
    ContentChecksum      VARCHAR(64)     NULL,
    
    -- PII / data protection
    PiiPolicyVersion     INT             NULL,
    PiiRedactedColumns   NVARCHAR(MAX)   NULL,    -- JSON list
    
    -- Lifecycle
    StorageTier          NVARCHAR(10)    NOT NULL DEFAULT 'hot',
    Status               NVARCHAR(20)    NOT NULL DEFAULT 'created',
    
    -- Audit
    CreatedAt            DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    LastVerifiedAt       DATETIME2(3)    NULL,
    LastAccessedAt       DATETIME2(3)    NULL,
    PurgedAt             DATETIME2(3)    NULL,
    PurgedReason         NVARCHAR(MAX)   NULL,
    
    CONSTRAINT PK_ParquetSnapshotRegistry PRIMARY KEY CLUSTERED (RegistryId),
    CONSTRAINT CK_ParquetSnapshotRegistry_Tier CHECK 
        (StorageTier IN ('hot', 'warm', 'cold', 'frozen')),
    CONSTRAINT CK_ParquetSnapshotRegistry_Status CHECK 
        (Status IN ('created', 'verified', 'replicated', 'archived', 
                    'missing', 'purged', 'replication_failed'))
);

-- Idempotency: one row per snapshot
CREATE UNIQUE INDEX UX_ParquetSnapshotRegistry_Identity 
    ON General.ops.ParquetSnapshotRegistry 
    (SourceName, TableName, BatchId, BusinessDate);

-- Tier review job
CREATE INDEX IX_ParquetSnapshotRegistry_TierAge 
    ON General.ops.ParquetSnapshotRegistry (StorageTier, CreatedAt);

-- Per-table file lookup
CREATE INDEX IX_ParquetSnapshotRegistry_TableLookup 
    ON General.ops.ParquetSnapshotRegistry 
    (SourceName, TableName, BusinessDate, BatchId DESC);

-- Snowflake replication status
CREATE INDEX IX_ParquetSnapshotRegistry_NeedsReplication 
    ON General.ops.ParquetSnapshotRegistry (CreatedAt)
    WHERE SnowflakeStagePath IS NULL AND Status = 'created';

-- Integrity verification scan
CREATE INDEX IX_ParquetSnapshotRegistry_Verification 
    ON General.ops.ParquetSnapshotRegistry (LastVerifiedAt)
    WHERE Status NOT IN ('purged', 'missing');
```

**Storage forecast**: ~10M rows × ~1KB = **~10 GB**. Rowstore.

---

## 9. `ExtractionRangePolicy`

**Purpose**: date-range scheduler config for large tables. Replaces fixed `LookbackDays`.

**Decisions addressed**: D12.

**Edge cases addressed**: M11 (cold-start), M12 (immutable history).

```sql
CREATE TABLE General.ops.ExtractionRangePolicy (
    RangeId            BIGINT IDENTITY(1,1) NOT NULL,
    SourceName         NVARCHAR(50)    NOT NULL,
    TableName          NVARCHAR(255)   NOT NULL,
    RangeStartDate     DATE            NULL,        -- NULL = "today" (open-ended)
    RangeEndDate       DATE            NULL,        -- NULL = "today"
    RangeKind          NVARCHAR(20)    NOT NULL,    -- 'current', 'lookback', 'backfill', 'reconciliation'
    MaxStaleDays       INT             NOT NULL,
    Priority           INT             NOT NULL DEFAULT 50,
    LastExtractedAt    DATETIME2(3)    NULL,
    LastSuccessAt      DATETIME2(3)    NULL,
    Active             BIT             NOT NULL DEFAULT 1,
    Notes              NVARCHAR(MAX)   NULL,
    CreatedAt          DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    UpdatedAt          DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    
    CONSTRAINT PK_ExtractionRangePolicy PRIMARY KEY CLUSTERED (RangeId),
    CONSTRAINT CK_ExtractionRangePolicy_Kind CHECK 
        (RangeKind IN ('current', 'lookback', 'backfill', 'reconciliation'))
);

-- Scheduler "due ranges" query
CREATE INDEX IX_ExtractionRangePolicy_Schedule 
    ON General.ops.ExtractionRangePolicy 
    (Active, Priority DESC, LastExtractedAt)
    INCLUDE (SourceName, TableName, RangeKind, MaxStaleDays);

-- Per-table policy lookup
CREATE INDEX IX_ExtractionRangePolicy_Table 
    ON General.ops.ExtractionRangePolicy 
    (SourceName, TableName, Active);
```

**Storage forecast**: ~500 rows. Trivial.

---

## 10. `LatenessProfile`

**Purpose**: empirical `L_99` measurements per table. Drives per-table `LookbackDays` setting.

**Decisions addressed**: D11.

**Edge cases addressed**: M2, M9, M11.

```sql
CREATE TABLE General.ops.LatenessProfile (
    ProfileId          BIGINT IDENTITY(1,1) NOT NULL,
    SourceName         NVARCHAR(50)    NOT NULL,
    TableName          NVARCHAR(255)   NOT NULL,
    MeasuredAt         DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    MeasurementWindowDays INT          NOT NULL,    -- e.g. 90, 365
    BusinessDateColumn NVARCHAR(255)   NOT NULL,
    LastModifiedColumn NVARCHAR(255)   NOT NULL,
    
    -- Empirical percentiles (days late)
    LatenessP50        DECIMAL(10,2)   NULL,
    LatenessP90        DECIMAL(10,2)   NULL,
    LatenessP95        DECIMAL(10,2)   NULL,
    LatenessP99        DECIMAL(10,2)   NULL,
    LatenessP999       DECIMAL(10,2)   NULL,
    LatenessMax        DECIMAL(10,2)   NULL,
    
    -- Recommendations
    RecommendedLookback INT            NULL,        -- L_99 × 1.5
    SafetyFactor        DECIMAL(5,2)   NOT NULL DEFAULT 1.5,
    CurrentConfiguredLookback INT      NULL,        -- from UdmTablesList
    
    -- Drift detection
    PreviousP99         DECIMAL(10,2)  NULL,
    DriftPct            DECIMAL(5,2)   NULL,
    
    SampleRowCount      BIGINT         NOT NULL,
    
    CONSTRAINT PK_LatenessProfile PRIMARY KEY CLUSTERED (ProfileId)
);

-- Latest profile per table
CREATE INDEX IX_LatenessProfile_Latest 
    ON General.ops.LatenessProfile 
    (SourceName, TableName, MeasuredAt DESC);
```

**Storage forecast**: ~5K rows over 7 years. Trivial.

---

## 11. `DeleteEvaluationAudit`

**Purpose**: append-only audit of every (date, batch) delete-evaluation decision.

**Decisions addressed**: D13.

**Edge cases addressed**: I14.

```sql
CREATE TABLE General.ops.DeleteEvaluationAudit (
    AuditId                  BIGINT IDENTITY(1,1) NOT NULL,
    BatchId                  BIGINT          NOT NULL,
    SourceName               NVARCHAR(50)    NOT NULL,
    TableName                NVARCHAR(255)   NOT NULL,
    DateValue                DATE            NOT NULL,
    EvaluatedAt              DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    EvaluationOutcome        NVARCHAR(30)    NOT NULL,
    AuthoritativeBatchId     BIGINT          NULL,
    BronzeActiveCount        BIGINT          NULL,
    CandidateDeleteCount     BIGINT          NULL,
    ConfirmedDeleteCount     BIGINT          NULL,
    SuppressedReason         NVARCHAR(MAX)   NULL,
    
    CONSTRAINT PK_DeleteEvaluationAudit PRIMARY KEY CLUSTERED (AuditId),
    CONSTRAINT CK_DeleteEvaluationAudit_Outcome CHECK 
        (EvaluationOutcome IN ('evaluated', 'suppressed_no_success', 
                               'suppressed_all_failed', 'no_candidates'))
);

CREATE INDEX IX_DeleteEvaluationAudit_Lookup 
    ON General.ops.DeleteEvaluationAudit 
    (SourceName, TableName, DateValue, EvaluatedAt DESC);

CREATE INDEX IX_DeleteEvaluationAudit_Suppressed 
    ON General.ops.DeleteEvaluationAudit (EvaluationOutcome, EvaluatedAt DESC)
    WHERE EvaluationOutcome <> 'evaluated';
```

**Storage forecast**: ~5M rows × ~200 bytes = **~1 GB**.

---

## 12. `ExtractionGapLog`

**Purpose**: documented extraction gaps (per-source per-table per-date-range).

**Decisions addressed**: D22.

**Edge cases addressed**: G1-G10.

```sql
CREATE TABLE General.ops.ExtractionGapLog (
    GapLogId          BIGINT IDENTITY(1,1) NOT NULL,
    SourceName        NVARCHAR(50)    NOT NULL,
    TableName         NVARCHAR(255)   NOT NULL,
    MissingFromDate   DATE            NOT NULL,
    MissingToDate     DATE            NOT NULL,
    Classification    NVARCHAR(30)    NOT NULL,    -- 'never_attempted', 'all_attempts_failed', 'beyond_source_retention'
    DetectedAt        DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    DetectedByBatchId BIGINT          NOT NULL,
    Resolution        NVARCHAR(30)    NOT NULL DEFAULT 'PENDING',    -- 'PENDING', 'BACKFILLED', 'ACCEPTED', 'NO_LONGER_RECOVERABLE'
    ResolvedAt        DATETIME2(3)    NULL,
    ResolvedBy        NVARCHAR(255)   NULL,
    Reason            NVARCHAR(MAX)   NULL,
    
    CONSTRAINT PK_ExtractionGapLog PRIMARY KEY CLUSTERED (GapLogId),
    CONSTRAINT CK_ExtractionGapLog_DateRange CHECK (MissingToDate >= MissingFromDate),
    CONSTRAINT CK_ExtractionGapLog_Classification CHECK 
        (Classification IN ('never_attempted', 'all_attempts_failed', 'beyond_source_retention')),
    CONSTRAINT CK_ExtractionGapLog_Resolution CHECK 
        (Resolution IN ('PENDING', 'BACKFILLED', 'ACCEPTED', 'NO_LONGER_RECOVERABLE'))
);

CREATE INDEX IX_ExtractionGapLog_Pending 
    ON General.ops.ExtractionGapLog (Resolution, DetectedAt DESC)
    WHERE Resolution = 'PENDING';

CREATE INDEX IX_ExtractionGapLog_Lookup 
    ON General.ops.ExtractionGapLog (SourceName, TableName, MissingFromDate);
```

**Storage forecast**: ~1K rows lifetime. Trivial.

---

## 13. `ManualCorrectionLog`

**Purpose**: audit of any operator-driven Bronze writes outside normal pipeline flow.

**Decisions addressed**: S8 mitigation.

**Edge cases addressed**: S8.

```sql
CREATE TABLE General.ops.ManualCorrectionLog (
    CorrectionId      BIGINT IDENTITY(1,1) NOT NULL,
    SourceName        NVARCHAR(50)    NOT NULL,
    TableName         NVARCHAR(255)   NOT NULL,
    PerformedAt       DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    PerformedBy       NVARCHAR(255)   NOT NULL,
    TicketReference   NVARCHAR(255)   NULL,
    PkColumns         NVARCHAR(MAX)   NULL,    -- JSON list of affected PKs
    Operation         NVARCHAR(50)    NOT NULL,    -- 'UPDATE', 'DELETE', 'INSERT'
    BeforeState       NVARCHAR(MAX)   NULL,    -- JSON
    AfterState        NVARCHAR(MAX)   NULL,    -- JSON
    Justification     NVARCHAR(MAX)   NOT NULL,
    ApprovedBy        NVARCHAR(255)   NULL,
    
    CONSTRAINT PK_ManualCorrectionLog PRIMARY KEY CLUSTERED (CorrectionId)
);

CREATE INDEX IX_ManualCorrectionLog_Recent 
    ON General.ops.ManualCorrectionLog (PerformedAt DESC);
```

**Storage forecast**: ~500 rows lifetime. Trivial.

---

## 14. `ReconciliationLog`

**Purpose**: P3-4 weekly reconciliation results.

**Decisions addressed**: B-12, S14, OBS-6.

**Edge cases addressed**: S14.

```sql
CREATE TABLE General.ops.ReconciliationLog (
    ReconciliationId    BIGINT IDENTITY(1,1) NOT NULL,
    BatchId             BIGINT          NOT NULL,
    SourceName          NVARCHAR(50)    NOT NULL,
    TableName           NVARCHAR(255)   NOT NULL,
    CheckType           NVARCHAR(50)    NOT NULL,
    StartedAt           DATETIME2(3)    NOT NULL,
    CompletedAt         DATETIME2(3)    NULL,
    Status              NVARCHAR(20)    NOT NULL DEFAULT 'IN_PROGRESS',
    SourceCount         BIGINT          NULL,
    StageCount          BIGINT          NULL,
    BronzeCount         BIGINT          NULL,
    DiscrepancyCount    BIGINT          NULL,
    DriftPct            DECIMAL(10,4)   NULL,
    Severity            NVARCHAR(20)    NULL,    -- 'INFO', 'WARNING', 'ERROR', 'CRITICAL'
    Findings            NVARCHAR(MAX)   NULL,    -- JSON
    Acknowledged        BIT             NOT NULL DEFAULT 0,
    AcknowledgedAt      DATETIME2(3)    NULL,
    AcknowledgedBy      NVARCHAR(255)   NULL,
    
    CONSTRAINT PK_ReconciliationLog PRIMARY KEY CLUSTERED (ReconciliationId),
    CONSTRAINT CK_ReconciliationLog_Status CHECK 
        (Status IN ('IN_PROGRESS', 'SUCCESS', 'FAILED', 'PARTIAL'))
);

CREATE INDEX IX_ReconciliationLog_Recent 
    ON General.ops.ReconciliationLog 
    (SourceName, TableName, CheckType, StartedAt DESC);

CREATE INDEX IX_ReconciliationLog_Unacknowledged 
    ON General.ops.ReconciliationLog (Severity, StartedAt DESC)
    WHERE Acknowledged = 0 AND Severity IN ('WARNING', 'ERROR', 'CRITICAL');
```

**Storage forecast**: ~50K rows × ~2KB = **~100 MB**.

---

## 15. `SCD2RepairLog`

**Purpose**: log of repair actions taken by `tools/repair_scd2.py`.

**Decisions addressed**: SCD2-R6.

**Edge cases addressed**: S2, S3, V-4.

```sql
CREATE TABLE General.ops.SCD2RepairLog (
    RepairId          BIGINT IDENTITY(1,1) NOT NULL,
    BatchId           BIGINT          NULL,
    SourceName        NVARCHAR(50)    NOT NULL,
    TableName         NVARCHAR(255)   NOT NULL,
    RepairType        NVARCHAR(50)    NOT NULL,    -- 'sentinel_fill', 'orphan_cleanup', 'duplicate_active_dedup'
    Status            NVARCHAR(20)    NOT NULL,    -- 'DRY_RUN', 'APPLIED', 'FAILED'
    RowsAffected      BIGINT          NOT NULL DEFAULT 0,
    SamplePks         NVARCHAR(MAX)   NULL,    -- JSON
    StartedAt         DATETIME2(3)    NOT NULL,
    CompletedAt       DATETIME2(3)    NULL,
    DurationMs        BIGINT          NULL,
    InvokedBy         NVARCHAR(255)   NOT NULL,
    
    CONSTRAINT PK_SCD2RepairLog PRIMARY KEY CLUSTERED (RepairId),
    CONSTRAINT CK_SCD2RepairLog_RepairType CHECK 
        (RepairType IN ('sentinel_fill', 'orphan_cleanup', 'duplicate_active_dedup')),
    CONSTRAINT CK_SCD2RepairLog_Status CHECK 
        (Status IN ('DRY_RUN', 'APPLIED', 'FAILED'))
);

CREATE INDEX IX_SCD2RepairLog_Lookup 
    ON General.ops.SCD2RepairLog 
    (SourceName, TableName, StartedAt DESC);
```

**Storage forecast**: ~5K rows lifetime. Trivial.

---

## 16. `PiiVault`

**Purpose**: plaintext-to-token mapping with retention/legal-hold tracking. The single source of truth for PII protection.

**Decisions addressed**: D6, D26, D30.

**Edge cases addressed**: P1-P10, V1, V2.

**Security note**: requires TDE on `General` database (D45.7); access only via stored procedures (D45.6 — DELETE permission denied at role level).

```sql
CREATE TABLE General.ops.PiiVault (
    Token                VARCHAR(40)     NOT NULL,
    PiiType              NVARCHAR(20)    NOT NULL,    -- 'SSN', 'EIN', 'EMAIL', 'NAME', 'ACCOUNT'
    SourceName           NVARCHAR(50)    NOT NULL,
    PlaintextValue       NVARCHAR(MAX)   NOT NULL,
    PlaintextHash        VARBINARY(32)   NOT NULL,    -- SHA-256 for lookup
    
    -- v2 fix: D7 future-proof for AES-GCM-SIV migration without rewrap-everything
    EncryptionVersion    INT             NOT NULL DEFAULT 1,
    
    CreatedAt            DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    LastAccessedAt       DATETIME2(3)    NULL,
    AccessCount          BIGINT          NOT NULL DEFAULT 0,
    
    -- D30 retention / legal hold
    Status               NVARCHAR(20)    NOT NULL DEFAULT 'active',
    StatusReason         NVARCHAR(MAX)   NULL,
    StatusChangedAt      DATETIME2(3)    NULL,
    StatusChangedBy      NVARCHAR(128)   NULL,
    LegalHold            BIT             NOT NULL DEFAULT 0,
    LegalHoldReason      NVARCHAR(MAX)   NULL,
    LegalHoldReference   NVARCHAR(255)   NULL,
    RetentionExpiresAt   DATETIME2(3)    NULL,
    
    CONSTRAINT PK_PiiVault PRIMARY KEY CLUSTERED (Token),
    CONSTRAINT CK_PiiVault_PiiType CHECK 
        (PiiType IN ('SSN', 'EIN', 'EMAIL', 'NAME', 'ACCOUNT', 'PHONE', 'ADDRESS', 'OTHER')),
    CONSTRAINT CK_PiiVault_Status CHECK 
        (Status IN ('active', 'deleted_per_request', 'purged_for_retention', 'legal_hold_only')),
    CONSTRAINT CK_PiiVault_EncryptionVersion CHECK 
        (EncryptionVersion >= 1)
);

-- v2 fix per validation agent: filtered UNIQUE only on active rows.
-- Without the WHERE clause, a CCPA-deleted vault row (Status='deleted_per_request')
-- would block a fresh INSERT for the same plaintext on later re-tokenization,
-- because the unique index would see it as a collision.
-- The filtered index allows: deleted rows preserved as audit history, AND new
-- active rows mint cleanly when the same plaintext reappears in source.
CREATE UNIQUE INDEX UX_PiiVault_Lookup 
    ON General.ops.PiiVault (PiiType, SourceName, PlaintextHash)
    INCLUDE (Token, LegalHold)
    WHERE Status = 'active';

-- Defense-in-depth: non-unique secondary index covers historical lookups
-- (auditor: "show me every token issued for this plaintext, including deleted")
CREATE INDEX IX_PiiVault_HistoricalLookup
    ON General.ops.PiiVault (PiiType, SourceName, PlaintextHash, Status)
    INCLUDE (Token, StatusChangedAt);

-- Retention enforcement scan
CREATE INDEX IX_PiiVault_Retention 
    ON General.ops.PiiVault (RetentionExpiresAt)
    WHERE Status = 'active' AND LegalHold = 0;

-- Status review queries
CREATE INDEX IX_PiiVault_Status 
    ON General.ops.PiiVault (Status, StatusChangedAt DESC);

-- Legal hold review
CREATE INDEX IX_PiiVault_LegalHold 
    ON General.ops.PiiVault (LegalHold)
    WHERE LegalHold = 1;
```

**Storage forecast**: ~50M rows × ~300 bytes = **~15 GB**. Rowstore + PAGE compression.

---

## 17. `PiiTokenProvenance`

**Purpose**: append-only first-observation provenance per (Token, Source, Object, Column).

**Decisions addressed**: D26 (revised).

**Edge cases addressed**: V1-V10.

```sql
CREATE TABLE General.ops.PiiTokenProvenance (
    ProvenanceId         BIGINT IDENTITY(1,1) NOT NULL,
    Token                VARCHAR(40)     NOT NULL,
    SourceName           NVARCHAR(50)    NOT NULL,
    SourceObjectType     NVARCHAR(20)    NOT NULL,    -- 'TABLE', 'VIEW', 'FILE'
    DatabaseName         NVARCHAR(255)   NULL,
    SchemaName           NVARCHAR(255)   NULL,
    ObjectName           NVARCHAR(255)   NOT NULL,
    ColumnName           NVARCHAR(255)   NOT NULL,
    FilePath             NVARCHAR(1024)  NULL,
    FirstObservedBatchId BIGINT          NOT NULL,
    FirstObservedAt      DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    
    CONSTRAINT PK_PiiTokenProvenance PRIMARY KEY NONCLUSTERED (ProvenanceId),
    CONSTRAINT FK_PiiTokenProvenance_Vault FOREIGN KEY (Token) 
        REFERENCES General.ops.PiiVault(Token),
    CONSTRAINT CK_PiiTokenProvenance_ObjectType CHECK 
        (SourceObjectType IN ('TABLE', 'VIEW', 'FILE'))
);

-- Clustered columnstore for compression at high volume
CREATE CLUSTERED COLUMNSTORE INDEX CCI_PiiTokenProvenance 
    ON General.ops.PiiTokenProvenance;

-- Token lookup (audit query: where does this token appear?)
CREATE NONCLUSTERED INDEX IX_PiiTokenProvenance_Token 
    ON General.ops.PiiTokenProvenance (Token);

-- Object inventory (audit query: what PII columns in this table?)
CREATE NONCLUSTERED INDEX IX_PiiTokenProvenance_Object 
    ON General.ops.PiiTokenProvenance 
    (SourceName, ObjectName, ColumnName);

-- Idempotency: prevent duplicate first-observation rows
CREATE UNIQUE NONCLUSTERED INDEX UX_PiiTokenProvenance_FirstObs 
    ON General.ops.PiiTokenProvenance 
    (Token, SourceName, ObjectName, ColumnName, FilePath);
```

**Storage forecast**: ~250M rows × ~400 bytes raw = ~100 GB rowstore. With clustered columnstore + retention: **~12-15 GB on disk**.

---

## 18. `PiiTokenizationBatch`

**Purpose**: append-only batch-level tokenization summary.

**Decisions addressed**: D26 (revised).

**Edge cases addressed**: V4.

```sql
CREATE TABLE General.ops.PiiTokenizationBatch (
    BatchTokenizationId   BIGINT IDENTITY(1,1) NOT NULL,
    BatchId               BIGINT          NOT NULL,
    SourceName            NVARCHAR(50)    NOT NULL,
    ObjectName            NVARCHAR(255)   NOT NULL,
    ColumnName            NVARCHAR(255)   NOT NULL,
    TokenizedAt           DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    NewTokensGenerated    BIGINT          NOT NULL,
    ExistingTokensReused  BIGINT          NOT NULL,
    TotalRowsTokenized    BIGINT          NOT NULL,
    DurationMs            BIGINT          NOT NULL,
    
    CONSTRAINT PK_PiiTokenizationBatch PRIMARY KEY CLUSTERED (BatchTokenizationId)
);

-- v2 fix per ROUND_1_REVIEW: idempotency UNIQUE constraint.
-- Without this, the same batch could be tokenized twice and produce
-- two rows with conflicting NewTokensGenerated counts (I3 violation).
CREATE UNIQUE INDEX UX_PiiTokenizationBatch_Identity
    ON General.ops.PiiTokenizationBatch
    (BatchId, SourceName, ObjectName, ColumnName);

CREATE INDEX IX_PiiTokenizationBatch_BatchId 
    ON General.ops.PiiTokenizationBatch (BatchId);

CREATE INDEX IX_PiiTokenizationBatch_Source 
    ON General.ops.PiiTokenizationBatch 
    (SourceName, ObjectName, ColumnName, TokenizedAt DESC);
```

**Storage forecast**: ~1.3M rows × ~200 bytes = **~250 MB**.

---

## 19. `PiiVaultAccessLog`

**Purpose**: append-only audit of every decrypt operation.

**Decisions addressed**: D6, D30.

**Edge cases addressed**: P8.

```sql
CREATE TABLE General.ops.PiiVaultAccessLog (
    AccessLogId       BIGINT IDENTITY(1,1) NOT NULL,
    RequestId         UNIQUEIDENTIFIER NOT NULL,
    AccessedAt        DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    AccessedBy        NVARCHAR(255)   NOT NULL,
    AccessRole        NVARCHAR(255)   NOT NULL,
    Token             VARCHAR(40)     NOT NULL,
    Justification     NVARCHAR(MAX)   NOT NULL,
    AccessSourceIp    NVARCHAR(45)    NULL,    -- IPv4 or IPv6
    AccessApplication NVARCHAR(255)   NULL,
    
    CONSTRAINT PK_PiiVaultAccessLog PRIMARY KEY CLUSTERED (AccessLogId),
    -- v2 fix per ROUND_1_REVIEW: explicit FK to vault for referential integrity
    CONSTRAINT FK_PiiVaultAccessLog_Vault FOREIGN KEY (Token)
        REFERENCES General.ops.PiiVault(Token)
);

CREATE INDEX IX_PiiVaultAccessLog_RequestId 
    ON General.ops.PiiVaultAccessLog (RequestId);

CREATE INDEX IX_PiiVaultAccessLog_Token 
    ON General.ops.PiiVaultAccessLog (Token, AccessedAt DESC);

CREATE INDEX IX_PiiVaultAccessLog_User 
    ON General.ops.PiiVaultAccessLog (AccessedBy, AccessedAt DESC);

-- Anomaly detection: bulk access patterns
CREATE INDEX IX_PiiVaultAccessLog_BulkAccess 
    ON General.ops.PiiVaultAccessLog (AccessedBy, AccessedAt)
    INCLUDE (Token);
```

**Storage forecast**: ~500K rows × ~500 bytes = **~250 MB**.

---

## 20. `CcpaDeletionLog`

**Purpose**: append-only audit of CCPA right-to-deletion requests.

**Decisions addressed**: D30.

**Edge cases addressed**: P7, V8.

```sql
CREATE TABLE General.ops.CcpaDeletionLog (
    DeletionId            BIGINT IDENTITY(1,1) NOT NULL,
    RequestId             UNIQUEIDENTIFIER NOT NULL,
    RequestedAt           DATETIME2(3)    NOT NULL,
    RequestedBy           NVARCHAR(255)   NOT NULL,
    SubjectIdentifier     NVARCHAR(MAX)   NOT NULL,    -- encrypted subject reference
    AffectedTokens        NVARCHAR(MAX)   NOT NULL,    -- JSON list
    Action                NVARCHAR(30)    NOT NULL,    -- 'deleted', 'partial', 'legal_hold_override'
    LegalExceptionReason  NVARCHAR(MAX)   NULL,
    ProcessedAt           DATETIME2(3)    NULL,
    ProcessedBy           NVARCHAR(128)   NULL,
    NotifiedConsumerAt    DATETIME2(3)    NULL,
    
    CONSTRAINT PK_CcpaDeletionLog PRIMARY KEY CLUSTERED (DeletionId),
    CONSTRAINT CK_CcpaDeletionLog_Action CHECK 
        (Action IN ('deleted', 'partial', 'legal_hold_override', 'pending'))
);

CREATE UNIQUE INDEX UX_CcpaDeletionLog_RequestId 
    ON General.ops.CcpaDeletionLog (RequestId);

CREATE INDEX IX_CcpaDeletionLog_Recent 
    ON General.ops.CcpaDeletionLog (RequestedAt DESC);
```

**Storage forecast**: ~5K rows lifetime. Trivial.

---

## 21. `TableEnablementLog`

**Purpose**: Phase 4 per-table enablement tracking.

**Decisions addressed**: D34, Phase 4 deliverable.

```sql
CREATE TABLE General.ops.TableEnablementLog (
    EnablementId            BIGINT IDENTITY(1,1) NOT NULL,
    SourceName              NVARCHAR(50)    NOT NULL,
    TableName               NVARCHAR(255)   NOT NULL,
    EnabledAt               DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    EnabledBy               NVARCHAR(255)   NOT NULL,
    EnabledBatchId          BIGINT          NULL,
    FirstSuccessfulRunAt    DATETIME2(3)    NULL,
    Cohort                  NVARCHAR(50)    NULL,
    SignoffUser             NVARCHAR(255)   NULL,
    SignoffAt               DATETIME2(3)    NULL,
    Notes                   NVARCHAR(MAX)   NULL,
    
    CONSTRAINT PK_TableEnablementLog PRIMARY KEY CLUSTERED (EnablementId)
);

CREATE UNIQUE INDEX UX_TableEnablementLog_Table 
    ON General.ops.TableEnablementLog (SourceName, TableName);
```

**Storage forecast**: ~500 rows lifetime. Trivial.

---

## 22. `HealthCheckLog`

**Purpose**: Phase 6 health check results.

**Decisions addressed**: D32, D38.

```sql
CREATE TABLE General.ops.HealthCheckLog (
    HealthCheckId      BIGINT IDENTITY(1,1) NOT NULL,
    BatchId            BIGINT          NULL,
    CheckName          NVARCHAR(100)   NOT NULL,
    SourceName         NVARCHAR(50)    NULL,
    TableName          NVARCHAR(255)   NULL,
    StartedAt          DATETIME2(3)    NOT NULL,
    CompletedAt        DATETIME2(3)    NULL,
    Status             NVARCHAR(20)    NOT NULL,    -- 'OK', 'WARNING', 'ERROR', 'CRITICAL', 'INFO'
    Value              DECIMAL(18,6)   NULL,
    Threshold          DECIMAL(18,6)   NULL,
    Findings           NVARCHAR(MAX)   NULL,    -- JSON
    Acknowledged       BIT             NOT NULL DEFAULT 0,
    AcknowledgedAt     DATETIME2(3)    NULL,
    AcknowledgedBy     NVARCHAR(255)   NULL,
    
    CONSTRAINT PK_HealthCheckLog PRIMARY KEY CLUSTERED (HealthCheckId),
    CONSTRAINT CK_HealthCheckLog_Status CHECK 
        (Status IN ('OK', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'))
);

CREATE INDEX IX_HealthCheckLog_Recent 
    ON General.ops.HealthCheckLog 
    (CheckName, SourceName, TableName, StartedAt DESC);

CREATE INDEX IX_HealthCheckLog_Unacknowledged 
    ON General.ops.HealthCheckLog (Status, StartedAt DESC)
    WHERE Acknowledged = 0 AND Status IN ('WARNING', 'ERROR', 'CRITICAL');
```

**Storage forecast**: ~10M rows × ~500 bytes = **~5 GB** (with retention). Rowstore.

---

## 23. `SchemaContract` (NEW v2)

**v2 fix per ROUND_1_REVIEW.md**: D40 (Schema evolution governance, Round 7) requires a `SchemaContract` table to record the expected shape of each source object/column. Without it, schema-evolution-detected changes have no baseline to compare against.

**Purpose**: per-source per-object per-column contract entries that document the expected schema. Schema evolution (Phase 1 Round 7) compares actual source schema against contract; deviations escalate per the schema governance process.

**Decisions addressed**: D40, D41 supersession.

```sql
CREATE TABLE General.ops.SchemaContract (
    ContractId          BIGINT IDENTITY(1,1) NOT NULL,
    SourceName          NVARCHAR(50)    NOT NULL,
    ObjectName          NVARCHAR(255)   NOT NULL,    -- table or view name
    ColumnName          NVARCHAR(255)   NULL,        -- NULL = table-level contract
    
    ContractKey         NVARCHAR(100)   NOT NULL,    -- 'expected_type', 'nullability', 
                                                     -- 'precision', 'scale',
                                                     -- 'change_notification_sla_days',
                                                     -- 'is_pii', 'pii_type'
    ContractValue       NVARCHAR(MAX)   NOT NULL,
    
    EffectiveFrom       DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    EffectiveTo         DATETIME2(3)    NULL,        -- NULL = current; non-NULL = superseded
    SupersededBy        BIGINT          NULL,        -- self-reference to next ContractId
    
    Notes               NVARCHAR(MAX)   NULL,
    CreatedAt           DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    CreatedBy           NVARCHAR(255)   NOT NULL,
    
    CONSTRAINT PK_SchemaContract PRIMARY KEY CLUSTERED (ContractId)
);

-- Active contracts lookup (most common query)
CREATE INDEX IX_SchemaContract_Active 
    ON General.ops.SchemaContract 
    (SourceName, ObjectName, ColumnName, ContractKey, EffectiveFrom DESC)
    INCLUDE (ContractValue)
    WHERE EffectiveTo IS NULL;

-- History audit
CREATE INDEX IX_SchemaContract_History 
    ON General.ops.SchemaContract 
    (SourceName, ObjectName, ColumnName, ContractKey, EffectiveFrom);
```

**Example rows**:

```sql
-- DNA.osibank.ACCT.ACCTNBR is an integer PK, never null
INSERT INTO General.ops.SchemaContract 
    (SourceName, ObjectName, ColumnName, ContractKey, ContractValue, CreatedBy)
VALUES
    ('DNA', 'ACCT', 'ACCTNBR', 'expected_type', 'INTEGER', 'pipeline-lead'),
    ('DNA', 'ACCT', 'ACCTNBR', 'nullability', 'NOT NULL', 'pipeline-lead'),
    ('DNA', 'ACCT', 'ACCTNBR', 'is_pii', 'true', 'pipeline-lead'),
    ('DNA', 'ACCT', 'ACCTNBR', 'pii_type', 'ACCOUNT', 'pipeline-lead'),
    -- Source's expected change notification: 14 days before breaking changes
    ('DNA', 'ACCT', NULL, 'change_notification_sla_days', '14', 'pipeline-lead');
```

**Storage forecast**: ~5K rows lifetime (per-table per-column contracts × small number of contract keys). **<5 MB**.

**Edge cases addressed**: S6 (source date column semantic drift), E-16 (source type drift detection).

---

## 24. `OrphanedTokenLog` (NEW v2)

**v2 fix per ROUND_1_REVIEW.md**: P2 ("vault row deletion makes existing tokens unrecoverable") was the only 🔴 in P-series with no schema affordance. When `PiiVault.Status` flips to `'deleted_per_request'` or `'purged_for_retention'`, downstream Bronze rows still hold the token but can no longer decrypt it. Without a log, we have no record of what tokens were orphaned, what tables hold them, or what to communicate to consumers/auditors.

**Purpose**: append-only audit of vault status flips and the downstream tables / row counts still referencing the orphaned tokens at the time of orphaning.

**Decisions addressed**: D30 (retention), D6 (vault), supports P2 mitigation.

```sql
CREATE TABLE General.ops.OrphanedTokenLog (
    OrphanLogId          BIGINT IDENTITY(1,1) NOT NULL,
    Token                VARCHAR(40)     NOT NULL,
    OrphanedAt           DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
    OrphanReason         NVARCHAR(50)    NOT NULL,
                                  -- 'ccpa_deletion'
                                  -- 'retention_purge'
                                  -- 'manual_override'
                                  -- 'legal_hold_release'
    OrphanReference      NVARCHAR(255)   NULL,    -- e.g., CCPA RequestId, retention BatchId
    
    -- Snapshot of downstream impact at time of orphaning
    DownstreamSummary    NVARCHAR(MAX)   NULL,    -- JSON: 
                                                  -- [{"db":"UDM_Bronze","schema":"DNA","table":"ACCT","column":"SSN","row_count":1247}, ...]
    TotalDownstreamRows  BIGINT          NULL,
    
    NotificationSent     BIT             NOT NULL DEFAULT 0,
    NotifiedAt           DATETIME2(3)    NULL,
    NotifiedTo           NVARCHAR(MAX)   NULL,    -- JSON list of consumer teams
    
    Status               NVARCHAR(20)    NOT NULL DEFAULT 'logged',
                                  -- 'logged'        — recorded, no further action
                                  -- 'notified'      — consumers notified
                                  -- 'scrubbed'      — downstream rows scrubbed (advanced; per consumer policy)
    
    CONSTRAINT PK_OrphanedTokenLog PRIMARY KEY CLUSTERED (OrphanLogId),
    CONSTRAINT FK_OrphanedTokenLog_Vault FOREIGN KEY (Token) 
        REFERENCES General.ops.PiiVault(Token),
    CONSTRAINT CK_OrphanedTokenLog_Reason CHECK 
        (OrphanReason IN ('ccpa_deletion', 'retention_purge', 
                          'manual_override', 'legal_hold_release')),
    CONSTRAINT CK_OrphanedTokenLog_Status CHECK 
        (Status IN ('logged', 'notified', 'scrubbed'))
);

-- Token lookup
CREATE INDEX IX_OrphanedTokenLog_Token 
    ON General.ops.OrphanedTokenLog (Token);

-- Recent orphans (operational dashboard)
CREATE INDEX IX_OrphanedTokenLog_Recent 
    ON General.ops.OrphanedTokenLog (OrphanedAt DESC)
    INCLUDE (OrphanReason, Status);

-- Pending notifications
CREATE INDEX IX_OrphanedTokenLog_PendingNotification 
    ON General.ops.OrphanedTokenLog (Status, OrphanedAt)
    WHERE Status = 'logged';
```

**How it gets populated**: a trigger on `PiiVault` Status change INSERTs into this table, OR the SP-10 `EnforceRetention` and the CCPA deletion SP write to this table when they flip vault Status. Recommend: explicit SP-write in retention/deletion procs (more controllable than triggers).

**Storage forecast**: ~50K rows over 7 years (one row per token orphaned event). **<25 MB**.

**Edge cases addressed**: P2 (vault deletion makes tokens unrecoverable), V8 (GDPR right-to-erasure cascade).

---

# Stored procedures

## SP-1: `PiiVault_GetOrCreateToken` (atomic, race-condition-safe)

**v2 fix per ROUND_1_REVIEW.md**: original lookup-then-INSERT had I3 race condition (two callers with same plaintext both miss SELECT, both INSERT, second violates UNIQUE). Rewritten with `UPDLOCK + HOLDLOCK` to serialize concurrent callers through the read, plus defensive try/catch on UNIQUE violation.

```sql
CREATE PROCEDURE General.ops.PiiVault_GetOrCreateToken
    @Plaintext NVARCHAR(MAX),
    @PiiType   NVARCHAR(20),
    @SourceName NVARCHAR(50),
    @Token VARCHAR(40) OUTPUT,
    @WasNew BIT OUTPUT
WITH SCHEMABINDING, EXECUTE AS OWNER
AS
BEGIN
    SET NOCOUNT ON;
    SET @WasNew = 0;
    SET @Token = NULL;
    
    DECLARE @hash VARBINARY(32) = HASHBYTES('SHA2_256', @Plaintext);
    
    -- Idempotent lookup with UPDLOCK + HOLDLOCK.
    -- UPDLOCK promotes the read lock to update-intent — concurrent callers
    -- serialize at this point. HOLDLOCK extends to range-locking semantics
    -- against the unique index, preventing phantom INSERTs in the gap.
    -- Combined effect: another caller seeing the same hash will block here
    -- until our transaction commits, then their SELECT will find our row.
    SELECT @Token = Token 
    FROM General.ops.PiiVault WITH (UPDLOCK, HOLDLOCK)
    WHERE PiiType = @PiiType 
      AND SourceName = @SourceName 
      AND PlaintextHash = @hash
      AND Status = 'active';
    
    IF @Token IS NOT NULL
    BEGIN
        -- Bump access tracking; idempotent token return
        UPDATE General.ops.PiiVault
        SET LastAccessedAt = SYSUTCDATETIME(),
            AccessCount = AccessCount + 1
        WHERE Token = @Token;
        RETURN;
    END;
    
    -- Not found — generate new token and INSERT.
    -- The UPDLOCK held above guarantees no concurrent caller can have
    -- committed an INSERT with our hash between our SELECT and this INSERT.
    SET @Token = CONVERT(VARCHAR(40), NEWID());
    
    BEGIN TRY
        INSERT INTO General.ops.PiiVault 
            (Token, PiiType, SourceName, PlaintextValue, PlaintextHash,
             EncryptionVersion, RetentionExpiresAt)
        VALUES 
            (@Token, @PiiType, @SourceName, @Plaintext, @hash,
             1,  -- D7 future-proof: track encryption scheme version
             DATEADD(year, 7, SYSUTCDATETIME()));
        SET @WasNew = 1;
    END TRY
    BEGIN CATCH
        -- Defensive catch: if UNIQUE violation despite UPDLOCK (shouldn't
        -- happen but defense-in-depth), re-lookup; the other caller's token wins.
        IF ERROR_NUMBER() IN (2627, 2601)  -- UNIQUE / duplicate key violation
        BEGIN
            SELECT @Token = Token 
            FROM General.ops.PiiVault
            WHERE PiiType = @PiiType 
              AND SourceName = @SourceName 
              AND PlaintextHash = @hash
              AND Status = 'active';
            SET @WasNew = 0;
            
            IF @Token IS NULL
            BEGIN
                -- Catastrophic: UNIQUE fired but row is gone. Re-raise.
                THROW;
            END;
        END
        ELSE
        BEGIN
            THROW;  -- re-raise non-UNIQUE errors
        END;
    END CATCH;
END;
```

**Edge cases addressed**: I3-vault (concurrent same-key INSERT — atomic via UPDLOCK + HOLDLOCK), P1 (deterministic encryption — same plaintext returns same token), P9 (cross-source isolation via SourceName in lookup index).

**Status interaction (per D45.6 v3 + UX_PiiVault_Lookup filtered index)**: SP-1 lookup matches only `Status = 'active'` rows. Plaintexts whose only vault row has `Status IN ('deleted_per_request', 'purged_for_retention')` will mint fresh active tokens — by design, allowing re-tokenization after retention purge. **Plaintexts whose only vault row has `Status = 'legal_hold_only'` ALSO mint fresh active tokens**: legal-hold rows are preserved separately for litigation per D30, while operational tokenization continues unaffected. Auditor's `IX_PiiVault_HistoricalLookup` query returns both rows for full lineage.

**Three-way race acknowledgment**: the catch block's `THROW` at the end can fire under a benign three-way race (caller A inserts active row, retention/CCPA SP flips Status to non-active, caller B's catch re-lookup with `Status='active'` returns NULL). Failure mode is loud (operator-visible error), not silent corruption. Astronomically rare under realistic load; acceptable.

**Test invariants** (Tier 1 + Tier 3):
- Single-caller correctness: same plaintext → same token across calls
- Concurrent invocation: 4 callers in parallel with same plaintext → exactly one INSERT, all return same token
- Cross-source: same plaintext from DNA vs CCM → distinct tokens
- High-volume: 10K calls in serial complete within reasonable time (UPDLOCK doesn't deadlock under realistic load)

## SP-2: `PiiVault_Decrypt` (audit-logged)

```sql
CREATE PROCEDURE General.ops.PiiVault_Decrypt
    @RequestId UNIQUEIDENTIFIER,
    @Token VARCHAR(40),
    @Justification NVARCHAR(MAX)
WITH EXECUTE AS OWNER
AS
BEGIN
    SET NOCOUNT ON;
    
    -- Audit row before returning plaintext
    INSERT INTO General.ops.PiiVaultAccessLog
        (RequestId, AccessedBy, AccessRole, Token, Justification,
         AccessSourceIp, AccessApplication)
    VALUES
        (@RequestId, SYSTEM_USER, 
         (SELECT TOP 1 r.name FROM sys.user_token t 
          JOIN sys.database_principals r ON t.principal_id = r.principal_id 
          WHERE r.type = 'R'),
         @Token, @Justification,
         CONVERT(NVARCHAR(45), CONNECTIONPROPERTY('client_net_address')),
         APP_NAME());
    
    -- Update LastAccessedAt + AccessCount
    UPDATE General.ops.PiiVault
    SET LastAccessedAt = SYSUTCDATETIME(),
        AccessCount = AccessCount + 1
    WHERE Token = @Token;
    
    -- Return plaintext (only for active tokens)
    SELECT Token, PlaintextValue
    FROM General.ops.PiiVault
    WHERE Token = @Token AND Status IN ('active', 'legal_hold_only');
END;
```

## SP-3: `PipelineExecutionGate_AcquireProd`

**v2 fix**: was placeholder pointing at RB-9; now fully inlined.

Acquires the gate for production pipeline execution. Generates a fresh BatchId, sets gate Status='STARTING', and seeds heartbeat. Atomic via `sp_getapplock` on the cycle key.

```sql
CREATE PROCEDURE General.ops.PipelineExecutionGate_AcquireProd
    @CycleType NVARCHAR(10),  -- 'AM' or 'PM'
    @CycleDate DATE,
    @ExpectedStartTime DATETIME2(3),
    @GateId BIGINT OUTPUT,
    @BatchId BIGINT OUTPUT
WITH EXECUTE AS OWNER
AS
BEGIN
    SET NOCOUNT ON;
    
    DECLARE @lock_resource NVARCHAR(255) = 
        N'pipeline_gate_' + @CycleType + '_' + CONVERT(VARCHAR(10), @CycleDate, 23);
    DECLARE @lock_result INT;
    
    -- Atomic gate claim
    EXEC @lock_result = sp_getapplock
        @Resource = @lock_resource,
        @LockMode = 'Exclusive',
        @LockOwner = 'Session',
        @LockTimeout = 5000;
    
    IF @lock_result < 0
    BEGIN
        RAISERROR('Gate lock could not be acquired for %s/%s', 16, 1, @CycleType, @CycleDate);
        RETURN;
    END;
    
    BEGIN TRY
        -- Generate a new BatchId
        SET @BatchId = NEXT VALUE FOR General.ops.PipelineBatchSequence;
        
        -- INSERT or UPDATE the gate
        MERGE General.ops.PipelineExecutionGate AS target
        USING (SELECT @CycleType AS CycleType, @CycleDate AS CycleDate) AS src
        ON target.CycleType = src.CycleType AND target.CycleDate = src.CycleDate
        WHEN MATCHED AND target.Status IN ('PENDING', 'FAILED', 'TIMEOUT', 'CANCELLED') THEN
            UPDATE SET ExecutingServer = 'production',
                       Status = 'STARTING',
                       ActualStartTime = SYSUTCDATETIME(),
                       BatchId = @BatchId,
                       LastHeartbeatAt = SYSUTCDATETIME(),
                       FailureReason = NULL,
                       CancellationRequested = 0,
                       CancellationRequestedAt = NULL,
                       CancellationRequestedBy = NULL,
                       CancellationReason = NULL,
                       CancellationAcknowledgedAt = NULL
        WHEN MATCHED AND target.Status IN ('STARTING', 'RUNNING', 'SUCCEEDED') THEN
            -- Cycle already in progress or done — do not clobber
            UPDATE SET LastHeartbeatAt = target.LastHeartbeatAt  -- no-op
        WHEN NOT MATCHED THEN
            INSERT (CycleType, CycleDate, ExpectedStartTime, ActualStartTime, ExecutingServer,
                    Status, BatchId, LastHeartbeatAt)
            VALUES (@CycleType, @CycleDate, @ExpectedStartTime, SYSUTCDATETIME(),
                    'production', 'STARTING', @BatchId, SYSUTCDATETIME());
        
        -- Capture the GateId of the row we touched
        SELECT @GateId = GateId 
        FROM General.ops.PipelineExecutionGate
        WHERE CycleType = @CycleType AND CycleDate = @CycleDate;
        
        EXEC sp_releaseapplock @Resource = @lock_resource;
    END TRY
    BEGIN CATCH
        EXEC sp_releaseapplock @Resource = @lock_resource;
        THROW;
    END CATCH;
END;
```

**Edge cases addressed**: F4 (failover claims gate during prod recovery — guarded by sp_getapplock), F20 (two prod processes — second blocks on lock).

---

## SP-4: `PipelineExecutionGate_AcquireTest`

**v2 fix**: full body inlined.

Test pipeline gate-check. Returns one of three actions: 'EXIT_SUCCEEDED' (prod handled it), 'EXIT_RUNNING_HEALTHY' (prod still running with recent heartbeat), or 'PROCEED_FAILOVER' (prod failed/timed-out/never-started, claim gate as test).

```sql
CREATE PROCEDURE General.ops.PipelineExecutionGate_AcquireTest
    @CycleType NVARCHAR(10),
    @CycleDate DATE,
    @ExpectedStartTime DATETIME2(3),
    @HeartbeatStaleMinutes INT = 10,
    @ProdMaxRuntimeMinutes INT = 120,
    @GateId BIGINT OUTPUT,
    @BatchId BIGINT OUTPUT,
    @Action NVARCHAR(30) OUTPUT  -- 'EXIT_SUCCEEDED' | 'EXIT_RUNNING_HEALTHY' | 'PROCEED_FAILOVER'
WITH EXECUTE AS OWNER
AS
BEGIN
    SET NOCOUNT ON;
    
    DECLARE @lock_resource NVARCHAR(255) = 
        N'pipeline_gate_' + @CycleType + '_' + CONVERT(VARCHAR(10), @CycleDate, 23);
    DECLARE @lock_result INT;
    DECLARE @status NVARCHAR(20);
    DECLARE @start DATETIME2(3);
    DECLARE @heartbeat DATETIME2(3);
    DECLARE @existing_gate_id BIGINT;
    
    EXEC @lock_result = sp_getapplock
        @Resource = @lock_resource,
        @LockMode = 'Exclusive',
        @LockOwner = 'Session',
        @LockTimeout = 5000;
    
    IF @lock_result < 0
    BEGIN
        RAISERROR('Gate lock could not be acquired for test failover check', 16, 1);
        RETURN;
    END;
    
    BEGIN TRY
        SELECT @existing_gate_id = GateId,
               @status = Status,
               @start = ActualStartTime,
               @heartbeat = LastHeartbeatAt
        FROM General.ops.PipelineExecutionGate
        WHERE CycleType = @CycleType AND CycleDate = @CycleDate;
        
        -- Decision tree (precedence: SUCCEEDED > healthy RUNNING > failover)
        IF @status = 'SUCCEEDED'
        BEGIN
            SET @Action = 'EXIT_SUCCEEDED';
            SET @GateId = @existing_gate_id;
            SET @BatchId = NULL;
            EXEC sp_releaseapplock @Resource = @lock_resource;
            RETURN;
        END;
        
        IF @status = 'RUNNING' 
           AND DATEDIFF(MINUTE, @heartbeat, SYSUTCDATETIME()) < @HeartbeatStaleMinutes
           AND DATEDIFF(MINUTE, @start, SYSUTCDATETIME()) < @ProdMaxRuntimeMinutes
        BEGIN
            -- Prod is healthy — test exits cleanly
            SET @Action = 'EXIT_RUNNING_HEALTHY';
            SET @GateId = @existing_gate_id;
            SET @BatchId = NULL;
            EXEC sp_releaseapplock @Resource = @lock_resource;
            RETURN;
        END;
        
        -- Failover: prod failed, timed out, never started, stale heartbeat, or runtime exceeded
        SET @BatchId = NEXT VALUE FOR General.ops.PipelineBatchSequence;
        
        MERGE General.ops.PipelineExecutionGate AS target
        USING (SELECT @CycleType AS CycleType, @CycleDate AS CycleDate) AS src
        ON target.CycleType = src.CycleType AND target.CycleDate = src.CycleDate
        WHEN MATCHED THEN
            UPDATE SET ExecutingServer = 'test',
                       Status = 'STARTING',
                       ActualStartTime = SYSUTCDATETIME(),
                       BatchId = @BatchId,
                       LastHeartbeatAt = SYSUTCDATETIME(),
                       FailureReason = 
                          'Auto-failover: prod ' + ISNULL(@status, 'NEVER_STARTED') 
                          + COALESCE('; last heartbeat ' 
                                + CONVERT(VARCHAR(30), @heartbeat, 121), '')
        WHEN NOT MATCHED THEN
            INSERT (CycleType, CycleDate, ExpectedStartTime, ActualStartTime, ExecutingServer,
                    Status, BatchId, LastHeartbeatAt, FailureReason)
            VALUES (@CycleType, @CycleDate, @ExpectedStartTime, SYSUTCDATETIME(),
                    'test', 'STARTING', @BatchId, SYSUTCDATETIME(),
                    'Auto-failover: prod NEVER_STARTED');
        
        SELECT @GateId = GateId 
        FROM General.ops.PipelineExecutionGate
        WHERE CycleType = @CycleType AND CycleDate = @CycleDate;
        
        SET @Action = 'PROCEED_FAILOVER';
        
        -- Audit event
        INSERT INTO General.ops.PipelineEventLog
            (BatchId, EventType, EventDetail, StartedAt, CompletedAt, 
             Status, Metadata, CycleType, CycleDate, ServerRole)
        VALUES
            (@BatchId, 'FAILOVER_TRIGGERED',
             'cycle=' + @CycleType + ' date=' + CONVERT(VARCHAR(10), @CycleDate, 23),
             SYSUTCDATETIME(), SYSUTCDATETIME(),
             'SUCCESS',
             '{"prior_status":"' + ISNULL(@status, 'NEVER_STARTED') + '"}',
             @CycleType, @CycleDate, 'test');
        
        EXEC sp_releaseapplock @Resource = @lock_resource;
    END TRY
    BEGIN CATCH
        EXEC sp_releaseapplock @Resource = @lock_resource;
        THROW;
    END CATCH;
END;
```

**Edge cases addressed**: F3 (slow-but-successful prod), F4 (failover during prod recovery), F15 (prod stuck), F18 (prod completes between cancellation and timeout).

---

## SP-5: `PipelineExecutionGate_RequestCancellation`

**v2 fix**: full body inlined.

Sets the cancellation flag on the gate. Test pipeline calls this when it determines failover is needed. Production pipeline reads the flag at every heartbeat.

```sql
CREATE PROCEDURE General.ops.PipelineExecutionGate_RequestCancellation
    @CycleType NVARCHAR(10),
    @CycleDate DATE,
    @RequestedBy NVARCHAR(50),
    @Reason NVARCHAR(MAX)
WITH EXECUTE AS OWNER
AS
BEGIN
    SET NOCOUNT ON;
    
    DECLARE @lock_resource NVARCHAR(255) = 
        N'pipeline_gate_' + @CycleType + '_' + CONVERT(VARCHAR(10), @CycleDate, 23);
    DECLARE @lock_result INT;
    
    EXEC @lock_result = sp_getapplock
        @Resource = @lock_resource,
        @LockMode = 'Exclusive',
        @LockOwner = 'Session',
        @LockTimeout = 5000;
    
    IF @lock_result < 0
    BEGIN
        RAISERROR('Gate lock could not be acquired for cancellation request', 16, 1);
        RETURN;
    END;
    
    BEGIN TRY
        UPDATE General.ops.PipelineExecutionGate
        SET CancellationRequested = 1,
            CancellationRequestedAt = SYSUTCDATETIME(),
            CancellationRequestedBy = @RequestedBy,
            CancellationReason = @Reason
        WHERE CycleType = @CycleType 
          AND CycleDate = @CycleDate
          AND Status IN ('STARTING', 'RUNNING')
          AND CancellationRequested = 0;  -- idempotent: don't re-request
        
        EXEC sp_releaseapplock @Resource = @lock_resource;
    END TRY
    BEGIN CATCH
        EXEC sp_releaseapplock @Resource = @lock_resource;
        THROW;
    END CATCH;
END;
```

**Edge cases addressed**: F15 (prod stuck), F19 (cancellation flag stuck — idempotency clause guards).

---

## SP-6: `PipelineExecutionGate_AcknowledgeCancellation`

**v2 fix**: full body inlined.

Production pipeline calls this when graceful shutdown completes. Confirms acknowledgment to test pipeline.

```sql
CREATE PROCEDURE General.ops.PipelineExecutionGate_AcknowledgeCancellation
    @GateId BIGINT
WITH EXECUTE AS OWNER
AS
BEGIN
    SET NOCOUNT ON;
    
    UPDATE General.ops.PipelineExecutionGate
    SET Status = 'CANCELLED',
        CancellationAcknowledgedAt = SYSUTCDATETIME(),
        ActualCompletionTime = SYSUTCDATETIME()
    WHERE GateId = @GateId
      AND CancellationRequested = 1
      AND CancellationAcknowledgedAt IS NULL;  -- idempotent
END;
```

**Edge cases addressed**: F15-F18 (cancellation flow completion).

## SP-7: `IdempotencyLedger_StartStep`

```sql
CREATE PROCEDURE General.ops.IdempotencyLedger_StartStep
    @BatchId BIGINT,
    @SourceName NVARCHAR(50),
    @TableName NVARCHAR(255),
    @EventType NVARCHAR(50),
    @Action NVARCHAR(20) OUTPUT  -- 'PROCEED' or 'SHORT_CIRCUIT'
WITH EXECUTE AS OWNER
AS
BEGIN
    SET NOCOUNT ON;
    
    DECLARE @existing_status NVARCHAR(20) = NULL;
    
    SELECT @existing_status = Status
    FROM General.ops.IdempotencyLedger
    WHERE BatchId = @BatchId
      AND SourceName = @SourceName
      AND TableName = @TableName
      AND EventType = @EventType;
    
    IF @existing_status = 'COMPLETED'
    BEGIN
        SET @Action = 'SHORT_CIRCUIT';
        RETURN;
    END;
    
    IF @existing_status IS NULL
    BEGIN
        BEGIN TRY
            INSERT INTO General.ops.IdempotencyLedger
                (BatchId, SourceName, TableName, EventType, Status, StartedAt)
            VALUES
                (@BatchId, @SourceName, @TableName, @EventType, 'IN_PROGRESS', SYSUTCDATETIME());
            SET @Action = 'PROCEED';
        END TRY
        BEGIN CATCH
            -- Concurrent INSERT attempt — second loser
            IF ERROR_NUMBER() = 2627  -- UNIQUE constraint violation
            BEGIN
                SET @Action = 'SHORT_CIRCUIT';
            END
            ELSE
            BEGIN
                THROW;
            END;
        END CATCH;
    END
    ELSE
    BEGIN
        -- IN_PROGRESS or FAILED — proceed; calling code may retry
        SET @Action = 'PROCEED';
        UPDATE General.ops.IdempotencyLedger
        SET Status = 'IN_PROGRESS',
            StartedAt = SYSUTCDATETIME()
        WHERE BatchId = @BatchId
          AND SourceName = @SourceName
          AND TableName = @TableName
          AND EventType = @EventType;
    END;
END;
```

## SP-8: `IdempotencyLedger_CompleteStep`

```sql
CREATE PROCEDURE General.ops.IdempotencyLedger_CompleteStep
    @BatchId BIGINT,
    @SourceName NVARCHAR(50),
    @TableName NVARCHAR(255),
    @EventType NVARCHAR(50),
    @Status NVARCHAR(20),  -- 'COMPLETED' or 'FAILED'
    @ErrorMessage NVARCHAR(MAX) = NULL
WITH EXECUTE AS OWNER
AS
BEGIN
    SET NOCOUNT ON;
    
    UPDATE General.ops.IdempotencyLedger
    SET Status = @Status,
        CompletedAt = SYSUTCDATETIME(),
        DurationMs = DATEDIFF(MILLISECOND, StartedAt, SYSUTCDATETIME()),
        ErrorMessage = @ErrorMessage
    WHERE BatchId = @BatchId
      AND SourceName = @SourceName
      AND TableName = @TableName
      AND EventType = @EventType;
END;
```

## SP-9: `IdempotencyLedger_RecoveryStartupSweep`

```sql
CREATE PROCEDURE General.ops.IdempotencyLedger_RecoveryStartupSweep
    @MaxAgeHours INT = 4
WITH EXECUTE AS OWNER
AS
BEGIN
    SET NOCOUNT ON;
    
    UPDATE General.ops.IdempotencyLedger
    SET Status = 'FAILED',
        CompletedAt = SYSUTCDATETIME(),
        ErrorMessage = 'Stale IN_PROGRESS — recovered at startup',
        RecoveryAction = 'STARTUP_SWEEP_FAILED'
    WHERE Status = 'IN_PROGRESS'
      AND StartedAt < DATEADD(HOUR, -@MaxAgeHours, SYSUTCDATETIME());
    
    SELECT @@ROWCOUNT AS RowsRecovered;
END;
```

## SP-11: `PipelineLog_ExtendPartition` (NEW v2)

**v2 fix**: addresses ROUND_1_REVIEW finding that PartitionFunction values stop at 2026-12-01. Without monthly extension, PipelineLog INSERTs will silently fail at end of 2026.

Extends the partition function ahead of time. Runs as a SQL Agent job monthly.

```sql
CREATE PROCEDURE General.ops.PipelineLog_ExtendPartition
    @MonthsAhead INT = 6
WITH EXECUTE AS OWNER
AS
BEGIN
    SET NOCOUNT ON;
    
    DECLARE @last_partition DATE;
    DECLARE @target_date DATE = DATEADD(MONTH, @MonthsAhead, CAST(SYSUTCDATETIME() AS DATE));
    DECLARE @next_partition DATE;
    DECLARE @partitions_created INT = 0;
    
    -- Find the latest partition boundary
    SELECT @last_partition = MAX(CAST(prv.value AS DATE))
    FROM sys.partition_functions pf
    JOIN sys.partition_range_values prv 
        ON pf.function_id = prv.function_id
    WHERE pf.name = 'pf_PipelineLog_Monthly';
    
    IF @last_partition IS NULL
    BEGIN
        RAISERROR('Partition function pf_PipelineLog_Monthly not found', 16, 1);
        RETURN;
    END;
    
    -- Add monthly boundaries up to target
    SET @next_partition = DATEADD(MONTH, 1, @last_partition);
    
    WHILE @next_partition <= @target_date
    BEGIN
        ALTER PARTITION SCHEME ps_PipelineLog_Monthly NEXT USED [PRIMARY];
        ALTER PARTITION FUNCTION pf_PipelineLog_Monthly()
            SPLIT RANGE (@next_partition);
        
        SET @next_partition = DATEADD(MONTH, 1, @next_partition);
        SET @partitions_created = @partitions_created + 1;
    END;
    
    -- Audit
    INSERT INTO General.ops.PipelineEventLog
        (BatchId, EventType, EventDetail, StartedAt, CompletedAt, Status, Metadata)
    VALUES
        (NEXT VALUE FOR General.ops.PipelineBatchSequence,
         'PARTITION_EXTENSION',
         'pf_PipelineLog_Monthly extended to ' 
            + CONVERT(VARCHAR(10), DATEADD(MONTH, -1, @next_partition), 23),
         SYSUTCDATETIME(), SYSUTCDATETIME(),
         'SUCCESS',
         '{"partitions_created":' + CAST(@partitions_created AS VARCHAR(10)) 
            + ',"target_date":"' + CONVERT(VARCHAR(10), @target_date, 23) + '"}');
END;
```

**Schedule**: SQL Agent job runs first day of each month, calls this proc with `@MonthsAhead=6` (always have 6 months of partition headroom).

**SQL Agent job DDL** (deployment requirement, not table DDL):

```sql
-- Run on the SQL Server instance hosting General database
USE msdb;
GO
EXEC dbo.sp_add_job
    @job_name = N'UDM_PipelineLog_ExtendPartition_Monthly',
    @description = N'Monthly partition function extension for PipelineLog (D45.2)',
    @enabled = 1,
    @owner_login_name = N'sa';   -- B02: explicit owner; DBA replaces with canonical service account at deployment (sa is fail-safe default that exists on every SQL Server instance)

EXEC dbo.sp_add_jobstep
    @job_name = N'UDM_PipelineLog_ExtendPartition_Monthly',
    @step_name = N'Extend partition',
    @subsystem = N'TSQL',
    @command = N'EXEC General.ops.PipelineLog_ExtendPartition @MonthsAhead = 6;',
    @database_name = N'General';

EXEC dbo.sp_add_schedule
    @schedule_name = N'Monthly_FirstDayUTC',
    @freq_type = 16,                 -- monthly
    @freq_interval = 1,              -- first day of month
    @freq_recurrence_factor = 1,     -- B02: every 1 month (required for @freq_type=16; defaults to 0 which is invalid for monthly schedules)
    @active_start_time = 020000;     -- 02:00 UTC

EXEC dbo.sp_attach_schedule
    @job_name = N'UDM_PipelineLog_ExtendPartition_Monthly',
    @schedule_name = N'Monthly_FirstDayUTC';
```

**B02 fix landed 2026-05-12** (additive per D92 forward-only): two msdb-DDL parameters that were missing from the original Round 1 v2 spec — `@owner_login_name` on `sp_add_job` (without it, ownership defaults to the calling-session login → non-portable across deployments) and `@freq_recurrence_factor` on `sp_add_schedule` (without it, monthly schedule with `@freq_type=16` defaults `factor=0` which is invalid). Both parameters are deployment-required; `sa` placeholder for the login is conservative-safe (always exists on every SQL Server instance) — DBA replaces with the canonical service account login (e.g., `sql_agent_proxy` or similar) at per-server deployment time. No SchemaContract row needed (msdb deployment artifact, not General-database schema object).

**Edge cases addressed**: M1 (cold-start partition setup), prevents the time-bomb identified in ROUND_1_REVIEW.

**Round 4 (Tools) deliverable**: a Python wrapper `tools/extend_partitions.py` for operators who can't trigger SQL Agent jobs directly.

---

## SP-10: `EnforceRetention`

```sql
CREATE PROCEDURE General.ops.EnforceRetention
    @DryRun BIT = 1
WITH EXECUTE AS OWNER
AS
BEGIN
    SET NOCOUNT ON;
    
    DECLARE @Affected BIGINT = 0;
    
    IF @DryRun = 1
    BEGIN
        SELECT COUNT(*) AS WouldBeFlipped
        FROM General.ops.PiiVault
        WHERE RetentionExpiresAt < SYSUTCDATETIME()
          AND LegalHold = 0
          AND Status = 'active';
    END
    ELSE
    BEGIN
        UPDATE General.ops.PiiVault
        SET Status = 'purged_for_retention',
            StatusReason = '7-year retention expired (D30)',
            StatusChangedAt = SYSUTCDATETIME(),
            StatusChangedBy = 'retention_job'
        WHERE RetentionExpiresAt < SYSUTCDATETIME()
          AND LegalHold = 0
          AND Status = 'active';
        SET @Affected = @@ROWCOUNT;
        
        SELECT @Affected AS Flipped;
    END;
END;
```

---

# Edge case → DDL feature mapping

| Edge case | DDL feature that addresses it |
|---|---|
| I1 (same BatchId retry) | Ledger UNIQUE on (BatchId, Source, Table, EventType) + SP-7 short-circuit logic |
| I3 (concurrent same-batch) — ledger | Ledger UNIQUE constraint; SP-7 catches violation |
| I3 (concurrent same-key) — vault | **v2 fix**: SP-1 uses UPDLOCK + HOLDLOCK serialization + try/catch on UNIQUE violation |
| I3 (same batch tokenized twice) — tokenization summary | **v2 fix**: UX_PiiTokenizationBatch_Identity UNIQUE on (BatchId, Source, Object, Column) |
| I4 (BCP partial-write) | ParquetSnapshotRegistry UNIQUE on identity; SP for register ensures atomicity |
| I13 (snapshot re-INSERT) | UX_ParquetSnapshotRegistry_Identity rejects duplicates |
| I19 (stale IN_PROGRESS) | SP-9 startup sweep; IX_IdempotencyLedger_Stuck filtered index |
| F4 (failover claims gate during prod recovery) | Gate UNIQUE on (CycleType, CycleDate); sp_getapplock at app layer |
| F11 (forgotten cutback) | PromotionLock.Active computed column with filtered UNIQUE index |
| F14 (maintenance window) | MaintenanceWindow.IX_Active for fast suppression check |
| F15-F19 (cancellation flow) | PipelineExecutionGate cancellation columns + status state machine |
| V1 (same plaintext, multiple columns) | PiiTokenProvenance allows multiple rows per Token |
| V2 (per-source isolation) | PiiVault UX_Lookup includes SourceName |
| V3 (provenance volume) | Clustered columnstore index CCI_PiiTokenProvenance |
| P1 (deterministic encryption) | PiiVault PlaintextHash + atomic GET-OR-CREATE in SP-1 (v2: UPDLOCK + HOLDLOCK) |
| P2 (vault row deletion orphans downstream tokens) | **v2 fix**: new `OrphanedTokenLog` table (table 24) + FK to vault; retention/CCPA SPs write here on every Status flip with downstream impact summary |
| P3 (vault corruption) | TDE + DENY DELETE permission + nightly backup (operational) |
| P5 (plaintext leak in logs) | PipelineLog at app layer; sensitive_data_filter (Phase 1 module) |
| P7 (right-to-erasure) | Status='deleted_per_request' + CcpaDeletionLog audit |
| P8 (decrypt audit) | PiiVaultAccessLog + SP-2 always logs |
| G7 (FirstLoadDate excluded gaps) | Gap detector reads from UdmTablesList (existing) — outside this schema |
| M1 (zero late arrivals) | LatenessProfile per-table; floor in app code |
| M9 (L_99 drift) | LatenessProfile.PreviousP99 + DriftPct |
| S2 (B-4 orphan cleanup) | Bronze (existing schema); covered by SCD2 engine + this schema's SCD2RepairLog |
| S14 (reconciliation findings) | ReconciliationLog.Acknowledged required before next run (app-layer enforcement) |

---

# Storage forecast (consolidated)

| Table | Estimated rows (7y) | Avg row | Storage (rowstore) | Storage (with compression) |
|---|---|---|---|---|
| PipelineEventLog | 50M | 500 B | 25 GB | 5-8 GB (PAGE) |
| PipelineLog | 5B | 300 B | 1.5 TB | 150-250 GB (CCI) |
| PipelineExtraction | 500K | 200 B | 100 MB | 50 MB |
| PipelineExecutionGate | 5K | 600 B | 3 MB | trivial |
| PromotionLock | 100 | 500 B | trivial | trivial |
| MaintenanceWindow | 500 | 500 B | trivial | trivial |
| IdempotencyLedger | 50M | 250 B | 12 GB | 3-5 GB |
| ParquetSnapshotRegistry | 10M | 1 KB | 10 GB | 5-8 GB |
| ExtractionRangePolicy | 500 | 300 B | trivial | trivial |
| LatenessProfile | 5K | 300 B | trivial | trivial |
| DeleteEvaluationAudit | 5M | 200 B | 1 GB | 500 MB |
| ExtractionGapLog | 1K | 500 B | trivial | trivial |
| ManualCorrectionLog | 500 | 1 KB | trivial | trivial |
| ReconciliationLog | 50K | 2 KB | 100 MB | 50 MB |
| SCD2RepairLog | 5K | 1 KB | 5 MB | trivial |
| PiiVault | 50M | 300 B | 15 GB | 5-8 GB |
| PiiTokenProvenance | 250M | 400 B | 100 GB | 12-15 GB (CCI) |
| PiiTokenizationBatch | 1.3M | 200 B | 250 MB | 100 MB |
| PiiVaultAccessLog | 500K | 500 B | 250 MB | 100 MB |
| CcpaDeletionLog | 5K | 1 KB | 5 MB | trivial |
| TableEnablementLog | 500 | 500 B | trivial | trivial |
| HealthCheckLog | 10M | 500 B | 5 GB | 2 GB |
| **SchemaContract** (NEW v2) | 5K | 1 KB | 5 MB | trivial |
| **OrphanedTokenLog** (NEW v2) | 50K | 500 B | 25 MB | 15 MB |
| **Total** | **~6.4B rows** | | **~1.7 TB** | **~190-300 GB** |

The PipelineLog dominates at 90%+ of total storage; CCI compression and partition-based retention purge are essential.

---

# DBA review checklist

- [ ] Schema name `ops` agreed and authorized
- [ ] TDE enabled on `General` database
- [ ] DELETE permission denied to all roles for audit tables (PiiVault, PiiVaultAccessLog, CcpaDeletionLog, ManualCorrectionLog, PiiTokenProvenance, PiiTokenizationBatch, DeleteEvaluationAudit, ExtractionGapLog, ReconciliationLog, SCD2RepairLog, TableEnablementLog, **OrphanedTokenLog (v2)**, **SchemaContract (v2)**)
- [ ] PiiVault DELETE policy: vault rows are NEVER physically DELETEd; Status column flips for retention / CCPA deletion / legal hold (per D30, D45.6 v2)
- [ ] `PipelineLog_ExtendPartition` SQL Agent job created with monthly schedule (per SP-11, **v2**)
- [ ] `PiiVault.EncryptionVersion` defaults to 1 for all initial inserts (D7 future-proof, **v2**)
- [ ] `PiiTokenizationBatch.UX_PiiTokenizationBatch_Identity` UNIQUE constraint reviewed (**v2**)
- [ ] `PiiVaultAccessLog.FK_PiiVaultAccessLog_Vault` FK to PiiVault confirmed (**v2**)
- [ ] `OrphanedTokenLog.FK_OrphanedTokenLog_Vault` FK to PiiVault confirmed (**v2**)
- [ ] `SchemaContract` initial seed rows decided (per source, per critical column) — owner: pipeline-lead (**v2**)
- [ ] Pipeline service principal granted EXEC on stored procedures, INSERT on append-only tables, SELECT on read tables
- [ ] Authorized decrypt role created for SP-2 (PiiVault_Decrypt)
- [ ] All UNIQUE constraints reviewed for correct identity
- [ ] All FOREIGN KEY constraints reviewed for cascade behavior (none cascade — manual handling)
- [ ] Partition function for PipelineLog reviewed (monthly windows; auto-extension job needed)
- [ ] Clustered columnstore indexes appropriate for the access patterns (PipelineLog, PiiTokenProvenance)
- [ ] PAGE compression applied to high-volume rowstore tables
- [ ] Index sizes reviewed against expected query patterns
- [ ] Backup strategy aligned with audit requirements (vault tables in special backup tier)
- [ ] Always On Availability Group configuration includes all `General.ops` tables
- [ ] Storage forecast within database growth plan
- [ ] Stored procedures use SCHEMABINDING where possible
- [ ] Stored procedure permissions reviewed (EXECUTE AS OWNER for elevation)
- [ ] All CHECK constraints reviewed for correctness against status enum docs
- [ ] All datetime columns confirmed as DATETIME2(3) (not DATETIME)
- [ ] All hash columns confirmed as VARCHAR(64)
- [ ] No column allows NULL where business rules require non-null
- [ ] Identity seed/increment confirmed for all IDENTITY columns
- [ ] Sequence cache size (100) appropriate for batch volume
- [ ] No unintentional default values introduced
- [ ] Index fill factor reviewed for write-heavy tables (default 0=100% acceptable for append-only)

---

# Round 1 acceptance criteria

- [ ] DBA review checklist complete with sign-off
- [ ] All edge cases in mapping table verified (test ideas drafted for Round 5)
- [ ] Storage forecast reviewed against capacity baseline (D42 deliverable 0.17)
- [ ] All sub-decisions D45.1-D45.8 confirmed
- [ ] No 🔴 open items in this round
- [ ] Status flipped to 🟢 in `03_DECISIONS.md` D45
- [ ] Next round (Configuration, Round 2) plan can begin

# Open items / questions for review

**v2 status (after ROUND_1_REVIEW.md fixes)**:

✅ **Resolved in v2**:
1. ~~Partition rollover automation~~ → addressed by SP-11 (`PipelineLog_ExtendPartition`) + SQL Agent job DDL inlined
2. ~~SP-3 through SP-6 placeholders~~ → bodies fully inlined
3. ~~SP-1 concurrency bug~~ → rewritten with UPDLOCK + HOLDLOCK + try/catch
4. ~~Missing PiiTokenizationBatch UNIQUE~~ → added UX_PiiTokenizationBatch_Identity
5. ~~Missing FK on PiiVaultAccessLog~~ → FK_PiiVaultAccessLog_Vault added
6. ~~Missing EncryptionVersion column on PiiVault~~ → added with default 1
7. ~~SchemaContract not yet planned (D40 / Round 7)~~ → table 23 added
8. ~~OrphanedTokenLog not yet planned (P2)~~ → table 24 added with FK to vault
9. ~~D45.6 imprecision on PiiVault DELETE policy~~ → updated to clarify Status flip pattern, never physical DELETE

🟡 **Still open for DBA + ops review** (do not block schema sharing):

1. **Index fill factor**: defaults assumed; DBA may want to override for specific tables.

2. **Default schema for connections**: should `General.ops` be the default schema for the pipeline service principal? Or should all references be schema-qualified?

3. **TDE certificate**: needs to be created and backed up to recovery location before any vault tables are populated. Cert rotation procedure documented in operational runbook (post-Phase 1).

4. **Always On replica targeting**: which AG group includes `General` database? Synchronous-commit replicas required for at least: PiiVault, PipelineExecutionGate, IdempotencyLedger. Async OK for log tables.

5. **Snapshot isolation level**: recommend `ALLOW_SNAPSHOT_ISOLATION ON` for `General` database to support vault read consistency under concurrent load.

6. **Parquet path field width**: `NVARCHAR(1024)` — confirm sufficient for deepest expected Hive path. Worst case: `\\archive\source=DNA\table=AUDIT_LOG_LONG_NAME\year=2025\month=12\day=31\batch=99999999_part-99.parquet` ≈ 130 chars. 1024 is generous.

7. **PiiType enum**: currently locked to 8 values (SSN, EIN, EMAIL, NAME, ACCOUNT, PHONE, ADDRESS, OTHER). When new types arise, add via the schema-evolution governance (D40, Round 7) — not by editing this CHECK constraint in place.

8. **OrphanedTokenLog notification path**: how are consumer teams notified when their tokens are orphaned? Email? Power BI alert? Pending Phase 6 health-check integration.

9. **SchemaContract initial seeding**: the table is empty at deployment. First-pass seed should capture critical PII columns (`is_pii=true`, `pii_type=...`) and aggressive type contracts. Round 7 deliverable.

10. **Always On AG synchronous-commit subset**: explicit list of tables that need synchronous-commit replicas (vs async): `PiiVault`, `PipelineExecutionGate`, `IdempotencyLedger`, `ParquetSnapshotRegistry`. Others can be async.

These items are flagged for DBA review and operational decisions; they don't block the schema being shared.

---

# Round 1 v2 changelog

| Change | Driver | Detail |
|---|---|---|
| SP-1 rewrite | ROUND_1_REVIEW finding 1 (I3 race) | UPDLOCK + HOLDLOCK serialize concurrent callers; try/catch on UNIQUE for defense |
| SP-3 inlined | ROUND_1_REVIEW finding 2 | Full body for `PipelineExecutionGate_AcquireProd` |
| SP-4 inlined | ROUND_1_REVIEW finding 2 | Full body for `PipelineExecutionGate_AcquireTest` with three-action decision tree |
| SP-5 inlined | ROUND_1_REVIEW finding 2 | Full body for `PipelineExecutionGate_RequestCancellation` |
| SP-6 inlined | ROUND_1_REVIEW finding 2 | Full body for `PipelineExecutionGate_AcknowledgeCancellation` |
| SP-11 added | ROUND_1_REVIEW finding 3 (partition time-bomb) | `PipelineLog_ExtendPartition` + SQL Agent job DDL |
| Table 23 SchemaContract added | ROUND_1_REVIEW (Round 7 unscheduled) | Per-source per-column contract entries |
| Table 24 OrphanedTokenLog added | ROUND_1_REVIEW (P2 unaddressed) | Append-only audit of vault Status flips with downstream impact |
| PiiVault.EncryptionVersion added | D7 future-proof | INT NOT NULL DEFAULT 1; allows D7 migration without rewrap |
| PiiTokenizationBatch UNIQUE | ROUND_1_REVIEW finding 5 | UX on (BatchId, Source, Object, Column) — I3 mitigation |
| PiiVaultAccessLog FK to PiiVault | ROUND_1_REVIEW finding 4 | Referential integrity; documented FK policy |
| OrphanedTokenLog FK to PiiVault | New table | Same pattern |
| Edge case mapping updated | New rows | I3 (vault), I3 (tokenization batch), P2 (orphan log), partition rollover |
| Storage forecast updated | New tables | +5 MB SchemaContract, +25 MB OrphanedTokenLog |
| DBA checklist updated | New items | 8 v2-specific items added |
| D45.6 description clarified | ROUND_1_REVIEW (D45.6 imprecision) | PiiVault uses Status flip, never physical DELETE |

**v2 acceptance**: pending DBA review. After DBA sign-off, D45 flips from 🟡 to 🟢, and Round 1 closes.
