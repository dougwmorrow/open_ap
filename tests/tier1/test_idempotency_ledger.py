"""Tier 1 unit test for utils/idempotency_ledger.py.

Per D70 Tier 1 — per-edge-case + per-error-path coverage; mocks pyodbc
cursor; no live SQL Server.

North Star pillars:
  - Idempotent (D15: every short-circuit / retry / concurrent path tested).
  - Operationally stable (every error path surfaces the documented base
    type per D68 → exit code per D74).
  - Audit-grade (UPDATE writes preserve DurationMs + ErrorMessage; sweep
    writes RecoveryAction='STARTUP_SWEEP_FAILED' per § 4.1).
  - Traceability (B-223 caveat verified — metadata kwarg accepted but never
    persisted to ledger row; prior_result always None).

Spec: phase1/03_core_modules.md § 4.1 + phase1/01_database_schema.md § 7.

B-numbers: B85 (utils/errors.py); B-223 (metadata-column-absence caveat).
"""
from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pyodbc
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_cursor(fetchone_returns=None, *, rowcount: int = 1) -> MagicMock:
    cur = MagicMock()
    if fetchone_returns is not None:
        if isinstance(fetchone_returns, list):
            cur.fetchone.side_effect = fetchone_returns
        else:
            cur.fetchone.return_value = fetchone_returns
    cur.rowcount = rowcount
    return cur


def _make_cursor_for(cur: MagicMock):
    @contextmanager
    def _cm(_db: str):
        yield cur

    return _cm


def _make_multi_cursor_for(cursors: list):
    """For tests where each cursor_for() call gets a fresh cursor."""
    iterator = iter(cursors)

    @contextmanager
    def _cm(_db: str):
        yield next(iterator)

    return _cm


def _unique_violation(message: str = "Violation of UNIQUE KEY constraint (2627)") -> pyodbc.IntegrityError:
    return pyodbc.IntegrityError("23000", f"[23000] {message}")


def _fk_violation() -> pyodbc.IntegrityError:
    """A non-UNIQUE IntegrityError (foreign key) that must NOT short-circuit.

    Uses the canonical SQL Server FK-violation phrasing so the detector
    heuristic (which now requires "Violation of UNIQUE KEY constraint" /
    "Cannot insert duplicate key" / etc.) correctly rejects this.
    """
    return pyodbc.IntegrityError(
        "23000",
        "[23000] The INSERT statement conflicted with the FOREIGN KEY constraint.",
    )


# ---------------------------------------------------------------------------
# Validation — param contract per § 4.1
# ---------------------------------------------------------------------------


class TestParameterValidation:

    def test_batch_id_none_raises_config_error(self):
        from utils.errors import LedgerConfigError
        from utils import idempotency_ledger as mod

        with patch.object(mod, "cursor_for", _make_cursor_for(_make_cursor())):
            with pytest.raises(LedgerConfigError):
                with mod.ledger_step(
                    batch_id=None,  # type: ignore[arg-type]
                    source_name="DNA",
                    table_name="ACCT",
                    event_type="EXTRACT",
                ):
                    pass

    def test_batch_id_zero_raises_config_error(self):
        from utils.errors import LedgerConfigError
        from utils import idempotency_ledger as mod

        with patch.object(mod, "cursor_for", _make_cursor_for(_make_cursor())):
            with pytest.raises(LedgerConfigError):
                with mod.ledger_step(
                    batch_id=0,
                    source_name="DNA",
                    table_name="ACCT",
                    event_type="EXTRACT",
                ):
                    pass

    def test_batch_id_negative_raises_config_error(self):
        from utils.errors import LedgerConfigError
        from utils import idempotency_ledger as mod

        with patch.object(mod, "cursor_for", _make_cursor_for(_make_cursor())):
            with pytest.raises(LedgerConfigError):
                with mod.ledger_step(
                    batch_id=-1,
                    source_name="DNA",
                    table_name="ACCT",
                    event_type="EXTRACT",
                ):
                    pass

    @pytest.mark.parametrize("field,value", [
        ("source_name", ""),
        ("table_name", ""),
        ("event_type", ""),
    ])
    def test_empty_string_field_raises_config_error(self, field, value):
        from utils.errors import LedgerConfigError
        from utils import idempotency_ledger as mod

        kwargs = dict(
            batch_id=1,
            source_name="DNA",
            table_name="ACCT",
            event_type="EXTRACT",
        )
        kwargs[field] = value
        with patch.object(mod, "cursor_for", _make_cursor_for(_make_cursor())):
            with pytest.raises(LedgerConfigError):
                with mod.ledger_step(**kwargs):
                    pass


# ---------------------------------------------------------------------------
# Entry path — fresh INSERT
# ---------------------------------------------------------------------------


class TestFreshInsertPath:

    def test_fresh_insert_yields_step_id_from_output_clause(self):
        from utils import idempotency_ledger as mod

        cur = _make_cursor(fetchone_returns=(123,))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with mod.ledger_step(
                batch_id=42,
                source_name="DNA",
                table_name="ACCT",
                event_type="EXTRACT",
            ) as step:
                assert step.step_id == 123
                assert step.was_short_circuited is False
                assert step.prior_result is None

    def test_fresh_insert_passes_canonical_args(self):
        from utils import idempotency_ledger as mod

        cur = _make_cursor(fetchone_returns=(1,))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with mod.ledger_step(
                batch_id=42,
                source_name="DNA",
                table_name="ACCT",
                event_type="EXTRACT",
            ):
                pass

        insert_call = cur.execute.call_args_list[0]
        sql = insert_call.args[0]
        args = insert_call.args[1:]
        assert "INSERT INTO General.ops.IdempotencyLedger" in sql
        assert "OUTPUT INSERTED.LedgerId" in sql
        assert args == (42, "DNA", "ACCT", "EXTRACT")

    def test_insert_output_no_row_raises_config_error(self):
        """If the INSERT...OUTPUT returns no row (driver / table misconfig),
        we must NOT silently yield step_id=None."""
        from utils.errors import LedgerConfigError
        from utils import idempotency_ledger as mod

        cur = MagicMock()
        cur.fetchone.return_value = None  # explicitly None (vs MagicMock default)
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with pytest.raises(LedgerConfigError):
                with mod.ledger_step(
                    batch_id=1,
                    source_name="DNA",
                    table_name="ACCT",
                    event_type="EXTRACT",
                ):
                    pass


# ---------------------------------------------------------------------------
# UNIQUE violation branches — COMPLETED short-circuit / IN_PROGRESS / FAILED retry
# ---------------------------------------------------------------------------


class TestUniqueViolationBranches:

    def test_completed_short_circuits_without_exit_update(self):
        from utils import idempotency_ledger as mod

        cur = MagicMock()
        cur.execute.side_effect = [_unique_violation(), None]
        cur.fetchone.return_value = (50, "COMPLETED")

        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with mod.ledger_step(
                batch_id=1,
                source_name="DNA",
                table_name="ACCT",
                event_type="EXTRACT",
            ) as step:
                assert step.was_short_circuited is True
                assert step.step_id == 50

        # No third UPDATE on exit — short-circuit must NOT touch the row.
        assert cur.execute.call_count == 2

    def test_in_progress_raises_ledger_step_failed(self):
        from utils.errors import LedgerStepFailed, PipelineRetryableError
        from utils import idempotency_ledger as mod

        cur = MagicMock()
        cur.execute.side_effect = [_unique_violation(), None]
        cur.fetchone.return_value = (60, "IN_PROGRESS")

        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with pytest.raises(LedgerStepFailed) as exc_info:
                with mod.ledger_step(
                    batch_id=1,
                    source_name="DNA",
                    table_name="ACCT",
                    event_type="EXTRACT",
                ):
                    pytest.fail(
                        "Should never enter the with-body on IN_PROGRESS race"
                    )

        # LedgerStepFailed is retryable per D68 + D74 exit code 1.
        assert isinstance(exc_info.value, PipelineRetryableError)
        assert "existing_step_id" in exc_info.value.metadata

    def test_failed_resets_to_in_progress_and_yields_normally(self):
        from utils import idempotency_ledger as mod

        # 4 execute calls: INSERT(raises) → SELECT existing → UPDATE reset → UPDATE clean exit
        cur = MagicMock()
        cur.execute.side_effect = [
            _unique_violation(),
            None,  # SELECT
            None,  # UPDATE reset
            None,  # UPDATE COMPLETED on clean exit
        ]
        cur.fetchone.return_value = (70, "FAILED")

        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with mod.ledger_step(
                batch_id=1,
                source_name="DNA",
                table_name="ACCT",
                event_type="EXTRACT",
            ) as step:
                assert step.step_id == 70
                assert step.was_short_circuited is False, (
                    "FAILED retry MUST yield was_short_circuited=False so "
                    "caller actually re-runs the work"
                )

        assert cur.execute.call_count == 4
        reset_sql = cur.execute.call_args_list[2].args[0]
        assert "SET Status = 'IN_PROGRESS'" in reset_sql
        assert "WHERE LedgerId = ? AND Status = 'FAILED'" in reset_sql

    def test_unexpected_status_raises_config_error(self):
        from utils.errors import LedgerConfigError
        from utils import idempotency_ledger as mod

        cur = MagicMock()
        cur.execute.side_effect = [_unique_violation(), None]
        cur.fetchone.return_value = (80, "ABANDONED")  # check constraint disabled

        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with pytest.raises(LedgerConfigError):
                with mod.ledger_step(
                    batch_id=1,
                    source_name="DNA",
                    table_name="ACCT",
                    event_type="EXTRACT",
                ):
                    pass

    def test_phantom_unique_violation_raises_step_failed(self):
        from utils.errors import LedgerStepFailed
        from utils import idempotency_ledger as mod

        cur = MagicMock()
        cur.execute.side_effect = [_unique_violation(), None]
        cur.fetchone.return_value = None  # SELECT returned nothing (phantom race)

        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with pytest.raises(LedgerStepFailed):
                with mod.ledger_step(
                    batch_id=1,
                    source_name="DNA",
                    table_name="ACCT",
                    event_type="EXTRACT",
                ):
                    pass

    def test_non_unique_integrity_error_bubbles_unchanged(self):
        """FK / CHECK violations are caller bugs — they must NOT short-circuit."""
        from utils import idempotency_ledger as mod

        cur = MagicMock()
        cur.execute.side_effect = _fk_violation()

        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with pytest.raises(pyodbc.IntegrityError):
                with mod.ledger_step(
                    batch_id=1,
                    source_name="DNA",
                    table_name="ACCT",
                    event_type="EXTRACT",
                ):
                    pass


# ---------------------------------------------------------------------------
# Clean / exception exit semantics
# ---------------------------------------------------------------------------


class TestExitSemantics:

    def test_clean_exit_writes_duration_ms_as_int(self):
        from utils import idempotency_ledger as mod

        cur = _make_cursor(fetchone_returns=(1,))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with mod.ledger_step(
                batch_id=1, source_name="DNA",
                table_name="ACCT", event_type="EXTRACT",
            ):
                pass

        update_call = cur.execute.call_args_list[-1]
        sql = update_call.args[0]
        positional = update_call.args[1:]
        assert "'COMPLETED'" in sql and "DurationMs = ?" in sql
        assert isinstance(positional[0], int)
        assert positional[0] >= 0

    def test_exception_writes_truncated_error_message(self):
        from utils import idempotency_ledger as mod

        cur = _make_cursor(fetchone_returns=(1,))
        long_msg = "x" * 10_000  # 10K chars — must be truncated to 4000
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with pytest.raises(RuntimeError):
                with mod.ledger_step(
                    batch_id=1, source_name="DNA",
                    table_name="ACCT", event_type="EXTRACT",
                ):
                    raise RuntimeError(long_msg)

        update_call = cur.execute.call_args_list[-1]
        sql = update_call.args[0]
        positional = update_call.args[1:]
        assert "'FAILED'" in sql
        # 2nd positional param is ErrorMessage
        assert isinstance(positional[1], str)
        assert len(positional[1]) <= 4000, (
            f"ErrorMessage must be truncated to ≤4000 chars; got "
            f"{len(positional[1])}"
        )

    def test_exit_update_failure_does_not_swallow_caller_exception(self, caplog):
        """If the UPDATE to FAILED itself fails (e.g. DB connection died
        mid-step), the caller's original exception MUST still surface."""
        from utils import idempotency_ledger as mod

        cur = MagicMock()
        # 1st: INSERT returns LedgerId. 2nd: UPDATE (raises secondary error).
        cur.execute.side_effect = [None, pyodbc.Error("DB went away")]
        cur.fetchone.return_value = (1,)

        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with caplog.at_level(logging.ERROR, logger="utils.idempotency_ledger"):
                with pytest.raises(ValueError, match="caller-side"):
                    with mod.ledger_step(
                        batch_id=1, source_name="DNA",
                        table_name="ACCT", event_type="EXTRACT",
                    ):
                        raise ValueError("caller-side problem")

        # The DB error during cleanup should have been logged
        assert any("Failed to UPDATE" in r.message for r in caplog.records), (
            "Cleanup failure must be logged so the audit trail isn't silent"
        )

    def test_caller_exception_preserved_not_wrapped(self):
        """The caller's exception MUST surface verbatim, not wrapped in
        LedgerStepFailed (per § 4.1: "bubbles up the caller's exception")."""
        from utils.errors import LedgerStepFailed
        from utils import idempotency_ledger as mod

        cur = _make_cursor(fetchone_returns=(1,))
        sentinel = KeyError("a specific identity object")

        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with pytest.raises(KeyError) as exc_info:
                with mod.ledger_step(
                    batch_id=1, source_name="DNA",
                    table_name="ACCT", event_type="EXTRACT",
                ):
                    raise sentinel

        assert exc_info.value is sentinel
        assert not isinstance(exc_info.value, LedgerStepFailed)


# ---------------------------------------------------------------------------
# B-223 caveat — metadata kwarg accepted but NOT persisted
# ---------------------------------------------------------------------------


class TestMetadataColumnCaveat:

    def test_metadata_kwarg_accepted_but_never_in_sql(self):
        """Per B-223 + § 4.1: metadata kwarg is forward-compatibility ONLY.
        It MUST NOT appear in any INSERT / UPDATE SQL until B-223 lands."""
        from utils import idempotency_ledger as mod

        cur = _make_cursor(fetchone_returns=(1,))
        sensitive_metadata = {"internal_signal": "should_never_be_persisted"}

        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with mod.ledger_step(
                batch_id=1, source_name="DNA",
                table_name="ACCT", event_type="EXTRACT",
                metadata=sensitive_metadata,
            ):
                pass

        for call in cur.execute.call_args_list:
            sql = call.args[0]
            assert "Metadata" not in sql, (
                "Per B-223 caveat: until the Metadata column lands, ledger SQL "
                "MUST NOT reference a Metadata column. Got SQL: " + sql[:200]
            )
            # Also assert the sensitive value never appears in the params.
            for arg in call.args[1:]:
                if isinstance(arg, str):
                    assert "internal_signal" not in arg
                    assert "should_never_be_persisted" not in arg

    def test_prior_result_always_none_until_b63(self):
        """LedgerStep.prior_result MUST be None on every code path until B-223."""
        from utils import idempotency_ledger as mod

        # Fresh INSERT path
        cur = _make_cursor(fetchone_returns=(1,))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with mod.ledger_step(
                batch_id=1, source_name="DNA",
                table_name="ACCT", event_type="EXTRACT",
            ) as step:
                assert step.prior_result is None

        # COMPLETED short-circuit path
        cur = MagicMock()
        cur.execute.side_effect = [_unique_violation(), None]
        cur.fetchone.return_value = (1, "COMPLETED")
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with mod.ledger_step(
                batch_id=1, source_name="DNA",
                table_name="ACCT", event_type="EXTRACT",
            ) as step:
                assert step.prior_result is None


# ---------------------------------------------------------------------------
# B70 — metadata kwarg DeprecationWarning (Round 6 § 7.2)
# ---------------------------------------------------------------------------


class TestMetadataDeprecationWarning:
    """B70 closure (2026-05-14, Round 6 § 7.2): until B-223 lands,
    passing ``metadata=`` to ``ledger_step()`` is accept-and-discard.
    The new DeprecationWarning routes callers to ``event_tracker.track()``
    for metadata persistence.
    """

    def test_non_none_metadata_emits_deprecation_warning(self):
        """Non-None metadata MUST raise DeprecationWarning at function
        entry — the "traceability beats convenience" pillar guardrail.
        """
        import warnings
        from utils import idempotency_ledger as mod

        cur = _make_cursor(fetchone_returns=(1,))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                with mod.ledger_step(
                    batch_id=1, source_name="DNA",
                    table_name="ACCT", event_type="EXTRACT",
                    metadata={"any_key": "any_value"},
                ):
                    pass
            dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
            assert dep_warnings, (
                "B70: metadata kwarg with non-None value MUST emit a "
                "DeprecationWarning"
            )
            assert "ledger_step(metadata=" in str(dep_warnings[0].message)
            assert "event_tracker.track()" in str(dep_warnings[0].message)

    def test_none_metadata_does_not_emit_warning(self):
        """Default None metadata MUST NOT trigger the DeprecationWarning.
        Otherwise the spam would be unmanageable.
        """
        import warnings
        from utils import idempotency_ledger as mod

        cur = _make_cursor(fetchone_returns=(1,))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                with mod.ledger_step(
                    batch_id=1, source_name="DNA",
                    table_name="ACCT", event_type="EXTRACT",
                    # metadata defaults to None
                ):
                    pass
            dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
            assert not dep_warnings, (
                "B70: default None metadata MUST NOT emit DeprecationWarning"
            )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class TestInternalHelpers:

    def test_utcnow_ms_is_naive_datetime(self):
        """_utcnow_ms returns naive datetime per SCD2-P1-f invariant."""
        from utils.idempotency_ledger import _utcnow_ms

        now = _utcnow_ms()
        assert isinstance(now, datetime)
        assert now.tzinfo is None, (
            "_utcnow_ms must return NAIVE datetime per SCD2-P1-f invariant"
        )

    def test_utcnow_ms_truncated_to_milliseconds(self):
        """_utcnow_ms truncates microseconds → milliseconds (DATETIME2(3))."""
        from utils.idempotency_ledger import _utcnow_ms

        now = _utcnow_ms()
        assert now.microsecond % 1000 == 0, (
            f"_utcnow_ms microseconds must be divisible by 1000 (ms precision); "
            f"got {now.microsecond}"
        )

    @pytest.mark.parametrize("exc,expected", [
        (pyodbc.IntegrityError("23000", "Violation of UNIQUE KEY constraint 'UX_X'"), True),
        (pyodbc.IntegrityError("23000", "Cannot insert duplicate key in object 'X' (2627)"), True),
        (pyodbc.IntegrityError("23000", "Violation of PRIMARY KEY constraint (2601)"), True),
        # FK and CHECK violations must NOT short-circuit. The "FK references
        # a UNIQUE index" wording is the case that defeated the old heuristic.
        (pyodbc.IntegrityError("23000", "FK references a UNIQUE index on parent"), False),
        (pyodbc.IntegrityError("23000", "CHECK constraint failed"), False),
    ])
    def test_is_unique_violation_detection(self, exc, expected):
        from utils.idempotency_ledger import _is_unique_violation

        assert _is_unique_violation(exc) is expected


# ---------------------------------------------------------------------------
# startup_recovery_sweep — I19
# ---------------------------------------------------------------------------


class TestStartupRecoverySweep:

    def test_zero_stale_returns_zero_no_update(self):
        from utils import idempotency_ledger as mod

        cur = _make_cursor(fetchone_returns=(0,))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            assert mod.startup_recovery_sweep() == 0
        assert cur.execute.call_count == 1, (
            "Zero-stale path MUST NOT issue an UPDATE"
        )

    def test_some_stale_within_max_updates_and_returns_rowcount(self):
        from utils import idempotency_ledger as mod

        count_cur = _make_cursor(fetchone_returns=(3,))
        update_cur = _make_cursor(rowcount=3)
        cm = _make_multi_cursor_for([count_cur, update_cur])
        with patch.object(mod, "cursor_for", cm):
            result = mod.startup_recovery_sweep(max_stale_count=10)

        assert result == 3
        update_sql = update_cur.execute.call_args.args[0]
        assert "'FAILED'" in update_sql
        assert "'STARTUP_SWEEP_FAILED'" in update_sql, (
            "Sweep UPDATE must set RecoveryAction='STARTUP_SWEEP_FAILED' so "
            "audit trail distinguishes sweep-induced FAILED rows from "
            "in-band caller failures"
        )

    def test_too_many_stale_raises_ledger_stuck(self):
        from utils.errors import LedgerStuck, PipelineFatalError
        from utils import idempotency_ledger as mod

        count_cur = _make_cursor(fetchone_returns=(15,))
        # No UPDATE cursor — sweep should raise before reaching it
        with patch.object(mod, "cursor_for", _make_cursor_for(count_cur)):
            with pytest.raises(LedgerStuck) as exc_info:
                mod.startup_recovery_sweep(max_stale_count=10)

        # LedgerStuck is fatal per D68 → exit code 2 per D74
        assert isinstance(exc_info.value, PipelineFatalError)
        assert exc_info.value.metadata["stale_count"] == 15

    def test_negative_threshold_raises_config_error(self):
        from utils.errors import LedgerConfigError
        from utils.idempotency_ledger import startup_recovery_sweep

        with pytest.raises(LedgerConfigError):
            startup_recovery_sweep(stale_threshold_minutes=-1)

    def test_zero_threshold_raises_config_error(self):
        from utils.errors import LedgerConfigError
        from utils.idempotency_ledger import startup_recovery_sweep

        with pytest.raises(LedgerConfigError):
            startup_recovery_sweep(stale_threshold_minutes=0)

    def test_negative_max_stale_raises_config_error(self):
        from utils.errors import LedgerConfigError
        from utils.idempotency_ledger import startup_recovery_sweep

        with pytest.raises(LedgerConfigError):
            startup_recovery_sweep(max_stale_count=-1)


# ---------------------------------------------------------------------------
# __all__ surface
# ---------------------------------------------------------------------------


def test_module_all_surface():
    from utils import idempotency_ledger as mod

    expected = {"LedgerStep", "ledger_step", "startup_recovery_sweep"}
    assert set(mod.__all__) == expected, (
        f"__all__ must be exactly {expected}; got {set(mod.__all__)}"
    )
    for name in expected:
        assert hasattr(mod, name)
