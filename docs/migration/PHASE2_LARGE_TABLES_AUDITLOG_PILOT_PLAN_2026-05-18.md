# Phase 2 (Large Tables) — Parquet → SCD2 Autonomous Pipeline — AuditLog Pilot

**Date**: 2026-05-18 (v5 — post-v4-confirmation-gap-check; B-N renumber fix + body-sweep + minor remediations)
**Author**: pipeline lead + parent agent (orchestrator role); skills invoked per §0
**Status**: 🟡 Draft v5
**Pilot table**: `CCM.AuditLog` (96M rows; multi-year history)
**Operates atop**: `D2_EXECUTION_PLAN_PARQUET_DIRECT_SCD2_2026-05-17.md` + `UDM_PIPELINE_PHASE_A_TOKENIZATION_REORDER_2026-05-17.md` + `D2_GAP_RESOLUTION_PLAN_2026-05-17.md`

**v5 delta vs v4** (mechanical-only):
- B-N range renumbered B-496–B-534 → **B-497–B-535** (post-v4 commit `a0f0326` opened B-496 in HEAD, collided with v4's lowest B-N)
- 7 body citations in §3.1 + §4.1 + §5.2 corrected to match the renumber table (v4 had stale v3-numbered citations per v4 confirmation gap-check Pitfall #9.k finding)
- §8 B-535 body now includes `Justification NVARCHAR(MAX) NULL` column (matches §15.3 DDL canonical)
- Delta §7.5 preamble corrected "6 doc-side artifacts" → "12 doc-side artifacts"
- Architecture / design / decisions unchanged from v4

---

## §0. Planning session provenance

| Agent | Role | Findings |
|---|---|---|
| `ad3e78033b453746c` | v1 design-reviewer | 2 BLOCK + 4 IMPROVE + 7 Class — absorbed v2 |
| `a60badeb8ed452e5c` | v1 gap-check | 4 BLOCK + 21 IMPROVE + 3 OK — absorbed v2 |
| `a5e19d35c7c5e3281` | v1 pipeline-mechanics (B-339 substitute) | 3 BLOCK + 6 IMPROVE + 1 PASS — absorbed v2 |
| `a1a23fbd3098e5d76` | v2 Option B design-reviewer | 3 BLOCK + 7 IMPROVE — absorbed v3 |
| `a7c3f43f39535ea45` | v3 gap-check | 3 BLOCK + 17 IMPROVE + 10 OK — absorbed v4 |
| `a3d68f47ea920cb18` | v4 confirmation gap-check | 1 BLOCK reopened (G1-1 collision recurred) + 6+ Pitfall #9.k internal stale citations + 3 NEW gaps — **absorbed v5 (this version)** |

Skills (active throughout): `udm-planning-session-startup` / `udm-design-reviewer` / `udm-data-engineer-review` (B-501 substitute) / `udm-gap-check` / `udm-brainstorm` (Option B inline) / `udm-decision-recorder` / `udm-execution-classifier` / `udm-runbook-author` / `udm-edge-case-validator` / `udm-test-author` (scheduled R1+R2) / `udm-progress-logger` / `udm-step-10-verifier` / `udm-post-edit-verification` / `superpowers-verification-before-completion`.

---

## §1. Binding constraints

1. Greenfield posture per `02_PHASES.md:5`.
2. **Parquet on /VendorFiles = source-exact** per Phase A + D115 + D116. **DELIBERATE 30-day post-cutover exception**: during first 30 days (per `UdmTablesList.SidecarRetentionDays`) after Phase 2 cutover, masked parquet ALSO writes to `/VendorFiles/_audit_retention/...`. After retention expiry: steady-state operation reverts to raw-only.
3. SE1-SE10 invariants + SE11/SE12/SE13 (no-hyphen format) apply.
4. D2 lock: no Stage writes for cutover tables.
5. SCD2-P1-* invariants preserved; chronological per-day replay only.
6. Months-old Parquet replayable per B-346 24-48h SLA.
7. Fully autonomous Automic schedule per D109; Snowflake replication via SEPARATE Automic JOB per D120 (does not block SCD2 promotion).
8. Forward-only additive schema evolution per D92.
9. D103 security model preserved; Option B reduces PII-leakage surface.
10. Existing Phase 2 ACCT plan stays 🟢 Locked but PAUSED per D118.
11. PII tokenization must happen BEFORE data lands in Snowflake; D6 + D26 guarantees byte-identical re-mask for audit replay.

---

## §2. Current state & scope re-shape

(Same §2.1 + §2.2 + §2.3 structure as v4. §2.2 gap-table B-N citations updated to v5 range B-497-B-535.)

---

## §3. Architecture: fully-autonomous AuditLog Parquet → SCD2 → Snowflake

### §3.1 Happy-path per-day flow (v5 = body citations corrected to v5 B-Ns)

```
STEPS 1-10 unchanged from v4 (main extraction + SCD2 cycle on JOB_PARQUET_AUDITLOG_INCR)
═══════════════════════════════════════════════════════════════════════════════════════
SEPARATE Automic JOB_SNOWFLAKE_REPLICATE_AUDITLOG (1 hour offset; no sp_getapplock during Snowflake I/O)
═══════════════════════════════════════════════════════════════════════════════════════

For each ParquetSnapshotRegistry row WHERE Status='verified' AND NOT EXISTS
    (SnowflakeReplicationLog row Status='replicated' for same RegistryId):
  ┌──────────────────────────────────────────────────────────────────────┐
  │ STEP S1: Determine ReplicationAttempt = MAX(prior) + 1                │
  ├──────────────────────────────────────────────────────────────────────┤
  │ STEP S2: SELECT @marker = SYSUTCDATETIME() FROM SQL Server             │
  │          (PRE-tokenize round-trip per B-527 — semantic locked)         │
  │          INSERT SnowflakeReplicationLog (RegistryId,                   │
  │              SnowflakeStagePath, VaultTokenSnapshotMarker=@marker,     │
  │              ReplicationAttempt, Status='in_progress') per D123        │
  ├──────────────────────────────────────────────────────────────────────┤
  │ STEP S3: Read raw parquet from registry.NetworkDrivePath               │
  ├──────────────────────────────────────────────────────────────────────┤
  │ STEP S4: tokenize_pii_columns(df, table_config.pii_column_list)        │
  ├──────────────────────────────────────────────────────────────────────┤
  │ STEP S5: Serialize masked parquet to in-memory bytes                   │
  │          stage_path = f"{SNOWFLAKE_STAGE_NAME}/{source}/{table}/"     │
  │                       f"{registry_id}/attempt_{N}/masked.parquet"     │
  │          per D124 (canonical SNOWFLAKE_STAGE_NAME from                 │
  │          utils/configuration.py / data_load/snowflake_uploader.py:693) │
  ├──────────────────────────────────────────────────────────────────────┤
  │ STEP S6: SHA-256 of IN-MEMORY masked bytes (NOT Snowflake-stage        │
  │          read-back) — cheap + deterministic                            │
  ├──────────────────────────────────────────────────────────────────────┤
  │ STEP S7: PUT bytes to SNOWFLAKE_STAGE_NAME stage_path                  │
  │          During first 30 days post-cutover (per                        │
  │          UdmTablesList.SidecarRetentionDays):                          │
  │            ALSO write to /VendorFiles/_audit_retention/<src>/<tbl>/   │
  │            year=Y/month=M/day=D/<batch>.masked.parquet                 │
  ├──────────────────────────────────────────────────────────────────────┤
  │ STEP S8: COPY INTO <iceberg_table> FROM @stage_path                    │
  │          Capture rows_loaded + COPY_HISTORY query_id                   │
  ├──────────────────────────────────────────────────────────────────────┤
  │ STEP S9: UPDATE SnowflakeReplicationLog                                │
  │          SET Status='replicated', MaskedContentChecksum=...,           │
  │              RowsCopied=..., CopyHistoryId=...,                         │
  │              ReplicatedAt=SYSUTCDATETIME()                             │
  │          WHERE ReplicationId=... AND Status='in_progress'              │
  ├──────────────────────────────────────────────────────────────────────┤
  │ STEP S10: del df + gc.collect()                                         │
  └──────────────────────────────────────────────────────────────────────┘
```

### §3.2 Backfill / replay path (unchanged)

### §3.3 Layer responsibility (unchanged — canonical naming locked)

`data_load/snowflake_replicator.py::replicate_to_snowflake_with_masking()` composes M17 + M4 + INSERT-first SnowflakeReplicationLog discipline. CLI shim at `tools/replicate_to_snowflake_with_masking.py` for operator-driven invocation; Automic invokes the CLI. NO separate `main_snowflake_replicate.py`.

`data_load/snowflake_replay.py::replay_snowflake_upload()` returns `SnowflakeReplayResult`. CLI: `tools/replay_snowflake_upload.py`.

`General.ops.SnowflakeCcpaPurgeLog` table (NEW per user choice 2026-05-18): FK to SnowflakeReplicationLog.ReplicationId + FK to CcpaDeletionLog; tracks CCPA Snowflake-side purges as separate audit trail (cleaner than extending SnowflakeReplicationLog Status enum).

---

## §4. Prerequisites & dependency chain

### §4.1 Hard gates by Round (v5 = B-N citations corrected to v5 range)

| Gate | Round | Status |
|---|---|---|
| Phase A R1 closure | R1 build start | 🟡 NEW |
| `SnowflakeReplicationLog` + `SnowflakeCcpaPurgeLog` migrations authored + idempotent per §15.3 + B-523 + B-535 | R1 close | 🟡 NEW |
| NEW orchestration `data_load/snowflake_replicator.py::replicate_to_snowflake_with_masking()` composing M17 + M4 per B-524 + B-525 | R2 close | 🟡 NEW |
| D121-D124 locked | R2 close | 🟡 NEW |
| B-524 INSERT-first crash-safety + startup-recovery sweep extension with graceful-degrade if Snowflake API unreachable | R2 close | 🟡 NEW CRITICAL |
| B-525 deterministic Snowflake stage-path using canonical `SNOWFLAKE_STAGE_NAME` | R2 close | 🟡 NEW CRITICAL |
| B-522 ReplayMode.AS_OF vs ReplayMode.CURRENT code paths | R2 close | 🟡 NEW CRITICAL |
| B-526 RB-10 extension for Snowflake-side CCPA consequences | R2 close | 🟡 NEW HIGH |
| B-527 VaultTokenSnapshotMarker via SQL Server SYSUTCDATETIME() pre-tokenize SELECT round-trip + 1s grace buffer | R2 close | 🟡 NEW |
| B-530 + new `tools/replay_snowflake_upload.py` CLI + `CLI_REPLAY_SNOWFLAKE_UPLOAD` EventType (28th CLI_* family member FINAL after entire v5 cohort) | R2 close | 🟡 NEW |
| B-528 `UdmTablesList.SidecarRetentionDays` column + `enforce_retention.py --sidecar-only` | R3 close | 🟡 NEW |
| D120 frozen-11 → frozen-13 (JOB_PARQUET_AUDITLOG_INCR + JOB_SNOWFLAKE_REPLICATE_AUDITLOG) | R5 day 0 | 🟡 NEW |
| 30-day post-cutover audit-retention sidecar active per §15.6 | R5 day 0 | 🟡 NEW |
| B-534 Snowflake data-sharing policy template + pre-configuration runbook (CCPA Snowflake-side prereq) | R5 day 0 (before cutover) | 🟡 NEW |
| B-533 D120 schedule-offset operator approval + race-window empirical analysis | R5 day 0 (before cutover) | 🟡 NEW |

### §4.2 Soft gates

`tools/query_parquet.py` (B-335); D2-EC1-EC4 (B-340); B-349 Polars version tracking; B-529 SnowflakeReplicationLog filtered pending-retry index (opportunistic R3).

---

## §5. Implementation rounds (v5 = body B-N citations corrected throughout)

### §5.1 R1 — Foundation Wiring (~2 weeks; 17 deliverables)

(Same R1.1-R1.15 from v4 + R1.16/R1.17 with v5 B-N citations:)

| # | Artifact | B-N |
|---|---|---|
| R1.16 | NEW migration `migrations/snowflake_replication_log.py` per §15.3 DDL | B-523 |
| R1.17 | NEW migration `migrations/snowflake_ccpa_purge_log.py` per §15.3 + user choice 2026-05-18 | B-535 |

### §5.2 R2 — Replay + Snowflake Replication Layer (~2 weeks; 16 deliverables + 11 v5 Snowflake additions)

| # | Artifact | B-N |
|---|---|---|
| R2.17 | NEW `data_load/snowflake_replicator.py` module with `replicate_to_snowflake_with_masking()` orchestrator | B-524 + B-525 |
| R2.18 | M17 `copy_parquet_to_snowflake()` additive parameter extension per D92 | Q10 |
| R2.19 | `startup_recovery_sweep` extension for SnowflakeReplicationLog Status='in_progress' reconciliation with graceful-degrade if Snowflake API unreachable | B-524 + D123 |
| R2.20 | D121 locked (Option B core) | D121 |
| R2.21 | D122 locked (AS_OF vs CURRENT split using PiiVault.StatusChangedAt) | D122 + B-522 |
| R2.22 | D123 locked (INSERT-first crash-safety mandatory) | D123 + B-524 |
| R2.23 | D124 locked (deterministic stage-path using canonical SNOWFLAKE_STAGE_NAME) | D124 + B-525 |
| R2.24 | NEW `tools/replay_snowflake_upload.py` CLI + `CLI_REPLAY_SNOWFLAKE_UPLOAD` EventType | B-530 |
| R2.25 | NEW `data_load/snowflake_replay.py` module with `replay_snowflake_upload()` returning `SnowflakeReplayResult` | B-522 + B-530 |
| R2.26 | RB-10 extension: Snowflake-side CCPA consequences; writes to NEW SnowflakeCcpaPurgeLog per user choice 2026-05-18 | B-526 + B-535 |
| R2.27 | NEW `RB-17` Snowflake audit replay runbook | LT-AT-15 |

### §5.3 R3 — Scale Validation + Sidecar Retention (~2-3 weeks; same as v4 with B-N citations corrected)

### §5.4 R4 — AuditLog Dry-Run on Test (~2-3 weeks + 10-day soak; same as v4)

### §5.5 R5 — AuditLog Production Cutover (~1 day + 14-day soak; same as v4 with B-N citations B-533/B-534 from v5)

### §5.6 R6 (optional) — Scale to second large table

---

## §6. Edge cases

### §6.1 Existing series walked (unchanged)

### §6.2 LT-AT series — 15 entries (unchanged from v4)

### §6.3 SE-series extensions (SE11/SE12/SE13 no-hyphen format; v5 B-N citations corrected)

| Code | Description | Mitigation source B-N |
|---|---|---|
| SE11 | Snowflake upload failure mid-COPY → retry must NOT double-load | B-524 + B-525 + D123 + D124 |
| SE12 | Vault row added retroactively → re-mask produces different bytes | B-527 (Marker via SYSUTCDATETIME round-trip) |
| SE13 | CCPA deletion between original upload and audit replay | B-522 + D122 + RB-10 extension via B-526 + B-535 new table |

---

## §7. New D-N candidates (8 total; D117–D124 — bodies unchanged from v4; v5 B-N citations corrected)

D117–D124 bodies same as v4 §7.

---

## §8. New B-N enumeration (39 total; **B-497–B-535** per v4 confirmation gap-check renumber-fix)

**Cohort 1 — B-497 through B-521** (25 entries; v1→v2 cohort; v5 renumber from v4's B-496-B-520):

| v3 B-N | v4 B-N | **v5 B-N** | Severity | Title |
|---|---|---|---|---|
| B-495 | B-496 | **B-497** | MEDIUM | Phase A R1 interface freeze document |
| B-496 | B-497 | **B-498** | MEDIUM | source_verifier_fn CDC_VERIFY_STRICT_ON_FAILURE semantics preservation |
| B-497 | B-498 | **B-499** | HIGH | Explicit NULL PK filter call-site in orchestrator post-D2 reorder |
| B-498 | B-499 | **B-500** | MEDIUM | replay_parquet_range cross-schema-boundary handling |
| B-499 | B-500 | **B-501** | CRITICAL | RB-16 2-phase cutover design (pre-cutover batch outside main txn) |
| B-500 | B-501 | **B-502** | HIGH | Phase A R1 attestation as tracked dependency |
| B-501 | B-502 | **B-503** | HIGH | udm-data-engineer-review agent authored |
| B-502 | B-503 | **B-504** | MEDIUM | LT-AT edge case series introduction cascade |
| B-503 | B-504 | **B-505** | LOW | Phase 3 pilot-scope reshape D-N (consolidated into D118) |
| B-504 | B-505 | **B-506** | LOW | R02 status reconciliation HANDOFF vs RISKS |
| B-505 | B-506 | **B-507** | LOW | Per-server `.env` migration status verification table |
| B-506 | B-507 | **B-508** | MEDIUM | `del df_raw; gc.collect()` between Parquet write + tokenize |
| B-507 | B-508 | **B-509** | HIGH | MALLOC_ARENA_MAX=2 set in Automic JOB parent shell env |
| B-508 | B-509 | **B-510** | HIGH | Source-side `IX_AuditLog_DateTime` index verification with CCM DBA |
| B-509 | B-510 | **B-511** | MEDIUM | `verify_parquet_snapshot` accepts pre-computed SHA |
| B-510 | B-511 | **B-512** | MEDIUM | `_insert_registry_row` populates `uncompressed_bytes` from Parquet metadata |
| B-511 | B-512 | **B-513** | MEDIUM | Sub-day Parquet chunking facility |
| B-512 | B-513 | **B-514** | CRITICAL | NEW `bulk_load_bronze_replay_context` (TABLOCK during replay) |
| B-513 | B-514 | **B-515** | HIGH | SCD2 INSERT BCP sub-batches matching SCD2_UPDATE_BATCH_SIZE |
| B-514 | B-515 | **B-516** | MEDIUM | Filtered nonclustered index `IX_Orphan_<table>` |
| B-515 | B-516 | **B-517** | HIGH | CCI + SCD2 interaction benchmark with >2x reject-gate |
| B-516 | B-517 | **B-518** | HIGH | Partition-aligned CCI helper |
| B-517 | B-518 | **B-519** | HIGH | R3.3 benchmark scope ≥365-day or 2555-day |
| B-518 | B-519 | **B-520** | MEDIUM | Operator alerting policy SKIPPED-during-replay vs SKIPPED-stale-lock |
| B-519 | B-520 | **B-521** | MEDIUM | Tier 4 C16 mid-replay crash + resume test |

**Cohort 2 — B-522 through B-532** (11 entries; v2→v3 Option B cohort; v5 renumber from v4's B-521-B-531):

| v3 B-N | v4 B-N | **v5 B-N** | Severity | Title |
|---|---|---|---|---|
| B-520 | B-521 | **B-522** | CRITICAL | ReplayMode.AS_OF vs ReplayMode.CURRENT implementation |
| B-521 | B-522 | **B-523** | CRITICAL | SnowflakeReplicationLog DDL columns (RowsCopied + CopyHistoryId + SourceFilePurgedAt + Status CHECK) |
| B-522 | B-523 | **B-524** | CRITICAL | INSERT-first crash-safety for SnowflakeReplicationLog + startup-recovery sweep extension |
| B-523 | B-524 | **B-525** | CRITICAL | Deterministic Snowflake stage-path using canonical `SNOWFLAKE_STAGE_NAME` |
| B-524 | B-525 | **B-526** | HIGH | RB-10 extension: Snowflake-side CCPA consequences procedure |
| B-525 | B-526 | **B-527** | MEDIUM | VaultTokenSnapshotMarker via SQL Server SYSUTCDATETIME() pre-tokenize SELECT round-trip |
| B-526 | B-527 | **B-528** | MEDIUM | `UdmTablesList.SidecarRetentionDays` column + `enforce_retention.py --sidecar-only` |
| B-527 | B-528 | **B-529** | LOW | SnowflakeReplicationLog filtered pending-retry index |
| B-528 | B-529 | **B-530** | MEDIUM | `CLI_REPLAY_SNOWFLAKE_UPLOAD` EventType registration (28th CLI_* family member) |
| B-529 | B-530 | **B-531** | MEDIUM | Tier 3 test_snowflake_uploader_to_test_account extension |
| B-530 | B-531 | **B-532** | LOW | JIT-3 Phase 5+ exploration (Snowflake-canonical SCD2) |

**Cohort 3 — B-533 through B-535** (3 entries; v3 gap-check additions; v5 renumber from v4's B-532-B-534):

- **B-533** (🟡 Open; MEDIUM; WSJF 2.0): **D120 schedule-offset operator approval + race-window empirical analysis** — `JOB_SNOWFLAKE_REPLICATE_AUDITLOG` schedule AM 03:00 / PM 18:00 has theoretical race window if main JOB_PARQUET_AUDITLOG_INCR runs long; Status='verified' filter closes structurally per D124 but empirical AuditLog M3 verify durations + operator approval must precede R5.4 cutover. Source: v3 gap-check Agent `a7c3f43f39535ea45` G5-4 2026-05-18. Closure target: Phase 2 R5 (before cutover).

- **B-534** (🟡 Open; HIGH; WSJF 3.0): **Snowflake data-sharing policy template + pre-configuration runbook** for CCPA Snowflake-side consequences — RB-10 extension (B-526) cites 3 options (Snowflake masking policy / DELETE+manifest / row-access policy filter); operator must pre-configure ONE with Snowflake admin; per-environment configuration runbook + policy template needed before R5 cutover. Source: v3 gap-check G5-1 2026-05-18. Closure target: Phase 2 R5 (before cutover).

- **B-535** (🟡 Open; MEDIUM; WSJF 2.5): **NEW table `General.ops.SnowflakeCcpaPurgeLog`** + migration `migrations/snowflake_ccpa_purge_log.py` (user choice 2026-05-18 per v3 gap-check G6-4 — cleaner separation than extending SnowflakeReplicationLog `Status` enum). DDL: `PurgeLogId BIGINT IDENTITY PK / ReplicationId BIGINT NOT NULL FK to SnowflakeReplicationLog / CcpaDeletionLogId BIGINT NOT NULL FK to CcpaDeletionLog / SnowflakeAction NVARCHAR(50) (masking_policy_activated/deleted/row_access_policy_filtered) / SnowflakePurgedAt DATETIME2(3) NOT NULL DEFAULT SYSUTCDATETIME() / AffectedIcebergRowCount BIGINT NULL / Actor NVARCHAR(255) NOT NULL / Justification NVARCHAR(MAX) NULL`. Migration per D92 idempotent re-run. R2.26 RB-10 extension writes rows here. Source: v3 gap-check G6-4 + user choice 2026-05-18. Closure target: Phase 2 R1 (migration) + R2.26 (wiring).

---

## §9. Risk register (15 total; R50–R64 unchanged from v4)

---

## §10. Acceptance gates (unchanged from v4)

---

## §11. Operator runbook references (RB-15 + RB-16 + RB-17 — bodies unchanged from v4; v5 B-N citations corrected)

---

## §12. Open questions for re-review (Q1–Q16 unchanged from v4)

---

## §13. Out of scope (unchanged from v4)

---

## §14. v1 → v2 → v3 → v4 → v5 delta summary

| Version | Trigger | Key change |
|---|---|---|
| v2 | v1 3-agent cohort (9 BLOCK + 38 IMPROVE) | RB-13/14 → RB-15/16; D-NEW letter → D117-D120 numeric; CCPA snapshot REQUIRED parameter; cutover 2-phase split; +25 new B-Ns |
| v3 | Option B reviewer (3 BLOCK + 7 IMPROVE) | NEW §15 Snowflake Replication Layer; SnowflakeReplicationLog table; INSERT-first crash safety; AS_OF vs CURRENT mode split; deterministic stage path; +11 new B-Ns |
| v4 | v3 gap-check (3 BLOCK + 17 IMPROVE) | B-N renumber +1 (B-496-B-534); SE-N hyphen→no-hyphen; SNOWFLAKE_STAGE_NAME canonical lock; SnowflakeCcpaPurgeLog new table per user choice; module naming locked; +3 new B-Ns (B-532/533/534) |
| **v5** | **v4 confirmation gap-check (1 BLOCK reopened + 6+ stale citations + 3 minor)** | **B-N renumber +1 again (B-497-B-535) — post-v4 commit a0f0326 reopened collision; 7 body citations corrected; B-535 body adds Justification column; delta §7.5 preamble 6→12 artifacts** |

---

## §15. Snowflake Replication Layer (unchanged structure from v4 — §15.3 DDL canonical; §15.4 lifecycle; §15.5 replay surface; §15.6 sidecar; §15.7 CCPA flow; §15.8 Phase 5 alignment; §15.9 test surface)

### §15.3 DDL (unchanged from v4 — SnowflakeReplicationLog + SnowflakeCcpaPurgeLog WITH `Justification NVARCHAR(MAX) NULL` per v4 §15.3 canonical)

```sql
-- SnowflakeReplicationLog DDL (unchanged from v4 §15.3)
-- SnowflakeCcpaPurgeLog DDL (unchanged from v4 §15.3 — includes Justification column)
```

(Full DDL preserved verbatim from v4 §15.3 — §8 B-535 body now matches the canonical DDL per v4 confirmation gap-check NEW-2 fix.)

---

**End of plan v5.** Ready for tracker merge OR final confirmation gap-check pass.
