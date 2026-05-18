"""Tier 0 regression test for CLAUDE.md L437 + HANDOFF.md §8 Pitfall #9.l extensions.

Per D67 — runs at build time + every commit; runtime ceiling < 5 s; no DB / network.

Pins the LOAD-BEARING canonical text for the Pitfall #9.l cohort-attribution
metadata sub-class extension that was added via B-450 closure (2026-05-17). The
discipline extension covers cohort-attribution metadata working-memory drift —
the 1st-event empirical anchor is commit `e76078c` where B-409/B-414 cohort
attributions were cited as CB-7-A/CB-7-B against canonical CB-4-C/CB-6-E.

Both target areas (CLAUDE.md L437 EXTENDED sub-clause + HANDOFF.md §8 Pitfall
#9.l Step 8 region) are LOAD-BEARING for forward-prevention. If silently
removed during a future refactor, the discipline regression is undetectable
WITHOUT a regression test.

Closes B-456 per Agent 64 G4 test coverage gap surface.

This file's assertions cover:
  - CLAUDE.md L437 area contains "EXTENDED 2026-05-17 per B-450 closure" literal
  - CLAUDE.md L437 area cites cohort attribution keywords + agent IDs + commit
    hashes + B-N closure mechanisms
  - HANDOFF.md §8 Pitfall #9.l Step 8 region contains canonical metadata
    extension text covering the same scope
  - Both files cite B-450 closure as the discipline anchor
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CLAUDE_MD_PATH = REPO_ROOT / "CLAUDE.md"
HANDOFF_MD_PATH = REPO_ROOT / "docs" / "migration" / "HANDOFF.md"


@pytest.fixture(scope="module")
def claude_md_content() -> str:
    """Load CLAUDE.md content once per module run."""
    assert CLAUDE_MD_PATH.is_file(), f"CLAUDE.md not found at {CLAUDE_MD_PATH}"
    return CLAUDE_MD_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def handoff_md_content() -> str:
    """Load HANDOFF.md content once per module run."""
    assert HANDOFF_MD_PATH.is_file(), f"HANDOFF.md not found at {HANDOFF_MD_PATH}"
    return HANDOFF_MD_PATH.read_text(encoding="utf-8")


def test_claude_md_l437_extended_clause_present(claude_md_content: str) -> None:
    """Assertion 1: CLAUDE.md L437 area contains the literal `EXTENDED 2026-05-17 per B-450 closure` substring.

    Pins the B-450 closure anchor — if the extension is silently removed during
    a future refactor, this regression test catches the discipline drift.
    """
    assert "EXTENDED 2026-05-17 per B-450 closure" in claude_md_content, (
        "CLAUDE.md must retain the literal 'EXTENDED 2026-05-17 per B-450 closure' "
        "sub-clause anchoring the Pitfall #9.l cohort-attribution metadata extension. "
        "If this assertion fails, a refactor silently removed the load-bearing anchor."
    )


def test_claude_md_l437_extended_clause_covers_cohort_attribution_metadata(
    claude_md_content: str,
) -> None:
    """Assertion 2: CLAUDE.md L437 EXTENDED sub-clause cites the canonical metadata-extension scope keywords.

    Verifies the extension scope covers cohort attributions + agent IDs + commit
    hashes + B-N closure mechanisms (the canonical 4-element scope per B-450 closure).
    """
    # The full canonical extension scope phrase from CLAUDE.md L437
    canonical_scope_phrase = (
        "cohort attributions + agent IDs + commit hashes + B-N closure mechanisms"
    )
    assert canonical_scope_phrase in claude_md_content, (
        f"CLAUDE.md must enumerate the 4-element canonical extension scope: "
        f"'{canonical_scope_phrase}'. Missing this enumeration weakens the Pitfall "
        f"#9.l extension semantics."
    )
    # Verify the EXTENDED sub-clause specifically cites Step 8 directive scope extension
    assert "Step 8 directive scope" in claude_md_content, (
        "CLAUDE.md must cite the 'Step 8 directive scope' extension (the directive "
        "now extends from 'canonical DDL' to 'canonical metadata')."
    )


def test_handoff_section_8_pitfall_9l_step_8_extension_present(
    handoff_md_content: str,
) -> None:
    """Assertion 3: HANDOFF.md §8 Pitfall #9.l Step 8 region contains the canonical metadata extension text.

    Pins the B-450 closure anchor + the canonical 4-element scope at the §8
    Pitfall #9.l region. The directive scope must be expanded to BOTH canonical
    DDL columns AND canonical metadata fields per the closure.
    """
    # Anchor 1: B-450 closure citation in HANDOFF.md
    assert "EXTENDED 2026-05-17 per B-450 closure" in handoff_md_content, (
        "HANDOFF.md must retain the literal 'EXTENDED 2026-05-17 per B-450 closure' "
        "sub-clause anchoring the Pitfall #9.l cohort-attribution metadata extension."
    )
    # Anchor 2: empirical anchor commit `e76078c` (1st-event evidence for the sub-class)
    assert "e76078c" in handoff_md_content, (
        "HANDOFF.md must cite the empirical anchor commit `e76078c` as the 1st-event "
        "evidence for the cohort-attribution-metadata sub-class."
    )
    # Anchor 3: canonical metadata scope enumeration matches CLAUDE.md
    canonical_scope_phrase = (
        "cohort attributions + agent IDs + commit hashes + B-N closure mechanisms"
    )
    assert canonical_scope_phrase in handoff_md_content, (
        f"HANDOFF.md §8 Pitfall #9.l Step 8 region must enumerate the 4-element "
        f"canonical extension scope: '{canonical_scope_phrase}'."
    )
    # Anchor 4: Step 8 directive scope expanded — canonical DDL AND canonical metadata
    assert "Step 8 directive scope expanded" in handoff_md_content, (
        "HANDOFF.md must explicitly cite 'Step 8 directive scope expanded' to record "
        "the canonical-re-read precondition extension."
    )


def test_pitfall_9l_extension_cites_b450_closure_in_both_files(
    claude_md_content: str, handoff_md_content: str,
) -> None:
    """Assertion 4: Both CLAUDE.md and HANDOFF.md cite B-450 closure as the discipline anchor.

    Cross-file consistency check — the B-450 closure anchor must be present in
    BOTH canonical locations so that future cross-doc cascade audits can verify
    parallel state.
    """
    # B-450 closure must be cited in both files at the Pitfall #9.l extension point
    claude_b450_count = claude_md_content.count("B-450 closure")
    handoff_b450_count = handoff_md_content.count("B-450 closure")
    assert claude_b450_count >= 1, (
        f"CLAUDE.md must cite 'B-450 closure' at least once (found {claude_b450_count})."
    )
    assert handoff_b450_count >= 1, (
        f"HANDOFF.md must cite 'B-450 closure' at least once (found {handoff_b450_count})."
    )
