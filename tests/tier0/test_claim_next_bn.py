"""Tier 0 smoke tests for `tools/claim_next_bn.py` per B-562 Component A.

Per D67 — runs at build time + every commit; runtime ceiling < 5 s.
Pins atomic B-N claim CLI behavior against silent regression.

Empirical anchor: B-N collision 2026-05-19 caught by manual BACKLOG re-read
discipline (NOT git workflow). This tool eliminates the discipline dependency.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.claim_next_bn import (
    EVENT_TYPE,
    EXIT_FATAL,
    EXIT_OPERATIONAL,
    EXIT_SUCCESS,
    EXIT_WARNING,
    VALID_SEVERITIES,
    _BN_ROW_RE,
    cli_main,
    find_highest_bn,
    next_available_bn,
    open_placeholder_entry,
)


def test_module_imports() -> None:
    """Assertion 1: public surface available + D74 exit codes canonical."""
    assert callable(cli_main)
    assert callable(find_highest_bn)
    assert callable(next_available_bn)
    assert callable(open_placeholder_entry)
    assert EVENT_TYPE == "CLI_CLAIM_NEXT_BN"
    assert EXIT_SUCCESS == 0
    assert EXIT_WARNING == 1
    assert EXIT_OPERATIONAL == 2
    assert EXIT_FATAL == 3
    assert VALID_SEVERITIES == ("CRITICAL", "HIGH", "MEDIUM", "LOW")


def test_bn_row_regex_matches_canonical_formats() -> None:
    """Assertion 2: regex matches both standard + strikethrough formats per B-490."""
    content = (
        "- **B-558** (🟡 Open; HIGH; WSJF 3.5): scope\n"
        "- ~~**B-414**~~ (⚫ CLOSED): scope\n"
        "- **B-100** (🟡 Open): scope\n"
        "Random line without B-N.\n"
    )
    matches = _BN_ROW_RE.findall(content)
    assert len(matches) == 3
    captured_numbers = sorted(int(num) for _strike, num in matches)
    assert captured_numbers == [100, 414, 558]


def test_find_highest_bn_on_real_backlog() -> None:
    """Assertion 3: finds highest B-N in actual BACKLOG.md (>= 562 post-open)."""
    highest = find_highest_bn()
    assert highest >= 562, f"expected highest B-N >= 562; got {highest}"


def test_next_available_bn_returns_highest_plus_one(tmp_path: Path) -> None:
    """Assertion 4: next_available_bn returns highest + 1."""
    backlog = tmp_path / "BACKLOG.md"
    backlog.write_text(
        "- **B-100** (🟡 Open): scope\n"
        "- **B-200** (⚫ CLOSED): scope\n",
        encoding="utf-8",
    )
    assert next_available_bn(backlog) == 201


def test_find_highest_bn_defensive_cases(tmp_path: Path) -> None:
    """Assertion 5: defensive — empty/missing BACKLOG returns 0."""
    assert find_highest_bn(tmp_path / "nonexistent.md") == 0
    empty = tmp_path / "empty.md"
    empty.write_text("", encoding="utf-8")
    assert find_highest_bn(empty) == 0
    no_bn = tmp_path / "no_bn.md"
    no_bn.write_text("Some content without B-N rows.\n", encoding="utf-8")
    assert find_highest_bn(no_bn) == 0


def test_open_placeholder_dry_run_does_not_write(tmp_path: Path) -> None:
    """Assertion 6: dry_run=True returns slot WITHOUT modifying BACKLOG."""
    backlog = tmp_path / "BACKLOG.md"
    original_content = "- **B-100** (🟡 Open): scope\n"
    backlog.write_text(original_content, encoding="utf-8")
    b_n, written = open_placeholder_entry(
        backlog, scope="Test", severity="MEDIUM", wsjf=2.0, dry_run=True,
    )
    assert b_n == 101
    assert written is False
    assert backlog.read_text(encoding="utf-8") == original_content


def test_open_placeholder_apply_writes_entry(tmp_path: Path) -> None:
    """Assertion 7: dry_run=False appends placeholder entry with correct fields."""
    backlog = tmp_path / "BACKLOG.md"
    backlog.write_text("- **B-100** (🟡 Open): scope\n", encoding="utf-8")
    b_n, written = open_placeholder_entry(
        backlog, scope="Test scope description", severity="HIGH", wsjf=4.0, dry_run=False,
    )
    assert b_n == 101
    assert written is True
    new_content = backlog.read_text(encoding="utf-8")
    assert "B-101" in new_content
    assert "HIGH" in new_content
    assert "4.0" in new_content
    assert "Test scope description" in new_content
    assert "PLACEHOLDER" in new_content


def test_open_placeholder_invalid_severity_raises(tmp_path: Path) -> None:
    """Assertion 8: invalid severity raises ValueError."""
    backlog = tmp_path / "BACKLOG.md"
    backlog.write_text("- **B-100** (🟡 Open): scope\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid severity"):
        open_placeholder_entry(
            backlog, scope="Test", severity="INVALID", wsjf=2.0, dry_run=True,
        )
