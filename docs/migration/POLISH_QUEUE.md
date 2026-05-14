# POLISH_QUEUE.md — Cosmetic / Readability Tracker (P-numbers)

**Single source of truth for low-stakes wording / status-render / supersession-crumb / formatting items that don't block a phase and don't deserve a B-number.**

**Status**: 🟢 Locked 2026-05-12 per D113 (POLISH_QUEUE.md cosmetic-tracker discipline; analogous to D55 5-gate / D60 round close-out / D89-D91 Pattern F / D95-D99 self-improvement — process-discipline D-numbers locked 🟢 directly at first authoring per D111 exemption for process-infra)

Last reviewed: 2026-05-12 (created at residual-sweep close-out post-multi-agent-cascade; introduced to give P-numbers a home distinct from B-numbers and `_validation_log.md` audit findings)

---

## Pillar mapping (per D61)

Every new tracking discipline cites which NORTH_STAR pillar(s) it serves. POLISH_QUEUE.md serves:

- **Audit-grade**: preserves render-discipline trail — every cosmetic change (status-badge flip, supersession-crumb addition, stale-date refresh) gets a dated audit row with closure mechanism. No silent change discipline applies to cosmetic items the same way it applies to substantive items per Pitfall #9.j.
- **Traceability**: P-numbers create a stable identifier for every cosmetic carryover item, so cross-document references stay resolvable. Without POLISH_QUEUE, cosmetic items either rotted as untracked TODOs or polluted BACKLOG WSJF view; with it, each item has a stable ID + state + closure target.

(The other 3 pillars — Idempotent, Operationally stable, $120K — are not load-bearing on POLISH_QUEUE.md; cosmetic items by definition don't change behavior, idempotency, ops surface, or cost.)

---

## Risk delta (per D61)

**⬇️ DE-ESCALATED**: a sub-class of **R28** (round-level cascade self-attestation gap). Pre-POLISH_QUEUE, cosmetic render-drift had no dedicated home — items either (a) leaked into BACKLOG WSJF view as low-priority B-items, polluting the substantive-work signal; (b) became ad-hoc deferral lists at the bottom of `_validation_log.md` entries (e.g. the 2026-05-12 multi-agent cascade deferred R-7/R-8/R-9/R-10 inline at `_validation_log.md:2582`); or (c) silently rotted unrecorded. POLISH_QUEUE gives render-drift a typed, audit-trail-preserving substrate, closing one of the cascade-self-attestation gap's sub-channels.

**No new R-number introduced.** POLISH_QUEUE's own self-discipline gaps (e.g. the P-4 misquote caught in gap analysis) are an instance of Pitfall #9.i (fix-introduces-fresh-instance-of-same-bug-class), not a new risk class.

---

## What goes in POLISH_QUEUE.md (vs BACKLOG.md vs _validation_log.md)

The three trackers are intentionally narrow — knowing which one to use matters.

| Tracker | Purpose | Items look like | Numbering | How items leave |
|---|---|---|---|---|
| **BACKLOG.md** | Substantive open work the project owes (specs / migrations / tools / runbooks / triage workloads) | "Author RB-14 .env migration runbook"; "Implement Tool 14 measure_lateness.py"; "Populate UdmTablesList.PiiColumnList per source" | B-numbers (B01-B999) | Closed via decision lock, artifact authoring, code landing, or supersession |
| **POLISH_QUEUE.md** (this file) | Cosmetic / readability / status-render / supersession-crumb items that don't change behavior or unlock work | "Refresh D106 → D109 supersession crumb in 04b § 6"; "BACKLOG WSJF view leading badges drift after closure"; "Stale date in CURRENT_STATE pickup-sequence self-reference" | **P-numbers** (P-1, P-2, ...) | Closed when the cosmetic fix lands; doesn't trigger validation cascade |
| **_validation_log.md** | Audit trail of validation passes + fix-applications + Pattern F audits | "Cycle 4 R6 sleeper-bug stress caught 2 🔴"; "Fix-application-2 applied per Pattern F audit findings" | Section-by-section by date | Append-only history; archive past-Round-N entries per archive policy at top of file |

**Distinguishing test**: Does fixing this item change a decision body, a runbook procedure, an SP body, a tool spec, or a piece of pipeline code? If YES → B-number. If it's a wording crumb, stale date, missing supersession marker, status-badge mismatch, or render-discipline drift → P-number.

**Why a separate file**: B-numbers are scarce signal — every B-item is real backlog the project owes. Polishing items (especially the trail of D107 / D106 supersession crumbs across N docs) would flood the BACKLOG WSJF view if numbered as B-items. Validation log entries are append-only history, not a live worklist. POLISH_QUEUE is the live worklist for cosmetic carryover.

---

## Status legend

- **🟡 Open** — not yet polished; lives in the queue
- **🟠 Noticeable** — slightly higher priority than baseline 🟡 (e.g. front-and-center stale crumb in NORTH_STAR or HANDOFF §3 lock list)
- **⚫ CLOSED** — fix applied; row preserved for audit-trail with strikethrough body + closure date + closure mechanism
- **⬜ Deferred** — knowingly deferred past current phase (e.g. cascade of N>10 supersession crumbs across N>10 docs deferred to next round close-out)

---

## How items leave

A P-item closes when EITHER:
1. The cosmetic fix lands inline in the affected doc; row gets ⚫ CLOSED + closure date + brief mechanism note.
2. The item is converted to a B-number (rare — happens when "polish" turns out to require substantive work; document the promotion + retire the P-row).
3. The item is consciously deferred to a later round close-out (⬜ Deferred + target round).

**Items do NOT silently leave**. Every state change is annotated with date + reason — same render discipline as BACKLOG.md per Pitfall #9 sub-class 9.j.

---

## Active items

### P-1 (🟡 Open): D109 supersession crumb refresh in Round 4.5b § 6

- **Affected**: `phase1/04b_phase_0_closure_tools.md` § 6 (L239-240)
- **Issue**: Doc authored 2026-05-12 before D109 same-session supersession of D106; cites D106 only for Automic schedule baseline.
- **Inline mitigation applied 2026-05-12**: D109 supersession crumb appended at L239 + L240 noting D106 ⚫ Superseded by D109 + verifying the JOB_LATENESS_MEASURE Sat 06:00 + JOB_CAPACITY_BASELINE monthly 04:00 schedules remain safe vs the dual-Automic prod-then-test pattern.
- **Polish remaining**: At Phase 2 R1 close-out, when 04b enters its first real revision cycle, lift the canonical schedule citation from D106 → D109 directly in the prose (D92 forward-only permits supersession via new lock; the inline crumb is the bridge until then).
- **Closure target**: Phase 2 R1 close-out
- **Why P not B**: doesn't change Tool 14 / 15 / 16 specs or behavior; the schedules remain operationally safe; pure citation freshness.

### P-2 (🟡 Open): D107 3-revision arc supersession crumbs cascade audit

- **Affected**: any artifact authored between D107 fix-app-1 (2nd revision, 2026-05-12 morning) and the final 3rd revision (post-multi-agent cascade) may cite the 2nd-revision framing.
- **Inline mitigations applied 2026-05-12**:
  - HANDOFF.md L394 inline crumb extended to note 2nd → 3rd revision arc
  - NORTH_STAR.md L112 inline supersession crumb added
  - GLOSSARY.md D107 entry final framing applied
  - 02_PHASES.md L43 (0.5 deliverable narrative) updated to both-local framing
- **Polish remaining**: One-pass audit at Phase 2 R1 kickoff to grep for any remaining "VendorFile.*offsite" or "VendorFile.*vendor-managed" stragglers across all 13 cascade docs; convert each to the both-local final framing OR add inline supersession crumb if the artifact is locked per D92.
- **Closure target**: Phase 2 R1 kickoff
- **Why P not B**: cosmetic citation freshness; D110 + D107-final are canonical and authoritative.

### P-3 (🟡 Open): D106 → D109 supersession crumb cascade audit

- **Affected**: any artifact citing the AM 02:00 / PM 17:00 schedule using D106 as the canonical reference without D109 supersession crumb.
- **Inline mitigations applied 2026-05-12**:
  - 02_PHASES.md L48 (deliv 0.10) D109 supersession crumb added
  - `phase1/04b_phase_0_closure_tools.md` L239-240 D109 supersession crumb added
  - HANDOFF §3 L132 D106 already shows ⚫ Superseded by D109
- **Polish remaining**: same-pass with P-2 at Phase 2 R1 kickoff — grep for `per D106` / `D106 lock` references; ensure each either has D109 supersession crumb OR has been migrated to direct D109 citation per D92.
- **Closure target**: Phase 2 R1 kickoff (combined sweep with P-2)
- **Why P not B**: schedule values still operationally correct; D106's underlying values (02:00 AM + 17:00 PM) survive in D109 as the Prod legs. Citation freshness only.

### P-4 (🟡 Open): _validation_log.md first-archive execution

- **Affected**: `docs/migration/_validation_log.md` (currently >2700 lines as of 2026-05-12 D113-lock-cascade tail; threshold ALREADY exceeded — exact count varies as appends accumulate)
- **Issue**: Archive policy is documented inline at `_validation_log.md:12-23`. Threshold trigger ("file exceeds ~2000 lines OR entries older than 90 days") is currently MET (line count >2000 — exact figure will continue to grow with every appended validation entry until first archive cycle). Archive cadence is not yet executed; the policy text at L23 names the trigger event as "Phase 2 R1 close-out → archive entries pre-2026-04-12".
- **Polish item**: At Phase 2 R1 close-out (per the policy's own stated trigger), execute the first archive cycle per `_validation_log.md:14-21` procedure: (1) copy entries dated >30-days-ago to sibling file `_validation_log_archive_<YYYY-MM>.md` (e.g. `_validation_log_archive_2026-04.md`) preserving exact original formatting + header; (2) truncate the archived entries from the live file leaving last ~30 days; (3) add one-line back-reference at the top of the truncated live file: `**Archive**: pre-<YYYY-MM-DD> entries archived to _validation_log_archive_<YYYY-MM>.md (append-only; reads identical to original)`; (4) verify post-truncate line count < 1000 (otherwise repeat with earlier cutoff). Note: archive shape is SIBLING file with by-month naming + keep-last-30-days, NOT an `_archive/` subdirectory with by-round naming (corrects pre-fix P-4 misquote).
- **Closure target**: Phase 2 R1 close-out (per the policy's stated trigger event; not R1 kickoff — kickoff is too early for the close-out cascade to invoke the archive procedure)
- **Why P not B**: file-hygiene only; no behavior or decision-content change. Append-only invariant preserved by the archive procedure (archive file MUST NOT be edited after creation; live file resumes append-only with truncated prefix).
- **Self-correction note** (preserves audit-trail per Pitfall #9.i discipline): original P-4 body (committed at POLISH_QUEUE.md authoring 2026-05-12) misquoted the archive policy in 3 drift points — (a) threshold unit "~120 KB" should have been "~2000 lines"; (b) archive shape "_archive/ subdirectory with by-round naming" should have been "sibling file with by-month naming"; (c) closure target "Phase 2 R1 kickoff" should have been "Phase 2 R1 close-out". Fix-application 2026-05-12 same-session — full body rewritten verbatim against the actual policy text. This self-correction is Pitfall #9.i 8th-event evidence (fix-introduces-fresh-instance — authoring POLISH_QUEUE.md to solve render-discipline drift, then immediately introducing render-discipline drift inside it).

### P-6 (🟠 Noticeable — priority-bumped 2026-05-12 post-Pattern-E-R1C1): Pitfall #9.i event-count arithmetic drift reconciliation

- **Affected**: `HANDOFF.md` §8 9.i evidence-base section (L278-283) + `_validation_log.md` D113 lock entry + `_validation_log.md` Phase F cascade-completion entry
- **Issue**: Three different 9.i event counts cited across docs:
  - HANDOFF §8 section header says "10-event empirical campaign / 2 rounds" but enumerates **13 events / 3 rounds** (R5×3 + R6×5 + R7×5)
  - D113 validation log entry says "8th cumulative event" then enumerates **9 events** (R6×5 + R8×2 + R1.5×1 + D113-P-4×1 = 9, not 8)
  - Phase F validation log entry says "9th cumulative event" + math "5+2+1+1+1 = 9" — actually **10 events** (5+2+1+1+1 = 10)
- **Root cause**: two different counting bases at play — (a) within-round-validation-campaign during D72 cycles vs (b) cascade-completion-tail outside artifact validation. Both are valid measures; the drift is from inconsistent count maintenance across cycles.
- **Polish item**: At Phase 2 R1 close-out (when cumulative counts get touched again), reconcile to ONE canonical count basis OR introduce explicit two-stream notation (e.g., "9.i evidence base: 13 within-round-validation events across R5/R6/R7 + 2 cascade-completion-tail events at 2026-05-12 D113/Phase F = 15 cumulative events"). Whichever basis is chosen, propagate consistently to HANDOFF §8 + future validation log entries + `_reviewer_effectiveness.md`.
- **Closure target**: Phase 2 R1 close-out (combined sweep with P-6's natural arithmetic-recount discipline)
- **Why P not B**: doesn't affect any decision body, runbook, SP, or code; pure arithmetic-narrative freshness. Pitfall #9.k recurrence (arithmetic-propagation drift); 9.k is already an active sub-class so no new formalization needed.
- **Self-reference**: this very P-6 entry is the 11th 9.i event candidate AND 4th 9.k event candidate (the audit catching the drift is itself the closure). Same-cycle detection + deferred-fix pattern; consistent with D113's "items don't silently leave" rule.

### P-7 (🟡 Open): D113 cascade to missed aggregate docs per D93

- **Affected**: `02_PHASES.md` + `PHASE_1_DEEP_DIVE_PLAN.md` + `SELF_IMPROVEMENT_DISCIPLINE.md`
- **Issue**: Three aggregate process docs were NOT touched in the Phase F cascade (which covered CLAUDE.md + 00_OVERVIEW + MAINTENANCE + MULTI_AGENT_GUIDE + 5 skill files). Per D93 cross-doc cascade propagation mandate, these should reference D113 / POLISH_QUEUE.md for completeness.
- **Inline mitigation applied 2026-05-12**: none (deferred to closure target).
- **Polish remaining**: At Phase 2 R1 close-out OR earlier organic-touch (whichever comes first), add a brief D113 / POLISH_QUEUE reference to each:
  - `02_PHASES.md`: one-line entry in any tracker/reference section noting POLISH_QUEUE.md exists for cosmetic items
  - `PHASE_1_DEEP_DIVE_PLAN.md`: one-line mention in Phase 1 close-out narrative or tracker list
  - `SELF_IMPROVEMENT_DISCIPLINE.md`: one-line entry noting that cosmetic improvements from self-improvement skills can land as P-N items
- **Closure target**: Phase 2 R1 close-out (combined sweep with P-6 + P-2 + P-3 supersession-crumb sweeps)
- **Why P not B**: doesn't change phase scope, plan content, or self-improvement discipline; pure reference completeness per D93.

### P-8 (🟡 Open): `ACCT_smoke` invented table name persistence

- **Affected**: `phase2/01_pilot_prerequisites.md` § 4.7 (dev smoke test invokes `ACCT_smoke`) + § 7 rollback row (drop table reference)
- **Issue**: § 4.7 invokes a smoke test against `UDM_Stage.DNA.ACCT_smoke` — table doesn't exist; invented during initial R1 spec authoring. CLAUDE.md convention is `--table <single_table> --source DNA` against a real single table. Pattern E R1C1-4 idempotency advisory also flagged retry-safety (no DROP IF EXISTS).
- **Polish item**: At R1 § 4.7 implementation time, replace `ACCT_smoke` with either (a) a real small DNA test table (e.g. `DNA.osibank.ACCT_TEST` if engineering team confirms one exists), OR (b) explicit "TBD by R1 implementer; recommended approach: pick smallest real DNA table OR synthetic-data harness with DROP IF EXISTS guard". Also add DROP IF EXISTS to the tear-down step in § 7.
- **Closure target**: R1 § 4.7 implementation (Phase 2 R1 execution)
- **Why P not B**: doesn't change R1 procedure substance; specificity drift only.

### P-9 (🟡 Open): D-number table in `phase2/01_pilot_prerequisites.md` § 2 not numerically sorted

- **Affected**: `phase2/01_pilot_prerequisites.md` § 2 D-number table (L77-108)
- **Issue**: After Pattern E R1C1 D107 row addition adjacent to D44, the table reads `... D33 → D44 → D107 → D55 → D62 → ...` — breaks numerical order. Original sort was loosely chronological-by-Round-introduction; my insertion put D107 (R0 user-sign-off batch) next to D44 (R0 prep) which is defensible but reads visually jarring.
- **Polish item**: At R1 close-out polish, re-sort § 2 D-table strictly by D-number (D6, D11, D14, D16, D26, D27, D29, D33, D44, D55, D62, ..., D107, D108, D109, ..., D113). Single-pass table-rewrite.
- **Closure target**: R1 close-out polish sweep
- **Why P not B**: cosmetic / readability only; doesn't change semantic.

### P-10 (🟡 Open): `phase2/00_phase_overview.md` R1 row status didn't update post-cycle-1

- **Affected**: `phase2/00_phase_overview.md` round-by-round outline table (R1 row)
- **Issue**: After Pattern E cycle 1 + fix-application 1, the R1 row status still reads "🟡 Plan-draft (initial authoring 2026-05-12; awaits D55 5-gate validation + pipeline-lead sign-off)". Should now read "🟡 Plan-draft (post-cycle-1 fix-application 2026-05-12; cycle 2 verify-fresh-instance pending; pipeline-lead sign-off pending; B197 SELinux fix pending)".
- **Polish item**: One-line update.
- **Closure target**: This session OR cycle 2 close-out (whichever lands first).
- **Why P not B**: status freshness, not substantive change.

### P-11 (🟡 Open): `HANDOFF.md` §3 in-flight R1 entry didn't update post-cycle-1

- **Affected**: `HANDOFF.md` §3 in-flight Phase 2 R1 spec doc bullet
- **Issue**: Same as P-10 — status freshness not refreshed post-cycle-1 fix-application.
- **Polish item**: Add "(post-cycle-1 fix-application; cycle 2 pending)" parenthetical.
- **Closure target**: This session OR cycle 2 close-out.
- **Why P not B**: status freshness.

### P-14 (🟡 Open): Gate 6 diagnostic decision-tree step (b) Status filter completeness + operator-error 4th-mode

- **Affected**: `phase2/01_pilot_prerequisites.md` § 6 Gate 6 diagnostic decision-tree (added at cycle-5 fix)
- **Issue**: Pattern E R1C6 idempotency advisory found that Gate 6 step (b) `Status='FAILED'` filter doesn't catch the cycle-5 abandonment-without-apply HALT path (which writes NO audit row — operator-error precedes canonical procedure). Per `CK_PipelineEventLog_Status` enum (`IN_PROGRESS / SUCCESS / FAILED / SKIPPED`), a graceful HALT before canonical procedure leaves zero forensic trail. Also: the 4-step (a/b/c/d) decision-tree doesn't explicitly enumerate operator-error as a 4th distinct cause of `actual_count < 9`.
- **Polish item**: extend Gate 6 diagnostic step (b) to `Status IN ('FAILED', 'SKIPPED')` AND add explicit note that operator-error HALT at § 7 step 1a is detected via step (a) DB-connectivity + step (c) INFORMATION_SCHEMA query (resolution: "run forward-apply migration first").
- **Closure target**: R1 close-out polish OR Phase 2 R1 implementation time (whichever lands first)
- **Why P not B**: doesn't change Gate 6 acceptance logic substantively; clarifies diagnostic decision-tree completeness for operator-error mode.

### P-13 (🟡 Open): Partial-ladder abandonment recovery procedure missing

- **Affected**: `phase2/01_pilot_prerequisites.md` § 7 (rollback + partial-ladder recovery section)
- **Issue**: Pattern E R1C4 idempotency 🟡 advisory found that § 7 "Partial-ladder failure recovery" 4-step decision tree covers forward-application scenarios (B193/B194/B195 ALTER fails partway across dev → test → prod) but does NOT cover the symmetric scenario for abandonment (operator runs `--abandon` on dev + test succeeds, fails on prod). The same 4-step tree could be referenced but is not.
- **Polish item**: Add one paragraph under § 7 § 4.4 rollback row noting "Partial-ladder abandonment failures: follow the partial-ladder decision tree, treating abandonment as the forward action — back-out for dev + test means writing a SECOND abandonment-of-abandonment SchemaContract row (forward-only per D92, never reverse the supersession chain). DB-connectivity pre-check + targeted INFORMATION_SCHEMA query both apply."
- **Closure target**: R1 close-out polish OR cycle 5 fix-application (whichever lands first)
- **Why P not B**: doesn't change abandonment procedure itself; adds procedural cross-reference for an edge-case recovery scenario.

### P-12 (🟡 Open): `CLAUDE.md` L634 "(Rounds 1-5)" wording inaccuracy

- **Affected**: `CLAUDE.md` L634 edge case series catalog summary
- **Issue**: Original wording was "M/S/I/N/P/G/D/F/V (Rounds 1-7)" meaning these series were ACTIVE-ACROSS Rounds 1-7. My Pattern E R1C1 fix changed to "(Rounds 1-5)" which suggests INTRODUCED-DURING-Rounds-1-5 — subtle semantic shift. Both readings are defensible since the series existed pre-R5 and were active through R7, but the original was more accurate.
- **Polish item**: Revert "(Rounds 1-5)" → "(Rounds 1-7)" OR rephrase to "(introduced pre-Round-5; active through Phase 1)" for clarity.
- **Closure target**: Next CLAUDE.md edit cycle
- **Why P not B**: cosmetic wording drift.

### P-15 (🟡 Open): Retroactive backport of bound-param + SCOPE_IDENTITY patterns to earlier tool tests

- **Affected**: `tests/tier{0,1}/test_measure_lateness.py`, `test_capture_parity_baseline.py`, `test_verify_credentials_load.py`, `test_import_pii_inventory.py`, `test_lateness_columns.py`, `test_pii_inventory_audit_log.py`, `test_capacity_baseline_log.py` (7 test files from prior 8-unit cohort B183/B184/B188/B189/B190/B193/B194/B195)
- **Issue**: Two patterns demonstrated effective in § 3.8 build (2026-05-12) — (1) **bound-param inspection** (test inspects `executed_params` AND `executed_sql`, mirroring B218 retroactive fix); (2) **SCOPE_IDENTITY for audit_event_id** (audit-row writer returns IDENTITY value as int, populating `audit_event_id` key per spec). The 7 earlier test files do NOT use these patterns; they may have similar latent issues OR be silently passing only because their author code uses literal SQL (not parameterized).
- **Polish item**: Audit each of the 7 test files. Where author code uses parameterized SQL → add `executed_params` capture + bound-param inspection. Where audit_event_id is part of the JSON output spec → audit the author's `_write_audit_row` return semantics.
- **Closure target**: Phase 2 R1 close-out polish-sweep OR engineer-side iteration during R1c deployment when test-infrastructure consistency becomes load-bearing.
- **Why P not B**: doesn't change tool behavior; defends test files against latent flakiness if engineer modifies author code in the future. Cosmetic + defensive only.

### P-16 (🟡 Open): CODE_BUILD_STATUS Round 4 section header arithmetic propagation cleanup

- **Affected**: `docs/migration/CODE_BUILD_STATUS.md` L33 (was `"0/11 built"` header) — FIXED INLINE 2026-05-12 to `"2/11 built"` after gap-check 9.k finding.
- **Issue**: Section header didn't propagate when at-a-glance count was updated post-§ 3.10 + § 3.8 builds (Pitfall #9.k arithmetic-propagation drift instance). Fixed inline.
- **Polish item (forward-looking)**: When CODE_BUILD_STATUS Round 4 OR Round 3 count next changes, verify BOTH at-a-glance summary table (L22 region) AND per-section header (L33 + L48 region for Round 3) update in lockstep. Add a producer self-check note in the file's "How units move through state" section reminding of dual-location update.
- **Closure target**: Next CODE_BUILD_STATUS edit cycle (organic; not blocking).
- **Why P not B**: cosmetic propagation discipline; no procedural change required.

### P-17 (🟡 Open): Round 5 § 5.6 strict `<=` needs ULP-tolerance note for percentile monotonicity

- **Affected**: `docs/migration/phase1/05_tests.md` § 5.6 ("Lateness percentile monotonicity")
- **Issue**: Canonical § 5.6 wording asserts strict `<=` (`p50 <= p90 <= p95 <= p99 <= max`). Tier 2 property test cohort 2026-05-14 Agent D found that `statistics.quantiles()` with `method="inclusive"` on floats can produce a p_high value that is bit-equal to p_low under specific Hypothesis-generated sample distributions (e.g. all samples within 1 ULP of each other). Strict `<=` still holds in practice because the two floats compare equal, but the spec wording reads as if strict `<` were expected. Agent D worked around it via deduplicated-sample strategies in `test_lateness_monotonicity.py`.
- **Polish item**: Add a 1-line note to § 5.6: "Strict `<=` semantics — for sample distributions where consecutive percentiles round to bit-equal floats (within 1 ULP), `p_low == p_high` is permitted under the inclusive-quantile algorithm; tests use `<=` not `<`." No behavior change.
- **Closure target**: Next `phase1/05_tests.md` edit cycle (likely Round 5 close-out OR Phase 2 R1 spec re-read pass).
- **Why P not B**: cosmetic spec clarification; behavior under `statistics.quantiles()` is correct; spec wording is the only drift.

### P-18 (🟡 Open): § 5.3 NFC/NFD plaintext normalization upstream of SP-1 — future enhancement candidate

- **Affected**: `docs/migration/phase1/05_tests.md` § 5.3 (tokenization determinism) + Round 1 § SP-1 contract docs
- **Issue**: Tier 2 property test cohort 2026-05-14 Agent C's `test_unicode_nfc_nfd_distinct_tokens` documents SP-1's current contract: NFC-form `"é"` and NFD-form `"é"` produce DIFFERENT tokens because SP-1 hashes the byte sequence. This matches production behavior. Some sources may emit either form depending on the OS / driver / locale, which means the SAME logical user identifier could produce two tokens across a database migration. A future enhancement could normalize plaintext to NFC upstream of SP-1 (in `pii_tokenizer.tokenize_pii_columns`) to make tokenization Unicode-form-agnostic.
- **Polish item**: Add a future-enhancement bullet to § 5.3 (or open a separate B-N once the operational impact is observed). For now, document the current contract more explicitly: "SP-1 is byte-form sensitive by design; callers wanting NFC-equivalent tokenization should normalize plaintext upstream."
- **Closure target**: Spec-clarification at next round close-out; promotion to B-N if/when an operational incident surfaces NFC/NFD divergence in production.
- **Why P not B**: documents existing behavior; behavior is correct per current SP-1 contract; no procedural / code change required unless an incident occurs.

### P-19 (🟡 Open): § 5.3 empty-string vs NULL plaintext semantics

- **Affected**: `docs/migration/phase1/05_tests.md` § 5.3 + Round 1 § PiiVault DDL (`Plaintext NVARCHAR(MAX) NOT NULL`)
- **Issue**: Tier 2 property test cohort 2026-05-14 — § 5.3 example tokenization test uses `st.text(min_size=1, max_size=200)`, skipping empty strings. But Round 1 § PiiVault DDL admits empty string (`NOT NULL` only excludes NULL; `''` is valid). Agent C's `test_empty_string_handling` added a regression guard documenting that the mock vault DOES mint a token for `''`; the M4 module's NULL pass-through contract leaves None alone (not empty string). Spec § 5.3 example wording would be clearer if it explicitly stated the empty-string-is-non-NULL contract.
- **Polish item**: Add a 1-line clarification to § 5.3: "Empty string is a valid plaintext per `PiiVault.Plaintext NVARCHAR(MAX) NOT NULL`; `min_size=1` in the example strategy is a property-test heuristic, not a contract restriction. NULL plaintext is pass-through in `tokenize_pii_columns` per the M4 module contract."
- **Closure target**: Next `phase1/05_tests.md` edit cycle.
- **Why P not B**: cosmetic spec clarification; the property test (Agent C) already pins the correct behavior via regression guard.

### ~~P-5~~ (⚫ CLOSED 2026-05-12): GLOSSARY P-number entry

- ~~**Affected**: `docs/migration/GLOSSARY.md`~~
- ~~**Issue**: New P-number scheme introduced at POLISH_QUEUE.md authoring 2026-05-12 — GLOSSARY needs a P-N entry under its short-form-identifiers section so future agents recognize "P-1" / "P-2" / etc.~~
- ~~**Polish item**: Add entry near the existing B-N / D-N / R-N entries.~~
- ~~**Closure target**: this session (cascade step of POLISH_QUEUE introduction)~~
- ~~**Why P not B**: dictionary entry; doesn't change any procedure or decision.~~
- **Closure mechanism**: Two GLOSSARY entries landed inline during the POLISH_QUEUE.md introduction cascade — (1) main symbol-prefix table row `P-<N>` slotted next to `B<N>` per natural-cousin placement; (2) "Authoritative source" table at L598 row `P-numbers (polish queue) | POLISH_QUEUE.md`. P-5 row preserved with strikethrough for audit-trail per Pitfall #9.j status-render discipline + BACKLOG.md closure-render precedent.

---

## Closed items (audit-trail)

P-5 (⚫ CLOSED 2026-05-12; ↑ see "Active items" section above for full body preserved with strikethrough; closed inline during POLISH_QUEUE introduction cascade — the GLOSSARY P-N entry IS the closure mechanism for the very item that mandated the entry; rare same-session create-and-close pattern preserved in audit-trail per the queue's own discipline)

---

## Deferred items

*(none yet)*

---

## Item authoring template

When adding a new P-item:

```
### P-<N> (🟡 Open | 🟠 Noticeable | ⬜ Deferred): <one-line title>

- **Affected**: <file path + line range or section>
- **Issue**: <2-3 sentences describing what's cosmetically off>
- **Inline mitigation applied (if any)**: <date + what was done; e.g. "supersession crumb added">
- **Polish remaining**: <what still needs to happen to fully close>
- **Closure target**: <session / round / phase-boundary>
- **Why P not B**: <one sentence — confirms it doesn't change behavior, decisions, runbooks, SP bodies, or code>
```

## Closure template

When closing a P-item, replace the `🟡 Open` badge with `⚫ CLOSED YYYY-MM-DD` + add a "Closure mechanism" line. Preserve the original body via strikethrough (`~~...~~`) per BACKLOG.md precedent + Pitfall #9 sub-class 9.j status-render discipline.

---

## Read order context

POLISH_QUEUE.md is **NOT** part of the Canonical Context Load (D62) Stage 1 mandatory reads — it's a worklist, not a context doc. Skim it at round close-outs + phase boundaries to convert any 🟡 items that the closing round's work touches into ⚫ CLOSED rows.

Producers + reviewers + cascade-auditors do NOT need to read POLISH_QUEUE before authoring or reviewing — its items are by construction NOT load-bearing on artifact correctness. (If a P-item turns out to be load-bearing, promote to B-number + retire the P-row per "How items leave" rule 2.)

---

## Relation to Pattern F (D89-D91) + sub-class 9.j (D96 + B144)

Pattern F + sub-class 9.j FORMALIZED status-render discipline at HANDOFF §8: any item with a leading status badge AND inline closure annotation must reconcile to inline-annotation-canonical. POLISH_QUEUE.md operationalizes that discipline at the doc-set level — items that *would* have been low-priority Pattern F findings (cosmetic readability drift, not artifact correctness drift) land here instead of as 🟡 carryover B-items or as recurring Pattern F advisory rows.

**Pattern F still reviews POLISH_QUEUE.md during round close-out** — the cascade-auditor reviews ⚫ CLOSED entries from the closing round to confirm no closure mechanism was missed, and reviews 🟡 Open entries to confirm they're genuinely cosmetic (not promoted-B-candidates in disguise).

---

Owner: pipeline lead (delegated to round close-out cascade authoring).
