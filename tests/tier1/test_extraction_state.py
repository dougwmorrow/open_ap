"""Tier 1 unit test for cdc/extraction_state.py.

Per D70 Tier 1 — per-function + per-error-path coverage; mocks pyodbc
cursor; no live SQL Server.

North Star pillars:
  - Idempotent (D14 ExtractionAttempt monotonic; D15 caller's
    ledger_step gates the higher-level extraction; this module is the
    persistence half — every short-circuit / retry / unique-collision
    path tested).
  - Operationally stable (every error path surfaces the documented base
    type per D68 — InvalidTrustGate is PipelineFatalError,
    ExtractionStateUnavailable is PipelineRetryableError; exit codes
    follow from D74).
  - Audit-grade (record_extraction_attempt writes BatchId + Status +
    StartedAt + IsReExtraction + ExtractionAttempt + FailureReason
    truncated to 4000 chars).
  - Traceability (FirstLoadDate floor + future-date ceiling on the trust
    gate; SCD2-P1-f / CDC-NOW-MS invariant on naive ms datetimes).

Spec: phase1/03_core_modules.md § 4.2 + phase1/01_database_schema.md § 3.

B-numbers: B85 (utils/errors.py).
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
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
    """A non-UNIQUE IntegrityError (foreign key)."""
    return pyodbc.IntegrityError(
        "23000",
        "[23000] The INSERT statement conflicted with the FOREIGN KEY constraint.",
    )


# ===========================================================================
# is_date_trusted
# ===========================================================================


class TestIsDateTrustedValidation:
    """Identity-input + future-date + FirstLoadDate boundary validation."""

    def test_future_date_raises_invalid_trust_gate(self):
        from cdc import extraction_state as mod
        from utils.errors import InvalidTrustGate

        cur = _make_cursor(fetchone_returns=(None,))
        tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with pytest.raises(InvalidTrustGate) as exc_info:
                mod.is_date_trusted(
                    source_name="DNA",
                    table_name="ACCT",
                    business_date=tomorrow,
                )
        # Error metadata carries today/business_date for diagnostics.
        assert "business_date" in exc_info.value.metadata

    def test_pre_first_load_date_raises_invalid_trust_gate(self):
        """If UdmTablesList.FirstLoadDate is set and business_date is
        earlier, trust gate refuses with InvalidTrustGate."""
        from cdc import extraction_state as mod
        from utils.errors import InvalidTrustGate

        # FirstLoadDate lookup returns 2024-01-01.
        cur_floor = _make_cursor(fetchone_returns=(date(2024, 1, 1),))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur_floor)):
            with pytest.raises(InvalidTrustGate) as exc_info:
                mod.is_date_trusted(
                    source_name="DNA",
                    table_name="ACCT",
                    business_date=date(2023, 12, 31),
                )
        assert "first_load_date" in exc_info.value.metadata

    def test_first_load_date_null_skips_floor_check(self):
        """A NULL FirstLoadDate -> the floor check downgrades to no-op.
        The trust gate proceeds to the PipelineExtraction lookup."""
        from cdc import extraction_state as mod

        # (1) FirstLoadDate lookup returns NULL; (2) PipelineExtraction
        #     lookup returns no row -> trust gate False.
        cur = MagicMock()
        cur.fetchone.side_effect = [(None,), None]

        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            result = mod.is_date_trusted(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2020, 1, 1),
            )
        assert result is False

    def test_missing_udmtables_row_skips_floor_check(self):
        """If UdmTablesList has no row for the (source, table), the
        floor check downgrades — does not raise."""
        from cdc import extraction_state as mod

        cur = MagicMock()
        cur.fetchone.side_effect = [None, None]
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            result = mod.is_date_trusted(
                source_name="UNKNOWN_SOURCE",
                table_name="UNKNOWN_TABLE",
                business_date=date(2025, 1, 15),
            )
        assert result is False

    def test_empty_source_name_raises_invalid_trust_gate(self):
        from cdc import extraction_state as mod
        from utils.errors import InvalidTrustGate

        cur = MagicMock()
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with pytest.raises(InvalidTrustGate):
                mod.is_date_trusted(
                    source_name="",
                    table_name="ACCT",
                    business_date=date(2025, 1, 15),
                )

    def test_datetime_subtype_rejected(self):
        """``datetime`` IS a subclass of ``date`` but we want pure
        ``date`` only — datetime input is a caller bug."""
        from cdc import extraction_state as mod
        from utils.errors import InvalidTrustGate

        cur = MagicMock()
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with pytest.raises(InvalidTrustGate):
                mod.is_date_trusted(
                    source_name="DNA",
                    table_name="ACCT",
                    business_date=datetime(2025, 1, 15, 12, 0, 0),  # type: ignore[arg-type]
                )


class TestIsDateTrustedHappyPath:

    def test_success_row_exists_returns_true(self):
        from cdc import extraction_state as mod

        # FirstLoadDate NULL (skip floor), then SUCCESS row found.
        cur = MagicMock()
        cur.fetchone.side_effect = [(None,), (1,)]

        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            result = mod.is_date_trusted(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
            )
        assert result is True

    def test_no_success_row_returns_false(self):
        from cdc import extraction_state as mod

        cur = MagicMock()
        cur.fetchone.side_effect = [(None,), None]

        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            result = mod.is_date_trusted(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
            )
        assert result is False

    def test_business_date_equal_first_load_date_passes(self):
        """``business_date == FirstLoadDate`` is in scope (strict ``<`` test)."""
        from cdc import extraction_state as mod

        cur = MagicMock()
        cur.fetchone.side_effect = [(date(2025, 1, 1),), (1,)]

        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            result = mod.is_date_trusted(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 1),
            )
        assert result is True

    def test_today_utc_passes_future_check(self):
        """Today (UTC) is NOT a future date — must pass."""
        from cdc import extraction_state as mod

        cur = MagicMock()
        cur.fetchone.side_effect = [(None,), None]
        today_utc = datetime.now(timezone.utc).date()

        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            result = mod.is_date_trusted(
                source_name="DNA",
                table_name="ACCT",
                business_date=today_utc,
            )
        assert result is False  # No SUCCESS row yet but not a trust violation.


class TestIsDateTrustedErrorPaths:

    def test_operational_error_raises_extraction_state_unavailable(self):
        from cdc import extraction_state as mod
        from utils.errors import ExtractionStateUnavailable, PipelineRetryableError

        cur = MagicMock()
        # First call (FirstLoadDate lookup) raises OperationalError.
        cur.execute.side_effect = pyodbc.OperationalError("Connection lost")

        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with pytest.raises(ExtractionStateUnavailable) as exc_info:
                mod.is_date_trusted(
                    source_name="DNA",
                    table_name="ACCT",
                    business_date=date(2025, 1, 15),
                )
        # ExtractionStateUnavailable is retryable per D68.
        assert isinstance(exc_info.value, PipelineRetryableError)


# ===========================================================================
# most_recent_success
# ===========================================================================


class TestMostRecentSuccess:

    def test_returns_date_when_success_exists(self):
        from cdc import extraction_state as mod

        cur = _make_cursor(fetchone_returns=(date(2024, 12, 31),))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            result = mod.most_recent_success(
                source_name="DNA",
                table_name="ACCT",
            )
        assert result == date(2024, 12, 31)
        assert not isinstance(result, datetime)

    def test_returns_none_when_no_success(self):
        from cdc import extraction_state as mod

        cur = _make_cursor(fetchone_returns=(None,))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            result = mod.most_recent_success(
                source_name="DNA",
                table_name="ACCT",
            )
        assert result is None

    def test_pyodbc_returns_datetime_coerces_to_date(self):
        """pyodbc may return DATE as datetime depending on driver; we
        must always coerce to plain ``date``."""
        from cdc import extraction_state as mod

        cur = _make_cursor(
            fetchone_returns=(datetime(2024, 12, 31, 12, 0, 0),),
        )
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            result = mod.most_recent_success(
                source_name="DNA",
                table_name="ACCT",
            )
        assert result == date(2024, 12, 31)
        assert type(result) is date

    def test_operational_error_raises_extraction_state_unavailable(self):
        from cdc import extraction_state as mod
        from utils.errors import ExtractionStateUnavailable

        cur = MagicMock()
        cur.execute.side_effect = pyodbc.OperationalError("Connection lost")
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with pytest.raises(ExtractionStateUnavailable):
                mod.most_recent_success(
                    source_name="DNA",
                    table_name="ACCT",
                )

    def test_empty_identifier_raises(self):
        from cdc import extraction_state as mod
        from utils.errors import ExtractionStateUnavailable

        with pytest.raises(ExtractionStateUnavailable):
            mod.most_recent_success(source_name="", table_name="ACCT")


# ===========================================================================
# is_reextraction
# ===========================================================================


class TestIsReextraction:

    def test_first_attempt_returns_false(self):
        from cdc import extraction_state as mod

        cur = _make_cursor(fetchone_returns=None)
        cur.fetchone.return_value = None
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            result = mod.is_reextraction(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
            )
        assert result is False

    def test_prior_attempt_returns_true(self):
        from cdc import extraction_state as mod

        cur = _make_cursor(fetchone_returns=(1,))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            result = mod.is_reextraction(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
            )
        assert result is True

    def test_failed_prior_attempt_still_counts(self):
        """Any prior row counts (regardless of Status) — the helper
        answers "any attempt before?", not "any successful attempt?"."""
        from cdc import extraction_state as mod

        cur = _make_cursor(fetchone_returns=(1,))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            result = mod.is_reextraction(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
            )
        # And the WHERE clause must NOT filter on Status.
        executed_sql = cur.execute.call_args.args[0]
        assert "Status" not in executed_sql, (
            "is_reextraction must count ALL prior attempts, regardless of Status"
        )
        assert result is True


# ===========================================================================
# get_extraction_attempt
# ===========================================================================


class TestGetExtractionAttempt:

    def test_no_prior_returns_one(self):
        from cdc import extraction_state as mod

        cur = _make_cursor(fetchone_returns=(None,))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            result = mod.get_extraction_attempt(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
            )
        assert result == 1

    def test_prior_n_returns_n_plus_one(self):
        from cdc import extraction_state as mod

        cur = _make_cursor(fetchone_returns=(3,))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            result = mod.get_extraction_attempt(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
            )
        assert result == 4

    def test_max_query_shape(self):
        from cdc import extraction_state as mod

        cur = _make_cursor(fetchone_returns=(2,))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            mod.get_extraction_attempt(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
            )
        sql = cur.execute.call_args.args[0]
        assert "MAX(ExtractionAttempt)" in sql

    def test_operational_error_raises_unavailable(self):
        from cdc import extraction_state as mod
        from utils.errors import ExtractionStateUnavailable

        cur = MagicMock()
        cur.execute.side_effect = pyodbc.OperationalError("Connection lost")
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            with pytest.raises(ExtractionStateUnavailable):
                mod.get_extraction_attempt(
                    source_name="DNA",
                    table_name="ACCT",
                    business_date=date(2025, 1, 15),
                )


# ===========================================================================
# record_extraction_attempt — INSERT path
# ===========================================================================


class TestRecordExtractionAttemptInsertPath:

    def test_first_attempt_inserts_and_returns_extraction_id(self):
        from cdc import extraction_state as mod

        # (1) get_extraction_attempt -> 1; (2) INSERT -> ExtractionId=987.
        cur_attempt = _make_cursor(fetchone_returns=(None,))
        cur_insert = _make_cursor(fetchone_returns=(987,))
        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([cur_attempt, cur_insert]),
        ):
            result = mod.record_extraction_attempt(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
                batch_id=42,
                status="IN_PROGRESS",
            )
        assert result == 987
        # Insert SQL signature.
        insert_sql = cur_insert.execute.call_args.args[0]
        assert "INSERT INTO General.ops.PipelineExtraction" in insert_sql
        assert "OUTPUT INSERTED.ExtractionId" in insert_sql
        # IsReExtraction defaults to 0 for first attempt.
        args = cur_insert.execute.call_args.args
        # Param positions: [0]=SQL, [1..11]=bound params in INSERT VALUES order
        # (batch_id, source, table, date, status, started, completed,
        #  rows_extracted, is_reextraction, attempt, failure_reason).
        assert args[1] == 42                        # batch_id
        assert args[2] == "DNA"                     # source_name
        assert args[3] == "ACCT"                    # table_name
        assert args[4] == date(2025, 1, 15)         # business_date
        assert args[5] == "IN_PROGRESS"             # status
        assert args[9] == 0                         # is_reextraction
        assert args[10] == 1                        # attempt

    def test_explicit_attempt_skips_lookup(self):
        """When extraction_attempt is supplied, the helper skips the
        MAX-lookup roundtrip."""
        from cdc import extraction_state as mod

        cur_insert = _make_cursor(fetchone_returns=(101,))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur_insert)):
            result = mod.record_extraction_attempt(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
                batch_id=42,
                status="SUCCESS",
                extraction_attempt=2,
            )
        assert result == 101
        # Exactly one execute call — the INSERT. No MAX lookup.
        assert cur_insert.execute.call_count == 1
        args = cur_insert.execute.call_args.args
        # Param positions: [0]=SQL, [9]=is_reextraction, [10]=attempt.
        assert args[9] == 1                         # is_reextraction (attempt > 1)
        assert args[10] == 2                        # attempt

    def test_completed_at_set_for_terminal_status(self):
        """SUCCESS / FAILED -> CompletedAt populated. IN_PROGRESS -> NULL.

        ``cursor.execute(sql, *params)`` -> ``call_args.args[0]`` is the SQL,
        ``args[1:]`` are the bound parameters. INSERT VALUES order is:
        (batch_id, source, table, date, status, started, completed,
        rows_extracted, is_reextraction, attempt, failure_reason)
        -> param indices 1..11 -> CompletedAt at args[7], StartedAt at args[6].
        """
        from cdc import extraction_state as mod

        # SUCCESS case: CompletedAt non-null.
        cur_attempt = _make_cursor(fetchone_returns=(None,))
        cur_insert = _make_cursor(fetchone_returns=(1,))
        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([cur_attempt, cur_insert]),
        ):
            mod.record_extraction_attempt(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
                batch_id=42,
                status="SUCCESS",
            )
        args = cur_insert.execute.call_args.args
        completed_at = args[7]
        assert completed_at is not None
        assert isinstance(completed_at, datetime)
        # SCD2-P1-f / CDC-NOW-MS — naive (no tzinfo).
        assert completed_at.tzinfo is None

        # IN_PROGRESS case: CompletedAt NULL.
        cur_attempt2 = _make_cursor(fetchone_returns=(None,))
        cur_insert2 = _make_cursor(fetchone_returns=(2,))
        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([cur_attempt2, cur_insert2]),
        ):
            mod.record_extraction_attempt(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
                batch_id=42,
                status="IN_PROGRESS",
            )
        args = cur_insert2.execute.call_args.args
        assert args[7] is None

    def test_failure_reason_truncated(self):
        """FailureReason longer than 4000 chars must be truncated."""
        from cdc import extraction_state as mod

        cur_attempt = _make_cursor(fetchone_returns=(None,))
        cur_insert = _make_cursor(fetchone_returns=(1,))
        long_reason = "X" * 5000
        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([cur_attempt, cur_insert]),
        ):
            mod.record_extraction_attempt(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
                batch_id=42,
                status="FAILED",
                failure_reason=long_reason,
            )
        args = cur_insert.execute.call_args.args
        # Param positions: [11]=failure_reason (last bound param).
        assert len(args[11]) == 4000

    def test_started_at_naive_ms(self):
        """StartedAt must be naive UTC, truncated to milliseconds, per
        the SCD2-P1-f / CDC-NOW-MS invariant."""
        from cdc import extraction_state as mod

        cur_attempt = _make_cursor(fetchone_returns=(None,))
        cur_insert = _make_cursor(fetchone_returns=(1,))
        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([cur_attempt, cur_insert]),
        ):
            mod.record_extraction_attempt(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
                batch_id=42,
                status="IN_PROGRESS",
            )
        args = cur_insert.execute.call_args.args
        # Param positions: [0]=SQL, [1]=batch_id, [2]=source, [3]=table,
        # [4]=date, [5]=status, [6]=started_at, [7]=completed_at, [8]=rows,
        # [9]=is_reextraction, [10]=attempt, [11]=failure_reason.
        started_at = args[6]
        assert isinstance(started_at, datetime)
        assert started_at.tzinfo is None
        # Microseconds must be a multiple of 1000 (ms precision).
        assert started_at.microsecond % 1000 == 0


# ===========================================================================
# record_extraction_attempt — UNIQUE collision UPDATE path
# ===========================================================================


class TestRecordExtractionAttemptUniqueCollisionPath:

    def test_unique_violation_falls_through_to_update(self):
        """On INSERT UNIQUE collision, the helper UPDATEs the existing
        row by the same key and returns its ExtractionId."""
        from cdc import extraction_state as mod

        # (1) get_extraction_attempt -> 1; (2) INSERT raises UNIQUE;
        # (3) UPDATE...OUTPUT -> ExtractionId=555.
        cur_attempt = _make_cursor(fetchone_returns=(None,))
        cur_insert = MagicMock()
        cur_insert.execute.side_effect = _unique_violation()
        cur_update = _make_cursor(fetchone_returns=(555,))
        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([cur_attempt, cur_insert, cur_update]),
        ):
            result = mod.record_extraction_attempt(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
                batch_id=42,
                status="SUCCESS",
            )
        assert result == 555
        # The UPDATE SQL must target the same UNIQUE-index key tuple.
        update_sql = cur_update.execute.call_args.args[0]
        assert "UPDATE General.ops.PipelineExtraction" in update_sql
        assert "WHERE SourceName = ?" in update_sql
        assert "AND ExtractionAttempt = ?" in update_sql

    def test_non_unique_integrity_error_surfaces_as_invalid_trust_gate(self):
        """A non-UNIQUE IntegrityError (FK / CHECK) is NOT a UNIQUE
        collision — surfaces as InvalidTrustGate (configuration class)."""
        from cdc import extraction_state as mod
        from utils.errors import InvalidTrustGate

        cur_attempt = _make_cursor(fetchone_returns=(None,))
        cur_insert = MagicMock()
        cur_insert.execute.side_effect = _fk_violation()
        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([cur_attempt, cur_insert]),
        ):
            with pytest.raises(InvalidTrustGate):
                mod.record_extraction_attempt(
                    source_name="DNA",
                    table_name="ACCT",
                    business_date=date(2025, 1, 15),
                    batch_id=42,
                    status="SUCCESS",
                )

    def test_phantom_unique_then_no_row_on_update_raises_unavailable(self):
        """UNIQUE violation on INSERT but no row found on follow-up
        UPDATE -> phantom-write race; retryable per B-7."""
        from cdc import extraction_state as mod
        from utils.errors import ExtractionStateUnavailable

        cur_attempt = _make_cursor(fetchone_returns=(None,))
        cur_insert = MagicMock()
        cur_insert.execute.side_effect = _unique_violation()
        # MagicMock() auto-stubs fetchone() to a MagicMock(); we need an
        # explicit None to exercise the phantom-row branch.
        cur_update = MagicMock()
        cur_update.fetchone.return_value = None
        with patch.object(
            mod, "cursor_for",
            _make_multi_cursor_for([cur_attempt, cur_insert, cur_update]),
        ):
            with pytest.raises(ExtractionStateUnavailable):
                mod.record_extraction_attempt(
                    source_name="DNA",
                    table_name="ACCT",
                    business_date=date(2025, 1, 15),
                    batch_id=42,
                    status="SUCCESS",
                )


# ===========================================================================
# record_extraction_attempt — input validation
# ===========================================================================


class TestRecordExtractionAttemptValidation:

    def test_invalid_status_raises(self):
        from cdc import extraction_state as mod
        from utils.errors import InvalidTrustGate

        with pytest.raises(InvalidTrustGate):
            mod.record_extraction_attempt(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
                batch_id=42,
                status="DONE",  # not in CHECK constraint
            )

    @pytest.mark.parametrize("bad_batch", [None, 0, -1, "1", 1.5])
    def test_invalid_batch_id_raises(self, bad_batch):
        from cdc import extraction_state as mod
        from utils.errors import InvalidTrustGate

        with pytest.raises(InvalidTrustGate):
            mod.record_extraction_attempt(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
                batch_id=bad_batch,  # type: ignore[arg-type]
                status="IN_PROGRESS",
            )

    @pytest.mark.parametrize("bad_date", [
        "2025-01-15",
        datetime(2025, 1, 15, 12, 0, 0),
        None,
    ])
    def test_invalid_business_date_raises(self, bad_date):
        from cdc import extraction_state as mod
        from utils.errors import InvalidTrustGate

        with pytest.raises(InvalidTrustGate):
            mod.record_extraction_attempt(
                source_name="DNA",
                table_name="ACCT",
                business_date=bad_date,  # type: ignore[arg-type]
                batch_id=42,
                status="IN_PROGRESS",
            )

    def test_empty_source_name_raises(self):
        from cdc import extraction_state as mod
        from utils.errors import InvalidTrustGate

        with pytest.raises(InvalidTrustGate):
            mod.record_extraction_attempt(
                source_name="",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
                batch_id=42,
                status="IN_PROGRESS",
            )

    def test_invalid_extraction_attempt_raises(self):
        from cdc import extraction_state as mod
        from utils.errors import InvalidTrustGate

        with pytest.raises(InvalidTrustGate):
            mod.record_extraction_attempt(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2025, 1, 15),
                batch_id=42,
                status="IN_PROGRESS",
                extraction_attempt=0,
            )


# ===========================================================================
# Internal helpers
# ===========================================================================


class TestInternalHelpers:

    def test_utcnow_ms_is_naive(self):
        from cdc.extraction_state import _utcnow_ms

        result = _utcnow_ms()
        assert result.tzinfo is None
        assert isinstance(result, datetime)

    def test_utcnow_ms_truncated_to_milliseconds(self):
        from cdc.extraction_state import _utcnow_ms

        result = _utcnow_ms()
        assert result.microsecond % 1000 == 0

    @pytest.mark.parametrize("exc,expected", [
        (_unique_violation("Violation of UNIQUE KEY constraint (2627)"), True),
        (_unique_violation("Cannot insert duplicate key (2601)"), True),
        (_unique_violation("Violation of PRIMARY KEY constraint"), True),
        (_fk_violation(), False),
        (pyodbc.IntegrityError("23000", "[23000] CHECK constraint failed"), False),
    ])
    def test_is_unique_violation_detection(self, exc, expected):
        from cdc.extraction_state import _is_unique_violation

        assert _is_unique_violation(exc) is expected

    def test_coerce_date_handles_datetime(self):
        from cdc.extraction_state import _coerce_date

        assert _coerce_date(datetime(2025, 1, 15, 12, 0, 0)) == date(2025, 1, 15)
        assert _coerce_date(date(2025, 1, 15)) == date(2025, 1, 15)
        assert _coerce_date(None) is None

    def test_coerce_date_rejects_unknown_type(self):
        from cdc.extraction_state import _coerce_date
        from utils.errors import ExtractionStateUnavailable

        with pytest.raises(ExtractionStateUnavailable):
            _coerce_date("2025-01-15")  # type: ignore[arg-type]


# ===========================================================================
# ExtractionState dataclass
# ===========================================================================


class TestExtractionStateDataclass:

    def test_construction(self):
        from cdc.extraction_state import ExtractionState

        state = ExtractionState(
            source_name="DNA",
            table_name="ACCT",
            business_date=date(2025, 1, 15),
            status="SUCCESS",
            extraction_attempt=2,
            is_reextraction=True,
            started_at=datetime(2025, 1, 15, 14, 30, 0),
            batch_id=100,
        )
        assert state.source_name == "DNA"
        assert state.extraction_attempt == 2
        assert state.is_reextraction is True

    def test_frozen(self):
        from dataclasses import FrozenInstanceError

        from cdc.extraction_state import ExtractionState

        state = ExtractionState(
            source_name="DNA",
            table_name="ACCT",
            business_date=date(2025, 1, 15),
            status="SUCCESS",
            extraction_attempt=1,
            is_reextraction=False,
            started_at=None,
            batch_id=None,
        )
        with pytest.raises(FrozenInstanceError):
            state.status = "FAILED"  # type: ignore[misc]

    def test_equality(self):
        from cdc.extraction_state import ExtractionState

        a = ExtractionState(
            source_name="DNA",
            table_name="ACCT",
            business_date=date(2025, 1, 15),
            status="SUCCESS",
            extraction_attempt=1,
            is_reextraction=False,
            started_at=None,
            batch_id=None,
        )
        b = ExtractionState(
            source_name="DNA",
            table_name="ACCT",
            business_date=date(2025, 1, 15),
            status="SUCCESS",
            extraction_attempt=1,
            is_reextraction=False,
            started_at=None,
            batch_id=None,
        )
        assert a == b
