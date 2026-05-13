"""CLI common boilerplate — shared setup for small and large table pipelines.

L-1: Centralizes environment setup, logging, startup checks, RSS monitoring,
and TableConfig serialization that was duplicated between main_small_tables.py
and main_large_tables.py.

Import this module BEFORE any other project imports in main_*.py files.
Module-level code sets MALLOC_ARENA_MAX, POLARS_MAX_THREADS, and sys.path.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# M-1: Capture BEFORE setdefault — was MALLOC_ARENA_MAX set externally?
# glibc arena configuration is locked at process start — os.environ.setdefault()
# only covers child processes (ProcessPoolExecutor workers).
MALLOC_ARENA_EXTERNALLY_SET = "MALLOC_ARENA_MAX" in os.environ

# M-1: Set MALLOC_ARENA_MAX=2 for child processes. Reduces glibc arenas from
# 8x cores (48 on 6-core) to 2, preventing 10x memory bloat (Polars #23128).
os.environ.setdefault("MALLOC_ARENA_MAX", "2")
# M-2: POLARS_MAX_THREADS=1 prevents thread oversubscription when using
# ProcessPoolExecutor — parallelism is achieved via multiprocessing.
os.environ.setdefault("POLARS_MAX_THREADS", "1")

# Ensure project root is on sys.path for imports
sys.path.insert(0, str(Path(__file__).parent))

import configuration as config
from observability.log_handler import SqlServerLogHandler

logger = logging.getLogger(__name__)


def setup_logging(batch_id: int | None = None) -> SqlServerLogHandler:
    """Configure logging: StreamHandler + SqlServerLogHandler.

    Args:
        batch_id: Pipeline batch ID for log context.

    Returns:
        The SqlServerLogHandler instance (for flush/context updates).
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    )
    root.addHandler(console)

    # SQL Server log handler
    sql_handler = SqlServerLogHandler(level=getattr(logging, config.LOG_LEVEL, logging.INFO))
    if batch_id is not None:
        sql_handler.set_context(batch_id=batch_id)
    root.addHandler(sql_handler)

    return sql_handler


def startup_checks() -> None:
    """Run startup checks: staging cleanup + RCSI verification.

    P3-3: Clean up orphaned staging tables from previous crashed runs.
    E-9: Verify RCSI enabled on Bronze for non-blocking SCD2 updates.
    """
    from schema.staging_cleanup import cleanup_orphaned_staging_tables
    cleanup_orphaned_staging_tables()

    from connections import verify_rcsi_enabled
    verify_rcsi_enabled()


def warn_malloc_arena() -> None:
    """W-4: Warn if MALLOC_ARENA_MAX was not set in the external environment.

    glibc arena configuration is locked at process start. os.environ.setdefault()
    only covers child processes. The variable must be set before the Python
    interpreter starts (systemd unit file, shell wrapper, .bashrc).
    """
    if not MALLOC_ARENA_EXTERNALLY_SET:
        logger.warning(
            "W-4: MALLOC_ARENA_MAX was not set in the external environment "
            "(current: %s, set by os.environ.setdefault). glibc arena "
            "configuration is locked at process start. Set MALLOC_ARENA_MAX=2 "
            "in the systemd unit file or shell wrapper to prevent glibc arena "
            "fragmentation causing 10x memory bloat (Polars issue #23128).",
            os.environ.get("MALLOC_ARENA_MAX"),
        )


def warn_workers(workers: int) -> None:
    """M-2: Warn if workers exceed recommended maximum for 64 GB system."""
    if workers > 4:
        logger.warning(
            "M-2: Running with %d workers. On a 64 GB system, >4 workers risks OOM "
            "during CDC/SCD2 join operations (peak memory = 2.5-3x DataFrame size). "
            "Recommended: --workers 4 or fewer.",
            workers,
        )


def check_rss_memory(source_name: str, table_name: str) -> None:
    """B-8: Check RSS memory between table iterations.

    Polars + glibc arena fragmentation can cause RSS to grow monotonically
    during multi-table runs (Polars issue #23128). Logs WARNING at 85% of
    MAX_RSS_GB and ERROR at the limit.
    """
    try:
        import psutil
        rss_gb = psutil.Process().memory_info().rss / (1024 ** 3)
        if rss_gb > config.MAX_RSS_GB:
            logger.error(
                "B-8: RSS memory %.1f GB exceeds MAX_RSS_GB (%.1f GB) before %s.%s. "
                "Polars allocator may not be releasing memory to OS (issue #23128). "
                "Consider: (a) set MALLOC_ARENA_MAX=2 (W-4), (b) reduce --workers, "
                "(c) restart pipeline to reclaim RSS.",
                rss_gb, config.MAX_RSS_GB, source_name, table_name,
            )
        elif rss_gb > config.MAX_RSS_GB * 0.85:
            logger.warning(
                "B-8: RSS memory %.1f GB approaching MAX_RSS_GB (%.1f GB) before %s.%s.",
                rss_gb, config.MAX_RSS_GB, source_name, table_name,
            )
    except ImportError:
        pass  # psutil not installed — skip RSS check


def validate_cli_filters(
    source_name: str | None,
    table_name: str | None,
) -> None:
    """H-4: Validate --source and --table CLI arguments against UdmTablesList.

    Belt-and-suspenders guard: even though H-3 parameterizes queries, this
    catches typos early and prevents unexpected empty result sets.

    Raises:
        SystemExit: If the value is not found in UdmTablesList.
    """
    if source_name is None and table_name is None:
        return

    from orchestration.table_config import TableConfigLoader
    loader = TableConfigLoader()

    if source_name:
        known_sources = loader.get_known_sources()
        if source_name not in known_sources:
            logger.error(
                "H-4: --source '%s' not found in UdmTablesList. "
                "Known sources: %s",
                source_name, sorted(known_sources),
            )
            sys.exit(1)

    if table_name:
        known_tables = loader.get_known_tables()
        if table_name not in known_tables:
            logger.error(
                "H-4: --table '%s' not found in UdmTablesList. "
                "Known tables (first 20): %s",
                table_name, sorted(known_tables)[:20],
            )
            sys.exit(1)


def log_connection_overhead() -> None:
    """P-3: Log cumulative connection overhead at pipeline end."""
    from connections import get_connection_overhead
    total_ms, count = get_connection_overhead()
    if count > 0:
        logger.info(
            "P-3: Connection overhead: %.1f ms total across %d connections (%.1f ms avg)",
            total_ms, count, total_ms / count,
        )


def shutdown_connections() -> None:
    """Item-18: Close pooled connections at pipeline shutdown."""
    from connections import close_connection_pool
    close_connection_pool()


def table_config_to_dict(tc, batch_id: int) -> dict:
    """Serialize a ``TableConfig`` for cross-process transfer via
    ``ProcessPoolExecutor``.

    Uses ``dataclasses.asdict`` so every ``TableConfig`` field — including
    nested ``ColumnConfig`` dataclasses — is captured automatically. Adding
    a new field to ``TableConfig`` does NOT require updating this function;
    it simply rides along.

    Worker-only metadata (``batch_id``, ``force``, etc.) lives at the top
    level of the returned dict, alongside the dataclass fields.

    Why this matters
    ----------------

    Earlier this serializer enumerated fields by hand. Every time a new
    ``TableConfig`` field was added (``StripSuffix``, ``MaxRowsPerDay``,
    the SCD2 enhancement block) it was silently dropped at the worker
    boundary — runs with ``--workers > 1`` got dataclass defaults
    instead of the values from ``UdmTablesList``. ``--workers 1`` (no
    pool) was the only path where every field reached the orchestrator.
    The hand-list pattern made it look like everything worked because
    workflows tested with one worker first, and the bug only surfaced
    on production parallel runs.

    Args:
        tc: TableConfig instance.
        batch_id: Current batch ID.

    Returns:
        Dict suitable for pickling across process boundaries. The
        worker reconstructs via ``table_config_from_dict``.
    """
    from dataclasses import asdict

    d = asdict(tc)

    # exclude_columns is a set on the dataclass; asdict serializes it
    # as a set. Sets pickle fine, but we coerce on the worker side
    # defensively (older payloads may have it as a list).

    # Worker-only metadata. Kept separate from the dataclass fields so
    # the worker can pop them before TableConfig(**d) reconstruction.
    d["batch_id"] = batch_id
    d["force"] = False
    return d


# Field names that are NOT TableConfig dataclass fields. Worker reconstructors
# pop these before passing the rest as **kwargs to TableConfig(...).
_WORKER_METADATA_KEYS = ("batch_id", "force", "refresh_pks")


def table_config_from_dict(payload: dict):
    """Reconstruct a ``TableConfig`` (and nested ``ColumnConfig`` rows) from
    the dict produced by ``table_config_to_dict``.

    Returns a tuple ``(table_config, metadata_dict)`` where the
    metadata dict carries the worker-only keys (``batch_id``, ``force``,
    optionally ``refresh_pks``). Caller pulls what it needs from the
    metadata.

    Symmetric counterpart to ``table_config_to_dict`` — use both, and
    new ``TableConfig`` fields propagate end-to-end without touching
    main_large_tables.py or main_small_tables.py.
    """
    from orchestration.table_config import TableConfig, ColumnConfig

    payload = dict(payload)  # don't mutate the caller's dict

    metadata = {k: payload.pop(k) for k in _WORKER_METADATA_KEYS if k in payload}

    # Nested ColumnConfig dataclasses: asdict turned each into a dict;
    # rebuild the dataclass instances.
    columns_dicts = payload.pop("columns", [])
    columns = [ColumnConfig(**c) for c in columns_dicts]

    # exclude_columns: dataclasses.asdict preserves set type, but
    # pickle/unpickle through some transports may convert to list.
    # Coerce defensively.
    if "exclude_columns" in payload:
        ec = payload["exclude_columns"]
        if ec is None:
            payload["exclude_columns"] = set()
        elif not isinstance(ec, set):
            payload["exclude_columns"] = set(ec)

    tc = TableConfig(columns=columns, **payload)
    return tc, metadata

def final_cleanup_output_dir() -> None:
    """P3-7: Final sweep of CSV_OUTPUT_DIR at pipeline shutdown.

    Catches orphaned temp files from tables that failed mid-pipeline
    (after CSV write but before reaching the per-table CSV_CLEANUP step).
    On a 64 GB system with 4 workers, orphaned CSVs and .fmt files from
    a single failed large-table day can be multi-GB.

    Also cleans up tmpfs staging directory if enabled.

    Safe to call unconditionally — only deletes known pipeline temp patterns.
    """
    from data_load.bcp_loader import cleanup_tmpfs

    output_dir = Path(config.CSV_OUTPUT_DIR)
    if not output_dir.exists():
        return

    cleaned = 0
    # Clean all known pipeline temp file extensions
    for pattern in ("*.csv", "*.fmt"):
        for f in output_dir.glob(pattern):
            try:
                f.unlink()
                cleaned += 1
            except OSError:
                logger.warning("P3-7: Failed to delete orphaned file: %s", f)

    # Clean any leftover parallel BCP chunk directories
    for d in output_dir.glob("_chunks_*"):
        if d.is_dir():
            try:
                import shutil
                shutil.rmtree(d, ignore_errors=True)
                cleaned += 1
            except OSError:
                logger.warning("P3-7: Failed to remove chunk dir: %s", d)

    if cleaned > 0:
        logger.info(
            "P3-7: Final cleanup removed %d orphaned temp file(s) from %s",
            cleaned, output_dir,
        )

    # Clean tmpfs staging directory
    cleanup_tmpfs()

def restore_simple_recovery() -> None:
    """Restore UDM_Stage and UDM_Bronze to SIMPLE recovery after pipeline completes.

    Final cleanup step run unconditionally in every main module's shutdown
    sequence. The pre-pipeline-run state is whatever the operator left the
    database in; the daily pipeline ends with SIMPLE so the transaction log
    doesn't grow between runs (SIMPLE auto-truncates at each checkpoint).

    Production-safety gate (PIPELINE_MANAGE_RECOVERY_MODEL):
      * "auto" / "always": if a database is currently in FULL, leave it
        alone — production keeps FULL for PITR commitments.
      * "never": skip every database regardless of current model.

    Logs warnings on failure but does not raise — a failed restore should
    not mask pipeline success/failure exit codes.

    Uses its own connection because this runs after shutdown_connections()
    may have been called. Autocommit=True ensures the ALTER DATABASE commits
    immediately without an explicit COMMIT.
    """
    import configuration as pipeline_config
    from connections import get_connection, quote_identifier

    gate = pipeline_config.PIPELINE_MANAGE_RECOVERY_MODEL
    databases = [pipeline_config.STAGE_DB, pipeline_config.BRONZE_DB]

    if gate == "never":
        logger.info(
            "PIPELINE_MANAGE_RECOVERY_MODEL=never — skipping restore_simple_recovery "
            "for %s",
            ", ".join(databases),
        )
        return

    for database in databases:
        try:
            conn = get_connection(database)
            try:
                cursor = conn.cursor()
                # Check current model — skip if already SIMPLE or in FULL
                # (production rule: never force a FULL DB to SIMPLE).
                cursor.execute(
                    "SELECT recovery_model_desc FROM sys.databases WHERE name = ?",
                    database,
                )
                row = cursor.fetchone()
                current_model = row[0] if row else "UNKNOWN"

                if current_model == "SIMPLE":
                    logger.debug(
                        "Recovery model already SIMPLE on %s — no action needed",
                        database,
                    )
                elif current_model == "FULL":
                    logger.info(
                        "Recovery model on %s is FULL — leaving it alone "
                        "(production protection, gate=%s).",
                        database, gate,
                    )
                else:
                    logger.info(
                        "Restoring %s to SIMPLE recovery model (was %s)",
                        database, current_model,
                    )
                    cursor.execute(
                        f"ALTER DATABASE {quote_identifier(database)} "
                        f"SET RECOVERY SIMPLE"
                    )
                    # Verify the ALTER took effect
                    cursor.execute(
                        "SELECT recovery_model_desc FROM sys.databases "
                        "WHERE name = ?",
                        database,
                    )
                    row = cursor.fetchone()
                    if row and row[0] == "SIMPLE":
                        logger.info(
                            "Confirmed %s is now SIMPLE recovery model",
                            database,
                        )
                    else:
                        logger.warning(
                            "ALTER DATABASE SET RECOVERY SIMPLE did not take "
                            "effect on %s (current model: %s). Manual "
                            "intervention may be needed.",
                            database, row[0] if row else "unknown",
                        )
                cursor.close()
            finally:
                conn.close()
        except Exception:
            logger.exception(
                "Failed to restore SIMPLE recovery model for %s — "
                "manual intervention may be needed",
                database,
            )