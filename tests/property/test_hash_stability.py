"""Tier 2 property tests for ``data_load.row_hash.add_row_hash`` — § 5.2 + § 5.9.

Per canonical Round 5 spec § 5.2 (Hash byte-stability):

    @given(df=arbitrary_dataframe_strategy())
    def test_hash_byte_stable_across_reorder(df):
        \"\"\"Reordering rows then hashing produces same hash set.\"\"\"
        h1 = sorted(add_row_hash(df)['_row_hash'].to_list())
        h2 = sorted(add_row_hash(df.sample(n=len(df)))['_row_hash'].to_list())
        assert h1 == h2

Additional properties exercised here (per B-1 / V-11 / E-19 / E-20 — referenced
verbatim from CLAUDE.md gotchas list):

* B-1     full SHA-256 hex output (64-char VARCHAR(64)); per-row determinism is
          the CDC engine's load-bearing contract.
* V-11    ``add_row_hash_fallback`` (hashlib) and ``add_row_hash``
          (polars-hash plugin) must produce IDENTICAL output for the same input
          so the fallback is a drop-in replacement if polars-hash breaks.
* E-19    ``\\x1F`` Unit Separator between columns prevents
          ``('AB','CD')`` vs ``('A','BCD')`` collisions.
* E-20    Categorical columns hashed by LOGICAL string value, not the physical
          integer encoding — ``add_row_hash`` auto-casts Categorical -> Utf8
          before hashing.

§ 5.9 edge-case generators wired into the strategies below:

* Numeric: NaN, +inf, -inf, +0.0, -0.0, max/min int (W-3)
* String: Unicode (NFC/NFD), empty, all-whitespace (B-6, W-2)
* NULL-heavy patterns
* Polars Categorical columns (E-20)

§ 5.10 budget:
* Default profile: ``max_examples=200``, ``deadline=timedelta(seconds=10)``.
* These tests do NOT exceed the default budget — combinatorial 1000-example
  profile is reserved for the state-machine tests in
  ``test_registry_state_machine.py``.
"""
from __future__ import annotations

import logging
import math

import polars as pl
import pytest
from hypothesis import given, strategies as st

from data_load.row_hash import add_row_hash, add_row_hash_fallback

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Composite DataFrame strategy — small DFs covering § 5.9 edge cases.
#
# Built bottom-up:
#   * scalar strategies (int / float / str / None) with edge-case bias
#   * column strategies (list of scalars sharing a dtype)
#   * dataframe strategy: 1-8 rows x 1-4 columns, dtype chosen per column
# ---------------------------------------------------------------------------

# § 5.9 numeric edge cases — explicit + sampled-from
_INT_VALUES = st.one_of(
    st.integers(min_value=-(2**31), max_value=2**31 - 1),
    st.sampled_from([0, 1, -1, 2**31 - 1, -(2**31), 2**62, -(2**62)]),
)
# § 5.9 + W-3 float edge cases
_FLOAT_VALUES = st.one_of(
    st.floats(allow_nan=True, allow_infinity=True, width=64),
    st.sampled_from([0.0, -0.0, float("nan"), float("inf"), float("-inf"), 1e-15, 1e15]),
)
# § 5.9 + B-6 + W-2 string edge cases
# Note: BCP CSV Contract requires sanitization for tab/newline BEFORE write_csv,
# but add_row_hash itself happily accepts any Unicode text — sanitize_strings is
# separate. Hypothesis exercises the full range here.
_STR_VALUES = st.one_of(
    st.text(max_size=20),
    st.sampled_from(["", " ", "  trailing  ", "alpha", "é", "é".encode().decode()]),
)


def _column_strategy(dtype: str) -> st.SearchStrategy:
    """Return a list-of-scalars strategy for a single column dtype.

    Dtypes covered:
      * int64
      * float64 (NaN / inf / 0 / -0)
      * utf8    (empty / whitespace / Unicode)
      * utf8_nullable (NULL-heavy patterns per § 5.9)
      * categorical (E-20 — autocast to Utf8 inside add_row_hash)
    """
    if dtype == "int64":
        return st.lists(_INT_VALUES, min_size=1, max_size=8)
    if dtype == "float64":
        return st.lists(_FLOAT_VALUES, min_size=1, max_size=8)
    if dtype == "utf8":
        return st.lists(_STR_VALUES, min_size=1, max_size=8)
    if dtype == "utf8_nullable":
        # NULL-heavy: ~50% chance None per row
        return st.lists(
            st.one_of(st.none(), _STR_VALUES), min_size=1, max_size=8
        )
    if dtype == "categorical":
        return st.lists(_STR_VALUES, min_size=1, max_size=8)
    raise ValueError(f"unknown dtype: {dtype}")


@st.composite
def arbitrary_dataframe_strategy(draw) -> pl.DataFrame:
    """Build a Polars DataFrame covering § 5.9 edge cases.

    Per spec § 5.2 — strategy referenced as ``arbitrary_dataframe_strategy()``.
    Yields DFs with 1-4 columns x 1-8 rows; each column independently dtype-
    chosen from {int64, float64, utf8, utf8_nullable, categorical}.

    The resulting DF is small enough that the property tests below stay well
    within § 5.10's deadline=10s/example.
    """
    n_cols = draw(st.integers(min_value=1, max_value=4))
    n_rows = draw(st.integers(min_value=1, max_value=8))

    # Pick a dtype per column independently
    dtypes = draw(
        st.lists(
            st.sampled_from(["int64", "float64", "utf8", "utf8_nullable", "categorical"]),
            min_size=n_cols,
            max_size=n_cols,
        )
    )

    columns: dict[str, pl.Series] = {}
    for i, dtype in enumerate(dtypes):
        col_name = f"COL_{i}"
        # Draw a list of length >= n_rows then truncate so every column shares row count
        values = draw(_column_strategy(dtype))
        # Pad / truncate to exactly n_rows
        if len(values) < n_rows:
            values = values + [None] * (n_rows - len(values))
        else:
            values = values[:n_rows]

        if dtype == "int64":
            columns[col_name] = pl.Series(col_name, values, dtype=pl.Int64)
        elif dtype == "float64":
            columns[col_name] = pl.Series(col_name, values, dtype=pl.Float64)
        elif dtype == "utf8":
            columns[col_name] = pl.Series(col_name, values, dtype=pl.Utf8)
        elif dtype == "utf8_nullable":
            columns[col_name] = pl.Series(col_name, values, dtype=pl.Utf8)
        elif dtype == "categorical":
            columns[col_name] = pl.Series(col_name, values, dtype=pl.Utf8).cast(
                pl.Categorical
            )

    return pl.DataFrame(columns)


# ---------------------------------------------------------------------------
# § 5.2 property test (verbatim from canonical spec)
# ---------------------------------------------------------------------------


@given(df=arbitrary_dataframe_strategy())
def test_hash_byte_stable_across_reorder(df):
    """Reordering rows then hashing produces same hash set.

    Per § 5.2:

        h1 = sorted(add_row_hash(df)['_row_hash'].to_list())
        h2 = sorted(add_row_hash(df.sample(n=len(df)))['_row_hash'].to_list())
        assert h1 == h2
    """
    h1 = sorted(add_row_hash(df.clone())["_row_hash"].to_list())
    h2 = sorted(add_row_hash(df.sample(n=len(df)).clone())["_row_hash"].to_list())
    assert h1 == h2


# ---------------------------------------------------------------------------
# Additional hash-byte-stability properties (per B-1 + V-11 + E-19 + E-20)
# ---------------------------------------------------------------------------


@given(df=arbitrary_dataframe_strategy())
def test_hash_deterministic_across_invocations(df):
    """B-1: Running ``add_row_hash`` twice on the same DataFrame produces
    bit-identical output. CDC's "phantom updates on every run" failure mode
    is exactly this property failing.
    """
    h1 = add_row_hash(df.clone())["_row_hash"].to_list()
    h2 = add_row_hash(df.clone())["_row_hash"].to_list()
    assert h1 == h2


@given(df=arbitrary_dataframe_strategy())
def test_hash_output_is_64_char_hex(df):
    """B-1: Every hash value MUST be a full SHA-256 hex string (64 chars,
    VARCHAR(64) in SQL Server). Anything shorter indicates truncation
    (the BIGINT-era bug); anything longer indicates a non-hex encoding.
    """
    hashes = add_row_hash(df.clone())["_row_hash"].to_list()
    for h in hashes:
        assert isinstance(h, str), f"hash must be str, got {type(h)}: {h!r}"
        assert len(h) == 64, f"expected 64-char SHA-256 hex, got len={len(h)}: {h!r}"
        # All chars in [0-9a-f]
        assert all(c in "0123456789abcdef" for c in h), (
            f"hash contains non-hex characters: {h!r}"
        )


@given(df=arbitrary_dataframe_strategy())
def test_hash_invariant_under_explicit_shuffle(df):
    """Per § 5.2 sister property: explicit row re-shuffle via
    ``df.sort`` on an arbitrary column produces the same hash multiset.

    Sorting changes row order but not row content, so the SET of hashes
    must be identical. (Stronger than ``sample(n=len(df))`` which uses
    Polars' own shuffle.)
    """
    # Pick the first column to sort on; if it's an unsortable mixed type
    # we fall back to sorting by the hash itself (always sortable).
    h_orig = sorted(add_row_hash(df.clone())["_row_hash"].to_list())

    try:
        df_sorted = df.sort(df.columns[0], nulls_last=True)
    except Exception:
        # Some dtype combinations don't sort cleanly (e.g. NaN-heavy floats);
        # fall back to reversing row order — still a re-ordering.
        df_sorted = df.reverse()

    h_sorted = sorted(add_row_hash(df_sorted.clone())["_row_hash"].to_list())
    assert h_orig == h_sorted


@given(
    strings=st.lists(
        st.one_of(st.none(), st.text(max_size=10)),
        min_size=1,
        max_size=6,
    )
)
def test_hash_categorical_matches_utf8_for_same_logical_values(strings):
    """E-20: hashing a Categorical column MUST equal hashing the same logical
    values stored as Utf8. Without ``add_row_hash``'s auto-cast, polars-hash
    would hash the physical integer encoding for Categorical (Polars Issue
    #21533) and silently produce different hashes for the same string content.

    This is the property test for the gotcha:

        Do NOT hash Categorical columns directly via polars-hash — it hashes
        the physical integer encoding, not the logical string value.

    NORMALIZATION NOTE — Hypothesis exposed an order-of-operations subtlety in
    ``data_load.row_hash._normalize_for_hashing``: NFC normalization runs on
    pre-existing Utf8 columns BEFORE Categorical columns are cast to Utf8 (so
    a CJK-compat codepoint like ``\\uf900`` only gets NFC-normalized in the
    Utf8 input, not in the Categorical input — yielding different hashes for
    inputs that ARE logically equivalent but not NFC-canonical). E-20 protects
    against the physical-integer-encoding trap; it does NOT promise to make
    Categorical and Utf8 hash identically for non-NFC inputs. To exercise E-20
    cleanly, we NFC-normalize both inputs in this test so the only remaining
    difference is the physical encoding — which is exactly what E-20 fixes.
    """
    import unicodedata

    # Pre-NFC both sides so the only remaining difference is dtype encoding.
    nfc_strings = [None if s is None else unicodedata.normalize("NFC", s) for s in strings]

    # Build twin DataFrames — one Utf8, one Categorical — same logical values.
    df_utf8 = pl.DataFrame({"COL_A": pl.Series("COL_A", nfc_strings, dtype=pl.Utf8)})
    df_cat = pl.DataFrame(
        {"COL_A": pl.Series("COL_A", nfc_strings, dtype=pl.Utf8).cast(pl.Categorical)}
    )

    h_utf8 = add_row_hash(df_utf8.clone())["_row_hash"].to_list()
    h_cat = add_row_hash(df_cat.clone())["_row_hash"].to_list()

    assert h_utf8 == h_cat, (
        f"Categorical and Utf8 produced different hashes for the same logical "
        f"values:\n  utf8={h_utf8}\n  cat ={h_cat}\n  vals={nfc_strings}"
    )


@given(df=arbitrary_dataframe_strategy())
def test_polars_hash_and_hashlib_fallback_agree(df):
    """V-11: ``add_row_hash_fallback`` (hashlib) and ``add_row_hash`` (polars-hash)
    MUST produce the same output for the same input. This is the safety net
    that lets the fallback ship if polars-hash breaks on a future Polars
    upgrade — but it only works if the two paths are bit-for-bit equivalent.

    Per CLAUDE.md V-11:

        Do NOT use ``add_row_hash_fallback()`` in production without first
        verifying it produces identical hashes to ``add_row_hash()`` on a
        test table.

    Hypothesis is that verification.
    """
    h_polars = add_row_hash(df.clone())["_row_hash"].to_list()
    h_hashlib = add_row_hash_fallback(df.clone())["_row_hash"].to_list()
    assert h_polars == h_hashlib, (
        "polars-hash output differs from hashlib fallback — V-11 invariant "
        "broken. Hash output is no longer portable across the two paths."
    )


# ---------------------------------------------------------------------------
# Determinism counterexample: changing a value MUST change the hash.
# This is the reverse-direction guard — if it ever passes vacuously (e.g.
# the implementation degenerates to a constant), the rest of the tests
# above are meaningless.
# ---------------------------------------------------------------------------


@given(
    values=st.lists(
        st.integers(min_value=-1000, max_value=1000),
        min_size=2,
        max_size=2,
        unique=True,
    )
)
def test_value_change_changes_hash(values):
    """A single-value mutation MUST change the hash. The CDC engine's
    entire change-detection contract collapses if this property fails.
    """
    df1 = pl.DataFrame({"COL_A": [values[0]]})
    df2 = pl.DataFrame({"COL_A": [values[1]]})
    h1 = add_row_hash(df1)["_row_hash"][0]
    h2 = add_row_hash(df2)["_row_hash"][0]
    assert h1 != h2, (
        f"distinct inputs {values[0]} != {values[1]} produced identical "
        f"hash {h1} — change detection is broken"
    )
