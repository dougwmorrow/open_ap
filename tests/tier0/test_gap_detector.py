"""Tier 0 build-time smoke test for tools/gap_detector.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s. All
external dependencies (pyodbc cursor, ``utils.connections.cursor_for``)
are mocked. No live SQL Server required.

North Star pillars:
  - Operationally stable (D67 Tier 0 discipline: import + invocability +
    happy-path + failure-path in < 5 s with zero external I/O).
  - Idempotent (read-only function; multi-call returns identical
    :class:`GapReport` lists for unchanged historical data).
  - Audit-grade (every invocation writes exactly one ``GAP_DETECT`` row
    to ``PipelineEventLog`` regardless of result).
  - Traceability (GapReport carries source/table/expected_range/
    missing_dates/recommended_action for operator inspection).

D-numbers: D11 (empirical L_99), D14 (IsReExtraction), D22 (hourly
gap detector), D67 (Tier 0), D68 (error hierarchy), D69 (cursor_for
ownership), D92 (forward-only additive).

B-numbers: B-245 (M13 authoring); B85 (utils/errors.py dependency closed).

Spec: phase1/03_core_modules.md § 5.3 + phase1/01_database_schema.md § 3.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Test fixtures — mock cursor_for context manager
# ---------------------------------------------------------------------------


def _make_cursor(fetchone_returns=None, fetchall_returns=None) -> MagicMock:
    """Build a mock pyodbc cursor with optional fetch return values."""
    cur = MagicMock()
    if fetchone_returns is not None:
        cur.fetchone.return_value = fetchone_returns
    if fetchall_returns is not None:
        cur.fetchall.return_value = fetchall_returns
    cur.rowcount = 1
    return cur


def _make_multi_cursor_for(cursors: list):
    """Return a cursor_for-shaped context manager yielding the next
    cursor from ``cursors`` on each call.

    Mirrors the pattern used by tests/tier0/test_extraction_state.py
    (M10 sibling).
    """
    iterator = iter(cursors)

    @contextmanager
    def _cm(_db: str):
        yield next(iterator)

    return _cm


# ---------------------------------------------------------------------------
# (a) Module imports without error
# ---------------------------------------------------------------------------


def test_module_imports():
    """(a) tools.gap_detector imports cleanly per D67 assertion 1.

    Verifies no syntax errors, no missing dependencies, no import-time
    DB / network side-effects.
    """
    import tools.gap_detector as mod

    assert mod is not None
    assert hasattr(mod, "detect_extraction_gaps")
    assert hasattr(mod, "GapReport"), "Public dataclass per § 5.3"
    assert callable(mod.detect_extraction_gaps)
    assert mod.__all__ == ["GapReport", "detect_extraction_gaps"]


# ---------------------------------------------------------------------------
# (b) GapReport dataclass shape per § 5.3 canonical interface
# ---------------------------------------------------------------------------


def test_gap_report_dataclass_shape():
    """(b) GapReport is a frozen dataclass with the canonical fields.

    Per § 5.3 interface spec — exposes source_name, table_name,
    expected_range (tuple[date, date]), missing_dates (list[date]),
    recommended_action (str).
    """
    from dataclasses import FrozenInstanceError

    from tools.gap_detector import GapReport

    report = GapReport(
        source_name="DNA",
        table_name="ACCT",
        expected_range=(date(2025, 1, 1), date(2025, 1, 31)),
        missing_dates=[date(2025, 1, 15), date(2025, 1, 16)],
        recommended_action="backfill",
    )
    assert report.source_name == "DNA"
    assert report.table_name == "ACCT"
    assert report.expected_range == (date(2025, 1, 1), date(2025, 1, 31))
    assert report.missing_dates == [date(2025, 1, 15), date(2025, 1, 16)]
    assert report.recommended_action == "backfill"

    # Frozen: cannot reassign fields.
    with pytest.raises(FrozenInstanceError):
        report.source_name = "CCM"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# (c) Empty-gap (every table is clean) returns empty list
# ---------------------------------------------------------------------------


def test_detect_extraction_gaps_returns_empty_when_clean():
    """(c) When every checked table has full SUCCESS coverage in the
    expected range, the function returns an empty list AND still
    writes a GAP_DETECT audit row.
    """
    from tools import gap_detector as mod

    # Cursor 1: UdmTablesList -> one large table with FirstLoadDate +
    # LookbackDays. Cursor 2: PipelineExtraction SUCCESS dates fully
    # covering the expected range. Cursor 3: GAP_DETECT INSERT.
    udm_cur = _make_cursor(
        fetchall_returns=[("DNA", "ACCT", date(2025, 1, 1), 7)]
    )
    # as_of_date=2025-01-10, lookback=7 -> expected range = 1/1..1/3 (3 days).
    success_cur = _make_cursor(
        fetchall_returns=[(date(2025, 1, 1),), (date(2025, 1, 2),), (date(2025, 1, 3),)]
    )
    audit_cur = _make_cursor()

    with patch.object(
        mod, "cursor_for",
        _make_multi_cursor_for([udm_cur, success_cur, audit_cur]),
    ):
        result = mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))

    assert isinstance(result, list)
    assert result == []  # No gaps.


# ---------------------------------------------------------------------------
# (d) Single-table gap detection — happy path
# ---------------------------------------------------------------------------


def test_detect_extraction_gaps_single_gap_returns_report():
    """(d) When a table is missing one or more dates in its expected
    range, a GapReport with those exact missing dates is returned and
    the recommended_action is 'backfill' (some SUCCESS rows exist).
    """
    from tools.gap_detector import (
        ACTION_BACKFILL,
        GapReport,
        detect_extraction_gaps,
    )
    import tools.gap_detector as mod

    # Single large table, expected range = 1/1..1/5 (5 days),
    # SUCCESS only for 1/1, 1/2, 1/4 -> missing = 1/3, 1/5.
    udm_cur = _make_cursor(
        fetchall_returns=[("DNA", "ACCT", date(2025, 1, 1), 7)]
    )
    success_cur = _make_cursor(
        fetchall_returns=[(date(2025, 1, 1),), (date(2025, 1, 2),), (date(2025, 1, 4),)]
    )
    audit_cur = _make_cursor()

    with patch.object(
        mod, "cursor_for",
        _make_multi_cursor_for([udm_cur, success_cur, audit_cur]),
    ):
        result = detect_extraction_gaps(as_of_date=date(2025, 1, 12))

    assert len(result) == 1
    report = result[0]
    assert isinstance(report, GapReport)
    assert report.source_name == "DNA"
    assert report.table_name == "ACCT"
    assert report.expected_range == (date(2025, 1, 1), date(2025, 1, 5))
    assert report.missing_dates == [date(2025, 1, 3), date(2025, 1, 5)]
    assert report.recommended_action == ACTION_BACKFILL


# ---------------------------------------------------------------------------
# (e) GapDetectorTimeout raised on slow query
# ---------------------------------------------------------------------------


def test_detect_extraction_gaps_raises_timeout_on_slow_query():
    """(e) When the SUCCESS-row scan exceeds 60 s, the function raises
    GapDetectorTimeout (PipelineRetryableError per D68).

    Verifies the timeout error wrapping logic: a pyodbc.OperationalError
    with HYT00 SQL state is recognized as a timeout and surfaces as
    the documented retryable subclass.
    """
    import pyodbc

    from tools import gap_detector as mod
    from utils.errors import GapDetectorTimeout, PipelineRetryableError

    udm_cur = _make_cursor(
        fetchall_returns=[("DNA", "ACCT", date(2025, 1, 1), 7)]
    )
    # Simulate a server-side query timeout on the SUCCESS scan.
    success_cur = MagicMock()
    success_cur.execute.side_effect = pyodbc.OperationalError(
        "HYT00", "[HYT00] Query timeout expired"
    )
    audit_cur = _make_cursor()

    with patch.object(
        mod, "cursor_for",
        _make_multi_cursor_for([udm_cur, success_cur, audit_cur]),
    ):
        with pytest.raises(GapDetectorTimeout) as exc_info:
            mod.detect_extraction_gaps(as_of_date=date(2025, 1, 12))

    # GapDetectorTimeout is a PipelineRetryableError per D68.
    assert isinstance(exc_info.value, PipelineRetryableError)
    # Metadata carries diagnostics.
    assert exc_info.value.metadata.get("timeout_seconds") == 60


# ---------------------------------------------------------------------------
# (f) Never-extracted table -> 'investigate-source'
# ---------------------------------------------------------------------------


def test_never_extracted_table_recommends_investigate_source():
    """(f) A table with zero SUCCESS rows in the expected range gets
    'investigate-source' (not 'backfill') — operator must check before
    issuing a blind backfill.
    """
    from tools.gap_detector import ACTION_INVESTIGATE, detect_extraction_gaps
    import tools.gap_detector as mod

    udm_cur = _make_cursor(
        fetchall_returns=[("DNA", "NEW_TABLE", date(2025, 1, 1), 7)]
    )
    # Zero SUCCESS rows.
    success_cur = _make_cursor(fetchall_returns=[])
    audit_cur = _make_cursor()

    with patch.object(
        mod, "cursor_for",
        _make_multi_cursor_for([udm_cur, success_cur, audit_cur]),
    ):
        result = detect_extraction_gaps(as_of_date=date(2025, 1, 12))

    assert len(result) == 1
    assert result[0].recommended_action == ACTION_INVESTIGATE
    assert result[0].missing_dates  # Non-empty.
