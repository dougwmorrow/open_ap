# udm-session-compactor Phase 2.1 Hardening — Implementation Plan

**Date**: 2026-05-19
**Closes**: B-558 (NEW; HIGH WSJF 3.5; will be opened at first build commit per Phase 2.1 cohort consolidation)
**Target deliverable**: 5 HIGH-severity gap closures from UDM_SESSION_COMPACTOR_REVIEW_2026-05-19.md
**Authored by**: parent agent (this chat session); claude-opus-4-7; context pressure high; CCL completed
**Empirical anchor**: pipeline-lead direction "review the plan and see if it aligns with previous research... If more research is needed we should do that. After research, we should have a plan. After the plan we should gap check the plan for missing events. If the plan looks good, let's begin the build."

---

## §0. Planning session provenance

| Skill | Invoked at | Scope | Rationale |
|---|---|---|---|
| `udm-planning-session-startup` | 2026-05-19 (this commit) | PS-3 TOOL (primary) + PS-5 SKILL + PS-1 ARCH (secondary) | Hardening cohort touches multiple substrate layers |
| `claude-code-guide` (research) | 2026-05-19 (sub-agent `a7778dca8c0fdb8b8`) | PS-3 narrow research | Concurrent-session detection patterns |
| `udm-gap-check` (Phase 1.5; pending) | TBD (sub-agent TBD) | PS-3 + PS-5 mandatory | Independent verification of this plan |
| `udm-design-reviewer` (Phase 3; pending) | TBD post-implementation | PS-1 ARCH mandatory substrate-edit | Procedural review pre-commit |
| `udm-test-author` (Phase 2; pending) | TBD during implementation | PS-3 conditional | Tier 0 test sketches for new check + hook refactor |
| `udm-checks-and-balances` (Phase 3; pending) | TBD at attestation | PS-1+PS-3 mandatory | 5-gate validation |
| `udm-post-edit-verification` (Phase 4; pending) | TBD at commit | hard rule 14 substrate-edit | TEST + GAP + REVIEW cascade |
| `udm-progress-logger` (throughout) | per milestone | per hard rule 9 | Tracker updates |
| `udm-execution-classifier` (conditional) | TBD if new CLI surfaces | PS-3 conditional | check_snapshot_claims is operator-invoked indirectly via pre-commit hook |

**Sub-agents spawned + skill inheritance**:

| Sub-agent | Spawned at | Skills inherited |
|---|---|---|
| `claude-code-guide` agent (`a7778dca8c0fdb8b8`) | 2026-05-19 (Step 3 research) | claude-code-guide; cited hard rule 13 inheritance in prompt |
| `udm-gap-check` reviewer (TBD) | 2026-05-19 (Step 5 gap-check) | inherited per hard rule 13 |
| `udm-design-reviewer` / PRE-COMMIT (TBD) | TBD (Phase 3 attestation) | inherited per hard rule 13 |

---

## §1. Background + B-N closure target

**B-558** (TBD-open; HIGH WSJF 3.5): "udm-session-compactor Phase 2.1 hardening cohort — close 5 HIGH-severity gaps from UDM_SESSION_COMPACTOR_REVIEW_2026-05-19.md (Gap 1.2 + 3.1 + 5.3 + 2.3 + 2.4) via single substrate-edit cohort". Closure target: this plan + immediate Phase 4 commit.

**Why bundle**: 5 HIGH gaps share substrate (`.claude/hooks/` + `.claude/skills/udm-session-compactor/` + `tools/pre_commit_checks.py` + `tools/check_commit_msg.py` + new `tools/check_snapshot_claims.py`) and a single coherent design (snapshot-validation discipline matching D-N / RB-N / SP-N substrate). Splitting would require multiple PRE-COMMIT reviewer cycles + tracker arithmetic across cohorts.

**Effort**: ~1.5 days estimated.

---

## §2. Research findings (anchor)

### §2.1 Prior research (canonical anchor)

Per `docs/migration/_research/llm-handoffs-traceability-hallucination-2026-05-18.md` (12 primary sources). Key findings applicable to this cohort:
- **Finding 3.1** (arXiv 2511.00776; 60-paper meta-analysis 2025): file-path + numeric-claim confabulation is LEAST-MITIGATED LLM hallucination sub-type → motivates R-1 + R-3 claim-validation checks
- **Finding 3.2** (AWS Well-Architected idempotency token pattern): verify prior-result-valid before treating canonical → motivates R-6 snapshot-validity check before suppression
- **Finding 3.3** (AWS Operational Excellence "quantifiable criteria" + MARCH multi-agent verification): producer ≠ reviewer for canonical artifacts → motivates R-2 udm-gap-check post-snapshot
- **Finding 2.1** (Apache Iceberg + Google SRE "selective reprocessing scoped by audit trail"): not directly applicable here but informs the broader discipline

### §2.2 NEW research (this planning session)

Per claude-code-guide sub-agent `a7778dca8c0fdb8b8` 2026-05-19:

**Canonical finding**: PostToolUse hook payload includes `transcript_path` field directly — fully qualified absolute path to the originating session's transcript JSONL. The current `_find_transcript_jsonl(session_id)` glob-search is REDUNDANT.

**Implication for R-5**: simpler fix than originally proposed. Instead of "cwd-constrained glob", use `payload["transcript_path"]` directly. Eliminates concurrent-session-collision risk surface entirely.

**Secondary findings**:
- Session IDs are UUIDs; guaranteed unique across concurrent sessions on same machine
- `CLAUDE_PROJECT_DIR` env var available (project root)
- `cwd` field in payload available for validation
- No race condition — harness passes correct session_id to each hook

### §2.3 Alignment with existing plan

| Recommendation | Alignment | Refinement |
|---|---|---|
| **R-1** snapshot claims drift detection | ✅ STRONG | Implementation: new `tools/check_snapshot_claims.py` orchestrator + Phase 1 check |
| **R-2** udm-gap-check post-snapshot | ✅ STRONG | Implementation: SKILL.md mandate + Tier 0 assertion check for required structure |
| **R-3** Extend B-449 to snapshot scope | ✅ STRONG | Implementation: extend `PytestCountDisambiguationCheck` OR add new `SnapshotPytestClaimCheck` subclass |
| **R-5** Session detection | 🔄 REFINED via NEW research | Use `payload["transcript_path"]` directly; remove glob search; far simpler than original "cwd-constrained" proposal |
| **R-6** Snapshot validity check before suppression | ✅ STRONG | Implementation: extend `_has_recent_snapshot()` to parse + validate file structure |

---

## §3. Implementation plan

### §3.1 Component A — `tools/check_snapshot_claims.py` (NEW Phase 1 check; R-1)

**Purpose**: Validate snapshot file claims against actual repo state at commit time.

**Implementation**:
- Pattern: matches existing `check_wc_line_count_claims` (B-481) + `check_file_path_existence` (B-495) Phase 1 check patterns
- Function: `check_snapshot_claims(staged_files: list[str]) -> CheckResult`
- Logic:
  - Filter staged files to `docs/migration/_session_snapshots/*.md`
  - For each snapshot file:
    - Parse YAML frontmatter for `commit_hash` field
    - Verify commit_hash exists in `git log --format=%H` output (via subprocess)
    - Parse §2 body for "B-N closed: K" claims
    - Cross-check K against `grep -c "⚫ CLOSED" docs/migration/BACKLOG.md`
    - Parse §1 body for pytest count claims (delegate to B-449 regex `_PYTEST_FULL_TRIPLET_RE`)
- Severity: WARN (not BLOCK; D74 exit code 1; per FP-policy precedent of B-481 + B-495)
- Findings cap 10
- New entry appended to `CHECKS` registry at next available slot (currently 10 entries; this becomes the next; absolute position determined at build time per Pitfall #9.k drift-prevention)
- Test coverage: `tests/tier0/test_pre_commit_checks_b558_snapshot_claims.py` (~8 assertions)
- **Step 10 discipline (per Pitfall #9.n)**: at closure commit, MUST update (a) CLAUDE.md Structure row for `tools/pre_commit_checks.py` adding `check_snapshot_claims` to surface list + (b) GLOSSARY.md public-surface entries for `check_snapshot_claims` + regex/helper constants + (c) update CHECKS registry count narrative in CLAUDE.md L99 row + GLOSSARY L765 row
- **udm-execution-classifier**: NOT a new standalone CLI; integrated into existing `pre_commit_checks.py` orchestrator; classification = "manual" trigger × "recurring" frequency per existing pre-commit orchestrator pattern; no new ONE_OFF_SCRIPTS.md entry needed

### §3.2 Component B — SKILL.md update (R-2 + R-6)

**Purpose**: Mandate post-authoring verification + extend `_has_recent_snapshot()` to parse-validate.

**SKILL.md changes** (`.claude/skills/udm-session-compactor/SKILL.md`):
- NEW section "Post-authoring verification discipline (per B-558 closure 2026-05-19; Phase 2.1 hardening cohort)":
  - Mandate `udm-gap-check` invocation immediately after snapshot authoring
  - Mandate cite reviewer agent-ID in snapshot §0 verification footer (or new §6 footer)
  - 6-category audit: G1 N/A no leading-badge / G2 claims-vs-actual / G3 cross-refs resolve / G4 discipline applied / G5 N/A / G6 surfaced patterns
- Update "Output contract" section: snapshot MUST include a §6 verification footer once gap-check completes

**Hook changes** (`.claude/hooks/session-compactor-warning.py`):
- `_has_recent_snapshot()` extended:
  - Currently: checks file mtime > session_start
  - NEW: ALSO opens file, checks for `## §1 ` through `## §5 ` headers + minimum 2KB file size
  - If snapshot exists but malformed, treat as "no snapshot" → emit warning
- Tier 0: 3 NEW assertions covering structural validation cases

### §3.3 Component C — snapshot pytest-claim verification (R-3)

**Purpose**: Apply existing pytest-count-disambiguation discipline to snapshot content.

**Implementation choices** (revised per Gate 2 gap-check `abbbbd0ae702860da` G3-1):
- **Option A** (ORIGINAL; REJECTED): Extend `PytestCountDisambiguationCheck` (B-449; `_PYTEST_COUNT_RE` at L684) to ALSO scan staged snapshot files. Architectural mismatch: ABC `CommitMsgCheck.scan(commit_msg, ctx)` signature is commit-msg-scoped; cross-scope extension stretches the abstraction.
- **Option B** (CHOSEN): NEW Phase 1 quality check in `tools/pre_commit_checks.py` — `check_snapshot_pytest_claims(staged_files)` — using the existing `_PYTEST_COUNT_RE` regex via import (or duplicate canonical pattern). Native fit to `check_*(staged_files)` signature; matches existing B-481 / B-495 Phase 1 check patterns; no ABC contract stretching.

**Implementation** (Option B):
- NEW function `check_snapshot_pytest_claims(staged_files)` in `tools/pre_commit_checks.py`
- Filter staged files to `docs/migration/_session_snapshots/*.md`
- For each snapshot, apply `_PYTEST_COUNT_RE` (imported from `tools/check_commit_msg.py` OR duplicated canonical pattern with cross-ref comment)
- Apply `is_empirical_anchor_context()` Layer 2 suppression (from `tools/anchor_context.py`) for historical citations
- Severity: WARN (consistent with B-449 + B-481 + B-495 precedent)
- Append to CHECKS registry at next available slot
- Test coverage: 4 NEW Tier 0 assertions at `tests/tier0/test_pre_commit_checks_b558_snapshot_pytest.py`

### §3.4 Component D — hook refactor for R-5

**Purpose**: Use `payload["transcript_path"]` directly per research finding §2.2.

**Implementation** (`.claude/hooks/session-compactor-warning.py`):
- DELETE `_find_transcript_jsonl()` function (obsolete)
- In `main()`: read `payload.get("transcript_path", "")` directly; convert to `Path`
- Fallback: if `transcript_path` missing or invalid, log warning to telemetry + skip (silent skip per defensive pattern)
- Net LOC delta: -25 LOC removed + ~5 LOC added = -20 LOC simplification
- Tier 0: extend test_session_compactor_warning_hook.py with 2 NEW assertions for transcript_path direct usage + missing-field fallback

---

## §4. Effort + sub-agent plan

| Phase | Effort | Sub-agents | Output |
|---|---|---|---|
| Phase 1 — Research + Plan | DONE (~30 min) | claude-code-guide `a7778dca8c0fdb8b8` | this plan + alignment review |
| Phase 1.5 — Plan gap-check | PENDING (~15-20 min) | `udm-gap-check` reviewer | Verdict; 0+ findings to remediate |
| Phase 2 — Build (Components A + B + C + D) | PENDING (~3-4 hours) | parent agent + `udm-test-author` skill inline | New check + SKILL.md updates + hook refactor + Tier 0 tests |
| Phase 3 — Multi-reviewer attestation | PENDING (~30-45 min) | `udm-design-reviewer` + PRE-COMMIT independent reviewer + final `udm-gap-check` | Verdicts; 🟢 closure |
| Phase 4 — Commit + push | PENDING (~15 min) | parent agent + PRE-COMMIT reviewer | B-558 lands; trackers updated |

**Total estimated**: ~1.5 days from this commit through B-558 closure.

---

## §5. Risks + open questions

### Risks (carried into Phase 3 review)

**R-A: Component C (B-449 extension) could increase false-positive rate**
- Existing B-449 was calibrated for commit-msg context; snapshot context has different pytest-count patterns
- Mitigation: WARN-only severity (per existing B-449 convention); `is_empirical_anchor_context()` Layer 2 suppression carries over

**R-B: Component A regex might be brittle**
- YAML frontmatter parsing without pyyaml dep — use simple `re` patterns + might miss edge cases
- Mitigation: WARN-only; defensive regex; fail-silent on parse errors

**R-C: Hook refactor could break if transcript_path field absent**
- Older Claude Code versions might not send this field
- Mitigation: graceful fallback (silent skip) on missing field; document minimum Claude Code version

### Open questions (Phase 1.5 gap-check should surface or resolve)

1. **Q1**: Should `check_snapshot_claims` be BLOCK or WARN? Currently proposed WARN per B-481/B-495 precedent. Pipeline-lead may want BLOCK for HIGH-severity drift.
2. **Q2**: Should snapshot §0 frontmatter REQUIRE `commit_hash` field or accept inline body citation? Affects regex complexity.
3. **Q3**: When `udm-gap-check` post-snapshot finds 🟡 IN-FLIGHT-DRIFT, what's the inline-fix path vs spawn-2nd-pass? Currently snapshot is immutable post-commit; corrections via amendment file.

---

## §6. Approval gates

### Gate 1 (NOW): Plan content approval
- User reviews this plan + approves OR redirects
- Phase 1.5 gap-check does NOT start until user approves

### Gate 2 (Phase 1.5): Plan gap-check verdict
- Independent `udm-gap-check` reviewer
- 6-category audit on this plan deliverable
- 🟢 CLEAN → proceed to Phase 2 build
- 🟡 IN-FLIGHT-DRIFT → inline-fix + re-verify

### Gate 3 (Phase 3): Multi-reviewer attestation on built code
- udm-design-reviewer on substrate edits
- PRE-COMMIT independent reviewer per hard rule 14
- 🟢 verdict required before Phase 4 commit

### Gate 4 (Phase 4): Final commit + push
- All trackers updated + B-558 ⚫ CLOSED render
- Commit message includes full cascade-evidence

---

## §7. Cross-references

- `docs/migration/UDM_SESSION_COMPACTOR_REVIEW_2026-05-19.md` — source of 29 gaps; this plan closes the 5 HIGH-severity ones (Gap 1.2 + 3.1 + 5.3 + 2.3 + 2.4)
- `docs/migration/_research/llm-handoffs-traceability-hallucination-2026-05-18.md` — prior research artifact (12 primary sources)
- `.claude/skills/udm-session-compactor/SKILL.md` — to be amended (R-2 + R-6 components)
- `.claude/hooks/session-compactor-warning.py` — to be amended (R-5 + R-6 components)
- `tools/check_commit_msg.py` `PytestCountDisambiguationCheck` (B-449) — to be extended (R-3 component)
- `tools/pre_commit_checks.py` CHECKS registry — to be extended (R-1 component; 11th check)
- `docs/migration/BACKLOG.md` — B-558 to be opened at first build commit
- `docs/migration/03_DECISIONS.md` — D55+D56 producer ≠ reviewer; D74 exit codes; D75 dry-run; D76 audit-row
- `tools/anchor_context.py` — `is_empirical_anchor_context()` helper for Layer 2 false-positive suppression (extending to snapshot scope via Component C)

---

## §8. Status

**This plan**: ✅ Gate 1 + Gate 2 COMPLETE + remediated.

**Gate 2 verdict**: `udm-gap-check` reviewer `abbbbd0ae702860da` returned 🔴 BLOCK + 7 🟡 findings. Inline-fixed at this commit:
- B-547 → **B-558** (next available slot; B-547 collision with existing "RB-16 rewrite" B-N)
- §3.3 architecture choice REVISED — Option A rejected (ABC contract mismatch); Option B chosen (new Phase 1 check in `tools/pre_commit_checks.py`)
- §3.3 regex attribution corrected (`_PYTEST_COUNT_RE` from B-449, NOT `_PYTEST_FULL_TRIPLET_RE` from B-464)
- §3.1 hardcoded "11th check" → "next available slot at build time" (per Pitfall #9.k drift-prevention)
- §3.1 Step 10 discipline citation added (CLAUDE.md Structure + GLOSSARY + CLI registry sync)
- §3.1 udm-execution-classifier decision documented (no new ONE_OFF_SCRIPTS entry)

**Gate 1 user-decision Q1 (BLOCK vs WARN for snapshot claims)** — surface to pipeline-lead:
- **Recommended**: WARN severity per established B-449 + B-481 + B-495 precedent (all Phase 1 quality checks at WARN; pipeline-lead can escalate to BLOCK reservatively per WSJF MEDIUM)
- **Alternative**: BLOCK per the HIGH-severity nature of snapshot drift (Gap 1.2 + 3.1 + 5.3 are HIGH)

Assuming WARN unless redirected — consistent with precedent + reviewer's recommended-action.

**NEW B-N to be opened at build commit**: **B-559** (MEDIUM WSJF ~2.0) — CCPA/PII compliance scrubbing for snapshots per review R-4 (Phase 2.2 deferred work; tracked to prevent orphan-forward-prevention drift per B-451 pattern).

**Next action**: proceed to Phase 2 build per user-direction "If the plan looks good, let's begin the build."
