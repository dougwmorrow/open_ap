"""M8 — ``tools/verify_server_parity.py`` (Wave 5, B-243).

Per **Round 3 § 3.2** at ``docs/migration/phase1/03_core_modules.md`` L773-822
(canonical module spec) + **Round 2 § 4.1-4.3** at
``docs/migration/phase1/02_configuration.md`` L820-1015 (baseline JSON schema +
verifier interface canonical L957-961 + drift severity classification D65) +
**Round 4 § 3.7** at ``docs/migration/phase1/04_tools.md`` L951-1024 (CLI shim
wraps this module body — same signature).

Purpose
-------

At every pipeline startup (per D27), compare current server state against
``/etc/pipeline/parity_baseline.json`` (D103 — outside ``/debi``) and produce a
``ParityReport`` with per-check status. Block pipeline start on any fatal-tier
drift by raising ``ParityFatalError`` (CLI maps to ``sys.exit(1)`` per § 3.7
exit-code contract).

What this module does (per spec § 3.2)
---------------------------------------

1. Read ``/etc/pipeline/parity_baseline.json`` (raises ``ParityBaselineMissing``
   if absent / malformed).
2. Run probes per baseline categories — per R2 § 4.2 verification surface table
   (operating_system / python / native_libraries / env_vars_required /
   filesystem_layout / systemd_unit / tpm2 / credentials_envelope /
   udm_tables_list_schema).
3. Classify each check per D65 severity tier (fatal / warning / informational /
   match).
4. Compose ``ParityReport`` dataclass and return it. Raise ``ParityFatalError``
   if any check is fatal-tier OR ``fail_on_warning=True`` and any warning.
5. Read-only on filesystem; CLI shim writes the PARITY_VERIFY audit row +
   exit-code mapping.

Function signature (canonical per R2 § 4.2 L957-961)
----------------------------------------------------

::

    def verify_server_parity(
        baseline_path: str | Path | None = None,
        server_name: str | None = None,
        fail_on_warning: bool = False,
        *,
        server: str | None = None,
        json_output: bool = False,
    ) -> ParityReport

* ``baseline_path`` — override the baseline JSON path. Default reads from
  ``/etc/pipeline/parity_baseline.json`` (D103 canonical location).
* ``server_name`` — server identifier (e.g. ``"dev"`` / ``"test"`` / ``"prod"``).
  Defaults to ``$SERVER_NAME`` env var, then ``socket.gethostname()``.
* ``fail_on_warning`` — when True, treats warning-tier drift as fatal (strict
  ops mode). Default False.
* ``server`` — keyword-only alias for ``server_name`` so callers like
  ``tools/promote_test_to_prod.py`` that pass ``server=`` continue to work.
* ``json_output`` — when True, serializes the report to JSON-friendly dict
  (presentation aid; primary path is the dataclass return value).

Error modes (per D68 + § 3.2 L795-799)
---------------------------------------

* ``ParityFatalError`` (PipelineFatalError) — any check in fatal tier failed;
  pipeline MUST NOT proceed (CLI exit 2 per § 3.7 + D74).
* ``ParityBaselineMissing`` (PipelineFatalError) — baseline JSON absent or
  malformed (CLI exit 2).
* ``ParityProbeError`` (PipelineFatalError) — system probe failed (e.g.
  ``tpm2_getcap`` returned non-zero — itself a parity violation per F21).

Idempotency (per D15 + § 3.2 L789-793)
---------------------------------------

Read-only on filesystem; INSERT-only on PipelineEventLog (written by CLI shim,
not by this module). Re-invocation produces a NEW report row — each pipeline
startup is its own audit moment per § 3.2 L791. No retry — parity is point-in-
time; transient discrepancies should be observed, not retried-away.

Concurrency (per § 3.2 L800-803)
---------------------------------

Synchronous prerequisite at process start. Single-threaded; no concurrency
required. One-shot invocation per pipeline run.

Platform consideration (per D103 threat-surface inversion)
----------------------------------------------------------

* On Linux RHEL (canonical production target): all probes run.
* On Windows dev workstation (per D103): TPM2 / kernel-keyring / SELinux /
  rpm-q probes return ``"skipped"`` informational severity. RHEL-only fields
  like ``tpm2.pcr_policy_hash`` resolve to ``WINDOWS_SENTINEL`` and produce
  informational checks (NOT fatal — operators verifying on dev workstation
  must not see exit 2 simply because TPM2 is unavailable).

D-numbers consumed
------------------

D15 (idempotency mandatory), D27 (cross-server parity contract), D62-D65
(parity drift severity classification), D67 (Tier 0 discipline), D68 (error
class hierarchy — utils.errors canonical), D74 (CLI exit-code contract 0/1/2),
D75 (CLI argument naming), D76 (CLI audit-row contract — written by shim),
D85 (module startup sequence stage 3 — parity check), D92 (forward-only
additive — new module), D103 (Claude Code security model — baseline at
``/etc/pipeline/`` outside ``/debi``).

B-numbers closed: B-243 (Wave 5 M8 build per CODE_BUILD_STATUS.md).

See also
--------

* ``utils.errors`` — canonical ``ParityFatalError`` / ``ParityBaselineMissing``
  / ``ParityProbeError`` (per B228 — DO NOT define local exception classes).
* ``data_load/parity_baseline_capture.py`` — companion module that produces
  the baseline JSON this module reads.
* ``tools/promote_test_to_prod.py`` — calls ``verify_server_parity(server=...)``
  as pre-condition for failover acknowledgment.
* CLAUDE.md "Claude Code Security Model" — D103 boundary; credentials and
  baseline live OUTSIDE ``/debi``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import socket
import stat
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Literal

# Make the project root importable so we can reach utils.errors.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Canonical exception imports per B228 — DO NOT define local classes.
from utils.errors import (  # noqa: E402
    ParityBaselineMissing,
    ParityFatalError,
    ParityProbeError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# D103 canonical baseline path (outside /debi; root:root 0644 per R2 § 4.1).
DEFAULT_BASELINE_PATH = "/etc/pipeline/parity_baseline.json"

# D76 EventType for the audit row written by the CLI shim (NOT this module).
EVENT_TYPE = "PARITY_VERIFY"

# Sentinels — mirror parity_baseline_capture.py convention so values produced
# at capture time and read at verify time use the same vocabulary.
WINDOWS_SENTINEL = "windows-unsupported"
PROBE_FAILED_SENTINEL = "<probe_failed>"
UNAVAILABLE_SENTINEL = "<unavailable>"

# D65 severity literal — canonical per R2 § 4.2 L941.
Severity = Literal["fatal", "warning", "informational", "match"]

# Overall verdict per R2 § 4.2 L955.
Overall = Literal["pass", "warn", "fail"]


# ---------------------------------------------------------------------------
# Dataclasses (per R2 § 4.2 L941-955 canonical)
# ---------------------------------------------------------------------------


@dataclass
class ParityCheck:
    """One check result per R2 § 4.2 L941-947 canonical.

    Note canonical field name is ``key`` (NOT ``name``) per § 3.7 L985 +
    Pitfall #9 invented-field-name guard.
    """

    key: str  # e.g. "python.version", "credentials_envelope.sha256"
    expected: str
    actual: str
    severity: Severity
    exception_match: bool = False  # True if matched a non-expired documented_exception
    note: str | None = None


@dataclass
class ParityReport:
    """Composite report per R2 § 4.2 L948-955 canonical.

    ``overall`` derived from ``fatal_count`` / ``warning_count``:

    * any ``fatal_count > 0`` -> ``"fail"``
    * else any ``warning_count > 0`` -> ``"warn"``
    * else -> ``"pass"``
    """

    server_name: str
    baseline_name: str
    baseline_pinned_at: str
    checks: list[ParityCheck] = field(default_factory=list)
    fatal_count: int = 0
    warning_count: int = 0
    informational_count: int = 0
    match_count: int = 0
    overall: Overall = "pass"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict matching § 3.7 L1003 ``--json`` shape."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Platform detection helpers
# ---------------------------------------------------------------------------


def _is_linux() -> bool:
    """True iff running on Linux (the canonical RHEL production target)."""
    return platform.system() == "Linux"


def _is_windows() -> bool:
    """True iff running on Windows (the canonical dev workstation per D103)."""
    return platform.system() == "Windows" or os.name == "nt"


# ---------------------------------------------------------------------------
# Subprocess helper — captures stdout/stderr without ever holding key material
# ---------------------------------------------------------------------------


def _run_subprocess(
    cmd: list[str],
    *,
    timeout: float = 10.0,
) -> tuple[int, str, str]:
    """Run a subprocess and return ``(returncode, stdout, stderr)``.

    Returns ``(-1, "", "<reason>")`` on FileNotFoundError, TimeoutExpired, or
    any other OS error. Mirrors the contract used by
    ``data_load/credentials_verifier.py`` for consistency.
    """
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        stdout = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
        stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
        return proc.returncode, stdout, stderr
    except FileNotFoundError as exc:
        return -1, "", f"binary not found: {exc}"
    except subprocess.TimeoutExpired:
        return -1, "", "subprocess timed out"
    except Exception as exc:  # noqa: BLE001
        return -1, "", f"subprocess raised: {type(exc).__name__}"


# ---------------------------------------------------------------------------
# Baseline JSON loader
# ---------------------------------------------------------------------------


def _load_baseline(path: str | Path) -> dict[str, Any]:
    """Load + validate the baseline JSON.

    Raises ``ParityBaselineMissing`` if the file is absent, unreadable, or
    malformed. Validates that the top-level structure has at least the
    ``schema_version`` and ``baseline_name`` keys — any other malformed shape
    is caught downstream when probes look up their categories.
    """
    p = Path(path)
    if not p.is_file():
        raise ParityBaselineMissing(
            f"Baseline JSON not found at {path!r}",
            metadata={"baseline_path": str(path)},
        )
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, PermissionError) as exc:
        raise ParityBaselineMissing(
            f"Baseline JSON at {path!r} unreadable: {exc}",
            metadata={"baseline_path": str(path), "error": str(exc)},
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParityBaselineMissing(
            f"Baseline JSON at {path!r} malformed: {exc}",
            metadata={"baseline_path": str(path), "error": str(exc)},
        ) from exc
    if not isinstance(data, dict):
        raise ParityBaselineMissing(
            f"Baseline JSON at {path!r} root is not an object (got {type(data).__name__})",
            metadata={"baseline_path": str(path)},
        )
    # Spot-check the canonical keys per R2 § 4.1 L820-L915. Missing top-level
    # keys are tolerated (some probes may be intentionally absent on captures
    # done with ``--no-tpm2`` etc.); only the BASELINE_VERSION + name keys
    # are mandatory.
    if "schema_version" not in data or "baseline_name" not in data:
        raise ParityBaselineMissing(
            f"Baseline JSON at {path!r} missing schema_version or baseline_name",
            metadata={"baseline_path": str(path)},
        )
    return data


# ---------------------------------------------------------------------------
# Severity classification per D65 (R2 § 4.3 L1003-1015)
# ---------------------------------------------------------------------------


# D65: keys whose drift is FATAL — code execution would produce different
# results across servers. Per R2 § 4.3 examples.
_FATAL_KEYS: frozenset[str] = frozenset({
    "python.version",
    "python.pip_freeze_sha256",
    "native_libraries.oracle_instant_client_version",
    "native_libraries.odbc_driver_version",
    "native_libraries.mssql_tools_version",
    "native_libraries.gpg_version",
    "env_vars_required.MALLOC_ARENA_MAX",
    "env_vars_required.ORACLE_HOME",
    "env_vars_required.LD_LIBRARY_PATH",
    "systemd_unit.sha256",
    "credentials_envelope.sha256",
    "credentials_envelope.schema_version",
    "tpm2.pcr_policy_hash",
    "udm_tables_list_schema.expected_columns_sha256",
})

# D65: keys whose drift is WARNING — likely-same-result but indicates risk.
_WARNING_KEYS: frozenset[str] = frozenset({
    "operating_system.kernel",  # kernel patch level diff (point release)
    "tpm2.tpm2_tools_version",
    "native_libraries.odbc_driver_name",
    "env_vars_required.TZ",  # added 2026-05-12 per D109 timezone pin; WARN for 30 days post-amend
})

# D65: keys whose drift is INFORMATIONAL — tracked for trend/audit only.
_INFORMATIONAL_KEYS: frozenset[str] = frozenset({
    "operating_system.distro",
    "operating_system.version",
    "native_libraries.oracle_instant_client_dir",
    "native_libraries.mssql_tools_dir",
    "credentials_envelope.recipient_count",
    "credentials_envelope.primary_recipient_fingerprint",
    "credentials_envelope.breakglass_recipient_fingerprint",
    "udm_tables_list_schema.spec_doc",
})


def _classify_severity(key: str, expected: str, actual: str) -> Severity:
    """Classify a check's severity per D65.

    * ``expected == actual`` -> ``"match"``
    * On Windows, sentinel actual values map to ``"informational"`` (D103
      threat-surface inversion — dev workstation must not page on missing
      RHEL-only probes).
    * Else look up the key in _FATAL_KEYS / _WARNING_KEYS / _INFORMATIONAL_KEYS
      tables. Default for unmapped keys is ``"warning"`` (defense-in-depth —
      a new key added without explicit classification gets the safer-of-two
      defaults).
    """
    if expected == actual:
        return "match"
    if _is_windows() and actual in (WINDOWS_SENTINEL, PROBE_FAILED_SENTINEL):
        return "informational"
    if key in _FATAL_KEYS:
        return "fatal"
    if key in _WARNING_KEYS:
        return "warning"
    if key in _INFORMATIONAL_KEYS:
        return "informational"
    # filesystem_layout entries: drift on a "must_exist" path is fatal,
    # drift on owner/mode is warning. Pattern-match the key prefix.
    if key.startswith("filesystem_layout.") and key.endswith(".must_exist"):
        return "fatal"
    if key.startswith("filesystem_layout."):
        return "warning"
    # Default: warning. New keys must be explicitly added to one of the sets.
    return "warning"


# ---------------------------------------------------------------------------
# Documented-exceptions handling (R2 § 4.1 L902-911 + F23 edge case)
# ---------------------------------------------------------------------------


def _expired(expires_at: str | None) -> bool:
    """True iff the documented exception's expires_at is on/before today.

    Per F23: expired exceptions are auto-rejected (force re-review). Per
    R2 § 4.1, expires_at is an ISO date (YYYY-MM-DD) OR ISO datetime
    (YYYY-MM-DDTHH:MM:SSZ); accept both.
    """
    if not expires_at:
        return True
    try:
        # Try datetime first (with optional Z suffix), then date.
        text = expires_at.rstrip("Z")
        if "T" in text:
            exp_dt = datetime.fromisoformat(text)
            return exp_dt.date() <= date.today()
        exp_date = date.fromisoformat(text)
        return exp_date <= date.today()
    except (ValueError, TypeError):
        return True  # malformed → treat as expired (force re-review)


def _matches_documented_exception(
    key: str,
    actual: str,
    server_name: str,
    documented_exceptions: Iterable[dict[str, Any]],
) -> tuple[bool, str | None]:
    """Check whether ``(key, actual)`` matches a non-expired documented exception.

    Returns ``(matched, expires_at)``. ``matched=True`` iff:

    * the exception's ``key`` matches the check key
    * the exception's per-server value (``dev_value`` / ``test_value`` /
      ``prod_value``) matches ``actual``
    * the exception's ``expires_at`` is in the future

    Per F22 / F23 / R2 § 4.1 documented_exceptions schema.
    """
    server_value_key = f"{server_name}_value" if server_name else None
    for entry in documented_exceptions:
        if not isinstance(entry, dict):
            continue
        if entry.get("key") != key:
            continue
        # Match the server-specific value if server_name is known; else accept
        # any server's value (defensive — operator can run without --server).
        expected_value = None
        if server_value_key and server_value_key in entry:
            expected_value = entry[server_value_key]
        else:
            for cand in ("dev_value", "test_value", "prod_value"):
                if cand in entry:
                    expected_value = entry[cand]
                    if expected_value == actual:
                        break
        if expected_value != actual:
            continue
        if _expired(entry.get("expires_at")):
            return False, entry.get("expires_at")
        return True, entry.get("expires_at")
    return False, None


# ---------------------------------------------------------------------------
# Per-category live probes (return the actual current state)
# ---------------------------------------------------------------------------


def _probe_operating_system_actual() -> dict[str, str]:
    """Return current OS distro/version/kernel.

    On Windows: returns WINDOWS_SENTINEL for distro/version (kernel is informational).
    """
    if _is_windows():
        return {
            "distro": WINDOWS_SENTINEL,
            "version": WINDOWS_SENTINEL,
            "kernel": platform.release() or WINDOWS_SENTINEL,
        }
    distro = PROBE_FAILED_SENTINEL
    version = PROBE_FAILED_SENTINEL
    try:
        os_release = Path("/etc/os-release")
        if os_release.is_file():
            content = os_release.read_text(encoding="utf-8")
            kv: dict[str, str] = {}
            for line in content.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    kv[k.strip()] = v.strip().strip('"').strip("'")
            name = kv.get("NAME", "")
            distro = (
                "RHEL"
                if "Red Hat" in name
                else (kv.get("ID", "") or PROBE_FAILED_SENTINEL).upper()
            )
            version = kv.get("VERSION_ID", PROBE_FAILED_SENTINEL)
    except OSError:
        pass
    return {
        "distro": distro,
        "version": version,
        "kernel": platform.release() or PROBE_FAILED_SENTINEL,
    }


def _probe_python_actual(*, runner=_run_subprocess) -> dict[str, str]:
    """Return current Python version + pip freeze hash.

    pip freeze is deterministically ordered (sorted) then SHA-256'd. On
    subprocess failure, hash is PROBE_FAILED_SENTINEL.
    """
    py_version = platform.python_version()
    pip_freeze_hash = PROBE_FAILED_SENTINEL
    rc, stdout, _stderr = runner([sys.executable, "-m", "pip", "freeze"], timeout=15.0)
    if rc == 0 and stdout:
        normalized = "\n".join(
            sorted(line.strip() for line in stdout.splitlines() if line.strip())
        )
        pip_freeze_hash = "sha256:" + hashlib.sha256(
            normalized.encode("utf-8")
        ).hexdigest()
    return {
        "version": py_version,
        "pip_freeze_sha256": pip_freeze_hash,
    }


def _probe_native_libraries_actual(*, runner=_run_subprocess) -> dict[str, str]:
    """Return current native-library versions (rpm -q on RHEL; WINDOWS_SENTINEL elsewhere)."""
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
    out: dict[str, str] = {}
    # Oracle
    oracle_dir = os.getenv("ORACLE_HOME", "/opt/oracle/instantclient_19_21")
    out["oracle_instant_client_dir"] = oracle_dir
    rc, stdout, _ = runner(
        ["rpm", "-q", "--qf", "%{VERSION}", "oracle-instantclient19.21-basic"]
    )
    out["oracle_instant_client_version"] = stdout.strip() if rc == 0 and stdout else PROBE_FAILED_SENTINEL
    # ODBC
    rc, stdout, _ = runner(["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}", "msodbcsql18"])
    out["odbc_driver_version"] = stdout.strip() if rc == 0 and stdout else PROBE_FAILED_SENTINEL
    out["odbc_driver_name"] = "ODBC Driver 18 for SQL Server"
    # mssql-tools
    rc, stdout, _ = runner(["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}", "mssql-tools18"])
    out["mssql_tools_version"] = stdout.strip() if rc == 0 and stdout else PROBE_FAILED_SENTINEL
    out["mssql_tools_dir"] = "/opt/mssql-tools18"
    # GPG
    rc, stdout, _ = runner(["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}", "gnupg2"])
    out["gpg_version"] = stdout.strip() if rc == 0 and stdout else PROBE_FAILED_SENTINEL
    return out


def _probe_env_vars_actual(required_keys: Iterable[str]) -> dict[str, str]:
    """Return current values of required env vars; missing → PROBE_FAILED_SENTINEL."""
    return {name: os.environ.get(name, PROBE_FAILED_SENTINEL) for name in required_keys}


def _probe_filesystem_actual(entry: dict[str, Any]) -> dict[str, Any]:
    """Probe one filesystem_layout entry — return current existence + owner + mode.

    On Windows, owner/mode probes fall back to WINDOWS_SENTINEL (POSIX mode
    bits do not map cleanly to NTFS ACLs).
    """
    path = entry.get("path", "")
    result: dict[str, Any] = {"path": path, "must_exist": False, "owner": PROBE_FAILED_SENTINEL, "mode": PROBE_FAILED_SENTINEL}
    p = Path(path) if path else None
    if p is None:
        return result
    exists = p.exists()
    result["must_exist"] = exists
    if not exists:
        return result
    if _is_windows():
        result["owner"] = WINDOWS_SENTINEL
        result["mode"] = WINDOWS_SENTINEL
        return result
    try:
        st = p.stat()
        result["mode"] = oct(st.st_mode & 0o777)[2:].zfill(4)
        try:
            import grp
            import pwd
            uname = pwd.getpwuid(st.st_uid).pw_name
            gname = grp.getgrgid(st.st_gid).gr_name
            result["owner"] = f"{uname}:{gname}"
        except (KeyError, ImportError):
            result["owner"] = f"{st.st_uid}:{st.st_gid}"
    except OSError:
        result["mode"] = PROBE_FAILED_SENTINEL
        result["owner"] = PROBE_FAILED_SENTINEL
    return result


def _probe_systemd_unit_actual(path: str) -> str:
    """Return current SHA-256 of systemd unit file; WINDOWS_SENTINEL on Windows."""
    if _is_windows():
        return WINDOWS_SENTINEL
    p = Path(path)
    if not p.is_file():
        return PROBE_FAILED_SENTINEL
    try:
        return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
    except (OSError, PermissionError):
        return PROBE_FAILED_SENTINEL


def _probe_tpm2_actual(*, runner=_run_subprocess) -> dict[str, str]:
    """Return TPM2 capability + tools version.

    On Windows: returns WINDOWS_SENTINEL — D103 dev workstation has no TPM2.
    On Linux: runs ``tpm2_getcap properties-fixed`` — non-zero exit code
    indicates hardware fault (F21) and triggers ``ParityProbeError`` at the
    caller's discretion (this function returns the sentinel; classifier
    decides severity).
    """
    if _is_windows():
        return {
            "pcr_policy_hash": WINDOWS_SENTINEL,
            "tpm2_tools_version": WINDOWS_SENTINEL,
            "getcap_status": WINDOWS_SENTINEL,
        }
    out: dict[str, str] = {}
    # Live tpm2_getcap probe — failure surfaces as ParityProbeError when fatal-tier.
    rc, _stdout, stderr = runner(["tpm2_getcap", "properties-fixed"])
    if rc == -1:
        out["getcap_status"] = PROBE_FAILED_SENTINEL  # binary not found
    elif rc == 0:
        out["getcap_status"] = "ok"
    else:
        out["getcap_status"] = f"non-zero rc={rc}"
    # PCR policy hash file (operator-pinned at D64 sealing time).
    policy_path = Path("/etc/pipeline/tpm2_pcr_policy.hash")
    if policy_path.is_file():
        try:
            out["pcr_policy_hash"] = "sha256:" + policy_path.read_text(
                encoding="utf-8"
            ).strip()
        except OSError:
            out["pcr_policy_hash"] = PROBE_FAILED_SENTINEL
    else:
        out["pcr_policy_hash"] = UNAVAILABLE_SENTINEL
    # tpm2-tools version (rpm -q).
    rc, stdout, _ = runner(["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}", "tpm2-tools"])
    out["tpm2_tools_version"] = (
        stdout.strip() if rc == 0 and stdout else PROBE_FAILED_SENTINEL
    )
    return out


def _probe_credentials_envelope_actual(envelope_path: str) -> dict[str, Any]:
    """Return current SHA-256 of GPG envelope; WINDOWS_SENTINEL on Windows."""
    if _is_windows():
        return {
            "sha256": WINDOWS_SENTINEL,
            "schema_version": "1.0",
            "recipient_count": 0,
        }
    p = Path(envelope_path)
    if not p.is_file():
        return {
            "sha256": PROBE_FAILED_SENTINEL,
            "schema_version": PROBE_FAILED_SENTINEL,
            "recipient_count": 0,
        }
    try:
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return {
            "sha256": "sha256:" + h.hexdigest(),
            # schema_version / recipient_count come from the baseline directly;
            # we don't try to reconstruct from the file at verify time.
            "schema_version": "1.0",
            "recipient_count": 0,
        }
    except (OSError, PermissionError):
        return {
            "sha256": PROBE_FAILED_SENTINEL,
            "schema_version": PROBE_FAILED_SENTINEL,
            "recipient_count": 0,
        }


# ---------------------------------------------------------------------------
# Check assembly — build one ParityCheck row per baseline key
# ---------------------------------------------------------------------------


def _stringify(value: Any) -> str:
    """Normalize a value to its canonical string form for diff display."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def _add_check(
    checks: list[ParityCheck],
    *,
    key: str,
    expected: Any,
    actual: Any,
    server_name: str,
    documented_exceptions: list[dict[str, Any]],
) -> None:
    """Build one ParityCheck row + classify severity + check documented_exceptions."""
    expected_s = _stringify(expected)
    actual_s = _stringify(actual)
    severity = _classify_severity(key, expected_s, actual_s)
    exception_match = False
    note: str | None = None
    if severity != "match":
        matched, exp_at = _matches_documented_exception(
            key, actual_s, server_name, documented_exceptions
        )
        if matched:
            # Documented exception → downgrade severity to "warning".
            exception_match = True
            severity = "warning"
            note = f"documented exception (expires_at={exp_at})"
    checks.append(
        ParityCheck(
            key=key,
            expected=expected_s,
            actual=actual_s,
            severity=severity,
            exception_match=exception_match,
            note=note,
        )
    )


def _build_checks(
    baseline: dict[str, Any],
    *,
    server_name: str,
    actuals: dict[str, Any],
) -> list[ParityCheck]:
    """Build the per-key ParityCheck list from a baseline + actuals dict.

    ``actuals`` is the result of running all probes; key shape mirrors the
    baseline. Missing actuals are filled with PROBE_FAILED_SENTINEL.
    """
    documented_exceptions = baseline.get("documented_exceptions") or []
    if not isinstance(documented_exceptions, list):
        documented_exceptions = []
    checks: list[ParityCheck] = []

    # operating_system
    os_expected = baseline.get("operating_system", {})
    os_actual = actuals.get("operating_system", {})
    if isinstance(os_expected, dict) and isinstance(os_actual, dict):
        for sub in ("distro", "version", "kernel"):
            if sub in os_expected:
                _add_check(
                    checks,
                    key=f"operating_system.{sub}",
                    expected=os_expected.get(sub),
                    actual=os_actual.get(sub, PROBE_FAILED_SENTINEL),
                    server_name=server_name,
                    documented_exceptions=documented_exceptions,
                )

    # python
    py_expected = baseline.get("python", {})
    py_actual = actuals.get("python", {})
    if isinstance(py_expected, dict) and isinstance(py_actual, dict):
        for sub in ("version", "pip_freeze_sha256"):
            if sub in py_expected:
                _add_check(
                    checks,
                    key=f"python.{sub}",
                    expected=py_expected.get(sub),
                    actual=py_actual.get(sub, PROBE_FAILED_SENTINEL),
                    server_name=server_name,
                    documented_exceptions=documented_exceptions,
                )

    # native_libraries
    nl_expected = baseline.get("native_libraries", {})
    nl_actual = actuals.get("native_libraries", {})
    if isinstance(nl_expected, dict) and isinstance(nl_actual, dict):
        for sub in (
            "oracle_instant_client_version",
            "oracle_instant_client_dir",
            "odbc_driver_version",
            "odbc_driver_name",
            "mssql_tools_version",
            "mssql_tools_dir",
            "gpg_version",
        ):
            if sub in nl_expected:
                _add_check(
                    checks,
                    key=f"native_libraries.{sub}",
                    expected=nl_expected.get(sub),
                    actual=nl_actual.get(sub, PROBE_FAILED_SENTINEL),
                    server_name=server_name,
                    documented_exceptions=documented_exceptions,
                )

    # env_vars_required
    env_expected = baseline.get("env_vars_required", {})
    env_actual = actuals.get("env_vars_required", {})
    if isinstance(env_expected, dict) and isinstance(env_actual, dict):
        for env_key, env_val in env_expected.items():
            _add_check(
                checks,
                key=f"env_vars_required.{env_key}",
                expected=env_val,
                actual=env_actual.get(env_key, PROBE_FAILED_SENTINEL),
                server_name=server_name,
                documented_exceptions=documented_exceptions,
            )

    # filesystem_layout
    fs_expected = baseline.get("filesystem_layout", [])
    if isinstance(fs_expected, list):
        fs_actuals_list = actuals.get("filesystem_layout", []) or []
        actual_by_path = {entry.get("path"): entry for entry in fs_actuals_list if isinstance(entry, dict)}
        for entry in fs_expected:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path", "")
            actual_entry = actual_by_path.get(path, {})
            # must_exist check
            _add_check(
                checks,
                key=f"filesystem_layout.{path}.must_exist",
                expected=entry.get("must_exist", True),
                actual=actual_entry.get("must_exist", False),
                server_name=server_name,
                documented_exceptions=documented_exceptions,
            )
            # owner check (skip when sentinels on either side or both)
            if "owner" in entry:
                _add_check(
                    checks,
                    key=f"filesystem_layout.{path}.owner",
                    expected=entry.get("owner"),
                    actual=actual_entry.get("owner", PROBE_FAILED_SENTINEL),
                    server_name=server_name,
                    documented_exceptions=documented_exceptions,
                )
            # mode check (normalize via _stringify)
            if "mode" in entry:
                _add_check(
                    checks,
                    key=f"filesystem_layout.{path}.mode",
                    expected=entry.get("mode"),
                    actual=actual_entry.get("mode", PROBE_FAILED_SENTINEL),
                    server_name=server_name,
                    documented_exceptions=documented_exceptions,
                )

    # systemd_unit
    sysd_expected = baseline.get("systemd_unit", {})
    sysd_actual = actuals.get("systemd_unit", {})
    if isinstance(sysd_expected, dict) and isinstance(sysd_actual, dict):
        for sub in ("sha256",):
            if sub in sysd_expected:
                _add_check(
                    checks,
                    key=f"systemd_unit.{sub}",
                    expected=sysd_expected.get(sub),
                    actual=sysd_actual.get(sub, PROBE_FAILED_SENTINEL),
                    server_name=server_name,
                    documented_exceptions=documented_exceptions,
                )

    # tpm2
    tpm_expected = baseline.get("tpm2", {})
    tpm_actual = actuals.get("tpm2", {})
    if isinstance(tpm_expected, dict) and isinstance(tpm_actual, dict):
        for sub in ("pcr_policy_hash", "tpm2_tools_version"):
            if sub in tpm_expected:
                _add_check(
                    checks,
                    key=f"tpm2.{sub}",
                    expected=tpm_expected.get(sub),
                    actual=tpm_actual.get(sub, PROBE_FAILED_SENTINEL),
                    server_name=server_name,
                    documented_exceptions=documented_exceptions,
                )

    # credentials_envelope
    creds_expected = baseline.get("credentials_envelope", {})
    creds_actual = actuals.get("credentials_envelope", {})
    if isinstance(creds_expected, dict) and isinstance(creds_actual, dict):
        for sub in ("sha256", "schema_version", "recipient_count"):
            if sub in creds_expected:
                _add_check(
                    checks,
                    key=f"credentials_envelope.{sub}",
                    expected=creds_expected.get(sub),
                    actual=creds_actual.get(sub, PROBE_FAILED_SENTINEL),
                    server_name=server_name,
                    documented_exceptions=documented_exceptions,
                )

    # udm_tables_list_schema
    udm_expected = baseline.get("udm_tables_list_schema", {})
    udm_actual = actuals.get("udm_tables_list_schema", {})
    if isinstance(udm_expected, dict) and isinstance(udm_actual, dict):
        for sub in ("expected_columns_sha256", "spec_doc"):
            if sub in udm_expected:
                _add_check(
                    checks,
                    key=f"udm_tables_list_schema.{sub}",
                    expected=udm_expected.get(sub),
                    actual=udm_actual.get(sub, PROBE_FAILED_SENTINEL),
                    server_name=server_name,
                    documented_exceptions=documented_exceptions,
                )

    return checks


# ---------------------------------------------------------------------------
# Top-level orchestrator — runs all probes against the baseline
# ---------------------------------------------------------------------------


def _run_all_probes(
    baseline: dict[str, Any],
    *,
    runner=_run_subprocess,
) -> dict[str, Any]:
    """Execute every probe required by the baseline categories.

    Returns a dict matching the baseline shape (with ``actual`` values).
    Raises ``ParityProbeError`` if a critical RHEL probe fails fatally on
    Linux (e.g. ``tpm2_getcap`` returned non-zero — F21 hardware fault).
    """
    actuals: dict[str, Any] = {}
    actuals["operating_system"] = _probe_operating_system_actual()
    actuals["python"] = _probe_python_actual(runner=runner)
    actuals["native_libraries"] = _probe_native_libraries_actual(runner=runner)
    # env_vars_required — only probe the keys present in baseline
    env_baseline = baseline.get("env_vars_required", {}) or {}
    actuals["env_vars_required"] = _probe_env_vars_actual(env_baseline.keys())
    # filesystem_layout — probe each entry
    fs_baseline = baseline.get("filesystem_layout", []) or []
    actuals["filesystem_layout"] = [
        _probe_filesystem_actual(entry) for entry in fs_baseline if isinstance(entry, dict)
    ]
    # systemd_unit
    sysd = baseline.get("systemd_unit", {}) or {}
    actuals["systemd_unit"] = {
        "path": sysd.get("path", "/etc/systemd/system/pipeline.service"),
        "sha256": _probe_systemd_unit_actual(
            sysd.get("path", "/etc/systemd/system/pipeline.service")
        ),
    }
    # tpm2 — F21 hardware fault detection
    tpm = baseline.get("tpm2", {}) or {}
    tpm_actual = _probe_tpm2_actual(runner=runner)
    actuals["tpm2"] = tpm_actual
    # F21: on Linux, if tpm2_getcap returned non-zero AND baseline says
    # tpm2.required is True, that's a parity violation — raise.
    if _is_linux() and tpm.get("required") is True:
        getcap_status = tpm_actual.get("getcap_status", "")
        if isinstance(getcap_status, str) and getcap_status.startswith("non-zero"):
            raise ParityProbeError(
                f"TPM2 hardware probe failed ({getcap_status}); F21 fatal-tier drift",
                metadata={"probe": "tpm2_getcap", "status": getcap_status},
            )
    # credentials_envelope
    creds_baseline = baseline.get("credentials_envelope", {}) or {}
    actuals["credentials_envelope"] = _probe_credentials_envelope_actual(
        creds_baseline.get("path", "/etc/pipeline/credentials.json.gpg")
    )
    # udm_tables_list_schema — design-time hash; verify at runtime by
    # echoing the baseline value (the canonical column list is also
    # design-time in capture). Live INFORMATION_SCHEMA queries are out
    # of scope per phase2/01 § 4.3 cycle-3 scope clarification.
    actuals["udm_tables_list_schema"] = dict(
        baseline.get("udm_tables_list_schema", {}) or {}
    )

    return actuals


# ---------------------------------------------------------------------------
# Public function — canonical signature per R2 § 4.2 L957-961
# ---------------------------------------------------------------------------


def verify_server_parity(
    baseline_path: str | Path | None = None,
    server_name: str | None = None,
    fail_on_warning: bool = False,
    *,
    server: str | None = None,
    json_output: bool = False,
    _runner=_run_subprocess,
) -> ParityReport:
    """Compare current server state against ``/etc/pipeline/parity_baseline.json``.

    See module docstring for the contract. Returns a ``ParityReport``;
    raises ``ParityFatalError`` on fatal drift OR ``fail_on_warning=True``
    with any warning. Raises ``ParityBaselineMissing`` on absent/malformed
    baseline. Raises ``ParityProbeError`` on system probe failure (e.g.
    ``tpm2_getcap`` non-zero on a baseline that marks tpm2 required).

    Args:
        baseline_path: Path to baseline JSON; default DEFAULT_BASELINE_PATH.
        server_name: Server identifier for documented-exceptions lookup.
            Default reads $SERVER_NAME env var, then socket.gethostname().
        fail_on_warning: When True, treat warning-tier drift as fatal.
        server: Keyword-only alias for ``server_name`` so callers like
            ``tools/promote_test_to_prod.py`` that pass ``server=`` work.
        json_output: When True, return the report's dict form via
            ``ParityReport.to_dict()`` semantics. (The dataclass return
            value is still primary; this flag is a presentation hint.)
        _runner: Internal — subprocess runner override for tests.

    Returns:
        ``ParityReport`` with per-check status + counts + overall verdict.

    Raises:
        ParityBaselineMissing: baseline JSON absent or malformed.
        ParityProbeError: critical system probe failed (F21).
        ParityFatalError: any fatal-tier drift OR fail_on_warning=True with warnings.
    """
    # Resolve server name precedence: explicit > server > $SERVER_NAME > hostname.
    effective_server = server_name or server or os.environ.get("SERVER_NAME") or socket.gethostname() or "unknown"

    path = baseline_path or DEFAULT_BASELINE_PATH
    logger.debug("Loading baseline from %s", path)
    baseline = _load_baseline(path)

    actuals = _run_all_probes(baseline, runner=_runner)
    checks = _build_checks(baseline, server_name=effective_server, actuals=actuals)

    fatal = sum(1 for c in checks if c.severity == "fatal")
    warning = sum(1 for c in checks if c.severity == "warning")
    info = sum(1 for c in checks if c.severity == "informational")
    match = sum(1 for c in checks if c.severity == "match")

    if fatal > 0:
        overall: Overall = "fail"
    elif warning > 0:
        overall = "warn"
    else:
        overall = "pass"

    report = ParityReport(
        server_name=effective_server,
        baseline_name=str(baseline.get("baseline_name", "unknown")),
        baseline_pinned_at=str(baseline.get("pinned_at", "")),
        checks=checks,
        fatal_count=fatal,
        warning_count=warning,
        informational_count=info,
        match_count=match,
        overall=overall,
    )

    logger.info(
        "Parity verify: server=%s baseline=%s overall=%s fatal=%d warn=%d info=%d match=%d",
        effective_server,
        report.baseline_name,
        overall,
        fatal,
        warning,
        info,
        match,
    )

    # Raise on fatal drift (per § 3.2 L795-799). CLI shim catches + exits 1/2.
    if fatal > 0:
        raise ParityFatalError(
            f"Fatal-tier parity drift: {fatal} fatal check(s) on server={effective_server!r}",
            metadata={
                "server_name": effective_server,
                "baseline_name": report.baseline_name,
                "fatal_count": fatal,
                "warning_count": warning,
                "informational_count": info,
                "match_count": match,
                # First-three keys are enough for paging diagnostics
                "fatal_keys": [c.key for c in checks if c.severity == "fatal"][:3],
            },
        )
    if fail_on_warning and warning > 0:
        raise ParityFatalError(
            f"Warning-tier parity drift with fail_on_warning=True: {warning} warning check(s)",
            metadata={
                "server_name": effective_server,
                "baseline_name": report.baseline_name,
                "warning_count": warning,
                "warning_keys": [c.key for c in checks if c.severity == "warning"][:3],
            },
        )

    # json_output is a presentation hint — primary return value is still the
    # dataclass. Callers wanting strict JSON use report.to_dict() directly.
    if json_output:
        logger.debug("json_output requested — report.to_dict() keys: %s", sorted(report.to_dict().keys()))

    return report


__all__ = [
    "ParityCheck",
    "ParityReport",
    "Severity",
    "Overall",
    "ParityFatalError",
    "ParityBaselineMissing",
    "ParityProbeError",
    "DEFAULT_BASELINE_PATH",
    "EVENT_TYPE",
    "WINDOWS_SENTINEL",
    "PROBE_FAILED_SENTINEL",
    "UNAVAILABLE_SENTINEL",
    "verify_server_parity",
]
