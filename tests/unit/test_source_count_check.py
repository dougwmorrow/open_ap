"""Tests for ``extract.source_count_check`` — Phase 2 row-count check."""
from __future__ import annotations

import logging
from unittest.mock import patch

import polars as pl
import pytest

import extract.source_count_check as src_count
from extract.source_count_check import check_source_count_integrity


logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def _enable_count_check(monkeypatch):
    """The conftest disables ``CDC_SOURCE_COUNT_CHECK`` globally to
    prevent live-source calls in unrelated unit tests. This module
    needs it ON to observe behavior.
    """
    monkeypatch.delenv("CDC_SOURCE_COUNT_CHECK", raising=False)
    monkeypatch.delenv("CDC_SOURCE_COUNT_TOLERANCE_PCT", raising=False)
    monkeypatch.delenv("CDC_SOURCE_COUNT_WINDOWED_TOLERANCE_PCT", raising=False)
    monkeypatch.delenv("CDC_SOURCE_COUNT_STRICT_ON_FAILURE", raising=False)


def _df(n: int) -> pl.DataFrame:
    return pl.DataFrame({"PK_ID": list(range(n)), "VAL": ["x"] * n})


def test_perfect_match_is_ok(make_table_config):
    tc = make_table_config()
    df = _df(1000)

    with patch.object(src_count, "_query_source_count", return_value=1000):
        result = check_source_count_integrity(df, tc)

    logger.info("Match: extracted=%d source=%d delta_pct=%.4f ok=%s",
                result.extracted_count, result.source_count,
                result.delta_pct, result.ok)

    assert result.ok is True
    assert result.skipped is False
    assert result.delta == 0
    assert result.delta_pct == 0.0


def test_within_tolerance_is_ok(make_table_config):
    """Default tolerance 0.5%: extracted=995 vs source=1000 → 0.5% delta → ok."""
    tc = make_table_config()
    df = _df(995)

    with patch.object(src_count, "_query_source_count", return_value=1000):
        result = check_source_count_integrity(df, tc)

    logger.info("Within tolerance: delta=%d delta_pct=%.4f", result.delta,
                result.delta_pct)

    assert result.ok is True
    assert result.delta == -5
    assert abs(result.delta_pct - 0.5) < 1e-9


def test_exceeds_tolerance_fails(make_table_config, caplog):
    """1% delta exceeds the default 0.5% tolerance → ok=False."""
    tc = make_table_config()
    df = _df(990)

    with patch.object(src_count, "_query_source_count", return_value=1000):
        with caplog.at_level(logging.ERROR, logger="extract.source_count_check"):
            result = check_source_count_integrity(df, tc)

    logger.info("Exceeds tolerance: extracted=%d source=%d delta_pct=%.4f ok=%s",
                result.extracted_count, result.source_count,
                result.delta_pct, result.ok)

    assert result.ok is False
    assert result.delta == -10
    assert abs(result.delta_pct - 1.0) < 1e-9

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("integrity check FAILED" in r.message for r in errors)


def test_custom_tolerance_via_env(make_table_config, monkeypatch):
    monkeypatch.setenv(src_count._TOLERANCE_ENV, "5.0")  # 5% tolerance
    tc = make_table_config()
    df = _df(960)  # 4% delta — within new tolerance

    with patch.object(src_count, "_query_source_count", return_value=1000):
        result = check_source_count_integrity(df, tc)

    logger.info("Custom tolerance: tolerance=%.2f delta_pct=%.4f ok=%s",
                result.tolerance_pct, result.delta_pct, result.ok)

    assert result.tolerance_pct == 5.0
    assert result.ok is True


def test_disable_env_skips(make_table_config, monkeypatch):
    monkeypatch.setenv(src_count._DISABLE_ENV, "0")
    tc = make_table_config()
    df = _df(0)  # would be a 100% delta if checked

    # No need to mock _query_source_count — disabled means the query is
    # never run.
    result = check_source_count_integrity(df, tc)

    assert result.skipped is True
    assert result.ok is True
    assert "CDC_SOURCE_COUNT_CHECK=0" in result.skip_reason


# ---------------------------------------------------------------------------
# Phase 3.1 — windowed mode
# ---------------------------------------------------------------------------


def test_windowed_perfect_match_is_ok(make_table_config):
    """Windowed args trigger date-scoped COUNT(*); matched counts → ok."""
    from datetime import date

    tc = make_table_config()
    df = _df(50_000)

    with patch.object(src_count, "_query_source_count", return_value=50_000) as mock:
        result = check_source_count_integrity(
            df, tc,
            date_column="DateTime",
            window_start=date(2026, 5, 1),
            window_end=date(2026, 5, 2),
        )

    logger.info("Windowed match: extracted=%d source=%d ok=%s windowed=%s",
                result.extracted_count, result.source_count,
                result.ok, result.windowed)

    assert result.ok is True
    assert result.windowed is True
    assert result.window_start == "2026-05-01"
    assert result.window_end == "2026-05-02"

    # Confirm the window args were forwarded to _query_source_count.
    call = mock.call_args
    assert call.kwargs["date_column"] == "DateTime"
    assert call.kwargs["window_start"] == date(2026, 5, 1)
    assert call.kwargs["window_end"] == date(2026, 5, 2)


def test_windowed_uses_tighter_default_tolerance(make_table_config):
    """Windowed default tolerance is 0.1% (vs 0.5% for full-table). A
    0.5% delta passes full-table mode but FAILS windowed mode."""
    from datetime import date

    tc = make_table_config()
    df = _df(99_500)  # 0.5% delta — within full-table tolerance, exceeds windowed

    with patch.object(src_count, "_query_source_count", return_value=100_000):
        full_result = check_source_count_integrity(df, tc)
        windowed_result = check_source_count_integrity(
            df, tc,
            date_column="DateTime",
            window_start=date(2026, 5, 1),
            window_end=date(2026, 5, 2),
        )

    logger.info("Full-table tolerance: %.4f%% ok=%s",
                full_result.tolerance_pct, full_result.ok)
    logger.info("Windowed tolerance:   %.4f%% ok=%s",
                windowed_result.tolerance_pct, windowed_result.ok)

    assert full_result.ok is True
    assert full_result.tolerance_pct == 0.5
    assert windowed_result.ok is False
    assert windowed_result.tolerance_pct == 0.1


def test_windowed_custom_tolerance_via_env(make_table_config, monkeypatch):
    from datetime import date

    monkeypatch.setenv(src_count._WINDOWED_TOLERANCE_ENV, "2.0")
    tc = make_table_config()
    df = _df(98_500)  # 1.5% delta — within 2.0 tolerance

    with patch.object(src_count, "_query_source_count", return_value=100_000):
        result = check_source_count_integrity(
            df, tc,
            date_column="DateTime",
            window_start=date(2026, 5, 1),
            window_end=date(2026, 5, 2),
        )

    assert result.tolerance_pct == 2.0
    assert result.ok is True


def test_partial_window_args_raises(make_table_config):
    """Half-supplied window args are an error — never silently fall back
    to full-table mode (which would compare daily extraction against
    whole-table count and always fail)."""
    import pytest as _pytest
    tc = make_table_config()
    df = _df(0)

    with _pytest.raises(ValueError, match="Windowed source-count check requires"):
        check_source_count_integrity(df, tc, date_column="DateTime")

    from datetime import date
    with _pytest.raises(ValueError, match="Windowed source-count check requires"):
        check_source_count_integrity(df, tc, window_start=date(2026, 5, 1))


def test_build_where_clause_oracle_uses_named_binds():
    """Oracle source → ``:start_dt`` / ``:end_dt`` named binds. Same
    pattern as extract/oracle_extractor.py."""
    from datetime import date
    where, params = src_count._build_where_clause(
        date_column="DateTime",
        window_start=date(2026, 5, 1),
        window_end=date(2026, 5, 2),
        is_oracle=True,
    )

    logger.info("Oracle where: %s, params: %s", where, params)

    assert ":start_dt" in where
    assert ":end_dt" in where
    assert isinstance(params, dict)
    assert params == {"start_dt": date(2026, 5, 1), "end_dt": date(2026, 5, 2)}


def test_build_where_clause_sql_server_uses_question_marks():
    from datetime import date
    where, params = src_count._build_where_clause(
        date_column="DateTime",
        window_start=date(2026, 5, 1),
        window_end=date(2026, 5, 2),
        is_oracle=False,
    )

    logger.info("SQL Server where: %s, params: %s", where, params)

    assert "DateTime >= ?" in where
    assert "DateTime < ?" in where
    assert ":start_dt" not in where
    assert isinstance(params, list)
    assert params == [date(2026, 5, 1), date(2026, 5, 2)]


def test_build_where_clause_full_table_mode():
    """No date args → empty WHERE, empty params."""
    where, params = src_count._build_where_clause(
        date_column=None,
        window_start=None,
        window_end=None,
        is_oracle=False,
    )

    assert where == ""
    assert params == []


def test_query_failure_default_non_strict(make_table_config, caplog):
    """Default strict mode is OFF for the count check — connection blips
    shouldn't block the pipeline. Logs WARNING but ok=True.
    """
    tc = make_table_config()
    df = _df(100)

    def _boom(*_a, **_k):
        raise RuntimeError("simulated COUNT(*) failure")

    with patch.object(src_count, "_query_source_count", side_effect=_boom):
        with caplog.at_level(logging.WARNING,
                             logger="extract.source_count_check"):
            result = check_source_count_integrity(df, tc)

    assert result.skipped is True
    assert result.ok is True  # non-strict default
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("non-strict" in r.message for r in warnings)


def test_query_failure_strict_mode(make_table_config, monkeypatch, caplog):
    monkeypatch.setenv(src_count._STRICT_ENV, "1")
    tc = make_table_config()
    df = _df(100)

    with patch.object(src_count, "_query_source_count",
                      side_effect=RuntimeError("nope")):
        with caplog.at_level(logging.ERROR,
                             logger="extract.source_count_check"):
            result = check_source_count_integrity(df, tc)

    assert result.ok is False
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("strict mode" in r.message for r in errors)


def test_metadata_dict_shape(make_table_config):
    tc = make_table_config()
    df = _df(950)

    with patch.object(src_count, "_query_source_count", return_value=1000):
        result = check_source_count_integrity(df, tc)

    md = result.as_metadata_dict()

    logger.info("Metadata: %s", md)

    assert set(md.keys()) >= {
        "ok", "skipped", "extracted_count", "source_count",
        "delta", "delta_pct", "tolerance_pct", "duration_ms",
    }
    assert md["extracted_count"] == 950
    assert md["source_count"] == 1000
    assert md["delta"] == -50


def test_source_empty_extracted_zero_is_ok(make_table_config):
    """Source genuinely empty AND extraction empty → ok."""
    tc = make_table_config()
    df = _df(0)

    with patch.object(src_count, "_query_source_count", return_value=0):
        result = check_source_count_integrity(df, tc)

    assert result.ok is True
    assert result.delta_pct == 0.0


def test_source_empty_extracted_nonzero_fails(make_table_config):
    """Source returns 0 but extraction has rows — should fail (delta=100%)."""
    tc = make_table_config()
    df = _df(5)

    with patch.object(src_count, "_query_source_count", return_value=0):
        result = check_source_count_integrity(df, tc)

    logger.info("Empty source / nonzero extract: delta_pct=%.2f ok=%s",
                result.delta_pct, result.ok)

    assert result.ok is False
    assert result.delta_pct == 100.0
