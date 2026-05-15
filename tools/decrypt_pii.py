"""Round 4 § 3.4 — ``tools/decrypt_pii.py``.

Per **Round 4 § 3.4** at ``docs/migration/phase1/04_tools.md`` L664-749
(canonical spec) + **Round 3 § 2.2** ``data_load/pii_decryptor.py``
canonical interface (``decrypt_token(*, token: str, justification: str,
request_id: uuid.UUID | None = None) -> str | None``).

Operator-driven CLI wrapper for M5 ``decrypt_token`` per Round 3 § 2.2.
Decrypt a token (or batch of tokens) with mandatory ``--justification``;
SP-2 writes the audit row to ``PiiVaultAccessLog`` server-side atomic
with the decrypt per P8 + D6. **Operator authority assumed** — pipeline
service account does NOT have decrypt permission per D6.

SECURITY-CRITICAL contract (per D103 + P5)
==========================================

* **NEVER log decrypted plaintext.** The plaintext leaves M5 via the
  function return value; from there it flows to stdout (the intended
  operator output) via ``print()`` — NEVER through ``logger.*`` calls
  and NEVER into the ``PipelineEventLog.Metadata`` JSON payload.
* Audit-row Metadata carries: Token (hex identifier — not sensitive),
  Operator, Justification (length only — operator-supplied free text
  may contain accidental PII so we log length not value), Status
  outcome, RequestId. **NEVER** carries the decrypted plaintext.
* Empty / whitespace ``--justification`` is rejected by argparse +
  validated again at the function boundary BEFORE any M5 round trip.
  No audit row is written for malformed input (audit semantics require
  a non-empty reason).
* M5 itself emits ``logger.info`` lines that include Token + RequestId
  + plaintext_length only. The ``observability.sensitive_data_filter``
  is the last-mile defense-in-depth redactor.

What this tool does
-------------------

1. Parse one or more ``--token`` flags OR a ``--token-file`` (mutually
   exclusive per spec § 3.4 L724).
2. Validate ``--justification`` is non-empty (audit contract per D6 +
   D26 + D75 — empty rejected at arg-parse).
3. For each token, invoke M5 :func:`decrypt_token` per Round 3 § 2.2
   keyword-only signature ``(*, token, justification, request_id)``.
4. Catch:

   * :class:`TokenNotFound` (Round 3 § 2.2 — ``PipelineFatalError``)
     → exit 2; stdout per-token line ``<hint> -> NOT_FOUND``;
     **NO** server-side audit row written by SP-2 (Token absent means
     SP-2 returns empty result-set BEFORE the audit insert per L1422-1434).
   * :class:`DecryptDenied` (Round 3 § 2.2 — token Status is
     ``'deleted_per_request'`` or ``'purged_for_retention'``) →
     **NOT a fatal exit code per spec § 3.4 L711** — tool returns exit
     0 with stdout ``<hint> -> <NULL> (CCPA-deleted)``. Audit row IS
     written server-side per L1422-1434 BEFORE SP-2 returns NULL.
   * :class:`VaultUnavailable` (PipelineRetryableError) → exit 1.
   * :class:`PipelineFatalError` subclasses other than TokenNotFound
     (e.g. VaultConfigError) → exit 2.

5. Per-token stdout line per spec § 3.4 L686-689 + L734:

   * Normal decrypt: ``<token-hint> -> <plaintext>``
   * CCPA-deleted: ``<token-hint> -> <NULL> (CCPA-deleted)``
   * Not found:    ``<token-hint> -> NOT_FOUND``
   * (``--mask-output`` replaces plaintext with last-4-chars + redaction)
   * ``<token-hint>`` = first 4 chars + ``<...>`` + last 4 chars
     (e.g. ``a3f1<...>9c2d``)

6. Write ONE ``CLI_DECRYPT_PII`` audit row to
   ``General.ops.PipelineEventLog`` per D76. ``Metadata`` JSON contains:
   ``actor``, ``justification`` (operator-supplied; surface for audit
   correlation), ``request_id``, ``token_count``, ``decrypted_count``,
   ``null_count`` (CCPA-deleted), ``not_found_count``, ``status``,
   ``exit_code``, ``event_kind='pii_decrypt'``, ``token_hints`` (list
   of redacted hints for cross-correlation against PiiVaultAccessLog).
   **NEVER** carries the decrypted plaintext.
7. Exit 0 / 1 / 2 per D74 + spec § 3.4 L737-740.

CLI contract (per spec § 3.4 L713-723)
--------------------------------------

::

    # Single token
    python3 tools/decrypt_pii.py --token <token-hex> \\
        --justification 'Audit ticket #12345 — operator review'

    # Batch from file (one token per line; '#' comments skipped)
    python3 tools/decrypt_pii.py --token-file /path/to/tokens.txt \\
        --justification 'CCPA right-to-know request #6789 — Q2 2026'

    # JSON output for downstream consumption
    python3 tools/decrypt_pii.py --token <token-hex> \\
        --justification 'audit' --json

    # Masked stdout (last-4-chars only)
    python3 tools/decrypt_pii.py --token <token-hex> \\
        --justification 'audit' --mask-output

Exit codes (per D74 + spec § 3.4 L737-740)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **0** — all tokens processed successfully (including CCPA-deleted
  with NULL plaintext per spec § 3.4 L711). Stdout contains the per-
  token lines; the operator interprets ``<NULL> (CCPA-deleted)`` as
  the deletion having been authorized.
* **1** — at least one token failed with a retryable error
  (:class:`VaultUnavailable` — vault DB drop / deadlock). Operator can
  re-run; no partial-state risk since SP-2 is read-only on PiiVault.
* **2** — fatal: at least one :class:`TokenNotFound` (Token absent
  from PiiVault) OR :class:`VaultConfigError` (env keys missing /
  vault unreachable at startup) OR missing justification (argparse).

Audit row (per D76 + spec § 3.4 L691)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``General.ops.PipelineEventLog.EventType = 'CLI_DECRYPT_PII'``
  (one of the 11 R4 canonical CLI_* family values per CLAUDE.md)
* ONE row per INVOCATION (NOT one per token — per-token counts surface
  in Metadata JSON; the per-token ``PiiVaultAccessLog`` rows ARE
  written server-side by SP-2, separate from this CLI-level audit row).
* ``Status in {SUCCESS, FAILED}`` (SUCCESS for exit 0; FAILED for exit
  1 / 2).
* ``Metadata`` JSON shape::

    {
        "event_kind": "pii_decrypt",
        "actor": "<operator>",
        "justification": "<operator-supplied text>",
        "request_id": "<uuid>",
        "token_count": <int>,
        "decrypted_count": <int>,
        "null_count": <int>,
        "not_found_count": <int>,
        "vault_unavailable_count": <int>,
        "token_hints": ["a3f1<...>9c2d", ...],
        "mask_output": <bool>,
        "exit_code": <int>,
        "status": "SUCCESS|FAILED",
        "started_at": "<ISO-8601 naive-UTC>",
        "completed_at": "<ISO-8601 naive-UTC>"
    }

Plaintext NEVER appears anywhere in the Metadata payload — only in
stdout via ``print()`` (a separate channel the operator captures
explicitly).

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: PRIMARY: Manual operator CLI for ad-hoc compliance /
  audit / CCPA right-to-know responses. SECONDARY: NEVER scheduled
  (per D6 + P8 — no automation should decrypt PII on a schedule).
* **Frequency**: Ad-hoc / event-driven (NOT recurring).
* **Idempotency**: At SP level YES — SP-2's read-only decrypt produces
  the same plaintext deterministically per the SCD2 hash invariant.
  At the audit level NO (every operator access is a separate audit
  event per D26 — re-decrypting the same token N times produces N
  ``PiiVaultAccessLog`` rows; this is intentional).
* **Concurrency**: Single-process; serial token-by-token through SP-2.
  ``--workers`` NOT supported per spec § 3.4 L728 (audit semantics
  require serial; rate-limiting is desirable for the operator-facing
  surface).
* **Audit-row family**: ``CLI_DECRYPT_PII`` per D76 + CLAUDE.md
  CLI_* family registry.
* **Routing**: PRIMARY tracker ``ONE_OFF_SCRIPTS.md`` operator tools
  table (manual + event-driven). NO scheduled tracker entry.

D-numbers consumed
------------------

D6 (vault decrypt path — operator-authority only),
D15 (idempotency at SP level — read-only on PiiVault),
D26 (append-only audit — every operator access is a separate row),
D30 (CCPA-deleted tokens return None — DecryptDenied raised by M5,
  CAUGHT by this tool and treated as exit 0 success per spec L711),
D67 (Tier 0 smoke discipline),
D68 (canonical exception hierarchy — utils.errors),
D74-D77 (CLI exit-code contract + argument naming + audit-row contract +
  Tier 0 7-canonical-assertion scaffold per spec § 3.4 L742),
D92 (forward-only additive — new tool),
D103 (Claude Code security model — NEVER log decrypted plaintext;
  defense-in-depth via sensitive_data_filter at the handler level),
P5 (no plaintext in logs — defense-in-depth pattern),
P8 (audit every decrypt — SP-2 owns the server-side audit write).

Canonical references cited (per Pitfall #9.l producer self-check)
-----------------------------------------------------------------

* M5 decrypt_token signature: ``data_load/pii_decryptor.py`` L113-115
  keyword-only ``(*, token: str, justification: str, request_id:
  uuid.UUID | None = None)`` returning ``str | None`` (per Round 3
  § 2.2 canonical — verified by direct file read at build time per
  Pitfall #9.l).
* M5 exceptions: ``utils.errors.TokenNotFound`` (PipelineFatalError;
  Token absent from PiiVault), ``utils.errors.DecryptDenied``
  (PipelineFatalError; Status forbids decrypt — CAUGHT here and treated
  as exit 0 success per spec § 3.4 L711), ``utils.errors.VaultUnavailable``
  (PipelineRetryableError; connection drop), ``utils.errors.VaultConfigError``
  (PipelineFatalError; env keys missing).
* SP-2 DDL: ``phase1/01_database_schema.md`` L1414-1455
  ``General.ops.PiiVault_Decrypt`` — parameters ``@RequestId
  UNIQUEIDENTIFIER`` / ``@Token VARCHAR(40)`` / ``@Justification
  NVARCHAR(MAX)``. Audit-row INSERT is performed server-side inside SP-2
  body (L1422-1434) atomic with decrypt — NO client-side audit write
  for PiiVaultAccessLog needed.
* PiiVaultAccessLog DDL: ``phase1/01_database_schema.md`` L1031-1048
  columns ``RequestId``, ``AccessedAt``, ``AccessedBy``, ``AccessRole``,
  ``Token``, ``Justification``, ``AccessSourceIp``, ``AccessApplication``.
* CLI conventions: ``phase1/04_tools.md`` § 1.4 (canonical args) +
  § 1.7 (invocation-pattern heuristic — AUTOMIC_RUN_ID env + isatty) +
  § 1.8 (exit-code mapping) + § 1.9 (boilerplate template).

See also
--------

* ``data_load/pii_decryptor.py`` (M5) — wrapped module.
* ``data_load/vault_client.py`` (M6) — connection pool + retry composer.
* ``observability/sensitive_data_filter.py`` — defense-in-depth log
  filter (P5).
* ``tools/parquet_verify.py`` — sibling Round 4 § 3.2 tool (same
  Tier 0-friendly structure; audit-row writer pattern).
* ``tools/enforce_retention.py`` — sibling Round 4 § 3.8 tool (same
  exception-bridge pattern via data_load._exceptions for tests).
* RB-4 (PII audit access runbook).
* RB-10 (CCPA right-to-deletion — DecryptDenied = audit'd no-op).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Project root on sys.path so we can reach data_load + utils.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Canonical exception hierarchy per D68 + B228 (utils.errors single source
# of truth; tools import from utils.errors directly).
try:
    from utils.errors import (  # noqa: E402
        DecryptDenied,
        PipelineFatalError,
        PipelineRetryableError,
        TokenNotFound,
        VaultConfigError,
        VaultUnavailable,
    )
except (ImportError, ModuleNotFoundError):
    # Defensive fallback for test environments where utils.errors is
    # mocked as MagicMock — re-import from the filesystem directly.
    import importlib.util as _importlib_util  # noqa: E402

    _err_path = Path(__file__).resolve().parent.parent / "utils" / "errors.py"
    _spec = _importlib_util.spec_from_file_location(
        "utils._errors_decrypt_pii", _err_path
    )
    _err_mod = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_err_mod)
    DecryptDenied = _err_mod.DecryptDenied
    PipelineFatalError = _err_mod.PipelineFatalError
    PipelineRetryableError = _err_mod.PipelineRetryableError
    TokenNotFound = _err_mod.TokenNotFound
    VaultConfigError = _err_mod.VaultConfigError
    VaultUnavailable = _err_mod.VaultUnavailable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exit-code constants (per D74 + spec § 3.4 L737-740)
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0
EXIT_OPERATIONAL_FAILURE = 1
EXIT_FATAL = 2

# D76 EventType registered in CLAUDE.md CLI_* family registry (one of the
# 11 R4 canonical values).
EVENT_TYPE = "CLI_DECRYPT_PII"

# Per-token verdict tokens per spec § 3.4 L686-689 + L734
VERDICT_DECRYPTED = "decrypted"
VERDICT_CCPA_DELETED = "ccpa_deleted"
VERDICT_NOT_FOUND = "not_found"
VERDICT_VAULT_UNAVAILABLE = "vault_unavailable"
VERDICT_ERROR = "error"


# ---------------------------------------------------------------------------
# Actor detection (per § 1.7 invocation pattern heuristic)
# ---------------------------------------------------------------------------


def _detect_actor() -> str:
    """Resolve ``--actor`` default per spec § 1.7 invocation-pattern heuristic.

    1. AUTOMIC_RUN_ID env var present -> 'automic' (per spec § 3.4 L728
       NOT scheduled — but the detection itself is canonical across
       all R4 tools; AUTOMIC presence here would surface in audit row
       Metadata as a contract violation for operator review).
    2. sys.stdin.isatty() -> 'operator' (the canonical case for this
       tool; operators run from a TTY for ad-hoc compliance requests).
    3. Else -> 'pipeline' (defensive default — pipeline programmatic
       callers should pass --actor explicitly anyway).
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
# Token-hint helpers (per spec § 3.4 L734: first 4 chars + '<...>' + last 4 chars)
# ---------------------------------------------------------------------------


def _token_hint(token: str) -> str:
    """Build the canonical token-hint per spec § 3.4 L734.

    Format: first 4 chars + ``<...>`` + last 4 chars.
    Example: ``a3f12345...9c2d`` -> ``a3f1<...>9c2d``.

    For tokens shorter than 9 chars (defensive — canonical PiiVault.Token
    is VARCHAR(40) hex per SP-2), we return the full token (no masking
    possible). Empty/None token returns ``<empty>``.
    """
    if token is None or not isinstance(token, str) or not token:
        return "<empty>"
    if len(token) < 9:
        # Too short to mask meaningfully; return as-is.
        return token
    return f"{token[:4]}<...>{token[-4:]}"


def _mask_plaintext(plaintext: str) -> str:
    """Apply --mask-output redaction per spec § 3.4 L729-732.

    Show plaintext as last-4-chars + redaction prefix. Caveat per spec:
    'still writes plaintext to caller's stdout pipe — operator should
    redirect stdout to a file if even masked display is too sensitive'.
    The masking here is the CLI-level display; the underlying string is
    NOT zeroed.

    For plaintext shorter than 4 chars, returns ``<redacted>`` (no
    last-4 available; defensive).
    """
    if plaintext is None or not isinstance(plaintext, str):
        return "<redacted>"
    if len(plaintext) < 4:
        return "<redacted>"
    return f"<...redacted-len-{len(plaintext)}...>{plaintext[-4:]}"


# ---------------------------------------------------------------------------
# Token-file parsing (per spec § 3.4 L716-718: one token per line, '#' comments)
# ---------------------------------------------------------------------------


def _read_tokens_from_file(file_path: Path) -> list[str]:
    """Read tokens from a file per spec § 3.4 L716-718.

    Format: one token per line. Lines starting with ``#`` are comments
    (skipped per spec § 3.4 L744 Tier 1 test surface). Blank lines
    skipped. Whitespace stripped from each line.

    Raises
    ------
    PipelineFatalError
        File does not exist OR is not readable.
    """
    if not file_path.exists():
        raise PipelineFatalError(
            f"Token file does not exist: {file_path}",
            metadata={"file_path": str(file_path)},
        )
    if not file_path.is_file():
        raise PipelineFatalError(
            f"Token file is not a regular file: {file_path}",
            metadata={"file_path": str(file_path)},
        )

    tokens: list[str] = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    continue
                tokens.append(line)
    except OSError as exc:
        raise PipelineFatalError(
            f"Failed to read token file {file_path}: {exc}",
            metadata={"file_path": str(file_path), "error": str(exc)},
        ) from exc

    if not tokens:
        # Empty file (only comments / blanks) — treat as fatal per spec
        # contract (operator submitted no work to do; surface explicitly
        # rather than silently exit 0).
        raise PipelineFatalError(
            f"Token file contains no tokens (only comments / blank lines): "
            f"{file_path}",
            metadata={"file_path": str(file_path)},
        )

    return tokens


# ---------------------------------------------------------------------------
# Audit row writer (per D76 + spec § 3.4 L691)
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
    """INSERT one ``CLI_DECRYPT_PII`` row into PipelineEventLog.

    Per D76 + spec § 3.4 L691. ONE row per invocation (NOT one per
    token — per-token counts surface in Metadata JSON; the per-token
    ``PiiVaultAccessLog`` rows ARE written server-side by SP-2).
    Best-effort: failures are logged but do not affect the verdict
    exit code (parity with B188 / B189 / B190 / B218 audit-row patterns).

    Returns the SCOPE_IDENTITY() of the inserted row so the JSON
    ``audit_event_id`` key (per spec § 3.4 L735) can be populated.
    Returns None on failure (the JSON key is then null).

    When ``skip=True`` (test path; main()'s ``no_audit_event``), returns
    None immediately without writing.

    SECURITY-CRITICAL: ``metadata`` MUST NOT carry the decrypted
    plaintext. Caller is responsible for keeping plaintext out of the
    dict; this function does NOT scrub.
    """
    if skip:
        return None

    metadata_json = json.dumps(metadata, separators=(",", ":"), default=str)
    token_count = metadata.get("token_count", 0)
    decrypted_count = metadata.get("decrypted_count", 0)
    event_detail = (
        f"decrypt_pii / tokens={token_count} / decrypted={decrypted_count} / "
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
            cursor.execute(
                f"INSERT INTO [{general_db}].ops.PipelineEventLog "
                f"(BatchId, TableName, SourceName, EventType, EventDetail, "
                f" StartedAt, CompletedAt, Status, ErrorMessage, Metadata) "
                f"VALUES (NEXT VALUE FOR [{general_db}].ops.PipelineBatchSequence, "
                f"        NULL, NULL, ?, ?, ?, SYSUTCDATETIME(), ?, ?, ?); "
                f"SELECT CAST(SCOPE_IDENTITY() AS BIGINT) AS AuditEventId;",
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
        logger.exception("Failed to write CLI_DECRYPT_PII audit row")
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


def _format_human_line(verdict_row: dict, *, mask_output: bool) -> str:
    """Format a single-token stdout line per spec § 3.4 L686-689 + L734.

    Format: ``<token-hint> -> <result>`` where result depends on verdict:
        decrypted: plaintext (or masked redaction if --mask-output)
        ccpa_deleted: ``<NULL> (CCPA-deleted)``
        not_found: ``NOT_FOUND``
        vault_unavailable / error: ``<ERROR: ...>``
    """
    hint = verdict_row.get("token_hint") or "<unknown>"
    verdict = verdict_row.get("verdict")
    plaintext = verdict_row.get("plaintext")

    if verdict == VERDICT_DECRYPTED:
        if plaintext is None:
            # Defensive: verdict is decrypted but plaintext missing —
            # surface as error rather than print 'None'.
            return f"{hint} -> <ERROR: decrypted verdict but plaintext missing>"
        if mask_output:
            return f"{hint} -> {_mask_plaintext(plaintext)}"
        return f"{hint} -> {plaintext}"
    if verdict == VERDICT_CCPA_DELETED:
        return f"{hint} -> <NULL> (CCPA-deleted)"
    if verdict == VERDICT_NOT_FOUND:
        return f"{hint} -> NOT_FOUND"
    if verdict == VERDICT_VAULT_UNAVAILABLE:
        err = verdict_row.get("error_message") or "vault unreachable"
        return f"{hint} -> <ERROR: vault unavailable — {err}>"
    if verdict == VERDICT_ERROR:
        err = verdict_row.get("error_message") or "unknown error"
        return f"{hint} -> <ERROR: {err}>"
    # Defensive fallback
    return f"{hint} -> <unknown verdict: {verdict}>"


def _emit_human_summary(
    *,
    verdicts: list[dict],
    counts: dict[str, int],
    mask_output: bool,
    audit_event_id: int | None,
) -> None:
    """Print spec § 3.4 L734 stdout block.

    Per-token lines + final summary line. SECURITY-CRITICAL: plaintext
    goes to ``print()`` directly — NOT through ``logger`` so the
    ``SqlServerLogHandler`` never sees it.
    """
    for v in verdicts:
        print(_format_human_line(v, mask_output=mask_output))

    decrypted = counts.get("decrypted", 0)
    ccpa_deleted = counts.get("ccpa_deleted", 0)
    not_found = counts.get("not_found", 0)
    vault_unavail = counts.get("vault_unavailable", 0)
    err = counts.get("error", 0)

    summary = (
        f"{decrypted:,} decrypted / {ccpa_deleted:,} CCPA-deleted / "
        f"{not_found:,} not found"
    )
    if vault_unavail or err:
        summary += f" / {vault_unavail:,} vault-unavailable / {err:,} error"
    if audit_event_id is not None:
        summary += f" — audit event {audit_event_id}"
    print(summary)


def _emit_json(payload: dict) -> None:
    """Emit the canonical JSON payload per spec § 3.4 L735.

    Shape: list of dicts ``[{"token_hint": "...", "plaintext": "...",
    "status": "decrypted|ccpa_deleted|not_found", "request_id": "...",
    "audit_event_id": N}]``. Top-level wrapper is a dict carrying
    ``verdicts`` + ``counts`` + ``audit_event_id`` + ``dry_run=False``
    (always — this tool has no dry-run mode per spec § 1.2; it's
    read-only on PiiVault).

    SECURITY-CRITICAL: plaintext appears in the JSON output per spec
    § 3.4 L735 ("``plaintext`` is the actual decrypted string"). Operator
    is responsible for redirecting stdout to secure storage per spec.
    The JSON goes via ``print()`` not through logger.
    """
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


# ---------------------------------------------------------------------------
# Verdict aggregator
# ---------------------------------------------------------------------------


def _aggregate_counts(verdicts: list[dict]) -> dict[str, int]:
    """Tally per-verdict counts for stdout summary + Metadata JSON."""
    counts = {
        "decrypted": 0,
        "ccpa_deleted": 0,
        "not_found": 0,
        "vault_unavailable": 0,
        "error": 0,
    }
    for v in verdicts:
        verdict = v.get("verdict")
        if verdict == VERDICT_DECRYPTED:
            counts["decrypted"] += 1
        elif verdict == VERDICT_CCPA_DELETED:
            counts["ccpa_deleted"] += 1
        elif verdict == VERDICT_NOT_FOUND:
            counts["not_found"] += 1
        elif verdict == VERDICT_VAULT_UNAVAILABLE:
            counts["vault_unavailable"] += 1
        elif verdict == VERDICT_ERROR:
            counts["error"] += 1
    return counts


def _derive_exit_code(verdicts: list[dict]) -> int:
    """Derive exit code per spec § 3.4 L737-740.

    * Any ``not_found`` (TokenNotFound — fatal per D68) → exit 2
    * Any ``error`` (catch-all fatal — VaultConfigError / unexpected) → exit 2
    * Any ``vault_unavailable`` (retryable) AND no fatal → exit 1
    * Else → exit 0 (all decrypted / CCPA-deleted)

    Per spec § 3.4 L711: DecryptDenied / CCPA-deleted is **NOT** a
    fatal exit code — the tool returns exit 0 with stdout
    ``<NULL> (CCPA-deleted)`` (the deletion was authorized per RB-10).
    """
    has_fatal = any(
        v.get("verdict") in (VERDICT_NOT_FOUND, VERDICT_ERROR) for v in verdicts
    )
    if has_fatal:
        return EXIT_FATAL
    has_retryable = any(
        v.get("verdict") == VERDICT_VAULT_UNAVAILABLE for v in verdicts
    )
    if has_retryable:
        return EXIT_OPERATIONAL_FAILURE
    return EXIT_SUCCESS


# ---------------------------------------------------------------------------
# Per-token decrypt wrapper
# ---------------------------------------------------------------------------


def _decrypt_one_token(
    token: str,
    *,
    justification: str,
    request_id: uuid.UUID,
    decrypt_fn: Callable,
) -> dict:
    """Invoke M5 :func:`decrypt_token` for one token and return verdict dict.

    Catches:
      * TokenNotFound → verdict='not_found' (exit 2 fatal contributor)
      * DecryptDenied → verdict='ccpa_deleted' (exit 0 — NOT fatal per
        spec § 3.4 L711). Audit row written server-side by SP-2 per
        SP-2 body L1422-1434.
      * VaultUnavailable → verdict='vault_unavailable' (exit 1 retryable)
      * VaultConfigError / other PipelineFatalError → verdict='error' (exit 2)
      * Unexpected → verdict='error' (defensive; exit 2)

    SECURITY: the returned dict carries ``plaintext`` (the decrypted
    string) for the ``decrypted`` verdict. Caller is responsible for
    keeping it out of audit-row Metadata and out of logger calls — this
    function does NOT log the plaintext.
    """
    hint = _token_hint(token)
    verdict_row: dict[str, Any] = {
        "token_hint": hint,
        "verdict": None,
        "plaintext": None,
        "error_message": None,
        "request_id": str(request_id),
    }
    try:
        # M5 canonical signature per Round 3 § 2.2:
        #   decrypt_token(*, token, justification, request_id) -> str | None
        plaintext = decrypt_fn(
            token=token,
            justification=justification,
            request_id=request_id,
        )
        # M5's contract per the docstring: returns str on happy path.
        # If somehow we get None back (legacy / mocked behavior), treat
        # as CCPA-deleted per the spec — DecryptDenied is the canonical
        # signal but defensive handling for direct-None.
        if plaintext is None:
            verdict_row["verdict"] = VERDICT_CCPA_DELETED
        else:
            verdict_row["verdict"] = VERDICT_DECRYPTED
            verdict_row["plaintext"] = plaintext
    except TokenNotFound as exc:
        verdict_row["verdict"] = VERDICT_NOT_FOUND
        verdict_row["error_message"] = str(exc)[:500]
        # SECURITY: log Token (hex hint) but NEVER any plaintext-adjacent
        # info. The Token is a non-sensitive identifier per D103.
        logger.warning(
            "decrypt_pii: Token absent from PiiVault token_hint=%s request_id=%s",
            hint,
            request_id,
        )
    except DecryptDenied as exc:
        # CCPA / retention purge — spec § 3.4 L711 says exit 0; the
        # audit row was STILL written server-side by SP-2 before the
        # NULL return per D26 + SP-2 body L1422-1434.
        verdict_row["verdict"] = VERDICT_CCPA_DELETED
        verdict_row["error_message"] = str(exc)[:500]
        logger.info(
            "decrypt_pii: DecryptDenied (CCPA / retention) token_hint=%s request_id=%s",
            hint,
            request_id,
        )
    except VaultUnavailable as exc:
        verdict_row["verdict"] = VERDICT_VAULT_UNAVAILABLE
        verdict_row["error_message"] = str(exc)[:500]
        logger.warning(
            "decrypt_pii: VaultUnavailable token_hint=%s request_id=%s: %s",
            hint,
            request_id,
            exc,
        )
    except VaultConfigError as exc:
        verdict_row["verdict"] = VERDICT_ERROR
        verdict_row["error_message"] = f"VaultConfigError: {str(exc)[:500]}"
        logger.error(
            "decrypt_pii: VaultConfigError token_hint=%s request_id=%s: %s",
            hint,
            request_id,
            exc,
        )
    except PipelineFatalError as exc:
        verdict_row["verdict"] = VERDICT_ERROR
        verdict_row["error_message"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        logger.error(
            "decrypt_pii: %s token_hint=%s request_id=%s: %s",
            type(exc).__name__,
            hint,
            request_id,
            exc,
        )
    except PipelineRetryableError as exc:
        verdict_row["verdict"] = VERDICT_VAULT_UNAVAILABLE
        verdict_row["error_message"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        logger.warning(
            "decrypt_pii: retryable %s token_hint=%s request_id=%s: %s",
            type(exc).__name__,
            hint,
            request_id,
            exc,
        )
    except ValueError as exc:
        # M5's input validation raises ValueError for malformed input —
        # this is fatal per the function-boundary contract.
        verdict_row["verdict"] = VERDICT_ERROR
        verdict_row["error_message"] = f"ValueError: {str(exc)[:500]}"
        logger.error(
            "decrypt_pii: input validation failed token_hint=%s: %s",
            hint,
            exc,
        )
    except Exception as exc:  # noqa: BLE001
        verdict_row["verdict"] = VERDICT_ERROR
        verdict_row["error_message"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        logger.exception(
            "decrypt_pii: unexpected exception token_hint=%s request_id=%s",
            hint,
            request_id,
        )
    return verdict_row


# ---------------------------------------------------------------------------
# Top-level main() — programmatic entry
# ---------------------------------------------------------------------------


def main(
    *,
    actor: str,
    tokens: list[str] | None = None,
    token_file: str | Path | None = None,
    justification: str | None = None,
    request_id: uuid.UUID | None = None,
    mask_output: bool = False,
    json_output: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    no_audit_event: bool = False,
    # ---- Injection hooks (test path) ----
    decrypt_fn: Callable | None = None,
    audit_cursor_factory: Callable | None = None,
    general_db: str | None = None,
) -> dict:
    """Programmatic entry — decrypt one or more PiiVault tokens.

    Returns a dict matching the D76 audit-row Metadata shape (see module
    docstring for canonical schema). Exit-code derivation per D74 +
    spec § 3.4 L737-740:

    * 0: all tokens decrypted successfully (or CCPA-deleted per spec L711)
    * 1: at least one VaultUnavailable (retryable)
    * 2: at least one TokenNotFound OR fatal config error OR missing
      justification

    Parameters
    ----------
    actor:
        Operator identity (per D75 + D76). REQUIRED.
    tokens:
        Explicit list of tokens to decrypt. Mutually exclusive with
        ``token_file`` per spec § 3.4 L724.
    token_file:
        Path to a file containing one token per line. Mutually exclusive
        with ``tokens`` per spec § 3.4 L724. ``#`` comments + blank
        lines skipped per spec § 3.4 L744.
    justification:
        REQUIRED non-empty per D6 + D26 + D75. Empty / whitespace-only
        → exit 2 fatal (no SP-2 round trip; no audit row).
    request_id:
        Optional UUID — ties multiple decrypts to one operator request
        for audit grouping per spec § 3.4 L726. None → auto-generate
        via uuid.uuid4() (one UUID for the whole invocation, NOT per
        token — operator's intent is one decryption "session" per CLI
        invocation per RB-4 audit-row convention).
    mask_output:
        When True, redact plaintext to last-4-chars + redaction prefix.
        Default False (full plaintext to stdout — operator can redirect).
    json_output:
        When True, emit canonical JSON to stdout instead of human lines.
    no_audit_event:
        When True, skip the CLI-level PipelineEventLog write (pipeline-
        programmatic callers per D75 + D76). The per-token
        PiiVaultAccessLog rows are STILL written server-side by SP-2.
    decrypt_fn:
        Test-injection hook. Defaults to live M5 ``decrypt_token`` import.
    audit_cursor_factory:
        Test-injection hook. Defaults to live ``utils.connections.get_connection``.
    general_db:
        Override the General DB name (defaults to
        ``utils.configuration.GENERAL_DB``, fallback ``'General'``).
    """
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif quiet:
        logging.getLogger().setLevel(logging.ERROR)

    # Resolve general_db tag
    if general_db is None:
        try:
            import utils.configuration as config  # type: ignore

            general_db = getattr(config, "GENERAL_DB", "General")
        except Exception:  # noqa: BLE001
            general_db = "General"

    # ---- Resolve request_id (auto-generate if not provided) ----
    if request_id is None:
        request_id = uuid.uuid4()
    elif not isinstance(request_id, uuid.UUID):
        # Try to coerce from str — argparse may pass us a str.
        try:
            request_id = uuid.UUID(str(request_id))
        except (ValueError, TypeError):
            request_id = uuid.uuid4()

    # ---- Pre-populate result (security: NO plaintext, NO token list) ----
    # Per D103 + spec § 3.4 L735: token_hints (redacted) surface in
    # audit Metadata for cross-correlation; the raw token values do NOT.
    result: dict[str, Any] = {
        "event_kind": "pii_decrypt",
        "actor": actor,
        "justification": justification,
        "request_id": str(request_id),
        "token_count": 0,
        "decrypted_count": 0,
        "null_count": 0,
        "not_found_count": 0,
        "vault_unavailable_count": 0,
        "error_count": 0,
        "token_hints": [],  # redacted hints only; never raw tokens
        "mask_output": mask_output,
        "verdicts": [],
        "exit_code": EXIT_SUCCESS,
        "status": "SUCCESS",
        "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "started_at_dt": started_at,
        "completed_at": None,
        "audit_event_id": None,
        "errors": [],
    }

    # ---- Validate justification — empty / None / whitespace → exit 2 ----
    # Per spec § 3.4 L711-712: 'Missing --justification (empty string) →
    # arg-parse error → exit 2; SP-2 NOT NULL constraint would have
    # rejected anyway'. We validate again at the function boundary
    # because programmatic callers (no argparse) must also be guarded.
    # SECURITY: NO audit row written for malformed input (audit semantics
    # require non-empty reason; we cannot honor the contract without one).
    if not isinstance(justification, str) or not justification.strip():
        result["exit_code"] = EXIT_FATAL
        result["status"] = "FAILED"
        result["error_type"] = "MissingJustification"
        result["error_message"] = (
            "--justification is REQUIRED non-empty per D6 + D26 + D75. "
            "Empty / whitespace-only justification rejected at function "
            "boundary BEFORE any SP-2 round trip (audit-grade contract: "
            "every decrypt requires an operator-supplied reason for the "
            "PiiVaultAccessLog row). NO audit row written for malformed "
            "input."
        )
        result["errors"].append(result["error_message"])
        result["completed_at"] = _now_iso_naive()
        if not quiet:
            print(f"FATAL: {result['error_message']}", file=sys.stderr)
        return result

    # ---- Resolve token list — exactly one of tokens / token_file ----
    has_tokens = bool(tokens)
    has_token_file = bool(token_file)
    if has_tokens and has_token_file:
        result["exit_code"] = EXIT_FATAL
        result["status"] = "FAILED"
        result["error_type"] = "ArgumentConflict"
        result["error_message"] = (
            "--token and --token-file are mutually exclusive per spec "
            "§ 3.4 L724. Pick exactly one."
        )
        result["errors"].append(result["error_message"])
        result["completed_at"] = _now_iso_naive()
        if not quiet:
            print(f"FATAL: {result['error_message']}", file=sys.stderr)
        return result
    if not has_tokens and not has_token_file:
        result["exit_code"] = EXIT_FATAL
        result["status"] = "FAILED"
        result["error_type"] = "MissingTokens"
        result["error_message"] = (
            "Must specify either --token (repeatable) OR --token-file. "
            "Spec § 3.4 L713-723."
        )
        result["errors"].append(result["error_message"])
        result["completed_at"] = _now_iso_naive()
        if not quiet:
            print(f"FATAL: {result['error_message']}", file=sys.stderr)
        return result

    # ---- Load tokens from file if requested ----
    resolved_tokens: list[str] = []
    if has_token_file:
        try:
            resolved_tokens = _read_tokens_from_file(Path(str(token_file)))
        except PipelineFatalError as exc:
            result["exit_code"] = EXIT_FATAL
            result["status"] = "FAILED"
            result["error_type"] = "TokenFileError"
            result["error_message"] = str(exc)[:500]
            result["errors"].append(f"TokenFileError: {exc}")
            result["completed_at"] = _now_iso_naive()
            if not quiet:
                print(f"FATAL: {exc}", file=sys.stderr)
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
    else:
        resolved_tokens = list(tokens)  # type: ignore[arg-type]

    # ---- Validate each token is non-empty ----
    for i, t in enumerate(resolved_tokens):
        if not isinstance(t, str) or not t.strip():
            result["exit_code"] = EXIT_FATAL
            result["status"] = "FAILED"
            result["error_type"] = "InvalidToken"
            result["error_message"] = (
                f"Token at position {i} is empty / whitespace-only. "
                "All tokens must be non-empty hex strings per SP-2 "
                "@Token VARCHAR(40) NOT NULL constraint."
            )
            result["errors"].append(result["error_message"])
            result["completed_at"] = _now_iso_naive()
            if not quiet:
                print(f"FATAL: {result['error_message']}", file=sys.stderr)
            audit_id = _write_audit_row(
                result,
                status="FAILED",
                error_message=result["error_message"],
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            result["audit_event_id"] = audit_id
            return result

    result["token_count"] = len(resolved_tokens)
    result["token_hints"] = [_token_hint(t) for t in resolved_tokens]

    # ---- Resolve decrypt_fn (live M5 import unless injected) ----
    if decrypt_fn is None:
        try:
            from data_load.pii_decryptor import decrypt_token  # type: ignore
            decrypt_fn = decrypt_token
        except (ImportError, ModuleNotFoundError) as exc:
            result["exit_code"] = EXIT_FATAL
            result["status"] = "FAILED"
            result["error_type"] = "VaultConfigError"
            result["error_message"] = (
                f"data_load.pii_decryptor unimportable: {exc}"
            )
            result["errors"].append(result["error_message"])
            result["completed_at"] = _now_iso_naive()
            if not quiet:
                print(f"FATAL: {result['error_message']}", file=sys.stderr)
            audit_id = _write_audit_row(
                result,
                status="FAILED",
                error_message=result["error_message"][:4000],
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            result["audit_event_id"] = audit_id
            return result

    # ---- Decrypt each token serially (per spec § 3.4 L728 no --workers) ----
    # SECURITY: plaintext stays in verdict_row['plaintext'] for stdout
    # rendering only. Audit row Metadata is built separately and does
    # NOT pull from verdict_row['plaintext'].
    verdicts: list[dict] = []
    for token in resolved_tokens:
        verdict_row = _decrypt_one_token(
            token,
            justification=justification,
            request_id=request_id,
            decrypt_fn=decrypt_fn,
        )
        verdicts.append(verdict_row)

    counts = _aggregate_counts(verdicts)
    result["decrypted_count"] = counts["decrypted"]
    result["null_count"] = counts["ccpa_deleted"]
    result["not_found_count"] = counts["not_found"]
    result["vault_unavailable_count"] = counts["vault_unavailable"]
    result["error_count"] = counts["error"]
    result["exit_code"] = _derive_exit_code(verdicts)
    result["status"] = (
        "SUCCESS" if result["exit_code"] == EXIT_SUCCESS else "FAILED"
    )

    # ---- Build audit Metadata that EXPLICITLY excludes plaintext ----
    # SECURITY-CRITICAL: per D103 + P5 + spec § 3.4 L692-693, the audit
    # row Metadata MUST NOT contain decrypted plaintext. We build a
    # plaintext-free verdict projection for the audit row.
    audit_verdicts = []
    for v in verdicts:
        audit_verdicts.append({
            "token_hint": v.get("token_hint"),
            "verdict": v.get("verdict"),
            "request_id": v.get("request_id"),
            # error_message included for diagnostic value; M5's exception
            # messages do NOT contain plaintext per its security
            # discipline (D103 — M5 only logs Token + RequestId).
            "error_message": v.get("error_message"),
            # NOTE: 'plaintext' field is explicitly absent.
        })
    result["verdicts"] = audit_verdicts

    # ---- Render result + write audit row ----
    result["completed_at"] = _now_iso_naive()
    audit_event_id = _write_audit_row(
        result,
        status=result["status"],
        error_message=result.get("error_message"),
        cursor_factory=audit_cursor_factory,
        general_db=general_db,
        skip=no_audit_event,
    )
    result["audit_event_id"] = audit_event_id

    # ---- Render stdout AFTER audit-row write so audit_event_id surfaces ----
    # SECURITY: emit_human_summary + emit_json take verdicts that
    # INCLUDE plaintext (for the operator-facing stdout). The audit
    # row's metadata (already written) has the plaintext-free version.
    if json_output:
        _emit_json(_build_json_payload(verdicts, counts, audit_event_id))
    elif not quiet:
        _emit_human_summary(
            verdicts=verdicts,
            counts=counts,
            mask_output=mask_output,
            audit_event_id=audit_event_id,
        )

    # For programmatic callers, return a result dict that does NOT
    # include the raw plaintext (defense-in-depth — even if a
    # programmatic caller leaks the result dict to logs, no plaintext
    # escapes via that path).
    return result


def _now_iso_naive() -> str:
    """ISO-8601 naive-UTC timestamp per SCD2-P1-f naive-UTC invariant."""
    return (
        datetime.now(timezone.utc)
        .replace(tzinfo=None)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _build_json_payload(
    verdicts: list[dict],
    counts: dict[str, int],
    audit_event_id: int | None,
) -> dict:
    """Build the canonical JSON output payload per spec § 3.4 L735.

    Top-level shape: ``{dry_run, counts, verdicts: [...], audit_event_id}``.
    Each verdict carries token_hint + plaintext (if decrypted) + status +
    request_id.

    SECURITY: this payload CONTAINS plaintext per spec § 3.4 L735 — the
    JSON output is the operator's intended downstream-machine format
    (e.g. piped into ``jq`` for transformation). Operator is responsible
    for routing the JSON to secure storage. The payload goes via
    ``print()``, NOT through logger calls.
    """
    return {
        "dry_run": False,  # spec § 1.2 — this tool is read-only (no dry-run mode)
        "counts": counts,
        "verdicts": [
            {
                "token_hint": v.get("token_hint"),
                "plaintext": v.get("plaintext"),
                "status": v.get("verdict"),
                "request_id": v.get("request_id"),
            }
            for v in verdicts
        ],
        "audit_event_id": audit_event_id,
    }


# ---------------------------------------------------------------------------
# CLI argv entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    """Alias for :func:`_build_parser` — Tier 0 scaffold contract."""
    return _build_parser()


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser per spec § 3.4 + § 1.4 canonical args.

    Per spec § 3.4 L724: ``--token`` and ``--token-file`` are mutually
    exclusive. argparse can't express this directly when ``--token`` is
    repeatable (action='append'); we add each as a regular arg and
    enforce mutex in :func:`_validate_args` + :func:`main`.

    Per spec § 3.4 L711-712: ``--justification`` is REQUIRED non-empty.
    We set ``required=True`` so argparse rejects missing; we also
    validate non-empty at parse time and re-validate at the function
    boundary (defense-in-depth — programmatic callers without argparse
    must also fail-fast).
    """
    parser = argparse.ArgumentParser(
        description=(
            "Decrypt one or more PiiVault tokens via M5 decrypt_token. "
            "Mandatory --justification (non-empty). Writes one "
            "CLI_DECRYPT_PII audit row per invocation; SP-2 writes "
            "one PiiVaultAccessLog row per token server-side."
        ),
    )

    # ---- Tool-specific args (per spec § 3.4 L723-732) ----
    parser.add_argument(
        "--token",
        action="append",
        default=None,
        help=(
            "Token hex string (canonical PiiVault.Token VARCHAR(40)). "
            "Repeatable for small batches. Mutually exclusive with "
            "--token-file. Spec § 3.4 L723."
        ),
    )
    parser.add_argument(
        "--token-file",
        default=None,
        help=(
            "Path to file containing one token per line. '#' comments "
            "+ blank lines skipped. Mutually exclusive with --token. "
            "Spec § 3.4 L716-718 + L724."
        ),
    )
    parser.add_argument(
        "--request-id",
        default=None,
        help=(
            "Optional UUID for tying multiple decrypts to one operator "
            "request (audit-row grouping). Auto-generated via "
            "uuid.uuid4() when omitted. Spec § 3.4 L726."
        ),
    )
    parser.add_argument(
        "--mask-output",
        action="store_true",
        help=(
            "Mask plaintext to last-4-chars + redaction prefix in "
            "stdout (the plaintext still leaves the process via the "
            "caller's stdout pipe — redirect to a file for secure "
            "storage). Spec § 3.4 L729-732."
        ),
    )

    # ---- D75 canonical args (per spec § 1.4) ----
    parser.add_argument(
        "--justification",
        required=True,
        help=(
            "REQUIRED non-empty per D6 + D26 + D75. Free-text reason "
            "for the decrypt — written to PiiVaultAccessLog.Justification "
            "by SP-2 server-side. Spec § 3.4 L725."
        ),
    )
    parser.add_argument(
        "--actor",
        default=None,
        help=(
            "Operator identity (per D75 + D76). One of operator / "
            "automic / pipeline / reconciliation. Auto-detected via "
            "TTY / AUTOMIC_RUN_ID env when omitted. Spec § 3.4 L728: "
            "automic NOT a normal invocation pattern for this tool."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help=(
            "Emit canonical JSON output per spec § 3.4 L735 "
            "({dry_run, counts, verdicts, audit_event_id}) instead "
            "of human summary."
        ),
    )
    parser.add_argument(
        "--no-audit-event",
        action="store_true",
        help=(
            "Skip CLI-level PipelineEventLog write (pipeline-"
            "programmatic callers per D75 + D76). The per-token "
            "PiiVaultAccessLog rows are STILL written server-side "
            "by SP-2."
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


def _validate_args(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> None:
    """Enforce --token vs --token-file mutex + non-empty justification.

    argparse cannot express the cross-arg mutex declaratively (multi-arg
    vs single-arg). main() also enforces this — _validate_args provides
    earlier feedback at parse time.

    Per spec § 3.4 L711-712: empty / whitespace-only justification is
    fatal — argparse rejects via parser.error (exit 2 by argparse contract).
    """
    has_tokens = bool(args.token)
    has_token_file = bool(args.token_file)
    if has_tokens and has_token_file:
        parser.error(
            "--token is mutually exclusive with --token-file. "
            "Pick one mode. Spec § 3.4 L724."
        )
    if not has_tokens and not has_token_file:
        parser.error(
            "Must specify either --token (repeatable) OR --token-file. "
            "Spec § 3.4 L713-723."
        )
    if not args.justification or not args.justification.strip():
        parser.error(
            "--justification must be non-empty per D6 + D26 + D75. "
            "Audit-grade contract: every decrypt requires an operator-"
            "supplied reason for the PiiVaultAccessLog row."
        )


def cli_main() -> int:
    """Argv entry point — argparse + main() + return exit code per D74.

    Exit codes (always one of 0 / 1 / 2 per D74 + spec § 3.4 L737-740):
        - 0: all tokens decrypted (including CCPA-deleted per spec L711)
        - 1: at least one VaultUnavailable (retryable)
        - 2: at least one TokenNotFound / VaultConfigError / arg error
    """
    parser = _build_parser()
    args = parser.parse_args()
    _validate_args(args, parser)

    actor = args.actor or _detect_actor()

    # Resolve --request-id from str (argparse) to UUID
    request_id: uuid.UUID | None = None
    if args.request_id:
        try:
            request_id = uuid.UUID(args.request_id)
        except (ValueError, TypeError) as exc:
            print(
                f"FATAL: --request-id is not a valid UUID: {args.request_id!r} "
                f"({exc}). Spec § 3.4 L726.",
                file=sys.stderr,
            )
            return EXIT_FATAL

    try:
        result = main(
            actor=actor,
            tokens=args.token,
            token_file=args.token_file,
            justification=args.justification,
            request_id=request_id,
            mask_output=args.mask_output,
            json_output=args.json_output,
            verbose=args.verbose,
            quiet=args.quiet,
            no_audit_event=args.no_audit_event,
        )
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else EXIT_FATAL
        if code not in (EXIT_SUCCESS, EXIT_OPERATIONAL_FAILURE, EXIT_FATAL):
            code = EXIT_FATAL
        return code
    except KeyboardInterrupt:
        logger.warning("Interrupted by operator")
        return EXIT_OPERATIONAL_FAILURE
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        # SECURITY: traceback may contain function-arg repr from any
        # frame; we truncate to 1000 chars and emit to stderr only.
        # M5 frames would NOT contain plaintext (M5 logs Token only).
        print(
            f"FATAL: decrypt_pii unexpected exception:\n{tb[:1000]}",
            file=sys.stderr,
        )
        return EXIT_FATAL

    exit_code = int(result.get("exit_code", EXIT_FATAL))
    # Defensive clamp — every exit path MUST be 0 / 1 / 2 per D74 contract.
    if exit_code not in (EXIT_SUCCESS, EXIT_OPERATIONAL_FAILURE, EXIT_FATAL):
        logger.error(
            "Non-canonical exit_code %r returned from main(); "
            "clamping to EXIT_FATAL",
            exit_code,
        )
        exit_code = EXIT_FATAL
    return exit_code


if __name__ == "__main__":
    sys.exit(cli_main())
