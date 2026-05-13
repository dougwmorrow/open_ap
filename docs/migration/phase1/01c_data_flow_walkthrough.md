# Phase 1 Round 1.5c — Data Flow Walkthrough + Observability Annotations

**Status**: 🟡 Proposed — pending Round 1.5 D72 validation campaign + Pattern F close-out audit
**Round position**: Round 1.5 — Schema Documentation Supplement
**Authored**: 2026-05-11

This supplement closes the schema-story gap most impactful for **dashboard authorship + data-driven insights**: a per-cycle trace of what writes happen to the 24 `General.ops.*` tables + 2 `General.dbo.*` control tables, when, in what order, with what observability hooks. One of 5 Round 1.5 supplements: G1 `phase1/01a_control_tables.md` (Round 1.5a) + G3+G4 `phase1/01b_bronze_stage_example_ddl.md` (Round 1.5b) + this doc (Round 1.5c) + G5 `phase1/07a_schema_contract_examples.md` (Round 1.5d) + G2 ER diagrams in `09_VISUALS.md` (Round 1.5e).

---

## § 0 — Read order + scope

### 0.1 Required reading

1. `phase1/01a_control_tables.md` — control tier (UdmTablesList + UdmTablesColumnsList)
2. `phase1/01_database_schema.md` — Round 1 operational metadata tables
3. `phase1/01b_bronze_stage_example_ddl.md` — Bronze + Stage table shape
4. `CLAUDE.md` "Data Flow (per table)" + "Observability: Event Tracking + Pipeline Logs" sections
5. `phase1/03_core_modules.md` — Round 3 Python module interface specs
6. `phase1/04_tools.md` — Round 4 operator CLI specs
7. `01_ARCHITECTURE.md` — architecture-level data flow
8. `05_RUNBOOKS.md` — RB-2 (manual failover), RB-9 (auto-failover), RB-10 (CCPA), RB-11 (retention), RB-12 (deployment)

### 0.2 Why this doc exists

After Phase 1 Rounds 1-8 + Round 1.5a/b/c/d/e (all 5 supplements: control tables + Bronze/Stage DDL + this data-flow walkthrough + SchemaContract examples + ER diagrams), an engineer joining the project can see:
- WHAT data is stored (Round 1 + supplements)
- HOW the pipeline is configured (Round 2 + 01a)
- WHAT modules exist (Round 3-4)
- HOW it's tested (Round 5)
- HOW it deploys (Round 6)
- HOW schema evolves post-lock (Round 7)
- HOW the validation discipline self-tunes (Round 8)

But none of those answer: **"When the AM cycle runs at 06:00, what actually happens, in what order, and which tables get written when?"** This doc is that narrative. It's the dashboard author's reference — it shows exactly which events fire at which moments so Power BI / Snowflake reports / monitoring dashboards know what to query.

### 0.3 Scope

**In scope**:
- § 1: The 3 cycle types (AM / PM / ad-hoc) — what triggers each
- § 2: AM cycle happy-path end-to-end trace
- § 3: Per-table extract → CDC → SCD2 → Parquet sub-cycle
- § 4: Failover branch (heartbeat-stale → test claims gate)
- § 5: Cancellation branch (cooperative SP-5/SP-6)
- § 6: Crash recovery branch (SP-9 startup recovery sweep)
- § 7: Edge case branches (delete detection, gap detection, manual correction, repair)
- § 8: Observability annotations — what gets logged where + what's queryable
- § 9: Dashboard query catalog (15+ example queries grouped by audience)
- § 10: Bottleneck-identification workflow
- § 11: Validation gates self-check

**Out of scope**:
- Snowflake mirror runtime (Phase 5)
- Health-check tier (Phase 6)
- Per-module Python implementation details (Round 3)
- DR scenario (RB-7 quarterly drill)

---

## § 1 — Cycle types

| Cycle | When | Trigger | Server | Primary writes |
|---|---|---|---|---|
| **AM** | ~06:00 weekdays | Automic `JOB_PIPELINE_AM_CYCLE` (per Round 2 § 5.1 + R7 frozen-11 inventory) | Prod (test stays warm) | `PipelineExecutionGate` row with `CycleType='AM'` |
| **PM** | ~18:00 weekdays | Automic `JOB_PIPELINE_PM_CYCLE` | Prod (test stays warm) | `PipelineExecutionGate` row with `CycleType='PM'` |
| **Ad-hoc** | Operator-triggered | Operator runs `main_small_tables.py --table <X>` or `main_large_tables.py --table <X>` | Either prod or test | `PipelineEventLog` only (no `PipelineExecutionGate` row) |

Cycle types are mutually exclusive — at most one AM + one PM per `CycleDate`. The pipeline reads `CycleType` + `CycleDate` to enforce this via `UNIQUE` constraint on `PipelineExecutionGate (CycleType, CycleDate)`.

---

## § 2 — AM cycle happy-path end-to-end trace

The walkthrough below shows what happens from Automic firing the trigger through to the last write at cycle completion. Times are illustrative; column writes are concrete.

### T0 — Automic fires AM cycle trigger

```
06:00:00 — Automic invokes:
  python3 main_small_tables.py --workers 4 --cycle AM --batch-id-source General.ops.PipelineBatchSequence
  (or for large tables: main_large_tables.py with appropriate args)
```

`AUTOMIC_RUN_ID` env var is set; main script reads it for invocation-context heuristic (per D75 actor TTY heuristic).

**Database writes so far**: none.

### T1 — Module startup sequence (per D85)

```
06:00:01 — credentials_loader.load()
06:00:01 — INSERT General.ops.PipelineEventLog
              EventType=STARTUP_CREDS_LOAD
              Status=IN_PROGRESS
              StartedAt=06:00:01
```

```
06:00:03 — credentials_loader.load() returns; vault config initialized
06:00:03 — UPDATE General.ops.PipelineEventLog
              SET CompletedAt=06:00:03, DurationMs=2000, Status=SUCCESS
              WHERE EventId=<just-inserted>
06:00:03 — INSERT General.ops.PipelineEventLog
              EventType=STARTUP_VAULT_CONFIG
              Status=IN_PROGRESS
```

```
06:00:05 — Vault pool config complete → INSERT STARTUP_PARITY_CHECK row
06:00:05 — server_parity_verifier.verify()
            Reads: /etc/pipeline/parity_baseline.json
            Compares: RHEL version, Python version, library SHAs, MALLOC_ARENA_MAX, etc.
06:00:06 — If FATAL drift → sys.exit(1) — no further writes
06:00:06 — UPDATE PARITY_CHECK row Status=SUCCESS
06:00:06 — INSERT STARTUP_LEDGER_SWEEP row
```

```
06:00:07 — SP-9 IdempotencyLedger_RecoveryStartupSweep(@max_age_minutes=60)
              Scans IdempotencyLedger for IN_PROGRESS rows older than 60 min
              Cleans stale rows (per E-8 + Round 3 § 4.1)
              Returns count of recovered rows
06:00:08 — UPDATE STARTUP_LEDGER_SWEEP row Status=SUCCESS, RowsProcessed=<count>
06:00:08 — INSERT STARTUP_ORCHESTRATION_START row
```

Module-startup observable signature: 5 rows in `PipelineEventLog` with `EventType IN ('STARTUP_CREDS_LOAD', 'STARTUP_VAULT_CONFIG', 'STARTUP_PARITY_CHECK', 'STARTUP_LEDGER_SWEEP', 'STARTUP_ORCHESTRATION_START')` — see CLAUDE.md "STARTUP_*" family registration.

### T2 — Acquire AM gate (production server)

```
06:00:10 — Pipeline calls SP-3 PipelineExecutionGate_AcquireProd(
              @cycle='AM', @cycle_date='2026-05-11'
            ) → returns @gate_id, @batch_id (BIGINT)
            
06:00:10 — INSERT General.ops.PipelineExecutionGate (
              CycleType='AM',
              CycleDate='2026-05-11',
              ExecutingServer='prod-server-01',
              Status='STARTING',
              ActualStartTime='2026-05-11 06:00:10',
              LastHeartbeatAt='2026-05-11 06:00:10',
              CancellationRequested=0,
              ...
            )
            Returns @gate_id, @batch_id
            
06:00:10 — UPDATE STARTUP_ORCHESTRATION_START row Status=SUCCESS
```

**Database writes so far**: 5 STARTUP_* rows + 1 PipelineExecutionGate row.

### T3 — Read UdmTablesList for cycle's tables

```
06:00:11 — TableConfigLoader.load_tables(cycle='AM')
              SELECT tl.*, list of UdmTablesColumnsList rows joined on (SourceName, TableName, Layer)
              FROM General.dbo.UdmTablesList tl
              WHERE tl.IsEnabled = 1
                AND tl.StageLoadTool = 'Python'
                AND tl.SourceName IN ('DNA', 'CCM', 'EPICOR')   -- AM cycle scope
              ORDER BY some priority order;
            
            Returns N TableConfig objects (one per row)
```

**Database READS** — no writes. UdmTablesList is the trigger tier.

### T4 — Per-table processing (parallel workers)

For each table T (subject to `--workers N` concurrency; default 4):

See § 3 for the per-table sub-cycle. Each table writes ~12-15 rows across `PipelineEventLog` (per-step events) + `IdempotencyLedger` (per-step state) + `ParquetSnapshotRegistry` (1 row per Parquet write) + Stage table + Bronze table.

**Heartbeat**: every ~30 seconds during table processing, pipeline updates `PipelineExecutionGate.LastHeartbeatAt = SYSDATETIME()` so test server's SP-4 doesn't claim the gate via failover (per § 4 below).

### T5 — Reconciliation (post-table loop)

```
06:30:00 — After all tables processed:
06:30:01 — Run reconcile_counts() for tables with weekly recon scheduled
06:30:01 — INSERT General.ops.ReconciliationLog (
              BatchId=<batch_id>, CheckType='reconcile_counts',
              Status='IN_PROGRESS', StartedAt=06:30:01, ...
            )
06:30:03 — (Reconciliation runs; checks source row counts vs Stage vs Bronze)
06:30:03 — UPDATE ReconciliationLog Status='SUCCESS', DiscrepancyCount=<N>, CompletedAt=06:30:03
```

If `DiscrepancyCount > 0`, ALSO writes a `PipelineEventLog` row with `EventType='RECONCILE_DISCREPANCY'` for alerting.

### T6 — Snowflake mirror (Phase 5; currently TBD)

```
06:30:05 — (When Phase 5 lands) snowflake_uploader.stage_pending_parquet()
            Reads ParquetSnapshotRegistry WHERE StorageTier='hot' AND SnowflakeStagePath IS NULL
            COPY INTO Snowflake stage
            UPDATE ParquetSnapshotRegistry SET SnowflakeStagePath=<path>, StorageTier='snowflake_staged'
```

Until Phase 5: ParquetSnapshotRegistry rows stay with `StorageTier='hot'` + `SnowflakeStagePath IS NULL`.

### T7 — Release AM gate

```
06:30:10 — UPDATE General.ops.PipelineExecutionGate
              SET Status='SUCCEEDED',
                  ActualCompletionTime='2026-05-11 06:30:10'
              WHERE GateId=@gate_id;
06:30:10 — INSERT PipelineEventLog (
              EventType='CYCLE_COMPLETED', BatchId=@batch_id,
              Status='SUCCESS', DurationMs=<total>,
              Metadata={"tables_processed": N, "tables_skipped": M, "reconciliation_discrepancies": K}
            )
```

**Total AM cycle observable signature** (happy path):
- 6 STARTUP_* + CYCLE_COMPLETED rows in `PipelineEventLog`
- 1 `PipelineExecutionGate` row (created at T2, updated at T7)
- 1 `PipelineBatchSequence` value consumed (the `@batch_id`)
- Per-table: ~12-15 rows in `PipelineEventLog` × N tables (see § 3)
- 1 `ParquetSnapshotRegistry` row per table
- 1+ `ReconciliationLog` row depending on schedule
- 0+ `PipelineLog` rows (narrative; many per cycle but all linked by `BatchId`)
- 0 manual correction rows (only operator UPDATEs write these)

---

## § 3 — Per-table sub-cycle (the inner loop)

For each table T in the cycle's scope:

```
T_start — Worker N picks up table T from queue

[Step 1: Acquire table lock]
T_start+1ms — sp_getapplock(@table=T, @LockOwner='Session')
              Per P1-2; prevents concurrent runs on same table.
              If lock held by another run: INSERT PipelineEventLog (
                EventType='TABLE_TOTAL', Status='SKIPPED',
                EventDetail='Lock held by another run'
              ) → skip to next table
              
[Step 2: Begin extraction]
T_start+10ms — SP-7 IdempotencyLedger_StartStep(
                @BatchId, @SourceName=T.SourceName, @TableName=T.SourceObjectName,
                @EventType='EXTRACT'
              ) → returns @Action
              If @Action='skip' (this step already SUCCEEDED for this BatchId): skip to Step 4
              If @Action='proceed': continue
              
T_start+10ms — INSERT IdempotencyLedger (
                BatchId=@BatchId, SourceName=T.SourceName, TableName=T.SourceObjectName,
                EventType='EXTRACT', Status='IN_PROGRESS', StartedAt=...
              )
              
T_start+10ms — INSERT PipelineEventLog (
                EventType='EXTRACT', BatchId=@BatchId, SourceName=T.SourceName, TableName=T.SourceObjectName,
                Status='IN_PROGRESS', StartedAt=...
              )
              
[Step 3: Execute extraction]
T_start+100ms — extractor (ConnectorX OR oracledb per UdmTablesList routing)
                connects to source, runs SQL, returns Polars DataFrame
                For large table: per-day windowed loop (per CLAUDE.md "Large Tables")
                
T_start+5s — Extraction returns DataFrame with N rows
T_start+5s — sanitize_strings(), add _row_hash (polars-hash), add _extracted_at
              
T_start+5s — pii_tokenizer.tokenize_pii_columns(df, T.PiiColumnList)
              For each new plaintext value:
                SP-1 PiiVault_GetOrCreateToken(@plaintext, @pii_type, @source_name)
                → may INSERT PiiVault row (if new) + INSERT PiiTokenProvenance row (if first observation for this (Source, Object))
              
T_start+6s — INSERT PiiTokenizationBatch (
                BatchId=@BatchId, SourceName=T.SourceName, ObjectName=T.SourceObjectName,
                ColumnName=<each PII column>, TokenizedAt=...,
                NewTokensGenerated=<count>, ExistingTokensReused=<count>, TotalRowsTokenized=N, DurationMs=...
              )  -- one row per (BatchId, SourceName, ObjectName, ColumnName) per UX_PiiTokenizationBatch_Identity

[Step 4: Write Parquet snapshot]
T_start+6.5s — parquet_writer.write_snapshot(df, T.SourceName, T.SourceObjectName, target_date)
                Stage-check-exchange rename pattern: write to .inflight, atomic rename to final path
T_start+8s — INSERT ParquetSnapshotRegistry (
                SourceName=T.SourceName, TableName=T.SourceObjectName, BatchId=@BatchId,
                BusinessDate=target_date, StorageTier='hot',
                CompressedBytes=..., UncompressedBytes=..., Checksum=...,
                CreatedAt=08:..., LastVerifiedAt=NULL
              )

[Step 5: Write Stage CDC table (BCP)]
T_start+8s — prepare_dataframe_for_bcp() + reorder_columns_for_bcp() + sanitize()
T_start+8s — bcp_loader writes UDM_Stage.{Source}.{Table}_cdc rows
T_start+10s — INSERT PipelineEventLog (EventType='BCP_LOAD', ..., RowsProcessed=N, DurationMs=2000)

[Step 6: CDC promotion (Polars in-memory)]
T_start+10.5s — cdc/engine.py compares Stage current vs new DataFrame
                Detects: inserts (I), updates (U), deletes (D)
                Filters NULL PKs per P0-4
                Writes change rows back to Stage with _cdc_operation set
T_start+12s — INSERT PipelineEventLog (
                EventType='CDC_PROMOTION', BatchId=@BatchId, SourceName=..., TableName=...,
                Status='SUCCESS', DurationMs=1500,
                RowsInserted=I, RowsUpdated=U, RowsDeleted=D, RowsUnchanged=Z,
                Metadata={"null_pk_rows": K, "update_ratio": U/(I+U+Z+D)}
              )

[Step 7: SCD2 promotion (Polars in-memory vs Bronze active)]
T_start+12.5s — scd2/engine.py compares Stage current vs Bronze active rows
                Detects: new versions (Update-close), deletes (Delete-close), resurrects (R-op), inserts (I-op)
                Writes via 2-step pattern (INSERT new versions with Flag=0; UPDATE close-old + activate-new)
                Per SCD2-R4 three-value flag semantic
T_start+15s — INSERT PipelineEventLog (
                EventType='SCD2_PROMOTION', BatchId=@BatchId, ...,
                Status='SUCCESS', DurationMs=2500,
                RowsInserted=Inew, RowsUpdated=Uclose, RowsDeleted=Dclose,
                Metadata={"active_ratio": <Flag=1 / total>, "scd2_repair_triggered": false}
              )

[Step 8: Cleanup CSV]
T_start+15.5s — cleanup_csvs() removes temp CSV files

[Step 9: Complete idempotency ledger step]
T_start+15.5s — SP-8 IdempotencyLedger_CompleteStep(@BatchId, T.SourceName, T.SourceObjectName,
                'EXTRACT', Status='COMPLETED')  -- canonical CK_IdempotencyLedger_Status: IN_PROGRESS/COMPLETED/FAILED

[Step 10: Release table lock]
T_start+16s — sp_releaseapplock

[Step 11: Write TABLE_TOTAL summary]
T_start+16s — INSERT PipelineEventLog (
                EventType='TABLE_TOTAL', BatchId=@BatchId, SourceName=T.SourceName, TableName=T.SourceObjectName,
                Status='SUCCESS', DurationMs=16000, RowsProcessed=N,
                Metadata={"extract_ms": 6000, "bcp_ms": 2000, "cdc_ms": 1500, "scd2_ms": 2500}
              )
```

**Per-table observable signature**:
- 1 `IdempotencyLedger` row (EXTRACT step; may have N sub-steps for large tables)
- 5-7 `PipelineEventLog` rows (EXTRACT, BCP_LOAD, CDC_PROMOTION, SCD2_PROMOTION, CSV_CLEANUP, TABLE_TOTAL; plus optional STARTUP for large tables)
- 1 `ParquetSnapshotRegistry` row
- 1 `PiiTokenizationBatch` row (if `PiiColumnList` non-NULL)
- 0-N `PiiVault` row inserts (only on truly new plaintext values)
- 0-N `PiiTokenProvenance` row inserts (only on first-observation events)
- 0-N `PipelineLog` rows (narrative; depends on log level)
- Bronze + Stage table writes (per § 3 of this doc)

For large tables (per-day windowed): multiply the per-step rows by the day count (e.g., 30-day lookback × 7 steps × ~5 rows per step = ~1050 rows per table per cycle).

---

## § 4 — Failover branch

Triggered when test server detects prod heartbeat is stale (per D29 revised + RB-9).

```
[Test server's AM cycle starts ~30 minutes after prod AM]
06:30:00 — Test invokes SP-4 PipelineExecutionGate_AcquireTest(@cycle='AM', @cycle_date='2026-05-11',
            @HeartbeatStaleMinutes=15, @ProdMaxRuntimeMinutes=120)

           Logic:
           - Read existing AM gate row
           - If Status='SUCCEEDED' → return @Action='EXIT_SUCCEEDED' (no failover needed)
           - If Status='RUNNING' AND LastHeartbeatAt > NOW - 15 min → return @Action='EXIT_RUNNING_HEALTHY'
             (prod is still alive; test exits without touching anything)
           - If Status='RUNNING' AND LastHeartbeatAt <= NOW - 15 min → @Action='PROCEED_FAILOVER'
             AND UPDATE gate row: ExecutingServer='test-server-01', Status='RUNNING' (gate retains RUNNING; only ExecutingServer flips — per Round 1 SP-4 § 4)

[Path A: EXIT_SUCCEEDED]
06:30:01 — INSERT PipelineEventLog (EventType='CYCLE_EXIT_SUCCEEDED', BatchId=NULL,
            Metadata={"reason": "prod completed AM cycle"})
06:30:01 — Test process exits 0; no further writes

[Path B: EXIT_RUNNING_HEALTHY]
06:30:01 — INSERT PipelineEventLog (EventType='CYCLE_EXIT_RUNNING_HEALTHY', BatchId=NULL,
            Metadata={"prod_heartbeat_age_seconds": 480})
06:30:01 — Test process exits 0; no further writes

[Path C: PROCEED_FAILOVER (the failover case)]
06:30:01 — INSERT PipelineEventLog (EventType='CYCLE_FAILED_OVER', BatchId=NULL,
            Metadata={"prod_heartbeat_stale_seconds": 1200, "prod_server": "prod-server-01"})
06:30:01 — UPDATE PipelineExecutionGate
            SET ExecutingServer='test-server-01', Status='RUNNING'
            WHERE GateId=<existing>
06:30:02 — Test claims the gate; continues per § 3 from per-table processing
            (idempotency ledger short-circuits any steps prod already SUCCEEDED on)
```

**Observable signature for failover events** (per RB-9):
- `EventType='CYCLE_FAILED_OVER'` event with Metadata
- `PipelineExecutionGate.ExecutingServer` flips prod → test
- `PipelineExecutionGate.LastHeartbeatAt` resumes incrementing under test
- Operations dashboard alert fires on `CYCLE_FAILED_OVER` events within last 24h

---

## § 5 — Cancellation branch

Operator-initiated, cooperative (per D33).

```
[Operator decides to cancel an in-flight cycle]
HH:MM:SS — Operator runs: SP-5 PipelineExecutionGate_RequestCancellation(
            @cycle='AM', @cycle_date='2026-05-11', @requested_by='ops-lead', @reason='Source DB outage')
HH:MM:SS — UPDATE PipelineExecutionGate
            SET CancellationRequested=1,
                CancellationRequestedBy='ops-lead',
                CancellationReason='Source DB outage'
            WHERE CycleType='AM' AND CycleDate='2026-05-11'

[Pipeline checks for cancellation between tables]
HH:MM:SS — orchestration/check_cancellation()
            SELECT CancellationRequested FROM PipelineExecutionGate WHERE GateId=...
            If 1 → orchestration loop stops processing further tables
            
HH:MM:SS — SP-6 PipelineExecutionGate_AcknowledgeCancellation(@gate_id)
            UPDATE PipelineExecutionGate SET Status='CANCELLED', ActualCompletionTime=NOW
HH:MM:SS — INSERT PipelineEventLog (EventType='CYCLE_CANCELLED', BatchId=...,
            Metadata={"tables_processed_before_cancel": N, "tables_remaining": M,
                      "cancellation_requested_by": "ops-lead", "cancellation_reason": "Source DB outage"})
```

Cooperative semantics: tables already in-progress complete normally (idempotency ledger ensures no partial writes); only remaining-queued tables are skipped.

---

## § 6 — Crash recovery branch

Triggered by `kill -9` or process crash mid-cycle.

```
[Cycle was at table N of M when crash occurred]
HH:MM:SS — Pipeline process killed; OS releases sp_getapplock automatically (per W-8 Session-owned locks)
HH:MM:SS — PipelineExecutionGate.LastHeartbeatAt no longer increments

[Next AM cycle invocation (could be same day or next day)]
NEXT_HH:MM:SS — Module startup sequence runs (§ 2 T1)
              SP-9 IdempotencyLedger_RecoveryStartupSweep(@max_age_minutes=60)
              Identifies IN_PROGRESS rows older than 60 min
              For each: UPDATE Status='FAILED' (per CK_IdempotencyLedger_Status canonical IN_PROGRESS/COMPLETED/FAILED — recovered-after-crash classifies as FAILED so caller can re-attempt the step on next run with idempotency-ledger short-circuit semantics)
              Returns recovered row count

NEXT_HH:MM:SS — INSERT PipelineEventLog (EventType='STARTUP_LEDGER_SWEEP',
              Metadata={"recovered_count": K, "max_recovered_age_minutes": 480})

[If prior crashed cycle was the same CycleType + CycleDate]
NEXT_HH:MM:SS — SP-3 or SP-4 detects existing IN_PROGRESS gate row
                → returns @Action='RECOVERY' (new path? OR PROCEED_FAILOVER if heartbeat stale)
                → resume processing per failover logic
```

**Observable signature**:
- `EventType='STARTUP_LEDGER_SWEEP'` with `Metadata.recovered_count > 0`
- Original `PipelineEventLog` rows from crashed cycle have `Status='IN_PROGRESS'` + no `CompletedAt`
- `PipelineLog` rows with `LogLevel='CRITICAL'` if exception trace was captured before crash

---

## § 7 — Edge case branches

### 7.1 Delete detection (large tables; per P1-4)

Per CLAUDE.md "Large Tables Windowed CDC":

```
HH:MM:SS — During CDC promotion, engine detects PKs missing from current extract that were present prior
HH:MM:SS — Cross-check with PipelineExtraction trust gate (per canonical Round 1 § 3 schema)
            For each candidate-delete PK:
              IF source PipelineExtraction.Status='SUCCESS' for the affected DateValue → DELETE proceeds
              IF source not yet trusted → INSERT DeleteEvaluationAudit (
                AuditId, BatchId, SourceName, TableName, DateValue, EvaluatedAt,
                EvaluationOutcome='suppressed_no_success', AuthoritativeBatchId=...,
                BronzeActiveCount=..., CandidateDeleteCount=K, SuppressedReason='...'
              )  -- per canonical Round 1 § 11 schema
              Then candidate deletes are skipped this cycle
```

**Observable signature**: `DeleteEvaluationAudit` rows with `Decision='SUPPRESSED'` indicate deletes pending. Reconciliation queries can flag tables with persistent suppression.

### 7.2 Extraction gap detection

Per Round 3 `cdc/gap_detector.py`:

```
HH:MM:SS — Large-table gap detector identifies missing DateValue rows in PipelineExtraction (per canonical Round 1 § 3)
HH:MM:SS — INSERT ExtractionGapLog (
            GapLogId, SourceName, TableName, MissingFromDate=<gap start>, MissingToDate=<gap end>,
            Classification='never_attempted', DetectedAt=..., DetectedByBatchId=...,
            Resolution='PENDING'
          )  -- per canonical Round 1 § 12 schema (Classification enum: never_attempted / all_attempts_failed / beyond_source_retention)
HH:MM:SS — gap_detector auto-enqueues recoverable gaps for next cycle (within retention window); Resolution flips to 'BACKFILLED' on success
```

**Observable signature**: `ExtractionGapLog` rows with `GapDate > NOW - 30 days` indicate active gap-recovery candidates.

### 7.3 Manual correction (operator-initiated)

```
HH:MM:SS — Operator: tools/manual_correction.py --table ACCT --row-pk 12345 --action 'fix_token'
HH:MM:SS — INSERT ManualCorrectionLog (
            CorrectionId, BatchId=NULL, SourceName, TableName,
            CorrectionType='token_re-tokenize', Description='token reassignment per RB-10 audit',
            Actor='ops-lead', Justification='CCPA audit follow-up', CorrectedAt=...
          )
```

ManualCorrectionLog is the explicit operator-write trail — distinct from automated pipeline writes. Compliance audits read this table specifically.

### 7.4 SCD2 repair (operator-driven via tools/repair_scd2.py)

```
HH:MM:SS — Operator: tools/repair_scd2.py --apply --type sentinel_fill --source DNA --table ACCT
HH:MM:SS — INSERT SCD2RepairLog (
            RepairId, SourceName='DNA', TableName='ACCT',
            RepairType='sentinel_fill', Status='IN_PROGRESS', StartedAt=...
          )
HH:MM:SS — Repair runs (per SCD2-R6 safe ops list)
HH:MM:SS — UPDATE SCD2RepairLog Status='SUCCESS', RowsAffected=K, SamplePks=<JSON list>, CompletedAt=...
```

---

## § 8 — Observability annotations — what gets logged where

### 8.1 The "two tables, two purposes" pattern

Per CLAUDE.md "Observability: Event Tracking + Pipeline Logs":

| Table | Purpose | Cardinality |
|---|---|---|
| `General.ops.PipelineEventLog` | The **dashboard layer** — small, structured, one row per step. Query for bottleneck analysis, throughput trends, failure rates. | ~5-15 rows per table per cycle × N tables = ~50-500 rows per cycle |
| `General.ops.PipelineLog` | The **investigation layer** — many rows per step. Detailed narrative for debugging *why* something was slow / failed / behaved unexpectedly. | ~10-200 rows per cycle (filtered by log level) |

Together: PipelineEventLog says "ACCT SCD2_PROMOTION took 12 minutes Tuesday 2 PM"; PipelineLog says "Stage row count was 2.3M; memory peaked 6 GB; UPDATE batch hit lock-wait on Bronze".

### 8.2 EventType families and what each says

Per CLAUDE.md "EventType families registered per Round 4 D76 + Round 6 § 6.4":

| Family | Says | Cardinality per cycle |
|---|---|---|
| `EXTRACT` | Extract from source completed | 1 per table |
| `BCP_LOAD` | BCP CSV → SQL Server load | 0-2 per table (small tables = 1 staging table load; large tables embed inside CDC) |
| `CDC_PROMOTION` | Polars CDC comparison + Stage write | 1 per table |
| `SCD2_PROMOTION` | Polars SCD2 comparison + Bronze write | 1 per table |
| `CSV_CLEANUP` | Temp CSV files removed | 1 per table |
| `TABLE_TOTAL` | End-to-end per-table wall time | 1 per table |
| `CLI_<TOOL>` | Operator CLI invocation | 0+ per cycle (operator-driven) |
| `CYCLE_FAILED_OVER` / `CYCLE_CANCELLED` / `CYCLE_COMPLETED` | Cycle lifecycle | 1 per cycle |
| `STARTUP_<STAGE>` | Module startup sequence (5 stages) | 5 per pipeline process invocation |
| `MIGRATION_<NAME>` | Migration script invocation | 1 per migration run (rare) |
| `DEPLOYMENT_<ENV>` | Deployment audit | 1 per deployment (dev nightly / test daily / prod weekly per D86) |
| `DISTRIBUTION_CHECK` | Numeric distribution baseline (B-10) | 0+ per cycle (weekly recon) |
| `MODIFIED_SWEEP` | Tier-2 modified-date sweep result (LT-2) | 1 per large table per cycle (if LastModifiedColumn set) |

### 8.3 Status enum

`PipelineEventLog.Status` allowed values (per `CK_PipelineEventLog_Status`):
- `IN_PROGRESS` — step started; not yet complete
- `SUCCESS` — step completed without error
- `FAILED` — step raised an exception
- `SKIPPED` — step did not execute (lock held; idempotency ledger short-circuit; cancellation)

### 8.4 Metadata JSON convention

Most events carry `Metadata` as a JSON string. Common keys per EventType:
- `EXTRACT`: `{"source_query_seconds": X, "rows_extracted": N, "extractor_type": "connectorx|oracledb"}`
- `CDC_PROMOTION`: `{"null_pk_rows": K, "update_ratio": float, "schema_migration": bool}`
- `SCD2_PROMOTION`: `{"active_ratio": float, "scd2_repair_triggered": bool, "delete_close_count": K}`
- `TABLE_TOTAL`: `{"extract_ms": int, "bcp_ms": int, "cdc_ms": int, "scd2_ms": int}`
- `CYCLE_FAILED_OVER`: `{"prod_heartbeat_stale_seconds": int, "prod_server": "prod-server-01"}`
- `CYCLE_CANCELLED`: `{"tables_processed_before_cancel": int, "cancellation_requested_by": "ops-lead", "cancellation_reason": "..."}`
- `DEPLOYMENT_<ENV>`: `{"tag": "v1.2.3", "actor": "...", "pre_check_results": [...], "post_check_results": [...]}`

---

## § 9 — Dashboard query catalog

Operational dashboards by audience. Each query is Power BI / Snowflake / direct-SQL-Server-compatible (SQL Server syntax shown; trivially adaptable).

### 9.1 Operations team — "Is the AM cycle running on schedule?"

```sql
SELECT
    CycleDate,
    CycleType,
    ExecutingServer,
    Status,
    ActualStartTime,
    ActualCompletionTime,
    DATEDIFF(MINUTE, ActualStartTime, COALESCE(ActualCompletionTime, SYSDATETIME())) AS minutes_elapsed,
    CASE 
        WHEN Status = 'SUCCEEDED' THEN '✅'
        WHEN Status = 'RUNNING' AND DATEDIFF(MINUTE, LastHeartbeatAt, SYSDATETIME()) > 15 THEN '🔴 STALE'
        WHEN Status IN ('STARTING','RUNNING') THEN '🟡 RUNNING'
        WHEN Status = 'RUNNING' AND ExecutingServer <> (SELECT TOP 1 ExecutingServer FROM General.ops.PipelineExecutionGate WHERE CycleType = pg.CycleType ORDER BY ActualStartTime ASC) THEN '🟡 FAILOVER'
        WHEN Status = 'CANCELLED' THEN '⚪ CANCELLED'
        WHEN Status = 'FAILED' THEN '🔴 FAILED'
    END AS health
FROM General.ops.PipelineExecutionGate
WHERE CycleDate >= DATEADD(DAY, -14, SYSDATETIME())
ORDER BY CycleDate DESC, CycleType;
```

**Dashboard**: real-time cycle health card; alert on any 🔴 status persisting > 15 min.

### 9.2 Engineering team — "What are the slowest tables this week?"

```sql
SELECT TOP 20
    SourceName,
    TableName,
    AVG(DurationMs) / 1000.0 AS avg_seconds,
    MAX(DurationMs) / 1000.0 AS max_seconds,
    COUNT(*) AS run_count,
    AVG(RowsProcessed) AS avg_rows,
    AVG(CAST(RowsProcessed AS FLOAT) / NULLIF(DurationMs / 1000.0, 0)) AS avg_rows_per_sec
FROM General.ops.PipelineEventLog
WHERE EventType = 'TABLE_TOTAL'
  AND Status = 'SUCCESS'
  AND StartedAt > DATEADD(DAY, -7, SYSDATETIME())
GROUP BY SourceName, TableName
ORDER BY avg_seconds DESC;
```

**Dashboard**: bar chart by table; spotlight outliers for performance investigation.

### 9.3 Engineering team — "Which step is the bottleneck per table?"

```sql
WITH StepDurations AS (
    SELECT
        SourceName, TableName, EventType,
        AVG(DurationMs) / 1000.0 AS avg_seconds
    FROM General.ops.PipelineEventLog
    WHERE EventType IN ('EXTRACT', 'BCP_LOAD', 'CDC_PROMOTION', 'SCD2_PROMOTION', 'CSV_CLEANUP')
      AND Status = 'SUCCESS'
      AND StartedAt > DATEADD(DAY, -7, SYSDATETIME())
    GROUP BY SourceName, TableName, EventType
)
SELECT
    SourceName, TableName,
    MAX(CASE WHEN EventType = 'EXTRACT' THEN avg_seconds END) AS extract_s,
    MAX(CASE WHEN EventType = 'BCP_LOAD' THEN avg_seconds END) AS bcp_s,
    MAX(CASE WHEN EventType = 'CDC_PROMOTION' THEN avg_seconds END) AS cdc_s,
    MAX(CASE WHEN EventType = 'SCD2_PROMOTION' THEN avg_seconds END) AS scd2_s,
    MAX(CASE WHEN EventType = 'CSV_CLEANUP' THEN avg_seconds END) AS cleanup_s
FROM StepDurations
GROUP BY SourceName, TableName
ORDER BY MAX(avg_seconds) DESC;
```

**Dashboard**: stacked bar per table; identify whether EXTRACT, CDC, or SCD2 dominates total time.

### 9.4 Compliance team — "PII tokenization activity by source"

```sql
SELECT
    SourceName,
    SUM(NewTokensGenerated) AS new_tokens_week,
    SUM(ExistingTokensReused) AS reused_tokens_week,
    CAST(SUM(ExistingTokensReused) AS FLOAT) / NULLIF(SUM(NewTokensGenerated + ExistingTokensReused), 0) AS reuse_ratio
FROM General.ops.PiiTokenizationBatch
WHERE TokenizedAt > DATEADD(DAY, -7, SYSDATETIME())
GROUP BY SourceName
ORDER BY new_tokens_week DESC;
```

**Dashboard**: PII volume per source; reuse ratio indicates tokenization-determinism health (low reuse ratio could signal a problem).

### 9.5 Compliance team — "Decrypt access patterns"

```sql
SELECT
    Actor,
    COUNT(*) AS access_count_week,
    COUNT(DISTINCT RequestId) AS distinct_requests,
    MIN(AccessedAt) AS first_access,
    MAX(AccessedAt) AS most_recent
FROM General.ops.PiiVaultAccessLog
WHERE AccessedAt > DATEADD(DAY, -7, SYSDATETIME())
GROUP BY Actor
ORDER BY access_count_week DESC;
```

**Dashboard**: who accessed PII decryption this week; flag anomalies via z-score or threshold.

### 9.6 Operations team — "Lock contention frequency"

```sql
SELECT
    SourceName, TableName,
    COUNT(*) AS skip_count_week,
    MIN(StartedAt) AS first_skip,
    MAX(StartedAt) AS most_recent_skip
FROM General.ops.PipelineEventLog
WHERE EventType = 'TABLE_TOTAL'
  AND Status = 'SKIPPED'
  AND EventDetail = 'Lock held by another run'
  AND StartedAt > DATEADD(DAY, -7, SYSDATETIME())
GROUP BY SourceName, TableName
ORDER BY skip_count_week DESC;
```

**Dashboard**: identify tables with chronic lock contention; informs scheduling decisions.

### 9.7 Engineering team — "Failover incidents this quarter"

```sql
SELECT
    StartedAt AS failover_time,
    JSON_VALUE(Metadata, '$.prod_heartbeat_stale_seconds') AS heartbeat_stale_seconds,
    JSON_VALUE(Metadata, '$.prod_server') AS prod_server_at_failover
FROM General.ops.PipelineEventLog
WHERE EventType = 'CYCLE_FAILED_OVER'
  AND StartedAt > DATEADD(DAY, -90, SYSDATETIME())
ORDER BY StartedAt DESC;
```

**Dashboard**: failover timeline; correlation with deployments / source-system outages.

### 9.8 Engineering team — "Reconciliation discrepancy trends"

```sql
SELECT
    CONVERT(DATE, CompletedAt) AS recon_date,
    SourceName,
    TableName,
    CheckType,
    SUM(DiscrepancyCount) AS total_discrepancies
FROM General.ops.ReconciliationLog
WHERE Status = 'SUCCESS'
  AND CompletedAt > DATEADD(DAY, -30, SYSDATETIME())
GROUP BY CONVERT(DATE, CompletedAt), SourceName, TableName, CheckType
HAVING SUM(DiscrepancyCount) > 0
ORDER BY recon_date DESC, total_discrepancies DESC;
```

**Dashboard**: reconciliation health over time; spike detection drives investigation runbooks.

### 9.9 Engineering team — "CDC update ratio anomaly detection" (per E-12)

```sql
SELECT TOP 50
    StartedAt,
    SourceName, TableName,
    JSON_VALUE(Metadata, '$.update_ratio') AS update_ratio,
    JSON_VALUE(Metadata, '$.null_pk_rows') AS null_pk_rows,
    RowsUpdated,
    RowsInserted + RowsUpdated + RowsDeleted + RowsUnchanged AS total_rows
FROM General.ops.PipelineEventLog
WHERE EventType = 'CDC_PROMOTION'
  AND Status = 'SUCCESS'
  AND CAST(JSON_VALUE(Metadata, '$.update_ratio') AS FLOAT) > 0.5
  AND RowsUpdated > 1000
  AND StartedAt > DATEADD(DAY, -14, SYSDATETIME())
ORDER BY StartedAt DESC;
```

**Dashboard**: alert when update_ratio > 50% AND updates > 1000 (per E-12) — signals systematic hash mismatch / schema drift / normalization bug.

### 9.10 Engineering team — "SCD2 active-ratio drift" (per E-14)

```sql
SELECT
    SourceName, TableName,
    CONVERT(DATE, StartedAt) AS run_date,
    AVG(CAST(JSON_VALUE(Metadata, '$.active_ratio') AS FLOAT)) AS avg_active_ratio
FROM General.ops.PipelineEventLog
WHERE EventType = 'SCD2_PROMOTION'
  AND Status = 'SUCCESS'
  AND StartedAt > DATEADD(DAY, -30, SYSDATETIME())
GROUP BY SourceName, TableName, CONVERT(DATE, StartedAt)
HAVING AVG(CAST(JSON_VALUE(Metadata, '$.active_ratio') AS FLOAT)) < 0.5
ORDER BY avg_active_ratio ASC;
```

**Dashboard**: tables with declining active ratio over time signal mass-deletion or accumulation issue.

### 9.11 Operations team — "Parquet storage growth by table"

```sql
SELECT
    SourceName, TableName,
    COUNT(*) AS snapshot_count,
    SUM(CompressedBytes) / 1024.0 / 1024.0 / 1024.0 AS total_gb,
    SUM(CompressedBytes) / NULLIF(COUNT(*), 0) / 1024.0 / 1024.0 AS avg_mb_per_snapshot
FROM General.ops.ParquetSnapshotRegistry
WHERE CreatedAt > DATEADD(DAY, -30, SYSDATETIME())
GROUP BY SourceName, TableName
ORDER BY total_gb DESC;
```

**Dashboard**: storage capacity planning; informs Phase 0 deliverable 0.17 baseline updates.

### 9.12 Operations team — "Data freshness by table" (per E-15)

```sql
SELECT
    tl.SourceName,
    tl.SourceObjectName,
    tl.CDCMode,
    MAX(el.StartedAt) AS last_successful_run,
    DATEDIFF(HOUR, MAX(el.StartedAt), SYSDATETIME()) AS hours_stale,
    CASE 
        WHEN DATEDIFF(HOUR, MAX(el.StartedAt), SYSDATETIME()) > 48 THEN '🔴 STALE-2x'
        WHEN DATEDIFF(HOUR, MAX(el.StartedAt), SYSDATETIME()) > 36 THEN '🟡 STALE-1.5x'
        ELSE '✅ Fresh'
    END AS freshness
FROM General.dbo.UdmTablesList tl
LEFT JOIN General.ops.PipelineEventLog el
    ON el.SourceName = tl.SourceName
   AND el.TableName = tl.SourceObjectName
   AND el.EventType = 'TABLE_TOTAL'
   AND el.Status = 'SUCCESS'
WHERE tl.IsEnabled = 1
  AND tl.StageLoadTool = 'Python'
GROUP BY tl.SourceName, tl.SourceObjectName, tl.CDCMode
ORDER BY hours_stale DESC;
```

**Dashboard**: freshness alarms per B-9 tiered thresholds.

### 9.13 Engineering team — "Schema evolution audit trail"

```sql
SELECT
    ObjectName,
    ColumnName,
    ContractKey,
    ContractValue,
    EffectiveFrom,
    EffectiveTo,
    CreatedBy,
    Notes
FROM General.ops.SchemaContract
WHERE SourceName = 'pipeline'
  AND EffectiveFrom > DATEADD(DAY, -180, SYSDATETIME())
ORDER BY EffectiveFrom DESC;
```

**Dashboard**: rolling 6-month view of SP signature evolutions + future schema changes; drives compliance audits.

### 9.14 Management — "Pipeline cost / value summary card"

```sql
WITH WeekStats AS (
    SELECT
        COUNT(DISTINCT BatchId) AS cycle_count_week,
        SUM(CASE WHEN EventType = 'TABLE_TOTAL' AND Status = 'SUCCESS' THEN 1 ELSE 0 END) AS table_runs_success,
        SUM(CASE WHEN EventType = 'TABLE_TOTAL' AND Status = 'FAILED' THEN 1 ELSE 0 END) AS table_runs_failed,
        SUM(CASE WHEN EventType = 'TABLE_TOTAL' AND Status = 'SKIPPED' THEN 1 ELSE 0 END) AS table_runs_skipped,
        SUM(CASE WHEN EventType = 'TABLE_TOTAL' THEN RowsProcessed ELSE 0 END) AS total_rows_processed,
        SUM(CASE WHEN EventType = 'TABLE_TOTAL' THEN DurationMs ELSE 0 END) / 1000.0 / 60.0 AS total_minutes
    FROM General.ops.PipelineEventLog
    WHERE StartedAt > DATEADD(DAY, -7, SYSDATETIME())
)
SELECT
    cycle_count_week,
    table_runs_success,
    CAST(table_runs_success AS FLOAT) / NULLIF(table_runs_success + table_runs_failed, 0) AS success_rate,
    table_runs_failed,
    table_runs_skipped,
    total_rows_processed,
    total_minutes
FROM WeekStats;
```

**Dashboard**: single executive card; weekly trend over 12 weeks.

### 9.16 Compliance team — "Token-to-Bronze reverse index" (closes B178 storytelling gap)

> *"Auditor asks: where does token `abc123def456` appear in production right now?"*

```sql
-- Cross-Bronze scan; UNION across enabled PII tables
-- Generate from UdmTablesList.PiiColumnList dynamically OR hard-code per known tables
WITH token_locations AS (
    SELECT 'DNA.ACCT' AS source_table, 'TAXID' AS column_name, ACCTNBR AS pk
    FROM UDM_Bronze.DNA.ACCT_scd2_python
    WHERE TAXID = 'abc123def456' AND UdmActiveFlag = 1
    UNION ALL
    SELECT 'DNA.ACCT' AS source_table, 'EMAIL' AS column_name, ACCTNBR AS pk
    FROM UDM_Bronze.DNA.ACCT_scd2_python
    WHERE EMAIL = 'abc123def456' AND UdmActiveFlag = 1
    -- ... repeat per PII-bearing Bronze table per UdmTablesList.PiiColumnList
)
SELECT * FROM token_locations
ORDER BY source_table, column_name, pk;
```

**Dashboard**: CCPA audit drill-down; "where to delete from when right-to-deletion lands". Phase 6 candidate for materialized view + index optimization. Note: scales by PII-bearing-table count; an explicit Snowflake reverse index (Phase 5+) may eventually replace this.

### 9.17 Compliance team — "Per-operator audit consolidator" (closes B179 storytelling gap)

> *"Show me everything ops-lead did this quarter across manual corrections, PII decryptions, deployments, cancellations, and retire actions."*

```sql
DECLARE @Actor NVARCHAR(255) = 'ops-lead';
DECLARE @QuarterStart DATETIME2(3) = '2026-01-01';
DECLARE @QuarterEnd DATETIME2(3) = '2026-04-01';

-- Manual corrections (RB-13 retirements, ad-hoc fixes)
SELECT 'manual_correction' AS event_class, CorrectedAt AS event_at,
       CorrectionType AS action, Description AS detail, Justification
FROM General.ops.ManualCorrectionLog
WHERE Actor = @Actor AND CorrectedAt BETWEEN @QuarterStart AND @QuarterEnd

UNION ALL
-- PII decryptions (per D26 + RB-10)
SELECT 'pii_decryption' AS event_class, AccessedAt AS event_at,
       'decrypt' AS action, CONCAT('RequestId=', RequestId) AS detail, Justification
FROM General.ops.PiiVaultAccessLog
WHERE Actor = @Actor AND AccessedAt BETWEEN @QuarterStart AND @QuarterEnd

UNION ALL
-- Deployments (per D87)
SELECT 'deployment' AS event_class, StartedAt AS event_at,
       EventType AS action, 
       CONCAT('tag=', JSON_VALUE(Metadata, '$.tag'), '; actor=', JSON_VALUE(Metadata, '$.actor')) AS detail,
       JSON_VALUE(Metadata, '$.justification') AS Justification
FROM General.ops.PipelineEventLog
WHERE EventType LIKE 'DEPLOYMENT_%'
  AND JSON_VALUE(Metadata, '$.actor') = @Actor
  AND StartedAt BETWEEN @QuarterStart AND @QuarterEnd

UNION ALL
-- Cancellations (per D33)
SELECT 'cancellation' AS event_class, CancellationRequestedAt AS event_at,
       'cancel_cycle' AS action,
       CONCAT('CycleType=', CycleType, ' CycleDate=', CycleDate, ' Reason=', CancellationReason) AS detail,
       CancellationReason AS Justification
FROM General.ops.PipelineExecutionGate
WHERE CancellationRequestedBy = @Actor
  AND CancellationRequestedAt BETWEEN @QuarterStart AND @QuarterEnd

UNION ALL
-- CCPA deletion requests processed
SELECT 'ccpa_deletion' AS event_class, ProcessedAt AS event_at,
       Action AS action,
       CONCAT('RequestId=', RequestId, '; affected_tokens=', LEFT(AffectedTokens, 100), '...') AS detail,
       LegalExceptionReason AS Justification
FROM General.ops.CcpaDeletionLog
WHERE ProcessedBy = @Actor
  AND ProcessedAt BETWEEN @QuarterStart AND @QuarterEnd

ORDER BY event_at DESC;
```

**Dashboard**: quarterly per-operator audit report. Cross-table actor consolidation. Closes the "everything Actor=X did" narrative gap.

### 9.18 Engineering team — "Column-history walker" (closes B180 storytelling gap)

> *"When did `DNA.ACCT.CHARGEOFFAMT` go from `NUMBER(18,4)` to `NUMBER(20,6)`? Who approved it?"*

```sql
SELECT 
    ContractId,
    ContractKey,
    ContractValue,
    EffectiveFrom,
    EffectiveTo,
    CreatedBy,
    Notes,
    -- Forward-link the chain
    sc2.ContractId AS superseded_by_id,
    sc2.ContractValue AS next_value
FROM General.ops.SchemaContract sc
LEFT JOIN General.ops.SchemaContract sc2 ON sc2.ContractId = sc.SupersededBy
WHERE sc.SourceName = 'DNA'
  AND sc.ObjectName = 'ACCT'
  AND sc.ColumnName = 'CHARGEOFFAMT'
  AND sc.ContractKey IN ('expected_type', 'precision', 'scale')
ORDER BY sc.EffectiveFrom ASC;
```

**Dashboard**: per-column evolution timeline. Drives compliance audits ("when did this column change shape") + DBA change-management reviews.

### 9.19 Operations team — "Cross-source health comparison" (closes B181 storytelling gap)

> *"Is DNA pipeline healthier than CCM pipeline this quarter? Where are the bottlenecks per source?"*

```sql
DECLARE @QuarterStart DATETIME2(3) = '2026-01-01';
DECLARE @QuarterEnd DATETIME2(3) = '2026-04-01';

WITH per_source_stats AS (
    SELECT 
        SourceName,
        COUNT(DISTINCT BatchId) AS cycle_count,
        SUM(CASE WHEN EventType = 'TABLE_TOTAL' AND Status = 'SUCCESS' THEN 1 ELSE 0 END) AS table_runs_success,
        SUM(CASE WHEN EventType = 'TABLE_TOTAL' AND Status = 'FAILED' THEN 1 ELSE 0 END) AS table_runs_failed,
        SUM(CASE WHEN EventType = 'TABLE_TOTAL' AND Status = 'SKIPPED' THEN 1 ELSE 0 END) AS table_runs_skipped,
        AVG(CASE WHEN EventType = 'TABLE_TOTAL' AND Status = 'SUCCESS' THEN CAST(DurationMs AS FLOAT) END) / 1000.0 AS avg_seconds_per_table,
        SUM(CASE WHEN EventType = 'TABLE_TOTAL' THEN RowsProcessed ELSE 0 END) AS total_rows,
        -- Reconciliation discrepancies
        (SELECT COUNT(*) FROM General.ops.ReconciliationLog rl 
         WHERE rl.SourceName = el.SourceName 
           AND rl.CompletedAt BETWEEN @QuarterStart AND @QuarterEnd
           AND rl.DiscrepancyCount > 0) AS recon_discrepancies,
        -- Extraction gaps
        (SELECT COUNT(*) FROM General.ops.ExtractionGapLog gl
         WHERE gl.SourceName = el.SourceName
           AND gl.DetectedAt BETWEEN @QuarterStart AND @QuarterEnd
           AND gl.Resolution = 'PENDING') AS pending_gaps
    FROM General.ops.PipelineEventLog el
    WHERE el.StartedAt BETWEEN @QuarterStart AND @QuarterEnd
      AND el.SourceName IS NOT NULL
    GROUP BY el.SourceName
)
SELECT 
    SourceName,
    cycle_count,
    table_runs_success,
    CAST(table_runs_success AS FLOAT) / NULLIF(table_runs_success + table_runs_failed, 0) AS success_rate,
    table_runs_failed,
    table_runs_skipped,
    avg_seconds_per_table,
    total_rows,
    recon_discrepancies,
    pending_gaps,
    -- Health composite score (illustrative)
    CASE 
        WHEN CAST(table_runs_success AS FLOAT) / NULLIF(table_runs_success + table_runs_failed, 0) >= 0.99 
             AND pending_gaps = 0 
             AND recon_discrepancies = 0 THEN '✅ Healthy'
        WHEN CAST(table_runs_success AS FLOAT) / NULLIF(table_runs_success + table_runs_failed, 0) >= 0.95 THEN '🟡 Watch'
        ELSE '🔴 Degraded'
    END AS health
FROM per_source_stats
ORDER BY SourceName;
```

**Dashboard**: side-by-side per-source health card (DNA / CCM / EPICOR rows). Management-tier KPI dashboard. Closes "cross-source narrative" gap.

(For Round 8 self-improvement-loop dashboards; queries the ledger as a SQL table once data is imported)

```sql
-- Hypothetical: _reviewer_effectiveness.md imported as a SQL table
SELECT
    Specialty,
    COUNT(*) AS events_to_date,
    SUM(CAST(FalseClean AS INT)) AS false_clean_count,
    CAST(SUM(CAST(FalseClean AS INT)) AS FLOAT) / COUNT(*) AS false_clean_rate,
    AVG(Minutes) AS avg_minutes
FROM dbo.ReviewerEffectivenessLedger
GROUP BY Specialty
ORDER BY false_clean_rate DESC, events_to_date DESC;
```

**Dashboard**: tracks the self-improvement loop's empirical metrics; drives 8.B specialty-tuner trend analysis.

---

## § 10 — Bottleneck-identification workflow

When a dashboard shows a slow cycle or failed step, the standard investigation flow:

```
Step 1: Identify cycle in PipelineEventLog (§ 9.1 — find IN_PROGRESS or FAILED gate)
   ↓ get BatchId
Step 2: SELECT * FROM PipelineEventLog WHERE BatchId = ? ORDER BY StartedAt
   → see per-step duration trail; identify slow step (e.g., CDC_PROMOTION for table ACCT)
   ↓ get StartedAt timestamp window for that step
Step 3: SELECT * FROM PipelineLog WHERE BatchId = ? 
        AND TableName = 'ACCT' AND CreatedAt BETWEEN ? AND ?
        ORDER BY CreatedAt
   → see WARNINGS or ERRORS that fired during the slow step (e.g., "memory peaked 8 GB on
     2.3M-row DataFrame")
   ↓
Step 4: SELECT * FROM PipelineLog WHERE BatchId = ? AND LogLevel IN ('WARNING', 'ERROR', 'CRITICAL')
   → see exception traces if any
   ↓
Step 5: Cross-reference with control tier:
        SELECT * FROM UdmTablesList WHERE SourceName = 'DNA' AND SourceObjectName = 'ACCT'
   → confirm config matches expectations (CDCMode, ExcludeFromHash, LookbackDays)
```

This is the standard "drill-down" pattern. The two-table layered observability (per CLAUDE.md § "How the Two Tables Work Together") makes it efficient.

---

## § 11 — Validation gates self-check

### 11.1 Gate 1 — Cross-reference

| Check | Verdict |
|---|---|
| Cycle types match Round 2 § 5 Automic job inventory | ✅ Walked (AM + PM + ad-hoc; frozen-11 per R7) |
| EventType families match CLAUDE.md "EventType families registered per Round 4 D76 + Round 6 § 6.4" | ✅ Walked (CLI_*, CYCLE_*, MIGRATION_*, DEPLOYMENT_*, STARTUP_*) |
| Per-table step sequence matches CLAUDE.md "Data Flow (per table)" | ✅ Walked (extract → hash → tokenize → write Parquet → BCP Stage → CDC promote → SCD2 promote → cleanup) |
| Failover semantics match Round 1 § 4 SP-4 + RB-9 | ✅ Walked (heartbeat-stale → EXIT_RUNNING_HEALTHY vs PROCEED_FAILOVER) |
| Cancellation semantics match D33 + SP-5/SP-6 + RB-9 | ✅ Walked |
| Crash recovery semantics match D85 + SP-9 + max_age_minutes=60 (per B137) | ✅ Walked |
| Edge case branches match P1-4 (delete), gap_detector, ManualCorrectionLog, SCD2-R6 repair | ✅ Walked |
| Observability annotations match CLAUDE.md "Observability" section + Round 4 EventType contract | ✅ Walked |
| Dashboard queries valid SQL Server syntax | ✅ Walked (all 15 queries use canonical column names + correct JSON_VALUE syntax + standard joins) |

### 11.2 Gate 2 — Independent QA

Pattern E from cycle 1 per D97 Tier β. Round 1.5 supplements collectively operate at Tier β (~70 KB total).

### 11.3 Gate 3 — Edge case enumeration

§ 7 walks delete detection / gap detection / manual correction / SCD2 repair. § 4-6 walk failover / cancellation / crash recovery. M/S/I/N/P/G/D/F/V/T/DP/SI series have been walked in Round 1 + Round 2 + Round 5; this doc references but does not re-enumerate.

### 11.4 Gate 4 — Edge case validation

Each branch in § 4-7 cites the SP / runbook / decision that mitigates (SP-4 for failover; SP-5/SP-6 for cancellation; SP-9 for crash recovery; SCD2-R6 for repair).

### 11.5 Gate 5 — Idempotency / regression

| Check | Verdict |
|---|---|
| Per-step idempotency via IdempotencyLedger short-circuit | ✅ § 3 Step 2 covers |
| Re-running cycle with same BatchId = no-op | ✅ Per D15 invariant; idempotency ledger gates each step |
| Locked Round 1 / Round 2 / Round 3-4 specs untouched | ✅ This is sibling supplement |
| Dashboard queries respect status enum + EventType canonical values | ✅ Walked |

### 11.6 Pillar mapping (per D61)

| Pillar | Contribution |
|---|---|
| Audit-grade | § 8.1 explicit on PipelineEventLog (dashboard) + PipelineLog (investigation); both append-only |
| Traceability | § 10 bottleneck-investigation workflow ties cycle-level observation to per-step root cause |
| Idempotent | § 3 Step 2 idempotency ledger short-circuit; § 6 crash recovery |
| Operationally stable | § 9 dashboard query catalog gives operators a complete toolkit |
| $120K/year ceiling | Bounded compute; observability adds rows to existing tables (no new Snowflake spend) |

---

## § 12 — Cycle log (Round 1.5 D72 campaign — populated post-acceptance)

See `phase1/01a_control_tables.md` § 11 for the canonical R1.5 cycle log table (all 5 supplements share the same combined campaign). Round 1.5 D72 campaign summary: 6 review cycles + 1 Pattern F event; 23 cumulative 🔴 caught + fixed; D101 math-infeasibility acceptance per D73/D78/D94 precedent.

Full per-cycle detail in `_validation_log.md` 2026-05-11 Round 1.5 entry.

---

## Owner

Pipeline lead. This doc is the dashboard author's reference — § 9 query catalog should be reviewed quarterly per `MAINTENANCE.md` to keep aligned with operational dashboards in production.

## Last updated

2026-05-11 (Round 1.5c authored — observability annotations + 15-query dashboard catalog supporting data-driven insights goal; pending Pattern E validation)
