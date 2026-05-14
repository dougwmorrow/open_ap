"""Tier 0 build-time smoke test for utils/errors.py.

Per D67 + D77 — runs at build time + every commit. Runtime ceiling < 5 s.
NO external dependencies (no Docker, no DB, no network) — pure library
hierarchy assertions.

North Star pillars:
  - Operationally stable (D67 Tier 0 discipline: import + hierarchy + ctor
    in < 5 s with zero external I/O; import failure blocks build).
  - Audit-grade (D76 audit-row contract: ``metadata`` kwarg feeds
    PipelineEventLog Metadata field).
  - Idempotent (B85 base classes drive the B-7 retry pattern uniformly).

D-numbers: D67 (Tier 0 discipline), D68 (error class hierarchy),
D74 (exit-code contract — fatal=2, retryable=1), D76 (audit-row contract),
D77 (Tier 0 scaffold pattern), D92 (forward-only additive — new module).

B-numbers: B85 (utils/errors.py authoring — closed by this file + its tests).

Spec: phase1/06_deployment.md § 4.6 (canonical body),
phase1/03_core_modules.md § 8.1 (D68 hierarchy lock).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path (matches tests/ convention)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# (a) Module imports without error
# ---------------------------------------------------------------------------


def test_module_imports():
    """(a) utils/errors.py imports without error.

    Per D67 Tier 0 assertion 1. Verifies no syntax errors, no missing
    dependencies, no import-time side-effects (no DB, no filesystem,
    no env reads).

    Spec: phase1/06_deployment.md § 4.6. Closes B85.
    """
    import utils.errors as errors_mod

    assert errors_mod is not None, (
        "utils.errors must import cleanly. If this fails, check for syntax "
        "errors or missing dependencies in utils/errors.py."
    )
    assert hasattr(errors_mod, "__all__"), (
        "utils.errors must declare __all__ to control the public surface "
        "per Round 6 § 4.6 spec."
    )


# ---------------------------------------------------------------------------
# (b) Three base classes exist with the documented hierarchy
# ---------------------------------------------------------------------------


def test_base_classes_exist_and_inherit_correctly():
    """(b) PipelineError + PipelineFatalError + PipelineRetryableError exist
    with the D68 two-tier hierarchy.

    Per D68: PipelineError is the abstract base; PipelineFatalError and
    PipelineRetryableError both inherit from it. PipelineError itself
    inherits from the stdlib Exception.

    Spec: phase1/03_core_modules.md § 8.1 + phase1/06_deployment.md § 4.6.
    """
    from utils.errors import (
        PipelineError,
        PipelineFatalError,
        PipelineRetryableError,
    )

    assert issubclass(PipelineError, Exception), (
        "PipelineError must inherit from Exception so stdlib catch-all "
        "handlers work."
    )
    assert issubclass(PipelineFatalError, PipelineError), (
        "PipelineFatalError must inherit from PipelineError per D68 two-tier "
        "hierarchy. Round 4 § 1.8 cli_main_wrapper relies on this."
    )
    assert issubclass(PipelineRetryableError, PipelineError), (
        "PipelineRetryableError must inherit from PipelineError per D68."
    )
    assert not issubclass(PipelineFatalError, PipelineRetryableError), (
        "Fatal and Retryable must be siblings, not parent/child — the "
        "§ 1.8 wrapper catches them separately to map to different exit codes."
    )
    assert not issubclass(PipelineRetryableError, PipelineFatalError), (
        "Retryable must NOT be a subclass of Fatal — would cause B-7 retry "
        "logic to mis-classify retryable errors as fatal."
    )


# ---------------------------------------------------------------------------
# (c) Constructor accepts (message, *, metadata=None) per D76
# ---------------------------------------------------------------------------


def test_constructor_signature_per_d76():
    """(c) PipelineError ctor accepts (message, *, metadata=None) per D76.

    Per D76 audit-row contract: the metadata kwarg is forwarded to
    PipelineEventLog.Metadata. Default is an EMPTY DICT (not None) so
    downstream JSON serialization is uniform.

    Spec: phase1/06_deployment.md § 4.6 ctor signature.
    """
    from utils.errors import PipelineError, PipelineFatalError

    # Positional message + no metadata
    err = PipelineError("test message")
    assert str(err) == "test message", "message must round-trip through str()"
    assert err.metadata == {}, (
        "metadata default must be an empty dict, not None. Downstream "
        "JSON serialization assumes metadata is always a dict."
    )

    # Keyword-only metadata
    err = PipelineFatalError("fatal", metadata={"key": "value", "count": 42})
    assert err.metadata == {"key": "value", "count": 42}, (
        "metadata kwarg must be stored verbatim for PipelineEventLog write."
    )

    # metadata must be keyword-only (positional should fail)
    with pytest.raises(TypeError):
        PipelineError("msg", {"positional": "should fail"})


# ---------------------------------------------------------------------------
# (d) Per-module subclasses exist and inherit from correct base
# ---------------------------------------------------------------------------


def test_per_module_subclasses_inherit_correctly():
    """(d) The 19 per-module subclasses inherit from the correct D68 base.

    Maps each subclass to its expected base per Round 6 § 4.6 spec.
    Catches a class whose inheritance was silently changed (e.g. a
    PipelineRetryableError downgraded to PipelineFatalError would break
    the B-7 retry path).

    Spec: phase1/06_deployment.md § 4.6.
    """
    import utils.errors as e

    fatal_subclasses = [
        # § 1 Parquet
        "ParquetWriteCrash",
        "ParquetReplayError",
        "RegistryStatusInvalid",
        "RegistryHashMismatch",
        # § 2 PII / vault
        "VaultConfigError",
        "TokenNotFound",
        "DecryptDenied",
        "PiiColumnNotFound",
        # § 3 Credentials + parity
        "CredentialsLoadError",
        "ParityFatalError",
        "ParityBaselineMissing",
        "ParityProbeError",
        # § 4 Idempotency
        "LedgerStuck",
        "LedgerConfigError",
        "InvalidTrustGate",
        # § 5 Scheduling
        "RangePolicyMissing",
        "InsufficientHistory",
        # § 6 Observability
        "FilterConfigError",
        # § 7 Snowflake
        "SnowflakeAuthFailed",
        "SnowflakeBudgetAlert",
        # Round 4 cross-cutting
        "LegalHoldConflict",
        "MigrationError",
    ]
    retryable_subclasses = [
        # § 1 Parquet
        "RegistryInsertConflict",
        "RegistryFileNotFound",
        # § 2 PII / vault
        "VaultUnavailable",
        # § 4 Idempotency
        "LedgerStepFailed",
        "LedgerLockTimeout",
        "ExtractionStateUnavailable",
        # § 5 Scheduling
        "GapDetectorTimeout",
        # § 7 Snowflake
        "SnowflakeCopyTimeout",
    ]

    for name in fatal_subclasses:
        cls = getattr(e, name, None)
        assert cls is not None, (
            f"{name} must be defined in utils.errors per Round 6 § 4.6."
        )
        assert issubclass(cls, e.PipelineFatalError), (
            f"{name} must inherit from PipelineFatalError (exit code 2 per "
            f"D74). If this fails, the class was downgraded to retryable "
            f"or to plain Exception."
        )

    for name in retryable_subclasses:
        cls = getattr(e, name, None)
        assert cls is not None, (
            f"{name} must be defined in utils.errors per Round 6 § 4.6."
        )
        assert issubclass(cls, e.PipelineRetryableError), (
            f"{name} must inherit from PipelineRetryableError (exit code 1 "
            f"per D74, B-7 retry pattern). If this fails, the class was "
            f"upgraded to fatal — verify retry-vs-fatal classification."
        )


# ---------------------------------------------------------------------------
# (e) Raise + catch by base type works (the § 1.8 wrapper relies on this)
# ---------------------------------------------------------------------------


def test_raise_and_catch_by_base_class():
    """(e) Round 4 § 1.8 cli_main_wrapper catches PipelineFatalError /
    PipelineRetryableError generically. Verify a per-module subclass
    raised gets caught by its base.

    Without this, the § 1.8 wrapper would mis-classify the exit code,
    breaking the D74 contract.

    Spec: phase1/04_tools.md § 1.8.
    """
    from utils.errors import (
        CredentialsLoadError,
        PipelineFatalError,
        PipelineRetryableError,
        VaultUnavailable,
    )

    # CredentialsLoadError is fatal — must be caught by PipelineFatalError
    caught_as_fatal = False
    try:
        raise CredentialsLoadError("test fatal", metadata={"layer": "gpg"})
    except PipelineFatalError as exc:
        caught_as_fatal = True
        assert exc.metadata == {"layer": "gpg"}
    assert caught_as_fatal, (
        "CredentialsLoadError must be catchable as PipelineFatalError — "
        "the § 1.8 wrapper depends on this for exit code 2 mapping."
    )

    # VaultUnavailable is retryable — must be caught by PipelineRetryableError
    caught_as_retryable = False
    try:
        raise VaultUnavailable("test retryable", metadata={"attempt": 2})
    except PipelineRetryableError as exc:
        caught_as_retryable = True
        assert exc.metadata == {"attempt": 2}
    assert caught_as_retryable, (
        "VaultUnavailable must be catchable as PipelineRetryableError — "
        "the B-7 retry pattern depends on this."
    )


# ---------------------------------------------------------------------------
# (f) Metadata default is per-instance (no mutable-default bug)
# ---------------------------------------------------------------------------


def test_metadata_default_not_shared_across_instances():
    """(f) metadata default ``{}`` is per-instance, not shared.

    Guards against the classic Python mutable-default bug — if metadata
    were a module-level dict shared across instances, mutating one
    exception's metadata would silently pollute another's.

    Spec: phase1/06_deployment.md § 4.6 ctor design.
    """
    from utils.errors import PipelineError

    err_a = PipelineError("a")
    err_b = PipelineError("b")

    err_a.metadata["polluted"] = True

    assert err_b.metadata == {}, (
        "Each exception must have its OWN metadata dict. If err_b.metadata "
        "contains 'polluted', a mutable default is shared across instances "
        "— this would silently corrupt audit-row data."
    )
    assert err_a.metadata == {"polluted": True}
