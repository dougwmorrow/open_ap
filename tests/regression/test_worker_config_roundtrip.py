"""Regression tests for the worker-boundary TableConfig serialization.

The original ``table_config_to_dict`` enumerated fields by hand. Every
time a new dataclass field was added (StripSuffix, MaxRowsPerDay, the
SCD2 enhancement block) it was silently dropped at the worker
boundary — runs with ``--workers > 1`` got dataclass defaults instead
of UdmTablesList values. The bug only surfaced with parallel runs;
single-worker testing missed it.

These tests pin the contract: every TableConfig field in
``dataclasses.fields(TableConfig)`` survives a round-trip through
``table_config_to_dict`` → ``table_config_from_dict``. Adding a new
field now requires updating only ``TableConfig`` itself; serialization
rides along automatically. If someone reverts to a hand-list and a
field is missing, the round-trip test fails.
"""
from __future__ import annotations

import dataclasses
import logging
import pickle

from orchestration.table_config import ColumnConfig, TableConfig
from utils.cli_common import table_config_from_dict, table_config_to_dict


logger = logging.getLogger(__name__)


def _build_full_config() -> TableConfig:
    """Construct a TableConfig with non-default values on EVERY field
    that downstream code consults — strip_suffix, max_rows_per_day, the
    SCD2 enhancement block, exclude_columns, etc."""
    tc = TableConfig(
        source_object_name="CARDTXN",
        source_server="sc.example.org",
        source_database="DNAPROD",
        source_schema_name="OSIBANK",
        source_name="DNA",
        stage_table_name="CARDTXN",
        bronze_table_name="CARDTXN",
        source_aggregate_column_name="ACTIVITYDATE",
        source_aggregate_column_type="datetime",
        source_index_hint="CARDTXN_DX18",
        partition_on=None,
        first_load_date="2022-04-12",
        lookback_days=3,
        stage_load_tool="Python",
        strip_suffix=True,
        max_rows_per_day=5_000_000,
        columns=[
            ColumnConfig(
                source_name="DNA",
                table_name="CARDTXN",
                column_name="ID",
                ordinal_position=1,
                is_primary_key=True,
                layer="Stage",
                is_index=True,
                index_name="PK_CARDTXN",
                index_type="CLUSTERED",
            ),
            ColumnConfig(
                source_name="DNA",
                table_name="CARDTXN",
                column_name="ACTIVITYDATE",
                ordinal_position=2,
                is_primary_key=False,
                layer="Stage",
                is_index=False,
                index_name=None,
                index_type=None,
            ),
        ],
        _resolved_stage_schema="dna",
        _resolved_bronze_schema="dna",
    )
    tc.exclude_columns = {"INTERNAL_NOTE", "AUDIT_BLOB"}
    tc.scd2_mode = "incremental"
    tc.scd2_date_columns = ["DATELASTMAINT", "ACTIVITYDATE"]
    tc.source_delete_date_column = "DATEDELETED"
    tc.duplicate_resolution_order = "DATELASTMAINT,UdmEffectiveDateTime"
    tc.allow_duplicates = False
    tc.preserve_datetime = True
    tc.repair_chain_after = True
    tc.allow_gaps = False
    tc.exclude_from_hash = ["DATELASTMAINT"]
    tc.default_begin_date = "1900-01-01"
    tc.force_new_segment_columns = ["STATUS"]
    tc.expected_retention_days = 1080
    tc.last_modified_column = "DATELASTMAINT"
    return tc


def test_round_trip_preserves_every_dataclass_field():
    """The contract — every field on TableConfig survives the round trip.
    Iterates ``dataclasses.fields(TableConfig)`` so a future field
    addition is automatically covered."""
    original = _build_full_config()
    payload = table_config_to_dict(original, batch_id=999)

    restored, metadata = table_config_from_dict(payload)

    assert metadata == {"batch_id": 999, "force": False}

    for f in dataclasses.fields(TableConfig):
        if f.name == "columns":
            continue  # checked separately
        original_val = getattr(original, f.name)
        restored_val = getattr(restored, f.name)
        assert restored_val == original_val, (
            f"Field {f.name!r} did NOT round-trip. "
            f"Original: {original_val!r}, restored: {restored_val!r}"
        )

    assert len(restored.columns) == len(original.columns)
    for orig_col, rest_col in zip(original.columns, restored.columns):
        for f in dataclasses.fields(ColumnConfig):
            assert getattr(rest_col, f.name) == getattr(orig_col, f.name), (
                f"ColumnConfig field {f.name!r} did NOT round-trip"
            )


def test_strip_suffix_survives_round_trip():
    """The original symptom: StripSuffix=1 in DB but worker sees False
    because the dict serializer didn't include it."""
    tc = _build_full_config()
    assert tc.strip_suffix is True

    payload = table_config_to_dict(tc, batch_id=1)
    restored, _ = table_config_from_dict(payload)

    logger.info("strip_suffix: original=%s restored=%s",
                tc.strip_suffix, restored.strip_suffix)
    assert restored.strip_suffix is True
    assert restored.stage_full_table_name == tc.stage_full_table_name
    assert restored.bronze_full_table_name == tc.bronze_full_table_name
    # And specifically: no _cdc / _scd2_python suffix.
    assert not restored.stage_full_table_name.endswith("_cdc")
    assert not restored.bronze_full_table_name.endswith("_scd2_python")


def test_max_rows_per_day_survives_round_trip():
    """The other half of the original symptom: MaxRowsPerDay=5000000 in
    DB but worker sees None because the dict serializer didn't include
    it. Guard threshold then defaults to 5x baseline."""
    tc = _build_full_config()
    assert tc.max_rows_per_day == 5_000_000

    payload = table_config_to_dict(tc, batch_id=1)
    restored, _ = table_config_from_dict(payload)

    assert restored.max_rows_per_day == 5_000_000


def test_scd2_enhancement_fields_survive_round_trip():
    """The whole SCD2 enhancement block silently fell back to defaults
    on parallel runs prior to this fix."""
    tc = _build_full_config()
    payload = table_config_to_dict(tc, batch_id=1)
    restored, _ = table_config_from_dict(payload)

    assert restored.scd2_mode == "incremental"
    assert restored.scd2_date_columns == ["DATELASTMAINT", "ACTIVITYDATE"]
    assert restored.source_delete_date_column == "DATEDELETED"
    assert restored.duplicate_resolution_order == "DATELASTMAINT,UdmEffectiveDateTime"
    assert restored.allow_duplicates is False
    assert restored.preserve_datetime is True
    assert restored.exclude_from_hash == ["DATELASTMAINT"]
    assert restored.default_begin_date == "1900-01-01"
    assert restored.force_new_segment_columns == ["STATUS"]
    assert restored.expected_retention_days == 1080
    assert restored.last_modified_column == "DATELASTMAINT"


def test_exclude_columns_set_round_trips_as_set():
    """``exclude_columns`` is a set (frozen membership semantics, not
    ordered). Some pickle paths convert sets to lists; the from_dict
    helper coerces back to ensure downstream code can do ``in`` checks
    against a set in O(1)."""
    tc = _build_full_config()
    payload = table_config_to_dict(tc, batch_id=1)

    # Simulate a transport that converted set → list.
    if isinstance(payload["exclude_columns"], set):
        payload["exclude_columns"] = list(payload["exclude_columns"])

    restored, _ = table_config_from_dict(payload)
    assert isinstance(restored.exclude_columns, set)
    assert restored.exclude_columns == {"INTERNAL_NOTE", "AUDIT_BLOB"}


def test_force_and_refresh_pks_metadata_pass_through():
    """Worker metadata (``force``, ``refresh_pks``) lives outside the
    dataclass fields and reaches the worker via the metadata dict."""
    tc = _build_full_config()
    payload = table_config_to_dict(tc, batch_id=42)
    payload["force"] = True
    payload["refresh_pks"] = True

    restored, metadata = table_config_from_dict(payload)
    assert metadata["batch_id"] == 42
    assert metadata["force"] is True
    assert metadata["refresh_pks"] is True

    # Restored TableConfig should NOT have these as attributes.
    assert not hasattr(restored, "batch_id")
    assert not hasattr(restored, "force")


def test_payload_pickles_through_processpool_boundary():
    """End-to-end: the dict actually pickles. ProcessPoolExecutor uses
    pickle for cross-process transfer, so unpicklable values would
    surface here as a TypeError at submit time on the operator's box."""
    tc = _build_full_config()
    payload = table_config_to_dict(tc, batch_id=7)

    blob = pickle.dumps(payload)
    restored_payload = pickle.loads(blob)

    restored, metadata = table_config_from_dict(restored_payload)
    assert metadata["batch_id"] == 7
    assert restored.strip_suffix is True
    assert restored.max_rows_per_day == 5_000_000
