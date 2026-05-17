# UDM Pipeline Migration — Decision Log

Every architectural decision made during the planning phase, with rationale and status. New decisions append to this log; superseded decisions stay in place with a `superseded by` link.

## Decision Status Legend

- 🟢 Locked — agreed and binding
- 🟡 Proposed — recommended, awaiting sign-off
- 🔴 Deferred — explicit pause until trigger condition
- ⚫ Superseded — replaced by a later decision

---

## D1: Switch from change-detection CDC to append-only-equivalent semantics

**Status**: 🟢 Locked
**Driver**: Manager request; regulatory audit need.

**Decision**: Replace the legacy "1 Stage row per PK with hash-deduped change detection" pattern with full per-run audit trail via Parquet snapshots, while keeping SCD2 in Bronze on hash-based change detection.

**Rationale**: Bronze SCD2 alone proved sufficient for regulator queries about state-on-date-X. The remaining audit gap — "did the pipeline observe row X on date Y?" — is filled by Parquet snapshots, not by changing the Stage semantic.

**Superseded by D2** for the actual mechanism.

---

## D2: Drop the Stage layer entirely; Parquet snapshots replace it

**Status**: 🟢 Locked
**Driver**: Manager pushback against the Stage-and-snapshot dual-layer approach; cost/simplicity preference.

**Decision**: Remove the `UDM_Stage.{Source}.{Table}_cdc` tables. Pipeline writes a Parquet snapshot per run directly to the network drive; SCD2 promotion reads the in-memory DataFrame and compares against Bronze active rows. Stage no longer exists as a layer.

**Rationale**:
- Hash compare against Bronze (existing SCD2 behavior) makes Stage's hash compare redundant for change detection
- Parquet snapshots provide the audit-grade per-run history
- Significant code reduction (~40% on the CDC side)
- Industry-standard data lake pattern (Iceberg, Delta, Hudi)

**Trade-off accepted**: SCD2 reads slightly more rows from Bronze per run (active rows for matching PKs). Already efficient with `run_scd2_targeted` pattern.

---

## D3: Keep SCD2 in Python+Polars indefinitely (do not migrate to Snowflake)

**Status**: 🟢 Locked
**Driver**: Cost discipline ($120K/yr Snowflake cap); existing investment in audited Python pipeline; agent research validation.

**Decision**: SCD2 promotion runs in Python+Polars on the existing Linux server. Snowflake is restricted to: analytics consumption, periodic full-row reconciliation (P3-4), ad-hoc backfills.

**Rationale**: Agent 1 research (December 2025) found:
- Python on owned hardware: ~$0/run incremental
- Snowflake-native daily SCD2: ~$36-120K/year — would consume entire budget
- Python's audited edge-case inventory (CLAUDE.md, ~14 categories) would need to be re-encoded as MERGE pre/post-conditions
- Maintainability: Python wins on 5-year horizon for SCD2 specifically (loud failure mode vs. silent MERGE failure)

**Migration triggers**: see `00_OVERVIEW.md` § "Migration Triggers" for conditions that would force revisit.

---

## D4: Network drive Parquet for snapshot storage

**Status**: 🟢 Locked
**Driver**: Existing infrastructure; storage budget; eventual Snowflake migration.

**Decision**: Parquet files live on the existing network drive. Path layout: `\\archive\source={Source}\table={Table}\year={YYYY}\month={MM}\day={DD}\batch={BatchId}_part-{N}.parquet`.

**Rationale**:
- Zero new storage cost (network drive already paid for)
- Hive-style partitioning compatible with Polars, DuckDB, Snowflake external tables
- Eventual Snowflake migration: same Parquet files become Iceberg-managed without movement

---

## D5: Snowflake-managed Iceberg tables for Snowflake mirror

**Status**: 🟡 Proposed (Phase 5)
**Driver**: Cost optimization (Agent 2 research) and tool parity.

**Decision**: When Snowflake integration lands in Phase 5, Bronze and audit-archive use Snowflake-managed Iceberg tables, not COPY INTO + native micro-partitions.

**Rationale**: Agent 2 research found:
- Iceberg keeps storage on cheap object storage; native is ~5× more expensive at $23/TB/month
- Snowflake's Iceberg scanner is now within ~2× of native performance
- Single source of truth: Polars on network drive reads exactly the bytes Snowflake reads

**Open**: actual cost validation in Phase 0 trial week-1 data.

---

## D6: PII protection via in-house tokenization vault

**Status**: 🟢 Locked
**Driver**: Strict open-source policy; no external cloud services for cryptography; idempotency requirement.

**Decision**: PII columns (SSN, EIN, account number, email, name) are replaced with random tokens via `General.ops.PiiVault` — a SQL Server-resident plaintext-to-token map. Decryption is via stored procedure with role check + audit log.

**Rationale**:
- Zero new software (no Vault, no cloud KMS, no HSM, no Python crypto library beyond what's already in stack)
- PCI-DSS 4.0 explicitly endorses tokenization with vault scope-reduction
- Idempotency natural: lookup-before-insert returns the same token for the same plaintext
- Auditable: every plaintext access logged via `PiiVaultAccessLog`

**Trade-off accepted**: vault corruption is catastrophic; mitigated by SQL Server backups + restore-test rehearsal.

**Superseded D6-prev**: cloud KMS proposal (rejected: no external cloud services allowed).

---

## D7: AES-GCM-SIV considered as fallback if vault becomes a bottleneck

**Status**: 🔴 Deferred
**Driver**: Performance hedge.

**Decision**: If `General.ops.PiiVault` lookup performance degrades below acceptable throughput (estimated trigger: >10× current pipeline duration), the fallback is TPM-sealed master key + AES-256-GCM-SIV (deterministic mode). Documented but not implemented.

---

## D8: Operation enum + boolean is_current (not 3-state combined)

**Status**: 🟢 Locked
**Driver**: Industry research (Agent 1 — Dec 2025).

**Decision**: Stage rows historically used `_cdc_is_current ∈ {0,1,2}` as a 3-state combined flag. After dropping Stage (D2) this is moot for the live pipeline, but for backwards-compatibility in the legacy Stage tables during cohort migration, the documented semantic is: `_cdc_operation CHAR(1)` ∈ {I,U,D,R} + `_cdc_is_current BIT` ∈ {0,1}.

**Rationale**: Every authoritative CDC source (Debezium, Fivetran, Delta CDF, Iceberg, DMS, Snowflake Streams, dbt) separates operation enum from currency flag. Conflating them forces every consumer to know about the conflation.

---

## D9: Bronze `UdmActiveFlag` keeps three values {0, 1, 2}

**Status**: 🟢 Locked
**Driver**: SCD2-R4 legacy alignment; existing nonclustered indexes filtered on `UdmActiveFlag = 2`.

**Decision**: Bronze's `UdmActiveFlag` retains 3-value semantic — 0 (historic, update-closed), 1 (active), 2 (deleted at source). This is independent of the Stage `_cdc_is_current` decision (D8).

**Rationale**: Downstream consumers and existing indexes depend on the three-value semantic. Collapsing would silently change query results.

---

## D10: Resurrection captured via `UdmScd2Operation = 'R'`

**Status**: 🟢 Locked
**Driver**: Existing pipeline behavior (E-18, M3); audit trail value.

**Decision**: When a previously deleted PK reappears in source, the new Bronze version carries `UdmScd2Operation='R'`. Distinct from the standard `'I'` (new insert) and `'U'` (update) operations.

**Rationale**: Agent 1 research: not standard in CDC log tools but defensible and audit-friendly. Already implemented; no reason to remove.

---

## D11: Lookback driven by empirical L_99 measurement

**Status**: 🟢 Locked
**Driver**: Agent 2 research; current fixed L=30 may be wrong per table.

**Decision**: Replace fixed `LookbackDays = 30` with per-table `L_99` measured via the lateness profiling query. Set `LookbackDays = max(L_99 × 1.5, business_minimum, 7)` per table, clipped to time budget `L_time_max`.

**Rationale**: Agent 2 research:
- Exponential decay assumption understates the heavy tail of real transactional systems
- Streaming community uses p99 of measured event-delay distribution
- Industry pattern: measure-then-quantile, not solve-for-L on assumed distribution

**Open**: run measurement query on top 5 large tables (Phase 0 deliverable 0.2).

---

## D12: Date-range schedule table (`ExtractionRangePolicy`)

**Status**: 🟢 Locked (infrastructure in Phase 1; opt-in adoption from Phase 5)
**Driver**: User suggestion; flexibility beyond fixed `LookbackDays`.

**Decision**: New table `General.ops.ExtractionRangePolicy` lets each table specify multiple date ranges with their own `MaxStaleDays` and `Priority`. Range scheduler picks ranges per pipeline run within time budget.

**Rationale**: Closer to how Netflix Maestro and Uber Hudi schedule their incremental jobs. Lets large tables express "today every 4 hours, last week weekly, last 30 days monthly" without changing pipeline architecture.

**Trade-off accepted**: more configuration surface; `LookbackDays` shorthand on `UdmTablesList` auto-generates a default policy for tables that don't need the flexibility.

---

## D13: Delete detection trust gate via `PipelineExtraction.Status`

**Status**: 🟢 Locked
**Driver**: User feedback (round on large-table deletes); avoid the flapping-source bug by construction.

**Decision**: SCD2 only marks Bronze rows as deleted when:
1. The row's source business date `D` has at least one `Status='SUCCESS'` row in `PipelineExtraction`
2. The most-recent successful snapshot for `D` (in Stage today, in Parquet post-migration) does not contain the PK
3. The verify-before-close source query confirms (existing `cdc/source_verifier.py` defense)

If `PipelineExtraction` for date `D` shows `Status='FAIL'` or no row exists, **delete evaluation is suppressed** and logged to `DeleteEvaluationAudit`.

**Rationale**: User stated: "If the row exists with Status='FAIL' (or doesn't exist at all): the extraction is incomplete or untrusted, the absence of the PK does not imply a delete, and the close is suppressed." This rule completely closes the flapping-source-bug class.

---

## D14: `IsReExtraction` and `ExtractionAttempt` columns on `PipelineExtraction`

**Status**: 🟢 Locked (Phase 1 migration)
**Driver**: User feedback on re-extraction tracking.

**Decision**: Add `IsReExtraction BIT NOT NULL DEFAULT 0` and `ExtractionAttempt INT NOT NULL DEFAULT 1` columns. Pipeline computes server-side at INSERT time via lookup of prior SUCCESS rows for same (TableName, SourceName, DateValue).

**Rationale**: Operator needs to distinguish "first extraction" from "lookback re-extraction" from "operator-triggered backfill." Two columns on existing table cleaner than a new tracking table.

**Small tables exempt**: small tables don't write to `PipelineExtraction` (no `DateValue` concept).

---

## D15: Idempotency mandatory at every layer

**Status**: 🟢 Locked
**Driver**: User constraint: "Idempotency is the most important. Complexity or simplicity don't matter."

**Decision**: Every pipeline step has an explicit idempotency mechanism. Master invariant (see `01_ARCHITECTURE.md` § Idempotency Contract):

> Running the same pipeline batch twice with the same source state produces zero net writes the second time.

**Mechanisms**: deterministic extraction (TRUNC boundaries), deterministic tokenization (vault lookup), deterministic hashing (polars-hash plugin), Parquet stage-check-exchange, idempotency ledger short-circuiting, conditional MERGE on hash inequality, verify-before-close + windowed-scoped + trust-gated delete detection, INSERT-IF-NOT-EXISTS for the registry.

---

## D16: Stage-check-exchange pattern for crash-safe Parquet writes

**Status**: 🟢 Locked (Phase 1)
**Driver**: Agent 3 idempotency research; Airbnb-canonical pattern.

**Decision**: Parquet writes go to `_inflight_*.parquet` first, validate (row count, schema hash), then atomic-rename to final filename + INSERT into registry. Crash mid-write leaves an orphan inflight file (cleaned up by `parquet_verify.py`); never produces a registry row pointing at corrupt data.

---

## D17: Idempotency ledger on every pipeline step

**Status**: 🟢 Locked (Phase 1)
**Driver**: User: "If it ensures idempotency then include it. Complex or not complex does not matter."

**Decision**: `General.ops.IdempotencyLedger` tracks `(BatchId, SourceName, TableName, EventType)` with `Status` ∈ {IN_PROGRESS, COMPLETED, FAILED}. Every pipeline step:
1. INSERT row with `Status='IN_PROGRESS'` — short-circuits if a `COMPLETED` row already exists for the key
2. Execute the step
3. UPDATE row to `Status='COMPLETED'` (or `FAILED` with error message)

UNIQUE constraint on the key prevents concurrent same-batch writes.

**Recovery sweep at startup**: rows stuck `IN_PROGRESS` older than `2 × T_max` are reset to `FAILED` with reason "stale in-progress lock — recovered at startup."

---

## D18: Move verify-before-close + E-12 detection to SCD2 layer

**Status**: 🟢 Locked (Phase 1)
**Driver**: Architectural cleanup — these defenses cannot disappear when Stage layer is removed.

**Decision**: Phase 1 work moves these existing defenses from `cdc/engine.py` into `scd2/engine.py`:
- `cdc/source_verifier.py::verify_deletes_against_source` — called by SCD2 before closing Bronze rows on candidate deletes
- E-12 phantom-update ratio monitoring — emitted as `SCD2_PROMOTION` metadata

**Rationale**: per CLAUDE.md `Do NOT` rules, these defenses cannot be removed. They must be live elsewhere when CDC stops emitting candidate deletes.

---

## D19: 2x daily pipeline cadence

**Status**: 🟢 Locked
**Driver**: User capability statement.

**Decision**: Pipeline runs 2x per day (typical: 06:00 and 18:00 local). Minimum acceptable cadence is 1x daily.

**Rationale**: Halves the maximum gap from a single missed run; runs twice on same source are idempotent (zero extra Bronze writes) so cost of 2x is operationally bounded.

---

## D20: 3-server failover protocol for production outages

**Status**: 🟢 Locked
**Driver**: User confirmation of dev/test/prod servers + system engineer team.

**Decision**: When production pipeline server is unavailable >2 hours, promote test → production via the documented protocol in `05_RUNBOOKS.md`. Dev → test concurrently. Cutback when production is restored.

**Rationale**: Eliminates the multi-day outage risk class. Auditor SLA on data freshness can be met even during hardware failure scenarios.

---

## D21: 5-tier test pyramid

**Status**: 🟢 Locked
**Driver**: Agent 3 idempotency-testing research; user emphasis on idempotency verification.

**Decision**: Test strategy uses five tiers (see `06_TESTING.md`):
- Tier 1: Unit (every commit)
- Tier 2: Property-based with Hypothesis (every commit)
- Tier 3: Integration replay (every PR + nightly)
- Tier 4: Crash injection (pre-release)
- Tier 5: Audit/compliance verification (quarterly)

---

## D22: Hourly gap detector

**Status**: 🟢 Locked (Phase 1)
**Driver**: Need explicit detection of missing extraction dates.

**Decision**: `cdc/gap_detector.py` runs hourly via cron. Detects (source, table, business_date) tuples where `PipelineExtraction` has either no row or only `Status='FAIL'` rows. Auto-enqueues recoverable gaps to `ExtractionRangePolicy` as backfill ranges. Beyond-lookback gaps logged to `ExtractionGapLog` for operator decision.

---

## D23: Snowflake budget alert at 80% of monthly cap

**Status**: 🟢 Locked
**Driver**: $120K/yr cap; user requested cost discipline.

**Decision**: Cost alert at $8K/month (80% of $120K/12). Triggers architecture review before overshoot.

---

## D24: Vault corruption is catastrophic; backup discipline mandatory

**Status**: 🟢 Locked
**Driver**: Tokenization vault is single point of failure for PII recovery.

**Decision**:
- SQL Server Always On Availability Groups across the three servers (or equivalent HA)
- Nightly encrypted vault backup to offsite storage
- Weekly restore-test rehearsal: pick 100 random tokens, restore vault from latest backup to a test instance, assert lookup returns identical plaintext
- Vault row counts monitored in PipelineEventLog daily

---

## D25: ParquetSnapshotRegistry is the canonical Parquet index

**Status**: 🟢 Locked (Phase 1)
**Driver**: Need single source of truth for Parquet file existence/location/tier.

**Decision**: Every Parquet file written has a corresponding row in `General.ops.ParquetSnapshotRegistry`. Registry is queryable for: tier classification, missing-file detection, Snowflake replication status, integrity (checksum) status. UNIQUE constraint on `(SourceName, TableName, BatchId, BusinessDate)`.

---

## D26: PiiVault augmented with append-only provenance tables

**Status**: 🟢 Locked (revised; superseded original UPSERT design)
**Driver**: Auditor traceability + user requirement that history be retained, not overwritten.

**Decision**: Three append-only metadata tables alongside `PiiVault`:

1. **`General.ops.PiiTokenProvenance`** — one row per `(Token, SourceName, ObjectName, ColumnName, FilePath)` on **first observation only**. Immutable once written. Captures the schema-level audit: when did we start collecting this PII column?
2. **`General.ops.PiiTokenizationBatch`** — one row per (BatchId, Source, Object, Column) recording the batch-level tokenization summary (NewTokensGenerated, ExistingTokensReused, TotalRowsTokenized). Append-only.
3. **`General.ops.PiiVault` retention/legal-hold columns**: `Status`, `StatusReason`, `StatusChangedAt`, `LegalHold`, `LegalHoldReason`, `LegalHoldReference`, `RetentionExpiresAt`. Vault rows are never DELETEd; Status changes track lifecycle.

**Why this grain, not per-observation**: per-row observation logging at 3M rows/day × 5 PII cols × 7 years × 2 runs/day = 76B rows for a single table — untenable. The temporal observation history is captured by Bronze SCD2 versions (every row's effective date range tells you when each token was active in source data). The metadata tables capture the **schema-level audit** (when columns started being collected) and the **batch-level audit** (what the pipeline did).

**Rationale**:
- Append-only matches SCD2 thinking: never overwrite history
- Bounded volume: provenance ~250M rows over full vault lifetime, batch-log ~1.3M rows over 7 years
- Auditor queries answerable from the combination: PiiVault (what), PiiTokenProvenance (where), PiiTokenizationBatch (when batches ran), Bronze SCD2 (temporal history)
- CCPA/CPRA right-to-delete supported via vault Status; never DELETE physically

**Supersedes the original D26** which proposed UPSERT with FirstSeen/LastSeen/OccurrenceCount in a single row.

---

## D30: 7-year retention with legal-hold override (CCPA/CPRA/GLBA aligned)

**Status**: 🟢 Locked
**Driver**: California regulatory requirements (CCPA/CPRA), GLBA financial retention obligations, user direction.

**Decision**:
- **Default retention**: PiiVault rows have `RetentionExpiresAt = CreatedAt + 7 years`. Beyond expiry, Status flips to `'purged_for_retention'` via the monthly retention enforcement job.
- **Bronze SCD2 versions**: rows with `UdmEndDateTime < 7 years ago` archived to Parquet cold tier, then purged from Bronze.
- **Parquet snapshots**: retained per the Hot/Warm/Cold tier policy (independent retention story).
- **Legal hold**: `LegalHold = 1` on vault row suppresses retention purge. Reason and reference (ticket/case ID) documented. Used for litigation, regulatory inquiry, GLBA-required retention beyond 7 years.
- **CCPA right-to-deletion**: Status = `'deleted_per_request'` on vault row. Tokens in Bronze become orphan references (effectively forgotten — crypto-shredding equivalent). Bronze rows are NOT physically scrubbed (preserves audit trail). If a legal hold applies, deletion is suppressed and customer is notified of the legal exception per CCPA.
- **CcpaDeletionLog**: append-only audit of every deletion request, action taken, legal exceptions invoked.

**Tools**:
- `tools/enforce_retention.py` — monthly job; flips Status for expired vault rows, triggers Bronze archival
- `tools/process_ccpa_deletion.py` — operator-driven deletion processor
- New runbook: **RB-10: CCPA right-to-deletion request**

---

## D29: AM/PM hot-standby via Automic + SQL Server gate table (revised)

**Status**: 🟢 Locked (revised; supersedes original watchdog VM design)
**Driver**: User direction — Automic is the orchestrator, not cron. Two Automic pipelines (production + test) coordinate via a SQL Server gate table.

**Decision**:
- **Coordination table**: `General.ops.PipelineExecutionGate` with `CycleType ('AM'|'PM')`, `CycleDate`, `Status (PENDING|STARTING|RUNNING|SUCCEEDED|FAILED|TIMEOUT)`, `ExecutingServer`, `BatchId`, `LastHeartbeatAt`. UNIQUE on `(CycleType, CycleDate)`.
- **Automic production pipeline**: scheduled at 02:00 (AM) and 17:00 (PM). Acquires the gate, runs to completion, updates Status.
- **Automic test pipeline (failover)**: scheduled at 04:30 (AM) and 19:30 (PM). 2.5-hour buffer past prod start. Reads gate; runs only if Status indicates prod failed, timed out, or never started.
- **Atomicity**: `sp_getapplock` on `(CycleType, CycleDate)` prevents two failover instances claiming the gate.
- **No external watchdog needed** — Automic does the scheduling, the SQL Server table does the coordination.

**Pipeline duration**: 1-2 hours typical. Silver/Gold downstream jobs run independently after pipeline completion.

**Supersedes the original D29** which proposed a separate watchdog VM; that's no longer needed.

---

## D31: Power BI for log analytics and pipeline dashboards

**Status**: 🟢 Locked
**Driver**: User direction — Power BI is the BI tool, not Grafana.

**Decision**: All log analytics, pipeline dashboards, and data health visualizations are delivered via Power BI connected to SQL Server. This implies:
- Logs MUST land in SQL Server tables (already true: `PipelineEventLog`, `PipelineLog`)
- Logs MUST be structured (mandatory fields: `BatchId`, `SourceName`, `TableName`, `EventType`, `Status`, structured `Metadata` JSON)
- Power BI dataset refresh schedule is independent of pipeline runs
- Dashboards can be embedded in operator portals, executive summary views, audit deliverables

**No Prometheus, no Grafana, no separate monitoring stack** — SQL Server + Power BI is the entirety of the observability tooling.

**See**: `07_LOGGING.md` for the full logging schema and Power BI integration plan.

---

## D32: Phase 7 — Data Health Checks

**Status**: 🟢 Locked (planned for after migration completes)
**Driver**: User direction — health checks deserve dedicated treatment.

**Decision**: A new Phase 7 covers comprehensive data health checks beyond the migration scope:
- **Source health**: row count / schema / null-rate / distribution drift
- **Pipeline health**: throughput trends, SCD2 churn, vault metrics, error rate trends
- **Bronze health**: active-to-total ratio, version velocity, freshness, referential integrity
- **Cross-layer health**: Bronze ↔ Parquet drift, Bronze ↔ Snowflake drift
- **Power BI dashboards**: pipeline overview, table-level deep dive, anomaly detection, executive summary
- **Alerting integration**: per-check thresholds, escalation paths

Phase 7 starts after Phase 6 cleanup is complete. Some of the underlying mechanics (P3-4 reconciliation, B-9 freshness, E-14 active ratio) already exist in CLAUDE.md — Phase 7 unifies them under a single dashboard story.

**See**: `02_PHASES.md` for Phase 7 deliverables; `08_HEALTH_CHECKS.md` (to be created when phase begins) for full design.

---

## D27: Linux cryptographic parity across dev / test / prod

**Status**: 🟢 Locked
**Driver**: User constraint — "All 3 servers must have the same functionality, tools, keys, events." Need cross-server identical setup so failover is seamless.

**Decision**:
- **PII protection stays in the tokenization vault** (D6); not Linux-managed.
- **Credential protection** (vault user passwords, source DB credentials, etc.) uses Linux-native features:
  - GPG-encrypted credential file at `/etc/pipeline/credentials.json.gpg`
  - GPG passphrase sealed to TPM2 on RHEL 9, or stored in kernel keyring (`keyutils`) on RHEL 8
- **Identical setup mandatory across all 3 servers**: same RHEL version, same Python (3.12.11), same library pins, same systemd unit (with `MALLOC_ARENA_MAX=2`), same TPM presence/absence, same GPG keyring, same network drive mount points, same NTP source, same monitoring agents, same cron files (only role differs at runtime).

**New tool**: `tools/verify_server_parity.py` runs at pipeline startup and ad-hoc to compare servers against the parity checklist; treat parity failure as deployment blocker.

**Rationale**: failover (D20, D29) requires the test/dev server to seamlessly become prod. Any drift between servers makes failover risky. Parity verification catches drift before it bites in an outage.

---

## D28: Source DB outages handled by Oracle / SQL Server on-call team

**Status**: 🟢 Locked
**Driver**: User confirmation — Oracle and SQL Server have a dedicated on-call team.

**Decision**: Pipeline runbook scope excludes source-database recovery. We detect source unavailability via `PipelineExtraction.Status='FAIL'`; trust gate suppresses deletes (D13). Source-DB restoration is delegated to the database on-call team. Pipeline auto-recovers on the next run after source is restored.

**Architectural implication**:
- Bronze SQL Server HA (Always On Availability Groups) is owned by the SQL Server team, not the pipeline team
- PiiVault HA same
- Source DB outage MTTR is bounded by the DB team's SLA, not by pipeline-team escalation

---

## D29 (original): AM/PM hot-standby with watchdog VM ⚫ Superseded by D29 (revised) below.

---

## D33: Cooperative cancellation of stuck production runs

**Status**: 🟢 Locked
**Driver**: User direction — when test triggers failover, production should be cancelled rather than left running concurrently.

**Decision**: Production pipeline checks `PipelineExecutionGate.CancellationRequested` at every heartbeat (5 min). Test pipeline sets the flag before claiming the gate; waits up to 15 min for production to acknowledge gracefully. Production self-terminates at the next table boundary (no mid-table interrupts), releases locks, flushes logs, sets gate Status='CANCELLED'.

**New gate columns**:
- `CancellationRequested BIT NOT NULL DEFAULT 0`
- `CancellationRequestedAt DATETIME2(3) NULL`
- `CancellationRequestedBy NVARCHAR(50) NULL`
- `CancellationReason NVARCHAR(MAX) NULL`
- `CancellationAcknowledgedAt DATETIME2(3) NULL`

**Test pipeline behavior on timeout** (production didn't acknowledge within 15 min):
- Log CRITICAL: "Production did not acknowledge cancellation"
- Send alert to operator (manual intervention required)
- Test does NOT proceed automatically — operator decides next action
- Avoids two pipelines running concurrently when production is stuck-but-not-dead

**Why cooperative not forced**:
- No SSH access required (avoids security surface)
- Clean shutdown preserves logs and lock release
- Stuck-but-running is rare; operator awareness is the right outcome

**See runbook**: RB-9 in `05_RUNBOOKS.md` for the full cancellation flow.

---

## D34: No legacy migration — initial deployment

**Status**: 🟢 Locked
**Driver**: User confirmation — no SQL Server tables exist yet.

**Decision**:
- All migration scripts are `CREATE TABLE` from scratch (no `ALTER TABLE`)
- Phase 6 (legacy cleanup) is removed; phases renumber so Health Checks becomes Phase 6
- Phase 4 transforms from "cohort cutover" to "per-table enablement" — first deployment per table, no legacy state to migrate
- Cutover protocols in earlier doc revisions are obsolete; the runbook for first-time table enablement replaces them

**Rationale**: pipeline codebase exists (per CLAUDE.md) but production deployment is greenfield. Avoids the riskiest class of migration work and saves ~2 months of effort.

**See**: `02_PHASES.md` Phase 4 (revised) and Phase 6 (renumbered).

---

## D35: Deep dive sequence — Round 1 (Database Schema) first

**Status**: 🟢 Locked
**Driver**: User direction — start deep dive with Round 1 (Database Schema) since all other Phase 1 work depends on it.

**Decision**: Phase 1 deep dive proceeds in six rounds (per `PHASE_1_DEEP_DIVE_PLAN.md`). Round 1 is Database Schema. Subsequent rounds in order: Configuration, Core Modules, Tools, Tests, Deployment.

**Resumability**: `CURRENT_STATE.md` at the migration directory root captures the current planning position. If a session is interrupted, that file plus this decision identify where to pick up.

**Rationale**: DDL is unambiguous and reviewable; DBA review is the gating dependency for all Phase 1 work; getting it scheduled early de-risks Phase 0 sign-off; subsequent rounds (modules, tools, tests) all depend on the schema being final.

---

## D36: Per-phase narrative documentation

**Status**: 🟢 Locked
**Driver**: User direction — need documentation explaining why each phase exists, with audience-specific views.

**Decision**: Each phase has a `docs/migration/phaseN/00_phase_overview.md` with sections for:
- Purpose & rationale (why this phase exists)
- For engineers (technical scope, key decisions, anti-patterns)
- For management (timeline, cost, risk, business value)
- For auditors (audit posture this phase establishes)
- For operators (day-to-day changes)
- Visuals (Mermaid diagrams)
- Round-by-round outline (quick links to deep-dive artifacts)

The Phase 1 narrative is created as the template for other phases.

---

## D37: Visuals via Mermaid in source-controlled markdown

**Status**: 🟢 Locked
**Driver**: User direction — visuals help when shared understanding is lacking. Specific example: "CDC append" vs "snapshot data" confusion.

**Decision**: All architecture and process visuals authored as Mermaid diagrams embedded in markdown files. Renders in GitHub, VS Code, Power BI documentation, most modern viewers. Source-controlled with the rest of the docs.

`09_VISUALS.md` consolidates the key system-level diagrams; per-phase docs include phase-specific diagrams.

**The "CDC append vs snapshot" clarification**: what we are building is **snapshot data**, not traditional CDC append. Traditional CDC emits change events (insert/update/delete records) per source mutation. Our pipeline captures **state observations** at extraction time and infers changes via SCD2 hash compare downstream. This distinction is clarified visually in `09_VISUALS.md`.

---

## D38: Phase 6 expanded to "Health, Lineage & Catalog"

**Status**: 🟢 Locked
**Driver**: User question about missing topics from a data engineering perspective.

**Decision**: Phase 6 expands from "Data Health Checks" to "Health, Lineage & Catalog" with three sub-areas:
- Health checks (existing scope)
- Data lineage tracking (audit-grade row-level lineage source → Bronze → Snowflake)
- Data catalog publication (discoverability for analytics consumers)

No new phases added; scope absorbed into existing Phase 6.

---

## D39: Silver/Gold layer scoping — out of scope (Option 1)

**Status**: 🟢 Locked
**Driver**: User direction — Silver/Gold are owned by other teams whose complexity is outside this pipeline's responsibility.

**Decision**: Pipeline team's responsibility ends at Bronze SCD2 + Snowflake mirror. Silver and Gold layers are entirely out of scope. **No consumption contract document is published; no Phase 7 added.** Other teams build their own consumption pattern against Bronze on their schedule.

**Implication for Phase 6**: the third sub-area (originally "data catalog") is reframed as **Alation integration via the existing data governance team** (D43). Pipeline team publishes metadata; data governance team owns the catalog itself.

---

## D40: Schema evolution governance — formal process in Phase 1

**Status**: 🟢 Locked
**Driver**: Identified gap — `evolve_schema()` handles automatic column adds but human-in-the-loop process for breaking changes is undefined.

**Decision**: Phase 1 gains Round 7 (Schema Evolution Governance) covering:
- Automatic-add scope (existing P0-2 behavior)
- Operator-decision scope (column removals — current WARNING; type changes — current ERROR)
- Source schema change notification protocol (DB on-call team → pipeline team)
- Schema contract document per source
- Quarterly schema review meeting cadence
- Tooling: `tools/schema_diff_report.py` to summarize changes per quarter

---

## D41: Source schema contracts — ⚫ Superseded

**Status**: ⚫ Superseded by D40 (internal schema evolution governance)
**Driver**: User correction — schemas are controlled internally by the team, not by external sources requiring contracts.

**Decision (superseded)**: original plan was to draft source schema contracts with the DB on-call team. Removed because the team controls source schemas internally; D40 (schema evolution governance) covers the internal change-control process sufficiently.

**Phase 0 deliverable 0.16** (originally source schema contracts) is **removed**.

---

## D42: Capacity planning baseline in Phase 0

**Status**: 🟢 Locked
**Driver**: Identified gap — no projection of row count growth, table size, etc.

**Decision**: Phase 0 adds deliverable 0.17 (capacity baseline). For top 10 tables, document:
- Current row count
- Daily growth rate
- 12-month projected row count
- 7-year projected storage (Bronze, Parquet, Snowflake)
- Threshold for "consider scaling action" alerts

---

## D43: Alation integration via existing data governance team

**Status**: 🟡 Proposed (awaiting Phase 0 engagement with data governance team)
**Driver**: User direction — data catalog is owned by Alation and an existing data governance team.

**Decision**: Phase 6 third sub-area is **Alation integration**, not "build a catalog." Pipeline team publishes metadata to Alation; data governance team owns the catalog and consumer-facing experience. Specifically:

- **Phase 0 deliverable 0.18**: engage data governance team; scope what metadata the pipeline should publish to Alation (table schemas, lineage, PII column flags, retention status, freshness)
- **Phase 6 deliverable**: implement metadata publishing — likely via Alation's REST API or a scheduled export from `General.ops` tables
- **Coordination cadence**: quarterly sync with data governance team for catalog freshness review

**Open**: exact metadata payload TBD with data governance team in Phase 0.

---

## D44: DR drill expansion to include data center loss

**Status**: 🟢 Locked
**Driver**: User direction — DR rehearsal should include full data center loss scenario.

**Decision**: RB-7 (quarterly DR rehearsal) expanded to alternate between two scenarios:
- **Q1 + Q3**: server-failover rehearsal (existing scope) — production server unavailable, promote test
- **Q2 + Q4**: data center loss simulation — primary site unavailable, recover from offsite Parquet archive into a different SQL Server instance, then reconstruct Bronze via RB-8 (Bronze rebuild from Parquet)

**Implications**:
- Need offsite Parquet replication (a copy of Hot Parquet outside the primary network drive). Could be: (a) cloud archive storage, (b) secondary network drive at a separate site, (c) Snowflake stage as DR target once Phase 5 is live
- Phase 4 deliverable: identify offsite Parquet replication target and validate the recovery path
- Phase 4 acceptance criterion: one DC-loss tabletop exercise completed

**Recovery path for DC loss** documented in `05_RUNBOOKS.md` RB-7 (expanded) and RB-8 (Bronze rebuild from Parquet).

---

## D45: Phase 1 Round 1 (Database Schema) deep dive begun

**Status**: 🟡 In progress
**Driver**: User direction — start Round 1 per D35.

**Decision**: Round 1 deliverable `docs/migration/phase1/01_database_schema.md` is the comprehensive database schema spec covering all 23 tables in `General.ops`, supporting indexes, ~10 stored procedures, edge case mapping, storage forecast, and DBA review checklist.

**Round 1 sub-decisions (locked during this round)**:

- **D45.1**: `General.ops` is a new schema within the existing `General` database (alongside `dbo`). Schema owner: pipeline service principal.
- **D45.2**: All bigint primary keys are `BIGINT IDENTITY(1,1)`; rowstore for tables with targeted updates, partitioned columnstore for append-only high-volume tables (PipelineLog, PiiTokenProvenance).
- **D45.3**: Single sequence object `General.ops.PipelineBatchSequence` is the source of truth for `BatchId` values across all tables.
- **D45.4**: All datetime columns use `DATETIME2(3)` (millisecond precision) per BCP CSV contract and SCD2-P1-f invariant.
- **D45.5**: All hash columns use `VARCHAR(64)` (full SHA-256 hex string) per B-1.
- **D45.6** (v3, validation-driven): Audit tables have no DELETE permission granted to any role; rows are append-only forever. **PiiVault is the most-protected table**: rows are NEVER physically DELETEd. Retention, CCPA right-to-deletion, and legal hold release flip the `Status` column instead (`active` → `deleted_per_request` | `purged_for_retention` | `legal_hold_only`). The Status-flip pattern interacts with the `UX_PiiVault_Lookup` filtered unique index (`WHERE Status = 'active'`) — together they preserve audit history while allowing fresh active rows for re-tokenization of plaintexts whose prior vault row was deleted/purged. Audit tables with DELETE denied at role level: `PiiVault`, `PiiVaultAccessLog`, `CcpaDeletionLog`, `ManualCorrectionLog`, `PiiTokenProvenance`, `PiiTokenizationBatch`, `OrphanedTokenLog`, `SchemaContract`, `DeleteEvaluationAudit`, `ExtractionGapLog`, `ReconciliationLog`, `SCD2RepairLog`, `TableEnablementLog`.
- **D45.7**: TDE (Transparent Data Encryption) enabled at database level for `General` (deployment requirement, not in CREATE TABLE).
- **D45.8**: Stored procedures use SCHEMABINDING where possible to prevent accidental schema drift breaking the procedure.

**Status when complete**: locks Round 1; advances to Round 2 (Configuration).

**See**: `docs/migration/phase1/01_database_schema.md` for the full spec.

---

## D46: Claude skill / plugin evaluation

**Status**: 🟡 Proposed (awaiting open-source approval results)
**Driver**: User direction — research Claude skills that could accelerate planning + development.

**Decision (proposed)**:

| Skill | Status | Rationale |
|---|---|---|
| **Superpowers** (github.com/obra/superpowers) | 🟡 Proposed (pending OSS approval) | Planning module decomposes Phase rounds into 2-5 minute tasks; TDD module aligns with `06_TESTING.md`'s tier pyramid |
| **Senior Data Engineer skill** (alirezarezvani/claude-skills) | 🟡 Proposed (pending OSS approval) | Inline CDC/SCD2/Polars validation; reduces dependency on multi-round Agent research |
| **ADR (Architecture Decision Records) skill** | ⚫ Skipped | Substantial overlap with existing `03_DECISIONS.md`; our D-numbered status-flagged log already implements ADR conventions |
| **Audit Trail skill** | ⚫ Skipped | Substantial overlap with `03_DECISIONS.md` + `PipelineEventLog` + `IdempotencyLedger` |
| **Python Test Auditor** | 🟡 Deferred | Useful starting Phase 1 Round 5; premature now |
| **Database Designer** | ⚫ Skipped | Round 1 DDL already complete |
| **Trail of Bits Security skills** | ⚫ Skipped | `/security-review` built-in is sufficient |
| **`/review`, `/security-review`, `/init`** (built-in) | 🟢 Use as-is | Already in stock Claude Code; invoke during Phase 1 Round 3+ |
| **`anthropic-skills:consolidate-memory`** (already approved) | 🟢 Use as-is | Periodic doc/memory cleanup |

**Open-source policy gate**: per the user's "very strict on open source" constraint, third-party skills (Superpowers, Senior Data Engineer, Test Auditor) require security/compliance approval before adoption. Recommendation: get Superpowers through approval first (most widely adopted, lowest risk profile) to validate the approval pipeline; defer others until that lands.

**Re-evaluate**: when entering Phase 1 Round 5 (Test Auditor) and at start of each subsequent phase.

**See**: `MAINTENANCE.md` § "Development Tooling" for installation and usage details.

---

## D47: Round 0.5 — pre-locking integration spike

**Status**: 🟢 Locked (authorized by user; awaiting engineer assignment + dev environment access)
**Driver**: Reflection agent finding (`ROUND_1_REVIEW.md`) — plan is over-specified vs zero code execution; combinations of D6/D16/D29 have not been validated with running code.

**Decision (proposed)**: Insert a 1-week throwaway spike between Phase 0 and Phase 1 Round 3 that exercises three high-risk integration points:

1. **Parquet stage-check-exchange** (D16) — Polars write to `_inflight_*.parquet`, validate, atomic-rename, register
2. **Vault GET-OR-CREATE under concurrency** (D6) — 4 simultaneous processes calling SP-1 with same plaintext; verify exactly one row created
3. **Automic gate-table acquire flow** (D29) — simulate prod failure mid-run, confirm test pipeline acquires gate cleanly with sp_getapplock

Code is throwaway. Run on dev only. Output: confirmation each integration works as specified, OR a punch list of small adjustments to D6/D16/D29 before locking Round 3 module designs.

**Rationale**: validate decision combinations before they're locked; reduce cost of inevitable correction during Phase 2 pilot.

**Effort**: ~1 week with 1 engineer. Parallel-able with Round 1 v2 work.

**Authorization**: user said "I'm fine with proceeding with your recommended approach on objectives" — D47 authorized, awaiting only the engineer + dev environment access to execute. Status flips to 🟢 to reflect the authorization (executing the spike is a separate event tracked in `phase1/03_round_0_5_FINDINGS.md` once it runs).

---

## D48: Project-local Claude skills authored

**Status**: 🟢 Locked
**Driver**: User direction to gather/implement skills; combined with OSS approval gate on third-party skills.

**Decision**: Authored five project-local skills under `.claude/skills/` rather than installing third-party Superpowers content:

| Skill | Purpose |
|---|---|
| `udm-planning` | Round task decomposition with verification |
| `udm-brainstorm` | Force ≥3 alternatives before locking |
| `udm-edge-case-validator` | M/S/I/N/P/G/D/F/V series check |
| `udm-decision-recorder` | D-number / status / rationale enforcement |
| `udm-runbook-author` | Runbook structure enforcement |
| `udm-data-engineer-review` | CDC/SCD2/Polars/Parquet pattern review |

Skills are markdown SKILL.md files with frontmatter, version-controlled with the repo, no external dependencies. If third-party Superpowers is approved later, it supplements (does not replace) these.

**See**: `SKILLS_PLAN.md` for usage.

---

## D49: Round 1 v2 → v3 iteration (validation-driven, locked after second-pass)

**Status**: 🟢 Locked (after second-pass validation 2026-05-09)
**Driver**: Reflection agent findings — Round 1 schema doc had 8 specific issues including 🔴 SP-1 concurrency bug, 🔴 partition time-bomb, 🔴 PiiTokenizationBatch idempotency gap.

**Decision**: All 8 issues resolved in v2 of `phase1/01_database_schema.md`:
- ✅ SP-1 rewritten with UPDLOCK + HOLDLOCK + try/catch on UNIQUE violation (atomic GET-OR-CREATE)
- ✅ SP-3 through SP-6 bodies fully inlined (gate acquisition, cancellation request/acknowledgment)
- ✅ SP-11 added: `PipelineLog_ExtendPartition` + SQL Agent job DDL (resolves partition time-bomb)
- ✅ PiiTokenizationBatch UNIQUE constraint added: `UX_PiiTokenizationBatch_Identity` on (BatchId, SourceName, ObjectName, ColumnName)
- ✅ SchemaContract table added (table 23) for D40 schema evolution governance
- ✅ OrphanedTokenLog table added (table 24) for P2 mitigation with FK to vault
- ✅ EncryptionVersion column added to PiiVault (D7 future-proof)
- ✅ PiiVaultAccessLog FK to PiiVault added; OrphanedTokenLog FK to PiiVault added
- ✅ D45.6 precision updated to clarify: PiiVault uses Status flip pattern, never physical DELETE
- ✅ Doc changelog appended; open items list updated (✅ resolved vs 🟡 still-open)

**Edge case mapping updated**: I3 (vault concurrency, tokenization batch idempotency) and P2 (orphan log) now have explicit mappings.

**Storage forecast updated**: +5 MB (SchemaContract) + 25 MB (OrphanedTokenLog).

**DBA checklist updated**: 8 v2-specific items added (TDE, partition job, FK confirmations, EncryptionVersion default, etc.).

**Status flip (corrected via udm-checks-and-balances discipline)**: 

Initial v2 was prematurely declared 🟢. The validation agent (per `CHECKS_AND_BALANCES.md`) ran the 5 gates and found 3 🔴 blockers + 7 🟡 follow-ups:

- 🔴 1: SP-1 lookup with `Status='active'` filter against unfiltered UNIQUE index — would THROW on re-tokenization of any plaintext whose vault row was CCPA-deleted or retention-purged. **Fixed in v3**: UX_PiiVault_Lookup made filtered (`WHERE Status='active'`); historical lookups served by IX_PiiVault_HistoricalLookup.
- 🔴 2: D45.6 in `03_DECISIONS.md` did not actually reflect the v2 expansion claimed in the schema doc body. **Fixed in v3**: D45.6 entry updated.
- 🔴 3: `04_EDGE_CASES.md` P2 still 🔴 despite the schema doc claiming OrphanedTokenLog mitigates it. **Fixed in v3**: P2 flipped to 🟡 (mitigation in place, SP wiring pending). I3 entries also widened to cover the three facets (ledger, vault, tokenization batch).

🟡 follow-ups deferred (tracked in `_validation_log.md` and CURRENT_STATE.md):
- SP-3 BatchId-waste path
- SQL Agent job DDL missing `@freq_recurrence_factor`, `@owner_login_name`
- SchemaContract: missing self-FK, CHECK on date range, filtered-UNIQUE on active contracts
- OrphanedTokenLog: SP-10 extension and CCPA deletion SP not yet authored
- `phase1/00_phase_overview.md` Round 7 narrative needs SchemaContract moved-to-v2 update
- SCHEMABINDING inconsistency across SPs

**Final status**: D49 🟡 → 🟢 Locked after second-pass validation (2026-05-09) returned ALL ✅. Schema v3 ready for DBA review. 7 🟡 follow-ups tracked in CURRENT_STATE.md and `_validation_log.md` for incremental fixing. Round 2 (Configuration) drafting can now begin in parallel with DBA review.

**Validation trail**:
- First-pass (2026-05-09): 3 🔴 found in v2 → v3 fixes applied
- Second-pass (2026-05-09): all ✅, no new 🔴, fixes confirmed solid
- Both pass entries in `_validation_log.md`

**Discipline lesson**: artifact production ≠ validation; first-pass validation alone insufficient — fixes need second-pass to confirm they work and don't introduce new bugs (D56). The 🟢 lock here is gated on the second-pass entry, per D55 + D56.

---

## D50: Obsidian as optional documentation navigation layer

**Status**: 🟢 Locked (additive; opt-in)
**Driver**: User direction to research and integrate Obsidian for the planning phase.

**Decision**: `docs/migration/` can be opened as an Obsidian vault directly with zero file changes. Mermaid renders out of the box. Bidirectional wiki-links, Dataview, and Templater are available via plugins (gated on OSS approval per D46).

**Phased adoption** (see `OBSIDIAN_GUIDE.md` for details):
- **Phase 1**: open as vault, install plugins (Dataview, Templater, Smart Connections, Excalidraw, Frontmatter Links, Claude Code MCP)
- **Phase 2**: create `_templates/` for new decisions / edge cases / runbooks (✅ done — three templates committed)
- **Phase 3**: split monolith files (`03_DECISIONS.md`, `04_EDGE_CASES.md`, `05_RUNBOOKS.md`) into per-entity files with YAML frontmatter — **deferred until concrete need surfaces**
- **Phase 4**: Dataview dashboards — depends on Phase 3
- **Phase 5**: Claude Code MCP plugin for IDE-style integration

**Rationale**: zero-effort baseline (Phase 1 = open folder); high-value queries (Dataview) gated on a one-time scripted split. Stops short of mandatory adoption — the team can stay in VS Code if they prefer.

**Trade-offs accepted**:
- Obsidian-flavored Markdown (wiki-links, Dataview blocks) doesn't render on GitHub
- Commercial license required (~$50/user/year) for paid team use
- Plugin breakage risk on Obsidian core upgrades

**Reversibility**: fully reversible. Plugins are uninstallable; templates are pure markdown.

---

## D51: Project-local Claude Code subagents (udm-design-reviewer, udm-test-author)

**Status**: 🟢 Locked
**Driver**: User direction to research multi-agent setup; reflection agent identified bugs that a design reviewer would have caught.

**Decision**: Two project-scoped subagents authored under `.claude/agents/`:

1. **`udm-design-reviewer`** — reviews architectural changes, CDC/SCD2 logic, schema evolution, edge case coverage. Reads `CLAUDE.md`, `docs/migration/01_ARCHITECTURE.md`, `03_DECISIONS.md`, `04_EDGE_CASES.md` before each review. Categorized output (✅ / 🟡 / 🔴 / ⚪) with edge case ID and decision number citations.

2. **`udm-test-author`** — authors Tier 1 (unit), Tier 2 (property-based), and Tier 3 (integration) tests. References `06_TESTING.md` for tier patterns and `04_EDGE_CASES.md` for required edge case coverage. Output structured per file with edge case IDs in docstrings.

**Anti-patterns documented**: per `MULTI_AGENT_GUIDE.md` — empty descriptions, over-constraining tools, bloated agents (>4-5 specialists), agent loops (subagents can't nest), trivial-task delegation.

**See**: `MULTI_AGENT_GUIDE.md` for the complete pattern catalog.

---

## D52: Permission mode set to `bypassPermissions` in settings.local.json

**Status**: 🟢 Locked (per user direction)
**Driver**: User direction to disable permission popups and enable dangerously-skip-permissions.

**Decision**: `.claude/settings.local.json` has `permissions.defaultMode: "bypassPermissions"`. This disables most permission prompts within the existing session. The `--dangerously-skip-permissions` CLI flag provides equivalent behavior at process start.

**Risk acknowledgment**: per security agent research, `bypassPermissions` mode disables safety guards and overrides protected paths. Real-world incidents include `rm -rf /` from prompt-injection or misconstrued instructions.

**Mitigations**:
- Explicit `permissions.deny` list still blocks: `.env`, `*.key`, `*.pem`, `vault/**`, `secrets.json`, `credentials.json*`, `Bash(rm -rf /*)`, `Bash(rm -rf ~/*)`, `Bash(curl * | sh)`, `Bash(wget * | sh)`
- `.claudeignore` documents the same intent in human-readable form (community claude-ignore hook can enforce, if installed)
- Operating environment is a personal Test_Repo on a development machine — not a production system with PII or financial data

**For production environments**: this decision should NOT propagate. Production servers require the strict permission model with explicit allowlists.

**Reversibility**: fully reversible. Change `defaultMode` to `default` to restore prompts.

---

## D53: `.claudeignore` and security baseline

**Status**: 🟢 Locked
**Driver**: User direction to research and add Claude ignore file with security considerations.

**Decision**: Two artifacts at the project root:

1. **`.claudeignore`** — documents the intent in `.gitignore`-style syntax. **Note**: `.claudeignore` is NOT officially supported by Claude Code (as of May 2026). The file is for human reference + the community claude-ignore hook (github.com/li-zhixin/claude-ignore) if/when installed.

2. **`.claude/settings.local.json` `permissions.deny` list** — actually enforced by Claude Code. Mirrors the critical entries from `.claudeignore`.

**Patterns ignored / denied**:
- Credentials: `.env`, `.env.*`, `secrets.json`, `credentials.json*`, `*.pem`, `*.key`, `*.ppk`, `*.crt`, `*.p12`, `*.pfx`
- PII vault: `vault/**`, `*.vault.encrypted`, `PiiVault*.backup`
- Logs (PII risk): `logs/`, `*.log`, `audit_logs/`, `PipelineLog.export.*`, `PiiVaultAccessLog.export.*`
- Production: `production_config/`, `prod/`, `terraform/production/`
- Build / IDE: `node_modules/`, `__pycache__/`, `.vscode/`, `.idea/`, `dist/`, `build/`, `.venv/`
- OS: `Thumbs.db`, `.DS_Store`, `desktop.ini`
- Dangerous Bash: `rm -rf /*`, `rm -rf ~/*`, `curl * | sh`, `wget * | sh`

**See**: `.claudeignore` (project root) and `.claude/settings.local.json`.

**Reversibility**: fully reversible.

---

## D54: PreToolUse / PostToolUse hooks (deferred)

**Status**: 🔴 Deferred
**Driver**: Security agent research recommended hooks for additional safety; user direction did not explicitly request hooks.

**Decision**: Hooks are NOT installed in Phase 1. Rationale:
- The permission `deny` list provides primary protection
- Hooks add operational complexity (script files in `.claude/hooks/`, cross-platform shell incompatibility on Windows + Linux)
- We have only 5 project skills + 2 agents; adding hooks now is premature optimization

**Trigger to revisit**: when production-class data starts flowing through the development environment, or when an incident demonstrates the permission deny list isn't sufficient.

**See**: security agent research output for hook examples (PreToolUse on `Read(.env*)`, PostToolUse on `Edit(schema/*.sql)`).

---

## D55: Checks-and-balances validation discipline (mandatory)

**Status**: 🟢 Locked
**Driver**: User direction — flagged that artifacts were being produced and immediately marked complete without independent validation. Reflection agent found 8 critical bugs in v1 that pure-production discipline missed; new validation agent found 3 more 🔴 blockers in v2 that should not have shipped to DBA review.

**Decision**: Every significant artifact (decision flip, runbook addition, schema doc update, round acceptance, phase deliverable) must pass the 5-gate udm-checks-and-balances discipline before being declared complete.

The 5 gates:
1. **Cross-reference** — verify consistency with rest of doc set (decisions, edge cases, runbooks)
2. **Quality assurance** — independent review (separate agent or human, not the producer)
3. **Edge case enumeration** — walk M/S/I/N/P/G/D/F/V series; flag gaps and new cases
4. **Edge case validation** — every "addressed" case has tangible verification (test, constraint, runbook step)
5. **Idempotency / regression** — D15 invariant preserved; no previously-validated work broken

**Mandatory artifacts**:
- `.claude/skills/udm-checks-and-balances/SKILL.md` — orchestration skill
- `docs/migration/CHECKS_AND_BALANCES.md` — discipline doc with examples
- `docs/migration/_validation_log.md` — append-only audit trail; required entry for every 🟢 status flip

**Status semantics** (clarified):
- 🟡 Proposed = artifact exists, validation NOT performed
- 🟢 Locked = validation gates ALL ✅, log entry written
- 🟡 Validated-with-followups = gates ✅ but 🟡 items tracked in CURRENT_STATE
- 🔴 Blocked = validation found 🔴; must fix before lock
- ⚫ Superseded = replaced by newer artifact

**Hard rule**: 🟢 Locked WITHOUT a `_validation_log.md` entry is a status mismatch and must be corrected.

**Trade-off accepted**: validation adds time per change. The reflection agent and validation agent saved 11+ critical bugs from shipping to DBA review — the time cost is dramatically less than the cost of those bugs landing in production.

**See**: `CHECKS_AND_BALANCES.md` for the complete discipline.

**This decision validates itself**: by being added to the decision log with this rationale, citing specific artifacts and the validation log entries that motivated it.

---

## D56: Second-pass validation mandatory after fix application

**Status**: 🟢 Locked
**Driver**: First-pass validation agent caught 3 🔴 in v2 of `phase1/01_database_schema.md`. Without a second-pass after the fixes were applied, we'd have repeated the same anti-pattern: produce-fix → declare-complete. The user direction made this explicit: "Add this decision for a second-pass validation as part of our overall process and ensure that the process is followed."

**Decision**: Every artifact that triggers a 🔴 in first-pass validation MUST receive a second-pass validation by an INDEPENDENT agent before any status flip to 🟢 Locked. The second-pass:

1. Confirms the 🔴 fixes work as specified
2. Verifies no NEW 🔴 introduced by the fixes
3. Verifies no regression of previously-validated work
4. Walks all 5 gates fresh — not just the gates that originally failed

**Why a separate decision from D55**: D55 establishes the 5-gate discipline. D56 establishes the iteration discipline — that fixes need their own validation, not just a "yes I addressed the issue" claim. Pattern: produce → first-pass validate → fix → second-pass validate → record → lock.

**Independence requirement**: the second-pass agent must be a DIFFERENT agent than the first-pass. Same producer / first-pass / second-pass = no validation. Independent reviewers catch what self-review and even single-reviewer rounds miss.

**Mandatory artifacts**:
- Append-only entry in `_validation_log.md` for both first-pass AND second-pass passes
- Cross-reference between the entries (second-pass cites first-pass agentId or date)
- Status flip 🟡 → 🟢 only after second-pass returns clean ALL ✅ or ✅-with-acceptable-🟡

**Exemption — when second-pass not required**:
- First-pass returned ALL ✅ with no 🔴 (only 🟡 follow-ups) — second-pass optional but recommended
- Trivial edits (typo fixes, formatting, editorial re-org)
- Doc-only changes that don't introduce new behavior, constraints, or decisions

**Trade-off accepted**: second-pass adds ~30 minutes per significant artifact. Given the first-pass on v2 caught 3 production-blocking bugs, the cost is justified — and the second-pass on v3 confirmed no regressions, providing a clean lock signal.

**This decision validates itself**: the second-pass agent that ran on v3 confirmed v3 is ready for DBA review. First validation log entry recorded both passes. Discipline now operational.

**See**: `CHECKS_AND_BALANCES.md` § "Second-pass validation"; `_validation_log.md` for the v3 second-pass entry; D49 flip to 🟢 gated on this round.

---

## D57: PM-mindset adoption (HANDOFF, NORTH_STAR, BACKLOG, RISKS)

**Status**: 🟢 Locked (after three-pass validation cycle: first-pass + second-pass + third-pass per D55/D56; see `_validation_log.md` 2026-05-09 PM artifacts entry)
**Driver**: User direction — research project-management patterns and integrate into the project; Task Master research surfaced gaps where existing planning docs were missing PM discipline (continuity, conflict resolution, risk visibility).

**Decision**: Four PM-discipline files added to `docs/migration/`:

1. **`HANDOFF.md`** — continuity-oriented onboarding doc; "how to take over" (vs `CURRENT_STATE.md` which is "where we are right now"). Read order, locked vs in-flight, validation non-negotiables, stakeholder map, pitfalls, escalation.
2. **`NORTH_STAR.md`** — single conflict-resolution rubric: "audit-grade traceability for every Bronze row, deployable, idempotent, operationally stable — at a Snowflake spend ceiling of $120K/year." Five pillars, per-phase contribution map, agent prompt anchor.
3. **`BACKLOG.md`** — WSJF-prioritized 🟡 follow-ups (currently scattered across validation log, CURRENT_STATE, TODO mentions in CLAUDE.md). 14 initial items B01-B14 with COD/JS scoring.
4. **`RISKS.md`** — lightweight risk register; 15 active delivery risks (R01-R15) with likelihood × impact scoring, owners, mitigations. Distinct from `04_EDGE_CASES.md` (technical correctness vs delivery risk).

**Rationale per research**:
- Skip PRD.md (00_OVERVIEW + 02_PHASES already cover)
- Skip ROADMAP.md (02_PHASES is the roadmap)
- Skip CHANGELOG.md (validation log + locked decisions are the changelog)
- Adopt these four because they fill gaps: continuity (HANDOFF), conflict resolution (NORTH_STAR), backlog visibility (BACKLOG), delivery-risk surface (RISKS).

**Trade-offs accepted**: 4 more files in the doc set (~13 → 17 + per-phase). Maintenance overhead bounded — quarterly review per `MAINTENANCE.md`.

**See**: `HANDOFF.md`, `NORTH_STAR.md`, `BACKLOG.md`, `RISKS.md`.

---

## D58: udm-researcher subagent (proactive + on-demand)

**Status**: 🟢 Locked (after three-pass validation cycle; see `_validation_log.md` 2026-05-09 PM artifacts entry)
**Driver**: User direction — "include a research agent that can trigger as needed or on its own to help support different phases."

**Decision**: New project-scoped subagent at `.claude/agents/udm-researcher.md`:

- **Tools**: Read, Grep, Glob, Write, WebSearch, WebFetch (Write scoped to `_research/` directory by **convention** — agent body explicitly instructs no edits to primary docs; not enforced by tool restriction since hard restriction would prevent the agent from creating its own output files)
- **Model**: sonnet
- **Trigger pattern**: BOTH proactive (description includes "use PROACTIVELY when...") AND on-demand (@udm-researcher invocation)
- **Output convention**: writes findings to `docs/migration/_research/<topic-slug>-<YYYY-MM-DD>.md`; never edits primary docs (preserves D55/D56 producer ≠ reviewer pattern)
- **Anchor**: every research run reads NORTH_STAR.md first; findings tied to the five pillars
- **Composition**: Validation Gate 2 may auto-invoke researcher when finding unsupported claims; researcher findings cited by `udm-decision-recorder` when adding D-numbers

**Proactive triggers** (description phrases the main agent recognizes):
- Phase plan references external standard without citation
- New edge case mitigation lacks primary source
- Decision cites benchmark without link
- Validation discovers unsupported claim
- New phase begins (research current best practices)
- User asks "is this industry-standard?" / "what's best practice for X?"

**Anti-pattern explicitly avoided**: researcher does NOT edit `03_DECISIONS.md`, schema docs, runbooks, or edge case register. It produces research artifacts in `_research/`; producer agents (or the user) incorporate findings via the standard validation discipline.

**See**: `.claude/agents/udm-researcher.md` for full agent body; `MULTI_AGENT_GUIDE.md` for orchestration patterns; `_research/` for output directory.

---

## D59: Task Master MCP server — explicitly skipped

**Status**: ⚫ Skipped (with reasoning)
**Driver**: User direction to research Task Master and integrate ideas; research found substantial overlap with existing docs.

**Decision**: Do NOT install [eyaltoledano/claude-task-master](https://github.com/eyaltoledano/claude-task-master) MCP server.

**Rationale**:

1. **80% functional overlap** with existing `02_PHASES.md` + `PHASE_1_DEEP_DIVE_PLAN.md` + per-phase docs — both decompose work into structured tasks with dependencies and complexity
2. **Conflicts with validation discipline** — Task Master's `set_task_status` is single-actor flip; D55/D56 require producer ≠ first-pass ≠ second-pass roles per status flip; wiring D55 into TM is more work than the tool saves
3. **Assumes greenfield decomposition** — TM's value is initial PRD-to-tasks; we're at Phase 1 Round 1 v3, well past that stage
4. **Output format less auditable** — TM produces JSON tasks; our D-numbered status-flagged decisions are more audit-grade and align with regulatory traceability requirements

**When to revisit**: if a *new sub-project* with greenfield decomposition emerges (e.g., Phase 5 Snowflake mirror migration), TM could do the first cut for that. Until then, existing phase docs win.

**Alternative considered**: [Backlog.md MCP server](https://github.com/MrLesk/Backlog.md) — markdown-native task files with CLI. **Deferred** — current `BACKLOG.md` is hand-maintained at 14 items; revisit if backlog grows past ~30 items.

---

## D60: Round close-out protocol; HANDOFF as living per-round artifact

**Status**: 🟢 Locked
**Driver**: User direction — "Did we integrate HANDOFF or another system so that our agents can keep track of the work made at each round? After each round HANDOFF file should be updated and related skills or techniques should understand how to work with the HANDOFF system."

**Honest answer to the user's question**: Before this decision, NO. HANDOFF.md was created in D57 as a one-time onboarding doc and was never updated per round. CURRENT_STATE.md was the de-facto living doc. This was a discipline gap.

**Decision**: Establish a round close-out protocol that:

1. **Promotes HANDOFF.md to a living per-round artifact**. New §11 "Round history" appends one row per round during close-out. §3 "Locked vs in-flight", §5 "Active risks", §7 "Skills and subagents", §8 "Pitfalls", and §13 "Last updated" are touched as needed.

2. **Codifies the close-out as a distinct meta-discipline** separate from per-artifact validation:
   - `udm-checks-and-balances` (D55) = per-artifact, per-decision, per-runbook validation
   - `udm-round-closeout` (NEW, D60) = per-round aggregate doc updates + cross-doc consistency sweep
   - Per-artifact validation runs FIRST; round close-out runs LAST.

3. **Authors `udm-round-closeout` skill** at `.claude/skills/udm-round-closeout/SKILL.md` orchestrating an 8-section close-out checklist:
   - Per-artifact validation completeness
   - Decision log updates
   - Edge case register updates
   - Runbook consistency
   - Backlog and risks
   - **Aggregate doc updates** (CURRENT_STATE, HANDOFF, BACKLOG, RISKS, NORTH_STAR, 00_OVERVIEW)
   - Cross-doc consistency sweep
   - Validation log entry

4. **Updates existing skills/agents to reference HANDOFF** so the system as a whole is HANDOFF-aware:
   - `udm-checks-and-balances` mentions close-out as the post-validation step
   - `udm-design-reviewer` reads HANDOFF.md alongside other context docs
   - `udm-test-author` reads HANDOFF.md
   - `udm-researcher` already reads HANDOFF.md
   - `udm-decision-recorder` adds "verify HANDOFF.md updated" to its post-decision checklist
   - `udm-runbook-author` adds "verify HANDOFF.md §7 if new runbook is operationally significant"

5. **Independence at the round level**: per D55/D56, the close-out reviewer should be a different agent than the round's primary producer. Round close-out IS a validation gate.

6. **Trivial-edit exemption**: a round consisting of one typo fix doesn't warrant full close-out. Apply judgment: 3+ artifacts changed OR any status flip → run full close-out; otherwise commit as trivial edit.

**Rationale**: Without this discipline, HANDOFF.md drifted from reality after every round. The user's question surfaced the gap explicitly. The close-out skill formalizes "what does it mean to finish a round" — answer: not just artifacts done, but aggregate state visible to a new agent picking up tomorrow.

**Trade-off accepted**: each round closes with one extra step (~15-30 min for a substantive round). The cost is bounded; the benefit is HANDOFF.md actually serving its stated purpose.

**This decision retroactively applies**: round close-out is run on the round that established it (eat-our-own-dog-food). HANDOFF.md §11 round history is initialized with the 5 rounds completed to date.

**See**: `.claude/skills/udm-round-closeout/SKILL.md`, `HANDOFF.md` §11.

---

## D61: Integrate NORTH_STAR / BACKLOG / RISKS into the agent system

**Status**: 🟢 Locked
**Driver**: User reflection — "Reflect on the other files. NORTH_STAR, RISKS, BACKLOG and so on. Do we need to integrate these files into our system as we just did with HANDOFF?"

**Pillar(s) served**: Audit-grade, Operationally stable, Traceability (canonical NORTH_STAR pillar names)

**Decision**: Three integrations to close gaps identified in reflection:

1. **Pillar mapping requirement on decisions** (NORTH_STAR enforcement)
   - `udm-decision-recorder` skill template adds "Pillar(s) served" line — required for all new decisions D62+
   - Existing D1-D60 backfill is a 🟡 follow-up tracked as B16 in BACKLOG
   - Makes NORTH_STAR queryable: "show me every decision serving traceability" is now a grep, not manual work

2. **Risk-surfacing in design review and validation Gate 5** (RISKS integration)
   - `udm-design-reviewer` agent operating model now reads RISKS.md before reviews
   - `udm-design-reviewer` output adds "Risks introduced / addressed" section flagging 🆕/✅/⬆️/⬇️ deltas
   - `udm-checks-and-balances` Gate 5 expanded to include risk delta check
   - Round close-out (per D60) consumes these findings to update RISKS.md

3. **Backlog-surfacing in validation outputs** (BACKLOG integration)
   - Every 🟡 finding from validation gates includes a proposed B-number with WSJF score
   - Round close-out appends proposals directly to BACKLOG.md without re-deriving
   - Closes the gap where validation log entries had follow-up lists that didn't always propagate

**Plus 6 doc updates** to fix stale references:
- `udm-design-reviewer` reads NORTH_STAR (clears B15)
- `CLAUDE.md` autonomous rules updated for D55-D60 discipline mandate
- `02_PHASES.md` Phase 1 Round 1 status reflects 🟢 Locked
- `00_OVERVIEW.md` document map adds skills + agents tier
- `SKILLS_PLAN.md` updated with new skills (`udm-checks-and-balances`, `udm-round-closeout`)
- `MAINTENANCE.md` § Onboarding read order adds NORTH_STAR + HANDOFF + RISKS

**Deferred to BACKLOG**:
- B16: Backfill pillar mapping on D1-D60 (1-2 hours)
- B17: Cross-reference audit tool (half day)
- B18: Per-decision risk classification on D1-D60

**Rationale**: PM-discipline files (NORTH_STAR, BACKLOG, RISKS) existed but weren't enforced as invariants by the agent system. Adding pillar mapping, risk surfacing, and backlog surfacing makes them load-bearing rather than ornamental.

**Trade-offs accepted**: 
- New decisions take ~1 minute longer to record (pillar + risk fields)
- Validation outputs are slightly longer (B-number proposals + risk deltas)
- Backfill of D1-D60 is non-trivial work deferred to BACKLOG

**Reversibility**: reversible. Remove the template fields; the existing decision log structure still works without them.

**Risk delta**: ⬇️ DE-ESCALATED R12 (Documentation drift). Cross-doc enforcement reduces likelihood from Medium to Low; RISKS.md updated to reflect new score 2. Will close R12 entirely after Round 2 demonstrates the discipline holds in a non-meta round (avoids declaring victory mid-establishment).

**See**: `udm-decision-recorder/SKILL.md`, `udm-checks-and-balances/SKILL.md` Gate 5, `udm-design-reviewer.md` operating model + Risk-surfacing section.

---

## D62: Multi-agent discipline enforcement — Canonical Context Load (CCL) mandatory in every agent and skill

**Status**: 🟢 Locked (after first-pass dog-food test + mandatory second-pass per D56 — see `_validation_log.md` 2026-05-10 D62 entry)
**Driver**: User explicitly flagged that custom subagents and project-local skills had inconsistent / incomplete instructions for reading the canonical PM docs (NORTH_STAR, HANDOFF, CURRENT_STATE, CHECKS_AND_BALANCES, RISKS, BACKLOG, _validation_log) before producing output. D60 (HANDOFF awareness) and D61 (NORTH_STAR/RISKS/BACKLOG integration) addressed templates but didn't standardize a *named protocol* with verification rule. User: "Ensure multi-agent teams use Claude skills and regard related markdown files... It is the highest priority that we ensure that multi-agent teams also abide by our requirements."

**Pillar(s) served** (per D61):
- **Audit-grade**: every agent invocation grounds output in the same canonical context, producing reproducible reviews; verification rule (first `Read` on Stage 1 doc) is auditable from tool trace
- **Operationally stable**: eliminates inconsistency in agent behavior across rounds; new engineers / agents picking up the project see one named protocol, not 11 ad-hoc read lists
- **Idempotent**: same input + same Stage 1+2 context = same agent output

**Decision**: Every custom subagent (`.claude/agents/*.md`) and every project-local skill (`.claude/skills/*/SKILL.md`) MUST follow the Canonical Context Load (CCL) protocol documented in `docs/migration/MULTI_AGENT_GUIDE.md` § Canonical Context Load. CCL has 4 stages:

- **Stage 1 — Orientation** (4 mandatory reads, BEFORE any other Read): `NORTH_STAR.md`, `HANDOFF.md`, `CURRENT_STATE.md`, `CHECKS_AND_BALANCES.md`
- **Stage 2 — Risk + Backlog awareness** (3 mandatory reads for review/production work): `RISKS.md`, `BACKLOG.md`, `_validation_log.md`
- **Stage 3 — Task-specific reads** (varies per agent/skill, enumerated in each definition file)
- **Stage 4 — Reference-on-demand** (grep, don't full-read): `03_DECISIONS.md`, `04_EDGE_CASES.md`, `05_RUNBOOKS.md`, `02_PHASES.md`

**Verification rule**: agent's first content-substantive tool call (`Read` or `Grep` with content output) MUST hit a Stage 1 doc. Glob-only / filesystem-listing calls before Stage 1 do not violate. Tool-trace audit confirms compliance. Spot-check at every round close-out; full audit quarterly per `MAINTENANCE.md`.

**Self-edit fallback**: if a Stage 1 doc itself is the artifact under edit, Stage 1 reads still run BEFORE the edit; the artifact-as-target is read again under Stage 3 with intent-to-edit framing.

**Trivial-task exception**: typo / formatting / 1-line clarification edits skip Stages 1-2; note exception in output ("Trivial edit — CCL Stage 1+2 skipped per exception").

**Rationale**: D60 added "read HANDOFF" to udm-design-reviewer + udm-test-author + udm-researcher. D61 added pillar-mapping requirement to udm-decision-recorder + risk-surfacing to udm-design-reviewer. But the read protocol drifted across agents and was absent in most skills (audit found 0/8 skills had full Stage 1+2 coverage; 6/8 had nothing; 3/3 agents had partial coverage at best — no single component had the full canonical context-load protocol). A single named doctrine (CCL) is canonical across the system; all agents/skills reference it; users can audit compliance via tool traces.

Alternatives considered:
- (a) **Leave per-agent inconsistencies in place** — rejected: agents drift in coverage; can't audit compliance.
- (b) **Enforce reads via PreToolUse hooks** — rejected: D54 deferred hooks until production-class data; adds infrastructure burden ahead of need.
- (c) **Embed full doctrine in every agent body** — rejected: duplication risk + drift on doctrine update.
- (d) **Reference doctrine from MULTI_AGENT_GUIDE.md from each agent (chosen)** — single source of truth, agents/skills reference by name.

**Trade-offs accepted**:
- Each agent invocation now reads 4-7 markdown files before substantive work — adds ~30s of context loading per invocation. Acceptable given audit-grade discipline value.
- Compliance is honor-system + trace-audit (no hard enforcement until D54 hooks land). User accepts trace-audit as the verification mechanism.
- Trivial-task exception is a judgment call — author may abuse to skip discipline. Mitigated: any 🟢 status flip without `_validation_log.md` entry remains a status mismatch (D55 hard rule).

**Affects**:
- Decisions: extends D55, D56, D60, D61 (formalizes agent discipline from D60+D61 templates into mandatory protocol)
- Edge cases: F-series (failover — agents must know what's locked vs in-flight)
- Runbooks: none directly
- Schema: none directly
- Code modules: none directly
- Skills: all 8 in `.claude/skills/` updated with CCL section
- Agents: all 3 in `.claude/agents/` updated with CCL operating model
- Docs: `MULTI_AGENT_GUIDE.md` (canonical doctrine), `SKILLS_PLAN.md` (reference)

**Reversibility**: Reversible. CCL is a discipline; reverting means removing the section from each .md file. No code or schema impact. Future PreToolUse-hook enforcement (when D54 lifts) is an upgrade path, not a fork.

**Risk delta** (per D61):
- ⬇️ DE-ESCALATED: R3 (single-engineer Python expertise). CCL standardizes context loading so any agent / engineer picking up work sees consistent context — reduces bus-factor likelihood.
- 🆕 NEW: R16 — agent compliance with CCL is honor-system (trace-audit only, no hard enforcement until D54 hooks land). Likelihood 2 × Impact 2 = 4 (low). Mitigation: dog-food test verifies compliance pattern + quarterly audit per MAINTENANCE.md.

**See also**:
- `docs/migration/MULTI_AGENT_GUIDE.md` § Canonical Context Load (doctrine source)
- `.claude/agents/*.md` (all 3 — CCL in operating model)
- `.claude/skills/*/SKILL.md` (all 8 — CCL section)
- `docs/migration/SKILLS_PLAN.md` (cross-reference)
- `docs/migration/_validation_log.md` 2026-05-10 D62 dog-food entry

---

### D62 — Amendment 2026-05-15 (D.3 of MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.5)

**Status**: 🟢 Locked 2026-05-15 (additive amendment to original D62 body above; preserves Stage 1-4 protocol unchanged; adds Stage 0 + downstream-artifact cross-refs + discipline-floor extensions). Authored per D.3 of the markdown refactor effort. Lock authority: pipeline-lead Option A path approval ("B-273 → D.2 → D.3 → D.4") 2026-05-15.

**Amendment scope**: ADDITIVE only — extends CCL with a recommended-not-mandatory Stage 0 routing-manifest read; cross-refs new downstream artifacts (PLANNING_DISCIPLINE.md / INDEX.md / `_refactor_log.md` / `_archive/` / CLAUDE_GOTCHAS.md) that didn't exist when D62 was originally locked; acknowledges numerical drift in §Affects skill/agent counts; codifies discipline-floor additions since lock. Original D62 Stage 1-4 semantics, Verification rule, Self-edit fallback, and Trivial-task exception remain unchanged + binding.

#### Stage 0 — Routing manifest (NEW; recommended-not-mandatory)

- **`docs/migration/INDEX.md`** — master routing manifest in llms.txt format; authored 2026-05-15 per D.2 Phase 1 task 1.3 + MARKDOWN_REFACTOR_PLAN.md §13.2. Read FIRST when uncertain which downstream Stage 1+2+3 docs your task actually needs. Skip when: you already know which Stage 1+2+3 docs you need (typical for experienced agents on recurring task patterns).

**Why recommended-not-mandatory**: experienced agents on recurring tasks don't need INDEX.md routing — they already know which Stage 1 docs to load. Mandatory Stage 0 for ALL invocations would add overhead without proportional value. The recommendation gate captures the benefit (discoverability for novel task patterns + fresh-agent onboarding) without imposing the cost on every invocation.

**Evaluation heuristic** (added 2026-05-16 per B-289 closure): If your task-type does not map to a known recurring pattern from prior rounds, treat Stage 0 as mandatory. Closes the asymmetry where experienced agents correctly skip Stage 0 on familiar work BUT fresh agents on novel task patterns may also skip (incorrectly). The recurring-pattern test: have you (or any prior agent on this branch) performed a task with this scope + artifact-set + invocation context within the last 3-5 rounds? If NO → Stage 0 mandatory; consult INDEX.md before proceeding.

#### Downstream-artifact cross-refs added (per PLANNING_DISCIPLINE.md §1.4)

Artifacts authored since D62 lock that the doctrine now references:

- **`docs/migration/PLANNING_DISCIPLINE.md`** (authored 2026-05-15) — skill-selection matrix + sub-agent inheritance contract; binding per CLAUDE.md hard rule 13
- **`docs/migration/INDEX.md`** (authored 2026-05-15) — CCL Stage 0 master routing manifest (see above)
- **`docs/migration/_refactor_log.md`** (authored 2026-05-15) — append-only refactor audit trail per Option B belt-and-suspenders strategy
- **`docs/migration/_archive/`** subdirectory (created 2026-05-15) — verbatim refactor archive home; recovery path without git archaeology
- **`docs/migration/CLAUDE_GOTCHAS.md`** (authored 2026-05-15) — extracted gotcha sidecar per D.5 trim; active reference for B-N/E-N/V-N/W-N/OBS-N/SCD2-*/LT-*/DIAG-*/Item-* code-level lookups

#### Discipline-floor additions since D62 lock (augment CCL without superseding)

These extend the CCL protocol with structural disciplines added across Rounds 4-8 + this session:

- **CLAUDE.md hard rule 13** (introduced 2026-05-15) — planning-session skill-activation discipline + sub-agent inheritance contract binding for ALL agents/skills/multi-agent-teams. CCL Stage 1+2 is still mandatory; hard rule 13 adds skill-selection discipline ON TOP.
- **`superpowers-verification-before-completion`** (imported 2026-05-15 from `obra/superpowers` v5.1.0; MIT) — ALWAYS-MANDATORY pre-completion gate per PLANNING_DISCIPLINE.md §2.3. Iron Law: "NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE". Pairs with CCL: CCL ensures inputs are correct; verification-before-completion ensures outputs are real.
- **`superpowers-systematic-debugging`** (imported 2026-05-15 from `obra/superpowers` v5.1.0) — ALWAYS-MANDATORY for any debugging scope. Iron Law: "NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST". Closes gap that no `udm-*` skill addresses structured debugging methodology.
- **`superpowers-tdd`** (imported 2026-05-15) — OPTIONAL conditional for PS-3 TOOL scope. RED-GREEN-REFACTOR test-driven-development discipline.
- **B-280 verbatim-extraction-safety** (formalized 2026-05-15 from D.5 trim Pitfall #9.l sub-pattern recurrence) — use `git show <pre-commit>:<file>` or `curl` for byte-exact content extraction. Avoid Write-tool re-typing of escape-sequence-bearing content (rendering pipeline can collapse ` `/` ` escape sequences to literal U+2028/U+2029 control characters — the exact BCP-corrupting pattern B-6 warns against).

#### Numerical drift acknowledgment (per Pitfall #9.k arithmetic-propagation)

Original D62 §Affects enumerated:
- "all 8 skills in `.claude/skills/`" → as of 2026-05-15: **22+ project `udm-*` skills + 3 imported `superpowers-*` skills + multiple non-project skills = 25+ total**
- "all 3 agents in `.claude/agents/`" → as of 2026-05-15: **5-7 project agents** (udm-design-reviewer, udm-test-author, udm-researcher, udm-cascade-auditor, udm-data-engineer-review, udm-checks-and-balances-agent)

To be reconciled at next round close-out via `udm-cascade-audit-evolver` count-refresh (B-N candidate; pending recurrence-evidence per HANDOFF §8 sub-class accumulator). These drifts do NOT invalidate the original D62 discipline; they reflect organic accumulation of skills/agents across Rounds 4-8 + this session's planning-discipline + Superpowers partial-adoption work.

#### Forward-strategy contract (per PLANNING_DISCIPLINE.md §1.5)

Any future PS-2 DOC scope refactor (markdown trim / split / extract / relocate) MUST follow Option B belt-and-suspenders strategy:
1. Always archive verbatim to `_archive/` via `git show <pre-commit>:<file>` byte-exact extraction
2. Always cross-ref from active file to canonical destination(s)
3. Always log to `_refactor_log.md` with full provenance
4. Always preserve non-git recovery path

#### Amendment cross-references

- `MARKDOWN_REFACTOR_PLAN.md` §7.1 task 1.5 (D.3 task definition)
- `MARKDOWN_REFACTOR_PLAN.md` §18 phase breakdown (D.0-D.6 sequence)
- `INDEX.md` (CCL Stage 0 artifact)
- `PLANNING_DISCIPLINE.md` §1.4 (downstream artifacts) + §1.5 (refactor-strategy contract) + §2.3 (always-mandatory skills extension)
- `_refactor_log.md` (audit trail of all refactor events; binding template)
- `MULTI_AGENT_GUIDE.md` §"Stage 0 — Routing manifest" subsection (added 2026-05-15 cross-ref to INDEX.md)
- CLAUDE.md hard rule 13 (planning-session skill-activation; binding)
- B-N closures this session: B-273 (F9.1 one-directional relaxation) + B-279 (research-grounding)
- B-N opens this session: B-272 + B-274 through B-284 (12 cumulative)
- Commits this session: ec1ced1 → 521b68c → 1b00755 → e15cd3a → bacfebe → c189432 → 7e2c606 → bd7e6e5 → c6aa546 → 4c6d11f → 395d22d (11 commits to D.3 amendment + this commit)

**Amendment author**: Parent agent per D.3 cascade execution 2026-05-15 per user Option A path authorization.

**Acceptance**: amendment locks 🟢 same-session per D111 process-infra exemption precedent (analogous to D55 / D60 / D89-D91 / D95-D99 / D113 — process-discipline meta-decisions don't gate on 🟡-first attestation when the discipline they encode is itself first-event-evidenced and pipeline-lead approved via Option A path).

**Acceptance footnote (post-hoc 2026-05-16 per B-285 closure)**: The D111 exemption was applied to this additive amendment **by ANALOGY** to D111's enumerated exempt class (meta-process decisions / design patterns / schema-evolution discipline) — NOT by explicit text of D111. D111's body at `03_DECISIONS.md` L3154 enumerates the exempt class for ORIGINAL decisions; it does not explicitly enumerate "additive amendments to decisions already in the exempt class." The amendment's analogy is reasonable (additive amendments preserve original semantics + add no operational-infra claims) but the precedent was undocumented at lock time. **B-285 post-hoc reviewer pass 2026-05-16** closes the substantiation gap via paired Gate 2 invocation: udm-design-reviewer agent (13th cumulative sub-agent inheritance contract application) + udm-checks-and-balances 5-gate (14th application) — both verdicts integrated into `_validation_log.md` second-pass entry citing original D.3 lock at L8773. Pattern F convergent finding A-1 + post-hoc gap-check G4 finding closed via this review. **Follow-up tracking**: B-292 (open) tracks formal extension of D111 exempt-class to include additive amendments (closure target: next round close-out via udm-cascade-audit-evolver). Until B-292 closes, future additive D-N amendments invoking D111 exemption MUST cite both D111 + this footnote + the closure of B-285 as the precedent chain.

---

## D63: `UdmTablesList` new column inventory + idempotent ALTER DDL

**Status**: 🟢 Locked (after first-pass + mandatory second-pass + third-pass per D56 — see `_validation_log.md` 2026-05-10 Round 2 entries)
**Driver**: Phase 1 Round 2 (Configuration) requires 6 new columns on `General.dbo.UdmTablesList` to support the new pipeline build's CDC mode cutover (`CDCMode`), PII tokenization (`PiiColumnList`), retention classification (`DataClassification`), Phase 4 rollout cohorts (`CohortAssignment`), operator transient toggle (`IsEnabled`), and table-level legal hold (`LegalHoldOnly`).

**Pillar(s) served** (per D61): **Audit-grade**, **Traceability**

**Decision**: Add 6 new columns to `General.dbo.UdmTablesList` via idempotent `IF NOT EXISTS`-guarded ALTER DDL (per D34 greenfield posture). Each column has a named `DEFAULT` constraint (`DF_UdmTablesList_<col>`) for targeted future drop; CHECK constraints on enum-typed columns (`CDCMode`, `DataClassification`). Defaults preserve current pipeline behavior bit-for-bit on first deployment.

The 6 columns:
1. `CDCMode NVARCHAR(20) NOT NULL DEFAULT 'change_detect'` (CHECK: `IN ('change_detect', 'parquet_snapshot')`) — per-table flag for Phase 4 cutover atomicity
2. `PiiColumnList NVARCHAR(MAX) NULL` — CSV of PII column names per source row; consumed by tokenization layer (D6)
3. `DataClassification NVARCHAR(20) NULL` (CHECK: `IN ('PII', 'PCI', 'none') OR NULL`) — informs retention SLA + audit reporting per D30
4. `CohortAssignment NVARCHAR(50) NULL` — Phase 4 rollout sequencing tag
5. `IsEnabled BIT NOT NULL DEFAULT 1` — transient operator toggle; distinct from `StageLoadTool IS NULL` (permanent skip)
6. `LegalHoldOnly BIT NOT NULL DEFAULT 0` — table-level legal hold per D30 + RB-11

**Rationale**: All 6 columns are required by the new pipeline build's design (covered in `phase1/02_configuration.md § 1.2`). Adding via separate DDL block (not a single column-addition statement) means each can be reviewed independently and the migration is partially recoverable on failure. `IF NOT EXISTS` guards make re-deploy a no-op (D34 + idempotency invariant D15). Named DEFAULT constraints enable targeted ALTER DROP without scanning `sys.default_constraints` for system-generated names.

Alternatives considered:
- (a) **Add all 6 columns in a single ALTER** — rejected: failure of one rolls back all; harder to migrate per-column independently
- (b) **Defer columns to per-feature migrations** (e.g. `CDCMode` lands with Phase 4, `PiiColumnList` with vault enablement) — rejected: fragments the schema across rounds; Round 6 deployment becomes a chain of mini-migrations
- (c) **Add columns NULL-able with no defaults**, populate via post-step UPDATE — rejected: leaves rows in an inconsistent intermediate state; existing pipeline reads would see NULL `IsEnabled` and behave undefined
- (d) **Idempotent guarded ALTER with NOT NULL DEFAULTs (chosen)** — single atomic per-column addition; safe re-deploy; preserves current behavior

**Trade-offs accepted**:
- DDL is verbose (6 ALTER blocks + 2 CHECK constraint blocks). Acceptable — verbosity here matches Round 1 style and aids per-column audit
- First-run after deployment doesn't immediately exercise the new columns (they're configured per-table over Phase 4); columns sit with defaults for weeks-months on most tables
- `PiiColumnList` is `NVARCHAR(MAX)` to support any reasonable PII surface; storage cost negligible

**Affects**:
- Decisions: implements no prior decision directly; consumed by Phase 4 cutover (D29-adjacent), D6 (vault PII tokenization), D30 (retention)
- Edge cases: P-series (PiiColumnList enables P1 / P5 / P8 / P9 mitigations at config layer); F-series (IsEnabled supports operational toggle)
- Runbooks: RB-11 (retention enforcement) reads `LegalHoldOnly`; future Phase 4 cutover runbook reads `CDCMode`
- Schema: `General.dbo.UdmTablesList` (6 ALTER ADDs + 2 CHECK constraints; named DEFAULTs)
- Code modules: `orchestration/table_config.py` extends `TableConfig` dataclass with 6 new fields; `data_load/pii_tokenizer.py` reads `PiiColumnList`; Round 3 implementation
- Skills: `udm-data-engineer-review` checklist may need an entry for the new columns (B-number candidate at close-out)
- Docs: `phase1/02_configuration.md § 1.2 + § 1.3` (canonical spec); `phase1/01_database_schema.md` Refs section

**Reversibility**: Reversible at table level (DROP COLUMN, DROP CONSTRAINT). But: once a column is populated with non-default values in production rows, reverting requires data preservation strategy. Treat as reversible during Phase 1; harder once Phase 4 populates.

**Risk delta** (per D61):
- No new risks. Mitigates implicit risk of column-shape drift (column add without spec) via the formal inventory in `02_configuration.md § 1`

**See also**:
- `docs/migration/phase1/02_configuration.md` § 1.1 (existing column inventory), § 1.2 (new columns spec), § 1.3 (DDL)
- `docs/migration/03_DECISIONS.md` D6, D30, D34
- `migrations/udm_tables_list_phase1_columns.py` (Round 6 deployment artifact — file to be created)

---

## D64: GPG passphrase storage strategy — TPM2 sealed against PCR set

**Status**: 🟢 Locked (after first-pass + mandatory second-pass + third-pass per D56 — see `_validation_log.md` 2026-05-10 Round 2 entries)
**Driver**: B13 (Phase 0 deliverable 0.12) — GPG-based credential strategy needs a concrete passphrase-storage scheme so the pipeline can auto-decrypt `/etc/pipeline/credentials.json.gpg` at process start (no interactive input) per Automic unattended schedule (D29 revised).

**Pillar(s) served** (per D61): **Operationally stable**, **Audit-grade**

**Decision**: Store the GPG passphrase **sealed in TPM2 NVRAM, unsealed only when boot-time PCR measurements match a known-good configuration** (kernel + initrd + bootloader). At pipeline process start, `credentials_loader.py` invokes `tpm2_unseal` to retrieve the passphrase, decrypts the envelope via `gpg2 --batch --pinentry-mode loopback --passphrase-fd 0`, then zeros out the passphrase buffer.

**Rationale**: Selected via `udm-brainstorm` 4-alternative enumeration (`phase1/02_configuration.md § 3.2`). Walked through `NORTH_STAR.md` conflict-resolution rubric in priority order:

1. **Audit-grade always wins**: TPM2 PCR-sealing leaves auditable evidence in syslog (`tpm2_unseal` events with PCR values). Option B (kernel keyring) has no such attestation.
2. **Traceability**: TPM2 unseal events integrate with audit trail. Option D (manual operator unlock) leaves no record of WHO unlocked.
3. **Idempotent**: Sealed passphrase is byte-identical every boot. Option B has daemon-timing dependency.
4. **Operationally stable**: TPM2 supports Automic unattended cycle. Options C (YubiKey) and D (manual) are incompatible — REJECTED on this pillar alone.
5. **$120K/year ceiling**: TPM2 is included in standard RHEL server pricing; no incremental cost. Option C requires hardware procurement.

Alternatives considered (full enumeration in `02_configuration.md § 3.2`):
- (a) **Linux kernel keyring (keyutils)** — rejected: no hardware attestation; passphrase in plaintext kernel RAM
- (b) **Hardware token (YubiKey)** — rejected: incompatible with Automic unattended schedule (touch-to-confirm)
- (c) **Offline manual unlock** — rejected: 2,190 operator interactions/year × 3 servers = burnout + error rate
- (d) **TPM2 sealed against PCR (chosen)** — hardware-rooted trust; standard RHEL tooling; unattended-compatible

**Trade-offs accepted**:
- Coupling to kernel + bootloader version: every patch requires re-sealing (RB-12 includes patch-day procedure)
- Cross-server parity surface increases: PCR policy hash is now part of `parity_baseline.json` (§ 4.1)
- TPM2 hardware fault is catastrophic until break-glass recovery via secondary recipient (mitigated: envelope has 2 recipients per § 3.1)

**Affects**:
- Decisions: implements B13; respects D27 (cross-server parity — PCR policy in baseline); respects D29 revised + D33 (unattended Automic schedule + cooperative cancellation)
- Edge cases: F-series new entry (TPM2 hardware fault → break-glass recovery)
- Runbooks: RB-12 (key rotation — § 3.4 stub; full authoring tracked as B41)
- Schema: none
- Code modules: `data_load/credentials_loader.py` (R3) — interface in § 3.3; reads passphrase via `tpm2_unseal` shell-out
- Docs: `phase1/02_configuration.md § 3` (full spec)

**Reversibility**: HARD. Once TPM2-sealed passphrase is operational, migrating to another strategy is a key-rotation event (RB-12). Reversible in principle (re-seal to different scheme) but operationally expensive.

**Risk delta** (per D61):
- 🆕 NEW: candidate F-series edge case for TPM2 hardware fault → tracked at Round 2 close-out per B40
- ⬇️ DE-ESCALATED implicit: R09 (PII compliance audit) — TPM2 attestation strengthens audit-grade posture for credential-handling

**See also**:
- `docs/migration/phase1/02_configuration.md` § 3.2 (brainstorm), § 3.3 (loader interface), § 3.4 (RB-12 stub), § 3.5 (audit trail)
- `docs/migration/BACKLOG.md` B13 (Phase 0 deliv 0.12 implementation)
- `docs/migration/03_DECISIONS.md` D6 (vault), D27 (parity), D29 (Automic), D54 (hooks deferred — TPM2 unseal could be a PreToolUse hook when D54 lifts)

---

## D65: Parity drift severity classification (fatal / warning / informational)

**Status**: 🟢 Locked (after first-pass + mandatory second-pass + third-pass per D56 — see `_validation_log.md` 2026-05-10 Round 2 entries)
**Driver**: B12 (Phase 0 deliverable 0.11) — Cross-server parity baseline needs a concrete severity tier so `tools/verify_server_parity.py` (R4 impl) can make pipeline-start / pipeline-block decisions deterministically.

**Pillar(s) served** (per D61): **Operationally stable**, **Idempotent**

**Decision**: Classify parity-baseline drift into four tiers (fatal / warning / informational / match), with **fatal** triggering `sys.exit(1)` at pipeline start. The categorization rule: if drift COULD produce silent data-correctness divergence between dev and prod, it's fatal. Otherwise warning (review at quarterly parity check) or informational (trend only). Match is the no-action default.

Fatal-tier items: Python version mismatch; library SHA mismatch; `MALLOC_ARENA_MAX` missing or wrong; `systemd_unit.sha256` differs; `credentials_envelope.sha256` differs; mssql-tools major version mismatch; missing required filesystem path; TPM2 PCR policy hash differs.

Warning-tier: kernel patch level (point release); transient `sysctl` differences; documented exception invoked (e.g. `AUDIT_LOG_LEVEL = DEBUG` on dev).

Informational: server uptime; load average; recent kernel patch deploy timestamp.

**Rationale**: The pipeline's idempotency invariant (D15) requires same-code-same-input-same-output across servers. Any drift that could violate this is fatal. `MALLOC_ARENA_MAX=2` is the canonical example — its absence (per W-4) causes 10× memory bloat from glibc arena fragmentation. Same code, same input, but prod OOMs and dev doesn't — masking the bug until production. Pipeline refusing to start is intentionally restrictive: D27 + audit-grade pillar > convenience.

Alternatives considered:
- (a) **Single-tier "must match"** — rejected: rejects legitimate per-server differences (e.g. operational tags); would block deployment for trivia
- (b) **Three-tier without informational** — rejected: loses trend signal for slow drift (e.g. kernel patches accumulating)
- (c) **Operator-judgment per-check at runtime** — rejected: non-deterministic; pipeline decisions vary by operator
- (d) **Four-tier with auto-block on fatal (chosen)** — deterministic; operator-overridable via `documented_exceptions` with explicit `expires_at`

**Trade-offs accepted**:
- "Fatal" is intentionally aggressive — first-run after dependency upgrade requires pin re-roll (extra step). Acceptable per audit-grade pillar.
- Some legitimate operational drift (e.g. a sysadmin patches kernel before pipeline lead re-pins baseline) requires temporary `documented_exceptions` — adds operational ceremony.

**Affects**:
- Decisions: implements D27 operationally; respects D15 (idempotency invariant)
- Edge cases: F-series — new F entry for "MALLOC_ARENA_MAX unset triggers fatal" (B40)
- Runbooks: none directly; baseline maintenance cadence (§ 4.4) is operator practice not a runbook
- Schema: none
- Code modules: `tools/verify_server_parity.py` (R4 impl)
- Docs: `phase1/02_configuration.md § 4.3`

**Reversibility**: Reversible. Severity tiers can be re-classified; default action on each tier can be changed. Changing the criteria for "fatal" is the higher-impact decision and would supersede via new D-number.

**Risk delta** (per D61):
- ✅ MITIGATES (pending substantiation): R08 (cross-server parity drift) — formal severity classification operationalizes D27. Score reduction proposed (4 → 2) per Pitfall #8, only after `verify_server_parity` actually runs in dev.

**See also**:
- `docs/migration/phase1/02_configuration.md` § 4.1 (baseline JSON), § 4.2 (verifier interface), § 4.3 (severity), § 4.4 (cadence)
- `docs/migration/BACKLOG.md` B12 (Phase 0 implementation)
- `CLAUDE.md` § "Deployment Requirements" W-4 (`MALLOC_ARENA_MAX`)
- `docs/migration/03_DECISIONS.md` D27, D15

---

## D66: Automic job inventory + `JOB_<DOMAIN>_<CADENCE>` naming + gate-table contract

**Status**: 🟢 Locked (after first-pass + mandatory second-pass + third-pass per D56 — see `_validation_log.md` 2026-05-10 Round 2 entries)
**Driver**: Phase 1 Round 2 orchestration scope — Automic instance (per D29 revised) needs (a) an authoritative job list, (b) a naming convention that survives operator additions over time, and (c) a per-job-type contract with `PipelineExecutionGate` so failover behavior (D33) is consistent.

**Pillar(s) served** (per D61): **Operationally stable**, **Audit-grade**

**Decision**: Three sub-decisions, bundled:

1. **Job inventory** — 8 jobs at Round 2 freeze: `JOB_PARITY_VERIFY`, `JOB_PIPELINE_AM`, `JOB_PIPELINE_PM`, `JOB_GAP_DETECT`, `JOB_RECONCILE_WEEKLY`, `JOB_RETENTION_MONTHLY`, `JOB_CCPA_PROCESS`, `JOB_FAILOVER_TEST`. Of these, **only `JOB_PIPELINE_AM` and `JOB_PIPELINE_PM` use `PipelineExecutionGate`** (per Round 1's `CK_PipelineExecutionGate_CycleType IN ('AM', 'PM')` — preserving D34 greenfield posture, Round 1 schema is canonical). The other 6 jobs use `sp_getapplock` + `PipelineEventLog` for concurrency + audit (per `02_configuration.md § 5.3.6`). Schedule, server, upstream/downstream per `02_configuration.md § 5.1`. New jobs added by superseding this decision or sub-decision (D66.N).

2. **Naming convention** — `JOB_<DOMAIN>_<CADENCE>`. Domains: `PIPELINE`, `RETENTION`, `RECONCILE`, `PARITY`, `GAP`, `CCPA`, `FAILOVER`. Cadences: `AM`, `PM`, `DAILY`, `HOURLY`, `WEEKLY`, `MONTHLY`, `QUARTERLY`, `ONDEMAND`, `VERIFY`. Ad-hoc names forbidden; new DOMAINs require a D-number.

3. **Gate-table contract (AM/PM only)** — 4-phase lifecycle (Acquire via SP-3/SP-4 / Heartbeat / Cancel-check / Release) per `02_configuration.md § 5.3`. **Acquire uses Round 1's existing SP-3 (`PipelineExecutionGate_AcquireProd`) / SP-4 (`PipelineExecutionGate_AcquireTest`)** — Round 2 does NOT re-invent the acquire pattern. SP-3/SP-4 use `sp_getapplock` + transactional `MERGE` (per `01_database_schema.md` L1447+). Round 1 canonical column names used throughout (`LastHeartbeatAt`, `ActualStartTime`, `ActualCompletionTime`, `ExecutingServer`); no new gate columns introduced by Round 2. Heartbeat cadence: 5 min during AM/PM. Cancel-check on every heartbeat per D33; ack via `CancellationAcknowledgedAt` (Round 1 column). Progress / result detail lives in `PipelineEventLog`, not gate columns. Non-AM/PM job concurrency in § 5.3.6 (sp_getapplock + ledger + event log).

**Rationale**: Without an authoritative inventory, operators add jobs ad-hoc, naming drifts, and the gate-table contract becomes inconsistent (some jobs heartbeat, some don't; some check cancellation, some don't). The bundle locks all three concerns together so Round 4 (tools) + Round 6 (deployment) consume one consistent spec.

Alternatives considered:
- (a) **Inventory only, leave naming + contract informal** — rejected: drift surface; first operator-added job breaks the pattern
- (b) **Per-job D-numbers** — rejected: 8 D-numbers when one bundle suffices; D66.1 through D66.N pattern usable when changes are scoped
- (c) **Naming convention only, no inventory** — rejected: doesn't enforce the contract
- (d) **Bundle (chosen)** — three concerns lock together; sub-decisions (D66.1, D66.2, D66.3) supersede individually

**Trade-offs accepted**:
- Bundle is a single 🟡 → 🟢 flip — if Gate 2 finds an issue in one sub-decision, the whole bundle fails. Mitigated: sub-decision granularity (D66.1, D66.2, D66.3) is available for partial supersession.
- 8 jobs is the Round 2 freeze; adding a 9th job requires a new sub-decision. Acceptable — operations need a documented "approve this addition" step.

**Affects**:
- Decisions: implements D29 revised + D33 operationally; respects D22 (gap detection), D30 (retention), D27 (parity verify pre-flight)
- Edge cases: F-series — failover sequence § 5.4 is the central F-series guarantee; G-series — gap detection scheduling
- Runbooks: RB-9 (failover) cross-links to § 5.4; RB-10 (CCPA) cross-links to `JOB_CCPA_PROCESS`; RB-11 (retention) cross-links to `JOB_RETENTION_MONTHLY`
- Schema: `PipelineExecutionGate` already has the lifecycle columns (Round 1 schema, table 6); no new schema
- Code modules: `orchestration/table_lock.py` (gate acquire/release), `orchestration/pipeline_steps.py` (cancel-check integration) — Round 3 impl
- Docs: `phase1/02_configuration.md § 5` (full spec)

**Reversibility**: Reversible per sub-decision. Job inventory (D66.1) changes per operator approval. Naming convention (D66.2) is sticky — changing requires renaming existing jobs in Automic (operational cost). Gate-table contract (D66.3) changes require coordinated Round 3 module changes.

**Risk delta** (per D61):
- ⬇️ DE-ESCALATED (pending): R10 (production hardware failure) — formal failover sequence § 5.4 reduces MTTR. Score reduction proposed only after DR drill rehearses the sequence end-to-end (Pitfall #8 caution).
- 🆕 NEW: none directly — fits within existing F-series risk surface

**See also**:
- `docs/migration/phase1/02_configuration.md` § 5.1 (inventory), § 5.2 (naming), § 5.3 (gate contract), § 5.4 (failover)
- `docs/migration/03_DECISIONS.md` D29 (Automic revised), D33 (cooperative cancellation), D17 (idempotency ledger), D22 (gap detector)
- `docs/migration/05_RUNBOOKS.md` RB-9, RB-10, RB-11

---

## D67: Build-time immediate dummy-data smoke test (Tier 0) — every module verified at build, not at deploy

**Status**: 🟢 Locked (user-directed discipline addition 2026-05-10; same authority pattern as D62 — user explicit request constitutes the lock signal)
**Driver**: User direction 2026-05-10 — "One thing I'd like to include during the build phase is once we build something, we should immediately test that the code works as intended with dummy data. Record this idea somewhere." Recorded as a discipline addition before continuing Round 3 work.

**Pillar(s) served** (per D61):
- **Operationally stable**: build-time bugs caught at build time, not at deploy or production
- **Audit-grade**: every module has documented Tier 0 smoke-test execution creating audit trail of "this code was built AND verified runnable"
- **Idempotent**: dummy-data Tier 0 tests are themselves idempotent (pure / mocked); same input → same output validated at build

**Decision**: Every module produced from Round 3 onward (Round 3 spec; Round 4 Tools; Round 6 Deployment) MUST have a companion **Tier 0 smoke test** that runs at build time. Tier 0 is a NEW tier added to the 5-tier test pyramid established by D21 — the pyramid is now 6 tiers (Tier 0 / 1 / 2 / 3 / 4 / 5).

**Tier 0 specification**:

| Property | Value |
|---|---|
| File location | `tests/smoke/test_<module>.py` (one file per module) |
| Runtime ceiling | < 5 seconds per module |
| External dependencies | NONE — no Docker, no network, no real DB; pure functions with mocks where I/O is needed |
| Coverage scope | (1) module imports without error; (2) main public function invocable with synthetic dummy data; (3) return shape matches documented interface; (4) no silent failure paths |
| Trigger | (a) every commit (CI); (b) at the moment a module is authored (build-time invocation immediately following the Edit / Write that lands the module file) |
| Failure consequence | blocks any further build step; module is NOT considered "built" until Tier 0 passes |

**Tier 0 vs Tier 1 distinction**:

- **Tier 0 (NEW)**: build-time smoke; <5s; pure/mock; module-level "does it run?" check
- **Tier 1**: unit tests; <30s per module; happy-path + documented edge cases + boundary conditions
- **Tier 2**: property-based (Hypothesis); per-invariant idempotence proofs
- **Tier 3**: integration (Docker SQL Server fixture); end-to-end pipeline scenarios
- **Tier 4**: crash injection; pre-release confidence
- **Tier 5**: manual quarterly audit drills

Tier 0 is NOT a replacement for Tier 1 — it is the immediate sanity-check layer that runs at the moment of code creation. Tier 1+ remain Round 5 scope but Tier 0 lives wherever the module lives (Round 3 modules → Round 3 close-out adds Tier 0; Round 4 tools → Round 4 close-out adds Tier 0; etc.).

**Rationale**: Round 1 v1 had 8 bugs that shipped to "complete" status because no validation step ran. D55 (5-gate doc validation) addresses doc-level review. Tier 0 is the code-level parallel — "build it and immediately verify it runs" is the code-level equivalent of "write a doc and immediately validate it through the 5 gates". Without Tier 0, modules can ship with import errors, undefined names, interface drift, or silent failures that Tier 1+ tests would catch LATER at a much higher rework cost.

This decision codifies a practice that should have been implicit since D55 but wasn't. Recording explicitly closes that gap.

Alternatives considered:
- (a) **Defer all testing to Round 5** — rejected: leaves a build → Round 5 window where modules accumulate untested; bugs surface late and compound
- (b) **Tier 0 = full Tier 1** — rejected: Tier 1 is comprehensive (edge cases, fixtures); collapsing into one tier removes the fast-feedback property
- (c) **Manual operator smoke test post-deploy** — rejected: not auditable, not reproducible, not gated, not enforceable
- (d) **Build-time Tier 0 + Round 5 Tier 1/2/3 (chosen)** — fast feedback at build; comprehensive coverage in Round 5; orthogonal and additive

**Trade-offs accepted**:
- Each module deliverable is now 2 artifacts (module file + `tests/smoke/test_<module>.py`). Adds ~5-10 min per module authoring time.
- CI pipeline gains a Tier 0 stage before Tier 1. Acceptable per fast-feedback property.
- Tier 0 tests may drift from module signatures if not kept in sync. Mitigated: Round 3's module-spec template (per `phase1/03_core_modules.md` common patterns) freezes the interface; Tier 0 is the immediate verification that the implementation matches.
- Pre-Round-3 modules (existing extract/, data_load/, cdc/, scd2/ code referenced in CLAUDE.md) do NOT retroactively need Tier 0. Discipline applies forward from Round 3.

**Affects**:
- Decisions: extends D21 (5-tier test pyramid becomes 6-tier with Tier 0); composes with D55 + D56 (Tier 0 is to code what 5-gate is to docs); composes with D62 CCL (Tier 0 author invokes the same Stage 1+2 CCL as any producer)
- Edge cases: I-series — Tier 0 includes "invocable with synthetic input" check which catches I-series violations at module level before they reach integration
- Runbooks: Round 6 deployment runbook adds "Tier 0 smoke check passes before deploy proceeds" as a pre-flight gate
- Schema: none
- Code modules: every Round 3 module gets a `tests/smoke/test_<module>.py` companion (Round 3 close-out backfills the 6 modules already specified in § 1 + § 2; Round 3 going forward specifies Tier 0 inline)
- Skills: `udm-test-author` skill template extends to author Tier 0 sketches alongside Tier 1; tracked as B-number at Round 3 close-out
- Docs: `phase1/03_core_modules.md` § 8.4 (test fixture strategy) explicitly references Tier 0; future `06_TESTING.md` (Round 5 deliverable) extends to 6 tiers

**Reversibility**: Reversible — removing Tier 0 means deleting `tests/smoke/` files and removing the build-time check from CI. No data, schema, or external dependency impact.

**Risk delta** (per D61):
- ⬇️ DE-ESCALATED (pending evidence): **R03** (single-engineer Python expertise) — Tier 0 captures the engineer's working knowledge as auditable smoke tests; reduces bus-factor risk. Score reduction proposed only after first ~5 Round 3 modules ship with Tier 0 (per Pitfall #8 hedge — don't reduce until evidence lands).
- ⬇️ DE-ESCALATED (pending evidence): **R11** (validation discipline drift) — Tier 0 makes code-level validation mechanical, not optional. Same hedge.
- 🆕 None directly.

**See also**:
- `docs/migration/03_DECISIONS.md` D21 (5-tier test pyramid — superseded conceptually by 6-tier extension; D21 status remains 🟢 Locked with the extension noted)
- `docs/migration/phase1/03_core_modules.md` § 8.4 (test fixture strategy — will reference Tier 0 explicitly)
- `docs/migration/HANDOFF.md` § 8 Pitfall #1 ("Producing artifacts without validation") — Tier 0 is the code-level fix for this pitfall
- `docs/migration/06_TESTING.md` (Round 5 deliverable — will be extended to 6 tiers)

---

## D68: Error class hierarchy + retry semantics across Round 3 modules

**Status**: 🟢 Locked (after first-pass + mandatory second-pass + third-pass per D56 — see `_validation_log.md` 2026-05-10 Round 3 entries)
**Driver**: Round 3 module interfaces (§ 1 – § 7 of `phase1/03_core_modules.md`) each raise typed exceptions. Without a hierarchy, every module invents its own error class and callers can't decide retry-vs-fatal uniformly.

**Pillar(s) served** (per D61): **Operationally stable**, **Idempotent**

**Decision**: Two-tier base + per-module subclasses:
- `PipelineFatalError` — no retry; pipeline exits via `sys.exit(1)`; logged at CRITICAL
- `PipelineRetryableError` — retry per B-7 (exponential backoff, max 3 attempts, base delay 2s); logged at WARNING on retry, ERROR on terminal failure
- Per-module subclasses (e.g. `CredentialsLoadError`, `ParityFatalError`, `VaultUnavailable`, `ParquetWriteCrash`, `LedgerStepFailed`, `SnowflakeAuthFailed`) inherit from one of the above

Every Round 3 module specifies which classes it raises in its `Error modes` section.

**Rationale**: B-7's `cx_read_sql_safe` retry pattern is already the canonical retry idiom (CLAUDE.md). Extending to a 2-tier hierarchy formalizes the retry-vs-fatal decision at the type level, removing per-caller logic.

Alternatives considered: (a) single base class (rejected — loses retry-vs-fatal semantics); (b) 4-tier with operator-fixable / user-fixable distinctions (rejected — overengineered; revisit if Round 5 testing surfaces friction); (c) 2-tier (chosen — sufficient).

**Trade-offs accepted**: 2-tier may be insufficient for nuanced classifications later; revisit if friction.

**Affects**: All Round 3 modules; Round 5 test patterns (pytest.raises class matching); CLAUDE.md autonomous-rules pattern.

**Reversibility**: Reversible — flatten hierarchy or extend with sub-tiers without API break.

**Risk delta** (per D61): None directly. R11 (validation discipline drift) marginally helped by typed error contract.

**See also**: `phase1/03_core_modules.md` § "Error class pattern" + § 8.1; B-7 (CLAUDE.md).

---

## D69: Connection / cursor ownership model — `cursor_for(db_name)` canonical; no cursor crosses module boundaries

**Status**: 🟢 Locked (after first-pass + mandatory second-pass + third-pass per D56 — see `_validation_log.md` 2026-05-10 Round 3 entries)
**Driver**: Round 3's 17 modules each touch SQL Server. Without a canonical ownership model, modules may share cursors across boundaries (deadlock risk under D33 cancellation; idempotency violation under crash recovery).

**Pillar(s) served** (per D61): **Operationally stable**, **Idempotent**

**Decision**:
- `cursor_for(db_name)` context manager (existing in `connections.py`) is the canonical pattern; every module opens its OWN cursor inside its OWN context
- Cursors NEVER pass across module-boundary function calls
- `--workers` spawn subprocesses each with their own connection pool — no shared state across workers
- Within a process, the vault DB connection pool (`vault_client.configure_vault_connection_pool`) is a SEPARATE explicit pool, configured at module import time
- Per W-8: vault locks use `@LockOwner='Session'` with `autocommit=True`; do NOT change to Transaction-scoped without removing explicit `sp_releaseapplock` call

**Rationale**: CLAUDE.md "Gotchas" already documents the Item-22 + W-8 patterns implicitly. Codifying as D69 makes the discipline visible in every Round 3 module spec (§ "Concurrency (per D69)" appears in each).

**Trade-offs accepted**: Per-call cursor opening adds latency vs. shared cursor reuse. Acceptable given pipeline's batch-oriented profile (cursor lifecycle is dwarfed by BCP / extraction time).

**Affects**: All Round 3 modules' Concurrency sections; Round 4 tools follow the same pattern; Round 6 deployment's CI pipeline runs `--workers` smoke tests to verify isolation.

**Reversibility**: Reversible — connection-pool refactor doesn't break callers.

**Risk delta** (per D61): None directly.

**See also**: `phase1/03_core_modules.md` § "Resource ownership pattern" + § 8.2; CLAUDE.md Item-22, W-8.

---

## D70: Test fixture strategy (Tier 0/1/2/3/4/5 per D67-extended pyramid)

**Status**: 🟢 Locked (after first-pass + mandatory second-pass + third-pass per D56 — see `_validation_log.md` 2026-05-10 Round 3 entries)
**Driver**: Round 5 (Tests) needs fixture conventions frozen at Round 3 so module specs can reference `__test_fixtures__` in their interfaces. Without freeze, Round 5 + Round 6 deploy will both depend on a moving target.

**Pillar(s) served** (per D61): **Audit-grade**, **Operationally stable**

**Decision** (full per `phase1/03_core_modules.md` § 8.3):
- Tier 0: `tests/smoke/test_<module>.py` per module; <5s; pure / mock (D67 mandatory)
- Tier 1: `tests/unit/test_<module>.py` per-edge-case + per-error-path; pytest fixtures per-module
- Tier 2: `tests/property/test_<invariant>.py` Hypothesis strategies + idempotence proofs
- Tier 3: `tests/integration/` with Docker SQL Server fixture (`conftest.py`)
- Tier 4: `tests/crash/` chaos engineering; pre-release
- Tier 5: manual quarterly audit drills (`06_TESTING.md`)

Fixture data shared via `tests/fixtures/` (udm_test_fixtures, arbitrary_dataframe, synthetic_parquet, mock_credentials_envelope.gpg.b64); per-module `__test_fixtures__: list[str]` constant declares dependencies.

**Rationale**: Codifies what D21 (5-tier pyramid) + D67 (Tier 0 mandatory) imply but never freeze structurally.

**Trade-offs accepted**: Docker fixture adds ~30s Tier 3 startup; mitigated via `pytest --keepalive` + CI shared container.

**Affects**: Round 5 doc (`06_TESTING.md`) extends from D21's 5-tier to 6-tier; every Round 3 module's Test surface section uses these tier names; Round 6 CI stages map 1:1 to tiers.

**Reversibility**: Reversible — tier definitions can be refactored without breaking individual tests.

**Risk delta** (per D61):
- ⬇️ DE-ESCALATED (pending substantiation): R03 + R11 — same as D67. Hedge per Pitfall #8.

**See also**: `phase1/03_core_modules.md` § 8.3; D21 (5-tier pyramid, extended to 6-tier by D67); D67 (Tier 0 mandate).

---

## D71: Snowflake auth flow — RSA key decrypted from GPG envelope; ephemeral key file at `/dev/shm/snowflake_pk_<pid>`

**Status**: 🟢 Locked (after first-pass + mandatory second-pass + third-pass per D56 — see `_validation_log.md` 2026-05-10 Round 3 entries)
**Driver**: § 7.1 `snowflake_uploader` needs concrete auth flow; Snowflake's RSA key auth requires a key file on disk; D6 (no cloud KMS) means the key must come from the GPG envelope.

**Pillar(s) served** (per D61): **Audit-grade**, **$120K/year ceiling**

**Decision**:
- `SNOWFLAKE_PRIVATE_KEY_PEM` is stored in the GPG envelope (per Round 2 § 3.1 envelope schema)
- `credentials_loader` (§ 3.1) decrypts the envelope; the PEM is one of the returned dict values
- Caller (`snowflake_uploader`) writes the PEM to `/dev/shm/snowflake_pk_<pid>` mode `0600` (tmpfs — never persisted to disk)
- Snowflake `CONNECTION` reads via file path
- `release_snowflake_key()` (separate helper in `credentials_loader`) deletes the file after Snowflake auth completes
- NEVER logs the file's contents; sensitive_data_filter (§ 6.1) redacts RSA PEM blocks via pattern

**Rationale**: Snowflake's Python SDK requires a key file path; in-memory key is not a first-class option. tmpfs (`/dev/shm`) is RAM-backed — file never hits persistent storage. Per-process file path (`<pid>` suffix) prevents `--workers` collision.

**Trade-offs accepted**: Key file exists on disk for the duration of one Snowflake session (typically <1 minute per `COPY INTO`). Mitigated: tmpfs is volatile; aggressive cleanup via `release_snowflake_key()`; file mode 0600 owner-only.

**Affects**: § 7.1 `snowflake_uploader`; § 3.1 `credentials_loader` adds `release_snowflake_key()` helper; sensitive_data_filter pattern for RSA PEM blocks.

**Reversibility**: Reversible — Snowflake offers key-pair auth via other mechanisms (e.g. credential plugins); switching is a `credentials_loader` change.

**Risk delta** (per D61):
- 🆕 NEW: R20 (proposed) — `/dev/shm` key file leak via crash mid-session (file not deleted by `release_snowflake_key()`). Likelihood Low × Impact Medium = 2 ⚪. Mitigation: tmpfs reset at reboot + filesystem-level monitoring detects orphaned files; B-number at close-out to author monitor.
- Status: R20 NOT YET ADDED to RISKS.md — Round 3 close-out task per Pitfall #8 (parallel to R18/R19).

**See also**: `phase1/03_core_modules.md` § 7.1, § 3.1; Round 2 § 2.1.8 + § 3.1; D6 + D5.

---

## D72: Validation cycle termination rule — up-to-10 cycles per round with 3-consecutive-clean convergence

**Status**: 🟢 Locked (user-directed discipline addition 2026-05-10; same authority pattern as D62/D67 — user explicit request constitutes the lock signal)
**Driver**: User direction 2026-05-10 — "I'd rather have a great plan well thought out and thorough to prevent issues later. I'm considering adding 10 total validations where if there are three validations in a row that state nothing else is missing and everything is good then we proceed without processing additional validations." Adopted mid-Round-3 after the 4-agent deep-validation surfaced 3 new 🔴 that survived the standard D56 3-pass cycle.

**Pillar(s) served** (per D61):
- **Audit-grade**: convergence rule is auditable — count cycles; count consecutive clean; verdict
- **Operationally stable**: prevents infinite validation cycles; provides explicit termination criterion
- **Idempotent**: same convergence criterion applied uniformly across rounds

**Decision**: For any artifact under D55 + D56 validation:

1. **Validation cycle definition**: one cycle = one independent review pass — either a single-agent D56-style sequential pass OR a parallel multi-agent batch (e.g., the 4-agent deep-validation pattern introduced 2026-05-10).

2. **Cycle ceiling**: **maximum 10 validation cycles per round** before mandatory architectural-review escalation per `CHECKS_AND_BALANCES.md` § "Iterative validation cycles".

3. **Convergence rule (new termination)**: **3 consecutive cycles returning CLEAN** → cycle terminates; artifact may flip 🟡 → 🟢 Locked.
   - "Clean" = no 🔴 findings, and any 🟡 findings are documented backlog items (B-numbered) that the validator explicitly identifies as non-blocking.
   - "Not clean" = any 🔴, OR any 🟡 that the validator flags as blocking.

4. **Counting rule**: each parallel multi-agent batch counts as **ONE cycle**. A 4-agent batch with one 🔴 finding from any single agent = 1 cycle, "not clean". A 4-agent batch with all ✅ + only backlog-eligible 🟡 = 1 cycle, "clean".

5. **Reset rule**: any cycle returning "not clean" RESETS the consecutive-clean counter to 0. The counter only ticks forward when a cycle is fully clean.

6. **Escalation rule**: if the 10th cycle still hasn't produced 3 consecutive clean cycles, escalate to **architectural review** (per CHECKS_AND_BALANCES.md L195-199). Architectural review may: (a) split the artifact into smaller scope, (b) accept current state with explicit 🟡 carryover and detailed BACKLOG list, (c) re-scope the round.

**Rationale**: Round 2 + Round 3 both hit 3 D56 sequential passes; Round 3 then surfaced NEW 🔴s via 4-agent deep validation. This proves:
- (a) Standard D56 single-agent cycles have structural blind spots (cross-table column-name lift sub-class — HANDOFF Pitfall #9.5)
- (b) D56 has no explicit terminating criterion — ambiguity about when a round is "done"
- (c) Deep validation needs to compose with D56, not replace it

D72 codifies: keep iterating until convergence is demonstrated (3 clean) or escalate at 10. The "3 consecutive" requirement is stronger than "2 consecutive" because Pitfall #9 evidence shows drift can survive multiple passes; 3 in a row provides a robust convergence signal.

Alternatives considered:
- (a) **No termination rule** (status quo D56) — rejected: leaves ambiguity about when a round is done; encourages premature lock
- (b) **Hard cap at N cycles with no convergence rule** — too rigid; ignores empirical convergence
- (c) **2-consecutive clean** — too lenient given Pitfall #9 four-round evidence
- (d) **3-consecutive clean + 10 max (chosen)** — strong convergence signal + bounded total cost + architectural-review escape valve
- (e) **5-consecutive clean** — overly conservative; would inflate validation cost without proportional benefit

**Trade-offs accepted**:
- Validation cost rises at the margin (sometimes 3 clean cycles when 2 would have empirically sufficed). Acceptable given audit-grade pillar value.
- "Clean" definition is judgment-call at the margins (some 🟡s might be load-bearing vs backlog-eligible). Mitigation: validator MUST explicitly call out whether each 🟡 is blocking or backlog-eligible in their report.
- Cycles consume agent-tokens; max 10 cycles × up to 4 agents = up to 40 agent-runs per round. Acceptable for the value of avoiding production bugs.

**Affects**:
- Decisions: extends D55 (5-gate validation) and D56 (mandatory second-pass after 🔴) — those remain; D72 adds explicit termination rule
- Edge cases: none directly
- Runbooks: none
- Schema: none
- Code modules: none directly
- Skills: `udm-checks-and-balances` skill body extended with D72 convergence rule
- Docs: `CHECKS_AND_BALANCES.md` § "Iterative validation cycles" extended; `_validation_log.md` entries should include cycle count + consecutive-clean count toward convergence

**Reversibility**: Reversible — D72 is a discipline addition; reverting means removing the convergence rule. No code or schema impact.

**Risk delta** (per D61):
- ⬇️ DE-ESCALATED (pending substantiation): R11 (validation discipline drift) — explicit termination rule reduces "is this round done yet?" ambiguity. Per Pitfall #8 hedge: do NOT reduce score until first round actually converges under D72.

**Round 3 application** (as of D72 lock — cycle 4 time; see `CURRENT_STATE.md` for live state):
- Cycles so far: 4 (D56 first-pass, second-pass, third-pass + 4-agent deep validation round 1)
- Consecutive clean: 0 (D56 third-pass was clean but the deep-validation cycle reset the counter to 0 because it found 🔴)
- Remaining capacity: 6 cycles before architectural-review escalation
- Convergence target: 3 consecutive clean cycles from this point

**Round 3 application** (updated 2026-05-10 cycle 9 close per Reviewer U finding — D72 cycle count divergence regression):
- Cycles consumed: 9 (D56 first/second/third + 4-agent cycles 4/5/6/7/8/9)
- Consecutive clean: 0 (reset at cycle 9 by Reviewers U + W clerical 🔴 findings; cycle 8 was first all-clean batch)
- Remaining capacity: 1 cycle (cycle 10) — but mathematically INSUFFICIENT to reach 3-consecutive-clean target
- **Architectural review triggered** per D72 escalation rule. Options: (a) split spec, (b) accept current state with 🟡 carryover, (c) re-scope round. Decision pending pipeline-lead judgment.

**See also**:
- `docs/migration/CHECKS_AND_BALANCES.md` § "Iterative validation cycles" (will be updated to cite D72)
- `docs/migration/_validation_log.md` (each cycle entry now includes cycle count + clean-streak count)
- `docs/migration/03_DECISIONS.md` D55, D56 (this decision extends them; does not supersede)

---

## D73: Round 3 architectural-review decision — accept spec doc with 🟡 BACKLOG carryover (D72 escalation Option (b))

**Status**: 🟢 Locked (pipeline-lead architectural-review decision per D72 escalation rule 2026-05-10)
**Driver**: D72 ceiling reached at Round 3 cycle 9 (9 cycles consumed; 0 consecutive clean after cycle 9 reset; 1 cycle remaining mathematically insufficient to reach 3-consecutive-clean target). Per D72 escalation rule, pipeline-lead architectural-review judgment required.

**Pillar(s) served** (per D61):
- **Operationally stable**: explicit architectural-review decision prevents indefinite validation loop while preserving full audit trail
- **Audit-grade**: every reviewer agentId + finding + fix is logged in `_validation_log.md`; backlog carryover items are individually B-numbered with clear scope
- **Idempotent**: D72 escalation rule applied deterministically (10-cycle ceiling reached; convergence math evaluated; Option (b) selected with documented rationale)

**Decision**: Apply D72 escalation Option (b) — **accept current state of `phase1/03_core_modules.md` with explicit 🟡 BACKLOG carryover**. Flip spec doc status 🟡 RE-OPENED → 🟢 Locked with architectural-review citation. Constituent decisions D67-D71 remain 🟢 (unchanged).

**Carryover items** (all backlog-eligible per Reviewer T cycle 8 + Reviewer X cycle 9 independent classification): B63 (Tier 0 error-mode extension); B65 (release_snowflake_key definition); B66 (event_tracker god-module refactor); B67 (vault_client typed wrappers); B68 (sensitive_data_filter thread-safety choice); B70-B72 (ledger_step metadata footgun + compose example + None safety); B74 (BACKLOG re-sort polish); plus existing B47, B48, B49, B50, B54-B58.

**Rationale**: 6 4-agent deep-validation cycles (4-9) produced converging evidence:
1. **Pitfall #9 cross-table column-name-lift sub-class** identified cycle 4 — D56 3-pass blind spot
2. **Column-walk specialist (B73)** as structural fix — Reviewers M (cycle 7), Q (cycle 8), V (cycle 9) all found ZERO fresh drift
3. **Cycle 8 first all-clean 4-agent batch** demonstrated artifact CAN reach clean state under 4-agent scrutiny
4. **Cycle 9 findings categorically clerical** — cycle-count text drift, stale checklist labels — NOT structural module-spec issues
5. **Remaining items independently classified backlog-eligible** by 2 different reviewers in 2 different cycles

Continuing further cycles would risk infinite regress through aggregate-doc consistency churn without categorical value-add. The discipline produced 15+ real bug catches; marginal value of additional cycles is below cost.

**Alternatives considered** (per D72 escalation options):
- (a) Split spec into 7 layer-specific docs — rejected: structurally unnecessary; module specs are clean; would lose composition value
- (b) Accept current state with 🟡 carryover (chosen) — backed by 3 cycles of converging evidence
- (c) Re-scope round — rejected: would slow Round 4-6
- (d) Override D72 and continue cycle 10 — rejected: mathematically cannot reach 3-consecutive-clean; would be theater

**Trade-offs accepted**:
- 15+ deferred items in BACKLOG (B47-B74 range). Mitigated: each is B-numbered with scope, source citation, target round. Round 5 (Tests) close-out will systematically revisit Round 3's backlog.
- Spec doc lock includes acknowledged 🟡 — readers must consult BACKLOG. Documented in HANDOFF + CURRENT_STATE.
- D72 ceiling-without-convergence sets a precedent — architectural review may become a normal exit path rather than exception. Round 4 will be the test.

**Affects**:
- Decisions: D67-D71 remain 🟢 Locked (no change); D72 escalation rule empirically validated by first invocation
- Edge cases: none directly
- Runbooks: none
- Schema: none
- Code modules: 17 module specs in `phase1/03_core_modules.md` now 🟢 (with B-number carryover)
- Skills: `udm-checks-and-balances` skill can cite D73 as the canonical architectural-review escalation pattern
- Docs: HANDOFF §3 (+D73), §12 (Round 3 close-out row); CURRENT_STATE Recently completed; BACKLOG retains B-numbered items

**Reversibility**: Reversible — if Round 5 or later finds backlog items are blocking, re-open `phase1/03_core_modules.md` with new D-number per existing supersession discipline.

**Risk delta** (per D61):
- ⬇️ DE-ESCALATED (pending substantiation): R11 (validation discipline drift) — D72 escalation rule worked as designed (forced decision when cycles couldn't converge). Per Pitfall #8 hedge: do NOT reduce R11 score until Round 4 demonstrates clean exit under D72.
- 🆕 NEW: **R21 — Backlog carryover from Round 3 (15+ items) creates downstream risk if Round 5 (Tests) close-out doesn't systematically revisit.** Likelihood Medium × Impact Low = 2 ⚪. Mitigation: Round 5 acceptance criteria includes explicit B-item triage step covering B63-B74.

**See also**:
- `docs/migration/03_DECISIONS.md` D72 (the rule applied)
- `docs/migration/_validation_log.md` 2026-05-10 Round 3 D72 convergence cycles 4-9 (the evidence)
- `docs/migration/BACKLOG.md` B63-B74 (carryover items)
- `docs/migration/phase1/03_core_modules.md` (the locked artifact)
- `docs/migration/HANDOFF.md` §3 (D73 added) + §12 (Round 3 close-out row)

---

## D74. CLI exit-code contract (0 / 1 / 2 trichotomy)

**Status**: 🟢 Locked 2026-05-10
**Driver**: Round 4 (Tools) needs a canonical exit-code convention that Automic + operators consume uniformly across all 11 CLIs. Without an explicit contract, future tool authors return ad-hoc codes; Automic mis-categorizes results (escalates or under-escalates); operator mental model fragments.

**Decision**: Round 4 CLIs use a 3-code contract documented in `phase1/04_tools.md` § 1.1:
- **0**: Success (normal completion OR idempotent no-op short-circuit OR dry-run preview produced). PipelineEventLog row with `Status='SUCCESS'`. Always normal — operator takes no action
- **1**: Expected operational failure (nothing to process / dry-run found drift / Automic should re-run after operator intervention / warning-tier parity drift). PipelineEventLog row with `Status='FAILED'` + `ErrorMessage`. Operator review; not page-able
- **2**: Fatal error (config missing, GPG envelope decrypt failure, vault auth failure, FATAL exception class per D68). Stack trace in stderr. Operator must intervene; page-able

**Rationale** (per NORTH_STAR conflict-resolution rubric):
- **Operationally stable** — Automic consumes the contract uniformly; the trichotomy is small enough that operators memorize it and large enough that page-vs-review distinction is preserved
- **Audit-grade** — every CLI invocation writes a PipelineEventLog row with the exit code reflected in `Status`; audit trail is consistent across tools

**Pillar(s) served**: Operationally stable, Audit-grade

**Trade-offs accepted**:
- Unix conventional exit 130 (128+SIGINT) NOT honored — `KeyboardInterrupt` maps to exit 1 (operator review, not page). Decision tracked as B87 for future revisit if shell-composition becomes common
- 3 codes may be insufficient if future tools need granular failure classification (e.g. "user-fixable vs operator-fixable"); revisit if Round 5 testing surfaces friction

**Tier 0 enforcement** (per D67 + D77): every CLI tool's smoke test asserts the exception → exit-code mapping per § 1.8 boilerplate (`PipelineFatalError` → exit 2; `PipelineRetryableError` → exit 1; success → exit 0).

**Risk delta** (per D61):
- 🆕 NEW: **R22 — CLI exit-code drift** (Likelihood Low × Impact Medium = 3 ⚪). Status: added to RISKS.md at Round 4 close-out per B77 + Pitfall #8 discipline.

**See also**:
- `docs/migration/phase1/04_tools.md` § 1.1 (the contract)
- `docs/migration/phase1/04_tools.md` § 1.8 (the exception-handling wrapper that enforces the mapping)
- `docs/migration/03_DECISIONS.md` D68 (error class hierarchy that drives the mapping)
- `docs/migration/RISKS.md` R22 (the drift risk)

---

## D75. CLI argument naming + default semantics

**Status**: 🟢 Locked 2026-05-10
**Driver**: Round 4 introduces 11 CLI tools that share an operator-facing argument surface. Without canonical names + default semantics, every tool invents its own filter / dry-run / actor conventions; operator learning cost compounds.

**Decision**: Round 4 CLIs use canonical argument names documented in `phase1/04_tools.md` § 1.4:
- `--source` / `--table` for filters (matching `UdmTablesList.SourceName` / `TableName`)
- `--apply` opt-in for side-effecting tools (default = dry-run per § 1.2)
- `--all` to override absence-of-filter (must pair with `--apply` for fan-out prevention)
- `--batch-id` for pipeline-programmatic callers (skip auto-allocation)
- `--actor` defaults to operator (TTY) / automic (env var) / pipeline (explicit) per § 1.7 heuristic
- `--justification` REQUIRED for decrypt or override paths (per D6 + P8 audit)
- `--no-audit-event` for pipeline-programmatic invocations (avoid duplicate audit rows)
- `--verbose` / `--quiet` / `--json` for output control

**Rationale**: standardized argument surface reduces operator cognitive load; per-tool deviation requires explicit justification.

**Pillar(s) served**: Operationally stable, Audit-grade, Traceability

**Trade-offs accepted**: tool-specific arguments must use kebab-case consistent with the canonical names; no tool may redefine a canonical name with a different meaning.

**See also**:
- `docs/migration/phase1/04_tools.md` § 1.4 (the canonical argument table)
- `docs/migration/phase1/04_tools.md` § 1.7 (the actor TTY heuristic)

---

## D76. CLI audit-row contract

**Status**: 🟢 Locked 2026-05-10
**Driver**: Round 4 CLIs are operator-driven; the audit trail must be uniform so post-hoc analysis (compliance audits, incident response) can locate every CLI invocation. Round 3 § 6.3 `event_tracker.track()` is the primitive; Round 4 codifies the CLI-level usage.

**Decision**: Every Round 4 CLI invocation writes ONE `PipelineEventLog` row with:
- `EventType='CLI_<TOOL_NAME>'` (canonical naming — see B86 for CLAUDE.md inventory addition)
- `Metadata` JSON containing `argv`, `actor`, `dry_run`, `apply`, plus tool-specific fields (registry_id, source_filter, etc.)
- Sensitive fields redacted by `SensitiveDataFilter` (Round 3 § 6.1) before write — never plaintext PII

Pipeline-programmatic invocations (where the caller already has a BatchId + EventLog row) skip the CLI audit row via `--no-audit-event` flag (default OFF; ON when `--actor pipeline`) — prevents duplicate events.

**Rationale**: per D26 append-only audit posture; every operator action produces a discoverable trail; pipeline-programmatic invocations don't duplicate the parent's event row.

**Pillar(s) served**: Audit-grade, Traceability

**Trade-offs accepted**: introduces 11 new `CLI_*` EventType values to the existing inventory (CLAUDE.md L25 lists EXTRACT / BCP_LOAD / etc.); tracked as B86 for inventory documentation. Some tools (parquet_tier_review, detect_extraction_gaps) write BOTH a CLI envelope event AND the wrapped Round 3 module's per-row events — operator sees both in audit trail (acceptable; more information not less).

**See also**:
- `docs/migration/phase1/04_tools.md` § 1.5 (the contract)
- `docs/migration/03_DECISIONS.md` D26 (append-only audit posture)
- `docs/migration/03_DECISIONS.md` D31 (Power BI consumes PipelineEventLog)

---

## D77. CLI Tier 0 scaffold pattern

**Status**: 🟢 Locked 2026-05-10
**Driver**: Round 4 CLIs need build-time smoke coverage per D67 (locked at Round 3). Without a uniform Tier 0 scaffold, per-tool tests drift; CI gating becomes inconsistent.

**Decision**: Every Round 4 CLI tool has a `tests/smoke/test_tools_<name>.py` that:
- Runs in **<5 seconds** with NO external dependencies (no Docker, no real DB, no network — pure / mock only per D67)
- Asserts (a) module imports without error; (b) `python3 tools/<name>.py --help` returns exit 0 with non-empty stdout; (c) arg parser accepts the canonical argument set without raising; (d) `--dry-run` (or default-dry-run mode) does NOT call any side-effecting cursor; (e) `--apply` invokes the wrapped Round 3 module function (mocked) with expected positional + keyword args; (f) exception → expected exit code mapping per D74 — `PipelineFatalError` → exit 2; `PipelineRetryableError` → exit 1; success → exit 0

**Rationale**: uniform scaffold reduces test-authoring cost; CI gating becomes deterministic across tools.

**Pillar(s) served**: Operationally stable, Audit-grade

**Trade-offs accepted**: D77 lists 6 assertions; § 2 of `04_tools.md` initially listed 5 (B89 tracks the reconciliation). The assertion (f) exception → exit-code mapping is the strongest defense against D74 contract drift (R22 mitigation).

**Backfill obligation** (per B83): all 11 Round 4 CLI Tier 0 smoke tests must be authored at Round 6 deployment time; Round 4 specs include sketches.

**See also**:
- `docs/migration/phase1/04_tools.md` § 1.6 (the canonical assertion list)
- `docs/migration/03_DECISIONS.md` D67 (the parent Tier 0 discipline)
- `docs/migration/03_DECISIONS.md` D70 (6-tier test pyramid; Tier 0 is tier 0)

---

## D78. Round 4 spec doc architectural-review acceptance with BACKLOG carryover

**Status**: 🟢 Locked 2026-05-10
**Driver**: After 8 D72 validation cycles on `phase1/04_tools.md` (4 cycles 🔴 → cycle 5 ✅ → cycle 6 🔴 → cycle 7 ✅ → cycle 8 🔴), math infeasibility for 3-consecutive-clean convergence reached: cycles 9 + 10 remaining; need 3 consecutive clean = impossible. Per D72 escalation rule: architectural review.

**Decision**: Accept `phase1/04_tools.md` 🟢 Locked **with explicit 🟡 BACKLOG carryover** (B77-B107 = 30 items; B92 closed-in-cycle = 29 active). Round 5 (Tests) close-out must systematically triage each B-item. This is the **direct Round 3 D73 precedent applied to Round 4** — same Option (b) of D72's escalation menu.

**Rationale**: 8 cycles produced 19 real bug catches; the structural-drift surface (Pitfall #9 sub-classes 1-7 now documented) is exhausted as far as cycle-time-bounded review can detect. The cycle-6 + cycle-8 sleeper bugs were sub-class fresh-instances (invented `FileSizeBytes` column; wrong section cite § 5.3.5 vs § 5.4; invented § 2.1.10) — addressed inline; the remaining 🟡s are framing / clerical and don't block downstream rounds. **Locking now > locking never**. Round 5's systematic triage covers the carryover.

**Pillar(s) served**: Operationally stable (don't let validation cycle indefinitely), Audit-grade (the full 8-cycle audit trail is in `_validation_log.md`)

**Carryover items** (per `phase1/04_tools.md` § 5.2 + cycle 4 + cycle 6 + cycle 8 additions):
- B77 (R22 add to RISKS), B78 (3 new edge cases), B79 (SP-4 @AcknowledgmentOnly), B80 (2 new Automic jobs), B81 (CCPA SP authorship per B01), B82 (ops-channel client + Phase 0 deliv), B83 (Tier 0 backfill 11 tools), B84 (udm-test-author CLI extension), B85 (utils/errors.py base classes), B86 (CLI_* EventType family in CLAUDE.md), B87 (SIGINT/exit-130), B88 (--dry-run + --apply mutex), B89 (D77 5-vs-6 assertion reconciliation), B90 (invocation pattern edge case), B91 (F-next sub-states), B93 (SP-10 @CutoffOverride), B94 (SP-10 @CategoryFilter), B95 (Pitfall #9 keyword-only sub-class), B96 (SIGINT rationale note), B97 (SnowSQL cross-ref), B98 (F25 alert dispatcher edge case), B99 (SP-4↔SP-6 race window), B100 (Gate 5 label rename), B101 (RB-11 mislabel), B102 (Stage 1 read order), B103 (Round 3 § 2.2 contradiction), B104 (log_retention_cleanup batch-size), B105 (CYCLE_FAILED_OVER tracking), B106 (B101 line citation off-by-one), B107 (Pitfall #9 wrong-section-cite sub-class).

**Combined Round 3 + Round 4 carryover** (Round 5 mandate): 58 active items (29 Round 3 + 29 Round 4).

**Trade-offs accepted**:
- Carryover-risk per R23 (added at close-out) — Medium × Low = 2 ⚪ — mitigated by Round 5 acceptance criteria mandating systematic triage
- HANDOFF Pitfall #9 sub-class list grows 5 → 7 (B95 + B107) — increases producer self-check burden but improves catch rate

**Affects** (downstream):
- DECISIONS: D74-D77 lock alongside; D78 is the meta-decision that locks the SPEC
- Edge cases: B78 + B98 propose 4 new cases (F-next + P-next + I-next + F25)
- Runbooks: B101 surfaces RB-11 framing fix
- Schema: B79 + B93 + B94 propose Round 1 SP evolution for Round 7
- Code modules: 11 CLI specs in `phase1/04_tools.md` now 🟢 (with B-number carryover)
- Docs: HANDOFF §3 (+D74-D78), §12 (Round 4 close-out row); CURRENT_STATE Recently completed; BACKLOG retains B-numbered items

**Reversibility**: Reversible — if Round 5 or later finds carryover items are blocking, re-open `phase1/04_tools.md` with new D-number per existing supersession discipline.

**Risk delta** (per D61):
- ⬇️ DE-ESCALATED (pending substantiation): R11 (validation discipline drift) — Round 4 demonstrated clean exit under D72 (paralleling Round 3 D73 exit). Two consecutive rounds exiting cleanly per D72/D73 establishes discipline maturity. Per Pitfall #8 hedge: do NOT reduce R11 score until Round 5 also demonstrates clean exit or natural 3-consecutive convergence.
- 🆕 NEW: **R22 — CLI exit-code drift** (low score 3 ⚪; tracked via Tier 0 + D74 contract; mitigated structurally)
- 🆕 NEW: **R23 — Round 4 BACKLOG carryover** (low score 2 ⚪; mitigated by Round 5 systematic triage)

**See also**:
- `docs/migration/03_DECISIONS.md` D72 (the rule applied)
- `docs/migration/03_DECISIONS.md` D73 (the Round 3 precedent this parallels)
- `docs/migration/_validation_log.md` 2026-05-10 Round 4 D72 8-cycle entry (the evidence)
- `docs/migration/BACKLOG.md` B77-B107 (carryover items)
- `docs/migration/phase1/04_tools.md` (the locked artifact)
- `docs/migration/HANDOFF.md` §3 (D74-D78 added) + §12 (Round 4 close-out row)
- `docs/migration/RISKS.md` R22 + R23 (associated risk deltas)

---

## D79. Test data fixture canonical schema

**Status**: 🟢 Locked 2026-05-10
**Driver**: Round 5 (Tests) needs single source of truth for test fixture data structure across Tiers 1-3. Without canonical schema, fixture drift against Round 1 production schema risks Tier 3 + 4 tests passing against stale state while production schema evolves.

**Decision**: Test data fixture lives at `tests/fixtures/udm_test_fixtures/schema.sql` mirroring Round 1 DDL verbatim. Refresh required at every Round 1 schema change (Round 7 governance procedure includes fixture-regenerate step). Container: `mcr.microsoft.com/mssql/server:2022-CU14-ubuntu-22.04` (version-pinned per Round 6 § 7.10 / § 4.5 / § 5.4 / § 8.10 — `:latest` invites parity-drift class flagged by R5C1-5 advisory + R6C4 sleeper-bug review; CU14 is the canonical pinned version. dbt-sqlserver + SQLAlchemy test-suite precedent). Lifecycle managed via `testcontainers-python` Mssql module (session-scope container). State-leakage mitigation: SQLAlchemy-style transactional rollback per Tier 3 test.

**Pillar(s) served**: Operationally stable, Idempotent

**See also**: `phase1/05_tests.md` § 1.3; `phase1/01_database_schema.md` (canonical Round 1 DDL); R24 (proposed risk for schema drift)

---

## D80. Tier-0-to-Tier-1 transition discipline

**Status**: 🟢 Locked 2026-05-10
**Driver**: Tier 0 smoke tests (per D67) bloat if they absorb Tier 1 coverage. Need explicit boundary discipline preventing CI's first-stage gate from slowing.

**Decision**: Tier 0 smoke test stays at Tier 0 ONLY IF: runtime ≤5 seconds; no external dependencies; tests `(a)-(f)` canonical assertion set per D77; does NOT exhaustively cover error paths. When any constraint breaches, **promote to Tier 1** with explicit cross-reference. Pitfall #10 reminder: Tier 0 is smoke screen, NOT comprehensive test.

**Pillar(s) served**: Operationally stable

**See also**: `phase1/05_tests.md` § 1.6; D67 (parent Tier 0 discipline); D77 (CLI Tier 0 scaffold pattern)

---

## D81. Property-test shrinkage budget per module

**Status**: 🟢 Locked 2026-05-10
**Driver**: Hypothesis property tests need explicit budget tuning + reproducibility convention for CI.

**Decision**: Default `max_examples=200` per `pytest.fixture(scope='session')` (consistent with pandas; above SQLAlchemy's 50). Combinatorial-heavy modules (CDC engine, SCD2 engine, transition state graphs): `max_examples=1000` (consistent with numpy). Shrinkage budget: `deadline=timedelta(seconds=10)`. Pre-release: bump master idempotence property to `max_examples=5000`. **CI determinism**: Hypothesis profile uses `settings.register_profile('ci', derandomize=True, max_examples=200)` per R5C1-5 advisory — CI runs derandomized so failures reproduce across runs (avoids "passed yesterday but failed today" trap); local dev uses default randomized profile for broader coverage.

**Pillar(s) served**: Idempotent, Operationally stable

**See also**: `phase1/05_tests.md` § 5.10; `06_TESTING.md` Tier 2 section

---

## D82. Coverage thresholds per tier

**Status**: 🟢 Locked 2026-05-10
**Driver**: Per-tier coverage targets need explicit anchors so CI gating is deterministic and team-aligned.

**Decision**:
- Tier 0: 100% module-import success rate (28 of 28 modules + tools)
- Tier 1: ≥90% line coverage per module (idempotence-relevant fns: 100%)
- **Tier 2: 100% of declared properties pass shrinkage within budget** (Hypothesis is pass-or-fail per shrinkage, NOT stochastic — per R5C1-5 advisory; "≥80% pass rate" framing is a category error that risks operators normalizing genuine bugs as acceptable flake)
- Tier 3: ≥95% scenario pass rate per nightly (investigate >5% flake)
- Tier 4: 100% crash-boundary recovery
- Tier 5: 100% quarterly audit-question pass rate

**Pillar(s) served**: Audit-grade, Operationally stable

**See also**: `phase1/05_tests.md` § 1.5; D67 (Tier 0 discipline); D70 (6-tier pyramid)

---

## D83. Round 5 spec doc architectural-review acceptance — CONVERGENCE-CONFIRMED variant

**Status**: 🟢 Locked 2026-05-10
**Driver**: Round 5 5-cycle D72 validation campaign caught 26 cumulative 🔴 with trajectory 17→7→1→1→0. Cycle 5 broke the Pitfall #9 fix-fresh-instance pattern for the first time in 8 rounds (zero fresh-instance drift introduced by cycle 4 fixes). Cycle 4 sleeper-bug stress test cleared deepest available validation depth per `_reviewer_effectiveness.md`.

**Decision**: Accept `phase1/05_tests.md` 🟢 Locked with explicit 🟡 BACKLOG carryover (B108-B119 + § 9.2 Round 6 deferrals + § 9.3 Round 7 deferrals). **NEW PRECEDENT — convergence-confirmed acceptance** distinct from Round 3 D73 + Round 4 D78 math-infeasibility-acceptance:

| Variant | Trigger | Round 3 D73 | Round 4 D78 | Round 5 D83 |
|---|---|---|---|---|
| Math-infeasibility | 10-cycle ceiling reached without 3-consecutive-clean | ✓ cycle 9 | ✓ cycle 8 | n/a |
| Convergence-confirmed | Cycle ✅ + 0 fresh-instance drift + sleeper-bug stress depth exhausted | n/a | n/a | ✓ cycle 5 |

**Rationale**: Round 3 + Round 4 invoked architectural-review acceptance only when math became infeasible (forced). Round 5 invokes acceptance when convergence evidence is unprecedentedly strong:
1. Cycle 4 sleeper-bug stress (deepest depth available per `_reviewer_effectiveness.md`) found 1 🔴 + 2 🟡; cycle 5 confirms fix landed + ZERO fresh-instance drift — Pitfall #9 fix-fresh-instance pattern broken for first time in 8 rounds (D49 v2→v3 / Round 2 first-pass / Round 2 second-pass / Round 3 second-pass / Round 3 cycles 5-6 / Round 4 cycle 2 / Round 4 cycle 6 / Round 4 cycle 8 / Round 5 cycle 2-4 all had fresh-instance recurrences; Round 5 cycle 5 broke the chain)
2. 5 cycles remaining (6-10) for natural D72 convergence; marginal value of 2-3 more cycles vs cycle 4's depth + cycle 5's confirmation is low
3. Round 5 risk bounded by Round 3/4 D73/D78 acceptance (Round 5 cannot harbor canonical drift that Round 3/4 don't already contain)

**Pillar(s) served**: Operationally stable (don't iterate when ROI is low), Audit-grade (the 5-cycle audit trail in `_validation_log.md` substantiates acceptance)

**Carryover items** (Round 6 close-out triage adds to cumulative workload alongside Round 3 D73 + Round 4 D78 carryover):
- 9 items closed in Round 5 § 9.1 (B47/B48/B50/B83/B84/B91/B98/B99/B105)
- 24 items deferred to Round 6 § 9.2 (B58/B63/B65-B72/B85-B90/B96-B97/B100-B104/B106 + B69 promoted)
- 6 items deferred to Round 7 § 9.3 (B79/B80/B81/B82/B93/B94)
- 12 new BACKLOG items B108-B119 (closes B92 gap + advisory framings from R5C1-5)

**Risk delta** (per D61):
- 🆕 NEW: **R24** — Test-fixture canonical schema drift (Medium × Low = 2 ⚪). Per Pitfall #8 hedge: "NOT YET ADDED to RISKS.md — close-out task"
- 🆕 NEW: **R25** — Round 5 BACKLOG carryover (Medium × Low = 2 ⚪). Per Pitfall #8 hedge: "NOT YET ADDED to RISKS.md — close-out task"
- ⬇️ DE-ESCALATED (pending substantiation): **R19** (Tier 0 drift) — Round 5 § 3 catalog + § 3.4 verify_tier0_drift.py spec. Hedge: NOT reduce until first ~5 Tier 0 smoke tests authored AND verify_tier0_drift.py operational

**Pitfall #9 sub-class candidate**: R5 cycles 1-4 surfaced NEW bug class — process-discipline-failure (false-closure claims / wrong-doc-scope / stale-count propagation). 3 fresh-instance occurrences across cycles 1-4. Tracked as **B120 candidate** for HANDOFF §8 Pitfall #9 sub-class 9.i formalization at Round 6 close-out.

**See also**:
- `docs/migration/03_DECISIONS.md` D72 (the rule), D73 (Round 3 math-infeasibility precedent), D78 (Round 4 math-infeasibility precedent)
- `docs/migration/_validation_log.md` 2026-05-10 Round 5 D72 5-cycle entry
- `docs/migration/_reviewer_effectiveness.md` (sleeper-bug stress empirical evidence; column-walk 0% false-clean track record)
- `docs/migration/BACKLOG.md` B108-B119 (carryover items + 12 new)
- `docs/migration/phase1/05_tests.md` (the locked artifact)
- `docs/migration/HANDOFF.md` §3 (D79-D83 added) + §12 (Round 5 close-out row)
- `docs/migration/RISKS.md` R24 + R25 (associated risk deltas)

---

## D84. Deployment artifact contract — immutable git tag + rsync + GPG-signed manifest + atomic symlink swap

**Status**: 🟢 Locked 2026-05-10
**Driver**: Round 6 deployment workflow needs a deterministic, auditable artifact contract that supports reproducible deploys + rollback.

**Decision**: Each deploy is an immutable git tag (`v<MAJOR>.<MINOR>.<PATCH>-<env>`); rsync of the tagged tree to `/opt/pipeline/<tag>/`; GPG-signed `MANIFEST.sha256` verified post-rsync; **atomic symlink swap via `ln -s <tgt> current.new && mv -T current.new current`** (single `rename(2)` syscall — NOT `ln -sfn` which is unlink+symlink race window per Capistrano #346 + Deployer + Etsy canonical references); systemd restart triggers § 1.7 module startup sequence; pre + post-deployment checklist gates each environment promotion per D87.

**Pillar(s) served**: Audit-grade, Operationally stable, Idempotent

**See also**: `phase1/06_deployment.md` § 1.2 + § 1.4

---

## D85. Module startup sequence — credentials_loader → vault pool → parity verifier → ledger sweep → orchestration (closes B69)

**Status**: 🟢 Locked 2026-05-10
**Driver**: B69 Round 6 dependency (BACKLOG L62) — credentials_loader → vault pool config → server_parity_verifier → ledger startup sweep → orchestration sequence needed canonical inline definition; Round 6 deploy implementer needs this contract.

**Decision**: 5-stage fail-fast startup sequence per `phase1/06_deployment.md` § 1.7:
- **Stage 1**: credentials_loader (Round 3 § 3.1) — read `/debi/.env` + decrypt GPG envelope via gpg2 + TPM2 unseal + write Snowflake RSA key to `/dev/shm/snowflake_pk_<pid>` (D71)
- **Stage 2**: vault pool config (Round 3 § 2.3) — `configure_vault_connection_pool` + `SELECT 1` health check
- **Stage 3**: server_parity_verifier (Round 3 § 3.2 / Round 4 § 3.7) — read `parity_baseline.json` + compare to current server state per D65 severity tiers
- **Stage 4**: idempotency_ledger startup_recovery_sweep (Round 3 § 4.1) — `max_age_minutes=60` (canonical 1 hour); mark stale `IN_PROGRESS` rows as FAILED (per `CK_IdempotencyLedger_Status IN ('IN_PROGRESS','COMPLETED','FAILED')` — 3-value enum L445-446)
- **Stage 5**: orchestration begins — acquire PipelineExecutionGate per SP-3/SP-4

Each stage fails fast with documented exit codes per D74 (1=expected operational / 2=fatal). Stage failures abort the pipeline before subsequent stages run.

**Pillar(s) served**: Operationally stable, Audit-grade

**See also**: `phase1/06_deployment.md` § 1.7; closes B69

---

## D86. Three-environment deployment cadence — dev nightly / test daily / prod weekly Monday window

**Status**: 🟢 Locked 2026-05-10
**Driver**: Round 6 needs explicit deploy cadence + promotion gates per environment for predictable rollouts.

**Decision**:
- **dev**: nightly auto-deploy on `main` HEAD at 02:00 dev-server local (CI Tier 0+1+2 green required)
- **test**: daily auto-deploy after dev smoke pass + 4-hour test soak before next-step gate; failed test soak blocks prod promotion
- **prod**: weekly auto-deploy Monday window 02:00-05:00 after test soak (168h all-green) + pipeline-lead manual sign-off

Parity baseline (per D65) re-snapshotted at each environment after successful deploy. Failed prod deploy → AUTO-ROLLBACK per § 1.5 decision matrix.

**Pillar(s) served**: Operationally stable

**See also**: `phase1/06_deployment.md` § 1.5

---

## D87. Pre/post-deployment checklist contract — single PipelineEventLog audit row per promotion

**Status**: 🟢 Locked 2026-05-10
**Driver**: Round 6 deploy workflow needs auditable gating; per D55 + D62 every status change requires an audit trail.

**Decision**: Each environment promotion (dev → test, test → prod) writes ONE `PipelineEventLog` row with `EventType='DEPLOYMENT_<ENV>'` + `Status` ∈ enum L143-144 + `Metadata` JSON of every pre-check + post-check pass/fail with actor + justification. 12 pre-deployment checks + 10 post-deployment checks per § 1.6. Failed checklist short-circuits the promotion. Pipeline-lead reviews any FAILED-with-override at round close-out.

**Pillar(s) served**: Audit-grade, Operationally stable

**See also**: `phase1/06_deployment.md` § 1.6; D76 (CLI audit-row contract pattern extended to deploy events)

---

## D88. Round 6 spec doc architectural-review acceptance — CONVERGENCE-CONFIRMED variant (paralleling D83)

**Status**: 🟢 Locked 2026-05-10
**Driver**: Round 6 7-cycle D72 validation campaign caught 15 cumulative 🔴 with trajectory 10→1→1→2→1→1→0. **5-consecutive Pitfall #9 sub-class 9.i recurrences** (cycles 2/3/5/6/7) empirically confirm the structural pattern for which B120 candidate proposes formalization. Cycle 4 sleeper-bug stress (per R4C8 + R5C4 precedent) found 2 🔴 (B108-B114+B117 silent omission + § 10.1 Q4 mis-cite) — 3rd consecutive event-base for the sleeper-bug discipline.

**Decision**: Accept `phase1/06_deployment.md` 🟢 Locked with explicit 🟡 BACKLOG carryover (B120-B141 + § 12.2 Round 7 deferrals + close-out task list per § 11.4). **Convergence-confirmed variant per D83 precedent**:

| Variant | Trigger | Round 3 D73 | Round 4 D78 | Round 5 D83 | Round 6 D88 |
|---|---|---|---|---|---|
| Math-infeasibility | 10-cycle ceiling without 3-consecutive-clean | ✓ cycle 9 | ✓ cycle 8 | n/a | n/a |
| Convergence-confirmed | Trajectory demonstrates convergence + sleeper-bug stress depth exhausted + structural pattern empirically confirmed | n/a | n/a | ✓ cycle 5 (broke 8-round fix-fresh-instance pattern) | ✓ cycle 7 (5-consecutive 9.i recurrence formalizes structural pattern for B120) |

**Rationale**: Round 6 invokes acceptance because (a) cycle 4 sleeper-bug stress cleared deepest available validation depth + cycle 5 verification confirmed; (b) 5-consecutive 9.i recurrence across cycles 2/3/5/6/7 IS the empirical evidence base that B120 formalization requires — additional cycles would likely produce more 9.i fresh-instances at metadata level without changing the design-level convergence; (c) Pattern E from cycle 1 + sleeper-bug stress at cycle 4 + 6 cycles of fix-verify discipline = the structural pattern is now overwhelmingly substantiated for HANDOFF §8 sub-class 9.i formalization.

**Pillar(s) served**: Operationally stable (don't iterate when ROI is metadata-noise), Audit-grade (the 7-cycle audit trail in `_validation_log.md` substantiates acceptance), Idempotent (every fresh-instance closure is documented + B-numbered)

**Carryover items** (Round 7 close-out triage adds to cumulative workload alongside Round 3 D73 + Round 4 D78 + Round 5 D83 carryover):
- 29 items closed in Round 6 § 12.1 (28 deferred + 1 cycle-2 B63 promoted)
- 6 items deferred to Round 7 § 12.2 (B79/B80/B81/B82/B93/B94)
- 30 items audit-trail § 12.3 (already-closed at prior rounds)
- 13 items outside-scope § 12.4 (12 + B117 cycle-5 + 3 § 9.2 re-deferrals B66/B67/B71)
- 22 new BACKLOG items B120-B141 (10 cycle-1 + 3 cycle-2 + 4 cycle-3 + 4 cycle-4-sleeper-bug + 1 cycle-6-final-convergence)

**Risk delta** (per D61):
- 🆕 NEW: **R26** — Deployment artifact tampering (Low × High = 3 🟡)
- 🆕 NEW: **R27** — Pre/post-deploy checklist gate skipped under deadline pressure (Medium × Medium = 4 🟡)
- ⬇️ DE-ESCALATED (pending substantiation): **R02** (Round 0.5 spike untested) — § 5.6 first synthetic pipeline run + RB-12 close-out. Hedge: NOT reduce until first 3 production deploys actually succeed AND Round 0.5 spike outcomes are documented
- ⬇️ DE-ESCALATED (pending): **R08** (cross-server parity drift) — § 3.4 baseline + § 1.7 Stage 3 verifier + § 3.6 documented exceptions
- ⬇️ DE-ESCALATED (pending): **R23** (Round 4 BACKLOG carryover) — § 12 closes 27+ items; remaining items have clear Round 7 placement
- ⬇️ DE-ESCALATED (pending): **R25** (Round 5 BACKLOG carryover) — § 12 closes Round 5 § 9.2 24-item set with explicit 20 closed + 3 re-deferred + 1 promoted-and-closed reconciliation

**Pitfall #9 sub-class 9.i formalization (B120 candidate)**: R6 cycles 2/3/4/5/6/7 = 5 consecutive fresh-instance recurrences of process-discipline-failure class (trailing-summary-count drift + B-range stale references + invented B-number forward-cites + B-item silent-omission + wrong-section-cite). Empirically the strongest evidence base yet for HANDOFF §8 sub-class 9.i formalization. Round 6 close-out lands the formal sub-class wording per B120 + B136 + B141 (cumulative directive strengthening).

**See also**:
- `docs/migration/03_DECISIONS.md` D72 (the rule), D73 (Round 3 math-infeasibility precedent), D78 (Round 4 math-infeasibility precedent), D83 (Round 5 convergence-confirmed precedent)
- `docs/migration/_validation_log.md` 2026-05-10 Round 6 D72 7-cycle entry
- `docs/migration/_reviewer_effectiveness.md` (Pattern E 4th invocation; sleeper-bug stress 3rd event; column-walk 6 events)
- `docs/migration/BACKLOG.md` B120-B141 (22 new items + carryover triage)
- `docs/migration/phase1/06_deployment.md` (the locked artifact)
- `docs/migration/HANDOFF.md` §3 (D84-D88 added) + §8 (Pitfall #9 9.i formalized via B120) + §12 (Round 6 close-out row)
- `docs/migration/RISKS.md` R26 + R27 (associated risk deltas)

**Addendum 2026-05-11 (post-retrospective)**: D88's convergence-confirmed claim has a substantiation gap that D83's did not — **R5C5 was an independent clean-cycle verification (✅ CLEAN, 0 fresh-instance drift) AFTER the cycle-4 fixes landed**, but **R6C7 was the FIX-application cycle itself** (defining B141 in response to R6C6's invented forward-cite finding), NOT an independent post-fix verification. The trajectory `10→1→1→2→1→1→0` final `0` is producer self-attestation, not reviewer verdict. This is the exact gap class Pattern F (D89/D90/D91) catches via Trigger A (D-acceptance substantiation). Round 6 retroactive Pattern F audit (2026-05-11) confirms the gap; Pattern F is the structural fix for future rounds. D88 itself remains 🟢 Locked (the spec doc IS substantively converged at the design level — the gap is procedural, not content; future-round acceptance decisions will be Pattern-F-verified before lock per D89 going forward).

---

## D89. Pattern F discipline — tiered close-out cascade audit (Layer 1 deterministic script + Layer 2 paired-judgment agents)

**Status**: 🟢 Locked 2026-05-11 — first production invocation at Round 7 close-out empirically substantiated D89/D90/D91 thesis. Paired-agent Layer 2 surfaced 5-8 cascade gaps producer reflection + 8 cycles of Pattern E validation missed (NORTH_STAR D-list stale; PHASE_1_DEEP_DIVE_PLAN + 00_OVERVIEW + 02_PHASES Round-7-status drift; B146-B155 BACKLOG silent omission; validation log entry missing; B94 type-width drift). 3-event Pattern F evidence base (R6 retroactive + R6 unscoped + R7 first-production). 6-event cascade-audit specialty 0% false-clean.

**Driver**: Round 6 D88 close-out cascade left 7 structural gaps undetected (B140 false-closure / B86 CLAUDE.md gap / RB-12 forward-cite to non-existent body / HANDOFF §3 L108 stale B-range / 02_PHASES.md + PHASE_1_DEEP_DIVE_PLAN.md multi-round stale / B121 partial closure / D88 acceptance lacking clean verification cycle). Root cause: artifact-level work has 3-tier defense (Pattern E 5-agent + sleeper-bug stress + D72 convergence) but the round close-out cascade had ZERO independent verification — producer self-attests round 🟢 with no Gate-2 equivalent. The B120 5-step directive existed at Round 6 close-out and STILL did not enforce itself on its own cascade (Pitfall #9 9.i recurrence at close-out level).

**Decision**: **Tiered Pattern F discipline** — bring the round close-out cascade under the same level of independent-verification discipline that Pattern E + D55/D56 provide at the artifact level. Per `udm-brainstorm` Option 5 evaluation 2026-05-11:

- **Layer 1 (deterministic, mechanical)**: `tools/verify_cascade.py` script (per D91) runs the 3 text-matching triggers (C = stale references / D = forward-cite resolution / F = aggregate-doc Round-N freshness). 100% deterministic — zero agent variance on text classes.
- **Layer 2 (paired-judgment agents)**: `udm-cascade-auditor` agent (per D90) spawned as TWO independent instances in parallel. Each instance runs the 3 judgment triggers (A = D-acceptance substantiation / B = B-item closure-target audit / E = CLAUDE.md convention registration). Findings reports compared; agreement → cycle clean; disagreement → cascade fix-cycle.

**Why tiered (constraint: never trust 1 agent for cascade-level)**: Round 6 demonstrated single-agent self-attestation fails at cascade level. Pattern E evidence: column-walk specialty achieves 0% false-clean because it's narrowly-scoped + paired with cross-reference + internal-consistency reviewers; comprehensive-5-gate single-agent has confirmed false-clean (R4C5 + R4C7). Pattern F applies the same lesson: deterministic where possible (Layer 1 = no judgment variance); paired-independent where judgment is required (Layer 2). NO single agent has unilateral verdict on any trigger.

**Why not Option 1 (single-agent Pattern F)**: same producer-self-attestation failure mode as the original gap; one judge ≠ independent verification.

**Why not Option 2 (full 6-agent specialty)**: 6 agents per close-out > 5 agents in a full Pattern E cycle that validates an ENTIRE spec doc; structurally over-engineered for round-level discipline that should backstop artifact-level, not exceed it.

**Why not Option 3 (2-agent paired generalist on all 6)**: correlated blind spots — two generalist agents may share the same misses; loses the script's deterministic catch on text classes.

**Pillar(s) served**: Audit-grade (every cascade audit produces a structured findings report; cascade-level Gate-2 equivalent of D55), Operationally stable (Pattern F catches what producer self-attestation misses; recovers Round 6 cascade-gap blast radius), Idempotent (deterministic Layer 1 produces same verdict on same input)

**Composition with existing disciplines**:
- D55 (5-gate validation) — Pattern F is the round-level analog of Gate 2
- D56 (mandatory second-pass after 🔴) — Pattern F 🔴 → cascade fix-cycle → second Pattern F audit
- D60 (round close-out protocol) — Pattern F = Section 9 of close-out checklist (per `udm-round-closeout` skill v2)
- D62 (CCL) — Pattern F agents perform CCL Stage 1+2
- D72 (validation cycle termination rule) — Pattern F counts as ONE cycle in the ledger; if second Pattern F audit still 🔴 → architectural-review escalation per D73/D78/D83/D88 precedent
- D54 (hooks deferred) — when D54 returns, Layer 1's script logic converts directly to PreToolUse hooks; Layer 2 agents remain for judgment classes

**Cost framing**: 1 script invocation (deterministic; cacheable; seconds) + 2 agent invocations per close-out. LIGHTER than Pattern E (5 agents × N cycles per spec doc per round). Structurally correct: round-level discipline backstops artifact-level, not the other way around.

**Risk delta** (per D61):
- 🆕 NEW: **R28** — Round-level cascade self-attestation gap (Medium × High = 6 🔴 pre-Pattern-F; drops to Low × Medium = 2 ⚪ after D89/D90/D91 lock + Round 7 empirical evidence)
- ✅ MITIGATES (when locked): cascade-level recurrence of Pitfall #9 9.i (process-discipline-failure) — Layer 1's Trigger C + Trigger D scanning catches stale-range + forward-cite drift deterministically; Layer 2's Trigger B audit catches false-closure claims

**Pitfall #11 added to HANDOFF §8**: "Cascade-level self-attestation without independent verification". First evidence: Round 6 close-out 7 structural gaps. Structural fix: Pattern F (this decision).

**Lock criteria for 🟡 → 🟢**: 1 round of empirical Pattern F production evidence (Round 7 close-out is the first invocation). Same maturation timeline as Pattern E (R3 provisional → R4 empirical at R4C4 → 🟢 by Round 5).

**Reversibility**: HIGHLY REVERSIBLE. If Round 7 evidence shows Layer 2's paired agents have zero disagreement across 3+ rounds → can consolidate to single agent (Layer 1 script as the deterministic backstop). If Layer 1 script has high false-positive rate → can promote specific trigger classes to Layer 2 specialty agents. If D54 hooks return → migrate Layer 1 logic to hooks; Layer 2 remains.

**Cross-references**:
- `docs/migration/MULTI_AGENT_GUIDE.md` § Pattern F (doctrine + Layer 1 + Layer 2 composition + D72 counting rule)
- `.claude/skills/udm-round-closeout/SKILL.md` § Section 9 (close-out invocation pattern)
- `.claude/agents/udm-cascade-auditor.md` (Layer 2 agent definition; D90)
- `tools/verify_cascade.py` (Layer 1 script; D91)
- `docs/migration/HANDOFF.md` §8 Pitfall #11 (first-evidence)
- `docs/migration/RISKS.md` R28 (the risk Pattern F mitigates)
- `docs/migration/BACKLOG.md` B142+ (Round 7 close-out tasks for Pattern F first-production run)

---

## D90. `udm-cascade-auditor` agent definition (Pattern F Layer 2 paired-judgment)

**Status**: 🟢 Locked 2026-05-11 alongside D89 — Round 7 first-production paired invocation (INST1 `ad80b8cef05d8c3bd` + INST2 `a3ae7684dac80646f`) demonstrated paired-instance design works as specified; convergent + divergent findings handled per Pattern F doctrine; 0% false-clean across 6 cascade-audit events (R6 retroactive ×2 + R6 unscoped ×2 + R7 first-production ×2).

**Driver**: D89 mandates paired-judgment for Pattern F's 3 judgment-class triggers (A/B/E). Need a canonical agent definition that the close-out skill spawns as TWO independent instances.

**Decision**: Author `.claude/agents/udm-cascade-auditor.md` per the existing `.claude/agents/udm-design-reviewer.md` + `.claude/agents/udm-researcher.md` patterns. Operating model:
- CCL Stage 1+2+3 mandatory (per D62) — first content-substantive tool call MUST hit a Stage 1 doc
- Mandate: 3 judgment triggers (A = D-acceptance substantiation / B = B-item closure-target audit / E = CLAUDE.md convention registration)
- Output: structured findings report (per-trigger ✅/🟡/🔴 with file:line + matched-text + expected + actual + recommendation)
- Hard rule: invoked as PAIR; single-instance invocation violates D89 constraint and is rejected
- Independence: each instance does NOT read the paired auditor's report; orchestrator surfaces disagreements
- Tools: Read, Grep, Glob, Bash (matches udm-design-reviewer; needed for canonical-anchor extraction + reference resolution + ref grep)
- Model: sonnet (matches udm-design-reviewer; judgment-class work doesn't need opus, doesn't deserve haiku)

**Pillar(s) served**: Audit-grade (every judgment-class finding cites canonical source), Operationally stable (paired-independence prevents single-agent blind spots)

**Lock criteria**: same as D89 — Round 7 empirical evidence.

**Cross-references**:
- D89 (parent discipline)
- `.claude/agents/udm-cascade-auditor.md` (the agent definition itself)
- `.claude/agents/udm-design-reviewer.md` (pattern precedent for agent structure)
- `docs/migration/MULTI_AGENT_GUIDE.md` § Pattern F Layer 2

---

## D91. `tools/verify_cascade.py` deterministic script contract (Pattern F Layer 1)

**Status**: 🟢 Locked 2026-05-11 alongside D89 — Round 7 first-production: Layer 1 simulated via Grep (per Pattern F doctrine since python3 not available in current env); deterministic regex sweep + anchor extraction caught mechanical drifts complementing Layer 2 judgment-class catches. Script ready for CI environment with python3 available.

**Driver**: D89 mandates a deterministic layer for Pattern F's 3 mechanical-class triggers (C/D/F). Need a canonical script that scans cascade docs and emits machine-readable findings.

**Decision**: Author `tools/verify_cascade.py` per the existing `tools/verify_tier0_drift.py` precedent (D67 + R19 + B58). Contract:
- **Triggers covered**: C (stale references — B-range upper bounds drifted from BACKLOG max; "next round" labels on locked rounds; B-count claims drifted from actual), D (forward-cite resolution — every `RB-N` / `SP-N` / `B-N` / `D-N` / `R-N` reference resolves to canonical anchor; broken refs → 🔴 for RB/D, 🟡 for B/R/SP), F (aggregate-doc freshness — 02_PHASES.md Phase row + PHASE_1_DEEP_DIVE_PLAN.md Round stubs + HANDOFF §3 in-flight reflect current locked-Round per HANDOFF §3 lock list)
- **Canonical-anchor extractors**: BACKLOG.md → B-numbers via `**B(\d+)**` pattern; 03_DECISIONS.md → D-numbers via `^## D(\d+)` headers; RISKS.md → R-numbers via `| R(\d+) |` table rows; 05_RUNBOOKS.md → RB-numbers via `^## RB-(\d+)` headers; 01_database_schema.md → SP-numbers via `\bSP-(\d+)\b`
- **Output**: structured `CascadeReport` (text or JSON) — per-finding trigger / severity / file:line / rule / matched_text / expected / actual / recommendation
- **Exit codes** (per D74): 0 clean / 1 🟡 only / 2 🔴 (BLOCKING)
- **CLI args**: `--triggers C,D,F` (selective) / `--json --out path` / `--docs-only` (skip CLAUDE.md project root)
- **Dependencies**: stdlib only (re / argparse / json / pathlib / dataclasses) — no third-party so it runs in CI without env setup

**Pillar(s) served**: Audit-grade (deterministic catch on text classes; zero agent variance), Operationally stable (script-driven enforcement; long-lived asset that extends incrementally as new trigger classes emerge), Idempotent (same input → same verdict; cacheable)

**Lock criteria**: same as D89 — Round 7 empirical evidence + a clean script execution against the Round 7 cascade.

**Forward path (D54 hooks)**: Layer 1's check logic converts directly to PreToolUse hooks on `Edit`/`Write`. When D54 returns, the script remains as a non-hook-context fallback (e.g., CI runs) + as audit-trail generator; hook-backstopped enforcement at edit-time becomes the primary defense.

**Cross-references**:
- D89 (parent discipline)
- `tools/verify_cascade.py` (the script itself)
- `tools/verify_tier0_drift.py` (pattern precedent for tools/ structure)
- `docs/migration/MULTI_AGENT_GUIDE.md` § Pattern F Layer 1

---

## D92. Schema evolution governance procedure — forward-only additive + SchemaContract supersession

**Status**: 🟢 Locked 2026-05-11 (via Round 7 D94 architectural-review acceptance — math-infeasibility variant)

**Driver**: D40 (schema evolution governance + SchemaContract table) was locked in Round 1 v3 but never operationalized as a procedure. Round 7 was tasked with operationalization per Phase 1 plan. The Round 6 retrospective + Pattern F unscoped audit empirically confirmed that locked Round 1-6 artifacts have parallel-claim consistency requirements that ad-hoc changes break.

**Decision**: Forward-only additive schema evolution discipline per `phase1/07_schema_evolution_governance.md` § 1.1-§ 1.4. Permitted evolution paths:
- New SP parameter (additive; default value preserves caller compat); migration script + SchemaContract row + idempotent ALTER + `EventType='MIGRATION_<NAME>'` per D87
- New SP entirely (new SP-N number sequential); SchemaContract `ContractKey='sp_new_<name>'`; appended to Round 1 § "SP Index" via Round 7 close-out (NOT editing Round 1 body)
- New table column (additive); SchemaContract row + idempotent ALTER per Round 2 § 1.3 precedent
- New Automic job (operational config, not DDL); SchemaContract `ContractKey='automic_job'` + frozen-N count increment + `EventType='MIGRATION_AUTOMIC_INVENTORY'`
- New Phase 0 deliverable (one-time amendment to 02_PHASES.md; no PipelineEventLog row)

**NOT PERMITTED**: SP parameter rename / SP parameter removal / table column rename / table column removal. Reasons: ~50+ cross-references in locked Rounds 2-6 specs would break at unbounded cost. If removal absolutely required, supersede the entire SP with SP-N+1 via SchemaContract chain + ⚫ status on prior SP.

**Pillar(s) served**: Audit-grade (SchemaContract supersession audit trail), Operationally stable (governance procedure removes ad-hoc schema changes), Idempotent (every governance change writes idempotent migration script)

**Cross-references**:
- `phase1/07_schema_evolution_governance.md` § 1.1 (the canonical procedure)
- `phase1/01_database_schema.md` § 23 (SchemaContract canonical DDL L1188-1208)
- D40 (parent decision — schema evolution governance lock)
- D87 (audit-row contract pattern — MIGRATION_* EventType family)

---

## D93. Cross-doc cascade propagation requirement (formalizes Pattern F unscoped audit lesson)

**Status**: 🟢 Locked 2026-05-11 (via Round 7 D94 architectural-review acceptance)

**Driver**: Pattern F unscoped audit 2026-05-11 found parallel-claim mismatch — D89-D91 "locked" claim appeared at BOTH 02_PHASES.md L67 AND PHASE_1_DEEP_DIVE_PLAN.md L173. R6 retroactive fix landed at 02_PHASES.md but did not propagate to PHASE_1_DEEP_DIVE_PLAN.md. The pattern recurred at Round 7 cycle 1 + cycle 7 (Round 4 § 3.9 CLI consumer gap; § 11.1 BACKLOG line-cite drift) — empirically structural.

**Decision**: When any D-status / B-status / R-status / convention is changed in ONE doc, mandate cross-doc sweep for parallel claims per `phase1/07_schema_evolution_governance.md` § 1.5 (D93 mandate table). Pattern F discipline (D89/D90/D91) is the mechanism that enforces D93 — Layer 1 deterministic script catches mechanical parallel-claim drift; Layer 2 paired-judgment agents catch convention-level parallel-claim mismatches.

**Pillar(s) served**: Audit-grade, Operationally stable

**Cross-references**:
- `phase1/07_schema_evolution_governance.md` § 1.5
- D89/D90/D91 (Pattern F mechanism)
- HANDOFF §8 Pitfall #11 (cascade-self-attestation; the failure D93 prevents)
- R28 (round-level cascade self-attestation gap; D93 + Pattern F together mitigate)

---

## D94. Round 7 spec doc architectural-review acceptance — MATH-INFEASIBILITY variant (paralleling D73 / D78)

**Status**: 🟢 Locked 2026-05-11

**Driver**: Round 7 8-cycle Pattern E campaign produced 12+ → 5 → 1 → 0 → 1 → 0 → 3 → 0 🔴 trajectory. Cycle 5 sleeper-bug stress (mandatory final per R4C8 + R5C4 + R6C4 precedent) surfaced SP-12 contract gap; cycles 6-7-8 addressed substantive findings. Cycle 7 independent verification (per R5C5 precedent, NOT R6C7 self-referential closure) found cycle-6-introduced fix-fresh-instance bugs (Pitfall #9 8-event campaign — industrially confirmed structural pattern). Cycle 8 fix-application (current). **D72 ceiling math infeasibility**: 8 cycles consumed of 10; counter at 0; need 3-consecutive-clean within remaining 2 cycles (9, 10) = mathematically infeasible.

**Decision**: Accept `phase1/07_schema_evolution_governance.md` 🟢 Locked via D72 architectural-review acceptance per Round 3 D73 + Round 4 D78 math-infeasibility precedent. **D94 is the 3rd math-infeasibility acceptance (after D73 + D78); distinct from D83 + D88 convergence-confirmed variant.**

| Variant | Trigger | Round 3 D73 | Round 4 D78 | Round 5 D83 | Round 6 D88 | Round 7 D94 |
|---|---|---|---|---|---|---|
| Math-infeasibility | 10-cycle ceiling reached without 3-consecutive-clean | ✓ cycle 9 | ✓ cycle 8 | n/a | n/a | ✓ cycle 8 |
| Convergence-confirmed | Trajectory + sleeper-bug stress depth exhausted + structural pattern empirically confirmed | n/a | n/a | ✓ cycle 5 | ✓ cycle 7 | n/a |

**Carryover items** (Round 8 + later rounds + close-out cascade):
- 7 items closed in Round 7 § 11.1 (B79/B80/B81/B82/B93/B94/B128)
- 3 items deferred to Round 8 § 11.2 (B129 + B143 + B144)
- ~80+ items already-closed audit-trail § 11.3
- 11 items outside-Round-7 scope § 11.4
- 14 new BACKLOG items B146-B159 (10 primary + 4 R7C1-5 advisory)

**Risk delta** (per D61):
- 🆕 NEW: **R29** — SchemaContract supersession compounds (Low × Low = 1 ⚪; archival policy at 7-year retention per D30)
- 🆕 NEW: **R30** — D93 cross-doc cascade sweep may miss edge-case parallel claims rendered as prose-not-cite (Medium × Low = 2 ⚪; Pattern F Layer 2 paired agents catch judgment-class refs)
- ⬇️ DE-ESCALATED (pending): **R06** (Source schema changes during build) — § 1.1 supersession protocol formalizes; SchemaContract table operational per § 2.5 + § 3 + § 4 + § 5.4 row writes
- ⬇️ DE-ESCALATED (pending): **R18** (parity-exception expiration enforcement gap) — JOB_PARITY_EXCEPTION_NOTIFY per § 6.2 mitigates with 30-day pre-expiry alerts

**Pitfall #9 8-event campaign**: Round 7 confirms the structural pattern formalized via B120 sub-class 9.i has empirical strength. Every cycle introduced fresh-instance bugs (cycles 2/3/5/6/7) — exact 5-consecutive recurrences within Round 7 alone, paralleling R6's 5-consecutive pattern. **B144 sub-class 9.j candidate** (B-item status-render discipline) has 2-event evidence base (R6 retroactive + R7C7) — eligible for HANDOFF §8 formalization at Round 8 close-out.

**Cross-references**:
- `phase1/07_schema_evolution_governance.md` (the locked artifact)
- D72 (the rule applied)
- D73 (Round 3 math-infeasibility precedent)
- D78 (Round 4 math-infeasibility precedent)
- D83 / D88 (convergence-confirmed precedent — distinct variant)
- D89-D91 (Pattern F discipline — first production invocation at Round 7 close-out per § 13)
- `_validation_log.md` 2026-05-11 Round 7 D72 8-cycle entry
- BACKLOG B146-B159 (carryover items + Round 8 deferrals)
- RISKS R29 + R30 (associated risk deltas)

---

## D95. Self-improvement skill suite umbrella discipline

**Status**: 🟢 Locked 2026-05-11

**Driver**: Round 8 (Sub-Agent Self-Improvement Discipline; LAST Phase 1 round). After 7 rounds, validation refinements cost ~60 min/round + 3 user round-trips per optimization (user identifies → I propose → user approves → I implement). At ~2 optimizations per round across Rounds 1-7, the cumulative cost is ~7 hours over Phase 1. Round 8 inverts the loop: discipline observes itself via `_reviewer_effectiveness.md`; six analysis skills + one collector + one versioner propose deltas at every round close-out; user reviews ONCE per round + approves a batch per-delta within the session.

**Pillar(s) served** (per D61): Operationally stable (discipline self-maintains); Audit-grade (versioned changes); Traceability (ledger trends); Idempotent (auto-revert on regression); $120K/year ceiling (bounded compute — close-out only).

**Decision**: Lock the 7-skill self-improvement suite + 1 meta-doc as the canonical mechanism for sub-agent prompt evolution across rounds. Skills:
- **8.A `udm-retrospective-collector`** — auto-appends per-reviewer-event rows to `_reviewer_effectiveness.md` at every close-out
- **8.B `udm-specialty-tuner`** — reads ledger trends; proposes specialty prompt refinements (REFINE / RETIRE-OR-PAIR / NO ACTION)
- **8.C `udm-subclass-accumulator`** — scans round 🔴 findings; proposes new Pitfall #9 sub-class formalization at 2-event evidence threshold
- **8.D `udm-producer-checklist-evolver`** — identifies producer-missable bug classes; proposes directive strengthening
- **8.E `udm-cycle-cadence-optimizer`** — computes per-tier cadence calibration (Tier α/β/γ/δ); monitors carryover-compounding per B129
- **8.F `udm-agent-prompt-versioner`** — applies user-approved deltas; semver versioning + archive; auto-revert on regression
- **8.G `udm-cascade-audit-evolver`** — scans Pattern F findings; proposes new Layer 1 / Layer 2 trigger candidates (B143 implementation)

Meta-doc: `docs/migration/SELF_IMPROVEMENT_DISCIPLINE.md` documents the loop end-to-end + escape conditions (FREEZE the loop).

**Hard rules**:
1. Skills PROPOSE; user APPROVES; 8.F APPLIES (no autonomous prompt-rewrite)
2. Bounded compute — skills run at close-out only, NOT per cycle
3. Reversibility — every prompt change has an archived predecessor
4. Cross-doc consistency — skill outputs go through D55 5-gate validation like any other artifact
5. Minimum-event thresholds — ≥5 events for specialty recommendations; ≥2 events for sub-class formalization; ≥3 rounds for cadence proposals per complexity tier

**Rationale**: The discipline pattern matches recognized self-improving LLM systems (Self-Refine arXiv:2303.17651; OpenAI Self-Evolving Agents cookbook; ARIA arXiv:2507.17131), bounded by human-in-the-loop oversight (Anthropic Constitutional AI). Project-specific extension: every change is D-numbered + versioned + reversible.

**Trade-offs accepted**:
- One-round lag on auto-revert (regression caught at round N+1, not within deployment window) — deliberate bounded-compute tradeoff
- Six analysis skills add ~30 min to every round close-out (offset by ~60 min saved per round on optimization cycles)
- Manual user review session remains mandatory — discipline does NOT remove operator-in-the-loop

**Affects**:
- Decisions: D55 + D56 + D60 + D62 + D72 + D83 + D88 + D89-D91 (extends; doesn't replace)
- Edge cases: SI series (16 → 23 cases per Round 8 cycles 1-2)
- Runbooks: none (meta-tooling, not pipeline)
- Schema: none (project-doc-class artifacts)
- Code modules: 7 new `.claude/skills/udm-*/SKILL.md` + 1 meta-doc

**Reversibility**: reversible per skill (each skill's outputs reviewed independently); meta-discipline reversible by D-numbered decision if loop diverges per escape conditions.

**Risk delta** (per D61):
- 🆕 NEW: **R31** — Self-improvement loop introduces feedback-loop instability (Low × High = 3)
- 🟡 PROPOSED-PENDING-EVIDENCE: **R03** (single-engineer bus factor) — discipline preserves agent quality across personnel; de-escalation eligible after Phase 2 first-loop-invocation
- 🟡 PROPOSED-PENDING-EVIDENCE: **R11** (validation discipline drift) — 8.D producer-checklist-evolver actively counteracts drift; de-escalation eligible after evidence

**See also**: `phase1/08_sub_agent_self_improvement.md` (the spec doc) + `SELF_IMPROVEMENT_DISCIPLINE.md` (the meta-doc) + 7 SKILL.md files at `.claude/skills/udm-*/`.

---

## D96. Pitfall #9 sub-class 9.j formalization (B-item status-render discipline)

**Status**: 🟢 Locked 2026-05-11

**Driver**: B144 sub-class 9.j candidate reached 2-event evidence base (R6 unscoped Pattern F + R7 first-production Pattern F = 26 cumulative instances of `🟡 Open` leading badge + `**CLOSED YYYY-MM-DD**` inline annotation drift). Discipline-accumulation precedent set by 9.i formalization at R6 close-out (B120) per cumulative R5+R6 = 8-occurrence evidence base.

**Pillar(s) served**: Audit-grade (status-claim integrity); Traceability (badge-vs-annotation discipline catches state drift at scale).

**Decision**: Formalize sub-class 9.j inline at HANDOFF §8 sub-class accumulator alongside 9.a-9.i. Producer self-check directive: after ANY cycle-N or close-out edit that adds/closes a B-item, (1) verify leading badge matches inline annotation; (2) if mismatch, flip badge to canonical render. Add as Step 6 to existing 5-step 9.i audit (so the combined Pitfall #9.i + 9.j audit is 6 steps).

**Rationale**: Round close-out is high-velocity. Producer adds many B-items + closes some in rapid sequence. Inline-close annotation faster than badge-flip; badge left stale. Mass-flipping badges at end-of-close-out is itself error-prone (Pitfall #9.i mechanical-fix-introduces-fresh-instance). Pattern F Layer 2 paired-judgment catches 9.j cascade-level; 8.C subclass-accumulator skill auto-proposes future sub-classes at 2-event evidence.

**Trade-offs accepted**: 9.j adds one more producer self-check step per B-item modification. Marginal cost; high catch rate. Discipline accumulation continues — Round 9+ may surface 9.k+.

**Affects**:
- HANDOFF.md §8: 9.j formalized inline alongside 9.a-9.i
- BACKLOG: B144 status flips ⚫ Closed at Round 8 close-out cascade
- `.claude/skills/udm-subclass-accumulator/SKILL.md`: implementation reference

**Reversibility**: reversible if Round 9+ evidence contradicts (e.g., zero 9.j recurrences in Phase 2 indicates the pattern was Round-7-close-out-cascade-specific, not structural). Discipline accumulation doesn't lock irreversibly.

**Risk delta**: None (formalization of existing pattern; no new risk).

**See also**: `HANDOFF.md` §8 9.j entry; `phase1/08_sub_agent_self_improvement.md` § 12; B144.

---

## D97. Cycle-cadence-optimizer artifact-complexity tier mapping

**Status**: 🟢 Locked 2026-05-11

**Driver**: 7 rounds of empirical evidence on cycle-count vs convergence-outcome by artifact size. R2 = 1 cycle (Pattern E all-clean first-cycle). R3 = 9 cycles (80 KB, math-infeasibility). R4 = 8 cycles (85 KB, math-infeasibility). R5 = 5 cycles (75 KB, convergence-confirmed). R6 = 7 cycles (110 KB, convergence-confirmed). R7 = 8 cycles (50 KB, math-infeasibility 9.i-recurrence-driven). Round 8 = 9 cycles (~130 KB total, convergence-confirmed). Pattern emerges: artifact-size correlates with cycle-count but not deterministically; complexity tier defines initial cadence.

**Pillar(s) served**: Operationally stable (predictable cadence); $120K/year ceiling (bounded compute per tier).

**Decision**: 4-tier classification (project-derived taxonomy, NOT external SE standard):
- **Tier α**: Single-section <10 KB → D56 2-pass (R2 D62 dog-food precedent)
- **Tier β**: Multi-section 10-50 KB → Pattern E from cycle 1 + 2-3 verify (R2 Configuration precedent)
- **Tier γ**: Multi-section spec doc 50-100 KB → Pattern E from C1 + sleeper-bug stress mandatory final + Pattern F close-out (R3/R5/R7 mean 7.3 cycles)
- **Tier δ**: Mega-spec >100 KB OR mega-table inventory → Above + math-infeasibility OR convergence-confirmed acceptance (R6 + R8 precedent)

Minimum-event thresholds for proposing cadence calibration:
- ≥3 rounds in a tier before cadence-change proposed
- LOW confidence on tier with <3 events (retain prior tier's cadence)

**Rationale**: Per Round 8 8.E specialty + R8C9 verify clean: Tier γ cadence empirically fitting at mean 7.3 cycles std-dev 2.1. Tier δ has 2 events (R6 + R8); both invoked convergence-confirmed acceptance. Carryover-trend monitor per B129: R5 (12) → R6 (22) → R7 (10) → R8 carryover trajectory stable.

**Trade-offs accepted**:
- Tier classification is project-derived; not externally canonical
- Same-tier rounds may show high variance (R3 9 cycles vs R5 5 cycles, both Tier γ) — tier sets initial cadence, not final outcome
- Threshold guards rule out premature reclassification

**Affects**:
- `.claude/skills/udm-cycle-cadence-optimizer/SKILL.md` (implementation)
- `phase1/08_sub_agent_self_improvement.md` § 6.3 tier table
- D72 (10-cycle ceiling unchanged); tier sets cadence WITHIN D72

**Reversibility**: tier definitions revisable via D-numbered decision if Phase 2+ data demonstrates better classification.

**Risk delta**: None (operationalizes existing D72 within tier-specific cadence; no new risk class).

**See also**: `phase1/08_sub_agent_self_improvement.md` § 6 + D72 + B129.

---

## D98. Agent prompt versioning + change-log convention

**Status**: 🟢 Locked 2026-05-11

**Driver**: Self-improvement loop requires reversible prompt evolution. Without versioning, prompt deltas accumulate untracked; rollback requires manual reconstruction. Without changelog, reasoning behind a delta is lost when next round refines it again.

**Pillar(s) served**: Audit-grade (versioned changes); Traceability (changelog trail); Idempotent (rollback is mechanical).

**Decision**: Adopt semver `vMAJOR.MINOR.PATCH` for `.claude/agents/<name>.md` reviewer agent prompts.
- **MAJOR**: structural change (new mandatory tool; new mandatory output section; schema change in input/output contract)
- **MINOR**: directive addition (new producer self-check item; new sub-class entry; specialty-pairing change)
- **PATCH**: wording polish (example update; line-citation fix; terminology tightening)

Frontmatter convention:
```yaml
---
name: udm-<agent>
description: ...
tools: ...
model: ...
version: v1.2.1
last_updated: 2026-05-11
changelog: docs/migration/_agent_evolution/udm-<agent>-changelog.md
---
```

Archive: `.claude/agents/_archive/<name>-v<version>-<date>.md` (append-only).

Changelog: `docs/migration/_agent_evolution/<name>-changelog.md` (append-only); one row per version bump with: source skill, change_type, delta (before/after), rationale, tested-at, reversible-yes/no.

Skill 8.F (`udm-agent-prompt-versioner`) is the ONLY mechanism for writes to `.claude/agents/*.md` post-Round-8. Direct edits violate the discipline.

**Rationale**: Emerging convention per getmaxim.ai 2025 + PromptVer Dec 2025 + dasroot.net Feb 2026 — applying semver to system prompts is becoming canonical in prompt-engineering practice. Not yet ISO/IEEE-standardized, but operationally tested across the ecosystem.

**Trade-offs accepted**:
- Adds per-delta overhead (~1-2 min per applied delta for archive copy + changelog append)
- Forces operator discipline (no quick edits without versioning)
- Skill 8.F has central write authority — single-point-of-failure if 8.F bugs, but auto-revert path mitigates

**Affects**:
- `.claude/agents/udm-*.md` (4 existing — udm-design-reviewer, udm-test-author, udm-researcher, udm-cascade-auditor) — get version frontmatter at Round 8 close-out OR next prompt edit
- `.claude/agents/_archive/` (new directory, append-only)
- `docs/migration/_agent_evolution/<name>-changelog.md` (new per-agent files; created on first version bump)

**Reversibility**: full per-delta. Rollback is mechanical: copy `_archive/<name>-v<prior>-<date>.md` back to `.claude/agents/<name>.md`.

**Risk delta** (per D61):
- 🆕 NEW: contributes to R31 (feedback-loop instability) — auto-revert path mitigates
- ⬇️ DE-ESCALATED implicit: prior unversioned-prompt-edit risk

**See also**: `phase1/08_sub_agent_self_improvement.md` § 7 + `.claude/skills/udm-agent-prompt-versioner/SKILL.md` + SELF_IMPROVEMENT_DISCIPLINE.md.

---

## D99. Round 8 spec doc architectural-review acceptance — CONVERGENCE-CONFIRMED variant (paralleling D83 / D88)

**Status**: 🟢 Locked 2026-05-11

**Driver**: Round 8 9-cycle Pattern E + sleeper-bug stress + convergence-verification campaign. Trajectory: cycle 1 = 5 🔴 (Pattern E 5-agent) → cycle 3 = 1 🔴 (comprehensive-5-gate verify, 6th-consecutive Pitfall #9.i fix-fresh-instance) → cycle 5 = 3 🔴 (sleeper-bug stress; 5th-event 100% catch rate extended) → cycle 7 = 2 🔴 (final convergence verify caught cycle-6 mechanical-fix-ADDS-content sibling-miss) → cycle 9 = 0 🔴 (final convergence verify, post-cycle-8 fixes clean). 11 cumulative 🔴 caught + fixed across the campaign.

**Pillar(s) served**: Operationally stable + Audit-grade.

**Decision**: Accept `phase1/08_sub_agent_self_improvement.md` + 7 SKILL.md files + `SELF_IMPROVEMENT_DISCIPLINE.md` 🟢 Locked via D72 architectural-review acceptance per **Round 5 D83 + Round 6 D88 convergence-confirmed variant** (paralleling structure, distinct from Round 3/4/7 math-infeasibility variant). **D99 is the 3rd convergence-confirmed acceptance (after D83 + D88); distinct from D73/D78/D94 math-infeasibility variant.**

| Variant | Trigger | Round 5 D83 | Round 6 D88 | Round 8 D99 |
|---|---|---|---|---|
| Convergence-confirmed | Trajectory + sleeper-bug stress depth + fix-fresh-instance class caught + final-verify clean | ✓ cycle 5 | ✓ cycle 7 | ✓ cycle 9 |

**Carryover items**:
- 5 items closing at Round 8 close-out cascade § 11.1 (B129/B143/B144/B145/B155)
- 9 items deferred to Phase 2 § 11.2 (B146/B150-B153/B156-B159)
- ~30+ items audit-trail § 11.3 (closed in Rounds 3-7)
- 6 items outside-scope § 11.4 (B16-B18/B66/B67/B71)
- 2+ new BACKLOG items B160-B161 (Round 8 net-new)

**Risk delta** (per D61):
- 🆕 NEW: **R31** — Self-improvement loop feedback-loop instability (Low × High = 3 🟡)
- 🟡 PROPOSED-PENDING-EVIDENCE: **R03** + **R11** (de-escalation eligible after Phase 2 first-loop-invocation)

**Pitfall #9 6th-event sub-class 9.i campaign**: Round 8 cycle 3 marked the 6th-consecutive fresh-instance recurrence (R6 cycles 2/3/5/6/7 + R8 cycle 3 = 6 events across 2 rounds). Pattern continues industrially-confirmed.

**Sub-class 9.j formalization**: B144 candidate 2-event evidence base met (R6 unscoped + R7 first-production); landed inline at HANDOFF §8 per D96.

**Sleeper-bug stress 5-event empirical extension**: R4C8 + R5C4 + R6C4 + R7C5 + R8C5 = 5 events with 100% catch rate POST-CLEAN.

**Phase 1 completion**: Round 8 is the LAST Phase 1 round per `PHASE_1_DEEP_DIVE_PLAN.md`. With D99 lock, Phase 1 acceptance criteria check + Phase 2 (Pilot Cutover) handoff begins.

**Cross-references**:
- `phase1/08_sub_agent_self_improvement.md` (the locked artifact)
- D72 (the rule applied)
- D83 / D88 (convergence-confirmed precedent)
- D73 / D78 / D94 (math-infeasibility precedent — distinct variant)
- D95-D98 (constituent decisions locked alongside)
- D89-D91 (Pattern F discipline — mandatory at close-out cascade)
- `_validation_log.md` 2026-05-11 Round 8 D72 9-cycle entry
- BACKLOG B129/B143/B144/B145/B155 closures + B160-B161 net-new
- RISKS R31 + R03/R11 framing fix

---

## D100. Documentation supplement discipline (Round-N.5 mini-rounds)

**Status**: 🟢 Locked 2026-05-11

**Driver**: Post-Round-8 reflection identified that Round 1 schema doc + Round 2 § 1 + Round 3-7 specs collectively tell ~30% of the data pipeline story to a new engineer / dashboard author / DBA. The other ~70% — control-tier trigger semantics, Bronze/Stage example DDL, data flow walkthrough, ER diagrams, SchemaContract examples — was implicit or scattered across CLAUDE.md / 01_ARCHITECTURE.md / 09_VISUALS.md. Round 1.5 closed this gap with 5 documentation supplements (G1-G6).

**Pillar(s) served** (per D61): Audit-grade (every reference traces to canonical source); Traceability (cross-doc navigation enables onboarding); Operationally stable (dashboards + new engineers can self-serve).

**Decision**: Establish Round-N.5 mini-round pattern for documentation supplements that:
1. Are ADDITIVE only — never edit locked Round-N artifacts (per D40 + D92 forward-only)
2. Live as sibling files (`phase1/01a_*.md`, `phase1/01b_*.md`, etc.) — naming follows letter-suffix convention
3. Reference canonical sources as authoritative; supplement-vs-canonical contradiction = canonical wins
4. Pass D72 validation discipline (Pattern E from cycle 1 + sleeper-bug stress mandatory final + Pattern F at close-out per D89)
5. Use Tier α/β/γ/δ classification per D97 — combined supplement-cluster tier matches the largest single supplement
6. Get a D-number for the supplement-discipline itself (this decision is D100)

**Round 1.5 invocation specifics**:
- 5 supplements: G1 `phase1/01a_control_tables.md` (Round 1.5a, Tier β) + G3+G4 `phase1/01b_bronze_stage_example_ddl.md` (Round 1.5b, Tier α) + G6 `phase1/01c_data_flow_walkthrough.md` (Round 1.5c, Tier β) + G5 `phase1/07a_schema_contract_examples.md` (Round 1.5d, Tier α) + G2 ER diagrams in `09_VISUALS.md` (Round 1.5e, Tier α)
- Combined cluster ~80 KB → Tier β-borderline; cycle ceiling 10
- 6-cycle Pattern E campaign: Cycle 1 (5-agent, 11 🔴) → Cycle 2 (fix) → Cycle 3 (comprehensive verify, 3 🔴 fix-fresh-instance) → Cycle 4 (fix) → Cycle 5 (sleeper-bug stress, 8 🔴) → Cycle 6 (fix). Trajectory 11→3→8→cycle 7+. Total 22 cumulative 🔴 caught.
- **D101 acceptance**: math-infeasibility variant per D73/D78/D94 precedent — combined supplement-cluster could not converge to 3-clean within D72 ceiling due to canonical-source-drift volume in ER diagrams; remaining work tracked as B173 (comprehensive ER canonical sweep) + B166-B172 + I24

**Rationale**: Without this discipline, future schema-story gaps will recur (every new round adds spec content but doesn't address navigability + canonical-source-completeness gaps). Documenting Round-N.5 as a named pattern lets future rounds invoke it explicitly when needed.

**Trade-offs accepted**:
- Adds doc-count overhead — each Round-N may spawn 1-5 supplements at N.5
- Validation overhead scales with supplement count (each supplement walks 5 gates)
- Supplement-cluster tier classification may not perfectly fit per-doc effort

**Affects**:
- Decisions: D40 + D92 (forward-only additive — supplements respect locked-artifact discipline)
- Edge cases: I24 newly proposed (Multiple active SchemaContract rows)
- Runbooks: none directly; future RB-future may emerge per supplement work
- Schema: none (supplements are documentation-only)
- Code modules: none directly

**Reversibility**: reversible per-supplement (each is its own doc; can be deprecated). Discipline itself reversible via D-numbered decision.

**Risk delta** (per D61):
- 🆕 PROPOSED-LOW: documentation supplement count grows unbounded — track via B-future at close-out
- ⬇️ DE-ESCALATED implicit: schema-story-incompleteness risk (was implicit in R28 mitigation)

**See also**: `phase1/01a_control_tables.md` + `phase1/01b_bronze_stage_example_ddl.md` + `phase1/01c_data_flow_walkthrough.md` + `phase1/07a_schema_contract_examples.md` + `09_VISUALS.md` § ER diagrams + D101 (Round 1.5 acceptance) + GLOSSARY (Round-N.5 entry).

---

## D101. Round 1.5 documentation supplement architectural-review acceptance — MATH-INFEASIBILITY variant (paralleling D73 / D78 / D94)

**Status**: 🟢 Locked 2026-05-11

**Driver**: Round 1.5 6-cycle Pattern E campaign produced trajectory 11→3→8 with cumulative 22 🔴 across cycles 1+3+5. Cycle 5 sleeper-bug stress surfaced 8 substantive findings (largest sleeper-bug catch in project history) including comprehensive ER-diagram canonical-source drift across 9 tables. Cycle 6 fix-application addressed highest-impact items but the 9-table ER canonical sweep is too large to fold into remaining D72 cycle budget (~3-4 cycles needed for comprehensive walk vs. 4 cycles remaining within ceiling).

**Decision**: Accept the Round 1.5 supplement cluster (5 docs) 🟢 Locked via D72 architectural-review acceptance per Round 3 D73 + Round 4 D78 + Round 7 D94 math-infeasibility precedent. **D101 is the 4th math-infeasibility acceptance (after D73 + D78 + D94); distinct from D83 + D88 + D99 convergence-confirmed variant.**

| Variant | Trigger | Round 3 D73 | Round 4 D78 | Round 5 D83 | Round 6 D88 | Round 7 D94 | Round 8 D99 | Round 1.5 D101 |
|---|---|---|---|---|---|---|---|---|
| Math-infeasibility | Convergence math-infeasible OR canonical-source-sweep scope-exhausting | ✓ cycle 9 | ✓ cycle 8 | n/a | n/a | ✓ cycle 8 | n/a | ✓ cycle 6 |
| Convergence-confirmed | Trajectory + sleeper-bug + final-verify clean | n/a | n/a | ✓ cycle 5 | ✓ cycle 7 | n/a | ✓ cycle 9 | n/a |

**Carryover items (B-numbers; new from Round 1.5)**:
- **B166**: Verify `SchemaName` column existence in production `UdmTablesColumnsList`
- **B167**: UPDATE trigger on `UdmTablesList.IsEnabled` (or Python-side audit alternative — see Pitfall #9 sub-class drift discussion)
- **B168**: Permanent-retire runbook for UdmTablesList row + Stage/Bronze table drop
- **B169**: Advisory lock on `UdmTablesList` row UPDATEs (concurrent operator UPDATEs race)
- **B170**: UNIQUE constraint on active `SchemaContract` rows per (SourceName, ObjectName, ColumnName, ContractKey)
- **B171**: `SupersededBy` circular-reference detection in SchemaContract
- **B172**: Operator-facing supplement for V-4 defensive Bronze query pattern (currently in CLAUDE.md only)
- **B173**: Comprehensive ER-canonical-sweep across `09_VISUALS.md` § ER diagrams — 9 tables flagged with column-name drift per R1.5C5 sleeper-bug catches (PromotionLock, MaintenanceWindow, PipelineExtraction, DeleteEvaluationAudit, ExtractionGapLog, TableEnablementLog, HealthCheckLog, ExtractionRangePolicy, LatenessProfile)
- **B174**: SP-9 parameter-name reconciliation — Python wrapper uses `max_age_minutes=60` but canonical SP-9 signature is `@MaxAgeHours INT = 4`; verify production-code alignment
- **B175**: 09_VISUALS.md PromotionLock + MaintenanceWindow + PipelineExtraction et al. column-name drift (compounded with B173)

**Edge case added**: **I24** — Multiple active SchemaContract rows for same (SourceName, ObjectName, ColumnName, ContractKey) — mitigated by B170 once implemented.

**Empirical findings extended**:
- Pitfall #9 sub-class 9.i 7th-event campaign continues (R6 cycles 2/3/5/6/7 + R8 cycle 3 + R8 cycle 7 + R1.5 cycle 3 = 7 events). Pattern industrially confirmed at non-coincidental confidence.
- Sleeper-bug stress 6-event 100% catch rate extended (R4C8 + R5C4 + R6C4 + R7C5 + R8C5 + R1.5C5). R1.5C5 found 8 🔴 — largest single sleeper-bug catch yet.
- Math-infeasibility now 4-event precedent (R3 + R4 + R7 + R1.5); convergence-confirmed 3-event precedent (R5 + R6 + R8). Both variants industrially supported.

**Risk delta** (per D61 + Pitfall #8):
- 🟡 PROPOSED-PENDING-EVIDENCE: **B173** ER canonical sweep affects R12 (documentation drift); de-escalation eligible after sweep completes
- No new R-numbers; existing risk surface mitigated by B-number assignment

**Pattern F at close-out**: 3rd production Pattern F invocation; lock criteria for R28 extended-mitigation evidence per D89/D90/D91 doctrine.

**Cross-references**:
- 5 Round 1.5 supplement docs (the locked artifacts)
- D72 (the rule applied)
- D73 / D78 / D94 (math-infeasibility precedents)
- D83 / D88 / D99 (convergence-confirmed precedent — distinct variant)
- D100 (Documentation supplement discipline — locked alongside)
- D89/D90/D91 (Pattern F discipline; 3rd production invocation at this close-out)
- `_validation_log.md` 2026-05-11 Round 1.5 D72 6-cycle entry
- BACKLOG B166-B175 + I24 carryover

### D101 addendum (2026-05-11 post-backlog-batch per Pattern F INSTANCE 2 X3 + B177 closure)

**Math-infeasibility sub-variant taxonomy** (extended after R1.5 case):

1. **Sub-variant α — 3-clean-ceiling-infeasibility** (R3 D73 / R4 D78 / R7 D94): D72 10-cycle ceiling reached with insufficient cycles remaining to achieve 3-consecutive-clean convergence. Typical trigger: persistent fix-fresh-instance recurrence pattern (Pitfall #9.i).
2. **Sub-variant β — scope-exhausting deferral** (R1.5 D101): D72 cycles remain but the remaining work (e.g., comprehensive canonical-source sweep across N artifacts) would require more cycles than remain within ceiling. Distinct from α — convergence is feasible BUT scope > budget. Typical trigger: Round-N.5 supplement-cluster surfaces a cross-artifact discipline gap that scales with N artifacts.

Both sub-variants are valid D72 escalation paths per D73 + D78 + D94 + D101 precedent. The acceptance discipline is the same (B-item carryover; explicit deferral with target round / phase).

Total math-infeasibility precedent: 4 events (D73 R3 α + D78 R4 α + D94 R7 α + D101 R1.5 β). Total convergence-confirmed precedent: 3 events (D83 R5 + D88 R6 + D99 R8). Both variants industrially supported.

---

## D102. AES-256-GCM encryption pinning for tokenization vault

**Status**: 🟢 Locked 2026-05-11

**Driver**: Phase 0 deliverable 0.4 finalization in the context of the company merger. The merger requires explicit mask/unmask capability with a documented algorithm choice. Round 1 § 16 `PiiVault.EncryptedPlaintext BINARY` left the encryption algorithm unspecified — D102 pins it.

**Pillar(s) served** (per D61): Audit-grade (algorithm explicitly named); Traceability (operators + auditors can verify); Operationally stable (no algorithm ambiguity at implementation time).

**Decision**: All `PiiVault.EncryptedPlaintext` storage uses **AES-256-GCM** (authenticated encryption with associated data). The BINARY column stores: `nonce(12 bytes) || ciphertext(N bytes) || auth_tag(16 bytes)` concatenated. Python implementation per Round 3 `pii_tokenizer.py` + `pii_decryptor.py` uses `cryptography.hazmat.primitives.ciphers.aead.AESGCM`. Encryption key is derived from the TPM2-sealed master key per D64 (no separate KMS dependency).

**Rationale**:
- AES-256-GCM is NIST-recommended (SP 800-38D) for new systems
- Authenticated mode prevents silent ciphertext modification (vs CBC which requires separate MAC)
- Python `cryptography` library is the canonical implementation; widely audited
- 12-byte nonce + 16-byte auth tag overhead is acceptable (28 bytes per value)
- Compatible with future migration to commercial KMS via wrapping (D14)

**Trade-offs accepted**:
- 28-byte fixed overhead per encrypted value (small for typical PII sizes ~10-200 bytes)
- Nonce must be unique per (key, plaintext) — Python implementation uses 12-byte random nonce per encryption (collision probability negligible at row volumes)
- Key rotation requires re-encryption — handled via D14 future migration path

**Affects**:
- Decisions: D6 (in-house tokenization vault — algorithm now pinned), D64 (GPG envelope — encryption key derivation), D14 (KMS migration trigger)
- Edge cases: V1-V10 (vault provenance); P-series (PII handling)
- Runbooks: RB-3, RB-4 (decryption procedures use SP-2)
- Schema: Round 1 § 16 `PiiVault.EncryptedPlaintext BINARY` (column unchanged; algorithm clarified per D102)
- Code modules: Round 3 `pii_tokenizer.py` + `pii_decryptor.py`

**Reversibility**: hard — changing algorithm requires re-encrypting all stored vault rows. Document migration path in RB-future if needed.

**Risk delta** (per D61):
- ⬇️ DE-ESCALATED: ambiguity around encryption choice (was implicit in spec; now pinned)

**See also**: `phase1/01_database_schema.md` § 16 PiiVault + Round 3 § 2 pii_tokenizer + D64 + D6.

---

## D103. Claude Code security model — `/debi` working-directory boundary + multi-layer defense

**Status**: 🟢 Locked 2026-05-11

**Driver**: Phase 0 deliverable 0.12 + user-stated strict security policy. Claude Code (this assistant) is used for dev work but must NEVER access production credentials or sensitive paths. Threat surface concentration: dev environment (where Claude operates) is the priority protection target — NOT prod (which is isolated by image-bake policy).

**Pillar(s) served** (per D61): Audit-grade (every Claude tool call logged); Operationally stable (deny-rule enforcement); $120K/year ceiling (no commercial endpoint security spending — RHEL-native tools only).

**Decision**: Multi-layer defense-in-depth model:

### Threat-surface inversion (priority: dev > test > prod)

| Environment | Claude Code installed? | Real credentials? | Protection focus |
|---|---|---|---|
| **Dev** (workstation) | ✅ Yes — operates in `/debi` only | ❌ NEVER on disk | **Maximum — this is the threat surface** |
| **Test** (RHEL) | ❌ No (image-bake enforced via RB-12) | ✅ Test-only credentials | Standard RHEL hardening |
| **Prod** (RHEL) | ❌ No (image-bake enforced) | ✅ Prod credentials, TPM2-sealed | Standard RHEL hardening + restricted access |

### Layered defense (dev environment)

**L1 — `/debi` working-directory boundary**: Claude's allowed scope is `/debi` project directory ONLY. All credentials live OUTSIDE `/debi`.

**L2 — `.claudeignore`**: ignore patterns for all credential paths including `/etc/pipeline/**`, `/home/**`, `/root/**`, `~/.ssh/**`, `~/.gnupg/**`, `~/.pipeline/**`, `~/.aws/**`, `~/.kube/**`, `/dev/shm/snowflake_pk_*`, `C:/ProgramData/Pipeline/**`, `C:/Users/*/AppData/Local/Pipeline/**`, `*.gpg`, `*.pem`, `*.key`, `**/.env`, etc.

**L3 — `.claude/settings.local.json` `permissions.deny`**: enforced rules covering Read + Bash + PowerShell tool calls against all credential paths. Overrides `bypassPermissions` mode per Claude Code semantics.

**L4 — No real credentials on dev disk**: dev uses fake values in `.env.example`; Tier 1 tests use mocks; Tier 3 integration tests run on test environment (where Claude is not installed); engineers SSH into test for credential-dependent work, never copy creds to dev.

**L5 — Filesystem ACLs**: NTFS ACLs on Windows / POSIX ACLs on Linux for per-user explicit deny. `setfacl -m u:<dev-user>:--- /etc/pipeline/credentials.json.gpg`.

**L8 — OS-native credential storage** (dev side, if needed for interactive debugging): Windows DPAPI; Linux kernel keyring via `keyctl`. NEVER plaintext files on dev disk.

### Layered defense (test + prod)

**L9 — auditd logging** (RHEL-shipped, vendor-supported): every file access on credential paths logged to `/var/log/audit/audit.log`. Quarterly review per MAINTENANCE.md.

**L10 — systemd-creds + TPM2 sealing** (per D64): production credentials only readable by the systemd unit context.

**L11 — SELinux MAC** (RHEL-shipped, enabled per Phase 0 0.11 confirmation): default RHEL Mandatory Access Control framework. Document configuration for engineers unfamiliar with RHEL.

**L12 — Network isolation**: test + prod have no outbound internet except Snowflake + source DB endpoints. Claude Code API calls would be network-blocked even if Claude were installed.

**L13 — Image-bake policy (RB-12 enforcement)**: test + prod OS images explicitly exclude Claude Code binary. RB-12 deployment checklist verifies `which claude-code` returns nothing.

### `.env` location migration

Per this decision, `.env` files are MOVED out of `/debi`. New canonical location: `/etc/pipeline/.env` (system-managed; owned by `pipeline:pipeline`; mode `0400`). This supersedes the prior CLAUDE.md convention of `/debi/.env`. Migration steps for existing production code tracked as **B182** (`.env` migration runbook; WSJF 4.0 — pipeline cannot deploy with credentials in `/debi`).

### What is NOT used (per user security policy)

- ❌ AppArmor (open source — banned by policy)
- ❌ Commercial endpoint security (CrowdStrike / McAfee / Microsoft Defender for Endpoint / Trellix / etc. — no spending on commercial options per policy)
- ❌ Pre-commit hooks that are open-source-only (gitleaks / detect-secrets / etc. — no separate OSS installs unless RHEL-shipped)
- ❌ Secrets manager (HashiCorp Vault / AWS Secrets Manager / Azure Key Vault — Phase 5+ candidate but no current commitment)

### What IS used (per user policy)

- ✅ RHEL-shipped tools: SELinux + auditd + systemd-creds + POSIX ACLs + kernel keyring
- ✅ Microsoft Windows-built-in: NTFS ACLs + DPAPI + Credential Manager (dev workstations)
- ✅ Working-directory boundary + `.claudeignore` + `permissions.deny` (Claude Code-native; no installs)
- ✅ Operational discipline: no creds on dev disk; SSH into test/prod for credential-dependent work

**Rationale**: Per user-stated strict security policy + zero commercial spending budget, defense is built from RHEL-native tools + Claude Code-native mechanisms + operational discipline. Working-directory boundary is the primary architectural defense; OS-level perms + `.claudeignore`/`permissions.deny` provide enforcement; SELinux + auditd provide kernel-level enforcement + detection on test/prod.

**Trade-offs accepted**:
- Engineers cannot use Claude on test/prod for debugging — must SSH manually
- Dev workflows can't include interactive credential access (use `.env.example` placeholders)
- No commercial endpoint protection redundancy (relies on RHEL-native + OS perms)

**Affects**:
- Decisions: D52 (bypassPermissions mode) + D53 (.claudeignore baseline) + D54 (hooks deferred) + D64 (GPG envelope + TPM2)
- Runbooks: RB-12 (deployment) extended with image-bake "no Claude on test/prod" check
- Schema: none directly
- Code modules: none directly
- Configuration: `.claudeignore` + `.claude/settings.local.json` updated 2026-05-11
- New doc: `docs/migration/SECURITY_MODEL.md` (canonical reference for engineers unfamiliar with RHEL setup)

**Reversibility**: reversible per layer. Discipline self-maintains through code review + quarterly audit.

**Risk delta** (per D61):
- 🆕 NEW: **R32** — Claude Code accidentally accesses production credentials (Low × High = 3 🟡 pre-mitigation; reduces to Low × Medium = 2 ⚪ post-mitigation via L1-L13 defense-in-depth)
- ⬇️ DE-ESCALATED: implicit credential-leakage-via-developer-tooling risk

**See also**: `docs/migration/SECURITY_MODEL.md` (canonical reference) + `.claudeignore` + `.claude/settings.local.json` + RB-12 image-bake check.

---

## D104. Pilot table selection — `DNA.osibank.ACCT` (1.2M rows)

**Status**: 🟢 Locked 2026-05-11

**Driver**: Phase 0 deliverable 0.7 closure. Pipeline team + consumer reps selected ACCT as the pilot table for Phase 2 cutover.

**Pillar(s) served** (per D61): Operationally stable (Phase 2 has a concrete target); Audit-grade (selection rationale documented).

**Decision**: Phase 2 (Pilot Cutover) operates on `DNA.osibank.ACCT` as the first table to migrate to the new pipeline. 1.2M rows — slightly above the original "<1M rows" pilot suggestion but within tractable single-day extraction limits (~1-3 minute extracts; CDC + SCD2 in-memory comfortably under 1 GB).

**Rationale**:
- ACCT is the canonical example throughout planning docs (CLAUDE.md "Table Naming Conventions", Round 1.5b Bronze+Stage DDL example, Round 1.5c data flow walkthrough)
- DNA source is the largest source system; ACCT validates Oracle extraction path (ConnectorX + oracledb fallback)
- 1.2M row size validates per-table performance + memory model without requiring large-table windowed extraction (Phase 3 scope)
- ACCT has PII columns (`TAXID`, `EMAIL`, `PHONE`) — pilot validates tokenization flow per D6 + D102
- ACCT is referenced throughout the test fixture canonical schema (D79); pilot validates Tier 3 integration test parity

**Trade-offs accepted**:
- Slightly larger than original criterion (1.2M vs <1M) — extends Phase 2 wall-clock by ~1-2 minutes per cycle
- Pilot focuses on small-table flow only (no large-table windowed extraction validation until Phase 3)
- Consumer-team impact varies by ACCT downstream query volume — verify quietly via 90-day query log review before cutover

**Affects**:
- Phases: Phase 2 (Pilot Cutover) scope explicitly DNA.ACCT
- Decisions: D6 (tokenization vault — ACCT PII columns), D11 (LookbackDays — N/A for small tables), D79 (test fixture canonical schema)
- Runbooks: RB-1 / RB-2 / RB-9 — exercised on ACCT first
- Schema: Bronze + Stage tables for ACCT created via auto-generation per Round 1.5b
- Code modules: all Round 3 modules + Round 4 CLIs exercised on ACCT

**Reversibility**: reversible — different pilot table can be substituted if ACCT proves unsuitable during Phase 2 prep.

**Risk delta** (per D61):
- ⬇️ DE-ESCALATED: **R01** (Phase 0 deliverable 0.7 pending) — partially mitigated; full closure when 0.1 architecture sign-off lands

**See also**: `02_PHASES.md` § Phase 2 Cutover Protocol + `phase1/01b_bronze_stage_example_ddl.md` (ACCT example DDL) + `phase1/01c_data_flow_walkthrough.md` (ACCT used in narrative).

---

## D105. SQL naming standards — procedures + views (mandatory enforcement)

**Status**: 🟢 Locked 2026-05-11

**Driver**: User-stated mandatory naming standard for all SQL artifacts in this project. Aligns with team's existing SQL convention. Going-forward enforcement; existing SP names grandfathered (D92 forward-only respected).

**Pillar(s) served** (per D61): Operationally stable (consistent naming across all SQL artifacts); Audit-grade (file-name-to-object-name mapping is unambiguous).

**Decision**: All NEW procedures and views from 2026-05-11 onwards follow these patterns:

| Object type | DB object name | File name in directory |
|---|---|---|
| **Procedure** | `General.{schema}.Proc{ProcedureName}` | `{schema}_Proc{ProcedureName}.sql` |
| **View** | `General.{schema}.Vw{ViewName}` | `{schema}_Vw{ViewName}.sql` |

Concrete examples:
- New CCPA SP: object = `General.ops.ProcProcessCcpaDeletion`; file = `ops_ProcProcessCcpaDeletion.sql`
- Merger-context view (per D102 + 0.4): object = `General.dbo.VwMaskedColumnRegistry`; file = `dbo_VwMaskedColumnRegistry.sql`
- Future parity-baseline-capture proc: object = `General.ops.ProcCaptureParityBaseline`; file = `ops_ProcCaptureParityBaseline.sql`

### Grandfather clause for existing SPs

**ALL EXISTING canonical SP names (Round 1 SP-1 through SP-11 + Round 7 SP-12) ARE PRESERVED.** No retroactive rename. D92 forward-only schema discipline is respected. Names like `General.ops.PiiVault_GetOrCreateToken`, `General.ops.PipelineExecutionGate_AcquireTest`, `General.ops.EnforceRetention`, `General.ops.PiiVault_ProcessCcpaDeletion` remain canonical.

When existing SPs receive Round 7-style additive parameter evolutions (per D92), the SP name does NOT change.

### Mandatory enforcement on all agents and sub-agents

All custom agents (`.claude/agents/udm-*.md`) and project-local skills (`.claude/skills/udm-*/SKILL.md`) MUST reject NEW SQL artifacts not conforming to D105. Specifically:
- `udm-design-reviewer` flags new DDL with non-conformant names as 🔴
- `udm-test-author` writes test code referencing new SPs/views with conformant names
- `udm-decision-recorder` validates D-number entries proposing new SPs/views use conformant names
- `udm-runbook-author` uses conformant names in any new DDL examples
- `udm-data-engineer-review` Gate 1 check includes naming-standard verification
- `CHECKS_AND_BALANCES.md` 5-gate validation Gate 1 includes naming-standard check for new artifacts

### Rationale

- Schema-prefixed file names enable bulk file operations (e.g., "deploy all `ops_` artifacts")
- DB object names without schema repetition (e.g., `ProcProcessCcpaDeletion` not `ops_ProcProcessCcpaDeletion`) avoid redundancy since schema is implicit in `General.{schema}.` namespace
- `Proc` / `Vw` prefix on object name disambiguates from tables (which have no prefix) in error messages + query plans
- File-vs-object asymmetry is intentional: file system has flat namespace (needs schema prefix); database has hierarchical namespace (schema implicit)

**Trade-offs accepted**:
- Mixed naming conventions in spec docs (existing SPs use legacy pattern; new SPs use D105) — readers must understand grandfather context
- File names are longer than DB object names by `{schema}_` prefix (e.g., `ops_` adds 4 chars)
- D105 is mandatory but not retroactive — slight inconsistency in canonical references

**Affects**:
- Decisions: D92 (forward-only schema evolution — D105 respects via grandfather clause)
- All future SQL DDL from Phase 0 onwards
- All agent + skill prompts (enforcement layer)
- HANDOFF §8 Pitfall #12 (naming standards must be locked early)
- CLAUDE.md "SQL Naming Standards" section (new)

**Reversibility**: reversible per future D-numbered decision if a different naming standard is later required. Existing artifact grandfathering minimizes blast radius.

**Risk delta** (per D61):
- None new (standardization reduces ambiguity)

**See also**: `CLAUDE.md` (project root, "SQL Naming Standards" section) + HANDOFF §8 Pitfall #12 + GLOSSARY.md entry + 6 agent/skill prompt updates.

---

## D106. Operational pipeline schedule — 02:00 AM cycle + 17:00 PM cycle

**Status**: 🟢 Locked 2026-05-12 — ⚫ Superseded by D109 2026-05-12 same-session (revised AM/PM cycle expanded to dual-Automic prod/test trigger times with 4-hour gap; supersession is forward-only per D92 — D106 body retained verbatim per D92 forward-only discipline; consult D109 below for canonical operational schedule)

**Driver**: Phase 0 deliv 0.10 ("2x/day pipeline schedule windows agreed"). Round 2 § 5.1 + Round 7 § 6.2 specified the Automic frozen-11 job inventory + structure (AM cycle / PM cycle / parity verify / retention monthly / etc.) with EXAMPLE times of "Daily 06:00" (AM) and "Daily 18:00" (PM). The Phase 0 step is the OPERATIONAL choice of concrete cron-equivalent times for production deploy.

**Pillar(s) served** (per D61): Operationally stable + Audit-grade (operator + Automic + downstream consumers all gate on a known schedule).

**Decision**: The canonical operational pipeline schedule for `JOB_PIPELINE_AM` is **02:00 weekdays** (Mon-Fri 02:00 local time); for `JOB_PIPELINE_PM` is **17:00 daily** (5 PM local time, Mon-Sun). All dependent jobs in the Round 2 § 5.1 + Round 7 § 6.2 frozen-11 inventory schedule relative to these anchors per their existing dependency contracts (e.g., `JOB_PARITY_VERIFY` per pipeline start = synchronous prerequisite immediately before each AM/PM cycle; `JOB_RETENTION_MONTHLY` = month-end after final PM cycle of the month).

**Rationale**:
- User-confirmed: "2 AM and 5 PM work for us."
- 02:00 weekdays for AM aligns with off-business-hours processing window typical for nightly ETL — lower contention on source DBs (DNA / CCM / EPICOR), lower contention on target SQL Server (Bronze writes), lower contention on network drive (Parquet writes). Skipping weekends matches existing operational cadence per CLAUDE.md "Multiple runs per day provide natural retry coverage for transient failures" pattern.
- 17:00 daily for PM captures end-of-business-day source activity before consumers query Bronze the next morning. Daily (Mon-Sun) is wider than AM (Mon-Fri) because some weekend transactions (e.g. CCM weekend activity for credit card auth flows) need next-business-day Bronze visibility.
- Times are SUPERSEDING the Round 2 § 5.1 + Round 7 § 6.2 example values (06:00 / 18:00) — those were placeholder values pending Phase 0 operational choice per the deliv 0.10 text itself ("this Phase 0 step is operational scheduling against the frozen-11 inventory"). Per D92 forward-only, the example values were never canonical operational config; this decision is the canonical pin.

**Trade-offs accepted**:
- 02:00 AM start means errors discovered overnight have ~5 hours of business-day blast radius before operator daytime presence. Mitigated by D29/D33 cooperative cancellation + Automic auto-failover (RB-9) running test-side hot-standby.
- 17:00 PM start during business hours means some contention with daytime source DB queries; mitigated by D11 + D14 lookback days providing natural re-extraction coverage if PM extraction lags.
- Times are LOCAL (server-local timezone); R32 cross-server parity baseline (per D27 + D65) MUST include timezone in `env_vars_required` so dev/test/prod stay aligned.

**Affects**:
- Decisions: extends D66 (job inventory) + Round 2 § 5.1 + Round 7 § 6.2 (job dependency contracts); the names + dependencies + CHECK constraints are unchanged
- Automic UI deployment at Phase 2 R1: cron expressions for `JOB_PIPELINE_AM` = `0 2 * * 1-5` (or Automic-equivalent), `JOB_PIPELINE_PM` = `0 17 * * *`
- `phase1/02_configuration.md` § 5.1 (L1042+): example times 06:00 / 18:00 are superseded for operational deploy; D106 is canonical. Per D92 forward-only, Round 2 spec not edited in place; D106 supersedes the operational schedule clause implicitly.
- Phase 0 deliv 0.10 (closes 🟢 strict)
- `phase1/02_configuration.md` § 4.1 parity baseline `env_vars_required`: SHOULD include `TZ` value to pin timezone (no spec change; operational note for B188 implementation)

**Reversibility**: reversible — schedule times are operational config, not schema. Future D-number can supersede if business hours shift OR if Automic + observability data shows the windows aren't right. The frozen-11 STRUCTURE is locked per D66 + D92; only TIMES are operational config.

**Risk delta** (per D61): No new risks. R02 (Round 0.5 spike) + R32 (Claude credential-access) unchanged. R01 strict-closure counter increments by 1 (deliv 0.10 → 🟢). **Note**: this is one of EIGHT simultaneous strict-closures in the same user-sign-off batch (0.6/0.9/0.10/0.14/0.15/0.18/0.19/0.20); post-cascade aggregate counter is 12/20 strict (60%); see RISKS.md R01 row for the de-escalation that followed.

**See also**: Round 2 § 5.1 (`phase1/02_configuration.md` L1042+) + Round 7 § 6.2 + D66 + RB-9 (auto-failover schedule context) + 02_PHASES.md Phase 0 deliv 0.10 closure narrative.

---

## D107. Dual offsite Parquet replication paths — H drive + VendorFile

**Status**: 🟢 Locked 2026-05-12 (user-confirmed at Phase 0 deliv 0.19 closure)

**Driver**: Phase 0 deliv 0.19 ("Offsite Parquet replication target identified — for DC-loss DR scenario"). D44 locked the requirement (DR drill alternates Q1/Q3 server failover; Q2/Q4 DC loss; RB-7 + RB-8 specify offsite Parquet consumer behavior) but left the SPECIFIC target unspecified. User now specifies two paths.

**Pillar(s) served** (per D61): Audit-grade + operationally stable + traceability (offsite Parquet is the DR safety net for the entire pipeline's Bronze layer per RB-8 Bronze rebuild from Parquet).

**Decision (RE-REFRAMED 2026-05-12 fix-application-2 same-session per user clarification "The H drive and VendorFiles drive are local environments for the company")**: TWO network drive paths total, **BOTH Windows-based AND BOTH LOCAL to the company's in-house infrastructure**:

1. **H drive (primary local network drive)**: Windows drive-letter mount of the canonical `\\archive\...` UNC pattern locked in D2 + D4 + D45.2. Concretely: `H:\source={Source}\table={Table}\year={YYYY}\month={MM}\day={DD}\batch={BatchId}_part-{N}.parquet` resolves to the same physical storage as `\\archive\source={Source}\...` per Windows drive-letter mount semantics. PRIMARY destination — pipeline writes land here first; D2/D4 + D45.2 invariants (100-250 MB target file size; ZSTD compression; sort order; statistics enabled) apply.
2. **VendorFile location (secondary local network drive)**: a second Windows network drive in the company's in-house infrastructure (NOT vendor-managed; the name reflects the drive's primary content / organization, NOT its location). Specific host + canonical UNC path TBD per ops team at Phase 2 R1 implementation. Receives byte-equivalent Parquet content via async replication from H drive (mechanism = robocopy / DFS / Windows-Server-side replication TBD).

**Critical clarification of DR posture**: BOTH H drive AND VendorFile are LOCAL to the company DC. **D107 alone does NOT cover the DC-loss DR scenario** that D44 + RB-7 (Q2/Q4 DR drill) + RB-8 (Bronze rebuild from Parquet) assume. The user-confirmed two-drive setup provides:
- **In-DC redundancy** against single-disk / single-server failure (operationally useful)
- **Operational secondary** for read access by other teams or backup readers
- **NOT** geographic-separation DR for DC loss (both drives go down with the DC)

**True off-DC DR target identification is OPEN** post-clarification. Phase 0 deliv 0.19 (offsite Parquet replication target for DC-loss DR) is downgraded from 🟢 strict → 🟡 partial pending: (a) confirmation that DC-loss DR is in-scope for this project, (b) if in-scope: identification of a true off-DC target (separate DC, cloud storage, vendor-managed mirror); if out-of-scope: explicit acceptance of DC-loss-no-DR posture via new D-number. Tracked as **B192** at next backlog batch.

**(Historical notes — pre-fix framings)**:
- **Pre-fix-1** (original D107 lock same session 2026-05-12): framed BOTH H + VendorFile as "offsite" — first user clarification corrected to H=primary, VendorFile=offsite
- **Pre-fix-2** (post-fix-application-1): framed H=primary local + VendorFile=offsite (vendor-managed off-DC) — second user clarification corrected to BOTH local; offsite DR is now an open question
- **Current framing** (this fix-application-2): H=primary local + VendorFile=secondary local; off-DC DR is uncovered and tracked as B192

**Rationale**:
- User-confirmed (3-step clarification arc same session 2026-05-12):
  1. "We will have two network drive paths, H drive and another VendorFile location network drive. These are windows based paths." (initial)
  2. "As for 0.5, we have two network drive paths. H and VendorFiles." (clarification 1 — both serve Phase 0 deliv 0.5)
  3. "The H drive and VendorFiles drive are local environments for the company." (clarification 2 — BOTH are local, neither is vendor-managed off-DC)
- Two-drive in-DC setup provides operational benefits: (a) **single-disk / single-server failure resilience** (one drive remains available if the other has hardware issues); (b) **operational secondary** for read access (other teams / backup readers can use VendorFile without competing for H drive bandwidth); (c) **partition-strategy optionality** (different partition layouts on H vs VendorFile possible per Tool 16 partition-recommendation advisory).
- DC-loss DR scenario per D44 + RB-7 Q2/Q4 drill is NOT addressed by D107 alone — both drives are local and would be lost together in a DC-loss event. True off-DC DR target identification is an OPEN question tracked as B192.
- Windows-based paths are consistent with the existing infrastructure used by the engineering team; no new infrastructure procurement required for either drive.

**Trade-offs accepted**:
- VendorFile replication is ASYNCHRONOUS to H drive primary write — Bronze + H drive Parquet land first; VendorFile copy lags by minutes to hours. Acceptable for the operational secondary use case (consumers reading from VendorFile see slightly-stale data; primary readers use H drive).
- Replication mechanism (DFS / robocopy / xcopy / Windows-Server-side replication) deferred to Phase 2 R1 implementation choice; per D92 forward-only, this decision locks the TARGETS + ROLES but leaves the MECHANISM additive at implementation time.
- **DC-loss DR is NOT covered by D107**: both drives are in the same DC; a DC-loss event affects both. This is a knowingly-accepted gap pending resolution via B192 (true off-DC DR target identification). Until B192 resolves, the project's DR posture for DC-loss is: rely on company-level backup / vendor SLAs / re-extraction from source DBs (per D34 greenfield deployment + D14 IsReExtraction pattern + D11 lookback days providing natural re-extraction coverage).
- Windows-based paths mean RHEL pipeline servers need SMB/CIFS mount + Windows credentials for write access to BOTH drives. H drive is the primary network drive (closes deliv 0.5 strict per existing 00_OVERVIEW + 01_ARCHITECTURE + D2/D4 references); SMB/CIFS mount configuration on the RHEL pipeline servers is verified as part of Phase 2 R1 pre-flight (per the Phase 2 plan-draft R1 prerequisites + parity baseline B183). VendorFile requires its own SMB/CIFS mount + company-internal credentials — adds a `WINDOWS_VENDORFILE_CREDS` env-key family (TBD) to the `.env` per D27 + D103 + D63 + the Round 7 § 7.3 OPS-key amendment pattern; tracked as a B-future at Phase 2 R1.

**Affects**:
- Decisions: D2 + D4 (primary network drive path standard) — D107 OPERATIONALIZES these by naming H drive as the Windows mount of the canonical `\\archive\...` UNC pattern. The UNC path stays canonical; H drive is the operator-friendly drive-letter alias. D44 (DR alternates Q1/Q3 + Q2/Q4) — D107 alone does NOT satisfy the off-DC DR target requirement D44 left open (both drives are local); resolution per D110 explicit DC-loss-no-DR posture acceptance. D27 (cross-server parity) — both H drive (primary local) + VendorFile (secondary local) must be reachable from all 3 servers (dev / test / prod); parity baseline filesystem_layout SHOULD include both paths (B-future).
- RB-7 (DR rehearsal): test plan covers (a) primary H drive failure (read from VendorFile local secondary); (b) DC loss — NOT covered by D107 since both drives are in-DC; delegated to D110 (DC-loss-no-DR posture acceptance + recovery via company backup + source-DB re-extraction). RB-7 Q2/Q4 drill scope reduces to tabletop + re-extraction validation per D110 trade-offs.
- RB-8 (Bronze rebuild from Parquet): rebuild operator selects H drive by default (primary network drive, expected to be available); falls back to VendorFile ONLY if H drive is lost or unreachable. Procedure update tracked at Phase 2 R1.
- Phase 0 deliv 0.5 (network drive path standard finalized) — D107 closes 🟢 strict by anchoring H drive as the primary network drive + VendorFile as the secondary local mirror. Deliv 0.19 (offsite Parquet replication target for DC-loss DR) is DOWNGRADED from 🟢 strict → 🟡 partial pending B192 resolution (true off-DC target identification OR explicit DC-loss-no-DR acceptance decision).
- `01_ARCHITECTURE.md` + `00_OVERVIEW.md` should note H drive as the primary mount + VendorFile as secondary local mirror in their data-flow diagrams (B-future or Round 1.5b supplement); DC-loss DR posture per D110 acceptance.

**Reversibility**: reversible — offsite targets are operational config. Adding / removing offsite paths is an additive decision per D92; the primary network drive (per D2/D4) is the canonical source-of-truth, so offsite changes don't affect Bronze rebuild logic beyond which path the operator reads from.

**Risk delta** (per D61): ⬇️ DE-ESCALATED context: D44 DR DC-loss scenario gains a concrete recoverable path. R01 strict-closure counter increments by 1 (deliv 0.19 → 🟢) as part of the 8-simultaneous-closure user-sign-off batch (0.6/0.9/0.10/0.14/0.15/0.18/0.19/0.20); post-cascade aggregate counter is 12/20 strict (60%); see RISKS.md R01 row for the de-escalation that followed.

**See also**: D2 + D4 + D44 + D45.2 + RB-7 + RB-8 + Round 4 § 3.11 `alert_dispatcher` (downstream alerts on offsite-replication failures) + Phase 0 deliv 0.5 + 0.19 closure narratives + `phase1/04b_phase_0_closure_tools.md` § 5 (Tool 16 partition-recommendation logic for primary + offsite paths).

---

## D108. Ops-channel client — email (SQL Server + Automic) + Power BI metrics + Microsoft Teams

**Status**: 🟢 Locked 2026-05-12 (user-confirmed at Phase 0 deliv 0.20 closure)

**Driver**: Phase 0 deliv 0.20 ("Ops-channel client integration") + B156 (R7C1-5 advisory framing concern that proposed `OPS_CHANNEL_FALLBACK_ORDER=slack,pagerduty,email,sms` inverts canonical SRE architecture). User now specifies the actual mechanism for production deploy.

**Pillar(s) served** (per D61): Operationally stable + Audit-grade (every alert + notification leaves a trail through pre-existing audit-tracked channels — SQL Server mail history, Automic logs, Power BI alert audit, Teams audit).

**Decision**: Ops-channel notifications use **EMAIL** as the primary delivery mechanism, sourced from one of three audit-tracked engines:
1. **SQL Server Database Mail** (`msdb.dbo.sysmail_*` + `sp_send_dbmail`) — primary for alerts originating from Bronze layer logic (e.g. SCD2 reconciliation alerts, retention enforcement, CCPA process notifications). Pre-existing infrastructure already used by team per user note: "We already send emails via SQL Server to our team."
2. **Automic notifications** — primary for alerts originating from Automic job lifecycle (failure / success / SLA breach on `JOB_PIPELINE_AM` / `JOB_PIPELINE_PM` / `JOB_PARITY_VERIFY` / `JOB_RETENTION_MONTHLY` / etc.). Pre-existing infrastructure.
3. **Power BI metric-based alerts** — primary for trend / threshold alerts (e.g., row-count anomaly, lateness L_99 drift, capacity baseline drift). Pre-existing PBI alert infrastructure tied to dashboards.

**Microsoft Teams** is the secondary surface — alerts CAN be routed to Teams channels via either (a) SQL Server Database Mail to a Teams-monitored mailbox, or (b) Power BI Teams integration, or (c) Automic-to-Teams webhook (vendor-supported). No new MS Teams infrastructure required.

This decision **SUPERSEDES** the B156 advisory framing concern. The R7C1-5 advisory raised that `OPS_CHANNEL_FALLBACK_ORDER=slack,pagerduty,email,sms` inverts canonical SRE patterns (where PagerDuty is the routing hub) — B156 is now ⚫ CLOSED with rationale: **the project does NOT use Slack / PagerDuty / SMS**; ops-channel architecture is EMAIL-centric via SQL Server + Automic + Power BI + Teams. The advisory's SRE-canonical concern doesn't apply because the project's stack is different.

**Rationale**:
- User-confirmed: "We will send notifications via email. Automic and SQL Server can send such notifications. We already send emails via SQL Server to our team. These metrics can be tracked in PowerBI as well and we can send notifications there. We also use Microsoft Teams."
- Uses pre-existing infrastructure ($0 additional cost, no new vendor relationships) per the project's strict cost ceiling.
- Email + Teams hybrid provides both push (email = inbox-driven) and pull (Teams = channel-monitored) surfaces; operators can choose per alert criticality.
- SQL Server Database Mail is auditable via `msdb.dbo.sysmail_event_log` — every alert send is recorded; satisfies D26 append-only audit-grade pillar.

**Trade-offs accepted**:
- NO real-time paging mechanism (no PagerDuty / OpsGenie / SMS / Slack). Critical alerts must surface via email — operators must monitor email actively or set up email-to-SMS forwarding on their side. Mitigated by the multiple-surface approach (Teams channel monitoring provides a more-real-time secondary surface).
- Round 4 § 3.11 `alert_dispatcher` implementation at Phase 2 R1 uses Python's `smtplib` (for direct email) OR shells out to `sp_send_dbmail` (for SQL Server Database Mail integration). Mechanism choice deferred to implementation per D92 forward-only.
- Per-environment `OPS_CHANNEL_*` env keys: Round 7 § 7.3 (`phase1/07_schema_evolution_governance.md` L545+) amended Round 2 § 2 baseline `.env` from 45 keys → 54 keys (9 new `OPS_CHANNEL_*` keys per L561). D108 narrows this to the email-mechanism subset: `OPS_CHANNEL_SMTP_HOST` / `OPS_CHANNEL_SMTP_PORT` / `OPS_CHANNEL_SMTP_USER` / `OPS_CHANNEL_FROM` / `OPS_CHANNEL_TO_DEV` / `OPS_CHANNEL_TO_TEST` / `OPS_CHANNEL_TO_PROD` (or equivalent). PagerDuty / Slack-related env keys originally proposed in Round 7 § 7.3 L550-L552 (`OPS_CHANNEL_PRIMARY=slack`, `OPS_CHANNEL_SLACK_WEBHOOK`, `OPS_CHANNEL_PAGERDUTY_KEY`) are explicitly SUPERSEDED per D108 + B156 closure — to be ignored at Phase 2 R1 implementation OR explicitly removed via a Round 7.5 supplement.

**Affects**:
- Decisions: extends Round 4 § 3.11 `alert_dispatcher` interface (mechanism = email-via-smtplib or email-via-sp_send_dbmail); extends Round 7 § 7.2 `JOB_PARITY_EXCEPTION_NOTIFY` consumer; extends Round 2 § 2 `OPS_CHANNEL_*` env-key set
- B156 ⚫ CLOSED — advisory framing concern resolved: project stack is email-centric, not SRE-canonical Slack/PagerDuty pattern; closure attestation in B156 entry
- Phase 0 deliv 0.20 closes 🟢 strict
- Round 4 § 3.11 implementation lands at Phase 2 R1 per `phase2/00_phase_overview.md` R1 prereq #5 (per-tool implementations)

**Reversibility**: reversible — ops-channel architecture is operational config. If future requirements demand real-time paging (regulatory + SLA-driven), a new D-number can supersede D108 to add PagerDuty or equivalent. The audit-trail-via-email approach is locked at this decision; alternatives are additive.

**Risk delta** (per D61): ⬇️ DE-ESCALATED: B156 advisory carryover ⚫ CLOSED (R7C1-5 finding resolved). ⬆️ MINOR ESCALATION: alert-latency risk slightly elevated (no real-time paging) but well below action threshold; document as new sub-class of R02 (operational readiness) rather than open a new R-number. R01 strict-closure counter increments by 1 (deliv 0.20 → 🟢) as part of the 8-simultaneous-closure user-sign-off batch; post-cascade aggregate counter is 12/20 strict (60%), **CROSSING the ≥10/20 threshold** — **R01 DE-ESCALATED Likelihood High → Medium → score 9 → 6** in the same cascade; see RISKS.md R01 row for the de-escalation narrative.

**See also**: Round 4 § 3.11 `alert_dispatcher` (`phase1/04_tools.md`) + Round 7 § 7.2 (`phase1/07_schema_evolution_governance.md`) + Round 2 § 2 (`phase1/02_configuration.md`) + B82 + B156 + Phase 0 deliv 0.20 closure narrative.

---

## D109. Operational pipeline schedule revised — dual-Automic prod/test trigger times with 4-hour gap (supersedes D106)

**Status**: 🟢 Locked 2026-05-12 (user-confirmed same-session as D106; supersedes D106 forward-only per D92)

**Driver**: User clarification same-session 2026-05-12 of the dual-Automic-instance topology underlying Phase 0 deliv 0.10. User said: "We have 2 Automic instances. 1 for production and 1 for testing and development. This testing and development Automic instance will trigger the pipeline at a time of our choosing. The test environment should check the status of the production environment. The production environment should update the status of a given SQL table and based on this update, the test environment will run or it will not trigger because production succeeded. The SQL table will be used as a way to have production and test pipelines communicate. Generally, our pipeline takes 1 hour to run so 2 AM production and 6 AM test should be sufficient triggers. We can trigger production at 5 PM and trigger test at 9 PM." D106 locked single-event 02:00 + 17:00 against an implicit single-Automic-schedule assumption — D109 expands the contract to dual-instance prod-then-test triggers with a 4-hour gap derived from the empirical "1 hour to run" pipeline runtime.

**Pillar(s) served** (per D61): Operationally stable + Audit-grade (dual-Automic-trigger contract makes the failover path empirically reachable every cycle; SQL-table-based prod-test communication via `General.ops.PipelineExecutionGate` is the canonical audit anchor per D29 revised + D33 + Round 1 § 4 + SP-3 / SP-4 acquire contracts).

**Decision**: The canonical operational pipeline schedule is dual-Automic-instance with prod-then-test trigger pairs per cycle, communicating exclusively via `General.ops.PipelineExecutionGate`:

| Cycle | Prod trigger (Automic prod instance) | Test trigger (Automic test/dev instance) | Gap | Days |
|---|---|---|---|---|
| **AM** | 02:00 local | 06:00 local | 4 hours | Weekdays (Mon-Fri) |
| **PM** | 17:00 local | 21:00 local | 4 hours | Daily (Mon-Sun) |

- **Production Automic instance** triggers `JOB_PIPELINE_AM` at 02:00 weekdays + `JOB_PIPELINE_PM` at 17:00 daily. Acquires `PipelineExecutionGate` via SP-3 `PipelineExecutionGate_AcquireProd` (Round 1 SP-3); runs to completion; updates Status='SUCCEEDED' / 'FAILED' / 'TIMEOUT' / 'CANCELLED' per the Round 1 status enum + CHECK constraint.
- **Test/dev Automic instance** triggers the same logical jobs at 06:00 weekdays + 21:00 daily. Acquires `PipelineExecutionGate` via SP-4 `PipelineExecutionGate_AcquireTest` (Round 1 SP-4); reads the prod row first; runs ONLY if prod's row indicates failure / timeout / never-started; otherwise SP-4 returns `EXIT_RUNNING_HEALTHY` per Round 2 § 5.1 + skips execution.
- **4-hour gap** (vs D29 revised's 2.5-hour buffer): empirical safety margin = 1-hour observed pipeline runtime + 3-hour buffer for variance / source-DB latency / retry overhead / D33 cancellation grace.
- **SQL-table communication is exclusive** — `PipelineExecutionGate` per Round 1 + UNIQUE on `(CycleType, CycleDate)` is the single source of truth that both Automic instances poll via SP-3 / SP-4. No shared filesystem, no Automic-to-Automic messaging.

**Rationale**:
- User-confirmed dual-Automic topology supersedes D106's implicit single-schedule assumption. D106 set 02:00 + 17:00 as canonical *single-event* times; D109 preserves those as the PROD-trigger times AND adds the TEST-trigger times (06:00 + 21:00) for the dual-instance failover path.
- 4-hour gap reflects empirical runtime + 3× safety multiplier. Industry practice for nightly-ETL failover windows where false-failover cost > late-failover cost.
- Test gates on PROD STATUS in SQL — not on time-elapsed — which is the exact contract Round 2 § 5.1 + SP-4 encode. D109 ratifies existing Round 1 + Round 2 schema/SP design as the operational contract; no new gate columns, no new SP signatures.
- Weekend skip for AM (Mon-Fri) preserves D106 rationale (lower contention; pre-existing operational cadence). PM stays daily (Mon-Sun) for weekend CCM coverage.

**Trade-offs accepted**:
- 4-hour gap is wider than D29 revised's 2.5-hour value — D109 is canonical going forward; D29 revised body stays unchanged per D92 forward-only.
- 06:00 AM test trigger means ~07:00 completion for test-side failover; tight operator response window if test-side also fails (low-probability double failure). Mitigated by D108 ops-channel email alerts on test-side TIMEOUT / FAILED.
- 21:00 PM test trigger may overlap with downstream Silver/Gold job windows if those run at 23:00+. Mitigated by D29 revised's "downstream jobs gate on `PipelineExecutionGate.Status='SUCCEEDED'`" rather than wall-clock.
- Local timezone (server-local per D106 carryover) — R32 parity baseline `env_vars_required` MUST include `TZ` (B188 implementation note tracked from D106; explicit `TZ` add to baseline schema via polish-item-2 fix).
- Test/dev Automic acquires gate via SP-4 which mutates state — gate-table communication is bidirectional (prod writes, test reads-and-conditionally-writes). Established Round 1 + Round 2 contract; no new audit surface.

**Affects**:
- Decisions: ⚫ Supersedes D106 (operational schedule); extends D29 revised (sets concrete test-trigger times); extends D33 cooperative cancellation (15-min grace within 4-hour gap); extends D66 (job inventory); extends Round 1 SP-3 / SP-4 acquire contracts (no signature change); extends Round 2 § 5.1 (canonical times now D109 vs Round 2 example values 06:00 / 18:00).
- Automic deployment at Phase 2 R1:
  - Production Automic instance: cron-equivalent `0 2 * * 1-5` for `JOB_PIPELINE_AM`; `0 17 * * *` for `JOB_PIPELINE_PM`
  - Test/dev Automic instance: cron-equivalent `0 6 * * 1-5` for `JOB_PIPELINE_AM`; `0 21 * * *` for `JOB_PIPELINE_PM`
- `phase1/02_configuration.md` § 5.1: example times 06:00 / 18:00 superseded for operational deploy by D109. Per D92 forward-only, Round 2 spec not edited in place; D109 supersedes implicitly.
- D29 revised body ("scheduled at 04:30 (AM) and 19:30 (PM)"): operationally superseded by D109 06:00 / 21:00; D29 body unchanged per D92.
- Phase 0 deliv 0.10: stays 🟢 strict (closed via D106; D109's supersession is a refinement).
- B188 (lateness measurement): `JOB_LATENESS_MEASURE` schedule must not collide with AM 02:00-06:00 or PM 17:00-21:00 envelopes; pick non-overlapping window (e.g., 09:00 weekdays).

**Reversibility**: reversible — schedule times remain operational config. Future D-number can supersede if (a) observed pipeline runtime grows beyond 1 hour, (b) business hours shift, or (c) Automic instance topology changes (e.g., merger to single-instance). The dual-Automic-instance ARCHITECTURE is itself canonical per user-confirmed topology — only TIMES are operational config.

**Risk delta** (per D61): No new risks. D106 supersession is a refinement, not architecture change. R02 + R32 unchanged. R01 strict-closure counter unchanged (deliv 0.10 already counted at D106 close). D109 reduces likelihood of "test runs while prod still healthy" false-failover scenario by widening gap from 2.5h to 4h — ⬇️ DE-ESCALATION inside existing R02 frame.

**See also**: D106 (⚫ superseded by this decision) + D29 revised + D33 + Round 1 § 4 `PipelineExecutionGate` (`phase1/01_database_schema.md`) + Round 1 SP-3 + SP-4 + Round 2 § 5.1 (`phase1/02_configuration.md`) + RB-9 (auto-failover) + 02_PHASES.md Phase 0 deliv 0.10 closure.

---

## D110. DC-loss-no-DR posture acceptance — B192 resolution path (b)

**Status**: 🟢 Locked 2026-05-12 (user-confirmed at B192 closure approval: "The DC-loss DR posture decision (B192) has also been approved. We're fine with this scope.")

**Driver**: B192 (BACKLOG.md) surfaced at the Phase 0 user-sign-off cascade post-D107 fix-application-2 — user clarified BOTH H drive and VendorFile network paths are LOCAL to the company DC, leaving DC-loss DR scenario per D44 + RB-7 Q2/Q4 + RB-8 uncovered. B192 offered two resolution paths: (a) identify true off-DC target, (b) explicit acceptance of DC-loss-no-DR posture. User selected path (b).

**Pillar(s) served** (per D61): Audit-grade + operationally stable (explicit-acceptance D-number gives auditable artifact documenting the conscious DR-scope choice; auditors can review D110 + trace rationale + accepted residual risk).

**Decision**: The project explicitly ACCEPTS a DC-loss-no-DR posture for Bronze rebuild from Parquet (RB-8) + quarterly DC-loss drill (RB-7 Q2/Q4). The pipeline does NOT require an off-DC Parquet mirror as part of its own DR design. Recovery mechanisms in catastrophic DC-loss, in priority order:

1. **Company-level backup** (OUTSIDE pipeline scope) — primary off-DC recovery mechanism
2. **Source-DB re-extraction** per canonical pattern:
   - D34 greenfield (all migration scripts are CREATE FROM scratch; re-extraction is the established recovery path)
   - D14 `IsReExtraction` flag pattern enabling explicit re-extraction runs
   - D11 lookback days providing natural rolling re-extraction coverage on every routine run
3. **Vendor SLAs on source-DB availability** — Oracle / SQL Server / EPICOR DBs are vendor-/DBA-managed per D28; their availability + recovery contracts ARE the underlying DR substrate

**Rationale**:
- User-confirmed explicit acceptance: "We're fine with this scope" — closes B192 in favor of path (b).
- Re-extraction is operationally proven: pipeline already re-extracts on every run via D11 lookback days; D14 extends to explicit-trigger mode. A DC-loss recovery is functionally equivalent to a "very large IsReExtraction run" against restored source DBs.
- Source DBs are vendor-managed (D28); their DR contracts are canonical substrate the pipeline depends on. Building a parallel pipeline-managed off-DC mirror would duplicate this substrate at substantial cost and operational complexity.
- D107's two-drive setup (H + VendorFile) remains operationally valuable for in-DC single-disk / single-server resilience — D110 does NOT remove D107; D110 only declares D107's coverage is sufficient AT THE PIPELINE LAYER + off-DC coverage is provided BY OTHER LAYERS (company backup + vendor source-DB DR + re-extraction).
- Cost: zero new commercial spend. Building a true off-DC target (cloud blob / vendor mirror / separate-DC network drive) would violate D103 cost ceiling without commensurate pipeline-layer benefit beyond what re-extraction already provides.

**Trade-offs accepted**:
- **RTO for DC loss is bounded by re-extraction speed** — 3B-row table at ~10K rows/sec ≈ 3.5 days; total pipeline catch-up across 50+ tables ≈ 1-2 weeks. Knowingly-accepted RTO; faster RTO would require off-DC mirror per path (a), rejected here.
- **Regulatory implications for D30 7-year retention**: violation in DC-loss event depends on company-level backup retention reaching 7 years. Pipeline team accepts dependency at pipeline-lead level. Future compliance review may re-open via supersession.
- **D44 quarterly DR drill scope reduction**: RB-7 Q2/Q4 drill becomes TABLETOP exercise validating re-extraction path + company-backup recovery procedure rather than live Parquet-restore drill. RB-7 spec update tracked at Phase 2 R1.
- **RB-8 Bronze rebuild scope**: retains server-loss + ransomware + accidental-truncate cases per D44. DC-loss case REMOVED from RB-8 stated scenarios + DELEGATED to D110 re-extraction path; RB-8 spec update tracked at Phase 2 R1.
- **B192 closure**: B192 ⚫ CLOSED via D110 path (b). **Phase 0 deliv 0.19 re-flips 🟡 partial → 🟢 strict** — the deliverable text is satisfied by "no off-DC target identified; risk accepted per D110" when accompanied by the explicit-acceptance D-number. R01 strict-closure counter increments back by 1.

**Affects**:
- Decisions: extends D44 (DR drill Q2/Q4 scope clarified to tabletop + re-extraction); extends RB-7 + RB-8 (DC-loss case delegated); references D34 + D14 + D11 + D28 + D103 substrate.
- B192 ⚫ CLOSED via D110 path (b). Closure attestation in BACKLOG.md B192 entry.
- Phase 0 deliv 0.19 re-flips 🟡 → 🟢 strict via D110 closure mechanism.
- `05_RUNBOOKS.md` RB-7 + RB-8 scope update: tracked as B-future at Phase 2 R1 per D92 forward-only.
- `RISKS.md` R01 strict-closure counter: D108 brought to 12/20 + this D110 re-flip restores to 12/20 (the prior D107 fix-application-2 downgrade is reversed).

**Reversibility**: reversible — if compliance / regulatory audit determines DC-loss-no-DR violates D30, OR if company backup infrastructure changes, OR if cloud storage costs drop, new D-number can supersede D110 to mandate true off-DC target. Standard D92 forward-only supersession path.

**Risk delta** (per D61): ⬇️ DE-ESCALATED: B192 ⚫ CLOSED; no new R-number. R01 strict-closure counter restores from D107 fix-app-2 downgrade. ⬆️ MINOR ESCALATION inside R02 frame: explicit DC-loss-no-DR acceptance documents knowingly-accepted residual risk; sub-class of R02 (alongside D108 alert-latency sub-class).

**See also**: B192 (BACKLOG.md) + D44 + D34 + D14 + D11 + D28 + D103 + D107 + RB-7 + RB-8 + Phase 0 deliv 0.19 closure (`02_PHASES.md`).

---

## D111. Operational-infra decision discipline — propose-then-attest two-stage status flip

**Status**: 🟡 Proposed 2026-05-12 (self-referentially demonstrating its own discipline; will flip 🟢 Locked at user-attestation event ≥4 hours later OR at next session)

**Driver**: Process discipline surfaced from D107's three same-session revisions (initial lock → fix-application-1 H=primary + VendorFile=offsite → fix-application-2 BOTH=local). Each revision was driven by progressive user clarification of operational reality. Plus D106 → D109 churn (D106 single-event 02/17 superseded same-session by D109 dual-Automic 02/06 + 17/21 once dual-instance topology surfaced). Pattern: authoring-time assumptions about operational reality can be wrong even when the authoring agent has all canonical context. D111 codifies a process-level rule to prevent recurrence.

**Pillar(s) served** (per D61): Audit-grade + operationally stable (every operational-infra D-number gets a paper trail of WHEN user confirmed operational truth, separate from WHEN the decision was first proposed; the gap becomes investigable rather than silent).

**Decision**: Decisions touching **operational infrastructure** — defined as any decision whose locked value would be falsifiable by a single operator query against the running environment (paths, schedules, env keys, deployment topologies, credentials locations, server hostnames + roles, Automic instance topology, network drive identity, host-level configurations) — MUST START as **🟡 Proposed** at authoring time, regardless of authoring-agent confidence in the value. Flip to **🟢 Locked** requires:

1. **Explicit user-attestation** that proposed value matches operational truth at attestation time, recorded in decision body with date + attestation phrase (e.g., "user-confirmed 2026-MM-DD at [context]"), AND
2. **No further revisions in the same session** — if user provides clarifying corrections during the same session as the initial proposal, status stays 🟡 Proposed; corrected value is incorporated; cycle restarts. Flip to 🟢 Locked happens at start of NEW session OR after substantive pause (≥4 hours) when user re-confirms corrected value.

**Decisions exempt from D111**: structural / architectural / schema-evolution / pillar-mapping decisions whose locked value is NOT falsifiable by operator query (e.g., "use Polars SCD2 with INSERT-first pattern" = design choice, not operational fact). Exempt class includes design patterns, edge-case mitigation, schema-evolution discipline, meta-process decisions like D111 itself.

D111 is a META-DISCIPLINE about WHEN to flip status — doesn't supersede prior operational-infra D-numbers retroactively. Existing 🟢 Locked operational-infra decisions stay locked per D92. D111 applies prospectively.

**Rationale**:
- D107 churn evidence: three revisions in one session each driven by user clarification of operational truth — demonstrates well-grounded authoring (D107 cited Phase 0 deliv 0.19, D44, RB-7, RB-8, D2, D4, D45.2) can lock the wrong operational value when operator's mental model hasn't been explicitly elicited.
- D106 + D109 churn evidence: D106 locked single-event 02:00 + 17:00 hours before D109's same-session supersession revealed dual-Automic + 4-hour gap was actual operational design. D106's authoring assumed single-schedule architecture — would have been caught had D106 started 🟡 Proposed with explicit operational-attestation gate.
- 🟡 → 🟢 discipline already exists per canonical D-number status enum + "How to Add a Decision" L2980-L2982. D111 EXTENDS with per-D-class rule about WHEN flip is appropriate.
- Same-session-pause requirement addresses subtle failure mode: user can attest to value then immediately revise within same conversational context. Session boundary / ≥4-hour pause forces attestation against refreshed mental state.
- Parallel disciplines: D55 5-gate + D56 mandatory second-pass + D89-D91 Pattern F. D111 sits in same family of "structural friction to catch implicit-assumption failures."

**Trade-offs accepted**:
- **Authoring latency**: every operational-infra decision requires at least one attestation cycle before flip — typically same-session prompt + response. Accepted because attestation cost (~minutes) << rework cost of churn (D107 ~30+ minutes across three revisions + cascade reconciliation).
- **Definition ambiguity**: "operational infrastructure" has fuzzy edges. Borderline cases use the "falsifiable by single operator query" rubric. Reviewers can challenge if rubric misapplied.
- **Meta-process burden**: adds per-D-number status-check directive to producer Gate 1 self-check per D95-D99 self-improvement suite. Minor producer-checklist evolution via `udm-producer-checklist-evolver` at next round close-out.
- **Self-referential locking**: D111 itself is meta-process (exempt-by-class), but starts 🟡 to demonstrate the discipline. Flip 🟢 at session boundary OR ≥4-hour pause when user ratifies the discipline itself.

**Affects**:
- Decisions: extends D55 + D56 + "How to Add a Decision" step 4 with per-D-class rubric.
- Future operational-infra D-numbers: must follow D111. Examples that WOULD have been 🟡-first under D111: D106, D107, D109. Examples that WOULD NOT (exempt): D45.4 (DATETIME2(3) ms-precision), D45.5 (VARCHAR(64) hash), D56 + D60 + D61 process disciplines.
- Producer Gate 1 self-check: adds operational-infra classification step + status-flip-gate verification step.
- `CHECKS_AND_BALANCES.md` Gate 1: should flag operational-infra D-numbers locked at authoring time as discipline violation.
- No prior D-numbers retroactively re-flipped per D92.

**Reversibility**: reversible — if practice reveals propose-then-attest too heavyweight (e.g., trivial operational-infra decisions), new D-number can supersede to narrow / remove. Standard D92 forward-only.

**Risk delta** (per D61): No new technical risks; ⬇️ DE-ESCALATED PROCESS risk: future operational-infra D-number churn should reduce in frequency. R02 operational-readiness sub-class "operational-truth drift" implicitly de-escalated. No R-number open/close.

**See also**: D107 (operational-infra churn evidence) + D106 + D109 (schedule churn) + D55 + D56 + D89-D91 + D95-D99 + D92 + "How to Add a Decision" + HANDOFF.md producer Gate 1 sections + `SELF_IMPROVEMENT_DISCIPLINE.md`.

---

## D112. Round-N.5 deep-dive plan timing — just-in-time at prior-phase close-out (formalizes B186)

**Status**: 🟢 Locked 2026-05-12 (user-confirmed at B186 timing-lock cascade: "just-in-time timing for Phase 3-6 deep-dive plans"; lift from B186 entry body to process-level decision)

**Driver**: B186 originally tracked "Author Phase 3 / 4 / 5 / 6 deep-dive plan docs" as open backlog with no timing constraint. User-confirmed just-in-time timing at Phase 0 user-sign-off batch cascade 2026-05-12 — each downstream-phase plan authored AT the close-out of the prior phase, not speculatively. B186 entry body carries inline timing-lock annotation; D112 lifts to project-wide process decision for posterity.

**Pillar(s) served** (per D61): Audit-grade + operationally stable (just-in-time avoids canonical-source drift — each plan reflects empirical learnings from prior phase rather than authoring-time speculation).

**Decision**: Downstream-phase deep-dive plan documents (the `phase{N}/00_phase_overview.md` + supporting per-round docs paralleling `phase1/00_phase_overview.md` + `phase2/00_phase_overview.md`) are authored AT THE CLOSE-OUT of Phase N's final round — never speculatively in advance:

| Plan doc | Authored at | Gate |
|---|---|---|
| `phase3/00_phase_overview.md` + supporting | Phase 2 R4 close-out | Phase 2 R4 sign-off complete |
| `phase4/00_phase_overview.md` + supporting | Phase 3 final-round close-out | Phase 3 sign-off complete |
| `phase5/00_phase_overview.md` + supporting | Phase 4 final-round close-out **AND** B191 Snowflake-test-conclusion (~mid-June 2026) | Both gates satisfied |
| `phase6/00_phase_overview.md` + supporting | Phase 5 final-round close-out | Phase 5 sign-off complete |

Each plan covers canonical structure: Purpose + Why-this-phase-exists + For-engineers / For-management / For-auditors / For-operators + Visuals + Round-by-round outline + acceptance criteria (gate-to-next-phase).

**Rationale**:
- User-confirmed at prior turn: direct quote "just-in-time timing for Phase 3-6 deep-dive plans".
- Empirical learning anchor: each phase produces evidence (Phase 1 = schema-stability; Phase 2 = Bronze production-readiness; Phase 3 = large-table scale; Phase 4 = cohort cutover; Phase 5 = Snowflake operational) informing NEXT phase's plan. Speculative authoring risks locking architectural assumptions that evidence then invalidates.
- Canonical-source drift avoidance: speculative plan becomes stale reference other docs cite. Phase 5 plan authored before B191 Snowflake-test conclusion would lock pre-test assumptions.
- B191 gate on Phase 5 plan specifically: Snowflake test conclusion firms up clustering / partition / Iceberg / native / cost decisions. Just-in-time + B191 gate ensures plan reflects post-test reality.
- D-number lift per close-out cascade best practice: process disciplines applying to multiple future events deserve D-number for cross-doc citation. Engineers searching `03_DECISIONS.md` find D112 directly rather than spelunking BACKLOG.

**Trade-offs accepted**:
- No advance phase-plan visibility for stakeholders at Phase 1. Mitigated by canonical phase narrative in `02_PHASES.md` Phase 3-6 outline sections.
- Authoring burden concentration: each phase close-out cascade has additional artifact of authoring next-phase plan. Bounded (4 plan docs × 4 remaining phases).
- B191 AND-gate for Phase 5: plan waits for BOTH Phase 4 close-out AND B191 conclusion. If B191 concludes first, plan still waits for Phase 4; if Phase 4 close-out first, plan waits for B191.
- Backward-compatibility: `phase1/00_phase_overview.md` + `phase2/00_phase_overview.md` already exist; D112 applies prospectively to Phase 3+.

**Affects**:
- Decisions: extends D60 (round close-out discipline) — adds per-phase-close-out artifact of next-phase plan; references D55 + D92 + D95-D99 + B186 (now closed via D112) + B191 (Phase 5 gate).
- B186 ⚫ CLOSED via D112; tracking shifts to per-phase close-out work-items.
- `udm-round-closeout` skill should include per-phase-close-out check "if final round of Phase N, author Phase N+1 plan as part of close-out cascade" — skill-update tracked at next close-out via `udm-specialty-tuner`.
- `02_PHASES.md` Phase 3-6 outline sections stay as-is; deep-dive plans land as separate `phase{N}/00_phase_overview.md`.
- `CURRENT_STATE.md`: Phase 3-6 plan-doc rows show "🟡 Pending — author at Phase N-1 close-out per D112".

**Reversibility**: reversible — if practice reveals just-in-time too late, new D-number can supersede to allow earlier authoring. Standard D92 forward-only.

**Risk delta** (per D61): No new risks. ⬇️ DE-ESCALATED canonical-source-drift risk; ⬇️ DE-ESCALATED B186-open burden. R01 strict-closure counter unchanged (B186 not a Phase 0 deliverable).

**See also**: B186 + B191 + D60 + D55 + D92 + D95-D99 + `phase1/00_phase_overview.md` + `phase2/00_phase_overview.md` + `02_PHASES.md` Phase 3-6 sections.

---

## D113. POLISH_QUEUE.md cosmetic-tracker discipline (P-N scheme)

**Status**: 🟢 Locked 2026-05-12 (process-discipline D-number — follows established precedent class **D55** 5-gate / **D60** round close-out / **D61** NORTH_STAR-RISKS-BACKLOG integration / **D89-D91** Pattern F / **D95-D99** self-improvement discipline; all 🟢 Locked directly at first authoring, with no 🟡-first attestation requirement applied. D111's operational-infra 🟡-first rule explicitly does NOT cover process-discipline D-numbers per its own scope text — process-discipline D113 is consistent with the established precedent class, not an exception requiring D111 authorization. Self-audit-on-cascade 2026-05-12 — Phase G — surfaced the prior wording "per D111 exemption" as logically thin since D111 is itself 🟡 Proposed; reframed via fix-application-in-place per D92-process-discipline-doc-clarification convention. Substantiating cycle: this D113 body authoring + Phase A/B/F cascade across 19 docs documented inline at `_validation_log.md` 2026-05-12 entries.)

**Pillar alignment** (per D61): **Audit-grade** (every cosmetic change gets a dated audit row with closure mechanism — same render-discipline as BACKLOG.md per Pitfall #9.j) + **Traceability** (P-numbers create stable identifiers for cosmetic carryover items so cross-doc references stay resolvable).

**Driver**: Post-multi-agent-cascade residual sweep 2026-05-12 found ~5 cosmetic carryover items (D107 / D106 supersession crumbs across the cascade footprint) that didn't fit cleanly anywhere — they're not substantive enough for BACKLOG WSJF view, they're not validation findings for `_validation_log.md`, and they're not behavior-changing for D-numbers. Per Pitfall #9.j (B-item status-render discipline) the project formalized render-discipline at the doc level; D113 formalizes it at the *tracking* level: cosmetic items get a dedicated typed substrate (POLISH_QUEUE.md) with their own identifier scheme (P-numbers).

**Decision**:
- **POLISH_QUEUE.md** (`docs/migration/POLISH_QUEUE.md`) is the single source of truth for cosmetic / readability / status-render / supersession-crumb / stale-date items that don't change behavior or unlock work.
- **P-numbers** (P-1, P-2, ...) are the identifier scheme; analogous to but distinct from B-numbers (substantive backlog), D-numbers (decisions), R-numbers (risks).
- **Status legend**: 🟡 Open / 🟠 Noticeable / ⚫ CLOSED / ⬜ Deferred — same vocabulary as BACKLOG.md per Pitfall #9.j.
- **Distinguishing test**: Does fixing this item change a decision body, runbook procedure, SP body, tool spec, or pipeline code? If YES → B-number. If it's a wording crumb, stale date, missing supersession marker, badge mismatch, or render-discipline drift → P-number.
- **How items leave**: (a) cosmetic fix lands inline + row gets ⚫ CLOSED + closure-mechanism line + strikethrough preserved; (b) item escalates to B-number (rare; document promotion + retire P-row); (c) explicit deferral with ⬜ + target round/phase boundary. Items do NOT silently leave.
- **Round close-out skim**: per skill update to `udm-round-closeout/SKILL.md` CCL Stage 2.5 + close-out checklist new section "POLISH_QUEUE.md" — at every round close-out, skim 🟡 Open P-items and close any whose underlying cosmetic drift was incidentally cleaned up by the round's substantive work.
- **Pattern F audit coverage**: per skill update to `udm-cascade-audit-evolver/SKILL.md` Trigger B + Trigger E extensions — Pattern F Layer 2 auditors include POLISH_QUEUE.md in audit scope at round close-out (closure-target audit + convention-registration audit apply analogously to P-numbers as they do to B-numbers).
- **Archive cadence for POLISH_QUEUE.md itself**: deferred to organic evolution; if/when the file grows comparable to `_validation_log.md` (>2000 lines), the archive policy at `_validation_log.md:14-23` is the precedent template to adopt (sibling file `POLISH_QUEUE_archive_<YYYY-MM>.md` + by-month naming + keep last ~30 days). For now (5 seed items), no archive cadence operationalized.

**Rationale**: Render-discipline drift was already a tracked Pitfall #9.j class with 2-event evidence (R6 retroactive + R7 first-production per `HANDOFF.md` §8 9.j formalization). The 2026-05-12 multi-agent cascade extended the evidence to 3-4 events; the residual sweep extended it further. Continuing to handle render-drift as ad-hoc deferral lines at the bottom of `_validation_log.md` entries (R-7/R-8/R-9/R-10 pattern from 2026-05-12 multi-agent cascade audit) leaks into the validation log's append-only audit-trail purity and provides no closure mechanism. POLISH_QUEUE.md gives render-drift a typed substrate with closure rules.

**Trade-offs** (knowingly accepted):
- **Yet-another-tracker overhead**: 4th tracker now (BACKLOG / RISKS / _validation_log / POLISH_QUEUE). Mitigated by: distinguishing test is mechanical (does fix change behavior YES/NO → B vs P); CCL Stage 2.5 marks POLISH_QUEUE as optional-skim not mandatory-read, so it doesn't inflate the producer onboarding cost.
- **P→B escalation criteria deferred**: D113 says "rare" but doesn't define a test. Accepted because the volume is low (5 seed items) and false-escalation cost is reversible. If volume grows, a sub-D-number or B-future can tighten the rule. **NOT a 🟡 carryover** — explicit deferral via D113's own scope.
- **Pattern F audit scope widening**: Pattern F Layer 2 now reads one additional doc (POLISH_QUEUE.md). Per `_reviewer_effectiveness.md` cascade-audit specialty events, Layer 2 audits already cover 11+ docs — adding 1 more is marginal cost.
- **D113 itself is a same-session-as-tracker D-lock**: POLISH_QUEUE.md was authored 2026-05-12 morning and D113 locks the discipline 2026-05-12 afternoon. Per established process-discipline precedent (D55 / D60 / D61 / D89-D91 / D95-D99 — all 🟢 directly at first authoring), no 🟡-first attestation required for process-infra D-numbers. D111's operational-infra 🟡-first rule does NOT apply per its own scope text (operational-infra = paths/schedules/env-keys/credentials/topology; process-discipline is a distinct class). Per D55 5-gate, the validation log entry (next section) documents the lock + the seed-items state at lock time.

**Cascade**:
- `docs/migration/POLISH_QUEUE.md` — Status badge "🟢 Locked 2026-05-12 per D113" added at file header; "Pillar mapping (per D61)" + "Risk delta (per D61)" sections added below frontmatter; P-4 archive policy misquote corrected via fix-application same-session.
- `HANDOFF.md` §3 lock list — D113 row added under "🟢 Locked 2026-05-12 (process-discipline batch + multi-agent cascade)" block.
- `HANDOFF.md` §14 last-reviewed — date confirms 2026-05-12 with D113 + POLISH_QUEUE crumb.
- `HANDOFF.md` §13 Quick links — `POLISH_QUEUE.md` row added (landed at residual sweep cascade earlier 2026-05-12).
- `CURRENT_STATE.md` — D-range bumped D1-D112 → D1-D113 throughout.
- `NORTH_STAR.md` — D113 added to decision list.
- `GLOSSARY.md` — D-range bumped + P-N entry added (landed at residual sweep cascade earlier 2026-05-12; D113 lock confirms the convention).
- `CHECKS_AND_BALANCES.md` CCL Stage 2.5 — POLISH_QUEUE skim recommendation added (landed at residual sweep cascade earlier 2026-05-12; D113 lock confirms).
- `.claude/skills/udm-round-closeout/SKILL.md` — CCL Stage 2.5 + close-out checklist new section "POLISH_QUEUE.md" added.
- `.claude/skills/udm-cascade-audit-evolver/SKILL.md` — CCL Stage 2.5 added; Trigger B + Trigger E descriptions extended to cover P-numbers.
- `_validation_log.md` — D113 lock + cascade entry appended (next).

**Reversibility**: reversible — if POLISH_QUEUE.md proves redundant or noisy, a future D-number can supersede D113 (retire POLISH_QUEUE.md as a worklist; either fold seed items into BACKLOG or treat them as `_validation_log.md` historical entries). Standard D92 forward-only — no retroactive edits to D113 once locked.

**Risk delta** (per D61): No new R-numbers. ⬇️ DE-ESCALATED a sub-class of R28 (round-level cascade self-attestation gap) — pre-D113, cosmetic render-drift had no dedicated home, leaking into BACKLOG WSJF view OR ad-hoc `_validation_log.md` deferral lists OR silent rot; POLISH_QUEUE.md gives render-drift a typed substrate with closure mechanism. R01 strict-closure counter unchanged (D113 is process-discipline, not a Phase 0 deliverable).

**See also**: `POLISH_QUEUE.md` + `HANDOFF.md` §8 Pitfall #9.j + D55 + D60 + D61 + D89-D91 + D92 + D95-D99 + D111 + B144 + `_validation_log.md` 2026-05-12 multi-agent cascade entry + 2026-05-12 residual-sweep entry + 2026-05-12 D113 lock entry (next).

---

## D114 — AppLaunchpad blindspot-ledger high-ROI subset adoption (🟢 Locked 2026-05-16)

**Status**: 🟢 Locked 2026-05-16

**Pillars served (per D61)**: operationally-stable (catches discipline-drift in-flight rather than post-hoc) + idempotent (executable + queryable discipline encoding) + auditable (every cascade event logged + ledger-validated)

**Driver**: discipline-debt-accumulation pattern surfaced 5x in 2026-05-15→2026-05-16 session (commits `521b68c` / `3eef410` / `aee329c` / `a03a35c` / `4112e92` — see HANDOFF §8 Pitfall #9.o for full evidence base). Prose-only encoding of Pitfall #9 sub-classes in HANDOFF §8 required producer SELF-CHECK at the right moment; the 5-event empirical base proved producer self-check is necessary-but-insufficient. Catch-time lag = 1-4 days (post-hoc gap-check). User-direction "let's create an agentic system that triggers these events rather than relying on skills. Research how to use langchain or related python libraries" → research grounding via `_research/agentic-orchestration-architecture-2026-05-16.md` (35 citations) → user-provided AppLaunchpad source spec at `agentic-architecture.md` → gap analysis at `_research/applaunchpad-udm-gap-analysis-2026-05-16.md` (18-section REUSE/ADAPT/SKIP/DECISION-NEEDED matrix) → user decisions D1-D6 (high-ROI subset only; no orchestrator / no substrate / no Slack).

**Decision**: Adopt the high-ROI subset of AppLaunchpad's agentic-software-factory pattern, scoped to (a) blindspot ledger YAML encoding + protocol + CLI scanner per AppLaunchpad §12 Layer 3, and (b) conservative Claude Code hooks per AppLaunchpad §12 Layer 1. Defer full AppLaunchpad replica (orchestrator + event store + ingester + Slack + cockpit + substrate per AppLaunchpad §§ 5-13) unless and until the high-ROI subset proves durable value over ≥1 week of operator use.

**Specifically locked**:

1. **Blindspot ledger location**: `docs/migration/blindspots/{ledger.yml, protocol.md}` (per user D-answer choice "docs/migration/blindspots/ (Recommended)" 2026-05-16). REJECTED alternatives: AppLaunchpad source-spec convention `playbooks/blindspots/` (would split discipline-content from `docs/migration/` canonical tree); `.claude/blindspots/` (would obscure from human readers browsing docs).

2. **Detection-rule implementation tier**: 4 of 15 rules implemented Phase 1 (`check_9j_b_item_status_render` + `check_9o_recursive_exemption` + `check_9n_convention_registration` + `check_9h_off_by_n_line_citation`). 11 remaining rules deferred to Phase 2 per B-295 sub-item 7 (require schema parsing OR multi-doc cross-reference infrastructure beyond pure-stdlib Phase 1 scope). Transparency-via-skipped-checks: CLI reports skipped entries explicitly per query invocation so producers know exactly which rules are not yet enforced.

3. **Hook scope**: conservative (per user D-answer choice "Conservative (Recommended)" 2026-05-16). `PreToolUse` warn-only on 6 protected primary docs (`03_DECISIONS.md` / `NORTH_STAR.md` / `02_PHASES.md` / `CHECKS_AND_BALANCES.md` / `HANDOFF.md` / `CLAUDE.md`); `PostToolUse` auto-invoke `query_blindspots --file <relative_path>` on Edit/Write to source files only (10 source dirs: `tools/ data_load/ cdc/ scd2/ orchestration/ schema/ extract/ observability/ utils/ migrations/`; skips test files + docs + `.claude/`); `SessionStart` optional log to `_session_logs/` if directory exists. ALL hooks exit 0 (no blocking; warn-only per first-deployment safety). REJECTED alternatives: Aggressive (would fire on every Edit/Write to docs/migration/ adding noise to normal doc editing); Opt-in only (would defeat the discipline by making mechanism manual-trigger).

4. **CLI execution classification**: Manual × Recurring + Automated-via-Claude-Code-hook (NEW category; not in existing canonical `ONE_OFF_SCRIPTS.md` / `phase1/02_configuration.md §5.1 Automic frozen-N` taxonomy). Tracked in `ONE_OFF_SCRIPTS.md §"Ad-hoc operator tools"` as closest fit; full classification rationale documented in that entry. Not Automic-scheduled (no fixed `*/N` schedule); not one-off (recurring); hook-driven invocation is novel to UDM as of D114.

5. **Substrate**: dev-workstation only (Windows 11). `.venv\Scripts\python.exe` invocation in `.claude/settings.json` hooks. Mac/Linux dev workstations have known limitation (silent hook failure for `protect-primary-docs.py` and `session-start-logger.py`; `auto-verify-step-10.py` has `sys.executable` fallback). Per D103 security model, Claude Code is dev-workstation only; not on test/prod RHEL servers. Cross-platform hook support deferred per B-295 sub-item 15.

6. **Audit row backing**: `_session_logs/cli_query_blindspots_<date>.log` JSON-line append-only (per `_emit_audit_row` in `tools/query_blindspots.py`). DB-side `General.ops.PipelineEventLog` `CLI_QUERY_BLINDSPOTS` event type registered in CLAUDE.md L197 CLI_* family registry (15 → 16) but NOT YET wired to DB write (Phase 2 work when SQL Server connectivity available outside production pipeline context).

7. **Composition with existing discipline mechanisms**: AUGMENTS, does NOT replace. The ledger is one data source that `udm-gap-check` / `udm-step-10-verifier` / Pattern F audit / hard rule 14 cascade Step 2 can query. Future `udm-gap-check` SKILL.md update (B-295 sub-item not yet enumerated; Phase 2 candidate) will explicitly invoke the ledger as first check; current state = ledger callable but skill not yet wired to invoke it.

**Trade-offs accepted**:

- **NOT building full AppLaunchpad replica**: orchestrator + event store + ingester + vault frontmatter + Slack + cockpit + substrate are all deferred. The high-ROI subset addresses the 5-event Pitfall #9.o pattern via executable detection without the ~10-15-day infrastructure cost of full replica. If subset proves insufficient, full replica remains a clean re-evaluation point (the gap analysis at `_research/applaunchpad-udm-gap-analysis-2026-05-16.md` is the resume-from-here artifact).

- **4-of-15 detection rules implemented (Phase 1)**: 11 remaining rules registered in ledger but report as "skipped" in CLI output. Honest gap disclosure rather than false-completeness pretending. Phase 2 work to extend remaining rules sequenced after ≥1 week empirical use of Phase 1 4-rule subset.

- **Warn-only hooks (no blocking)**: first-deployment safety preferred over enforcement. If false-positive rate proves low + signal proves valuable over time, future D-N could promote hooks from warn to block (e.g., `--live` mode default for pre-commit). Currently dev-workstation only per D103.

- **DB-less audit row (file-based)**: dev-workstation has no `General.ops.PipelineEventLog` connectivity outside pipeline runs. `_session_logs/` JSON-line append serves as audit substrate. When pipeline-environment integration becomes scope-relevant, future D-N can promote audit-row writes to DB-side.

- **Heuristic detection rules** (not semantic): regex + structural checks. Producer review distinguishes true vs false positives. Documented limitation in `protocol.md` §Limitations.

- **Non-Pull-Based**: AppLaunchpad Principle D (Pull-not-Push) explicitly NOT adopted. UDM remains push-based (parent agent invokes skills when user types trigger phrase). Pull-based architecture requires orchestrator + substrate (deferred per #5 + user D-answer D2 SKIP).

**Cross-references**:

- AppLaunchpad source spec: `agentic-architecture.md` at repo root (920 lines; user-provided; §12 Layer 3 blindspot ledger pattern is the direct source for this adoption)
- Research grounding: `_research/agentic-orchestration-architecture-2026-05-16.md` (35 primary-source citations; LangGraph vs CrewAI vs AutoGen vs Anthropic SDK comparison; recommends Claude Code native over LangGraph for this project's scope)
- Gap analysis: `_research/applaunchpad-udm-gap-analysis-2026-05-16.md` (18-section REUSE/ADAPT/SKIP/DECISION-NEEDED matrix; resume-from-here artifact if full-replica adoption ever resumed)
- Implementation: `tools/query_blindspots.py` (574 lines per actual `wc -l` at 570ac67) + `docs/migration/blindspots/{ledger.yml, protocol.md}` (481 + 244 lines per actual `wc -l` at 570ac67; original D114 narrative had stale 379+220 counts from f699250 build-time per Pitfall #9.k arithmetic-propagation drift caught at instance-6 gap-check 570ac67-post-hoc) + `.claude/hooks/{protect-primary-docs.py, auto-verify-step-10.py, session-start-logger.py}` + `.claude/settings.json` hook handlers
- Tests: `tests/tier0/test_query_blindspots.py` (9 tests) + `tests/tier1/test_query_blindspots_checks.py` (25 tests including 7 added at commit `d645cee` for B-295 sub-items 8 + 9 fixes)
- Tracked closures: B-294 (this adoption itself; ⚫ CLOSED `f699250`) + B-293 (backfill from compacted-session gap surfaced by tool's first production run; ⚫ CLOSED `f699250`) + B-295 sub-items 8 + 9 (regex tightening + scope-awareness; ⚫ CLOSED `d645cee`)
- Forward-tracked open work: B-295 16-item follow-up cohort (10 remaining sub-items as of D114 lock; 4-6 cycles forecast per user calibration question 2026-05-16)
- Composition: CLAUDE.md hard rules 9 (progress-logger) / 11 (gap-check mandatory) / 13 (planning-discipline sub-agent inheritance) / 14 (post-edit verification cascade + anti-rationalization clause); HANDOFF §8 Pitfall #9.a-9.o canonical prose source; `udm-step-10-verifier` skill (composes with ledger 9.n check); `udm-gap-check` skill (Phase 2 will invoke ledger as first check); Pattern F `udm-cascade-auditor` (proposed Trigger H = ledger queries at round close-out per `_research/applaunchpad-udm-gap-analysis-2026-05-16.md` recommendation)
- Per D62 + D113 + D89-D91 + D95-D99 precedent: process-infra D-number locks same-session as the discipline it formalizes; D111's 🟡-first operational-infra rule does NOT apply (process-discipline scope per D111 body text)

**Reversibility**: reversible. If the high-ROI subset proves insufficient OR produces false-positive fatigue (R33 candidate per design-reviewer 2026-05-16) OR the operator burden exceeds benefit, future D-N can supersede D114 (retire `tools/query_blindspots.py` + hooks + `blindspots/` ledger; revert to prose-only HANDOFF §8 discipline). Pre-revert escape hatch: ledger remains valuable archival reference even if execution mechanism retired.

**Risk delta (per D61)**:

- **NEW R33 candidate**: blindspot-ledger false-positive fatigue. The 9.o + 9.h checks have inherent over-fire potential (descriptive vs applicative context distinction is heuristic). If operators learn to dismiss matches without review, detector loses credibility. Severity Low × Medium = 2. Mitigated empirically by B-295 sub-items 8 + 9 fix (10→1 match reduction on BACKLOG.md; 90% false-positive reduction); will revisit if pattern recurs after Phase 1 4-rule subset has ≥1 week operator use.
- **MITIGATED R16 sub-class** (CCL compliance honor-system): `auto-verify-step-10.py` hook mechanically invokes the ledger on every source edit, shifting catch-time from honor-system post-hoc to at-edit-time for the 4 implemented checks. Partial mitigation (11 of 15 rules still unimplemented). R16 score unchanged but sub-class of catch-time concern partially addressed.
- **DE-ESCALATED R28 sub-class** (cascade self-attestation gap): `protect-primary-docs.py` adds a low-friction reminder whenever a protected primary doc is edited, providing structural defense against unauthorized cascade edits. Not full mitigation of R28; de-escalates the subclass of "cascade edit proceeds without awareness."

**See also**: `BACKLOG.md` B-293 / B-294 / B-295 + `_validation_log.md` 2026-05-16 entries (AppLaunchpad adoption + B-295 sub-items 8 + 9 closure) + HANDOFF §8 Pitfall #9.o + AppLaunchpad source spec `agentic-architecture.md` + research artifacts above + `_session_logs/cli_query_blindspots_<date>.log` (live audit trail).

---

## How to Add a Decision

1. Increment the next D-number
2. Set status to 🟡 Proposed
3. Capture: driver (what prompted it), decision (what was chosen), rationale (why), trade-offs (what we accept), and any links to research or prior decisions
4. After sign-off, update status to 🟢 Locked
5. If superseding an earlier decision, update that decision's status to ⚫ and link forward
