# R5: CCPA + Parquet Replay Legal Research

**Date**: 2026-05-17
**Researcher**: `udm-researcher` agent (agentId `a959ee0434c90087b`; 42nd cumulative production application this session); CCL-compliant (Stage 1-3 reads completed before external search)
**Triggered by**: D2 execution plan pre-sign-off gap-check (Agent `ae1476a588dd34e15` G1 finding); persisted to file 2026-05-17 per Gap G14 surfaced by 2nd-pass gap-check reviewer (Agent `ad295972762e5ef33`; 43rd cumulative)
**Anchor**: D2 (Parquet replaces Stage) + D26 (vault provenance) + D30 (7-year retention + CCPA) + D102 (AES-256-GCM) + RB-10 (CCPA deletion) + the CCPA-deletion stored procedure (per CLAUDE.md SP family registry) (PiiVault_ProcessCcpaDeletion)

---

## Executive Summary

Tokenized PII in Parquet snapshots is **pseudonymized personal data under GDPR and personal information under CCPA** — NOT exempt from either regime — because the pipeline's own PiiVault mapping table gives the data controller the ability to re-identify. Confirmed by GDPR Recital 26, GDPR Article 4(5), and EDPB Guidelines 01/2025 (January 2026) which explicitly state that deletion of the mapping table does NOT automatically make pseudonymized data anonymous unless irreversibility conditions are met. Under CCPA, the data-level GLBA exemption is narrow (applies only to information collected pursuant to GLBA, not all data held by a financial institution) and the CCPA "deidentified" standard (Civil Code 1798.140(m)) cannot be met while the vault exists.

Critical legal protections available:
1. GDPR Article 17(3)(b) legal obligation exemption (SOX/GLBA 7-year retention overrides erasure for covered records)
2. CCPA 1798.105(d)(8) legal obligation exemption
3. Vault `Status='deleted_per_request'` functioning as **practical inaccessibility** — not technically satisfying the strict GDPR irreversibility standard for anonymization but widely used in industry (MiFID II + GDPR parallel in financial sector)

The replay capability creates **active legal exposure**: restoring a pre-deletion Parquet snapshot for a subject who exercised right-to-deletion and failing to immediately re-delete constitutes a CCPA violation by regulatory and practitioner consensus. GDPR guidance is equivalent. The safe design requires a **replay-time CCPA filter** — a deletion-aware restore pattern that treats the `CcpaDeletionLog` as a tombstone applied at replay time.

**Confidence**: medium-high on regulatory classification; medium on vault-soft-delete sufficiency (EDPB position clear; DPA enforcement action record thin). Legal counsel review of the vault-soft-delete design vs EDPB 01/2025 is REQUIRED before Phase 2 production go-live.

---

## RQ1: Tokenized-PII Legal Classification

### Findings

**Finding RQ1-1**: GDPR classifies tokenized data with controller-accessible vault as personal data (Recital 26 + Article 4(1) + Article 4(5)). Per gdpr-info.eu/art-4-gdpr/ + gdpr-info.eu/recitals/no-26/: "All means reasonably likely to be used by the controller... to identify the natural person directly or indirectly." Our PiiVault holds the token-to-plaintext mapping — controller possesses additional information. Personal data, not anonymous.

**Finding RQ1-2**: EDPB Guidelines 01/2025 (adopted January 2026; verified at edpb.europa.eu) explicitly confirm vault deletion does NOT make pseudonymized data anonymous: "The deletion of the additional information does not automatically render the pseudonymised data anonymous. The conditions of anonymisation would have to be met (i.e., anonymisation is irreversible)."

**Finding RQ1-3**: CCPA deidentification standard (California Civil Code 1798.140(m)) cannot be met while the vault exists. Requires "reasonable measures to ensure the information cannot be associated with a consumer" AND public commitment to maintain in deidentified form. PiiVault existence violates both requirements.

**Finding RQ1-4**: CCPA pseudonymization definition (1798.140(aa)) confirms pseudonymized data remains personal information; only deidentified standard removes data from CCPA scope.

**Finding RQ1-5**: IAPP analysis "CCPA offers minimal advantages for deidentification, pseudonymization, and aggregation" — pseudonymized data remains subject to CCPA obligations.

### Classification

Our Parquet snapshots with tokenized PII columns fall squarely into:
- **GDPR**: "Pseudonymized data" under Article 4(5) — still personal data, right to erasure applies
- **CCPA**: personal information under 1798.140 — right to delete applies

NOT "deidentified, exempt" while PiiVault exists.

---

## RQ2: Immutable Audit Data Exemptions

### Findings

**Finding RQ2-1**: GDPR Article 17(3) exemptions verbatim:
- (a) freedom of expression
- (b) compliance with legal obligations OR public interest tasks
- (c) public interest in public health
- (d) archiving, research, or statistical purposes
- (e) establishment/exercise/defense of legal claims

**Article 17(3)(b) is the operative exemption** for financial records. SOX/GLBA statutory retention triggers it.

**Finding RQ2-2**: SOX 802 (18 U.S.C. § 1519) mandates 7-year retention of audit records. GLBA requires financial records retention to demonstrate compliance with federal financial privacy requirements. For DNA/CCM/EPICOR financial sources, Bronze SCD2 rows and Parquet snapshots containing financial transaction records almost certainly fall within SOX-covered audit records.

**Finding RQ2-3**: CCPA 1798.105(d)(8) provides equivalent legal-obligation exemption: business not required to comply with deletion request if must maintain personal information to "comply with a legal obligation."

**Finding RQ2-4**: CCPA 1798.105(b) backup/archival delay provision: deletion compliance can be **delayed** until backup systems are "restored or re-accessed or used for a disclosure, sale, or commercial purpose." This is a **delay provision, NOT an exemption** — deletion obligation revives at access time.

**Finding RQ2-5**: GDPR Article 17(3)(d) "archival" narrowly scoped to "public interest, scientific or historical research purposes" — does NOT apply to commercial operational archives.

### Recommendation

1. SOX-covered Bronze rows + Parquet snapshots: Article 17(3)(b) + CCPA 1798.105(d)(8) apply. Requires documented legal hold record per D30 + CcpaDeletionLog showing legal exception invoked.
2. Parquet snapshots as cold archives: CCPA 1798.105(b) allows delay of deletion, BUT obligation revives when archive accessed for pipeline replay.
3. Article 17(3)(d) does NOT apply to our operational archives.
4. Legal counsel determination REQUIRED to confirm SOX coverage scope for specific data elements.

---

## RQ3: Replay Capability Legal Exposure

### Findings

**Finding RQ3-1**: CCPA restoration of pre-deletion backup = violation. TechTarget analysis (primary practitioner source): "if a company receives a deletion request, removes the data, then later restores a pre-deletion backup due to data loss, the deleted record is restored — thereby resulting in a CCPA violation."

**Finding RQ3-2**: CCPA 1798.105(b) delay provision applies ONLY until archive is "accessed or used." Once a Parquet snapshot is replayed (accessed/used), the deletion obligation for that subject's data REVIVES IMMEDIATELY. The replay event itself triggers the obligation.

**Finding RQ3-3**: MiFID II / GDPR paradox precedent — crypto-shredding as accepted industry pattern. Per VeritasChain analysis: PII fields encrypted per-subject with AES-256-GCM keys; key destruction renders PII "computationally unrecoverable." Critical distinction: vault-token model is WEAKER than crypto-shredding because tokens in Parquet still REFERENCE the vault row even after Status='deleted_per_request' — "the token still references deleted data, potentially violating GDPR's requirement that erasure be demonstrably irreversible."

**Finding RQ3-4**: GDPR functional test = irreversibility required, not practical inaccessibility. EDPB 01/2025: "deletion of additional information does not automatically render pseudonymised data anonymous." Vault Status='deleted_per_request' FAILS irreversibility test.

**Finding RQ3-5**: Regulatory "deletion" test is functional inaccessibility, not bit-level erasure, but standard remains contested. ICO/CNIL generally accept practical inaccessibility; EDPB 01/2025 standard for crossing into anonymized-non-personal-data is irreversibility. Conservative compliance: treat vault-soft-delete as practical inaccessibility + document residual risk.

### Replay Exposure Recommendation

Replay creates **active, not hypothetical, legal exposure**:
1. CCPA: replaying pre-deletion snapshot ≡ restoring backup → deletion obligation revives at access time
2. GDPR: replay re-introduces pseudonymized personal data into active processing → no lawful basis for erased subjects (assuming no Article 17(3) exemption)
3. Capability existing without exercise does NOT itself constitute violation; violation occurs at moment of replay without filtering deleted subjects

---

## RQ4: Industry Patterns

### Findings

**Finding RQ4-1 (Snowflake)**: Official guidance — segregate PII into dedicated tables; Time Travel windows ≤30 days for PII tables; track erasure requests. Snowflake does NOT document crypto-shredding pattern. Philosophy: "compliance is not a function of your database but rather a function of the design you choose."

**Finding RQ4-2 (Apache Iceberg)**: Three documented patterns:
1. DELETE + compaction + expire_snapshots (physical removal)
2. Crypto-shredding (per-user key, destroy on deletion request) — "faster compliance without physical file deletion"
3. Flag-for-deletion + batch delete operations

For REPLAY scenarios, only pattern (2) survives without post-replay re-deletion.

**Finding RQ4-3 (Databricks Delta Lake)**: DELETE + VACUUM pattern. "delete PII from bronze layer first, then propagate changes to silver and gold layers." Does NOT provide guidance on replay/restore scenarios.

**Finding RQ4-4 (Banking sector)**: CCPA GLBA exemption is **data-level**, not entity-level. Applies only to "personal information collected, processed, sold, or disclosed pursuant to" GLBA — specifically Nonpublic Personal Information (NPI). Marketing data, audit infrastructure metadata REMAIN subject to CCPA. Financial institutions must conduct data-element-level classification.

**Finding RQ4-5 (Apache Iceberg V3)**: Row lineage (_row_id + _last_updated_sequence_number) enables precise tracking of row creation + deletion. Supports "GDPR right-to-be-forgotten requests and regulatory compliance deletes without write amplification."

### Industry Pattern Summary

Dominant pattern for immutable-archive + deletion-obligation: **crypto-shredding with per-subject keys**, NOT vault-soft-delete. Our vault-token model is between crypto-shredding (stronger) and no protection (weaker). Vault-soft-delete is WEAKER than crypto-shredding for GDPR because: (a) mapping table still exists; (b) reversibility preserved in theory. **Most significant legal risk finding in this research.**

---

## RQ5: Idempotency-Preserving Deletion Design Patterns

### Findings

**Finding RQ5-1 (Tombstone-style)**: Apache Iceberg + Dremio docs document "flag-for-deletion" — deletion recorded as separate row (tombstone) rather than physical delete. For replay: if CcpaDeletionLog treated as tombstone table, replay can JOIN against it and suppress rows deterministically. **Recognized pattern.**

**Finding RQ5-2 (Time-aware replay treating CCPA as historical SCD2 close)**: NO published primary source found documenting "time-aware replay" as named pattern. However logical construction from MiFID II/GDPR paradox + Iceberg row lineage: replay should be treated as "what would have happened at time T if we had this data?" — and if subject deleted at T1 < T, replay should produce closed SCD2 row as of T1. **Architectural implication, not externally-documented pattern.**

**Finding RQ5-3 (Per-replay CcpaDeletionLog snapshot binding)**: NO external source documents this specific pattern. Closest published pattern is Databricks medallion approach (delete from bronze, propagate to silver/gold) — structurally similar but not replay-specific.

**Finding RQ5-4 (CCPA 1798.105(b) backup delay = only statutory safe harbor)**: Restoration of backup containing deleted-subject data creates violation obligation at access time. If Parquet snapshot replayed solely for SCD2 corruption recovery (not commercial disclosure), the deletion obligation for subjects in that snapshot REVIVES at access time (the replay itself). Organization not in violation for HAVING retained pre-deletion snapshot in archive storage; obligation must be satisfied at moment of replay.

### Recommendation

Deletion-aware replay design requires THREE elements:

1. **CcpaDeletionLog as replay-time filter**: before promoting any SCD2 row, JOIN against CcpaDeletionLog + suppress rows for any token with Status='deleted_per_request' at time of replay. Deterministic + idempotent (same snapshot twice → same Bronze output).

2. **Replay audit row**: the CCPA-deletion stored procedure (per CLAUDE.md SP family registry)/CcpaDeletionLog must capture that a replay occurred for snapshot containing deleted-subject rows, and that those rows were filtered. Audit trail proving compliance at replay time.

3. **Temporal scoping**: subjects with SOX-covered records (Article 17(3)(b) / CCPA 1798.105(d)(8) legal-obligation exemption) — filter should NOT suppress those rows; instead record legal exception in replay audit row. Requires per-row legal-hold checking during replay.

---

## Synthesis: Implications for D2 + replay_parquet_range Design

**Constraint identified**: Parquet snapshots containing tokenized PII are personal data under BOTH GDPR + CCPA. Vault-soft-delete pattern provides practical inaccessibility but does NOT meet EDPB irreversibility standard for full anonymization. **Residual regulatory risk that must be disclosed in compliance documentation.**

**Design space narrowed to**:
1. Replay must query CcpaDeletionLog at replay-time + suppress or legal-hold rows per subject. NON-NEGOTIABLE per CCPA 1798.105(b).
2. CcpaDeletionLog serves DUAL use: (a) the CCPA-deletion stored procedure (per CLAUDE.md SP family registry) primary deletion-state source; (b) replay-time tombstone for deletion-aware SCD2 promotion. NOT a new artifact — extends existing.
3. Snapshots for subjects with active legal holds (SOX/GLBA): survive replay with legal exception recorded.
4. Pipeline should NOT wait until "archive is restored" to determine deletion status (per CCPA 1798.105(b) semantics). Pre-filter at replay initiation using CURRENT CcpaDeletionLog state.

**Open D-N candidates**:

- **D-N.a candidate**: "Vault-soft-delete (Status='deleted_per_request') accepted as sufficient for CCPA right-to-delete compliance for non-GLBA-exempt data, with residual GDPR risk documented and reviewed annually" — D30 currently implies this but EDPB 01/2025 makes the decision sharper. Requires legal counsel sign-off.

- **D-N.b candidate**: "`replay_parquet_range` MUST apply CcpaDeletionLog filter as Step 0 before any Bronze promotion" — operational design decision lockable WITHOUT legal counsel.

---

## Sources Cited

| # | URL | Authority |
|---|---|---|
| 1 | https://gdpr-info.eu/art-4-gdpr/ | Primary: GDPR text |
| 2 | https://gdpr-info.eu/art-17-gdpr/ | Primary: GDPR text |
| 3 | https://gdpr-info.eu/recitals/no-26/ | Primary: GDPR text |
| 4 | https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=1798.140. | Primary: California statute |
| 5 | https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?sectionNum=1798.105.&lawCode=CIV | Primary: California statute |
| 6 | EDPB Guidelines 01/2025 press release | Primary: EDPB official guidance |
| 7 | EDPB Guidelines 01/2025 PDF | Primary: EDPB official guidance |
| 8 | ICO right to erasure guidance | Primary: DPA official guidance (UK) |
| 9 | SEC records retention rules 2003 | Primary: SEC regulatory text |
| 10 | Databricks GDPR Delta docs (AWS) | Primary: Databricks official documentation |
| 11 | Snowflake GDPR compliance blog | Primary: Snowflake official blog |
| 12 | AWS Iceberg V3 deletion vectors blog | Primary: AWS official documentation |
| 13 | Dremio: Iceberg + right to be forgotten | Secondary: technical analysis |
| 14 | DEV Community: MiFID II / GDPR crypto-shredding paradox (VeritasChain) | Community: financial sector analysis |
| 15 | Davis Wright Tremaine: GLBA/CCPA exemption | Secondary: law firm analysis |
| 16 | TechTarget: backup compliance CCPA | Secondary: practitioner analysis |
| 17 | Trilateral Research: EDPB 01/2025 unpacking | Secondary: legal analysis |
| 18 | Mirsky & Company: encrypted data GDPR 2025 | Secondary: legal analysis |
| 19 | IAPP: CCPA pseudonymization minimal advantage | Secondary: professional privacy analysis |
| 20 | Ryft: GDPR compliance with Apache Iceberg | Secondary: technical analysis |
| 21 | Privacy World: financial institution CCPA | Secondary: practitioner analysis |

---

## Confidence Assessment

| Research question | Confidence |
|---|---|
| RQ1 (Tokenized-PII legal classification) | HIGH — GDPR Article 4(1)/(5), Recital 26, EDPB 01/2025 unambiguous; CCPA 1798.140 unambiguous; 5 primary sources converge |
| RQ2 (Immutable audit data exemptions) | HIGH on existence; MEDIUM on scope — requires legal counsel determination for our pipeline's data |
| RQ3 (Replay capability legal exposure) | MEDIUM-HIGH — CCPA 1798.105(b) clear; GDPR equivalent clear in principle; specific "capability without exercise" question has no direct regulatory ruling |
| RQ4 (Industry patterns) | MEDIUM — crypto-shredding consensus; vault-token model less common in published guidance |
| RQ5 (Idempotency-preserving deletion patterns) | LOW-MEDIUM — no external source documents replay-time tombstone pattern specifically; three-element recommendation is research synthesis |

**Overall**: MEDIUM. Classification findings (RQ1) HIGH-confidence and load-bearing. Exemption scope (RQ2) + vault-soft-delete sufficiency (RQ3) BOTH require legal counsel input before production go-live.

---

## Counter-Evidence

**Against "vault-soft-delete creates GDPR violation"**: Multiple practitioner sources (Conduktor, Seald, EncryptionConsulting) assert crypto-shredding (including vault key deletion) satisfies GDPR erasure in practice. DPAs have NOT issued formal enforcement decisions against vault-soft-delete patterns in financial sector pipelines as of research date. Some DPAs accept functional inaccessibility as satisfying the spirit of Article 17.

**Against "CCPA right-to-delete applies to financial pipeline data"**: GLBA data-level exemption covers "information collected, processed, sold, or disclosed pursuant to GLBA." If DNA/CCM/EPICOR source systems generate exclusively GLBA-covered NPI, CCPA right-to-delete may not apply at data-element level. Requires legal counsel determination.

**Against "replay creates imminent legal exposure"**: 1798.105(b) delay provision means pipeline NOT in violation for retaining pre-deletion Parquet snapshots in archive. Exposure materializes only at replay execution. If SCD2 corruption recovery scenarios are rare (years-apart), practical risk is low.

---

## What This Research Does NOT Cover

1. Whether specific DNA/CCM/EPICOR source data qualifies as GLBA-covered NPI — requires source system classification
2. Whether CCPA applies given potential GLBA data-level exemption scope — requires legal counsel
3. Regulatory enforcement risk calibration — outside research scope
4. GDPR applicable law question — depends on whether source systems contain EU data subjects
5. EDPB 01/2025 post-public-consultation final guidelines — draft text authoritative but may shift

---

## Recommended Actions

1. **Immediate design action (no legal counsel required)**: Add CcpaDeletionLog filter as Step 0 of any `replay_parquet_snapshot()` or `replay_parquet_range()`. Suppresses rows for subjects with Status='deleted_per_request' AND no applicable legal hold. D-N.b candidate — operational decision lockable NOW.

2. **Legal counsel required before production**: Commission written determination from qualified California privacy attorney on: (a) GLBA data-level exemption application to pipeline's source data; (b) vault-soft-delete satisfaction of GDPR Article 17; (c) SOX 802 creation of Article 17(3)(b) / CCPA 1798.105(d)(8) exemptions. Track as open item in D30's compliance record.

3. **D30 update candidate**: D30 currently states crypto-shredding-equivalent satisfies CCPA deletion. EDPB 01/2025 finding makes this sharper. Acknowledge in D30 as residual risk with documented compliance posture + annual review cadence.

4. **R09 risk update candidate**: R09 (PII compliance audit timing — Low × High = 3) may warrant escalation in light of replay exposure. Replay is non-obvious path to re-introducing deleted-subject data. If replay-time filter implemented, risk mitigated at technical level.

5. **Validation gate note**: D30's "crypto-shredding equivalent" language may not be defensible in light of EDPB 01/2025. Gate 2 QA reviewer should confirm whether D30 needs strengthened posture disclosure.

---

## Cross-References

- D2 (Parquet replaces Stage layer) + D16 (per-run Parquet snapshots) — immutable snapshots creating the replay scenario
- D26 (append-only PiiTokenProvenance + PiiVault lifecycle) — vault soft-delete mechanism under legal review
- D30 (7-year retention + CCPA/CPRA/GLBA alignment) — exemption candidate for legal-obligation override
- D102 (AES-256-GCM crypto pin) — encryption at rest but vault mapping preserved; distinction from true crypto-shredding
- RB-10 (CCPA right-to-deletion runbook) — operational procedure creating deletion records the replay filter must consult
- R09 (PII compliance audit timing risk) — this research may warrant re-assessment
- B-341 (G1 design target per research request) — replay_parquet_range with CCPA-aware filter
- `docs/migration/D2_GAP_RESOLUTION_PLAN_2026-05-17.md` §2 — G1 design Option A4 validated by this research
- `docs/migration/D2_EXECUTION_PLAN_PARQUET_DIRECT_SCD2_2026-05-17.md` §5.4 + §11 Risk-NEW-D
