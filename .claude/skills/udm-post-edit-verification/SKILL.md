---
name: udm-post-edit-verification
version: 1.1.0
description: Mandatory post-edit verification cascade per CLAUDE.md hard rule 14 — runs TEST + GAP ANALYSIS + REVIEW after ANY substantive update / enhancement / creation of an object (markdown file / code / SKILL.md / D-N body / runbook / SP / etc.) BEFORE commit. Closes the discipline-debt accumulation pattern that surfaced across this project's history (commit 521b68c stale-narrative-quotation; D.3/D.4 cumulative pragmatic exemptions documented in B-285 / B-286). Trigger: any substantive edit. Anti-trigger: trivial typo fixes (<5 lines + no semantic change) + tracker-only commits (BACKLOG strikethrough flip only). Per user-direction 2026-05-15. v1.1.0 (2026-05-16) per B-317 Phase 2B: adds tri-section labeling discipline (closes B-318) + Workflow tooling subsection citing tools/generate_cascade_evidence.py + tools/cascade_classifier.py + auto-spawn parallel-agent pattern for substrate edits.
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

**SUBSTRATE override (per Phase 2A; v1.1.0)**: anti-triggers above do NOT apply to substrate-edit commits. `tools/cascade_classifier.py::is_substrate_path()` mechanically detects substrate (CLAUDE.md / .claude/skills/udm-*/SKILL.md / .claude/agents/udm-*.md / `tools/pre_commit_checks.py` etc.) and classifies as `SUBSTRATE_EDIT` with `cascade_required=True` regardless of typo/whitespace/badge-flip appearance. Substrate-edits are high-risk by definition (they BREAK discipline if broken). Empirical: commit `0a0ff49` silently skipped cascade on substrate refactor.

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

## Output contract — Tri-section labeling discipline (v1.1.0; closes B-318)

After cascade completes, parent agent MUST emit explicit tri-section markdown headers in the commit message (NOT a bullet list — markdown headers are mechanically detected by `tools/check_commit_msg.py` cascade-evidence regex per B-317 Phase 1A).

**Required structure (mechanically enforced at commit-msg hook for non-anti-trigger commits)**:

```markdown
## TEST
<pytest verdict — fresh run; cite NNN/MM/0>
<orchestrator smoke test verdict if applicable — `python tools/pre_commit_checks.py --verbose` → 6/6 PASS>
<targeted-module test verdict>

## GAP ANALYSIS
<udm-gap-check independent reviewer agentId + verdict>
<OR inline G1-G6 audit with per-category verdict>

## REVIEW
<scope-appropriate reviewer skill + agentId + verdict>
<OR inline self-review (valid ONLY ≤50 LOC + no new public surface; NEVER valid for SUBSTRATE_EDIT)>
```

**For anti-trigger commits (TYPO_ONLY / WHITESPACE_ONLY / BADGE_FLIP_ONLY / POLISH_QUEUE_ONLY)**: each section may contain `SKIPPED: <classification> anti-trigger` text. Generator emits this scaffold automatically (see Workflow tooling subsection below).

**Mechanical enforcement (Phase 1A; B-317)**: `tools/check_commit_msg.py` invokes `tools/cascade_classifier.py::classify_commit()` → if `cascade_required=True` (SUBSTANTIVE / SUBSTRATE_EDIT), then `has_cascade_evidence()` regex scan must find all 3 section headers OR commit-msg hook BLOCKS the commit. Producer cannot bypass mechanically without `--no-verify` (self-flagging).

This commit-message section IS the audit trail. Future Pattern F audits cross-check the commit-message claim against actual evidence in `_validation_log.md` + sub-agent transcripts.

## Workflow tooling (v1.1.0 — Phase 2A; B-317)

**`tools/generate_cascade_evidence.py`** — friction-reduction template generator. Producer runs `python tools/generate_cascade_evidence.py --no-audit` on staged scope; tool classifies the commit + emits tri-section template appropriate to classification (ANTI_TRIGGER brief with SKIPPED / SUBSTANTIVE full G1-G6 scaffold / SUBSTRATE full + 6-reviewer-type scaffold). Producer pipes into commit message + fills verdicts. Removes the "skip cascade because writing evidence section is overhead" failure mode.

**`tools/cascade_classifier.py`** — 6-classification mechanical detector (SUBSTRATE_EDIT / TYPO_ONLY / WHITESPACE_ONLY / BADGE_FLIP_ONLY / POLISH_QUEUE_ONLY / SUBSTANTIVE). Strict mode: substrate-edits (enumerated `SUBSTRATE_FILES` + `SUBSTRATE_DIR_PREFIXES`) OVERRIDE all anti-trigger detection per CLAUDE.md hard rule 14 substrate-edit clause. Used by both `tools/check_commit_msg.py` enforcement + `tools/generate_cascade_evidence.py` template generation.

**`tools/check_commit_msg.py`** — commit-msg hook enforcement (Phase 1A). Reads classification + verifies tri-section structure for cascade-required commits. Audit row written to `_session_logs/cli_check_commit_msg_<date>.log` per D76 with classification + missing_sections payload for forensic audit.

**Producer workflow** (v1.1.0 recommended pattern):
1. Make edits + stage with `git add`
2. Run `python tools/generate_cascade_evidence.py --no-audit` → get scaffold
3. Run TEST / GAP ANALYSIS / REVIEW per scaffold; fill in verdicts
4. Commit via `git commit -F <commit-msg-file>` OR `git commit -m "<message>"` — BOTH trigger the commit-msg hook per B-307 closure (hook receives `COMMIT_EDITMSG` path as `$1`; reliable for ALL commit modes including direct `-m`)

**When to skip the generator**: anti-trigger commits classified as TYPO_ONLY / WHITESPACE_ONLY / BADGE_FLIP_ONLY / POLISH_QUEUE_ONLY may skip the generator if the producer writes a minimal commit message + the commit-msg hook will not BLOCK (anti-triggers bypass cascade-evidence check). For all SUBSTANTIVE / SUBSTRATE commits: ALWAYS use the generator OR write the tri-section structure manually.

## Auto-spawn parallel-agent pattern (v1.1.0 — Phase 2B optional discipline)

For SUBSTANTIVE / SUBSTRATE_EDIT commits where independent review is required, parent agent should spawn GAP ANALYSIS + REVIEW agents in PARALLEL (not sequential) via `Agent` tool with `run_in_background=true`. While agents work, parent does tracker updates. When agents complete, parent synthesizes findings into commit message.

**Why parallel**: GAP ANALYSIS (`udm-gap-check`) and REVIEW (`udm-design-reviewer` / `udm-data-engineer-review` / etc.) review DIFFERENT scopes. Their work is independent. Sequential invocation wastes wall-clock time.

**Pattern**:
```
1. Make + stage edits
2. Spawn 2 background agents (Agent tool, run_in_background=true):
   - Agent A: udm-design-reviewer (or scope-appropriate review)
   - Agent B: udm-gap-check 6-category audit
3. While agents work: pytest verify + tracker updates (BACKLOG / CURRENT_STATE / HANDOFF / _validation_log)
4. Await both task-notification completions
5. Synthesize findings into commit message tri-section structure
6. Apply BLOCK findings inline; defer IMPROVE findings as B-Ns
7. Commit (hook validates)
```

**Empirical anchor** (2026-05-16 session; 4 commits): `db77516` (B-313/B-314/B-315 cohort; 2 agents A+B), `354dd5d` (B-316 fix-cycle 2; retroactive cascade on 0a0ff49 with 2 agents), `c0ad9c6` (Phase 1A/1B/2A landing; 1 design reviewer), `c662863` (Phase 2A generator; 1 design reviewer). Total 6 sub-agent invocations; 0 missed-finding regressions; all reviewer-surfaced 🔴 BLOCKs caught + fixed inline before commit. Pattern composes with hard rule 14 cascade.

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
- User-direction 2026-05-16: "We need a complete solution to ensure this never happens again. Come up with an extensive plan." → B-317 Phase 1A + 1B + 2A + 2B (this v1.1.0 amendment).
- **CLAUDE.md hard rule 14** (canonical home; binding directive) + substrate-edit clause (Phase 2A added 2026-05-16)
- `udm-gap-check` SKILL.md (Step 2 invocation)
- `udm-checks-and-balances` SKILL.md (Step 3 invocation for D-N + doc scopes)
- `superpowers-verification-before-completion` SKILL.md (Step 1 verification discipline)
- `udm-step-10-verifier` SKILL.md (Step 1 substep for new public surface)
- `udm-next-step-cascade` SKILL.md (Step 1.6 NEW invokes this skill)
- `udm-exemption-verifier` SKILL.md (Step 2.5 invocation; Mechanism B for exemption claims)
- `PLANNING_DISCIPLINE.md` §2.3 always-mandatory skills (this skill added)
- `tools/cascade_classifier.py` (Phase 1B mechanical classifier; B-317)
- `tools/check_commit_msg.py` cascade-evidence enforcement (Phase 1A; B-317)
- `tools/generate_cascade_evidence.py` (Phase 2A friction reduction; B-317)
- HANDOFF §8 Pitfall #9.o candidate B-286 (formalization candidate; superseded by hard rule 14 forward-prevention; B-286 closed concurrent with this skill landing)
- B-317 (Phase 1A + 1B + 2A + 2B complete; closes silent cascade-skip class)
- B-318 (tri-section labeling discipline; closed inline at v1.1.0 amendment)
- Evidence base: commit `521b68c` + `3eef410` + `aee329c` + `a03a35c` discipline-debt accumulation events + commit `0a0ff49` (B-316 closure; silent cascade-skip empirical anchor)

## Owner

Pipeline lead. First production invocation expected: immediately after this skill is committed (self-applies via Step 1 of `udm-next-step-cascade` Step 1.6 NEW extension).
