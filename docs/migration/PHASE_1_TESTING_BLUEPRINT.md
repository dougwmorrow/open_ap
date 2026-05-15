# Phase 1 Testing Blueprint

**Purpose**: Step-by-step validation sequence from PR creation through production-bug root-cause + fix verification.

**Audience**: Pipeline operator running tests on their own environment.

**Branch state at time of authoring**: `phase-1-round-3-build-campaign` @ commit `6eae9fb` (16 commits ahead of `master`).

**Estimated total time**: 30-60 minutes if everything passes; longer if production-bug Phase 2 requires repair action.

**How to use this doc**: Work through phases in order. Each phase has an explicit success criterion. Each command has expected output. Each failure mode has a "what to do next" pointer. Save the diagnostic output from Phase 2 — that's the thing to bring back to the chat session for analysis.

---

## Phase 0 — Pre-PR local verification (5 minutes)

Run these BEFORE creating the PR. Catches anything obviously broken.

### 0.1 Branch state

```powershell
git status
git log --oneline master..HEAD | Measure-Object | Select-Object -ExpandProperty Count
```

**Expected**: working tree clean; **16** commits on branch.

**If different**:
- Uncommitted changes → decide whether to commit, stash, or discard before proceeding
- Different commit count → check `git log master..HEAD` for unexpected commits

### 0.2 Full pytest suite

```powershell
.venv\Scripts\python.exe -m pytest tests/tier0 tests/tier1 tests/unit tests/property tests/regression -q --no-header
```

**Expected output (last line)**:
```
2 failed, 2281 passed, 10 skipped in ~50s
```

The 2 failures are the **pre-existing B218 carryover** in `test_log_retention_cleanup.py` (config-missing case in unrelated tool). NOT introduced by this session.

**If you see more than 2 failures OR new failure files**: stop and investigate before proceeding to PR. Run a single failing test verbosely:

```powershell
.venv\Scripts\python.exe -m pytest tests/path/to/test_file.py::test_name -xvs
```

### 0.3 Sanity-check the 3 new tools import cleanly

```powershell
.venv\Scripts\python.exe -c "import tools.snowflake_copy_smoke; import tools.scd2_replay_smoke; import tools.diagnose_stage_bronze_gap; print('OK')"
```

**Expected**: `OK`

**If ImportError**: missing dependency in `.venv`. Run `uv pip install -r requirements.txt` (or whatever the project's install command is) and retry.

### 0.4 `--help` works for each tool

```powershell
.venv\Scripts\python.exe -m tools.snowflake_copy_smoke --help
.venv\Scripts\python.exe -m tools.scd2_replay_smoke --help
.venv\Scripts\python.exe -m tools.diagnose_stage_bronze_gap --help
```

**Expected**: each prints argparse usage with all flags documented. Confirms argparse wired correctly + no top-level import side-effects at CLI invocation.

### Phase 0 success criterion

- ✅ Working tree clean
- ✅ 2281 pass / 10 skip / 2 fail (B218 carryover only)
- ✅ 3 new tools import + `--help` works

**You're ready to create the PR.**

---

## Phase 1 — Create the PR (5 minutes)

### 1.1 Push branch to remote (already done if you've been pushing this session)

```powershell
git push origin phase-1-round-3-build-campaign
```

Branch is already at `origin/phase-1-round-3-build-campaign` @ `6eae9fb` per session history.

### 1.2 Create PR

The session's been pushing to `dougwmorrow/open_ap`. PR URL pattern:

```
https://github.com/dougwmorrow/open_ap/pull/new/phase-1-round-3-build-campaign
```

### 1.3 Recommended PR title

```
Phase 1 Round 6 follow-up: 3-tool cohort + Round 3 build campaign + B-N closure cycle
```

### 1.4 Recommended PR body

```markdown
## Summary

Phase 1 implementation campaign: ~85% complete after this PR. 16 commits land:

- **Round 3 build campaign** (17 M-modules; 1,063 tests)
- **Round 4 build campaign** (9/11 tools BUILT; 2 blocked on B81 SP-12 + B82 ops-channel)
- **Round 6 partial** (Tier 2 property tests; 53 properties + 1 production bug surfaced + fixed)
- **Round 6 follow-up** (3 user-facing tools: Snowflake smoke + SCD2-from-Parquet smoke + Stage/Bronze diagnostic)

**Pytest baseline**: 395 → 2281 pass (+1886) / 10 skip / 2 fail (B218 carryover; 0 net regression introduced).

**Production bug diagnostic infrastructure shipped**: `tools/diagnose_stage_bronze_gap.py` classifies PKs in Stage CDC but missing from Bronze SCD2 into 5 theory categories (IN_FLIGHT_ORPHAN / DELETED_FROM_SOURCE / NEVER_INSERTED / ALL_CLOSED / RESURRECTED_AS_INACTIVE) with per-theory operational recommendations.

## Test plan

See `docs/migration/PHASE_1_TESTING_BLUEPRINT.md` for the full operator validation sequence:

- Phase 0: pre-PR local verification (pytest 2281 pass)
- Phase 2: Diagnose the production CDC/SCD2 bug (read-only)
- Phase 3: Snowflake smoke against trial credentials
- Phase 4: SCD2-from-Parquet smoke
- Phase 5: Per-theory repair actions (if Phase 2 surfaces non-empty gap)

## Notes for reviewer

- All 3 new tools are READ-ONLY by default (`--dry-run` default per D75; require `--apply` for any mutations)
- Diagnostic tool is READ-ONLY in all modes (only write is the PipelineEventLog audit row per D76)
- Step 10 producer-discipline (CLAUDE.md Structure + GLOSSARY registration) applied for all 3 tools
- 16 commits intentionally NOT squashed — each commit is a discrete logical unit per session-established discipline

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

### 1.5 Squash vs merge?

**Recommendation: regular merge (NOT squash)**. Each commit is a discrete logical unit per the session-established discipline (build → gap-check → fix → commit pattern). Squashing collapses the audit trail.

**If your repo policy requires squash**: use squash but extract the per-commit messages into the PR body for trail preservation.

### Phase 1 success criterion

- ✅ PR created with title/body
- ✅ PR shows 16 commits / branch `phase-1-round-3-build-campaign`
- ✅ No merge conflicts with `master`

---

## Phase 2 — Diagnose the CDC/SCD2 production bug (15-30 minutes)

This is the load-bearing test for your production bug ("UDM_Bronze SCD2 tables have a few primary keys that are not showing there, but they show in UDM_Stage CDC layer").

**The diagnostic is READ-ONLY**. Safe to run anytime — only writes a single audit row to `General.ops.PipelineEventLog`. No mutations to Stage / Bronze / source.

### 2.1 Run diagnostic against the affected table

Replace `DNA` / `ACCT` with the source/table where you observe the bug. If unknown, start with your largest-volume table.

```bash
python -m tools.diagnose_stage_bronze_gap --source DNA --table ACCT --include-state
```

**Expected output shape**:

```
========================================
Stage→Bronze Gap Diagnostic
========================================
Source: DNA
Table:  ACCT
PK columns: AcctNumber, AcctType
Stage current rows (cdc_is_current=1): 1,234,567
Bronze active rows (Flag=1):           1,234,562
---
GAP: 5 PKs in Stage but NOT in Bronze

  PK={AcctNumber=12345, AcctType=CK} → IN_FLIGHT_ORPHAN
     Bronze _scd2_key=98765, UdmEffectiveDateTime=2026-05-13 14:32:18.123
     Recommend: tools/repair_scd2.py --source DNA --table ACCT --apply

  PK={AcctNumber=12346, AcctType=SV} → NEVER_INSERTED
     No Bronze row found.
     Recommend: tools/inspect_cdc_pk.py --source DNA --table ACCT --pk-values 12346,SV

  ... (up to --limit)

Summary by theory:
  IN_FLIGHT_ORPHAN:       2 (40%)
  NEVER_INSERTED:         1 (20%)
  DELETED_FROM_SOURCE:    2 (40%)
```

### 2.2 Save the output

```bash
python -m tools.diagnose_stage_bronze_gap --source DNA --table ACCT --include-state \
  --output-file diagnostic_DNA_ACCT_$(date +%Y-%m-%d).txt
```

This produces a file you can paste back into the chat session for analysis.

### 2.3 Interpret by exit code

| Exit code | Meaning | What to do |
|---|---|---|
| **0** (SUCCESS) | No gap found — Stage current PKs == Bronze active PKs | 🎉 No production bug. Your perception may have been transient (mid-pipeline state). Re-run later if recurrence. |
| **1** (OPERATIONAL) | Gap found | Go to **Phase 2.4** (theory decision tree) |
| **2** (FATAL) | Config error — PK columns unresolvable, table not in UdmTablesList, etc. | Check `General.dbo.UdmTablesColumnsList` for the source/table row; verify `IsPrimaryKey=1` is set on at least one column for `Layer='Stage'` |

### 2.4 Theory decision tree

Pick the theory category that matches MOST of your gap entries:

#### Theory T1 — IN_FLIGHT_ORPHAN (mid-INSERT crash)

**What it means**: SCD2 INSERT-first pattern crashed between Bronze INSERT (with `UdmActiveFlag=0`) and `_activate_new_versions()` (flip to `Flag=1`). The row exists but is invisible to downstream consumers who filter `WHERE UdmActiveFlag=1`.

**Predicate**: Bronze row exists with `UdmActiveFlag=0 AND UdmEndDateTime IS NULL AND UdmSourceEndDate IS NULL AND UdmScd2Operation IN ('U','R')`.

**Recommended action — repair**:

```bash
# Dry-run first
python -m tools.repair_scd2 --source DNA --table ACCT --orphan-cleanup --dry-run

# If dry-run output looks right
python -m tools.repair_scd2 --source DNA --table ACCT --orphan-cleanup --apply
```

The repair tool deletes orphan Flag=0 rows OR activates them depending on the safer choice per `tools/repair_scd2.py` logic. See CLAUDE.md SCD2-R6 for the full repair-scope contract.

**Then verify**:
```bash
python -m tools.diagnose_stage_bronze_gap --source DNA --table ACCT
```
Should return exit 0 (HEALTHY) for the orphan PKs.

#### Theory T2 — DELETED_FROM_SOURCE (Flag=2 already captured)

**What it means**: Bronze has `UdmActiveFlag=2` rows for these PKs, meaning the SCD2 layer already knows they were deleted from source. But Stage still shows `_cdc_is_current=1` for the same PK — that's INCONSISTENT.

**Most likely cause**: CDC source-verifier flap. The source-verifier at `cdc/source_verifier.py` (Phase 2 of cdc_root_cause_blueprint.md) flips `_cdc_is_current` to 0 when source confirms the row is gone. If the verifier had a transient network failure, it may have flapped back.

**Recommended action — investigate**:

1. Check the verifier strict mode:
   ```bash
   # In env file or shell
   echo $env:CDC_VERIFY_STRICT_ON_FAILURE
   # Should be "1" (strict). If "0" or unset, the verifier silently treats failures as "row still exists" which is the wrong default.
   ```

2. Check the source: does the row ACTUALLY still exist in DNA.osibank.ACCT for that PK?
   ```sql
   SELECT * FROM DNA.osibank.ACCT WHERE AcctNumber=12345 AND AcctType='CK';
   ```
   - If row EXISTS in source: Bronze Flag=2 is wrong; manual fix needed (or wait for next CDC pass which should re-detect)
   - If row does NOT exist in source: Stage `_cdc_is_current=1` is stale; CDC should have flipped it. Next pipeline run should catch it.

3. Check `PipelineLog` for `cdc.source_verifier` entries around the affected BatchId:
   ```sql
   SELECT TOP 50 CreatedAt, LogLevel, Message, ErrorMessage
   FROM General.ops.PipelineLog
   WHERE Module = 'cdc.source_verifier'
     AND TableName = 'ACCT'
     AND CreatedAt > DATEADD(day, -7, GETDATE())
   ORDER BY CreatedAt DESC;
   ```

#### Theory T3 — NEVER_INSERTED (silent SCD2 skip)

**What it means**: No Bronze row at all for this PK. SCD2 promotion silently skipped it. This is the worst case — implies a bug in the SCD2 engine OR a data shape issue.

**Investigation candidates** (in order of likelihood):
- (a) NULL in PK column → `_filter_null_pks()` excluded it before CDC
- (b) Hash collision against an existing closed row (very rare with VARCHAR(64) SHA-256)
- (c) BCP load failed for this specific batch (check Pipeline*Log for ERROR around BatchId)
- (d) Type mismatch in PK column between Stage and Bronze (B-13 territory: Oracle DATE includes time, Oracle NUMBER precision)

**Recommended action — drill into one specific PK**:

```bash
python -m tools.inspect_cdc_pk --source DNA --table ACCT --pk-values 12346,SV
```

Then query Pipeline*Log around the relevant BatchId:

```sql
-- Find the BatchId for the Stage row
SELECT _cdc_batch_id, _cdc_operation, _cdc_valid_from, _cdc_is_current
FROM UDM_Stage.DNA.ACCT_cdc
WHERE AcctNumber=12346 AND AcctType='SV';

-- Then find the SCD2_PROMOTION event for that BatchId
SELECT *
FROM General.ops.PipelineEventLog
WHERE BatchId = <BatchId>
  AND EventType = 'SCD2_PROMOTION'
  AND TableName = 'ACCT';

-- And the PipelineLog entries
SELECT TOP 100 CreatedAt, LogLevel, Module, FunctionName, Message, ErrorMessage
FROM General.ops.PipelineLog
WHERE BatchId = <BatchId>
  AND TableName = 'ACCT'
ORDER BY CreatedAt;
```

Look for: `NULL PK` warnings, hash mismatch warnings, BCP failures, schema evolution events.

#### Theory T4 — ALL_CLOSED (newest version didn't activate)

**What it means**: Bronze has multiple Flag=0 rows for this PK but no Flag=1. Same crash window as T1 but the in-flight predicate doesn't match (e.g., `UdmEndDateTime` is set, indicating the close ran but the activate didn't).

**Recommended action**:

```bash
# Dry-run repair (different repair mode than T1)
python -m tools.repair_scd2 --source DNA --table ACCT --activate-newest --dry-run
```

If the dry-run output identifies the right rows, apply:

```bash
python -m tools.repair_scd2 --source DNA --table ACCT --activate-newest --apply
```

#### Theory T5 — RESURRECTED_AS_INACTIVE (resurrection insert in-flight)

**What it means**: Bronze has both Flag=0 + Flag=2 rows but no Flag=1. PK was deleted (Flag=2 row) then re-appeared in source (Stage CDC inserted new row) but the SCD2 resurrection insert is in-flight (`UdmScd2Operation='R'` with Flag=0).

**Recommended action**:

1. Check if the next pipeline run completes the resurrection (most likely path — wait):
   ```bash
   # Run the next pipeline cycle for this table
   python main_small_tables.py --source DNA --table ACCT
   ```

2. Re-run the diagnostic:
   ```bash
   python -m tools.diagnose_stage_bronze_gap --source DNA --table ACCT
   ```

3. If still stuck, treat it as a T1 in-flight orphan and use the T1 repair flow.

#### UNKNOWN

If the diagnostic can't classify a PK (no Bronze row + diagnostic queries returned unexpected shapes), it falls into UNKNOWN. This is rare — implies the diagnostic's 5-theory taxonomy missed an edge case.

**Recommended action**: paste the full diagnostic output (especially the UNKNOWN entries) back into the chat session for analysis.

### Phase 2 success criterion

One of:
- ✅ Exit 0 (no gap; production bug not currently present)
- ✅ Exit 1 + theory classification matched + repair action ran + re-run shows gap closed
- 🚧 Exit 1 + UNKNOWN entries → bring back to chat session for analysis

---

## Phase 3 — Snowflake smoke (10 minutes)

Tests the end-to-end COPY INTO path against your trial Snowflake account.

### 3.1 Prerequisites

- [ ] Snowflake trial account access confirmed (you mentioned this is set up)
- [ ] Snowflake credentials at `/etc/pipeline/credentials.json.gpg` (D103 canonical path) OR equivalent on Windows dev — must be decryptable
- [ ] At least one `ParquetSnapshotRegistry` row with `Status IN ('verified', 'replicated')`
- [ ] Snowflake target database / schema / table created (or willing to use the default mapping per M17 `_default_snowflake_table()`)

### 3.2 Find a registry_id to test with

```sql
SELECT TOP 5 RegistryId, SourceName, TableName, BusinessDate, Status, RowCount, NetworkDrivePath
FROM General.ops.ParquetSnapshotRegistry
WHERE Status IN ('verified', 'replicated')
ORDER BY CreatedAt DESC;
```

Pick a SMALL one (e.g., `RowCount < 100K`) for the first test. Note the `RegistryId`.

### 3.3 Dry-run first

```bash
python -m tools.snowflake_copy_smoke --registry-id <ID> --dry-run
```

**Expected output**:
```
[DRY-RUN] Would COPY INTO Snowflake table: DNA.BRONZE.ACCT (or custom override)
Registry: id=123 source=DNA table=ACCT date=2026-05-13 rows=45,231
Network drive path: \\archive\udm\parquet\source=DNA\table=ACCT\year=2026\month=05\day=13\batch_id=98765\snapshot.parquet
Timeout: 300s
Exit: 0
```

No actual Snowflake call. Confirms config + registry lookup work.

### 3.4 Real COPY

```bash
python -m tools.snowflake_copy_smoke --registry-id <ID> --apply
```

**Expected output (success)**:
```
SnowflakeCopyResult:
  registry_id:      123
  snowflake_table:  DNA.BRONZE.ACCT
  rows_copied:      45,231
  copy_history_id:  01a2b3c4-5678-9def-...
  duration_ms:      4823
Exit: 0
```

### 3.5 Failure modes

| Exit code | Likely cause | What to check |
|---|---|---|
| **1** OPERATIONAL_FAILURE | `VaultUnavailable` (network), `SnowflakeCopyTimeout` (300s exceeded) | Re-run; Snowflake credit budget; network |
| **2** FATAL `RegistryNotFound` | Bad `--registry-id` | `SELECT * FROM ParquetSnapshotRegistry WHERE RegistryId=<ID>` |
| **2** FATAL `RegistryStatusInvalid` | Status not in {verified, replicated, archived} | The snapshot needs to be SHA-verified first via `tools/parquet_verify.py` |
| **2** FATAL `SnowflakeAuthFailed` | RSA key materialization failure | Check `/etc/pipeline/credentials.json.gpg` decryptable + RSA private key valid |
| **2** FATAL `SnowflakeBudgetAlert` | Budget pre-check exceeded threshold | Configurable via env; review Snowflake credits usage |
| **2** FATAL `CredentialsLoadError` | GPG decrypt failed | TPM2 / GPG agent issue |

### 3.6 Verify in Snowflake

```sql
-- In Snowflake
SELECT COUNT(*) AS row_count, MAX(_udm_extracted_at) AS latest
FROM <db>.<schema>.<table>
WHERE _udm_business_date = '2026-05-13';
```

`row_count` should match `rows_copied` from the smoke output.

### Phase 3 success criterion

- ✅ Dry-run exits 0 with sensible output
- ✅ Real `--apply` exits 0 with `rows_copied > 0`
- ✅ Row count in Snowflake matches registry's `RowCount`

---

## Phase 4 — SCD2-from-Parquet smoke (10 minutes)

Tests the end-to-end Parquet replay → SCD2 promotion path.

### 4.1 Prerequisites

- [ ] Same `RegistryId` as Phase 3 (or a different verified one)
- [ ] Bronze table exists for source/table (e.g., `UDM_Bronze.DNA.ACCT_scd2_python`)
- [ ] `TableConfig` row in `General.dbo.UdmTablesList` for the source/table
- [ ] Capture pre-test Bronze active row count for verification

### 4.2 Capture pre-test Bronze state

```sql
SELECT COUNT(*) AS bronze_active_before
FROM UDM_Bronze.DNA.ACCT_scd2_python
WHERE UdmActiveFlag = 1;
```

Note the count. You'll compare after.

### 4.3 Find the replay parameters

```sql
SELECT RegistryId, SourceName, TableName, BusinessDate, OriginalBatchId, Status, RowCount
FROM General.ops.ParquetSnapshotRegistry
WHERE RegistryId = <ID>;
```

You need `SourceName` / `TableName` / `BusinessDate` / `OriginalBatchId` for the next step.

### 4.4 Dry-run

```bash
python -m tools.scd2_replay_smoke \
  --source DNA \
  --table ACCT \
  --business-date 2026-05-13 \
  --original-batch-id 98765 \
  --dry-run
```

**Expected**: prints the resolved table_config + replay tuple + would-run-SCD2. No mutations.

### 4.5 Real apply

```bash
python -m tools.scd2_replay_smoke \
  --source DNA \
  --table ACCT \
  --business-date 2026-05-13 \
  --original-batch-id 98765 \
  --apply
```

**Expected output**:
```
Replayed parquet: registry_id=123, rows=45,231, sha256_verified=True
SCD2 promotion result:
  rows_inserted_new:     0    (PKs already exist in Bronze)
  rows_inserted_versions: 12  (new versions for changed PKs)
  rows_updated_close:    12   (closed old versions of changed PKs)
  rows_unchanged:        45,219
Bronze active rows: before=1,234,562 after=1,234,562 (delta 0)
Exit: 0
```

The replay should be **idempotent**: if you replay the same `RegistryId` twice, the second run shows 0 changes (everything matches what's already in Bronze).

### 4.6 Verify Bronze state

```sql
-- Bronze active count should match pre-test (or differ by exactly the new-version delta)
SELECT COUNT(*) AS bronze_active_after
FROM UDM_Bronze.DNA.ACCT_scd2_python
WHERE UdmActiveFlag = 1;

-- For any updated PKs, verify the source-date chain is gapless
SELECT TOP 10 AcctNumber, UdmEffectiveDateTime, UdmEndDateTime,
       UdmSourceBeginDate, UdmSourceEndDate, UdmActiveFlag, UdmScd2Operation
FROM UDM_Bronze.DNA.ACCT_scd2_python
WHERE AcctNumber IN (SELECT TOP 5 AcctNumber FROM UDM_Stage.DNA.ACCT_cdc
                     WHERE _cdc_operation = 'U' AND _cdc_is_current = 1)
ORDER BY AcctNumber, UdmEffectiveDateTime;
```

### 4.7 Failure modes

| Exit code | Likely cause | What to check |
|---|---|---|
| **1** OPERATIONAL_FAILURE | `LedgerLockTimeout` (sp_getapplock contention) | Re-run; check for stale sessions holding locks |
| **2** FATAL `RegistryNotFound` | Bad replay tuple | Verify `(SourceName, TableName, BusinessDate, OriginalBatchId)` all match a registry row |
| **2** FATAL `ParquetReplayError` | SHA-256 mismatch OR row count mismatch | File corruption; escalate to RB-6 / RB-8 |
| **2** FATAL `MissingPrimaryKey` | TableConfig has no PK columns set | Check `UdmTablesColumnsList WHERE IsPrimaryKey=1` |
| **2** FATAL `TableConfigNotFound` | Source/table not in UdmTablesList | Insert row into `UdmTablesList` |

### Phase 4 success criterion

- ✅ Dry-run exits 0 with sensible output
- ✅ Real `--apply` exits 0 with `rows_unchanged > 0`
- ✅ Bronze active count change matches the expected new-versions delta
- ✅ Idempotent re-run produces 0 changes

---

## Phase 5 — Decision: merge PR or iterate

### 5.1 If Phase 0-4 all passed cleanly

- ✅ **Recommended: merge the PR**. The work is solid: 2281 tests pass, 3 new operator tools end-to-end-tested, production-bug diagnostic infrastructure ready.
- After merge, the branch can be deleted. The next deployment can pick up `master`.

### 5.2 If Phase 2 found gap entries + Phase 2 repair actions worked

- ✅ **Recommended: merge the PR**. The diagnostic tool just paid for itself.
- Document the production-bug root cause + fix in a `_validation_log.md` follow-up entry (or paste back into chat session for me to write).

### 5.3 If Phase 2 found gap entries + repair didn't fully close the gap

- 🚧 **Hold the PR**. Bring the diagnostic output + repair output back to the chat session.
- We'll analyze the specific theory category + design the next remediation step.

### 5.4 If Phase 3 or Phase 4 hit a FATAL exit

- 🚧 **Hold the PR**. Bring the error message + relevant Pipeline*Log query results back to chat.
- Likely an environmental issue (creds, registry state, network) — not a code defect since pytest passes.

---

## Appendix A — Reference table of session deliverables

| Phase | Tool / Module | Lines | Tests | Purpose |
|---|---|---|---|---|
| Round 3 Wave 0 | `utils/errors.py` | ~410 | 111 | D68 canonical error hierarchy (PipelineFatalError / PipelineRetryableError) |
| Round 3 Wave 1-5 | 17 M-modules | ~12,500 | 952 | Core foundation modules (M1-M17) |
| Round 4.1 | 5 CLI tools | 5,700 | 392 | parquet_tier_review / parquet_verify / lateness_profile / detect_extraction_gaps / verify_server_parity_cli |
| Wave 4.6 | `decrypt_pii.py` | 1,410 | 80 | Operator-authorized PII decryption with justification + audit |
| Round 6 Tier 2 | 8 property test files | ~3,300 | 53 properties | Hypothesis property tests per Round 5 § 5.1-5.8 |
| Round 6 § 4.7 | `verify_tier0_drift.py` | 1,400 (+218 B-266) | 80 + 13 | Tier 0 spec-vs-test drift auditor |
| Round 6 follow-up | `snowflake_copy_smoke.py` | 982 | 69 | Snowflake COPY INTO end-to-end smoke |
| Round 6 follow-up | `scd2_replay_smoke.py` | 1,118 | 61 | Parquet → SCD2 end-to-end smoke |
| Round 6 follow-up | `diagnose_stage_bronze_gap.py` | 1,693 | 68 | CDC/SCD2 production-bug diagnostic |

## Appendix B — Reference docs for deep-dive

- `CLAUDE.md` § "SQL Naming Standards" + "Claude Code Security Model" + DIAG-1 / SCD2-P1-* / SCD2-R* / SCD2-R10.2 / B-2 / B-13 / W-* / E-* gotchas
- `docs/migration/HANDOFF.md` — full session continuity context
- `docs/migration/CURRENT_STATE.md` — resume-from-here pointer
- `docs/migration/GLOSSARY.md` — code/acronym reference (D-numbers, B-numbers, M-modules, R-numbers, RB-N, etc.)
- `docs/migration/BACKLOG.md` — open + closed B-Ns (current count: ~269 opened, ~140 closed)
- `docs/migration/CODE_BUILD_STATUS.md` — per-unit code-build dashboard
- `docs/migration/_validation_log.md` — chronological event log of all validation activities

## Appendix C — Operational gotchas to remember

- **D75 dry-run default**: All 3 new tools default to `--dry-run`. You MUST pass `--apply` for real invocation. The diagnostic tool is the exception — it's READ-ONLY in all modes (no `--apply` flag needed; no mutations possible).
- **D76 audit row**: Every CLI invocation writes ONE row to `General.ops.PipelineEventLog`, even on dry-run or failure. Tracks who ran what, when, with what args, and what the outcome was.
- **D74 exit codes**: 0=SUCCESS, 1=OPERATIONAL (retryable), 2=FATAL. Use these to route in scripts/automation.
- **B-2 lock escalation**: SCD2 UPDATE batches above ~5,000 rows escalate from row locks to table-level X locks. The diagnostic tool uses Polars anti-join client-side to AVOID server-side LEFT JOIN ... NULL that could trigger this.
- **D103 security model**: Claude Code operates only inside `/debi` working directory. Credentials live OUTSIDE that boundary. If a tool asks for credentials inside `/debi` — that's a red flag.

---

**End of blueprint.** Save your Phase 2 diagnostic output. Bring it back to the chat session for analysis.
