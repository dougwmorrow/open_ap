# Phase 1 Round 1.5a — Control Tables (the Trigger Tier)

**Status**: 🟡 Proposed — pending Round 1.5 D72 validation campaign + Pattern F close-out audit
**Round position**: Round 1.5 — Schema Documentation Supplement (additive to Round 1 schema doc; does NOT modify the locked Round 1 + Round 2 specs per D92 forward-only discipline)
**Authored**: 2026-05-11

This supplement closes the schema-story gap identified in the post-Round-8 reflection: a reader of `phase1/01_database_schema.md` alone cannot understand how the pipeline knows what to extract. This doc consolidates the trigger-tier story.

---

## § 0 — Read order + foundational context

### 0.1 Required reading (per D62 CCL Stage 1+2)

Before reviewing this artifact:
1. `docs/migration/NORTH_STAR.md` — pillar priority
2. `docs/migration/HANDOFF.md` — locked vs in-flight; §3 D-numbers D62 (CCL), D63 (UdmTablesList 6 new columns), D40+D92 (forward-only schema discipline)
3. `docs/migration/CURRENT_STATE.md` — Round 1.5 supplements in flight; Phase 1 Rounds 1-8 complete
4. `docs/migration/CHECKS_AND_BALANCES.md` — 5-gate + Tier β validation expectations
5. `docs/migration/GLOSSARY.md` — code/acronym reference
6. `docs/migration/phase1/01_database_schema.md` — Round 1 (the 24 `General.ops.*` tables; this supplement is its trigger-tier complement)
7. `docs/migration/phase1/02_configuration.md` § 1 — Round 2 canonical UdmTablesList inventory (29 base + 6 D63 columns); this doc references but does NOT supersede Round 2 § 1
8. `CLAUDE.md` (project root) — production-code reference for `UdmTablesList` + `UdmTablesColumnsList` + `column_sync.py` discovery flow

### 0.2 Why this doc exists

Round 1 (`phase1/01_database_schema.md`) defined the 24 `General.ops.*` tables — what the pipeline **records about itself** as it runs. Round 2 § 1 (`phase1/02_configuration.md`) defined `UdmTablesList` — what **triggers** the pipeline. The split was deliberate (Round 1 = destinations + observers; Round 2 = configuration), but it left a story gap: a DBA or engineer reading Round 1 alone cannot answer "how does the pipeline know which tables to process?"

This doc closes that gap. It is a **navigation supplement** — it consolidates pointers to canonical content already present in Round 2 + CLAUDE.md, presents both control tables as one coherent layer, adds the observability hooks dashboards need to wire up, and walks the lifecycle (when rows are added / updated / deleted in these tables).

### 0.3 Scope

**In scope** (this document):
- § 1: Control tier vs operational metadata tier (the conceptual split)
- § 2: `General.dbo.UdmTablesList` canonical column inventory (references Round 2 § 1.1 + 1.2 + Round 7 R-2 SCD2 fields)
- § 3: `General.dbo.UdmTablesColumnsList` canonical column inventory (per CLAUDE.md "Column Tracking" + `schema/column_sync.py` metadata additions)
- § 4: How the two tables relate (join semantics; Layer discriminator)
- § 5: Lifecycle — when rows get added, updated, deleted
- § 6: Example rows (3 concrete examples: DNA ACCT small; DNA CARDTXN large; EPICOR transactional)
- § 7: Primary-key discovery flow per source-system type
- § 8: Observability hooks — which control-table columns power which dashboards
- § 9: Edge cases (M/S/I/F/V series walk for control-tier failure modes)
- § 10: Validation gates self-check

**Out of scope** (deferred or covered elsewhere):
- The 24 `General.ops.*` operational metadata tables (`phase1/01_database_schema.md`)
- The Bronze + Stage table DDL example (`phase1/01b_bronze_stage_example_ddl.md` — sibling G3+G4 supplement)
- The end-to-end data flow narrative (`phase1/01c_data_flow_walkthrough.md` — sibling G6 supplement)
- The Automic job inventory + scheduling (`phase1/02_configuration.md` § 5)
- The actual column-sync / table-creator Python implementations (`schema/column_sync.py` + `schema/table_creator.py` — covered by `CLAUDE.md` Architecture Decisions section + Round 3 module interface specs)

### 0.4 Foundational decisions

| # | Decision | Round 1.5a dependency |
|---|---|---|
| D34 | Greenfield deployment | UdmTablesList INSERT-then-process model; no migration-from-legacy path |
| D40 | Schema evolution governance lock | Round 1.5a is supplement, NOT schema change; locked Round 1 + Round 2 specs untouched |
| D62 | CCL doctrine | This doc's read order respects CCL Stage 1+2 |
| D63 | UdmTablesList 6 new columns (CDCMode, PiiColumnList, DataClassification, CohortAssignment, IsEnabled, LegalHoldOnly) | § 2.5 enumerates these |
| D92 | Forward-only additive schema evolution | Round 1.5a is doc-level supplement; no DDL changes |
| D95 | Self-improvement skill suite | Round 1.5a validation produces ledger entries that feed 8.A retrospective-collector at Phase 2 R1 close-out |

### 0.5 Constituent decisions (proposed; locked at Round 1.5 close-out)

- **D100** — Documentation supplement discipline (Round-N.5 mini-rounds; additive-only; tier-α/β validation per D97)

(Other gaps G2-G6 covered in sibling supplements; not new D-numbers each — the supplement-doc pattern is the load-bearing decision.)

---

## § 1 — Control tier vs operational metadata tier

The UDM pipeline has two distinct database-resident metadata layers, both in the `General` database but in different schemas:

| Layer | Schema | Purpose | Read or write? | Tables |
|---|---|---|---|---|
| **Control tier** | `General.dbo` | Tells the pipeline what to do | Pipeline READS at startup + during execution | `UdmTablesList`, `UdmTablesColumnsList` |
| **Operational metadata tier** | `General.ops` | Records what the pipeline did | Pipeline WRITES during execution; downstream consumers READ for observability | 24 tables (see `phase1/01_database_schema.md`) |

This separation is important:

1. **Permissions**: control tier is operator-editable (DBA + pipeline lead can update `UdmTablesList` rows to enable/disable tables, change CDC mode, set cohort assignments). Operational metadata tier is pipeline-write-only (operators query but should never `UPDATE`/`DELETE` rows directly — manual corrections go through `ManualCorrectionLog`).

2. **Backup cadence**: control tier should be backed up before any operator-driven change. Operational metadata tier is backed up per standard 7-year retention (D30) but corruption recovery is via re-running the pipeline (idempotent per D15).

3. **Audit semantics**: control tier changes are recorded in `General.ops.ManualCorrectionLog` (every `UPDATE UdmTablesList SET ...` writes a correction-log row per § 5.3 below). Operational metadata tier is append-only by design (`PipelineEventLog`, `PipelineLog`, etc.) — corrections come via reconciliation runs not direct edits.

4. **Greenfield deployment relevance** (D34): both layers are CREATEd on fresh deploy. The control tier needs SEED data (`UdmTablesList` rows for each source table to extract) — Phase 2 R1 pilot table selection (Phase 0 deliverable 0.7) is the first row insert. Operational metadata tier is created empty; rows accumulate from first pipeline run.

---

## § 2 — `General.dbo.UdmTablesList` canonical column inventory

**Authoritative source**: `phase1/02_configuration.md` § 1.1 (29 pre-Phase-1 columns) + § 1.2 (6 new D63 columns) = 35 columns. This § is a navigation aid; if it contradicts Round 2 § 1, Round 2 wins.

### § 2.1 At-a-glance column families

The 35 columns group into 5 functional families:

| Family | Columns | Purpose |
|---|---|---|
| Source connection + routing (12) | `SourceObjectName`, `SourceServer`, `SourceDatabase`, `SourceSchemaName`, `SourceName`, `SourceAggregateColumnType`, `SourceAggregateColumnName`, `FirstLoadDate`, `LookbackDays`, `SourceIndexHint`, `PartitionOn`, `StageLoadTool` | Where to extract FROM; how to extract (oracledb vs ConnectorX); date column for large-table windowing; whether this table is owned by Python pipeline |
| Target naming (3) | `StageTableName`, `BronzeTableName`, `StripSuffix` | Where to extract TO; custom name overrides; legacy-disambiguation suffix toggle (per SS-1) |
| Per-table thresholds (1) | `MaxRowsPerDay` | Override for daily-extraction growth guard (P1-13) |
| SCD2 enhancement block (12) | `SCD2Mode`, `SCD2DateColumns`, `SourceDeleteDateColumn`, `DuplicateResolutionOrder`, `AllowDuplicates`, `PreserveDateTime`, `RepairChainAfter`, `AllowGaps`, `ExcludeFromHash`, `DefaultBeginDate`, `ForceNewSegmentColumns`, `ExpectedRetentionDays` | Per-table SCD2 waterfall + dedup + hash exclusion + retention classification (per SCD2-P1-d + SCD2-R2-a + SCD2-R8 + SCD2-R10.2 + SCD2-R2-b) |
| Reconciliation (1) | `LastModifiedColumn` | Source modification-timestamp column for Tier-2 modified-date sweep (LT-2) |
| Pipeline build additions (6) | `CDCMode`, `PiiColumnList`, `DataClassification`, `CohortAssignment`, `IsEnabled`, `LegalHoldOnly` | Net-new for this build per D63 |

**Total: 12 + 3 + 1 + 12 + 1 + 6 = 35 columns.**

### § 2.2 Source connection + routing family (columns 1-12)

These columns tell the pipeline WHERE to read from + HOW to read. Canonical type definitions live in `phase1/02_configuration.md` § 1.1.1.

Per CLAUDE.md "Key Architecture Decisions" — extraction routing:

```
If SourceIndexHint IS NOT NULL:
    → oracledb extractor (date-chunked, INDEX-hinted)
Elif Oracle source AND PartitionOn IS NOT NULL:
    → ConnectorX partition_on (parallel)
Elif Oracle source:
    → ConnectorX bulk FULL scan
Elif SQL Server source:
    → connectorx_sqlserver_extractor (bulk FULL scan)
```

`StageLoadTool` is the master switch: `'Python'` → this pipeline owns the table; `NULL` → skip (table is owned by another pipeline or has no pipeline yet).

### § 2.3 Target naming family (columns 13-15)

| Column | Default behavior | Override |
|---|---|---|
| `StageTableName` | `UDM_Stage.{SourceName}.{SourceObjectName}_cdc` | When set, becomes `UDM_Stage.{SourceName}.{StageTableName}_cdc` |
| `BronzeTableName` | `UDM_Bronze.{SourceName}.{SourceObjectName}_scd2_python` | When set, becomes `UDM_Bronze.{SourceName}.{BronzeTableName}_scd2_python` |
| `StripSuffix` | `0` (default) — preserve `_cdc` / `_scd2_python` suffix (legacy-disambiguation per SS-1 Do-NOT rule) | `1` — drop the suffix (used by AuditLog + CARDTXN migrating off legacy T-SQL pipeline) |

**Hard rule** (per CLAUDE.md SS-1): `StripSuffix=1` is per-table opt-in, NEVER a global default flip. Flipping globally would let Python-pipeline writes collide with legacy T-SQL table names.

### § 2.4 SCD2 enhancement family (columns 17-28)

Per Round 7 R-2 + SCD2-P1-d + SCD2-R2-a + SCD2-R8 + SCD2-R10.2 + SCD2-R2-b discipline. These 12 columns drive SCD2-tier behavior per-table.

**Canonical defaults preserve pre-Phase-1 behavior bit-for-bit**: `SCD2Mode = 'incremental'`, all other SCD2-tier columns `NULL` or `0`. A table with these defaults runs identically to the pre-build pipeline.

Notable columns:
- **`SCD2DateColumns`** — CSV waterfall for per-row `UdmSourceBeginDate` (e.g., `'DATEOPENED,DATELASTMAINT'`). NULL falls back to batch-level scalar.
- **`ExcludeFromHash`** — CSV of column names to drop from row-hash input (e.g., DNA's `DATELASTMAINT` to prevent phantom CDC updates per SCD2-R10.2). **First run on existing Bronze triggers a one-time mass-update wave** (B-3-class behavior) — schedule during maintenance window.
- **`ExpectedRetentionDays`** — per-table retention horizon. Drives delete-close classification: "within retention" (expected purge, INFO) vs "exceeds retention" (anomalous delete, WARNING).
- **`LastModifiedColumn`** — source-system modified-timestamp column for Tier-2 sweep (LT-2). Typical DNA value: `'DATELASTMAINT'`. CCM + EPICOR have NULL — neither has the column.

### § 2.5 Pipeline build additions (D63 — columns 30-35)

Per Round 2 § 1.2:

| Column | Type | NULL | Default | Purpose |
|---|---|---|---|---|
| `CDCMode` | `NVARCHAR(20)` | NO | `'change_detect'` | Per-table CDC mode flag; `'change_detect'` (legacy) or `'parquet_snapshot'` (new build). Phase 4 cutover flips per-table atomically. |
| `PiiColumnList` | `NVARCHAR(MAX)` | YES | `NULL` | CSV of column names to tokenize via SP-1 before row-hash (e.g., `'SSN,EMAIL,PHONE'`). NULL = no PII columns. |
| `DataClassification` | `NVARCHAR(20)` | YES | `NULL` | `'PII'` / `'PCI'` / `'none'` / `NULL` (not yet classified). Drives retention SLAs. |
| `CohortAssignment` | `NVARCHAR(50)` | YES | `NULL` | Free-text Phase 4 rollout cohort tag (e.g., `'cohort-1-pilot'`). |
| `IsEnabled` | `BIT` | NO | `1` | Operator toggle — `0` pauses extraction for this table. Distinct from `StageLoadTool IS NULL` (permanent skip). |
| `LegalHoldOnly` | `BIT` | NO | `0` | Per D30 legal-hold override. When `1`, table is held against retention purge. |

### § 2.6 Indexes on UdmTablesList

Per Round 2 § 1 + production reality (per CLAUDE.md):
- Primary key: `(SourceName, SourceObjectName)` — composite, matches the natural identity of a source table
- Filtered index on `(IsEnabled, StageLoadTool)` for fast "what runs this AM cycle?" startup query — Round 1.5a recommendation; verify with DBA if absent
- No clustered columnstore (table is small — ~50-200 rows expected; row-store is correct)

---

## § 3 — `General.dbo.UdmTablesColumnsList` canonical column inventory

**Authoritative source**: CLAUDE.md "Column Tracking" section + recent `schema/column_sync.py` metadata-column migration. Per-row purpose: one row per (`SourceName`, `TableName`, `Layer`, `ColumnName`) describing column-level metadata.

### § 3.1 Canonical column inventory (12 columns)

#### § 3.1.1 Base columns (9 — per CLAUDE.md "Column Tracking")

| # | Column | Type | NULL | Purpose |
|---|---|---|---|---|
| 1 | `SourceName` | `NVARCHAR(50)` | NO | Source-system short code (`DNA` / `CCM` / `EPICOR`); joins to `UdmTablesList.SourceName` |
| 2 | `TableName` | `NVARCHAR(128)` | NO | UDM table name (matches `SourceObjectName` OR custom `StageTableName` / `BronzeTableName`) |
| 3 | `ColumnName` | `NVARCHAR(128)` | NO | Column name in the UDM table |
| 4 | `OrdinalPosition` | `INT` | NO | Column position in the UDM table (1-indexed; matches `INFORMATION_SCHEMA.COLUMNS.ORDINAL_POSITION`) |
| 5 | `IsPrimaryKey` | `BIT` | NO | `1` if column is part of the PK; drives CDC + SCD2 comparison and dedup. Must be manually set for Oracle views without unique indexes per § 7 below |
| 6 | `Layer` | `NVARCHAR(20)` | NO | Medallion architecture layer — allowed: `'Stage'` / `'Bronze'` / `'Silver'` / `'Gold'`. CDC + SCD2 pipelines write rows for both `'Stage'` and `'Bronze'` per layer |
| 7 | `IsIndex` | `BIT` | NO | `1` if column should have an index in the UDM table |
| 8 | `IndexName` | `NVARCHAR(128)` | YES | Index name (when `IsIndex = 1`); convention: `IX_{TableName}_{ColumnName}` |
| 9 | `IndexType` | `NVARCHAR(50)` | YES | SQL Server index type when `IsIndex = 1` — e.g., `'NONCLUSTERED'`, `'CLUSTERED COLUMNSTORE'` |

#### § 3.1.2 Metadata additions (3 — per recent `column_sync.py` migration; see CLAUDE.md "Column Sync" section)

| # | Column | Type | NULL | Purpose |
|---|---|---|---|---|
| 10 | `ObjectType` | `NVARCHAR(20)` | YES | `'TABLE'` or `'VIEW'` from source system (`sys.objects` for SQL Server / `ALL_OBJECTS` for Oracle). Disambiguates PK discovery flow (table = PK constraint; view = unique-index fallback) |
| 11 | `DatabaseName` | `NVARCHAR(128)` | YES | Source database name (matches `UdmTablesList.SourceDatabase`); redundant but enables downstream queries that don't want to join to `UdmTablesList` |
| 12 | `MetadataLastUpdated` | `DATETIME2(3)` | YES | Server-side `SYSDATETIME()` at row insert/sync. Drives staleness detection when source schemas drift |

### § 3.2 Note on potential `SchemaName` column

User context (2026-05-11): a reviewer mentioned `SchemaName` as a column. **Current canonical sources (CLAUDE.md "Column Tracking" + `schema/column_sync.py` interface) do NOT list `SchemaName` as a column.** The schema role is played by `SourceName` (the source-system short code, which IS the schema in `UDM_Stage.*` and `UDM_Bronze.*` per CLAUDE.md "Table Naming Conventions"). The source-side schema (e.g., `osibank` for DNA) lives on `UdmTablesList.SourceSchemaName`, not on `UdmTablesColumnsList`.

If a `SchemaName` column exists in production but not in canonical docs, that is a documentation drift. **Action item** (proposed B-number at close-out): verify against production `INFORMATION_SCHEMA.COLUMNS` and either (a) reconcile docs to add `SchemaName` if it exists, or (b) confirm it doesn't and close the question. Tracked as 🟡 follow-up.

### § 3.3 Indexes on UdmTablesColumnsList

Per CLAUDE.md "Column Sync":
- Primary key: `(SourceName, TableName, Layer, ColumnName)` — composite; one row per layered column
- `(SourceName, TableName, Layer, IsPrimaryKey)` filtered on `IsPrimaryKey = 1` — fast PK lookup for CDC + SCD2 engines

---

## § 4 — How the two tables relate

### § 4.1 Join semantics

`UdmTablesList` is per-(`SourceName`, `SourceObjectName`); `UdmTablesColumnsList` is per-(`SourceName`, `TableName`, `Layer`, `ColumnName`). The join is on `SourceName` + `TableName` where `TableName` matches either `SourceObjectName` (default) or the custom `StageTableName` / `BronzeTableName` (when overridden).

```sql
-- "Give me all columns for a configured table"
SELECT
    tl.SourceName,
    tl.SourceObjectName,
    tl.SourceServer,
    tl.SourceSchemaName,
    cl.ColumnName,
    cl.OrdinalPosition,
    cl.IsPrimaryKey,
    cl.Layer,
    cl.IsIndex,
    cl.IndexName,
    cl.IndexType
FROM General.dbo.UdmTablesList tl
JOIN General.dbo.UdmTablesColumnsList cl
    ON cl.SourceName = tl.SourceName
   AND cl.TableName = COALESCE(tl.BronzeTableName, tl.SourceObjectName)  -- Bronze case
WHERE tl.IsEnabled = 1
  AND tl.StageLoadTool = 'Python'
  AND cl.Layer = 'Bronze'
ORDER BY cl.OrdinalPosition;
```

### § 4.2 Layer discriminator

`UdmTablesColumnsList` carries one row per layered column — so a single source table with the default naming (`StripSuffix=0`) has TWO sets of rows: one for `Layer='Stage'` (the CDC stage table) and one for `Layer='Bronze'` (the SCD2 bronze table). With `StripSuffix=1`, the names overlap (no suffix) but the rows are still distinct via the `Layer` column.

Stage and Bronze have different column sets:
- **Stage** = source columns + CDC framework columns (`_cdc_operation`, `_cdc_valid_from/to`, `_cdc_is_current`, `_cdc_batch_id`, `_row_hash`, `_extracted_at`) — see `phase1/01b_bronze_stage_example_ddl.md` for the exact DDL
- **Bronze** = source columns + SCD2 framework columns (`_scd2_key`, `UdmHash`, `UdmEffectiveDateTime`, `UdmEndDateTime`, `UdmActiveFlag`, `UdmScd2Operation`, `UdmSourceBeginDate`, `UdmSourceEndDate`)

`schema/column_sync.py` populates both Layer-row-sets at first sync.

---

## § 5 — Lifecycle: when rows get added, updated, deleted

### § 5.1 Adding a new table to the pipeline

```
[Operator action]                              [Pipeline action]
─────────────────────                          ─────────────────────
1. INSERT UdmTablesList row                    
   (SourceName, SourceObjectName, etc.)
   IsEnabled=1, StageLoadTool='Python'         
                                               
2. (Pipeline runs)                             3. TableConfigLoader reads UdmTablesList
                                                  WHERE IsEnabled=1 AND StageLoadTool='Python'
                                                  → finds new table
                                               
                                               4. schema/table_creator.py creates
                                                  UDM_Stage.{SourceName}.{table}_cdc
                                                  UDM_Bronze.{SourceName}.{table}_scd2_python
                                               
                                               5. schema/column_sync.py syncs
                                                  INFORMATION_SCHEMA.COLUMNS
                                                  → INSERT UdmTablesColumnsList rows
                                                    for both Layer='Stage' and Layer='Bronze'
                                               
                                               6. PK discovery (Oracle ALL_CONSTRAINTS /
                                                  SQL Server sys.indexes / view fallback)
                                                  → UPDATE UdmTablesColumnsList SET IsPrimaryKey=1
                                                    WHERE column is in PK
                                               
                                               7. Pipeline proceeds with first extraction
```

**Key point**: operator inserts ONE row in `UdmTablesList`. The pipeline auto-populates `UdmTablesColumnsList`, creates the Stage + Bronze tables, and discovers PKs on the FIRST run. This is the "optimistic behavior" per CLAUDE.md.

### § 5.2 Disabling a table

```sql
UPDATE General.dbo.UdmTablesList
SET IsEnabled = 0
WHERE SourceName = 'DNA' AND SourceObjectName = 'PROBLEMATIC_TABLE';
```

The next pipeline run skips this table. **Audit**: per CLAUDE.md, every `IsEnabled` flip should write a row to `General.ops.ManualCorrectionLog` recording the actor + reason. This is operator-discipline, not enforced at the database level (no trigger). 🟡 Follow-up: consider an UPDATE trigger on `UdmTablesList.IsEnabled` to enforce.

### § 5.3 Changing CDC mode (Phase 4 cutover per § 1.2.1)

Per Phase 4 cutover protocol in `02_PHASES.md`:

```sql
BEGIN TRANSACTION;
    -- Close the change-detect chapter for this table
    UPDATE UDM_Stage.{SourceName}.{table}_cdc
    SET _cdc_is_current = 0 WHERE _cdc_is_current = 1;
    
    -- Audit row
    INSERT General.ops.PipelineEventLog (EventType, SourceName, TableName, Metadata, ...)
    VALUES ('CDC_MODE_CUTOVER', @SourceName, @TableName, '{"from":"change_detect","to":"parquet_snapshot"}', ...);
    
    -- Flip the mode
    UPDATE General.dbo.UdmTablesList
    SET CDCMode = 'parquet_snapshot'
    WHERE SourceName = @SourceName AND SourceObjectName = @SourceObjectName;
COMMIT;
```

The next pipeline run reads `CDCMode='parquet_snapshot'` and uses the Parquet-snapshot flow.

### § 5.4 Removing a table from the pipeline

**Do not DELETE rows.** Set `IsEnabled = 0` (audit-preserving). Removing the `UdmTablesList` row would orphan the Stage + Bronze tables (which still exist on disk) without recording why. Per D34 + Pitfall #1, append-only mindset applies.

If a table must be permanently retired:
1. Set `IsEnabled = 0` + record reason in `ManualCorrectionLog`
2. Wait at least one retention cycle (per `ExpectedRetentionDays` or 90 days default) to ensure no in-flight queries depend on it
3. Operator-driven `DROP TABLE` on Stage + Bronze (separate runbook — currently 🟡 outside-scope; tracked as **B168**)
4. Then (and only then) `DELETE FROM UdmTablesList` + `DELETE FROM UdmTablesColumnsList`

---

## § 6 — Example rows (3 concrete examples)

### § 6.1 Small table — DNA.osibank.ACCT

**UdmTablesList row**:

```
SourceObjectName        = 'ACCT'
SourceServer            = 'oracle-dna-prod.example.com'
SourceDatabase          = 'DNA'
SourceSchemaName        = 'osibank'
SourceName              = 'DNA'
SourceAggregateColumnType = NULL                    -- small table; no windowing
SourceAggregateColumnName = NULL
FirstLoadDate           = NULL
LookbackDays            = NULL
SourceIndexHint         = NULL                       -- → ConnectorX bulk full scan
PartitionOn             = NULL
StageLoadTool           = 'Python'
StageTableName          = NULL                       -- default UDM_Stage.DNA.ACCT_cdc
BronzeTableName         = NULL                       -- default UDM_Bronze.DNA.ACCT_scd2_python
StripSuffix             = 0
MaxRowsPerDay           = NULL
SCD2Mode                = 'incremental'
SCD2DateColumns         = 'DATEOPENED,DATELASTMAINT'  -- per-row waterfall
SourceDeleteDateColumn  = NULL
DuplicateResolutionOrder = 'DATELASTMAINT,UdmEffectiveDateTime'
AllowDuplicates         = 0
PreserveDateTime        = 0
RepairChainAfter        = NULL
AllowGaps               = 0
ExcludeFromHash         = 'DATELASTMAINT'            -- per SCD2-R10.2; prevents phantom CDC updates
DefaultBeginDate        = NULL
ForceNewSegmentColumns  = NULL
ExpectedRetentionDays   = NULL                       -- no per-table override; uses default 7-year
LastModifiedColumn      = 'DATELASTMAINT'            -- Tier-2 modified-date sweep
CDCMode                 = 'change_detect'            -- pre-cutover
PiiColumnList           = 'TAXID,EMAIL,PHONE'        -- 3 PII columns
DataClassification      = 'PII'
CohortAssignment        = 'cohort-2-pilot'
IsEnabled               = 1
LegalHoldOnly           = 0
```

**UdmTablesColumnsList rows** (illustrative subset; ~30 source columns + framework columns × 2 layers):

```
SourceName  TableName  ColumnName        Ord  IsPK  Layer    IsIndex  IndexName              IndexType        ObjectType  DatabaseName
DNA         ACCT       ACCTNBR             1   1    Stage      1     IX_ACCT_ACCTNBR        NONCLUSTERED     TABLE       DNA
DNA         ACCT       ACCTNBR             1   1    Bronze     1     IX_ACCT_ACCTNBR        NONCLUSTERED     TABLE       DNA
DNA         ACCT       TAXID               5   0    Stage      0     NULL                   NULL             TABLE       DNA
DNA         ACCT       TAXID               5   0    Bronze     0     NULL                   NULL             TABLE       DNA
DNA         ACCT       DATEOPENED         12   0    Bronze     1     IX_ACCT_DATEOPENED     NONCLUSTERED     TABLE       DNA
DNA         ACCT       DATELASTMAINT      14   0    Bronze     0     NULL                   NULL             TABLE       DNA
...
DNA         ACCT       _cdc_operation     31   0    Stage      0     NULL                   NULL             TABLE       DNA
DNA         ACCT       _cdc_valid_from    32   0    Stage      1     IX_ACCT_cdc_window     NONCLUSTERED     TABLE       DNA
DNA         ACCT       _row_hash          36   0    Stage      0     NULL                   NULL             TABLE       DNA
DNA         ACCT       _scd2_key          31   0    Bronze     1     (clustered IDENTITY)   CLUSTERED        TABLE       DNA
DNA         ACCT       UdmHash            32   0    Bronze     0     NULL                   NULL             TABLE       DNA
DNA         ACCT       UdmActiveFlag      35   0    Bronze     1     UX_ACCT_active_PK      UNIQUE filtered  TABLE       DNA
```

Note: `_cdc_*` columns only on Stage rows; `Udm*` + `_scd2_key` columns only on Bronze rows.

### § 6.2 Large table — DNA.osibank.CARDTXN

**UdmTablesList row** (delta from ACCT):

```
SourceObjectName        = 'CARDTXN'
SourceAggregateColumnType = 'DATE'
SourceAggregateColumnName = 'TRANSACTIONDATE'     -- daily windowed extract
FirstLoadDate           = '2022-01-01'
LookbackDays            = 3                        -- 3-day rolling per P3-2 + V-7
SourceIndexHint         = 'INDEX(CARDTXN IX_TRANSACTIONDATE)'  -- oracledb path
StripSuffix             = 1                        -- per SS-1 opt-in (CARDTXN migrating off legacy)
MaxRowsPerDay           = 500000                   -- per P1-13; observed ~280k/day in 2024
DataClassification      = 'PCI'                    -- card transactions
PiiColumnList           = 'CARDNUMBER,CVV'
CohortAssignment        = 'cohort-4-large-pci'
```

Stage table is `UDM_Stage.DNA.CARDTXN` (no `_cdc` suffix per StripSuffix=1); Bronze is `UDM_Bronze.DNA.CARDTXN`.

### § 6.3 SQL Server transactional table — CCM.dbo.TransactionDetail

**UdmTablesList row**:

```
SourceObjectName        = 'TransactionDetail'
SourceServer            = 'sqlserver-ccm-prod.example.com'
SourceDatabase          = 'CCM'
SourceSchemaName        = 'dbo'
SourceName              = 'CCM'
SourceAggregateColumnType = 'DATETIME2'
SourceAggregateColumnName = 'TransactionTimestamp'
FirstLoadDate           = '2020-01-01'
LookbackDays            = 7                         -- CCM is slower-late than DNA
SourceIndexHint         = NULL                       -- SQL Server source; uses ConnectorX
PartitionOn             = NULL                       -- non-partitioned ConnectorX
StageLoadTool           = 'Python'
StageTableName          = NULL
BronzeTableName         = NULL
StripSuffix             = 0
MaxRowsPerDay           = NULL
SCD2Mode                = 'incremental'
SCD2DateColumns         = 'TransactionTimestamp'    -- single-column waterfall
LastModifiedColumn      = NULL                       -- CCM has no such column per LT-2
ExpectedRetentionDays   = 1080                       -- CCM 3-year retention per source-system purge policy
CDCMode                 = 'change_detect'
PiiColumnList           = NULL                       -- no PII columns in this table
DataClassification      = 'none'
CohortAssignment        = 'cohort-3-large'
IsEnabled               = 1
LegalHoldOnly           = 0
```

---

## § 7 — Primary-key discovery flow per source-system type

Per CLAUDE.md "Column Sync" section. `schema/column_sync.py` discovers PKs after Stage + Bronze tables are created.

### § 7.1 Oracle TABLE source

Query `ALL_CONSTRAINTS` + `ALL_CONS_COLUMNS`:

```sql
SELECT cc.COLUMN_NAME, cc.POSITION
FROM ALL_CONSTRAINTS c
JOIN ALL_CONS_COLUMNS cc
    ON cc.OWNER = c.OWNER AND cc.CONSTRAINT_NAME = c.CONSTRAINT_NAME
WHERE c.OWNER = :source_schema_name      -- e.g. 'osibank'
  AND c.TABLE_NAME = :source_object_name  -- e.g. 'ACCT'
  AND c.CONSTRAINT_TYPE = 'P'              -- primary key
ORDER BY cc.POSITION;
```

→ For each returned column: `UPDATE UdmTablesColumnsList SET IsPrimaryKey = 1` for matching (`SourceName`, `TableName`, `Layer`, `ColumnName`) rows in both layers.

### § 7.2 Oracle VIEW source (no PK constraint)

Fall back to `ALL_INDEXES` + `ALL_IND_COLUMNS` with `UNIQUENESS = 'UNIQUE'`:

```sql
SELECT ic.COLUMN_NAME, ic.COLUMN_POSITION
FROM ALL_INDEXES i
JOIN ALL_IND_COLUMNS ic
    ON ic.INDEX_OWNER = i.OWNER AND ic.INDEX_NAME = i.INDEX_NAME
WHERE i.TABLE_OWNER = :source_schema_name
  AND i.TABLE_NAME = :source_object_name
  AND i.UNIQUENESS = 'UNIQUE'
ORDER BY i.INDEX_NAME, ic.COLUMN_POSITION;
```

If multiple unique indexes exist, the first one (alphabetical by `INDEX_NAME`) wins; pipeline logs a WARNING.

### § 7.3 Oracle VIEW with NO unique index — dependency walk

Per CLAUDE.md "Column Sync" optimistic-behavior note: walk `ALL_DEPENDENCIES` to find underlying TABLE(s), look up their PK(s), and use the first table whose PK columns ALL appear in the view's column list. Multiple matching candidates → log a WARNING; one wins; operator can manually set `IsPrimaryKey = 1` if discovery picks wrong.

### § 7.4 SQL Server TABLE source

Query `sys.indexes` + `sys.index_columns`:

```sql
SELECT c.name AS column_name, ic.key_ordinal
FROM sys.indexes i
JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
JOIN sys.tables t ON t.object_id = i.object_id
JOIN sys.schemas s ON s.schema_id = t.schema_id
WHERE s.name = @source_schema_name
  AND t.name = @source_object_name
  AND i.is_primary_key = 1
ORDER BY ic.key_ordinal;
```

### § 7.5 SQL Server VIEW source

Same fall-back as Oracle: first unique index → dependency walk → manual override.

### § 7.6 Manual override (for views without unique indexes OR PK discovery failure)

```sql
UPDATE General.dbo.UdmTablesColumnsList
SET IsPrimaryKey = 1
WHERE SourceName = 'DNA'
  AND TableName = 'VIEW_NAME_HERE'
  AND ColumnName IN ('PK_COL_1', 'PK_COL_2');
```

CDC + SCD2 are SKIPPED for tables/views with no `IsPrimaryKey = 1` rows in `UdmTablesColumnsList` — the pipeline logs a WARNING but does not error. Operator must set manually before processing resumes.

---

## § 8 — Observability hooks (for dashboards + data-driven insights)

This section closes the user's stated goal: dashboards on the data pipeline process. The control tier feeds operational dashboards directly — these are the columns to query.

### § 8.1 "What runs today?" dashboard

```sql
SELECT
    tl.SourceName,
    tl.SourceObjectName,
    tl.SourceServer,
    tl.CDCMode,
    tl.DataClassification,
    tl.CohortAssignment,
    tl.MaxRowsPerDay,
    tl.LookbackDays,
    CASE
        WHEN tl.SourceAggregateColumnName IS NOT NULL THEN 'large-table windowed'
        WHEN tl.SourceIndexHint IS NOT NULL THEN 'oracledb hinted'
        WHEN tl.SourceServer LIKE 'oracle%' THEN 'oracle bulk'
        ELSE 'sqlserver bulk'
    END AS extraction_strategy
FROM General.dbo.UdmTablesList tl
WHERE tl.IsEnabled = 1
  AND tl.StageLoadTool = 'Python'
ORDER BY tl.SourceName, tl.SourceObjectName;
```

Operational use: "show me everything that runs this AM cycle". Power BI bar chart by `SourceName` + `extraction_strategy` reveals the pipeline composition.

### § 8.2 "Pipeline enablement progress" dashboard (Phase 4 rollout tracking)

```sql
SELECT
    CohortAssignment,
    COUNT(*) AS total_tables,
    SUM(CASE WHEN IsEnabled = 1 THEN 1 ELSE 0 END) AS enabled,
    SUM(CASE WHEN CDCMode = 'parquet_snapshot' THEN 1 ELSE 0 END) AS cutover_complete,
    SUM(CASE WHEN DataClassification IS NULL THEN 1 ELSE 0 END) AS unclassified
FROM General.dbo.UdmTablesList
WHERE StageLoadTool = 'Python'
GROUP BY CohortAssignment
ORDER BY CohortAssignment;
```

Operational use: "how many tables in cohort-2 still need PII classification?" Power BI funnel chart per cohort.

### § 8.3 "PII surface area" dashboard

```sql
SELECT
    SourceName,
    COUNT(*) AS tables_with_pii,
    SUM(LEN(PiiColumnList) - LEN(REPLACE(PiiColumnList, ',', '')) + 1) AS approx_pii_column_count
FROM General.dbo.UdmTablesList
WHERE PiiColumnList IS NOT NULL
  AND IsEnabled = 1
GROUP BY SourceName;
```

Operational use: compliance reporting — "how many PII columns are under tokenization per source?". Drives quarterly compliance reviews.

### § 8.4 "Retention class distribution" dashboard

```sql
SELECT
    DataClassification,
    COUNT(*) AS table_count,
    SUM(CASE WHEN LegalHoldOnly = 1 THEN 1 ELSE 0 END) AS under_legal_hold,
    AVG(CAST(ExpectedRetentionDays AS FLOAT)) AS avg_retention_days
FROM General.dbo.UdmTablesList
WHERE IsEnabled = 1 AND StageLoadTool = 'Python'
GROUP BY DataClassification;
```

Operational use: "what's our retention exposure by classification?". Feeds quarterly retention enforcement runs (RB-11).

### § 8.5 "Index health" dashboard

Cross-join `UdmTablesColumnsList` with `INFORMATION_SCHEMA.STATISTICS` (or `sys.indexes`) to find configured-vs-actual index drift:

```sql
SELECT
    cl.SourceName,
    cl.TableName,
    cl.Layer,
    cl.ColumnName,
    cl.IndexName AS configured_index,
    cl.IndexType AS configured_type,
    -- Then JOIN to sys.indexes filtered to UDM_Stage.* and UDM_Bronze.* for actual
    CASE WHEN cl.IsIndex = 1 THEN 'should-exist' ELSE 'should-not-exist' END AS expected
FROM General.dbo.UdmTablesColumnsList cl
WHERE cl.IsIndex = 1
ORDER BY cl.SourceName, cl.TableName, cl.Layer, cl.IndexName;
```

Operational use: surface index-config drift (configured but missing; existing but unconfigured). Drives index rebuild planning.

### § 8.6 "Per-table SCD2 configuration" dashboard

```sql
SELECT
    SourceName,
    SourceObjectName,
    SCD2Mode,
    SCD2DateColumns,
    DuplicateResolutionOrder,
    ExcludeFromHash,
    ExpectedRetentionDays
FROM General.dbo.UdmTablesList
WHERE IsEnabled = 1
  AND SCD2DateColumns IS NOT NULL
ORDER BY SourceName, SourceObjectName;
```

Operational use: "which tables use per-row SCD2 waterfall? Are the date columns configured correctly?". Drives Round 7 R-2 SCD2 config audits.

### § 8.7 Cross-control-tier joins to operational metadata (the real value layer)

Joining control tier (`General.dbo.*`) to operational metadata (`General.ops.*`) is where data-driven insights live. Example: "show me the slowest tables in the cohort-3 rollout":

```sql
SELECT
    tl.SourceName,
    tl.SourceObjectName,
    tl.CohortAssignment,
    AVG(el.DurationMs) / 1000.0 AS avg_seconds,
    MAX(el.DurationMs) / 1000.0 AS max_seconds,
    COUNT(*) AS run_count
FROM General.dbo.UdmTablesList tl
JOIN General.ops.PipelineEventLog el
    ON el.SourceName = tl.SourceName
   AND el.TableName = tl.SourceObjectName
WHERE tl.CohortAssignment = 'cohort-3-large'
  AND el.EventType = 'TABLE_TOTAL'
  AND el.Status = 'SUCCESS'
  AND el.StartedAt > DATEADD(DAY, -7, SYSDATETIME())
GROUP BY tl.SourceName, tl.SourceObjectName, tl.CohortAssignment
ORDER BY avg_seconds DESC;
```

Output: "cohort-3 has 8 tables averaging 4-12 minutes per AM cycle; CARDTXN is the slowest at 12 min p99". This is the dashboard that drives Phase 6 health monitoring.

---

## § 9 — Edge case mapping (M / S / I / F / V series walk)

| Series | Concern | Mitigation (control tier) |
|---|---|---|
| **M** | UdmTablesList row count exceeds index capacity | Filtered index on `(IsEnabled, StageLoadTool)` — small workload; not a real concern at ~50-200 rows |
| **S** | Source schema drift breaks UdmTablesColumnsList | `schema/column_sync.py` re-syncs on each run; logs WARNING on missing column (per E-11) |
| **I3-variant** | Two concurrent operator UPDATEs to same UdmTablesList row | Per row-level locking + last-writer-wins; audit via ManualCorrectionLog — 🟡 explicit advisory lock not currently enforced (tracked as **B169**) |
| **F-series** | Pipeline reads UdmTablesList during config-row delete (race) | Operator discipline: never DELETE; only set `IsEnabled = 0` |
| **V-series** | UdmTablesColumnsList contains stale rows after source schema change | `column_sync.py` adds new columns; logs WARNING on removed; `MetadataLastUpdated` enables staleness queries |
| **SI-series** | None (control tier is not part of self-improvement loop) | n/a |
| **DP-series** | Migration that adds UdmTablesList column → cascade to UdmTablesColumnsList? | NO — UdmTablesList columns are per-table config; UdmTablesColumnsList columns are per-column metadata. Independent migration paths. |

🟡 Follow-up: confirm M-series formal applicability with edge-case-validator skill at validation.

---

## § 10 — Validation gates self-check

### 10.1 Gate 1 — Cross-reference

| Check | Pass criterion | Verdict |
|---|---|---|
| Canonical UdmTablesList inventory matches Round 2 § 1.1+1.2 | All 35 columns + types + nullability + defaults verified | ✅ Walked |
| UdmTablesColumnsList inventory matches CLAUDE.md "Column Tracking" + column_sync metadata additions | 12 columns confirmed | ✅ Walked |
| Round 7 SCD2 column additions (R-2) reflected in § 2.4 | 12 SCD2 columns enumerated | ✅ Walked |
| D63 6 new columns reflected in § 2.5 | All 6 + types + defaults + drivers verified | ✅ Walked |
| Naming conventions match CLAUDE.md "Table Naming Conventions" | `UDM_Stage.{SourceName}.{table}_cdc` / `UDM_Bronze.{SourceName}.{table}_scd2_python` + StripSuffix variant | ✅ Walked |
| Cross-doc refs (Round 2 § 1, CLAUDE.md, Round 7, 02_PHASES.md Phase 4) | All cited correctly | ✅ Walked (verify at Gate 2) |

### 10.2 Gate 2 — Quality assurance (independent review)

Pattern E from cycle 1 per D97 Tier β (50-100 KB target; this doc ~30 KB so borderline Tier α/β — operating at Tier β for the supplement-cluster total ~70 KB).

### 10.3 Gate 3 — Edge case enumeration

§ 9 walks M/S/I/F/V series. SI-series N/A (control tier not part of self-improvement). DP-series clarified (independent migration paths).

### 10.4 Gate 4 — Edge case validation

Each ✅ case in § 9 cites the mitigation source (E-11 / column_sync.py / ManualCorrectionLog / etc.).

### 10.5 Gate 5 — Idempotency / regression

| Check | Verdict |
|---|---|
| D15 invariant preserved | ✅ Control-tier reads are idempotent (no side effects) |
| D34 greenfield posture preserved | ✅ All ALTER DDL in Round 2 § 1.3 uses `IF NOT EXISTS` guards |
| D40 / D92 forward-only discipline | ✅ Round 1.5a is supplement; no locked-artifact edits |
| Round 1 schema doc unchanged | ✅ This is sibling supplement at `phase1/01a_*.md` not `phase1/01_*.md` |
| Round 2 § 1 referenced as authoritative | ✅ § 2 explicitly says "Round 2 wins" on any contradiction |

### 10.6 Pillar contribution (per D61)

| Pillar | Round 1.5a contribution |
|---|---|
| Audit-grade | Lifecycle § 5 explicit on append-only operator discipline (IsEnabled toggle vs DELETE); ManualCorrectionLog audit |
| Traceability | § 8 observability hooks expose control-tier state for dashboards |
| Idempotent | Pipeline auto-populates UdmTablesColumnsList on first run (operator INSERTs only UdmTablesList row) |
| Operationally stable | § 5 lifecycle + § 7 PK discovery flow give operators a clear mental model |
| $120K/year ceiling | n/a (no Snowflake-cost implications) |

### 10.7 Risk delta (per D61 + Pitfall #8)

🟡 PROPOSED-NEW: nothing net-new — this is a documentation supplement. Existing R06 (source schema changes during build) is partially mitigated by § 5 + § 7 + S-series treatment in § 9.

### 10.8 Backlog surfacing (per D61)

Net-new 🟡 follow-ups proposed:
- **B166**: Verify `SchemaName` column existence in production `UdmTablesColumnsList` per § 3.2 note — reconcile or close
- **B167**: UPDATE trigger on `UdmTablesList.IsEnabled` to enforce ManualCorrectionLog audit (currently operator-discipline only)
- **B168**: Permanent-retire runbook for UdmTablesList row + Stage/Bronze table drop (currently undefined operational gap per § 5.4)
- **B169**: Advisory lock on `UdmTablesList` row UPDATEs to enforce serialization (currently row-level lock + last-writer-wins; concurrent operator UPDATEs can race — surfaced by I3-variant edge case in § 9)

---

## § 11 — Cycle log (Round 1.5 D72 campaign — populated post-acceptance)

| Cycle | Type | 🔴 | 🟡 | Outcome |
|---|---|---|---|---|
| R1.5C1 | Pattern E 5-agent (column-walk + cross-reference + internal-consistency + D72-edge + advisory-research) | 11 (7 column-walk + 0 cross-ref + 2 internal-consistency + 2 D72-edge + 0 advisory) | ~11 + 4 advisory framing | Not clean; cycle 2 fix-cycle required |
| R1.5C2 | Fix-application | — | — | 11 cycle-1 🔴 addressed (SP-10 name × 12; @CategoryFilter type-width; SP-4 baseline; OrphanedTokenLog + CcpaDeletionLog ER blocks; PipelineExecutionGate + IdempotencyLedger Status enums; filename/round-label; B-future → B166-B172) |
| R1.5C3 | Comprehensive-5-gate verify | 3 (7th-event Pitfall #9.i fix-fresh-instance: Cluster C audit-history off-by-one + Gate-1 self-check stale + dashboard query enum surviving) | 0 | Not clean; cycle 4 fix-cycle required |
| R1.5C4 | Fix-application | — | — | 3 cycle-3 🔴 addressed |
| R1.5C5 | Sleeper-bug stress test (6-event 100% catch rate extended) | 8 (largest single sleeper-bug catch in project history — SP-8 Status='SUCCESS' + PiiVault.PiiCategory invented × 3 sites + @CategoryFilter Gate-1 contradiction + SP-4 audit-history + PiiTokenizationBatch × 3 sites + token VARCHAR(40) + B-4 marker drift + 09_VISUALS ER comprehensive drift across 9 tables) | 4 (SP-9 param name + B167 trigger scope + B172 target + D100 supplement-Pattern-F) | Not clean; 9-table ER drift scope-exhausting per D72 ceiling |
| R1.5C6 | Fix-application | — | — | Highest-impact items addressed; 9-table ER comprehensive sweep deferred to B173 |
| R1.5-PF-INST1+INST2 | Pattern F Layer 2 paired (3rd-production per D89) | 1 🔴 (D93 violation — 02_PHASES + PHASE_1_DEEP_DIVE_PLAN + 00_OVERVIEW missing Round 1.5 references) + 2 🟡 (Trigger J candidate per X2; 5th math-infeasibility sub-variant per X3) | 2 | D93 violation fixed; X2 + X3 tracked as B176 + B177 |

**Round 1.5 D72 campaign summary**: 6 review cycles + 1 Pattern F event = effective 7-event campaign. **23 cumulative 🔴 caught + fixed**. Trajectory 11→3→8 (note: C5 UPward step due to scope-exhausting 9-table ER drift — D101 math-infeasibility variant acceptance per D73/D78/D94 precedent; 4th math-infeasibility precedent distinct from D83/D88/D99 convergence-confirmed).

(Full per-cycle detail in `_validation_log.md` 2026-05-11 Round 1.5 entry.)

---

## Owner

Pipeline lead. Round 1.5a is a documentation supplement; canonical authority remains with Round 2 § 1 (UdmTablesList) + CLAUDE.md "Column Tracking" (UdmTablesColumnsList).

## Last updated

2026-05-11 (Round 1.5a authored; pending Pattern E validation + Pattern F close-out)
