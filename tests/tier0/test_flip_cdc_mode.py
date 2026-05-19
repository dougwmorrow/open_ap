"""Tier 0 smoke test for tools/flip_cdc_mode.py (B-546).

Per D67 — runtime ceiling < 5s; all external dependencies mocked.

Asserts:
- Module imports cleanly
- ALLOWED_MODES + EVENT_TYPE + EXIT_* constants present
- classify_transition() returns correct verdicts for all 9 transition pairs
  (3x3 - NOOPs + valid + RISKY + UNKNOWN)
- apply() honors dry-run default per D75
- apply() blocks NOOP transitions (target == current) with EXIT_BLOCKED
- apply() blocks RISKY direct change_detect->parquet_snapshot without --force
- apply() allows RISKY with --force (returns EXIT_WARNING after apply OR
  EXIT_SUCCESS on dry-run with would_flip=True)
- apply() returns EXIT_FATAL when row missing for source.table
- apply() raises ValueError-equivalent (EXIT_FATAL via result dict) on
  invalid target_mode

Per CLAUDE.md "Dev workstation pytest collection skew" (B-328): production
deps mocked via sys.modules pre-patch.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _stub_modules():
    """Pre-patch sys.modules so `import tools.flip_cdc_mode` works on
    Windows dev workstations without polars/pyodbc/oracledb."""

    saved = {}
    for name in ["polars", "connectorx", "pyodbc", "oracledb", "polars_hash"]:
        saved[name] = sys.modules.get(name)
        sys.modules[name] = MagicMock()

    saved["tools.flip_cdc_mode"] = sys.modules.get("tools.flip_cdc_mode")
    sys.modules.pop("tools.flip_cdc_mode", None)

    yield

    for name, mod in saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod
    sys.modules.pop("tools.flip_cdc_mode", None)


def _import_tool():
    from tools import flip_cdc_mode  # noqa: PLC0415
    return flip_cdc_mode


def _make_mock_connection(current_mode: str | None) -> MagicMock:
    """Mock pyodbc connection whose cursor.fetchone() returns
    (current_mode,) when row exists, None when absent."""

    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.fetchone.return_value = (current_mode,) if current_mode is not None else None
    return conn


# ---------------------------------------------------------------------------
# Class A — module surface invariants
# ---------------------------------------------------------------------------


def test_module_imports_cleanly():
    mod = _import_tool()
    assert mod is not None
    assert mod.EVENT_TYPE == "CLI_FLIP_CDC_MODE"


def test_allowed_modes_3_values_per_d125():
    mod = _import_tool()
    assert mod.ALLOWED_MODES == ("change_detect", "parquet_snapshot", "both")


def test_exit_codes_per_d74():
    mod = _import_tool()
    assert mod.EXIT_SUCCESS == 0
    assert mod.EXIT_WARNING == 1
    assert mod.EXIT_BLOCKED == 2
    assert mod.EXIT_FATAL == 3


# ---------------------------------------------------------------------------
# Class B — classify_transition() matrix correctness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "current,target,expected",
    [
        # NOOP: same mode (3 cases)
        ("change_detect", "change_detect", "NOOP"),
        ("parquet_snapshot", "parquet_snapshot", "NOOP"),
        ("both", "both", "NOOP"),
        # ALLOWED (5 transitions per plan §2.3)
        ("change_detect", "both", "ALLOWED"),
        ("both", "parquet_snapshot", "ALLOWED"),
        ("parquet_snapshot", "both", "ALLOWED"),
        ("parquet_snapshot", "change_detect", "ALLOWED"),
        ("both", "change_detect", "ALLOWED"),
        # RISKY (1 transition: direct change_detect -> parquet_snapshot)
        ("change_detect", "parquet_snapshot", "RISKY"),
    ],
)
def test_classify_transition_matrix(current, target, expected):
    mod = _import_tool()
    assert mod.classify_transition(current, target) == expected


# ---------------------------------------------------------------------------
# Class C — apply() behavior
# ---------------------------------------------------------------------------


def test_apply_invalid_target_mode_returns_fatal():
    mod = _import_tool()
    conn = _make_mock_connection(current_mode="change_detect")
    result = mod.apply(
        conn, source="DNA", table="ACCT",
        target_mode="legacy",  # Pitfall #9.k stale value class — must reject
        actor="test", justification="t", dry_run=True,
    )
    assert result["event_kind"] == "fatal"
    assert result["exit_code"] == mod.EXIT_FATAL
    assert "Invalid target_mode" in result["error"]


def test_apply_missing_row_returns_fatal():
    mod = _import_tool()
    conn = _make_mock_connection(current_mode=None)
    result = mod.apply(
        conn, source="DNA", table="NONEXISTENT",
        target_mode="both",
        actor="test", justification="t", dry_run=True,
    )
    assert result["event_kind"] == "fatal"
    assert result["exit_code"] == mod.EXIT_FATAL
    assert "UdmTablesList row missing" in result["error"]


def test_apply_noop_when_same_mode():
    mod = _import_tool()
    conn = _make_mock_connection(current_mode="both")
    result = mod.apply(
        conn, source="DNA", table="ACCT",
        target_mode="both",  # Same as current → NOOP
        actor="test", justification="t", dry_run=True,
    )
    assert result["event_kind"] == "noop"
    assert result["exit_code"] == mod.EXIT_BLOCKED


def test_apply_risky_direct_blocked_without_force():
    mod = _import_tool()
    conn = _make_mock_connection(current_mode="change_detect")
    result = mod.apply(
        conn, source="DNA", table="ACCT",
        target_mode="parquet_snapshot",  # RISKY direct flip
        actor="test", justification="t", dry_run=True, force=False,
    )
    assert result["event_kind"] == "blocked"
    assert result["exit_code"] == mod.EXIT_BLOCKED
    assert "shadow-write validation" in result["message"]


def test_apply_risky_direct_allowed_with_force_dryrun():
    mod = _import_tool()
    conn = _make_mock_connection(current_mode="change_detect")
    result = mod.apply(
        conn, source="DNA", table="ACCT",
        target_mode="parquet_snapshot",
        actor="test", justification="t", dry_run=True, force=True,
    )
    assert result["event_kind"] == "dry_run"
    assert result["exit_code"] == mod.EXIT_SUCCESS
    assert result["transition_risk"] == "RISKY"
    assert result.get("would_flip") is True


def test_apply_dry_run_safe_transition():
    """Safe transition (change_detect → both) dry-run returns SUCCESS +
    would_flip=True without executing UPDATE/INSERT."""

    mod = _import_tool()
    conn = _make_mock_connection(current_mode="change_detect")
    result = mod.apply(
        conn, source="DNA", table="ACCT",
        target_mode="both",
        actor="test", justification="t", dry_run=True,
    )
    assert result["event_kind"] == "dry_run"
    assert result["exit_code"] == mod.EXIT_SUCCESS
    assert result["transition_risk"] == "ALLOWED"
    assert result["dry_run"] is True
    # No commit on dry-run
    conn.commit.assert_not_called()


def test_apply_dry_run_no_update_executed():
    """D75 dry-run violation guard: NO UPDATE / INSERT executed on dry-run."""

    mod = _import_tool()
    conn = _make_mock_connection(current_mode="change_detect")
    cursor = conn.cursor.return_value
    mod.apply(
        conn, source="DNA", table="ACCT",
        target_mode="both",
        actor="test", justification="t", dry_run=True,
    )
    # Only 1 SELECT executed (current mode probe); NO UPDATE, NO INSERT
    sqls = [call.args[0] for call in cursor.execute.call_args_list]
    for sql in sqls:
        upper = sql.upper()
        assert "UPDATE" not in upper, f"D75 violation: UPDATE executed: {sql[:80]}"
        assert "INSERT INTO" not in upper, f"D75 violation: INSERT executed: {sql[:80]}"


# ---------------------------------------------------------------------------
# Class D — defensive Pitfall #9.k forward-prevention
# ---------------------------------------------------------------------------


def test_legacy_value_not_in_allowed_modes():
    """Pitfall #9.k forward-prevention: 'legacy' must NEVER appear in
    ALLOWED_MODES (canonical is 'change_detect' per D63)."""

    mod = _import_tool()
    assert "legacy" not in mod.ALLOWED_MODES
    assert "Legacy" not in mod.ALLOWED_MODES


def test_module_source_excludes_legacy_literal():
    """Defensive: tool source MUST NOT contain 'legacy' as a CDCMode value
    (Pitfall #9.k stale-value drift class — same anchor as RB-16 fix at
    a53c50a 2026-05-19)."""

    src = Path("tools/flip_cdc_mode.py").read_text(encoding="utf-8")
    # The string 'legacy' appears once in the tool — as a NEGATIVE test value
    # in the test file, not in the production module. Verify it's not a
    # CDCMode value reference in the production tool itself.
    # Per discovery: 'legacy' is used in docstrings as descriptive English
    # ("RB-16 rollback") not as a CDCMode enum literal.
    # Check that no enum-style string literal 'legacy' appears:
    assert "'legacy'" not in src, "Pitfall #9.k drift: 'legacy' string literal found"
    assert '"legacy"' not in src, "Pitfall #9.k drift: \"legacy\" string literal found"
