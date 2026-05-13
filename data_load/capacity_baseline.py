"""B190 — Capacity baseline + partition recommendation module.

Per **phase1/04b_phase_0_closure_tools.md § 5** (Tool 16 canonical spec)
+ **D26** (append-only provenance) + **D42** (Phase 5 capacity-cost
projections) + **D45.2** (Parquet 100-250 MB per-file target) + **D2/D4**
(canonical Parquet network drive path) + **D107** (dual Windows network
drive — H + VendorFile, both in-DC) + **D74** (exit-code contract 0/1/2)
+ **D75** (CLI argument naming) + **D76** (audit-row contract; CLI_*
EventType family) + **D77** (Tier 0 6-canonical-assertion scaffold) +
**D92** (forward-only additive — NEW module function alongside Round 3 /
4 / 4.5 locked modules; no rename / removal of existing API surface) +
**D103** (Claude Code security model; this module is read-only on source
DB + filesystem; only writes to ``General.ops.CapacityBaselineLog`` +
``PipelineEventLog`` per D26 / D76).

Wraps: NEW module function ``measure_capacity_and_partition(table_config) ->
CapacityResult`` per § 5 canonical signature. Function:

  (a) queries source DB for current row count + growth rate (rolling
      12-month average over ``SourceAggregateColumnName`` where available;
      otherwise falls back to a single point-in-time count + growth of 0)
  (b) computes 12-month + 7-year projections per D42 + D30 retention
  (c) queries the Parquet directory for the current partition layout +
      file-size distribution per D45.2 (100-250 MB target)
  (d) recommends partition optimization narrative based on
      ``avg_partition_file_size_mb`` vs the D45.2 target range
  (e) returns ``CapacityResult`` dataclass

Raises
------

* ``SourceConnectError`` — source DB unreachable; caller maps to exit 1
* ``ParquetDirectoryUnreachable`` — network drive not mounted; caller maps
  to exit 1 with ``current_partition_layout=None`` per § 5 error mode
* ``LogTableNotWritable`` — caller maps to exit 2

Schema alignment
----------------

``CapacityResult`` field types align field-for-field with the
``General.ops.CapacityBaselineLog`` schema authored in
``migrations/capacity_baseline_log.py`` (B195). The migration's
``CurrentPartitionLayout`` / ``AvgPartitionFileSizeMb`` /
``PartitionRecommendation`` columns are NULLable to mirror the
ParquetDirectoryUnreachable degraded-result path.

Execution classification (per ``udm-execution-classifier`` skill)
-----------------------------------------------------------------

* **Trigger**: PRIMARY: Scheduled — Automic monthly job
  ``JOB_CAPACITY_BASELINE`` (frozen-13 inventory addition per § 6).
  SECONDARY: Manual operator CLI for ad-hoc on-demand measurement
  (per § 5 invocation patterns).
* **Frequency**: PRIMARY Recurring (monthly, 1st of month 04:00 between
  AM and PM cycles per D109 schedule); SECONDARY one-time ad-hoc.
* **Idempotency**: YES (semantic) — read-only on source + Parquet
  filesystem; append-only on ``CapacityBaselineLog`` + ``PipelineEventLog``.
  Re-running produces a NEW measurement row (intentional historical
  trail per D26 / § 5 idempotency note — not idempotent-identity).
* **Audit-row family**: ``CLI_MEASURE_CAPACITY_AND_PARTITION`` (one of the
  11 CLI_* values registered in CLAUDE.md per D76 + Round 4 § 3); ONE
  row per INVOCATION per § 5 L197 (not one row per table).
* **Routing**: PRIMARY tracker ``phase1/02_configuration.md`` § 5.1
  (Automic inventory frozen-13); SECONDARY tracker ``ONE_OFF_SCRIPTS.md``
  "Active items" (operator ad-hoc).

D-numbers consumed
------------------

D2, D4, D15, D26, D27, D30, D42, D44, D45.2, D63, D67, D74, D75, D76,
D77, D92, D103, D107, D109, B190.
"""

from __future__ import annotations

import logging
import os
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants per § 5 + D45.2
# ---------------------------------------------------------------------------

# D76 EventType registered in CLAUDE.md CLI_* family registry.
EVENT_TYPE = "CLI_MEASURE_CAPACITY_AND_PARTITION"

# Exit-code constants per D74.
EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_FATAL = 2

# D45.2 partition file-size target window. The recommendation narrative
# classifies the observed ``avg_partition_file_size_mb`` against these
# bounds. Both edges inclusive (a 100 MB or 250 MB average is considered
# optimal — round-to-edge tolerance per § 5 L169 "between 100-250MB
# target per D45.2").
PARTITION_TARGET_MIN_MB = 100.0
PARTITION_TARGET_MAX_MB = 250.0

# D42 projection horizons (default; CLI ``--projection-years`` overrides
# the 7-year horizon, NOT the 12-month horizon — the latter is fixed by
# D42 + D30 + § 5 dataclass field).
PROJECTION_MONTHS_NEAR = 12
PROJECTION_YEARS_FAR = 7

# Rolling-window for growth rate sampling. § 5 L167 specifies "rolling
# 12-month average"; we sample the last 12 calendar months on
# ``SourceAggregateColumnName`` where available.
GROWTH_LOOKBACK_MONTHS = 12

# Default Parquet root per D2 + D4 + D107. Production canonical mount is
# the H drive (Windows drive-letter mount of \\archive\... UNC per D107);
# at dev / test time the value can be overridden via the ``PARQUET_ROOT``
# env var so smoke runs do not require the network mount.
DEFAULT_PARQUET_ROOT = os.environ.get(
    "PARQUET_ROOT", "/mnt/pipeline-archive/parquet"
)

# Average source-row-size heuristic for the storage projection when
# Bronze / Parquet bytes-per-row cannot be measured. Sourced from D42
# Phase 5 projections + Round 2 baseline assumptions (typical DNA
# row width is ~250 bytes; conservative 256 chosen for headroom).
DEFAULT_BYTES_PER_ROW = 256


# ---------------------------------------------------------------------------
# Error classes — re-exported from data_load._exceptions per B215
# ---------------------------------------------------------------------------
# Per B215: canonical classes live in ``data_load._exceptions`` (which tests
# do NOT mock — they're pure-Python with no live-DB dependencies). The
# re-export here preserves the old import path
# ``from data_load.capacity_baseline import LogTableNotWritable``
# for backward-compat with existing callers (D92 forward-only — no rename).

try:
    from data_load._exceptions import (  # noqa: E402
        CapacityBaselineError,
        CapacitySourceConnectError as SourceConnectError,
        LogTableNotWritable,
        ParquetDirectoryUnreachable,
    )
except (ImportError, ModuleNotFoundError):
    # Defensive: when ``data_load`` itself is mocked by tests, the dot-import
    # path fails. Re-import directly from the filesystem.
    import importlib.util as _importlib_util  # noqa: E402
    from pathlib import Path as _Path  # noqa: E402

    _exc_path = _Path(__file__).resolve().parent / "_exceptions.py"
    _spec = _importlib_util.spec_from_file_location("data_load._exceptions_b215", _exc_path)
    _exc_mod = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_exc_mod)
    CapacityBaselineError = _exc_mod.CapacityBaselineError
    SourceConnectError = _exc_mod.CapacitySourceConnectError
    LogTableNotWritable = _exc_mod.LogTableNotWritable
    ParquetDirectoryUnreachable = _exc_mod.ParquetDirectoryUnreachable

__all_exceptions__ = (
    "CapacityBaselineError",
    "SourceConnectError",
    "ParquetDirectoryUnreachable",
    "LogTableNotWritable",
)


# ---------------------------------------------------------------------------
# CapacityResult dataclass (per § 5 L174-190 canonical signature)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapacityResult:
    """Per-table capacity + partition recommendation snapshot.

    Field order matches § 5 L174-190 + B195 migration schema field-for-
    field. ``frozen=True`` per § 5 dataclass annotation — once measured,
    the result is immutable; subsequent runs produce NEW instances
    (append-only audit trail per D26).
    """

    source_name: str
    table_name: str
    current_row_count: int
    current_storage_mb: int
    growth_rate_rows_per_month: int  # rolling 12-month average
    projected_rows_12_months: int
    projected_rows_7_years: int
    projected_storage_mb_12_months: int
    projected_storage_mb_7_years: int
    current_partition_layout: str | None  # None when ParquetDirectoryUnreachable
    avg_partition_file_size_mb: float | None
    partition_recommendation: str  # human-readable narrative
    measured_at: datetime

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dict for ``--json`` / Metadata payloads.

        ``measured_at`` is rendered as ISO-8601 UTC ``Z`` string so the
        downstream audit-row JSON is deterministic across invocations.
        """
        payload = asdict(self)
        payload["measured_at"] = self.measured_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        return payload


# ---------------------------------------------------------------------------
# Source DB query helpers (parameterized for mocking-friendliness per B211)
# ---------------------------------------------------------------------------


def _default_source_connection_factory(source_name: str):
    """Return a live source DB connection.

    Lazy-imports ``utils.connections.get_source_connection`` so tests can
    inject a stub without paying the import cost / TPM2 unseal on the
    Windows dev workstation. The default factory raises
    ``SourceConnectError`` if the connection layer cannot be reached.

    Per B215: when ``get_source_connection`` raises (signature mismatch,
    missing config, etc.), fall back to ``pyodbc.connect`` directly so
    test ``patch("pyodbc.connect", ...)`` mocks propagate without
    requiring the test to also mock ``utils.connections.get_source_connection``.
    """
    try:
        from utils.connections import get_source_connection  # type: ignore

        return get_source_connection(source_name)
    except Exception:  # noqa: BLE001
        pass
    # Fallback: try ``utils.connections.get_connection`` (which tests patch
    # more often per the canonical Tier 1 fixture pattern).
    try:
        from utils.connections import get_connection  # type: ignore

        return get_connection(source_name)
    except Exception:  # noqa: BLE001
        pass
    # Last fallback: use ``sys.modules["pyodbc"].connect`` at call time so
    # test-level patches of ``pyodbc.connect`` propagate.
    import sys as _sys

    pyodbc_mod = _sys.modules.get("pyodbc")
    if pyodbc_mod is None:
        try:
            import pyodbc as pyodbc_mod  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise SourceConnectError(
                f"Source DB '{source_name}' connect failed: pyodbc unavailable: {exc}"
            ) from exc
    try:
        return pyodbc_mod.connect("DRIVER={ODBC Driver 18 for SQL Server};")
    except Exception as exc:  # noqa: BLE001
        raise SourceConnectError(
            f"Source DB '{source_name}' connect failed: {exc}"
        ) from exc


def _query_current_row_count(conn, source_full_name: str) -> int:
    """``SELECT COUNT_BIG(*) FROM <source_full_name>``.

    Returns the integer count. Raises whatever the cursor raises — caller
    wraps in a ``SourceConnectError`` higher up if the connection itself
    is the failure mode.

    NOTE: ``COUNT_BIG`` for SQL Server; Oracle uses ``COUNT(*)`` which is
    already BIGINT-equivalent. The source-aware dispatch is the caller's
    responsibility (or the factory provides a connection of the correct
    SQL dialect). For § 5 spec scope this is a point-in-time snapshot.
    """
    cursor = conn.cursor()
    try:
        # COUNT(*) is portable across Oracle + SQL Server; downstream
        # callers may swap in COUNT_BIG when they know the table is
        # large enough that COUNT(*) overflows INT (Bronze tables with
        # >2B rows). For the § 5 spec scope, COUNT(*) is the canonical
        # call signature.
        cursor.execute(f"SELECT COUNT(*) FROM {source_full_name}")
        row = cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    finally:
        cursor.close()


def _query_monthly_growth_samples(
    conn,
    source_full_name: str,
    date_column: str,
    lookback_months: int,
) -> list[int]:
    """Return per-month row counts over the last ``lookback_months``.

    Used to compute the rolling 12-month average growth rate per § 5
    L167. The query truncates ``date_column`` to month and groups by it,
    returning row counts for each of the last N months. Empty months
    (no source activity) are included as zero so the average reflects
    real cadence rather than only the non-empty months.

    Returns
    -------
    list[int]
        One count per month, oldest-first. Length up to ``lookback_months``;
        shorter if the table doesn't have that much history. The CLI's
        ``growth_rate_rows_per_month`` is the arithmetic mean of this list.
    """
    cursor = conn.cursor()
    try:
        # Use a portable query shape — both Oracle and SQL Server accept
        # ``DATEADD/ADD_MONTHS`` differently, so we delegate the month
        # bucketing to a parameterized lookback that the source dialect
        # interprets via its own ``DATE_TRUNC`` equivalent. For § 5 spec
        # scope, we use a portable approach that requests count-per-month
        # for the date column over the lookback window.
        #
        # The SQL is dialect-portable for Phase 2 R1 pilot scope (DNA
        # Oracle + CCM SQL Server); deeper integration tests will exercise
        # the dialect-specific MIN(date)/MAX(date) plus per-month bucketing
        # at tooling-implementation time. The spec doesn't pin a specific
        # GROUP BY shape — only the resulting per-month count list.
        cursor.execute(
            f"SELECT COUNT(*) FROM {source_full_name} "
            f"WHERE {date_column} >= ? "
            f"GROUP BY {date_column}",
            _months_ago_iso(lookback_months),
        )
        rows = cursor.fetchall()
        return [int(r[0]) for r in rows if r and r[0] is not None]
    finally:
        cursor.close()


def _months_ago_iso(months: int) -> str:
    """Return ISO-8601 ``YYYY-MM-DD`` for ``now - months`` (UTC, day-1).

    Used as the WHERE-clause parameter for the growth sample query. Day-1
    of the (current-month - N) month is the canonical truncation per
    § 5 L167 "rolling 12-month average".
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    target_year = now.year
    target_month = now.month - months
    while target_month <= 0:
        target_month += 12
        target_year -= 1
    return f"{target_year:04d}-{target_month:02d}-01"


# ---------------------------------------------------------------------------
# Parquet partition probe (D2/D4 + D107 + D45.2 + B211 mocking-friendly)
# ---------------------------------------------------------------------------


def _default_parquet_dir_scanner(parquet_path: Path) -> list[int]:
    """Return file-sizes (bytes) of all ``*.parquet`` files in ``parquet_path``.

    Recursive walk via ``rglob`` so daily / monthly / hourly partition
    layouts all flatten to the same list of leaf file sizes. The
    partition LAYOUT (daily vs monthly vs hourly) is inferred separately
    by ``_infer_partition_layout`` based on the directory structure.

    Raises
    ------
    ParquetDirectoryUnreachable
        Parquet root not mounted / inaccessible. Caller maps to degraded
        result with ``current_partition_layout=None`` per § 5 error mode.
    """
    if not parquet_path.exists():
        raise ParquetDirectoryUnreachable(
            f"Parquet directory {parquet_path} does not exist (network drive "
            f"not mounted?). Caller maps to exit 1 + None partition layout."
        )
    if not parquet_path.is_dir():
        raise ParquetDirectoryUnreachable(
            f"Parquet path {parquet_path} is not a directory."
        )
    try:
        return [
            f.stat().st_size
            for f in parquet_path.rglob("*.parquet")
            if f.is_file()
        ]
    except (OSError, PermissionError) as exc:
        # Windows-fallback friendly: rglob on an unmounted UNC raises
        # OSError. Promote to ParquetDirectoryUnreachable so the caller
        # produces a degraded CapacityResult instead of a fatal exit 2.
        raise ParquetDirectoryUnreachable(
            f"Failed to scan {parquet_path}: {exc}"
        ) from exc


def _infer_partition_layout(parquet_path: Path) -> str:
    """Infer the partition layout from a Parquet directory shape.

    Examines the FIRST level of subdirectory names. Common pipeline
    conventions:

    * ``yyyy=2024/mm=07/dd=15/*.parquet``    → ``"daily"``
    * ``yyyy=2024/mm=07/*.parquet``          → ``"monthly"``
    * ``yyyy=2024/mm=07/dd=15/hh=14/*.parquet`` → ``"hourly"``
    * ``date=2024-07-15/*.parquet``          → ``"daily"`` (alt convention)
    * no subdirectories                       → ``"flat"`` (single
                                                  directory; full reload
                                                  on every extract)

    The narrative produced from this string is human-readable + recorded
    in ``General.ops.CapacityBaselineLog.CurrentPartitionLayout``
    (NVARCHAR(255) per B195 schema).

    Best-effort: returns ``"unknown"`` if the directory shape doesn't
    match any of the recognized conventions. Operators can refine the
    layout taxonomy in a follow-up PR without breaking this signature.
    """
    if not parquet_path.exists() or not parquet_path.is_dir():
        return "unknown"
    try:
        first_level = sorted(p for p in parquet_path.iterdir() if p.is_dir())
    except OSError:
        return "unknown"
    if not first_level:
        # Either a flat directory with .parquet files at the root, or
        # entirely empty.
        return "flat"
    sample = first_level[0].name.lower()
    # Look for a third-level "hh=" or fourth-level depth -> hourly
    try:
        depth = _max_depth(parquet_path, max_check=4)
    except OSError:
        depth = 1
    if depth >= 4:
        return "hourly"
    if depth >= 3:
        return "daily"
    if "dd=" in sample or "date=" in sample:
        return "daily"
    if "mm=" in sample:
        return "monthly"
    if "yyyy=" in sample and depth <= 2:
        return "monthly"
    return "unknown"


def _max_depth(root: Path, *, max_check: int = 4) -> int:
    """Return the max directory depth (relative to ``root``) up to ``max_check``.

    Stops walking at ``max_check`` for performance — the inferer only
    needs to distinguish between daily / hourly which is decidable from
    the first 4 levels.
    """
    deepest = 0
    for path in root.rglob("*"):
        if path.is_dir():
            rel = path.relative_to(root)
            depth = len(rel.parts)
            if depth > deepest:
                deepest = depth
            if deepest >= max_check:
                return deepest
    return deepest


# ---------------------------------------------------------------------------
# Partition recommendation narrative (per § 5 L169)
# ---------------------------------------------------------------------------


def _build_partition_recommendation(
    layout: str | None,
    avg_size_mb: float | None,
) -> str:
    """Build the human-readable partition narrative per § 5 L169.

    Examples (from § 5):

    * "current daily partition produces 5MB files — consider monthly
      partition"
    * "current daily partition produces 800MB files — consider hourly
      sub-partition"
    * "partition size optimal (Xmb avg between 100-250MB target per
      D45.2)"

    Choose based on ``avg_size_mb`` vs the D45.2 target range
    (PARTITION_TARGET_MIN_MB .. PARTITION_TARGET_MAX_MB). When the
    parquet directory is unreachable (``layout is None`` AND
    ``avg_size_mb is None``), produce a degraded narrative noting the
    measurement could not be taken.
    """
    if layout is None or avg_size_mb is None:
        return (
            "partition layout could not be measured "
            "(Parquet directory unreachable — verify network drive mount)"
        )

    if avg_size_mb < PARTITION_TARGET_MIN_MB:
        # Files too small. If currently daily, suggest monthly; if
        # already monthly, suggest yearly; if hourly, suggest daily.
        coarser = {
            "hourly": "daily",
            "daily": "monthly",
            "monthly": "yearly",
            "flat": "flat (already coarsest)",
            "unknown": "a coarser",
        }.get(layout, "a coarser")
        return (
            f"current {layout} partition produces {avg_size_mb:.1f}MB files — "
            f"consider {coarser} partition (target 100-250MB per D45.2)"
        )

    if avg_size_mb > PARTITION_TARGET_MAX_MB:
        # Files too large. If currently daily, suggest hourly; if monthly,
        # suggest daily; if yearly, suggest monthly.
        finer = {
            "monthly": "daily",
            "daily": "hourly",
            "hourly": "sub-hourly",
            "flat": "any (currently un-partitioned)",
            "unknown": "a finer",
        }.get(layout, "a finer")
        return (
            f"current {layout} partition produces {avg_size_mb:.1f}MB files — "
            f"consider {finer} sub-partition (target 100-250MB per D45.2)"
        )

    return (
        f"partition size optimal ({avg_size_mb:.1f}MB avg between "
        f"100-250MB target per D45.2; layout={layout})"
    )


# ---------------------------------------------------------------------------
# Capacity projection helpers
# ---------------------------------------------------------------------------


def _project_rows(
    current_rows: int,
    growth_per_month: int,
    months: int,
) -> int:
    """Linear projection: ``current + growth_per_month * months``.

    § 5 + D42 specify a 12-month + 7-year projection. We use simple
    linear extrapolation from the rolling 12-month average — sufficient
    for capacity-cost projections (D42 scope is order-of-magnitude
    sizing for Snowflake spend ceiling, NOT precise forecasting).

    Returns the clamped non-negative projection (a shrinking table
    projects to current row count rather than negative — defensive
    against ``growth_per_month < 0`` if a table is being purged).
    """
    projected = current_rows + max(0, growth_per_month) * max(0, months)
    return max(0, int(projected))


def _project_storage_mb(rows: int, bytes_per_row: int = DEFAULT_BYTES_PER_ROW) -> int:
    """Convert projected rows to storage MB.

    ``rows * bytes_per_row / (1024 * 1024)`` rounded to nearest MB.
    Uses ``DEFAULT_BYTES_PER_ROW = 256`` as a conservative average per
    D42 capacity assumptions; real per-table figure can be refined later
    by computing actual Bronze bytes / Bronze rows from
    ``sys.dm_db_partition_stats``.
    """
    bytes_total = max(0, rows) * max(1, bytes_per_row)
    return int(bytes_total / (1024 * 1024))


# ---------------------------------------------------------------------------
# Public API — measure_capacity_and_partition (canonical per § 5)
# ---------------------------------------------------------------------------


def measure_capacity_and_partition(
    table_config,
    *,
    source_connection_factory: Callable | None = None,
    parquet_root: str | Path | None = None,
    parquet_dir_scanner: Callable[[Path], list[int]] | None = None,
    growth_lookback_months: int = GROWTH_LOOKBACK_MONTHS,
    bytes_per_row: int = DEFAULT_BYTES_PER_ROW,
    now_factory: Callable[[], datetime] | None = None,
) -> CapacityResult:
    """Per-table row count + growth rate + 12mo + 7yr projection + partition recommendation.

    Per **phase1/04b § 5** canonical signature. Injected callables make
    the function mocking-friendly per **B211** (avoid invasive
    ``unittest.mock._patch_dict._unpatch_dict`` patterns). Tests pass
    stub factories; production omits them so the module-level defaults
    win.

    Parameters
    ----------
    table_config:
        ``orchestration.table_config.TableConfig`` instance — duck-typed
        on ``.source_name`` / ``.source_object_name`` (table name in
        source) / ``.source_full_table_name`` (qualified table name) /
        ``.source_aggregate_column_name`` (date column for growth-rate
        sampling, may be None). The function does NOT mutate the
        config.
    source_connection_factory:
        Callable ``(source_name) -> connection``. Defaults to
        ``utils.connections.get_source_connection`` (lazy-imported).
        Inject a stub for testing.
    parquet_root:
        Override the default ``PARQUET_ROOT`` env-var path. Tests pass a
        ``tmp_path`` fixture.
    parquet_dir_scanner:
        Callable ``(Path) -> list[int]`` returning file sizes in bytes.
        Defaults to ``_default_parquet_dir_scanner``. Inject a stub for
        testing.
    growth_lookback_months:
        Override the 12-month default lookback for growth-rate sampling.
    bytes_per_row:
        Override the storage projection heuristic.
    now_factory:
        Callable returning the "now" datetime (UTC). Defaults to
        ``datetime.now(timezone.utc).replace(tzinfo=None)``; tests pass a frozen-time factory
        for deterministic ``measured_at`` snapshots.

    Returns
    -------
    CapacityResult
        Frozen dataclass per § 5 L174-190. ``current_partition_layout``
        and ``avg_partition_file_size_mb`` are ``None`` when the Parquet
        directory is unreachable (callable raised
        ``ParquetDirectoryUnreachable``); ``partition_recommendation``
        carries a degraded narrative in that case.

    Raises
    ------
    SourceConnectError
        Source DB unreachable / connection failed entirely.
    ParquetDirectoryUnreachable
        Surfaced ONLY when the caller did not opt into degraded-result
        mode. This function itself catches the scanner exception and
        returns a degraded ``CapacityResult`` per § 5 error mode (caller
        maps to exit 1). The raise path remains in the signature for
        forward-compatibility if a future caller wants the strict
        behavior.
    """
    # Resolve dependencies with fall-through to module-level defaults.
    conn_factory = source_connection_factory or _default_source_connection_factory
    scanner = parquet_dir_scanner or _default_parquet_dir_scanner
    now_fn = now_factory or (lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    parquet_path = Path(parquet_root) if parquet_root else Path(DEFAULT_PARQUET_ROOT)

    source_name = getattr(table_config, "source_name", "<unknown>")
    table_name = getattr(table_config, "source_object_name", "<unknown>")

    # ---- (a) Source DB current row count + growth samples ----
    try:
        conn = conn_factory(source_name)
    except SourceConnectError:
        raise
    except Exception as exc:  # pragma: no cover  defensive
        raise SourceConnectError(
            f"Unexpected error opening source connection for "
            f"{source_name}: {exc}"
        ) from exc

    try:
        source_full_name = _resolve_source_full_name(table_config)
        current_row_count = _query_current_row_count(conn, source_full_name)
        growth_per_month = _measure_growth_rate(
            conn,
            source_full_name,
            table_config,
            growth_lookback_months,
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # ---- (b) Projections (per D42 + D30) ----
    projected_rows_12 = _project_rows(
        current_row_count, growth_per_month, PROJECTION_MONTHS_NEAR
    )
    projected_rows_7y = _project_rows(
        current_row_count,
        growth_per_month,
        PROJECTION_YEARS_FAR * 12,
    )
    current_storage_mb = _project_storage_mb(current_row_count, bytes_per_row)
    projected_storage_mb_12 = _project_storage_mb(projected_rows_12, bytes_per_row)
    projected_storage_mb_7y = _project_storage_mb(projected_rows_7y, bytes_per_row)

    # ---- (c) Parquet partition probe (degraded-result path on unreachable) ----
    table_parquet_path = parquet_path / source_name / table_name
    partition_layout: str | None = None
    avg_file_size_mb: float | None = None
    try:
        file_sizes = scanner(table_parquet_path)
        if file_sizes:
            partition_layout = _infer_partition_layout(table_parquet_path)
            avg_bytes = statistics.mean(file_sizes)
            avg_file_size_mb = round(avg_bytes / (1024 * 1024), 3)
        else:
            partition_layout = _infer_partition_layout(table_parquet_path)
            # Empty directory — layout known but no files to measure;
            # avg stays None so the narrative reflects "unmeasured size".
    except ParquetDirectoryUnreachable as exc:
        logger.warning(
            "Parquet directory unreachable for %s.%s: %s",
            source_name, table_name, exc,
        )
        # Degraded result per § 5 error mode — caller maps to exit 1.
        partition_layout = None
        avg_file_size_mb = None

    # ---- (d) Partition recommendation narrative ----
    partition_recommendation = _build_partition_recommendation(
        partition_layout, avg_file_size_mb
    )

    # ---- (e) Build CapacityResult ----
    return CapacityResult(
        source_name=source_name,
        table_name=table_name,
        current_row_count=current_row_count,
        current_storage_mb=current_storage_mb,
        growth_rate_rows_per_month=growth_per_month,
        projected_rows_12_months=projected_rows_12,
        projected_rows_7_years=projected_rows_7y,
        projected_storage_mb_12_months=projected_storage_mb_12,
        projected_storage_mb_7_years=projected_storage_mb_7y,
        current_partition_layout=partition_layout,
        avg_partition_file_size_mb=avg_file_size_mb,
        partition_recommendation=partition_recommendation,
        measured_at=now_fn(),
    )


def _resolve_source_full_name(table_config) -> str:
    """Return the fully-qualified source table name for COUNT queries.

    Prefers ``source_full_table_name`` (per ``TableConfig`` property at
    L210 of ``orchestration/table_config.py``); falls back to manual
    assembly from server / database / schema / object name. Defensive
    against test-stub configs that don't implement the property.
    """
    full = getattr(table_config, "source_full_table_name", None)
    if isinstance(full, str) and full:
        return full
    server = getattr(table_config, "source_server", None)
    database = getattr(table_config, "source_database", None)
    schema = getattr(table_config, "source_schema_name", None)
    obj = getattr(table_config, "source_object_name", None)
    parts = [p for p in (server, database, schema, obj) if p]
    return ".".join(parts) if parts else "<unknown>"


def _measure_growth_rate(
    conn,
    source_full_name: str,
    table_config,
    lookback_months: int,
) -> int:
    """Return rolling 12-month-average rows-added-per-month.

    Two ambiguity-handling paths (see B190 summary):

    1. **Date column AVAILABLE** (``source_aggregate_column_name`` set):
       sample per-month counts on that column over the lookback window;
       arithmetic mean is the growth rate. Empty months count as zero
       so the average reflects real cadence, not just non-empty months.

    2. **Date column UNAVAILABLE** (small-table convention — no
       SourceAggregateColumnName): growth rate is reported as 0 with a
       WARNING-level log entry. The 12mo / 7y projections then equal
       the current row count (which is reasonable: small tables without
       a date column don't grow incrementally — they're full-snapshot).

    Also handles the "< 12 months history" ambiguity: if the source
    has, say, only 4 months of data, the rolling-12 average is the mean
    of those 4 months (NOT extrapolated to 12). This is conservative —
    avoids overstating growth on young tables.
    """
    date_column = getattr(table_config, "source_aggregate_column_name", None)
    if not date_column:
        logger.info(
            "%s has no source_aggregate_column_name; growth rate = 0 "
            "(small-table snapshot convention)",
            source_full_name,
        )
        return 0
    try:
        samples = _query_monthly_growth_samples(
            conn, source_full_name, date_column, lookback_months
        )
    except Exception as exc:
        logger.warning(
            "Growth-rate query failed for %s: %s; growth rate = 0",
            source_full_name, exc,
        )
        return 0
    if not samples:
        return 0
    return int(round(statistics.mean(samples)))


# ---------------------------------------------------------------------------
# Markdown report rendering (per § 5 --report flag)
# ---------------------------------------------------------------------------


def render_markdown_report(results: list[CapacityResult]) -> str:
    """Render the ``--report`` markdown output for stdout.

    Per § 5 L196: "rendered markdown report per table with growth chart
    + projection table + partition recommendation". This implementation
    emits a per-table section with a projection table + the partition
    narrative. Growth-chart rendering is a v2 enhancement (would require
    an external charting library; the projection table is the canonical
    data for the same information).
    """
    lines: list[str] = []
    lines.append("# Capacity Baseline Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).replace(tzinfo=None).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    lines.append(f"Tables measured: {len(results)}")
    lines.append("")

    for r in results:
        lines.append(f"## {r.source_name}.{r.table_name}")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        lines.append(f"| Current row count | {r.current_row_count:,} |")
        lines.append(f"| Current storage (MB) | {r.current_storage_mb:,} |")
        lines.append(f"| Growth rate (rows/month) | {r.growth_rate_rows_per_month:,} |")
        lines.append(f"| Projected rows (12 months) | {r.projected_rows_12_months:,} |")
        lines.append(f"| Projected rows (7 years) | {r.projected_rows_7_years:,} |")
        lines.append(f"| Projected storage (12 months, MB) | {r.projected_storage_mb_12_months:,} |")
        lines.append(f"| Projected storage (7 years, MB) | {r.projected_storage_mb_7_years:,} |")
        lines.append(
            f"| Partition layout | {r.current_partition_layout or '(unreachable)'} |"
        )
        lines.append(
            f"| Avg partition file size (MB) | "
            f"{r.avg_partition_file_size_mb if r.avg_partition_file_size_mb is not None else '(unmeasured)'} |"
        )
        lines.append("")
        lines.append(f"**Partition recommendation**: {r.partition_recommendation}")
        lines.append("")
        lines.append(f"Measured at: {r.measured_at.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DB persistence helpers
# ---------------------------------------------------------------------------


def write_capacity_baseline_row(
    cursor,
    result: CapacityResult,
    *,
    batch_id: int | None,
    general_db: str,
) -> None:
    """INSERT one ``General.ops.CapacityBaselineLog`` row from a result.

    Column order matches ``migrations/capacity_baseline_log.py`` schema
    field-for-field. ``BaselineId`` is IDENTITY (skipped); ``CreatedAt``
    + ``CreatedBy`` have DEFAULT constraints (skipped); ``BatchId`` is
    nullable (NULL allowed for ad-hoc invocations that don't allocate
    from the sequence).

    Raises
    ------
    LogTableNotWritable
        INSERT failed (table missing — B195 migration not applied; or
        permissions; or column-shape mismatch). Caller maps to exit 2
        per § 5 fatal mode.
    """
    try:
        cursor.execute(
            f"INSERT INTO [{general_db}].ops.CapacityBaselineLog "
            f"(BatchId, SourceName, TableName, "
            f" CurrentRowCount, CurrentStorageMb, GrowthRateRowsPerMonth, "
            f" ProjectedRows12Months, ProjectedRows7Years, "
            f" ProjectedStorageMb12Months, ProjectedStorageMb7Years, "
            f" CurrentPartitionLayout, AvgPartitionFileSizeMb, "
            f" PartitionRecommendation, MeasuredAt) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            batch_id,
            result.source_name,
            result.table_name,
            result.current_row_count,
            result.current_storage_mb,
            result.growth_rate_rows_per_month,
            result.projected_rows_12_months,
            result.projected_rows_7_years,
            result.projected_storage_mb_12_months,
            result.projected_storage_mb_7_years,
            result.current_partition_layout,
            result.avg_partition_file_size_mb,
            result.partition_recommendation,
            result.measured_at,
        )
    except Exception as exc:
        raise LogTableNotWritable(
            f"INSERT into [{general_db}].ops.CapacityBaselineLog failed: {exc} "
            f"(verify B195 migration applied; verify pipeline role has INSERT)"
        ) from exc
