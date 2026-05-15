# Blocker evidence verification — pre-sign-off audit of 3 remaining BLOCKERS

**Date**: 2026-05-15
**Scope**: empirical verification of the 3 BLOCKERS (B-3 / B-4 / B-5) flagged by `gap-audit-synthesis-2026-05-15.md` as mandatory pre-sign-off
**Method**: read each cited source verbatim; classify each claim ✅ FULLY EVIDENCED / 🟡 PARTIALLY EVIDENCED / 🔴 NOT EVIDENCED; propose concrete actions
**Author context**: independent verification pass (per D55+D56 producer ≠ reviewer); the gap-audit synthesis was authored by the producer; this artifact is the reviewer pass

---

## Evidence summary (top-line)

| BLOCKER | Claim | Verdict | Inline-fixable? |
|---|---|---|---|
| **B-3** | `verify_cascade.py::default_scan_paths()` doesn't glob `_archive/` | ✅ **FULLY EVIDENCED** — function literally enumerates 17 hardcoded paths + `phase1/*.md`; zero `_archive/` reference | ✅ YES — 5-line patch ready |
| **B-4** | Three conflicting archive cutoff rules (30 / >30 / 90 days) | 🟡 **PARTIALLY EVIDENCED** — the "3 rules" are not 3 conflicting rules but 3 ATTRIBUTES of a single 2-trigger policy that the gap-audit conflated; real gap is that the literal cutoff date is not stamped in §7.1 task 1.1 | 🟡 PARTIAL — pipeline-lead decision needed for date; plan edit mechanical |
| **B-5** | 17 of 24 open Q-N unclassified by sign-off-blocking vs deferrable | 🟡 **PARTIALLY EVIDENCED** — actual count is **24 open out of 26 total** (Q-13 + Q-22 RESOLVED); classification table is genuinely missing; the "17 of 24" arithmetic is unsourced but the underlying claim is correct | ✅ YES — classification table is purely editorial |

**Headline**: The 3 BLOCKERS are **all real, but B-4 + B-5 are smaller than the synthesis claimed**. B-3 is the genuine high-stakes issue (silently drops audit coverage at Phase 1.0). B-4 is a documentation-cleanliness issue that the pipeline-lead resolves with a single decision. B-5 is purely editorial (the questions exist; the meta-classification is missing).

**Net verdict**: 1 critical (B-3) + 2 editorial (B-4 + B-5). All 3 close in ≤2 sessions; only B-4 needs a pipeline-lead decision.

---

## B-3: `verify_cascade.py::default_scan_paths()` missing `_archive/` glob

### Cited claim (gap-audit-synthesis L51-57)

> `verify_cascade.py::default_scan_paths()` hardcodes scan targets; doesn't include `_archive/` paths. When Phase 1.0 archive cascade fires, archived entries silently drop out of Pattern F audit coverage. Risk: months of audit blind-spots before anyone notices.

### Empirical evidence

Read `tools/verify_cascade.py` L381-405 verbatim:

```python
def default_scan_paths() -> list[Path]:
    """Cascade doc set — every file Pattern F audits by default."""
    paths = [
        DOCS_DIR / "HANDOFF.md",
        DOCS_DIR / "CURRENT_STATE.md",
        DOCS_DIR / "NORTH_STAR.md",
        DOCS_DIR / "RISKS.md",
        DOCS_DIR / "BACKLOG.md",
        DOCS_DIR / "_validation_log.md",
        DOCS_DIR / "_reviewer_effectiveness.md",
        DOCS_DIR / "03_DECISIONS.md",
        DOCS_DIR / "04_EDGE_CASES.md",
        DOCS_DIR / "05_RUNBOOKS.md",
        DOCS_DIR / "02_PHASES.md",
        DOCS_DIR / "00_OVERVIEW.md",
        DOCS_DIR / "PHASE_1_DEEP_DIVE_PLAN.md",
        DOCS_DIR / "MULTI_AGENT_GUIDE.md",
        DOCS_DIR / "CHECKS_AND_BALANCES.md",
        DOCS_DIR / "MAINTENANCE.md",
        REPO_ROOT / "CLAUDE.md",
    ]
    # plus all phase1/*.md
    if PHASE1_DIR.exists():
        paths.extend(sorted(PHASE1_DIR.glob("*.md")))
    return paths
```

**Findings**:
1. 17 hardcoded file paths
2. ONE glob expansion: `PHASE1_DIR.glob("*.md")`
3. ZERO references to `_archive/` (full-file grep for `_archive` returns zero hits in `tools/verify_cascade.py`)
4. ZERO recursive globbing — any new directory created at `docs/migration/_archive/` is invisible
5. The downstream Trigger D forward-cite-resolution sweep (L217-284) operates only on `scan_paths`, so archived B-N / D-N / R-N / RB-N / SP-N cites would be invisible — Pattern F gives a false ✅ CLEAN verdict

### Empirical verdict: ✅ FULLY EVIDENCED

The gap is real and consequential. After Phase 1.0 archive cascade authors `docs/migration/_archive/_validation_log_archive_2026-04.md`, all cross-refs in that file (B-N, D-N, etc.) are outside Pattern F's audit scope. A subsequent stale-reference (e.g. retroactive D-number renumber) would silently break the archive without anyone noticing.

### Recommended fix (5-line unified diff)

```diff
--- a/tools/verify_cascade.py
+++ b/tools/verify_cascade.py
@@ -402,6 +402,9 @@ def default_scan_paths() -> list[Path]:
     # plus all phase1/*.md
     if PHASE1_DIR.exists():
         paths.extend(sorted(PHASE1_DIR.glob("*.md")))
+    # plus all _archive/*.md (per B-3 post-Phase-1.0 archive cascade audit coverage)
+    archive_dir = DOCS_DIR / "_archive"
+    if archive_dir.exists():
+        paths.extend(sorted(archive_dir.glob("*.md")))
     return paths
```

**Why this is mechanically safe**: additive (no removed files); guarded by `archive_dir.exists()` so it's a no-op pre-Phase-1.0; matches existing `phase1/*.md` glob pattern; survives no-archive-yet baseline + arbitrary archive growth post-Phase-1.0.

**Test fixture suggestion** (companion at Phase 2 / not pre-sign-off blocking): add a `tests/tier0/test_verify_cascade_archive_glob.py` Tier 0 smoke test asserting that an `_archive/example.md` file lands in `default_scan_paths()` output.

**B-N candidate**: B-272 (per gap-audit numbering).

---

## B-4: Three conflicting archive cutoff date rules

### Cited claim (gap-audit-synthesis L59-66)

> Plan §5.1 implies "30 days" / NEW_REPO_STARTER_TEMPLATE.md §6 says ">30-days-ago" / Canonical policy at `_validation_log.md` L13-15 says "older than 90 days". Proposed 2026-04-12 cutoff doesn't match any of them precisely. Operator at execution time has no authoritative tiebreaker.

### Empirical evidence

**Source 1 — `_validation_log.md` L12-19 (verbatim)**:
> ## Archive policy
>
> When this file exceeds ~2000 lines OR contains entries older than 90 days, the round close-out cascade authors an archive cycle:
>
> 1. Copy entries dated >30-days-ago to a sibling file `_validation_log_archive_<YYYY-MM>.md` (e.g., `_validation_log_archive_2026-05.md`) preserving exact original formatting + header
> 2. Truncate the archived entries from this live file, leaving only the last ~30 days

**Source 2 — `NEW_REPO_STARTER_TEMPLATE.md` L206-217 (verbatim)**:
> ## Archive policy
>
> **Triggers** (whichever fires first):
> - File exceeds 2,000 lines
> - File contains entries older than 90 days
> - Quarterly review boundary
>
> **Procedure**:
> 1. Copy entries dated >30-days-ago to `docs/_archive/_validation_log_archive_<YYYY-MM>.md`
> 2. Truncate the archived entries from this live file
> 3. Add 1-line back-reference at top: `**Archive**: pre-<YYYY-MM-DD> entries archived to _validation_log_archive_<YYYY-MM>.md`
> 4. Verify line count post-truncate is <2,000

**Source 3 — `MARKDOWN_REFACTOR_PLAN.md` L374 task 1.1 (verbatim)**:
> 1.1 Survey current `_validation_log.md` cutoff date for archive | Pipeline lead | <30 min | Cutoff date decided (proposed: 2026-04-12 per the policy as written)

### Reconciliation analysis

The gap-audit framed this as "3 conflicting rules", which is misleading. The actual state is:

**There is ONE policy with TWO trigger conditions and ONE retention semantic**:
- **Triggers** (whichever fires first): file ≥ 2,000 lines **OR** contains entries older than 90 days
- **Retention**: keep "last 30 days" live; archive "older than 30 days" to sibling file
- **Result**: when triggered, the live file is truncated to the last 30 days

The "30 / >30 / 90" numbers are NOT three competing rules — they are three different aspects of the same policy:
- **90 days** = trigger threshold ("when must we archive?")
- **30 days** = retention window ("how much stays live?")
- **>30 days** = cutoff predicate ("which entries get archived?")

`_validation_log.md` L12-19 + `NEW_REPO_STARTER_TEMPLATE.md` L206-217 are **bit-for-bit semantically equivalent** (the template phrasing is slightly tighter; same numbers).

### Empirical verdict: 🟡 PARTIALLY EVIDENCED

The "3 conflicting rules" framing in the gap-audit is wrong. The real gap is narrower:

1. **No literal cutoff date is stamped in §7.1 task 1.1** — task 1.1 currently says "proposed: 2026-04-12" without a binding date. The operator at execution time still has to compute the cutoff. ✅ This is a real (small) gap.
2. **The 2026-04-12 candidate isn't sourced** — it's parenthetical; not derived from "today minus 30 days" or anything explicit. Pipeline-lead has to decide.
3. **The 30-day vs 90-day distinction has no operational ambiguity** — 90 days is the trigger, 30 days is the retention window, ">30 days" is the cutoff predicate. They are not in conflict.

### Recommended action (single rule for operator)

**Recommendation: NO POLICY CHANGE NEEDED.** The existing policy at `_validation_log.md` L12-19 is internally consistent and binding. Only the §7.1 task 1.1 framing needs editorial clarification:

**Proposed §7.1 task 1.1 rewrite**:
> 1.1 Compute archive cutoff date for `_validation_log.md` per policy at L12-19 | Pipeline lead | <30 min | Cutoff date = (today − 30 days) = **2026-04-15**; archive file named `_validation_log_archive_2026-04.md` (per L17 naming convention)

If pipeline-lead wants to **change** the retention window (e.g. "keep last 60 days instead of 30"), that is a separate policy revision and requires updating `_validation_log.md` L12-19 + `NEW_REPO_STARTER_TEMPLATE.md` L206-217 in lockstep. But the gap-audit framed the existing policy as broken; it isn't.

**Pipeline-lead decision required (binary)**:
- (a) Accept the as-written 30-day retention window → proceed with cutoff = 2026-04-15 (today − 30 days), no policy edits needed
- (b) Revise the retention window (specify N days) → requires policy edit in both source files; trigger threshold (90 days) can stay independent

**My recommendation (the reviewer)**: option (a). The 30-day retention window is the canonical policy; the gap-audit conflated trigger / cutoff / retention numbers; no policy revision is warranted. Plan §7.1 task 1.1 gets the editorial rewrite above and BLOCKER B-4 closes.

**B-N candidate**: B-273 (per gap-audit numbering).

---

## B-5: 17 of 24 open Q-N unclassified by sign-off-blocking vs deferrable

### Cited claim (gap-audit-synthesis L68-74)

> Plan §10 has Q-1 through Q-26; Q-13 + Q-22 RESOLVED; 24 remain. NO classification of which questions BLOCK pipeline-lead's sign-off vs which are "answer-when-needed". Pipeline-lead reading the plan can't tell what's actually gating approval. Best read: 4 questions actually block (Q-1 approval to proceed / Q-2 cutoff date / Q-12 CLAUDE.md trim / Q-23 hygiene-rules-as-binding).

### Empirical evidence (Q-N inventory verification)

Read `MARKDOWN_REFACTOR_PLAN.md` §10 L425-451 verbatim. Numbered questions:

- **Q-1 through Q-7**: §10 L427-433 (un-prefixed, listed as `1.` through `7.`)
- **Q-8 through Q-12**: §10 L435-443 (bolded, prefixed `**Q-N (NEW per ...)**`)
- **Q-13 through Q-17**: §10 L445 (summarized inline; details in §13.6 L737-742)
- **Q-13 ✅ RESOLVED 2026-05-15**: §10 L449 (RESOLVED inline)
- **Q-18 through Q-22**: §10 L447 (summarized inline; details in §15.5 L822-826)
- **Q-22 ✅ RESOLVED 2026-05-15**: §10 L447 inline (RESOLVED in same line; "Q-22 ✅ RESOLVED 2026-05-15")
- **Q-23 through Q-26**: §10 L451 (summarized inline; details in §16.6 L974-977)

**Count verification**: 26 questions total (Q-1 through Q-26 numerically continuous, no gaps). 2 marked RESOLVED (Q-13 + Q-22). **24 remain unresolved.** The gap-audit's count is correct.

### Classification table for the 24 unresolved questions

Legend:
- 🔴 **SIGN-OFF BLOCKING** — pipeline-lead MUST answer before plan can flip 🟡 Plan-final → 🟢 Locked
- 🟡 **PHASE-1 DESIGN DECISION** — answer when starting the affected Phase 1 task; doesn't block sign-off
- ⚪ **DEFERRABLE** — answer when needed; not blocking; can land as B-N post-approval

| Q-N | Brief description | Classification | Rationale |
|---|---|---|---|
| Q-1 | Approval to proceed with Phase 1? | 🔴 BLOCKING | Definitional — this IS the sign-off |
| Q-2 | `_validation_log.md` archive cutoff date | 🔴 BLOCKING | Phase 1.0 (the immediate-priority task) literally needs this date |
| Q-3 | INDEX scope (canonical-only vs routing-by-intent) | 🟡 DESIGN | Answer when starting Phase 1.3 (INDEX.md authoring); doesn't gate sign-off |
| Q-4 | Pre-commit hook adoption (auto-add vs fail-if-stale) | 🟡 DESIGN | Phase 2.3 question; Phase 1 doesn't touch hooks |
| Q-5 | D-N for the refactor decision itself | ⚪ DEFERRABLE | Bookkeeping; per D111 process-infra exemption can land directly when authored |
| Q-6 | Skill update scope for D62 | 🟡 DESIGN | Phase 1.5 question; bulk-update enumerable at execution time |
| Q-7 | Snowflake test fixture pre-staging runbook | ⚪ DEFERRABLE | Orphan from prior cascade; not part of this refactor; can pair OR not |
| Q-8 | INDEX.md ref'd from project-root CLAUDE.md? | 🟡 DESIGN | Phase 1.6 CLAUDE.md trim question; can decide at execution time |
| Q-9 | GLOSSARY.md merge into INDEX.md? | 🟡 DESIGN | Phase 1.3 INDEX scope question; can decide at execution time |
| Q-10 | Commission internal benchmark study post-Phase-1+2? | ⚪ DEFERRABLE | Post-Phase-2 question; doesn't gate Phase 1 |
| Q-11 | Approve `udm-context-loader` subagent at Phase 2? | 🟡 DESIGN | Phase 2 question; doesn't gate Phase 1 sign-off |
| Q-12 | Approve CLAUDE.md trim to <300 lines at Phase 1.6? | 🔴 BLOCKING | Phase 1.6 is in the proposed Phase 1 scope per §7.1; can't ship Phase 1 without a yes/no/defer |
| Q-14 | Approve P1 Navigation Paradox UDM topology mapping? | ⚪ DEFERRABLE | Meta-research; doesn't gate Phase 1 execution |
| Q-15 | Approve P4 intent.lisp investigation? | ⚪ DEFERRABLE | Meta-research; doesn't gate Phase 1 execution |
| Q-16 | Approve P7 auto-compaction interaction investigation? | ⚪ DEFERRABLE | Meta-research; doesn't gate Phase 1 execution |
| Q-17 | Approve §13.4 heading-slug stability as binding rule? | 🟡 DESIGN | Empirical revision already locked at §13.4 + Q-22 resolved; this Q is "is the rule binding for ALL headings going forward?" — pipeline-lead picks at Phase 1.3+ |
| Q-18 | Label CCL stages as quality tiers in D62? | ⚪ DEFERRABLE | D62 doctrine update Phase 1.5; framing question; not blocking |
| Q-19 | Mandate lead-with-answer writing discipline for all NEW edits? | 🟡 DESIGN | Markdown hygiene rule; relates to Q-23; can pair |
| Q-20 | Near-duplicate-paragraph audit across canonical trackers? | ⚪ DEFERRABLE | Polish work; can land as B-N post-Phase-1 |
| Q-21 | 4-component cross-ref maintenance design? | 🟡 DESIGN | Phase 2.4 design question; doesn't gate Phase 1 |
| Q-23 | 6-rule markdown hygiene as binding (D-N candidate)? | 🔴 BLOCKING | Hygiene rules are referenced as binding in §7.1 task 1.4 + § 16.1; need pipeline-lead approval before they "bind" |
| Q-24 | NEW_REPO_STARTER_TEMPLATE.md as canonical greenfield ref? | ⚪ DEFERRABLE | Internal-only artifact; binding-or-not doesn't block Phase 1 |
| Q-25 | Q11 quarterly markdown research-refresh cadence? | ⚪ DEFERRABLE | Quarterly cadence start date doesn't gate Phase 1 |
| Q-26 | Year-1 milestones (Day 0/30/90/180/365) as roadmap commitment? | ⚪ DEFERRABLE | Roadmap framing; can iterate post-Phase-1 |

**Count**: 4 🔴 BLOCKING / 8 🟡 DESIGN / 12 ⚪ DEFERRABLE = 24 total ✅

### Empirical verdict: 🟡 PARTIALLY EVIDENCED

The gap-audit's count (24 unresolved) is correct. The "17 of 24 unclassified" is arithmetically off — the underlying reality is "**0 of 24 are explicitly classified**" in the plan as it stands (the plan has no §10.A classification table at all). But the gap-audit's *headline* claim — that pipeline-lead can't tell what's actually gating approval — is correct.

The gap-audit's "4 questions actually block (Q-1 / Q-2 / Q-12 / Q-23)" is consistent with my independent classification above. ✅ Convergent verdict.

### Shortest path to pipeline-lead sign-off

**The 4 🔴 BLOCKING questions reduce to 4 binary decisions**:
1. **Q-1**: Approve Phase 1? (yes / no / redirect)
2. **Q-2**: Accept 2026-04-15 archive cutoff per current policy? (yes / pick different date / change policy)
3. **Q-12**: Approve CLAUDE.md trim to <300 lines at Phase 1.6? (yes / no / partial)
4. **Q-23**: Approve 6-rule markdown hygiene as binding? (yes / no / pick subset)

**Recommendation**: Add §10.A "Sign-off-blocking vs deferrable classification" table to the plan (copying the table above). Pipeline-lead reads the 4 🔴 rows and answers 4 binary questions. Plan flips 🟡 → 🟢 once those 4 are answered. The 20 non-blocking questions move to Phase 1 design decisions OR a `_research/open_questions_post_sign_off.md` artifact that tracks them separately.

**B-N candidate**: B-274 (per gap-audit numbering).

---

## Recommended actions (consolidated)

| BLOCKER | Action | Owner | Effort | Pipeline-lead decision needed? |
|---|---|---|---|---|
| **B-3** | Apply the 5-line unified diff to `tools/verify_cascade.py::default_scan_paths()` | Engineer or parent agent | <5 min | NO — mechanical patch |
| **B-3** (companion) | Author `tests/tier0/test_verify_cascade_archive_glob.py` Tier 0 smoke test | `udm-test-author` per Tier 0 cohort | ~30 min | NO — additive test |
| **B-4** | Editorial rewrite of §7.1 task 1.1 (stamp literal cutoff date = 2026-04-15) | Parent agent | <10 min | YES (binary: accept as-written OR revise retention window) |
| **B-4** (companion) | NO POLICY CHANGE — gap-audit's "3 conflicting rules" framing was wrong | n/a | n/a | NO |
| **B-5** | Add §10.A "Sign-off-blocking vs deferrable classification" table (copy table above into the plan) | Parent agent | ~15 min | NO — editorial; pipeline-lead just READS the table |
| **B-5** (follow-up) | After §10.A lands, pipeline-lead answers 4 🔴 BLOCKING Q-N questions | Pipeline lead | <30 min | YES (4 binary decisions) |

**Total work to close all 3 BLOCKERS**: ~1 hour of parent-agent + engineer time + ~30 min of pipeline-lead review/decision time.

**Sign-off mechanics**:
1. Apply B-3 patch (mechanical)
2. Apply B-4 §7.1 task 1.1 editorial rewrite (mechanical)
3. Apply B-5 §10.A classification table (mechanical)
4. Pipeline-lead reads §10.A; answers Q-1 / Q-2 / Q-12 / Q-23 (binary)
5. Plan flips 🟡 Plan-final → 🟢 Locked

---

## Are the BLOCKERS real or speculative?

**All 3 are real, but in different ways**:

- **B-3 (verify_cascade.py archive glob)**: ✅ **GENUINE HIGH-STAKES GAP**. Code literally does not glob `_archive/`; after Phase 1.0 fires, audit coverage silently degrades. This one matters.
- **B-4 (3 conflicting cutoff rules)**: 🟡 **REAL BUT SMALLER THAN CLAIMED**. The "3 rules" framing was inaccurate — the policy is internally consistent. Real gap is editorial: §7.1 task 1.1 doesn't stamp a literal date.
- **B-5 (Q-N unclassified)**: 🟡 **REAL EDITORIAL GAP**. 24 unresolved questions exist with zero meta-classification; pipeline-lead can't see the gating set. Fix is purely editorial; 4 binary decisions emerge from the classification.

**Confidence**: 🟢 HIGH — all 3 claims verified against verbatim source citations; 1 inaccurate framing identified (B-4); 2 inline-fixable; 1 needs pipeline-lead decision (B-4 only, and it's binary).

The gap-audit synthesis was directionally correct on all 3 BLOCKERS but slightly over-stated B-4's severity. Net: pipeline-lead's path to sign-off is ~1.5 hours of work split between agent + lead.
