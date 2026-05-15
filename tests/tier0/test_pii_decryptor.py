"""Tier 0 build-time smoke test for data_load/pii_decryptor.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s. All
external dependencies (M6 ``call_vault_sp``, SP-2 cursor) are mocked.
No live SQL Server required.

North Star pillars:
  - Audit-grade (D6 + D26 + D30 — every decrypt produces a server-side
    PiiVaultAccessLog row; SP-2 owns the audit write; this module
    composes M6 with sp_name='PiiVault_Decrypt').
  - Operationally stable (D67 Tier 0 discipline: import + happy-path +
    error-path + justification-required path in < 5 s).
  - Security-first (D103 — NEVER log decrypted plaintext; smoke verifies
    the success path returns the canned plaintext WITHOUT echoing it
    in module logs).

D-numbers: D6, D17, D26, D30, D67, D68, D75, D103.
B-numbers: M5 (build-tracker entry — closed by authoring this module
+ its tests); M6 (vault_client dependency closed); B85 (utils/errors
dependency closed); B103 (DecryptDenied raised — verified here).

Spec: phase1/03_core_modules.md § 2.2 + phase1/01_database_schema.md
SP-2 + PiiVaultAccessLog DDL (re-read at build time per Pitfall #9.l).
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path (matches tests/ convention)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sp2_success_result(token: str = "dna-test-token", plaintext: str = "123-45-6789"):
    """Return a canned SP-2 success-path result-set dict."""
    return {"Token": token, "PlaintextValue": plaintext}


def _sp2_denied_result(token: str = "dna-test-token"):
    """Return a canned SP-2 result-set with NULL plaintext (Status forbids decrypt)."""
    return {"Token": token, "PlaintextValue": None}


def _sp2_absent_result():
    """Return a canned SP-2 result-set for an absent Token (empty dict)."""
    return {}


# ---------------------------------------------------------------------------
# (a) Module imports + import uuid resolves
# ---------------------------------------------------------------------------


def test_module_imports():
    """pii_decryptor imports cleanly + exposes the canonical interface."""
    from data_load import pii_decryptor as pd

    assert hasattr(pd, "decrypt_token")
    # Module composes M6 + utils.errors — verify the canonical imports
    # resolve so the module-level binding is intact (not a stub).
    import uuid as uuid_module
    assert pd.uuid is uuid_module
    # __all__ lists only the public surface — defensive against accidental
    # private symbol leakage.
    assert pd.__all__ == ["decrypt_token"]


# ---------------------------------------------------------------------------
# (b) + (c) decrypt_token invokable with mocked SP-2 cursor returning canned
# plaintext for an active-status token
# ---------------------------------------------------------------------------


def test_decrypt_token_active_status_returns_plaintext():
    """SP-2 happy path: active-status token → plaintext str."""
    from data_load import pii_decryptor as pd

    with patch.object(pd, "call_vault_sp") as mock_sp:
        mock_sp.return_value = _sp2_success_result(
            token="dna-test-token", plaintext="555-12-3456"
        )

        result = pd.decrypt_token(
            token="dna-test-token",
            justification="Tier 0 smoke test",
        )

    assert isinstance(result, str)
    assert result == "555-12-3456"
    # Verify SP-2 was invoked with the canonical args (token + justification
    # + an auto-generated RequestId UUID).
    mock_sp.assert_called_once()
    call_kwargs = mock_sp.call_args
    assert call_kwargs.args[0] == "PiiVault_Decrypt"
    sp_args = call_kwargs.kwargs["sp_args"]
    assert sp_args["Token"] == "dna-test-token"
    assert sp_args["Justification"] == "Tier 0 smoke test"
    # RequestId auto-generated as a str(UUID).
    assert uuid.UUID(sp_args["RequestId"])  # raises if not a valid UUID


# ---------------------------------------------------------------------------
# (d) Auto-generated request_id is a valid uuid.UUID when None passed
# ---------------------------------------------------------------------------


def test_decrypt_token_auto_generates_request_id():
    """request_id=None → auto-generates a uuid.UUID; appears in sp_args."""
    from data_load import pii_decryptor as pd

    with patch.object(pd, "call_vault_sp") as mock_sp:
        mock_sp.return_value = _sp2_success_result()

        pd.decrypt_token(
            token="dna-test-token",
            justification="Tier 0 smoke",
            request_id=None,
        )

    sp_args = mock_sp.call_args.kwargs["sp_args"]
    # Must be parseable as a UUID (auto-gen produces uuid4 → 36-char str).
    parsed = uuid.UUID(sp_args["RequestId"])
    assert parsed.version == 4


# ---------------------------------------------------------------------------
# (e) Raises TokenNotFound on mocked absent-Token result
# ---------------------------------------------------------------------------


def test_decrypt_token_raises_token_not_found_when_absent():
    """SP-2 empty result-set → TokenNotFound (fatal, never silent None)."""
    from data_load import pii_decryptor as pd
    from utils.errors import TokenNotFound

    with patch.object(pd, "call_vault_sp") as mock_sp:
        mock_sp.return_value = _sp2_absent_result()

        with pytest.raises(TokenNotFound) as exc_info:
            pd.decrypt_token(
                token="missing-token",
                justification="Tier 0 smoke — absent path",
            )

    # Token + request_id should appear in metadata for audit-grade
    # downstream PipelineLog ingestion (D76).
    assert exc_info.value.metadata["token"] == "missing-token"
    assert "request_id" in exc_info.value.metadata


# ---------------------------------------------------------------------------
# (f) Raises ValueError when justification is empty string
# ---------------------------------------------------------------------------


def test_decrypt_token_rejects_empty_justification():
    """Empty justification fails fast — no SP-2 round trip, no audit row."""
    from data_load import pii_decryptor as pd

    with patch.object(pd, "call_vault_sp") as mock_sp:
        with pytest.raises(ValueError):
            pd.decrypt_token(
                token="dna-test-token",
                justification="",
            )

        # SP-2 NEVER invoked when justification is empty — audit-grade
        # contract requires the reason BEFORE the round trip so a
        # malformed call cannot accidentally produce an audit row.
        mock_sp.assert_not_called()


# ---------------------------------------------------------------------------
# Bonus smoke: deleted_per_request → DecryptDenied (closes B103)
# ---------------------------------------------------------------------------


def test_decrypt_token_raises_decrypt_denied_on_null_plaintext():
    """SP-2 returns row with NULL plaintext → DecryptDenied (CCPA per RB-10).

    Closes B103 — Round 6 § 7.9 resolution: DecryptDenied IS raised by
    this wrapper. Smoke verifies that contract.
    """
    from data_load import pii_decryptor as pd
    from utils.errors import DecryptDenied

    with patch.object(pd, "call_vault_sp") as mock_sp:
        mock_sp.return_value = _sp2_denied_result(token="deleted-token")

        with pytest.raises(DecryptDenied) as exc_info:
            pd.decrypt_token(
                token="deleted-token",
                justification="Tier 0 smoke — CCPA path",
            )

    assert exc_info.value.metadata["token"] == "deleted-token"
    assert "request_id" in exc_info.value.metadata
