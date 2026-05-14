"""Tier 1 unit test for data_load/pii_tokenizer.py.

Per D70 Tier 1 — per-error-path + per-edge-case coverage; mocks M6
``call_vault_sp`` + General cursor; no live SQL Server.

Test scope (organized as classes per sibling tier1 style):

  TestImports
    - Public function exposed; no side-effects at import.
    - utils.errors canonical exceptions are the ones used (NOT local classes).

  TestSchemaPreservation
    - Output schema == input schema (PII columns are still string-typed).
    - Output height == input height.
    - Non-PII columns pass through unchanged (object equality).
    - Multiple PII columns rewritten independently.

  TestPerRowSpInvocation
    - SP-1 invoked once per non-null cell × column.
    - Each invocation carries (Plaintext, PiiType, SourceName) in sp_args.
    - PiiType defaults to 'OTHER' (CHECK constraint enum).
    - PiiType override threads to SP-1 args.
    - SourceName threads to SP-1 args.

  TestNullHandling
    - None cells DO NOT call SP-1.
    - Empty string cells DO call SP-1 (per spec — caller normalizes Oracle E-1).
    - Mixed null + non-null produces correct token alignment.

  TestIdempotency
    - Re-tokenizing the same df produces the same DataFrame (deterministic).
    - Same plaintext → same token (per D15) when the mocked SP-1 returns
      the same canned token.
    - Provenance UNIQUE violation swallowed (no exception bubbles).
    - Batch summary UNIQUE violation swallowed (no exception bubbles).

  TestErrorTranslation
    - PiiColumnNotFound when column_list names absent column. FATAL.
    - VaultUnavailable bubbles from M6 unchanged.
    - VaultUnavailable when SP-1 returns empty / non-string token.
    - PiiColumnNotFound metadata includes missing column name + df schema.

  TestProvenanceWrites
    - One PiiTokenProvenance INSERT per non-null cell.
    - INSERT carries (Token, SourceName, ObjectType, ObjectName, ColumnName,
      FilePath, BatchId) in canonical order.
    - SourceObjectType = 'FILE' when file_path != ''.
    - SourceObjectType = 'TABLE' when file_path = ''.
    - UNIQUE violation (2627 / 2601) swallowed; loop continues.

  TestBatchSummaryWrites
    - One PiiTokenizationBatch INSERT per (BatchId × SourceName × ObjectName
      × ColumnName).
    - NewTokensGenerated count = number of WasNew=1 SP-1 returns.
    - ExistingTokensReused count = number of WasNew=0 SP-1 returns.
    - TotalRowsTokenized = sum of non-null cells processed.
    - DurationMs computed from now_ms_fn delta.
    - UNIQUE violation swallowed; loop continues.

  TestEmptyShortCircuit
    - column_list=None → no SP-1, no cursor I/O.
    - column_list=[] → no SP-1, no cursor I/O.
    - Returned DataFrame is the input unchanged.

  TestSecurityContract
    - Plaintext never appears in caplog records at any log level.
    - Column names DO appear in log records (operator visibility).
    - Counts DO appear in log records (operator visibility).

  TestEdgeCases
    - DataFrame with zero rows (empty PII column).
    - Non-string PII cell (numeric) is coerced to string for SP-1.
    - Multiple columns in column_list with different tokens.
    - Same plaintext across columns gets independent provenance rows.

Spec: phase1/03_core_modules.md § 2.1 + phase1/01_database_schema.md
SP-1 + PiiTokenProvenance + PiiTokenizationBatch.

D-numbers: D6, D15, D26, D63, D67, D68, D103.
B-numbers: closes the M4 build-tracker entry by authoring this test.
"""
from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, call

import polars as pl
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@contextmanager
def _fake_cursor_cm(cur):
    try:
        yield cur
    finally:
        pass


def _make_cursor():
    cur = MagicMock()
    cur.execute.return_value = None
    return cur


def _make_factory(cur):
    return lambda: _fake_cursor_cm(cur)


def _stub_call_sp(token_value: str = "tok", was_new: int = 1):
    """Mock M6 call_vault_sp returning {Token, WasNew} per SP-1 contract."""
    def _stub(sp_name, *, sp_args, **kwargs):
        assert sp_name == "PiiVault_GetOrCreateToken", sp_name
        return {"Token": token_value, "WasNew": was_new}
    return MagicMock(side_effect=_stub)


def _stub_call_sp_by_plaintext(mapping: dict[str, tuple[str, int]]):
    """Mock M6 call_vault_sp returning per-plaintext canned (Token, WasNew).

    Mapping: plaintext → (token, was_new). Plaintexts not in the map raise
    AssertionError (test contract violation).
    """
    def _stub(sp_name, *, sp_args, **kwargs):
        assert sp_name == "PiiVault_GetOrCreateToken"
        pt_value = sp_args.get("Plaintext")
        assert pt_value in mapping, f"unexpected plaintext: {pt_value!r}"
        token, was_new = mapping[pt_value]
        return {"Token": token, "WasNew": was_new}
    return MagicMock(side_effect=_stub)


def _make_pyodbc_unique_error(code: int = 2627):
    """Build a synthetic UNIQUE-violation exception matching the
    _is_unique_violation heuristic.
    """
    err = Exception(f"(SQLSTATE 23000) UNIQUE violation ({code})")
    err.args = (("23000", f"UNIQUE violation ({code})", code),)
    return err


# ===========================================================================
# TestImports
# ===========================================================================


class TestImports:
    def test_public_function_exposed(self):
        from data_load import pii_tokenizer as pt
        assert hasattr(pt, "tokenize_pii_columns")

    def test_uses_canonical_pii_column_not_found(self):
        """B228 lesson — DO NOT define local exception classes."""
        from data_load import pii_tokenizer as pt
        from utils.errors import PiiColumnNotFound as CanonicalPCNF

        # The exception raised by tokenize_pii_columns MUST be the canonical
        # utils.errors.PiiColumnNotFound — verify by triggering the path
        # and matching against the canonical class.
        df = pl.DataFrame({"X": [1]})
        cur = _make_cursor()
        with pytest.raises(CanonicalPCNF):
            pt.tokenize_pii_columns(
                df,
                source_name="DNA",
                object_name="ACCT",
                column_list=["NOPE"],
                batch_id=1,
                call_vault_sp_fn=_stub_call_sp(),
                general_cursor_factory=_make_factory(cur),
                now_ms_fn=lambda: 0,
            )

    def test_uses_canonical_vault_unavailable(self):
        """B228 lesson — VaultUnavailable bubbles from utils.errors only."""
        from data_load import pii_tokenizer as pt
        from utils.errors import VaultUnavailable

        df = pl.DataFrame({"SSN": ["x"]})
        cur = _make_cursor()
        # Mock call_vault_sp returning empty token → contract violation →
        # VaultUnavailable per the tokenize_cell contract-check.
        bad_call = MagicMock(side_effect=lambda *a, **k: {"Token": "", "WasNew": 1})

        with pytest.raises(VaultUnavailable):
            pt.tokenize_pii_columns(
                df,
                source_name="DNA",
                object_name="ACCT",
                column_list=["SSN"],
                batch_id=1,
                call_vault_sp_fn=bad_call,
                general_cursor_factory=_make_factory(cur),
                now_ms_fn=lambda: 0,
            )


# ===========================================================================
# TestSchemaPreservation
# ===========================================================================


class TestSchemaPreservation:
    def _invoke(self, df, columns, call_sp=None, cur=None):
        from data_load.pii_tokenizer import tokenize_pii_columns

        return tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=columns,
            batch_id=1,
            call_vault_sp_fn=call_sp or _stub_call_sp(),
            general_cursor_factory=_make_factory(cur or _make_cursor()),
            now_ms_fn=lambda: 0,
        )

    def test_height_preserved(self):
        df = pl.DataFrame({"PK": [1, 2, 3, 4, 5], "SSN": list("abcde")})
        out = self._invoke(df, ["SSN"])
        assert out.height == 5

    def test_column_set_preserved(self):
        df = pl.DataFrame({"PK": [1], "SSN": ["x"], "EMAIL": ["y"], "NAME": ["z"]})
        out = self._invoke(df, ["SSN", "EMAIL"])
        assert set(out.columns) == {"PK", "SSN", "EMAIL", "NAME"}

    def test_pii_columns_string_typed(self):
        df = pl.DataFrame({"SSN": ["x", "y", "z"]})
        out = self._invoke(df, ["SSN"])
        assert out["SSN"].dtype == pl.Utf8

    def test_non_pii_columns_unchanged(self):
        df = pl.DataFrame({"PK": [1, 2, 3], "VAL": [10, 20, 30], "SSN": ["a", "b", "c"]})
        out = self._invoke(df, ["SSN"])
        assert out["PK"].to_list() == [1, 2, 3]
        assert out["VAL"].to_list() == [10, 20, 30]

    def test_multiple_pii_columns_each_rewritten(self):
        df = pl.DataFrame({"SSN": ["s1", "s2"], "EMAIL": ["e1", "e2"]})
        call_sp = _stub_call_sp(token_value="tok-X", was_new=1)
        out = self._invoke(df, ["SSN", "EMAIL"], call_sp=call_sp)
        assert out["SSN"].to_list() == ["tok-X", "tok-X"]
        assert out["EMAIL"].to_list() == ["tok-X", "tok-X"]
        # SP-1 called 2 rows × 2 columns = 4 times.
        assert call_sp.call_count == 4


# ===========================================================================
# TestPerRowSpInvocation
# ===========================================================================


class TestPerRowSpInvocation:
    def _invoke_with_sp_capture(self, df, columns, *, source_name="DNA", pii_type=None):
        from data_load.pii_tokenizer import tokenize_pii_columns

        cur = _make_cursor()
        call_sp = _stub_call_sp(token_value="tk", was_new=1)
        kwargs = dict(
            source_name=source_name,
            object_name="ACCT",
            column_list=columns,
            batch_id=1,
            call_vault_sp_fn=call_sp,
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        if pii_type is not None:
            kwargs["pii_type"] = pii_type
        tokenize_pii_columns(df, **kwargs)
        return call_sp

    def test_one_call_per_cell(self):
        df = pl.DataFrame({"SSN": ["a", "b", "c", "d"]})
        sp = self._invoke_with_sp_capture(df, ["SSN"])
        assert sp.call_count == 4

    def test_sp_args_contains_plaintext_pii_type_source(self):
        df = pl.DataFrame({"SSN": ["abc"]})
        sp = self._invoke_with_sp_capture(df, ["SSN"], source_name="DNA")
        call_kwargs = sp.call_args.kwargs
        sp_args = call_kwargs["sp_args"]
        assert set(sp_args.keys()) == {"Plaintext", "PiiType", "SourceName"}
        assert sp_args["Plaintext"] == "abc"
        assert sp_args["SourceName"] == "DNA"

    def test_default_pii_type_is_other(self):
        """SP-1 CHECK constraint enum includes 'OTHER' (Round 1 L885-886)."""
        df = pl.DataFrame({"SSN": ["x"]})
        sp = self._invoke_with_sp_capture(df, ["SSN"])
        sp_args = sp.call_args.kwargs["sp_args"]
        assert sp_args["PiiType"] == "OTHER"

    def test_pii_type_override_threads_through(self):
        df = pl.DataFrame({"SSN": ["x"]})
        sp = self._invoke_with_sp_capture(df, ["SSN"], pii_type="SSN")
        sp_args = sp.call_args.kwargs["sp_args"]
        assert sp_args["PiiType"] == "SSN"

    def test_source_name_threads_to_sp_args(self):
        df = pl.DataFrame({"SSN": ["x"]})
        sp = self._invoke_with_sp_capture(df, ["SSN"], source_name="CCM")
        sp_args = sp.call_args.kwargs["sp_args"]
        assert sp_args["SourceName"] == "CCM"


# ===========================================================================
# TestNullHandling
# ===========================================================================


class TestNullHandling:
    def test_none_does_not_call_sp(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"SSN": [None, None, None]})
        cur = _make_cursor()
        sp = _stub_call_sp()

        out = tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=1,
            call_vault_sp_fn=sp,
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        assert sp.call_count == 0
        assert out["SSN"].to_list() == [None, None, None]

    def test_empty_string_does_call_sp(self):
        """Per § 2.1 — empty strings are tokenized; caller normalizes E-1
        upstream where applicable.
        """
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"SSN": [""]})
        cur = _make_cursor()
        sp = _stub_call_sp(token_value="empty-tok", was_new=1)
        out = tokenize_pii_columns(
            df,
            source_name="SQLSERVER_SRC",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=1,
            call_vault_sp_fn=sp,
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        assert sp.call_count == 1
        assert sp.call_args.kwargs["sp_args"]["Plaintext"] == ""
        assert out["SSN"].to_list() == ["empty-tok"]

    def test_mixed_null_and_value_alignment(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"PK": [1, 2, 3, 4, 5],
                           "SSN": [None, "a", None, "b", None]})
        cur = _make_cursor()
        sp = _stub_call_sp(token_value="TK", was_new=1)
        out = tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=1,
            call_vault_sp_fn=sp,
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        # 2 SP-1 calls (one per non-null).
        assert sp.call_count == 2
        # Token alignment preserved.
        assert out["SSN"].to_list() == [None, "TK", None, "TK", None]


# ===========================================================================
# TestIdempotency
# ===========================================================================


class TestIdempotency:
    def test_same_plaintext_same_token_returns_identical_df(self):
        """Per D15 — when mock SP-1 is deterministic, output is identical
        across multiple invocations.
        """
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"SSN": ["abc", "def", "abc"]})
        mapping = {"abc": ("tok-abc", 1), "def": ("tok-def", 1)}

        cur1 = _make_cursor()
        out1 = tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=1,
            call_vault_sp_fn=_stub_call_sp_by_plaintext(mapping),
            general_cursor_factory=_make_factory(cur1),
            now_ms_fn=lambda: 0,
        )
        # Second invocation — different cursor, but SP-1 mock deterministic.
        cur2 = _make_cursor()
        out2 = tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=2,  # different batch_id — token output STILL same
            call_vault_sp_fn=_stub_call_sp_by_plaintext(mapping),
            general_cursor_factory=_make_factory(cur2),
            now_ms_fn=lambda: 0,
        )
        assert out1["SSN"].to_list() == out2["SSN"].to_list()
        assert out1["SSN"].to_list() == ["tok-abc", "tok-def", "tok-abc"]

    def test_provenance_unique_violation_swallowed(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"SSN": ["a", "b"]})
        cur = _make_cursor()

        # First execute call (provenance INSERT) raises UNIQUE; second call
        # (next provenance INSERT) succeeds; subsequent batch summary
        # INSERT succeeds.
        cur.execute.side_effect = [
            _make_pyodbc_unique_error(2627),  # provenance INSERT row 1
            None,  # provenance INSERT row 2
            None,  # batch summary INSERT
        ]

        # Should NOT raise — UNIQUE swallowed per D26.
        out = tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=1,
            call_vault_sp_fn=_stub_call_sp(token_value="TK", was_new=0),
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        assert out["SSN"].to_list() == ["TK", "TK"]
        assert cur.execute.call_count == 3

    def test_batch_summary_unique_violation_swallowed(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"SSN": ["a"]})
        cur = _make_cursor()
        cur.execute.side_effect = [
            None,  # provenance INSERT
            _make_pyodbc_unique_error(2601),  # batch summary INSERT
        ]
        out = tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=1,
            call_vault_sp_fn=_stub_call_sp(token_value="TK", was_new=1),
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        assert out["SSN"].to_list() == ["TK"]


# ===========================================================================
# TestErrorTranslation
# ===========================================================================


class TestErrorTranslation:
    def test_pii_column_not_found_raised(self):
        from data_load.pii_tokenizer import tokenize_pii_columns
        from utils.errors import PiiColumnNotFound

        df = pl.DataFrame({"PK": [1]})
        with pytest.raises(PiiColumnNotFound):
            tokenize_pii_columns(
                df,
                source_name="DNA",
                object_name="ACCT",
                column_list=["MISSING_COL"],
                batch_id=1,
                call_vault_sp_fn=_stub_call_sp(),
                general_cursor_factory=_make_factory(_make_cursor()),
                now_ms_fn=lambda: 0,
            )

    def test_pii_column_not_found_metadata_includes_missing_and_schema(self):
        from data_load.pii_tokenizer import tokenize_pii_columns
        from utils.errors import PiiColumnNotFound

        df = pl.DataFrame({"PK": [1], "EXISTS_COL": ["x"]})
        with pytest.raises(PiiColumnNotFound) as excinfo:
            tokenize_pii_columns(
                df,
                source_name="DNA",
                object_name="ACCT",
                column_list=["EXISTS_COL", "NO_SUCH"],
                batch_id=99,
                call_vault_sp_fn=_stub_call_sp(),
                general_cursor_factory=_make_factory(_make_cursor()),
                now_ms_fn=lambda: 0,
            )
        meta = excinfo.value.metadata
        assert "NO_SUCH" in meta["missing_columns"]
        assert "EXISTS_COL" in meta["df_columns"]
        assert meta["batch_id"] == 99
        assert meta["source_name"] == "DNA"

    def test_vault_unavailable_bubbles_from_m6(self):
        from data_load.pii_tokenizer import tokenize_pii_columns
        from utils.errors import VaultUnavailable

        df = pl.DataFrame({"SSN": ["x"]})
        cur = _make_cursor()

        def _raising_sp(sp_name, *, sp_args, **kwargs):
            raise VaultUnavailable("SP-1 connection lost", metadata={"attempts": 3})

        with pytest.raises(VaultUnavailable):
            tokenize_pii_columns(
                df,
                source_name="DNA",
                object_name="ACCT",
                column_list=["SSN"],
                batch_id=1,
                call_vault_sp_fn=MagicMock(side_effect=_raising_sp),
                general_cursor_factory=_make_factory(cur),
                now_ms_fn=lambda: 0,
            )

    def test_empty_token_returned_raises_vault_unavailable(self):
        from data_load.pii_tokenizer import tokenize_pii_columns
        from utils.errors import VaultUnavailable

        df = pl.DataFrame({"SSN": ["x"]})
        cur = _make_cursor()

        with pytest.raises(VaultUnavailable) as excinfo:
            tokenize_pii_columns(
                df,
                source_name="DNA",
                object_name="ACCT",
                column_list=["SSN"],
                batch_id=1,
                call_vault_sp_fn=MagicMock(
                    side_effect=lambda *a, **k: {"Token": "", "WasNew": 1}
                ),
                general_cursor_factory=_make_factory(cur),
                now_ms_fn=lambda: 0,
            )
        assert excinfo.value.metadata["returned_token_type"] == "str"

    def test_non_string_token_returned_raises_vault_unavailable(self):
        from data_load.pii_tokenizer import tokenize_pii_columns
        from utils.errors import VaultUnavailable

        df = pl.DataFrame({"SSN": ["x"]})
        cur = _make_cursor()
        # SP-1 contract violation — None token.
        bad_sp = MagicMock(side_effect=lambda *a, **k: {"Token": None, "WasNew": 1})
        with pytest.raises(VaultUnavailable):
            tokenize_pii_columns(
                df,
                source_name="DNA",
                object_name="ACCT",
                column_list=["SSN"],
                batch_id=1,
                call_vault_sp_fn=bad_sp,
                general_cursor_factory=_make_factory(cur),
                now_ms_fn=lambda: 0,
            )

    def test_non_unique_db_error_bubbles_up(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"SSN": ["x"]})
        cur = _make_cursor()
        # Non-UNIQUE error on provenance INSERT — should bubble.
        cur.execute.side_effect = RuntimeError("Permission denied on PiiTokenProvenance")

        with pytest.raises(RuntimeError):
            tokenize_pii_columns(
                df,
                source_name="DNA",
                object_name="ACCT",
                column_list=["SSN"],
                batch_id=1,
                call_vault_sp_fn=_stub_call_sp(),
                general_cursor_factory=_make_factory(cur),
                now_ms_fn=lambda: 0,
            )


# ===========================================================================
# TestProvenanceWrites
# ===========================================================================


class TestProvenanceWrites:
    def test_one_provenance_row_per_cell(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"SSN": ["a", "b", "c"]})
        cur = _make_cursor()
        tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=42,
            call_vault_sp_fn=_stub_call_sp("TOK", was_new=1),
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        # 3 provenance INSERTs + 1 batch summary INSERT = 4 execute calls.
        assert cur.execute.call_count == 4

    def test_provenance_args_in_canonical_order(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"SSN": ["plain1"]})
        cur = _make_cursor()
        tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=7,
            file_path="",
            call_vault_sp_fn=_stub_call_sp("TOK", was_new=1),
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        # First execute call = provenance INSERT.
        first_call = cur.execute.call_args_list[0]
        sql, *positional = first_call.args
        assert "PiiTokenProvenance" in sql
        # Positional args per _PROVENANCE_INSERT_SQL:
        # Token, SourceName, SourceObjectType, ObjectName, ColumnName,
        # FilePath, FirstObservedBatchId
        assert positional == ["TOK", "DNA", "TABLE", "ACCT", "SSN", "", 7]

    def test_source_object_type_file_when_file_path_set(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"SSN": ["x"]})
        cur = _make_cursor()
        tokenize_pii_columns(
            df,
            source_name="HIVE_SRC",
            object_name="snapshot.parquet",
            column_list=["SSN"],
            batch_id=1,
            file_path="/data/hive/snapshot.parquet",
            call_vault_sp_fn=_stub_call_sp("T", was_new=1),
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        first_call = cur.execute.call_args_list[0]
        _sql, *positional = first_call.args
        # SourceObjectType is positional index 2.
        assert positional[2] == "FILE"
        # FilePath is positional index 5.
        assert positional[5] == "/data/hive/snapshot.parquet"

    def test_source_object_type_table_when_file_path_empty(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"SSN": ["x"]})
        cur = _make_cursor()
        tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=1,
            file_path="",
            call_vault_sp_fn=_stub_call_sp("T", was_new=1),
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        first_call = cur.execute.call_args_list[0]
        _sql, *positional = first_call.args
        assert positional[2] == "TABLE"


# ===========================================================================
# TestBatchSummaryWrites
# ===========================================================================


class TestBatchSummaryWrites:
    def test_one_summary_row_per_column(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"SSN": ["a"], "EMAIL": ["b"]})
        cur = _make_cursor()
        tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN", "EMAIL"],
            batch_id=1,
            call_vault_sp_fn=_stub_call_sp("T", was_new=1),
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        # SSN: 1 provenance + 1 summary = 2
        # EMAIL: 1 provenance + 1 summary = 2
        # Total: 4 execute calls.
        assert cur.execute.call_count == 4
        # Last call for each column is the batch summary.
        summary_calls = [
            c for c in cur.execute.call_args_list
            if "PiiTokenizationBatch" in c.args[0]
        ]
        assert len(summary_calls) == 2

    def test_new_tokens_counted(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"SSN": ["a", "b", "c"]})
        cur = _make_cursor()
        # All 3 are new (WasNew=1).
        tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=5,
            call_vault_sp_fn=_stub_call_sp("T", was_new=1),
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        summary_call = [
            c for c in cur.execute.call_args_list
            if "PiiTokenizationBatch" in c.args[0]
        ][0]
        # Positional args: BatchId, SourceName, ObjectName, ColumnName,
        # NewTokensGenerated, ExistingTokensReused, TotalRowsTokenized,
        # DurationMs
        positional = summary_call.args[1:]
        assert positional[0] == 5  # BatchId
        assert positional[4] == 3  # NewTokensGenerated
        assert positional[5] == 0  # ExistingTokensReused
        assert positional[6] == 3  # TotalRowsTokenized

    def test_existing_tokens_counted(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"SSN": ["a", "b"]})
        cur = _make_cursor()
        # All reused (WasNew=0).
        tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=1,
            call_vault_sp_fn=_stub_call_sp("T", was_new=0),
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        summary_call = [
            c for c in cur.execute.call_args_list
            if "PiiTokenizationBatch" in c.args[0]
        ][0]
        positional = summary_call.args[1:]
        assert positional[4] == 0  # NewTokensGenerated
        assert positional[5] == 2  # ExistingTokensReused
        assert positional[6] == 2  # TotalRowsTokenized

    def test_null_cells_dont_count_in_total(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"SSN": ["a", None, "b", None, "c"]})
        cur = _make_cursor()
        tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=1,
            call_vault_sp_fn=_stub_call_sp("T", was_new=1),
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        summary_call = [
            c for c in cur.execute.call_args_list
            if "PiiTokenizationBatch" in c.args[0]
        ][0]
        positional = summary_call.args[1:]
        # 3 non-null cells.
        assert positional[6] == 3
        # All 3 new in this fixture.
        assert positional[4] == 3

    def test_duration_ms_computed_from_clock(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"SSN": ["a"]})
        cur = _make_cursor()

        # Clock returns 100, then 250 → duration_ms = 150.
        clock_values = iter([100, 250])
        tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=1,
            call_vault_sp_fn=_stub_call_sp("T", was_new=1),
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: next(clock_values),
        )
        summary_call = [
            c for c in cur.execute.call_args_list
            if "PiiTokenizationBatch" in c.args[0]
        ][0]
        positional = summary_call.args[1:]
        # DurationMs at positional index 7.
        assert positional[7] == 150


# ===========================================================================
# TestEmptyShortCircuit
# ===========================================================================


class TestEmptyShortCircuit:
    def test_none_column_list_no_io(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"X": [1, 2, 3]})
        cur = _make_cursor()
        sp = MagicMock()

        out = tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=None,
            batch_id=1,
            call_vault_sp_fn=sp,
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        assert out.equals(df)
        assert sp.call_count == 0
        assert cur.execute.call_count == 0

    def test_empty_list_no_io(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"X": [1]})
        cur = _make_cursor()
        sp = MagicMock()

        out = tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=[],
            batch_id=1,
            call_vault_sp_fn=sp,
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        assert out.equals(df)
        assert sp.call_count == 0
        assert cur.execute.call_count == 0

    def test_empty_short_circuit_does_not_open_cursor(self):
        """The cursor factory should NOT be invoked on the short-circuit path."""
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"X": [1]})
        factory = MagicMock()

        out = tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=[],
            batch_id=1,
            call_vault_sp_fn=_stub_call_sp(),
            general_cursor_factory=factory,
            now_ms_fn=lambda: 0,
        )
        assert out.equals(df)
        assert factory.call_count == 0


# ===========================================================================
# TestSecurityContract
# ===========================================================================


class TestSecurityContract:
    def test_plaintext_never_in_caplog_debug(self, caplog):
        from data_load.pii_tokenizer import tokenize_pii_columns

        caplog.set_level(logging.DEBUG, logger="data_load.pii_tokenizer")
        plaintext = "TOP-SECRET-9876"
        df = pl.DataFrame({"SSN": [plaintext]})
        cur = _make_cursor()
        tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=1,
            call_vault_sp_fn=_stub_call_sp("REDACTED-TOK", was_new=1),
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        for record in caplog.records:
            rendered = record.getMessage()
            assert plaintext not in rendered

    def test_plaintext_never_in_caplog_with_unique_swallowed(self, caplog):
        """Even with UNIQUE-violation handling (which logs at DEBUG),
        plaintext stays out of the log surface.
        """
        from data_load.pii_tokenizer import tokenize_pii_columns

        caplog.set_level(logging.DEBUG, logger="data_load.pii_tokenizer")
        plaintext = "CONFIDENTIAL-AAA-BBB"
        df = pl.DataFrame({"SSN": [plaintext]})
        cur = _make_cursor()
        cur.execute.side_effect = [
            _make_pyodbc_unique_error(2627),  # provenance UNIQUE
            None,  # batch summary
        ]
        tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=1,
            call_vault_sp_fn=_stub_call_sp("TOK", was_new=0),
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        for record in caplog.records:
            assert plaintext not in record.getMessage()

    def test_plaintext_never_in_pii_column_not_found_message(self, caplog):
        from data_load.pii_tokenizer import tokenize_pii_columns
        from utils.errors import PiiColumnNotFound

        plaintext = "VERY-SECRET-XYZ"
        df = pl.DataFrame({"OTHER": [plaintext]})
        with pytest.raises(PiiColumnNotFound) as excinfo:
            tokenize_pii_columns(
                df,
                source_name="DNA",
                object_name="ACCT",
                column_list=["NOPE"],
                batch_id=1,
                call_vault_sp_fn=_stub_call_sp(),
                general_cursor_factory=_make_factory(_make_cursor()),
                now_ms_fn=lambda: 0,
            )
        # Exception message MUST NOT include cell values (only column names).
        assert plaintext not in str(excinfo.value)
        # Metadata also clean.
        for v in excinfo.value.metadata.values():
            assert plaintext not in str(v)

    def test_column_names_visible_in_logs(self, caplog):
        from data_load.pii_tokenizer import tokenize_pii_columns

        caplog.set_level(logging.INFO, logger="data_load.pii_tokenizer")
        df = pl.DataFrame({"SSN_COL": ["x"]})
        cur = _make_cursor()
        tokenize_pii_columns(
            df,
            source_name="MY_SRC",
            object_name="MY_TBL",
            column_list=["SSN_COL"],
            batch_id=42,
            call_vault_sp_fn=_stub_call_sp("T", was_new=1),
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        all_logs = " ".join(r.getMessage() for r in caplog.records)
        # Operator-visible context — these MUST be in the log surface.
        assert "SSN_COL" in all_logs
        assert "MY_SRC" in all_logs
        assert "MY_TBL" in all_logs
        assert "42" in all_logs  # batch_id

    def test_counts_visible_in_logs(self, caplog):
        from data_load.pii_tokenizer import tokenize_pii_columns

        caplog.set_level(logging.INFO, logger="data_load.pii_tokenizer")
        df = pl.DataFrame({"SSN": ["a", "b", "c", "d", "e"]})
        cur = _make_cursor()
        tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=1,
            call_vault_sp_fn=_stub_call_sp("T", was_new=1),
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        all_logs = " ".join(r.getMessage() for r in caplog.records)
        # The 5-row count should be visible somewhere (aggregate, not per-cell).
        assert "5" in all_logs


# ===========================================================================
# TestEdgeCases
# ===========================================================================


class TestEdgeCases:
    def test_zero_row_pii_column(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"SSN": pl.Series([], dtype=pl.Utf8)})
        cur = _make_cursor()
        sp = _stub_call_sp("T", was_new=1)
        out = tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=1,
            call_vault_sp_fn=sp,
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        # No SP-1 calls (no rows).
        assert sp.call_count == 0
        # Zero rows out.
        assert out.height == 0
        # But the batch summary still got written (idempotent record per
        # column tokenized — TotalRowsTokenized=0).
        summary_calls = [
            c for c in cur.execute.call_args_list
            if "PiiTokenizationBatch" in c.args[0]
        ]
        assert len(summary_calls) == 1
        positional = summary_calls[0].args[1:]
        assert positional[6] == 0  # TotalRowsTokenized

    def test_numeric_cell_coerced_to_string_for_sp(self):
        """Defensive cast — caller is expected to pass string PII columns
        but numeric cells get coerced rather than crashing the SP-1 call.
        """
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"ACCT_NUMBER": [1234567890, 9876543210]})
        cur = _make_cursor()
        sp = _stub_call_sp("T", was_new=1)
        out = tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["ACCT_NUMBER"],
            batch_id=1,
            call_vault_sp_fn=sp,
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        # SP-1 received the string form of each int.
        plaintexts = [c.kwargs["sp_args"]["Plaintext"] for c in sp.call_args_list]
        assert plaintexts == ["1234567890", "9876543210"]
        # Output column became string type with tokens.
        assert out["ACCT_NUMBER"].to_list() == ["T", "T"]
        assert out["ACCT_NUMBER"].dtype == pl.Utf8

    def test_multiple_columns_different_tokens(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"SSN": ["s1"], "EMAIL": ["e1"]})
        cur = _make_cursor()

        # Return different tokens based on the column-driven plaintext.
        def _per_plaintext(sp_name, *, sp_args, **kwargs):
            pt = sp_args["Plaintext"]
            return {"Token": f"tok-{pt}", "WasNew": 1}

        sp = MagicMock(side_effect=_per_plaintext)
        out = tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN", "EMAIL"],
            batch_id=1,
            call_vault_sp_fn=sp,
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        assert out["SSN"].to_list() == ["tok-s1"]
        assert out["EMAIL"].to_list() == ["tok-e1"]

    def test_same_plaintext_across_columns_gets_independent_provenance(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        # Same plaintext "shared" appears in both SSN and EMAIL columns.
        df = pl.DataFrame({"SSN": ["shared"], "EMAIL": ["shared"]})
        cur = _make_cursor()

        sp = _stub_call_sp("SAME-TOK", was_new=1)
        tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN", "EMAIL"],
            batch_id=1,
            call_vault_sp_fn=sp,
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        # Two provenance INSERTs (one per ColumnName) for the same Token —
        # each column is a separate first-observation context per V1
        # (PiiTokenProvenance allows multiple rows per Token).
        provenance_calls = [
            c for c in cur.execute.call_args_list
            if "PiiTokenProvenance" in c.args[0]
        ]
        assert len(provenance_calls) == 2
        column_names = [c.args[5] for c in provenance_calls]  # ColumnName positional
        assert set(column_names) == {"SSN", "EMAIL"}

    def test_batch_id_threads_to_provenance_and_summary(self):
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"SSN": ["x"]})
        cur = _make_cursor()
        tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["SSN"],
            batch_id=8675309,
            call_vault_sp_fn=_stub_call_sp("T", was_new=1),
            general_cursor_factory=_make_factory(cur),
            now_ms_fn=lambda: 0,
        )
        # Provenance INSERT — FirstObservedBatchId at positional index 6.
        provenance_call = [
            c for c in cur.execute.call_args_list
            if "PiiTokenProvenance" in c.args[0]
        ][0]
        assert provenance_call.args[7] == 8675309
        # Batch summary INSERT — BatchId at positional index 1.
        summary_call = [
            c for c in cur.execute.call_args_list
            if "PiiTokenizationBatch" in c.args[0]
        ][0]
        assert summary_call.args[1] == 8675309

    def test_pii_columns_become_utf8_when_input_was_other_dtype(self):
        """Per spec — 'Schema unchanged (columns are still string type)'.
        Our implementation writes Utf8 output. If the input was numeric,
        the post-tokenization column is Utf8 (string tokens).
        """
        from data_load.pii_tokenizer import tokenize_pii_columns

        df = pl.DataFrame({"NUM": [1, 2, 3]})
        out = tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["NUM"],
            batch_id=1,
            call_vault_sp_fn=_stub_call_sp("T", was_new=1),
            general_cursor_factory=_make_factory(_make_cursor()),
            now_ms_fn=lambda: 0,
        )
        assert out["NUM"].dtype == pl.Utf8
        assert out["NUM"].to_list() == ["T", "T", "T"]
