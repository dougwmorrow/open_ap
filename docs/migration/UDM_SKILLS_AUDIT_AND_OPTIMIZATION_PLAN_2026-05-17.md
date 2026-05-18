# UDM Skills — Comprehensive Audit + Optimization Plan (4-Cohort Multi-Agent Review)

**Date**: 2026-05-17
**Author**: parent agent (orchestrator role) synthesizing 4-cohort multi-agent review per user direction "We should review all skills for any gaps and optimize them. Proceed with your recommended next steps. Use a multi-agent team."
**Status**: 🟡 Draft v1 — awaiting independent reviewer + pipeline-lead sign-off
**Scope**: PS-9 SELF (skills review + optimization) + PS-1 ARCH (cross-skill composition gaps); 24 of 25 udm-* skills reviewed (udm-progress-logger excluded — dedicated plan at commit `4d7dee8`)
**Multi-agent cohort**: Agents 54 (Cohort A orchestration) + 55 (Cohort B validation) + 56 (Cohort C artifact authoring) + 57 (Cohort D self-improvement) = +4 cumulative inheritance applications

---

## §0. Planning session provenance

| Skill / Agent | Invocation | Scope | Rationale |
|---|---|---|---|
| `udm-planning-session-startup` | session start (inline acknowledgment) | PS-9 SELF + PS-1 ARCH | Pipeline-lead trigger phrase met |
| `udm-design-reviewer` × 4 (cohort) | Agents 54-57 (background parallel) | PS-1 + PS-9 mandatory | 4-cohort architectural review of all 24 skills |
| `udm-edge-case-validator` | inline (this synthesis) | PS-1 implicit | Edge case enumeration per skill (PL-series template) |
| `udm-checks-and-balances` | scheduled at attestation | PS-1 mandatory | 5-gate validation pre-sign-off |
| `udm-gap-check` | scheduled at attestation | always-mandatory §2.3 | Independent gap-check on synthesis |
| `udm-progress-logger` v1.2.0 | inline throughout | always-mandatory per hard rule 9 | Tracker updates per Step 4.5 arithmetic-propagation discipline |
| `udm-post-edit-verification` | this commit | hard rule 14 | TEST + GAP + REVIEW cascade |

**Sub-agent inheritance contract** (per hard rule 13): all 4 cohort agents received explicit inheritance directive citing udm-design-reviewer + udm-edge-case-validator + udm-checks-and-balances. Verified via spawn prompts.

---

## §1. Binding constraints + cross-cohort convergent themes

### §1.1 Binding constraints

1. **Preserve in-flight skill discipline**: no breaking changes; all enhancements ADDITIVE per D98 semver
2. **Empirical-evidence-driven**: every B-N traces to specific cohort agent finding
3. **Producer + harness composition**: producer-side discipline (SKILL.md) composes with harness (Mechanism C-1) without duplication
4. **Backward-compat**: existing skill invocations continue to work
5. **No build in this plan** — design only; implementation tracked via B-N opens

### §1.2 Cross-cohort convergent themes (4 of 4 cohorts agree)

**Theme 1 — Series-list drift is SYSTEMIC (HIGHEST PRIORITY)**: 4 skills embed the canonical edge case series list as a frozen literal, all stale at 9 series (M/S/I/N/P/G/D/F/V) vs current 14 (M/S/I/N/P/G/D/F/V/DP/T/SI/SE/PL):
- `udm-round-closeout` Section 3 (Cohort A finding)
- `udm-checks-and-balances` Gate 3 (Cohort B finding)
- `udm-edge-case-validator` series table L66-75 + Stage 3 CCL text L25 (Cohort B finding)
- `udm-gap-check` Category 3 9.a-9.m (missing 9.n + 9.o; Cohort B finding)

**Impact**: every Gate 3 walk + every Category 3 sweep silently incomplete since Round 6 (when DP series added). Most-recent-formalized sub-classes (9.n + 9.o) AND most-recent-formalized series (PL) NOT covered by ANY skill-embedded list.

**Theme 2 — D98 version field absent across many skills**: Cohort A (4 of 6) + Cohort B (4 of 7) + Cohort D (acknowledged systemic) = 8+ of 24 skills missing `version:` frontmatter. Pitfall #9.m self-application gap (D98 discipline not applied to skill SKILL.md files).

**Theme 3 — Tier 0 stubs described but not implemented (D67 violation)**: 6 Cohort D skills + 4 Cohort B skills = 10+ skills with described-but-unimplemented Tier 0 stubs.

**Theme 4 — Pitfall #9.k arithmetic-propagation in skill checklists**: udm-gap-check Category 3 stale at 9.a-9.m; udm-subclass-accumulator keyword table stale for 9.k-9.o; multiple skills cite stale series lists. The skill suite designed to detect Pitfall #9.k drift is itself stale on Pitfall #9.k.

**Theme 5 — NORTH_STAR.md missing from cross-doc cascades**: Cohort C surfaced B-297 recurrence pattern; NORTH_STAR.md not in udm-decision-recorder or udm-runbook-author cross-doc checklists despite being canonical pillar-mapping register for D62+ decisions.

**Theme 6 — udm-data-engineer-review checklist drift behind CLAUDE.md Do-NOT rules**: 4 missing items (SCD2-P1-e in-flight orphan predicate / CDC_VERIFY_STRICT_ON_FAILURE / CDC_NOW_MS / D116 metadata schema). Drift between canonical anti-pattern source (CLAUDE.md) + skill's review checklist.

**Theme 7 — Direct policy CONFLICT**: udm-post-edit-verification anti-trigger at L25-32 says "this very SKILL.md authoring (recursive trigger; bootstrap exemption)" — udm-exemption-verifier CRITICAL CARVE-OUT at L62-68 says SKILL.md authoring commits are NOT exempt. Agents read both and produce incompatible verdicts.

---

## §2. Per-cohort findings summary

### §2.1 Cohort A — Orchestration (6 skills; Agent 54)

| Skill | Top finding | WSJF |
|---|---|---|
| udm-round-closeout | Section 3 series list stale (9 vs 14 canonical) | 5.0 🔴 |
| udm-post-build-verify | Windows collection-skew (B-328) not in Step 2 | 5.0 🔴 |
| udm-planning-session-startup | Quoted-context anti-trigger missing (PSS-1) | 3.0 |
| udm-next-step-cascade | Git push failure path (NSC-4) | 3.0 |
| udm-brainstorm | Locked-D-number guard missing | 4.0 |
| udm-planning | 6-step cycle not bound to skill names (UP-7) | 2.0 |

**12 candidates surfaced; no B-N needed for cohort summary line — actual B-N assignment in §3 table below** (Cohort A B-A-1 through B-A-12).

### §2.2 Cohort B — Validation (7 skills; Agent 55)

| Skill | Top finding | WSJF |
|---|---|---|
| udm-checks-and-balances | Gate 3 series list 9 → 14 | 5.0 🔴 |
| udm-edge-case-validator | Series table + Stage 3 CCL text 9 → 14 | 5.0 🔴 |
| udm-gap-check | Category 3 missing 9.n + 9.o | 5.0 🔴 |
| udm-post-edit-verification | Anti-trigger CONTRADICTS udm-exemption-verifier CARVE-OUT | 5.0 🔴 |
| udm-step-10-verifier | Step 3 conflates GLOSSARY + L207 (split needed) | 3.0 |
| udm-exemption-verifier | CRITICAL CARVE-OUT presence not in Tier 0 stub | 4.0 |
| udm-context-loader | PS-9 SELF row under-specifies (CLAUDE.md + 04_EDGE_CASES) | 4.0 |

**10 candidates surfaced; tracked in §3 enumeration below** (Cohort B BNcand-408 through BNcand-417 plan-local).

### §2.3 Cohort C — Artifact Authoring (5 skills; Agent 56)

| Skill | Top finding | WSJF |
|---|---|---|
| udm-decision-recorder | NORTH_STAR.md missing from cross-doc checklist (B-297 recurrence) | 1.5 |
| udm-runbook-author | No cross-doc checklist at all + no RB-N numbering + no classifier coupling | 1.0-1.5 |
| udm-execution-classifier | B-298 hook-automated category missing (already tracked; underweighted) | (escalate WSJF) |
| udm-data-engineer-review | Checklist drift behind 4 CLAUDE.md Do-NOT rules | 3.0 🔴 |
| udm-cycle-cadence-optimizer | Tier δ output template missing | 0.5 |

**10 candidates surfaced; tracked in §3 enumeration below** (Cohort C BNcand-408 through BNcand-417 plan-local; conflicts with Cohort B numbering).

### §2.4 Cohort D — Self-Improvement (6 skills; Agent 57)

| Skill | Top finding | WSJF |
|---|---|---|
| udm-retrospective-collector | Specialty enum missing "cascade-audit" | (multiple) |
| udm-specialty-tuner | Per-round per-specialty schema gap | (multiple) |
| udm-subclass-accumulator | Keyword table stale for 9.k-9.o + CLAUDE.md not in CCL | 4.0 🔴 |
| udm-producer-checklist-evolver | CLAUDE.md §14 not in lookup; 8.C/8.D coordination gap | (multiple) |
| udm-cascade-audit-evolver | CCL Stage 4 greps non-existent specialty; B176 not in candidate list | (multiple) |
| udm-agent-prompt-versioner | target_agent scope ambiguity for tools/verify_cascade.py deltas | (single) |

**7 candidates surfaced; tracked in §3 enumeration below** (Cohort D BNcand-408 through BNcand-414 plan-local; conflicts with Cohorts B + C).

---

## §3. Cumulative B-N enumeration (deconflicted to canonical numbering)

**Mapping**: cohort plan-local candidate placeholders; tracked in §3 enumeration below → canonical numeric range (next-available after current latest in BACKLOG; no B-N needed for this mapping note — actual assignment at BACKLOG.md commit cycle). Total ~39 B-N candidates after deconfliction.

### §3.1 CRITICAL Phase 1 (highest-WSJF; immediate bug fixes)

| Canonical B-N | Title | WSJF | Cohort source |
|---|---|---|---|
| **BNcand-408** | **CRITICAL**: Fix series-list drift in ALL 4 affected skills atomically (udm-round-closeout Section 3 + udm-checks-and-balances Gate 3 + udm-edge-case-validator series table + Stage 3 CCL + udm-gap-check Category 3 9.a-9.m → 9.a-9.o) — single atomic commit prevents re-drift | 5.0 | A + B convergent |
| **BNcand-409** | **CRITICAL**: Resolve udm-post-edit-verification anti-trigger CONTRADICTION with udm-exemption-verifier CRITICAL CARVE-OUT on SKILL.md authoring commits (Cohort B CB-4-C) | 5.0 | B |
| **BNcand-410** | **CRITICAL**: Windows collection-skew (B-328) guidance in udm-post-build-verify Step 2 — oracledb/polars ImportError exemption path | 5.0 | A |
| **BNcand-411** | **CRITICAL**: udm-subclass-accumulator keyword table extension for 9.k-9.o + add CLAUDE.md to CCL Stage 3 (prevents false-new-sub-class proposals at next close-out) | 4.0 | D |
| **BNcand-412** | udm-context-loader PS-9 SELF row extension to include 04_EDGE_CASES.md + CLAUDE.md (skill-review session under-spec) | 4.0 | B |
| **BNcand-413** | Locked-D-number guard for udm-brainstorm (BS-2; recommendation MUST NOT contradict locked D-N without supersession process) | 4.0 | A |
| **BNcand-414** | udm-exemption-verifier CRITICAL CARVE-OUT presence assertion in Tier 0 stub (prevents accidental removal) | 4.0 | B |
| **BNcand-415** | udm-round-closeout HANDOFF §14 update in Section 6 HANDOFF checklist (RC-7; matches udm-next-step-cascade §14 discipline) | 4.0 | A |

### §3.2 HIGH Phase 2 (D98 cascade + critical-coupling fixes)

| Canonical B-N | Title | WSJF | Cohort source |
|---|---|---|---|
| **BNcand-416** | D98 `version:` frontmatter cascade — add to 8+ skills missing it (udm-next-step-cascade + udm-round-closeout + udm-brainstorm + udm-planning + udm-post-build-verify + udm-checks-and-balances + udm-edge-case-validator + udm-gap-check + udm-exemption-verifier) + add changelog section | 3.0-4.0 | A + B convergent |
| **BNcand-417** | Resolve B23 (NEXT_AVAILABLE B-number computation) in udm-checks-and-balances backlog-surfacing section — supply grep mechanic; B23 open since Phase 1 R3 | 3.0 | B |
| **BNcand-418** | udm-step-10-verifier Step 3 split into Step 3a (GLOSSARY) + Step 3b (L207 CLI_* registry); current conflation causes producer to stop at GLOSSARY-clean | 3.0 | B |
| **BNcand-419** | udm-data-engineer-review checklist extension — SCD2-P1-e in-flight orphan predicate (BOTH UdmEndDateTime IS NULL AND UdmSourceEndDate IS NULL) | 3.0 | C |
| **BNcand-420** | udm-data-engineer-review checklist extension — CDC source verification section (CDC_VERIFY_STRICT_ON_FAILURE + CDC_VERIFY_MAX_CANDIDATES + CDC_NOW_MS invariant + source-count-check separation) | 3.0 | C |
| **BNcand-421** | udm-data-engineer-review checklist extension — D116 metadata schema check (Parquet `udm_pipeline_version` key + key_value_metadata mandate) | 3.0 | C |
| **BNcand-422** | udm-gap-check Category 3 + CCL self-check fallback Hard rule 7 tension resolution (clarify fallback's Stage 1 minimum SATISFIES Hard rule 7) | 3.0 | B |
| **BNcand-423** | udm-next-step-cascade git push failure error-handling path (NSC-4; surface error + manual-push URL; still emit cascade-complete report) | 3.0 | A |
| **BNcand-424** | udm-planning-session-startup quoted-context anti-trigger (PSS-1; trigger phrases in backticks/blockquotes/code fences excluded) | 3.0 | A |
| **BNcand-425** | udm-round-closeout Section 10 FREEZE-state guard at top (skip 10.1-10.7 if loop FROZEN with explicit citation) | 3.0 | A |
| **BNcand-426** | NORTH_STAR.md write-side cascade rule — add to udm-decision-recorder cross-doc checklist as item 11 (closes B-297 recurrence pattern) | 3.0 | C |
| **BNcand-427** | NORTH_STAR.md write-side rule in CLAUDE.md Do-NOT section (forward-prevention; "Do NOT merge D62+ decision without NORTH_STAR.md pillar-mapping row") | 3.0 | C |
| **BNcand-428** | udm-execution-classifier hook-automated category (B-298 already tracked; ESCALATE WSJF 1.5 → 2.5; D114 deployed) | (escalate) | C |
| **BNcand-429** | udm-step-10-verifier Step 1 skip-rule exception for fixture-factory functions (CB-5-A) | 3.0 | B |
| **BNcand-430** | Extend udm-exemption-verifier trigger list to exclude legitimate verifier-evidence-citing commits (CB-6-C; "Verdict: VALID" in CASCADE-EVIDENCE section) | 2.0 | B |

### §3.3 MEDIUM Phase 3 (Tier 0 + composition + integration tests)

| Canonical B-N | Title | WSJF | Cohort source |
|---|---|---|---|
| **BNcand-431** | Tier 0 stub authoring batch — 10+ skills missing implementations (4 Cohort B + 6 Cohort D + others). Lightweight structure-verification tests; ~30 LOC each | 1.0-2.0 | B + D convergent |
| **BNcand-432** | Bind skills to udm-planning's 6-step cycle (UP-7; name udm-design-reviewer at Step 3 QA + udm-edge-case-validator at Step 4 + udm-checks-and-balances at Step 6) | 2.0 | A |
| **BNcand-433** | udm-runbook-author cross-doc update checklist + RB-N monotonic numbering + udm-execution-classifier coupling | 1.0-1.5 | C |
| **BNcand-434** | udm-post-edit-verification SQL SP / migration TEST table row (currently undefined for SQL artifact type) | 2.0 | B |
| **BNcand-435** | udm-brainstorm composition table addition (currently absent; include udm-researcher + udm-decision-recorder + udm-gap-check) | 2.0 | A |
| **BNcand-436** | udm-decision-recorder + classifier coupling (sentence: "If decision introduces executable artifact, invoke udm-execution-classifier") | 1.0 | C |
| **BNcand-437** | udm-retrospective-collector specialty enum extension ("cascade-audit" or Phase F clarification) + Phase 2+ round-naming convention (P2-R1 etc.) | (multiple) | D |
| **BNcand-438** | udm-specialty-tuner per-round per-specialty schema in _reviewer_effectiveness.md (supports R31 FREEZE detection #1) | 1.0 | D |
| **BNcand-439** | udm-producer-checklist-evolver CLAUDE.md §14 in lookup procedure (closes 9.k-9.o miss; coordinated with BNcand-411) | (paired) | D |
| **BNcand-440** | udm-cascade-audit-evolver Round 8 close-out candidate list refresh (add B176 Pattern F Trigger J); CCL Stage 4 specialty correlation fix | (multiple) | D |
| **BNcand-441** | udm-agent-prompt-versioner target_agent scope clarification (or define application path for tools/verify_cascade.py deltas) | 3.0 | D |
| **BNcand-442** | udm-cycle-cadence-optimizer Tier δ output template sub-section + carryover trend floor (≥5 items per round for 3 rounds = alarm) | 0.5-1.0 | C |

### §3.4 LOW Phase 4 (polish + cosmetics)

| Canonical B-N | Title | WSJF | Cohort source |
|---|---|---|---|
| **BNcand-443** | Sub-agent spawn ordering guard for udm-planning-session-startup (PSS-3; Step 3 user approval MUST precede Agent tool calls) | 1.5 | A |
| **BNcand-444** | udm-context-loader CCL token baseline refresh from current repo state (CB-7-F; baseline stale from 2026-05-15) | 1.5 | B |
| **BNcand-445** | Cross-skill composition diagram in master plan OR per-skill (consistent format across all 24 skills) | 1.0 | A + C convergent |
| **BNcand-446** | udm-cycle-cadence-optimizer + others — Phase 2+ round-naming convention propagation across skills with `round&lt;N&gt;` file naming | 1.0 | D |
| **BNcand-447** | udm-cascade-audit-evolver output file on NO-ACTION rounds (with verdict explicitly stated; downstream Stage 4 reads don't silently fail) | 1.0 | D |

**Net B-N count**: 40 NEW (BNcand-408 through BNcand-447). 4 cohorts proposed total 39; deconflicted to 40 with thematic consolidation (BNcand-408 fixes 4 skills atomically; BNcand-419-BNcand-421 are 3 separate udm-data-engineer-review checklist items).

---

## §4. NEW R-N candidates

| R-N | Description | Score | Source |
|---|---|---|---|
| **RNcand-44** | Self-improvement skill suite zero automated tests (D67 violation) — validation logic regressions undetected between close-out invocations | Low × Medium = 2 ⚪ | D |
| **RNcand-45** | Sub-class 9.k-9.o staleness in self-improvement skills (8.A/8.C/8.D) creates false-candidate proposals at next close-out — user-approval bandwidth wasted | Low × Low = 2 ⚪ | D |
| **RNcand-46** | Frozen series lists in 3+ validation skills (Cohort B) create systemic silent-coverage-gap on every Gate 3 walk + every Category 3 sweep | Low × High = 3 🟡 | B |
| **RNcand-47** | udm-post-edit-verification anti-trigger + udm-exemption-verifier CRITICAL CARVE-OUT direct contradiction on SKILL.md authoring commits → incompatible policy execution | Low × Medium = 2 ⚪ | B |
| **RNcand-48** | NORTH_STAR.md write-side cascade gap (3rd recurrence at B-297; Pitfall #9.m candidate) | Low × Medium = 2 ⚪ | C |
| **RNcand-49** | udm-data-engineer-review checklist drift behind CLAUDE.md Do-NOT rules — 4 missing items; each new Do-NOT rule that's not added to checklist widens review gap | Low × High = 3 🟡 | C |

---

## §5. Phased implementation roadmap

### Phase 1 — CRITICAL bug fixes (cycle 1; ~150 LOC)

**Goal**: clear all 🔴 WSJF 5.0 active bugs before next close-out / planning session.

| B-N | LOC est | Risk |
|---|---|---|
| BNcand-408 (series-list 4-skill atomic) | ~30 | LOW (mechanical text replacement) |
| BNcand-409 (anti-trigger vs CARVE-OUT) | ~20 | MEDIUM (policy reconciliation; may need user input) |
| BNcand-410 (Windows collection-skew) | ~30 | LOW (additive Step 2 guidance) |
| BNcand-411 (udm-subclass-accumulator 9.k-9.o + CLAUDE.md CCL) | ~30 | LOW (additive keyword table extension) |
| BNcand-412 (udm-context-loader PS-9 SELF row) | ~10 | LOW (single-row extension) |
| BNcand-413 (udm-brainstorm locked-D guard) | ~15 | LOW (additive enforcement clause) |
| BNcand-414 (udm-exemption-verifier Tier 0 CARVE-OUT assertion) | ~15 | LOW (test assertion) |
| BNcand-415 (udm-round-closeout HANDOFF §14) | ~5 | LOW (single bullet add) |
| **Total Phase 1** | **~155 LOC** | **~1 cycle** |

### Phase 2 — D98 cascade + critical coupling (cycle 2; ~200 LOC)

D98 version field + changelog cascade to 8+ skills + classifier coupling + cross-doc fixes. Higher LOC due to per-skill changelog authoring.

### Phase 3 — Tier 0 + integration tests (cycles 3-4; ~500 LOC)

10+ Tier 0 stubs authored + integration tests for new disciplines. Higher cycle count due to per-skill test authoring + verification.

### Phase 4 — Composition + polish (deferred; opportunistic)

Composition diagrams, round-naming convention propagation, baseline refresh, miscellaneous polish.

### Phase 5 — Mechanism C-1 extension for skill-list-drift prevention (DEFERRED)

Author Mechanism C-1 9th check `check_skill_series_list_sync` that grep-asserts skill-embedded series lists match canonical `04_EDGE_CASES.md` preamble count. Closes systematic structural vulnerability surfaced by Theme 1.

---

## §6. Risk + invariant preservation

### §6.1 Skill discipline invariants preserved

| Invariant | Source | This plan affects? |
|---|---|---|
| Per-completion timing | udm-progress-logger Hard rule 1 | ✅ Preserved |
| Append-only tracker discipline | udm-progress-logger Hard rule 2 + Pitfall #9.j | ✅ Preserved |
| Producer ≠ reviewer per D55+D56 | udm-checks-and-balances Gate 2 | ✅ Preserved |
| D72 convergence rule | udm-checks-and-balances Second-pass | ✅ Preserved |
| Mechanism C-1 hook enforcement | tools/pre_commit_checks.py | ✅ Preserved; Phase 5 extends |

### §6.2 New risks (per §4 above)

5 NEW R-Ns opened (RNcand-44-RNcand-48) tracking the structural gaps surfaced by this audit.

---

## §7. Sign-off readiness

### §7.1 Pre-sign-off actions (this commit)

- [x] Plan authored with §0 provenance + 4-cohort attribution
- [x] §1 binding constraints + 7 cross-cohort convergent themes documented
- [x] §2 per-cohort findings summary
- [x] §3 ~40 B-Ns deconflicted to canonical numbering (BNcand-408-BNcand-447)
- [x] §4 6 NEW R-Ns enumerated
- [x] §5 phased roadmap with cycle estimates
- [ ] Spawn independent D55+D56 reviewer on synthesis plan
- [ ] Open ~40 B-Ns in BACKLOG.md + 6 R-Ns in RISKS.md
- [ ] Pipeline-lead Phase 1 cycle authorization

### §7.2 Pre-Phase-1-execution

- [ ] BNcand-408 through BNcand-415 (CRITICAL) opened in BACKLOG with concrete numbers
- [ ] Phase 1 cycle authorization

### §7.3 D72 cycle implications

This plan IS itself substantive planning work; per udm-checks-and-balances + D72 discipline, the 4-cohort cohort review constitutes cycle 1 (4-agent multi-cohort batch counts as 1 cycle). An independent reviewer pass on THIS synthesis would be cycle 2. Convergence on a skill-audit plan does NOT block Phase 1 execution per se — Phase 1 fixes can land per individual B-N closures with their own validation cycles.

---

## §8. Cross-references

- `.claude/skills/*/SKILL.md` × 24 (all reviewed)
- `docs/migration/UDM_PROGRESS_LOGGER_REVIEW_AND_OPTIMIZATION_PLAN_2026-05-17.md` (exemplar pattern; commit `4d7dee8`)
- 4 cohort agent outputs preserved as task-notification results in parent session transcript (Agents 54-57)
- `tools/pre_commit_checks.py` (Mechanism C-1 — Phase 5 extension target)
- CLAUDE.md hard rule 9 (progress-logger) + hard rule 11 (gap-check) + hard rule 13 (sub-agent inheritance) + hard rule 14 (post-edit verification cascade)
- HANDOFF §8 Pitfall #9.j/k/l/m/n/o sub-class registry
- `04_EDGE_CASES.md` canonical 14-series register (M/S/I/N/P/G/D/F/V/DP/T/SI/SE/PL)

---

**Awaiting**:
1. Independent reviewer pass on this synthesis (D55+D56)
2. Pipeline-lead Phase 1 cycle authorization
3. B-N + R-N concrete-numeric opening commit (estimated +40 B-Ns + 6 R-Ns)
