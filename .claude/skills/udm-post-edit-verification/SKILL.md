---
name: udm-post-edit-verification
version: 1.0.0
description: Mandatory post-edit verification cascade per CLAUDE.md hard rule 14 — runs TEST + GAP ANALYSIS + REVIEW after ANY substantive update / enhancement / creation of an object (markdown file / code / SKILL.md / D-N body / runbook / SP / etc.) BEFORE commit. Closes the discipline-debt accumulation pattern that surfaced across this project's history (commit 521b68c stale-narrative-quotation; D.3/D.4 cumulative pragmatic exemptions documented in B-285 / B-286). Trigger: any substantive edit. Anti-trigger: trivial typo fixes (<5 lines + no semantic change) + tracker-only commits (BACKLOG strikethrough flip only). Per user-direction 2026-05-15.
---

# UDM Post-Edit Verification

Mandatory cascade per CLAUDE.md hard rule 14. After ANY substantive edit, run the 3-step verification BEFORE claiming the work complete or committing.

## CRITICAL — when this skill fires

This skill is **always-mandatory** per CLAUDE.md hard rule 14 for any substantive edit. It is NOT user-trigger-gated like `udm-next-step-cascade`; it fires automatically after any qualifying edit.

### Triggers (any of these)

- Code file modified (`.py` / `.sql` / `.yaml` / `.toml` / etc.)
- Markdown file created OR substantively edited (>5 line change OR semantic content change)
- Skill SKILL.md created OR modified
- Agent definition modified
- New D-N / B-N / R-N / RB-N / SP-N entry
- New EventType constant
- Configuration value change

### Anti-triggers (NO cascade required)

- Typo fix < 5 lines AND no semantic change
- BACKLOG.md strikethrough-only flip (B-N closure annotation; leading-badge flip per Pitfall #9.j)
- Whitespace / line-ending normalization
- POLISH_QUEUE P-N entry cosmetic edit
- This very SKILL.md authoring (recursive trigger; bootstrap exemption documented)

### When in doubt

ASK whether the edit qualifies. Default to invoking the cascade. Cost of unnecessary cascade < cost of skipped cascade.

## 3-step procedure

### Step 1 — TEST (artifact-type-appropriate verification)

| Artifact type | TEST verification |
|---|---|
| Python code | `pytest tests/tier0 tests/tier1 tests/unit tests/property tests/regression tests/integration tests/crash -q --no-header` (full authoritative; per Pitfall #9.k stale-narrative-quotation lesson — DO NOT carry pytest count from prior commit) |
| Markdown doc | (a) cross-ref resolution check (`grep -E "\]\(([^)]+)\)" <file>` + verify each link); (b) anchor verification (`grep "^## " <file>` for slug stability); (c) Step 10 if new public surface |
| Skill SKILL.md | (a) YAML frontmatter parses; (b) `name:` field matches directory; (c) CCL Stage references resolve; (d) trigger phrase examples present |
| New D-N / RB-N body | (a) Status badge present; (b) §Rationale + §Affects + §Reversibility sections present; (c) cross-refs resolve |
| Configuration value | (a) Schema validation (if applicable); (b) related tests pass |
| EventType constant | (a) CLAUDE.md L325 CLI_\* family registry updated (if CLI_\* type); (b) `phase1/02_configuration.md` family registry updated |

Apply `superpowers-verification-before-completion` Iron Law: "NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE". Run the test commands NOW — not from memory.

### Step 2 — GAP ANALYSIS (`udm-gap-check`)

Invoke `udm-gap-check` skill per CLAUDE.md hard rule 11. For substantial edits (multi-file OR new public surface OR new D-N), this means **spawning an INDEPENDENT reviewer agent** (general-purpose with inheritance contract per hard rule 13). For smaller edits (single-file content modification with clear scope), inline 6-category gap-check (G1-G6) may substitute.

**Step 2.1 — Self-application via `query_blindspots` on META-COMMIT files (added 2026-05-16 per B-299 closure)**: BEFORE invoking the broader gap-check (independent agent OR inline 6-category), run `python tools/query_blindspots.py --file <each-META-COMMIT-file> --severity p0,p1 --no-audit` on the COMPLETE set of files modified by the current commit (not just a sample). Cite each scan's verdict in the commit-message cascade-evidence section. **Empirical anchor**: Pitfall #9.o INSTANCE-6 (commit `570ac67` 2026-05-16) — producer ran `query_blindspots` only on BACKLOG.md (predictable B144 match) and NOT on META-COMMIT's actually-edited files (`03_DECISIONS.md` D114 body / `GLOSSARY.md` surface rows / `CODE_BUILD_STATUS.md` / `ONE_OFF_SCRIPTS.md` / `HANDOFF.md` / `INDEX.md`). This is Pitfall #9.m discipline-not-applied-to-own-tracker textbook, masked by selective smoke-test scope. The "Empirical smoke-test verification" section in the commit message created the illusion of self-application without the substance. **Hard rule**: per Step 2.1, the cascade-evidence section MUST enumerate each META-COMMIT file scanned + each scan's match-count + verdict. Absence of per-file enumeration = self-application incomplete = GAP ANALYSIS Step 2 invalid.

**6-category audit**:
- G1: Pitfall #9.j leading-badge alignment
- G2: Pitfall #9.k arithmetic-propagation
- G3: Pitfall #9.l canonical re-read
- G4: Pitfall #9.m discipline-applied-to-tracker
- G5: Pitfall #9.n convention-registration
- G6: new B-N opportunities

Verdict: ✅ CLEAN / 🟡 fixable inline / 🔴 escalate.

If 🟡: fix inline + re-verify. If 🔴: surface to user + DO NOT commit until resolved.

### Step 2.5 — EXEMPTION VERIFICATION (`udm-exemption-verifier`; added 2026-05-16 per B-296 closure / Pitfall #9.o instance-7 closure)

If the draft commit message contains ANY of these phrases:
- "Layer N+1 termination"
- "recursive-exemption"
- "verbatim implementation"
- "100% overlap on architectural-decision-substance"
- "specific scope-justified exemption"
- "REVIEW: SKIPPED"
- "no new architecture introduced"
- "implementing prior reviewer's recommendation"

Then **MUST invoke `udm-exemption-verifier` skill** (see `.claude/skills/udm-exemption-verifier/SKILL.md`) BEFORE proceeding to Step 3 OR committing. The verifier is Mechanism B per CLAUDE.md hard rule 14 anti-rationalization clause; 5-min budget cap; binary VALID/INVALID verdict.

**Verdict handling**:
- **VALID** → exemption substantiated; proceed to Step 3 (parent inline REVIEW per scope-justified pattern)
- **INVALID-with-specific-files** → spawn `udm-gap-check` independent reviewer per D56 second-pass; address findings; re-run Step 2.5; do NOT commit until verdict flips to VALID

**Empirical anchor**: 7-instance Pitfall #9.o evidence base (commits 521b68c / 3eef410 / aee329c / a03a35c / 4112e92 / 570ac67 / 01d32c0) proved Mechanism A v3 (step-5 self-evidence requirement) empirically insufficient — pattern recurred within ~30 min of clause codification. Mechanism B (this Step 2.5 invocation) breaks the recursive failure mode by shifting verification from producer self-judgment to independent third-party agent invocation.

**Anti-trigger for Step 2.5**: if commit message contains FULL independent reviewer evidence (Agent A + Agent B + gap-check all spawned + cited inline), no exemption is being claimed → Step 2.5 not needed → proceed directly to Step 3.

### Step 3 — REVIEW (scope-appropriate)

Per PLANNING_DISCIPLINE.md §2.2 matrix, invoke the appropriate review skill:

| Edit scope | REVIEW skill |
|---|---|
| Architectural / cross-cutting | `udm-design-reviewer` (agent) |
| Pipeline-touching (CDC / SCD2 / Polars / Parquet / BCP) | `udm-data-engineer-review` (agent) |
| D-N body (locked OR new) | `udm-checks-and-balances` (5-gate per D55) |
| Runbook (RB-N) | `udm-runbook-author` validation pass |
| New stored procedure | `udm-data-engineer-review` + SchemaContract row check |
| Edge case (M/S/I/N/P/G/D/F/V/T/DP/SI) | `udm-edge-case-validator` |
| Markdown doc / sidecar / archive | `udm-checks-and-balances` 5-gate (cross-ref + idempotency emphasis) |
| Skill SKILL.md content | `udm-cascade-audit-evolver` if Pattern F discipline change; else inline review per `udm-producer-checklist-evolver` |
| Trivial cosmetic | NO review (anti-trigger; skip cascade entirely) |

### Acceptance gate (after all 3 steps)

ALL three steps must produce ✅ verdict OR documented 🟡-with-inline-fix evidence. Then commit IS allowed.

If any step produces 🔴 escalate — DO NOT commit; surface to user for direction.

## Output contract

After cascade completes, parent agent must emit (in commit message OR `_validation_log.md` entry):

```markdown
**Post-edit verification cascade per hard rule 14**:
- TEST: <command run> → <verdict + fresh evidence>
- GAP ANALYSIS: <skill invoked + verdict>
- REVIEW: <skill invoked + verdict>
- ANTI-TRIGGER claim (if cascade skipped): <which anti-trigger applies + justification>
```

This commit-message section IS the audit trail. Future Pattern F audits cross-check the commit-message claim against actual evidence in `_validation_log.md` + sub-agent transcripts.

## Cost discipline

| Cascade tier | Time | When |
|---|---|---|
| Full cascade (TEST + GAP + REVIEW) | ~5-10 min | Substantive new content OR architectural change |
| Light cascade (TEST + inline GAP only) | ~1-2 min | Single-file content modification with clear scope |
| Anti-trigger skip | 0 min | Typo / strikethrough flip / cosmetic |

Apply minimum-viable per scope. Per PLANNING_DISCIPLINE.md §2.5 minimum-viable-set principle: DON'T spawn 3 sub-agents for a 2-line fix.

## Composition with other skills

| Skill | Relationship |
|---|---|
| `udm-next-step-cascade` | Step 1.6 (NEW) invokes this skill after Step 1's edit lands |
| `udm-gap-check` | Step 2 of this skill IS udm-gap-check invocation |
| `udm-checks-and-balances` | Step 3 of this skill IS udm-checks-and-balances invocation (for D-N + runbook + doc scopes) |
| `superpowers-verification-before-completion` | Step 1 of this skill IS verification-before-completion application |
| `udm-step-10-verifier` | Step 1 substep for any edit introducing new public surface |
| `udm-progress-logger` | Invoked AFTER this skill's cascade completes; logs the verification evidence |

## Examples

### Example 1 — Code change (full cascade)

```
User: "Fix the bug in cdc/engine.py _filter_null_pks()"
Parent agent: [makes the fix]
Parent agent: [invokes udm-post-edit-verification skill]
  TEST: pytest tests/tier0..tests/crash -q → 2320 pass / 58 skip / 0 fail (fresh; per Pitfall #9.k)
  GAP ANALYSIS: udm-gap-check inline (single-file content; no public surface change) → ✅ CLEAN
  REVIEW: udm-data-engineer-review (CDC engine touched) → spawn sub-agent → verdict ✅
  Acceptance: ✅; commit allowed
```

### Example 2 — Markdown doc creation (full cascade)

```
User: "Author docs/migration/SECURITY_MODEL.md per D103"
Parent agent: [authors the doc]
Parent agent: [invokes udm-post-edit-verification skill]
  TEST: cross-ref check (grep all links resolve) + Step 10 (new public surface) ✅
  GAP ANALYSIS: spawn udm-gap-check independent reviewer → 6-category → ✅ CLEAN
  REVIEW: udm-checks-and-balances 5-gate → spawn sub-agent → ✅ all gates pass
  Acceptance: ✅; commit allowed
```

### Example 3 — Trivial typo fix (anti-trigger; skip cascade)

```
User: "Fix typo in HANDOFF.md L42"
Parent agent: [edits 1 word]
Parent agent: [recognizes anti-trigger; skips cascade]
  ANTI-TRIGGER claim: typo fix < 5 lines + no semantic change → cascade skipped
  Commit message includes anti-trigger justification
```

### Example 4 — BACKLOG strikethrough flip (anti-trigger; skip cascade)

```
User: "Close B-145 in BACKLOG"
Parent agent: [flips leading badge per Pitfall #9.j]
Parent agent: [recognizes anti-trigger; skips cascade]
  ANTI-TRIGGER claim: BACKLOG strikethrough-only flip → cascade skipped
  Commit message includes anti-trigger justification
```

### Example 5 — Skill SKILL.md content modification (light cascade)

```
User: "Add Stage 0 reference to all 20 SKILL.md files"
Parent agent: [bulk script edits 20 files]
Parent agent: [invokes udm-post-edit-verification skill]
  TEST: grep -l "Stage 0" .claude/skills/udm-*/SKILL.md | wc -l → 20 ✅
  GAP ANALYSIS: inline 6-category (mechanical bulk edit; deterministic) → ✅ CLEAN
  REVIEW: SKIPPED (per Pitfall #9.j SKILL.md content modification is not architectural)
  Acceptance: ✅ (light cascade); commit allowed
```

## Anti-pattern this skill closes

Throughout 2026-05-15 session:
- Commit `521b68c` (sign-off ceremony): claimed `pytest 2320/62/0` WITHOUT running pytest → caught only via post-hoc user audit-question → remediation `1b00755`
- Commits `3eef410` (D.3) + `aee329c` (cleanup) + `a03a35c` (D.4): cumulative pragmatic exemptions; SAME skill (udm-gap-check) deferred in 3 consecutive same-session commits → caught only via post-hoc user audit-question → remediation `57f6336`
- Pattern: discipline rigor decays as session length grows; minimum-viable defaults become skip-default

This skill structurally prevents the pattern by making the cascade mandatory + auto-fire per edit. The discipline becomes part of the COMMIT flow, not an optional post-hoc check.

## Tier 0 stub (per D67)

`tests/tier0/test_skill_post_edit_verification.py`. Verifies:
- Skill imports / parses
- Trigger-classifier rejects empty / single-word "edit" claims
- Trigger-classifier accepts code / markdown / SKILL.md / D-N edits
- Anti-trigger-classifier accepts typo (<5 lines) / strikethrough-flip / whitespace
- Edge case: ambiguous edit → returns ASK verdict (parent agent asks user)
- 3-step output contract format

## Cross-references

- User-direction 2026-05-15: "Turn this into a mandatory event. After updating, enhancing, or creating a new object such as markdown file or code, a test, gap analysis, and review must be run to check the latest updates."
- **CLAUDE.md hard rule 14** (canonical home; binding directive)
- `udm-gap-check` SKILL.md (Step 2 invocation)
- `udm-checks-and-balances` SKILL.md (Step 3 invocation for D-N + doc scopes)
- `superpowers-verification-before-completion` SKILL.md (Step 1 verification discipline)
- `udm-step-10-verifier` SKILL.md (Step 1 substep for new public surface)
- `udm-next-step-cascade` SKILL.md (Step 1.6 NEW invokes this skill)
- `PLANNING_DISCIPLINE.md` §2.3 always-mandatory skills (this skill added)
- HANDOFF §8 Pitfall #9.o candidate B-286 (formalization candidate; superseded by hard rule 14 forward-prevention; B-286 closed concurrent with this skill landing)
- Evidence base: commit `521b68c` + `3eef410` + `aee329c` + `a03a35c` discipline-debt accumulation events

## Owner

Pipeline lead. First production invocation expected: immediately after this skill is committed (self-applies via Step 1 of `udm-next-step-cascade` Step 1.6 NEW extension).
