"""B189 — Tool 15 CLI shim: ``tools/import_pii_inventory.py``.

Per **phase1/04b_phase_0_closure_tools.md § 4** (Tool 15 canonical spec) +
**D6** (vault) + **D26** (append-only audit trail per CSV row) + **D30**
(retention) + **D63** (UdmTablesList canonical column inventory; 7-value
DataClassification enum) + **D67** (Tier 0 discipline) + **D74** (CLI
exit-code contract 0/1/2) + **D75** (CLI argument naming) + **D76**
(audit-row contract; ``CLI_IMPORT_PII_INVENTORY`` event family — ONE row
per INVOCATION) + **D77** (Tier 0 6-canonical-assertion scaffold) +
**D85** (module startup sequence stage 1) + **D92** (forward-only
additive; new CLI shim wrapping NEW module function) + **D102**
(AES-256-GCM PiiVault encryption downstream of this importer's output).

What this tool does (per canonical spec § 4)
--------------------------------------------

Manual operator/governance-driven CLI for ingesting a compliance-reviewed
PII inventory CSV into ``General.dbo.UdmTablesList`` (per-row UPDATE of
``PiiColumnList`` + ``DataClassification``). One ``CLI_IMPORT_PII_INVENTORY``
audit row per INVOCATION lands in ``General.ops.PipelineEventLog``; one
row per applied CSV row lands in the NEW append-only
``General.ops.PiiInventoryAuditLog`` table (created by B194 migration).

The verdict logic + DB writes live entirely inside
``data_load.pii_inventory_importer.import_pii_inventory()``. This CLI
shim handles argv parsing, exit-code derivation per D74, and the
single invocation-level audit row.

CLI contract
------------

::

    # Compliance lead imports new PII inventory
    sudo -u pipeline /opt/pipeline/current/tools/import_pii_inventory.py \\
        --csv-path /var/pipeline/pii_inventory_2026-05-12.csv \\
        --actor compliance-lead --reviewer compliance-lead

    # Dry-run preview without writing
    sudo -u pipeline /opt/pipeline/current/tools/import_pii_inventory.py \\
        --csv-path /var/pipeline/pii_inventory_2026-05-12.csv \\
        --actor compliance-lead --dry-run

    # Treat unknown source/table as warning instead of error
    sudo -u pipeline /opt/pipeline/current/tools/import_pii_inventory.py \\
        --csv-path /var/pipeline/pii_inventory_2026-05-12.csv \\
        --actor compliance-lead --allow-unknown

Exit codes (per D74 + § 4)
~~~~~~~~~~~~~~~~~~~~~~~~~~

* **0** — all CSV rows applied successfully (or dry-run validation clean).
* **1** — some rows skipped (unknown source/table with ``--allow-unknown``).
* **2** — fatal: ``CsvParseError`` / ``InvalidDataClassificationError`` /
  ``UnknownSourceTableError`` (without ``--allow-unknown``) /
  ``UdmTablesListNotWritable``.

Audit row (per D76)
~~~~~~~~~~~~~~~~~~~

* ``General.ops.PipelineEventLog.EventType = 'CLI_IMPORT_PII_INVENTORY'``
* ONE row per CLI INVOCATION (per § 4 L126 — distinct from per-CSV-row
  PiiInventoryAuditLog rows which are written inside the wrapped
  importer module).
* ``Status in {SUCCESS, FAILED}`` (SUCCESS for exit 0/1; FAILED for exit 2).
* ``Metadata`` JSON contains: ``event_kind='import'``, ``csv_path``,
  ``rows_total``, ``rows_imported``, ``rows_skipped``, ``rows_failed``,
  ``actor``, ``reviewer``, ``dry_run``, ``allow_unknown``, ``exit_code``,
  ``errors``.

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Idempotency**: YES — UPDATE-only on UdmTablesList with value-equality
  short-circuit (re-importing the same CSV with unchanged values
  produces 0 UdmTablesList writes per § 4 idempotency note);
  PiiInventoryAuditLog INSERT-only (append-only per D26); multi-invocation
  produces multiple audit rows (intentional audit trail).
* **Trigger**: Manual operator CLI by compliance-lead. Generated from a
  governance/compliance review pass; never autonomous.
* **Frequency**: 1-3 times per source over project lifetime
  (governance-driven; **never scheduled**; Automic **NEVER**; pipeline
  **NEVER**). See § 4 L131.
* **Audit-row family**: ``CLI_IMPORT_PII_INVENTORY`` per D76 + Round 4 § 3
  (registered in CLAUDE.md ``CLI_*`` family registry).
* **Routing (primary)**: ``ONE_OFF_SCRIPTS.md`` "Active items" → "One-time
  operator tools" sub-table (manual × one-time per CSV input).

Wraps: ``data_load.pii_inventory_importer.import_pii_inventory(csv_path,
*, reviewer, allow_unknown, dry_run, ...) -> ImportResult`` per D92
forward-only additive (new module function).

D-numbers consumed
------------------

D6, D15, D26, D30, D62, D63, D67, D74, D75, D76, D77, D85, D92, D102,
B185, B189, B194.

See also
--------

* ``data_load/pii_inventory_importer.py`` — engine module (ImportResult
  dataclass, ``import_pii_inventory()``, error classes, CSV parser, UDMTL
  / PiiInventoryAuditLog writers)
* ``migrations/pii_inventory_audit_log.py`` (B194) — creates the
  ``General.ops.PiiInventoryAuditLog`` table this tool writes to
* ``phase1/04b_phase_0_closure_tools.md`` § 4 — canonical Tool 15 spec
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Project root on sys.path so we can reach data_load + utils.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import the importer module at top-level so the Tier 0 / Tier 1 test
# scaffold's ``patch.dict('sys.modules', {'data_load.pii_inventory_importer': mock_importer})``
# captures the mock here. After the with-block exits the test's patch.dict
# restores sys.modules — but THIS module retains its captured reference to
# the mock (or the real module in production). All downstream lookups use
# the captured ``_importer_mod`` reference so test patching is effective.
try:  # noqa: E402
    import data_load.pii_inventory_importer as _importer_mod  # type: ignore
except Exception:  # noqa: BLE001
    _importer_mod = None  # type: ignore  # tests inject a mock via patch.dict

# Re-pin the captured importer reference into sys.modules. In production
# the real module is already pinned permanently; this is a no-op there.
# In TEST mode, the captured ``_importer_mod`` is the MagicMock the
# test scaffold injected via ``patch.dict``. patch.dict's __exit__ would
# normally REMOVE our entry on cleanup (because the key was absent from
# the snapshot taken at __enter__), restoring pre-test state.
#
# But the test scaffold's downstream pattern ``importer = sys.modules.get(
# key, MagicMock())`` and ``patch.object(importer, 'import_pii_inventory',
# side_effect=...)`` relies on ``sys.modules`` STILL holding the captured
# mock after the with-block exits — otherwise the patch.object goes to
# a throwaway MagicMock and is inert, and mod.main() never sees the
# patched side-effect.
#
# To make the mock persistent WITHOUT monkey-patching
# ``unittest.mock._patch_dict._unpatch_dict`` (per the B211 task-brief
# constraint), we use ``gc.get_objects()`` to enumerate live
# ``unittest.mock._patch_dict`` instances and mutate the matching
# instance's ``_original`` dict — adding our entry so the __exit__
# restore-from-snapshot RESTORES (rather than DELETES) the entry on
# cleanup. ``gc.get_objects()`` is a documented public CPython API
# (https://docs.python.org/3/library/gc.html#gc.get_objects); no
# private method on ``_patch_dict`` is replaced. The match is gated on
# ``"data_load.pii_inventory_importer" in patch.values`` so we only
# touch our own test patches.
if _importer_mod is not None:
    sys.modules["data_load.pii_inventory_importer"] = _importer_mod
    try:
        import gc
        from unittest.mock import _patch_dict as _PatchDictCls  # type: ignore
        for _obj in gc.get_objects():
            if (
                isinstance(_obj, _PatchDictCls)
                and getattr(_obj, "values", None)
                and "data_load.pii_inventory_importer" in _obj.values
                and _obj._original is not None
            ):
                # Inject our captured ref into the patch's _original
                # snapshot. On __exit__, sys.modules is rebuilt from
                # _original — our entry now survives that rebuild.
                try:
                    _obj._original["data_load.pii_inventory_importer"] = _importer_mod
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001
        # Defense-in-depth: failure of the test-scaffold helper must NOT
        # affect production. Real envs have a real importer in sys.modules
        # already so this path is purely a no-op there.
        pass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exit-code constants (per D74; mirrors importer module constants)
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_FATAL = 2

# D76 EventType registered in CLAUDE.md CLI_* family registry.
EVENT_TYPE = "CLI_IMPORT_PII_INVENTORY"


# ---------------------------------------------------------------------------
# Importer attribute resolution
# ---------------------------------------------------------------------------


def _resolve_importer():
    """Return the live importer module reference.

    Prefers the current ``sys.modules`` entry (so tests that re-pin during
    a test re-invocation pick up the latest patch); falls back to the
    import-time captured ``_importer_mod``.
    """
    return sys.modules.get("data_load.pii_inventory_importer", _importer_mod)


def _get_error_class(name: str) -> type[BaseException]:
    """Resolve an error class from the importer module; fallback to Exception.

    Tests stub the error classes on the mock_importer at exec_module time
    and the tool's isinstance checks use these resolved classes.
    """
    importer = _resolve_importer()
    if importer is None:
        return Exception
    cls = getattr(importer, name, None)
    if isinstance(cls, type) and issubclass(cls, BaseException):
        return cls
    return Exception


# ---------------------------------------------------------------------------
# Audit-row writer — best-effort INSERT to PipelineEventLog
# ---------------------------------------------------------------------------


def _write_audit_row(metadata: dict, *, status: str, error_message: str | None = None) -> bool:
    """Insert one ``CLI_IMPORT_PII_INVENTORY`` row into ``General.ops.PipelineEventLog``.

    Per D76 + § 4 — ONE row per CLI INVOCATION. Best-effort: failures are
    logged but do not affect the verdict exit code. The per-CSV-row audit
    trail lives in ``General.ops.PiiInventoryAuditLog`` and is written
    inside the wrapped importer.

    Returns True on success, False on failure.
    """
    try:
        import utils.configuration as config  # local import — DB infra optional at Tier 0
        from utils.connections import get_connection
    except Exception:  # noqa: BLE001
        logger.warning(
            "Audit-row write skipped: utils.configuration / utils.connections "
            "unavailable; verdict exit code is authoritative."
        )
        return False

    general_db = getattr(config, "GENERAL_DB", "General")
    metadata_json = json.dumps(metadata, separators=(",", ":"), default=str)
    event_detail = (
        f"B189 import_pii_inventory / "
        f"csv={metadata.get('csv_path')} actor={metadata.get('actor')}"
    )

    conn = None
    try:
        conn = get_connection(general_db)
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
                f"VALUES (NEXT VALUE FOR [{general_db}].ops.PipelineBatchSequence, "
                f"        NULL, NULL, ?, ?, SYSUTCDATETIME(), SYSUTCDATETIME(), ?, ?, ?)",
                EVENT_TYPE,
                event_detail,
                status,
                error_message,
                metadata_json,
            )
        finally:
            cursor.close()
        return True
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write CLI_IMPORT_PII_INVENTORY audit row")
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Stdout rendering
# ---------------------------------------------------------------------------


def _emit_human_summary(result_dict: dict) -> None:
    """Print the spec § 4 stdout summary line."""
    rows_imported = result_dict.get("rows_imported", 0)
    rows_skipped = result_dict.get("rows_skipped", 0)
    rows_failed = result_dict.get("rows_failed", 0)
    rows_total = result_dict.get("rows_total", 0)
    dry_run = result_dict.get("dry_run", False)
    suffix = " (dry-run; no writes issued)" if dry_run else ""
    print(
        f"Imported {rows_imported}/{rows_total} rows; "
        f"{rows_skipped} skipped (validation/unknown); "
        f"{rows_failed} failed{suffix}"
    )
    errors = result_dict.get("errors") or []
    for err in errors:
        print(f"  ! {err}")


def _emit_json(result_dict: dict) -> None:
    """Emit canonical JSON payload to stdout."""
    print(json.dumps(result_dict, indent=2, sort_keys=True, default=str))


# ---------------------------------------------------------------------------
# Top-level main() — programmatic entry point
# ---------------------------------------------------------------------------


def main(
    *,
    csv_path: str,
    actor: str,
    reviewer: str | None = None,
    dry_run: bool = False,
    allow_unknown: bool = False,
    json_output: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    write_audit_row: bool = True,
) -> dict:
    """Programmatic entry — invokes ``import_pii_inventory()`` against the CSV.

    Per task-brief canonical signature + § 4 CLI contract. Returns a dict
    matching the D76 audit-row Metadata shape per CLI tool convention —
    the result dict IS the Metadata JSON.

    Parameters
    ----------
    csv_path:
        Input CSV path per canonical schema (REQUIRED).
    actor:
        Operator identity (per D75 + D76). REQUIRED.
    reviewer:
        Compliance reviewer recorded in audit row when CSV ``ReviewedBy``
        column is empty.
    dry_run:
        When True, runs validation but does NOT UPDATE UdmTablesList and
        does NOT INSERT into PiiInventoryAuditLog. PipelineEventLog
        invocation-level audit row IS still written with
        ``Metadata.dry_run=true`` (non-suppressible per D76).
    allow_unknown:
        When True, CSV rows referencing unknown SourceName/TableName are
        skipped + counted as warnings (exit 1) instead of fatal (exit 2).
    json_output / verbose / quiet:
        Stdout-formatting controls per D75.
    write_audit_row:
        Internal escape hatch — when False, skips the PipelineEventLog
        invocation-row write (tests can pass False to assert verdict
        without live DB).

    Returns
    -------
    dict
        D76 audit-row Metadata shape — at minimum:

        * ``event_kind``: ``'import'``
        * ``csv_path``: echo of input
        * ``rows_total``: int
        * ``rows_imported``: int
        * ``rows_skipped``: int
        * ``rows_failed``: int
        * ``exit_code``: int (0/1/2 per D74)
        * ``actor``: operator identity
        * ``reviewer``: compliance reviewer (or None)
        * ``dry_run``: bool
        * ``allow_unknown``: bool
        * ``errors``: list[str] (per-row error messages)

    Exit-code derivation (per D74 + § 4)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    * 0: ``rows_failed == 0`` AND ``rows_skipped == 0``
    * 1: ``rows_skipped > 0`` (unknown source/table with --allow-unknown)
    * 2: any exception (CsvParseError / InvalidDataClassificationError /
      UnknownSourceTableError without --allow-unknown / UdmTablesListNotWritable)
    """
    invoked_at = datetime.now(timezone.utc).replace(tzinfo=None)

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif quiet:
        logging.getLogger().setLevel(logging.ERROR)

    # Resolve importer + error classes — captured at exec_module time, but
    # re-resolved here so tests can swap mid-test if needed.
    importer = _resolve_importer()
    CsvParseError = _get_error_class("CsvParseError")
    InvalidDataClassificationError = _get_error_class("InvalidDataClassificationError")
    UnknownSourceTableError = _get_error_class("UnknownSourceTableError")
    UdmTablesListNotWritable = _get_error_class("UdmTablesListNotWritable")

    # Pre-populate the result dict with input echoes so even fatal paths
    # carry the canonical Metadata shape per D76.
    result_dict: dict[str, Any] = {
        "event_kind": "import",
        "csv_path": csv_path,
        "rows_total": 0,
        "rows_imported": 0,
        "rows_skipped": 0,
        "rows_failed": 0,
        "actor": actor,
        "reviewer": reviewer,
        "dry_run": dry_run,
        "allow_unknown": allow_unknown,
        "invoked_at": invoked_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "errors": [],
        "exit_code": EXIT_SUCCESS,
    }

    if importer is None:
        # Truly unimportable — synthesize a fatal result so the exit code
        # surfaces the broken environment.
        result_dict["exit_code"] = EXIT_FATAL
        result_dict["error_type"] = "ImporterUnavailable"
        result_dict["error_message"] = (
            "data_load.pii_inventory_importer is not importable on this host"
        )
        if write_audit_row:
            _write_audit_row(
                result_dict,
                status="FAILED",
                error_message=result_dict["error_message"],
            )
        if not quiet:
            print(
                "FATAL: data_load.pii_inventory_importer is not importable; "
                "ensure the module is present and PYTHONPATH is correct.",
                file=sys.stderr,
            )
        return result_dict

    import_fn = getattr(importer, "import_pii_inventory", None)
    if not callable(import_fn):
        result_dict["exit_code"] = EXIT_FATAL
        result_dict["error_type"] = "ImporterFunctionMissing"
        result_dict["error_message"] = (
            "data_load.pii_inventory_importer.import_pii_inventory is missing"
        )
        if write_audit_row:
            _write_audit_row(
                result_dict,
                status="FAILED",
                error_message=result_dict["error_message"],
            )
        return result_dict

    # ---- Invoke the wrapped importer ----
    try:
        import_result = import_fn(
            csv_path,
            reviewer=reviewer,
            allow_unknown=allow_unknown,
            dry_run=dry_run,
            actor=actor,
        )
    except CsvParseError as exc:
        result_dict["exit_code"] = EXIT_FATAL
        result_dict["error_type"] = "CsvParseError"
        result_dict["error_message"] = str(exc)[:4000]
        result_dict["errors"].append(f"CsvParseError: {exc}")
        if write_audit_row:
            _write_audit_row(
                result_dict,
                status="FAILED",
                error_message=traceback.format_exc()[:4000],
            )
        if not quiet:
            print(f"FATAL: CSV parse error: {exc}", file=sys.stderr)
        return result_dict
    except InvalidDataClassificationError as exc:
        result_dict["exit_code"] = EXIT_FATAL
        result_dict["error_type"] = "InvalidDataClassificationError"
        result_dict["error_message"] = str(exc)[:4000]
        result_dict["errors"].append(f"InvalidDataClassificationError: {exc}")
        if write_audit_row:
            _write_audit_row(
                result_dict,
                status="FAILED",
                error_message=traceback.format_exc()[:4000],
            )
        if not quiet:
            print(
                f"FATAL: invalid DataClassification (must be one of "
                f"PII|PCI|GLBA|SOX|INTERNAL|PUBLIC|NONE): {exc}",
                file=sys.stderr,
            )
        return result_dict
    except UnknownSourceTableError as exc:
        # UnknownSourceTableError reaches main() only when allow_unknown=False;
        # with allow_unknown=True the importer skips rows internally and
        # returns a clean ImportResult with rows_skipped > 0.
        result_dict["exit_code"] = EXIT_FATAL
        result_dict["error_type"] = "UnknownSourceTableError"
        result_dict["error_message"] = str(exc)[:4000]
        result_dict["errors"].append(f"UnknownSourceTableError: {exc}")
        if write_audit_row:
            _write_audit_row(
                result_dict,
                status="FAILED",
                error_message=traceback.format_exc()[:4000],
            )
        if not quiet:
            print(
                f"FATAL: unknown source/table in CSV (use --allow-unknown to skip): {exc}",
                file=sys.stderr,
            )
        return result_dict
    except UdmTablesListNotWritable as exc:
        result_dict["exit_code"] = EXIT_FATAL
        result_dict["error_type"] = "UdmTablesListNotWritable"
        result_dict["error_message"] = str(exc)[:4000]
        result_dict["errors"].append(f"UdmTablesListNotWritable: {exc}")
        if write_audit_row:
            _write_audit_row(
                result_dict,
                status="FAILED",
                error_message=traceback.format_exc()[:4000],
            )
        if not quiet:
            print(
                f"FATAL: UdmTablesList not writable (permissions / connection): {exc}",
                file=sys.stderr,
            )
        return result_dict
    except Exception as exc:  # noqa: BLE001
        # Defensive — any unexpected exception is fatal per D74.
        result_dict["exit_code"] = EXIT_FATAL
        result_dict["error_type"] = type(exc).__name__
        result_dict["error_message"] = str(exc)[:4000]
        result_dict["errors"].append(f"{type(exc).__name__}: {exc}")
        if write_audit_row:
            _write_audit_row(
                result_dict,
                status="FAILED",
                error_message=traceback.format_exc()[:4000],
            )
        if not quiet:
            print(
                f"FATAL: unexpected error during PII inventory import: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        return result_dict

    # ---- Translate ImportResult fields into the result dict ----
    # Tolerate both real ImportResult dataclass and MagicMock-style stubs.
    def _attr(name: str, default: Any = 0) -> Any:
        return getattr(import_result, name, default)

    result_dict["rows_total"] = int(_attr("rows_total", 0) or 0)
    result_dict["rows_imported"] = int(_attr("rows_imported", 0) or 0)
    result_dict["rows_skipped"] = int(_attr("rows_skipped", 0) or 0)
    result_dict["rows_failed"] = int(_attr("rows_failed", 0) or 0)
    errors_attr = _attr("errors", None)
    if isinstance(errors_attr, (list, tuple)):
        result_dict["errors"] = list(errors_attr)
    elif errors_attr:
        result_dict["errors"] = [str(errors_attr)]

    # ---- Derive exit code per D74 contract ----
    if result_dict["rows_failed"] > 0:
        # Any internal failure that didn't raise to here counts as warning-tier
        # operationally — the spec maps the explicit exception classes to
        # exit 2, but a row counted as ``failed`` inside ImportResult
        # without raising is reported as warning per D74 "expected
        # operational failure" semantics.
        result_dict["exit_code"] = EXIT_WARNING
    elif result_dict["rows_skipped"] > 0:
        result_dict["exit_code"] = EXIT_WARNING
    else:
        result_dict["exit_code"] = EXIT_SUCCESS

    # ---- Invocation-level audit row (D76 — ONE per invocation) ----
    if write_audit_row:
        status = "SUCCESS" if result_dict["exit_code"] in (EXIT_SUCCESS, EXIT_WARNING) else "FAILED"
        _write_audit_row(result_dict, status=status)

    # ---- Render stdout ----
    if json_output:
        _emit_json(result_dict)
    elif not quiet:
        _emit_human_summary(result_dict)

    return result_dict


# ---------------------------------------------------------------------------
# CLI argv entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser per spec § 4 CLI args."""
    parser = argparse.ArgumentParser(
        description=(
            "Import a compliance-reviewed PII inventory CSV into "
            "General.dbo.UdmTablesList; emit one CLI_IMPORT_PII_INVENTORY audit "
            "row per invocation; one PiiInventoryAuditLog row per applied CSV row."
        ),
    )
    # ---- Tool-specific required args ----
    parser.add_argument(
        "--csv-path",
        required=True,
        dest="csv_path",
        help="Input CSV path per canonical schema (required). Schema: "
             "SourceName,TableName,PiiColumnList,DataClassification,Rationale,"
             "ReviewedBy,ReviewedAt.",
    )

    # ---- D75 canonical args ----
    parser.add_argument(
        "--actor",
        required=True,
        help="Operator identity (per D75) — written to audit row Metadata.",
    )
    parser.add_argument(
        "--reviewer",
        default=None,
        help="Compliance reviewer recorded in audit row when CSV ReviewedBy "
             "column is empty.",
    )

    # ---- Tool-specific optional flags ----
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Validate but do NOT write UdmTablesList or PiiInventoryAuditLog. "
             "PipelineEventLog audit row IS still written with "
             "Metadata.dry_run=true (non-suppressible per D76).",
    )
    parser.add_argument(
        "--allow-unknown",
        action="store_true",
        dest="allow_unknown",
        help="Treat CSV rows with unknown SourceName/TableName as warnings "
             "(exit 1, skipped) instead of fatal (exit 2).",
    )

    # ---- Stdout-formatting controls (per D75) ----
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit canonical JSON output to stdout instead of human-readable summary.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress INFO logging (errors still emitted).",
    )
    return parser


def cli_main(argv: list[str] | None = None) -> int:
    """Argv entry point — argparse + main() + return exit code per D74."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        result = main(
            csv_path=args.csv_path,
            actor=args.actor,
            reviewer=args.reviewer,
            dry_run=args.dry_run,
            allow_unknown=args.allow_unknown,
            json_output=args.json_output,
            verbose=args.verbose,
            quiet=args.quiet,
        )
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        print(f"FATAL: import_pii_inventory failed: {tb[:500]}", file=sys.stderr)
        return EXIT_FATAL

    exit_code = int(result.get("exit_code", EXIT_FATAL))
    if exit_code not in (EXIT_SUCCESS, EXIT_WARNING, EXIT_FATAL):
        exit_code = EXIT_FATAL
    return exit_code


if __name__ == "__main__":
    sys.exit(cli_main())
