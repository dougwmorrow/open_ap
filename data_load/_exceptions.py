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
