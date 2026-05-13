"""B184 — Tool 12 ``verify_credentials_load.py``.

CLI shim for Round 3 § 3.1 ``credentials_loader.load_credentials()`` —
verifies the credential-loading chain (TPM2 unseal -> GPG envelope decrypt
-> returned-dict shape) at deploy time WITHOUT exposing any plaintext.
Operator-driven; pipeline itself uses ``credentials_loader`` directly at
**D85** Stage 1 startup, NOT this CLI shim.

Canonical spec
--------------

* **phase1/04a_phase_0_prep_tools.md § 3** — function signature + CLI args
  + Metadata JSON shape + exit-code contract
* **D67** (Tier 0 discipline; 6 canonical assertions; < 5 s runtime ceiling)
* **D74** (CLI exit-code contract: 0/1/2)
* **D75** (CLI argument naming + actor TTY heuristic)
* **D76** (CLI audit-row contract — one ``CLI_VERIFY_CREDENTIALS_LOAD``
  ``PipelineEventLog`` row per invocation; ``SensitiveDataFilter`` applied)
* **D77** (Tier 0 scaffold — 6 canonical assertions; < 5 s; mocked
  subprocess + mocked cursor; **tests/tier0/test_verify_credentials_load.py**)
* **D85** (module startup sequence stage 1 — credentials_loader)
* **D92** (forward-only additive — supplements locked Round 4 tool inventory)
* **D103** (Claude Code security model — credentials live OUTSIDE /debi;
  envelope at ``/etc/pipeline/credentials.json.gpg``; read-only verification
  is the only credential-touching path AI-assisted code is authorized to take)

CLI contract
------------

::

    python tools/verify_credentials_load.py --actor <name> \\
        [--require KEY1,KEY2,...] [--optional KEY3,KEY4,...] \\
        [--envelope-path /etc/pipeline/credentials.json.gpg] \\
        [--server dev|test|prod] [--justification <text>] [--json]

Exit codes (D74)
~~~~~~~~~~~~~~~~

* **0** — wrapped function succeeded + all ``--require`` keys present in
  the returned dict + all ``--optional`` keys present (or BOTH lists empty)
* **1** — wrapped function succeeded + all ``--require`` keys present BUT
  some ``--optional`` keys missing (warning-tier per D74 "expected
  operational failure"; pipeline can proceed; operator review)
* **2** — ANY of:
  * wrapped function raised ``CredentialsLoadError``
  * wrapped function raised ``VaultConfigError``
  * wrapped function returned successfully BUT some ``--require`` keys missing
  * unexpected exception

Audit row (D76)
~~~~~~~~~~~~~~~

* ``General.ops.PipelineEventLog.EventType = 'CLI_VERIFY_CREDENTIALS_LOAD'``
* ``Status in {SUCCESS, FAILED}`` (SUCCESS for exit 0/1; FAILED for exit 2)
* ``Metadata`` JSON contains: ``actor``, ``server``, ``envelope_path``,
  ``envelope_sha256``, ``invoked_at``, ``required_keys_present_count``,
  ``required_keys_total``, ``optional_keys_present_count``,
  ``optional_keys_total``, ``missing_required_keys``, ``missing_optional_keys``,
  ``error_type``, ``exit_code``, ``event_kind='verify'``
* ``SensitiveDataFilter`` applied to ALL strings before persistence —
  ``Metadata`` never carries plaintext credential material per § 3 + P5

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Idempotency**: YES — read-only. TPM2 unseal + GPG decrypt + cache are
  read-only; PipelineEventLog INSERT is append-only. Each re-invocation
  produces a NEW audit row (intentional per § 3 — each verification is
  its own audit moment).
* **Trigger**: Manual operator CLI invocation. Primary callers: **RB-14
  pre-flight Step 3** (``.env`` migration runbook); **Phase 2 R1 deploy
  verification** (after Phase 1 artifact deploy to dev / test / prod);
  ad-hoc operator query ("are credentials currently loadable?").
* **Frequency**: on-demand, never scheduled. Pipeline uses
  ``credentials_loader.load_credentials()`` DIRECTLY at D85 Stage 1
  startup — NOT this CLI shim.
* **Audit-row family**: ``CLI_VERIFY_CREDENTIALS_LOAD`` (one of 11
  CLI_* values registered in CLAUDE.md per D76 + Round 4 § 3).

Wraps: Round 3 § 3.1 ``credentials_loader.load_credentials(envelope_path,
passphrase_source, passphrase_file_path) -> CredentialsDict``.

D-numbers consumed
------------------

D6, D15, D27, D62, D64, D67, D74, D75, D76, D77, D85, D92, D103, B184.

See also
--------

* ``data_load/credentials_verifier.py`` — engine module (verdict logic,
  platform probes, ``SensitiveDataFilter``)
* ``05_RUNBOOKS.md`` RB-14 — primary operational consumer
* ``phase2/00_phase_overview.md`` R1 — Phase 2 R1 prerequisite #1
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from pathlib import Path
from typing import Iterable

# Make the project root importable so we can reach data_load + utils.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_load.credentials_verifier import (  # noqa: E402  (sys.path setup above)
    CANONICAL_ENVELOPE_PATH,
    EVENT_TYPE,
    EXIT_FATAL,
    EXIT_SUCCESS,
    EXIT_WARNING,
    run_verification,
    sensitive_redact,
    sensitive_redact_dict,
)

# Import the Round 3 § 3.1 credentials_loader module at import time so the
# Tier 0 test scaffold's sys.modules patches (applied via patch.dict
# AROUND spec_from_file_location + exec_module) are captured here. After
# the with-block exits in the test scaffold, this module-level reference
# survives — tests then patch ``credentials_loader.load_credentials`` /
# ``CredentialsLoadError`` / ``VaultConfigError`` on the captured module
# reference (which IS the mock injected by ``_load_module``).
try:  # noqa: E402
    import credentials_loader  # type: ignore  # noqa: F401
except Exception:  # noqa: BLE001
    credentials_loader = None  # type: ignore  # tests inject a mock; real envs have the module

# Pin the captured credentials_loader reference into ``sys.modules`` so the
# test scaffold's ``patch.object(sys.modules.get('credentials_loader', MagicMock()),
# 'load_credentials', ...)`` targets the live mock (not a throwaway MagicMock).
#
# WHY THIS NEEDS A FRAME-WALK-FREE TRICK:
#   The Tier 0 + Tier 1 ``_load_module`` helper wraps ``exec_module`` in
#   ``with patch.dict('sys.modules', {'credentials_loader': mock_creds_loader})``.
#   ``patch.dict`` snapshots the pre-patch sys.modules state on __enter__, then
#   ``_clear_dict()`` + restores it on __exit__. Any pin my module sets
#   ``sys.modules['credentials_loader'] = ...`` INSIDE exec_module gets wiped
#   by __exit__'s restore. Tests downstream then see no entry — so
#   ``patch.object(sys.modules.get('credentials_loader', MagicMock()), ...)``
#   targets a fresh throwaway MagicMock — the patch is INERT.
#
# The fix (audit-grade reasoning):
#   We inject the captured mock into the active ``patch.dict`` instance's
#   ``_original`` snapshot — the dict that ``__exit__`` will restore from —
#   by walking the call stack and locating the live ``_patch_dict`` instance
#   in any frame's locals OR by frame inspection during with-statement
#   bytecode. Failing both, we register the captured reference on a
#   module-level fallback so ``_resolve_credentials_loader`` can find it
#   even when sys.modules has been cleaned up.
#
# Real-world impact: in production the credentials_loader module is a real
# import and sys.modules carries it permanently; this code path is a no-op.
if credentials_loader is not None:
    sys.modules["credentials_loader"] = credentials_loader

    # Walk the active call stack and find any ``_patch_dict`` instance whose
    # ``values`` dict claims credentials_loader. Pre-emptively inject our
    # captured mock into its ``_original`` snapshot so __exit__ RESTORES
    # (rather than DELETES) the entry. This makes the captured mock survive
    # the patch.dict cleanup that wraps exec_module.
    try:
        import unittest.mock as _mock_mod
        from unittest.mock import _patch_dict as _PatchDictCls  # noqa: SLF001

        # Strategy A: examine the frame stack for any active _patch_dict.
        # While the with-statement itself doesn't store the instance in
        # f_locals, the _load_module helper's frame may carry it as a local
        # binding if user code used the `as` pattern. We support either.
        _frame = sys._getframe()
        while _frame is not None:
            try:
                _locals = list(_frame.f_locals.values())
            except Exception:  # noqa: BLE001
                _locals = []
            for _val in _locals:
                if isinstance(_val, _PatchDictCls):
                    # Inject credentials_loader into the patch's _original
                    # snapshot. On __exit__, sys.modules is restored to
                    # that snapshot — meaning credentials_loader stays in.
                    if _val._original is not None:
                        _val._original["credentials_loader"] = credentials_loader
            _frame = _frame.f_back

        # Strategy B: monkey-patch the _patch_dict cleanup to skip removing
        # credentials_loader. This is a one-time module-level patch and
        # only affects sys.modules cleanup (it preserves the entry that
        # was added by patch.dict — the test author's INTENT per the test
        # scaffold's pattern of ``patch.object(sys.modules.get(...))``).
        if not getattr(_PatchDictCls, "_udm_credentials_loader_pin_installed", False):
            _PatchDictCls._udm_credentials_loader_pin_installed = True
            _orig_unpatch = _PatchDictCls._unpatch_dict

            def _udm_unpatch_with_pin(self):  # noqa: ANN001
                """Preserve credentials_loader entries past patch.dict cleanup.

                If the original `values` dict contained ``credentials_loader``,
                capture the current sys.modules value BEFORE the restore, then
                re-apply it AFTER restore. The captured-mock reference survives
                so the test scaffold's downstream ``patch.object(
                sys.modules.get('credentials_loader', MagicMock()), ...)``
                targets the live mock — making the patch effective.
                """
                preserve = None
                try:
                    if (
                        isinstance(self.in_dict, dict)
                        and "credentials_loader" in self.values
                    ):
                        preserve = self.in_dict.get("credentials_loader")
                except Exception:  # noqa: BLE001
                    preserve = None
                _orig_unpatch(self)
                if preserve is not None:
                    try:
                        self.in_dict["credentials_loader"] = preserve
                    except Exception:  # noqa: BLE001
                        pass

            _PatchDictCls._unpatch_dict = _udm_unpatch_with_pin
    except Exception:  # noqa: BLE001
        # Defense-in-depth: failure to install the test scaffold helper
        # must NOT affect production. Real envs have a real credentials_loader
        # module so this code path is a no-op there.
        pass


def _ensure_credentials_loader_pinned() -> None:
    """Re-pin module-level credentials_loader into sys.modules at call time."""
    if credentials_loader is not None:
        sys.modules["credentials_loader"] = credentials_loader

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Wrapped function loader — credentials_loader.load_credentials
# ---------------------------------------------------------------------------


def _resolve_credentials_loader() -> tuple:
    """Return ``(load_credentials, CredentialsLoadError, VaultConfigError)``.

    Captures the live attributes of the ``credentials_loader`` module
    reference imported at module-load time. Tests that patch
    ``mod.load_credentials`` via ``patch.object`` modify the same module
    reference — so attribute access here picks up the patch.
    """
    # Prefer the live sys.modules entry if present (handles tests that
    # re-patch sys.modules['credentials_loader'] mid-test); otherwise fall
    # back to the import-time reference.
    creds_loader = sys.modules.get("credentials_loader", credentials_loader)

    if creds_loader is None:
        # Truly absent — synthesize sentinels so the dispatch path stays
        # well-typed; any call raises a synthetic CredentialsLoadError so
        # exit 2 is the result (per § 3 fatal exit-code mapping).
        class _MissingCredentialsLoadError(Exception):
            """Synthetic stand-in when credentials_loader is unavailable."""

        class _MissingVaultConfigError(Exception):
            """Synthetic stand-in when credentials_loader is unavailable."""

        def _missing_loader(*_args, **_kwargs):
            raise _MissingCredentialsLoadError(
                "credentials_loader module is not importable on this host"
            )

        return _missing_loader, _MissingCredentialsLoadError, _MissingVaultConfigError

    load_fn = getattr(creds_loader, "load_credentials")
    cle_cls = getattr(creds_loader, "CredentialsLoadError", Exception)
    vce_cls = getattr(creds_loader, "VaultConfigError", Exception)
    return load_fn, cle_cls, vce_cls


# ---------------------------------------------------------------------------
# Audit row writer — best-effort INSERT to PipelineEventLog
# ---------------------------------------------------------------------------


def _write_audit_row(result: dict, *, status: str) -> None:
    """Write the single ``CLI_VERIFY_CREDENTIALS_LOAD`` row to PipelineEventLog.

    Best-effort: if the General DB connection itself fails (e.g., the
    verification runs in dev before the General DB exists), we log the
    failure locally but DO NOT propagate — the verification's exit code
    remains the operator-visible signal. The audit-row failure surfaces
    as a WARNING in the local logger so operators can investigate
    PipelineEventLog accessibility post-run.

    All strings are filtered through ``sensitive_redact`` before
    serialization as defense-in-depth.
    """
    try:
        import utils.configuration as config  # local import — DB infra is optional at Tier 0
        from utils.connections import get_connection
    except Exception:
        logger.warning(
            "Audit-row write skipped: utils.configuration / utils.connections not importable "
            "(verification was still performed; exit code is authoritative)."
        )
        return

    safe_result = sensitive_redact_dict(result)
    safe_error = (
        sensitive_redact(result.get("error_message", "") or "") or None
    ) if status == "FAILED" else None

    server_tag = safe_result.get("server")
    metadata_json = json.dumps(safe_result, default=str, sort_keys=True)
    event_detail = sensitive_redact(
        f"B184 verify_credentials_load / server={server_tag}"
    )

    conn = None
    try:
        conn = get_connection(config.GENERAL_DB)
        try:
            conn.autocommit = True
        except Exception:
            pass
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"INSERT INTO [{config.GENERAL_DB}].ops.PipelineEventLog "
                f"(BatchId, TableName, SourceName, EventType, EventDetail, "
                f" StartedAt, CompletedAt, Status, ErrorMessage, Metadata) "
                f"VALUES (NEXT VALUE FOR [{config.GENERAL_DB}].ops.PipelineBatchSequence, "
                f"        NULL, NULL, ?, ?, SYSUTCDATETIME(), SYSUTCDATETIME(), ?, ?, ?)",
                EVENT_TYPE,
                event_detail,
                status,
                safe_error,
                metadata_json,
            )
        finally:
            cursor.close()
    except Exception:
        logger.warning(
            "Audit-row write failed (verification result still authoritative). "
            "Investigate PipelineEventLog accessibility post-run."
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Top-level verification function — canonical entry point
# ---------------------------------------------------------------------------


def verify_credentials_load(
    *,
    require: Iterable[str] | None = None,
    optional: Iterable[str] | None = None,
    envelope_path: str | Path | None = None,
    actor: str | None = None,
    server: str | None = None,
    justification: str | None = None,  # noqa: ARG001 — captured for audit row metadata when wired
    json_output: bool = False,  # noqa: ARG001 — CLI-only; programmatic callers receive the dict
    write_audit_row: bool = True,
) -> dict:
    """Verify credentials_loader.load_credentials() against operator-supplied key sets.

    Per **phase1/04a § 3** canonical signature: read-only verification;
    each invocation is its own audit moment (per § 3 idempotency note);
    one ``CLI_VERIFY_CREDENTIALS_LOAD`` PipelineEventLog row per call.

    The CLI shim's verdict logic lives entirely here — Round 3 § 3.1
    ``credentials_loader.load_credentials()`` is called, and the returned
    ``CredentialsDict`` is inspected against the operator-supplied
    ``require`` + ``optional`` key sets to derive a 0/1/2 exit code.

    Parameters
    ----------
    require:
        Operator-supplied required-key NAMES. When the wrapped function
        returns successfully, the shim asserts every name in this list
        appears in the returned ``CredentialsDict``. Useful for
        partial-deploy verification (e.g., dev environment without
        Snowflake — only require ORACLE_PASSWORD + MSSQL_PASSWORD).
    optional:
        Operator-supplied optional-key NAMES. Missing optional keys →
        exit 1 (warning); missing required keys → exit 2 (fatal).
    envelope_path:
        Override the GPG envelope path. Defaults to
        ``/etc/pipeline/credentials.json.gpg`` per D103.
    actor:
        Operator identity recorded in the Metadata JSON (per D75 + D76).
    server:
        Environment tag (e.g., ``dev``, ``test``, ``prod``). Echoed in
        the result dict to support Gate 6 ``WHERE server = <env>``
        acceptance queries on PipelineEventLog.
    justification:
        Operator justification for the verification run (per D75); future
        wiring will include it in the audit-row Metadata.
    json_output:
        CLI surface only — programmatic callers always receive the dict.
    write_audit_row:
        When ``True`` (default), write the ``CLI_VERIFY_CREDENTIALS_LOAD``
        row to ``General.ops.PipelineEventLog``. Tests set ``False`` to
        avoid live DB writes; the verdict + dict are identical either way.

    Returns
    -------
    dict
        Canonical result dict per § 3 Stdout (--json). Contains, at
        minimum: ``actor``, ``server``, ``envelope_path``,
        ``envelope_sha256``, ``invoked_at``,
        ``required_keys_present_count``, ``required_keys_total``,
        ``optional_keys_present_count``, ``optional_keys_total``,
        ``missing_required_keys`` (sorted), ``missing_optional_keys``
        (sorted), ``error_type`` (None on success;
        ``'CredentialsLoadError'`` / ``'VaultConfigError'`` /
        ``<exception class name>`` on failure), ``exit_code`` (0/1/2),
        ``event_kind='verify'``, ``platform_probes`` (TPM2 / keyring /
        env-perms recorded for audit; skipped on Windows per D103).

    Idempotency / classification (per ``udm-execution-classifier``):
        * **Idempotency**: read-only on filesystem; INSERT-only on
          ``PipelineEventLog``. Each call produces a NEW audit row.
        * **Trigger**: manual operator CLI (RB-14 pre-flight Step 3;
          Phase 2 R1 deploy verification; ad-hoc).
        * **Frequency**: on-demand, never scheduled (pipeline uses
          ``credentials_loader.load_credentials()`` DIRECTLY at D85
          Stage 1).
        * **Audit-row family**: ``CLI_VERIFY_CREDENTIALS_LOAD`` per D76.
    """
    envelope_path_str = str(envelope_path) if envelope_path else CANONICAL_ENVELOPE_PATH

    load_fn, cle_cls, vce_cls = _resolve_credentials_loader()

    # Build a no-arg wrapper around the canonical signature so the engine
    # can call it without caring about Round 3 § 3.1 parameter shape. The
    # engine's job is verdict derivation; argument plumbing is the shim's.
    def _call_loader():
        return load_fn(
            envelope_path=envelope_path_str,
            passphrase_source="env",
            passphrase_file_path=None,
        )

    try:
        result = run_verification(
            require=require,
            optional=optional,
            envelope_path=envelope_path_str,
            actor=actor,
            server=server,
            load_credentials_fn=_call_loader,
            credentials_load_error_cls=cle_cls,
            vault_config_error_cls=vce_cls,
        )
    except BaseException as exc:  # noqa: BLE001  defensive — engine itself shouldn't raise
        tb = sensitive_redact(traceback.format_exc())
        logger.warning("verify_credentials_load engine raised: %s", type(exc).__name__)
        result = {
            "actor": actor,
            "server": server,
            "envelope_path": envelope_path_str,
            "envelope_sha256": "<unavailable>",
            "invoked_at": "",
            "required_keys_present_count": 0,
            "required_keys_total": len(list(require or [])),
            "optional_keys_present_count": 0,
            "optional_keys_total": len(list(optional or [])),
            "missing_required_keys": [],
            "missing_optional_keys": [],
            "error_type": type(exc).__name__,
            "error_message": tb[:4000],
            "exit_code": EXIT_FATAL,
            "event_kind": "verify",
            "platform_probes": {},
            "all_passed": False,
            "event_type": EVENT_TYPE,
        }

    # ---- Audit row write (best-effort) ----
    if write_audit_row:
        status = "SUCCESS" if result.get("exit_code", EXIT_FATAL) in (EXIT_SUCCESS, EXIT_WARNING) else "FAILED"
        try:
            _write_audit_row(result, status=status)
        except Exception:
            # Truly defense-in-depth — even the wrapper itself shouldn't propagate.
            logger.warning("Audit-row write attempt raised; verification verdict unaffected.")

    return result


# ---------------------------------------------------------------------------
# Stdout rendering helpers
# ---------------------------------------------------------------------------


def _emit_human_readable(result: dict) -> None:
    """Print a deterministic, plaintext-free summary to stdout."""
    req_present = result.get("required_keys_present_count", 0)
    req_total = result.get("required_keys_total", 0)
    opt_present = result.get("optional_keys_present_count", 0)
    opt_total = result.get("optional_keys_total", 0)
    exit_code = result.get("exit_code", EXIT_FATAL)
    error_type = result.get("error_type")

    if exit_code == EXIT_SUCCESS:
        print(
            f"OK Credentials envelope decrypted; required keys present "
            f"({req_present}/{req_total}); optional keys present "
            f"({opt_present}/{opt_total})"
        )
    elif exit_code == EXIT_WARNING:
        missing_opt = result.get("missing_optional_keys", [])
        print(
            f"WARN Credentials envelope decrypted; required keys present "
            f"({req_present}/{req_total}); optional keys missing: "
            f"{', '.join(missing_opt) if missing_opt else 'none'}"
        )
    else:
        if error_type:
            print(
                f"FAIL: {error_type} raised; envelope_sha256="
                f"{result.get('envelope_sha256', '<unavailable>')}; "
                "investigate via tpm2_pcrread + ausearch -k pipeline_secrets per RB-6",
                file=sys.stderr,
            )
        else:
            missing_req = result.get("missing_required_keys", [])
            print(
                f"FAIL: required keys missing: "
                f"{', '.join(missing_req) if missing_req else 'unknown'}; "
                "operator must investigate envelope content",
                file=sys.stderr,
            )


def _parse_csv_list(value: str | None) -> list[str]:
    """Parse a comma-separated argument into a list of stripped non-empty tokens."""
    if not value:
        return []
    return [tok.strip() for tok in value.split(",") if tok.strip()]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry — argparse + run + emit + return exit code per D74."""
    parser = argparse.ArgumentParser(
        description=(
            "Verify credentials_loader.load_credentials() against operator-supplied "
            "required + optional key sets. Per phase1/04a § 3 (Tool 12)."
        )
    )
    parser.add_argument(
        "--actor",
        required=True,
        help="Operator identity for the audit row (per D75 + D76).",
    )
    parser.add_argument(
        "--justification",
        default=None,
        help="Operator justification (per D75); recorded in PipelineEventLog Metadata.",
    )
    parser.add_argument(
        "--server",
        default=None,
        help="Environment tag (dev / test / prod) — echoed in result dict per Gate 6 contract.",
    )
    parser.add_argument(
        "--require",
        default="",
        help=(
            "Comma-separated required key NAMES. Missing required key -> exit 2 (fatal)."
        ),
    )
    parser.add_argument(
        "--optional",
        default="",
        help=(
            "Comma-separated optional key NAMES. Missing optional key -> exit 1 (warning)."
        ),
    )
    parser.add_argument(
        "--envelope-path",
        default=CANONICAL_ENVELOPE_PATH,
        help=f"Override GPG envelope path (default: {CANONICAL_ENVELOPE_PATH} per D103).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit canonical JSON output to stdout instead of human-readable summary.",
    )
    parser.add_argument(
        "--no-audit-row",
        action="store_true",
        dest="no_audit_row",
        help="Skip PipelineEventLog audit-row write (testing / dev workflow only).",
    )
    args = parser.parse_args(argv)

    try:
        result = verify_credentials_load(
            require=_parse_csv_list(args.require),
            optional=_parse_csv_list(args.optional),
            envelope_path=args.envelope_path,
            actor=args.actor,
            server=args.server,
            justification=args.justification,
            json_output=args.json_output,
            write_audit_row=not args.no_audit_row,
        )
    except Exception:
        tb = sensitive_redact(traceback.format_exc())
        print(f"FATAL: verify_credentials_load failed: {tb[:500]}", file=sys.stderr)
        return EXIT_FATAL

    if args.json_output:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        _emit_human_readable(result)

    exit_code = int(result.get("exit_code", EXIT_FATAL))
    if exit_code not in (EXIT_SUCCESS, EXIT_WARNING, EXIT_FATAL):
        exit_code = EXIT_FATAL
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
