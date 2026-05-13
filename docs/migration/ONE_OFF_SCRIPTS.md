# ONE_OFF_SCRIPTS.md — Run-Once Scripts + Operator Tools Tracker

**Status**: 🟢 Locked 2026-05-12 per user-direction "I'll need to be aware of any one off scripts. If a tool need to be run once, I'll need to know."

**Purpose**: tracker for scripts/tools that run ONCE (per-server, per-migration, per-spike, per-cleanup, per-CSV-import), not on a schedule. Separate from scheduled tools registry per phase1/02_configuration.md § 5.1 frozen-11 Automic inventory.

**Last reviewed**: 2026-05-12 (initial authoring at build-mode pivot)

---

## Status legend

- **🟡 Pending** — not yet run; script may be in 🟡 build-pending OR 🟢 build-complete state
- **🟢 Build complete; pending deployment** — script authored + tested + reviewed but not yet executed on target server
- **✅ Run** — executed at least once on a target server; audit row in `PipelineEventLog` OR `ManualCorrectionLog`
- **⚫ Archived** — script no longer applicable (superseded; deprecated; one-time spike concluded)

---

## What goes here (vs scheduled tools registry)

| This tracker (ONE_OFF_SCRIPTS) | NOT here (scheduled tools) |
|---|---|
| Migration scripts (DB schema changes; run once per server) | `JOB_PIPELINE_AM` (D109 weekday 02:00) |
| One-time runbooks (RB-14 `.env` migration per server) | `JOB_PIPELINE_PM` (D109 daily 17:00) |
| Spike code (R02 `_spike_round_0_5/`; archive after) | `JOB_LATENESS_MEASURE` weekly (B188 Tool 14) |
| One-time operator tools (B189 Tool 15 PII inventory import per CSV) | `JOB_CAPACITY_BASELINE` monthly (B190 Tool 16) |
| One-time setup scripts (initial credentials provisioning per server) | `JOB_PARQUET_VERIFY` daily |
| RB-1 cutover (per-table; runs once per table during Phase 4 cohort cutover) | `JOB_LOG_CLEANUP`, `JOB_PARITY_EXCEPTION_NOTIFY` etc. |

Scheduled / recurring tools live in `phase1/02_configuration.md` § 5.1 + Round 7 § 6.2 frozen-11 inventory.

---

## Active items (🟡 Pending / 🟢 Build complete)

### Migration scripts (run once per server; idempotent `IF NOT EXISTS` guards per D92)

| ID | Script | Purpose | Status | Owner | Trigger |
|---|---|---|---|---|---|
| **B193** | `migrations/lateness_columns.py` (284 lines) + `tests/tier0/test_lateness_columns.py` (198 lines, 6 tests) + `tests/tier1/test_lateness_columns.py` (361 lines, 10 tests after B202 inline addition) | ALTER `General.dbo.UdmTablesList` ADD COLUMN `LatenessL99Minutes INT NULL` + `LatenessL99UpdatedAt DATETIME2(3) NULL` per D63 | 🟢 **Build complete 2026-05-12** via Pattern B1 (3-agent: author + test-author + design-reviewer); 1 🔴 found (dry-run `idempotency_path` shape mismatch) + fixed inline; 4 🟡 advisories (2 fixed inline; 2 deferred to B202/B203 already tracked). Pending deployment to dev/test/prod servers. | R1 engineer | R1b (Schema + parity micro-round); run once per server dev → test → prod |
| **B194** | `migrations/pii_inventory_audit_log.py` (485 lines) + `tests/tier0/test_pii_inventory_audit_log.py` (393 lines, 6 tests) + `tests/tier1/test_pii_inventory_audit_log.py` (899 lines, 14 tests post-B204+B205 fixes) | CREATE TABLE `General.ops.PiiInventoryAuditLog` (append-only per D26; 11 columns incl. AuditId IDENTITY PK + CHECK on DataClassification 5-value enum {PII, PHI, PCI, PUBLIC, INTERNAL}) | 🟢 **Build complete 2026-05-12** via Pattern B2 cohort + cycle-1 reviewer found 2 🔴 inline-fixed (B204 FIRST_APPLY_DDL_COUNT 1→2; B205 CHECK assertion scope fix) + 2 🟡 deferred (B206 partial-state test; B207 docstring dimension coverage). Pending deployment. | R1 engineer | R1b; run once per server |
| **B195** | `migrations/capacity_baseline_log.py` (361 lines) + `tests/tier0/test_capacity_baseline_log.py` (326 lines, 6 tests) + `tests/tier1/test_capacity_baseline_log.py` (791 lines, 12 tests post-B204 fix) | CREATE TABLE `General.ops.CapacityBaselineLog` (append-only per D26; 13 CapacityResult fields + 4 surrounding append-only cols + IX_CapacityBaselineLog_Table NONCLUSTERED) | 🟢 **Build complete 2026-05-12** via Pattern B2 cohort + cycle-1 reviewer found 1 🔴 inline-fixed (B204 FIRST_APPLY_DDL_COUNT 1→2) + 3 🟡 deferred (B209 failure-audit Tier 1 test; B210 PipelineBatchSequence pre-flight; ONE_OFF_SCRIPTS entry — this one). Pending deployment. | R1 engineer | R1b; run once per server |

### One-time runbook procedures (run once per server)

| ID | Runbook | Purpose | Status | Owner | Trigger |
|---|---|---|---|---|---|
| **RB-14** | `.env` migration `/debi/.env` → `/etc/pipeline/.env` | One-time migration per server; mode 0400 / owned `pipeline:pipeline` / SELinux context restore | 🟡 Pending — **🔴 BLOCKED on B197 SELinux `semanage fcontext` step addition** | Sysadmin | R1a § 4.1; once per server |
| **B197** | RB-14 `semanage fcontext` step addition | One-time per server (additive to RB-14 procedure; registers file-context policy rule for `/etc/pipeline/`) | 🟡 Build pending (sysadmin coordination required for canonical SELinux type) | Sysadmin | Pre-R1a; required before RB-14 can complete cleanly |

### One-time operator tools (NOT scheduled; CLI manual invocation)

| ID | Tool | Purpose | Status | Owner | Trigger |
|---|---|---|---|---|---|
| **B189** | `tools/import_pii_inventory.py` (709 lines) + `data_load/pii_inventory_importer.py` (827 lines) + `tests/tier0/test_import_pii_inventory.py` (537 lines, 7 tests) + `tests/tier1/test_import_pii_inventory.py` (1081 lines, 23 tests) — Tool 15 | One-time CSV import of PII inventory per source per compliance review; operator-driven | 🟢 **Build complete 2026-05-12** via Pattern B3 cohort (Wave 1 first attempt: author API-error crash; Wave 1 retry agent succeeded). **30/30 tests PASS** in 0.55s. B189 author resolved B184 monkey-patch issue with cleaner `gc.get_objects()`-based public-API pattern (still potentially fragile; B211 + B216 candidate). Pending engineer deployment. | R1c engineer | R1c; once per source per inventory CSV change (1-3 times per source over project lifetime) |
| - | `tools/verify_credentials_load.py` (641 lines) + `data_load/credentials_verifier.py` (525 lines) + `tests/tier0/test_verify_credentials_load.py` (452 lines, 7 tests) + `tests/tier1/test_verify_credentials_load.py` (999 lines, 17 tests) — Tool 12 / **B184** | Per-server credential validation; per-server one-time during R1a deployment + on-demand re-validation | 🟢 **Build complete 2026-05-12** via Pattern B2 cohort + B2-re-implementation cycle (initial author/test-author signature divergence caught by post-build-verify; re-implementation aligned to canonical phase1/04a § 3 signature; **24/24 tests PASS**). Pending engineer-side deployment. | R1a engineer | R1a § 4.2 |
| - | `tools/capture_parity_baseline.py` (394 lines) + `data_load/parity_baseline_capture.py` (577 lines) + `tests/tier0/test_capture_parity_baseline.py` (454 lines, 8 tests) + `tests/tier1/test_capture_parity_baseline.py` (1032 lines, 23 tests) — Tool 13 / **B183** | Per-server parity baseline JSON capture; one-time during R1b deployment + on-demand re-capture if drift detected | 🟢 **Build complete 2026-05-12** via Pattern B2 cohort; **28/28 PASS + 3 skipped** (Tier-2-deferred property-based tests). Pending engineer-side deployment. | R1b engineer | R1b § 4.3 |

### Ad-hoc operator tools (Manual × Recurring; operator-driven; no fixed schedule)

Tools that operators invoke as needed when conditions warrant (drift detection, reconciliation, investigation). Distinct from one-time scripts (run once total) AND from scheduled tools (recurring Automic jobs). Classification routing per `.claude/skills/udm-execution-classifier/SKILL.md`.

| Tool | Purpose | Cadence trigger | Typical frequency |
|---|---|---|---|
| `cdc/reconciliation/reconcile_table.py` | Full column-by-column reconciliation per P3-4 | Operator-detected hash collision OR weekly reconciliation gap | Weekly to monthly per table |
| `cdc/reconciliation/scd2_repair.py` (via `tools/repair_scd2.py`) | SCD2 chain repair per SCD2-R6 (3 deterministically-safe auto-repairs) | Operator-detected SCD2 anomaly via `tools/validate_scd2.py` | As needed; rare |
| `tools/inspect_cdc_pk.py` | CDC PK investigation per DIAG-1 | Operator investigating "missing current row" complaint | Per investigation; rare |
| `tools/validate_cdc.py` | Table-wide CDC validation | Operator pre-validation OR post-incident | Per investigation |
| `tools/validate_scd2.py` | Bronze SCD2 structural integrity validation | Operator pre-validation OR post-incident | Per investigation |
| `tools/backfill.py` | R-13 large-table backfill (re-process date range) | Operator-detected gap; pipeline drift recovery | As needed; rare |
| `tools/sweep_modified.py` | LT-2 modified-date sweep (Tier 2 reconciliation) | Operator-detected drift OR scheduled wrapper | Per investigation OR scheduled |

### Spike code (run once; archive after)

| ID | Spike | Purpose | Status | Owner |
|---|---|---|---|---|
| **R02** | `_spike_round_0_5/` (~500 lines throwaway Python) | Validates D6 vault concurrency + D16 Parquet stage-check-exchange + D29 Automic gate-table coordination against running code; ~1 engineer-week scope | 🟡 Pending execution (deferred per user 2026-05-12; engineer staffing accepted) | R02 engineer |

### One-time SchemaContract / data fixes (TBD per R1 execution discoveries)

| ID | Fix | Purpose | Status | Owner | Trigger |
|---|---|---|---|---|---|
| **B200** | SchemaContract abandonment guard refinement | Engineer-side refinement of `phase2/01_pilot_prerequisites.md` § 7 § 4.4 step-1 guard predicate against empirical SchemaContract DDL | 🟡 Build pending | R1 § 4.4 engineer | R1b implementation time; one-time spec refinement (not a script per se but tracked here for visibility) |

---

## Completed items (preserved for audit-trail)

### Migration scripts already run (from prior project work per CLAUDE.md migrations/)

These run-once scripts have ALREADY been executed on production servers. Listed here for completeness so the operator/engineer knows what's been done.

| Script | Purpose | Status | Tracking source |
|---|---|---|---|
| `migrations/b1_hash_varchar64.py` | `_row_hash` + `UdmHash` BIGINT → VARCHAR(64) per B-1 | ✅ Run | CLAUDE.md "Known Issues & Backlog" |
| `migrations/strip_suffix_column.py` | `UdmTablesList` ADD COLUMN `StripSuffix` per SS-1 | ✅ Run | CLAUDE.md "Table Naming Conventions" SS-1 |
| `migrations/audit_log_cardtxn_config.py` | Per-table opt-in for AuditLog + CARDTXN StripSuffix | ✅ Run | CLAUDE.md SS-1 |
| `migrations/scd2_phase1_config.py` | Phase 1 SCD2 config columns + Bronze source-date pair per SCD2-P1-d | ✅ Run | CLAUDE.md SCD2-P1-d |
| `migrations/scd2_expected_retention_days.py` | `UdmTablesList` ADD COLUMN `ExpectedRetentionDays` per SCD2-R2-b | ✅ Run | CLAUDE.md SCD2-P1-d |
| `migrations/scd2_repair_log.py` | CREATE TABLE `General.ops.SCD2RepairLog` per SCD2-R6 | ✅ Run | CLAUDE.md SCD2-R6 |
| `migrations/extraction_guard_per_table.py` | `UdmTablesList` ADD COLUMN `MaxRowsPerDay` per P1-13 | ✅ Run | CLAUDE.md "MaxRowsPerDay" |
| `migrations/udm_tables_columns_list_metadata.py` | `UdmTablesColumnsList` metadata columns (`ObjectType`, `DatabaseName`, `MetadataLastUpdated`) | ✅ Run | CLAUDE.md "Column Sync" |

---

## Archived items

*(none yet)*

---

## How items move

```
🟡 Build pending  →  🟢 Build complete  →  ✅ Run  →  ⚫ Archived (if superseded)
   ↑                       ↑                   ↑              ↑
   Backlog adds B-N       Pattern B1          Server exec    Future supersession
                          team complete       writes audit   per D92 forward-only
                                              row to log
```

State change is annotated inline with date + mechanism, same render discipline as BACKLOG.md per Pitfall #9.j.

---

## Relation to other trackers

| Tracker | Purpose |
|---|---|
| **BACKLOG.md** | Substantive build work tracking (e.g. B193 = "author this script") |
| **ONE_OFF_SCRIPTS.md** (this file) | Operational one-off-ness tracking (e.g. B193 = "run this script once per server when ready") |
| **POLISH_QUEUE.md** | Cosmetic / readability items (P-numbers; non-blocking) |
| **`_validation_log.md`** | Audit trail of validation passes + fix-applications |
| **phase1/02_configuration.md § 5.1** | Scheduled / recurring Automic jobs (frozen-11 inventory); NOT one-off |

---

## Read order context

ONE_OFF_SCRIPTS.md is **NOT** part of D62 CCL Stage 1 mandatory reads — it's an operational worklist for engineers + sysadmins. Optional skim during R1 close-out + R1 execution to confirm which scripts have run + which remain.

---

Owner: Pipeline lead (delegated to R1 implementation engineer for build-state tracking; sysadmin for runbook one-time procedures).
