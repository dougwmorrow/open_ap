# Producer gap audit — MARKDOWN_REFACTOR_PLAN.md Phase 1 execution readiness

**Date**: 2026-05-15
**Auditor perspective**: Independent fresh-read engineer about to execute Phase 1 tomorrow morning. Did NOT participate in the 4 plan-revision sessions; picking the plan up cold. Frame: "what would block, slow, or confuse me at 9am tomorrow when the operator says 'execute Phase 1'?"
**Scope**: Execution readiness only — not strategy critique, not research validity critique. Plan-final → 🟢 Locked transition gate readiness.
**Backing artifacts read**: `MARKDOWN_REFACTOR_PLAN.md` (997 lines, 4th revision), `NEW_REPO_STARTER_TEMPLATE.md` (334 lines), `tools/measure_ccl_overhead.py` (218 lines), `tools/test_github_slug.py` (89 lines), `_research/em-dash-slug-test-2026-05-15.md` (149 lines), `_research/ccl-baseline-2026-05-15.md` (116 lines), `_research/agent-discoverability-2026-05-15.md` (header + §A; full file context). Also spot-checked: `tools/verify_cascade.py` L380-405 (default scan paths), `_validation_log.md` L1-30 (existing archive policy), `.claude/skills/` directory listing.

---

## Summary (lead-with-answer per §15.2 Pattern b)

**The plan is research-rich and strategy-locked but execution-poor.** Tomorrow morning, an operator handed this plan would face 3 blocking unknowns within the first 30 minutes: (1) the Phase 1.0 archive procedure has a different cutoff rule in the plan (§5.1 "30 days") vs. the canonical policy in `_validation_log.md` L13-23 ("entries older than 90 days") — which wins? (2) `tools/verify_cascade.py` L389 hardcodes `_validation_log.md` as a scan target but does NOT know about an `_archive/` subdirectory — Phase 1.0 archive would silently break Pattern F audit coverage of historical entries; the plan claims this is mitigated (§2.2 non-goal #2 + §8 R-MR2) but the mitigation reasoning depends on "no source file moves" which is false the moment the archive lands. (3) Phase 1.B (INDEX.md) needs to cite the archive path (`_validation_log_archive_2026-04.md` per §13.1), creating a hard Phase 1.0 → Phase 1.B ordering dependency that the §5.1 task list does NOT make explicit. There are 17 open questions Q-8 through Q-26 unresolved with no classification of which block sign-off vs. which are "answer-when-needed."

Confidence: 🟢 High — every finding is grounded in a specific line of the plan or a verified file-system state.

---

## Per-dimension findings

### Dimension 1 — Vague task definitions

**🔴 BLOCKER F-1: Archive cutoff date conflict — plan says "30 days" / canonical policy says "90 days" / proposed cutoff is 2026-04-12 ≈ 33 days ago.**

The plan §5.1 Phase 1.0 PROMOTED bullet says "trimming it by 73% (7,519 → 2,000 lines)." Phase 1.1 (§7.1) says "Cutoff date decided (proposed: 2026-04-12 per the policy as written)." But `_validation_log.md` L13-15 actually says: "When this file exceeds ~2000 lines OR contains entries older than 90 days." Today is 2026-05-15; 90 days ago is 2026-02-14; 30 days ago is 2026-04-15; the proposed 2026-04-12 cutoff is ~33 days ago — closer to "30 days" but NOT matching either L13 ("90 days") OR §5.1 implied trim target ("under 30 days" per NEW_REPO_STARTER_TEMPLATE.md §6 archive policy that hard-codes "entries dated >30-days-ago"). Operator at 9am tomorrow has THREE conflicting cutoff rules and no authoritative tiebreaker. The plan does not say "pipeline-lead picks at execution" with a default; it says "per the policy as written" — but the policy as written says 90 days, which would archive ~7,500 of 7,519 lines (over-trim).

**Recommendation**: Plan §7.1 row 1.1 must state the LITERAL cutoff date + which policy line wins + why. The operator should be able to copy-paste a date string, not re-derive it.

**🔴 BLOCKER F-2: "Entries dated within the cutoff window but referencing earlier events" is unspecified.**

A validation log entry dated 2026-05-12 may reference a Round 4 close-out event from 2026-04-28. Archive procedure must clarify: does the entry's OWN date determine archive eligibility, or does the EVENT date it references? Neither plan nor `_validation_log.md` L13-23 says. Practical impact: if event-date wins, the operator must read every entry's body to decide archive — slow and error-prone. If entry-date wins, recent retrospective entries about old events stay in the live file forever — defeats the trim purpose.

**Recommendation**: Add 1-line rule to §7.1 Phase 1.2: "entry-date wins (no body inspection)."

**🟡 FRICTION F-3: "Truncate the archived entries from this live file" is not a defined Git/shell operation.**

The procedure in `_validation_log.md` L17 says "Truncate the archived entries from this live file" but does not specify: (a) `sed -i` boundary line numbers? (b) interactive editor cut? (c) script (does not exist)? An operator at 9am will choose an approach; without spec, it could be `sed -i '20,5519d'` (data loss risk if off-by-one) or manual cut-paste in VS Code (slow, error-prone for 5,519 lines).

**Recommendation**: Spec the truncation operation literally — either commit a one-off `tools/archive_validation_log.py` (sed-equivalent + line-range validation) OR specify a defensive `git apply` patch workflow.

### Dimension 2 — Missing acceptance criteria

**🔴 BLOCKER F-4: "How do you know Phase 1.0 is DONE?" has no concrete test.**

§9 lists 6 metrics but they are for Phase 1+2 COMBINED, not Phase 1.0 specifically. The only Phase-1.0-specific success signal is the empirical claim "recovers ~62% of CCL Stage 1+2 token cost" (§5.1 + §15.4). But the plan does not say "run `tools/measure_ccl_overhead.py --baseline-out _research/ccl-post-phase-1.0-<date>.md` and assert s1+s2 tokens drop from 362,154 to <250,000." Without an explicit assertion command, "done" is opinion-driven.

**Recommendation**: Phase 1.0 acceptance test = (a) `_validation_log.md` line count <2000, (b) `_validation_log_archive_2026-04.md` exists + is append-only-marked, (c) re-run of `measure_ccl_overhead.py` shows s1+s2 token delta ≥-130K (≈ -36% of 362K). Make this a 3-line shell snippet in §7.1.

**🟡 FRICTION F-5: Sign-off mechanism (§12) is a single empty table row with no instructions.**

The table has columns "Role / Name / Date / Decision" but nothing tells the pipeline-lead HOW to sign off. Edit the row? File a separate validation-log entry? Open a B-N? Comment in a PR? The plan does not say. (Compare to the project's existing D-number lock procedure in `03_DECISIONS.md` which has a literal "Status: 🟡 Open → 🟢 Locked" flow with a known second-pass reviewer.)

**Recommendation**: Add one paragraph to §12: "Sign-off mechanism: pipeline-lead edits §12 row in-place AND appends a `_validation_log.md` entry per the existing 5-gate discipline AND opens a B-N for Phase 1 execution tracking. All three actions are atomic in a single commit titled `chore: MARKDOWN_REFACTOR_PLAN sign-off + Phase 1 start`."

### Dimension 3 — Tooling referenced but not yet built

**🔴 BLOCKER F-6: `tools/regenerate_md_indexes.py` is a Phase 2 deliverable but the plan claims Phase 1 INDEX.md is "best-effort" hand-authored (§7.1 row 1.3, §8 R-MR1) — so Phase 1 INDEX.md HAS NO REGENERATOR. After hand-authoring, the first edit to ANY source file silently invalidates the INDEX line ranges. The mitigation "agents tolerate 5-line drift via Grep fallback" (§8 R-MR1) is unverifiable until §6 Gate 1 sub-check is implemented — which requires INDEX existence — which requires Phase 1.3 — chicken-and-egg.**

Specifically tools referenced in plan but NOT existing:
- `tools/regenerate_md_indexes.py` (§5.1 Phase 2.F) — does not exist
- `tools/rewrite_cross_refs.py` (§13.3 + §15.2 Pattern d) — does not exist
- `tools/check_markdown_hygiene.py` (§16.1 Tier 2) — does not exist
- `tools/verify_md_index_consistency.py` (§6 Gate 1) — does not exist

Skills referenced but NOT existing:
- `udm-find-canonical` skill (§5.1 Phase 1.E) — confirmed absent from `.claude/skills/` directory listing
- `udm-context-loader` subagent (§4.5 Option T5 + §5.1 Phase 2.I) — confirmed absent
- `udm-cross-ref-checker` SKILL (§15.2 Pattern d) — confirmed absent

The plan classifies these as Phase 1 (find-canonical) vs Phase 2 (others) but does not say which Phase 1 tasks block on which Phase 1 sub-builds. Specifically: Phase 1.E `udm-find-canonical` skill authoring needs INDEX.md to exist (Phase 1.B/C) AND needs the canonical-home routing table populated (Phase 1.B+C output). So the sub-ordering inside Phase 1 is at minimum 1.0 → 1.B → 1.C → 1.E → 1.D.

**Recommendation**: Add §7.1.5 "Phase 1 internal task DAG" with a 6-node dependency graph + explicit "Phase 1.E cannot start until 1.B+1.C land."

### Dimension 4 — Implicit dependencies

**🔴 BLOCKER F-7: `tools/verify_cascade.py` L389 hardcodes `DOCS_DIR / "_validation_log.md"` as the SOLE validation-log scan path. After Phase 1.0 archive, ~7,000 lines of history move to `_archive/_validation_log_archive_2026-04.md` which is NOT in the scan list. Pattern F audit will silently lose historical coverage.**

Verified by reading `tools/verify_cascade.py` L380-405 (`default_scan_paths()` function). The list is hardcoded; no glob over `_archive/`. The plan §2.2 non-goal #2 says "Not breaking the Pattern F audit script — its regex patterns are calibrated against current paths" and §8 R-MR2 says "Phase 1 doesn't move any source file; only adds new INDEX files. Pattern F regex unaffected" — both statements are FALSE for Phase 1.0 archive because the archive DOES move source content (just from inside the file rather than the file itself). The mitigation reasoning silently assumes "intra-file move = no path change = no audit impact" which only holds if the audit reads the archive file too.

**Recommendation**: Phase 1.0 MUST include an additive 1-line edit to `tools/verify_cascade.py::default_scan_paths()` adding `*sorted((DOCS_DIR / "_archive").glob("_validation_log_archive_*.md"))` BEFORE the archive commit lands. This is a 5-minute change but it's a hard prerequisite for not silently losing audit coverage.

**🟡 FRICTION F-8: `udm-round-closeout` skill is referenced as the Phase 2.G alternative regeneration cadence (§5.1 + §16.1 Tier 3) but the skill's `SKILL.md` does not yet contain an INDEX-regeneration step.**

Without scoping that skill update as a Phase 2 deliverable, the "Phase 2.G alternative" is non-executable.

**Recommendation**: Add to §7.2 "Phase 2.G prerequisite: `udm-round-closeout/SKILL.md` Stage 2.6 INDEX regeneration step authored."

### Dimension 5 — Order-of-operations ambiguity

**🟡 FRICTION F-9: Phase 1 task ordering is non-strict in §5.1 (just bulleted A-E) but several tasks have hard dependencies.**

The §7.1 work-breakdown table is rows 1.1-1.6 implying sequential but the §5.1 Phase 1 bullets 0/A/B/C/D/E are not ordered. Specifically:
- 1.B (INDEX.md authoring) needs to KNOW the archive path `_validation_log_archive_2026-04.md` exists → 1.0 must land first
- 1.C (per-file INDEX sidecars) need NOT block on 1.B (they are independent) → 1.B + 1.C parallel-safe
- 1.D (D62 doctrine update) needs INDEX.md existence (to add Stage 0 reference) → must follow 1.B
- 1.E (udm-find-canonical skill) needs routing-table data which is the OUTPUT of 1.B+1.C consolidation → must follow both

So strict order: **1.0 → (1.B ‖ 1.C) → 1.D + 1.E (parallel) → 1.6 review**.

**🟡 FRICTION F-10: Catch-22 risk on INDEX.md vs CLAUDE.md trim.**

If Q-12 (CLAUDE.md trim to <300 lines) executes BEFORE INDEX.md authoring (Phase 1.B), the trimmed CLAUDE.md will reference an INDEX.md that doesn't exist yet — agents reading the trimmed CLAUDE.md mid-Phase-1 will encounter broken pointers. Conversely if INDEX.md authoring blocks on CLAUDE.md being trimmed (because INDEX should reflect the trimmed structure), there is a cycle. Plan does not resolve this.

**Recommendation**: Author INDEX.md FIRST with stub pointer to "CLAUDE.md (current; trim pending Q-12)"; author CLAUDE.md trim SECOND with explicit link to INDEX.md; document this 2-phase sequence in §7.1.

### Dimension 6 — Concurrency

**🟡 FRICTION F-11: No lock or coordination protocol for concurrent Phase 1 executors.**

The plan implicitly assumes a single operator. If 2 people run Phase 1.0 archive simultaneously (e.g., one parent-agent and one human operator both reading the §12 sign-off as "approved"), both could attempt the truncate operation. Without sp_getapplock-equivalent, the second `git push` would overwrite the first. Risk is real because the plan does not explicitly assign Phase 1 ownership.

**Recommendation**: §7.1 row 1.2 should specify "owner = pipeline-lead OR pipeline-lead-delegated-agent (one only); coordination via branch lock — work on `markdown-refactor/phase-1` branch only, no parallel branches."

### Dimension 7 — Rollback

**🟡 FRICTION F-12: "Reversible via git revert" (§2.1 goal #4 + §9 metric #6) is claimed but not verified for Phase 1.0 archive specifically.**

`git revert` of the archive commit recovers the truncated lines in `_validation_log.md` AND deletes the archive file. But if anyone has cited the archive file in a downstream artifact (e.g., a future B-N references "see `_validation_log_archive_2026-04.md` entry from 2026-04-08 for context") then the revert silently breaks the citation. Plan does not say "no inbound cites to archive files until Phase 2 closes" which would be the safe rule.

**🟡 FRICTION F-13: Data-loss scenarios git doesn't recover.**

If the operator runs the archive truncate operation and then runs `git add . && git commit -am "archive"` WITHOUT staging the new archive file first (typo / forgot `git add _archive/`), the truncated entries are LOST — git tracks the truncation but never sees the archive file. Reflog would catch it within 30 days but plan does not flag this risk.

**Recommendation**: §7.1 row 1.2 acceptance test should include `git status` snapshot showing BOTH the modified live file AND the new archive file staged together; verify line-count delta matches.

### Dimension 8 — 5-line quick-start

**🟡 FRICTION F-14: Plan does not contain a literal 5-command quick-start.**

For an operator handed this plan at 9am tomorrow, the literal sequence should be (proposed):

```bash
# 1. Snapshot pre-archive state
python tools/measure_ccl_overhead.py --baseline-out docs/migration/_research/ccl-pre-archive-2026-05-16.json
# 2. Update verify_cascade.py to include _archive/ subdirectory (F-7 fix)
$EDITOR tools/verify_cascade.py  # add archive glob to default_scan_paths()
# 3. Execute archive (script TBD per F-3)
python tools/archive_validation_log.py --cutoff 2026-04-12 --out docs/migration/_archive/
# 4. Verify post-archive state
python tools/measure_ccl_overhead.py --baseline-out docs/migration/_research/ccl-post-archive-2026-05-16.json
# 5. Commit atomically
git add docs/migration/_validation_log.md docs/migration/_archive/ tools/verify_cascade.py && git commit -m "..."
```

The plan does not have this. Without it, every operator re-derives the sequence and gets it slightly wrong.

**Recommendation**: Add §7.1.A "Operator quick-start (Phase 1.0)" with the literal 5-command sequence + expected `ls`/`wc -l` verification outputs after each step.

### Dimension 9 — Sign-off mechanism

Covered in F-5 above. **🟡 FRICTION**.

### Dimension 10 — Open questions Q-1 through Q-26

**🔴 BLOCKER F-15: 17 of 24 open questions are unresolved and the plan does not classify which BLOCK sign-off vs. which are "answer-when-needed."**

Q-13 and Q-22 are marked ✅ RESOLVED in §10. That leaves Q-1 through Q-12 (mostly approval gates), Q-14 through Q-21 (cross-domain synthesis derivatives), Q-23 through Q-26 (long-term governance). Reading them, my best classification:

- **Sign-off blockers (must answer before approve)**: Q-1 (approval to proceed), Q-2 (archive cutoff date — re F-1), Q-12 (CLAUDE.md trim Y/N — re F-10), Q-17 (heading-slug policy binding — affects all future heading authoring including any Phase 1 INDEX.md headings), Q-22 [already resolved]
- **Phase 1 execution decisions (defer to "before that task starts")**: Q-3 (INDEX scope), Q-5 (D-N for refactor), Q-6 (which skills get D62 update)
- **Phase 2+ decisions (defer)**: Q-4 (pre-commit hook), Q-11 (udm-context-loader), Q-21 (4-component cross-ref design)
- **Quality-bar approvals (defer to round close-out)**: Q-18, Q-19, Q-20, Q-23, Q-24, Q-25, Q-26
- **Optional / nice-to-have**: Q-7 (snowflake fixture), Q-8 (CLAUDE.md→INDEX reference), Q-9 (GLOSSARY merge), Q-10 (benchmark study), Q-14 (Navigation Paradox topology), Q-15 (intent.lisp), Q-16 (auto-compaction)

**Recommendation**: Add §10.A "Q-classification" with the above tiering. Pipeline-lead must answer 4 blocking questions (Q-1, Q-2, Q-12, Q-17) AT minimum before Plan-final → 🟢 Locked.

---

## Top-5 most-impactful gaps to close before pipeline-lead approves Plan-final → 🟢 Locked

| Rank | Finding | Severity | 5-minute fix? |
|---|---|---|---|
| 1 | **F-7** `tools/verify_cascade.py` does not scan `_archive/` — silent audit-coverage loss after Phase 1.0 | 🔴 BLOCKER | Yes (5-line edit to `default_scan_paths()`) |
| 2 | **F-1** Archive cutoff conflict (30d / 90d / 2026-04-12) — three rules, no winner | 🔴 BLOCKER | Yes (1-line authoritative statement in §7.1) |
| 3 | **F-15** 17 open questions unclassified — pipeline-lead can't tell what blocks sign-off | 🔴 BLOCKER | Yes (add §10.A Q-classification — 30 min) |
| 4 | **F-4** Phase 1.0 has no explicit "done" test | 🔴 BLOCKER | Yes (3-line shell snippet in §7.1) |
| 5 | **F-6 + F-14** No quick-start command sequence + 4 referenced tools don't exist | 🔴 BLOCKER | Partial — quick-start is 30 min; tools are deferrable IF the quick-start says "skip step 3 until `archive_validation_log.py` lands" |

---

## What would make this plan execution-ready (5-point view)

1. **One operator script per Phase 1 step** — at minimum `tools/archive_validation_log.py` for 1.0 + a stub `tools/regenerate_md_indexes.py --once` for 1.B+1.C so the indexes are reproducible, not hand-authored.
2. **Explicit task DAG inside Phase 1** — replace §7.1's flat table with a 6-node dependency graph showing what blocks what (1.0 → 1.B/1.C parallel → 1.D/1.E parallel → 1.6 review).
3. **Pre-flight checklist on §12 sign-off** — pipeline-lead must answer Q-1/Q-2/Q-12/Q-17 (the 4 blocking questions per F-15) + edit §12 row + open a B-N for tracking, all in one commit.
4. **Pattern F coverage extension as a Phase 1.0 PRECONDITION not a Phase 2.4 deliverable** — `tools/verify_cascade.py::default_scan_paths()` must learn about `_archive/` BEFORE the first archive lands; this is a 5-minute change that prevents a silent multi-month audit-coverage gap.
5. **Acceptance test per task expressed as a shell command, not prose** — every §7.1 row gets a "Validation: `<command>` returns <expected>" suffix. Today the prose is "✅ CLEAN verdict required for merge" which is opinion-driven; tomorrow it should be "`pytest tests/tier0/test_phase_1_archive.py` exits 0."

If items 1-5 land in a single follow-up commit, the plan moves from "research-rich, execution-poor" to "🟢 Lockable + an operator can execute Phase 1.0 in <2 hours from a cold read."
