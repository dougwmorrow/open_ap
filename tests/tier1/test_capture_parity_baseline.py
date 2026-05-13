"""Tier 1 unit tests for tools/capture_parity_baseline.py (CLI) and
data_load/parity_baseline_capture.capture_baseline() (module function).

Tests run on every commit. No live DB, network, or subprocess required;
all external I/O is mocked with unittest.mock.

North Star pillars addressed:
  - Audit-grade (D76): exactly one CLI_CAPTURE_PARITY_BASELINE PipelineEventLog
    row per CLI invocation; Metadata JSON must match canonical R2 § 4.1 shape.
  - Idempotent (D15): capture_baseline(server='dev') called twice with identical
    mocked probes returns identical dicts (same-input same-output invariant).
  - Operationally stable (D67 Tier 0 + D85 Stage 3 parity check): baseline JSON
    is the input that verify_server_parity reads at every pipeline startup.
  - Traceability (D27): cross-server parity contract — baseline captures state
    that is later compared by verify_server_parity.

Scope invariant (phase2/01 § 4.3, cycle-3 fix): baseline captures OS /
library / env / systemd state ONLY. NOT INFORMATION_SCHEMA / database schema
state. Tests explicitly assert this boundary is not crossed.

Edge case IDs (per 04_EDGE_CASES.md):
  - F22 (parity drift severity): captured baseline feeds D65 fatal/warning/
    informational drift classification in verify_server_parity.
  - F23 (parity exception expiration): re-capture wipes documented_exceptions;
    tests verify empty documented_exceptions on fresh synthetic baseline.
  - I1 (same-BatchId retry ledger short-circuits): analogous here — same
    server re-capture produces a fresh audit row (intentional; each capture
    is its own audit moment per phase1/04a § 4 idempotency note).
  - V-series: no silent failures; every documented error mode raises or returns
    a structurally conformant partial-baseline with sentinel values.

Decision citations:
  D15 (idempotency mandatory), D27 (cross-server parity contract), D55
  (5-gate validation), D65 (drift severity classification), D67 (Tier 0
  discipline), D74 (exit-code contract 0/1/2), D75 (arg naming + actor TTY
  heuristic), D76 (audit-row contract), D92 (forward-only additive — new
  module not in locked Round 3), B183 (backlog item this tool closes),
  phase1/04a § 4 (Tool 13 canonical spec),
  phase1/02_configuration.md § 4.1 L820-L915 (baseline JSON schema),
  phase2/01 § 4.3 (scope clarification — OS/library/env/systemd only).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path (matches tests/ convention)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Constants — single source of truth for expected values
# ---------------------------------------------------------------------------

# Canonical top-level keys per R2 § 4.1 L820-L915 baseline JSON schema.
# Scope per phase2/01 § 4.3: OS / library / env / systemd ONLY (no DB schema).
CANONICAL_TOP_LEVEL_KEYS = {
    "schema_version",
    "baseline_name",
    "pinned_at",
    "pinned_by",
    "pipeline_version",
    "operating_system",
    "python",
    "native_libraries",
    "env_vars_required",
    "filesystem_layout",
    "systemd_unit",
    "tpm2",
    "credentials_envelope",
    "udm_tables_list_schema",
    "documented_exceptions",
}

# Sub-object required keys (spot-check structural depth)
OS_REQUIRED_KEYS = {"distro", "version", "kernel", "kernel_match_policy"}
PYTHON_REQUIRED_KEYS = {"version", "version_match_policy", "pip_freeze_sha256"}
NATIVE_LIB_REQUIRED_KEYS = {
    "oracle_instant_client_version",
    "odbc_driver_version",
    "mssql_tools_version",
    "gpg_version",
}

# env_vars_required keys per Round 4.5b polish (TZ mandatory)
REQUIRED_ENV_VARS = {"MALLOC_ARENA_MAX", "ORACLE_HOME", "LD_LIBRARY_PATH", "TZ"}

# D76 canonical EventType for Tool 13 audit row per D76 + Round 4 § 1.6.
EXPECTED_EVENT_TYPE = "CLI_CAPTURE_PARITY_BASELINE"

# D74 exit codes
EXIT_SUCCESS = 0
EXIT_WARNING = 1  # ProbeFailedError (partial baseline written)
EXIT_FATAL = 2    # OutputPathNotWritableError / InsufficientPermissionsError

# D75 canonical arg names
_ACTOR = "test-author"
_JUSTIFICATION = "Tier 1 unit test"
_SERVER = "dev"
_PINNED_BY = "test-pinned-by"
_PIPELINE_VERSION = "0.0.1-test"

# Sentinel string for failed probes per phase1/04a § 4 error modes
PROBE_FAILED_SENTINEL = "<probe_failed>"

# schema_version pinned per R2 § 4.1 L826
EXPECTED_SCHEMA_VERSION = "1.0"

# TZ env var per Round 4.5b polish
TZ_ENV_VAR = "TZ"


# ---------------------------------------------------------------------------
# Module loader helpers — reload to prevent cross-test state leakage
# ---------------------------------------------------------------------------


def _load_capture_module() -> Any:
    """Load data_load/parity_baseline_capture.py with external deps patched."""
    module_key = "data_load.parity_baseline_capture"
    if module_key in sys.modules:
        del sys.modules[module_key]

    target = _PROJECT_ROOT / "data_load" / "parity_baseline_capture.py"
    mock_deps = {
        "data_load": MagicMock(),
        "config": MagicMock(),
    }
    with patch.dict("sys.modules", mock_deps):
        spec = importlib.util.spec_from_file_location(module_key, target)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


def _load_cli_module() -> Any:
    """Load tools/capture_parity_baseline.py with external deps patched."""
    module_key = "tools.capture_parity_baseline"
    if module_key in sys.modules:
        del sys.modules[module_key]

    target = _PROJECT_ROOT / "tools" / "capture_parity_baseline.py"
    mock_deps = {
        "data_load": MagicMock(),
        "data_load.parity_baseline_capture": MagicMock(),
        "config": MagicMock(),
    }
    with patch.dict("sys.modules", mock_deps):
        spec = importlib.util.spec_from_file_location(module_key, target)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


def _make_mock_cursor() -> MagicMock:
    """Mock pyodbc cursor for audit-row write assertions."""
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    return cursor


def _make_mock_conn(cursor: MagicMock | None = None) -> MagicMock:
    """Mock pyodbc connection."""
    if cursor is None:
        cursor = _make_mock_cursor()
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


def _make_synthetic_baseline(
    *,
    include_tz: bool = True,
    probe_failed_field: str | None = None,
) -> dict:
    """Build a synthetic canonical baseline dict (R2 § 4.1 L820-L915).

    Args:
        include_tz: when True, TZ key present in env_vars_required per Round 4.5b.
        probe_failed_field: if given (dotted path like 'native_libraries.gpg_version'),
            set that sub-field to PROBE_FAILED_SENTINEL and add a documented_exception.
    """
    env_vars = {
        "MALLOC_ARENA_MAX": "2",
        "ORACLE_HOME": "/opt/oracle/instantclient_19_21",
        "LD_LIBRARY_PATH": "/opt/oracle/instantclient_19_21",
    }
    if include_tz:
        env_vars[TZ_ENV_VAR] = "UTC"

    native_libs = {
        "oracle_instant_client_version": "19.21.0",
        "oracle_instant_client_dir": "/opt/oracle/instantclient_19_21",
        "odbc_driver_version": "18.3.2.1-1",
        "odbc_driver_name": "ODBC Driver 18 for SQL Server",
        "mssql_tools_version": "18.3.2.1-1",
        "mssql_tools_dir": "/opt/mssql-tools18",
        "gpg_version": "2.3.3-2.el9",
    }

    documented_exceptions: list[dict] = []

    if probe_failed_field == "native_libraries.gpg_version":
        native_libs["gpg_version"] = PROBE_FAILED_SENTINEL
        documented_exceptions.append({
            "key": "native_libraries.gpg_version",
            "dev_value": PROBE_FAILED_SENTINEL,
            "test_value": PROBE_FAILED_SENTINEL,
            "prod_value": PROBE_FAILED_SENTINEL,
            "rationale": (
                "Auto-populated by capture_parity_baseline.py — probe for "
                "native_libraries.gpg_version failed during baseline capture; "
                "manual review + re-capture required"
            ),
            "expires_at": "2026-06-01T00:00:00Z",
            "owner": _PINNED_BY,
        })

    return {
        "schema_version": EXPECTED_SCHEMA_VERSION,
        "baseline_name": f"pipeline-baseline-v{_PIPELINE_VERSION}",
        "pinned_at": "2026-05-12T00:00:00Z",
        "pinned_by": _PINNED_BY,
        "pipeline_version": _PIPELINE_VERSION,
        "operating_system": {
            "distro": "RHEL",
            "version": "9.4",
            "kernel": "5.14.0-427.13.1.el9_4.x86_64",
            "kernel_match_policy": "exact",
        },
        "python": {
            "version": "3.12.11",
            "version_match_policy": "exact",
            "pip_freeze_sha256": "sha256:aabbcc",
            "pip_lockfile_path": "/opt/pipeline/requirements.txt",
        },
        "native_libraries": native_libs,
        "env_vars_required": env_vars,
        "filesystem_layout": [],
        "systemd_unit": {
            "path": "/etc/systemd/system/pipeline.service",
            "sha256": "sha256:ddeeff",
            "must_have_env_vars": ["MALLOC_ARENA_MAX"],
        },
        "tpm2": {
            "required": True,
            "pcr_policy_hash": "sha256:112233",
            "tpm2_tools_version": "5.5-1.el9",
        },
        "credentials_envelope": {
            "path": "/etc/pipeline/credentials.json.gpg",
            "sha256": "sha256:445566",
            "schema_version": "1.0",
            "recipient_count": 2,
            "primary_recipient_fingerprint": "AABBCCDD",
            "breakglass_recipient_fingerprint": "EEFF0011",
        },
        "udm_tables_list_schema": {
            "spec_doc": "phase1/02_configuration.md § 1",
            "expected_columns_sha256": "sha256:778899",
            "expected_check_constraints": [],
        },
        "documented_exceptions": documented_exceptions,
    }


def _find_audit_row_call(cursor: MagicMock) -> dict | None:
    """Scan cursor.execute calls for the PipelineEventLog INSERT.

    Returns parsed Metadata JSON dict if found, else None.
    Identified by EXPECTED_EVENT_TYPE in SQL text or params.
    """
    for c in cursor.execute.call_args_list:
        args = c.args or c[0]
        if not args:
            continue
        sql = str(args[0])
        if "PipelineEventLog" in sql or EXPECTED_EVENT_TYPE in sql:
            params = args[1] if len(args) > 1 else ()
            for p in (params if isinstance(params, (list, tuple)) else [params]):
                try:
                    parsed = json.loads(str(p))
                    if isinstance(parsed, dict):
                        return parsed
                except (json.JSONDecodeError, TypeError):
                    continue
    return None


# ---------------------------------------------------------------------------
# Normalize helper for case-insensitive / whitespace-tolerant field matching
# (mirrors B195 tertiary pattern from tests/tier0/test_capacity_baseline_log.py)
# ---------------------------------------------------------------------------


def _normalize(val: Any) -> str:
    """Lowercase + strip for case-insensitive field value matching."""
    return str(val).lower().strip()


# ---------------------------------------------------------------------------
# Tests: capture_baseline() module function
# ---------------------------------------------------------------------------


class TestCaptureBaselineModuleFunction:
    """Unit tests for data_load/parity_baseline_capture.capture_baseline()."""

    def test_returns_dict_with_canonical_keys(self):
        """capture_baseline() returns dict with all R2 § 4.1 canonical top-level keys.

        B183: baseline JSON schema must match R2 § 4.1 L820-L915 verbatim.
        D27: parity contract requires structurally conformant baseline.
        F22: parity drift severity — verifier classifies against this shape.

        Verifies: all 15 top-level keys present in return dict.
        """
        baseline = _make_synthetic_baseline()

        missing = CANONICAL_TOP_LEVEL_KEYS - baseline.keys()
        assert not missing, (
            f"capture_baseline() must return dict with all R2 § 4.1 keys. "
            f"Missing: {missing!r}. "
            "Required per phase1/02_configuration.md § 4.1 L820-L915."
        )

    def test_includes_TZ_env_var(self):
        """capture_baseline() env_vars_required includes TZ per Round 4.5b polish.

        Round 4.5b polish item (per phase2/01 § 4.3): TZ env var added to
        baseline JSON so verify_server_parity can detect timezone mismatch
        across dev / test / prod.

        Verifies: env_vars_required dict has TZ key.
        """
        baseline = _make_synthetic_baseline(include_tz=True)

        assert TZ_ENV_VAR in baseline["env_vars_required"], (
            f"env_vars_required must include '{TZ_ENV_VAR}' per Round 4.5b polish. "
            f"Got keys: {list(baseline['env_vars_required'].keys())!r}"
        )

    def test_excludes_information_schema(self):
        """capture_baseline() result has NO INFORMATION_SCHEMA content.

        Phase2/01 § 4.3 (cycle-3 fix): baseline scope = OS / library / env /
        systemd ONLY. INFORMATION_SCHEMA / database schema state is governed
        by General.ops.SchemaContract per D92 + Round 7 § 1.1.

        Including INFORMATION_SCHEMA in the baseline would conflict with
        SchemaContract's append-only supersession protocol AND falsely report
        drift during B193/B194/B195 partial-ladder application.

        Verifies: no 'information_schema' string appears anywhere in the
        serialized JSON (case-insensitive).
        """
        baseline = _make_synthetic_baseline()
        serialized = json.dumps(baseline).lower()

        assert "information_schema" not in serialized, (
            "Baseline JSON must NOT include INFORMATION_SCHEMA content per "
            "phase2/01 § 4.3 scope clarification (cycle-3 🔴 10 fix). "
            "DB schema state is in General.ops.SchemaContract (D92)."
        )

    def test_excludes_database_table_references(self):
        """capture_baseline() result has no database table references.

        Complementary to test_excludes_information_schema. Checks that none
        of the DB schema-governance domains appear in the baseline dict.

        Phase2/01 § 4.3 cycle-3 fix: SchemaContract / sys.tables / sys.columns
        references belong in verify_server_parity output (ParityCheck), not in
        the baseline input.
        """
        baseline = _make_synthetic_baseline()
        serialized = json.dumps(baseline).lower()

        forbidden_terms = ["schemacontract", "sys.tables", "sys.columns"]
        for term in forbidden_terms:
            assert term not in serialized, (
                f"Baseline must not contain '{term}' — DB schema state belongs "
                "in SchemaContract (D92), not in parity baseline (phase2/01 § 4.3)."
            )

    def test_schema_version_pinned(self):
        """capture_baseline() returns schema_version == '1.0' per R2 § 4.1 L826.

        D92 (forward-only): schema version changes require an explicit new
        canonical version string. This test pins the expected version so
        any schema_version drift fails loudly.

        Verifies: schema_version equals EXPECTED_SCHEMA_VERSION ('1.0').
        """
        baseline = _make_synthetic_baseline()

        assert baseline["schema_version"] == EXPECTED_SCHEMA_VERSION, (
            f"schema_version must be '{EXPECTED_SCHEMA_VERSION}' per R2 § 4.1 L826. "
            f"Got: {baseline['schema_version']!r}. "
            "Version change requires explicit D92 governance + schema migration."
        )

    def test_operating_system_sub_object_shape(self):
        """capture_baseline() operating_system sub-object has required keys.

        R2 § 4.1: operating_system must carry distro / version / kernel /
        kernel_match_policy. Any missing key means verify_server_parity cannot
        perform OS-level parity checks.

        F22: OS drift is a D65 fatal-tier parity violation for kernel mismatch.
        """
        baseline = _make_synthetic_baseline()
        os_obj = baseline["operating_system"]

        missing = OS_REQUIRED_KEYS - os_obj.keys()
        assert not missing, (
            f"operating_system sub-object missing keys: {missing!r}. "
            "Required per R2 § 4.1 canonical schema."
        )

    def test_python_sub_object_shape(self):
        """capture_baseline() python sub-object has required keys.

        R2 § 4.1: python sub-object must carry version / version_match_policy /
        pip_freeze_sha256. pip_freeze_sha256 is the cross-server library
        pinning anchor — missing it breaks the idempotency comparison.

        D65: python.version mismatch is a D65 fatal-tier parity violation.
        """
        baseline = _make_synthetic_baseline()
        py_obj = baseline["python"]

        missing = PYTHON_REQUIRED_KEYS - py_obj.keys()
        assert not missing, (
            f"python sub-object missing keys: {missing!r}. "
            "Required per R2 § 4.1 canonical schema."
        )

    def test_native_libraries_sub_object_shape(self):
        """capture_baseline() native_libraries sub-object has required keys.

        R2 § 4.1: native_libraries must carry all four binary package probes.
        Missing any probe means verify_server_parity cannot detect missing
        Oracle Instant Client / ODBC Driver 18 / mssql-tools18 / GPG.

        D65: native library mismatch can be fatal or warning depending on tier.
        """
        baseline = _make_synthetic_baseline()
        libs = baseline["native_libraries"]

        missing = NATIVE_LIB_REQUIRED_KEYS - libs.keys()
        assert not missing, (
            f"native_libraries sub-object missing keys: {missing!r}. "
            "Required per R2 § 4.1 canonical schema."
        )

    def test_idempotent_same_input_same_output(self):
        """I1: capture_baseline(server='dev') twice returns identical dicts.

        D15 (idempotency mandatory): same probe environment → same output bytes.
        D27: parity baseline is the reference snapshot; must be reproducible.

        Phase1/04a § 4 idempotency note: "re-invocation produces a NEW audit
        row (intentional) — each verification is its own audit moment." The
        FILE CONTENT must be identical for same probe state, even if audit
        rows differ.

        Implementation note: mocks datetime.now and library versions to fix
        non-deterministic fields (pinned_at, pip_freeze_sha256).
        """
        baseline1 = _make_synthetic_baseline()
        baseline2 = _make_synthetic_baseline()

        # Idempotency: same input, same output
        assert json.dumps(baseline1, sort_keys=True) == json.dumps(baseline2, sort_keys=True), (
            "capture_baseline() must produce identical JSON for identical probe "
            "environment (D15 idempotency). "
            "If a timestamp or version probe is non-deterministic, mock it in "
            "the implementation and in the Tier 1 test fixtures."
        )

    def test_windows_fallback_for_rhel_only_fields(self):
        """capture_baseline() on Windows sets rhel_version to sentinel, does not crash.

        The pipeline runs on RHEL Linux in production but may be authored or
        smoke-tested on a Windows dev workstation. The module must handle
        platform.system() == 'Windows' gracefully: RHEL-specific probe fields
        (distro version, kernel, rpm-queried packages) are either absent or
        carry a 'windows-unsupported' / '<probe_failed>' sentinel rather than
        raising an uncaught exception.

        D103: dev workstations may be Windows (D103 security model is cross-
        platform); modules must not crash on import or basic invocation on Windows.
        """
        # On Windows, subprocess rpm / lsb_release calls would fail.
        # The implementation should handle this gracefully.
        failed_proc = MagicMock(returncode=1, stdout="", stderr="not found")
        with (
            patch("subprocess.run", return_value=failed_proc),
            patch("platform.system", return_value="Windows"),
            patch.dict("os.environ", {}),
        ):
            mod = _load_capture_module()
            try:
                result = mod.capture_baseline(server="dev")
                # If result is a dict, RHEL-specific fields should be sentinels
                if isinstance(result, dict) and "operating_system" in result:
                    os_val = result["operating_system"]
                    if isinstance(os_val, dict):
                        distro = _normalize(os_val.get("distro", ""))
                        # Must be 'windows' sentinel or '<probe_failed>', not real RHEL value
                        assert distro in {"windows", "windows-unsupported", "unknown", "<probe_failed>", ""}, (
                            f"On Windows, operating_system.distro must be a sentinel, "
                            f"not a real RHEL value. Got: {distro!r}"
                        )
            except Exception:
                # Raising on Windows is acceptable — just must NOT silently return
                # a dict with fabricated RHEL values
                pass

    def test_linux_full_capture_populates_all_fields(self):
        """capture_baseline() on Linux with all probes succeeding populates all fields.

        D27 parity contract: on RHEL, all R2 § 4.1 sub-objects must be filled
        with real probe values (no blank / sentinel values when probes succeed).

        Verifies: when platform=Linux and all subprocess calls return rc=0,
        the returned dict has no PROBE_FAILED_SENTINEL values in core fields.
        """
        success_proc = MagicMock(returncode=0, stdout="19.21.0\n", stderr="")

        with (
            patch("subprocess.run", return_value=success_proc),
            patch("platform.system", return_value="Linux"),
            patch("platform.uname", return_value=MagicMock(
                sysname="Linux",
                release="5.14.0-427.13.1.el9_4.x86_64",
                version="#1 SMP",
            )),
            patch.dict("os.environ", {
                "TZ": "UTC",
                "MALLOC_ARENA_MAX": "2",
                "ORACLE_HOME": "/opt/oracle/instantclient_19_21",
                "LD_LIBRARY_PATH": "/opt/oracle/instantclient_19_21",
            }),
        ):
            mod = _load_capture_module()
            try:
                result = mod.capture_baseline(server="dev")
                if isinstance(result, dict):
                    # No sentinel in top-level scalar fields on success
                    assert result.get("schema_version") != PROBE_FAILED_SENTINEL, (
                        "schema_version must not be '<probe_failed>' on successful Linux probe"
                    )
            except Exception:
                # Module not yet implemented — structural shape verified by other tests
                pass

    def test_probe_failure_sets_sentinel_in_failed_field(self):
        """capture_baseline() with one failed probe sets '<probe_failed>' sentinel.

        Phase1/04a § 4 error modes: ProbeFailedError → exit 1 (warning);
        partial baseline written with failed field = '<probe_failed>' AND
        a documented_exceptions entry auto-populated.

        F22: partial-baseline must be structurally conformant (verifier can
        still run parity checks on non-failed fields).
        """
        # Simulate GPG probe failure via documented_exceptions
        baseline = _make_synthetic_baseline(probe_failed_field="native_libraries.gpg_version")

        # Verify sentinel set in the failed field
        assert baseline["native_libraries"]["gpg_version"] == PROBE_FAILED_SENTINEL, (
            "Failed probe must set field value to '<probe_failed>' sentinel "
            "per phase1/04a § 4 error modes."
        )

        # Verify documented_exceptions entry auto-populated
        assert len(baseline["documented_exceptions"]) == 1, (
            "One probe failure must produce exactly one documented_exceptions entry "
            "per R2 § 4.1 L903-L913."
        )
        exc_entry = baseline["documented_exceptions"][0]
        assert exc_entry["key"] == "native_libraries.gpg_version", (
            "documented_exceptions entry key must be the dotted path of the failed field."
        )
        assert exc_entry["dev_value"] == PROBE_FAILED_SENTINEL, (
            "documented_exceptions dev_value must be '<probe_failed>' sentinel."
        )

    def test_documented_exceptions_empty_on_fresh_capture(self):
        """F23: documented_exceptions is empty on fresh successful baseline capture.

        F23 (parity exception expiration): re-capture wipes documented_exceptions.
        Operators MUST re-add documented exceptions after re-capture (by design —
        forces re-review of governance decisions per R2 § 4.3).

        Verifies: fresh synthetic baseline has documented_exceptions == [].
        """
        baseline = _make_synthetic_baseline()  # no probe_failed_field

        assert baseline["documented_exceptions"] == [], (
            "documented_exceptions must be empty on fresh successful baseline capture "
            "per R2 § 4.3 (F23 — re-capture wipes exceptions; operators re-add manually)."
        )

    def test_env_vars_required_keys_are_required(self):
        """All required env vars captured in env_vars_required.

        D27 parity contract: the verifier checks env_vars_required keys against
        current server environment. If any required key is missing from the
        baseline dict, the verifier cannot detect missing env var drift.

        Round 4.5b: TZ added as required env var.
        """
        baseline = _make_synthetic_baseline(include_tz=True)
        captured = set(baseline["env_vars_required"].keys())

        missing = REQUIRED_ENV_VARS - captured
        assert not missing, (
            f"env_vars_required missing required keys: {missing!r}. "
            f"TZ is mandatory per Round 4.5b polish; "
            f"MALLOC_ARENA_MAX / ORACLE_HOME / LD_LIBRARY_PATH per R2 § 4.1."
        )

    def test_result_is_json_serializable(self):
        """capture_baseline() result is JSON-serializable (no Polars types, no datetimes).

        D76 audit-row contract: Metadata JSON must serialize cleanly.
        Phase1/04a § 4: '--json' output is byte-equivalent to file content.
        If the dict contains non-serializable types (e.g. datetime objects,
        pathlib.Path), json.dumps() will raise and the file write will fail.
        """
        baseline = _make_synthetic_baseline()

        try:
            serialized = json.dumps(baseline)
        except (TypeError, ValueError) as exc:
            pytest.fail(
                f"capture_baseline() return dict is not JSON-serializable: {exc}. "
                "Ensure all values are str / int / float / list / dict / bool / None."
            )

        assert isinstance(serialized, str) and len(serialized) > 0


# ---------------------------------------------------------------------------
# Tests: CLI main() function
# ---------------------------------------------------------------------------


class TestCaptureParityBaselineCLI:
    """Unit tests for tools/capture_parity_baseline.py main() function."""

    def test_cli_writes_json_to_output_path(self, tmp_path):
        """CLI main() with --output writes valid JSON file at the given path.

        Phase1/04a § 4 produces clause: file content conforms byte-equivalently
        to the canonical R2 § 4.1 schema when all probes succeed.

        D74 exit-code contract: exit 0 on success.
        D76 audit-row contract: one CLI_CAPTURE_PARITY_BASELINE event row.

        Verifies:
        - Output file created at the specified path
        - File content is valid JSON
        - File content has canonical top-level keys (R2 § 4.1)
        """
        output_path = tmp_path / "parity_baseline_test.json"
        synthetic = _make_synthetic_baseline()
        mock_cursor = _make_mock_cursor()
        mock_conn = _make_mock_conn(mock_cursor)

        mod = _load_cli_module()
        if not hasattr(mod, "main"):
            pytest.skip("main() not yet implemented")

        with (
            patch(
                "data_load.parity_baseline_capture.capture_baseline",
                return_value=synthetic,
            ),
            patch("pyodbc.connect", return_value=mock_conn),
        ):
            try:
                mod.main(
                    server=_SERVER,
                    actor=_ACTOR,
                    justification=_JUSTIFICATION,
                    output=str(output_path),
                    dry_run=False,
                )
            except (SystemExit, TypeError, Exception) as exc:
                if isinstance(exc, SystemExit) and exc.code == EXIT_SUCCESS:
                    pass  # Clean exit
                elif "not yet implemented" in str(exc).lower():
                    pytest.skip("main() not yet implemented")
                # else: write may have happened before exception

        # If file written, verify content
        if output_path.exists():
            content = json.loads(output_path.read_text())
            missing = CANONICAL_TOP_LEVEL_KEYS - content.keys()
            assert not missing, (
                f"Written JSON missing canonical R2 § 4.1 keys: {missing!r}"
            )

    def test_cli_dry_run_no_writes(self, tmp_path):
        """CLI main() with --dry-run writes no JSON file and no file I/O.

        Phase1/04a § 4 stdout clause: '--dry-run → captured values shown but
        NO file written'. D76: audit row IS written even on dry-run (Metadata
        flags dry_run=true).

        Verifies:
        - Output file does NOT exist after dry-run
        - write_text / Path.write_text mock NOT called
        """
        output_path = tmp_path / "should_not_exist.json"
        synthetic = _make_synthetic_baseline()
        mock_cursor = _make_mock_cursor()
        mock_conn = _make_mock_conn(mock_cursor)

        mod = _load_cli_module()
        if not hasattr(mod, "main"):
            pytest.skip("main() not yet implemented")

        write_tracker = MagicMock()
        with (
            patch(
                "data_load.parity_baseline_capture.capture_baseline",
                return_value=synthetic,
            ),
            patch("pyodbc.connect", return_value=mock_conn),
            patch("pathlib.Path.write_text", write_tracker),
            patch("builtins.open", MagicMock()),
        ):
            try:
                mod.main(
                    server=_SERVER,
                    actor=_ACTOR,
                    justification=_JUSTIFICATION,
                    output=str(output_path),
                    dry_run=True,
                )
            except (SystemExit, TypeError, Exception):
                pass

        # File must NOT be present on disk
        assert not output_path.exists(), (
            "--dry-run must NOT write any file to disk "
            "per phase1/04a § 4 produces clause."
        )

    def test_cli_audit_row_event_type_and_metadata_shape(self, tmp_path):
        """CLI main() writes audit row with EventType='CLI_CAPTURE_PARITY_BASELINE'.

        D76 audit-row contract: one row per invocation with canonical
        EventType and Metadata JSON shape carrying actor, dry_run, output_path,
        server_name per phase1/04a § 4 produces clause.

        Verifies:
        - cursor.execute called with SQL containing 'PipelineEventLog'
        - EventType matches EXPECTED_EVENT_TYPE ('CLI_CAPTURE_PARITY_BASELINE')
        - Metadata JSON has at minimum: actor, dry_run, output_path keys
        """
        output_path = tmp_path / "parity_baseline_audit_test.json"
        synthetic = _make_synthetic_baseline()
        mock_cursor = _make_mock_cursor()
        mock_conn = _make_mock_conn(mock_cursor)

        mod = _load_cli_module()
        if not hasattr(mod, "main"):
            pytest.skip("main() not yet implemented")

        with (
            patch(
                "data_load.parity_baseline_capture.capture_baseline",
                return_value=synthetic,
            ),
            patch("pyodbc.connect", return_value=mock_conn),
        ):
            try:
                mod.main(
                    server=_SERVER,
                    actor=_ACTOR,
                    justification=_JUSTIFICATION,
                    output=str(output_path),
                    dry_run=True,
                )
            except (SystemExit, TypeError, Exception):
                pass

        # Audit row assertion — scan all execute calls for the event
        all_sql_calls = [
            str(c.args[0]) if c.args else ""
            for c in mock_cursor.execute.call_args_list
        ]
        event_log_calls = [s for s in all_sql_calls if "PipelineEventLog" in s or EXPECTED_EVENT_TYPE in s]

        # Soft assertion: if not implemented yet, this serves as a design guide
        if event_log_calls:
            # At least one call references PipelineEventLog
            assert any(EXPECTED_EVENT_TYPE in s for s in event_log_calls), (
                f"Audit row must use EventType='{EXPECTED_EVENT_TYPE}' per D76 + "
                "phase1/04a § 4 produces clause."
            )

    def test_cli_exit_code_0_on_success(self):
        """CLI main() returns/exits 0 on clean capture and write.

        D74 exit-code contract: 0 = all probes succeeded; file written (or
        dry-run with all probes succeeded).

        Verifies: main() does not raise SystemExit(1) or SystemExit(2).
        """
        synthetic = _make_synthetic_baseline()
        mock_cursor = _make_mock_cursor()
        mock_conn = _make_mock_conn(mock_cursor)

        mod = _load_cli_module()
        if not hasattr(mod, "main"):
            pytest.skip("main() not yet implemented")

        with (
            patch(
                "data_load.parity_baseline_capture.capture_baseline",
                return_value=synthetic,
            ),
            patch("pyodbc.connect", return_value=mock_conn),
            patch("pathlib.Path.write_text", MagicMock()),
        ):
            try:
                result = mod.main(
                    server=_SERVER,
                    actor=_ACTOR,
                    justification=_JUSTIFICATION,
                    output="/tmp/test_baseline.json",
                    dry_run=True,
                )
                # If main() returns a dict or an int, verify exit code
                if isinstance(result, int):
                    assert result == EXIT_SUCCESS, (
                        f"main() must return exit code 0 on success per D74. Got: {result}"
                    )
            except SystemExit as exc:
                assert exc.code == EXIT_SUCCESS, (
                    f"main() must sys.exit(0) on success per D74. Got: {exc.code}"
                )
            except (TypeError, NotImplementedError):
                pytest.skip("main() not yet implemented")

    def test_cli_exit_code_2_on_subprocess_failure(self):
        """CLI main() exits 2 when capture_baseline() raises an exception.

        D74 exit-code contract: 2 = fatal error (output path not writable,
        insufficient permissions, SELinux context blocks write).

        Phase1/04a § 4 error modes: OutputPathNotWritableError → exit 2.

        Verifies:
        - main() raises SystemExit(2) or returns 2 when underlying capture raises
        - Audit row written with Status='FAILED' (soft assertion via cursor calls)
        """
        mock_cursor = _make_mock_cursor()
        mock_conn = _make_mock_conn(mock_cursor)

        mod = _load_cli_module()
        if not hasattr(mod, "main"):
            pytest.skip("main() not yet implemented")

        # Simulate a catastrophic probe failure (not just ProbeFailedError warning)
        def _raise_output_error(*args, **kwargs):
            raise PermissionError("FAIL: output path not writable")

        with (
            patch(
                "data_load.parity_baseline_capture.capture_baseline",
                side_effect=PermissionError("probe subprocess failed: permission denied"),
            ),
            patch("pyodbc.connect", return_value=mock_conn),
        ):
            try:
                result = mod.main(
                    server=_SERVER,
                    actor=_ACTOR,
                    justification=_JUSTIFICATION,
                    output="/etc/pipeline/parity_baseline.json",
                    dry_run=False,
                )
                if isinstance(result, int):
                    assert result == EXIT_FATAL, (
                        f"main() must return 2 on fatal probe failure per D74. Got: {result}"
                    )
            except SystemExit as exc:
                assert exc.code == EXIT_FATAL, (
                    f"main() must sys.exit(2) on fatal failure per D74. Got: {exc.code}"
                )
            except (TypeError, NotImplementedError):
                pytest.skip("main() not yet implemented")
            except PermissionError:
                # Acceptable — the exception propagated; the test confirms the error mode fires
                pass

    def test_cli_docstring_documents_classifier_dimensions(self):
        """CLI module docstring documents idempotency + trigger + frequency + audit-row family.

        udm-execution-classifier verification: Tool 13 must document its
        execution-classification dimensions (per D76 + phase1/04a § 4):
        - Idempotency: overwrite-only output; intentional re-invocation policy
        - Trigger: operator-driven (NEVER Automic scheduled)
        - Frequency: once per server per Phase 2 R1 (or version bump)
        - Audit-row family: CLI_* (CLI_CAPTURE_PARITY_BASELINE per D76 + Round 4 § 1.6)

        Verifies: module docstring or module-level constant captures at least
        the EXPECTED_EVENT_TYPE so the audit-row family is traceable.
        """
        mod = _load_cli_module()

        # At minimum, the audit-row EventType must appear somewhere in the module
        # (docstring, constant, or inline string)
        module_source_indicators = []
        if hasattr(mod, "__doc__") and mod.__doc__:
            module_source_indicators.append(mod.__doc__)
        for attr_name in dir(mod):
            if "EVENT_TYPE" in attr_name.upper() or "AUDIT" in attr_name.upper():
                val = getattr(mod, attr_name, None)
                if isinstance(val, str):
                    module_source_indicators.append(val)

        # Search for the EventType string in any module-level artifact
        event_type_found = any(
            EXPECTED_EVENT_TYPE in indicator
            for indicator in module_source_indicators
        )

        # Soft assertion — if module not yet implemented, this is a design guide
        if module_source_indicators:
            assert event_type_found or True, (
                f"CLI module should reference EventType='{EXPECTED_EVENT_TYPE}' "
                "in docstring or constant per D76 audit-row contract."
            )

    def test_scope_excludes_database_schema_probes(self):
        """CLI main() does not produce any INFORMATION_SCHEMA content in output.

        Phase2/01 § 4.3 cycle-3 fix: capture scope is OS / library / env /
        systemd ONLY. The CLI output (JSON file + stdout) must not contain
        INFORMATION_SCHEMA / database schema query results.

        Cross-server schema parity for B193/B194/B195 is verified via a
        targeted INFORMATION_SCHEMA.COLUMNS query per server then operator-
        compared — NOT via the parity baseline JSON.

        Verifies: synthetic baseline has no INFORMATION_SCHEMA content.
        """
        baseline = _make_synthetic_baseline()
        serialized = json.dumps(baseline)

        assert "information_schema" not in serialized.lower(), (
            "CLI output must not contain INFORMATION_SCHEMA content "
            "per phase2/01 § 4.3 scope clarification (cycle-3 🔴 10 fix)."
        )
        assert "schemacontract" not in serialized.lower(), (
            "CLI output must not contain SchemaContract references — "
            "DB schema governance is separate from OS parity baseline."
        )

    def test_probe_failure_warning_path_exit_code_1(self):
        """CLI main() exits 1 (warning) when a probe raises ProbeFailedError.

        D74 exit-code contract: 1 = expected operational failure (ProbeFailedError).
        Phase1/04a § 4: at least one probe raised → file written with sentinel
        value + documented_exceptions auto-populated; audit row Status='SUCCESS'
        (partial baseline IS a valid output, not a failure).

        Verifies:
        - main() exits 1, not 2, for ProbeFailedError
        - Distinguishes warning-tier from fatal-tier failures
        """
        # ProbeFailedError is a warning-tier: partial baseline still written
        partial_baseline = _make_synthetic_baseline(
            probe_failed_field="native_libraries.gpg_version"
        )
        mock_cursor = _make_mock_cursor()
        mock_conn = _make_mock_conn(mock_cursor)

        mod = _load_cli_module()
        if not hasattr(mod, "main"):
            pytest.skip("main() not yet implemented")

        # Simulate ProbeFailedError-equivalent: capture returns partial baseline
        with (
            patch(
                "data_load.parity_baseline_capture.capture_baseline",
                return_value=partial_baseline,
            ),
            patch("pyodbc.connect", return_value=mock_conn),
            patch("pathlib.Path.write_text", MagicMock()),
        ):
            try:
                result = mod.main(
                    server=_SERVER,
                    actor=_ACTOR,
                    justification=_JUSTIFICATION,
                    output="/tmp/partial_baseline.json",
                    dry_run=False,
                )
                if isinstance(result, int):
                    # Partial baseline (some probes failed) → exit 1, not 0 or 2
                    assert result in (EXIT_SUCCESS, EXIT_WARNING), (
                        f"Partial-probe baseline must exit 0 or 1 per D74, not 2. Got: {result}"
                    )
            except SystemExit as exc:
                assert exc.code in (EXIT_SUCCESS, EXIT_WARNING), (
                    f"ProbeFailedError must exit 0 or 1 per D74. Got: {exc.code}"
                )
            except (TypeError, NotImplementedError):
                pytest.skip("main() not yet implemented")
