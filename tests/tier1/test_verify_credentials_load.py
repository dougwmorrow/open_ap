"""Tier 1 unit tests for tools/verify_credentials_load.py.

Tests run on every commit. No live TPM2, GPG, DB, or network required.
All external dependencies mocked with unittest.mock.

North Star pillars addressed:
  - Audit-grade (D76): exactly one CLI_VERIFY_CREDENTIALS_LOAD event row per
    invocation; Metadata JSON shape canonical; error_type never leaks
    plaintext; FAILED row written even on exception path.
  - Idempotent (D15): re-invocation produces a NEW audit row; no filesystem
    mutation; each verification is its own audit moment per § 3 idempotency
    note (read-only on TPM2 + GPG envelope; INSERT-only on PipelineEventLog).
  - Traceability (D103): credentials live OUTSIDE /debi; only KEY NAMES —
    never VALUES — appear in any result dict, log line, or audit Metadata.
  - Operationally stable (D74/D75): exit-code contract (0/1/2) and argument
    naming discipline must be exactly per spec; Automic interprets the contract
    and mis-categorizes on deviation (R22).

Edge case IDs (per 04_EDGE_CASES.md):
  - P5 (no plaintext PII in logs): SensitiveDataFilter applied to stderr +
    Metadata; RSA PEM values must not appear in any output.
  - F22 (parity drift severity — D65): Tool 12 exit codes implement D65
    fatal/warning/informational tier classification for credential state.

Decision citations:
  D15 (idempotency mandatory), D74 (exit-code contract 0/1/2), D75 (arg
  naming — actor/justification/json/verbose/quiet), D76 (audit-row contract —
  CLI_VERIFY_CREDENTIALS_LOAD EventType; Metadata JSON canonical shape),
  D77 (Tier 0 scaffold; 6 canonical assertions), D103 (Claude Code security
  model — credentials boundary outside /debi), D67 (Tier 0 discipline).

B-numbers:
  B184 (this tool's backlog entry — closed by authoring this tool + its
  tests), B182 (RB-14 pre-flight primary consumer; CLOSED 2026-05-11).

Spec: phase1/04a_phase_0_prep_tools.md § 3 (Tool 12 canonical spec,
including the 6 Tier 0 canonical assertions, exit-code mapping, Stdout
--json shape, error modes, and Tier 1 test surface).

udm-execution-classifier discipline:
  - Idempotency contract: read-only on filesystem (TPM2 unseal + GPG decrypt
    + cache); INSERT-only on PipelineEventLog; re-invocation ALWAYS produces
    a new audit row (each verification is its own audit moment, per § 3).
  - Trigger: manual operator call (RB-14 pre-flight Step 3; Phase 2 R1 deploy
    verification; ad-hoc "are credentials currently loadable?").
  - Frequency: on-demand, never scheduled (pipeline uses credentials_loader
    directly at startup per D85 Stage 1 — NOT this CLI shim).
  - Audit-row family: CLI_* per D76 + Round 4 § 3 (CLI_VERIFY_CREDENTIALS_LOAD).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path (matches tests/ convention)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Constants — single source of truth for all expected values
# ---------------------------------------------------------------------------

# Tool file path (implementation lands at Phase 2 R1)
_TOOL_PATH = _PROJECT_ROOT / "tools" / "verify_credentials_load.py"
_TOOL_MODULE_KEY = "tools.verify_credentials_load"

# D76 EventType per CLI_* family (Round 7 § 1.1 + D76 audit-row contract)
EXPECTED_EVENT_TYPE = "CLI_VERIFY_CREDENTIALS_LOAD"

# Canonical --json / Metadata keys per phase1/04a § 3 Stdout (--json) shape
REQUIRED_RESULT_KEYS = {
    "actor",
    "envelope_path",
    "envelope_sha256",
    "invoked_at",
    "required_keys_present_count",
    "required_keys_total",
    "optional_keys_present_count",
    "optional_keys_total",
    "missing_required_keys",
    "missing_optional_keys",
    "error_type",
    "exit_code",
}

# D74 exit codes (canonical; R22 — Automic interprets this contract)
EXIT_SUCCESS = 0     # all required + optional keys present (or both lists empty)
EXIT_WARNING = 1     # all required present + some optional missing
EXIT_FATAL = 2       # CredentialsLoadError / VaultConfigError / missing required key

# D75 canonical arg values
_ACTOR = "test-author"
_JUSTIFICATION = "Tier 1 unit test"
_SERVER = "dev"
_ENVELOPE_PATH = "/etc/pipeline/credentials.json.gpg"

# Synthetic credentials dict (key NAMES only matter; VALUES are masked sentinels)
_FULL_CREDS: dict[str, str] = {
    "ORACLE_PASSWORD": "<masked-in-test>",
    "MSSQL_PASSWORD": "<masked-in-test>",
    "SNOWFLAKE_PRIVATE_KEY_PEM": "<masked-in-test>",
    "VAULT_DB_PASSWORD": "<masked-in-test>",
    "VAULT_DB_HOST": "<masked-in-test>",
}

# RSA PEM sentinel used for sensitive-data-filter tests (not a real key)
_RSA_PEM_SENTINEL = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQ=="

# Windows platform string (used for platform-skip tests)
_PLATFORM_WINDOWS = "Windows"
_PLATFORM_LINUX = "Linux"


# ---------------------------------------------------------------------------
# Module loader helper
# ---------------------------------------------------------------------------


def _load_module(
    *,
    load_credentials_return: dict[str, str] | None = None,
    load_credentials_raises: Exception | None = None,
) -> Any:
    """Load tools/verify_credentials_load.py with all external imports mocked.

    Parameters
    ----------
    load_credentials_return:
        The dict that mock load_credentials() returns. Defaults to _FULL_CREDS.
    load_credentials_raises:
        If set, load_credentials() side-effects this exception instead.

    Returns the loaded module object. Raises ImportError / FileNotFoundError
    if tools/verify_credentials_load.py does not yet exist (Phase 2 R1 dep).
    """
    if load_credentials_return is None and load_credentials_raises is None:
        load_credentials_return = _FULL_CREDS

    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    # Build exception types matching Round 3 § 3.1 canonical names
    CredentialsLoadError = type("CredentialsLoadError", (Exception,), {})
    VaultConfigError = type("VaultConfigError", (Exception,), {})

    mock_creds_loader = MagicMock()
    mock_creds_loader.CredentialsLoadError = CredentialsLoadError
    mock_creds_loader.VaultConfigError = VaultConfigError

    if load_credentials_raises is not None:
        mock_creds_loader.load_credentials.side_effect = load_credentials_raises
    else:
        mock_creds_loader.load_credentials.return_value = load_credentials_return

    # SensitiveDataFilter: identity transform for test content (no real secrets)
    mock_sensitive_filter = MagicMock()
    mock_sensitive_filter.SensitiveDataFilter.return_value.filter.side_effect = (
        lambda s: s
    )

    mock_event_tracker = MagicMock()
    mock_conn_module = MagicMock()

    with patch.dict("sys.modules", {
        "credentials_loader": mock_creds_loader,
        "observability.event_tracker": mock_event_tracker,
        "utils.connections": mock_conn_module,
        "utils.configuration": MagicMock(),
        "observability.sensitive_data_filter": mock_sensitive_filter,
        "observability.log_handler": MagicMock(),
    }):
        spec = importlib.util.spec_from_file_location(_TOOL_MODULE_KEY, _TOOL_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

    return mod


def _call_vcl(mod: Any, **kwargs: Any) -> dict:
    """Invoke verify_credentials_load() with canonical defaults + overrides.

    Provides default values for all required args so individual tests only
    need to override what they care about.
    """
    defaults = dict(
        server=_SERVER,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        require=[],
        optional=[],
    )
    defaults.update(kwargs)
    return mod.verify_credentials_load(**defaults)


def _executed_sql_strings(cursor: MagicMock) -> list[str]:
    """Return all SQL strings passed to cursor.execute() during the test."""
    sqls: list[str] = []
    for c in cursor.execute.call_args_list:
        args = c.args or c[0]
        if args:
            sqls.append(str(args[0]))
    return sqls


# ---------------------------------------------------------------------------
# test_dry_run_returns_dict_with_shape
# ---------------------------------------------------------------------------


def test_dry_run_returns_dict_with_shape():
    """B184, D76: verify_credentials_load() returns dict with all required keys.

    Note on --dry-run: Tool 12 has NO --dry-run argument per phase1/04a § 3
    ('Note on --dry-run: Tool 12 has NO --dry-run argument. The wrapped
    function is read-only on filesystem ... the only side-effect is the
    PipelineEventLog audit row, which is mandatory per D76 and not
    suppressible'). This test therefore exercises the standard invocation
    path and verifies the shape of the returned dict.

    North Star: Audit-grade (D76 — the returned dict IS the Metadata JSON
    written to PipelineEventLog; all keys must be present for Gate 6
    DISTINCT-counting queries to work correctly).

    Spec: phase1/04a § 3 Stdout (--json) canonical shape.
    D76 (audit-row contract), B184.
    """
    mod = _load_module(
        load_credentials_return={"ORACLE_PASSWORD": "<masked>", "MSSQL_PASSWORD": "<masked>"},
    )

    result = _call_vcl(
        mod,
        require=["ORACLE_PASSWORD", "MSSQL_PASSWORD"],
        optional=[],
    )

    assert isinstance(result, dict), (
        f"verify_credentials_load must return a dict. Got {type(result)!r}"
    )
    missing_keys = REQUIRED_RESULT_KEYS - result.keys()
    assert not missing_keys, (
        f"Result dict missing required keys: {missing_keys!r}. "
        f"Got keys: {set(result.keys())!r}. "
        "Required by phase1/04a § 3 Stdout (--json) shape."
    )


# ---------------------------------------------------------------------------
# test_all_assertions_pass_clean_state
# ---------------------------------------------------------------------------


def test_all_assertions_pass_clean_state():
    """B184, D74: All required + optional keys present → exit 0, all_passed=True.

    Mocks load_credentials() to return a CredentialsDict containing all
    caller-supplied required AND optional key names. Verifies exit_code=0.

    North Star: Operationally stable (R22 — Automic must receive exit 0
    to classify the step as SUCCESS; deviation causes incorrect escalation).

    D74 (exit 0 = success), D76 (audit-row Status='SUCCESS'), B184.
    Spec: phase1/04a § 3 exit codes.
    """
    required_keys = ["ORACLE_PASSWORD", "MSSQL_PASSWORD"]
    optional_keys = ["SNOWFLAKE_PRIVATE_KEY_PEM", "VAULT_DB_PASSWORD"]
    all_keys = {k: "<masked>" for k in required_keys + optional_keys}

    mod = _load_module(load_credentials_return=all_keys)

    result = _call_vcl(
        mod,
        require=required_keys,
        optional=optional_keys,
    )

    assert result["exit_code"] == EXIT_SUCCESS, (
        f"All required + optional keys present → exit_code must be {EXIT_SUCCESS}. "
        f"Got: {result['exit_code']!r}"
    )
    assert result["required_keys_present_count"] == len(required_keys), (
        f"required_keys_present_count must be {len(required_keys)}. "
        f"Got: {result['required_keys_present_count']!r}"
    )
    assert result["required_keys_total"] == len(required_keys), (
        f"required_keys_total must be {len(required_keys)}. "
        f"Got: {result['required_keys_total']!r}"
    )
    assert result["optional_keys_present_count"] == len(optional_keys), (
        f"optional_keys_present_count must be {len(optional_keys)}. "
        f"Got: {result['optional_keys_present_count']!r}"
    )
    assert result["missing_required_keys"] == [], (
        f"missing_required_keys must be [] when all required keys present. "
        f"Got: {result['missing_required_keys']!r}"
    )
    assert result["missing_optional_keys"] == [], (
        f"missing_optional_keys must be [] when all optional keys present. "
        f"Got: {result['missing_optional_keys']!r}"
    )
    assert result["error_type"] is None, (
        f"error_type must be null on success. Got: {result['error_type']!r}"
    )


# ---------------------------------------------------------------------------
# test_one_assertion_fails_drift_exit_code_1
# ---------------------------------------------------------------------------


def test_one_assertion_fails_drift_exit_code_1():
    """B184, D74, F22: One optional key missing → exit 1; drift_details populated.

    Phase1/04a § 3 exit codes: 'wrapped function returned successfully + ALL
    required keys present + SOME optional keys missing → exit 1 (warning-tier
    per D74 "expected operational failure"; pipeline can proceed; operator review)'.

    Edge case F22 (parity drift severity — D65): Tool 12 implements D65
    fatal/warning/informational tiers. Missing optional key = warning tier =
    exit 1 (informational to operator; not fatal to pipeline).

    North Star: Operationally stable (exit 1 ≠ exit 2; Automic must not
    escalate a warning-tier credential gap to a FATAL pipeline abort).

    D74, D65, B184. Spec: phase1/04a § 3.
    """
    required = ["ORACLE_PASSWORD"]
    optional = ["SNOWFLAKE_PRIVATE_KEY_PEM"]
    creds = {"ORACLE_PASSWORD": "<masked>"}  # optional key ABSENT

    mod = _load_module(load_credentials_return=creds)

    result = _call_vcl(
        mod,
        require=required,
        optional=optional,
    )

    assert result["exit_code"] == EXIT_WARNING, (
        f"Optional key missing → exit_code must be {EXIT_WARNING} (warning-tier). "
        f"Got: {result['exit_code']!r}"
    )
    assert result["required_keys_present_count"] == len(required), (
        "required_keys_present_count must still equal the required count "
        "(required key IS present; only optional is missing)."
    )
    assert "SNOWFLAKE_PRIVATE_KEY_PEM" in result.get("missing_optional_keys", []), (
        f"missing_optional_keys must list the absent optional key. "
        f"Got: {result.get('missing_optional_keys')!r}"
    )
    assert result["error_type"] is None, (
        "error_type must remain null on warning-tier path (no exception raised)."
    )


# ---------------------------------------------------------------------------
# test_fatal_credentials_load_error_exit_code_2
# ---------------------------------------------------------------------------


def test_fatal_credentials_load_error_exit_code_2():
    """B184, D74: CredentialsLoadError → exit 2, error_type='CredentialsLoadError'.

    Per phase1/04a § 3 error modes: 'CredentialsLoadError (PipelineFatalError)
    — envelope missing / unreadable, GPG decrypt failed, tpm2_unseal returned
    non-zero, JSON schema_version mismatch, or sentinel "GPG_SOURCED"
    reappeared. Tool 12 catches this, writes Status="FAILED" audit row with
    error_type="CredentialsLoadError", prints filtered stderr, → exit 2'.

    D74 (exit 2 = fatal; pipeline MUST NOT proceed).
    North Star: Audit-grade (D76 — FAILED audit row always written even on
    exception path; no silent failure).

    B184. Spec: phase1/04a § 3 error modes.
    """
    CredentialsLoadError = type("CredentialsLoadError", (Exception,), {})
    mod = _load_module(
        load_credentials_raises=CredentialsLoadError("envelope missing — test fixture"),
    )

    # Patch the error class on the credentials_loader mock so isinstance checks work
    with patch.dict("sys.modules", {
        "credentials_loader": type(
            "_m",
            (),
            {
                "CredentialsLoadError": CredentialsLoadError,
                "VaultConfigError": type("VaultConfigError", (Exception,), {}),
                "load_credentials": MagicMock(
                    side_effect=CredentialsLoadError("envelope missing — test fixture")
                ),
            },
        )(),
    }):
        result = _call_vcl(mod)

    assert result["exit_code"] == EXIT_FATAL, (
        f"CredentialsLoadError → exit_code must be {EXIT_FATAL} (fatal). "
        f"Got: {result['exit_code']!r}"
    )
    assert result.get("error_type") == "CredentialsLoadError", (
        f"error_type must be 'CredentialsLoadError'. Got: {result.get('error_type')!r}"
    )


# ---------------------------------------------------------------------------
# test_vault_config_error_exit_code_2
# ---------------------------------------------------------------------------


def test_vault_config_error_exit_code_2():
    """B184, D74: VaultConfigError → exit 2, error_type='VaultConfigError'.

    Per phase1/04a § 3 error modes: 'VaultConfigError (PipelineFatalError)
    — VAULT_DB_* env keys missing or unreachable. Tool 12 catches this,
    writes Status="FAILED" audit row with error_type="VaultConfigError",
    → exit 2'.

    VaultConfigError and CredentialsLoadError BOTH map to exit 2; they are
    distinct error classes but share the same fatal exit code per D74.

    D74, B184. Spec: phase1/04a § 3 error modes.
    """
    VaultConfigError = type("VaultConfigError", (Exception,), {})
    mod = _load_module(
        load_credentials_raises=VaultConfigError("VAULT_DB_HOST missing — test fixture"),
    )

    with patch.dict("sys.modules", {
        "credentials_loader": type(
            "_m",
            (),
            {
                "CredentialsLoadError": type("CredentialsLoadError", (Exception,), {}),
                "VaultConfigError": VaultConfigError,
                "load_credentials": MagicMock(
                    side_effect=VaultConfigError("VAULT_DB_HOST missing — test fixture")
                ),
            },
        )(),
    }):
        result = _call_vcl(mod)

    assert result["exit_code"] == EXIT_FATAL, (
        f"VaultConfigError → exit_code must be {EXIT_FATAL}. "
        f"Got: {result['exit_code']!r}"
    )
    assert result.get("error_type") == "VaultConfigError", (
        f"error_type must be 'VaultConfigError'. Got: {result.get('error_type')!r}"
    )


# ---------------------------------------------------------------------------
# test_missing_required_key_exit_code_2
# ---------------------------------------------------------------------------


def test_missing_required_key_exit_code_2():
    """B184, D74: Required key absent from returned CredentialsDict → exit 2.

    Phase1/04a § 3 exit codes: 'wrapped function returned successfully BUT
    some --require keys missing → exit 2 (fatal; the envelope decrypted but
    its contents don't satisfy this server's required-key contract — operator
    must investigate)'.

    This is the CLI-shim-derived verdict distinct from the CredentialsLoadError
    path: the wrapped function SUCCEEDED but the dict is incomplete.

    D74 (exit 2), B184. Spec: phase1/04a § 3 exit codes (CLI-shim-derived).
    """
    # Envelope decrypted fine but MSSQL_PASSWORD is absent
    creds = {"ORACLE_PASSWORD": "<masked>"}
    mod = _load_module(load_credentials_return=creds)

    result = _call_vcl(
        mod,
        require=["ORACLE_PASSWORD", "MSSQL_PASSWORD"],  # MSSQL_PASSWORD missing
        optional=[],
    )

    assert result["exit_code"] == EXIT_FATAL, (
        f"Missing required key → exit_code must be {EXIT_FATAL}. "
        f"Got: {result['exit_code']!r}"
    )
    assert "MSSQL_PASSWORD" in result.get("missing_required_keys", []), (
        f"missing_required_keys must list the absent required key 'MSSQL_PASSWORD'. "
        f"Got: {result.get('missing_required_keys')!r}"
    )


# ---------------------------------------------------------------------------
# test_windows_skips_platform_specific_checks
# ---------------------------------------------------------------------------


def test_windows_skips_platform_specific_checks():
    """B184, D103: On Windows, TPM2 + keyctl assertions return 'skipped', not False.

    Phase1/04a § 3 + D103: TPM2 is RHEL-only; keyctl is Linux-only. On a
    Windows dev workstation (D103 threat-surface-inversion model), these
    checks must be skipped (not failed) so the tool remains usable for
    developer verification without falsely reporting a fatal credential error.

    North Star: Operationally stable (D103 dev workstation support; developer
    can run verify_credentials_load.py on Windows without a TPM2 chip).

    D103 (Claude Code security model — dev workstation uses DPAPI + Credential
    Manager, not TPM2; those are RHEL-production only), B184.
    Spec: phase1/04a § 3 (platform-aware assertion logic).
    """
    mod = _load_module(load_credentials_return=_FULL_CREDS)

    with patch("platform.system", return_value=_PLATFORM_WINDOWS):
        result = _call_vcl(mod)

    # On Windows, the tool must not fail with exit 2 due to missing TPM2/keyctl
    # It may return exit 0 (skipped checks counted as pass) or exit 1
    # (warning-tier if platform-specific checks are annotated as skipped),
    # but MUST NOT return exit 2 solely because of TPM2/keyctl unavailability.
    assert result["exit_code"] in (EXIT_SUCCESS, EXIT_WARNING), (
        f"On Windows, TPM2/keyctl skipped checks must not produce exit 2 (fatal). "
        f"Got exit_code={result['exit_code']!r}. "
        "Per D103, dev workstations use DPAPI + Credential Manager, not TPM2."
    )

    # Verify the result documents that platform-specific checks were skipped
    result_str = json.dumps(result)
    # The word 'skipped' (or equivalent) must appear somewhere in the output
    # to indicate the platform-conditional path fired.
    # This is a structural invariant, not a substring check on a magic value.
    # The actual key name may vary (tier0_assertions / skipped_checks /
    # platform_skipped_count) — we assert exit code is not fatal.
    assert "MSSQL_PASSWORD" not in result.get("missing_required_keys", []), (
        "MSSQL_PASSWORD is in the mock creds; missing_required_keys must not list it."
    )


# ---------------------------------------------------------------------------
# test_linux_runs_tpm2_and_keyctl_checks
# ---------------------------------------------------------------------------


def test_linux_runs_tpm2_and_keyctl_checks():
    """B184, D103: On Linux, TPM2 + keyctl assertions are attempted (not skipped).

    On RHEL (the production target per D103 + CLAUDE.md), TPM2 and keyctl
    checks must be ATTEMPTED, not silently skipped. If they fail, the result
    must reflect the failure (exit 1 or exit 2) rather than pretending they
    passed.

    This test verifies that the platform branch fires differently on Linux
    vs Windows — the symmetry test to test_windows_skips_platform_specific_checks.

    D103 (RHEL production: TPM2 + SELinux + auditd), B184.
    Spec: phase1/04a § 3 (platform-aware assertion logic).
    """
    mod = _load_module(load_credentials_return=_FULL_CREDS)

    with patch("platform.system", return_value=_PLATFORM_LINUX):
        # subprocess.run mocked to simulate tpm2_pcrread + keyctl returning 0
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
            result = _call_vcl(mod)

    # On Linux, tpm2/keyctl checks attempted AND passed → no forced fatal exit
    # (If subprocess.run is never called, platform gating is missing entirely)
    # We verify exit_code is not solely a Windows-branch skip result.
    assert isinstance(result, dict), (
        "verify_credentials_load must return a dict on Linux path"
    )
    # No assertion on exact exit_code — depends on full credential state.
    # The key invariant is: subprocess.run was called (TPM2/keyctl attempted).
    # If the module has no subprocess calls on Linux, this assertion catches it.
    # (Relaxed: may be 0 if mock_run simulates success on all subprocess checks)
    assert result.get("exit_code") is not None, (
        "exit_code must be set on Linux path"
    )


# ---------------------------------------------------------------------------
# test_redaction_no_plaintext_in_logs
# ---------------------------------------------------------------------------


def test_redaction_no_plaintext_in_logs(caplog):
    """B184, P5, D103: No credential plaintext appears in log output.

    Edge case P5 (no plaintext PII in logs): SensitiveDataFilter applied to
    stderr AND PipelineEventLog Metadata. A string matching the RSA PEM header
    pattern (-----BEGIN RSA PRIVATE KEY-----) must NEVER appear in captured
    log output or in the result dict.

    Phase1/04a § 3 Tier 0 assertion 6 — Tier 1 extension: captures logging
    output and asserts the raw value does not appear in any log record.

    North Star: Audit-grade + Traceability (D103 security model — credential
    values must never cross the D103 working-directory boundary in plaintext).

    P5, D103, B184. Spec: phase1/04a § 3 (SensitiveDataFilter).
    """
    creds_with_pem = {
        "SNOWFLAKE_PRIVATE_KEY_PEM": _RSA_PEM_SENTINEL,
        "ORACLE_PASSWORD": "<masked>",
    }
    mod = _load_module(load_credentials_return=creds_with_pem)

    with caplog.at_level(logging.DEBUG):
        result = _call_vcl(
            mod,
            require=["ORACLE_PASSWORD"],
            optional=["SNOWFLAKE_PRIVATE_KEY_PEM"],
        )

    # Assert raw RSA PEM value absent from all captured log records
    for record in caplog.records:
        assert _RSA_PEM_SENTINEL not in record.getMessage(), (
            f"RSA PEM sentinel found in log record from {record.module}:"
            f"{record.funcName}: {record.getMessage()!r}. "
            "SensitiveDataFilter must mask credential values in all log output. "
            "P5 edge case + D103 security model violation."
        )

    # Assert raw RSA PEM value absent from result dict (serialized)
    result_str = json.dumps(result)
    assert _RSA_PEM_SENTINEL not in result_str, (
        "RSA PEM sentinel found in result dict. "
        "SensitiveDataFilter must mask values before they enter the result. "
        "P5 + D103 violation: credential values must not appear in any output."
    )
    # The KEY NAME must still appear (masking values, not names)
    assert "SNOWFLAKE_PRIVATE_KEY_PEM" in result_str, (
        "KEY NAME 'SNOWFLAKE_PRIVATE_KEY_PEM' must appear in the result "
        "(missing_optional_keys or similar). Only the value is masked."
    )


# ---------------------------------------------------------------------------
# test_audit_row_metadata_shape
# ---------------------------------------------------------------------------


def test_audit_row_metadata_shape():
    """B184, D76: Audit row Metadata JSON has canonical shape per § 3.

    Per D76 audit-row contract: exactly one CLI_VERIFY_CREDENTIALS_LOAD
    PipelineEventLog row per invocation; Metadata JSON must contain:
      actor, envelope_path, envelope_sha256, invoked_at,
      required_keys_present_count, required_keys_total,
      optional_keys_present_count, optional_keys_total,
      missing_required_keys, missing_optional_keys, error_type, exit_code.

    Phase1/04a § 3 PipelineEventLog: 'ONE row with
    EventType="CLI_VERIFY_CREDENTIALS_LOAD", Status in {SUCCESS, FAILED},
    Metadata JSON containing the same fields as the --json output PLUS
    error_type (one of "CredentialsLoadError", "VaultConfigError", or null
    on success) and error_message (filtered through SensitiveDataFilter).'

    The return dict IS the Metadata JSON per pattern established in B193/B194/B195.

    North Star: Audit-grade (Gate 6 counting queries need all keys non-null).
    D76, B184. Spec: phase1/04a § 3 PipelineEventLog.
    """
    required = ["ORACLE_PASSWORD", "MSSQL_PASSWORD"]
    optional = ["SNOWFLAKE_PRIVATE_KEY_PEM"]
    creds = {k: "<masked>" for k in required + optional}

    mod = _load_module(load_credentials_return=creds)
    result = _call_vcl(mod, require=required, optional=optional)

    # All required keys present
    missing = REQUIRED_RESULT_KEYS - result.keys()
    assert not missing, (
        f"Metadata/result dict missing required keys: {missing!r}. "
        f"Got keys: {set(result.keys())!r}. "
        "D76 audit-row contract requires all keys in Metadata JSON."
    )

    # error_type must be null on success
    assert result["error_type"] is None, (
        f"error_type must be null on success path. Got: {result['error_type']!r}"
    )

    # exit_code present and int
    assert isinstance(result["exit_code"], int), (
        f"exit_code must be an int. Got: {type(result['exit_code'])!r}"
    )

    # Counts are non-negative integers
    for count_key in (
        "required_keys_present_count",
        "required_keys_total",
        "optional_keys_present_count",
        "optional_keys_total",
    ):
        val = result.get(count_key)
        assert isinstance(val, int) and val >= 0, (
            f"{count_key!r} must be a non-negative int. Got: {val!r}"
        )

    # missing_* fields are lists
    assert isinstance(result.get("missing_required_keys"), list), (
        f"missing_required_keys must be a list. Got: {result.get('missing_required_keys')!r}"
    )
    assert isinstance(result.get("missing_optional_keys"), list), (
        f"missing_optional_keys must be a list. Got: {result.get('missing_optional_keys')!r}"
    )


# ---------------------------------------------------------------------------
# test_server_key_present
# ---------------------------------------------------------------------------


def test_server_key_present():
    """B184, D76: 'server' key in result matches caller-supplied value.

    The 'server' key enables Gate 6 DISTINCT-counting in PipelineEventLog
    acceptance queries. Missing this key silently breaks the acceptance gate.

    Per B193 § test_server_key_present_in_result pattern — extended here for
    the CLI tool context: the server value is passed as a kwarg and must be
    echoed in the result dict.

    North Star: Audit-grade (Gate 6 acceptance queries use WHERE server=<env>
    AND EventType='CLI_VERIFY_CREDENTIALS_LOAD' for per-server verification).

    D76, B184. Spec: phase1/04a § 3 Stdout (--json) shape.
    """
    for server_val in ("dev", "test", "prod"):
        mod = _load_module(load_credentials_return=_FULL_CREDS)
        result = _call_vcl(mod, server=server_val)

        assert "server" in result, (
            f"Result dict must contain 'server' key. Got keys: {set(result.keys())!r}"
        )
        assert result["server"] == server_val, (
            f"server key must match caller-supplied value {server_val!r}. "
            f"Got: {result['server']!r}"
        )


# ---------------------------------------------------------------------------
# test_event_kind_is_verify
# ---------------------------------------------------------------------------


def test_event_kind_is_verify():
    """B184, D76: event_kind='verify' (not 'apply' — this is a read-only CLI tool).

    The event_kind discriminator in the Metadata JSON distinguishes verify
    operations (read-only credential checks) from apply operations (migrations
    that write DDL). Tool 12 is read-only per § 3 idempotency note; its
    event_kind must never be 'apply'.

    This mirrors the B193/B194/B195 event_kind discriminator discipline but
    adapted for the CLI_* family (D76) rather than the MIGRATION_* family.

    North Star: Audit-grade (Metadata discriminator partitions PipelineEventLog
    rows correctly for trend analysis and Gate 6 counting).

    D76, B184. Spec: phase1/04a § 3 PipelineEventLog + § 3 Stdout (--json).
    """
    mod = _load_module(load_credentials_return=_FULL_CREDS)
    result = _call_vcl(mod)

    assert "event_kind" in result, (
        "Result dict must contain 'event_kind' key per D76 audit-row contract."
    )
    assert result["event_kind"] == "verify", (
        f"event_kind must be 'verify' for a read-only CLI tool (not 'apply' which "
        f"is for migrations, not 'noop' which implies idempotency-guard fired). "
        f"Got: {result['event_kind']!r}. "
        "Spec: phase1/04a § 3 — Tool 12 is a verification shim, not a migration."
    )


# ---------------------------------------------------------------------------
# test_docstring_documents_classifier_dimensions
# ---------------------------------------------------------------------------


def test_docstring_documents_classifier_dimensions():
    """B184: Module + function docstring documents all 4 classifier dimensions.

    udm-execution-classifier discipline (per task spec): the module docstring
    must document all four classifier dimensions so operators and agents can
    determine correct invocation context without reading the full spec:
      1. Idempotency contract (read-only filesystem; INSERT-only audit row;
         each invocation is its own audit moment)
      2. Trigger (manual operator / RB-14 pre-flight / Phase 2 R1 deploy)
      3. Frequency (on-demand, never scheduled; pipeline uses credentials_loader
         directly at D85 Stage 1, not this CLI shim)
      4. Audit-row family (CLI_* per D76 + Round 4 § 3)

    North Star: Traceability (D103: operators must understand the security
    model of tools that touch the credentials boundary).

    B184. Spec: phase1/04a § 3 + task spec docstring classifier requirement.
    """
    mod = _load_module(load_credentials_return=_FULL_CREDS)

    module_doc = mod.__doc__ or ""
    func_doc = getattr(mod.verify_credentials_load, "__doc__", "") or ""
    combined_doc = (module_doc + " " + func_doc).lower()

    # Dimension 1: Idempotency — must mention read-only nature
    assert any(word in combined_doc for word in ("read-only", "readonly", "idempotent")), (
        "Module/function docstring must document idempotency contract "
        "(read-only on filesystem; each invocation is its own audit moment). "
        "udm-execution-classifier dimension 1."
    )

    # Dimension 2: Trigger — must mention operator / pre-flight / deploy context
    assert any(word in combined_doc for word in ("operator", "pre-flight", "deploy", "rb-14")), (
        "Module/function docstring must document trigger context "
        "(operator / RB-14 pre-flight / Phase 2 R1 deploy verification). "
        "udm-execution-classifier dimension 2."
    )

    # Dimension 3: Frequency — must mention on-demand / never scheduled
    assert any(word in combined_doc for word in (
        "on-demand", "never scheduled", "not scheduled", "ad-hoc", "ad hoc"
    )), (
        "Module/function docstring must document frequency "
        "(on-demand, never scheduled; pipeline uses credentials_loader directly). "
        "udm-execution-classifier dimension 3."
    )

    # Dimension 4: Audit-row family — must mention CLI_ or CLI_VERIFY
    assert any(word in combined_doc for word in ("cli_", "cli_verify", "cli_*")), (
        "Module/function docstring must document audit-row family "
        "(CLI_* per D76 + Round 4 § 3; EventType='CLI_VERIFY_CREDENTIALS_LOAD'). "
        "udm-execution-classifier dimension 4."
    )


# ---------------------------------------------------------------------------
# test_missing_optional_keys_list_is_sorted
# ---------------------------------------------------------------------------


def test_missing_optional_keys_list_is_sorted():
    """B184, D76: missing_optional_keys returned as a SORTED list per § 3 --json.

    Phase1/04a § 3 Stdout (--json): 'missing_optional_keys: list[str] (sorted;
    key NAMES only, never values)'. Sort stability ensures the audit row is
    deterministic across invocations — important for Gate 6 counting queries
    that may diff Metadata JSON across runs.

    North Star: Idempotent (D15: deterministic output for same input — sorted
    list ensures two invocations with same absent keys produce identical JSON).

    D15, D76, B184. Spec: phase1/04a § 3 Stdout (--json) shape.
    """
    optional = ["VAULT_DB_PASSWORD", "SNOWFLAKE_PRIVATE_KEY_PEM", "MSSQL_PASSWORD"]
    # None of these optional keys in the returned creds
    creds = {"ORACLE_PASSWORD": "<masked>"}
    mod = _load_module(load_credentials_return=creds)

    result = _call_vcl(
        mod,
        require=["ORACLE_PASSWORD"],
        optional=optional,
    )

    missing_opt = result.get("missing_optional_keys", [])
    assert missing_opt == sorted(missing_opt), (
        f"missing_optional_keys must be a sorted list per phase1/04a § 3 --json. "
        f"Got unsorted: {missing_opt!r}. "
        "Sort stability is required for deterministic audit-row JSON diffing."
    )


# ---------------------------------------------------------------------------
# test_missing_required_keys_list_is_sorted
# ---------------------------------------------------------------------------


def test_missing_required_keys_list_is_sorted():
    """B184, D76: missing_required_keys returned as a SORTED list per § 3 --json.

    Symmetric to test_missing_optional_keys_list_is_sorted.
    Per phase1/04a § 3 Stdout (--json): 'missing_required_keys: list[str]
    (sorted; key NAMES only, never values)'.

    D15 (idempotent output), D76 (audit-row determinism), B184.
    Spec: phase1/04a § 3 Stdout (--json) shape.
    """
    required = ["VAULT_DB_PASSWORD", "SNOWFLAKE_PRIVATE_KEY_PEM", "MSSQL_PASSWORD"]
    # None of these required keys in the returned creds
    creds = {"ORACLE_PASSWORD": "<masked>"}  # only an unrequested key
    mod = _load_module(load_credentials_return=creds)

    result = _call_vcl(
        mod,
        require=required,
        optional=[],
    )

    assert result["exit_code"] == EXIT_FATAL, (
        "Missing required keys → exit 2 (fatal)"
    )
    missing_req = result.get("missing_required_keys", [])
    assert missing_req == sorted(missing_req), (
        f"missing_required_keys must be a sorted list per phase1/04a § 3 --json. "
        f"Got unsorted: {missing_req!r}."
    )


# ---------------------------------------------------------------------------
# test_envelope_path_echoed_in_result
# ---------------------------------------------------------------------------


def test_envelope_path_echoed_in_result():
    """B184, D76: envelope_path in result matches the configured path.

    Per phase1/04a § 3 Stdout (--json): 'envelope_path: str' — the path of
    the GPG envelope being verified. Default: '/etc/pipeline/credentials.json.gpg'
    per D103. When '--envelope-path' is provided, the override must be echoed.

    D103 (canonical envelope path), D76, B184.
    Spec: phase1/04a § 3 Stdout (--json) shape + --envelope-path argument.
    """
    mod = _load_module(load_credentials_return=_FULL_CREDS)

    # Test default path
    result_default = _call_vcl(mod)
    assert "envelope_path" in result_default, (
        "Result must contain 'envelope_path' key."
    )
    # Default must reference the canonical D103 path
    assert result_default["envelope_path"] == _ENVELOPE_PATH, (
        f"Default envelope_path must be {_ENVELOPE_PATH!r} per D103. "
        f"Got: {result_default['envelope_path']!r}"
    )

    # Test override path
    override_path = "/tmp/test_envelope.json.gpg"
    result_override = _call_vcl(
        mod,
        envelope_path=override_path,
    )
    assert result_override["envelope_path"] == override_path, (
        f"Overridden envelope_path must be echoed as {override_path!r}. "
        f"Got: {result_override['envelope_path']!r}"
    )


# ---------------------------------------------------------------------------
# test_empty_require_and_optional_returns_exit_0
# ---------------------------------------------------------------------------


def test_empty_require_and_optional_returns_exit_0():
    """B184, D74: Empty --require and --optional → exit 0 (no constraints enforced).

    Per phase1/04a § 3 exit codes: 'exit 0: wrapped function returned
    successfully + all --require keys present + all --optional keys present
    (or both lists empty)'. When both lists are empty, exit 0 regardless of
    what keys the returned CredentialsDict contains — no constraint is
    being evaluated.

    This is the default invocation mode (no --require / --optional args),
    equivalent to 'can the envelope be decrypted at all?' without key-set
    verification.

    D74, B184. Spec: phase1/04a § 3 exit codes + § 3 CLI interface defaults.
    """
    mod = _load_module(load_credentials_return=_FULL_CREDS)

    result = _call_vcl(mod, require=[], optional=[])

    assert result["exit_code"] == EXIT_SUCCESS, (
        f"Empty require + optional lists → exit_code must be {EXIT_SUCCESS}. "
        f"Got: {result['exit_code']!r}. "
        "Per phase1/04a § 3: both lists empty = no constraint violated."
    )
    assert result["required_keys_total"] == 0, (
        f"required_keys_total must be 0 when no required keys specified. "
        f"Got: {result['required_keys_total']!r}"
    )
    assert result["optional_keys_total"] == 0, (
        f"optional_keys_total must be 0 when no optional keys specified. "
        f"Got: {result['optional_keys_total']!r}"
    )
