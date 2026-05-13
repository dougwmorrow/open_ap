# Phase 2 Round 1 — Pilot Prerequisites

**Status**: 🟢 Locked 2026-05-12 per **D88 convergence-confirmed acceptance precedent** (paralleling Round 6 D88 acceptance at cycle 7 with 1 remaining 🔴 carryover via B141). **23 🔴 cumulative caught + fixed across cycles 1-5** (11 + 6 + 3 + 2 + 1) plus 1 🔴 carryover (B200 — SchemaContract abandonment guard refinement; defer to R1 § 4.4 implementation engineer with empirical SchemaContract DDL access). Convergence trajectory 11→6→3→2→1→1 (cycle 5 column-walk CLEAN; cycle 6 idempotency found 1 fresh-instance 🔴 carried as B200). **Cross-reference clean since cycle 2** + **column-walk clean since cycle 5**; **idempotency saturated at 1 🔴 across cycles 5-6 indicating diminishing-returns on producer-side fixes against canonical SchemaContract details** — empirical signal validates Path B convergence-confirmed acceptance per D88 precedent rather than continuing cycle 7+. **Empirical meta-pattern (user-surfaced 2026-05-12)**: 5 of 6 fix-cycles introduced SchemaContract-canonical-detail bugs — tracked as **B201** (Pitfall #9.l candidate: canonical-schema-detail drift sub-class formalization). **🔴 R1 § 4.1 acceptance blocked on B197** (RB-14 SELinux `semanage fcontext` gap) — independent of doc lock status. **Pipeline-lead sign-off pending** for R1 execution authorization; spec doc itself 🟢 locked per validation discipline.

**Owner**: Pipeline lead + on-call engineer.

**Last reviewed**: 2026-05-12 (initial authoring per Phase 2 sequence; sibling to `phase2/00_phase_overview.md` per L3 deliverable map).

**Tier classification** (per D97 cycle-cadence-optimizer tier mapping): **Tier β** (10-50 KB; operational spec doc with procedural step-by-step; lighter than Phase 1 architectural round docs because R1 is execution-of-existing-runbooks not novel-design).

---

## Read order (D62 Canonical Context Load)

Before invoking any R1 step:

**Stage 1 — Orientation** (mandatory, 4 reads):
- `docs/migration/NORTH_STAR.md` (5 pillars + conflict-resolution rubric)
- `docs/migration/HANDOFF.md` (project context; §3 lock list confirms D113 + Phase 2 plan + Round 0.5 spike status)
- `docs/migration/CURRENT_STATE.md` (in-flight status)
- `docs/migration/CHECKS_AND_BALANCES.md` (5-gate validation discipline this round runs under)

**Stage 2 — Risk + Backlog awareness** (mandatory):
- `docs/migration/RISKS.md` (R02 Round 0.5 spike + R32 Claude credential-access)
- `docs/migration/BACKLOG.md` (B183-B196 R1-touched items)
- `docs/migration/_validation_log.md` (recent entries: 2026-05-12 D113 lock + Phase F cascade + Phase G convergence)

**Stage 2.5 — Polish queue skim** (per D113):
- `docs/migration/POLISH_QUEUE.md` (P-1 / P-2 / P-3 / P-4 / P-6 / P-7 — closure targets at R1 close-out OR R1 kickoff)

**Stage 3 — Task-specific reads for this round**:
- `docs/migration/phase2/00_phase_overview.md` (Phase 2 overview; R1 scope at L162-180)
- `docs/migration/phase1/04a_phase_0_prep_tools.md` (Tools 12 + 13 canonical specs)
- `docs/migration/phase1/04b_phase_0_closure_tools.md` (Tools 14 + 15 + 16 canonical specs)
- `docs/migration/phase1/06_deployment.md` (D86 cadence + D87 12-pre / 10-post checklist + module startup per D85)
- `docs/migration/05_RUNBOOKS.md` (RB-12 Phase 1 deploy + RB-14 `.env` migration)
- `docs/migration/phase1/01_database_schema.md` (Round 1 v3 schema for migration script idempotency contracts)

**Stage 4 — Reference-on-demand**:
- `03_DECISIONS.md` (D104 pilot table; D86/D87 cadence + checklist; D103 security; D85 startup; D92 forward-only schema; D113 POLISH_QUEUE)
- `04_EDGE_CASES.md` (M/S/I/N/P/G/D/F/V series — applicability check per § 8 below)
- `phase1/07_schema_evolution_governance.md` (SchemaContract per D92 — applies to B193/B194/B195 migrations)

**Verification rule** (per D62): the executor's first content-substantive tool call (Read or Grep) MUST hit a Stage 1 doc.

---

## § 1. Purpose

Get the pilot environment (dev / test / prod) prerequisite-ready so Round 2 (Dry-Run on Test) can begin with confidence.

**Specifically, Round 1 produces**:
- Phase 1 artifacts deployed to dev / test / prod per D86 cadence (3-environment ladder)
- All 5 Phase 0 closure tools (Tools 12-16) implemented + smoke-tested per Round 4.5 + Round 4.5b specs
- 3 migration scripts (B193/B194/B195) authored + applied on dev → test → prod per D92 forward-only additive
- RB-14 `.env` migration executed on all 3 servers (D103 `/debi/.env` → `/etc/pipeline/.env` migration)
- Parity baseline captured per Tool 13 + verified per `verify_server_parity.py`
- Dev environment smoke-tested end-to-end (synthetic data; no real ACCT yet)
- R02 Round 0.5 spike executed + closed (D6 / D16 / D29 empirically validated against running code)
- All R1 acceptance gates passed → Round 2 unblocked

**Out of scope** for R1:
- Real ACCT data extraction (R2 starts that)
- Production data writes (R3 starts that)
- 14-day production soak (R3 + R4 cover that)
- Bronze parity comparison vs legacy (R2 + R3 cover that)
- Drill exercises RB-3 / RB-9 (R4 covers those)

---

## § 2. Foundational decisions

R1 execution rests on the following 🟢 Locked decisions. Producer must verify each is still 🟢 before invoking any R1 step.

| D-number | Topic | R1 relevance |
|---|---|---|
| **D6** | Vault concurrency via SP-1 | R02 spike validates against running code; R1 acceptance needs R02 closed |
| **D11** | LookbackDays mechanism | R1 smoke-test exercises (synthetic data; verifies the parameter wiring) |
| **D14** | IsReExtraction flag | Same — wired through but not exercised on real data until R2 |
| **D16** | Parquet stage-check-exchange via atomic rename | R02 spike validates against running code |
| **D26** | PiiTokenProvenance schema + retention | B194 migration creates PiiInventoryAuditLog; D26 governs |
| **D27** | Cross-server parity baseline | Tool 13 capture + Tool 14-equivalent (verify_server_parity per R4 § 3.7) executes |
| **D29** | Automic-driven failover via PipelineExecutionGate | R02 spike validates SP-3/SP-4/SP-5/SP-6 chain |
| **D33** | Cooperative cancellation | R02 spike covers (CYCLE_CANCELLED event family per RB-9) |
| **D44** | DR drill expansion (RB-7 Q2/Q4 alternating-scenarios) | R1 does NOT exercise full DR drill — primary RB-7 invocation happens at R4 close-out per phase2/00 L37 |
| **D107** | Two Windows network drive paths (H drive + VendorFile; both LOCAL in-DC) | R1 confirms both drives mounted + writable on all 3 servers; pairs with D110 DC-loss-no-DR posture |
| **D55** | 5-gate validation | This very doc submits to D55 at § 9 |
| **D62** | Canonical Context Load | Mandatory at every step invocation |
| **D67** | Tier 0 smoke tests | All 17 Phase 1 modules must Tier-0-smoke green per R1 § 5 |
| **D72** | Validation cycle termination | If R1 validation hits 🔴 fix-fresh-instance, D72 governs cycle count |
| **D74-D77** | Tool authoring conventions (exit codes / args / audit row / Tier 0 scaffold) | All 5 Tools 12-16 implementations apply |
| **D78** | Round 4 acceptance precedent | Cited if R1 acceptance needs architectural-review escalation |
| **D85** | Module startup sequence (5 stages) | Smoke-test verifies all 5 STARTUP_* events in PipelineEventLog |
| **D86** | 3-environment deploy cadence (dev nightly → test daily +4h soak → prod weekly Monday) | R1 schedule structure |
| **D87** | Pre-deploy 12-check + post-deploy 10-check checklist | § 3 + § 5 below |
| **D88** | Convergence-confirmed acceptance precedent | Cited if R1 validation hits math-infeasibility |
| **D89-D91** | Pattern F cascade audit | Mandatory at R1 close-out per `udm-round-closeout` skill |
| **D92** | Forward-only schema evolution | B193/B194/B195 migration shape (additive ALTER + new tables; never in-place edit) |
| **D95-D99** | Self-improvement skill suite | Section 10 of `udm-round-closeout` invokes at R1 close-out |
| **D102** | AES-256-GCM PiiVault | Not exercised on real PII until R2; B194 PiiInventoryAuditLog schema preserves D102 contract |
| **D103** | Claude Code security model + 13-layer defense | `/etc/pipeline/.env` location enforced; RB-14 migration |
| **D104** | Pilot table = `DNA.osibank.ACCT` | R1 prep is FOR this table; verification queries scope to this table |
| **D105** | SQL naming standards (Proc / Vw) | Any new SP / view surfacing during R1 follows D105 from first commit |
| **D108** | Ops-channel email-centric (Database Mail + Automic + Power BI + Teams) | R1 STARTUP_* events alert via this channel; no PagerDuty / Slack / SMS |
| **D109** | Operational schedule dual-Automic 4-hour gap | R1 deploy cadence MUST respect prod-then-test pattern |
| **D110** | DC-loss-no-DR posture | R1 understands DR scope (re-extraction + company backup; no off-DC mirror) |
| **D112** | Just-in-time plan timing | R1 close-out triggers Phase 3 plan authoring per D112 IF acceptance signs off |
| **D113** | POLISH_QUEUE.md cosmetic tracker | R1 close-out skims POLISH_QUEUE per `udm-round-closeout` CCL Stage 2.5 |

**Forward-cite resolution** (Trigger D per Pattern F): all D-numbers above resolve in `03_DECISIONS.md`. If any cite drifts, P-N candidate per Gate 1 cross-reference guidance in `udm-checks-and-balances/SKILL.md`.

---

## § 3. Pre-flight (12 pre-checks per D87)

Execute the 12 pre-checks from `phase1/06_deployment.md` § 1.6 (Pre/post-deployment checklist contract per D87) BEFORE any R1 step:

**Note on ordering**: pre-flight covers what must be true BEFORE R1 sub-steps run. Some checks (like Tool 12 / Tool 13 PASS) cannot apply at R1 entry because those tools are AUTHORED in § 4.2 / § 4.3 — they appear in § 5 post-step verification instead. The 12 pre-checks below are limited to conditions verifiable BEFORE any § 4 sub-step executes.

1. **CCL Stage 1 + 2 complete**: 7 doc reads logged in operator's working notes; Stage 1 first-read verified (D62 verification rule).
2. **Tier 0 smoke tests green**: all 17 Phase 1 modules pass per D67 (`pytest tests/tier0/ -x`).
3. **Tier 1 unit tests green**: per `phase1/05_tests.md` (`pytest tests/tier1/ -x`).
4. **Branch state clean**: `git status` clean on `main`; no uncommitted changes; current commit SHA logged in operator notes.
5. **Build artifacts ready**: `pip wheel` produces installable wheels for all Python modules; no import errors.
6. **Environment file present**: `/etc/pipeline/.env` exists on target server, mode 0400, owned `pipeline:pipeline` per D103 + RB-14 (verified per § 4.1 execution; pre-check on subsequent servers).
7. **Module startup smoke**: invoking `main_small_tables.py --list-tables` on the target server completes in < 30s + writes 5 STARTUP_* events (CREDS_LOAD / VAULT_CONFIG / PARITY_CHECK / LEDGER_SWEEP / ORCHESTRATION_START) per D85.
8. **Migration scripts dry-run clean**: B193 + B194 + B195 each run with `--dry-run` flag; no errors; idempotent `IF NOT EXISTS` guards verified.
9. **Gate-table state clean**: `SELECT * FROM General.ops.PipelineExecutionGate WHERE CycleDate >= TODAY` returns no stale rows; if non-empty, RB-2 cleanup runs first.
10. **Operator credentials provisioned**: executing operator has `pipeline` group membership; sudo access for `restorecon` + SELinux operations confirmed.
11. **Server time + NTP healthy**: `timedatectl status` shows synchronized; no clock drift > 1 min vs reference per D109 + D86 schedule precision requirements.
12. **PiPipeline service stopped** (test/prod only — dev runs ad-hoc): `systemctl status pipeline.service` shows inactive before deploy work begins.

**Tool 12 + Tool 13 PASS verification moved to § 5 post-step verification** (Gap 3 corrective per producer self-check 2026-05-12 — Tool 12 is AUTHORED in § 4.2 + Tool 13 is AUTHORED in § 4.3; PASS verification belongs as post-step checks of those sub-steps, NOT as overall pre-flight).

If ANY pre-check fails → halt R1; investigate; document in operator notes; do not proceed until all 12 PASS.

---

## § 4. Step-by-step procedure

R1 executes 8 sub-steps, each on dev → test → prod ladder per D86 cadence. Each sub-step has its own audit row in `PipelineEventLog` (per D76 audit-row contract).

### § 4.1. RB-14 `.env` migration (`/debi/.env` → `/etc/pipeline/.env`)

**Per-server**: dev → test → prod, with check-pause-check between servers.

Procedure delegated to **`05_RUNBOOKS.md` § RB-14** (🟢 ⚫ CLOSED 2026-05-11 per B182). RB-14 covers:
- Pre-flight: verify `/debi/.env` exists + readable
- Migration: `cp /debi/.env /etc/pipeline/.env` + `chmod 0400 /etc/pipeline/.env` + `chown pipeline:pipeline /etc/pipeline/.env` + `restorecon -v /etc/pipeline/.env` (SELinux restore per D103)
- Validation: `tools/verify_credentials_load.py` PASS using `/etc/pipeline/.env` as default
- Audit row: `ManualCorrectionLog` entry with operator + timestamp + server name
- Rollback: revert to `/debi/.env` if validation fails

**Acceptance**: RB-14 audit row in `ManualCorrectionLog` for each of dev / test / prod; `verify_credentials_load.py` PASS on each.

**🔴 BLOCKER — B197 SELinux gap** (per Pattern E R1C1-5 advisory researcher + R1C3 🔴 Q3 cross-ref): RB-14 as currently authored is INSUFFICIENT for § 4.1 acceptance because `restorecon -v /etc/pipeline/.env` alone does not register a file-context policy rule for the custom non-standard path `/etc/pipeline/`. Per RHEL canonical guidance, `semanage fcontext -a -t <type> "/etc/pipeline(/.*)?"` MUST run FIRST to register the policy rule, then `restorecon -Rv /etc/pipeline/` resolves to the correct service-confining type. Without that first step, the file gets generic `etc_t` label rather than the intended service-specific confinement — silently breaking D103 Layer 11 (SELinux enforcing) assurance. **§ 4.1 acceptance is BLOCKED on B197 closure** — operator running RB-14 unchanged will produce idempotent file-copy success while leaving SELinux confinement broken; re-runs will loop indefinitely without converging on a working state. Track via BACKLOG.md B197 (WSJF 4.0); sysadmin coordination required to confirm canonical SELinux type before B197 closure unblocks § 4.1.

**Event row** (per D76): `EventType = 'CLI_VERIFY_CREDENTIALS_LOAD'`; Metadata JSON includes `{server, env_path, post_migration: true}`.

### § 4.2. Tool 12 implementation + verification

**B184 (Tool 12 `verify_credentials_load.py`)** implementation:
- Canonical spec at `phase1/04a_phase_0_prep_tools.md` § 3
- Implements Tier 0 scaffold per D67 + D77 (6 canonical assertions: TPM2 unsealable, GPG decryptable, key permissions 0400, kernel keyring populated, in-memory only, redacted in logs)
- CLI exit-code contract per D74 (0 = clean, 1 = drift, 2 = fatal)
- Args per D75 (`--server`, `--actor`, `--justification`, `--dry-run`)
- Audit row per D76 (`EventType = 'CLI_VERIFY_CREDENTIALS_LOAD'`)
- SensitiveDataFilter applied per RB-14 + D103 (no plaintext secrets in logs)

**Execution**:
- Author `tools/verify_credentials_load.py` against spec
- Author `tests/tier0/test_verify_credentials_load.py` per Tier 0 scaffold pattern
- Run `pytest tests/tier0/test_verify_credentials_load.py` → must PASS in < 5s
- Run `tools/verify_credentials_load.py --server dev --actor <operator> --justification "R1 pre-flight"` → expect PASS
- Repeat for `--server test` and `--server prod`

**Acceptance**: B184 implementation lands in `tools/verify_credentials_load.py` (no longer just a spec); Tier 0 + 3 server invocations PASS; PipelineEventLog has 3 `CLI_VERIFY_CREDENTIALS_LOAD` rows with `Status = 'SUCCESS'`.

### § 4.3. Tool 13 implementation + parity baseline capture + verification

**B183 (Tool 13 `capture_parity_baseline.py`)** implementation:
- Canonical spec at `phase1/04a_phase_0_prep_tools.md` § 4
- Captures baseline JSON per Round 2 § 4.1 canonical schema (RHEL version, Python pinned, library set, systemd unit hash, TZ env var per Round 4.5b polish item)
- **Scope (per Pattern E R1C1-4 finding 🔴 10 fix + R1C3 🔴 Q1/Q2 correction)**: baseline captures **OS / library / env / systemd** state only — **NOT** `INFORMATION_SCHEMA` (full database schema state). Database schema state is governed authoritatively by `General.ops.SchemaContract` per D92 + Round 7 § 1.1; capturing full INFORMATION_SCHEMA in the parity baseline would conflict with SchemaContract's append-only supersession protocol AND would falsely report drift between servers whenever B193/B194/B195 partial-ladder application leaves servers temporarily diverged (which is operationally expected during § 4.4 sequential application). The § 6 Gate 2 `verify_server_parity.py` check is for OS/library/env parity ONLY; **cross-server schema parity for the B193/B194/B195 changes specifically is verified via a targeted `INFORMATION_SCHEMA.COLUMNS` query per server then operator-compared** (NOT via SchemaContract — SchemaContract has no `ServerName` column per Round 1 § 23 schema; canonical row keying is `(SourceName, ObjectName, ColumnName, ContractKey)` shared across servers): `SELECT 'B193' AS Migration, TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'UdmTablesList' AND COLUMN_NAME IN ('LatenessL99Minutes', 'LatenessL99UpdatedAt') UNION ALL SELECT 'B194', TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'ops' AND TABLE_NAME = 'PiiInventoryAuditLog' UNION ALL SELECT 'B195', TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'ops' AND TABLE_NAME = 'CapacityBaselineLog' ORDER BY Migration, COLUMN_NAME` — operator captures result on each of dev/test/prod; row-set comparison shows divergence if any server is missing rows. **DB-connectivity pre-check (per R1C4 🟡 advisory + R1C5 column-walk miscite correction)**: before running this query on a target server, the operator MUST verify DB connectivity per § 3 pre-check #7 (module startup smoke — `main_small_tables.py --list-tables` exercises the DB connection path). If any server fails to connect (e.g. SELinux-blocked `.env` read pre-B197 closure — see § 4.1 🔴 BLOCKER), the operator cannot distinguish "schema didn't apply" from "couldn't connect to verify schema applied"; partial-server-application becomes unverifiable until DB connectivity is restored. Halt R1 until all 3 servers can execute this query successfully. Cycle-3 root cause: cycle-2 fix invented a non-executable `SchemaContract` query referencing non-existent `ServerName` + `Active` columns; corrected to targeted INFORMATION_SCHEMA query above.
- Idempotent: same input → same output bytes
- Wraps NEW module `data_load/parity_baseline_capture.capture_baseline()` per D92 forward-only additive

**Tool 14-equivalent** (`tools/verify_server_parity.py`) per **R4 § 3.7** spec already locked:
- Compares current server state against captured baseline
- Exit 0 if zero drift; exit 1 if warning drift (≤ 3); exit 2 if fatal drift
- Audit row `EventType = 'CLI_VERIFY_SERVER_PARITY'`

**Execution**:
- Author `tools/capture_parity_baseline.py` + `data_load/parity_baseline_capture.py` against spec
- Author Tier 0 tests per scaffold pattern
- Author `tools/verify_server_parity.py` per R4 § 3.7 (if not already authored as part of R4 implementations)
- On dev: capture baseline → save as `parity_baseline_dev_<timestamp>.json` to canonical config location
- Repeat for test + prod
- Run `verify_server_parity.py --server <env> --baseline <path>` on each → expect PASS

**Acceptance**: B183 implementation lands; 3 baseline JSONs captured; 3 parity verifications PASS; PipelineEventLog has 3 `CLI_VERIFY_SERVER_PARITY` rows with `Status = 'SUCCESS'`.

### § 4.4. Migration scripts B193 / B194 / B195 (additive ALTER + new tables)

Apply in this order per dependency:
1. **B193**: `migrations/lateness_columns.py` — ALTER `UdmTablesList` ADD COLUMN `LatenessL99Minutes` INT NULL + `LatenessL99UpdatedAt` DATETIME2(3) NULL per D63 + D92 additive ALTER.
2. **B194**: `migrations/pii_inventory_audit_log.py` — CREATE TABLE `General.ops.PiiInventoryAuditLog` (10-column append-only schema per BACKLOG.md L374; D26 + D92 additive).
3. **B195**: `migrations/capacity_baseline_log.py` — CREATE TABLE `General.ops.CapacityBaselineLog` (schema MUST match Tool 16 `CapacityResult` dataclass per `phase1/04b_phase_0_closure_tools.md` § 5; D26 + D92 additive).

**Each migration script must**:
- Be idempotent (`IF NOT EXISTS` guard on every DDL statement)
- Record audit row to `PipelineEventLog` with `EventType = 'MIGRATION_<NAME>'` per D76 + Round 7 § 1.1 SchemaContract supersession protocol. **Audit-row idempotency contract (per Pattern E R1C1-4 finding 🔴 9 fix + R1C2-3 finding 🔴 I3 discriminator addition + R1C4 findings 🔴 G1 server-key + 🔴 G2 abandonment_noop)**: every script invocation writes EXACTLY ONE audit row regardless of DDL no-op state; **canonical Metadata JSON shape**: `{"event_kind": "apply" | "noop" | "abandonment" | "abandonment_noop", "ddl_applied": <bool>, "idempotency_path": "first" | "no-op" | null, "ddl_statements_executed": <int>, "server": "<env>", ...kind-specific-fields}`. **Mandatory `server` key** (added per R1C4 🔴 G1 — Gate 6 DISTINCT-counting query needs this key; CLAUDE.md MIGRATION_* registry cascade tracked as B199). The `event_kind` discriminator partitions all consumer filters cleanly: `apply` rows are first-applications with `ddl_applied=true` + `idempotency_path='first'`; `noop` rows are re-runs of an `apply` (idempotent DDL no-op) with `ddl_applied=false` + `idempotency_path='no-op'`; `abandonment` rows are forward-only-supersession events with `ddl_applied=false` + `idempotency_path=null` + kind-specific fields per § 7 § 4.4 rollback row; `abandonment_noop` rows are re-runs-after-abandonment (IF NOT EXISTS guard at § 7 step 1 fires; audit row STILL writes to honor the "exactly one row per invocation" contract) with `ddl_applied=false` + `idempotency_path=null` + Metadata key `prior_abandonment_event_id` pointing to the original abandonment row. **§ 6 Gate 6 count is "9 first-application MIGRATION_* events filtered on `event_kind = 'apply'` AND `ddl_applied = true`"**, not raw count of MIGRATION_* rows. Inverse re-run analysis filter is `event_kind = 'noop'` (NOT `idempotency_path = 'no-op'` alone — that would silently include `abandonment_noop` rows). Abandonment audit lineage filter is `event_kind IN ('abandonment', 'abandonment_noop')`.
- Add a SchemaContract row per Round 7 § 1.1 (SchemaContract supersession protocol; table DDL at Round 1 § 23) to formalize the additive change
- Be revertable ONLY via forward-only supersession per D92 + § 7 § 4.4 rollback row (NOT in-place DROP COLUMN / DROP TABLE — explicitly forbidden by D92 "Rename / removal NOT permitted post-lock"). Migration scripts MUST NOT include commented-out DROP statements that suggest reverse-state rollback; the canonical rollback path is the SchemaContract abandonment procedure documented at § 7

**Execution ladder**: dev → test → prod, with check-pause-check between servers. After dev apply, verify with `SELECT * FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'UdmTablesList' AND COLUMN_NAME LIKE 'LatenessL99%'` (must return 2 rows) before proceeding to test.

**Acceptance**: 9 first-application migrations total (3 scripts × 3 servers) filtered on `Metadata.event_kind = 'apply'` AND `Metadata.ddl_applied = true`; 3 SchemaContract rows per server. Raw `MIGRATION_*` row count may exceed 9 across retries — the canonical Gate 6 count uses the filter per § 4.4 audit-row contract.

### § 4.5. Tools 14 / 15 / 16 implementations (B188 / B189 / B190)

Per Round 4.5b supplement at `phase1/04b_phase_0_closure_tools.md`:
- **B188 (Tool 14 `measure_lateness.py`)** — wraps NEW `data_load/lateness_measurement.measure_lateness()`; depends on B193 columns; § 3 of supplement is canonical spec
- **B189 (Tool 15 `import_pii_inventory.py`)** — wraps NEW `data_load/pii_inventory_importer.import_pii_inventory()`; depends on B194 audit log table; § 4 of supplement is canonical spec; gates B185 data-side PII inventory population
- **B190 (Tool 16 `measure_capacity_and_partition.py`)** — wraps NEW `data_load/capacity_baseline.measure_capacity_and_partition()`; depends on B195 audit log table; § 5 of supplement is canonical spec

**Each Tool follows**:
- D74 exit codes / D75 args / D76 audit row / D77 Tier 0 scaffold (6 canonical assertions)
- Operator-driven via CLI (Tool 15 has no Automic schedule; Tools 14 + 16 add Automic jobs JOB_LATENESS_MEASURE + JOB_CAPACITY_BASELINE per § 6 of supplement — Automic config deferred to Phase 2 R1 close-out per per-task schedule additions)

**Execution**:
- Author each Tool + tests; Tier 0 PASS in < 5s
- Invoke each Tool once on dev with smoke-test inputs (synthetic data only)
- B188: measure-lateness against UdmTablesList rows where `SourceName = 'DNA'` AND `LastModifiedColumn IS NOT NULL`
- B189: import-pii-inventory dry-run against a test CSV (no real PII)
- B190: measure-capacity against a non-pilot table for smoke (e.g. `DNA.osibank.ACCT_HISTORY` if present)

**Acceptance**: B188 + B189 + B190 implementations land; 3 Tier 0 test suites PASS; 3 dev-smoke invocations PASS; PipelineEventLog has `CLI_MEASURE_LATENESS` + `CLI_IMPORT_PII_INVENTORY` (Tool 15 audit-row family per D76) + `CLI_MEASURE_CAPACITY_AND_PARTITION` rows.

### § 4.6. RB-12 Phase 1 artifact deployment (dev → test → prod)

Procedure delegated to **`05_RUNBOOKS.md` § RB-12** (🟢 Locked at Round 6 close-out per B127). RB-12 covers:
- Pre-flight: 12 pre-checks per D87 (this § 3 mirrors them at R1 scope)
- Artifact prep: immutable git tag, atomic symlink swap via `mv -T` per D84
- Cadence: dev nightly → test daily after dev pass + 4h soak → prod weekly Monday window per D86
- Post-deploy: 10 post-checks per D87
- Rollback: prior tag reachable via symlink revert

**Deploy cadence per D86** (D86 = deploy schedule; D109 = separate pipeline-run schedule that pre-existing operational system follows after deploys land):
- Dev deploy: any weekday evening; soak overnight (D86 dev-nightly slot)
- Test deploy: next weekday, after dev soak passes 4 hours per D86 (D86 test-daily +4h soak slot)
- Prod deploy: subsequent Monday window per D86 prod-weekly-Monday-window

**Pipeline-run schedule per D109** (separate concern from deploy timing — D109 governs WHEN pipelines run, D86 governs WHEN deploys happen):
- Once deploys land, the operational pipeline runs per D109 dual-Automic prod-then-test pattern (AM Prod 02:00 + Test 06:00 weekdays; PM Prod 17:00 + Test 21:00 daily) with SQL-table coordination via PipelineExecutionGate per D29/D33/SP-3/SP-4
- Deploy work SHOULD avoid coinciding with D109 schedule slots — coordinate so the test deploy + 4h soak doesn't overlap a Test 06:00 pipeline run; coordinate so prod Monday deploy doesn't overlap Prod 02:00 OR 17:00 cycles

**Acceptance**: 3 deploys complete; 3 `DEPLOYMENT_DEV` + `DEPLOYMENT_TEST` + `DEPLOYMENT_PROD` rows in PipelineEventLog per D76; each post-check PASS.

### § 4.7. Dev environment end-to-end smoke test

After § 4.1-4.6 complete on dev, run synthetic-data smoke through the full pipeline:

**Steps**:
1. Insert one synthetic row into `UDM_Stage.DNA.ACCT_smoke` (a test-only staging table; NOT `ACCT_cdc`)
2. Invoke `main_small_tables.py --table ACCT_smoke --source DNA --dry-run`
3. Verify 5 STARTUP_* events written per D85
4. Verify `EXTRACT` + `CDC_PROMOTION` + `SCD2_PROMOTION` + `CSV_CLEANUP` + `TABLE_TOTAL` events in PipelineEventLog
5. Verify `PipelineLog` has narrative entries for each step
6. Verify gate-table coordination per D29 + SP-3/SP-4 + **I22** (concurrent-acquire idempotency at `04_EDGE_CASES.md:92`) — synthetic row should acquire + release gate cleanly; if smoke is extended to simulate concurrent acquirers, the loser side's UNIQUE-violation TRY/CATCH path per SP-3 atomicity contract is the I22 verification
7. Tear down: drop `ACCT_smoke` table; no rollback needed

**Acceptance**: PipelineEventLog shows clean 5 STARTUP + 5 step events; gate-table state clean post-run; no errors in PipelineLog.

### § 4.8. R02 Round 0.5 spike (D47)

**Per phase2/00_phase_overview.md L76**: R02 (Round 0.5 spike not executed) is a 🔴 blocker for Phase 2 R3 AND Phase 2 R1 acceptance requires R02 closed.

**Status as of 2026-05-12**: 🔴 NOT yet executed (staffing-accepted per user 2026-05-12 multi-agent cascade; coding/execution pending).

**Spike scope** (per `phase1/03_round_0_5_spike_plan.md`):
- **Scenario A**: D6 vault concurrency via SP-1 with 16 concurrent threads → verify no token-issuance race; OrphanedTokenLog clean
- **Scenario B**: D16 Parquet stage-check-exchange via atomic rename + UNIQUE constraint → verify no double-stage on crash-recovery
- **Scenario C**: D29 Automic gate-table acquisition via SP-3/SP-4/SP-5/SP-6 with normal/failover/cancellation/concurrent-test sub-tests → verify cooperative cancellation per D33 + failover per RB-9 + **I22 idempotency** (`04_EDGE_CASES.md:92` — concurrent-acquire loser-side UNIQUE-violation TRY/CATCH path is exactly Scenario C's concurrent-test sub-test)

**Execution model**: ~500 lines of throwaway Python in `_spike_round_0_5/`; 1 engineer-week on dev environment only; does NOT write to test or prod.

**Acceptance** (R1-specific): Scenarios A + B + C all PASS; throwaway code archived but not deployed; lessons-learned captured in `_spike_round_0_5/findings_2026-MM-DD.md` for future reference; R02 risk-status updated 🔴 → ⚪ in RISKS.md.

---

## § 5. Post-step verification (10 post-checks per D87)

After each R1 sub-step (§ 4.1 through § 4.8), execute the 10 generic post-checks from `phase1/06_deployment.md` § 1.6 (Pre/post-deployment checklist contract per D87):

1. **Audit row written**: PipelineEventLog has new row for the sub-step's EventType with `Status = 'SUCCESS'`.
2. **Narrative log entries**: PipelineLog has at least 1 INFO entry per sub-step (operational visibility per OBS-1/OBS-2/OBS-3 conventions in CLAUDE.md).
3. **No fatal errors**: PipelineLog filtered by `LogLevel IN ('ERROR', 'CRITICAL')` returns zero rows for the BatchId.
4. **Gate-table clean**: PipelineExecutionGate has no stale rows (sp_getapplock released; D29 cooperative-cancellation invariants hold).
5. **Idempotency proof**: re-running the same sub-step produces no new effects (no new rows, no schema drift; per D15 idempotent invariant).
6. **Cross-server consistency**: if step ran on dev → test, post-step state on test matches dev within parity-baseline tolerance.
7. **Module startup clean on next invocation**: re-run `main_small_tables.py --list-tables`; STARTUP_* events still emit cleanly post-step.
8. **Tier 0 still green**: re-run `pytest tests/tier0/` after the step; no test regressions.
9. **Sensitive-data scan**: grep PipelineLog narrative entries for plaintext credential leaks; expect zero hits (D103 SensitiveDataFilter applied).
10. **POLISH_QUEUE skim**: skim P-1 / P-2 / P-3 / P-4 / P-6 / P-7 — close any whose underlying cosmetic drift was incidentally cleaned up by this sub-step's work per D113.

**Sub-step-specific post-checks** (relocated from pre-flight per Gap 3 corrective 2026-05-12 — these tools are AUTHORED in § 4.2/§ 4.3 so their PASS verification belongs as post-step checks of those sub-steps):

- **After § 4.2 (Tool 12 implementation)**: `tools/verify_credentials_load.py --server <env>` PASS on dev → test → prod (3 invocations); PipelineEventLog has 3 `CLI_VERIFY_CREDENTIALS_LOAD` SUCCESS rows.
- **After § 4.3 (Tool 13 implementation)**: `tools/capture_parity_baseline.py` PASS + JSON written on each of dev/test/prod; `tools/verify_server_parity.py` (R4 § 3.7) PASS against captured baselines; PipelineEventLog has 3 `CLI_VERIFY_SERVER_PARITY` SUCCESS rows.
- **After § 4.4 (B193/B194/B195 migrations)**: `INFORMATION_SCHEMA.COLUMNS` reflects new columns; SchemaContract rows present; 9 first-application `MIGRATION_*` audit rows filtered on `Metadata.event_kind = 'apply'` AND `Metadata.ddl_applied = true` (3 scripts × 3 servers); raw row count may exceed 9 across retries per § 4.4 audit-row contract.
- **After § 4.5 (Tools 14/15/16 implementations)**: Tier 0 PASS for each of B188/B189/B190; dev smoke invocations PASS; 3 `CLI_*` SUCCESS audit rows.
- **After § 4.6 (RB-12 deploy ladder)**: 3 `DEPLOYMENT_*` rows (DEV / TEST / PROD) per D76 audit row contract; D87 10-post-check executes cleanly per server.
- **After § 4.7 (dev end-to-end smoke)**: 5 STARTUP_* + 5 step events in PipelineEventLog; gate-table clean.
- **After § 4.8 (R02 Round 0.5 spike)**: Scenarios A + B + C PASS; throwaway-code archived to `_spike_round_0_5/`; RISKS.md R02 score 🔴 → ⚪.

If ANY post-check fails → mark sub-step as 🟡; investigate; document in operator notes; do not advance to next sub-step until either remediation lands OR explicit deferral decision documented.

---

## § 6. Acceptance gate (R1 → R2 transition)

Per phase2/00_phase_overview.md L175-180. R1 is complete when ALL of the following PASS:

| # | Gate | Evidence |
|---|---|---|
| 1 | `tools/verify_credentials_load.py` PASS on all 3 servers | 3 `CLI_VERIFY_CREDENTIALS_LOAD` SUCCESS rows in PipelineEventLog |
| 2 | `tools/verify_server_parity.py` PASS across dev/test/prod (zero fatal, ≤ 3 warning) **AND** targeted INFORMATION_SCHEMA.COLUMNS query (per § 4.3 scope clarification — query at § 4.3 covers B193/B194/B195 changes) returns identical row-sets across all 3 servers (per Pattern E R1C2 🔴 I1 + R1C3 🔴 Q1/Q2 correction — parity baseline scope excludes full INFORMATION_SCHEMA per cycle-1 fix; targeted INFORMATION_SCHEMA query for the 3 specific migrations is the canonical cross-server schema-parity sub-check; SchemaContract is canonical contract registry without per-server keying so cannot be used for divergence detection) | 3 `CLI_VERIFY_SERVER_PARITY` SUCCESS rows + identical INFORMATION_SCHEMA query result-sets across 3 servers (sub-check evidence captured in operator notes per § 5 post-step verification — operator runs query on each server + compares row-sets manually OR via diff-tool) |
| 3 | PipelineEventLog shows clean STARTUP_CREDS_LOAD + STARTUP_VAULT_CONFIG + STARTUP_PARITY_CHECK + STARTUP_LEDGER_SWEEP + STARTUP_ORCHESTRATION_START events on dev smoke test | 5 STARTUP_* rows per dev BatchId |
| 4 | All 17 Phase 1 modules import + Tier 0 smoke tests pass in < 5s each per D67 | Tier 0 test report green |
| 5 | RB-14 audit row in `ManualCorrectionLog` for every server's migration | 3 audit rows |
| 6 | B193 + B194 + B195 migrations applied + SchemaContract rows present on all 3 servers | 9 first-application `MIGRATION_*` events counted via `SELECT COUNT(DISTINCT EventType + '_' + JSON_VALUE(Metadata, '$.server')) FROM PipelineEventLog WHERE EventType LIKE 'MIGRATION_%' AND JSON_VALUE(Metadata, '$.event_kind') = 'apply' AND JSON_VALUE(Metadata, '$.ddl_applied') = 'true'` (DISTINCT on (EventType, server) handles crash-retry duplicates per § 4.4 canonical Metadata shape mandates `server` key per R1C4 🔴 G1 fix; raw row count may exceed 9 across retries per § 4.4 contract) + 9 active SchemaContract rows (3 per server filtered on `EffectiveTo IS NULL`; SchemaContract is canonical contract registry — identical natural-key row sets across servers per Round 1 § 23 schema; cross-server schema-state verification is via § 4.3 + § 7 step 4 targeted INFORMATION_SCHEMA query, NOT SchemaContract). **Gate 6 diagnostic decision-tree (per R1C5 🟡 advisory)**: if `actual_count < 9`, halt and investigate per this order before assuming migration didn't run: (a) re-run § 4.3 DB-connectivity pre-check on the absent server(s) — SELinux-blocked DB connection (B197) prevents audit row writes; (b) check `PipelineEventLog` filtered by `EventType LIKE 'MIGRATION_%'` AND `Status='FAILED'` for crash-pre-audit-write evidence; (c) check `INFORMATION_SCHEMA.COLUMNS` directly on each server to confirm whether schema changes landed independently of audit-row state; (d) only after a/b/c return no signal, conclude migration didn't run + re-execute § 4.4 with appropriate idempotency-path branching |
| 7 | B188 + B189 + B190 Tool implementations land + Tier 0 PASS + smoke invocations PASS on dev | 3 Tier 0 reports + 3 dev-smoke event rows |
| 8 | RB-12 deploy ladder dev → test → prod complete; all 22 D87 checks (12 pre + 10 post) PASS per server | 3 DEPLOYMENT_* rows + 66 checklist-line audit notes |
| 9 | R02 Round 0.5 spike executed; Scenarios A + B + C PASS; lessons-learned doc landed | RISKS.md R02 score 🔴 → ⚪; `_spike_round_0_5/findings_2026-MM-DD.md` exists |
| 10 | Dev end-to-end smoke (§ 4.7) PASS | PipelineEventLog clean; gate-table clean |
| 11 | R1 close-out cascade per D60 + Pattern F per D89-D91 + Section 10 self-improvement per D95-D99 complete | `_validation_log.md` R1 close-out entry; HANDOFF §11 row appended |
| 12 | Pipeline-lead acceptance sign-off documented | `03_DECISIONS.md` R1-close D-number (D114 candidate) 🟢 Locked |

R1 acceptance D-number candidate: **D114** (Phase 2 Round 1 acceptance) per phase2/00 L233 estimate range D114-D116.

---

## § 7. Rollback procedures

Each R1 sub-step has its own rollback path. Catalog:

| Sub-step | Rollback procedure | Rollback evidence |
|---|---|---|
| § 4.1 RB-14 `.env` migration | Revert: copy `/etc/pipeline/.env` back to `/debi/.env`; restore prior mode/owner; per RB-14 § rollback | ManualCorrectionLog entry with reason |
| § 4.2 Tool 12 impl | Revert: git revert commit; redeploy via RB-12 with prior tag | DEPLOYMENT_ROLLBACK event row |
| § 4.3 Tool 13 + parity baseline | Revert: delete captured baseline JSON; git revert Tool 13 + module function commits | DEPLOYMENT_ROLLBACK event row |
| § 4.4 B193/B194/B195 migrations | **Forward-only supersession per D92** (NOT in-place DROP COLUMN / DROP TABLE — D92 explicit: "Rename / removal NOT permitted post-lock"). Procedure (per Pattern E R1C2 🔴 I2 fix — uses canonical SchemaContract `EffectiveTo`/`SupersededBy` mechanism per Round 1 § 23 schema; **no nonexistent `Status` column**; per R1C4 🔴 G2 audit-row contract preserved on re-run; per R1C5 🔴 I-NEW-1 prior-apply existence guard): (1) **TWO-CONDITION idempotency guard FIRST**: (1a) verify prior apply exists: `IF NOT EXISTS (SELECT 1 FROM General.ops.SchemaContract WHERE ContractKey = '<schema-element>' AND EffectiveTo IS NULL AND (JSON_VALUE(ContractValue, '$.abandonment') IS NULL OR JSON_VALUE(ContractValue, '$.abandonment') != 'true'))` → **HALT with operator error "cannot abandon never-applied element <ContractKey>"; do not write audit row** (this prevents orphan SchemaContract rows with dangling `original_contract_id` references — operator must run forward-apply migration first OR remove the abandon command from R1 scope); (1b) verify no prior abandonment exists: `IF NOT EXISTS (SELECT 1 FROM General.ops.SchemaContract WHERE ContractKey = '<schema-element>' AND EffectiveTo IS NULL AND JSON_VALUE(ContractValue, '$.abandonment') = 'true')` → proceed to steps 2-6 with `event_kind='abandonment'`; ELSE → skip steps 2-6 (all state-mutating + observational steps are idempotent or already-completed on first-time abandonment; nothing to re-do) and write audit row at step 7 with `event_kind='abandonment_noop'` + `prior_abandonment_event_id` Metadata key per § 4.4 canonical shape (honors the "EXACTLY ONE row per invocation" contract on re-runs); (2) within a single transaction: INSERT new SchemaContract row with `EffectiveFrom = SYSUTCDATETIME()`, `EffectiveTo = NULL`, `SupersededBy = NULL`, `ContractValue` JSON `{"abandonment": true, "reason": "<operator-supplied>", "abandoned_by": "<actor>", "original_contract_id": <prior row PK>}`; (3) UPDATE the prior contract row to `EffectiveTo = SYSUTCDATETIME()` AND `SupersededBy = <new row PK>` — this transitions the IX_SchemaContract_Active filtered unique index correctly; (4) document column/table in `CLAUDE.md` Do-NOT rules as "do not populate; abandoned YYYY-MM-DD via SchemaContract supersession (ContractKey=...)"; (5) verify B188 (Tool 14 `measure_lateness.py`) detects + ignores the abandoned column via `WHERE ContractValue NOT LIKE '%"abandonment":true%' OR EffectiveTo IS NOT NULL`; (6) leave physical column/table in place permanently; (7) **mandatory** write MIGRATION_<NAME> audit row regardless of step-1 branch (preserves audit-row contract — see Metadata shape below). The audit trail is the abandonment SchemaContract chain (prior row's `SupersededBy` + new row's `ContractValue.abandonment`), NOT a reversed-state. | Re-uses existing `MIGRATION_<NAME>` EventType per D76 family (already in CLAUDE.md MIGRATION_* registry); Metadata JSON carries one of two shapes depending on step-1 branch: **first-time abandonment**: `{"event_kind": "abandonment", "supersession_contract_id": <new SchemaContract row PK>, "original_migration_event_id": <prior MIGRATION_<NAME> event PK>, "ddl_applied": false, "idempotency_path": null, "ddl_statements_executed": 0, "server": "<env>"}`; **re-run-after-abandonment (abandonment_noop)**: `{"event_kind": "abandonment_noop", "prior_abandonment_event_id": <original abandonment row PK>, "ddl_applied": false, "idempotency_path": null, "ddl_statements_executed": 0, "server": "<env>"}`. NO new event family invented + SchemaContract abandonment chain written per D92 + Round 7 § 1.1 canonical supersession protocol |
| § 4.5 Tools 14/15/16 impls | Revert: git revert commits; redeploy | DEPLOYMENT_ROLLBACK event rows |
| § 4.6 RB-12 deploy | Revert: symlink swap to prior tag per D84; RB-12 § rollback | DEPLOYMENT_ROLLBACK event row |
| § 4.7 Dev smoke | Tear down: drop `ACCT_smoke` test staging table (no real data at risk) | DEBUG-level cleanup log |
| § 4.8 R02 spike | Archive throwaway code; no rollback needed (spike never wrote to prod) | `_spike_round_0_5/` directory archived |

**Whole-R1 rollback**: if R1 must be abandoned mid-way:
1. Reverse the sub-step order (e.g., rollback § 4.6 deploys first, then § 4.4 migrations, then § 4.1 .env)
2. Each per-server rollback executes prod → test → dev (reverse of deploy order)
3. Audit-row trail in PipelineEventLog preserves the rollback decision + executor
4. RISKS.md R02 + R-future risk delta documented

**Partial-ladder failure recovery** (per Pattern E R1C1-4 finding 🔴 8 fix): the dev → test → prod ladder is NOT atomic across servers. If a sub-step lands on dev + test but fails on prod (or any partial-success state), use this 4-step decision tree BEFORE reversing or forwarding:

1. **Detect which servers actually applied the change**: query each server's state directly (INFORMATION_SCHEMA / SchemaContract rows / artifact-tag symlink) — do NOT trust the operator's mental model. Document each server's state in operator notes.
2. **Classify the failure cause**:
   - **Transient** (network blip, transient SQL connection error, brief Automic timeout): retry on prod after waiting + verifying transient resolved.
   - **Server-specific structural** (name collision, permissions, OS version drift, etc.): isolate the structural issue; decide whether to fix-prod-forward OR back-out dev+test.
   - **Cross-server-systemic** (script bug affecting all servers but late-discovered): back out dev + test; do NOT proceed to prod.
3. **For schema migrations (§ 4.4) specifically**: if dev + test succeeded but prod failed, **do NOT use ALTER DROP COLUMN on dev + test** (D92 forward-only). Instead either (a) fix-prod-forward by resolving the prod-specific structural cause (recommended); OR (b) leave dev + test with the additive column in place + open a B-N tracking the cross-server divergence + halt R1 until resolution.
4. **Parity baseline re-capture + targeted INFORMATION_SCHEMA cross-server query mandatory after partial-ladder recovery** (per Pattern E R1C2 🔴 I1 + R1C3 🔴 Q1/Q2 correction): any cross-server divergence introduced by partial application invalidates the § 4.3 baseline; re-capture per Tool 13 BEFORE any further R1 sub-step proceeds OR before R2 begins. **Critical**: § 4.3 baseline scope explicitly EXCLUDES full INFORMATION_SCHEMA per cycle-1 🔴 10 fix — so cross-server schema divergence (the exact failure class partial-ladder produces) will NOT be caught by `verify_server_parity.py` alone. Operator MUST ALSO run the targeted INFORMATION_SCHEMA query per § 4.3 + Gate 2 sub-check (covers B193/B194/B195 schema elements specifically): `SELECT 'B193' AS Migration, TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'UdmTablesList' AND COLUMN_NAME IN ('LatenessL99Minutes', 'LatenessL99UpdatedAt') UNION ALL SELECT 'B194', TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'ops' AND TABLE_NAME = 'PiiInventoryAuditLog' UNION ALL SELECT 'B195', TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'ops' AND TABLE_NAME = 'CapacityBaselineLog' ORDER BY Migration, COLUMN_NAME` on each server + compare row-sets. Any cross-server row-set mismatch = real cross-server schema divergence; halt R1 until resolved via forward-only-supersession path at § 4.4 rollback row. The § 6 Gate 2 acceptance check now includes this INFORMATION_SCHEMA sub-check explicitly. SchemaContract is canonical contract registry (no `ServerName` column per Round 1 § 23) and cannot serve as the divergence-detection mechanism — INFORMATION_SCHEMA is the right tool because schema state is per-server while SchemaContract is per-contract-key.

**No prod data at risk during R1** because R1 does NOT write real ACCT data (R2 starts that). Rollback risk is operational-config + schema-divergence (cross-server), not data-integrity.

---

## § 8. Edge cases (applicability against existing series)

R1 execution exercises the following edge case classes from `04_EDGE_CASES.md`. Canonical series catalog: **M / S / I / N / P / G / D / F / V / DP / T / SI** (12 series — DP-Series added 2026-05-10 at Round 6 close-out per B121 at L163; T-Series added 2026-05-10 partial at Round 5 + Round 6 per B108 + B121 at L179; CLAUDE.md L634 updated 2026-05-12 via Pattern E R1C1 cycle 1 to reflect the 12-series canonical register). Each applicable series is verified during § 4 / § 5 execution; new R1-specific cases are added to `04_EDGE_CASES.md` if surfaced during validation.

| Series | Applicability | R1-specific notes |
|---|---|---|
| **M-series** (multi-server / multi-environment) | High | All 3 environments touched; M-class events expected on dev → test deploy parity edges |
| **S-series** (security / credentials) | High | RB-14 .env migration + D103 13-layer model + SELinux restore-context exercises S-class |
| **I-series** (idempotency) | High | Migration scripts B193/B194/B195 + module startup + Tier 0 tests all exercise I-class; **I22 (SP-3 concurrent-acquire idempotency at `04_EDGE_CASES.md:92`)** specifically exercised by § 4.7 step 6 dev smoke + § 4.8 R02 Scenario C concurrent-test sub-tests |
| **N-series** (NULL handling) | Medium | B193 ADD COLUMN with NULL default; existing rows get NULL — verify CDC/SCD2 handle gracefully |
| **P-series** (PII / privacy) | Medium | B194 PiiInventoryAuditLog schema enforces D26 + D102; no real PII until R2 |
| **G-series** (gate / locking) | Medium-High | D29 + SP-3/SP-4 + sp_getapplock all exercised during § 4.7 smoke; G7 (table newly added, dates < FirstLoadDate excluded) applies once B193 LatenessL99Minutes column populated by Tool 14 |
| **D-series** (deployment 2x/day cadence) | High | RB-12 + D86/D87 + D84 artifact contract all exercised |
| **F-series** (failover) | High | F21 (GPG passphrase loss / TPM2 hardware fault) defended against by § 4.2 verify_credentials_load.py; F22 (parity exception expiry) detected by § 4.3 verify_server_parity.py; F23 (MALLOC_ARENA_MAX unset) checked at § 3 pre-check #7 module startup; R02 Scenario C extends to F-class verification |
| **V-series** (vault) | Medium | R02 Scenario A covers concurrency; primary verification at R2 |
| **DP-series** (deployment pipeline) | High | DP1 atomic symlink swap + DP2 systemd restart + DP4 subprocess TPM2 unseal storm + DP6 NTP skew (mirrors pre-check #11) + DP7 TPM2 PCR drift all directly exercised by § 4.6 RB-12 deploy ladder + § 4.1 RB-14 |
| **T-series** (testing) | High | T1 (Tier 0 drift) + T3 (Tier 3 flake) exercised by § 4.2/§ 4.3 Tier 0 invocations + § 4.7 dev smoke; pre-check #2 mandates Tier 0 green but R1 should verify Tier 0 hasn't drifted from spec contract |
| **SI-series** (self-improvement discipline) | Low | R1 close-out Section 10 self-improvement skill suite invokes per D95-D99 |

**Non-series cross-cutting concerns** (worth noting separately):
- **Timezone (TZ)**: TZ env-var pin per Round 4.5b polish; verified by Tool 13 parity baseline; cross-cuts S + I + M
- **Dual-Automic prod-test 4-hour-gap (D109)**: pipeline-run schedule coordination via PipelineExecutionGate per D29/D33/SP-3/SP-4; cross-cuts G + F + DP

**New R1-specific candidate edge cases** (surface during execution, append to `04_EDGE_CASES.md` if confirmed):
- **`F25` candidate** (replaces prior `S-next` framing per Pattern E R1C1-3 reframe): SELinux restore-context cross-server drift — if `restorecon -v /etc/pipeline/.env` outputs differ across dev/test/prod (different policy modules loaded; different `semanage fcontext` registrations), parity baseline must capture the SELinux label too. Cross-server config-discipline edge, NOT a SCD2-reliability S-series edge.
- **`D-next` candidate**: already partly covered by **DP3** (parity baseline drift detected post-deploy) + **F18** (gate Status='SUCCEEDED' between request and 15-min timeout); reframe as DP3 cross-ref + sub-case rather than standalone D-next.
- **`I-next` candidate**: already partly covered by **I3** (BatchId-reuse short-circuit) + **I11** (schema evolution between runs); reframe as I3 + I11 cross-ref + sub-case verifying `IF NOT EXISTS` no-op idempotency guarantees the audit-row contract from § 4.4 + 🔴 9 fix.

---

## § 9. Validation gates (D55 5-gate for this spec doc)

This spec doc itself submits to D55 5-gate validation before 🟢 Lock. Reviewer must be independent of the producer per D56 mandatory-second-pass discipline.

### Gate 1 — Cross-reference

- All D-numbers cited in § 2 resolve in `03_DECISIONS.md` ✅ (verified at authoring; auditor re-verifies)
- All B-numbers cited (B183-B196) resolve in `BACKLOG.md` ✅
- All P-numbers cited (P-1, P-2, P-3, P-4, P-6, P-7) resolve in `POLISH_QUEUE.md` ✅
- All RB-numbers cited (RB-12, RB-14, RB-1, RB-2, RB-3, RB-9) resolve in `05_RUNBOOKS.md` ✅
- All Tool numbers (12-16) resolve in `phase1/04a_phase_0_prep_tools.md` + `phase1/04b_phase_0_closure_tools.md` ✅
- All event-row types (CLI_*, MIGRATION_*, STARTUP_*, DEPLOYMENT_*) resolve in `CLAUDE.md` EventType family registry ✅

### Gate 2 — QA

- Procedural clarity: each § 4 sub-step has clear pre-condition + action + post-condition
- No internal contradictions (e.g., § 4.4 dependency order matches § 6 gate count)
- Tier classification (Tier β) matches D97 cycle-cadence rubric
- Carryover B-items / P-items correctly identified in § 10

### Gate 3 — Edge cases

- § 8 covers all 12 applicable edge case series (M/S/I/N/P/G/D/F/V/DP/T/SI per `04_EDGE_CASES.md` canonical register — DP at L163; T at L179; SI at the L179+ section. CLAUDE.md L634 updated 2026-05-12 via Pattern E R1C1 to match)
- Round 8 SI series included per `phase1/08_sub_agent_self_improvement.md` § 10
- Round 6 DP-Series additions + Round 5/6 T-Series additions included per `04_EDGE_CASES.md:163` (DP per B121) + `:179` (T per B108 + B121)

### Gate 4 — Edge case validation

- Each edge case in § 8 has explicit verification step in § 4 OR § 5
- New R1-specific candidate edges (S-next / D-next / I-next) flagged for confirmation during execution

### Gate 5 — Idempotency / regression

- § 4 sub-steps are independently idempotent (re-running produces no new effects per D15)
- Whole R1 procedure is idempotent (R1 re-run after success is a no-op + audit row trail)
- No regression vs Phase 1 invariants (CDC mechanics + SCD2 + BCP CSV contract + vault all unchanged)
- POLISH_QUEUE P-N items don't introduce regressions (cosmetic-only per D113)

### Validation log entry

This spec doc 🟡 → 🟢 transition requires a `_validation_log.md` entry per D55. Authoring the entry is § 11 below. Status flip happens AFTER validation cycle completes per `udm-checks-and-balances` discipline.

---

## § 10. Carryover B-items + P-items (closure targets at R1)

B-items whose IMPLEMENTATION executes at R1 (B-numbers themselves are already ⚫ CLOSED at spec lock; impl work tracked against same B-numbers per project convention — see BACKLOG.md L88-90 for B182/B183/B184 spec-closure 2026-05-11):

- **B183** (Tool 13 `capture_parity_baseline.py`) — B-number ⚫ CLOSED 2026-05-11 (spec lock at `phase1/04a_phase_0_prep_tools.md` § 4); **implementation lands at § 4.3**
- **B184** (Tool 12 `verify_credentials_load.py`) — B-number ⚫ CLOSED 2026-05-11 (spec lock at `phase1/04a_phase_0_prep_tools.md` § 3); **implementation lands at § 4.2**

B-items whose B-number itself closes AT R1 (newly-opened 🟡 items that need both spec + impl + close-out):

- **B188** (Tool 14 implementation) — 🟡 → ⚫ at § 4.5 execution
- **B189** (Tool 15 implementation) — 🟡 → ⚫ at § 4.5 execution
- **B190** (Tool 16 implementation) — 🟡 → ⚫ at § 4.5 execution
- **B193** (UdmTablesList lateness columns migration) — 🟡 → ⚫ at § 4.4 execution
- **B194** (PiiInventoryAuditLog table migration) — 🟡 → ⚫ at § 4.4 execution
- **B195** (CapacityBaselineLog table migration) — 🟡 → ⚫ at § 4.4 execution

B-items REFERENCED at R1 but NOT closing here (carry forward):
- **B185** (data-side PII inventory population) — gated by B189 + compliance review; closes at R2 OR R3
- **B191** (Snowflake test conclusion) — ~mid-June 2026; gates Phase 5 + Tool 16 partition refinement
- **B196** (Step 7 producer-checklist formalization) — closes at R1 close-out OR R2 kickoff per WSJF 1.5

P-items closing AT R1 OR R1 kickoff:
- **P-1** (D109 supersession crumb refresh in Round 4.5b § 6) — closes at R1 close-out
- **P-2** (D107 3-revision arc cascade audit) — closes at R1 kickoff sweep
- **P-3** (D106 → D109 supersession cascade audit) — closes at R1 kickoff (combined with P-2)
- **P-4** (_validation_log.md first-archive execution) — closes at R1 close-out per policy text
- **P-6** (Pitfall #9.i arithmetic drift reconciliation; 🟠 Noticeable per priority bump 2026-05-12) — closes at R1 close-out
- **P-7** (D113 cascade to 3 missed aggregate docs) — closes at R1 close-out (combined with P-1)
- **P-8** (`ACCT_smoke` invented table name; § 4.7 + § 7) — closes at R1 § 4.7 implementation
- **P-9** (D-number table in § 2 not numerically sorted) — closes at R1 close-out polish sweep
- **P-10** (`phase2/00_phase_overview.md` R1 row status post-cycle update) — closes at this session OR cycle 2 close-out
- **P-11** (`HANDOFF.md` §3 in-flight R1 entry post-cycle update) — closes at this session OR cycle 2 close-out
- **P-12** (`CLAUDE.md` L634 "Rounds 1-5" wording inaccuracy) — closes at next CLAUDE.md edit cycle

R1 close-out should produce a coordinated P-item closure sweep — touching all 11 listed P-items in one cascade.

---

## § 11. Validation log entry (to be authored at R1 spec doc 🟡 → 🟢)

Format: per `_validation_log.md` "How to add an entry" template at the bottom of that file. This section reserves the slot; actual entry is appended to `_validation_log.md` at the validation cycle close.

Required fields:
- Date + artifact (`phase2/01_pilot_prerequisites.md`)
- Trigger (initial authoring 2026-05-12)
- Validator (must be independent per D56; spawn `udm-design-reviewer` or equivalent)
- 5-gate results (Gates 1-5 per § 9)
- Second-pass invocation if any Gate returns 🔴
- 🟡 carryover items → P-numbers OR B-numbers per D113 + Gate 1 guidance
- Verdict + lock status flip

**Pattern E invocation**: per Phase 1 precedent (Rounds 2 + 4 + 5 + 6 + 7 + 8 all used Pattern E from cycle 1), R1 spec doc validation should invoke 5-agent Pattern E from cycle 1 to maximize first-pass catch rate. Per `_reviewer_effectiveness.md` empirical evidence: column-walk specialty + cross-reference specialty + edge-case-validation specialty + idempotency specialty + advisory researcher.

**Pattern F at R1 close-out**: per D89-D91 mandatory at every round close-out. Layer 1 deterministic script (`tools/verify_cascade.py`) + Layer 2 paired-judgment agents (`udm-cascade-auditor` × 2). Sub-class evidence-base extension expected (likely 9.i / 9.j / 9.k recurrence on R1 execution).

---

## Acceptance + sign-off

R1 spec doc 🟢 Lock awaits:
1. D55 5-gate validation cycle completes clean (or D72-style convergence-confirmed/math-infeasibility acceptance)
2. Pipeline lead sign-off documented in `_validation_log.md`
3. R1 execution can begin (subject to R02 Round 0.5 spike progress)

**Current status**: 🟡 Plan-draft 2026-05-12 (initial authoring complete; awaits independent validation + pipeline-lead sign-off).
