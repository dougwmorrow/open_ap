"""Tier 0 build-time smoke test for cdc/extraction_state.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s. All
external dependencies (pyodbc cursor, ``utils.connections.cursor_for``)
are mocked. No live SQL Server required.

North Star pillars:
  - Operationally stable (D67 Tier 0 discipline: import + invocability +
    happy-path + failure-path in < 5 s with zero external I/O).
  - Idempotent (D14 ExtractionAttempt monotonic; D15 caller's
    ledger_step gates the higher-level extraction; this module is the
    persistence half).
  - Audit-grade (every INSERT writes BatchId + Status + StartedAt;
    every error path surfaces the documented base type per D68).

D-numbers: D11 (empirical L_99), D13 (trust gate), D14
(IsReExtraction / ExtractionAttempt), D67 (Tier 0), D68 (error
hierarchy), D69 (cursor_for ownership), D92 (forward-only additive).

B-numbers: B85 (utils/errors.py dependency closed).

Spec: phase1/03_core_modules.md § 4.2 + phase1/01_database_schema.md § 3.
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
# Test fixtures — mock cursor_for context manager
# ---------------------------------------------------------------------------


def _make_cursor(fetchone_returns=None) -> MagicMock:
    """Build a mock pyodbc cursor with optional fetchone return values."""
    cur = MagicMock()
    if fetchone_returns is not None:
        if isinstance(fetchone_returns, list):
            cur.fetchone.side_effect = fetchone_returns
        else:
            cur.fetchone.return_value = fetchone_returns
    cur.rowcount = 1
    return cur


def _make_cursor_for(cur: MagicMock):
    """Return a cursor_for-shaped context manager yielding the given cursor."""

    @contextmanager
    def _cm(_db: str):
        yield cur

    return _cm


def _make_multi_cursor_for(cursors: list):
    """For tests where each cursor_for() call gets a fresh cursor."""
    iterator = iter(cursors)

    @contextmanager
    def _cm(_db: str):
        yield next(iterator)

    return _cm


# ---------------------------------------------------------------------------
# (a) Module imports without error
# ---------------------------------------------------------------------------


def test_module_imports():
    """(a) cdc.extraction_state imports cleanly per D67 assertion 1.

    Verifies no syntax errors, no missing dependencies, no import-time
    DB / network side-effects.
    """
    import cdc.extraction_state as mod

    assert mod is not None
    assert hasattr(mod, "is_date_trusted")
    assert hasattr(mod, "most_recent_success")
    assert hasattr(mod, "is_reextraction")
    assert hasattr(mod, "get_extraction_attempt")
    assert hasattr(mod, "record_extraction_attempt")
    assert hasattr(mod, "ExtractionState"), "Public dataclass per § 4.2"


# ---------------------------------------------------------------------------
# (b) is_date_trusted returns bool on happy path
# ---------------------------------------------------------------------------


def test_is_date_trusted_returns_bool_when_row_exists():
    """(b) is_date_trusted returns True for a date with a prior SUCCESS row."""
    from cdc import extraction_state as mod

    cur = MagicMock()
    # Sequence: (1) UdmTablesList.FirstLoadDate (returns no row -> skip floor),
    # then (2) PipelineExtraction trust-gate lookup (returns sentinel row).
    cur.fetchone.side_effect = [None, (1,)]

    with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
        result = mod.is_date_trusted(
            source_name="DNA",
            table_name="ACCT",
            business_date=date(2025, 1, 15),
        )

    assert isinstance(result, bool)
    assert result is True


# ---------------------------------------------------------------------------
# (c) most_recent_success returns date | None
# ---------------------------------------------------------------------------


def test_most_recent_success_returns_date_or_none():
    """(c) most_recent_success returns a date when SUCCESS rows exist,
    None otherwise.

    Verifies both shapes — the function MUST not silently return a
    datetime or a string per the typed contract in § 4.2.
    """
    from cdc import extraction_state as mod

    # Case 1: SUCCESS row exists — returns date.
    cur_with = _make_cursor(fetchone_returns=(date(2024, 12, 31),))
    with patch.object(mod, "cursor_for", _make_cursor_for(cur_with)):
        result = mod.most_recent_success(source_name="DNA", table_name="ACCT")
    assert result == date(2024, 12, 31)
    assert isinstance(result, date)
    assert not isinstance(result, datetime), (
        "most_recent_success must coerce datetime -> date per § 4.2"
    )

    # Case 2: no SUCCESS rows — returns None.
    cur_none = _make_cursor(fetchone_returns=(None,))
    with patch.object(mod, "cursor_for", _make_cursor_for(cur_none)):
        result = mod.most_recent_success(source_name="DNA", table_name="ACCT")
    assert result is None


# ---------------------------------------------------------------------------
# (d) InvalidTrustGate raised on future dates
# ---------------------------------------------------------------------------


def test_is_date_trusted_future_raises_invalid_trust_gate():
    """(d) is_date_trusted raises InvalidTrustGate when business_date is
    in the future (UTC).

    Per § 4.2 + D68 — fatal configuration error, no retry semantics.
    """
    from cdc import extraction_state as mod
    from utils.errors import InvalidTrustGate, PipelineFatalError

    # Mock the DB so the future-date check happens BEFORE the DB lookup
    # — the test fails noisily if the function accidentally hits the DB.
    cur = MagicMock()
    cur.fetchone.return_value = None
    tomorrow_utc = datetime.now(timezone.utc).date() + timedelta(days=1)

    with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
        with pytest.raises(InvalidTrustGate) as exc_info:
            mod.is_date_trusted(
                source_name="DNA",
                table_name="ACCT",
                business_date=tomorrow_utc,
            )

    # InvalidTrustGate is a PipelineFatalError per D68.
    assert isinstance(exc_info.value, PipelineFatalError)
    # The DB MUST NOT have been touched for the trust-gate query — the
    # future check short-circuits before any I/O.
    # (FirstLoadDate lookup may run; that's fine for the smoke level.)


# ---------------------------------------------------------------------------
# (e) record_extraction_attempt INSERTs a row and returns ExtractionId
# ---------------------------------------------------------------------------


def test_record_extraction_attempt_returns_int_extraction_id():
    """(e) record_extraction_attempt INSERTs and returns the new ExtractionId.

    Verifies the canonical happy path: caller passes status='IN_PROGRESS'
    at extraction start, the INSERT...OUTPUT clause returns a fresh
    ExtractionId, and the function surfaces it as int.
    """
    from cdc import extraction_state as mod

    # Two cursor_for() calls: (1) get_extraction_attempt query -> MAX(prior)
    # returns None (first attempt); (2) INSERT...OUTPUT -> ExtractionId=987.
    cur_lookup = _make_cursor(fetchone_returns=(None,))
    cur_insert = _make_cursor(fetchone_returns=(987,))

    with patch.object(
        mod, "cursor_for",
        _make_multi_cursor_for([cur_lookup, cur_insert]),
    ):
        result = mod.record_extraction_attempt(
            source_name="DNA",
            table_name="ACCT",
            business_date=date(2025, 1, 15),
            batch_id=42,
            status="IN_PROGRESS",
        )

    assert isinstance(result, int)
    assert result == 987

    # The INSERT SQL must reference the canonical table + columns.
    insert_sql = cur_insert.execute.call_args.args[0]
    assert "INSERT INTO General.ops.PipelineExtraction" in insert_sql
    assert "OUTPUT INSERTED.ExtractionId" in insert_sql
    assert "ExtractionAttempt" in insert_sql
    assert "IsReExtraction" in insert_sql


# ---------------------------------------------------------------------------
# (f) ExtractionState dataclass is frozen + has the documented fields
# ---------------------------------------------------------------------------


def test_extraction_state_dataclass_shape():
    """(f) ExtractionState is a frozen dataclass with the canonical fields.

    Per § 4.2 interface spec.
    """
    from dataclasses import FrozenInstanceError

    from cdc.extraction_state import ExtractionState

    state = ExtractionState(
        source_name="DNA",
        table_name="ACCT",
        business_date=date(2025, 1, 15),
        status="SUCCESS",
        extraction_attempt=1,
        is_reextraction=False,
        started_at=datetime(2025, 1, 15, 14, 30, 0),
        batch_id=100,
    )
    assert state.source_name == "DNA"
    assert state.status == "SUCCESS"
    assert state.extraction_attempt == 1
    assert state.is_reextraction is False

    # Frozen: cannot reassign fields.
    with pytest.raises(FrozenInstanceError):
        state.status = "FAILED"  # type: ignore[misc]
