"""Tier 1 unit test for utils/errors.py.

Per D70 Tier 1 — per-edge-case + per-error-path coverage; <5 min runtime;
≥90% line coverage on the module. Complements Tier 0 (smoke) by walking
the per-subclass semantics + cross-cutting invariants.

North Star pillars:
  - Operationally stable (every error path is asserted to surface the
    correct base type so § 1.8 wrapper exit codes stay aligned with D74).
  - Audit-grade (metadata round-trips through raise → catch → log without
    mutation or loss).
  - Idempotent (B-7 retry pattern relies on PipelineRetryableError; one
    mis-classification breaks pipeline durability).

Spec: phase1/06_deployment.md § 4.6 + phase1/03_core_modules.md § 8.1 + D68.

B-numbers: B85 (utils/errors.py — closed by this file's pass).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Hierarchy invariants — base class semantics
# ---------------------------------------------------------------------------


class TestBaseClassSemantics:
    """PipelineError + PipelineFatalError + PipelineRetryableError must
    obey the D68 two-tier hierarchy + D76 metadata ctor contract."""

    def test_pipeline_error_is_abstract_in_spirit(self):
        """PipelineError can technically be raised (Python has no abstract
        method enforcement at the Exception level) but the docstring says
        "Never raised directly." This test pins the docstring claim so a
        future edit can't silently remove it."""
        from utils.errors import PipelineError

        assert "Never raise directly" in (PipelineError.__doc__ or ""), (
            "PipelineError docstring must document the 'never raise directly' "
            "convention so future readers don't introduce direct raises."
        )

    def test_fatal_documents_exit_code_2(self):
        """PipelineFatalError docstring must reference exit code 2 per D74."""
        from utils.errors import PipelineFatalError

        assert "exit code 2" in (PipelineFatalError.__doc__ or "").lower(), (
            "PipelineFatalError docstring must reference D74 exit code 2 "
            "explicitly. Round 4 § 1.8 wrapper relies on this convention."
        )

    def test_retryable_documents_b7_pattern(self):
        """PipelineRetryableError docstring must reference B-7 retry pattern."""
        from utils.errors import PipelineRetryableError

        doc = (PipelineRetryableError.__doc__ or "").lower()
        assert "b-7" in doc or "exponential backoff" in doc, (
            "PipelineRetryableError docstring must reference B-7 / exponential "
            "backoff so callers know the retry pattern applies."
        )

    def test_metadata_is_dict_after_ctor(self):
        """metadata is ALWAYS a dict post-construction (never None)."""
        from utils.errors import PipelineError

        for arg in [None, {}, {"key": "value"}]:
            err = PipelineError("msg", metadata=arg)
            assert isinstance(err.metadata, dict), (
                f"metadata must be a dict regardless of ctor arg ({arg!r}). "
                "Downstream JSON serialization assumes dict, not None."
            )

    def test_message_is_str_arg(self):
        """str(exc) returns the message argument verbatim."""
        from utils.errors import PipelineFatalError

        err = PipelineFatalError("specific error context")
        assert str(err) == "specific error context"

    def test_metadata_kwarg_only(self):
        """metadata MUST be keyword-only — passing it positionally must fail.

        Guards against ``PipelineError("msg", {"key": "val"})`` silently
        passing the dict as a second positional Exception arg (where it
        would be accessible as ``exc.args[1]`` instead of ``exc.metadata``).
        """
        from utils.errors import PipelineRetryableError

        with pytest.raises(TypeError):
            PipelineRetryableError("msg", {"should": "fail"})


# ---------------------------------------------------------------------------
# Subclass classification — every subclass goes to the right exit code
# ---------------------------------------------------------------------------


_FATAL_SUBCLASSES = [
    "ParquetWriteCrash",
    "ParquetReplayError",
    "RegistryStatusInvalid",
    "RegistryHashMismatch",
    "RegistryNotFound",
    "VaultConfigError",
    "TokenNotFound",
    "DecryptDenied",
    "PiiColumnNotFound",
    "CredentialsLoadError",
    "ParityFatalError",
    "ParityBaselineMissing",
    "ParityProbeError",
    "LedgerStuck",
    "LedgerConfigError",
    "InvalidTrustGate",
    "RangePolicyMissing",
    "InsufficientHistory",
    "FilterConfigError",
    "SnowflakeAuthFailed",
    "SnowflakeBudgetAlert",
    "LegalHoldConflict",
    "MigrationError",
]

_RETRYABLE_SUBCLASSES = [
    "RegistryInsertConflict",
    "RegistryFileNotFound",
    "VaultUnavailable",
    "LedgerStepFailed",
    "LedgerLockTimeout",
    "ExtractionStateUnavailable",
    "GapDetectorTimeout",
    "SnowflakeCopyTimeout",
]


@pytest.mark.parametrize("name", _FATAL_SUBCLASSES)
def test_fatal_subclass_inherits_from_fatal_base(name):
    """Every named fatal subclass inherits from PipelineFatalError.

    If this fails, the class was downgraded to retryable (or to plain
    Exception) — the § 1.8 wrapper would mis-map its exit code, breaking
    the D74 contract for that error path.
    """
    import utils.errors as e

    cls = getattr(e, name, None)
    assert cls is not None, f"{name} missing from utils.errors"
    assert issubclass(cls, e.PipelineFatalError), (
        f"{name} must be PipelineFatalError. Verify Round 6 § 4.6 spec "
        "hasn't been amended to reclassify this error."
    )


@pytest.mark.parametrize("name", _RETRYABLE_SUBCLASSES)
def test_retryable_subclass_inherits_from_retryable_base(name):
    """Every named retryable subclass inherits from PipelineRetryableError.

    If this fails, the B-7 retry pattern would skip the retry loop and
    treat the error as fatal — operational stability regression.
    """
    import utils.errors as e

    cls = getattr(e, name, None)
    assert cls is not None, f"{name} missing from utils.errors"
    assert issubclass(cls, e.PipelineRetryableError), (
        f"{name} must be PipelineRetryableError. Verify Round 6 § 4.6 spec "
        "hasn't been amended to reclassify this error."
    )


@pytest.mark.parametrize("name", _FATAL_SUBCLASSES + _RETRYABLE_SUBCLASSES)
def test_all_subclasses_accept_metadata_kwarg(name):
    """Every per-module subclass inherits the D76 metadata kwarg contract.

    Without this, a CLI catching PipelineError generically and reading
    ``exc.metadata`` would AttributeError on subclasses that overrode
    __init__ without forwarding metadata.
    """
    import utils.errors as e

    cls = getattr(e, name)
    err = cls("test", metadata={"k": "v"})
    assert err.metadata == {"k": "v"}, (
        f"{name}.__init__ must forward metadata kwarg to PipelineError.__init__."
    )


# ---------------------------------------------------------------------------
# Catch-by-base semantics — the § 1.8 wrapper contract
# ---------------------------------------------------------------------------


class TestCatchByBaseClass:
    """Round 4 § 1.8 cli_main_wrapper catches PipelineFatalError /
    PipelineRetryableError generically. Per-subclass raises MUST round-trip
    through the base-class catch."""

    @pytest.mark.parametrize("name", _FATAL_SUBCLASSES)
    def test_fatal_subclass_caught_by_pipelinefatalerror(self, name):
        """raise SubclassError → catch PipelineFatalError → exc preserves type."""
        import utils.errors as e

        cls = getattr(e, name)
        with pytest.raises(e.PipelineFatalError) as exc_info:
            raise cls("test")
        assert isinstance(exc_info.value, cls), (
            f"caught exception must preserve {name} identity for diagnostics"
        )

    @pytest.mark.parametrize("name", _RETRYABLE_SUBCLASSES)
    def test_retryable_subclass_caught_by_pipelineretryableerror(self, name):
        """raise SubclassError → catch PipelineRetryableError → preserves type."""
        import utils.errors as e

        cls = getattr(e, name)
        with pytest.raises(e.PipelineRetryableError) as exc_info:
            raise cls("test")
        assert isinstance(exc_info.value, cls)

    def test_pipelineerror_catches_both_branches(self):
        """The PipelineError base class catches both fatal and retryable.

        This is the ultimate fallback in § 1.8 — if a future tool author
        catches PipelineError generically, they MUST get both branches.
        """
        from utils.errors import (
            PipelineError,
            PipelineFatalError,
            PipelineRetryableError,
        )

        with pytest.raises(PipelineError):
            raise PipelineFatalError("fatal")
        with pytest.raises(PipelineError):
            raise PipelineRetryableError("retryable")

    def test_fatal_not_caught_as_retryable(self):
        """PipelineFatalError MUST NOT be caught by PipelineRetryableError.

        If this fails, the B-7 retry pattern would attempt to retry a
        fatal error (e.g. missing credentials) — wasted attempts + delay
        before the operator is paged.
        """
        from utils.errors import PipelineFatalError, PipelineRetryableError

        with pytest.raises(PipelineFatalError):
            try:
                raise PipelineFatalError("fatal")
            except PipelineRetryableError:
                pytest.fail("Fatal must NOT be caught as retryable")

    def test_retryable_not_caught_as_fatal(self):
        """PipelineRetryableError MUST NOT be caught by PipelineFatalError.

        If this fails, retryable errors would short-circuit to the fatal
        exit code 2 — Automic would page on transient connection drops.
        """
        from utils.errors import PipelineFatalError, PipelineRetryableError

        with pytest.raises(PipelineRetryableError):
            try:
                raise PipelineRetryableError("retryable")
            except PipelineFatalError:
                pytest.fail("Retryable must NOT be caught as fatal")


# ---------------------------------------------------------------------------
# Exception chaining — `raise ... from exc` must preserve __cause__
# ---------------------------------------------------------------------------


class TestExceptionChaining:
    """Per Round 3 § 8 + Python idiom, callers use ``raise X from underlying``
    to preserve the underlying exception as ``__cause__``. The metadata
    contract must not break that mechanism."""

    def test_raise_from_preserves_cause(self):
        """raise PipelineFatalError(...) from pyodbc_error → __cause__ preserved."""
        from utils.errors import VaultConfigError

        underlying = RuntimeError("pyodbc connection drop")
        try:
            try:
                raise underlying
            except RuntimeError as exc:
                raise VaultConfigError("env keys missing") from exc
        except VaultConfigError as wrapped:
            assert wrapped.__cause__ is underlying, (
                "raise ... from exc must preserve __cause__ for diagnostics."
            )
            assert str(wrapped) == "env keys missing"

    def test_metadata_independent_from_cause(self):
        """metadata is per-instance; chaining doesn't merge metadata."""
        from utils.errors import VaultUnavailable

        with pytest.raises(VaultUnavailable) as exc_info:
            try:
                raise RuntimeError("transient")
            except RuntimeError as exc:
                raise VaultUnavailable(
                    "retryable", metadata={"attempt": 1}
                ) from exc

        assert exc_info.value.metadata == {"attempt": 1}, (
            "metadata must remain the value passed at ctor, regardless of "
            "exception chaining."
        )


# ---------------------------------------------------------------------------
# Metadata-content discipline — keys are JSON-safe per D76
# ---------------------------------------------------------------------------


class TestMetadataContent:
    """D76 audit-row contract — metadata feeds PipelineEventLog Metadata
    field as JSON. Callers should pass JSON-safe values. This module does
    NOT enforce the type at runtime (would be expensive on every raise),
    but the docstring documents the contract and these tests pin the
    "metadata is stored as-is" semantics that downstream JSON serializers
    rely on."""

    def test_nested_dict_preserved(self):
        from utils.errors import PipelineFatalError

        meta = {"outer": {"inner": [1, 2, 3]}, "count": 0}
        err = PipelineFatalError("msg", metadata=meta)
        assert err.metadata == meta

    def test_empty_metadata_serializes_as_empty_dict(self):
        """The default empty-dict (not None) is significant for downstream
        json.dumps(exc.metadata) — None would render as "null", dict as "{}"."""
        import json

        from utils.errors import PipelineError

        err = PipelineError("msg")
        # json.dumps must succeed and produce "{}"
        assert json.dumps(err.metadata) == "{}"


# ---------------------------------------------------------------------------
# __all__ surface — every export is importable and every fatal/retryable
# subclass appears in __all__
# ---------------------------------------------------------------------------


def test_all_subclasses_in_module_all():
    """__all__ must include every base class + every subclass.

    Without this, ``from utils.errors import *`` would silently miss
    subclasses, and the public API surface in the module docstring
    would lie.
    """
    import utils.errors as e

    expected = (
        ["PipelineError", "PipelineFatalError", "PipelineRetryableError"]
        + _FATAL_SUBCLASSES
        + _RETRYABLE_SUBCLASSES
    )

    missing = [name for name in expected if name not in e.__all__]
    assert not missing, (
        f"__all__ is missing these classes: {missing}. Add them to the "
        "__all__ list in utils/errors.py."
    )

    # And every name in __all__ must actually exist as an attribute
    for name in e.__all__:
        assert hasattr(e, name), (
            f"__all__ references {name!r} but it is not defined in the module."
        )


def test_no_unexpected_extra_exports():
    """__all__ must not export anything beyond the documented contract.

    If a future edit adds a new class to __all__ without adding it here,
    this test fails — forces the author to either add the test parameter
    or remove the class from __all__.
    """
    import utils.errors as e

    documented = set(
        ["PipelineError", "PipelineFatalError", "PipelineRetryableError"]
        + _FATAL_SUBCLASSES
        + _RETRYABLE_SUBCLASSES
    )
    extra = set(e.__all__) - documented
    assert not extra, (
        f"__all__ exports undocumented classes: {extra}. Either add them to "
        f"_FATAL_SUBCLASSES / _RETRYABLE_SUBCLASSES in this test file, or "
        "remove them from __all__ in utils/errors.py."
    )
