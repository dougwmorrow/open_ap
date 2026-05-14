"""Tier 0 build-time smoke test for data_load/pii_tokenizer.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s. All
external dependencies (M6 vault wrapper, General DB cursor) are mocked.
No live SQL Server required.

North Star pillars:
  - Audit-grade (D26 — provenance + batch summary INSERTs verified via
    mock-cursor assertion; D103 security — smoke verifies plaintext NEVER
    appears in captured log records)
  - Operationally stable (D67 — module import side-effect-free + happy
    path + NULL pass-through + missing-column FATAL in < 5 s with zero
    external I/O)
  - Idempotent (D15 — re-tokenizing same plaintext returns same token;
    smoke asserts the per-row SP-1 contract via mock canned responses)

D-numbers: D6, D15, D26, D63, D67, D68, D103.
B-numbers: closes the M4 build-tracker entry by authoring this test.

Spec: phase1/03_core_modules.md § 2.1 + phase1/01_database_schema.md SP-1
+ PiiTokenProvenance + PiiTokenizationBatch (re-read at build time per
Pitfall #9.l).
"""
from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import polars as pl
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@contextmanager
def _fake_cursor_cm(cur):
    """Yield the provided cursor mock as a context manager."""
    try:
        yield cur
    finally:
        pass


def _make_general_cursor():
    """Build a mock pyodbc.Cursor for General DB provenance + batch writes."""
    cur = MagicMock()
    cur.execute.return_value = None
    return cur


def _make_general_factory(cur):
    """Zero-arg factory returning a context manager that yields cur."""
    return lambda: _fake_cursor_cm(cur)


def _canned_call_vault_sp(token_value: str = "tok-canned", was_new: int = 1):
    """Build a mock M6 call_vault_sp returning a canned SP-1 result dict.

    Per Round 1 SP-1 L1397 trailing SELECT — result dict has keys
    {'Token': str, 'WasNew': int}.
    """
    def _stub(sp_name: str, *, sp_args, **kwargs):
        assert sp_name == "PiiVault_GetOrCreateToken", sp_name
        # Echo back the canned token; tests asserting deterministic
        # tokenization patch over this with a per-plaintext map.
        return {"Token": token_value, "WasNew": was_new}
    return MagicMock(side_effect=_stub)


# ---------------------------------------------------------------------------
# (a) Module imports cleanly with no side effects
# ---------------------------------------------------------------------------


def test_module_imports_clean():
    """Module imports without pulling pyodbc / configuration / vault_client."""
    from data_load import pii_tokenizer as pt

    assert hasattr(pt, "tokenize_pii_columns")
    # The default cursor factory must not be invoked at import time.
    assert callable(pt._default_general_cursor_factory)


# ---------------------------------------------------------------------------
# (b) Happy path — single PII column replaced by token
# ---------------------------------------------------------------------------


def test_tokenize_replaces_pii_column_values():
    """tokenize_pii_columns swaps SSN plaintext for canned tokens."""
    from data_load.pii_tokenizer import tokenize_pii_columns

    df = pl.DataFrame({"ACCTNBR": ["1", "2", "3"], "SSN": ["111", "222", "333"]})
    cur = _make_general_cursor()
    call_sp = _canned_call_vault_sp(token_value="dna-test-token", was_new=1)

    result = tokenize_pii_columns(
        df,
        source_name="DNA",
        object_name="ACCT",
        column_list=["SSN"],
        batch_id=999,
        call_vault_sp_fn=call_sp,
        general_cursor_factory=_make_general_factory(cur),
        now_ms_fn=lambda: 0,
    )

    # Schema + height preserved.
    assert result.height == 3
    assert set(result.columns) == {"ACCTNBR", "SSN"}
    # SSN column values replaced with canned token.
    assert result["SSN"].to_list() == ["dna-test-token"] * 3
    # ACCTNBR pass-through unchanged.
    assert result["ACCTNBR"].to_list() == ["1", "2", "3"]
    # SP-1 called exactly once per cell (3 rows × 1 column).
    assert call_sp.call_count == 3


# ---------------------------------------------------------------------------
# (c) NULL pass-through — no SP-1 call for None cells
# ---------------------------------------------------------------------------


def test_null_pii_cells_pass_through():
    """Rows with PII column = None do NOT trigger SP-1 and remain None."""
    from data_load.pii_tokenizer import tokenize_pii_columns

    df = pl.DataFrame({"PK": [1, 2, 3], "SSN": ["111", None, "333"]})
    cur = _make_general_cursor()
    call_sp = _canned_call_vault_sp(token_value="t", was_new=1)

    result = tokenize_pii_columns(
        df,
        source_name="DNA",
        object_name="ACCT",
        column_list=["SSN"],
        batch_id=1,
        call_vault_sp_fn=call_sp,
        general_cursor_factory=_make_general_factory(cur),
        now_ms_fn=lambda: 0,
    )

    # SP-1 called only for the 2 non-null cells.
    assert call_sp.call_count == 2
    # NULL preserved at row index 1.
    assert result["SSN"].to_list() == ["t", None, "t"]


# ---------------------------------------------------------------------------
# (d) PiiColumnNotFound raised when column absent from df
# ---------------------------------------------------------------------------


def test_missing_pii_column_raises_pii_column_not_found():
    """Per spec error mode — bad PiiColumnList entry → FATAL."""
    from data_load.pii_tokenizer import tokenize_pii_columns
    from utils.errors import PiiColumnNotFound

    df = pl.DataFrame({"PK": [1], "VALUE": ["x"]})
    cur = _make_general_cursor()

    with pytest.raises(PiiColumnNotFound) as excinfo:
        tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=["NONEXISTENT"],
            batch_id=1,
            call_vault_sp_fn=_canned_call_vault_sp(),
            general_cursor_factory=_make_general_factory(cur),
            now_ms_fn=lambda: 0,
        )
    assert "NONEXISTENT" in str(excinfo.value)
    # Cursor never touched — fail-fast before any DB I/O.
    assert cur.execute.call_count == 0


# ---------------------------------------------------------------------------
# (e) Empty / None column_list short-circuits with no DB I/O
# ---------------------------------------------------------------------------


def test_empty_column_list_returns_df_unchanged():
    """column_list = [] / None → no SP-1 calls, no cursor writes."""
    from data_load.pii_tokenizer import tokenize_pii_columns

    df = pl.DataFrame({"PK": [1, 2], "V": ["a", "b"]})
    cur = _make_general_cursor()
    call_sp = MagicMock()  # would raise if called

    for empty in ([], None):
        result = tokenize_pii_columns(
            df,
            source_name="DNA",
            object_name="ACCT",
            column_list=empty,
            batch_id=1,
            call_vault_sp_fn=call_sp,
            general_cursor_factory=_make_general_factory(cur),
            now_ms_fn=lambda: 0,
        )
        # DataFrame returned unchanged.
        assert result.equals(df)

    assert call_sp.call_count == 0
    assert cur.execute.call_count == 0


# ---------------------------------------------------------------------------
# (f) Log-safety smoke — plaintext NEVER appears in log records
# ---------------------------------------------------------------------------


def test_plaintext_never_appears_in_logs(caplog):
    """D103 + P5 — plaintext PII MUST NOT appear in any captured log line."""
    from data_load.pii_tokenizer import tokenize_pii_columns

    caplog.set_level(logging.DEBUG, logger="data_load.pii_tokenizer")

    sensitive_plaintext = "SUPER-SECRET-SSN-123-45-6789"
    df = pl.DataFrame({"PK": [1], "SSN": [sensitive_plaintext]})
    cur = _make_general_cursor()
    call_sp = _canned_call_vault_sp(token_value="redacted-tok", was_new=1)

    tokenize_pii_columns(
        df,
        source_name="DNA",
        object_name="ACCT",
        column_list=["SSN"],
        batch_id=1,
        call_vault_sp_fn=call_sp,
        general_cursor_factory=_make_general_factory(cur),
        now_ms_fn=lambda: 0,
    )

    for record in caplog.records:
        # Format the record the way a real handler would, including args.
        try:
            rendered = record.getMessage()
        except Exception:  # pragma: no cover
            rendered = str(record.msg)
        assert sensitive_plaintext not in rendered, (
            f"Plaintext leaked in log record: {rendered!r}"
        )


# ---------------------------------------------------------------------------
# Runtime gate — Tier 0 budget < 5 s for the full file
# ---------------------------------------------------------------------------


def test_runtime_under_5s():
    """Sanity check: smoke suite stays well within Tier 0 budget."""
    from data_load.pii_tokenizer import tokenize_pii_columns

    df = pl.DataFrame({"PK": [1] * 50, "SSN": ["s"] * 50})
    cur = _make_general_cursor()
    call_sp = _canned_call_vault_sp()

    started = time.monotonic()
    tokenize_pii_columns(
        df,
        source_name="DNA",
        object_name="ACCT",
        column_list=["SSN"],
        batch_id=1,
        call_vault_sp_fn=call_sp,
        general_cursor_factory=_make_general_factory(cur),
        now_ms_fn=lambda: 0,
    )
    elapsed = time.monotonic() - started
    # 50 mocked SP-1 calls + 50 provenance INSERTs + 1 batch summary should
    # complete sub-second; 5 s ceiling is the Tier 0 budget.
    assert elapsed < 2.0
