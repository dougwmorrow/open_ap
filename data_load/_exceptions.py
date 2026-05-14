"""B215 — canonical exception classes shared between data_load modules + tools.

Per **D92** forward-only additive — new module that consolidates exception
classes referenced by both ``data_load/`` engine modules and ``tools/`` CLI
shims. Tests mock the ``data_load.*`` engine modules (e.g.
``data_load.lateness_measurement``) as ``MagicMock``, which replaces the
exception classes themselves with ``MagicMock`` attributes — so
``except SomeError as exc:`` in the tool fails with::

    TypeError: catching classes that do not inherit from BaseException
    is not allowed

The fix: tools import exception classes from this module, which tests do
NOT mock (it has no live-DB dependencies, so mocking would be gratuitous).
The engine modules re-export the same classes for backward-compat with
``from data_load.lateness_measurement import UdmTablesListNotWritable``
callers (still valid; just routed through here).

D-numbers consumed
------------------

D68 (error class hierarchy — PipelineFatalError / PipelineRetryableError),
D92 (forward-only additive — new module; no rename / removal of existing
API surface), B215 (test-fix cohort closure tracking).
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Lateness-measurement exceptions (data_load/lateness_measurement.py + B188)
# ---------------------------------------------------------------------------


class LatenessMeasurementError(Exception):
    """Base class for lateness measurement errors."""


class SourceConnectError(LatenessMeasurementError):
    """Source DB unreachable — exit 1 retryable per Tool 14 spec § 3."""


class BronzeTableMissing(LatenessMeasurementError):
    """Bronze table not yet deployed for this UdmTablesList row.

    Per Tool 14 spec § 3 — UPDATE still writes ``LatenessL99Minutes = NULL``
    with notes='Bronze not deployed yet'. The CLI shim catches this and
    maps to exit 1 (warning-tier).
    """


class InsufficientSampleError(LatenessMeasurementError):
    """< MIN_SAMPLE_COUNT rows in the lookback window.

    Per Tool 14 spec § 3 — UPDATE still writes the L99 anyway with notes
    'low sample count: N'. The CLI shim maps to exit 1 (warning-tier).
    """


class UdmTablesListNotWritable(LatenessMeasurementError):
    """``General.dbo.UdmTablesList`` not writable — exit 2 fatal per Tool 14 spec § 3."""


# ---------------------------------------------------------------------------
# Capacity-baseline exceptions (data_load/capacity_baseline.py + B190)
# ---------------------------------------------------------------------------


class CapacityBaselineError(Exception):
    """Base class for capacity-baseline-specific failures."""


class CapacitySourceConnectError(CapacityBaselineError):
    """Source DB unreachable / connect failure for capacity baseline.

    Distinct from :class:`SourceConnectError` (the lateness variant) so
    callers can pattern-match against the correct hierarchy. Caller (CLI)
    maps to exit 1 per Tool 16 spec § 5 error modes.
    """


class ParquetDirectoryUnreachable(CapacityBaselineError):
    """Parquet network drive not mounted / inaccessible.

    Caller (CLI) maps to exit 1 per Tool 16 spec § 5 — measurement returns
    with ``current_partition_layout=None`` + ``avg_partition_file_size_mb=None``
    + ``partition_recommendation`` describing the unreachable state.
    """


class LogTableNotWritable(CapacityBaselineError):
    """``General.ops.CapacityBaselineLog`` not writable.

    Caller (CLI) maps to exit 2 per Tool 16 spec § 5 — fatal; operator
    must investigate (typically B195 migration not yet applied).
    """


# ---------------------------------------------------------------------------
# Log-retention-cleanup exceptions (tools/log_retention_cleanup.py + R4 § 3.10)
# ---------------------------------------------------------------------------


class LogRetentionCleanupError(Exception):
    """Base class for ``tools/log_retention_cleanup.py`` failures.

    Per Round 4 § 3.10 + D74 exit-code contract; sub-classes route to
    exit 1 (warning / retryable) vs exit 2 (fatal).
    """


class LogRetentionLockContention(LogRetentionCleanupError):
    """``sp_getapplock`` on ``('log_retention_cleanup',)`` not acquired.

    Another cleanup run is in flight OR a Power BI / SSMS session is
    holding a long-running read lock against ``PipelineLog``. Caller
    (CLI) maps to exit 1 per Round 4 § 3.10 error modes — operator can
    re-run after the contending session releases.
    """


class LogRetentionConfigError(LogRetentionCleanupError):
    """Configuration unavailable (e.g. ``utils.configuration`` import fails).

    Caller (CLI) maps to exit 2 per Round 4 § 3.10 error modes — fatal;
    operator must investigate (typically env-var / connection-string
    misconfiguration on the host).
    """


# ---------------------------------------------------------------------------
# Vault retention exceptions (tools/enforce_retention.py + R4 § 3.8)
# Per Round 4 § 3.8 L1067-1068 canonical exception class names — caller
# (CLI) maps VaultUnavailable -> exit 1 retryable, VaultConfigError -> exit 2
# fatal per the spec's "Error modes" section.
# ---------------------------------------------------------------------------


class VaultError(Exception):
    """Base class for vault-side errors raised by the SP-10 wrapper.

    Per Round 3 § 2.3 ``vault_client.call_vault_sp()`` error translation +
    Round 4 § 3.8 L1067-1068 canonical exception names. Sub-classes route
    to exit 1 (retryable) vs exit 2 (fatal) per D74 + spec § 3.8 L1113-1116.
    """


class VaultUnavailable(VaultError):
    """Vault DB connection drop OR retryable error mid-SP-10 invocation.

    Per Round 4 § 3.8 L1067 — exit 1 (retryable). Caller can re-run
    (SP-10 is a single-statement transactional UPDATE per L1115 — either
    the whole UPDATE commits or none of it does; no partial-row state
    is possible).
    """


class VaultConfigError(VaultError):
    """Missing/unreachable vault DB env keys at startup OR fatal config.

    Per Round 4 § 3.8 L1068 — exit 2 (fatal). Caller must investigate
    (typically env-var / connection-string misconfiguration on the host
    or missing Round 3 § 2.3 vault_client config).
    """


# ---------------------------------------------------------------------------
# Promote-test-to-prod exceptions (tools/promote_test_to_prod.py + R4 § 3.6)
# Per Round 4 § 3.6 L868-873 canonical exception class names — both fatal
# (exit 2). Forward-only additive per D92 — new classes; no existing API
# surface renamed or removed.
# ---------------------------------------------------------------------------


class ParityFatalError(Exception):
    """Fatal-tier parity drift between test server and parity baseline.

    Per Round 3 § 3.2 L794 + Round 4 § 3.6 L868. The test server's parity
    check is a PRE-CONDITION for failover acknowledgment — if the test
    server itself has fatal drift (e.g. column schema mismatch on a Round
    1 table, or a CK constraint defaulted differently), promoting it to
    own a prod cycle would propagate the drift. Caller (CLI) maps to
    exit 2 (fatal) per spec § 3.6 L937 — operator MUST restore parity
    before retrying. The ``--skip-parity-check`` flag overrides this
    pre-condition but logs CRITICAL per spec L894.

    Subclass of ``Exception`` (not ``PipelineFatalError``) to keep the
    canonical exception module dependency-free; ``tools/verify_server_parity.py``
    (Round 4 § 3.7) raises a ``PipelineFatalError`` subclass at the engine
    boundary, but this tool catches the broader ``ParityFatalError`` to
    avoid importing the Round 3 module hierarchy at CLI parse time.
    """


class GateNotAcquirable(Exception):
    """``sp_getapplock`` on the gate Resource string blocked or failed.

    Per Round 4 § 3.6 L869 + Round 1 SP-3 / SP-4 canonical resource format
    ``'pipeline_gate_' + @CycleType + '_' + CONVERT(VARCHAR(10), @CycleDate, 23)``
    (SP-3 L1467-1468 + SP-4 L1552-1553). When SP-4's internal
    ``sp_getapplock`` returns a negative code, SP-4 raises (per L1568
    ``RAISERROR``) and pyodbc surfaces the error here. Caller (CLI) maps
    to exit 2 (fatal) per spec § 3.6 L937 — another pipeline (prod claim
    OR a concurrent test-promotion attempt) holds the lock; serializing
    is the gate-contract guarantee and "wait for it" is not actionable
    by the operator (the contending process is by definition transient).
    """
