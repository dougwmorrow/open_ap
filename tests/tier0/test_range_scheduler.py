"""Tier 0 build-time smoke test for orchestration/range_scheduler.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s. All
external dependencies (pyodbc cursor, ``utils.connections.cursor_for``,
``cdc.extraction_state.most_recent_success``) are mocked. No live SQL
Server required.

North Star pillars:
  - Operationally stable (D67 Tier 0 discipline: import + invocability +
    happy-path + failure-path in < 5 s with zero external I/O).
  - Idempotent (pure function — multi-call returns identical
    :class:`ExtractionPlan` for identical inputs).
  - Audit-grade (the returned plan carries ``policy_source`` so operators
    can trace which mode drove the schedule).

D-numbers: D11 (empirical L_99), D12 (``ExtractionRangePolicy``), D14
(IsReExtraction), D67 (Tier 0), D68 (error hierarchy), D69 (cursor_for
ownership), D92 (forward-only additive).

B-numbers: B85 (utils/errors.py dependency closed).

Spec: phase1/03_core_modules.md § 5.1 + phase1/01_database_schema.md § 9.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Test fixtures — mock cursor_for context manager + most_recent_success
# ---------------------------------------------------------------------------


def _make_cursor(fetchone_returns=None, fetchall_returns=None) -> MagicMock:
    """Build a mock pyodbc cursor with optional fetch return values."""
    cur = MagicMock()
    if fetchone_returns is not None:
        if isinstance(fetchone_returns, list):
            cur.fetchone.side_effect = fetchone_returns
        else:
            cur.fetchone.return_value = fetchone_returns
    if fetchall_returns is not None:
        cur.fetchall.return_value = fetchall_returns
    cur.rowcount = 1
    return cur


def _make_multi_cursor_for(cursors: list):
    """Return a cursor_for-shaped context manager that yields the next
    cursor from ``cursors`` on each call.

    ``range_scheduler`` invokes ``cursor_for("General")`` twice per call:
    once for ``UdmTablesList`` and once for ``ExtractionRangePolicy``.
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
    """(a) orchestration.range_scheduler imports cleanly per D67 assertion 1.

    Verifies no syntax errors, no missing dependencies, no import-time
    DB / network side-effects.
    """
    import orchestration.range_scheduler as mod

    assert mod is not None
    assert hasattr(mod, "plan_extraction_range"), (
        "Public planner function per § 5.1"
    )
    assert hasattr(mod, "ExtractionPlan"), "Public dataclass per § 5.1"
    assert "plan_extraction_range" in mod.__all__
    assert "ExtractionPlan" in mod.__all__


# ---------------------------------------------------------------------------
# (b) ExtractionPlan dataclass shape per § 5.1 interface
# ---------------------------------------------------------------------------


def test_extraction_plan_dataclass_shape():
    """(b) ExtractionPlan is a frozen dataclass with the canonical fields.

    Per § 5.1 interface spec — source_name, table_name, dates,
    re_extraction_flags, policy_source.
    """
    from dataclasses import FrozenInstanceError, fields

    from orchestration.range_scheduler import ExtractionPlan

    field_names = {f.name for f in fields(ExtractionPlan)}
    assert field_names == {
        "source_name", "table_name", "dates",
        "re_extraction_flags", "policy_source",
    }

    plan = ExtractionPlan(
        source_name="DNA",
        table_name="ACCT",
        dates=[date(2025, 1, 14), date(2025, 1, 15)],
        re_extraction_flags={date(2025, 1, 14): True, date(2025, 1, 15): False},
        policy_source="default-lookback",
    )
    assert plan.source_name == "DNA"
    assert plan.policy_source == "default-lookback"
    assert plan.dates == [date(2025, 1, 14), date(2025, 1, 15)]

    # frozen — cannot mutate
    with pytest.raises(FrozenInstanceError):
        plan.source_name = "OTHER"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# (c) Default-lookback mode happy path returns ordered dates
# ---------------------------------------------------------------------------


def test_plan_default_lookback_returns_ordered_dates():
    """(c) Default-lookback mode: UdmTablesList has LookbackDays=3, no
    policy rows, no prior success — returns 3 dates ascending.
    """
    from orchestration import range_scheduler as mod

    # cursor 1: UdmTablesList lookup — FirstLoadDate=2024-01-01, LookbackDays=3
    # cursor 2: ExtractionRangePolicy lookup — no rows.
    cur_udm = _make_cursor(fetchone_returns=(date(2024, 1, 1), 3))
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

    assert plan.policy_source == "default-lookback"
    assert plan.dates == [
        date(2025, 1, 13), date(2025, 1, 14), date(2025, 1, 15),
    ]
    # No prior success — every date flagged as first-time (not re-extraction).
    assert all(not v for v in plan.re_extraction_flags.values())
    assert set(plan.re_extraction_flags.keys()) == set(plan.dates)


# ---------------------------------------------------------------------------
# (d) Policy mode happy path — explicit range from ExtractionRangePolicy
# ---------------------------------------------------------------------------


def test_plan_policy_mode_unions_active_ranges():
    """(d) Policy mode: an active ExtractionRangePolicy row drives the
    schedule; policy_source reflects the explicit path.
    """
    from orchestration import range_scheduler as mod

    cur_udm = _make_cursor(fetchone_returns=(date(2024, 1, 1), 7))
    cur_policy = _make_cursor(fetchall_returns=[
        (date(2025, 1, 13), date(2025, 1, 15)),
    ])

    with patch.object(
        mod, "cursor_for",
        _make_multi_cursor_for([cur_udm, cur_policy]),
    ), patch.object(
        mod, "most_recent_success", return_value=date(2025, 1, 14),
    ):
        plan = mod.plan_extraction_range(
            source_name="DNA",
            table_name="ACCT",
            as_of_date=date(2025, 1, 15),
        )

    assert plan.policy_source == "ExtractionRangePolicy"
    assert plan.dates == [
        date(2025, 1, 13), date(2025, 1, 14), date(2025, 1, 15),
    ]
    # Prior success on 2025-01-14: dates <= 01-14 are re-extractions.
    assert plan.re_extraction_flags[date(2025, 1, 13)] is True
    assert plan.re_extraction_flags[date(2025, 1, 14)] is True
    assert plan.re_extraction_flags[date(2025, 1, 15)] is False


# ---------------------------------------------------------------------------
# (e) RangePolicyMissing raised when neither config exists
# ---------------------------------------------------------------------------


def test_plan_raises_range_policy_missing_when_unconfigured():
    """(e) Neither LookbackDays nor an ExtractionRangePolicy row exists —
    must raise RangePolicyMissing (PipelineFatalError per D68).
    """
    from orchestration import range_scheduler as mod
    from utils.errors import PipelineFatalError, RangePolicyMissing

    # UdmTablesList present but LookbackDays=NULL; no policy rows.
    cur_udm = _make_cursor(fetchone_returns=(date(2024, 1, 1), None))
    cur_policy = _make_cursor(fetchall_returns=[])

    with patch.object(
        mod, "cursor_for",
        _make_multi_cursor_for([cur_udm, cur_policy]),
    ), patch.object(
        mod, "most_recent_success", return_value=None,
    ):
        with pytest.raises(RangePolicyMissing) as exc_info:
            mod.plan_extraction_range(
                source_name="DNA",
                table_name="ACCT",
                as_of_date=date(2025, 1, 15),
            )

    # Per D68: RangePolicyMissing inherits PipelineFatalError.
    assert isinstance(exc_info.value, PipelineFatalError)
    # The metadata payload carries the diagnostic context per D76.
    assert exc_info.value.metadata["source_name"] == "DNA"
    assert exc_info.value.metadata["table_name"] == "ACCT"


# ---------------------------------------------------------------------------
# (f) Empty plan is a valid output (everything within FirstLoadDate floor)
# ---------------------------------------------------------------------------


def test_plan_returns_empty_when_clipped_to_zero():
    """(f) Empty ``dates`` list is a valid plan when the rolling window
    falls entirely before FirstLoadDate — the floor clips it to zero.
    """
    from orchestration import range_scheduler as mod

    # FirstLoadDate=2026-01-01, LookbackDays=3, as_of_date=2025-01-15
    # → window [2025-01-13, 2025-01-15] entirely before floor → empty.
    cur_udm = _make_cursor(fetchone_returns=(date(2026, 1, 1), 3))
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

    assert plan.dates == []
    assert plan.re_extraction_flags == {}
    assert plan.policy_source == "default-lookback"
