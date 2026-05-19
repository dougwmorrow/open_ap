"""Tier 0 build-time smoke tests for `.claude/skills/udm-session-compactor/SKILL.md`.

Per D67 — runs at build time + every commit; runtime ceiling < 5 s; no DB / network.

Pins the canonical content of the udm-session-compactor SKILL.md against silent
regression. Authored 2026-05-18 per B-492 closure (Phase 1 manual-trigger session-
state compression discipline layer; empirical anchor: this session compaction +
SESSION_RESUME.md insufficiency surfaced by gap-check reviewer ab45539c33d1cebd1
G2 finding; claude-code-guide research established Phase 2 token-tracking deferred
due to hooks lacking Claude Code token-count access per anthropics/claude-code#34340).

Uses the B-461 _skill_test_base.py factory pattern (baseline tests via factories;
skill-specific assertions on top).
"""
from __future__ import annotations

from tests.tier0._skill_test_base import (
    assert_skill_contains_substrings,
    get_skill_path,
    make_baseline_test_frontmatter_name,
    make_baseline_test_skill_exists,
    make_skill_content_fixture,
)

SKILL_NAME = "udm-session-compactor"
SKILL_PATH = get_skill_path(SKILL_NAME)

# Baseline fixture + 2 baseline tests via factory calls per B-461 pattern
skill_content = make_skill_content_fixture(SKILL_NAME)
test_skill_file_exists = make_baseline_test_skill_exists(SKILL_NAME)
test_frontmatter_name = make_baseline_test_frontmatter_name(SKILL_NAME)


def test_required_section_headers_present(skill_content: str) -> None:
    """B-492 Assertion 3: required canonical section headers present for skill protocol."""
    assert_skill_contains_substrings(
        skill_content,
        [
            "## Why this skill exists",
            "## When to invoke",
            "## Anti-triggers",
            "## The 5-section snapshot procedure",
            "## Output contract",
            "## Edge cases",
            "## Composition with other skills",
            "## Phase 1 vs Phase 2 scope",
            "## Tier 0 stub",
            "## Cross-references",
            "## Changelog",
        ],
        hint="Canonical skill structure per .claude/skills/udm-*/SKILL.md pattern + Phase 1/2 scope discipline",
    )


def test_five_canonical_snapshot_sections_present(skill_content: str) -> None:
    """B-492 Assertion 4: all 5 canonical snapshot sections (§1-§5) enumerated in skill body.

    These are the canonical sections the snapshot artifact at
    `docs/migration/_session_snapshots/<date>-<commit>.md` MUST contain per output
    contract. Skill body documents them as the procedure spec.
    """
    assert_skill_contains_substrings(
        skill_content,
        [
            "### §1 — Active work context",
            "### §2 — Completed deliverables",
            "### §3 — Open runway",
            "### §4 — Deeper insights",
            "### §5 — Pointer-back cross-refs",
        ],
        hint="5-section canonical snapshot structure must be documented in skill body for producer-side discipline pin",
    )


def test_composition_table_includes_canonical_composers(skill_content: str) -> None:
    """B-492 Assertion 5: composition table includes all 5 canonical composer surfaces.

    The skill explicitly composes with `udm-progress-logger` (per-completion) +
    `udm-cohort-review` (cross-cohort) + `udm-round-closeout` (round-aggregate) +
    `udm-gap-check` (snapshot completeness verifier) + `SESSION_RESUME.md` (lightweight
    pointer the snapshot AUGMENTS). Pinning these explicitly prevents composition-drift
    where a future agent forgets one layer.
    """
    assert_skill_contains_substrings(
        skill_content,
        [
            "udm-progress-logger",
            "udm-cohort-review",
            "udm-round-closeout",
            "udm-gap-check",
            "SESSION_RESUME.md",
        ],
        hint="Canonical 5-composer surface set must be enumerated in Composition table",
    )


def test_phase_1_vs_phase_2_scope_documented(skill_content: str) -> None:
    """B-492 Assertion 6: Phase 1 (current) vs Phase 2 (deferred) scope discipline.

    Phase 1 = manual-trigger only; Phase 2 = token-tracking subsystem deferred per
    claude-code-guide research 2026-05-18 finding that Claude Code hooks cannot
    access token counts (anthropics/claude-code#34340 feature request).
    """
    assert_skill_contains_substrings(
        skill_content,
        [
            "Phase 1 (current",
            "Phase 2 (deferred",
            "anthropics/claude-code#34340",
            "Token Counting API",
        ],
        hint="Phase 1/2 scope discipline + claude-code-guide research provenance must be pinned",
    )


def test_output_contract_pins_canonical_snapshot_path(skill_content: str) -> None:
    """B-492 Assertion 7: output contract pins canonical snapshot file path format.

    Snapshot artifacts MUST live at `docs/migration/_session_snapshots/<YYYY-MM-DD>-
    <commit-hash-prefix-7>.md` — pinning the canonical path prevents future
    snapshot-location drift.
    """
    assert_skill_contains_substrings(
        skill_content,
        [
            "docs/migration/_session_snapshots/",
            "YYYY-MM-DD",
            "commit-hash-prefix-7",
        ],
        hint="Canonical snapshot path format MUST be pinned in output contract section",
    )


def test_trim_policy_taxonomy_present(skill_content: str) -> None:
    """B-495-class Assertion 9 (added 2026-05-18 per research Rec 1): trim-policy
    taxonomy distinguishing regenerable vs irreplaceable content present in skill body.

    Per `_research/llm-handoffs-traceability-hallucination-2026-05-18.md` Finding 1.1
    (CMV paper, Imperial College London 2026): naive compaction destroys ~98% of
    nuanced reasoning while preserving surface summary. Trim-policy taxonomy is the
    load-bearing distinction for preserving context across compaction.
    """
    assert_skill_contains_substrings(
        skill_content,
        [
            "Content durability",
            "regenerable vs irreplaceable",
            "Regenerable content",
            "Irreplaceable content",
            "Trim-policy enforcement",
            "Empirical anchor for trim-policy",
        ],
        hint="Trim-policy taxonomy must be documented per research recommendation 2026-05-18",
    )


def test_trim_policy_cites_cmv_research_anchor(skill_content: str) -> None:
    """B-495-class Assertion 10 (added 2026-05-18 per research Rec 1): trim-policy
    taxonomy cites the CMV research artifact + Imperial College London + ab45539c33d1cebd1
    empirical anchor. Forward-prevention against drift over time.
    """
    assert_skill_contains_substrings(
        skill_content,
        [
            "_research/llm-handoffs-traceability-hallucination-2026-05-18.md",
            "Imperial College London",
            "ab45539c33d1cebd1",
        ],
        hint="Trim-policy section must cite research artifact + empirical anchor",
    )


def test_empirical_anchor_cited(skill_content: str) -> None:
    """B-492 Assertion 8: empirical anchor 1-event evidence base cited.

    The skill exists because of a specific empirical event: this session's
    compaction + SESSION_RESUME.md proving insufficient (cumulative-count drift
    surfaced by gap-check reviewer ab45539c33d1cebd1 G2 finding).
    """
    assert_skill_contains_substrings(
        skill_content,
        [
            "1-event",
            "ab45539c33d1cebd1",
            "SESSION_RESUME.md proved insufficient",
        ],
        hint="Empirical anchor citation prevents 'why does this skill exist' drift over time",
    )
