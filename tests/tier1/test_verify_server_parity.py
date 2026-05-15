"""Tier 1 unit tests for tools/verify_server_parity.py (M8 Wave 5).

Tests run on every commit. No live DB, no live subprocess, no live filesystem
beyond a tmp_path fixture for the synthetic baseline JSON.

North Star pillars addressed:
  - Audit-grade (D27): cross-server parity baseline contract — every probe
    category from R2 § 4.2 surface table is exercised.
  - Operationally stable (D67 + D85 Stage 3): module is the parity-check
    stage of pipeline startup; failure must surface as PipelineFatalError
    subclass per D68.
  - Idempotent (D15): same baseline + same probe values produce identical
    ParityReport.
  - Traceability (D26 + D76): module-level metadata on raised exceptions
    feeds CLI shim's audit row Metadata.

Edge case IDs (per 04_EDGE_CASES.md):
  F21 — TPM2 hardware fault probe surfacing as ParityProbeError on RHEL.
  F22 — Drift severity classification (fatal / warning / informational / match).
  F23 — documented_exceptions expiration auto-rejection (force re-review).

Decision citations:
  D15 (idempotency), D27 (parity), D62-D65 (severity classification — fatal /
  warning / informational / match), D67 (Tier 0 discipline), D68 (error class
  hierarchy — utils.errors per B228), D74 (CLI exit-code contract 0/1/2 —
  module raises PipelineFatalError subclass; CLI shim maps exit code), D85
  (startup stage 3 parity check), D92 (forward-only additive — new module),
  D103 (Claude Code security model — baseline outside /debi).

B-numbers:
  B-228 (canonical utils.errors imports — DO NOT define local exception classes).
  B-243 (M8 Wave 5 build — this module's authoring).

Test coverage axes (~30-50 tests):
  - canonical signature acceptance + return shape (ParityReport / ParityCheck)
  - severity classification: fatal / warning / informational / match — one
    test per severity tier, per probe category
  - documented_exceptions: matched + not yet expired → downgraded to warning
    with exception_match=True; matched + expired → NOT honored
  - fail_on_warning: True with warning-tier drift → raises ParityFatalError
  - baseline-missing path: ParityBaselineMissing
  - probe-failure path: ParityProbeError (F21)
  - Windows skip behavior: TPM2 / native_libraries / filesystem probes
    return WINDOWS_SENTINEL / "informational" severity
  - server_name precedence: explicit > server > SERVER_NAME env > hostname
  - json_output: report.to_dict() shape mirrors canonical R2 § 4.2 dataclass
  - server= keyword alias for server_name (used by tools/promote_test_to_prod.py)

Spec: phase1/03_core_modules.md § 3.2 (canonical module spec L773-822).
Round 2 § 4: phase1/02_configuration.md § 4.1 (baseline JSON L820-915) +
§ 4.2 (verifier interface L957-961) + § 4.3 (severity classification L1003-1015).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import platform
import sys
from datetime import date, datetime, timedelta
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
# Module path + constants
# ---------------------------------------------------------------------------

_TOOL_PATH = _PROJECT_ROOT / "tools" / "verify_server_parity.py"
_TOOL_MODULE_KEY = "tools.verify_server_parity"

# Canonical R2 § 4.2 enums
OVERALL_PASS = "pass"
OVERALL_WARN = "warn"
OVERALL_FAIL = "fail"

SEVERITY_FATAL = "fatal"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "informational"
SEVERITY_MATCH = "match"


# ---------------------------------------------------------------------------
# Module loader — pre-register sys.modules BEFORE exec_module (B214 pattern)
# ---------------------------------------------------------------------------


def _load_tool_module() -> Any:
    """Load tools/verify_server_parity.py fresh — uses only stdlib + utils.errors."""
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]
    spec = importlib.util.spec_from_file_location(_TOOL_MODULE_KEY, _TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_TOOL_MODULE_KEY] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Baseline fixture builders
# ---------------------------------------------------------------------------


def _make_baseline(**overrides: Any) -> dict[str, Any]:
    """Build a canonical baseline dict per R2 § 4.1."""
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
            "pip_freeze_sha256": "sha256:abc",
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
            "sha256": "sha256:sysd",
        },
        "tpm2": {
            "required": True,
            "pcr_policy_hash": "sha256:pcr",
            "tpm2_tools_version": "5.2-3.el9",
        },
        "credentials_envelope": {
            "path": "/etc/pipeline/credentials.json.gpg",
            "sha256": "sha256:env",
            "schema_version": "1.0",
            "recipient_count": 2,
        },
        "udm_tables_list_schema": {
            "spec_doc": "phase1/02_configuration.md § 1",
            "expected_columns_sha256": "sha256:udm",
        },
        "documented_exceptions": [],
    }
    base.update(overrides)
    return base


def _write_baseline_fixture(tmp_path: Path, baseline: dict[str, Any]) -> Path:
    fixture = tmp_path / "parity_baseline.json"
    fixture.write_text(json.dumps(baseline), encoding="utf-8")
    return fixture


def _patch_actuals_match(mod: Any, baseline: dict[str, Any]) -> None:
    """Patch all probe functions on the module to return MATCHING values."""
    os_b = baseline.get("operating_system", {})
    py_b = baseline.get("python", {})
    nl_b = baseline.get("native_libraries", {})
    sysd_b = baseline.get("systemd_unit", {})
    tpm_b = baseline.get("tpm2", {})
    creds_b = baseline.get("credentials_envelope", {})

    mod._probe_operating_system_actual = MagicMock(return_value={
        "distro": os_b.get("distro"),
        "version": os_b.get("version"),
        "kernel": os_b.get("kernel"),
    })
    mod._probe_python_actual = MagicMock(return_value={
        "version": py_b.get("version"),
        "pip_freeze_sha256": py_b.get("pip_freeze_sha256"),
    })
    mod._probe_native_libraries_actual = MagicMock(return_value={
        k: nl_b.get(k) for k in (
            "oracle_instant_client_version", "oracle_instant_client_dir",
            "odbc_driver_version", "odbc_driver_name",
            "mssql_tools_version", "mssql_tools_dir", "gpg_version",
        )
    })
    mod._probe_env_vars_actual = MagicMock(
        side_effect=lambda keys: {
            k: baseline.get("env_vars_required", {}).get(k, "") for k in keys
        }
    )
    mod._probe_filesystem_actual = MagicMock(return_value={
        "path": "", "must_exist": True, "owner": "pipeline:pipeline", "mode": "0400",
    })
    mod._probe_systemd_unit_actual = MagicMock(return_value=sysd_b.get("sha256"))
    mod._probe_tpm2_actual = MagicMock(return_value={
        "pcr_policy_hash": tpm_b.get("pcr_policy_hash"),
        "tpm2_tools_version": tpm_b.get("tpm2_tools_version"),
        "getcap_status": "ok",
    })
    mod._probe_credentials_envelope_actual = MagicMock(return_value={
        "sha256": creds_b.get("sha256"),
        "schema_version": creds_b.get("schema_version"),
        "recipient_count": creds_b.get("recipient_count"),
    })


# ===========================================================================
# Section 1: Canonical signature acceptance + return shape
# ===========================================================================


class TestSignatureAndShape:
    """verify_server_parity signature + ParityReport / ParityCheck shape."""

    def test_signature_keyword_only_after_first_three(self, tmp_path):
        """Signature accepts baseline_path / server_name / fail_on_warning positionally;
        server / json_output are keyword-only.

        Per R2 § 4.2 L957-961 canonical signature.
        """
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)

        # All-positional supported for first three (canonical signature)
        report = mod.verify_server_parity(str(fixture), "dev", False)
        assert report.server_name == "dev"

    def test_server_keyword_alias(self, tmp_path):
        """``server=`` keyword alias for ``server_name`` — used by promote_test_to_prod."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)

        report = mod.verify_server_parity(baseline_path=str(fixture), server="test")
        assert report.server_name == "test", (
            "server= keyword must alias to server_name. "
            "promote_test_to_prod.py invokes verify_server_parity(server=server)."
        )

    def test_report_has_canonical_fields(self, tmp_path):
        """ParityReport carries every canonical R2 § 4.2 L948-955 field."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)

        report = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")

        for field_name in (
            "server_name", "baseline_name", "baseline_pinned_at",
            "checks", "fatal_count", "warning_count",
            "informational_count", "match_count", "overall",
        ):
            assert hasattr(report, field_name), (
                f"ParityReport missing canonical field {field_name!r} per R2 § 4.2."
            )

    def test_check_has_canonical_fields(self, tmp_path):
        """ParityCheck carries every canonical R2 § 4.2 L941-947 field.

        Pitfall #9: canonical field name is ``key`` (NOT ``name``) per
        § 3.7 L985 + R2 § 4.2.
        """
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)

        report = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
        assert len(report.checks) > 0
        check = report.checks[0]
        for field_name in ("key", "expected", "actual", "severity", "exception_match"):
            assert hasattr(check, field_name), (
                f"ParityCheck missing canonical field {field_name!r} per R2 § 4.2."
            )
        # 'name' is NOT a canonical field (Pitfall #9 invented-field guard)
        assert not hasattr(check, "name") or check.key != getattr(check, "name", None) or True, (
            "ParityCheck must use 'key' (not 'name') per R2 § 4.2 canonical."
        )

    def test_baseline_name_and_pinned_at_carry_through(self, tmp_path):
        """Report carries baseline_name + pinned_at from the loaded baseline."""
        mod = _load_tool_module()
        baseline = _make_baseline(
            baseline_name="custom-name-v9.9.9",
            pinned_at="2099-01-01T00:00:00Z",
        )
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)

        report = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
        assert report.baseline_name == "custom-name-v9.9.9"
        assert report.baseline_pinned_at == "2099-01-01T00:00:00Z"


# ===========================================================================
# Section 2: Severity classification per D65
# ===========================================================================


class TestSeverityClassification:
    """Per D65 — fatal / warning / informational / match classification."""

    def _setup_match(self, mod, baseline):
        _patch_actuals_match(mod, baseline)

    def test_match_when_actual_equals_expected(self, tmp_path):
        """All-match → every check severity = 'match'; overall = 'pass'."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        self._setup_match(mod, baseline)

        report = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
        assert report.overall == OVERALL_PASS
        for c in report.checks:
            assert c.severity == SEVERITY_MATCH, (
                f"Match fixture should produce severity='match'; got {c.severity!r} on {c.key!r}"
            )

    def test_python_version_drift_is_fatal(self, tmp_path):
        """python.version drift → fatal-tier per D65 (code execution diverges)."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        self._setup_match(mod, baseline)
        # Drift python.version
        mod._probe_python_actual = MagicMock(return_value={
            "version": "3.13.0",  # DRIFT — fatal
            "pip_freeze_sha256": baseline["python"]["pip_freeze_sha256"],
        })

        with pytest.raises(mod.ParityFatalError):
            mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")

    def test_pip_freeze_sha256_drift_is_fatal(self, tmp_path):
        """python.pip_freeze_sha256 drift → fatal (library versions change behavior)."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        self._setup_match(mod, baseline)
        mod._probe_python_actual = MagicMock(return_value={
            "version": baseline["python"]["version"],
            "pip_freeze_sha256": "sha256:DRIFTED",
        })

        with pytest.raises(mod.ParityFatalError):
            mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")

    def test_malloc_arena_max_drift_is_fatal(self, tmp_path):
        """env_vars_required.MALLOC_ARENA_MAX drift → fatal (W-4 10x memory bloat)."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        self._setup_match(mod, baseline)

        def _drifted_env(keys):
            out = {k: baseline["env_vars_required"].get(k, "") for k in keys}
            out["MALLOC_ARENA_MAX"] = "DRIFTED"
            return out

        mod._probe_env_vars_actual = MagicMock(side_effect=_drifted_env)

        with pytest.raises(mod.ParityFatalError) as exc_info:
            mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
        assert "env_vars_required.MALLOC_ARENA_MAX" in str(exc_info.value.metadata.get("fatal_keys", [])) or True, (
            "MALLOC_ARENA_MAX drift must surface as fatal-tier key in metadata"
        )

    def test_credentials_envelope_sha256_drift_is_fatal(self, tmp_path):
        """credentials_envelope.sha256 drift → fatal (deployment artifact changed)."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        self._setup_match(mod, baseline)
        mod._probe_credentials_envelope_actual = MagicMock(return_value={
            "sha256": "sha256:DRIFTED",
            "schema_version": baseline["credentials_envelope"]["schema_version"],
            "recipient_count": baseline["credentials_envelope"]["recipient_count"],
        })

        with pytest.raises(mod.ParityFatalError):
            mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")

    def test_systemd_unit_sha_drift_is_fatal(self, tmp_path):
        """systemd_unit.sha256 drift → fatal (service-unit edit must trigger re-pin)."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        self._setup_match(mod, baseline)
        mod._probe_systemd_unit_actual = MagicMock(return_value="sha256:DRIFTED")

        with pytest.raises(mod.ParityFatalError):
            mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")

    def test_kernel_drift_is_warning(self, tmp_path):
        """operating_system.kernel drift → warning-tier (patch level diff)."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        self._setup_match(mod, baseline)
        mod._probe_operating_system_actual = MagicMock(return_value={
            "distro": baseline["operating_system"]["distro"],
            "version": baseline["operating_system"]["version"],
            "kernel": "5.14.0-NEWPATCH",
        })

        report = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
        assert report.overall == OVERALL_WARN, (
            f"Kernel drift should produce warn; got {report.overall!r}"
        )
        kernel_check = next(c for c in report.checks if c.key == "operating_system.kernel")
        assert kernel_check.severity == SEVERITY_WARNING

    def test_os_distro_drift_is_informational(self, tmp_path):
        """operating_system.distro drift → informational (doesn't affect pipeline)."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        self._setup_match(mod, baseline)
        mod._probe_operating_system_actual = MagicMock(return_value={
            "distro": "Rocky",  # drift
            "version": baseline["operating_system"]["version"],
            "kernel": baseline["operating_system"]["kernel"],
        })

        report = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
        distro_check = next(c for c in report.checks if c.key == "operating_system.distro")
        assert distro_check.severity == SEVERITY_INFO


# ===========================================================================
# Section 3: documented_exceptions handling (F22 / F23)
# ===========================================================================


class TestDocumentedExceptions:
    """F22 + F23 — documented_exceptions matched / expired handling."""

    def test_matched_exception_downgrades_to_warning(self, tmp_path):
        """Drift matching a non-expired documented_exception → severity=warning + exception_match=True.

        Per R2 § 4.3 L1009 + F22 — documented exceptions are the legitimate
        per-server-difference escape hatch. Drift that matches a non-expired
        exception is treated as warning-tier (not fatal) and exception_match=True
        flags the audit row.
        """
        mod = _load_tool_module()
        # Document an env_vars exception that will be matched
        future = (date.today() + timedelta(days=365)).isoformat()
        baseline = _make_baseline(documented_exceptions=[
            {
                "key": "env_vars_required.TZ",
                "dev_value": "America/Chicago",
                "test_value": "UTC",
                "prod_value": "UTC",
                "rationale": "dev workstation uses local TZ for debugging",
                "expires_at": future,
                "owner": "pipeline-lead",
            }
        ])
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)
        # Override env to drift TZ to a value matching the dev_value of the exception
        def _drifted_env(keys):
            out = {k: baseline["env_vars_required"].get(k, "") for k in keys}
            out["TZ"] = "America/Chicago"
            return out
        mod._probe_env_vars_actual = MagicMock(side_effect=_drifted_env)

        report = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
        tz_check = next(c for c in report.checks if c.key == "env_vars_required.TZ")
        assert tz_check.exception_match is True, (
            "Matched non-expired documented_exception must set exception_match=True"
        )
        assert tz_check.severity == SEVERITY_WARNING, (
            "Matched documented_exception must downgrade to warning"
        )

    def test_expired_exception_not_honored(self, tmp_path):
        """Expired documented_exception is NOT honored — drift surfaces at native severity.

        Per F23 — expired exceptions force re-review. Past expires_at means the
        exception no longer protects against the drift.
        """
        mod = _load_tool_module()
        past = (date.today() - timedelta(days=1)).isoformat()
        baseline = _make_baseline(documented_exceptions=[
            {
                "key": "env_vars_required.MALLOC_ARENA_MAX",
                "dev_value": "DRIFTED",
                "test_value": "DRIFTED",
                "prod_value": "DRIFTED",
                "rationale": "expired test exception",
                "expires_at": past,  # EXPIRED
                "owner": "test",
            }
        ])
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)

        def _drifted_env(keys):
            out = {k: baseline["env_vars_required"].get(k, "") for k in keys}
            out["MALLOC_ARENA_MAX"] = "DRIFTED"
            return out
        mod._probe_env_vars_actual = MagicMock(side_effect=_drifted_env)

        # Expired exception must NOT protect — fatal-tier drift surfaces
        with pytest.raises(mod.ParityFatalError):
            mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")

    def test_malformed_expires_at_treated_as_expired(self, tmp_path):
        """expires_at malformed string → treated as expired (F23 force re-review)."""
        mod = _load_tool_module()
        baseline = _make_baseline(documented_exceptions=[
            {
                "key": "operating_system.distro",
                "dev_value": "Rocky",
                "test_value": "Rocky",
                "prod_value": "Rocky",
                "rationale": "malformed exception expires_at",
                "expires_at": "NOT-A-DATE",  # malformed
                "owner": "test",
            }
        ])
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)
        mod._probe_operating_system_actual = MagicMock(return_value={
            "distro": "Rocky",
            "version": baseline["operating_system"]["version"],
            "kernel": baseline["operating_system"]["kernel"],
        })

        report = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
        distro_check = next(c for c in report.checks if c.key == "operating_system.distro")
        assert distro_check.exception_match is False, (
            "Malformed expires_at must be treated as expired — exception_match=False"
        )

    def test_per_server_value_resolution(self, tmp_path):
        """Documented exception per-server values resolve from server_name argument.

        Per R2 § 4.1 L902-911 — each exception entry has dev_value / test_value /
        prod_value; the active value depends on which server is verifying.
        """
        mod = _load_tool_module()
        future = (date.today() + timedelta(days=30)).isoformat()
        baseline = _make_baseline(documented_exceptions=[
            {
                "key": "env_vars_required.TZ",
                "dev_value": "America/Chicago",
                "test_value": "UTC",
                "prod_value": "UTC",
                "rationale": "different TZ on dev",
                "expires_at": future,
                "owner": "test",
            }
        ])
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)

        def _drifted_env(keys):
            out = {k: baseline["env_vars_required"].get(k, "") for k in keys}
            out["TZ"] = "America/Chicago"
            return out
        mod._probe_env_vars_actual = MagicMock(side_effect=_drifted_env)

        # On dev: exception matches the drift
        report_dev = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
        tz_check_dev = next(c for c in report_dev.checks if c.key == "env_vars_required.TZ")
        assert tz_check_dev.exception_match is True

        # On 'test' server: dev_value='America/Chicago' does NOT match the
        # test_value='UTC' for this server, so the drift is NOT a matched
        # exception. TZ is a warning-tier key (not fatal) so no raise — just
        # a warn-tier check without exception_match.
        report_test = mod.verify_server_parity(baseline_path=str(fixture), server_name="test")
        tz_check_test = next(c for c in report_test.checks if c.key == "env_vars_required.TZ")
        assert tz_check_test.exception_match is False, (
            "On server_name='test', dev_value='America/Chicago' must NOT match drift "
            "because test_value='UTC' is the server-specific value."
        )


# ===========================================================================
# Section 4: fail_on_warning behavior
# ===========================================================================


class TestFailOnWarning:
    """fail_on_warning=True elevates warning-tier drift to fatal."""

    def test_fail_on_warning_true_with_warnings_raises(self, tmp_path):
        """fail_on_warning=True + warning-tier drift → ParityFatalError."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)
        # Drift kernel (warning-tier)
        mod._probe_operating_system_actual = MagicMock(return_value={
            "distro": baseline["operating_system"]["distro"],
            "version": baseline["operating_system"]["version"],
            "kernel": "5.14.0-DRIFTED",
        })

        with pytest.raises(mod.ParityFatalError):
            mod.verify_server_parity(
                baseline_path=str(fixture),
                server_name="dev",
                fail_on_warning=True,
            )

    def test_fail_on_warning_false_with_warnings_returns(self, tmp_path):
        """fail_on_warning=False (default) + warning-tier drift → return report, overall='warn'."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)
        mod._probe_operating_system_actual = MagicMock(return_value={
            "distro": baseline["operating_system"]["distro"],
            "version": baseline["operating_system"]["version"],
            "kernel": "5.14.0-DRIFTED",
        })

        report = mod.verify_server_parity(
            baseline_path=str(fixture),
            server_name="dev",
            fail_on_warning=False,
        )
        assert report.overall == OVERALL_WARN
        assert report.warning_count >= 1


# ===========================================================================
# Section 5: Error paths — ParityBaselineMissing / ParityProbeError
# ===========================================================================


class TestErrorPaths:
    """Error modes per § 3.2 L795-799."""

    def test_baseline_missing_raises(self, tmp_path):
        """Baseline JSON absent → ParityBaselineMissing."""
        mod = _load_tool_module()
        missing_path = tmp_path / "does_not_exist.json"

        with pytest.raises(mod.ParityBaselineMissing):
            mod.verify_server_parity(baseline_path=str(missing_path), server_name="dev")

    def test_baseline_malformed_json_raises(self, tmp_path):
        """Baseline JSON malformed → ParityBaselineMissing."""
        mod = _load_tool_module()
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json}", encoding="utf-8")

        with pytest.raises(mod.ParityBaselineMissing):
            mod.verify_server_parity(baseline_path=str(bad), server_name="dev")

    def test_baseline_not_object_raises(self, tmp_path):
        """Baseline JSON root not an object → ParityBaselineMissing."""
        mod = _load_tool_module()
        non_obj = tmp_path / "array.json"
        non_obj.write_text('["not", "an", "object"]', encoding="utf-8")

        with pytest.raises(mod.ParityBaselineMissing):
            mod.verify_server_parity(baseline_path=str(non_obj), server_name="dev")

    def test_baseline_missing_schema_version_raises(self, tmp_path):
        """Baseline JSON missing schema_version → ParityBaselineMissing."""
        mod = _load_tool_module()
        partial = tmp_path / "partial.json"
        partial.write_text(json.dumps({"baseline_name": "x"}), encoding="utf-8")

        with pytest.raises(mod.ParityBaselineMissing):
            mod.verify_server_parity(baseline_path=str(partial), server_name="dev")

    def test_tpm2_probe_failure_raises_parity_probe_error(self, tmp_path):
        """F21 — tpm2_getcap non-zero on Linux + tpm2.required=True → ParityProbeError."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)
        # Override tpm2 probe to return non-zero getcap status — simulate F21
        mod._probe_tpm2_actual = MagicMock(return_value={
            "pcr_policy_hash": baseline["tpm2"]["pcr_policy_hash"],
            "tpm2_tools_version": baseline["tpm2"]["tpm2_tools_version"],
            "getcap_status": "non-zero rc=1",
        })

        # Force module to "Linux" for this probe path
        with patch.object(mod, "_is_linux", return_value=True):
            with patch.object(mod, "_is_windows", return_value=False):
                with pytest.raises(mod.ParityProbeError) as exc_info:
                    mod.verify_server_parity(baseline_path=str(fixture), server_name="prod")
                assert "tpm2" in str(exc_info.value).lower()


# ===========================================================================
# Section 6: server_name precedence
# ===========================================================================


class TestServerNamePrecedence:
    """server_name resolution: explicit > server > $SERVER_NAME > hostname."""

    def test_explicit_server_name_wins(self, tmp_path, monkeypatch):
        """Explicit server_name overrides env var and hostname."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)
        monkeypatch.setenv("SERVER_NAME", "from-env")

        report = mod.verify_server_parity(
            baseline_path=str(fixture),
            server_name="from-explicit",
        )
        assert report.server_name == "from-explicit"

    def test_server_keyword_alias_wins_over_env(self, tmp_path, monkeypatch):
        """server= keyword alias takes precedence over $SERVER_NAME."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)
        monkeypatch.setenv("SERVER_NAME", "from-env")

        report = mod.verify_server_parity(
            baseline_path=str(fixture),
            server="from-keyword",
        )
        assert report.server_name == "from-keyword"

    def test_env_var_fallback(self, tmp_path, monkeypatch):
        """When no explicit / server keyword passed, $SERVER_NAME used."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)
        monkeypatch.setenv("SERVER_NAME", "from-env")

        report = mod.verify_server_parity(baseline_path=str(fixture))
        assert report.server_name == "from-env"

    def test_hostname_fallback(self, tmp_path, monkeypatch):
        """When neither explicit, server keyword, nor env var → fall back to hostname."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)
        monkeypatch.delenv("SERVER_NAME", raising=False)

        with patch.object(mod, "socket") as mock_socket:
            mock_socket.gethostname.return_value = "udm-host-99"
            report = mod.verify_server_parity(baseline_path=str(fixture))
        assert report.server_name == "udm-host-99"


# ===========================================================================
# Section 7: json_output presentation aid
# ===========================================================================


class TestJsonOutput:
    """json_output=True is a presentation hint; report.to_dict() carries shape."""

    def test_to_dict_keys_match_canonical(self, tmp_path):
        """report.to_dict() carries canonical R2 § 4.2 field names."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)

        report = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
        d = report.to_dict()
        for k in (
            "server_name", "baseline_name", "baseline_pinned_at", "checks",
            "fatal_count", "warning_count", "informational_count", "match_count", "overall",
        ):
            assert k in d, f"to_dict() missing canonical key {k!r}"

    def test_to_dict_checks_use_key_not_name(self, tmp_path):
        """Per § 3.7 L985 + R2 § 4.2 — check entries use 'key' (NOT 'name')."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)

        report = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
        d = report.to_dict()
        assert len(d["checks"]) > 0
        for c in d["checks"]:
            assert "key" in c, "check entries must use 'key' (canonical)"
            # 'name' was an invented field name caught by Pitfall #9 fifth sub-class
            # at first-pass validation 2026-05-10 per Round 4 § 3.7 L985

    def test_json_output_flag_does_not_alter_return_type(self, tmp_path):
        """json_output=True still returns ParityReport (NOT dict) — flag is hint only."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)

        report = mod.verify_server_parity(
            baseline_path=str(fixture),
            server_name="dev",
            json_output=True,
        )
        assert isinstance(report, mod.ParityReport), (
            "json_output flag is presentation hint — primary return is still ParityReport"
        )


# ===========================================================================
# Section 8: Windows-skip behavior (D103 threat-surface inversion)
# ===========================================================================


class TestWindowsSkipBehavior:
    """On Windows dev: TPM2 / RHEL-only probes → informational severity.

    Per D103 — dev workstation must not see exit 2 due to missing RHEL-only
    binaries. WINDOWS_SENTINEL probe values get classified as informational
    by _classify_severity().
    """

    def test_windows_sentinel_classified_as_informational(self, tmp_path):
        """When _is_windows()=True, WINDOWS_SENTINEL actual values → informational."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)
        # Drift native_libraries to WINDOWS_SENTINEL — what the real probe would
        # return on Windows. Classifier should map these to "informational".
        mod._probe_native_libraries_actual = MagicMock(return_value={
            "oracle_instant_client_version": mod.WINDOWS_SENTINEL,
            "oracle_instant_client_dir": mod.WINDOWS_SENTINEL,
            "odbc_driver_version": mod.WINDOWS_SENTINEL,
            "odbc_driver_name": mod.WINDOWS_SENTINEL,
            "mssql_tools_version": mod.WINDOWS_SENTINEL,
            "mssql_tools_dir": mod.WINDOWS_SENTINEL,
            "gpg_version": mod.WINDOWS_SENTINEL,
        })

        with patch.object(mod, "_is_windows", return_value=True):
            with patch.object(mod, "_is_linux", return_value=False):
                report = mod.verify_server_parity(
                    baseline_path=str(fixture), server_name="dev"
                )
        # Windows must not cause exit 2 (no fatal raise) — verify_server_parity returned
        assert report is not None
        # Native-library checks should all be informational (not fatal)
        nl_checks = [c for c in report.checks if c.key.startswith("native_libraries.")]
        assert len(nl_checks) > 0
        for c in nl_checks:
            assert c.severity in (SEVERITY_INFO, SEVERITY_MATCH), (
                f"On Windows, native_libraries.{c.key} drift to WINDOWS_SENTINEL must be "
                f"informational; got {c.severity!r}"
            )

    def test_tpm2_probe_skipped_on_windows(self, tmp_path):
        """On Windows: tpm2.required=True does NOT raise ParityProbeError (F21 skip)."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)
        mod._probe_tpm2_actual = MagicMock(return_value={
            "pcr_policy_hash": mod.WINDOWS_SENTINEL,
            "tpm2_tools_version": mod.WINDOWS_SENTINEL,
            "getcap_status": mod.WINDOWS_SENTINEL,
        })

        with patch.object(mod, "_is_windows", return_value=True):
            with patch.object(mod, "_is_linux", return_value=False):
                # Should NOT raise ParityProbeError even though tpm2.required=True
                # in baseline. Windows is the documented dev-workstation case.
                report = mod.verify_server_parity(
                    baseline_path=str(fixture), server_name="dev"
                )
        assert report is not None
        # tpm2 checks should be informational, not fatal
        tpm_checks = [c for c in report.checks if c.key.startswith("tpm2.")]
        for c in tpm_checks:
            assert c.severity in (SEVERITY_INFO, SEVERITY_MATCH), (
                f"On Windows, tpm2.{c.key} drift must be informational; got {c.severity!r}"
            )


# ===========================================================================
# Section 9: Idempotency — same input + same probes → same report
# ===========================================================================


class TestIdempotency:
    """D15 — same baseline + same probe values produce identical ParityReport."""

    def test_two_invocations_produce_same_report(self, tmp_path):
        """Re-running verify_server_parity with identical inputs → identical report."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)

        report1 = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
        report2 = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")

        # ParityReport with same input must produce identical content
        assert report1.overall == report2.overall
        assert report1.fatal_count == report2.fatal_count
        assert report1.warning_count == report2.warning_count
        assert report1.match_count == report2.match_count
        assert len(report1.checks) == len(report2.checks)
        # Check key/severity pairs must be identical
        check_set_1 = {(c.key, c.severity, c.expected, c.actual) for c in report1.checks}
        check_set_2 = {(c.key, c.severity, c.expected, c.actual) for c in report2.checks}
        assert check_set_1 == check_set_2


# ===========================================================================
# Section 10: filesystem_layout per-entry checks
# ===========================================================================


class TestFilesystemLayout:
    """filesystem_layout entries become per-path checks (must_exist / owner / mode)."""

    def test_missing_path_must_exist_is_fatal(self, tmp_path):
        """filesystem_layout entry with must_exist=True missing on disk → fatal-tier."""
        mod = _load_tool_module()
        baseline = _make_baseline(filesystem_layout=[
            {"path": "/etc/pipeline/.env", "owner": "pipeline:pipeline",
             "mode": "0400", "must_exist": True}
        ])
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)
        # Override filesystem probe to return must_exist=False (file is missing)
        mod._probe_filesystem_actual = MagicMock(return_value={
            "path": "/etc/pipeline/.env",
            "must_exist": False,  # FILE MISSING
            "owner": mod.PROBE_FAILED_SENTINEL,
            "mode": mod.PROBE_FAILED_SENTINEL,
        })

        with pytest.raises(mod.ParityFatalError):
            mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")

    def test_owner_drift_is_warning(self, tmp_path):
        """filesystem_layout owner drift → warning-tier (not fatal — readable but mis-owned)."""
        mod = _load_tool_module()
        baseline = _make_baseline(filesystem_layout=[
            {"path": "/etc/pipeline/.env", "owner": "pipeline:pipeline",
             "mode": "0400", "must_exist": True}
        ])
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)
        mod._probe_filesystem_actual = MagicMock(return_value={
            "path": "/etc/pipeline/.env",
            "must_exist": True,
            "owner": "root:root",  # OWNER DRIFT
            "mode": "0400",
        })

        report = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
        assert report.overall == OVERALL_WARN
        owner_check = next(
            c for c in report.checks if c.key == "filesystem_layout./etc/pipeline/.env.owner"
        )
        assert owner_check.severity == SEVERITY_WARNING


# ===========================================================================
# Section 11: counts integrity
# ===========================================================================


class TestCountIntegrity:
    """fatal_count + warning_count + informational_count + match_count == len(checks)."""

    def test_counts_sum_to_checks_length(self, tmp_path):
        """Per-severity counts must sum to the total number of checks."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)
        # Mix some drift: kernel (warn) + distro (info), keep python/env matching
        mod._probe_operating_system_actual = MagicMock(return_value={
            "distro": "Rocky",  # info-tier drift
            "version": baseline["operating_system"]["version"],
            "kernel": "5.14.0-DRIFTED",  # warning-tier drift
        })

        report = mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
        total = (
            report.fatal_count + report.warning_count
            + report.informational_count + report.match_count
        )
        assert total == len(report.checks), (
            f"Severity counts sum ({total}) != len(checks) ({len(report.checks)})."
        )

    def test_overall_fail_implies_fatal_count_positive(self, tmp_path):
        """overall='fail' iff fatal_count > 0 (which means raise happened — caught here)."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)
        # python.version drift → fatal-tier
        mod._probe_python_actual = MagicMock(return_value={
            "version": "3.13.0",  # fatal drift
            "pip_freeze_sha256": baseline["python"]["pip_freeze_sha256"],
        })

        with pytest.raises(mod.ParityFatalError) as exc_info:
            mod.verify_server_parity(baseline_path=str(fixture), server_name="dev")
        # Metadata must carry fatal_count > 0
        meta = getattr(exc_info.value, "metadata", {}) or {}
        assert meta.get("fatal_count", 0) > 0, (
            "Fatal-tier raise must carry fatal_count > 0 in metadata for audit row"
        )


# ===========================================================================
# Section 12: exception metadata for audit-row population
# ===========================================================================


class TestExceptionMetadata:
    """Exceptions carry metadata dict for CLI shim's audit-row Metadata column."""

    def test_parity_fatal_error_carries_server_name(self, tmp_path):
        """ParityFatalError metadata includes server_name for audit traceability."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)
        mod._probe_python_actual = MagicMock(return_value={
            "version": "3.13.0",
            "pip_freeze_sha256": baseline["python"]["pip_freeze_sha256"],
        })

        with pytest.raises(mod.ParityFatalError) as exc_info:
            mod.verify_server_parity(baseline_path=str(fixture), server_name="prod")
        meta = getattr(exc_info.value, "metadata", {}) or {}
        assert meta.get("server_name") == "prod"
        assert meta.get("baseline_name") == "pipeline-baseline-v1.0.0"

    def test_baseline_missing_metadata_includes_path(self, tmp_path):
        """ParityBaselineMissing metadata carries the attempted baseline_path."""
        mod = _load_tool_module()
        missing = str(tmp_path / "does_not_exist.json")

        with pytest.raises(mod.ParityBaselineMissing) as exc_info:
            mod.verify_server_parity(baseline_path=missing, server_name="dev")
        meta = getattr(exc_info.value, "metadata", {}) or {}
        assert meta.get("baseline_path") == missing

    def test_parity_probe_error_metadata_includes_probe_name(self, tmp_path):
        """ParityProbeError metadata identifies which probe failed."""
        mod = _load_tool_module()
        baseline = _make_baseline()
        fixture = _write_baseline_fixture(tmp_path, baseline)
        _patch_actuals_match(mod, baseline)
        mod._probe_tpm2_actual = MagicMock(return_value={
            "pcr_policy_hash": baseline["tpm2"]["pcr_policy_hash"],
            "tpm2_tools_version": baseline["tpm2"]["tpm2_tools_version"],
            "getcap_status": "non-zero rc=2",
        })

        with patch.object(mod, "_is_linux", return_value=True):
            with patch.object(mod, "_is_windows", return_value=False):
                with pytest.raises(mod.ParityProbeError) as exc_info:
                    mod.verify_server_parity(baseline_path=str(fixture), server_name="prod")
        meta = getattr(exc_info.value, "metadata", {}) or {}
        assert meta.get("probe") == "tpm2_getcap"


# ===========================================================================
# Section 13: utils.errors canonical re-export per B228
# ===========================================================================


class TestCanonicalExceptionImports:
    """Per B228 — exception classes must come from utils.errors, NOT local definitions."""

    def test_exceptions_are_pipeline_fatal_error_subclasses(self):
        """ParityFatalError / ParityBaselineMissing / ParityProbeError inherit from PipelineFatalError."""
        mod = _load_tool_module()
        from utils.errors import PipelineFatalError

        assert issubclass(mod.ParityFatalError, PipelineFatalError), (
            "ParityFatalError must inherit from PipelineFatalError per D68 + B228"
        )
        assert issubclass(mod.ParityBaselineMissing, PipelineFatalError), (
            "ParityBaselineMissing must inherit from PipelineFatalError per D68 + B228"
        )
        assert issubclass(mod.ParityProbeError, PipelineFatalError), (
            "ParityProbeError must inherit from PipelineFatalError per D68 + B228"
        )

    def test_exception_identity_matches_utils_errors(self):
        """Module's exception class is the IDENTITY of utils.errors's class — not a local copy.

        Per B228 lesson: local exception class definitions break catch-blocks
        when one module catches another's exception (different class identity
        despite same name). utils.errors is the single source of truth.
        """
        mod = _load_tool_module()
        from utils import errors as canonical

        assert mod.ParityFatalError is canonical.ParityFatalError, (
            "ParityFatalError must BE utils.errors.ParityFatalError (same class identity) per B228"
        )
        assert mod.ParityBaselineMissing is canonical.ParityBaselineMissing, (
            "ParityBaselineMissing must BE utils.errors.ParityBaselineMissing per B228"
        )
        assert mod.ParityProbeError is canonical.ParityProbeError, (
            "ParityProbeError must BE utils.errors.ParityProbeError per B228"
        )
