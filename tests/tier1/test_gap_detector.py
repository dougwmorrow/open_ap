"""Tier 1 unit test for tools/gap_detector.py.

Per D70 Tier 1 — per-function + per-error-path coverage; mocks pyodbc
cursor + ``utils.connections.cursor_for``; no live SQL Server.

North Star pillars:
  - Idempotent (read-only function; multi-call returns identical
    :class:`GapReport` lists for unchanged historical data; tested via
    repeated invocation with the same mocks).
  - Operationally stable (every error path surfaces the documented base
    type per D68 — GapDetectorTimeout is PipelineRetryableError,
    ExtractionStateUnavailable is PipelineRetryableError; exit codes
    follow from D74 in the CLI shim).
  - Audit-grade (every invocation writes exactly one ``GAP_DETECT`` row
    to ``PipelineEventLog`` regardless of result; FAILED audit on raise).
  - Traceability (GapReport carries the full picture: source/table/
    expected_range/missing_dates/recommended_action; event row
    Metadata JSON includes affected-table summary).

D-numbers: D11 (empirical L_99), D14 (IsReExtraction), D22 (hourly
gap detector), D67 (Tier 0), D68 (error hierarchy), D69 (cursor_for
ownership), D92 (forward-only additive).

B-numbers: B-245 (M13 authoring); B85 (utils/errors.py).

Spec: phase1/03_core_modules.md § 5.3 + phase1/01_database_schema.md § 3
+ phase1/04_tools.md § 3.5 (CLI shim consumer contract).
"""
from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pyodbc
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


_UNSET = object()


def _make_cursor(
    fetchone_returns=_UNSET,
    fetchall_returns=None,
    *,
    rowcount: int = 1,
) -> MagicMock:
    """Build a mock cursor with optional fetch return values."""
    cur = MagicMock()
    if fetchone_returns is not _UNSET:
        cur.fetchone.return_value = fetchone_returns
    if fetchall_returns is not None:
        cur.fetchall.return_value = fetchall_returns
    cur.rowcount = rowcount
    # Mock the timeout attribute so module's `cur.timeout = N` doesn't blow up.
    cur.timeout = 0
    return cur


def _make_multi_cursor_for(cursors: list):
    """For tests where each cursor_for() call gets a fresh cursor."""
    iterator = iter(cursors)

    @contextmanager
    def _cm(_db: str):
        yield next(iterator)

    return _cm


def _make_cursor_for(cur: MagicMock):
    """Single-cursor cursor_for shim."""

    @contextmanager
    def _cm(_db: str):
        yield cur

    return _cm


def _timeout_error(message: str = "Query timeout expired") -> pyodbc.OperationalError:
    return pyodbc.OperationalError("HYT00", f"[HYT00] {message}")


def _connection_error() -> pyodbc.OperationalError:
    return pyodbc.OperationalError(
        "08001",
        "[08001] [Microsoft][ODBC Driver 18 for SQL Server]"
        "TCP Provider: Error code 0x68",
    )


def _audit_cursor() -> MagicMock:
    """A cursor for the GAP_DETECT INSERT — always succeeds."""
    return _make_cursor()


# ===========================================================================
# § GapReport dataclass
# ===========================================================================


class TestGapReportDataclass:
    """Field shape, frozen-ness, equality, hashability."""

    def test_dataclass_has_canonical_fields(self):
        from tools.gap_detector import GapReport

        report = GapReport(
            source_name="DNA",
            table_name="ACCT",
            expected_range=(date(2025, 1, 1), date(2025, 1, 31)),
            missing_dates=[date(2025, 1, 15)],
            recommended_action="backfill",
        )
        assert report.source_name == "DNA"
        assert report.table_name == "ACCT"
        assert report.expected_range == (date(2025, 1, 1), date(2025, 1, 31))
        assert report.missing_dates == [date(2025, 1, 15)]
        assert report.recommended_action == "backfill"

    def test_frozen_cannot_mutate(self):
        from dataclasses import FrozenInstanceError

        from tools.gap_detector import GapReport

        report = GapReport(
            source_name="DNA", table_name="X",
            expected_range=(date(2025, 1, 1), date(2025, 1, 1)),
            missing_dates=[], recommended_action="backfill",
        )
        with pytest.raises(FrozenInstanceError):
            report.source_name = "CCM"  # type: ignore[misc]
        with pytest.raises(FrozenInstanceError):
            report.recommended_action = "investigate-source"  # type: ignore[misc]

    def test_equality_by_value(self):
        from tools.gap_detector import GapReport

        a = GapReport(
            source_name="DNA", table_name="X",
            expected_range=(date(2025, 1, 1), date(2025, 1, 2)),
            missing_dates=[date(2025, 1, 1)],
            recommended_action="backfill",
        )
        b = GapReport(
            source_name="DNA", table_name="X",
            expected_range=(date(2025, 1, 1), date(2025, 1, 2)),
            missing_dates=[date(2025, 1, 1)],
            recommended_action="backfill",
        )
        c = GapReport(
            source_name="DNA", table_name="Y",  # different table
            expected_range=(date(2025, 1, 1), date(2025, 1, 2)),
            missing_dates=[date(2025, 1, 1)],
            recommended_action="backfill",
        )
        assert a == b
        assert a != c

    def test_action_constants_exposed(self):
        """The module exposes canonical action-string constants for
        operator-facing callers (CLI shim, alert dispatcher)."""
        from tools.gap_detector import (
            ACTION_BACKFILL,
            ACTION_INVESTIGATE,
            ACTION_NO_ACTION,
        )

        assert ACTION_BACKFILL == "backfill"
        assert ACTION_INVESTIGATE == "investigate-source"
        assert ACTION_NO_ACTION == "within-lookback-no-action"


# ===========================================================================
# § Input validation
# ===========================================================================


class TestInputValidation:
    """Boundary tests on the keyword-only public signature."""

    def test_empty_string_source_filter_raises(self):
        """An empty-string ``source_filter`` is rejected at the boundary."""
        from tools import gap_detector as mod
        from utils.errors import ExtractionStateUnavailable

        with pytest.raises(ExtractionStateUnavailable):
            mod.detect_extraction_gaps(source_filter="", as_of_date=date(2025, 1, 1))

    def test_whitespace_only_source_filter_raises(self):
        from tools import gap_detector as mod
        from utils.errors import ExtractionStateUnavailable

        with pytest.raises(ExtractionStateUnavailable):
            mod.detect_extraction_gaps(source_filter="   ", as_of_date=date(2025, 1, 1))

    def test_non_string_source_filter_raises(self):
        from tools import gap_detector as mod
        from utils.errors import ExtractionStateUnavailable

        with pytest.raises(ExtractionStateUnavailable):
            mod.detect_extraction_gaps(source_filter=123, as_of_date=date(2025, 1, 1))  # type: ignore[arg-type]

    def test_datetime_as_of_date_raises(self):
        """``datetime`` is a subclass of ``date``; the function MUST
        reject it explicitly (the SCD2-P1-f / CDC-NOW-MS family of
        invariants depends on naive date boundaries)."""
        from tools import gap_detector as mod
        from utils.errors import ExtractionStateUnavailable

        with pytest.raises(ExtractionStateUnavailable):
            mod.detect_extraction_gaps(
                as_of_date=datetime(2025, 1, 1, 12, 0, 0)  # type: ignore[arg-type]
            )

    def test_none_as_of_date_defaults_to_today(self):
        """``as_of_date=None`` defaults to UTC today (not raises)."""
        from tools import gap_detector as mod

        # No tables fetched, no work to do.
        udm_cur = _make_cursor(fetchall_returns=[])
        audit_cur = _audit_cursor()
        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, audit_cur]),
        ):
            result = mod.detect_extraction_gaps()  # as_of_date defaults to today
        assert result == []

    def test_none_source_filter_scans_all_sources(self):
        from tools import gap_detector as mod

        udm_cur = _make_cursor(fetchall_returns=[])
        audit_cur = _audit_cursor()
        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, audit_cur]),
        ):
            result = mod.detect_extraction_gaps(source_filter=None, as_of_date=date(2025, 1, 1))
        assert result == []
        # The UdmTablesList SELECT had no SourceName filter.
        executed_sql = udm_cur.execute.call_args.args[0]
        assert "SourceName = ?" not in executed_sql


# ===========================================================================
# § Daterange / classification helpers
# ===========================================================================


class TestDaterangeHelpers:
    """White-box tests on the date-math helpers (defends against
    off-by-one drift on range boundaries)."""

    def test_daterange_inclusive_single_day(self):
        from tools.gap_detector import _daterange_inclusive

        result = _daterange_inclusive(date(2025, 1, 1), date(2025, 1, 1))
        assert result == [date(2025, 1, 1)]

    def test_daterange_inclusive_multi_day(self):
        from tools.gap_detector import _daterange_inclusive

        result = _daterange_inclusive(date(2025, 1, 1), date(2025, 1, 4))
        assert result == [
            date(2025, 1, 1), date(2025, 1, 2),
            date(2025, 1, 3), date(2025, 1, 4),
        ]

    def test_daterange_inclusive_collapsed_returns_empty(self):
        from tools.gap_detector import _daterange_inclusive

        # end < start -> empty list (not raise).
        assert _daterange_inclusive(date(2025, 1, 5), date(2025, 1, 1)) == []

    def test_daterange_inclusive_year_boundary(self):
        from tools.gap_detector import _daterange_inclusive

        result = _daterange_inclusive(date(2024, 12, 30), date(2025, 1, 2))
        assert result == [
            date(2024, 12, 30), date(2024, 12, 31),
            date(2025, 1, 1), date(2025, 1, 2),
        ]


class TestExpectedRange:
    """Tests for :func:`_expected_range` — the lookback-window math."""

    def test_first_load_none_returns_none(self):
        from tools.gap_detector import _expected_range

        result = _expected_range(
            first_load_date=None,
            lookback_days=7,
            as_of_date=date(2025, 1, 10),
        )
        assert result is None

    def test_lookback_none_uses_default(self):
        """A NULL ``LookbackDays`` defaults to the module's conservative
        ``_DEFAULT_LOOKBACK_DAYS`` (7) — not a crash."""
        from tools.gap_detector import _DEFAULT_LOOKBACK_DAYS, _expected_range

        result = _expected_range(
            first_load_date=date(2025, 1, 1),
            lookback_days=None,
            as_of_date=date(2025, 1, 20),
        )
        # range_end = 1/20 - 7 = 1/13.
        assert result == (date(2025, 1, 1), date(2025, 1, 20) - timedelta(days=_DEFAULT_LOOKBACK_DAYS))

    def test_lookback_zero_treated_as_no_exclusion(self):
        """``LookbackDays = 0`` is "expected through today" (no lookback)."""
        from tools.gap_detector import _expected_range

        result = _expected_range(
            first_load_date=date(2025, 1, 1),
            lookback_days=0,
            as_of_date=date(2025, 1, 10),
        )
        assert result == (date(2025, 1, 1), date(2025, 1, 10))

    def test_negative_lookback_clamped_to_zero(self):
        """A defensively-set negative ``LookbackDays`` is clamped to 0
        rather than producing a future range_end."""
        from tools.gap_detector import _expected_range

        result = _expected_range(
            first_load_date=date(2025, 1, 1),
            lookback_days=-3,
            as_of_date=date(2025, 1, 10),
        )
        assert result == (date(2025, 1, 1), date(2025, 1, 10))

    def test_lookback_exceeds_table_age_collapses_range(self):
        """When LookbackDays is so large that range_end < range_start,
        the function returns the tuple — the calling code interprets
        the collapsed range as "nothing to check"."""
        from tools.gap_detector import _expected_range

        result = _expected_range(
            first_load_date=date(2025, 1, 5),
            lookback_days=30,
            as_of_date=date(2025, 1, 10),
        )
        # range_end = 1/10 - 30 = 2024-12-11; before range_start.
        assert result is not None
        range_start, range_end = result
        assert range_end < range_start

    def test_typical_lookback_window(self):
        """The canonical case: lookback=7 from 1/20 -> expected through 1/13."""
        from tools.gap_detector import _expected_range

        result = _expected_range(
            first_load_date=date(2025, 1, 1),
            lookback_days=7,
            as_of_date=date(2025, 1, 20),
        )
        assert result == (date(2025, 1, 1), date(2025, 1, 13))


class TestComputeMissingDates:
    """Set-difference math between expected range and SUCCESS dates."""

    def test_no_missing_when_fully_covered(self):
        from tools.gap_detector import _compute_missing_dates

        expected = (date(2025, 1, 1), date(2025, 1, 3))
        success = {date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)}
        assert _compute_missing_dates(expected, success) == []

    def test_all_missing_when_empty_success(self):
        from tools.gap_detector import _compute_missing_dates

        expected = (date(2025, 1, 1), date(2025, 1, 3))
        assert _compute_missing_dates(expected, set()) == [
            date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3),
        ]

    def test_partial_missing_preserves_order(self):
        from tools.gap_detector import _compute_missing_dates

        expected = (date(2025, 1, 1), date(2025, 1, 5))
        success = {date(2025, 1, 2), date(2025, 1, 4)}
        assert _compute_missing_dates(expected, success) == [
            date(2025, 1, 1), date(2025, 1, 3), date(2025, 1, 5),
        ]

    def test_collapsed_range_returns_empty(self):
        from tools.gap_detector import _compute_missing_dates

        # end < start - empty expected -> empty missing.
        expected = (date(2025, 1, 5), date(2025, 1, 1))
        assert _compute_missing_dates(expected, set()) == []


class TestClassifyAction:
    """Recommended-action classification matrix."""

    def test_no_missing_returns_no_action(self):
        from tools.gap_detector import (
            ACTION_NO_ACTION,
            _classify_action,
        )

        result = _classify_action(missing_dates=[], success_dates={date(2025, 1, 1)})
        assert result == ACTION_NO_ACTION

    def test_some_missing_with_success_rows_returns_backfill(self):
        from tools.gap_detector import ACTION_BACKFILL, _classify_action

        result = _classify_action(
            missing_dates=[date(2025, 1, 2)],
            success_dates={date(2025, 1, 1)},
        )
        assert result == ACTION_BACKFILL

    def test_some_missing_with_no_success_returns_investigate(self):
        from tools.gap_detector import ACTION_INVESTIGATE, _classify_action

        result = _classify_action(
            missing_dates=[date(2025, 1, 1), date(2025, 1, 2)],
            success_dates=set(),
        )
        assert result == ACTION_INVESTIGATE


# ===========================================================================
# § Timeout detection
# ===========================================================================


class TestIsTimeoutError:
    """Heuristics for distinguishing timeout from generic OperationalError."""

    def test_hyt00_state_recognized(self):
        from tools.gap_detector import _is_timeout_error

        exc = pyodbc.OperationalError("HYT00", "[HYT00] Query timeout expired")
        assert _is_timeout_error(exc) is True

    def test_hyt01_state_recognized(self):
        from tools.gap_detector import _is_timeout_error

        exc = pyodbc.OperationalError("HYT01", "[HYT01] Connection timeout")
        assert _is_timeout_error(exc) is True

    def test_connection_error_not_recognized_as_timeout(self):
        from tools.gap_detector import _is_timeout_error

        exc = pyodbc.OperationalError(
            "08001", "[08001] [ODBC] TCP Provider: Error code"
        )
        assert _is_timeout_error(exc) is False

    def test_message_phrase_recognized_when_state_unknown(self):
        """Defends against driver drift — if a future pyodbc version
        uses a different SQLSTATE for timeout but keeps the same phrase
        in the message, the heuristic still catches it."""
        from tools.gap_detector import _is_timeout_error

        exc = pyodbc.OperationalError(
            "UNKNOWN", "[UNKNOWN] operation cancelled"
        )
        assert _is_timeout_error(exc) is True


# ===========================================================================
# § Full happy-path scenarios
# ===========================================================================


class TestEmptyResult:
    """Happy path: no large tables, or all tables clean."""

    def test_no_large_tables_returns_empty_list(self):
        from tools import gap_detector as mod

        udm_cur = _make_cursor(fetchall_returns=[])
        audit_cur = _audit_cursor()
        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, audit_cur]),
        ):
            result = mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))
        assert result == []

    def test_single_table_fully_covered_returns_empty(self):
        """One table, range = 1/1..1/3, all three SUCCESS rows present."""
        from tools import gap_detector as mod

        udm_cur = _make_cursor(
            fetchall_returns=[("DNA", "ACCT", date(2025, 1, 1), 7)]
        )
        success_cur = _make_cursor(
            fetchall_returns=[
                (date(2025, 1, 1),),
                (date(2025, 1, 2),),
                (date(2025, 1, 3),),
            ]
        )
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, success_cur, audit_cur]),
        ):
            result = mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))
        assert result == []

    def test_table_with_null_first_load_skipped(self):
        """A large table with NULL FirstLoadDate has no defined expected
        range — silently skipped."""
        from tools import gap_detector as mod

        udm_cur = _make_cursor(
            fetchall_returns=[("DNA", "ACCT", None, 7)]
        )
        # SUCCESS scan should NOT be called for this table.
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, audit_cur]),
        ):
            result = mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))
        assert result == []

    def test_table_with_collapsed_range_skipped(self):
        """When lookback exceeds the table's age, the expected range
        collapses and the table is silently skipped."""
        from tools import gap_detector as mod

        # FirstLoadDate=1/5, LookbackDays=30, as_of=1/10
        # -> range_end = 1/10 - 30 < 1/5.
        udm_cur = _make_cursor(
            fetchall_returns=[("DNA", "NEW", date(2025, 1, 5), 30)]
        )
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, audit_cur]),
        ):
            result = mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))
        assert result == []


class TestSingleGap:
    """Happy path: single table with gap reported."""

    def test_one_missing_date_in_middle(self):
        from tools import gap_detector as mod
        from tools.gap_detector import ACTION_BACKFILL

        udm_cur = _make_cursor(
            fetchall_returns=[("DNA", "ACCT", date(2025, 1, 1), 7)]
        )
        # Expected = 1/1..1/3 (as_of=1/10, lookback=7).
        # SUCCESS for 1/1 + 1/3 -> missing = 1/2.
        success_cur = _make_cursor(
            fetchall_returns=[(date(2025, 1, 1),), (date(2025, 1, 3),)]
        )
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, success_cur, audit_cur]),
        ):
            result = mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))

        assert len(result) == 1
        r = result[0]
        assert r.source_name == "DNA"
        assert r.table_name == "ACCT"
        assert r.expected_range == (date(2025, 1, 1), date(2025, 1, 3))
        assert r.missing_dates == [date(2025, 1, 2)]
        assert r.recommended_action == ACTION_BACKFILL

    def test_consecutive_missing_dates_preserved(self):
        from tools import gap_detector as mod

        udm_cur = _make_cursor(
            fetchall_returns=[("DNA", "ACCT", date(2025, 1, 1), 7)]
        )
        # Expected = 1/1..1/5 (as_of=1/12).
        # SUCCESS for 1/1, 1/5 -> missing = 1/2, 1/3, 1/4.
        success_cur = _make_cursor(
            fetchall_returns=[(date(2025, 1, 1),), (date(2025, 1, 5),)]
        )
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, success_cur, audit_cur]),
        ):
            result = mod.detect_extraction_gaps(as_of_date=date(2025, 1, 12))

        assert result[0].missing_dates == [
            date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4),
        ]

    def test_first_and_last_missing(self):
        """Sentinel-position missing dates at the range boundaries."""
        from tools import gap_detector as mod

        udm_cur = _make_cursor(
            fetchall_returns=[("DNA", "X", date(2025, 1, 1), 7)]
        )
        # Expected = 1/1..1/5. SUCCESS only middle -> 1/1 and 1/5 missing.
        success_cur = _make_cursor(
            fetchall_returns=[
                (date(2025, 1, 2),), (date(2025, 1, 3),), (date(2025, 1, 4),)
            ]
        )
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, success_cur, audit_cur]),
        ):
            result = mod.detect_extraction_gaps(as_of_date=date(2025, 1, 12))

        assert result[0].missing_dates == [date(2025, 1, 1), date(2025, 1, 5)]


class TestMultiTableGaps:
    """Multi-table reporting + ordering."""

    def test_multiple_sources_separate_reports(self):
        from tools import gap_detector as mod

        # Two tables: DNA.ACCT with gap; CCM.TRANS clean.
        udm_cur = _make_cursor(
            fetchall_returns=[
                ("CCM", "TRANS", date(2025, 1, 1), 7),
                ("DNA", "ACCT", date(2025, 1, 1), 7),
            ]
        )
        ccm_success = _make_cursor(
            fetchall_returns=[(date(2025, 1, 1),), (date(2025, 1, 2),), (date(2025, 1, 3),)]
        )
        dna_success = _make_cursor(
            fetchall_returns=[(date(2025, 1, 1),)]  # 1/2 and 1/3 missing.
        )
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, ccm_success, dna_success, audit_cur]),
        ):
            result = mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))

        assert len(result) == 1
        assert result[0].source_name == "DNA"
        assert result[0].table_name == "ACCT"

    def test_two_tables_both_with_gaps(self):
        from tools import gap_detector as mod

        udm_cur = _make_cursor(
            fetchall_returns=[
                ("CCM", "TRANS", date(2025, 1, 1), 7),
                ("DNA", "ACCT", date(2025, 1, 1), 7),
            ]
        )
        # CCM missing 1/2; DNA missing all.
        ccm_success = _make_cursor(fetchall_returns=[(date(2025, 1, 1),), (date(2025, 1, 3),)])
        dna_success = _make_cursor(fetchall_returns=[])
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, ccm_success, dna_success, audit_cur]),
        ):
            result = mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))

        assert len(result) == 2
        # Order matches UdmTablesList scan order (alphabetical).
        assert result[0].source_name == "CCM"
        assert result[1].source_name == "DNA"
        # DNA was never-extracted in range -> investigate.
        from tools.gap_detector import ACTION_BACKFILL, ACTION_INVESTIGATE
        assert result[0].recommended_action == ACTION_BACKFILL
        assert result[1].recommended_action == ACTION_INVESTIGATE


class TestSourceFilter:
    """``source_filter`` keyword constrains UdmTablesList scan."""

    def test_filter_passed_as_parameter(self):
        from tools import gap_detector as mod

        udm_cur = _make_cursor(fetchall_returns=[])
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, audit_cur]),
        ):
            mod.detect_extraction_gaps(
                source_filter="DNA", as_of_date=date(2025, 1, 10)
            )

        executed_args = udm_cur.execute.call_args
        # The SQL contains the source filter clause.
        assert "SourceName = ?" in executed_args.args[0]
        # And the bound parameter is "DNA".
        assert "DNA" in executed_args.args

    def test_filter_returns_only_matching_source(self):
        from tools import gap_detector as mod

        # UdmTablesList query returns only the filtered source (DB side).
        udm_cur = _make_cursor(
            fetchall_returns=[("DNA", "ACCT", date(2025, 1, 1), 7)]
        )
        success_cur = _make_cursor(fetchall_returns=[])
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, success_cur, audit_cur]),
        ):
            result = mod.detect_extraction_gaps(
                source_filter="DNA", as_of_date=date(2025, 1, 10)
            )

        assert all(r.source_name == "DNA" for r in result)


class TestAsOfDateOverride:
    """``as_of_date`` is the historical-replay knob."""

    def test_historical_as_of_date_yields_smaller_range(self):
        """Same FirstLoadDate but different as_of_date -> different expected_range."""
        from tools import gap_detector as mod

        # Run as of 2025-01-10, lookback 7 -> expected through 1/3.
        udm_cur = _make_cursor(
            fetchall_returns=[("DNA", "ACCT", date(2025, 1, 1), 7)]
        )
        success_cur = _make_cursor(fetchall_returns=[])
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, success_cur, audit_cur]),
        ):
            result = mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))

        assert result[0].expected_range == (date(2025, 1, 1), date(2025, 1, 3))

    def test_future_as_of_date_extends_expected_range(self):
        from tools import gap_detector as mod

        udm_cur = _make_cursor(
            fetchall_returns=[("DNA", "ACCT", date(2025, 1, 1), 7)]
        )
        success_cur = _make_cursor(fetchall_returns=[])
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, success_cur, audit_cur]),
        ):
            result = mod.detect_extraction_gaps(as_of_date=date(2026, 1, 10))

        # Expected = 1/1/2025 .. 1/10/2026 - 7 = 1/3/2026.
        assert result[0].expected_range == (date(2025, 1, 1), date(2026, 1, 3))


# ===========================================================================
# § Error / failure paths
# ===========================================================================


class TestTimeoutHandling:
    """``GapDetectorTimeout`` raises on slow query."""

    def test_timeout_on_pipelineextraction_scan_raises(self):
        from tools import gap_detector as mod
        from utils.errors import GapDetectorTimeout, PipelineRetryableError

        udm_cur = _make_cursor(
            fetchall_returns=[("DNA", "ACCT", date(2025, 1, 1), 7)]
        )
        slow_cur = MagicMock()
        slow_cur.timeout = 0
        slow_cur.execute.side_effect = _timeout_error()
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, slow_cur, audit_cur]),
        ):
            with pytest.raises(GapDetectorTimeout) as exc_info:
                mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))

        # Timeout is a PipelineRetryableError per D68.
        assert isinstance(exc_info.value, PipelineRetryableError)
        # Metadata captures diagnostics for operator.
        md = exc_info.value.metadata
        assert md["source_name"] == "DNA"
        assert md["table_name"] == "ACCT"
        assert md["timeout_seconds"] == 60

    def test_audit_row_written_at_failed_status_on_timeout(self):
        """When timeout fires, the audit row is still written but with
        Status='FAILED' — operator sees something happened."""
        from tools import gap_detector as mod
        from utils.errors import GapDetectorTimeout

        udm_cur = _make_cursor(
            fetchall_returns=[("DNA", "ACCT", date(2025, 1, 1), 7)]
        )
        slow_cur = MagicMock()
        slow_cur.timeout = 0
        slow_cur.execute.side_effect = _timeout_error()
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, slow_cur, audit_cur]),
        ):
            with pytest.raises(GapDetectorTimeout):
                mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))

        # Audit cursor's execute was called with the INSERT INTO ...
        audit_call = audit_cur.execute.call_args
        sql = audit_call.args[0]
        assert "INSERT INTO General.ops.PipelineEventLog" in sql
        # Status param is positional — check FAILED appeared in args.
        assert "FAILED" in audit_call.args


class TestConnectionFailure:
    """Generic OperationalError surfaces as ExtractionStateUnavailable."""

    def test_udm_tables_lookup_failure(self):
        from tools import gap_detector as mod
        from utils.errors import ExtractionStateUnavailable, PipelineRetryableError

        bad_cur = MagicMock()
        bad_cur.timeout = 0
        bad_cur.execute.side_effect = _connection_error()
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([bad_cur, audit_cur]),
        ):
            with pytest.raises(ExtractionStateUnavailable) as exc_info:
                mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))

        assert isinstance(exc_info.value, PipelineRetryableError)

    def test_pipeline_extraction_lookup_failure(self):
        from tools import gap_detector as mod
        from utils.errors import ExtractionStateUnavailable

        udm_cur = _make_cursor(
            fetchall_returns=[("DNA", "ACCT", date(2025, 1, 1), 7)]
        )
        bad_cur = MagicMock()
        bad_cur.timeout = 0
        bad_cur.execute.side_effect = _connection_error()
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, bad_cur, audit_cur]),
        ):
            with pytest.raises(ExtractionStateUnavailable):
                mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))

    def test_unexpected_date_value_type_raises_extraction_state_unavailable(self):
        """A pyodbc row column that's neither None / date / datetime
        surfaces as ExtractionStateUnavailable rather than a raw
        TypeError — operator gets a diagnosable error."""
        from tools.gap_detector import _coerce_date
        from utils.errors import ExtractionStateUnavailable

        with pytest.raises(ExtractionStateUnavailable):
            _coerce_date("2025-01-01")  # str, not date.


# ===========================================================================
# § Audit-row write
# ===========================================================================


class TestAuditRowWrite:
    """GAP_DETECT event row written per invocation."""

    def test_success_audit_row_written_when_no_gaps(self):
        from tools import gap_detector as mod
        from tools.gap_detector import EVENT_TYPE

        udm_cur = _make_cursor(fetchall_returns=[])
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, audit_cur]),
        ):
            mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))

        audit_call = audit_cur.execute.call_args
        sql = audit_call.args[0]
        assert "INSERT INTO General.ops.PipelineEventLog" in sql
        assert EVENT_TYPE in audit_call.args
        assert "SUCCESS" in audit_call.args

    def test_success_audit_row_written_when_gaps_found(self):
        """Even when gaps are found, the function does not raise —
        the audit row is SUCCESS."""
        from tools import gap_detector as mod

        udm_cur = _make_cursor(
            fetchall_returns=[("DNA", "ACCT", date(2025, 1, 1), 7)]
        )
        success_cur = _make_cursor(fetchall_returns=[])
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, success_cur, audit_cur]),
        ):
            mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))

        audit_call = audit_cur.execute.call_args
        assert "SUCCESS" in audit_call.args

    def test_audit_row_metadata_contains_canonical_fields(self):
        from tools import gap_detector as mod

        udm_cur = _make_cursor(
            fetchall_returns=[("DNA", "ACCT", date(2025, 1, 1), 7)]
        )
        success_cur = _make_cursor(fetchall_returns=[])
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, success_cur, audit_cur]),
        ):
            mod.detect_extraction_gaps(
                source_filter="DNA", as_of_date=date(2025, 1, 10)
            )

        # Inspect the metadata JSON (it's the last positional arg).
        metadata_json = audit_cur.execute.call_args.args[-1]
        md = json.loads(metadata_json)
        assert md["as_of_date"] == "2025-01-10"
        assert md["source_filter"] == "DNA"
        assert md["tables_checked"] == 1
        assert md["tables_with_gaps"] == 1
        assert md["module_version"] == "M13/v1"
        # Affected tables list populated.
        assert len(md["affected_tables"]) == 1
        assert md["affected_tables"][0]["source_name"] == "DNA"
        assert md["affected_tables"][0]["table_name"] == "ACCT"

    def test_audit_row_failure_does_not_propagate(self):
        """If the audit-row INSERT fails (audit DB unreachable), the
        verdict (return value) is preserved — best-effort write."""
        from tools import gap_detector as mod

        udm_cur = _make_cursor(fetchall_returns=[])
        bad_audit_cur = MagicMock()
        bad_audit_cur.execute.side_effect = pyodbc.Error("audit DB down")

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, bad_audit_cur]),
        ):
            # No exception — verdict is preserved.
            result = mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))
        assert result == []

    def test_audit_row_metadata_capped_for_large_results(self):
        """When >50 affected tables, the metadata is truncated to avoid
        flooding the audit log."""
        from tools import gap_detector as mod
        from tools.gap_detector import _METADATA_AFFECTED_TABLES_CAP

        # 60 tables, all with gaps.
        tables = [("DNA", f"T_{i:03d}", date(2025, 1, 1), 7) for i in range(60)]
        cursors = [_make_cursor(fetchall_returns=tables)]
        for _ in tables:
            cursors.append(_make_cursor(fetchall_returns=[]))  # All missing.
        cursors.append(_audit_cursor())

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for(cursors),
        ):
            result = mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))

        assert len(result) == 60  # Returned list is NOT truncated.

        audit_cur = cursors[-1]
        metadata_json = audit_cur.execute.call_args.args[-1]
        md = json.loads(metadata_json)
        # affected_tables list is capped + has truncation marker.
        assert len(md["affected_tables"]) == _METADATA_AFFECTED_TABLES_CAP + 1
        assert "_truncated" in md["affected_tables"][-1]
        assert md["tables_with_gaps"] == 60  # The actual count, not truncated.

    def test_audit_row_metadata_missing_dates_capped(self):
        """Per-table missing-dates list inside metadata is capped to
        avoid runaway JSON growth for tables with years of gaps."""
        from tools.gap_detector import (
            _METADATA_MISSING_DATES_CAP,
            _serialize_missing_dates_for_metadata,
        )

        many_dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(150)]
        serialized = _serialize_missing_dates_for_metadata(many_dates)
        # Cap + truncation marker.
        assert len(serialized) == _METADATA_MISSING_DATES_CAP + 1
        assert serialized[-1] == "..."

    def test_audit_row_metadata_missing_dates_not_capped_when_small(self):
        from tools.gap_detector import _serialize_missing_dates_for_metadata

        few = [date(2025, 1, 1), date(2025, 1, 2)]
        serialized = _serialize_missing_dates_for_metadata(few)
        assert serialized == ["2025-01-01", "2025-01-02"]


# ===========================================================================
# § Idempotency
# ===========================================================================


class TestIdempotency:
    """Multi-call with identical inputs returns identical reports."""

    def test_repeated_invocation_returns_identical_reports(self):
        """Calling twice with the same inputs and mocks returns
        identical GapReport lists — pure-function discipline."""
        from tools import gap_detector as mod

        def fresh_mocks():
            udm_cur = _make_cursor(
                fetchall_returns=[("DNA", "ACCT", date(2025, 1, 1), 7)]
            )
            success_cur = _make_cursor(
                fetchall_returns=[(date(2025, 1, 1),), (date(2025, 1, 3),)]
            )
            audit_cur = _audit_cursor()
            return [udm_cur, success_cur, audit_cur]

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for(fresh_mocks()),
        ):
            r1 = mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for(fresh_mocks()),
        ):
            r2 = mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))

        assert r1 == r2
        assert r1[0].missing_dates == r2[0].missing_dates


# ===========================================================================
# § Edge cases — boundaries + invariants
# ===========================================================================


class TestEdgeCases:
    """Boundary conditions and invariants."""

    def test_missing_dates_returned_in_ascending_order(self):
        """The returned ``missing_dates`` list is ordered ascending
        (oldest first) per § 5.3 — independent of SUCCESS-row order."""
        from tools import gap_detector as mod

        udm_cur = _make_cursor(
            fetchall_returns=[("DNA", "ACCT", date(2025, 1, 1), 7)]
        )
        # Return SUCCESS rows in reverse order on the wire.
        success_cur = _make_cursor(
            fetchall_returns=[(date(2025, 1, 5),), (date(2025, 1, 1),)]
        )
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, success_cur, audit_cur]),
        ):
            result = mod.detect_extraction_gaps(as_of_date=date(2025, 1, 12))

        # Missing = 1/2, 1/3, 1/4 — must be ascending regardless of
        # the order pyodbc returned SUCCESS rows.
        assert result[0].missing_dates == [
            date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4),
        ]

    def test_pyodbc_returns_datetime_instead_of_date_coerced(self):
        """pyodbc occasionally returns DATETIME for DATE columns
        depending on driver; the module coerces to date."""
        from tools import gap_detector as mod

        # FirstLoadDate returned as datetime.datetime instead of datetime.date.
        udm_cur = _make_cursor(
            fetchall_returns=[("DNA", "ACCT", datetime(2025, 1, 1, 12, 30, 0), 7)]
        )
        success_cur = _make_cursor(
            fetchall_returns=[(datetime(2025, 1, 1, 0, 0, 0),)]
        )
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, success_cur, audit_cur]),
        ):
            result = mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))

        # No crash — coerce_date handled both.
        # Expected range start = 1/1 (coerced from datetime).
        if result:
            assert isinstance(result[0].expected_range[0], date)
            assert not isinstance(result[0].expected_range[0], datetime)

    def test_typed_contract_expected_range_is_tuple_not_list(self):
        """``expected_range`` is a tuple, not a list — the dataclass
        is hashable, and the canonical contract names a tuple type."""
        from tools import gap_detector as mod

        udm_cur = _make_cursor(
            fetchall_returns=[("DNA", "ACCT", date(2025, 1, 1), 7)]
        )
        success_cur = _make_cursor(fetchall_returns=[])
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, success_cur, audit_cur]),
        ):
            result = mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))

        assert isinstance(result[0].expected_range, tuple)
        assert len(result[0].expected_range) == 2

    def test_module_constants_unchanged(self):
        """Defends against silent edits to the canonical constants.
        Constants here are documented contracts with the CLI shim +
        operator runbooks."""
        from tools.gap_detector import (
            ACTION_BACKFILL,
            ACTION_INVESTIGATE,
            ACTION_NO_ACTION,
            EVENT_TYPE,
            _DEFAULT_LOOKBACK_DAYS,
            _METADATA_AFFECTED_TABLES_CAP,
            _METADATA_MISSING_DATES_CAP,
            _QUERY_TIMEOUT_SECONDS,
        )

        assert EVENT_TYPE == "GAP_DETECT"
        assert _QUERY_TIMEOUT_SECONDS == 60
        assert _DEFAULT_LOOKBACK_DAYS == 7
        assert _METADATA_MISSING_DATES_CAP == 100
        assert _METADATA_AFFECTED_TABLES_CAP == 50
        assert ACTION_BACKFILL == "backfill"
        assert ACTION_INVESTIGATE == "investigate-source"
        assert ACTION_NO_ACTION == "within-lookback-no-action"


# ===========================================================================
# § Logging discipline
# ===========================================================================


class TestLoggingDiscipline:
    """The module logs at INFO/DEBUG levels (no plaintext PII)."""

    def test_starting_message_logged_at_info(self, caplog):
        from tools import gap_detector as mod

        udm_cur = _make_cursor(fetchall_returns=[])
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, audit_cur]),
        ):
            with caplog.at_level("INFO", logger="tools.gap_detector"):
                mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))

        assert any(
            "detect_extraction_gaps" in rec.message for rec in caplog.records
        )

    def test_skip_logged_at_debug_for_null_first_load(self, caplog):
        from tools import gap_detector as mod

        udm_cur = _make_cursor(
            fetchall_returns=[("DNA", "NULL_TABLE", None, 7)]
        )
        audit_cur = _audit_cursor()

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([udm_cur, audit_cur]),
        ):
            with caplog.at_level("DEBUG", logger="tools.gap_detector"):
                mod.detect_extraction_gaps(as_of_date=date(2025, 1, 10))

        debug_messages = [
            rec.message for rec in caplog.records if rec.levelname == "DEBUG"
        ]
        assert any("FirstLoadDate not configured" in m for m in debug_messages)


# ===========================================================================
# § Cross-module integration (smoke; mocked DB but real utils.errors)
# ===========================================================================


class TestCrossModuleIntegration:
    """Verify the module composes correctly with utils.errors hierarchy."""

    def test_gap_detector_timeout_is_pipeline_retryable_error(self):
        from utils.errors import GapDetectorTimeout, PipelineRetryableError

        assert issubclass(GapDetectorTimeout, PipelineRetryableError)

    def test_extraction_state_unavailable_is_pipeline_retryable_error(self):
        from utils.errors import ExtractionStateUnavailable, PipelineRetryableError

        assert issubclass(ExtractionStateUnavailable, PipelineRetryableError)

    def test_metadata_kwarg_pattern_preserved(self):
        """Both error classes accept the canonical metadata kwarg per
        the D68 contract — surfaced in audit-row JSON downstream."""
        from utils.errors import ExtractionStateUnavailable, GapDetectorTimeout

        a = GapDetectorTimeout("msg", metadata={"k": "v"})
        b = ExtractionStateUnavailable("msg", metadata={"k": "v"})
        assert a.metadata == {"k": "v"}
        assert b.metadata == {"k": "v"}
