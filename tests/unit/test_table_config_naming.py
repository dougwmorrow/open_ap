"""Tests for ``TableConfig`` Stage / Bronze name construction, including
the SS-1 ``StripSuffix`` opt-in.

The naming convention is the durable contract that ties UdmTablesList
config to the actual SQL table names. Regressions here break every
table that depends on the affected configuration.
"""
from __future__ import annotations

import logging

import utils.configuration as config


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default behavior — suffix retained
# ---------------------------------------------------------------------------


def test_stage_name_default_appends_cdc_suffix(make_table_config):
    """Default ``strip_suffix=False`` produces the legacy
    ``{StageTableName or SourceObjectName}_cdc`` form. Every table that
    existed before the SS-1 migration must keep this behavior."""
    tc = make_table_config(table_name="ACCT", source_name="DNA")

    logger.info("Stage name (default): %s", tc.stage_full_table_name)

    assert tc.stage_full_table_name.endswith("_cdc")
    assert tc.stage_full_table_name == f"{config.STAGE_DB}.DNA.ACCT_cdc"


def test_bronze_name_default_appends_scd2_python_suffix(make_table_config):
    tc = make_table_config(table_name="ACCT", source_name="DNA")

    logger.info("Bronze name (default): %s", tc.bronze_full_table_name)

    assert tc.bronze_full_table_name.endswith("_scd2_python")
    assert tc.bronze_full_table_name == f"{config.BRONZE_DB}.DNA.ACCT_scd2_python"


# ---------------------------------------------------------------------------
# SS-1 — opt-in bare names
# ---------------------------------------------------------------------------


def test_stage_name_strip_suffix_drops_cdc(make_table_config):
    """``strip_suffix=True`` returns the bare name without the
    trailing ``_cdc``. Used for tables that have migrated off the
    legacy T-SQL pipeline."""
    tc = make_table_config(
        table_name="AuditLog", source_name="CCM", strip_suffix=True,
    )

    logger.info("Stage name (strip): %s", tc.stage_full_table_name)

    assert not tc.stage_full_table_name.endswith("_cdc")
    assert tc.stage_full_table_name == f"{config.STAGE_DB}.CCM.AuditLog"


def test_bronze_name_strip_suffix_drops_scd2_python(make_table_config):
    tc = make_table_config(
        table_name="AuditLog", source_name="CCM", strip_suffix=True,
    )

    logger.info("Bronze name (strip): %s", tc.bronze_full_table_name)

    assert not tc.bronze_full_table_name.endswith("_scd2_python")
    assert tc.bronze_full_table_name == f"{config.BRONZE_DB}.CCM.AuditLog"


def test_strip_suffix_with_custom_stage_table_name(make_table_config):
    """Custom ``StageTableName`` override + ``StripSuffix=1`` → uses
    the override as the bare name."""
    from orchestration.table_config import TableConfig

    tc = make_table_config(
        table_name="AuditLog", source_name="CCM", strip_suffix=True,
    )
    # Mutate stage_table_name post-build to mirror what the loader does
    # when StageTableName is populated in UdmTablesList.
    tc.stage_table_name = "AuditLogCustom"
    tc.bronze_table_name = "AuditLogCustomBronze"

    logger.info("Stage name (strip + custom): %s", tc.stage_full_table_name)
    logger.info("Bronze name (strip + custom): %s", tc.bronze_full_table_name)

    assert tc.stage_full_table_name == f"{config.STAGE_DB}.CCM.AuditLogCustom"
    assert tc.bronze_full_table_name == f"{config.BRONZE_DB}.CCM.AuditLogCustomBronze"
    assert isinstance(tc, TableConfig)


def test_strip_suffix_default_is_false(make_table_config):
    """The default value of the field must be False so every existing
    config row preserves its current behavior. The migration adds the
    column with ``DEFAULT 0``, so newly-loaded rows arrive with
    StripSuffix=0 → ``_bit_to_bool`` → False."""
    tc = make_table_config()

    logger.info("Default strip_suffix: %s", tc.strip_suffix)

    assert tc.strip_suffix is False
    # And the names should carry the suffix.
    assert tc.stage_full_table_name.endswith("_cdc")
    assert tc.bronze_full_table_name.endswith("_scd2_python")
