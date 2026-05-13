"""Tests for ``cdc.source_verifier`` — Phase 2 verify-before-close.

Exercises the partition logic (confirmed vs false negative), env-var
toggles, batching, and failure-mode handling. The actual source query
is mocked at ``_query_source_for_pks`` so tests don't need a live
Oracle / SQL Server instance.
"""
from __future__ import annotations

import json
import logging
from unittest.mock import patch

import polars as pl
import pytest

import cdc.source_verifier as source_verifier
from cdc.source_verifier import (
    VerificationResult,
    verify_deletes_against_source,
    _build_existence_query,
    _iter_batches,
)


logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def _enable_verifier(monkeypatch):
    """The conftest disables ``CDC_VERIFY_BEFORE_CLOSE`` for the rest of
    the test suite (no live source available). Tests in this module
    need the verifier ON so we can observe its behavior. Strip the env
    var so the module's defaults apply.
    """
    monkeypatch.delenv("CDC_VERIFY_BEFORE_CLOSE", raising=False)
    monkeypatch.delenv("CDC_VERIFY_STRICT_ON_FAILURE", raising=False)
    monkeypatch.delenv("CDC_VERIFY_MAX_CANDIDATES", raising=False)


@pytest.fixture
def candidate_pks() -> pl.DataFrame:
    return pl.DataFrame({"ACCTNBR": [205, 1042, 9876, 12345]})


def test_empty_candidate_set_is_noop(make_table_config):
    tc = make_table_config(table_name="ACCT", source_name="DNA",
                           pk_columns=["ACCTNBR"])
    empty = pl.DataFrame(schema={"ACCTNBR": pl.Int64})

    result = verify_deletes_against_source(empty, ["ACCTNBR"], tc)

    logger.info("Empty candidate result: candidate=%d confirmed=%d false_neg=%d",
                result.candidate_count, result.confirmed_count,
                result.false_negative_count)

    assert result.candidate_count == 0
    assert result.confirmed_count == 0
    assert result.false_negative_count == 0
    assert not result.skipped


def test_disable_env_var_skips(make_table_config, candidate_pks, monkeypatch):
    monkeypatch.setenv(source_verifier._DISABLE_ENV, "0")
    tc = make_table_config(pk_columns=["ACCTNBR"])

    result = verify_deletes_against_source(candidate_pks, ["ACCTNBR"], tc)

    assert result.skipped is True
    assert "CDC_VERIFY_BEFORE_CLOSE=0" in result.skip_reason


def test_windowed_skipped(make_table_config, candidate_pks):
    tc = make_table_config(pk_columns=["ACCTNBR"])

    result = verify_deletes_against_source(
        candidate_pks, ["ACCTNBR"], tc, windowed=True,
    )

    assert result.skipped is True
    assert "windowed" in result.skip_reason


def test_too_many_candidates_skipped(make_table_config, monkeypatch):
    """Above CDC_VERIFY_MAX_CANDIDATES, the verifier refuses to flood the
    source with IN-list queries — extraction-count check is the right
    defense at that scale.
    """
    monkeypatch.setenv(source_verifier._MAX_CANDIDATES_ENV, "5")
    tc = make_table_config(pk_columns=["ACCTNBR"])
    big = pl.DataFrame({"ACCTNBR": list(range(100))})

    result = verify_deletes_against_source(big, ["ACCTNBR"], tc)

    logger.info("Skip reason: %s", result.skip_reason)

    assert result.skipped is True
    assert "exceeds" in result.skip_reason


def test_all_pks_confirmed_deleted(make_table_config, candidate_pks):
    """Source returns zero rows for the candidates → all confirmed deletes."""
    tc = make_table_config(pk_columns=["ACCTNBR"])

    empty_found = pl.DataFrame(schema={"ACCTNBR": pl.Int64})
    with patch.object(source_verifier, "_query_source_for_pks",
                      return_value=empty_found):
        result = verify_deletes_against_source(candidate_pks, ["ACCTNBR"], tc)

    logger.info("All confirmed: confirmed=%d false_neg=%d",
                result.confirmed_count, result.false_negative_count)

    assert result.skipped is False
    assert result.confirmed_count == 4
    assert result.false_negative_count == 0
    assert result.confirmed_deletes["ACCTNBR"].to_list() == [205, 1042, 9876, 12345]


def test_all_pks_are_false_negatives(make_table_config, candidate_pks, caplog):
    """Source still has every candidate → every delete is suppressed."""
    tc = make_table_config(pk_columns=["ACCTNBR"])

    found = pl.DataFrame({"ACCTNBR": [205, 1042, 9876, 12345]})
    with patch.object(source_verifier, "_query_source_for_pks",
                      return_value=found):
        with caplog.at_level(logging.WARNING, logger="cdc.source_verifier"):
            result = verify_deletes_against_source(candidate_pks, ["ACCTNBR"], tc)

    assert result.confirmed_count == 0
    assert result.false_negative_count == 4

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("suppressed 4/4" in r.message for r in warnings), \
        "Expected a WARNING that 4 of 4 deletes were suppressed"


def test_partial_false_negatives(make_table_config, candidate_pks):
    """Source has 2 of 4 candidates → 2 confirmed, 2 suppressed."""
    tc = make_table_config(pk_columns=["ACCTNBR"])

    # Source still has 1042 and 12345; 205 and 9876 are genuinely gone.
    found = pl.DataFrame({"ACCTNBR": [1042, 12345]})
    with patch.object(source_verifier, "_query_source_for_pks",
                      return_value=found):
        result = verify_deletes_against_source(candidate_pks, ["ACCTNBR"], tc)

    logger.info("Partial: confirmed=%s false_neg=%s",
                result.confirmed_deletes["ACCTNBR"].to_list(),
                result.false_negatives["ACCTNBR"].to_list())

    assert result.confirmed_count == 2
    assert result.false_negative_count == 2
    assert sorted(result.confirmed_deletes["ACCTNBR"].to_list()) == [205, 9876]
    assert sorted(result.false_negatives["ACCTNBR"].to_list()) == [1042, 12345]


def test_source_query_failure_strict_default(make_table_config, candidate_pks, caplog):
    """Default strict mode: failure → all candidates as false negatives so
    nothing gets closed."""
    tc = make_table_config(pk_columns=["ACCTNBR"])

    def _boom(*_a, **_k):
        raise RuntimeError("simulated network failure")

    with patch.object(source_verifier, "_query_source_for_pks", side_effect=_boom):
        with caplog.at_level(logging.ERROR, logger="cdc.source_verifier"):
            result = verify_deletes_against_source(candidate_pks, ["ACCTNBR"], tc)

    logger.info("Strict failure result: skipped=%s false_neg=%d error=%s",
                result.skipped, result.false_negative_count, result.error)

    assert result.skipped is True
    assert result.false_negative_count == 4  # all suppressed
    assert result.confirmed_count == 0
    assert "simulated network failure" in result.error

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("strict mode" in r.message for r in errors)


def test_source_query_failure_non_strict(make_table_config, candidate_pks,
                                          monkeypatch, caplog):
    """Non-strict: failure → caller proceeds with original close behavior."""
    monkeypatch.setenv(source_verifier._STRICT_ENV, "0")
    tc = make_table_config(pk_columns=["ACCTNBR"])

    def _boom(*_a, **_k):
        raise RuntimeError("simulated failure")

    with patch.object(source_verifier, "_query_source_for_pks", side_effect=_boom):
        with caplog.at_level(logging.WARNING, logger="cdc.source_verifier"):
            result = verify_deletes_against_source(candidate_pks, ["ACCTNBR"], tc)

    assert result.skipped is True
    # Non-strict: do NOT mark as false negatives — caller falls back to
    # original close behavior.
    assert result.false_negative_count == 0
    assert result.confirmed_count == 0


def test_metadata_dict_shape(make_table_config, candidate_pks):
    tc = make_table_config(pk_columns=["ACCTNBR"])

    empty_found = pl.DataFrame(schema={"ACCTNBR": pl.Int64})
    with patch.object(source_verifier, "_query_source_for_pks",
                      return_value=empty_found):
        result = verify_deletes_against_source(candidate_pks, ["ACCTNBR"], tc)

    md = result.as_metadata_dict()

    logger.info("Metadata: %s", md)

    assert set(md.keys()) >= {
        "candidate_count", "confirmed_count", "false_negative_count",
        "skipped", "skip_reason", "duration_ms",
    }
    assert md["candidate_count"] == 4
    assert md["confirmed_count"] == 4
    assert md["false_negative_count"] == 0


# ---------------------------------------------------------------------------
# Lower-level helpers
# ---------------------------------------------------------------------------


def test_build_existence_query_single_pk():
    """Single-column PK → standard IN(?, ?, ...) form."""
    batch = [(1,), (2,), (3,)]
    query, params = _build_existence_query(
        "OSIBANK.ACCT", ["ACCTNBR"], batch, lambda i: f":p{i}",
    )

    logger.info("Query: %s", query)
    logger.info("Params: %s", params)

    assert "FROM OSIBANK.ACCT" in query
    assert "ACCTNBR IN" in query
    assert ":p0" in query and ":p2" in query
    assert params == [1, 2, 3]


def test_build_existence_query_composite_pk():
    """Composite PK → OR-of-AND form, portable across Oracle and SQL Server."""
    batch = [(1, "x"), (2, "y")]
    query, params = _build_existence_query(
        "DBO.MULTIKEY", ["KEY1", "KEY2"], batch, lambda i: "?",
    )

    logger.info("Composite query: %s", query)

    # Should produce: WHERE (KEY1 = ? AND KEY2 = ?) OR (KEY1 = ? AND KEY2 = ?)
    assert "KEY1 = ?" in query
    assert "KEY2 = ?" in query
    assert query.count(" OR ") == 1
    assert " IN " not in query  # OR-of-AND form, not row-constructor IN
    assert params == [1, "x", 2, "y"]


def test_iter_batches_chunks_correctly():
    df = pl.DataFrame({"PK": list(range(7))})
    batches = list(_iter_batches(df, ["PK"], batch_size=3))

    logger.info("Batch sizes: %s", [len(b) for b in batches])

    assert len(batches) == 3
    assert len(batches[0]) == 3
    assert len(batches[1]) == 3
    assert len(batches[2]) == 1
    # Each batch row is a tuple of PK values.
    assert batches[0][0] == (0,)


def test_iter_batches_empty_dataframe():
    df = pl.DataFrame(schema={"PK": pl.Int64})
    batches = list(_iter_batches(df, ["PK"], batch_size=10))

    assert batches == []
