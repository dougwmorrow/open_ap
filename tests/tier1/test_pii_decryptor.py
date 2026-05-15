"""Tier 1 unit test for data_load/pii_decryptor.py.

Per D70 Tier 1 — per-error-path + per-edge-case coverage; mocks M6
``call_vault_sp``; no live SQL Server.

Test scope (organized as classes per sibling tier1 style):

  TestInterface
    - decrypt_token exposed via __all__.
    - Module imports uuid module.
    - Module does NOT define local exception classes (B228 lesson).

  TestJustificationValidation
    - Empty string rejected with ValueError.
    - Whitespace-only string rejected with ValueError.
    - None rejected with ValueError.
    - Non-str types (int / bytes / list) rejected with ValueError.
    - SP-2 NEVER invoked on validation failure (audit contract).

  TestTokenValidation
    - Empty token rejected with ValueError.
    - None token rejected with ValueError.
    - Non-str token rejected with ValueError.

  TestRequestIdHandling
    - None → auto-generates uuid4.
    - Explicit UUID passed through as str.
    - Non-UUID type rejected with ValueError.
    - sp_args['RequestId'] is always a str (pyodbc binding contract).

  TestHappyPath
    - SP-2 single-row dict result → returns plaintext str.
    - SP-2 multi-row dict result → first row wins (defensive).
    - Plaintext can contain Unicode / special chars (round-trip).

  TestTokenNotFound
    - SP-2 empty dict → TokenNotFound (fatal).
    - SP-2 _rows: [] → TokenNotFound.
    - Metadata carries token + request_id.

  TestDecryptDenied
    - SP-2 returns dict with PlaintextValue=None → DecryptDenied.
    - Closes B103 (Round 6 § 7.9 resolution).
    - Metadata carries token + request_id.

  TestVaultUnavailableBubble
    - M6 VaultUnavailable bubbles up unchanged.
    - M6 VaultConfigError bubbles up unchanged.
    - PipelineFatalError sibling errors bubble up unchanged.

  TestLogSafety
    - Plaintext NEVER appears in log records.
    - Justification VALUE NEVER appears in log records (only length).
    - Token + request_id + plaintext_length DO appear at INFO.
    - On TokenNotFound, plaintext (which doesn't exist) not in logs.
    - On DecryptDenied, plaintext (NULL) not in logs.

  TestSpArgsContract
    - Composed call passes sp_name='PiiVault_Decrypt'.
    - sp_args has exactly {RequestId, Token, Justification}.
    - No extra keys leak from caller-side state.

  TestIdempotency
    - Two consecutive decrypts → two M6 calls (audit semantics, NOT
      result caching — every call is a separate audit event per D26).
    - Same RequestId across two calls produces two SP-2 invocations.

  TestPlaintextCoercion
    - bytes plaintext → decoded UTF-8.
    - bytearray plaintext → decoded UTF-8.
    - Non-decodable bytes → DecryptDenied (defensive).

Spec: phase1/03_core_modules.md § 2.2 + phase1/01_database_schema.md
SP-2 + PiiVaultAccessLog DDL.

D-numbers: D6, D17, D26, D30, D67, D68, D70, D75, D103.
B-numbers: M5 (build-tracker entry — closed by authoring this test);
B103 (DecryptDenied — verified raised per Round 6 § 7.9).
"""
from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_sp():
    """Patch data_load.pii_decryptor.call_vault_sp with a MagicMock."""
    from data_load import pii_decryptor as pd

    with patch.object(pd, "call_vault_sp") as mock:
        yield mock


def _success(token: str = "dna-test-token", plaintext: str = "555-12-3456"):
    """Build a canned SP-2 success-path result-set dict."""
    return {"Token": token, "PlaintextValue": plaintext}


def _denied(token: str = "dna-test-token"):
    """Build a canned SP-2 result-set with NULL plaintext (denied)."""
    return {"Token": token, "PlaintextValue": None}


def _absent():
    """Build a canned SP-2 empty result (Token absent)."""
    return {}


# ===========================================================================
# TestInterface
# ===========================================================================


class TestInterface:
    """The module's public surface matches the canonical § 2.2 spec."""

    def test_decrypt_token_in_all(self):
        from data_load import pii_decryptor as pd

        assert "decrypt_token" in pd.__all__

    def test_module_imports_uuid(self):
        """``import uuid`` resolves at module top (spec smoke (a))."""
        from data_load import pii_decryptor as pd

        assert pd.uuid is not None
        assert hasattr(pd.uuid, "uuid4")
        assert hasattr(pd.uuid, "UUID")

    def test_module_does_not_define_local_exception_classes(self):
        """B228 lesson — exceptions imported from utils.errors only.

        Defensive against the temptation to redefine TokenNotFound /
        DecryptDenied locally in this module (which would produce two
        independent class objects + break isinstance() at the caller).
        """
        from data_load import pii_decryptor as pd
        from utils.errors import (
            TokenNotFound as canonical_TokenNotFound,
            DecryptDenied as canonical_DecryptDenied,
        )

        # The names should resolve to the canonical classes via module
        # globals (the import-from path) — NOT to locally-defined classes.
        assert pd.TokenNotFound is canonical_TokenNotFound
        assert pd.DecryptDenied is canonical_DecryptDenied


# ===========================================================================
# TestJustificationValidation
# ===========================================================================


class TestJustificationValidation:
    """justification must be non-empty per D75 audit-grade contract."""

    def test_empty_string_rejected(self, mock_sp):
        from data_load import pii_decryptor as pd

        with pytest.raises(ValueError, match="non-empty"):
            pd.decrypt_token(token="dna-test", justification="")
        mock_sp.assert_not_called()

    def test_whitespace_only_rejected(self, mock_sp):
        from data_load import pii_decryptor as pd

        for ws in (" ", "\t", "\n", "   \t  \n  "):
            with pytest.raises(ValueError, match="non-empty"):
                pd.decrypt_token(token="dna-test", justification=ws)
        mock_sp.assert_not_called()

    def test_none_rejected(self, mock_sp):
        from data_load import pii_decryptor as pd

        with pytest.raises(ValueError):
            pd.decrypt_token(token="dna-test", justification=None)  # type: ignore[arg-type]
        mock_sp.assert_not_called()

    def test_non_str_types_rejected(self, mock_sp):
        from data_load import pii_decryptor as pd

        for bad in (42, b"bytes", ["a", "b"], {"key": "val"}, 3.14):
            with pytest.raises(ValueError):
                pd.decrypt_token(token="dna-test", justification=bad)  # type: ignore[arg-type]
        mock_sp.assert_not_called()

    def test_sp2_never_invoked_on_validation_failure(self, mock_sp):
        """No SP-2 round trip when justification is malformed.

        Audit-grade contract — the justification IS the audit-row payload;
        a missing justification means we cannot honor the audit semantics
        and must refuse the request BEFORE any server-side state changes.
        """
        from data_load import pii_decryptor as pd

        try:
            pd.decrypt_token(token="dna-test", justification="")
        except ValueError:
            pass

        try:
            pd.decrypt_token(token="dna-test", justification="   ")
        except ValueError:
            pass

        mock_sp.assert_not_called()


# ===========================================================================
# TestTokenValidation
# ===========================================================================


class TestTokenValidation:
    """token must be a non-empty string (mirrors SP-2 NOT NULL contract)."""

    def test_empty_token_rejected(self, mock_sp):
        from data_load import pii_decryptor as pd

        with pytest.raises(ValueError):
            pd.decrypt_token(token="", justification="audit reason")
        mock_sp.assert_not_called()

    def test_none_token_rejected(self, mock_sp):
        from data_load import pii_decryptor as pd

        with pytest.raises(ValueError):
            pd.decrypt_token(token=None, justification="audit reason")  # type: ignore[arg-type]
        mock_sp.assert_not_called()

    def test_non_str_token_rejected(self, mock_sp):
        from data_load import pii_decryptor as pd

        for bad in (42, b"bytes", uuid.uuid4()):
            with pytest.raises(ValueError):
                pd.decrypt_token(token=bad, justification="audit reason")  # type: ignore[arg-type]
        mock_sp.assert_not_called()


# ===========================================================================
# TestRequestIdHandling
# ===========================================================================


class TestRequestIdHandling:
    """request_id passing + auto-generation contract."""

    def test_none_auto_generates_uuid4(self, mock_sp):
        from data_load import pii_decryptor as pd

        mock_sp.return_value = _success()
        pd.decrypt_token(token="t", justification="r", request_id=None)

        sp_args = mock_sp.call_args.kwargs["sp_args"]
        parsed = uuid.UUID(sp_args["RequestId"])
        assert parsed.version == 4

    def test_explicit_uuid_passed_through_as_str(self, mock_sp):
        from data_load import pii_decryptor as pd

        fixed = uuid.UUID("12345678-1234-5678-1234-567812345678")
        mock_sp.return_value = _success()
        pd.decrypt_token(token="t", justification="r", request_id=fixed)

        sp_args = mock_sp.call_args.kwargs["sp_args"]
        # The UUID is stringified for pyodbc binding (UNIQUEIDENTIFIER).
        assert sp_args["RequestId"] == str(fixed)
        assert uuid.UUID(sp_args["RequestId"]) == fixed

    def test_non_uuid_request_id_rejected(self, mock_sp):
        from data_load import pii_decryptor as pd

        for bad in ("not-a-uuid", 42, b"bytes", ["a"], {"k": "v"}):
            with pytest.raises(ValueError):
                pd.decrypt_token(
                    token="t",
                    justification="r",
                    request_id=bad,  # type: ignore[arg-type]
                )
        mock_sp.assert_not_called()

    def test_request_id_always_str_for_sp_args(self, mock_sp):
        """pyodbc UNIQUEIDENTIFIER binding requires str (not uuid.UUID obj)."""
        from data_load import pii_decryptor as pd

        for rid in (None, uuid.uuid4(), uuid.UUID(int=0)):
            mock_sp.reset_mock()
            mock_sp.return_value = _success()
            pd.decrypt_token(token="t", justification="r", request_id=rid)
            sp_args = mock_sp.call_args.kwargs["sp_args"]
            assert isinstance(sp_args["RequestId"], str)


# ===========================================================================
# TestHappyPath
# ===========================================================================


class TestHappyPath:
    """SP-2 active-status response → return plaintext."""

    def test_single_row_dict_returns_plaintext(self, mock_sp):
        from data_load import pii_decryptor as pd

        mock_sp.return_value = _success(plaintext="real-ssn-555")
        result = pd.decrypt_token(token="t", justification="r")

        assert isinstance(result, str)
        assert result == "real-ssn-555"

    def test_multi_row_dict_first_row_wins(self, mock_sp):
        """SP-2 has UNIQUE PK on Token so multi-row shouldn't happen — but
        if a future SP-N or driver oddity produces it, take the first row
        defensively.
        """
        from data_load import pii_decryptor as pd

        mock_sp.return_value = {
            "_rows": [
                {"Token": "t", "PlaintextValue": "first"},
                {"Token": "t", "PlaintextValue": "second"},
            ]
        }
        result = pd.decrypt_token(token="t", justification="r")
        assert result == "first"

    def test_plaintext_with_unicode(self, mock_sp):
        from data_load import pii_decryptor as pd

        unicode_plain = "Müller-Lüdenscheidt"
        mock_sp.return_value = _success(plaintext=unicode_plain)
        result = pd.decrypt_token(token="t", justification="r")
        assert result == unicode_plain

    def test_plaintext_with_special_chars(self, mock_sp):
        from data_load import pii_decryptor as pd

        # Tabs, newlines, control chars — should round-trip exactly
        # (SP-2 stores the raw plaintext; we never sanitize here).
        special = "line1\nline2\ttab\x00null"
        mock_sp.return_value = _success(plaintext=special)
        result = pd.decrypt_token(token="t", justification="r")
        assert result == special

    def test_empty_string_plaintext_returned_as_empty_string(self, mock_sp):
        """Distinct from None — an empty plaintext is a valid value.

        SP-2 only returns the row for active/legal_hold_only Status; an
        empty-string plaintext means the source field was empty when
        tokenized. Distinguishing this from None (=> DecryptDenied) is
        critical for D26 audit semantics.
        """
        from data_load import pii_decryptor as pd

        mock_sp.return_value = _success(plaintext="")
        result = pd.decrypt_token(token="t", justification="r")
        assert result == ""


# ===========================================================================
# TestTokenNotFound
# ===========================================================================


class TestTokenNotFound:
    """SP-2 empty result-set → TokenNotFound (fatal, never silent None)."""

    def test_empty_dict_raises_token_not_found(self, mock_sp):
        from data_load import pii_decryptor as pd
        from utils.errors import TokenNotFound

        mock_sp.return_value = _absent()
        with pytest.raises(TokenNotFound):
            pd.decrypt_token(token="missing", justification="r")

    def test_empty_rows_list_raises_token_not_found(self, mock_sp):
        from data_load import pii_decryptor as pd
        from utils.errors import TokenNotFound

        mock_sp.return_value = {"_rows": []}
        with pytest.raises(TokenNotFound):
            pd.decrypt_token(token="missing", justification="r")

    def test_metadata_carries_token_and_request_id(self, mock_sp):
        from data_load import pii_decryptor as pd
        from utils.errors import TokenNotFound

        fixed_rid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        mock_sp.return_value = _absent()

        with pytest.raises(TokenNotFound) as exc_info:
            pd.decrypt_token(token="abc123", justification="r", request_id=fixed_rid)

        assert exc_info.value.metadata["token"] == "abc123"
        assert exc_info.value.metadata["request_id"] == str(fixed_rid)

    def test_token_not_found_is_fatal(self):
        """TokenNotFound is a PipelineFatalError per D68 hierarchy."""
        from utils.errors import PipelineFatalError, TokenNotFound

        assert issubclass(TokenNotFound, PipelineFatalError)


# ===========================================================================
# TestDecryptDenied
# ===========================================================================


class TestDecryptDenied:
    """SP-2 returns row with NULL plaintext → DecryptDenied (CCPA per RB-10).

    Closes B103 (Round 6 § 7.9 resolution).
    """

    def test_null_plaintext_raises_decrypt_denied(self, mock_sp):
        from data_load import pii_decryptor as pd
        from utils.errors import DecryptDenied

        mock_sp.return_value = _denied(token="deleted-token")
        with pytest.raises(DecryptDenied):
            pd.decrypt_token(token="deleted-token", justification="r")

    def test_metadata_carries_token_and_request_id(self, mock_sp):
        from data_load import pii_decryptor as pd
        from utils.errors import DecryptDenied

        fixed_rid = uuid.UUID("87654321-4321-8765-4321-876543218765")
        mock_sp.return_value = _denied(token="deleted-token")

        with pytest.raises(DecryptDenied) as exc_info:
            pd.decrypt_token(
                token="deleted-token", justification="r", request_id=fixed_rid
            )

        assert exc_info.value.metadata["token"] == "deleted-token"
        assert exc_info.value.metadata["request_id"] == str(fixed_rid)

    def test_decrypt_denied_is_fatal(self):
        """DecryptDenied is a PipelineFatalError per D68 hierarchy."""
        from utils.errors import DecryptDenied, PipelineFatalError

        assert issubclass(DecryptDenied, PipelineFatalError)

    def test_multi_row_with_null_plaintext_raises(self, mock_sp):
        """Defensive: multi-row result with NULL on first row → DecryptDenied."""
        from data_load import pii_decryptor as pd
        from utils.errors import DecryptDenied

        mock_sp.return_value = {
            "_rows": [
                {"Token": "deleted", "PlaintextValue": None},
            ]
        }
        with pytest.raises(DecryptDenied):
            pd.decrypt_token(token="deleted", justification="r")


# ===========================================================================
# TestVaultUnavailableBubble
# ===========================================================================


class TestVaultUnavailableBubble:
    """M6 retryable + fatal errors bubble up unchanged.

    M5 does NOT catch / translate / retry — M6 owns the retry policy
    (B-7); M5 is a thin spec-shaped wrapper.
    """

    def test_vault_unavailable_bubbles_up(self, mock_sp):
        from data_load import pii_decryptor as pd
        from utils.errors import VaultUnavailable

        mock_sp.side_effect = VaultUnavailable(
            "vault DB connection lost",
            metadata={"attempts": 3},
        )

        with pytest.raises(VaultUnavailable) as exc_info:
            pd.decrypt_token(token="t", justification="r")

        # Original exception bubbled up unchanged — metadata preserved.
        assert exc_info.value.metadata == {"attempts": 3}

    def test_vault_config_error_bubbles_up(self, mock_sp):
        from data_load import pii_decryptor as pd
        from utils.errors import VaultConfigError

        mock_sp.side_effect = VaultConfigError(
            "VAULT_DB_PASSWORD missing",
            metadata={"missing_env_key": "VAULT_DB_PASSWORD"},
        )

        with pytest.raises(VaultConfigError) as exc_info:
            pd.decrypt_token(token="t", justification="r")

        assert exc_info.value.metadata["missing_env_key"] == "VAULT_DB_PASSWORD"

    def test_pipeline_fatal_error_bubbles_up(self, mock_sp):
        """FK / CHECK violations from M6 surface as PipelineFatalError."""
        from data_load import pii_decryptor as pd
        from utils.errors import PipelineFatalError

        mock_sp.side_effect = PipelineFatalError(
            "FK violation on PiiVaultAccessLog",
            metadata={"sql_error_code": 547},
        )

        with pytest.raises(PipelineFatalError):
            pd.decrypt_token(token="t", justification="r")


# ===========================================================================
# TestLogSafety
# ===========================================================================


class TestLogSafety:
    """D103 — plaintext + justification VALUES never appear in log records."""

    def test_plaintext_value_not_in_logs_on_success(self, mock_sp, caplog):
        from data_load import pii_decryptor as pd

        secret = "secret-ssn-12345-6789-PII"
        mock_sp.return_value = _success(plaintext=secret)

        with caplog.at_level(logging.DEBUG, logger="data_load.pii_decryptor"):
            pd.decrypt_token(token="t", justification="audit reason — case 1234")

        for record in caplog.records:
            assert secret not in record.getMessage()

    def test_justification_value_not_in_logs(self, mock_sp, caplog):
        from data_load import pii_decryptor as pd

        # Justification could (rarely) contain operator-pasted PII; we
        # NEVER echo its value into logs — only its length.
        justification = "audit request — SSN 555-12-3456 referenced"
        mock_sp.return_value = _success()

        with caplog.at_level(logging.DEBUG, logger="data_load.pii_decryptor"):
            pd.decrypt_token(token="t", justification=justification)

        for record in caplog.records:
            # The justification *value* must not leak; the length is fine.
            assert justification not in record.getMessage()
            assert "555-12-3456" not in record.getMessage()
            # Length still acceptable to log.
            # (Length numeric form like 'justification_length=42' is OK.)

    def test_token_appears_in_logs(self, mock_sp, caplog):
        """Token IS expected in logs — it's a non-sensitive hex identifier."""
        from data_load import pii_decryptor as pd

        mock_sp.return_value = _success()

        with caplog.at_level(logging.INFO, logger="data_load.pii_decryptor"):
            pd.decrypt_token(token="abc123def456", justification="r")

        log_text = " ".join(r.getMessage() for r in caplog.records)
        assert "abc123def456" in log_text

    def test_plaintext_not_in_logs_on_token_not_found(self, mock_sp, caplog):
        from data_load import pii_decryptor as pd
        from utils.errors import TokenNotFound

        mock_sp.return_value = _absent()

        with caplog.at_level(logging.DEBUG, logger="data_load.pii_decryptor"):
            with pytest.raises(TokenNotFound):
                pd.decrypt_token(token="missing", justification="r")

        for record in caplog.records:
            # No plaintext value should appear — there's no plaintext, but
            # defensive against future regression that might log the
            # SP result dict directly.
            assert "PlaintextValue" not in record.getMessage()

    def test_plaintext_not_in_logs_on_decrypt_denied(self, mock_sp, caplog):
        from data_load import pii_decryptor as pd
        from utils.errors import DecryptDenied

        mock_sp.return_value = _denied()

        with caplog.at_level(logging.DEBUG, logger="data_load.pii_decryptor"):
            with pytest.raises(DecryptDenied):
                pd.decrypt_token(token="deleted", justification="r")

        # No plaintext was returned (it's NULL); no exposure risk here,
        # but defensive — sp_result dict should not be echoed.
        for record in caplog.records:
            assert "PlaintextValue" not in record.getMessage()


# ===========================================================================
# TestSpArgsContract
# ===========================================================================


class TestSpArgsContract:
    """The composed M6 call must use the canonical SP-2 sp_args shape."""

    def test_sp_name_is_pii_vault_decrypt(self, mock_sp):
        from data_load import pii_decryptor as pd

        mock_sp.return_value = _success()
        pd.decrypt_token(token="t", justification="r")

        assert mock_sp.call_args.args[0] == "PiiVault_Decrypt"

    def test_sp_args_keys_match_sp2_signature(self, mock_sp):
        """Exactly {RequestId, Token, Justification} — no extras."""
        from data_load import pii_decryptor as pd

        mock_sp.return_value = _success()
        pd.decrypt_token(token="t", justification="r")

        sp_args = mock_sp.call_args.kwargs["sp_args"]
        assert set(sp_args.keys()) == {"RequestId", "Token", "Justification"}

    def test_token_and_justification_passed_through_verbatim(self, mock_sp):
        from data_load import pii_decryptor as pd

        mock_sp.return_value = _success()
        pd.decrypt_token(token="my-token-hex", justification="case 1234 audit")

        sp_args = mock_sp.call_args.kwargs["sp_args"]
        assert sp_args["Token"] == "my-token-hex"
        assert sp_args["Justification"] == "case 1234 audit"


# ===========================================================================
# TestIdempotency
# ===========================================================================


class TestIdempotency:
    """Two consecutive decrypts → two M6 calls (no client-side caching)."""

    def test_two_calls_produce_two_sp2_invocations(self, mock_sp):
        """Every decrypt is a separate audit event per D26 append-only."""
        from data_load import pii_decryptor as pd

        mock_sp.return_value = _success(plaintext="value")
        pd.decrypt_token(token="t", justification="r1")
        pd.decrypt_token(token="t", justification="r2")

        assert mock_sp.call_count == 2

    def test_same_token_same_plaintext_returned(self, mock_sp):
        """Idempotent server-side — same Token returns same plaintext.

        The audit log row count grows by 1 per call (server-side); this
        test verifies the CLIENT-SIDE return value is the same when SP-2
        returns the same value across two invocations.
        """
        from data_load import pii_decryptor as pd

        mock_sp.return_value = _success(plaintext="constant-value")
        first = pd.decrypt_token(token="t", justification="r1")
        second = pd.decrypt_token(token="t", justification="r2")

        assert first == second == "constant-value"

    def test_explicit_request_id_reused_passes_through_twice(self, mock_sp):
        """Reusing the same RequestId is operator's choice — module
        doesn't dedupe; SP-2 doesn't dedupe either (audit log has IDENTITY
        PK; UNIQUE constraint on (RequestId, AccessedAt) is NOT enforced
        per § 1.19 DDL).
        """
        from data_load import pii_decryptor as pd

        fixed = uuid.UUID("12345678-1234-5678-1234-567812345678")
        mock_sp.return_value = _success()
        pd.decrypt_token(token="t", justification="r1", request_id=fixed)
        pd.decrypt_token(token="t", justification="r2", request_id=fixed)

        assert mock_sp.call_count == 2
        # Both calls used the same RequestId.
        ids = [c.kwargs["sp_args"]["RequestId"] for c in mock_sp.call_args_list]
        assert ids == [str(fixed), str(fixed)]


# ===========================================================================
# TestPlaintextCoercion
# ===========================================================================


class TestPlaintextCoercion:
    """Defensive coercion when SP-2 driver returns non-str plaintext.

    SP-2 declares ``PlaintextValue VARCHAR`` so pyodbc normally yields
    Python ``str``. A driver oddity could return bytes / bytearray; we
    decode UTF-8 defensively. Non-decodable bytes → DecryptDenied
    (rather than silent corruption).
    """

    def test_bytes_plaintext_decoded_utf8(self, mock_sp):
        from data_load import pii_decryptor as pd

        mock_sp.return_value = {
            "Token": "t",
            "PlaintextValue": "café".encode("utf-8"),
        }
        result = pd.decrypt_token(token="t", justification="r")
        assert result == "café"

    def test_bytearray_plaintext_decoded_utf8(self, mock_sp):
        from data_load import pii_decryptor as pd

        mock_sp.return_value = {
            "Token": "t",
            "PlaintextValue": bytearray("data".encode("utf-8")),
        }
        result = pd.decrypt_token(token="t", justification="r")
        assert result == "data"

    def test_non_decodable_bytes_raises_decrypt_denied(self, mock_sp):
        from data_load import pii_decryptor as pd
        from utils.errors import DecryptDenied

        # 0xFF is invalid UTF-8 in single-byte context.
        mock_sp.return_value = {
            "Token": "t",
            "PlaintextValue": b"\xff\xfe\xff",
        }
        with pytest.raises(DecryptDenied):
            pd.decrypt_token(token="t", justification="r")
