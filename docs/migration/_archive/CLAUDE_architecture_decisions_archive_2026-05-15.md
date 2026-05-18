<\!-- Archive provenance:
- Extracted from: CLAUDE.md (pre-trim state at commit c189432 / 2026-05-15 / 720 lines total)
- Extracted at: lines 214-291 (78 lines verbatim)
- Trim commit: 7e2c606 (D.5 Approach A — Conservative trim per Q-12 approved)
- Trim rationale: section was largely DUPLICATE of canonical content at the destination(s); replaced in active CLAUDE.md with summary + cross-ref to reduce CCL token cost
- Destination cross-ref(s) in active CLAUDE.md: docs/migration/phase1/01_database_schema.md (canonical 2,167 lines)
- Archive strategy: belt-and-suspenders per user-direction 2026-05-15 (Option B "Archive EVERYTHING verbatim"); content preserved for recovery without git archaeology
- Reversibility: `git show c189432:CLAUDE.md` returns full pre-trim CLAUDE.md; this archive is a partial slice
- Authored: 2026-05-15 by retroactive archive sweep per refactor-strategy decision
- Linked from: docs/migration/_refactor_log.md (refactor event D.5-architecture-decisions)
-->

# CLAUDE.md — Key Architecture Decisions (archived)

**This is an archived copy** of the Key Architecture Decisions section from CLAUDE.md, extracted verbatim from the pre-D.5-trim state. The active CLAUDE.md no longer contains this section — see cross-ref destination(s) above for the canonical home(s).

If you arrived here looking for current information: prefer the destination cross-ref. This archive exists for recovery + audit-trail purposes only.

---

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
