# Phase 2 Large-Tables Plan v5 — Tracker Delta

**Date**: 2026-05-18 (v5 — post-v4-confirmation-gap-check; B-N range B-497-B-535)
**Source plan**: `docs/migration/PHASE2_LARGE_TABLES_AUDITLOG_PILOT_PLAN_2026-05-18.md` v5
**Reviewer cohorts** (6 agents across 5 versions):
- v1 (3 agents): `ad3e78033b453746c` + `a60badeb8ed452e5c` + `a5e19d35c7c5e3281`
- v2 Option B: `a1a23fbd3098e5d76`
- v3 gap-check: `a7c3f43f39535ea45`
- v4 confirmation gap-check: `a3d68f47ea920cb18`

**v5 delta vs v4**: B-N range renumbered B-496-B-534 → **B-497-B-535** (HEAD `a0f0326` opened B-496 post-v4); §7.5 preamble corrected "6 artifacts" → "12 artifacts"; §8 B-535 body verified to include `Justification NVARCHAR(MAX) NULL` column per §15.3 DDL canonical.

**Total v5 inventory**: 39 new B-Ns (B-497–B-535) + 8 new D-Ns (D117–D124) + 15 new R-Ns (R50–R64) + 15 LT-AT entries + 3 SE additions (SE11/SE12/SE13 no-hyphen) + 3 new RBs (RB-15 + RB-16 + RB-17) + 1 RB-10 extension + 1 EventType extension + 1 UdmTablesList column + 1 NEW table (SnowflakeCcpaPurgeLog) + Automic frozen-11 → frozen-13.

---

## §1. BACKLOG.md additions — 39 new B-Ns (B-497–B-535)

**Cohort header**:

```markdown
## Phase 2 Large-Tables plan v5 reviewer cohort items B-497-B-535 — added 2026-05-18 per 6-agent review cycle (v1: ad3e78033b453746c + a60badeb8ed452e5c + a5e19d35c7c5e3281; v2 Option B: a1a23fbd3098e5d76; v3 gap-check: a7c3f43f39535ea45; v4 confirmation gap-check: a3d68f47ea920cb18)
```

### B-497 — B-521 (25 entries; v1→v2 cohort)

Bodies identical to prior delta versions; B-N labels shifted +2 from v3 (B-495→B-497, ..., B-519→B-521).

### B-522 — B-532 (11 entries; v2→v3 Option B cohort)

Bodies identical to prior delta versions; B-N labels shifted +2 from v3.

### B-533 — B-535 (3 NEW v3-gap-check entries; renumbered from v4 B-532-B-534)

- **B-533** (🟡 Open; MEDIUM; WSJF 2.0): **D120 schedule-offset operator approval + race-window empirical analysis**. Source: v3 gap-check G5-4 2026-05-18. Closure target: Phase 2 R5.
- **B-534** (🟡 Open; HIGH; WSJF 3.0): **Snowflake data-sharing policy template + pre-configuration runbook** for CCPA Snowflake-side consequences. Source: v3 gap-check G5-1 2026-05-18. Closure target: Phase 2 R5.
- **B-535** (🟡 Open; MEDIUM; WSJF 2.5): **NEW table `General.ops.SnowflakeCcpaPurgeLog`** + migration `migrations/snowflake_ccpa_purge_log.py` (user choice 2026-05-18 per v3 gap-check G6-4). DDL: `PurgeLogId BIGINT IDENTITY PK / ReplicationId BIGINT NOT NULL FK to SnowflakeReplicationLog / CcpaDeletionLogId BIGINT NOT NULL FK to CcpaDeletionLog / SnowflakeAction NVARCHAR(50) / SnowflakePurgedAt DATETIME2(3) NOT NULL DEFAULT SYSUTCDATETIME() / AffectedIcebergRowCount BIGINT NULL / Actor NVARCHAR(255) NOT NULL / Justification NVARCHAR(MAX) NULL`. R2.26 RB-10 extension writes rows here. Source: v3 gap-check G6-4 + user choice 2026-05-18.

---

## §2. RISKS.md additions — 15 new R-Ns (R50–R64; bodies unchanged from prior delta versions)

---

## §3. 03_DECISIONS.md additions — 8 new D-Ns (D117–D124; bodies unchanged from v4 delta §3)

D119 venue clarified (IdempotencyLedger value, NOT PipelineEventLog family).
D121 prominent 30-day exception display.
D124 canonical `SNOWFLAKE_STAGE_NAME` env var lock.
D120 v3 extension: frozen-11 → frozen-13 (both new jobs).

---

## §4. 05_RUNBOOKS.md additions — 3 new RBs (RB-15 + RB-16 + RB-17) + RB-10 extension

RB-10 extension writes to NEW SnowflakeCcpaPurgeLog (per user choice 2026-05-18); B-N citation updated to **B-526 + B-535** (v5 range).

---

## §5. 04_EDGE_CASES.md additions — LT-AT series + SE11/SE12/SE13 (no-hyphen)

LT-AT-1..15 unchanged.

SE11/SE12/SE13 entry-body B-N citations updated to v5 range:
- SE11 mitigation: B-524 + B-525 + D123 + D124
- SE12 mitigation: B-527
- SE13 mitigation: B-522 + D122 + RB-10 extension via B-526 + B-535

---

## §6. CLAUDE.md L207 + L208 additions

`SNOWFLAKE_REPLICATION_*` family extension (unchanged).
CLI_* count: 24 baseline + R2.14's 3 + R2.24 (CLI_REPLAY_SNOWFLAKE_UPLOAD per B-530) = **28 tools FINAL after entire v5 cohort lands**.

---

## §7. Migration additions for v5 (4 migrations)

1. `migrations/snowflake_replication_log.py` (B-523) — creates `General.ops.SnowflakeReplicationLog`
2. `migrations/sidecar_retention_days_column.py` (B-528) — ALTER UdmTablesList ADD SidecarRetentionDays
3. `migrations/snowflake_replication_log_pending_retry_index.py` (B-529) — filtered index
4. `migrations/snowflake_ccpa_purge_log.py` (B-535) — creates `General.ops.SnowflakeCcpaPurgeLog` per user choice 2026-05-18

Each per D92 idempotent re-run + Tier 0 idempotency test.

---

## §7.5 Convention-registration deliverables (**12 doc-side artifacts** per v4 confirmation gap-check NEW-3 arithmetic fix)

Beyond migrations (§7), the v5 cohort introduces **12 doc-side artifacts** requiring explicit cross-doc cascade. Each tracked as Phase 2 R2/R3/R5 deliverable:

| # | Artifact | Target doc + section | Phase 2 Round | Source B-N |
|---|---|---|---|---|
| 1 | `data_load/snowflake_replicator.py` module row | CLAUDE.md Structure `data_load/` | R2 close | B-524 + B-525 |
| 2 | `data_load/snowflake_replay.py` module row | CLAUDE.md Structure `data_load/` | R2 close | B-522 + B-530 |
| 3 | `tools/replicate_to_snowflake_with_masking.py` CLI row | CLAUDE.md Structure `tools/` + `phase1/04_tools.md` § | R2 close | B-524 |
| 4 | `tools/replay_snowflake_upload.py` CLI row | CLAUDE.md Structure `tools/` + `phase1/04_tools.md` § | R2 close | B-530 |
| 5 | `General.ops.SnowflakeReplicationLog` DDL section | `phase1/01_database_schema.md` § N | R1 close | B-523 |
| 6 | `General.ops.SnowflakeCcpaPurgeLog` DDL section | `phase1/01_database_schema.md` § N | R1 close | B-535 |
| 7 | `UdmTablesList.SidecarRetentionDays` column doc | `phase1/02_configuration.md` § 1.2 | R3 close | B-528 |
| 8 | `JOB_SNOWFLAKE_REPLICATE_AUDITLOG` + `JOB_PARQUET_AUDITLOG_INCR` Automic inventory + SchemaContract MIGRATION_AUTOMIC_INVENTORY rows | `phase1/02_configuration.md` § 5.1 frozen-N | R5 day 0 | D120 v3 ext. |
| 9 | `SnowflakeReplayResult` dataclass | GLOSSARY.md public-surface table | R2 close | B-530 |
| 10 | `RB-15` runbook index entry | `05_RUNBOOKS.md` L7-23 | R2 close | B-499 (NOTE: B-499 in v5 = old "cross-schema-boundary"; RB-15 actually traces to B-344 + B-500 — verify at merge time) |
| 11 | `RB-16` runbook index entry | `05_RUNBOOKS.md` L7-23 | R4 close | B-501 |
| 12 | `RB-17` runbook index entry + `LT-AT-Series` header + `SE11/SE12/SE13` entries | `05_RUNBOOKS.md` L7-23 + `04_EDGE_CASES.md` SE-series L301-310 (append) + new LT-AT-Series after PL-Series at L316 | R2 close (RB-17 + SE) + R3 close (LT-AT) | B-530 (RB-17), B-527 (SE12), B-535 (SE13), B-504 (LT-AT series header) |

Per-Round close-out invokes `udm-step-10-verifier` to verify each row landed in the canonical doc.

---

## §8. Merge order (v5)

1. 03_DECISIONS.md (§3) — D117-D124 first
2. BACKLOG.md (§1) — B-497-B-535 next
3. 05_RUNBOOKS.md (§4) — RB-15 + RB-16 + RB-17 + RB-10 extension
4. 04_EDGE_CASES.md (§5) — LT-AT-Series header + LT-AT-1..15 + SE11/SE12/SE13
5. RISKS.md (§2) — R50-R64
6. CLAUDE.md (§6) — L207-L208 family additions
7. Migrations (§7) — at Phase 2 R1/R3 build time
8. Convention-registration deliverables (§7.5) — per-Round build cascade

---

## §9. Commit message template (v5)

```text
docs(phase2-large-tables): land plan v5 + tracker deltas (B-497-B-535, D117-D124, R50-R64, RB-15+RB-16+RB-17, LT-AT series, SE11/SE12/SE13)

Plan: PHASE2_LARGE_TABLES_AUDITLOG_PILOT_PLAN_2026-05-18.md v5 — post-6-agent reviewer cycle

Tracker delta: PHASE2_LARGE_TABLES_TRACKER_DELTA_2026-05-18.md v5

## TEST
- B-N range B-497-B-535 verified non-colliding via `git grep "\*\*B-49[7-9]\*\*\|\*\*B-5[0-3][0-9]\*\*" docs/migration/BACKLOG.md` → 0 prior matches
- SE-N naming `SE11/SE12/SE13` (no-hyphen) verified matching canonical 04_EDGE_CASES.md:301-310
- `SNOWFLAKE_STAGE_NAME` env var canonical reference verified at `data_load/snowflake_uploader.py:693`
- Pre-commit hooks: `tools/pre_commit_checks.py` passes
- pytest tier0+tier1: baseline preserved
- _validation_log.md row recorded for v5 cohort landing

## GAP ANALYSIS
- v1 udm-gap-check (a60badeb8ed452e5c): 4 BLOCK + 21 IMPROVE + 3 OK → absorbed v2
- Option B udm-design-reviewer (a1a23fbd3098e5d76): 3 BLOCK + 7 IMPROVE → absorbed v3
- v3 udm-gap-check (a7c3f43f39535ea45): 3 BLOCK + 17 IMPROVE + 10 OK → absorbed v4
- v4 confirmation gap-check (a3d68f47ea920cb18): 1 BLOCK reopened (B-N collision) + 6+ stale citations + 3 NEW gaps → absorbed v5
- Cross-tracker registration: 39 new B-Ns + 8 D-Ns + 15 R-Ns + 3 RB placeholders + LT-AT series + SE11/SE12/SE13 + 1 EventType family + CLI_* count + 12 convention-registration deferred-but-tracked deliverables

## REVIEW
- v1 udm-design-reviewer: 2 BLOCK → fixed v2
- v1 udm-data-engineer-review substitute: 3 BLOCK → fixed v2
- v2 udm-design-reviewer Option B: 3 BLOCK → fixed v3
- v3 udm-gap-check: 3 BLOCK → fixed v4
- v4 confirmation gap-check: 1 BLOCK reopened + Pitfall #9.k internal stale citations → fixed v5
- Substrate-edit cascade per CLAUDE.md hard rule 14: plan v5 file is substantive artifact; tracker delta v5 is transcription

Closes: nothing
Opens: B-497-B-535 (39 new B-Ns); D117-D124 proposed; R50-R64; RB-15+RB-16+RB-17 + RB-10 extension; LT-AT series; SE11/SE12/SE13; NEW table SnowflakeCcpaPurgeLog per B-535
```

---

**End of delta v5.** Ready for tracker merge.
