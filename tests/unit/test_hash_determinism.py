"""Hash determinism tests for ``data_load.row_hash.add_row_hash``.

The CDC engine relies on ``_row_hash`` being **bit-stable** across runs.
If the same input produces a different hash on two consecutive runs, every
existing PK appears as a phantom UPDATE — driving spurious SCD2 versioning.

These tests cover the documented edge cases from CLAUDE.md:

* W-2 — NULL sentinel uses ``\\x1F`` (Unit Separator), never ``\\x00``
* W-3 — IEEE 754 normalization for NaN, ±Inf, ±0
* E-1 — Oracle empty string treated as NULL
* E-4 — trailing-space RTRIM
* E-19 — column separator prevents cross-column collisions
* E-20 — Categorical columns hashed by logical value
* SCD2-R10.2 — ``exclude_from_hash`` removes columns from the hash input
"""
from __future__ import annotations

import logging

import polars as pl
import pytest

from data_load.row_hash import add_row_hash


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Determinism — the headline contract.
# ---------------------------------------------------------------------------


def test_same_input_produces_same_hash():
    """Run ``add_row_hash`` twice on identical data; hashes must match."""
    df = pl.DataFrame({
        "PK_ID": [1, 2, 3],
        "VALUE": ["alpha", "beta", "gamma"],
        "AMOUNT": [10.5, 20.0, 30.25],
    })

    logger.info("Input: %d rows, columns=%s", df.height, df.columns)

    df1 = add_row_hash(df.clone())
    df2 = add_row_hash(df.clone())

    hashes1 = df1["_row_hash"].to_list()
    hashes2 = df2["_row_hash"].to_list()

    logger.info("Pass 1 hashes: %s", hashes1)
    logger.info("Pass 2 hashes: %s", hashes2)

    assert hashes1 == hashes2, (
        f"Hash output is non-deterministic — pass 1: {hashes1}, pass 2: {hashes2}. "
        "polars-hash plugin not registered correctly, or Polars version drift."
    )

    # Sanity: SHA-256 hex strings are 64 chars
    for h in hashes1:
        assert len(h) == 64, f"Expected 64-char hex (SHA-256), got {len(h)}: {h}"


def test_different_rows_produce_different_hashes():
    df = pl.DataFrame({
        "PK_ID": [1, 2],
        "VALUE": ["alpha", "beta"],
    })
    df = add_row_hash(df)
    h1, h2 = df["_row_hash"].to_list()
    logger.info("Row 1 hash: %s", h1)
    logger.info("Row 2 hash: %s", h2)
    assert h1 != h2, "Different row content collided to the same hash"


def test_value_change_changes_hash():
    """Single-value mutation must change the hash — the entire CDC engine
    relies on this."""
    base = pl.DataFrame({"PK_ID": [1], "VALUE": ["alpha"]})
    mutated = pl.DataFrame({"PK_ID": [1], "VALUE": ["beta"]})

    h_before = add_row_hash(base)["_row_hash"][0]
    h_after = add_row_hash(mutated)["_row_hash"][0]

    logger.info("VALUE='alpha' -> %s", h_before)
    logger.info("VALUE='beta'  -> %s", h_after)

    assert h_before != h_after


# ---------------------------------------------------------------------------
# E-19 — column-boundary collision prevention.
# ---------------------------------------------------------------------------


def test_column_boundary_collision_prevented():
    """``("AB", "CD")`` and ``("A", "BCD")`` would collide without the
    ``\\x1F`` column separator. E-19 ensures they don't.
    """
    df_a = pl.DataFrame({"COL1": ["AB"], "COL2": ["CD"]})
    df_b = pl.DataFrame({"COL1": ["A"],  "COL2": ["BCD"]})

    h_a = add_row_hash(df_a)["_row_hash"][0]
    h_b = add_row_hash(df_b)["_row_hash"][0]

    logger.info("('AB','CD')   -> %s", h_a)
    logger.info("('A','BCD')   -> %s", h_b)

    assert h_a != h_b, "Column boundary collision — \\x1F separator missing"


# ---------------------------------------------------------------------------
# W-3 — IEEE 754 float normalization.
# ---------------------------------------------------------------------------


def test_negative_zero_normalized_to_positive_zero():
    df_pos = pl.DataFrame({"PK": [1], "VAL": [0.0]})
    df_neg = pl.DataFrame({"PK": [1], "VAL": [-0.0]})

    h_pos = add_row_hash(df_pos)["_row_hash"][0]
    h_neg = add_row_hash(df_neg)["_row_hash"][0]

    logger.info("VAL=+0.0 -> %s", h_pos)
    logger.info("VAL=-0.0 -> %s", h_neg)

    assert h_pos == h_neg, (
        "+0.0 and -0.0 hashed differently — W-3 IEEE 754 normalization broken. "
        "Will produce phantom CDC updates for any column that flips sign of zero."
    )


def test_nan_inf_produce_stable_hashes():
    """NaN and ±Inf must produce stable, deterministic hashes."""
    df = pl.DataFrame({
        "PK": [1, 2, 3, 4],
        "VAL": [float("nan"), float("inf"), float("-inf"), 1.0],
    })

    h1 = add_row_hash(df.clone())["_row_hash"].to_list()
    h2 = add_row_hash(df.clone())["_row_hash"].to_list()

    logger.info("NaN/Inf hashes pass 1: %s", h1)
    logger.info("NaN/Inf hashes pass 2: %s", h2)

    assert h1 == h2, "NaN / ±Inf hashed non-deterministically"

    # Each special value should produce a distinct hash from a finite value
    nan_h, posinf_h, neginf_h, normal_h = h1
    assert len({nan_h, posinf_h, neginf_h, normal_h}) == 4, (
        "NaN / +Inf / -Inf / 1.0 collided — W-3 normalization missed a case"
    )


# ---------------------------------------------------------------------------
# E-1 / E-4 — Oracle empty-string and trailing-space normalization.
# ---------------------------------------------------------------------------


def test_oracle_empty_string_equals_null():
    """When ``source_is_oracle=True``, '' and NULL hash identically — Oracle
    treats them as the same value."""
    df_empty = pl.DataFrame({"PK": [1], "VAL": [""]})
    df_null = pl.DataFrame({"PK": [1], "VAL": [None]}, schema={"PK": pl.Int64, "VAL": pl.Utf8})

    h_empty = add_row_hash(df_empty, source_is_oracle=True)["_row_hash"][0]
    h_null = add_row_hash(df_null, source_is_oracle=True)["_row_hash"][0]

    logger.info("Oracle '' -> %s", h_empty)
    logger.info("Oracle NULL -> %s", h_null)

    assert h_empty == h_null, (
        "E-1: Oracle '' and NULL hashed differently — every Oracle-sourced "
        "row with empty-string fields will produce phantom CDC updates."
    )


def test_oracle_empty_string_distinct_from_null_for_sql_server():
    """For SQL Server sources, '' and NULL are different values and must
    hash differently."""
    df_empty = pl.DataFrame({"PK": [1], "VAL": [""]})
    df_null = pl.DataFrame({"PK": [1], "VAL": [None]}, schema={"PK": pl.Int64, "VAL": pl.Utf8})

    h_empty = add_row_hash(df_empty, source_is_oracle=False)["_row_hash"][0]
    h_null = add_row_hash(df_null, source_is_oracle=False)["_row_hash"][0]

    logger.info("SQL Server '' -> %s", h_empty)
    logger.info("SQL Server NULL -> %s", h_null)

    assert h_empty != h_null, (
        "SQL Server distinguishes '' from NULL — hashes must differ."
    )


def test_trailing_space_rtrim():
    """E-4: 'foo' and 'foo   ' must hash identically — Oracle CHAR padding
    and SQL Server ANSI padding can produce divergent trailing whitespace
    on the same logical value."""
    df_clean = pl.DataFrame({"PK": [1], "VAL": ["foo"]})
    df_padded = pl.DataFrame({"PK": [1], "VAL": ["foo   "]})

    h_clean = add_row_hash(df_clean)["_row_hash"][0]
    h_padded = add_row_hash(df_padded)["_row_hash"][0]

    logger.info("VAL='foo'    -> %s", h_clean)
    logger.info("VAL='foo   ' -> %s", h_padded)

    assert h_clean == h_padded, (
        "E-4: Trailing-space RTRIM not applied — pads cause phantom CDC updates."
    )


# ---------------------------------------------------------------------------
# E-20 — Categorical columns must hash by logical value, not physical code.
# ---------------------------------------------------------------------------


def test_categorical_column_hashes_by_value():
    df_utf8 = pl.DataFrame({"PK": [1, 2], "STATUS": ["ACTIVE", "CLOSED"]})
    df_cat = pl.DataFrame({
        "PK": [1, 2],
        "STATUS": pl.Series(["ACTIVE", "CLOSED"], dtype=pl.Categorical),
    })

    h_utf8 = add_row_hash(df_utf8)["_row_hash"].to_list()
    h_cat = add_row_hash(df_cat)["_row_hash"].to_list()

    logger.info("Utf8        hashes: %s", h_utf8)
    logger.info("Categorical hashes: %s", h_cat)

    assert h_utf8 == h_cat, (
        "E-20: Categorical column hashed differently than Utf8 with the "
        "same logical values. polars-hash hashes the physical integer "
        "encoding — must cast to Utf8 first."
    )


def test_categorical_column_hashes_match_utf8_for_cjk_compat_codepoint():
    """B-262 regression: Categorical(``'豈'``) hashes identically to
    Utf8(``'豈'``) after NFC normalization.

    CJK compatibility codepoint U+F900 ('豈') NFC-normalizes to U+8C5A ('豈').
    Pre-B-262 fix, ``_normalize_for_hashing`` ran NFC on pre-existing Utf8
    columns BEFORE casting Categorical -> Utf8 — so Categorical-input strings
    skipped NFC normalization entirely. Same logical string fed via Utf8 vs
    Categorical produced different hashes.

    E-20 protects against polars-hash's physical-integer-encoding trap;
    this test pins the COMPLEMENTARY invariant — NFC equivalence across
    dtypes. Surfaced by Tier 2 Hypothesis property test
    (``test_hash_stability`` § 5.2) and backfilled here as a unit-test
    regression so the Tier 1 suite carries the lesson forward without
    depending on Hypothesis cache.
    """
    cjk_compat = "豈"  # 豈 (compat) — NFC-normalizes to U+8C5A

    df_utf8 = pl.DataFrame({"PK": [1], "VAL": [cjk_compat]})
    df_cat = pl.DataFrame({
        "PK": [1],
        "VAL": pl.Series([cjk_compat], dtype=pl.Utf8).cast(pl.Categorical),
    })

    h_utf8 = add_row_hash(df_utf8)["_row_hash"][0]
    h_cat = add_row_hash(df_cat)["_row_hash"][0]

    logger.info("Utf8(U+F900)        -> %s", h_utf8)
    logger.info("Categorical(U+F900) -> %s", h_cat)

    assert h_utf8 == h_cat, (
        "B-262: Categorical-input CJK compat codepoint did NOT NFC-normalize "
        "before hashing. Same logical string produced different hashes "
        "depending on column dtype. Cast-before-NFC ordering broken."
    )


def test_categorical_column_hashes_match_utf8_for_trailing_whitespace():
    """B-262 regression: Categorical(``' '``) hashes identically to
    Utf8(``' '``) after RTRIM (E-4) normalization.

    The Categorical path skipped the full string-normalization pipeline
    (NFC + RTRIM) pre-B-262. Trailing-space-only strings produced divergent
    hashes between Utf8 and Categorical inputs because RTRIM only ran on
    pre-existing Utf8 columns.

    Hypothesis discovered this counter-example alongside the CJK case;
    backfilled here as a paired Tier 1 regression.
    """
    df_utf8 = pl.DataFrame({"PK": [1], "VAL": [" "]})
    df_cat = pl.DataFrame({
        "PK": [1],
        "VAL": pl.Series([" "], dtype=pl.Utf8).cast(pl.Categorical),
    })

    h_utf8 = add_row_hash(df_utf8)["_row_hash"][0]
    h_cat = add_row_hash(df_cat)["_row_hash"][0]

    logger.info("Utf8(' ')        -> %s", h_utf8)
    logger.info("Categorical(' ') -> %s", h_cat)

    assert h_utf8 == h_cat, (
        "B-262: Categorical-input trailing-space-only string did NOT RTRIM "
        "before hashing. Same logical string produced different hashes "
        "depending on column dtype. Cast-before-normalize ordering broken."
    )


# ---------------------------------------------------------------------------
# SCD2-R10.2 — exclude_from_hash drops columns from the hash input.
# ---------------------------------------------------------------------------


def test_exclude_from_hash_ignores_listed_column():
    """A column in ``exclude_from_hash`` must not change the hash when it
    changes value. Typical use: ``DATELASTMAINT`` on DNA tables."""
    df_a = pl.DataFrame({
        "PK": [1],
        "VALUE": ["alpha"],
        "DATELASTMAINT": ["2026-01-01"],
    })
    df_b = pl.DataFrame({
        "PK": [1],
        "VALUE": ["alpha"],
        "DATELASTMAINT": ["2026-05-06"],  # changed
    })

    excluded = ["DATELASTMAINT"]
    h_a = add_row_hash(df_a, exclude_cols=excluded)["_row_hash"][0]
    h_b = add_row_hash(df_b, exclude_cols=excluded)["_row_hash"][0]

    logger.info("DATELASTMAINT='2026-01-01' -> %s (excluded from hash)", h_a)
    logger.info("DATELASTMAINT='2026-05-06' -> %s (excluded from hash)", h_b)

    assert h_a == h_b, (
        "SCD2-R10.2: column listed in exclude_from_hash still influenced "
        "the hash. Wired incorrectly — DATELASTMAINT bumps would flood "
        "the pipeline with phantom CDC updates."
    )


def test_exclude_from_hash_does_not_remove_column_from_dataframe():
    """``exclude_from_hash`` only affects the hash input. The column itself
    must still be present in the DataFrame for BCP loading."""
    df = pl.DataFrame({
        "PK": [1],
        "VALUE": ["alpha"],
        "DATELASTMAINT": ["2026-01-01"],
    })

    df_hashed = add_row_hash(df, exclude_cols=["DATELASTMAINT"])

    logger.info("Columns after add_row_hash: %s", df_hashed.columns)

    assert "DATELASTMAINT" in df_hashed.columns, (
        "exclude_from_hash must not drop the column from the DataFrame — "
        "Stage and Bronze still need to load and store it."
    )
    assert "_row_hash" in df_hashed.columns
