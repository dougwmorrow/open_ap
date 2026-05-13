"""Tests for the per-table extraction-guard override
(``UdmTablesList.MaxRowsPerDay`` → ``check_extraction_guard(
max_rows_per_day_override=...)``).

The override exists for tables that grew dramatically over time —
e.g. CARDTXN went from ~500 rows/day in 2022 to ~280k rows/day in
2024. With a 5x multiplier check against the historical baseline,
every recent day fires the guard even though the day is well within
memory budget.
"""
from __future__ import annotations

import logging

from orchestration.guards import check_extraction_guard


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default (no override) — current behavior preserved
# ---------------------------------------------------------------------------


def test_default_growth_check_blocks_5x_spike():
    """Without an override, fresh > 5 * baseline blocks (CARDTXN scenario
    that motivated the override)."""
    ok = check_extraction_guard(
        "DNA", "CARDTXN", fresh_count=280_000, baseline_count=529,
    )
    assert ok is False


def test_default_growth_check_passes_within_5x():
    ok = check_extraction_guard(
        "DNA", "ACCT", fresh_count=2000, baseline_count=500,
    )
    assert ok is True


def test_default_first_run_ceiling_blocks_above_default():
    ok = check_extraction_guard(
        "DNA", "ACCT", fresh_count=200_000_000, baseline_count=None,
    )
    assert ok is False


# ---------------------------------------------------------------------------
# With override
# ---------------------------------------------------------------------------


def test_override_passes_growth_when_within_absolute_ceiling():
    """The motivating scenario: CARDTXN with baseline 529, fresh 280k.
    Default 5x multiplier (= 2645) blocks. MaxRowsPerDay=5_000_000
    raises the floor → fresh 280k passes."""
    ok = check_extraction_guard(
        "DNA", "CARDTXN", fresh_count=280_000, baseline_count=529,
        max_rows_per_day_override=5_000_000,
    )

    logger.info("Override scenario: 280k rows vs 529 baseline + 5M ceiling → ok=%s", ok)
    assert ok is True


def test_override_still_blocks_above_absolute_ceiling():
    """Cartesian-join detection survives the override — anything above
    the per-table ceiling still blocks."""
    ok = check_extraction_guard(
        "DNA", "CARDTXN", fresh_count=10_000_000, baseline_count=529,
        max_rows_per_day_override=5_000_000,
    )
    assert ok is False


def test_override_still_blocks_when_multiplier_dominates():
    """If 5x * baseline > MaxRowsPerDay, the multiplier check still
    fires (defends against a sudden enormous baseline shift)."""
    ok = check_extraction_guard(
        "DNA", "CARDTXN", fresh_count=20_000_000,
        baseline_count=10_000_000,  # 5x = 50M > 5M override
        max_rows_per_day_override=5_000_000,
    )
    # 20M < 50M (multiplier limit) AND 20M > 5M (override) — but
    # max(50M, 5M) = 50M is the binding limit, so 20M passes.
    assert ok is True


def test_override_first_run_ceiling_replaces_default():
    """First run (no baseline). Override replaces first_run_ceiling
    outright — operator's per-table value wins over the global default."""
    # No override — global ceiling 100M permits 50M.
    ok_default = check_extraction_guard(
        "DNA", "CARDTXN", fresh_count=50_000_000, baseline_count=None,
    )
    assert ok_default is True

    # With override 5M — same fresh count (50M) blocks.
    ok_override = check_extraction_guard(
        "DNA", "CARDTXN", fresh_count=50_000_000, baseline_count=None,
        max_rows_per_day_override=5_000_000,
    )
    assert ok_override is False


def test_override_first_run_ceiling_passes_under_override():
    ok = check_extraction_guard(
        "DNA", "CARDTXN", fresh_count=300_000, baseline_count=None,
        max_rows_per_day_override=5_000_000,
    )
    assert ok is True


# ---------------------------------------------------------------------------
# None / 0 override falls back to defaults
# ---------------------------------------------------------------------------


def test_none_override_uses_global_default():
    """``None`` (the default for table_config.max_rows_per_day) leaves
    the guard exactly as before — every table without the column
    populated keeps its current behavior."""
    ok_explicit_none = check_extraction_guard(
        "DNA", "ACCT", fresh_count=2000, baseline_count=500,
        max_rows_per_day_override=None,
    )
    ok_default = check_extraction_guard(
        "DNA", "ACCT", fresh_count=2000, baseline_count=500,
    )
    assert ok_explicit_none == ok_default


def test_zero_override_falls_through_to_defaults():
    """0 is falsy — same as None. Defends against operator typos
    (UPDATE ... SET MaxRowsPerDay = 0)."""
    ok = check_extraction_guard(
        "DNA", "ACCT", fresh_count=2000, baseline_count=500,
        max_rows_per_day_override=0,
    )
    # 5 * 500 = 2500, fresh 2000 → ok
    assert ok is True
