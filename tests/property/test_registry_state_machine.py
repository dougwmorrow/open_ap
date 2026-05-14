"""Tier 2 property tests for ``data_load.parquet_registry_client`` state machine — § 5.5.

Per canonical Round 5 spec § 5.5 (ParquetSnapshotRegistry status-machine state graph):

    @given(transition_sequence=st.lists(
        st.sampled_from(['verify', 'replicate', 'archive', 'purge', 'mark_missing']),
        max_size=10,
    ))
    def test_registry_status_transitions_never_invalid(transition_sequence):
        \"\"\"Every transition path produces valid Status; no path produces invalid
        predecessor without raising.\"\"\"
        registry_id = create_test_row(status='created')
        for transition in transition_sequence:
            try:
                apply_transition(registry_id, transition)
            except RegistryStatusInvalid:
                pass  # Expected when transition not valid from current state
            assert query_status(registry_id) in VALID_STATUSES

Coverage:

* Hypothesis explores the (initial state x transition sequence) cross-product;
  with ``max_size=10`` and 7 states, the reachable transition graph is finite
  but combinatorially deep enough to require ``max_examples=1000`` per § 5.10.
* No live DB. The M3 module's lazy ``_get_cursor_for`` / ``_get_ledger_step``
  hooks are patched at the module level (B-214 lesson — no bare ``sys.modules``
  writes). Per-test, an in-memory dict simulates the registry row's status
  column so the state machine is exercised end-to-end.
* Per § 5.5 + D17, re-applying the same transition (idempotency) MUST be a
  no-op — the test sequence may contain repeats and the row's status must
  end the loop in a valid state.

Edge-case generator (§ 5.9):

* ParquetSnapshotRegistry Status enum + transition graph — exactly the
  generator listed at § 5.9 "NEW: ParquetSnapshotRegistry Status enum +
  transition graph (per § 5.5)".

§ 5.10 budget:

* This file uses Hypothesis's ``combinatorial`` profile per § 5.10:
  ``max_examples=1000`` (consistent with numpy test suite ceiling),
  ``deadline=timedelta(seconds=10)``. The profile is REGISTERED by Agent A
  in ``tests/property/conftest.py`` per § 5.10 wording and SELECTED here
  via ``hypothesis.settings(parent=combinatorial)`` per-test. If the
  registered profile is absent (e.g. running this file in isolation),
  Hypothesis falls back to its built-in defaults — tests still pass but
  with less depth.

Discipline lessons applied (per parent-agent prompt):

* B-228 — exception classes are imported from canonical ``utils.errors``,
  NEVER redefined locally.
* B-214 — DB / ledger collaborators are stubbed via ``patch.object`` at
  module attributes (``_get_cursor_for`` / ``_get_ledger_step``), NOT
  bare ``sys.modules`` writes.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from data_load import parquet_registry_client as mod
from utils.errors import RegistryStatusInvalid

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical valid statuses — referenced verbatim from the module's
# ALL_STATUSES export (per CK_ParquetSnapshotRegistry_Status DDL constraint).
# ---------------------------------------------------------------------------

VALID_STATUSES = frozenset(mod.ALL_STATUSES)

# Transition names in the canonical § 5.5 alphabet
TRANSITION_NAMES = ["verify", "replicate", "archive", "purge", "mark_missing"]


# ---------------------------------------------------------------------------
# In-memory fake registry — single source of truth for status during a
# property example. Every transition function is patched to consult + mutate
# this dict instead of hitting SQL Server.
# ---------------------------------------------------------------------------


def _canonical_row(registry_id: int, status: str, file_path: Path) -> dict:
    """Build a canonical registry-row dict matching the module's projection."""
    return {
        "RegistryId": registry_id,
        "SourceName": "DNA",
        "TableName": "ACCT",
        "BatchId": 12345,
        "BusinessDate": date(2026, 5, 13),
        "NetworkDrivePath": str(file_path),
        "SnowflakeStagePath": None,
        "SnowflakeUploadedAt": None,
        "RowCount": 100,
        "UncompressedBytes": 4_000_000,
        "CompressedBytes": 800_000,
        "SchemaHash": "a" * 64,
        # ContentChecksum is filled in by the test with the real SHA of
        # whatever bytes get written; required for verify to succeed.
        "ContentChecksum": None,
        "StorageTier": "hot",
        "Status": status,
        "CreatedAt": datetime(2026, 5, 13, 0, 0, 0),
        "LastVerifiedAt": None,
        "LastAccessedAt": None,
        "PurgedAt": None,
        "PurgedReason": None,
    }


class _FakeRegistry:
    """In-memory registry standing in for SQL Server during property tests.

    Stores one row keyed by ``registry_id``. Exposes:
      * ``query_status(registry_id)`` — read current Status.
      * ``set_status(registry_id, status)`` — direct write (used by the
        fake UPDATE).
    """

    def __init__(self, row: dict) -> None:
        self._row = row

    def get_row(self) -> dict:
        return dict(self._row)  # defensive copy

    def query_status(self) -> str:
        return self._row["Status"]

    def set_status(self, new_status: str) -> None:
        self._row["Status"] = new_status

    def set_field(self, key: str, value) -> None:
        self._row[key] = value


def _make_cursor_for_factory(registry: _FakeRegistry):
    """Build a cursor_for factory whose UPDATE flips the in-memory registry row.

    The cursor mock interprets each ``execute(sql, params)`` call:
      * ``SELECT ...`` -> populates ``fetchone`` from ``registry.get_row()``
      * ``UPDATE ...`` -> mutates ``registry`` based on params; rowcount=1
                          when the prior-status CHECK predicate matches,
                          else 0 (race-loss path inside the module).

    Returns ``(factory, cursor_mock)``; ``cursor_mock`` is shared across
    all ``with cursor_for('General')`` contexts within one property example.
    """
    cursor = MagicMock()

    def _execute(sql, *params):
        # Flatten params: pyodbc accepts (sql, p1, p2, ...) OR (sql, tuple)
        if len(params) == 1 and isinstance(params[0], (tuple, list)):
            params = tuple(params[0])

        if sql.lstrip().upper().startswith("SELECT"):
            row = registry.get_row()
            cursor.fetchone.return_value = tuple(row.values())
            cursor.description = [(k,) for k in row.keys()]
            cursor.rowcount = 1
            return

        if sql.lstrip().upper().startswith("UPDATE"):
            # Parse: ... SET ... Status = ? WHERE RegistryId = ? AND Status = ?
            # Last 3 params (in order): new_status, registry_id, expected_current
            # But some UPDATEs (e.g. LastAccessedAt) only set fields and have
            # WHERE RegistryId = ? — handle both shapes.
            if "Status = ?" in sql and "AND Status = ?" in sql:
                # Status-flipping UPDATE
                new_status = params[-3]
                expected_current = params[-1]
                if registry.query_status() == expected_current:
                    # Apply extra SET clauses (LastVerifiedAt, etc) before flip
                    if "LastVerifiedAt = ?" in sql:
                        registry.set_field("LastVerifiedAt", params[0])
                    if "SnowflakeStagePath = ?" in sql:
                        registry.set_field("SnowflakeStagePath", params[0])
                        registry.set_field("SnowflakeUploadedAt", params[1])
                    if "StorageTier = ?" in sql:
                        registry.set_field("StorageTier", params[0])
                    if "PurgedAt = ?" in sql:
                        registry.set_field("PurgedAt", params[0])
                        registry.set_field("PurgedReason", params[1])
                    registry.set_status(new_status)
                    cursor.rowcount = 1
                else:
                    cursor.rowcount = 0
            else:
                # Fire-and-forget side updates like LastAccessedAt — no-op
                cursor.rowcount = 1
            return

        cursor.rowcount = 0

    cursor.execute.side_effect = _execute

    def _factory(_db: str):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cursor)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    return _factory, cursor


def _make_ledger_step_factory():
    """Build a ledger_step factory returning a context that never short-
    circuits (so every transition's UPDATE actually runs through the cursor).
    """
    step = MagicMock()
    step.was_short_circuited = False
    step.step_id = 1
    step.prior_result = None

    def _factory(**_kwargs):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=step)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    return _factory


# ---------------------------------------------------------------------------
# Transition dispatcher — maps the § 5.5 alphabet to module functions.
# ---------------------------------------------------------------------------


def _apply_transition(name: str, registry_id: int, file_path: Path) -> None:
    """Invoke the module function for transition ``name``.

    Mirrors the spec's ``apply_transition`` shim. Re-raises
    ``RegistryStatusInvalid`` so the caller can suppress it per § 5.5.
    """
    if name == "verify":
        mod.verify_parquet_snapshot(registry_id=registry_id, actor="hypothesis")
    elif name == "replicate":
        mod.mark_replicated(registry_id=registry_id, replica_target="snowflake:test")
    elif name == "archive":
        mod.mark_archived(registry_id=registry_id, archive_location="cold:test")
    elif name == "purge":
        mod.mark_purged(registry_id=registry_id, retention_batch_id=999)
    elif name == "mark_missing":
        mod.mark_missing(registry_id=registry_id, detected_by="hypothesis")
    else:
        raise AssertionError(f"unknown transition name: {name!r}")


# ---------------------------------------------------------------------------
# Hypothesis settings — § 5.10 combinatorial budget for state-machine tests.
#
# We attempt to inherit Agent A's registered 'combinatorial' profile; if it
# isn't registered (e.g. running this file in isolation), Hypothesis uses
# its default profile — tests still pass but explore fewer examples.
# ---------------------------------------------------------------------------


def _state_machine_settings() -> settings:
    """Return Hypothesis settings configured for state-graph exploration.

    Per § 5.10:
      * Combinatorial-heavy modules (transition state graphs): max_examples=1000
      * Shrinkage budget: deadline=timedelta(seconds=10) per example
    """
    return settings(
        max_examples=1000,
        deadline=timedelta(seconds=10),
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    )


# ---------------------------------------------------------------------------
# § 5.5 canonical property test
# ---------------------------------------------------------------------------


@_state_machine_settings()
@given(
    transition_sequence=st.lists(
        st.sampled_from(TRANSITION_NAMES), min_size=0, max_size=10
    )
)
def test_registry_status_transitions_never_invalid(transition_sequence, tmp_path_factory):
    """Every transition path produces a valid Status; no path produces an
    invalid predecessor without raising.

    Per § 5.5 (canonical):

        registry_id = create_test_row(status='created')
        for transition in transition_sequence:
            try:
                apply_transition(registry_id, transition)
            except RegistryStatusInvalid:
                pass
            assert query_status(registry_id) in VALID_STATUSES
    """
    # Build a fresh fake registry + on-disk Parquet file per example
    tmp_path = tmp_path_factory.mktemp("registry_sm")
    payload = b"PAR1FAKE" * 16
    file_path = tmp_path / f"{abs(hash(tuple(transition_sequence))) % 10**8}.parquet"
    file_path.write_bytes(payload)

    import hashlib

    sha = hashlib.sha256(payload).hexdigest()

    row = _canonical_row(registry_id=42, status=mod.STATUS_CREATED, file_path=file_path)
    row["ContentChecksum"] = sha
    registry = _FakeRegistry(row)

    cursor_factory, _cursor = _make_cursor_for_factory(registry)
    ledger_factory = _make_ledger_step_factory()

    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), patch.object(
        mod, "_get_ledger_step", return_value=ledger_factory
    ):
        for transition in transition_sequence:
            try:
                _apply_transition(transition, 42, file_path)
            except RegistryStatusInvalid:
                # Expected when the transition isn't legal from the current state
                pass
            assert registry.query_status() in VALID_STATUSES, (
                f"Registry status escaped the canonical set after applying "
                f"{transition!r}: got {registry.query_status()!r}, "
                f"sequence so far up to that transition included: "
                f"{transition_sequence}"
            )


# ---------------------------------------------------------------------------
# Additional property: re-applying the same transition is a no-op (D17)
# ---------------------------------------------------------------------------


@_state_machine_settings()
@given(
    transition_sequence=st.lists(
        st.sampled_from(TRANSITION_NAMES), min_size=1, max_size=8
    )
)
def test_repeated_transition_is_idempotent(transition_sequence, tmp_path_factory):
    """D17: After applying a transition, re-applying the SAME transition
    must NOT change the Status — it's either a no-op (status already in the
    target) or raises RegistryStatusInvalid (illegal repeat from new state).

    The fake registry preserves Status across the re-call, so the final
    Status after the doubled call must equal the Status after the single
    call.
    """
    tmp_path = tmp_path_factory.mktemp("registry_idempotent")
    payload = b"PAR1FAKE" * 16
    file_path = tmp_path / f"{abs(hash(tuple(transition_sequence))) % 10**8}.parquet"
    file_path.write_bytes(payload)

    import hashlib

    sha = hashlib.sha256(payload).hexdigest()

    row = _canonical_row(registry_id=42, status=mod.STATUS_CREATED, file_path=file_path)
    row["ContentChecksum"] = sha
    registry = _FakeRegistry(row)

    cursor_factory, _cursor = _make_cursor_for_factory(registry)
    ledger_factory = _make_ledger_step_factory()

    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), patch.object(
        mod, "_get_ledger_step", return_value=ledger_factory
    ):
        for transition in transition_sequence:
            # First application: capture pre-Status and post-Status
            try:
                _apply_transition(transition, 42, file_path)
            except RegistryStatusInvalid:
                pass
            status_after_first = registry.query_status()

            # Second application of the same transition: must not change Status
            try:
                _apply_transition(transition, 42, file_path)
            except RegistryStatusInvalid:
                pass
            status_after_second = registry.query_status()

            assert status_after_first == status_after_second, (
                f"D17 violation: re-applying {transition!r} changed Status "
                f"from {status_after_first!r} to {status_after_second!r}"
            )


# ---------------------------------------------------------------------------
# Additional property: terminal states (purged, missing) cannot transition out
# ---------------------------------------------------------------------------


@_state_machine_settings()
@given(transition=st.sampled_from(TRANSITION_NAMES))
def test_purged_is_terminal_for_all_transitions(transition, tmp_path_factory):
    """D26 + § 1.3: ``purged`` is a terminal state. ANY transition attempt
    from purged MUST leave Status='purged'.

    Per CLAUDE.md gotcha:

        purged is terminal per D26 append-only audit posture
    """
    tmp_path = tmp_path_factory.mktemp("registry_terminal_purged")
    file_path = tmp_path / "f.parquet"
    file_path.write_bytes(b"X")

    row = _canonical_row(registry_id=42, status=mod.STATUS_PURGED, file_path=file_path)
    registry = _FakeRegistry(row)

    cursor_factory, _cursor = _make_cursor_for_factory(registry)
    ledger_factory = _make_ledger_step_factory()

    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), patch.object(
        mod, "_get_ledger_step", return_value=ledger_factory
    ):
        try:
            _apply_transition(transition, 42, file_path)
        except RegistryStatusInvalid:
            pass

    assert registry.query_status() == mod.STATUS_PURGED, (
        f"purged is terminal — but Status flipped to {registry.query_status()!r} "
        f"after attempted transition {transition!r}"
    )


@_state_machine_settings()
@given(transition=st.sampled_from(TRANSITION_NAMES))
def test_missing_is_terminal_under_automated_flow(transition, tmp_path_factory):
    """``missing`` is terminal under the automated transition surface — only
    manual operator action can move it back (e.g. operator re-uploads the
    file and runs a manual SP). The module's automated functions MUST never
    flip missing -> anything else.
    """
    tmp_path = tmp_path_factory.mktemp("registry_terminal_missing")
    file_path = tmp_path / "f.parquet"
    file_path.write_bytes(b"X")

    row = _canonical_row(registry_id=42, status=mod.STATUS_MISSING, file_path=file_path)
    registry = _FakeRegistry(row)

    cursor_factory, _cursor = _make_cursor_for_factory(registry)
    ledger_factory = _make_ledger_step_factory()

    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), patch.object(
        mod, "_get_ledger_step", return_value=ledger_factory
    ):
        try:
            _apply_transition(transition, 42, file_path)
        except RegistryStatusInvalid:
            pass

    assert registry.query_status() == mod.STATUS_MISSING, (
        f"missing is terminal under automated flow — but Status flipped to "
        f"{registry.query_status()!r} after attempted transition {transition!r}"
    )


# ---------------------------------------------------------------------------
# Additional property: is_legal_transition matches the actual function's
# accept/reject decision (pure-vs-effectful consistency).
# ---------------------------------------------------------------------------


@_state_machine_settings()
@given(
    current=st.sampled_from(list(mod.ALL_STATUSES)),
    transition=st.sampled_from(TRANSITION_NAMES),
)
def test_is_legal_transition_matches_module_behavior(current, transition, tmp_path_factory):
    """``is_legal_transition`` is a pure mirror of the state-machine graph.
    A transition the graph rejects MUST raise RegistryStatusInvalid; a
    transition the graph accepts MUST NOT raise (for the documented happy
    path).

    Self-loops (``X -> X``) return True from ``is_legal_transition`` and
    the module short-circuits as a no-op — they are tested at
    test_repeated_transition_is_idempotent above.
    """
    transition_to_status = {
        "verify": mod.STATUS_VERIFIED,
        "replicate": mod.STATUS_REPLICATED,
        "archive": mod.STATUS_ARCHIVED,
        "purge": mod.STATUS_PURGED,
        "mark_missing": mod.STATUS_MISSING,
    }
    target = transition_to_status[transition]

    is_legal = mod.is_legal_transition(current, target)

    tmp_path = tmp_path_factory.mktemp("registry_consistency")
    payload = b"PAR1FAKE"
    file_path = tmp_path / "f.parquet"
    file_path.write_bytes(payload)

    import hashlib

    sha = hashlib.sha256(payload).hexdigest()

    row = _canonical_row(registry_id=42, status=current, file_path=file_path)
    row["ContentChecksum"] = sha
    registry = _FakeRegistry(row)

    cursor_factory, _cursor = _make_cursor_for_factory(registry)
    ledger_factory = _make_ledger_step_factory()

    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), patch.object(
        mod, "_get_ledger_step", return_value=ledger_factory
    ):
        raised = False
        try:
            _apply_transition(transition, 42, file_path)
        except RegistryStatusInvalid:
            raised = True

    if is_legal:
        # No raise expected. Status flipped to target (or stayed if it was
        # already target via the idempotent self-loop short-circuit).
        assert not raised, (
            f"is_legal_transition({current!r}, {target!r}) said True but the "
            f"module raised RegistryStatusInvalid"
        )
        assert registry.query_status() == target, (
            f"legal transition {transition!r} from {current!r} did not flip "
            f"Status to {target!r} — landed in {registry.query_status()!r}"
        )
    else:
        # is_legal said False — module must raise AND Status must remain unchanged
        assert raised, (
            f"is_legal_transition({current!r}, {target!r}) said False but the "
            f"module did not raise RegistryStatusInvalid"
        )
        assert registry.query_status() == current, (
            f"illegal transition {transition!r} from {current!r} mutated Status "
            f"to {registry.query_status()!r} despite raising"
        )
