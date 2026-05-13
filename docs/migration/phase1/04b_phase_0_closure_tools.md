# Round 4.5b — Phase 0 Closure Tools Supplement

**Status**: 🟡 Draft (authored 2026-05-12 at Phase 0 user-sign-off batch closure to close residuals on deliv 0.2 / 0.3 / 0.5 + 0.17). Per **D100** Round-N.5 documentation supplement discipline + **D92** forward-only schema-evolution governance — this is the second additive supplement to locked `phase1/04_tools.md`. Pre-D78 Tools 1-11 grandfathered; Round 4.5 added Tools 12-13 (B183/B184); this supplement adds Tools 14-16 (B188-B190 implementation tracking).

## § 1. Purpose + scope

Three operator tools needed to close Phase 0 deliverables 0.2 / 0.3 / 0.5 + 0.17 per user-sign-off batch 2026-05-12:

- **Tool 14 — `tools/measure_lateness.py`** (B188; closes deliv 0.2 partial): periodic query against source DBs + target Bronze to measure per-table lateness (L_99 per D11) and update a new tracked column on `General.dbo.UdmTablesList`.
- **Tool 15 — `tools/import_pii_inventory.py`** (B189; closes deliv 0.3 partial residual to B185): CSV-driven import to populate `UdmTablesList.PiiColumnList` + `DataClassification` per source. Operator generates CSV (programmatically OR by hand) → tool ingests + writes.
- **Tool 16 — `tools/measure_capacity_and_partition.py`** (B190; closes deliv 0.17 partial + deliv 0.5 advisory side): per-table row count + growth rate + 12-month + 7-year storage projection + partition-optimization recommendation for primary network drive (per D2/D4) and offsite paths (per D107). Drives Phase 5 capacity-cost projections per D42.

All three tools follow Round 4 conventions: **D74** exit-code contract, **D75** argument naming, **D76** audit-row contract (`CLI_<TOOL_NAME>`), **D77** Tier 0 scaffold pattern, **D67 + D70** test pyramid.

### Boundaries

- Does NOT modify locked Round 4 tools (§ 3.1-§ 3.11) or Round 4.5 tools (§ 3-§ 4 of supplement 4a). Forward-only additive per D92.
- Does NOT introduce new D-numbers — consumes existing D11 / D14 / D27 / D42 / D44 / D63 / D67 / D74-D77 / D92 / D100 / D103 / D106 / D107 / D108.
- Implementation lands at Phase 2 R1 per the Phase 2 plan-draft `phase2/00_phase_overview.md`; THIS supplement is the spec, not the code.

### New `UdmTablesList` columns required (per D63 forward-only additive)

Two NEW columns on `General.dbo.UdmTablesList` per D92 additive ALTER pattern:

| Column | Type | Nullable | Purpose | Set by |
|---|---|---|---|---|
| `LatenessL99Minutes` | INT | YES | Per-table empirical 99th-percentile lateness in minutes from source `SourceAggregateColumnName` to Bronze `UdmEffectiveDateTime` per D11. Recomputed by Tool 14 at each invocation; NULL = unmeasured. | Tool 14 (`measure_lateness.py`) |
| `LatenessL99UpdatedAt` | DATETIME2(3) | YES | Timestamp of last L99 measurement. NULL = unmeasured. | Tool 14 |

Both columns are forward-only additive per D92; idempotent `ALTER TABLE ... ADD ... IF NOT EXISTS`-guarded DDL ships in a migration script (B188 implementation deliverable). No supersession of locked Round 1 / Round 2 schema; ALTER pattern is the canonical D40 + D63 + D92 mechanism.

## § 2. Read order

For an engineer or AI agent picking this up cold:
1. `phase1/04_tools.md` § 1 (cross-cutting CLI conventions)
2. `phase1/04a_phase_0_prep_tools.md` (sibling Round 4.5 supplement — Tools 12-13)
3. `phase1/02_configuration.md` § 1 (`UdmTablesList` canonical column inventory — Tools 14-16 update or query)
4. `03_DECISIONS.md` D11 + D14 + D42 + D44 + D63 + D74-D77 + D106 + D107 + D108 (decisions this supplement operationalizes)
5. This document (§ 3 + § 4 + § 5)

## § 3. Tool 14 — `tools/measure_lateness.py`

**Purpose**: Periodic query against source DB (DNA / CCM / EPICOR per source row in `UdmTablesList`) + target Bronze tables to compute per-table empirical 99th-percentile lateness (L_99 per D11). Updates `UdmTablesList.LatenessL99Minutes` + `LatenessL99UpdatedAt`. Closes Phase 0 deliv 0.2 partial-closure; first invocation establishes initial baseline; subsequent invocations track drift.

**Wraps**: NEW module function `data_load/lateness_measurement.py::measure_lateness(table_config) -> LatenessResult` (per D92 forward-only additive — new module, no rename of locked R3 modules). Function: (a) reads `table_config.source_aggregate_column_name`, (b) queries source DB for distribution of (source-row-`SourceAggregateColumnName` → server `SYSUTCDATETIME()`) deltas over the last `lookback_days` (default 30), (c) computes 99th percentile, (d) returns dataclass with `l99_minutes: int | None`, `sample_count: int`, `measured_at: datetime`, `notes: str`.

**Consumes**: D11 (empirical L_99 per-table); D14 (`IsReExtraction`); D63 (UdmTablesList canonical column inventory + ADD pattern); D67; D74-D77; D106 (operational schedule — Tool 14 invoked DAILY between AM + PM cycles via Automic OR weekly per ops choice).

**Produces**:
- **Output**: UPDATE `UdmTablesList` SET `LatenessL99Minutes` = <int> + `LatenessL99UpdatedAt` = SYSUTCDATETIME() per row processed
- **stdout** (success): summary table of (SourceName / TableName / prior L99 / new L99 / Δ); final line `Lateness measured for N tables; M tables drifted >20% from prior baseline`
- **stdout** (`--json`): list of `LatenessResult` dataclass serialized
- **PipelineEventLog**: ONE row per table with `EventType='CLI_MEASURE_LATENESS'`, `Status` ∈ {SUCCESS, FAILED}, `Metadata` JSON containing `source_name`, `table_name`, `l99_minutes`, `sample_count`, `prior_l99_minutes`, `drift_pct`

**Invocation patterns**:
- **Automic** (primary): a new Automic job `JOB_LATENESS_MEASURE` (one of two additions in this supplement that extend frozen-11 → frozen-13 per § 6 below; the OTHER addition is Tool 16's `JOB_CAPACITY_BASELINE`) runs the tool against all `IsEnabled=1` rows once weekly
- **Operator ad-hoc** (occasional): per-table on-demand measurement: `python3 tools/measure_lateness.py --source DNA --table ACCT`
- **Pipeline**: NEVER — Tool 14 is a measurement tool, not a pipeline step

**Idempotency** (per D15): read-only on source + Bronze; UPDATE-only on `UdmTablesList`. Re-invocation produces a NEW L99 measurement reflecting the latest distribution; this is intentional drift-tracking, not idempotent identity. INSERT-only on `PipelineEventLog`.

**Error modes** (per D68):
- `SourceConnectError` (per ConnectorX / oracledb / pyodbc error class) → exit 1 retryable
- `BronzeTableMissing` (table in `UdmTablesList` but no Bronze table exists yet — pre-deploy state) → exit 1; UPDATE writes `LatenessL99Minutes=NULL` + notes "Bronze not deployed yet"
- `InsufficientSampleError` (< 100 rows in the lookback window — distribution unreliable) → exit 1 (warning); UPDATE writes the L99 anyway with notes "low sample count: N"
- `MeasurementOK` (default success) → exit 0
- `UdmTablesListNotWritable` (permissions / lock issue) → exit 2

**CLI interface**:
```bash
# Automic weekly invocation against all enabled tables
sudo -u pipeline /opt/pipeline/current/tools/measure_lateness.py --all --actor automic

# Operator ad-hoc for one table
sudo -u pipeline /opt/pipeline/current/tools/measure_lateness.py --source DNA --table ACCT
```

**Tool-specific arguments** (in addition to D75 canonical `--actor`, `--json`, `--verbose`, `--quiet`):

| Argument | Type | Default | Semantics |
|---|---|---|---|
| `--all` | flag | False | Run against every `UdmTablesList` row with `IsEnabled=1` (mutex with `--source`/`--table`) |
| `--source` | str | None | Restrict to one source (DNA / CCM / EPICOR) |
| `--table` | str | None | Restrict to one table (must be paired with `--source`) |
| `--lookback-days` | int | 30 | Lookback window for the L99 distribution computation |
| `--drift-threshold-pct` | float | 20.0 | Δ percentage above which a table is flagged in stdout summary as "drifted" |
| `--dry-run` | flag | False | Measure but do NOT UPDATE `UdmTablesList`; write audit row only |

**Exit codes** (per D74): 0 = all measurements succeeded; 1 = some tables warning (insufficient sample / Bronze missing); 2 = fatal (source connection failed entirely, UdmTablesList not writable).

**Tier 0 smoke test** (per D77; 6 canonical assertions):
1. (import) module imports without error
2. (help) `--help` exits 0
3. (success) mocked source + Bronze cursors returning a synthetic distribution → exit 0; UPDATE called once per mocked row; one `CLI_MEASURE_LATENESS` event row per mocked table with Status=SUCCESS
4. (warning insufficient sample) mocked source returning < 100 rows → exit 1; UPDATE still called with `notes` populated
5. (fatal source-connect) mocked `cx_read_sql_safe` raising `ConnectionError` → exit 2; UPDATE not called; event Status=FAILED
6. (`--dry-run`) `--dry-run` → exit 0; UPDATE NOT called; event Metadata `dry_run=true`

**Cross-doc references**: D11 + D14 + D27 + D63 + D74-D77 + D106 (Automic invocation timing); Phase 0 deliv 0.2 closure (this tool closes the partial residual); B188 (implementation tracking).

## § 4. Tool 15 — `tools/import_pii_inventory.py`

**Purpose**: Read a CSV file containing per-source PII column declarations + data classifications, validate, and UPDATE `UdmTablesList.PiiColumnList` + `DataClassification` per row per D63. Closes Phase 0 deliv 0.3 partial residual (B185 data-side). CSV is generated programmatically by ops OR hand-authored by compliance review; tool ingests + writes.

**Wraps**: NEW module function `data_load/pii_inventory_importer.py::import_pii_inventory(csv_path) -> ImportResult` (D92 additive). Function: (a) reads CSV with canonical schema, (b) validates each row against `UdmTablesList` (source + table must exist; rejects unknown), (c) validates `DataClassification` against canonical enum, (d) returns dataclass with `rows_imported: int`, `rows_skipped: int`, `errors: list[str]`.

**CSV canonical schema** (frozen at first implementation; per D92 additive — new optional columns may be ADDed but existing columns NOT renamed/removed):

```csv
SourceName,TableName,PiiColumnList,DataClassification,Rationale,ReviewedBy,ReviewedAt
DNA,ACCT,"ACCT_NUMBER,SSN,CUST_EMAIL",PII,Customer PII per compliance review 2026-XX-XX,compliance-lead,2026-05-12
DNA,CARDTXN,"CARD_NUMBER,CUST_EMAIL,POSTAL_CODE",PCI,Payment card data per PCI-DSS scoping,compliance-lead,2026-05-12
CCM,...,...,...,...,...,...
```

`DataClassification` enum: `PII` | `PCI` | `GLBA` | `SOX` | `INTERNAL` | `PUBLIC` | `NONE` (matches D63 canonical inventory).

`PiiColumnList` is a comma-separated list of column names within the source table that contain protected data; gets tokenized at extraction per the pipeline's D6 vault tokenization flow.

**Consumes**: D6 (vault) + D26 (audit trail) + D30 (retention) + D63 (UdmTablesList canonical) + D74-D77 + D92 + D102 (AES-256-GCM encryption for tokenized PII).

**Produces**:
- **Output**: UPDATE `UdmTablesList` SET `PiiColumnList` = <value> + `DataClassification` = <value> per CSV row
- **stdout** (success): summary table; final line `Imported N rows; M skipped (validation errors)`
- **stdout** (`--json`): `ImportResult` dataclass + per-row outcomes
- **PipelineEventLog**: ONE row per invocation with `EventType='CLI_IMPORT_PII_INVENTORY'`, Metadata containing `csv_path`, `rows_imported`, `rows_skipped`, `actor`, `reviewer` (if `ReviewedBy` column populated in CSV)
- **`General.ops.PiiInventoryAuditLog`** (NEW append-only table per D26 + D92 additive — schema in B189 implementation): one row per CSV row applied with `BatchId`, `ImportedAt`, `Source`, `Table`, `PiiColumnList`, `DataClassification`, `Rationale`, `ReviewedBy`, `ReviewedAt`, `Actor`

**Invocation patterns**:
- **Operator** (primary): `python3 tools/import_pii_inventory.py --csv-path /tmp/pii_inventory_2026-05-12.csv --actor compliance-lead`
- **Automic**: NEVER (governance-driven; never scheduled)
- **Pipeline**: NEVER

**Idempotency** (per D15 + D26): re-running with the same CSV produces no `UdmTablesList` writes IF row values unchanged (hash compare); writes occur only on actual change. `PiiInventoryAuditLog` is append-only — multi-invocation produces multiple audit rows (intentional audit trail).

**Error modes**: `CsvParseError` → exit 2; `UnknownSourceTableError` (CSV row references non-existent UdmTablesList row) → exit 1 skip + warning; `InvalidDataClassificationError` → exit 2; `UdmTablesListNotWritable` → exit 2.

**CLI interface**:
```bash
# Compliance lead imports new PII inventory
sudo -u pipeline /opt/pipeline/current/tools/import_pii_inventory.py \
    --csv-path /var/pipeline/pii_inventory_2026-05-12.csv \
    --actor compliance-lead --reviewer compliance-lead

# Dry-run preview without writing
sudo -u pipeline /opt/pipeline/current/tools/import_pii_inventory.py \
    --csv-path /var/pipeline/pii_inventory_2026-05-12.csv --dry-run
```

**Tool-specific arguments** (in addition to D75 canonical):

| Argument | Type | Default | Semantics |
|---|---|---|---|
| `--csv-path` | path | required | Input CSV per canonical schema |
| `--reviewer` | str | None | Records `ReviewedBy` for audit row if CSV doesn't supply it |
| `--dry-run` | flag | False | Validate but do NOT write |
| `--allow-unknown` | flag | False | Treat unknown SourceName/TableName as warning instead of error |

**Exit codes**: 0 success; 1 some rows skipped; 2 fatal (parse error, unknown classification, not writable).

**Tier 0 smoke test** (6 assertions): import, help, success-with-valid-CSV, error-invalid-classification (exit 2), warning-unknown-source-table (exit 1), dry-run (no UPDATE).

**Cross-doc references**: D6 + D26 + D30 + D63 + D74-D77 + D92 + D102; Phase 0 deliv 0.3 closure; B185 data-side closure via this tool; B189 implementation tracking.

## § 5. Tool 16 — `tools/measure_capacity_and_partition.py`

**Purpose**: Per-table row count + growth rate measurement (last 12 months) + 12-month + 7-year storage projection + partition-optimization recommendation for primary network drive (D2/D4) and offsite paths (D107 H drive + VendorFile). Closes Phase 0 deliv 0.17 partial residual (capacity baseline) + provides advisory data for deliv 0.5 (partition optimization). Drives Phase 5 Snowflake capacity-cost projections per D42.

**Wraps**: NEW module function `data_load/capacity_baseline.py::measure_capacity_and_partition(table_config) -> CapacityResult` (D92 additive). Function: (a) queries source DB for current row count + growth rate, (b) computes 12-month + 7-year projections per D42, (c) queries Parquet directory for current partition layout + file-size distribution per D45.2 (100-250MB target), (d) recommends partition optimization (e.g., "current daily partition produces 5MB files — consider monthly partition" or "current daily partition produces 800MB files — consider hourly sub-partition"), (e) returns dataclass.

**Consumes**: D2 + D4 + D27 + D42 + D44 + D45.2 + D63 + D67 + D74-D77 + D92 + D107 (dual offsite paths for which optimization recommendation applies).

**CapacityResult dataclass** (new in B190 implementation; per D92 additive):
```python
@dataclass(frozen=True)
class CapacityResult:
    source_name: str
    table_name: str
    current_row_count: int
    current_storage_mb: int
    growth_rate_rows_per_month: int  # rolling 12-month average
    projected_rows_12_months: int
    projected_rows_7_years: int
    projected_storage_mb_12_months: int
    projected_storage_mb_7_years: int
    current_partition_layout: str  # canonical from D2/D4 path
    avg_partition_file_size_mb: float
    partition_recommendation: str  # human-readable narrative
    measured_at: datetime
```

**Produces**:
- **Output**: `General.ops.CapacityBaselineLog` (NEW append-only table per D26 + D92 additive — schema in B190 implementation): one row per (table, measurement_date)
- **stdout** (success): summary table; final line `Capacity baseline for N tables; M tables flagged for partition optimization`
- **stdout** (`--json`): list of `CapacityResult` serialized
- **stdout** (`--report`): rendered markdown report per table with growth chart + projection table + partition recommendation
- **PipelineEventLog**: ONE row per invocation with `EventType='CLI_MEASURE_CAPACITY_AND_PARTITION'`, Metadata containing tables measured, projection totals

**Invocation patterns**:
- **Automic** (primary): monthly job `JOB_CAPACITY_BASELINE` (one of two additions in this supplement that extend frozen-11 → frozen-13 per § 6; the OTHER addition is Tool 14's `JOB_LATENESS_MEASURE`) runs against all `IsEnabled=1` rows
- **Operator ad-hoc**: per-table on demand
- **Pipeline**: NEVER

**Idempotency** (per D15 + D26): read-only on source + Parquet; append-only on `CapacityBaselineLog`. Re-running produces new baseline row (intentional historical trail).

**Error modes**: `SourceConnectError` → exit 1; `ParquetDirectoryUnreachable` (network drive not mounted) → exit 1 with `current_partition_layout=NULL`; `MeasurementOK` → exit 0; `LogTableNotWritable` → exit 2.

**CLI interface**:
```bash
# Monthly Automic invocation
sudo -u pipeline /opt/pipeline/current/tools/measure_capacity_and_partition.py --all --actor automic

# Per-table ad-hoc with markdown report
sudo -u pipeline /opt/pipeline/current/tools/measure_capacity_and_partition.py \
    --source DNA --table ACCT --report > /tmp/ACCT_capacity.md
```

**Tool-specific arguments** (in addition to D75 canonical):

| Argument | Type | Default | Semantics |
|---|---|---|---|
| `--all` | flag | False | Run against all enabled tables |
| `--source` + `--table` | str | None | Restrict to one table |
| `--report` | flag | False | Emit markdown report to stdout |
| `--projection-years` | int | 7 | Future projection window (per D30 retention) |
| `--include-offsite` | flag | True | Include H drive + VendorFile (per D107) in storage projections |
| `--partition-recommendation-only` | flag | False | Skip growth projection; only output partition advisory (faster, for deliv 0.5 work) |

**Exit codes**: 0 success; 1 some tables warning; 2 fatal.

**Tier 0 smoke test** (6 assertions): import, help, success, warning-parquet-unreachable, fatal-log-not-writable, `--report` mode produces valid markdown.

**Cross-doc references**: D2 + D4 + D27 + D42 + D44 + D45.2 + D63 + D74-D77 + D92 + D107; Phase 0 deliv 0.17 closure + 0.5 advisory; B190 implementation tracking; Phase 5 Snowflake cost projections.

## § 6. Cross-tool considerations + Automic schedule additions

Tools 14 + 16 add two new Automic jobs to the frozen-11 inventory (per D66 + Round 7 § 6.2). Per D92 forward-only, this is additive — the frozen-11 becomes **frozen-13** with the additions:

- `JOB_LATENESS_MEASURE` — weekly (Sat 06:00 per operator preference; doesn't conflict with `JOB_PIPELINE_AM` 02:00 weekdays per D106 *(D106 ⚫ Superseded by D109 same-session 2026-05-12; D109 confirms 02:00 Prod + 06:00 Test AM weekdays — Sat 06:00 still safe vs Prod AM but now overlaps Test AM weekdays; weekly Sat-only schedule still avoids the conflict since weekdays = Mon-Fri. P-1 polish-queue item tracks D109 supersession crumb refresh at Phase 2 R1)*)
- `JOB_CAPACITY_BASELINE` — monthly (1st of month 04:00, between AM and PM cycles per D106 *(D106 ⚫ Superseded by D109; 04:00 monthly remains between Prod AM 02:00 and Test AM 06:00 — 1-of-month-only frequency makes weekday-coincidence rare; same P-1 polish item applies)*)

Tool 15 (`import_pii_inventory.py`) is operator-driven only — no Automic schedule.

Frozen-13 inventory addition tracked in B188 + B190 implementation deliverables; aggregate-doc cascade to follow at next round close-out (currently the change is documented HERE in Round 4.5b supplement, not in Round 2 § 5.1 + Round 7 § 6.2 per D92 forward-only no-in-place-edit rule).

## § 7. Validation gates + cross-references

Subject to D55 5-gate discipline + D56 mandatory-second-pass + D62 CCL + Pattern F at close-out. Validation log entry follows at completion.

**Edge cases addressed**: F22 (parity drift) — Tool 16 partition recommendations respect per-environment parity; P5 (no plaintext PII in logs) — Tool 15 only LOGS column NAMES + classifications, never sample data.

**Cross-references**: D2 + D4 + D6 + D11 + D14 + D26 + D27 + D30 + D42 + D44 + D45.2 + D63 + D66 + D67 + D74-D77 + D92 + D100 + D102 + D103 + D106 + D107 + D108; B156 + B185 + B187 closed elsewhere; B188 + B189 + B190 new in this supplement; Phase 0 deliv 0.2 + 0.3 + 0.5 (advisory side) + 0.17 closures; Round 4.5 supplement `phase1/04a_phase_0_prep_tools.md` sibling.

## § 8. How to update this document

Per D100 + D92 forward-only — additive changes only. New tool specs (Tool 17, etc.) may be appended; existing sections get fix-in-place updates only for typos or cross-reference corrections. Validation discipline + Pattern F at close-out apply.
