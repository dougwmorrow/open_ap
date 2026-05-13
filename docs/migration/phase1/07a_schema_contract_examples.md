# Phase 1 Round 1.5d — SchemaContract Example Rows

**Status**: 🟡 Proposed — pending Round 1.5 D72 validation campaign + Pattern F close-out audit
**Round position**: Round 1.5 — Schema Documentation Supplement
**Authored**: 2026-05-11

This supplement makes the abstract Round 7 "SchemaContract chain" concrete by showing 3 example clusters of rows:
1. **Cluster A** — Source schema contracts (column-level shape; per Round 1 table 23 design intent)
2. **Cluster B** — Round 7 SP signature evolution (SP-4 / SP-10 / SP-12 per B79/B93/B94/B81)
3. **Cluster C** — `SupersededBy` chain (hypothetical future re-evolution showing forward-link)

This is a sibling supplement to `phase1/07_schema_evolution_governance.md` (which is locked per D94); per D92 + D40 forward-only discipline, this is additive documentation not a schema change.

---

## § 0 — Read order + scope

### 0.1 Required reading

1. `docs/migration/phase1/01_database_schema.md` § 23 — `SchemaContract` table DDL + example
2. `docs/migration/phase1/07_schema_evolution_governance.md` § 2 (SP-4) + § 3 (SP-10 `@CutoffOverride`) + § 4 (SP-10 `@CategoryFilter`) + § 5 (SP-12 new SP)
3. `docs/migration/03_DECISIONS.md` D40 + D92 (schema evolution governance + forward-only additive)
4. `CLAUDE.md` "Round 7 SP signature evolutions" section (registered at Round 8 close-out)

### 0.2 Why this doc exists

Round 7 introduced 3 SP signature evolutions + 1 new SP, with each change supposed to land a row in `General.ops.SchemaContract` per § 4.5 joint migration script. A reader of Round 1 schema doc sees the SchemaContract DDL and one source-schema-column example; a reader of Round 7 spec sees the migration narrative but not the concrete contract rows. This doc shows what 9 specific contract rows look like — 1 cluster for each SP signature evolution + 1 for the new SP.

### 0.3 Scope

**In scope**:
- § 1: SchemaContract column reminder (per Round 1 § 23)
- § 2: Cluster A — Source schema contract example (DNA.ACCT.ACCTNBR per Round 1 § 23.example)
- § 3: Cluster B — SP signature evolution contract rows (SP-4, SP-10, SP-12)
- § 4: Cluster C — `SupersededBy` forward-link chain (hypothetical future SP-4 re-evolution)
- § 5: Querying current contract version (operator queries)
- § 6: Validation gates self-check

**Out of scope**:
- The migration scripts that write these rows (Round 6 deployment scope per D87)
- Schema-evolution detection logic comparing actual vs contract (Round 7 § 1.4)
- Source-DB-team change-notification SLAs (Phase 0 deliverable 0.14)

---

## § 1 — SchemaContract column reminder

Per Round 1 § 23 (table 23):

| Column | Type | Purpose |
|---|---|---|
| `ContractId` | `BIGINT IDENTITY(1,1)` | PK |
| `SourceName` | `NVARCHAR(50)` NOT NULL | Source-system short code OR `'pipeline'` for internal artifacts (SP signatures, table additions) |
| `ObjectName` | `NVARCHAR(255)` NOT NULL | Object (table / view / SP / column / configuration item) — flexible naming |
| `ColumnName` | `NVARCHAR(255)` NULL | Column / parameter / sub-element; NULL = object-level contract |
| `ContractKey` | `NVARCHAR(100)` NOT NULL | What's being asserted (e.g., `'expected_type'`, `'nullability'`, `'parameter_default'`) |
| `ContractValue` | `NVARCHAR(MAX)` NOT NULL | The asserted value |
| `EffectiveFrom` | `DATETIME2(3)` NOT NULL DEFAULT SYSUTCDATETIME() | When this contract row took effect |
| `EffectiveTo` | `DATETIME2(3)` NULL | NULL = currently active; non-NULL = superseded |
| `SupersededBy` | `BIGINT` NULL | Forward-link to the ContractId that replaced this row |
| `Notes` | `NVARCHAR(MAX)` NULL | Free-text rationale / ticket reference / runbook pointer |
| `CreatedAt` | `DATETIME2(3)` NOT NULL DEFAULT SYSUTCDATETIME() | Row insertion timestamp |
| `CreatedBy` | `NVARCHAR(255)` NOT NULL | Actor responsible for the change (operator, migration script, DBA, etc.) |

Indexes:
- `IX_SchemaContract_Active` — filtered on `EffectiveTo IS NULL` for active-contract lookup (most common query)
- `IX_SchemaContract_History` — chronological for audit

---

## § 2 — Cluster A: Source schema contract (Round 1 § 23 example expanded)

Per Round 1 § 23 example — DNA.osibank.ACCT.ACCTNBR is an integer PK, never null, contains PII (account number).

```sql
-- Cluster A: Source schema contract for DNA.osibank.ACCT.ACCTNBR
-- 5 rows establish the column's contract; 1 row at table level for change-notification SLA

INSERT INTO General.ops.SchemaContract
    (SourceName, ObjectName, ColumnName, ContractKey, ContractValue, CreatedBy, Notes)
VALUES
    ('DNA', 'ACCT', 'ACCTNBR', 'expected_type', 'INTEGER', 'pipeline-lead',
     'Source Oracle column DNA.osibank.ACCT.ACCTNBR is NUMBER(18,0); Polars Int64; SQL Server BIGINT'),
    
    ('DNA', 'ACCT', 'ACCTNBR', 'nullability', 'NOT NULL', 'pipeline-lead',
     'Per source DBA confirmation 2026-05-XX; verified via ALL_TAB_COLUMNS.NULLABLE = N'),
    
    ('DNA', 'ACCT', 'ACCTNBR', 'is_pii', 'true', 'pipeline-lead',
     'Account number qualifies as PII per CCPA broad-PII definition; tokenized per UdmTablesList.PiiColumnList'),
    
    ('DNA', 'ACCT', 'ACCTNBR', 'pii_type', 'ACCOUNT', 'pipeline-lead',
     'Categorization for compliance reporting; aligns with PiiVault.PiiType CHECK enum (SSN/EIN/EMAIL/NAME/ACCOUNT/PHONE/ADDRESS/OTHER) per Round 1 § 17'),
    
    ('DNA', 'ACCT', NULL, 'change_notification_sla_days', '14', 'pipeline-lead',
     'Source DBA team commits to 14-day pre-change notice on breaking changes; per Phase 0 deliverable 0.14');
```

**Operational use**: schema-evolution detection (Round 7 § 1.4) compares actual source schema against these rows on each pipeline run. If `ALL_TAB_COLUMNS` reports `NULLABLE='Y'` for ACCTNBR, the pipeline raises a ContractViolation event + logs to `PipelineEventLog` (EventType=`SCHEMA_DRIFT`).

---

## § 3 — Cluster B: Round 7 SP signature evolution contract rows

Per Round 7 closures B79/B93/B94/B81 (closed 2026-05-11). Each evolution adds a SchemaContract row asserting the SP's parameter shape post-change. Together with prior parameter assertions (pre-Round-7 baseline assumed), this enables future SP-signature-drift detection.

### 3.1 SP-4 `@AcknowledgmentOnly` addition (B79 closure)

```sql
-- Cluster B.1: SP-4 PipelineExecutionGate_AcquireTest gained @AcknowledgmentOnly BIT = 0 parameter at Round 7
-- Per phase1/07_schema_evolution_governance.md § 2 + B79

INSERT INTO General.ops.SchemaContract
    (SourceName, ObjectName, ColumnName, ContractKey, ContractValue, CreatedBy, Notes)
VALUES
    ('pipeline', 'PipelineExecutionGate_AcquireTest', '@AcknowledgmentOnly', 'parameter_type', 'BIT',
     'migration/r7_sp4_acknowledgment_only.py',
     'R7 B79: dry-run mode for tools/promote_test_to_prod.py (Round 4 § 3.6 consumer). When = 1, SP returns @Action = ''EXIT_ACKNOWLEDGED'' without state mutation.'),
    
    ('pipeline', 'PipelineExecutionGate_AcquireTest', '@AcknowledgmentOnly', 'parameter_default', '0',
     'migration/r7_sp4_acknowledgment_only.py',
     'Default 0 preserves pre-R7 caller compat (forward-only additive per D92).'),
    
    ('pipeline', 'PipelineExecutionGate_AcquireTest', '@AcknowledgmentOnly', 'parameter_nullable', 'false',
     'migration/r7_sp4_acknowledgment_only.py',
     'BIT NOT NULL with default; matches D92 additive discipline.'),
    
    ('pipeline', 'PipelineExecutionGate_AcquireTest', '@AcknowledgmentOnly', 'introduced_at_round', 'R7',
     'migration/r7_sp4_acknowledgment_only.py',
     'Originates from R7 § 2; closes B79.'),
    
    -- Object-level contract: SP-4 parameter-list length (input parameters only; OUTPUT params excluded from contract count per § 1.2 convention)
    ('pipeline', 'PipelineExecutionGate_AcquireTest', NULL, 'parameter_count_input', '6',
     'migration/r7_sp4_acknowledgment_only.py',
     'Pre-R7: 5 input params (@CycleType, @CycleDate, @ExpectedStartTime, @HeartbeatStaleMinutes, @ProdMaxRuntimeMinutes) + 3 OUTPUT (@GateId, @BatchId, @Action) per Round 1 § 4 SP-4. Post-R7: 6 input params (added @AcknowledgmentOnly per § 2.2 evolved signature).');
```

### 3.2 SP-10 `@CutoffOverride` + `@CategoryFilter` joint addition (B93+B94 closures)

```sql
-- Cluster B.2: SP-10 EnforceRetention gained 2 parameters at Round 7
-- Per phase1/07_schema_evolution_governance.md § 3 + § 4 + B93 + B94 (joint migration)

INSERT INTO General.ops.SchemaContract
    (SourceName, ObjectName, ColumnName, ContractKey, ContractValue, CreatedBy, Notes)
VALUES
    -- @CutoffOverride per § 3
    ('pipeline', 'EnforceRetention', '@CutoffOverride', 'parameter_type', 'DATETIME2(3)',
     'migration/r7_sp10_cutoff_override_category_filter.py',
     'R7 B93: operator-driven override of computed retention cutoff (default = NOW - ExpectedRetentionDays).'),
    
    ('pipeline', 'EnforceRetention', '@CutoffOverride', 'parameter_default', 'NULL',
     'migration/r7_sp10_cutoff_override_category_filter.py',
     'NULL preserves pre-R7 default-cutoff behavior; non-NULL triggers operator-override path.'),
    
    -- @CategoryFilter per § 4
    ('pipeline', 'EnforceRetention', '@CategoryFilter', 'parameter_type', 'NVARCHAR(20)',
     'migration/r7_sp10_cutoff_override_category_filter.py',
     'R7 B94: PiiType value to restrict the retention sweep (e.g., ''SSN''). Width NVARCHAR(20) matches UdmTablesList.DataClassification + PiiVault.PiiType canonical widths per Round 7 § 3.2 + § 4.2.'),
    
    ('pipeline', 'EnforceRetention', '@CategoryFilter', 'parameter_default', 'NULL',
     'migration/r7_sp10_cutoff_override_category_filter.py',
     'NULL = sweep all categories (pre-R7 behavior).'),
    
    -- Object-level: joint introduction
    ('pipeline', 'EnforceRetention', NULL, 'parameter_count_input', '3',
     'migration/r7_sp10_cutoff_override_category_filter.py',
     'Pre-R7: 1 input param (@DryRun). Post-R7 joint: 3 input params (added @CutoffOverride + @CategoryFilter at end of list per § 1.2 named-param compat).');
```

### 3.3 SP-12 PiiVault_ProcessCcpaDeletion new SP (B81 closure)

```sql
-- Cluster B.3: SP-12 is NEW at Round 7 (B81). New-SP contract = full parameter inventory
-- Per phase1/07_schema_evolution_governance.md § 5 + B81

INSERT INTO General.ops.SchemaContract
    (SourceName, ObjectName, ColumnName, ContractKey, ContractValue, CreatedBy, Notes)
VALUES
    -- Object-level: SP existence + Round of introduction
    ('pipeline', 'PiiVault_ProcessCcpaDeletion', NULL, 'object_type', 'STORED_PROCEDURE',
     'migration/r7_sp12_ccpa_deletion.py',
     'R7 B81: CCPA right-to-deletion SP wrapping the RB-10 workflow.'),
    
    ('pipeline', 'PiiVault_ProcessCcpaDeletion', NULL, 'introduced_at_round', 'R7',
     'migration/r7_sp12_ccpa_deletion.py',
     'New SP; no prior version to supersede.'),
    
    ('pipeline', 'PiiVault_ProcessCcpaDeletion', NULL, 'parameter_count', '7',
     'migration/r7_sp12_ccpa_deletion.py',
     '7 parameters: @RequestId, @SubjectIdentifier, @TokenList, @LegalExceptionReason, @RequestedBy, @Actor, @DryRun.'),
    
    -- Per-parameter contracts (illustrative subset; production migration writes all 7)
    ('pipeline', 'PiiVault_ProcessCcpaDeletion', '@RequestId', 'parameter_type', 'UNIQUEIDENTIFIER',
     'migration/r7_sp12_ccpa_deletion.py',
     'External CCPA request ID; correlates SP invocation to compliance ticket.'),
    
    ('pipeline', 'PiiVault_ProcessCcpaDeletion', '@SubjectIdentifier', 'parameter_type', 'NVARCHAR(MAX)',
     'migration/r7_sp12_ccpa_deletion.py',
     'Subject identifier (typically email, SSN, or account number). NULL allowed for token-file bulk mode per § 5 COALESCE.'),
    
    ('pipeline', 'PiiVault_ProcessCcpaDeletion', '@SubjectIdentifier', 'parameter_default', 'NULL',
     'migration/r7_sp12_ccpa_deletion.py',
     'NULL → COALESCE to synthetic placeholder ''TOKEN_FILE_BULK_'' + @RequestId per CcpaDeletionLog.SubjectIdentifier NOT NULL constraint.'),
    
    ('pipeline', 'PiiVault_ProcessCcpaDeletion', '@TokenList', 'parameter_type', 'NVARCHAR(MAX)',
     'migration/r7_sp12_ccpa_deletion.py',
     'CSV of tokens to delete. NOT NULL — must specify either by SubjectIdentifier-lookup OR explicit token list.'),
    
    ('pipeline', 'PiiVault_ProcessCcpaDeletion', '@DryRun', 'parameter_default', '1',
     'migration/r7_sp12_ccpa_deletion.py',
     'Default = dry-run (safe). Operator must explicitly pass 0 for actual deletion. Per D75 dry-run default for side-effecting tools.');
```

---

## § 4 — Cluster C: `SupersededBy` forward-link chain (hypothetical future evolution)

Scenario: in some future round (e.g., Round 10 hypothetical), SP-4 needs an additional `@RetryAcknowledgment BIT = 0` parameter. The original `@AcknowledgmentOnly` contract row stays (audit trail) but is marked superseded; new contract rows take effect.

```sql
-- Cluster C: hypothetical future SP-4 re-evolution
-- Original @AcknowledgmentOnly contract rows from § 3.1 get superseded

-- Step 1: insert new contract rows for the post-Round-10 state
INSERT INTO General.ops.SchemaContract
    (SourceName, ObjectName, ColumnName, ContractKey, ContractValue, CreatedBy, Notes)
VALUES
    ('pipeline', 'PipelineExecutionGate_AcquireTest', '@RetryAcknowledgment', 'parameter_type', 'BIT',
     'migration/r10_sp4_retry_acknowledgment.py',
     'R10 future B-N: support retry-loop case where promote tool wants to acknowledge without claiming new gate.'),
    
    ('pipeline', 'PipelineExecutionGate_AcquireTest', '@RetryAcknowledgment', 'parameter_default', '0',
     'migration/r10_sp4_retry_acknowledgment.py',
     'Forward-only additive per D92.'),
    
    -- Re-assert parameter_count_input at object level (now 7 instead of 6)
    ('pipeline', 'PipelineExecutionGate_AcquireTest', NULL, 'parameter_count_input', '7',
     'migration/r10_sp4_retry_acknowledgment.py',
     'R10: added @RetryAcknowledgment to existing 6 input params (including R7 @AcknowledgmentOnly).');

-- Step 2: supersede the prior parameter_count row
DECLARE @OldContractId BIGINT = (
    SELECT ContractId
    FROM General.ops.SchemaContract
    WHERE SourceName = 'pipeline'
      AND ObjectName = 'PipelineExecutionGate_AcquireTest'
      AND ColumnName IS NULL
      AND ContractKey = 'parameter_count_input'
      AND EffectiveTo IS NULL
);

DECLARE @NewContractId BIGINT = SCOPE_IDENTITY();  -- captured from prior INSERT

UPDATE General.ops.SchemaContract
SET EffectiveTo = SYSUTCDATETIME(),
    SupersededBy = @NewContractId
WHERE ContractId = @OldContractId;
```

**Forward-link audit**: query "show me the evolution history of SP-4's parameter_count":

```sql
WITH ContractHistory AS (
    SELECT 
        ContractId, ContractValue, EffectiveFrom, EffectiveTo, SupersededBy, CreatedBy, Notes
    FROM General.ops.SchemaContract
    WHERE SourceName = 'pipeline'
      AND ObjectName = 'PipelineExecutionGate_AcquireTest'
      AND ColumnName IS NULL
      AND ContractKey = 'parameter_count_input'
)
SELECT *
FROM ContractHistory
ORDER BY EffectiveFrom ASC;
```

Output (hypothetical):
```
ContractId  ContractValue  EffectiveFrom            EffectiveTo              SupersededBy  CreatedBy                                       Notes
14          5              <pre-R7 baseline date>   2026-05-11T00:00:00.000  47            migration/r1_initial_sp4.py                     Pre-R7 baseline (5 input params per Round 1 SP-4 § 4)
47          6              2026-05-11T00:00:00.000  <R10 future date>        N             migration/r7_sp4_acknowledgment_only.py         R7 closure B79 (added @AcknowledgmentOnly → 6 input params)
N           7              <R10 future date>        NULL                     NULL          migration/r10_sp4_retry_acknowledgment.py       R10 (hypothetical) B-N (added @RetryAcknowledgment → 7 input params)
```

The chain — `14 → 47 → N` — gives full audit history of SP-4's input parameter count.

---

## § 5 — Querying current contract version

The `IX_SchemaContract_Active` filtered index makes this the cheap common query:

### 5.1 "What's the current contract for SP-4?"

```sql
SELECT ColumnName, ContractKey, ContractValue, Notes
FROM General.ops.SchemaContract
WHERE SourceName = 'pipeline'
  AND ObjectName = 'PipelineExecutionGate_AcquireTest'
  AND EffectiveTo IS NULL                       -- filtered index hits here
ORDER BY ColumnName, ContractKey;
```

### 5.2 "Which SPs evolved in Round 7?"

```sql
SELECT DISTINCT ObjectName, MIN(EffectiveFrom) AS introduced_at
FROM General.ops.SchemaContract
WHERE SourceName = 'pipeline'
  AND Notes LIKE 'R7%'                          -- by Notes convention
GROUP BY ObjectName
ORDER BY introduced_at;
```

### 5.3 "Have any source-DBA SLAs been violated?" (cross-table with PipelineEventLog SCHEMA_DRIFT events)

```sql
SELECT
    sc.SourceName,
    sc.ObjectName,
    sc.ContractValue AS sla_days,
    el.StartedAt AS drift_detected_at,
    DATEDIFF(DAY, el.Metadata.value('$.notified_at', 'DATETIME2'), el.StartedAt) AS notice_provided_days
FROM General.ops.SchemaContract sc
JOIN General.ops.PipelineEventLog el
    ON el.SourceName = sc.SourceName
   AND el.TableName = sc.ObjectName
   AND el.EventType = 'SCHEMA_DRIFT'
WHERE sc.ContractKey = 'change_notification_sla_days'
  AND sc.EffectiveTo IS NULL
  AND el.StartedAt > DATEADD(DAY, -90, SYSDATETIME());
```

(Schema-drift event metadata schema is hypothetical pending Round 7 § 1.4 detection-logic implementation; this query illustrates the join pattern.)

---

## § 6 — Validation gates self-check

### 6.1 Gate 1 — Cross-reference

| Check | Verdict |
|---|---|
| SchemaContract DDL matches Round 1 § 23 | ✅ Walked (12 columns + 2 indexes) |
| SP-4 evolution matches Round 7 § 2 + B79 closure | ✅ Walked (`@AcknowledgmentOnly` BIT = 0 default) |
| SP-10 evolution matches Round 7 § 3 + § 4 + B93+B94 joint closure | ✅ Walked (`@CutoffOverride` DATETIME2(3) NULL + `@CategoryFilter` NVARCHAR(20) NULL) |
| SP-12 new SP matches Round 7 § 5 + B81 closure | ✅ Walked (7 parameters; @SubjectIdentifier COALESCE to synthetic placeholder per cycle 8 R7 fix) |
| `SupersededBy` self-reference matches Round 1 § 23 design | ✅ Walked |
| Naming convention (SourceName='pipeline' for internal artifacts) | ✅ Consistent with prior Round 1 § 23 example (which used 'DNA' for source schemas) |
| D92 forward-only additive discipline | ✅ All examples are additive (new columns, new parameters, new SPs); no rename/removal |

### 6.2 Gate 2 — Independent QA

Pattern E from cycle 1 (Tier α; combined Round 1.5 supplements operate at Tier β).

### 6.3 Gate 3 — Edge case enumeration

| Edge case | Concern | Mitigation |
|---|---|---|
| SchemaContract row count grows unbounded | R29 (Round 7 close-out) | 7-year archival per D30; B150 tracks |
| Multiple active contract rows for same (Source, Object, Column, Key) | I-series invariant | `IX_SchemaContract_Active` filtered index would benefit from UNIQUE constraint — 🟡 follow-up |
| SupersededBy points to a row with EffectiveTo IS NULL (active loop) | Logical inconsistency | Operator discipline; no DB-level constraint enforces; 🟡 follow-up |
| Migration script crashes mid-update (some new rows inserted, old rows not superseded) | I3 race | Migration scripts run inside transactions per D87 atomicity discipline |

### 6.4 Gate 4 — Edge case validation

🟡 follow-ups identified at § 6.3 — tracked as:
- **B170**: UNIQUE constraint on active SchemaContract rows per (SourceName, ObjectName, ColumnName, ContractKey) WHERE EffectiveTo IS NULL — prevents multiple active contract rows for the same key
- **B171**: SupersededBy circular-reference detection at INSERT time (or post-INSERT validation) — prevents A→B→A loops
- **I24** (new edge case): file in `04_EDGE_CASES.md` I-series at Round 1.5 close-out — "Multiple active SchemaContract rows for same (SourceName, ObjectName, ColumnName, ContractKey)" — mitigated by B170 once implemented

### 6.5 Gate 5 — Idempotency / regression

| Check | Verdict |
|---|---|
| Re-running migration scripts is no-op via `IF NOT EXISTS` guards | ✅ Per D34 + R7 § 4.5 joint migration script pattern |
| Locked Round 7 spec untouched | ✅ This is sibling supplement |
| `SupersededBy` semantics preserve audit trail | ✅ Append-only — `UPDATE` only sets `EffectiveTo` + `SupersededBy`; never DELETEs |

### 6.6 Pillar mapping (per D61)

| Pillar | Contribution |
|---|---|
| Audit-grade | `SupersededBy` chain enables full reconstruction of any SP's evolution history |
| Traceability | `Notes` column ties each row to migration script + closure ticket |
| Idempotent | Migration scripts use `IF NOT EXISTS`; re-run is no-op |
| Operationally stable | Schema drift detection (Round 7 § 1.4) reads these rows as ground truth |
| $120K/year ceiling | n/a |

---

## § 7 — Cycle log (Round 1.5 D72 campaign — populated post-acceptance)

See `phase1/01a_control_tables.md` § 11 for the canonical R1.5 cycle log table (all 5 supplements share the same combined campaign). Round 1.5 D72 campaign summary: 6 review cycles + 1 Pattern F event; 23 cumulative 🔴 caught + fixed; D101 math-infeasibility acceptance per D73/D78/D94 precedent.

Full per-cycle detail in `_validation_log.md` 2026-05-11 Round 1.5 entry.

---

## Owner

Pipeline lead. SchemaContract is the canonical home for schema-evolution audit history per D40 + D92; this doc shows what its rows look like in practice for the Round 7 closures.

## Last updated

2026-05-11 (Round 1.5d authored; pending Pattern E validation)
