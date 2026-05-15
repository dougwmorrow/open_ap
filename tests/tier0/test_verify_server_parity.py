"""Tier 0 build-time smoke test for tools/verify_server_parity.py (M8 Wave 5).

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (subprocess OS probes, filesystem reads beyond a
synthetic fixture path) are mocked. No live DB, no live network required.

6 D77-canonical assertions per phase1/03_core_modules.md § 3.2 L805-810:
  (a) Module imports without error (tools/verify_server_parity.py)
  (b) `verify_server_parity(baseline_path='fixture.json')` invocable
  (c) Returns ParityReport with overall in {'pass', 'warn', 'fail'}
  (d) All-match fixture returns overall='pass'
  (e) One fatal mismatch fixture returns overall='fail' AND raises
      ParityFatalError when fail_on_warning=False
  (f) Tier 0 total runtime < 5 s per D67

North Star pillars:
  - Audit-grade (D27): cross-server parity baseline contract.
  - Operationally stable (D67): import + invoke + shape + error-modes in
    < 5 s with zero external I/O; D74 exit-code contract via raised
    PipelineFatalError subclass.
  - Idempotent (D15): same baseline + same probe values produce identical
    ParityReport contents (modulo presentation timestamps which this module
    does NOT carry — only the CLI shim writes audit-row CreatedAt).

D-numbers: D15 (idempotency mandatory), D27 (cross-server parity contract),
D62-D65 (drift severity), D67 (Tier 0 discipline), D68 (error class hierarchy
— utils.errors canonical per B228), D74 (exit-code contract 0/1/2),
D85 (module startup sequence stage 3 — parity check), D92 (forward-only
additive — new module), D103 (Claude Code security model — baseline lives
OUTSIDE /debi).

Edge case IDs (per 04_EDGE_CASES.md F-series):
  F21 (TPM2 hardware fault — surfaces as ParityProbeError on RHEL).
  F22 (parity drift severity classification per D65).
  F23 (documented_exceptions expiration — expired exceptions auto-rejected).

B-numbers: B-243 (M8 Wave 5 build).

Spec: phase1/03_core_modules.md § 3.2 (canonical module spec L773-822).
Round 2 § 4: phase1/02_configuration.md § 4.1 (baseline JSON L820-915) +
§ 4.2 (verifier interface L957-961) + § 4.3 (severity classification L1003-1015).
Round 4 § 3.7: phase1/04_tools.md L951-1024 (CLI shim wraps same signature).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Module path
# ---------------------------------------------------------------------------

_TOOL_PATH = _PROJECT_ROOT / "tools" / "verify_server_parity.py"
_TOOL_MODULE_KEY = "tools.verify_server_parity"

# ---------------------------------------------------------------------------
# Constants — single source of truth
# ---------------------------------------------------------------------------

# D76 EventType per CLI_* family — written by CLI shim per § 3.7, not by module
EXPECTED_EVENT_TYPE = "PARITY_VERIFY"

# Canonical R2 § 4.2 L955 overall enum (3 values)
OVERALL_PASS = "pass"
OVERALL_WARN = "warn"
OVERALL_FAIL = "fail"
VALID_OVERALL = {OVERALL_PASS, OVERALL_WARN, OVERALL_FAIL}

# Canonical R2 § 4.2 L941 severity enum (4 values)
SEVERITY_FATAL = "fatal"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "informational"
SEVERITY_MATCH = "match"
VALID_SEVERITY = {SEVERITY_FATAL, SEVERITY_WARNING, SEVERITY_INFO, SEVERITY_MATCH}


# ---------------------------------------------------------------------------
# Module loader — per B214: pre-register sys.modules BEFORE exec_module
# ---------------------------------------------------------------------------


def _load_tool_module() -> Any:
    """Load tools/verify_server_parity.py with no external deps that need
    mocking (the module uses only stdlib + utils.errors, both real)."""
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    spec = importlib.util.spec_from_file_location(_TOOL_MODULE_KEY, _TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    # B214: pre-register BEFORE exec_module
    sys.modules[_TOOL_MODULE_KEY] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fixture baselines + actuals
# ---------------------------------------------------------------------------


def _make_baseline(**overrides: Any) -> dict[str, Any]:
    """Build a canonical baseline dict per R2 § 4.1 L820-915.

    Defaults match what an all-match probe run would produce.
    """
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "baseline_name": "pipeline-baseline-v1.0.0",
        "pinned_at": "2026-05-13T00:00:00Z",
        "pinned_by": "test",
        "pipeline_version": "1.0.0",
        "operating_system": {
            "distro": "RHEL",
            "version": "9.4",
            "kernel": "5.14.0-test",
            "kernel_match_policy": "major_minor",
        },
        "python": {
            "version": "3.12.11",
            "pip_freeze_sha256": "sha256:abc123",
        },
        "native_libraries": {
            "oracle_instant_client_version": "19.21.0",
            "oracle_instant_client_dir": "/opt/oracle/instantclient_19_21",
            "odbc_driver_version": "18.3.2.1-1",
            "odbc_driver_name": "ODBC Driver 18 for SQL Server",
            "mssql_tools_version": "18.3.2.1-1",
            "mssql_tools_dir": "/opt/mssql-tools18",
            "gpg_version": "2.3.3-2.el9",
        },
        "env_vars_required": {
            "MALLOC_ARENA_MAX": "2",
            "ORACLE_HOME": "/opt/oracle/instantclient_19_21",
            "LD_LIBRARY_PATH": "/opt/oracle/instantclient_19_21",
            "TZ": "UTC",
        },
        "filesystem_layout": [],
        "systemd_unit": {
            "path": "/etc/systemd/system/pipeline.service",
            "sha256": "sha256:sysd_hash",
        },
        "tpm2": {
            "required": True,
            "pcr_policy_hash": "sha256:pcr_hash",
            "tpm2_tools_version": "5.2-3.el9",
        },
        "credentials_envelope": {
            "path": "/etc/pipeline/credentials.json.gpg",
            "sha256": "sha256:env_hash",
            "schema_version": "1.0",
            "recipient_count": 2,
        },
        "udm_tables_list_schema": {
            "spec_doc": "phase1/02_configuration.md § 1",
            "expected_columns_sha256": "sha256:udm_hash",
        },
        "documented_exceptions": [],
    }
    base.update(overrides)
    return base


def _write_baseline_fixture(tmp_path: Path, baseline: dict[str, Any]) -> Path:
    """Write a baseline dict to a tmp_path file and return the path."""
    fixture = tmp_path / "parity_baseline.json"
    fixture.write_text(json.dumps(baseline), encoding="utf-8")
    return fixture


def _patch_actuals(mod: Any, all_match_baseline: dict[str, Any]) -> Any:
    """Build a mock-runner that returns matching values for every probe.

    The module's probes are intercepted at the ``_runner`` keyword by
    patching ``_probe_*_actual`` and ``_probe_filesystem_actual`` functions
    on the module directly to return the matching values from the baseline.
    """
    os_block = all_match_baseline.get("operating_system", {})
    py_block = all_match_baseline.get("python", {})
    nl_block = all_match_baseline.get("native_libraries", {})
    sysd_block = all_match_baseline.get("systemd_unit", {})
    tpm_block = all_match_baseline.get("tpm2", {})
    creds_block = all_match_baseline.get("credentials_envelope", {})
    udm_block = all_match_baseline.get("udm_tables_list_schema", {})

    mod._probe_operating_system_actual = MagicMock(return_value={
        "distro": os_block.get("distro", "RHEL"),
        "version": os_block.get("version", "9.4"),
        "kernel": os_block.get("kernel", "5.14.0-test"),
    })
    mod._probe_python_actual = MagicMock(return_value={
        "version": py_block.get("version", "3.12.11"),
        "pip_freeze_sha256": py_block.get("pip_freeze_sha256", "sha256:abc123"),
    })
    mod._probe_native_libraries_actual = MagicMock(return_value={
        k: nl_block.get(k, "") for k in (
            "oracle_instant_client_version",
            "oracle_instant_client_dir",
            "odbc_driver_version",
            "odbc_driver_name",
            "mssql_tools_version",
            "mssql_tools_dir",
            "gpg_version",
        )
    })
    mod._probe_env_vars_actual = MagicMock(
        side_effect=lambda keys: {
            k: all_match_baseline.get("env_vars_required", {}).get(k, "") for k in keys
        }
    )
    mod._probe_filesystem_actual = MagicMock(return_value={
        "path": "/etc/pipeline/.env",
        "must_exist": True,
        "owner": "pipeline:pipeline",
        "mode": "0400",
    })
    mod._probe_systemd_unit_actual = MagicMock(
        return_value=sysd_block.get("sha256", "sha256:sysd_hash")
    )
    mod._probe_tpm2_actual = MagicMock(return_value={
        "pcr_policy_hash": tpm_block.get("pcr_policy_hash", "sha256:pcr_hash"),
        "tpm2_tools_version": tpm_block.get("tpm2_tools_version", "5.2-3.el9"),
        "getcap_status": "ok",
    })
    mod._probe_credentials_envelope_actual = MagicMock(return_value={
        "sha256": creds_block.get("sha256", "sha256:env_hash"),
        "schema_version": creds_block.get("schema_version", "1.0"),
        "recipient_count": creds_block.get("recipient_count", 2),
    })
    return mod


# ===========================================================================
# Tier 0 assertion (a): module imports without error
# ===========================================================================


def test_module_imports():
    """(a) Module imports without error.

    D67 Tier 0 assertion 1: the module must be importable; missing
    dependencies or syntax errors block every subsequent build step.
    Per B228 — the module imports its exception classes from utils.errors;
    if those imports are missing the module load fails here.

    Spec: phase1/03_core_modules.md § 3.2 L805(a).
    """
    _t0 = time.monotonic()

    mod = _load_tool_module()

    assert mod is not None, (
        "tools/verify_server_parity.py must load without error. "
        "Check for missing imports or syntax errors. D67 Tier 0 (a)."
    )
    # Public surface checks per § 3.2 + R2 § 4.2 canonical dataclasses
    assert hasattr(mod, "verify_server_parity"), (
        "Module must expose verify_server_parity() per R2 § 4.2 L957."
    )
    assert hasattr(mod, "ParityReport"), (
        "Module must expose ParityReport dataclass per R2 § 4.2 L948-955."
    )
    assert hasattr(mod, "ParityCheck"), (
        "Module must expose ParityCheck dataclass per R2 § 4.2 L941-947."
    )
    # B228: canonical exception imports — DO NOT define local classes
    assert hasattr(mod, "ParityFatalError"), (
        "Module must re-export ParityFatalError from utils.errors per B228."
    )
    assert hasattr(mod, "ParityBaselineMissing"), (
        "Module must re-export ParityBaselineMissing from utils.errors per B228."
    )
    assert hasattr(mod, "ParityProbeError"), (
        "Module must re-export ParityProbeError from utils.errors per B228."
    )

    elapsed = time.monotonic() - _t0
    assert elapsed < 5.0, f"Module load must complete in < 5 s. Took {elapsed:.2f} s."


# ===========================================================================
# Tier 0 assertion (b): verify_server_parity(baseline_path='fixture.json') invocable
# ===========================================================================


def test_verify_invocable_with_fixture(tmp_path: Path):
    """(b) verify_server_parity invocable with synthetic fixture baseline.

    Per D67 Tier 0 assertion 2 + § 3.2 L805(b). Builds a synthetic baseline
    JSON file at tmp_path, patches all probe functions to return matching
    values, invokes verify_server_parity(baseline_path=fixture). Must not
    raise.

    Spec: phase1/03_core_modules.md § 3.2 L805(b).
    """
    mod = _load_tool_module()
    baseline = _make_baseline()
    fixture = _write_baseline_fixture(tmp_path, baseline)
    _patch_actuals(mod, baseline)

    report = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")

    assert report is not None, "verify_server_parity must return a ParityReport, not None"
    assert isinstance(report, mod.ParityReport), (
        f"Return value must be ParityReport; got {type(report).__name__}"
    )


# ===========================================================================
# Tier 0 assertion (c): Returns ParityReport with overall in {pass, warn, fail}
# ===========================================================================


def test_overall_in_canonical_enum(tmp_path: Path):
    """(c) Report.overall ∈ {'pass', 'warn', 'fail'} per R2 § 4.2 L955.

    Spec: phase1/03_core_modules.md § 3.2 L805(c) + R2 § 4.2 L955.
    Pitfall #9.c: strict enum — only these three values are canonical.
    """
    mod = _load_tool_module()
    baseline = _make_baseline()
    fixture = _write_baseline_fixture(tmp_path, baseline)
    _patch_actuals(mod, baseline)

    report = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
    assert report.overall in VALID_OVERALL, (
        f"overall must be in {VALID_OVERALL}; got {report.overall!r}. "
        "R2 § 4.2 L955 canonical enum."
    )


# ===========================================================================
# Tier 0 assertion (d): all-match fixture returns overall='pass'
# ===========================================================================


def test_all_match_returns_pass(tmp_path: Path):
    """(d) All-match fixture returns overall='pass'.

    Per § 3.2 L805(d) + R2 § 4.3 — if every check is a 'match', overall
    must be 'pass'. fatal_count must be 0; warning_count must be 0;
    checks list must be non-empty.

    Spec: phase1/03_core_modules.md § 3.2 L805(d).
    """
    mod = _load_tool_module()
    baseline = _make_baseline()
    fixture = _write_baseline_fixture(tmp_path, baseline)
    _patch_actuals(mod, baseline)

    report = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
    assert report.overall == OVERALL_PASS, (
        f"All-match fixture must return overall='pass'; got {report.overall!r}. "
        f"Checks: {[(c.key, c.severity) for c in report.checks if c.severity != 'match']!r}"
    )
    assert report.fatal_count == 0, (
        f"All-match fixture must have fatal_count=0; got {report.fatal_count}"
    )
    assert report.warning_count == 0, (
        f"All-match fixture must have warning_count=0; got {report.warning_count}"
    )
    assert len(report.checks) > 0, "Report must have at least one check"


# ===========================================================================
# Tier 0 assertion (e): one fatal mismatch returns overall='fail' AND raises
# ===========================================================================


def test_one_fatal_mismatch_raises(tmp_path: Path):
    """(e) One fatal mismatch fixture raises ParityFatalError.

    Per § 3.2 L795 + L805(e): "any check in fatal tier failed; pipeline
    must NOT proceed" — verify_server_parity raises ParityFatalError
    before returning.

    Verifies fatal-tier classification per D65: python.pip_freeze_sha256
    drift is fatal because library versions affect code execution.

    Spec: phase1/03_core_modules.md § 3.2 L795 + L805(e).
    """
    mod = _load_tool_module()
    baseline = _make_baseline()
    fixture = _write_baseline_fixture(tmp_path, baseline)

    # Drift the actual pip_freeze hash (fatal-tier per _FATAL_KEYS)
    mod._probe_operating_system_actual = MagicMock(return_value={
        "distro": "RHEL", "version": "9.4", "kernel": "5.14.0-test",
    })
    mod._probe_python_actual = MagicMock(return_value={
        "version": "3.12.11",
        "pip_freeze_sha256": "sha256:DRIFTED",  # FATAL drift
    })
    mod._probe_native_libraries_actual = MagicMock(return_value=dict(
        baseline["native_libraries"]
    ))
    mod._probe_env_vars_actual = MagicMock(
        side_effect=lambda keys: {k: baseline["env_vars_required"].get(k, "") for k in keys}
    )
    mod._probe_filesystem_actual = MagicMock(return_value={
        "path": "", "must_exist": True, "owner": "pipeline:pipeline", "mode": "0400"
    })
    mod._probe_systemd_unit_actual = MagicMock(return_value=baseline["systemd_unit"]["sha256"])
    mod._probe_tpm2_actual = MagicMock(return_value={
        "pcr_policy_hash": baseline["tpm2"]["pcr_policy_hash"],
        "tpm2_tools_version": baseline["tpm2"]["tpm2_tools_version"],
        "getcap_status": "ok",
    })
    mod._probe_credentials_envelope_actual = MagicMock(return_value=dict(
        baseline["credentials_envelope"]
    ))

    with pytest.raises(mod.ParityFatalError) as exc_info:
        mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
    assert "fatal" in str(exc_info.value).lower(), (
        f"Exception message must reference 'fatal' drift; got {exc_info.value!r}"
    )


# ===========================================================================
# Tier 0 assertion (f): runtime < 5 s
# ===========================================================================


def test_tier0_total_runtime_under_5s(tmp_path: Path):
    """(f) Tier 0 total runtime < 5 s per D67.

    Sentinel test: if the module starts doing real I/O (subprocess,
    filesystem reads, DB connections) the runtime ceiling is breached and
    this test catches the regression.

    Spec: phase1/03_core_modules.md § 3.2 L805(f). D67 Tier 0 ceiling.
    """
    start = time.monotonic()

    mod = _load_tool_module()
    baseline = _make_baseline()
    fixture = _write_baseline_fixture(tmp_path, baseline)
    _patch_actuals(mod, baseline)
    report = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
    _ = report.to_dict()

    elapsed = time.monotonic() - start
    assert elapsed < 5.0, (
        f"Tier 0 ceiling: must complete < 5 s. Took {elapsed:.2f} s. D67."
    )
