# UDM Pipeline Phase A — Tokenization-Timing Reorder + Extraction-Timestamp Recording

**Date**: 2026-05-17
**Author**: parent agent (orchestrator role) responding to pipeline-lead direction 2026-05-17 "Proceed with your recommended next steps" + 3-agent brainstorm cohort findings
**Status**: 🟡 Draft v1 (focused; smaller scope than `UDM_PIPELINE_REDESIGN_PARQUET_SOURCE_EXACT_2026-05-17.md`)
**Supersedes**: `UDM_PIPELINE_REDESIGN_PARQUET_SOURCE_EXACT_2026-05-17.md` (the original ~600-line PME-inclusive plan, retired inline per pipeline-lead Phase A/B split direction)
**Pairs with**: Phase B (future plan; deferred — covers PME at-rest encryption + crypto-shredding for CCPA; gates on B-353/354/355/357/364 + legal counsel review per R5)
**Closes (gates Phase A R1)**: D115 + D116 lock | B-356 (D-NEW-D revision) | B-367 (DATETIME2 precision) | B-371 (canonical-doc cascade) | B-373 (Tier 1 source-exactness test)

---

## §0. Planning session provenance

**Skills invoked during this Phase A authoring session** (extends 2026-05-17 brainstorm session; same activation per CLAUDE.md hard rule 13):

| Skill / Agent | Invocation | Scope | Rationale |
|---|---|---|---|
| `udm-planning-session-startup` | 2026-05-17 (session start) | Always-mandatory | Activated 10 active + 8 on-demand skills earlier in session; inherited |
| `udm-brainstorm` | 2026-05-17 earlier | PS-1 ARCH | Original architecture options enumerated → led to original plan |
| `udm-design-reviewer` agent | 2026-05-17 (43rd cumulative; `a472e0575d28816bb`) | PS-1 mandatory | Architectural review of original plan → 🔴 BLOCK on 8 gaps → motivates this Phase A/B split |
| `udm-researcher` agent | 2026-05-17 (44th; `a54fcc995f87f919c`) | PS-1 mandatory | PME industry + KMS + Parquet metadata research → R6 persisted; informs D116 schema |
| Independent gap-check agent | 2026-05-17 (45th; `afad0935ac58cd263`) | always-mandatory | 6-category gap-check on original plan → 🔴 6/6 → drove Phase A/B split decision |
| `udm-decision-recorder` | 2026-05-17 (this session) | PS-8 mandatory | D115 + D116 opened as 🟡 Proposed in `03_DECISIONS.md` per this plan |
| `udm-progress-logger` | 2026-05-17 (this session) | always-mandatory §2.3 | 24 NEW B-Ns + 4 R-Ns + SE-N series + narrative updates per pipeline-lead direction "log the issues found"; **EXTENDED** 2026-05-17 at D56 2nd-pass remediation cycle: +14 NEW B-Ns (B-377-B-390) + R36 re-scored ⚪ 2 → 🟡 3 + R38 NEW + SE-9 + SE-10 + Phase A plan inline fixes per design-reviewer Agent 46 + gap-check Agent 47 cohort findings |
| `udm-checks-and-balances` | scheduled at attestation | PS-1 + PS-8 mandatory | 5-gate validation pending |
| `udm-edge-case-validator` | inline (this plan) | PS-1 implicit | SE1-SE7 invariants documented + SCD2-P1-* preservation verified |
| `udm-step-10-verifier` | scheduled at attestation | mandatory per CLAUDE.md hard rule 9 Step 12 | New module surfaces (none in Phase A — refactor-only) |
| `udm-gap-check` (skill) | scheduled at attestation | always-mandatory §2.3 | Independent gap-check on this Phase A plan (separate from the cohort gap-check on original plan) |
| `udm-post-edit-verification` | this commit | hard rule 14 | TEST + GAP + REVIEW cascade |

**Phase A scope is INTENTIONALLY NARROW** to satisfy user HARD REQUIREMENT immediately without big-bang risk per gap-check Agent 45's finding G6.12. PME / crypto-shredding / per-subject keys / D-NEW-B/C/E DEFERRED to Phase B (separate future plan).

---

## §1. Binding constraints (carried forward from user direction)

1. **Parquet = exact source data** (HARD REQUIREMENT). Parquet files MUST be byte-equivalent representations of source data at extraction. Only Parquet's structural-encoding transformations permitted.
2. **Extraction timestamp recording** (HARD REQUIREMENT addition). Must be able to tell WHEN raw data was extracted from source — answered via Parquet file-level `key_value_metadata` per D116 (R1+R7 research convergence).
3. **No PII tokenization in Parquet** during Phase A — tokenization happens AFTER Parquet write, in-memory before Bronze (per D115).
4. **Idempotency** (D15) — Parquet immutable; downstream pipeline deterministic per existing E-2 + SCD2-P1-* invariants.
5. **SCD2 invariants preserved** (per D2 + D18) — engine unchanged; reads in-memory tokenized DataFrame; verify-before-close + E-12 phantom-update detection unaffected.
6. **Greenfield project** (per `02_PHASES.md` L5) — no production Parquet to migrate; code refactor only.
7. **3B-row large table compatibility** — Phase A reorder doesn't change memory profile vs current architecture; in-memory tokenization already happens in current flow, just at different ordering.

---

## §2. Phase A scope

### §2.1 IN scope (must land for Phase A R1 close)

1. **Code refactor**: `orchestration/small_tables.py` + `orchestration/large_tables.py` reorder per D115 (Parquet write → in-memory tokenization → SCD2)
2. **`data_load/parquet_writer.py` extension**: accept extraction-timestamp parameters; embed in Parquet `key_value_metadata` footer per D116 schema
3. **`extract/connectorx_oracle_extractor.py` + siblings extension**: capture extraction-query-started-at + extraction-query-completed-at timestamps; return alongside DataFrame
4. **`ParquetSnapshotRegistry` schema evolution** (D92 forward-only ALTER): add `ExtractionQueryStartedAt DATETIME2(3) NULL` + `ExtractionQueryCompletedAt DATETIME2(3) NULL` columns
5. **DATETIME2(7) precision handling** (B-367): add `coerce_timestamps='us', allow_truncated_timestamps=True` to pyarrow write_table; document as accepted SE-2 exception
6. **ConnectorX DATE overflow defensive assertion** (B-366): pre-write check for Oracle DATE ≥ 2262-04-12; raise SourceExactnessError
7. **SE1-SE7 invariant enforcement** (D-NEW edge case series): schema-diff assertion + row-count assertion + control-character preservation + dtype 1:1 validation at Parquet write
8. **Tier 1 source-exactness test** (B-373): `tests/tier1/test_parquet_source_exactness.py` round-trip verification via Docker fixture
9. **Canonical doc cascade** (B-371): update `phase1/01c_data_flow_walkthrough.md` § 3 + `00_OVERVIEW.md` + `phase1/03_core_modules.md` + `phase1/06_observability_and_test_strategy.md` references per D93
10. **D115 + D116 lock** (after sign-off): flip 🟡 Proposed → 🟢 Locked; supersede D6 partially (timing clause)

### §2.2 OUT of scope (deferred to Phase B)

| Deferred item | Reason | Phase B B-N gate |
|---|---|---|
| Parquet Modular Encryption (PME) at-rest | pyarrow PME availability + KmsClient bridge + column-key granularity all unresolved | B-353 + B-354 + B-355 |
| Per-subject keys + `PiiSubjectKeys` table | DDL bug + granularity ambiguity unresolved | B-357 + B-359 |
| Crypto-shredding for CCPA | Legal counsel review required per R5 | (legal counsel B-N — open at Phase B kick-off) |
| CCPA-deletion SP per RB-10 extension for crypto-shred + orphan sweep | Depends on PME + PiiSubjectKeys | B-360 |
| RB-10 amendment for crypto-shredding | Depends on D-NEW-C lock | B-372 |
| New RB-N for crypto-shredding operator runbook | Depends on D-NEW-C lock | (Phase B prereq) |
| `PiiSubjectKeyAccessLog` table | Depends on D-NEW-E DDL | B-363 |
| Tier 4 crash boundary C16 | Depends on PME write path | B-365 |
| Snowflake federation under PME | Snowflake doesn't support PME (R5) | B-368 |
| New PII column retroactive PME procedure (SE-8) | Depends on PME | B-362 |
| PME performance benchmark at 3B-row scale | Depends on PME enabled | B-364 |

### §2.3 Open work (for Phase A B-N enumeration only — additive)

- **B-374** (🟡 Open; opened during pre-commit cross-ref remediation per `fe53b4c`): refactor `extract/` modules to capture + return extraction timestamps alongside DataFrame
- **B-375** (🟡 Open; opened during pre-commit cross-ref remediation per `fe53b4c`): orchestration-layer wiring of timestamps through to `parquet_writer`
- **B-376** (🟡 Open; opened during pre-commit cross-ref remediation per `fe53b4c`): test fixture migration if any test assumes current tokenize-before-Parquet ordering (audit at build time)

---

## §3. Architecture: source-exact Parquet + downstream tokenization (NO PME for Phase A)

### §3.1 Per-table flow (NEW ordering for Phase A)

```
T_start — Worker N picks up table T

[Step 1: Acquire table lock] — unchanged (sp_getapplock per P1-2)

[Step 2: Begin extraction + idempotency ledger] — unchanged

[Step 3: Execute extraction]
T+100ms: extractor.extract(...) returns:
  - df: Polars DataFrame (source dtypes preserved; source-exact data)
  - extraction_query_started_at: ISO-8601 UTC (captured at SELECT submission)
  - extraction_query_completed_at: ISO-8601 UTC (captured at DataFrame materialization)
T+5s: NO sanitization here (deferred to Step 4 in-memory)
      NO tokenization here (deferred per D115)
      NO _row_hash injection (deferred)
      NO _extracted_at column (deferred)

[Step 4 (NEW): Write source-exact Parquet — PRIMARY ARTIFACT]
T+5s: parquet_writer.write_snapshot(
        df=df,
        source_name=T.SourceName,
        source_table=T.SourceObjectName,
        target_date=target_date,
        extraction_query_started_at=extraction_query_started_at,
        extraction_query_completed_at=extraction_query_completed_at,
        pipeline_batch_id=batch_id,
        pipeline_version=pipeline_version,
      )
  - Stage-check-exchange (per D16)
  - SE1-SE7 invariant assertions per D-NEW edge case series:
    - SE1: column count = source column count
    - SE2: dtype 1:1 with documented mapping (DATETIME2(7) truncation exception per B-367)
    - SE4: NO additive columns
    - SE5: control characters preserved (NO sanitization)
    - SE6: row count = source row count (audit + key_value_metadata cross-check)
  - Parquet write with key_value_metadata schema per D116:
    udm_source_system, udm_source_schema, udm_source_table,
    udm_extraction_started_at, udm_extraction_ended_at, udm_parquet_written_at,
    udm_pipeline_batch_id, udm_pipeline_version,
    udm_encryption_config: "none" (Phase A; Phase B will be "pme_plaintext_footer_aes_gcm_v1"),
    udm_row_count
  - INSERT ParquetSnapshotRegistry (Status='created') with new ExtractionQueryStartedAt + ExtractionQueryCompletedAt columns
  - Async copy to VendorFile per D107
T+8s: ParquetSnapshotRegistry INSERT complete (Status='created')

[Step 5 (NEW): In-memory downstream pipeline — TOKENIZED PATH]
T+8s: df_in_memory = df  # After Parquet write completes (Step 4 T+8s), the original `df` reference can be mutated forward without affecting Parquet content because pyarrow conversion at §4.2 `polars_df.to_arrow()` already copies buffers to Arrow representation. Polars→Arrow conversion is the isolation boundary, NOT Polars COW semantics.
T+8s: sanitize_strings(df_in_memory)  # BCP-CSV-only; in-memory only; NOT applied to Parquet
T+8s: pii_tokenizer.tokenize_pii_columns(df_in_memory, T.PiiColumnList)  # per D115
      - Vault SP-1 unchanged (deterministic per D6 token-stability invariant)
      - PiiTokenizationBatch INSERT unchanged
T+9s: add_row_hash(df_in_memory)  # polars-hash SHA-256 on tokenized values; deterministic per vault SP-1
T+9s: df_in_memory's _extracted_at = extraction_query_completed_at (in-memory only; EXCLUDED from _row_hash inputs per existing ExcludeFromHash discipline)

[Step 6 (NEW): SCD2 promotion (Polars in-memory vs Bronze active)] — UNCHANGED per D2 + D18
T+12.5s: scd2/engine.run_scd2(
           table_config=T,
           df_current=df_in_memory_tokenized,  # tokens; deterministic hash per SP-1
           pk_columns=T.PrimaryKey,
           source_verifier_fn=closure,         # per D18 verify-before-close
           output_dir=...,
         )
         - 3-step atomic write per E-2
         - E-12 phantom-update ratio in SCD2_PROMOTION metadata
         - Hash stable across runs (tokens deterministic)

[Step 7: BCP CSV cleanup] — unchanged

[Step 8: Complete idempotency ledger step] — unchanged

[Step 9: Release table lock] — unchanged

[Step 10: TABLE_TOTAL summary] — unchanged
```

### §3.2 Comparison to current architecture

| Step | Current architecture | Phase A architecture | Phase B (deferred) |
|---|---|---|---|
| Extract | df returned from source | df + extraction timestamps returned | same as Phase A |
| Tokenize | BEFORE Parquet write (D6) | AFTER Parquet write (D115 supersedes D6 timing) | same as Phase A |
| Parquet write | Tokenized data | Source-exact data + key_value_metadata (D116) | + PME column encryption (D-NEW-B) |
| Sanitize | Before Parquet | In-memory only (post-Parquet) | same as Phase A |
| _row_hash | Before Parquet (as column) | In-memory only (post-Parquet) | same as Phase A |
| _extracted_at | Before Parquet (as column) | In-memory only + Parquet key_value_metadata (D116) | same as Phase A |
| SCD2 input | Tokenized in-memory df | Tokenized in-memory df (unchanged) | same as Phase A |
| Bronze content | Tokens (unchanged) | Tokens (unchanged) | Tokens (unchanged) |

**Net effect for Phase A**: Parquet contains source-exact plaintext PII; Bronze contains tokens (unchanged). Compensating control for Parquet plaintext: D103 13-layer security model + filesystem ACLs + `/debi` boundary + no-Claude-on-prod (R36 ⚪ 2).

---

## §4. Extraction-timestamp recording per D116

### §4.1 `key_value_metadata` schema (canonical for Phase A + B)

```
udm_source_system          : str  # "DNA" | "CCM" | "EPICOR"
udm_source_schema          : str  # e.g., "osibank"
udm_source_table           : str  # e.g., "ACCT"
udm_extraction_started_at  : str  # ISO-8601 UTC (e.g., "2026-05-17T02:00:00.123Z")
udm_extraction_ended_at    : str  # ISO-8601 UTC
udm_parquet_written_at     : str  # ISO-8601 UTC (post-fsync)
udm_pipeline_batch_id      : str  # GUID from PipelineBatchSequence
udm_pipeline_version       : str  # pipeline release tag (e.g., "udm-v2.3.1")
udm_encryption_config      : str  # "none" (Phase A) | "pme_plaintext_footer_aes_gcm_v1" (Phase B)
udm_row_count              : str  # str(int); SE-6 invariant cross-check
```

### §4.2 pyarrow API pattern (Phase A; per R6 research R1-2)

```python
import pyarrow as pa
import pyarrow.parquet as pq

# Convert Polars → pyarrow Table (copy-on-write; ~10-30% memory overhead at write)
arrow_table = polars_df.to_arrow()

# Attach key_value_metadata to schema
schema_with_meta = arrow_table.schema.with_metadata({
    "udm_source_system": source_name,
    "udm_source_schema": source_schema,
    "udm_source_table": source_table,
    "udm_extraction_started_at": extraction_query_started_at.isoformat() + "Z",
    "udm_extraction_ended_at": extraction_query_completed_at.isoformat() + "Z",
    "udm_parquet_written_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),  # set immediately before write; `datetime.utcnow()` deprecated in Python 3.12 per design-reviewer G4
    "udm_pipeline_batch_id": str(batch_id),
    "udm_pipeline_version": PIPELINE_VERSION,
    "udm_encryption_config": "none",
    "udm_row_count": str(len(polars_df)),
})
table_with_meta = arrow_table.replace_schema_metadata(schema_with_meta.metadata)
# CRITICAL per design-reviewer A5 + R6 R1-2: pyarrow `Table.cast(schema)` performs DTYPE CASTING,
# NOT schema metadata attachment. `replace_schema_metadata()` is the correct API to attach key_value_metadata.
# Verify post-write via `pq.read_schema(filepath).metadata` containing the expected keys (see B-356 Tier 0 test).

# Write with explicit precision handling per B-367
pq.write_table(
    table_with_meta,
    inflight_path,
    compression='zstd',
    compression_level=3,
    coerce_timestamps='us',
    allow_truncated_timestamps=True,  # B-367: SQL Server DATETIME2(7) → us truncation
)
```

### §4.3 ParquetSnapshotRegistry D92 forward-only ALTER

```sql
-- Migration: migrations/add_extraction_timestamps_to_parquet_registry.py
-- D92 forward-only ALTER + joint SchemaContract row INSERT per D40 + Round 7 § 4.5 pattern (per B-387)

BEGIN TRANSACTION;

ALTER TABLE General.ops.ParquetSnapshotRegistry
ADD ExtractionQueryStartedAt DATETIME2(3) NULL,
    ExtractionQueryCompletedAt DATETIME2(3) NULL;

INSERT INTO General.ops.SchemaContract (
    SourceName, ObjectName, ColumnName, ContractKey,
    DataType, IsNullable, EffectiveFrom, EffectiveTo,
    SupersededBy, AppliedBy, AppliedAt, MigrationScript
) VALUES
('General', 'ParquetSnapshotRegistry', 'ExtractionQueryStartedAt', 'd116_extraction_started_at_v1',
 'DATETIME2(3)', 1, SYSUTCDATETIME(), NULL, NULL,
 SUSER_SNAME(), SYSUTCDATETIME(), 'add_extraction_timestamps_to_parquet_registry.py'),
('General', 'ParquetSnapshotRegistry', 'ExtractionQueryCompletedAt', 'd116_extraction_completed_at_v1',
 'DATETIME2(3)', 1, SYSUTCDATETIME(), NULL, NULL,
 SUSER_SNAME(), SYSUTCDATETIME(), 'add_extraction_timestamps_to_parquet_registry.py');

COMMIT TRANSACTION;

-- Backfill for existing rows: NULL is acceptable (pre-D116 rows have no recorded timestamps)
-- New rows post-migration MUST be populated by parquet_writer
-- Idempotency per B-379: migration script wraps ALTER in TRY/CATCH on duplicate-column error; SchemaContract INSERT is keyed on ContractKey unique; re-run is no-op
```

### §4.4 Reading extraction timestamps (operator query)

```python
# Operator inspection without DB lookup (audit-grade per Pillar 1)
metadata = pq.read_metadata(parquet_file_path)
schema = pq.read_schema(parquet_file_path)
custom = schema.metadata  # dict[bytes, bytes]

extracted_at = custom[b"udm_extraction_started_at"].decode("utf-8")
source_table = custom[b"udm_source_table"].decode("utf-8")
row_count = int(custom[b"udm_row_count"].decode("utf-8"))
encryption_config = custom[b"udm_encryption_config"].decode("utf-8")

print(f"{source_table}: extracted at {extracted_at}, {row_count} rows, encryption={encryption_config}")
```

---

## §5. Code change inventory (Phase A R1 scope)

| File | Change | Effort | B-N |
|---|---|---|---|
| `extract/connectorx_oracle_extractor.py` | Capture extraction-query timestamps; return alongside DataFrame | ~20 lines | B-374 (new) |
| `extract/connectorx_sqlserver_extractor.py` | Same | ~20 lines | B-374 |
| `extract/oracle_extractor.py` (oracledb fallback) | Same | ~15 lines | B-374 |
| `extract/udm_connectorx_extractor.py` | Same | ~10 lines | B-374 |
| `data_load/parquet_writer.py` | Accept timestamps + pipeline_version; embed in key_value_metadata; SE1-SE7 assertions; B-367 truncation handling | ~80 lines | B-356 (D-NEW-D revision) |
| `migrations/add_extraction_timestamps_to_parquet_registry.py` | NEW migration; ALTER + SchemaContract row per D92 | ~50 lines | B-356 |
| `orchestration/small_tables.py` | Reorder: Parquet write BEFORE tokenization; pass timestamps through | ~30 lines | B-375 (new) |
| `orchestration/large_tables.py` | Same reorder; large-table per-day Parquet write also | ~30 lines | B-375 |
| `extract/oracle_extractor.py` | Defensive assertion for ConnectorX DATE overflow ≥ 2262-04-12 | ~10 lines | B-366 |
| `tests/tier1/test_parquet_source_exactness.py` (NEW) | Docker-fixture round-trip; SE1-SE7 verification | ~200 lines | B-373 |
| `tests/tier0/test_parquet_writer_metadata.py` (NEW) | Tier 0 smoke: key_value_metadata read-back from written file | ~50 lines | B-356 |
| `tests/tier0/test_orchestration_reorder.py` (NEW) | Tier 0 smoke: ordering assertion (Parquet write call BEFORE tokenize call) | ~30 lines | B-375 |
| `docs/migration/phase1/01c_data_flow_walkthrough.md` § 3 | Update flow diagram + step descriptions to reflect new ordering | ~80 lines | B-371 |
| `docs/migration/00_OVERVIEW.md` + `phase1/03_core_modules.md` + `phase1/06_observability_and_test_strategy.md` | D93 cross-doc cascade for tokenization-timing references | ~40 lines total | B-371 |
| `CLAUDE.md` Gotchas + Do-NOT rules | Add D116 key_value_metadata schema convention + B-367 DATETIME2 precision note | ~30 lines | B-371 + B-367 |
| `data_load/pii_tokenizer.py` | UNCHANGED (caller graph changes; module itself unchanged) | 0 lines | n/a |
| `scd2/engine.py` | UNCHANGED per D2 + D18 commitments | 0 lines | n/a |
| `data_load/parquet_replay.py` | **CRITICAL Phase A change** (per design-reviewer B8) — apply `sanitize_strings()` + `tokenize_pii_columns()` + `add_row_hash()` after reading plaintext Parquet and before passing to `scd2/engine.run_scd2()`. Replay path was implicit-tokenized in pre-Phase-A architecture (Stage table held tokens). Phase A reorder requires explicit replay-path tokenize-then-hash for SCD2 hash-stability + chain reconstruction. Defensive metadata fallback per B-380 for pre-Phase-A files. | ~100 lines | B-383 (CRITICAL) + B-380 |
| `tests/tier1/test_parquet_source_exactness.py` (NEW; extended scope) | Includes REPLAY-path acceptance test per SE-9: Parquet → tokenize → SCD2 chain produces IDENTICAL Bronze output to original-extraction → tokenize → SCD2 chain | +100 lines on top of B-373 base | B-373 (extended scope) |
| `data_load/parquet_writer.py` | **EXTENSION**: WRITER PATH SWITCH from Polars-native `df.write_parquet(use_pyarrow=False)` → pyarrow `pq.write_table()` to support `key_value_metadata` (Polars Rust writer does NOT support PME schema metadata). **Behavioral consequence**: SHA-256 hash of Parquet file CHANGES (different internal encoding between Polars-native vs pyarrow writer for identical data); `ParquetSnapshotRegistry.ContentChecksum` values from pre-Phase-A Polars-native files are NOT comparable to post-Phase-A pyarrow files. Greenfield project per `02_PHASES.md` L5 → no migration needed; operator awareness only. D45.2 contract preservation table: ZSTD-3 → `pq.write_table(compression='zstd', compression_level=3)`; statistics enabled → `pq.write_table(write_statistics=True)`; sort order → applied at in-memory step (NOT Parquet per SE-7); Hive partition layout preserved via `pq.write_to_dataset(partition_cols=...)`. **NEW**: `os.chmod(0o440)` after atomic rename per design-reviewer E1 (compensating control for R36 Phase A plaintext PII; current umask 0644 = world-readable security regression vs stated control). | additional ~50 lines on top of base | B-356 + R36 mitigation |
| `migrations/add_extraction_timestamps_to_parquet_registry.py` | EXTENDED: includes SchemaContract row INSERT per D40 + Round 7 § 4.5 joint migration pattern (per gap-check G3 9.l + B-387) | +30 lines on top of base | B-387 |
| **TOTAL** | | ~980 lines | 12 B-Ns (B-356/366/367/371/373/374/375/376/380/383/386/387) |

**Effort estimate**: ~3-4 cycles for Phase A R1 (vs original plan's 6-9 cycles for PME-inclusive version). Greenfield advantage preserved.

---

## §6. SCD2 + D18 compatibility (UNCHANGED)

All D2 + D18 commitments preserved:
- Stage layer dropped (D2)
- SCD2 reads in-memory DataFrame (D2)
- source_verifier_fn closure for verify-before-close (D18)
- E-12 phantom-update ratio in SCD2_PROMOTION metadata (D18)
- 3-step atomic write per E-2 (preserved)
- B-4 orphan cleanup (preserved)
- P0-8 INSERT-first then UPDATE (preserved)
- All SCD2-P1-* invariants preserved (SCD2-P1-a through P1-f all unchanged)

What changes for SCD2 input:
- `df_current` passed to `scd2/engine.run_scd2()` is now POST-tokenization (in-memory) instead of from Stage table
- Token-determinism invariant (per D6 vault SP-1): same source plaintext → same token → same `_row_hash` → SCD2 hash compare stable across runs
- **NEW invariant documented at SE-N canonical location (04_EDGE_CASES.md SE-9)**: `_extracted_at` EXCLUDED from `_row_hash` inputs (it's a pipeline artifact, NOT source data; equivalent to `ExcludeFromHash` treatment per SCD2-R10.2). This invariant is load-bearing for SCD2 hash-stability across happy-path runs vs replay-path runs — replay path SYNTHESIZES `_extracted_at` from `ParquetSnapshotRegistry.CreatedAt` (NOT from current wall-clock), preserving hash-stability for SCD2 chain reconstruction.

---

## §7. Compensating controls for Phase A plaintext PII in Parquet (R36 mitigation)

Phase A writes plaintext PII to Parquet (no PME — that's Phase B). Compensating controls per D103 13-layer security model:

| Layer | Control | Application to Phase A Parquet |
|---|---|---|
| 1 | `/debi` working-directory boundary | Parquet on H drive (NOT in `/debi`); Claude on dev CANNOT read |
| 2 | `.claudeignore` | H drive paths not in `/debi`; not reachable |
| 3 | `.claude/settings.local.json` permissions.deny | H drive paths denied even if Claude attempted Read |
| 4 | No-creds-on-dev | Parquet plaintext PII visible only to authorized pipeline service account |
| 5 | POSIX + NTFS ACLs | H drive directory mode-restricted to pipeline group |
| 6 | File-mode 0440 | Parquet files read-only to authorized group; no world-read |
| 7 | GPG-at-rest | (Phase B will add PME per D-NEW-B; Phase A relies on filesystem ACL only) |
| 8 | OS-native vaults | (Not applicable to Parquet; applies to credentials) |
| 9 | auditd | Audit watch on Parquet directories logs all access |
| 10 | systemd-creds + TPM2 | (Phase B will use for PME master KEK; Phase A doesn't use) |
| 11 | SELinux enforcing | RHEL prod servers; mandatory access control |
| 12 | Network isolation | Parquet directories not network-exported beyond replication path |
| 13 | Image-bake check | test/prod RHEL has NO Claude installed |

**Risk posture**: Equivalent to current `/etc/pipeline/.env` plaintext credentials posture per D103. R36 (Low × Medium = 2 ⚪) acceptable for Phase A. Phase B PME closes the compliance gap per R5 EDPB Guidelines 02/2025 + crypto-shredding pattern.

---

## §8. Phase A R1 migration prerequisites

### §8.1 Gate-blockers (must close BEFORE Phase A R1 build starts)

1. **D115 locked** (PII tokenization timing reorder partially supersedes D6) — pipeline-lead sign-off required
2. **D116 locked** (extraction-timestamp via key_value_metadata + 2 new ParquetSnapshotRegistry columns) — pipeline-lead sign-off required
3. **D6 supersession crumb added to D6 body** — leading badge flip 🟢 → ⚫ Superseded (partial; with link to D115); tracked per B-384
4. **B-356 closed** (D-NEW-D revision; satisfied by D116 lock — this becomes a same-cycle closure)
5. **B-371 cross-doc cascade complete** OR explicitly scoped to land alongside Phase A R1 build
6. **Compliance determination gate** (per design-reviewer Agent 46 Section F4 BLOCK + R38 NEW 2026-05-17) — **pipeline-lead or data governance team confirms Phase A plaintext-PII-in-Parquet posture is permissible under applicable regulation and organizational data policy, WITH DOCUMENTATION**. Required because Phase A introduces a new PII-at-rest surface that did not exist before (pre-Phase-A Parquet has NO plaintext PII; SCD2 Bronze has tokens). Plaintext-PII window estimated 3-6 months until Phase B PME lands (Phase B gated on B-353+B-354+B-355+B-357+B-364+B-389 external legal counsel review weeks-to-months). Without compliance attestation, Phase A deployment risks immediate-rollback if compliance finding surfaces post-deployment. Pipeline subject to financial-services data classification policy + CCPA "reasonable security" standard + potential PCI DSS Requirement 3.5 if card data present in DNA. Acceptance: written attestation from pipeline-lead OR data governance team citing applicable regulation review.
7. **R36 compensating controls verified implemented** (R36 currently 🟡 3; returns to ⚪ 2 when all 3 verified): (a) `os.chmod(0o440)` after Parquet atomic rename in `parquet_writer.py` (per design-reviewer E1); (b) auditd watch rule on H drive Parquet directory root per B-381 (per design-reviewer E2); (c) backup tape encryption verified on H drive's storage infrastructure (per design-reviewer E5). Without these 3 controls, D103 Layer 6 / Layer 9 protections claimed in Phase A §7 are paper-only.
8. **B-353 (pyarrow PME RHEL availability spike)** — even though Phase A doesn't use PME, the spike confirms Phase B viability and informs Phase A→B timeline (R38 risk-window quantification)
9. **B-377 (Polars Decimal128 → Parquet round-trip verification)** on production version (per design-reviewer A3); document as SE-2 exception if unfixed; defensive assertion if affecting source-exactness for DNA/EPICOR NUMBER columns

### §8.2 Phase A R1 build steps (sequenced)

1. Open B-374 + B-375 + B-376 in BACKLOG.md
2. Author DDL migration script (`migrations/add_extraction_timestamps_to_parquet_registry.py`)
3. Author `parquet_writer.py` extension (timestamps + key_value_metadata)
4. Author Tier 0 + Tier 1 tests (parquet_writer_metadata + source_exactness + orchestration_reorder)
5. Author orchestration reorder (small_tables + large_tables)
6. Author extractor timestamp capture (4 extractors)
7. Run full Tier 0 + Tier 1 pytest cohort; verify SE1-SE7 round-trip passes
8. Author canonical-doc cascade per B-371
9. Round close-out cascade per `udm-round-closeout`

### §8.3 Phase A R1 acceptance criteria

- All Tier 0 + Tier 1 + property + regression tests pass (current baseline + new Phase A tests)
- ACCT pilot (per D104) runs end-to-end with source-exact Parquet + tokenized Bronze
- Tier 1 source-exactness round-trip test (B-373) passes for ACCT
- Operator can read extraction timestamps from Parquet file without DB lookup (D116 self-describing test)
- ParquetSnapshotRegistry has populated `ExtractionQueryStartedAt` + `ExtractionQueryCompletedAt` columns
- 1-week soak on dev (no regressions in CDC + SCD2 + verify-before-close + E-12)

---

## §9. D-N + B-N + R-N + SE-N cross-reference

### §9.1 D-Ns (this plan motivates)

- **D115** 🟡 Proposed (this plan) — PII tokenization timing reorder; partially supersedes D6
- **D116** 🟡 Proposed (this plan) — Extraction-timestamp via Parquet `key_value_metadata` plaintext-footer

### §9.2 D-Ns deferred to Phase B

- **D-NEW-B** — PME at-rest encryption (gates on B-353 + B-354 + B-355)
- **D-NEW-C** — Crypto-shredding via PME key destruction (gates on legal counsel review per R5)
- **D-NEW-E** — `PiiSubjectKeys` + `PiiSubjectKeyShredLog` + `PiiSubjectKeyAccessLog` DDL (gates on B-357 + B-359)

### §9.3 B-Ns gating Phase A R1

| B-N | Title | Closure target |
|---|---|---|
| B-356 | Revise D-NEW-D extraction-timestamp design (satisfied by D116 lock) | Phase A R1 prereq |
| B-366 | ConnectorX Oracle DATE overflow defensive assertion | Phase A R1 build |
| B-367 | DATETIME2(7) precision exception (`allow_truncated_timestamps=True`) | Phase A R1 build |
| B-371 | `01c_data_flow_walkthrough.md` § 3 + cascade per D93 | Phase A R1 build |
| B-373 | Tier 1 source-exactness test | Phase A R1 build |
| B-370 | Phase A/B split (this plan satisfies) | THIS plan |
| B-374 | Extractor timestamp capture refactor | Phase A R1 build (open at build start) |
| B-375 | Orchestration timestamp wiring | Phase A R1 build (open at build start) |
| B-376 | Test fixture migration audit | Phase A R1 build (open at build start) |

### §9.4 R-Ns Phase A scope

- **R36** ⚪ 2 (NEW; plaintext PII in Phase A Parquet; compensating D103) — accepted for Phase A; closes when Phase B PME lands
- **R37** ⚪ 1 (NEW; Parquet metadata schema drift) — mitigated by `udm_pipeline_version` key + B-373 test

### §9.5 SE-N edge case series (Phase A binding invariants)

- SE1 (column count) / SE2 (dtype 1:1) / SE3 (value byte-equivalence) / SE4 (no additive columns) / SE5 (control char preservation) / SE6 (row count) / SE7 (row order) — all enforced at Parquet write per §3.1 Step 4
- SE8 (new PII column retroactive PME) — deferred to Phase B (B-362)

---

## §10. Phase B preview (DEFERRED — separate future plan)

Phase B will layer the following ON TOP of Phase A (additive; Phase A's D115/D116 remain valid; the original-plan "D-NEW-A" candidate IS NOW D115; the original-plan "D-NEW-D" candidate IS NOW D116; only "D-NEW-B" / "D-NEW-C" / "D-NEW-E" remain as Phase B candidate D-N numbers TBD):

1. **Parquet Modular Encryption (PME)** per D-NEW-B candidate — column-level AES-GCM via pyarrow; `plaintext_footer=True` per R6 R1-4
2. **Per-subject keys + KmsClient bridge** per D-NEW-E candidate — `PiiSubjectKeys` table; TPM2-sealed master KEK wraps per-subject DEKs; custom `PyArrowKmsClient` implementation per B-355
3. **Crypto-shredding for CCPA** per D-NEW-C candidate — destroy subject's DEK = data mathematically unrecoverable per R5 industry pattern
4. **CCPA-deletion SP per RB-10 extension** per B-360 — single-transaction crypto-shred + B-4 orphan sweep
5. **RB-10 amendment** per B-372 — operator runbook for crypto-shredding
6. **`PiiSubjectKeyAccessLog`** per B-363 — audit trail for legitimate PME decryption
7. **PME-EC1-6 edge cases** — generation race / decrypt failure / SubjectIdentifier scope / shred-and-restore / metadata tampering / schema drift mid-day
8. **PME performance benchmark** per B-364 — 3B-row replay validated BEFORE production cutover
9. **Tier 4 crash boundary C16** per B-365 — PME key generation crash injection
10. **Snowflake federation handling** per B-368 — Option A (decrypt-before-COPY) since Snowflake doesn't support PME per R5

**Phase B gate-blockers** (must close BEFORE Phase B kick-off):
- B-353 (pyarrow PME RHEL availability spike) — 🔴 6
- B-354 (PME column-key granularity redesign) — 🔴
- B-355 (PyArrowKmsClient bridge design) — 🔴
- B-357 (PiiSubjectKeys DDL fix) — 🔴
- Legal counsel review of crypto-shredding per R5 — 🔴

---

## §11. Sign-off readiness

### §11.1 Pre-sign-off actions (this commit)

- [x] Phase A plan authored
- [x] §0 provenance section
- [x] R6 research persisted (`_research/r6-pme-extraction-time-2026-05-17.md`)
- [x] Original plan inline-superseded (header added per §11.3 below)
- [x] D115 + D116 opened as 🟡 Proposed in 03_DECISIONS.md
- [x] B-353 through B-390 opened in BACKLOG.md (24 from initial cohort at `7cb7659` + 14 from D56 2nd-pass remediation this commit)
- [x] R34-R37 opened in RISKS.md
- [x] SE1-SE8 added to 04_EDGE_CASES.md (NEW SE-N series)
- [x] CURRENT_STATE L7 + HANDOFF §14 narrative prepended
- [x] _validation_log.md event row appended
- [ ] Spawn independent gap-check on THIS Phase A plan (per D55+D56 second-pass)
- [ ] Pipeline-lead sign-off on D115 + D116 lock

### §11.2 Pre-Phase-A-R1-execution actions

- [ ] D115 locked
- [ ] D116 locked
- [ ] D6 supersession crumb added (partial supersession; timing clause only)
- [ ] B-370 closed (this plan satisfies)
- [ ] B-374 + B-375 + B-376 opened in BACKLOG.md

### §11.3 Original plan supersession

The original plan `docs/migration/UDM_PIPELINE_REDESIGN_PARQUET_SOURCE_EXACT_2026-05-17.md` is **SUPERSEDED INLINE** by this Phase A plan per pipeline-lead direction 2026-05-17. A supersession header will be added to the original plan top pointing to:
- THIS Phase A plan (active; Phase A scope)
- Future Phase B plan (TBD; covers PME + crypto-shredding deferred from original)

Reason for supersession:
- 3-agent gap-check cohort returned 🔴 BLOCK on 8 architectural gaps in original plan
- Original plan conflated 2 independent changes (timing reorder + at-rest encryption) into big-bang
- Phase A/B split reduces immediate risk while satisfying user hard requirement
- ~80% of blocker scope eliminated from Phase A

---

## §12. Cross-references

- `docs/migration/UDM_PIPELINE_REDESIGN_PARQUET_SOURCE_EXACT_2026-05-17.md` (ORIGINAL; superseded by THIS Phase A plan)
- `docs/migration/_research/r6-pme-extraction-time-2026-05-17.md` (Phase B grounding; informs D116 schema for Phase A)
- `docs/migration/_research/r5-ccpa-parquet-replay-legal-2026-05-17.md` (Phase B legal grounding)
- `docs/migration/D2_GAP_RESOLUTION_PLAN_2026-05-17.md` (D2 implementation gaps; orthogonal to Phase A scope; remain valid)
- `docs/migration/03_DECISIONS.md` D2 + D6 (partially superseded by D115) + D15 + D16 + D18 + D25 + D102 + D103 + D107 + D110 + D115 (NEW 🟡) + D116 (NEW 🟡)
- `docs/migration/04_EDGE_CASES.md` SE-N series (NEW SE1-SE7 for Phase A; SE8 deferred)
- `docs/migration/RISKS.md` R34-R37 (NEW; R34/R35 Phase B-related; R36/R37 Phase A-active)
- `docs/migration/BACKLOG.md` B-353 through B-390 (38 NEW B-Ns total: 24 from initial cohort + 14 from 2nd-pass remediation; Phase A-active: B-356/366/367/370/371/373/374/375/376/377/379/380/381/382/383/384/385/386/387/390; Phase B: remainder; B-388 + B-389 = forward-prevention discipline)
- CLAUDE.md hard rule 14 anti-rationalization clause — Phase A/B split satisfies "explicit anti-trigger claim with justification" via gap-check Agent 45 cohort evidence
- `phase1/01c_data_flow_walkthrough.md` § 3 (current canonical flow; will be cascaded per B-371)
- `data_load/parquet_writer.py` (extension target; ~80 LOC change)
- `orchestration/small_tables.py` + `orchestration/large_tables.py` (refactor targets; ~30 LOC each)
- `extract/*.py` (timestamp capture; ~65 LOC total across 4 modules)
- `scd2/engine.py` (UNCHANGED per D2 + D18; sanity-check verified)
- `data_load/pii_tokenizer.py` (UNCHANGED; caller graph changes only)

---

**Awaiting**:
1. Pipeline-lead sign-off on D115 + D116 lock
2. Independent gap-check on THIS Phase A plan (D55+D56 second-pass)
3. Phase A R1 build start authorization
