# udm-progress-logger v1.2.0 — Review, Edge Cases, and Optimization Plan

**Date**: 2026-05-17
**Author**: parent agent (orchestrator role) per user direction "We should review udm-progress-logger, think of edge cases and come up with a plan for ensuring that this tool properly works and is optimized"
**Status**: 🟡 Draft v1 — awaiting independent reviewer + pipeline-lead sign-off
**Subject**: `.claude/skills/udm-progress-logger/SKILL.md` (currently v1.2.0 per commit `156721e`)
**Scope**: PS-9 SELF (skill review + optimization) + PS-1 ARCH (edge case enumeration); NOT a code-build plan — plan only

---

## §0. Planning session provenance

**Skills invoked during this planning session** (per `udm-planning-session-startup` SKILL.md Step 5 contract):

| Skill / Agent | Invocation | Scope | Rationale |
|---|---|---|---|
| `udm-planning-session-startup` | 2026-05-17 (session-implicit; pipeline-lead trigger phrase "come up with a plan for ensuring...") | Always-mandatory entry | Activates the planning skill set |
| `udm-edge-case-validator` (skill) | inline (this plan §3) | PS-1 explicit; user asked for edge cases | Walk M/S/I/N/P/G/D/F/V/DP/T/SI/SE series for applicability + propose NEW PL-N series |
| `udm-design-reviewer` (agent) | scheduled at plan post-authoring | PS-1 + PS-9 mandatory | Independent architectural review of the optimization design |
| `udm-checks-and-balances` (skill) | scheduled at plan attestation | PS-1 mandatory | 5-gate validation before sign-off |
| `udm-gap-check` (skill) | scheduled at plan attestation | always-mandatory per §2.3 | Independent gap-check on this plan body |
| `udm-progress-logger` (skill) | inline + at attestation | always-mandatory per CLAUDE.md hard rule 9 | **Self-application risk**: this skill IS the subject under review; care needed to invoke v1.2.0 discipline on changes to v1.2.0 itself |
| `udm-post-edit-verification` (skill) | this commit | hard rule 14 | TEST + GAP + REVIEW cascade |
| `udm-decision-recorder` (skill) | DEFERRED if D-N candidates emerge | PS-8 conditional | Plan may surface D-N for harness-level discipline (e.g., D-N for Mechanism C-1 extension covering Step 4.5) |
| `udm-runbook-author` (skill) | DEFERRED if RB-N emerges | PS-5 conditional | Plan may surface RB-N for "verify skill discipline ran correctly" operator procedure |

**Sub-agent inheritance contract** (per hard rule 13): any sub-agent spawned during this session receives explicit skill inheritance directive enumerating the applicable subset.

**Self-application meta-risk note**: per skill v1.2.0 Anti-pattern "writing per-completion entry WITHOUT refreshing existing narrative for inherited drift" — when applying v1.2.0 enhancements to v1.2.0 itself, the producer (parent agent) must apply Step 4.5 arithmetic-propagation sweep to its own work product (this plan body). Specifically: counts of Hard rules / Steps / Edge cases / B-Ns mentioned here must be propagated consistently across §2 + §3 + §5 + §9 if any cycle of revision changes them.

---

## §1. Binding constraints

1. **Preserve v1.2.0 in-flight discipline**: no breaking changes to existing Steps / Hard rules / Anti-patterns. All optimizations are ADDITIVE per D98 semver MINOR/PATCH discipline.
2. **Empirical-evidence-driven**: every proposed enhancement traces to specific empirical anchor (this session's 6-cycle ladder; prior cohort findings; B-N + cycle citations).
3. **Producer-side + harness-side composition**: the skill is producer-side discipline; composes with `tools/pre_commit_checks.py` (Mechanism C-1 harness-side) without replacing or duplicating.
4. **Backward-compat for prior agent invocations**: v1.0.0 + v1.1.0 callers continue to work; v1.2.0+ enhancements are new directives, not behavioral changes.
5. **No build in this plan** — design only. Implementation tracked via B-N opens; build occurs in subsequent cycles per WSJF prioritization.
6. **D72 ladder learning applied**: each optimization candidate must have a traceable rationale connecting to specific Pitfall #9.* sub-class instances OR specific cohort agent finding.

---

## §2. Current state review (v1.2.0)

### §2.1 Skill structure summary

| Component | Count | Source line |
|---|---|---|
| Frontmatter version | v1.2.0 | SKILL.md L3 |
| Sections | 13 | L11-L227 |
| Steps (Step 0 + Step 1 + ... + Step 5; with Step 4.5 added v1.2.0) | 6 | L58-L142 |
| Hard rules | 8 | L144-L153 |
| Anti-patterns | 8 | L154-L165 |
| Integration partners (skills) | 4 | L164-L168 |
| Changelog entries | 3 (v1.0.0 + v1.1.0 + v1.2.0) | L227-L232 |
| Empirical anchors cited | 2026-05-12 8-unit cohort (skill genesis) + 2026-05-17 D72 6-cycle ladder (v1.2.0 enhancements) | scattered |

### §2.2 Coverage map (what the skill enforces)

| Discipline | Mechanism | Source |
|---|---|---|
| Per-completion tracker write | Step 1 routing table + Step 4 _validation_log row | L74-L127 |
| Status-render Pitfall #9.j | Step 2 (leading badge ↔ inline annotation; + 🟠 PARTIAL CLOSURE v1.2.0 extension) | L94-L102 |
| Hard-rule 🟢 lock requirement | Step 3 (no 🟢 without _validation_log + classification entry) | L103-L110 |
| Arithmetic-propagation Pitfall #9.k | Step 4.5 (v1.2.0; per-change-type grep table + verification second-grep) | added at L129 area |
| Convention-registration Pitfall #9.n | Implicit in Step 1 (Step 10 producer self-check inheritance per CLAUDE.md hard rule 9 Step 10) | L74-L93 |
| Cohort partial-failure | Hard rule 6 (log 🟢 units immediately + open B-N per 🔴 unit) | L151 |
| Code-build classification | Hard rule 7 (CODE_BUILD_STATUS.md transition required) | L152 |
| Status-transition arithmetic | Hard rule 8 (v1.2.0; no transition without Step 4.5 sweep) | added |

### §2.3 Composition with other discipline layers

```
Producer-side (this skill) ─┬─→ Harness-side (Mechanism C-1)
                            │   - tools/pre_commit_checks.py 8 checks
                            │   - .githooks/pre-commit + commit-msg
                            │
                            ├─→ Per-artifact validation (udm-checks-and-balances)
                            │
                            ├─→ Per-build (udm-post-build-verify + udm-execution-classifier)
                            │
                            └─→ Per-round (udm-round-closeout)
```

**Currently NOT mechanically enforced** (gap):
- Step 4.5 arithmetic-propagation sweep — no harness check; relies on producer discipline
- 🟠 PARTIAL CLOSURE convention — no canonical legend update in BACKLOG.md preamble (only inline in skill SKILL.md)
- Cross-session continuity (skill writes _validation_log at session N; session N+1 starts with stale state)

### §2.4 Empirical effectiveness evidence (v1.0.0 → v1.2.0)

| Version | Date | Trigger | Empirical evidence base |
|---|---|---|---|
| v1.0.0 | 2026-05-12 | 8-unit cohort tracker-drift gap | Main agent had to close B-items in separate post-cohort turn; build agents didn't update trackers |
| v1.1.0 | 2026-05-17 | B189 closure cohort CLI_* family registry drift | 4-tool L207 drift (3 B-317 cascade + 1 B189) for 1-5 days |
| v1.2.0 | 2026-05-17 | D72 6-cycle ladder on Phase A plan | 5+ Pitfall #9.k instances in tracker updates THE SKILL PRODUCES (self-recurrence) + B-382 partial-closure pattern + narrative-drift across multi-commit cascade |

**Net effectiveness signal**: each version bump was triggered by a NEW empirical pattern not covered by prior version. Suggests the skill is genuinely useful BUT requires ongoing evolution as new failure modes surface. The Step 4.5 self-recurrence pattern (Pitfall #9.k at v1.2.0 anchor) is the strongest evidence that "the skill's own work product is the highest-recurrence drift site."

---

## §3. Edge case enumeration

**Methodology**: walk the canonical 13-series M/S/I/N/P/G/D/F/V/DP/T/SI/SE series for applicability; propose NEW PL-series (Progress Logger discipline) for skill-specific edge cases.

### §3.1 Existing series applicability

| Series | Applicability to udm-progress-logger | Verdict |
|---|---|---|
| M (math/lookback) | N/A (pipeline data series) | ⚪ N/A |
| S (SCD2 reliability) | N/A | ⚪ N/A |
| I (idempotency) | **Applicable** — skill idempotency on re-invocation (I-SKILL-1 below) | 🟡 Applicable |
| N (network/Parquet) | N/A | ⚪ N/A |
| P (PII/encryption) | N/A | ⚪ N/A |
| G (gap detection) | **Applicable** — skill skip detection (G-SKILL-1 below) | 🟡 Applicable |
| D (2x/day cadence) | N/A | ⚪ N/A |
| F (failover) | N/A | ⚪ N/A |
| V (vault provenance) | N/A | ⚪ N/A |
| DP (deployment pipeline) | N/A for skill itself | ⚪ N/A |
| T (testing) | **Applicable** — Tier 0/1 test for skill structure (T-SKILL-1 below) | 🟡 Applicable |
| SI (self-improvement) | **Applicable** — skill version drift; empirical-evidence-obsolescence; convergence with udm-cascade-audit-evolver (SI-SKILL-1 below) | 🟡 Applicable |
| SE (source-exactness) | N/A | ⚪ N/A |

### §3.2 NEW PL-series (Progress Logger discipline) — proposed canonical 14th series

**PL-1**: **Concurrent invocation** — 2 sub-agents finish substantive work simultaneously; both invoke the skill; race condition on `_validation_log.md` append. **Mitigation (revised per Agent 53 review)**: agent-coordination convention — multi-agent teams designate ONE logging agent; the designated agent runs Step 1-5; others wait until Step 5 report emitted. (Original POSIX `fcntl.flock` framing was wrong-layer — skill is documentation discipline, not code module; POSIX-lock is a separate harness-level mitigation tracked via B-N if recurrence observed.)

**PL-2**: **Idempotent re-invocation** — skill invoked twice for same completion event (e.g., parent retries after transient error). **Mitigation**: Step 4 checks for existing same-date/same-event row before append; idempotent re-run produces zero net writes. **Dedup key (formal per Agent 53 IMPROVE)**: `(date YYYY-MM-DD, B-N|D-N|R-N|RB-N reference, EventType per completion type)`. If a row matching ALL three components exists in `_validation_log.md`, the re-invocation is a no-op + report cites "DEDUP — prior entry at YYYY-MM-DD found; no write performed."

**PL-3**: **Skill never invoked** despite substantive work completing (silent skip) — **G-class gap**. **Mitigation (revised per Agent 53 BLOCK)**: Mechanism C-1 9th check NEW (B-PL-5) — pre-commit hook detects substantive commit per ANY of 4 trigger arms WITHOUT corresponding `_validation_log.md` event entry within same commit-message-date → BLOCK:
1. ≥50 LOC delta in non-test files (substantive code change)
2. New public surface (new top-level def/class/EXPORT_TYPE constant)
3. D-N status transition (new D-N row OR existing D-N status badge change)
4. **`BACKLOG.md` staged AND diff contains `⚫ CLOSED` annotation** (4th arm added per Agent 53 finding: documentation-only B-N closures were silently passing the original 3-arm trigger) OR `RISKS.md` R-N score/badge change.

**PL-4**: **Skill invoked too early** (before all sub-tasks in a logical completion land) — partial-state logged + subsequent completions get cumulatively partial-state references. **Mitigation**: Hard rule 6 already handles cohort partial-failure; extend to single-agent multi-task case via Step 0 (post-compaction tracker re-Read mandates verification).

**PL-5**: **Skill version drift** (bidirectional per Agent 53 IMPROVE) — agent invokes v1.0.0 expectations but encounters v1.2.0 (skill is newer); OR agent invokes v1.3.0 expectations but encounters v1.2.0 (skill is older). **Mitigation**: NEW Step 0.5 (skill-version cross-check) — first Read on SKILL.md frontmatter; verify version. (a) If SKILL.md HIGHER than agent expectation, read changelog diff for NEW mandatory steps/rules added in interim versions; apply ALL current-version directives. (b) If SKILL.md LOWER than agent expectation, surface to parent — agent may be assuming directives not yet in canonical skill (could indicate stale skill OR agent mental model fabrication).

**PL-6**: **Step 4.5 false-positive grep** — legitimate prose references to OLD value as historical context (e.g., "previously R36 was ⚪ 2 before re-scoring") could be flagged by simple grep. **Mitigation**: Step 4.5 sweep instructions specify "stale referenc**ES** to OLD value in **CURRENT-STATE** narrative" — historical-context references (with framing words "previously" / "was" / "before" / "originally") are intentionally excluded from "stale" classification.

**PL-7**: **Step 4.5 grep noise outside docs/migration/** — re-scoring an R-N referenced in external artifacts (e.g., legal counsel docs, external compliance reports) — Step 4.5 sweep can't cover. **Mitigation**: Acknowledged scope limitation; new B-N for "external artifact reference tracking" if scope expands (NOT Phase A scope).

**PL-8**: **Convention-cascade enumeration limit** — Step 4.5 table says "ALL canonical doc anchor locations" for new edge case series; what is the comprehensive enumeration? Currently B-382 + B-392 evidence shows initial 14-scope was UNDERCOUNT (7+ additional locations discovered post-hoc). **Mitigation**: NEW automated `tools/find_canonical_enumerations.py` (B-N candidate per §5) — scans `docs/migration/` + `.claude/` + repo root for "M/S/I/N/P/G/D/F/V" pattern; outputs comprehensive enumeration list per new edge case series introduction.

**PL-9**: **🟠 PARTIAL CLOSURE state transition** — what if partial state changes (e.g., 11 of 14 → 13 of 14)? Skill currently has no explicit guidance on PARTIAL state evolution. **Mitigation**: NEW Step 2 sub-bullet: "PARTIAL state changes require leading-badge annotation update (`🟠 PARTIAL CLOSURE` remains; inline annotation updated to `X of Y applied`; if X = Y, full closure ⚫ CLOSED at next invocation)". **Trigger for PARTIAL → ⚫ CLOSED flip (per Agent 53 IMPROVE)**: When the remainder-tracking B-N (`Z deferred to B-NNN`) reaches ⚫ CLOSED status, the original PARTIAL row flips ⚫ CLOSED at the next skill invocation. The skill must Read the remainder B-N status during Step 1 routing for any partial-closed entry; if remainder closed, flip parent. This requires the skill to maintain explicit linkage between parent + remainder B-Ns.

**PL-10**: **Skill self-recurrence on its own enhancements** — v1.2.0 enhancement commit itself produced trackers; should the skill have logged the v1.2.0 introduction via Step 4.5 propagation? **Empirical**: commit `156721e` (v1.2.0 introduction) DID write `_validation_log.md` entry but did NOT explicitly self-apply Step 4.5 (no count narrative changed). **Mitigation (revised per Agent 53 IMPROVE — narrow scope)**: N/A is scoped to **initial skill-introduction commit only** (no count delta in canonical narratives at the introduction point). For SUBSEQUENT skill-revision commits (e.g., v1.3.0 incorporating Phase 1 deliverables) OR plan-revision commits responding to reviewer findings: Step 4.5 MUST be applied to the producer's own work product if the revision introduces count/range/score deltas (see PL-17 NEW for the meta-self-application case during PL-series introduction).

**PL-11**: **Hook BLOCK mid-write** — pre-commit hook BLOCKs while skill is mid-execution; tracker writes partially landed; resume protocol? **Mitigation**: tracker writes happen BEFORE git commit attempt (per Step 1-4 sequence); hook BLOCK affects commit, not tracker state. Already correctly ordered.

**PL-12**: **Skill conflict with udm-round-closeout** at round boundary — which takes precedence? **Mitigation**: Hard rule 1 already mandates per-completion timing ("Log at the moment of completion, not later"); udm-round-closeout is later cadence and consumes prior per-completion entries. No conflict; complementary.

**PL-13**: **Tracker write succeeds but commit fails** — `_validation_log.md` updated but no audit trail in git. **Mitigation (revised per Agent 53 IMPROVE — concrete protocol)**: Step 0 EXTENSION (uncommitted-tracker-write detection at session start) — at session start, the skill first invocation runs `git status --short` on `docs/migration/`; if uncommitted tracker writes are observed from prior session, verify whether the corresponding completion was already committed (`git log -p docs/migration/_validation_log.md`) OR roll back the tracker write manually before proceeding. Composes with existing Step 0 post-compaction tracker re-Read.

**PL-14**: **Empirical evidence base obsolescence** — a Hard rule added in v1.0.0 (e.g., Hard rule 4) but project workflow evolves; rule becomes obsolete. **Mitigation**: SI series + udm-cascade-audit-evolver Round 8 cadence reviews skill rules at quarterly cadence per MAINTENANCE.md; obsolete rules transition to ⚫ Deprecated in changelog with rationale.

**PL-15**: **Cross-session continuity** — skill writes `_validation_log.md` at session N; session N+1 starts with stale state of in-memory expectations. **Mitigation**: Step 0 (post-compaction tracker re-Read) is the existing mitigation; covers fresh-session start.

**PL-16 (NEW per Agent 53)**: **Cohort cross-agent state drift** — different from PL-1 concurrent invocation. Cohort agents each update DIFFERENT trackers based on their PARTIAL view of cohort state. Agent A closes B-N-1 in BACKLOG.md; Agent B opens new R-N in RISKS.md; neither runs full Step 4.5 sweep because each sees only its own work. Resulting tracker state is consistent per-unit but collectively incoherent (R-N references a B-N count Agent A just updated). **Mitigation**: per PL-1 convention, the designated logging agent reads ALL cohort members' outputs before Step 1 (not just its own); Step 4.5 sweep runs on UNION of cohort-touched canonical references.

**PL-17 (NEW per Agent 53; Pitfall #9.m self-application)**: **PL-series introduction itself triggers convention-cascade per Pitfall #9.n** — introducing PL-series as 14th canonical series immediately creates obligation to propagate "14 canonical series total" + "M/S/I/N/P/G/D/F/V/DP/T/SI/SE/PL" enumerations across ~21+ canonical anchor locations (per B-382 + B-392 evidence base). Additionally: v1.3.0 SKILL.md edits introducing PL-series must THEMSELVES apply Step 4.5 to the SKILL.md body when the Step 4.5 table's "new edge case series" row is updated to mention PL-series. **Mitigation**: B-PL-14 explicitly tracks the canonical-doc cascade (~21+ locations per Agent 49 G3.9.n empirical expansion); skill-edit commit applies Step 4.5 to its own work product per the Anti-pattern v1.2.0 directive.

### §3.3 Edge case series summary

**15 NEW PL-series edge cases proposed** (revised per Agent 53 review: original 13 + PL-16 + PL-17). Total NEW canonical entries for `04_EDGE_CASES.md`: **15** (PL-1 through PL-17; PL-14 + PL-15 are existing-discipline-covered per original framing; PL-16 + PL-17 added per reviewer cohort cross-agent + meta-self-application).

---

## §4. Optimization opportunities (raw enumeration)

1. **Tier 0 test for skill SKILL.md** — frontmatter parse + section header presence + Step 4.5 + Hard rule 8 + Changelog v1.2.0 row present
2. **Tier 1 integration test** — end-to-end fake B-N closure event + skill invocation + verify all expected tracker writes happen
3. **Mechanism C-1 9th orchestrator check** — extend `tools/pre_commit_checks.py` with `check_progress_logger_compliance` (detect substantive commit WITHOUT corresponding `_validation_log.md` entry → BLOCK)
4. **Automated Step 4.5 arithmetic sweep** — script `tools/check_arithmetic_propagation.py` mechanically greps canonical narratives for stale counts/ranges/scores; called from Mechanism C-1 + invocable manually
5. **Skill-version cross-check directive** — Step 0.5 NEW; first Read on SKILL.md frontmatter; verify version matches expectation
6. **Concurrent-invocation lock** — Hard rule 9 NEW; POSIX `fcntl.flock` LOCK_EX pattern
7. **Convention-cascade automation** — `tools/find_canonical_enumerations.py` scans repo for canonical enumeration anchor locations; outputs comprehensive list per new edge case series
8. **Skill prompt for sub-agents inheritance directive** — parent agent task brief MUST include explicit "invoke udm-progress-logger when you finish" line when spawning sub-agents
9. **Empirical effectiveness measurement framework** — track Step 4.5 sweeps catching actual drift vs false positives over time; quarterly review per MAINTENANCE.md
10. **Multi-language regex patterns** — skill provides canonical PowerShell + sed + grep snippets for the arithmetic sweep (reduces per-invocation cognitive overhead)
11. **🟠 PARTIAL CLOSURE legend canonization** — update BACKLOG.md preamble status legend to include 🟠 PARTIAL CLOSURE alongside 🟡 Open / ⚫ CLOSED / 🟠 Noticeable (currently only documented in skill SKILL.md Step 2; not in tracker legend)
12. **Step 4.5 false-positive guidance** — explicit framing for distinguishing "historical-context references" from "stale-narrative references" (PL-6 mitigation)
13. **Cross-skill composition diagram** — visual diagram or ASCII art showing skill cascade ordering (Step 0 → 1 → 2 → 3 → 4 → 4.5 → 5 → udm-gap-check trigger → udm-round-closeout)
14. **Skill-self-application protocol** — explicit guidance for when the skill IS the subject of modification (meta-application risk per PL-10)
15. **Performance baseline measurement** — measure skill invocation duration baseline; flag if any future enhancement materially slows the discipline cycle

### §4.1 Optimization ranked by WSJF (COD ÷ JS)

| # | Optimization | COD | JS | WSJF | Priority | Closure target |
|---|---|---|---|---|---|---|
| 1 | Tier 0 test for skill structure | 4 | 1 | 4.0 | HIGH | Next cycle |
| 3 | Mechanism C-1 9th orchestrator check (skill compliance enforcement) | 5 | 3 | 1.67 | HIGH | 1-2 cycles |
| 11 | 🟠 PARTIAL CLOSURE legend canonization in BACKLOG.md | 3 | 1 | 3.0 | HIGH | Next cycle |
| 4 | Automated Step 4.5 arithmetic sweep tool | 4 | 3 | 1.33 | MEDIUM | 2 cycles |
| 5 | Skill-version cross-check (Step 0.5) | 3 | 1 | 3.0 | MEDIUM | Next cycle |
| 6 | Concurrent-invocation lock (Hard rule 9) | 3 | 1 | 3.0 | MEDIUM | Next cycle (if PL-1 observed) |
| 2 | Tier 1 integration test | 3 | 3 | 1.0 | MEDIUM | 2-3 cycles |
| 8 | Sub-agent inheritance directive prompt extension | 2 | 1 | 2.0 | MEDIUM | Next cycle |
| 12 | Step 4.5 false-positive guidance | 2 | 1 | 2.0 | MEDIUM | Inline addition |
| 14 | Skill-self-application protocol | 2 | 1 | 2.0 | MEDIUM | Inline addition |
| 7 | Convention-cascade enumeration tool | 3 | 3 | 1.0 | LOW | Opportunistic |
| 9 | Empirical effectiveness measurement framework | 2 | 3 | 0.67 | LOW | Phase 3+ |
| 10 | Multi-language regex pattern library | 1 | 2 | 0.5 | LOW | Polish |
| 13 | Cross-skill composition diagram | 1 | 1 | 1.0 | LOW | Polish |
| 15 | Performance baseline measurement | 1 | 2 | 0.5 | LOW | Polish |

---

## §5. Recommended optimizations (priority-ordered)

### Phase 1 — High-WSJF, low-risk (CYCLE 1)

**Goal**: catch regressions + establish baseline + canonize convention.

1. **B-PL-1 (HIGH; WSJF 4.0)**: Author `tests/tier0/test_skill_progress_logger.py` (Tier 0 smoke test) — verifies SKILL.md frontmatter parses; version field present; Step 0 + Step 1 + Step 2 + Step 3 + Step 4 + Step 4.5 + Step 5 section headers present; Hard rules 1-8 enumerated; Anti-patterns ≥6 present; Changelog has v1.2.0 row.

2. **B-PL-2 (HIGH; WSJF 3.0)**: Canonize 🟠 PARTIAL CLOSURE in BACKLOG.md status legend preamble. Currently only documented in skill Step 2; BACKLOG.md legend says 🟡 Open / ⚫ CLOSED / 🟠 Noticeable. Add 🟠 PARTIAL CLOSURE as 4th canonical status with definition.

3. **B-PL-3 (MEDIUM; WSJF 3.0)**: Skill Step 0.5 (skill-version cross-check) — first Read on SKILL.md frontmatter; verify version matches expectation. Inline addition to SKILL.md.

4. **B-PL-4 (MEDIUM; WSJF 2.0)**: Step 4.5 false-positive guidance (PL-6 mitigation) — explicit framing words ("previously" / "was" / "before" / "originally") excluded from stale-classification. Inline addition.

### Phase 2 — Harness-side mechanical enforcement (CYCLE 2)

5. **B-PL-5 (HIGH; WSJF 1.67)**: Mechanism C-1 9th orchestrator check `check_progress_logger_compliance` in `tools/pre_commit_checks.py` — detects substantive commit per ANY of 4 trigger arms (revised per Agent 53 BLOCK on PL-3 trigger underspecification): (a) ≥50 LOC delta in non-test files; (b) new public surface (top-level def/class/EXPORT_TYPE constant); (c) D-N status transition; (d) `BACKLOG.md` staged AND diff contains `⚫ CLOSED` annotation OR `RISKS.md` R-N score/badge change. If trigger fires WITHOUT corresponding `_validation_log.md` entry within same commit-date → BLOCK. Closes silent-skip gap (PL-3) including the documentation-only B-N closure false-negative arm originally missed.

6. **B-PL-6 (MEDIUM; WSJF 1.33)**: Automated Step 4.5 arithmetic sweep tool `tools/check_arithmetic_propagation.py` — mechanically greps canonical narratives for stale counts/ranges/scores; called from Mechanism C-1 + invocable manually. Closes Pitfall #9.k mechanical-defense gap.

### Phase 3 — Integration testing + evidence collection (CYCLE 3+)

7. **B-PL-7 (MEDIUM; WSJF 1.0)**: Tier 1 integration test — end-to-end fake B-N closure event + skill invocation + verify all expected tracker writes happen. Pattern from existing `tests/tier1/test_*` cohort.

8. **B-PL-8 (LOW; WSJF 0.67)**: Empirical effectiveness measurement framework — quarterly review per MAINTENANCE.md tracking Step 4.5 sweep effectiveness (catches per invocation; false positives per invocation; net signal-to-noise ratio).

### Phase 4 — Polish (DEFERRED)

9. **B-PL-9 (LOW; WSJF 1.0)**: Cross-skill composition diagram / ASCII art in SKILL.md
10. **B-PL-10 (LOW; WSJF 0.5)**: Multi-language regex pattern library
11. **B-PL-11 (LOW; WSJF 0.5)**: Performance baseline measurement
12. **B-PL-12 (LOW; WSJF 1.0)**: Convention-cascade enumeration tool

### §5.1 Phase 1 deliverables (suggested first-cycle build)

| Artifact | Lines | Effort | B-PL number |
|---|---|---|---|
| `tests/tier0/test_skill_progress_logger.py` (NEW) | ~80 LOC | 0.5 cycle | B-PL-1 |
| `docs/migration/BACKLOG.md` status legend preamble update | ~5 LOC | 0.1 cycle | B-PL-2 |
| `.claude/skills/udm-progress-logger/SKILL.md` Step 0.5 addition | ~15 LOC | 0.2 cycle | B-PL-3 |
| SKILL.md Step 4.5 false-positive guidance | ~10 LOC | 0.1 cycle | B-PL-4 |
| **TOTAL Phase 1** | ~110 LOC | ~1 cycle | 4 B-Ns |

---

## §6. Verification approach

### §6.1 Tier 0 test scope (B-PL-1)

- Frontmatter YAML parses cleanly via `yaml.safe_load()`
- `name:` field = `udm-progress-logger`
- `version:` field matches semver pattern `v\d+\.\d+\.\d+`
- ≥13 section headers present (## level)
- 8 hard rules enumerated (Hard rule 1 through Hard rule 8)
- ≥8 anti-patterns enumerated
- Changelog table has 3 rows (v1.0.0 + v1.1.0 + v1.2.0); each with date + change + trigger
- Step 4.5 section present with table
- Hard rule 8 present
- Self-application meta-risk note present (per this plan §0)

### §6.2 Tier 1 integration test scope (B-PL-7)

- Create fake B-N closure event (e.g., temporary BACKLOG row)
- Simulate skill invocation (mock parent agent → skill → tracker writes)
- Verify `_validation_log.md` row written with correct format
- Verify BACKLOG.md row struck through + ⚫ CLOSED annotation
- Verify Step 4.5 sweep would catch synthetic arithmetic drift if introduced
- Verify Hard rule 8 enforcement (status transition without sweep → flag)

### §6.3 Mechanical enforcement (Mechanism C-1; B-PL-5 + B-PL-6)

`check_progress_logger_compliance` check:
- Trigger conditions: substantive commit detection per criteria (≥50 LOC OR new D-N/R-N row OR new module/class/function)
- Verify: `_validation_log.md` event entry exists within ±1 day of commit date
- Verdict: BLOCK if substantive + no entry; PASS if entry present
- Exemption: trivial commits (typo / whitespace / badge flip per anti-trigger detection)

`check_arithmetic_propagation` check (B-PL-6):
- Trigger conditions: staged file contains B-N range claim ("B-X through B-Y") OR R-N score ("R-N 🟡 N") OR series enumeration ("M/S/I/...")
- Verify: count/range/score is current per canonical source comparison
- Verdict: BLOCK if mismatch; PASS if consistent
- Exemption: historical-context framing words present nearby

### §6.4 Manual verification per release

Each version bump (v1.2.0 → v1.3.0 etc.) requires:
1. Tier 0 test pass (B-PL-1 implemented)
2. Changelog row added with empirical anchor citation
3. Self-application of Step 4.5 if any count/range/score in skill body changed
4. Independent reviewer pass (D55+D56 discipline)
5. `_validation_log.md` event entry per the skill's own hard rule 1

---

## §7. Implementation phase plan

### §7.1 Cycle gates

| Phase | Deliverable | Gate-blockers | Estimated cycles |
|---|---|---|---|
| Phase 1 | B-PL-1 through B-PL-4 (Tier 0 test + legend + Step 0.5 + Step 4.5 guidance) | Pipeline-lead approval of THIS plan; B-PL-1 through B-PL-4 opened in BACKLOG | 1 cycle |
| Phase 2 | B-PL-5 + B-PL-6 (Mechanism C-1 extensions) | Phase 1 complete; B-PL-5 + B-PL-6 opened | 1-2 cycles |
| Phase 3 | B-PL-7 (Tier 1 integration test) | Phase 2 Mechanism C-1 9th check passing in CI (per Agent 53 BLOCK — fake-event integration test uses mocked tracker files, NOT Docker containers; pyarrow/testcontainers dependency removed) | 1-2 cycles |
| Phase 4 | Polish items (B-PL-8 through B-PL-12) | Opportunistic | Deferred |

### §7.2 Cycle 1 (Phase 1) acceptance criteria

- ✅ B-PL-1 Tier 0 test passes (verifies SKILL.md structure post-Phase-1 additions)
- ✅ BACKLOG.md status legend preamble updated to canonize 🟠 PARTIAL CLOSURE
- ✅ SKILL.md updated to v1.3.0 with Step 0.5 + Step 4.5 false-positive guidance
- ✅ Changelog v1.3.0 row added with empirical anchor citation (THIS plan + B-PL-1 through B-PL-4)
- ✅ Self-application of Step 4.5 verified (no count drift introduced)
- ✅ Independent reviewer pass (D55+D56)
- ✅ `_validation_log.md` event entry per skill hard rule 1

### §7.3 Out-of-scope for this plan

- Building Mechanism C-1 9th orchestrator check (Phase 2 work; tracked but not authored here)
- Building Tier 1 integration test (Phase 3 work)
- Cross-cutting concerns (e.g., udm-round-closeout review; udm-checks-and-balances review) — those are separate planning sessions if needed

---

## §8. Risk + invariant preservation

### §8.1 Skill invariants preserved

| Invariant | Mechanism | This plan touches? |
|---|---|---|
| Per-completion timing (Hard rule 1) | Skill version invariant | ✅ Preserved |
| Append-only tracker discipline (Hard rule 2) | Skill version invariant | ✅ Preserved |
| Closure mechanism citation (Hard rule 3) | Skill version invariant | ✅ Preserved |
| No 🟢 without _validation_log (Hard rule 4) | Skill version invariant | ✅ Preserved |
| Build-code classification (Hard rule 5+7) | Skill version invariant | ✅ Preserved |
| One invocation per completion event (Hard rule 6) | Skill version invariant | ✅ Preserved; PL-2 idempotency mitigation extends |
| Status-transition arithmetic sweep (Hard rule 8; v1.2.0) | Recent addition | ✅ Preserved; PL-6 false-positive guidance extends |
| 🟠 PARTIAL CLOSURE convention (Step 2; v1.2.0) | Recent addition | ✅ Preserved; B-PL-2 canonizes externally |

### §8.2 New risk register entries

| R-N candidate | Description | Score |
|---|---|---|
| R-PL-A | Phase 1 cycle introduces breaking change to v1.2.0 callers | Low × Medium = 2 ⚪ |
| R-PL-B | Mechanism C-1 9th check (B-PL-5) **insufficient BLOCK coverage due to trigger underspecification (false-NEGATIVE risk)** — revised per Agent 53 Section D: original "excessive false-positive" framing was wrong-direction. The 4-arm trigger (per PL-3 mitigation revision) closes the documentation-only B-N closure false-negative gap; if implementation drifts back to 3-arm trigger, false-negatives recur. Mitigation: B-PL-5 implementation MUST land with 4-arm trigger as specified; Tier 0 test verifies all 4 arms fire on synthetic inputs | Low × High = 3 🟡 |
| R-PL-C | Step 4.5 false-positive guidance (B-PL-4) too permissive; misses genuine stale-narrative cases | Low × Low = 1 ⚪ |
| **R-PL-D** | **PL-series cascade incompleteness on introduction** (NEW per Agent 53 Section D) — structurally analogous to B-382 14-location undercount that expanded to 21+ per B-392. If PL-series cascade scope under-counts canonical anchor locations, partial registration would persist across canonical docs for days. Mitigation: B-PL-14 explicit scope = comprehensive grep-and-cascade per `tools/find_canonical_enumerations.py` (B-PL-12); compose with Mechanism C-1 9th check (B-PL-5) | Low × Medium = 2 ⚪ |
| **R-PL-E** | **v1.3.0 SKILL.md substrate-edit friction underestimated in Phase 1 schedule** (NEW per Agent 53 Section D meta-risk) — `.claude/skills/udm-*/SKILL.md` is SUBSTRATE per `tools/cascade_classifier.py::SUBSTRATE_DIR_PREFIXES`; v1.3.0 SKILL.md edits incorporating Phase 1 deliverables require FULL cascade evidence (TEST + GAP + REVIEW) per hard rule 14 substrate-edit clause + commit-msg trigger detection on exemption-claim phrasings. Producer must spawn reviewer for substrate-edit; 1-cycle Phase 1 estimate may underbudget this friction | Low × Low = 1 ⚪ |

### §8.3 PL-N edge case series (proposed canonical 14th)

PL-1 through PL-13 enumerated in §3.2; would land in `04_EDGE_CASES.md` as a NEW series (after SE). Total series count: 13 → 14 (would trigger another Step 4.5 SE-N-style cascade per Pitfall #9.n discipline).

---

## §9. B-N enumeration

**15 NEW B-N candidates** proposed (B-PL-1 through B-PL-15; all tracked via this §9 enumeration; no B-N needed for this disposition since the candidates themselves are the §9 enumeration): revised per Agent 53 F4 finding fixing original "12" arithmetic-drift + Agent 53 Section B missing-item adding B-PL-15 + originally-omitted B-PL-13 + B-PL-14 from initial count; original §9 said "12" which itself was an empirical instance of Pitfall #9.k self-recurrence in the very plan about preventing such drift:

| B-PL | Title | WSJF | Phase | Closure target |
|---|---|---|---|---|
| B-PL-1 | Tier 0 test for skill SKILL.md structure | 4.0 | 1 | Next cycle |
| B-PL-2 | Canonize 🟠 PARTIAL CLOSURE in BACKLOG.md status legend | 3.0 | 1 | Next cycle |
| B-PL-3 | SKILL.md Step 0.5 skill-version cross-check directive | 3.0 | 1 | Next cycle |
| B-PL-4 | SKILL.md Step 4.5 false-positive guidance | 2.0 | 1 | Next cycle |
| B-PL-5 | Mechanism C-1 9th orchestrator check (skill compliance enforcement) | 1.67 | 2 | 1-2 cycles |
| B-PL-6 | Automated Step 4.5 arithmetic sweep tool | 1.33 | 2 | 2 cycles |
| B-PL-7 | Tier 1 integration test for skill end-to-end | 1.0 | 3 | 2-3 cycles |
| B-PL-8 | Empirical effectiveness measurement framework | 0.67 | 4 | Quarterly cadence |
| B-PL-9 | Cross-skill composition diagram in SKILL.md | 1.0 | 4 | Opportunistic |
| B-PL-10 | Multi-language regex pattern library | 0.5 | 4 | Polish |
| B-PL-11 | Performance baseline measurement | 0.5 | 4 | Polish |
| B-PL-12 | Convention-cascade enumeration automation tool | 1.0 | 4 | Opportunistic |
| **B-PL-15** | **CCL self-check fallback verification mechanism** (NEW per Agent 53 Section B missing-item finding) — narrow-scope workers (e.g., Pattern B build agents per SKILL.md L197-L204) operate under CCL self-edit fallback; no verification mechanism prevents agent from falsely citing "fallback applied" while silently skipping CCL entirely. Build verification check (Tier 1 OR Mechanism C-1 extension) for fallback-claim authenticity | 1.0 | 3 | Phase 3 |

**Plus PL-series edge case authoring** (B-PL-13 through B-PL-14):

| B-PL | Title | WSJF | Phase | Closure target |
|---|---|---|---|---|
| B-PL-13 | Author PL-series edge cases (PL-1 through PL-13) in `04_EDGE_CASES.md` (14th canonical series after SE) | 2.0 | 1 | Next cycle |
| B-PL-14 | Cascade PL-series convention-registration per Pitfall #9.n (CLAUDE.md L448 + INDEX.md L37 + GLOSSARY.md L633 + 04_EDGE_CASES.md preamble + ~10 additional canonical doc locations) | 1.5 | 2 | Cycle after B-PL-13 lands |

**Plus new R-N candidates** (R-PL-A + R-PL-B [reframed per Agent 53] + R-PL-C + R-PL-D + R-PL-E per §8.2; 5 NEW R-Ns total).

**Plus NEW edge case series** (PL-series; 14th canonical) — opens cascade requirement per Pitfall #9.n.

**B-N numbering**: actual numeric B-N assignment (next-available slots after B-392 latest in BACKLOG) happens at next BACKLOG.md update commit; "B-PL-N" is the placeholder convention used in this plan-local scope for clarity.

---

## §10. Sign-off readiness checklist

### §10.1 Pre-sign-off actions (this commit)

- [x] Plan authored with §0 provenance
- [x] §3 edge case enumeration (13 NEW PL-N proposed)
- [x] §4-§5 optimization opportunities ranked
- [x] §7 phase plan with cycle gates
- [x] §9 B-N enumeration
- [ ] Spawn independent design-reviewer per D55+D56
- [ ] Spawn independent gap-check
- [ ] Open 15 B-Ns in BACKLOG.md (next-available range after current latest B-392; actual numeric assignment at commit time) — updated per Agent 53 remediation adding B-PL-15
- [ ] Open 5 R-Ns in RISKS.md (R-PL-A through R-PL-E per Agent 53 revision)
- [ ] Open PL-series in `04_EDGE_CASES.md` (14th canonical series)
- [ ] Cascade PL-series enumeration update per Pitfall #9.n discipline (B-PL-14)

### §10.2 Pre-Phase-1-execution actions

- [ ] Pipeline-lead sign-off on THIS plan
- [ ] B-PL-1 + B-PL-2 + B-PL-3 + B-PL-4 + B-PL-13 opened in BACKLOG.md with concrete numbers
- [ ] Phase 1 cycle authorization

### §10.3 Phase 1 acceptance criteria (cycle gate)

Per §7.2 above.

---

## §11. Cross-references

- `.claude/skills/udm-progress-logger/SKILL.md` (v1.2.0; subject under review)
- `tools/pre_commit_checks.py` (Mechanism C-1; 8 current orchestrator checks; B-PL-5 + B-PL-6 add 9th + arithmetic-propagation check)
- `tools/check_arithmetic_propagation.py` (NEW per B-PL-6)
- `tests/tier0/test_skill_progress_logger.py` (NEW per B-PL-1)
- `tests/tier1/test_skill_progress_logger_integration.py` (NEW per B-PL-7)
- `docs/migration/BACKLOG.md` (status legend canonization per B-PL-2; ~14 NEW B-Ns)
- `docs/migration/RISKS.md` (3 NEW R-Ns)
- `docs/migration/04_EDGE_CASES.md` (NEW PL-series 14th canonical per B-PL-13)
- `docs/migration/_validation_log.md` (event entries per skill hard rule 1)
- `docs/migration/PLANNING_DISCIPLINE.md` (sub-agent inheritance contract per hard rule 13)
- CLAUDE.md hard rule 9 (progress-logger discipline) + hard rule 14 (post-edit verification cascade)

---

**Awaiting**:
1. Independent design-reviewer pass on THIS plan
2. Independent gap-check on THIS plan
3. Pipeline-lead sign-off on Phase 1 cycle authorization
4. Concrete B-N number assignment at commit
