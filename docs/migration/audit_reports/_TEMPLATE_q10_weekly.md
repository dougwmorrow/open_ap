# Q10 weekly backup integrity drill — YYYY-WW

**Template**. Copy to `Q10_weekly_<YYYY-WW>.md` (e.g. `Q10_weekly_2026-W23.md`) for each weekly run.

Spec home: `docs/migration/06_TESTING.md` Tier 5 Q10 + `docs/migration/phase1/05_tests.md` § 8.2 Q10. Cadence per W-12 vault restore test cadence noted in CLAUDE.md.

---

## Header

| Field | Value |
|---|---|
| ISO week | YYYY-WW |
| Date executed | YYYY-MM-DD |
| Operator | (full name + role) |
| Backup file restored | (path / S3 key / vendor backup ID) |
| Backup creation date | YYYY-MM-DD HH:MM (per backup metadata) |
| Staging environment | (e.g. `Staging.ops.PiiVault` on `<staging-host>`) |
| Audit budget consumed | (minutes; expected ~30 min) |

---

## Procedure execution

| Step | Outcome |
|---|---|
| 1. Backup restored to staging successfully | ✅ / 🔴 (note any restore-side errors) |
| 2. 100 random tokens queried from staging | ✅ N rows returned / 🔴 if <100 |
| 3. Each decrypted via `decrypt_pii.py` against staging | ✅ all 100 / 🔴 N of 100 failed to decrypt |
| 4. Plaintext cross-checked against expected | ✅ all 100 match / 🔴 N of 100 mismatch |

---

## Results

| Item | Value |
|---|---|
| Tokens decrypted successfully | N of 100 |
| Plaintext mismatches | N (target: 0) |
| Mismatch token IDs (if any) | (list) |
| Decrypt failures (if any) | (list with verdict per failure: VERDICT_NOT_FOUND / VERDICT_VAULT_UNAVAILABLE / VERDICT_ERROR) |

**Pass criterion**: 100/100 decrypt + 100/100 plaintext match.
**Verdict**: ✅ PASS / 🔴 FAIL

---

## Incident escalation (only if 🔴)

If ANY mismatch OR decrypt failure:

1. ✅/🔴 Production CCPA / decrypt operations paused immediately
2. ✅/🔴 Incident note filed in `RISKS.md`
3. ✅/🔴 Pipeline lead + on-call notified (cite channel + timestamp)
4. ✅/🔴 Investigation findings documented in `_validation_log.md` under today's date

---

## Sign-off

| Role | Name | Date |
|---|---|---|
| Operator | | |
| Pipeline lead (acknowledgment; required only on 🔴) | | |
