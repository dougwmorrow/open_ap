"""Tier 1 tests for B-337 / D119: startup_recovery_sweep legacy pre-D2 EventType
forensic-preservation discipline.

Pins:
1. `startup_recovery_sweep` MUST count + log legacy pre-D2 rows
   (EventType IN ('SCD2_PROMOTION','CDC_PROMOTION')) separately and emit
   a WARNING enumerating them — but MUST NOT auto-sweep them.
2. The stale-count SELECT that drives the sweep decision MUST exclude
   legacy pre-D2 EventTypes.
3. The UPDATE statement that performs the sweep MUST also exclude legacy
   pre-D2 EventTypes (so even if a malformed stale-count slipped through
   the gating SELECT, the actual sweep would still preserve forensics).
4. The docstring for `ledger_step` MUST mention both 'SCD2_PROMOTION'
   (legacy per D119) and 'SCD2_PROMOTION_D2' (post-cutover canonical).

Per CLAUDE.md hard rule 11 (post-edit verification): authored AT the
R1.8/B-337 closure commit so 🟢 status is reachable.
"""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _stub_modules_for_idempotency_ledger():
    """idempotency_ledger imports utils.connections + logging — fully isolated."""

    stubs = {
        "utils.connections": types.ModuleType("utils.connections"),
        "utils.errors": types.ModuleType("utils.errors"),
    }

    # utils.connections needs `cursor_for` context-manager surface.
    class _CursorForStub:
        last_instance = None

        def __init__(self, _db_name):
            self.cursor = MagicMock()
            type(self).last_instance = self

        def __enter__(self):
            return self.cursor

        def __exit__(self, exc_type, exc, tb):
            return False

    stubs["utils.connections"].cursor_for = _CursorForStub

    # utils.errors needs PipelineFatalError + LedgerStepFailed + LedgerStuck +
    # LedgerConfigError for the ledger module import.
    class _PipelineFatalError(Exception):
        pass

    class _LedgerStepFailed(_PipelineFatalError):
        pass

    class _LedgerStuck(_PipelineFatalError):
        pass

    class _LedgerConfigError(_PipelineFatalError):
        pass

    stubs["utils.errors"].PipelineFatalError = _PipelineFatalError
    stubs["utils.errors"].LedgerStepFailed = _LedgerStepFailed
    stubs["utils.errors"].LedgerStuck = _LedgerStuck
    stubs["utils.errors"].LedgerConfigError = _LedgerConfigError

    saved = {}
    for k, v in stubs.items():
        saved[k] = sys.modules.get(k)
        sys.modules[k] = v
    # Force re-import of utils.idempotency_ledger to pick up our stubs.
    sys.modules.pop("utils.idempotency_ledger", None)

    yield _CursorForStub

    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v
    sys.modules.pop("utils.idempotency_ledger", None)


# ---------------------------------------------------------------------------
# Class A: source-text invariants (these don't require import; they're pin-tests
# against the SQL strings themselves so the discipline survives refactors).
# ---------------------------------------------------------------------------


def _read_source() -> str:
    return (REPO_ROOT / "utils" / "idempotency_ledger.py").read_text(encoding="utf-8")


def test_select_stalecount_excludes_legacy_pre_d2_eventtypes():
    """Pin: the gating stale-count SELECT inside startup_recovery_sweep MUST
    include `AND EventType NOT IN ('SCD2_PROMOTION', 'CDC_PROMOTION')`.
    """

    src = _read_source()
    # Find the second SELECT COUNT(*) (the one with `IX_IdempotencyLedger_Stuck`
    # comment above it). Both pre- and post-fix have a SELECT here; the post-fix
    # version adds the legacy-exclusion clause.
    pattern = re.compile(
        r"SELECT COUNT\(\*\)\s*FROM General\.ops\.IdempotencyLedger\s+"
        r"WHERE Status = 'IN_PROGRESS'\s+"
        r"AND StartedAt < DATEADD\(MINUTE, -\?, SYSUTCDATETIME\(\)\)\s+"
        r"AND EventType NOT IN \('SCD2_PROMOTION', 'CDC_PROMOTION'\)",
        re.MULTILINE,
    )
    matches = pattern.findall(src)
    assert len(matches) == 1, (
        f"Expected exactly 1 stale-count SELECT with legacy-exclusion; "
        f"found {len(matches)}"
    )


def test_update_block_excludes_legacy_pre_d2_eventtypes():
    """Pin: the UPDATE statement inside startup_recovery_sweep MUST also include
    `AND EventType NOT IN ('SCD2_PROMOTION', 'CDC_PROMOTION')` — the defense-in-
    depth invariant from D119 + B-337.
    """

    src = _read_source()
    pattern = re.compile(
        r"UPDATE General\.ops\.IdempotencyLedger\s+"
        r"SET Status = 'FAILED',\s+"
        r"CompletedAt = SYSUTCDATETIME\(\),\s+"
        r"ErrorMessage = 'Stale on startup recovery sweep',\s+"
        r"RecoveryAction = 'STARTUP_SWEEP_FAILED'\s+"
        r"WHERE Status = 'IN_PROGRESS'\s+"
        r"AND StartedAt < DATEADD\(MINUTE, -\?, SYSUTCDATETIME\(\)\)\s+"
        r"AND EventType NOT IN \('SCD2_PROMOTION', 'CDC_PROMOTION'\)",
        re.MULTILINE,
    )
    matches = pattern.findall(src)
    assert len(matches) == 1, (
        f"Expected exactly 1 UPDATE block with legacy-exclusion; "
        f"found {len(matches)}. D119 defense-in-depth invariant violated."
    )


def test_forensic_warning_select_present():
    """Pin: a separate SELECT COUNT(*) that COUNTS legacy pre-D2 rows must exist
    BEFORE the gating SELECT — this is the forensic-evidence enumeration that
    drives the WARNING log."""

    src = _read_source()
    pattern = re.compile(
        r"SELECT COUNT\(\*\)\s*FROM General\.ops\.IdempotencyLedger\s+"
        r"WHERE Status = 'IN_PROGRESS'\s+"
        r"AND StartedAt < DATEADD\(MINUTE, -\?, SYSUTCDATETIME\(\)\)\s+"
        r"AND EventType IN \('SCD2_PROMOTION', 'CDC_PROMOTION'\)",
        re.MULTILINE,
    )
    matches = pattern.findall(src)
    assert len(matches) == 1, (
        f"Expected exactly 1 forensic-warning SELECT (with EventType IN ...); "
        f"found {len(matches)}. D119 forensic-preservation invariant violated."
    )


def test_forensic_warning_includes_b337_d119_markers():
    """Pin: the WARNING log message MUST cite B-337 + D119 so future operators
    + cross-cohort reviewers can grep for the canonical references."""

    src = _read_source()
    assert "B-337/D119" in src, (
        "B-337/D119 marker missing from startup_recovery_sweep WARNING; "
        "operator-investigation citation per D119 body required."
    )
    assert "forensic" in src.lower(), (
        "forensic-preservation rationale missing from B-337/D119 WARNING; "
        "design-reviewer Class A-2 finding requires explicit rationale."
    )


def test_docstring_mentions_d119_cutover():
    """Pin: the `ledger_step` docstring MUST list both 'SCD2_PROMOTION' (legacy)
    and 'SCD2_PROMOTION_D2' (post-cutover canonical) per D119 EventType policy."""

    src = _read_source()
    assert "'SCD2_PROMOTION_D2'" in src, (
        "SCD2_PROMOTION_D2 canonical EventType missing from ledger_step docstring "
        "(D119 cutover EventType naming)."
    )
    assert "D119" in src, "D119 reference missing from docstring."


# ---------------------------------------------------------------------------
# Class B: behavioral invariants — exercise startup_recovery_sweep with a
# mocked cursor_for and verify the actual SQL it issues + the rowcount it
# returns.
# ---------------------------------------------------------------------------


def test_sweep_skips_legacy_rows_when_only_legacy_stale(_stub_modules_for_idempotency_ledger):
    """Behavior: if the only stale IN_PROGRESS rows are legacy pre-D2 rows
    (SCD2_PROMOTION + CDC_PROMOTION), the sweep MUST:
    - emit a forensic WARNING with the legacy count
    - find 0 non-legacy stale rows (gating SELECT)
    - therefore NOT execute the UPDATE
    - return 0.
    """

    cursor_for_cls = _stub_modules_for_idempotency_ledger
    from utils.idempotency_ledger import startup_recovery_sweep  # noqa: E402

    # Mock cur.execute + cur.fetchone:
    # - 1st execute: forensic SELECT → fetchone returns (3,)  [3 legacy rows]
    # - 2nd execute: gating SELECT → fetchone returns (0,)    [0 non-legacy stale]
    # - No 3rd execute should happen (skip-sweep branch).
    fetchone_results = [(3,), (0,)]
    instance_holder: list = []

    class _Cur:
        def __init__(self, _):
            self.execute = MagicMock()
            self.rowcount = 0
            self._fetchone_calls = 0
            instance_holder.append(self)

        def fetchone(self):
            result = fetchone_results[self._fetchone_calls]
            self._fetchone_calls += 1
            return result

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    # Monkey-patch cursor_for at the point of use in the ledger module.
    import utils.idempotency_ledger as il_mod
    il_mod.cursor_for = _Cur

    result = startup_recovery_sweep(stale_threshold_minutes=15)
    assert result == 0, "Expected 0 rows swept when only legacy stale rows present"

    # Only the first `with cursor_for(...)` block runs (forensic+gating SELECTs);
    # the second block (UPDATE) is skipped because stale_count==0 returns early.
    assert len(instance_holder) == 1, (
        f"Expected 1 cursor block (sweep short-circuited at stale_count==0); "
        f"got {len(instance_holder)} blocks"
    )
    cur = instance_holder[0]
    assert cur.execute.call_count == 2, (
        f"Expected 2 executes (forensic+gating SELECTs only; UPDATE skipped); "
        f"got {cur.execute.call_count}"
    )


def test_sweep_processes_non_legacy_when_present(_stub_modules_for_idempotency_ledger):
    """Behavior: if there are non-legacy stale IN_PROGRESS rows (e.g. EXTRACT,
    BCP_LOAD, SCD2_PROMOTION_D2), the sweep MUST execute the UPDATE."""

    fetchone_results = [(0,), (5,)]  # 0 legacy, 5 non-legacy stale
    instance_holder: list = []

    class _Cur:
        def __init__(self, _):
            self.execute = MagicMock()
            self.rowcount = 5
            self._fetchone_calls = 0
            instance_holder.append(self)

        def fetchone(self):
            result = fetchone_results[self._fetchone_calls]
            self._fetchone_calls += 1
            return result

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    # Import the ledger first so its `cursor_for` symbol is bound, then patch.
    import utils.idempotency_ledger as il_mod  # noqa: E402
    il_mod.cursor_for = _Cur

    from utils.idempotency_ledger import startup_recovery_sweep  # noqa: E402

    result = startup_recovery_sweep(stale_threshold_minutes=15)
    assert result == 5

    # Two `with cursor_for(...)` blocks: first does forensic+gating SELECTs,
    # second does the UPDATE. Each block gets a fresh _Cur instance.
    assert len(instance_holder) == 2, (
        f"Expected 2 cursor blocks (SELECT block + UPDATE block); "
        f"got {len(instance_holder)} blocks"
    )

    select_cur, update_cur = instance_holder[0], instance_holder[1]
    assert select_cur.execute.call_count == 2, (
        f"Expected 2 SELECT executes in first block; got "
        f"{select_cur.execute.call_count}"
    )
    assert update_cur.execute.call_count == 1, (
        f"Expected 1 UPDATE execute in second block; got "
        f"{update_cur.execute.call_count}"
    )

    update_sql = update_cur.execute.call_args_list[0].args[0]
    assert "UPDATE General.ops.IdempotencyLedger" in update_sql
    assert "EventType NOT IN" in update_sql, (
        "UPDATE SQL missing EventType NOT IN (...) defense-in-depth clause"
    )
    assert "'SCD2_PROMOTION'" in update_sql and "'CDC_PROMOTION'" in update_sql
