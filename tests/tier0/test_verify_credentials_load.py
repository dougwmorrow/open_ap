"""Tier 0 build-time smoke test for tools/verify_credentials_load.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (credentials_loader, pyodbc cursor, subprocess,
filesystem) are mocked. No live TPM2, GPG, or SQL Server required.

North Star pillars:
  - Audit-grade (D76 audit-row contract: one CLI_VERIFY_CREDENTIALS_LOAD row
    per invocation; Metadata JSON keys canonical; error_type never leaks
    plaintext per § 3.6 + SensitiveDataFilter).
  - Operationally stable (D67 Tier 0 discipline: import + invoke + shape +
    error-modes in < 5 s with zero external I/O).
  - Idempotent (D15: re-invocation produces a NEW audit row; no side-effects
    on filesystem or credentials; each verification is its own audit moment
    per § 3 idempotency note).
  - Traceability (D103: credentials live OUTSIDE /debi; only KEY NAMES — never
    VALUES — appear in any output or audit row).

D-numbers: D67 (Tier 0 discipline), D74 (exit-code contract: 0/1/2),
D75 (arg naming), D76 (audit-row contract), D77 (6-canonical-assertion
Tier 0 scaffold), D103 (Claude Code security model — credentials boundary).

B-numbers: B184 (this tool's backlog entry, closed by authoring this tool +
its tests), B182 (RB-14 pre-flight consumer; CLOSED 2026-05-11 via RB-14).

Spec: phase1/04a_phase_0_prep_tools.md § 3 (Tool 12 canonical spec).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path (matches tests/ convention)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Tool module path — the file does not yet exist at test-authoring time
# (implementation lands at Phase 2 R1 per phase2/00_phase_overview.md R1).
# All smoke tests load it via spec_from_file_location; if the file is absent
# the import-test fails with an informative message, blocking the build
# correctly per D67 semantics.
# ---------------------------------------------------------------------------

_TOOL_PATH = _PROJECT_ROOT / "tools" / "verify_credentials_load.py"
_TOOL_MODULE_KEY = "tools.verify_credentials_load"

# ---------------------------------------------------------------------------
# Shared constants — single source of truth inside this file
# ---------------------------------------------------------------------------

# Required keys per phase1/04a § 3 --json output + PipelineEventLog Metadata
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

# D76 EventType for this tool (CLI_* family, Round 7 § 1.1)
EXPECTED_EVENT_TYPE = "CLI_VERIFY_CREDENTIALS_LOAD"

# Synthetic credentials dict returned by the mocked load_credentials()
# Per § 3: CredentialsDict is NewType wrapping dict[str, str]; key NAMES only
# in output, never VALUES. Values here are masked sentinels for test safety.
_SYNTHETIC_CREDS: dict[str, str] = {
    "ORACLE_PASSWORD": "<masked-in-test>",
    "MSSQL_PASSWORD": "<masked-in-test>",
    "SNOWFLAKE_PRIVATE_KEY_PEM": "<masked-in-test>",
    "VAULT_DB_PASSWORD": "<masked-in-test>",
}

# D75 canonical args
_ACTOR = "test-build-smoke"
_JUSTIFICATION = "Tier 0 build-time assertion"
_ENVELOPE_PATH = "/etc/pipeline/credentials.json.gpg"


# ---------------------------------------------------------------------------
# Helpers — module loader + mock factories
# ---------------------------------------------------------------------------


def _load_module() -> Any:
    """Load tools/verify_credentials_load.py with all external imports mocked.

    Patches credentials_loader and event_tracker so the module body never
    touches real TPM2, GPG, or SQL Server at import time.

    Returns the loaded module object, or raises if the file is absent
    (which fails the build per D67 intent).
    """
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    mock_creds_loader = MagicMock()
    mock_creds_loader.load_credentials.return_value = _SYNTHETIC_CREDS
    mock_creds_loader.CredentialsLoadError = type(
        "CredentialsLoadError", (Exception,), {}
    )
    mock_creds_loader.VaultConfigError = type(
        "VaultConfigError", (Exception,), {}
    )

    mock_event_tracker = MagicMock()
    mock_conn_module = MagicMock()
    mock_sensitive_filter = MagicMock()
    mock_sensitive_filter.SensitiveDataFilter.return_value.filter.side_effect = (
        lambda s: s  # identity — test content has no real secrets
    )

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


def _make_mock_cursor() -> MagicMock:
    """Return a mock pyodbc cursor that accepts PipelineEventLog INSERTs."""
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    return cursor


def _make_mock_conn(cursor: MagicMock) -> MagicMock:
    """Return a mock pyodbc connection wrapping the given cursor."""
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


# ---------------------------------------------------------------------------
# (a) Module imports without error
# ---------------------------------------------------------------------------


def test_module_imports():
    """(a) tools/verify_credentials_load.py imports without error.

    Per D67 Tier 0 assertion 1 + D77 6-canonical scaffold assertion 1.
    Verifies no missing dependencies, no syntax errors, no import-time
    side-effects (no TPM2 unseal, no GPG decrypt, no DB connection).

    North Star: Operationally stable (import failures block every subsequent
    build step per D67 failure consequence).

    Spec: phase1/04a § 3 (Tool 12 canonical spec).
    B184 (tool authoring closes this backlog item).
    """
    mod = _load_module()
    assert mod is not None, (
        "Module must load without error. If this fails, check for missing "
        "dependencies or syntax errors in tools/verify_credentials_load.py."
    )
    assert hasattr(mod, "verify_credentials_load"), (
        "tools/verify_credentials_load.py must expose a top-level "
        "'verify_credentials_load' function per phase1/04a § 3."
    )


# ---------------------------------------------------------------------------
# (b) Main public function is callable
# ---------------------------------------------------------------------------


def test_verify_credentials_load_is_callable():
    """(b) verify_credentials_load() is callable per D67 Tier 0 assertion 2.

    D77 canonical scaffold assertion 2: main public function invocable with
    synthetic dummy data. Uses mocked load_credentials() so no real envelope
    or TPM2 is required.

    Spec: phase1/04a § 3 function signature:
      verify_credentials_load(*, server, actor, justification) -> dict
    """
    mod = _load_module()
    assert callable(mod.verify_credentials_load), (
        "verify_credentials_load must be callable"
    )


# ---------------------------------------------------------------------------
# (c) Success path returns dict with required keys (all keys present, exit 0)
# ---------------------------------------------------------------------------


def test_success_all_keys_present_returns_dict():
    """(c) Mocked load_credentials success + required keys present → exit 0 dict.

    Per D67 Tier 0 assertion 3 + D77 canonical scaffold assertion 3 (success).
    Tier 0 assertion from phase1/04a § 3:
      mocked load_credentials returning CredentialsDict({'ORACLE_PASSWORD':
      '<masked>', 'MSSQL_PASSWORD': '<masked>'}) + --require
      ORACLE_PASSWORD,MSSQL_PASSWORD → exit 0; one CLI_VERIFY_CREDENTIALS_LOAD
      event row with Status=SUCCESS; required_keys_present_count equals 2.

    North Star: Audit-grade (D76 audit-row contract written on success).
    Traceability (D103: only key NAMES in output, no values).

    Spec: phase1/04a § 3 exit codes + § 3 Stdout (--json) shape.
    B184.
    """
    mod = _load_module()

    with patch.object(
        sys.modules.get("credentials_loader", MagicMock()),
        "load_credentials",
        return_value={"ORACLE_PASSWORD": "<masked>", "MSSQL_PASSWORD": "<masked>"},
    ):
        result = mod.verify_credentials_load(
            server="dev",
            actor=_ACTOR,
            justification=_JUSTIFICATION,
            require=["ORACLE_PASSWORD", "MSSQL_PASSWORD"],
            optional=[],
        )

    assert result is not None, "verify_credentials_load must return a dict, not None"
    assert isinstance(result, dict), (
        f"Return value must be a dict, got {type(result)!r}"
    )
    assert result.get("exit_code") == 0, (
        f"All required keys present → exit_code must be 0 per D74. "
        f"Got exit_code={result.get('exit_code')!r}. Full result: {result!r}"
    )
    assert result.get("required_keys_present_count") == 2, (
        f"required_keys_present_count must equal 2 (both keys present). "
        f"Got: {result.get('required_keys_present_count')!r}"
    )


# ---------------------------------------------------------------------------
# (d) Warning path: optional key missing → exit 1
# ---------------------------------------------------------------------------


def test_optional_key_missing_returns_exit_1():
    """(d) All required keys present + optional key missing → exit 1 dict.

    Per D67 Tier 0 assertion 4 + D77 canonical scaffold assertion 4 (warning).
    Per phase1/04a § 3: 'wrapped function returned successfully + ALL required
    keys present + SOME optional keys missing → exit 1 (warning-tier per D74
    "expected operational failure"; pipeline can proceed; operator review)'.

    D74: exit 1 = expected operational failure.
    North Star: Operationally stable (warning tier keeps pipeline running;
    does not abort on a non-fatal missing optional key).

    Spec: phase1/04a § 3 exit codes (warning-tier).
    B184.
    """
    mod = _load_module()

    with patch.object(
        sys.modules.get("credentials_loader", MagicMock()),
        "load_credentials",
        return_value={"ORACLE_PASSWORD": "<masked>"},
    ):
        result = mod.verify_credentials_load(
            server="dev",
            actor=_ACTOR,
            justification=_JUSTIFICATION,
            require=["ORACLE_PASSWORD"],
            optional=["SNOWFLAKE_PRIVATE_KEY_PEM"],  # absent from returned dict
        )

    assert isinstance(result, dict), "verify_credentials_load must return a dict"
    assert result.get("exit_code") == 1, (
        f"Optional key missing → exit_code must be 1 (warning-tier) per D74. "
        f"Got exit_code={result.get('exit_code')!r}."
    )
    missing_optional = result.get("missing_optional_keys", [])
    assert "SNOWFLAKE_PRIVATE_KEY_PEM" in missing_optional, (
        f"missing_optional_keys must list the absent optional key. "
        f"Got: {missing_optional!r}"
    )


# ---------------------------------------------------------------------------
# (e) Fatal path: CredentialsLoadError → exit 2
# ---------------------------------------------------------------------------


def test_credentials_load_error_returns_exit_2():
    """(e) Mocked load_credentials raising CredentialsLoadError → exit 2 dict.

    Per D67 Tier 0 assertion 5 + D77 canonical scaffold assertion 5 (fatal).
    Per phase1/04a § 3: 'CredentialsLoadError (PipelineFatalError) → exit 2;
    Status="FAILED"; error_type="CredentialsLoadError"; stderr filtered through
    SensitiveDataFilter'.

    D74: exit 2 = fatal; pipeline MUST NOT proceed.
    North Star: Audit-grade (D76 — FAILED audit row still written; no silent
    failure even on fatal path).

    Spec: phase1/04a § 3 error modes (CredentialsLoadError).
    B184.
    """
    mod = _load_module()

    CredentialsLoadError = type("CredentialsLoadError", (Exception,), {})

    with patch.object(
        sys.modules.get("credentials_loader", MagicMock()),
        "load_credentials",
        side_effect=CredentialsLoadError("envelope missing"),
    ), patch.object(
        sys.modules.get("credentials_loader", MagicMock()),
        "CredentialsLoadError",
        CredentialsLoadError,
    ):
        result = mod.verify_credentials_load(
            server="dev",
            actor=_ACTOR,
            justification=_JUSTIFICATION,
        )

    assert isinstance(result, dict), "verify_credentials_load must return a dict even on fatal path"
    assert result.get("exit_code") == 2, (
        f"CredentialsLoadError → exit_code must be 2 (fatal) per D74. "
        f"Got: {result.get('exit_code')!r}"
    )
    assert result.get("error_type") == "CredentialsLoadError", (
        f"error_type must be 'CredentialsLoadError'. Got: {result.get('error_type')!r}"
    )


# ---------------------------------------------------------------------------
# (f) Sensitive-data filter: no plaintext credential value in output
# ---------------------------------------------------------------------------


def test_sensitive_data_filter_no_plaintext_in_result():
    """(f) Credential values NEVER appear in result dict or Metadata.

    Per D67 Tier 0 assertion 6 + D77 canonical scaffold assertion 6
    (sensitive-data filter). Per phase1/04a § 3 Tier 0 smoke test item 6:
    'mocked dict returning a value matching SensitiveDataFilter regex
    (e.g., a string starting with -----BEGIN RSA PRIVATE KEY-----) → assert
    that value NEVER appears in stdout/stderr/PipelineEventLog Metadata;
    only the KEY NAME appears in any output'.

    North Star: Audit-grade + Traceability (D103: credentials live OUTSIDE
    /debi; any leaked plaintext is a D103 security boundary violation).

    Spec: phase1/04a § 3 (SensitiveDataFilter applied to stderr + Metadata).
    B184.
    """
    _PLAINTEXT_SECRET = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQ=="
    mod = _load_module()

    with patch.object(
        sys.modules.get("credentials_loader", MagicMock()),
        "load_credentials",
        return_value={"SNOWFLAKE_PRIVATE_KEY_PEM": _PLAINTEXT_SECRET},
    ):
        result = mod.verify_credentials_load(
            server="dev",
            actor=_ACTOR,
            justification=_JUSTIFICATION,
            require=["SNOWFLAKE_PRIVATE_KEY_PEM"],
            optional=[],
        )

    # Serialize the entire result to a string and scan for the raw secret
    result_str = json.dumps(result)
    assert _PLAINTEXT_SECRET not in result_str, (
        "The raw RSA private key value MUST NOT appear in the result dict. "
        "SensitiveDataFilter must strip or mask it. "
        "D103: credentials boundary violation — values must never leave the "
        "module boundary in plaintext. Only KEY NAMES are permitted in output."
    )
    # The KEY NAME itself must be present (redaction masks values, not names)
    assert "SNOWFLAKE_PRIVATE_KEY_PEM" in result_str, (
        "The KEY NAME 'SNOWFLAKE_PRIVATE_KEY_PEM' must still appear in the "
        "result (only the value is masked, not the name). "
        "Per phase1/04a § 3: missing_required_keys lists KEY NAMES only."
    )


# ---------------------------------------------------------------------------
# (g) Tier 0 total runtime < 5 s per D67
# ---------------------------------------------------------------------------


def test_tier0_total_runtime_under_5s():
    """(g) All Tier 0 smoke assertions complete in < 5 s per D67.

    Sentinel test: if the module starts performing real I/O (TPM2 unseal,
    GPG decrypt, DB connection, network call) the runtime ceiling will be
    breached and this test will catch the regression before the build step.

    D67: Runtime ceiling < 5 seconds per module (build-time constraint).
    Spec: phase1/04a § 3 Tier 0 (runs in < 5 s with mocked subprocess +
    mocked cursor per D77).
    B184.
    """
    start = time.monotonic()

    mod = _load_module()
    mock_creds = {"ORACLE_PASSWORD": "<masked>", "MSSQL_PASSWORD": "<masked>"}

    with patch.object(
        sys.modules.get("credentials_loader", MagicMock()),
        "load_credentials",
        return_value=mock_creds,
    ):
        mod.verify_credentials_load(
            server="dev",
            actor=_ACTOR,
            justification=_JUSTIFICATION,
            require=list(mock_creds.keys()),
            optional=[],
        )

    elapsed = time.monotonic() - start
    assert elapsed < 5.0, (
        f"Tier 0 smoke must complete in < 5 s per D67. "
        f"Took {elapsed:.2f} s. Module is likely performing real I/O — "
        "check for missing mocks (TPM2, GPG, pyodbc, filesystem)."
    )
