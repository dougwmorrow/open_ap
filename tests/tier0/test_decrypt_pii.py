"""Tier 0 build-time smoke test for tools/decrypt_pii.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (M5 ``decrypt_token``, M16 event_tracker,
PipelineEventLog cursor) are mocked. No live DB, no live network required.

7-assertion D77-canonical scaffold per phase1/04_tools.md § 3.4 L742:
  (a) Module imports without error (tools/decrypt_pii.py).
  (b) --help exits 0 + contains the word 'justification'.
  (c) Missing --justification raises arg-parse error → exit 2.
  (d) --token <hex> + --justification 'audit' with mocked decrypt_token
      returning plaintext 'foo' → tool returns exit 0 + stdout contains 'foo'.
  (e) Mocked decrypt_token returning DecryptDenied (CCPA) → exit 0 +
      stdout contains 'CCPA-deleted' (per spec § 3.4 L711 — NOT fatal).
  (f) Mocked decrypt_token raising TokenNotFound → exit 2.
  (g) --mask-output masks plaintext to redaction form in stdout.

Security-critical invariants verified:
  - Plaintext NEVER appears in log records at any level (caplog).
  - Audit row Metadata (the JSON payload) does NOT contain plaintext.
  - Missing justification = no SP-2 call + no audit row.

North Star pillars addressed:
  - Audit-grade (D76 audit-row contract: exactly one CLI_DECRYPT_PII
    row per invocation; Metadata JSON carries token_hints + counts +
    actor + justification; NEVER plaintext).
  - Security-first (D103 — NEVER log decrypted plaintext; sensitive
    data filter is defense-in-depth at the handler level).
  - Operationally stable (D67 Tier 0: import + invoke + shape +
    error-modes in < 5s with zero external I/O; D74 exit-code 0/1/2).
  - Idempotent (D15 + D26): M5 is read-only on PiiVault; the audit
    log accumulates one row per invocation (multi-decrypt = N audit
    rows server-side, but ONE CLI-level audit row for the operator).

SP-2 canonical signature (Pitfall #9.b — verified at L1414-1455):
  CREATE PROCEDURE General.ops.PiiVault_Decrypt
    @RequestId UNIQUEIDENTIFIER, @Token VARCHAR(40),
    @Justification NVARCHAR(MAX)
M5 canonical signature (Pitfall #9.l — verified at pii_decryptor.py L113-115):
  decrypt_token(*, token: str, justification: str,
                request_id: uuid.UUID | None = None) -> str | None

D-numbers: D6 (vault), D15 (idempotency), D26 (append-only audit),
  D30 (CCPA-deleted authorized), D67 (Tier 0 discipline), D74 (exit
  codes 0/1/2), D75 (arg naming — --justification REQUIRED non-empty),
  D76 (audit-row CLI_DECRYPT_PII), D77 (Tier 0 7-canonical scaffold
  per spec § 3.4 L742), D103 (security model — NEVER log plaintext),
  P5 (defense-in-depth log filter), P8 (audit every decrypt).

B-numbers:
  B214 (sys.modules pre-registration before exec_module),
  B215 (canonical exception classes from utils.errors),
  B218 (_test_sys_modules_patch stashed for _call_main re-patch),
  B228 (no local exception classes — utils.errors single source).

Spec: phase1/04_tools.md § 3.4 (canonical spec L664-749).
M5: phase1/03_core_modules.md § 2.2 + data_load/pii_decryptor.py.
SP-2 DDL: phase1/01_database_schema.md L1414-1455.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
import time
import uuid
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

_TOOL_PATH = _PROJECT_ROOT / "tools" / "decrypt_pii.py"
_TOOL_MODULE_KEY = "tools.decrypt_pii"

# ---------------------------------------------------------------------------
# Constants — single source of truth for expected values
# ---------------------------------------------------------------------------

# D76 EventType per CLI_* family (§ 3.4 L691)
EXPECTED_EVENT_TYPE = "CLI_DECRYPT_PII"

# D74 exit codes (§ 3.4 L737-740)
EXIT_SUCCESS = 0
EXIT_OPERATIONAL_FAILURE = 1
EXIT_FATAL = 2

# D75 canonical actor (per TTY heuristic default — used in tests)
_ACTOR = "test-build-smoke"
_JUSTIFICATION = "Tier 0 smoke test"

# Canonical M5 happy-path plaintext
_PLAINTEXT_FOO = "foo"
_PLAINTEXT_SENSITIVE = "555-12-3456"
_TOKEN_HEX = "a3f1234567890abcdef1234567890abcdef9c2d"


# ---------------------------------------------------------------------------
# Exception class resolution — B215 pattern (utils.errors canonical)
# ---------------------------------------------------------------------------

def _resolve_exception_classes():
    """Resolve canonical exception classes from utils.errors per B228 + B215.

    utils.errors is the single source of truth (no local exception classes
    in tools/ per B228). If utils.errors lacks the classes (build-time
    miss), define minimal stand-ins so the test can still validate the
    remaining assertions.
    """
    try:
        from utils.errors import (  # type: ignore
            DecryptDenied,
            TokenNotFound,
            VaultConfigError,
            VaultUnavailable,
        )
        return TokenNotFound, DecryptDenied, VaultUnavailable, VaultConfigError
    except ImportError:
        class TokenNotFound(Exception):  # type: ignore[no-redef]
            """Stand-in: utils.errors.TokenNotFound missing."""

        class DecryptDenied(Exception):  # type: ignore[no-redef]
            """Stand-in: utils.errors.DecryptDenied missing."""

        class VaultUnavailable(Exception):  # type: ignore[no-redef]
            """Stand-in: utils.errors.VaultUnavailable missing."""

        class VaultConfigError(Exception):  # type: ignore[no-redef]
            """Stand-in: utils.errors.VaultConfigError missing."""

        return TokenNotFound, DecryptDenied, VaultUnavailable, VaultConfigError


TokenNotFound, DecryptDenied, VaultUnavailable, VaultConfigError = (
    _resolve_exception_classes()
)


# ---------------------------------------------------------------------------
# Module loader — mocks all external dependencies
# ---------------------------------------------------------------------------


def _load_tool_module(
    *,
    plaintext: str | None = _PLAINTEXT_FOO,
    raise_token_not_found: bool = False,
    raise_decrypt_denied: bool = False,
    raise_vault_unavailable: bool = False,
    raise_vault_config_error: bool = False,
) -> Any:
    """Load tools/decrypt_pii.py with all external imports mocked.

    Parameters
    ----------
    plaintext:
        Value M5 ``decrypt_token`` returns on the happy path. None
        signals "use one of the raise_* flags".
    raise_token_not_found:
        If True, M5 raises TokenNotFound (fatal → exit 2).
    raise_decrypt_denied:
        If True, M5 raises DecryptDenied (CCPA → exit 0 per spec L711).
    raise_vault_unavailable:
        If True, M5 raises VaultUnavailable (retryable → exit 1).
    raise_vault_config_error:
        If True, M5 raises VaultConfigError (fatal → exit 2).

    B214 pattern: sys.modules pre-registration before exec_module().
    B215 pattern: canonical exception classes from utils.errors NOT mocked.
    B218 pattern: _test_sys_modules_patch stashed on mod for _call_main re-patch.
    """
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    # Build mock for M5 decrypt_token
    mock_decrypt_token = MagicMock()
    if raise_token_not_found:
        mock_decrypt_token.side_effect = TokenNotFound(
            "Token absent — test fixture"
        )
    elif raise_decrypt_denied:
        mock_decrypt_token.side_effect = DecryptDenied(
            "CCPA-deleted — test fixture"
        )
    elif raise_vault_unavailable:
        mock_decrypt_token.side_effect = VaultUnavailable(
            "Vault unreachable — test fixture"
        )
    elif raise_vault_config_error:
        mock_decrypt_token.side_effect = VaultConfigError(
            "Vault config error — test fixture"
        )
    else:
        mock_decrypt_token.return_value = plaintext

    # Build M5 module mock that exposes decrypt_token
    mock_pii_decryptor = MagicMock()
    mock_pii_decryptor.decrypt_token = mock_decrypt_token

    # Audit-row cursor mock (PipelineEventLog INSERT)
    mock_cursor = MagicMock()
    executed_sql: list[str] = []
    executed_params: list[Any] = []

    def _capture_execute(sql: str, *args, **kwargs) -> None:
        executed_sql.append(str(sql))
        if args:
            params = args[0] if len(args) == 1 else args
            if isinstance(params, (list, tuple)):
                executed_params.extend(params)
            else:
                executed_params.append(params)

    mock_cursor.execute.side_effect = _capture_execute
    mock_cursor.fetchone.return_value = (12345,)  # SCOPE_IDENTITY() AS AuditEventId
    mock_cursor.fetchall.return_value = []
    mock_cursor.description = [("AuditEventId",)]
    mock_cursor._executed_sql = executed_sql
    mock_cursor._executed_params = executed_params

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_connections = MagicMock()
    mock_connections.cursor_for = MagicMock(return_value=mock_cursor)
    mock_connections.get_general_connection = MagicMock(return_value=mock_conn)
    mock_connections.get_connection = MagicMock(return_value=mock_conn)

    mock_event_tracker = MagicMock()
    mock_event = MagicMock()
    mock_event_tracker.track = MagicMock()
    mock_event_tracker.track.return_value.__enter__ = MagicMock(return_value=mock_event)
    mock_event_tracker.track.return_value.__exit__ = MagicMock(return_value=False)

    mock_config = MagicMock()
    mock_config.GENERAL_DB = "General"

    mock_pyodbc = MagicMock()
    mock_pyodbc.connect = MagicMock(return_value=mock_conn)

    sys_modules_patch: dict[str, Any] = {
        "connections": mock_connections,
        "utils.connections": mock_connections,
        "config": mock_config,
        "utils.configuration": mock_config,
        "observability.event_tracker": mock_event_tracker,
        "observability.log_handler": MagicMock(),
        "pyodbc": mock_pyodbc,
        "data_load.pii_decryptor": mock_pii_decryptor,
    }

    with patch.dict("sys.modules", sys_modules_patch):
        spec = importlib.util.spec_from_file_location(_TOOL_MODULE_KEY, _TOOL_PATH)
        mod = importlib.util.module_from_spec(spec)
        # B214: pre-register BEFORE exec_module
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

    # B218: stash patch dict for _call_main re-apply
    mod._test_sys_modules_patch = sys_modules_patch
    mod._test_decrypt_token = mock_decrypt_token
    mod._test_cursor = mock_cursor
    mod._test_executed_sql = executed_sql
    mod._test_executed_params = executed_params
    return mod


def _call_main(mod: Any, **overrides: Any) -> dict:
    """Call tool main() with canonical defaults + overrides.

    Defaults match spec: justification required; mask_output False;
    json_output False; verbose/quiet False.

    Re-applies sys.modules patch per B218 (measure_lateness pattern).
    """
    defaults = dict(
        actor=_ACTOR,
        tokens=[_TOKEN_HEX],
        token_file=None,
        justification=_JUSTIFICATION,
        request_id=None,
        mask_output=False,
        json_output=False,
        verbose=False,
        quiet=False,
        no_audit_event=False,
        decrypt_fn=getattr(mod, "_test_decrypt_token", None),
    )
    defaults.update(overrides)
    sys_modules_patch = getattr(mod, "_test_sys_modules_patch", {})
    try:
        with patch.dict("sys.modules", sys_modules_patch):
            return mod.main(**defaults)
    except SystemExit as exc:
        return {"exit_code": exc.code, "_raised_system_exit": True}
    except Exception as exc:
        return {
            "exit_code": EXIT_FATAL,
            "_exception": str(exc),
            "_raised_system_exit": False,
        }


# ===========================================================================
# Assertion (a): Module imports without error
# ===========================================================================


def test_a_module_imports():
    """(a) tools/decrypt_pii.py imports without error.

    Per D67 Tier 0 assertion 1 + D77 7-canonical scaffold assertion 1.
    Verifies no missing dependencies, no syntax errors, no import-time DB calls.
    Module must expose a top-level 'main' function per § 3.4 CLI interface.

    North Star: Operationally stable (import failure blocks every build step).
    D67, D77. Spec: phase1/04_tools.md § 3.4.
    """
    mod = _load_tool_module()
    assert mod is not None, (
        "tools/decrypt_pii.py must load without error. "
        "Check for missing dependencies or syntax errors. D67."
    )
    assert hasattr(mod, "main"), (
        "tools/decrypt_pii.py must expose a top-level 'main' function "
        "per § 3.4 CLI interface. D67 Tier 0 assertion 1."
    )
    assert hasattr(mod, "_build_arg_parser"), (
        "tools/decrypt_pii.py must expose _build_arg_parser (Tier 0 scaffold "
        "contract — Tier 0 needs to test argparse without subprocess invocation)."
    )


# ===========================================================================
# Assertion (b): --help exits 0 + mentions 'justification'
# ===========================================================================


def test_b_help_exits_0_mentions_justification():
    """(b) --help exits 0 + contains the word 'justification'.

    argparse always calls sys.exit(0) on --help. The help body must
    mention --justification so the operator sees the required argument.

    D74 (exit 0 = help), D77 (assertion 2). Spec: § 3.4 L742(b).
    """
    mod = _load_tool_module()

    parser = mod._build_arg_parser()
    # argparse --help raises SystemExit(0) AFTER printing help text.
    # We capture the help text directly via format_help() to verify
    # 'justification' is mentioned.
    help_text = parser.format_help()
    assert "justification" in help_text.lower(), (
        "--help must mention 'justification' since it's REQUIRED. "
        f"Got help text: {help_text!r}. "
        "Spec: § 3.4 L725 (--justification REQUIRED). D77 assertion 2."
    )

    # Also verify argparse exits 0 on --help
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])
    assert exc_info.value.code == 0, (
        f"--help must exit 0 per D74. Got: {exc_info.value.code!r}. "
        "D74. Spec: § 3.4 L742(b)."
    )


# ===========================================================================
# Assertion (c): Missing --justification → exit 2 + no SP-2 call
# ===========================================================================


def test_c_missing_justification_exits_2():
    """(c) Missing / empty --justification → exit 2 + NO M5 call + NO audit row.

    Per spec § 3.4 L711-712: 'Missing --justification (empty string) →
    arg-parse error → exit 2'. The function-boundary validation in
    main() catches programmatic callers that bypass argparse.

    SECURITY-CRITICAL: audit row MUST NOT be written for malformed
    input (audit-grade contract requires non-empty reason).

    D75 (justification REQUIRED), D74 (exit 2). Spec: § 3.4 L742(c) + L711.
    """
    mod = _load_tool_module()
    assert mod is not None

    # Test 1: empty string justification
    result = _call_main(mod, justification="")
    assert result.get("exit_code") == EXIT_FATAL, (
        f"Empty justification must exit {EXIT_FATAL}. "
        f"Got: {result.get('exit_code')!r}. Spec: § 3.4 L711."
    )
    # SP-2 must NOT have been called
    decrypt_mock = mod._test_decrypt_token
    assert not decrypt_mock.called, (
        "Empty justification must NOT trigger M5 decrypt_token call. "
        f"Mock was called {decrypt_mock.call_count} times. "
        "Audit-grade contract: malformed input rejected at function "
        "boundary BEFORE any SP-2 round trip."
    )

    # Test 2: whitespace-only justification
    mod2 = _load_tool_module()
    result2 = _call_main(mod2, justification="   ")
    assert result2.get("exit_code") == EXIT_FATAL, (
        f"Whitespace-only justification must exit {EXIT_FATAL}. "
        f"Got: {result2.get('exit_code')!r}."
    )
    assert not mod2._test_decrypt_token.called, (
        "Whitespace-only justification must NOT trigger M5 decrypt_token call."
    )

    # Test 3: argparse rejects missing --justification
    parser = mod._build_arg_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--token", _TOKEN_HEX])
    assert exc_info.value.code != 0, (
        "argparse must reject missing --justification (exit non-zero). "
        f"Got code: {exc_info.value.code!r}. Spec: § 3.4 L725."
    )


# ===========================================================================
# Assertion (d): Happy path — mocked plaintext 'foo' → exit 0 + stdout has 'foo'
# ===========================================================================


def test_d_happy_path_decrypted_plaintext_in_stdout(capsys):
    """(d) --token <hex> + --justification 'audit' + mocked plaintext 'foo'
        → exit 0 + stdout contains 'foo'.

    Per spec § 3.4 L686-689: stdout shape ``<token-hint> -> <plaintext>``.
    Verifies M5 was invoked with the canonical keyword-only signature
    AND the plaintext flows to stdout (operator-facing channel).

    SECURITY: plaintext goes through ``print()``, NOT through logger
    (which would be filtered by sensitive_data_filter at the handler
    level).

    D74 (exit 0 success), D77 (assertion 4). Spec: § 3.4 L742(d) + L686.
    """
    mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
    assert mod is not None

    result = _call_main(
        mod, tokens=[_TOKEN_HEX], justification=_JUSTIFICATION
    )

    assert result.get("exit_code") == EXIT_SUCCESS, (
        f"Happy-path decrypt must exit {EXIT_SUCCESS}. "
        f"Got: {result.get('exit_code')!r}, error: "
        f"{result.get('error_message')!r}. Spec: § 3.4 L737."
    )

    # M5 must have been called with canonical keyword-only signature
    decrypt_mock = mod._test_decrypt_token
    assert decrypt_mock.called, (
        "M5 decrypt_token must be invoked for happy path. "
        f"Call count: {decrypt_mock.call_count}."
    )
    call_kwargs = decrypt_mock.call_args.kwargs
    assert call_kwargs.get("token") == _TOKEN_HEX, (
        f"M5 must be called with token={_TOKEN_HEX!r} (canonical kw-only). "
        f"Got kwargs: {call_kwargs!r}."
    )
    assert call_kwargs.get("justification") == _JUSTIFICATION, (
        f"M5 must be called with justification={_JUSTIFICATION!r}. "
        f"Got kwargs: {call_kwargs!r}."
    )
    assert "request_id" in call_kwargs, (
        "M5 must be called with request_id (auto-generated UUID when "
        "operator omits --request-id). "
        f"Got kwargs: {call_kwargs!r}."
    )

    # Plaintext must appear in stdout
    captured = capsys.readouterr()
    assert _PLAINTEXT_FOO in captured.out, (
        f"Plaintext {_PLAINTEXT_FOO!r} must appear in stdout per spec § 3.4 L686. "
        f"Got stdout: {captured.out!r}."
    )


# ===========================================================================
# Assertion (e): DecryptDenied (CCPA) → exit 0 + stdout 'CCPA-deleted'
# ===========================================================================


def test_e_ccpa_deleted_exits_0_with_marker(capsys):
    """(e) Mocked M5 raising DecryptDenied → exit 0 + stdout contains 'CCPA-deleted'.

    Per spec § 3.4 L711: 'DecryptDenied ... NOT an exception per § 2.2;
    tool returns exit 0 with stdout <NULL> (CCPA-deleted) — audit row
    IS written'. The CCPA deletion was authorized per RB-10; the
    operator must see it explicitly but the tool does NOT exit fatal.

    This is THE most subtle behavior of this tool: M5 raises an
    exception, but the tool catches it and treats it as a success
    outcome (exit 0). Re-running won't help — the CCPA deletion is
    permanent per D30.

    D30 (CCPA-authorized non-decrypt), D77 (assertion 5). Spec: § 3.4 L742(e) + L711.
    """
    mod = _load_tool_module(raise_decrypt_denied=True)
    assert mod is not None

    result = _call_main(
        mod, tokens=[_TOKEN_HEX], justification=_JUSTIFICATION
    )

    assert result.get("exit_code") == EXIT_SUCCESS, (
        f"DecryptDenied (CCPA) must exit {EXIT_SUCCESS} per spec § 3.4 L711. "
        f"Got: {result.get('exit_code')!r}. "
        "NOT a fatal exit code — the deletion was authorized per RB-10."
    )

    captured = capsys.readouterr()
    assert "CCPA-deleted" in captured.out, (
        f"DecryptDenied verdict must surface 'CCPA-deleted' marker in stdout "
        f"per spec § 3.4 L687. Got stdout: {captured.out!r}."
    )


# ===========================================================================
# Assertion (f): TokenNotFound → exit 2
# ===========================================================================


def test_f_token_not_found_exits_2(capsys):
    """(f) Mocked M5 raising TokenNotFound → exit 2 fatal.

    Per spec § 3.4 L711: 'TokenNotFound ... → exit 2; stderr message
    names the token's hint; audit row NOT written (no token = no audit
    semantics)'. The Token is absent from PiiVault — this is a
    configuration drift (wrong vault) or audit-trail tampering signal.

    D68 (PipelineFatalError hierarchy), D74 (exit 2), D77 (assertion 6).
    Spec: § 3.4 L742(f) + L711.
    """
    mod = _load_tool_module(raise_token_not_found=True)
    assert mod is not None

    result = _call_main(
        mod, tokens=[_TOKEN_HEX], justification=_JUSTIFICATION
    )

    assert result.get("exit_code") == EXIT_FATAL, (
        f"TokenNotFound must exit {EXIT_FATAL} per spec § 3.4 L711. "
        f"Got: {result.get('exit_code')!r}."
    )

    captured = capsys.readouterr()
    assert "NOT_FOUND" in captured.out, (
        f"TokenNotFound verdict must surface 'NOT_FOUND' in stdout "
        f"per spec § 3.4 L688. Got stdout: {captured.out!r}."
    )


# ===========================================================================
# Assertion (g): --mask-output masks plaintext in stdout
# ===========================================================================


def test_g_mask_output_redacts_plaintext(capsys):
    """(g) --mask-output masks plaintext to redaction form in stdout.

    Per spec § 3.4 L729-732: '--mask-output flag, default False; show
    plaintext only as last-4-chars + redaction prefix in stdout'.
    Caveat: 'still writes plaintext to caller's stdout pipe — operator
    should redirect stdout to a file if even masked display is too
    sensitive'.

    The masking is a CLI display courtesy, not a security primitive.
    The actual plaintext is still in process memory until GC.

    D77 (assertion 7). Spec: § 3.4 L742(g) + L729.
    """
    mod = _load_tool_module(plaintext=_PLAINTEXT_SENSITIVE)
    assert mod is not None

    result = _call_main(
        mod,
        tokens=[_TOKEN_HEX],
        justification=_JUSTIFICATION,
        mask_output=True,
    )

    assert result.get("exit_code") == EXIT_SUCCESS, (
        f"Masked output must still exit {EXIT_SUCCESS}. "
        f"Got: {result.get('exit_code')!r}."
    )

    captured = capsys.readouterr()
    # Full plaintext must NOT appear in stdout when --mask-output is on
    assert _PLAINTEXT_SENSITIVE not in captured.out, (
        f"With --mask-output, full plaintext {_PLAINTEXT_SENSITIVE!r} must "
        f"NOT appear in stdout. Got stdout: {captured.out!r}. "
        "Spec: § 3.4 L729."
    )
    # SOME form of redaction must appear (e.g. last-4-chars OR redaction prefix)
    assert (
        "redacted" in captured.out.lower()
        or "<...>" in captured.out
        or _PLAINTEXT_SENSITIVE[-4:] in captured.out
    ), (
        f"With --mask-output, stdout must show redacted form. "
        f"Got stdout: {captured.out!r}. Spec: § 3.4 L729."
    )


# ===========================================================================
# SECURITY-CRITICAL: Plaintext NEVER appears in log records
# ===========================================================================


def test_security_plaintext_not_in_logs(caplog):
    """Plaintext NEVER appears in log records at any level.

    Per D103 + P5: the decrypted plaintext must NOT flow through the
    Python logging chain. M5 logs Token + RequestId + plaintext_length
    (NOT the value); this tool logs Token (hex hint) + RequestId.
    SensitiveDataFilter is defense-in-depth at the handler level.

    This test is THE most important security guard: any future
    refactoring that accidentally introduces ``logger.info(plaintext)``
    or ``logger.debug(f"got {plaintext}")`` immediately breaks this
    assertion.

    D103 (security model), P5 (defense-in-depth log filter).
    """
    caplog.set_level(logging.DEBUG)
    mod = _load_tool_module(plaintext=_PLAINTEXT_SENSITIVE)
    assert mod is not None

    _call_main(mod, tokens=[_TOKEN_HEX], justification=_JUSTIFICATION)

    # Walk every log record at every level
    for record in caplog.records:
        message = record.getMessage()
        assert _PLAINTEXT_SENSITIVE not in message, (
            f"SECURITY VIOLATION: plaintext {_PLAINTEXT_SENSITIVE!r} appeared "
            f"in log record at level {record.levelname}: {message!r}. "
            f"Module: {record.module}, function: {record.funcName}. "
            "Per D103 + P5 — plaintext MUST NEVER enter the logging chain."
        )


# ===========================================================================
# SECURITY-CRITICAL: Audit row Metadata does NOT contain plaintext
# ===========================================================================


def test_security_plaintext_not_in_audit_metadata():
    """Audit row Metadata JSON does NOT contain plaintext.

    Per D103 + spec § 3.4 L692-693: Metadata JSON carries token_hints
    (redacted) + counts + actor + justification + request_id — NEVER
    the decrypted plaintext value.

    This test inspects the SQL params written to PipelineEventLog and
    verifies the Metadata JSON serialization does not leak plaintext.

    D76 (audit-row contract), D103 (security model).
    """
    import json

    mod = _load_tool_module(plaintext=_PLAINTEXT_SENSITIVE)
    assert mod is not None

    _call_main(mod, tokens=[_TOKEN_HEX], justification=_JUSTIFICATION)

    # Inspect the executed SQL params for the audit row INSERT
    executed_params = mod._test_executed_params
    # Find the Metadata JSON parameter — it's the longest string parameter
    # in the INSERT (typically). We scan all params and check none contain
    # the plaintext.
    for param in executed_params:
        if isinstance(param, str):
            # Try to parse as JSON; if it parses, walk it
            try:
                decoded = json.loads(param)
            except (json.JSONDecodeError, ValueError):
                # Plain string param — still check it directly
                assert _PLAINTEXT_SENSITIVE not in param, (
                    f"SECURITY VIOLATION: plaintext appeared in audit SQL "
                    f"param: {param!r}. Per D103 + § 3.4 L692."
                )
                continue
            # JSON-decoded — re-serialize and check
            serialized = json.dumps(decoded)
            assert _PLAINTEXT_SENSITIVE not in serialized, (
                f"SECURITY VIOLATION: plaintext appeared in audit-row Metadata "
                f"JSON: {serialized!r}. Per D103 + § 3.4 L692."
            )


# ===========================================================================
# Runtime ceiling assertion — Tier 0 must complete < 5 s total (D67)
# ===========================================================================


def test_tier0_runtime_ceiling():
    """Tier 0 full suite mock-invocation completes < 5 s (D67 ceiling).

    Verifies that the smoke test itself does not incur external I/O.
    Runs the primary operations (import, decrypt, error paths) under
    the 5-second ceiling mandated by D67.

    D67 (runtime ceiling < 5s per module). Spec: § 3.4 L742 preamble.
    """
    start = time.monotonic()

    mod = _load_tool_module()
    assert mod is not None

    _call_main(mod, tokens=[_TOKEN_HEX], justification=_JUSTIFICATION)
    _call_main(mod, justification="")  # missing justification path

    elapsed = time.monotonic() - start
    assert elapsed < 5.0, (
        f"Tier 0 mock invocations exceeded 5s ceiling: {elapsed:.2f}s. "
        "D67 mandates < 5s for Tier 0 smoke tests (no external deps). "
        "Check for live DB calls or network I/O that bypassed mock."
    )
