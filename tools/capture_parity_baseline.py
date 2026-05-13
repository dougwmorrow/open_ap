"""B183 — Tool 13 CLI shim: capture cross-server parity baseline JSON.

Per Round 4.5 supplement at ``docs/migration/phase1/04a_phase_0_prep_tools.md``
§ 4 (Tool 13 canonical spec). Wraps the NEW module function
``data_load.parity_baseline_capture.capture_baseline()`` per **D92** forward-only
additive schema-evolution governance.

Purpose
-------

Captures the current server's OS / library / env / systemd state to the
canonical baseline JSON per Round 2 § 4.1 schema at
``docs/migration/phase1/02_configuration.md`` L820-L915. Consumed by
``tools/verify_server_parity.py`` (R4 § 3.7) at every pipeline startup.

Scope (per phase2/01 § 4.3 cycle-3 fix)
---------------------------------------

Baseline captures **OS / library / env / systemd** state only — **NOT**
``INFORMATION_SCHEMA`` (full database schema state). Cross-server schema
parity is verified separately via targeted ``INFORMATION_SCHEMA.COLUMNS``
queries per server.

Usage
-----

::

    sudo -u pipeline /opt/pipeline/current/tools/capture_parity_baseline.py \\
        --pinned-by pipeline-lead --pipeline-version 1.0.0 \\
        --actor pipeline --justification "Phase 2 R1 dev baseline capture" \\
        --server dev

    # Dry-run preview without writing
    python3 tools/capture_parity_baseline.py \\
        --pinned-by pipeline-lead --pipeline-version 1.0.0 \\
        --actor pipeline --justification "preview" --server dev --dry-run

Exit codes (per D74)
--------------------

* 0 — clean (all probes succeeded; file written OR dry-run preview)
* 1 — warning (at least one probe raised; partial baseline captured with
  documented_exception auto-populated)
* 2 — fatal (output path not writable / insufficient permissions / SELinux
  context blocks write); file NOT written

Audit row (per D76)
-------------------

ONE row per invocation, ``EventType='CLI_CAPTURE_PARITY_BASELINE'``,
``Metadata`` JSON containing:

* ``actor``, ``justification``, ``server``, ``pinned_by``, ``pipeline_version``
* ``output_path``, ``dry_run``, ``exit_code``
* ``probes_failed_count``, ``capture_duration_ms``
* ``baseline_sha256`` (hash of captured baseline excluding ``pinned_at``)
* 4-axis classification per udm-execution-classifier:
  ``classification = {trigger: 'Manual', frequency: 'OneTimePerServer',
  idempotency: 'Yes', audit_family: 'CLI_CAPTURE_PARITY_BASELINE'}``

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: Manual CLI invocation by an operator (Phase 2 R1 dev/test/prod
  setup; on-demand re-capture if drift detected)
* **Frequency**: One-time per server during Phase 2 R1; re-capture on-demand
* **Idempotency**: YES — read-only probes; overwrite-only single output path
* **Audit-row family**: ``CLI_CAPTURE_PARITY_BASELINE``
* **Routing**: ``ONE_OFF_SCRIPTS.md`` "Active items" (one-time-per-server)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_load.parity_baseline_capture import (  # noqa: E402
    PROBE_FAILED_SENTINEL,
    UNAVAILABLE_SENTINEL,
    baseline_sha256,
    capture_baseline,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


TOOL_NAME = "capture_parity_baseline"
EVENT_TYPE = "CLI_CAPTURE_PARITY_BASELINE"
DEFAULT_OUTPUT_PATH = "/etc/pipeline/parity_baseline.json"


# ---------------------------------------------------------------------------
# Audit-row writer (best-effort; per D76 the row is MANDATORY but if DB write
# itself fails we still preserve the operator-facing stdout/stderr signal)
# ---------------------------------------------------------------------------

def _write_audit_row(metadata: dict, *, status: str, error_message: str | None = None) -> bool:
    """Insert one CLI_CAPTURE_PARITY_BASELINE row in PipelineEventLog.

    Returns True on success, False on failure. Failure is logged but does not
    propagate — the operator-facing exit code remains driven by the probe
    result, not the audit-write result. (Per D76 the audit row is mandatory
    semantics; a DB-write failure is itself an operator-visible warning via
    stderr.)
    """
    try:
        import utils.configuration as config
        from utils.connections import get_connection
    except Exception:
        logger.warning("Audit-row write skipped: utils.configuration / utils.connections unavailable")
        return False
    conn = None
    try:
        conn = get_connection(config.GENERAL_DB)
        try:
            conn.autocommit = False
        except Exception:
            pass
        cursor = conn.cursor()
        cursor.execute(
            f"INSERT INTO [{config.GENERAL_DB}].ops.PipelineEventLog "
            f"(BatchId, TableName, SourceName, EventType, EventDetail, "
            f" StartedAt, CompletedAt, Status, ErrorMessage, Metadata) "
            f"VALUES (NEXT VALUE FOR [{config.GENERAL_DB}].ops.PipelineBatchSequence, "
            f"        NULL, NULL, ?, ?, SYSUTCDATETIME(), SYSUTCDATETIME(), ?, ?, ?)",
            EVENT_TYPE,
            f"B183 parity baseline / server={metadata.get('server')}",
            status, error_message, json.dumps(metadata, separators=(",", ":")),
        )
        conn.commit()
        cursor.close()
        return True
    except Exception:
        logger.exception("Failed to write CLI_CAPTURE_PARITY_BASELINE audit row")
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _count_probes_failed(baseline: dict) -> int:
    """Count fields whose value is PROBE_FAILED_SENTINEL or UNAVAILABLE_SENTINEL.

    Counts recursive scalar leaves only; matches the auto-exception count
    populated by capture_baseline's ``documented_exceptions`` scan.
    """
    return len(baseline.get("documented_exceptions", []))


def _print_human_summary(baseline: dict, *, output_path: str, dry_run: bool) -> None:
    """Print the human-readable summary table per § 4 spec stdout example."""
    os_blk = baseline.get("operating_system", {})
    py_blk = baseline.get("python", {})
    nl_blk = baseline.get("native_libraries", {})
    env_blk = baseline.get("env_vars_required", {})
    fs_blk = baseline.get("filesystem_layout", [])
    sysd_blk = baseline.get("systemd_unit", {})
    tpm_blk = baseline.get("tpm2", {})
    cred_blk = baseline.get("credentials_envelope", {})
    utl_blk = baseline.get("udm_tables_list_schema", {})
    doc_exc = baseline.get("documented_exceptions", [])

    print(f"Parity baseline capture — pinned_by: {baseline.get('pinned_by')}")
    print(f"  schema_version              : {baseline.get('schema_version')}")
    print(f"  baseline_name               : {baseline.get('baseline_name')}")
    print(f"  pinned_at                   : {baseline.get('pinned_at')}")
    print(f"  pipeline_version            : {baseline.get('pipeline_version')}")
    print(f"  operating_system.distro     : {os_blk.get('distro')}")
    print(f"  operating_system.version    : {os_blk.get('version')}")
    print(f"  operating_system.kernel     : {os_blk.get('kernel')}")
    print(f"  python.version              : {py_blk.get('version')}")
    print(f"  python.pip_freeze_sha256    : {py_blk.get('pip_freeze_sha256')}")
    print(f"  native_libraries.oracle_*   : {nl_blk.get('oracle_instant_client_version')} @ "
          f"{nl_blk.get('oracle_instant_client_dir')}")
    print(f"  native_libraries.odbc_*     : {nl_blk.get('odbc_driver_version')} @ "
          f"{nl_blk.get('odbc_driver_name')}")
    print(f"  native_libraries.mssql_*    : {nl_blk.get('mssql_tools_version')} @ "
          f"{nl_blk.get('mssql_tools_dir')}")
    print(f"  native_libraries.gpg_version: {nl_blk.get('gpg_version')}")
    print(f"  env_vars_required           : {len(env_blk)} keys captured ({', '.join(env_blk.keys())})")
    print(f"  filesystem_layout           : {len(fs_blk)} paths captured (per R2 § 4.1)")
    print(f"  systemd_unit.sha256         : {sysd_blk.get('sha256')}")
    print(f"  tpm2.pcr_policy_hash        : {tpm_blk.get('pcr_policy_hash')}")
    print(f"  credentials_envelope.sha256 : {cred_blk.get('sha256')}")
    print(f"  udm_tables_list_schema.expected_columns_sha256: {utl_blk.get('expected_columns_sha256')}")
    print(f"  documented_exceptions       : {len(doc_exc)} "
          f"({'auto-populated probe gaps' if doc_exc else 'initial capture — operators add post-capture per R2 § 4.3'})")
    if dry_run:
        print(f"[DRY RUN] Baseline would be written to {output_path} (schema R2 § 4.1)")
    else:
        print(f"Baseline captured; output written to {output_path} (schema R2 § 4.1)")


def main(
    *,
    pinned_by: str,
    pipeline_version: str,
    actor: str,
    justification: str,
    server: str,
    output_path: str = DEFAULT_OUTPUT_PATH,
    baseline_name: str | None = None,
    probe_tpm2: bool = True,
    dry_run: bool = False,
    json_output: bool = False,
) -> dict:
    """CLI entry point per D76 audit-row contract.

    Returns the audit Metadata dict (also written to PipelineEventLog as
    ``Metadata`` column). Caller (CLI argv path) maps this to a process exit
    code via the ``exit_code`` key.
    """
    started_ms = time.perf_counter()
    metadata: dict = {
        "actor": actor,
        "justification": justification,
        "server": server,
        "pinned_by": pinned_by,
        "pipeline_version": pipeline_version,
        "output_path": output_path,
        "dry_run": dry_run,
        "exit_code": 0,
        "probes_failed_count": 0,
        "capture_duration_ms": 0,
        "baseline_sha256": None,
        "classification": {
            "trigger": "Manual",
            "frequency": "OneTimePerServer",
            "idempotency": "Yes",
            "audit_family": EVENT_TYPE,
        },
    }

    try:
        baseline = capture_baseline(
            output_path=output_path,
            pinned_by=pinned_by,
            pipeline_version=pipeline_version,
            dry_run=dry_run,
            baseline_name=baseline_name,
            probe_tpm2=probe_tpm2,
            server=server,
        )
    except PermissionError as exc:
        metadata["exit_code"] = 2
        metadata["error_type"] = "OutputPathNotWritableError"
        metadata["error_message"] = str(exc)
        elapsed_ms = int((time.perf_counter() - started_ms) * 1000)
        metadata["capture_duration_ms"] = elapsed_ms
        _write_audit_row(metadata, status="FAILED", error_message=str(exc))
        msg = (f"FAIL: output path {output_path} not writable; check ownership + mode "
               f"(expected pipeline:pipeline 0640 on /etc/pipeline/) — {exc}")
        print(msg, file=sys.stderr)
        return metadata
    except OSError as exc:
        # SELinux denial typically surfaces as PermissionError on RHEL but
        # generic OSError covers EROFS / ENOSPC / SELinux context mismatches.
        metadata["exit_code"] = 2
        metadata["error_type"] = "OutputPathNotWritableError"
        metadata["error_message"] = str(exc)
        elapsed_ms = int((time.perf_counter() - started_ms) * 1000)
        metadata["capture_duration_ms"] = elapsed_ms
        _write_audit_row(metadata, status="FAILED", error_message=str(exc))
        print(f"FAIL: write to {output_path} failed: {exc}", file=sys.stderr)
        return metadata
    except Exception as exc:
        metadata["exit_code"] = 2
        metadata["error_type"] = type(exc).__name__
        metadata["error_message"] = str(exc)
        elapsed_ms = int((time.perf_counter() - started_ms) * 1000)
        metadata["capture_duration_ms"] = elapsed_ms
        _write_audit_row(metadata, status="FAILED", error_message=traceback.format_exc()[:4000])
        print(f"FAIL: unexpected error: {exc}", file=sys.stderr)
        return metadata

    elapsed_ms = int((time.perf_counter() - started_ms) * 1000)
    probes_failed = _count_probes_failed(baseline)
    metadata["probes_failed_count"] = probes_failed
    metadata["capture_duration_ms"] = elapsed_ms
    metadata["baseline_sha256"] = baseline_sha256(baseline)
    # Exit 1 if any probe failed (warning-tier); exit 0 otherwise.
    metadata["exit_code"] = 1 if probes_failed > 0 else 0

    status = "SUCCESS"
    _write_audit_row(metadata, status=status)

    if json_output:
        print(json.dumps(baseline, indent=2, separators=(",", ": ")))
    else:
        _print_human_summary(baseline, output_path=output_path, dry_run=dry_run)
        if probes_failed > 0:
            print(f"WARNING: {probes_failed} probe(s) failed — see "
                  f"documented_exceptions entries for details (exit 1).", file=sys.stderr)

    return metadata


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture cross-server parity baseline JSON per Round 2 § 4.1 schema.",
    )
    # Tool-specific required args per § 4 spec
    parser.add_argument(
        "--pinned-by", required=True,
        help="R2 § 4.1 'pinned_by' — human-readable operator authorizing the capture.",
    )
    parser.add_argument(
        "--pipeline-version", required=True,
        help="R2 § 4.1 'pipeline_version' (e.g. '1.0.0').",
    )
    parser.add_argument(
        "--output-path", default=DEFAULT_OUTPUT_PATH,
        help=f"Output JSON path. Default: {DEFAULT_OUTPUT_PATH}",
    )
    parser.add_argument(
        "--baseline-name", default=None,
        help="Override default baseline_name (default: 'pipeline-baseline-v{pipeline_version}').",
    )
    parser.add_argument(
        "--no-tpm2", dest="probe_tpm2", action="store_false",
        help="Skip TPM2 probing; tpm2.pcr_policy_hash recorded as <unavailable>.",
    )
    # D75 canonical args
    parser.add_argument(
        "--actor", required=True,
        help="Operator running the tool (per D75); written to audit row Metadata.",
    )
    parser.add_argument(
        "--justification", required=True,
        help="Operator justification (per D75); written to audit row Metadata.",
    )
    parser.add_argument(
        "--server", required=True, choices=("dev", "test", "prod"),
        help="Target server tag (per D75 + § 4 spec).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run all probes + assemble baseline dict; do NOT write the output file.",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Emit captured baseline as JSON on stdout (instead of human summary).",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable DEBUG logging.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress INFO logging (errors still emitted).",
    )
    parser.set_defaults(probe_tpm2=True)
    return parser


def cli_main() -> int:
    """Argv entry point; maps Metadata.exit_code → process exit code."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif args.quiet:
        logging.getLogger().setLevel(logging.ERROR)

    metadata = main(
        pinned_by=args.pinned_by,
        pipeline_version=args.pipeline_version,
        actor=args.actor,
        justification=args.justification,
        server=args.server,
        output_path=args.output_path,
        baseline_name=args.baseline_name,
        probe_tpm2=args.probe_tpm2,
        dry_run=args.dry_run,
        json_output=args.json_output,
    )
    return int(metadata.get("exit_code", 2))


if __name__ == "__main__":
    sys.exit(cli_main())
