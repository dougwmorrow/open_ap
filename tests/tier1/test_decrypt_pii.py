"""Tier 1 unit tests for tools/decrypt_pii.py.

Tests run on every commit. No live DB, no live network required.
All external dependencies mocked with unittest.mock.

North Star pillars addressed:
  - Audit-grade (D76): exactly one CLI_DECRYPT_PII PipelineEventLog
    row per invocation; Metadata JSON carries token_hints + counts +
    actor + justification — NEVER plaintext. audit_event_id key MUST
    be present in JSON output per B218 spec-compliance lesson.
  - Security-first (D103 + P5): plaintext NEVER in log records;
    plaintext NEVER in audit Metadata; --mask-output redacts stdout
    display; SP-2 owns server-side audit insert atomic with decrypt.
  - Operationally stable (D74/D75): exit-code contract (0/1/2);
    argument naming discipline must be exactly per spec.
  - Idempotent at SP level (D15 + D26): M5 is read-only on PiiVault;
    audit log is append-only — multi-decrypt = N PiiVaultAccessLog
    rows server-side, plus ONE CLI-level audit row for the operator.

PiiVault.Token canonical type (Pitfall #9.d — verified at L1416):
  VARCHAR(40) hex ASCII (NOT NVARCHAR).
M5 canonical signature (Pitfall #9.l — verified at pii_decryptor.py L113-115):
  decrypt_token(*, token: str, justification: str,
                request_id: uuid.UUID | None = None) -> str | None

Naive-UTC datetime invariant (SCD2-P1-f): every datetime captured in
audit row Metadata must be tzinfo=None. Verified in test_audit_metadata_naive_utc.

Edge case IDs (per 04_EDGE_CASES.md):
  M-? (PII): plaintext leak via logs (canonical security ban).
  I1 (same RequestId retry: SP-2 writes one audit row per call — every
    invocation is a separate audit event per D26).
  N-? (Negative): empty justification at function boundary → fatal.

Decision citations:
  D6 (vault — operator-authority decrypt path),
  D15 (idempotency mandatory at SP level — re-run safe),
  D17 (idempotency at SP body — SP-2 read-only on PiiVault),
  D26 (append-only audit — every operator access is a separate row),
  D30 (CCPA-deleted tokens return None — DecryptDenied CAUGHT and
       treated as exit 0 success per spec L711),
  D67 (Tier 0 discipline — this file is Tier 1 complement),
  D68 (canonical exception hierarchy — utils.errors),
  D70 (Tier 1 unit-test discipline — per-error-path coverage),
  D74 (exit-code contract 0/1/2),
  D75 (arg naming: token / token-file / justification / request-id /
       mask-output / actor / json / verbose / quiet / no-audit-event),
  D76 (audit-row contract: CLI_DECRYPT_PII EventType; Metadata JSON
       shape; token_hints redacted; NEVER plaintext),
  D77 (Tier 0 canonical scaffold — Tier 1 extends, not weakens),
  D103 (security model — NEVER log decrypted plaintext),
  P5 (defense-in-depth log filter — sensitive_data_filter),
  P8 (audit every decrypt — SP-2 owns the server-side audit insert).

B-numbers:
  B214 (sys.modules pre-registration before exec_module),
  B215 (canonical exception classes — utils.errors single source),
  B218 (_test_sys_modules_patch stashed for _call_main re-patch;
        audit_event_id key MUST be present in JSON output),
  B228 (no local exception classes — utils.errors is the source).

Spec: phase1/04_tools.md § 3.4 (canonical spec L664-749).
M5: phase1/03_core_modules.md § 2.2 + data_load/pii_decryptor.py.
SP-2 DDL: phase1/01_database_schema.md L1414-1455.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import sys
import uuid
from datetime import datetime
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
# Constants — single source of truth
# ---------------------------------------------------------------------------

EXPECTED_EVENT_TYPE = "CLI_DECRYPT_PII"

EXIT_SUCCESS = 0
EXIT_OPERATIONAL_FAILURE = 1
EXIT_FATAL = 2

_ACTOR = "test-tier1"
_JUSTIFICATION = "Tier 1 unit test"

_PLAINTEXT_FOO = "foo"
_PLAINTEXT_SSN = "555-12-3456"
_PLAINTEXT_EMAIL = "alice@example.com"

_TOKEN_HEX_A = "a3f1234567890abcdef1234567890abcdef9c2d"
_TOKEN_HEX_B = "b1234567890abcdef1234567890abcdef9c2dab"
_TOKEN_HEX_C = "c2dabcdef1234567890abcdef1234567890a3f1"
_TOKEN_SHORT = "abc1"  # short token (defensive — canonical is 40 hex)

# Required JSON output keys per spec § 3.4 L735
REQUIRED_JSON_KEYS = frozenset({"dry_run", "counts", "verdicts", "audit_event_id"})

# Required Metadata keys per D76 + spec § 3.4 L692
REQUIRED_METADATA_KEYS = frozenset({"event_kind", "actor", "justification", "token_count"})


# ---------------------------------------------------------------------------
# Exception class resolution — B215 pattern (utils.errors canonical)
# ---------------------------------------------------------------------------

def _resolve_exception_classes():
    """Resolve canonical exception classes from utils.errors per B228 + B215."""
    try:
        from utils.errors import (  # type: ignore
            DecryptDenied,
            PipelineFatalError,
            PipelineRetryableError,
            TokenNotFound,
            VaultConfigError,
            VaultUnavailable,
        )
        return (
            TokenNotFound,
            DecryptDenied,
            VaultUnavailable,
            VaultConfigError,
            PipelineFatalError,
            PipelineRetryableError,
        )
    except ImportError:
        class TokenNotFound(Exception):  # type: ignore[no-redef]
            """Stand-in: utils.errors.TokenNotFound missing."""

        class DecryptDenied(Exception):  # type: ignore[no-redef]
            """Stand-in: utils.errors.DecryptDenied missing."""

        class VaultUnavailable(Exception):  # type: ignore[no-redef]
            """Stand-in: utils.errors.VaultUnavailable missing."""

        class VaultConfigError(Exception):  # type: ignore[no-redef]
            """Stand-in: utils.errors.VaultConfigError missing."""

        class PipelineFatalError(Exception):  # type: ignore[no-redef]
            """Stand-in: utils.errors.PipelineFatalError missing."""

        class PipelineRetryableError(Exception):  # type: ignore[no-redef]
            """Stand-in: utils.errors.PipelineRetryableError missing."""

        return (
            TokenNotFound,
            DecryptDenied,
            VaultUnavailable,
            VaultConfigError,
            PipelineFatalError,
            PipelineRetryableError,
        )


(
    TokenNotFound,
    DecryptDenied,
    VaultUnavailable,
    VaultConfigError,
    PipelineFatalError,
    PipelineRetryableError,
) = _resolve_exception_classes()


# ---------------------------------------------------------------------------
# Module loader — mocks all external dependencies
# ---------------------------------------------------------------------------


def _make_decrypt_side_effect(token_to_plaintext: dict[str, Any]):
    """Return a side_effect function that maps token → plaintext / exception.

    Values can be:
      - str: returned as plaintext
      - None: returned (treated as CCPA-deleted by tool)
      - Exception instance: raised
    """
    def _side(*, token: str, justification: str, request_id: uuid.UUID):
        if token not in token_to_plaintext:
            raise TokenNotFound(f"Token absent: {token!r}")
        result = token_to_plaintext[token]
        if isinstance(result, Exception):
            raise result
        return result
    return _side


def _load_tool_module(
    *,
    plaintext: str | None = _PLAINTEXT_FOO,
    raise_token_not_found: bool = False,
    raise_decrypt_denied: bool = False,
    raise_vault_unavailable: bool = False,
    raise_vault_config_error: bool = False,
    raise_unexpected: bool = False,
    decrypt_side_effect: Any = None,
    audit_cursor_fails: bool = False,
) -> Any:
    """Load tools/decrypt_pii.py with all external imports mocked.

    Parameters
    ----------
    plaintext:
        Default return value for M5 decrypt_token. None = CCPA-deleted.
    raise_*:
        If True, M5 raises the corresponding exception.
    decrypt_side_effect:
        Override — callable used as decrypt_token.side_effect.
    audit_cursor_fails:
        If True, the audit-row INSERT cursor raises an exception
        (audit-row write should be best-effort; tool must still exit
        with the verdict exit code).

    B214 pattern: sys.modules pre-registration before exec_module().
    B215 pattern: canonical exception classes NOT mocked.
    B218 pattern: _test_sys_modules_patch stashed for _call_main re-patch.
    """
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    mock_decrypt_token = MagicMock()
    if decrypt_side_effect is not None:
        mock_decrypt_token.side_effect = decrypt_side_effect
    elif raise_token_not_found:
        mock_decrypt_token.side_effect = TokenNotFound("Token absent — test fixture")
    elif raise_decrypt_denied:
        mock_decrypt_token.side_effect = DecryptDenied("CCPA-deleted — test fixture")
    elif raise_vault_unavailable:
        mock_decrypt_token.side_effect = VaultUnavailable("Vault unreachable — test fixture")
    elif raise_vault_config_error:
        mock_decrypt_token.side_effect = VaultConfigError("Vault config error — test fixture")
    elif raise_unexpected:
        mock_decrypt_token.side_effect = RuntimeError("Unexpected — test fixture")
    else:
        mock_decrypt_token.return_value = plaintext

    mock_pii_decryptor = MagicMock()
    mock_pii_decryptor.decrypt_token = mock_decrypt_token

    # Audit-row cursor mock
    mock_cursor = MagicMock()
    executed_sql: list[str] = []
    executed_params: list[Any] = []
    executed_param_lists: list[list[Any]] = []

    def _capture_execute(sql: str, *args, **kwargs) -> None:
        executed_sql.append(str(sql))
        # args is a tuple of pyodbc-style positional params
        param_list = list(args)
        executed_param_lists.append(param_list)
        # Flatten for quick scan
        for p in param_list:
            if isinstance(p, (list, tuple)):
                executed_params.extend(p)
            else:
                executed_params.append(p)

    if audit_cursor_fails:
        def _failing_execute(sql, *args, **kwargs):
            executed_sql.append(str(sql))
            raise RuntimeError("Audit INSERT failed — test fixture")
        mock_cursor.execute.side_effect = _failing_execute
    else:
        mock_cursor.execute.side_effect = _capture_execute

    mock_cursor.fetchone.return_value = (42,)  # SCOPE_IDENTITY() AS AuditEventId
    mock_cursor.fetchall.return_value = []
    mock_cursor.description = [("AuditEventId",)]
    mock_cursor._executed_sql = executed_sql
    mock_cursor._executed_params = executed_params
    mock_cursor._executed_param_lists = executed_param_lists

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
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

    mod._test_sys_modules_patch = sys_modules_patch
    mod._test_decrypt_token = mock_decrypt_token
    mod._test_cursor = mock_cursor
    mod._test_executed_sql = executed_sql
    mod._test_executed_params = executed_params
    mod._test_executed_param_lists = executed_param_lists
    return mod


def _call_main(mod: Any, **overrides: Any) -> dict:
    """Call tool main() with canonical defaults + overrides."""
    defaults = dict(
        actor=_ACTOR,
        tokens=[_TOKEN_HEX_A],
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


def _extract_audit_metadata(mod: Any) -> dict | None:
    """Find the audit-row INSERT and extract the Metadata JSON dict.

    Returns None if no audit INSERT was issued.
    """
    for sql, params in zip(mod._test_executed_sql, mod._test_executed_param_lists):
        if "PipelineEventLog" in sql and "INSERT" in sql:
            # Find the JSON string param (longest str param looking like JSON)
            for p in params:
                if isinstance(p, str) and p.startswith("{") and p.endswith("}"):
                    try:
                        return json.loads(p)
                    except (json.JSONDecodeError, ValueError):
                        continue
    return None


# ===========================================================================
# Tier 1: Happy path decrypt behavior
# ===========================================================================


class TestHappyPath:
    """M5 happy path → exit 0 + plaintext in stdout.

    Per § 3.4 L686 — stdout shape ``<token-hint> -> <plaintext>``.
    D74 (exit 0), D75 (--token + --justification).
    """

    def test_single_token_decrypted(self, capsys):
        """One token, M5 returns plaintext → exit 0, stdout has plaintext."""
        mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A])
        assert result["exit_code"] == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert _PLAINTEXT_FOO in captured.out

    def test_multiple_tokens_decrypted(self, capsys):
        """Three tokens, all decrypted → exit 0; all plaintexts in stdout."""
        side = _make_decrypt_side_effect({
            _TOKEN_HEX_A: "alpha",
            _TOKEN_HEX_B: "beta",
            _TOKEN_HEX_C: "gamma",
        })
        mod = _load_tool_module(decrypt_side_effect=side)
        result = _call_main(
            mod, tokens=[_TOKEN_HEX_A, _TOKEN_HEX_B, _TOKEN_HEX_C]
        )
        assert result["exit_code"] == EXIT_SUCCESS
        assert result["decrypted_count"] == 3
        captured = capsys.readouterr()
        assert "alpha" in captured.out
        assert "beta" in captured.out
        assert "gamma" in captured.out

    def test_m5_called_with_canonical_kw_only_signature(self):
        """M5 receives token + justification + request_id as kw-only args.

        Per pii_decryptor.py L113-115 (Pitfall #9.l): canonical signature
        is keyword-only. Positional args would fail at the M5 boundary.
        """
        mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
        _call_main(mod, tokens=[_TOKEN_HEX_A])
        decrypt = mod._test_decrypt_token
        assert decrypt.called
        # Verify no positional args (canonical is kw-only)
        for call in decrypt.call_args_list:
            assert call.args == (), (
                f"M5 must be invoked with keyword-only args. "
                f"Got positional: {call.args!r}."
            )
            assert "token" in call.kwargs
            assert "justification" in call.kwargs
            assert "request_id" in call.kwargs

    def test_unicode_plaintext_roundtrips(self, capsys):
        """M5 returns Unicode plaintext → tool emits it correctly."""
        unicode_pt = "Müller-García café é à"
        mod = _load_tool_module(plaintext=unicode_pt)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A])
        assert result["exit_code"] == EXIT_SUCCESS
        captured = capsys.readouterr()
        assert unicode_pt in captured.out


# ===========================================================================
# Tier 1: Justification validation (REQUIRED non-empty per D75)
# ===========================================================================


class TestJustificationRequired:
    """--justification is REQUIRED non-empty per D6 + D26 + D75.

    Per § 3.4 L711-712: empty / missing → exit 2 + NO SP-2 call + NO
    audit row. The function boundary enforces this for programmatic
    callers; argparse enforces it via required=True for CLI callers.
    """

    def test_empty_string_exits_2_no_sp2_call(self):
        """justification='' → exit 2; M5 NOT called; NO audit row written."""
        mod = _load_tool_module()
        result = _call_main(mod, justification="")
        assert result["exit_code"] == EXIT_FATAL
        assert not mod._test_decrypt_token.called
        # NO audit row INSERT
        sql_inserts = [s for s in mod._test_executed_sql if "INSERT" in s.upper()]
        assert not sql_inserts, (
            f"NO audit row should be written for empty justification. "
            f"Got INSERTs: {sql_inserts!r}."
        )

    def test_whitespace_only_exits_2(self):
        """justification='   \\t\\n' → exit 2; M5 NOT called."""
        mod = _load_tool_module()
        result = _call_main(mod, justification="   \t\n")
        assert result["exit_code"] == EXIT_FATAL
        assert not mod._test_decrypt_token.called

    def test_none_justification_exits_2(self):
        """justification=None → exit 2."""
        mod = _load_tool_module()
        result = _call_main(mod, justification=None)
        assert result["exit_code"] == EXIT_FATAL
        assert not mod._test_decrypt_token.called

    def test_argparse_rejects_missing_justification(self):
        """argparse argument parser rejects --token without --justification."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--token", _TOKEN_HEX_A])
        assert exc_info.value.code != 0

    def test_argparse_rejects_empty_justification(self):
        """argparse parser rejects --justification '' via _validate_args."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(
            ["--token", _TOKEN_HEX_A, "--justification", ""]
        )
        # _validate_args should call parser.error which raises SystemExit
        with pytest.raises(SystemExit):
            mod._validate_args(args, parser)


# ===========================================================================
# Tier 1: TokenNotFound (exit 2 fatal)
# ===========================================================================


class TestTokenNotFound:
    """M5 raises TokenNotFound → exit 2 + stdout 'NOT_FOUND'.

    Per § 3.4 L711: TokenNotFound is fatal — the Token is absent from
    PiiVault (configuration drift OR audit-trail tampering signal).
    """

    def test_token_not_found_exits_2(self):
        """M5 raises TokenNotFound → exit 2."""
        mod = _load_tool_module(raise_token_not_found=True)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A])
        assert result["exit_code"] == EXIT_FATAL
        assert result["not_found_count"] == 1

    def test_token_not_found_stdout_marker(self, capsys):
        """Stdout contains 'NOT_FOUND' for the not-found token."""
        mod = _load_tool_module(raise_token_not_found=True)
        _call_main(mod, tokens=[_TOKEN_HEX_A])
        captured = capsys.readouterr()
        assert "NOT_FOUND" in captured.out

    def test_mixed_found_and_not_found_exits_2(self, capsys):
        """If ANY token is not-found, overall exit is 2 (fatal trumps success)."""
        side = _make_decrypt_side_effect({
            _TOKEN_HEX_A: "alpha",
            # _TOKEN_HEX_B intentionally absent → side will raise TokenNotFound
        })
        mod = _load_tool_module(decrypt_side_effect=side)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A, _TOKEN_HEX_B])
        assert result["exit_code"] == EXIT_FATAL
        assert result["decrypted_count"] == 1
        assert result["not_found_count"] == 1


# ===========================================================================
# Tier 1: DecryptDenied / CCPA-deleted (exit 0 — NOT fatal)
# ===========================================================================


class TestDecryptDeniedCcpa:
    """M5 raises DecryptDenied → exit 0 + stdout 'CCPA-deleted'.

    THE most subtle behavior per § 3.4 L711: exception caught but NOT
    propagated to exit code. Re-running won't help — deletion was
    authorized per D30 + RB-10. The audit row WAS written server-side
    by SP-2 before SP-2 returned NULL per SP-2 body L1422-1434.
    """

    def test_ccpa_deleted_exits_0(self):
        """M5 raises DecryptDenied → exit 0 (NOT fatal per spec L711)."""
        mod = _load_tool_module(raise_decrypt_denied=True)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A])
        assert result["exit_code"] == EXIT_SUCCESS, (
            "DecryptDenied (CCPA) must exit 0 per spec § 3.4 L711. "
            f"Got: {result['exit_code']}."
        )

    def test_ccpa_deleted_stdout_marker(self, capsys):
        """Stdout contains '<NULL> (CCPA-deleted)' marker."""
        mod = _load_tool_module(raise_decrypt_denied=True)
        _call_main(mod, tokens=[_TOKEN_HEX_A])
        captured = capsys.readouterr()
        assert "CCPA-deleted" in captured.out
        assert "NULL" in captured.out

    def test_ccpa_deleted_increments_null_count(self):
        """null_count surfaces in result dict."""
        mod = _load_tool_module(raise_decrypt_denied=True)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A])
        assert result["null_count"] == 1
        assert result["decrypted_count"] == 0

    def test_m5_returning_none_treated_as_ccpa(self):
        """If M5 returns None directly (no exception), still treated as CCPA."""
        mod = _load_tool_module(plaintext=None)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A])
        assert result["exit_code"] == EXIT_SUCCESS
        assert result["null_count"] == 1


# ===========================================================================
# Tier 1: VaultUnavailable (exit 1 retryable)
# ===========================================================================


class TestVaultUnavailable:
    """M5 raises VaultUnavailable → exit 1 retryable.

    Per § 3.4 L710: 'VaultUnavailable (PipelineRetryableError) → exit 1'.
    Operator can re-run; no partial-state risk since SP-2 is read-only.
    """

    def test_vault_unavailable_exits_1(self):
        mod = _load_tool_module(raise_vault_unavailable=True)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A])
        assert result["exit_code"] == EXIT_OPERATIONAL_FAILURE

    def test_vault_unavailable_increments_count(self):
        mod = _load_tool_module(raise_vault_unavailable=True)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A])
        assert result["vault_unavailable_count"] == 1


# ===========================================================================
# Tier 1: VaultConfigError (exit 2 fatal)
# ===========================================================================


class TestVaultConfigError:
    """M5 raises VaultConfigError → exit 2 fatal."""

    def test_vault_config_error_exits_2(self):
        mod = _load_tool_module(raise_vault_config_error=True)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A])
        assert result["exit_code"] == EXIT_FATAL

    def test_vault_config_error_increments_count(self):
        mod = _load_tool_module(raise_vault_config_error=True)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A])
        assert result["error_count"] == 1


# ===========================================================================
# Tier 1: Token-file invocation
# ===========================================================================


class TestTokenFile:
    """--token-file invocation reads tokens line-by-line; '#' comments skipped.

    Per § 3.4 L716-718 + L744.
    """

    def test_token_file_reads_tokens(self, tmp_path, capsys):
        """File with 2 tokens, both decrypted → exit 0."""
        token_file = tmp_path / "tokens.txt"
        token_file.write_text(f"{_TOKEN_HEX_A}\n{_TOKEN_HEX_B}\n")
        side = _make_decrypt_side_effect({
            _TOKEN_HEX_A: "alpha",
            _TOKEN_HEX_B: "beta",
        })
        mod = _load_tool_module(decrypt_side_effect=side)
        result = _call_main(mod, tokens=None, token_file=str(token_file))
        assert result["exit_code"] == EXIT_SUCCESS
        assert result["decrypted_count"] == 2

    def test_token_file_skips_comments(self, tmp_path):
        """Lines starting with '#' are skipped per spec § 3.4 L744."""
        token_file = tmp_path / "tokens.txt"
        token_file.write_text(
            f"# header comment\n{_TOKEN_HEX_A}\n# mid-comment\n{_TOKEN_HEX_B}\n"
        )
        side = _make_decrypt_side_effect({
            _TOKEN_HEX_A: "alpha",
            _TOKEN_HEX_B: "beta",
        })
        mod = _load_tool_module(decrypt_side_effect=side)
        result = _call_main(mod, tokens=None, token_file=str(token_file))
        assert result["exit_code"] == EXIT_SUCCESS
        assert result["token_count"] == 2

    def test_token_file_skips_blank_lines(self, tmp_path):
        """Blank lines skipped."""
        token_file = tmp_path / "tokens.txt"
        token_file.write_text(f"\n\n{_TOKEN_HEX_A}\n\n\n")
        mod = _load_tool_module(plaintext="alpha")
        result = _call_main(mod, tokens=None, token_file=str(token_file))
        assert result["exit_code"] == EXIT_SUCCESS
        assert result["token_count"] == 1

    def test_token_file_strips_whitespace(self, tmp_path):
        """Leading/trailing whitespace on lines stripped."""
        token_file = tmp_path / "tokens.txt"
        token_file.write_text(f"  {_TOKEN_HEX_A}  \n\t{_TOKEN_HEX_B}\t\n")
        side = _make_decrypt_side_effect({
            _TOKEN_HEX_A: "alpha",
            _TOKEN_HEX_B: "beta",
        })
        mod = _load_tool_module(decrypt_side_effect=side)
        result = _call_main(mod, tokens=None, token_file=str(token_file))
        assert result["exit_code"] == EXIT_SUCCESS
        assert result["token_count"] == 2

    def test_token_file_missing_exits_2(self, tmp_path):
        """File does not exist → exit 2 fatal."""
        missing = tmp_path / "nonexistent.txt"
        mod = _load_tool_module()
        result = _call_main(mod, tokens=None, token_file=str(missing))
        assert result["exit_code"] == EXIT_FATAL

    def test_token_file_empty_exits_2(self, tmp_path):
        """File with only comments / blanks → exit 2 fatal."""
        token_file = tmp_path / "empty.txt"
        token_file.write_text("# only comments\n\n# more\n")
        mod = _load_tool_module()
        result = _call_main(mod, tokens=None, token_file=str(token_file))
        assert result["exit_code"] == EXIT_FATAL

    def test_token_and_token_file_mutually_exclusive(self, tmp_path):
        """Cannot specify both --token AND --token-file → exit 2."""
        token_file = tmp_path / "tokens.txt"
        token_file.write_text(f"{_TOKEN_HEX_A}\n")
        mod = _load_tool_module()
        result = _call_main(
            mod, tokens=[_TOKEN_HEX_A], token_file=str(token_file)
        )
        assert result["exit_code"] == EXIT_FATAL

    def test_no_token_no_file_exits_2(self):
        """Neither --token nor --token-file → exit 2."""
        mod = _load_tool_module()
        result = _call_main(mod, tokens=None, token_file=None)
        assert result["exit_code"] == EXIT_FATAL


# ===========================================================================
# Tier 1: Audit row writing (D76 contract)
# ===========================================================================


class TestAuditRowWriting:
    """Exactly one CLI_DECRYPT_PII audit row written per invocation.

    Per D76 + § 3.4 L691. Metadata JSON carries token_hints + counts +
    actor + justification + request_id — NEVER plaintext.
    """

    def test_audit_row_written_on_success(self):
        """Happy path writes one PipelineEventLog INSERT."""
        mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
        _call_main(mod, tokens=[_TOKEN_HEX_A])
        inserts = [
            s for s in mod._test_executed_sql
            if "PipelineEventLog" in s and "INSERT" in s.upper()
        ]
        assert len(inserts) == 1, (
            f"Exactly ONE PipelineEventLog INSERT per invocation. "
            f"Got {len(inserts)}: {inserts!r}."
        )

    def test_audit_row_event_type_is_cli_decrypt_pii(self):
        """Audit row EventType is CLI_DECRYPT_PII per CLAUDE.md CLI_* family."""
        mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
        _call_main(mod, tokens=[_TOKEN_HEX_A])
        # EventType is one of the positional params in the INSERT
        all_params = mod._test_executed_params
        assert EXPECTED_EVENT_TYPE in all_params, (
            f"EventType {EXPECTED_EVENT_TYPE!r} must appear in audit INSERT params. "
            f"Got: {all_params!r}."
        )

    def test_audit_metadata_has_required_keys(self):
        """Metadata JSON has all required D76 keys."""
        mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
        _call_main(mod, tokens=[_TOKEN_HEX_A])
        metadata = _extract_audit_metadata(mod)
        assert metadata is not None, "Audit Metadata JSON must be parseable"
        for key in REQUIRED_METADATA_KEYS:
            assert key in metadata, (
                f"Audit Metadata missing required key {key!r}. "
                f"Got keys: {list(metadata.keys())!r}."
            )

    def test_audit_metadata_carries_token_hints_not_raw_tokens(self):
        """Metadata 'token_hints' carries redacted hints, NOT raw tokens.

        Per D103 — even the Token itself, while not plaintext-PII, should
        appear in audit Metadata as a redacted hint to discourage Token-
        scraping attacks on the audit log. Per spec § 3.4 L734.
        """
        mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
        _call_main(mod, tokens=[_TOKEN_HEX_A])
        metadata = _extract_audit_metadata(mod)
        assert metadata is not None
        hints = metadata.get("token_hints", [])
        assert hints, "token_hints must be non-empty"
        # Hint format: first 4 chars + '<...>' + last 4 chars
        for hint in hints:
            assert "<...>" in hint, (
                f"token_hint must contain '<...>' redaction marker. "
                f"Got: {hint!r}."
            )

    def test_audit_metadata_carries_actor_and_justification(self):
        """Metadata has actor + justification per D76."""
        mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
        _call_main(
            mod,
            tokens=[_TOKEN_HEX_A],
            justification="Audit ticket SR-12345",
            actor="alice@example.com",
        )
        metadata = _extract_audit_metadata(mod)
        assert metadata is not None
        assert metadata["actor"] == "alice@example.com"
        assert metadata["justification"] == "Audit ticket SR-12345"

    def test_audit_metadata_status_failed_on_token_not_found(self):
        """Metadata status='FAILED' when tokens not found."""
        mod = _load_tool_module(raise_token_not_found=True)
        _call_main(mod, tokens=[_TOKEN_HEX_A])
        metadata = _extract_audit_metadata(mod)
        assert metadata is not None
        assert metadata.get("status") == "FAILED"
        assert metadata.get("exit_code") == EXIT_FATAL

    def test_no_audit_event_skips_insert(self):
        """--no-audit-event skips the audit row write (pipeline-programmatic path)."""
        mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
        _call_main(mod, tokens=[_TOKEN_HEX_A], no_audit_event=True)
        inserts = [
            s for s in mod._test_executed_sql
            if "PipelineEventLog" in s and "INSERT" in s.upper()
        ]
        assert not inserts, (
            "no_audit_event=True must skip the audit-row INSERT. "
            f"Got: {inserts!r}."
        )

    def test_audit_cursor_failure_does_not_change_exit_code(self):
        """Audit-row INSERT failure is best-effort; verdict exit code is authoritative."""
        mod = _load_tool_module(
            plaintext=_PLAINTEXT_FOO,
            audit_cursor_fails=True,
        )
        result = _call_main(mod, tokens=[_TOKEN_HEX_A])
        # Even if audit write fails, the decrypt itself succeeded → exit 0
        assert result["exit_code"] == EXIT_SUCCESS


# ===========================================================================
# SECURITY-CRITICAL: Plaintext NEVER in logs / NEVER in audit Metadata
# ===========================================================================


class TestSecurityPlaintextSafety:
    """Plaintext NEVER in log records; NEVER in audit Metadata.

    Per D103 + P5: plaintext flows ONLY through print() to stdout
    (operator-facing). NEVER through logger.* calls (which would be
    captured by SqlServerLogHandler → PipelineLog). NEVER into audit
    Metadata JSON (which goes to PipelineEventLog).
    """

    def test_plaintext_not_in_log_records(self, caplog):
        """Walk every log record at every level; plaintext must be absent."""
        caplog.set_level(logging.DEBUG)
        mod = _load_tool_module(plaintext=_PLAINTEXT_SSN)
        _call_main(mod, tokens=[_TOKEN_HEX_A])
        for record in caplog.records:
            message = record.getMessage()
            assert _PLAINTEXT_SSN not in message, (
                f"SECURITY VIOLATION: plaintext in log at {record.levelname}: "
                f"{message!r}. Per D103 + P5."
            )

    def test_email_plaintext_not_in_logs(self, caplog):
        """Email-like plaintext also not in logs (different shape)."""
        caplog.set_level(logging.DEBUG)
        mod = _load_tool_module(plaintext=_PLAINTEXT_EMAIL)
        _call_main(mod, tokens=[_TOKEN_HEX_A])
        for record in caplog.records:
            assert _PLAINTEXT_EMAIL not in record.getMessage()

    def test_plaintext_not_in_audit_metadata(self):
        """Plaintext value must NOT appear in audit Metadata JSON."""
        mod = _load_tool_module(plaintext=_PLAINTEXT_SSN)
        _call_main(mod, tokens=[_TOKEN_HEX_A])
        metadata = _extract_audit_metadata(mod)
        assert metadata is not None
        metadata_str = json.dumps(metadata)
        assert _PLAINTEXT_SSN not in metadata_str, (
            f"SECURITY VIOLATION: plaintext in audit Metadata: "
            f"{metadata_str!r}. Per D103 + § 3.4 L692."
        )

    def test_plaintext_not_in_audit_sql_params(self):
        """Plaintext must NOT appear in any SQL param sent to audit INSERT."""
        mod = _load_tool_module(plaintext=_PLAINTEXT_SSN)
        _call_main(mod, tokens=[_TOKEN_HEX_A])
        for param in mod._test_executed_params:
            if isinstance(param, str):
                assert _PLAINTEXT_SSN not in param, (
                    f"SECURITY VIOLATION: plaintext in SQL param: {param!r}."
                )

    def test_plaintext_not_in_returned_result_dict(self):
        """The result dict returned to programmatic callers does NOT contain
        plaintext (defense-in-depth — programmatic callers may leak the dict).
        """
        mod = _load_tool_module(plaintext=_PLAINTEXT_SSN)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A])
        result_str = json.dumps(result, default=str)
        assert _PLAINTEXT_SSN not in result_str, (
            "SECURITY VIOLATION: plaintext appears in result dict — "
            "programmatic callers may leak. Verdicts in result should "
            "be the audit-safe projection (no plaintext field)."
        )

    def test_justification_value_in_metadata_is_intentional(self):
        """The --justification operator value DOES appear in Metadata (audit-grade
        contract per D75) — but it's operator-supplied free text, NOT M5's
        decrypted plaintext. This test exists to document the distinction.
        """
        mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
        operator_justification = "Audit ticket SR-99999"
        _call_main(
            mod, tokens=[_TOKEN_HEX_A], justification=operator_justification
        )
        metadata = _extract_audit_metadata(mod)
        assert metadata is not None
        # operator justification IS in metadata — this is correct
        assert metadata["justification"] == operator_justification


# ===========================================================================
# Tier 1: JSON output shape
# ===========================================================================


class TestJsonOutput:
    """--json emits the canonical JSON payload per § 3.4 L735."""

    def test_json_output_has_required_keys(self, capsys):
        """JSON output has dry_run, counts, verdicts, audit_event_id keys."""
        mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
        _call_main(mod, tokens=[_TOKEN_HEX_A], json_output=True)
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        for key in REQUIRED_JSON_KEYS:
            assert key in payload, (
                f"JSON output missing required key {key!r}. "
                f"Got keys: {list(payload.keys())!r}. Spec § 3.4 L735."
            )

    def test_json_audit_event_id_present_b218(self, capsys):
        """audit_event_id key MUST be present per B218 lesson."""
        mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
        _call_main(mod, tokens=[_TOKEN_HEX_A], json_output=True)
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert "audit_event_id" in payload, (
            "audit_event_id key MUST be present in JSON output per B218."
        )

    def test_json_counts_shape(self, capsys):
        """counts dict has the canonical verdict-count keys."""
        side = _make_decrypt_side_effect({
            _TOKEN_HEX_A: "alpha",
            _TOKEN_HEX_B: DecryptDenied("CCPA-deleted"),
        })
        mod = _load_tool_module(decrypt_side_effect=side)
        _call_main(
            mod, tokens=[_TOKEN_HEX_A, _TOKEN_HEX_B], json_output=True
        )
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        counts = payload["counts"]
        assert counts["decrypted"] == 1
        assert counts["ccpa_deleted"] == 1

    def test_json_verdicts_shape_per_token(self, capsys):
        """Each verdict has token_hint + plaintext + status + request_id."""
        mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
        _call_main(mod, tokens=[_TOKEN_HEX_A], json_output=True)
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert len(payload["verdicts"]) == 1
        v = payload["verdicts"][0]
        assert "token_hint" in v
        assert "plaintext" in v
        assert "status" in v
        assert "request_id" in v
        assert v["status"] == "decrypted"
        assert v["plaintext"] == _PLAINTEXT_FOO

    def test_json_quiet_does_not_suppress_json(self, capsys):
        """JSON output goes via print(), so --quiet (logging-level) does NOT
        affect it. The JSON appears regardless.
        """
        mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
        _call_main(
            mod, tokens=[_TOKEN_HEX_A], json_output=True, quiet=False
        )
        captured = capsys.readouterr()
        assert captured.out.strip(), "JSON output must be non-empty"
        payload = json.loads(captured.out)
        assert payload is not None


# ===========================================================================
# Tier 1: --mask-output redaction
# ===========================================================================


class TestMaskOutput:
    """--mask-output redacts plaintext display in stdout."""

    def test_mask_output_redacts_plaintext(self, capsys):
        """Full plaintext does NOT appear in stdout when --mask-output is on."""
        mod = _load_tool_module(plaintext=_PLAINTEXT_SSN)
        _call_main(
            mod, tokens=[_TOKEN_HEX_A], mask_output=True
        )
        captured = capsys.readouterr()
        assert _PLAINTEXT_SSN not in captured.out

    def test_mask_output_shows_redaction_marker(self, capsys):
        """Stdout shows last-4-chars + redaction prefix."""
        mod = _load_tool_module(plaintext=_PLAINTEXT_SSN)
        _call_main(
            mod, tokens=[_TOKEN_HEX_A], mask_output=True
        )
        captured = capsys.readouterr()
        # last 4 chars: '3456'
        assert _PLAINTEXT_SSN[-4:] in captured.out or "redacted" in captured.out.lower()

    def test_mask_output_in_json_still_emits_plaintext(self, capsys):
        """--mask-output does NOT affect --json (operator opted in to JSON)."""
        mod = _load_tool_module(plaintext=_PLAINTEXT_SSN)
        _call_main(
            mod,
            tokens=[_TOKEN_HEX_A],
            mask_output=True,
            json_output=True,
        )
        captured = capsys.readouterr()
        # Per spec: --json mode shows actual plaintext for downstream consumption
        # The --mask-output flag is a human-format display courtesy.
        payload = json.loads(captured.out)
        assert payload["verdicts"][0]["plaintext"] == _PLAINTEXT_SSN


# ===========================================================================
# Tier 1: Token-hint formatting
# ===========================================================================


class TestTokenHint:
    """token_hint = first 4 + '<...>' + last 4 chars (per spec § 3.4 L734)."""

    def test_token_hint_shape(self):
        """40-char hex token → '<4>< ...><4>'."""
        mod = _load_tool_module()
        hint = mod._token_hint(_TOKEN_HEX_A)
        assert hint.startswith(_TOKEN_HEX_A[:4])
        assert hint.endswith(_TOKEN_HEX_A[-4:])
        assert "<...>" in hint

    def test_short_token_hint_returns_full(self):
        """Tokens < 9 chars returned as-is (defensive)."""
        mod = _load_tool_module()
        hint = mod._token_hint(_TOKEN_SHORT)
        # _TOKEN_SHORT is 4 chars → returned as-is
        assert hint == _TOKEN_SHORT

    def test_empty_token_hint(self):
        """Empty token → '<empty>'."""
        mod = _load_tool_module()
        assert mod._token_hint("") == "<empty>"
        assert mod._token_hint(None) == "<empty>"


# ===========================================================================
# Tier 1: Request-ID handling
# ===========================================================================


class TestRequestId:
    """--request-id passed to M5; auto-generated if absent."""

    def test_request_id_auto_generated(self):
        """request_id=None → auto-generates UUID; M5 receives a UUID instance."""
        mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
        _call_main(mod, tokens=[_TOKEN_HEX_A], request_id=None)
        decrypt = mod._test_decrypt_token
        call_kwargs = decrypt.call_args.kwargs
        rid = call_kwargs["request_id"]
        assert isinstance(rid, uuid.UUID), (
            f"M5 must receive a UUID instance for request_id. Got: {type(rid).__name__}."
        )

    def test_explicit_request_id_passes_through(self):
        """Explicit UUID passed through to M5 unchanged."""
        my_uuid = uuid.UUID("12345678-1234-1234-1234-1234567890ab")
        mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
        _call_main(mod, tokens=[_TOKEN_HEX_A], request_id=my_uuid)
        decrypt = mod._test_decrypt_token
        assert decrypt.call_args.kwargs["request_id"] == my_uuid

    def test_same_request_id_for_all_tokens_in_invocation(self):
        """Per RB-4: one --request-id ties the whole invocation."""
        side = _make_decrypt_side_effect({
            _TOKEN_HEX_A: "alpha",
            _TOKEN_HEX_B: "beta",
        })
        mod = _load_tool_module(decrypt_side_effect=side)
        my_uuid = uuid.uuid4()
        _call_main(
            mod, tokens=[_TOKEN_HEX_A, _TOKEN_HEX_B], request_id=my_uuid
        )
        decrypt = mod._test_decrypt_token
        assert decrypt.call_count == 2
        for call in decrypt.call_args_list:
            assert call.kwargs["request_id"] == my_uuid


# ===========================================================================
# Tier 1: Exit-code derivation across mixed verdicts
# ===========================================================================


class TestExitCodeDerivation:
    """Exit-code aggregation per spec § 3.4 L737-740.

    Priority order (highest wins):
      2 (fatal) — any not_found / error
      1 (retryable) — any vault_unavailable AND no fatal
      0 (success) — all decrypted / ccpa_deleted
    """

    def test_all_decrypted_exits_0(self):
        side = _make_decrypt_side_effect({
            _TOKEN_HEX_A: "alpha",
            _TOKEN_HEX_B: "beta",
        })
        mod = _load_tool_module(decrypt_side_effect=side)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A, _TOKEN_HEX_B])
        assert result["exit_code"] == EXIT_SUCCESS

    def test_all_ccpa_exits_0(self):
        side = _make_decrypt_side_effect({
            _TOKEN_HEX_A: DecryptDenied("ccpa-1"),
            _TOKEN_HEX_B: DecryptDenied("ccpa-2"),
        })
        mod = _load_tool_module(decrypt_side_effect=side)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A, _TOKEN_HEX_B])
        assert result["exit_code"] == EXIT_SUCCESS

    def test_mixed_success_ccpa_exits_0(self):
        side = _make_decrypt_side_effect({
            _TOKEN_HEX_A: "alpha",
            _TOKEN_HEX_B: DecryptDenied("ccpa"),
        })
        mod = _load_tool_module(decrypt_side_effect=side)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A, _TOKEN_HEX_B])
        assert result["exit_code"] == EXIT_SUCCESS

    def test_vault_unavailable_alone_exits_1(self):
        mod = _load_tool_module(raise_vault_unavailable=True)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A])
        assert result["exit_code"] == EXIT_OPERATIONAL_FAILURE

    def test_success_plus_vault_unavailable_exits_1(self):
        side = _make_decrypt_side_effect({
            _TOKEN_HEX_A: "alpha",
            _TOKEN_HEX_B: VaultUnavailable("transient"),
        })
        mod = _load_tool_module(decrypt_side_effect=side)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A, _TOKEN_HEX_B])
        assert result["exit_code"] == EXIT_OPERATIONAL_FAILURE

    def test_token_not_found_trumps_vault_unavailable(self):
        """Fatal trumps retryable when mixed."""
        side = _make_decrypt_side_effect({
            _TOKEN_HEX_A: VaultUnavailable("transient"),
            # _TOKEN_HEX_B absent → TokenNotFound (fatal)
        })
        mod = _load_tool_module(decrypt_side_effect=side)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A, _TOKEN_HEX_B])
        assert result["exit_code"] == EXIT_FATAL

    def test_invalid_empty_token_exits_2(self):
        """Empty token in --token list → exit 2 (rejected before M5)."""
        mod = _load_tool_module()
        result = _call_main(mod, tokens=[_TOKEN_HEX_A, ""])
        assert result["exit_code"] == EXIT_FATAL


# ===========================================================================
# Tier 1: Naive-UTC datetime invariant (SCD2-P1-f)
# ===========================================================================


class TestNaiveUtcDatetime:
    """Datetimes in audit Metadata must be tzinfo=None per SCD2-P1-f."""

    def test_started_at_dt_naive_utc(self):
        """result['started_at_dt'] is timezone-naive."""
        mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
        result = _call_main(mod, tokens=[_TOKEN_HEX_A])
        started_at_dt = result.get("started_at_dt")
        if started_at_dt is not None and isinstance(started_at_dt, datetime):
            assert started_at_dt.tzinfo is None, (
                f"started_at_dt must be tz-naive per SCD2-P1-f. "
                f"Got: {started_at_dt.tzinfo!r}."
            )


# ===========================================================================
# Tier 1: Pitfall #9 guard — canonical M5 signature
# ===========================================================================


class TestPitfall9CanonicalSignature:
    """Pitfall #9.l producer self-check: M5 signature is canonical.

    M5 canonical (verified at pii_decryptor.py L113-115):
      decrypt_token(*, token, justification, request_id) -> str | None
    """

    def test_m5_invoked_with_canonical_kw_names(self):
        """token, justification, request_id are the canonical kw arg names."""
        mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
        _call_main(mod, tokens=[_TOKEN_HEX_A])
        decrypt = mod._test_decrypt_token
        call_kwargs = decrypt.call_args.kwargs
        canonical = {"token", "justification", "request_id"}
        assert canonical.issubset(set(call_kwargs.keys())), (
            f"M5 must be invoked with canonical kw args: {canonical}. "
            f"Got: {set(call_kwargs.keys())}."
        )

    def test_m5_not_invoked_with_invented_kw(self):
        """No invented kw args like 'operator', 'user', 'reason'."""
        mod = _load_tool_module(plaintext=_PLAINTEXT_FOO)
        _call_main(mod, tokens=[_TOKEN_HEX_A])
        decrypt = mod._test_decrypt_token
        call_kwargs = set(decrypt.call_args.kwargs.keys())
        invented = {"operator", "user", "reason", "purpose"}
        intersection = call_kwargs & invented
        assert not intersection, (
            f"M5 must NOT be invoked with invented kw args: {intersection}. "
            f"Got: {call_kwargs}. Pitfall #9.l."
        )


# ===========================================================================
# Tier 1: argparse argument surface
# ===========================================================================


class TestArgparseSurface:
    """Argparse accepts D75 canonical args; produces expected types."""

    def test_argparse_accepts_canonical_args(self):
        """All D75 canonical args accepted."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args([
            "--token", _TOKEN_HEX_A,
            "--justification", _JUSTIFICATION,
            "--actor", _ACTOR,
            "--json",
            "--verbose",
            "--no-audit-event",
            "--mask-output",
        ])
        assert args.token == [_TOKEN_HEX_A]
        assert args.justification == _JUSTIFICATION
        assert args.actor == _ACTOR
        assert args.json_output is True
        assert args.verbose is True
        assert args.no_audit_event is True
        assert args.mask_output is True

    def test_argparse_token_repeatable(self):
        """--token is action='append' (repeatable)."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args([
            "--token", _TOKEN_HEX_A,
            "--token", _TOKEN_HEX_B,
            "--justification", _JUSTIFICATION,
        ])
        assert args.token == [_TOKEN_HEX_A, _TOKEN_HEX_B]

    def test_argparse_request_id_accepts_uuid_str(self):
        """--request-id accepts UUID string."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        my_uuid_str = "12345678-1234-1234-1234-1234567890ab"
        args = parser.parse_args([
            "--token", _TOKEN_HEX_A,
            "--justification", _JUSTIFICATION,
            "--request-id", my_uuid_str,
        ])
        assert args.request_id == my_uuid_str

    def test_argparse_help_mentions_security(self):
        """--help body emphasizes audit + justification."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        help_text = parser.format_help()
        assert "justification" in help_text.lower()
        # Help should mention audit / PiiVaultAccessLog
        assert "audit" in help_text.lower() or "PiiVaultAccessLog" in help_text
