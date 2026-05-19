"""Tier 0 build-time smoke tests for `tools/anchor_context.py`.

Per D67 — runs at build time + every commit; runtime ceiling < 5 s; no DB / network.

Pins canonical content + behavior of the shared empirical-anchor context detection
helper extracted at B-491 + B-496 bundled closure 2026-05-18 (from
`tools/check_commit_msg.py` B-488 original closure).

The helper enables suppression of false-positive WARNs in heuristic checks when
the matching content cites historical pattern instances rather than asserting
current-commit claims.
"""
from __future__ import annotations

from tools.anchor_context import (
    EMPIRICAL_ANCHOR_MARKERS,
    is_empirical_anchor_context,
)


def test_module_exports() -> None:
    """B-491+B-496 Assertion 1: module exports canonical surface."""
    assert isinstance(EMPIRICAL_ANCHOR_MARKERS, tuple)
    assert callable(is_empirical_anchor_context)


def test_canonical_18_marker_set() -> None:
    """B-491+B-496 Assertion 2: canonical 18-marker set preserved per B-488 closure.

    Pins forward-extensibility — new markers may be APPENDED but not removed
    (would break back-compat with existing call sites in check_commit_msg.py).
    """
    assert len(EMPIRICAL_ANCHOR_MARKERS) >= 18
    # Canonical anchors that MUST be present
    for canonical_marker in (
        "empirical anchor commit",
        "META-IRONY",
        "1st-event",
        "historical reference",
        "Quote-cite from reviewer",
        "Mechanism A step 5",
    ):
        assert canonical_marker in EMPIRICAL_ANCHOR_MARKERS, (
            f"canonical marker {canonical_marker!r} missing"
        )


def test_detects_marker_on_target_line() -> None:
    """B-491+B-496 Assertion 3: returns True when marker is on the target line."""
    lines = ["context-prelude", "Per empirical anchor commit `abc123`, the pattern fired"]
    assert is_empirical_anchor_context(lines, idx=1) is True


def test_detects_marker_within_5line_lookback() -> None:
    """B-491+B-496 Assertion 4: returns True for 5-line lookback window."""
    lines = [
        "Earlier 2026-05-18 (META-IRONY citation):",
        "Detail line 1",
        "Detail line 2",
        "Detail line 3",
        "Detail line 4",
        "Target line citing `path/to/file.py`",
    ]
    # idx=5 should match marker at idx=0 (5-line lookback default)
    assert is_empirical_anchor_context(lines, idx=5) is True


def test_returns_false_outside_lookback_window() -> None:
    """B-491+B-496 Assertion 5: returns False when marker is beyond lookback window.

    Marker at idx=0, target at idx=6 — outside default 5-line lookback.
    """
    lines = [
        "Earlier 2026-05-18 (META-IRONY citation):",
        "Detail line 1",
        "Detail line 2",
        "Detail line 3",
        "Detail line 4",
        "Detail line 5",
        "Target line citing `path/to/file.py`",
    ]
    assert is_empirical_anchor_context(lines, idx=6) is False


def test_returns_false_when_no_marker_present() -> None:
    """B-491+B-496 Assertion 6: returns False when no marker in any line."""
    lines = [
        "Normal narrative content",
        "More normal content",
        "Target line citing `path/to/file.py`",
    ]
    assert is_empirical_anchor_context(lines, idx=2) is False


def test_invalid_idx_returns_false() -> None:
    """B-491+B-496 Assertion 7: defensive — negative or out-of-bounds idx returns False."""
    lines = ["line 0", "META-IRONY", "line 2"]
    assert is_empirical_anchor_context(lines, idx=-1) is False
    assert is_empirical_anchor_context(lines, idx=99) is False


def test_custom_lookback_window() -> None:
    """B-491+B-496 Assertion 8: lookback parameter is configurable."""
    lines = [
        "META-IRONY citation",
        "Detail 1",
        "Detail 2",
        "Target line",
    ]
    # idx=3 with lookback=2 should NOT find marker at idx=0
    assert is_empirical_anchor_context(lines, idx=3, lookback=2) is False
    # idx=3 with lookback=3 should find marker at idx=0
    assert is_empirical_anchor_context(lines, idx=3, lookback=3) is True
