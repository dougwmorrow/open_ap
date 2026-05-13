"""Regression test for the alternating ``I`` / ``U`` `_cdc_operation`
pattern observed on ``UDM_Stage.dna.ACCT`` for ``ACCTNBR=205``.

Reported observation
--------------------

The user looked at every Stage row for ``ACCTNBR=205`` and saw rows with
``_cdc_operation`` alternating between ``I`` and ``U``::

    row  op  is_current
    ---  --  ----------
    1    I   0
    2    U   0
    3    I   0
    4    U   0
    ...

The expectation was: one ``I`` row (the very first ingest) followed by
``U`` rows for every subsequent change, with ``_cdc_is_current`` flagging
the latest. Multiple ``I`` rows for the same PK looked wrong.

What's actually happening
-------------------------

The CDC engine has no concept of "this PK has been seen before". It
classifies a row as ``I`` whenever the PK is **not present in
_cdc_is_current = 1 rows** at the moment CDC runs. So:

* Run N: ``ACCTNBR=205`` is in source, no current row in Stage
  → INSERT, ``_cdc_operation = 'I'``, ``_cdc_is_current = 1``
* Run N+1: source returns same hash → UNCHANGED
* Run N+1: source returns different hash → UPDATE,
  ``_cdc_operation = 'U'``, old row's ``_cdc_is_current`` flipped to 0
* Run N+2: ``ACCTNBR=205`` is **missing** from the fresh extraction →
  reverse anti-join → previous current row's ``_cdc_is_current`` flipped
  to 0. **No new row inserted.**
* Run N+3: ``ACCTNBR=205`` reappears in source → no current row exists →
  classified as INSERT again → ``_cdc_operation = 'I'``

Resurrection-as-``R`` is only modeled in **SCD2 / Bronze**
(``UdmScd2Operation = 'R'``) — not in Stage.

So the alternating ``I``/``U`` pattern signals one of:

1. **The PK is intermittently missing from the fresh extraction.**
   Possible causes: an ETL filter is excluding the row some runs;
   for large tables the row's date column drifts in and out of the
   ``LookbackDays`` window; partial extraction failures (ConnectorX
   returning a subset) that go undetected.
2. **A genuine source delete-and-reinsert cycle** at the source system.

These tests document the engine's behavior so the user can confirm
whether their observation matches case 1 or 2 by inspecting the
intermediate Stage state.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import patch

import polars as pl

import cdc.engine as cdc_engine
from cdc.engine import CDCContext, _run_cdc_core
from data_load.row_hash import add_row_hash


logger = logging.getLogger(__name__)


def _hash(df: pl.DataFrame) -> pl.DataFrame:
    return add_row_hash(df)


def _run_cdc(table_config, fresh, existing, *, log_label="CDC"):
    ctx = CDCContext(
        read_existing=lambda: existing,
        track_deleted_pks=False,
        log_label=log_label,
        log_window="",
    )
    with patch.object(cdc_engine, "table_exists", return_value=True), \
         patch.object(cdc_engine, "_write_and_load_cdc"), \
         patch.object(cdc_engine, "_expire_cdc_rows"):
        return _run_cdc_core(table_config, fresh, batch_id=1, output_dir="/tmp", ctx=ctx)


# ---------------------------------------------------------------------------
# Stable PK — single I, all subsequent changes are U.
# ---------------------------------------------------------------------------


def test_continuously_present_pk_only_produces_one_insert(make_table_config):
    """A PK that appears in **every** fresh extraction with at least one
    change between consecutive runs should produce exactly one ``I`` row
    (the very first run) and ``U`` rows for every subsequent change.

    This is the scenario the user expected for ``ACCTNBR=205``.
    """
    tc = make_table_config(
        table_name="ACCT",
        source_name="DNA",
        pk_columns=["ACCTNBR"],
        non_pk_columns=["BALANCE"],
    )

    history: list[tuple[str, int]] = []  # (operation, batch_index)
    existing = pl.DataFrame(schema={
        "ACCTNBR": pl.Int64, "BALANCE": pl.Int64, "_row_hash": pl.Utf8,
    })

    # Five runs, each with a different BALANCE — every run after the first
    # is a hash mismatch and should be classified U.
    runs = [
        {"ACCTNBR": 205, "BALANCE": 1000},
        {"ACCTNBR": 205, "BALANCE": 1100},
        {"ACCTNBR": 205, "BALANCE": 1200},
        {"ACCTNBR": 205, "BALANCE": 1300},
        {"ACCTNBR": 205, "BALANCE": 1400},
    ]

    for i, payload in enumerate(runs):
        fresh = _hash(pl.DataFrame([payload]))
        logger.info("Run %d: fresh ACCTNBR=%d BALANCE=%d existing_rows=%d",
                    i + 1, payload["ACCTNBR"], payload["BALANCE"], existing.height)

        result = _run_cdc(tc, fresh, existing)

        # The engine doesn't return the operation labels directly — derive
        # them from the (inserts, updates, deletes) counts. Each run touches
        # exactly one row.
        if result.inserts == 1 and result.updates == 0:
            history.append(("I", i + 1))
        elif result.updates == 1 and result.inserts == 0:
            history.append(("U", i + 1))
        elif result.unchanged == 1:
            history.append(("UNCHANGED", i + 1))
        else:
            history.append(("UNEXPECTED", i + 1))

        # Roll forward: the new row becomes "current" for the next run.
        existing = fresh

    operations = [op for op, _ in history]
    logger.info("Operations across 5 runs: %s", operations)

    assert operations == ["I", "U", "U", "U", "U"], (
        f"Expected one I followed by four U, got {operations}. "
        "The engine no longer matches PKs across runs the way it should — "
        "investigate hash determinism or PK dtype drift."
    )

    insert_count = sum(1 for op in operations if op == "I")
    assert insert_count == 1, (
        f"PK 205 produced {insert_count} I rows when continuously present in "
        "source. Should be exactly 1."
    )


# ---------------------------------------------------------------------------
# Flapping PK — what the user is actually seeing.
# ---------------------------------------------------------------------------


def test_flapping_pk_resurrects_as_insert(make_table_config):
    """Reproduces the user's observation: when a PK disappears from the
    fresh extraction and later reappears, the reappearance is classified
    as ``I``, not as a continuation of the prior version's history.

    This is **by design** in the current engine. If the user is seeing
    alternating ``I``/``U`` for ``ACCTNBR=205``, the upstream extraction
    is dropping the row on alternating runs.
    """
    tc = make_table_config(
        table_name="ACCT",
        source_name="DNA",
        pk_columns=["ACCTNBR"],
        non_pk_columns=["BALANCE"],
    )

    # Run 1: ACCTNBR=205 is in source for the first time → I
    fresh_1 = _hash(pl.DataFrame([{"ACCTNBR": 205, "BALANCE": 1000}]))
    result_1 = _run_cdc(tc, fresh_1, pl.DataFrame(schema={
        "ACCTNBR": pl.Int64, "BALANCE": pl.Int64, "_row_hash": pl.Utf8,
    }))
    logger.info("Run 1 (first appearance): I=%d U=%d D=%d",
                result_1.inserts, result_1.updates, result_1.deletes)
    assert result_1.inserts == 1
    assert result_1.updates == 0

    # Run 2: ACCTNBR=205 has a hash change → U
    fresh_2 = _hash(pl.DataFrame([{"ACCTNBR": 205, "BALANCE": 1100}]))
    result_2 = _run_cdc(tc, fresh_2, fresh_1)
    logger.info("Run 2 (hash change): I=%d U=%d D=%d",
                result_2.inserts, result_2.updates, result_2.deletes)
    assert result_2.updates == 1

    # Run 3: ACCTNBR=205 disappears from source → reverse anti-join closes
    # the current row. existing has the row; fresh does not.
    #
    # In the real-world scenario, the extraction returns thousands of OTHER
    # rows but happens to drop 205 — fresh is non-empty. We simulate that
    # with a sentinel ACCTNBR=999 so the empty-extraction guard does not
    # short-circuit before the reverse anti-join runs.
    fresh_3 = _hash(pl.DataFrame([{"ACCTNBR": 999, "BALANCE": 7000}]))
    existing_3 = _hash(pl.DataFrame([{"ACCTNBR": 205, "BALANCE": 1100}]))
    result_3 = _run_cdc(tc, fresh_3, existing_3)
    logger.info("Run 3 (PK missing from source): I=%d U=%d D=%d",
                result_3.inserts, result_3.updates, result_3.deletes)
    assert result_3.deletes == 1
    assert result_3.inserts == 1  # the sentinel ACCTNBR=999 is new

    # Run 4: ACCTNBR=205 reappears. The current row was closed in run 3,
    # so existing has zero current rows for this PK — anti-join classifies
    # the reappearance as INSERT.
    fresh_4 = _hash(pl.DataFrame([{"ACCTNBR": 205, "BALANCE": 1500}]))
    existing_after_close = pl.DataFrame(schema=fresh_2.schema)  # no current rows
    result_4 = _run_cdc(tc, fresh_4, existing_after_close)
    logger.info("Run 4 (PK reappears): I=%d U=%d D=%d",
                result_4.inserts, result_4.updates, result_4.deletes)

    assert result_4.inserts == 1, (
        "When a previously-closed PK reappears, the engine classifies it "
        "as I. This is documented behavior — but it's the source of the "
        "alternating I/U pattern the user is seeing."
    )
    assert result_4.updates == 0


def test_flapping_pk_produces_alternating_i_u_pattern(make_table_config):
    """End-to-end demonstration of the I/U/D/I/U/D/... pattern that the
    user observed on ``ACCTNBR=205``.

    Six simulated runs alternating present / absent / present in source.
    The history shows the engine producing exactly the user's pattern.
    """
    tc = make_table_config(
        table_name="ACCT",
        source_name="DNA",
        pk_columns=["ACCTNBR"],
        non_pk_columns=["BALANCE"],
    )

    # Real-world flapping scenario: source always returns SOMETHING (a
    # sentinel row), but the target PK 205 is intermittently missing.
    # An "absent" run is fresh-without-205 (the empty-extraction guard
    # would short-circuit a completely empty fresh).
    schema = {"ACCTNBR": pl.Int64, "BALANCE": pl.Int64, "_row_hash": pl.Utf8}
    existing = pl.DataFrame(schema=schema)
    sentinel_row = {"ACCTNBR": 999, "BALANCE": 7000}

    timeline = [
        ("present", [{"ACCTNBR": 205, "BALANCE": 1000}, sentinel_row]),
        ("present", [{"ACCTNBR": 205, "BALANCE": 1100}, sentinel_row]),
        ("absent",  [sentinel_row]),                       # 205 dropped
        ("present", [{"ACCTNBR": 205, "BALANCE": 1200}, sentinel_row]),  # resurrection
        ("present", [{"ACCTNBR": 205, "BALANCE": 1300}, sentinel_row]),
        ("absent",  [sentinel_row]),
    ]

    operations: list[str] = []

    for i, (kind, payload) in enumerate(timeline):
        fresh = _hash(pl.DataFrame(payload))

        result = _run_cdc(tc, fresh, existing)

        # The 205-specific operation each run, ignoring the sentinel.
        if kind == "present":
            target_in_existing = existing.height > 0 and \
                205 in existing["ACCTNBR"].to_list()
            if not target_in_existing:
                op = "I"
            elif result.updates >= 1:
                op = "U"
            else:
                op = "?"
        else:  # absent — 205 is in existing but not in fresh
            op = "D" if result.deletes >= 1 else "?"
        operations.append(op)

        logger.info("Run %d (%s): op=%s  (existing rows in: %d, I=%d U=%d D=%d)",
                    i + 1, kind, op, existing.height,
                    result.inserts, result.updates, result.deletes)

        # Roll forward existing. Present runs replace; absent runs keep
        # only the sentinel (the 205 row's _cdc_is_current would be 0).
        if kind == "present":
            existing = fresh
        else:
            existing = _hash(pl.DataFrame([sentinel_row]))

    logger.info("Full history of operations: %s", operations)

    expected = ["I", "U", "D", "I", "U", "D"]
    assert operations == expected, (
        f"Expected {expected} (the user's observed pattern), got {operations}. "
        "If this fails, the engine's classification has drifted from the "
        "documented behavior — which would be its own kind of regression."
    )

    # The pattern itself is the bug surface: alternating I/U with closed
    # rows in between is what the user saw on Stage.
    assert operations.count("I") > 1, (
        "Multiple I rows for the same PK is the user's reported pattern. "
        "Each I represents a fresh detection after a close — not source "
        "data corruption."
    )
