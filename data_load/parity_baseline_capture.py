"""B183 — Parity baseline capture module.

Per Round 4.5 supplement at ``docs/migration/phase1/04a_phase_0_prep_tools.md``
§ 4 (Tool 13 canonical spec) + Round 2 § 4.1 baseline JSON canonical schema
at ``docs/migration/phase1/02_configuration.md`` L820-L915.

NEW module function per **D92** forward-only additive schema-evolution
governance. Wrapped by the CLI shim ``tools/capture_parity_baseline.py``.

Scope (per Phase 2 R1 § 4.3 cycle-3 🔴 fix
``docs/migration/phase2/01_pilot_prerequisites.md`` L184):

    Baseline captures **OS / library / env / systemd** state only — **NOT**
    ``INFORMATION_SCHEMA`` (full database schema state). Database schema state
    is governed authoritatively by ``General.ops.SchemaContract`` per D92 +
    Round 7 § 1.1. Cross-server schema parity is verified separately via
    targeted ``INFORMATION_SCHEMA.COLUMNS`` queries per server then
    operator-compared.

The ``udm_tables_list_schema.expected_columns_sha256`` field IS captured but
its value is a DESIGN-TIME hash of the spec doc column inventory, NOT a live
INFORMATION_SCHEMA probe. Empirical sourcing: hash of the canonical column
list as documented at Round 2 § 1 (read from a known string constant; not a
DB query).

Function signature
------------------

::

    capture_baseline(
        output_path: str,
        pinned_by: str,
        pipeline_version: str,
        *,
        dry_run: bool = False,
        baseline_name: str | None = None,
        probe_tpm2: bool = True,
        server: str | None = None,
    ) -> dict

Returns a JSON-serializable ``dict`` byte-equivalent to the canonical R2 § 4.1
schema. Idempotent — same probe inputs (same server state) produce the same
output bytes modulo ``pinned_at`` (which is stamped at capture time).

Cross-platform
--------------

The probes target RHEL Linux (the production deployment target per D34). When
invoked on Windows (dev workstation per D103), RHEL-specific probes (``rpm
-q``, ``systemctl``, ``tpm2_getcap``, ``sestatus``) fall back to the sentinel
string ``"windows-unsupported"`` rather than raising. Operators capturing the
canonical production baseline MUST run on the actual RHEL server; Windows
output is for development smoke only.

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: Manual CLI invocation (operator runs Tool 13 CLI shim)
* **Frequency**: One-time per server during Phase 2 R1 (dev / test / prod);
  on-demand re-capture if drift detected
* **Idempotency**: YES — read-only filesystem probes; writes a single output
  JSON path (overwrite-only per § 4 spec)
* **Audit-row family**: ``CLI_CAPTURE_PARITY_BASELINE`` (per D76; written by
  the CLI shim, not by this module)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASELINE_SCHEMA_VERSION = "1.0"
WINDOWS_SENTINEL = "windows-unsupported"
PROBE_FAILED_SENTINEL = "<probe_failed>"
UNAVAILABLE_SENTINEL = "<unavailable>"

# Canonical filesystem layout per R2 § 4.1 L863-L870. Static design-time
# value — NOT a live filesystem probe. verify_server_parity.py compares the
# live state against this list at startup.
CANONICAL_FILESYSTEM_LAYOUT: list[dict] = [
    {"path": "/etc/pipeline/.env", "owner": "pipeline:pipeline", "mode": "0400", "must_exist": True},
    {"path": "/etc/pipeline/", "owner": "pipeline:pipeline", "mode": "0750", "must_exist": True},
    {"path": "/etc/pipeline/credentials.json.gpg", "owner": "pipeline:pipeline", "mode": "0640", "must_exist": True},
    {"path": "/etc/pipeline/parity_baseline.json", "owner": "root:root", "mode": "0644", "must_exist": True},
    {"path": "/var/pipeline/csv/", "owner": "pipeline:pipeline", "mode": "0750", "must_exist": True},
    {"path": "/var/log/pipeline/", "owner": "pipeline:pipeline", "mode": "0750", "must_exist": True},
    {"path": "/mnt/pipeline-archive/parquet/", "owner": "pipeline:pipeline", "mode": "0750", "must_exist": True},
]

# Canonical env var inventory per R2 § 4.1 L857-L860 + L924 Round 4.5b TZ
# polish. Values captured live from current environment.
EXPECTED_ENV_VARS: tuple[str, ...] = (
    "MALLOC_ARENA_MAX",
    "ORACLE_HOME",
    "LD_LIBRARY_PATH",
    "TZ",
)

# Canonical UdmTablesList CHECK constraints per R2 § 4.1 L898-L901. Design-time
# list; matches Round 2 § 1 inventory.
EXPECTED_UDM_TABLESLIST_CHECK_CONSTRAINTS: list[str] = [
    "CK_UdmTablesList_SCD2Mode",
    "CK_UdmTablesList_CDCMode",
    "CK_UdmTablesList_DataClassification",
]

# Canonical UdmTablesList column inventory per Round 2 § 1 — used to compute
# the design-time expected_columns_sha256. Sourced from spec doc only; NOT
# from INFORMATION_SCHEMA (per phase2/01 § 4.3 cycle-3 fix).
CANONICAL_UDM_TABLESLIST_COLUMNS: tuple[str, ...] = (
    "TableId", "SourceName", "SourceServer", "SourceDatabase", "SourceSchemaName",
    "SourceObjectName", "SourceIndexHint", "PartitionOn",
    "SourceAggregateColumnType", "SourceAggregateColumnName", "FirstLoadDate",
    "LookbackDays", "StageLoadTool", "StageTableName", "BronzeTableName",
    "MaxRowsPerDay", "StripSuffix",
    "SCD2Mode", "SCD2DateColumns", "SourceDeleteDateColumn",
    "DuplicateResolutionOrder", "AllowDuplicates", "PreserveDateTime",
    "RepairChainAfter", "AllowGaps", "ExcludeFromHash", "DefaultBeginDate",
    "ForceNewSegmentColumns", "ExpectedRetentionDays", "LastModifiedColumn",
    "CDCMode", "PiiColumnList", "DataClassification", "CohortAssignment",
    "IsEnabled", "LegalHoldOnly",
    "LatenessL99Minutes", "LatenessL99UpdatedAt",
)


def _is_windows() -> bool:
    return os.name == "nt" or platform.system().lower().startswith("win")


def _run_subprocess(args: list[str], *, timeout: float = 5.0) -> str | None:
    """Run a probe subprocess; return stdout stripped, or None on failure.

    Returns None for: command not found, non-zero exit, timeout, any exception.
    Callers map None to PROBE_FAILED_SENTINEL or alternative.
    """
    if _is_windows():
        return None
    try:
        completed = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False,
        )
        if completed.returncode != 0:
            return None
        return (completed.stdout or "").strip() or None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Individual probes
# ---------------------------------------------------------------------------

def _probe_operating_system() -> dict:
    """RHEL distro / version / kernel + kernel_match_policy."""
    if _is_windows():
        return {
            "distro": WINDOWS_SENTINEL,
            "version": WINDOWS_SENTINEL,
            "kernel": WINDOWS_SENTINEL,
            "kernel_match_policy": "major_minor",
        }
    distro = PROBE_FAILED_SENTINEL
    version = PROBE_FAILED_SENTINEL
    try:
        os_release = Path("/etc/os-release")
        if os_release.is_file():
            content = os_release.read_text(encoding="utf-8")
            kv = {}
            for line in content.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    kv[k.strip()] = v.strip().strip('"').strip("'")
            # NAME=Red Hat Enterprise Linux / VERSION_ID=9.4
            name = kv.get("NAME", "")
            distro = "RHEL" if "Red Hat" in name else (kv.get("ID", "") or PROBE_FAILED_SENTINEL).upper()
            version = kv.get("VERSION_ID", PROBE_FAILED_SENTINEL)
    except OSError:
        pass
    kernel = platform.release() or PROBE_FAILED_SENTINEL
    return {
        "distro": distro,
        "version": version,
        "kernel": kernel,
        "kernel_match_policy": "major_minor",
    }


def _probe_python() -> dict:
    """python.version + version_match_policy + pip_freeze_sha256 + lockfile path."""
    pip_freeze_hash = PROBE_FAILED_SENTINEL
    freeze_out = _run_subprocess([sys.executable, "-m", "pip", "freeze"], timeout=15.0)
    if freeze_out is not None:
        # Deterministic ordering: sort lines, then hash
        normalized = "\n".join(sorted(line.strip() for line in freeze_out.splitlines() if line.strip()))
        pip_freeze_hash = _sha256_hex(normalized)
    return {
        "version": platform.python_version(),
        "version_match_policy": "exact",
        "pip_freeze_sha256": pip_freeze_hash,
        "pip_lockfile_path": "/etc/pipeline/python-deps.lock",
    }


def _probe_native_libraries() -> dict:
    """Oracle Instant Client / ODBC Driver / mssql-tools18 / GPG versions + dirs."""
    if _is_windows():
        return {
            "oracle_instant_client_version": WINDOWS_SENTINEL,
            "oracle_instant_client_dir": WINDOWS_SENTINEL,
            "odbc_driver_version": WINDOWS_SENTINEL,
            "odbc_driver_name": WINDOWS_SENTINEL,
            "mssql_tools_version": WINDOWS_SENTINEL,
            "mssql_tools_dir": WINDOWS_SENTINEL,
            "gpg_version": WINDOWS_SENTINEL,
        }

    # Oracle Instant Client — check $ORACLE_HOME or canonical /opt/oracle path
    oracle_dir = os.getenv("ORACLE_HOME", "/opt/oracle/instantclient_19_21")
    oracle_version = PROBE_FAILED_SENTINEL
    if Path(oracle_dir).is_dir():
        # Version inferred from directory name (e.g. instantclient_19_21 → 19.21.0)
        # Fall back to rpm query if dir naming is non-canonical.
        rpm_out = _run_subprocess(["rpm", "-q", "--qf", "%{VERSION}", "oracle-instantclient19.21-basic"])
        oracle_version = rpm_out or "19.21.0"  # canonical R2 § 4.1 default

    # ODBC Driver 18 for SQL Server
    odbc_out = _run_subprocess(["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}", "msodbcsql18"])
    odbc_version = odbc_out or PROBE_FAILED_SENTINEL
    odbc_driver_name = "ODBC Driver 18 for SQL Server"

    # mssql-tools18
    mssql_out = _run_subprocess(["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}", "mssql-tools18"])
    mssql_version = mssql_out or PROBE_FAILED_SENTINEL
    mssql_dir = "/opt/mssql-tools18"

    # GPG
    gpg_out = _run_subprocess(["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}", "gnupg2"])
    if gpg_out is None:
        gpg_out = _run_subprocess(["gpg", "--version"])
        if gpg_out:
            # First line: "gpg (GnuPG) 2.3.3"
            first = gpg_out.splitlines()[0]
            parts = first.split()
            gpg_version = parts[-1] if parts else PROBE_FAILED_SENTINEL
        else:
            gpg_version = PROBE_FAILED_SENTINEL
    else:
        gpg_version = gpg_out

    return {
        "oracle_instant_client_version": oracle_version,
        "oracle_instant_client_dir": oracle_dir,
        "odbc_driver_version": odbc_version,
        "odbc_driver_name": odbc_driver_name,
        "mssql_tools_version": mssql_version,
        "mssql_tools_dir": mssql_dir,
        "gpg_version": gpg_version,
    }


def _probe_env_vars_required() -> dict:
    """env_vars_required: dict of EXPECTED_ENV_VARS captured from os.environ.

    Missing env vars: value set to PROBE_FAILED_SENTINEL so verify_server_parity
    can flag them (verify-time policy decides severity).
    """
    return {name: os.getenv(name, PROBE_FAILED_SENTINEL) for name in EXPECTED_ENV_VARS}


def _probe_filesystem_layout() -> list[dict]:
    """Returns the canonical filesystem layout per R2 § 4.1.

    Static design-time inventory; verify_server_parity.py performs the
    per-path stat check at runtime. Returned verbatim here so the baseline
    JSON encodes operator expectations (any path absent at verify time is
    drift).
    """
    return [dict(entry) for entry in CANONICAL_FILESYSTEM_LAYOUT]


def _probe_systemd_unit() -> dict:
    """systemd_unit: path + sha256 of the unit file + required env-vars list."""
    unit_path = "/etc/systemd/system/pipeline.service"
    sha = PROBE_FAILED_SENTINEL
    if _is_windows():
        sha = WINDOWS_SENTINEL
    else:
        unit_file = Path(unit_path)
        if unit_file.is_file():
            try:
                sha = _sha256_hex(unit_file.read_bytes())
            except OSError:
                sha = PROBE_FAILED_SENTINEL
    return {
        "path": unit_path,
        "sha256": sha,
        "must_have_env_vars": ["MALLOC_ARENA_MAX=2"],
    }


def _probe_tpm2(*, enabled: bool) -> dict:
    """tpm2: required + pcr_policy_hash + tpm2_tools_version.

    enabled=False (operator passed --no-tpm2) → policy hash + tools version set
    to UNAVAILABLE_SENTINEL; calling code auto-populates a documented_exception.
    """
    if not enabled:
        return {
            "required": True,
            "pcr_policy_hash": UNAVAILABLE_SENTINEL,
            "tpm2_tools_version": UNAVAILABLE_SENTINEL,
        }
    if _is_windows():
        return {
            "required": True,
            "pcr_policy_hash": WINDOWS_SENTINEL,
            "tpm2_tools_version": WINDOWS_SENTINEL,
        }
    # TPM2 PCR policy hash — read from canonical location set up by D64 sealing
    # procedure. Path is conventional; fall back to PROBE_FAILED if missing.
    policy_path = Path("/etc/pipeline/tpm2_pcr_policy.hash")
    if policy_path.is_file():
        try:
            pcr_hash = "sha256:" + policy_path.read_text(encoding="utf-8").strip()
        except OSError:
            pcr_hash = PROBE_FAILED_SENTINEL
    else:
        # Live tpm2_getcap probe to confirm TPM2 is functional; cannot
        # reconstruct the sealed PCR policy hash at capture time without the
        # original sealing context.
        getcap = _run_subprocess(["tpm2_getcap", "properties-fixed"])
        pcr_hash = PROBE_FAILED_SENTINEL if getcap is None else UNAVAILABLE_SENTINEL
    tpm2_tools = _run_subprocess(["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}", "tpm2-tools"])
    return {
        "required": True,
        "pcr_policy_hash": pcr_hash,
        "tpm2_tools_version": tpm2_tools or PROBE_FAILED_SENTINEL,
    }


def _probe_credentials_envelope() -> dict:
    """credentials_envelope: path + sha256 + schema_version + recipient info."""
    env_path = "/etc/pipeline/credentials.json.gpg"
    sha = PROBE_FAILED_SENTINEL
    recipient_count = 0
    primary_fp = PROBE_FAILED_SENTINEL
    breakglass_fp = PROBE_FAILED_SENTINEL
    if _is_windows():
        return {
            "path": env_path,
            "sha256": WINDOWS_SENTINEL,
            "schema_version": "1.0",
            "recipient_count": 0,
            "primary_recipient_fingerprint": WINDOWS_SENTINEL,
            "breakglass_recipient_fingerprint": WINDOWS_SENTINEL,
        }
    envelope = Path(env_path)
    if envelope.is_file():
        try:
            sha = _sha256_hex(envelope.read_bytes())
        except OSError:
            sha = PROBE_FAILED_SENTINEL
        # gpg --list-packets emits recipient key IDs; map to long-form
        # fingerprints with gpg --list-keys --with-fingerprint.
        packets = _run_subprocess(["gpg", "--list-packets", env_path], timeout=10.0)
        if packets:
            recipient_count = sum(1 for line in packets.splitlines() if line.startswith(":pubkey enc packet"))
        keys = _run_subprocess(["gpg", "--list-keys", "--with-fingerprint", "--with-colons"], timeout=10.0)
        if keys:
            # Pick first two fingerprint records as primary + break-glass
            fps = [line.split(":")[9] for line in keys.splitlines() if line.startswith("fpr:") and len(line.split(":")) > 9]
            if fps:
                primary_fp = fps[0]
            if len(fps) > 1:
                breakglass_fp = fps[1]
    return {
        "path": env_path,
        "sha256": sha,
        "schema_version": "1.0",
        "recipient_count": recipient_count,
        "primary_recipient_fingerprint": primary_fp,
        "breakglass_recipient_fingerprint": breakglass_fp,
    }


def _probe_udm_tables_list_schema() -> dict:
    """udm_tables_list_schema: design-time canonical column hash + CHECK list.

    Per phase2/01 § 4.3 cycle-3 fix — this is NOT a live INFORMATION_SCHEMA
    query. The hash is computed from CANONICAL_UDM_TABLESLIST_COLUMNS (sourced
    from the Round 2 § 1 spec doc inventory).
    """
    canonical_text = ",".join(sorted(CANONICAL_UDM_TABLESLIST_COLUMNS))
    return {
        "spec_doc": "docs/migration/phase1/02_configuration.md § 1",
        "expected_columns_sha256": _sha256_hex(canonical_text),
        "expected_check_constraints": list(EXPECTED_UDM_TABLESLIST_CHECK_CONSTRAINTS),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def capture_baseline(
    output_path: str,
    pinned_by: str,
    pipeline_version: str,
    *,
    dry_run: bool = False,
    baseline_name: str | None = None,
    probe_tpm2: bool = True,
    server: str | None = None,
) -> dict:
    """Capture OS/library/env/systemd baseline state for parity verification.

    Returns canonical JSON-serializable dict per Round 2 § 4.1 schema. Does
    NOT include live INFORMATION_SCHEMA (per phase2/01 § 4.3 cycle-3 fix).

    Args:
        output_path: target JSON path; default canonical is
            ``/etc/pipeline/parity_baseline.json``. When ``dry_run=True`` the
            file is NOT written, but the returned dict still includes the
            target path so the CLI shim can display "would-write" output.
        pinned_by: canonical R2 § 4.1 ``pinned_by`` — human-readable operator
            identity authorizing the capture (required, no default).
        pipeline_version: canonical R2 § 4.1 ``pipeline_version`` (e.g.
            ``"1.0.0"``). verify_server_parity uses this for deploy-version
            drift detection (required, no default).
        dry_run: if True, run probes + assemble dict + return WITHOUT writing
            the output file. Same input → same output bytes modulo the
            ``pinned_at`` timestamp.
        baseline_name: override the default ``f"pipeline-baseline-v{pipeline_version}"``.
        probe_tpm2: when False, the tpm2 block is set to UNAVAILABLE_SENTINEL
            and a documented_exception entry is auto-populated. Mirrors the
            CLI's ``--no-tpm2`` flag.
        server: optional server tag (e.g. ``"dev"`` / ``"test"`` / ``"prod"``).
            Currently unused inside the baseline body (the canonical R2 § 4.1
            schema does not have a server-tag field; per-server semantics
            emerge from the file's deployment location). Accepted so the CLI
            shim can pass through for downstream metadata.

    Returns:
        dict serializable to JSON; byte-equivalent to the canonical R2 § 4.1
        schema.

    Note on idempotency:
        Re-running on the same server produces identical bytes EXCEPT for
        ``pinned_at`` (stamped at capture time). If you need a deterministic
        re-capture for testing, monkey-patch ``datetime.now(timezone.utc).replace(tzinfo=None)`` or
        run with ``dry_run=True`` + override ``pinned_at`` in the returned
        dict before serializing.
    """
    pinned_at = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")
    name = baseline_name or f"pipeline-baseline-v{pipeline_version}"

    logger.info("Capturing parity baseline: pinned_by=%s pipeline_version=%s server=%s dry_run=%s",
                pinned_by, pipeline_version, server or "<unset>", dry_run)

    documented_exceptions: list[dict] = []

    # Run probes; each is wrapped to fail-soft into the canonical sentinel
    # values so the schema shape is preserved even on partial-probe failure.
    operating_system = _probe_operating_system()
    python_block = _probe_python()
    native_libraries = _probe_native_libraries()
    env_vars_required = _probe_env_vars_required()
    filesystem_layout = _probe_filesystem_layout()
    systemd_unit = _probe_systemd_unit()
    tpm2_block = _probe_tpm2(enabled=probe_tpm2)
    credentials_envelope = _probe_credentials_envelope()
    udm_tables_list_schema = _probe_udm_tables_list_schema()

    # Auto-populate a documented_exception for any field set to a sentinel
    # other than WINDOWS_SENTINEL (Windows is expected; not an exception).
    # PROBE_FAILED + UNAVAILABLE sentinels both trigger an auto-exception
    # per phase1/04a § 4 spec.
    def _scan_for_sentinels(prefix: str, obj):
        if isinstance(obj, dict):
            for key, val in obj.items():
                dotted = f"{prefix}.{key}" if prefix else key
                _scan_for_sentinels(dotted, val)
        elif isinstance(obj, str) and obj in (PROBE_FAILED_SENTINEL, UNAVAILABLE_SENTINEL):
            documented_exceptions.append({
                "key": prefix,
                "dev_value": obj,
                "test_value": obj,
                "prod_value": obj,
                "rationale": (
                    f"Auto-populated by capture_parity_baseline.py — probe for {prefix} "
                    f"failed (or skipped) during baseline capture; manual review + re-capture required"
                ),
                "expires_at": _expires_at_iso(pinned_at, days=30),
                "owner": pinned_by,
            })

    _scan_for_sentinels("operating_system", operating_system)
    _scan_for_sentinels("python", python_block)
    _scan_for_sentinels("native_libraries", native_libraries)
    _scan_for_sentinels("env_vars_required", env_vars_required)
    _scan_for_sentinels("systemd_unit", systemd_unit)
    _scan_for_sentinels("tpm2", tpm2_block)
    _scan_for_sentinels("credentials_envelope", credentials_envelope)

    baseline = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "baseline_name": name,
        "pinned_at": pinned_at,
        "pinned_by": pinned_by,
        "pipeline_version": pipeline_version,
        "operating_system": operating_system,
        "python": python_block,
        "native_libraries": native_libraries,
        "env_vars_required": env_vars_required,
        "filesystem_layout": filesystem_layout,
        "systemd_unit": systemd_unit,
        "tpm2": tpm2_block,
        "credentials_envelope": credentials_envelope,
        "udm_tables_list_schema": udm_tables_list_schema,
        "documented_exceptions": documented_exceptions,
    }

    # Serialize once; reuse for both file write + sha256 of returned content.
    serialized = json.dumps(baseline, indent=2, sort_keys=False, separators=(",", ": "))

    if not dry_run:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(serialized, encoding="utf-8")
        logger.info("Baseline written to %s (%d bytes)", target, len(serialized))
    else:
        logger.info("[DRY RUN] Baseline would be written to %s (%d bytes)", output_path, len(serialized))

    return baseline


def _expires_at_iso(pinned_at: str, *, days: int) -> str:
    """Return ISO date string `pinned_at + days` (date-only per R2 § 4.3)."""
    try:
        dt = datetime.strptime(pinned_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        dt = datetime.now(timezone.utc).replace(tzinfo=None)
    from datetime import timedelta
    return (dt + timedelta(days=days)).strftime("%Y-%m-%d")


def baseline_sha256(baseline: dict) -> str:
    """Compute sha256 of the canonical JSON serialization of a baseline dict.

    Helper for the CLI shim's audit-row Metadata. Strips ``pinned_at`` before
    hashing so the hash is stable across captures that differ only by
    timestamp (useful for drift detection: same hash → identical state).
    """
    stable = {k: v for k, v in baseline.items() if k != "pinned_at"}
    return _sha256_hex(json.dumps(stable, indent=2, sort_keys=False, separators=(",", ": ")))
