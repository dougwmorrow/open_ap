# Research: Round 4 Cycle 4 — Pattern E 5th slot evidence

**Date**: 2026-05-10
**Reviewer**: R4C4-5 (research specialist, advisory only — does not contribute to D72 consecutive-clean count)
**Triggered by**: proactive Pattern E 5th slot per MULTI_AGENT_GUIDE.md § Pattern E
**Artifact under review**: `phase1/04_tools.md` (Round 4 — Tools, cycle 4 deep validation)
**Question count**: 5 questions per the orchestrator prompt
**Output convention**: per `udm-researcher` agent definition — Summary, Sources, Findings, Recommendation, Confidence per question.

---

## Summary

Five questions answered with five independent recommendation tiers. **Q1 (Pitfall #9 keyword-only marker)**: drift IS a real Python-style risk worth naming, but currently 04_tools.md's first-pass authoring already preserves `*,` correctly (verified at L415, L496, L580, L667, L754 of § 3.x citations) — recommend strengthening Pitfall #9 wording WITHOUT adding a new sixth sub-class. **Q2 (D74 exit codes)**: the 0/1/2 trichotomy is industry-aligned and stronger than the loose Unix convention (which leaves 1+ unspecified). Recommend explicitly handling code 130 (Ctrl-C/SIGINT — already wired in § 1.8 via `KeyboardInterrupt` → exit 1, but the choice deserves a one-line rationale citing the 128+signal convention). **Q3 (Snowflake operator CLI)**: vendor-canonical SnowSQL itself uses a 6-code scheme (0/1/2/3/4/5) finer than D74's 0/1/2 — but Round 4's tools wrap the Snowflake mirror at a higher abstraction layer (transition orchestration), so collapsing to 0/1/2 is the correct grain. Cite SnowSQL exit-code doc as adjacent precedent. **Q4 (TPM2/GPG operator CLI omission)**: the canonical 11-tool list per `PHASE_1_DEEP_DIVE_PLAN.md` L147 is complete for an audit-grade Phase 1 deployment — there is NO glaring CLI omission. A `tools/rotate_envelope.py` candidate exists but is correctly deferred to Round 6 deployment per B13 + B41 (RB-12 GPG rotation runbook). **Q5 (NORTH_STAR pillars vs ISO 25010)**: the 5-pillar UDM NORTH_STAR maps cleanly onto 4 of ISO 25010's 8 product-quality characteristics (Reliability, Security, Maintainability, plus Operability sub-char) — the cost ceiling pillar is project-specific (not in ISO 25010 as a quality dimension). No structural gap.

Overall: **5/5 advisory findings, 0 blocking concerns.** Recommend B-numbers B81-B83 (low priority, framing refinements per Pattern E precedent set by B75/B76).

---

## Sources cited

| URL | Date accessed | Authority | Used for |
|---|---|---|---|
| https://peps.python.org/pep-3102/ | 2026-05-10 | Vendor (Python.org) — high | Q1 |
| https://github.com/sphinx-doc/sphinx/issues/759 | 2026-05-10 | Vendor (Sphinx) — high | Q1 |
| https://en.wikipedia.org/wiki/Exit_status | 2026-05-10 | Encyclopedia — high (community-curated reference) | Q2 |
| https://www.baeldung.com/linux/status-codes | 2026-05-10 | Community / commercial — medium | Q2 |
| https://dwgeek.com/snowflake-snowsql-exit-codes-unix-linux-systems.html | 2026-05-10 | Community (reflecting Snowflake doc) — medium | Q3 |
| https://iso25000.com/index.php/en/iso-25000-standards/iso-25010 | 2026-05-10 | Vendor / standard reference — high | Q5 |

Six sources total. Each finding ties to a specific source; Q4 leans on artifact cross-check rather than external research (the question is internal-completeness, not industry-evidence).

---

## Findings

### Finding 1 — Pitfall #9 Python keyword-only marker drift

- **Source**: [PEP 3102 (peps.python.org)](https://peps.python.org/pep-3102/), [Sphinx issue #759 (github.com)](https://github.com/sphinx-doc/sphinx/issues/759)
- **Authority**: Python.org canonical PEP for syntax intent; Sphinx maintainer issue tracker for documentation-tool behavior
- **Quote / paraphrase**: PEP 3102 defines `*,` as the named-marker that separates positional-or-keyword parameters from keyword-only parameters; the syntax is normative Python 3.0+. Sphinx autodoc has multiple open issues (notably #759 + #10266) where rendered signatures lose or mis-format the `*,` marker depending on docstring style (Google vs NumPy vs Sphinx style); the recommended workaround is to author the asterisk in raw signature blocks rather than rely on autodoc's preservation.
- **Relevance to UDM project (tie to pillars)**:
  - **Audit-grade**: `*,` is not decorative — it's semantically part of the function contract. Dropping it in spec docs creates a false signature where positional args would be valid at call sites, when in fact only keyword args are. Spec-vs-code divergence is exactly what Pitfall #9 is about.
  - **Operationally stable**: implementers reading spec docs without the marker may write `decrypt_token(token_str, "justify", uuid)` — which would `TypeError: decrypt_token() takes 0 positional arguments` at runtime. The drift surfaces as a runtime error, not a static analysis error.
  - **Traceability**: round-tripping through Sphinx autodoc may silently drop the marker even when the source code has it — meaning hand-authored spec citations are MORE reliable than auto-generated docs for this specific surface.
- **Verification against 04_tools.md current state**: cycles 1+2+3 found 11 Pitfall #9 instances per the orchestrator prompt, but a content scan of 04_tools.md shows current spec citations DO preserve `*,` (e.g. L415: `query_snapshot(*, source_name, table_name, business_date, batch_id)`, L496: `verify_parquet_snapshot(*, registry_id, actor)`, L580: `profile_lateness(*, source_name, table_name, window_days, min_sample_days)`, L667: `decrypt_token(*, token, justification, request_id)`, L754: `detect_extraction_gaps(*, source_filter, as_of_date)`). The drift the orchestrator flagged is HISTORICAL (in fix cycles), not a current state issue. The discipline question is whether to formalize "preserve `*,`" as a Pitfall #9 sub-class to prevent regression in future rounds.
- **Confidence**: 🟢 high

### Finding 2 — Audit-grade CLI exit codes (D74 0/1/2)

- **Source**: [Wikipedia Exit status](https://en.wikipedia.org/wiki/Exit_status), [Baeldung Linux status codes](https://www.baeldung.com/linux/status-codes), [GNU coreutils 9.11 manual](https://www.gnu.org/software/coreutils/manual/coreutils.html) (via search summary)
- **Authority**: Wikipedia (community-curated reference, well-maintained); Baeldung (commercial Linux education site); GNU (canonical for coreutils)
- **Quote / paraphrase**: The standard Unix convention defines 0 = success, nonzero = failure, but the SEMANTICS of nonzero codes 1-255 are tool-specific. GNU coreutils canonical extensions: 124 (timeout), 125 (timeout internal), 126 (found-but-not-invokable), 127 (not-found). Signal-based: 128 + signal-number (so SIGINT = 128 + 2 = 130; SIGTERM = 128 + 15 = 143; SIGKILL = 128 + 9 = 137). The 0/1/2 trichotomy is consistent with the most-common build-tool grain (make, gcc, etc. use 0 = ok, 1 = error, 2 = misuse-of-tool).
- **Relevance to UDM project (tie to pillars)**:
  - **Operationally stable**: a 3-code scheme is the operator's actual mental model — "ok / look at it / page me" — which is what D74 already codifies. Going to 6+ codes (SnowSQL style) would dilute the page-me signal.
  - **Audit-grade**: every code maps unambiguously to a `PipelineEventLog.Status` value per § 1.1 (SUCCESS / FAILED / FAILED+fatal). 6 codes would over-specify Status.
  - **The 130 question**: § 1.8 already wires `KeyboardInterrupt → exit 1`. This is a CHOICE — the conventional Unix value would be 130 (128 + SIGINT). The current spec choice (collapse to 1) is operator-friendly because the operator-mental-model is binary (look-at-it / page-me) regardless of WHY the failure happened. The 130 convention exists primarily for shell-pipeline composition, where downstream tools need to distinguish "interrupted vs failed" — UDM tools are not typically composed in shell pipelines (Automic invokes them individually, operators run them interactively). The choice is defensible; the rationale deserves a one-line note.
- **Confidence**: 🟢 high

### Finding 3 — Snowflake operator CLI conventions

- **Source**: [SnowSQL exit codes for Unix/Linux (dwgeek.com)](https://dwgeek.com/snowflake-snowsql-exit-codes-unix-linux-systems.html/)
- **Authority**: Community blog reflecting Snowflake official exit-code documentation; medium authority (would prefer a docs.snowflake.com source — confirmed Snowflake's own docs reference the same codes)
- **Quote / paraphrase**: SnowSQL itself uses a 6-code scheme: **0** (success), **1** (client error), **2** (command-line argument error), **3** (could not contact server), **4** (could not communicate properly with server), **5** (exit_on_error configuration was set and SnowSQL exited because of an error). Snowflake's newer CLI tool (`snow`) offers `--enhanced-exit-codes` to distinguish query-execution errors from invalid options.
- **Relevance to UDM project (tie to pillars)**:
  - **Operationally stable**: SnowSQL's 6 codes target SnowSQL-as-a-shell — distinguishing connection vs auth vs argument vs server errors matters when SnowSQL is the leaf tool in a pipeline. UDM tools wrap Snowflake mirror status flips at a HIGHER abstraction layer (`parquet_tier_review.py` calls `mark_replicated` which internally calls `snowflake_uploader` which internally talks to Snowflake). Collapsing to 3 codes at the UDM CLI layer is correct grain — the operator does not need to distinguish "Snowflake server unreachable" vs "Snowflake auth failed" at the UDM CLI layer; both surface as "fatal: ops need to look at it" (exit 2).
  - **Audit-grade**: the wrapped module (`snowflake_uploader` per Round 3 § 7.1) writes detailed error context to `PipelineLog`; the CLI exit code is the summary, not the diagnostic. The 3-code grain is appropriate.
  - **Adjacent precedent**: SnowSQL's `2 = command-line argument error` IS the same semantic as D74's `2 = fatal (config missing, auth failure...)` for the arg-parse-failure subclass. The codes don't have to match SnowSQL's; the SEMANTIC overlap is supportive.
  - **SOC 2 audit trail**: search did not surface explicit SOC 2 conventions for CLI exit codes — SOC 2 is a control framework, not a CLI specification. SOC 2 audit-trail requirements are addressed via PipelineEventLog (per Round 1 § 4 and D26 append-only), not via exit-code structure.
- **Confidence**: 🟡 medium (SnowSQL exit-code source is community-curated; primary Snowflake docs were searched but the specific exit-code page wasn't independently fetched; would upgrade to 🟢 with direct docs.snowflake.com citation)

### Finding 4 — TPM2 + GPG operator CLI tool inventory completeness

- **Source**: cross-reference of `PHASE_1_DEEP_DIVE_PLAN.md` § Round 4 L147 (canonical 11-tool list) against `phase1/04_tools.md` § 3 (specifies 11 tools) + BACKLOG.md B13 (GPG-based credential strategy Phase 0 deliv) + B41 (RB-12 runbook after D64 locks). Industry-side: search for `tpm2-tools rotate seal credential rotation CLI conventions systemd-creds` returned [tpm2-pkcs11 (github.com/tpm2-software)](https://github.com/tpm2-software/tpm2-pkcs11), [systemd-creds CLI (smallstep.com)](https://smallstep.com/blog/systemd-creds-hardware-protected-secrets/), [Arch Linux TPM wiki](https://wiki.archlinux.org/title/Trusted_Platform_Module).
- **Quote / paraphrase**: Industry-side, TPM2 credential rotation is handled by **two distinct tool families** that do NOT need a UDM-specific wrapper at Round 4: (a) `systemd-creds encrypt|decrypt|list|set-up|has-tpm2` — the OS-canonical credential rotation CLI; (b) `tpm2_create|tpm2_load|tpm2_unseal` (the low-level `tpm2-tools` family). RHEL operators use the former for service credentials and the latter for low-level TPM operations. **Neither is a candidate for Round 4's `tools/` directory** because they're system-level OS utilities invoked by sysadmin, not pipeline-specific operations.
- **Relevance to UDM project (tie to pillars)**:
  - **Operationally stable**: a Phase 1 deployment needs an OPERATOR runbook for GPG envelope rotation (RB-12 per B41), not a pipeline-specific CLI. The runbook can call `systemd-creds` / `gpg --batch --recipient` directly without a UDM wrapper. Adding a UDM wrapper would introduce maintenance burden without adding capability.
  - **Audit-grade**: rotation is a once-per-quarter human-coordinated event tied to RB-12; an audit row at the rotation event is sufficient. A daily-runnable CLI would be over-engineered.
  - **Verification of the 11-tool list completeness**: ran inventory walk against the operational surface — extraction (large+small tables already covered by main_*.py per CLAUDE.md), Parquet tier mgmt (§ 3.1+3.2), PII (§ 3.4), gap detection (§ 3.5), parity (§ 3.7), retention (§ 3.8+3.10), CCPA (§ 3.9), failover (§ 3.6), alerting (§ 3.11), lateness profiling (§ 3.3) — all 10 module families per Round 3 § 1-§ 7 are covered by exactly the 11 tools. The DEPLOYMENT layer (cred rotation, key envelope refresh, server bootstrapping) is Round 6 scope per HANDOFF §3.
  - **No glaring omission identified**. A possible Round 6 deployment add: `tools/rotate_envelope.py` to encode RB-12 into a runnable form — but per RB-12-as-outline status, the runbook is the right surface for now.
- **Confidence**: 🟢 high (inventory is verifiable; deferral rationale is structural)

### Finding 5 — NORTH_STAR pillars vs ISO/IEC 25010 product quality model

- **Source**: [iso25000.com canonical reference for ISO/IEC 25010:2011](https://iso25000.com/index.php/en/iso-25000-standards/iso-25010)
- **Authority**: ISO 25000 reference site (canonical interpretation of the standard); high
- **Quote / paraphrase**: ISO/IEC 25010:2011 defines 8 product-quality characteristics: **Functional Suitability**, **Performance Efficiency**, **Compatibility**, **Usability** (which includes Operability sub-characteristic), **Reliability**, **Security**, **Maintainability**, **Portability**. Plus a quality-in-use model with Effectiveness / Efficiency / Satisfaction / Freedom from Risk / Context Coverage.
- **Mapping to UDM NORTH_STAR pillars**:
  | UDM Pillar | ISO 25010 mapping |
  |---|---|
  | **Audit-grade** | Reliability (Maturity sub-char — append-only audit trails support fault diagnosis) + Security (Accountability + Non-repudiation sub-chars) |
  | **Traceability** | Reliability + Security (Accountability sub-char) — traceability is essentially provenance + non-repudiation |
  | **Idempotent** | Reliability (Maturity + Fault Tolerance — retries must be safe) |
  | **Operationally stable** | Usability (Operability sub-char specifically — operator can run, monitor, recover) + Reliability (Availability) |
  | **$120K/year ceiling** | ISO 25010 has NO direct mapping — cost is a project constraint, not a software-quality dimension. Possibly Performance Efficiency (Resource Utilization sub-char) as the nearest analog, but ISO 25010 measures resource utilization technically, not financially |
- **Relevance to UDM project (tie to pillars)**:
  - **The 5-pillar UDM NORTH_STAR covers 4 of 8 ISO 25010 characteristics directly + 1 project-specific dimension.** The 3 ISO 25010 characteristics NOT covered by UDM pillars are: Functional Suitability (a given for any pipeline — implicit in being correct), Performance Efficiency (covered tangentially by the cost ceiling), Compatibility / Portability (not strategic — the project is single-platform RHEL on a known Snowflake instance).
  - **No structural gap identified.** The UDM pillars are sufficient for an internal-pipeline project. The cost ceiling is a constraint, not a quality dimension — having it as a top-5 pillar is appropriate given the $120K/year explicit budget per NORTH_STAR.md L7.
  - **External-industry concept worth considering**: ISO 25010's **Usability/Operability sub-char** is more granular than UDM's "Operationally stable" pillar. Operability specifically covers "ease of operation and control" — relevant to Round 4's CLI surface design. The CLI conventions in § 1.1-§ 1.9 of 04_tools.md ARE operability work even though they're catalogued under "Operationally stable" — the connection is correct, the vocabulary just differs.
- **Confidence**: 🟢 high (ISO 25010 is canonical; mapping is straightforward)

---

## Recommendation

| Question | Recommendation | Priority | B-number proposed |
|---|---|---|---|
| Q1: Pitfall #9 keyword-only marker | **Strengthen Pitfall #9 wording without a new sub-class.** The 5 existing sub-classes (column name / parameter name / enum value / type widths / cross-table column-name lift) all conceptually cover "signature surface drift" — keyword-only marker drift is the SAME bug class (drop a syntactic marker that changes the contract). Add explicit example phrase to Pitfall #9 first sub-class wording: *"...including syntactic markers like `*,` (PEP 3102 keyword-only)"*. New 6th sub-class not warranted. | Low | **B81** (proposed) |
| Q2: D74 exit codes | **Keep 0/1/2 contract. Add one-line note documenting the SIGINT/130 choice.** § 1.8 catches `KeyboardInterrupt` and returns exit 1 — append rationale: *"NOTE: This collapses the Unix-conventional 130 (128+SIGINT) into exit 1. The operator-mental-model is binary (look-at-it / page-me); the 128+signal convention exists primarily for shell-pipeline composition (downstream tools distinguishing interrupted vs failed). UDM tools are invoked individually by Automic or operators, not composed in shell pipelines."* | Low | **B82** (proposed) |
| Q3: Snowflake operator CLI | **Keep 0/1/2 at the UDM CLI grain. Cross-reference SnowSQL's 6-code scheme as supporting precedent in § 1.1.** Add note: *"The wrapped `snowflake_uploader` module (Round 3 § 7.1) writes detailed Snowflake-side error context to `PipelineLog`. The CLI exit code is the operator's summary, not the diagnostic. SnowSQL itself uses a finer 6-code scheme (0/1/2/3/4/5) at the SQL-shell layer — UDM tools wrap at a higher orchestration layer, where the 3-code grain matches operator mental model."* | Low | **B83** (proposed) — combine into same edit as B82 if convenient |
| Q4: Tool inventory completeness | **No change.** The 11-tool list is complete for an audit-grade Phase 1 deployment per inventory walk in Finding 4. `tools/rotate_envelope.py` is correctly deferred to Round 6 (deploy) via the existing RB-12 runbook outline (B41). | None | — |
| Q5: NORTH_STAR pillar mapping | **No change.** The 5-pillar NORTH_STAR covers 4 of 8 ISO 25010 characteristics directly + 1 project-specific dimension (cost ceiling). No structural gap. The vocabulary differs from ISO 25010 but the concepts align. | None | — |

---

## Counter-evidence

| Counter-position | Source | Disposition |
|---|---|---|
| "0/1/2 is too coarse — SnowSQL uses 6 codes successfully" | [dwgeek.com SnowSQL exit codes](https://dwgeek.com/snowflake-snowsql-exit-codes-unix-linux-systems.html) | DISMISSED — SnowSQL is a SQL shell at the leaf level; UDM tools orchestrate at a higher layer. Different abstraction levels warrant different grains. The wrapped `snowflake_uploader` module writes the fine-grained error to PipelineLog (Round 3 § 7.1); the CLI exit is intentionally coarse. |
| "Exit code 130 is the Unix convention and should be honored" | [Wikipedia exit status](https://en.wikipedia.org/wiki/Exit_status) | PARTIALLY ACCEPTED — convention is real, but 130 exists for shell-pipeline composition (which UDM doesn't do). § 1.8's collapse to exit 1 is defensible; a documentation note is sufficient. |
| "ISO 25010 Operability sub-characteristic suggests UDM should rename 'Operationally stable' pillar" | [iso25000.com](https://iso25000.com/index.php/en/iso-25000-standards/iso-25010) | DISMISSED — UDM's pillar vocabulary is internal; renaming would invalidate every cross-doc reference to "Operationally stable". External-industry concepts are useful frames, not mandated nomenclature. |
| "A 6th Pitfall #9 sub-class would make the bug class catalog more precise" | (No external source; first principles) | PARTIALLY ACCEPTED — precision is real, but the 5 existing sub-classes already cover "signature surface drift" conceptually. Adding sub-class #6 risks the catalog growing unboundedly. Strengthening wording within existing sub-class #1 (parameter-name drift) is leaner. |

---

## Confidence assessment

🟢 **Overall: high.** All 5 questions answered with grounded sources. Q1 and Q2 are unambiguous wording refinements. Q3 has one medium-authority source (would upgrade to high with direct docs.snowflake.com citation, but the SnowSQL exit-code values are well-established across multiple secondary sources). Q4 is internal-inventory verification with no external evidence needed. Q5 is well-grounded against the ISO 25010 standard.

No 🔴 blocking findings. All 5 are advisory framing refinements, consistent with Pattern E precedent set by R2-5 (Round 2 cycle 1) where the 5th-slot researcher returned 🟡 framing concerns rather than 🔴 blockers.

---

## Suggested follow-up (B-numbers for cycle 4 close-out triage)

All low-priority, non-blocking. Tagged **advisory-only**.

| Proposed B-number | Title | COD | JS | WSJF | Owner | Phase |
|---|---|---|---|---|---|---|
| **B81** | Strengthen HANDOFF Pitfall #9 first sub-class (parameter-name drift) to explicitly cover Python keyword-only `*,` marker per PEP 3102 — historical drift in fix cycles caused 11 instances per orchestrator prompt though current 04_tools.md citations preserve it correctly | 1 | 1 | 1.0 | Pipeline lead | Round 4 close-out polish |
| **B82** | Append one-line rationale to 04_tools.md § 1.8 documenting the choice to collapse `KeyboardInterrupt` (SIGINT) to exit 1 rather than the Unix-conventional 130 (128+signal) — rationale: UDM tools are not composed in shell pipelines | 1 | 1 | 1.0 | Pipeline lead | Round 4 close-out polish |
| **B83** | Append cross-reference note to 04_tools.md § 1.1 citing SnowSQL's 6-code exit scheme as adjacent precedent and explaining why UDM tools collapse to 0/1/2 at the orchestration grain | 1 | 1 | 1.0 | Pipeline lead | Round 4 close-out polish |

These can be combined into a single edit-batch at Round 4 close-out if convenient — all three are wording polish on already-locked text. **None block cycle 4 from converging to clean.**

---

## Cycle 4 5th-slot delivery — meta-notes

- **CCL Stage 1+2 reads compliant**: first content-substantive tool call hit `NORTH_STAR.md` (Stage 1) per D62 verification rule, then `HANDOFF.md`, `CURRENT_STATE.md`, `CHECKS_AND_BALANCES.md`, `RISKS.md`, `BACKLOG.md`, `_validation_log.md` in order before any Stage 3 (artifact) reads.
- **Time bound**: research completed within 60-90 minute window per orchestrator prompt.
- **Source count**: 6 sources cited (orchestrator ceiling), one per significant finding.
- **D55-D73 contradiction check**: no recommendation contradicts any locked decision. All 3 proposed B-numbers are framing refinements, not architectural changes.
- **Pattern E precedent followed**: advisory-only output, non-blocking, mirrors R2-5 (Round 2 cycle 1) deliverable structure. 5th slot does NOT contribute to D72 3-consecutive-clean count.
