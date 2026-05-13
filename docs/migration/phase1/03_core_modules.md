# Phase 1, Round 3 — Core Modules

**Status**: 🟢 Locked (architectural-review path per D72 escalation rule — see D73 in `03_DECISIONS.md` and `_validation_log.md` 2026-05-10 Round 3 D72 convergence cycles 4-9 + close-out). Three-pass D56 iterative cycle (first-pass `a65ec4a14b134ef9d`, second-pass `aa4966b690d6103c5`, third-pass `a0d71fd460855a5c9`) PLUS 6 4-agent deep-validation cycles (4-9, 24 reviewer agents) PLUS column-walk specialist (B73, Reviewer M cycle 7) PLUS first all-clean batch (cycle 8 Q/R/S/T) PLUS Pitfall #9 cross-table-column-name-lift sub-class confirmed exhausted via 3 independent column-walks. Cycle 9 findings categorically clerical (aggregate-doc cycle-count drift, stale checklist labels) — module spec content structurally stable. Remaining 🟡 carry over to BACKLOG as B63 / B65 / B66 / B67 / B68 / B70 / B71 / B72 / B74 (all backlog-eligible per cycle 8 + cycle 9 independent reviewer classification). Round 3 Locked via D72 Option (b) — accept current state with explicit BACKLOG carryover.

This document is the Python module interface spec for the UDM pipeline build. It freezes ~15 module signatures + docstrings + error modes so Round 4 (Tools), Round 5 (Tests), and Round 6 (Deployment) can consume one consistent contract. **Implementation is deferred to Round 6 deployment** — this round produces interfaces only.

Round 3 is the design freeze that Round 6's deployment scripts implement against. Round 5's test suite is authored against these signatures (test-first per Round 5 scope). Per `02_configuration.md` § 0 scope: this round consumes the configuration locked by D63-D66 (`UdmTablesList` columns, `.env` keys, GPG envelope spec, parity baseline JSON, Automic gate-table contract).

## Read order for this round (per D62 Canonical Context Load)

Agents and skills working on Round 3 perform CCL Stage 1+2 first per `MULTI_AGENT_GUIDE.md` § Canonical Context Load (D62). Reading order specific to Round 3:

1. `docs/migration/CURRENT_STATE.md` — confirm Round 3 is in flight; Round 2 just locked
2. `docs/migration/HANDOFF.md` — locked vs in-flight; Pitfall #9 (fix-introduces-same-bug-class) is fresh — applies to this round
3. `docs/migration/NORTH_STAR.md` — pillar priority; Round 3 primarily advances **Idempotent** + **Operationally stable** + **Audit-grade** + **Traceability** pillars
4. `docs/migration/CHECKS_AND_BALANCES.md` — 5-gate validation discipline + CCL preamble
5. `docs/migration/RISKS.md` — R03 (single-engineer Python expertise) is most-relevant; this doc is also the mitigation evidence for R03 score reduction post-Round-3
6. `docs/migration/BACKLOG.md` — Round 3-adjacent items: B08 (SP-1 atomicity test — Round 5 dep but interface lives here), B01 (OrphanedTokenLog wiring — consumed by retention path), B33/B36/B37 (D62 follow-ups deferred)
7. `docs/migration/_validation_log.md` — past validation findings; Pitfall #9's three-round evidence is the most-recent lesson
8. **This document**
9. `docs/migration/phase1/02_configuration.md` (Round 2 — REQUIRED for Round 3): § 1 (UdmTablesList canonical inventory — every column the modules read or write); § 2 (.env keys consumed by every module); § 3 (GPG envelope spec consumed by credentials_loader); § 4 (parity baseline consumed by server_parity_verifier); § 5 (Automic gate contract consumed by main_*.py orchestrators)
10. `docs/migration/phase1/01_database_schema.md` (Round 1) — every SP signature this round wraps; every table this round reads / writes; canonical DDL is the source of truth per **Pitfall #9**
11. `docs/migration/03_DECISIONS.md` (search by D-number) — D2/D4/D5/D6/D11-D17/D22/D26/D33 are foundational; D63-D66 just locked; D67+ may be added
12. `CLAUDE.md` (project root) — existing module references (extract/, data_load/, cdc/, scd2/, schema/, orchestration/, observability/); BCP CSV Contract; Do-NOT rules

## Scope

**In scope** (this document):

- **§ 1**: Parquet layer — `parquet_writer`, `parquet_replay`, `parquet_registry_client` (3 modules)
- **§ 2**: PII / vault layer — `pii_tokenizer`, `pii_decryptor`, `vault_client` (3 modules)
- **§ 3**: Credentials + parity — `credentials_loader`, `server_parity_verifier` (2 modules; interfaces partially frozen in `02_configuration.md` § 3.3 + § 4.2)
- **§ 4**: Idempotency + extraction state — `idempotency_ledger`, `extraction_state` (2 modules)
- **§ 5**: Scheduling + lateness + gaps — `range_scheduler`, `lateness_profiler`, `gap_detector` (3 modules)
- **§ 6**: Observability — `sensitive_data_filter`, `log_handler` v2, `event_tracker` v2 (3 modules)
- **§ 7**: Snowflake — `snowflake_uploader` (1 module)
- **§ 8**: Cross-cutting patterns — error class hierarchy, retry semantics, resource ownership, test-fixture strategy
- **§ 9**: Edge case mapping — M / S / I / N / P / G / D / F / V series walk against Round 3 interfaces
- **§ 10**: Validation gates self-check (Gate 1 + Gate 5 + handoff to `udm-design-reviewer` for Gate 2)

**Out of scope** (deferred):

- Python implementation bodies — Round 6 deploy + Round 5 test-first authoring
- Operator-facing CLI scripts — Round 4 (Tools); they CONSUME these module interfaces
- Tier 1/2/3 test code — Round 5 (Tests); test signatures may be sketched in § 8.4
- Snowflake account setup — Phase 0 deliv 0.6
- Schema evolution governance procedure — Round 7
- DBA review of any Round 1 schema additions surfaced by Round 3 module needs (would supersede via new D-numbers; D34 greenfield permits if pre-deployment)

## Foundational decisions (Round 3 dependencies)

| # | Decision | Round 3 dependency |
|---|---|---|
| D2 | Stage dropped; Parquet snapshots replace it | § 1 parquet_writer / parquet_replay / parquet_registry_client |
| D4 | Network drive Parquet | § 1 parquet_writer writes here; § 4 idempotency_ledger gates the write |
| D5 | Snowflake-managed Iceberg | § 7 snowflake_uploader |
| D6 | In-house tokenization vault | § 2 pii_tokenizer / pii_decryptor / vault_client wrap Round 1 SPs |
| D11 | Empirical L_99 lookback | § 5.2 lateness_profiler |
| D12 | `ExtractionRangePolicy` table | § 5.1 range_scheduler |
| D13 | Delete-detection trust gate | § 4.2 extraction_state.is_date_trusted |
| D14 | `IsReExtraction` / `ExtractionAttempt` columns | § 4.2 extraction_state |
| D15 | Idempotency mandatory at every layer | § 4.1 idempotency_ledger is the central enforcer; every module obeys |
| D16 | Stage-check-exchange for crash-safe Parquet | § 1.1 parquet_writer inflight-rename pattern (per D45.2 Round 1) |
| D17 | Idempotency ledger pattern | § 4.1 idempotency_ledger; startup recovery sweep (I19) |
| D22 | Hourly gap detector | § 5.3 gap_detector (consumed by `JOB_GAP_DETECT` per D66 § 5.1) |
| D26 | Append-only PiiTokenProvenance | § 2 pii_tokenizer writes provenance |
| D33 | Cooperative cancellation | § 6.3 event_tracker monitors gate flag; every long-running module checks |
| D62 | CCL doctrine | This § "Read order" exists because of D62 |
| D63 | UdmTablesList new columns | § 2 reads `PiiColumnList`; § 4 reads `IsEnabled`; etc. |
| D64 | TPM2 passphrase storage | § 3.1 credentials_loader |
| D65 | Parity drift severity | § 3.2 server_parity_verifier |
| D66 | Automic job inventory + gate-table contract | § 4 + § 5 + § 6 modules consumed by AM/PM jobs; § 5.3 gap_detector consumed by `JOB_GAP_DETECT` |

## New decisions anticipated in this round

These will be captured via `udm-decision-recorder` (per D62 — recorder reads `NORTH_STAR.md` to confirm canonical pillar names case-sensitively):

| Proposed | Topic | Pillar(s) served (canonical from NORTH_STAR.md) |
|---|---|---|
| D68 | Error class hierarchy + retry semantics across Round 3 modules — `PipelineFatalError` (no retry, blocks pipeline) vs `PipelineRetryableError` (B-7 pattern: exponential backoff, max 3 attempts) vs per-module subclasses (CredentialsLoadError, ParityFatalError, VaultUnavailable, ParquetWriteCrash) | **Operationally stable**, **Idempotent** |
| D69 | Connection / cursor ownership model — `cursor_for(db_name)` context manager (existing pattern in `connections.py`) is canonical; `--workers` spawn subprocesses each with their own connection pool (no shared cursors across workers); never pass cursor objects across module boundaries | **Operationally stable**, **Idempotent** |
| D70 | Test fixture strategy (Round 5 dep frozen in Round 3) — Docker SQL Server fixture for Tier 3; pytest fixtures defined per-module; Hypothesis strategies for Tier 2 property tests; module interfaces include a `__test_fixtures__` constant naming the fixture set each module needs. **Tier 0 (per D67 — locked) is mandatory for every module at build time**; lives at `tests/smoke/test_<module>.py`. | **Audit-grade**, **Operationally stable** |
| D71 | Snowflake auth flow specifics (if surfaced via § 7) — RSA private key decrypted from GPG envelope; written to `/dev/shm/snowflake_pk_<pid>` mode `0600`; deleted post-session; Snowflake CONNECTION reads via path; never logs the path's contents | **Audit-grade**, **$120K/year ceiling** |

**Renumbering note** (2026-05-10): D67 was claimed by the build-time Tier 0 smoke-test discipline (user-directed addition mid-Round-3). The proposed Round 3 decisions originally numbered D67-D70 shifted to D68-D71. All cross-references in subsequent module specs (§ 1 – § 7) use the post-shift numbering; § 1 + § 2 specs authored before the shift cite D67 (error class) and D68 (cursor ownership) — these references will be updated at Round 3 close-out (tracked as a close-out task, not a 🔴 since the shift was announced before validation).

If module-interface surface uncovers additional choice points (e.g. `dataclass` vs `pydantic` for typed payloads; sync vs async I/O for Parquet write), more D-numbers will follow with full pillar mapping.

## Naming conventions (Round 3-specific)

- **Module file paths**: lowercase + `snake_case`, single underscore (`data_load/credentials_loader.py`, `extract/router.py`)
- **Class names**: `PascalCase` (`PipelineEventTracker`, `IdempotencyLedger`, `ParityReport`)
- **Function names**: `snake_case` with verb-first (`load_credentials`, `verify_server_parity`, `run_cdc`)
- **Constant names**: `UPPER_SNAKE_CASE` (`SCD2_UPDATE_BATCH_SIZE`, `UDM_SOURCE_END_SENTINEL`)
- **Dataclass / TypedDict / NewType**: `PascalCase` ending in role (`CredentialsDict`, `ParityCheck`, `ExtractionState`)
- **Exception classes**: `PascalCase` ending in `Error` (`CredentialsLoadError`, `ParityFatalError`, `VaultUnavailable` — exception to the `Error` suffix where domain term is clearer)
- **Module-level singletons**: lowercase (`logger`, `event_tracker`); module-private via leading underscore (`_credentials_cache`)
- **Test files**: `tests/<tier>/test_<module_name>.py` (e.g. `tests/unit/test_credentials_loader.py`)

## Common patterns (cross-module)

### Module-level contract structure

Every module spec in § 1 – § 7 follows this template (per `udm-data-engineer-review` skill's interface review pattern):

```markdown
#### Module: `path/to/module.py`

**Purpose**: <one-sentence what this module does>
**Consumes** (decisions / specs / configs): <D-numbers; UdmTablesList columns from § 1.x; .env keys from § 2.x; Round 1 SPs / tables>
**Produces** (side effects + return values): <DB writes; file writes; log writes; return-shapes>
**Idempotency** (per D15): <how same-input retry produces zero net writes>
**Error modes** (per D68): <FATAL exceptions; retryable exceptions; per-module subclasses>
**Concurrency** (per D69): <thread-safety; connection ownership; --workers behavior>
**Interfaces** (signatures + docstrings):

```python
# Actual Python signature here — frozen at Round 3 lock
def main_function(arg1: Type1, arg2: Type2 = default) -> ReturnType:
    """One-line summary.

    Detailed docstring with Args, Returns, Raises, Side effects, Idempotency notes.
    Cite Round 1 SP / Round 2 column / D-number references inline.
    """
```

**Test surface** (Round 5 dep): <fixture sets; Tier 1 / 2 / 3 / 4 / 5 test sketches>
**Cross-doc references**: <Round 1 SP-N; Round 2 § X.Y; CLAUDE.md gotcha references>
```

This template is normative — every module in § 1 – § 7 conforms.

### Pitfall #9 compliance (every interface)

Per HANDOFF Pitfall #9 (added at Round 2 close-out), every Python signature in this document that references a Round 1 / Round 2 column name, SP parameter, enum value, or constraint name MUST cite the exact canonical source (`file:line` or `file § X.Y row Z`). The producer Gate 1 self-check (§ 10.1) AND the Gate 2 independent reviewer (§ 10.3) both verify EVERY such reference against the canonical DDL. **No invented column names. No invented parameter names. No invented enum values.** Round 2's first-pass + second-pass found 5 🔴 across this exact failure mode — Round 3 explicitly defends against it via the citation requirement.

### Resource ownership pattern (per D69 proposed)

Every module that touches DB connections uses the existing `cursor_for(db_name)` context manager from `connections.py`. Cursors are NEVER passed across module-boundary function calls — the consumer opens its own cursor inside its own context. `--workers` spawns subprocesses each with their own connection pool; no shared state across workers. This pattern preserves D15 idempotency invariant under concurrency (W-8 sp_getapplock with `@LockOwner='Session'` is the second guard).

### Tier 0 build-time smoke test (per D67 — locked 2026-05-10)

Every module spec in § 1 – § 7 includes a **Tier 0 smoke test** in its "Test surface" subsection. Tier 0 runs at the moment the module is authored (build-time) and on every commit (CI). It is the immediate code-level parallel to the 5-gate doc-validation discipline (D55).

**Tier 0 requirements** (per D67):

- Lives at `tests/smoke/test_<module>.py`
- Runs in < 5 seconds; NO external dependencies (no Docker, no network, no real DB — pure / mock only)
- Checks: (a) module imports without error; (b) main public function invocable with synthetic dummy data; (c) return shape matches documented interface; (d) no silent failure paths
- Failure blocks any further build step

For § 1 + § 2 modules already specified above without inline Tier 0 mention (authored before D67 lock at 2026-05-10), Tier 0 sketches will be appended at Round 3 close-out (tracked as a close-out task). From § 3 onward, every module's Test surface line begins with a Tier 0 spec.

### Error class pattern (per D68 proposed — was D67 pre-shift)

```python
class PipelineError(Exception):
    """Base for all pipeline errors. Never raised directly."""

class PipelineFatalError(PipelineError):
    """No retry. Pipeline must exit. Used for: missing credentials, parity drift,
    irrecoverable corruption, decision violations. Always logged at CRITICAL."""

class PipelineRetryableError(PipelineError):
    """Retry with exponential backoff per B-7 cx_read_sql_safe pattern.
    Max 3 attempts. Base delay 2s. Used for: transient connection failures,
    deadlock victim, transient network. Logged at WARNING on retry; ERROR on
    final failure."""

# Per-module subclasses inherit from one of the above
class CredentialsLoadError(PipelineFatalError):
    """Raised by data_load/credentials_loader.py when GPG decrypt fails or
    schema_version doesn't match. Never retryable — operator must intervene."""

class ParityFatalError(PipelineFatalError):
    """Raised by tools/verify_server_parity.py on fatal-tier drift per D65."""
```

The hierarchy is part of D67's lock; every module in § 1 – § 7 specifies which classes it raises.

---

## § 1. Parquet layer (3 modules)

The Parquet layer is the central architectural piece of the new pipeline (D2 — Stage dropped, Parquet replaces it; D4 — network drive Parquet for snapshot storage). All three modules in this layer compose to provide: durable snapshots; replay-from-Parquet for Bronze rebuild (RB-8); canonical Parquet index via `ParquetSnapshotRegistry`.

### § 1.1 Module: `data_load/parquet_writer.py`

**Purpose**: Write a Polars DataFrame to a Parquet file at the canonical Hive-partitioned path with D45.2 config (ZSTD-3, 100-250 MB target, Hive partition, statistics enabled, inflight-rename pattern); register the file in `ParquetSnapshotRegistry`.

**Consumes**:
- Decisions: D2, D4, D15, D16, D26, D45.2, D45.3
- `.env`: `PARQUET_OUTPUT_DIR` (per `02_configuration.md` § 2.1.4)
- Round 1: `ParquetSnapshotRegistry` (per `01_database_schema.md` § 12 — table 12 — UNIQUE on `(BatchId, SourceName, TableName, BusinessDate)`)
- Round 1: `PipelineBatchSequence` (per D45.3 — caller pre-allocates BatchId)

**Produces**:
- Parquet file at `<PARQUET_OUTPUT_DIR>/<SourceName>/<TableName>/year=YYYY/month=MM/day=DD/<BatchId>.parquet`
- SHA-256 hash computed post-rename
- INSERT row in `ParquetSnapshotRegistry` with `Status='created'` (verification flips to `'verified'` in a separate call — see § 1.3)

**Idempotency** (per D15 + D16):
- `(BatchId, SourceName, TableName, BusinessDate)` UNIQUE on `ParquetSnapshotRegistry` prevents duplicate registry rows
- Re-call with same key raises `RegistryInsertConflict` (retryable per D68); caller queries registry first if retry intended
- Inflight-rename pattern (D16): write to `*.parquet.inflight` → fsync → atomic rename → fsync parent dir. Crash mid-write leaves inflight file but no registry row — recoverable

**Error modes** (per D68 proposed):
- `ParquetWriteCrash` (PipelineFatalError) — inflight file exists but rename failed (filesystem error); operator must inspect
- `RegistryInsertConflict` (PipelineRetryableError) — UNIQUE violation during registry INSERT (concurrent worker race); retry with backoff

**Concurrency** (per D69 proposed):
- `cursor_for('General')` per call; no shared state across module boundary
- Multiple `--workers` writing different `(SourceName, TableName, BusinessDate)` tuples are independent
- Inflight-rename + UNIQUE constraint together prevent same-tuple races

**Interface**:

```python
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import polars as pl

@dataclass(frozen=True)
class ParquetWriteResult:
    file_path: Path           # full path of the materialized .parquet file
    file_size_bytes: int
    row_count: int
    sha256: str               # full 64-char hex (per B-1)
    registry_id: int          # General.ops.ParquetSnapshotRegistry.RegistryId
    status: str               # 'created' — never 'verified' from this call

def write_parquet_snapshot(
    df: pl.DataFrame,
    *,
    source_name: str,                  # one of {'DNA', 'CCM', 'EPICOR', ...}
    table_name: str,                   # e.g. 'ACCT'
    business_date: date,               # Hive partition date (year=YYYY/month=MM/day=DD)
    batch_id: int,                     # from PipelineBatchSequence (D45.3)
    output_dir: Path | None = None,    # default: $PARQUET_OUTPUT_DIR (testing override only)
) -> ParquetWriteResult:
    """Write df to a Parquet file at the canonical Hive-partitioned path.

    Args: see § 1.1 for parameter semantics. business_date drives Hive partition;
        batch_id MUST come from PipelineBatchSequence (never client-side counter).
        df MUST be pre-sorted (PK ASC, _extracted_at DESC) per D45.2.

    Returns: ParquetWriteResult with file_path, file_size_bytes, row_count, sha256
        (full SHA-256 hex per B-1), registry_id, status='created'.

    Raises:
        ParquetWriteCrash: inflight file exists but atomic rename failed. FATAL.
        RegistryInsertConflict: UNIQUE violation on
            (BatchId, SourceName, TableName, BusinessDate) — retryable.

    Side effects:
        - Writes <output_dir>/<source_name>/<table_name>/year=YYYY/month=MM/day=DD/<batch_id>.parquet
        - INSERT into General.ops.ParquetSnapshotRegistry (Status='created')

    Idempotency (per D15 + D16): re-call with same key raises RegistryInsertConflict;
        partial write leaves inflight file without registry row (recoverable).

    Parquet config (per D45.2 — Round 1):
        - Compression: ZSTD level 3
        - Row-group sizing: target 100-250 MB
        - Statistics: MIN / MAX / NULL_COUNT / DISTINCT_COUNT enabled
        - Atomic-rename pattern: write to .inflight, fsync, rename, fsync parent

    Verification path: this module does NOT self-verify (producer / verifier
    separation per D55 spirit). `verify_parquet_snapshot()` in § 1.3 flips
    Status 'created' → 'verified' after independent SHA-256 + row-count check.
    """
```

**Test surface** (Round 5 dep):
- **Tier 0 smoke (per D67 — backfilled at Round 3 close-out per B55)**: assert (a) module imports; (b) `write_parquet_snapshot(df=synthetic_df, source_name='TEST', table_name='T', business_date=date(2026,1,1), batch_id=999, output_dir=tmp_path)` invokable with mocked pyodbc cursor; (c) returns `ParquetWriteResult` with all fields populated and correct types; (d) raises `RegistryInsertConflict` on mocked UNIQUE violation; (e) <5s, no real network drive / no real DB. Location: `tests/smoke/test_parquet_writer.py`.
- Tier 1 unit: given fixture DataFrame + tempdir, assert path / size / row count / sha256
- Tier 1 unit: idempotency — second call same key raises `RegistryInsertConflict`
- Tier 1 crash injection: kill mid-rename → inflight file present + registry row absent
- Tier 2 property (Hypothesis): for arbitrary DataFrame `df`, `result.row_count == len(df)`; `result.sha256 == hashlib.sha256(open(file_path, 'rb').read()).hexdigest()`
- Tier 3 integration: full extract → write → verify chain against Docker SQL Server fixture

**Cross-doc references**:
- Round 1: `phase1/01_database_schema.md` ParquetSnapshotRegistry DDL
- Round 2: `phase1/02_configuration.md` § 2.1.4 (`PARQUET_OUTPUT_DIR`)
- CLAUDE.md: B-1 (full SHA-256 hex requirement), D45.2 narrative
- D-numbers cited per Pitfall #9 discipline — every reference resolves

---

### § 1.2 Module: `data_load/parquet_replay.py`

**Purpose**: Read a registered Parquet snapshot and replay it through the SCD2 promotion path — used by RB-8 (Bronze rebuild from Parquet) and by Round 5 / Round 7 reconciliation when Bronze drift is detected.

**Consumes**:
- Decisions: D2, D4, D15, D45.2
- Round 1: `ParquetSnapshotRegistry` (read; verify `Status IN ('verified', 'replicated', 'archived')` before replay)
- Round 1: `IdempotencyLedger` (D17) — replay is gated on a `REPLAY` event row
- Round 2: `UdmTablesList` canonical inventory (read PK columns + `ExcludeFromHash` per SCD2-R10.2)

**Produces**:
- Polars DataFrame ready to feed `scd2/engine.py`'s `run_scd2()` or `run_scd2_targeted()`
- One `IdempotencyLedger` row with `EventType='REPLAY'`
- One `PipelineEventLog` event row (per OBS-7 metadata) with replay provenance: source registry_id, file_path, sha256, row_count

**Idempotency** (per D15 + D17):
- IdempotencyLedger UNIQUE on `(BatchId, SourceName, TableName, EventType='REPLAY')` prevents duplicate replay
- Re-call with same key short-circuits (returns the prior result via registry lookup); ledger Status='COMPLETED' is the signal

**Error modes**:
- `ParquetReplayError` (PipelineFatalError) — registry row exists but file missing OR file SHA-256 doesn't match registry (corruption — escalate to RB-6 vault recovery + RB-8 rebuild)
- `RegistryStatusInvalid` (PipelineFatalError) — caller attempted replay against `Status IN ('created', 'missing', 'purged', 'replication_failed')`; verifier hasn't run or file is gone
- `LedgerLockTimeout` (PipelineRetryableError) — sp_getapplock contention on replay; retry per B-7 pattern

**Concurrency**:
- `cursor_for('General')` for registry + ledger access
- `sp_getapplock` on `(SourceName, TableName, BatchId)` ensures one replay per batch
- Workers replaying different batches independent

**Interface**:

```python
from dataclasses import dataclass
import polars as pl

@dataclass(frozen=True)
class ReplayResult:
    df: pl.DataFrame              # ready for SCD2 promotion
    registry_id: int
    source_file: Path
    row_count: int
    sha256_verified: str          # matches registry SHA on success
    extracted_at: datetime        # original extraction timestamp from snapshot
    batch_id: int                 # the BatchId of the ORIGINAL snapshot (not the replay)

def replay_parquet_snapshot(
    *,
    source_name: str,
    table_name: str,
    business_date: date,
    original_batch_id: int,       # the snapshot's BatchId; NOT the replay's BatchId
    replay_batch_id: int,         # fresh BatchId for the replay event (for audit)
) -> ReplayResult:
    """Read a registered Parquet snapshot, verify SHA-256 against registry,
    return a Polars DataFrame ready for SCD2 promotion.

    Args:
        source_name / table_name / business_date / original_batch_id: identify
            the snapshot to replay (UNIQUE in ParquetSnapshotRegistry).
        replay_batch_id: fresh BatchId for the IdempotencyLedger event + audit.

    Returns: ReplayResult with df, file path, SHA confirmation, row count.

    Raises:
        ParquetReplayError: registry row exists but file missing / SHA mismatch.
            FATAL — corruption signal; escalate per RB-6 / RB-8.
        RegistryStatusInvalid: caller attempted replay against a non-verified
            snapshot. Verifier must run first.
        LedgerLockTimeout: sp_getapplock contention; retryable.

    Side effects:
        - INSERTs IdempotencyLedger row (BatchId=replay_batch_id, EventType='REPLAY')
        - INSERTs PipelineEventLog row with replay provenance metadata
        - Reads file from network drive; no writes to it

    Idempotency: re-call with same replay_batch_id short-circuits via ledger
        Status='COMPLETED' lookup. Re-call with different replay_batch_id
        produces a NEW audit event row (intentional — operator-triggered
        re-replays should be auditable).
    """
```

**Test surface**:
- **Tier 0 smoke (per D67 — backfilled at Round 3 close-out per B55)**: assert (a) module imports; (b) `replay_parquet_snapshot(source_name='TEST', table_name='T', business_date=date(2026,1,1), original_batch_id=42, replay_batch_id=999)` invokable with mocked registry + fixture Parquet file; (c) returns `ReplayResult` shape with df + sha256_verified + extracted_at + batch_id; (d) raises `ParquetReplayError` on simulated SHA-256 mismatch; (e) raises `RegistryStatusInvalid` on Status='created' fixture; (f) <5s, no real network drive / no real DB. Location: `tests/smoke/test_parquet_replay.py`.
- Tier 1: happy path — write → register → verify → replay → assert df equals original
- Tier 1: SHA mismatch — corrupt file post-write, assert `ParquetReplayError`
- Tier 1: status not verified — `RegistryStatusInvalid` raised
- Tier 2 property: replay(write(df)) ≡ df (round-trip identity on schema + content)
- Tier 3 integration: RB-8 Bronze rebuild scenario end-to-end

**Cross-doc references**:
- RB-8 (Bronze rebuild from Parquet) consumes this directly
- Round 5 reconciliation may call replay for drift recovery
- D2, D4, D15, D17, D45.2; OBS-7 metadata pattern; B-7 retry; W-8 lock pattern

---

### § 1.3 Module: `data_load/parquet_registry_client.py`

**Purpose**: Thin client for `General.ops.ParquetSnapshotRegistry` operations — registry verification (flip `created` → `verified`), status updates (`verified` → `replicated` → `archived`), purge handling (`purged`), failure handling (`replication_failed`, `missing`). Centralizes the Status enum transitions per the registry's 7-state lifecycle.

**Consumes**:
- Round 1: `ParquetSnapshotRegistry` (full status enum: `created`, `verified`, `replicated`, `archived`, `missing`, `purged`, `replication_failed`)
- Decisions: D15, D25 (registry as canonical Parquet index), D26 (append-only audit posture — Status flips, never DELETE)

**Produces**:
- UPDATE on `ParquetSnapshotRegistry.Status` with **per-transition audit columns from canonical Round 1 DDL** (verified post-deep-validation): `LastVerifiedAt` on verify; `PurgedAt` + `PurgedReason` on purge; `LastAccessedAt` on access events; `SnowflakeUploadedAt` on replicate. **There is no generic `StatusChangedAt` / `StatusChangedBy` pair** — each transition function writes the specific canonical column for its transition type. (Earlier draft of this doc invented `StatusChangedAt` / `StatusChangedBy` — Pitfall #9 sub-class "cross-table column-name lift", caught by 4-agent deep validation 2026-05-10.)
- `PipelineEventLog` event for each significant transition (verified / archived / missing / replication_failed)

**Idempotency**:
- Status transitions are idempotent at the row level (re-flip `verified` → `verified` is a no-op UPDATE)
- Each transition function validates the predecessor Status; invalid transitions raise `RegistryStatusInvalid`

**Error modes**:
- `RegistryStatusInvalid` (PipelineFatalError) — attempted transition from an incompatible predecessor (e.g. `purged` → `verified`)
- `RegistryFileNotFound` (PipelineFatalError) — verification target file is absent; mark as `missing` via separate transition
- `RegistryHashMismatch` (PipelineFatalError) — computed SHA-256 doesn't match registry; possible corruption

**Concurrency**:
- `cursor_for('General')` per transition
- Concurrent flips on the same row are serialized by SQL Server row locking + `CHECK` predicate on the UPDATE

**Interface**:

```python
from enum import StrEnum

class ParquetSnapshotStatus(StrEnum):
    CREATED = 'created'
    VERIFIED = 'verified'
    REPLICATED = 'replicated'      # mirrored to Snowflake / offsite
    ARCHIVED = 'archived'          # moved to cold storage per D30 retention
    MISSING = 'missing'            # file gone — operator escalation
    PURGED = 'purged'              # legitimately removed via D30 retention
    REPLICATION_FAILED = 'replication_failed'

@dataclass(frozen=True)
class ParquetVerifyResult:
    """Distinct from ParquetWriteResult — returned by verify_parquet_snapshot().
    ParquetWriteResult's `status` field contract is 'created' (write-only function);
    this dataclass's `status` field is 'verified' after successful SHA + row-count check.
    Introduced 2026-05-10 at Round 3 deep-validation to resolve type contract mismatch."""

    registry_id: int
    file_path: Path
    sha256_verified: str           # full SHA-256 hex; matches registry on success
    row_count_verified: int        # matches registry row count
    last_verified_at: datetime     # SYSUTCDATETIME() at verify moment; written to registry column LastVerifiedAt
    status: str                    # always 'verified' on successful return; raises otherwise

def verify_parquet_snapshot(
    *,
    registry_id: int,
    actor: str = 'pipeline',       # 'pipeline' / 'operator' / 'reconciliation'
) -> ParquetVerifyResult:
    """Flip Status 'created' → 'verified' after independent SHA-256 + row-count check.
    Raises RegistryStatusInvalid if Status is not 'created'.
    Raises RegistryFileNotFound if the registered file is absent.
    Raises RegistryHashMismatch if computed SHA-256 ≠ registry SHA.
    Idempotent: re-call after success is a no-op (Status already 'verified')."""

def mark_replicated(*, registry_id: int, replica_target: str) -> None:
    """Flip Status 'verified' → 'replicated'. replica_target identifies the destination
    (e.g. 'snowflake:UDM_BRONZE_MIRROR', 's3://offsite-bucket/...'). Writes audit event."""

def mark_archived(*, registry_id: int, archive_location: str) -> None:
    """Flip Status 'replicated' → 'archived' (D30 cold-storage retention)."""

def mark_missing(*, registry_id: int, detected_by: str) -> None:
    """Flip any non-purged Status → 'missing' when file is detected absent.
    Triggers RB-6 / RB-8 escalation alert."""

def mark_purged(*, registry_id: int, retention_batch_id: int) -> None:
    """Flip Status 'archived' → 'purged' at retention enforcement (D30, JOB_RETENTION_MONTHLY).
    retention_batch_id ties the purge to a JOB_RETENTION_MONTHLY event row."""

def mark_replication_failed(*, registry_id: int, failure_reason: str) -> None:
    """Flip 'verified' → 'replication_failed' when COPY INTO Snowflake fails. Retryable;
    operator can manually re-attempt or escalate."""

def query_snapshot(
    *, source_name: str, table_name: str, business_date: date, batch_id: int
) -> dict | None:
    """Lookup by (BatchId, SourceName, TableName, BusinessDate). Returns None if absent."""
```

**Test surface**:
- **Tier 0 smoke (per D67 — backfilled at Round 3 close-out per B55)**: assert (a) module imports; (b) each of 7 transition functions (`verify_parquet_snapshot`, `mark_replicated`, `mark_archived`, `mark_missing`, `mark_purged`, `mark_replication_failed`, `query_snapshot`) invokable with mocked cursor; (c) each raises `RegistryStatusInvalid` on invalid predecessor fixture (e.g. `mark_replicated` against Status='created' instead of 'verified'); (d) `query_snapshot` returns `None` for absent key fixture, returns `dict` for present key fixture; (e) <5s, no real DB. Location: `tests/smoke/test_parquet_registry_client.py`.
- Tier 1: each transition function — happy path + invalid-predecessor + idempotent re-call
- Tier 1: SHA mismatch detection in `verify_parquet_snapshot`
- Tier 2 property: status-machine state graph — every transition path produces valid Status; no path produces an invalid predecessor without raising

**Cross-doc references**:
- Round 1: ParquetSnapshotRegistry table 12 schema (status enum + audit columns)
- D25, D30, D45.2
- `JOB_RETENTION_MONTHLY` (per `02_configuration.md` § 5.1) calls `mark_archived` then `mark_purged`
- Snowflake mirror (Round 7 — § 7.1 below) calls `mark_replicated`

---

## § 2. PII / vault layer (3 modules)

These modules wrap Round 1's vault SPs (SP-1 GetOrCreateToken, SP-2 Decrypt) and the audit-log machinery (PiiVaultAccessLog, PiiTokenProvenance). Per D6: no cloud KMS; all crypto lives in `General.ops.PiiVault`. Per D26: provenance is append-only.

### § 2.1 Module: `data_load/pii_tokenizer.py`

**Purpose**: Per-row tokenize each cell in columns named by `UdmTablesList.PiiColumnList` (D63 § 1.2.2) via Round 1 SP-1 (`PiiVault_GetOrCreateToken`); append provenance rows to `PiiTokenProvenance` (D26); return a transformed DataFrame with tokens in place of plaintext.

**Consumes**:
- Decisions: D6, D26, D15 (idempotent — same plaintext + same source → same token)
- Round 1 SP-1 signature (`01_database_schema.md` L1319-1324, verified against canonical DDL per Pitfall #9): `@Plaintext NVARCHAR(MAX), @PiiType NVARCHAR(20), @SourceName NVARCHAR(50), @Token VARCHAR(40) OUTPUT, @WasNew BIT OUTPUT`. Per-row invocation: caller supplies the three input params; SP-1 returns `(@Token, @WasNew)` via OUTPUT params. `@WasNew = 1` when a new vault row was created; `@WasNew = 0` when an existing token was returned (lookup hit). The wrapper consumes both OUTPUT params and counts `@WasNew = 1` rows for the `PiiTokenizationBatch.NewTokensGenerated` metric (column verified to exist in Round 1 schema).
- Round 1: `PiiVault` table (vault DDL); `PiiTokenProvenance` table — append-only; UNIQUE on `(Token, SourceName, ObjectName, ColumnName, FilePath)` per L971-974
- Round 2: `UdmTablesList.PiiColumnList` (per `02_configuration.md` § 1.2.2 — CSV column name list); `UdmTablesList.DataClassification` (read-only context — informs RB-10 CCPA flow)

**Produces**:
- Polars DataFrame with PII column values replaced by tokens (string column → token string)
- Per-cell SP-1 INSERT (vault) + provenance INSERT (audit) — both append-only per D26
- Zero plaintext in any log line per P5 (sensitive_data_filter — § 6.1 — enforces)

**Idempotency** (per D15 + D6):
- SP-1's `UPDLOCK + HOLDLOCK + try/catch on UNIQUE` (per Round 1 v3 fix) ensures same plaintext → same token deterministically across calls
- `PiiTokenProvenance` UNIQUE on `(Token, SourceName, ObjectName, ColumnName, FilePath)` prevents duplicate provenance for same observation context
- Re-tokenizing the same DataFrame produces identical tokens (deterministic encryption); provenance INSERT may no-op on UNIQUE violation (acceptable per D26 — observation already recorded)

**Error modes** (per D68):
- `VaultUnavailable` (PipelineRetryableError) — SP-1 connection failure or transient lock timeout; retry per B-7
- `PiiColumnNotFound` (PipelineFatalError) — `UdmTablesList.PiiColumnList` names a column absent from the source DataFrame; configuration drift requires operator fix
- `TokenizationLogged` (NOT an exception — a warning) — SP-1 returned 'legal_hold_only' Status for a token; logged at WARNING; tokenization succeeds via second-token-per-plaintext outcome (per Round 1 v3 D45.6 + SP-1 narrative)

**Concurrency**:
- `cursor_for('General')` per call; vault connection only
- Multiple workers tokenizing different `(SourceName, TableName)` independent
- Same-source concurrent calls: SP-1's `UPDLOCK + HOLDLOCK` serializes per-plaintext

**Interface**:

```python
import polars as pl

def tokenize_pii_columns(
    df: pl.DataFrame,
    *,
    source_name: str,
    object_name: str,            # source table or file name
    column_list: list[str] | None = None,  # default: read from UdmTablesList.PiiColumnList
    file_path: str = '',         # populated for file sources; empty for DB sources
    batch_id: int,               # for provenance audit; from PipelineBatchSequence
) -> pl.DataFrame:
    """Replace plaintext values in `column_list` columns with tokens from PiiVault.

    Args:
        df: DataFrame with plaintext PII cells. Non-PII columns are pass-through.
        source_name: e.g. 'DNA'. Drives per-source vault isolation (D6 + P9).
        object_name: source table / file name. Captured in provenance for V7 audit.
        column_list: CSV-parsed list of PII column names. None → read from
            UdmTablesList.PiiColumnList (per 02_configuration.md § 1.2.2);
            empty list → no tokenization (return df unchanged).
        file_path: empty string for DB-sourced data; full Hive snapshot path for file.
        batch_id: from PipelineBatchSequence; surfaces in PiiTokenProvenance.BatchId.

    Returns: DataFrame with PII columns replaced by token strings. Schema unchanged
        (columns are still string type). Row count unchanged.

    Raises:
        VaultUnavailable: SP-1 connection or lock failure. Retryable per B-7.
        PiiColumnNotFound: column_list references a column absent from df.schema. FATAL.

    Side effects (per row × per PII column = N × M side-effects):
        - SP-1 INSERT-or-lookup to General.ops.PiiVault (deterministic per D6)
        - INSERT to General.ops.PiiTokenProvenance (UNIQUE may suppress duplicates)
        - NO log line includes plaintext (sensitive_data_filter per P5 enforces)

    Idempotency (per D15): re-tokenizing the same df produces an identical DataFrame
        (deterministic encryption). Provenance INSERT may no-op on UNIQUE — that is
        the intended D26 append-only behavior.

    Empty-string vs NULL handling:
        - NULL: passed through as NULL token-position (no SP-1 call)
        - '': for Oracle sources, treated as NULL per E-1; for SQL Server, tokenized
        - Caller is responsible for upstream E-1 normalization where applicable
    """
```

**Test surface**: **Tier 0 smoke (per D67 — backfilled at Round 3 close-out per B55)**: assert (a) module imports; (b) `tokenize_pii_columns(df=synthetic_df_with_pii, source_name='DNA', object_name='ACCT', column_list=['SSN'], file_path='', batch_id=999)` invokable with mocked SP-1 cursor (mock returns canned `(@Token='dna-test-token', @WasNew=1)` per L1319-1324); (c) returns DataFrame with `SSN` column values replaced by 'dna-test-token'; (d) NULL pass-through verified — input row with `SSN=None` returns `SSN=None` in output; (e) raises `PiiColumnNotFound` when `column_list=['NONEXISTENT']` and df doesn't have that column; (f) <5s, no real vault DB. Location: `tests/smoke/test_pii_tokenizer.py`. Tier 1 (deterministic round-trip same-plaintext-same-token); Tier 1 (NULL pass-through); Tier 1 (empty-string Oracle vs SQL Server); Tier 2 property (idempotent: `tokenize(tokenize(df)) == tokenize(df)` since tokens themselves are not in PiiColumnList); Tier 3 integration (full pipeline tokenization round-trip).

**Cross-doc references**: Round 1 SP-1 body (`01_database_schema.md`); Round 2 `02_configuration.md` § 1.2.2; CLAUDE.md E-1, P5, P9, D45.6; RB-10 CCPA flow.

---

### § 2.2 Module: `data_load/pii_decryptor.py`

**Purpose**: Operator-driven (NOT pipeline-path) decrypt of a single token via Round 1 SP-2; write audit row to `PiiVaultAccessLog` per P8 + D6.

**Consumes**:
- Decisions: D6 (vault decrypt path); P8 (audit on every decrypt)
- Round 1: SP-2 `PiiVault_Decrypt`; `PiiVaultAccessLog` table
- Caller authentication is OUT OF SCOPE (operator authority assumed; pipeline service account does not have decrypt permission per D6)

**Produces**:
- Plaintext value (returned in memory, never logged)
- INSERT row in `PiiVaultAccessLog` via SP-2 with canonical columns `(RequestId, AccessedAt, AccessedBy, AccessRole, Token, Justification, AccessSourceIp, AccessApplication)` per `01_database_schema.md` L1033-1048 (`AccessedBy` / `AccessRole` populated by SP-2 from `SYSTEM_USER` per L1428; `AccessSourceIp` / `AccessApplication` captured from session context inside SP-2)
- Optional: zero-out plaintext after caller's use (caller responsibility)

**Idempotency**: read-only on PiiVault; INSERT-only on audit log. Multiple decrypts of same token produce multiple audit rows (intended — every access is a separate audit event per D26).

**Error modes**:
- `TokenNotFound` (PipelineFatalError) — Token absent from PiiVault; never silently return None
- `DecryptDenied` (PipelineFatalError) — Token Status='deleted_per_request' (CCPA deletion); SP-2 returns NULL plaintext (per D30 + RB-10 retention semantics)
- `VaultUnavailable` (PipelineRetryableError) — connection failure; retryable per B-7

**Concurrency**: read-only path; high-throughput decrypt audit chains are serialized at the audit-log INSERT level (table has IDENTITY PK — no contention).

**Interface**:

```python
import uuid

def decrypt_token(
    *,
    token: str,
    justification: str,            # maps to SP-2 @Justification (L1416) — required for audit per D6
    request_id: uuid.UUID | None = None,  # maps to SP-2 @RequestId (L1415); auto-generates if None
) -> str | None:
    """Decrypt a token. Returns plaintext or None if Status='deleted_per_request'.

    Args:
        token: the token from PiiVault.Token (validated against SP-2 lookup).
            Maps to SP-2 @Token VARCHAR(40) (L1416) — note canonical type is
            VARCHAR (ASCII), not NVARCHAR (Unicode); token format is hex digits.
        justification: free-text reason — required for audit. Maps to SP-2
            @Justification NVARCHAR(MAX) (L1417). Caller MUST supply non-empty.
        request_id: optional UUID for tying multiple decrypts to a single
            operator request. None → auto-generate via uuid.uuid4(). Maps
            to SP-2 @RequestId UNIQUEIDENTIFIER (L1415).

    Returns: plaintext string for active/legal_hold_only tokens; None for
        deleted_per_request / purged_for_retention tokens (audit row STILL
        written per D26 append-only).

    Raises:
        TokenNotFound: Token absent from PiiVault. FATAL (never silent None).
        DecryptDenied: Token Status='purged_for_retention' (D30 retention).
        VaultUnavailable: SP-2 connection or lock failure. Retryable per B-7.

    Side effects (per SP-2 body L1414-1455):
        - SP-2 invocation with cursor_for('General')
        - INSERT to General.ops.PiiVaultAccessLog with canonical columns
            (RequestId, AccessedAt, AccessedBy, AccessRole, Token, Justification,
            AccessSourceIp, AccessApplication) per L1033-1048
        - AccessedBy / AccessRole populated by SP-2 from SYSTEM_USER (L1428)
        - AccessedAt populated by SP-2 from SYSUTCDATETIME() (L1428)
        - NO log line includes plaintext (P5 enforced via sensitive_data_filter)

    Caller hygiene: plaintext should be zeroed after use:
        plaintext = decrypt_token(token=tk, justification='audit request 1234')
        try:
            use(plaintext)
        finally:
            plaintext = None  # best-effort GC hint; ctypes.memset for high-security paths
    """
```

**Test surface**: **Tier 0 smoke (per D67 — backfilled at Round 3 close-out per B55)**: assert (a) module imports + `import uuid` resolves; (b) `decrypt_token(token='dna-test-token', justification='Tier 0 smoke')` invokable with mocked SP-2 cursor returning canned plaintext; (c) returns `str` for active-status mock and `None` for purged-status mock; (d) auto-generated `request_id` is a valid `uuid.UUID` when None passed; (e) raises `TokenNotFound` on mocked absent-Token fixture; (f) raises `ValueError` (Python builtin — caught by SP-2 NOT NULL constraint) if `justification=''`; (g) <5s, no real vault DB. Location: `tests/smoke/test_pii_decryptor.py`. Tier 1 (active token decrypt + audit row present); Tier 1 (deleted_per_request returns None + audit row STILL present); Tier 1 (TokenNotFound on absent token); Tier 5 manual / quarterly audit drill — confirm PiiVaultAccessLog rows match expected operator interactions.

**Cross-doc references**: Round 1 SP-2; PiiVaultAccessLog; D6, D26, D30, P5, P8; RB-4 (audit access).

---

### § 2.3 Module: `data_load/vault_client.py`

**Purpose**: Thin centralizing wrapper for vault-SP invocations — single connection-management point, single retry policy point, single error-translation point. Other modules (pii_tokenizer, pii_decryptor, future SPs from SP-10 EnforceRetention etc.) call through here.

**Consumes**:
- Round 1: PiiVault-related SPs — SP-1 `PiiVault_GetOrCreateToken` (L1319), SP-2 `PiiVault_Decrypt` (L1414), SP-10 `EnforceRetention` (L1950 — writes to PiiVault.Status per D30 retention), plus future SPs from B01 (CCPA deletion SP — extends SP-10 to write OrphanedTokenLog rows). **NOTE**: SP-11 `PipelineLog_ExtendPartition` (L1853) is NOT vault-related — it handles `PipelineLog` partition rollover and routes through a separate `partition_manager` module (not specified in Round 3 — Round 6 deployment scope).
- Round 2: `VAULT_DB_*` env keys (`02_configuration.md` § 2.1.3); `VAULT_GPG_KEY_ID` (informational — used by credentials_loader)
- Decisions: D6 (vault is a single DB connection target); D68 (retry semantics — was D67 pre-shift); D69 (cursor ownership — was D68 pre-shift)

**Produces**:
- SP return values (typed per the SP body)
- Translated exceptions: SQL Server error class → `PipelineError` subtype per D68
- One log entry per SP invocation at DEBUG (NO plaintext); at WARNING for retries; at ERROR for terminal failure

**Idempotency**: thin pass-through; idempotency lives at each SP's body (per D17). This module's wrapping is itself idempotent (retry is safe per B-7 pattern).

**Error modes**:
- Translates SQL Server pyodbc errors: connection failure / deadlock → `VaultUnavailable` (retryable); CHECK violation / FK violation → wrapping `PipelineFatalError` subtype; UNIQUE violation → bubbles up to caller for context-specific handling (some are expected per SP-1 catch-and-relookup)
- `VaultConfigError` (PipelineFatalError) — `VAULT_DB_*` env keys missing or unreachable; surfaces at pipeline startup

**Concurrency**: per-call `cursor_for('General')` — no shared cursor across module boundary (D68). Vault DB connection pool is single-process; `--workers` spawn subprocesses each with their own pool.

**Interface**:

```python
from typing import TypeVar, Callable, ParamSpec

P = ParamSpec('P')
R = TypeVar('R')

def call_vault_sp(
    sp_name: str,                  # 'PiiVault_GetOrCreateToken' etc.
    *,
    sp_args: dict,                 # parameter name → value
    max_retries: int = 3,          # per B-7
    base_delay_seconds: float = 2.0,
) -> dict:
    """Invoke a vault SP with cursor_for('General'), retry per B-7 on retryable
    SQL errors (deadlock, connection drop, lock timeout). Returns SP output as a
    dict mapping output-parameter name → value. Raises VaultUnavailable on final
    retry exhaustion; raises VaultConfigError if env keys are missing or unreachable
    at module import time. Translates SP-specific exceptions per D68 hierarchy.

    Per Pitfall #9, sp_name MUST match a Round 1 SP defined in
    `phase1/01_database_schema.md` (SP-1 / SP-2 / SP-10 / SP-11 + any future SPs).
    A typo in sp_name surfaces at SQL Server as 'cannot find SP' — FATAL with
    informative log.
    """

def configure_vault_connection_pool(
    *,
    max_connections: int = 4,      # tuned per --workers; default supports workers=4
    connection_timeout_seconds: int = 30,
) -> None:
    """Configure the vault connection pool at process start. Called once by
    main_*.py orchestrator BEFORE any vault SP invocation. Subsequent calls
    raise VaultConfigError (re-configuration not supported)."""
```

**Test surface**: **Tier 0 smoke (per D67 — backfilled at Round 3 close-out per B55)**: assert (a) module imports; (b) `call_vault_sp(sp_name='PiiVault_GetOrCreateToken', sp_args={'Plaintext': 'test', 'PiiType': 'SSN', 'SourceName': 'DNA'})` invokable with mocked cursor returning canned OUTPUT params `{'Token': 'test-token', 'WasNew': 1}`; (c) returns `dict` with the OUTPUT param values; (d) `configure_vault_connection_pool(max_connections=4)` invokable; second call raises `VaultConfigError`; (e) mocked SQL deadlock (error 1205) triggers retry per B-7 (mock asserts 3 invocations total before final failure); (f) `VaultUnavailable` raised on retry exhaustion; (g) <5s, no real DB. Location: `tests/smoke/test_vault_client.py`. Tier 1 (SP invocation with mock cursor); Tier 1 (retry on deadlock); Tier 1 (FATAL on unknown SP); Tier 3 (real vault SP invocation against Docker SQL Server fixture).

**Cross-doc references**: Round 1 all PiiVault SPs; Round 2 § 2.1.3; D6, D17, D67, D68; B-7 retry pattern; W-8 lock pattern.

---

## § 3. Credentials + parity (2 modules)

Both modules have their interfaces partially frozen in Round 2 (`phase1/02_configuration.md` § 3.3 + § 4.2). This section adds the full Round 3 module-spec detail (Idempotency / Error modes / Concurrency / Tier 0 / cross-doc refs) without re-stating the interfaces — readers consult Round 2 for signatures.

### § 3.1 Module: `data_load/credentials_loader.py`

**Purpose**: Decrypt `/etc/pipeline/credentials.json.gpg` at pipeline process start via TPM2-sealed passphrase (per D64) + `gpg2 --batch --pinentry-mode loopback`; return a `CredentialsDict` mapping `.env` key names to plaintext secrets. Cache the dict at module level for the process lifetime. **Interface signature: `02_configuration.md` § 3.3** (canonical).

**Consumes**:
- Decisions: D6 (vault credentials live here), D27 (cross-server parity — same envelope on all 3 servers), D64 (TPM2 passphrase storage), D67 (Tier 0 smoke required)
- Round 2: `02_configuration.md` § 3.1 (envelope spec), § 3.2 (D64 TPM2 rationale), § 3.3 (loader interface — canonical)
- External: `/etc/pipeline/credentials.json.gpg` (file), `gpg2` binary at `$GPG_BIN_PATH`, `tpm2_unseal` (RHEL `tpm2-tools` package)

**Produces**:
- `CredentialsDict` (NewType wrapping `dict[str, str]`) — keys match `.env` `*_PASSWORD` / `SNOWFLAKE_PRIVATE_KEY_PEM` placeholder names
- ONE `PipelineEventLog` row with `EventType='CREDENTIALS_LOAD'` per process; `Metadata` JSON includes `envelope_sha256`, `passphrase_source`, `key_id_used` (per `02_configuration.md` § 3.5)
- For Snowflake RSA key: writes ephemeral `/dev/shm/snowflake_pk_<pid>` mode `0600`; returns the path in the dict; caller responsible for `release_snowflake_key()` cleanup

**Idempotency** (per D15):
- First call performs decrypt + audit-log write
- Subsequent calls within the same process return the cached dict (no second decrypt; no second audit row)
- The cache is per-process; `--workers` subprocesses each load credentials once (per D69 — was D68)
- NO retry — TPM2 unseal failure or GPG decrypt failure is fail-fast (FATAL)

**Error modes** (per D68 — was D67):
- `CredentialsLoadError` (PipelineFatalError) — envelope missing / unreadable / GPG decrypt failed / `tpm2_unseal` returned non-zero / JSON schema_version mismatch / sentinel `'GPG_SOURCED'` reappeared in decrypted dict (loop / re-substitution bug)
- `VaultConfigError` (PipelineFatalError) — `VAULT_DB_*` env keys missing or unreachable (surfaces at startup)
- NEVER retryable — operator must intervene

**Concurrency** (per D69 — was D68):
- Single-process: cache at module level (`_credentials_cache: CredentialsDict | None = None`)
- Multi-worker (`--workers`): each subprocess loads independently; no shared state
- Thread-safe within a process via module-level guard; not thread-safe across processes (by design)

**Tier 0 smoke test** (per D67):
- `tests/smoke/test_credentials_loader.py` — runs in <5s, no real GPG / TPM2
- Mock `subprocess.run` for gpg2 + tpm2_unseal; mock pyodbc cursor for audit-log INSERT
- Asserts: (a) module imports; (b) `load_credentials(envelope_path='fixture.gpg', passphrase_source='env', passphrase_file_path=None)` invokable; (c) returns `CredentialsDict` shape; (d) raises `CredentialsLoadError` when mocked gpg2 returns non-zero; (e) sentinel detection: if mocked decrypt returns `{'X_PASSWORD': 'GPG_SOURCED'}`, raises `CredentialsLoadError`

**Test surface (Round 5)**:
- Tier 1 unit: per-error-path coverage (envelope missing, GPG fails, sentinel reappears, schema version drift)
- Tier 1 unit: caching — second call returns cached dict without re-decrypt
- Tier 3 integration: real GPG decrypt with test envelope + test TPM2 emulator
- Tier 5 manual: quarterly audit drill — operator confirms `PipelineEventLog WHERE EventType='CREDENTIALS_LOAD'` shows expected pattern

**Cross-doc references**: `02_configuration.md` § 3 (full spec); D6, D27, D64, D67; D26 audit trail; W-2 (`\x1F` sentinel — different sentinel but similar discipline); B13 (Phase 0 deliv 0.12 implementation).

---

### § 3.2 Module: `tools/verify_server_parity.py`

**Purpose**: At every pipeline startup, compare current server state against `/etc/pipeline/parity_baseline.json` (D65) and produce a `ParityReport` with per-check status. Block pipeline start (`sys.exit(1)`) on any fatal-tier drift. **Interface signature: `02_configuration.md` § 4.2** (canonical).

**Consumes**:
- Decisions: D27 (parity contract), D65 (drift severity classification — fatal / warning / informational), D67 (Tier 0 smoke required)
- Round 2: `02_configuration.md` § 4.1 (baseline JSON schema), § 4.2 (verifier interface — canonical), § 4.3 (severity classification — D65)
- External: `/etc/pipeline/parity_baseline.json` (file, mode 0644 root:root); system probes (`os.environ`, `pip freeze`, `uname -r`, `rpm -q`, `stat`, `sha256sum`, `tpm2_getcap`, `tpm2_pcrread`)

**Produces**:
- `ParityReport` dataclass per `02_configuration.md` § 4.2 — list of `ParityCheck` with `severity: Literal["fatal", "warning", "informational", "match"]`
- ONE `PARITY_VERIFY` event row in `PipelineEventLog` per pipeline-startup invocation with full report in `Metadata` JSON
- On fatal tier: alert via configured ops channel (Phase 0 deliv 0.10) — operator notification synchronous with `sys.exit(1)`
- DEBUG-level `PipelineLog` entries per individual check

**Idempotency** (per D15):
- Read-only on filesystem; INSERT-only on `PipelineEventLog`
- Re-invocation produces a NEW report row (intentional — each pipeline startup is its own audit moment)
- NO retry — parity is point-in-time; transient discrepancies should be observed, not retried-away

**Error modes** (per D68):
- `ParityFatalError` (PipelineFatalError) — any check in `fatal` tier failed; pipeline must NOT proceed
- `ParityBaselineMissing` (PipelineFatalError) — baseline JSON absent or malformed
- `ParityProbeError` (PipelineFatalError) — system probe failed (e.g. `tpm2_getcap` returned non-zero, indicating hardware fault — itself a parity violation per F21)

**Concurrency**:
- Synchronous prerequisite at process start (per `02_configuration.md` § 5.1 `JOB_PARITY_VERIFY`)
- Single-threaded; no concurrency required
- One-shot invocation per pipeline run

**Tier 0 smoke test** (per D67):
- `tests/smoke/test_server_parity_verifier.py` — runs in <5s with mocked probes
- Mock filesystem reads + `subprocess.run` for system probes; provide synthetic baseline JSON
- Asserts: (a) module imports; (b) `verify_server_parity(baseline_path='fixture.json')` invokable; (c) returns `ParityReport` with `overall ∈ {'pass', 'warn', 'fail'}`; (d) all-match fixture returns `overall='pass'`; (e) one fatal mismatch fixture returns `overall='fail'` AND raises `ParityFatalError` when `fail_on_warning=False`

**Test surface (Round 5)**:
- Tier 1 unit: per-check coverage — Python version match, library SHA match, env var presence, filesystem layout, systemd_unit SHA, TPM2 PCR policy hash, envelope SHA
- Tier 1 unit: documented exception handling — non-fatal drift logged + accepted when in `documented_exceptions` AND `expires_at > today`; rejected when expired
- Tier 2 property: severity classification — every check has exactly one severity tier; no check claims both `fatal` and `warning`
- Tier 3 integration: real server probe against Docker fixture (RHEL container with baseline + intentional drifts)

**Cross-doc references**: `02_configuration.md` § 4 (full spec); D27, D65, D67; B12 (Phase 0 deliv 0.11 implementation); F22 + F23 (parity edge cases in 04_EDGE_CASES.md from Round 2 close-out); R08 (parity drift risk — pending score reduction per Pitfall #8).

---

## § 4. Idempotency + extraction state (2 modules)

These two modules are the central enforcement points for D15 (idempotency mandatory at every layer) and D11/D13/D14 (lookback / trust gate / re-extraction tracking). Every other Round 3 module gates on `idempotency_ledger`; the extraction modules gate on `extraction_state`.

### § 4.1 Module: `utils/idempotency_ledger.py`

**Purpose**: Provide a context manager `with ledger.step(...)` that enforces per-step idempotency per D17 — UNIQUE constraint on `(BatchId, SourceName, TableName, EventType)` in `General.ops.IdempotencyLedger` prevents duplicate side-effecting operations; startup recovery sweep (I19) reconciles `IN_PROGRESS` rows from prior crashes.

**Consumes**:
- Decisions: D15 (idempotency mandatory), D17 (ledger pattern), D67 (Tier 0 smoke), I19 (startup recovery sweep — `01_database_schema.md` references this)
- Round 1: `IdempotencyLedger` table — UNIQUE on `(BatchId, SourceName, TableName, EventType)`; Status enum `('IN_PROGRESS', 'COMPLETED', 'FAILED')` per `01_database_schema.md` (verify via Grep at module impl time per Pitfall #9)
- Round 2: `02_configuration.md` § 5.3.6 (non-AM/PM jobs use IdempotencyLedger as a key concurrency mechanism)

**Produces**:
- INSERT to `IdempotencyLedger` on context-manager entry (`Status='IN_PROGRESS'`, `StartedAt=SYSUTCDATETIME()`)
- UPDATE on context-manager exit (`Status='COMPLETED'` on clean exit; `Status='FAILED'` + `ErrorMessage` on exception)
- Return value from the `with` block: `LedgerStep` with `step_id`, `was_short_circuited` (True if prior `Status='COMPLETED'` row exists), and `prior_result` (JSON metadata from the prior completion)
- Startup recovery sweep at process start: find `IN_PROGRESS` rows older than 1 hour, mark `'FAILED'` with reason `'Stale on startup recovery sweep'` (per I19 + W-8 sp_getapplock Session-owned auto-release pattern)

**Idempotency** (per D15 — this module IS the central enforcer):
- The UNIQUE constraint is the atomicity guarantee; try-INSERT with catch-on-UNIQUE-violation drives the short-circuit branch
- Re-entry with same `(BatchId, SourceName, TableName, EventType)` short-circuits via `was_short_circuited=True`; caller skips the side-effecting work and uses `prior_result`
- This pattern is the canonical idempotency idiom for the pipeline (analogous to SP-1's UPDLOCK+HOLDLOCK+catch for the vault, scoped to step-level rather than row-level)

**Error modes** (per D68):
- `LedgerStepFailed` (PipelineRetryableError on caller's caught exception; PipelineFatalError on infrastructure errors) — bubbles up the caller's exception after marking the row `FAILED`
- `LedgerStuck` (PipelineFatalError) — startup sweep found > N stale `IN_PROGRESS` rows (`N=10` configurable); indicates systemic crash pattern; operator intervention required
- `LedgerConfigError` (PipelineFatalError) — table missing / schema mismatch at module import time

**Concurrency** (per D69):
- `cursor_for('General')` per step; no shared cursor across boundary
- The UNIQUE constraint serializes same-key concurrent attempts at the database level
- Multi-worker safe; each worker's step writes its own row keyed by BatchId + SourceName + TableName + EventType

**Interface**:

```python
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

@dataclass(frozen=True)
class LedgerStep:
    step_id: int                    # General.ops.IdempotencyLedger.LedgerId
    was_short_circuited: bool       # True if prior Status='COMPLETED' row existed
    prior_result: dict | None       # CAVEAT (deep-validation 2026-05-10): IdempotencyLedger
                                    # canonical DDL has NO Metadata JSON column. For now this field
                                    # is always None. Future enhancement (Round 6 deployment dep):
                                    # either add Metadata column via ALTER OR populate from
                                    # PipelineEventLog.Metadata joined on BatchId. Tracked as B63
                                    # at Round 3 deep-validation close-out.

@contextmanager
def ledger_step(
    *,
    batch_id: int,
    source_name: str,
    table_name: str,
    event_type: str,                # 'EXTRACT', 'BCP_LOAD', 'CDC_PROMOTION', 'SCD2_PROMOTION', 'PARQUET_WRITE', etc.
    metadata: dict | None = None,   # CAVEAT (per LedgerStep.prior_result above): IdempotencyLedger
                                    # has no Metadata column. This parameter is accepted for
                                    # forward-compatibility but currently NOT written to the ledger
                                    # row. Step authors who need metadata persistence should write
                                    # to PipelineEventLog.Metadata via event_tracker (§ 6.3). B63
                                    # tracks future enhancement (either ALTER add Metadata column
                                    # OR formal join-via-PipelineEventLog pattern).
) -> Iterator[LedgerStep]:
    """Idempotent step gate per D15 + D17.

    Entry: INSERTs IdempotencyLedger row with Status='IN_PROGRESS'. On UNIQUE
    violation, queries the existing row. If Status='COMPLETED', yields LedgerStep
    with was_short_circuited=True + prior_result=None (per caveat above, until
    B63 lands). Caller skips side effects (was_short_circuited is the load-bearing
    signal). If Status='IN_PROGRESS' (concurrent worker or stale), raises
    LedgerStepFailed. If Status='FAILED', the row was a prior crash — caller
    decides retry vs escalate (see usage examples in 06_TESTING.md Round 5).

    Exit (clean): UPDATEs Status='COMPLETED', CompletedAt=SYSUTCDATETIME().
    Metadata is NOT written to IdempotencyLedger (column does not exist per
    L431-447 canonical DDL); per the param caveat above, metadata persistence
    goes through event_tracker → PipelineEventLog.Metadata until B63 lands.

    Exit (exception): UPDATEs Status='FAILED', ErrorMessage=str(exc),
    CompletedAt=SYSUTCDATETIME(); re-raises the caller's exception.

    Args: see § 4.1 for parameter semantics. event_type values are open-ended
        but canonical: 'EXTRACT', 'BCP_LOAD', 'CDC_PROMOTION', 'SCD2_PROMOTION',
        'PARQUET_WRITE', 'REPLAY', plus any '<JOB_NAME>' for non-AM/PM jobs
        per 02_configuration.md § 5.3.6.

    Raises:
        LedgerStepFailed: concurrent IN_PROGRESS row exists, or DB error.
        LedgerStuck: never raised by this function — only by startup_recovery_sweep.

    Idempotency: re-entry with same key short-circuits via prior result. This is
        the canonical pipeline idempotency pattern per D17.
    """

def startup_recovery_sweep(
    *,
    stale_threshold_minutes: int = 60,
    max_stale_count: int = 10,
) -> int:
    """At process start, scan IdempotencyLedger for IN_PROGRESS rows older than
    threshold. Mark them FAILED with ErrorMessage='Stale on startup recovery sweep'
    per I19. Returns count of rows swept. Raises LedgerStuck if count > max_stale_count
    (systemic crash signal — operator intervention required)."""
```

**Tier 0 smoke test** (per D67):
- `tests/smoke/test_idempotency_ledger.py` — <5s, mocked cursor
- Asserts: (a) module imports; (b) `ledger_step` context manager invokable with synthetic key; (c) clean exit UPDATEs to `COMPLETED`; (d) exception in `with` block UPDATEs to `FAILED` AND re-raises; (e) mocked UNIQUE violation short-circuits and yields `was_short_circuited=True`

**Test surface (Round 5)**:
- Tier 1 unit: short-circuit on COMPLETED; raise on IN_PROGRESS; raise + retry on FAILED (caller decision)
- Tier 1 unit: startup_recovery_sweep — mock stale rows, assert UPDATE to FAILED
- Tier 2 property: f(f(x)) ≡ f(x) — running the same step twice produces identical observable outcome (second call short-circuits)
- Tier 3 integration: real concurrency — two workers attempt same step, exactly one succeeds, other short-circuits
- Tier 4 crash injection: kill process mid-step → `IN_PROGRESS` row remains → next process's sweep marks `FAILED`

**Cross-doc references**: `01_database_schema.md` IdempotencyLedger DDL (table 11); D15, D17, D67, D68, D69; I19 (startup recovery); W-8 (Session-owned lock auto-release); `02_configuration.md` § 5.3.6 (non-AM/PM jobs).

---

### § 4.2 Module: `cdc/extraction_state.py`

**Purpose**: Encapsulate the trust gate (D13 — `is_date_trusted`) + lookback decisions (D11 — empirical L_99) + re-extraction tracking (D14 — `IsReExtraction` / `ExtractionAttempt` columns) for large-table windowed extraction. Reads `General.ops.PipelineExtraction` (Round 1 table); used by `orchestration/large_tables.py` per CLAUDE.md.

**Consumes**:
- Decisions: D11 (empirical L_99 lookback), D13 (trust gate for delete detection), D14 (IsReExtraction / ExtractionAttempt), D67 (Tier 0)
- Round 1: `PipelineExtraction` table — canonical columns per `01_database_schema.md` L253-271 (verified post-cycle-6 per Pitfall #9 cross-table-column-lift sub-class): `ExtractionId BIGINT IDENTITY` (PK), `BatchId`, `SourceName`, `TableName`, `DateValue`, `Status` (CHECK: `'IN_PROGRESS','SUCCESS','FAILED'`), `StartedAt`, `CompletedAt`, `EvaluatedAt` (default `SYSUTCDATETIME()`), `RowsExtracted`, `IsReExtraction` (D14), `ExtractionAttempt` (D14), `FailureReason`. NOTE: column is `StartedAt` (not `ExtractedAt` — earlier spec draft had cross-table-column-lift drift; corrected cycle 6→7). UNIQUE index `UX_PipelineExtraction_Identity (SourceName, TableName, DateValue, ExtractionAttempt)`.
- Round 2: `UdmTablesList.LookbackDays`, `FirstLoadDate`, `LastModifiedColumn` (per `02_configuration.md` § 1.1.5)
- CLAUDE.md: existing `pipeline_state.py` module is the pre-Phase-1 reference (this Round 3 module is its successor / refactor for the new pipeline)

**Produces**:
- Pure functions (no side effects) returning typed answers: `is_date_trusted(source, table, date) -> bool`, `most_recent_success(source, table) -> date | None`, `is_reextraction(source, table, date) -> bool`, `get_extraction_attempt(source, table, date) -> int`
- One write helper: `record_extraction_attempt(source, table, date, batch_id, status)` — INSERT to `PipelineExtraction` (Status enum from Round 1 schema per Pitfall #9)

**Idempotency**:
- Read functions: side-effect-free, callable any number of times with same return value
- `record_extraction_attempt`: gated by IdempotencyLedger via the caller (orchestration layer); the INSERT itself uses the `(SourceName, TableName, DateValue, ExtractionAttempt)` UNIQUE per Round 1

**Error modes** (per D68):
- `ExtractionStateUnavailable` (PipelineRetryableError) — DB connection failure; retryable per B-7
- `InvalidTrustGate` (PipelineFatalError) — `is_date_trusted` called with a date in the future or before `FirstLoadDate`; configuration error

**Concurrency** (per D69):
- `cursor_for('General')` per call
- Read functions are stateless; multi-worker safe
- `record_extraction_attempt` UNIQUE constraint serializes same-key concurrent attempts

**Interface**:

```python
from datetime import date
from dataclasses import dataclass

@dataclass(frozen=True)
class ExtractionState:
    source_name: str
    table_name: str
    business_date: date
    status: str                # 'SUCCESS', 'FAILED', 'IN_PROGRESS' per Round 1 enum
    extraction_attempt: int    # 1-indexed
    is_reextraction: bool
    started_at: datetime | None       # maps to canonical PipelineExtraction.StartedAt (L260)
    batch_id: int | None

def is_date_trusted(*, source_name: str, table_name: str, business_date: date) -> bool:
    """D13 trust gate — returns True only if PipelineExtraction shows
    Status='SUCCESS' for this (source, table, date). False otherwise.
    Used by CDC engine: untrusted dates do NOT trigger delete detection
    (per D13 — delete inference requires a successful prior extraction
    of the same date as comparison baseline).
    Raises InvalidTrustGate if business_date is in the future."""

def most_recent_success(*, source_name: str, table_name: str) -> date | None:
    """Returns the most-recent business_date with Status='SUCCESS' for the
    (source, table). None if no successful extraction ever recorded.
    Used by orchestration to determine starting boundary for lookback window."""

def is_reextraction(*, source_name: str, table_name: str, business_date: date) -> bool:
    """Returns True if PipelineExtraction shows ≥ 1 prior attempt for this
    (source, table, date). False on first attempt. Drives D14
    IsReExtraction flag on the new extraction's row."""

def get_extraction_attempt(*, source_name: str, table_name: str, business_date: date) -> int:
    """Returns next ExtractionAttempt number (1 + max prior attempt). Used at
    extraction start to assign a unique attempt sequence per D14."""

def record_extraction_attempt(
    *,
    source_name: str,
    table_name: str,
    business_date: date,
    batch_id: int,
    status: str,                  # 'IN_PROGRESS' / 'SUCCESS' / 'FAILED'
    rows_extracted: int | None = None,
    failure_reason: str | None = None,
) -> int:
    """INSERT new PipelineExtraction row OR UPDATE existing row by
    (SourceName, TableName, DateValue, ExtractionAttempt). Returns the
    PipelineExtraction.ExtractionId of the row touched.
    Idempotent: re-call with same (source, table, date, attempt) UPDATES rather
    than INSERTs duplicate row. Caller's outer IdempotencyLedger step gates
    the higher-level extraction operation."""
```

**Tier 0 smoke test** (per D67):
- `tests/smoke/test_extraction_state.py` — <5s, mocked cursor returning canned rows
- Asserts: (a) module imports; (b) all 5 functions invocable; (c) `is_date_trusted` returns bool; (d) `most_recent_success` returns `date | None`; (e) `record_extraction_attempt` returns int (the ExtractionId); (f) future-date input to `is_date_trusted` raises `InvalidTrustGate`

**Test surface (Round 5)**:
- Tier 1 unit: each function per status — SUCCESS / FAILED / IN_PROGRESS / no row
- Tier 1 unit: re-extraction sequencing — attempt 1 then 2 then 3
- Tier 2 property: monotonicity — `get_extraction_attempt` is strictly increasing within same key
- Tier 3 integration: large-table date-chunked extraction state machine end-to-end

**Cross-doc references**: Round 1 PipelineExtraction DDL; D11, D13, D14, D67; CLAUDE.md `pipeline_state.py` (predecessor reference); `02_configuration.md` § 1.1.5 (`LastModifiedColumn` — separate from `SourceAggregateColumnName` — Tier-2 sweep is in cdc/reconciliation/modified_sweep.py, NOT this module).

---

## § 5. Scheduling + lateness + gaps (3 modules)

These modules together drive the large-table windowed extraction cadence: when to extract (range_scheduler per D12), how far back to extract (lateness_profiler per D11), and when to alert on missing dates (gap_detector per D22).

### § 5.1 Module: `orchestration/range_scheduler.py`

**Purpose**: Plan the date range a pipeline run will extract for each large table — reads `General.ops.ExtractionRangePolicy` (D12), composes with `UdmTablesList.FirstLoadDate` + `LookbackDays` + `extraction_state.most_recent_success` to produce an ordered list of `business_date` values to process.

**Consumes**:
- Decisions: D11 (empirical L_99), D12 (`ExtractionRangePolicy` table), D14 (re-extraction tracking), D67 (Tier 0)
- Round 1: `ExtractionRangePolicy` table (verify schema via Grep at impl per Pitfall #9)
- Round 2: `UdmTablesList.FirstLoadDate`, `LookbackDays`, `LastModifiedColumn` (per `02_configuration.md` § 1.1)
- Other modules: `cdc/extraction_state.py` § 4.2 (`most_recent_success`)

**Produces**:
- Ordered `list[date]` of business dates to extract (per-table)
- Per-date `IsReExtraction` flag composed from `extraction_state.is_reextraction`

**Idempotency**: pure function; reads only; multi-call returns identical lists for identical inputs.

**Error modes** (per D68): `RangePolicyMissing` (PipelineFatalError) — `ExtractionRangePolicy` row absent for a table that requires explicit policy; operator must configure.

**Concurrency** (per D69): stateless; multi-worker safe.

**Interface**:

```python
from datetime import date
from dataclasses import dataclass

@dataclass(frozen=True)
class ExtractionPlan:
    source_name: str
    table_name: str
    dates: list[date]                # ordered ascending; oldest first
    re_extraction_flags: dict[date, bool]   # per-date IsReExtraction value
    policy_source: str               # 'ExtractionRangePolicy' or 'default-lookback'

def plan_extraction_range(
    *,
    source_name: str,
    table_name: str,
    as_of_date: date = None,         # default: today
) -> ExtractionPlan:
    """Compute the ordered list of business dates this pipeline run will extract
    for the (source, table). Considers:
        - UdmTablesList.FirstLoadDate (earliest boundary)
        - UdmTablesList.LookbackDays (rolling window from as_of_date)
        - ExtractionRangePolicy override (per D12) if present
        - extraction_state.most_recent_success (avoid re-extracting old SUCCESS dates
            unless ExtractionRangePolicy explicitly says to)

    Returns: ExtractionPlan with ordered dates + per-date is_reextraction flags.
        Empty `dates` list is valid (everything already extracted; nothing to do).

    Raises: RangePolicyMissing if table needs explicit policy but row absent.
    """
```

**Tier 0** (per D67): `tests/smoke/test_range_scheduler.py` — mocked UdmTablesList row + mocked extraction_state.most_recent_success; assert `ExtractionPlan` shape + ordered dates + plausible re_extraction_flags map.

**Cross-doc**: D11, D12, D14, D67; Round 1 ExtractionRangePolicy; Round 2 § 1.1 (LookbackDays/FirstLoadDate); § 4.2 above.

---

### § 5.2 Module: `cdc/lateness_profiler.py`

**Purpose**: Measure empirical L_99 lateness per D11 — for each (source, table), compute the 99th percentile of (business_date → first_observed_in_pipeline) lag observed historically. Output drives `UdmTablesList.LookbackDays` configuration (operator-set after profiler runs).

**Consumes**:
- Decisions: D11 (empirical L_99 lookback), D67 (Tier 0)
- Round 1: `PipelineExtraction` (Status='SUCCESS' rows historical), `PipelineEventLog` (extraction-start timestamps)
- Other modules: read-only consumer of historical state

**Produces**:
- `LatenessReport` per (source, table) with p50, p90, p95, p99 lag percentiles in days
- Optional: writes a row to `General.ops.LatenessProfile` for trend tracking (canonical Round 1 table name per `01_database_schema.md` — earlier draft invented `LatenessProfileLog`; corrected 2026-05-10 deep-validation per Pitfall #9 cross-table column-name-lift sub-class)

**Idempotency**: read-only on historical data; report is reproducible from same input window.

**Error modes** (per D68): `InsufficientHistory` (PipelineFatalError when invoked with <30 days of data — percentiles unstable below that window). Operator can override with `min_days` parameter.

**Concurrency** (per D69): stateless; multi-call safe.

**Interface**:

```python
from datetime import date
from dataclasses import dataclass

@dataclass(frozen=True)
class LatenessReport:
    source_name: str
    table_name: str
    window_start: date
    window_end: date
    sample_count: int
    p50_days: float
    p90_days: float
    p95_days: float
    p99_days: float           # the headline number — informs LookbackDays
    max_observed_days: int

def profile_lateness(
    *,
    source_name: str,
    table_name: str,
    window_days: int = 90,            # default 90-day historical window
    min_sample_days: int = 30,        # raise InsufficientHistory below this
) -> LatenessReport:
    """Compute empirical L_99 lateness percentiles for the (source, table) over
    the trailing `window_days`. Returns LatenessReport with p50/p90/p95/p99/max.
    Operator should set UdmTablesList.LookbackDays = ceil(p99) + safety margin.

    Raises: InsufficientHistory if PipelineExtraction has fewer than
        `min_sample_days` SUCCESS rows in the window.
    """
```

**Tier 0**: `tests/smoke/test_lateness_profiler.py` — mocked cursor returning canned percentile-shaped data; assert report shape + monotonic ordering (p50 ≤ p90 ≤ p95 ≤ p99 ≤ max).

**Cross-doc**: D11, D67; Round 1 PipelineExtraction; Round 2 § 1.1.1 col 9 (LookbackDays — consumes this report's p99).

---

### § 5.3 Module: `tools/gap_detector.py`

**Purpose**: Hourly per D22 — detect missing business_date rows in `PipelineExtraction` for each (source, large-table). Alert operator on gap. Drives `JOB_GAP_DETECT` per `02_configuration.md` § 5.1.

**Consumes**:
- Decisions: D22 (hourly gap detector), D67 (Tier 0)
- Round 1: `PipelineExtraction`
- Round 2: `UdmTablesList.FirstLoadDate`, `LookbackDays`, `LastModifiedColumn` (decides "is this date expected to be extracted by now?")

**Produces**:
- `GapReport` listing per-(source, table) the missing dates + recommended action
- `PipelineEventLog` row with `EventType='GAP_DETECT'` per hourly run + Metadata JSON
- Operator alert (Phase 0 deliv 0.10 channel) if any gap detected

**Idempotency**: read-only; report is reproducible; multiple hourly runs produce identical reports for unchanged historical data.

**Error modes** (per D68): `GapDetectorTimeout` (PipelineRetryableError) — query > 60s; retry per B-7.

**Concurrency** (per D69): single hourly run per server; ephemeral (no gate row per § 5.1 of Round 2 § 5.1).

**Interface**:

```python
from datetime import date
from dataclasses import dataclass

@dataclass(frozen=True)
class GapReport:
    source_name: str
    table_name: str
    expected_range: tuple[date, date]
    missing_dates: list[date]
    recommended_action: str    # 'backfill' / 'investigate-source' / 'within-lookback-no-action'

def detect_extraction_gaps(
    *,
    source_filter: str | None = None,     # None = all sources
    as_of_date: date = None,              # default: today
) -> list[GapReport]:
    """For each large table (UdmTablesList.SourceAggregateColumnName IS NOT NULL),
    list missing business_date rows in PipelineExtraction within the expected
    range (FirstLoadDate to as_of_date - LookbackDays). Returns one GapReport per
    affected table. Writes GAP_DETECT event row regardless of result (audit trail).
    Operator alert fires if any GapReport.missing_dates is non-empty."""
```

**Tier 0**: `tests/smoke/test_gap_detector.py` — mocked cursor returning a sparse PipelineExtraction set; assert `GapReport` shape and correct missing_dates identification.

**Cross-doc**: D22, D67; Round 1 PipelineExtraction; Round 2 § 5.1 (JOB_GAP_DETECT schedule); G-series edge cases in 04_EDGE_CASES.md.

---

## § 6. Observability (3 modules)

These three together produce the audit-grade observability layer (per D6 Audit-grade pillar). `sensitive_data_filter` enforces P5 (no plaintext PII in logs); `log_handler` v2 routes structured logs to `PipelineLog`; `event_tracker` v2 routes structured events to `PipelineEventLog`. CLAUDE.md OBS-1 through OBS-7 are the existing observability constraints — Round 3 v2 modules preserve them.

### § 6.1 Module: `observability/sensitive_data_filter.py`

**Purpose**: A `logging.Filter` subclass that redacts plaintext from log messages BEFORE they hit any sink — per P5 (no plaintext PII anywhere in logs). Wraps `log_handler` + `event_tracker` to enforce universally.

**Consumes**:
- Decisions: P5 (CLAUDE.md), D6 (PII tokenization), D67 (Tier 0)
- Round 2: `02_configuration.md` § 2.3 sensitive-key handling + § 3.5 audit trail (already documents this module's role)
- External: `logging.Filter` Python stdlib API

**Produces**:
- Filtered log records with PII/credentials redacted to `<REDACTED:reason>`
- ZERO log lines containing plaintext (verified at Tier 1 / Tier 3)

**Idempotency**: stateless filter; same input record + same patterns → same redacted output.

**Error modes** (per D68): `FilterConfigError` (PipelineFatalError) — pattern compilation failed at module import. NEVER raises during filtering (would lose log lines).

**Concurrency** (per D69): thread-safe (filter applied per-record; no shared mutable state).

**Interface**:

```python
import logging
import re
from typing import Pattern

SENSITIVE_PATTERNS: dict[str, Pattern[str]] = {
    'password': re.compile(r'(?i)([\w_]*_password)\s*[=:]\s*\S+'),
    'rsa_private_key': re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----', re.DOTALL),
    'gpg_passphrase': re.compile(r'(?i)passphrase\s*[=:]\s*\S+'),
    # Per-source PII patterns are added at runtime by tokenizer (see register_pii_pattern())
}

class SensitiveDataFilter(logging.Filter):
    """A logging.Filter that redacts plaintext from log records per P5.

    Redaction pattern: replace each match with f'<REDACTED:{pattern_name}>'.
    Patterns are checked against record.msg AND each record.args item.

    Performance: O(P × M) per record where P = pattern count, M = message length.
    Patterns compiled once at module import; runtime cost is ~50µs per record.

    Concurrency: thread-safe — patterns are read-only after import; no shared state.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Apply all patterns to record.msg + record.args. Mutates record in
        place; ALWAYS returns True (never drops a log line — redaction, not
        suppression). Failures in regex apply are caught and the record is
        passed through with a synthetic '<filter_failed>' marker; never
        loses a log line."""

def register_pii_pattern(name: str, pattern: str) -> None:
    """Add a per-source PII pattern at runtime (e.g. SSN format for DNA).
    Called by pii_tokenizer at process start after reading PiiColumnList.
    Raises FilterConfigError on invalid regex."""
```

**Tier 0** (per D67): `tests/smoke/test_sensitive_data_filter.py` — assert (a) module imports; (b) filter applied to a record with `password=foo` redacts to `<REDACTED:password>`; (c) filter applied to a clean record passes through unchanged; (d) `register_pii_pattern` adds a runtime pattern.

**Test surface (Round 5)**:
- Tier 1 unit: each pattern (password / RSA / passphrase / per-source PII)
- Tier 1 unit: pattern doesn't match clean text (no false positives that mask real log content)
- Tier 1 unit: multi-pattern message — all patterns redacted correctly
- Tier 2 property: filter is idempotent — applying twice produces the same result as once (no double-redaction artifacts)
- Tier 5 manual: quarterly review of `PipelineLog` for any leaked plaintext (audit drill)

**Cross-doc**: P5, D6, D67; Round 2 § 2.3 + § 3.5; § 6.2 + § 6.3 below (filter is installed on both handlers).

---

### § 6.2 Module: `observability/log_handler.py` (v2 — replaces existing)

**Purpose**: `SqlServerLogHandler` — a `logging.Handler` subclass that writes structured rows to `General.ops.PipelineLog` with `BatchId` + `TableName` + `SourceName` context. Preserves OBS-4 (buffer size 10 with WARNING+ immediate flush) and OBS-5 (explicit commit per write). Replaces the pre-Phase-1 handler.

**Consumes**:
- Decisions: D31 (Power BI for log analytics), D67 (Tier 0)
- Round 1: `PipelineLog` table
- CLAUDE.md: OBS-4 (buffer + immediate flush WARNING+), OBS-5 (explicit commit), OBS-7 (JSON-merge metadata pattern)
- Other modules: composes `SensitiveDataFilter` from § 6.1 (always installed)

**Produces**:
- `PipelineLog` row per log record at appropriate severity (DEBUG / INFO / WARNING / ERROR / CRITICAL)
- Buffered batching at INFO and below; WARNING+ flushes immediately per OBS-4

**Idempotency**: append-only writes; multiple invocations produce additional rows (log entries are temporal).

**Error modes** (per D68): `LogHandlerWriteFailed` (logged to stderr, never raised — handler failures must not crash pipeline). Defensive try/except inside `emit()`.

**Concurrency**: thread-local context (BatchId / TableName / SourceName held in `contextvars`); thread-safe writes via cursor per-emit (no shared cursor).

**Interface**:

```python
import logging
from contextvars import ContextVar

_batch_id_ctx: ContextVar[int | None] = ContextVar('batch_id', default=None)
_table_name_ctx: ContextVar[str | None] = ContextVar('table_name', default=None)
_source_name_ctx: ContextVar[str | None] = ContextVar('source_name', default=None)

class SqlServerLogHandler(logging.Handler):
    """Writes structured logs to General.ops.PipelineLog.

    Context: reads _batch_id_ctx / _table_name_ctx / _source_name_ctx from
    contextvars. Callers set these via set_log_context() at the start of
    each pipeline-step boundary.

    Buffering: INFO and below buffered in a 10-record list (per OBS-4 reduced
    from 50 to narrow crash-loss window); WARNING+ flushed immediately.
    Buffer auto-flushes on close() or process exit.

    Explicit commit per OBS-5: every flush calls conn.commit() — do NOT
    rely on autocommit, future config changes shouldn't silently break this.

    Filter: SensitiveDataFilter from § 6.1 is installed by default. Override
    only with explicit justification (PII redaction is P5 invariant)."""

def set_log_context(*, batch_id: int, table_name: str | None = None, source_name: str | None = None) -> None:
    """Set the per-thread / per-async-task log context. Subsequent log records
    in this context include the BatchId/TableName/SourceName in their PipelineLog rows."""

def clear_log_context() -> None:
    """Clear the log context — call at pipeline-step exit."""
```

**Tier 0** (per D67): `tests/smoke/test_log_handler.py` — mocked cursor; assert (a) module imports; (b) handler accepts a `LogRecord` and writes via mocked cursor; (c) WARNING record flushes immediately (mocked commit called); (d) set/clear_log_context affects subsequent emits.

**Test surface (Round 5)**: Tier 1 unit (each severity level); Tier 1 unit (buffer flush at 10); Tier 1 unit (WARNING immediate flush); Tier 1 unit (SensitiveDataFilter applied — plaintext password in log message → redacted in PipelineLog row); Tier 3 integration (real PipelineLog table).

**Cross-doc**: D31, D67; Round 1 PipelineLog; OBS-4, OBS-5, OBS-7, P5; § 6.1 above.

---

### § 6.3 Module: `observability/event_tracker.py` (v2 — replaces existing)

**Purpose**: `PipelineEventTracker` — a context manager wrapping each pipeline step that writes one `PipelineEventLog` row per step. Preserves OBS-5 (explicit commit), OBS-7 (JSON-merge metadata pattern), and OBS-3 (SKIPPED status for lock-blocked tables).

**Consumes**:
- Decisions: D31 (Power BI dashboards consume PipelineEventLog), D33 (cancellation flag — tracker reads CancellationRequested at heartbeat), D62 CCL (tracker is the audit trail for CCL compliance traces), D67 (Tier 0)
- Round 1: `PipelineEventLog` table + `CK_PipelineEventLog_Status` enum (`('IN_PROGRESS','SUCCESS','FAILED','SKIPPED')` per Round 1 L143-144)
- CLAUDE.md: OBS-3 (SKIPPED for lock-blocked), OBS-5, OBS-7
- Other modules: composes `SensitiveDataFilter` for Metadata JSON sanitization

**Produces**:
- One `PipelineEventLog` row per `track()` invocation
- Status transitions: IN_PROGRESS (entry) → SUCCESS/FAILED (exit) per Round 1 enum (Pitfall #9 — verified)
- Metadata JSON merge per OBS-7 (existing JSON parsed, new keys merged, written back)
- Optional: heartbeat updates to `PipelineExecutionGate.LastHeartbeatAt` for AM/PM cycles (per Round 2 § 5.3.2) — invoked from inside the `with` block

**Idempotency**: append-only; each `track()` call writes its own row.

**Error modes** (per D68): same defensive pattern as `SqlServerLogHandler` — tracker failures logged to stderr but never raised (observability must not crash pipeline).

**Concurrency**: per-call cursor; thread-safe via contextvars.

**Interface**:

```python
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator

@dataclass
class EventState:
    event_log_id: int | None = None
    rows_processed: int | None = None
    rows_inserted: int | None = None
    rows_updated: int | None = None
    rows_deleted: int | None = None
    rows_unchanged: int | None = None
    rows_before: int | None = None
    rows_after: int | None = None
    metadata: dict = field(default_factory=dict)

@contextmanager
def track(
    *,
    event_type: str,                # 'EXTRACT' / 'CDC_PROMOTION' / 'SCD2_PROMOTION' / 'TABLE_TOTAL' / 'CREDENTIALS_LOAD' / 'PARITY_VERIFY' / 'CYCLE_CANCELLED' / etc.
    table_name: str | None,
    source_name: str | None,
    batch_id: int,
    event_detail: str | None = None,
) -> Iterator[EventState]:
    """Wrap a pipeline step. On entry, INSERTs PipelineEventLog row with
    Status='IN_PROGRESS'. Yields EventState; caller mutates fields as the step
    progresses. On clean exit, UPDATEs Status='SUCCESS', CompletedAt, rows_*,
    metadata (per OBS-7 JSON-merge). On exception, UPDATEs Status='FAILED' +
    ErrorMessage, then re-raises. Skipped via early `return` with Status='SKIPPED'
    (per OBS-3 — when table_lock acquisition fails).

    Args: see § 6.3 for parameter semantics. event_type values are open-ended
        but should reuse canonical names (see EventType column in CLAUDE.md
        Architecture Decisions section).

    Per Pitfall #9: Status values MUST be in CK_PipelineEventLog_Status enum
    ('IN_PROGRESS','SUCCESS','FAILED','SKIPPED' — Round 1 L143-144). NEVER
    'STARTING'/'RUNNING'/'SUCCEEDED'/'TIMEOUT'/'CANCELLED' for PipelineEventLog
    — those values belong to PipelineExecutionGate's separate enum
    (`CK_PipelineExecutionGate_Status` per `01_database_schema.md` L328-330).

    Side effects: 2 cursor writes (INSERT on entry, UPDATE on exit), each with
    explicit conn.commit() per OBS-5."""

def skip(*, event_type: str, table_name: str, source_name: str, batch_id: int, reason: str) -> None:
    """Standalone helper for SKIPPED events (OBS-3) — when a step is skipped
    BEFORE the with-block can be entered (e.g. lock not acquired). Single
    INSERT with Status='SKIPPED'."""
```

**Tier 0** (per D67): `tests/smoke/test_event_tracker.py` — mocked cursor; assert (a) `track()` context manager invokable; (b) entry writes Status='IN_PROGRESS'; (c) clean exit writes Status='SUCCESS'; (d) exception in `with` block writes Status='FAILED' AND re-raises; (e) Status values match the Round 1 enum per Pitfall #9.

**Test surface (Round 5)**: Tier 1 unit (each event type + status transition); Tier 1 unit (OBS-7 metadata merge); Tier 1 unit (skip helper); Tier 2 property (Status always in enum — Hypothesis fuzz `event_type` and any field, assert Status never drifts); Tier 3 integration.

**Cross-doc**: D31, D33, D62, D67; Round 1 PipelineEventLog DDL + Status enum L143-144 (Pitfall #9 verified); OBS-3, OBS-5, OBS-7; § 5.3 of Round 2 (gate-table heartbeat); § 6.1 above (SensitiveDataFilter on Metadata).

---

## § 7. Snowflake (1 module)

### § 7.1 Module: `data_load/snowflake_uploader.py`

**Purpose**: Mirror a verified Parquet snapshot to Snowflake via `COPY INTO` against managed Iceberg tables (D5). Reads the file path + SHA from `ParquetSnapshotRegistry` (§ 1.3); flips registry Status `verified` → `replicated` on success (via `mark_replicated()` from § 1.3).

**Consumes**:
- Decisions: D3 (Snowflake for analytics + reconciliation only — cost ceiling), D5 (Snowflake-managed Iceberg), D23 (Snowflake budget alert at 80% cap), D67 (Tier 0), D71 (Snowflake auth — was D70 pre-shift)
- Round 1: `ParquetSnapshotRegistry` (read file path + SHA + status; write status via § 1.3)
- Round 2: `02_configuration.md` § 2.1.8 (Snowflake env keys); § 3 (`SNOWFLAKE_PRIVATE_KEY_PEM` decrypted from GPG envelope per D71)

**Produces**:
- `COPY INTO <SNOWFLAKE_DATABASE>.<SNOWFLAKE_SCHEMA>.<table_name>` execution against Iceberg target
- `ParquetSnapshotRegistry.Status` flip via `mark_replicated()`
- `PipelineEventLog` row with `EventType='SNOWFLAKE_COPY_INTO'`; Metadata includes warehouse, rows_copied, copy_history_id

**Idempotency** (per D15):
- Snowflake's `COPY INTO` is itself idempotent by-file (re-copying the same file → 0 rows added because COPY tracks file-load history per Snowflake docs)
- Registry status flip from `verified` → `replicated` is idempotent at the function level (per § 1.3 `mark_replicated`)
- Re-call: idempotent at both layers

**Error modes** (per D68):
- `SnowflakeAuthFailed` (PipelineFatalError) — RSA key decrypt or `CONNECT` failed; operator intervention
- `SnowflakeBudgetAlert` (PipelineRetryableError or PipelineFatalError per D23) — credit usage > 80% of monthly cap; alert + optionally block COPY
- `SnowflakeCopyTimeout` (PipelineRetryableError) — COPY exceeded timeout; retry per B-7
- `RegistryStatusInvalid` (PipelineFatalError) — bubbled from `mark_replicated()` if registry status is not `verified`

**Concurrency** (per D69):
- Single Snowflake CONNECTION per process (RSA key path is per-process per D71)
- `--workers` spawn subprocesses each with their own CONNECTION (and their own ephemeral key file)
- `COPY INTO` against same file from two processes is safe (Snowflake's file-load history dedups)

**Interface**:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class SnowflakeCopyResult:
    registry_id: int
    snowflake_table: str            # 'DB.SCHEMA.TABLE_NAME'
    rows_copied: int                # from Snowflake COPY INTO result
    copy_history_id: str            # Snowflake's file-load history ID
    duration_ms: int

def copy_parquet_to_snowflake(
    *,
    registry_id: int,
    snowflake_table: str | None = None,    # default: f'{SF_DB}.{SF_SCHEMA}.{table_name}' from config
    timeout_seconds: int = 300,
) -> SnowflakeCopyResult:
    """Issue COPY INTO from the registered Parquet file into the Snowflake Iceberg
    target table. Reads file path from ParquetSnapshotRegistry; verifies SHA before
    COPY; flips Status 'verified' → 'replicated' on success via mark_replicated().

    Args:
        registry_id: ParquetSnapshotRegistry.RegistryId of a Status='verified' row.
        snowflake_table: Override the default `DB.SCHEMA.TABLE_NAME` mapping.
        timeout_seconds: COPY INTO query timeout.

    Returns: SnowflakeCopyResult with rows_copied + copy_history_id.

    Raises:
        SnowflakeAuthFailed: RSA key decrypt or auth handshake failed.
        SnowflakeBudgetAlert: monthly credit cap > 80%.
        SnowflakeCopyTimeout: COPY exceeded `timeout_seconds`. Retryable.
        RegistryStatusInvalid: source Status was not 'verified'.

    Side effects:
        - Snowflake COPY INTO execution
        - ParquetSnapshotRegistry.Status flip via mark_replicated()
        - PipelineEventLog row with EventType='SNOWFLAKE_COPY_INTO'

    Idempotency: Snowflake's per-file load history dedups; re-call is safe.

    Auth flow (per D71): SNOWFLAKE_PRIVATE_KEY_PEM is in the credentials dict
    from credentials_loader (§ 3.1); writes to /dev/shm/snowflake_pk_<pid> mode
    0600; CONNECTION reads via file path; key file deleted by release_snowflake_key()
    after COPY completes. Never logs the path's contents (P5 + sensitive_data_filter)."""
```

**Tier 0** (per D67): `tests/smoke/test_snowflake_uploader.py` — mock Snowflake connector + mock registry read/write; assert (a) function invokable; (b) returns `SnowflakeCopyResult` shape; (c) raises `RegistryStatusInvalid` on non-verified status fixture; (d) mocked auth-fail raises `SnowflakeAuthFailed`.

**Test surface (Round 5)**: Tier 1 unit (each error path); Tier 1 unit (registry status flip happens AFTER COPY succeeds, not before); Tier 1 unit (RSA key file cleanup post-session — assert /dev/shm path is unlinked); Tier 3 integration (real Snowflake trial account from Phase 0 deliv 0.6 / B39).

**Cross-doc**: D3, D5, D23, D67, D71 (was D70); Round 1 ParquetSnapshotRegistry; Round 2 § 2.1.8 + § 3; § 1.3 above (`mark_replicated`).

---

## § 8. Cross-cutting patterns

This section formalizes three cross-cutting concerns as decisions (now D68 / D69 / D70 per the post-shift numbering) and one development discipline addition for Round 5.

### § 8.1 Error class hierarchy (D68 — was D67 pre-D67-shift)

Locked above in § "Common patterns / Error class pattern (per D68)". Summary: 2-tier base (`PipelineFatalError` vs `PipelineRetryableError`); per-module subclasses inheriting from the appropriate base. Logged at CRITICAL (FATAL) or WARNING (retryable on retry) → ERROR (retryable on terminal failure).

**Pillar(s) served** (per D61): **Operationally stable**, **Idempotent**.

**Trade-offs accepted**: 2-tier base may be insufficient for nuanced classification (e.g. "user-fixable vs operator-fixable"); revisit if Round 5 testing surfaces friction. For Round 3 lock, 2-tier is sufficient.

### § 8.2 Connection / cursor ownership (D69 — was D68 pre-shift)

Locked above in § "Common patterns / Resource ownership pattern (per D69)". Summary: `cursor_for(db_name)` context manager from existing `connections.py` is canonical; cursors NEVER cross module boundaries; `--workers` spawn subprocesses each with their own connection pool; within a process, vault DB connection pool is a separate explicit pool (`vault_client.configure_vault_connection_pool` at module import).

**Pillar(s) served** (per D61): **Operationally stable**, **Idempotent**.

**Implementation note**: every Round 3 module spec above includes "**Concurrency** (per D69)" explicitly — this is the discipline enforcement layer.

### § 8.3 Test fixture strategy (D70 — was D69 pre-shift)

**Status**: 🟡 Proposed (locks after Round 3 Gate 2 + mandatory second-pass per D56 if 🔴)
**Pillar(s) served** (per D61): **Audit-grade**, **Operationally stable**.

**Decision**:

- **Tier 0** (per D67): `tests/smoke/test_<module>.py` per module; <5s; pure / mock; runs at build + every commit. Mandatory.
- **Tier 1**: `tests/unit/test_<module>.py`; per-edge-case + per-error-path; pytest fixtures defined per-module
- **Tier 2**: `tests/property/test_<invariant>.py`; Hypothesis strategies for arbitrary inputs; idempotence proofs
- **Tier 3**: `tests/integration/`; Docker SQL Server fixture (`conftest.py`); end-to-end pipeline scenarios from Round 5 doc
- **Tier 4**: `tests/crash/`; chaos engineering / kill -9 injection at documented crash boundaries; pre-release
- **Tier 5**: manual quarterly audit drills documented in `06_TESTING.md` (Round 5)

**Fixture data**:

- `tests/fixtures/udm_test_fixtures/` — Docker SQL Server schema + seed data shared across Tier 3
- `tests/fixtures/arbitrary_dataframe.py` — Hypothesis strategy for arbitrary Polars DataFrames (Tier 2)
- `tests/fixtures/synthetic_parquet/` — pre-generated Parquet files for snapshot replay tests
- `tests/fixtures/mock_credentials_envelope.gpg.b64` — base64-encoded test envelope for credentials_loader Tier 1 (decryptable with a test key checked into the repo with explicit "DO NOT USE IN PROD" markers)

**Module-level `__test_fixtures__` constant**: every Round 3 module includes a `__test_fixtures__: list[str]` module-level constant naming the fixture sets it depends on. CI loads only the required fixtures per test run.

**Trade-offs accepted**: Docker SQL Server fixture adds ~30s startup cost per Tier 3 invocation; mitigated by `pytest --keepalive` for local dev and shared fixture container in CI.

### § 8.4 Build-time discipline (per D67)

Per D67 (locked 2026-05-10), every module produced by Round 3 → Round 6 has a companion Tier 0 smoke test that runs at build time. The discipline applies:

- AT module authoring time: produce module → IMMEDIATELY produce `tests/smoke/test_<module>.py` → IMMEDIATELY invoke it; if fail, fix before declaring module complete
- AT every commit (CI): Tier 0 stage runs before Tier 1 stage; failure blocks CI
- AT Round close-out: round verifier confirms every module produced this round has a Tier 0 smoke test AND it passes

For § 1 + § 2 modules already specified before D67 lock, Tier 0 sketches will be appended at Round 3 close-out (close-out task — tracked as a separate B-number).

**Pillar(s) served** (per D61): **Operationally stable** (build-time bugs caught at build); **Audit-grade** (Tier 0 execution creates audit trail of "this code was built AND verified runnable"); **Idempotent** (Tier 0 tests are themselves idempotent — pure / mock).

---

## § 9. Edge case mapping (Gate 3 input)

Round 3 is INTERFACE design — most pipeline-correctness edge cases are addressed at the runtime layer (where the implementations land in Round 5+ via Tier 0/1/2/3 tests gating each module). This section marks which series Round 3 addresses at the interface level, which it enables for downstream rounds, and which it surfaces as new.

### § 9.1 M / S / I / N / P / G / D / F / V series walk against Round 3 interfaces

| Series | Round 3 status | Specifics |
|---|---|---|
| **M** (math/lookback/lateness) | ✅ Addressed | § 5.2 `lateness_profiler` provides empirical L_99 measurement per D11; § 5.1 `range_scheduler` consumes per-table LookbackDays |
| **S** (SCD2 reliability) | ⚪ Referenced | Round 3 modules don't change SCD2 runtime semantics — those live in pre-Phase-1 `scd2/engine.py`. § 1.2 `parquet_replay` feeds into SCD2 (RB-8) but uses existing `run_scd2_targeted()` |
| **I** (idempotency) | ✅ Addressed (central) | § 4.1 `idempotency_ledger` IS the central D15 enforcement module. Every other Round 3 module composes through it (per § 8.4 + module-spec patterns above). I3 race-condition class covered by ledger's UNIQUE+catch idiom (analogous to SP-1's UPDLOCK+HOLDLOCK+catch — per Pitfall #9 the canonical pattern) |
| **N** (network drive / Parquet) | ✅ Addressed | § 1.1 `parquet_writer` inflight-rename per D16; § 1.3 `parquet_registry_client` provides `mark_missing` for N-series file-gone case |
| **P** (PII / encryption) | ✅ Addressed | § 2.1 `pii_tokenizer` + § 2.2 `pii_decryptor` + § 2.3 `vault_client` per D6; § 6.1 `sensitive_data_filter` per P5; provenance per D26 |
| **G** (gap detection / outage recovery) | ✅ Addressed | § 5.3 `gap_detector` per D22; § 1.2 `parquet_replay` for RB-8 Bronze rebuild path |
| **D** (2x/day cadence) | ⚪ Referenced | § 6.3 `event_tracker` v2 supports the AM/PM cycle gate per `02_configuration.md` § 5.3.2 + § 5.3.3 (heartbeat + cancel-check); orchestration layer drives the cadence (not Round 3 scope) |
| **F** (failover / cross-server parity) | ✅ Addressed | § 3.2 `server_parity_verifier` per D27 + D65; § 6.3 `event_tracker` heartbeat + cancel-check support D33 failover. F21-F23 (added at Round 2 close-out) covered by § 3.2 + parity verifier severity tiers |
| **V** (vault provenance) | ✅ Addressed | § 2.1 `pii_tokenizer` writes provenance per D26; § 2.2 `pii_decryptor` writes PiiVaultAccessLog per P8 + D26 |

### § 9.2 New edge cases surfaced by Round 3

Three candidates for `04_EDGE_CASES.md` additions at Round 3 close-out:

| Proposed | Description | Mitigation in Round 3 |
|---|---|---|
| I (next) | `idempotency_ledger.ledger_step` re-entry with `Status='IN_PROGRESS'` from a CONCURRENT worker (not stale) — should raise `LedgerStepFailed`, not short-circuit (caller would otherwise skip the work but the other worker hasn't completed it) | § 4.1 explicit handling: short-circuit ONLY on `Status='COMPLETED'`; `IN_PROGRESS` raises `LedgerStepFailed` |
| N (next) | `parquet_writer` inflight file rename succeeds but `ParquetSnapshotRegistry` INSERT fails — registry has no row but file exists; orphaned file | § 1.1 raises `RegistryInsertConflict` (retryable) or `ParquetWriteCrash` (FATAL); operator-callable function in § 1.3 `mark_missing` allows registering existing inflight files retroactively |
| P (next) | `pii_tokenizer` re-tokenizes after `pii_decryptor` returned `None` for `Status='purged_for_retention'` — tokenizer must NOT recreate the same token because the plaintext is gone (no decrypt path); MUST mint a new token + write provenance | § 2.1 `pii_tokenizer` relies on SP-1's UPDLOCK+HOLDLOCK+catch pattern — purged plaintext is gone, so the new tokenize call inserts a NEW vault row (different token from the purged one). Audit trail preserved via PiiVault.Status='purged_for_retention' on the old row + new row with Status='active' |

Close-out task (close-out B-number to be assigned): append three rows to `04_EDGE_CASES.md`; operator computes IDs via `grep "^| I[0-9]" 04_EDGE_CASES.md | tail -1` then increment.

---

## § 10. Validation gates (Round 3 producer self-check)

Per D55 + D62, this § is the producer self-check before invoking Gate 2 independent review. **Per Pitfall #9 + Round 2's three-pass cycle precedent**, this self-check pays explicit attention to EVERY Python signature's SQL column / parameter / enum reference against canonical DDL.

### § 10.1 Gate 1 self-check — Cross-reference

For each D-number cited in this doc (~30 D-numbers across § 0-9):
- D2, D3, D4, D5, D6, D11, D12, D13, D14, D15, D16, D17, D21, D22, D23, D25, D26, D27, D31, D33, D45.2, D45.3, D45.6, D55, D56, D60, D61, D62, D63, D64, D65, D66, D67, D68-D71 (proposed): all resolve per `03_DECISIONS.md`
- B-numbers cited: B01, B07, B08, B12, B13, B33, B36, B37, B38-B43, B47-B49 — all match `BACKLOG.md` state

For Round 1 SP / table / enum references (Pitfall #9 critical surface):
- SP-1 `PiiVault_GetOrCreateToken` — verified against `01_database_schema.md` SP-1 body
- SP-2 `PiiVault_Decrypt` — verified
- SP-3 / SP-4 NOT cited directly in Round 3 modules (those references live in Round 2 § 5; Round 3 modules reference Round 2's § 5 narrative, not the SPs themselves)
- `PipelineEventLog.Status` enum: `('IN_PROGRESS','SUCCESS','FAILED','SKIPPED')` cited per § 6.3 — verified against L143-144 (Pitfall #9 was the lesson from Round 2)
- `PipelineExecutionGate.Status` enum: cited per § 6.3 implicit (event_tracker doesn't write to gate table)
- `IdempotencyLedger.Status` enum: `('IN_PROGRESS', 'COMPLETED', 'FAILED')` cited per § 4.1 — verified per CLAUDE.md "Status enums" reference table; Pitfall #9 verification via Grep at module impl recommended
- `PipelineExtraction` columns: cited per § 4.2 — **verified against canonical `01_database_schema.md` L253-271 (cycle 6→7 fix; cycle 7 column-walk specialist Reviewer M confirmed all 13 canonical columns enumerated correctly in § 4.2 L948); `started_at` dataclass field at L983 explicitly maps to canonical `StartedAt` L260)**
- `ParquetSnapshotRegistry.Status` enum: 7-state per § 1.3 — verified against CLAUDE.md narrative

For Round 2 references:
- All § 1.x / § 2.x / § 3 / § 4 / § 5 / § 6 / § 7 references in `02_configuration.md` resolve

**Status**: ✅ producer self-check completed. Mandatory Gate 2 independent review per D56.

### § 10.2 Gate 5 self-check — Risk delta + Backlog surfacing (per D61)

**Per D62 Pitfall #8** (added at Round 2 close-out): every risk-delta line in this § MUST be verified against `RISKS.md` BEFORE Round 3 locks.

**Risks introduced / addressed**:

```
RISKS (per D61):
- 🆕 NEW: R19 (proposed) — Tier 0 smoke tests may drift from module interfaces if not
       kept in sync (i.e., interface evolves but smoke test still checks the old shape).
       Likelihood Medium × Impact Low = 2 ⚪. Mitigation: Round 5 close-out includes
       a Tier 0 vs interface signature reconciliation check; B-number to author the
       reconciliation script.
       Status: NOT YET ADDED to RISKS.md — close-out task per Pitfall #8.

- ⬇️ DE-ESCALATED (pending substantiation): R03 (single-engineer Python expertise) —
       formal Round 3 interface specs + Tier 0 smoke tests reduce tribal-knowledge dep.
       Hedge per Pitfall #8: do NOT reduce score until first ~5 Round 3 modules
       actually ship with Tier 0 + ~1 successful second-engineer onboarding using
       this doc as primary reference.

- ⬇️ DE-ESCALATED (pending): R11 (validation discipline drift) — D67 Tier 0 makes
       code-level validation mechanical, paralleling D55's doc-level mechanism. Hedge
       per Pitfall #8: do NOT reduce score until first round actually exercises Tier 0.
```

**Backlog proposals** (per D61 — current max in BACKLOG.md after Round 2 close-out is **B50**; NEXT_AVAILABLE = **B51**, but B51 + B52 were already used for Round 2 second-pass fixes; NEXT_AVAILABLE = **B53**):

```
BACKLOG (per D61):
- 🟡 B53: Add R19 to RISKS.md (Tier 0 drift) at Round 3 close-out (Pitfall #8 discipline)
       COD 3, JS 1, WSJF=3.0
- 🟡 B54: Append three new edge cases (I-next / N-next / P-next per § 9.2) to
       04_EDGE_CASES.md at Round 3 close-out; COD 2, JS 1, WSJF=2.0
- 🟡 B55: Backfill Tier 0 smoke tests for § 1 + § 2 modules already specified before
       D67 lock (6 modules — parquet_writer, parquet_replay, parquet_registry_client,
       pii_tokenizer, pii_decryptor, vault_client); COD 4, JS 2, WSJF=2.0
- 🟡 B56: Update D-number cross-references in § 1 + § 2 module specs from pre-shift
       (D67 / D68) to post-shift (D68 / D69) — close-out task; COD 1, JS 1, WSJF=1.0
- 🟡 B57: Extend `udm-test-author` skill template to author Tier 0 sketches alongside
       Tier 1 (per D67 affects clause); COD 2, JS 1, WSJF=2.0
- 🟡 B58: Author Tier 0 vs module-interface reconciliation script (drift detection per
       R19 mitigation); COD 3, JS 2, WSJF=1.5
```

### § 10.3 Gate 2 — Independent review (NEXT STEP at Round 3 close-out)

Invocation pattern per `udm-design-reviewer` agent + D62 CCL:

> Per `MULTI_AGENT_GUIDE.md` § Canonical Context Load (D62), perform CCL before reviewing. First content-substantive `Read` MUST be on a Stage 1 doc. Review `phase1/03_core_modules.md` for: (1) Gate 1 cross-reference — every D-number cited resolves; every Round 1 SP / table / enum reference matches canonical DDL per Pitfall #9 (THIS IS THE HIGH-RISK SURFACE — Round 2 hit this 3+ times); (2) Gate 2 design soundness — D67 Tier 0 spec coherent; D68-D71 sub-decisions sound; (3) Gate 3 edge case coverage in § 9; (4) Gate 4 verification — each ✅ in § 9.1 has tangible mechanism; (5) Gate 5 idempotency / regression — D55-D67 invariants preserved; risk-delta claims in § 10.2 match `RISKS.md` per Pitfall #8.

Expected output: 5-gate validation report; **mandatory second-pass per D56 if 🔴; third-pass if second-pass introduces NEW 🔴** (Round 2 cycle precedent — iterative convergence is expected; no escalation needed unless fourth-pass also dirty).

### § 10.4 Gate 3 + Gate 4 — Edge case enumeration + validation

Walked in § 9. § 9.1 series-by-series; § 9.2 surfaces 3 new candidates (B54 to append at close-out). Each ✅ in § 9.1 has tangible Round 3 mechanism (module spec interface + Tier 0 smoke test at build time per D67).

### § 10.5 Round 3 acceptance criteria checklist (will run at close-out)

- [ ] § 0 – § 10 all present and self-consistent
- [ ] D68 – D71 captured in `03_DECISIONS.md` (post-shift numbering — D67 already locked for Tier 0)
- [ ] `udm-design-reviewer` independent first-pass returned no 🔴 (mandatory second-pass + third-pass per D56 if 🔴)
- [ ] `_validation_log.md` entry appended documenting all validation passes
- [ ] Cross-doc updates landed: 04_EDGE_CASES.md (B54 — 3 new cases); CLAUDE.md (one-line pointer in Architecture Decisions to `03_core_modules.md`); 06_TESTING.md update placeholder for 6-tier pyramid per D67
- [ ] BACKLOG.md updated with B53 – B74 (original close-out scope was B53-B58; D72 deep-validation cycles 4-9 expanded through B74; updated 2026-05-10 per Reviewer W finding)
- [ ] RISKS.md updated with R19 (per B53)
- [ ] HANDOFF.md §3 + §12 + §14 updated via `udm-round-closeout`
- [ ] CURRENT_STATE.md "Recently completed" + "Recent rounds" + "Last updated" updated
- [ ] NORTH_STAR.md Phase 1 row already shows Audit-grade + Operationally stable + Idempotent pillars (no change expected — Round 3 advances them as expected)
- [ ] Doc status flip: `phase1/03_core_modules.md` "🟡 RE-OPENED (D72 convergence cycle)" → "🟢 Locked (D72 architectural-review decision OR convergence)" — updated 2026-05-10 cycle 9→10 per Reviewer W finding (original "🟡 Drafting" label predated the deep-validation re-open)
- [ ] D-number renumbering follow-up (B56): § 1 + § 2 module specs updated to use D68 (errors) / D69 (cursor) instead of pre-shift D67 / D68
- [ ] § 1 + § 2 Tier 0 backfill (B55) — six smoke test sketches appended to module specs

---

## End of Round 3 — Core Modules

**Status when this checklist completes**: 🟢 Locked, ready for Round 4 (Tools) to consume the operator-facing CLI surface that wraps these modules, Round 5 (Tests) to write Tier 1/2/3/4 tests against the interface contracts, Round 6 (Deployment) to implement bodies + Tier 0 smoke tests + CI pipeline.

**Cycle expectation**: based on Round 2's precedent (first-pass 3 🔴, second-pass 2 NEW 🔴, third-pass clean), Round 3 may hit 1-2 🔴 in first-pass cross-reference + design review. The Pitfall #9 + #8 disciplines applied throughout this doc (citing every Round 1 / Round 2 / D-number reference; hedging risk-delta claims) reduce the surface but cannot eliminate. Plan for at least one second-pass; possibly third-pass.
