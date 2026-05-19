"""Tier 1 identity test for B-345 — canonical `TABLE_LOCK_RESOURCE_FORMAT`.

Per Phase 2 large-tables plan v5 §4.1 + delta v5 §1 B-345: the
`orchestration/table_lock.py::TABLE_LOCK_RESOURCE_FORMAT` constant is the
SINGLE SOURCE OF TRUTH for the `sp_getapplock @Resource` string used to
prevent concurrent pipeline runs on the same (source, table). Future
consumers — specifically `data_load/parquet_replay.py::replay_table_lock`
when B-332 `replay_parquet_range` lands at R2 — MUST import this constant
rather than hand-coding their own format.

If the replay-side and the orchestrator-side resource strings ever drift,
the `sp_getapplock` semantic breaks: both processes would acquire
"different" locks for the same logical table, opening a double-write
window during Bronze SCD2 promotion + Snowflake replication.

This test is **forward-prevention** — it pins the canonical format BEFORE
the consumer (replay_table_lock) is authored. When the consumer lands
at R2, this test should be extended (per the marker comment at the
bottom of this file) to ALSO verify that `replay_table_lock` invokes
`TABLE_LOCK_RESOURCE_FORMAT.format(...)` with the same arguments.

D-numbers consumed: D55 + D56 (producer ≠ reviewer; this test is the
mechanical reviewer of the canonical contract). D67 (Tier 1 discipline).
D92 (forward-only additive — the public promotion of `_LOCK_RESOURCE`
is additive; no external imports affected since the leading underscore
signaled private).

W-8 + N-1 invariants (Session-owned + ODBC resiliency) are NOT tested
here — those are integration-level concerns covered by Tier 3.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# Canonical expected format per orchestration/table_lock.py:47.
# Hard-coded here as a separate-source-of-truth-witness so a producer
# editing the orchestrator constant cannot silently change the contract
# without this test failing.
_CANONICAL_FORMAT = "UDM_Pipeline_{source}_{table}"


def _import_table_lock():
    """Lazy import with sys.modules pre-patch.

    `orchestration/table_lock.py` does `import configuration as configuration`
    which only resolves when `utils/` (containing configuration.py) is on the
    sys.path — that happens in production entry points (main_*.py) but NOT
    in pytest collection from `tests/tier1/`. Pre-patch the `configuration`
    module with a MagicMock so the import succeeds; we only care about the
    canonical constant value, not the configuration values themselves.

    Also pre-patch `pyodbc` so we don't require it installed on Windows dev
    workstations (per CLAUDE.md "Dev workstation pytest collection skew" /
    B-328 — production deps may not be present locally).
    """
    if "configuration" not in sys.modules:
        sys.modules["configuration"] = MagicMock()
    if "pyodbc" not in sys.modules:
        sys.modules["pyodbc"] = MagicMock()
    # Use importlib to force a fresh import so the mocks apply
    import importlib.util  # noqa: PLC0415
    spec = importlib.util.spec_from_file_location(
        "orchestration_table_lock_test",
        _PROJECT_ROOT / "orchestration" / "table_lock.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_canonical_format_constant_present_and_public():
    """B-345: the constant must be importable as a public name (no leading underscore)."""
    mod = _import_table_lock()
    assert hasattr(mod, "TABLE_LOCK_RESOURCE_FORMAT"), (
        "orchestration.table_lock must expose TABLE_LOCK_RESOURCE_FORMAT "
        "as a public constant per B-345 (was private _LOCK_RESOURCE pre-2026-05-18)."
    )
    # Old private name MUST be gone (no aliasing — clean rename per B-345)
    assert not hasattr(mod, "_LOCK_RESOURCE"), (
        "orchestration.table_lock should NOT carry the old _LOCK_RESOURCE alias; "
        "clean rename per B-345 (no external imports of the private name existed "
        "at rename time per git grep verification)."
    )


def test_canonical_format_string_value():
    """Pin the canonical format string against drift."""
    mod = _import_table_lock()
    assert mod.TABLE_LOCK_RESOURCE_FORMAT == _CANONICAL_FORMAT, (
        f"TABLE_LOCK_RESOURCE_FORMAT drift detected: got {mod.TABLE_LOCK_RESOURCE_FORMAT!r}, "
        f"expected {_CANONICAL_FORMAT!r}. Any change to this constant requires a new "
        f"D-N (lock-resource format is a contract with downstream consumers like "
        f"replay_table_lock per B-332)."
    )


@pytest.mark.parametrize(
    "source,table,expected",
    [
        ("DNA", "ACCT", "UDM_Pipeline_DNA_ACCT"),
        ("CCM", "AuditLog", "UDM_Pipeline_CCM_AuditLog"),
        ("DNA", "CARDTXN", "UDM_Pipeline_DNA_CARDTXN"),
        ("EPICOR", "PartTransfer", "UDM_Pipeline_EPICOR_PartTransfer"),
    ],
)
def test_canonical_format_substitution(source, table, expected):
    """Format substitution must produce the expected sp_getapplock @Resource value."""
    mod = _import_table_lock()
    resource = mod.TABLE_LOCK_RESOURCE_FORMAT.format(source=source, table=table)
    assert resource == expected, (
        f"Format substitution drift for ({source!r}, {table!r}): "
        f"got {resource!r}, expected {expected!r}"
    )


def test_canonical_format_required_placeholders_present():
    """Format string must contain {source} and {table} placeholders only."""
    mod = _import_table_lock()
    fmt = mod.TABLE_LOCK_RESOURCE_FORMAT
    assert "{source}" in fmt, "TABLE_LOCK_RESOURCE_FORMAT must contain {source} placeholder"
    assert "{table}" in fmt, "TABLE_LOCK_RESOURCE_FORMAT must contain {table} placeholder"
    # No other placeholders allowed (would change the substitution contract)
    import string
    field_names = {
        field for _, field, _, _ in string.Formatter().parse(fmt) if field
    }
    assert field_names == {"source", "table"}, (
        f"TABLE_LOCK_RESOURCE_FORMAT has unexpected placeholders: {field_names - {'source', 'table'}}"
    )


# -----------------------------------------------------------------------------
# Forward-prevention marker — extend when B-332 replay_parquet_range lands at R2
# -----------------------------------------------------------------------------
#
# When `data_load/parquet_replay.py::replay_table_lock` is authored
# (per B-332 + Phase 2 v5 plan §3.2 step 3), extend this test file with:
#
# def test_replay_table_lock_uses_canonical_format():
#     """B-345 identity: replay-side lock must use orchestration-side canonical format."""
#     from data_load.parquet_replay import replay_table_lock  # noqa
#     from orchestration.table_lock import TABLE_LOCK_RESOURCE_FORMAT  # noqa
#
#     # Assert via source inspection OR mock-based call assertion:
#     #   - replay_table_lock module-level constant `_REPLAY_LOCK_FORMAT` (if any)
#     #     equals TABLE_LOCK_RESOURCE_FORMAT
#     #   - OR the function body resolves the resource string by importing the
#     #     canonical constant (verifiable via ast.parse + module-attribute walk)
#     ...
#
# This forward marker is the canonical extension point. Until R2 ships, the
# tests above pin the orchestrator-side contract. Drift at the replay-side
# (when authored) will be caught by the extended test.
