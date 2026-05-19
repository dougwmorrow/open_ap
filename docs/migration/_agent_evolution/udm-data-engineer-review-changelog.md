# udm-data-engineer-review — Changelog

Per D98 agent-versioning convention (semver `vMAJOR.MINOR.PATCH` on `.claude/agents/<name>.md`); MAJOR=structural change, MINOR=directive addition, PATCH=wording polish. Archived prior versions live at `.claude/agents/_archive/<name>-<version>-<date>.md` (append-only audit trail).

This changelog is the per-agent audit trail mandated by `udm-agent-prompt-versioner` skill (per D98 + Round 8 D95 umbrella).

## v1.0.0 — 2026-05-18

**Initial authoring** per B-503 closure (was B-339 pre-v5-renumber per Phase 2 large-tables plan v5 cohort, commit `864e91a`).

**Specialty**: pipeline-mechanics review at scale (3B-row class) — CDC / SCD2 / Polars / Parquet / BCP / SQL Server / Oracle / ConnectorX design choices against industry-standard patterns + UDM pipeline's empirical baselines.

**Empirical anchor**: substitutes for the general-purpose agent `a5e19d35c7c5e3281` which performed v1 pipeline-mechanics review of `docs/migration/PHASE2_LARGE_TABLES_AUDITLOG_PILOT_PLAN_2026-05-18.md` (3 BLOCK + 6 IMPROVE + 1 PASS across M1-M9 dimensions). Findings from that v1 review informed plan v2 → v3 → v4 → v5 absorbed deltas (B-507 + B-508 + ... + B-521 + R-N escalations R53 / R58 / R59 / R60 / R61). The M1-M9 dimensions are canonical because they're the empirically-validated review surface for this class of work.

**Closes**: B-339 (original "udm-data-engineer-review agent type 'not found' from D2 execution plan attempt") + B-503 (v5-renumbered B-339 = "udm-data-engineer-review agent authored at .claude/agents/udm-data-engineer-review.md; replaces v1's general-purpose-substitute contingency").

**Structure**: YAML frontmatter (name + description + tools + model + version + last_updated + changelog) + body sections (specialty + when-to-invoke + trigger phrases + anti-triggers + CCL Stage 1-3 operating model + M1-M9 review dimensions + output contract + examples + 10 anti-patterns + composition table + empirical anchor + sub-agent inheritance contract + owner). Mirrors `udm-design-reviewer.md` canonical structure (per `udm-design-reviewer-changelog.md` precedent).

**Tools**: Read, Grep, Glob, Bash (read-only review; mirrors udm-design-reviewer).

**Composition**: PS-4 SP mandatory at session start (per `docs/migration/PLANNING_DISCIPLINE.md` §2.2 matrix); PS-1 ARCH + PS-3 TOOL conditional (when scale-dependent claims or pipeline-mechanics-touching tools). Pairs with `udm-design-reviewer` for build cohorts touching pipeline core; pairs with `udm-checks-and-balances` 5-gate at attestation.

**Related skill**: a SKILL also exists at `.claude/skills/udm-data-engineer-review/SKILL.md` with same `name:` field. The skill is for inline-applied review discipline (invoked via `Skill` tool); this AGENT is for independent reviewer-spawn pattern (invoked via `Agent` tool with `subagent_type='udm-data-engineer-review'`). Both surfaces are valid; choose by invocation context (skill for inline producer-discipline; agent for independent Gate 2 review per D55 + D56). Future readers should not conflate the two — they coexist by design.

## Future entry template

```markdown
## vX.Y.Z — YYYY-MM-DD

**Change**: <one-sentence what>

**Reason**: <one-sentence why; usually traces to a Pattern E or Pattern F retrospective finding>

**Diff**: <link to commit or paragraph-level summary of the directive change>

**Archived**: `.claude/agents/_archive/udm-data-engineer-review-vX.Y.Z-YYYY-MM-DD.md` (per D98 append-only)
```
