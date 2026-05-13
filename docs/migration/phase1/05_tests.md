# Phase 1, Round 5 — Tests

**Status**: 🟢 **Locked via D83 architectural-review acceptance** (paralleling Round 3 D73 + Round 4 D78 precedent) — see `_validation_log.md` 2026-05-10 Round 5 D72 cycles 1-5 entry. Five-cycle validation campaign: cycle 1 Pattern E (5 agents — 17 🔴 across 3 of 4 blocking + 5 🟡 advisory framing) → cycle 2 single-agent (7 🔴 fix-fresh-instance) → cycle 3 single-agent (1 🔴 count-math drift) → cycle 4 sleeper-bug stress test (1 🔴 + 2 🟡 — load-bearing B-number cite) → cycle 5 final-convergence verification (✅ CLEAN; 0 fresh-instance drift; Pitfall #9 fix-fresh-instance pattern broken for the first time in 8 rounds). 26 cumulative 🔴 caught + fixed; trajectory 17→7→1→1→0 demonstrates convergence; sleeper-bug stress test cleared deepest available validation depth at cycle 4. **Pattern E from cycle 1 proved structurally superior** to Round 4's sequential single-agent cycles 1-3 (caught the same bug-class surface in 1 cycle vs 3). D83 acceptance with explicit 🟡 BACKLOG carryover (B108-B119 + cycle 5+ advisory items) for Round 6 close-out triage. Constituent decisions D79-D82 (test fixture schema / Tier 0-vs-1 boundary / Hypothesis budget / coverage thresholds) lock alongside.

This document is the per-module + per-tool test plan specification for the UDM pipeline. It consolidates Tier 0 sketches from Rounds 3 + 4, authors Tier 1-4 test plans across all 28 modules + tools, defines Tier 5 quarterly audit procedures, and executes the systematic B47-B107 backlog triage per D73 (Round 3) + D78 (Round 4) carryover mandates. **Test implementation is deferred to Round 6 deployment** — this round produces test specifications only.

Round 5 is the test-surface freeze that Round 6's deployment scripts implement against. Per the discipline established in Rounds 3-4: every Round 3 module signature + every Round 4 tool signature must have a corresponding Round 5 test plan; the test plan cites the canonical interface line-by-line.

## Read order for this round (per D62 Canonical Context Load)

Agents and skills working on Round 5 perform CCL Stage 1+2 first per `MULTI_AGENT_GUIDE.md` § Canonical Context Load (D62) — canonical Stage 1 order per `MULTI_AGENT_GUIDE.md` L189-194:

1. `docs/migration/NORTH_STAR.md` — pillar priority; Round 5 primarily advances **Audit-grade** (tests are the audit evidence layer) + **Operationally stable** (regression coverage) + **Idempotent** (Tier 2 property tests prove the master invariant) pillars
2. `docs/migration/HANDOFF.md` — locked vs in-flight; **Pitfall #9 sub-class accumulator** (8 sub-classes 9.a-9.h, formalized 2026-05-10) is fresh — every test plan reference must walk each sub-class
3. `docs/migration/CURRENT_STATE.md` — confirm Round 5 is in flight; Rounds 1-4 all locked; process optimization phase 1 landed
4. `docs/migration/CHECKS_AND_BALANCES.md` — 5-gate validation discipline + CCL preamble + D72 termination rule
5. `docs/migration/RISKS.md` — R19 (Tier 0 drift) most-relevant; R22 (CLI exit-code drift) Round 4 carryover; R23 (Round 4 BACKLOG carryover) drives this round's triage mandate
6. `docs/migration/BACKLOG.md` — **B47-B107 (58 active items after B92 closed-in-cycle) are the systematic triage workload for this round per D73 + D78**
7. `docs/migration/_validation_log.md` — Round 4 D72 8-cycle entry is the most-recent lesson (Pattern E + sleeper-bug stress test established)
8. `docs/migration/_reviewer_effectiveness.md` — empirical evidence for sub-agent specialty selection in this round's validation campaign
9. **This document**
10. `docs/migration/06_TESTING.md` (canonical 6-tier framework — updated 2026-05-10 to add Tier 0 per D67)
11. `docs/migration/phase1/03_core_modules.md` (Round 3 — 17 module interfaces this round tests; Tier 0 sketches already embedded per § 1-§ 7)
12. `docs/migration/phase1/04_tools.md` (Round 4 — 11 CLI interfaces this round tests; Tier 0 sketches already embedded per § 3.1-§ 3.11)
13. `docs/migration/phase1/02_configuration.md` (Round 2 — UdmTablesList + .env + parity baseline; test inputs derive from this)
14. `docs/migration/phase1/01_database_schema.md` (Round 1 — fixture databases mirror this; integration tests deploy this DDL to Docker SQL Server)
15. `docs/migration/04_EDGE_CASES.md` — M/S/I/N/P/G/D/F/V series; every edge case must have ≥1 test in this round's plan
16. `docs/migration/03_DECISIONS.md` (search by D-number) — D15 (idempotency invariant — Tier 2 master test); D17 (idempotency ledger pattern); D67 (Tier 0 discipline); D70 (6-tier pyramid); D74-D78 (Round 4 CLI contracts)
17. `CLAUDE.md` (project root) — existing test infrastructure references; BCP CSV Contract; Do-NOT rules; reconciliation patterns (B-10, B-11, B-12)

## Scope

**In scope** (this document):

- **Foundational decisions** (unnumbered preamble — Round 5 dependencies on D-numbers + Round 3 modules + Round 4 tools)
- **§ 1**: Cross-cutting test conventions — naming, fixture inventory, CI pipeline integration, coverage targets per tier, Tier 0 vs Tier 1 boundary discipline
- **§ 2**: Round 5 producer self-check pre-flight (Pitfall #9 sub-class walk 9.a-9.h)
- **§ 3**: **Tier 0 backfill catalog** — consolidated index of all 28 Tier 0 smoke tests (17 modules from Round 3 + 11 tools from Round 4); per-test cross-link to source artifact; pass criteria; closes B55 backfill obligation
- **§ 4**: Tier 1 unit test plans — per-module + per-tool unit test surface (1-2 test names per error path + happy path)
- **§ 5**: Tier 2 property test plans — Hypothesis strategies for idempotence + hash byte-stability + tokenization determinism + schema-machine state graphs
- **§ 6**: Tier 3 integration test plans — Docker SQL Server fixture scenarios from `06_TESTING.md` extended with Round 3 + Round 4 module/tool integration
- **§ 7**: Tier 4 crash injection test plans — extend `06_TESTING.md` C1-C10 crash boundaries with Round 4 CLI-level boundaries (C11+) where applicable
- **§ 8**: Tier 5 manual audit drill plans — extend `06_TESTING.md` Q1-Q5 quarterly procedures with Round 3+4 surface
- **§ 9**: **B47-B107 systematic triage** — per-item classification: Round 5 work / Round 6 work / Round 7 work / already closed at prior round / pre-Round-5 process-optimization closure. This is the largest section and the round's most-distinctive deliverable
- **§ 10**: Edge case mapping — M / S / I / N / P / G / D / F / V series walk against Round 5 test surface (every edge case → ≥1 test)
- **§ 11**: Validation gates self-check + Round 5 acceptance criteria — § 11.1 Gate 1 + § 11.2 Gate 5 + § 11.3 Gate 2 handoff to Pattern E + § 11.4 acceptance criteria checklist
- **§ 12**: End of Round 5 — distinctive outputs summary

**Out of scope** (deferred):

- Test implementation bodies — Round 6 deployment authors actual `tests/**/*.py` files against these specs
- New decisions about test framework choice — pytest + Hypothesis already established (Round 3 § 8.3)
- New Round 1 schema additions — Round 7 (Schema Evolution Governance) territory
- Snowflake test account setup — Phase 0 deliv 0.6
- Production parity verification — Round 6 + Phase 2 scope
- Long-term performance benchmarking — Phase 6 (Health Checks)

## Foundational decisions (Round 5 dependencies)

| # | Decision | Round 5 dependency |
|---|---|---|
| D15 | Idempotency mandatory at every layer | § 5 Tier 2 master property `f(f(x)) == f(x)` applied to every transformation |
| D17 | Idempotency ledger pattern | § 4 Tier 1 tests for `ledger_step()` short-circuit + recovery sweep |
| D26 | Append-only PiiTokenProvenance | § 4 Tier 1 tests assert provenance INSERT happens and UNIQUE constraint behaves correctly |
| D55 | 5-gate validation discipline | This round's status flip 🟡 → 🟢 requires `_validation_log.md` entry |
| D56 | Mandatory second-pass after 🔴 | Iterative validation cycles per D72 ceiling |
| D62 | CCL doctrine | § 0 "Read order" exists because of D62 |
| D67 | Build-time Tier 0 smoke test discipline | § 3 backfill catalog; § 1 boundary discipline (Tier 0 vs Tier 1) |
| D70 | 6-tier test fixture strategy | This round IS the 6-tier pyramid's per-artifact instantiation |
| D72 | Validation cycle termination rule | Apply Pattern E from cycle 1 (per `_reviewer_effectiveness.md` empirical evidence — comprehensive-5-gate single-agent has confirmed false-clean rate) |
| D73 | Round 3 architectural-review acceptance with B47-B74 carryover | § 9 systematic triage mandate |
| D74 | CLI exit-code contract | § 4 Tier 1 tests assert exit-code mapping per tool |
| D75 | CLI argument naming | § 4 Tier 1 tests verify canonical arg-set accepted |
| D76 | CLI audit-row contract | § 4 Tier 1 tests verify `EventType='CLI_<TOOL_NAME>'` event row written |
| D77 | CLI Tier 0 scaffold pattern | § 3 Tier 0 backfill catalog ensures every Round 4 tool has the 6-assertion scaffold |
| D78 | Round 4 architectural-review acceptance with B77-B107 carryover | § 9 systematic triage mandate (combined with D73 = 58 items) |

## New decisions anticipated in this round

These will be captured via `udm-decision-recorder` (per D62):

| Proposed | Topic | Pillar(s) served |
|---|---|---|
| D79 | Test data fixture canonical schema — single source of truth for fixture data structure across Tiers 1-3; defined in `tests/fixtures/udm_test_fixtures/schema.sql` paralleling Round 1 DDL; refreshed at every Round 1 schema change | **Operationally stable**, **Idempotent** |
| D80 | Tier-0-to-Tier-1 transition discipline — when a Tier 0 smoke test would extend past 5s OR add an external dependency, the test must be promoted to Tier 1 with explicit cross-reference; prevents Tier 0 bloat | **Operationally stable** |
| D81 | Property-test shrinkage budget per module — Hypothesis runs with `max_examples=200` by default; modules with combinatorial state spaces (CDC engine, SCD2 engine) get `max_examples=1000` configured in fixture | **Idempotent** |
| D82 | Coverage thresholds per tier — Tier 0: 100% module-import success; Tier 1: ≥90% line coverage; **Tier 2: 100% of declared properties pass shrinkage within budget** (Hypothesis is pass-or-fail per shrinkage, NOT stochastic — per R5C1-5 cycle 1 advisory finding; shrinkage budget = `max_examples=200` + `deadline=10s` per § 5.10); Tier 3: ≥95% scenario pass rate; Tier 4: 100% crash boundary recovery; Tier 5: quarterly pass/fail recorded in `audit_reports/` | **Audit-grade**, **Operationally stable** |

---

## § 1. Cross-cutting test conventions

### § 1.1 6-tier pyramid (per D67 + D70)

Canonical 6-tier framework lives at `06_TESTING.md` (updated 2026-05-10 to add Tier 0 per D67). This Round 5 spec is the PER-MODULE / PER-TOOL instantiation of that framework. Cross-reference:

- 06_TESTING.md = horizontal strategy (what each tier proves; CI integration; fixture conventions)
- This doc = vertical per-artifact test plans (which tests live at which tier for each of 28 modules + tools)

### § 1.2 Test naming + structure conventions

| Tier | Path convention | Test name convention |
|---|---|---|
| 0 (smoke) | `tests/smoke/test_<module>.py` for modules / `tests/smoke/test_tools_<tool>.py` for CLIs | `test_<assertion_letter>_<short_description>` (e.g. `test_a_module_imports`, `test_f_pipeline_fatal_error_exits_2`) |
| 1 (unit) | `tests/unit/test_<module>.py` | `test_<behavior>` (e.g. `test_add_row_hash_deterministic`); one test per error path; one test per happy-path branch |
| 2 (property) | `tests/property/test_<invariant>.py` (organized by invariant, not by module) | `test_<invariant>_holds_for_<input_type>` (e.g. `test_idempotence_holds_for_arbitrary_dataframe`) |
| 3 (integration) | `tests/integration/test_<scenario>.py` (organized by scenario, not by module) | `test_<scenario>` (e.g. `test_first_run_populates_bronze_and_parquet`) |
| 4 (crash) | `tests/crash/test_crash_<C-number>.py` (one file per crash boundary) | `test_recovery_from_<crash_point>` |
| 5 (audit) | `docs/migration/audit_reports/Q<year>_<quarter>.md` (per quarter) | n/a — manual procedure with sign-off |

### § 1.3 Fixture inventory (per D79 proposed)

Single source of truth: `tests/fixtures/udm_test_fixtures/`. Refreshed at every Round 1 schema change.

| Fixture | Tiers using it | Description |
|---|---|---|
| `tests/fixtures/udm_test_fixtures/schema.sql` | 3, 4 | Docker SQL Server bootstrap DDL — mirrors Round 1 schema verbatim. Container: `mcr.microsoft.com/mssql/server:2022-CU14-ubuntu-22.04` (version-pinned per Round 6 § 7.10 / § 4.5 / § 5.4 / § 8.10 — `:latest` invites parity-drift class flagged by R5C1-5 advisory; CU14 is the canonical pinned version. dbt-sqlserver + SQLAlchemy test-suite precedent). Lifecycle managed via `testcontainers-python` Mssql module (session-scope container per § 1.4 CI stage 3) |
| `tests/fixtures/udm_test_fixtures/seed_data.sql` | 3, 4 | ~10K rows across 3 source tables (small/medium/large simulated); realistic PII patterns; multi-version SCD2 history. **State-leakage mitigation** (per R5C1-5 advisory): each Tier 3 test wrapped in SQLAlchemy-style transactional rollback (BEGIN at fixture entry; ROLLBACK at test exit) — preserves session-scope container performance + per-test isolation. Tier 4 crash-injection tests are non-rollback (crash itself prevents the COMMIT) — Tier 4 fixture provides its own cleanup script |
| `tests/fixtures/arbitrary_dataframe.py` | 2 | Hypothesis strategy for arbitrary Polars DataFrames; edge case generators (NaN, ±inf, ±0.0, max/min int, Unicode NFC/NFD, tabs/newlines/null bytes, Categorical, NULL-heavy) |
| `tests/fixtures/synthetic_parquet/` | 1, 3 | Pre-generated Parquet files for snapshot replay tests; covers happy path + induced corruption (1-byte truncation) + row-count mismatch |
| `tests/fixtures/mock_credentials_envelope.gpg.b64` | 1, 3 | Base64-encoded test GPG envelope decryptable with checked-in test key (marked DO_NOT_USE_IN_PROD) |
| `tests/fixtures/mock_pyodbc/` | 0, 1 | Mock pyodbc cursor utilities — return canned rows / canned OUTPUT params / simulate UNIQUE violations / simulate deadlocks |
| `tests/fixtures/mock_subprocess/` | 0, 1 | Mock subprocess.run — simulate gpg2 / tpm2_unseal / SnowSQL invocations |

### § 1.4 CI pipeline integration

Stage ordering per commit:
1. **Tier 0 stage** (≤2 min): run all `tests/smoke/*.py`; failure blocks the build
2. **Tier 1 stage** (≤5 min): run all `tests/unit/*.py`; failure blocks PR merge
3. **Tier 2 stage** (≤10 min): run all `tests/property/*.py` with `max_examples=200`; failure blocks PR merge
4. **Tier 3 stage** (≤30 min): run all `tests/integration/*.py` against Docker SQL Server fixture; runs on every PR + nightly
5. **Tier 4 stage** (≤2 hr): run `tests/crash/*.py` pre-release only
6. **Tier 5 stage** (manual): quarterly per `06_TESTING.md` Q1-Q5

Coverage report aggregated and posted to PR.

### § 1.5 Coverage targets per tier (per D82 proposed — Tier 2 reframed per R5C1-5 advisory)

| Tier | Coverage metric | Target |
|---|---|---|
| 0 | Module-import success rate | 100% (28 of 28) |
| 1 | Line coverage per module | ≥90% (idempotence-relevant fns: 100%) |
| 2 | Property invariant pass rate within shrinkage budget | **100% of declared properties must pass shrinkage within budget** (Hypothesis is pass-or-fail per shrinkage, not stochastic — R5C1-5 cycle 1 advisory finding flagged the original "≥80% pass rate" framing as a category error that risks operators normalizing genuine bugs as acceptable flake). A property that fails shrinkage = real bug; not a budget threshold. Shrinkage budget = `max_examples=200` default + `deadline=timedelta(seconds=10)` per § 5.10 |
| 3 | Scenario pass rate per nightly run | ≥95% (some flakes acceptable; investigate >5%) |
| 4 | Crash-boundary recovery success rate | 100% per pre-release run |
| 5 | Quarterly audit-question pass rate | 100% (any fail triggers Pitfall-aware retrospective per close-out skill) |

### § 1.6 Tier 0 vs Tier 1 boundary discipline (per D80 proposed)

A Tier 0 smoke test stays at Tier 0 ONLY IF:
- Runtime ≤5 seconds
- No external dependencies (no Docker, no real DB, no network)
- Tests `(a)-(f)` canonical assertion set per § 3 inventory
- Does NOT exhaustively cover error paths beyond what's documented in the spec

When a Tier 0 test would breach any of these constraints, **promote it to Tier 1** with explicit cross-reference. This prevents Tier 0 bloat (where smoke tests gradually absorb Tier 1 coverage and slow CI's first-stage gate).

Pitfall #10 reminder (per HANDOFF §8): Tier 0 is the smoke screen, NOT the comprehensive test. Resist the temptation to expand it.

### § 1.7 Pitfall #9 compliance (every test plan)

Per HANDOFF Pitfall #9 sub-class accumulator (9.a-9.h, formalized 2026-05-10), every test plan reference in §§ 3-8 that cites a Round 1 SP / column / enum / Round 2 dataclass field / Round 3 module function signature / Round 4 CLI argument MUST cite the exact canonical source (`file:line` or `file § X.Y`). The producer Gate 1 self-check walks each sub-class 9.a-9.h. The Gate 2 Pattern E reviewers (specifically the column-walk specialist per R4C4-1 precedent + empirical 0% false-clean rate from `_reviewer_effectiveness.md`) re-verify EVERY such reference. **No invented column names. No invented parameter names. No invented enum values. No invented Round 3 function names. No invented Round 4 CLI argument names. No wrong-section-cites with invented section descriptions.**

Round 4's 19-🔴 cumulative campaign + 7-round-evidence Pitfall #9 pattern apply here in full. Test plan authors who reference Round 3 module `verify_parquet_snapshot(*, registry_id, actor)` MUST preserve the `*,` keyword-only marker (sub-class 9.g). Test plan authors who reference Round 4 tool `--source` / `--table` / `--apply` MUST use canonical names per Round 4 § 1.4 (sub-class 9.b parameter-name drift applied to CLI arg names).

---

## § 2. Round 5 producer self-check pre-flight (Pitfall #9 sub-class walk)

Before invoking § 11 Pattern E review, producer (me) walks each sub-class against this artifact:

- **9.a column-name drift**: Round 1 column references — every cited column verified against `01_database_schema.md`. Specifically check: `ParquetSnapshotRegistry.CompressedBytes` (L492), `ParquetSnapshotRegistry.UncompressedBytes` (L491), `PipelineExecutionGate.ExecutingServer` (L310), `PipelineEventLog.ServerRole` (L139 — distinct cross-table), `PipelineLog.LogLevel` (L202), `PiiVaultAccessLog.(RequestId, AccessedAt, AccessedBy, AccessRole, Token, Justification, AccessSourceIp, AccessApplication)` (L1033-1048), `PiiVault.(RetentionExpiresAt, LegalHold, Status)` (filtered via SP-10 body L1965-1968). ✓ Verified.
- **9.b parameter-name drift**: SP signatures — SP-2 `PiiVault_Decrypt(@RequestId UNIQUEIDENTIFIER, @Token VARCHAR(40), @Justification NVARCHAR(MAX))` (L1414-1417); SP-4 `PipelineExecutionGate_AcquireTest(... @Action NVARCHAR(30) OUTPUT)` (L1531-1546); SP-10 `EnforceRetention(@DryRun BIT = 1)` (L1953-1954). Round 4 CLI canonical args per `04_tools.md` § 1.4: `--source` / `--table` / `--apply` / `--dry-run` / `--batch-id` / `--actor` / `--justification` / `--no-audit-event` / `--json` / `--verbose` / `--quiet`. ✓ Verified.
- **9.c enum-value drift**: `CK_PipelineEventLog_Status IN ('IN_PROGRESS','SUCCESS','FAILED','SKIPPED')` (L143-144); `CK_PipelineExecutionGate_Status IN ('PENDING', 'STARTING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'TIMEOUT', 'CANCELLED')` (L328-330); `CK_PipelineExecutionGate_CycleType IN ('AM', 'PM')` (L326-327); `CK_PipelineExecutionGate_ExecutingServer IN ('production', 'test')` (L331-332); `CK_PipelineLog_LogLevel IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')` (L215-216); SP-4 `@Action ∈ ('EXIT_SUCCEEDED', 'EXIT_RUNNING_HEALTHY', 'PROCEED_FAILOVER')` (L1546); ParquetSnapshotStatus 7-state per Round 3 § 1.3 + L515-516. ✓ Verified.
- **9.d type-width drift**: `@Token VARCHAR(40)` (L1416 — NOT VARCHAR(20) or NVARCHAR(40)); `@PiiType NVARCHAR(20)` per SP-1 (L1321 — NOT (50)); `LogLevel NVARCHAR(10)` (L202); `ExecutingServer NVARCHAR(20)` (L310); `@Action NVARCHAR(30) OUTPUT` (L1546). ✓ Verified.
- **9.e Unicode-vs-ASCII drift**: `@Token VARCHAR(40)` (ASCII per L1416 — NOT NVARCHAR); `@Justification NVARCHAR(MAX)` (Unicode per L1417); `@Plaintext NVARCHAR(MAX)` per SP-1 (L1320 — Unicode); `@RequestId UNIQUEIDENTIFIER` (L1415 — not a string type). ✓ Verified.
- **9.f cross-table column-name lift**: `ServerRole` is on `PipelineEventLog` L139 only — NOT on `PipelineExecutionGate` (which has `ExecutingServer` L310). `Status` exists on multiple tables (PipelineEventLog, PipelineExecutionGate, PipelineLog, PiiVault, ParquetSnapshotRegistry, IdempotencyLedger, PipelineExtraction) — every reference must specify which table. `BatchId` exists on multiple tables. `CreatedAt` exists on multiple tables. ✓ Verified per-table context for every reference.
- **9.g Python keyword-only marker drift**: Round 3 module signatures use `*,` keyword-only marker. Every cited Round 3 function in this doc preserves the marker: `write_parquet_snapshot(df, *, source_name, table_name, business_date, batch_id, output_dir)` (Round 3 § 1.1 L233-241); `verify_parquet_snapshot(*, registry_id, actor)` (§ 1.3 L441-445); `mark_replicated(*, registry_id, replica_target)` etc. (§ 1.3 L452-475); `decrypt_token(*, token, justification, request_id)` (§ 2.2 L608-613); `profile_lateness(*, source_name, table_name, window_days, min_sample_days)` (§ 5.2 L1143-1148); `detect_extraction_gaps(*, source_filter, as_of_date)` (§ 5.3 L1199-1203); `ledger_step(*, batch_id, source_name, table_name, event_type, metadata)` (§ 4.1 L871-883); `track(*, event_type, table_name, source_name, batch_id, event_detail)` (§ 6.3 L1398-1405); `copy_parquet_to_snowflake(*, registry_id, snowflake_table, timeout_seconds)` (§ 7.1 L1485-1489). Round 2 `verify_server_parity(baseline_path, server_name, fail_on_warning)` (L957-961 — positional, NOT keyword-only — different convention). ✓ Verified.
- **9.h wrong-section-cite with invented section description**: Every `§ X.Y` citation in this doc resolved against the target doc's actual section header before writing. Round 2 § 5.4 (Failover behavior) vs § 5.3.5 (Per-AM/PM-cycle column matrix) — distinct sections; this doc cites § 5.4 for failover-related test scenarios (Round 4 § 3.6 promote_test_to_prod testing). Round 3 § 1.3 (parquet_registry_client) vs § 1.2 (parquet_replay) vs § 1.1 (parquet_writer) — distinct sections; this doc cites correct sections for each test plan. ✓ Verified.

**Status**: ✅ producer self-check complete. Mandatory Pattern E Gate 2 review per § 11.

---

## § 3. Tier 0 backfill catalog (closes B55 + B83)

Tier 0 smoke tests for all 17 Round 3 modules + 11 Round 4 tools = 28 total. Each test follows the canonical 6-assertion contract per `06_TESTING.md` Tier 0 section + Round 4 § 1.6 (D77).

### § 3.1 Round 3 module Tier 0 inventory (17 tests)

Source: Tier 0 sketches embedded in `phase1/03_core_modules.md` § 1 through § 7. This catalog is the consolidated index.

| Module | Path | Source spec | Assertions specific to this module |
|---|---|---|---|
| `parquet_writer` | `tests/smoke/test_parquet_writer.py` | Round 3 § 1.1 L276 | mocked cursor + tmp_path output_dir; `RegistryInsertConflict` on mocked UNIQUE violation; returns `ParquetWriteResult` (file_path, file_size_bytes, row_count, sha256, registry_id, status='created') |
| `parquet_replay` | `tests/smoke/test_parquet_replay.py` | Round 3 § 1.2 L374 | mocked registry + fixture Parquet; returns `ReplayResult` (df, registry_id, source_file, row_count, sha256_verified, extracted_at, batch_id); `ParquetReplayError` on SHA mismatch; `RegistryStatusInvalid` on Status='created' |
| `parquet_registry_client` | `tests/smoke/test_parquet_registry_client.py` | Round 3 § 1.3 L478 | 7 transition functions (`verify_parquet_snapshot` / `mark_replicated` / `mark_archived` / `mark_missing` / `mark_purged` / `mark_replication_failed` / `query_snapshot`) each invocable with mocked cursor; `RegistryStatusInvalid` on invalid predecessor |
| `pii_tokenizer` | `tests/smoke/test_pii_tokenizer.py` | Round 3 § 2.1 L574 | mocked SP-1 cursor returns canned `(@Token, @WasNew=1)`; NULL pass-through; `PiiColumnNotFound` on missing column |
| `pii_decryptor` | `tests/smoke/test_pii_decryptor.py` | Round 3 § 2.2 L653 | mocked SP-2 cursor; `str` returned for active token mock; `None` for purged-status mock; auto-generated `request_id` is valid `uuid.UUID`; `TokenNotFound` on absent-Token fixture; `ValueError` on empty justification |
| `vault_client` | `tests/smoke/test_vault_client.py` | Round 3 § 2.3 L718 | `call_vault_sp` with mocked cursor; mocked deadlock triggers 3-attempt retry; `VaultUnavailable` on retry exhaustion; `configure_vault_connection_pool` second call raises `VaultConfigError` |
| `credentials_loader` | `tests/smoke/test_credentials_loader.py` | Round 3 § 3.1 L758-761 | mocked subprocess for gpg2 + tpm2_unseal; mocked cursor for audit-log INSERT; returns `CredentialsDict`; `CredentialsLoadError` on mocked gpg2 non-zero exit; sentinel detection (decrypted dict contains `'GPG_SOURCED'` → raises) |
| `server_parity_verifier` | `tests/smoke/test_server_parity_verifier.py` | Round 3 § 3.2 L803-806 | mocked filesystem reads + subprocess for system probes; synthetic baseline JSON; returns `ParityReport` with `overall ∈ {'pass', 'warn', 'fail'}`; all-match → `'pass'`; one fatal mismatch → `'fail'` AND raises `ParityFatalError` when `fail_on_warning=False` |
| `idempotency_ledger` | `tests/smoke/test_idempotency_ledger.py` | Round 3 § 4.1 L927-929 | `ledger_step` context manager with synthetic key; clean exit UPDATEs to `COMPLETED`; exception in `with` block UPDATEs to `FAILED` AND re-raises; mocked UNIQUE violation short-circuits with `was_short_circuited=True` |
| `extraction_state` | `tests/smoke/test_extraction_state.py` | Round 3 § 4.2 L1026-1028 | all 5 functions invocable; `is_date_trusted` returns bool; `most_recent_success` returns `date | None`; `record_extraction_attempt` returns int (ExtractionId); future-date input raises `InvalidTrustGate` |
| `range_scheduler` | `tests/smoke/test_range_scheduler.py` | Round 3 § 5.1 L1099 | mocked UdmTablesList + mocked `extraction_state.most_recent_success`; `ExtractionPlan` shape + ordered dates + plausible re_extraction_flags map |
| `lateness_profiler` | `tests/smoke/test_lateness_profiler.py` | Round 3 § 5.2 L1159 | mocked cursor returning canned percentile-shaped data; monotonic ordering `p50 ≤ p90 ≤ p95 ≤ p99 ≤ max`; `InsufficientHistory` (PipelineFatalError) raised at <30 sample days |
| `gap_detector` | `tests/smoke/test_gap_detector.py` | Round 3 § 5.3 L1211 | mocked cursor returning sparse PipelineExtraction; `GapReport` shape; correct missing_dates identification |
| `sensitive_data_filter` | `tests/smoke/test_sensitive_data_filter.py` | Round 3 § 6.1 L1279 | filter applied to record with `password=foo` redacts to `<REDACTED:password>`; clean record passes through; `register_pii_pattern` adds runtime pattern; invalid regex raises `FilterConfigError` |
| `log_handler` | `tests/smoke/test_log_handler.py` | Round 3 § 6.2 L1347 | handler accepts `LogRecord` and writes via mocked cursor; WARNING flushes immediately (mocked commit called); set/clear_log_context affects subsequent emits |
| `event_tracker` | `tests/smoke/test_event_tracker.py` | Round 3 § 6.3 L1432 | `track()` context manager invokable; entry writes Status='IN_PROGRESS'; clean exit writes Status='SUCCESS'; exception in `with` block writes Status='FAILED' AND re-raises; Status values match `CK_PipelineEventLog_Status` enum per Pitfall #9 9.c |
| `snowflake_uploader` | `tests/smoke/test_snowflake_uploader.py` | Round 3 § 7.1 L1521 | mocked Snowflake connector + mocked registry read/write; returns `SnowflakeCopyResult` shape; `RegistryStatusInvalid` on non-verified status fixture; mocked auth-fail raises `SnowflakeAuthFailed` |

**Closes**:
- **B55** (Tier 0 backfill for § 1 + § 2 modules): all 6 § 1 + § 2 Tier 0 sketches indexed above + cross-linked back to Round 3 source spec line citations. Marked done.
- **B83** (Tier 0 backfill for 11 Round 4 tools): see § 3.2 below.

### § 3.2 Round 4 tool Tier 0 inventory (11 tests)

Source: Tier 0 sketches embedded in `phase1/04_tools.md` § 3.1 through § 3.11. This catalog is the consolidated index.

| Tool | Path | Source spec | Assertions specific to this tool |
|---|---|---|---|
| `parquet_tier_review` | `tests/smoke/test_tools_parquet_tier_review.py` | Round 4 § 3.1 | mocked cursor with 3 synthetic `verified` rows + `--dry-run` returns exit 0, calls `query_snapshot` 3x, calls NO `mark_*`; mocked `mark_replicated` raising `RegistryStatusInvalid` returns exit 2; `--apply` without `--to-status` raises arg-parse error (exit 2) |
| `parquet_verify` | `tests/smoke/test_tools_parquet_verify.py` | Round 4 § 3.2 | `--registry-id 12345` parses; `--registry-id` + `--source` raises mutex error; mocked `verify_parquet_snapshot` success → exit 0; `RegistryStatusInvalid` → exit 2; `RegistryFileNotFound` → exit 1; `--dry-run` does NOT call `verify_parquet_snapshot` |
| `lateness_profile` | `tests/smoke/test_tools_lateness_profile.py` | Round 4 § 3.3 | `--source DNA --table ACCT` parses; mocked `profile_lateness` returning valid `LatenessReport` → exit 0 + stdout contains "p99"; `InsufficientHistory` (PipelineFatalError) → exit 2 per § 1.8 mapping; `--json` produces parseable JSON; `--no-persist` does NOT call any DB write |
| `decrypt_pii` | `tests/smoke/test_tools_decrypt_pii.py` | Round 4 § 3.4 | missing `--justification` raises arg-parse error → exit 2; mocked `decrypt_token` returning plaintext → exit 0 + stdout contains plaintext; returning `None` → exit 0 + stdout contains `CCPA-deleted`; `TokenNotFound` → exit 2; `--mask-output` masks stdout |
| `detect_extraction_gaps` | `tests/smoke/test_tools_detect_extraction_gaps.py` | Round 4 § 3.5 | mocked `detect_extraction_gaps` returning empty list → exit 0 + stdout `No gaps`; mocked returning GapReport with non-empty missing_dates → exit 1 + stdout contains source.table; `--alert` + `--actor automic` + non-empty gaps → mocked `alert_dispatcher` invoked once; `--json` parseable |
| `promote_test_to_prod` | `tests/smoke/test_tools_promote_test_to_prod.py` | Round 4 § 3.6 | missing `--cycle` / `--justification` → arg-parse error → exit 2; mocked SP-4 `@Action='PROCEED_FAILOVER'` + parity-pass → exit 0 + stdout contains `'PROCEED_FAILOVER'`; `@Action='EXIT_SUCCEEDED'` → exit 0; `@Action='EXIT_RUNNING_HEALTHY'` → exit 1; `ParityFatalError` → exit 2; `--skip-parity-check` allows past parity-fail mock |
| `verify_server_parity` | `tests/smoke/test_tools_verify_server_parity.py` | Round 4 § 3.7 | mocked `verify_server_parity` returning `overall='pass'` → exit 0; `'warn'` → exit 1; `'fail'` → exit 2; `ParityBaselineMissing` → exit 2; `--alert` + `fatal` → mocked `alert_dispatcher` invoked once; `--fail-on-warning` + `'warn'` → exit 2 (mapped up) |
| `enforce_retention` | `tests/smoke/test_tools_enforce_retention.py` | Round 4 § 3.8 | `python3 tools/enforce_retention.py` (no args = dry-run default) invokable; mocked SP-10 returning `WouldBeFlipped` count → exit 0; `--apply` calls SP-10 with `@DryRun=0`; mocked SP-10 returning 0 WouldBeFlipped → exit 0 (legal-hold silently filtered); `VaultConfigError` → exit 2; arg-parse rejects `--retention-date` / `--actor-name` / `--categories` (forward-incompat guard against invented Pitfall #9.b parameter drift per Round 4 § 3.8 L1118 + B93 + B94 schema-evolution tracking) |
| `process_ccpa_deletion` | `tests/smoke/test_tools_process_ccpa_deletion.py` | Round 4 § 3.9 | missing `--request-id`/`--justification` → arg-parse exit 2; `--token-file` + `--subject-id` → mutex exit 2; mocked SP returning deletion counts → exit 0; mocked SP raising `LegalHoldConflict` → exit 2 |
| `log_retention_cleanup` | `tests/smoke/test_tools_log_retention_cleanup.py` | Round 4 § 3.10 | `--dry-run` does NOT call DELETE; `--apply` invokes per-level DELETE; ERROR/CRITICAL never in DELETE WHERE clause; `--batch-size 10000` reflected in DELETE |
| `alert_dispatcher` | `tests/smoke/test_tools_alert_dispatcher.py` | Round 4 § 3.11 | missing `--severity`/`--source-tool`/`--message` → arg-parse exit 2; mocked successful channel → exit 0; mocked all-channel failure → exit 1; `--severity warning` + default channels → Slack invoked, PagerDuty NOT; `--details-json '{invalid json'` → arg-parse error |

### § 3.3 Implementation requirement (Round 6 deployment)

Per D67 + B83: Round 6 deployment authors all 28 Tier 0 smoke test files against the assertions specified above. Each file uses `pytest` + `unittest.mock` + mocked pyodbc cursor + mocked subprocess. CI's Tier 0 stage runs them all in ≤2 minutes (target: 28 tests × 5 sec = 140 sec).

### § 3.4 Verification

Tier 0 drift detection per B58 (`tools/verify_tier0_drift.py` — interface stub from Round 3 close-out): at every Round 6+ deployment, this tool compares each `tests/smoke/*.py` assertion set against the source spec's documented Tier 0 sketch. Drift → 🔴.

---

## § 4. Tier 1 unit test plans

For each of 28 modules + tools, Tier 1 tests cover happy path + per-error-path + per-edge-case behaviors. Total estimated Tier 1 test count: ~250-350 individual tests.

### § 4.1 Tier 1 per Round 3 module

| Module | Tier 1 test surface |
|---|---|
| `parquet_writer` | (a) given fixture df + tempdir → assert path / size / row count / sha256; (b) idempotency — second call same key raises `RegistryInsertConflict`; (c) crash injection — kill mid-rename → inflight file present + registry row absent; (d) ZSTD-3 compression verified via file inspection; (e) Hive partition path matches `year=YYYY/month=MM/day=DD` |
| `parquet_replay` | (a) happy path — write → register → verify → replay → assert df equals original; (b) SHA mismatch — corrupt file post-write, assert `ParquetReplayError`; (c) status not verified — `RegistryStatusInvalid` raised; (d) idempotent re-replay via ledger short-circuit |
| `parquet_registry_client` | (a) each of 7 transition functions: happy path + invalid-predecessor + idempotent re-call; (b) SHA mismatch detection in `verify_parquet_snapshot`; (c) audit columns written per transition (`LastVerifiedAt` on verify; `PurgedAt` + `PurgedReason` on purge; `SnowflakeUploadedAt` on replicate) |
| `pii_tokenizer` | (a) deterministic round-trip — same plaintext + same source = same token; (b) NULL pass-through; (c) Oracle empty-string normalization (per E-1); (d) `PiiColumnNotFound` on misconfigured column; (e) `VaultUnavailable` retry behavior; (f) provenance INSERT idempotency under UNIQUE violation |
| `pii_decryptor` | (a) active token decrypt + audit row present in `PiiVaultAccessLog`; (b) `deleted_per_request` returns None + audit row STILL present per D26; (c) `TokenNotFound` on absent token; (d) missing `justification` raises ValueError per SP-2 NOT NULL constraint; (e) request_id auto-generation creates valid UUID |
| `vault_client` | (a) SP invocation with mock cursor; (b) retry on mocked deadlock (3 attempts); (c) `VaultUnavailable` on retry exhaustion; (d) `VaultConfigError` on unknown SP; (e) connection pool single-init then second-init raises |
| `credentials_loader` | (a) per-error-path: envelope missing / GPG fails / sentinel reappears / schema version drift; (b) caching — second call returns cached dict without re-decrypt; (c) Snowflake RSA key written to `/dev/shm/snowflake_pk_<pid>` mode 0600; (d) `release_snowflake_key()` cleanup post-session |
| `server_parity_verifier` | (a) per-check coverage — Python version / library SHA / env var / filesystem layout / systemd unit SHA / TPM2 PCR / envelope SHA; (b) documented exceptions honored (`expires_at > today` accepted; expired rejected); (c) per-severity tier exit-code mapping; (d) baseline JSON malformed / missing → `ParityBaselineMissing` |
| `idempotency_ledger` | (a) short-circuit on COMPLETED; (b) raise on IN_PROGRESS; (c) raise + retry on FAILED (caller decision); (d) startup_recovery_sweep — mock stale rows, assert UPDATE to FAILED; (e) UNIQUE constraint serializes concurrent attempts |
| `extraction_state` | (a) each function per status — SUCCESS / FAILED / IN_PROGRESS / no row; (b) re-extraction sequencing — attempt 1 then 2 then 3; (c) future-date input to `is_date_trusted` raises `InvalidTrustGate` |
| `range_scheduler` | (a) `ExtractionPlan` shape with valid date ordering; (b) `RangePolicyMissing` if `ExtractionRangePolicy` absent for required table; (c) `LookbackDays` window correctly applied; (d) `FirstLoadDate` boundary respected |
| `lateness_profiler` | (a) monotonic ordering p50 ≤ p90 ≤ p95 ≤ p99 ≤ max in report; (b) insufficient history → `InsufficientHistory` (PipelineFatalError) + helpful message; (c) `--persist` writes `LatenessProfile` row; `--no-persist` does not |
| `gap_detector` | (a) no-gaps / single-gap / multiple-source gaps reporting; (b) `--as-of-date` historical view consistency; (c) `--alert` invocation gating; (d) `recommended_action` correctly classifies gaps as `backfill` / `investigate-source` / `within-lookback-no-action` |
| `sensitive_data_filter` | (a) each pattern (password / RSA private key / passphrase / per-source PII); (b) pattern doesn't match clean text; (c) multi-pattern message — all patterns redacted; (d) thread-safety verified via concurrent emit |
| `log_handler` | (a) each severity level; (b) buffer flush at 10 records per OBS-4; (c) WARNING+ immediate flush; (d) SensitiveDataFilter applied — plaintext in log message → redacted in PipelineLog row |
| `event_tracker` | (a) each event type + status transition; (b) OBS-7 metadata JSON-merge pattern; (c) skip helper writes Status='SKIPPED' per OBS-3; (d) per Pitfall #9 9.c — Status values strictly in `('IN_PROGRESS','SUCCESS','FAILED','SKIPPED')` enum |
| `snowflake_uploader` | (a) each error path (auth fail / budget alert / copy timeout / registry status invalid); (b) registry status flip happens AFTER COPY succeeds; (c) RSA key file cleanup post-session — assert `/dev/shm` path is unlinked |

### § 4.2 Tier 1 per Round 4 tool

| Tool | Tier 1 test surface |
|---|---|
| `parquet_tier_review` | (a) each status transition path (created → verified → replicated → archived → purged) — happy path + invalid predecessor + age filter; (b) `--age-days 30` correctly filters newer rows; (c) per-error-path coverage; (d) status-machine state graph property — never transitions to invalid predecessor |
| `parquet_verify` | (a) per-error-path coverage; happy path; `--dry-run` semantics; (b) `--continue-on-error` — second row's failure doesn't abort first/third row's success; (c) idempotent re-call returns `SKIPPED_ALREADY_VERIFIED`; (d) `--registry-id` + range-filter mutual exclusion |
| `lateness_profile` | (a) monotonic ordering in stdout; (b) insufficient history → exit 2 (per § 1.8 PipelineFatalError mapping); (c) `--json` schema stable; (d) `--persist` writes `LatenessProfile` row |
| `decrypt_pii` | (a) `--justification` required (missing → arg-parse exit 2); (b) per-token-status (decrypted / CCPA-deleted / not-found) — each produces expected stdout + audit row; (c) `--token-file` reads correctly; comment lines (`#`) skipped; (d) P5 verification — log lines never contain plaintext; SensitiveDataFilter applied |
| `detect_extraction_gaps` | (a) no-gaps / single-gap / multiple-source gaps; (b) `--as-of-date` historical consistency; (c) `--alert` invocation gating; (d) exit 0 on clean / exit 1 on gaps detected |
| `promote_test_to_prod` | (a) per-verdict path (PROCEED_FAILOVER / EXIT_SUCCEEDED / EXIT_RUNNING_HEALTHY / parity-fail); (b) `--skip-parity-check` requires `--justification` text containing rationale (Tier 1 semantic check via keyword); (c) audit event written; (d) idempotent re-call on acknowledged failover is no-op |
| `verify_server_parity` | (a) per-severity tier exit-code mapping (informational → 0 / warning → 1 / fatal → 2); (b) per-check coverage; (c) documented_exceptions honored; (d) `--fail-on-warning` flag elevates warning to fatal |
| `enforce_retention` | (a) dry-run vs apply behavior; LegalHold respect (rows with LegalHold=1 NOT purged); (b) SP-10 returns canonical `WouldBeFlipped` count on `@DryRun=1`; tool stdout reflects accurately; (c) `VaultConfigError` → exit 2; (d) forward-incompat guard — invented args rejected by arg-parse |
| `process_ccpa_deletion` | (a) per-error path (token-not-found / already-deleted / legal-hold-conflict); (b) `--token-file` + `--subject-id` mutex; (c) audit `CcpaDeletionLog` row written per token; (d) `--request-id` traceable through audit |
| `log_retention_cleanup` | (a) per-level retention rule (DEBUG/INFO 30d; WARNING 90d; ERROR/CRITICAL never); (b) `--batch-size` honored; (c) lock timeout → exit 1; (d) sp_getapplock prevents concurrent runs |
| `alert_dispatcher` | (a) severity-to-channel mapping (informational → Slack only; warning → Slack + email; fatal → Slack + email + PagerDuty); (b) dedupe-key passed through to PagerDuty payload; (c) SensitiveDataFilter applied to message before dispatch; (d) zero-channels-available + severity=fatal → exit 2 + log-only audit trail (per B98) |

**Closes**: B85 (`utils/errors.py` base classes) — needed by every Tier 1 test plan above that asserts exception → exit-code mapping per D74. § 4 specifies the test surface; Round 6 implementation authors `utils/errors.py` first, then writes Tier 1 tests against the exception class hierarchy.

---

## § 5. Tier 2 property test plans

Hypothesis-based property tests. Organized by invariant, not by module (per § 1.2 conventions).

### § 5.1 Master idempotence property (D15)

```python
@given(df=arbitrary_dataframe_strategy())
def test_pipeline_step_is_idempotent(df, transformation):
    """For every transformation f in the pipeline: f(f(x)) == f(x)."""
    once = transformation(df)
    twice = transformation(transformation(df))
    assert once.frame_equal(twice)
```

Apply to: `add_row_hash`, `sanitize_strings`, `cast_bit_columns`, `_filter_null_pks`, `_coerce_blank_pks`, `_dedup_source_pks`, `conform_to_schema`, `tokenize_pii_columns`, `reorder_columns_for_bcp`.

### § 5.2 Hash byte-stability

```python
@given(df=arbitrary_dataframe_strategy())
def test_hash_byte_stable_across_reorder(df):
    """Reordering rows then hashing produces same hash set."""
    h1 = sorted(add_row_hash(df)['_row_hash'].to_list())
    h2 = sorted(add_row_hash(df.sample(n=len(df)))['_row_hash'].to_list())
    assert h1 == h2
```

### § 5.3 Tokenization determinism

```python
@given(plaintext=st.text(min_size=1, max_size=200))
def test_tokenize_deterministic(plaintext, vault):
    """Same plaintext returns same token, even after restart."""
    t1 = tokenize(plaintext, 'EMAIL', 'DNA')
    t2 = tokenize(plaintext, 'EMAIL', 'DNA')
    assert t1 == t2
```

### § 5.4 Encryption roundtrip

```python
@given(plaintext=st.text())
def test_encrypt_decrypt_roundtrip(plaintext, vault):
    token = tokenize(plaintext, 'EMAIL', 'DNA')
    recovered = decrypt(token)
    assert recovered == plaintext
```

### § 5.5 ParquetSnapshotRegistry status-machine state graph

```python
@given(transition_sequence=st.lists(st.sampled_from(['verify', 'replicate', 'archive', 'purge', 'mark_missing']), max_size=10))
def test_registry_status_transitions_never_invalid(transition_sequence):
    """Every transition path produces valid Status; no path produces invalid predecessor without raising."""
    registry_id = create_test_row(status='created')
    for transition in transition_sequence:
        try:
            apply_transition(registry_id, transition)
        except RegistryStatusInvalid:
            pass  # Expected when transition not valid from current state
        assert query_status(registry_id) in VALID_STATUSES
```

### § 5.6 Lateness percentile monotonicity

```python
@given(samples=st.lists(st.floats(min_value=0, max_value=30), min_size=30, max_size=500))
def test_lateness_percentiles_monotonic(samples):
    """p50 ≤ p90 ≤ p95 ≤ p99 ≤ max for any sample distribution."""
    report = profile_lateness_from_samples(samples)
    assert report.p50_days <= report.p90_days
    assert report.p90_days <= report.p95_days
    assert report.p95_days <= report.p99_days
    assert report.p99_days <= report.max_observed_days
```

### § 5.7 SensitiveDataFilter idempotence (per § 6.1 module spec)

```python
@given(log_message=st.text())
def test_sensitive_data_filter_idempotent(log_message):
    """filter(filter(msg)) == filter(msg) — no double-redaction artifacts."""
    once = sensitive_data_filter.apply(log_message)
    twice = sensitive_data_filter.apply(once)
    assert once == twice
```

### § 5.8 PiiTokenProvenance UNIQUE constraint property

```python
@given(observations=st.lists(st.tuples(st.text(), st.text(), st.text(), st.text(), st.text()), max_size=20))
def test_provenance_unique_constraint_dedups(observations):
    """Re-inserting same (Token, SourceName, ObjectName, ColumnName, FilePath) is a no-op per D26."""
    for obs in observations:
        upsert_provenance(*obs)
    # Total row count = unique observations count
    assert provenance_row_count() == len(set(observations))
```

### § 5.9 Edge case generators (per `06_TESTING.md` § Tier 2 + new for Round 5)

- Numeric: NaN, ±inf, ±0.0, max/min int, max precision decimal (W-3)
- String: Unicode (NFC/NFD), tabs/newlines/null bytes, very long, empty, all-whitespace (B-6, W-2)
- NULL-heavy / NULL-empty patterns
- Polars Categorical columns (E-20)
- Mixed dtypes within a column (post-coercion)
- **NEW**: ParquetSnapshotRegistry Status enum + transition graph (per § 5.5)
- **NEW**: SP-4 @Action enum + verdict-to-exit-code mapping (per Round 4 § 3.6)
- **NEW**: ParityReport severity tier + exit-code mapping (per Round 4 § 3.7)

### § 5.10 Property-test budget (per D81 proposed)

- Default: `max_examples=200` per `pytest.fixture(scope='session')` (consistent with pandas test suite which uses 100, slightly above SQLAlchemy's 50; per R5C1-5 advisory finding)
- Combinatorial-heavy modules (CDC engine, SCD2 engine, transition state graphs): `max_examples=1000` (consistent with numpy test suite ceiling)
- Shrinkage budget: `deadline=timedelta(seconds=10)` per example to prevent runaway
- Pre-release: bump to `max_examples=5000` for the master idempotence property to find rare edge cases
- **CI determinism**: Hypothesis profile in `tests/conftest.py` uses `settings.register_profile('ci', derandomize=True, max_examples=200)` per R5C1-5 advisory — CI runs use derandomized profile so failures are reproducible across CI runs (avoids the "passed yesterday but failed today on the same code" Hypothesis trap); local dev uses default randomized profile for broader coverage

---

## § 6. Tier 3 integration test plans

Build on `06_TESTING.md` Tier 3 scenarios + extend with Round 3 + Round 4 module/tool integration.

### § 6.1 Pre-existing scenarios from `06_TESTING.md`

All 9 scenarios (test_first_run_populates_bronze_and_parquet through test_pii_decrypt_logs_audit_row) preserved as-is. Round 5 adds the scenarios below.

### § 6.2 New Round 3 module integration scenarios

| Scenario | Test |
|---|---|
| `test_parquet_write_verify_replay_chain` | Write → verify → replay through full module chain; assert df bytes identical |
| `test_credentials_loader_full_decrypt` | Real GPG envelope (test key) → decrypt → validate `CredentialsDict` shape + audit event written |
| `test_idempotency_ledger_concurrency` | Two workers attempt same step concurrently; exactly one succeeds, other short-circuits |
| `test_extraction_state_machine` | Per-day extraction state lifecycle (IN_PROGRESS → SUCCESS / FAILED → re-extraction) |
| `test_range_scheduler_with_real_policies` | Real `ExtractionRangePolicy` rows + real `extraction_state` history → produce `ExtractionPlan` |
| `test_lateness_profiler_full_history` | Real `PipelineExtraction` data with synthetic delay distribution; verify percentile computation against known answer |
| `test_gap_detector_synthetic_gaps` | Inject gap into `PipelineExtraction`; verify `GapReport` correctly identifies it |
| `test_event_tracker_with_real_pipeline_event_log` | Full `track()` context manager against real `PipelineEventLog` table; verify status transitions + OBS-7 metadata merge |
| `test_snowflake_uploader_to_test_account` | Real Snowflake trial account (account-setup unscoped in Phase 0; presupposed by Phase 0 deliv 0.6 cost-data capture per 02_PHASES.md L44) + real Parquet upload; verify registry status flip + COPY INTO history |

### § 6.3 New Round 4 tool integration scenarios

| Scenario | Test |
|---|---|
| `test_parquet_tier_review_full_lifecycle` | Real registry rows + tool transitions through full status chain; verify per-transition audit events |
| `test_decrypt_pii_audit_trail` | Operator decrypt via CLI → verify `PiiVaultAccessLog` row matches request_id + justification + actor; P5 verification (no plaintext in PipelineLog) |
| `test_promote_test_to_prod_failover_e2e` | Real `PipelineExecutionGate` with synthetic missing-heartbeat row → SP-3/4/5/6 invocation chain → assert gate state flipped + audit event written |
| `test_verify_server_parity_against_drift` | Docker fixture with intentional drifts at each severity tier (informational/warning/fatal); assert exit-code mapping correct |
| `test_enforce_retention_with_synthetic_old_rows` | Synthetic `PiiVault` rows with `RetentionExpiresAt < now` + mix of LegalHold=0/1; verify SP-10 flips only LegalHold=0 rows |
| `test_log_retention_cleanup_preserves_errors` | Synthetic `PipelineLog` with old DEBUG/INFO/WARNING + ERROR/CRITICAL rows; verify DELETE removes only old DEBUG/INFO/WARNING |
| `test_alert_dispatcher_with_test_channels` | Real Slack test workspace + PagerDuty sandbox + test email; fire alert, verify receipt + audit row |

### § 6.4 Cross-tool integration scenarios (NEW)

| Scenario | Test |
|---|---|
| `test_gap_detection_triggers_alert_dispatcher` | `detect_extraction_gaps` returns non-empty `GapReport` → `alert_dispatcher` invoked → operator-visible alert |
| `test_parity_failure_triggers_alert_dispatcher` | `verify_server_parity` returns `overall='fail'` + `--alert` → `alert_dispatcher` fires page-class alert |
| `test_retention_purge_event_recorded` | `enforce_retention --apply` → `PipelineEventLog` row written with `EventType='CLI_ENFORCE_RETENTION'` per D76 |

---

## § 7. Tier 4 crash injection test plans

Extend `06_TESTING.md` C1-C10 crash boundaries with Round 4 CLI-level boundaries.

### § 7.1 Pre-existing C1-C10 from `06_TESTING.md`

Preserved as-is. All crash points are module-level (extract / Parquet / SCD2 / ledger / Snowflake).

### § 7.2 New CLI-level crash boundaries (C11+)

| ID | Crash point | Expected post-restart state |
|---|---|---|
| C11 | `parquet_tier_review --apply` mid-batch (between two transition function calls) | Some rows transitioned; remainder unchanged; re-run idempotent (predecessor-Status filter skips already-transitioned rows) |
| C12 | `decrypt_pii` mid-batch (operator-supplied token list, partway through) | Some tokens decrypted + audit-logged; remainder not yet processed; re-run idempotent (audit is append-only per D26) |
| C13 | `promote_test_to_prod --apply` between SP-4 verdict and SP-6 acknowledgment | Gate state inconsistent (SP-4 said failover, SP-6 not yet called); re-run on next operator invocation completes acknowledgment OR detects already-acknowledged state |
| C14 | `enforce_retention --apply` mid-SP-10 transaction | SP-10 is single transactional UPDATE — either committed or rolled back; restart sees consistent state per standard SQL Server transactional atomicity |
| C15 | `alert_dispatcher` between channel-1-success and channel-2-attempt | Some channels delivered; some not; exit code reflects partial success per Round 4 § 3.11 |

### § 7.3 Pass criteria

After restart, system converges to the same final state as a clean run. No data loss. No stale locks. Audit log reflects partial completion accurately. `_validation_log.md` records crash test outcomes per release.

---

## § 8. Tier 5 manual audit drill plans

Extend `06_TESTING.md` Q1-Q5 with Round 3 + Round 4 surface.

### § 8.1 Pre-existing Q1-Q5

Preserved as-is.

### § 8.2 New audit drills (Q6+)

| ID | Drill | Frequency |
|---|---|---|
| Q6 | **CLI audit trail verification** — pick 3 random `EventType='CLI_*'` rows from last quarter's `PipelineEventLog`; verify `Metadata.actor` matches operator records; verify `Metadata.justification` (where applicable) is non-empty; verify P5 compliance (no plaintext in metadata) | Quarterly |
| Q7 | **Tier 0 drift audit** — run `tools/verify_tier0_drift.py` (per B58); confirm every `tests/smoke/*.py` assertion set matches its source spec's documented Tier 0 sketch; flag drift as 🔴 | Quarterly |
| Q8 | **Reviewer effectiveness ledger audit** — manually review `_reviewer_effectiveness.md` trend table; confirm no specialty role exceeds 25% false-clean rate; confirm self-improvement loop proposals (per Round 8) are landing | Quarterly |
| Q9 | **CCPA deletion proof** — pick 1 historical CCPA deletion request from last quarter; verify `CcpaDeletionLog` row exists with valid `--request-id` + justification; verify affected tokens decrypted to None post-deletion | Quarterly |
| Q10 | **Backup integrity drill** — restore PiiVault from latest backup to staging; verify random sample of 100 tokens decrypt to expected plaintext (W-12 vault restore test cadence) | Weekly |

---

## § 9. B47-B107 systematic triage (per D73 + D78 carryover mandates)

**Scope**: every B-number in B47-B107 active range, plus B33/B36/B37 (D62 follow-ups) + B75/B76 (Round 2 cycle 1 Pattern E) that overlap the Round 5 carryover surface. Each item triaged below with its **canonical BACKLOG description** (NOT inferred from B-number range) and classification: Round 5 work / Round 6 work / Round 7 work / already closed at prior round / pre-Round-5 process-optimization phase 1 closure.

**Producer note (cycle 1 fix)**: Round 5 cycle 1 R5C1-2 + R5C1-4 reviewers found the initial draft of this section misclassified ~12 B-items by using B-number range as proxy for content (e.g. claiming B47-B50 were "Round 3 Tier 0/1/2/3 reconciliation" — actually Round 2 first-pass / third-pass items with completely different topics). This rebuilt § 9 cites each item's canonical BACKLOG.md description.

### § 9.1 Round 5 closes — items this round resolves

Each item closed by Round 5 spec content (this doc) or by Round 5 close-out cross-doc updates:

| B-num | Canonical BACKLOG description | How Round 5 closes it |
|---|---|---|
| B47 | Document D66 sub-decision (D66.1/D66.2/D66.3) supersession mechanics — per-sub vs bundle Status field | Closure via Round 5 close-out note: D66 sub-decisions follow D45.x precedent (lock as bundle); document inline in `03_DECISIONS.md` D66 + reference from HANDOFF Pitfall #2 (premature lock) at close-out |
| B48 | File new I-series edge case in `04_EDGE_CASES.md` for concurrent gate-table acquire via SP-3 (I3 variant) | Close-out task: append new I-series row to `04_EDGE_CASES.md`; sibling to T1-T3 close-out task per § 10.2 |
| B50 | Strengthen Pitfall #9 wording in HANDOFF.md ("fix-introduces-fresh-instance" three-round evidence) | **SUPERSEDED** by HANDOFF §8 Pitfall #9 sub-class accumulator (9.a-9.h, formalized 2026-05-10 in process-optimization phase 1) — B50's narrative-wording goal is now fully covered by the formal 8-sub-class checklist. Mark closed at Round 5 close-out as "superseded by accumulator" |
| B83 | Tier 0 backfill for all 11 Round 4 tools | Closed via § 3.2 catalog above (line citations to Round 4 source spec) |
| B84 | `udm-test-author` agent CLI extension (D67 + D77 alignment) | § 3 6-assertion contract + § 4 Tier 1 surface establish the contract; skill-file update tracked for Round 8 self-improvement loop |
| B91 | F-next split into EXIT_SUCCEEDED + EXIT_RUNNING_HEALTHY sub-states | Closure via Round 5 § 10 edge case mapping: F-next close-out task (B108) explicitly enumerates the two sub-states |
| B98 | New F25 edge case (alert dispatcher zero-channels-fatal escalation) | Closure via close-out task: append F25 to `04_EDGE_CASES.md` (sibling to B108 close-out); § 4.2 alert_dispatcher row + § 6.4 cross-tool reference the mechanism |
| B99 | SP-4↔SP-6 race window documentation | Closed via § 7.2 C13 crash injection test (Tier 4) — documents the race window and recovery path |
| B105 | CYCLE_FAILED_OVER + CYCLE_CANCELLED EventType tracking | Partial closure: § 6.2 + § 7.2 reference these canonical names; full closure pairs with B86 (CLI_* + CYCLE_* family in CLAUDE.md) deferred to Round 6 |

**Round 5 closure count**: 9 items (down from initial draft's 15 — cycle 2 R5C2 found B54/B55/B56/B57 already closed at Round 3 close-out per BACKLOG L147-150; B100 + B102 wrong-doc-scope — their canonical targets are Round 4 § 5.2 / Round 4 § 0 which Round 5 doesn't touch; relocated to § 9.2 Round 6 work + § 9.4 already-closed respectively).

**Close-out task list** (work that closes these items at Round 5 close-out, not in this spec doc):
- B47 narrative addition to `03_DECISIONS.md` D66
- B48 new I-series row to `04_EDGE_CASES.md` (paired with B108)
- B50 marked superseded by HANDOFF §8 sub-class accumulator
- B98 / F25 appended to `04_EDGE_CASES.md`
- B102 cycle-1 fix verification: confirm § 0 of this doc actually uses canonical Stage 1 order

### § 9.2 Round 6 work — defer to deployment

Implementation work that requires authoring code, not spec updates:

| B-num | Canonical BACKLOG description | Round 6 scope |
|---|---|---|
| B58 | Author Tier 0 vs module-interface reconciliation script (drift detection per R19 mitigation) | Round 6 implements `tools/verify_tier0_drift.py`; Round 5 § 3.4 specifies the contract this script enforces |
| B63 | Extend Tier 0 sketches to cover ALL declared Error modes per module (Reviewer C 13/17 partial; 2 zero-coverage) | Round 6 extends Tier 0 sketches per § 3 6-assertion contract; Round 5 plan is the contract |
| B65 | Define `release_snowflake_key(*, key_file_path: str) -> None` inline in Round 3 § 3.1 | Round 6 implements per Round 3 § 3.1 + § 7.1 specs |
| B66 | `event_tracker` god-module refactor (split → PipelineEventLog writer + gate_heartbeat module) | Round 6 architectural refactor decision; Round 5 test plan does NOT assume refactor structure |
| B67 | `vault_client.call_vault_sp` typed wrappers (`call_get_or_create_token`, `call_decrypt`, etc.) | Round 6 implements per Reviewer D recommendation; Round 5 § 4.1 vault_client tests accommodate either signature |
| B68 | `sensitive_data_filter` thread-safety contradiction resolution | Round 6 implementation decision (option a or b); Round 5 § 4.1 + § 5.7 test for thread-safety either way |
| B70 | `ledger_step(metadata=...)` param footgun mitigation (DeprecationWarning until B63 lands OR remove param) | Round 6 implements; Round 5 § 4.1 unit tests accommodate either path |
| B71 | Nested with-block example showing `event_tracker.track()` outer + `ledger_step` inner | Round 6 documentation; Round 5 test plan references the pattern |
| B72 | Pin `LedgerStep.prior_result is None` caller-side contract (mypy + Tier 0 assertion) | Round 6 implements + adds Tier 0 assertion; Round 5 § 4.1 unit tests assert None safety |
| B85 | Author `utils/errors.py` base classes (PipelineError / PipelineFatalError / PipelineRetryableError + per-module subclasses) | Round 6 implements per D68 hierarchy; Round 5 § 4 references the classes |
| B86 | Add `CLI_*` EventType family (+ CYCLE_* per B105) to CLAUDE.md Architecture Decisions | Round 6 documentation update — partial closure with B105 |
| B87 | KeyboardInterrupt → exit 1 vs exit 130 decision | Round 6 implementation choice + CLAUDE.md note; defaults to Round 4 § 1.8 contract |
| B88 | `--dry-run` + `--apply` mutex clarification | Round 6 arg-parser implementation; Round 5 § 4.2 Tier 1 tests verify mutex |
| B89 | Reconcile D77 5-vs-6 Tier 0 assertion count (Round 4 § 2 lists 5; Round 4 § 1.6 lists 6) | Round 6 documentation edit to Round 4 § 2 (update D77 entry to 6 assertions matching § 1.6 + 06_TESTING.md). **Note**: B89 was incorrectly marked "closed in process optimization phase 1" in the initial draft of this section — corrected at cycle 1 fix per R5C1-4 + R5C1-2 findings. The actual 5-vs-6 inconsistency in `04_tools.md` § 2 still exists; only Round 6 deployment can land the source-spec edit |
| B90 | Explicit handling of `AUTOMIC_RUN_ID set AND isatty() True` edge case | Round 6 implementation per Round 4 § 1.7 hedge; Round 5 § 4.2 Tier 1 tests verify behavior |
| B96 | SIGINT/exit-130 rationale note added to § 1.8 (R5C1-5 advisory) | Round 6 documentation update |
| B97 | SnowSQL exit-code cross-reference note added to § 1.1 (R5C1-5 advisory) | Round 6 documentation update |
| B101 | RB-11 framing reconciliation (canonical title "7-Year Retention Enforcement" vs "legal-hold runbook" mislabel) | Round 6 fix: either rename RB-11 in `05_RUNBOOKS.md` or correct all Round 4 § 3.8 + § 3.9 framing. **Note**: initial draft of this section claimed Round 5 closes B101 via § 8.2 Q-drills; R5C1-2 found § 8.2 does NOT actually reference RB-11 by canonical title. Corrected here — Round 6 work |
| B103 | Round 3 § 2.2 `decrypt_token` internal contradiction (DecryptDenied PipelineFatalError vs returns None docstring) | Round 6 fix to Round 3 § 2.2 — either remove `DecryptDenied` exception class OR update docstring; Round 5 § 4.1 pii_decryptor tests assume returns-None path consistent with current docstring |
| B104 | `log_retention_cleanup --batch-size` default 50000 → 4000 (B-2 lock-escalation lesson) | Round 6 update to Round 4 § 3.10 default value + Round 6 implementation honors new default |
| B106 | B101 line citation off-by-one (claims L1124/L1156/L1215; actual L1069/L1125/L1216 post-fixes) | Round 6 fix to BACKLOG.md B101 entry — refresh line citations; trivial polish |
| B69 | Add explicit "module startup sequence" section to Round 3 spec or Round 6 deploy doc — credentials_loader → vault pool config → server_parity_verifier → ledger sweep → orchestration | Round 6 dependency per BACKLOG L62 — implementer wires this. Round 5 test plans cover behavior at each stage but don't impose sequence |
| B100 | § 5.2 (Round 4 04_tools.md) + § 10.2 (Round 3 03_core_modules.md) Gate 5 label rename | **Wrong-doc-scope** — Round 5 § 11.2 uses the corrected label inline, but the canonical B100 targets edits to Round 4 + Round 3 spec docs which Round 5 doesn't modify. Round 6 deployment-time or Round 7 governance edits those locked spec docs |
| B102 | § 0 Read order in Round 4 04_tools.md uses canonical CCL Stage 1 order | **Wrong-doc-scope** — Round 5 § 0 fix applies cycle 1 fix-1 to Round 5's own § 0 but the canonical B102 targets Round 4's § 0. Round 6 or Round 7 governance edits Round 4's spec doc |

**Round 6 deferral count**: 24 items (initial draft 21 + 3 cycle-2 corrections: B69 promoted from § 9.6 + B100 + B102 moved from § 9.1 wrong-doc-scope claims).

### § 9.3 Round 7 work — Schema Evolution Governance

Items requiring Round 1 schema changes or 02_PHASES.md amendments:

| B-num | Canonical BACKLOG description | Round 7 scope |
|---|---|---|
| B79 | SP-4 `@AcknowledgmentOnly` schema evolution (Round 4 § 3.6 promote_test_to_prod dry-run dependency) | Round 7 — SP signature change requires Round 1 supersession discipline |
| B80 | `JOB_PARQUET_VERIFY` + `JOB_LOG_CLEANUP` Automic inventory amendment (frozen-8 → 10) | Round 7 — Round 2 § 5.1 inventory change |
| B81 | Author CCPA deletion SP (extends B01 — OrphanedTokenLog wiring + CCPA SP) | Round 7 — net-new SP requires Round 1 supersession; Round 5 § 4.2 process_ccpa_deletion + § 6.3 + § 8.2 reference but don't assume signature |
| B82 | Propose new Phase 0 deliverable for ops-channel client (Slack / PagerDuty / email / SMTP) | Round 7 — new Phase 0 deliv + 02_PHASES.md amendment |
| B93 | SP-10 `@CutoffOverride DATETIME2(3) = NULL` parameter (operator-driven override) | Round 7 — SP signature change |
| B94 | SP-10 `@CategoryFilter NVARCHAR(MAX) = 'all'` parameter (SP-level filter) | Round 7 — SP signature change |

**Round 7 deferral count**: 6 items.

### § 9.4 Already closed at prior round (audit trail only)

| B-num | Canonical BACKLOG description | Where closed |
|---|---|---|
| B40 | Append F21/F22/F23 to `04_EDGE_CASES.md` F-series | CLOSED 2026-05-10 at Round 2 close-out (per BACKLOG L142) |
| B43 | Add R18 to RISKS.md (parity-baseline expires_at expiration) | CLOSED at Round 2 close-out (per BACKLOG Completed section) |
| B53 | Add R19 (Tier 0 drift) to RISKS.md | CLOSED at Round 3 close-out (per BACKLOG L143) |
| B54 | Appended I21/N11/P11 (concurrent-IN_PROGRESS / orphaned inflight Parquet / re-tokenize after vault purge) to `04_EDGE_CASES.md` | CLOSED 2026-05-10 (per BACKLOG L147 — cycle 2 R5C2 finding that initial draft mis-classified as Round 5 work; corrected) |
| B55 | Tier 0 backfill for Round 3 § 1 + § 2 modules (6 modules) | CLOSED 2026-05-10 (per BACKLOG L148 — initial Round 3 close-out deliverable; cycle 2 correction). Round 5 § 3.1 consolidates these into the canonical catalog, but the sketches themselves landed at Round 3 close-out |
| B56 | D-number cross-references in Round 3 § 1 + § 2 pre-shift D67/D68 → post-shift D68/D69 | CLOSED 2026-05-10 (per BACKLOG L149 — Round 3 close-out polish; cycle 2 correction) |
| B57 | Extend `udm-test-author` skill template for Tier 0 sketches alongside Tier 1 | CLOSED 2026-05-10 (per BACKLOG L150 — `.claude/skills/udm-test-author/SKILL.md` updated at Round 3 close-out; cycle 2 correction) |
| B58 | Tier 0 vs module-interface reconciliation script (drift detection per R19 mitigation) | CLOSED 2026-05-10 as INTERFACE STUB (per BACKLOG L151 — `tools/verify_tier0_drift.py` stub authored; full impl deferred to Round 6 per stub comment). Round 5 § 3.4 specifies the contract; Round 6 implements. **Partial-closure status** — keep tracked for Round 6 implementation |
| B59 | Round 3 first-pass closure tracker | CLOSED at Round 3 close-out (per BACKLOG L144) |
| B60 | Strengthen Pitfall #9 wording (four-round evidence) | CLOSED 2026-05-10 (per BACKLOG L152). Subsequently SUPERSEDED by HANDOFF §8 Pitfall #9 sub-class accumulator 2026-05-10 (B95 + B107 took it further with sub-classes 9.g + 9.h) |
| B61 | Round 3 second-pass clean-up (NVARCHAR(50)→(20)) | CLOSED 2026-05-10 (per BACKLOG L145) |
| B62 | Round 3 second-pass clean-up (NVARCHAR(40)→VARCHAR(40)) | CLOSED 2026-05-10 (per BACKLOG L146) |
| B73 | Mechanical column-by-column walk of Round 3 § 4-§ 7 against canonical DDL | CLOSED 2026-05-10 cycle 7 by Reviewer M — zero fresh lift instances; Pitfall #9 sub-class exhausted (per BACKLOG L66) |
| B92 | verify_server_parity signature server_name parameter | CLOSED in-cycle at Round 4 first-pass validation (per BACKLOG B92 entry) |

**Already-closed count**: 14 items (cycle 2 correction from 9 — added B54/B55/B56/B57/B58). These are listed for audit trail; Round 5 takes no action on them.

### § 9.5 Pre-Round-5 process-optimization phase 1 closures

Closed 2026-05-10 during process-optimization phase 1 (before Round 5 began):

| B-num | Canonical BACKLOG description | Where closed |
|---|---|---|
| B95 | Strengthen Pitfall #9 first sub-class wording to cover Python PEP 3102 `*,` keyword-only marker drift | CLOSED 2026-05-10 — HANDOFF §8 Pitfall #9 sub-class 9.g formalized |
| B107 | HANDOFF Pitfall #9 sixth sub-class addition: "wrong section number with invented section description" | CLOSED 2026-05-10 — HANDOFF §8 Pitfall #9 sub-class 9.h formalized |

**Process-optimization closure count**: 2 items.

### § 9.6 Still open and NOT triaged into Round 5/6/7 — explicit non-actions

Items in the B47-B107 range that are 🟡 Open but don't have a natural Round 5/6/7 placement under the D73+D78 carryover mandate:

| B-num | Canonical BACKLOG description | Why not in 9.1-9.3 |
|---|---|---|
| B33 | Author CCL audit-cadence checklist for quarterly review | Phase 6 (per BACKLOG L46) — quarterly cadence, not Round 5/6/7 phase scope |
| B36 | Tighten CCL verification rule to cover Bash-cat / WebFetch (D62 second-pass) | Phase 1 R3 follow-up (per BACKLOG L47) — predates Round 5; not blocking |
| B37 | Document explicit handling of simultaneous multi-Stage-1-doc edits (D62 second-pass) | Phase 1 R3 follow-up (per BACKLOG L48) — predates Round 5; not blocking |
| B38 | Author 30-day pre-expiry notification for parity-baseline `documented_exceptions` (R18) | Phase 1 R4 follow-up (per BACKLOG L70) — predates Round 5 but Round 4 didn't close; could be Round 6 if escalated |
| B39 | Capture first month of Snowflake trial cost data (Phase 0 deliv 0.6) | Phase 0 (per BACKLOG L71) — not in Round 5/6/7 scope |
| B41 | Author RB-12 in full per `udm-runbook-author` skill (after D64 locks) | Phase 1 R4 (per BACKLOG L73) — predates Round 5; could be deferred to Round 6 |
| B42 | After D63 locks, ensure `CK_UdmTablesList_SCD2Mode` exists via reconciliation query | Phase 0 / Phase 1 R6 deploy (per BACKLOG L74) — Round 6 dependency but not from D73/D78 carryover lists |
| B49 | Pin parity-baseline `expires_at` timezone to UTC across `documented_exceptions` | Phase 0 (per BACKLOG L78) — Phase 0 follow-up, not Round 5/6/7 |
| B64 | Correct D71 pillar mapping in `03_DECISIONS.md` — "$120K/year ceiling" → "Operationally stable" OR rewrite rationale | Round 3 deep-validation close-out polish (per BACKLOG L57) — could be Round 5 close-out polish; non-blocking |
| B74 | Optional re-sort BACKLOG main table to strict-monotonic-by-B-ID | Round 3 close-out polish (per BACKLOG L67) — non-load-bearing for downstream readers |
| B75 | Re-ground D64 framing ("industry-standard" → systemd-creds / GPG-on-TPM advisory) | Round 3-style framing polish (per BACKLOG L68) — non-blocking |
| B76 | Investigate D71 in-memory Snowflake key alternative (eliminates R20) | Round 4 / Round 5 dependency (per BACKLOG L69) — could be Round 6 if researched |
| B77 | Add R22 to RISKS.md (CLI exit-code drift) | **R22 already landed in RISKS.md L32 per Round 4 close-out** — cycle 2 verification confirmed. B77 BACKLOG entry just hasn't been moved to Completed yet. Round 5 close-out closes B77 entry via B119 |
| B103 | Round 3 § 2.2 internal contradiction (DecryptDenied vs returns None docstring) | Promoted to § 9.2 Round 6 work — see B103 row in § 9.2 |
| B104 | log_retention_cleanup --batch-size 50000 → 4000 (B-2 lock-escalation lesson) | Promoted to § 9.2 Round 6 work — see B104 row in § 9.2 |

**Cycle 2 fix corrections** to § 9 triage:
- **§ 9.1 demotions**: B54/B55/B56/B57 moved to § 9.4 already-closed (BACKLOG L147-150 confirmed); B100 + B102 moved to § 9.2 Round 6 work (wrong-doc-scope — fixes target Round 4/3 spec docs, not Round 5)
- **§ 9.2 promotions**: B69 + B100 + B102 added (B69 was previously claimed "promoted" but missing from list; B100 + B102 reclassified per wrong-doc-scope finding)
- **§ 9.4 additions**: B54/B55/B56/B57/B58 added (cycle 1 R5C2 caught false-closure mis-classifications)
- **§ 11.2 R22 narrative corrected**: R22 IS in RISKS.md L32 per Round 4 close-out; cycle 1 initial draft falsely claimed "never landed"
- **B119 rewritten**: close B77 BACKLOG entry (not "land R22 in RISKS.md" which is already done)
- **L87 D82 description corrected**: Tier 2 metric reframed from "≥80% pass rate" to "100% properties pass shrinkage within budget" (matches § 1.5 reframe)

### § 9.7 Triage summary (post-cycle-2 corrections)

| Category | Count | List |
|---|---|---|
| Round 5 closes (per § 9.1) | 9 | B47, B48, B50, B83, B84, B91, B98, B99, B105 |
| Round 6 deferral (per § 9.2) | 24 | B58, B63, B65, B66, B67, B68, B69, B70, B71, B72, B85, B86, B87, B88, B89, B90, B96, B97, B100, B101, B102, B103, B104, B106 |
| Round 7 deferral (per § 9.3) | 6 | B79, B80, B81, B82, B93, B94 |
| Already closed at prior round (per § 9.4) | 14 | B40, B43, B53, B54, B55, B56, B57, B58 (partial — stub closed; full impl Round 6), B59, B60, B61, B62, B73, B92 |
| Pre-Round-5 process-optimization phase 1 closures (per § 9.5) | 2 | B95, B107 |
| Open but outside D73+D78 carryover scope (per § 9.6) | 15 | B33, B36, B37, B38, B39, B41, B42, B49, B64, B74, B75, B76, B77 (→ Round 5 close-out B119), B103 (→Round 6, also listed § 9.2), B104 (→Round 6, also listed § 9.2) |
| **Total tracked** | **70** | covers B33+B36+B37 + B38-B43 + B47-B107 inclusive. Note 3 items double-listed for clarity: B58 (§ 9.4 stub + § 9.2 full-impl), B103 (§ 9.6 outside-scope + § 9.2 promoted-to-Round-6), B104 (same as B103). Unique count = 67 |

**Reconciliation note**: HANDOFF §3 / CURRENT_STATE / D78 acceptance text said "58 active items in B47-B107 minus B92 closed". Actual canonical count per BACKLOG.md B47-B107 active = 56 (B47-B107 is 61 IDs but B53/B73/B92 closed = 58 active; plus B59/B60/B61/B62 already-closed-at-prior-round = 54 active D73+D78-strict; plus B54/B55/B56/B57/B58 closed at Round 3 close-out = 49 active D73+D78-strict). The "58" figure was approximate; this rebuilt § 9 reconciles to actual canonical state. **B77 BACKLOG entry closure pending Round 5 close-out** (R22 already in RISKS.md per Round 4 close-out).

Round 5 close-out updates `BACKLOG.md` to reflect this triage: 9 closed in this round + 24 marked "Round 6 work" + 6 marked "Round 7 work" + carryover noted on remaining items.

---

## § 10. Edge case mapping (Gate 3 input)

Round 5 is the test-surface freeze that validates every edge case. Walk the M / S / I / N / P / G / D / F / V series:

### § 10.1 Series-by-series walk

| Series | Round 5 coverage | Specifics |
|---|---|---|
| **M** (math/lookback/lateness) | ✅ Tier 1 + Tier 2 | § 4.1 lateness_profiler tests; § 5.6 percentile monotonicity property |
| **S** (SCD2 reliability) | ✅ Tier 1 + Tier 3 + Tier 4 | Existing 06_TESTING.md Tier 3 scenarios + new C13 crash injection per § 7.2 |
| **I** (idempotency) | ✅ Tier 2 (master property) + Tier 4 | § 5.1 master idempotence property; § 7 crash injection convergence tests |
| **N** (network drive / Parquet) | ✅ Tier 1 + Tier 4 | § 4.1 parquet_writer / parquet_replay / parquet_registry_client tests; C2/C3 crash injection |
| **P** (PII / encryption) | ✅ Tier 1 + Tier 5 | § 4.1 pii_tokenizer / pii_decryptor tests; § 8 Q6 + Q9 audit drills |
| **G** (gap detection / outage recovery) | ✅ Tier 1 + Tier 3 | § 4.1 gap_detector tests; § 6.4 cross-tool integration |
| **D** (2x/day cadence) | ✅ Tier 3 | § 6.3 promote_test_to_prod failover end-to-end |
| **F** (failover / cross-server parity) | ✅ Tier 1 + Tier 3 + Tier 4 | § 4.2 verify_server_parity + promote_test_to_prod tests; C13 crash injection; **F25 PROPOSED per B98** (alert dispatcher zero-channels-fatal escalation — Tier 1 + Tier 3 coverage in § 4.2 alert_dispatcher) — F25 to be appended to `04_EDGE_CASES.md` at Round 5 close-out paired with B108 task |
| **V** (vault provenance) | ✅ Tier 1 + Tier 5 | § 4.1 pii_tokenizer provenance tests; § 5.8 UNIQUE constraint property; Q9 CCPA audit drill |

### § 10.2 New edge cases surfaced by Round 5 test planning

| Proposed | Description | Mitigation in Round 5 |
|---|---|---|
| T1 (test-series) | Tier 0 smoke test drift — sketch updated in source spec but `tests/smoke/test_<X>.py` not refreshed; CI passes stale test that no longer matches contract | § 3.4 verify_tier0_drift.py (B58 — Round 6 implements) + Q7 quarterly audit drill |
| T2 | Tier 2 property test hits Hypothesis shrinkage budget — example fails reduction; "false" failure that's actually a real bug masked by shrinkage timeout | § 5.10 budget per module; deadline=10s; pre-release bumps to max_examples=5000 |
| T3 | Tier 3 integration test produces flake (intermittent failure on Docker SQL Server fixture warmup) — false-positive failure rate impacts CI signal | § 1.5 coverage target: ≥95% scenario pass rate per nightly; investigate >5%; flake detection via test_<name>_flaky retry |

**Close-out task**: append T1-T3 to `04_EDGE_CASES.md` Test-series under new T-prefix (or merge into existing series if applicable). Tracked as B108 below.

---

## § 11. Validation gates (Round 5 producer self-check)

Per D55 + D62, this is the producer self-check before invoking Pattern E Gate 2 review. Per the **Gate 5 label correction (B100)**: Gate 5 self-check covers idempotency / regression + D61 risk-delta + Backlog surfacing.

### § 11.1 Gate 1 self-check — Cross-reference

Per § 2 above, every Round 1 / Round 2 / Round 3 / Round 4 reference walked against canonical per Pitfall #9 a-h. ✅

### § 11.2 Gate 5 self-check — Idempotency + Risk delta + Backlog (per D61 + B100 corrected label)

**Idempotency / regression** (the actual Gate 5 surface per D55):
- D15 invariant: § 5.1 master property test covers every transformation
- D17 ledger pattern: § 4.1 idempotency_ledger tests + § 5.5 status-machine state graph
- D26 append-only: § 5.8 UNIQUE constraint property + § 6 integration audit trail verification
- No locked decision (D55-D78) contradicted by Round 5 test plan

**Risks introduced / addressed** (per D61):

```
RISKS (per D61):
- ⬇️ DE-ESCALATED (pending substantiation): R19 (Tier 0 drift) — Round 5 § 3 catalog
  + § 3.4 verify_tier0_drift.py spec address the drift surface. Hedge per Pitfall #8:
  do NOT reduce R19 score until first ~5 Tier 0 smoke tests are actually authored
  AND verify_tier0_drift.py is operational.

- ⬇️ DE-ESCALATED (pending): R23 (Round 4 BACKLOG carryover) — Round 5 § 9 triage
  closes 15 items in-round; remaining items have clear Round 6/7 placement. Hedge:
  do NOT reduce R23 score until Round 6 close-out confirms the 21 Round-6-deferral
  items are picked up.

- ◎ UNCHANGED: R22 (CLI exit-code drift) — R22 already landed in RISKS.md L32 at Round 4
  close-out (per Round 4 § 5.4 acceptance criteria + Round 4 close-out _validation_log entry).
  Cycle 1 R5C1-2 noted R22 mentioned in § 0 L17 but absent from § 11.2 risk-delta block;
  cycle 2 R5C2 verified R22 IS in RISKS.md canonical. The remaining work is closing
  BACKLOG B77 entry (still 🟡 Open per BACKLOG L158) — tracked via B119 below at Round 5
  close-out. Status: unchanged this round; B77 closure pending at close-out.

- 🆕 NEW PROPOSAL: R24 — Test-fixture canonical schema drift. Likelihood Medium ×
  Impact Low = 2 ⚪. When Round 1 schema evolves (via Round 7 governance), the test
  fixture must be regenerated. If forgotten, Tier 3 + 4 tests pass against stale
  fixture while production schema has drifted. Mitigation: D79 proposed — fixture
  schema mirrors Round 1 DDL; refresh required at every Round 1 change; Round 7
  governance procedure includes fixture-regenerate step.
  Status: NOT YET ADDED to RISKS.md — close-out task per Pitfall #8.
```

**Backlog proposals** (per D61 — current max in BACKLOG.md after Round 4 close-out is **B107**; NEXT_AVAILABLE = **B108**):

```
BACKLOG (per D61):
- 🟡 B108: Append T1-T3 (test-series edge cases) + F25 (alert dispatcher zero-channels-fatal
       per B98) + I-next per B48 to 04_EDGE_CASES.md at Round 5 close-out. COD 2, JS 1, WSJF=2.0
- 🟡 B109: Add R24 to RISKS.md (test-fixture canonical schema drift) at Round 5
       close-out per Pitfall #8 discipline. COD 2, JS 1, WSJF=2.0
- 🟡 B110: D79 (test data fixture canonical schema) needs lockdown via decision
       recording at Round 5 close-out. COD 1, JS 1, WSJF=1.0
- 🟡 B111: D80 (Tier-0-to-Tier-1 transition discipline) needs lockdown via decision
       recording at Round 5 close-out. COD 1, JS 1, WSJF=1.0
- 🟡 B112: D81 (Property-test shrinkage budget per module) needs lockdown. WSJF=1.0
- 🟡 B113: D82 (Coverage thresholds per tier) needs lockdown. WSJF=1.0
- 🟡 B114: D82 Tier 2 coverage metric reframed from "≥80% pass rate" to "100% properties
       pass shrinkage within budget" per R5C1-5 advisory finding (Hypothesis is pass-or-fail
       per shrinkage, not stochastic). Already applied inline at § 1.5; B114 tracks the
       decision-record landing at Round 5 close-out. COD 2, JS 1, WSJF=2.0
- 🟡 B115: Add fixture state-leakage mitigation to § 1.3 (SQLAlchemy-style transactional
       rollback per Tier 3 test; Tier 4 non-rollback with custom cleanup). Already applied
       inline at § 1.3; B115 tracks the corresponding test fixture authoring at Round 6.
       COD 2, JS 1, WSJF=2.0
- 🟡 B116: Cite testcontainers-python + canonical `mcr.microsoft.com/mssql/server:2022-CU14-ubuntu-22.04`
       (version-pinned per R6 § 7.10 / § 4.5 / § 5.4 / § 8.10 — `:latest` invites parity-drift class
       flagged by R5C1-5 advisory + R6C4 sleeper-bug) image in D79 + § 1.3. Already applied inline;
       B116 tracks the decision-record landing. **Closed at Round 6 retrospective 2026-05-11**
       (Pattern F Layer 2 INSTANCE 1 surfaced second-order B140 false-closure at this exact location
       — proposal-log occurrence was missed at original B140 cleanup; corrected here).
       COD 1, JS 1, WSJF=1.0
- 🟡 B117: Optional — cite Microsoft BVT (Build Verification Test) and Google small-test
       vocabulary in § 1.6 Tier-0-vs-Tier-1 boundary discipline (R5C1-5 advisory). Low priority.
       COD 1, JS 1, WSJF=0.5
- 🟡 B118: Specify Hypothesis `derandomize=True` CI profile in `tests/conftest.py` per § 5.10
       (R5C1-5 advisory — prevents non-reproducible CI failures). Already applied inline;
       B118 tracks fixture authoring at Round 6. COD 1, JS 1, WSJF=1.0
- 🟡 B119: Close BACKLOG entry B77 at Round 5 close-out (move to Completed section).
       R22 already in RISKS.md L32 per Round 4 close-out (cycle 2 R5C2 verified canonical
       state); B77 just hasn't been moved to BACKLOG Completed section yet. Cycle 1 R5C1-2
       initially flagged a gap that was actually a closure-state-not-updated issue, not a
       risk-not-landed issue. Cycle 2 corrected the framing. COD 1, JS 1, WSJF=1.0
```

**Sources** (per R5C1-5 cycle 1 advisory):
- Hypothesis docs on `settings` profile + `derandomize` parameter
- pandas, SQLAlchemy, numpy test-suite Hypothesis settings precedent
- Martin Fowler "Practical Test Pyramid" (Tier 0/1 boundary)
- Google Testing Blog "Just Say No to More E2E Tests" (Tier 3 flake budget)
- Microsoft Learn mssql Docker quickstart + testcontainers-python mssql module
- Google SRE Book monitoring chapter (coverage threshold conventions)

### § 11.3 Gate 2 — Independent review (NEXT STEP after this self-check)

**Per `_reviewer_effectiveness.md` empirical evidence + Pattern E proven on Round 4 cycle 4**: invoke Pattern E from cycle 1 with 5 parallel agents:

1. **R5C1-1**: column-walk specialist (Pitfall #9 a-h surface — 17 Round 3 modules + 11 Round 4 tools + 28 Tier 0 sketches + Tier 1/2/3 references)
2. **R5C1-2**: cross-reference / Pitfall #9 sweep (B47-B107 triage accuracy; D-numbers; cross-doc links to 06_TESTING.md / 03_core_modules.md / 04_tools.md)
3. **R5C1-3**: internal consistency (test plan coherence; tier-to-tier boundary respect per D80; § 9 triage internal consistency)
4. **R5C1-4**: D72 convergence + edge case coverage (Gate 3 + Gate 4 — every edge case has ≥1 test; § 10 walk completeness)
5. **R5C1-5**: advisory researcher (testing-framework best practices — pytest fixture scoping; Hypothesis shrinkage strategies; SQL Server Docker fixture conventions)

Then **sleeper-bug stress test cycle** per R4C8 precedent (mandatory final cycle before D73/D78-style architectural acceptance).

### § 11.4 Round 5 acceptance criteria checklist (run at close-out)

- [ ] Intro through § 12 all present and self-consistent
- [ ] D79-D82 captured in `03_DECISIONS.md` (test fixture schema + Tier-0-to-1 boundary + property budget + coverage thresholds)
- [ ] Pattern E cycle 1 returned ≤4 🔴 (or single comprehensive returned 0 — per `_reviewer_effectiveness.md` evidence, expect Pattern E to surface bugs single-agent would miss)
- [ ] Sleeper-bug stress test cycle complete (mandatory final cycle per R4C8 precedent)
- [ ] `_validation_log.md` entry appended documenting all validation passes
- [ ] `_reviewer_effectiveness.md` updated with Round 5 cycle entries per ledger schema
- [ ] Cross-doc updates landed: 04_EDGE_CASES.md (B108 — T1-T3 + F25 proposed), CLAUDE.md (CLI_* EventType family per B86), 06_TESTING.md (already updated 2026-05-10 with the 6-tier pyramid including the new Tier 0 section)
- [ ] BACKLOG.md updated with B108-B119 (12 proposed) + close 9 items per § 9.1 + reclassify 24 items per § 9.2 (Round 6 work; includes B103/B104 also listed in § 9.6) + reclassify 6 items per § 9.3 (Round 7 work) + audit-trail 14 already-closed items per § 9.4 (B58 partial — stub closed, full impl Round 6) + 2 process-optimization closures per § 9.5 + 15 outside-scope items per § 9.6 (3 of which double-listed with § 9.2/§ 9.4 per § 9.7 reconciliation note; unique total 67)
- [ ] RISKS.md updated with R24 (per B109)
- [ ] HANDOFF.md §3 + §12 + §14 updated via `udm-round-closeout`
- [ ] CURRENT_STATE.md "Recently completed" + "Recent rounds" + "Last updated" + "Next concrete step" (→ Round 6 Deployment) updated
- [ ] NORTH_STAR.md Phase 1 row already shows pillars (no change expected — Round 5 advances **Audit-grade** + **Operationally stable** + **Idempotent** as expected)
- [ ] Doc status flip: `phase1/05_tests.md` "🟡 Drafting" → "🟢 Locked" (after validation passes; D73/D78-style architectural-review acceptance if D72 math infeasible)

---

## § 12. End of Round 5 — Tests

**Status when this checklist completes**: 🟢 Locked, ready for Round 6 (Deployment) to implement test bodies + Tier 0 backfill + CI pipeline; Round 7 (Schema Evolution Governance) to handle SP signature changes; Round 8 (Sub-Agent Self-Improvement Discipline) to consume Round 5's `_reviewer_effectiveness.md` updates.

**Round 5 distinctive outputs**:
- 6-tier test pyramid instantiated per-artifact (28 modules + tools × 6 tiers)
- Tier 0 backfill catalog (B55 closed at Round 3; B83 closed via this round § 3.2 catalog)
- Tier 1/2/3/4/5 test plans authored
- **67 unique BACKLOG items triaged** post-cycle-3 corrections (70 tracked with 3 intentional double-listings — B58 stub/full-impl, B103 + B104 promoted to Round 6 but originally outside-scope): 9 closed in-round (§ 9.1); 24 Round 6 work (§ 9.2); 6 Round 7 work (§ 9.3); 14 already-closed at prior round audit-trail (§ 9.4); 2 process-optimization closures (§ 9.5); 15 outside D73+D78 scope (§ 9.6). The initial cycle-1 draft mis-classified 6 items (B54-B57 false-as-Round-5-close + B100/B102 wrong-doc-scope); R5C2 cycle 2 reviewer caught the Pitfall #9 fix-introduces-fresh-instance pattern recurrence (8th-round evidence) and the fixes were re-applied per cycle 2. Cycle 3 R5C3 reviewer caught a count-math drift introduced by cycle 2 (§ 9.7 stated "11 outside-scope" but list contained 15); cycle 3 fix updated count to match.
- 4 new decisions proposed (D79-D82 test framework discipline)
- 1 new risk proposed (R24 fixture schema drift)
- 12 new BACKLOG items proposed (B108-B119 — initial 6 from cycle-1 draft + 6 from cycle-1 R5C1-5 advisory researcher findings)
