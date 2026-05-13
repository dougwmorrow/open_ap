"""PK filtering and coercion — P0-4 and P0-4b safeguards.

NULL primary keys break CDC anti-joins (NULL != NULL → every "match" fails,
producing perpetual re-inserts) and SCD2 business-key matching. These tests
verify that the filter and the empty-string sentinel coercion both operate
correctly before CDC sees the data.
"""
from __future__ import annotations

import logging

import polars as pl

from cdc.engine import (
    CDCResult,
    _BLANK_PK_SENTINEL,
    _coerce_blank_pks,
    _filter_null_pks,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# P0-4 — NULL PK filter
# ---------------------------------------------------------------------------


def test_filter_null_pk_drops_null_rows(make_table_config):
    """Rows with NULL in the PK column must be removed before CDC."""
    tc = make_table_config(pk_columns=["PK_ID"], non_pk_columns=["VALUE"])

    df = pl.DataFrame({
        "PK_ID": [1, None, 3, None],
        "VALUE": ["a", "b", "c", "d"],
    })

    logger.info("Input rows: %d (PKs: %s)", df.height, df["PK_ID"].to_list())

    result = CDCResult()
    filtered = _filter_null_pks(df, ["PK_ID"], tc, result)

    logger.info("Filtered rows: %d", filtered.height)
    logger.info("null_pk_rows tracked: %d", result.null_pk_rows)
    logger.info("Surviving PKs: %s", filtered["PK_ID"].to_list())

    assert filtered.height == 2
    assert filtered["PK_ID"].to_list() == [1, 3]
    assert result.null_pk_rows == 2


def test_filter_null_pk_multi_column_pk(make_table_config):
    """For composite PKs, a NULL in any one component disqualifies the row."""
    tc = make_table_config(pk_columns=["KEY1", "KEY2"])

    df = pl.DataFrame({
        "KEY1": [1, None, 3, 4],
        "KEY2": ["a", "b", None, "d"],
        "VALUE": ["v1", "v2", "v3", "v4"],
    })

    logger.info("Composite PK input: %d rows", df.height)

    result = CDCResult()
    filtered = _filter_null_pks(df, ["KEY1", "KEY2"], tc, result)

    logger.info("Surviving rows: %s", filtered.to_dicts())
    logger.info("null_pk_rows tracked: %d", result.null_pk_rows)

    assert filtered.height == 2
    assert result.null_pk_rows == 2
    surviving = set(zip(filtered["KEY1"].to_list(), filtered["KEY2"].to_list()))
    assert surviving == {(1, "a"), (4, "d")}


def test_filter_null_pk_no_nulls_passes_through(make_table_config):
    """Clean input — no rows dropped, no count incremented."""
    tc = make_table_config(pk_columns=["PK_ID"])
    df = pl.DataFrame({"PK_ID": [1, 2, 3], "VALUE": ["a", "b", "c"]})

    result = CDCResult()
    filtered = _filter_null_pks(df, ["PK_ID"], tc, result)

    logger.info("Clean input: %d rows in, %d rows out", df.height, filtered.height)

    assert filtered.height == 3
    assert result.null_pk_rows == 0


# ---------------------------------------------------------------------------
# P0-4b — Empty-string PK coercion
# ---------------------------------------------------------------------------


def test_blank_string_pk_coerced_to_sentinel(make_table_config):
    """Empty-string PK values become ``<BLANK>`` rather than NULL.

    BCP character mode silently converts ``''`` to NULL during load, which
    would then fail the P0-4 NULL PK filter and drop the row. The coercion
    keeps the row alive with a deterministic substitute value.
    """
    tc = make_table_config(pk_columns=["PK_ID"])

    df = pl.DataFrame({
        "PK_ID": ["abc", "", "def", "   "],  # last one is whitespace-only
        "VALUE": ["a", "b", "c", "d"],
    })

    logger.info("Input PKs (with blanks): %s", df["PK_ID"].to_list())

    coerced = _coerce_blank_pks(df, ["PK_ID"], tc)

    logger.info("After coercion: %s", coerced["PK_ID"].to_list())

    pks = coerced["PK_ID"].to_list()
    assert pks[0] == "abc"
    assert pks[1] == _BLANK_PK_SENTINEL
    assert pks[2] == "def"
    assert pks[3] == _BLANK_PK_SENTINEL, (
        "Whitespace-only PK should also be coerced — strip_chars before compare"
    )


def test_blank_pk_coercion_skips_non_string_columns(make_table_config):
    """Numeric PK columns can't have empty strings; coercion is a no-op."""
    tc = make_table_config(pk_columns=["PK_ID"])

    df = pl.DataFrame({"PK_ID": [1, 2, 3], "VALUE": ["a", "b", "c"]})

    logger.info("Numeric PK input dtype: %s", df["PK_ID"].dtype)

    coerced = _coerce_blank_pks(df, ["PK_ID"], tc)

    logger.info("After coercion: %s", coerced["PK_ID"].to_list())

    assert coerced["PK_ID"].to_list() == [1, 2, 3]
    assert coerced["PK_ID"].dtype == pl.Int64


def test_blank_pk_coercion_already_sentinel_unchanged(make_table_config):
    """If a row already has the sentinel, leave it alone — idempotent."""
    tc = make_table_config(pk_columns=["PK_ID"])

    df = pl.DataFrame({
        "PK_ID": ["abc", _BLANK_PK_SENTINEL, "def"],
        "VALUE": ["a", "b", "c"],
    })

    logger.info("Input includes sentinel: %s", df["PK_ID"].to_list())

    coerced = _coerce_blank_pks(df, ["PK_ID"], tc)

    logger.info("After coercion: %s", coerced["PK_ID"].to_list())

    assert coerced["PK_ID"].to_list() == ["abc", _BLANK_PK_SENTINEL, "def"]
