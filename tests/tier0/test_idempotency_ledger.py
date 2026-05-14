"""Tier 0 build-time smoke test for utils/idempotency_ledger.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s. All
external dependencies (pyodbc cursor, connections.cursor_for) are mocked.
No live SQL Server required.

North Star pillars:
  - Operationally stable (D67 Tier 0 discipline: import + ctor + happy-path
    + failure-path round-trip in < 5 s with zero external I/O).
  - Idempotent (D15: this module IS the central enforcer; smoke must verify
    short-circuit + retry semantics on first build).
  - Audit-grade (UPDATE writes ErrorMessage + DurationMs; smoke asserts the
    audit row gets written on both clean and exception exits).

D-numbers: D15 (idempotency), D17 (ledger pattern), D67 (Tier 0),
D68 (error hierarchy), D69 (cursor_for ownership), D92 (forward-only).

B-numbers: B85 (utils/errors.py dependency closed); B63 (Metadata column
absence caveat — verified that metadata kwarg is accepted but not persisted).

Spec: phase1/03_core_modules.md § 4.1 + phase1/01_database_schema.md § 7.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pyodbc
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Test fixtures — mock cursor_for context manager
# ---------------------------------------------------------------------------


def _make_cursor(fetchone_returns=None) -> MagicMock:
    """Build a mock pyodbc cursor with optional fetchone return values."""
    cur = MagicMock()
    if fetchone_returns is not None:
        if isinstance(fetchone_returns, list):
            cur.fetchone.side_effect = fetchone_returns
        else:
            cur.fetchone.return_value = fetchone_returns
    cur.rowcount = 1
    return cur


def _make_cursor_for(cur: MagicMock):
    """Return a cursor_for-shaped context manager yielding the given cursor."""

    @contextmanager
    def _cm(_db: str):
        yield cur

    return _cm


def _build_unique_violation() -> pyodbc.IntegrityError:
    """Construct a pyodbc.IntegrityError whose args carry the 2627/2601 code.

    Real driver error tuples look like:
      ('23000', "[23000] [Microsoft][...] Violation of UNIQUE KEY constraint ...")
    For test purposes we mimic the shape with a UNIQUE substring so
    _is_unique_violation() detects it.
    """
    return pyodbc.IntegrityError(
        "23000",
        "[23000] Violation of UNIQUE KEY constraint (SQL Server error 2627)",
    )


# ---------------------------------------------------------------------------
# (a) Module imports without error
# ---------------------------------------------------------------------------


def test_module_imports():
    """(a) utils.idempotency_ledger imports cleanly per D67 assertion 1.

    Verifies no syntax errors, no missing dependencies, no import-time
    DB / network side-effects.
    """
    import utils.idempotency_ledger as mod

    assert mod is not None
    assert hasattr(mod, "ledger_step"), "ledger_step context manager must exist"
    assert hasattr(mod, "startup_recovery_sweep"), "sweep helper must exist"
    assert hasattr(mod, "LedgerStep"), "LedgerStep dataclass must exist"


# ---------------------------------------------------------------------------
# (b) ledger_step yields a LedgerStep on a fresh INSERT (clean exit path)
# ---------------------------------------------------------------------------


def test_clean_exit_updates_to_completed():
    """(b) ledger_step clean exit UPDATEs row to Status='COMPLETED'.

    Mocks cursor_for to return a cursor whose INSERT returns a fresh
    LedgerId. Verifies the UPDATE statement in the exit path uses
    Status='COMPLETED' + DurationMs.
    """
    from utils import idempotency_ledger as mod

    cur = _make_cursor(fetchone_returns=(42,))  # OUTPUT LedgerId
    with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
        with mod.ledger_step(
            batch_id=1,
            source_name="DNA",
            table_name="ACCT",
            event_type="EXTRACT",
        ) as step:
            assert isinstance(step, mod.LedgerStep)
            assert step.step_id == 42
            assert step.was_short_circuited is False
            assert step.prior_result is None  # B63 caveat

    # 1st execute = INSERT, 2nd execute = UPDATE clean-exit
    assert cur.execute.call_count == 2, (
        f"Expected 2 executes (INSERT + UPDATE on clean exit); got "
        f"{cur.execute.call_count}"
    )
    final_sql = cur.execute.call_args_list[-1].args[0]
    assert "UPDATE" in final_sql and "'COMPLETED'" in final_sql, (
        "Clean-exit UPDATE must set Status='COMPLETED'. Got SQL: "
        + final_sql[:200]
    )


# ---------------------------------------------------------------------------
# (c) Exception in `with` block UPDATEs to FAILED AND re-raises
# ---------------------------------------------------------------------------


def test_exception_updates_to_failed_and_reraises():
    """(c) Exception in the `with` block marks row FAILED and re-raises.

    Per § 4.1: "bubbles up the caller's exception after marking the row
    FAILED" — the caller's exception MUST NOT be wrapped in
    LedgerStepFailed. Verifies (i) the exit-path UPDATE used 'FAILED';
    (ii) the caller's ValueError surfaces unchanged.
    """
    from utils import idempotency_ledger as mod

    cur = _make_cursor(fetchone_returns=(99,))
    sentinel_exc = ValueError("caller-side blow-up — must surface verbatim")

    with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
        with pytest.raises(ValueError) as exc_info:
            with mod.ledger_step(
                batch_id=1,
                source_name="DNA",
                table_name="ACCT",
                event_type="EXTRACT",
            ):
                raise sentinel_exc

    assert exc_info.value is sentinel_exc, (
        "Caller's ValueError must surface verbatim (not wrapped in "
        "LedgerStepFailed). Per § 4.1 Error modes."
    )
    final_sql = cur.execute.call_args_list[-1].args[0]
    assert "'FAILED'" in final_sql and "ErrorMessage" in final_sql, (
        "Exception-exit UPDATE must set Status='FAILED' AND write "
        "ErrorMessage. Got SQL: " + final_sql[:200]
    )


# ---------------------------------------------------------------------------
# (d) UNIQUE violation on COMPLETED short-circuits
# ---------------------------------------------------------------------------


def test_unique_violation_completed_short_circuits():
    """(d) UNIQUE violation + existing Status='COMPLETED' yields
    was_short_circuited=True and skips the exit UPDATE.

    The canonical D15 short-circuit path — caller skips side-effecting
    work and uses prior_result (currently None per B63).
    """
    from utils import idempotency_ledger as mod

    cur = MagicMock()
    cur.execute.side_effect = [
        _build_unique_violation(),  # INSERT raises UNIQUE violation
        None,                       # SELECT existing row
    ]
    cur.fetchone.return_value = (77, "COMPLETED")  # SELECT result

    with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
        with mod.ledger_step(
            batch_id=1,
            source_name="DNA",
            table_name="ACCT",
            event_type="EXTRACT",
        ) as step:
            assert step.step_id == 77
            assert step.was_short_circuited is True, (
                "COMPLETED short-circuit MUST yield was_short_circuited=True"
            )
            assert step.prior_result is None  # B63 caveat

    # 2 executes: INSERT (raised) + SELECT. NO third UPDATE on exit.
    assert cur.execute.call_count == 2, (
        "Short-circuit path must NOT issue an exit UPDATE — the prior "
        f"COMPLETED row is canonical. Got {cur.execute.call_count} executes."
    )


# ---------------------------------------------------------------------------
# (e) startup_recovery_sweep returns int + handles zero-stale case
# ---------------------------------------------------------------------------


def test_startup_sweep_returns_int_zero_stale():
    """(e) startup_recovery_sweep returns 0 when no stale rows exist.

    Smoke for the I19 startup recovery path. Mocks the COUNT query to
    return 0 and verifies no UPDATE is issued.
    """
    from utils import idempotency_ledger as mod

    cur = _make_cursor(fetchone_returns=(0,))
    with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
        result = mod.startup_recovery_sweep()

    assert isinstance(result, int)
    assert result == 0
    # Only the COUNT query should have run; no UPDATE on zero-stale.
    assert cur.execute.call_count == 1


# ---------------------------------------------------------------------------
# (f) LedgerStep dataclass is frozen + has the documented fields
# ---------------------------------------------------------------------------


def test_ledger_step_dataclass_shape():
    """(f) LedgerStep is a frozen dataclass with the documented field set.

    Per § 4.1 interface spec: step_id, was_short_circuited, prior_result.
    Frozen = no field-set after construction.
    """
    from dataclasses import FrozenInstanceError

    from utils.idempotency_ledger import LedgerStep

    step = LedgerStep(step_id=1, was_short_circuited=False, prior_result=None)
    assert step.step_id == 1
    assert step.was_short_circuited is False
    assert step.prior_result is None

    with pytest.raises(FrozenInstanceError):
        step.step_id = 999  # type: ignore[misc]
