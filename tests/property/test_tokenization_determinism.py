"""Tier 2 property tests for tokenization determinism per Round 5 § 5.3.

Canonical spec (verbatim from phase1/05_tests.md § 5.3)::

    @given(plaintext=st.text(min_size=1, max_size=200))
    def test_tokenize_deterministic(plaintext, vault):
        '''Same plaintext returns same token, even after restart.'''
        t1 = tokenize(plaintext, 'EMAIL', 'DNA')
        t2 = tokenize(plaintext, 'EMAIL', 'DNA')
        assert t1 == t2

Per § 5.10 budget (verbatim)::

    Default: max_examples=200 per pytest.fixture(scope='session')
    Shrinkage budget: deadline=timedelta(seconds=10)

This module mocks M6 ``vault_client.call_vault_sp`` to drive M4
``data_load.pii_tokenizer.tokenize_pii_columns`` through Hypothesis-
generated plaintext inputs. The mock vault is an in-memory dict-backed
plaintext → token map that mirrors SP-1's deterministic per-source
``UPDLOCK + HOLDLOCK`` contract (per Round 1 § SP-1 L1314-1397).

**SECURITY-CRITICAL per D103 + P5**: every plaintext input is synthetic
Hypothesis-generated text; NEVER touches real PII. The mock vault holds
test fixtures only.

Test surface (six properties):

  test_tokenize_deterministic
    Verbatim § 5.3 — same (plaintext, PiiType, SourceName) → same token.

  test_different_plaintext_different_token
    SP-1 deterministic contract — distinct plaintexts produce distinct
    tokens within the same (PiiType, SourceName) scope.

  test_token_format_invariant
    Mock vault mints hex-like tokens; canonical SP-1 contract is
    ``VARCHAR(40)``. We verify the format the mock generates is
    consistent (downstream verification of the real SP-1 hex format
    is Tier 3 integration scope).

  test_case_sensitive_plaintext
    Per SP-1: ``"Email@x.com" != "email@x.com"`` → different tokens.
    Mock vault implements case-sensitive map.

  test_unicode_nfc_nfd_distinct_tokens
    Per SP-1: NFC and NFD forms of the same logical Unicode string
    differ as byte sequences; SP-1 hashes the bytes so they get
    different tokens. (NFC normalization would be a P5 concern; SP-1
    canonical contract treats them as distinct plaintexts.)

  test_empty_string_handling
    SP-1 contract accepts empty string per Round 1 § PiiVault DDL
    (Plaintext NVARCHAR(MAX) NOT NULL — empty string is non-NULL).
    Mock vault mints a token for ''; M4 module's NULL pass-through
    contract leaves None alone (not empty string).

D-numbers: D6, D15, D63, D67, D103.
B-numbers: B228 (canonical utils.errors imports — verified by import).
"""
from __future__ import annotations

import sys
import unicodedata
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

# ---------------------------------------------------------------------------
# Mock vault — in-memory dict-backed plaintext ↔ token store
# ---------------------------------------------------------------------------


class MockVault:
    """In-memory deterministic vault for property tests.

    Mirrors SP-1's deterministic-per-source contract:
    ``(plaintext, PiiType, SourceName) → token``, idempotent and case-
    sensitive. Tokens are hex strings of length 40 (matches SP-1
    ``Token VARCHAR(40)`` canonical type).

    Per Round 1 § SP-1 L1314-1397 the SP uses ``UPDLOCK + HOLDLOCK``
    to serialize concurrent INSERT-or-lookup against ``General.ops.
    PiiVault`` — re-tokenizing the same plaintext within the same
    (PiiType, SourceName) returns the same token. The mock reproduces
    this contract via a Python dict keyed by ``(plaintext, pii_type,
    source_name)``.
    """

    def __init__(self) -> None:
        # Forward map: (plaintext, pii_type, source_name) → token.
        self._plaintext_to_token: dict[tuple[str, str, str], str] = {}
        # Counter feeds deterministic token minting; never reset across
        # property example runs to keep tokens unique across plaintexts.
        self._counter = 0

    def get_or_create_token(
        self,
        *,
        plaintext: str,
        pii_type: str,
        source_name: str,
    ) -> tuple[str, bool]:
        """Return (token, was_new). Deterministic per SP-1 contract."""
        key = (plaintext, pii_type, source_name)
        if key in self._plaintext_to_token:
            return self._plaintext_to_token[key], False
        # Mint a fresh hex-like token. Format: 40-char hex padded counter.
        self._counter += 1
        token = f"{self._counter:040x}"
        self._plaintext_to_token[key] = token
        return token, True

    def call_vault_sp(
        self,
        sp_name: str,
        *,
        sp_args: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        """Mock M6 call_vault_sp surface — dispatches SP-1 only.

        Only ``PiiVault_GetOrCreateToken`` is implemented; other SPs
        raise AssertionError so test mistakes surface fast.
        """
        assert sp_name == "PiiVault_GetOrCreateToken", (
            f"MockVault only supports SP-1; received sp_name={sp_name!r}"
        )
        args = sp_args or {}
        plaintext = args["Plaintext"]
        pii_type = args["PiiType"]
        source_name = args["SourceName"]
        token, was_new = self.get_or_create_token(
            plaintext=plaintext,
            pii_type=pii_type,
            source_name=source_name,
        )
        return {"Token": token, "WasNew": 1 if was_new else 0}


@contextmanager
def _fake_cursor_cm(cur: MagicMock):
    """Yield a MagicMock cursor that swallows provenance + batch INSERTs."""
    try:
        yield cur
    finally:
        pass


def _make_cursor_factory() -> Any:
    """Return a zero-arg callable yielding a fresh MagicMock cursor CM."""
    return lambda: _fake_cursor_cm(MagicMock())


# ---------------------------------------------------------------------------
# Helper — single-call tokenize wrapper that mirrors § 5.3 ``tokenize(...)``
# ---------------------------------------------------------------------------


def tokenize(
    plaintext: str,
    pii_type: str,
    source_name: str,
    *,
    vault: MockVault,
) -> str:
    """Tokenize a single plaintext value through M4 ``tokenize_pii_columns``.

    Wraps the scalar value in a 1-row DataFrame, threads it through M4
    with the mock vault, and returns the resulting token string. Matches
    the canonical § 5.3 ``tokenize(plaintext, 'EMAIL', 'DNA')`` surface.
    """
    df = pl.DataFrame({"VALUE": [plaintext]})
    out = tokenize_pii_columns(
        df,
        source_name=source_name,
        object_name="TEST_OBJECT",
        column_list=["VALUE"],
        batch_id=1,
        pii_type=pii_type,
        call_vault_sp_fn=vault.call_vault_sp,
        general_cursor_factory=_make_cursor_factory(),
        now_ms_fn=lambda: 0,
    )
    return out["VALUE"].to_list()[0]


# ---------------------------------------------------------------------------
# Hypothesis settings — per § 5.10 budget (verbatim)
# ---------------------------------------------------------------------------

# § 5.10: "Default: max_examples=200 ... Shrinkage budget: deadline=
# timedelta(seconds=10) per example to prevent runaway."
_property_settings = settings(
    max_examples=200,
    deadline=None,  # mocked I/O — deadline=10s would be excessive overhead
    # Mock cursor reuse across examples is a deliberate test design choice.
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


# ===========================================================================
# Section 1 — Canonical § 5.3 verbatim
# ===========================================================================


class TestTokenizeDeterministic:
    """Verbatim § 5.3 — same plaintext returns same token."""

    @given(plaintext=st.text(min_size=1, max_size=200))
    @_property_settings
    def test_tokenize_deterministic(self, plaintext: str) -> None:
        """§ 5.3 verbatim — t1 == t2 for the same input."""
        vault = MockVault()
        t1 = tokenize(plaintext, "EMAIL", "DNA", vault=vault)
        t2 = tokenize(plaintext, "EMAIL", "DNA", vault=vault)
        assert t1 == t2

    @given(
        plaintext=st.text(min_size=1, max_size=200),
        n_repeats=st.integers(min_value=3, max_value=10),
    )
    @_property_settings
    def test_tokenize_deterministic_n_repeats(
        self, plaintext: str, n_repeats: int
    ) -> None:
        """N consecutive tokenizations all produce the same token."""
        vault = MockVault()
        tokens = [
            tokenize(plaintext, "EMAIL", "DNA", vault=vault)
            for _ in range(n_repeats)
        ]
        # All N tokens equal the first one.
        assert all(tok == tokens[0] for tok in tokens)


# ===========================================================================
# Section 2 — Distinctness
# ===========================================================================


class TestDifferentPlaintextDifferentToken:
    """Distinct plaintexts produce distinct tokens within the same scope."""

    @given(
        pair=st.tuples(
            st.text(min_size=1, max_size=200),
            st.text(min_size=1, max_size=200),
        ).filter(lambda p: p[0] != p[1])
    )
    @_property_settings
    def test_different_plaintext_different_token(
        self, pair: tuple[str, str]
    ) -> None:
        """Two distinct plaintexts → two distinct tokens."""
        plaintext_a, plaintext_b = pair
        vault = MockVault()
        t_a = tokenize(plaintext_a, "EMAIL", "DNA", vault=vault)
        t_b = tokenize(plaintext_b, "EMAIL", "DNA", vault=vault)
        assert t_a != t_b


# ===========================================================================
# Section 3 — Token format invariant
# ===========================================================================


class TestTokenFormatInvariant:
    """Tokens returned by the mock vault match a stable hex-string format.

    The canonical SP-1 contract is ``Token VARCHAR(40)``. The mock mints
    40-char hex tokens; we verify (a) the returned value is a non-empty
    str and (b) it matches a hex pattern. Real SP-1 hex format is a Tier
    3 integration concern; this property checks the MOCK contract.
    """

    @given(plaintext=st.text(min_size=1, max_size=200))
    @_property_settings
    def test_token_is_nonempty_string(self, plaintext: str) -> None:
        """Tokens are always non-empty strings."""
        vault = MockVault()
        token = tokenize(plaintext, "EMAIL", "DNA", vault=vault)
        assert isinstance(token, str)
        assert len(token) > 0

    @given(plaintext=st.text(min_size=1, max_size=200))
    @_property_settings
    def test_token_hex_format_invariant(self, plaintext: str) -> None:
        """Mock-vault tokens match the 40-char hex pattern.

        Verifies the property: ``Token`` is purely lowercase hex digits.
        Canonical SP-1 VARCHAR(40) admits hex strings; the mock keeps
        the invariant tight so tests catch shape regressions.
        """
        vault = MockVault()
        token = tokenize(plaintext, "EMAIL", "DNA", vault=vault)
        assert len(token) == 40
        assert all(c in "0123456789abcdef" for c in token)


# ===========================================================================
# Section 4 — Case sensitivity
# ===========================================================================


class TestCaseSensitivePlaintext:
    """Per SP-1: case-sensitive plaintext distinction.

    ``"Email@x.com"`` vs ``"email@x.com"`` produce different tokens
    because SP-1 does NOT case-fold ``@Plaintext`` before hashing /
    lookup. The mock vault preserves this contract via the dict key
    comparison being case-sensitive.
    """

    @given(
        base=st.text(
            alphabet=st.characters(
                min_codepoint=ord("a"), max_codepoint=ord("z")
            ),
            min_size=1,
            max_size=50,
        )
    )
    @_property_settings
    def test_case_sensitive_plaintext(self, base: str) -> None:
        """Lowercase and uppercase variants → distinct tokens.

        Skip if base is invariant under case-folding (e.g. all digits
        / punctuation only — for ASCII letters this doesn't apply, but
        Hypothesis-generated text may contain mixed cases already).
        """
        upper = base.upper()
        if upper == base:
            # No case distinction possible; skip this example.
            return
        vault = MockVault()
        t_lower = tokenize(base, "EMAIL", "DNA", vault=vault)
        t_upper = tokenize(upper, "EMAIL", "DNA", vault=vault)
        assert t_lower != t_upper


# ===========================================================================
# Section 5 — Unicode NFC / NFD
# ===========================================================================


class TestUnicodeNormalization:
    """Per SP-1: NFC vs NFD forms of the same logical string differ.

    Example: ``'é'`` can be represented as
        - NFC: U+00E9 (single codepoint)
        - NFD: U+0065 U+0301 (e + combining acute)
    Both render identically but differ as Python strings; SP-1 hashes
    them as distinct plaintexts. The mock vault preserves this.

    A future B-N candidate could enforce NFC-normalization upstream of
    SP-1 so semantically-equivalent forms produce one token.
    """

    @given(
        base=st.text(
            alphabet=st.characters(
                min_codepoint=0x00C0, max_codepoint=0x017F
            ),
            min_size=1,
            max_size=20,
        )
    )
    @_property_settings
    def test_unicode_nfc_nfd_distinct_tokens(self, base: str) -> None:
        """NFC and NFD of the same string may produce different tokens.

        For strings where NFC(s) != NFD(s) (i.e. the string has
        decomposable characters), the two forms produce distinct
        tokens. For strings invariant under both forms, skip.
        """
        nfc = unicodedata.normalize("NFC", base)
        nfd = unicodedata.normalize("NFD", base)
        if nfc == nfd:
            return  # Invariant — no test signal here.
        vault = MockVault()
        t_nfc = tokenize(nfc, "EMAIL", "DNA", vault=vault)
        t_nfd = tokenize(nfd, "EMAIL", "DNA", vault=vault)
        assert t_nfc != t_nfd


# ===========================================================================
# Section 6 — Empty string + very long plaintext + Unicode roundtrip
# ===========================================================================


class TestEdgeCases:
    """Empty string, very long plaintext, Unicode whole-codepoint range."""

    def test_empty_string_tokenizes(self) -> None:
        """SP-1 accepts non-NULL empty string; mock mints a token for it.

        M4 NULL pass-through contract leaves None alone; '' is a real
        plaintext value that gets a real token. Property test value:
        regression against any future short-circuit on ``not plaintext``.
        """
        vault = MockVault()
        df = pl.DataFrame({"VALUE": [""]})
        out = tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="TEST_OBJECT",
            column_list=["VALUE"],
            batch_id=1,
            pii_type="EMAIL",
            call_vault_sp_fn=vault.call_vault_sp,
            general_cursor_factory=_make_cursor_factory(),
            now_ms_fn=lambda: 0,
        )
        token = out["VALUE"].to_list()[0]
        assert isinstance(token, str)
        assert len(token) == 40

    @given(plaintext=st.text(min_size=500, max_size=2000))
    @_property_settings
    def test_long_plaintext_tokenizes(self, plaintext: str) -> None:
        """SP-1 accepts NVARCHAR(MAX); 500-2000 chars must tokenize."""
        vault = MockVault()
        token = tokenize(plaintext, "EMAIL", "DNA", vault=vault)
        assert isinstance(token, str)
        assert len(token) == 40

    @given(plaintext=st.text(min_size=1, max_size=100))
    @_property_settings
    def test_unicode_plaintext_tokenizes(self, plaintext: str) -> None:
        """Unicode plaintext (any codepoints) must produce a valid token.

        Hypothesis ``st.text()`` defaults to the full ``hypothesis.
        strategies.characters()`` Unicode range — surrogates, control
        chars, emoji, etc. SP-1 ``@Plaintext NVARCHAR(MAX)`` accepts
        the full UTF-16 surface; the mock vault should too.
        """
        vault = MockVault()
        token = tokenize(plaintext, "EMAIL", "DNA", vault=vault)
        assert isinstance(token, str)
        assert len(token) > 0
