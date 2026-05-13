# UDM Pipeline Migration — Operational Runbooks

Procedures for the operations the team will run during migration and steady-state. Each runbook is self-contained and assumes only that the reader has CLAUDE.md context.

## Runbook Index

| # | Runbook | When to use |
|---|---|---|
| RB-1 | Per-table cutover (legacy → new flow) | Phase 2-4 migrations |
| RB-2 | Recovery from production outage (server failover) | Production server unavailable >2h |
| RB-3 | Recovery from extraction gaps (post-outage backfill) | Pipeline returned from downtime |
| RB-4 | PII decryption for audit / dispute resolution | Auditor or operator request for plaintext |
| RB-5 | Backfill an explicit date range | Discovered historical gap or correction needed |
| RB-6 | Vault corruption recovery | PiiVault integrity compromised |
| RB-7 | DR rehearsal (quarterly) | Scheduled disaster recovery test |
| RB-8 | Bronze rebuild from Parquet | Catastrophic Bronze loss |
| RB-9 | Automatic AM/PM failover | AM or PM run failed, timed out, or never started |
| RB-10 | CCPA / CPRA right-to-deletion request | Customer requests data deletion under California privacy law |
| RB-11 | 7-year retention enforcement | Monthly automated job; vault Status flips for expired tokens |
| RB-12 | Pipeline Deployment (per D84-D87) | Scheduled per D86 cadence (dev nightly / test daily / prod weekly Monday window) OR emergency hotfix (with operator + pipeline-lead sign-off). Covers full deploy + rollback + recovery + TPM2 re-seal procedures |
| RB-13 | Permanent-retire Table | Source table permanently decommissioned; consumer + compliance sign-off obtained; ≥ 90-day cool-down (or `ExpectedRetentionDays`) elapsed |
| RB-14 | `.env` Location Migration (`/debi/.env` → `/etc/pipeline/.env`) | One-time per-server migration per D103; closes B182; run BEFORE next pipeline deploy after 2026-05-11 |

---

## RB-1: Per-Table Cutover

**When**: a table is migrating from the legacy CDC/Stage flow to the new Parquet-snapshot + direct-to-Bronze flow.

### Pre-flight checks (T-24h)

```
1. Confirm no manual runs / backfills scheduled for the table
2. Notify consumer-team owners (from Phase 0 audit) of impending cutover
3. Run integrity validation:
     python3 tools/validate_scd2.py --source X --table Y
     # Must report HEALTHY. If not, resolve before cutover.
4. Drain crash recovery:
     python3 tools/repair_scd2.py --source X --table Y --dry-run
     # If any repairs proposed, resolve before cutover.
5. Verify idempotency ledger has no stale IN_PROGRESS rows for this table:
     SELECT * FROM General.ops.IdempotencyLedger
     WHERE SourceName='X' AND TableName='Y'
       AND Status='IN_PROGRESS'
       AND StartedAt < DATEADD(hour, -4, SYSUTCDATETIME());
     # If any rows: resolve via startup recovery sweep first.
```

### Cutover (T)

```sql
-- Acquire table-level lock (extended timeout, 30s)
DECLARE @lock INT;
EXEC @lock = sp_getapplock
    @Resource = N'pipeline_table_X_Y',
    @LockMode = 'Exclusive',
    @LockOwner = 'Session',
    @LockTimeout = 30000;
-- @lock must be 0; abort otherwise

BEGIN TRAN;

-- 1. Close the legacy change-detect chapter
UPDATE [UDM_Stage].[X].[Y_cdc]
SET _cdc_is_current = 0,
    _cdc_valid_to = SYSUTCDATETIME()
WHERE _cdc_is_current = 1;

-- 2. Stamp cutover event
INSERT INTO General.ops.PipelineEventLog
  (BatchId, TableName, SourceName, EventType, EventDetail, Status, Metadata, StartedAt, CompletedAt)
VALUES
  (NEXT VALUE FOR General.ops.PipelineBatchSequence,
   'Y', 'X', 'CDC_MODE_CUTOVER',
   'legacy_to_parquet_snapshot',
   'SUCCESS',
   '{"rows_closed": ' + CAST(@@ROWCOUNT AS VARCHAR(20)) + '}',
   SYSUTCDATETIME(), SYSUTCDATETIME());

-- 3. Flip the table's mode
UPDATE General.dbo.UdmTablesList
SET CDCMode = 'parquet_snapshot'
WHERE SourceName = 'X' AND SourceObjectName = 'Y';

COMMIT TRAN;

EXEC sp_releaseapplock @Resource = N'pipeline_table_X_Y';
```

### Post-cutover validation

```
1. Run the next scheduled pipeline cycle for this table
   python3 main_small_tables.py --source X --table Y

2. Verify Parquet snapshot was written:
   SELECT * FROM General.ops.ParquetSnapshotRegistry
   WHERE SourceName='X' AND TableName='Y'
   ORDER BY CreatedAt DESC;

3. Verify Bronze identical to pre-cutover for unchanged rows:
   python3 tools/validate_parquet.py --source X --table Y --against-bronze

4. Verify idempotency:
   # Re-run pipeline with same BatchId; assert zero new Bronze rows
   python3 main_small_tables.py --source X --table Y --batch-id <prior_batch_id>

5. Soak: 2 weeks of unattended daily runs before next cohort cutover
```

### Rollback (within 48h post-cutover only)

```sql
-- Restore prior CDCMode; pipeline reverts to legacy Stage path
UPDATE General.dbo.UdmTablesList
SET CDCMode = 'change_detect'
WHERE SourceName = 'X' AND SourceObjectName = 'Y';

-- Restore Stage current rows (use prior batch's snapshot to identify)
-- This is awkward; document operator decision in PipelineEventLog.
INSERT INTO General.ops.PipelineEventLog
  (..., EventType='CDC_MODE_ROLLBACK', ...)
```

After 48h, rollback is no longer feasible because the new flow has accumulated Parquet history that the legacy flow can't consume.

---

## RB-2: Production Server Failover

**When**: production pipeline server unavailable >2 hours, system engineering team confirms not transient.

### Promotion (test → production)

```
1. Confirm production unavailable; system engineering ack
2. Acquire emergency_promotion lock:
   INSERT INTO General.ops.PromotionLock (LockedAt, LockedBy, Reason)
   VALUES (SYSUTCDATETIME(), SYSTEM_USER, 'Production server hardware failure');

3. On TEST server:
   a. Stop test pipeline cron
   b. Update /debi/.env to point to PRODUCTION endpoints:
      - SQL Server target endpoints (UDM_Stage, UDM_Bronze, General)
      - Network drive paths (\\archive\...)
      - PiiVault credentials (production role)
      - Source database connection strings (prod)
   c. Verify connectivity:
      python3 -c "from utils.connections import test_all; test_all()"
   d. Run smoke test:
      python3 main_small_tables.py --source DNA --table <smoke_test_table> --dry-run

4. If smoke test passes:
   a. Schedule promoted-test for next pipeline window
   b. Insert event:
      INSERT INTO General.ops.PipelineEventLog (... EventType='PROMOTION_EVENT' ...)
   c. Notify ops + business stakeholders via standard channel

5. While promoted-test handles production load:
   - System engineering rebuilds production
   - Run gap detector hourly during this period
   - Note: dev → test promotion concurrent is optional but recommended

6. CUTBACK to production (mirror of promotion):
   a. Confirm production rebuilt and tested
   b. Stop promoted-test cron
   c. Reset test config to test endpoints
   d. Start production cron
   e. Run gap detector to verify no missed dates
   f. Release emergency_promotion lock
```

### What if test server is also unavailable?

Dev → production promotion. Same protocol. After cutback, restore test server first (production stable) then dev.

---

## RB-3: Post-Outage Gap Recovery

**When**: pipeline returns from any outage (server failure, source unavailability, network drive offline). Run after server is back online.

```
1. Smoke test:
   python3 main_small_tables.py --source DNA --table <smoke_test_table>

2. Detect gaps:
   python3 tools/detect_extraction_gaps.py --since {last_known_good_date}
   # Output: list of (source, table, dates) with classification

3. Decide per gap class:

   GAPS WITHIN LOOKBACK WINDOW:
     Action: none required
     Range scheduler picks them up on next normal run
     Validate: re-run gap detector after one pipeline cycle; gap should clear

   GAPS BEYOND LOOKBACK BUT WITHIN SOURCE RETENTION:
     Action:
       python3 tools/backfill.py --source X --table Y --from D1 --to D2
       # IsReExtraction=1 stamped automatically
     Pipeline processes on next run with priority over normal lookback
     Re-run gap detector after backfill completes

   GAPS BEYOND SOURCE RETENTION:
     Action: cannot recover from source
     Document the gap:
       INSERT INTO General.ops.ExtractionGapLog (SourceName, TableName,
              MissingFromDate, MissingToDate, Resolution, Reason)
       VALUES ('X', 'Y', D1, D2,
               'ACCEPTED', 'Beyond source retention; documented in audit log');
     Run cross-source reconciliation if any other system retained the data
     Auditor query "did pipeline run on date D" returns honest answer:
       "No — see ExtractionGapLog row {id} for documented outage"

4. Verify Bronze integrity for the recovery period:
   python3 tools/validate_scd2.py --since {last_known_good_date}

5. Run weekly P3-4 reconciliation early to confirm no drift

6. Confirm idempotency:
   # Re-run a recovered date a second time; assert zero new Bronze writes
```

---

## RB-4: PII Decryption (Authorized)

**When**: auditor request, dispute resolution, regulator inquiry, or internal investigation.

### Authorization gate

```
1. Verify caller has the role PII_DECRYPT_REQUESTOR
   SELECT * FROM sys.database_role_members
   WHERE member_principal_id = USER_ID(SYSTEM_USER);

2. Document business reason in advance:
   INSERT INTO General.ops.PiiDecryptRequest
     (RequestedBy, RequestedAt, BusinessReason, RequestId)
   VALUES (SYSTEM_USER, SYSUTCDATETIME(),
           'Audit request from Compliance team, ticket #12345',
           NEWID());

3. Capture the RequestId for the decrypt call
```

### Decryption call

```sql
-- Use the audited stored procedure; never SELECT directly from PiiVault
EXEC General.ops.PiiVault_Decrypt
    @RequestId = '<uuid-from-step-2>',
    @TokenList = N'token1,token2,token3',
    @Justification = N'Audit request 12345';

-- Returns: token, plaintext, plus inserts row into PiiVaultAccessLog
```

### Post-decryption

```
1. Capture decrypted output to a secured ticket attachment (encrypted at rest)
2. Do NOT log plaintext to file or console
3. Confirm PiiVaultAccessLog has matching row:
   SELECT * FROM General.ops.PiiVaultAccessLog
   WHERE RequestId = '<uuid>';
4. Close ticket with reference to RequestId
```

### Bulk decryption (rare)

For large-scale audit requests:
```sql
-- Use the bulk-decrypt procedure with an explicit row limit
EXEC General.ops.PiiVault_DecryptBulk
    @RequestId = '<uuid>',
    @MaxRows = 1000,
    @Justification = N'...';
```

`@MaxRows` is enforced server-side. Larger requests must be broken into multiple calls; each logged separately.

---

## RB-5: Backfill an Explicit Date Range

**When**: discovered a historical gap, source corrected old data, or operator-driven reload.

```bash
# Dry run first to preview what will happen
python3 tools/backfill.py \
    --source DNA \
    --table ACCT \
    --from 2024-01-01 \
    --to 2024-01-31 \
    --dry-run

# Output:
# Would re-extract 31 dates
# Estimated rows: ~93M (3M/day × 31)
# Estimated runtime: ~75 minutes
# Will mark IsReExtraction=1 on each PipelineExtraction row

# Execute (omit --dry-run)
python3 tools/backfill.py \
    --source DNA \
    --table ACCT \
    --from 2024-01-01 \
    --to 2024-01-31 \
    --reason "Source team corrected DATELASTMAINT bug for January 2024"
```

### Validation

```
1. Run gap detector:
   python3 tools/detect_extraction_gaps.py --since 2024-01-01 --until 2024-01-31
   # Should report no gaps for the backfilled range

2. Verify Bronze captured changes:
   SELECT TableName, EventType, RowsInserted, RowsUpdated, EventDetail
   FROM General.ops.PipelineEventLog
   WHERE TableName = 'ACCT' AND SourceName = 'DNA'
     AND EventDetail BETWEEN '2024-01-01' AND '2024-01-31'
   ORDER BY EventDetail;

3. If source data was unchanged for some dates: zero Bronze writes (idempotent)
4. If source corrected: new SCD2 versions reflect the correction
```

---

## RB-6: Vault Corruption Recovery

**When**: PiiVault integrity check fails, vault row count anomalies, suspected unauthorized modification.

### Detection signals

- `PiiVault` row count drops unexpectedly (monitored daily)
- Pipeline encrypt operation produces a new token for an existing plaintext (vault lookup miss)
- Auditor decrypt request fails for a token that should exist

### Immediate response

```
1. Stop all pipeline runs:
   crontab -e  # comment out pipeline schedule
   pkill -f main_small_tables.py
   pkill -f main_large_tables.py

2. Snapshot the current vault state (for forensic analysis):
   sqlcmd -S server -d General -Q "
     SELECT * INTO General.ops.PiiVault_forensic_<timestamp>
     FROM General.ops.PiiVault;"

3. Identify scope of corruption:
   # Compare row count to last good backup
   # Identify missing or modified rows
```

### Restore

```
1. Identify the most recent verified backup (weekly restore-test should give confidence)
2. Restore vault to a STAGING database first:
   RESTORE DATABASE General_staging FROM DISK = '/backup/General_<date>.bak'
   WITH REPLACE, MOVE 'General_data' TO '/data/General_staging.mdf';

3. Compare staging vault vs production:
   # Identify rows in production NOT in staging (these may be POST-corruption new tokens)
   # Identify rows in staging NOT in production (these are the corrupted/lost rows)

4. Apply both deltas:
   a. Insert the lost rows from staging into production (recover lost mappings)
   b. Audit the post-corruption new rows; if any are valid, retain; if any are
      duplicates/corruption, remove

5. Verify integrity:
   SELECT COUNT(*), COUNT(DISTINCT PlaintextHash) FROM General.ops.PiiVault;
   # Counts should be equal (UNIQUE constraint enforces)

6. Rotate decrypt access credentials (precautionary)

7. Restart pipeline; first run uses ledger to validate idempotency

8. File incident report including: timeline, scope, restoration actions, lessons learned
```

### What if backup is also corrupt?

Then tokens minted between the last good backup and now point to plaintexts that cannot be recovered. Affected Bronze/Parquet rows have orphan tokens. Document in audit log; downstream consumers cannot decrypt these rows.

This is a regulator-reportable incident. Engage compliance team immediately.

---

## RB-7: Quarterly DR Rehearsal

**When**: scheduled quarterly (March, June, September, December).

**Alternating scenarios** (per D44):
- **Q1 (March), Q3 (September)**: Server-failover scenario — production server unavailable, promote test
- **Q2 (June), Q4 (December)**: **Data center loss scenario** — primary site unavailable, recover from offsite Parquet archive

### Scenario A — Server-failover (Q1 + Q3) script

```
1. Day 1, 09:00: Schedule a 24-hour production "outage" simulation
   - Coordinate with system engineering
   - Notify business stakeholders (this is a drill)
   - Confirm support availability

2. Day 1, 10:00: Simulate production server unavailability
   - System engineering blocks pipeline server access (firewall rule, not destruction)
   - Pipeline cron fails

3. Day 1, 10:30: Operator team detects outage (via freshness alert)

4. Day 1, 11:00: Execute RB-2 (server failover) on test server
   - Time the promotion
   - Document any unexpected friction

5. Day 1-2: Promoted-test runs production load for 24 hours

6. Day 2, 10:00: Restore production access (system engineering)

7. Day 2, 11:00: Execute RB-2 cutback procedure

8. Day 2, 12:00: Run RB-3 gap recovery
   - Should report no gaps (failover handled it)
   - Or, intentionally introduced gaps for the rehearsal — backfill them

9. Day 2, 13:00: Validate Bronze integrity
   - Run all validation tools
   - Compare against pre-rehearsal Bronze snapshot
   - Should be identical except for legitimate intra-rehearsal source changes

10. Day 2, 14:00: Post-mortem
    - What went well
    - What surprised the team
    - Update RB-2 with lessons learned
    - File the rehearsal report in this directory
```

### Scenario A pass criteria

- Total promotion + cutback time < 4 hours combined
- Zero data loss
- All validation tools green post-rehearsal
- Operator team able to execute without runbook author present

### Scenario B — Data center loss (Q2 + Q4) script

```
1. T-7 days: confirm offsite Parquet replication is current (per D44)
   - Verify ParquetSnapshotRegistry shows recent SnowflakeStagePath populated, OR
   - Verify offsite network drive (different DC) has Parquet copies up to last hour, OR
   - Verify whatever offsite mechanism is in place per Phase 4 deliverable

2. Day 1, 09:00: Schedule a 24-hour DC-loss simulation
   - Coordinate with system engineering and the DR site team
   - Notify business stakeholders (this is a drill)

3. Day 1, 10:00: Simulate primary site unavailability
   - System engineering blocks ALL access to primary DC (firewall rule)
   - Pipeline server, SQL Server, network drive all unreachable from outside

4. Day 1, 10:30: DR team detects unavailability via existing monitoring

5. Day 1, 11:00: Begin recovery at the DR site (separate physical location)
   a. Provision DR-site SQL Server instance (or use pre-staged DR replica)
   b. Provision DR-site Linux server with pipeline code (parity-verified)
   c. Mount offsite Parquet storage as the DR network drive
   d. Bring up DR vault (restored from latest backup, per RB-6)
   e. Verify connectivity and parity

6. Day 1, 12:00 - Day 2, 00:00: Reconstruct Bronze via RB-8 (Bronze rebuild from Parquet)
   - Replay Parquet snapshots in batch_id order through SCD2
   - Bounded by table count and Parquet volume; for the largest 3B-row table,
     this is multi-hour but acceptable for DR
   - For smaller tables, reconstruction is fast

7. Day 2, 06:00: Bring DR pipeline online; resume daily AM/PM cycles
   - Idempotent: if source data is reachable from DR site, reconstruction is straightforward
   - If source is unreachable from DR site (geographically isolated), document the gap

8. Day 2, 09:00: Verify DR site is producing identical Bronze output
   - Compare against pre-loss Bronze snapshot
   - Run validate_scd2.py
   - Run sample auditor queries

9. Day 2, 10:00: Restore primary site access (system engineering)

10. Day 2, 11:00: Cutback decision:
    - Option A: continue running from DR site for an extended period (if cleaner)
    - Option B: cutback to primary; DR site reverts to standby
    - Option C: keep DR site as second active replica (if architecture supports)

11. Day 2, 14:00: Post-mortem
    - Time to recovery (target: < 24 hours; ambitious target: < 12 hours)
    - Data integrity (any loss?)
    - Process gaps discovered
    - Update RB-7 with lessons learned
```

### Scenario B pass criteria

- DR site reaches operational state within 24 hours of simulated outage
- Bronze reconstruction matches pre-loss snapshot (allowing for legitimate intra-rehearsal source changes)
- Vault decryption works against restored vault for sample tokens
- All validation tools green post-recovery
- Documentation reflects the actual DR procedure (no untested steps)

---

## RB-8: Bronze Rebuild from Parquet (Catastrophic)

**When**: SQL Server Bronze database lost, corrupted beyond standard backup recovery, or migration to new infrastructure.

### Estimate scope before starting

```
1. Identify date range to rebuild:
   - From: FirstLoadDate per UdmTablesList
   - To: today
2. Estimate runtime per table:
   - Small: ~10 sec/batch × 730 batches/year × N years
   - Large: ~5 min/day × 365 × N years
3. For 3B-row table over 7 years: ~10-14 days
4. Stage on dev or test server first, never directly into production
```

### Procedure

```python
# Pseudocode - tools/rebuild_bronze_from_parquet.py
for table in tables_to_rebuild:
    # 1. Drop and recreate Bronze table (clean slate)
    drop_bronze_table(table)
    ensure_bronze_table(table)
    
    # 2. Read all Parquet snapshots in batch_id order
    parquet_files = (
        ParquetSnapshotRegistry
        .filter(SourceName=table.source, TableName=table.name)
        .order_by('BatchId')
    )
    
    # 3. Replay each batch through SCD2 in order
    for parquet in parquet_files:
        df = read_parquet(parquet.NetworkDrivePath)
        run_scd2(table, df)  # Idempotent; conditional MERGE
        log_progress(table, parquet)
    
    # 4. Validate against weekly P3-4 reconciliation snapshot
    validate_bronze_against_reconciliation_baseline(table)
```

### Validation

- Bronze row count within 1% of pre-loss snapshot (allow for legitimate changes during rebuild)
- All `UdmActiveFlag=1` PKs match the latest Parquet's PK set
- Sample 100 random PKs; verify version chain matches expected SCD2 history
- Run reconciliation against source for top 10 high-value tables

### Time-to-recover

For the full 3B-row dimension table set: 7-14 days replay. Plan for it as a multi-week event with executive visibility, not a same-day recovery. This is the architectural worst-case; mitigations include the 3-server architecture (D20), Always On Availability Groups, and never being in this scenario in the first place.

---

---

## RB-9: Automatic AM/PM Failover (Automic-driven)

**When**: production server's AM (or PM) pipeline run failed, timed out, or never started. Detected by the test-environment Automic pipeline checking the gate table.

**Mechanism**: two Automic pipelines (production + test) coordinated by `General.ops.PipelineExecutionGate`. No watchdog VM, no SSH, no separate monitoring host.

**See also** (per Round 2 close-out 2026-05-10): `phase1/02_configuration.md` § 5.1 (Automic job inventory — 8 jobs frozen at Round 2; AM/PM are this runbook's scope), § 5.3 (gate-table 4-phase lifecycle contract — Round 1 canonical column names; SP-3 / SP-4 acquire path), § 5.4 (failover sequence with 15-minute cooperative-cancel window per D33). RB-9 operationalizes those specifications; if this runbook diverges from `02_configuration.md` § 5, the spec is canonical (supersede via D-number, not by editing this runbook silently).

### Schedule

| Job | Server | Time | Behavior |
|---|---|---|---|
| Pipeline AM | Production | 02:00 | Always runs |
| Pipeline AM (failover) | Test | 04:30 | Runs only if AM gate indicates prod failed |
| Pipeline PM | Production | 17:00 | Always runs |
| Pipeline PM (failover) | Test | 19:30 | Runs only if PM gate indicates prod failed |

### Gate-acquisition logic (production pipeline first step)

```sql
-- Acquire the gate for this cycle
DECLARE @cycle NVARCHAR(10) = ?;  -- 'AM' or 'PM' from Automic var
DECLARE @cycle_date DATE = CAST(SYSDATETIME() AS DATE);

DECLARE @lock INT;
EXEC @lock = sp_getapplock
    @Resource = N'pipeline_gate_' + @cycle + '_' + CONVERT(VARCHAR(10), @cycle_date, 23),
    @LockMode = 'Exclusive',
    @LockOwner = 'Session',
    @LockTimeout = 5000;
IF @lock < 0
    RAISERROR('Gate lock could not be acquired', 16, 1);

-- INSERT or UPDATE the gate
MERGE General.ops.PipelineExecutionGate AS g
USING (SELECT @cycle AS CycleType, @cycle_date AS CycleDate) AS src
ON g.CycleType = src.CycleType AND g.CycleDate = src.CycleDate
WHEN MATCHED THEN
    UPDATE SET ExecutingServer = 'production',
               Status = 'STARTING',
               ActualStartTime = SYSDATETIME(),
               BatchId = NEXT VALUE FOR General.ops.PipelineBatchSequence,
               LastHeartbeatAt = SYSDATETIME()
WHEN NOT MATCHED THEN
    INSERT (CycleType, CycleDate, ExpectedStartTime, ActualStartTime, ExecutingServer,
            Status, BatchId, LastHeartbeatAt)
    VALUES (@cycle, @cycle_date, @cycle_date + CAST('02:00' AS TIME), SYSDATETIME(),
            'production', 'STARTING', NEXT VALUE FOR General.ops.PipelineBatchSequence, SYSDATETIME());

EXEC sp_releaseapplock @Resource = N'pipeline_gate_' + @cycle + '_' + CONVERT(VARCHAR(10), @cycle_date, 23);

-- Pipeline now runs; updates Status to 'RUNNING' once extraction starts,
-- 'SUCCEEDED' or 'FAILED' on completion. Heartbeat updates LastHeartbeatAt every 5 min.
```

### Test pipeline first step (failover gate-check)

```sql
DECLARE @cycle NVARCHAR(10) = ?;  -- 'AM' or 'PM' from Automic var
DECLARE @cycle_date DATE = CAST(SYSDATETIME() AS DATE);

-- Acquire gate lock
DECLARE @lock INT;
EXEC @lock = sp_getapplock
    @Resource = N'pipeline_gate_' + @cycle + '_' + CONVERT(VARCHAR(10), @cycle_date, 23),
    @LockMode = 'Exclusive',
    @LockOwner = 'Session',
    @LockTimeout = 5000;
IF @lock < 0
    RAISERROR('Gate lock could not be acquired', 16, 1);

DECLARE @status NVARCHAR(20), @start DATETIME2(3), @heartbeat DATETIME2(3);

SELECT @status = Status, @start = ActualStartTime, @heartbeat = LastHeartbeatAt
FROM General.ops.PipelineExecutionGate
WHERE CycleType = @cycle AND CycleDate = @cycle_date;

-- Decision tree
IF @status = 'SUCCEEDED'
BEGIN
    EXEC sp_releaseapplock @Resource = N'pipeline_gate_' + @cycle + '_' + CONVERT(VARCHAR(10), @cycle_date, 23);
    PRINT 'Production succeeded; test exits cleanly';
    RETURN 0;
END;

IF @status = 'RUNNING' AND DATEDIFF(minute, @heartbeat, SYSDATETIME()) < 10
BEGIN
    EXEC sp_releaseapplock @Resource = N'pipeline_gate_' + @cycle + '_' + CONVERT(VARCHAR(10), @cycle_date, 23);
    PRINT 'Production still running with recent heartbeat; test exits';
    RETURN 0;
END;

-- Failover: prod failed, timed out, never started, or heartbeat stale
UPDATE General.ops.PipelineExecutionGate
SET ExecutingServer = 'test',
    Status = 'STARTING',
    ActualStartTime = SYSDATETIME(),
    BatchId = NEXT VALUE FOR General.ops.PipelineBatchSequence,
    LastHeartbeatAt = SYSDATETIME(),
    FailureReason = 'Auto-failover: prod ' + ISNULL(@status, 'NEVER_STARTED') 
                    + COALESCE('; last heartbeat ' + CONVERT(VARCHAR(30), @heartbeat, 121), '')
WHERE CycleType = @cycle AND CycleDate = @cycle_date;

EXEC sp_releaseapplock @Resource = N'pipeline_gate_' + @cycle + '_' + CONVERT(VARCHAR(10), @cycle_date, 23);

INSERT INTO General.ops.PipelineEventLog (EventType, Metadata, ...)
VALUES ('FAILOVER_TRIGGERED', '{"cycle":"' + @cycle + '","reason":"' + ISNULL(@status, 'NEVER_STARTED') + '"}', ...);

PRINT 'Failover claimed; test pipeline proceeds';
RETURN 1;
```

### Operator validation post-failover

```sql
-- Did the failover work?
SELECT TOP 5 * FROM General.ops.PipelineExecutionGate
WHERE ExecutingServer = 'test'
ORDER BY ActualStartTime DESC;

-- Confirm Bronze populated for all expected tables
SELECT TableName, MAX(CompletedAt) AS LastSuccess
FROM General.ops.PipelineEventLog
WHERE EventType = 'TABLE_TOTAL' AND Status = 'SUCCESS'
GROUP BY TableName
ORDER BY LastSuccess;

-- Run gap detector
EXEC tools_detect_extraction_gaps;
```

### What happens on the next cycle if prod is back

- Production Automic runs at 02:00 (next AM)
- Tries to acquire the gate for new (CycleType, CycleDate)
- That row doesn't exist yet (prior cycle's row is for prior date) → INSERTs cleanly
- Runs to completion normally
- Test Automic at 04:30 reads gate, sees `SUCCEEDED`, exits

### What happens if prod is still down

- Production Automic at 02:00 fails (server down)
- No row inserted in `PipelineExecutionGate`
- Test Automic at 04:30 reads gate, finds no row → triggers failover
- Test runs to completion
- This continues each cycle until prod is restored
- After 24h continuous failover: alert fires for full RB-2 manual review

### Cutback

No explicit cutback action needed. As soon as prod is restored, the next cycle's prod Automic acquires the gate normally and test exits cleanly. Failover is per-cycle, not sticky.

### Cancellation of stuck production (D33)

When test detects prod is stuck (heartbeat stale, status RUNNING with no progress), test must cancel prod before claiming the gate.

**Test pipeline cancellation flow**:

```sql
-- Step 1: request cancellation
DECLARE @cycle NVARCHAR(10) = ?;
DECLARE @cycle_date DATE = CAST(SYSDATETIME() AS DATE);

UPDATE General.ops.PipelineExecutionGate
SET CancellationRequested = 1,
    CancellationRequestedAt = SYSDATETIME(),
    CancellationRequestedBy = 'test_failover',
    CancellationReason = 'Production heartbeat stale; test failover initiated'
WHERE CycleType = @cycle AND CycleDate = @cycle_date;

-- Step 2: poll for acknowledgment (max 15 min)
DECLARE @start DATETIME2(3) = SYSDATETIME();
DECLARE @ack DATETIME2(3) = NULL;
DECLARE @final_status NVARCHAR(20) = NULL;

WHILE DATEDIFF(minute, @start, SYSDATETIME()) < 15 AND @ack IS NULL
BEGIN
    SELECT @ack = CancellationAcknowledgedAt,
           @final_status = Status
    FROM General.ops.PipelineExecutionGate
    WHERE CycleType = @cycle AND CycleDate = @cycle_date;
    
    IF @final_status = 'SUCCEEDED'
    BEGIN
        -- Production finished naturally between cancellation request and timeout
        PRINT 'Production completed before cancellation acknowledged; test exits.';
        RETURN 0;
    END;
    
    IF @ack IS NOT NULL
        BREAK;  -- Cancellation acknowledged; proceed
    
    WAITFOR DELAY '00:00:30';  -- Poll every 30 seconds
END;

IF @ack IS NULL
BEGIN
    -- Timeout — production did not acknowledge
    INSERT INTO General.ops.PipelineLog
        (LogLevel, Module, Message, Metadata, CycleType, CycleDate)
    VALUES
        ('CRITICAL', 'failover_runbook',
         'Production did not acknowledge cancellation within 15 min — manual intervention required',
         '{"cycle":"' + @cycle + '","timeout_min":15}', @cycle, @cycle_date);
    
    -- Send alert (out-of-band; via tools/alert_dispatcher.py)
    -- DO NOT proceed; operator must decide
    RAISERROR('Production cancellation timeout; manual intervention required', 16, 1);
END;

-- Step 3: cancellation acknowledged; claim the gate
PRINT 'Production cancelled; test failover proceeds.';
-- ... continue with normal test failover gate-claim logic
```

**Production pipeline cancellation check** (every heartbeat, every 5 min during run):

```python
# In the pipeline's main loop, before processing each table
def check_cancellation():
    with cursor_for(GENERAL_DB) as cur:
        cur.execute("""
            SELECT CancellationRequested 
            FROM General.ops.PipelineExecutionGate
            WHERE GateId = ?
        """, gate_id)
        row = cur.fetchone()
        
        if row and row.CancellationRequested:
            logger.critical(
                "Cancellation requested by %s — initiating graceful shutdown",
                cancellation_requested_by,
                extra={"layer": "gate", "cancellation": True}
            )
            return True
    return False

def heartbeat():
    with cursor_for(GENERAL_DB) as cur:
        cur.execute("""
            UPDATE General.ops.PipelineExecutionGate
            SET LastHeartbeatAt = SYSDATETIME()
            WHERE GateId = ?
        """, gate_id)

def graceful_shutdown():
    # Release sp_getapplocks
    release_all_table_locks()
    
    # Flush logs
    flush_log_buffer()
    
    # Update gate
    with cursor_for(GENERAL_DB) as cur:
        cur.execute("""
            UPDATE General.ops.PipelineExecutionGate
            SET Status = 'CANCELLED',
                CancellationAcknowledgedAt = SYSDATETIME(),
                ActualCompletionTime = SYSDATETIME()
            WHERE GateId = ?
        """, gate_id)
    
    # Exit
    sys.exit(0)

# Pipeline main loop
for table in tables_to_process:
    heartbeat()
    if check_cancellation():
        graceful_shutdown()
        break
    process_table(table)
```

**What "graceful" means**:
- Finish current table (don't interrupt mid-table — partial state is harder to recover)
- Skip remaining tables in the run
- Release `sp_getapplock` on each table
- Flush log buffer (so the cancellation event is durable)
- Update gate Status='CANCELLED'
- Exit with code 0 (graceful, not failure)

**Why no force-kill path**: see D33 rationale. Stuck-but-not-dead is rare; operator awareness is the right outcome.

---

---

## RB-10: CCPA / CPRA Right-to-Deletion Request

**When**: a customer (or authorized agent) requests deletion of their personal information under California Consumer Privacy Act (CCPA) / California Privacy Rights Act (CPRA).

### Authorization gate

```
1. Verify the request is legitimate via the company's customer-identity verification process
   (separate from this runbook)
2. Capture verified consumer identity in CcpaDeletionLog
3. File request with unique RequestId (UUID)
```

### Identification

```sql
-- 1. Find every token associated with the consumer's PII identifiers
-- (assuming we have plaintext SSN, email, account numbers from verified request)
DECLARE @request_id UNIQUEIDENTIFIER = NEWID();

INSERT INTO General.ops.CcpaDeletionLog 
    (RequestId, RequestedAt, RequestedBy, SubjectIdentifier, AffectedTokens, Action)
VALUES
    (@request_id, SYSUTCDATETIME(), 
     'authorized_operator',
     '<encrypted subject reference>',
     '<TBD>',
     'pending');

-- 2. Find all tokens for the consumer's identifiers (across all sources)
DECLARE @ssn_hash VARBINARY(32) = HASHBYTES('SHA2_256', '<plaintext_ssn>');
DECLARE @email_hash VARBINARY(32) = HASHBYTES('SHA2_256', '<plaintext_email>');

WITH affected_tokens AS (
    SELECT Token, PiiType, SourceName, LegalHold
    FROM General.ops.PiiVault
    WHERE PlaintextHash IN (@ssn_hash, @email_hash, /* other identifiers */)
)
SELECT * FROM affected_tokens;
-- Capture results for the deletion log
```

### Legal hold check

```sql
-- For each affected token, check legal hold status
SELECT Token, LegalHold, LegalHoldReason, LegalHoldReference
FROM General.ops.PiiVault
WHERE Token IN (<affected token list>);

-- If ANY token has LegalHold=1:
--   Action becomes 'partial' or 'legal_hold_override'
--   Customer must be notified per CCPA of the legal exception
--   Reason and reference documented
```

### Deletion execution

```sql
-- For tokens NOT under legal hold, flip Status to 'deleted_per_request'
-- This is crypto-shredding equivalent: tokens in Bronze become orphan references,
-- effectively forgotten. We do NOT physically scrub Bronze rows (preserves audit trail).
BEGIN TRANSACTION;

UPDATE General.ops.PiiVault
SET Status = 'deleted_per_request',
    StatusReason = 'CCPA right-to-deletion request ' + CAST(@request_id AS VARCHAR(40)),
    StatusChangedAt = SYSUTCDATETIME(),
    StatusChangedBy = SYSTEM_USER
WHERE Token IN (<non-legal-hold tokens>)
  AND LegalHold = 0;

UPDATE General.ops.CcpaDeletionLog
SET AffectedTokens = '<JSON list>',
    Action = CASE WHEN <any legal hold> THEN 'partial' ELSE 'deleted' END,
    LegalExceptionReason = '<concatenated legal hold reasons or NULL>',
    ProcessedAt = SYSUTCDATETIME(),
    ProcessedBy = SYSTEM_USER
WHERE RequestId = @request_id;

COMMIT TRANSACTION;
```

### Customer notification

CCPA requires notification within 45 days of the request:
- Confirm deletion executed for non-legal-hold tokens
- Disclose any legal exceptions invoked (with the legal basis per CCPA section 1798.105)
- Document the notification (out-of-scope for pipeline; handled by customer service team)

### Audit verification

```sql
-- Verify no residual access path to plaintext for deleted tokens
SELECT t.Token, p.PlaintextValue
FROM <token list> t
LEFT JOIN General.ops.PiiVault p ON t.Token = p.Token
WHERE p.Status = 'active';
-- Should return zero rows for deleted tokens
```

### Related: tokens reappear in source

If the source system still holds the consumer's data and the next pipeline run re-tokenizes it, the lookup-before-insert pattern returns the SAME token (deterministic). The existing vault row's Status remains `'deleted_per_request'`. The source data was not deleted from source — that's a separate process. Document for the customer that source-side deletion is required for full erasure.

---

## RB-11: 7-Year Retention Enforcement

**When**: monthly automated job. Manual invocation for one-shot retention runs.

### Tooling

`tools/enforce_retention.py` performs three steps:

```python
# 1. Identify vault rows past RetentionExpiresAt without legal hold
expired = SELECT * FROM PiiVault 
          WHERE RetentionExpiresAt < SYSUTCDATETIME() 
            AND LegalHold = 0
            AND Status = 'active';

# 2. Flip Status; never physically DELETE
UPDATE PiiVault
SET Status = 'purged_for_retention',
    StatusReason = '7-year retention expired',
    StatusChangedAt = SYSUTCDATETIME(),
    StatusChangedBy = 'retention_job'
WHERE Token IN (<expired token list>);

# 3. Identify Bronze SCD2 versions older than 7 years for archival
# (Bronze archival to Parquet is a separate, slower operation; this job only flags)
```

### Manual override

```bash
# Suppress retention for a specific token (emergency legal hold)
python3 tools/enforce_retention.py --apply-legal-hold \
    --token X --reason "Litigation hold case #12345" --reference "case-12345"

# Force retention check on demand (e.g., end-of-quarter audit)
python3 tools/enforce_retention.py --run-now --since 2024-01-01

# Dry run to preview what would change
python3 tools/enforce_retention.py --dry-run
```

### Validation

- Monthly retention report committed to audit log
- Sample 50 random tokens flipped this month; verify Status, StatusReason, StatusChangedAt populated
- Verify zero `LegalHold = 1` tokens were flipped
- Power BI dashboard tracks: total active, total deleted_per_request, total purged_for_retention, total legal_hold_only

---

## RB-12: Pipeline Deployment

**Added**: 2026-05-11 (Round 6 retroactive close-out per Pattern F Phase B). Closes B41 + B127.

**Cross-references**: D84 (deployment artifact contract) + D85 (module startup sequence) + D86 (3-env cadence) + D87 (pre/post-deploy checklist contract) + `phase1/06_deployment.md` § 1.2 + § 1.4 + § 1.5 + § 1.6 + § 9.

### When to use

- Scheduled deploys per D86 cadence:
  - dev: nightly auto-cron at 02:00 dev-server local
  - test: daily auto-cron after dev smoke pass + 4-hour soak
  - prod: weekly auto-cron Monday 02:00-05:00 after test soak (168h all-green) + pipeline-lead manual sign-off
- Emergency hotfix (with explicit operator + pipeline-lead sign-off)
- Rollback (per § 3 below — reverse mode)

### Pre-flight (12 checks per § 1.6 pre-deployment checklist; ALL must pass)

1. Source git tag exists on remote + GPG-signed by authorized committer
2. Target server reachable (ssh + sudo); systemctl status reachable
3. Target server has ≥1.5x required disk free for `/opt/pipeline/<new_tag>/`
4. Target server has ≥8GB free memory
5. Target server is NOT mid-pipeline-run (`PipelineExecutionGate` Status NOT IN ('STARTING','RUNNING') per Round 1 schema L328-330)
6. Target environment NOT in maintenance window (`MaintenanceWindow` table — Round 1 schema)
7. Prior tag retained at `/opt/pipeline/<prior_tag>/` (rollback target)
8. Parity baseline at `/etc/pipeline/parity_baseline.json` ≤90 days old
9. GPG envelope at `/etc/pipeline/credentials.json.gpg` ≤90 days old; TPM2 PCR set unchanged since envelope sealed
10. CI Tier 0+1+2 green on the source tag's commit (per Round 5 § 1.4)
11. CI Tier 3 (integration) green within last 24h
12. Operator (`--actor`) supplied + justification (`--justification`) supplied per D75

Failed pre-check → ABORT deploy; write `EventType='DEPLOYMENT_<ENV>'` row with `Status='FAILED'` + `Metadata.failed_check` enumerating which check; do NOT proceed.

### Procedure (per § 1.4 + D84 atomic symlink-swap workflow)

```
# Engineering workstation
git tag -a v<N>.<N>.<N>-<env> -m "<description>"
git push origin v<N>.<N>.<N>-<env>

# CI builds + signs manifest
git archive --format=tar v<N>.<N>.<N>-<env> | gzip > pipeline-<tag>.tar.gz
cd /tmp && tar -xzf pipeline-<tag>.tar.gz
find . -type f -exec sha256sum {} \; > MANIFEST.sha256
gpg --detach-sign --armor MANIFEST.sha256

# Target server (per env; orchestrated via ssh from CI runner)
mkdir -p /opt/pipeline/<new_tag>
rsync -av --delete /tmp/pipeline-<new_tag>/ /opt/pipeline/<new_tag>/
cd /opt/pipeline/<new_tag>
sha256sum -c MANIFEST.sha256          # FAIL → ABORT (pre-symlink)
gpg --verify MANIFEST.sha256.asc      # FAIL → ABORT (pre-symlink)

# Atomic symlink swap per D84 (single rename(2) syscall)
ln -s /opt/pipeline/<new_tag> /opt/pipeline/current.new
mv -T /opt/pipeline/current.new /opt/pipeline/current

sudo systemctl restart pipeline.service  # § 1.7 startup sequence runs
```

### Validation (10 post-deployment checks per § 1.6; ALL must pass)

1. `systemctl status pipeline.service` shows active
2. `/opt/pipeline/current` symlink points to `<new_tag>`
3. `tools/verify_server_parity.py` returns `overall='pass'` OR documented exceptions match per § 3.6
4. Tier 0 smoke (`pytest tests/smoke/`) returns 28 of 28 green per § 5.1 — exit 0
5. First synthetic pipeline run (`python3 main_small_tables.py --source TEST --table SYNTHETIC_PILOT --dry-run`) completes end-to-end with zero crashes per § 5.6
6. `IdempotencyLedger` has no stale `IN_PROGRESS` rows (cleaned by startup sweep per § 1.7 Stage 4)
7. `PipelineExecutionGate` accepts new INSERT (sp_getapplock acquirable per SP-3)
8. Module startup sequence completed all 5 stages (audit-log rows for `CREDS_LOAD` + `VAULT_CONFIG` + `PARITY_CHECK` + `LEDGER_SWEEP` + `ORCHESTRATION_START` per STARTUP_* family in CLAUDE.md)
9. No CRITICAL log entries in `PipelineLog` within first 5 min post-restart
10. Soak period elapsed without operator alerts (4h for test; 24h for prod)

Failed post-check → ROLLBACK per § 3 decision matrix.

### Rollback (per § 1.5 decision matrix)

**AUTO-ROLLBACK conditions** (no operator deliberation; symlink revert fires immediately):
- `tools/verify_server_parity.py` FATAL severity at startup
- First synthetic pipeline run fails (any module crashes)
- Tier 0 smoke fails post-deploy

**MANUAL-ROLLBACK conditions** (pipeline-lead decides):
- Latency regression > 2× baseline (per `tools/lateness_profile.py`)
- Memory regression > 50% baseline (per RSS monitor + B-8)
- Specific table extraction failure (operator alert via `tools/alert_dispatcher.py`)

**Rollback procedure** (≤5 minutes from decision to operational state):

```
# Pipeline lead authorizes (any prod rollback requires lead sign-off)

# Symlink revert (single rename(2) per D84 — atomic)
ln -s /opt/pipeline/<prior_tag> /opt/pipeline/current.new
mv -T /opt/pipeline/current.new /opt/pipeline/current

sudo systemctl restart pipeline.service

# Verify rollback succeeded
pytest tests/smoke/  # against <prior_tag>; must be all green

# Audit row
# `EventType='DEPLOYMENT_ROLLBACK'` written with Metadata.prior_tag + Metadata.failed_tag + Metadata.failure_reason

# Mark failed tag for forensics
touch /opt/pipeline/<failed_tag>/.failed   # do NOT auto-delete; retain for postmortem
```

### Recovery from Stage-N failure

If § 1.7 module startup fails at any stage, the systemd unit restarts up to 3 times (per `Restart=on-failure, RestartSec=30s, StartLimitInterval=3min, StartLimitBurst=3`). After 3 failed restarts, systemd enters `failed` state and alerts.

Operator workflow:
```
1. systemctl status pipeline.service           → check failure stage from journal
2. Query PipelineEventLog for startup events (CREDS_LOAD / VAULT_CONFIG / PARITY_CHECK /
   LEDGER_SWEEP / ORCHESTRATION_START)         → identify failed stage
3. Stage 1 fail (CredentialsLoadError):
   - run tools/verify_server_parity.py + check GPG envelope SHA + TPM2 PCR set
   - resolve drift OR proceed to § 5 (TPM2 re-seal)
4. Stage 3 fail (ParityFatalError):
   - run tools/verify_server_parity.py standalone
   - identify mismatch tier; resolve fatal-tier first
5. Stage 4 fail (DB unreachable):
   - check IdempotencyLedger connectivity
   - clear stale IN_PROGRESS rows manually if needed
6. If unresolvable                              → ROLLBACK per § 3
```

### TPM2 re-seal procedure (Stage 1 failure due to PCR set drift)

When `tools/verify_server_parity.py` reports `envelope_sha256` drift OR Stage 1 fails on TPM2 unseal:

```
1. Confirm intended kernel/firmware change happened (Stage 1 failure may be benign)
2. Tear down old TPM2 sealed key:
   tpm2_evictcontrol -C o -c <persistent_handle>
3. Re-seal passphrase against current PCR set:
   tpm2_createpolicy --policy-pcr -l sha256:0,2,4,7 --policy-pcr-out policy.dat
   echo -n "<passphrase>" | tpm2_create -C primary.ctx -P "<owner_pw>" -i - \
                                          -L policy.dat -u key.pub -r key.priv
   tpm2_load -C primary.ctx -u key.pub -r key.priv -c key.ctx
   tpm2_evictcontrol -C o -c key.ctx <new_persistent_handle>
4. Update /etc/pipeline/parity_baseline.json with new PCR values
5. Re-run tools/verify_server_parity.py  → must return 'pass'
6. Re-run module startup sequence       → Stage 1 should succeed
```

### Forensic retention

Failed tags retained at `/opt/pipeline/<failed_tag>/` with `.failed` marker file. Do NOT auto-delete. Retain ≥30 days for postmortem investigation. Pipeline-lead approves deletion after postmortem completes.

### Audit trail

Every deploy + rollback writes ONE `PipelineEventLog` row per D87 contract:
- `EventType='DEPLOYMENT_<ENV>'` or `'DEPLOYMENT_ROLLBACK'`
- `Status` ∈ ('IN_PROGRESS','SUCCESS','FAILED','SKIPPED') per Round 1 schema L143-144
- `Metadata` JSON: tag, prior_tag, actor, justification, pre_check_results, post_check_results, soak_duration_minutes, deploy_started_at, deploy_completed_at, soak_completed_at

Query post-deploy:
```sql
SELECT TOP 10 EventType, Status, StartedAt, Metadata
FROM General.ops.PipelineEventLog
WHERE EventType LIKE 'DEPLOYMENT_%'
ORDER BY StartedAt DESC;
```

---

## RB-13 — Permanent-Retire Table (closes B168)

**Status**: 🟡 Draft (authored 2026-05-11 at Round 1.5 backlog-batch closure; first test deploy in Phase 4 cohort retirement).

### When to use

A source table is permanently retired from the pipeline. Common triggers:
- Source system decommissions the table
- Consumer teams confirm no downstream queries against the Bronze table for ≥ 90 days
- Compliance approves data retention conclusion for the table's classification (PII / PCI / none)
- Phase 4+ cohort retirement plans

**NOT for**: temporary pauses (use `UdmTablesList.IsEnabled = 0` per `phase1/01a_control_tables.md` § 5.2); operational issues (use ad-hoc recovery); per-row CCPA deletion (use RB-10).

### Pre-flight

- [ ] **Consumer-team sign-off**: no downstream queries against `UDM_Bronze.{SourceName}.{TableName}_scd2_python` in last 90 days
- [ ] **Compliance sign-off**: data retention obligation satisfied per `DataClassification` (PII: 7 years per D30; PCI: per GLBA; none: 7-year default)
- [ ] **Source-system confirmation**: source DBA confirms decommissioning
- [ ] **Disable + cool-down**: `UdmTablesList.IsEnabled = 0` for ≥ `ExpectedRetentionDays` (or 90 days default)
- [ ] **Verify no in-flight runs**: `PipelineExecutionGate.Status IN ('STARTING','RUNNING')` zero for runs touching this table in last 24h
- [ ] **Backup verification**: Parquet snapshots in cold-tier have valid checksums (`ParquetSnapshotRegistry.LastVerifiedAt > NOW - 90 days`)
- [ ] **Capture final BatchId**: record last BatchId that wrote to Bronze
- [ ] **Pipeline-lead authorization**: explicit go-ahead documented in `ManualCorrectionLog`

### Procedure

```sql
-- ⚠️ Permanent retirement is irreversible after the DROP TABLE step below. Confirm all pre-flight checks.

BEGIN TRANSACTION;

-- Step 1: Audit row for the retirement event
INSERT INTO General.ops.ManualCorrectionLog 
    (BatchId, SourceName, TableName, CorrectionType, Description, Actor, Justification, CorrectedAt)
VALUES (NULL, @SourceName, @TableName, 'TABLE_RETIREMENT',
        CONCAT('Permanent retirement per RB-13; final BatchId before retirement = ', @FinalBatchId),
        @PipelineLeadIdentity, @JustificationFromSignoffDocument, SYSUTCDATETIME());

-- Step 2: Snapshot OrphanedTokenLog for any vault rows referenced ONLY by this Bronze table
-- (Repeat per PII column listed in UdmTablesList.PiiColumnList)
INSERT INTO General.ops.OrphanedTokenLog 
    (Token, OrphanedAt, OrphanReason, OrphanReference, DownstreamSummary, TotalDownstreamRows, Status)
SELECT v.Token, SYSUTCDATETIME(), 'manual_override',
       CONCAT('RB-13 retirement of ', @SourceName, '.', @TableName),
       (SELECT @SourceName AS db, @TableName AS table_name FOR JSON PATH),
       (SELECT COUNT(*) FROM <Bronze table> WHERE <PII column> = v.Token),
       'logged'
FROM General.ops.PiiVault v
WHERE v.Token IN (SELECT DISTINCT <PII column> FROM <Bronze table>);

-- Step 3: Mark UdmTablesList row retired (StageLoadTool = NULL = permanent skip)
UPDATE General.dbo.UdmTablesList
SET StageLoadTool = NULL,  -- per Round 2 § 1.1.1: NULL = permanent skip (distinct from IsEnabled = 0 transient)
    IsEnabled = 0
WHERE SourceName = @SourceName AND SourceObjectName = @SourceObjectName;

COMMIT;
```

### Validation

After commit:
- [ ] Next pipeline run does NOT pick up the retired table
- [ ] `ManualCorrectionLog` row queryable by `Actor` + `CorrectedAt`
- [ ] `OrphanedTokenLog` rows present for all previously-referenced PII tokens
- [ ] Bronze + Stage tables remain queryable (NOT yet dropped — DBA action separate)

### Operator-driven table DROP (separate procedure)

After ≥ `ExpectedRetentionDays` (or 7 years per D30 default):

```sql
-- ⚠️ Destructive. DBA-only. Audit BEFORE drop.
INSERT INTO General.ops.ManualCorrectionLog (...)
VALUES (..., 'TABLE_DROP', 
        CONCAT('Final Bronze row count: ', (SELECT COUNT(*) FROM <Bronze table>),
               '; final Stage row count: ', (SELECT COUNT(*) FROM <Stage table>),
               '; retention satisfied per RB-13 + D30'), ...);

DROP TABLE UDM_Bronze.{SourceName}.{TableName}_scd2_python;
DROP TABLE UDM_Stage.{SourceName}.{TableName}_cdc;

-- Optional, after audit-grade trail confirmed:
DELETE FROM General.dbo.UdmTablesColumnsList WHERE SourceName = @SourceName AND TableName = @TableName;
DELETE FROM General.dbo.UdmTablesList WHERE SourceName = @SourceName AND SourceObjectName = @SourceObjectName;
```

### Rollback

If consumer-team or compliance objection surfaces BEFORE DROP TABLE:
- `UPDATE UdmTablesList SET IsEnabled = 1, StageLoadTool = 'Python' WHERE ...` reactivates extraction
- `OrphanedTokenLog` rows remain (audit trail); operator notes reactivation in `ManualCorrectionLog` as `CorrectionType = 'TABLE_RETIREMENT_REVERSED'`
- Bronze + Stage tables still queryable

After DROP TABLE: rollback requires full re-extraction from source (per RB-8 Bronze rebuild from Parquet) AND legal review of any retention obligations violated.

### Cross-references

- D30 (7-year retention with legal hold) + D34 (greenfield) + D45 (idempotency) + D92 (forward-only)
- `phase1/01a_control_tables.md` § 5.4 (lifecycle context) + `phase1/01b_bronze_stage_example_ddl.md` § 4
- RB-8 (Bronze rebuild from Parquet) + RB-10 (CCPA right-to-deletion) + RB-11 (7-Year Retention Enforcement)

### Owner

Pipeline lead. DBA executes DROP TABLE. Compliance + consumer-team sign-off mandatory.

---

## RB-14 — `.env` Location Migration (`/debi/.env` → `/etc/pipeline/.env`)

**Status**: 🟡 Draft (authored 2026-05-11 at Phase 0 prep close to close B182; first production deploy is the Phase 2 pilot cutover prerequisite — pipeline cannot deploy with credentials inside `/debi` per D103).

### When to use

**One-time migration** to move the `.env` credential file out of the Claude Code working directory (`/debi`) to the system-managed canonical location (`/etc/pipeline/.env`) per D103. Run this once per server (dev / test / prod) BEFORE the next pipeline deploy after 2026-05-11.

**NOT for**: routine `.env` value changes (those are operational config — edit in place, no migration); credential rotation (use the rotation procedures in RB-4 / RB-6 / RB-10 for vault-managed secrets, or rotate-and-redeploy for .env-resident values).

### Why this matters (per D103)

The `.env` file contains plaintext database connection strings, the TPM2 unseal reference for the GPG passphrase, Snowflake account identifiers, and other secrets needed at pipeline startup. Storing it inside `/debi` means Claude Code (which operates with `/debi` as its working-directory boundary) has architectural read access. The D103 model moves all credentials OUTSIDE `/debi` so Claude has zero authorized read path. Mode `0400` + ownership `pipeline:pipeline` on `/etc/pipeline/.env` is Layer 6 of the 13-layer defense; the architectural boundary (Layer 1) is what this runbook enforces.

### Pre-flight

- [ ] **Pipeline NOT actively running**: `PipelineExecutionGate.Status IN ('STARTING','RUNNING')` returns zero rows for the last hour; no AM/PM cycle in flight
  ```sql
  SELECT * FROM General.ops.PipelineExecutionGate
  WHERE Status IN ('STARTING','RUNNING')
    AND HeartbeatAt > DATEADD(hour, -1, SYSUTCDATETIME());
  -- Must return 0 rows
  ```
- [ ] **Operator has root or sudo on the target server** (`sudo -nv` returns no error)
- [ ] **TPM2 unseal verified working** on the target server BEFORE migration — confirms credentials can still be loaded post-move:
  ```bash
  # Verify TPM2 + GPG envelope decryption end-to-end (do NOT print passphrase)
  # NOTE: tools/verify_credentials_load.py spec is ⚫ CLOSED via Round 4.5 supplement at phase1/04a_phase_0_prep_tools.md § 3 (B184 closed 2026-05-11; implementation lands at Phase 2 R1)
  sudo -u pipeline /opt/pipeline/current/tools/verify_credentials_load.py \
      --require ORACLE_PASSWORD,MSSQL_PASSWORD,SNOWFLAKE_PRIVATE_KEY_PEM \
      --actor pipeline
  # Expected: "✅ Credentials envelope decrypted; required keys present (3/3); optional keys present (M/M)"
  # If Tool 12 implementation has not yet landed (pre-P2R1), the operator-equivalent inline call is:
  #   sudo -u pipeline /opt/pipeline/current/bin/python3 -c \
  #     "from data_load.credentials_loader import load_credentials; \
  #      d = load_credentials(envelope_path='/etc/pipeline/credentials.json.gpg', \
  #                          passphrase_source='env', passphrase_file_path=None); \
  #      required = {'ORACLE_PASSWORD','MSSQL_PASSWORD','SNOWFLAKE_PRIVATE_KEY_PEM'}; \
  #      missing = required - set(d.keys()); \
  #      print('OK' if not missing else f'MISSING: {sorted(missing)}')"
  # The CLI shim adds proper exit codes (per D74) and the PipelineEventLog audit row (per D76).
  ```
- [ ] **Existing `/debi/.env` exists and is readable**:
  ```bash
  sudo -u pipeline test -r /debi/.env && echo "OK: readable" || echo "MISSING — investigate before proceeding"
  ```
- [ ] **Backup of `/debi/.env` taken** to operator-only location (NOT to `/debi/`, NOT to a shared drive):
  ```bash
  sudo cp /debi/.env /root/env_backup_$(hostname)_$(date +%Y%m%d_%H%M%S).bak
  sudo chmod 0400 /root/env_backup_*.bak
  ```
- [ ] **`pipeline:pipeline` user/group exists**:
  ```bash
  id pipeline && getent group pipeline
  ```
- [ ] **`/etc/pipeline/` does NOT already exist with conflicting content** (fresh server) OR is empty:
  ```bash
  sudo test ! -e /etc/pipeline/ || sudo ls -la /etc/pipeline/  # confirm empty
  ```
- [ ] **SELinux mode confirmed** (`Enforcing` per D103 Layer 11): `sestatus | grep "Current mode"` shows `enforcing`
- [ ] **Pipeline-lead authorization** documented (this is a credential-touching operation):
  ```sql
  INSERT INTO General.ops.ManualCorrectionLog
      (BatchId, SourceName, TableName, CorrectionType, Description, Actor, Justification, CorrectedAt)
  VALUES (NULL, NULL, NULL, 'ENV_MIGRATION_AUTHORIZATION',
          'Pre-migration auth for RB-14 .env relocation on host ' + HOST_NAME(),
          SUSER_SNAME(), @JustificationDocLink, SYSUTCDATETIME());
  ```

### Procedure

```bash
# ⚠️ Run as root (or with sudo) directly on the target server.
# ⚠️ Do NOT pipe .env content through any tool — operate by mv/cp/chmod only.

set -euo pipefail

# Step 1: Create the canonical directory
sudo mkdir -p /etc/pipeline
sudo chown root:pipeline /etc/pipeline
sudo chmod 0750 /etc/pipeline
# Verify: drwxr-x--- root pipeline /etc/pipeline

# Step 2: Move (not copy) the .env to the new location
sudo mv /debi/.env /etc/pipeline/.env
# After mv, /debi/.env no longer exists; /etc/pipeline/.env owned by current invoking user

# Step 3: Set canonical ownership + mode
sudo chown pipeline:pipeline /etc/pipeline/.env
sudo chmod 0400 /etc/pipeline/.env
# Verify: -r-------- pipeline pipeline /etc/pipeline/.env

# Step 4: Apply SELinux context (per D103 Layer 11)
# .env should inherit the standard etc_t context; verify after move
sudo restorecon -v /etc/pipeline/.env
ls -lZ /etc/pipeline/.env
# Expected context: system_u:object_r:etc_t:s0 (or pipeline_conf_t if custom policy in place)

# Step 5: Update auditd watch rules (per D103 Layer 9)
# Append the new path to the audit rules file
sudo tee -a /etc/audit/rules.d/pipeline-secrets.rules > /dev/null <<'EOF'
-w /etc/pipeline/.env -p rwxa -k pipeline_secrets
-w /etc/pipeline/credentials.json.gpg -p rwxa -k pipeline_secrets
EOF
# Remove the legacy /debi/.env watch if present
sudo sed -i '/-w \/debi\/\.env /d' /etc/audit/rules.d/pipeline-secrets.rules || true
# Reload auditd
sudo augenrules --load
sudo systemctl restart auditd
# Verify the new watch is active
sudo auditctl -l | grep /etc/pipeline/.env

# Step 6: Update the pipeline's config.py to read from the new path
# (Code change is part of B182 deliverable; verify the deployed version is post-migration)
grep -n "ENV_PATH" /opt/pipeline/current/config.py
# Expected: ENV_PATH = "/etc/pipeline/.env"  (NOT "/debi/.env")
# If pre-migration code is still deployed, abort here and re-deploy first.

# Step 7: Smoke test — verify the pipeline can still load credentials from the new path
sudo -u pipeline /opt/pipeline/current/bin/python3 \
    /opt/pipeline/current/main_small_tables.py \
    --table ACCT --source DNA --dry-run
# Expected: exit code 0; PipelineEventLog gains 1 STARTUP_CREDS_LOAD event with Status='SUCCESS'

# Step 8: Verify Claude Code permission denial still active (sanity check Layer 3)
# Run from a Claude Code session on the dev workstation only:
#   Read("/etc/pipeline/.env")  →  expected: permission denied by .claude/settings.local.json
# DO NOT actually attempt this in production sessions; the deny rule is preventive.

# Step 9: Confirm /debi/.env is gone
sudo test ! -e /debi/.env && echo "OK: legacy path cleared" || echo "FAIL: /debi/.env still present"

# Step 10: Audit-row for completion
# (Run from a SQL Server cursor — pipeline lead or DBA identity)
```

```sql
INSERT INTO General.ops.ManualCorrectionLog
    (BatchId, SourceName, TableName, CorrectionType, Description, Actor, Justification, CorrectedAt)
VALUES (NULL, NULL, NULL, 'ENV_MIGRATION_COMPLETE',
        CONCAT('RB-14 .env migrated /debi/.env → /etc/pipeline/.env on host ', HOST_NAME(),
               '; mode 0400 pipeline:pipeline; SELinux context restored; auditd watch updated; ',
               'verify_credentials_load smoke test passed; closes B182'),
        SUSER_SNAME(), 'D103 architectural-boundary enforcement', SYSUTCDATETIME());
```

### Validation

```
1. Mode + ownership confirmed:
   sudo stat -c '%a %U:%G' /etc/pipeline/.env
   # Expected: 400 pipeline:pipeline

2. Pipeline starts cleanly from the new location:
   SELECT TOP 1 EventType, Status, StartedAt, Metadata
   FROM General.ops.PipelineEventLog
   WHERE EventType = 'STARTUP_CREDS_LOAD'
   ORDER BY StartedAt DESC;
   # Expected: Status='SUCCESS'; StartedAt > migration time;
   # Metadata JSON includes "env_path": "/etc/pipeline/.env"

3. auditd captures access events (run a deliberate read; should NOT trigger an alert because pipeline is authorized):
   sudo -u pipeline cat /etc/pipeline/.env > /dev/null
   sudo ausearch -k pipeline_secrets --start recent
   # Expected: one syscall=openat record; auid=pipeline

4. No reads from the legacy path post-migration (verify zero auditd hits for /debi/.env):
   sudo ausearch -k pipeline_secrets --start recent | grep "/debi/.env"
   # Expected: no results

5. Claude Code permission deny rule in effect on the dev workstation:
   # In .claude/settings.local.json `permissions.deny` array, confirm:
   grep '"/etc/pipeline/' .claude/settings.local.json
   # Expected: Read(/etc/pipeline/**) and Read(/etc/pipeline/.env) present

6. CLAUDE.md no longer cites legacy path as canonical:
   grep -n "/debi/.env" CLAUDE.md
   # Expected: zero hits OR hits explicitly labeled "legacy/deprecated"

7. Audit-row queryable:
   SELECT * FROM General.ops.ManualCorrectionLog
   WHERE CorrectionType IN ('ENV_MIGRATION_AUTHORIZATION','ENV_MIGRATION_COMPLETE')
     AND CorrectedAt > DATEADD(day, -1, SYSUTCDATETIME())
   ORDER BY CorrectedAt;
```

### Rollback

If the smoke test in Step 7 FAILS (pipeline cannot load credentials from new path):

```bash
# 1. Move the .env back to the legacy location (the file itself is untouched; only location moved)
sudo mv /etc/pipeline/.env /debi/.env
sudo chown pipeline:pipeline /debi/.env
sudo chmod 0400 /debi/.env

# 2. Restore SELinux context on legacy path
sudo restorecon -v /debi/.env

# 3. Roll back config.py to the pre-migration commit
cd /opt/pipeline/current && sudo -u pipeline git checkout <pre-migration-tag> -- config.py

# 4. Retry the smoke test against legacy path
sudo -u pipeline /opt/pipeline/current/bin/python3 \
    /opt/pipeline/current/main_small_tables.py \
    --table ACCT --source DNA --dry-run

# 5. Audit-row the rollback
```

```sql
INSERT INTO General.ops.ManualCorrectionLog
    (BatchId, SourceName, TableName, CorrectionType, Description, Actor, Justification, CorrectedAt)
VALUES (NULL, NULL, NULL, 'ENV_MIGRATION_ROLLBACK',
        CONCAT('RB-14 rollback on host ', HOST_NAME(), '; reason: ', @FailureMode,
               '; original /debi/.env restored; B182 remains open'),
        SUSER_SNAME(), @InvestigationNotes, SYSUTCDATETIME());
```

**Reversibility**: fully reversible BEFORE the legacy path is purged from the system. After Step 9 confirms `/debi/.env` is gone AND a pipeline run has successfully completed against the new path, treat the migration as locked-in (the operator backup at `/root/env_backup_*.bak` remains the only restore path).

### Known issues + follow-ups

- **`tools/verify_credentials_load.py` spec ⚫ CLOSED 2026-05-11**: CLI shim Tool 12 spec lives at `phase1/04a_phase_0_prep_tools.md` § 3 (Round 4.5 supplement; B184 ⚫ CLOSED). **Implementation lands at Phase 2 R1** per `phase2/00_phase_overview.md` R1 prereq #1. Until P2R1 implementation completes, the operator-equivalent inline Python fallback in Step 3 is acceptable but skips the D74 exit-code + D76 audit-row contract — operators using the fallback should manually write a `ManualCorrectionLog` row to preserve the audit trail.
- **D85 stage 1 narrative still references `/debi/.env`**: per D92 forward-only schema discipline, the D85 lock (Round 6 close-out 2026-05-10) cannot be edited in place. D103 supersedes the `.env` location clause implicitly. A Round 7+ SchemaContract row OR D85 supersession-decision may formalize this — track as 🟡 follow-up (candidate B-future at Phase 2 R1 close-out).
- **Custom SELinux policy (`pipeline_conf_t`)**: current procedure uses default `etc_t` context. If parity baseline (B183) requires stricter labeling, author a custom SELinux module under `/etc/selinux/policies/pipeline.te` — defer to Phase 5 hardening per D103 Layer 11.
- **No multi-host parallel migration tool**: this runbook is per-server. For Phase 4 multi-cohort rollout, B-future may track a wrapper script that applies RB-14 across dev + test + prod in sequence with check-pause-check between each — defer to Phase 4 cutover planning.

### Cross-references

- **D103** (Claude Code 13-layer security model) — Layer 1 working-directory boundary + Layer 6 file mode 0400 + Layer 9 auditd + Layer 11 SELinux
- **D85** (module startup sequence — stage 1 credentials_loader) — pre-D103 reference to `/debi/.env`; superseded by D103 for the path
- **B182** (this runbook closes B182 — WSJF 4.0 deploy-blocker)
- **`docs/migration/SECURITY_MODEL.md`** — canonical reference for the 13-layer defense
- **CLAUDE.md** § "Claude Code Security Model (D103 — summary)" — quick-reference for the rationale
- **`.claudeignore` + `.claude/settings.local.json` `permissions.deny`** — enforcement layers for Claude Code's `/etc/pipeline/**` deny rules

### Owner

Pipeline lead authorizes; sysadmin (or pipeline operator with sudo) executes; pipeline lead validates. Dev workstation migration may be self-service by the engineer.

---

## How to Add a Runbook

1. Increment the next RB-number
2. Write following the structure: When-to-use → Pre-flight → Procedure → Validation → Rollback (if applicable)
3. Test the runbook in dev before adding it here
4. Reference from the relevant phase in `02_PHASES.md` or edge case in `04_EDGE_CASES.md`
