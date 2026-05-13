"""End-to-end CDC change detection — exercises ``_run_cdc_core`` with a
synthetic ``CDCContext`` so no DB is needed.

Covers the four classifications:

* INSERT — PK in fresh, not in existing
* UPDATE — PK in both, hash differs
* UNCHANGED — PK in both, hash matches
* DELETE — PK in existing, not in fresh

Plus the P0-12 count invariant: ``inserts + updates + unchanged ==
len(df_fresh)``.

The test mocks ``_write_and_load_cdc`` and ``_expire_cdc_rows`` to no-ops
so we observe the *classification* without writing to SQL Server. The
classification is the part that determines the operation labels in Stage —
it's what answers the user's question about why ACCT 205 has alternating
I and U.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import polars as pl

import cdc.engine as cdc_engine
from cdc.engine import CDCContext, _run_cdc_core
from data_load.row_hash import add_row_hash


logger = logging.getLogger(__name__)


def _hash(df: pl.DataFrame) -> pl.DataFrame:
    return add_row_hash(df)


# ---------------------------------------------------------------------------
# Helper — invoke _run_cdc_core with mocked DB writes.
# ---------------------------------------------------------------------------


def _run_with_existing(
    table_config,
    df_fresh: pl.DataFrame,
    df_existing: pl.DataFrame,
    *,
    log_label: str = "CDC",
):
    """Run ``_run_cdc_core`` with ``df_existing`` as the synthetic Stage
    state. Returns the ``CDCResult``.

    Mocks ``_write_and_load_cdc`` and ``_expire_cdc_rows`` so no SQL Server
    is touched, and forces ``table_exists`` to True so we hit the change-
    detection branch (not the first-run-all-inserts branch).
    """
    ctx = CDCContext(
        read_existing=lambda: df_existing,
        track_deleted_pks=False,
        log_label=log_label,
        log_window="",
    )

    with patch.object(cdc_engine, "table_exists", return_value=True), \
         patch.object(cdc_engine, "_write_and_load_cdc"), \
         patch.object(cdc_engine, "_expire_cdc_rows"):
        return _run_cdc_core(table_config, df_fresh, batch_id=1, output_dir="/tmp", ctx=ctx)


# ---------------------------------------------------------------------------
# Single-class scenarios
# ---------------------------------------------------------------------------


def test_all_new_pks_classified_as_inserts(make_table_config):
    tc = make_table_config(pk_columns=["PK_ID"], non_pk_columns=["VALUE"])
    fresh = _hash(pl.DataFrame({"PK_ID": [1, 2, 3], "VALUE": ["a", "b", "c"]}))
    existing = _hash(pl.DataFrame({"PK_ID": [], "VALUE": []}, schema={"PK_ID": pl.Int64, "VALUE": pl.Utf8}))

    logger.info("Fresh PKs: %s, existing PKs: %s",
                fresh["PK_ID"].to_list(), existing["PK_ID"].to_list())

    result = _run_with_existing(tc, fresh, existing)

    logger.info("Result: I=%d U=%d D=%d Unchanged=%d",
                result.inserts, result.updates, result.deletes, result.unchanged)

    assert result.inserts == 3
    assert result.updates == 0
    assert result.deletes == 0
    assert result.unchanged == 0


def test_hash_change_classified_as_update(make_table_config):
    tc = make_table_config(pk_columns=["PK_ID"], non_pk_columns=["VALUE"])
    existing = _hash(pl.DataFrame({"PK_ID": [1, 2], "VALUE": ["old1", "old2"]}))
    fresh = _hash(pl.DataFrame({"PK_ID": [1, 2], "VALUE": ["new1", "new2"]}))

    logger.info("Existing hashes: %s", existing["_row_hash"].to_list())
    logger.info("Fresh hashes:    %s", fresh["_row_hash"].to_list())

    result = _run_with_existing(tc, fresh, existing)

    logger.info("Result: I=%d U=%d D=%d Unchanged=%d",
                result.inserts, result.updates, result.deletes, result.unchanged)

    assert result.inserts == 0
    assert result.updates == 2
    assert result.deletes == 0
    assert result.unchanged == 0


def test_identical_data_classified_as_unchanged(make_table_config):
    """Idempotency — re-running CDC on the same data must produce zero changes."""
    tc = make_table_config(pk_columns=["PK_ID"], non_pk_columns=["VALUE"])

    fresh = _hash(pl.DataFrame({"PK_ID": [1, 2, 3], "VALUE": ["a", "b", "c"]}))
    existing = fresh.clone()

    logger.info("Identical fresh and existing — expecting zero changes")

    result = _run_with_existing(tc, fresh, existing)

    logger.info("Result: I=%d U=%d D=%d Unchanged=%d",
                result.inserts, result.updates, result.deletes, result.unchanged)

    assert result.inserts == 0
    assert result.updates == 0
    assert result.deletes == 0
    assert result.unchanged == 3, (
        "Idempotency broken — re-running CDC on identical data produced "
        f"{result.inserts} inserts and {result.updates} updates."
    )


def test_missing_pk_classified_as_delete(make_table_config):
    """Reverse anti-join — PK in existing but missing from fresh."""
    tc = make_table_config(pk_columns=["PK_ID"], non_pk_columns=["VALUE"])
    existing = _hash(pl.DataFrame({"PK_ID": [1, 2, 3], "VALUE": ["a", "b", "c"]}))
    fresh = _hash(pl.DataFrame({"PK_ID": [1, 3], "VALUE": ["a", "c"]}))

    logger.info("Existing PKs: %s", existing["PK_ID"].to_list())
    logger.info("Fresh PKs:    %s (PK 2 is gone)", fresh["PK_ID"].to_list())

    result = _run_with_existing(tc, fresh, existing)

    logger.info("Result: I=%d U=%d D=%d Unchanged=%d",
                result.inserts, result.updates, result.deletes, result.unchanged)

    assert result.deletes == 1
    assert result.unchanged == 2


# ---------------------------------------------------------------------------
# Mixed scenario + count invariant
# ---------------------------------------------------------------------------


def test_mixed_changes_account_for_every_fresh_row(make_table_config):
    """P0-12: ``inserts + updates + unchanged == len(df_fresh)`` — every
    row in the fresh extract must land in exactly one classification.
    """
    tc = make_table_config(pk_columns=["PK_ID"], non_pk_columns=["VALUE"])

    existing = _hash(pl.DataFrame({
        "PK_ID": [1, 2, 3, 99],          # PK 99 will be deleted (missing from fresh)
        "VALUE": ["a", "b", "c", "old"],
    }))
    fresh = _hash(pl.DataFrame({
        "PK_ID": [1, 2, 3, 4, 5],         # 1 unchanged, 2/3 update, 4/5 new
        "VALUE": ["a", "B", "C", "d", "e"],
    }))

    logger.info(
        "Scenario: 1 unchanged (PK 1), 2 updates (PK 2,3), 2 inserts (PK 4,5), 1 delete (PK 99)"
    )

    result = _run_with_existing(tc, fresh, existing)

    logger.info("Counts: I=%d U=%d D=%d Unchanged=%d (fresh=%d)",
                result.inserts, result.updates, result.deletes, result.unchanged,
                fresh.height)

    assert result.inserts == 2
    assert result.updates == 2
    assert result.deletes == 1
    assert result.unchanged == 1

    # P0-12 invariant
    accounted = result.inserts + result.updates + result.unchanged
    assert accounted == fresh.height, (
        f"P0-12: {accounted} accounted rows != {fresh.height} fresh rows. "
        "Some fresh rows fell through classification — possible PK dtype "
        "mismatch causing silent join failures."
    )


# ---------------------------------------------------------------------------
# First-run path — Stage table doesn't exist yet.
# ---------------------------------------------------------------------------


def test_first_run_all_inserts(make_table_config):
    """When the Stage table doesn't exist, every fresh row is an INSERT."""
    tc = make_table_config(pk_columns=["PK_ID"], non_pk_columns=["VALUE"])
    fresh = _hash(pl.DataFrame({"PK_ID": [1, 2, 3], "VALUE": ["a", "b", "c"]}))

    ctx = CDCContext(
        read_existing=lambda: pl.DataFrame(),  # not called when table doesn't exist
        track_deleted_pks=False,
        log_label="CDC",
        log_window="",
    )

    logger.info("Simulating first-ever run — Stage table does not exist")

    with patch.object(cdc_engine, "table_exists", return_value=False), \
         patch.object(cdc_engine, "_write_and_load_cdc"), \
         patch.object(cdc_engine, "_expire_cdc_rows"):
        result = _run_cdc_core(tc, fresh, batch_id=1, output_dir="/tmp", ctx=ctx)

    logger.info("First-run result: I=%d U=%d D=%d Unchanged=%d",
                result.inserts, result.updates, result.deletes, result.unchanged)

    assert result.inserts == 3
    assert result.updates == 0
    assert result.deletes == 0
    assert result.unchanged == 0
