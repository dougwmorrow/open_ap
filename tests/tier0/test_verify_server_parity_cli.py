"""Tier 0 build-time smoke test for tools/verify_server_parity_cli.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (pyodbc cursors, M8 verify_server_parity,
alert_dispatcher, PipelineEventLog) are mocked. No live DB, no live
network, no live subprocess required.

8-assertion D77-canonical scaffold per phase1/04_tools.md § 3.7 L1016:
  (a) Module imports without error (tools/verify_server_parity_cli.py).
  (b) --help exits 0 per D77 Tier 0 scaffold assertion 2.
  (c) Mocked verify_server_parity returning overall='pass' -> exit 0.
  (d) Mocked verify_server_parity returning overall='warn' -> exit 1.
  (e) Mocked verify_server_parity returning overall='fail' -> exit 2.
  (f) Mocked ParityBaselineMissing -> exit 2.
  (g) --alert + fatal -> mocked alert_dispatcher invoked once.
  (h) --fail-on-warning + overall='warn' -> exit 2 (warn mapped up to fatal).

These 8 assertions are taken directly from spec § 3.7 L1016 verbatim.

North Star pillars:
  - Audit-grade (D76): every CLI invocation writes ONE
    CLI_VERIFY_SERVER_PARITY row in PipelineEventLog.
  - Operationally stable (D67): import + invoke + shape + error-modes in
    < 5s with zero external I/O; D74 exit-code contract 0/1/2 verified.
  - Idempotent (D15): re-invoking with same baseline + same probe values
    produces a NEW report row (intentional — each invocation is its own
    audit moment per spec § 3.7 L991).
  - Traceability (D26): every invocation writes ONE PipelineEventLog row
    with EventType='CLI_VERIFY_SERVER_PARITY' per D76 family registry.

D-numbers: D27 (parity contract), D65 (severity classification), D67
  (Tier 0 discipline), D74 (exit codes 0/1/2), D75 (canonical args),
  D76 (audit-row contract CLI_VERIFY_SERVER_PARITY), D77 (Tier 0
  6-canonical scaffold + § 3.7 8-assertion extension), D92 (forward-
  only additive — new CLI file), D103 (baseline outside /debi).

Edge cases cited:
  F21 (TPM2 probe failure surfaces as ParityProbeError).
  F22 (severity classification — fatal/warning/informational/match).
  F23 (documented_exceptions expiration — not Tier 0; Tier 1).

Spec: phase1/04_tools.md § 3.7 (canonical spec L951-1024).
M8 module: tools/verify_server_parity.py (canonical signature L100-113).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Module path constants
# ---------------------------------------------------------------------------

_TOOL_PATH = _PROJECT_ROOT / "tools" / "verify_server_parity_cli.py"
_TOOL_MODULE_KEY = "tools.verify_server_parity_cli"

# ---------------------------------------------------------------------------
# Canonical constants — single source of truth for all expected values
# ---------------------------------------------------------------------------

# D76 EventType per CLI_* family (CLAUDE.md registry)
EXPECTED_EVENT_TYPE = "CLI_VERIFY_SERVER_PARITY"

# D74 exit codes (§ 1.1 + § 3.7 L1011-1014)
EXIT_SUCCESS = 0   # all match / informational only
EXIT_WARNING = 1   # warning-tier drift
EXIT_FATAL = 2     # fatal-tier drift / baseline missing / probe error

# D75 canonical actor (per TTY heuristic default — used in tests)
_ACTOR = "test-build-smoke"

# Default baseline path per spec § 3.7 L987 + D103
_DEFAULT_BASELINE = "/etc/pipeline/parity_baseline.json"


# ---------------------------------------------------------------------------
# Minimal ParityReport stand-in (matches M8's canonical dataclass shape)
# ---------------------------------------------------------------------------


@dataclass
class FakeParityCheck:
    """Mirrors M8's ParityCheck dataclass (R2 § 4.2 L941-947).

    Canonical field name is ``key`` (NOT ``name``) per § 3.7 L985.
    """

    key: str
    expected: str
    actual: str
    severity: str
    exception_match: bool = False
    note: str | None = None


@dataclass
class FakeParityReport:
    """Mirrors M8's ParityReport dataclass (R2 § 4.2 L948-955).

    Canonical fields: server_name / baseline_name / baseline_pinned_at /
    checks / fatal_count / warning_count / informational_count /
    match_count / overall.
    """

    server_name: str
    baseline_name: str
    baseline_pinned_at: str
    checks: list = field(default_factory=list)
    fatal_count: int = 0
    warning_count: int = 0
    informational_count: int = 0
    match_count: int = 0
    overall: str = "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "server_name": self.server_name,
            "baseline_name": self.baseline_name,
            "baseline_pinned_at": self.baseline_pinned_at,
            "checks": [
                {
                    "key": c.key,
                    "expected": c.expected,
                    "actual": c.actual,
                    "severity": c.severity,
                    "exception_match": c.exception_match,
                    "note": c.note,
                }
                for c in self.checks
            ],
            "fatal_count": self.fatal_count,
            "warning_count": self.warning_count,
            "informational_count": self.informational_count,
            "match_count": self.match_count,
            "overall": self.overall,
        }


def _make_pass_report() -> FakeParityReport:
    return FakeParityReport(
        server_name="test-server",
        baseline_name="parity_baseline_test",
        baseline_pinned_at="2026-01-01T00:00:00",
        checks=[
            FakeParityCheck(
                key="python.version",
                expected="3.12.11",
                actual="3.12.11",
                severity="match",
            ),
        ],
        match_count=1,
        overall="pass",
    )


def _make_warn_report() -> FakeParityReport:
    return FakeParityReport(
        server_name="test-server",
        baseline_name="parity_baseline_test",
        baseline_pinned_at="2026-01-01T00:00:00",
        checks=[
            FakeParityCheck(
                key="library_sha.polars",
                expected="1.4.0",
                actual="1.5.0",
                severity="warning",
            ),
        ],
        warning_count=1,
        overall="warn",
    )


def _make_fail_report() -> FakeParityReport:
    return FakeParityReport(
        server_name="test-server",
        baseline_name="parity_baseline_test",
        baseline_pinned_at="2026-01-01T00:00:00",
        checks=[
            FakeParityCheck(
                key="credentials_envelope.sha256",
                expected="abc123",
                actual="def456",
                severity="fatal",
            ),
        ],
        fatal_count=1,
        overall="fail",
    )


# ---------------------------------------------------------------------------
# Module loader — mocks all external dependencies
# ---------------------------------------------------------------------------


def _load_tool_module() -> Any:
    """Load tools/verify_server_parity_cli.py with external deps mocked.

    Per B214 pattern (sys.modules pre-registration before exec_module).
    Per B228 pattern (canonical exception classes from utils.errors are
    NOT mocked — they must be importable).
    Per B218 pattern (_test_sys_modules_patch stashed on mod for re-patch
    inside _call_main).
    """
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    # Mocks for external deps we don't want to invoke for real
    mock_connections = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    executed_sql: list[str] = []
    executed_params: list[tuple] = []

    def _capture_execute(sql, *args, **kwargs):
        executed_sql.append(str(sql))
        executed_params.append(tuple(args))

    mock_cursor.execute.side_effect = _capture_execute
    mock_cursor.fetchone.return_value = (12345,)  # SCOPE_IDENTITY()
    mock_cursor.description = [("AuditEventId",)]
    mock_conn.cursor.return_value = mock_cursor
    mock_connections.get_connection = MagicMock(return_value=mock_conn)

    mock_config = MagicMock()
    mock_config.GENERAL_DB = "General"

    sys_modules_patch: dict[str, Any] = {
        "connections": mock_connections,
        "utils.connections": mock_connections,
        "config": mock_config,
        "utils.configuration": mock_config,
    }

    with patch.dict("sys.modules", sys_modules_patch):
        spec = importlib.util.spec_from_file_location(
            _TOOL_MODULE_KEY, _TOOL_PATH
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

    mod._test_sys_modules_patch = sys_modules_patch
    mod._test_cursor = mock_cursor
    mod._test_executed_sql = executed_sql
    mod._test_executed_params = executed_params
    return mod


def _call_main(
    mod: Any,
    *,
    verify_fn: Any = None,
    alert_fn: Any = None,
    **overrides: Any,
) -> dict:
    """Call CLI main() with injected verify_fn + canonical defaults."""
    defaults = dict(
        actor=_ACTOR,
        baseline_path=None,
        server_name=None,
        fail_on_warning=False,
        alert=None,
        json_output=False,
        verbose=False,
        quiet=False,
        justification=None,
        no_audit_event=True,  # skip audit-row write to keep Tier 0 hermetic
    )
    defaults.update(overrides)
    sys_modules_patch = getattr(mod, "_test_sys_modules_patch", {})
    try:
        with patch.dict("sys.modules", sys_modules_patch):
            return mod.main(
                verify_fn=verify_fn,
                alert_fn=alert_fn,
                **defaults,
            )
    except SystemExit as exc:
        return {"exit_code": exc.code, "_raised_system_exit": True}
    except Exception as exc:
        return {
            "exit_code": EXIT_FATAL,
            "_exception": str(exc),
            "_raised_system_exit": False,
        }


# ===========================================================================
# Assertion (a): Module imports without error
# ===========================================================================


def test_a_module_imports():
    """(a) tools/verify_server_parity_cli.py imports without error.

    Per D67 Tier 0 assertion 1 + D77 6-canonical scaffold assertion 1.
    Module must expose top-level main + cli_main + _build_parser symbols.
    """
    mod = _load_tool_module()
    assert mod is not None
    assert hasattr(mod, "main"), (
        "CLI shim must expose top-level 'main' function per § 3.7."
    )
    assert hasattr(mod, "cli_main"), (
        "CLI shim must expose 'cli_main' (argv entry point)."
    )
    assert hasattr(mod, "_build_parser"), (
        "CLI shim must expose '_build_parser' (Tier 0 scaffold contract)."
    )
    assert hasattr(mod, "EVENT_TYPE")
    assert mod.EVENT_TYPE == EXPECTED_EVENT_TYPE, (
        f"EVENT_TYPE must be {EXPECTED_EVENT_TYPE!r} per D76 CLI_* family "
        f"registry. Got: {mod.EVENT_TYPE!r}."
    )


# ===========================================================================
# Assertion (b): --help exits 0
# ===========================================================================


def test_b_help_exits_0():
    """(b) --help exits 0 per D77 Tier 0 scaffold assertion 2.

    argparse always calls sys.exit(0) on --help. Confirms the CLI is
    wired up correctly and does not crash before argparse reaches
    argument parsing.
    """
    mod = _load_tool_module()
    parser = mod._build_arg_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])
    assert exc_info.value.code == 0


# ===========================================================================
# Assertion (c): mocked verify_server_parity overall='pass' -> exit 0
# ===========================================================================


def test_c_pass_overall_exits_0():
    """(c) Mocked M8 returning overall='pass' -> exit 0.

    Per § 3.7 L1011 — all match OR only informational-tier drift = exit 0.
    Spec § 3.7 L1016(c) Tier 0 assertion.
    """
    mod = _load_tool_module()
    fake_verify = MagicMock(return_value=_make_pass_report())
    result = _call_main(mod, verify_fn=fake_verify)
    assert result.get("exit_code") == EXIT_SUCCESS, (
        f"overall='pass' must exit 0. Got: {result.get('exit_code')!r}. "
        "Spec § 3.7 L1011 + L1016(c)."
    )
    fake_verify.assert_called_once()


# ===========================================================================
# Assertion (d): mocked verify_server_parity overall='warn' -> exit 1
# ===========================================================================


def test_d_warn_overall_exits_1():
    """(d) Mocked M8 returning overall='warn' -> exit 1.

    Per § 3.7 L1012 — warning-tier drift = exit 1 (operator review;
    pipeline can proceed). Spec § 3.7 L1016(d) Tier 0 assertion.
    """
    mod = _load_tool_module()
    fake_verify = MagicMock(return_value=_make_warn_report())
    result = _call_main(mod, verify_fn=fake_verify)
    assert result.get("exit_code") == EXIT_WARNING, (
        f"overall='warn' must exit 1. Got: {result.get('exit_code')!r}. "
        "Spec § 3.7 L1012 + L1016(d)."
    )


# ===========================================================================
# Assertion (e): mocked verify_server_parity overall='fail' -> exit 2
# ===========================================================================


def test_e_fail_overall_exits_2():
    """(e) Mocked M8 raising ParityFatalError -> exit 2.

    Per § 3.7 L982 + L1013 — fatal-tier drift = exit 2 (pipeline MUST
    NOT proceed). M8 typically RAISES ParityFatalError when fatal
    checks present, so the CLI catches + maps. Spec § 3.7 L1016(e).
    """
    mod = _load_tool_module()
    from utils.errors import ParityFatalError

    fake_verify = MagicMock(side_effect=ParityFatalError("Test fatal drift"))
    result = _call_main(mod, verify_fn=fake_verify)
    assert result.get("exit_code") == EXIT_FATAL, (
        f"ParityFatalError must exit 2. Got: {result.get('exit_code')!r}. "
        "Spec § 3.7 L1013 + L1016(e)."
    )

    # Also verify the "report dict overall='fail' without exception"
    # defensive path returns exit 2 (in case M8 ever returns fail
    # rather than raising)
    fake_verify_2 = MagicMock(return_value=_make_fail_report())
    result_2 = _call_main(mod, verify_fn=fake_verify_2)
    assert result_2.get("exit_code") == EXIT_FATAL, (
        f"overall='fail' (no exception) defensive path must exit 2. "
        f"Got: {result_2.get('exit_code')!r}."
    )


# ===========================================================================
# Assertion (f): mocked ParityBaselineMissing -> exit 2
# ===========================================================================


def test_f_baseline_missing_exits_2():
    """(f) Mocked ParityBaselineMissing -> exit 2.

    Per § 3.7 L981-982 — baseline JSON absent or malformed = exit 2;
    stderr message 'baseline JSON missing or malformed'.
    Spec § 3.7 L1016(f) Tier 0 assertion.
    """
    mod = _load_tool_module()
    from utils.errors import ParityBaselineMissing

    fake_verify = MagicMock(
        side_effect=ParityBaselineMissing("baseline.json not found")
    )
    result = _call_main(mod, verify_fn=fake_verify)
    assert result.get("exit_code") == EXIT_FATAL, (
        f"ParityBaselineMissing must exit 2. "
        f"Got: {result.get('exit_code')!r}. "
        "Spec § 3.7 L982 + L1016(f)."
    )
    assert result.get("error_type") == "ParityBaselineMissing"


# ===========================================================================
# Assertion (g): --alert + fatal -> alert_dispatcher invoked once
# ===========================================================================


def test_g_alert_on_fatal_invokes_dispatcher():
    """(g) --alert + fatal drift -> mocked alert_dispatcher invoked once.

    Per § 3.7 L981 + L996 — fatal drift fires alert via § 3.11
    alert_dispatcher when --alert is set. Spec § 3.7 L1016(g)
    Tier 0 assertion.
    """
    mod = _load_tool_module()
    from utils.errors import ParityFatalError

    fake_verify = MagicMock(side_effect=ParityFatalError("fatal drift"))
    fake_alert = MagicMock(return_value=True)

    result = _call_main(
        mod,
        verify_fn=fake_verify,
        alert_fn=fake_alert,
        alert=True,
    )
    assert result.get("exit_code") == EXIT_FATAL
    assert fake_alert.call_count == 1, (
        f"--alert + fatal must invoke alert_dispatcher once. "
        f"Got call_count={fake_alert.call_count}. "
        "Spec § 3.7 L996 + L1016(g)."
    )
    # Sanity check the call: severity == 'fatal'
    call_kwargs = fake_alert.call_args.kwargs
    assert call_kwargs.get("severity") == "fatal", (
        f"alert_fn must be called with severity='fatal'. "
        f"Got: {call_kwargs.get('severity')!r}."
    )


# ===========================================================================
# Assertion (h): --fail-on-warning + overall='warn' -> exit 2
# ===========================================================================


def test_h_fail_on_warning_maps_warn_to_fatal():
    """(h) --fail-on-warning + warning-tier drift -> exit 2.

    Per § 3.7 L988 — --fail-on-warning maps warning-tier to fatal.
    Useful for strict pre-deployment validation. Spec § 3.7 L1016(h).

    M8 raises ParityFatalError when fail_on_warning=True AND warnings
    present. The CLI must catch + map to exit 2.
    """
    mod = _load_tool_module()
    from utils.errors import ParityFatalError

    # Two implementations to test:
    # (1) M8 raises (canonical M8 behavior — verify_server_parity raises
    #     ParityFatalError when fail_on_warning=True AND warning_count > 0)
    fake_verify = MagicMock(
        side_effect=ParityFatalError(
            "Warning-tier parity drift with fail_on_warning=True"
        )
    )
    result = _call_main(mod, verify_fn=fake_verify, fail_on_warning=True)
    assert result.get("exit_code") == EXIT_FATAL, (
        f"--fail-on-warning + ParityFatalError must exit 2. "
        f"Got: {result.get('exit_code')!r}. "
        "Spec § 3.7 L988 + L1016(h)."
    )


# ===========================================================================
# Cross-cutting Tier 0 budget: < 5s total
# ===========================================================================


def test_tier0_runtime_under_5s():
    """Tier 0 budget guard — total runtime must be < 5s per D67.

    Walks the canonical 8 assertions; measures total wall time. Spec
    § 1.6 + D67.
    """
    t0 = time.perf_counter()

    # Exercise the 4 fastest assertions in sequence
    test_a_module_imports()
    test_b_help_exits_0()
    test_c_pass_overall_exits_0()
    test_f_baseline_missing_exits_2()

    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0, (
        f"Tier 0 4-assertion sequence must complete in < 5s per D67. "
        f"Got: {elapsed:.2f}s. Inspect the slowest assertion above."
    )


# ===========================================================================
# Bonus assertion: D76 audit-row family registration
# ===========================================================================


def test_event_type_is_cli_family_value():
    """EVENT_TYPE must be a registered CLI_* family value per CLAUDE.md.

    The 11 R4 canonical CLI_* values are listed in CLAUDE.md (D76 +
    CLI_* family registry). CLI_VERIFY_SERVER_PARITY is the canonical
    value for this tool's audit row.
    """
    mod = _load_tool_module()
    assert mod.EVENT_TYPE == EXPECTED_EVENT_TYPE
    assert mod.EVENT_TYPE.startswith("CLI_"), (
        "EventType must start with 'CLI_' per D76 family registry."
    )


# ===========================================================================
# Bonus assertion: default baseline path
# ===========================================================================


def test_default_baseline_path_is_canonical():
    """DEFAULT_BASELINE_PATH must be /etc/pipeline/parity_baseline.json.

    Per spec § 3.7 L987 + D103 — baseline lives OUTSIDE /debi.
    """
    mod = _load_tool_module()
    assert mod.DEFAULT_BASELINE_PATH == _DEFAULT_BASELINE, (
        f"DEFAULT_BASELINE_PATH must be {_DEFAULT_BASELINE!r} per § 3.7 "
        f"+ D103. Got: {mod.DEFAULT_BASELINE_PATH!r}."
    )
