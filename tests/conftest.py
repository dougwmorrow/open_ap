"""Shared pytest fixtures and logging configuration for the CDC test suite.

All tests get verbose, structured logging so failures are diagnosable from
the captured output alone — no need to re-run with print debugging.

Run the suite with::

    python3 -m pytest tests/ -v --log-cli-level=INFO

To see only INFO-and-above for a specific test::

    python3 -m pytest tests/unit/test_hash_determinism.py -v --log-cli-level=INFO
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pytest

# Make the project root importable so tests can `import cdc.engine`, etc.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Logging — every test run emits structured INFO+ messages by default.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _configure_test_logging(caplog):
    """Default every test to INFO-level capture so assertion failures
    have the surrounding context. Tests that need DEBUG can call
    ``caplog.set_level(logging.DEBUG)`` explicitly.
    """
    caplog.set_level(logging.INFO)
    yield


@pytest.fixture(autouse=True)
def _disable_source_side_checks_by_default(monkeypatch):
    """Phase 2 of the CDC blueprint adds two source-side guards that
    require a live Oracle / SQL Server to function:

      - ``cdc/source_verifier.py`` (verify-before-close)
      - ``extract/source_count_check.py`` (row-count integrity)

    Both modules emit network calls when invoked from CDC. Unit tests
    don't have a source available, so we disable them by default for
    every test. Tests that *want* to exercise these paths re-enable
    via ``monkeypatch.delenv(...)`` or ``monkeypatch.setenv(..., "1")``
    before constructing their fixtures.
    """
    monkeypatch.setenv("CDC_VERIFY_BEFORE_CLOSE", "0")
    monkeypatch.setenv("CDC_SOURCE_COUNT_CHECK", "0")
    yield


# Quiet noisy third-party loggers that pollute test output.
logging.getLogger("connectorx").setLevel(logging.WARNING)
logging.getLogger("oracledb").setLevel(logging.WARNING)
logging.getLogger("pyodbc").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# TableConfig fixture builder — synthetic configs for unit tests so we
# never need to talk to General.dbo.UdmTablesList.
# ---------------------------------------------------------------------------


@pytest.fixture
def make_table_config():
    """Return a factory that builds a synthetic TableConfig.

    Example::

        def test_something(make_table_config):
            tc = make_table_config(
                table_name="ACCT",
                source_name="DNA",
                pk_columns=["ACCTNBR"],
            )
            assert tc.pk_columns == ["ACCTNBR"]
    """
    from orchestration.table_config import ColumnConfig, TableConfig

    def _build(
        table_name: str = "TEST_TABLE",
        source_name: str = "DNA",
        source_schema: str = "OSIBANK",
        source_database: str = "DNAPROD",
        pk_columns: list[str] | None = None,
        non_pk_columns: list[str] | None = None,
        scd2_date_columns: list[str] | None = None,
        exclude_from_hash: list[str] | None = None,
        duplicate_resolution_order: str | None = None,
        allow_duplicates: bool = False,
        strip_suffix: bool = False,
    ) -> TableConfig:
        pk_columns = pk_columns or ["PK_ID"]
        non_pk_columns = non_pk_columns or ["VALUE"]

        columns: list[ColumnConfig] = []
        ordinal = 1
        for layer in ("Stage", "Bronze"):
            for col in pk_columns:
                columns.append(ColumnConfig(
                    source_name=source_name,
                    table_name=table_name,
                    column_name=col,
                    ordinal_position=ordinal,
                    is_primary_key=True,
                    layer=layer,
                ))
                ordinal += 1
            for col in non_pk_columns:
                columns.append(ColumnConfig(
                    source_name=source_name,
                    table_name=table_name,
                    column_name=col,
                    ordinal_position=ordinal,
                    is_primary_key=False,
                    layer=layer,
                ))
                ordinal += 1

        return TableConfig(
            source_object_name=table_name,
            source_server="dummy",
            source_database=source_database,
            source_schema_name=source_schema,
            source_name=source_name,
            columns=columns,
            scd2_date_columns=scd2_date_columns,
            exclude_from_hash=exclude_from_hash,
            duplicate_resolution_order=duplicate_resolution_order,
            allow_duplicates=allow_duplicates,
            strip_suffix=strip_suffix,
        )

    return _build


# ---------------------------------------------------------------------------
# UAT marker — tests that need a live SQL Server connection.
# Skip automatically when the env var is not set, so unit tests run in CI
# without DB access.
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(config, items):
    skip_uat = pytest.mark.skip(
        reason=(
            "UAT test requires live SQL Server. Set CDC_UAT_ENABLED=1 to "
            "run; ensure /debi/.env points at the target environment."
        )
    )
    if os.environ.get("CDC_UAT_ENABLED") != "1":
        for item in items:
            if "uat" in item.keywords:
                item.add_marker(skip_uat)
