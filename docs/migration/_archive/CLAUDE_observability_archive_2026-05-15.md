<\!-- Archive provenance:
- Extracted from: CLAUDE.md (pre-trim state at commit c189432 / 2026-05-15 / 720 lines total)
- Extracted at: lines 292-405 (114 lines verbatim)
- Trim commit: 7e2c606 (D.5 Approach A — Conservative trim per Q-12 approved)
- Trim rationale: section was largely DUPLICATE of canonical content at the destination(s); replaced in active CLAUDE.md with summary + cross-ref to reduce CCL token cost
- Destination cross-ref(s) in active CLAUDE.md: docs/migration/phase1/02_configuration.md § Observability + CLAUDE.md (post-trim) summary at L195-225 + GLOSSARY skill catalogue
- Archive strategy: belt-and-suspenders per user-direction 2026-05-15 (Option B "Archive EVERYTHING verbatim"); content preserved for recovery without git archaeology
- Reversibility: `git show c189432:CLAUDE.md` returns full pre-trim CLAUDE.md; this archive is a partial slice
- Authored: 2026-05-15 by retroactive archive sweep per refactor-strategy decision
- Linked from: docs/migration/_refactor_log.md (refactor event D.5-observability)
-->

# CLAUDE.md — Observability: Event Tracking + Pipeline Logs (archived)

**This is an archived copy** of the Observability: Event Tracking + Pipeline Logs section from CLAUDE.md, extracted verbatim from the pre-D.5-trim state. The active CLAUDE.md no longer contains this section — see cross-ref destination(s) above for the canonical home(s).

If you arrived here looking for current information: prefer the destination cross-ref. This archive exists for recovery + audit-trail purposes only.

---

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

- **CLI_\*** family — one row per CLI invocation per D76 audit-row contract. Values: CLI_PARQUET_TIER_REVIEW, CLI_PARQUET_VERIFY, CLI_LATENESS_PROFILE, CLI_DECRYPT_PII, CLI_DETECT_EXTRACTION_GAPS, CLI_PROMOTE_TEST_TO_PROD, CLI_VERIFY_SERVER_PARITY, CLI_ENFORCE_RETENTION, CLI_PROCESS_CCPA_DELETION, CLI_LOG_RETENTION_CLEANUP, CLI_ALERT_DISPATCHER (11 tools per Round 4 § 3) + Round 6 follow-up additions CLI_VERIFY_TIER0_DRIFT (B58 full impl 146d97a) + CLI_SNOWFLAKE_COPY_SMOKE + CLI_SCD2_REPLAY_SMOKE + CLI_DIAGNOSE_STAGE_BRONZE_GAP (3-agent cohort 2026-05-14; 15 tools total). Metadata JSON carries args, actor, justification, exit_code per D75 + D76.
- **CYCLE_\*** family — pipeline cycle lifecycle per Round 2 § 5.3.6 + Round 4 § 3.6. Values: CYCLE_FAILED_OVER (test claimed gate after prod heartbeat stale; written by SP-4 path), CYCLE_CANCELLED (graceful cancellation per D33; written by check_cancellation per RB-9).
- **DEPLOYMENT_\*** family — per environment promotion audit row per D87 + Round 6 § 1.6. Values: DEPLOYMENT_DEV, DEPLOYMENT_TEST, DEPLOYMENT_PROD, DEPLOYMENT_ROLLBACK (4 variants). Metadata JSON carries tag, prior_tag, actor, justification, pre_check_results, post_check_results, soak_duration_minutes.
- **MIGRATION_\*** family — per `migrations/<name>.py` script invocation per Round 6 § 4.1. Values: MIGRATION_<NAME> (one per script; N values, one per migration). Metadata JSON carries applied_at, applied_by, checksum. **Round 7 addition** (per `phase1/07_schema_evolution_governance.md` § 6.2): MIGRATION_AUTOMIC_INVENTORY canonical value when the frozen-Automic-job inventory is amended (e.g., frozen-8 → frozen-11 per JOB_PARQUET_VERIFY + JOB_LOG_CLEANUP + JOB_PARITY_EXCEPTION_NOTIFY); Metadata JSON carries `added_jobs`, `frozen_count_before`, `frozen_count_after`.
- **PARQUET_\*** family — one row per Parquet snapshot state-machine transition per Round 3 § 1.3 + B-229. Values: PARQUET_VERIFY (post-write SHA verification), PARQUET_REPLICATE (Snowflake COPY succeeded), PARQUET_ARCHIVE (cold storage transition), PARQUET_PURGE (retention expiry), PARQUET_MARK_MISSING (file absent from network drive), PARQUET_MARK_REPLICATION_FAILED (Snowflake COPY error retryable). Metadata JSON carries registry_id, source_name, table_name, batch_id, business_date, sha256 per transition. Added 2026-05-14 at Round 3 close-out via paired-audit recommendation; closes B-229.
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
