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

### 2026-05-18 — FP-6 — `check_file_path_existence` self-firing on historical path citations (B-496 → bundled-closure with B-491 via B-488 shared helper)

- **trigger_pattern**: `_BACKTICK_PATH_RE = re.compile(r"`([^`\s\*\?<>\{\}]+/[^`\s\*\?<>\{\}]+)`")` post-filtered via `_is_credible_path_candidate` (whitelisted-prefix + whitelisted-extension OR trailing slash)
- **actual_semantic**: regex matched 37 path tokens inside `_validation_log.md` historical entries (e.g., `tools/query_parquet.py` / `tests/smoke/test_pii_tokenizer.py` / `data_load/idempotency_ledger.py` / `phase1/09_*.md`) — paths existed/were planned at original authoring but were renamed/moved/never-built in subsequent refactors. Append-only narrative discipline preserves citations verbatim; check WARN-fired on these historical references during normal commit cycles. Self-firing on the discipline's own closure commit (10th check addresses LLM file-path-confabulation hallucination class).
- **empirical_anchor_commit**: `2ac353b` (B-495 closure commit; check self-fired against staged BACKLOG.md + _validation_log.md)
- **detected_by**: cross-cohort gap-check reviewer `a9330411976057db7` G4-finding 2026-05-18 post-B-495 closure
- **remediation_status**: ABSORBED via B-491+B-496 bundled closure at commit `a7813df` — shared `is_empirical_anchor_context()` helper extracted to NEW `tools/anchor_context.py` module (per B-488 cross-module reuse pattern) + applied to `check_file_path_existence` line-by-line iteration loop
- **forward_prevention_B_N**: `B-496` (closed 2026-05-18 bundled with B-491) → ABSORBS into shared-helper consolidation
- **class**: self-reference meta-pattern (Pitfall #9-class; FP-6 = recurring with FP-2 + FP-3 + FP-5)

### 2026-05-18 — FP-5 — `check_wc_line_count_claims` self-firing on historical wc -l citations (B-491 → bundled-closure with B-496 via B-488 shared helper)

- **trigger_pattern**: `_WC_LINE_COUNT_CLAIM_RE = re.compile(r"\`(?P<filename>[^\`\s]+)\`[^(]*\([^)]*?(?P<count>\d+)\s+lines?\s+per\s+actual\s+\`?wc\s+-l\`?", re.IGNORECASE)` against staged markdown content + canonical filename map resolution
- **actual_semantic**: regex matched 3 wc -l citations in BACKLOG.md L408 + 2 corresponding `_validation_log.md` historical entries — citations were TRUE at B-307 authoring era (~2026-05-16) but BECAME stale post-multiple-refactors (.githooks/pre-commit 177 → 68; .githooks/commit-msg 117 → 41). Per append-only narrative discipline: historical citations preserved verbatim; check WARN-fired on these historical references during the very B-481 closure cohort that added the check.
- **empirical_anchor_commit**: `c781c9b` (B-481 closure commit; check self-fired against staged BACKLOG.md)
- **detected_by**: PRE-COMMIT reviewer `a4310f90ef3b89357` 2026-05-18 self-firing finding at B-481 closure cohort
- **remediation_status**: ABSORBED via B-491+B-496 bundled closure at commit `a7813df` — shared `is_empirical_anchor_context()` helper extracted to NEW `tools/anchor_context.py` module + applied to `check_wc_line_count_claims` line-aware iteration (compute line index from match.start() then 5-line lookback for anchor markers)
- **forward_prevention_B_N**: `B-491` (closed 2026-05-18 bundled with B-496) → ABSORBS into shared-helper consolidation
- **class**: self-reference meta-pattern (Pitfall #9-class; FP-5 = recurring with FP-2 + FP-3)

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

**As of 2026-05-18 close-out (round 6 in progress; UPDATED at B-491+B-496 bundled closure cohort `a7813df`)**:

| Class | Event count | Forward-prevention status |
|---|---|---|
| self-reference meta-pattern | **4** (FP-2 + FP-3 + FP-5 + FP-6) | ✅ CLOSED via B-488 shared helper + ✅ CLOSED via B-491+B-496 bundled extension (shared helper extracted to `tools/anchor_context.py` for cross-module reuse) |
| reviewer-methodology blind-spot | 1 (FP-4) | ✅ CLOSED via B-490 Step 6 |
| Pitfall #9.h staleness | 1 (FP-1) | ⚫ CLOSED via B-481 mechanical detection (check_wc_line_count_claims 9th Phase 1 check) + FP-5 deferred-then-absorbed via B-491 shared-helper suppression |

**Pattern observations (updated 2026-05-18 at a7813df)**:
- self-reference meta-pattern reached **4-event evidence** across 2 layers (check_commit_msg.py B-488 + pre_commit_checks.py B-491+B-496 bundled) → forward-prevention SHARED-HELPER extraction completed; ✅ canonical resolution per HANDOFF §8 2-event-then-bundle convention
- reviewer-methodology blind-spot at 1-event → forward-prevention authored anyway at producer judgment (B-490 closure); validation pending more events
- Pitfall #9.h at 1-event → mechanical detection added (B-481) + when self-fired on own closure → bundled into B-491+B-496 shared-helper consolidation. Full lifecycle now exemplified: empirical anchor → mechanical detection → self-firing on closure → context-aware suppression via shared helper.

**Meta-observation**: The self-reference meta-pattern class has now demonstrated the CANONICAL FULL LIFECYCLE for heuristic-check forward-prevention: (1) 1st-event surfaces → deferred per 2-event convention; (2) 2nd-event surfaces → bundled closure via shared-helper extraction; (3) shared helper enables cross-module reuse without per-check duplication; (4) accumulation tracker (this log) catalyzes the architectural recognition. Pattern reusable for future check-class self-firing.

## Next aggregation trigger

Round 6 close-out cascade should re-walk this log + classify any NEW events between 2026-05-18 and round-close. New 2+ event classes → open new forward-prevention B-Ns.
