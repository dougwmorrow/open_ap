# Test runbook — Parquet → SCD2 pipeline (CCM.AuditLog smoke)

Personal operator runbook. Not registered as RB-N. Walks the end-to-end smoke for the new Parquet → SCD2 path on one large table (`CCM.AuditLog`, ~96M rows) using existing built modules.

**Authored**: 2026-05-18 (session arc start). **Refreshed**: 2026-05-19 (post-R1 cohort B-N state update — see §10 Recent updates for the cohort closure deltas this runbook reflects).

---

## When to use this

You want to verify the new Parquet-write + SCD2-replay path works end-to-end before the D2 wiring lands in `main_large_tables.py`. The runbook tests every link in the chain in isolation:

| Stage | Module | Tool |
|---|---|---|
| Write parquet | `data_load/parquet_writer.py` (M1) | custom smoke script (this runbook) |
| Verify parquet | `data_load/parquet_registry_client.py` (M3) | `tools/parquet_verify.py` |
| Replay → SCD2 | `data_load/parquet_replay.py` (M2) + `scd2/engine.py::run_scd2()` | `tools/scd2_replay_smoke.py` |

## What this does NOT test

- The production large-table orchestrator (`main_large_tables.py`) — it does not call `write_parquet_snapshot()` today (B-336 + D2 plan target Phase 2 R1).
- Multi-day ordered replay — `replay_parquet_range()` is not built yet (B-332, Phase 2 R2 per closure-target fix at commit `0dc4f24` 2026-05-19; production CLI tracked as B-540 `tools/scd2_replay_range_smoke.py` per RB-15 placeholder reference at `05_RUNBOOKS.md` L1553). This runbook replays day-by-day in chronological order via a shell loop, which is the manual analog.
- Source verifier + E-12 phantom-update detection at the SCD2 layer — D18 engine-side parameter ⚫ implemented at R1.3 commit `4872581` 2026-05-18 (B-334 ⚫ CLOSED; `source_verifier_fn` keyword-only parameter on `run_scd2` + `run_scd2_targeted` + new helper `_apply_source_verifier_or_block` preserves CDC_VERIFY_STRICT_ON_FAILURE canonical semantic per CLAUDE.md Do-NOT rule). Orchestrator-side closure wiring at `small_tables.py` + `large_tables.py` (the closure that ACTUALLY calls source DB for verification) lands at R2 with D2 cutover; this runbook does NOT invoke the verifier — `source_verifier_fn=None` is the default behavior (skips verification).
- Tokenization step ordering — see `UDM_PIPELINE_REDESIGN_PARQUET_SOURCE_EXACT_2026-05-17.md` for the post-D2 design.

---

## Pre-flight

### 1. RHEL environment

- Linux RHEL with `MALLOC_ARENA_MAX=2` exported BEFORE Python starts (W-4).
- ODBC Driver 18 for SQL Server installed.
- Oracle Instant Client 19c installed (not needed for AuditLog/CCM specifically, but config.py imports may probe).
- `mssql-tools18` BCP utility at `/opt/mssql-tools18/bin/bcp`.
- Python 3.12.11 with `polars`, `connectorx`, `pyodbc`, `polars-hash`, `python-dotenv` installed.

### 2. Network drive mounted

```bash
mount | grep VendorFiles
ls -ld /VendorFiles/PROD/
```

Pick a parquet sub-directory and create it:

```bash
mkdir -p /VendorFiles/PROD/Parquet
touch /VendorFiles/PROD/Parquet/.smoke_probe && rm /VendorFiles/PROD/Parquet/.smoke_probe
```

### 3. `/etc/pipeline/.env` keys (D103 location)

Add or confirm:

```bash
# Pipeline env selection
PIPELINE_ENV=dev                                  # or 'prod'; defaults to 'dev' if unset

# Target UDM SQL Server (dev creds — switch to UDM_PROD_* when PIPELINE_ENV=prod)
UDM_CX_SERVER=<udm_sql_server>
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

# Parquet output dir — NEW for this smoke
PARQUET_OUTPUT_DIR=/VendorFiles/PROD/Parquet

# CSV staging dir (also used by Polars windowed extract as a side-effect)
CSV_OUTPUT_DIR=/VendorFiles/PROD/PythonIngestions

# Operational guards
MAX_RSS_GB=49.0
BCP_TIMEOUT=7200
```

File permissions per D103: `chmod 0400 /etc/pipeline/.env` ; owned by `pipeline:pipeline`.

Confirm with:

```bash
sudo -u pipeline python3 -c "
import utils.configuration as c
print('PIPELINE_ENV =', c.PIPELINE_ENV)
print('GENERAL_DB =', c.GENERAL_DB)
print('CSV_OUTPUT_DIR =', c.CSV_OUTPUT_DIR)
import os; print('PARQUET_OUTPUT_DIR =', os.environ.get('PARQUET_OUTPUT_DIR'))
"
```

### 4. Round 1 DDL deployed

The smoke requires these objects to exist in `General`:

- `General.ops.ParquetSnapshotRegistry` (table)
- `General.ops.PipelineBatchSequence` (sequence)
- `General.ops.PipelineEventLog` (table)
- `General.ops.PipelineLog` (table)
- `General.ops.IdempotencyLedger` (table — replay composes through it)
- `General.dbo.UdmTablesList` + `General.dbo.UdmTablesColumnsList` (config tables)

Probe:

```bash
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

Any `MISSING` → fix Round 1 deploy before continuing.

### 5. Source reachable

```bash
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

Use these numbers as the ground truth for end-of-test reconciliation.

---

## Procedure

### Step 1 — Seed `General.dbo.UdmTablesList` for AuditLog

```bash
python3 migrations/audit_log_cardtxn_config.py \
    --linked-server PDCAAGDNA02 --dry-run

python3 migrations/audit_log_cardtxn_config.py \
    --linked-server PDCAAGDNA02
```

Confirm:

```sql
SELECT SourceName, SourceObjectName, SourceDatabaseName, SourceSchemaName,
       SourceAggregateColumnName, SourceAggregateColumnType,
       FirstLoadDate, LookbackDays, StripSuffix, StageLoadTool,
       StageTableName, BronzeTableName
FROM General.dbo.UdmTablesList
WHERE SourceName='CCM' AND SourceObjectName='AuditLog';
```

Expected: one row with `StripSuffix=1`, `StageTableName='AuditLog'`, `BronzeTableName='AuditLog'`, `SourceAggregateColumnName='DateTime'`, `FirstLoadDate` populated.

### Step 2 — Create the setup helper script

Save the following at the repo root as `smoke_setup_auditlog.py`. One-shot script that:

- Extracts one day of AuditLog from source (smallest day in range to keep memory low).
- Ensures `UDM_Stage.ccm.AuditLog` + `UDM_Bronze.ccm.AuditLog` exist.
- Calls `sync_columns()` to populate `UdmTablesColumnsList` (which fills `TableConfig.pk_columns` on subsequent loads).

```python
"""One-shot infrastructure prep for the CCM.AuditLog parquet smoke.

Creates Stage + Bronze tables and populates UdmTablesColumnsList by
extracting one tiny day from source and feeding it to the canonical
schema/table_creator + schema/column_sync code paths.

Idempotent — re-running is safe.
"""
from __future__ import annotations
import logging, sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from extract.connectorx_sqlserver_extractor import extract_sqlserver_connectorx_windowed
from data_load.bcp_csv import add_row_hash
from schema.table_creator import ensure_stage_table, ensure_bronze_table
from schema.column_sync import sync_columns
from orchestration.table_config import TableConfigLoader
import utils.configuration as cfg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("smoke_setup_auditlog")

SOURCE_NAME = "CCM"
TABLE_NAME = "AuditLog"

def main() -> int:
    loader = TableConfigLoader()
    configs = loader.load_large_tables(source_name=SOURCE_NAME, table_name=TABLE_NAME)
    if not configs:
        log.error("No UdmTablesList row for %s.%s — run migrations/audit_log_cardtxn_config.py first",
                  SOURCE_NAME, TABLE_NAME)
        return 2
    tc = configs[0]
    if tc.first_load_date is None:
        log.error("FirstLoadDate is NULL — re-run the migration with --linked-server")
        return 2

    log.info("Stage  → %s", tc.stage_full_table_name)
    log.info("Bronze → %s", tc.bronze_full_table_name)

    # Pull one small day for schema inference. Pick FirstLoadDate; if that
    # day is huge, swap for any other quiet day.
    day = tc.first_load_date
    next_day = day + timedelta(days=1)

    csv_tmp = Path(cfg.CSV_OUTPUT_DIR) / "smoke_setup_auditlog"
    csv_tmp.mkdir(parents=True, exist_ok=True)

    log.info("Extracting one day [%s, %s) for schema inference", day, next_day)
    df, _csv = extract_sqlserver_connectorx_windowed(
        tc, csv_tmp, start_date=day, end_date=next_day,
    )
    if df.height == 0:
        log.warning("Day %s returned 0 rows — pick a different day for schema inference", day)
        return 1

    df = add_row_hash(df, exclude=tc.exclude_from_hash)
    log.info("Inferred schema from %d rows / %d cols", df.height, len(df.columns))

    stage_created = ensure_stage_table(tc, df)
    bronze_created = ensure_bronze_table(tc, df)
    log.info("Stage created=%s ; Bronze created=%s", stage_created, bronze_created)

    synced = sync_columns(tc)
    log.info("UdmTablesColumnsList sync result: %s (False = already populated)", synced)

    # Re-load config so pk_columns is materialized.
    tc2 = loader.load_large_tables(source_name=SOURCE_NAME, table_name=TABLE_NAME)[0]
    log.info("pk_columns after sync: %r", tc2.pk_columns)
    if not tc2.pk_columns:
        log.error("PK discovery failed — check source PK constraint on CCMREPORT.dbo.AuditLog "
                  "OR manually UPDATE UdmTablesColumnsList.IsPrimaryKey=1 for the PK column")
        return 2

    log.info("Setup complete. You can now run smoke_write_auditlog_parquet.py")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

Run:

```bash
python3 smoke_setup_auditlog.py
```

Verify:

```sql
SELECT Layer, ColumnName, OrdinalPosition, IsPrimaryKey
FROM General.dbo.UdmTablesColumnsList
WHERE SourceName='CCM' AND TableName='AuditLog'
ORDER BY Layer, OrdinalPosition;
```

Expected: rows for both `Layer='Stage'` and `Layer='Bronze'`, with `IsPrimaryKey=1` on `ID` (or whatever the source PK is).

### Step 3 — Create the parquet-write script

Save at repo root as `smoke_write_auditlog_parquet.py`:

```python
"""Day-by-day parquet write for CCM.AuditLog.

Iterates [FirstLoadDate, today). For each day: windowed extract -> add row
hash -> write_parquet_snapshot() -> log result. No Stage write, no Bronze
write, no CDC, no SCD2.

Re-runnable per day — but the registry UNIQUE on
(SourceName, TableName, BatchId, BusinessDate) means a re-run on a day that
already wrote with a different BatchId will succeed (different tuple), and
a re-run with the SAME BatchId on a SAME day will raise RegistryInsertConflict.
Easiest pattern: each invocation of this script allocates one fresh BatchId
and writes every missing day under it.
"""
from __future__ import annotations
import logging, sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import polars as pl
from extract.connectorx_sqlserver_extractor import extract_sqlserver_connectorx_windowed
from data_load.parquet_writer import write_parquet_snapshot
from data_load.bcp_csv import add_row_hash
from orchestration.table_config import TableConfigLoader
from utils.connections import cursor_for
from utils.errors import RegistryInsertConflict
import utils.configuration as cfg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("smoke_write_auditlog_parquet")

SOURCE_NAME = "CCM"
TABLE_NAME = "AuditLog"
END_DATE: date = date.today()                # adjust if you want a stop earlier than today

def allocate_batch_id() -> int:
    with cursor_for(cfg.GENERAL_DB) as cur:
        cur.execute("SELECT NEXT VALUE FOR General.ops.PipelineBatchSequence")
        return int(cur.fetchone()[0])

def main() -> int:
    loader = TableConfigLoader()
    configs = loader.load_large_tables(source_name=SOURCE_NAME, table_name=TABLE_NAME)
    if not configs:
        log.error("No UdmTablesList row — run smoke_setup_auditlog.py first")
        return 2
    tc = configs[0]
    if tc.first_load_date is None:
        log.error("FirstLoadDate is NULL")
        return 2

    batch_id = allocate_batch_id()
    log.info("Allocated BatchId=%d  range=[%s, %s)", batch_id, tc.first_load_date, END_DATE)

    csv_tmp = Path(cfg.CSV_OUTPUT_DIR) / "smoke_auditlog"
    csv_tmp.mkdir(parents=True, exist_ok=True)

    total_rows = 0
    total_files = 0
    day = tc.first_load_date
    while day < END_DATE:
        next_day = day + timedelta(days=1)
        try:
            df, _csv = extract_sqlserver_connectorx_windowed(
                tc, csv_tmp, start_date=day, end_date=next_day,
            )
        except Exception as exc:
            log.error("[%s] Extract failed: %s", day, exc)
            day = next_day
            continue

        if df.height == 0:
            log.info("[%s] 0 rows — no parquet written", day)
            day = next_day
            continue

        df = add_row_hash(df, exclude=tc.exclude_from_hash)

        try:
            result = write_parquet_snapshot(
                df,
                source_name=SOURCE_NAME,
                table_name=TABLE_NAME,
                business_date=day,
                batch_id=batch_id,
            )
        except RegistryInsertConflict as exc:
            log.warning("[%s] Already written (registry conflict) — skipping. %s", day, exc)
            day = next_day
            continue

        log.info(
            "[%s] rows=%d size=%dB sha=%s.. registry_id=%d -> %s",
            day, result.row_count, result.file_size_bytes,
            result.sha256[:12], result.registry_id, result.file_path,
        )
        total_rows += result.row_count
        total_files += 1
        day = next_day

    log.info("Done. files=%d rows=%d batch_id=%d", total_files, total_rows, batch_id)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

Run:

```bash
python3 smoke_write_auditlog_parquet.py 2>&1 | tee smoke_write.log
```

For a 96M-row table over multi-year history, expect this to take hours and consume significant network I/O. Monitor `MAX_RSS_GB` from `utils/configuration.py` — Polars holds each day's DF in memory before write. If a single day is unusually large (millions of rows), the script will spike RSS for that day.

Sanity check after a partial run:

```sql
-- Total snapshots registered
SELECT COUNT(*) AS day_count, SUM(RowCount) AS total_rows,
       MIN(BusinessDate) AS first_day, MAX(BusinessDate) AS last_day,
       SUM(CompressedBytes)/1024/1024 AS total_mb
FROM General.ops.ParquetSnapshotRegistry
WHERE SourceName='CCM' AND TableName='AuditLog' AND Status='created';

-- Days with zero parquet (compare against expected calendar)
SELECT BusinessDate FROM General.ops.ParquetSnapshotRegistry
WHERE SourceName='CCM' AND TableName='AuditLog'
ORDER BY BusinessDate;
```

### Step 4 — Verify each parquet file (SHA-256 + status flip)

For one specific day:

```bash
python3 tools/parquet_verify.py \
    --source CCM --table AuditLog \
    --business-date-from 2018-01-01 --business-date-to 2018-01-01 \
    --apply
```

For a date range:

```bash
python3 tools/parquet_verify.py \
    --source CCM --table AuditLog \
    --business-date-from 2018-01-01 --business-date-to 2018-12-31 \
    --apply
```

Successful verification flips `ParquetSnapshotRegistry.Status` from `created` to `verified`.

Confirm:

```sql
SELECT Status, COUNT(*) FROM General.ops.ParquetSnapshotRegistry
WHERE SourceName='CCM' AND TableName='AuditLog'
GROUP BY Status;
```

Expected after full verify: every row in `verified` status.

### Step 5 — Replay each day into SCD2

`tools/scd2_replay_smoke.py` replays ONE registered parquet snapshot into Bronze SCD2 per invocation. Multi-day ordered replay (`replay_parquet_range()` per B-332) does not exist yet, so loop manually in chronological order.

Test ONE day end-to-end first:

```bash
# Get the registry_id for one day
python3 - <<'PY'
import pyodbc, utils.configuration as c
conn = pyodbc.connect(
    f"DRIVER={{{c.ODBC_DRIVER}}};SERVER={c.SQL_SERVER_HOST},{c.SQL_SERVER_PORT};"
    f"DATABASE={c.GENERAL_DB};UID={c.SQL_SERVER_USER};PWD={c.SQL_SERVER_PASSWORD};"
    "Encrypt=yes;TrustServerCertificate=yes"
)
cur = conn.cursor()
cur.execute("""
    SELECT TOP 1 BatchId, BusinessDate
    FROM General.ops.ParquetSnapshotRegistry
    WHERE SourceName='CCM' AND TableName='AuditLog' AND Status='verified'
    ORDER BY BusinessDate ASC
""")
row = cur.fetchone()
print(f"First verified day: BatchId={row[0]}  BusinessDate={row[1]}")
PY

# Dry-run first (default — no Bronze write)
python3 -m tools.scd2_replay_smoke \
    --source CCM --table AuditLog \
    --business-date <YYYY-MM-DD> --original-batch-id <BatchId> \
    --dry-run

# Apply
python3 -m tools.scd2_replay_smoke \
    --source CCM --table AuditLog \
    --business-date <YYYY-MM-DD> --original-batch-id <BatchId> \
    --apply
```

Exit codes:

- `0` — replay + SCD2 succeeded (or dry-run completed)
- `1` — retryable (e.g. `LedgerLockTimeout`)
- `2` — fatal (`RegistryNotFound`, `RegistryStatusInvalid`, `ParquetReplayError`, `MissingPrimaryKey`)

Then loop in chronological order for every day:

```bash
python3 - <<'PY' > /tmp/auditlog_days.tsv
import pyodbc, utils.configuration as c
conn = pyodbc.connect(
    f"DRIVER={{{c.ODBC_DRIVER}}};SERVER={c.SQL_SERVER_HOST},{c.SQL_SERVER_PORT};"
    f"DATABASE={c.GENERAL_DB};UID={c.SQL_SERVER_USER};PWD={c.SQL_SERVER_PASSWORD};"
    "Encrypt=yes;TrustServerCertificate=yes"
)
cur = conn.cursor()
cur.execute("""
    SELECT BatchId, CONVERT(varchar(10), BusinessDate, 23)
    FROM General.ops.ParquetSnapshotRegistry
    WHERE SourceName='CCM' AND TableName='AuditLog' AND Status='verified'
    ORDER BY BusinessDate ASC
""")
for r in cur.fetchall():
    print(f"{r[0]}\t{r[1]}")
PY

while IFS=$'\t' read -r batch_id business_date; do
    echo "Replaying $business_date (batch_id=$batch_id)..."
    python3 -m tools.scd2_replay_smoke \
        --source CCM --table AuditLog \
        --business-date "$business_date" --original-batch-id "$batch_id" \
        --apply || echo "FAILED: $business_date" >> /tmp/auditlog_replay_failures.log
done < /tmp/auditlog_days.tsv
```

Order matters: SCD2-P1-b chained `UdmSourceEndDate` semantics require chronological replay (per B-332 rationale).

---

## Validation

### Row count reconciliation

```sql
-- Source ground truth (run on CCM source)
SELECT COUNT_BIG(*) FROM CCMREPORT.dbo.AuditLog;

-- Total rows landed in parquet
SELECT SUM(RowCount) FROM General.ops.ParquetSnapshotRegistry
WHERE SourceName='CCM' AND TableName='AuditLog' AND Status IN ('created','verified');

-- Bronze active rows after SCD2
SELECT COUNT_BIG(*) FROM UDM_Bronze.ccm.AuditLog WHERE UdmActiveFlag = 1;

-- Bronze total versions (active + closed)
SELECT COUNT_BIG(*) FROM UDM_Bronze.ccm.AuditLog;
```

For a first-load smoke (no source updates between extraction and replay):
- Source count ≈ parquet `SUM(RowCount)` ≈ Bronze total (small drift expected from source motion during the multi-hour test).
- Bronze active rows = source count for PKs that exist exactly once in source.

### SCD2 invariants on Bronze

```sql
-- V-4: every active PK should have exactly one row
SELECT ID, COUNT(*) AS active_count
FROM UDM_Bronze.ccm.AuditLog
WHERE UdmActiveFlag = 1
GROUP BY ID
HAVING COUNT(*) > 1;
-- Expected: zero rows

-- SCD2-P1-c: active rows must carry UdmSourceEndDate = '2999-12-31'
SELECT COUNT(*) FROM UDM_Bronze.ccm.AuditLog
WHERE UdmActiveFlag = 1 AND UdmSourceEndDate <> '2999-12-31';
-- Expected: zero rows

-- B-4: no orphan in-flight rows
SELECT COUNT(*) FROM UDM_Bronze.ccm.AuditLog
WHERE UdmActiveFlag = 0 AND UdmEndDateTime IS NULL
  AND UdmScd2Operation IN ('U','R');
-- Expected: zero rows
```

### Audit-log inspection

```sql
SELECT TOP 50 EventType, Status, RowsInserted, RowsUpdated, RowsClosed, Metadata
FROM General.ops.PipelineEventLog
WHERE TableName='AuditLog' AND SourceName='CCM'
ORDER BY StartedAt DESC;
```

Look for `CLI_PARQUET_VERIFY`, `CLI_SCD2_REPLAY_SMOKE`, `PARQUET_VERIFY`, `REPLAY`, `SCD2_PROMOTION` events.

### Parquet file durability spot-check

```bash
# Pick a registered parquet at random and re-SHA it manually
sqlcmd -S "$UDM_CX_SERVER" -d General -U "$UDM_DEV_UID" -P "$UDM_DEV_PASSWORD" -Q "
SET NOCOUNT ON;
SELECT TOP 1 NetworkDrivePath, ContentChecksum
FROM ops.ParquetSnapshotRegistry
WHERE SourceName='CCM' AND TableName='AuditLog'
ORDER BY NEWID();
"
sha256sum /VendorFiles/PROD/Parquet/CCM/AuditLog/year=YYYY/month=MM/day=DD/<batch>.parquet
```

Two hex strings should match exactly.

---

## Rollback / cleanup

**This smoke creates Stage + Bronze tables, populates `UdmTablesColumnsList`, writes parquet files, and writes Bronze SCD2 rows.** Decide intentionally whether to keep or wipe each.

### Wipe everything for a clean re-test

```sql
-- Drop Bronze (destroys SCD2 history for AuditLog)
DROP TABLE IF EXISTS UDM_Bronze.ccm.AuditLog;

-- Drop Stage (this smoke does not write to Stage, but setup created it)
DROP TABLE IF EXISTS UDM_Stage.ccm.AuditLog;

-- Clear column metadata
DELETE FROM General.dbo.UdmTablesColumnsList
WHERE SourceName='CCM' AND TableName='AuditLog';

-- Clear registry rows (also lets you re-write under fresh BatchIds)
DELETE FROM General.ops.ParquetSnapshotRegistry
WHERE SourceName='CCM' AND TableName='AuditLog';

-- Clear ledger rows from replay attempts
DELETE FROM General.ops.IdempotencyLedger
WHERE EventType IN ('PARQUET_REPLAY','REPLAY','SCD2_PROMOTION')
  AND Metadata LIKE '%"table_name": "AuditLog"%';

-- Clear audit events (optional — keep for forensics if you prefer)
DELETE FROM General.ops.PipelineEventLog
WHERE TableName='AuditLog' AND SourceName='CCM';
DELETE FROM General.ops.PipelineLog
WHERE TableName='AuditLog' AND SourceName='CCM';
```

Then on disk:

```bash
rm -rf /VendorFiles/PROD/Parquet/CCM/AuditLog/
rm -rf /VendorFiles/PROD/PythonIngestions/smoke_setup_auditlog/
rm -rf /VendorFiles/PROD/PythonIngestions/smoke_auditlog/
```

Leave `General.dbo.UdmTablesList` row in place — re-seeding via the migration is idempotent and cheap.

### Wipe only Bronze (re-replay)

If parquet files are good but you want to re-test SCD2 replay:

```sql
DELETE FROM UDM_Bronze.ccm.AuditLog;
DELETE FROM General.ops.IdempotencyLedger
WHERE EventType IN ('PARQUET_REPLAY','REPLAY','SCD2_PROMOTION')
  AND Metadata LIKE '%"table_name": "AuditLog"%';
```

Then re-run Step 5.

---

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `PARQUET_OUTPUT_DIR env key is unset` | env not loaded into the Python process | Confirm `/etc/pipeline/.env` mode 0400 + owner; restart shell |
| `Atomic rename failed ... ENOSPC` | VendorFiles full | Free space or remount; re-run the day |
| `RegistryInsertConflict` on write | same `(SourceName, TableName, BatchId, BusinessDate)` already registered | Either re-run the script (new BatchId) or delete the conflicting registry row |
| `parquet_verify` reports `RegistryHashMismatch` | file mutated post-write OR write was non-deterministic | Re-write the day and verify (a hash mismatch is destruction-class — never `--force` past it) |
| `scd2_replay_smoke` exits 2 `MissingPrimaryKey` | `UdmTablesColumnsList.IsPrimaryKey` is 0 for every Bronze row | Re-run `smoke_setup_auditlog.py` OR `UPDATE UdmTablesColumnsList SET IsPrimaryKey=1 WHERE Layer='Bronze' AND ColumnName='ID' AND SourceName='CCM' AND TableName='AuditLog'` |
| `scd2_replay_smoke` exits 2 `RegistryStatusInvalid` | Status is `created` not `verified` | Run `tools/parquet_verify.py --apply` on that day first |
| Bronze duplicate active rows (V-4) | replay ran out of order OR crash recovery left orphan | Apply `tools/repair_scd2.py` OR wipe Bronze + replay in chronological order |
| Polars OOM on a single day | day is too large for memory | Sub-day window in `smoke_write_auditlog_parquet.py` (split by hour); raise `MAX_RSS_GB` only if hardware allows |
| BCP hang during SCD2 first-run insert | TLS keep-alive drop | Per `BCP-HANG-FIX-v3`, first-run Bronze loads use TABLOCK + 100K batch; if still hanging, lower `BCP_PACKET_SIZE` further |

---

## Known limitations

1. **Multi-day replay must be sequential.** `replay_parquet_range()` (B-332; closure target Phase 2 R2) is not built; the shell loop in Step 5 is the manual analog. Sharding across workers will violate SCD2-P1-b chain semantics — do not parallelize. **Production-grade range CLI** tracked as B-540 `tools/scd2_replay_range_smoke.py` (prerequisite for B-344 RB-15 SCD2 corruption replay runbook authoring).
2. **Source verifier + E-12 detection** — engine-side parameter `source_verifier_fn` ⚫ LANDED at R1.3 commit `4872581` 2026-05-18 (B-334 + B-498 ⚫ CLOSED via this commit) at `scd2/engine.py::run_scd2` + `run_scd2_targeted`; STRICT-env-var parser subsequently unified to canonical `== "1"` semantic at commit `599124b` 2026-05-19 (B-538 ⚫ CLOSED). However, the orchestrator-side closure that ACTUALLY connects to source DB for verification is pending R2 D2 cutover wiring. Since this smoke runbook invokes `scd2/engine.run_scd2()` WITHOUT passing a `source_verifier_fn` (default `None`), the verifier branch is skipped — this is correct behavior for a smoke test of Parquet→SCD2 mechanics. Full E-12 phantom-update protection requires the orchestrator-side wiring + a real source connection.
3. **PII tokenization** is not invoked by this smoke. If AuditLog carries P5 PII, parquet snapshots written by this runbook contain plaintext. Production D2 / source-exact design (see `UDM_PIPELINE_REDESIGN_PARQUET_SOURCE_EXACT_2026-05-17.md`) tokenizes BEFORE parquet write; this smoke does not.
4. **First-load convention.** This runbook assumes Bronze is empty at start. Re-running on a populated Bronze will exercise SCD2 update + close paths, which is a different test.
5. **96M rows is a multi-hour smoke.** Run from a screen/tmux session. Budget RHEL server I/O accordingly.
6. **Parquet partition layout** is `<PARQUET_OUTPUT_DIR>/CCM/AuditLog/year=YYYY/month=MM/day=DD/<BatchId>.parquet` per D45.2 Hive convention. Do not rename or hand-edit the directory tree.

---

## After the test

Capture for the lessons file (or wherever you keep notes):

- Per-day extraction wall-clock (slowest / fastest / median).
- Average parquet size per million rows (for `B-333` Phase 3 H-drive capacity gate).
- Any Polars OOM days.
- Any SCD2 invariant violations surfaced by the validation queries.
- Exit-code distribution from `scd2_replay_smoke.py`.

These numbers feed Phase 2/3 sizing and inform whether `MaxRowsPerDay` (UdmTablesList) needs to be set on AuditLog for the production wiring once it lands.


---

## Recent updates (post-R1 cohort closure deltas — added 2026-05-19)

This runbook was authored 2026-05-18 at session arc start. Since then, the R1 cohort + remediation arc landed across 8 commits (`4b3e5c9` → `7e67f3a`) and changed the state of several B-Ns referenced above. This section enumerates the closure deltas + what they mean for the smoke procedure.

### B-Ns CLOSED during the R1 cohort (relevant to this runbook)

| B-N | Status delta | Commit | What it means for the smoke |
|---|---|---|---|
| **B-345** | 🟡 → ⚫ CLOSED | `4b3e5c9` 2026-05-18 | `_LOCK_RESOURCE` promoted to public `TABLE_LOCK_RESOURCE_FORMAT` in `orchestration/table_lock.py`. Future B-540 replay tool MUST import this canonical format string. Smoke procedure unchanged. |
| **B-334** | 🟡 → ⚫ CLOSED | `4872581` 2026-05-18 | `source_verifier_fn: Callable \| None = None` parameter added to `run_scd2` + `run_scd2_targeted`. Smoke runbook calls these helpers WITHOUT passing the parameter (default None → verifier branch skipped). No procedure change. |
| **B-498** | 🟡 → ⚫ CLOSED | `4872581` 2026-05-18 | `_apply_source_verifier_or_block` helper preserves `CDC_VERIFY_STRICT_ON_FAILURE=1` semantic per CLAUDE.md Do-NOT rule. Not exercised by this smoke (verifier branch skipped per default). |
| **B-337** | 🟡 → ⚫ CLOSED | `28c8d25` 2026-05-18 | `utils/idempotency_ledger.py::startup_recovery_sweep` extended with D119 forensic-preservation discipline — legacy pre-D2 EventTypes (`SCD2_PROMOTION` + `CDC_PROMOTION`) EXCLUDED from auto-sweep. Smoke procedure: ledger rows from this runbook use `EVENT_TYPE='PARQUET_WRITE'` + `'REPLAY'` (post-D2 canonical); NOT affected by the legacy-exclusion. |
| **B-538** | 🟡 → ⚫ CLOSED | `599124b` 2026-05-19 | `CDC_VERIFY_STRICT_ON_FAILURE` env-var parser unified to canonical `== "1"` literal-match. Set the env var to literal `"1"` (default if absent) for STRICT; literal `"0"` (or any non-`"1"` value) for non-strict. Smoke procedure: env var not needed for default behavior. |
| **B-541** | 🟡 → ⚫ CLOSED | `599124b` 2026-05-19 | `udm-cohort-review` SKILL.md strengthened with read-only audit contract. Operator/audit workflow only; no smoke-procedure impact. |

### B-Ns still 🟡 Open (relevant to this runbook)

| B-N | Severity | Closure target | What it means for the smoke |
|---|---|---|---|
| **B-332** | HIGH | Phase 2 R2 | `data_load/parquet_replay.py::replay_parquet_range()` (sequential per-day function) — not built. This smoke runbook replays day-by-day via shell loop in Step 5 as the manual analog. |
| **B-336** | MEDIUM | Phase 2 R1 | `orchestration/small_tables.py` lacks `write_parquet_snapshot()` call (small-table path). Not exercised by this smoke (CCM.AuditLog is large-table). |
| **B-540** | HIGH | Phase 2 R2 | `tools/scd2_replay_range_smoke.py` (production-grade CLI; D74/D75/D76 contract; `CLI_SCD2_REPLAY_RANGE_SMOKE` EventType). Replaces this runbook's Step 5 shell loop with a single command. Prerequisite for B-344 RB-15 SCD2 corruption replay runbook authoring. |
| **B-344** | HIGH | Phase 2 R2 (after B-540 lands) | RB-15 SCD2 corruption replay full-body runbook at `05_RUNBOOKS.md` L1548-1554. Adoption draft at `docs/migration/RB15_SCD2_CORRUPTION_REPLAY_PLAN_2026-05-18.md` (🟡 PROVISIONAL). |
| **B-4** | (gotcha; ongoing) | n/a | Orphan inactive Bronze row cleanup — `scd2/engine.py::_cleanup_orphaned_inactive_rows()` runs automatically at SCD2 entry; smoke procedure inherits the cleanup for free. |
| **B-333** | HIGH | Phase 3 R1 prerequisite | H-drive actual capacity verification + 7-year Parquet footprint projection. Capture parquet size per million rows during this smoke (see §After the test). |

### What changed in the smoke runbook this revision (2026-05-19)

- Lines 19-22 (§"What this does NOT test"): B-332 closure target Phase 2 R1 → R2; B-334 status 🟡 → ⚫ (with engine-side caveat); added B-540 forward-reference for production range CLI
- Lines 694-695 (§Known limitations): same closure-target + status updates; added B-540 + B-344 prerequisite chain explanation
- This §10 added (Recent updates section) — captures the full delta in tabular form for forensic-audit-grade lookup

### Citation provenance

All B-N status claims in this revision verified against `docs/migration/BACKLOG.md` at HEAD = `7e67f3a` 2026-05-19. Cross-cohort review of the closure cohort verified by Agent `a843ad09d24f2a607` 2026-05-19 (verdict: 🟢 PASS).
