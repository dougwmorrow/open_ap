# Oracle/SQL Server -> SQL Server data pipeline (Python + Polars + BCP)

ETL pipeline extracting from Oracle (DNA) and SQL Server (CCM, EPICOR) sources into a medallion architecture: UDM_Stage (CDC), UDM_Bronze (SCD2). Metadata-driven via General.dbo.UdmTablesList. Runs on Linux RedHat Server.

## Environment & Dependencies
- Python 3.12.11
- Oracle Instant Client 19c (for oracledb thick mode and ConnectorX oracle:// connections)
- ODBC Driver 18 for SQL Server (for BCP, pyodbc, and ConnectorX mssql:// connections)
- Key packages: polars, polars-hash, connectorx, oracledb, pyodbc
- BCP utility (mssql-tools18)
- .env file location: `/etc/pipeline/.env` (D103 — system-managed, mode 0400, owned by pipeline:pipeline; outside the `/debi` Claude working-directory boundary). Legacy location `/debi/.env` is deprecated and slated for migration — see B182 migration runbook (BACKLOG.md). `config.py` must read from `/etc/pipeline/.env` going forward.

## Structure
- config.py - env vars, DB names, BCP thresholds, paths (.env at `/etc/pipeline/.env` per D103; legacy `/debi/.env` deprecated)
- sources.py - source system registry (Oracle/SQL Server connection factories)
- connections.py - SQL Server target DB connections (Stage/Bronze/General), cursor_for() context manager
- cli_common.py - shared CLI boilerplate (environment setup, logging, startup checks, RSS monitoring)
- main_small_tables.py - CLI entry point for small tables
- main_large_tables.py - CLI entry point for large tables
- extract/ — Source Data Extraction
  - router.py - extraction routing: routes Oracle/SQL Server × ConnectorX/oracledb (E-3)
  - connectorx_oracle_extractor.py - ConnectorX Oracle extraction -> Polars -> BCP CSV
  - udm_connectorx_extractor.py - ConnectorX for internal UDM SQL Server reads
  - oracle_extractor.py - oracledb fallback (date-chunked with INDEX hints)
  - connectorx_sqlserver_extractor.py - ConnectorX SQL Server extraction -> Polars -> BCP CSV
- data_load/ — BCP Loading Infrastructure
  - bcp_loader.py - BCP subprocess wrapper (CSV -> SQL Server)
  - bcp_csv.py - BCP CSV helpers: hashing (polars-hash), sanitization, column reorder (P0-1), CSV write
  - row_hash.py - row hashing (polars-hash SHA-256, fallback hashlib)
  - sanitize.py - DataFrame sanitization (strings, BIT columns, UInt64, Oracle dates)
  - bcp_format.py - BCP XML format file generation
  - schema_utils.py - shared schema metadata queries for column validation and PK type lookup (P0-3)
  - index_management.py - index disable/rebuild around BCP loads
  - credentials_loader.py - GPG/TPM2 .env loader, Snowflake RSA key materialization, startup credentials audit (Round 3 § 3.1; Wave 1.3 build 2026-05-13; surface: `load_credentials`, `release_snowflake_key`, `clear_cache`, `CredentialsDict`, `PassphraseSource`)
  - parquet_registry_client.py - Parquet medallion registry status walker (created→verified→replicated→archived→purged) backed by IdempotencyLedger (Round 3 § 1.3; Wave 2.2 build 2026-05-13; surface: `verify_parquet_snapshot`, `mark_replicated`, `mark_archived`, `mark_missing`, `mark_purged`, `mark_replication_failed`, `query_snapshot`, `is_legal_transition`, `ParquetVerifyResult`; introduces `PARQUET_*` EventType family — see B-229)
  - vault_client.py - PiiVault stored-procedure wrapper (SP-1/SP-2/SP-10/SP-12) with connection-pool management (Round 3 § 2.3; Wave 2.3 build 2026-05-13; surface: `call_vault_sp`, `configure_vault_connection_pool`, `release_vault_connection_pool`)
- cdc/ — Change Data Capture
  - engine.py - Polars CDC: hash comparison, detect inserts/updates/deletes, NULL PK filter (P0-4)
  - reconciliation/ - full column-by-column reconciliation subpackage (P3-4)
  - extraction_state.py - per-table extraction-attempt ledger + trust gate + re-extraction detection (Round 3 § 4.2; Wave 1.4 build 2026-05-13; surface: `ExtractionState`, `is_date_trusted`, `most_recent_success`, `is_reextraction`, `get_extraction_attempt`, `record_extraction_attempt`)
- scd2/ — Slowly Changing Dimension Type 2
  - engine.py - Polars SCD2: Bronze comparison, UPDATES via typed staging (P0-3), INSERTs via BCP
- orchestration/ — Table Processing Flows
  - small_tables.py - orchestrator for small tables (no date column)
  - large_tables.py - orchestrator for large tables (date-chunked, per-day checkpoint)
  - guards.py - shared extraction guard logic (parameterized thresholds, baseline retrieval)
  - pipeline_steps.py - shared CDC/SCD2 promotion steps
  - table_config.py - TableConfig + TableConfigLoader from General.dbo.UdmTablesList
  - table_lock.py - sp_getapplock table-level locking to prevent concurrent runs (P1-2)
  - pipeline_state.py - extraction state tracking, gap detection, checkpoints
  - range_scheduler.py - windowed-CDC date-range planner (FirstLoadDate + LookbackDays + trust-gate composition over `cdc/extraction_state.py`); produces ordered date plan for large-table per-day processing (Round 3 § 5.1; Wave 2.1 build 2026-05-13; surface: `plan_extraction_range`, `ExtractionPlan`)
- schema/ — DDL & Schema Management
  - evolution.py - schema drift detection: ADD new cols, WARN removed, ERROR type changes (P0-2)
  - column_sync.py - auto-populate UdmTablesColumnsList + PK discovery from source
  - table_creator.py - auto-create Stage/Bronze tables from DataFrame dtypes
  - staging_cleanup.py - orphaned staging table cleanup at pipeline start (P3-3)
- migrations/ — One-time schema migration scripts
  - b1_hash_varchar64.py - ALTER _row_hash/UdmHash from BIGINT to VARCHAR(64)
- observability/ — Logging & Metrics
  - event_tracker.py - PipelineEventTracker context manager -> General.ops.PipelineEventLog
  - log_handler.py - SqlServerLogHandler (logging.Handler) -> General.ops.PipelineLog (v2 cutover Round 3 § 6.2; Wave 2.4 build 2026-05-13 PRESERVES v1 API — `SqlServerLogHandler`, `set_context()` — drop-in replacement; v2 surface adds: `set_log_context`, `clear_log_context`)
  - sensitive_data_filter.py - logging.Filter redacting P5 PII patterns (`record.msg` + `record.args`) before log emission; module-import-time pattern registry (Round 3 § 6.1; Wave 1.2 build 2026-05-13; surface: `SensitiveDataFilter`, `register_pii_pattern`, `SENSITIVE_PATTERNS`)
- utils/ — Shared Utilities
  - __init__.py - package marker
  - configuration.py - shared configuration constants + helpers (legacy `config.py` reference at top of Structure list also covers `.env` location per D103)
  - connections.py - SQL Server target DB connections (Stage/Bronze/General), cursor_for() context manager (also referenced top-of-Structure)
  - cli_common.py - shared CLI boilerplate (environment setup, logging, startup checks, RSS monitoring) (also referenced top-of-Structure)
  - sources.py - source system registry (Oracle/SQL Server connection factories) (also referenced top-of-Structure)
  - safe_concat.py - schema-validating `pl.concat()` wrapper (W-7 guardrail)
  - errors.py - canonical PipelineError two-tier hierarchy (PipelineFatalError / PipelineRetryableError + ~28 concrete subclasses) per D68; imported by every Round 3 module (Round 6 § 4.6 + Round 3 § 8.1; Wave 0 build 2026-05-13; surface: `PipelineError`, `PipelineFatalError`, `PipelineRetryableError` + concrete subclasses including `RegistryStatusInvalid`, `RegistryFileNotFound`, `RegistryHashMismatch`, `RegistryInsertConflict`, `RegistryNotFound`, `VaultUnavailable`, `VaultConfigError`, `LedgerStepFailed`, `LedgerStuck`, `LedgerConfigError`, `FilterConfigError`, `ParityFatalError`, `InvalidTrustGate`)
  - idempotency_ledger.py - canonical D15 idempotency-ledger context manager around `General.ops.IdempotencyLedger`; per-step crash-recovery short-circuit + startup-recovery sweep (Round 3 § 4.1; Wave 1.1 build 2026-05-13; surface: `LedgerStep`, `ledger_step`, `startup_recovery_sweep`)

## Known Issues & Backlog
See **TODO.md** for the remaining edge cases and hardening work. All 14 edge cases from the *Validating 14 Edge Cases in a Polars-BCP-CDC-SCD2 Pipeline on RHEL* research have been audited — 12 are fully implemented, 2 have remaining work:
- **P2-1 (polars-hash migration):** `add_row_hash()` now uses polars-hash plugin for deterministic, Rust-native hashing stable across Polars versions and Python sessions. Replaced native `hash_rows()` which was non-deterministic across sessions (GitHub #3966, #7758).
- **P3-2 (ConnectorX Oracle timezone):** oracledb path uses TRUNC() — fully mitigated. ConnectorX windowed path now also uses TRUNC() in WHERE clauses to prevent midnight boundary drift.
- Review TODO.md before starting any new feature work.

## Commands
- Run small tables: python3 main_small_tables.py --workers 4
- Single table: python3 main_small_tables.py --table ACCT --source DNA
- List tables: python3 main_small_tables.py --list-tables
- Extract specific source: python3 main_small_tables.py --workers 4 --source DNA
- Run large tables: python3 main_large_tables.py --workers 6

## BCP CSV Contract (Single Source of Truth)
All CSV writers MUST produce files matching this exact specification. Any deviation will cause BCP load failures or data corruption.
```
Delimiter:          tab (\t)
Row terminator:     LF only (-r 0x0A)
Header:             none
Quoting:            quote_style='never'
NULL representation: empty string
Datetime format:    '%Y-%m-%d %H:%M:%S.%3f'
BIT columns:        Int8 (0/1) — never True/False
Hash columns:       Full SHA-256 hex string, VARCHAR(64) (B-1)
UInt64 (non-hash):  .reinterpret(signed=True) -> Int64
String sanitization: replace \t \n \r \x00 with empty string BEFORE write_csv
Batch size:         write_csv(batch_size=4096) to avoid memory spikes
```

## Table Naming Conventions
Naming is driven by UdmTablesList. Custom names override the default when StageTableName or BronzeTableName is populated. The trailing `_cdc` / `_scd2_python` suffixes can be dropped per-table by setting `StripSuffix = 1`.

**Example: ACCT table from DNA source (schema: osibank), StripSuffix=0 (default)**

| Layer | Default Name | Custom Name Override |
|-------|-------------|---------------------|
| Source | `DNA.osibank.ACCT` | n/a |
| Stage (CDC) | `UDM_Stage.DNA.ACCT_cdc` | `UDM_Stage.DNA.{StageTableName}_cdc` |
| Bronze (SCD2) | `UDM_Bronze.DNA.ACCT_scd2_python` | `UDM_Bronze.DNA.{BronzeTableName}_scd2_python` |

Pattern: `{target_db}.{SourceName}.{table_name}_{suffix}`
- Stage suffix: `_cdc`
- Bronze suffix: `_scd2_python`
- The schema in UDM_Stage and UDM_Bronze is the SourceName (e.g., DNA, CCM, EPICOR), NOT the source schema

**SS-1: StripSuffix=1 (opt-in, large tables migrating off the legacy T-SQL pipeline)**

| Layer | Default Name (StripSuffix=1) | Custom Name Override (StripSuffix=1) |
|-------|------------------------------|--------------------------------------|
| Stage (CDC) | `UDM_Stage.DNA.ACCT` | `UDM_Stage.DNA.{StageTableName}` |
| Bronze (SCD2) | `UDM_Bronze.DNA.ACCT` | `UDM_Bronze.DNA.{BronzeTableName}` |

Default StripSuffix=0 preserves every existing table's behavior. Set per-table when downstream consumers have migrated off the legacy `_scd2`/`_python`-suffixed names. Migration scripts: `migrations/strip_suffix_column.py` (adds the column), `migrations/audit_log_cardtxn_config.py` (per-table opt-in for AuditLog and CARDTXN).

## Data Flow (per table)

### Small Tables (no date column - full extract each run)
Source (Oracle/SQL Server)
  -> ConnectorX full extract -> Polars DataFrame
  -> add _row_hash (polars-hash, deterministic across sessions) + _extracted_at
  -> Write BCP CSV (per BCP CSV Contract above)
  -> Ensure stage/bronze tables exist in UDM (auto-create from DataFrame dtypes)
  -> Schema evolution: detect new/removed/changed columns (P0-2)
  -> Column sync: auto-populate UdmTablesColumnsList + discover PKs from source
  -> Empty extraction guard: skip CDC if row count drops >90% vs previous run (P1-1)
  -> Table lock: sp_getapplock prevents concurrent runs on the same table (P1-2)
  -> CDC promotion (Polars in-memory comparison with existing CDC table)
        NULL PK filter (P0-4) -> anti-join inserts, hash compare updates, reverse anti-join deletes
        Column reorder to match target INFORMATION_SCHEMA ordinal position (P0-1)
        Staging tables use actual PK types from target (P0-3)
        columns: _cdc_operation (I/U/D), _cdc_valid_from/to, _cdc_is_current, _cdc_batch_id
        -> Capture changes via BCP into staging table
  -> SCD2 promotion (Polars comparison: CDC current vs Bronze active)
        Staging tables use actual PK types from target (P0-3)
        columns: UdmHash, UdmEffectiveDateTime, UdmEndDateTime, UdmActiveFlag, UdmScd2Operation
        -> UPDATEs via BCP staging table + MERGE
        -> INSERTs via BCP (append-only, never truncate Bronze)

### Large Tables (date-chunked - incremental extraction)
Per-day processing pipeline: extract one day at a time → windowed CDC → targeted SCD2 → checkpoint → next day.

Source (Oracle/SQL Server)
  -> Windowed extract (single day via SourceAggregateColumnName) -> Polars DataFrame
  -> add _row_hash (polars-hash) + _extracted_at
  -> Write BCP CSV (per BCP CSV Contract above)
  -> Ensure stage/bronze tables exist (first day only)
  -> Schema evolution (P0-2)
  -> Column sync (first load only)
  -> Table lock: sp_getapplock prevents concurrent runs (P1-2)
  -> Windowed CDC (P1-3/P1-4): compare only within extraction date window
        NULL PK filter (P0-4) -> anti-join inserts, hash compare updates
        Delete detection scoped to extraction window only (P1-4) — rows outside window untouched
        Column reorder (P0-1), typed staging tables (P0-3)
  -> Targeted SCD2 (P1-3): PK-scoped Bronze read via staging table join (not full table load)
  -> Checkpoint date as SUCCESS in PipelineExtractionState (P1-5)
  -> CSV cleanup
  -> Next day...

**Design decisions (resolved):**
- **Memory bounding (P1-3/P2-4):** Processing one day at a time keeps memory bounded. A 3B-row table with 3M rows/day fits comfortably in memory per-day.
- **Checkpoint and gap detection (P1-5):** `orchestration/pipeline_state.py` tracks per-day status in PipelineExtractionState. On restart, the pipeline resumes from the last successful date and fills gaps.
- **Partial extraction recovery (P1-6):** Each completed day is checkpointed. A failure on day 15 of 30 preserves the first 14 days; the next run picks up from day 15.
- **Idempotency:** Windowed CDC comparison handles re-runs safely. Re-extracting the same date produces unchanged hashes for untouched rows.
- **Delete detection (P1-4):** Scoped to extraction window. Rows outside the window are not considered deleted. Pair with periodic full reconciliation for real deletes.
- **Cross-day transaction overlap (V-7):** Source transactions spanning midnight may split across processing windows. Three mitigations exist: (1) `LookbackDays` provides a rolling re-extraction window as the primary mechanism — a lookback of 3 days means each date is re-processed across 3 runs, catching most split transactions. (2) `OVERLAP_MINUTES` env var (default 0) extends each day's window backward; when >= 1440 minutes (full day), shifts target_date back by 1+ days; sub-day precision requires datetime-level WHERE clauses in extractors (future enhancement). (3) Weekly reconciliation (`cdc/reconciliation.py`) catches any remaining discrepancies as the safety net. CDC comparison is idempotent — overlapping extraction windows produce no phantom changes because unchanged rows hash identically.

**Current extraction routing:**
- Oracle + SourceIndexHint populated -> oracledb with per-day date chunks, INDEX hints, TRUNC() boundaries (P3-2), distinct-date pre-query to skip empty days (P2-2)
- Oracle + SourceIndexHint NULL -> ConnectorX windowed with FULL scan hint, TRUNC() boundaries (P3-2)
- SQL Server -> ConnectorX windowed

**What we know works:**
- SourceAggregateColumnName is the date column used for WHERE clause filtering
- LookbackDays provides a rolling window to capture day-over-day changes
- FirstLoadDate defines the earliest date boundary for initial loads
- Multiple runs per day provide natural retry coverage for transient failures

## Key Architecture Decisions

**Extraction routing** is driven by UdmTablesList columns:
- SourceIndexHint: populated -> oracle_extractor (date-chunked INDEX hint)
- SourceIndexHint: NULL + Oracle -> connectorx_extractor (bulk FULL scan, 10-20x faster)
- PartitionOn: If value is not null then use column as ConnectorX partition_on column value else use regular ConnectorX extract. If both SourceIndexHint and PartitionOn are not NULL then proceed with using SourceIndexHint and oracledb for Oracle extracts otherwise proceed with ConnectorX for non-Oracle extracts.
- SourceObjectName: Table name of the source data.
- SourceServer: Linked server or server of source data.
- SourceDatabase: Database of source data.
- SourceSchemaName: Schema name of the source data.
- SourceName: The source name (DNA, CCM, EPICOR, etc) from where the data comes.
- SourceAggregateColumnType: The datatype of the SourceAggregateColumnName.
- SourceAggregateColumnName: The date column for large tables to incrementally extract data from.
- FirstLoadDate: Date in which the large table is to have data extracted from.
- LookbackDays: Number of days from current day which need data extracted for large tables. To capture rolling window and ensure we capture all changes day over day.
- StageTableName: Custom name of the Stage table (overrides SourceObjectName in naming).
- BronzeTableName: Custom name of the Bronze table (overrides SourceObjectName in naming).
- StageLoadTool: If value is Python then extract data. If null then do nothing.
- MaxRowsPerDay: Per-table override for the P1-13 daily-extraction guard (BIGINT NULL). When set, the growth-guard limit becomes `max(5x * baseline, MaxRowsPerDay)` instead of `5x * baseline` alone. Lets growing tables (e.g. CARDTXN went from ~500 rows/day in 2022 to ~280k rows/day in 2024) bypass the multiplier check while still blocking Cartesian-class spikes above the absolute ceiling. NULL preserves the global default. Migration: `migrations/extraction_guard_per_table.py`.
- SQL Server source: NULL + SQL Server -> connectorx_sqlserver_extractor (bulk FULL scan, 10-20x faster)

**Connection string patterns:**
- Oracle (ConnectorX): `oracle://user:pass@host:port/service`
- Oracle (oracledb): thick mode via Oracle Instant Client 19c
- SQL Server (ConnectorX): `mssql://user:pass@host:port/database`
- SQL Server (pyodbc/BCP): ODBC Driver 18 for SQL Server
- Further details TBD after connection testing

**Column Tracking** via General.dbo.UdmTablesColumnsList — used AFTER UDM tables have been created:
- SourceName: The source name of where data originates.
- TableName: Table name in UDM. Similar to SourceObjectName, StageTableName, and BronzeTableName.
- ColumnName: The column name from the table.
- OrdinalPosition: Column position in the table.
- IsPrimaryKey: A boolean flag of 1 or 0. Must be manually set for Oracle views that lack primary keys.
- Layer: The layer of the medallion architecture ie Stage, Bronze, Silver, Gold.
- IsIndex: A boolean flag of 1 or 0 specifically if the UDM table should have an index.
- IndexName: The name of the index.
- IndexType: The type of SQL Server index.

Primary uses:
1. CDC: IsPrimaryKey drives which columns are used for row-level comparison and change detection.
2. SCD2: IsPrimaryKey determines the business key for versioning.
3. Index optimization: IsIndex/IndexName/IndexType used by index_management.py for disable/rebuild around BCP loads.
4. Future: Will be used to optimize Stage and Bronze table structures.

Note: Oracle views do NOT expose primary keys — IsPrimaryKey must be manually populated in UdmTablesColumnsList for any Oracle view source.

**Column Sync** (schema/column_sync.py) — auto-populates UdmTablesColumnsList on first load:

When a new table is added to UdmTablesList, the pipeline automatically syncs column metadata and discovers primary keys. This runs once per table (skips if UdmTablesColumnsList already has rows for the source + table).

Flow:
1. After `ensure_stage_table` / `ensure_bronze_table` create the UDM tables
2. `sync_columns()` checks if UdmTablesColumnsList has rows — if yes, skip
3. Reads `INFORMATION_SCHEMA.COLUMNS` from the newly created Stage and Bronze tables
4. Inserts rows into UdmTablesColumnsList for both Stage and Bronze layers (IsPrimaryKey=0, IsIndex=0)
5. Discovers PKs from the source system:
   - Oracle tables: `ALL_CONSTRAINTS` with `CONSTRAINT_TYPE = 'P'`
   - Oracle views: falls back to `ALL_INDEXES` with `UNIQUENESS = 'UNIQUE'`
   - SQL Server tables: `sys.indexes` with `is_primary_key = 1`
   - SQL Server views: falls back to first unique index
6. Updates `IsPrimaryKey = 1` for discovered columns in both layers
7. Reloads columns into the in-memory `TableConfig` so CDC/SCD2 work on the first run

Optimistic behavior:
- Tables with discoverable PKs (PK constraint or eligible unique index): fully automatic, CDC/SCD2 run on the first pipeline execution.
- Views: discovery walks the source's dependency graph (`ALL_DEPENDENCIES` for Oracle, `sys.dm_sql_referenced_entities` for SQL Server), looks up the PK on each referenced table, and uses the first referenced table whose PK columns ALL appear in the view's column list. Self-healing — no manual config required. Multiple matching candidates log a warning; one wins.
- Views with no underlying TABLE dependency or no matching PK: columns still sync, PK warning is logged, CDC/SCD2 skip until IsPrimaryKey is set manually in UdmTablesColumnsList.
- PK discovery failure (connection error, permissions): columns still sync, PK warning logged, non-fatal.

UdmTablesColumnsList metadata columns (`migrations/udm_tables_columns_list_metadata.py`): every sync populates `ObjectType` ('TABLE'/'VIEW' from source `sys.objects` / `ALL_OBJECTS`), `DatabaseName` (the source database name), and `MetadataLastUpdated` (server-side `SYSDATETIME()` at insert). Lookups are non-blocking — failure leaves columns NULL.

**CDC + SCD2 in Polars** — the in-memory path carries df_current and pk_columns forward from CDC to SCD2, eliminating re-extraction from UDM_Stage.

**SCD2 is optimized from 5 steps to 2**: (1) single UPDATE batch for closes/deletes, (2) single INSERT batch for new rows + new versions. Unchanged rows are counted but NOT touched — saves GB of transaction log.

**BULK_LOGGED recovery model** is set on the target DB during the load window, restored to FULL with a log backup after. This is wrapped via '_bulk_load_recovery_context()'.

## Observability: Event Tracking + Pipeline Logs

The pipeline has two complementary observability tables in `General.ops`. Together they answer "what happened and how fast?" (PipelineEventLog) and "why did it happen that way?" (PipelineLog). The join point is `BatchId + TableName + SourceName`.

### General.ops.PipelineEventLog — Runtime Performance Tracking

The primary table for identifying bottlenecks and tracking pipeline health. PipelineEventTracker writes exactly one row per step per table. All tables in a run share one BatchId from General.ops.PipelineBatchSequence.

PipelineEventLog columns:
- BatchId: Pipeline run ID, constant for the entire run. Sourced from General.ops.PipelineBatchSequence.
- TableName: The table being processed (e.g., ACCT).
- SourceName: The data source (DNA, CCM, EPICOR, etc.).
- EventType: EXTRACT, BCP_LOAD, CDC_PROMOTION, SCD2_PROMOTION, CSV_CLEANUP, TABLE_TOTAL.
- EventDetail: Free-text detail about the event. May be removed if not providing value.
- StartedAt: Timestamp when the step began.
- CompletedAt: Timestamp when the step finished.
- DurationMs: Elapsed time in milliseconds (CompletedAt - StartedAt). This is the key metric for bottleneck analysis.
- Status: Success/failure indicator for the step.
- ErrorMessage: Error detail when Status indicates failure.
- RowsProcessed: Total rows handled during the step.
- RowsInserted: Rows inserted (CDC inserts or SCD2 new versions).
- RowsUpdated: Rows updated (CDC updates or SCD2 closes).
- RowsDeleted: Rows marked as deleted (CDC soft deletes).
- RowsUnchanged: Rows that matched and required no action.
- RowsBefore: Row count in the target table before the step ran.
- RowsAfter: Row count in the target table after the step completed.
- TableCreated: BIT (1/0) — whether the UDM table was auto-created during this run.
- Metadata: JSON or free-text field for one-off metrics. May be removed unless specific metrics prove worth tracking.
- RowsPerSecond: Throughput metric derived from RowsProcessed / (DurationMs / 1000).

EventType definitions:
- EXTRACT: Time to pull data from source (Oracle/SQL Server) into a Polars DataFrame and write the BCP CSV.
- BCP_LOAD: Time for the BCP subprocess to load the CSV into the SQL Server staging/CDC table.
- CDC_PROMOTION: Time for the Polars CDC comparison (hash-based insert/update/delete detection) and writing changes.
- SCD2_PROMOTION: Time for the Polars SCD2 comparison against Bronze and executing the UPDATE + INSERT batches.
- CSV_CLEANUP: Time to delete temporary BCP CSV files after load completes.
- TABLE_TOTAL: End-to-end wall time for the entire table pipeline (extract through SCD2), useful for identifying the slowest tables overall. Also used with Status=SKIPPED for lock-blocked tables (OBS-3).

EventType families registered per Round 4 D76 + Round 6 § 6.4 (closes B86):

- **CLI_\*** family — one row per CLI invocation per D76 audit-row contract. Values: CLI_PARQUET_TIER_REVIEW, CLI_PARQUET_VERIFY, CLI_LATENESS_PROFILE, CLI_DECRYPT_PII, CLI_DETECT_EXTRACTION_GAPS, CLI_PROMOTE_TEST_TO_PROD, CLI_VERIFY_SERVER_PARITY, CLI_ENFORCE_RETENTION, CLI_PROCESS_CCPA_DELETION, CLI_LOG_RETENTION_CLEANUP, CLI_ALERT_DISPATCHER (11 tools per Round 4 § 3). Metadata JSON carries args, actor, justification, exit_code per D75 + D76.
- **CYCLE_\*** family — pipeline cycle lifecycle per Round 2 § 5.3.6 + Round 4 § 3.6. Values: CYCLE_FAILED_OVER (test claimed gate after prod heartbeat stale; written by SP-4 path), CYCLE_CANCELLED (graceful cancellation per D33; written by check_cancellation per RB-9).
- **DEPLOYMENT_\*** family — per environment promotion audit row per D87 + Round 6 § 1.6. Values: DEPLOYMENT_DEV, DEPLOYMENT_TEST, DEPLOYMENT_PROD, DEPLOYMENT_ROLLBACK (4 variants). Metadata JSON carries tag, prior_tag, actor, justification, pre_check_results, post_check_results, soak_duration_minutes.
- **MIGRATION_\*** family — per `migrations/<name>.py` script invocation per Round 6 § 4.1. Values: MIGRATION_<NAME> (one per script; N values, one per migration). Metadata JSON carries applied_at, applied_by, checksum. **Round 7 addition** (per `phase1/07_schema_evolution_governance.md` § 6.2): MIGRATION_AUTOMIC_INVENTORY canonical value when the frozen-Automic-job inventory is amended (e.g., frozen-8 → frozen-11 per JOB_PARQUET_VERIFY + JOB_LOG_CLEANUP + JOB_PARITY_EXCEPTION_NOTIFY); Metadata JSON carries `added_jobs`, `frozen_count_before`, `frozen_count_after`.
- **STARTUP_\*** family — module startup sequence stages per D85 + Round 6 § 1.7. Values: CREDS_LOAD (Stage 1 credentials_loader complete), VAULT_CONFIG (Stage 2 vault pool config complete), PARITY_CHECK (Stage 3 server_parity_verifier complete), LEDGER_SWEEP (Stage 4 idempotency_ledger startup_recovery_sweep complete), ORCHESTRATION_START (Stage 5 main_*.py orchestration begins; gate acquired via SP-3/SP-4).

**PipelineEventTracker design**: A context manager that wraps each pipeline step. Captures StartedAt on entry, CompletedAt on exit, computes DurationMs, catches exceptions into ErrorMessage and sets Status to FAILED, then writes the row to PipelineEventLog. Pipeline code sets row counts on the event object as it discovers them. TABLE_TOTAL is an outer context manager around all inner steps for nested timing. If anything inside the `with` block throws, the event still gets recorded — you never lose visibility into failures.

```python
# Usage pattern in pipeline code
with tracker.track("EXTRACT", table_config) as event:
    df = extract_from_source(table_config)
    event.rows_processed = len(df)

with tracker.track("CDC_PROMOTION", table_config) as event:
    cdc_result = run_cdc(df, table_config)
    event.rows_inserted = cdc_result.inserts
    event.rows_updated = cdc_result.updates
    event.rows_deleted = cdc_result.deletes
    event.rows_unchanged = cdc_result.unchanged
```

### General.ops.PipelineLog — Detailed Diagnostic Logs

The investigation table for understanding *why* something was slow, failed, or behaved unexpectedly. Many rows per step — the narrative of what happened inside each pipeline step.

PipelineLog columns:
- BatchId: Same run-level ID as PipelineEventLog, enabling joins.
- TableName: Nullable — some log entries are pipeline-wide, not table-specific.
- SourceName: Nullable for the same reason.
- LogLevel: DEBUG, INFO, WARNING, ERROR, CRITICAL.
- Module: Python module that emitted the log (e.g., `extract.connectorx_oracle_extractor`, `cdc.engine`).
- FunctionName: The specific function (e.g., `extract_with_partition`, `_detect_changes`).
- Message: Human-readable log message.
- ErrorType: Exception class name when applicable (e.g., `ConnectionError`, `PolarsSchemaError`).
- StackTrace: Full traceback for ERROR/CRITICAL entries.
- Metadata: JSON field for structured context (query text, chunk date range, memory usage, intermediate row counts).
- CreatedAt: Timestamp of the log entry.

**SqlServerLogHandler design**: A custom `logging.Handler` subclass so every module uses standard `logger.info()`, `logger.warning()`, `logger.error()` calls. The handler holds the current BatchId and TableName in a thread-local or context variable — individual modules never pass tracking context around. The handler batches log entries and writes them to PipelineLog. Logs below a configurable threshold (e.g., DEBUG in production) are filtered at the handler level to avoid flooding the table.

**Log retention policy**: Keep 30 days of DEBUG/INFO, 90 days of WARNING+, indefinite for ERROR/CRITICAL. A SQL Agent job or pipeline post-step handles cleanup.

### How the Two Tables Work Together

PipelineEventLog is the **dashboard layer** — small, structured, one row per step. Query it to find the 10 slowest tables this week, which EventType is the bottleneck, whether throughput is degrading over time, or if a table's RowsProcessed dropped suddenly (a data quality signal).

PipelineLog is the **investigation layer** — many rows per step, detailed narrative. Once the event log tells you "ACCT SCD2_PROMOTION took 12 minutes on Tuesday's 2PM run," filter PipelineLog by that BatchId + TableName and see: ConnectorX partition count was 4, the DataFrame was 2.3M rows, memory peaked at 6GB, a warning fired about 14 columns requiring dtype casting, and the UPDATE batch hit a lock wait on Bronze.

Typical debugging workflow:
```sql
-- Step 1: Find the slow run
SELECT TableName, EventType, DurationMs, RowsProcessed, Status
FROM General.ops.PipelineEventLog
WHERE BatchId = 1042 AND DurationMs > 30000
ORDER BY DurationMs DESC;

-- Step 2: Dig into the details
SELECT CreatedAt, LogLevel, Module, FunctionName, Message, Metadata
FROM General.ops.PipelineLog
WHERE BatchId = 1042 AND TableName = 'ACCT'
  AND CreatedAt BETWEEN '2025-02-20 14:00:00' AND '2025-02-20 14:15:00'
ORDER BY CreatedAt;
```

Questions these tables answer together:
- "Which tables take the longest?" — PipelineEventLog, TABLE_TOTAL by DurationMs.
- "Is extraction or SCD2 the bottleneck for table X?" — PipelineEventLog, compare EXTRACT vs SCD2_PROMOTION DurationMs.
- "How many rows/second does BCP achieve for large loads?" — PipelineEventLog, RowsPerSecond on BCP_LOAD events.
- "Why did ACCT take 12 minutes today but 2 minutes yesterday?" — PipelineLog, compare Metadata and WARNING entries across BatchIds.
- "Did any step fail and need a retry?" — PipelineEventLog where Status = FAILED, then PipelineLog for StackTrace.
- "Are we seeing data quality drift?" — PipelineEventLog, trend RowsProcessed and RowsInserted/Updated/Deleted over time per table.

## Deployment Requirements
- **MALLOC_ARENA_MAX=2** must be set in the systemd unit file, shell wrapper, or `.bashrc` for the pipeline user BEFORE the Python process starts (W-4). `os.environ.setdefault()` in main_*.py only covers child processes — glibc arena configuration is locked at process start. Without this, Polars/Rust allocations can cause 10x memory bloat from glibc arena fragmentation (Polars issue #23128).
- **mssql-tools18**: Current minimum version is the installed default. When v18.6.1.1+ is available, upgrade to re-enable `-C 65001` for explicit UTF-8 codepage control (W-1).

## Gotchas
- Item-22: `CSV_OUTPUT_DIR` is safe for concurrent `--workers` only because each table's extract→CDC→SCD2→cleanup pipeline is sequential within a single worker. `cleanup_csvs()` globs `{source}_{table}_*.csv` with a trailing underscore (P3-6) to prevent cross-table matches. Do NOT restructure the pipeline to allow overlapping steps within a worker without adding per-table subdirectories for CSV isolation.
- B-1: _row_hash and UdmHash are VARCHAR(64) (full SHA-256 hex string). Previous BIGINT (64-bit truncation) was safe for per-PK CDC (~1.6×10⁻¹⁰ risk) but not for adjacent operations (reconciliation, future surrogate keys) where birthday-paradox collisions reach ~24% at 3B rows. Upgrade was defense-in-depth. Migration script: `migrations/b1_hash_varchar64.py`. First pipeline run after migration rehashes all rows (one-time CDC update wave).
- B-2: SCD2 UPDATE batch size must stay below 5,000 to prevent SQL Server lock escalation from row locks to table-level exclusive locks. Table-level exclusive locks override RCSI, blocking all readers. Controlled by `config.SCD2_UPDATE_BATCH_SIZE` (default 4,000).
- B-3: Schema evolution (column adds) changes all row hashes on the next run. `evolve_schema()` returns `SchemaEvolutionResult` so orchestrators can suppress E-12 false warnings during schema migration runs. Check `PipelineEventLog` metadata for `"schema_migration": true`.
- B-4: Orphaned Flag=0 rows (from crash between SCD2 INSERT and activation) are cleaned up at the start of each SCD2 run via `_cleanup_orphaned_inactive_rows()`. Safe to delete because they are invisible to downstream consumers.
- UInt64 from non-hash sources must be .reinterpret(signed=True) before writing — BCP/SQL Server cannot handle unsigned 64-bit
- String columns with embedded tabs/newlines corrupt BCP CSV when quote_style='never' — sanitize BEFORE write_csv
- ConnectorX returns Oracle DATE as Utf8 sometimes — auto-cast columns where DATE in col.upper()
- _scd2_key is IDENTITY in Bronze — must be excluded from INSERT DataFrames and BCP column lists
- _cdc_is_current and UdmActiveFlag are BIT in SQL Server — cast to Int8 before CSV write (not True/False)
- Polars write_csv with batch_size=4096 avoids memory spikes on large DataFrames
- The .env file lives at /debi/.env not project root
- Oracle views have no primary keys — schema/column_sync.py will attempt unique index discovery, but IsPrimaryKey in UdmTablesColumnsList may still need manual setup for views without unique indexes
- BCP CSV has no header — column mapping is POSITIONAL. `reorder_columns_for_bcp()` enforces deterministic order by reading INFORMATION_SCHEMA ordinal position before every BCP write (P0-1). Never use SELECT * in extraction queries.
- CDC/SCD2 staging tables read actual PK types from the target table via `get_column_types()` (P0-3). Never hardcode NVARCHAR(MAX) for PK columns in staging tables.
- NULL values in PK columns are filtered out before CDC comparison via `_filter_null_pks()` (P0-4). The count is tracked in PipelineEventLog metadata.
- Empty extraction guard (`_check_extraction_guard`) blocks CDC if row count drops >90% vs previous run (P1-1). Use `--force` to override for intentional reloads.
- `sp_getapplock` prevents concurrent pipeline runs on the same table (P1-2). If a run crashes, Session-owned locks auto-release on connection drop.
- Schema evolution runs every extraction (P0-2): new columns are ADDed, removed columns are WARNed (never dropped), type changes raise SchemaEvolutionError and skip the table.
- Large table windowed CDC scopes delete detection to the extraction window (P1-4). Rows outside the window are never marked as deleted.
- `schema/staging_cleanup.py` should run at pipeline start to drop orphaned `_staging_*` tables from crashes (P3-3).
- Weekly reconciliation (`cdc/reconciliation.py`) does full column-by-column comparison (not hash-based) to catch hash collisions and CDC logic bugs (P3-4).
- ConnectorX Oracle windowed extraction uses TRUNC() in WHERE clauses to prevent timezone boundary drift (P3-2). The oracledb path also uses TRUNC().
- oracledb extractor pre-queries for distinct dates to skip empty days (P2-2). ConnectorX large table path does not — empty days return quickly but incur connection overhead.
- ConnectorX partition skew is logged via `_log_partition_skew()` (P2-3). If the partition column has >10% NULLs, a WARNING suggests choosing a different column.
- V-4: After SCD2 promotion, `_check_duplicate_active_rows()` queries Bronze for PKs with >1 active row. Between a crash and recovery, downstream consumers using `WHERE UdmActiveFlag = 1` may see duplicates. Safe current-state access pattern: `ROW_NUMBER() OVER (PARTITION BY pk_cols ORDER BY UdmEffectiveDateTime DESC) WHERE rn = 1`.
- V-11: If polars-hash becomes incompatible with a future Polars version, `add_row_hash_fallback()` in `bcp_csv.py` provides a pure-Python hashlib SHA-256 fallback. To activate: replace `add_row_hash` with `add_row_hash_fallback` in `prepare_dataframe_for_bcp()`. Performance is slower (~5-10x) but functionally equivalent. Verify hash output matches on a test table before switching.
- W-2: NULL sentinel in hash input uses `\x1FNULL\x1F` (Unit Separator wrapping), NOT `\x00NULL\x00`. Null bytes risk C-string truncation in logging, debugging tools, and FFI boundaries. The `\x1F` sentinel is consistent with the column separator strategy (P0-6). Changing the sentinel changes hash output for every row containing NULLs — requires a one-time CDC update wave on first deployment.
- W-3: Float columns in hash input are normalized for IEEE 754 edge cases: ±0.0 → +0.0, NaN → `\x1FNaN\x1F`, Infinity → `\x1FINF\x1F`, -Infinity → `\x1F-INF\x1F`. Without this, these special values produce platform-dependent string representations causing phantom CDC updates.
- W-7: `validate_schema_before_concat()` in `bcp_csv.py` is called before every `pl.concat()` to catch silent type coercion (e.g., Int64 → Float64 in `diagonal_relaxed` mode). In extractors, schema mismatches are logged as warnings (non-blocking, since ConnectorX may legitimately return different dtypes). In CDC/SCD2, mismatches raise `SchemaValidationError`.
- W-8: `table_lock.py` uses Session-owned locks (`@LockOwner='Session'`) with `autocommit=True`. The RCSI race condition (sp_releaseapplock before COMMIT) does NOT apply to Session-scoped locks. If lock ownership is ever changed to Transaction-scoped, remove the explicit `sp_releaseapplock` call and let locks release at COMMIT time.
- W-10: `ensure_bronze_columnstore_index()` in `table_creator.py` is an opt-in migration for Bronze tables with 100M+ rows. Requires SQL Server 2022. Drops the clustered PK and recreates as nonclustered to make room for the ordered clustered columnstore index. Run during a maintenance window. Benchmark before and after.
- W-11: `reconcile_counts()` in `reconciliation.py` provides lightweight daily count reconciliation (source vs Stage vs Bronze). Designed to catch gross data loss within 24 hours rather than waiting for the weekly full-column reconciliation. Schedule as part of normal pipeline completion.
- W-12: `shrink_to_fit(in_place=True)` is called after large DataFrame operations (>100K rows) in CDC engine, large table extraction, and hash computation. Releases over-allocated memory buffers back to the allocator. Combines with W-4 (MALLOC_ARENA_MAX=2) to minimize memory bloat.
- W-13: `generate_bcp_format_file()` in `bcp_csv.py` produces XML .fmt files from INFORMATION_SCHEMA metadata. `bcp_load()` accepts an optional `format_file` parameter for explicit column mapping. The format file uses character mode with tab delimiters and LF terminators per the BCP CSV Contract. `reorder_columns_for_bcp()` remains as defense-in-depth validation even when format files are used.
- W-17: `General.ops.Quarantine` table stores records that fail schema contracts. `ensure_quarantine_table()`, `quarantine_record()`, and `quarantine_batch()` in `schema/evolution.py` provide the infrastructure. Currently hooked into schema type change errors. Low priority — the existing all-or-nothing table skip is safe, quarantine adds visibility into why records were rejected.
- E-1: Oracle empty string/NULL equivalence — `add_row_hash(source_is_oracle=True)` normalizes empty strings to NULL before hashing for Oracle sources. Oracle treats '' as NULL; SQL Server does not. Without this, every Oracle-sourced row with empty string fields generates phantom CDC updates indefinitely. Applied to the DataFrame itself (not just hash input) so BCP CSV output is also normalized. First deployment triggers a one-time CDC update wave for affected rows.
- E-2: SCD2 INSERT-first now uses a 3-step process: (1) INSERT new versions with UdmActiveFlag=0 for operation='U', (2) UPDATE to close old active versions, (3) UPDATE to activate new versions (`_activate_new_versions()`). This prevents conflicts with the filtered unique index (`ensure_bronze_unique_active_index`). New inserts (operation='I') still use UdmActiveFlag=1 directly. A crash after INSERT but before activation leaves rows with UdmActiveFlag=0, UdmEndDateTime IS NULL — detectable and recoverable on next run.
- E-3: BCP `-b` (batch size) flag is now controlled by `bcp_load(atomic=True/False)`. Bronze SCD2 loads default to atomic=True (no `-b` flag) — the entire INSERT is a single transaction. Stage/staging loads use atomic=False for performance since they are ephemeral. Without atomicity, a BCP failure partway through an SCD2 INSERT creates inconsistent Bronze state (some PKs with two active versions, others with none).
- E-4: All string columns are RTRIM'd before hashing to prevent phantom hash differences from trailing space divergence (Oracle CHAR padding, SQL Server ANSI padding rules). Applied after NFC normalization (V-2) and Oracle empty string normalization (E-1). First deployment triggers a one-time CDC update wave for rows with trailing spaces.
- E-5: `_execute_bronze_updates()` deduplicates `pks_to_close` via `.unique(subset=pk_columns)` before loading into the staging table. Also applied in `run_scd2()` close concat. Defense-in-depth against UPDATE FROM JOIN nondeterminism with duplicate staging keys. Currently safe (SET values are constants) but prevents issues if the pattern is extended.
- E-8: Under RCSI, the SCD2 INSERT and UPDATE are separate statements each with their own snapshot. Between INSERT commit and UPDATE commit, concurrent readers may see two active versions for updated PKs (transient window, typically milliseconds). Downstream consumers should use `ROW_NUMBER() OVER (PARTITION BY pk_cols ORDER BY UdmEffectiveDateTime DESC) WHERE rn = 1` instead of `WHERE UdmActiveFlag = 1` alone. The V-4 diagnostic and P1-16 dedup recovery handle the crash case.
- E-9: `verify_rcsi_enabled()` in `connections.py` runs at pipeline startup to check `READ_COMMITTED_SNAPSHOT` on the Bronze database. B-2 reduced batch size from 500K to 4K to prevent lock escalation even with RCSI — table-level exclusive locks override RCSI. The check is non-blocking — logs WARNING and continues if RCSI is disabled.
- E-10: `_check_log_space()` in `scd2/engine.py` runs before large UPDATE operations (>1M rows) to verify sufficient transaction log space. UPDATEs are always fully logged (~400 bytes × 2 per row for before/after images). A 5M-row UPDATE may require 5-20 GB of log space. Warns if available space is <1.5× estimated need. Ensure frequent log backups (15-30 min) during pipeline runs.
- E-11: `validate_source_schema()` in `schema/evolution.py` compares extracted DataFrame columns against expected columns from UdmTablesColumnsList. Missing columns (possible rename/drop) are ERROR-level and skip the table. Unexpected columns (new in source) are WARNING-level and allowed through — schema evolution handles the ADD. Only runs when UdmTablesColumnsList has been populated (not on first run).
- E-12: CDC update ratio is tracked in `CDC_PROMOTION` event metadata as `update_ratio`. A ratio >50% with >1000 updates triggers a WARNING for systematic hash mismatch (encoding change, schema drift, normalization bug). Query `PipelineEventLog WHERE EventType='CDC_PROMOTION'` and parse metadata JSON to trend update ratios over time.
- E-13: `check_version_velocity()` in `cdc/reconciliation.py` queries avg/max versions per PK and flags PKs with >10 versions. High version velocity indicates either genuine high-change-rate data or phantom version creation. Schedule as part of periodic reconciliation.
- E-14: Active-to-total ratio is tracked in `SCD2_PROMOTION` event metadata as `active_ratio`. A ratio <1% triggers a WARNING for possible mass incorrect closures. Trend this metric over time — gradual decline is expected as history accumulates.
- E-15: `_log_data_freshness()` checks max `UdmEffectiveDateTime` in Bronze after each SCD2 run. Warns if data is >48 hours stale, indicating silent pipeline failures where runs complete without processing new data.
- E-16: `detect_source_type_drift()` in `schema/column_sync.py` compares source column metadata (type, precision, scale) against Stage INFORMATION_SCHEMA. Detects precision changes (e.g., NUMBER(10,2) → NUMBER(15,4)) that could cause phantom hash mismatches. Call periodically or as part of reconciliation.
- E-17: `reconcile_aggregates()` in `cdc/reconciliation.py` compares SUM/COUNT/MIN/MAX of numeric columns between source and Bronze active rows. Catches value-level corruption that count validation misses. Schedule daily for high-value tables.
- E-18: Resurrected PKs (previously deleted, now reappearing in source) get `UdmScd2Operation='R'` in Bronze for audit trail. The version chain is: active ('I') → closed → deleted ('D') → closed → reactivated ('R'). Both `run_scd2()` and `run_scd2_targeted()` detect resurrections and build inserts with operation='R'. `_activate_new_versions()` targets both 'U' and 'R' operations.
- E-19: The `\x1F` (Unit Separator) between columns in hash concatenation prevents cross-column collisions. Without it, `("AB", "CD")` and `("A", "BCD")` produce the same hash. Documented in `add_row_hash()` and `add_row_hash_fallback()`.
- E-20: Categorical columns in Polars use physical integer encoding internally. polars-hash hashes the physical integer, not the logical string value (Polars Issue #21533). `add_row_hash()` and `add_row_hash_fallback()` detect Categorical columns and cast to Utf8 before hashing.
- E-21: ConnectorX converts Oracle NUMBER to Python float64, which has ~15 significant digits (vs Oracle's 38). Precision is already lost before pipeline processing for high-precision Oracle NUMBER columns. For critical columns with >15 digits, cast to VARCHAR2 in the extraction SQL.
- B-6: `sanitize_strings()` strips extended Unicode line-break characters (`\x0B`, `\x0C`, `\x85`, `\u2028`, `\u2029`) in addition to `\t`, `\n`, `\r`, `\x00`. These rare characters corrupt BCP CSV row boundaries. More likely in internationalized data, CMS content, or legacy system migrations.
- B-7: `cx_read_sql_safe()` in `extract/__init__.py` wraps all ConnectorX calls with Rust panic recovery (catches `BaseException`, not just `Exception`) and exponential backoff retry (3 attempts, 2s base delay). Non-retryable errors (syntax, permissions) fail fast. All extractors route through this wrapper.
- B-8: `_check_rss_memory()` in both `main_small_tables.py` and `main_large_tables.py` monitors RSS between table iterations in sequential mode. WARNING at 85% of `config.MAX_RSS_GB` (default 48), ERROR at limit. Combine with `MALLOC_ARENA_MAX=2` (W-4) for best results. psutil is optional — silently skipped if not installed.
- B-9: Freshness alerting uses two tiers: WARNING at 36 hours (1.5× expected refresh interval), ERROR at 48 hours (2× — two missed cycles). Extraction guard baselines use day-of-week aware queries (last 30 days, same weekday) to reduce false positives on weekends/holidays; falls back to any-day median if insufficient same-day data.
- B-10: `detect_distribution_shift()` in `reconciliation.py` compares numeric column means against a stored baseline using z-score analysis. Alert when shift exceeds 2σ. Stores baselines as `DISTRIBUTION_CHECK` events in PipelineEventLog. Schedule weekly — not every run.
- B-11: `reconcile_transformation_boundary()` in `reconciliation.py` validates row counts, key existence, and NULL rate comparisons between adjacent medallion layers. Implements circuit-breaker pattern — callers can block downstream processing on failure.
- B-12: `check_referential_integrity()` in `reconciliation.py` validates FK relationships across SCD2 tables. Supports both non-temporal (active flag) and temporal (BETWEEN effective/end dates) lookup modes. Detects orphaned FKs and ambiguous FKs (resolving to multiple dimension rows).
- OBS-1: The `BCP_LOAD` event type was removed from `small_tables.py` — it wrapped an empty block. BCP timing is captured within `CDC_PROMOTION` (staging table loads) and `SCD2_PROMOTION` (Bronze INSERT/UPDATE loads). Large tables never had a standalone BCP_LOAD event.
- OBS-2: Large table per-day events (EXTRACT, CDC_PROMOTION, SCD2_PROMOTION, CSV_CLEANUP) set `EventDetail = target_date` for per-day diagnostic filtering. Query example: `WHERE TableName = 'ACCT' AND EventDetail = '2025-02-15'`.
- OBS-3: Lock-skipped tables write a `TABLE_TOTAL` event with `Status = 'SKIPPED'` and `EventDetail = 'Lock held by another run'`. SKIPPED is a valid PipelineEventLog status alongside SUCCESS and FAILED. Monitor lock contention: `WHERE Status = 'SKIPPED'`.
- OBS-4: `SqlServerLogHandler` buffer reduced from 50 to 10 entries to narrow crash-loss window. WARNING+ log entries flush immediately regardless of buffer state. Flush failures print to stderr instead of being silently swallowed.
- OBS-5: `PipelineEventTracker._write_event()` and `SqlServerLogHandler._flush_buffer()` both call explicit `conn.commit()` after writes. Do not remove these — they protect against future autocommit configuration changes silently breaking observability.
- OBS-6: `General.ops.ReconciliationLog` stores reconciliation results for historical trending. Created by `ensure_reconciliation_log_table()` (idempotent). All public reconciliation functions (`reconcile_table`, `reconcile_counts`, `reconcile_active_pks`, `reconcile_bronze`, `reconcile_aggregates`) persist results via `_persist_reconciliation_result()`. CheckType discriminator identifies the reconciliation type.
- OBS-7: `_log_active_ratio()` in both orchestrators uses `json.loads()`/`json.dumps()` merge pattern for SCD2 event metadata. Any future SCD2 metadata extensions must follow this pattern — never overwrite `scd2_event.metadata` directly.
- SCD2-P1-a (dual date-pair contract): Bronze carries TWO independent date pairs. The **load-time pair** (`UdmEffectiveDateTime`, `UdmEndDateTime`) is the Silver/Gold contract and is unchanged from pre-Phase-1 — `UdmEffectiveDateTime` = arrival timestamp into UDM, `UdmEndDateTime` = NULL while active / load timestamp at close. The **source-date pair** (`UdmSourceBeginDate`, `UdmSourceEndDate`) is new in Phase 1 and carries R-1/R-3 business-date semantics — `UdmSourceBeginDate` = source business date, `UdmSourceEndDate` = `'2999-12-31'` sentinel while active, chained end when closed. The two pairs are INDEPENDENT; never conflate them. **R-2 extension:** `UdmSourceBeginDate` is now computed **per row** via a waterfall COALESCE over `table_config.scd2_date_columns` (primary → tie-breakers), falling through to `default_begin_date` then the batch-level fallback (`target_date` for large tables, `_extracted_at` for small tables). See `_build_source_begin_expr()` in `scd2/engine.py`. Tables without `SCD2DateColumns` configured still get the batch-level scalar — bit-for-bit identical to pre-R-2.
- SCD2-P1-b (R-3 chained source end dates): Closes are split by reason. Update-close (new version supersedes old) stamps `UdmSourceEndDate = successor_begin - 1 day` → gapless business chain with the successor. Delete-close (no successor in source) stamps `UdmSourceEndDate = batch source_begin`. `_execute_bronze_updates()` is called twice in `run_scd2` / `run_scd2_targeted` with a `label_suffix` param to disambiguate staging-table names and CSV paths. **R-2 per-PK extension:** when `_waterfall_active()` returns True (`scd2_date_columns` configured and at least one named column exists in `df_current`), update-close switches to per-PK mode — the staging table carries a `_source_end_dt DATETIME2(3)` column computed per-row by `_build_update_close_pks()` as `successor_UdmSourceBeginDate - 1 day`. `_execute_bronze_updates()` auto-detects per-PK mode via `"_source_end_dt" in pks_to_close.columns` and issues `SET UdmSourceEndDate = s._source_end_dt` instead of a scalar parameter. Delete-close stays scalar (no successor to chain against).
- SCD2-P1-c (R-3.3 active-row sentinel on source chain): Active rows carry `UdmSourceEndDate = '2999-12-31'` (DATETIME2(3) sentinel). NULL on `UdmSourceEndDate` is the B-4 in-flight marker for rows inserted with Flag=0 + operation U/R that haven't been activated yet. `_activate_new_versions()` stamps the sentinel and flips Flag=0 → Flag=1 in the same UPDATE. **R-2 update:** activation now matches rows by a **PK staging-table join** (`INNER JOIN _staging_scd2_activate_{table}` on `pk_columns`) — replaces the Phase-1 scalar `UdmSourceBeginDate = @dt` match so per-row waterfall values don't mask activations. The two-predicate in-flight filter (`UdmActiveFlag = 0 AND UdmSourceEndDate IS NULL AND UdmScd2Operation IN ('U','R')`) still gates against active rows and legacy closed rows per SCD2-P1-e. `UdmEndDateTime` is NOT part of this invariant — it stays NULL while active under the Silver/Gold contract.
- SCD2-P1-d (R-9 configuration): `TableConfig` carries SCD2 enhancement fields populated from `UdmTablesList`: `SCD2Mode`, `SCD2DateColumns`, `SourceDeleteDateColumn`, `DuplicateResolutionOrder`, `AllowDuplicates`, `PreserveDateTime`, `RepairChainAfter`, `AllowGaps`, `ExcludeFromHash`, `DefaultBeginDate`, `ForceNewSegmentColumns`, `ExpectedRetentionDays`. All fields default to values that preserve current behavior (`scd2_mode = "incremental"`, other SCD2 fields NULL). Parser helpers (`_parse_csv_list`, `_bit_to_bool`, `_none_if_blank`) live at the top of `orchestration/table_config.py`. Migrations: `scd2_phase1_config.py` (Phase 1 columns + Bronze source-date pair), `scd2_expected_retention_days.py` (R-2 retention column). Bulk-populate via `tools/detect_scd2_config.py` which derives per-source conventions from `schema/scd2_autoconfig.py` and writes to `General.dbo.UdmScd2ConfigProposal` for operator review before apply.
- SCD2-P1-e (orphan marker — BOTH predicates required): The B-4 in-flight orphan marker requires BOTH `UdmEndDateTime IS NULL` AND `UdmSourceEndDate IS NULL` (plus `UdmActiveFlag = 0 AND UdmScd2Operation IN ('U','R')`). Neither predicate is sufficient on its own: `UdmEndDateTime IS NULL` alone matches active rows; `UdmSourceEndDate IS NULL` alone matches pre-Phase-1 legacy CLOSED rows whose source-date column was never populated. The "source-date-only" predicate was the first Phase 1 design and it DELETED 53,747 legitimate historical rows from `UDM_Bronze.dna.ACCT_scd2_python` on the first run before being tightened. Any future engine work that inspects in-flight rows must use the combined predicate.
- SCD2-P1-f (datetime precision + tz invariant — activation now uses PK-staging join, not scalar match): `_as_source_datetime()` returns a **naive** (no tzinfo), **millisecond-precision** datetime in UTC wall time. Both normalizations are mandatory for BCP/pyodbc alignment. (1) BCP CSV writes datetimes with `'%Y-%m-%d %H:%M:%S.%3f'` (ms only) without a timezone suffix — SQL Server stores the value in `DATETIME2(3)` as naive wall time. (2) pyodbc/ODBC Driver 18 sends an *aware* Python datetime as `DATETIMEOFFSET`; SQL Server does implicit timezone conversion when comparing `DATETIME2 = DATETIMEOFFSET`, which on a non-UTC server silently produces a different UTC moment than what BCP stored. `UDM_SOURCE_END_SENTINEL` is `datetime(2999, 12, 31)` (naive) for the same reason. **R-2 fix:** `_activate_new_versions()` no longer uses the scalar `UdmSourceBeginDate = @dt` predicate — activation matches by PK staging-table join so it survives per-row waterfall begin dates AND removes the pyodbc/BCP precision-alignment dependency from the activation path specifically. The ms-precision + tz-strip invariant still applies to INSERT values (for consistency with BCP-stored values) and to any future code path that compares datetimes via pyodbc parameters.
- SCD2-R2-a (per-row UdmSourceBeginDate waterfall): When `table_config.scd2_date_columns` is non-empty, `_build_source_begin_expr()` emits a Polars expression that `pl.coalesce`s over the configured columns (cast to `Datetime("us")`, `strict=False` so unparseable Utf8 becomes NULL), `fill_null`s to `default_begin_date`, then to the batch-level fallback, then `.dt.truncate("1ms")`. The resulting per-row `UdmSourceBeginDate` supersedes the batch-level scalar used pre-R-2. Update-close `UdmSourceEndDate` chains off the per-row value via `_build_update_close_pks()`. Activation matching switched to PK-staging (SCD2-P1-c/f) because the scalar datetime predicate would miss rows with per-row begin dates. Tables without `SCD2DateColumns` configured keep the batch-level scalar — bit-for-bit identical to pre-R-2.
- SCD2-R10.2 (ExcludeFromHash wiring): `TableConfig.exclude_from_hash` was populated from `UdmTablesList.ExcludeFromHash` by the Phase 1 migration but was never passed to `add_row_hash()` before the R-2 commit. `prepare_dataframe_for_bcp()` now accepts an `exclude_from_hash` param and threads it through `add_row_hash()` → `_normalize_for_hashing()`. Columns in the list are dropped from the source-column list before `pl.concat_str(hash_exprs)`; the columns themselves still extract and load to Stage/Bronze normally. Typical DNA convention: `['DATELASTMAINT']` per the legacy `GenerateTableSCD2` proc. Missing column names log WARNING (typo guard). **First run after enabling on a Bronze table with existing data triggers a mass SCD2 update wave** — new hash (without excluded cols) differs from stored `UdmHash` (which included them). Matches the B-3 schema-evolution pattern.
- SCD2-R2-b (ExpectedRetentionDays classification): Delete-closes on tables with `UdmTablesList.ExpectedRetentionDays` set are classified by `_classify_delete_retention()` as "within retention" (INFO, expected purge) or "exceeds retention" (WARNING, anomalous delete — e.g. ACTV September incident). One SELECT per delete-close batch; runs only when `label_suffix == "delete_close"` AND per-PK mode is off AND `expected_retention_days is not None`. Non-blocking — SELECT failures warn-and-continue. Typical values from source purge policies (CCM TransactionDetail=1080 days, StatementHistory=365 days). Classification only — no behavior change on close itself.
- SCD2-R4 (UdmActiveFlag legacy alignment): `UdmActiveFlag` carries three legacy semantic values that downstream consumers and nonclustered indexes depend on. **Flag = 1**: currently active in source. **Flag = 2**: deleted from source — the row's life ended with a hard delete, NOT a supersession. **Flag = 0**: historical, closed by a newer version (update-close). `_execute_bronze_updates()` selects Flag = 2 when `label_suffix == "delete_close"` and Flag = 0 for every other close. Existing nonclustered indexes filtered on `UdmActiveFlag = 2` and consumer queries with `WHERE UdmActiveFlag != 0` rely on this distinction; collapsing back to a single closed value would silently change the result set of those queries. The B-4 orphan-cleanup and `_activate_new_versions()` predicates remain `Flag = 0 + Op IN ('U','R')` — unaffected because in-flight rows never carry Flag = 2.
- SCD2-R8 (DuplicateResolutionOrder enforcement): When source extraction returns >1 row per PK, `_dedup_source_pks()` in `cdc/engine.py` deduplicates BEFORE CDC and SCD2 see the data. With `UdmTablesList.DuplicateResolutionOrder` configured (parsed by `_parse_duplicate_resolution_order` into `[(col, descending), ...]` tuples), `_apply_duplicate_resolution_order` sorts by those columns (default DESC, explicit ASC supported) and keeps `first` per PK — deterministic across runs. Without configuration, falls back to `unique(keep="last")` (arbitrary but stable; the row chosen may differ across runs). Typical DNA convention: `'DATELASTMAINT,UdmEffectiveDateTime'` so the most-recently-touched row wins. Missing column names log WARNING and are dropped from the order. `_dedup_bronze_active` and `_dedup_stage_current` already sort by `UdmEffectiveDateTime DESC` / `_cdc_valid_from DESC` respectively — those paths are deterministic without R-8 and don't need it.
- LT-2 (modified-date sweep, large-table Tier 2): `cdc/reconciliation/modified_sweep.py` extracts only `(PK, UdmTablesList.LastModifiedColumn)` from source for the last `sweep_window_days` (default 90), BCP-loads the projection into a temp staging table on Bronze, and runs a server-side LEFT JOIN to find PKs where source `LastModifiedColumn` > Bronze `UdmSourceBeginDate` (or no Bronze active row exists). Catches late updates that fall outside the daily `LookbackDays` window. Runs detect-only at the end of `_process_large_table_locked` when `last_modified_column` is configured AND the daily pass succeeded AND no R-13 backfill is in flight. Records a `MODIFIED_SWEEP` event with drift counts. Operator-driven reload via `tools/sweep_modified.py --apply` is a v1 stub — currently directs to `tools/backfill.py` for the affected date range. Tables without `LastModifiedColumn` configured (CCM, EPICOR — neither has the column) are skipped. Typical DNA value: `'DATELASTMAINT'` (autoconfig DNA profile proposes it). **Reliability caveat:** `DATELASTMAINT` is bumped by the writing process. Per the DNA source-system owner, every known batch job and online transaction sets it on update — but the sweep cannot detect a row whose update slipped past `DATELASTMAINT` (e.g. a future batch job written without that step). Backstops: Tier 3 `reconcile_active_pks` for PK drift, Tier 4 `reconcile_aggregates` for mass value drift, and `reconcile_table` (P3-4) for definitive full-row hash comparison on high-criticality tables. Treat the modified-date sweep as the cheap daily catch-up layer; full-row reconciliation is the safety net.
- LT-3 (R-13 large-table backfill): `tools/backfill.py` re-processes an explicit date range via `process_large_table(..., dates_override=...)`. The orchestrator detects the override and uses the operator's date list verbatim instead of computing from `LookbackDays`/`FirstLoadDate`/checkpoints. The modified-date sweep step is suppressed during backfill — the explicit reload IS the action; sweep on top is redundant. `force=True` bypasses extraction guards (a backfill is already an authorized re-run). Idempotent: re-extracting an unchanged date produces no Bronze writes. Use case: discovered a January gap in March → `python3 tools/backfill.py --source DNA --table ACCT --from 2024-01-01 --to 2024-01-31`. CLI also accepts `--date YYYY-MM-DD` for single-day reprocess and `--dry-run` to list affected tables/dates without extracting.
- SCD2-R6 (Chain repair scope): `cdc/reconciliation/scd2_repair.py` and `tools/repair_scd2.py` ship three deterministically-safe auto-repairs and explicitly refuse to auto-fix anything ambiguous. Safe: `sentinel_fill` (Flag=1 rows missing `UdmSourceEndDate='2999-12-31'`); `orphan_cleanup` (B-4 in-flight orphans — predicate is the SCD2-P1-e hardened form); `duplicate_active_dedup` (close older Flag=1 rows per PK with `UdmSourceEndDate = winner_UdmSourceBeginDate - 1 day`). Refused: overlapping intervals, zero-active without Flag=2 (lost deletion context), source-date gaps, invalid Flag/Op domain values, Flag=2 with NULL `UdmEndDateTime`. Default mode is `--dry-run`; real changes require `--apply`. Every operation appends one row to `General.ops.SCD2RepairLog` (created by `migrations/scd2_repair_log.py`) with `RepairType`, `Status`, `RowsAffected`, `SamplePks` (JSON), and timing.
- B-13: Six Oracle→SQL Server type conversion pitfalls: (1) Oracle DATE includes time — `fix_oracle_date_columns()` upcasts `pl.Date` to `pl.Datetime` to prevent truncation. (2) Oracle NUMBER without precision can have >8 decimal places — document and monitor. (3) Oracle FLOAT(126) loses precision vs SQL Server FLOAT(53) — ~15 significant digits max. (4) Oracle RAW(16) GUID uses big-endian vs SQL Server mixed-endian — requires byte reordering if used as join keys. (5) Oracle BLOB/CLOB 4GB vs SQL Server 2GB limit — silent truncation possible. (6) Oracle VARCHAR2 BYTE vs SQL Server VARCHAR character semantics differ for multi-byte.
- B-14: The INSERT-first SCD2 pattern creates a transient zero-active-row window between closing old versions and activating new versions. Under RCSI, new readers during this window see zero active rows for affected PKs. Documented in `scd2/engine.py` module docstring. Defensive query pattern: `ROW_NUMBER() OVER (PARTITION BY pk_cols ORDER BY UdmEffectiveDateTime DESC) WHERE rn = 1`.
- DIAG-1 (Stage `_cdc_is_current=1` absence is normal for deleted PKs): When a PK is deleted from source, the CDC engine flips its `_cdc_is_current` from 1 to 0 and does NOT insert a new "delete marker" row in Stage. The PK ends up with zero `_cdc_is_current=1` rows. The audit trail of the delete lives in Bronze as `UdmActiveFlag = 2`. Operators investigating "missing current row" complaints should run `tools/inspect_cdc_pk.py --source <S> --table <T> --pk-values <PK>` — verdict `HEALTHY_DELETED` confirms the by-design behavior; any other verdict signals a real anomaly. Table-wide checks live in `tools/validate_cdc.py` (Stage current dups, Bronze active dups, hash divergence, in-flight orphans, Stage↔Bronze cross-layer drift, sampled source comparison). Both tools are read-only and complement `tools/validate_scd2.py` (which validates Bronze structural integrity in isolation).

## SQL Naming Standards (D105 — MANDATORY)

All new SQL objects created in `General` (or any other UDM database) MUST follow these conventions. **This is mandatory for every agent, sub-agent, skill, and human contributor.** Existing objects are grandfathered — do NOT retroactively rename. New objects only.

### Stored procedures
- **Database object name**: `General.{schema}.Proc{ProcedureName}` (PascalCase after the `Proc` prefix; no schema repetition inside the object name).
  - ✅ `General.ops.ProcProcessCcpaDeletion`
  - ✅ `General.ops.ProcEnforceRetention`
  - ❌ `General.ops.ops_ProcProcessCcpaDeletion` (schema repeated inside the object name)
  - ❌ `General.ops.processCcpaDeletion` (missing `Proc` prefix)
- **File name on disk**: `{schema}_Proc{ProcedureName}.sql` (schema-prefixed for filesystem grouping).
  - ✅ `ops_ProcProcessCcpaDeletion.sql`
  - ✅ `ops_ProcEnforceRetention.sql`
  - ❌ `ProcProcessCcpaDeletion.sql` (missing schema prefix)
  - ❌ `ops.ProcProcessCcpaDeletion.sql` (dot is for object names, underscore for filenames)

### Views
- **Database object name**: `General.{schema}.Vw{ViewName}`
  - ✅ `General.ops.VwActivePipelineRuns`
  - ✅ `General.dna.VwAcctCurrent`
  - ❌ `General.ops.vw_ActivePipelineRuns` (snake_case + lowercase prefix)
- **File name on disk**: `{schema}_Vw{ViewName}.sql`
  - ✅ `ops_VwActivePipelineRuns.sql`

### Grandfathered exceptions (do NOT rename)
Existing SP/view names that predate D105 are FINE as-is — D92 (forward-only schema discipline) applies. Examples that stay untouched:
- `General.ops.PiiVault_GetOrCreateToken`
- `General.ops.PiiVault_DecryptForOperator`
- Any other pre-D105 object discovered in the codebase

When you ENCOUNTER a grandfathered name, leave it alone. When you CREATE a new SP or view, apply D105.

### Tables, columns, indexes
No D105 mandate — existing conventions (PascalCase tables like `UdmTablesList`, mixed-case columns like `_cdc_is_current`, etc.) remain authoritative. D105 applies to procedures and views only.

### Enforcement
- `udm-decision-recorder`, `udm-runbook-author`, `udm-data-engineer-review` skills must check candidate SP/view names against D105 before locking artifacts that reference them.
- `udm-design-reviewer` + `udm-test-author` agents must flag D105 violations in any code, runbook, or schema-change proposal they review.
- `CHECKS_AND_BALANCES.md` Gate 1 (cross-reference) must include a naming-standard check for any new SP/view object referenced in the artifact under review.

## Claude Code Security Model (D103 — summary; canonical reference: `docs/migration/SECURITY_MODEL.md`)

**Claude Code operates only inside the `/debi` working directory. Credentials live OUTSIDE `/debi` and Claude has zero authorized read path to them.** This is the project's primary architectural defense for AI-assisted development.

### Per-environment posture (threat-surface inversion: dev > test > prod)
| Environment | Claude Code installed? | Why |
|---|---|---|
| **Dev workstation** | ✅ Yes (Windows or RHEL) | Highest threat surface — engineer AI-assists daily; deepest defense |
| **Test (RHEL)** | ❌ No | Image-baked NO-CLAUDE policy; test data has prod parity |
| **Prod (RHEL)** | ❌ No | Image-baked NO-CLAUDE policy; deployment is pull-from-registry only |

### Credential locations (Claude NEVER reads any of these)
- **Production (RHEL)**: `/etc/pipeline/.env` (mode 0400, pipeline:pipeline), `/etc/pipeline/credentials.json.gpg` (TPM2-sealed), `/dev/shm/snowflake_pk_<pid>` (ephemeral RSA, in-memory only)
- **Dev workstation (RHEL)**: `~/.ssh/`, `~/.gnupg/`, `~/.pipeline/`, `~/.aws/`, kernel keyring (`keyctl`)
- **Dev workstation (Windows)**: `C:/Users/<user>/.ssh/`, Credential Manager (DPAPI), `C:/ProgramData/Pipeline/`
- **NEVER inside `/debi`**: the project directory is sanitized — no `.env`, no `*.gpg`, no `*.pem`, no `*.key`, no `credentials.json`

### The 13 layers of defense (one-line summary; details in `SECURITY_MODEL.md`)
1. `/debi` working-directory boundary (Claude Code architectural)
2. `.claudeignore` patterns (human-readable inventory; community hook may enforce)
3. `.claude/settings.local.json` `permissions.deny` array (Claude Code enforced — Read/Bash/PowerShell deny rules for ~60 credential patterns)
4. No credential files on dev workstation inside any AI-accessible path
5. POSIX ACLs (`setfacl`) on RHEL + NTFS ACLs (`icacls`) on Windows — explicit deny for the Claude user against `~/.ssh/`, `~/.gnupg/`, `~/.aws/`, etc.
6. File-mode 0400 + ownership pipeline:pipeline on `/etc/pipeline/.env`
7. GPG-encrypted `credentials.json.gpg` at rest; decrypted in-memory only at pipeline start
8. OS-native credential vaults (Windows DPAPI / RHEL kernel keyring via `keyctl`) for dev secrets
9. `auditd` on RHEL — `/etc/audit/rules.d/pipeline-secrets.rules` watches `/etc/pipeline/` and `~/.ssh/` for any access; `ausearch -k pipeline_secrets`
10. `systemd-creds encrypt --with-key=tpm2` + `LoadCredentialEncrypted=` for service-managed secrets (TPM2-bound, cannot decrypt off the original machine)
11. **SELinux** on RHEL (enabled, enforcing) — RHEL-shipped MAC framework. `sestatus`, `ls -lZ`, `ps -eZ`, `audit2allow` for policy iteration. No AppArmor (open-source policy bans it).
12. Network isolation — Claude Code outbound restricted to allowlisted domains in `.claude/settings.local.json` `permissions.allow.WebFetch(domain:...)`
13. Image-bake check: production/test golden image build step fails if `which claude-code` returns 0

### What we use vs. what we don't (per user policy)
- ✅ RHEL-shipped tools (SELinux, auditd, systemd-creds, kernel keyring, POSIX ACLs, TPM2)
- ✅ Microsoft built-ins (DPAPI, NTFS ACLs, Credential Manager, Windows Defender baseline)
- ✅ Claude Code's own deny/allow lists in `.claude/settings.local.json`
- ❌ Commercial endpoint security (CrowdStrike, McAfee, MS Defender for Endpoint) — zero budget for paid security tools
- ❌ AppArmor — open-source MAC framework not shipped by RHEL; strict policy bans
- ❌ Third-party secrets managers (HashiCorp Vault SaaS, AWS Secrets Manager, Azure Key Vault) — deferred to Phase 5+ evaluation

### PiiVault encryption (D102 — AES-256-GCM)
- `PiiVault.EncryptedPlaintext` uses **AES-256-GCM** in Python (`cryptography` library).
- Wire format: `nonce (12 bytes) || ciphertext || auth_tag (16 bytes)` — single column, no separate IV/tag columns.
- Key managed via Phase 0.4 merger-context plan (TBD — likely TPM2-sealed on RHEL + DPAPI on Windows dev).
- Each token has a unique 12-byte random nonce per encryption operation; never reuse nonce + key.
- See `03_DECISIONS.md` D102 and `SECURITY_MODEL.md` § 4 for full crypto rationale.

### Operational discipline (DO / DO NOT)
- **DO** keep `/debi` clean — no committed `.env`, no committed `*.gpg`, no committed `*.pem`. Grep-check before every commit.
- **DO** add new credential paths to BOTH `.claudeignore` (documentation) AND `.claude/settings.local.json` `permissions.deny` (enforcement) when discovered.
- **DO** treat any `Read(...)` or `Bash(cat ...)` permission prompt for a credential path as a red flag — deny + investigate which agent/tool/skill is asking.
- **DO NOT** install Claude Code on test or prod RHEL servers. Image-bake check enforces this; do not whitelist around it.
- **DO NOT** loosen `.claude/settings.local.json` `permissions.deny` for the convenience of a single task — if a workflow legitimately needs credential access, the workflow runs OUTSIDE Claude (operator runs the script manually, pipes the result into the AI conversation as text).
- **DO NOT** commit anything from `~/.aws/`, `~/.ssh/`, `~/.gnupg/`, or any path matched by `.claudeignore` patterns.

### Incident response
If Claude Code is observed reading (or attempting to read) a credential file:
1. Capture the tool-call evidence (Read path + timestamp + agent invoking).
2. Check `auditd` (RHEL) or Event Viewer (Windows) for corroborating OS-level access logs.
3. Rotate the credential immediately (no debate — assume compromise).
4. Add the path to `permissions.deny` if not already present; verify `.claudeignore` parity.
5. File an incident note in `RISKS.md` under R32 (Claude credential-access risk) with the trigger event.

## Do NOT
- Do NOT truncate Bronze tables — SCD2 is append-only by design
- Do NOT use write_csv without batch_size=4096 on large DataFrames
- Do NOT add quoting to BCP CSV output — quote_style must always be 'never'
- Do NOT write True/False for BIT columns — must be 0/1 (Int8)
- Do NOT include _scd2_key (IDENTITY) in INSERT DataFrames or BCP column lists
- Do NOT assume source column order is stable — `reorder_columns_for_bcp()` enforces deterministic order, never bypass it
- Do NOT allow CDC to run if extraction returned 0 rows — the empty extraction guard (`_check_extraction_guard`) handles this; do not remove or weaken it
- Do NOT run full in-memory CDC/SCD2 comparison on large tables (3B+ rows) — use `run_cdc_windowed()` and `run_scd2_targeted()` which are date-partitioned
- Do NOT hardcode NVARCHAR(MAX) for PK columns in staging tables — always use `get_column_types()` from schema_utils.py
- Do NOT run overlapping pipeline instances on the same table — `orchestration/table_lock.py` enforces this via sp_getapplock; do not bypass it
- Do NOT use native Polars `hash_rows()` for row hashing — it is non-deterministic across Python sessions. Use the polars-hash plugin via `add_row_hash()` in bcp_csv.py
- Do NOT drop columns during schema evolution — `schema/evolution.py` logs WARNINGs for removed columns but never drops them. Data preservation is mandatory.
- Do NOT skip `_filter_null_pks()` before CDC comparison — NULL PKs cause duplicate inserts every run due to Polars NULL != NULL anti-join semantics
- Do NOT use `add_row_hash_fallback()` in production without first verifying it produces identical hashes to `add_row_hash()` on a test table — the fallback exists for polars-hash dependency failure scenarios only (V-11)
- Do NOT truncate SHA-256 hash output to Int64 — the full 64-char hex string must be stored as VARCHAR(64). Per-PK CDC comparison was safe at 64-bit (~1.6×10⁻¹⁰ risk — birthday paradox doesn't apply to per-key change detection), but full SHA-256 eliminates risk for adjacent operations (reconciliation, future surrogate keys, deduplication) where birthday-paradox collisions are real at 3B rows (~24%). See project research doc for full analysis (B-1)
- Do NOT set SCD2_UPDATE_BATCH_SIZE above 5,000 — SQL Server escalates to table-level exclusive locks at ~5,000 locks, overriding RCSI and blocking all concurrent readers (B-2)
- Do NOT remove `_cleanup_orphaned_inactive_rows()` from SCD2 entry points — orphaned Flag=0 rows from crash recovery accumulate silently and are never activated by normal flow (B-4)
- Do NOT query Bronze with only `WHERE UdmActiveFlag = 1` without dedup protection — use `ROW_NUMBER() OVER (PARTITION BY pk_cols ORDER BY UdmEffectiveDateTime DESC) WHERE rn = 1` to handle duplicate active rows from crash recovery windows (V-4)
- Do NOT use `\x00` (null byte) in hash sentinels — use `\x1F` (Unit Separator) instead. Null bytes cause C-string truncation in logging, FFI, and serialization layers, silently corrupting hash inputs (W-2)
- Do NOT use `pl.concat()` with `diagonal_relaxed` or `vertical_relaxed` without calling `validate_schema_before_concat()` first — silent type coercion (e.g., Int64 → Float64) can corrupt precision-sensitive values (W-7)
- Do NOT hash Categorical columns directly via polars-hash — it hashes the physical integer encoding, not the logical string value. Cast to Utf8 first. `add_row_hash()` handles this automatically (E-20)
- Do NOT change `@LockOwner` in table_lock.py from 'Session' to 'Transaction' without removing the explicit `sp_releaseapplock` call — Transaction-scoped locks with explicit release before COMMIT create a race condition under RCSI (W-8)
- Do NOT use `bcp_load(atomic=False)` for Bronze SCD2 loads — partial loads break SCD2 atomicity. Only Stage and ephemeral staging table loads should use `atomic=False` (E-3)
- Do NOT set `UdmActiveFlag=1` directly in `_build_scd2_insert()` for operation='U' — new versions must be inserted with UdmActiveFlag=0 and activated via `_activate_new_versions()` after closing old versions. Otherwise the filtered unique index rejects the INSERT (E-2)
- Do NOT change the semantic of `UdmEffectiveDateTime` or `UdmEndDateTime` — Silver and Gold read these as the load-time pair (arrival in UDM and load-time close). R-1/R-3 business-date semantics live on the separate `UdmSourceBeginDate` / `UdmSourceEndDate` pair. Mixing the two breaks downstream watermarking and skips historical backfill rows silently (SCD2-P1-a)
- Do NOT set `UdmSourceEndDate = NULL` on an active row — the sentinel `'2999-12-31'` is the invariant for `UdmActiveFlag = 1`. NULL on `UdmSourceEndDate` is reserved for in-flight inserts (Flag=0 + operation U/R) and is the orphan-detection marker for `_activate_new_versions` and `_cleanup_orphaned_inactive_rows` (SCD2-P1-c, SCD2-P1-e)
- Do NOT collapse the update-close and delete-close branches in `run_scd2` / `run_scd2_targeted` back into a single `_execute_bronze_updates()` call — their `UdmSourceEndDate` semantics differ (`source_begin - 1 day` vs `source_begin`), and mixing them breaks the business temporal chain even though the load-time `UdmEndDateTime` value is identical (SCD2-P1-b)
- Do NOT identify in-flight Bronze rows with only `UdmEndDateTime IS NULL` OR only `UdmSourceEndDate IS NULL` — the first matches active rows, the second matches legacy pre-Phase-1 closed rows. Always require BOTH plus `UdmActiveFlag = 0 AND UdmScd2Operation IN ('U','R')` (SCD2-P1-e)
- Do NOT bypass the `source_begin_date` parameter in `run_scd2` / `run_scd2_targeted` / `_build_scd2_insert` signatures. Orchestrators must pass the business date (`target_date` or `_extracted_at`); silently defaulting to `now()` populates `UdmSourceBeginDate` with a load timestamp and defeats the whole point of R-1 (SCD2-P1-a)
- Do NOT reintroduce the scalar `UdmSourceBeginDate = @dt` predicate in `_activate_new_versions()` — R-2 per-row waterfall values make that match silently miss every row, every update turns into an orphan-and-reinsert pair on the next run, and the update audit trail vanishes. PK-staging match is load-bearing (SCD2-P1-c, SCD2-P1-f)
- Do NOT bypass `table_config` on any `_build_scd2_insert()` call site. The waterfall expression (R-2) needs it to find `scd2_date_columns` and `default_begin_date`; without it every row gets the batch-level scalar and the per-row chain invariants (SCD2-P1-b update-close, SCD2-P1-c activation) become meaningless even for tables where waterfall is configured (SCD2-R2-a)
- Do NOT overwrite non-NULL values in `UdmTablesList` from autoconfig or the detect tool — manual operator choices are authoritative. `tools/detect_scd2_config.py` writes proposals to `UdmScd2ConfigProposal` for review; `--apply` only copies APPROVED rows. Autoconfig never writes directly to `UdmTablesList` (SCD2-P1-d)
- Do NOT skip wiring `table_config.exclude_from_hash` through `prepare_dataframe_for_bcp()` in new extractors — the field is populated from `UdmTablesList.ExcludeFromHash` and silently ignoring it puts `DATELASTMAINT` back into the row hash, producing phantom CDC updates on every source refresh (SCD2-R10.2)
- Do NOT collapse `UdmActiveFlag = 2` back into `0` for delete-close paths. `_execute_bronze_updates()` selects Flag based on `label_suffix`: Flag=2 for `delete_close`, Flag=0 for `update_close`. Legacy nonclustered indexes are filtered on `Flag = 2` and downstream queries with `WHERE Flag != 0` rely on the three-value semantic. Conversely, do NOT introduce Flag=2 in any insert path or in `_build_scd2_insert()` — Flag=2 belongs only to the delete-close UPDATE (SCD2-R4)
- Do NOT extend `tools/repair_scd2.py` with auto-repair for overlaps, source-date gaps, zero-active-without-Flag=2, invalid Flag/Op domain values, or Flag=2 rows with NULL `UdmEndDateTime`. Those defects represent state we can't safely reconstruct — auto-repairing destroys evidence and may corrupt history. R-6 is intentionally conservative; surface those via R-5 (`tools/validate_scd2.py`) and let an operator investigate (SCD2-R6)
- Do NOT change `cdc/source_verifier.py` `CDC_VERIFY_STRICT_ON_FAILURE` default from `1` to `0`. Strict-on-failure means a verification-query failure (network, permissions, syntax) treats every candidate delete as a false negative, so no Stage current rows close on uncertain ground. Flipping the default would silently re-enable the original flapping-source bug whenever the source connection has a hiccup. The non-strict path exists for explicit per-environment opt-out, not as a default. Likewise, do NOT skip the verifier call in `_run_cdc_core` — it must run on every non-empty `df_deleted` so the audit trail in `result.verify_before_close` is consistent across runs (Phase 2 of cdc_root_cause_blueprint.md)
- Do NOT collapse `extract/source_count_check.py` and `cdc/source_verifier.py` into a single check, and do NOT remove the `CDC_VERIFY_MAX_CANDIDATES` ceiling. They defend at different scales: the source-count check catches catastrophic partial extractions in one source query and aborts the run before CDC even runs; verify-before-close catches small false-positive deletes within the count-check tolerance band by querying source for the specific candidate PKs. Above `CDC_VERIFY_MAX_CANDIDATES` (default 10000), the verifier deliberately steps aside — the right defense at that scale is the count-check abort, not flooding source with hundreds of `WHERE pk IN (...)` batches (Phase 2 of cdc_root_cause_blueprint.md)
- Do NOT remove the autouse fixture `_disable_source_side_checks_by_default` from `tests/conftest.py` without providing equivalent isolation in every existing CDC test. The Phase 2 defenses make live source calls when invoked from `_run_cdc_core`; without the env-var-based disable, every unit test that exercises CDC would attempt to reach Oracle / SQL Server and fail. Tests that *want* the verifier or count-check ON re-enable via module-level `monkeypatch.delenv` (see `tests/unit/test_source_verifier.py` and `tests/unit/test_source_count_check.py`)
- Do NOT replace `_cdc_now_ms()` in `cdc/engine.py` with `datetime.now()` or `datetime.now(timezone.utc)` for the engine's `now` value. The expire step's `_cdc_valid_from < batch_valid_from` predicate compares a BCP-stored value (millisecond-precision per the BCP CSV Contract) against a pyodbc parameter (microsecond-precision end-to-end). Mismatched precision makes strict `<` match the just-inserted row and the expire UPDATE clobbers its own batch's writes — the alternating `I/U/I/U` symptom on every PK that updates. Naive (no tzinfo) is the second half of the invariant: a tz-aware parameter sends as `DATETIMEOFFSET` and SQL Server does an implicit timezone conversion when comparing `DATETIME2 = DATETIMEOFFSET`, silently producing a different UTC moment than what BCP stored. Same constraint as SCD2-P1-f, applied to the CDC engine. (CDC-NOW-MS)
- Do NOT replace `dataclasses.asdict(tc)` in `utils/cli_common.py::table_config_to_dict` with a hand-enumerated dict, and do NOT bypass `table_config_from_dict` in `main_large_tables.py::_process_table_worker` / `main_small_tables.py::_process_table_worker`. The hand-enumerated pattern silently dropped every new `TableConfig` field at the worker boundary (StripSuffix, MaxRowsPerDay, the entire SCD2 enhancement block all fell back to dataclass defaults on `--workers > 1` runs). Single-worker testing missed it because the no-pool path passes the live `TableConfig` object directly. The asdict/from_dict pair is the contract: every dataclass field round-trips automatically; adding a new field to `TableConfig` requires no other code changes. `tests/regression/test_worker_config_roundtrip.py` pins this. (WORKER-SERIALIZE)
- Do NOT flip the default of `UdmTablesList.StripSuffix` from `0` to `1` globally, and do NOT change `stage_full_table_name` / `bronze_full_table_name` in `orchestration/table_config.py` to drop the suffix unconditionally. The suffixes (`_cdc`, `_scd2_python`) are the only thing keeping Python-pipeline tables namespaced apart from legacy T-SQL pipeline tables that share the same `{SourceName}` schema (e.g. `dna.ACCT`). Per-table opt-in via `StripSuffix = 1` is the safe migration path — every row that hasn't been individually migrated keeps the legacy-disambiguating suffix. Removing the suffix globally would let Python-pipeline writes collide with legacy table names, with destruction-class consequences if the pipeline accidentally writes to a legacy table. (SS-1)
- (Additional rules to be added as we test and discover anti-patterns)

## Autonomous Rules
- Proceed without asking: refactoring shared utilities, adding type hints, fixing lint
- STOP and ask: changing BCP CSV format, modifying CDC/SCD2 comparison logic, altering table naming conventions, changing database/schema names, changing hash algorithm or polars-hash configuration, weakening or removing any edge case safeguard (P0-1 through P3-4)
- If a module fails to import: check sys.path.insert — project uses parent-directory imports
- Always verify BCP CSV format compatibility after ANY change to write functions
- Test with --table <single_table> --source DNA before running full pipeline

## Validation discipline (per D55 + D56 + D60 + D61 + D89-D91 in `docs/migration/03_DECISIONS.md`)

**Mandatory for all artifacts in the migration / planning project**:

1. **5-gate validation per artifact** (D55): cross-reference, QA, edge cases, edge case validation, idempotency/regression. See `docs/migration/CHECKS_AND_BALANCES.md`.
2. **Mandatory second-pass after 🔴** (D56): when first-pass returns 🔴, fixes get an INDEPENDENT second-pass before any 🟡 → 🟢 status flip. Producer ≠ first-pass ≠ second-pass agent.
3. **Round close-out** (D60): at end of every Phase round, run `udm-round-closeout` skill to update aggregate docs (HANDOFF.md, CURRENT_STATE.md, BACKLOG.md, RISKS.md, NORTH_STAR.md, 00_OVERVIEW.md, 02_PHASES.md) and verify cross-doc consistency.
4. **Pillar mapping + risk surfacing + backlog surfacing** (D61): every new decision cites NORTH_STAR pillar(s) served; design reviews surface risk deltas; validation 🟡s propose B-numbers for BACKLOG.
5. **Pattern F post-cascade audit** (D89/D90/D91 — 🟢 Locked 2026-05-11 post-Round-7 first-production-evidence + extended at Round 8 close-out): every round close-out runs Pattern F BEFORE round 🟢 lock. Layer 1 deterministic script (`tools/verify_cascade.py` — Triggers C/D/F: stale references, forward-cite resolution, aggregate-doc freshness). Layer 2 paired-judgment agents (`udm-cascade-auditor` × 2 — Triggers A/B/E: D-acceptance substantiation, B-item closure-target audit, CLAUDE.md convention registration). Round-level analog of D55 + Pattern E at artifact level. Pattern F is mitigation for R28 (round-level cascade self-attestation gap) per HANDOFF §8 Pitfall #11.
6. **Self-improvement skill suite** (D95-D99 — 🟢 Locked 2026-05-11 at Round 8 close-out via D99 convergence-confirmed acceptance): after Pattern F completes clean, the close-out cascade runs Section 10 of `udm-round-closeout` skill — 7 self-improvement skills + user-approval session. Skills: `udm-retrospective-collector` (8.A) / `udm-specialty-tuner` (8.B) / `udm-subclass-accumulator` (8.C) / `udm-producer-checklist-evolver` (8.D) / `udm-cycle-cadence-optimizer` (8.E) / `udm-cascade-audit-evolver` (8.G — B143) propose deltas; user reviews ONCE per round + approves YES/NO per delta within session; `udm-agent-prompt-versioner` (8.F) applies approved batch with semver versioning + archive per D98. Meta-doc: `docs/migration/SELF_IMPROVEMENT_DISCIPLINE.md`. Pitfall #9 sub-class 9.j formalized inline at HANDOFF §8 per D96 + B144 2-event evidence (R6 unscoped + R7 first-production).
7. **POLISH_QUEUE.md cosmetic-tracker discipline** (D113 — 🟢 Locked 2026-05-12 directly per D111 process-infra exemption analogous to D55 / D60 / D89-D91 / D95-D99): cosmetic / readability / status-render / supersession-crumb / stale-date items land in `docs/migration/POLISH_QUEUE.md` as **P-numbers** (P-1, P-2, ...). Distinct from B-numbers (substantive backlog work). Distinguishing test: does fixing the item change a decision body, runbook procedure, SP body, tool spec, or pipeline code? If YES → B-number; if NO → P-number. Status legend matches BACKLOG.md per Pitfall #9.j (🟡 Open / 🟠 Noticeable / ⚫ CLOSED / ⬜ Deferred); closure-render discipline preserved via strikethrough body + closure date + closure-mechanism line. Round-close-out cascade skims P-items per `udm-round-closeout/SKILL.md` CCL Stage 2.5; Pattern F audit coverage via `udm-cascade-audit-evolver/SKILL.md` Trigger B + E extensions; 5-gate cross-reference findings that are cosmetic-only land as P-N candidates per `udm-checks-and-balances/SKILL.md` Gate 1 guidance. ⬇️ DE-ESCALATES sub-class of R28 (round-level cascade self-attestation gap — render-drift now has typed substrate instead of leaking into BACKLOG WSJF view or ad-hoc deferral lists).
8. **Execution classification discipline** (skill `udm-execution-classifier` introduced 2026-05-12 at build-mode pivot per user-direction "I'll need to be aware of any one off scripts. If a tool need to be run once, I'll need to know"): every newly-authored executable artifact (script / tool / migration / runbook procedure / CLI command) MUST be classified along (Manual vs Scheduled trigger) × (One-time vs Recurring frequency) axes; routes to canonical tracker — one-time + ad-hoc → `ONE_OFF_SCRIPTS.md`; scheduled-recurring → `phase1/02_configuration.md` § 5.1 frozen-N Automic inventory. Invoke after authoring any executable artifact OR during design-review Gate 1 cross-reference sub-check OR during round close-out cascade. **Hard rule**: 🟢 Lock on built code WITHOUT a classification entry in the appropriate tracker is a status mismatch (same severity as "🟢 Locked WITHOUT `_validation_log.md` entry"). See `.claude/skills/udm-execution-classifier/SKILL.md` for procedure + classification matrix + examples.
9. **Progress-logger discipline** (skill `udm-progress-logger` introduced 2026-05-12 per user-direction "make it a skill to ensure that all agents, sub-agents and multi-agent teams keep our progress tracked"): every agent / sub-agent / multi-agent team that completes substantive work (B-item closure / fix-cycle landing / decision lock / runbook authoring / tool build / multi-unit cohort) MUST invoke `udm-progress-logger` to update canonical trackers IMMEDIATELY when the work lands — `BACKLOG.md` (strikethrough + ⚫ CLOSED + mechanism), `_validation_log.md` (event row under current round), and any applicable tier-tracker (`ONE_OFF_SCRIPTS.md` / `POLISH_QUEUE.md` / `RISKS.md` / `03_DECISIONS.md`). Fills the mid-round tracker-drift gap that `udm-round-closeout` only catches at end-of-round (too late if subsequent context proceeds for 24+ hours on stale trackers). **Hard rule**: substantive completion claim WITHOUT a `_validation_log.md` row in the same session is a status mismatch (same severity as #8). Invocation is per-completion (mid-round), not per-round (round-aggregate). See `.claude/skills/udm-progress-logger/SKILL.md` for procedure + tracker-routing matrix + 5-step checklist.
10. **Code-build progress dashboard** (`docs/migration/CODE_BUILD_STATUS.md` introduced 2026-05-12 per user-direction "tracking progress on completing the coding tasks"): single-pane view of which CODE artifacts (Round 4 operator tools / Round 3 core modules / migrations / pipeline core / Phase 0 prep + closure tools) are built, tested, and deployed. Status legend: ⬜ Specified / 🟡 In progress / 🟢 Built (tests pass; pending deployment) / ✅ Deployed (on a target server) / ⚫ Archived. Distinct from `BACKLOG.md` (meta-work + doc edits) + `ONE_OFF_SCRIPTS.md` (per-script operational tracking) + `phase1/02_configuration.md` § 5.1 (scheduled tools registry). **Hard rule (per `udm-progress-logger` discipline hard rule 7)**: no code-build 🟢 status flip without corresponding `CODE_BUILD_STATUS.md` per-unit row state transition + date + test pass-count. Every agent / sub-agent / multi-agent team building code MUST update this tracker at the moment of build-state transition, NOT batched to round close-out. Optional skim at start of any code-build agent invocation (prevents duplicate work) + at round close-out cascade (verify aggregate counts match per-unit tables).
11. **Gap-check discipline** (skill `udm-gap-check` introduced 2026-05-12 per user-direction "Ensure that all agents, sub-agents and multi-agent teams run a gap check after the enhancements are built out. Turn this into a requirement for them to follow or a skill or whatever gets them to run this check. A trigger perhaps."): every agent / sub-agent / multi-agent team that completes substantive build / enhancement / multi-artifact discipline work MUST invoke `udm-gap-check` IMMEDIATELY AFTER `udm-progress-logger` logs the completion AND BEFORE the work is claimed 🟢 complete. The skill spawns an INDEPENDENT reviewer agent (per D55+D56 producer ≠ reviewer) that walks the canonical 6-category audit: (1) cross-tracker drift, (2) untracked dependencies / blockers, (3) Pitfall #9.a-9.m sub-class instances, (4) convention registration gaps, (5) untracked B-N opportunities, (6) just-noticed issues. **Hard rule**: no 🟢 status claim WITHOUT a gap-check `_validation_log.md` entry showing reviewer verdict ≤🟡. 🔴 verdict BLOCKS 🟢 until fixed + mandatory second-pass per D56. 🟡 findings get inline-fix OR B-N opening — no silent deferral. Empirical evidence base: 3-wave 2026-05-12 session — EVERY wave's gap check found 🟡 issues the producer self-check (HANDOFF §8 Steps 1-9) missed (F-1 line-anchor drift / B219 + B220 surface / stale test counts in CODE_BUILD_STATUS / etc.). Producer self-check is necessary-but-insufficient at post-completion timescale; gap-check operationalizes the discipline. See `.claude/skills/udm-gap-check/SKILL.md` for procedure + 6-category template + integration with existing skills.
12. **Build-tier empirical calibration** (per B-226 — 🟢 CLOSED 2026-05-13 via 5-event evidence base from Wave 1+2 builds): when estimating Tier α/β/γ/δ classification for a Round 3+ build module/tool, weight the following SIGNALS as Tier-β-or-larger triggers (rather than the default Tier α "<10 KB" heuristic that systematically under-estimated 5 of 9 Round 3 Wave 1+2 modules):
   - **Auto-populating from canonical DDL** — modules that read INFORMATION_SCHEMA or canonical Round 1 DDL to construct typed dataclasses / row-tuples (e.g. `extraction_state.most_recent_success` reads `PipelineExtraction`; `parquet_registry_client.query_snapshot` reads `ParquetSnapshotRegistry`) → minimum **Tier β** regardless of file-size heuristic
   - **Comprehensive error-mode coverage** — modules whose `Error modes` section in the spec lists ≥3 distinct exception classes typically need exhaustive `pytest.raises` coverage in Tier 1 → minimum **Tier β**
   - **Subprocess / external-process orchestration** — modules that shell out to `tpm2_unseal` / `gpg` / `bcp` / Snowflake CLI have platform-detection + retry + error-translation surface → minimum **Tier β** (e.g. M7 credentials_loader)
   - **State-machine encoding** — modules implementing a multi-state transition graph (e.g. M3 parquet_registry_client's `created → verified → replicated → archived → purged` state machine with `_LEGAL_TRANSITIONS` table) → **Tier γ** (100 KB-class)
   - **INSERT/UPDATE state-machine helpers** — modules with `try-INSERT-catch-UNIQUE-violation-then-SELECT-existing` patterns (e.g. M10's `record_extraction_attempt`, M9's `ledger_step`, M3's `_flip_status`) → minimum **Tier β**
   - **Connection-pool / cursor-ownership** — modules that maintain their OWN connection pool separate from `cursor_for` (e.g. M6 vault_client's separate `_vault_pool`) → minimum **Tier β**
   - **Cross-module composition contract** — modules whose spec explicitly states "every other module composes through this" (e.g. M9 idempotency_ledger per § 4.1) → minimum **Tier β**

   **Application**: when invoking the Plan subagent for build-DAG sequencing, EXPLICITLY pass these heuristics as part of the prompt so the agent applies them to Round 3 + Round 4 tier estimates. Per D97 cycle cadence, Tier-β requires "Pattern E + 2-3 verify" verification discipline (vs Tier-α's lighter "D56 2-pass"). Mis-classifying a Tier-β module as Tier α led to no actual quality regressions in Wave 1+2 (all builds closed with ≤2 inline fix cycles), but the discipline-mismatch is a latent risk for Wave 3+ where modules may have more emergent complexity (e.g. M17 snowflake_uploader's COPY-INTO retry + RSA key materialization).

**Hard rule**: 🟢 Locked status WITHOUT a `_validation_log.md` entry is a status mismatch and must be corrected.

**Pitfall #9 sub-class 9.j — B-item status-render discipline** (FORMALIZED 2026-05-11 at Round 8 close-out per D96 + B144): B-item entries showing leading status badge (e.g., `🟡 Open`) AND inline `**CLOSED YYYY-MM-DD**` annotation in the same row create render-discipline drift. The inline annotation is canonical; the leading badge stale. **Producer self-check Step 6** (extends 9.i 5-step audit to 6 steps): after ANY cycle-N or close-out edit that adds/closes a B-item, verify leading badge matches inline annotation; flip badge if mismatch.

**Pitfall #9 sub-classes 9.k / 9.l / 9.m** (FORMALIZED 2026-05-12 per B198 / B201 / B196): **9.k — arithmetic-propagation drift** (count / row-index updated in one location, mirrors not propagated; 5-event evidence base from 2026-05-12); **9.l — canonical-schema-detail working-memory drift** (fix references canonical schema object but producer skipped re-read of canonical DDL; 5-event evidence base from Phase 2 R1 spec doc Pattern E cycles 2-6); **9.m — discipline-not-applied-to-its-own-tracker** (new tracker / skill / discipline authored without immediately applying its rule to itself; 2-event evidence base 2026-05-12 D113 + udm-progress-logger). **Producer self-check Steps 7 / 8 / 9** (extend 9.j 6-step audit to 9 steps): (7) regex-sweep + enumerate when counts change; (8) re-read canonical DDL before fixing schema-referencing procedures; (9) apply new discipline to its own authoring artifact + verify pass. See HANDOFF §8 Pitfall #9 sub-class accumulator for full evidence bases + structural fixes.

**Round 7 SP signature evolutions (per `phase1/07_schema_evolution_governance.md`)**:
- **SP-4 `@AcknowledgmentOnly` BIT = 0 parameter** (per B79 closure 2026-05-11) — additive parameter on `General.ops.PipelineExecutionGate_AcquireTest`; when `@AcknowledgmentOnly = 1`, SP returns `@Action = 'EXIT_ACKNOWLEDGED'` without state mutation (dry-run mode for `tools/promote_test_to_prod.py` per Round 4 § 3.6). Forward-only additive — all existing callers compatible via default value.
- **SP-10 `@CutoffOverride DATETIME2(3) = NULL` + `@CategoryFilter NVARCHAR(MAX) = NULL`** (per B93+B94 closures 2026-05-11) — additive on `General.ops.PiiVault_EnforceRetention`. `@CutoffOverride` permits operator override of computed cutoff; `@CategoryFilter` restricts to PiiCategory CSV list. Joint migration script. SchemaContract row added per § 4.5. Forward-only additive.
- **SP-12 `General.ops.PiiVault_ProcessCcpaDeletion`** (per B81 closure 2026-05-11) — NEW SP for RB-10 CCPA right-to-deletion. Parameters `@RequestId UNIQUEIDENTIFIER`, `@SubjectIdentifier NVARCHAR(MAX) = NULL`, `@TokenList NVARCHAR(MAX)`, `@LegalExceptionReason NVARCHAR(MAX) = NULL`, `@RequestedBy NVARCHAR(255)`, `@Actor NVARCHAR(255)`, `@DryRun BIT = 1`. COALESCE on `@SubjectIdentifier` to synthetic placeholder `'TOKEN_FILE_BULK_<RequestId>'` for canonical NOT NULL preservation in CcpaDeletionLog.

**Forward-only additive schema evolution discipline (per D92 — locked 2026-05-11)**: Round 1 artifacts forward-only; locked-artifact-change via SchemaContract chain (table 23, IX_SchemaContract_Active filtered unique). New SP / new column / new Automic job / new Phase 0 deliv permitted via additive ALTER + SchemaContract row. Rename / removal NOT permitted post-lock. SP signature evolution additive-only with default-value caller-compat — new parameters at END of existing parameter list OR before OUTPUT params with named-syntax caller verification (per § 1.2 + B159). Operationalizes D40.

**Edge case series**: M/S/I/N/P/G/D/F/V (Rounds 1-5) + **DP** (Round 6 deployment-pipeline series per `04_EDGE_CASES.md:163` — DP1-DP7 added at Round 6 close-out per B121) + **T** (Round 5/6 testing series per `04_EDGE_CASES.md:179` — T1-T4 added at Round 5 + Round 6 close-out per B108 + B121) + **SI** (Round 8 self-improvement-discipline series — SI1-SI23 per `04_EDGE_CASES.md` SI section; tracked at `phase1/08_sub_agent_self_improvement.md` § 10). **12 canonical series total** (M/S/I/N/P/G/D/F/V/DP/T/SI). Pattern E R1C1-3 caught the L634-stale-summary canonical-source drift 2026-05-12; tracked in POLISH_QUEUE for future P-N cosmetic cleanup of summary references that lag the register.

**Read order for AI agents working on the migration / planning project**:
1. `docs/migration/CURRENT_STATE.md` — where we are now
2. `docs/migration/HANDOFF.md` — continuity context (per D60)
3. `docs/migration/GLOSSARY.md` — code/acronym reference (D-numbers, R-numbers, B-numbers, RB-N, SP-N, Pitfall #N, Pattern A-F, Tier α/β/γ/δ, etc. — if you see a short-form identifier and don't recognize it, look here)
4. `docs/migration/NORTH_STAR.md` — conflict-resolution rubric (per D61)
5. `docs/migration/RISKS.md` — active delivery risks (per D61)
6. This file (CLAUDE.md) — technical history, gotchas, Do-NOT rules
7. Phase-specific docs as needed

## Error Recovery
- BCP row count mismatch -> investigate string sanitization, check for new control characters in source data
- BCP column count mismatch -> source schema changed (new/dropped column). `schema/evolution.py` handles new columns automatically; removed columns log WARNING. Check PipelineLog for SchemaEvolutionError if a type changed.
- ConnectorX connection failure -> verify .env credentials, check Oracle listener, try oracledb fallback
- CDC table auto-create failure -> check schema exists, verify _polars_dtype_to_sql mapping covers the dtype
- SCD2 staging table cleanup -> _execute_bronze_updates drops staging table in finally block; run `schema/staging_cleanup.py` to clean orphans from crashes
- Sudden spike in CDC "updates" for all rows -> likely a Polars upgrade invalidating polars-hash output (check changelog), or column order shifted (check `reorder_columns_for_bcp` warnings in PipelineLog), or schema evolution added a column (check PipelineEventLog metadata for `"schema_migration": true` — B-3)
- Orphaned Flag=0 rows in Bronze (UdmActiveFlag=0, UdmEndDateTime IS NULL) -> `_cleanup_orphaned_inactive_rows()` handles this automatically at the start of each SCD2 run (B-4). If manual cleanup is needed: `DELETE FROM Bronze WHERE UdmActiveFlag = 0 AND UdmEndDateTime IS NULL AND UdmScd2Operation IN ('U','R')`
- Hash migration from BIGINT to VARCHAR(64) -> run `python3 migrations/b1_hash_varchar64.py --dry-run` first, then without --dry-run during maintenance window. First pipeline run after migration rehashes all rows. The migration was driven by defense-in-depth for adjacent operations (reconciliation, future joins) where birthday-paradox risk is real at 3B rows, not by per-PK CDC risk which was safe at 64-bit (B-1)
- Extraction returns 0 rows -> extraction guard blocks CDC automatically. Check Oracle listener, network, permissions. Use `--force` only after confirming the empty extraction is intentional.
- Duplicate rows appearing in Bronze -> check PipelineLog for table lock acquisition failures (another run may have bypassed locking), or check for NULL PKs in PipelineEventLog metadata (null_pk_rows field)
- Large table OOM -> extraction window too wide for available memory. Reduce LookbackDays or verify the per-day processing path is being used (orchestration/large_tables.py processes one day at a time)
- Schema evolution error skipping table -> a source column changed type. Requires manual resolution: verify the type change is intentional, ALTER the target column or re-create the table, then re-run with `--force`
- Table lock not acquired -> another pipeline run is processing the same table. Wait for it to complete, or check for stale sessions if the other run crashed (Session-owned sp_getapplock locks auto-release on disconnect)