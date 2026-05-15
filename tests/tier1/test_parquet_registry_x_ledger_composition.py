"""Tier 1 composition test for ``data_load.parquet_registry_client``
* ``utils.idempotency_ledger`` — end-to-end cross-module wiring.

Every other Tier 1 test in this codebase exercises ONE module with the
OTHER mocked out (parquet_registry_client tests mock ``_get_ledger_step``;
idempotency_ledger tests mock ``cursor_for``). That isolation is correct
for unit tests, but it never exercises the actual wire across the
``with _registry_ledger_step(...) as step:`` boundary — the contract is
*latent* in every current test.

Per ``docs/migration/phase1/03_core_modules.md`` § 4.1::

    Every other Round 3 module composes through idempotency_ledger.

This file is the smallest possible Tier 1 test that proves the wire
actually composes. It mocks ONLY the SQL Server cursor boundary
(``cursor_for`` in both modules → the SAME stateful cursor). Everything
between the call into :func:`parquet_registry_client.verify_parquet_snapshot`
and the eventual ``cursor.execute(...)`` calls is real code from BOTH
modules.

Composition scenarios covered (canonical 3-test cohort)
=======================================================

1. **Fresh-INSERT happy path** — verify the cross-module ordering:
   SELECT registry → INSERT IdempotencyLedger → UPDATE registry →
   UPDATE IdempotencyLedger COMPLETED. EventType is the canonical
   ``PARQUET_VERIFY`` per ``parquet_registry_client.EVENT_TYPE_VERIFY``
   and ledger key columns reflect the registry row's
   ``(BatchId, SourceName, TableName)``.

2. **Ledger-short-circuit on re-entry (D15 idempotency proof)** — when
   the ledger INSERT raises ``pyodbc.IntegrityError`` (UNIQUE violation)
   and the SELECT-existing-row reports ``Status='COMPLETED'``, the
   ledger yields ``was_short_circuited=True`` and parquet_registry_client
   MUST skip the registry UPDATE. The final ledger-UPDATE on clean exit
   is ALSO skipped (per ledger module § "do NOT UPDATE on clean exit;
   the prior COMPLETED is canonical").

3. **Failure inside the ledger-gated work** — when the registry UPDATE
   raises ``pyodbc.OperationalError`` mid-step, the ledger ``__exit__``
   marks the ledger row ``Status='FAILED'`` with ``ErrorMessage`` carrying
   the exception text, and the caller's exception surfaces UNCHANGED
   (not wrapped in :class:`LedgerStepFailed` per § 4.1 "Error modes").

Mocking strategy
================

Only ``cursor_for`` is mocked, in BOTH modules, resolving to the same
underlying stateful mock cursor object. The cursor returns canned
``fetchone()`` results in a documented order so the assertions can pin
the cross-module sequence of ``execute()`` calls.

Specifically the test does NOT mock:

  - ``data_load.parquet_registry_client._get_ledger_step`` (let the real
    lazy import resolve to the real ``ledger_step`` contextmanager)
  - any function or class in ``utils.idempotency_ledger``
  - ``data_load.parquet_registry_client._registry_ledger_step``
  - ``data_load.parquet_registry_client._flip_status``

That is the entire point: BOTH module's code paths run end-to-end in a
single test, mocked only at the SQL boundary.

D-numbers consumed
==================

D15 (idempotency mandatory at every layer), D17 (ledger pattern),
D68 (error class hierarchy), D69 (cursor_for ownership), D76 (EventType
audit-row contract), B-223 (Metadata caveat — metadata kwarg accepted
but not persisted).

Composition contract verified
=============================

This test pins the following cross-module invariants that NO existing
Tier 0 / Tier 1 test pins (because the boundary is mocked in every
existing case):

  - ``parquet_registry_client`` passes the registry row's
    ``BatchId`` / ``SourceName`` / ``TableName`` verbatim to the ledger
    key (no transformation, no lift / drop, no coercion).
  - The EventType is the module-level constant
    ``EVENT_TYPE_VERIFY = 'PARQUET_VERIFY'`` (changes to this string would
    break replay / audit-trail joins).
  - ``step.was_short_circuited`` is honored by every mutating transition
    (here proved for ``verify_parquet_snapshot``; the contract extends to
    ``mark_replicated`` / ``mark_archived`` / etc. by the same pattern but
    is not re-tested here to keep the cohort tight).
  - Failure inside the ``with _registry_ledger_step(...)`` block marks
    the ledger row FAILED via the ledger's ``__exit__`` path — i.e. the
    caller need NOT manually handle the audit row on exception.
"""
from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pyodbc
import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path so ``import data_load.parquet_registry_client``
# and ``import utils.idempotency_ledger`` both resolve regardless of where
# pytest is invoked from.
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


_REGISTRY_MODULE_KEY = "data_load.parquet_registry_client"
_LEDGER_MODULE_KEY = "utils.idempotency_ledger"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _canonical_registry_row(**overrides) -> dict:
    """Build a dict mirroring the projection from
    ``_fetch_registry_row`` (20 canonical columns in the SELECT)."""
    base = {
        "RegistryId": 42,
        "SourceName": "DNA",
        "TableName": "ACCT",
        "BatchId": 12345,
        "BusinessDate": None,
        "NetworkDrivePath": "",  # filled in per-test from tmp_path
        "SnowflakeStagePath": None,
        "SnowflakeUploadedAt": None,
        "RowCount": 1000,
        "UncompressedBytes": 4_000_000,
        "CompressedBytes": 800_000,
        "SchemaHash": "a" * 64,
        "ContentChecksum": "b" * 64,
        "StorageTier": "hot",
        "Status": "created",
        "CreatedAt": None,
        "LastVerifiedAt": None,
        "LastAccessedAt": None,
        "PurgedAt": None,
        "PurgedReason": None,
    }
    base.update(overrides)
    return base


def _unique_violation_exc() -> pyodbc.IntegrityError:
    """Mint a UNIQUE-violation IntegrityError that the ledger's
    ``_is_unique_violation`` heuristic accepts."""
    return pyodbc.IntegrityError(
        "23000",
        "[23000] Violation of UNIQUE KEY constraint "
        "'UX_IdempotencyLedger_Key'. Cannot insert duplicate key "
        "in object 'General.ops.IdempotencyLedger'. (2627)",
    )


# ---------------------------------------------------------------------------
# StatefulCursor — pinned per-test by the test author to simulate the
# DB returning known values for SELECT / OUTPUT INSERTED.LedgerId in the
# precise order the cross-module code calls them.
# ---------------------------------------------------------------------------


class StatefulCursor:
    """A stateful cursor mock that records every ``execute()`` and answers
    ``fetchone()`` from a per-test pinned queue.

    Each ``execute()`` is recorded in ``executed`` along with its args.
    Each ``fetchone()`` pops from ``fetch_queue``; if the queue is empty
    the cursor returns ``None`` (consistent with real DB behavior for an
    empty result set).

    ``description`` is set ad-hoc per call when a test wants to drive
    ``_fetch_registry_row`` (which calls ``cur.description``). For other
    paths it defaults to an empty list.

    ``rowcount`` is settable so a test can drive ``_flip_status`` to
    return 0 / 1 etc. The ``execute_raises`` deque lets a test inject
    a per-call exception (popped in order); ``None`` means no raise.
    """

    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []
        self.fetch_queue: list = []
        self.description: list = []
        self.rowcount: int = 1
        # Per-call exception side-effects. Set to a list of exceptions
        # (or None for no raise) BEFORE calling the function under test.
        self.execute_raises: list = []

    def execute(self, sql, *args):
        # Normalize pyodbc's two calling conventions so the test sees
        # one stable representation:
        #
        #   cur.execute(sql, p1, p2, p3)     → args = (p1, p2, p3)
        #   cur.execute(sql, (p1, p2, p3))   → args = ((p1, p2, p3),)
        #
        # Both bind identically against pyodbc; record both flattened.
        # ``parquet_registry_client._flip_status`` uses the sequence form;
        # ``utils.idempotency_ledger.ledger_step`` uses the splat form.
        if len(args) == 1 and isinstance(args[0], (tuple, list)):
            recorded_args: tuple = tuple(args[0])
        else:
            recorded_args = args
        # Record the call BEFORE potentially raising so the test can
        # diagnose the sequence even on the failure call.
        self.executed.append((sql, recorded_args))
        if self.execute_raises:
            exc = self.execute_raises.pop(0)
            if exc is not None:
                raise exc
        return self

    def fetchone(self):
        if not self.fetch_queue:
            return None
        return self.fetch_queue.pop(0)


# ---------------------------------------------------------------------------
# Shared fixture: a stateful cursor + a cursor_for factory + module reloads.
# ---------------------------------------------------------------------------


@pytest.fixture
def composition_env():
    """Reset both modules + return a stateful cursor + cursor_for factory.

    Yields a namespace with:

      - ``registry``: the freshly-imported ``parquet_registry_client`` module
      - ``ledger``: the freshly-imported ``utils.idempotency_ledger`` module
      - ``cursor``: the shared :class:`StatefulCursor`
      - ``cursor_for``: a contextmanager-factory ``cursor_for(_db)`` that
        yields the shared cursor

    The fixture patches ``cursor_for`` in BOTH modules so all ``with
    cursor_for(...) as cur`` paths converge on the same stateful cursor.
    The parquet_registry_client's lazy ``_get_cursor_for`` is also
    redirected so the lazy resolution returns the same patched callable.
    """
    # Force re-import so any prior test that mutated module state starts
    # fresh. Order matters: ledger is imported by parquet_registry_client
    # via lazy import, but reloading registry alone does not invalidate
    # ledger's bound ``cursor_for`` symbol.
    for key in (_LEDGER_MODULE_KEY, _REGISTRY_MODULE_KEY):
        if key in sys.modules:
            del sys.modules[key]
    ledger = importlib.import_module(_LEDGER_MODULE_KEY)
    registry = importlib.import_module(_REGISTRY_MODULE_KEY)

    cursor = StatefulCursor()

    def _cursor_for_factory(_db: str):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cursor)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    # Patch 1: ledger module's directly-imported cursor_for symbol.
    p1 = patch.object(ledger, "cursor_for", _cursor_for_factory)
    # Patch 2: parquet_registry_client's lazy resolver returns our factory.
    p2 = patch.object(
        registry, "_get_cursor_for", lambda: _cursor_for_factory
    )

    with p1, p2:
        yield type(
            "CompositionEnv",
            (),
            {
                "registry": registry,
                "ledger": ledger,
                "cursor": cursor,
                "cursor_for": _cursor_for_factory,
            },
        )

    # Teardown — leave a clean slate for downstream tests.
    for key in (_LEDGER_MODULE_KEY, _REGISTRY_MODULE_KEY):
        if key in sys.modules:
            del sys.modules[key]


# ---------------------------------------------------------------------------
# Helpers — categorize execute() calls by SQL keyword + target table.
# ---------------------------------------------------------------------------


def _categorize(executed: list[tuple[str, tuple]]) -> list[str]:
    """Return one label per executed call ordered as they happened.

    Labels:
      - 'SELECT_REGISTRY'       — SELECT FROM ParquetSnapshotRegistry
      - 'INSERT_LEDGER'         — INSERT INTO IdempotencyLedger
      - 'SELECT_LEDGER'         — SELECT FROM IdempotencyLedger (existing-row lookup)
      - 'UPDATE_REGISTRY'       — UPDATE ParquetSnapshotRegistry
      - 'UPDATE_LEDGER'         — UPDATE IdempotencyLedger
      - 'OTHER'                 — anything we didn't classify (test failure)
    """
    labels: list[str] = []
    for sql, _args in executed:
        s = " ".join(sql.split())  # collapse whitespace for sturdy matching
        if "SELECT" in s and "ParquetSnapshotRegistry" in s:
            labels.append("SELECT_REGISTRY")
        elif "INSERT INTO General.ops.IdempotencyLedger" in s:
            labels.append("INSERT_LEDGER")
        elif "SELECT" in s and "IdempotencyLedger" in s:
            labels.append("SELECT_LEDGER")
        elif "UPDATE General.ops.ParquetSnapshotRegistry" in s:
            labels.append("UPDATE_REGISTRY")
        elif "UPDATE General.ops.IdempotencyLedger" in s:
            labels.append("UPDATE_LEDGER")
        else:
            labels.append("OTHER")
    return labels


# ---------------------------------------------------------------------------
# Composition tests
# ---------------------------------------------------------------------------


class TestParquetRegistryXLedgerComposition:
    """End-to-end composition: real parquet_registry_client × real
    idempotency_ledger; only the cursor is mocked.

    Every test invokes :func:`verify_parquet_snapshot` (the canonical
    mutating transition) and asserts on the cross-module ``execute()``
    sequence captured by the shared :class:`StatefulCursor`.
    """

    # ----- Test 1: fresh-INSERT happy path -----------------------------

    def test_verify_creates_ledger_row_with_correct_event_type(
        self, composition_env, tmp_path
    ):
        """Fresh-INSERT path: SELECT registry → INSERT ledger → UPDATE
        registry → UPDATE ledger COMPLETED. EventType is 'PARQUET_VERIFY';
        ledger key carries the registry row's BatchId / SourceName /
        TableName verbatim.
        """
        env = composition_env

        # Write a real parquet stand-in so _compute_sha256 succeeds.
        payload = b"PAR1" + b"\x00" * 256 + b"PAR1"
        file_path = tmp_path / "verify_happy.parquet"
        file_path.write_bytes(payload)
        expected_sha = hashlib.sha256(payload).hexdigest()

        row = _canonical_registry_row(
            Status="created",
            NetworkDrivePath=str(file_path),
            ContentChecksum=expected_sha,
        )

        # ----- Cursor scripting -----
        # 1) SELECT FROM ParquetSnapshotRegistry → return canonical-row tuple
        # 2) INSERT INTO IdempotencyLedger ... OUTPUT INSERTED.LedgerId
        #    → return (777,)  (the new LedgerId)
        # 3) UPDATE ParquetSnapshotRegistry → rowcount=1 (set below)
        # 4) UPDATE IdempotencyLedger (clean-exit COMPLETED) — no fetchone needed
        env.cursor.description = [(k,) for k in row.keys()]
        env.cursor.fetch_queue = [
            tuple(row.values()),
            (777,),
        ]
        env.cursor.rowcount = 1

        # ----- Invoke the cross-module composition -----
        result = env.registry.verify_parquet_snapshot(
            registry_id=42, actor="pipeline"
        )

        # ----- Pin the return value -----
        assert result.status == env.registry.STATUS_VERIFIED
        assert result.sha256_verified.lower() == expected_sha.lower()
        assert result.row_count_verified == 1000
        assert result.registry_id == 42

        # ----- Pin the cross-module execute() sequence -----
        labels = _categorize(env.cursor.executed)
        assert labels == [
            "SELECT_REGISTRY",      # _fetch_registry_row
            "INSERT_LEDGER",        # ledger entry (fresh-INSERT path)
            "UPDATE_REGISTRY",      # _flip_status created → verified
            "UPDATE_LEDGER",        # ledger clean-exit COMPLETED
        ], (
            f"Cross-module execute() sequence wrong; got {labels}. "
            "Expected SELECT_REGISTRY → INSERT_LEDGER → UPDATE_REGISTRY → "
            "UPDATE_LEDGER (ledger gates BEFORE the registry UPDATE; "
            "ledger COMPLETED stamp lands AFTER the work)."
        )

        # ----- Pin the INSERT_LEDGER args (key columns + EventType) -----
        insert_sql, insert_args = env.cursor.executed[1]
        # The INSERT positional args order is (BatchId, SourceName,
        # TableName, EventType) per ledger.ledger_step's INSERT statement.
        assert insert_args == (12345, "DNA", "ACCT", "PARQUET_VERIFY"), (
            f"Ledger key columns drifted from registry row → ledger key. "
            f"Expected (12345, 'DNA', 'ACCT', 'PARQUET_VERIFY'); "
            f"got {insert_args!r}. parquet_registry_client must pass "
            "the registry row's BatchId/SourceName/TableName verbatim AND "
            "EVENT_TYPE_VERIFY='PARQUET_VERIFY' as the EventType."
        )
        assert "OUTPUT INSERTED.LedgerId" in insert_sql

        # ----- Pin the UPDATE_REGISTRY args -----
        update_reg_sql, update_reg_args = env.cursor.executed[2]
        assert "LastVerifiedAt = ?" in update_reg_sql
        assert "Status = ?" in update_reg_sql
        assert "WHERE RegistryId = ? AND Status = ?" in update_reg_sql
        # The UPDATE expects predecessor Status='created'
        assert update_reg_args[-1] == "created"
        assert update_reg_args[-2] == 42  # registry_id
        assert update_reg_args[-3] == "verified"  # next_status

        # ----- Pin the UPDATE_LEDGER (clean-exit) args -----
        update_ledg_sql, update_ledg_args = env.cursor.executed[3]
        assert "SET Status = 'COMPLETED'" in update_ledg_sql
        assert "DurationMs = ?" in update_ledg_sql
        # The trailing param is LedgerId from the OUTPUT INSERTED row.
        assert update_ledg_args[-1] == 777

    # ----- Test 2: ledger-short-circuit (D15 idempotency proof) ---------

    def test_verify_idempotent_short_circuit_via_ledger_unique_violation(
        self, composition_env, tmp_path
    ):
        """D15 canonical idempotency proof: when the ledger INSERT raises
        UNIQUE-violation and the existing row's Status is 'COMPLETED', the
        ledger yields ``was_short_circuited=True`` and parquet_registry_client
        MUST skip the registry UPDATE. The ledger's own clean-exit UPDATE
        is also skipped (per ledger module: "do NOT UPDATE on clean exit;
        the prior COMPLETED is canonical").
        """
        env = composition_env

        # File must exist + hash must match — even on the short-circuit
        # path, parquet_registry_client computes the hash BEFORE opening
        # the ledger context (the hash check is part of the legality check).
        payload = b"PAR1" + b"\x00" * 100
        file_path = tmp_path / "verify_idempotent.parquet"
        file_path.write_bytes(payload)
        expected_sha = hashlib.sha256(payload).hexdigest()

        # Registry row reports Status='created' (NOT 'verified' — that
        # would activate the early-return cache path which BYPASSES the
        # ledger entirely; we want to exercise the ledger short-circuit).
        row = _canonical_registry_row(
            Status="created",
            NetworkDrivePath=str(file_path),
            ContentChecksum=expected_sha,
        )

        # ----- Cursor scripting -----
        # 1) SELECT FROM ParquetSnapshotRegistry → canonical row tuple
        # 2) INSERT INTO IdempotencyLedger → RAISES UNIQUE violation
        # 3) SELECT FROM IdempotencyLedger (existing-row lookup)
        #    → return (555, 'COMPLETED')
        # The ledger SHORT-CIRCUITS here. parquet_registry_client sees
        # was_short_circuited=True and skips its UPDATE. The ledger's
        # ``return`` statement on the COMPLETED branch prevents the final
        # clean-exit UPDATE.
        env.cursor.description = [(k,) for k in row.keys()]
        env.cursor.fetch_queue = [
            tuple(row.values()),       # 1) SELECT registry
            (555, "COMPLETED"),        # 3) SELECT existing ledger row
        ]
        env.cursor.execute_raises = [
            None,                      # 1) SELECT registry — no raise
            _unique_violation_exc(),   # 2) INSERT ledger — raise UNIQUE
            None,                      # 3) SELECT ledger — no raise
        ]

        # ----- Invoke -----
        result = env.registry.verify_parquet_snapshot(
            registry_id=42, actor="pipeline"
        )

        # ----- Pin the return value -----
        # parquet_registry_client returns a ParquetVerifyResult populated
        # from the fresh hash + the SELECT'd row (the function doesn't
        # know whether the ledger short-circuited from the result's
        # perspective; the wire contract is the EXECUTE sequence below).
        assert result.status == env.registry.STATUS_VERIFIED
        assert result.sha256_verified.lower() == expected_sha.lower()

        # ----- Pin the cross-module execute() sequence -----
        labels = _categorize(env.cursor.executed)
        assert labels == [
            "SELECT_REGISTRY",   # _fetch_registry_row
            "INSERT_LEDGER",     # ledger entry — raises UNIQUE
            "SELECT_LEDGER",     # ledger existing-row lookup → COMPLETED
            # IMPORTANT: NO UPDATE_REGISTRY (parquet_registry_client guard:
            #   ``if not step.was_short_circuited:``)
            # IMPORTANT: NO UPDATE_LEDGER (ledger short-circuit branch:
            #   ``return  # do NOT UPDATE on clean exit``)
        ], (
            f"Idempotent short-circuit wire wrong; got {labels}. "
            "D15 + D17 contract: when the ledger reports a prior "
            "COMPLETED row, NEITHER the registry UPDATE NOR the ledger "
            "clean-exit UPDATE may fire. Both modules must respect the "
            "short-circuit signal."
        )

        # ----- Pin the SELECT_LEDGER args (key columns) -----
        select_sql, select_args = env.cursor.executed[2]
        assert select_args == (12345, "DNA", "ACCT", "PARQUET_VERIFY"), (
            f"Ledger existing-row lookup used the wrong key; got "
            f"{select_args!r}. Must use the same BatchId/SourceName/"
            "TableName/EventType the INSERT used."
        )
        assert "FROM General.ops.IdempotencyLedger" in select_sql
        assert "WHERE BatchId = ?" in select_sql

    # ----- Test 3: failure inside the ledger-gated work -----------------

    def test_verify_failure_inside_ledger_marks_row_failed_and_reraises(
        self, composition_env, tmp_path
    ):
        """If the registry UPDATE raises mid-step (e.g. transient DB
        OperationalError), the ledger's ``__exit__`` marks the ledger
        row Status='FAILED' with ErrorMessage carrying the exception
        text, then re-raises the caller's exception UNCHANGED.

        This pins the cross-module failure-path contract: the caller does
        NOT need to manually mark the ledger row FAILED — composition
        handles it via the contextmanager exit path. The exception that
        surfaces is the ORIGINAL pyodbc.OperationalError (NOT wrapped in
        LedgerStepFailed).
        """
        env = composition_env

        payload = b"PAR1" + b"\x00" * 64
        file_path = tmp_path / "verify_failure.parquet"
        file_path.write_bytes(payload)
        expected_sha = hashlib.sha256(payload).hexdigest()

        row = _canonical_registry_row(
            Status="created",
            NetworkDrivePath=str(file_path),
            ContentChecksum=expected_sha,
        )

        sentinel_exc = pyodbc.OperationalError(
            "08S01",
            "[08S01] Communication link failure (10054): "
            "simulated DB hiccup during UPDATE",
        )

        # ----- Cursor scripting -----
        # 1) SELECT registry → canonical row
        # 2) INSERT ledger → return (888,) on OUTPUT
        # 3) UPDATE registry → RAISES OperationalError
        # 4) ledger's __exit__ UPDATE → marks FAILED (no fetchone needed)
        env.cursor.description = [(k,) for k in row.keys()]
        env.cursor.fetch_queue = [
            tuple(row.values()),
            (888,),
        ]
        env.cursor.execute_raises = [
            None,           # 1) SELECT registry
            None,           # 2) INSERT ledger
            sentinel_exc,   # 3) UPDATE registry — raises
            None,           # 4) UPDATE ledger FAILED — no raise
        ]

        # ----- Invoke + catch -----
        with pytest.raises(pyodbc.OperationalError) as exc_info:
            env.registry.verify_parquet_snapshot(
                registry_id=42, actor="pipeline"
            )

        # ----- Pin: the surfaced exception is the ORIGINAL, not wrapped -----
        assert exc_info.value is sentinel_exc, (
            "Composition contract: parquet_registry_client must surface "
            "the caller's exception verbatim; the ledger context manager "
            "MUST NOT wrap it in LedgerStepFailed."
        )

        # ----- Pin the cross-module execute() sequence -----
        labels = _categorize(env.cursor.executed)
        assert labels == [
            "SELECT_REGISTRY",   # _fetch_registry_row
            "INSERT_LEDGER",     # ledger entry — fresh INSERT
            "UPDATE_REGISTRY",   # _flip_status — RAISES inside ledger ctx
            "UPDATE_LEDGER",     # ledger __exit__ marks FAILED
        ], (
            f"Failure-path wire wrong; got {labels}. The ledger __exit__ "
            "MUST issue the FAILED-UPDATE even when the caller's work "
            "raised — that's the audit-trail invariant."
        )

        # ----- Pin the UPDATE_LEDGER args carry the failure context -----
        update_ledg_sql, update_ledg_args = env.cursor.executed[3]
        assert "SET Status = 'FAILED'" in update_ledg_sql
        assert "DurationMs = ?" in update_ledg_sql
        assert "ErrorMessage = ?" in update_ledg_sql
        # Args order is (DurationMs, ErrorMessage, LedgerId).
        assert isinstance(update_ledg_args[0], int)  # DurationMs
        assert isinstance(update_ledg_args[1], str)  # ErrorMessage
        assert "simulated DB hiccup" in update_ledg_args[1], (
            "Ledger FAILED-UPDATE must carry the caller's exception text "
            "in ErrorMessage so the audit trail is forensically complete."
        )
        assert update_ledg_args[2] == 888, (
            f"Ledger __exit__ must target the LedgerId from the ENTRY "
            f"INSERT's OUTPUT INSERTED clause; got {update_ledg_args[2]!r} "
            "instead of 888."
        )
