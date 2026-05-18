# UDM Pipeline Redesign — Source-Exact Parquet (Hard Requirement) — ⚫ SUPERSEDED BY PHASE A/B SPLIT 2026-05-17

> **⚫ SUPERSEDED INLINE 2026-05-17** by Phase A/B split per pipeline-lead direction "Proceed with your recommended next steps + log the issues found." The 3-agent gap-check cohort (`a472e0575d28816bb` design-reviewer + `a54fcc995f87f919c` researcher + `afad0935ac58cd263` gap-check) returned 🔴 BLOCK on 8 architectural gaps in this plan (PME column-key file-vs-row granularity / pyarrow PME availability / TPM2≠KMS / SubjectIdentifier DDL bug / crypto-shred+B-4 orphan interaction / per-subject PME no published case study / Snowflake doesn't support PME / arithmetic+citation drift Pitfall #9.k+9.l in plan body). This plan conflated two independent changes (tokenization-timing reorder + at-rest PME encryption) into one big-bang.
>
> **Replacement plans**:
> - **Phase A** (active): `docs/migration/UDM_PIPELINE_PHASE_A_TOKENIZATION_REORDER_2026-05-17.md` — tokenization-timing reorder + extraction-timestamp recording via Parquet `key_value_metadata` ONLY. No PME. ~3-4 cycles. Satisfies user HARD REQUIREMENT immediately. D115 + D116 lockable now.
> - **Phase B** (deferred): future plan — Parquet Modular Encryption (PME) layer + per-subject keys + crypto-shredding for CCPA. Gates on B-353 (pyarrow PME RHEL availability) + B-354 (column-key granularity redesign) + B-355 (KmsClient bridge) + B-357 (PiiSubjectKeys DDL fix) + legal counsel review per R5.
>
> **Research artifact (still valid)**: `docs/migration/_research/r6-pme-extraction-time-2026-05-17.md` (24 primary-source citations; informs both Phase A `key_value_metadata` schema + Phase B PME design).
>
> **What stays valid from this plan body below** (for Phase A reference):
> - §3.3 SE-1 through SE-7 invariants → adopted into Phase A as SE-N edge case series
> - §4.1 + §4.2 PME industry-pattern enumeration → Phase B reference (NOT Phase A scope)
> - §7 crypto-shredding design → Phase B reference (NOT Phase A scope)
> - §9 D-N enumeration → D115 + D116 split out for Phase A; D-NEW-B/C/E deferred to Phase B
>
> **What is REJECTED from this plan body below**:
> - §4.2 PME column-key pseudocode (per-row granularity) — architecturally invalid; PME column-keys are file-scoped; redesign per B-354 before Phase B locks D-NEW-B
> - §10.4 effort estimate 6-9 cycles — light; Phase B alone is 6-9 cycles; this plan would have been 12-18 cycles realistic
> - Greek-letter B-N convention (B-N-α through B-N-ν) — anti-pattern; replaced with numeric B-353 through B-373 in BACKLOG.md
> - §7.3 arithmetic claims "5 of 11 gaps" + "6 R5-research-surfaced gaps" + "4 of 6" — unsourced; flagged by gap-check Agent 45 as Pitfall #9.k recurrence
> - §2.1 citation "§ 3 Step 4-5" — off-by-one against `01c_data_flow_walkthrough.md` § 3 (tokenization is Step 3, Parquet is Step 4); flagged as Pitfall #9.l
>
> **Audit trail**: see `_validation_log.md` 2026-05-17 entry "Source-Exact Parquet Redesign 3-Agent Brainstorm Cohort + Phase A/B Split" for full agent verdicts + remediation rationale.
>
> **The plan body below is preserved verbatim for audit context but should NOT be cited as active spec.**

---

**Date**: 2026-05-17
**Author**: parent agent (orchestrator role) responding to user-direction "Parquet files must be the exact copy of the data that was extracted from the source at the time of the data pipeline run. Come up with a new plan for our data pipeline."
**Status**: ⚫ Superseded 2026-05-17 by Phase A/B split — was 🟡 Draft v1
**Supersedes**: tokenization-at-extraction flow (per `01c_data_flow_walkthrough.md` § 3 Step 5 ordering); D6 (PII tokenization timing) requires supersession D-N
**Parent constraint**: USER HARD REQUIREMENT — Parquet = exact-byte-equivalent source data at extraction moment; NO alteration whatsoever beyond what's structurally required for Parquet format itself

---

## §0. Planning session provenance

**Skills invoked during this redesign session** (extends prior `udm-planning-session-startup` session; same activation per CLAUDE.md hard rule 13):

| Skill | Invoked at | Scope reference | Rationale |
|---|---|---|---|
| `udm-planning-session-startup` | 2026-05-17 (prior session start) | Always-mandatory entry skill | 10-active + 8-on-demand skill set previously approved by user |
| `udm-decision-recorder` | DEFERRED to next cycle | PS-8 mandatory | D6 supersession + new D-Ns for PME + tokenization timing |
| `udm-design-reviewer` (agent) | scheduled post-plan-author | PS-1 + PS-8 mandatory | Independent architectural review |
| `udm-checks-and-balances` (skill) | scheduled at plan attestation | PS-1 + PS-8 mandatory | 5-gate validation |
| `udm-edge-case-validator` (skill) | inline (this plan) | PS-1 implicit | SCD2-P1-* + new edge cases under encrypted-Parquet |
| `udm-researcher` (agent) | scheduled post-plan-author | PS-1 mandatory | Parquet Modular Encryption (PME) industry patterns + KMS choice grounding |
| `udm-gap-check` (skill) | scheduled at plan attestation | always-mandatory §2.3 | Independent gap-check |
| `udm-progress-logger` (skill) | 2026-05-17 (throughout) | always-mandatory §2.3 | Tracker updates |
| `udm-post-edit-verification` (skill) | this commit | always-mandatory §2.3 per hard rule 14 | TEST + GAP + REVIEW cascade |

**Prior plan deliverables superseded** (cite as "earlier-in-session" not "outdated"):
- `docs/migration/D2_EXECUTION_PLAN_PARQUET_DIRECT_SCD2_2026-05-17.md` — D2 approach correct; tokenization-step ordering wrong per new hard requirement
- `docs/migration/D2_GAP_RESOLUTION_PLAN_2026-05-17.md` — 11 gaps still valid; G1 design (Option A4 time-aware replay) requires redesign because CCPA-deletion-as-Flag=2-synthesis ASSUMED tokenization-at-Parquet; new path = crypto-shredding via PME key destruction (simpler + more compliant)
- `docs/migration/_research/r5-ccpa-parquet-replay-legal-2026-05-17.md` — R5 findings even MORE relevant: validates crypto-shredding via PME key destruction as EDPB-irreversibility-compliant (vs vault-soft-delete which R5 found non-compliant)

---

## §1. Binding constraints (user-direction 2026-05-17 HARD REQUIREMENT)

1. **Parquet = exact source data**: Parquet files MUST be byte-equivalent representations of source data at extraction time. NO alterations whatsoever beyond what's structurally required for Parquet format itself (i.e., the only acceptable "transformations" are the column-type encoding semantics of Parquet itself).

2. **No PII tokenization at Parquet write**: tokenization must happen AFTER Parquet write, in-memory before downstream consumers (Bronze SCD2, Snowflake mirror).

3. **No string sanitization**: control characters (`\t \n \r \x00`) MUST be preserved in Parquet (Parquet handles them natively; sanitization is BCP-only concern).

4. **No additive metadata columns**: `_row_hash`, `_extracted_at` NOT in Parquet. These computed on-the-fly during downstream consumer reads.

5. **No dtype coercions beyond semantic-preserving Polars defaults**: Oracle DATE → Parquet timestamp(us) is OK if value-preserving; BIT → Int8 documented in side-channel; type changes that lose information PROHIBITED.

6. **Inherited from prior planning** (still binding):
   - Idempotency (D15) — Parquet immutable; replay deterministic
   - Months-old Parquet must be replayable for SCD2 corruption recovery
   - Blob storage = source of truth; UDM_Bronze = downstream consumer
   - 3B-record large table handling required
   - H drive primary; VendorFile secondary per D107

---

## §2. Current architecture conflicts (what must change)

### §2.1 Conflict map

| Current behavior | Per user hard requirement | Resolution |
|---|---|---|
| `pii_tokenizer.tokenize_pii_columns(df)` called BEFORE `parquet_writer.write_snapshot()` (per `01c_data_flow_walkthrough.md` § 3 Step 4-5) | Tokenization happens AFTER Parquet write | **REORDER**: extract → Parquet write → load Parquet → tokenize in-memory → Bronze SCD2 |
| `sanitize_strings()` applied before BOTH BCP CSV write AND Parquet write | NO sanitization in Parquet | **SPLIT path**: sanitize only in BCP CSV branch; Parquet branch writes raw |
| `_row_hash` (polars-hash) injected as column BEFORE Parquet write | NO additive columns in Parquet | **DEFER**: compute `_row_hash` on-the-fly during SCD2 read of Parquet OR store in sidecar metadata file |
| `_extracted_at` injected as column BEFORE Parquet write | NO additive columns in Parquet | **DEFER**: extraction timestamp recorded in `ParquetSnapshotRegistry` (already tracked); not in Parquet itself |
| D6 (PII tokenization at extraction) — LOCKED 🟢 | Conflicts with new requirement | **SUPERSEDE** D6 via new D-N: "PII tokenization happens post-Parquet-write, in-memory before Bronze" |
| Plaintext PII would land in Parquet under naive reorder | D103 security model + R5 EDPB 01/2025 + GDPR/CCPA compliance | **ADD encryption at rest**: Parquet Modular Encryption (PME) with column-level AES-GCM; per-subject key management for crypto-shredding |
| Replay-time CCPA filter (G1 Option A4) requires synthesized Flag=2 rows | Vault-soft-delete is NOT EDPB-compliant per R5 | **REPLACE with crypto-shredding**: CCPA deletion = destroy subject's PME key; subject's Parquet PII column rows become permanently unreadable; SIMPLER + MORE COMPLIANT than Flag=2 synthesis |

### §2.2 Decisions to supersede (D-N supersession required per D92 forward-only)

- **D6 supersession** (tentative-future-D-N — let's call this **D-NEW-A**): "PII tokenization happens AFTER Parquet write — in-memory during pipeline downstream consumer steps (Bronze SCD2 read; Snowflake federation). Parquet itself contains source-plaintext PII encrypted via Parquet Modular Encryption (PME) per D-NEW-B."

- **D6 supersession rationale**: User hard requirement Parquet = source-exact data. D6's tokenization-at-extraction violates this. Tokenization timing reorder + encryption at rest preserves D6's compliance intent while honoring source-exactness requirement.

### §2.3 New D-N candidates

- **D-NEW-B**: "Parquet Modular Encryption (PME) for at-rest PII protection; per-subject column-level AES-GCM keys with TPM2-sealed master key per D64 + D102 + D103 alignment"

- **D-NEW-C**: "Crypto-shredding via PME subject-key destruction is the canonical CCPA right-to-deletion mechanism (replaces vault-soft-delete pattern of D26 + RB-10); satisfies EDPB 01/2025 irreversibility standard per R5 research"

- **D-NEW-D**: "_row_hash + _extracted_at computed on-the-fly during downstream consumer reads of Parquet; NOT stored in Parquet; `_extracted_at` recorded in `ParquetSnapshotRegistry.CreatedAt` (already canonical)"

---

## §3. New architecture: source-exact raw Parquet + downstream tokenization

### §3.1 Architecture diagram

```
Source (Oracle / SQL Server)
        ↓ ConnectorX / oracledb
        ↓ Polars DataFrame (source dtypes preserved)
        ↓
   [PARALLEL FORK]
        ├──→ RAW Parquet write (per D-NEW-B)
        │    - Source-exact data, NO alterations
        │    - PII columns encrypted via PME (per-subject AES-GCM keys)
        │    - Non-PII columns plaintext (still Parquet binary encoding)
        │    - NO _row_hash, NO _extracted_at, NO sanitization
        │    - Stage-check-exchange per D16
        │    └──→ ParquetSnapshotRegistry INSERT (Status='created')
        │    └──→ VendorFile async-replicated copy per D107
        │
        ├──→ In-memory downstream pipeline:
        │    1. Polars sanitize_strings() (BCP-prep only; in-memory; NOT Parquet)
        │    2. pii_tokenizer.tokenize_pii_columns(df_in_memory) per D-NEW-A
        │    3. Compute _row_hash + _extracted_at in-memory
        │    4. SCD2 promotion (scd2/engine.run_scd2) per D2 + D18
        │    5. 3-step atomic write per E-2
        │    6. UDM_Bronze contains tokenized + hashed data (current pattern preserved)
        │
        └── NO Stage layer (per D2)
        
Replay path (SCD2 corruption recovery):
        ↓
   Operator invokes tools/scd2_replay_smoke.py --source X --table Y --start-date Y-M-D --end-date Y-M-D
        ↓
   replay_parquet_range(source, table, start_date, end_date)
        ↓
   For each snapshot in BatchId ASC order:
     1. Read raw Parquet
     2. PME decrypt PII columns (KMS provides subject keys)
        - CCPA-deleted subjects: key destroyed; decryption fails; row effectively deleted (crypto-shredding per D-NEW-C)
        - Active subjects: decrypt OK; row proceeds normally
        - SOX/GLBA legal-hold subjects: decrypt OK (key preserved); row proceeds normally
     3. Tokenize in-memory via vault SP-1
     4. Compute _row_hash + _extracted_at
     5. Standard SCD2 promotion per scd2/engine.run_scd2_targeted
     6. Per-day IdempotencyLedger checkpoint
```

### §3.2 Layer responsibilities (post-redesign)

| Layer | Job | Source-exactness check | Compliance mechanism |
|---|---|---|---|
| Source extraction | Polars DataFrame from source DB; preserve source dtypes | Polars schema mirrors source schema | TRUNC dates per W-3; deterministic extraction |
| **Parquet writer (NEW BEHAVIOR)** | Write Polars DataFrame to Parquet with PME on PII columns; NO alterations to data | Round-trip test: read Parquet (with decryption) → compare to source DB extraction at same time → byte-equivalent | PME AES-GCM column-level encryption per D-NEW-B + D102 |
| ParquetSnapshotRegistry | Track every file: location, tier, schema, integrity, encryption-key-id | Unchanged per D25 | Idempotent INSERT |
| **In-memory tokenizer (TIMING SHIFTED)** | Tokenize PII columns AFTER Parquet read (or after extraction for happy path) | N/A — operates on in-memory copy, not Parquet | Vault SP-1 unchanged; D26 vault provenance unchanged; D102 AES-256-GCM unchanged for vault encryption |
| SCD2 promotion | Hash-compare in-memory tokenized DataFrame vs Bronze active | Hash includes tokens (downstream representation); unrelated to Parquet source-exactness | Existing pattern preserved |
| UDM_Bronze | Tokenized + SCD2-versioned data; regulator-truth | Bronze unchanged (still tokens) | Per D2 + D18 unchanged |
| **Replay engine (NEW: CCPA filter via PME key state)** | Read Parquet → PME decrypt → tokenize → SCD2 | Crypto-shredded subjects: decryption fails → row excluded | D-NEW-C crypto-shredding via PME key destruction |
| KMS / key management | Per-subject PME key storage + lifecycle | Out-of-band: TPM2-sealed master + per-subject wrapped keys | D-NEW-B + D103 security model |

### §3.3 Source-exactness invariants (NEW; binding)

| Invariant | Check |
|---|---|
| **SE-1**: Parquet column count = source column count | Schema diff at write time |
| **SE-2**: Parquet column dtypes correspond 1:1 to source dtypes (per documented mapping table) | Validate at write time |
| **SE-3**: Parquet column values (after PME decryption for PII columns) byte-equivalent to source query result | Sample-based round-trip test per write |
| **SE-4**: NO additive columns in Parquet schema (`_row_hash`, `_extracted_at` etc.) | Schema validation at write time |
| **SE-5**: Control characters (`\t \n \r \x00`) preserved in Parquet string columns | Round-trip test |
| **SE-6**: Source row count = Parquet row count (no row filtering) | Count assertion at write time |
| **SE-7**: Source row order optionally preserved (or documented sort key) | Sort order in Parquet metadata |

---

## §4. Parquet encryption strategy (Parquet Modular Encryption — PME)

### §4.1 Why PME (vs alternatives)

| Alternative | Pros | Cons | Verdict |
|---|---|---|---|
| **No encryption** (raw plaintext PII in Parquet) | Simplest | GDPR/CCPA + D103 violation; plaintext PII on disk | REJECT |
| **Filesystem-level encryption** (LUKS / BitLocker on H drive) | Transparent to apps | All-or-nothing; no per-subject crypto-shredding; mount-time vulnerability | INSUFFICIENT (no per-subject key) |
| **Parquet Modular Encryption (PME)** | Column-level; per-subject keys; crypto-shredding via key destruction; Apache standard; Polars/pyarrow native support | More complex setup; key management overhead | **SELECTED** |
| **Vault-side encryption with token-only Parquet** | Current architecture | Violates user hard requirement (Parquet not source-exact) | REJECT (per user) |

### §4.2 PME implementation pattern

**Parquet Modular Encryption** is an Apache standard (Parquet 1.12+) supported by pyarrow + Polars (via `parquet_dataset.write` with `encryption_properties`).

```python
# Parquet writer with PME (conceptual)
from pyarrow.parquet import encryption

# Per-table encryption configuration
encryption_config = encryption.EncryptionConfiguration(
    footer_key="master_key_id",  # encrypts file metadata + non-PII column metadata
    column_keys={
        "SSN": "subject_key_id_for_ssn_row",
        "EMAIL": "subject_key_id_for_email_row",
        # ...
    },
    encryption_algorithm="AES_GCM_V1",  # per D102
)

# Key wrapping: master key wraps subject keys
# Master key stored in TPM2-sealed vault per D64
# Subject keys stored in KMS (per-subject-id rows)

pyarrow.parquet.write_table(
    table,
    file_path,
    encryption_properties=encryption_config.create_file_encryption_properties(crypto_factory),
    ...
)
```

### §4.3 Key management

**Master key**:
- Stored in TPM2-sealed location per D64 (already canonical for credentials per D103)
- Wraps subject-level keys
- Rotation per established RB-12 key rotation procedure (B41)

**Per-subject keys**:
- Generated at first observation of subject (similar to vault token generation timing)
- Stored in NEW `General.ops.PiiSubjectKeys` table (D-NEW-E):
  ```sql
  CREATE TABLE General.ops.PiiSubjectKeys (
      SubjectKeyId UNIQUEIDENTIFIER PRIMARY KEY,
      SubjectIdentifier NVARCHAR(MAX) NOT NULL,  -- hash of source PK for deduplication
      EncryptedSubjectKey VARBINARY(MAX) NOT NULL,  -- subject key wrapped by master
      CreatedAt DATETIME2(3) NOT NULL DEFAULT SYSUTCDATETIME(),
      Status NVARCHAR(20) NOT NULL DEFAULT 'active',  -- 'active' | 'shredded'
      ShreddedAt DATETIME2(3) NULL,
      ShredReason NVARCHAR(MAX) NULL  -- 'ccpa_request' | 'gdpr_request' | etc.
  );
  ```

**Per-subject key lifecycle**:
- **active**: subject key exists; PME decryption possible; row visible in pipeline
- **shredded**: subject key destroyed (column `EncryptedSubjectKey = NULL`); PME decryption impossible; row effectively deleted
- Crypto-shredding = `UPDATE PiiSubjectKeys SET EncryptedSubjectKey = NULL, Status = 'shredded', ShreddedAt = NOW(), ShredReason = 'ccpa_request' WHERE SubjectKeyId = ?`
- Append-only audit row to `PiiSubjectKeyShredLog` for compliance audit trail

### §4.4 Crypto-shredding semantics

**When operator invokes RB-10 CCPA right-to-deletion for subject X**:
1. the CCPA-deletion stored procedure (per CLAUDE.md SP family registry) looks up subject's PiiSubjectKeyId(s) — one per PII column affected
2. UPDATE PiiSubjectKeys: NULL out EncryptedSubjectKey for each
3. INSERT audit row to PiiSubjectKeyShredLog with timestamp + reason
4. Existing Bronze rows for subject X: tokens REFERENCE the vault rows (vault row Status='deleted_per_request' per current RB-10) — Bronze itself unchanged (audit trail per D26)
5. Future replay of pre-deletion Parquet: PME decrypt attempts to use subject key → returns NULL → pipeline treats as "subject deleted; skip row"

**EDPB 01/2025 irreversibility test**: 
- Master key + subject key both required for decryption
- Subject key destruction = decryption mathematically infeasible (AES-GCM = computationally unrecoverable without key)
- Satisfies EDPB irreversibility standard (per R5 industry pattern: crypto-shredding > vault-soft-delete)
- ⚠️ Legal counsel still required per R5 (R5 notes industry consensus but no DPA enforcement precedent specifically for PME crypto-shredding)

---

## §5. Pipeline flow reorder (new per-table inner loop)

### §5.1 New per-table flow (replaces `01c_data_flow_walkthrough.md` § 3)

```
T_start — Worker N picks up table T

[Step 1: Acquire table lock] — unchanged

[Step 2: Begin extraction + idempotency ledger] — unchanged

[Step 3: Execute extraction]
T+100ms: extractor returns Polars DataFrame (source dtypes preserved)
T+5s: NO sanitization here (deferred)
      NO tokenization here (deferred per D-NEW-A)
      NO _row_hash injection (deferred)
      NO _extracted_at column (deferred)
T+5s: parquet_writer.write_snapshot_with_pme(df, T.SourceName, T.SourceObjectName, target_date)
      - Stage-check-exchange (per D16)
      - PME encryption per D-NEW-B for T.PiiColumnList columns
      - Subject keys looked up / generated per T.PrimaryKey columns (deduplication)
      - INSERT ParquetSnapshotRegistry with EncryptionKeyId reference
      - Async copy to VendorFile per D107
T+8s: ParquetSnapshotRegistry INSERT (Status='created')

[Step 4: Downstream in-memory pipeline (NEW SEPARATION)]
T+8s: sanitize_strings(df_in_memory) — for BCP CSV prep only; NOT applied to Parquet
T+8s: pii_tokenizer.tokenize_pii_columns(df_in_memory, T.PiiColumnList) — per D-NEW-A
      - Vault SP-1 unchanged
      - PiiTokenizationBatch INSERT unchanged
T+9s: add_row_hash(df_in_memory) — polars-hash SHA-256
T+9s: add _extracted_at column (in-memory only; for SCD2 hash compare)

[Step 5: Stage CDC write] — REMOVED per D2 (Stage layer dropped)

[Step 6: CDC promotion] — REMOVED per D2

[Step 7: SCD2 promotion (Polars in-memory vs Bronze active)] — unchanged per D2 + D18
T+12.5s: scd2/engine.run_scd2(table_config, df_in_memory_tokenized, pk_columns, output_dir)
         - source_verifier_fn closure per D18 (verify-before-close)
         - E-12 phantom-update ratio in SCD2_PROMOTION metadata
         - 3-step atomic write per E-2

[Step 8: Cleanup CSV] — unchanged

[Step 9: Complete idempotency ledger step] — unchanged

[Step 10: Release table lock] — unchanged

[Step 11: TABLE_TOTAL summary] — unchanged
```

### §5.2 Code changes required

| File | Change | Effort |
|---|---|---|
| `data_load/parquet_writer.py` | NEW `write_snapshot_with_pme()` function; PME encryption via pyarrow; subject-key lookup/generation; sanitize/hash REMOVED from Parquet path | ~300 lines |
| `data_load/pii_subject_keys.py` (NEW module) | Subject key generation, storage, retrieval, crypto-shredding; TPM2-sealed master key handling | ~200 lines |
| `migrations/pii_subject_keys.py` (NEW migration) | CREATE TABLE `General.ops.PiiSubjectKeys` + `PiiSubjectKeyShredLog` | ~100 lines |
| `orchestration/small_tables.py` + `orchestration/large_tables.py` | Reorder: Parquet write BEFORE sanitization/tokenization/hashing; pass in-memory df forward to downstream | ~50 lines |
| `data_load/parquet_replay.py` | NEW `replay_parquet_range()` (per B-332) WITH PME decryption + crypto-shred-aware row exclusion | ~200 lines (B-332 + crypto-shred integration) |
| `tools/scd2_replay_smoke.py` | Extend to range mode + PME decryption operator UX | ~50 lines |
| `data_load/pii_decryptor.py` | NEW operator-justified PME decrypt for compliance investigation (extends existing decrypt_pii contract) | ~100 lines |
| `tools/process_ccpa_deletion.py` | Crypto-shredding integration: NULL out PiiSubjectKeys.EncryptedSubjectKey on deletion request | ~50 lines |
| Migration runbook (new RB-N) | Migrate from current code architecture to new architecture | runbook authoring |

### §5.3 Greenfield advantage

Per `02_PHASES.md` L5: "This is an initial build, not a migration. There is no legacy Stage layer to cut over from."

**For pipeline-data**: greenfield → no production Parquet to migrate.

**For code architecture**: current code has tokenization-at-extraction baked in; needs refactor BEFORE first pipeline run in production. This is much easier than migrating existing live data.

---

## §6. SCD2 flow + D18 + verify-before-close (unchanged from D2 plan)

D2 + D18 commitments preserved:
- Stage layer dropped (D2)
- SCD2 reads in-memory DataFrame (D2)
- source_verifier_fn closure for verify-before-close (D18)
- E-12 phantom-update ratio in SCD2_PROMOTION metadata (D18)
- 3-step atomic write per E-2 (preserved)
- B-4 orphan cleanup (preserved)
- P0-8 INSERT-first then UPDATE (preserved)
- All SCD2-P1-* invariants preserved

What changes:
- `df_current` passed to `scd2/engine.run_scd2()` is now from in-memory pipeline (POST-tokenization) OR from replay engine (POST-decryption + tokenization)
- Both paths produce SAME shape of DataFrame for SCD2 input
- SCD2 engine itself unchanged

---

## §7. Replay path with crypto-shredding (replaces G1 Option A4)

### §7.1 Old design (G1 Option A4 from gap-resolution plan)

Required:
- Filter rows against CcpaDeletionLog as-of snapshot
- Synthesize Flag=2 deletion event for CCPA deletion date
- 3-case per-row decision logic
- Complex state machine

### §7.2 New design (crypto-shredding via PME key destruction)

Much simpler:

```python
def replay_parquet_range(
    source: str, table: str, start_date: date, end_date: date,
    *, output_dir: Path, table_config: TableConfig,
    source_verifier_fn: Callable | None = None,
) -> ReplayRangeResult:
    """Multi-day ordered Parquet replay for SCD2 corruption recovery.

    CCPA deletion handling: implicit via PME crypto-shredding.
    Subjects whose PiiSubjectKeys.EncryptedSubjectKey was destroyed
    will have PME decrypt return NULL for their rows. Pipeline treats
    NULL-decrypt as "subject deleted; skip row."

    No CcpaDeletionLog filter needed at replay time — crypto-shredding
    operates at decryption layer (data is mathematically unrecoverable).
    """
    result = ReplayRangeResult()

    snapshots = query_snapshots_in_range(
        source, table, start_date, end_date,
        status_in=REPLAY_ELIGIBLE_STATUSES,
        order_by="BatchId ASC",  # SCD2-P1-b chain preservation
    )

    _cleanup_orphaned_inactive_rows(table_config.bronze_full_table_name, table_config)

    with replay_table_lock(source, table):
        for snapshot in snapshots:
            with ledger_step(
                batch_id=snapshot.batch_id,
                source_name=source,
                table_name=table,
                event_type="PARQUET_REPLAY",
            ) as step:
                if step.action == "skip":
                    continue

                # SHA verify
                if not _verify_sha(snapshot):
                    step.fail("SHA mismatch")
                    raise RegistryHashMismatch(snapshot.file_path)

                # Read Parquet with PME decryption
                # Crypto-shredded subjects: PME returns NULL for their PII columns
                # Pipeline detects NULL token = subject deleted; excludes row
                df_current = pyarrow.parquet.read_table(
                    snapshot.file_path,
                    decryption_properties=_get_pme_decrypt_properties(table_config),
                )

                # Detect crypto-shredded rows (PII columns all NULL post-decrypt)
                # for CCPA-deleted subjects
                df_current = _exclude_crypto_shredded_rows(df_current, table_config.pk_columns)

                # In-memory tokenize remaining (active) rows
                df_current_tokenized = tokenize_pii_columns(df_current, table_config.pii_columns)

                # Standard SCD2 promotion (chain preserved per source_begin_date)
                run_scd2_targeted(
                    table_config=table_config,
                    df_current=df_current_tokenized,
                    pk_columns=table_config.pk_columns,
                    output_dir=output_dir,
                    target_date=snapshot.business_date,
                    source_begin_date=snapshot.business_date,
                    source_verifier_fn=source_verifier_fn,
                )

                step.complete()

    return result
```

### §7.3 Why crypto-shredding is simpler + more compliant

| Aspect | G1 Option A4 (old) | Crypto-shredding (new) |
|---|---|---|
| Replay-time CCPA filter | Complex JOIN against CcpaDeletionLog | None needed (decryption layer does it) |
| Synthesized Flag=2 event | YES (forges historical event; violates SCD2-R4 per design reviewer Q1) | NO (subject just disappears post-shred) |
| ccpa_snapshot_as_of parameter | YES (idempotency concern per design reviewer Q3) | NO (PiiSubjectKeys state IS the truth) |
| B-4 cleanup + Case B interaction | Complex (UdmModifiedBy tag etc.) | None needed |
| EDPB irreversibility compliance | NO (vault-soft-delete; per R5 finding) | YES (mathematical via AES-GCM key destruction) |
| New flag value (Flag=3) for CCPA-synthesized | Required per reviewer Q1 BLOCK | NOT needed |
| Legal counsel posture | "vault-soft-delete acceptable with residual risk" | "crypto-shredding = industry-canonical pattern; satisfies EDPB" |

**Net effect**: crypto-shredding via PME ELIMINATES 5 of the 11 gaps surfaced in pre-sign-off gap-check (G1's complex 3-case logic + ccpa_snapshot_as_of + B-4 + Case B + Flag=2 semantic), 4 of the 6 R5-research-surfaced new gaps (CCPA-REPLAY-EC1-4), and aligns with industry-canonical pattern.

---

## §8. Snowflake integration (PME-aware federation)

### §8.1 Snowflake + PME

Snowflake supports Parquet Modular Encryption since 2023 (per Snowflake docs):
- External KMS integration (AWS KMS / Azure Key Vault / GCP KMS)
- For on-prem KMS (our case): Snowflake can use customer-managed keys via external function
- Per-column decryption in Snowflake SQL queries
- Masking policies on top of decryption for row-level security

### §8.2 Snowflake-side tokenization

Option (a): Snowflake-side tokenization via UDF
- UDF wraps vault SP-1 (call out from Snowflake)
- High latency for bulk operations
- Use case: ad-hoc analytics queries

Option (b): Mirror tokenized Bronze TO Snowflake (current pattern)
- Snowflake Bronze gets tokenized data (current architecture preserved)
- Snowflake federation of RAW Parquet only for compliance investigation
- Operator runs decrypt_pii.py for justified PII access

Recommendation: **Option (b)** — current Snowflake Bronze mirror pattern unchanged; PME-encrypted Parquet stays in audit-archive tier; federation only for compliance investigation by authorized operator.

---

## §9. D-N supersession + new D-N enumeration

### §9.1 D-N supersession needed (per D92 forward-only)

| Existing D-N | New D-N | Reason |
|---|---|---|
| **D6** (PII tokenization at extraction) | **D-NEW-A** "PII tokenization happens post-Parquet-write" | User hard requirement: Parquet = source-exact |

### §9.2 New D-N candidates

| D-N | Description | Status |
|---|---|---|
| **D-NEW-A** | PII tokenization happens post-Parquet-write (supersedes D6) | 🟡 Proposed; lockable |
| **D-NEW-B** | Parquet Modular Encryption (PME) for PII columns; column-level AES-GCM; per-subject keys | 🟡 Proposed; pending R-NEW industry-pattern research |
| **D-NEW-C** | Crypto-shredding via PME subject-key destruction = canonical CCPA right-to-deletion mechanism (supplements RB-10) | 🟡 Proposed; pending R5 industry pattern + legal-counsel sign-off |
| **D-NEW-D** | _row_hash + _extracted_at NOT in Parquet; computed on-the-fly during downstream consumer reads | 🟡 Proposed; lockable |
| **D-NEW-E** | New table `General.ops.PiiSubjectKeys` for per-subject PME key storage with crypto-shred audit trail | 🟡 Proposed; needs DDL design |

### §9.3 D-N already locked that REMAIN compatible

- **D2** (Drop Stage layer) — REMAINS LOCKED; D2 commitments preserved
- **D4** (Network drive Parquet) — REMAINS LOCKED; Hive layout unchanged
- **D15** (Master idempotency invariant) — REMAINS LOCKED; PME preserves
- **D16** (Stage-check-exchange) — REMAINS LOCKED; PME write is stage-check-exchange-aware
- **D18** (verify-before-close in SCD2) — REMAINS LOCKED
- **D25** (ParquetSnapshotRegistry) — REMAINS LOCKED; add `EncryptionKeyId` column per D92 forward-only
- **D26** (Append-only PiiVault provenance) — REMAINS LOCKED; vault still holds tokens
- **D30** (7-year retention + CCPA/GLBA) — REMAINS LOCKED; PME crypto-shredding actually STRENGTHENS compliance posture per R5
- **D102** (AES-256-GCM crypto pin) — REMAINS LOCKED; PME uses AES-GCM natively
- **D103** (Claude Code security model) — REMAINS LOCKED; Claude in /debi cannot access PME keys; cannot decrypt
- **D107** (H drive + VendorFile) — REMAINS LOCKED
- **D110** (DC-loss-no-DR posture) — REMAINS LOCKED

---

## §10. Migration phase plan

### §10.1 Phase 2 R1 (ACCT pilot — small-table source-exact + tokenized-Bronze)

**Prerequisites** (gates):
1. **D-NEW-A locked** (PII tokenization post-Parquet-write supersedes D6)
2. **D-NEW-B locked** (PME encryption strategy) — pending R-NEW industry-pattern research
3. **D-NEW-C locked** (crypto-shredding mechanism) — pending legal-counsel sign-off per R5
4. **D-NEW-D locked** (defer _row_hash/_extracted_at)
5. **D-NEW-E locked** (PiiSubjectKeys table DDL)
6. **B-332** built (`replay_parquet_range()`)
7. **B-334** built (source_verifier_fn closure per D18)
8. **B-336** built (Parquet write in small_tables.py)
9. **B-337** built (IdempotencyLedger SUPERSEDED)
10. **NEW B-N-α** (PME writer in parquet_writer.py)
11. **NEW B-N-β** (PiiSubjectKeys module + migration)
12. **NEW B-N-γ** (orchestration reorder)
13. **NEW B-N-δ** (replay with PME + crypto-shred-aware row exclusion)

**Deliverables**:
- ACCT pilot runs with source-exact Parquet + tokenized Bronze
- SE-1 through SE-7 invariants verified per Parquet write
- 1-week soak

**Risk profile**: HIGH (substantial architecture change; many new B-Ns; PME is new dependency)

### §10.2 Phase 3 R1 (smallest large-table — multi-day replay + crypto-shred validation)

Prerequisites: Phase 2 R1 ⚫ CLOSED + benchmarks per B-346 + crypto-shred audit trail validated

### §10.3 Phase 4+ (progressive large-table enablement) — unchanged scope

### §10.4 Code-build effort estimate

| Component | Lines | Effort |
|---|---|---|
| Parquet writer with PME | ~300 lines new | 1-2 cycles |
| PiiSubjectKeys module | ~200 lines new | 1 cycle |
| Migration for PiiSubjectKeys + PiiSubjectKeyShredLog | ~100 lines | 0.5 cycle |
| Orchestration reorder (small + large tables) | ~50 lines | 0.5 cycle |
| Replay engine with PME + crypto-shred | ~200 lines (per B-332 + integration) | 1-2 cycles |
| the CCPA-deletion stored procedure (per CLAUDE.md SP family registry) crypto-shred integration | ~50 lines | 0.5 cycle |
| Tier 0 + Tier 1 tests | ~500 lines | 1-2 cycles |
| Operator runbook for crypto-shredding (RB-N) | ~150 lines | 0.5 cycle |
| Migration runbook for code-architecture cutover | ~200 lines | 0.5 cycle |
| **Total** | ~1750 lines | **~6-9 cycles** |

This is substantial. Greenfield project advantage: no production data migration needed; only code refactor + first pipeline run with new architecture.

---

## §11. Risks + invariants

### §11.1 Source-exactness invariants (NEW SE-N series; binding)

Per §3.3 above — SE-1 through SE-7 must be verified per Parquet write. Tier 1 test: `tests/tier1/test_parquet_source_exactness.py` — round-trip source DB extraction vs Parquet read.

### §11.2 SCD2 invariants (preserved from current architecture)

All SCD2-P1-* + E-2 + P0-8 + B-4 + D15 invariants preserved (per §6 unchanged).

### §11.3 New risk register additions

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **R-NEW-E**: PME key loss = data permanently unrecoverable | Medium | Critical | TPM2-sealed master backup; KMS HA; key rotation runbook |
| **R-NEW-F**: PME performance overhead on 3B-row Parquet replay | Medium | High | Phase 2 R2 benchmark per B-346 extended scope; pyarrow PME is hardware-accelerated AES-NI |
| **R-NEW-G**: Polars + pyarrow PME compatibility regression on version upgrade | Low | Medium | Pin pyarrow version; integration test in CI |
| **R-NEW-H**: Subject-key generation race condition (concurrent extractions for same subject) | Low | Medium | UNIQUE constraint on (SubjectIdentifier) in PiiSubjectKeys; INSERT-IF-NOT-EXISTS pattern |
| **R-NEW-I**: Snowflake Iceberg federation requires external KMS integration | Medium | Medium | Defer to Phase 5; Snowflake supports external function pattern |

### §11.4 Risks DE-ESCALATED by this redesign

| Risk | Was | Now |
|---|---|---|
| **R-NEW-D** (CCPA-replay-interaction-unresolved per D2 gap-resolution plan) | Medium × High = 6 | DE-ESCALATED — crypto-shredding ELIMINATES the replay interaction; no synthesized Flag=2 needed |
| **R09** (PII compliance audit timing) | Low × High = 3 (potential escalation to Medium × High per R5) | DE-ESCALATED — crypto-shredding is EDPB-irreversibility-compliant per R5 industry pattern |
| **Risk-NEW-C** (D18 source coupling) | Low × Medium = 2 | Unchanged; D18 unaffected by this redesign |

---

## §12. B-N enumeration (NEW + amended)

### §12.1 B-Ns from prior plans that REMAIN

- **B-332** (multi-day Parquet replay engine) — REMAINS; now integrated with PME decryption per §7.2 above
- **B-333** (H drive capacity verification) — REMAINS; PME adds modest overhead (~10% file size)
- **B-334** (source_verifier_fn closure per D18) — REMAINS unchanged
- **B-335** (tools/query_parquet.py operator CLI) — REMAINS; now requires PME decryption awareness
- **B-336** (Parquet write to small_tables.py) — REMAINS; now uses write_snapshot_with_pme
- **B-337** (IdempotencyLedger SUPERSEDED status) — REMAINS unchanged
- **B-338-B-352** (D2 gap-resolution B-Ns) — most REMAIN; some scope changes per simplifications above

### §12.2 NEW B-N candidates from this redesign

| B-N candidate | Description | Severity | Closure target |
|---|---|---|---|
| **B-N-α** | Author `write_snapshot_with_pme()` in `data_load/parquet_writer.py` — PME-encrypted Parquet write per D-NEW-B | CRITICAL | Phase 2 R1 prereq |
| **B-N-β** | Author `data_load/pii_subject_keys.py` module — per-subject key management + crypto-shredding API per D-NEW-E | CRITICAL | Phase 2 R1 prereq |
| **B-N-γ** | Author migration `migrations/pii_subject_keys.py` — CREATE TABLE `General.ops.PiiSubjectKeys` + `PiiSubjectKeyShredLog` per D-NEW-E | CRITICAL | Phase 2 R1 prereq |
| **B-N-δ** | Refactor `orchestration/small_tables.py` + `large_tables.py` — reorder Parquet write BEFORE tokenization per D-NEW-A | CRITICAL | Phase 2 R1 prereq |
| **B-N-ε** | Extend `data_load/parquet_replay.py` with PME decryption + crypto-shred-aware row exclusion (integrates with B-332) | HIGH | Phase 2 R1 prereq |
| **B-N-ζ** | Extend `tools/process_ccpa_deletion.py` with crypto-shredding integration (NULL out subject key on deletion request) | HIGH | Phase 2 R3 prereq |
| **B-N-η** | Author **RB-14** "Crypto-shredding operational runbook" — when/how to invoke; key recovery prevention; audit trail validation | HIGH | Phase 2 R2 prereq |
| **B-N-θ** | Author **a TBD code-architecture cutover runbook (no RB-N assigned yet)** "Code architecture cutover" — migration from current tokenization-at-extraction to source-exact Parquet | HIGH | Phase 2 R1 prereq |
| **B-N-ι** | Author Tier 1 test `tests/tier1/test_parquet_source_exactness.py` — SE-1 through SE-7 round-trip verification | HIGH | Phase 2 R1 prereq |
| **B-N-κ** | Performance benchmark: PME encryption/decryption overhead at 3B-row scale (extends B-346 scope) | MEDIUM | Phase 2 R2 |
| **B-N-λ** | Research R-NEW-A: Parquet Modular Encryption industry patterns + KMS choice for on-prem | MEDIUM | Phase 2 R1 prereq (informs D-NEW-B lock) |
| **B-N-μ** | Research R-NEW-B: legal counsel review of crypto-shredding via PME key destruction (informs D-NEW-C lock per R5 recommendation) | CRITICAL | Phase 2 R3 prereq (BEFORE production go-live) |
| **B-N-ν** | Schema evolution: add `ParquetSnapshotRegistry.EncryptionKeyId UNIQUEIDENTIFIER NULL` column (D92 forward-only ALTER) | MEDIUM | Phase 2 R1 prereq |

**Will assign actual B-N numbers (B-353+) at next BACKLOG.md update.**

### §12.3 B-Ns from prior plans that can CLOSE per simplification

- **B-341** (G1 CCPA + Parquet replay design) — SIMPLIFIED scope: crypto-shredding via PME REPLACES complex Option A4. CAN BE RECLASSIFIED as "implement PME-based replay" or CLOSED-as-SUPERSEDED with new B-N pointing to crypto-shred path
- **B-351** (CCPA-REPLAY-EC1-4) — REDUCED scope: crypto-shred path has fewer edge cases (likely only EC2 legal-hold-override remains)
- **B-340** (D2-EC1-4) — REMAINS scope unchanged

---

## §13. Sign-off readiness checklist

### §13.1 Pre-sign-off actions (this commit)

- [x] New plan authored per user hard requirement
- [x] §0 provenance per Step 5 contract
- [x] §1 binding constraints documented
- [x] §2 conflict map vs current architecture
- [x] §3 new architecture (source-exact Parquet + downstream tokenization)
- [x] §4 PME encryption strategy
- [x] §5 pipeline flow reorder
- [x] §6 SCD2 + D18 compatibility
- [x] §7 replay with crypto-shredding
- [x] §8 Snowflake integration
- [x] §9 D-N supersession + new D-N enumeration
- [x] §10 migration phase plan
- [x] §11 risks + invariants (SE-1 through SE-7 new)
- [x] §12 B-N enumeration (~13 new placeholder items; SUPERSEDED — actual B-353 through B-373 opened in BACKLOG.md per Phase A/B split; no further B-N opening needed on this superseded plan)
- [ ] Spawn `udm-design-reviewer` for independent architectural review
- [ ] Spawn `udm-researcher` for R-NEW (PME industry patterns + KMS choice)
- [ ] Spawn `udm-gap-check` for independent gap analysis
- [ ] Open 13 new placeholder items in BACKLOG.md — already addressed via B-353 through B-373 per Phase A/B split; no B-N needed; this checklist item is superseded
- [ ] Open 5 new D-N candidates in 03_DECISIONS.md as 🟡 Proposed (per `udm-decision-recorder`)
- [ ] Update CURRENT_STATE + HANDOFF + _validation_log

### §13.2 Pre-Phase-2-R1-execution actions

- [ ] D-NEW-A locked (D6 supersession)
- [ ] D-NEW-B locked (PME strategy; pending R-NEW research)
- [ ] D-NEW-C locked (crypto-shredding; pending legal counsel per R5 + B-N-μ)
- [ ] D-NEW-D locked (defer _row_hash/_extracted_at)
- [ ] D-NEW-E locked (PiiSubjectKeys DDL)
- [ ] B-N-α through B-N-θ built + tested
- [ ] B-N-ι Tier 1 source-exactness tests pass

### §13.3 Sign-off

🟡 **DRAFT v1 2026-05-17** by parent agent. Authoring complete; requires reviewer cohort + R-NEW research + legal counsel per R5 before sign-off.

**Pipeline lead sign-off**: [ ] APPROVED / [ ] REDIRECT / [ ] BLOCK on specific design

---

## §14. Cross-references

- `docs/migration/D2_EXECUTION_PLAN_PARQUET_DIRECT_SCD2_2026-05-17.md` (PRIOR PLAN; superseded by tokenization-timing-reorder + PME addition)
- `docs/migration/D2_GAP_RESOLUTION_PLAN_2026-05-17.md` (PRIOR PLAN; 11 gaps partially superseded by simplification under crypto-shredding)
- `docs/migration/_research/r5-ccpa-parquet-replay-legal-2026-05-17.md` (R5 RESEARCH; VALIDATES crypto-shredding as EDPB-compliant)
- `docs/migration/03_DECISIONS.md` D2 + D4 + D6 (SUPERSEDED) + D15 + D16 + D18 + D25 + D26 + D30 + D64 + D92 + D102 + D103 + D107 + D110
- `docs/migration/05_RUNBOOKS.md` RB-10 (CCPA right-to-deletion; AMENDED with crypto-shred mechanism per D-NEW-C)
- `docs/migration/CLAUDE_GOTCHAS.md` SCD2-P1-* + E-2 + B-4 + D15 — ALL PRESERVED
- `scd2/engine.py` — UNCHANGED (still reads in-memory tokenized DataFrame)
- `data_load/parquet_writer.py` — NEW `write_snapshot_with_pme()` function
- `data_load/pii_subject_keys.py` — NEW module
- `migrations/pii_subject_keys.py` — NEW migration
- `orchestration/small_tables.py` + `orchestration/large_tables.py` — REORDERED
- `data_load/parquet_replay.py` — EXTENDED with PME decryption + crypto-shred-aware exclusion

---

**Awaiting**:
1. Independent reviewer + researcher cohort (next cycle)
2. D-NEW-A through D-NEW-E lock decisions
3. Pipeline-lead sign-off
