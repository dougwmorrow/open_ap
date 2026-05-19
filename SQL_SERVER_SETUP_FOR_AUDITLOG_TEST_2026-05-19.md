# SQL Server Setup Runbook — CCM.AuditLog test pre-flight

**Audience**: pipeline operator preparing SQL Server before running `main_large_tables.py --table AuditLog --source CCM` per `TEST_AUDITLOG_OPERATIONAL_2026-05-19.md` §5.

**Scope**: this runbook addresses the gap between your current `General.ops` state + what D125 dispatch requires. Plus: extends `UdmTablesList` with `CDCMode` column + sets up `UdmTablesList` row + `UdmTablesColumnsList` rows for AuditLog.

**Authored**: 2026-05-19 per user-provided current-state inventory.

---

## Your current `General.ops` tables (provided)

| Table | Status | Notes |
|---|---|---|
| `DataGaps` | ✅ have | Legacy / not used by D125 dispatch (OK to leave) |
| `ExtractionState` | ✅ have | Legacy / not used by D125 dispatch (OK to leave) |
| `HighWaterMark` | ✅ have | Legacy / not used by D125 dispatch (OK to leave) |
| `PipelineBatchSequence` | ✅ have | **REQUIRED** — D125 dispatch uses this for BatchId |
| `PipelineEventLog` | ✅ have | **REQUIRED** — per-step audit row table (D76 contract) |
| `PipelineExtractionState` | ✅ have | **REQUIRED** — per-table checkpoint table (P1-5) |
| `PipelineLog` | ✅ have | **REQUIRED** — narrative log via SqlServerLogHandler |
| `PipelineRun` | ✅ have | Legacy / superseded by PipelineEventLog (OK to leave) |
| `Quarantine` | ✅ have | Legacy / for ConcatCorruptionError isolation (W-17) |
| `ReconciliationLog` | ✅ have | Used by OBS-6 reconciliation (NOT required for D125 test) |
| `RunHistory` | ✅ have | Legacy / not used by D125 dispatch (OK to leave) |

## Missing — REQUIRED for D125 test

| Table | Why required | Severity |
|---|---|---|
| `General.ops.IdempotencyLedger` | D15 idempotency contract; `parquet_writer.py` + `parquet_replay.py` gate all writes through `ledger_step()` context manager. Pipeline will crash on Parquet write if absent. | **CRITICAL** |
| `General.ops.ParquetSnapshotRegistry` | Per-snapshot row tracking; `parquet_writer.py` INSERTs status='created' here; `parquet_replay.py` reads `NetworkDrivePath` + `ContentChecksum` here. Pipeline will crash on Parquet write if absent. | **CRITICAL** |

Both must be created BEFORE you run `main_large_tables.py` in `CDCMode='both'` or `'parquet_snapshot'`.

---

## §1. Create missing `General.ops` tables

### 1.1 `General.ops.IdempotencyLedger`

Per `docs/migration/phase1/01_database_schema.md` §7 canonical Round 1 DDL:

```sql
USE General;
GO

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
    RecoveryAction     NVARCHAR(50)    NULL,    -- 'STARTUP_SWEEP_FAILED', 'OPERATOR_ABANDONED', etc.

    CONSTRAINT PK_IdempotencyLedger PRIMARY KEY CLUSTERED (LedgerId),
    CONSTRAINT CK_IdempotencyLedger_Status CHECK
        (Status IN ('IN_PROGRESS', 'COMPLETED', 'FAILED'))
);
GO

-- Idempotency key: prevents double-write of (BatchId, SourceName, TableName, EventType)
CREATE UNIQUE INDEX UX_IdempotencyLedger_Key
    ON General.ops.IdempotencyLedger
    (BatchId, SourceName, TableName, EventType);
GO

-- Stuck IN_PROGRESS detection (startup recovery sweep per D45)
CREATE INDEX IX_IdempotencyLedger_Stuck
    ON General.ops.IdempotencyLedger (Status, StartedAt)
    WHERE Status = 'IN_PROGRESS';
GO

-- Per-batch status review
CREATE INDEX IX_IdempotencyLedger_Batch
    ON General.ops.IdempotencyLedger (BatchId, EventType);
GO
```

**Verify**:

```sql
SELECT
    OBJECT_ID('General.ops.IdempotencyLedger')           AS table_id,
    (SELECT COUNT(*) FROM sys.indexes
     WHERE object_id = OBJECT_ID('General.ops.IdempotencyLedger'))  AS index_count,
    (SELECT COUNT(*) FROM sys.check_constraints
     WHERE parent_object_id = OBJECT_ID('General.ops.IdempotencyLedger'))  AS check_count;
-- Expected: table_id NOT NULL; index_count = 4 (1 PK + 3 indexes); check_count = 1
```

### 1.2 `General.ops.ParquetSnapshotRegistry`

Per `docs/migration/phase1/01_database_schema.md` §8 canonical Round 1 DDL:

```sql
USE General;
GO

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
GO

-- Idempotency: one row per snapshot (SourceName, TableName, BatchId, BusinessDate)
CREATE UNIQUE INDEX UX_ParquetSnapshotRegistry_Identity
    ON General.ops.ParquetSnapshotRegistry
    (SourceName, TableName, BatchId, BusinessDate);
GO

-- Tier review job (D45.3)
CREATE INDEX IX_ParquetSnapshotRegistry_TierAge
    ON General.ops.ParquetSnapshotRegistry (StorageTier, CreatedAt);
GO

-- Per-table file lookup (B-555 v2 hash-check uses this via _query_latest_parquet_network_drive_path)
CREATE INDEX IX_ParquetSnapshotRegistry_TableLookup
    ON General.ops.ParquetSnapshotRegistry
    (SourceName, TableName, BusinessDate, BatchId DESC);
GO

-- Snowflake replication status (D5; not used by AuditLog test but canonical)
CREATE INDEX IX_ParquetSnapshotRegistry_NeedsReplication
    ON General.ops.ParquetSnapshotRegistry (CreatedAt)
    WHERE SnowflakeStagePath IS NULL AND Status = 'created';
GO

-- Integrity verification scan (D2 verifier)
CREATE INDEX IX_ParquetSnapshotRegistry_Verification
    ON General.ops.ParquetSnapshotRegistry (LastVerifiedAt)
    WHERE Status NOT IN ('purged', 'missing');
GO
```

**Verify**:

```sql
SELECT
    OBJECT_ID('General.ops.ParquetSnapshotRegistry')     AS table_id,
    (SELECT COUNT(*) FROM sys.indexes
     WHERE object_id = OBJECT_ID('General.ops.ParquetSnapshotRegistry'))  AS index_count,
    (SELECT COUNT(*) FROM sys.check_constraints
     WHERE parent_object_id = OBJECT_ID('General.ops.ParquetSnapshotRegistry'))  AS check_count;
-- Expected: table_id NOT NULL; index_count = 6 (1 PK + 5 indexes); check_count = 2
```

### 1.3 Verify all required tables now exist

```sql
SELECT
    [table] = obj,
    [exists] = CASE WHEN OBJECT_ID(obj) IS NOT NULL THEN 'OK' ELSE 'MISSING' END
FROM (VALUES
    ('General.ops.PipelineBatchSequence'),
    ('General.ops.PipelineEventLog'),
    ('General.ops.PipelineLog'),
    ('General.ops.PipelineExtractionState'),
    ('General.ops.IdempotencyLedger'),
    ('General.ops.ParquetSnapshotRegistry'),
    ('General.dbo.UdmTablesList'),
    ('General.dbo.UdmTablesColumnsList')
) AS v(obj);
-- All 8 must show 'OK'
```

---

## §2. Add `CDCMode` column to `UdmTablesList` (B-542)

D125 dispatch reads `UdmTablesList.CDCMode` to route pipeline execution. The column may or may not be present in your schema. Probe first:

### 2.1 Probe current state

```sql
-- Does CDCMode column exist?
SELECT name AS column_name,
       type_name = TYPE_NAME(user_type_id),
       max_length,
       is_nullable,
       (SELECT definition FROM sys.default_constraints WHERE parent_object_id = c.object_id AND parent_column_id = c.column_id) AS default_value
FROM sys.columns c
WHERE object_id = OBJECT_ID('General.dbo.UdmTablesList') AND name = 'CDCMode';
-- 0 rows = column missing; need §2.2 below
-- 1 row = column exists; skip to §2.3

-- Does CHECK constraint exist?
SELECT name, definition
FROM sys.check_constraints
WHERE parent_object_id = OBJECT_ID('General.dbo.UdmTablesList')
  AND name = 'CK_UdmTablesList_CDCMode';
-- 0 rows = constraint missing
-- 1 row = constraint exists
```

### 2.2 Add the column + CHECK constraint (if missing)

**Recommended**: use the canonical migration script (D74/D75/D76 compliant + writes audit trail):

```bash
# Dry-run first
python3 migrations/cdc_mode_column.py \
    --actor pipeline-lead \
    --justification "D63+D125 schema deploy for CCM.AuditLog test" \
    --server dev

# Apply
python3 migrations/cdc_mode_column.py --apply \
    --actor pipeline-lead \
    --justification "D63+D125 schema deploy for CCM.AuditLog test" \
    --server dev
```

**Alternative**: raw SQL (if you can't run the migration script for some reason):

```sql
USE General;
GO

-- Add column with default 'change_detect' (back-fills all existing rows)
ALTER TABLE General.dbo.UdmTablesList
    ADD CDCMode NVARCHAR(20) NOT NULL
        CONSTRAINT DF_UdmTablesList_CDCMode DEFAULT 'change_detect';
GO

-- Add 3-value CHECK constraint (per D125 from day 1)
ALTER TABLE General.dbo.UdmTablesList
    ADD CONSTRAINT CK_UdmTablesList_CDCMode
        CHECK (CDCMode IN ('change_detect', 'parquet_snapshot', 'both'));
GO
```

### 2.3 Verify

```sql
-- Column + default exist
SELECT c.name AS column_name,
       TYPE_NAME(c.user_type_id) AS type_name,
       c.max_length, c.is_nullable,
       dc.definition AS default_value
FROM sys.columns c
LEFT JOIN sys.default_constraints dc
    ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
WHERE c.object_id = OBJECT_ID('General.dbo.UdmTablesList') AND c.name = 'CDCMode';
-- Expect: type_name='nvarchar', max_length=40 (NVARCHAR(20) stored as 40 bytes), is_nullable=0,
-- default_value=('change_detect')

-- CHECK constraint exists with 3-value enum
SELECT name, definition
FROM sys.check_constraints
WHERE parent_object_id = OBJECT_ID('General.dbo.UdmTablesList')
  AND name = 'CK_UdmTablesList_CDCMode';
-- Expect: definition contains 'change_detect' AND 'parquet_snapshot' AND 'both'

-- All existing rows default to 'change_detect'
SELECT CDCMode, COUNT(*) AS row_count
FROM General.dbo.UdmTablesList
GROUP BY CDCMode;
-- Expect: all rows show CDCMode='change_detect' immediately after migration
```

---

## §3. Check `UdmTablesList` column completeness

The canonical UdmTablesList schema has **35 columns** per `docs/migration/phase1/02_configuration.md` §1. Your schema may have evolved differently. Probe what you have:

### 3.1 List all current columns

```sql
SELECT c.column_id AS ord,
       c.name AS column_name,
       TYPE_NAME(c.user_type_id) AS type_name,
       c.max_length,
       c.is_nullable
FROM sys.columns c
WHERE c.object_id = OBJECT_ID('General.dbo.UdmTablesList')
ORDER BY c.column_id;
```

### 3.2 Required columns for AuditLog test

These columns MUST be present for the pipeline to function. Compare against §3.1 output:

| Column | Type | Nullable | Required for AuditLog | Why |
|---|---|---|---|---|
| `SourceName` | NVARCHAR(50) | NO | YES | PK component |
| `SourceObjectName` | NVARCHAR(255) | NO | YES | PK component |
| `SourceDatabaseName` | NVARCHAR(255) | YES | YES (`'CCMREPORT'`) | Source DB connection |
| `SourceSchemaName` | NVARCHAR(50) | YES | YES (`'dbo'`) | Source schema |
| `SourceAggregateColumnName` | NVARCHAR(255) | YES | YES (`'DateTime'`) | Windowed CDC date partition column |
| `SourceAggregateColumnType` | NVARCHAR(50) | YES | YES (`'DATETIME'`) | Date column type |
| `FirstLoadDate` | DATE | YES | YES | Backfill start date |
| `LookbackDays` | INT | YES | YES (e.g. `30`) | Late-arriving data window |
| `StageLoadTool` | NVARCHAR(50) | YES | YES (`'connectorx'`) | Extractor routing |
| `StripSuffix` | BIT | NO DEFAULT 0 | RECOMMENDED `=1` for AuditLog | Bare-name convention (SS-1) |
| `StageTableName` | NVARCHAR(255) | YES | OPTIONAL (NULL = default) | Custom Stage name |
| `BronzeTableName` | NVARCHAR(255) | YES | OPTIONAL (NULL = default) | Custom Bronze name |
| `CDCMode` | NVARCHAR(20) | NO DEFAULT `'change_detect'` | YES | D125 dispatch (added in §2) |

Other canonical columns (NOT required for basic AuditLog test but typically present): `SourceIndexHint`, `PartitionOn`, `MaxRowsPerDay`, `ExpectedRetentionDays`, `PiiColumnList`, `DataClassification`, `RetentionPolicyKey`, `LegalHoldUntil`, `AppOwnerEmail`, `OnHold`, `CreatedAt`, `UpdatedAt`, `LastModifiedBy`, etc.

### 3.3 If `StripSuffix` column is missing

The `audit_log_cardtxn_config.py` migration script REQUIRES this column. Add it first:

```bash
# Dry-run
python3 migrations/strip_suffix_column.py --dry-run

# Apply
python3 migrations/strip_suffix_column.py
```

OR raw SQL:

```sql
USE General;
GO

ALTER TABLE General.dbo.UdmTablesList
    ADD StripSuffix BIT NOT NULL
        CONSTRAINT DF_UdmTablesList_StripSuffix DEFAULT 0;
GO
```

### 3.4 If other required columns are missing

If §3.1 shows any of the "Required for AuditLog" columns from §3.2 are missing, you'll need a custom ALTER. Provide me the output of §3.1 + I can author the missing-column ALTER statements.

---

## §4. Seed `UdmTablesList` row for CCM.AuditLog

### 4.1 Recommended: use the canonical migration script

```bash
# Dry-run (queries source for MIN([DateTime]) to determine FirstLoadDate)
python3 migrations/audit_log_cardtxn_config.py \
    --linked-server PDCAAGDNA02 --dry-run

# Apply
python3 migrations/audit_log_cardtxn_config.py \
    --linked-server PDCAAGDNA02
```

OR if you already know the earliest DateTime in the source AuditLog:

```bash
python3 migrations/audit_log_cardtxn_config.py \
    --first-load-date 2018-01-01 --dry-run
python3 migrations/audit_log_cardtxn_config.py \
    --first-load-date 2018-01-01
```

### 4.2 Alternative: manual SQL INSERT

If the migration script doesn't work for your environment, INSERT directly:

```sql
USE General;
GO

-- Adjust FirstLoadDate to your earliest AuditLog source row (query MIN([DateTime]) FROM CCMREPORT.dbo.AuditLog)
INSERT INTO General.dbo.UdmTablesList (
    SourceName,
    SourceObjectName,
    SourceDatabaseName,
    SourceSchemaName,
    SourceAggregateColumnName,
    SourceAggregateColumnType,
    FirstLoadDate,
    LookbackDays,
    StageLoadTool,
    StripSuffix,
    StageTableName,
    BronzeTableName,
    CDCMode
)
VALUES (
    'CCM',                  -- SourceName
    'AuditLog',             -- SourceObjectName
    'CCMREPORT',            -- SourceDatabaseName
    'dbo',                  -- SourceSchemaName
    'DateTime',             -- SourceAggregateColumnName (windowed CDC partition column)
    'DATETIME',             -- SourceAggregateColumnType
    '2018-01-01',           -- FirstLoadDate (ADJUST to your actual earliest source DateTime)
    30,                     -- LookbackDays (late-arriving data window)
    'connectorx',           -- StageLoadTool (SQL Server source -> connectorx)
    1,                      -- StripSuffix (=1 for AuditLog per audit_log_cardtxn_config.py)
    NULL,                   -- StageTableName (NULL = default UDM_Stage.CCM.AuditLog)
    NULL,                   -- BronzeTableName (NULL = default UDM_Bronze.CCM.AuditLog)
    'change_detect'         -- CDCMode (starts at default; flip to 'both' via tools/flip_cdc_mode.py later)
);
GO
```

**Adjust before running**:
- `FirstLoadDate` — query the actual earliest `DateTime` in source: `SELECT MIN([DateTime]) FROM CCMREPORT.dbo.AuditLog;` (this run-once query determines backfill scope)
- `LookbackDays` — 30 is typical; increase if AuditLog has heavy late-arriving data

### 4.3 Verify

```sql
SELECT SourceName, SourceObjectName, SourceDatabaseName, SourceSchemaName,
       SourceAggregateColumnName, SourceAggregateColumnType,
       FirstLoadDate, LookbackDays, StripSuffix, StageLoadTool,
       StageTableName, BronzeTableName, CDCMode
FROM General.dbo.UdmTablesList
WHERE SourceName = 'CCM' AND SourceObjectName = 'AuditLog';
-- Expect: 1 row with all canonical values
```

---

## §5. Seed `UdmTablesColumnsList` PK row(s) for CCM.AuditLog

The pipeline needs PK column metadata to perform CDC anti-joins + SCD2 business-key matching. CCM.AuditLog's PK is typically `ID` (single column) but verify against your source.

### 5.1 Recommended: automated column sync from source

The pipeline auto-discovers PK columns + populates `UdmTablesColumnsList` on the first run via `schema/column_sync.py`. Run it manually first to verify it works:

```bash
python3 -m schema.column_sync --source CCM --table AuditLog
```

This queries source `INFORMATION_SCHEMA.KEY_COLUMN_USAGE` + populates `General.dbo.UdmTablesColumnsList` rows with `IsPrimaryKey=1` for the source's PK columns.

### 5.2 Verify auto-discovered PK columns

```sql
SELECT ColumnName, OrdinalPosition, IsPrimaryKey, DataType, IsNullable
FROM General.dbo.UdmTablesColumnsList
WHERE SourceName = 'CCM' AND TableName = 'AuditLog'
ORDER BY OrdinalPosition;
```

**Expected**: at least 1 row with `IsPrimaryKey = 1`. CCM.AuditLog typically has `ID` (single-column PK).

### 5.3 Alternative: manual INSERT (if auto-sync fails)

First, find AuditLog's PK from the source:

```sql
-- Query the SOURCE server (CCMREPORT), not General
SELECT
    ku.COLUMN_NAME,
    ku.ORDINAL_POSITION,
    c.DATA_TYPE,
    c.IS_NULLABLE
FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
    ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
JOIN INFORMATION_SCHEMA.COLUMNS c
    ON c.TABLE_NAME = ku.TABLE_NAME AND c.COLUMN_NAME = ku.COLUMN_NAME
WHERE ku.TABLE_NAME = 'AuditLog'
  AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
ORDER BY ku.ORDINAL_POSITION;
```

Then INSERT into `UdmTablesColumnsList`:

```sql
USE General;
GO

-- Adjust ColumnName + DataType to match what §5.3 source-query returned
-- Typical AuditLog PK: 'ID' INT NOT NULL
INSERT INTO General.dbo.UdmTablesColumnsList (
    SourceName,
    TableName,
    ColumnName,
    OrdinalPosition,
    IsPrimaryKey,
    DataType,
    IsNullable
)
VALUES (
    'CCM',          -- SourceName
    'AuditLog',     -- TableName
    'ID',           -- ColumnName (ADJUST per §5.3 source query)
    1,              -- OrdinalPosition
    1,              -- IsPrimaryKey
    'int',          -- DataType (ADJUST per §5.3 source query)
    0               -- IsNullable (NOT NULL for PK)
);
GO

-- If AuditLog has a COMPOSITE PK (multiple columns), INSERT one row per PK column
-- with incrementing OrdinalPosition
```

### 5.4 Verify

```sql
SELECT ColumnName, OrdinalPosition, IsPrimaryKey, DataType, IsNullable
FROM General.dbo.UdmTablesColumnsList
WHERE SourceName = 'CCM' AND TableName = 'AuditLog'
  AND IsPrimaryKey = 1
ORDER BY OrdinalPosition;
-- Expect: at least 1 row
```

---

## §6. Bronze table — auto-created on first pipeline run

`schema/table_creator.py::ensure_bronze_table()` auto-creates `UDM_Bronze.CCM.AuditLog` from the source DataFrame's dtypes on the first pipeline run. No manual DDL needed.

### 6.1 Verify Bronze doesn't already exist (clean test starting state)

```sql
SELECT OBJECT_ID('UDM_Bronze.CCM.AuditLog') AS bronze_table_id;
-- NULL = doesn't exist yet (clean state; will be auto-created)
-- non-NULL = exists already (re-run will INSERT/UPDATE per SCD2 contract)
```

### 6.2 If Bronze already exists + you want to start clean (test/dev ONLY)

**DO NOT** run this against production Bronze. Test/dev environments only.

```sql
-- DESTRUCTIVE — drops Bronze AuditLog table entirely
DROP TABLE IF EXISTS UDM_Bronze.CCM.AuditLog;
GO

-- Also clear ParquetSnapshotRegistry rows for AuditLog (cleans up snapshot index)
DELETE FROM General.ops.ParquetSnapshotRegistry
WHERE SourceName = 'CCM' AND TableName = 'AuditLog';
GO

-- Also clear IdempotencyLedger rows for AuditLog (cleans up replay-resume state)
DELETE FROM General.ops.IdempotencyLedger
WHERE SourceName = 'CCM' AND TableName = 'AuditLog';
GO

-- Also clear PipelineExtractionState checkpoint (cleans up per-day resume state)
DELETE FROM General.ops.PipelineExtractionState
WHERE SourceName = 'CCM' AND TableName = 'AuditLog';
GO
```

---

## §7. Final pre-flight verification

Before running `main_large_tables.py`, verify all setup complete:

```sql
-- 1. All required General.ops tables exist
SELECT
    [table] = obj,
    [exists] = CASE WHEN OBJECT_ID(obj) IS NOT NULL THEN 'OK' ELSE 'MISSING' END
FROM (VALUES
    ('General.ops.PipelineBatchSequence'),
    ('General.ops.PipelineEventLog'),
    ('General.ops.PipelineLog'),
    ('General.ops.PipelineExtractionState'),
    ('General.ops.IdempotencyLedger'),
    ('General.ops.ParquetSnapshotRegistry')
) AS v(obj);
-- All 6 must show 'OK'

-- 2. CDCMode column + CHECK constraint present
SELECT
    [check] = 'CDCMode column',
    [exists] = CASE WHEN COL_LENGTH('General.dbo.UdmTablesList', 'CDCMode') IS NOT NULL THEN 'OK' ELSE 'MISSING' END
UNION ALL
SELECT
    'CK_UdmTablesList_CDCMode constraint',
    CASE WHEN EXISTS (
        SELECT 1 FROM sys.check_constraints
        WHERE parent_object_id = OBJECT_ID('General.dbo.UdmTablesList')
          AND name = 'CK_UdmTablesList_CDCMode'
    ) THEN 'OK' ELSE 'MISSING' END;
-- Both must show 'OK'

-- 3. AuditLog UdmTablesList row exists with valid CDCMode
SELECT
    [check] = 'AuditLog row in UdmTablesList',
    [exists] = CASE WHEN EXISTS (
        SELECT 1 FROM General.dbo.UdmTablesList
        WHERE SourceName='CCM' AND SourceObjectName='AuditLog'
    ) THEN 'OK' ELSE 'MISSING' END
UNION ALL
SELECT
    'AuditLog has PK column(s) in UdmTablesColumnsList',
    CASE WHEN EXISTS (
        SELECT 1 FROM General.dbo.UdmTablesColumnsList
        WHERE SourceName='CCM' AND TableName='AuditLog' AND IsPrimaryKey=1
    ) THEN 'OK' ELSE 'MISSING' END;
-- Both must show 'OK'

-- 4. AuditLog's current CDCMode (should be 'change_detect' at this point;
-- you'll flip to 'both' via tools/flip_cdc_mode.py in §4 of TEST_AUDITLOG_OPERATIONAL_2026-05-19.md)
SELECT SourceName, SourceObjectName, CDCMode, StripSuffix, FirstLoadDate, LookbackDays, StageLoadTool
FROM General.dbo.UdmTablesList
WHERE SourceName='CCM' AND SourceObjectName='AuditLog';
```

**If all 4 verification queries return all OK** → you're ready to proceed to `TEST_AUDITLOG_OPERATIONAL_2026-05-19.md` §4 (flip CDCMode to `'both'`) + §5 (run `main_large_tables.py`).

---

## §8. Troubleshooting

| Symptom | Probable cause | Fix |
|---|---|---|
| `CREATE TABLE` fails with permission error | Login lacks DDL rights on `General.ops` schema | Grant DDL: `GRANT CREATE TABLE ON SCHEMA::ops TO [your_login];` |
| ALTER TABLE fails with "object already exists" | Column / constraint already added (idempotent path) | Skip the ALTER; re-run §2.3 verification |
| `migrations/audit_log_cardtxn_config.py` errors with "linked server not found" | Linked server `PDCAAGDNA02` not configured | Use `--first-load-date` path instead (§4.1 second example) |
| `schema/column_sync.py` fails with "source table not found" | CCMREPORT.dbo.AuditLog not visible from migration host | Use manual INSERT path (§5.3) |
| Source query `MIN([DateTime]) FROM CCMREPORT.dbo.AuditLog` runs but returns NULL | Source table is empty | Verify with source-team that AuditLog has data; FirstLoadDate is moot if source is empty |
| UdmTablesList INSERT fails with NULL/NOT NULL violation | Your schema has additional NOT NULL columns I didn't include | Run §3.1 to enumerate columns + add missing NOT NULL values to the INSERT |

---

## §9. After this runbook completes

Proceed to **`TEST_AUDITLOG_OPERATIONAL_2026-05-19.md` §4** (flip CDCMode from `change_detect` to `both`) + §5 (run `main_large_tables.py`).

---

*Authored 2026-05-19 per user-provided General.ops inventory. Run §1 + §2 + §3 + §4 + §5 sequentially. §6 + §7 are verification. After all verifications pass, the SQL Server side is ready for the operational test.*
