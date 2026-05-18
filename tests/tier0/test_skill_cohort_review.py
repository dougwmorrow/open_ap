"""Tier 0 build-time smoke tests for `.claude/skills/udm-cohort-review/SKILL.md`.

Per D67 — runs at build time + every commit; runtime ceiling < 5 s; no DB / network.

Pins the canonical content of the udm-cohort-review SKILL.md against silent regression.
Authored 2026-05-18 per B-483 closure (cross-cohort review discipline layer; empirical
anchor: cross-cohort reviewer aa320fb75f55a5471 surfaced 3 🔴 + 2 NEW B-Ns across
ccf21a2 + 133b212 + 9983bee cohort that 3 prior single-commit reviewers missed).

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

SKILL_NAME = "udm-cohort-review"
SKILL_PATH = get_skill_path(SKILL_NAME)

# Baseline fixture + 2 baseline tests via factory calls per B-461 pattern
skill_content = make_skill_content_fixture(SKILL_NAME)
test_skill_file_exists = make_baseline_test_skill_exists(SKILL_NAME)
test_frontmatter_name = make_baseline_test_frontmatter_name(SKILL_NAME)


def test_required_section_headers_present(skill_content: str) -> None:
    """B-483 Assertion 3: required section headers present for skill protocol."""
    assert_skill_contains_substrings(
        skill_content,
        [
            "## When to invoke",
            "## Anti-triggers",
            "## The 6-scope procedure",
            "## Output contract",
            "## Composition with other skills",
            "## Edge cases",
        ],
        hint="Canonical skill structure per .claude/skills/udm-*/SKILL.md pattern",
    )


def test_six_scope_procedure_headers_present(skill_content: str) -> None:
    """B-483 Assertion 4: all 6 scope headers (§1 through §6) present in procedure
    section. These are canonical scopes mirroring the empirical-anchor reviewer
    aa320fb75f55a5471 prompt at 2026-05-18."""
    assert_skill_contains_substrings(
        skill_content,
        [
            "### §1 — Compositional integrity",
            "### §2 — New B-N quality assessment",
            "### §3 — Test coverage adequacy",
            "### §4 — Discipline-drift recurrence",
            "### §5 — Architectural debt assessment",
            "### §6 — Cross-doc consistency final sweep",
        ],
        hint="6-scope procedure canonical per B-483 closure 2026-05-18",
    )


def test_trigger_phrases_section_enumerates_canonical_phrases(skill_content: str) -> None:
    """B-483 Assertion 5: trigger-phrase section enumerates at least 4 canonical
    user-invokable phrases. Pins the canonical trigger set against silent removal."""
    assert_skill_contains_substrings(
        skill_content,
        [
            "cross-cohort review",
            "review the recent enhancements",
            "audit the cohort",
            "check across commits",
        ],
        hint="≥4 canonical trigger phrases per B-483 spec",
    )


def test_empirical_anchor_aa320fb75f55a5471_cited(skill_content: str) -> None:
    """B-483 Assertion 6: empirical-anchor agent ID + cohort commits cited
    (forensic-audit pin against accidental removal of the 1-event evidence base)."""
    assert_skill_contains_substrings(
        skill_content,
        [
            "aa320fb75f55a5471",
            "ccf21a2",
            "133b212",
            "9983bee",
        ],
        hint="1-event empirical anchor 2026-05-18 (cross-cohort review of "
             "Mechanism C-1 commit-msg cohort)",
    )


def test_composition_table_includes_existing_skills(skill_content: str) -> None:
    """B-483 Assertion 7: composition section references the 3 complementary
    review-discipline skills (udm-gap-check per-commit + udm-design-reviewer
    substrate-edit + udm-cascade-auditor round-level Pattern F)."""
    assert_skill_contains_substrings(
        skill_content,
        [
            "udm-gap-check",
            "udm-design-reviewer",
            "udm-cascade-auditor",
            "Pattern F",
        ],
        hint="Composition table per B-483 spec — complementary review layers",
    )


def test_six_failure_mode_classes_enumerated(skill_content: str) -> None:
    """B-483 Assertion 8: 6 failure-mode classes ONLY visible cross-cohort
    enumerated in 'Why this skill exists' section (matches §1-§6 scope mapping)."""
    assert_skill_contains_substrings(
        skill_content,
        [
            "Compositional drift",
            "Test-coverage gap interactions",
            "Architectural fragmentation accumulation",
            "Cumulative arithmetic propagation drift",
            "Stale forward-references post-cohort",
            "New-B-N calibration drift",
        ],
        hint="6 failure-mode classes canonical per B-483 spec; mirrors §1-§6 scopes",
    )


def test_output_contract_verdict_template_present(skill_content: str) -> None:
    """B-483 Assertion 9: output contract section includes the canonical verdict
    template with ✅ CLEAN / 🟡 ISSUES / 🔴 BLOCKERS three-tier ladder."""
    assert_skill_contains_substrings(
        skill_content,
        [
            "Cross-cohort review verdict",
            "✅ CLEAN",
            "🟡 ISSUES",
            "🔴 BLOCKERS",
            "Final verdict",
        ],
        hint="Verdict template canonical per B-483 spec",
    )


def test_anti_trigger_section_warns_against_overlap(skill_content: str) -> None:
    """B-483 Assertion 10: anti-trigger section explicitly warns against
    invoking when the request maps to other layers (single-commit / round-level)."""
    assert_skill_contains_substrings(
        skill_content,
        [
            "single commit",
            "round close-out",
        ],
        hint="Anti-trigger warns against overlap with single-commit / round-level "
             "review layers per B-483 spec",
    )
