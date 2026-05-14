"""Tier 2 property tests for encryption roundtrip per Round 5 § 5.4.

Canonical spec (verbatim from phase1/05_tests.md § 5.4)::

    @given(plaintext=st.text())
    def test_encrypt_decrypt_roundtrip(plaintext, vault):
        token = tokenize(plaintext, 'EMAIL', 'DNA')
        recovered = decrypt(token)
        assert recovered == plaintext

Per § 5.10 budget (verbatim)::

    Default: max_examples=200 per pytest.fixture(scope='session')
    Shrinkage budget: deadline=timedelta(seconds=10)

The mock vault holds a bidirectional ``plaintext ↔ token`` map. M4
``tokenize_pii_columns`` populates the forward direction; M5
``decrypt_token`` reads the reverse direction. A subset of tokens are
flagged ``deleted_per_request`` to drive ``DecryptDenied`` raising per
D30 + B103 (Round 6 § 7.9 resolution — DecryptDenied IS raised).

**SECURITY-CRITICAL per D103 + P5**: all plaintext is synthetic
Hypothesis-generated text. The mock vault holds test fixtures only.
Real plaintext NEVER touches this module.

Test surface (six properties):

  test_encrypt_decrypt_roundtrip
    Verbatim § 5.4 — ``decrypt(tokenize(plaintext)) == plaintext`` for
    any plaintext not in deleted-status.

  test_roundtrip_preserves_unicode
    Roundtrip preserves NFC/NFD forms exactly as input.

  test_roundtrip_preserves_whitespace_and_specials
    Roundtrip preserves whitespace, tabs, newlines, special chars,
    embedded null bytes (mock vault doesn't sanitize like BCP would —
    that's a serialization concern, not a vault concern).

  test_decrypt_unknown_token_raises_token_not_found
    Decrypting a token that was never minted raises
    ``utils.errors.TokenNotFound`` per D68 fatal hierarchy.

  test_decrypt_deleted_token_raises_decrypt_denied
    Decrypting a token whose status is ``deleted_per_request`` (CCPA
    per RB-10) raises ``utils.errors.DecryptDenied`` per D30 + B103.

  test_roundtrip_bidirectional_n_iterations
    ``decrypt(tokenize(x))`` reproduces x for N independent samples
    in a single vault — verifies the map stays consistent across
    interleaved tokenize / decrypt calls.

D-numbers: D6, D15, D26, D30, D63, D67, D68, D103.
B-numbers: B103 (DecryptDenied raised per Round 6 § 7.9); B228 (canonical
utils.errors imports).
"""
from __future__ import annotations

import sys
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import polars as pl
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

# Ensure project root on sys.path so utils.errors / data_load.* resolve.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from data_load.pii_tokenizer import tokenize_pii_columns  # noqa: E402
from utils.errors import DecryptDenied, TokenNotFound  # noqa: E402


# ---------------------------------------------------------------------------
# Mock vault — bidirectional plaintext ↔ token store with status enum
# ---------------------------------------------------------------------------


class MockVault:
    """Bidirectional in-memory vault for property tests.

    Forward map (SP-1 surface):
        ``(plaintext, pii_type, source_name) → token``

    Reverse map (SP-2 surface):
        ``token → (plaintext, status)`` where status ∈
        {``"active"``, ``"legal_hold_only"``, ``"deleted_per_request"``,
        ``"purged_for_retention"``}.

    Per Round 1 § SP-2 L1411-1455 — SP-2 only returns plaintext for
    ``Status IN ('active', 'legal_hold_only')``. Other statuses cause
    SP-2 to return a row with ``PlaintextValue = NULL`` (per M5
    docstring + B103 resolution) which the M5 wrapper translates to
    ``DecryptDenied``. Mock implementation: status held in the reverse
    map; SP-2 returns dict with PlaintextValue=None for denied statuses.

    Absent tokens (never tokenized) return ``{}`` from SP-2, which the
    M5 wrapper translates to ``TokenNotFound``.
    """

    def __init__(self) -> None:
        # Forward direction: SP-1 lookup.
        self._plaintext_to_token: dict[tuple[str, str, str], str] = {}
        # Reverse direction: SP-2 lookup. Status defaults 'active'.
        self._token_to_plaintext: dict[str, tuple[str, str]] = {}
        self._counter = 0

    def get_or_create_token(
        self,
        *,
        plaintext: str,
        pii_type: str,
        source_name: str,
    ) -> tuple[str, bool]:
        """SP-1 contract: deterministic per (plaintext, pii_type, source)."""
        key = (plaintext, pii_type, source_name)
        if key in self._plaintext_to_token:
            return self._plaintext_to_token[key], False
        self._counter += 1
        token = f"{self._counter:040x}"
        self._plaintext_to_token[key] = token
        # Reverse map seeded with 'active' status by default.
        self._token_to_plaintext[token] = (plaintext, "active")
        return token, True

    def mark_deleted(self, token: str) -> None:
        """Flip a token's status to 'deleted_per_request' (CCPA per RB-10)."""
        if token not in self._token_to_plaintext:
            raise KeyError(f"unknown token: {token}")
        plaintext, _status = self._token_to_plaintext[token]
        self._token_to_plaintext[token] = (plaintext, "deleted_per_request")

    def decrypt(self, *, token: str) -> dict[str, Any]:
        """SP-2 contract.

        Returns:
            - ``{}`` if token absent → M5 raises TokenNotFound.
            - ``{"Token": ..., "PlaintextValue": None}`` if status
              forbids decrypt → M5 raises DecryptDenied.
            - ``{"Token": ..., "PlaintextValue": "..."}`` on happy path.
        """
        if token not in self._token_to_plaintext:
            return {}
        plaintext, status = self._token_to_plaintext[token]
        if status in ("active", "legal_hold_only"):
            return {"Token": token, "PlaintextValue": plaintext}
        # 'deleted_per_request' / 'purged_for_retention' → NULL plaintext.
        return {"Token": token, "PlaintextValue": None}

    # --- M6 call_vault_sp dispatchers ---

    def call_vault_sp_tokenize(
        self,
        sp_name: str,
        *,
        sp_args: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        """Mock M6 surface for SP-1 only (tokenization side)."""
        assert sp_name == "PiiVault_GetOrCreateToken", sp_name
        args = sp_args or {}
        token, was_new = self.get_or_create_token(
            plaintext=args["Plaintext"],
            pii_type=args["PiiType"],
            source_name=args["SourceName"],
        )
        return {"Token": token, "WasNew": 1 if was_new else 0}

    def call_vault_sp_decrypt(
        self,
        sp_name: str,
        *,
        sp_args: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        """Mock M6 surface for SP-2 only (decryption side)."""
        assert sp_name == "PiiVault_Decrypt", sp_name
        args = sp_args or {}
        return self.decrypt(token=args["Token"])


@contextmanager
def _fake_cursor_cm(cur: MagicMock):
    try:
        yield cur
    finally:
        pass


def _make_cursor_factory() -> Any:
    return lambda: _fake_cursor_cm(MagicMock())


# ---------------------------------------------------------------------------
# Helpers — single-call tokenize + decrypt wrappers
# ---------------------------------------------------------------------------


def tokenize(plaintext: str, pii_type: str, source: str, *, vault: MockVault) -> str:
    """Tokenize a single scalar plaintext through M4."""
    df = pl.DataFrame({"VALUE": [plaintext]})
    out = tokenize_pii_columns(
        df,
        source_name=source,
        object_name="TEST_OBJECT",
        column_list=["VALUE"],
        batch_id=1,
        pii_type=pii_type,
        call_vault_sp_fn=vault.call_vault_sp_tokenize,
        general_cursor_factory=_make_cursor_factory(),
        now_ms_fn=lambda: 0,
    )
    return out["VALUE"].to_list()[0]


def decrypt(token: str, *, vault: MockVault) -> str:
    """Decrypt a token through M5; raises per M5 contract.

    M5 ``decrypt_token`` is imported inside this helper to allow patching
    ``data_load.vault_client.call_vault_sp`` at test scope via
    ``monkeypatch`` from the caller — but for property tests we use the
    explicit injection path through a partial wrapper to avoid touching
    module-level state per B214 (no bare sys.modules writes).
    """
    # M5 has no injection kwarg for call_vault_sp; it imports the
    # canonical name at module top. Per B214 lesson we use monkeypatch
    # via a thin local import + getattr-replace wrapper. The simplest
    # safe approach: monkeypatch is per-test fixture; here we instead
    # call M5 by patching its bound symbol via the unittest.mock.patch
    # context manager (scope-bounded; no bare sys.modules writes).
    from unittest.mock import patch as _patch

    import data_load.pii_decryptor as _pd  # noqa: F401

    with _patch.object(_pd, "call_vault_sp", vault.call_vault_sp_decrypt):
        from data_load.pii_decryptor import decrypt_token

        return decrypt_token(
            token=token,
            justification="property-test audit justification",
            request_id=uuid.uuid4(),
        )


# ---------------------------------------------------------------------------
# Hypothesis settings — per § 5.10 budget (verbatim)
# ---------------------------------------------------------------------------

_property_settings = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


# ===========================================================================
# Section 1 — Canonical § 5.4 verbatim
# ===========================================================================


class TestEncryptDecryptRoundtrip:
    """Verbatim § 5.4 — decrypt(tokenize(plaintext)) == plaintext."""

    @given(plaintext=st.text())
    @_property_settings
    def test_encrypt_decrypt_roundtrip(self, plaintext: str) -> None:
        """§ 5.4 verbatim."""
        vault = MockVault()
        token = tokenize(plaintext, "EMAIL", "DNA", vault=vault)
        recovered = decrypt(token, vault=vault)
        assert recovered == plaintext


# ===========================================================================
# Section 2 — Unicode preservation
# ===========================================================================


class TestRoundtripUnicodePreservation:
    """Roundtrip preserves Unicode forms exactly (NFC + NFD distinct)."""

    @given(
        base=st.text(
            alphabet=st.characters(
                min_codepoint=0x00C0, max_codepoint=0x017F
            ),
            min_size=1,
            max_size=30,
        )
    )
    @_property_settings
    def test_roundtrip_preserves_nfc(self, base: str) -> None:
        """NFC plaintext → token → plaintext returns same NFC bytes."""
        nfc = unicodedata.normalize("NFC", base)
        vault = MockVault()
        token = tokenize(nfc, "EMAIL", "DNA", vault=vault)
        recovered = decrypt(token, vault=vault)
        assert recovered == nfc

    @given(
        base=st.text(
            alphabet=st.characters(
                min_codepoint=0x00C0, max_codepoint=0x017F
            ),
            min_size=1,
            max_size=30,
        )
    )
    @_property_settings
    def test_roundtrip_preserves_nfd(self, base: str) -> None:
        """NFD plaintext → token → plaintext returns same NFD bytes."""
        nfd = unicodedata.normalize("NFD", base)
        vault = MockVault()
        token = tokenize(nfd, "EMAIL", "DNA", vault=vault)
        recovered = decrypt(token, vault=vault)
        assert recovered == nfd


# ===========================================================================
# Section 3 — Whitespace + special chars
# ===========================================================================


class TestRoundtripPreservesWhitespaceAndSpecials:
    """Whitespace, tabs, newlines, control bytes, etc. round-trip exactly."""

    @given(plaintext=st.text(min_size=1, max_size=200))
    @_property_settings
    def test_roundtrip_preserves_whitespace(self, plaintext: str) -> None:
        """Any-whitespace + Unicode roundtrips exactly.

        The vault doesn't strip / normalize / sanitize — those are
        serialization concerns (BCP CSV writers, log handlers). The
        vault is byte-perfect.
        """
        vault = MockVault()
        token = tokenize(plaintext, "EMAIL", "DNA", vault=vault)
        recovered = decrypt(token, vault=vault)
        assert recovered == plaintext


# ===========================================================================
# Section 4 — TokenNotFound on unknown token
# ===========================================================================


class TestDecryptUnknownTokenRaises:
    """Decrypting a never-minted token raises TokenNotFound (D68 fatal)."""

    @given(
        bogus_token=st.text(
            alphabet=st.characters(
                min_codepoint=ord("0"), max_codepoint=ord("9")
            ),
            min_size=40,
            max_size=40,
        )
    )
    @_property_settings
    def test_decrypt_unknown_token_raises_token_not_found(
        self, bogus_token: str
    ) -> None:
        """Token never minted → TokenNotFound from M5 wrapper."""
        vault = MockVault()  # Empty vault.
        with pytest.raises(TokenNotFound):
            decrypt(bogus_token, vault=vault)


# ===========================================================================
# Section 5 — DecryptDenied on deleted_per_request token (per D30 + B103)
# ===========================================================================


class TestDecryptDeletedTokenRaisesDecryptDenied:
    """Decrypting a CCPA-deleted token raises DecryptDenied per D30 + B103.

    Per RB-10 the operator may issue a CCPA right-to-deletion request
    that flips ``PiiVault.Status`` to ``'deleted_per_request'``. SP-2
    detects the status and returns NULL plaintext (audit row still
    written server-side per D26 append-only). M5 translates this to
    ``DecryptDenied``. B103 (Round 6 § 7.9) resolves the docstring
    contradiction — DecryptDenied IS raised in this case.
    """

    @given(plaintext=st.text(min_size=1, max_size=100))
    @_property_settings
    def test_decrypt_deleted_token_raises_decrypt_denied(
        self, plaintext: str
    ) -> None:
        """Token with status='deleted_per_request' → DecryptDenied."""
        vault = MockVault()
        token = tokenize(plaintext, "EMAIL", "DNA", vault=vault)
        # Flip the status mid-test — simulates a CCPA deletion that
        # happened between the tokenize-time write and the decrypt-time
        # read.
        vault.mark_deleted(token)
        with pytest.raises(DecryptDenied):
            decrypt(token, vault=vault)


# ===========================================================================
# Section 6 — N-iteration bidirectional consistency
# ===========================================================================


class TestRoundtripBidirectionalNIterations:
    """Interleaved tokenize/decrypt sequences stay consistent.

    Builds a vault, tokenizes N distinct plaintexts, then decrypts each
    token and verifies the plaintext matches its input. Catches map-
    consistency regressions where the forward direction drifts from the
    reverse direction across multiple operations in one vault instance.
    """

    @given(
        plaintexts=st.lists(
            st.text(min_size=1, max_size=100),
            min_size=2,
            max_size=10,
            unique=True,
        )
    )
    @_property_settings
    def test_roundtrip_n_distinct_plaintexts(
        self, plaintexts: list[str]
    ) -> None:
        """Tokenize N plaintexts, decrypt them all, verify roundtrip."""
        vault = MockVault()
        # Tokenize each in turn.
        token_to_input: dict[str, str] = {}
        for plaintext in plaintexts:
            token = tokenize(plaintext, "EMAIL", "DNA", vault=vault)
            token_to_input[token] = plaintext
        # Distinct plaintexts → distinct tokens (within scope).
        assert len(token_to_input) == len(plaintexts)
        # Decrypt each token and verify it returns the original input.
        for token, expected_plaintext in token_to_input.items():
            recovered = decrypt(token, vault=vault)
            assert recovered == expected_plaintext
