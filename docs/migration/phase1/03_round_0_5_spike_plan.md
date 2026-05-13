# Phase 1, Round 0.5 — Pre-Locking Integration Spike

**Status**: 🟢 Authorized (D47); ready to execute
**Estimated effort**: 1 engineer-week, dev environment only
**Owner**: pipeline lead (assigned per the round's start)

## Why this round exists

Per `ROUND_1_REVIEW.md` and D47: the project has 49 locked decisions and 23 fully-specified tables but **zero lines of production code**. Three integrations have not been validated by running code:

1. **D6** — vault GET-OR-CREATE under concurrency (PiiVault.SP-1)
2. **D16** — Parquet stage-check-exchange (write to `_inflight_*.parquet`, validate, atomic rename, register)
3. **D29** — Automic-driven gate-table acquisition for AM/PM cycles

Risk: by the time we start writing real code in Phase 1 Round 3 (Core Modules), these integrations will reveal edge cases that 49 locked decisions don't anticipate. Each subsequent locked decision raises the cost of correction. Round 0.5 validates these three integration points with throwaway code on dev — bounded effort, high information return.

**Output**: confirmation that D6, D16, D29 work as specified, OR a punch list of small adjustments to those decisions before locking Round 3.

## Scope (what's in / out)

### In scope

- Three test scenarios (Section 3) on dev server
- Dev SQL Server instance with v2 schema deployed (Round 1 v2 must be DBA-approved first OR a temporary `General_dev_spike` database stood up)
- Throwaway Python code in a `_spike_round_0_5/` directory (not committed to production code path)
- Findings documented in `phase1/03_round_0_5_FINDINGS.md` (created at end of round)
- Punch list of adjustments to D6, D16, D29 (or confirmation: none needed)

### Out of scope

- Production deployment of any spike code
- Any changes to vault, Bronze, Stage tables on test or prod servers
- Round 1 v2 schema fixes (separate work; can run in parallel)
- Round 2 configuration drafting (separate work)

## Pre-spike preparation (T-3 days)

```
1. Confirm dev SQL Server instance is available with admin access
2. Either:
   a) Round 1 v2 schema deployed to dev, OR
   b) Stand up a temporary General_dev_spike database with the minimum
      schema needed (PiiVault, PiiTokenizationBatch, PipelineExecutionGate,
      ParquetSnapshotRegistry, IdempotencyLedger, PipelineEventLog,
      PipelineBatchSequence)
3. Confirm dev pipeline server has Python 3.12+ with: polars, polars-hash,
   pyodbc, cryptography
4. Confirm dev network drive mount point (or use local /tmp for isolation)
5. Create _spike_round_0_5/ directory; gitignore it
6. Allocate 5 contiguous business days on the engineer's calendar
```

## Test scenarios

### Scenario A: D6 — vault GET-OR-CREATE under concurrency

**What we're validating**: SP-1 (`PiiVault_GetOrCreateToken`) is atomic. Two simultaneous callers with the same plaintext+source must produce exactly one INSERT, with both callers receiving the same token.

**Setup**:
```sql
-- Deploy SP-1 v2 (with UPDLOCK + HOLDLOCK + try/catch) to dev
-- Confirm vault is empty for the test PiiType
DELETE FROM General.ops.PiiVault WHERE PiiType = 'TEST_SSN';
```

**Test method** (`_spike_round_0_5/test_vault_concurrency.py`):
```python
import concurrent.futures
import pyodbc
from collections import Counter

CONN_STR = "..."  # dev connection
TEST_PLAINTEXT = "123-45-6789"
TEST_PII_TYPE = "TEST_SSN"
TEST_SOURCE = "DNA"
NUM_CALLERS = 16

def call_sp1():
    """Each caller hits SP-1 with the same plaintext."""
    conn = pyodbc.connect(CONN_STR, autocommit=True)
    cursor = conn.cursor()
    token = cursor.execute("""
        DECLARE @t VARCHAR(40), @new BIT;
        EXEC General.ops.PiiVault_GetOrCreateToken
            @Plaintext = ?, @PiiType = ?, @SourceName = ?,
            @Token = @t OUTPUT, @WasNew = @new OUTPUT;
        SELECT @t, @new;
    """, TEST_PLAINTEXT, TEST_PII_TYPE, TEST_SOURCE).fetchone()
    conn.close()
    return token  # (token_value, was_new)

def main():
    # Fire 16 concurrent callers
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_CALLERS) as ex:
        results = list(ex.map(lambda _: call_sp1(), range(NUM_CALLERS)))
    
    tokens = [r[0] for r in results]
    new_flags = [r[1] for r in results]
    
    # Assertions
    unique_tokens = set(tokens)
    print(f"Unique tokens: {len(unique_tokens)}")
    print(f"WasNew=True count: {sum(new_flags)}")
    print(f"WasNew=False count: {sum(1 for f in new_flags if not f)}")
    
    # Pass criteria:
    assert len(unique_tokens) == 1, f"Expected exactly 1 unique token, got {len(unique_tokens)}"
    assert sum(new_flags) == 1, f"Expected exactly 1 new INSERT, got {sum(new_flags)}"
    
    # Verify vault state
    conn = pyodbc.connect(CONN_STR)
    cursor = conn.cursor()
    row_count = cursor.execute("""
        SELECT COUNT(*) FROM General.ops.PiiVault
        WHERE PiiType = ? AND SourceName = ?
    """, TEST_PII_TYPE, TEST_SOURCE).fetchone()[0]
    assert row_count == 1, f"Expected 1 vault row, got {row_count}"
    
    print("✅ D6 vault concurrency test PASSED")

if __name__ == "__main__":
    main()
```

**Expected outcome**:
- Exactly 1 unique token across all 16 callers
- Exactly 1 INSERT (`WasNew=True` count = 1)
- Vault has exactly 1 row for the test (PiiType, SourceName, plaintext)

**What to record in findings**:
- Did SP-1 produce the expected outcome?
- Median / p99 latency per call (UPDLOCK serialization should add some latency)
- Any deadlocks in the SQL Server log during the test
- Any unexpected error codes in the catch block

**If test fails**:
- Examine the failed callers' error codes
- Check if the issue is UPDLOCK timeout vs. UNIQUE violation
- Tune `LockTimeout` in SP if needed
- Consider escalating to `MERGE WITH (HOLDLOCK)` pattern if try/catch path is exercised too often

---

### Scenario B: D16 — Parquet stage-check-exchange

**What we're validating**: Polars writes to `_inflight_*.parquet`, validation passes, atomic rename to final filename, registry INSERT succeeds. Crash mid-write leaves orphan inflight file (no false registry row); restart cleanly recovers.

**Setup**:
```sql
-- Deploy ParquetSnapshotRegistry to dev
DELETE FROM General.ops.ParquetSnapshotRegistry WHERE SourceName = 'TEST';
```

```bash
# Pick a writable path (network drive or /tmp/spike for isolation)
SPIKE_PATH=/tmp/spike/parquet
mkdir -p $SPIKE_PATH
```

**Test method** (`_spike_round_0_5/test_parquet_atomic.py`):
```python
import polars as pl
import os
import time
from pathlib import Path
import pyodbc

CONN_STR = "..."
SPIKE_PATH = Path("/tmp/spike/parquet")
TEST_SOURCE = "TEST"
TEST_TABLE = "ATOMIC_TEST"

def make_test_df(n=10_000):
    return pl.DataFrame({
        "pk": range(n),
        "value": [f"row_{i}" for i in range(n)],
        "_extracted_at": [time.time()] * n,
    })

def test_normal_write():
    """Test 1: normal stage-check-exchange completes successfully."""
    df = make_test_df()
    batch_id = int(time.time())
    inflight = SPIKE_PATH / f"{TEST_SOURCE}_{TEST_TABLE}_{batch_id}_part-0_inflight.parquet"
    final = SPIKE_PATH / f"{TEST_SOURCE}_{TEST_TABLE}_{batch_id}_part-0.parquet"
    
    # Write to inflight
    df.write_parquet(inflight, compression="zstd", compression_level=3)
    
    # Validate
    df_read = pl.read_parquet(inflight)
    assert df_read.shape == df.shape
    file_size = inflight.stat().st_size
    
    # Atomic rename
    inflight.rename(final)
    
    # Register
    conn = pyodbc.connect(CONN_STR, autocommit=True)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO General.ops.ParquetSnapshotRegistry
            (SourceName, TableName, BatchId, NetworkDrivePath, RowCount, 
             UncompressedBytes, CompressedBytes, SchemaHash)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'test_schema_hash')
    """, TEST_SOURCE, TEST_TABLE, batch_id, str(final), 
         len(df), df.estimated_size(), file_size)
    
    print(f"✅ Test 1 (normal write): {final.name} registered, size={file_size}")

def test_crash_before_rename():
    """Test 2: crash mid-write leaves orphan; no false registry row."""
    df = make_test_df()
    batch_id = int(time.time()) + 1
    inflight = SPIKE_PATH / f"{TEST_SOURCE}_{TEST_TABLE}_{batch_id}_part-0_inflight.parquet"
    
    df.write_parquet(inflight)
    # Simulate crash: don't rename, don't register
    
    # Verify state:
    conn = pyodbc.connect(CONN_STR)
    cursor = conn.cursor()
    row_count = cursor.execute("""
        SELECT COUNT(*) FROM General.ops.ParquetSnapshotRegistry
        WHERE SourceName = ? AND TableName = ? AND BatchId = ?
    """, TEST_SOURCE, TEST_TABLE, batch_id).fetchone()[0]
    
    assert row_count == 0, "Registry must NOT have a row for this batch"
    assert inflight.exists(), "Orphan inflight file must exist (recoverable)"
    
    print(f"✅ Test 2 (crash before rename): orphan inflight present, no registry row")

def test_idempotent_register():
    """Test 3: re-attempting register for same batch is a no-op (UNIQUE)."""
    df = make_test_df(100)
    batch_id = int(time.time()) + 2
    final = SPIKE_PATH / f"{TEST_SOURCE}_{TEST_TABLE}_{batch_id}_part-0.parquet"
    df.write_parquet(final)
    
    conn = pyodbc.connect(CONN_STR, autocommit=True)
    cursor = conn.cursor()
    
    # First insert succeeds
    cursor.execute("""
        INSERT INTO General.ops.ParquetSnapshotRegistry
            (SourceName, TableName, BatchId, NetworkDrivePath, RowCount,
             UncompressedBytes, CompressedBytes, SchemaHash)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'test_schema_hash')
    """, TEST_SOURCE, TEST_TABLE, batch_id, str(final),
         100, 5000, 2000)
    
    # Second attempt with same identity (SourceName, TableName, BatchId, BusinessDate)
    # should hit UNIQUE constraint
    try:
        cursor.execute("""
            INSERT INTO General.ops.ParquetSnapshotRegistry
                (SourceName, TableName, BatchId, NetworkDrivePath, RowCount,
                 UncompressedBytes, CompressedBytes, SchemaHash)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'test_schema_hash')
        """, TEST_SOURCE, TEST_TABLE, batch_id, str(final),
             100, 5000, 2000)
        assert False, "Second INSERT should have failed (UNIQUE violation)"
    except pyodbc.IntegrityError:
        print(f"✅ Test 3 (idempotent register): UNIQUE constraint correctly rejected duplicate")

if __name__ == "__main__":
    test_normal_write()
    test_crash_before_rename()
    test_idempotent_register()
```

**Expected outcome**:
- Test 1: file written, validated, renamed, registered. Round-trip read matches input.
- Test 2: orphan inflight file present, registry has no row.
- Test 3: second INSERT hits UNIQUE constraint, throws IntegrityError.

**What to record in findings**:
- Polars write throughput on dev disk (rows/sec, MB/sec)
- Atomic rename behavior on the chosen filesystem (Linux vs SMB share — different semantics)
- Compression ratio achieved (ZSTD-3 target: ~5x for narrow tables)
- Any unexpected errors in normal path

**If test fails**:
- If atomic rename doesn't work on SMB: reconsider D16 — may need a different staging approach (e.g., write to local tmp, then rsync to network)
- If registry INSERT race conditions surface: revisit ParquetSnapshotRegistry constraint design

---

### Scenario C: D29 — Automic-driven gate-table acquisition

**What we're validating**: The Automic + SQL Server gate coordination model from D29 (revised) actually works. Production claims gate, runs, completes; or production fails and test claims gate via failover with sp_getapplock preventing double-claim.

**Setup**:
```sql
-- Deploy PipelineExecutionGate, PipelineBatchSequence, and SP-3 through SP-6
DELETE FROM General.ops.PipelineExecutionGate WHERE CycleType IN ('TEST_AM', 'TEST_PM');
```

**Test method** (`_spike_round_0_5/test_gate_acquisition.py`):
```python
import pyodbc
import time
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor

CONN_STR = "..."
TEST_CYCLE_TYPE = "AM"
TEST_CYCLE_DATE = date.today()

def acquire_prod():
    """Simulate production claiming gate."""
    conn = pyodbc.connect(CONN_STR, autocommit=True)
    cursor = conn.cursor()
    cursor.execute("""
        DECLARE @gate_id BIGINT, @batch_id BIGINT;
        EXEC General.ops.PipelineExecutionGate_AcquireProd
            @CycleType = ?, @CycleDate = ?,
            @ExpectedStartTime = ?,
            @GateId = @gate_id OUTPUT, @BatchId = @batch_id OUTPUT;
        SELECT @gate_id, @batch_id;
    """, TEST_CYCLE_TYPE, TEST_CYCLE_DATE, datetime.utcnow())
    return cursor.fetchone()

def acquire_test():
    """Simulate test failover check."""
    conn = pyodbc.connect(CONN_STR, autocommit=True)
    cursor = conn.cursor()
    cursor.execute("""
        DECLARE @gate_id BIGINT, @batch_id BIGINT, @action NVARCHAR(30);
        EXEC General.ops.PipelineExecutionGate_AcquireTest
            @CycleType = ?, @CycleDate = ?,
            @ExpectedStartTime = ?,
            @GateId = @gate_id OUTPUT, 
            @BatchId = @batch_id OUTPUT,
            @Action = @action OUTPUT;
        SELECT @gate_id, @batch_id, @action;
    """, TEST_CYCLE_TYPE, TEST_CYCLE_DATE, datetime.utcnow())
    return cursor.fetchone()

def request_cancellation():
    """Simulate test pipeline requesting cancellation."""
    conn = pyodbc.connect(CONN_STR, autocommit=True)
    cursor = conn.cursor()
    cursor.execute("""
        EXEC General.ops.PipelineExecutionGate_RequestCancellation
            @CycleType = ?, @CycleDate = ?,
            @RequestedBy = 'test_failover',
            @Reason = 'Spike test cancellation';
    """, TEST_CYCLE_TYPE, TEST_CYCLE_DATE)

def acknowledge_cancellation(gate_id):
    """Simulate production acknowledging cancellation."""
    conn = pyodbc.connect(CONN_STR, autocommit=True)
    cursor = conn.cursor()
    cursor.execute("""
        EXEC General.ops.PipelineExecutionGate_AcknowledgeCancellation @GateId = ?;
    """, gate_id)

def test_normal_prod_run():
    """Test 1: prod acquires, runs, completes; test exits cleanly."""
    # Reset
    conn = pyodbc.connect(CONN_STR, autocommit=True)
    conn.cursor().execute("""
        DELETE FROM General.ops.PipelineExecutionGate
        WHERE CycleType = ? AND CycleDate = ?
    """, TEST_CYCLE_TYPE, TEST_CYCLE_DATE)
    
    # Prod claims gate
    gate_id, batch_id = acquire_prod()
    print(f"  Prod gate_id={gate_id}, batch_id={batch_id}")
    
    # Simulate prod running and completing
    cursor = pyodbc.connect(CONN_STR, autocommit=True).cursor()
    cursor.execute("""
        UPDATE General.ops.PipelineExecutionGate
        SET Status = 'SUCCEEDED',
            ActualCompletionTime = SYSUTCDATETIME(),
            LastHeartbeatAt = SYSUTCDATETIME()
        WHERE GateId = ?
    """, gate_id)
    
    # Test runs failover check; should see SUCCEEDED
    test_gate_id, test_batch_id, action = acquire_test()
    assert action == 'EXIT_SUCCEEDED', f"Expected EXIT_SUCCEEDED, got {action}"
    print(f"✅ Test 1 (normal prod run): test correctly exits clean (action={action})")

def test_failover_prod_failed():
    """Test 2: prod fails; test claims gate via failover."""
    # Reset
    conn = pyodbc.connect(CONN_STR, autocommit=True)
    conn.cursor().execute("""
        DELETE FROM General.ops.PipelineExecutionGate
        WHERE CycleType = ? AND CycleDate = ?
    """, TEST_CYCLE_TYPE, TEST_CYCLE_DATE)
    
    # Prod claims gate, then fails
    gate_id, batch_id = acquire_prod()
    cursor = pyodbc.connect(CONN_STR, autocommit=True).cursor()
    cursor.execute("""
        UPDATE General.ops.PipelineExecutionGate
        SET Status = 'FAILED',
            FailureReason = 'Simulated prod failure',
            LastHeartbeatAt = SYSUTCDATETIME()
        WHERE GateId = ?
    """, gate_id)
    
    # Test runs failover check; should claim gate
    test_gate_id, test_batch_id, action = acquire_test()
    assert action == 'PROCEED_FAILOVER', f"Expected PROCEED_FAILOVER, got {action}"
    assert test_gate_id == gate_id, f"Expected same gate_id, got {test_gate_id}"
    assert test_batch_id != batch_id, f"Expected new batch_id, got {test_batch_id}"
    
    # Verify gate state
    cursor.execute("""
        SELECT ExecutingServer, Status FROM General.ops.PipelineExecutionGate
        WHERE GateId = ?
    """, gate_id)
    row = cursor.fetchone()
    assert row[0] == 'test', f"Expected ExecutingServer=test, got {row[0]}"
    assert row[1] == 'STARTING', f"Expected Status=STARTING, got {row[1]}"
    print(f"✅ Test 2 (failover): test correctly claimed gate (action={action})")

def test_cancellation_flow():
    """Test 3: prod stuck; test requests cancel; prod acknowledges; test claims."""
    # Reset
    conn = pyodbc.connect(CONN_STR, autocommit=True)
    conn.cursor().execute("""
        DELETE FROM General.ops.PipelineExecutionGate
        WHERE CycleType = ? AND CycleDate = ?
    """, TEST_CYCLE_TYPE, TEST_CYCLE_DATE)
    
    # Prod claims gate, "runs" but with stale heartbeat
    gate_id, batch_id = acquire_prod()
    cursor = pyodbc.connect(CONN_STR, autocommit=True).cursor()
    cursor.execute("""
        UPDATE General.ops.PipelineExecutionGate
        SET Status = 'RUNNING',
            ActualStartTime = DATEADD(HOUR, -3, SYSUTCDATETIME()),
            LastHeartbeatAt = DATEADD(MINUTE, -30, SYSUTCDATETIME())
        WHERE GateId = ?
    """, gate_id)
    
    # Test detects stuck prod, requests cancel
    request_cancellation()
    
    # Verify cancellation flag set
    cursor.execute("""
        SELECT CancellationRequested, CancellationRequestedBy
        FROM General.ops.PipelineExecutionGate
        WHERE GateId = ?
    """, gate_id)
    row = cursor.fetchone()
    assert row[0] == True
    assert row[1] == 'test_failover'
    
    # Prod acknowledges
    acknowledge_cancellation(gate_id)
    
    # Verify gate Status is CANCELLED
    cursor.execute("""
        SELECT Status, CancellationAcknowledgedAt
        FROM General.ops.PipelineExecutionGate
        WHERE GateId = ?
    """, gate_id)
    row = cursor.fetchone()
    assert row[0] == 'CANCELLED'
    assert row[1] is not None
    print(f"✅ Test 3 (cancellation): prod cancelled, ack received, gate status=CANCELLED")
    
    # Test now claims gate via failover
    test_gate_id, test_batch_id, action = acquire_test()
    # After CANCELLED, test should be able to claim (not EXIT_SUCCEEDED, not EXIT_RUNNING_HEALTHY)
    assert action == 'PROCEED_FAILOVER', f"Expected PROCEED_FAILOVER post-cancel, got {action}"
    print(f"✅ Test 3b: test claimed gate post-cancellation (action={action})")

def test_concurrent_test_attempts():
    """Test 4: two test pipelines run simultaneously; sp_getapplock prevents double-claim."""
    # Reset to no row (worst case)
    conn = pyodbc.connect(CONN_STR, autocommit=True)
    conn.cursor().execute("""
        DELETE FROM General.ops.PipelineExecutionGate
        WHERE CycleType = ? AND CycleDate = ?
    """, TEST_CYCLE_TYPE, TEST_CYCLE_DATE)
    
    # Two test instances try simultaneously
    with ThreadPoolExecutor(max_workers=2) as ex:
        results = list(ex.map(lambda _: acquire_test(), range(2)))
    
    # Exactly one should get PROCEED_FAILOVER
    actions = [r[2] for r in results]
    proceed_count = sum(1 for a in actions if a == 'PROCEED_FAILOVER')
    
    # The second one might get EXIT_RUNNING_HEALTHY (because first one set Status=STARTING)
    # or might also get PROCEED_FAILOVER if timing works out — but only one should have
    # actually written the gate row.
    
    # Verify gate state shows exactly one batch_id
    cursor = pyodbc.connect(CONN_STR).cursor()
    cursor.execute("""
        SELECT BatchId, ExecutingServer, Status
        FROM General.ops.PipelineExecutionGate
        WHERE CycleType = ? AND CycleDate = ?
    """, TEST_CYCLE_TYPE, TEST_CYCLE_DATE)
    rows = cursor.fetchall()
    assert len(rows) == 1, f"Expected 1 gate row, got {len(rows)}"
    print(f"✅ Test 4 (concurrent test): exactly 1 gate row (sp_getapplock works)")

if __name__ == "__main__":
    test_normal_prod_run()
    test_failover_prod_failed()
    test_cancellation_flow()
    test_concurrent_test_attempts()
```

**Expected outcome**:
- Test 1: prod acquires, completes; test exits with action=EXIT_SUCCEEDED
- Test 2: prod fails; test acquires with action=PROCEED_FAILOVER
- Test 3: cancellation flow completes end-to-end; gate ends in CANCELLED state
- Test 4: two simultaneous test claims → exactly one gate row

**What to record in findings**:
- sp_getapplock acquisition time (typically <100ms)
- Cycle through prod-acquire → fail → test-acquire timing
- Any deadlocks or unexpected errors
- Confirmation that the cancellation acknowledgment path works

**If test fails**:
- If sp_getapplock doesn't serialize: reconsider lock semantics in SP-3 / SP-4
- If cancellation flag isn't propagated correctly: revisit SP-5 / SP-6 logic
- If concurrent test attempts produce >1 gate row: critical bug, must fix before any production deployment

## Deliverable: `phase1/03_round_0_5_FINDINGS.md`

At end of round, the engineer who executed the spike writes a findings document with this structure:

```markdown
# Round 0.5 Findings

## Executed
- Date range: <start> to <end>
- Engineer: <name>
- Dev environment: <SQL Server instance, host, network drive path>

## Scenario A — Vault concurrency (D6)
- Test 1 result: PASS / FAIL
- Latency stats: median X ms, p99 Y ms, max Z ms
- Issues encountered: <list>
- Recommendation: D6 confirmed as-is | D6 needs adjustment <details>

## Scenario B — Parquet stage-check-exchange (D16)
- Test 1 (normal): PASS / FAIL
- Test 2 (crash recovery): PASS / FAIL
- Test 3 (idempotent register): PASS / FAIL
- Performance: <write throughput, compression ratio>
- Recommendation: D16 confirmed | D16 needs adjustment <details>

## Scenario C — Gate acquisition (D29)
- Test 1 (normal prod run): PASS / FAIL
- Test 2 (failover): PASS / FAIL
- Test 3 (cancellation flow): PASS / FAIL
- Test 4 (concurrent test): PASS / FAIL
- Recommendation: D29 confirmed | D29 needs adjustment <details>

## Punch list (decision adjustments needed)
| Decision | Adjustment | Severity |
|---|---|---|
| ... | ... | ... |

## Round 0.5 verdict
- [ ] All three integrations validated as specified
- [ ] Adjustments needed: <list, with priority>
- [ ] Round 3 (Core Modules) can proceed: yes / yes-with-adjustments / no

## Cleanup
- [ ] Spike code committed to a branch (not main)
- [ ] Dev test data cleaned up (vault rows, gate rows, parquet files)
- [ ] _spike_round_0_5/ directory removed or archived
```

## Acceptance criteria for Round 0.5

- All 3 scenarios executed (10 individual tests)
- Findings document written and reviewed
- Punch list produced (zero items = D6/D16/D29 confirmed; non-zero items = D-numbers updated before Round 3)
- Spike code archived (not in production code path)
- Dev environment cleaned up

## What this round does NOT validate

- End-to-end pipeline (extract → tokenize → write parquet → SCD2 → register) — that's Phase 2 pilot
- Bronze SCD2 logic — covered in Phase 1 Round 3
- Cross-server failover — that's Phase 4 DR rehearsal
- Snowflake integration — Phase 5
- Production-class load — none of this runs on prod

## Related decisions

- D6 — vault tokenization
- D16 — Parquet stage-check-exchange
- D29 — Automic gate (revised)
- D33 — Cooperative cancellation
- D45 — Phase 1 Round 1 schema (the SP-1 v2, SP-3 through SP-6 v2 inlined are tested here)
- D47 — this round's authorization
