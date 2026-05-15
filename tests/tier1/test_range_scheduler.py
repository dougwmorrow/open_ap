"""Tier 1 unit test for orchestration/range_scheduler.py.

Per D70 Tier 1 — per-function + per-error-path coverage; mocks pyodbc
cursor + ``cdc.extraction_state.most_recent_success``; no live SQL
Server.

North Star pillars:
  - Idempotent (pure function — multi-call returns identical
    :class:`ExtractionPlan` for identical inputs; tested via repeated
    invocation with the same mocks).
  - Operationally stable (every error path surfaces the documented base
    type per D68 — RangePolicyMissing is PipelineFatalError,
    ExtractionStateUnavailable is PipelineRetryableError; exit codes
    follow from D74).
  - Audit-grade (the returned plan carries ``policy_source`` for trace;
    metadata payload on exceptions captures source/table/reason).
  - Traceability (FirstLoadDate floor + as_of_date ceiling enforced on
    both modes; cap on max_dates defends against unbounded ranges).

D-numbers: D11 (empirical L_99 — informs LookbackDays but scheduler
agnostic), D12 (``ExtractionRangePolicy``), D14 (IsReExtraction), D67
(Tier 0), D68 (error hierarchy), D69 (cursor_for ownership), D92
(forward-only additive).

B-numbers: B85 (utils/errors.py).

Spec: phase1/03_core_modules.md § 5.1 + phase1/01_database_schema.md § 9.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    """Build a mock cursor.

    Pass ``fetchone_returns=None`` explicitly to mean "fetchone returned
    no row" (the cursor's ``fetchone()`` returns ``None``). The
    ``_UNSET`` sentinel default means "don't override fetchone" — used
    by tests that only care about ``fetchall``.
    """
    cur = MagicMock()
    if fetchone_returns is not _UNSET:
        if isinstance(fetchone_returns, list):
            cur.fetchone.side_effect = fetchone_returns
        else:
            cur.fetchone.return_value = fetchone_returns
    if fetchall_returns is not None:
        cur.fetchall.return_value = fetchall_returns
    cur.rowcount = rowcount
    return cur


def _make_cursor_for(cur: MagicMock):
    @contextmanager
    def _cm(_db: str):
        yield cur

    return _cm


def _make_multi_cursor_for(cursors: list):
    """Yield each cursor in turn for sequential ``cursor_for(...)`` calls.

    range_scheduler does two cursor_for calls per plan: UdmTablesList
    then ExtractionRangePolicy.
    """
    iterator = iter(cursors)

    @contextmanager
    def _cm(_db: str):
        yield next(iterator)

    return _cm


def _patch_scheduler(*, udm_row, policy_rows, prior_success=None):
    """Convenience: returns the patch context managers for a planning call.

    Use as::

        with _patch_scheduler(
            udm_row=(date(2024,1,1), 3),
            policy_rows=[],
            prior_success=None,
        ):
            plan = mod.plan_extraction_range(...)
    """
    from orchestration import range_scheduler as mod

    cur_udm = _make_cursor(fetchone_returns=udm_row)
    cur_policy = _make_cursor(fetchall_returns=policy_rows)

    return [
        patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([cur_udm, cur_policy]),
        ),
        patch.object(mod, "most_recent_success", return_value=prior_success),
    ]


@contextmanager
def _scheduler_ctx(*, udm_row, policy_rows, prior_success=None):
    patches = _patch_scheduler(
        udm_row=udm_row,
        policy_rows=policy_rows,
        prior_success=prior_success,
    )
    try:
        for p in patches:
            p.start()
        yield
    finally:
        for p in patches:
            p.stop()


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Reject malformed inputs before any DB I/O."""

    def test_empty_source_name_raises(self):
        from orchestration import range_scheduler as mod
        from utils.errors import RangePolicyMissing

        with pytest.raises(RangePolicyMissing):
            mod.plan_extraction_range(
                source_name="",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

    def test_empty_table_name_raises(self):
        from orchestration import range_scheduler as mod
        from utils.errors import RangePolicyMissing

        with pytest.raises(RangePolicyMissing):
            mod.plan_extraction_range(
                source_name="DNA",
                table_name="",
                as_of_date=date(2025, 1, 15),
            )

    def test_non_string_source_name_raises(self):
        from orchestration import range_scheduler as mod
        from utils.errors import RangePolicyMissing

        with pytest.raises(RangePolicyMissing):
            mod.plan_extraction_range(
                source_name=123,  # type: ignore[arg-type]
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

    def test_datetime_as_of_date_rejected(self):
        """``datetime`` IS a ``date`` subclass; the scheduler wants pure
        ``date`` to avoid time-of-day comparison surprises."""
        from orchestration import range_scheduler as mod
        from utils.errors import RangePolicyMissing

        with pytest.raises(RangePolicyMissing):
            mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=datetime(2025, 1, 15, 14, 30),  # type: ignore[arg-type]
            )

    def test_negative_max_dates_raises(self):
        from orchestration import range_scheduler as mod
        from utils.errors import RangePolicyMissing

        with pytest.raises(RangePolicyMissing):
            mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
                max_dates=-1,
            )

    def test_zero_max_dates_raises(self):
        from orchestration import range_scheduler as mod
        from utils.errors import RangePolicyMissing

        with pytest.raises(RangePolicyMissing):
            mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
                max_dates=0,
            )

    def test_default_as_of_date_is_today_utc(self):
        """When ``as_of_date`` is omitted, the planner uses today UTC."""
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(None, 1),
            policy_rows=[],
            prior_success=None,
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
            )

        today_utc = datetime.now(timezone.utc).date()
        assert plan.dates == [today_utc]


# ---------------------------------------------------------------------------
# Default-lookback mode
# ---------------------------------------------------------------------------


class TestDefaultLookbackMode:
    """No ExtractionRangePolicy rows → fall back to LookbackDays rolling window."""

    def test_one_day_window(self):
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(date(2024, 1, 1), 1),
            policy_rows=[],
            prior_success=None,
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        assert plan.policy_source == "default-lookback"
        assert plan.dates == [date(2025, 1, 15)]

    def test_seven_day_window(self):
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(date(2024, 1, 1), 7),
            policy_rows=[],
            prior_success=None,
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        assert plan.policy_source == "default-lookback"
        assert plan.dates == [
            date(2025, 1, 9), date(2025, 1, 10), date(2025, 1, 11),
            date(2025, 1, 12), date(2025, 1, 13), date(2025, 1, 14),
            date(2025, 1, 15),
        ]

    def test_window_clipped_by_first_load_date(self):
        """LookbackDays would walk past FirstLoadDate; window clips."""
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(date(2025, 1, 13), 7),  # FirstLoadDate
            policy_rows=[],
            prior_success=None,
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        # Window [2025-01-09, 2025-01-15] but floor at 2025-01-13.
        assert plan.dates == [
            date(2025, 1, 13), date(2025, 1, 14), date(2025, 1, 15),
        ]

    def test_dates_sorted_ascending(self):
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(None, 5),
            policy_rows=[],
            prior_success=None,
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        assert plan.dates == sorted(plan.dates)
        assert plan.dates[0] == date(2025, 1, 11)
        assert plan.dates[-1] == date(2025, 1, 15)

    def test_floor_null_means_no_floor(self):
        """``FirstLoadDate IS NULL`` skips the floor clip."""
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(None, 3),
            policy_rows=[],
            prior_success=None,
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        assert len(plan.dates) == 3
        assert plan.dates[0] == date(2025, 1, 13)


# ---------------------------------------------------------------------------
# Policy mode
# ---------------------------------------------------------------------------


class TestPolicyMode:
    """ExtractionRangePolicy active rows drive the schedule per D12."""

    def test_single_range_explicit_bounds(self):
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(date(2024, 1, 1), None),
            policy_rows=[(date(2025, 1, 12), date(2025, 1, 14))],
            prior_success=None,
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        assert plan.policy_source == "ExtractionRangePolicy"
        assert plan.dates == [
            date(2025, 1, 12), date(2025, 1, 13), date(2025, 1, 14),
        ]

    def test_null_start_means_today(self):
        """``RangeStartDate IS NULL`` means ``as_of_date``."""
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(date(2024, 1, 1), None),
            policy_rows=[(None, date(2025, 1, 15))],
            prior_success=None,
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        assert plan.dates == [date(2025, 1, 15)]

    def test_null_end_means_today(self):
        """``RangeEndDate IS NULL`` means ``as_of_date``."""
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(date(2024, 1, 1), None),
            policy_rows=[(date(2025, 1, 13), None)],
            prior_success=None,
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        assert plan.dates == [
            date(2025, 1, 13), date(2025, 1, 14), date(2025, 1, 15),
        ]

    def test_both_null_means_today_only(self):
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(date(2024, 1, 1), None),
            policy_rows=[(None, None)],
            prior_success=None,
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        assert plan.dates == [date(2025, 1, 15)]

    def test_multiple_ranges_union_dedup_sort(self):
        """Overlapping ranges union; dedupe; sort ascending."""
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(date(2024, 1, 1), None),
            policy_rows=[
                (date(2025, 1, 10), date(2025, 1, 12)),
                (date(2025, 1, 11), date(2025, 1, 13)),  # overlaps
            ],
            prior_success=None,
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        # Union of [10..12] + [11..13] = [10, 11, 12, 13] sorted, no dupes.
        assert plan.dates == [
            date(2025, 1, 10), date(2025, 1, 11),
            date(2025, 1, 12), date(2025, 1, 13),
        ]

    def test_inverted_range_is_no_op(self):
        """``RangeStartDate > RangeEndDate`` (mis-entered) returns 0 dates
        rather than raising — the planner is forgiving of inert rows.
        """
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(date(2024, 1, 1), None),
            policy_rows=[(date(2025, 1, 20), date(2025, 1, 10))],
            prior_success=None,
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        assert plan.dates == []
        # Policy was present even though it yielded nothing.
        assert plan.policy_source == "ExtractionRangePolicy"

    def test_range_clipped_to_as_of_date_ceiling(self):
        """Range end > as_of_date clips to today."""
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(date(2024, 1, 1), None),
            policy_rows=[(date(2025, 1, 14), date(2025, 1, 30))],
            prior_success=None,
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        assert plan.dates == [date(2025, 1, 14), date(2025, 1, 15)]

    def test_range_clipped_by_first_load_date(self):
        """Range start < FirstLoadDate clips to floor."""
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(date(2025, 1, 13), None),
            policy_rows=[(date(2025, 1, 10), date(2025, 1, 15))],
            prior_success=None,
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        assert plan.dates == [
            date(2025, 1, 13), date(2025, 1, 14), date(2025, 1, 15),
        ]

    def test_max_dates_truncates_unbounded_range(self):
        """A 10-year range against max_dates=5 keeps the most recent 5."""
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(None, None),
            policy_rows=[(date(2015, 1, 1), date(2025, 1, 15))],
            prior_success=None,
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
                max_dates=5,
            )

        assert len(plan.dates) == 5
        assert plan.dates[-1] == date(2025, 1, 15)
        assert plan.dates[0] == date(2025, 1, 11)


# ---------------------------------------------------------------------------
# Re-extraction flag composition (D14)
# ---------------------------------------------------------------------------


class TestReExtractionFlags:

    def test_no_prior_success_all_false(self):
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(None, 3),
            policy_rows=[],
            prior_success=None,
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        assert all(v is False for v in plan.re_extraction_flags.values())

    def test_prior_success_marks_older_dates_true(self):
        """Dates <= prior_success_date are flagged as re-extraction."""
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(None, 5),
            policy_rows=[],
            prior_success=date(2025, 1, 13),
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        # Window: 2025-01-11..2025-01-15. Prior SUCCESS on 2025-01-13.
        assert plan.re_extraction_flags[date(2025, 1, 11)] is True
        assert plan.re_extraction_flags[date(2025, 1, 12)] is True
        assert plan.re_extraction_flags[date(2025, 1, 13)] is True
        assert plan.re_extraction_flags[date(2025, 1, 14)] is False
        assert plan.re_extraction_flags[date(2025, 1, 15)] is False

    def test_flag_keys_match_dates(self):
        """The flag dict's keys == ``set(plan.dates)`` exactly."""
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(None, 3),
            policy_rows=[],
            prior_success=date(2025, 1, 14),
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        assert set(plan.re_extraction_flags.keys()) == set(plan.dates)

    def test_empty_dates_yields_empty_flags(self):
        from orchestration import range_scheduler as mod

        # FirstLoadDate well past as_of_date → empty plan.
        with _scheduler_ctx(
            udm_row=(date(2030, 1, 1), 3),
            policy_rows=[],
            prior_success=date(2025, 1, 14),
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        assert plan.dates == []
        assert plan.re_extraction_flags == {}


# ---------------------------------------------------------------------------
# Error paths (per D68)
# ---------------------------------------------------------------------------


class TestRangePolicyMissing:
    """Configuration-error paths — RangePolicyMissing (PipelineFatalError)."""

    def test_udm_row_missing_and_no_policy(self):
        """UdmTablesList row absent AND no ExtractionRangePolicy rows."""
        from orchestration import range_scheduler as mod
        from utils.errors import PipelineFatalError, RangePolicyMissing

        with _scheduler_ctx(
            udm_row=None,
            policy_rows=[],
            prior_success=None,
        ):
            with pytest.raises(RangePolicyMissing) as exc_info:
                mod.plan_extraction_range(
                    source_name="DNA",
                    table_name="ACCT",
                    as_of_date=date(2025, 1, 15),
                )

        assert isinstance(exc_info.value, PipelineFatalError)
        meta = exc_info.value.metadata
        assert meta["source_name"] == "DNA"
        assert meta["table_name"] == "ACCT"
        assert meta["udm_row_present"] is False
        assert meta["active_policy_count"] == 0

    def test_udm_present_lookback_null_and_no_policy(self):
        from orchestration import range_scheduler as mod
        from utils.errors import RangePolicyMissing

        with _scheduler_ctx(
            udm_row=(date(2024, 1, 1), None),
            policy_rows=[],
            prior_success=None,
        ):
            with pytest.raises(RangePolicyMissing) as exc_info:
                mod.plan_extraction_range(
                    source_name="DNA",
                    table_name="ACCT",
                    as_of_date=date(2025, 1, 15),
                )

        meta = exc_info.value.metadata
        assert meta["udm_row_present"] is True
        assert meta["lookback_days"] is None

    def test_zero_lookback_treated_as_unconfigured(self):
        """``LookbackDays = 0`` is non-positive — same as NULL semantically."""
        from orchestration import range_scheduler as mod
        from utils.errors import RangePolicyMissing

        with _scheduler_ctx(
            udm_row=(date(2024, 1, 1), 0),
            policy_rows=[],
            prior_success=None,
        ):
            with pytest.raises(RangePolicyMissing):
                mod.plan_extraction_range(
                    source_name="DNA",
                    table_name="ACCT",
                    as_of_date=date(2025, 1, 15),
                )

    def test_policy_present_with_no_lookback_still_works(self):
        """Active policy row + LookbackDays NULL — policy mode wins."""
        from orchestration import range_scheduler as mod

        with _scheduler_ctx(
            udm_row=(date(2024, 1, 1), None),
            policy_rows=[(date(2025, 1, 14), date(2025, 1, 15))],
            prior_success=None,
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        assert plan.dates == [date(2025, 1, 14), date(2025, 1, 15)]
        assert plan.policy_source == "ExtractionRangePolicy"


class TestExtractionStateUnavailable:
    """Transient DB failure → PipelineRetryableError."""

    def test_udm_lookup_operational_error(self):
        from orchestration import range_scheduler as mod
        from utils.errors import (
            ExtractionStateUnavailable,
            PipelineRetryableError,
        )

        cur = MagicMock()
        cur.execute.side_effect = pyodbc.OperationalError("08001", "connection lost")

        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with pytest.raises(ExtractionStateUnavailable) as exc_info:
                mod.plan_extraction_range(
                    source_name="DNA",
                    table_name="ACCT",
                    as_of_date=date(2025, 1, 15),
                )

        assert isinstance(exc_info.value, PipelineRetryableError)

    def test_policy_lookup_operational_error(self):
        from orchestration import range_scheduler as mod
        from utils.errors import ExtractionStateUnavailable

        # First cursor (UdmTablesList) succeeds; second (policy) blows up.
        cur_udm = _make_cursor(fetchone_returns=(date(2024, 1, 1), 3))
        cur_policy = MagicMock()
        cur_policy.execute.side_effect = pyodbc.OperationalError(
            "08001", "policy table unreachable",
        )

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([cur_udm, cur_policy]),
        ):
            with pytest.raises(ExtractionStateUnavailable):
                mod.plan_extraction_range(
                    source_name="DNA",
                    table_name="ACCT",
                    as_of_date=date(2025, 1, 15),
                )

    def test_unexpected_date_value_type_raises(self):
        """A non-date value in a date column surfaces as
        ExtractionStateUnavailable per ``_coerce_date``."""
        from orchestration import range_scheduler as mod
        from utils.errors import ExtractionStateUnavailable

        cur_udm = _make_cursor(fetchone_returns=("not-a-date", 3))
        cur_policy = _make_cursor(fetchall_returns=[])

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([cur_udm, cur_policy]),
        ), patch.object(
            mod, "most_recent_success", return_value=None,
        ):
            with pytest.raises(ExtractionStateUnavailable):
                mod.plan_extraction_range(
                    source_name="DNA",
                    table_name="ACCT",
                    as_of_date=date(2025, 1, 15),
                )


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


class TestCoercionHelpers:

    def test_datetime_value_coerces_to_date(self):
        """pyodbc occasionally returns DATE as datetime; coerce."""
        from orchestration import range_scheduler as mod

        cur_udm = _make_cursor(
            fetchone_returns=(datetime(2024, 1, 1, 0, 0), 3),
        )
        cur_policy = _make_cursor(fetchall_returns=[])

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([cur_udm, cur_policy]),
        ), patch.object(
            mod, "most_recent_success", return_value=None,
        ):
            plan = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        # Should accept FirstLoadDate=2024-01-01 from a datetime cell.
        assert plan.dates[0] == date(2025, 1, 13)

    def test_coerce_date_none_passthrough(self):
        """``_coerce_date(None)`` returns None — used for nullable
        FirstLoadDate / range bound columns."""
        from orchestration.range_scheduler import _coerce_date

        assert _coerce_date(None) is None


# ---------------------------------------------------------------------------
# Idempotency: pure function — same inputs, same output
# ---------------------------------------------------------------------------


class TestIdempotency:

    def test_repeated_call_same_inputs_same_output(self):
        """Pure function — multi-call returns identical content."""
        from orchestration import range_scheduler as mod

        # Each call needs its own cursor pair since fetchone is a stateful
        # side-effect mock; build them lazily.
        def _build_cursors():
            return [
                _make_cursor(fetchone_returns=(date(2024, 1, 1), 3)),
                _make_cursor(fetchall_returns=[]),
            ]

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for(_build_cursors()),
        ), patch.object(
            mod, "most_recent_success", return_value=date(2025, 1, 14),
        ):
            plan_a = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for(_build_cursors()),
        ), patch.object(
            mod, "most_recent_success", return_value=date(2025, 1, 14),
        ):
            plan_b = mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        assert plan_a.dates == plan_b.dates
        assert plan_a.re_extraction_flags == plan_b.re_extraction_flags
        assert plan_a.policy_source == plan_b.policy_source


# ---------------------------------------------------------------------------
# Query shape — assert we hit the canonical tables
# ---------------------------------------------------------------------------


class TestQueryShape:

    def test_udm_lookup_targets_correct_table_columns(self):
        from orchestration import range_scheduler as mod

        cur_udm = _make_cursor(fetchone_returns=(date(2024, 1, 1), 3))
        cur_policy = _make_cursor(fetchall_returns=[])

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([cur_udm, cur_policy]),
        ), patch.object(
            mod, "most_recent_success", return_value=None,
        ):
            mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        # First execute on cur_udm is the UdmTablesList lookup.
        udm_sql = cur_udm.execute.call_args.args[0]
        assert "UdmTablesList" in udm_sql
        assert "FirstLoadDate" in udm_sql
        assert "LookbackDays" in udm_sql
        assert "SourceObjectName" in udm_sql

    def test_policy_lookup_targets_active_rows(self):
        from orchestration import range_scheduler as mod

        cur_udm = _make_cursor(fetchone_returns=(date(2024, 1, 1), 3))
        cur_policy = _make_cursor(fetchall_returns=[])

        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([cur_udm, cur_policy]),
        ), patch.object(
            mod, "most_recent_success", return_value=None,
        ):
            mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

        policy_sql = cur_policy.execute.call_args.args[0]
        assert "ExtractionRangePolicy" in policy_sql
        assert "Active = 1" in policy_sql
        assert "RangeStartDate" in policy_sql
        assert "RangeEndDate" in policy_sql


# ---------------------------------------------------------------------------
# ExtractionPlan dataclass invariants
# ---------------------------------------------------------------------------


class TestExtractionPlanDataclass:

    def test_frozen_dataclass(self):
        from dataclasses import FrozenInstanceError

        from orchestration.range_scheduler import ExtractionPlan

        plan = ExtractionPlan(
            source_name="DNA",
            table_name="ACCT",
            dates=[],
            re_extraction_flags={},
            policy_source="default-lookback",
        )
        with pytest.raises(FrozenInstanceError):
            plan.policy_source = "other"  # type: ignore[misc]

    def test_fields_match_spec(self):
        from dataclasses import fields

        from orchestration.range_scheduler import ExtractionPlan

        expected = {
            "source_name", "table_name", "dates",
            "re_extraction_flags", "policy_source",
        }
        actual = {f.name for f in fields(ExtractionPlan)}
        assert actual == expected
