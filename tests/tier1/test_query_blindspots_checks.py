"""Tier 1 tests for the 4 Phase 1 blindspot check functions in query_blindspots.py.

Covers:
- check_9j_b_item_status_render: badge vs inline annotation mismatch
- check_9o_recursive_exemption: phrase + termination-citation absence
- check_9n_convention_registration: new public surface in source files
- check_9h_off_by_n_line_citation: large/inverted L-range citations

Plus query_blindspots() end-to-end behavior with synthetic content.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# 9j — B-item status-render discipline
# ---------------------------------------------------------------------------

def test_9j_detects_stale_open_badge_with_closed_inline():
    from tools.query_blindspots import check_9j_b_item_status_render
    content = (
        "- **B270** (🟡 Open): Some description. **CLOSED 2026-05-15** "
        "via mechanism X.\n"
    )
    matches = check_9j_b_item_status_render(content, "BACKLOG.md")
    assert len(matches) == 1
    assert matches[0].entry_id == "9j-b-item-status-render-discipline"
    assert matches[0].severity == "p2"
    assert "B270" in matches[0].diagnostic


def test_9j_no_match_when_badge_matches_annotation():
    from tools.query_blindspots import check_9j_b_item_status_render
    content = "- **B270** (⚫ Closed): Some description. **CLOSED 2026-05-15**\n"
    matches = check_9j_b_item_status_render(content, "BACKLOG.md")
    assert matches == []


def test_9j_no_match_open_without_inline_closed():
    from tools.query_blindspots import check_9j_b_item_status_render
    content = "- **B271** (🟡 Open): Description; no closure yet.\n"
    matches = check_9j_b_item_status_render(content, "BACKLOG.md")
    assert matches == []


def test_9j_detects_hyphenated_b_n_format():
    """B-295 sub-item 8: hyphenated `**B-294**` format must be caught."""
    from tools.query_blindspots import check_9j_b_item_status_render
    content = "- **B-294** (🟡 Open): Description. **CLOSED 2026-05-16** via X.\n"
    matches = check_9j_b_item_status_render(content, "BACKLOG.md")
    assert len(matches) == 1
    assert "B294" in matches[0].diagnostic


def test_9j_skips_strikethrough_wrapped_entries():
    """B-295 sub-item 8: strikethrough-wrapped lines are already-rendered-closed."""
    from tools.query_blindspots import check_9j_b_item_status_render
    content = "- ~~**B-280** (🟡 Open)~~ description. **CLOSED 2026-05-16** via X.\n"
    matches = check_9j_b_item_status_render(content, "BACKLOG.md")
    assert matches == []


def test_9j_skips_double_tilde_at_start():
    """Lines beginning with ~~ are skipped regardless of where badge sits."""
    from tools.query_blindspots import check_9j_b_item_status_render
    content = "~~- **B999** (🟡 Open) inside strikethrough~~. **CLOSED 2026-05-16**\n"
    matches = check_9j_b_item_status_render(content, "BACKLOG.md")
    assert matches == []


# ---------------------------------------------------------------------------
# 9o — Recursive-exemption rationalization
# ---------------------------------------------------------------------------

def test_9o_detects_triple_counted_review_without_termination():
    from tools.query_blindspots import check_9o_recursive_exemption
    content = (
        "Cascade application: triple-counted review via Gate 2 + paired-judgment.\n"
        "No further gap-check needed.\n"
    )
    matches = check_9o_recursive_exemption(content, "COMMIT_MSG")
    assert len(matches) >= 1
    assert matches[0].entry_id == "9o-recursive-exemption-rationalization"
    assert matches[0].severity == "p0"


def test_9o_no_match_when_termination_cited():
    from tools.query_blindspots import check_9o_recursive_exemption
    content = (
        "Recursive exemption: this is a Layer N+1 termination per CLAUDE.md "
        "hard rule 14. 4-step pre-commit verification confirmed.\n"
    )
    matches = check_9o_recursive_exemption(content, "COMMIT_MSG")
    assert matches == []


def test_9o_detects_by_analogy_phrase():
    from tools.query_blindspots import check_9o_recursive_exemption
    content = "Applying D111 process-infra exemption by analogy without formal extension.\n"
    matches = check_9o_recursive_exemption(content, "COMMIT_MSG")
    assert len(matches) >= 1


def test_9o_suppresses_in_b_item_descriptive_block():
    """B-295 sub-item 9: 9.o phrases inside B-N item bullets in BACKLOG are descriptive."""
    from tools.query_blindspots import check_9o_recursive_exemption
    content = (
        "- **B-292** (🟡 Open; HIGH; WSJF 3.0): **Formally extend D111 exempt-class** — "
        "D62 amendment applied D111 exemption by analogy — reasonable but undocumented.\n"
    )
    matches = check_9o_recursive_exemption(content, "docs/migration/BACKLOG.md")
    assert matches == []


def test_9o_fires_in_commit_message_outside_doc():
    """9.o phrases in commit messages (non-descriptive-context paths) still fire."""
    from tools.query_blindspots import check_9o_recursive_exemption
    content = "Applied D111 exemption by analogy. Cascade exempt per recursive coverage.\n"
    matches = check_9o_recursive_exemption(content, "COMMIT_MSG")
    assert len(matches) >= 1


def test_9o_fires_outside_item_bullet_even_in_descriptive_doc():
    """9.o phrase in BACKLOG narrative outside any B-N bullet still fires."""
    from tools.query_blindspots import check_9o_recursive_exemption
    content = (
        "# Backlog\n"
        "\n"
        "We're applying D111 by analogy to D62 amendments. This is the methodology.\n"
        "\n"
        "## Methodology\n"
        "Section header.\n"
    )
    matches = check_9o_recursive_exemption(content, "docs/migration/BACKLOG.md")
    assert len(matches) >= 1


def test_9o_suppresses_inside_d_item_block():
    """D-N item bullets in 03_DECISIONS also suppress as descriptive context."""
    from tools.query_blindspots import check_9o_recursive_exemption
    content = (
        "- **D113** Process-infra exemption — applying CCL discipline by analogy is permitted.\n"
    )
    matches = check_9o_recursive_exemption(content, "docs/migration/03_DECISIONS.md")
    assert matches == []


# ---------------------------------------------------------------------------
# 9n — Convention registration not applied to new build artifacts
# ---------------------------------------------------------------------------

def test_9n_detects_new_public_function_in_tools_dir():
    from tools.query_blindspots import check_9n_convention_registration
    content = (
        "def public_function(arg):\n"
        "    return arg\n\n"
        "def _private_helper(arg):\n"
        "    return arg\n"
    )
    matches = check_9n_convention_registration(content, "tools/new_tool.py")
    assert len(matches) == 1
    assert matches[0].entry_id == "9n-convention-registration-not-applied-to-new-build-artifacts"


def test_9n_detects_public_class_and_constant():
    from tools.query_blindspots import check_9n_convention_registration
    content = (
        "EVENT_TYPE = 'CLI_NEW'\n"
        "EXIT_SUCCESS = 0\n\n"
        "class PublicClass:\n"
        "    pass\n"
    )
    matches = check_9n_convention_registration(content, "tools/new_tool.py")
    assert len(matches) == 1
    assert "PublicClass" in matches[0].snippet or "EVENT_TYPE" in matches[0].snippet


def test_9n_skips_test_files():
    from tools.query_blindspots import check_9n_convention_registration
    content = "def test_new_thing():\n    assert True\n"
    matches = check_9n_convention_registration(content, "tests/tier0/test_new.py")
    assert matches == []


def test_9n_skips_non_source_dirs():
    from tools.query_blindspots import check_9n_convention_registration
    content = "def some_function():\n    pass\n"
    matches = check_9n_convention_registration(content, "docs/migration/scratch.py")
    assert matches == []


def test_9n_skips_underscore_prefixed_only():
    from tools.query_blindspots import check_9n_convention_registration
    content = "def _helper():\n    pass\n\ndef _another():\n    pass\n"
    matches = check_9n_convention_registration(content, "tools/private_only.py")
    assert matches == []


# ---------------------------------------------------------------------------
# 9h — Off-by-N line citation
# ---------------------------------------------------------------------------

def test_9h_detects_large_l_range():
    from tools.query_blindspots import check_9h_off_by_n_line_citation
    content = "Per spec L100-L500 the procedure must...\n"
    matches = check_9h_off_by_n_line_citation(content, "runbook.md")
    assert len(matches) == 1
    assert matches[0].entry_id == "9h-wrong-section-number-invented-description"


def test_9h_no_match_small_range():
    from tools.query_blindspots import check_9h_off_by_n_line_citation
    content = "Per spec L100-L105 the procedure must...\n"
    matches = check_9h_off_by_n_line_citation(content, "runbook.md")
    assert matches == []


def test_9h_detects_inverted_range():
    from tools.query_blindspots import check_9h_off_by_n_line_citation
    content = "Per spec L500-L100 the procedure must...\n"
    matches = check_9h_off_by_n_line_citation(content, "runbook.md")
    assert len(matches) == 1


# ---------------------------------------------------------------------------
# query_blindspots() end-to-end
# ---------------------------------------------------------------------------

def test_query_blindspots_with_synthetic_file(tmp_path):
    from tools.query_blindspots import query_blindspots, EXIT_WARNING
    test_file = tmp_path / "BACKLOG.md"
    test_file.write_text(
        "- **B999** (\U0001f7e1 Open): Test. **CLOSED 2026-05-16** via test.\n",
        encoding="utf-8",
    )
    report = query_blindspots(files=[str(test_file)])
    assert report.exit_code == EXIT_WARNING
    assert len(report.matches) >= 1
    assert any("9j" in m.entry_id for m in report.matches)


def test_query_blindspots_severity_filter(tmp_path):
    from tools.query_blindspots import query_blindspots
    test_file = tmp_path / "BACKLOG.md"
    test_file.write_text(
        "- **B999** (\U0001f7e1 Open): Test. **CLOSED 2026-05-16** via test.\n",
        encoding="utf-8",
    )
    report = query_blindspots(files=[str(test_file)], severity_filter=["p0"])
    assert all(m.severity == "p0" for m in report.matches)


def test_query_blindspots_live_mode_p0_exits_2(tmp_path):
    from tools.query_blindspots import query_blindspots, EXIT_OPERATIONAL_FAILURE
    test_file = tmp_path / "COMMIT_MSG"
    test_file.write_text(
        "Cascade complete. Triple-counted review covers all gaps.\n"
        "No further gap-check needed.\n"
    )
    report = query_blindspots(files=[str(test_file)], live=True)
    assert report.exit_code == EXIT_OPERATIONAL_FAILURE


def test_query_blindspots_tag_filter(tmp_path):
    from tools.query_blindspots import query_blindspots
    test_file = tmp_path / "BACKLOG.md"
    test_file.write_text(
        "- **B999** (\U0001f7e1 Open): Test. **CLOSED 2026-05-16** via test.\n",
        encoding="utf-8",
    )
    report = query_blindspots(files=[str(test_file)], tag_filter=["b-item"])
    assert any("9j" in m.entry_id for m in report.matches)
