# False-Positive Event Log

Append-only audit trail for false-positive events surfaced by heuristic checks (CommitMsgCheck subclasses; cross-cohort reviewer grep methodology; etc.) per **B-489 closure 2026-05-18** (Layer 3 of the false-positive prevention architecture).

## Purpose

Parallels `docs/migration/_validation_log.md` (per-cohort validation events) + `docs/migration/_reviewer_effectiveness.md` (per-reviewer-event metadata at round level). This tracker accumulates **per-false-positive-event metadata** so recurring patterns can be classified at round-aggregate cadence → opens forward-prevention B-Ns when ≥2-event evidence accumulates.

## When to log an event

Append a new row when any of the following happens:

1. **Heuristic check WARN-fires on its own closure commit**: e.g., B-458 ClosureAnnotationConsistencyCheck firing on quoted historical `B-414 CLOSED` reference (B-480 event class). Self-reference meta-pattern.
2. **Reviewer methodology blind-spot surfaced**: e.g., cross-cohort reviewer grep pattern missing a canonical format variant (B-490 event class — pattern-completeness gap).
3. **Stale narrative/threshold claim becomes false post-refactor**: e.g., CLAUDE.md "127 lines per actual wc -l" cited TRUE at authoring but BECAME false post-refactor (Pitfall #9.h class).
4. **Cumulative arithmetic propagation drift**: count updated in one location but mirror locations carry stale value (Pitfall #9.k class).

## Schema

Each event row (append at top; reverse-chronological):

```markdown
### YYYY-MM-DD — <event-id> — <check_name>

- **trigger_pattern**: <regex / heuristic / claim that fired>
- **actual_semantic**: <what the matched text actually meant; why this was false-positive>
- **empirical_anchor_commit**: `<git-hash>` (commit where false-positive was observed)
- **detected_by**: <reviewer agent ID OR producer self-catch OR cross-cohort reviewer>
- **remediation_status**: <DEFERRED | INLINE-FIXED at commit `<hash>` | TRACKED as B-NNN | ABSORBED via B-NNN>
- **forward_prevention_B_N**: `B-NNN` (B-N tracking the forward-prevention fix, if any)
- **class**: <Pitfall #9.X sub-class OR new class label>
```

## Aggregation discipline

At round close-out cascade (per `udm-round-closeout` SKILL.md):

1. Walk all events since last round close-out
2. Group by `class` field — identify recurring patterns (≥2 events in same class)
3. For each recurring class: open forward-prevention B-N if not already tracked
4. Verify each `forward_prevention_B_N` cited in this log exists in BACKLOG.md (cross-tracker drift check)

## Composition with other discipline layers

| Layer | Cadence | Tracker |
|---|---|---|
| WARN-only severity | per-fire | (no tracker; stderr only) |
| Shared `_is_empirical_anchor_context()` helper (B-488) | per-commit | (suppression via code; no event log) |
| Reviewer methodology Step 6 (B-490) | per-cohort | (verdict cites methodology; no event log) |
| **`_false_positive_log.md` accumulation (B-489)** | **per-event → round-aggregate** | **THIS file** |

## Initial event corpus (seeded 2026-05-18 at B-489 closure)

Empirical evidence base accumulated through 2026-05-18 session arc. Events sorted most-recent-first.

### 2026-05-18 — FP-4 — cross-cohort review grep methodology (B-490 closure absorbed)

- **trigger_pattern**: `grep -oE "^- \*\*B-[0-9]+\*\*" docs/migration/BACKLOG.md` — primary regex for B-N row enumeration
- **actual_semantic**: regex matches only standard format `- **B-N**` and misses older strikethrough-wrapped format `- ~~**B-N**~~` used for B-408-B-414 historical closures pre-Pitfall-#9.j-leading-badge-discipline. Reviewer reported 73 phantom-gap drift in B-393-B-486 range; broader regex confirms 0 gaps (94 unique rows present).
- **empirical_anchor_commit**: `9e8291a` (cross-cohort reviewer `aa320fb75f55a5471` reported 🔴 §4 Pitfall #9.k recurrence as FALSE POSITIVE)
- **detected_by**: producer self-catch + secondary regex verification at commit `9e8291a` remediation cycle
- **remediation_status**: ABSORBED via B-490 (Mechanism A Step 6 regex-completeness verification section added to `udm-cohort-review` SKILL.md with 5-variant canonical format-variant table)
- **forward_prevention_B_N**: `B-490` (closed 2026-05-18)
- **class**: reviewer-methodology blind-spot (new class; FP-4 = 1st-event anchor)

### 2026-05-18 — FP-3 — B-464 NarrativePytestClaimVerificationCheck self-firing (B-487 absorbed via B-488)

- **trigger_pattern**: `_PYTEST_FULL_TRIPLET_RE` matching `\b(?P<pass>\d{2,5})\s*pass[/,]\s*(?P<skip>\d{1,4})\s*skip(?:\s*[/,]\s*(?P<fail>\d{1,3})\s*fail)?` with skip-count threshold 20
- **actual_semantic**: regex matched `2664 pass / 62 skip / 0 fail` inside empirical-anchor citation prose at commit `c6ba969` body — the "62 skip" was a HISTORICAL REFERENCE citing the META-IRONY pattern from commit `1f74b72`, not a producer claim about the current commit's pytest output. WARN fired on the discipline's own closure commit (self-reference meta-pattern).
- **empirical_anchor_commit**: `c6ba969` (B-464 closure commit)
- **detected_by**: cross-cohort reviewer `a73a72b3539791788` §2 calibration-drift finding
- **remediation_status**: ABSORBED via B-488 shared `_is_empirical_anchor_context()` helper (B-487 originally tracked the issue; B-488 absorbed it into shared-helper consolidation)
- **forward_prevention_B_N**: `B-488` (closed 2026-05-18) → absorbs `B-487` (closed 2026-05-18)
- **class**: self-reference meta-pattern (Pitfall #9-class; recurring with FP-2)

### 2026-05-18 — FP-2 — B-458 ClosureAnnotationConsistencyCheck self-firing (B-480 absorbed via B-488)

- **trigger_pattern**: `_CLOSURE_CLAIM_RE` matching `\*\*B-(\d+)\s+CLOSED\*\*|\bB-(\d+)\s+(?:⚫\s*)?CLOSED\b` with BACKLOG annotation cross-check
- **actual_semantic**: regex matched `B-414 CLOSED` inside REVIEW-section quote-cite of prior reviewer's verdict at commits `133b212` + `40da316` + `9983bee` — the "B-414 CLOSED" was a HISTORICAL REFERENCE in quoted reviewer output describing the 20fe33a empirical-anchor pattern, not a producer claim about the current commit's closures. WARN fired on the discipline's own closure commit + multiple subsequent commits (self-reference meta-pattern).
- **empirical_anchor_commit**: `133b212` (B-458 closure commit; pattern recurred at `40da316`, `9983bee`)
- **detected_by**: producer self-catch at commit `133b212` post-commit; tracked + remediated incrementally
- **remediation_status**: ABSORBED via B-488 shared `_is_empirical_anchor_context()` helper (B-480 originally tracked the issue; B-488 absorbed it into shared-helper consolidation)
- **forward_prevention_B_N**: `B-488` (closed 2026-05-18) → absorbs `B-480` (closed 2026-05-18)
- **class**: self-reference meta-pattern (Pitfall #9-class; 1st-event of recurring class)

### 2026-05-18 — FP-1 — CLAUDE.md wc -l line-count claim staleness (B-481 deferred)

- **trigger_pattern**: narrative claim `"127 lines per actual wc -l after B-307 refactor"` for `.githooks/pre-commit` + `"117 lines per actual wc -l per B-307 split"` for `.githooks/commit-msg`
- **actual_semantic**: claims were TRUE at original authoring (B-307 era ~2026-05-16) but BECAME FALSE post-multiple-refactors. Actual `wc -l` at 2026-05-18 reports 68 + 41 lines respectively. Stale-by-time-passing, not detection-blind-spot.
- **empirical_anchor_commit**: detected at commit `9e8291a` cross-cohort review (reviewer `aa320fb75f55a5471` §6 finding)
- **detected_by**: cross-cohort reviewer `aa320fb75f55a5471` §6 Pitfall #9.h finding
- **remediation_status**: INLINE-FIXED at commit `9e8291a` (CLAUDE.md L98 updated to actual `wc -l` values); B-481 opened to track forward-prevention mechanism (auto-verifying wc -l claims via pre-commit check)
- **forward_prevention_B_N**: `B-481` (🟡 Open; LOW WSJF 1.0; deferred until 2nd-event evidence per scope-management)
- **class**: Pitfall #9.h L-range/wc -l line-count claim staleness

## Aggregation findings (round close-out classification)

**As of 2026-05-18 close-out (round 6 in progress)**:

| Class | Event count | Forward-prevention status |
|---|---|---|
| self-reference meta-pattern | 2 (FP-2 + FP-3) | ✅ CLOSED via B-488 shared helper |
| reviewer-methodology blind-spot | 1 (FP-4) | ✅ CLOSED via B-490 Step 6 |
| Pitfall #9.h staleness | 1 (FP-1) | 🟡 B-481 open; defer-trigger 2nd-event |

**Pattern observations**:
- self-reference meta-pattern reached 2-event evidence → forward-prevention authored (B-488); ✅ working as designed
- reviewer-methodology blind-spot at 1-event → forward-prevention authored anyway at producer judgment (B-490 closure); validation pending more events
- Pitfall #9.h at 1-event → deferred per established 2-event threshold for new mechanism authoring

## Next aggregation trigger

Round 6 close-out cascade should re-walk this log + classify any NEW events between 2026-05-18 and round-close. New 2+ event classes → open new forward-prevention B-Ns.
