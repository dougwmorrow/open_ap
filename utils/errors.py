"""Pipeline error class hierarchy per D68 + Round 6 § 4.6 spec (closes B85).

Two top-level base classes (per D68 + Round 3 § 8.1 + Round 6 § 4.6):

- :class:`PipelineError` — abstract base; all pipeline-emitted exceptions
  inherit. Never raised directly.
- :class:`PipelineFatalError` — unrecoverable. CLI exit code 2 per D74;
  logged at CRITICAL by the § 1.8 wrapper. No retry.
- :class:`PipelineRetryableError` — transient. CLI exit code 1 per D74;
  retry per B-7 ``cx_read_sql_safe`` pattern (exponential backoff, max 3
  attempts, base delay 2 s); logged at WARNING on retry, ERROR on terminal.

Per-module subclasses live here so every Round 3 module + Round 4 CLI tool
imports from a single canonical surface (avoids the temptation to redefine
the same class in multiple modules — see the naming-collision note below).

Constructor contract
====================

Every subclass accepts ``(message: str, *, metadata: dict | None = None)``.
The ``metadata`` dict is forwarded to ``PipelineEventLog.Metadata`` by the
CLI's § 1.8 wrapper (per D76 audit-row contract). Keep keys JSON-safe;
never include plaintext PII (the :class:`observability.sensitive_data_filter
.SensitiveDataFilter` is the last-mile redactor, but callers should not
rely on it for primary safety).

Usage example::

    from utils.errors import PipelineFatalError, VaultUnavailable

    try:
        result = call_vault_sp(...)
    except pyodbc.OperationalError as exc:
        raise VaultUnavailable(
            "vault DB unreachable mid-SP-1",
            metadata={"sp_name": "PiiVault_GetOrCreateToken", "attempt": 2},
        ) from exc

Round 4 § 1.8 boilerplate ``cli_main_wrapper`` catches the two BASE classes
and maps them to exit codes uniformly — operator-facing tools NEVER need
per-subclass handling. The subclass name appears in stderr + PipelineLog
for diagnostics.

Naming collision with ``data_load._exceptions``
================================================

``data_load/_exceptions.py`` defines a SEPARATE ``ParityFatalError`` /
``VaultUnavailable`` / ``VaultConfigError`` hierarchy intentionally
(subclasses of plain :class:`Exception`) to keep that CLI-boundary module
dependency-free from this engine-level hierarchy. The two will reconcile
in a follow-up migration B-item; for now, callers should pick the one
their boundary documents:

- Engine / module-internal code → ``utils.errors.*`` (this module)
- CLI parse-time / argparse boundary in tools/ → ``data_load._exceptions.*``

When the migration lands (tracked as **B-222**), ``data_load._exceptions``
will re-export the canonical ``utils.errors`` versions, retiring the
duplicate definitions. DO NOT introduce a third copy of any of these
names elsewhere.

D-numbers consumed
==================

- D68 — error class hierarchy + retry semantics
- D74 — CLI exit-code contract (0 / 1 / 2)
- D76 — CLI audit-row contract (metadata kwarg feeds PipelineEventLog)
- D92 — forward-only additive (new module; no existing API renamed)

B-numbers closed
================

- B85 — ``utils/errors.py`` authoring per § 4.6 spec.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    # Base classes
    "PipelineError",
    "PipelineFatalError",
    "PipelineRetryableError",
    # § 1 Parquet layer
    "ParquetReplayError",
    "ParquetWriteCrash",
    "RegistryFileNotFound",
    "RegistryHashMismatch",
    "RegistryInsertConflict",
    "RegistryNotFound",
    "RegistryStatusInvalid",
    # § 2 PII / vault layer
    "DecryptDenied",
    "PiiColumnNotFound",
    "TokenNotFound",
    "VaultConfigError",
    "VaultUnavailable",
    # § 3 Credentials + parity
    "CredentialsLoadError",
    "ParityBaselineMissing",
    "ParityFatalError",
    "ParityProbeError",
    # § 4 Idempotency + extraction state
    "InvalidTrustGate",
    "LedgerConfigError",
    "LedgerLockTimeout",
    "LedgerStepFailed",
    "LedgerStuck",
    "ExtractionStateUnavailable",
    # § 5 Scheduling + lateness + gaps
    "GapDetectorTimeout",
    "InsufficientHistory",
    "RangePolicyMissing",
    # § 6 Observability
    "FilterConfigError",
    # § 7 Snowflake
    "SnowflakeAuthFailed",
    "SnowflakeBudgetAlert",
    "SnowflakeCopyTimeout",
    # § Round 4 cross-cutting
    "LegalHoldConflict",
    "MigrationError",
]


# ---------------------------------------------------------------------------
# Base classes (D68 two-tier hierarchy)
# ---------------------------------------------------------------------------


class PipelineError(Exception):
    """Abstract base for all pipeline-emitted exceptions. Never raise directly.

    All subclasses accept ``(message: str, *, metadata: dict | None = None)``.
    ``metadata`` is forwarded to ``PipelineEventLog.Metadata`` per D76.
    """

    def __init__(self, message: str, *, metadata: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.metadata: dict[str, Any] = metadata or {}


class PipelineFatalError(PipelineError):
    """Unrecoverable pipeline error. CLI exit code 2 per D74.

    The § 1.8 ``cli_main_wrapper`` logs at CRITICAL and returns exit 2.
    Operators are paged; intervention required. No retry.
    """


class PipelineRetryableError(PipelineError):
    """Transient pipeline error. CLI exit code 1 per D74.

    Retry per B-7 ``cx_read_sql_safe`` pattern (exponential backoff, max 3
    attempts, base delay 2 s). Logged at WARNING on retry, ERROR on the
    terminal attempt. Operator review (not page-able).
    """


# ---------------------------------------------------------------------------
# § 1 Parquet layer (Round 3 § 1.1 – § 1.3)
# ---------------------------------------------------------------------------


class ParquetWriteCrash(PipelineFatalError):
    """Inflight ``.parquet.inflight`` file exists but atomic rename failed.

    Per Round 3 § 1.1 — filesystem-level failure (ENOSPC, EACCES, network
    drive dropped). Operator must inspect; the inflight file is recoverable
    (RB-6 vault-recovery path mirrors the pattern).
    """


class ParquetReplayError(PipelineFatalError):
    """Registry row exists but file is missing OR file SHA-256 doesn't match.

    Per Round 3 § 1.2 — escalate to RB-6 vault recovery + RB-8 rebuild.
    Indicates corruption or rogue manual deletion on the Parquet network
    drive.
    """


class RegistryInsertConflict(PipelineRetryableError):
    """UNIQUE violation on ``ParquetSnapshotRegistry`` INSERT.

    Per Round 3 § 1.1 — concurrent ``--workers`` race on the same
    ``(BatchId, SourceName, TableName, BusinessDate)`` tuple. Retry per B-7;
    caller may query the registry to detect the winner before retry.
    """


class RegistryStatusInvalid(PipelineFatalError):
    """Caller attempted a registry transition from an incompatible predecessor.

    Per Round 3 § 1.3 — e.g. ``purged → verified`` is rejected by the
    state-machine. Or replay attempted against
    ``Status IN ('created', 'missing', 'purged', 'replication_failed')``.
    """


class RegistryFileNotFound(PipelineRetryableError):
    """Verification target file is absent from the Parquet network drive.

    Per Round 4 § 3.2 — transient mount issue OR permanent loss (escalate
    via separate ``mark_missing`` transition). Retryable so a remount can
    rescue the file before the verifier marks it ``missing``.
    """


class RegistryHashMismatch(PipelineFatalError):
    """Computed SHA-256 doesn't match the registry-recorded hash.

    Per Round 3 § 1.3 — possible corruption (bit rot, partial write that
    survived rename via filesystem-cache race). Escalate to RB-6.
    """


class RegistryNotFound(PipelineFatalError):
    """Registry row absent for a registry_id the caller treated as valid.

    Per Round 3 § 1.3 — every mutating transition reads the existing row
    via ``WHERE RegistryId = ?``; a missing row means the caller passed a
    stale or fabricated ID. Distinct from :class:`RegistryFileNotFound`
    (which is about the on-disk Parquet file). Added 2026-05-13 to back
    M3 ``parquet_registry_client.py`` refactor away from local-exception
    classes per D68 + B-228.
    """


# ---------------------------------------------------------------------------
# § 2 PII / vault layer (Round 3 § 2.1 – § 2.3)
# ---------------------------------------------------------------------------


class VaultUnavailable(PipelineRetryableError):
    """Vault DB connection drop OR transient lock timeout mid-SP invocation.

    Per Round 3 § 2.3 — SP-1 / SP-2 connection failure, deadlock victim,
    or ``sp_getapplock`` contention. Retry per B-7.
    """


class VaultConfigError(PipelineFatalError):
    """``VAULT_DB_*`` env keys missing OR vault DB unreachable at startup.

    Per Round 3 § 2.3 + Round 3 § 3.1 — surfaces at pipeline startup
    when ``vault_client.configure_vault_connection_pool()`` runs. Operator
    must fix env / connectivity before any subsequent run.
    """


class TokenNotFound(PipelineFatalError):
    """SP-2 decrypt requested for a token absent from PiiVault.

    Per Round 3 § 2.2 — never silently return None; surface as fatal so
    the caller cannot accidentally treat "missing" as "ok". Indicates
    either a configuration drift (wrong vault) or audit-trail tampering.
    """


class DecryptDenied(PipelineFatalError):
    """SP-2 returned NULL plaintext because the token's Status is non-decrypt.

    Per Round 3 § 2.2 + D30 + RB-10 — typically
    ``Status = 'deleted_per_request'`` (CCPA right-to-deletion). Operators
    should never bypass this; the deletion was authorized. Note: B103
    docstring-contradiction resolved per Round 6 § 7.9 — this class IS
    raised by the SP-2 wrapper.
    """


class PiiColumnNotFound(PipelineFatalError):
    """``UdmTablesList.PiiColumnList`` names a column absent from the source DataFrame.

    Per Round 3 § 2.1 — configuration drift. Operator must reconcile
    ``UdmTablesList.PiiColumnList`` against the source schema before retry.
    """


# ---------------------------------------------------------------------------
# § 3 Credentials + parity (Round 3 § 3.1 – § 3.2 + Round 4 § 3.7)
# ---------------------------------------------------------------------------


class CredentialsLoadError(PipelineFatalError):
    """GPG-decrypt failed OR ``tpm2_unseal`` returned non-zero OR schema_version drift.

    Per Round 3 § 3.1 — envelope missing, unreadable, or the decrypted
    dict still contains the ``'GPG_SOURCED'`` sentinel (re-substitution
    bug). Operator must fix the envelope + TPM2 state.
    """


class ParityFatalError(PipelineFatalError):
    """Fatal-tier parity drift between test and prod per D65 severity tiers.

    Per Round 3 § 3.2 + Round 4 § 3.6 / § 3.7 — pipeline MUST NOT proceed.
    See also ``data_load._exceptions.ParityFatalError`` (separate class,
    plain ``Exception`` subclass, intentionally dependency-free at CLI
    boundary — naming collision documented in module docstring).
    """


class ParityBaselineMissing(PipelineFatalError):
    """``/etc/pipeline/parity_baseline.json`` absent or malformed.

    Per Round 3 § 3.2 + Round 4 § 3.7 — fatal; operator must regenerate
    the baseline via ``tools/capture_parity_baseline.py``.
    """


class ParityProbeError(PipelineFatalError):
    """System probe failed (e.g. ``tpm2_getcap`` returned non-zero).

    Per Round 3 § 3.2 — itself a parity violation per F21 (hardware fault
    is a fatal-tier divergence from the parity baseline expectations).
    """


# ---------------------------------------------------------------------------
# § 4 Idempotency + extraction state (Round 3 § 4.1 – § 4.2)
# ---------------------------------------------------------------------------


class LedgerStepFailed(PipelineRetryableError):
    """``ledger_step`` context manager caught an exception in the wrapped block.

    Per Round 3 § 4.1 — the caller's exception is the ``__cause__``;
    ``LedgerStepFailed`` bubbles up AFTER the ledger row is marked
    ``FAILED``. Retryable by default; callers that wrap an inherently
    fatal block should raise the underlying ``PipelineFatalError`` and
    let the wrapper handle the ledger transition.
    """


class LedgerStuck(PipelineFatalError):
    """Startup recovery sweep found > N stale ``IN_PROGRESS`` ledger rows.

    Per Round 3 § 4.1 (I19 startup recovery) — ``N=10`` configurable.
    Indicates a systemic crash pattern; operator intervention required.
    """


class LedgerConfigError(PipelineFatalError):
    """``IdempotencyLedger`` table missing OR schema mismatch at module import.

    Per Round 3 § 4.1 — surfaces only at first use; module import does NOT
    run the schema probe (would create a circular dependency with database
    bootstrap).
    """


class LedgerLockTimeout(PipelineRetryableError):
    """``sp_getapplock`` contention during ``ledger_step`` acquisition.

    Per Round 3 § 1.2 — concurrent replay attempts on the same Parquet
    snapshot. Retry per B-7.
    """


class ExtractionStateUnavailable(PipelineRetryableError):
    """``PipelineExtraction`` table connection failure during state lookup.

    Per Round 3 § 4.2 — transient DB connectivity; retry per B-7.
    """


class InvalidTrustGate(PipelineFatalError):
    """``is_date_trusted`` called with a date in the future OR before ``FirstLoadDate``.

    Per Round 3 § 4.2 — configuration error (caller has the wrong
    ``FirstLoadDate`` OR a stale clock). Operator must reconcile config.
    """


# ---------------------------------------------------------------------------
# § 5 Scheduling + lateness + gaps (Round 3 § 5.1 – § 5.3)
# ---------------------------------------------------------------------------


class RangePolicyMissing(PipelineFatalError):
    """``ExtractionRangePolicy`` row absent for a table that requires explicit policy.

    Per Round 3 § 5.1 — operator must INSERT a row before the
    ``range_scheduler`` can plan extractions for this table.
    """


class InsufficientHistory(PipelineFatalError):
    """Lateness profiler invoked with < ``min_days`` of history.

    Per Round 3 § 5.2 — percentiles unstable below ``min_days`` (default
    30). Operator can override via ``min_days`` parameter if a smaller
    sample is acceptable for a one-off probe.
    """


class GapDetectorTimeout(PipelineRetryableError):
    """Gap-detection query exceeded 60 s timeout.

    Per Round 3 § 5.3 — retry per B-7. Persistent timeout indicates the
    ``PipelineExtraction`` table needs an index (track via separate B-N).
    """


# ---------------------------------------------------------------------------
# § 6 Observability (Round 3 § 6.1 – § 6.3)
# ---------------------------------------------------------------------------


class FilterConfigError(PipelineFatalError):
    """``SensitiveDataFilter`` pattern compilation failed at module import.

    Per Round 3 § 6.1 — raised ONLY at import; NEVER during filtering (a
    filter exception would lose log lines). Operator must fix the pattern
    list in the filter config.
    """


# ---------------------------------------------------------------------------
# § 7 Snowflake (Round 3 § 7.1)
# ---------------------------------------------------------------------------


class SnowflakeAuthFailed(PipelineFatalError):
    """Snowflake RSA-key decrypt OR ``CONNECT`` failed.

    Per Round 3 § 7.1 + D71 — typically a stale RSA envelope, a stale
    public key registered in Snowflake, or a role / network policy
    misconfiguration. Operator must rotate.
    """


class SnowflakeBudgetAlert(PipelineFatalError):
    """Snowflake credit usage > 80% of monthly cap per D23.

    Per Round 3 § 7.1 + D23 ($120K / year ceiling) — fatal by default;
    callers wanting non-blocking alerting should catch + log + continue.
    The default-fatal semantics encode the budget discipline at the type
    level.
    """


class SnowflakeCopyTimeout(PipelineRetryableError):
    """Snowflake ``COPY INTO`` exceeded timeout.

    Per Round 3 § 7.1 — retry per B-7. Persistent timeout suggests a
    file-size or partition-layout regression (track via capacity baseline).
    """


# ---------------------------------------------------------------------------
# Round 4 cross-cutting (per Round 4 § 3.9 + Round 6 § 4.1)
# ---------------------------------------------------------------------------


class LegalHoldConflict(PipelineFatalError):
    """CCPA deletion request targets a token under legal hold.

    Per Round 4 § 3.9 — operator must resolve the legal-hold question
    BEFORE the deletion can proceed (the deletion would otherwise destroy
    evidence under hold, a separate compliance violation).
    """


class MigrationError(PipelineFatalError):
    """Migration script ``apply()`` raised after partial DDL execution.

    Per Round 6 § 4.1 — operator must inspect the partial state; the
    migration framework's idempotency guard (B-7-style ledger row + DDL
    transaction wrap where supported) determines what to roll back vs
    re-attempt.
    """
