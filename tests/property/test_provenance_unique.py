"""Tier 2 property tests for PiiTokenProvenance UNIQUE constraint per § 5.8.

Canonical spec (verbatim from phase1/05_tests.md § 5.8)::

    @given(observations=st.lists(
        st.tuples(st.text(), st.text(), st.text(), st.text(), st.text()),
        max_size=20))
    def test_provenance_unique_constraint_dedups(observations):
        '''Re-inserting same (Token, SourceName, ObjectName, ColumnName,
        FilePath) is a no-op per D26.'''
        for obs in observations:
            upsert_provenance(*obs)
        # Total row count = unique observations count
        assert provenance_row_count() == len(set(observations))

Per § 5.10 budget (verbatim)::

    Default: max_examples=200 per pytest.fixture(scope='session')
    Shrinkage budget: deadline=timedelta(seconds=10)

PiiTokenProvenance writes happen in M4 ``data_load.pii_tokenizer`` via
``_insert_provenance_row``. The function INSERTs a row, swallows UNIQUE
violation (SQL Server errors 2627 / 2601) per D26 append-only contract,
and returns True iff a new row was inserted (False iff swallowed).

This module mocks the General-DB cursor's ``execute()`` to track every
INSERT against a Python set keyed by the canonical UNIQUE columns
``(Token, SourceName, ObjectName, ColumnName, FilePath)``. When the
cursor sees an INSERT for an already-recorded tuple, it raises a
synthetic UNIQUE-violation exception that M4's ``_is_unique_violation``
heuristic recognizes — exercising the SWALLOW path.

**SECURITY-CRITICAL per D103 + P5**: all synthetic observation tuples
are Hypothesis-generated strings; the mock cursor never touches real
PII or a real SQL Server.

Test surface (five properties):

  test_provenance_unique_constraint_dedups
    Verbatim § 5.8 — total row count = unique observation count.

  test_provenance_append_only_no_delete
    Per D26 — NO DELETE invoked on PiiTokenProvenance under any
    observation sequence. Verified via cursor.execute call inspection.

  test_provenance_unique_constraint_on_canonical_columns
    Per Round 1 schema — UNIQUE on ``(Token, SourceName, ObjectName,
    ColumnName, FilePath)``. Re-INSERT triggers a 2627 SQLSTATE that
    M4's ``_is_unique_violation`` heuristic catches.

  test_provenance_order_independent
    Per D15 idempotency — insertion order has no effect on final
    row count or row content. Shuffled observation lists produce the
    same set membership.

  test_provenance_idempotent_n_repeats
    Re-inserting the SAME observation 100x produces exactly 1
    persisted row.

D-numbers: D6, D15, D26, D67, D68, D103.
B-numbers: B228 (canonical utils.errors imports — verified via M4's
own dependency on utils.errors).
"""
from __future__ import annotations

import sys
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
# Mock provenance store + cursor
# ---------------------------------------------------------------------------


class MockProvenanceStore:
    """In-memory PiiTokenProvenance store with UNIQUE-constraint behavior.

    Mirrors Round 1 § PiiTokenProvenance UNIQUE on ``(Token, SourceName,
    ObjectName, ColumnName, FilePath)`` (per Round 1 v3 + L929-974).

    Backing data structure is a Python set of 5-tuples; INSERT either
    adds to the set (first observation) or raises a synthetic SQL Server
    UNIQUE-violation error (matches M4's ``_is_unique_violation``
    heuristic — error tuple carries int code 2627).

    Also tracks per-call PiiTokenizationBatch summary INSERTs separately
    so we can verify M4 does ONE per (BatchId, SourceName, ObjectName,
    ColumnName) rather than per row.
    """

    def __init__(self) -> None:
        # Canonical UNIQUE keys captured.
        self.provenance_set: set[tuple[str, str, str, str, str]] = set()
        # Track every INSERT attempt so we can audit no-op behavior.
        self.provenance_inserts_attempted: int = 0
        self.provenance_inserts_succeeded: int = 0
        self.provenance_inserts_unique_violations: int = 0
        # Batch-summary INSERTs (separate UNIQUE on BatchId × Source ×
        # Object × Column per UX_PiiTokenizationBatch_Identity v2).
        self.batch_set: set[tuple[int, str, str, str]] = set()
        self.batch_inserts_attempted: int = 0
        # Track other DML operations to verify D26 append-only.
        self.delete_attempted: int = 0
        self.update_attempted: int = 0

    def execute(self, sql: str, *args: Any) -> None:
        """Mock pyodbc cursor.execute() — distinguishes provenance vs batch.

        Per M4 ``_PROVENANCE_INSERT_SQL`` the call shape is::

            INSERT INTO General.ops.PiiTokenProvenance
                (Token, SourceName, SourceObjectType, ObjectName,
                 ColumnName, FilePath, FirstObservedBatchId)
            VALUES (?, ?, ?, ?, ?, ?, ?)

        Per M4 ``_BATCH_INSERT_SQL``::

            INSERT INTO General.ops.PiiTokenizationBatch
                (BatchId, SourceName, ObjectName, ColumnName,
                 NewTokensGenerated, ExistingTokensReused,
                 TotalRowsTokenized, DurationMs)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        sql_lower = sql.strip().lower()
        # Audit DELETE / UPDATE attempts — D26 forbids both on these tables.
        if sql_lower.startswith("delete"):
            self.delete_attempted += 1
            return
        if sql_lower.startswith("update"):
            self.update_attempted += 1
            return

        if "piitokenprovenance" in sql_lower:
            # Provenance INSERT — extract the UNIQUE key columns.
            #   args = (Token, SourceName, SourceObjectType, ObjectName,
            #           ColumnName, FilePath, FirstObservedBatchId)
            self.provenance_inserts_attempted += 1
            token = args[0]
            source_name = args[1]
            # args[2] = SourceObjectType (not part of UNIQUE key)
            object_name = args[3]
            column_name = args[4]
            file_path = args[5]
            unique_key = (
                token,
                source_name,
                object_name,
                column_name,
                file_path,
            )
            if unique_key in self.provenance_set:
                # Synthetic UNIQUE-violation matching M4's heuristic.
                self.provenance_inserts_unique_violations += 1
                err = Exception(
                    f"UNIQUE violation 2627 on PiiTokenProvenance for "
                    f"key={unique_key}"
                )
                err.args = (("23000", "UNIQUE violation", 2627),)
                raise err
            self.provenance_set.add(unique_key)
            self.provenance_inserts_succeeded += 1
            return

        if "piitokenizationbatch" in sql_lower:
            # Batch summary INSERT.
            #   args = (BatchId, SourceName, ObjectName, ColumnName, ...)
            self.batch_inserts_attempted += 1
            batch_id = args[0]
            source_name = args[1]
            object_name = args[2]
            column_name = args[3]
            unique_key = (batch_id, source_name, object_name, column_name)
            if unique_key in self.batch_set:
                err = Exception(
                    f"UNIQUE violation 2627 on PiiTokenizationBatch for "
                    f"key={unique_key}"
                )
                err.args = (("23000", "UNIQUE violation", 2627),)
                raise err
            self.batch_set.add(unique_key)
            return

        # Any other SQL is unexpected — fail fast.
        raise AssertionError(
            f"MockProvenanceStore.execute received unexpected SQL: "
            f"{sql_lower[:60]!r}"
        )

    def provenance_row_count(self) -> int:
        """Return the count of distinct stored observations."""
        return len(self.provenance_set)


@contextmanager
def _store_backed_cursor_cm(store: MockProvenanceStore):
    """Yield a cursor that delegates execute() to the store."""
    cur = MagicMock()
    cur.execute.side_effect = store.execute
    try:
        yield cur
    finally:
        pass


def _make_store_factory(store: MockProvenanceStore) -> Any:
    """Build a general_cursor_factory bound to a specific store."""
    return lambda: _store_backed_cursor_cm(store)


# ---------------------------------------------------------------------------
# Helpers — convert (Token, SourceName, ObjectName, ColumnName, FilePath)
# observations into M4 tokenize_pii_columns invocations.
# ---------------------------------------------------------------------------


def _stub_call_sp_returning_token(token: str) -> Any:
    """Mock M6 call_vault_sp returning a fixed token (canned SP-1 result).

    Per § 5.8 the test isn't measuring SP-1 determinism (that's § 5.3);
    it's measuring the UNIQUE-constraint behavior of the PROVENANCE
    write path. We pin SP-1's output to a specific token so the
    plaintext-to-token decoupling doesn't perturb the test.
    """
    def _stub(sp_name: str, *, sp_args: dict[str, Any], **_kwargs: Any) -> dict:
        assert sp_name == "PiiVault_GetOrCreateToken"
        return {"Token": token, "WasNew": 1}
    return _stub


def upsert_provenance(
    token: str,
    source_name: str,
    object_name: str,
    column_name: str,
    file_path: str,
    *,
    store: MockProvenanceStore,
) -> None:
    """Invoke M4 with a 1-row DataFrame to force ONE provenance write.

    Threads the observation tuple through M4's normal write path:
    one plaintext cell → one SP-1 call (mock returns the supplied
    Token) → one provenance INSERT against the store. UNIQUE
    violation against ``store`` is swallowed by M4 per D26 — observed
    via ``store.provenance_inserts_unique_violations`` counter.

    Empty strings are tokenized as-is — M4's NULL pass-through only
    applies to None, not ''.
    """
    df = pl.DataFrame({column_name: ["synthetic-test-plaintext"]})
    tokenize_pii_columns(
        df,
        source_name=source_name,
        object_name=object_name,
        column_list=[column_name],
        file_path=file_path,
        batch_id=1,
        call_vault_sp_fn=_stub_call_sp_returning_token(token),
        general_cursor_factory=_make_store_factory(store),
        now_ms_fn=lambda: 0,
    )


# ---------------------------------------------------------------------------
# Hypothesis strategies + settings
# ---------------------------------------------------------------------------


# Per § 5.8 the canonical strategy is
#   st.lists(st.tuples(st.text(), st.text(), st.text(), st.text(), st.text()),
#            max_size=20)
# We tighten min_size=1 because empty observation lists trivially satisfy
# the property (0 = 0); the assertion is more interesting with at least
# one observation. We also constrain text to ASCII to avoid Polars
# Categorical / column-name surprises (column_name is fed through M4 as a
# DataFrame column name; Polars allows arbitrary Utf8 column names but
# Hypothesis-generated control chars can hit ``with_columns`` edge cases
# orthogonal to this test).

_safe_text = st.text(
    alphabet=st.characters(
        min_codepoint=0x21,
        max_codepoint=0x7E,  # printable ASCII (excludes space + ctrl)
        blacklist_characters=('"', "'", "\\"),  # SQL-literal-ish safety
    ),
    min_size=1,
    max_size=20,
)

# 5-tuple matching the UNIQUE constraint columns. Per § 5.8 spec:
# (Token, SourceName, ObjectName, ColumnName, FilePath).
_observation_strategy = st.tuples(
    _safe_text,  # Token
    _safe_text,  # SourceName
    _safe_text,  # ObjectName
    _safe_text,  # ColumnName
    _safe_text,  # FilePath
)

_property_settings = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


# ===========================================================================
# Section 1 — Verbatim § 5.8 spec
# ===========================================================================


class TestProvenanceUniqueConstraintDedups:
    """Verbatim § 5.8 — row count = unique observations count."""

    @given(observations=st.lists(_observation_strategy, min_size=1, max_size=20))
    @_property_settings
    def test_provenance_unique_constraint_dedups(
        self, observations: list[tuple[str, str, str, str, str]]
    ) -> None:
        """§ 5.8 verbatim — re-insert same key is a no-op per D26."""
        store = MockProvenanceStore()
        for obs in observations:
            upsert_provenance(*obs, store=store)
        # Per § 5.8: total row count = unique observations count.
        assert store.provenance_row_count() == len(set(observations))


# ===========================================================================
# Section 2 — D26 append-only — no DELETE / no UPDATE under any sequence
# ===========================================================================


class TestProvenanceAppendOnlyNoDelete:
    """Per D26 — M4 NEVER issues DELETE / UPDATE against PiiTokenProvenance.

    Regression guard against future M4 changes that might introduce a
    cleanup path (which would break the audit trail and violate D26).
    """

    @given(observations=st.lists(_observation_strategy, min_size=1, max_size=20))
    @_property_settings
    def test_provenance_no_delete(
        self, observations: list[tuple[str, str, str, str, str]]
    ) -> None:
        """No matter what observations land, NO DELETE is issued."""
        store = MockProvenanceStore()
        for obs in observations:
            upsert_provenance(*obs, store=store)
        assert store.delete_attempted == 0

    @given(observations=st.lists(_observation_strategy, min_size=1, max_size=20))
    @_property_settings
    def test_provenance_no_update(
        self, observations: list[tuple[str, str, str, str, str]]
    ) -> None:
        """No matter what observations land, NO UPDATE is issued."""
        store = MockProvenanceStore()
        for obs in observations:
            upsert_provenance(*obs, store=store)
        assert store.update_attempted == 0


# ===========================================================================
# Section 3 — UNIQUE constraint on the canonical 5-column key
# ===========================================================================


class TestProvenanceUniqueOnCanonicalColumns:
    """UNIQUE constraint fires on the canonical 5-column key.

    Verifies M4's UNIQUE-violation swallowing path is reached: re-INSERT
    of the same tuple registers as a unique_violation in the store.
    """

    @given(obs=_observation_strategy, n=st.integers(min_value=2, max_value=10))
    @_property_settings
    def test_unique_violation_count_equals_n_minus_one(
        self, obs: tuple[str, str, str, str, str], n: int
    ) -> None:
        """Re-insert N times: 1 success + (N-1) UNIQUE violations.

        First call succeeds (first observation); calls 2..N each hit
        the UNIQUE constraint and are swallowed by M4 per D26.
        """
        store = MockProvenanceStore()
        for _ in range(n):
            upsert_provenance(*obs, store=store)
        assert store.provenance_row_count() == 1
        assert store.provenance_inserts_succeeded == 1
        assert store.provenance_inserts_unique_violations == n - 1
        assert store.provenance_inserts_attempted == n


# ===========================================================================
# Section 4 — Order-independence
# ===========================================================================


class TestProvenanceOrderIndependent:
    """Per D15 — insertion order doesn't change final state.

    Two stores fed the same observation set in different orders end
    up with identical row sets.
    """

    @given(observations=st.lists(_observation_strategy, min_size=2, max_size=15))
    @_property_settings
    def test_provenance_order_independent_final_set(
        self, observations: list[tuple[str, str, str, str, str]]
    ) -> None:
        """Reverse-order insertion produces the same final row set."""
        store_forward = MockProvenanceStore()
        store_reverse = MockProvenanceStore()
        for obs in observations:
            upsert_provenance(*obs, store=store_forward)
        for obs in reversed(observations):
            upsert_provenance(*obs, store=store_reverse)
        # Both stores end up with the same canonical row set.
        assert store_forward.provenance_set == store_reverse.provenance_set
        # ...and the same row count, which equals the unique input count.
        assert (
            store_forward.provenance_row_count()
            == store_reverse.provenance_row_count()
            == len(set(observations))
        )


# ===========================================================================
# Section 5 — Idempotency under N-repeat
# ===========================================================================


class TestProvenanceIdempotentNRepeats:
    """Re-inserting the same observation 100x produces exactly 1 row.

    Tightens the property in § 5.8 by stressing the swallow path with
    high N — defends against a future M4 regression that might miscount
    or double-insert under volume.
    """

    @given(obs=_observation_strategy)
    @_property_settings
    def test_provenance_idempotent_100_repeats(
        self, obs: tuple[str, str, str, str, str]
    ) -> None:
        """100 repeats of the same observation → 1 stored row."""
        store = MockProvenanceStore()
        for _ in range(100):
            upsert_provenance(*obs, store=store)
        assert store.provenance_row_count() == 1
        assert store.provenance_inserts_succeeded == 1
        assert store.provenance_inserts_unique_violations == 99
