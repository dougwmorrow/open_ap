# UDM Pipeline — Final Architecture

## 1. Architecture Diagram

```
                              ┌──────────────────────────────────┐
                              │ General.ops metadata tables      │
                              │   PipelineEventLog               │ ◄── process attestation
                              │   PipelineLog                    │     audit truth for "did the
                              │   PipelineExtraction             │     pipeline run on date X"
                              │   ParquetSnapshotRegistry        │
                              │   IdempotencyLedger              │
                              │   DeleteEvaluationAudit          │
                              │   ExtractionRangePolicy          │
                              │   LatenessProfile                │
                              │   ReconciliationLog              │
                              │   ManualCorrectionLog            │
                              │   SCD2RepairLog                  │
                              │   ExtractionGapLog               │
                              │   PiiVault                       │ ◄── tokenization
                              │   PiiVaultAccessLog              │     decrypt audit
                              └──────────────────────────────────┘
                                            ▲
                                            │ writes
                                            │
   ┌─────────┐  Polars+ConnectorX  ┌──────────────────────────────┐
   │ Source  ├────────────────────►│ Python Pipeline (Linux)      │
   │ Oracle  │                     │                              │
   │ SQL Srv │                     │ 1. Extract (windowed/full)   │
   └─────────┘                     │ 2. PII tokenize via vault    │
                                   │ 3. Hash + add metadata       │
                                   │ 4. Write Parquet (atomic)    │
                                   │ 5. Run SCD2 vs Bronze active │
                                   │ 6. Apply SCD2 changes        │
                                   │ 7. Register / audit          │
                                   └──┬───────────┬───────────────┘
                                      │           │
                       writes Parquet │           │ writes SCD2 versions
                                      ▼           ▼
   ┌──────────────────────────────────┐  ┌─────────────────────────────────┐
   │ Network Drive (immutable)        │  │ UDM_Bronze (SQL Server)         │
   │ \\archive\source=...\            │  │   SCD2 versioned dimension      │
   │   table=...\year=YYYY\           │  │   + dual date pair (R-1/R-3)    │
   │   month=MM\day=DD\               │  │   + UdmActiveFlag {0,1,2}       │
   │   batch={id}_part-N.parquet      │  │   + token columns for PII       │
   │ ZSTD-3, 128MB, sorted            │  └────────────┬────────────────────┘
   │ Tracked in registry              │               │
   └────────────┬─────────────────────┘               │ async mirror
                │ async upload (Phase 5)              ▼
                ▼                          ┌─────────────────────────────────┐
   ┌──────────────────────────────────┐    │ Snowflake Bronze (mirror)       │
   │ Snowflake Iceberg @audit_archive │    │   masking policies on tokens    │
   │   reads same Parquet files       │◄───┤   analytics warehouse           │
   │   external; pruned by stats      │    └─────────────────────────────────┘
   └──────────────────────────────────┘                ▲
                                                       │
                                          analytics, reconciliation, backfill
                                          (paid Snowflake compute, ~$25-40K/yr)
```

Three durable artifacts per pipeline run:

1. **Parquet** on the network drive — every observed source state, immutable, audit-grade.
2. **Bronze SCD2 in SQL Server** — every state change with effective dates, regulator-truth.
3. **Operational metadata in `General.ops`** — process attestation, idempotency, audit logs.

Each layer has a single job. No layer doubles up. Recovery flows from durable layers (Parquet, registry) outward to operational state (Bronze, mirrors).

## 2. Layer Responsibilities

| Layer | Job | Idempotency mechanism |
|---|---|---|
| **Source** | Snapshot-isolated read where available; window-bounded queries with TRUNC date boundaries | Same window, same source state → byte-identical extraction |
| **PII tokenization** | Replace PII columns with vault tokens via `General.ops.PiiVault` | Lookup-before-insert; same plaintext → same token |
| **Parquet writer** | Write per-batch ZSTD-3 Parquet to network drive; atomic via inflight-rename pattern | Filename includes batch_id; UNIQUE constraint on registry; checksum verified post-write |
| **Parquet registry** | Track every file: location, tier, schema hash, integrity status | Idempotent INSERT; reconciler detects orphans / missing files |
| **Snowflake replicator** | Async mirror Parquet to Snowflake Iceberg stage | Snowflake `LOAD_HISTORY` dedup; registry tracks `SnowflakeStagePath` |
| **SCD2 promotion** | Compare current extraction against Bronze active for matching PKs; emit new versions | Hash compare on `_row_hash` vs `UdmHash`; conditional MERGE |
| **Bronze (SQL Server)** | Authoritative SCD2 history with dual-date contract | INSERT-first crash-safe; B-4 orphan cleanup; V-4 dedup detection |
| **Bronze (Snowflake mirror)** | Analytics target | Async COPY INTO from Parquet (or Iceberg federation) |
| **Idempotency ledger** | Track each pipeline step's status; short-circuit retries | UNIQUE on `(BatchId, Source, Table, EventType)` |
| **Process attestation** | PipelineEventLog, PipelineExtraction | Append-only, BatchId-keyed |
| **Delete audit** | DeleteEvaluationAudit per (date, batch_id) | Append-only |

## 3. Storage and Encoding Specs (binding)

### Parquet file specification

```
File size target:    128 MB compressed
Compression codec:   ZSTD level 3
Row group size:      128 MB OR 1,000,000 rows (first wins)
Page size:           1 MB
Statistics:          MIN/MAX/NULL_COUNT/DISTINCT_COUNT every column (mandatory)
Dictionary encoding: enabled (Polars default)
Sort order within:   (pk_columns ASC, _extracted_at DESC)
Filename pattern:    {source}_{table}_{batch_id}_{date}_part-{N}.parquet
                     {date} = target_date for large tables; '' for small
Partition layout:    \\archive\source={SourceName}\
                              table={TableName}\
                              year={YYYY}\month={MM}\day={DD}\
                              batch={BatchId}_part-{N}.parquet
```

### PII tokenization specification

- **Method**: in-house tokenization vault (`General.ops.PiiVault`) + provenance (`General.ops.PiiTokenProvenance`)
- **Tokens**: random GUID-derived `VARCHAR(40)` strings
- **Lookup index**: `(PiiType, SourceName, SHA-256(plaintext))` for O(log n) match
- **Determinism**: same plaintext on same source → same token (idempotency required for hash compare)
- **Provenance**: every (Token, SourceName, ObjectType, Database, Schema, Object, Column, FilePath) tuple gets a `PiiTokenProvenance` row on first observation; subsequent observations bump LastSeenBatchId/At + OccurrenceCount
- **Storage**: vault table protected via SQL Server TDE; access via stored procedure with role check + audit log
- **Decrypt audit**: every plaintext access logged to `General.ops.PiiVaultAccessLog` in same transaction
- **Cross-source isolation**: `SourceName` in the vault key prevents accidental cross-source PII matching unless explicitly desired
- **Cross-source query** (for auditor inquiries): JOIN PiiVault on PlaintextHash to find all tokens for a plaintext across sources, then JOIN PiiTokenProvenance for observation history

### Cross-server parity (D27)

All three servers (dev, test, prod) must be identical for failover (D29) to work. The parity invariants:

- Same RHEL release across all 3 servers
- Same Python version (3.12.11)
- Same library versions (frozen `requirements.txt`)
- Same systemd unit configuration with `MALLOC_ARENA_MAX=2` (W-4)
- Same TPM presence (or none on all)
- Same GPG keyring for `/etc/pipeline/credentials.json.gpg`
- Same network drive mount points (`/mnt/archive`)
- Same NTP/chrony time source
- Same monitoring agent set (Prometheus node exporter, log forwarder)
- Same cron files (only role differs at runtime via env config)

**Verification**: `tools/verify_server_parity.py` runs at pipeline startup and ad-hoc, comparing all three servers against this checklist. Drift triggers a deployment-blocker alert.

### Source DB ownership boundary (D28)

Oracle and SQL Server source DB outages, plus Bronze SQL Server HA, plus PiiVault HA, are owned by the database on-call team — not the pipeline team. Pipeline detects via `PipelineExtraction.Status='FAIL'`; trust gate (D13) suppresses deletes; pipeline auto-recovers when source returns. Pipeline runbooks scope only application-level recovery.

### Cooperative cancellation of stuck production runs (D33)

When test triggers failover for a stuck production run, test sets `PipelineExecutionGate.CancellationRequested = 1`. Production's heartbeat loop (every 5 min) checks the flag and self-terminates at the next table boundary — releases locks, flushes logs, sets `Status = 'CANCELLED'`, exits cleanly. Test waits up to 15 min for acknowledgment; on timeout, alerts operator and does NOT proceed automatically (avoids running two pipelines on stuck-but-alive production).

### Initial deployment, not migration (D34)

This is a greenfield deployment. No legacy Stage tables, no legacy CDC code in production, no cutover protocol. All migration scripts are `CREATE TABLE` from scratch. Phase 4 is per-table enablement, not cohort cutover. Phase 6 (cleanup of legacy) is removed from the plan.

### Hot/Warm/Cold tier classification (logical, pre-Snowflake)

- **hot**: created in last 90 days OR accessed in last 30 days. Network drive + future Snowflake stage.
- **warm**: 90 days–2 years. Network drive only; Snowflake reads via Iceberg external table on demand.
- **cold**: >2 years. Slower-tier network drive (or future cloud archive).
- **frozen**: future, >5 years. Cloud-archive blob; restore-on-demand.

A weekly `tools/parquet_tier_review.py` job updates `StorageTier` based on age + access. **No file movement** until storage pressure or cost demands it; just a logical label until then.

## 4. Idempotency Contract — the Master Invariant

> **Running the same pipeline batch twice with the same source state produces zero net writes the second time.**

Achieved via these layered guarantees, each in a different place:

1. **Source extraction** is deterministic for a given window because of TRUNC/CAST date boundaries.
2. **PII tokenization** is deterministic because the vault returns the existing token for a known plaintext.
3. **Hash computation** is deterministic across processes (polars-hash plugin, P2-1).
4. **Parquet write** is replay-safe via stage-check-exchange: write to `_inflight_*.parquet`, validate, atomic-rename when complete. Crash mid-write = orphan inflight file, no false data in registry.
5. **Idempotency ledger** short-circuits any step whose `(BatchId, Source, Table, EventType)` row is `Status='COMPLETED'`.
6. **SCD2 promotion** is idempotent because the hash compare against Bronze's `UdmHash` returns "unchanged" for any row whose source state is identical to its current Bronze version.
7. **Delete detection** is idempotent because evaluating the same (date, source, table, success-batch-id) tuple twice produces the same candidate set, and the verify-before-close + Bronze conditional MERGE produce zero net writes when state is unchanged.
8. **Snowflake replication** is idempotent because Snowflake's `COPY INTO ... FILES = ('...')` deduplicates against the file-load history.

Property-based test (Tier 2, see `06_TESTING.md`) asserts these compose: `pipeline(pipeline(state)) == pipeline(state)`.

## 5. Failure Recovery Model

Three failure categories, each recoverable from a higher-durability layer.

| Failure | Detection | Recovery path | RTO |
|---|---|---|---|
| SCD2 promotion crashes mid-run | Idempotency ledger row stuck `IN_PROGRESS` | Restart pipeline with same BatchId; ledger short-circuits completed steps, resumes the crashed one | minutes |
| Bronze duplicate-active row from crash | `validate_scd2.py` (R-5), V-4 post-SCD2 check | `repair_scd2.py duplicate_active_dedup` (R-6) | minutes |
| Bronze missing a version | `validate_parquet.py` Parquet↔Bronze drift | Replay SCD2 from Parquet snapshot — read Parquet, run SCD2 against Bronze; idempotent | hours |
| Bronze drifted long-term | Weekly P3-4 reconciliation | Heavy: rebuild Bronze from Parquet replay in batch_id order | days for 3B-row table |
| Network drive unavailable during extraction | OS-level error | Fail fast; operator restores network drive; same BatchId retry | hours |
| Parquet file corrupted | `parquet_verify.py` checksum mismatch | Re-extract from source for that date if within source retention; else mark file `Status='missing'`, document audit note | hours |
| Snowflake mirror lagging | Registry: `SnowflakeStagePath IS NULL` after N days | Async retry job; never blocks Bronze writes | bounded by Snowflake availability |
| **Production server down 1-2 days** | System monitor / freshness alert | **Server failover protocol** (see `05_RUNBOOKS.md`): promote test → prod | 2-4 hours |
| Pipeline missed dates within lookback | Hourly gap detector | Range scheduler auto-enqueues missing dates on next run | one cycle |
| Pipeline missed dates beyond lookback | Gap detector | Operator backfill via `tools/backfill.py`; documented in ExtractionGapLog | days |
| PII vault row missing for a token | SCD2 join failure on decrypt | Vault backups; restore from latest snapshot; document in audit log | hours |
| Source itself is wrong | P3-4 reconciliation flags drift | Source team fixes; pipeline backfills | days |
| Catastrophic loss of SQL Server Bronze | Disaster | Rebuild Bronze from full Parquet replay (network drive). Last-resort recovery path; testable | days for full replay |

**Key property**: no failure mode requires re-extracting from source for already-captured dates. Source may have changed by the time you notice. Parquet is the bottom of the recovery stack; tokenization vault and SQL Server backup are the secondary recovery substrates.

## 6. Audit and Compliance Posture

| Auditor question | Where the answer lives | At rest |
|---|---|---|
| "What was PK X's value on date Y?" | Bronze SCD2 `WHERE Y BETWEEN UdmSourceBeginDate AND UdmSourceEndDate` | Tokens for PII columns; metadata plaintext |
| "Show every observed source state on date Y" | Parquet registry → file → Polars/DuckDB/Snowflake read | Tokens for PII |
| "Was the pipeline run on date Y?" | PipelineEventLog | n/a |
| "Was every business date in the lookback window successfully extracted?" | PipelineExtraction; gaps shown by missing/Status=FAIL rows | n/a |
| "What deletes did we suppress on a FAILED date Y?" | DeleteEvaluationAudit | n/a |
| "What was X's SSN on day D" (authorized) | Bronze token → vault decrypt → audit log row written | Plaintext returned to authorized role only |
| "Was data X redacted under policy version V at write time?" | ParquetSnapshotRegistry.PiiPolicyVersion | n/a |
| "Has Bronze drifted from source over time?" | ReconciliationLog (P3-4 weekly) | n/a |

### Compliance alignment

- **PCI-DSS 4.0**: Tokenization satisfies Req 3.5 (rendering PAN unreadable) and reduces vault scope (Req 3.6); PiiVaultAccessLog satisfies key-management audit requirement.
- **SOC 2**: Access control on PiiVault via SQL Server roles + audit log on every read covers CC6.1/CC6.7.
- **GDPR Article 32 / Article 4(5)**: Pseudonymization satisfied by tokenization. Article 17 erasure = DELETE vault row + DELETE Bronze rows holding the token (or null tokens).

## 7. Operational Cadence

- **2x daily pipeline runs** (e.g. 06:00 and 18:00 local). Minimum 1x; 2x preferred for resilience.
- **Hourly gap detector** runs on the pipeline server.
- **Weekly P3-4 reconciliation** runs against Bronze for high-criticality tables.
- **Monthly lateness profiling** updates `LatenessProfile` per large table.
- **Quarterly DR rehearsal**: simulate multi-day production outage; promote test→prod; backfill; cutback.
- **Annual key/token rotation review** for the PII vault.

## 8. Cost Envelope

| Component | Annual cost (estimated) |
|---|---|
| Pipeline server (existing hardware) | $0 incremental |
| SQL Server licenses (existing) | $0 incremental |
| Network drive storage (existing) | $0 incremental |
| Snowflake — Bronze mirror storage (~10-15 GB compressed, large tables) | ~$3-6K |
| Snowflake — daily ingest compute | ~$15-25K |
| Snowflake — analytics + reconciliation compute | ~$5-10K |
| Snowflake — audit query compute (external Iceberg) | ~$1-3K |
| **Total Snowflake estimated** | **~$25-45K/yr** |
| **Budget cap** | **$120K/yr** |
| **Headroom** | **~$75-95K/yr** for growth, ad-hoc, unplanned |

The headroom is real and intentional. The architecture targets staying well under the cap during steady-state operation, with substantial buffer for backfills, reconciliations, growth, and unplanned spikes.
