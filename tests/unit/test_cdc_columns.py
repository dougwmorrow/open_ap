"""Tests for ``_add_cdc_columns`` — verifies that the six CDC tracking
columns are added with the correct dtypes.

Critical invariants:

* ``_cdc_is_current`` must be ``Int8`` — BCP rejects Boolean for BIT columns
* ``_cdc_operation`` must carry the supplied label verbatim (``I``, ``U``, ``D``)
* ``_cdc_batch_id`` must be ``Int64``
* ``_cdc_valid_from`` is timezone-aware UTC (Stage reads with TZ)
* ``_cdc_valid_to`` is NULL on the new row (only set when expired)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import polars as pl

from cdc.engine import _add_cdc_columns


logger = logging.getLogger(__name__)


def test_add_cdc_columns_adds_all_six():
    df = pl.DataFrame({"PK_ID": [1, 2, 3], "VALUE": ["a", "b", "c"]})
    valid_from = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)

    result = _add_cdc_columns(df, "I", valid_from, batch_id=42)

    logger.info("Output columns: %s", result.columns)
    expected = {
        "_cdc_operation",
        "_cdc_valid_from",
        "_cdc_valid_to",
        "_cdc_is_current",
        "_cdc_batch_id",
        "UdmModifiedBy",
    }
    missing = expected - set(result.columns)
    assert not missing, f"Missing CDC columns: {missing}"


def test_cdc_is_current_is_int8_not_boolean():
    """BCP CSV writes ``True`` as ``True`` (text), which SQL Server BIT
    rejects. Must be ``Int8`` so it serializes as 0 or 1.
    """
    df = pl.DataFrame({"PK_ID": [1]})
    result = _add_cdc_columns(df, "I", datetime.now(timezone.utc), 1)

    logger.info("_cdc_is_current dtype: %s", result["_cdc_is_current"].dtype)

    assert result["_cdc_is_current"].dtype == pl.Int8, (
        "_cdc_is_current must be Int8 — Boolean would corrupt BCP CSV "
        "(writes as 'True' / 'False' which SQL Server BIT rejects)."
    )
    assert result["_cdc_is_current"][0] == 1


def test_cdc_operation_carries_supplied_label():
    df = pl.DataFrame({"PK_ID": [1]})
    valid_from = datetime.now(timezone.utc)

    for op in ("I", "U", "D"):
        result = _add_cdc_columns(df, op, valid_from, 1)
        logger.info("op=%r -> _cdc_operation=%r", op, result["_cdc_operation"][0])
        assert result["_cdc_operation"][0] == op


def test_cdc_batch_id_is_int64():
    df = pl.DataFrame({"PK_ID": [1]})
    result = _add_cdc_columns(df, "I", datetime.now(timezone.utc), batch_id=12345)

    logger.info("_cdc_batch_id dtype: %s, value: %s",
                result["_cdc_batch_id"].dtype, result["_cdc_batch_id"][0])

    assert result["_cdc_batch_id"].dtype == pl.Int64
    assert result["_cdc_batch_id"][0] == 12345


def test_cdc_valid_from_is_utc_aware():
    df = pl.DataFrame({"PK_ID": [1]})
    valid_from = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    result = _add_cdc_columns(df, "I", valid_from, 1)

    dtype = result["_cdc_valid_from"].dtype
    logger.info("_cdc_valid_from dtype: %s", dtype)

    assert isinstance(dtype, pl.Datetime)
    assert dtype.time_zone == "UTC"


def test_cdc_valid_to_starts_null():
    """``_cdc_valid_to`` is the close-out timestamp — only set when a row
    is expired. New rows must carry NULL.
    """
    df = pl.DataFrame({"PK_ID": [1, 2, 3]})
    result = _add_cdc_columns(df, "I", datetime.now(timezone.utc), 1)

    nulls = result["_cdc_valid_to"].is_null().sum()
    logger.info("_cdc_valid_to nulls on new rows: %d/%d", nulls, result.height)

    assert nulls == result.height, "New CDC rows must have _cdc_valid_to NULL"
