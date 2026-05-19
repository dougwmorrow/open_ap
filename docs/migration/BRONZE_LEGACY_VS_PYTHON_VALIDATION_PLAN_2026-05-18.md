# Bronze Legacy vs Python — Historic Backfill + Validation Watchdog Plan

**Date authored**: 2026-05-18
**Branch**: `round-6-post-merge-tracking`
**Status**: 🟡 Proposed (plan-only; no code lands this session)
**Owner**: Pipeline lead
**Concurrent session note**: SESSION_RESUME.md indicates an active session pivot-awaiting; this plan introduces **zero file overlap** with active session's hot files (`tools/check_commit_msg.py`, `tests/tier0/test_check_commit_msg.py`, `SESSION_RESUME.md`). Phase 1 build deferred until pivot direction is known. See §10 for full non-conflict statement.

---

## §0. Planning session provenance

**Skills invoked during this planning session** (per `udm-planning-session-startup` v0.2 + `docs/migration/PLANNING_DISCIPLINE.md` matrix):

| Skill | Invoked at | Scope reference | Rationale |
|---|---|---|---|
| `udm-planning-session-startup` | 2026-05-18 (session start) | Hard rule 13 | Trigger-phrase match: "Come up with a plan to address this effort" |
| `udm-checks-and-balances` | 2026-05-18 (plan attestation; inline 5-gate-lite on plan deliverable) | PS-1 + PS-8 mandatory | Plan touches architectural design + introduces D-N candidates |
| `udm-decision-recorder` | 2026-05-18 (§3 D-N candidate enumeration) | PS-8 mandatory | 11 D-N candidates surfaced; recorded inline pending pipeline-lead 🟢 lock approval |
| `udm-execution-classifier` | 2026-05-18 (§4.1 + §5.1 classification inline) | PS-3 mandatory | Two new tools introduced — classification recorded against (Manual vs Scheduled) × (One-time vs Recurring) matrix |
| `udm-data-engineer-review` | 2026-05-18 (§4.2 LegacySeedManifest DDL + §5.3 ReconciliationLog extension) | PS-4 mandatory | DDL change to General.ops; SQL Server / SCD2 / Polars design choices to review |
| `udm-edge-case-validator` | 2026-05-18 (§8 edge case mapping) | Always-mandatory at signoff | Walks V/S/M/B/P/SE/T series for relevance to this plan |
| `udm-runbook-author` | 2026-05-18 (§7 RB-N spec — light coverage; full authoring deferred to Phase D) | PS-5 conditional → ACTIVATED | RB-N drift-triage runbook scoped in this plan |
| `superpowers-verification-before-completion` | 2026-05-18 (pre-completion gate; before claiming plan ready) | Always-mandatory | Iron Law: no completion claims without fresh verification evidence |
| `udm-post-edit-verification` | 2026-05-18 (3-step cascade after plan-deliverable Write) | Always-mandatory per CLAUDE.md hard rule 14 | TEST + GAP ANALYSIS + REVIEW after substantive edit |
| `udm-gap-check` | 2026-05-18 (pre-author self-audit + planned post-author independent reviewer spawn) | Always-mandatory at attestation | 6-category audit; one self-audit completed before authoring (caught 11 plan-content gaps); independent reviewer planned post-Write |

**Skills available on-demand (deferred — not activated up-front per `PLANNING_DISCIPLINE.md` §2.5 minimum-viable-set):**

- `udm-test-author` — defer to Phase 1 code-build session (test sketches at spec time recorded inline; full pytest authoring is build-time)
- `udm-context-loader` — only invoked when spawning a sub-agent during this session
- `udm-researcher` — light grounding on parallel-run validation industry patterns (may invoke if open Q surfaces during plan authoring)
- `udm-brainstorm` — decisions already chosen via AskUserQuestion; not needed unless review surfaces new open Q
- `udm-progress-logger` / `udm-step-10-verifier` — N/A (plan-only session; no code or new public surface)
- `superpowers-systematic-debugging` — N/A (no bug / test failure investigation in this session)

**Sub-agents spawned + skill inheritance:**

| Sub-agent | Spawned at | Skills inherited (per CLAUDE.md hard rule 13 §3.1 contract) |
|---|---|---|
| (planned) `udm-design-reviewer` for §3 + §4 + §5 architectural review | TBD post plan-deliverable Write | Mandatory: `udm-checks-and-balances`, `udm-decision-recorder`, `udm-data-engineer-review`, `udm-edge-case-validator`. Conditional: `udm-runbook-author`, `udm-execution-classifier`. |
| (planned) independent `udm-gap-check` reviewer | TBD post plan-deliverable Write | 6-category G1-G6 audit on the plan-as-authored |

(If pipeline-lead approves the plan without these reviewer spawns, this table will be amended at the approval-commit moment.)

---

## §1. Executive summary

### §1.1 The need

Two adjacent-but-distinct problems, surfaced in one user-direction 2026-05-18:

1. **Historic backfill (DNA + EPICOR; CCM deferred)** — capture legacy `UDM_Bronze.{lowercase(SourceName)}.{table_name}` SCD2 history into the python pipeline's `UDM_Bronze.{UPPERCASE_SourceName}.{table_name}_scd2_python` (or unsuffixed when `StripSuffix=1`) so python pipeline runs forward from a fully-historied bootstrap. Bootstrap mode per user direction (Q1 = python NOT yet running forward on these tables).
2. **Ongoing validation watchdog (multi-month parallel-run)** — during legacy decommission, compare legacy vs python Bronze for the same source PKs; surface drift; let an operator runbook (RB-N) triage findings.

### §1.2 4-phase shape

| Phase | Scope | Sequencing | Owner |
|---|---|---|---|
| **A** | Historical backfill of DNA + EPICOR via `tools/seed_from_legacy_batch.py` + `General.ops.LegacySeedManifest` table + pre/post-seed gates | Build first; sequenced before pipeline forward-run on these tables | Claude builds; operator executes |
| **B** | Validation watchdog via `tools/compare_legacy_vs_python_bronze.py` + `cdc/reconciliation/legacy_vs_python.py` + `ReconciliationLog` extension (`CheckType` enum); manifest-aware findings classification | Build after Phase A lands; runs continuously for ~few months during parallel-run | Claude builds; operator schedules + reviews findings |
| **C** | CCM bespoke solution | **DEFERRED** — placeholder section only; design out-of-scope for this plan | TBD; later session |
| **D** | Investigation runbook (RB-N) for drift triage | Spec'd in this plan §7; full authoring deferred until Phase B has surfaced enough finding-types to inform the runbook structure | Claude authors; operator drives |

### §1.3 What this plan does NOT commit to

- **No code this session.** Phase 1 build sequencing depends on the active session's pivot direction (SESSION_RESUME Option C touches `cdc/reconciliation/`).
- **No CCM design.** Phase C is explicitly placeholder.
- **No automatic remediation.** Watchdog surfaces drift; runbook decides per-finding; no auto-repair.
- **No timeline.** Sequencing is logical (A → B → D); calendar-dates set by pipeline-lead.

---

## §2. Context + existing infrastructure

### §2.1 What `cdc/reconciliation/` already does

The subpackage covers THREE comparison axes (per `cdc/reconciliation/__init__.py`):

1. **Source ↔ Stage (CDC)** — `reconcile_table` / `reconcile_table_windowed` in `core.py`. Full column-by-column or windowed by `SourceAggregateColumnName`.
2. **Stage ↔ python Bronze (SCD2)** — `reconcile_bronze` in `scd2_integrity.py`. Detects hash mismatches, orphaned active rows, missing rows, duplicate active PKs.
3. **SCD2 structural integrity** — `validate_scd2_integrity`. Overlapping intervals, zero-active PKs, dual date-pair invariants per SCD2-P1-a/b/c/e/f/R2/R4.

Supporting axes: `reconcile_active_pks` (E-7), `reconcile_counts` (W-11), `detect_distribution_shift` (B-10), `reconcile_aggregates` (E-17), `reconcile_transformation_boundary` (B-11), `check_referential_integrity` (B-12), `VersionVelocityResult` (E-13).

Persistence: `General.ops.ReconciliationLog` (canonical DDL at `phase1/01_database_schema.md` §14) — generic schema with `CheckType` discriminator + `Metadata` JSON + `Severity` + `Acknowledged` columns. Used by S14 (reconciliation findings) for operator-acknowledge gate.

### §2.2 What `tools/seed_from_legacy.py` already does

- Single-table seed: reads legacy table; drops legacy-only columns (`UdmCreateId/UdmCreateDateTime/UdmUpdateId/UdmUpdateDateTime/UdmSource/UdmHash/_scd2_key`); recomputes `UdmHash` over source-columns-only via python algorithm; backfills `UdmSourceBeginDate` via R-2 waterfall (mirrors `scd2.engine._build_source_begin_expr`); stamps Flag-based `UdmSourceEndDate` + `UdmScd2Operation` + `UdmModifiedBy='legacy_seed'`.
- Schema-drift safe (pads NULL for python target cols missing from legacy).
- Atomic BCP to Bronze + non-atomic BCP to Stage (Flag=1 rows only).
- Pre-flight: requires python target tables to exist (auto-created by no-op pipeline pass).

### §2.3 Gaps for the new requirements

**Phase A historical backfill gaps:**

| Gap | Impact | Closure path |
|---|---|---|
| Single-table only; no `--source X --all` batch mode | Operator must script a shell loop for ~200+ tables | New `tools/seed_from_legacy_batch.py` wrapper |
| Legacy table FQN required as explicit arg | No auto-resolution from convention | Wrapper derives `UDM_Bronze.{lowercase(SourceName)}.{table_name}` per D-LP-3 below |
| No server-side seed manifest | Operators can't query "which tables seeded" via SQL | New `General.ops.LegacySeedManifest` table per D-LP-1 |
| No post-seed parity gate | Errors detected only at next pipeline run (or never) | Wrapper invokes cheap parity check inline per D-LP-7 |
| Not D74/D75/D76 compliant | Inconsistent with canonical tool contract | Wrapper authored to canonical contract; `seed_from_legacy.py` brought up to spec inline if friction surfaces during Phase A |
| No resume-safety / re-seed guardrails | Re-running silently truncate-and-reloads | Manifest pre-flight check rejects already-seeded tables without `--force` |
| No CCM hard-error | Operator could accidentally seed CCM | Wrapper hard-errors on `--source CCM` until Phase C lands |

**Phase B validation watchdog gaps:** no existing legacy ↔ python comparator. Closest precedent is the same-pipeline `Stage ↔ python Bronze` comparator (`reconcile_bronze`), but it doesn't address cross-pipeline equivalence. New module + new tool.

---

## §3. Decisions surfaced (D-N candidates)

The following 11 decisions emerged during this planning session and need pipeline-lead 🟢 lock before Phase 1 build commences. Numbering prefix `D-LP-N` (Legacy/Python) reserved pending allocation against the canonical `03_DECISIONS.md` D-N sequence at next round close-out.

### D-LP-1 — Seed manifest persistence: new `General.ops.LegacySeedManifest` table
**Rationale**: per-table SQL queryability ("which DNA tables seeded; which still pending") + multi-week operator work survives session boundaries. PipelineEventLog reuse insufficient (JSON-field extraction friction).
**User choice**: 2026-05-18 AskUserQuestion Q2 = "New General.ops.LegacySeedManifest table".
**Pillar served**: Audit-grade + Operationally stable.
**Schema**: see §4.2.

### D-LP-2 — Backfill mode: bootstrap (truncate-then-load)
**Rationale**: python pipeline NOT yet running forward on DNA + EPICOR tables; simplest path; matches existing `seed_from_legacy.py` truncate-then-load implicit pattern.
**User choice**: 2026-05-18 AskUserQuestion Q1 = "Bootstrap".
**Pillar served**: Operationally stable.
**Implication**: pre-flight rejects tables with non-empty python target (or `--force` override).

### D-LP-3 — Legacy table naming: convention-derived `UDM_Bronze.{lowercase(SourceName)}.{table_name}`
**Rationale**: matches legacy convention verbatim; no UdmTablesList schema change.
**User choice**: 2026-05-18 AskUserQuestion (first batch) Q3 = "Convention-derived (Recommended)".
**Pillar served**: Operationally stable.
**Implication**: tool checks existence; manifest Status='no_legacy_source' if absent (skip, don't fail).

### D-LP-4 — Watchdog comparison scope: active rows + full history equivalence as default
**Rationale**: peace-of-mind use case (multi-month parallel-run watchdog) wants comprehensive coverage; user explicitly chose Option B "Active + full history default" over Option A "Active only".
**User choice**: 2026-05-18 AskUserQuestion (first batch) Q2 = "Active rows + full history equivalence as default".
**Pillar served**: Audit-grade + Traceability.
**Implication**: large-table windowed mode (per §5.9) required for tables exceeding `_RECON_MAX_ROWS=50M`.

### D-LP-5 — Watchdog use case: parallel-run watchdog (multi-month)
**Rationale**: legacy decommission with peace-of-mind validation over a multi-month parallel-run window; recurring weekly cadence preferred over one-time pre-decommission gate.
**User choice**: 2026-05-18 AskUserQuestion (first batch) Q1 = "Ongoing parallel-run watchdog".
**Pillar served**: Audit-grade + Operationally stable.
**Implication**: tool registered in `phase1/02_configuration.md` §5.1 frozen-N Automic inventory (scheduled-recurring) per MIGRATION_AUTOMIC_INVENTORY event. Cadence proposal: weekly per-table rotation (full-history mode) + nightly counts-only sweep across all tables.

### D-LP-6 — Failure handling: per-table isolation + cheap parity gate
**Rationale**: independent per-table seed avoids head-of-line blocking; cheap post-seed gate (counts + active-PK diff) catches gross errors fast; deep validation deferred to Phase B watchdog.
**User choice**: 2026-05-18 AskUserQuestion (second batch) Q3 = "Per-table isolation + cheap parity gate (Recommended)".
**Pillar served**: Operationally stable.
**Implication**: per-table failures isolated to manifest row; batch continues; operator triages via runbook.

### D-LP-7 — Drift contract: surface DRIFT, not BLAME
**Rationale**: during multi-month parallel-run, either pipeline could be wrong on a finding-by-finding basis. Tool MUST NOT assert which pipeline is "correct"; runbook decides per-finding via operator investigation.
**Author choice**: 2026-05-18 plan-author proposal pending pipeline-lead approval.
**Pillar served**: Audit-grade.
**Implication**: result vocabulary uses neutral terms (DRIFT, NON-EQUIVALENT, PK-IN-LEGACY-NOT-PYTHON) — NOT "wrong" / "error" / "incorrect".

### D-LP-8 — PII column handling: discover from `UdmTablesList.PiiColumnList` + skip with categorization
**Rationale**: python tokenizes per D6 + P5; legacy stores plaintext (or different scheme). Direct value compare → 100% false-positive on PII columns. Two options: (a) decrypt python tokens via SP-2 with operator justification + audit on every watchdog run (heavy + leaks plaintext into watchdog logs — security violation per SECURITY_MODEL.md), (b) skip PII columns from value comparison and record them as `pii_skipped` in metadata (lightweight; preserves security model).
**Author choice**: Option (b) — skip with categorization. Pipeline-lead may override if blank-box verification of PII tokenization correctness is in scope.
**Pillar served**: Audit-grade + Security (PII).
**Edge case ref**: P-series (PII / Encryption / Tokenization Vault).
**Implication**: `LegacyPythonReconciliationResult.pii_columns_skipped: list[str]` + drift counter excludes PII column mismatches.

### D-LP-9 — Version-key strategy for full-history mode: `(PK, source-content-hash-recomputed)` with python algorithm
**Rationale**: `(PK, UdmEffectiveDateTime)` mismatches because load-time differs between pipelines; `(PK, UdmSourceBeginDate)` fails because legacy lacks the column natively. Workable pragmatic version key: for each (PK, version) pair on legacy, recompute python `UdmHash` over source columns and match python rows by `(PK, UdmHash)`. Hash-based version-key handles late-arrival close-timing differences gracefully (same content = same hash = matched version regardless of close-time).
**Author choice**: 2026-05-18 plan-author proposal pending pipeline-lead approval. **Open Q**: alternative is to relax history comparison to "PK-and-content-only" without version-pairing (count distinct source content states per PK per side, then diff). Cheaper but less precise on version-count audits.
**Pillar served**: Audit-grade + Idempotent.
**Edge case ref**: SCD2-P1-a (dual date-pair), SCD2-P1-f (datetime precision invariant).
**Implication**: full-history mode is HASH-RECOMPUTE-HEAVY — adds ~30s per million rows per legacy table (Polars vectorized).

### D-LP-10 — Stability window discipline: per-table L_99 from `cdc.lateness_profiler` LatenessReport
**Rationale**: per M2/M4/G8 + B-11 boundary reconciliation precedent, legitimate drift exists in trailing L_99 hours (late-arriving source updates not yet processed by both pipelines). Hard-skip drift findings for rows where `MAX(UdmSourceBeginDate, UdmEffectiveDateTime) > NOW() - L_99` per table. Default L_99 fallback when no LatenessReport exists: 48 hours.
**Author choice**: 2026-05-18 plan-author proposal pending pipeline-lead approval.
**Pillar served**: Operationally stable.
**Edge case ref**: M-series (M2 bimodal late-arrivals; M4 unreliable LASTMOD), G-series (G8 backfill during outage).
**Implication**: comparator CLI flag `--stability-window-hours N` (default per-table from LatenessReport; falls back to 48).

### D-LP-11 — CCM exclusion: hard-error on `--source CCM` until Phase C bespoke solution lands
**Rationale**: CCM has known different legacy structure; user direction "CCM will need a very specific solution that we can work on later"; defense-in-depth prevents accidental run with wrong assumptions.
**User choice**: implicit from 2026-05-18 user-direction.
**Pillar served**: Operationally stable.
**Implication**: both Phase A seed batch tool AND Phase B watchdog tool hard-error on `--source CCM` with explicit message: "CCM source deferred per Phase C of validation plan; see docs/migration/BRONZE_LEGACY_VS_PYTHON_VALIDATION_PLAN_2026-05-18.md §6".

---

## §4. Phase A — Historical backfill (DNA + EPICOR)

### §4.1 Tool spec: `tools/seed_from_legacy_batch.py`

**Execution classification** (per `udm-execution-classifier`):
- Trigger: **Manual** (operator-driven during legacy decommission)
- Frequency: **One-time** (per-table once-and-done; resume-safe via manifest)
- Tracker routing: `ONE_OFF_SCRIPTS.md` (NOT `phase1/02_configuration.md` §5.1 — not scheduled)

**Signature**:
```
python3 tools/seed_from_legacy_batch.py \
  --source DNA \                     # required; SourceName (DNA / EPICOR; CCM rejected)
  [--table ACCT]                      # optional; single-table mode for resume / retry
  [--force]                           # optional; overrides already-seeded check
  [--manifest-only]                   # optional; emit manifest pre-flight report w/o seeding
  [--dry-run | --apply]               # D75 dry-run default; --apply commits
  [--max-parallel N]                  # optional; default 1 (per-table serial); operator opt-in to N
```

**Exit codes** (D74):
- `EXIT_SUCCESS = 0` — all targeted tables seeded successfully (manifest Status='completed')
- `EXIT_WARNING = 1` — one or more tables skipped or failed; batch continued; manifest reflects per-table state
- `EXIT_BLOCKED = 2` — pre-flight rejected (CCM source / no UdmTablesList rows / Bronze auto-create needed)
- `EXIT_FATAL = 3` — unrecoverable error (DB unreachable / credential failure)

**EVENT_TYPE** (D76): `CLI_SEED_FROM_LEGACY_BATCH` (would be CLI_* family member 25 — confirm against current L207 count at build time; Option A enforcement now requires count update inline). Per-table seed events written as PipelineEventLog rows with `EventType='LEGACY_SEED'` (with composite type per D-LP-1).

**Audit row** (D76): per-invocation row to `_session_logs/cli_seed_from_legacy_batch_<date>.log` with args / actor / table list / per-table verdicts.

### §4.2 Schema additions: `General.ops.LegacySeedManifest` (DDL spec)

Per D-LP-1. **Forward-only additive DDL per D92 + SchemaContract row + MIGRATION_LEGACY_SEED_MANIFEST event type.**

```sql
CREATE TABLE General.ops.LegacySeedManifest (
    ManifestId          BIGINT IDENTITY(1,1) NOT NULL,
    SourceName          NVARCHAR(128)  NOT NULL,
    TableName           NVARCHAR(256)  NOT NULL,
    LegacyTableFqn      NVARCHAR(512)  NOT NULL,
    PythonTargetBronze  NVARCHAR(512)  NOT NULL,
    PythonTargetStage   NVARCHAR(512)  NOT NULL,
    Status              NVARCHAR(32)   NOT NULL,
    SeedStartedAt       DATETIME2(3)   NOT NULL,
    SeedCompletedAt     DATETIME2(3)   NULL,
    LegacyRowCount      BIGINT         NULL,
    SeededBronzeRows    BIGINT         NULL,
    SeededStageRows     BIGINT         NULL,
    LegacyActivePkCount BIGINT         NULL,
    PythonActivePkCount BIGINT         NULL,
    WaterfallConfigJson NVARCHAR(MAX)  NULL,    -- snapshot of scd2_date_columns + default_begin_date
    ExcludeFromHashJson NVARCHAR(MAX)  NULL,    -- snapshot of UdmTablesList.ExcludeFromHash
    SchemaDriftJson     NVARCHAR(MAX)  NULL,    -- columns padded NULL per seed_from_legacy.py drift logic
    SeededBy            NVARCHAR(128)  NOT NULL,
    ErrorMessage        NVARCHAR(MAX)  NULL,
    PostSeedParityJson  NVARCHAR(MAX)  NULL,    -- post-seed cheap-parity gate result snapshot
    CONSTRAINT PK_LegacySeedManifest PRIMARY KEY CLUSTERED (ManifestId),
    CONSTRAINT CK_LegacySeedManifest_Status CHECK (Status IN (
        'in_progress', 'completed', 'failed',
        'skipped_no_legacy_source', 'skipped_target_not_created', 'skipped_target_not_empty',
        'skipped_already_seeded', 'skipped_ccm', 'post_seed_parity_failed'
    ))
);

CREATE UNIQUE INDEX UX_LegacySeedManifest_SourceTable_Active
    ON General.ops.LegacySeedManifest (SourceName, TableName)
    WHERE Status = 'completed';

CREATE INDEX IX_LegacySeedManifest_PendingFailed
    ON General.ops.LegacySeedManifest (Status, SeedStartedAt DESC)
    WHERE Status IN ('in_progress', 'failed', 'post_seed_parity_failed');
```

**SchemaContract row** (per D92): appended at table-creation migration; ContractKey = `LegacySeedManifest:v1`.

**Migration script home**: `migrations/legacy_seed_manifest_init.py` (forward-only DDL + SchemaContract write).

**DELETE permission**: denied at role level per D45.6 v2 (manifest is audit; rows are NEVER physically DELETEd; Status flip pattern for re-seed scenarios — completion supersedes prior manifest row via `Status='completed'` filtered unique index; failed/skipped rows persist for audit trail).

### §4.3 Pre-flight checklist (per-table)

Run before each per-table seed; record verdict in manifest row:

| Check | Pass condition | Fail action |
|---|---|---|
| CCM source filter | `SourceName != 'CCM'` | Hard-error; batch rejects entire run |
| UdmTablesList row exists | `SELECT 1 FROM General.dbo.UdmTablesList WHERE SourceName=? AND TableName=?` returns 1 | Skip with Status='skipped_no_udm_row' |
| Legacy table exists | `OBJECT_ID('UDM_Bronze.{lowercase(SourceName)}.{TableName}')` not NULL | Skip with Status='skipped_no_legacy_source' |
| Python target Bronze exists | `OBJECT_ID(table_config.bronze_full_table_name)` not NULL | Skip with Status='skipped_target_not_created' (operator must run no-op pipeline pass to auto-create) |
| Python target Stage exists | `OBJECT_ID(table_config.stage_full_table_name)` not NULL | Skip with Status='skipped_target_not_created' |
| Python target Bronze empty | `SELECT TOP 1 1 FROM <target_bronze>` returns 0 rows | Skip with Status='skipped_target_not_empty' (unless `--force`) |
| Not already successfully seeded | No prior manifest row with Status='completed' for `(SourceName, TableName)` | Skip with Status='skipped_already_seeded' (unless `--force`) |
| SCD2DateColumns configured OR default_begin_date | `table_config.scd2_date_columns` non-empty OR `table_config.default_begin_date` non-NULL | Warn only (seed_from_legacy.py handles fallback to UdmEffectiveDateTime; not blocking) |

### §4.4 Per-table seed flow

Per-table flow within the batch:

1. **Insert manifest row** with Status='in_progress', SeedStartedAt=NOW().
2. **Invoke single-table seed logic** — either by subprocess to existing `seed_from_legacy.py` OR by extracting its core into `tools/_seed_from_legacy_core.py` callable. Recommendation: extract core into a callable; subprocess overhead non-trivial across 100+ tables. (Build-time decision; both routes work.)
3. **Capture per-table outputs**: LegacyRowCount / SeededBronzeRows / SeededStageRows / SchemaDriftJson / WaterfallConfigJson / ExcludeFromHashJson.
4. **Run post-seed parity gate** (§4.5).
5. **Flip manifest Status** to 'completed' (parity passed) OR 'post_seed_parity_failed' (parity failed) OR 'failed' (seed itself threw).
6. **Continue to next table** regardless of per-table outcome (per D-LP-6).

### §4.5 Post-seed parity gate (cheap mode)

Per D-LP-6. Three checks; pass-all required for Status='completed':

| Check | Predicate | Severity |
|---|---|---|
| Row count parity | `COUNT(*) legacy == COUNT(*) python_bronze` (across ALL Flag values) | 🔴 BLOCK on mismatch |
| Active-PK count parity | `COUNT(*) WHERE UdmActiveFlag=1` matches both sides | 🔴 BLOCK on mismatch |
| Active-PK set difference | `EXCEPT` on PK columns yields 0 PKs on either side | 🔴 BLOCK on mismatch |

**Result row** written to `PostSeedParityJson` column in manifest with per-check verdict + sample drift PKs (up to 100) for triage.

**NO column-value comparison** in the cheap gate — that's Phase B watchdog territory. The cheap gate catches gross seed errors (wrong table, partial load, BCP truncation, atomic-vs-non-atomic crash mid-load).

### §4.6 Manifest taxonomy

`Status` enum (per CHECK constraint above):

| Status | Meaning | Operator action |
|---|---|---|
| `in_progress` | Seed running OR seed crashed mid-flight | Investigate; manual cleanup; re-run with `--force` if recoverable |
| `completed` | Seed + post-seed parity gate both passed | None — table is ready for python pipeline forward-run |
| `failed` | Seed itself threw before parity gate | Investigate ErrorMessage; re-run after fix |
| `post_seed_parity_failed` | Seed completed but cheap parity gate found drift | Investigate PostSeedParityJson; re-run with `--force` or per-table fix |
| `skipped_no_legacy_source` | Legacy table doesn't exist | No action — table never had legacy counterpart |
| `skipped_target_not_created` | Python target Bronze/Stage doesn't exist | Run no-op pipeline pass; then re-run seed |
| `skipped_target_not_empty` | Python target has rows already (and not `--force`) | Triage: is python already running on this table? if so, NOT a bootstrap case — DO NOT proceed; if not, truncate + re-seed with `--force` |
| `skipped_already_seeded` | Prior `Status='completed'` row exists | Re-run with `--force` only if intentional |
| `skipped_ccm` | CCM source rejected | Wait for Phase C |

### §4.7 Resume semantics

- Re-running batch is safe: pre-flight skips already-completed tables; failed/skipped tables NOT auto-retried (operator opts in via `--force` or `--table`).
- Idempotent on completed tables: filtered unique index `UX_LegacySeedManifest_SourceTable_Active` prevents double-completion.
- Per-table state machine: `in_progress` → `completed` | `failed` | `post_seed_parity_failed`; or `in_progress` skipped pre-flight → terminal skip state.
- No mid-state recovery for `in_progress` rows — operator manually flips Status to 'failed' (via UPDATE) if a crash mid-seed left a phantom row.

---

## §5. Phase B — Validation watchdog

### §5.1 Tool spec: `tools/compare_legacy_vs_python_bronze.py`

**Execution classification**:
- Trigger: **Scheduled** (weekly Automic per D-LP-5) + **Manual** (operator on-demand for incident response)
- Frequency: **Recurring** (multi-month parallel-run window)
- Tracker routing: `phase1/02_configuration.md` §5.1 frozen-N Automic inventory (NEW entry) — MIGRATION_AUTOMIC_INVENTORY event when added

**Signature**:
```
python3 tools/compare_legacy_vs_python_bronze.py \
  --source DNA \                          # required; DNA/EPICOR; CCM hard-rejected per D-LP-11
  [--table ACCT]                          # optional; single-table mode
  [--all]                                 # optional; all tables for source (default if --table absent)
  --mode {counts_only,active,full_history} \
  [--sample-size N]                       # optional; row sample for full_history mode
  [--stability-window-hours N]            # optional; defaults to per-table L_99 from LatenessReport
  [--dry-run | --apply]                   # D75; --apply writes findings to ReconciliationLog
  [--manifest-aware]                      # optional; default ON when manifest table exists
```

**Exit codes** (D74):
- `EXIT_SUCCESS = 0` — all targeted tables clean (no drift; `is_clean == True`)
- `EXIT_WARNING = 1` — drift found; non-blocking (surface to operator runbook)
- `EXIT_BLOCKED = 2` — pre-flight rejected (CCM / table not in manifest as completed)
- `EXIT_FATAL = 3` — unrecoverable

**EVENT_TYPE** (D76): `CLI_COMPARE_LEGACY_VS_PYTHON_BRONZE`. Per-table finding rows written to `General.ops.ReconciliationLog` with `CheckType` discriminator (see §5.3).

### §5.2 Module spec: `cdc/reconciliation/legacy_vs_python.py`

**Public surface** (to register in CLAUDE.md Structure + GLOSSARY public-surface):
- `reconcile_legacy_vs_python(table_config, *, mode, sample_size, stability_window_hours, exclude_columns) -> LegacyPythonReconciliationResult`
- `LegacyPythonReconciliationResult` (dataclass — new addition to `cdc/reconciliation/models.py`)
- `EVENT_TYPE = 'LEGACY_VS_PYTHON_RECONCILE'` (composite of CheckType discriminator)
- Status / mode / drift-class enum constants

**Composition** (per `udm-data-engineer-review` discipline):
- Reads python Bronze via `extract.udm_connectorx_extractor.read_bronze_table`
- Reads legacy Bronze via direct ConnectorX URI (mirrors `seed_from_legacy.py._read_legacy()`)
- Computes per-row content hash via `data_load.row_hash.add_row_hash` (excluding UDM-meta columns) — provides the `(PK, content-hash)` version-key for full_history mode per D-LP-9
- Honors `_RECON_MAX_ROWS=50M` size guard; windowed mode for larger tables (§5.9)
- Honors `table_config.exclude_from_hash` (excluded columns are also skipped from value drift comparison; flagged only as `informational` finding-class)
- Honors `table_config.pii_column_list` (PII columns skipped from value comparison per D-LP-8)
- Reads `cdc.lateness_profiler.LatenessReport` for per-table L_99 stability window per D-LP-10

### §5.3 Result model + persistence

**`LegacyPythonReconciliationResult`** (extend `cdc/reconciliation/models.py`):

```python
@dataclass
class LegacyPythonReconciliationResult:
    table_name: str
    source_name: str
    mode: str                            # 'counts_only' | 'active' | 'full_history'
    legacy_row_count: int = 0
    python_row_count: int = 0
    legacy_active_pk_count: int = 0
    python_active_pk_count: int = 0
    pk_in_legacy_not_python: int = 0     # missing in python
    pk_in_python_not_legacy: int = 0     # extra in python
    rows_in_stability_window_skipped: int = 0    # per D-LP-10
    pii_columns_skipped: list[str] = field(default_factory=list)   # per D-LP-8
    exclude_from_hash_columns_skipped: list[str] = field(default_factory=list)  # per Q D-LP-?-? open
    schema_drift_columns_legacy_only: list[str] = field(default_factory=list)
    schema_drift_columns_python_only: list[str] = field(default_factory=list)
    # Active-mode drift
    active_pk_value_mismatches: int = 0
    active_column_mismatch_counts: dict[str, int] = field(default_factory=dict)
    # Full-history-mode drift
    history_versions_legacy: int = 0
    history_versions_python: int = 0
    version_pairs_matched: int = 0
    version_pairs_only_legacy: int = 0
    version_pairs_only_python: int = 0
    # Findings classification per manifest awareness
    seed_divergence_count: int = 0       # rows with UdmSourceBeginDate < manifest.SeedCompletedAt
    pipeline_divergence_count: int = 0   # rows with UdmSourceBeginDate >= manifest.SeedCompletedAt
    # Metadata
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return (
            self.pk_in_legacy_not_python == 0
            and self.pk_in_python_not_legacy == 0
            and self.active_pk_value_mismatches == 0
            and self.version_pairs_only_legacy == 0
            and self.version_pairs_only_python == 0
            and not self.errors
        )
```

**Persistence**: reuse `General.ops.ReconciliationLog` (per §2.1 — schema already supports `CheckType` discriminator + `Metadata` JSON + `Severity` + `Acknowledged`). New `CheckType` values:
- `LEGACY_VS_PYTHON_COUNTS`
- `LEGACY_VS_PYTHON_ACTIVE`
- `LEGACY_VS_PYTHON_FULL_HISTORY`

Severity mapping:
- `is_clean == True` → Severity='INFO' + Status='SUCCESS'
- Any PK-set drift → Severity='WARNING' + Status='FAILED' (operator-acknowledge gate per S14)
- Active value mismatches > 0 → Severity='WARNING' + Status='FAILED'
- Schema drift legacy-only columns present → Severity='ERROR' + Status='FAILED' (python may have lost a column)
- errors list non-empty → Severity='ERROR' + Status='ERROR'

**No new table** for watchdog — reuses existing ReconciliationLog. (Distinct from seed manifest, which IS a new table per D-LP-1.)

### §5.4 Comparison axes (3 modes)

| Mode | Operations | Cost class | When to run |
|---|---|---|---|
| `counts_only` | (a) `COUNT(*)` row parity (b) `COUNT(*) WHERE UdmActiveFlag=1` parity (c) Active-PK set diff via `EXCEPT` | Cheap (~seconds per table) | Nightly across all DNA + EPICOR tables |
| `active` | counts_only + column-by-column value comparison for Flag=1 PKs (excluding PII per D-LP-8 + ExcludeFromHash informational-only) | Medium (~minutes per table) | Weekly rotating subset (e.g., 1/7 of tables per night) |
| `full_history` | active + `(PK, content-hash)` version-pair comparison across ALL Flag values | Heavy (~minutes-hours per table; hash recompute is the cost) | Weekly per-table rotation OR on-demand operator triage |

Default cadence in §1.2 / §5.5: nightly `counts_only` for all + weekly rotating `full_history` per-table.

### §5.5 Manifest-aware findings classification

**Pre-condition**: `--manifest-aware` flag (default ON when `General.ops.LegacySeedManifest` table exists).

**Procedure**:
1. Per-table, look up most-recent `Status='completed'` manifest row; extract `SeedCompletedAt`.
2. For each drift finding (PK or version-pair), inspect the row's `UdmSourceBeginDate` (python side) or `UdmEffectiveDateTime` (fallback if SourceBeginDate NULL).
3. If `row_date < SeedCompletedAt` → categorize as `seed_divergence` (legacy and python disagree on historical state; likely seed-time issue OR ongoing legacy correction).
4. If `row_date >= SeedCompletedAt` → categorize as `pipeline_divergence` (post-cutover divergence; ongoing python pipeline produced different result than legacy continued to produce in parallel).
5. Increment respective counter; metadata JSON carries per-finding category.

**Why this matters**: seed-divergence findings are usually "expected" (legacy enrichment columns the python pipeline backfills on first run; schema-evolution mass updates; etc.) — runbook action is "informational; verify against expected enrichment patterns". Pipeline-divergence findings are "investigate" — they indicate the python pipeline produced different output than legacy for the same source state.

### §5.6 Stability window discipline

Per D-LP-10. Procedure:

1. Load per-table `L_99` from `cdc.lateness_profiler.LatenessReport` (if exists for `(SourceName, TableName)`).
2. Compute `cutoff = NOW() - L_99 hours` (fallback L_99=48h if no report).
3. Skip findings where the relevant row's `MAX(UdmSourceBeginDate, UdmEffectiveDateTime) > cutoff`.
4. Record `rows_in_stability_window_skipped` in result for transparency.

CLI override: `--stability-window-hours 0` disables the suppression (operator opt-in for incident-response deep audit).

### §5.7 PII column handling

Per D-LP-8.

1. Load `table_config.pii_column_list` from `UdmTablesList.PiiColumnList` (CSV; per D6 + Round 4.5b § 4).
2. Skip these columns from value comparison.
3. Record skipped columns in `pii_columns_skipped` for transparency.
4. Increment a separate `pii_columns_assumed_equivalent` counter (informational; not drift).

**Out of scope for v1**: blank-box verification of tokenization correctness (would require operator-justified SP-2 decrypt + audit on every watchdog run; security violation per SECURITY_MODEL.md). Pipeline-lead may revisit in v2.

### §5.8 ExcludeFromHash + schema-evolution drift handling

**ExcludeFromHash columns** (per `UdmTablesList.ExcludeFromHash`):
- Skipped from drift-flagging
- Counted in `exclude_from_hash_columns_skipped` for transparency
- Informational only

**Schema-evolution drift**:
- Columns present in python target but NOT in legacy → `schema_drift_columns_python_only` (expected — python target auto-created from CURRENT source; legacy snapshot pre-dates schema growth). Informational.
- Columns present in legacy but NOT in python target → `schema_drift_columns_legacy_only` → 🔴 INVESTIGATE (either legacy retained a column python dropped, OR python missed a migration). Surface as Severity='ERROR'.

### §5.9 Large-table windowed mode

For tables exceeding `_RECON_MAX_ROWS=50M` (matches existing C-7 size guard discipline):

- `counts_only` mode runs without windowing (cheap aggregate queries)
- `active` mode windows by `SourceAggregateColumnName` if configured (mirrors `reconcile_table_windowed` precedent); if not configured, falls back to `--sample-size N` operator-specified
- `full_history` mode for large tables: REQUIRE `--sample-size` flag OR raise `RECON_TABLE_TOO_LARGE` error (mirrors existing C-7 discipline)

### §5.10 StripSuffix=1 collision precondition

When `table_config.strip_suffix == 1`, python Bronze name is `UDM_Bronze.DNA.ACCT` (uppercase) vs legacy `UDM_Bronze.dna.ACCT` (lowercase). SQL Server schema-name comparison is case-INSENSITIVE by default.

**Precondition check at tool entry**:
1. Resolve python Bronze FQN via table_config
2. Resolve legacy FQN via convention (D-LP-3)
3. If `python_fqn.lower() == legacy_fqn.lower()` → hard-error with explicit message; operator must (a) confirm distinct physical tables OR (b) rename the python target to disambiguate.

**Edge case ref**: SS-1 in CLAUDE.md "Do NOT" list.

---

## §6. Phase C — CCM bespoke solution (DEFERRED)

**Status**: 🔴 Deferred per user direction 2026-05-18 ("CCM will need a very specific solution that we can work on later").

**What this section commits to**: nothing. CCM is explicitly OUT of scope for this plan.

**What's known about CCM** (from existing codebase signals):
- Legacy CCM tables exist at `UDM_Bronze.ccm.<table>` (lowercase schema, per `seed_from_legacy.py` conventions)
- CCM data appears to be source-typed as SQL Server (vs DNA = Oracle, EPICOR = ?)
- No specific CCM design notes encountered during plan-author pre-flight reads
- User indicated CCM requires "a very specific solution" → implies known structural differences vs DNA/EPICOR

**Forward path**: when pipeline-lead is ready to scope Phase C, a separate planning session (new `udm-planning-session-startup` invocation) authors a Phase-C-specific plan deliverable. THIS plan's tools (`seed_from_legacy_batch.py` / `compare_legacy_vs_python_bronze.py`) hard-reject `--source CCM` per D-LP-11 until that point.

---

## §7. Phase D — Investigation runbook (RB-N spec)

Per `udm-runbook-author` (light coverage; full authoring deferred until Phase B has surfaced enough finding-types).

**Proposed runbook**: `docs/migration/05_RUNBOOKS.md` → RB-N "Legacy/Python Bronze drift triage"

**Structure** (per `udm-runbook-author` When → Pre-flight → Procedure → Validation → Rollback):

| Section | Content |
|---|---|
| **When** | Watchdog tool produced finding with Severity ∈ {WARNING, ERROR}; ReconciliationLog row has `Acknowledged=0` |
| **Pre-flight** | Identify CheckType (LEGACY_VS_PYTHON_COUNTS / _ACTIVE / _FULL_HISTORY); identify manifest-aware finding-class (seed_divergence / pipeline_divergence); confirm finding is outside stability window (L_99-aware) |
| **Procedure (decision tree)** | (1) If CheckType=COUNTS + PK count drift only → check for in-flight pipeline run for table; if not, investigate per `tools/diagnose_stage_bronze_gap.py` extension OR direct SQL inspection of legacy vs python row counts. (2) If CheckType=ACTIVE + active-pk-value-mismatches > 0 → inspect column-level mismatches; for each column: (a) is column in `ExcludeFromHash`? acknowledge as informational; (b) is column expected to drift due to legacy enrichment pattern? acknowledge with operator justification; (c) is value transformation rule different between pipelines? open BACKLOG B-N. (3) If CheckType=FULL_HISTORY + version pair drift → investigate close-timing differences (SCD2-P1-b update-close semantics); compare `UdmSourceEndDate` invariants. (4) Per-finding acknowledgment: `UPDATE General.ops.ReconciliationLog SET Acknowledged=1, AcknowledgedBy=?, AcknowledgedAt=NOW(), AcknowledgmentNotes=? WHERE Id=?` |
| **Validation** | Operator confirms acknowledgment row count == expected; subsequent watchdog run on same table emits zero NEW non-acknowledged findings of same class |
| **Rollback** | None — runbook is investigative, not modifying |

**Open Q (deferred to RB-N authoring session)**: should certain finding-classes auto-open BACKLOG B-Ns (e.g., `pipeline_divergence` count > N)? Threshold + automation policy TBD.

---

## §8. Edge case mapping (per `udm-edge-case-validator`)

Walks the 14-series canonical edge-case taxonomy in `04_EDGE_CASES.md`:

| Series | Relevant edge cases | This plan's coverage |
|---|---|---|
| **M** (Math / Lateness) | M2 bimodal late-arrivals; M4 unreliable LASTMOD; M14 (if exists) | Covered by §5.6 stability window discipline (D-LP-10) |
| **S** (SCD2 Reliability) | S8 manual Bronze write; S14 reconciliation finding (acknowledge gate); S10 force-after-extraction-guard | S14 directly addressed (ReconciliationLog `Acknowledged` flag per S14 wiring); S8 NOT addressed (out of scope — manual writes are a separate discipline) |
| **I** (Idempotency) | I5 hash collision; I24 multiple active SchemaContract rows | I5 addressed by full SHA-256 + per-PK comparison precedent; I24 NOT relevant (seed manifest uses filtered unique index on completed status — Status='completed' rows are unique per (SourceName, TableName)) |
| **B** (Engineering / Boundary recon) | B-11 boundary reconciliation; B-1 hash discipline VARCHAR(64) | B-11 informs the comparator design; B-1 confirms hash recompute strategy (SHA-256 hex VARCHAR(64) per D-LP-9) |
| **P** (PII / Encryption) | P5 PII-pattern logging filter; D6 tokenization; D102 AES-256-GCM | D-LP-8 commits to skipping PII columns from value comparison (preserves security model; defers blank-box validation) |
| **G** (Gap Detection) | G8 backfill during outage | Stability window discipline covers tail-end legitimate drift |
| **V** (Verification) | V-4 duplicate active rows; V-11 polars-hash fallback | V-4 NOT specifically addressed (existing `reconcile_bronze` handles duplicate-active-PK check; if duplicates exist on legacy side, drift will surface — operator triages); V-11 inherited from existing `add_row_hash()` discipline |
| **SE** (Source-Exactness) | SE7 source row order; SE-other Phase A invariants | NOT directly relevant — Phase A SE invariants are about source-to-Parquet writes; this plan compares Bronze-to-Bronze (post-CDC, post-SCD2 transformations) |
| **T** (Testing) | T1-T4 testing series | Phase 1 build will author Tier 0 + Tier 1 tests; integration tests (Tier 3) deferred — see §9 |
| **DP / SI / F / D / N / PL** | Not specifically relevant to this plan | N/A |

**New edge case candidates surfaced** (for inclusion at next round close-out via `udm-subclass-accumulator` if pattern recurs):

- **V-? proposed** — "cross-pipeline equivalence verification" (this plan's domain) — currently absent from V-series; if Phase B operational experience produces 3+ findings showing the discipline IS load-bearing, formalize as V-N at Round 9+ close-out.
- **SE-? proposed** — "source-content-equivalence-under-different-pipelines" — semantic neighbor to SE-series; defer pending evidence base.

---

## §9. Discipline + governance artifacts

### §9.1 Trackers to update at Phase 1 build time (NOT this session)

| Tracker | Update | When |
|---|---|---|
| `BACKLOG.md` | Open B-N for each unbuilt component: Phase A tool, Phase A manifest DDL, Phase B comparator + tool, Phase D runbook | Phase 1 build session start |
| `CODE_BUILD_STATUS.md` | Add per-unit rows: `tools/seed_from_legacy_batch.py`, `cdc/reconciliation/legacy_vs_python.py`, `tools/compare_legacy_vs_python_bronze.py`, `migrations/legacy_seed_manifest_init.py` | Phase 1 build session start; status flips per build-state transitions |
| `_validation_log.md` | Append plan-authoring event (this session) + per-build attestation events (Phase 1) | This session (plan event); Phase 1 sessions (build events) |
| `ONE_OFF_SCRIPTS.md` | Add `seed_from_legacy_batch.py` entry per D-LP-2 (one-time per-table) | Phase 1 build session start |
| `phase1/02_configuration.md` §5.1 | Add `compare_legacy_vs_python_bronze.py` to frozen-N Automic inventory per D-LP-5 | Phase 1 build session — emit MIGRATION_AUTOMIC_INVENTORY event when added |
| `03_DECISIONS.md` | Allocate D-N numbers for D-LP-1 through D-LP-11; lock per `udm-decision-recorder` discipline | Pipeline-lead approval of THIS plan |
| `04_EDGE_CASES.md` | Add V-N or SE-N candidate after Phase B produces 3+ events | Round 9+ close-out (deferred) |
| `05_RUNBOOKS.md` | Add RB-N drift-triage runbook | Phase D session (after Phase B has surfaced finding-types) |
| `CLAUDE.md` Structure | Register `tools/seed_from_legacy_batch.py` + `tools/compare_legacy_vs_python_bronze.py` + `cdc/reconciliation/legacy_vs_python.py` + `migrations/legacy_seed_manifest_init.py` per hard rule 9 Step 10 | Phase 1 build sessions |
| `CLAUDE.md` L207 CLI_* registry | Increment count (24 → 26 with both new CLIs); add `CLI_SEED_FROM_LEGACY_BATCH` + `CLI_COMPARE_LEGACY_VS_PYTHON_BRONZE` | Phase 1 build sessions |
| `CLAUDE.md` EventType families | Document `LEGACY_SEED` event type (Phase A) + `LEGACY_VS_PYTHON_RECONCILE` event composite (Phase B); confirm `MIGRATION_LEGACY_SEED_MANIFEST` migration event | Phase 1 build sessions |
| `GLOSSARY.md` public-surface tables | Add Phase A + Phase B module/tool exports | Phase 1 build sessions |
| `RISKS.md` | Open R-N for "long-tail seed completion for high-table-count sources" + "watchdog finding-flood at parallel-run start"; both LOW likelihood / MEDIUM impact per WSJF | Phase 1 build session start |

### §9.2 CCL Stage routing (per INDEX.md)

This plan deliverable lands in `docs/migration/` directly (not phase1/) — matches the pattern of `NEXT_STEPS_PLAN_2026-05-17.md` + `MARKDOWN_REFACTOR_PLAN.md`. INDEX.md "Active plans" section is the right home for an entry; pipeline-lead may add at approval-commit.

### §9.3 Test sketches (Phase 1 build session preview)

Deferred to Phase 1 build session; sketch outline here for completeness:

**Tier 0 (deterministic; <100ms each):**
- `tests/tier0/test_seed_from_legacy_batch.py` — CLI parsing, pre-flight matrix, manifest state-machine transitions, CCM hard-rejection
- `tests/tier0/test_compare_legacy_vs_python_bronze.py` — CLI parsing, mode selection, exit-code mapping
- `tests/tier0/test_legacy_vs_python_module.py` — public surface, result model serialization, version-key hash recompute determinism
- `tests/tier0/test_legacy_seed_manifest_ddl.py` — DDL string parses, CHECK constraint covers all Status enum values

**Tier 1 (regression; <1s each):**
- Synthetic legacy + python DataFrames; test all 3 modes (counts / active / full_history); manifest-aware classification; stability window suppression; PII column skip; ExcludeFromHash skip; schema-drift handling; StripSuffix=1 collision precondition

**Tier 3 (integration; testcontainers; Linux-CI only):**
- `tests/integration/test_legacy_python_seed_and_compare_e2e.py` — testcontainers mssql:2022 image; seed synthetic legacy → run comparator → verify clean → modify python side → verify drift detected

**Tier 4 (crash injection; deferred):**
- Crash-mid-seed test (manifest Status='in_progress' recovery)

### §9.4 Property tests (Tier 2)

Deferred to Phase 1 build session. Candidates:
- Idempotence: running comparator twice on same legacy+python state yields same result
- Hash recompute determinism: legacy row → python algorithm hash is byte-stable across Polars versions per V-11
- Stability window monotonicity: increasing `--stability-window-hours` monotonically increases `rows_in_stability_window_skipped`

---

## §10. Non-conflict statement vs concurrent SESSION_RESUME.md work

**Active session state** (per `SESSION_RESUME.md` at session start):
- Branch: `round-6-post-merge-tracking`
- Hot files: `tools/check_commit_msg.py` + `tests/tier0/test_check_commit_msg.py` + `SESSION_RESUME.md`
- Status: "Awaiting pipeline-lead pivot direction" — 79 commits across 3 days of meta-discipline work (Mechanism C-1 expansion + SKILL semver bumps)
- Pivot options listed include Option C "Phase 2 pilot ACCT testing — End-to-end CDC + SCD2 + reconciliation on DNA.osibank.ACCT" which would touch `cdc/reconciliation/`

**This plan's file footprint** (when Phase 1 build commences):
- NEW: `tools/seed_from_legacy_batch.py`, `tools/compare_legacy_vs_python_bronze.py`, `cdc/reconciliation/legacy_vs_python.py`, `migrations/legacy_seed_manifest_init.py`, `tests/tier0/test_seed_from_legacy_batch.py`, `tests/tier0/test_compare_legacy_vs_python_bronze.py`, `tests/tier0/test_legacy_vs_python_module.py`, `tests/tier0/test_legacy_seed_manifest_ddl.py`, `tests/integration/test_legacy_python_seed_and_compare_e2e.py`, `docs/migration/BRONZE_LEGACY_VS_PYTHON_VALIDATION_PLAN_2026-05-18.md` (this file)
- EXTEND: `cdc/reconciliation/__init__.py` (export new symbols), `cdc/reconciliation/models.py` (add LegacyPythonReconciliationResult), `CLAUDE.md` (Structure + L207 + EventType families), `GLOSSARY.md` (public surface), `BACKLOG.md`, `_validation_log.md`, `CODE_BUILD_STATUS.md`, `ONE_OFF_SCRIPTS.md`, `phase1/02_configuration.md` §5.1, `03_DECISIONS.md`, `INDEX.md` (Active plans entry)
- DO NOT TOUCH (active session's hot files): `tools/check_commit_msg.py`, `tests/tier0/test_check_commit_msg.py`, `SESSION_RESUME.md`

**Coordination commitment**:
- Phase 1 build is deferred until active session's pivot direction is known. If active session pivots to Option C (Phase 2 pilot ACCT testing), `cdc/reconciliation/` extensions are coordinated via:
  - (a) waiting for Option C to land first, OR
  - (b) authoring the new module file (`legacy_vs_python.py`) atomically without modifying existing module files
- This plan-deliverable Write (this session) is the ONLY write to disk in this session. No tracker mutations. No code changes. Minimal conflict surface.

---

## §11. Open questions remaining (for pipeline-lead resolution before Phase 1 build)

| # | Question | Default if no answer | Decision affected |
|---|---|---|---|
| Q1 | Per-table waterfall config snapshot in manifest: full JSON or just column names? | Full JSON (audit-grade preference) | §4.2 schema |
| Q2 | `seed_from_legacy.py` upgrade to D74/D75/D76 in scope for Phase A OR defer? | Defer (wrapper is sufficient; lift inline if friction) | Phase A scope |
| Q3 | Watchdog cadence proposal — nightly counts + weekly rotating full_history. Acceptable? | Yes (D-LP-5 default) | §5.4 |
| Q4 | `--manifest-aware` default ON: any reason to flip default OFF? | No — manifest-aware default ON; opt-out via `--no-manifest-aware` | §5.5 |
| Q5 | Pipeline-divergence finding auto-open BACKLOG B-N threshold? | Manual operator triage only; no auto-open | §7 + Phase D |
| Q6 | Snowflake mirror (per `N9` edge case) — is THIS plan's scope also Bronze-on-Snowflake side, or SQL Server Bronze only? | SQL Server Bronze only; Snowflake mirror reconciliation is a separate effort | Phase B scope |
| Q7 | StripSuffix=1 status across DNA + EPICOR tables: which tables are currently StripSuffix=1? Audit needed before Phase A. | TBD via `SELECT SourceName, TableName, StripSuffix FROM General.dbo.UdmTablesList WHERE SourceName IN ('DNA','EPICOR')` | §5.10 precondition |
| Q8 | If Phase A surfaces a per-table seed that requires legacy-enrichment-column backfill (per `seed_from_legacy.py` MEMBERAGREEMENT note), is THIS plan's tool responsible for the enrichment? | NO — defer to python pipeline's R-2 waterfall on first forward-run (matches existing single-table seed behavior) | §4.4 |

---

## §12. Sequencing + risks

### §12.1 Recommended sequencing

1. **Pipeline-lead approves this plan** (or redirects via this section's open Qs)
2. **Lock D-LP-1 through D-LP-11** in `03_DECISIONS.md` via `udm-decision-recorder` (allocate canonical D-N numbers; lock 🟢 with this plan as evidence)
3. **Phase A1 build session**: `tools/seed_from_legacy_batch.py` + `migrations/legacy_seed_manifest_init.py` + Tier 0 + Tier 1 tests + tracker artifacts (per §9.1)
4. **Phase A2 operator execution**: pipeline-lead schedules Automic / shell-loop run across DNA + EPICOR tables; manifests fill in
5. **Phase A3 validation**: post-seed cheap parity gates passing for all DNA + EPICOR tables (manifest Status='completed' rate)
6. **Phase B1 build session**: `cdc/reconciliation/legacy_vs_python.py` + `tools/compare_legacy_vs_python_bronze.py` + Tier 0 + Tier 1 + Tier 3 tests + tracker artifacts
7. **Phase B2 operator deployment**: Automic schedule (nightly counts + weekly full_history rotating); MIGRATION_AUTOMIC_INVENTORY event
8. **Phase B3 operational** (multi-month): operator reviews ReconciliationLog findings; manual acknowledgment per S14 gate
9. **Phase D**: RB-N runbook authoring after Phase B has surfaced 3+ finding-types
10. **Phase C scoping**: separate planning session when pipeline-lead is ready

### §12.2 Risks (R-N candidates for `RISKS.md`)

- **R-?-a Long-tail seed completion** — DNA + EPICOR have N tables; per-table seed for large tables (3B+ rows) is hours-scale; full backfill window may span days-to-weeks of operator wall time. *Mitigation*: per-table isolation per D-LP-6 + parallelism via `--max-parallel`; manifest visibility for operator pacing.
- **R-?-b Watchdog finding-flood at parallel-run start** — initial Phase B2 deployment will surface ALL accumulated drift findings at once; operator may be overwhelmed. *Mitigation*: stability window discipline (D-LP-10); cheap-mode-first cadence (counts_only nightly); pipeline-divergence vs seed-divergence categorization (D-LP-7 + §5.5).
- **R-?-c Hash-recompute cost for full_history mode** — at 3B-row scale × 200+ tables × weekly cadence × ~30s per million rows, compute budget non-trivial. *Mitigation*: per-table rotation (1/7 of tables per night); operator-tunable `--sample-size`.
- **R-?-d Manifest schema evolution** — if D-LP-1 schema needs revision post-deployment, forward-only additive per D92 + SchemaContract chain. *Mitigation*: existing forward-only discipline.
- **R-?-e CCM scope creep** — operator may pressure to extend tooling to CCM before Phase C is properly scoped. *Mitigation*: D-LP-11 hard-error.

---

## §13. Approval

**Pipeline-lead approval required before Phase 1 build commences.**

Approval form (suggested):
- [ ] 🟢 APPROVE — proceed to Phase A1 build session at pipeline-lead's earliest convenience
- [ ] 🟡 REDIRECT — open Q resolution required (cite §11 question numbers)
- [ ] 🔴 REJECT — fundamental design issue (specify)

Plan deliverable end.
