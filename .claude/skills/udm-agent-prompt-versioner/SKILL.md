---
name: udm-agent-prompt-versioner
description: Applies user-approved prompt deltas from `udm-specialty-tuner` / `udm-subclass-accumulator` / `udm-producer-checklist-evolver` / `udm-cascade-audit-evolver`. Manages semver `vMAJOR.MINOR.PATCH` versioning on `.claude/agents/<name>.md` per Round 8 D98 — MAJOR=structural; MINOR=directive addition; PATCH=wording polish. Archives prior versions to `.claude/agents/_archive/<name>-<version>-<date>.md` (append-only audit trail). Maintains per-agent changelog at `docs/migration/_agent_evolution/<name>-changelog.md`. Auto-revert on regression at next round close-out. NEVER applies without explicit user approval per Round 8 D95 umbrella. Invoked LAST in close-out cascade after pipeline lead reviews all proposed deltas.
---

# UDM Agent Prompt Versioner

Sixth (and final) close-out skill. The ONLY skill in the suite that writes to `.claude/agents/`. All others propose; this one applies (after user approval).

## When to invoke

- Every round close-out, AFTER user has reviewed 8.B/8.C/8.D/8.E/8.G proposed deltas + approved a batch
- Position: 7th and LAST of 7 close-out skills (applies user-approved batch from the 5 analysis skills; per `udm-round-closeout` Section 10.7 NEW)
- Skip if NO deltas approved (no writes needed)

## When NOT to invoke

- BEFORE user approval — skill aborts 🔴 if invoked without explicit approval token
- For changes touching production pipeline code (out-of-scope; this is meta-tooling only)

## Canonical Context Load (CCL) per D62

- **Stage 1**: `NORTH_STAR.md` + `HANDOFF.md` + `CURRENT_STATE.md` + `CHECKS_AND_BALANCES.md`
- **Stage 2**: `RISKS.md` + `BACKLOG.md` + `_validation_log.md`
- **Stage 3**: Target agent prompt file (e.g., `.claude/agents/udm-design-reviewer.md`); approved-deltas batch from pipeline lead (typically via skill output review session)
- **Stage 4**: grep `.claude/agents/_archive/` for prior versions

## Input contract

```python
@dataclass
class ApprovedDelta:
    target_agent: str  # filename without .md, e.g., "udm-design-reviewer"
    change_type: Literal["MAJOR", "MINOR", "PATCH"]
    source_skill: str  # which skill proposed: "specialty-tuner" / "subclass-accumulator" / "producer-checklist-evolver" / "cascade-audit-evolver"
    before_text: str  # exact prior content to replace
    after_text: str  # new content
    justification: str  # one-paragraph rationale (typically cites empirical evidence)
    approved_by: str  # pipeline lead identity
    approved_at: str  # YYYY-MM-DD
```

## Versioning convention (per D98)

Semver `vMAJOR.MINOR.PATCH`:
- **MAJOR**: structural change (new mandatory tool, new mandatory output section, output schema change)
- **MINOR**: directive addition (new producer self-check item, new sub-class)
- **PATCH**: wording polish (example update, line-citation fix, terminology tightening)

Frontmatter:
```yaml
---
name: udm-design-reviewer
description: ...
tools: Read, Grep, Glob, Bash
model: opus
version: v1.2.1
last_updated: 2026-05-11
changelog: docs/migration/_agent_evolution/udm-design-reviewer-changelog.md
---
```

## Apply procedure

For each ApprovedDelta:

1. **Read target file** + verify `before_text` matches CURRENT content (exact-match enforcement; abort 🔴 if drift)
2. **Read current frontmatter** version (e.g., `v1.2.0`)
3. **Bump version** per change_type (MAJOR: v1→v2; MINOR: v1.2→v1.3; PATCH: v1.2.0→v1.2.1)
4. **Copy current file** to `.claude/agents/_archive/<name>-v<current>-<date>.md` (append-only archive)
5. **Apply delta** to target file (replace `before_text` with `after_text`)
6. **Update frontmatter** (bump `version`, set `last_updated`)
7. **Append changelog row** to `docs/migration/_agent_evolution/<name>-changelog.md`

## Changelog row format

```markdown
## v1.2.1 — 2026-05-11

**Source**: <source_skill> Round <N> proposal accepted by <approved_by> <approved_at>
**Change type**: <MAJOR/MINOR/PATCH>
**Delta**:
- Section "<section-name>": <one-line summary>

**Rationale**: <justification quote>

**Tested at**: Round <N> close-out cascade; no regressions found.
**Reversible**: yes — prior v<prior-version> archived at `.claude/agents/_archive/<name>-v<prior>-<date>.md`
```

## Auto-revert on regression

If round N+1's first cycle shows regression in a region just-versioned at round N close-out:
1. Pipeline lead OR `udm-specialty-tuner` flags it
2. This skill invoked with rollback mode
3. Skill copies `_archive/<name>-v<prior>-<date>.md` back to `.claude/agents/<name>.md`
4. Changelog appended: `## v1.2.1 (REVERTED to v1.2.0) — <date>` with regression evidence
5. Failed delta becomes input to next 8.B/8.C/8.D invocation (so they learn from the failure pattern)

## User approval gate (HARD RULE per D95)

Skill ABORTS 🔴 if invoked without `approved_by` + `approved_at` fields populated. NO autonomous application. The discipline is user-review-once-per-round, not user-review-per-delta-individually — pipeline lead reviews skill output batch + approves N-of-M deltas, then this skill applies the approved batch.

## Composition

| Used with | Role |
|---|---|
| `udm-specialty-tuner` | Proposes deltas; THIS skill applies them after approval |
| `udm-subclass-accumulator` | Same |
| `udm-producer-checklist-evolver` | Same |
| `udm-cascade-audit-evolver` | Same |
| `udm-round-closeout` | Invokes this skill at the end of close-out after user-approval batch |
| `.claude/agents/_archive/` | Append-only archive of all superseded prompts |

## Tier 0 stub (per D67)

`tests/smoke/test_skill_agent_prompt_versioner.py`. Verifies:
- Skill imports
- Version bump correct (MAJOR/MINOR/PATCH)
- Apply procedure preserves frontmatter
- Archive copy is byte-identical to pre-apply file
- Abort on missing approval fields

## Anti-patterns

- ❌ Applying delta without user approval — abort 🔴
- ❌ Bumping version without archiving prior — discipline violation
- ❌ Editing changelog retroactively — append-only
- ❌ Skipping reversibility evidence — every delta must be revertable

## Cross-references

- D95 (umbrella) + D98 (versioning convention)
- `docs/migration/phase1/08_sub_agent_self_improvement.md` § 7
- `.claude/agents/_archive/` — directory
- `docs/migration/_agent_evolution/<name>-changelog.md` — per-agent changelogs

## Owner

Pipeline lead. ALL writes to `.claude/agents/` go through this skill (no direct edits to agent prompts after Round 8 lock).
