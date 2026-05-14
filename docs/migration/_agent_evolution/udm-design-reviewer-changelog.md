# udm-design-reviewer changelog

Per-agent semver changelog per D98 (Round 8 close-out semver discipline). Append-only. Each entry corresponds to one `udm-agent-prompt-versioner` skill invocation applying a user-approved delta from `udm-specialty-tuner` / `udm-subclass-accumulator` / `udm-producer-checklist-evolver` / `udm-cascade-audit-evolver`.

Format per entry:
- Version header (`## vMAJOR.MINOR.PATCH — YYYY-MM-DD`)
- Source skill + approval metadata
- Change type (MAJOR / MINOR / PATCH)
- Delta body summary
- Rationale (typically quoting empirical evidence)
- Test status + reversibility note

---

## v1.1.0 — 2026-05-14

**Source**: `udm-producer-checklist-evolver` Round 4 close-out proposal (DELTA-B2) accepted by user (`dougwmorrow`) 2026-05-14
**Change type**: MINOR (directive addition — new mandatory specialty slot; no structural change to existing prompt body sections)
**Delta**:
- Section ADDED: "Gate 2 Mandatory Specialty: Canonical-spec verbatim citation (Step 11 elevation per B-258 / 10-event evidence base 2026-05-14)"
- Frontmatter ADDED: `version: v1.1.0`, `last_updated: 2026-05-14`, `changelog: docs/migration/_agent_evolution/udm-design-reviewer-changelog.md`
- Body changes: NONE to existing sections (Operating model / Risk-surfacing / Backlog-surfacing / Review checklist / Output format / Anti-patterns / When NOT to use / Concrete example all unchanged)

**Rationale**: B-258 close — promote Step 11 (canonical-spec verbatim citation) from per-cycle producer self-check directive to Gate 2 mandatory reviewer specialty. Empirical evidence base = **10 events / 2 rounds / 100% producer-side success rate**:
- Round 3 (4 events): M17 + M8 + M12 + M13 task-prompt-vs-spec drift catches per DELTA-A2 / Pitfall #9.l extension
- Round 4 (6 events): § 3.1 + § 3.2 + § 3.3 + § 3.4 + § 3.5 + § 3.7 build cohort canonical-vs-brief signature drift catches at Round 4.1 + Wave 4.6

Crosses both `udm-producer-checklist-evolver` thresholds (≥3-events-≥2-rounds → 🟡 REFINE; ≥5-events-≥3-rounds → 🔴 mandatory specialty elevation). Skill SI7 edge case applies: "if a sub-class has 5+ producer-missable instances AND the existing directive is already comprehensive (4-5 steps), propose ELEVATION to Gate 2 mandatory specialty rather than directive strengthening."

Producer Gate 1 retention preserved (defense-in-depth) — existing HANDOFF §8 Step 11 producer self-check directive (added 2026-05-14 via DELTA-A4) stays in place. This delta adds the reviewer-side mandate as Gate 2 mandatory specialty.

**Tested at**: Round 4 close-out cascade 2026-05-14 — Pattern F skipped per user direction Option-A (defer until Phase 2 R1 when B81 + B82 unblock to bring Round 4 to 11/11). No regression baseline yet — first invocation under v1.1.0 is at Round 5 (Tests) kickoff.

**Reversible**: yes — prior `v1.0.0` archived at `.claude/agents/_archive/udm-design-reviewer-v1.0.0-2026-05-14.md` (byte-identical to HEAD pre-delta). Rollback procedure per `udm-agent-prompt-versioner` SKILL.md auto-revert section: if Round 5+ surfaces regression in canonical-spec citation reviews (e.g., reviewer over-flagging trivial line-anchor diffs as 🔴, or false-negative drift on semantic-vs-signature distinction), invoke versioner with rollback mode; copy archive back to `.claude/agents/udm-design-reviewer.md`; append revert entry to this changelog.

**Cross-references**:
- B-258 (`docs/migration/BACKLOG.md` L390) — closed via this delta application
- HANDOFF §8 Step 11 — producer self-check directive (added 2026-05-14 via DELTA-A4)
- Pitfall #9.l — canonical-schema-detail working-memory drift (sub-class accumulator basis)
- `.claude/agents/_archive/udm-design-reviewer-v1.0.0-2026-05-14.md` — prior version
- `docs/migration/_validation_log.md` 2026-05-14 entry — Round 4 close-out cascade delta application
- D95 / D98 (close-out skill suite + semver discipline — Round 8 D99 convergence lock)
