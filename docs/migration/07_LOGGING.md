# UDM Pipeline — Logging Strategy

## Philosophy

Three principles drive the logging design:

1. **Logs are first-class data, not throwaway debug output.** They live in SQL Server tables, are queried via Power BI, and feed audit reports. Structured from the start.
2. **Extensive logging by default; disciplined hygiene around sensitive data.** Better to log too much and filter at query time than to be missing the line that explains a production incident. Never log plaintext PII.
3. **Every log line is queryable by `BatchId`.** When something goes wrong, the operator's first move is `WHERE BatchId = X`, and that one filter must surface the entire story of that pipeline run.

## Existing logging infrastructure (preserved + extended)

The pipeline already has a logging foundation in `observability/`:

- **`observability/event_tracker.py`** — `PipelineEventTracker` context manager → `General.ops.PipelineEventLog`. One row per pipeline step.
- **`observability/log_handler.py`** — `SqlServerLogHandler` (a `logging.Handler` subclass) → `General.ops.PipelineLog`. Many rows per step.

Both stay. The new architecture extends them:

- New events for the new layers (Parquet write, vault tokenization, registry insert, gate acquisition)
- New mandatory fields for cross-layer queryability
- Power BI consumes both tables directly

## Log levels

Standard Python `logging` levels, used per CLAUDE.md retention discipline:

| Level | When to use | Retention | Examples |
|---|---|---|---|
| **DEBUG** | Step-by-step internal details useful only for troubleshooting | 30 days | "Read 50,247 rows from Stage", "Hash compare iteration 3 of 8" |
| **INFO** | Normal pipeline progression worth recording | 30 days | "Extraction started for DNA.ACCT", "SCD2 promoted 1,247 new versions" |
| **WARNING** | Unexpected condition that didn't fail the operation | 90 days | "L_99 measurement skipped: insufficient data", "Vault lookup latency >1s" |
| **ERROR** | Operation failed but pipeline can continue (e.g., one table failed, others run) | indefinite | "DNA.ACCT extraction failed", "Bronze MERGE deadlock" |
| **CRITICAL** | Pipeline-fatal condition | indefinite | "PiiVault unreachable", "Network drive unmounted", "Key rotation expired" |

Buffer flush behavior (preserves OBS-4):
- DEBUG/INFO: buffered up to 10 entries OR 5 seconds, whichever first
- WARNING+: flushed immediately (zero buffering window for severity-bearing messages)
- Buffer flush failure: print to stderr, never silently swallowed (OBS-4)

## Structured log schema

### `General.ops.PipelineEventLog` (existing — extended)

One row per pipeline *step*. Fields documented in CLAUDE.md; here's the full list with extensions for the new architecture:

| Column | Type | Purpose |
|---|---|---|
| BatchId | BIGINT | Per-run ID; constant for the entire pipeline run |
| TableName | NVARCHAR(255) | Table being processed |
| SourceName | NVARCHAR(50) | Source system |
| EventType | NVARCHAR(50) | EXTRACT, BCP_LOAD, CDC_PROMOTION, SCD2_PROMOTION, CSV_CLEANUP, TABLE_TOTAL, **PARQUET_WRITE, VAULT_TOKENIZE, REGISTRY_INSERT, GATE_ACQUIRE, FAILOVER_TRIGGERED, FAILOVER_RECOVERED, CDC_MODE_CUTOVER, RECONCILIATION_OVERRIDE, MANUAL_CORRECTION, COLD_RESTORE, COLD_PURGE, RETENTION_ENFORCEMENT, CCPA_DELETION** |
| EventDetail | NVARCHAR(MAX) | Free-text detail — typically `target_date` for windowed steps (OBS-2) |
| StartedAt | DATETIME2(3) | When the step began |
| CompletedAt | DATETIME2(3) | When the step finished |
| DurationMs | BIGINT | Wall-clock time |
| Status | NVARCHAR(20) | SUCCESS, FAILED, SKIPPED |
| ErrorMessage | NVARCHAR(MAX) | Error detail when Status='FAILED' |
| RowsProcessed | BIGINT | Total rows handled |
| RowsInserted | BIGINT | New CDC inserts / SCD2 new versions |
| RowsUpdated | BIGINT | Updated CDC / SCD2 closes |
| RowsDeleted | BIGINT | Marked-deleted |
| RowsUnchanged | BIGINT | No-op rows (idempotent skips) |
| RowsBefore | BIGINT | Target table count before |
| RowsAfter | BIGINT | Target table count after |
| TableCreated | BIT | Whether UDM table was created in this run |
| Metadata | NVARCHAR(MAX) | JSON for one-off metrics (existing OBS-7 pattern) |
| RowsPerSecond | DECIMAL(18,2) | Throughput |
| **CycleType** | NVARCHAR(10) | NEW: 'AM' or 'PM' — driven by Automic var (D29) |
| **CycleDate** | DATE | NEW: business date of the cycle |
| **ServerRole** | NVARCHAR(20) | NEW: 'production' or 'test' (failover visibility, D29) |

### `General.ops.PipelineLog` (existing — extended)

Many rows per step; the narrative log. Schema documented in CLAUDE.md. Mandatory fields preserved; new fields:

| Column | Type | Purpose |
|---|---|---|
| BatchId | BIGINT | Same as PipelineEventLog (join key) |
| TableName | NVARCHAR(255) NULL | Nullable for pipeline-level entries |
| SourceName | NVARCHAR(50) NULL | Nullable for pipeline-level entries |
| LogLevel | NVARCHAR(10) | DEBUG / INFO / WARNING / ERROR / CRITICAL |
| Module | NVARCHAR(255) | Python module (e.g., `extract.connectorx_oracle_extractor`) |
| FunctionName | NVARCHAR(255) | Specific function |
| Message | NVARCHAR(MAX) | Human-readable |
| ErrorType | NVARCHAR(255) | Exception class name when applicable |
| StackTrace | NVARCHAR(MAX) | Traceback for ERROR/CRITICAL |
| Metadata | NVARCHAR(MAX) | JSON for structured context |
| CreatedAt | DATETIME2(3) | When the entry was emitted |
| **CycleType** | NVARCHAR(10) NULL | NEW: matches PipelineEventLog |
| **CycleDate** | DATE NULL | NEW: matches PipelineEventLog |
| **ServerRole** | NVARCHAR(20) NULL | NEW: 'production' or 'test' |
| **Layer** | NVARCHAR(20) NULL | NEW: 'extract', 'tokenize', 'parquet', 'registry', 'scd2', 'snowflake', 'gate', 'vault', 'health' |

The `Layer` field is the biggest debugging accelerator — instead of grepping module names, operators filter by layer.

## Per-layer logging content

What each layer logs at each level. Use this as the discipline reference for new code.

### Extract layer

```python
# DEBUG: per-chunk progress
logger.debug("Read chunk %d of %d (%d rows)", chunk_n, total_chunks, len(chunk),
             extra={"layer": "extract", "chunk": chunk_n, "rows": len(chunk)})

# INFO: extraction started/completed
logger.info("Extraction started: source=%s table=%s window=[%s, %s)", 
            source, table, start_date, end_date,
            extra={"layer": "extract", "rows_expected": expected_count})

logger.info("Extraction completed: %d rows in %.2fs (%.0f rows/sec)",
            len(df), duration, len(df) / duration,
            extra={"layer": "extract", "throughput": len(df) / duration})

# WARNING: source connection slow, partial results, etc.
logger.warning("Source query exceeded 30s threshold: %.2fs", duration,
               extra={"layer": "extract", "threshold_breach": True})

# ERROR: extraction failed
logger.error("Extraction failed for %s.%s: %s", source, table, err,
             exc_info=True,  # captures stack trace
             extra={"layer": "extract", "error_class": err.__class__.__name__})
```

### Tokenization layer

```python
# DEBUG: per-batch tokenization progress
logger.debug("Tokenizing column %s: %d unique values, %d cached, %d new",
             column, total, cached, new,
             extra={"layer": "tokenize", "column": column,
                    "cached_count": cached, "new_count": new})

# INFO: column tokenized
logger.info("Tokenized column %s: %d new tokens, %d reused, %d total rows",
            column, new, reused, total,
            extra={"layer": "tokenize", "column": column})

# WARNING: vault lookup latency
logger.warning("Vault lookup latency %d ms exceeded 500ms threshold for column %s",
               latency_ms, column,
               extra={"layer": "tokenize", "latency_ms": latency_ms})

# ERROR: vault unreachable
logger.error("PiiVault unreachable: %s", err,
             extra={"layer": "tokenize", "vault_endpoint": endpoint})
# CRITICAL: vault unreachable + retry exhausted
```

**NEVER log**: plaintext PII values, decrypt operations beyond audit metadata. Use token references and hash prefixes only.

### Parquet write layer

```python
# DEBUG: file path, schema hash, row count
logger.debug("Writing Parquet: path=%s rows=%d schema_hash=%s",
             inflight_path, len(df), schema_hash,
             extra={"layer": "parquet", "path": str(inflight_path)})

# INFO: file completed
logger.info("Parquet written: %s (%.1f MB compressed, %d rows, %d row groups)",
            final_path, file_size_mb, row_count, row_groups,
            extra={"layer": "parquet", "size_mb": file_size_mb})

# WARNING: file size outside expected band
logger.warning("Parquet file size %.1f MB outside 100-250 MB band — possible "
               "configuration drift or unusual row distribution",
               file_size_mb,
               extra={"layer": "parquet", "expected_min": 100, "expected_max": 250})

# ERROR: write failure
logger.error("Parquet write failed at %s: %s", inflight_path, err,
             exc_info=True,
             extra={"layer": "parquet"})
```

### Registry layer

```python
# DEBUG: registry CRUD
logger.debug("Registry INSERT: source=%s table=%s batch=%d", 
             source, table, batch_id,
             extra={"layer": "registry"})

# INFO: registration succeeded
logger.info("Parquet registered: file=%s tier=%s checksum=%s",
            file_path, tier, checksum[:16],
            extra={"layer": "registry"})

# WARNING: idempotency hit (unusual but not error)
logger.warning("Registry INSERT idempotent skip: file %s already registered for batch %d",
               file_path, batch_id,
               extra={"layer": "registry", "idempotent_skip": True})

# ERROR: integrity check failed
logger.error("Registry checksum mismatch on %s — stored=%s computed=%s",
             file_path, stored_checksum[:16], computed_checksum[:16],
             extra={"layer": "registry"})
```

### SCD2 promotion layer

```python
# DEBUG: per-PK comparison
logger.debug("SCD2 compare: %d new, %d changed, %d unchanged, %d closed",
             new, changed, unchanged, closed,
             extra={"layer": "scd2"})

# INFO: SCD2 completed
logger.info("SCD2 promoted: source=%s table=%s new=%d changed=%d closed=%d unchanged=%d",
            source, table, new, changed, closed, unchanged,
            extra={"layer": "scd2"})

# WARNING: high update ratio (E-12)
logger.warning("E-12: High SCD2 new_versions ratio %.1f%% (%d/%d) — possible systematic hash mismatch",
               ratio * 100, new_versions, total,
               extra={"layer": "scd2", "ratio": ratio})

# ERROR: SCD2 promotion failure
# CRITICAL: B-4 orphan detection finds large number — possible past corruption
```

### Gate / failover layer

```python
# INFO: gate acquired
logger.info("Pipeline gate acquired: cycle=%s date=%s server=%s batch=%d",
            cycle, cycle_date, server, batch_id,
            extra={"layer": "gate", "cycle_type": cycle, "server": server})

# INFO: failover triggered
logger.info("FAILOVER triggered: cycle=%s reason=%s", cycle, reason,
            extra={"layer": "gate", "failover": True, "reason": reason})

# WARNING: failover triggered for second consecutive cycle
logger.warning("Production failover triggered for second consecutive cycle (%s) — "
               "escalate to RB-2 manual server failover",
               cycle,
               extra={"layer": "gate", "consecutive_failover": True})

# ERROR: gate row indicates corruption (e.g., RUNNING for >12h)
```

### Vault / decrypt layer

```python
# INFO: vault operation summary (NEVER plaintext)
logger.info("Vault: %d new tokens, %d reused for source=%s column=%s",
            new, reused, source, column,
            extra={"layer": "vault"})

# INFO: decrypt request (audit trail mirrored to PiiVaultAccessLog)
logger.info("Decrypt request: request_id=%s caller=%s tokens=%d justification=<redacted>",
            request_id, caller, len(tokens),
            extra={"layer": "vault", "request_id": str(request_id)})

# WARNING: anomalous decrypt access patterns
logger.warning("Decrypt anomaly: caller %s requested %d tokens (typical: <50)",
               caller, len(tokens),
               extra={"layer": "vault", "anomaly": True})
```

### Snowflake layer

```python
# INFO: replication started/completed
logger.info("Snowflake mirror: source=%s table=%s rows=%d duration=%.2fs",
            source, table, rows, duration,
            extra={"layer": "snowflake"})

# WARNING: lag detected
logger.warning("Snowflake mirror lag: %d minutes behind source",
               lag_minutes,
               extra={"layer": "snowflake", "lag_minutes": lag_minutes})

# ERROR: COPY INTO failed
```

### Health check layer (Phase 7)

```python
# INFO: check executed
logger.info("Health check: %s for %s.%s — status=%s value=%.4f threshold=%.4f",
            check_name, source, table, status, value, threshold,
            extra={"layer": "health", "check": check_name, "status": status})
```

## Sensitive data hygiene

**Hard rules**:

1. **Never log plaintext PII.** Use token references, hash prefixes, or redacted markers.
2. **Never log decrypt operation outputs** beyond what's already in `PiiVaultAccessLog`.
3. **Never log database connection strings** with embedded credentials.
4. **Never log full source query strings** that may contain PII as filter values.

**Enforcement mechanisms**:

- A custom `logging.Filter` (`observability/sensitive_data_filter.py`) scans every log message + Metadata JSON for patterns matching SSN, EIN, account number formats, email regex, and known sensitive column names. On match: replaces with `[REDACTED]` and logs a CRITICAL alert that sensitive data almost leaked.
- **Code review checklist**: every new logger.* call inspected for sensitive payload risk.
- **CI lint rule**: forbidden patterns in logger calls (e.g., `logger.*plaintext`, `logger.*ssn`, `logger.*decrypt.*plaintext`).
- **Quarterly review**: sample 1000 random log entries and audit for sensitive data leakage.

## Performance and buffering

Reuse the existing OBS-4 / OBS-5 patterns:

- Buffer up to 10 entries OR 5 seconds before flush (DEBUG/INFO)
- Flush WARNING+ immediately
- Explicit `conn.commit()` after each flush (OBS-5 — never trust autocommit)
- On flush failure: print to stderr (OBS-4 — surface, don't swallow)
- Per-pipeline-run `BatchId` cached in thread-local; modules don't pass it manually

## Retention policy (per CLAUDE.md)

```sql
-- Cleanup job runs daily; per-level retention enforced
-- DEBUG/INFO: 30 days
DELETE FROM General.ops.PipelineLog
WHERE LogLevel IN ('DEBUG', 'INFO')
  AND CreatedAt < DATEADD(day, -30, SYSUTCDATETIME());

-- WARNING+: 90 days
DELETE FROM General.ops.PipelineLog
WHERE LogLevel = 'WARNING'
  AND CreatedAt < DATEADD(day, -90, SYSUTCDATETIME());

-- ERROR/CRITICAL: indefinite (no cleanup; archive to Parquet at 1 year)

-- PipelineEventLog: indefinite (low volume, audit-critical)
-- Archived to cold-tier Parquet at 7 years per D30
```

## Power BI integration

### Connection

Power BI Desktop connects to SQL Server via DirectQuery (live) for the latest 7 days, Import (cached) for older history. Refresh schedule: hourly for hot data, daily for historical.

### Recommended dashboards

#### Dashboard 1: Pipeline Overview (real-time ops)

- **Tile 1**: Today's AM/PM run status (Production / Test, Success / Fail) — driven by `PipelineExecutionGate`
- **Tile 2**: Last 7 days run history with success rate
- **Tile 3**: Active batch_ids in flight (Status='RUNNING' in PipelineEventLog with no completion)
- **Tile 4**: Recent failover events (last 30 days)
- **Tile 5**: Tables behind expected freshness (B-9 alerting)

#### Dashboard 2: Per-Table Deep Dive

User filters by source + table, dashboard shows:
- Last 30 days runtime trend (from PipelineEventLog DurationMs by EventType)
- Throughput (rows/sec) by EventType
- Recent errors with stack traces
- Schema evolution history
- Bronze active count + version count over time

#### Dashboard 3: Anomaly Board (Phase 7)

- Recent anomalies (from HealthCheckLog where Status='WARNING' or 'ERROR')
- Anomaly severity distribution
- Per-table anomaly count over time
- Open vs acknowledged anomalies

#### Dashboard 4: Audit / Compliance

- Recent CCPA deletion requests (from CcpaDeletionLog)
- Vault row count by Status (active / deleted_per_request / purged_for_retention / legal_hold_only)
- Decrypt access patterns (from PiiVaultAccessLog) — anomaly detection
- Retention enforcement events (from PipelineEventLog where EventType='RETENTION_ENFORCEMENT')
- Cross-source PII inventory (from PiiTokenProvenance)

#### Dashboard 5: Executive Summary

- Pipeline uptime over the last quarter
- $/month Snowflake spend trend
- Number of tables migrated (Phase 4 progress)
- Audit-ready posture: outstanding ExtractionGapLog entries, ReconciliationFinding entries
- Headline metrics: rows processed, tokens minted, errors

## Debugging workflows

### Workflow 1: "Pipeline failed last night, what happened?"

```sql
-- Step 1: find the failed batch
SELECT TOP 1 * FROM General.ops.PipelineEventLog
WHERE Status = 'FAILED' 
  AND StartedAt > DATEADD(hour, -24, SYSUTCDATETIME())
ORDER BY StartedAt DESC;
-- Capture BatchId

-- Step 2: see the narrative for that batch
SELECT CreatedAt, LogLevel, Layer, Module, FunctionName, Message, ErrorType
FROM General.ops.PipelineLog
WHERE BatchId = @BatchId
ORDER BY CreatedAt;

-- Step 3: drill into ERROR / CRITICAL
SELECT CreatedAt, Module, FunctionName, Message, ErrorType, StackTrace, Metadata
FROM General.ops.PipelineLog
WHERE BatchId = @BatchId AND LogLevel IN ('ERROR', 'CRITICAL')
ORDER BY CreatedAt;
```

### Workflow 2: "Bronze for table X has duplicate active rows"

```sql
-- Find which batch wrote the duplicates
WITH dups AS (
    SELECT pk_columns, MIN(_cdc_batch_id) as first_batch, MAX(_cdc_batch_id) as last_batch
    FROM UDM_Bronze.X.Y_scd2_python
    WHERE UdmActiveFlag = 1
    GROUP BY pk_columns
    HAVING COUNT(*) > 1
)
SELECT * FROM dups;

-- Find the SCD2_PROMOTION events for those batches
SELECT * FROM General.ops.PipelineEventLog
WHERE BatchId IN (...) AND EventType = 'SCD2_PROMOTION';

-- See the narrative
SELECT * FROM General.ops.PipelineLog
WHERE BatchId IN (...) AND Layer = 'scd2'
ORDER BY BatchId, CreatedAt;
```

### Workflow 3: "Did we tokenize column X for source Y in the last week?"

```sql
SELECT BatchId, TokenizedAt, NewTokensGenerated, ExistingTokensReused, TotalRowsTokenized
FROM General.ops.PiiTokenizationBatch
WHERE SourceName = 'DNA' AND ColumnName = 'EMAIL'
  AND TokenizedAt > DATEADD(day, -7, SYSUTCDATETIME())
ORDER BY TokenizedAt DESC;
```

### Workflow 4: "Why did the auto-failover trigger this morning?"

```sql
SELECT TOP 5 * FROM General.ops.PipelineEventLog
WHERE EventType = 'FAILOVER_TRIGGERED'
ORDER BY StartedAt DESC;
-- Look at Metadata JSON for the reason

-- Then look at the prod batch that didn't complete
SELECT * FROM General.ops.PipelineExecutionGate
WHERE CycleDate = CAST(SYSDATETIME() AS DATE);
```

### Workflow 5: "How long did the SCD2 step take for table X over the last month?"

```sql
SELECT 
    CAST(StartedAt AS DATE) as RunDate,
    AVG(DurationMs) / 1000.0 as AvgSeconds,
    MAX(DurationMs) / 1000.0 as MaxSeconds
FROM General.ops.PipelineEventLog
WHERE EventType = 'SCD2_PROMOTION'
  AND TableName = 'X' AND SourceName = 'Y'
  AND StartedAt > DATEADD(month, -1, SYSUTCDATETIME())
GROUP BY CAST(StartedAt AS DATE)
ORDER BY RunDate;
```

(This query becomes a Power BI line chart trivially.)

## Alerting integration

Three classes of alerts:

| Class | Trigger | Channel | Response time |
|---|---|---|---|
| **Critical** | CRITICAL log entry; failover triggered for 2nd consecutive cycle; vault unreachable; key rotation expired | Email + Teams + on-call rotation | < 1 hour |
| **Warning** | WARNING entries above threshold rate; freshness >36h; reconciliation drift; vault decrypt anomaly | Email to ops team | < 24 hours |
| **Info** | First failover of a cycle (auto-recovered); single table failure; scheduled maintenance event | Power BI dashboard tile | reviewed daily |

Alert dispatch is handled by a separate `tools/alert_dispatcher.py` job that runs every 5 minutes, queries `PipelineEventLog` and `PipelineLog` for new high-severity entries, and routes via configured channels.

## Implementation notes for Phase 1

- **Add `Layer`, `CycleType`, `CycleDate`, `ServerRole` columns to PipelineLog and PipelineEventLog** as part of Phase 1 migrations
- **Implement `observability/sensitive_data_filter.py`** with regex-based PII detection
- **Implement `observability/log_handler.py` extension** to populate the new fields automatically from thread-local context
- **Implement `tools/log_retention_cleanup.py`** for the daily DELETE jobs
- **Implement `tools/alert_dispatcher.py`** with email/Teams routing
- **Power BI dashboard files** committed to `docs/power_bi/` as `.pbix` source-controlled artifacts (where possible)

## How to Add a Logging Pattern

1. Identify the layer (extract / tokenize / parquet / registry / scd2 / vault / snowflake / gate / health)
2. Pick the appropriate level (DEBUG / INFO / WARNING / ERROR / CRITICAL) per the table above
3. Use `logger.<level>(message, *args, extra={"layer": "...", "<custom>": ...})`
4. Avoid sensitive payloads (run through the sensitive_data_filter mentally; the runtime filter is a backstop)
5. Make the message human-readable AND include structured `extra` fields for Power BI parsing
6. If the new pattern surfaces a useful Power BI metric, add a dashboard tile for it
