# UDM Pipeline Migration — Testing Strategy

**Six**-tier test pyramid (Tier 0 added per D67, locked 2026-05-10). Each tier validates a different invariant; together they prove end-to-end correctness.

## Tier Summary

| Tier | Frequency | Runtime budget | What it proves |
|---|---|---|---|
| 0 — Build-time smoke | Every commit (CI pre-Tier-1) + manually at module/tool authoring | ≤5 sec per test; total Tier 0 stage ≤2 min | Module/tool imports without error; main function invocable with synthetic input; return shape matches documented interface; documented error modes raise expected exception; no silent failure paths. NO external dependencies (no Docker, no real DB, no network — pure / mock only). |
| 1 — Unit | Every commit | ≤5 min | Pure functions correct |
| 2 — Property-based | Every commit | ≤10 min | Idempotence at the function level |
| 3 — Integration replay | Every PR + nightly | ≤30 min | Idempotence end-to-end against fixture data |
| 4 — Crash injection | Pre-release | ≤2 hours | Convergence after failures at each documented crash point |
| 5 — Audit / compliance | Quarterly | manual | Auditor questions answerable; DR rehearsal |

---

## Tier 0 — Build-Time Smoke (per D67)

**Run**: at module/tool authoring time (immediately after writing code) + every commit via CI pre-Tier-1 stage.
**Budget**: ≤5 seconds per test; total Tier 0 stage ≤2 minutes across the full module + tool inventory.
**Tool**: pytest with mocked subprocess / mocked pyodbc cursor / synthetic Polars DataFrames.

**Tier 0 is the code-level parallel to D55's 5-gate doc-validation discipline.** It catches build-time bugs before they reach Tier 1; failure blocks any further build step.

### Canonical assertion set (6 assertions per Round 4 § 1.6 / D77)

Every Tier 0 smoke test asserts:
- (a) module/tool imports without error
- (b) `--help` returns exit 0 with non-empty stdout (CLI tools) OR main function is callable (modules)
- (c) arg parser accepts the canonical argument set without raising (CLI tools) OR public API accepts documented inputs without raising (modules)
- (d) dry-run / default mode does NOT call any side-effecting cursor (verified by asserting on mock cursor `execute` count)
- (e) `--apply` / side-effecting mode invokes the wrapped function (mocked) with expected positional + keyword args
- (f) exception → expected exit code mapping per Round 4 § 1.1 — `PipelineFatalError` → exit 2; `PipelineRetryableError` → exit 1; success → exit 0 (CLI tools) OR raises documented exception classes (modules)

### Pitfall: smoke ≠ comprehensive (per HANDOFF Pitfall #10)

Tier 0 is the runnability check; coverage point (d) — "no silent failure paths" — is systematically under-covered if Tier 0 sketches don't touch every declared Error mode. **Tier 0 SHOULD touch every documented exception, even if just with `pytest.raises(<Error>): main_function(<input that triggers Error>)`**. R19 (Tier 0 drift) materializes at sketch-authoring time if (d) is skipped.

Tier 1 is where comprehensive per-edge-case + per-error-path coverage lives. Tier 0 is the screen door, not the wall.

### Location convention

- Modules: `tests/smoke/test_<module>.py`
- CLI tools: `tests/smoke/test_tools_<tool>.py`

### Inventory

Per `phase1/05_tests.md` § 3, every Round 3 module (17 modules) + every Round 4 tool (11 CLIs) has a Tier 0 smoke test. Total: 28 Tier 0 tests at Phase 1 completion.

---

---

## Tier 1 — Unit Tests

**Run**: every commit via CI pre-merge.
**Budget**: 5 minutes.
**Tool**: pytest.

### Pure-function tests (representative list)

```python
# tests/unit/test_hash_determinism.py
def test_add_row_hash_deterministic_across_processes():
    """Hashing same DataFrame in two separate Python processes produces byte-equal output."""

def test_add_row_hash_independent_of_column_order():
    """P0-1 invariant: column reordering must not change hash."""

# tests/unit/test_pii_tokenizer.py
def test_tokenize_returns_same_token_for_same_plaintext():
    """Vault GET-OR-CREATE: same (PiiType, SourceName, plaintext) → same token across calls."""

def test_tokenize_decryption_roundtrip():
    """token → plaintext via vault join is byte-equal to original plaintext."""

def test_tokenize_different_sources_get_different_tokens():
    """SSN '123' from DNA and SSN '123' from CCM get distinct tokens (per-source isolation)."""

# tests/unit/test_parquet_writer.py
def test_parquet_write_read_roundtrip():
    """Polars df → parquet write → read → df is structurally identical."""

def test_parquet_inflight_atomic_rename():
    """Write to _inflight, rename, registry insert; crash mid-rename leaves orphan inflight, no registry row."""

# tests/unit/test_idempotency_ledger.py
def test_ledger_short_circuits_on_completed_status():
    """ledger.step() with prior COMPLETED row skips the body."""

def test_ledger_unique_constraint_blocks_concurrent():
    """Two simultaneous step() calls with same key — second raises IntegrityError."""

def test_ledger_recovery_sweep_resets_stale_in_progress():
    """Rows IN_PROGRESS older than 2x T_max → reset to FAILED on startup."""

# tests/unit/test_extraction_state.py
def test_is_date_trusted_returns_false_when_no_success_row():
    """No PipelineExtraction row → date is untrusted; deletes suppressed."""

def test_is_date_trusted_returns_true_with_one_success():
    """One SUCCESS row → date is trusted regardless of subsequent FAIL rows."""

def test_most_recent_success_picks_latest_attempt():
    """Three attempts (SUCCESS, FAIL, SUCCESS) → second SUCCESS wins."""

# tests/unit/test_idempotence_at_function_level.py
def test_sanitize_strings_idempotent():
    """sanitize(sanitize(x)) == sanitize(x) for any DataFrame."""

def test_filter_null_pks_idempotent():
    """f(f(x)) == f(x)."""

def test_dedup_source_pks_idempotent():
    """f(f(x)) == f(x)."""
```

### Coverage targets

- Every new module from Phase 1: ≥90% line coverage
- All idempotence-relevant transformation functions: 100% coverage
- All stored procedures (PiiVault_GetOrCreateToken, PiiVault_Decrypt, ledger_recovery_sweep): integration tests against test SQL Server

---

## Tier 2 — Property-Based Tests with Hypothesis

**Run**: every commit via CI pre-merge.
**Budget**: 10 minutes (configurable shrinkage budget).
**Tool**: pytest + hypothesis.

### Property: idempotence (the master test)

```python
from hypothesis import given, strategies as st
import polars as pl

@given(df=arbitrary_dataframe_strategy())
def test_pipeline_step_is_idempotent(df):
    """For every transformation f in the pipeline: f(f(x)) == f(x)."""
    once = transform(df)
    twice = transform(transform(df))
    assert once.frame_equal(twice)
```

Apply to:
- `add_row_hash`
- `sanitize_strings`
- `cast_bit_columns`
- `_filter_null_pks`
- `_coerce_blank_pks`
- `_dedup_source_pks`
- `conform_to_schema`
- `tokenize_pii_columns`
- `reorder_columns_for_bcp`

### Property: hash byte-stability

```python
@given(df=arbitrary_dataframe_strategy())
def test_hash_byte_stable_across_reorder(df):
    """Reordering rows then hashing produces same hash set."""
    h1 = sorted(add_row_hash(df)['_row_hash'].to_list())
    h2 = sorted(add_row_hash(df.sample(n=len(df)))['_row_hash'].to_list())
    assert h1 == h2
```

### Property: tokenization determinism

```python
@given(plaintext=st.text(min_size=1, max_size=200))
def test_tokenize_deterministic(plaintext, vault):
    """Same plaintext returns same token, even after restart."""
    t1 = tokenize(plaintext, 'EMAIL', 'DNA')
    t2 = tokenize(plaintext, 'EMAIL', 'DNA')
    assert t1 == t2
```

### Property: encryption roundtrip preserves all bytes

```python
@given(plaintext=st.text())
def test_encrypt_decrypt_roundtrip(plaintext, vault):
    token = tokenize(plaintext, 'EMAIL', 'DNA')
    recovered = decrypt(token)
    assert recovered == plaintext
```

### Edge case generators

- Numeric: NaN, ±inf, ±0.0, max/min int, max precision decimal (W-3)
- String: Unicode (NFC/NFD), tabs/newlines/null bytes, very long, empty, all-whitespace (B-6, W-2)
- NULL-heavy / NULL-empty patterns
- Polars Categorical columns (E-20)
- Mixed dtypes within a column (post-coercion)

---

## Tier 3 — Integration Replay Tests

**Run**: every PR (sub-set) + nightly (full).
**Budget**: 30 minutes per full run.
**Tool**: pytest + Docker SQL Server + tmpfs network drive simulator.

### Setup

- Docker SQL Server with fixture databases (UDM_Stage, UDM_Bronze, General)
- Fixture data: ~10K row table with realistic PII patterns and multi-version SCD2 history
- Mock network drive on tmpfs (fast cleanup between tests)
- Test PiiVault pre-populated with reference tokens

### Replay scenarios

```python
# tests/integration/test_replay_scenarios.py

def test_first_run_populates_bronze_and_parquet():
    pipeline.run(BatchId=1)
    assert bronze.row_count() == fixture.row_count
    assert parquet_registry.count(BatchId=1) >= 1

def test_no_op_rerun_zero_writes():
    """Same source state, same BatchId — second run is a no-op."""
    pipeline.run(BatchId=1)
    bronze_snapshot_1 = snapshot_bronze()
    pipeline.run(BatchId=1)  # Idempotency ledger short-circuits
    bronze_snapshot_2 = snapshot_bronze()
    assert bronze_snapshot_1 == bronze_snapshot_2

def test_no_op_rerun_new_batch_id_zero_bronze_writes():
    """Same source, new BatchId — Parquet adds a row, Bronze unchanged."""
    pipeline.run(BatchId=1)
    bronze_snapshot_1 = snapshot_bronze()
    parquet_count_1 = parquet_registry.total_count()
    pipeline.run(BatchId=2)
    bronze_snapshot_2 = snapshot_bronze()
    parquet_count_2 = parquet_registry.total_count()
    assert bronze_snapshot_1 == bronze_snapshot_2
    assert parquet_count_2 == parquet_count_1 + 1  # one new snapshot

def test_one_row_update_creates_one_new_version():
    pipeline.run(BatchId=1)
    fixture.update_row('PK1', new_value='X')
    pipeline.run(BatchId=2)
    versions_for_pk1 = bronze.query("WHERE pk='PK1' ORDER BY UdmEffectiveDateTime")
    assert len(versions_for_pk1) == 2
    assert versions_for_pk1[0].UdmActiveFlag == 0  # closed
    assert versions_for_pk1[1].UdmActiveFlag == 1  # active

def test_pk_delete_trusted_date_closes_bronze():
    pipeline.run(BatchId=1)
    fixture.delete_row('PK1')
    pipeline_extraction.mark_status('PK1_date', 'SUCCESS')
    pipeline.run(BatchId=2)
    pk1_active = bronze.query("WHERE pk='PK1' AND UdmActiveFlag=1")
    pk1_deleted = bronze.query("WHERE pk='PK1' AND UdmActiveFlag=2")
    assert pk1_active.empty
    assert len(pk1_deleted) == 1

def test_pk_delete_untrusted_date_suppressed():
    pipeline.run(BatchId=1)
    fixture.delete_row('PK1')
    pipeline_extraction.mark_status('PK1_date', 'FAIL')
    pipeline.run(BatchId=2)
    pk1_active = bronze.query("WHERE pk='PK1' AND UdmActiveFlag=1")
    audit_row = delete_evaluation_audit.query("WHERE pk='PK1'")
    assert len(pk1_active) == 1  # Still active
    assert audit_row.EvaluationOutcome == 'suppressed_no_success'

def test_resurrection_creates_op_R_version():
    pipeline.run(BatchId=1)
    fixture.delete_row('PK1')
    pipeline_extraction.mark_status('PK1_date', 'SUCCESS')
    pipeline.run(BatchId=2)
    fixture.add_row('PK1')
    pipeline.run(BatchId=3)
    versions = bronze.query("WHERE pk='PK1' ORDER BY UdmEffectiveDateTime")
    assert versions[-1].UdmScd2Operation == 'R'
    assert versions[-1].UdmActiveFlag == 1

def test_schema_evolution_new_column_handled():
    pipeline.run(BatchId=1)
    fixture.add_column('new_col')
    fixture.populate_random('new_col')
    pipeline.run(BatchId=2)
    bronze_columns = bronze.list_columns()
    assert 'new_col' in bronze_columns
    # All existing rows re-versioned because hash changed
    schema_migration_event = pipeline_event_log.query(
        "WHERE BatchId=2 AND Metadata LIKE '%schema_migration%'"
    )
    assert len(schema_migration_event) >= 1

def test_backfill_re_extraction_idempotent():
    """Re-extracting a date with IsReExtraction=1 produces zero Bronze writes
    if source unchanged."""
    pipeline.run(BatchId=1)
    bronze_snapshot_1 = snapshot_bronze()
    backfill.run(source='X', table='Y', date='2024-01-01')
    bronze_snapshot_2 = snapshot_bronze()
    assert bronze_snapshot_1 == bronze_snapshot_2

def test_pii_decrypt_logs_audit_row():
    pipeline.run(BatchId=1)
    request_id = pii_decrypt_request.create(reason='test')
    plaintexts = pii_vault.decrypt_bulk(request_id, tokens=['T1', 'T2'])
    audit_rows = pii_vault_access_log.query(f"WHERE RequestId='{request_id}'")
    assert len(audit_rows) >= 1
```

### Pass criteria

All scenarios green; no flakes (re-run a failed scenario must succeed). Snapshot diffs across scenarios must be byte-exact for idempotent operations.

---

## Tier 4 — Crash Injection

**Run**: pre-release.
**Budget**: 2 hours.
**Tool**: pytest + container kill orchestration.

### Approach

Run the pipeline in a Docker container against a fixture database. A second process injects SIGKILL at a specific point in execution. Restart the pipeline. Verify convergence.

### Crash boundaries (one test per)

| ID | Crash point | Expected post-restart state |
|---|---|---|
| C1 | Mid-extract (TLS drop simulation) | No Parquet, no registry row, no Bronze writes; ledger has no entry; restart succeeds |
| C2 | After Parquet `_inflight` write, before atomic rename | Orphan inflight file; `parquet_verify` cleans on next run |
| C3 | After Parquet rename, before registry INSERT | Orphan registered file; `parquet_verify` reconciles |
| C4 | After registry INSERT, before SCD2 step | Parquet exists, ledger says SCD2 IN_PROGRESS; restart resumes SCD2 from Parquet |
| C5 | Mid-SCD2 INSERT (Bronze partial commit) | Bronze has duplicate active rows; B-4 cleanup + retry restores |
| C6 | After SCD2 INSERT, before SCD2 close-old | Duplicate active; same as C5 |
| C7 | After SCD2 close-old, before activate-new | Zero active for affected PKs (B-14 transient window); next run recovers via E-2 |
| C8 | After SCD2 commits, before idempotency ledger UPDATE to COMPLETED | Ledger says IN_PROGRESS; restart sees Bronze already correct, idempotent |
| C9 | After ledger COMPLETED, before TABLE_TOTAL event | Event log incomplete; not affecting idempotency |
| C10 | Mid-Snowflake replication | Async retry; SQL Server Bronze unaffected |

### Pass criteria

After restart, Bronze converges to the same final state as a clean run with the same source. No data loss. No stale locks. Idempotency ledger ultimately reflects all completed steps.

---

## Tier 5 — Audit / Compliance Verification

**Run**: quarterly (Q1-Q9) + weekly (Q10 only — backup integrity per W-12 cadence) + ad hoc on auditor request.
**Budget**: full business day with operator (quarterly cycle); ~30 minutes per Q10 weekly run.
**Tool**: manual scripted procedures + reports.

### Q1 — Point-in-time query proof

Pick three random PKs. For each:
1. Query Bronze for the value as of a date 6 months ago: `WHERE @date BETWEEN UdmSourceBeginDate AND UdmSourceEndDate`
2. Cross-check against the Parquet snapshot for the corresponding batch
3. Assert the value matches

### Q2 — Pipeline activity proof

Pick three random business dates in the last quarter. For each:
1. Query `PipelineEventLog` for TABLE_TOTAL events on that date
2. Query `PipelineExtraction` for SUCCESS rows on that date (large tables only)
3. Assert proof of pipeline run for every (table, source) on that date
4. If gaps: cross-check against `ExtractionGapLog` for documented exceptions

### Q3 — PII redaction proof

1. Select 10 rows from Bronze with PII columns
2. Assert the values are tokens (40-char strings, format-validated)
3. Decrypt via `tools/decrypt_pii.py` with audit credentials
4. Assert plaintext is correctly recovered
5. Verify `PiiVaultAccessLog` has one row per decrypt request

### Q4 — Vault key/token rotation proof (annual)

1. Document current vault state (row count, oldest token CreatedAt)
2. Run a key/access credential rotation procedure
3. Pipeline runs daily for 1 week post-rotation
4. Assert old tokens still decrypt successfully
5. Assert new tokens are issued under the new credentials
6. Document in audit log

### Q5 — DR rehearsal (Runbook RB-7)

Quarterly server failover rehearsal. Pass criteria documented in RB-7.

### Q6 — CLI audit trail verification

Extends the Q1-Q5 vault-side surface with operator-CLI audit-row coverage per Round 4 D76 contract. Closes phase1/05_tests.md § 8.2 Q6 spec.

1. Pull last quarter's CLI rows: `SELECT BatchId, EventType, Metadata FROM General.ops.PipelineEventLog WHERE EventType LIKE 'CLI_%' AND CreatedAt >= DATEADD(quarter, -1, SYSUTCDATETIME())`
2. Pick 3 random rows
3. Parse `Metadata` JSON for each; verify `actor` is non-empty AND matches operator records (cross-reference HR / on-call rota for the row's date)
4. For audit-justification-required CLIs (`CLI_DECRYPT_PII` / `CLI_PROCESS_CCPA_DELETION` / `CLI_ENFORCE_RETENTION`): verify `justification` is non-empty AND follows the per-CLI-spec pattern
5. P5 compliance: scan `Metadata` JSON for plaintext PII patterns (SSN / credit-card / email-with-domain) — assert no matches

### Q7 — Tier 0 drift audit

Confirms the spec-vs-test contract enforced by `tools/verify_tier0_drift.py` (per B58) has not regressed since the prior quarter. Closes phase1/05_tests.md § 8.2 Q7 spec.

1. Run `python -m tools.verify_tier0_drift` (writes `tests/audit_reports/tier0_drift_<date>.md`)
2. Read the produced report; record overall verdict
3. Assert overall ≤ 🟡 (no 🔴 modules); for any 🟡: investigate cause; either align tests with spec OR open B-N for spec-vs-test divergence
4. Cross-reference any closed-or-deferred B-N from prior Q7 audits against the current report to confirm fixes landed
5. File the report in this quarter's audit-report file (cite the verify_tier0_drift output path)

### Q8 — Reviewer effectiveness ledger audit

Verifies the Round 8 self-improvement loop (D95-D99) is functioning: false-clean rates stay within bounds and approved deltas land. Closes phase1/05_tests.md § 8.2 Q8 spec.

1. Read `docs/migration/_reviewer_effectiveness.md` trend tables for the quarter
2. For each specialty role, compute false-clean rate = % of cycles where the specialty returned ✅ but post-cycle review (gap-check / Pattern E next cycle / Pattern F audit) found 🔴 they should have caught
3. Assert no role exceeds 25% over the quarter (per `udm-specialty-tuner` D95 RETIRE-OR-PAIR threshold); if exceeded, open B-N
4. Read `docs/migration/_agent_evolution/<agent>-changelog.md` for each prompt-versioned agent; verify all approved deltas from prior round close-outs landed (semver bumps applied per D98)
5. Note any specialty roles whose 6+-event evidence base shows false-clean rate >10% but ≤25% — REFINE candidate per D95

### Q9 — CCPA deletion proof

Verifies CCPA right-to-deletion (D30 + RB-10) is end-to-end honored: deletions logged, tokens unrecoverable post-deletion. Closes phase1/05_tests.md § 8.2 Q9 spec.

1. Pick 1 historical CCPA request from last quarter: `SELECT TOP 1 RequestId, SubjectIdentifier, Justification, RequestedBy, Actor, RequestedAt FROM General.ops.CcpaDeletionLog WHERE RequestedAt >= DATEADD(quarter, -1, SYSUTCDATETIME()) ORDER BY NEWID()`
2. Verify the row carries valid `RequestId` (UUID), non-empty `Justification`, non-empty `Actor` + `RequestedBy`
3. Pick 1-3 tokens from the deletion's `TokenList` (queryable via `PiiVault` rows whose `DeletedPerRequest = RequestId`)
4. For each token: invoke `python -m tools.decrypt_pii --token <T> --request-id <RequestId> --justification "Q9 quarterly audit"`
5. Assert each returns `VERDICT_CCPA_DELETED` OR `VERDICT_NOT_FOUND` — never `VERDICT_DECRYPTED` (per RB-10 contract; CCPA-deleted tokens MUST be unrecoverable post-deletion)

### Q10 — Backup integrity drill (weekly cadence)

NOTE: only Tier 5 drill that runs **weekly**, not quarterly. Mirrors the W-12 vault restore test cadence noted in CLAUDE.md. Closes phase1/05_tests.md § 8.2 Q10 spec.

1. Restore latest PiiVault backup to staging per backup runbook (cite the runbook in the drill report)
2. Query 100 random tokens from staging: `SELECT TOP 100 TokenId, EncryptedPlaintext FROM Staging.ops.PiiVault ORDER BY NEWID()`
3. Decrypt each via `python -m tools.decrypt_pii --token <T> --request-id <generated UUID> --justification "Q10 weekly backup integrity"` against the staging restore
4. Cross-check decrypted plaintext against expected (independent reference dataset OR `PiiTokenProvenance` audit trail in production)
5. Assert 100/100 match; on ANY mismatch: 🔴 incident — pause production CCPA / decrypt operations, file incident note in `RISKS.md`, investigate
6. File weekly summary at `docs/migration/audit_reports/Q10_weekly_<YYYY-WW>.md` (separate from quarterly Q1-Q9 file per the cadence mismatch)

### Reporting

Each quarter, file the audit verification report for Q1-Q9 in `docs/migration/audit_reports/QYYYY_QN.md` with:
- Date executed
- Operator + reviewer signatures
- Per-question pass/fail
- Any issues discovered + remediation taken
- Next quarter's focus areas

Q10 (weekly) files separately at `docs/migration/audit_reports/Q10_weekly_<YYYY-WW>.md` per its independent cadence.

A starting template lives at `docs/migration/audit_reports/_TEMPLATE_quarterly.md` (quarterly Q1-Q9) + `docs/migration/audit_reports/_TEMPLATE_q10_weekly.md` (Q10).

---

## Test Data Fixtures

### Standard fixture: `udm_test_fixtures`

A small Docker-loadable database with:
- 3 source tables (small, medium, large simulated)
- ~10K rows total with realistic PII patterns
- Multi-version SCD2 history (some PKs unchanged, some updated, some deleted, some resurrected)
- Edge case rows: NULL PKs, blank PKs, Unicode, multi-byte chars, future dates, very long strings
- Test PiiVault with reference token mappings

### Property-based generator: `arbitrary_dataframe_strategy`

Hypothesis strategy producing Polars DataFrames with:
- Arbitrary column counts (1-50)
- Arbitrary dtype mixtures
- Random NULL/empty/edge-value injection
- Polars-specific edge cases (Categorical, Date with timezone, etc.)

---

## Continuous Validation in Production

Beyond pre-release testing, these checks run continuously in production:

- **Hourly gap detector** (cdc/gap_detector.py) — flags any missed extraction date
- **Daily integrity check** — row count of `PiiVault` vs prior day; alert on unexpected drop
- **Daily ledger sweep** — find IN_PROGRESS rows older than `2 × T_max`; reset to FAILED
- **Weekly P3-4 reconciliation** — full-row column-by-column comparison against source
- **Weekly tier review** (`tools/parquet_tier_review.py`) — reclassify Parquet StorageTier
- **Weekly vault restore-test** — random sample 100 tokens, restore vault to staging, verify decrypt
- **Monthly lateness profiling** — re-measure `L_99` per large table; alert on >25% drift
- **Quarterly DR rehearsal** (RB-7)

These are not "tests" in the CI sense, but they are how we verify production stays correct after the test pyramid passes. They also feed back into the test suite when something is discovered (e.g., a new edge case becomes a Tier 1 test).

---

## How to Add a Test

1. Identify the tier (1-5 based on what's being tested)
2. Add the test in the appropriate file under `tests/`
3. Reference the relevant edge case (M/S/I/N/P/G/D series in `04_EDGE_CASES.md`) or decision (`03_DECISIONS.md`)
4. If the test discovers a new edge case during development, add it to the register
5. CI runs Tier 1+2+3 automatically on commit; Tier 4 runs pre-release; Tier 5 runs quarterly
