# UDM Pipeline Migration — Edge Case Register

Consolidated catalog of every edge case identified during planning. Six series, each prefixed by an identifier:

- **M-series**: Math / lookback / lateness
- **S-series**: SCD2 reliability
- **I-series**: Idempotency
- **N-series**: Network drive / Parquet
- **P-series**: PII / encryption
- **G-series**: Gap detection / outage recovery
- **D-series**: 2x/day cadence
- **F-series**: Failover / cross-server parity
- **V-series**: Vault provenance

Each row: edge case description, current handling status, mitigation.

## Status legend

- ✅ Mitigated in current/proposed architecture
- 🟡 Mitigation planned (specific phase)
- 🔴 Open — needs decision or design work

---

## M-Series: Math / Lookback / Lateness

| ID | Edge case | Status | Mitigation |
|---|---|---|---|
| M1 | Source has zero late-arrivals (all `LASTMOD = BUSINESS_DATE`); `L_99 = 0` | ✅ | Floor at 7 days handles weekly batch resilience and source clock-skew |
| M2 | Heavy bimodal late-arrivals (daily updates within 1 day + month-end batch 30 days later) | ✅ | Measure on 12-month window; use `L_99.9` for tables with known infrequent backfills; P3-4 weekly reconciliation as residual safety net |
| M3 | `L_99 > L_time_max` — time budget can't fit quality target | 🟡 | Operator escalation; log WARNING when clamp fires; options: increase `T_max`, accept lower `P_target`, or upgrade to log-based CDC |
| M4 | Unreliable `LASTMOD` column (not always bumped) | ✅ | LT-2 modified-date sweep + P3-4 weekly full reconciliation; math used as lower bound only |
| M5 | Negative `LASTMOD - BUSINESS_DATE` (clock skew) | ✅ | Filter `WHERE LASTMOD >= BUSINESS_DATE` in measurement query |
| M6 | Source backfill of data older than lookback | ✅ | Out of scope for math; triggered manually via `tools/backfill.py` (R-13); detected by P3-4 |
| M7 | Schema evolution mid-window | ✅ | B-3 metadata flag suppresses E-12 false alarm during expected mass-update wave |
| M8 | DST / timezone shift mid-window | ✅ | TRUNC consistent across measurement and extraction (P3-2) |
| M9 | `L_99` shifts dramatically between measurement runs | 🟡 | Re-measure quarterly; alert if measured `L_99` differs from configured by >25% |
| M10 | Holiday / weekend calendar gaps | ✅ | Convention: measure and configure in calendar days (not business days); document |
| M11 | First run of a new table, no `L_99` data | ✅ | Bootstrap with `LookbackDays = max(business_min, 30)` for first 90 days, then re-measure |
| M12 | Truly immutable history table (`L_99 = 0` for real) | ✅ | Per-table override: `LookbackDays = 1` for documented immutable tables |

---

## S-Series: SCD2 Reliability

| ID | Edge case | Status | Mitigation |
|---|---|---|---|
| S1 | Two consecutive runs with same source state produce different Bronze versions | ✅ | Hash compare; Tier 3 replay test as regression gate (Phase 2) |
| S2 | Crash between Bronze INSERT and UPDATE leaves duplicate active rows | ✅ | E-2 INSERT-first design + B-4 orphan cleanup |
| S3 | Crash between close-old and activate-new leaves zero active rows transiently | ✅ | B-14 documented; defensive query pattern: `ROW_NUMBER() WHERE rn=1` |
| S4 | Hash drift across Polars upgrade triggers mass false-positive new versions | 🟡 | Idempotency ledger gate at >50% update ratio without `schema_migration` flag → abort with operator override required |
| S5 | `UdmHash` and Stage `_row_hash` get out of sync | 🟡 | New invariant: SCD2 promotion verifies `Bronze.UdmHash == _row_hash` for matched PK before declaring "unchanged" |
| S6 | Source date column changes meaning (E-16 territory) | 🟡 | Quarterly source_type_drift check; `SchemaContract` table per source (Phase 4) |
| S7 | Cross-batch resurrection (closed in batch N, reappears in batch N+1) | ✅ | M3 / E-18 already handles; Tier 3 replay test |
| S8 | Manual Bronze write by operator (data correction outside pipeline) | 🟡 | Discourage; if unavoidable, log via `ManualCorrectionLog` for reconciliation correlation |
| S9 | Source business date in the future (data entry error) | 🟡 | Sanity range check: reject `business_date > today + 30 days`; quarantine to `General.ops.Quarantine` (W-17) |
| S10 | Pipeline runs with `force=True` after extraction guard fired | ✅ | Already supported; idempotent on unchanged source; `RECONCILIATION_OVERRIDE` event with operator + reason |
| S11 | Two pipeline workers on same table in parallel | ✅ | `sp_getapplock` (P1-2) prevents; second worker logs `Status='SKIPPED'` (OBS-3) |
| S12 | Bronze schema lags Stage (column added to Bronze for derived data) | ✅ | Documented invariant: Bronze schema must be a superset of source columns + SCD2 metadata; schema evolution flows source→Stage→Bronze, never reverse |
| S13 | Source emits same row twice in one extract (transactional race) | ✅ | S-1 dedup picks one via R-8 ordering; deterministic across re-runs |
| S14 | Reconciliation finds Bronze drift from source | 🟡 | Strengthen P3-4 to file `ReconciliationFinding` with operator-acknowledge gate before next pipeline run for that table; brakes-on-divergence pattern (Phase 4) |

---

## I-Series: Idempotency

| ID | Edge case | Status | Mitigation |
|---|---|---|---|
| I1 | Same `BatchId` reused after partial failure | ✅ | Idempotency ledger short-circuits `Status='COMPLETED'` rows; resumes `IN_PROGRESS` (Phase 1) |
| I2 | New `BatchId` after partial failure (operator chose not to retry old) | 🟡 | Startup recovery sweep surfaces `IN_PROGRESS`/`FAILED` rows for operator triage; `RECOVERED_ABANDONED` status documents the decision |
| I3 | Two concurrent runs with same `BatchId` (shouldn't happen under sp_getapplock) — **ledger** | ✅ | UNIQUE constraint on ledger key fails the second run fast (SP-7 catches 2627) |
| I3-vault | Concurrent SP-1 callers with same plaintext racing through lookup-then-INSERT — **vault** | ✅ | **v2 fix**: SP-1 uses `UPDLOCK + HOLDLOCK` to serialize callers through the read; try/catch on UNIQUE for defense-in-depth. UX_PiiVault_Lookup is filtered on `Status = 'active'` to interact correctly with the Status-flip retention pattern. |
| I3-tokenization | Same batch tokenized twice for same column (could produce conflicting NewTokensGenerated counts) — **PiiTokenizationBatch** | ✅ | **v2 fix**: UX_PiiTokenizationBatch_Identity UNIQUE on (BatchId, SourceName, ObjectName, ColumnName) prevents the second insert; calling code interprets as "already done" |
| I4 | BCP partial-write at byte level (network drop mid-load) | ✅ | Stage-check-exchange — write to `_inflight`, validate, atomic-rename. Crash leaves orphan inflight, never corrupts Stage |
| I5 | Hash collision between two semantically different rows | ✅ | SHA-256 + per-PK comparison ~1.6e-10 risk per PK per run (B-1); P3-4 column-by-column reconciliation catches collision-class drift |
| I6 | Hash drift across Polars / OS / locale upgrade | ✅ | polars-hash plugin (P2-1) deterministic across sessions; pinned in requirements.txt; Tier 1 regression test |
| I7 | Empty extraction | ✅ | P1-1 guard blocks CDC; ledger records `Status='SKIPPED'` |
| I8 | Source returns same PK twice in one extract | ✅ | S-1 dedup |
| I9 | Source returns NULL for a previously-non-NULL PK | ✅ | P0-4 filter |
| I10 | PK value changes type between runs | ✅ | P0-12 PK dtype alignment; alert on type change |
| I11 | Schema evolution between runs | ✅ | B-3 mass-update wave; expected; metadata flag |
| I12 | Pipeline runs 30 days, then backfills day 15 | ✅ | Idempotent at every layer if state unchanged; correct if state has changed |
| I13 | Snapshot (Parquet) re-INSERT for same `(pk, batch_id)` | ✅ | UNIQUE constraint on registry rejects; `MERGE WHEN NOT MATCHED` makes it silent |
| I14 | Delete idempotency under 30-day lookback (same date evaluated 30 times) | ✅ | Window-scoped + verify + trust-gated + re-entrant close (Pattern 4) |
| I15 | Re-running snapshot job for different `BatchId` over same source state | ✅ | Correct: snapshot table records observation events; multiple legitimate observations |
| I16 | Race between snapshot write and SCD2 promotion within a single batch | ✅ | Snapshot write happens after SCD2 completes; ledger gates ordering |
| I17 | Snapshot table never enabled, then enabled retroactively | 🟡 | Forward-only by design; one-shot job to backfill snapshots from Bronze available; `Synthesized=1` flag distinguishes |
| I18 | Resurrection in append-only Stage / Parquet | ✅ | E-18 + Parquet chain captures both delete and resurrection events |
| I19 | Partial idempotency-ledger failure (INSERT succeeds, UPDATE-to-COMPLETED fails) | 🟡 | Startup recovery sweep: rows `IN_PROGRESS` older than `2 × T_max` reset to `FAILED` with documented reason |
| I20 | Hash function changes between runs (e.g., upgrade SHA-256 to xxHash) | ✅ | Hard rule: requires planned migration; `_hash_version` column invalidates old comparisons; CLAUDE.md Do-NOT |
| I21 | `idempotency_ledger.ledger_step` re-entry hits Status='IN_PROGRESS' from a CONCURRENT worker (not stale from a prior crash) — should NOT short-circuit (other worker hasn't completed work) but should NOT FAIL silently either | ✅ | Round 3 § 4.1 `ledger_step` design: short-circuit only on Status='COMPLETED'; Status='IN_PROGRESS' raises `LedgerStepFailed` (caller decides retry-vs-escalate); startup_recovery_sweep distinguishes stale-from-crash vs concurrent via age threshold |
| I22 | Concurrent gate-table acquire via SP-3 (`PipelineExecutionGate_AcquireProd`) — two callers attempt simultaneous gate-acquire for same `(CycleType, CycleDate)` (I3 variant beyond vault / ledger / tokenization-batch facets) | ✅ | Per Round 1 SP-3 atomicity: `sp_getapplock` on `(@CycleType, @CycleDate)` serializes acquire; winner INSERTs the gate row + returns `@GateId` + `@BatchId`; loser hits UNIQUE `(CycleType, CycleDate)` violation in TRY/CATCH and returns "another instance acquired the gate" (matches SP-3 design L1531-1544). Per Round 2 § 5.1 D66 contract: SP-3 is the canonical acquire path for AM/PM cycles — clients NEVER reinvent the pattern. **Originally placed mistakenly in F-Series during Round 6 retroactive Pattern F close-out (2026-05-11); re-positioned to canonical I-Series at unscoped Pattern F audit (also 2026-05-11) per INSTANCE 1 finding. F-Series F24+1 entry referenced this I-Series row.** |

---

## N-Series: Network Drive / Parquet

| ID | Edge case | Status | Mitigation |
|---|---|---|---|
| N1 | Network drive unavailable during extraction | ✅ | Pipeline fails fast; same `BatchId` retries when network drive returns; no partial Stage state because Parquet is atomic |
| N2 | Parquet file written but registry insert fails | ✅ | `parquet_verify.py` walks directory tree, finds unregistered files, registers with `Status='created'` and triggers re-verification |
| N3 | Registry insert succeeded but Parquet write failed | ✅ | `parquet_verify` detects, marks `Status='missing'`; operator decides re-extract or accept gap |
| N4 | Two pipeline runs with same `BatchId` race-write same Parquet | ✅ | `sp_getapplock` prevents; UNIQUE constraint on registry; filename includes `BatchId` so physical writes don't collide |
| N5 | Schema evolves; old Parquet has different schema than new | ✅ | Each registry row stores `SchemaHash`; replay logic reads schema from Parquet metadata; `conform_to_schema` aligns |
| N6 | PII policy changes; column previously redacted now allowed | ✅ | `PiiPolicyVersion` per registry row; replay impossible to "recover" cleartext (by design) |
| N7 | Snowflake stage upload fails repeatedly | ✅ | Registry `SnowflakeStagePath IS NULL`; daily retry with backoff; never blocks Bronze writes |
| N8 | Audit query needs cold-tier Parquet | 🟡 | Restore step: move file to hot tier, update tier classification; future: Snowflake external table lazy load |
| N9 | Bronze SQL Server promotion succeeds but Snowflake mirror fails | ✅ | Bronze (SQL Server) is source of truth; Snowflake retries; reconciliation catches persistent drift |
| N10 | Row in Parquet but never made it to Bronze (SCD2 crash post-Parquet) | ✅ | Idempotency ledger detects `Status != 'COMPLETED'` for SCD2 step; restart re-runs SCD2 against existing Parquet |
| N11 | `parquet_writer` inflight file rename succeeds but `ParquetSnapshotRegistry` INSERT fails — orphan file on disk with no registry row pointing at it | ✅ | Round 3 § 1.1 raises `RegistryInsertConflict` (retryable) or `ParquetWriteCrash` (FATAL on rename failure); `parquet_verify` / `mark_missing` from § 1.3 allow operators to retroactively register existing inflight-renamed files |

---

## P-Series: PII / Encryption (Tokenization Vault)

| ID | Edge case | Status | Mitigation |
|---|---|---|---|
| P1 | Non-deterministic encryption breaks SCD2 hash compare | ✅ | Tokenization vault deterministic by design (lookup-before-insert); same plaintext → same token |
| P2 | Vault row deletion makes existing tokens unrecoverable (downstream Bronze tokens become orphan refs) | 🟡 | **Phase 1 v2 progress**: `OrphanedTokenLog` table (table 24 in `phase1/01_database_schema.md`) now exists with FK to PiiVault; tracks every Status flip with downstream impact summary. **Pending**: SP-10 EnforceRetention extended to write OrphanedTokenLog rows; CCPA deletion SP authored to do the same. Status flips to ✅ once SP wiring lands. |
| P3 | Vault corruption (catastrophic) | 🟡 | SQL Server AG replication + nightly encrypted offsite backup + weekly restore-test rehearsal (D24) |
| P4 | Vault read latency at scale | 🟡 | Heavy indexing on (PiiType, SourceName, PlaintextHash); batch lookups in pipeline; D7 fallback to TPM-sealed AES if performance degrades |
| P5 | Plaintext leakage in logs | 🟡 | Sanitize log handlers — never log decrypted payloads; lint rule + code review (Phase 1) |
| P6 | Token column width vs source column width | ✅ | Bronze token columns sized to `VARCHAR(40)` (GUID-derived tokens); narrower than typical PII source columns |
| P7 | GDPR right-to-erasure | 🟡 | Crypto-shredding equivalent: DELETE vault row → all downstream tokens become orphan references; cascade documented in runbook (Phase 4) |
| P8 | Audit trail of decrypts | ✅ | `PiiVaultAccessLog` written in same transaction as decrypt SELECT; stored procedure enforces |
| P9 | Cross-source PII match (same SSN in DNA and CCM) | ✅ | Vault key includes `SourceName` so default behavior is per-source isolation; cross-source match opt-in via separate stored proc with explicit operator authorization |
| P10 | Token re-issuance after vault restore from backup | 🟡 | Restore reverts to backup snapshot; new tokens minted between snapshot and restore are lost; downstream rows pointing to lost tokens become unrecoverable. Mitigation: nightly backup cadence + replication minimizes window |
| P11 | `pii_tokenizer` re-tokenizes plaintext after `pii_decryptor` returned None for `Status='purged_for_retention'` — must NOT recreate the same token (plaintext is gone, no decrypt path remains); MUST mint a new token + write fresh provenance | ✅ | Round 3 § 2.1 `tokenize_pii_columns` relies on SP-1's `UPDLOCK + HOLDLOCK + try/catch on UNIQUE` (per Round 1 v3); purged vault row's `Status != 'active'` does NOT match the filtered UX_PiiVault_Lookup index, so a new INSERT proceeds and mints a fresh token. Old purged row stays in PiiVault (D26 append-only) as audit trail. Caller sees two tokens for two distinct lifecycle phases |

---

## G-Series: Gap Detection / Outage Recovery

| ID | Edge case | Status | Mitigation |
|---|---|---|---|
| G1 | Pipeline returns from outage and finds gaps within lookback, but lookback was changed mid-outage | ✅ | Range scheduler picks new dates per current config; old gaps re-extract; subsequent shrink is a no-op |
| G2 | Two consecutive outages with successful days between | ✅ | Gap detector identifies all missing dates; range scheduler queues all by priority |
| G3 | Operator runs backfill for a date that was actually successful | ✅ | Idempotent: re-extracting unchanged source → zero Bronze writes; backfill logged with `IsReExtraction=1` |
| G4 | Source retention shorter than expected; pipeline missed beyond retention | 🟡 | Gap detector flags as "beyond source retention"; operator decision: accept gap or out-of-band data dump from source team |
| G5 | Vault was the cause of the outage | ✅ | All vault-dependent operations failed during outage; extraction couldn't start; on resume, normal recovery |
| G6 | Gap detector itself runs during outage | 🟡 | Detector runs from same server; first run after recovery surfaces all gaps; optional: separate monitoring host with read-only metadata access |
| G7 | Gap reported but date was never expected (table newly added) | ✅ | Detector excludes dates < `FirstLoadDate` |
| G8 | Source backfilled historical data during outage | 🟡 | Pipeline picks up days within lookback on resume; outside lookback caught by P3-4 weekly reconciliation |
| G9 | Outage longer than idempotency-ledger retention | ✅ | Stale `IN_PROGRESS` rows reset to `FAILED` at startup (I19 mitigation); recovery proceeds with new BatchIds; hash-compare gates double-write |
| G10 | `PipelineExtraction` not written for outage period | ✅ | Detector treats absence as `never_attempted`; distinct from `all_attempts_failed`; operator-facing severity classification |

---

## D-Series: 2x/day Cadence

| ID | Edge case | Status | Mitigation |
|---|---|---|---|
| D1 | Two pipeline runs on same day with same data (no source change) | ✅ | Each writes a Parquet snapshot (audit trail); Bronze sees unchanged hashes → no writes; registry has 2 rows; idempotent |
| D2 | AM run fails, PM run succeeds | ✅ | PM run picks up AM date via lookback; gap detector clears AM gap |
| D3 | Source mid-update during AM extraction | ✅ | AM sees partial state; PM sees corrected; SCD2 records two versions same day; T-1 SLA accepts intra-day fluctuation |
| D4 | AM and PM Parquet writes for same date | ✅ | Filename includes `BatchId`; AM and PM produce different filenames; no collision |
| D5 | Two same-day runs both detect same delete candidate | ✅ | First run closes Bronze (Flag=2); second sees already-closed; conditional MERGE no-ops; idempotent |

---

---

## DP-Series: Deployment Pipeline (added 2026-05-10 at Round 6 close-out per B121)

Edge cases for the dev/test/prod deployment workflow per Round 6 D84-D87. Distinct prefix from D-series (2x/day cadence) to avoid collision per Round 6 § 10.2 cycle 2 fix.

| ID | Edge case | Status | Mitigation |
|---|---|---|---|
| DP1 | Atomic symlink swap fails mid-deploy — `/opt/pipeline/current` points to incomplete tag dir | ✅ | `phase1/06_deployment.md` § 1.4 rsync completes BEFORE symlink swap; failed rsync leaves symlink at prior tag; swap itself is atomic via `ln -s <tgt> current.new && mv -T current.new current` (single `rename(2)` syscall — NOT `ln -sfn` which has race window per Capistrano #346) |
| DP2 | systemd restart fails — process won't start in new tag | ✅ | systemd retries 3x (`Restart=on-failure, RestartSec=30s, StartLimitInterval=3min, StartLimitBurst=3`); falls into `failed` state; alert fires; operator ROLLBACK per § 9.1. **Restart policy depends on D74 exit-code contract end-to-end** per § 9.3 — silent `sys.exit(0)` on logical failure = no restart, no alert, invisible failure |
| DP3 | Parity baseline drift detected post-deploy but not at deploy-time — sneaking through documented_exceptions window | ✅ | § 3.6 90-day exception expiry + RB-12 § 5 quarterly parity baseline refresh; `JOB_PARITY_EXCEPTION_NOTIFY` (B128 / B38 Round 7 amendment) fires 30-day pre-expiry notification |
| DP4 | Subprocess workers fail to inherit credentials (per D69 + § 1.7 invariant) — TPM2 unseal storm | ✅ | § 1.7 NOTE: subprocess workers inherit via pickle, NOT re-read GPG envelope; load test at § 5.6 catches this; `--workers N` spawn pattern preserves single-TPM2-unseal-per-process invariant per D69 |
| DP5 | Tier 0 smoke passes but Tier 1 fails in CI — false-clean deploy gate | ✅ | § 5.2 Tier 1 runs in CI pre-deploy; CI fail blocks promotion to next env per § 1.5 cadence; Tier 0 is the SMOKE gate (D67), NOT comprehensive Tier 1 coverage |
| DP6 | Time-skew between dev/test/prod servers — affects scheduled job sequencing | ✅ | NTP sync mandated per § 1.3; § 3.4 parity baseline includes server time drift check (informational tier); persistent skew >5s = WARNING-tier mismatch per D65 |
| DP7 | grub2/shim package update drifts TPM2 PCR 4; TPM2 unseal fails → Stage 1 of § 1.7 exits 2 (per D85) | 🟡 | § 3.5 PCR rationale note (PCR 4 = boot manager; drifts on monthly+ patch cadence); RB-12 § 3 re-seal workflow + alert routes to operator; B131 proposes streamlined re-seal runbook subsection |

---

## T-Series: Testing (added 2026-05-10 partial at Round 5 close-out + Round 6 close-out per B108 + B121)

Edge cases for the 6-tier test pyramid per Round 5 D79-D82 + Round 6 cycle 2 advisory.

| ID | Edge case | Status | Mitigation |
|---|---|---|---|
| T1 | Tier 0 smoke test drift — sketch updated in source spec but `tests/smoke/test_<X>.py` not refreshed; CI passes stale test that no longer matches contract | 🟡 | `phase1/05_tests.md` § 3.4 + `phase1/06_deployment.md` § 4.7 `verify_tier0_drift.py` full implementation (closes B58); Q7 quarterly audit per Round 5 § 8.2 |
| T2 | Tier 2 property test hits Hypothesis shrinkage budget — example fails reduction; "false" failure that's actually a real bug masked by shrinkage timeout | 🟡 | `phase1/05_tests.md` § 5.10 budget per module (`max_examples=200` default + `max_examples=1000` combinatorial-heavy + `deadline=10s`); pre-release bumps to `max_examples=5000` (release profile) per Round 6 § 7.11 |
| T3 | Tier 3 integration test produces flake (intermittent failure on Docker SQL Server fixture warmup) — false-positive failure rate impacts CI signal | 🟡 | `phase1/05_tests.md` § 1.5 coverage target ≥95% scenario pass rate per nightly; investigate >5% flake; `phase1/06_deployment.md` § 7.10 SQLAlchemy-style rollback per B115 + explicit CU pin per B116/B134 (`:2022-CU14-ubuntu-22.04` NOT `:latest`) |
| T4 | Hypothesis CI derandomized profile freezes fresh-edge-case discovery for weeks while test function stable — bugs hidden by deterministic-CI coverage gap | 🟡 | `phase1/06_deployment.md` § 7.11 + § 5.3 nightly profile (`derandomize=False`, `max_examples=500`, `deadline=20s`) runs in nightly CI stage; counterbalances `ci` profile's coverage-freeze property |

---

## F-Series: Failover / Cross-Server Parity

| ID | Edge case | Status | Mitigation |
|---|---|---|---|
| F1 | Test server config drift — has different Python lib versions than prod when failover fires | 🟡 | `tools/verify_server_parity.py` at pipeline startup; alert on drift; treat as deployment blocker |
| F2 | Test server has stale code at failover time | 🟡 | CI/CD deploys the same commit to all 3 servers; verify via `git rev-parse HEAD` parity check on startup |
| F3 | Watchdog incorrectly triggers failover during a slow-but-successful prod run | ✅ | 90-minute threshold tuned to absorb slow runs; sp_getapplock prevents double-write even if triggered erroneously |
| F4 | Failover fires while prod is recovering (race) | ✅ | sp_getapplock on (source, table) blocks the second runner; loser logs SKIPPED |
| F5 | Watchdog itself is down | 🟡 | Watchdog runs as systemd service with restart-on-failure; secondary watchdog on different server cross-monitors primary |
| F6 | Both prod AND test fail to start | 🔴 | Escalate to operator (RB-2 manual failover to dev); document as catastrophic outage |
| F7 | Network drive credentials differ between servers | ✅ | Cross-server parity rule (D27); verified on startup |
| F8 | Vault credentials differ between servers | ✅ | Same as F7 |
| F9 | Time skew between prod and test causes idempotency drift | ✅ | NTP/chrony cross-server sync mandated (D27 parity rule) |
| F10 | Failover writes Bronze rows with `_extracted_at` from test server clock vs prod's | ✅ | Both servers run NTP-synced time; ms-precision is irrelevant for SCD2 since UdmHash compare is value-based |
| F11 | Operator forgets to cutback after failover; test runs as prod indefinitely | 🟡 | Daily reminder cron when `PromotionLock` row is older than 24h; documented in RB-9 |
| F12 | Failover script SSH key compromised | 🔴 | SSH key sealed to TPM and rotated quarterly; documented in security baseline |
| F13 | Test server has different cron schedule than prod | ✅ | Cron files identical (D27); only role differs at runtime |
| F14 | Auto-failover triggers during scheduled maintenance window | 🟡 | Test pipeline reads `General.ops.MaintenanceWindow` table; suppresses failover if maintenance is active |
| F15 | Production stuck (heartbeat stale, process running) and test wants to fail over | ✅ | D33 cooperative cancellation: test sets CancellationRequested=1; prod self-terminates at next heartbeat |
| F16 | Production doesn't acknowledge cancellation within 15-min timeout | ✅ | Test logs CRITICAL, alerts operator, does NOT proceed automatically; manual decision required |
| F17 | Cancellation requested but production crashes before reading the flag | ✅ | sp_getapplock auto-releases on connection drop; test acquires gate via timeout-based reclamation |
| F18 | Test sets cancellation; production completes naturally between request and ack | ✅ | Test polls gate Status; if 'SUCCEEDED' between request and 15-min timeout: test exits cleanly, no failover needed |
| F19 | Cancellation flag stuck (test failed to clear) | 🟡 | Production checks: only honor cancellation if CancellationRequestedAt < ActualStartTime would mean prior cycle's cancellation; gate has UNIQUE on (CycleType, CycleDate) so flag is per-cycle |
| F20 | Two production pipelines somehow running on prod server (process duplication) | ✅ | sp_getapplock prevents both from acquiring gate; second exits with SKIPPED |
| F21 | GPG passphrase loss on a pipeline server (TPM2 hardware fault) — pipeline cannot decrypt `/etc/pipeline/credentials.json.gpg` at startup; pipeline refuses to start | 🟡 | Secondary `ops-breakglass` recipient on the envelope (per `phase1/02_configuration.md` § 3.1) provides recovery path; RB-12 key-rotation runbook (§ 3.4 stub) documents incident response; failover to operational server with working TPM2 per § 5.4. Surfaced by Round 2 D64 brainstorm. |
| F22 | Documented parity exception (`parity_baseline.json` `documented_exceptions[].expires_at`) elapses without renewal — `tools/verify_server_parity.py` flags FATAL drift; pipeline refuses to start at next AM/PM cycle | 🟡 | § 4.4 quarterly maintenance cadence; B38 — 30-day pre-expiry notification mechanism (cron + email/Slack) before expiration; tied to R18. Surfaced by Round 2. |
| F23 | Pipeline starts on a server with `MALLOC_ARENA_MAX` unset (per W-4 Do-NOT — would cause 10× memory bloat from glibc arena fragmentation) | ✅ | § 4.3 FATAL severity; `JOB_PARITY_VERIFY` synchronous prereq catches via `env_vars_required.MALLOC_ARENA_MAX` check; pipeline `sys.exit(1)` before any data extracted. Surfaced by Round 2; verified against `CLAUDE.md` § Deployment Requirements W-4. |
| F24 | Alert dispatcher invoked with `severity=fatal` AND zero channels available (e.g., ops-channel config missing, network partition isolates from Slack + PagerDuty + email) — tool must NOT silently swallow the failure | ✅ | Per Round 4 § 3.11 `alert_dispatcher.py` contract: zero-channels-available with severity=fatal → exit 2 + log-only audit row (`EventType='CLI_ALERT_DISPATCHER'` with `Status='FAILED'` + `Metadata.reason='no_channels_available'`) + operator escalation path via SP-3 `PipelineExecutionGate` (Status='FAILED' propagates to next AM/PM cycle gate-acquire); RB-9 operator playbook covers detection-via-cycle-failure pattern. Surfaced by Round 5 R5C1-4 advisory + Round 6 B98 → B108 tracking (closes the F-series side of B121; was tracked as "F25" planning placeholder, assigned canonical F24 at Round 6 retroactive close-out). |
| I22 (in F-Series — cross-ref) | **CROSS-REFERENCE to canonical I22 in I-Series above** — F-Series placement was a Round 6 retroactive Pattern F close-out mis-placement (2026-05-11); canonical I22 (Idempotency) row is in I-Series. F24 (alert dispatcher zero-channels-fatal) is the F-Series entry that pairs with this Round 6 retroactive B121-tracking. | ✅ | See canonical I22 row in I-Series above. |

---

## V-Series: Vault Provenance

| ID | Edge case | Status | Mitigation |
|---|---|---|---|
| V1 | Same plaintext appears in multiple columns of the same source table | ✅ | Single PiiVault row; multiple PiiTokenProvenance rows (one per column observed) |
| V2 | Same plaintext appears in different sources (DNA + CCM both have an SSN '123') | ✅ | Per-source vault keys (D6) — each source gets its own token; provenance rows show both observations under different tokens |
| V3 | Provenance row count grows unboundedly over years | 🟡 | Bounded by `(unique tokens × unique source/object/column triples)` — not per-row. For a stable schema, growth is logarithmic. Indexed by Token. Periodic vacuum review at 5+ year mark. |
| V4 | Provenance UPSERT fails (e.g. deadlock) | ✅ | Retry with backoff; tokenization succeeds even if provenance write fails (provenance is audit metadata, not load-bearing for the pipeline data flow) |
| V5 | Schema evolution adds a new PII column to an existing table | ✅ | First pipeline run after schema evolution: tokens generated for the column's plaintexts (existing where reused, new otherwise); provenance INSERT for the new (table, column) pair |
| V6 | Operator deletes a source table — provenance rows become stale | 🟡 | Periodic cleanup: rows with `LastSeenAt < N years ago` flagged for review; never auto-deleted (audit trail value) |
| V7 | Auditor asks "show me every place this SSN appears across all sources" | ✅ | Cross-source query: JOIN PiiVault on PlaintextHash to find all tokens for a plaintext, then JOIN PiiTokenProvenance to find observations. Audited via PiiVaultAccessLog. |
| V8 | GDPR right-to-erasure cascade | 🟡 | Erasing a vault row → query provenance for all (source, object, column) → coordinate erasure across each downstream object. Documented in runbook RB-4 / RB-6. |
| V9 | Provenance table corruption | ✅ | Same recovery path as PiiVault (RB-6); provenance is rebuildable from existing pipeline metadata + Bronze tokens |
| V10 | Tokenization happens for a file source, FilePath column needs to capture absolute path | ✅ | Schema includes FilePath NVARCHAR(1024); Hive-style snapshot path captured at provenance time |

---

## SI series — Self-Improvement Discipline edge cases (added 2026-05-11 per Round 8 D95-D99 close-out)

| ID | Description | Status | Mitigation |
|---|---|---|---|
| SI1 | Missing agentId in retrospective-collector input | ✅ | Orchestrator captures via Agent tool result; skill aborts 🔴 if absent per 8.A SKILL.md § 2.8 |
| SI2 | Specialty enum drift on a KNOWN existing value (e.g., `column-walks` plural or `column_walk` underscore) | ✅ | Skill validates against canonical enum; aborts 🔴 with valid-enum error |
| SI3 | Cycle-out-of-order in close-out gather | ✅ | Skill verifies cycle sequence; 🔴 if non-monotonic |
| SI4 | NEW specialty proposed by orchestrator (value not in canonical enum but addition intentional) | ✅ | Skill output CONFIDENCE LOW; "first observation; no action" |
| SI5 | Specialty with rising 🔴 catch rate but 0% false-clean — healthy not unhealthy | ✅ | Skill recognizes rising-catch as healthy signal |
| SI6 | Specialty never invoked (0 events EVER) | ✅ | Skill output: "deprecate candidate" |
| SI7 | Producer self-check directive exhausted (cannot be strengthened further) | ✅ | Skill proposes elevation to Gate 2 mandatory specialty |
| SI8 | Producer self-check over-fires (false-positive directive) | ✅ | Skill notes "directive over-fires; consider relaxing" |
| SI9 | Skill output proposes change that contradicts locked D-number | ✅ | Pre-flight check against `03_DECISIONS.md`; 🔴 abort |
| SI10 | Approved delta introduces fresh-instance bug class | ✅ | 8.F auto-revert at next round close-out + failed-delta documented |
| SI11 | User declines 50%+ proposed deltas in 2 consecutive rounds | ✅ | FREEZE the loop per SELF_IMPROVEMENT_DISCIPLINE.md § Bounds |
| SI12 | Multiple skills propose conflicting deltas | ✅ | User adjudicates at review; both deltas documented |
| SI13 | Skill confidence LOW persists for 3+ rounds | ✅ | Skill output: "insufficient evidence; consider deprecating" |
| SI14 | Cascade-audit-evolver finds Pattern F gap class not coverable by Layer 1 OR Layer 2 alone | ✅ | Propose joint Layer-1-script-extension AND Layer-2-prompt-strengthening |
| SI15 | Concurrent close-out invocations (multi-agent coordination) | ✅ | All 6 analysis skills are read-then-propose; only 8.F writes; serial invocation enforced |
| SI16 | Skill outputs older than 1 quarter become stale | ✅ | Quarterly review per `MAINTENANCE.md` re-grounds skills |
| SI17 | 8.F archive-write atomicity failure (archive write succeeds but main write fails or vice versa) | ✅ | Archive-FIRST atomicity contract — copy to `_archive/` BEFORE applying delta; verify archive checksum |
| SI18 | 8.F re-run idempotency (same approved batch invoked twice) | ✅ | Skill checks frontmatter `version:` against expected post-apply; idempotent re-run produces zero net writes |
| SI19 | `.claude/agents/_archive/` unbounded growth (over 10+ rounds × 7 skills × N versions) | ✅ | Quarterly archive-compaction per MAINTENANCE.md; retain last 4 versions per agent; older archives compressed to tar.gz |
| SI20 | User rejects ALL proposed deltas in a single round (100% NO) | ✅ | Cascade exits gracefully; no writes; INFO log; does NOT trigger SI11 freeze |
| SI21 | Pattern F frozen / D89/D90/D91 superseded — 8.G attempts invocation against deprecated discipline | ✅ | 8.G pre-flight check: if D89-D91 status ⚫ Superseded or FROZEN, skill ABORTS with INFO log |
| SI22 | Standing pre-approval — user grants "all PATCH-level deltas auto-approved going forward" | ⚪ | NOT supported by current design (D95 hard rule: human-in-the-loop per-delta per-round); escalate to D-numbered decision if requested |
| SI23 | Concurrent ledger edit corruption — `_reviewer_effectiveness.md` edited simultaneously | ✅ | 8.A acquires POSIX `fcntl.flock` LOCK_EX before append; retries 3× then aborts 🔴 |

Cross-refs: `docs/migration/phase1/08_sub_agent_self_improvement.md` § 10 (origin) + `docs/migration/SELF_IMPROVEMENT_DISCIPLINE.md` (loop documentation) + D95-D99.

---

## I24 — Multiple active SchemaContract rows for same (SourceName, ObjectName, ColumnName, ContractKey)

**Added 2026-05-11 at Round 1.5 close-out per D101 + R1.5C1-4 finding.**

**Description**: If migration script INSERTs a new SchemaContract row before setting `EffectiveTo` on the prior active row, both rows coexist with `EffectiveTo IS NULL` — violates the "exactly one active contract per key" invariant.

**Status**: 🟡 (mitigated via operator-discipline migration scripts; B170 tracks structural fix via filtered UNIQUE constraint).

**Mitigation**: 
- B170 — UNIQUE filtered constraint `UX_SchemaContract_ActiveKey (SourceName, ObjectName, ColumnName, ContractKey) WHERE EffectiveTo IS NULL` — prevents dual-active at DB level
- B171 — SupersededBy circular-reference detection at INSERT-time validates chain integrity
- Migration scripts wrap INSERT-then-UPDATE in BEGIN TRANSACTION / COMMIT (per D87 atomicity discipline)

**Cross-references**: D40 (schema evolution governance) + D92 (forward-only additive) + Round 7 § 4.5 joint migration script pattern + `phase1/07a_schema_contract_examples.md` § 6.3.

---

## SE-Series: Source-Exactness Invariants (added 2026-05-17 at source-exact Parquet redesign Phase A scope per D115 + D116 + B-373)

NEW 13th series (after M/S/I/N/P/G/D/F/V/DP/T/SI). Each SE-N entry encodes a binding invariant that Parquet writes MUST satisfy per user HARD REQUIREMENT 2026-05-17 ("Parquet files must be the exact copy of the data that was extracted from the source"). Verified via Tier 1 round-trip test per B-373.

| ID | Edge case / Invariant | Status | Mitigation |
|---|---|---|---|
| SE1 | Parquet column count must equal source query column count (no row count mismatch silently masking schema drift) | 🟡 | Schema-diff assertion at Parquet write time in `parquet_writer.write_snapshot()`; raises `SourceExactnessError` on mismatch; B-373 Tier 1 test |
| SE2 | Parquet column dtypes correspond 1:1 to source dtypes per documented mapping table (Oracle → Parquet per Oracle docs; SQL Server → Parquet per pyarrow defaults) | 🟡 | Documented exceptions: SQL Server DATETIME2(7) → Parquet timestamp[us] is factor-of-10 truncation (B-367; `allow_truncated_timestamps=True`); ConnectorX Oracle DATE overflow ≥ 2262-04-12 (B-366 defensive assertion); Oracle NUMBER(p>38) cannot be Parquet DECIMAL (rare; document) |
| SE3 | Parquet column VALUES (after PME decryption for PII columns in Phase B; plaintext in Phase A) byte-equivalent to source query result | 🟡 | Sample-based round-trip test per Parquet write at Tier 1 (B-373); Phase B adds decrypt-then-compare for PME columns |
| SE4 | NO additive columns in Parquet schema (`_row_hash`, `_extracted_at`, `_cdc_operation`, etc. — these are pipeline-internal artifacts, NOT source data) | 🟡 | `data_load/parquet_writer.py` enforces schema = source schema; pipeline metadata stored in `key_value_metadata` footer (per D116), NOT data columns |
| SE5 | Control characters (`\t`, `\n`, `\r`, `\x00`) preserved in Parquet string columns | 🟡 | Parquet handles control characters natively; `sanitize_strings()` is BCP-CSV-only (in-memory path); MUST NOT apply to DataFrame written to Parquet |
| SE6 | Source row count must equal Parquet row count (no row filtering during extraction-to-Parquet step) | 🟡 | Row-count assertion at Parquet write + `udm_row_count` key_value_metadata cross-check per D116 |
| SE7 | Source row order preserved (or documented sort key in Hive partition layout per D45.2) | 🟡 | Polars `DataFrame.write_parquet()` preserves row order; `_extracted_at` sort applied only at SCD2-input stage (in-memory; NOT in Parquet) |
| SE8 | Source adds NEW PII column mid-pipeline-life: Parquet files written BEFORE PiiColumnList update contain plaintext PII; files are immutable (Phase B PME-coverage-gap until retroactive re-extraction) | 🔴 | B-362 — author SE-8 + new RB-N "retroactive PME classification procedure"; notify operator on schema evolution ADD branch; identify Parquet window with new column plaintext; offer re-extraction-with-PME path. Phase B scope. |

Cross-refs: D115 (PII tokenization timing reorder) + D116 (extraction-timestamp via key_value_metadata) + `_research/r6-pme-extraction-time-2026-05-17.md` (R6 source-exactness verification patterns + R7 extraction-timestamp convention) + B-353 through B-373 (source-exact Parquet redesign brainstorm cohort) + `UDM_PIPELINE_PHASE_A_TOKENIZATION_REORDER_2026-05-17.md` (Phase A plan; canonical for SE-N enforcement).

---

## How to Add an Edge Case

1. Pick the appropriate series (M/S/I/N/P/G/D/F/V/SI/SE)
2. Increment the next ID in that series
3. Capture: description (one sentence), current status (✅/🟡/🔴), mitigation (what handles it or what needs to be built)
4. Add `Phase X` reference if the mitigation lands in a specific phase
5. If status is 🔴 (open), add a note to the next planning round
