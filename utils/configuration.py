"""Environment variables, BCP constants, paths, and CSV contract constants."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from /debi/.env (NOT project root)
load_dotenv("/debi/.env")

# ---------------------------------------------------------------------------
# Pipeline environment selection
# ---------------------------------------------------------------------------
# Set the PIPELINE_ENV environment variable to select which credential set
# the pipeline loads:
#
#   PIPELINE_ENV=prod  -> uses UDM_PROD_* (production server / login)
#   PIPELINE_ENV=dev   -> uses UDM_CX_SERVER / UDM_DEV_* (development)
#   unset / anything else -> defaults to dev (safe default — never auto-prod)
#
# Set this in /debi/.env for the standard host, or override per-invocation:
#   PIPELINE_ENV=prod python3 main_small_tables.py --source DNA --workers 4
#
# The active selection is printed to stdout at import time so it's visible
# in every pipeline log.
PIPELINE_ENV = os.getenv("PIPELINE_ENV", "dev").lower()
IS_PROD = PIPELINE_ENV == "prod"
IS_DEV = not IS_PROD

# Active target — everything downstream reads these
if IS_PROD:
    # --- Database Connection Vars (production) ---
    SQL_SERVER_HOST = os.getenv("UDM_PROD_SERVER", "")
    SQL_SERVER_PORT = int(os.getenv("UDM_DEV_PORT", "1433"))
    SQL_SERVER_USER = os.getenv("UDM_PROD_UID", "")
    SQL_SERVER_PASSWORD = os.getenv("UDM_PROD_PASSWORD", "")
else:
    # --- Database Connection Vars (development) ---
    SQL_SERVER_HOST = os.getenv("UDM_CX_SERVER", "")
    SQL_SERVER_PORT = int(os.getenv("UDM_DEV_PORT", "1433"))
    SQL_SERVER_USER = os.getenv("UDM_DEV_UID", "")
    SQL_SERVER_PASSWORD = os.getenv("UDM_DEV_PASSWORD", "")

# Once-per-process startup banner so operators can confirm which environment
# is active without having to grep config files. Uses print() because logging
# isn't configured this early in the import chain.
print(
    f"[utils.config] PIPELINE_ENV={PIPELINE_ENV!r}  "
    f"IS_PROD={IS_PROD}  "
    f"SQL_SERVER_HOST={SQL_SERVER_HOST or '<unset>'}  "
    f"SQL_SERVER_USER={SQL_SERVER_USER or '<unset>'}",
    flush=True,
)

# Target database names
GENERAL_DB = os.getenv('DB_GENERAL', 'General')
STAGE_DB = os.getenv('DB_STAGE', 'UDM_Stage')
BRONZE_DB = os.getenv('DB_BRONZE', 'UDM_Bronze')
SILVER_DB = os.getenv('DB_SILVER', 'UDM_Silver')
GOLD_DB = os.getenv('DB_GOLD', 'UDM_Gold')

# Oracle connection vars
ORACLE_USER = os.getenv("DNA_REPORTING_PROD_USERNAME", "")
ORACLE_PASSWORD = os.getenv("DNA_REPORT", "")
ORACLE_HOST = os.getenv("DNA_REPORTING_PROD_HOST", "")
ORACLE_PORT = int(os.getenv("DNA_REPORTING_PROD_PORT", "1521"))
ORACLE_SERVICE = os.getenv("DNA_REPORTING_PROD_SID", "")


# Oracle Instant Client path (for oracledb thick mode)
ORACLE_CLIENT_DIR = os.getenv("ORACLE_CLIENT_DIR", "/usr/lib/oracle/19.25/client64/lib")

# --- BCP Configuration ---
BCP_PATH = os.getenv("BCP_PATH", "/opt/mssql-tools18/bin/bcp")

# ---------------------------------------------------------------------------
# BCP throughput-optimized batch sizes (per table type)
# ---------------------------------------------------------------------------
# Stage tables (heaps, TABLOCK via sp_tableoption):
#   With BU locks, no row/page-level locks exist — no escalation concern.
#   Each batch commit triggers a log flush; fewer larger batches = fewer flushes.
#   100K–500K optimal. If chunks are ~256 MB, omitting -b entirely works too.
BCP_STAGE_BATCH_SIZE = int(os.getenv("BCP_STAGE_BATCH_SIZE", "100000"))
#
# Bronze tables (clustered index, no TABLOCK, concurrent readers required):
#   Without TABLOCK, BCP uses row-level locks. Lock escalation is checked at
#   ~2,500 acquisitions and attempted at ~5,000 per HoBt. Staying at 800
#   prevents escalation to table-level X locks that block concurrent readers.
BCP_BRONZE_BATCH_SIZE = int(os.getenv("BCP_BRONZE_BATCH_SIZE", "800"))
#
# Legacy fallback — used when caller doesn't specify stage vs bronze.
BCP_BATCH_SIZE = int(os.getenv("BCP_BATCH_SIZE", "5000"))

# ---------------------------------------------------------------------------
# BCP-HANG-FIX-v3: First-run Bronze load configuration
# ---------------------------------------------------------------------------
# When a Bronze table is empty (first-run backfill, no concurrent readers),
# it is safe to use the old pipeline's TABLOCK approach with a large batch
# size. This eliminates the connection-drop hang caused by 800-row micro-
# commits with row-level locks on clustered index tables.
#
# The rationale: TABLOCK on a clustered-index table acquires an EXCLUSIVE
# lock, blocking all readers. This is unacceptable during incremental loads
# where Bronze has active readers. But for first-run / empty tables, there
# are NO concurrent readers — TABLOCK is safe and dramatically improves
# throughput + connection stability (the BU lock keeps the session active,
# preventing TLS/TCP idle drops between batches).
#
# First-run Bronze loads: use TABLOCK + large batch size (100K).
# Falls back to BCP_BRONZE_BATCH_SIZE (800) for incremental loads.
BCP_BRONZE_FIRST_RUN_BATCH_SIZE = int(os.getenv(
    "BCP_BRONZE_FIRST_RUN_BATCH_SIZE", "100000"
))

# Row threshold above which first-run Bronze loads use TABLOCK.
# Tables with fewer rows than this are small enough that 800-batch loads
# complete quickly without hitting the TLS idle timeout.
BCP_BRONZE_TABLOCK_THRESHOLD = int(os.getenv(
    "BCP_BRONZE_TABLOCK_THRESHOLD", "10000"
))

# ---------------------------------------------------------------------------
# TDS packet size
# ---------------------------------------------------------------------------
# BCP-HANG-FIX-v3: Reduced from 16384 to 8192.
# 16384 sits exactly at Microsoft's documented maximum for encrypted
# connections (16,383 bytes), creating a dangerous TLS boundary condition:
#   - Each TLS record fragments into 12 TCP segments (reassembly-sensitive)
#   - Zero margin for SMUX headers if MARS is enabled
#   - Known ODBC Driver 18 + OpenSSL >= 3.2 incompatibility at this size
# 8192 cuts TCP segments per TLS record from 12 to 6, halving reassembly
# window and providing margin. Throughput impact is minimal for bulk ops
# where the bottleneck is SQL Server I/O, not network framing.
BCP_PACKET_SIZE = int(os.getenv("BCP_PACKET_SIZE", "8192"))

# SSL ceiling constant — TLS record size limit per RFC 2246 §6.2.2
BCP_SSL_MAX_PACKET_SIZE = 16384

# ---------------------------------------------------------------------------
# Parallel BCP streams (Stage heaps only)
# ---------------------------------------------------------------------------
# A single BCP stream typically achieves 100K–300K rows/sec. Parallel streams
# with sp_tableoption TABLOCK (BU locks are compatible) multiply throughput.
# 8 streams is a good starting point for Stage heaps with 10G networking.
# Bronze tables should NOT use parallel streams with TABLOCK (exclusive lock).
BCP_PARALLEL_STREAMS = int(os.getenv("BCP_PARALLEL_STREAMS", "8"))

# Minimum rows to trigger parallel BCP. Below this, single stream is fine.
BCP_PARALLEL_THRESHOLD = int(os.getenv("BCP_PARALLEL_THRESHOLD", "1000000"))

# ---------------------------------------------------------------------------
# Small table routing: pyodbc fast_executemany for tiny tables
# ---------------------------------------------------------------------------
# BCP subprocess startup costs ~1–2s (spawn, TDS handshake, lock acquisition).
# For tables < threshold, pyodbc fast_executemany completes in milliseconds.
BCP_SMALL_TABLE_THRESHOLD = int(os.getenv("BCP_SMALL_TABLE_THRESHOLD", "1000"))

# ---------------------------------------------------------------------------
# tmpfs for BCP CSV staging
# ---------------------------------------------------------------------------
# Writing CSVs to /dev/shm (tmpfs) eliminates source-side disk I/O.
# Reads/writes at memory bandwidth (~10–50 GB/s) vs NVMe (~3–7 GB/s).
# Falls back to CSV_OUTPUT_DIR if /dev/shm is unavailable or too small.
#
# DEFAULT: disabled. tmpfs lives in RAM, so on extraction-heavy days
# (especially large-table backfills) the CSVs compete with Polars
# DataFrames for memory and can OOM the server. Set CSV_TMPFS_ENABLED=true
# explicitly only when (a) RAM is plentiful, (b) CSV_OUTPUT_DIR I/O is
# the proven bottleneck, and (c) the data volume comfortably fits in
# tmpfs alongside the live extraction.
CSV_TMPFS_DIR = Path(os.getenv("CSV_TMPFS_DIR", "/dev/shm/udm_bcp"))
CSV_TMPFS_ENABLED = os.getenv("CSV_TMPFS_ENABLED", "false").lower() == "true"
# P1-7: BCP timeout in seconds — higher for large tables / initial backfills
BCP_TIMEOUT = int(os.getenv("BCP_TIMEOUT", "7200"))

# ---------------------------------------------------------------------------
# Recovery-model management
# ---------------------------------------------------------------------------
# Controls whether the BCP bulk-load context managers may switch the target
# database between FULL / BULK_LOGGED / SIMPLE recovery models around bulk
# loads, and whether the end-of-pipeline restore_simple_recovery() forces
# SIMPLE.
#
#   "auto"   (default): if a database is in FULL on entry, skip the swap
#            entirely and leave it in FULL. Otherwise switch to BULK_LOGGED
#            for the load and restore to whatever the database was on entry
#            (NOT hardcoded to FULL). End-of-pipeline restore_simple_recovery
#            also skips databases currently in FULL.
#
#            Production rule: production DBs are kept in FULL for PITR; the
#            pipeline never touches them. "auto" is safe by default.
#
#   "never": never change recovery model anywhere. Per-table options
#            (sp_tableoption, LOCK_ESCALATION) still apply.
#
#   "always": legacy behavior — always swap to BULK_LOGGED. On exit, restore
#            to the original model (still not hardcoded FULL — that bug is
#            fixed for all modes). Use only when you want forced minimal
#            logging on a database that wouldn't otherwise be touched.
PIPELINE_MANAGE_RECOVERY_MODEL = os.getenv(
    "PIPELINE_MANAGE_RECOVERY_MODEL", "auto"
).lower()

# BCP-HANG-FIX: Retry configuration for blocked BCP loads.
# When BCP times out (likely blocked by another session), retry with
# exponential backoff after cleaning up orphaned sessions. Default 3 retries
# gives attempts at 0s, 5s, 10s — total max wait ~15s before final failure.
BCP_MAX_RETRIES = int(os.getenv("BCP_MAX_RETRIES", "3"))

# BCP-HANG-FIX §7: Wait time in seconds after killing orphaned BULK INSERT
# sessions, to allow SQL Server to complete single-threaded rollback before
# retrying. For a 300K-row orphaned transaction, rollback typically takes 5-15s.
BCP_ORPHAN_ROLLBACK_WAIT = int(os.getenv("BCP_ORPHAN_ROLLBACK_WAIT", "15"))

# --- BCP Live Monitor Configuration ---
# BCP-HANG-FIX-v2: Background monitor thread polls SQL Server DMVs while BCP
# runs. These settings control how aggressively the monitor detects hangs.

# How often (seconds) the monitor queries SQL Server for diagnostics.
# Lower = more granular timeline but more load on SQL Server.
# 15s is a good balance: captures hang causes within 15s of onset.
BCP_MONITOR_INTERVAL = int(os.getenv("BCP_MONITOR_INTERVAL", "15"))

# How long (seconds) a definitive hang signal (e.g. LCK_M_IX wait, log full)
# must persist before the monitor triggers early abort. This is ALSO the
# initial grace period — no hang evaluation occurs before this many seconds.
# 120s is enough for BCP to establish connection and start inserting, while
# still catching hangs ~30x faster than waiting the full 7200s BCP_TIMEOUT.
BCP_HANG_ABORT_THRESHOLD = int(os.getenv("BCP_HANG_ABORT_THRESHOLD", "120"))

# ---------------------------------------------------------------------------
# BCP Monitor Skip Threshold (TODO-1: skip monitor for fast loads)
# ---------------------------------------------------------------------------
# Log evidence (2026-02-27): ACCTACCTROLEORG (174K rows) loaded in 3s,
# collecting 0 monitor snapshots — the monitor thread + pyodbc connection
# was pure overhead. For loads under this threshold, BCP runs unmonitored.
# The monitor's first poll is at BCP_MONITOR_INTERVAL (15s); loads completing
# faster than that never benefit from monitoring. 500K rows at ~15K rows/sec
# (Bronze worst-case) = ~33s, enough for 2 snapshots. Below that, monitoring
# adds overhead without actionable diagnostics.
BCP_MONITOR_ROW_THRESHOLD = int(os.getenv("BCP_MONITOR_ROW_THRESHOLD", "500000"))

# --- BCP CSV Contract (Single Source of Truth) ---
CSV_SEPARATOR = "\t"
CSV_ROW_TERMINATOR = "0x0A"  # LF only, passed to BCP -r flag
CSV_HAS_HEADER = False
CSV_QUOTE_STYLE = "never"
CSV_NULL_VALUE = ""
CSV_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S.%3f"
CSV_BATCH_SIZE = 4096  # Polars write_csv batch_size to avoid memory spikes

# --- File Paths ---
# CSV temp staging for BCP loads. Default points at the network-mounted
# VendorFiles share — has more capacity than the local server filesystem
# and avoids tmpfs / RAM pressure on extraction-heavy days. Can still be
# overridden per environment via the CSV_OUTPUT_DIR env var (typically
# in /debi/.env) — set it explicitly when running outside the standard
# server (dev workstations, CI, etc.).
CSV_OUTPUT_DIR = Path(os.getenv("CSV_OUTPUT_DIR", "/VendorFiles/PROD/PythonIngestions"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# --- ODBC Driver ---
ODBC_DRIVER = os.getenv("ODBC_DRIVER", "ODBC Driver 18 for SQL Server")

# --- SQL Server Source Connections (CCM, EPICOR, etc.) ---
# These can be extended per-source; for now they follow the same host or separate hosts
CCM_SERVER_HOST = os.getenv("CCMPROD_REPLICA_SERVER_FULL_NAME", SQL_SERVER_HOST)
CCM_SERVER_PORT = int(os.getenv("CCM_SERVER_PORT", str(1433)))
CCM_SERVER_USER = os.getenv("DLHDEV_UID", SQL_SERVER_USER)
CCM_SERVER_PASSWORD = os.getenv("DLHDEV_PASSWORD", SQL_SERVER_PASSWORD)

# V-7: Overlap minutes for large table windowed extraction.
# Extends each day's window backward to capture cross-midnight transactions.
# 0 = disabled (default). CDC handles duplicates idempotently via hash match.
OVERLAP_MINUTES = int(os.getenv("OVERLAP_MINUTES", "0"))

# B-2: SCD2 UPDATE batch size. Stay below 5,000 to prevent SQL Server
# lock escalation from row locks to table-level exclusive locks.
# Table-level exclusive locks override RCSI, blocking all concurrent readers.
SCD2_UPDATE_BATCH_SIZE = int(os.getenv("SCD2_UPDATE_BATCH_SIZE", "4000"))

# B-8: RSS memory ceiling in GB. Pipeline logs WARNING at 85% of this limit
# and ERROR at the limit. Polars + glibc arena fragmentation can cause RSS
# to grow monotonically during multi-table runs (Polars issue #23128).
# Combine with MALLOC_ARENA_MAX=2 (W-4) for best results.
#
# Sized for the production server: 64 GB physical RAM with ~49 GB safely
# usable after OS / SQL Server tooling overhead. Override per-environment
# via the MAX_RSS_GB env var if the host has different capacity.
MAX_RSS_GB = float(os.getenv("MAX_RSS_GB", "49.0"))

EPICOR_SERVER_HOST = os.getenv("EPICOR_SERVER_HOST", SQL_SERVER_HOST)
EPICOR_SERVER_PORT = int(os.getenv("EPICOR_SERVER_PORT", str(SQL_SERVER_PORT)))
EPICOR_SERVER_USER = os.getenv("EPICOR_SERVER_USER", SQL_SERVER_USER)
EPICOR_SERVER_PASSWORD = os.getenv("EPICOR_SERVER_PASSWORD", SQL_SERVER_PASSWORD)
