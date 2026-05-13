"""Tests for ``cdc.drift_detector``.

The detector is read-only — it observes Stage↔Bronze drift and emits
structured logs but never writes recovery rows. These tests exercise its
classification and disable-flag handling without a live SQL Server.

The DB-backed cross-database FULL OUTER JOIN path is exercised in
``tests/uat/test_stage_invariants.py``.
"""
from __future__ import annotations

import json
import logging
from unittest.mock import patch

import pytest

import cdc.drift_detector as drift_detector
from cdc.drift_detector import DriftReport, log_stage_bronze_drift


logger = logging.getLogger(__name__)


def test_disable_env_var_skips_check(make_table_config, monkeypatch):
    monkeypatch.setenv(drift_detector._DISABLE_ENV, "0")
    tc = make_table_config(table_name="ACCT", source_name="DNA",
                           pk_columns=["ACCTNBR"])

    report = log_stage_bronze_drift(tc)

    logger.info("Skip reason: %s", report.skip_reason)

    assert report.skipped is True
    assert "CDC_DRIFT_DETECTION=0" in report.skip_reason
    assert report.total == 0


def test_no_pk_columns_skipped():
    """The conftest fixture coerces ``pk_columns=[]`` back to ``["PK_ID"]``
    (it uses ``pk_columns or ["PK_ID"]``), so we build a minimal stand-in
    directly to exercise the empty-PK skip path.
    """
    from types import SimpleNamespace

    tc = SimpleNamespace(
        pk_columns=[],
        source_name="DNA",
        source_object_name="ACCT",
        stage_full_table_name="UDM_Stage.DNA.ACCT_cdc",
        bronze_full_table_name="UDM_Bronze.DNA.ACCT_scd2_python",
    )

    report = log_stage_bronze_drift(tc)

    logger.info("Skip reason: %s", report.skip_reason)

    assert report.skipped is True
    assert "no PK" in report.skip_reason


def test_missing_stage_table_skipped(make_table_config):
    tc = make_table_config(table_name="DOESNOTEXIST", pk_columns=["PK_ID"])

    with patch.object(drift_detector, "_table_exists", return_value=False):
        report = log_stage_bronze_drift(tc)

    logger.info("Skip reason: %s", report.skip_reason)

    assert report.skipped is True
    assert "does not exist" in report.skip_reason


def test_clean_state_no_warning(make_table_config, caplog):
    """Tables with zero drift emit an INFO ``CDC_DRIFT`` JSON line and
    nothing at WARNING level."""
    tc = make_table_config(table_name="ACCT", source_name="DNA",
                           pk_columns=["ACCTNBR"])

    def _populate(report, *_args, **_kwargs):
        report.stage_only = 0
        report.bronze_only = 0

    with patch.object(drift_detector, "_table_exists", return_value=True), \
         patch.object(drift_detector, "_populate_report", side_effect=_populate):
        with caplog.at_level(logging.INFO, logger="cdc.drift_detector"):
            report = log_stage_bronze_drift(tc)

    logger.info("Stage-only=%d Bronze-only=%d total=%d",
                report.stage_only, report.bronze_only, report.total)

    assert report.skipped is False
    assert report.total == 0

    info_drift = [r for r in caplog.records
                  if r.levelno == logging.INFO and r.message.startswith("CDC_DRIFT:")]
    assert info_drift, "Expected one INFO-level CDC_DRIFT log line on clean state"
    payload = json.loads(info_drift[0].message[len("CDC_DRIFT: "):])
    assert payload["signal"] == "drift_detected"
    assert payload["stage_only"] == 0
    assert payload["bronze_only"] == 0

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warnings, f"Expected no warnings, got: {[w.message for w in warnings]}"


def test_bronze_only_drift_warning_with_samples(make_table_config, caplog):
    """The headline scenario — Bronze active, Stage missing current. Emits
    a WARNING with sample PKs.
    """
    tc = make_table_config(table_name="ACCT", source_name="DNA",
                           pk_columns=["ACCTNBR"])

    def _populate(report, *_args, **_kwargs):
        report.stage_only = 0
        report.bronze_only = 4
        report.bronze_only_samples = ["205", "1042", "9876", "12345"]

    with patch.object(drift_detector, "_table_exists", return_value=True), \
         patch.object(drift_detector, "_populate_report", side_effect=_populate):
        with caplog.at_level(logging.WARNING, logger="cdc.drift_detector"):
            report = log_stage_bronze_drift(tc)

    logger.info("Bronze-only drift detected: %d PKs sampled %s",
                report.bronze_only, report.bronze_only_samples)

    assert report.bronze_only == 4
    assert report.stage_only == 0

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Bronze row" in r.message and "no _cdc_is_current=1" in r.message
               for r in warnings), "Expected a WARNING describing the bronze-only drift"

    json_lines = [r for r in caplog.records
                  if r.message.startswith("CDC_DRIFT:")]
    assert json_lines, "Expected a structured CDC_DRIFT JSON log line"
    payload = json.loads(json_lines[0].message[len("CDC_DRIFT: "):])
    assert payload["bronze_only"] == 4
    assert payload["bronze_only_samples"] == ["205", "1042", "9876", "12345"]


def test_stage_only_drift_warning(make_table_config, caplog):
    """The reverse scenario — Stage current row exists, Bronze missing
    active. Suggests SCD2 didn't propagate.
    """
    tc = make_table_config(table_name="ACCT", source_name="DNA",
                           pk_columns=["ACCTNBR"])

    def _populate(report, *_args, **_kwargs):
        report.stage_only = 2
        report.bronze_only = 0
        report.stage_only_samples = ["77", "88"]

    with patch.object(drift_detector, "_table_exists", return_value=True), \
         patch.object(drift_detector, "_populate_report", side_effect=_populate):
        with caplog.at_level(logging.WARNING, logger="cdc.drift_detector"):
            report = log_stage_bronze_drift(tc)

    assert report.stage_only == 2
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("current Stage row" in r.message and "no active Bronze" in r.message
               for r in warnings)


def test_query_failure_marked_skipped(make_table_config, caplog):
    """If the cross-DB query throws, the detector marks the report skipped
    rather than re-raising — never blocks CDC.
    """
    tc = make_table_config(pk_columns=["PK_ID"])

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated query failure")

    with patch.object(drift_detector, "_table_exists", return_value=True), \
         patch.object(drift_detector, "_populate_report", side_effect=_boom):
        report = log_stage_bronze_drift(tc)

    logger.info("Skip reason after simulated failure: %s", report.skip_reason)

    assert report.skipped is True
    assert "simulated query failure" in report.skip_reason


def test_metadata_dict_shape(make_table_config):
    """The ``as_metadata_dict()`` output should be a flat structure that
    can be embedded directly into ``PipelineEventLog.Metadata`` JSON."""
    report = DriftReport(
        source_name="DNA",
        table_name="ACCT",
        stage_only=1,
        bronze_only=2,
        stage_only_samples=["77"],
        bronze_only_samples=["205", "1042"],
    )

    payload = report.as_metadata_dict()

    logger.info("Metadata payload: %s", payload)

    assert payload == {
        "stage_only": 1,
        "bronze_only": 2,
        "stage_only_samples": ["77"],
        "bronze_only_samples": ["205", "1042"],
    }
