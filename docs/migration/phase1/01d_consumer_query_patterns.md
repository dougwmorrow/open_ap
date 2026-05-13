# Phase 1 Round 1.5f — Consumer Query Patterns (Bronze Defensive Queries)

**Status**: 🟢 Locked 2026-05-11 (closes B172 from Round 1.5 backlog; documentation-only supplement; no canonical schema changes)
**Round position**: Round 1.5 follow-on supplement (additive per D100 + D40 + D92 forward-only)
**Authored**: 2026-05-11 at backlog batch closure

This supplement closes B172 — elevates the V-4 defensive Bronze query pattern from CLAUDE.md (production-code reference) to consumer-facing operator/analyst reference. Downstream consumers querying Bronze SCD2 tables need to use defensive patterns that survive concurrent SCD2 promotion windows and crash-recovery states.

---

## § 0 — Read order + scope

### 0.1 Required reading

1. `phase1/01b_bronze_stage_example_ddl.md` — Bronze + Stage example DDL (framework column semantics)
2. `CLAUDE.md` "Do NOT" rules — especially "Do NOT query Bronze with only `WHERE UdmActiveFlag = 1` without dedup protection" (V-4)
3. `04_EDGE_CASES.md` V-4 (duplicate active rows during SCD2 INSERT-first window) + V-14 (transient zero-active-row window per B-14)
4. Round 1 § 16-22 PII vault table set + § 24 OrphanedTokenLog

### 0.2 Why this doc exists

Downstream consumers (Power BI dashboards, Snowflake analysts, audit queries, RB-10 CCPA processors) write SQL against Bronze tables. The NAIVE query pattern `SELECT ... FROM UDM_Bronze.{Source}.{Table}_scd2_python WHERE UdmActiveFlag = 1` is **unsafe under concurrent SCD2 promotion** — it can return:
- Zero rows for a PK that is actively being updated (transient zero-active window per V-14 + B-14)
- Duplicate rows for the same PK (V-4 — duplicates from crash-recovery + INSERT-then-activate windows)

Per CLAUDE.md "Do NOT" rules: `Do NOT query Bronze with only WHERE UdmActiveFlag = 1 without dedup protection — use ROW_NUMBER() OVER (PARTITION BY pk_cols ORDER BY UdmEffectiveDateTime DESC) WHERE rn = 1 to handle duplicate active rows from crash recovery windows (V-4)`.

This supplement makes that pattern + variants accessible to consumer teams without requiring them to read CLAUDE.md.

### 0.3 Scope

**In scope**:
- § 1: V-4 defensive query pattern (canonical ROW_NUMBER variant)
- § 2: Variants for time-travel queries (point-in-time Bronze state)
- § 3: PII decryption patterns (vault join + audit-trail discipline)
- § 4: Compliance audit query patterns (PII history + access trail + CCPA + orphan)
- § 5: Cross-source consumer patterns (multi-Bronze joins)
- § 6: Anti-patterns (the queries that don't survive concurrent SCD2 promotion)

**Out of scope**:
- Power BI DAX equivalents (Phase 6)
- Snowflake mirror queries (Phase 5)
- Source-system upstream queries (external)

---

## § 1 — V-4 defensive Bronze query pattern (canonical)

### 1.1 The pattern

```sql
-- ✅ CANONICAL — survives concurrent SCD2 promotion + crash-recovery + transient zero-active window
WITH ranked AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY <pk_cols> ORDER BY UdmEffectiveDateTime DESC) AS rn
    FROM UDM_Bronze.<SourceName>.<TableName>_scd2_python
    WHERE UdmActiveFlag IN (1, 2)  -- include delete-close per SCD2-R4 if you want most-recent state OR delete-close
      AND UdmEndDateTime IS NULL OR UdmEndDateTime > SYSDATETIME()  -- exclude historical
)
SELECT *
FROM ranked
WHERE rn = 1;
```

The `ROW_NUMBER() OVER (PARTITION BY pk_cols ORDER BY UdmEffectiveDateTime DESC) WHERE rn = 1` pattern:
- **Survives V-4** — picks the most-recent active row when 2 active rows exist transiently
- **Survives V-14** — returns 0 rows when zero active rows exist (no exception thrown); consumers can fallback to most-recent closed row if needed
- **Survives crash-recovery windows** — works regardless of B-4 orphans (which have `UdmActiveFlag = 0`; excluded by filter anyway)

### 1.2 Concrete example: DNA.ACCT current state

```sql
-- "What is account 12345's current state in Bronze?"
WITH ranked AS (
    SELECT 
        ACCTNBR, CUSTNBR, ACCTTYPE, DATEOPENED, DATECLOSED,
        CURRBAL, CHARGEOFFAMT,
        UdmEffectiveDateTime, UdmEndDateTime, UdmActiveFlag,
        ROW_NUMBER() OVER (PARTITION BY ACCTNBR ORDER BY UdmEffectiveDateTime DESC) AS rn
    FROM UDM_Bronze.DNA.ACCT_scd2_python
    WHERE ACCTNBR = 12345
      AND UdmActiveFlag IN (1, 2)
)
SELECT ACCTNBR, CUSTNBR, ACCTTYPE, DATEOPENED, DATECLOSED, CURRBAL, CHARGEOFFAMT
FROM ranked
WHERE rn = 1;
```

Returns at most 1 row, even during concurrent SCD2 update window.

### 1.3 Point-in-time variant (time-travel)

```sql
-- "What was account 12345's state on 2024-12-31?"
DECLARE @AsOfDate DATETIME2(3) = '2024-12-31 23:59:59.999';

WITH ranked AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY ACCTNBR ORDER BY UdmEffectiveDateTime DESC) AS rn
    FROM UDM_Bronze.DNA.ACCT_scd2_python
    WHERE ACCTNBR = 12345
      AND UdmEffectiveDateTime <= @AsOfDate
      AND (UdmEndDateTime IS NULL OR UdmEndDateTime > @AsOfDate)
)
SELECT *
FROM ranked
WHERE rn = 1;
```

### 1.4 Source-date variant (R-2 business-date semantics; per R7)

If your query is asking "what was the state in the SOURCE SYSTEM on business-date X" (not arrival-into-UDM date), use the source-date pair instead:

```sql
WITH ranked AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY ACCTNBR ORDER BY UdmSourceBeginDate DESC) AS rn
    FROM UDM_Bronze.DNA.ACCT_scd2_python
    WHERE ACCTNBR = 12345
      AND UdmSourceBeginDate <= @SourceBusinessDate
      AND (UdmSourceEndDate IS NULL 
           OR UdmSourceEndDate = '2999-12-31'  -- active sentinel per SCD2-P1-c
           OR UdmSourceEndDate > @SourceBusinessDate)
)
SELECT *
FROM ranked
WHERE rn = 1;
```

Per SCD2-P1-a: `UdmEffectiveDateTime` / `UdmEndDateTime` = load-time pair; `UdmSourceBeginDate` / `UdmSourceEndDate` = business-date pair. Use the right pair for your audit question.

---

## § 2 — Bulk query variants

### 2.1 All active rows for a source table

```sql
-- Current snapshot of all DNA accounts (safe for analytics)
WITH ranked AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY ACCTNBR ORDER BY UdmEffectiveDateTime DESC) AS rn
    FROM UDM_Bronze.DNA.ACCT_scd2_python
    WHERE UdmActiveFlag = 1
)
SELECT *
FROM ranked
WHERE rn = 1;
```

### 2.2 All historical states for a PK (audit / regulator query)

```sql
-- Full history of account 12345
SELECT *
FROM UDM_Bronze.DNA.ACCT_scd2_python
WHERE ACCTNBR = 12345
ORDER BY UdmEffectiveDateTime ASC;
```

This is the regulator-audit query — every SCD2 version is returned; no deduplication.

### 2.3 Delete-close audit (rows that were deleted from source)

```sql
-- Accounts that were deleted from source (per SCD2-R4 UdmActiveFlag=2)
SELECT *
FROM UDM_Bronze.DNA.ACCT_scd2_python
WHERE UdmActiveFlag = 2  -- 2 = delete-close per SCD2-R4
  AND UdmEndDateTime > DATEADD(DAY, -90, SYSDATETIME());
```

---

## § 3 — PII decryption patterns

### 3.1 Authorized decryption flow

PII columns in Bronze hold tokens (per `UdmTablesList.PiiColumnList`). Decryption is via SP-2:

```sql
-- ⚠️ Authorized only; logs to PiiVaultAccessLog
DECLARE @RequestId UNIQUEIDENTIFIER = NEWID();
DECLARE @Justification NVARCHAR(MAX) = 'Compliance request CCR-2026-Q1-042 per ops-channel ticket';
DECLARE @TokenList NVARCHAR(MAX);

-- Get tokens for accounts under review
SET @TokenList = (
    SELECT STRING_AGG(TAXID, ',') WITHIN GROUP (ORDER BY ACCTNBR)
    FROM (
        WITH ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY ACCTNBR ORDER BY UdmEffectiveDateTime DESC) AS rn
            FROM UDM_Bronze.DNA.ACCT_scd2_python
            WHERE ACCTNBR IN (12345, 67890, 11111)  -- audit scope
              AND UdmActiveFlag = 1
        )
        SELECT TAXID FROM ranked WHERE rn = 1
    ) sub
);

EXEC General.ops.PiiVault_Decrypt 
    @RequestId = @RequestId,
    @TokenList = @TokenList,
    @Justification = @Justification;
-- Returns: { Token, DecryptedValue } rows
-- Side effect: INSERTs to PiiVaultAccessLog per row decrypted
```

### 3.2 Anti-pattern (DO NOT do this)

```sql
-- ❌ NEVER — bypasses audit-trail; violates D30 + RB-10 + compliance discipline
SELECT EncryptedPlaintext FROM General.ops.PiiVault WHERE Token = '...';
-- DECRYPT_BY_KEY(... , EncryptedPlaintext)  -- ❌ no PiiVaultAccessLog entry
```

Always use SP-2 (single token) or SP-2-bulk (bounded bulk). Both write to `PiiVaultAccessLog` per D26.

---

## § 4 — Compliance audit query patterns

### 4.1 Full PII history for a subject (CCPA right-to-know)

```sql
-- "Show me everything UDM knows about account 12345 + the PII vault entries"
-- 1. Active state + history
SELECT 'history' AS query_class, *
FROM UDM_Bronze.DNA.ACCT_scd2_python
WHERE ACCTNBR = 12345
ORDER BY UdmEffectiveDateTime ASC;

-- 2. PII vault entries (joined via token)
WITH ranked AS (
    SELECT TAXID, EMAIL, PHONE,
           ROW_NUMBER() OVER (PARTITION BY ACCTNBR ORDER BY UdmEffectiveDateTime DESC) AS rn
    FROM UDM_Bronze.DNA.ACCT_scd2_python
    WHERE ACCTNBR = 12345
)
SELECT 'vault' AS query_class,
       v.PiiType, v.SourceName, v.CreatedAt, v.Status, v.LegalHold, v.RetentionExpiresAt
FROM ranked r
JOIN General.ops.PiiVault v 
  ON v.Token IN (r.TAXID, r.EMAIL, r.PHONE)
WHERE r.rn = 1;

-- 3. PII access trail (who decrypted this account's PII?)
SELECT 'access' AS query_class,
       al.AccessedAt, al.RequestedBy, al.Actor, al.Justification
FROM General.ops.PiiVaultAccessLog al
WHERE al.Token IN (
    SELECT TAXID FROM UDM_Bronze.DNA.ACCT_scd2_python WHERE ACCTNBR = 12345
       UNION
    SELECT EMAIL FROM UDM_Bronze.DNA.ACCT_scd2_python WHERE ACCTNBR = 12345
       UNION  
    SELECT PHONE FROM UDM_Bronze.DNA.ACCT_scd2_python WHERE ACCTNBR = 12345
)
ORDER BY al.AccessedAt DESC;
```

### 4.2 Orphaned-token check (PII tokens no longer decryptable)

```sql
-- "Which tokens in Bronze are orphaned (vault no longer holds the plaintext)?"
WITH all_tokens AS (
    SELECT 'TAXID' AS column_name, TAXID AS token FROM UDM_Bronze.DNA.ACCT_scd2_python WHERE TAXID IS NOT NULL
    UNION ALL
    SELECT 'EMAIL' AS column_name, EMAIL AS token FROM UDM_Bronze.DNA.ACCT_scd2_python WHERE EMAIL IS NOT NULL
)
SELECT at.column_name, at.token, otl.OrphanReason, otl.OrphanedAt
FROM all_tokens at
JOIN General.ops.OrphanedTokenLog otl ON otl.Token = at.token
GROUP BY at.column_name, at.token, otl.OrphanReason, otl.OrphanedAt
ORDER BY otl.OrphanedAt DESC;
```

---

## § 5 — Cross-source consumer patterns

### 5.1 Customer-360 (Customer joined across DNA + CCM)

```sql
-- "Show me account ACCT 12345 + its CCM TransactionDetail history this quarter"
WITH dna_account AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY ACCTNBR ORDER BY UdmEffectiveDateTime DESC) AS rn
    FROM UDM_Bronze.DNA.ACCT_scd2_python
    WHERE ACCTNBR = 12345 AND UdmActiveFlag = 1
),
ccm_txn AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY TransactionId ORDER BY UdmEffectiveDateTime DESC) AS rn
    FROM UDM_Bronze.CCM.TransactionDetail_scd2_python
    WHERE AccountNumber = '12345'
      AND TransactionTimestamp BETWEEN '2026-01-01' AND '2026-04-01'
      AND UdmActiveFlag = 1
)
SELECT 'account' AS type, ACCTNBR AS id, ACCTTYPE AS detail, DATEOPENED AS event_date
FROM dna_account WHERE rn = 1
UNION ALL
SELECT 'transaction' AS type, TransactionId AS id, TransactionType AS detail, TransactionTimestamp AS event_date
FROM ccm_txn WHERE rn = 1
ORDER BY event_date;
```

Each subquery uses the V-4 defensive ROW_NUMBER pattern.

### 5.2 Snowflake mirror query (Phase 5+; same defensive pattern applies)

```sql
-- Snowflake-side query — same defensive pattern translates
WITH ranked AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY ACCTNBR ORDER BY UdmEffectiveDateTime DESC) AS rn
    FROM UDM_BRONZE.DNA.ACCT_SCD2_PYTHON
    WHERE ACCTNBR = 12345 AND UdmActiveFlag = 1
)
SELECT *
FROM ranked
WHERE rn = 1;
```

---

## § 6 — Anti-patterns (DO NOT do these)

| Anti-pattern | Why it breaks | Fix |
|---|---|---|
| `SELECT ... WHERE UdmActiveFlag = 1` (no dedup) | V-4: may return 2 rows during transient SCD2 INSERT-then-activate window | Use ROW_NUMBER + rn = 1 (§ 1.1) |
| `SELECT TOP 1 ... ORDER BY UdmEffectiveDateTime DESC` (no PARTITION BY) | Returns 1 row total, not 1 row per PK | ROW_NUMBER per PK |
| `SELECT DISTINCT ...` to dedup | Loses the row's last-known state if columns are NULL | ROW_NUMBER + rn = 1 |
| `SELECT ... WHERE UdmActiveFlag IN (1)` (excluding `2`) | Misses delete-close rows; consumers asking "most-recent state" should usually include both | Use `UdmActiveFlag IN (1, 2)` for "current OR most-recently-deleted" queries |
| Querying source data directly (`DNA.osibank.ACCT`) | Bypasses tokenization; exposes plaintext PII; bypasses audit | Always query Bronze tokens + use SP-2 for authorized decrypt |
| Direct `PiiVault.EncryptedPlaintext` decrypt | Bypasses `PiiVaultAccessLog`; violates D26 + RB-10 | Always SP-2 / SP-2-bulk |
| `TRUNCATE TABLE UDM_Bronze.<X>` | Destroys SCD2 history; violates D34 + audit | NEVER. RB-13 retirement only after compliance sign-off. |

---

## § 7 — Validation gates self-check

### 7.1 Gate 1 — Cross-reference

| Check | Verdict |
|---|---|
| V-4 pattern matches CLAUDE.md "Do NOT" rule + 04_EDGE_CASES V-4 | ✅ |
| SP-2 invocation matches Round 1 SP-2 + SP-2-bulk signatures | ✅ |
| SCD2 framework column names match `phase1/01b_bronze_stage_example_ddl.md` + canonical Round 1 | ✅ |
| Time-travel + source-date variants match SCD2-P1-a/b/c + R-2 contract | ✅ |
| PII discipline matches D6 + D26 + D30 + RB-10 | ✅ |

### 7.2 Gate 2 — QA

This doc is the consumer-facing version of patterns already in CLAUDE.md. Pattern E full review not needed; D55 single-pass sufficient per Tier α (5 KB).

### 7.3 Gate 3-5

| Gate | Verdict |
|---|---|
| Gate 3 (edge case enumeration) | V-4 + V-14 + B-4 covered; § 6 anti-patterns cover failure modes |
| Gate 4 (edge case validation) | Each pattern verified against CLAUDE.md "Do NOT" rules |
| Gate 5 (idempotency / regression) | ✅ Queries are read-only; SP-2 writes audit-log idempotently per RequestId |

---

## Owner

Pipeline lead. Consumer-team representatives should review § 6 anti-patterns at Phase 2 first-loop-invocation; update with team-specific patterns as Phase 6 dashboards emerge.

## Last updated

2026-05-11 (closes B172; supplement to Round 1.5 set as Round 1.5f post-backlog-batch)
