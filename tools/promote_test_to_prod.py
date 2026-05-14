"""Round 4 § 3.6 — ``tools/promote_test_to_prod.py``.

Per **Round 4 § 3.6** at ``docs/migration/phase1/04_tools.md`` L837-947
(canonical spec) + **Round 1 SP-4 ``PipelineExecutionGate_AcquireTest``**
canonical DDL at ``docs/migration/phase1/01_database_schema.md``
L1531-1649 + **Round 1 SP-6 ``PipelineExecutionGate_AcknowledgeCancellation``**
canonical DDL at L1713-1735.

Failover acknowledgment per D29 (revised) + D33 (cooperative cancellation).
When the prod server is unhealthy, the test server's pipeline can be
promoted to take over a cycle (AM or PM). This tool wraps SP-4's three-
verdict decision tree and writes the audit trail for whichever outcome
SP-4 returns.

What this tool does
-------------------

1. (Pre-condition) Invoke ``tools/verify_server_parity.py`` (Round 3 § 3.2)
   against ``server='test'``. If ``ParityFatalError`` raised AND
   ``--skip-parity-check`` is NOT set, exit 2 (fatal); operator must
   restore parity before retrying. ``--skip-parity-check`` logs CRITICAL
   and proceeds.
2. Acquire the General DB connection + invoke SP-4
   ``PipelineExecutionGate_AcquireTest`` with ``@CycleType`` / ``@CycleDate``
   / ``@AcknowledgmentOnly`` (B79 amendment — proposed; see Idempotency
   section below). SP-4's internal ``sp_getapplock`` on
   ``'pipeline_gate_' + @CycleType + '_' + CONVERT(VARCHAR(10), @CycleDate, 23)``
   serializes concurrent test promotions; tool itself does NOT issue
   ``sp_getapplock`` directly per spec § 3.6 L872 (SP-4 owns the lock).
3. Read SP-4's ``@Action`` OUTPUT — one of (per L1546):

   * ``'EXIT_SUCCEEDED'`` — prod cycle already completed; no failover
     needed; exit 0 (informational outcome — clean prod run)
   * ``'EXIT_RUNNING_HEALTHY'`` — prod is healthy + running with recent
     heartbeat; no failover needed; exit 1 (informational, NOT page —
     operator misread the dashboard per spec § 4.2 F)
   * ``'PROCEED_FAILOVER'`` — prod failed / timed-out / never-started /
     stale heartbeat; SP-4 has already flipped ``ExecutingServer='test'``
     + claimed a new BatchId (per SP-4 body L1605-1623). In ``--apply``,
     this tool then invokes SP-6 ``AcknowledgeCancellation`` to flip the
     gate Status to ``'CANCELLED'`` (closing the prior prod cycle's
     state) + writes a ``CYCLE_FAILED_OVER`` event-tracker row.

4. Write ONE ``CLI_PROMOTE_TEST_TO_PROD`` row to
   ``General.ops.PipelineEventLog`` per D76 — ``Metadata`` JSON includes
   verdict, cycle, cycle_date, test_parity_status, applied flag, dry_run
   flag, actor, justification, event_kind='failover_promotion', exit_code.
5. Render stdout per spec § 3.6 L898-930 (human or JSON via ``--json``).
6. Exit 0 / 1 / 2 per D74 + spec § 3.6 L934-937.

CLI contract
------------

::

    # Operator-initiated failover during morning cycle
    python3 tools/promote_test_to_prod.py \\
        --cycle AM --cycle-date 2026-05-12 \\
        --actor operator \\
        --justification 'Prod server unreachable since 02:15; ops verified' \\
        --apply

    # Dry-run: would this be acceptable RIGHT NOW?
    python3 tools/promote_test_to_prod.py --cycle AM --cycle-date 2026-05-12 \\
        --actor operator \\
        --justification 'check failover preconditions'

    # Skip-parity-override (DANGEROUS — requires justification keywords)
    python3 tools/promote_test_to_prod.py --cycle PM --cycle-date 2026-05-12 \\
        --actor pipeline-lead \\
        --justification 'parity_check_skip_override: known-good drift in '
                        'IsIndex column on EPICOR.CUSTOMER per RB-7 step 4' \\
        --skip-parity-check --apply

Exit codes (per D74 + spec § 3.6 L934-937)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **0** — ``@Action='PROCEED_FAILOVER'`` successful (or dry-run preview)
  OR ``@Action='EXIT_SUCCEEDED'`` (prod cycle already done — clean
  informational outcome)
* **1** — ``@Action='EXIT_RUNNING_HEALTHY'`` (prod is healthy and running;
  no failover needed — operator review, not page) — informational
* **2** — fatal: ``ParityFatalError`` (without ``--skip-parity-check``);
  ``GateNotAcquirable`` (sp_getapplock blocked at SP-4 boundary);
  ``VaultConfigError`` (env / connection unavailable); B88 mutex
  violation (``--dry-run`` AND ``--apply``); missing required args

Audit row (per D76 + spec § 3.6 L853)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``General.ops.PipelineEventLog.EventType = 'CLI_PROMOTE_TEST_TO_PROD'``
  (one of the 11 R4 canonical CLI_* family values per CLAUDE.md)
* ONE row per INVOCATION (spec § 3.6 produces; SP-4's internal
  ``FAILOVER_TRIGGERED`` event row at SP-4 body L1632-1641 is a
  DISTINCT row — both surface together for the failover audit trail)
* ``Status in {SUCCESS, FAILED}`` (SUCCESS for exit 0/1; FAILED for exit 2)
* ``Metadata`` JSON shape::

    {
        "event_kind": "failover_promotion",
        "actor": "<operator>",
        "justification": "<text>",
        "cycle": "AM" | "PM",
        "cycle_date": "YYYY-MM-DD",
        "verdict": "PROCEED_FAILOVER" | "EXIT_SUCCEEDED"
                   | "EXIT_RUNNING_HEALTHY" | "EXIT_ACKNOWLEDGED",
        "test_parity_status": "pass" | "warn" | "fail" | "skipped",
        "applied": <bool>,
        "dry_run": <bool>,
        "skip_parity_check": <bool>,
        "batch_id": <int|null>,        # NEW BatchId on PROCEED_FAILOVER
        "gate_id": <int|null>,         # PipelineExecutionGate.GateId
        "exit_code": <int>,
        "started_at": "<ISO-8601 naive-UTC>",
        "completed_at": "<ISO-8601 naive-UTC>"
    }

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: PRIMARY: Manual operator CLI for emergency failover (RB-7
  DR drill OR RB-9 operations response). SECONDARY: Automic (rare —
  auto-detected prod heartbeat absence per spec L857).
* **Frequency**: PRIMARY ad-hoc / event-driven (NOT scheduled).
  SECONDARY rare Automic self-trigger.
* **Idempotency**: YES per spec § 3.6 L860-863 — SP-4 with
  ``@AcknowledgmentOnly=1`` is read-only; in ``--apply`` mode,
  re-invocation on an already-acknowledged failover is a no-op (SP-6 +
  the gate row's ``CancellationAcknowledgedAt`` is NOT NULL on the
  second call, so the second SP-6 UPDATE matches zero rows per L1731-
  1733 idempotency clause).
* **Concurrency**: SP-4's internal ``sp_getapplock`` on the cycle
  Resource string per Round 1 L1560-1564 serializes concurrent
  promotions on the same cycle/date. ``--workers`` NOT supported
  (single SP execution; serial is correct).
* **Audit-row family**: ``CLI_PROMOTE_TEST_TO_PROD`` per D76 + CLAUDE.md
  CLI_* family registry; AND ``CYCLE_FAILED_OVER`` via event_tracker on
  successful PROCEED_FAILOVER apply per CLAUDE.md CYCLE_* family.
* **Routing**: PRIMARY tracker ``ONE_OFF_SCRIPTS.md`` operator tools
  table (manual + event-driven). NOT in frozen-11 Automic inventory
  (Automic ``JOB_FAILOVER_TEST`` per Round 2 § 5.1 is a DR-rehearsal
  test driver, NOT this tool's invocation path).

B79 amendment (proposed)
~~~~~~~~~~~~~~~~~~~~~~~~

Per BACKLOG B79 + spec § 3.6 L852 + L862: SP-4 may evolve to accept
``@AcknowledgmentOnly BIT = 0`` parameter to support dry-run preview
without modifying gate state. When ``@AcknowledgmentOnly=1``, SP-4
returns ``@Action='EXIT_ACKNOWLEDGED'`` (a fourth verdict, distinct
from the three production-action verdicts) without invoking the MERGE
at L1605-1623 or the audit-event INSERT at L1632-1641.

This tool assumes B79 has landed and passes ``@AcknowledgmentOnly=1``
on every ``--dry-run`` invocation. If SP-4 has NOT yet been amended (B79
not yet executed), the EXEC fails with a Procedure-arg-count mismatch
that pyodbc raises as a generic ``Error``; the tool catches this and:

* In ``--dry-run`` mode: returns ``verdict='EXIT_ACKNOWLEDGED'`` (as a
  best-effort placeholder) + a CRITICAL log entry noting the B79
  dependency; the user sees the placeholder verdict and knows B79
  remains open. Exit 0.
* In ``--apply`` mode: this tool does NOT pass ``@AcknowledgmentOnly=1``,
  so this case does not arise.

D-numbers consumed
------------------

D27 (cross-server parity contract — pre-condition),
D29 revised (Automic-driven AM/PM coordination + failover),
D33 (cooperative cancellation via gate flag),
D65 (parity drift severity classification — fatal blocks; warning
allowed; informational silent),
D67 (Tier 0 smoke discipline),
D74-D77 (CLI exit-code contract + argument naming + audit-row contract +
Tier 0 6-canonical-assertion scaffold),
D92 (forward-only additive — exception module extension preserves
backward compatibility),
D102 (CDC-NOW-MS / SCD2-P1-f naive-UTC datetime invariant — every
datetime construction strips tzinfo + truncates to milliseconds).

Canonical references cited (per Pitfall #9.l producer self-check)
-----------------------------------------------------------------

* SP-4 DDL: ``phase1/01_database_schema.md`` L1531-1649 (re-read at
  producer Gate 1 self-check per HANDOFF §8 Pitfall #9.l).
  Real parameters: ``@CycleType NVARCHAR(10)`` (L1539),
  ``@CycleDate DATE`` (L1540),
  ``@ExpectedStartTime DATETIME2(3)`` (L1541),
  ``@HeartbeatStaleMinutes INT = 10`` (L1542),
  ``@ProdMaxRuntimeMinutes INT = 120`` (L1543),
  ``@GateId BIGINT OUTPUT`` (L1544),
  ``@BatchId BIGINT OUTPUT`` (L1545),
  ``@Action NVARCHAR(30) OUTPUT`` (L1546).
  ``@Action`` OUTPUT values: ``'EXIT_SUCCEEDED'`` (L1583),
  ``'EXIT_RUNNING_HEALTHY'`` (L1595), ``'PROCEED_FAILOVER'`` (L1629).
  Internal ``sp_getapplock`` on the gate Resource string per L1552-1564.
  Forward-additive B79 proposes ``@AcknowledgmentOnly BIT = 0`` for
  dry-run preview returning ``@Action='EXIT_ACKNOWLEDGED'``.
* SP-3 DDL: ``phase1/01_database_schema.md`` L1456-1525 — the canonical
  prod-claim flow this tool's failover supersedes. Resource format
  identical to SP-4 (L1467-1468) so the lock is SHARED between the
  two SPs per spec § 3.6 L872.
* SP-6 DDL: ``phase1/01_database_schema.md`` L1720-1734 — invoked
  ONLY in ``--apply`` mode after SP-4 returns ``PROCEED_FAILOVER``.
  Real parameter: ``@GateId BIGINT`` (L1721). SP-6 is idempotent (re-
  invocation on already-acknowledged row matches zero per L1731-1733).
* PipelineExecutionGate DDL: ``phase1/01_database_schema.md`` § 4
  L294-347 (re-read at producer Gate 1 self-check per Pitfall #9.l).
  Real columns referenced: ``CycleType NVARCHAR(10)`` (L305 — CHECK
  CK_PipelineExecutionGate_CycleType IN ('AM','PM') per L326-327),
  ``CycleDate DATE`` (L306),
  ``ExpectedStartTime DATETIME2(3) NOT NULL`` (L307),
  ``ActualStartTime DATETIME2(3) NULL`` (L308),
  ``ExecutingServer NVARCHAR(20) NULL`` (L310 — CHECK IN ('production',
  'test') per L331-332; earlier doc draft used the wrong column name
  ``ServerRole`` — that column lives on PipelineEventLog L139, NOT on
  this table — Pitfall #9.f cross-table column-name lift caught at
  spec first-pass per spec L846),
  ``Status NVARCHAR(20) NOT NULL DEFAULT 'PENDING'`` (L311 — CHECK IN
  ('PENDING', 'STARTING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'TIMEOUT',
  'CANCELLED') per L328-330),
  ``BatchId BIGINT NULL`` (L312),
  ``LastHeartbeatAt DATETIME2(3) NULL`` (L313),
  ``CancellationRequested BIT NOT NULL DEFAULT 0`` (L317),
  ``CancellationAcknowledgedAt DATETIME2(3) NULL`` (L321),
  ``GateId BIGINT IDENTITY(1,1)`` (L304 — PK).
* CLI conventions: ``phase1/04_tools.md`` § 1.4 (canonical args) +
  § 1.7 (invocation-pattern heuristic — AUTOMIC_RUN_ID env + isatty) +
  § 1.8 (exit-code mapping) + § 1.9 (boilerplate template) +
  § 1.2 (dry-run-default — this is a side-effecting tool by virtue of
  SP-6 invocation in apply mode).

See also
--------

* ``data_load/_exceptions.py`` — ``ParityFatalError`` + ``GateNotAcquirable``
  + ``VaultConfigError`` (per B215 canonical exception module pattern;
  per spec § 3.6 L868-873 canonical names + forward-only additive per D92).
* ``tools/verify_server_parity.py`` — Round 4 § 3.7 sibling tool that
  this tool invokes as a pre-condition (per spec § 3.6 L900).
* ``tools/enforce_retention.py`` — Round 4 § 3.8 sibling tool; this
  tool follows the same author pattern (Tier 0-friendly structure,
  ``_write_audit_row`` with SCOPE_IDENTITY return + ``skip`` parameter).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Project root on sys.path so we can reach data_load + utils.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Exception classes from the canonical _exceptions module (B215 pattern —
# tools import from data_load._exceptions because tests may mock the
# engine modules as MagicMock, replacing class symbols with MagicMock
# attributes and breaking ``except SomeError as exc:`` blocks).
try:
    from data_load._exceptions import (  # noqa: E402
        GateNotAcquirable,
        ParityFatalError,
        VaultConfigError,
    )
except (ImportError, ModuleNotFoundError):
    # Defensive fallback for environments where ``data_load`` is mocked
    # as MagicMock — re-import the file directly from the filesystem.
    import importlib.util as _importlib_util  # noqa: E402

    _exc_path = Path(__file__).resolve().parent.parent / "data_load" / "_exceptions.py"
    _spec = _importlib_util.spec_from_file_location(
        "data_load._exceptions_promote_test_to_prod", _exc_path
    )
    _exc_mod = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_exc_mod)
    ParityFatalError = _exc_mod.ParityFatalError
    GateNotAcquirable = _exc_mod.GateNotAcquirable
    VaultConfigError = _exc_mod.VaultConfigError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exit-code constants (per D74 + spec § 3.6 L934-937)
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_FATAL = 2

# D76 EventType registered in CLAUDE.md CLI_* family registry (one of the
# 11 R4 canonical values).
EVENT_TYPE = "CLI_PROMOTE_TEST_TO_PROD"

# CYCLE_FAILED_OVER event family value per CLAUDE.md CYCLE_* family
# registry (Round 4 D76 + Round 6 § 6.4). Written via event_tracker on
# successful PROCEED_FAILOVER apply per spec § 3.6 L851.
CYCLE_FAILED_OVER_EVENT = "CYCLE_FAILED_OVER"

# Canonical @Action OUTPUT values per SP-4 DDL L1546 + L1583/L1595/L1629.
# Tool MUST NOT invent values (Pitfall #9.c — caught at spec first-pass
# per L845 noting the earlier draft used 'exit'/'failover' incorrectly).
ACTION_EXIT_SUCCEEDED = "EXIT_SUCCEEDED"
ACTION_EXIT_RUNNING_HEALTHY = "EXIT_RUNNING_HEALTHY"
ACTION_PROCEED_FAILOVER = "PROCEED_FAILOVER"
# B79-proposed forward-additive verdict for @AcknowledgmentOnly=1
# (dry-run preview). NOT yet locked into SP-4 schema — see B79 in BACKLOG.
ACTION_EXIT_ACKNOWLEDGED = "EXIT_ACKNOWLEDGED"

# Canonical SP names per spec § 3.6 L841 + L1538/L1720.
SP_ACQUIRE_TEST = "ops.PipelineExecutionGate_AcquireTest"
SP_ACKNOWLEDGE_CANCELLATION = "ops.PipelineExecutionGate_AcknowledgeCancellation"

# Heartbeat-staleness threshold default per SP-4 L1542 (@HeartbeatStaleMinutes
# INT = 10). Surfaced as a constant for test introspection; the canonical
# default is set inside SP-4, so the tool relies on the SP default unless
# overridden (future B-number).
DEFAULT_HEARTBEAT_STALE_MINUTES = 10
DEFAULT_PROD_MAX_RUNTIME_MINUTES = 120

# Sentinel for the spec L900 "test server parity verified" pre-condition.
SERVER_TARGET_TEST = "test"


# ---------------------------------------------------------------------------
# Actor detection (per § 1.7 invocation pattern heuristic)
# ---------------------------------------------------------------------------


def _detect_actor() -> str:
    """Resolve ``--actor`` default per spec § 1.7 invocation-pattern heuristic.

    1. AUTOMIC_RUN_ID env var present -> 'automic'
    2. sys.stdin.isatty() -> 'operator'
    3. Else -> 'pipeline'
    """
    if os.environ.get("AUTOMIC_RUN_ID"):
        return "automic"
    try:
        if sys.stdin.isatty():
            return "operator"
    except (AttributeError, ValueError):
        # ValueError: I/O operation on closed file (pytest -s pipe)
        pass
    return "pipeline"


# ---------------------------------------------------------------------------
# Naive-UTC datetime helper (per CDC-NOW-MS / SCD2-P1-f invariant)
# ---------------------------------------------------------------------------


def _now_naive_utc_ms() -> datetime:
    """Return tz-naive UTC datetime truncated to milliseconds.

    Per CDC-NOW-MS / SCD2-P1-f invariant from CLAUDE.md Do-NOT section:
    BCP CSV writes use ``'%Y-%m-%d %H:%M:%S.%3f'`` (ms only); pyodbc
    sends an aware datetime as DATETIMEOFFSET which SQL Server implicitly
    converts when comparing DATETIME2 = DATETIMEOFFSET — producing a
    different UTC moment than what BCP stored on non-UTC servers. Naive
    + ms precision matches the storage format on both sides.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Truncate to milliseconds (drop sub-millisecond precision).
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def _format_iso(dt: datetime) -> str:
    """Render a naive-UTC datetime as a canonical ISO-8601 'Z' string."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Cycle-date parsing + validation
# ---------------------------------------------------------------------------


def _parse_cycle_date(raw: str | None) -> date:
    """Parse an ISO YYYY-MM-DD ``--cycle-date`` value.

    Defaults to today (UTC) per spec § 3.6 table at L890-892. Validates
    against ``date.fromisoformat`` strictly — non-ISO inputs raise
    ``ValueError`` which the caller surfaces as exit 2 (missing/invalid
    required arg per spec L869).
    """
    if raw is None:
        return _now_naive_utc_ms().date()
    return date.fromisoformat(raw)


def _validate_cycle(cycle: str) -> str:
    """Verify ``--cycle`` is 'AM' or 'PM' per CK_PipelineExecutionGate_CycleType.

    Per Round 1 canonical L326-327 + spec § 3.6 L891. Strict match (case
    sensitive — operators are expected to pass uppercase per the canonical
    CHECK constraint, and SP-4 string-concats ``@CycleType`` into the
    Resource string at L1552-1553).
    """
    if cycle not in ("AM", "PM"):
        raise ValueError(
            f"--cycle must be one of 'AM' / 'PM' "
            f"per CK_PipelineExecutionGate_CycleType (got {cycle!r})"
        )
    return cycle


# ---------------------------------------------------------------------------
# Parity-precheck integration (Round 3 § 3.2 — wrapped by Round 4 § 3.7)
# ---------------------------------------------------------------------------


def _resolve_default_parity_verifier() -> Callable:
    """Return a callable that invokes the Round 3 § 3.2 parity verifier.

    Resolves at CALL TIME so tests patching the module after tool import
    are honored. Production path: import ``verify_server_parity`` from
    Round 3 § 3.2's canonical module location. If the import fails (e.g.
    the module hasn't been deployed yet on dev), the fallback returns
    a NO-OP verifier that logs WARNING and returns 'skipped' — this
    preserves operator visibility into the missing pre-condition rather
    than silently failing closed (operator would expect spec-stated
    behavior of "parity verified ✓" on stdout per spec L900).
    """

    def _verify(server: str = SERVER_TARGET_TEST):
        # Try the canonical Round 3 § 3.2 module first.
        try:
            from tools.verify_server_parity import verify_server_parity  # type: ignore

            return verify_server_parity(server=server)
        except (ImportError, AttributeError):
            pass
        try:
            from data_load.parity_baseline_capture import (  # type: ignore
                verify_server_parity as _verify_via_capture,
            )

            return _verify_via_capture(server=server)
        except (ImportError, AttributeError):
            pass
        # No verifier wired in yet (dev environment) — log + return a
        # synthetic 'skipped' ParityReport-shaped dict so downstream
        # rendering shows "parity precheck skipped (verifier unavailable)".
        logger.warning(
            "Parity verifier unavailable (Round 3 § 3.2 module not deployed); "
            "treating as skipped. Operator should run tools/verify_server_parity.py "
            "manually before relying on this tool's verdict."
        )
        return {"overall": "skipped", "checks": []}

    return _verify


def _run_parity_precheck(
    parity_verifier: Callable,
    *,
    skip_parity_check: bool,
) -> tuple[str, str | None]:
    """Run the test-server parity precheck per spec § 3.6 L900.

    Returns a tuple ``(parity_status, error_message)``:

    * ``parity_status`` is one of ``'pass'`` / ``'warn'`` / ``'fail'`` /
      ``'skipped'`` (matches spec § 3.6 L932 ``test_parity_status`` JSON
      key). ``'skipped'`` is returned when ``--skip-parity-check`` is set
      OR when the verifier module is unavailable.
    * ``error_message`` is the parity report's free-text summary on
      fatal-tier mismatch (None otherwise).

    Raises :class:`ParityFatalError` on fatal-tier drift UNLESS
    ``skip_parity_check=True`` (in which case logs CRITICAL and returns
    ``('skipped', <error>)``).
    """
    if skip_parity_check:
        logger.critical(
            "PARITY PRECHECK SKIPPED via --skip-parity-check. "
            "Operator MUST justify this in --justification. The test server's "
            "parity drift may propagate into prod state if SP-4 returns "
            "PROCEED_FAILOVER and --apply is set."
        )
        return ("skipped", None)

    try:
        report = parity_verifier(server=SERVER_TARGET_TEST)
    except ParityFatalError:
        # The verifier itself raised — re-raise; caller will exit 2.
        raise
    except Exception as exc:  # noqa: BLE001
        # Generic verifier failure — treat as fatal per spec § 3.6 L868
        # "test server's parity check has fatal-tier drift; CANNOT promote
        # until parity restored; exit 2".
        raise ParityFatalError(
            f"Parity verifier raised {type(exc).__name__}: {exc}"
        ) from exc

    # Report shape per Round 3 § 3.2 — either a ParityReport dataclass
    # with ``.overall`` attribute OR a synthetic dict from the fallback.
    overall = getattr(report, "overall", None)
    if overall is None and isinstance(report, dict):
        overall = report.get("overall")

    if overall == "fail":
        raise ParityFatalError(
            f"Test-server parity check returned overall='fail'. "
            f"See PipelineLog for per-check details. "
            f"Operator MUST restore parity before retrying (or pass "
            f"--skip-parity-check with justification per spec § 3.6 L894)."
        )
    if overall == "warn":
        logger.warning(
            "Test-server parity returned overall='warn' "
            "(non-fatal per D65 tier mapping); proceeding."
        )
        return ("warn", None)
    if overall == "pass":
        return ("pass", None)
    if overall == "skipped":
        return ("skipped", None)
    # Unknown verdict — log + treat conservatively as skipped (operator
    # will see the parity_status='skipped' in the audit row).
    logger.warning(
        "Parity verifier returned unknown overall=%r; treating as skipped.",
        overall,
    )
    return ("skipped", None)


# ---------------------------------------------------------------------------
# SP-4 invocation — canonical signature ``PipelineExecutionGate_AcquireTest``
# ---------------------------------------------------------------------------


def _invoke_sp4(
    connection,
    *,
    cycle: str,
    cycle_date: date,
    acknowledgment_only: bool,
    general_db: str,
) -> tuple[str | None, int | None, int | None, str | None]:
    """Invoke SP-4 ``PipelineExecutionGate_AcquireTest`` and return verdict.

    Per SP-4 canonical body at ``phase1/01_database_schema.md`` L1531-1649
    (re-read per Pitfall #9.l):

    * Parameters: ``@CycleType NVARCHAR(10)``, ``@CycleDate DATE``,
      ``@ExpectedStartTime DATETIME2(3)`` (L1539-1541), ``@GateId BIGINT
      OUTPUT``, ``@BatchId BIGINT OUTPUT``, ``@Action NVARCHAR(30) OUTPUT``
      (L1544-1546).
    * B79-proposed ``@AcknowledgmentOnly BIT = 0`` is forward-additive —
      assumed present at the SP boundary by this tool. If SP-4 has NOT
      been amended yet (B79 open), the EXEC fails with a parameter-count
      mismatch which pyodbc raises; we catch + return verdict=None +
      let caller decide the path.

    Returns
    -------
    tuple[str | None, int | None, int | None, str | None]
        ``(action, gate_id, batch_id, error_message)`` —
        ``action`` is one of the canonical @Action values or None on
        failure; ``error_message`` carries the pyodbc exception text on
        failure path.

    Raises
    ------
    GateNotAcquirable
        Surfaced via the SP-4 internal ``sp_getapplock`` RAISERROR per
        L1568 — pyodbc raises a generic Error which we pattern-match
        for the "Gate lock could not be acquired" text. Caller maps to
        exit 2.
    """
    cursor = connection.cursor()
    try:
        # @ExpectedStartTime defaults to invocation time (ms-truncated
        # naive UTC) — SP-4 honors any DATETIME2(3) value here for the
        # NOT_MATCHED INSERT branch (L1619-1623).
        expected_start = _now_naive_utc_ms()
        ack_bit = 1 if acknowledgment_only else 0

        # SQL Server OUTPUT parameter idiom for EXEC via pyodbc — DECLARE
        # locals + EXEC + SELECT them back. We pass @AcknowledgmentOnly
        # named (B79 amendment) so older SP-4 without the parameter raises
        # a clear "Procedure expects parameter ... not supplied" / "Too
        # many arguments" error that the caller can pattern-match.
        sql = (
            "DECLARE @gate_id BIGINT, @batch_id BIGINT, @action NVARCHAR(30); "
            f"EXEC [{general_db}].{SP_ACQUIRE_TEST} "
            "  @CycleType = ?, "
            "  @CycleDate = ?, "
            "  @ExpectedStartTime = ?, "
            "  @AcknowledgmentOnly = ?, "
            "  @GateId = @gate_id OUTPUT, "
            "  @BatchId = @batch_id OUTPUT, "
            "  @Action = @action OUTPUT; "
            "SELECT @action AS Action, @gate_id AS GateId, @batch_id AS BatchId;"
        )
        cursor.execute(
            sql,
            cycle,
            cycle_date,
            expected_start,
            ack_bit,
        )
        row = cursor.fetchone() if cursor.description is not None else None
        if row is None:
            return (None, None, None, "SP-4 returned no rows (unexpected)")
        action = row[0]
        gate_id = row[1]
        batch_id = row[2]
        return (
            action if action is not None else None,
            int(gate_id) if gate_id is not None else None,
            int(batch_id) if batch_id is not None else None,
            None,
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        # SP-4 RAISERROR at L1568 produces this exact substring; treat
        # as fatal lock contention.
        if "Gate lock could not be acquired" in msg:
            raise GateNotAcquirable(
                f"SP-4 sp_getapplock blocked for cycle={cycle} "
                f"cycle_date={cycle_date.isoformat()}: {msg}"
            ) from exc
        return (None, None, None, msg)
    finally:
        try:
            cursor.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# SP-6 invocation — only on successful PROCEED_FAILOVER + apply
# ---------------------------------------------------------------------------


def _invoke_sp6(
    connection,
    *,
    gate_id: int,
    general_db: str,
) -> bool:
    """Invoke SP-6 ``PipelineExecutionGate_AcknowledgeCancellation`` for ``gate_id``.

    Per SP-6 canonical body at ``phase1/01_database_schema.md`` L1720-1734.
    Idempotent (L1731-1733 ``CancellationAcknowledgedAt IS NULL`` clause
    means a second invocation matches zero rows). Returns True on success
    (no exception raised) — the actual row-count is reflected by the
    gate row's ``CancellationAcknowledgedAt`` not being NULL after the
    call, but we don't read it back (best-effort).

    Note per spec § 3.6 L850-851: in the PROCEED_FAILOVER path, SP-4 has
    ALREADY flipped the gate to ``ExecutingServer='test'`` + Status='STARTING'
    via the MERGE at L1605-1623 + claimed a new BatchId at L1603. SP-6's
    role here is to close the prior prod cycle's cancellation chain — the
    gate's CancellationRequested may have been set by an earlier SP-5
    invocation (prod self-cancel) per spec § 5.3.6, OR may be 0 (auto-
    failover without explicit cancel request). Either way, SP-6 is
    idempotent + harmless when CancellationRequested = 0 (matches zero rows).
    """
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"EXEC [{general_db}].{SP_ACKNOWLEDGE_CANCELLATION} @GateId = ?;",
            gate_id,
        )
        return True
    finally:
        try:
            cursor.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Audit-row writer — one CLI_PROMOTE_TEST_TO_PROD row per invocation
# ---------------------------------------------------------------------------


def _write_audit_row(
    metadata: dict,
    *,
    status: str,
    error_message: str | None = None,
    cursor_factory: Callable | None = None,
    general_db: str = "General",
    skip: bool = False,
) -> int | None:
    """INSERT one ``CLI_PROMOTE_TEST_TO_PROD`` row into PipelineEventLog.

    Per D76 + spec § 3.6 L853. ONE row per invocation. Best-effort:
    failures are logged but do not affect the verdict exit code (parity
    with ``tools/enforce_retention.py`` ``_write_audit_row`` pattern).

    Returns the IDENTITY value of the inserted row via SCOPE_IDENTITY()
    so the JSON ``audit_event_id`` key (per spec § 3.6 L932) can be
    populated. Returns None on failure (the JSON key is then null).

    When ``cursor_factory`` is injected (test path), the live
    ``utils.connections`` resolution is skipped.

    When ``skip=True`` (test path; main()'s ``no_audit_event``), the
    function returns None immediately without writing.
    """
    if skip:
        return None
    metadata_json = json.dumps(metadata, separators=(",", ":"), default=str)
    event_detail = (
        f"promote_test_to_prod / "
        f"cycle={metadata.get('cycle')} "
        f"cycle_date={metadata.get('cycle_date')} "
        f"verdict={metadata.get('verdict')} "
        f"actor={metadata.get('actor')}"
    )

    if cursor_factory is None:
        try:
            from utils.connections import get_connection  # type: ignore

            def cursor_factory():  # type: ignore[no-redef]
                return get_connection(general_db)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Audit-row write skipped: utils.connections unavailable; "
                "verdict exit code is authoritative."
            )
            return None

    conn = None
    try:
        conn = cursor_factory()
        try:
            conn.autocommit = True
        except Exception:  # noqa: BLE001
            pass
        cursor = conn.cursor()
        try:
            # Capture the SCOPE_IDENTITY() of the inserted row so we
            # can surface it as audit_event_id in JSON output per spec
            # § 3.6 L932. The two statements run on the same connection
            # so SCOPE_IDENTITY() reflects this INSERT.
            cursor.execute(
                f"INSERT INTO [{general_db}].ops.PipelineEventLog "
                f"(BatchId, TableName, SourceName, EventType, EventDetail, "
                f" StartedAt, CompletedAt, Status, ErrorMessage, Metadata) "
                f"VALUES (?, NULL, NULL, ?, ?, ?, SYSUTCDATETIME(), ?, ?, ?); "
                f"SELECT CAST(SCOPE_IDENTITY() AS BIGINT) AS AuditEventId;",
                metadata.get("batch_id"),  # NULL for non-PROCEED_FAILOVER paths
                EVENT_TYPE,
                event_detail,
                metadata.get("started_at_dt"),
                status,
                error_message,
                metadata_json,
            )
            row = cursor.fetchone() if cursor.description is not None else None
            if row is None or row[0] is None:
                return None
            return int(row[0])
        finally:
            try:
                cursor.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write CLI_PROMOTE_TEST_TO_PROD audit row")
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# CYCLE_FAILED_OVER event_tracker row (per spec § 3.6 L850-851 + CLAUDE.md
# CYCLE_* family registration)
# ---------------------------------------------------------------------------


def _write_cycle_failed_over_event(
    metadata: dict,
    *,
    cursor_factory: Callable | None = None,
    general_db: str = "General",
) -> int | None:
    """INSERT a ``CYCLE_FAILED_OVER`` row into PipelineEventLog per CLAUDE.md.

    Per CLAUDE.md CYCLE_* family registration "CYCLE_FAILED_OVER (test
    claimed gate after prod heartbeat stale; written by SP-4 path)" — SP-4
    itself writes a ``FAILOVER_TRIGGERED`` row at L1632-1641, distinct
    from this ``CYCLE_FAILED_OVER`` row written by the tool after a
    successful SP-6 acknowledgment in --apply mode.

    Returns the SCOPE_IDENTITY() so it can surface in the result dict.
    Best-effort: failures are logged but do not affect the verdict exit
    code. The CLI_PROMOTE_TEST_TO_PROD audit row is the canonical
    invocation audit; this event is additive context for downstream
    queries that filter by EventType='CYCLE_FAILED_OVER'.
    """
    metadata_json = json.dumps(metadata, separators=(",", ":"), default=str)
    event_detail = (
        f"cycle={metadata.get('cycle')} "
        f"cycle_date={metadata.get('cycle_date')}"
    )

    if cursor_factory is None:
        try:
            from utils.connections import get_connection  # type: ignore

            def cursor_factory():  # type: ignore[no-redef]
                return get_connection(general_db)
        except Exception:  # noqa: BLE001
            return None

    conn = None
    try:
        conn = cursor_factory()
        try:
            conn.autocommit = True
        except Exception:  # noqa: BLE001
            pass
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"INSERT INTO [{general_db}].ops.PipelineEventLog "
                f"(BatchId, TableName, SourceName, EventType, EventDetail, "
                f" StartedAt, CompletedAt, Status, ErrorMessage, Metadata) "
                f"VALUES (?, NULL, NULL, ?, ?, ?, SYSUTCDATETIME(), ?, NULL, ?); "
                f"SELECT CAST(SCOPE_IDENTITY() AS BIGINT) AS EventId;",
                metadata.get("batch_id"),
                CYCLE_FAILED_OVER_EVENT,
                event_detail,
                metadata.get("started_at_dt"),
                "SUCCESS",
                metadata_json,
            )
            row = cursor.fetchone() if cursor.description is not None else None
            if row is None or row[0] is None:
                return None
            return int(row[0])
        finally:
            try:
                cursor.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write CYCLE_FAILED_OVER event row")
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Stdout rendering
# ---------------------------------------------------------------------------


def _emit_proceed_failover_apply(result: dict) -> None:
    """Spec § 3.6 L898-905 stdout block — apply + PROCEED_FAILOVER."""
    cycle = result.get("cycle")
    cycle_date = result.get("cycle_date")
    parity = result.get("test_parity_status", "skipped")
    parity_mark = (
        "✓"
        if parity in ("pass", "warn")
        else ("(skipped)" if parity == "skipped" else "✗")
    )
    sp6_at = result.get("sp6_acknowledged_at", "")
    batch_id = result.get("batch_id")
    audit_event_id = result.get("audit_event_id")
    print(f"Failover acknowledgment: {cycle} {cycle_date}")
    print(f"  Pre-check: test server parity verified {parity_mark}")
    print(f"  SP-4 verdict: PROCEED_FAILOVER")
    print(f"  SP-6 acknowledged at: {sp6_at}")
    suffix = f" BatchId: {batch_id}" if batch_id is not None else ""
    print(
        f"  Test server now owns this cycle (ExecutingServer='test')."
        f"{suffix}"
    )
    if audit_event_id is not None:
        print(
            f"  PipelineEventLog row: {audit_event_id} "
            f"(EventType='{EVENT_TYPE}')"
        )


def _emit_proceed_failover_dry(result: dict) -> None:
    """Spec § 3.6 L909-913 stdout block — dry-run + PROCEED_FAILOVER."""
    parity = result.get("test_parity_status", "skipped")
    parity_mark = (
        "✓"
        if parity in ("pass", "warn")
        else ("(skipped)" if parity == "skipped" else "✗")
    )
    print("Dry-run: failover acknowledgment would proceed")
    print(f"  Pre-check: test server parity verified {parity_mark}")
    print(f"  SP-4 verdict: PROCEED_FAILOVER")
    print("  Would acknowledge via SP-6. Re-run with --apply to commit.")


def _emit_exit_succeeded(result: dict) -> None:
    """Spec § 3.6 L918-922 stdout block — EXIT_SUCCEEDED."""
    cycle = result.get("cycle")
    cycle_date = result.get("cycle_date")
    print("No failover needed — prod cycle already succeeded.")
    print(
        f"  SP-4 verdict: EXIT_SUCCEEDED "
        f"(prod Status='SUCCEEDED' for {cycle} {cycle_date})"
    )
    print("  Test server exits cleanly. No gate change.")


def _emit_exit_running_healthy(result: dict) -> None:
    """Spec § 3.6 L926-930 stdout block — EXIT_RUNNING_HEALTHY."""
    print(
        "No failover needed — prod cycle is currently running with "
        "healthy heartbeat."
    )
    print(
        "  SP-4 verdict: EXIT_RUNNING_HEALTHY "
        "(prod LastHeartbeatAt within heartbeat tolerance)"
    )
    print(
        "  Test server exits cleanly. Operator should re-check prod "
        "dashboard before next attempt."
    )


def _emit_exit_acknowledged(result: dict) -> None:
    """Stdout block for the B79-proposed EXIT_ACKNOWLEDGED verdict (dry-run)."""
    print("Dry-run preview: SP-4 acknowledgment-only mode (B79 amendment).")
    print(
        "  SP-4 verdict: EXIT_ACKNOWLEDGED "
        "(@AcknowledgmentOnly=1; gate state NOT modified)"
    )
    print(
        "  Operator should re-run with --apply to commit the failover "
        "(or wait for prod recovery)."
    )


def _emit_json(payload: dict) -> None:
    """Emit the canonical JSON payload per spec § 3.6 L932."""
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


# ---------------------------------------------------------------------------
# General DB connection factory (test-friendly resolution)
# ---------------------------------------------------------------------------


def _resolve_default_gate_cursor_factory() -> Callable:
    """Return a callable that opens a connection to the General DB.

    Resolves at CALL TIME so tests patching ``sys.modules['pyodbc']``
    after tool import are honored. Mirrors enforce_retention's pattern.

    Raises :class:`VaultConfigError` (mapped to exit 2 by main()) if
    neither path succeeds.
    """

    def _open():
        try:
            from utils.connections import get_connection  # type: ignore

            return get_connection("General")
        except Exception:  # noqa: BLE001
            pass
        pyodbc_mod = sys.modules.get("pyodbc")
        if pyodbc_mod is None:
            try:
                import pyodbc as pyodbc_mod  # type: ignore  # noqa: F401
            except Exception as exc:  # noqa: BLE001
                raise VaultConfigError(
                    f"pyodbc / utils.connections both unavailable: {exc}"
                ) from exc
        return pyodbc_mod.connect("DRIVER={ODBC Driver 18 for SQL Server};")

    return _open


# ---------------------------------------------------------------------------
# Top-level main() — programmatic entry point (canonical B219 pre-spec)
# ---------------------------------------------------------------------------


def main(
    *,
    actor: str,
    cycle: str,
    justification: str,
    cycle_date: str | None = None,
    apply: bool = False,
    dry_run: bool | None = None,
    skip_parity_check: bool = False,
    json_output: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    no_audit_event: bool = False,
    # ---- Injection hooks (resolve at CALL TIME for test mock alignment) ----
    gate_cursor_factory: Callable | None = None,
    audit_cursor_factory: Callable | None = None,
    parity_verifier: Callable | None = None,
    general_db: str | None = None,
) -> dict:
    """Programmatic entry — invoke SP-4 + (optional) SP-6 per D29 / D33.

    Returns a dict matching the D76 audit-row Metadata shape (see module
    docstring for the canonical schema). Exit-code derivation per D74 +
    spec § 3.6 L934-937:

    * 0: PROCEED_FAILOVER successful OR dry-run preview OR EXIT_SUCCEEDED
    * 1: EXIT_RUNNING_HEALTHY (informational; operator review, not page)
    * 2: ParityFatalError / GateNotAcquirable / VaultConfigError /
      missing args / B88 mutex violation

    Parameters
    ----------
    actor:
        Operator identity (per D75 + D76). REQUIRED.
    cycle:
        REQUIRED. 'AM' or 'PM' per CK_PipelineExecutionGate_CycleType
        (Round 1 L326-327).
    justification:
        REQUIRED. Free-text operator rationale per spec L893 audit-trail
        D75/D76. When ``skip_parity_check=True``, MUST contain rationale
        keywords (validated in ``_validate_args``).
    cycle_date:
        Optional ISO YYYY-MM-DD; defaults to today (UTC). Maps to
        PipelineExecutionGate.CycleDate (Round 1 L306).
    apply:
        When True, SP-4 invoked with ``@AcknowledgmentOnly=0`` and SP-6
        invoked on PROCEED_FAILOVER verdict. When False (default per
        spec § 1.2), SP-4 invoked with ``@AcknowledgmentOnly=1`` (B79
        amendment) — read-only preview.
    dry_run:
        B88 mutex bridge — tests pass ``dry_run`` paralleling ``apply``.
        If True AND ``apply=True`` -> exit 2 (mutex violation per B88).
        If True alone -> override ``apply=False``.
    skip_parity_check:
        DANGEROUS per spec L894. Logs CRITICAL + proceeds past the
        parity precheck. ``justification`` MUST contain rationale
        keywords (enforced at ``_validate_args``).
    no_audit_event:
        When True, skip the CLI-level PipelineEventLog write (pipeline-
        programmatic callers per D75 + D76).
    gate_cursor_factory / audit_cursor_factory / parity_verifier:
        Test-injection hooks. Defaults resolve to live infrastructure.
    general_db:
        Override the canonical General DB name (defaults to
        ``utils.configuration.GENERAL_DB``, fallback ``'General'``).
    """
    started_at_dt = _now_naive_utc_ms()

    # B88 dry-run/apply mutex bridge: tests pass `dry_run` as a kwarg paralleling
    # `apply`. Canonical semantic: --apply makes it real; --dry-run forces preview.
    # If both True -> mutex violation (exit 2). If `dry_run=True` -> override
    # apply=False.
    if dry_run is True and apply is True:
        raise SystemExit(2)
    if dry_run is True:
        apply = False

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif quiet:
        logging.getLogger().setLevel(logging.ERROR)

    # ---- Validate cycle / cycle_date ----
    try:
        cycle = _validate_cycle(cycle)
        parsed_cycle_date = _parse_cycle_date(cycle_date)
    except ValueError as exc:
        # Argv-level validation should have caught this; if main() is
        # called programmatically with bad args, surface as exit 2.
        result: dict[str, Any] = _build_initial_result(
            actor=actor,
            cycle=cycle,
            cycle_date_raw=cycle_date or "",
            justification=justification,
            apply=apply,
            skip_parity_check=skip_parity_check,
            started_at_dt=started_at_dt,
        )
        result["exit_code"] = EXIT_FATAL
        result["error_type"] = "ValueError"
        result["error_message"] = str(exc)
        result["errors"].append(f"ValueError: {exc}")
        result["completed_at"] = _format_iso(_now_naive_utc_ms())
        if not quiet:
            print(f"FATAL: {exc}", file=sys.stderr)
        audit_id = _write_audit_row(
            result,
            status="FAILED",
            error_message=str(exc)[:4000],
            cursor_factory=audit_cursor_factory,
            general_db=general_db or "General",
            skip=no_audit_event,
        )
        result["audit_event_id"] = audit_id
        return result

    # Resolve general_db tag (matches enforce_retention pattern).
    if general_db is None:
        try:
            import utils.configuration as config  # type: ignore

            general_db = getattr(config, "GENERAL_DB", "General")
        except Exception:  # noqa: BLE001
            general_db = "General"

    # ---- Pre-populate result with input echoes for early-exit paths ----
    result = _build_initial_result(
        actor=actor,
        cycle=cycle,
        cycle_date_raw=parsed_cycle_date.isoformat(),
        justification=justification,
        apply=apply,
        skip_parity_check=skip_parity_check,
        started_at_dt=started_at_dt,
    )

    # ---- Stage 1: Parity precheck (per spec § 3.6 L900) ----
    if parity_verifier is None:
        parity_verifier = _resolve_default_parity_verifier()

    try:
        parity_status, _parity_err = _run_parity_precheck(
            parity_verifier,
            skip_parity_check=skip_parity_check,
        )
        result["test_parity_status"] = parity_status
    except ParityFatalError as exc:
        result["exit_code"] = EXIT_FATAL
        result["error_type"] = "ParityFatalError"
        result["error_message"] = str(exc)[:4000]
        result["errors"].append(f"ParityFatalError: {exc}")
        result["test_parity_status"] = "fail"
        logger.error("Parity precheck fatal: %s", exc)
        if not quiet:
            print(
                f"FATAL: test-server parity precheck failed: {exc}",
                file=sys.stderr,
            )
        result["completed_at"] = _format_iso(_now_naive_utc_ms())
        audit_id = _write_audit_row(
            result,
            status="FAILED",
            error_message=str(exc)[:4000],
            cursor_factory=audit_cursor_factory,
            general_db=general_db,
            skip=no_audit_event,
        )
        result["audit_event_id"] = audit_id
        return result

    # ---- Stage 2: Resolve gate connection factory ----
    if gate_cursor_factory is None:
        try:
            gate_cursor_factory = _resolve_default_gate_cursor_factory()
        except VaultConfigError as exc:
            result["exit_code"] = EXIT_FATAL
            result["error_type"] = "VaultConfigError"
            result["error_message"] = str(exc)[:4000]
            result["errors"].append(f"VaultConfigError: {exc}")
            result["completed_at"] = _format_iso(_now_naive_utc_ms())
            if not quiet:
                print(
                    f"FATAL: gate config unavailable: {exc}",
                    file=sys.stderr,
                )
            audit_id = _write_audit_row(
                result,
                status="FAILED",
                error_message=str(exc)[:4000],
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            result["audit_event_id"] = audit_id
            return result

    # ---- Stage 3: Invoke SP-4 + handle verdict tree ----
    conn = None
    try:
        try:
            conn = gate_cursor_factory()
        except VaultConfigError as exc:
            result["exit_code"] = EXIT_FATAL
            result["error_type"] = "VaultConfigError"
            result["error_message"] = str(exc)[:4000]
            result["errors"].append(f"VaultConfigError: {exc}")
            logger.error("VaultConfigError during connection setup: %s", exc)
            if not quiet:
                print(f"FATAL: vault config error: {exc}", file=sys.stderr)
            result["completed_at"] = _format_iso(_now_naive_utc_ms())
            audit_id = _write_audit_row(
                result,
                status="FAILED",
                error_message=str(exc)[:4000],
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            result["audit_event_id"] = audit_id
            return result
        except Exception as exc:  # noqa: BLE001
            # Generic connection failure -> exit 2 (fatal — connection is
            # a pre-condition for any SP invocation; not retryable in the
            # operational sense — operator must resolve infrastructure).
            result["exit_code"] = EXIT_FATAL
            result["error_type"] = type(exc).__name__
            result["error_message"] = str(exc)[:4000]
            result["errors"].append(f"{type(exc).__name__}: {exc}")
            logger.error("Connection to General DB failed: %s", exc)
            if not quiet:
                print(
                    f"FATAL: connection failed: {exc}",
                    file=sys.stderr,
                )
            result["completed_at"] = _format_iso(_now_naive_utc_ms())
            audit_id = _write_audit_row(
                result,
                status="FAILED",
                error_message=traceback.format_exc()[:4000],
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            result["audit_event_id"] = audit_id
            return result

        # autocommit=True is the canonical pattern per W-8 RCSI analysis +
        # enforce_retention pattern.
        try:
            conn.autocommit = True
        except Exception:  # noqa: BLE001
            pass

        # ---- Invoke SP-4 ----
        # In dry-run mode: @AcknowledgmentOnly=1 (B79 amendment — read-only
        # preview). In apply mode: @AcknowledgmentOnly=0 (full SP-4 flow
        # with MERGE + FAILOVER_TRIGGERED audit row inside SP-4 body).
        acknowledgment_only = not apply
        try:
            action, gate_id, batch_id, sp4_err = _invoke_sp4(
                conn,
                cycle=cycle,
                cycle_date=parsed_cycle_date,
                acknowledgment_only=acknowledgment_only,
                general_db=general_db,
            )
        except GateNotAcquirable as exc:
            # SP-4's internal sp_getapplock raised — exit 2 per spec L937.
            result["exit_code"] = EXIT_FATAL
            result["error_type"] = "GateNotAcquirable"
            result["error_message"] = str(exc)[:4000]
            result["errors"].append(f"GateNotAcquirable: {exc}")
            logger.error("GateNotAcquirable: %s", exc)
            if not quiet:
                print(
                    f"FATAL: gate lock contention (another pipeline holds "
                    f"the cycle lock): {exc}",
                    file=sys.stderr,
                )
            result["completed_at"] = _format_iso(_now_naive_utc_ms())
            audit_id = _write_audit_row(
                result,
                status="FAILED",
                error_message=str(exc)[:4000],
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            result["audit_event_id"] = audit_id
            return result

        # ---- Handle SP-4 verdict ----
        if action is None and sp4_err is not None:
            # In --dry-run mode, a parameter-count mismatch is the B79
            # signal — SP-4 hasn't been amended to accept @AcknowledgmentOnly
            # yet. Surface as EXIT_ACKNOWLEDGED placeholder per spec L862.
            if acknowledgment_only and (
                "Procedure" in sp4_err
                or "parameter" in sp4_err.lower()
                or "argument" in sp4_err.lower()
            ):
                logger.critical(
                    "B79 dependency: SP-4 does not yet accept "
                    "@AcknowledgmentOnly parameter. Returning placeholder "
                    "verdict EXIT_ACKNOWLEDGED. Apply the SP-4 amendment "
                    "(B79 in BACKLOG) before relying on dry-run for "
                    "operational decisions. Underlying SP-4 error: %s",
                    sp4_err,
                )
                result["verdict"] = ACTION_EXIT_ACKNOWLEDGED
                result["exit_code"] = EXIT_SUCCESS
                result["b79_dependency"] = True
                result["error_message"] = (
                    "B79 not yet executed: SP-4 missing @AcknowledgmentOnly. "
                    "Verdict is a placeholder."
                )
            else:
                # Real SP-4 failure (not parameter mismatch) — exit 2.
                result["exit_code"] = EXIT_FATAL
                result["error_type"] = "Sp4InvocationError"
                result["error_message"] = sp4_err[:4000]
                result["errors"].append(f"SP-4 invocation error: {sp4_err}")
                logger.error("SP-4 invocation failed: %s", sp4_err)
                if not quiet:
                    print(
                        f"FATAL: SP-4 invocation failed: {sp4_err}",
                        file=sys.stderr,
                    )
        else:
            result["verdict"] = action
            result["gate_id"] = gate_id
            # Per spec § 3.6 L932: batch_id populated only on PROCEED_FAILOVER
            # (the new BatchId test server acquired); null for EXIT_* verdicts
            # (no gate state change happened).
            result["batch_id"] = batch_id if action == ACTION_PROCEED_FAILOVER else None

            if action == ACTION_EXIT_SUCCEEDED:
                # Prod cycle already done — clean informational outcome.
                # Exit 0 per spec § 3.6 L935 + L866.
                result["exit_code"] = EXIT_SUCCESS

            elif action == ACTION_EXIT_RUNNING_HEALTHY:
                # Prod is healthy + running — informational; operator
                # should re-check the dashboard. Exit 1 per spec L867
                # + L936 (NOT page-able; NOT an emergency).
                result["exit_code"] = EXIT_WARNING

            elif action == ACTION_PROCEED_FAILOVER:
                # SP-4 has already flipped ExecutingServer='test' +
                # claimed a new BatchId via the MERGE at L1605-1623.
                # In --apply mode, invoke SP-6 to close the cancellation
                # chain. In dry-run mode (acknowledgment_only=1), this
                # branch only fires if B79 is NOT yet implemented (the
                # SP ignored the parameter and ran the full body) — log
                # warning + still record verdict but skip SP-6.
                if apply:
                    try:
                        if gate_id is None:
                            raise RuntimeError(
                                "SP-4 returned PROCEED_FAILOVER but @GateId "
                                "OUTPUT was NULL — SP-4 contract violation"
                            )
                        sp6_at_dt = _now_naive_utc_ms()
                        _invoke_sp6(
                            conn,
                            gate_id=gate_id,
                            general_db=general_db,
                        )
                        result["sp6_acknowledged_at"] = _format_iso(sp6_at_dt)
                        result["sp6_invoked"] = True

                        # Write the CYCLE_FAILED_OVER row per CLAUDE.md
                        # CYCLE_* family. Best-effort — failure logged but
                        # does not change verdict / exit code.
                        cycle_event_id = _write_cycle_failed_over_event(
                            result,
                            cursor_factory=audit_cursor_factory,
                            general_db=general_db,
                        )
                        result["cycle_failed_over_event_id"] = cycle_event_id
                        result["exit_code"] = EXIT_SUCCESS
                    except Exception as exc:  # noqa: BLE001
                        # SP-6 failure after SP-4 already flipped the gate
                        # — gate is in an intermediate state. SP-6 is
                        # idempotent per L1731-1733 so a re-run is safe.
                        # Surface as exit 2 (fatal — operator must
                        # investigate and likely re-run).
                        result["exit_code"] = EXIT_FATAL
                        result["error_type"] = type(exc).__name__
                        result["error_message"] = str(exc)[:4000]
                        result["errors"].append(
                            f"SP-6 ack failed after SP-4 PROCEED_FAILOVER: {exc}"
                        )
                        logger.exception(
                            "SP-6 acknowledgment failed after SP-4 PROCEED_FAILOVER"
                        )
                        if not quiet:
                            print(
                                f"FATAL: SP-6 ack failed after SP-4 "
                                f"PROCEED_FAILOVER (gate is in intermediate "
                                f"state; re-run is safe — SP-6 idempotent): "
                                f"{exc}",
                                file=sys.stderr,
                            )
                else:
                    # Dry-run + PROCEED_FAILOVER (means B79 isn't yet
                    # honored by SP-4 — SP-4 ignored @AcknowledgmentOnly
                    # and ran the full body). Log warning; report what
                    # WOULD happen + exit 0.
                    logger.warning(
                        "Dry-run yielded PROCEED_FAILOVER but @AcknowledgmentOnly "
                        "was sent as 1 — SP-4 may not yet honor B79. "
                        "Gate state has been mutated by SP-4 — operator "
                        "should verify via tools/inspect_table_config.py "
                        "or by querying General.ops.PipelineExecutionGate "
                        "directly."
                    )
                    result["exit_code"] = EXIT_SUCCESS
                    result["b79_partial"] = True

            elif action == ACTION_EXIT_ACKNOWLEDGED:
                # B79 honored — SP-4 returned the dry-run placeholder.
                # Exit 0.
                result["exit_code"] = EXIT_SUCCESS

            else:
                # Unknown verdict — Pitfall #9.c invented-value drift
                # would surface here. SP-4 contract is strict (per L1546).
                # Treat as fatal.
                result["exit_code"] = EXIT_FATAL
                result["error_type"] = "UnknownVerdict"
                result["error_message"] = (
                    f"SP-4 returned unknown @Action={action!r} — expected one "
                    f"of {ACTION_EXIT_SUCCEEDED!r} / {ACTION_EXIT_RUNNING_HEALTHY!r} "
                    f"/ {ACTION_PROCEED_FAILOVER!r} / {ACTION_EXIT_ACKNOWLEDGED!r}"
                )
                result["errors"].append(result["error_message"])
                logger.error(result["error_message"])
                if not quiet:
                    print(
                        f"FATAL: {result['error_message']}",
                        file=sys.stderr,
                    )

    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    result["completed_at"] = _format_iso(_now_naive_utc_ms())

    # ---- Invocation-level audit row (D76 — ONE per invocation) ----
    status = (
        "SUCCESS"
        if result["exit_code"] in (EXIT_SUCCESS, EXIT_WARNING)
        else "FAILED"
    )
    audit_event_id = _write_audit_row(
        result,
        status=status,
        error_message=result.get("error_message"),
        cursor_factory=audit_cursor_factory,
        general_db=general_db,
        skip=no_audit_event,
    )
    result["audit_event_id"] = audit_event_id

    # ---- Render stdout AFTER audit-row write so audit_event_id surfaces ----
    if json_output:
        # Spec § 3.6 L932 canonical shape — emit the canonical keys.
        json_payload = {
            "cycle": result["cycle"],
            "cycle_date": result["cycle_date"],
            "verdict": result.get("verdict"),
            "test_parity_status": result.get("test_parity_status", "skipped"),
            "applied": result["applied"],
            "batch_id": result.get("batch_id"),
            "audit_event_id": result["audit_event_id"],
        }
        _emit_json(json_payload)
    elif not quiet:
        verdict = result.get("verdict")
        if verdict == ACTION_PROCEED_FAILOVER and apply:
            _emit_proceed_failover_apply(result)
        elif verdict == ACTION_PROCEED_FAILOVER and not apply:
            _emit_proceed_failover_dry(result)
        elif verdict == ACTION_EXIT_SUCCEEDED:
            _emit_exit_succeeded(result)
        elif verdict == ACTION_EXIT_RUNNING_HEALTHY:
            _emit_exit_running_healthy(result)
        elif verdict == ACTION_EXIT_ACKNOWLEDGED:
            _emit_exit_acknowledged(result)
        # Fatal paths already printed to stderr earlier.

    return result


# ---------------------------------------------------------------------------
# Result-dict initializer (shared by main + early-exit paths)
# ---------------------------------------------------------------------------


def _build_initial_result(
    *,
    actor: str,
    cycle: str,
    cycle_date_raw: str,
    justification: str | None,
    apply: bool,
    skip_parity_check: bool,
    started_at_dt: datetime,
) -> dict[str, Any]:
    """Construct the result dict per the D76 audit-row metadata schema."""
    return {
        "event_kind": "failover_promotion",
        "actor": actor,
        "justification": justification,
        "cycle": cycle,
        "cycle_date": cycle_date_raw,
        "verdict": None,
        "test_parity_status": "skipped",
        "applied": apply,
        "dry_run": not apply,
        "skip_parity_check": skip_parity_check,
        "batch_id": None,
        "gate_id": None,
        "exit_code": EXIT_SUCCESS,
        "started_at": _format_iso(started_at_dt),
        "started_at_dt": started_at_dt,
        "completed_at": None,
        "audit_event_id": None,
        "sp6_invoked": False,
        "sp6_acknowledged_at": None,
        "cycle_failed_over_event_id": None,
        "b79_dependency": False,
        "b79_partial": False,
        "errors": [],
    }


# ---------------------------------------------------------------------------
# CLI argv entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    """Alias for :func:`_build_parser` — Tier 0 scaffold contract."""
    return _build_parser()


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser per spec § 3.6 + § 1.4 canonical args.

    Per Pitfall #9.b invented-parameter rule (HANDOFF §8): this parser
    does NOT accept any args outside the canonical set declared at
    spec § 3.6 L887-895 + § 1.4. Tier 0 assertion verifies this.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Failover acknowledgment per D29 revised + D33. Wraps SP-4 "
            "PipelineExecutionGate_AcquireTest + (on PROCEED_FAILOVER apply) "
            "SP-6 PipelineExecutionGate_AcknowledgeCancellation. Emits one "
            "CLI_PROMOTE_TEST_TO_PROD audit row per invocation."
        ),
    )

    # ---- Tool-specific args (per spec § 3.6 L887-895) ----
    parser.add_argument(
        "--cycle",
        required=True,
        choices=("AM", "PM"),
        help=(
            "REQUIRED. One of 'AM' / 'PM' per "
            "CK_PipelineExecutionGate_CycleType (Round 1 L326-327)."
        ),
    )
    parser.add_argument(
        "--cycle-date",
        default=None,
        help=(
            "ISO YYYY-MM-DD cycle date (defaults to today UTC). "
            "Maps to PipelineExecutionGate.CycleDate."
        ),
    )
    parser.add_argument(
        "--justification",
        required=True,
        help=(
            "REQUIRED. Free-text audit reason; surfaces in "
            "PipelineEventLog.Metadata.justification."
        ),
    )
    parser.add_argument(
        "--skip-parity-check",
        action="store_true",
        help=(
            "DANGEROUS — override the test-server parity precheck. "
            "Operator MUST justify in --justification with rationale "
            "keywords. Logged at CRITICAL."
        ),
    )

    # ---- D75 canonical args (per spec § 1.4) ----
    # --apply / --dry-run are mutually exclusive per B88.
    apply_group = parser.add_mutually_exclusive_group()
    apply_group.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Apply: invoke SP-4 with @AcknowledgmentOnly=0 (live failover) "
            "+ SP-6 on PROCEED_FAILOVER verdict. Default is dry-run."
        ),
    )
    apply_group.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Explicit dry-run opt-in (redundant — this is the default; "
            "useful for scripting clarity). SP-4 invoked with "
            "@AcknowledgmentOnly=1 (B79 amendment)."
        ),
    )

    parser.add_argument(
        "--actor",
        default=None,
        help=(
            "Operator identity (per D75 + D76). One of operator / automic / "
            "pipeline / pipeline-lead. Auto-detected via TTY / AUTOMIC_RUN_ID "
            "env when omitted."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help=(
            "Emit canonical JSON output per spec § 3.6 L932 instead of "
            "human summary."
        ),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress stdout summary (errors still emitted to stderr).",
    )
    return parser


# Rationale keywords expected in --justification when --skip-parity-check is
# set, per spec § 3.6 L943 (Tier 1 keyword check). Operator must include
# at least ONE to demonstrate they read the override warning.
_SKIP_PARITY_RATIONALE_KEYWORDS = (
    "parity_check_skip_override",
    "known-good drift",
    "rb-7",
    "rb-9",
    "drill",
    "operator override",
    "emergency",
)


def _validate_args(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> None:
    """Enforce --skip-parity-check rationale + --justification non-empty.

    Per spec § 3.6 L943 — Tier 1 keyword check. ``--skip-parity-check``
    requires ``--justification`` to contain at least one of the canonical
    rationale keywords. argparse's ``required=True`` already enforces
    non-empty justification + cycle.
    """
    # argparse handles required=True for --cycle + --justification + the
    # mutually-exclusive group for --apply/--dry-run; only the
    # --skip-parity-check rationale check is left to implement here.
    if args.skip_parity_check:
        justification_lc = (args.justification or "").lower()
        if not any(
            kw.lower() in justification_lc
            for kw in _SKIP_PARITY_RATIONALE_KEYWORDS
        ):
            parser.error(
                "--skip-parity-check requires --justification to contain "
                "a rationale keyword (one of: "
                + ", ".join(_SKIP_PARITY_RATIONALE_KEYWORDS)
                + "). The override bypasses a safety precondition; the "
                "justification must demonstrate operator intent."
            )


def cli_main() -> int:
    """Argv entry point — argparse + main() + return exit code per D74.

    Exit codes (always one of 0 / 1 / 2 per D74 + spec § 3.6 L934-937):
        - 0: PROCEED_FAILOVER successful (or dry-run preview) OR EXIT_SUCCEEDED
        - 1: EXIT_RUNNING_HEALTHY (informational; not page-able)
        - 2: ParityFatalError / GateNotAcquirable / VaultConfigError /
             missing args / B88 mutex violation
    """
    parser = _build_parser()
    args = parser.parse_args()
    _validate_args(args, parser)

    actor = args.actor or _detect_actor()

    try:
        result = main(
            actor=actor,
            cycle=args.cycle,
            justification=args.justification,
            cycle_date=args.cycle_date,
            apply=args.apply,
            skip_parity_check=args.skip_parity_check,
            json_output=args.json_output,
            verbose=args.verbose,
            quiet=args.quiet,
        )
    except SystemExit as exc:
        # B88 mutex violation (dry_run + apply both True) -> code 2.
        code = exc.code if isinstance(exc.code, int) else EXIT_FATAL
        if code not in (EXIT_SUCCESS, EXIT_WARNING, EXIT_FATAL):
            code = EXIT_FATAL
        return code
    except KeyboardInterrupt:
        logger.warning("Interrupted by operator")
        return EXIT_WARNING
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        print(
            f"FATAL: promote_test_to_prod unexpected exception:\n{tb[:1000]}",
            file=sys.stderr,
        )
        return EXIT_FATAL

    exit_code = int(result.get("exit_code", EXIT_FATAL))
    # Defensive clamp — every exit path MUST be 0 / 1 / 2 per D74
    # contract (Pitfall #9.m self-application — the docstring claims
    # "exit 0/1/2 per D74", so verify the claim).
    if exit_code not in (EXIT_SUCCESS, EXIT_WARNING, EXIT_FATAL):
        logger.error(
            "Non-canonical exit_code %r returned from main(); "
            "clamping to EXIT_FATAL",
            exit_code,
        )
        exit_code = EXIT_FATAL
    return exit_code


if __name__ == "__main__":
    sys.exit(cli_main())
