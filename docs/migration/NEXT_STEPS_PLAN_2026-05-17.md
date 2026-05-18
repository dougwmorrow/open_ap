# Next Steps Plan — Markdown Refactor Residual + UDM Pipeline Pivot

**Date**: 2026-05-17
**Author**: pipeline lead + parent agent (orchestrator role)
**Scope**: multi-domain plan covering (a) markdown-refactor remainder + (b) UDM pipeline pivot sequencing
**Status**: 🟢 Phase 0 infrastructure complete (skill + hook); Phases 1-N awaiting pipeline-lead sequencing direction
**Estimated effort**: Phase 0 = +1.5-2 cycles (DONE); Phases 1-N = TBD per chosen sequencing path

---

## §0. Planning session provenance

**Skills invoked during this planning session** (per `udm-planning-session-startup` skill at session start; see `docs/migration/PLANNING_DISCIPLINE.md` for matrix):

| Skill | Invoked at | Scope reference | Rationale |
|---|---|---|---|
| `udm-planning-session-startup` | 2026-05-17 (session start) | Always-mandatory entry skill | Walked 5-step protocol; surfaced 9 active + 9 on-demand skills; user approved |
| `udm-gap-check` | 2026-05-17 (post-startup) | always-mandatory §2.3 | Independent reviewer Agent `a694387bbf38ed19b` (29th cumulative) returned 🔴 BLOCK on initial skill activation list — 3 mandatory skills demoted to on-demand without §2.5 justification + PS-8 D-N missing dual-PRIMARY. Remediation applied inline + user re-approved revised list. |
| `udm-design-reviewer` (agent) | 2026-05-17 (Phase 0 attestation) | PS-1 + PS-8 mandatory | Independent review of Phase 0 multi-agent team output BEFORE plan commit. Agent `adf74ca386f192d64` (32nd cumulative) returned ✅ SOUND with 3 actionable IMPROVEs + 5 follow-up suggestions (no B-N needed — all dispositioned in §7.1: 4 absorbed inline + 1 deferred as low-WSJF opportunistic). |
| `udm-checks-and-balances` (skill) | 2026-05-17 (Phase 0 attestation) | PS-1 + PS-2 + PS-8 mandatory | 5-gate validation embedded in reviewer protocol |
| `udm-brainstorm` (skill) | 2026-05-17 (pivot scope decision) | PS-1 + PS-8 conditional | Pivot has 4+ defensible options (A/B/C/D for UDM + multiple for markdown residual); options enumerated below in §4 |
| `udm-researcher` (agent) | DEFERRED | PS-1 + PS-2 mandatory | Not invoked — primary-source grounding handled inline via Read tool; no novel research artifacts needed for this scope-decision plan |
| `udm-decision-recorder` (skill) | DEFERRED | PS-8 mandatory | Will fire if pivot sequencing decision warrants D-N capture; tracked in §6 below |
| `udm-planning` (skill) | DEFERRED | PROMOTED for markdown-residual execution | Will fire at markdown-residual execution time for task decomposition into 2-5 min units |
| `udm-progress-logger` (skill) | 2026-05-17 (throughout) | always-mandatory §2.3 | Tracker updates per per-build-type checklist for Phase 0 commit |
| `udm-post-edit-verification` (skill) | 2026-05-17 (this commit) | always-mandatory §2.3 per hard rule 14 | TEST + GAP + REVIEW cascade applied for Phase 0 commit + this plan deliverable |
| `udm-step-10-verifier` (skill) | DEFERRED to on-demand per §2.5 justification | always-mandatory §2.3 (demoted) | Will auto-promote if plan execution introduces new public surface |
| `superpowers-verification-before-completion` (skill) | DEFERRED to on-demand per §2.5 justification | always-mandatory §2.3 (demoted) | Auto-invokes at plan-deliverable commit attestation |
| `superpowers-systematic-debugging` (skill) | DEFERRED to on-demand per §2.5 justification | always-mandatory §2.3 (demoted) | Auto-invokes if research/execution surfaces unexpected behavior |

**Sub-agents spawned + skill inheritance** (per CLAUDE.md hard rule 13):

| Sub-agent | Spawned at | Skills inherited |
|---|---|---|
| general-purpose (gap-check on skill activation) | 2026-05-17 (29th cumulative) | udm-gap-check 6-category audit protocol |
| general-purpose (Worker A — udm-context-loader skill authoring) | 2026-05-17 (30th cumulative) | udm-progress-logger Step 0 + udm-checks-and-balances + udm-step-10-verifier + udm-post-edit-verification + superpowers-verification-before-completion + udm-test-author |
| general-purpose (Worker B — check_planning_provenance authoring) | 2026-05-17 (31st cumulative) | udm-progress-logger Step 0 + udm-checks-and-balances + udm-step-10-verifier + udm-execution-classifier + udm-post-edit-verification + superpowers-verification-before-completion + superpowers-tdd + udm-test-author |
| udm-design-reviewer (Phase 0 independent review) | 2026-05-17 (32nd cumulative) | udm-checks-and-balances 5-gate + udm-gap-check 6-category awareness + superpowers-verification-before-completion |

**B-N candidates surfaced during planning session** (tracked for closure consideration):
- 2 from gap-check reviewer (PS-N matrix amendments — §2.5 vs §2.3 ambiguity; udm-decision-recorder mandatory-for-pivot-sessions)
- 5 from Phase 0 design reviewer (numbers deliberately NOT cited to avoid B-N collision with canonical sequence; 4 absorbed inline + 1 deferred — see §7 for per-candidate disposition; no B-N needed since all dispositioned in-session)

---

## §1. Background

Post-meta-cascade session (76+ commits since 2026-05-15) approaches saturation. User requested transition planning:
1. **Q1**: What's the progress remaining for the markdown file refactor effort?
2. **Q2**: Do we need to plan anything before shifting to the UDM data pipeline effort?

Audit results (per pre-planning turn):
- **Markdown refactor**: 🟢 LOCKED 2026-05-15; ~6-9 hours active work remaining; D.1 calendar-deferred via B-272 until ~2026-06-08
- **UDM pipeline**: Phase 0 = 90% closed; Phase 1 substantially built; Phase 2 pilot requires live infrastructure (operator-blocked from Claude Code)

Plan answers Q1+Q2 by producing a sequencing decision + Phase 0 infrastructure investment to support clean handoff.

---

## §2. Goals

1. **Complete Phase 0 infrastructure investments** to support all forward plan execution: `udm-context-loader` skill + planning-provenance mechanical hook check
2. **Sequence remaining markdown-refactor work** against UDM pipeline pivot priorities
3. **Establish clear pivot scope decision** with explicit option enumeration (A/B/C/D)
4. **Preserve session-momentum metrics** (28+ multi-agent applications; 6→7 mechanical detectors; SKILL v1.2.0 in force) by codifying the meta-cascade closure point

---

## §3. Phase 0 — Infrastructure investments (✅ DONE this commit)

Authored in parallel via multi-agent team (Worker A + Worker B + independent reviewer):

### §3.1 `udm-context-loader` skill (B-275 ⚫ CLOSED)

- **NEW**: `.claude/skills/udm-context-loader/SKILL.md` (~236 lines)
- **NEW**: `tests/tier0/test_skill_context_loader.py` (10 tests; 10/10 PASS)
- **AMEND**: `docs/migration/PLANNING_DISCIPLINE.md` §2 matrix L111 (PS-6 COHORT row updated from "planned" to "newly-authored")
- **AMEND**: `docs/migration/BACKLOG.md` L363 (B-275 strikethrough + Pitfall #9.j leading-badge flip)

Closes B-275 (WSJF 3.0). Reduces sub-agent context-load cost when spawning parallel cohorts during plan execution.

### §3.2 `check_planning_provenance` 7th orchestrator hook check

- **AMEND**: `tools/pre_commit_checks.py` — added `check_planning_provenance()` function + `_is_planning_doc()` helper + `_PLANNING_PROVENANCE_HEADER_RE` regex
- **AMEND**: `tests/tier0/test_pre_commit_checks.py` — 5 new Tier 0 tests + 3 prior assertions updated
- **AMEND**: `CLAUDE.md` Structure L97 — `tools/pre_commit_checks.py` count "4 functions" → "7 functions" enumerated

CHECKS registry now 7 (was 6). Closes the "1b00755" empirical precedent class — planning-discipline now harness-enforced at commit-time.

### §3.3 Reviewer-found inline-fixes (4 applied inline pre-commit)

Per Agent `adf74ca386f192d64` (32nd cumulative) ✅ SOUND-with-improvements:
1. Cross-ref Composition table row in SKILL.md → `check_planning_provenance`
2. Cross-ref docstring in `check_planning_provenance` → `udm-context-loader` SKILL.md
3. Step 3 scope-keyword table fallback row for plan-authoring scope (PS-N session deliverable)
4. Step 5 "NOT a file" rationale clause (snapshot-staleness risk)

### §3.4 Pytest verification

- Worker A: 10/10 PASS on `test_skill_context_loader.py`
- Worker B: 34/34 PASS on `test_pre_commit_checks.py`
- Authoritative re-run post-multi-agent cohort: **2465 pass / 10 skip / 0 fail** (was 2449; +16 net)

---

## §4. Phase 1 — Sequencing decision (PIPELINE-LEAD INPUT REQUIRED)

### §4.1 Pivot scope options enumerated

| Option | Scope | Effort | Pros | Cons |
|---|---|---|---|---|
| **A: Phase 0 prep cleanup** | Close partial-closed items 0.1/0.2/0.3/0.4/0.8/0.17 (B185 PII inventory / B186 Phase 3-6 deep-dive plans / B188 lateness measurement / B189 PII data import / B190 capacity baseline) | ~2-3 cycles | Smallest-scope concrete progress; tight feedback loop; closes Phase 0 to 100% | Mostly spec-side work; doesn't run actual pipeline; may surface compliance/DBA review dependencies |
| **B: Phase 1 R-N continuation** | Identify any unbuilt Phase 1 round work (verify via `phase1/00_phase_overview.md` + CODE_BUILD_STATUS.md); pick smallest unbuilt round | unbounded; depends on round | Forward progress on canonical infrastructure | Need to verify what's actually unbuilt vs spec'd-but-built |
| **C: Phase 2 pilot ACCT testing** | Run small-table flow on DNA.osibank.ACCT (1.2M rows) end-to-end | **OPERATOR-BLOCKED** | Highest validation value; exercises CDC + SCD2 + reconciliation paths | Requires live Oracle + SQL Server connections + Claude Code does NOT have these; user must execute |
| **D: Open B-N bundle closure** | Phase 0 prep impl items B185/B188/B189/B190 (well-spec'd; effort estimated) | ~3-5 cycles | Closes multiple B-Ns; advances Phase 0 to ≥95% closed | Implementation-heavy; needs to verify which dependencies (oracledb local install per B-328 doc) are met |
| **E: Markdown-refactor D.2 sidecars** | Author 10 per-file `<file>_INDEX.md` sidecars per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.4 | ~1-2 hours | Cheapest unblocked markdown-refactor work; tangible deliverable | Doesn't advance pipeline; only marginal CCL benefit until Phase E tooling lands |
| **F: Markdown-refactor Phase E tooling** | Author `tools/regenerate_md_indexes.py` + Tier 0/1 tests + pre-commit hook + Pattern F extension per §7.2 | ~5-7 hours | Closes the markdown-discipline mechanical-enforcement loop | Larger scope; not strictly blocking pipeline pivot |

### §4.2 Recommendation framework (per NORTH_STAR pillar scoring)

Pipeline lead decides per these dimensions:

| Dimension | Weight | A: Phase 0 cleanup | B: Phase 1 R-N | C: Phase 2 pilot | D: B-N bundle | E: D.2 sidecars | F: Phase E tooling |
|---|---|---|---|---|---|---|---|
| **Forward project progress** | HIGH | Medium | High | Highest (validates everything) | Medium-High | Low | Low |
| **Operator-execution readiness** | HIGH | Medium | Medium | OPERATOR-blocked | Medium-High | N/A | N/A |
| **Claude-doable in-session** | MEDIUM | Yes (spec work) | Yes | NO | Yes (some items) | Yes | Yes |
| **Closure-density** (B-Ns per cycle) | MEDIUM | 1-2 per cycle | Variable | 0 (run test) | 4 in bundle | 0 (just authoring) | 1 (B-275-class) |
| **Risk of meta-cascade recurrence** | HIGH (manage) | LOW | LOW | LOW | LOW | LOW (productive) | LOW (productive) |

**Default recommendation (if pipeline lead requests RECOMMEND)**:

Sequencing: **A (Phase 0 cleanup) → D (B-N bundle subset) → E (D.2 sidecars opportunistically) → C (Phase 2 pilot) when operator-ready**. Defer B and F until phase-boundary explicit (B requires checking phase status; F is markdown-substantive work that competes with pipeline-substantive work).

Rationale per NORTH_STAR:
- **Operator-execution readiness pillar** dominates: Phase 0 cleanup unblocks all downstream phases; partial closure is leaving operational hooks dangling
- **Compounding leverage**: closing Phase 0 to 100% means Phase 1 R-N items have clear dependency-met checkboxes; closing Phase 1 means Phase 2 pilot can fire when operator-available
- **Risk-of-recurrence**: deferring meta-discipline work (E + F) until pipeline-substantive work demands it prevents drifting back into meta-cascade

### §4.3 Sequencing decision template (pipeline-lead fills in)

```
PIVOT DECISION (pipeline lead fills this in BEFORE Phase 2 execution):

Primary path chosen: [A / B / C / D / E / F / custom]
Secondary path (if any): [...]
Deferred items: [...]
Estimated cycles for primary: [X cycles wall-clock; Y session-hours active work]
First concrete deliverable: [name + acceptance criteria]
Operator-blocked items routed to: [user execution / scheduled / B-N closure target]
```

---

## §5. Phase 2 — Execution (depends on §4 decision)

Detail authored AFTER pipeline-lead provides §4.3 decision. Sub-tasks decomposed via `udm-planning` skill at execution time.

Per §2.5 minimum-viable-set principle: skills auto-promoted as scope requires (e.g., `udm-execution-classifier` if Phase 2 introduces new tools; `udm-decision-recorder` if D-N candidates surface; `udm-test-author` for any new code).

---

## §6. Decision capture (D-N candidates)

If pipeline lead's §4.3 sequencing decision is policy-shaping (e.g., establishes a forward convention "Phase 0 must be 100% closed before Phase 1 R-N continuation"), invoke `udm-decision-recorder` skill to capture as D-N at next round close-out.

Current session has NOT introduced new D-Ns (no policy-shaping outputs yet). Threshold for D-N capture: when sequencing decision is explicitly cited as binding for future planning sessions or sub-agent coordination.

---

## §7. Risks + deferred items

### §7.1 Reviewer-deferred follow-up items (5 total; 4 absorbed inline at §3.3; 1 deferred; no B-N needed — all dispositioned in-session below)

| Candidate | Disposition |
|---|---|
| Cross-ref SKILL.md ↔ hook check | ✅ ABSORBED INLINE §3.3 #1+#2 |
| Step 3 scope-keyword fallback row | ✅ ABSORBED INLINE §3.3 #3 |
| Step 5 "NOT a file" rationale | ✅ ABSORBED INLINE §3.3 #4 |
| Tier 0 test for code-fence false-pass edge case | 🟡 DEFERRED — extremely-unlikely scenario per reviewer; track as low-WSJF for opportunistic closure |
| Tier 0 test for UnicodeDecodeError path | 🟡 DEFERRED — implicitly tested via fall-through; track as low-WSJF for opportunistic closure |

### §7.2 Risk register additions

Per reviewer `adf74ca386f192d64`:
- **R-NEW (low-severity; LowxLow=1)**: Legacy plan docs (e.g., `MARKDOWN_REFACTOR_PLAN.md`) staged without §0 provenance will trigger BLOCK on amendment commits. Mitigation: BLOCK message directs producer to backfill §0; friction is intentional (enforces discipline retroactively). Recommend tracking as accepted residual risk in `RISKS.md` if R-N capture deemed warranted.

### §7.3 Markdown-refactor calendar dependencies

- **B-272 D.1 archive cascade**: defer until ~2026-06-08 (earliest qualifying entry per 30-day retention policy)
- **Phase F conditional split decision**: skip-vs-invoke gate at Day 90 post-sign-off = ~2026-08-13

---

## §8. Acceptance criteria

This planning session is considered complete when:
- ✅ Phase 0 infrastructure landed (commit pending; this commit lands skill + hook + plan deliverable)
- ✅ Plan deliverable authored with §0 provenance (this file)
- ⏳ Pipeline lead provides §4.3 sequencing decision (NEXT user action)
- ⏳ Phase 2 execution begins per chosen path

---

## §9. Cross-references

- `MARKDOWN_REFACTOR_PLAN.md` — markdown-refactor canonical plan (residual work tracked in §3-§5)
- `02_PHASES.md` — UDM pipeline phase status (Phase 0 / Phase 1 / Phase 2 / etc.)
- `CODE_BUILD_STATUS.md` — current build state per code artifact
- `PLANNING_DISCIPLINE.md` §2 — skill activation matrix used at session start
- `B-275` (CLOSED this commit) — `udm-context-loader` skill authoring
- `B-272` (calendar-deferred) — markdown-refactor D.1 archive cascade
- `B185 / B186 / B188 / B189 / B190` — Phase 0 partial-closure remaining items (potential Phase 2 D scope)
- `B-328` — Windows dev-env pytest skew (impacts local development setup)
- `B-331` — Pitfall #9.k line-anchor multi-site detection sub-step (opened this session; defer-eligible)
- Commit `d5af93a` — v1.2.0 mechanical enforcement gap closed (recent precedent for "documented-but-not-mechanically-enforced" pattern this plan's Phase 0 §3.2 closes for planning provenance)

---

## §10. Sign-off

**Authored by**: parent agent (orchestrator role)
**Independent review**: Agent `adf74ca386f192d64` (32nd cumulative; 5-gate validation ✅ SOUND-with-improvements; all actionable improvements absorbed inline)
**Awaiting**: pipeline-lead sequencing decision per §4.3 template before Phase 2 execution

🟢 **Plan Phase 0 LOCKED 2026-05-17** (infrastructure complete; awaiting pivot direction)
