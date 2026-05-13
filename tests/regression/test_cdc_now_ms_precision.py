"""Regression tests for the CDC expire double-close bug — the precision
mismatch between BCP-stored ``_cdc_valid_from`` (millisecond, per the
BCP CSV Contract) and the pyodbc ``batch_valid_from`` parameter
(microsecond, preserved end-to-end).

Background
----------

The expire UPDATE in ``cdc/engine.py:_expire_cdc_rows`` carries a
``WHERE _cdc_valid_from < ?`` predicate intended to exclude rows the
*current* batch just inserted. If the BCP-stored value is rounded to
millisecond precision while the parameter retains microseconds, strict
``<`` matches the just-inserted row and the expire UPDATE clobbers its
own batch's writes.

Symptom in production: every PK with a non-zero microsecond fraction in
the engine's ``now`` had its U row inserted *and* immediately closed
inside the same batch. Stage ended each run with no
``_cdc_is_current=1`` row for those PKs. The next run reclassified them
as ``I``. The user observed the alternating ``I/U/I/U`` pattern on
ACCTNBR=205 and across 138,725 PKs in DNA.ACCT.

Fix
---

``cdc.engine._cdc_now_ms`` truncates ``now`` to naive UTC wall time
with millisecond precision so the BCP-stored value and the pyodbc
parameter are bit-identical. Strict ``<`` now correctly excludes the
just-inserted row.

These tests assert both the helper's shape and that ``_run_cdc_core``
passes the helper's output to ``_expire_cdc_rows`` unchanged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import patch

import polars as pl

import cdc.engine as cdc_engine
from cdc.engine import CDCContext, _cdc_now_ms, _run_cdc_core
from data_load.row_hash import add_row_hash


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper-level invariants
# ---------------------------------------------------------------------------


def test_cdc_now_ms_is_naive():
    """The pyodbc / DATETIME2 alignment requires naive (no tzinfo).
    A tz-aware parameter sends as DATETIMEOFFSET and triggers an
    implicit timezone conversion in SQL Server when compared against
    the BCP-stored DATETIME2 value (SCD2-P1-f, applied to CDC).
    """
    n = _cdc_now_ms()

    logger.info("Returned: %s (tzinfo=%s)", n, n.tzinfo)

    assert n.tzinfo is None


def test_cdc_now_ms_truncates_microseconds_to_milliseconds():
    """BCP CSV writes ``'%Y-%m-%d %H:%M:%S.%3f'`` (millisecond precision).
    The pyodbc parameter must match — every microsecond beyond the third
    digit must be zero.
    """
    # Run multiple iterations to defend against the rare case where the
    # raw microsecond happens to already be a multiple of 1000.
    for _ in range(20):
        n = _cdc_now_ms()
        assert n.microsecond % 1000 == 0, (
            f"_cdc_now_ms() returned microsecond={n.microsecond} which is "
            f"not a multiple of 1000. BCP would round this to a different "
            f"value than what pyodbc sends, re-introducing the expire "
            f"double-close bug."
        )


def test_cdc_now_ms_close_to_now():
    """Sanity: the returned value should track wall time, not be a stale
    constant. Within 5 seconds of ``datetime.utcnow()`` on a healthy host.
    """
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    n = _cdc_now_ms()
    after = datetime.now(timezone.utc).replace(tzinfo=None)

    logger.info("before=%s n=%s after=%s", before, n, after)

    # Allow a generous window for slow CI hosts.
    assert (n - before).total_seconds() >= -1
    assert (after - n).total_seconds() >= -1
    assert abs((n - before).total_seconds()) < 5


# ---------------------------------------------------------------------------
# Engine integration — does _run_cdc_core hand the right value to expire?
# ---------------------------------------------------------------------------


def _hash(df: pl.DataFrame) -> pl.DataFrame:
    return add_row_hash(df)


def test_run_cdc_core_passes_ms_precision_batch_valid_from(make_table_config):
    """Drive _run_cdc_core through an UPDATE batch and capture the call
    to ``_expire_cdc_rows``. Assert that ``batch_valid_from`` carries
    naive, millisecond-precision time — the conditions under which the
    expire predicate ``_cdc_valid_from < batch_valid_from`` correctly
    excludes the just-inserted row.

    Without the fix this assertion fails: the engine would send a
    microsecond-precision (and tz-aware) datetime, the BCP-stored
    ``_cdc_valid_from`` would round to milliseconds, and strict ``<``
    would match the just-inserted U row.
    """
    tc = make_table_config(
        table_name="ACCT", source_name="DNA",
        pk_columns=["ACCTNBR"], non_pk_columns=["BALANCE"],
    )

    fresh = _hash(pl.DataFrame([{"ACCTNBR": 205, "BALANCE": 1100}]))
    existing = _hash(pl.DataFrame([{"ACCTNBR": 205, "BALANCE": 1000}]))

    ctx = CDCContext(
        read_existing=lambda: existing,
        track_deleted_pks=False,
        log_label="CDC",
        log_window="",
    )

    with patch.object(cdc_engine, "table_exists", return_value=True), \
         patch.object(cdc_engine, "_write_and_load_cdc"), \
         patch.object(cdc_engine, "_expire_cdc_rows") as expire_mock:
        result = _run_cdc_core(tc, fresh, batch_id=1, output_dir="/tmp", ctx=ctx)

    # Confirm we actually drove the engine through an UPDATE classification —
    # otherwise the expire mock is never called and the assertion below is
    # vacuously true.
    assert result.updates == 1, (
        f"Expected 1 update, got {result.updates}. The test setup didn't "
        f"reach the expire path."
    )
    assert expire_mock.called, "Expected _expire_cdc_rows to be called for an UPDATE batch"

    call = expire_mock.call_args

    # _expire_cdc_rows is called with batch_valid_from as a keyword arg.
    # The 4th positional arg (valid_to) should be the same value.
    bvf = call.kwargs.get("batch_valid_from")
    assert bvf is not None, (
        f"batch_valid_from kwarg missing from expire call. "
        f"Args: {call.args}, kwargs: {call.kwargs}"
    )

    logger.info("batch_valid_from passed to expire: %s (tzinfo=%s, microsecond=%d)",
                bvf, bvf.tzinfo, bvf.microsecond)

    assert bvf.tzinfo is None, (
        f"batch_valid_from is tz-aware ({bvf.tzinfo}). pyodbc will send "
        f"this as DATETIMEOFFSET; SQL Server's implicit conversion to "
        f"DATETIME2 in the WHERE clause produces a different UTC moment "
        f"than what BCP stored. SCD2-P1-f / CDC-NOW-MS invariant violated."
    )
    assert bvf.microsecond % 1000 == 0, (
        f"batch_valid_from microsecond={bvf.microsecond} is not a "
        f"multiple of 1000. BCP rounds the just-inserted "
        f"_cdc_valid_from to milliseconds; the expire predicate's "
        f"strict < will then incorrectly match the just-inserted row "
        f"and clobber it. CDC-NOW-MS invariant violated."
    )

    # Same value should appear as the 4th positional arg (valid_to)
    # because the engine reuses the single ``now`` variable for both.
    valid_to_arg = call.args[3]
    assert valid_to_arg == bvf, (
        f"valid_to ({valid_to_arg}) and batch_valid_from ({bvf}) differ. "
        f"They are supposed to be the same datetime instance — drift "
        f"between them re-introduces the precision bug."
    )
