-- =============================================================================
-- Tier 3 Integration Test Schema (minimal subset of Round 1 canonical DDL)
-- =============================================================================
--
-- Per docs/migration/phase1/05_tests.md § 1.3 fixture inventory:
--
--     "Docker SQL Server bootstrap DDL — mirrors Round 1 schema verbatim.
--      Container: mcr.microsoft.com/mssql/server:2022-CU14-ubuntu-22.04
--      (version-pinned per Round 6 § 7.10). Lifecycle managed via
--      testcontainers-python Mssql module."
--
-- Canonical source: docs/migration/phase1/01_database_schema.md
--
-- Scope: Round 1 schema has 23 tables. This fixture mirrors the minimal
-- subset needed by the 3 Tier 3 test files committed in commit bc91f79:
--
--   - test_idempotency_ledger_concurrency  → IdempotencyLedger
--   - test_parquet_write_verify_replay_chain → ParquetSnapshotRegistry
--   - test_extraction_state_machine         → PipelineExtraction
--
-- Plus their shared dependencies:
--
--   - PipelineBatchSequence (BIGINT generator for BatchId across all tables)
--   - PipelineEventLog (audit-row destination for D76 invocations)
--
-- Tables NOT included (deferred to follow-up B-N when more Tier 3 tests land):
--   - PipelineLog (partitioned columnstore; expensive bootstrap)
--   - PipelineExecutionGate (Phase 2 R3 dependency)
--   - PiiVault, PiiTokenProvenance, PiiVaultAccessLog (Phase 2 R1)
--   - SchemaContract (D92 forward-only additive; meta-schema)
--   - UdmTablesList, UdmTablesColumnsList (Phase 2 R1)
--   - SCD2RepairLog, ReconciliationLog, Quarantine (operator runbooks)
--   - Phase 2+ tables
--
-- Naming conventions per docs/migration/phase1/01_database_schema.md L36:
--   - Tables: PascalCase
--   - Sequences: <Purpose>Sequence
--   - Constraints: PK_/CK_/UX_/IX_ prefixed
--
-- B-115 follow-up closure target: this file. After deploying, tests in
-- tests/integration/ use the canonical_schema_loaded fixture from
-- tests/integration/conftest.py to apply this DDL to the Docker SQL Server
-- container at session-start.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 0. Schema bootstrap
-- -----------------------------------------------------------------------------
--
-- testcontainers spins up SQL Server with a default `master` DB only. We
-- create the `General` database + `ops` schema to mirror the production
-- naming convention so the Round 3 module code's `General.ops.<X>` table
-- references resolve identically against the test container.

IF DB_ID('General') IS NULL
BEGIN
    CREATE DATABASE General;
END
GO

USE General;
GO

IF SCHEMA_ID('ops') IS NULL
BEGIN
    EXEC('CREATE SCHEMA ops AUTHORIZATION dbo');
END
GO

-- -----------------------------------------------------------------------------
-- 1. Sequence: PipelineBatchSequence
--    Source: docs/migration/phase1/01_database_schema.md § 0 (L85-101)
-- -----------------------------------------------------------------------------

IF NOT EXISTS (
    SELECT 1 FROM sys.sequences
    WHERE name = 'PipelineBatchSequence'
      AND SCHEMA_NAME(schema_id) = 'ops'
)
BEGIN
    CREATE SEQUENCE General.ops.PipelineBatchSequence
        AS BIGINT
        START WITH 1
        INCREMENT BY 1
        MINVALUE 1
        NO MAXVALUE
        NO CYCLE
        CACHE 100;
END
GO

-- -----------------------------------------------------------------------------
-- 2. PipelineEventLog
--    Source: docs/migration/phase1/01_database_schema.md § 1 (L115-165)
--    Purpose: per-step event tracking; D76 audit-row destination.
-- -----------------------------------------------------------------------------

IF OBJECT_ID('General.ops.PipelineEventLog') IS NULL
BEGIN
    CREATE TABLE General.ops.PipelineEventLog (
        EventLogId        BIGINT IDENTITY(1,1) NOT NULL,
        BatchId           BIGINT          NOT NULL,
        TableName         NVARCHAR(255)   NULL,
        SourceName        NVARCHAR(50)    NULL,
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
        Metadata          NVARCHAR(MAX)   NULL,
        RowsPerSecond     DECIMAL(18,2)   NULL,
        CycleType         NVARCHAR(10)    NULL,
        CycleDate         DATE            NULL,
        ServerRole        NVARCHAR(20)    NULL,
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
END
GO

-- -----------------------------------------------------------------------------
-- 3. PipelineExtraction
--    Source: docs/migration/phase1/01_database_schema.md § 3 (L253-295)
--    Purpose: per-day extraction state ledger; cdc/extraction_state.py canonical.
-- -----------------------------------------------------------------------------

IF OBJECT_ID('General.ops.PipelineExtraction') IS NULL
BEGIN
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
        IsReExtraction       BIT             NOT NULL DEFAULT 0,
        ExtractionAttempt    INT             NOT NULL DEFAULT 1,
        FailureReason        NVARCHAR(MAX)   NULL,

        CONSTRAINT PK_PipelineExtraction PRIMARY KEY CLUSTERED (ExtractionId),
        CONSTRAINT CK_PipelineExtraction_Status CHECK
            (Status IN ('IN_PROGRESS', 'SUCCESS', 'FAILED'))
    );

    CREATE UNIQUE INDEX UX_PipelineExtraction_Identity
        ON General.ops.PipelineExtraction
        (SourceName, TableName, DateValue, ExtractionAttempt);

    CREATE INDEX IX_PipelineExtraction_TrustGate
        ON General.ops.PipelineExtraction
        (SourceName, TableName, DateValue, Status, EvaluatedAt DESC)
        INCLUDE (BatchId, IsReExtraction, ExtractionAttempt);

    CREATE INDEX IX_PipelineExtraction_Recent
        ON General.ops.PipelineExtraction (BatchId)
        INCLUDE (SourceName, TableName, DateValue, Status);
END
GO

-- -----------------------------------------------------------------------------
-- 4. IdempotencyLedger
--    Source: docs/migration/phase1/01_database_schema.md § 7 (L431-465)
--    Purpose: D15 idempotency invariant; ledger_step() short-circuit ledger.
-- -----------------------------------------------------------------------------

IF OBJECT_ID('General.ops.IdempotencyLedger') IS NULL
BEGIN
    CREATE TABLE General.ops.IdempotencyLedger (
        LedgerId           BIGINT IDENTITY(1,1) NOT NULL,
        BatchId            BIGINT          NOT NULL,
        SourceName         NVARCHAR(50)    NOT NULL,
        TableName          NVARCHAR(255)   NOT NULL,
        EventType          NVARCHAR(50)    NOT NULL,
        Status             NVARCHAR(20)    NOT NULL DEFAULT 'IN_PROGRESS',
        StartedAt          DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
        CompletedAt        DATETIME2(3)    NULL,
        DurationMs         BIGINT          NULL,
        ErrorMessage       NVARCHAR(MAX)   NULL,
        RecoveryAction     NVARCHAR(50)    NULL,

        CONSTRAINT PK_IdempotencyLedger PRIMARY KEY CLUSTERED (LedgerId),
        CONSTRAINT CK_IdempotencyLedger_Status CHECK
            (Status IN ('IN_PROGRESS', 'COMPLETED', 'FAILED'))
    );

    CREATE UNIQUE INDEX UX_IdempotencyLedger_Key
        ON General.ops.IdempotencyLedger
        (BatchId, SourceName, TableName, EventType);

    CREATE INDEX IX_IdempotencyLedger_Stuck
        ON General.ops.IdempotencyLedger (Status, StartedAt)
        WHERE Status = 'IN_PROGRESS';

    CREATE INDEX IX_IdempotencyLedger_Batch
        ON General.ops.IdempotencyLedger (BatchId, EventType);
END
GO

-- -----------------------------------------------------------------------------
-- 5. ParquetSnapshotRegistry
--    Source: docs/migration/phase1/01_database_schema.md § 8 (L477-540)
--    Purpose: Parquet medallion registry; D2/D4/D45.2 state machine.
-- -----------------------------------------------------------------------------

IF OBJECT_ID('General.ops.ParquetSnapshotRegistry') IS NULL
BEGIN
    CREATE TABLE General.ops.ParquetSnapshotRegistry (
        RegistryId           BIGINT IDENTITY(1,1) NOT NULL,
        SourceName           NVARCHAR(50)    NOT NULL,
        TableName            NVARCHAR(255)   NOT NULL,
        BatchId              BIGINT          NOT NULL,
        BusinessDate         DATE            NULL,

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
        PiiRedactedColumns   NVARCHAR(MAX)   NULL,

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

    CREATE UNIQUE INDEX UX_ParquetSnapshotRegistry_Identity
        ON General.ops.ParquetSnapshotRegistry
        (SourceName, TableName, BatchId, BusinessDate);

    CREATE INDEX IX_ParquetSnapshotRegistry_TierAge
        ON General.ops.ParquetSnapshotRegistry (StorageTier, CreatedAt);

    CREATE INDEX IX_ParquetSnapshotRegistry_TableLookup
        ON General.ops.ParquetSnapshotRegistry
        (SourceName, TableName, BusinessDate, BatchId DESC);

    CREATE INDEX IX_ParquetSnapshotRegistry_NeedsReplication
        ON General.ops.ParquetSnapshotRegistry (CreatedAt)
        WHERE SnowflakeStagePath IS NULL AND Status = 'created';

    CREATE INDEX IX_ParquetSnapshotRegistry_Verification
        ON General.ops.ParquetSnapshotRegistry (LastVerifiedAt)
        WHERE Status NOT IN ('purged', 'missing');
END
GO

-- =============================================================================
-- Schema bootstrap complete.
--
-- Verify via:
--   SELECT name FROM General.sys.tables WHERE schema_id = SCHEMA_ID('ops')
--   ORDER BY name;
--
-- Expected: 4 tables — IdempotencyLedger, ParquetSnapshotRegistry,
-- PipelineEventLog, PipelineExtraction.
--
-- Plus 1 sequence (PipelineBatchSequence) — verify via:
--   SELECT name FROM General.sys.sequences WHERE schema_id = SCHEMA_ID('ops');
-- =============================================================================
