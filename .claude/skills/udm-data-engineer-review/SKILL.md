---
name: udm-data-engineer-review
description: Reviews CDC / SCD2 / Polars / Parquet / BCP / SQL Server design choices against industry-standard patterns. Use when reviewing schema, stored procedures, Python modules touching CDC/SCD2 logic, Parquet write/read code, or windowed extraction. Catches non-idiomatic patterns and bugs that pure correctness review misses.
---

# UDM Data Engineering Review

Use this skill on artifacts that touch CDC, SCD2, Parquet, Polars, BCP, or windowed extraction. The review checks against established data engineering patterns specific to our stack.

## When to use

- Reviewing a schema doc (`phase1/01_database_schema.md`) before DBA review
- Reviewing a Python module that implements `cdc/`, `scd2/`, `data_load/`, `extract/`
- Reviewing a stored procedure that touches `PiiVault`, `PipelineExecutionGate`, `IdempotencyLedger`
- Reviewing a runbook that involves windowed extraction or hash-based change detection
- Before locking a decision (D-number) related to data pipeline mechanics

## Canonical Context Load (CCL) — required before invoking this skill (per D62)

Whoever invokes this skill (main agent or subagent) MUST have performed the Canonical Context Load (per `docs/migration/MULTI_AGENT_GUIDE.md` § Canonical Context Load) before applying this skill's discipline.

- **Stage 0 — Routing manifest** (recommended-not-mandatory; added 2026-05-15 per D62 amendment + D.2 INDEX.md per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.3): `docs/migration/INDEX.md` — read FIRST when uncertain which downstream Stage 1+2+3 docs your task actually needs. Skip when: you already know which Stage 1+2+3 docs to load (typical for recurring task patterns).
- **Stage 1 — Orientation** (mandatory, 4 reads): `NORTH_STAR.md`, `HANDOFF.md`, `CURRENT_STATE.md`, `CHECKS_AND_BALANCES.md`
- **Stage 2 — Risk + Backlog awareness** (mandatory): `RISKS.md`, `BACKLOG.md`, `_validation_log.md`
- **Stage 3 — Task-specific reads for this skill**: `CLAUDE.md` (project root — Do-NOT rules + technical history); `01_ARCHITECTURE.md` (current architecture); the artifact under review
- **Stage 4 — Reference-on-demand**: grep `03_DECISIONS.md` for D-numbers (especially D6, D15, D16, D17, P0-* / B-1 / E-* gotchas), `04_EDGE_CASES.md` for series IDs

If invoked from a subagent context, the subagent's CCL responsibility is hard-required (per agent definition — first `Read` must hit a Stage 1 doc).

## Review checklist (walk all relevant items)

### Polars + hash determinism

- [ ] Hash computation uses polars-hash plugin (deterministic across sessions per P2-1)
- [ ] No native `hash_rows()` calls
- [ ] Categorical columns cast to Utf8 before hashing (E-20)
- [ ] Float NaN/inf normalization in hash inputs (W-3)
- [ ] String RTRIM before hashing (E-4)
- [ ] Oracle empty-string normalization for Oracle sources (E-1)

### BCP + CSV contract

- [ ] write_csv uses `quote_style='never'` (BCP CSV Contract)
- [ ] BIT columns cast to Int8 (0/1, not True/False)
- [ ] String sanitization removes \t \n \r \x00 before write (B-6 extends to extended Unicode)
- [ ] Datetime format `'%Y-%m-%d %H:%M:%S.%3f'` (millisecond precision per SCD2-P1-f)
- [ ] batch_size=4096 to prevent memory spikes
- [ ] Column reorder via `reorder_columns_for_bcp` (P0-1) before write

### SCD2 invariants

- [ ] Bronze writes are append-only (never TRUNCATE)
- [ ] `_scd2_key` excluded from INSERT DataFrames
- [ ] Hash compare conditional on equality (no unconditional UPDATE)
- [ ] INSERT-first crash safety pattern (E-2)
- [ ] B-4 orphan cleanup invoked at SCD2 entry
- [ ] `UdmActiveFlag` semantic preserved: 0=historic, 1=active, 2=deleted-at-source (R-4)
- [ ] Resurrection captured as Op='R' (E-18)
- [ ] Dual date pair preserved: load-time (UdmEffectiveDateTime/UdmEndDateTime) vs source-date (UdmSourceBeginDate/UdmSourceEndDate) (SCD2-P1-a)

### Idempotency

- [ ] Every side-effecting operation gates on idempotency ledger (D17)
- [ ] Stage-check-exchange for crash-safe writes (D16)
- [ ] Hash compare returns no-op when source unchanged
- [ ] sp_getapplock on (source, table) for concurrent prevention
- [ ] startup recovery sweep for stale IN_PROGRESS rows (I19)

### Parquet specifics

- [ ] File size 100-250 MB target (D45.2; Snowflake-recommended)
- [ ] Compression: ZSTD level 3 for archive
- [ ] Sort order: (PK ASC, _extracted_at DESC)
- [ ] Hive-style partition path (year=YYYY/month=MM/day=DD/)
- [ ] Statistics enabled (MIN/MAX/NULL_COUNT/DISTINCT_COUNT)
- [ ] Inflight-rename pattern (write to _inflight, atomic rename, register)

### Windowed extraction (large tables)

- [ ] TRUNC date boundaries (P3-2 timezone safety)
- [ ] Per-day extraction (memory bounded per P2-4)
- [ ] LookbackDays from per-table config, not global (D11)
- [ ] PipelineExtraction trust gate for delete detection (D13)
- [ ] IsReExtraction flag set on re-extracted dates (D14)

### NULL / dtype gotchas

- [ ] NULL PK filter at extraction (P0-4)
- [ ] PK dtype alignment before joins (P0-12)
- [ ] UInt64 → Int64 reinterpret for non-hash columns
- [ ] Schema validation before pl.concat (W-7)

### Concurrency

- [ ] No lookup-then-INSERT patterns without MERGE WITH (HOLDLOCK) or catch-and-relookup
- [ ] sp_getapplock at table boundary
- [ ] No assumption of ordering between pipeline runs

### SQL naming standards (D105 — MANDATORY for new objects only; pre-D105 names grandfathered per D92)

- [ ] Any NEW stored procedure DB object name follows `General.{schema}.Proc{ProcedureName}` (PascalCase after the `Proc` prefix; no schema repetition inside the object name)
- [ ] Any NEW stored procedure file name follows `{schema}_Proc{ProcedureName}.sql`
- [ ] Any NEW view DB object name follows `General.{schema}.Vw{ViewName}`
- [ ] Any NEW view file name follows `{schema}_Vw{ViewName}.sql`
- [ ] Pre-D105 SP/view names cited from existing code (e.g. `PiiVault_GetOrCreateToken`, `PiiVault_DecryptForOperator`) are NOT renamed — grandfather clause per D92 forward-only
- [ ] Flag any draft proposing a new non-conformant name; do NOT flag pre-D105 names cited unchanged

### Security model (D103)

- [ ] No credential paths inside `/debi` (`.env`, `*.gpg`, `*.pem`, `*.key`, `credentials.json` should NEVER appear in the project directory)
- [ ] Any NEW credential path (added by the artifact under review) is also added to `.claudeignore` (documentation layer) AND `.claude/settings.local.json` `permissions.deny` (enforcement layer)
- [ ] Any code reading `.env` reads from `/etc/pipeline/.env` (canonical per D103); legacy `/debi/.env` reads are flagged for migration via B182
- [ ] `PiiVault.EncryptedPlaintext` uses AES-256-GCM wire format `nonce (12 bytes) || ciphertext || auth_tag (16 bytes)` per D102; no other algorithm without superseding D102
- [ ] Snowflake RSA private key handling per D71 (`/dev/shm/snowflake_pk_<pid>` mode 0600; `release_snowflake_key()` cleanup post-session)
- [ ] No code path attempts to bypass `.claude/settings.local.json` `permissions.deny` rules (Bash + PowerShell + Read tool calls against credential paths are denied; if an operation legitimately needs credential access, it runs OUTSIDE Claude)

## Output structure

```
ARTIFACT: <path>
SUMMARY: <one-sentence verdict — looks good / needs corrections / has bugs>

FINDINGS:

✅ Correctly implemented:
- <list of patterns the artifact handles right>

🟡 Concerns:
- <patterns that work but could be more robust>

🔴 Bugs / non-idiomatic patterns:
- <specific issue + fix recommendation + edge case ID>

⚪ Not applicable:
- <patterns that don't apply, with reason>

ACTION ITEMS:
1. <specific change to artifact>
2. <test to add (Tier 1/2/3)>
3. <decision to record (D-number)>
```

## Anti-patterns to flag

- ❌ Lookup-then-INSERT without atomicity guard (race condition class)
- ❌ Hash compare that doesn't normalize source-specific quirks (Oracle empty string, trailing whitespace)
- ❌ Bronze writes outside SCD2 promotion path
- ❌ Stage table reads outside `read_stage_table()` helper
- ❌ Direct datetime comparison without millisecond truncation (SCD2-P1-f)
- ❌ Polars `concat()` with `how='diagonal'` without W-7 schema validation
- ❌ Logging plaintext PII anywhere (P5)
- ❌ MERGE without conditional WHEN MATCHED on hash (Bronze re-versioning storm)

## When NOT to use

- Don't use for pure Python style review (use built-in `/review`)
- Don't use for security-only review (use built-in `/security-review`)
- Don't use for non-CDC code (e.g. UI, reporting)

## Concrete example

Reviewing SP-1 (`PiiVault_GetOrCreateToken`) in `phase1/01_database_schema.md`:

🔴 Bug: lookup-then-INSERT race condition. Two callers with same plaintext both miss SELECT, both INSERT, second violates UNIQUE.
🔴 Anti-pattern: catch on UNIQUE violation is missing — SP-7 has it for IdempotencyLedger but SP-1 doesn't.
✅ Correctly implemented: deterministic via PlaintextHash lookup; per-source isolation via SourceName in lookup index.
ACTION: rewrite as MERGE WITH (HOLDLOCK) or replicate SP-7 try/catch-then-relookup pattern. Add I3 to schema doc edge-case mapping.
