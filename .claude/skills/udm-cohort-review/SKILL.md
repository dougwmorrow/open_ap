---
name: udm-cohort-review
description: Cross-cohort review discipline layer per B-483 closure 2026-05-18. Operates between per-commit reviews (udm-gap-check + udm-design-reviewer; hard rule 11 + 14) and per-round Pattern F audits (udm-cascade-auditor; D89-D91). Walks 6-scope audit across 2-N related commits in same session arc to catch failure-mode classes invisible at single-commit scope (compositional drift, test-coverage gap interactions, architectural fragmentation accumulation, cumulative arithmetic propagation, stale forward-references post-cohort, new-B-N calibration drift). Empirical anchor 2026-05-18 (1-event evidence base): user-direction "Run a gap analysis or review to see if there are any issues with the recent enhancements" surfaced 3 🔴 + 2 NEW B-Ns across ccf21a2 + 133b212 + 9983bee that 3 prior single-commit reviewers missed.
---

# UDM Cohort Review

Cross-cohort review skill that fills the gap between per-commit independent reviews (udm-gap-check + udm-design-reviewer; per-completion / per-substrate-edit cadence) and per-round Pattern F cascade audits (udm-cascade-auditor; round-close-out cadence only).

## Why this skill exists (the gap it closes)

**Empirical evidence base (1-event 2026-05-18 + 6 failure-mode classes)**: user-direction "Run a gap analysis or review to see if there are any issues with the recent enhancements" at end of B-470 + B-458 multi-commit cohort spawned a cross-cohort review subagent (`aa320fb75f55a5471`) that surfaced **3 🔴 + 2 NEW B-Ns** across 3 commits (ccf21a2 + 133b212 + 9983bee) that the 3 prior independent reviewers (PRE-COMMIT for ccf21a2 + PRE-COMMIT for 133b212 + udm-gap-check on 133b212) ALL missed. Specific findings: (1) Pitfall #9.k arithmetic-propagation drift RECURRENCE (gap-check at 9983bee fixed drift but re-introduced it by opening B-480 in same commit → invisible to single-commit scope by construction); (2) CLAUDE.md L98 line-count drift (cited `127 lines per actual wc -l` for file that wc -l reports as 68 lines post-multiple-refactors — claim was TRUE at authoring time but BECAME false across subsequent refactors; invisible to single-commit scope); (3) stale forward-reference "future check addition like B-458" after B-458 closed in same commit (cohort-2 reviewer flagged + producer deferred; cross-cohort caught the carry-over).

**Failure-mode classes ONLY visible cross-cohort** (6 categories matching the 6-scope procedure below):

1. **Compositional drift** — Check N vs N-1 interactions invisible at N's review (e.g., B-482 `_fetch_staged_content` orchestrator-bypass seed emerging as ClosureAnnotationConsistencyCheck lands)
2. **Test-coverage gap interactions** — no single test exercising both N + N-1 simultaneously; neither commit's reviewer sees gap (e.g., `inline_fix_claim × closure_annotation` interaction gap)
3. **Architectural fragmentation accumulation** — each bypass looks fine alone; pattern emerges only across cohort
4. **Cumulative arithmetic propagation drift** — rollup updated in commit N+1 but stale in commit N+2 narratives (Pitfall #9.k recurrence 9983bee → required 9e8291a)
5. **Stale forward-references post-cohort** — reference TRUE at commit N; FALSE after commit N+1 closes target (e.g., "future check like B-458" stale post-133b212)
6. **New-B-N calibration drift** — WSJF estimates calibrated against last commit, not full cohort (e.g., B-478 + B-480 partial semantic overlap noted only at cross-cohort scope)

**Distinction from existing layers**:

| Layer | Scope | Cadence |
|---|---|---|
| `udm-design-reviewer` (hard rule 14 substrate-edit clause) | **Single commit's diff** | Before each substrate-edit commit |
| `udm-gap-check` (hard rule 11) | **Single just-landed commit** + immediate trackers | After substantive build |
| **`udm-cohort-review` (this skill; hard rule 11 extension)** | **2-N related commits in same session arc** | User-invokable + auto at session-pause / before SESSION_RESUME write |
| `udm-cascade-auditor` Pattern F (D89-D91) | Round-aggregate cross-doc | **Only at round close-out** |

## When to invoke

**User-invokable trigger phrases** (case-insensitive; partial match acceptable):

- "cross-cohort review"
- "review the recent enhancements" / "review the recent work"
- "audit the cohort" / "audit the recent cohort"
- "check across commits" / "look across commits"
- "comprehensive review" / "comprehensive audit"
- "are there any issues with the recent enhancements"
- "review the last N commits"

**Auto-invocable triggers** (parent agent SHOULD invoke without user prompt):

- **Before SESSION_RESUME.md write** at session pause/close (cross-cohort review catches narrative-drift before it gets frozen in resume doc)
- **Every Nth substantive commit** (N=3-5; calibrate from empirical evidence) when a multi-commit theme has accumulated ≥3 related commits

**NOT auto-invocable triggers** (would duplicate existing layers):

- Per-commit auto-trigger — duplicates udm-gap-check
- Round-close-out trigger — duplicates udm-cascade-auditor Pattern F
- Single-commit user request ("review this commit") — use udm-design-reviewer
- Round-level user request ("close out the round") — use udm-round-closeout

## Anti-triggers (do NOT invoke even if a trigger-like phrase appears)

- User invoking on a single commit ("review commit XYZ" / "audit ccf21a2") — that's udm-gap-check or udm-design-reviewer scope
- User invoking at round close-out ("close out round 6") — that's udm-round-closeout + Pattern F
- Session start when no commits have landed since last cross-cohort review (no new scope to review)
- User asking a meta-question about review process itself ("what does cross-cohort review do?")

## The 6-scope procedure (canonical)

For each invocation: parent agent identifies the cohort scope (last N commits OR commits matching topic regex OR commits since last cross-cohort review) + spawns an INDEPENDENT reviewer agent per D55 + D56 producer ≠ reviewer discipline. The reviewer walks ALL 6 scopes.

### §1 — Compositional integrity across cohort

- Do all components introduced by the cohort (new classes / functions / config rows / etc.) coexist cleanly with components from prior commits in the cohort?
- Specific patterns to inspect:
  - **Shared infrastructure usage**: do new components consume the same orchestrator helpers, or do some bypass them?
  - **State sharing**: do new components share state (caches, contexts) cleanly, or fragment?
  - **Test isolation**: do test fixtures across commits monkey-patch shared module state in ways that could interact?

### §2 — New B-N quality assessment

- Read each new B-N opened during cohort (verify closure targets are well-defined + WSJF estimates calibrated relative to each other)
- Detect duplicative / overlapping B-N semantics across cohort (different surface names, overlapping mechanisms)
- Verify open + close round-trips on B-Ns opened-and-closed within cohort scope

### §3 — Test coverage adequacy across cohort

- Run pytest on full-suite scope (tier0+tier1+unit+property+regression typically; or tier0 alone if cohort is doc-only)
- Identify obvious test gaps: interaction tests between new components from different cohort commits
- Verify new tests are isolated, not implicitly depending on absence of state from other checks
- Encoding hazards (BOM / newline / Unicode literal) at file-read or subprocess boundaries

### §4 — Discipline-drift recurrence (Pitfall #9.* sub-classes)

- Pitfall #9.j leading-badge consistency: every closed B-N entry across cohort has `(⚫ CLOSED YYYY-MM-DD; ...)` LEADING badge + inline annotation match
- Pitfall #9.k arithmetic-propagation: counts (B-N totals / Tier 0 assertions / pytest counts) propagated across ALL canonical mirrors (BACKLOG / CURRENT_STATE / HANDOFF / _validation_log / CLAUDE.md / GLOSSARY)
- Pitfall #9.l canonical re-read: implementation-narrative match (does BACKLOG description match actual code; does GLOSSARY entry match class signature)
- Pitfall #9.m discipline-applied: new discipline introduced in cohort applied to its OWN artifacts
- Pitfall #9.n convention-registration: new public surface present in CLAUDE.md Structure + GLOSSARY tables
- Pitfall #9.o exemption-rationalization: if any cohort commit cited an exemption claim, was it independently verified (Mechanism B)

### §5 — Architectural debt assessment

- Has the abstraction surface introduced by the cohort settled, or are there pending B-Ns suggesting incompleteness?
- Composition-inflation risk: does adding more components create orchestrator complexity faster than the abstraction handles?
- Latent bugs: any "parsed but not verified" / "detected but not handled" / "tracked but not enforced" deferrals?

### §6 — Cross-doc consistency final sweep

- Walk all canonical aggregate docs (CLAUDE.md / GLOSSARY / BACKLOG / CURRENT_STATE / HANDOFF / _validation_log / CODE_BUILD_STATUS)
- Verify all counts consistent across all locations
- Identify stale forward-references that have already been resolved
- Identify line-count / line-anchor claims (`per actual wc -l N`; `L<N>`) and verify against current file state (Pitfall #9.h)

## Output contract

The reviewer agent returns a verdict using this template (≤700 words):

```
## Cross-cohort review verdict: ✅ CLEAN / 🟡 ISSUES / 🔴 BLOCKERS

### §1 — Compositional integrity: ✅/🟡/🔴
<findings>

### §2 — B-N quality: ✅/🟡/🔴
<findings>

### §3 — Test coverage: ✅/🟡/🔴
<findings>

### §4 — Discipline-drift: ✅/🟡/🔴
<findings>

### §5 — Architectural debt: ✅/🟡/🔴
<findings>

### §6 — Cross-doc consistency: ✅/🟡/🔴
<findings>

### NEW issues surfaced
- <count> issues / <count> new B-number candidate entries (template placeholder; reviewer fills with concrete B-NNN values OR explicit dismissal) / <count> latent risks
- Per-issue: severity (🔴/🟡/✅) + specific file:line context + recommended remediation

### Final verdict
<recommendation for parent agent>
```

After receiving the reviewer verdict, parent agent:
- 🔴 BLOCKER: surface to user; do NOT auto-fix; await direction
- 🟡 ISSUES: apply inline-fixes per reviewer recommendation OR open new B-Ns OR both; commit remediation
- ✅ CLEAN: proceed to next work

## Composition with other skills

| Used with | Role |
|---|---|
| `udm-gap-check` (hard rule 11) | Complementary — gap-check is per-commit; cohort-review is across 2-N commits. Both can fire on the same cohort at different scopes. |
| `udm-design-reviewer` (hard rule 14) | Complementary — design-reviewer is single-commit substrate-edit cascade; cohort-review is cross-commit. Cohort-review may surface design issues design-reviewer missed at single-commit scope. |
| `udm-cascade-auditor` Pattern F (D89-D91) | Complementary — Pattern F is round-aggregate; cohort-review is sub-round multi-commit. Cohort-review findings may feed into Pattern F at round close-out. |
| `udm-round-closeout` (D60) | Composition point — at round close-out, cohort-review (this skill) for the final cohort + Pattern F for round-aggregate run BOTH before round 🟢 lock. |
| `udm-progress-logger` (hard rule 9) | Sequence — progress-logger runs IMMEDIATELY at completion; cohort-review runs at cohort-scope after several completions. |
| `udm-next-step-cascade` | Composition — cascade Step 2 gap-check runs udm-gap-check; if cohort has accumulated ≥3 commits, ALSO run udm-cohort-review as part of Step 2 OR at session-pause. |

## Edge cases

- **No prior commits to review**: skill cannot identify a cohort → ASK user OR return "N/A: insufficient commit history for cross-cohort review"
- **Reviewer agent finds 🔴**: surface to user; do NOT auto-fix per CLAUDE.md hard rule 11 + D56 second-pass discipline
- **Cohort spans round boundaries**: include commits from prior round IF they share theme with current cohort; flag the boundary in scope statement
- **Trivial cohort (3 cosmetic commits with no substantive change)**: still run all 6 scopes but expect ✅ CLEAN; verdict format unchanged
- **User invokes during active planning session**: cross-cohort review on plan deliverables (not committed code) — adapt §3 test coverage to "plan deliverable scope coverage" and §5 to "plan completeness"

## Tier 0 stub (per D67)

`tests/tier0/test_skill_cohort_review.py` (Tier 1 if more complex). Verifies:
- Skill file exists at canonical path
- Frontmatter `name` field = "udm-cohort-review"
- Frontmatter `description` field non-empty
- Required sections present: "When to invoke" + "Anti-triggers" + "6-scope procedure" + "Output contract" + "Composition"
- Trigger phrases section enumerates ≥4 canonical phrases
- 6-scope procedure section contains all 6 scope headers (§1 through §6)
- Output contract template includes "Cross-cohort review verdict" header

## Cross-references

- User-direction 2026-05-18: "This statement tells me that our review process only looks at single commits rather than the entire cohort of events from a recent enhancement. ... Come up with a proposal to address this gap" — the authorization for THIS skill.
- Empirical anchor: cross-cohort reviewer agent `aa320fb75f55a5471` at 2026-05-18 (cohort ccf21a2 + 133b212 + 9983bee).
- CLAUDE.md hard rule 11 (cohort-review extension — added at B-483 closure)
- CLAUDE.md hard rule 14 (substrate-edit cascade; complementary scope)
- D55 + D56 (producer ≠ reviewer discipline; this skill spawns independent reviewer)
- D89-D91 (Pattern F Layer 1 + Layer 2 round-level cascade audit; complementary scope)
- HANDOFF §8 Pitfall #9 sub-classes 9.h + 9.j + 9.k + 9.l + 9.m + 9.n + 9.o (failure modes the 6-scope procedure detects)

## Anti-pattern this skill closes

Independent review discipline operated at SINGLE-COMMIT scope (per-commit PRE-COMMIT design-reviewer + per-completion udm-gap-check) — but multi-commit cohort failure modes (compositional drift, cumulative propagation, fragmentation accumulation, stale forward-references) are INVISIBLE at single-commit scope by construction. Round-level Pattern F catches round-aggregate drift but ONLY at round close-out (too late for mid-round cohort feedback).

The 1-event empirical anchor (cross-cohort reviewer at 2026-05-18 catching 5 issues 3 single-commit reviewers missed) confirms the gap is structural, not coincidental — single-commit reviewers CANNOT see cross-commit interactions by definition.

This skill closes the gap with a third review layer at cohort scope, between per-commit and per-round cadences.

## Owner

Pipeline lead. First production invocation: at user-direction "Run a gap analysis or review to see if there are any issues with the recent enhancements" 2026-05-18 (informal; via general-purpose subagent). First skill-formalized invocation: per next user trigger-phrase invocation OR auto-trigger at next session pause.
