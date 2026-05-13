"""R-6: create ``General.ops.SCD2RepairLog`` audit table.

Every R-6 chain-repair operation writes one row to this table for traceability.
Idempotent — skips creation when the table already exists.

Usage::

    python3 migrations/scd2_repair_log.py --dry-run
    python3 migrations/scd2_repair_log.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.configuration as config
from utils.connections import get_general_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


REPAIR_LOG_DDL = """
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = 'ops'
)
EXEC('CREATE SCHEMA ops');

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_SCHEMA = 'ops' AND TABLE_NAME = 'SCD2RepairLog'
)
CREATE TABLE ops.SCD2RepairLog (
    RepairId        BIGINT IDENTITY(1,1) PRIMARY KEY,
    BatchId         BIGINT NULL,
    SourceName      NVARCHAR(50)  NOT NULL,
    TableName       NVARCHAR(128) NOT NULL,
    RepairType      NVARCHAR(50)  NOT NULL,    -- e.g. 'sentinel_fill', 'orphan_cleanup', 'duplicate_active_dedup'
    Status          NVARCHAR(20)  NOT NULL,    -- 'DRY_RUN' | 'APPLIED' | 'FAILED' | 'SKIPPED'
    RowsAffected    BIGINT NULL,
    SamplePks       NVARCHAR(MAX) NULL,        -- JSON array of up to 10 sample PKs
    Message         NVARCHAR(MAX) NULL,
    ErrorMessage    NVARCHAR(MAX) NULL,
    StartedAt       DATETIME2(3)  NOT NULL CONSTRAINT DF_SCD2RepairLog_StartedAt DEFAULT SYSDATETIME(),
    CompletedAt     DATETIME2(3)  NULL,
    DurationMs      BIGINT NULL,
    OperatorUser    NVARCHAR(128) NOT NULL CONSTRAINT DF_SCD2RepairLog_OperatorUser DEFAULT SUSER_SNAME(),
    INDEX IX_SCD2RepairLog_Table NONCLUSTERED (SourceName, TableName, StartedAt DESC)
);
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Preview DDL without executing.")
    args = parser.parse_args()

    if args.dry_run:
        logger.info("[DRY RUN] [%s] %s", config.GENERAL_DB, REPAIR_LOG_DDL.strip())
        return 0

    conn = get_general_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(REPAIR_LOG_DDL)
        conn.commit()
        cursor.close()
        logger.info("ops.SCD2RepairLog ensured (created or already present).")
        return 0
    except Exception:
        logger.exception("Failed to create ops.SCD2RepairLog.")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
