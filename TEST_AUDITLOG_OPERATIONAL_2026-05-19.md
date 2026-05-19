# Operator Test Runbook — main_large_tables.py against CCM.AuditLog (post-D125)

**Audience**: pipeline operator running the first real D125 shadow-mode test against CCM.AuditLog (96M rows).

**Goal**: verify SQL Server metadata + pipeline environment are ready, then run `main_large_tables.py` end-to-end with `CDCMode='both'` shadow-write semantic. Surfaces any real-data interaction issues before the canonical D125 cutover.

**Authored**: 2026-05-19 (post-D125 arc FULLY CODE-COMPLETE; supersedes isolated-module testing in `TEST_PARQUET_TO_SCD2_PIPELINE.md`).

---

## Companion docs (read these too)

| Doc | When to read |
|---|---|
| `docs/migration/05_RUNBOOKS.md` RB-16 (L1558) | **Canonical 2-step D125 cutover procedure**; this runbook is RB-16 Step 1 in operator-friendly form |
| `TEST_PARQUET_TO_SCD2_PIPELINE.md` | Module-level isolated smoke (pre-D125 wiring; mostly superseded; useful for narrow component debugging) |
| `CLAUDE.md` L308+ Do-NOT rules | Pipeline invariants you must NOT violate |
| `CLAUDE.md` Gotchas section + `docs/migration/CLAUDE_GOTCHAS.md` | B-1 through SCD2-* gotcha codes for debugging |

---

## What this runbook covers

The full operator workflow for a single CCM.AuditLog test cycle in `CDCMode='both'` shadow-write mode:

1. **Pre-flight**: RHEL env + network drive + .env + DDL deployed
2. **Schema migration**: `UdmTablesList.CDCMode` column exists (B-542)
3. **Metadata setup**: `UdmTablesList` + `UdmTablesColumnsList` rows for CCM.AuditLog
4. **CDCMode flip**: `change_detect` → `both` via `tools/flip_cdc_mode.py` (B-546)
5. **Pipeline run**: `python3 main_large_tables.py --table AuditLog --source CCM`
6. **Post-run verification**: Parquet present + Bronze populated + parity check (row-count + per-PK hash)
7. **Rollback**: how to back out if something goes wrong

---

## §1. Pre-flight (~10 min)

### 1.1 RHEL environment

```bash
# MALLOC_ARENA_MAX=2 MUST be exported BEFORE Python starts (W-4 in CLAUDE.md)
env | grep MALLOC_ARENA_MAX    # should print MALLOC_ARENA_MAX=2

# ODBC Driver 18 for SQL Server
odbcinst -q -d -n "ODBC Driver 18 for SQL Server"   # should print [ODBC Driver 18 for SQL Server]

# Oracle Instant Client 19c (required for config.py import even if AuditLog is SQL Server source)
ldconfig -p | grep libclntsh   # should print /usr/lib/oracle/19.x/client64/lib/libclntsh.so.19.1

# BCP utility
which bcp                       # should print /opt/mssql-tools18/bin/bcp

# Python 3.12.11 + deps
python3 --version
python3 -c "import polars, connectorx, pyodbc, polars_hash, dotenv; print('deps OK')"
```

### 1.2 Network drive mounted

```bash
mount | grep VendorFiles          # should show VendorFiles mounted
ls -ld /VendorFiles/PROD/Parquet  # parquet output dir
ls -ld /VendorFiles/PROD/PythonIngestions  # CSV staging dir

# Write probe
touch /VendorFiles/PROD/Parquet/.smoke_probe && rm /VendorFiles/PROD/Parquet/.smoke_probe || echo "WRITE FAILED"
```

### 1.3 `/etc/pipeline/.env` keys (D103 location)

Required keys for this run:

```bash
PIPELINE_ENV=dev
UDM_CX_SERVER=<udm_sql_server_host>
UDM_DEV_UID=<udm_dev_login>
UDM_DEV_PASSWORD=<udm_dev_pwd>
UDM_DEV_PORT=1433
DB_GENERAL=General
DB_STAGE=UDM_Stage
DB_BRONZE=UDM_Bronze
ODBC_DRIVER=ODBC Driver 18 for SQL Server

# CCM source (AuditLog lives here)
CCMPROD_REPLICA_SERVER_FULL_NAME=PDCAAGDNA02
CCM_SERVER_PORT=1433
DLHDEV_UID=<ccm_login>
DLHDEV_PASSWORD=<ccm_pwd>

# Parquet output dir
PARQUET_OUTPUT_DIR=/VendorFiles/PROD/Parquet

# CSV staging dir
CSV_OUTPUT_DIR=/VendorFiles/PROD/PythonIngestions

# Operational guards
MAX_RSS_GB=49.0
BCP_TIMEOUT=7200
```

File permissions per D103: `chmod 0400 /etc/pipeline/.env`; owned by `pipeline:pipeline`.

Verify Python can read config:

```bash
sudo -u pipeline python3 -c "
import utils.configuration as c
print('PIPELINE_ENV =', c.PIPELINE_ENV)
print('GENERAL_DB =', c.GENERAL_DB)
print('CSV_OUTPUT_DIR =', c.CSV_OUTPUT_DIR)
import os
print('PARQUET_OUTPUT_DIR =', os.environ.get('PARQUET_OUTPUT_DIR'))
"
```

### 1.4 Round 1 DDL + D125 schema deployed

These objects MUST exist in `General`:

```python
python3 - <<'PY'
import pyodbc, utils.configuration as c
conn = pyodbc.connect(
    f"DRIVER={{{c.ODBC_DRIVER}}};SERVER={c.SQL_SERVER_HOST},{c.SQL_SERVER_PORT};"
    f"DATABASE={c.GENERAL_DB};UID={c.SQL_SERVER_USER};PWD={c.SQL_SERVER_PASSWORD};"
    "Encrypt=yes;TrustServerCertificate=yes"
)
cur = conn.cursor()
for obj in [
    "General.ops.ParquetSnapshotRegistry",
    "General.ops.PipelineBatchSequence",
    "General.ops.PipelineEventLog",
    "General.ops.PipelineLog",
    "General.ops.IdempotencyLedger",
    "General.dbo.UdmTablesList",
    "General.dbo.UdmTablesColumnsList",
]:
    cur.execute("SELECT OBJECT_ID(?)", obj)
    print(f"{obj:55s} {'OK' if cur.fetchone()[0] is not None else 'MISSING'}")
PY
```

All `OK` required. Any `MISSING` → fix Round 1 deploy before continuing.

### 1.5 Source DB reachable (CCM)

```python
python3 - <<'PY'
import utils.configuration as c, pyodbc
conn = pyodbc.connect(
    f"DRIVER={{{c.ODBC_DRIVER}}};SERVER={c.CCM_SERVER_HOST},{c.CCM_SERVER_PORT};"
    f"DATABASE=CCMREPORT;UID={c.CCM_SERVER_USER};PWD={c.CCM_SERVER_PASSWORD};"
    "Encrypt=yes;TrustServerCertificate=yes"
)
cur = conn.cursor()
cur.execute("SELECT COUNT_BIG(*) FROM dbo.AuditLog")
print("CCMREPORT.dbo.AuditLog row count:", cur.fetchone()[0])
cur.execute("SELECT MIN([DateTime]), MAX([DateTime]) FROM dbo.AuditLog")
print("DateTime range:", cur.fetchone())
PY
```

**Capture these numbers as ground truth** for post-run reconciliation.

---

## §2. Schema migration — `UdmTablesList.CDCMode` column (B-542)

The D125 dispatch reads `UdmTablesList.CDCMode` per table. Deploy the column if not already deployed.

### 2.1 Probe whether already deployed

```sql
SELECT name, system_type_name = TYPE_NAME(user_type_id), is_nullable, default_object_id
FROM sys.columns
WHERE object_id = OBJECT_ID('General.dbo.UdmTablesList') AND name = 'CDCMode';
```

If 1 row returned → column exists; skip to §3.

If 0 rows → run migration:

### 2.2 Deploy migration

```bash
# Dry-run first
python3 migrations/cdc_mode_column.py \
    --actor pipeline-lead \
    --justification "D63+D125 schema deploy for CCM.AuditLog operational test" \
    --server dev

# Apply
python3 migrations/cdc_mode_column.py --apply \
    --actor pipeline-lead \
    --justification "D63+D125 schema deploy for CCM.AuditLog operational test" \
    --server dev
```

### 2.3 Verify

```sql
-- Column exists + CHECK constraint enforces 3-value enum (per D125)
SELECT cc.name AS check_constraint_name, cc.definition
FROM sys.check_constraints cc
WHERE cc.parent_object_id = OBJECT_ID('General.dbo.UdmTablesList')
  AND cc.name = 'CK_UdmTablesList_CDCMode';
-- Expect: definition contains 'change_detect' / 'parquet_snapshot' / 'both'

-- All existing rows default to 'change_detect'
SELECT CDCMode, COUNT(*) AS table_count
FROM General.dbo.UdmTablesList
GROUP BY CDCMode;
-- Expect: all rows CDCMode='change_detect' immediately after migration
```

---

## §3. Metadata setup — `UdmTablesList` + `UdmTablesColumnsList` for CCM.AuditLog (~10 min)

The pipeline needs the AuditLog row in `UdmTablesList` + PK columns in `UdmTablesColumnsList`.

### 3.1 If using the canonical AuditLog/CARDTXN migration script

```bash
# Dry-run
python3 migrations/audit_log_cardtxn_config.py \
    --linked-server PDCAAGDNA02 --dry-run

# Apply
python3 migrations/audit_log_cardtxn_config.py \
    --linked-server PDCAAGDNA02
```

### 3.2 Verify `UdmTablesList` row

```sql
SELECT SourceName, SourceObjectName, SourceDatabaseName, SourceSchemaName,
       SourceAggregateColumnName, SourceAggregateColumnType,
       FirstLoadDate, LookbackDays, StripSuffix, StageLoadTool,
       StageTableName, BronzeTableName, CDCMode
FROM General.dbo.UdmTablesList
WHERE SourceName = 'CCM' AND SourceObjectName = 'AuditLog';
```

**Expected values** for CCM.AuditLog:

| Column | Value |
|---|---|
| SourceName | `CCM` |
| SourceObjectName | `AuditLog` |
| SourceDatabaseName | `CCMREPORT` |
| SourceSchemaName | `dbo` |
| SourceAggregateColumnName | `DateTime` (PARTITIONED BY this column for windowed CDC) |
| SourceAggregateColumnType | `DATETIME` (or `DATETIME2(3)` depending on source schema) |
| FirstLoadDate | first date you want to load from (e.g. `2024-01-01`) |
| LookbackDays | typical: 30-60 (window size for late-arriving data) |
| StripSuffix | `1` (CARDTXN/AuditLog use SS-1 per `audit_log_cardtxn_config.py` — Bronze name `UDM_Bronze.CCM.AuditLog` not `..._scd2_python`) |
| StageLoadTool | `connectorx` (or `oracledb` for Oracle sources; AuditLog is SQL Server so connectorx) |
| StageTableName | NULL (use default naming) |
| BronzeTableName | NULL (use default naming with SS-1 stripped) |
| CDCMode | `change_detect` (default; flipped to `both` in §4) |

### 3.3 Verify `UdmTablesColumnsList` PK columns

```sql
SELECT ColumnName, OrdinalPosition, IsPrimaryKey, DataType, IsNullable
FROM General.dbo.UdmTablesColumnsList
WHERE SourceName = 'CCM' AND TableName = 'AuditLog'
ORDER BY OrdinalPosition;
```

**Required**: at least one row with `IsPrimaryKey = 1`. If empty OR no `IsPrimaryKey=1` rows → run column-sync first:

```bash
python3 -m schema.column_sync --source CCM --table AuditLog
```

**Why this matters**: B-560 closure WARNING fires if `_resolve_pk_columns()` returns empty; B-555 `--hash-check` requires PK columns. CCM.AuditLog typical PK = `[AuditLogId]` or composite.

### 3.4 Bronze table will be auto-created on first run

`schema/table_creator.py::ensure_bronze_table()` auto-creates `UDM_Bronze.CCM.AuditLog` on first pipeline run if it doesn't exist. No manual DDL needed.

Probe whether already exists:

```sql
SELECT OBJECT_ID('UDM_Bronze.CCM.AuditLog');
-- NULL = doesn't exist yet (will be auto-created); non-NULL = exists
```

---

## §4. Flip CDCMode to `'both'` (B-546)

The default `change_detect` mode runs legacy CDC only (no Parquet). Flip to `'both'` for shadow-write mode (Parquet AND legacy CDC AND SCD2 all run in parallel).

### 4.1 Dry-run first (D75 default)

```bash
python3 tools/flip_cdc_mode.py \
    --source CCM --table AuditLog --mode both \
    --actor pipeline-lead \
    --justification "RB-16 Step 1: AuditLog operational test shadow start"
```

Expected output:

```json
{
  "event_kind": "dry_run",
  "exit_code": 0,
  "source": "CCM",
  "table": "AuditLog",
  "current_mode": "change_detect",
  "target_mode": "both",
  "transition_risk": "ALLOWED",
  "dry_run": true,
  "would_flip": true
}
```

### 4.2 Apply

```bash
python3 tools/flip_cdc_mode.py --apply \
    --source CCM --table AuditLog --mode both \
    --actor pipeline-lead \
    --justification "RB-16 Step 1: AuditLog operational test shadow start"
```

Expected exit code: `0` (SUCCESS). Expected `event_kind`: `"apply"`. Expected `flipped: true`.

### 4.3 Verify

```sql
SELECT SourceName, SourceObjectName, CDCMode
FROM General.dbo.UdmTablesList
WHERE SourceName = 'CCM' AND SourceObjectName = 'AuditLog';
-- Expect: CDCMode = 'both'

-- Audit row written
SELECT TOP 1 EventType, EventDetail, Status, StartedAt, Metadata
FROM General.ops.PipelineEventLog
WHERE EventType = 'CLI_FLIP_CDC_MODE'
  AND TableName = 'AuditLog'
ORDER BY StartedAt DESC;
```

---

## §5. Run the pipeline — `main_large_tables.py` (~30 min to several hours for 96M rows)

This is the main event. Triggers the full D125 dispatch: write Parquet snapshot + run legacy CDC + run SCD2 → Bronze.

### 5.1 First run (single table, single worker for clean signal)

```bash
# Single table, single worker -- ALL output goes to stdout/stderr for debugging
python3 main_large_tables.py --table AuditLog --source CCM --workers 1
```

### 5.2 What you'll see at each stage

Per-day cycle (for each business date in the LookbackDays window):

```
INFO  Extracting CCM.AuditLog for date YYYY-MM-DD ...
INFO  Extracted N rows from source
INFO  Schema evolution: <no-op | added columns: ... | WARN removed columns: ...>
INFO  Writing Parquet snapshot to /VendorFiles/PROD/Parquet/CCM/AuditLog/year=YYYY/month=MM/day=DD/...
INFO  ParquetSnapshotRegistry row inserted with Status='created'
INFO  Running CDC promotion (legacy; windowed)
INFO  CDC: inserts=N updates=M deletes=K unchanged=U
INFO  Running SCD2 promotion (Bronze update)
INFO  SCD2: inserts=N closes=M unchanged=U
INFO  CSV cleanup: K temp files removed
```

If pipeline hits an issue → DON'T panic. The pipeline is designed to be idempotent. Errors caught and logged; subsequent runs resume from `PipelineExtractionState` checkpoint (P1-5).

### 5.3 Things to monitor

- **Memory**: `MAX_RSS_GB=49.0` guard; pipeline aborts cleanly if RSS exceeds threshold (W-4)
- **Disk space**: Parquet files accumulate in `/VendorFiles/PROD/Parquet/CCM/AuditLog/year=...`; CSV files in `/VendorFiles/PROD/PythonIngestions/` (auto-cleaned per-day)
- **PipelineLog tail** (in another terminal): `python3 -c "import utils.connections as c; ..."` OR query SQL Server directly

### 5.4 Stop / resume

- Ctrl-C is safe (sp_getapplock auto-releases on connection drop; W-8). State persisted via PipelineExtractionState checkpoint (P1-5).
- Re-run the same command to resume from the last checkpointed date.

---

## §6. Post-run verification (~10 min)

Verify all 3 paths ran successfully.

### 6.1 Parquet snapshots written

```sql
SELECT TOP 20 BatchId, BusinessDate, NetworkDrivePath, RowCount, Status, CreatedAt
FROM General.ops.ParquetSnapshotRegistry
WHERE SourceName = 'CCM' AND TableName = 'AuditLog'
ORDER BY CreatedAt DESC;
```

**Expected**: 1 row per business day processed. Status='created' (or 'verified' if you ran `tools/parquet_verify.py` separately).

Also check on disk:

```bash
ls -la /VendorFiles/PROD/Parquet/CCM/AuditLog/year=2024/month=01/  # adjust date
du -sh /VendorFiles/PROD/Parquet/CCM/AuditLog/
```

### 6.2 Bronze SCD2 populated

```sql
-- Active row count
SELECT COUNT(*) AS active_rows FROM UDM_Bronze.CCM.AuditLog WHERE UdmActiveFlag = 1;

-- Per-business-date insert + close counts
SELECT
    CAST(UdmEffectiveDateTime AS DATE) AS load_date,
    COUNT(*) AS rows_loaded,
    SUM(CASE WHEN UdmActiveFlag = 1 THEN 1 ELSE 0 END) AS still_active,
    SUM(CASE WHEN UdmActiveFlag = 0 THEN 1 ELSE 0 END) AS closed,
    SUM(CASE WHEN UdmActiveFlag = 2 THEN 1 ELSE 0 END) AS delete_marked
FROM UDM_Bronze.CCM.AuditLog
GROUP BY CAST(UdmEffectiveDateTime AS DATE)
ORDER BY load_date;
```

**Expected**: roughly equal to source row count from §1.5 ± any rows source has that aren't in the LookbackDays window.

### 6.3 Run nightly parity check (row-count level)

```bash
python3 tools/validate_parquet_vs_stage.py --apply \
    --source CCM --table AuditLog \
    --actor automated \
    --justification "RB-16 nightly parity sanity post-first-run"
```

**Expected**: exit code `0` (SUCCESS); per-table verdict `CLEAN`. If `DRIFT` (1-5%) → investigate; if `MAJOR_DRIFT` (>5% OR Parquet<Bronze) → BLOCK the cutover decision pending root-cause analysis.

### 6.4 Run per-PK hash parity check (B-555 v2; opt-in deep validation)

```bash
python3 tools/validate_parquet_vs_stage.py --apply --hash-check \
    --source CCM --table AuditLog \
    --actor pipeline-lead \
    --justification "RB-16 pre-cutover per-PK hash validation"
```

**Expected**: exit code `0`; per-table verdict `CLEAN`; metadata.hash_comparison shows `in_bronze_missing_from_parquet=0` (CRITICAL invariant per D115) + `pk_match_hash_diff=0` (content-equivalence verified).

Heavy I/O — for 96M rows, this can take significant memory + time. Use only for pre-cutover validation, not nightly.

### 6.5 Operational audit trail

```sql
-- This run's events
SELECT TOP 50 BatchId, TableName, EventType, EventDetail, DurationMs, Status, RowsProcessed
FROM General.ops.PipelineEventLog
WHERE TableName = 'AuditLog' AND StartedAt >= DATEADD(hour, -24, SYSUTCDATETIME())
ORDER BY StartedAt;
```

**Expect to see**: TABLE_TOTAL (outer wrapper) + EXTRACT + BCP_LOAD + PARQUET_WRITE + CDC_PROMOTION + SCD2_PROMOTION + CSV_CLEANUP events per business day.

---

## §7. Rollback (if needed)

If anything goes catastrophically wrong + you need to back out:

### 7.1 Flip CDCMode back to `change_detect`

```bash
python3 tools/flip_cdc_mode.py --apply \
    --source CCM --table AuditLog --mode change_detect \
    --actor pipeline-lead \
    --justification "Rollback CCM.AuditLog from operational test"
```

### 7.2 Optional: TRUNCATE Bronze (DESTRUCTIVE — only if Bronze data is test-only)

Per `docs/migration/05_RUNBOOKS.md` RB-18 (D2 cutover rollback for ACCT pilot). **DO NOT** run against production Bronze. Test/dev environments only.

### 7.3 Optional: clean up Parquet snapshots on disk

```bash
# Mark snapshots as 'purged' in registry (audit trail preserved)
# (NO automated CLI for this yet; use SQL UPDATE if needed)
# Actual file cleanup: rm -rf /VendorFiles/PROD/Parquet/CCM/AuditLog/ (test/dev only)
```

---

## §8. After successful run — next steps

If §6 verification passes (all CLEAN), you've successfully completed RB-16 Step 1 for one date. Continue running nightly for ≥30 days (per RB-16 shadow validation period) before considering cutover to `'parquet_snapshot'` mode (RB-16 Step 2).

Operational handoff:

1. Schedule nightly `main_large_tables.py --table AuditLog --source CCM` via your job scheduler
2. Schedule nightly `tools/validate_parquet_vs_stage.py --apply --source CCM --table AuditLog` (row-count parity)
3. Weekly `tools/validate_parquet_vs_stage.py --apply --hash-check ...` for deeper validation
4. After 30+ clean days → operator + pipeline-lead decision: proceed to Step 2 cutover (`tools/flip_cdc_mode.py --apply --mode parquet_snapshot`) per RB-16

---

## §9. Troubleshooting quick reference

| Symptom | Probable cause | Fix |
|---|---|---|
| `_resolve_pk_columns: no PK columns for CCM.AuditLog` WARNING | UdmTablesColumnsList missing PK rows | Run `python3 -m schema.column_sync --source CCM --table AuditLog` |
| `Bronze NULL-PK defensive filter will be a no-op; hash-check would FATAL` | Same as above + you ran `--hash-check` | Same fix |
| `MAJOR_DRIFT` parity verdict with Parquet > Bronze (>5%) | Either: (a) Parquet has NULL-PK rows Bronze filtered; OR (b) legitimate drift | Run `--hash-check` for definitive per-PK comparison; NULL-PK noise is filtered there per B-555 closure |
| `MAJOR_DRIFT` parity verdict with Bronze > Parquet (ANY %) | CRITICAL: Parquet missed data (D115 source-exactness violated) | DO NOT cut over. Investigate via `tools/diagnose_stage_bronze_gap.py` + escalate |
| `BCP row count mismatch` in PipelineLog | String sanitization gap | Check for new control chars in source (B-6 / W-2 / E-19 in CLAUDE_GOTCHAS.md) |
| `ConcatCorruptionError` from CDC | Polars Categorical dtype hashing bug (E-20) | Check for new Categorical columns; cast to Utf8 before hash |
| Run hangs at extract step | ConnectorX timeout OR network drive unmounted | Check `mount` + restart with `python3 main_large_tables.py --workers 1 --extract-tool oracledb` (fallback) |
| Memory exceeded `MAX_RSS_GB=49` | LookbackDays too high | Reduce LookbackDays in UdmTablesList OR use windowed CDC (default for large tables) |
| ParquetSnapshotRegistry row stuck in `'created'` Status | Verifier never ran | Run `python3 tools/parquet_verify.py --source CCM --table AuditLog --apply` to flip created → verified |

---

## §10. What's NEW in this runbook vs prior versions

This runbook supersedes `TEST_PARQUET_TO_SCD2_PIPELINE.md` for the POST-D125-wiring state. Key differences:

| Aspect | Old (`TEST_PARQUET_TO_SCD2_PIPELINE.md`) | This runbook |
|---|---|---|
| Audience | Module-level smoke tester (developer) | Operator running production orchestrator |
| Test mechanism | Custom smoke scripts per module | `main_large_tables.py` directly |
| Pipeline orchestration | Modules tested in isolation | Full D125 dispatch end-to-end |
| Parquet write | Custom script | `parquet_writer.write_parquet_snapshot()` invoked by orchestrator per B-544 v1 |
| Delete-detection | Not tested | Day-N vs day-N-1 Parquet diff per B-563 closure |
| Parity verification | Not tested | `tools/validate_parquet_vs_stage.py` (row-count + B-555 v2 `--hash-check`) |
| CDCMode integration | Not aware (predates D125) | Full B-542 + B-546 dispatch wired |

**D125 arc B-Ns this runbook exercises** (25 closures + 1 P-N):

| Component | B-Ns |
|---|---|
| Schema | B-542 `migrations/cdc_mode_column.py` |
| Operator CLIs | B-546 `flip_cdc_mode.py` + B-545/B-553/B-554/B-555 `validate_parquet_vs_stage.py` |
| Orchestrator dispatch | B-544 v1 + B-552 v1 + B-563 (`pipeline_steps.py` + `large_tables.py`) |
| Replay engine | B-552 v1 `replay_parquet_snapshot` + B-563 `run_parquet_delete_detection_step` |

---

*Authored 2026-05-19 post-D125 arc FULLY CODE-COMPLETE. Run this against test/dev environment first. Capture all SQL query outputs + audit-row metadata for post-run analysis. If you hit unexpected behavior, the `PipelineLog` (debug narrative) + `PipelineEventLog` (per-step timing/counts) are the canonical investigation surfaces — join on BatchId + TableName + SourceName.*
