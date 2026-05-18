# Tier 5 quarterly audit report — QYYYY_QN

**Template**. Copy to `QYYYY_QN.md` (e.g. `Q2026_Q3.md`) before each quarterly drill cycle. Q10 (weekly cadence) uses a separate template at `_TEMPLATE_q10_weekly.md`.

Spec home: `docs/migration/06_TESTING.md` Tier 5 + `docs/migration/phase1/05_tests.md` § 8.

---

## Header

| Field | Value |
|---|---|
| Quarter | QYYYY_QN (e.g. Q2026_Q3) |
| Date executed | YYYY-MM-DD |
| Operator | (full name + role) |
| Reviewer | (full name + role; MUST be different person from operator per D55+D56 second-pass discipline) |
| Audit budget consumed | (hours; expected ~1 business day for the full Q1-Q9 cycle) |
| Pipeline branch / tag at audit time | (e.g. `master @ <hash>` OR `v1.2.3`) |

---

## Q1 — Point-in-time query proof

| Item | Value |
|---|---|
| 3 PKs picked | (PK 1) / (PK 2) / (PK 3) |
| Source / table per PK | (source.table for each) |
| As-of date used | (typically 6 months prior) |
| Bronze value matches Parquet snapshot? | ✅ all 3 / 🔴 N of 3 mismatch |
| Notes | (any anomalies; tie-break choices) |

**Pass criterion**: 3-of-3 match.
**Verdict**: ✅ PASS / 🔴 FAIL

---

## Q2 — Pipeline activity proof

| Item | Value |
|---|---|
| 3 business dates picked | YYYY-MM-DD / YYYY-MM-DD / YYYY-MM-DD |
| TABLE_TOTAL events present per date? | ✅ / 🔴 list gaps |
| PipelineExtraction SUCCESS rows present (large tables)? | ✅ / 🔴 list gaps |
| Documented exceptions in ExtractionGapLog | (list any rows referenced) |

**Pass criterion**: every (table, source) for each picked date either has a SUCCESS row OR a documented gap.
**Verdict**: ✅ PASS / 🔴 FAIL

---

## Q3 — PII redaction proof

| Item | Value |
|---|---|
| 10 Bronze PII rows sampled | (PK list OR sample SQL) |
| All values are 40-char tokens? | ✅ / 🔴 list violations |
| 1 token decrypted via tools/decrypt_pii.py (audit creds)? | (token, plaintext-sanity-check ✅/🔴) |
| PiiVaultAccessLog row count incremented by exactly 1? | ✅ / 🔴 |

**Pass criterion**: tokens validated, decrypt round-trips, audit log incremented.
**Verdict**: ✅ PASS / 🔴 FAIL

---

## Q4 — Vault key/token rotation proof (annual)

Skip if not the annual-rotation quarter; mark "N/A — annual cadence; next due QYYYY_QN".

| Item | Value |
|---|---|
| Vault row count + oldest TokenId pre-rotation | (rows, CreatedAt of oldest) |
| Rotation procedure executed | (date + runbook reference) |
| Pipeline runs daily for 1 week post-rotation? | ✅ / 🔴 |
| Old tokens still decrypt? | ✅ all sampled / 🔴 list failures |
| New tokens issued under new credentials? | ✅ / 🔴 |
| Rotation logged in audit trail | (log file path / reference) |

**Pass criterion**: rotation completes, old tokens still decrypt, new tokens issued under new credentials.
**Verdict**: ✅ PASS / 🔴 FAIL / ⏭ N/A (annual; next due …)

---

## Q5 — DR rehearsal (RB-7)

| Item | Value |
|---|---|
| Rehearsal date | YYYY-MM-DD |
| RB-7 pass criteria met | ✅ each / 🔴 list failures |
| Any unexpected behavior | (notes) |

**Verdict**: ✅ PASS / 🔴 FAIL

---

## Q6 — CLI audit trail verification

| Item | Value |
|---|---|
| 3 random CLI_* rows picked | (BatchId / EventType / CreatedAt for each) |
| `actor` non-empty + matches operator records (each)? | ✅ all 3 / 🔴 list gaps |
| `justification` non-empty (where required)? | ✅ all 3 / 🔴 / N/A (none of 3 require) |
| P5 plaintext PII scan result | ✅ no matches / 🔴 list patterns + rows |

**Pass criterion**: 3-of-3 actor + justification valid; 0 plaintext PII matches.
**Verdict**: ✅ PASS / 🔴 FAIL

---

## Q7 — Tier 0 drift audit

| Item | Value |
|---|---|
| `tools/verify_tier0_drift` run date + output path | YYYY-MM-DD / `tests/audit_reports/tier0_drift_<date>.md` |
| Overall verdict | ✅ CLEAN / 🟡 / 🔴 |
| 🟡 findings (count + B-N opened or alignment applied) | (list) |
| 🔴 findings (MUST be 0) | (list — if non-empty, escalate) |
| Prior-quarter B-Ns confirmed landed | (list of B-N codes) |

**Pass criterion**: overall ≤ 🟡; all 🟡 either aligned with spec OR opened as B-N.
**Verdict**: ✅ PASS / 🟡 PASS-WITH-OPEN-B-Ns / 🔴 FAIL

---

## Q8 — Reviewer effectiveness ledger audit

| Specialty role | Cycles in quarter | False-clean rate | Verdict |
|---|---|---|---|
| (e.g. column-walk) | (N) | (X%) | ✅ ≤10% / 🟡 10-25% REFINE / 🔴 >25% RETIRE-OR-PAIR |
| ... | ... | ... | ... |

| Item | Value |
|---|---|
| Approved deltas from prior round close-outs all landed? | ✅ / 🔴 list missing |
| New REFINE / RETIRE-OR-PAIR B-Ns opened this quarter | (list) |

**Pass criterion**: no specialty exceeds 25% false-clean; all approved deltas applied.
**Verdict**: ✅ PASS / 🔴 FAIL

---

## Q9 — CCPA deletion proof

| Item | Value |
|---|---|
| Historical CCPA RequestId picked | (UUID) |
| RequestedAt | YYYY-MM-DD HH:MM |
| Justification valid (non-empty + on-pattern)? | ✅ / 🔴 |
| Actor + RequestedBy populated? | ✅ / 🔴 |
| 1-3 tokens picked from deletion's TokenList | (list) |
| decrypt_pii verdict per token | (each token: VERDICT_CCPA_DELETED / VERDICT_NOT_FOUND / 🔴 VERDICT_DECRYPTED) |

**Pass criterion**: 0 tokens return VERDICT_DECRYPTED (CCPA-deleted MUST be unrecoverable per RB-10).
**Verdict**: ✅ PASS / 🔴 FAIL

---

## Issues discovered + remediation

(Free-form. Note any 🔴 verdicts above + the remediation path: B-N opened, runbook updated, ad-hoc fix applied, etc.)

---

## Next quarter's focus areas

(Free-form. Carry forward open B-Ns, areas of concern, drills to deepen.)

---

## Sign-off

| Role | Name | Date |
|---|---|---|
| Operator | | |
| Reviewer | | |
| Pipeline lead (acknowledgment) | | |
