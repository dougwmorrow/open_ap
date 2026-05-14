"""M6 — Vault SP wrapper per Round 3 § 2.3 canonical spec.

This is the canonical pipeline entry-point for every vault stored-procedure
invocation. All vault-touching modules + tools (pii_tokenizer, pii_decryptor,
tools/enforce_retention.py, tools/process_ccpa_deletion.py, future SP-N
additions) compose through :func:`call_vault_sp`. Centralizing the wrapper
gives the pipeline ONE retry policy, ONE connection-management point, and
ONE error-translation point.

Canonical references
====================

- Round 3 ``phase1/03_core_modules.md`` § 2.3 (canonical interface — re-read
  at build time per Pitfall #9.l discipline)
- Round 1 ``phase1/01_database_schema.md`` — SP-1
  ``PiiVault_GetOrCreateToken`` (L1314-1319 OUTPUT params @Token / @WasNew),
  SP-2 ``PiiVault_Decrypt`` (L1411-1414 result-set: Token + PlaintextValue),
  SP-10 ``EnforceRetention`` (L1950 result-set: WouldBeFlipped / Flipped),
  plus B81 SP-12 ``PiiVault_ProcessCcpaDeletion`` (Round 7 — additive per D92)
- Round 2 ``phase1/02_configuration.md`` § 2.1.3 — VAULT_DB_SERVER /
  VAULT_DB_NAME / VAULT_DB_USER / VAULT_DB_PASSWORD env keys
- D6 (in-house tokenization vault — single DB connection target);
  D17 (idempotency at SP body — wrapper is thin pass-through);
  D68 (error class hierarchy — retry semantics; was D67 pre-shift);
  D69 (cursor ownership — vault DB has SEPARATE pool from General/Stage/Bronze;
  was D68 pre-shift); D71 (Snowflake auth — unrelated; M7 path);
  D103 (Claude Code security model — vault SPs handle plaintext PII,
  NEVER log argument VALUES, only NAMES + counts)
- B-7 (cx_read_sql_safe retry pattern — exponential backoff, max 3 attempts,
  base 2 s); W-8 (Session-owned applock pattern — informational; vault
  SPs themselves use UPDLOCK+HOLDLOCK serialization at row level, not
  applock; this module never grabs an applock directly)
- B-222 (open) — the legacy ``data_load._exceptions`` module also defines
  ``VaultUnavailable`` / ``VaultConfigError`` as plain Exception subclasses
  for the CLI argparse boundary. This module imports the canonical
  :mod:`utils.errors` versions (PipelineRetryableError / PipelineFatalError
  subclasses). The two hierarchies will reconcile in a follow-up migration;
  pick the right one for your boundary per the ``utils/errors.py`` docstring.

Retry policy (per B-7)
======================

Retryable pyodbc errors:

- ``pyodbc.OperationalError`` — connection drop / network hiccup
- ``pyodbc.InterfaceError`` — driver-level transient (e.g. connection reset)
- SQL Server deadlock victim (error 1205) — DB-level transient
- SQL Server lock timeout (error 1222) — DB-level transient
- ``sp_getapplock`` contention (error 1222 variant) — sub-set of lock timeout

Each retry waits ``base_delay_seconds * (2 ** attempt)`` (capped). On
exhaustion the wrapper raises :class:`VaultUnavailable` with the underlying
exception attached via ``__cause__``. The retry loop NEVER catches a
:class:`KeyboardInterrupt` or :class:`SystemExit`.

Non-retryable pyodbc errors (fatal — escalate immediately):

- ``pyodbc.IntegrityError`` UNIQUE / PK violation (codes 2627 / 2601) —
  BUBBLES UP unchanged so SP-1's catch-and-relookup pattern works
- ``pyodbc.IntegrityError`` FK violation (code 547) / CHECK violation
  (code 547) — :class:`PipelineFatalError` subclass (configuration drift)
- ``pyodbc.ProgrammingError`` "Could not find stored procedure" — caller
  passed an unknown ``sp_name`` (typo guard per Pitfall #9); FATAL with
  informative log

Concurrency (per D69)
=====================

The vault DB has a SEPARATE connection pool from General / Stage / Bronze.
Each :func:`call_vault_sp` invocation borrows a fresh cursor per call
(no shared cursor across the module boundary). Multi-worker safe — each
``--workers`` subprocess has its own pool dict (per-process module state).

Security discipline (D103)
==========================

* NEVER log SP argument VALUES. The module logs SP NAME + arg-key NAMES
  + arg COUNT at DEBUG; retries log NAME + attempt N at WARNING; terminal
  failures log NAME + final-attempt error class at ERROR.
* The ``observability.sensitive_data_filter`` redacts the
  ``password=...`` patterns that this module's own connect-string
  construction may emit at DEBUG (defense-in-depth). Do NOT rely on
  the filter as primary safety — never log VALUES from ``sp_args``.
* ``cursor_for_vault`` uses parameterized SQL ``{CALL ProcName (?, ?)}``
  ODBC-call syntax; argument values are bound via pyodbc parameter
  binding (NEVER string-formatted into SQL).

B-numbers
=========

- Closes **M6** build-tracker entry per parent orchestrator instructions.
- Consumes **B85** (utils/errors.py) — closed dependency.
- Note **B-222** — naming collision with data_load._exceptions (open;
  reconcile migration tracked).
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator

import pyodbc

from utils.errors import (
    PipelineFatalError,
    VaultConfigError,
    VaultUnavailable,
)

logger = logging.getLogger(__name__)

__all__ = [
    "VAULT_SP_REGISTRY",
    "call_vault_sp",
    "configure_vault_connection_pool",
    "release_vault_connection_pool",
    "is_pool_configured",
]


# ---------------------------------------------------------------------------
# Canonical SP registry per Round 1 § SP-1 / SP-2 / SP-10 / SP-12
# ---------------------------------------------------------------------------

# Per Pitfall #9 + § 2.3 docstring — sp_name must match a Round 1 SP. The
# registry serves two purposes:
#   (1) typo guard — unknown sp_name fails FAST locally rather than
#       round-tripping to SQL Server for a "cannot find SP" error
#   (2) signature contract — names + presence of OUTPUT params drive the
#       call-style choice (OUTPUT params need named parameter binding via
#       pyodbc.Cursor.execute and a follow-up SELECT @output_var; SPs that
#       return a result-set use cur.fetchall())
#
# "output_params" maps OUTPUT parameter names to canonical pyodbc.SQL_*
# types for binding. Empty list = SP returns ONLY a result-set.
# "result_set" True = SP body includes SELECT statements consumed via
# cur.fetchall(); rows are flattened into the returned dict via column-name
# keying for single-row result-sets and an "_rows" key for multi-row.
#
# Per § 2.3 + § 1.2 — three-part DB name resolves via VAULT_DB_NAME env key;
# the SP is invoked WITHOUT three-part qualification because the connection
# is already to the vault DB.
VAULT_SP_REGISTRY: dict[str, dict[str, Any]] = {
    "PiiVault_GetOrCreateToken": {
        "schema": "ops",
        "input_params": ("Plaintext", "PiiType", "SourceName"),
        "output_params": ("Token", "WasNew"),
        "result_set": False,
    },
    "PiiVault_Decrypt": {
        "schema": "ops",
        # SP-2 takes RequestId / Token / Justification (Round 1 § SP-2 L1414)
        "input_params": ("RequestId", "Token", "Justification"),
        "output_params": (),
        # SP-2 returns a SELECT Token, PlaintextValue result-set per L1437
        "result_set": True,
    },
    "EnforceRetention": {
        "schema": "ops",
        # Base SP signature is (@DryRun BIT = 1) per Round 1 § SP-10 L1948.
        # B93/B94 closures (Round 6) added @CutoffOverride / @CategoryFilter
        # as additive params with defaults — older callers passing just
        # DryRun remain compatible. Registry accepts the additive surface.
        "input_params": ("DryRun", "CutoffOverride", "CategoryFilter"),
        "output_params": (),
        # SP-10 SELECTs either WouldBeFlipped or Flipped per L1956 / L1972
        "result_set": True,
    },
    "PiiVault_ProcessCcpaDeletion": {
        "schema": "ops",
        # B81 closure 2026-05-11 — SP-12 per CLAUDE.md Round 7 § "SP signature
        # evolutions"; canonical entries documented at module top.
        "input_params": (
            "RequestId",
            "SubjectIdentifier",
            "TokenList",
            "LegalExceptionReason",
            "RequestedBy",
            "Actor",
            "DryRun",
        ),
        "output_params": (),
        "result_set": True,
    },
}


# ---------------------------------------------------------------------------
# Retry-classification — which pyodbc errors / SQL Server codes are retryable
# ---------------------------------------------------------------------------

# SQL Server native error codes that the retry loop catches:
#   1205 = deadlock victim ("Transaction was deadlocked on lock resources")
#   1222 = lock request timeout (incl. sp_getapplock contention)
_RETRYABLE_SQL_ERROR_CODES = frozenset({1205, 1222})

# UNIQUE / PK violation codes — these BUBBLE UP unchanged (per SP-1 § L1376
# catch-and-relookup contract). Callers downstream of SP-1 expect to catch
# pyodbc.IntegrityError themselves for the relookup branch.
_UNIQUE_VIOLATION_CODES = frozenset({2627, 2601})

# FK / CHECK violation codes — fatal, translated to PipelineFatalError.
# SQL Server reuses 547 for both FK violation and CHECK violation; either
# way the operator must reconcile the configuration before retry succeeds.
_FK_OR_CHECK_VIOLATION_CODES = frozenset({547})

# Phrases in the pyodbc error tuple that flag the "unknown SP" case so we
# can surface a FATAL with a registry hint rather than retrying.
_UNKNOWN_SP_PHRASES = (
    "Could not find stored procedure",
    "cannot find stored procedure",
)

# Cap the exponential-backoff delay so a misconfigured caller asking for
# `max_retries=999` doesn't grind forever between attempts.
_MAX_BACKOFF_DELAY_SECONDS = 60.0


# ---------------------------------------------------------------------------
# Connection-pool state (per-process, per § 2.3 + D69)
# ---------------------------------------------------------------------------

# Per D69 — vault DB has a SEPARATE connection pool from General / Stage /
# Bronze. Each pyodbc.Connection in the pool is single-thread-borrow under
# the multiprocessing worker model.
_vault_pool_state: dict[str, Any] = {
    "configured": False,
    "max_connections": 0,
    "connection_timeout_seconds": 0,
    # Single long-lived connection per process (matches utils/connections.py
    # Item-18 pattern — autocommit=True prevents transaction state leaks;
    # multi-worker isolation guaranteed by multiprocessing).
    "connection": None,
}


def is_pool_configured() -> bool:
    """Return True iff :func:`configure_vault_connection_pool` was called."""
    return bool(_vault_pool_state.get("configured", False))


def configure_vault_connection_pool(
    *,
    max_connections: int = 4,
    connection_timeout_seconds: int = 30,
) -> None:
    """Configure the vault connection pool at process start.

    Per Round 3 § 2.3 — called once by ``main_*.py`` orchestrator BEFORE
    any :func:`call_vault_sp` invocation. Subsequent calls in the same
    process raise :class:`VaultConfigError` (re-configuration not
    supported per § 2.3 spec).

    The function does NOT eagerly open a DB connection; it stores
    configuration parameters that the first :func:`call_vault_sp` will
    consume to materialize the connection on demand. This keeps module
    import side-effect-free (Tier 0 smoke discipline per D67).

    :param max_connections: Tuned per ``--workers``; default 4. Currently
        the implementation maintains a single long-lived connection per
        process (multi-worker isolation via separate subprocess pools);
        ``max_connections`` is captured for forward-compat with a future
        intra-process pool.
    :param connection_timeout_seconds: pyodbc ``timeout`` parameter on
        connect; default 30. Sub-second values are valid but rejected as
        configuration errors (operator typo guard).

    :raises VaultConfigError: pool already configured OR invalid parameters.
    """
    if _vault_pool_state.get("configured"):
        raise VaultConfigError(
            "Vault connection pool already configured; re-configuration is not "
            "supported per Round 3 § 2.3. Call release_vault_connection_pool() "
            "first if a reconfiguration is intentional.",
            metadata={
                "prior_max_connections": _vault_pool_state.get("max_connections"),
                "prior_connection_timeout_seconds": _vault_pool_state.get(
                    "connection_timeout_seconds"
                ),
            },
        )

    if not isinstance(max_connections, int) or max_connections <= 0:
        raise VaultConfigError(
            f"max_connections must be a positive integer (received "
            f"{max_connections!r}).",
            metadata={"max_connections": max_connections},
        )

    if (
        not isinstance(connection_timeout_seconds, int)
        or connection_timeout_seconds <= 0
    ):
        raise VaultConfigError(
            f"connection_timeout_seconds must be a positive integer "
            f"(received {connection_timeout_seconds!r}).",
            metadata={"connection_timeout_seconds": connection_timeout_seconds},
        )

    _vault_pool_state["max_connections"] = max_connections
    _vault_pool_state["connection_timeout_seconds"] = connection_timeout_seconds
    _vault_pool_state["connection"] = None
    _vault_pool_state["configured"] = True
    logger.info(
        "Vault connection pool configured (max_connections=%d, "
        "connection_timeout=%ds). Lazy-connect on first call.",
        max_connections,
        connection_timeout_seconds,
    )


def release_vault_connection_pool() -> None:
    """Close + clear the vault connection pool (process shutdown).

    Idempotent — safe to call when no pool is configured. Reverses
    :func:`configure_vault_connection_pool` so the next configure call
    is permitted (matches the test-fixture lifecycle expected by the
    Tier 0 / Tier 1 smoke + unit suite).
    """
    conn = _vault_pool_state.get("connection")
    if conn is not None:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 — best-effort close at shutdown
            logger.debug("Best-effort close of vault connection raised; ignoring.")
    _vault_pool_state["connection"] = None
    _vault_pool_state["configured"] = False
    _vault_pool_state["max_connections"] = 0
    _vault_pool_state["connection_timeout_seconds"] = 0


# ---------------------------------------------------------------------------
# Connection-string construction — reads VAULT_DB_* env keys per § 2.1.3
# ---------------------------------------------------------------------------


def _required_env(key: str) -> str:
    """Return ``os.environ[key]`` or raise :class:`VaultConfigError`."""
    value = os.environ.get(key)
    if not value:
        raise VaultConfigError(
            f"Required environment variable {key!r} is unset or empty. "
            f"Verify /etc/pipeline/.env loaded before vault SP invocation "
            f"(D85 Stage 1) and credentials_loader populated VAULT_DB_PASSWORD "
            f"per Round 3 § 3.1.",
            metadata={"missing_env_key": key},
        )
    return value


def _build_vault_connection_string() -> str:
    """Build the vault pyodbc connection string from VAULT_DB_* env keys.

    Per Round 2 § 2.1.3 — VAULT_DB_SERVER / VAULT_DB_NAME / VAULT_DB_USER /
    VAULT_DB_PASSWORD are MANDATORY. ODBC_DRIVER is shared with the rest
    of the pipeline (default 'ODBC Driver 18 for SQL Server').

    NEVER log this connection string at INFO+; the PWD substring is
    plaintext. The :mod:`observability.sensitive_data_filter` redacts the
    PWD pattern as defense-in-depth.
    """
    server = _required_env("VAULT_DB_SERVER")
    database = _required_env("VAULT_DB_NAME")
    user = _required_env("VAULT_DB_USER")
    password = _required_env("VAULT_DB_PASSWORD")
    driver = os.environ.get("ODBC_DRIVER", "ODBC Driver 18 for SQL Server")

    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        "TrustServerCertificate=yes;"
    )


def _get_vault_connection() -> pyodbc.Connection:
    """Return the pooled vault connection, materializing it on first call.

    Per § 2.3 + D69 — autocommit=True so the wrapper never holds a
    transaction across cursor borrows (which would break the
    SP-1 UPDLOCK+HOLDLOCK contract).
    """
    if not _vault_pool_state.get("configured"):
        raise VaultConfigError(
            "Vault connection pool not configured. Call "
            "configure_vault_connection_pool() at process start before any "
            "call_vault_sp() invocation (per Round 3 § 2.3 + D85 Stage 1).",
            metadata={"pool_state": "unconfigured"},
        )

    conn = _vault_pool_state.get("connection")
    if conn is not None:
        return conn  # type: ignore[no-any-return]

    timeout = int(_vault_pool_state.get("connection_timeout_seconds", 30))
    try:
        new_conn = pyodbc.connect(
            _build_vault_connection_string(),
            autocommit=True,
            timeout=timeout,
        )
    except VaultConfigError:
        # Env-key missing — VaultConfigError already raised inside
        # _build_vault_connection_string(); re-raise unchanged.
        raise
    except pyodbc.Error as exc:
        # Connection refused / DNS failure / TLS handshake / login failed —
        # surfaces at the FIRST call_vault_sp() rather than at configure
        # time (lazy connect per § 2.3). Translate to VaultConfigError so
        # operators see a clear FATAL at the canonical pipeline-startup
        # path rather than a raw pyodbc error.
        raise VaultConfigError(
            f"Vault DB connect failed at first call_vault_sp(): "
            f"{type(exc).__name__}",
            metadata={"pyodbc_error_class": type(exc).__name__},
        ) from exc

    _vault_pool_state["connection"] = new_conn
    return new_conn


@contextmanager
def _cursor_for_vault() -> Iterator[pyodbc.Cursor]:
    """Yield a pyodbc cursor against the vault connection.

    Per § 2.3 + D69 — cursor borrow is per-call, no sharing across
    :func:`call_vault_sp` boundary. On ``pyodbc.OperationalError``
    (connection drop / network blip) the stale connection is evicted from
    the pool and the error propagates so the retry loop can reconnect.
    """
    conn = _get_vault_connection()
    cur = conn.cursor()
    try:
        yield cur
    except pyodbc.OperationalError:
        # Evict the stale connection so the next attempt reconnects fresh.
        _vault_pool_state["connection"] = None
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        try:
            cur.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Error classification helpers
# ---------------------------------------------------------------------------


def _extract_sql_error_code(exc: BaseException) -> int | None:
    """Return the SQL Server native error code from a pyodbc error, or None.

    pyodbc errors carry a tuple of args; the SQL Server native error code
    typically appears either as a parenthesized "(2627)" / "(1205)" substring
    in the message OR as an int element inside a nested tuple. This helper
    tries both shapes and returns the first hit, or None if the pattern
    is unrecognizable.
    """
    args = getattr(exc, "args", None) or ()
    for arg in args:
        if isinstance(arg, int):
            return arg
        if isinstance(arg, tuple):
            for elt in arg:
                if isinstance(elt, int):
                    return elt
        if isinstance(arg, str):
            # Match "(NNNN)" or "SQL Server error NNNN" patterns.
            for token in (
                "1205",  # deadlock
                "1222",  # lock timeout
                "2627",  # PK violation
                "2601",  # UNIQUE violation
                "547",  # FK / CHECK violation
            ):
                if token in arg:
                    return int(token)
    return None


def _looks_like_unknown_sp(exc: BaseException) -> bool:
    """Return True iff the pyodbc error message matches the "unknown SP" pattern."""
    args = getattr(exc, "args", None) or ()
    for arg in args:
        if isinstance(arg, str):
            for phrase in _UNKNOWN_SP_PHRASES:
                if phrase.lower() in arg.lower():
                    return True
    return False


def _is_retryable(exc: BaseException) -> bool:
    """Return True iff the wrapper should retry on this exception.

    Per § 2.3 — retryable: connection drops, deadlock, lock timeout.
    Non-retryable: UNIQUE violation (bubbles up to caller), FK / CHECK
    violation (FATAL configuration error), unknown SP (FATAL typo).
    """
    if isinstance(exc, (pyodbc.OperationalError, pyodbc.InterfaceError)):
        return True

    if isinstance(exc, pyodbc.IntegrityError):
        # UNIQUE violations BUBBLE UP unchanged (caller catch-and-relookup).
        # FK / CHECK violations are FATAL — also not retryable.
        return False

    if isinstance(exc, pyodbc.ProgrammingError):
        # Unknown SP / syntax errors — never retryable (caller bug).
        return False

    code = _extract_sql_error_code(exc)
    if code is not None and code in _RETRYABLE_SQL_ERROR_CODES:
        return True

    return False


# ---------------------------------------------------------------------------
# Call-builder — turns an sp_name + sp_args dict into an ODBC {CALL ...} string
# ---------------------------------------------------------------------------


def _build_call_statement(
    sp_name: str,
    sp_args: dict[str, Any],
) -> tuple[str, list[Any], list[str]]:
    """Build an ODBC {CALL ProcName (?, ?, ?)} statement + positional args.

    Returns ``(sql, positional_args, output_param_names)``. The output param
    names are returned alongside so :func:`call_vault_sp` knows which
    ``SELECT @Token AS Token, @WasNew AS WasNew`` round-trip to execute after
    the CALL (pyodbc has no portable native OUTPUT parameter support across
    SQL Server drivers — the safer pattern is to declare local variables in
    the same batch and SELECT them as a result-set).

    The SQL emitted (for SP-1) looks like::

        DECLARE @Token VARCHAR(40);
        DECLARE @WasNew BIT;
        EXEC General.ops.PiiVault_GetOrCreateToken
            @Plaintext = ?,
            @PiiType = ?,
            @SourceName = ?,
            @Token = @Token OUTPUT,
            @WasNew = @WasNew OUTPUT;
        SELECT @Token AS Token, @WasNew AS WasNew;

    Pure-input SPs (SP-2, SP-10) emit a simpler form::

        EXEC General.ops.PiiVault_Decrypt
            @RequestId = ?, @Token = ?, @Justification = ?;

    :raises VaultConfigError: ``sp_name`` not in :data:`VAULT_SP_REGISTRY` OR
        ``sp_args`` includes an unknown parameter name.
    """
    registry_entry = VAULT_SP_REGISTRY.get(sp_name)
    if registry_entry is None:
        raise VaultConfigError(
            f"Unknown vault SP {sp_name!r}. Known SPs: "
            f"{sorted(VAULT_SP_REGISTRY.keys())}. Per Pitfall #9, sp_name "
            f"MUST match a Round 1 SP in phase1/01_database_schema.md.",
            metadata={"sp_name": sp_name, "known": sorted(VAULT_SP_REGISTRY.keys())},
        )

    schema = registry_entry["schema"]
    input_params: tuple[str, ...] = registry_entry["input_params"]
    output_params: tuple[str, ...] = registry_entry["output_params"]

    # Reject sp_args keys that are not in the registry contract — caught
    # locally so a typo surfaces without a round-trip to SQL Server.
    unknown_args = set(sp_args.keys()) - set(input_params)
    if unknown_args:
        raise VaultConfigError(
            f"Unknown sp_args for {sp_name!r}: {sorted(unknown_args)}. "
            f"Expected one of: {list(input_params)}.",
            metadata={
                "sp_name": sp_name,
                "unknown_args": sorted(unknown_args),
                "valid_input_params": list(input_params),
            },
        )

    # Build positional argument list in the registry's canonical order.
    # Missing input params bind as NULL — SPs are expected to have DEFAULTs
    # for any optional parameter (per D92 forward-only additive contract;
    # see EnforceRetention with @DryRun = 1, @CutoffOverride = NULL,
    # @CategoryFilter = NULL).
    positional: list[Any] = []
    input_assignments: list[str] = []
    for name in input_params:
        value = sp_args.get(name)
        positional.append(value)
        input_assignments.append(f"@{name} = ?")

    # OUTPUT-param SPs need DECLAREs + a follow-up SELECT.
    if output_params:
        declares: list[str] = []
        for name in output_params:
            # Use NVARCHAR(MAX) as a permissive declared type — SQL Server
            # implicitly casts SP-1's VARCHAR(40) @Token and BIT @WasNew
            # into NVARCHAR(MAX) / SQL_VARIANT-like behavior. The SELECT
            # round-trips the actual values back to pyodbc which yields
            # native Python types (str / int).
            declares.append(f"DECLARE @{name} NVARCHAR(MAX);")
        output_assignments = [f"@{n} = @{n} OUTPUT" for n in output_params]
        all_assignments = input_assignments + output_assignments
        select_clause = ", ".join(f"@{n} AS {n}" for n in output_params)
        sql = (
            "\n".join(declares)
            + f"\nEXEC {schema}.{sp_name}\n    "
            + ",\n    ".join(all_assignments)
            + f";\nSELECT {select_clause};"
        )
    else:
        sql = (
            f"EXEC {schema}.{sp_name}\n    "
            + ",\n    ".join(input_assignments)
            + ";"
        )

    return sql, positional, list(output_params)


# ---------------------------------------------------------------------------
# call_vault_sp — the public entry-point
# ---------------------------------------------------------------------------


def call_vault_sp(
    sp_name: str,
    *,
    sp_args: dict[str, Any] | None = None,
    max_retries: int = 3,
    base_delay_seconds: float = 2.0,
) -> dict[str, Any]:
    """Invoke a vault SP with cursor_for_vault, retry per B-7 on retryable
    SQL errors, and translate exceptions per D68 hierarchy.

    Per Round 3 § 2.3 — returns SP output as a dict mapping output-parameter
    name → value (for OUTPUT-param SPs like SP-1) OR result-set columns →
    values (for SPs like SP-2 / SP-10 that SELECT a single row).
    Multi-row result-sets are flattened with key ``"_rows"`` mapping to a
    list-of-dicts.

    :param sp_name: e.g. ``'PiiVault_GetOrCreateToken'``. MUST match a key
        in :data:`VAULT_SP_REGISTRY`.
    :param sp_args: Mapping of parameter NAME (without the ``@``) to value.
        ``None`` is treated as the empty dict (SP with no inputs).
    :param max_retries: Per B-7 default 3 (1 initial attempt + 2 retries).
        Caller can lower to 1 for SPs that must not retry under any
        circumstance.
    :param base_delay_seconds: Per B-7 default 2.0. Exponential backoff
        ``delay = base_delay_seconds * (2 ** (attempt - 1))`` capped at 60 s.

    :raises VaultUnavailable: Final retry attempt failed on a retryable
        error (connection drop, deadlock victim, lock timeout). The
        underlying pyodbc error is the ``__cause__``.
    :raises VaultConfigError: Pool not configured, env keys missing,
        unknown SP name, unknown sp_args key, or vault DB unreachable.
    :raises PipelineFatalError: FK / CHECK violation OR unknown SP at
        SQL Server side (sp_name passed registry guard but doesn't
        exist server-side — schema drift or environment mismatch).
    :raises pyodbc.IntegrityError: UNIQUE / PK violation — BUBBLES UP
        unchanged so SP-1's catch-and-relookup pattern works at the
        caller boundary.

    Security note: per D103 the wrapper logs SP NAME + arg-key NAMES +
    arg COUNT only; argument VALUES are NEVER logged (they may include
    plaintext PII destined for tokenization).
    """
    if not isinstance(sp_name, str) or not sp_name:
        raise VaultConfigError(
            f"sp_name must be a non-empty string (received {sp_name!r}).",
            metadata={"sp_name": sp_name},
        )
    if not isinstance(max_retries, int) or max_retries < 1:
        raise VaultConfigError(
            f"max_retries must be a positive integer (received {max_retries!r}).",
            metadata={"max_retries": max_retries},
        )
    if (
        not isinstance(base_delay_seconds, (int, float))
        or base_delay_seconds < 0
    ):
        raise VaultConfigError(
            f"base_delay_seconds must be a non-negative number "
            f"(received {base_delay_seconds!r}).",
            metadata={"base_delay_seconds": base_delay_seconds},
        )

    sp_args = sp_args or {}
    sql, positional, output_param_names = _build_call_statement(sp_name, sp_args)

    # Per D103 — log NAME + arg-key NAMES + arg COUNT only.
    arg_key_names = sorted(sp_args.keys())
    logger.debug(
        "call_vault_sp invoking SP=%s arg_keys=%s arg_count=%d max_retries=%d",
        sp_name,
        arg_key_names,
        len(sp_args),
        max_retries,
    )

    last_exc: BaseException | None = None
    for attempt in range(1, max_retries + 1):
        try:
            with _cursor_for_vault() as cur:
                cur.execute(sql, *positional)
                # Drain any preceding row counts so we land on the result-set
                # produced by either the OUTPUT-param trailing SELECT OR the
                # SP's own SELECT body.
                while cur.description is None and cur.nextset():
                    continue

                if cur.description is None:
                    # SP returned no result-set (no OUTPUT params, no SELECT).
                    # This is unusual for the vault SPs we register but valid
                    # for future void-returning SPs. Yield an empty dict.
                    logger.debug(
                        "call_vault_sp SP=%s returned no result-set "
                        "(no OUTPUT params, no SELECT)",
                        sp_name,
                    )
                    return {}

                # Capture description BEFORE the cursor closes — needed for
                # column-name keying outside the `with` block.
                description = cur.description
                # Fetch all rows for result-set SPs; single OUTPUT-param SPs
                # have exactly one row.
                rows = cur.fetchall()

            column_names = [col[0] for col in description] if description else []

            if not rows:
                # OUTPUT-param SP should always yield exactly one row from
                # the trailing SELECT; an empty result is a driver / SP
                # body anomaly worth logging at WARNING.
                logger.warning(
                    "call_vault_sp SP=%s returned empty result-set "
                    "(expected at least one row for OUTPUT params=%s)",
                    sp_name,
                    output_param_names,
                )
                return {}

            if len(rows) == 1:
                # Single row — flatten into the top-level dict for direct
                # caller use (e.g. result["Token"] for SP-1).
                result = _build_row_dict(rows[0], column_names, output_param_names)
                logger.debug(
                    "call_vault_sp SP=%s completed (single-row result), "
                    "keys=%s",
                    sp_name,
                    sorted(result.keys()),
                )
                return result

            # Multi-row result-set — yield under "_rows" key so the caller
            # can iterate. None of the current SP registry entries produce
            # multi-row results, but forward-compat for future SPs that may.
            multi_rows: list[dict[str, Any]] = [
                _build_row_dict(row, column_names, output_param_names)
                for row in rows
            ]
            return {"_rows": multi_rows}

        except pyodbc.IntegrityError as exc:
            code = _extract_sql_error_code(exc)
            if code is not None and code in _UNIQUE_VIOLATION_CODES:
                # BUBBLE UP unchanged per § 2.3 + SP-1 catch-and-relookup.
                logger.debug(
                    "call_vault_sp SP=%s: UNIQUE violation (code=%s) — "
                    "bubbling to caller for relookup",
                    sp_name,
                    code,
                )
                raise
            if code is not None and code in _FK_OR_CHECK_VIOLATION_CODES:
                logger.error(
                    "call_vault_sp SP=%s: FK / CHECK violation (code=%s) — "
                    "FATAL configuration drift",
                    sp_name,
                    code,
                )
                raise PipelineFatalError(
                    f"Vault SP {sp_name!r} raised IntegrityError "
                    f"(SQL Server code {code}) — FK / CHECK violation. "
                    f"Operator must reconcile vault configuration before retry.",
                    metadata={
                        "sp_name": sp_name,
                        "sql_error_code": code,
                        "attempt": attempt,
                    },
                ) from exc
            # Unrecognized IntegrityError variant — escalate FATAL.
            raise PipelineFatalError(
                f"Vault SP {sp_name!r} raised unrecognized IntegrityError "
                f"(code={code!r}). Operator must investigate.",
                metadata={
                    "sp_name": sp_name,
                    "sql_error_code": code,
                    "attempt": attempt,
                },
            ) from exc

        except pyodbc.ProgrammingError as exc:
            if _looks_like_unknown_sp(exc):
                logger.error(
                    "call_vault_sp SP=%s: SQL Server reports 'cannot find "
                    "stored procedure' — FATAL (sp_name passed registry guard "
                    "but doesn't exist server-side; schema drift?)",
                    sp_name,
                )
                raise PipelineFatalError(
                    f"Vault SP {sp_name!r} not found server-side. "
                    f"sp_name passed registry guard but SQL Server returned "
                    f"'cannot find stored procedure'. Likely causes: schema "
                    f"drift, env pointing at wrong DB, or migration not "
                    f"applied. Run "
                    f"`SELECT name FROM sys.procedures WHERE name = "
                    f"'{sp_name}'` on the vault DB to confirm.",
                    metadata={"sp_name": sp_name, "attempt": attempt},
                ) from exc
            logger.error(
                "call_vault_sp SP=%s: ProgrammingError — FATAL "
                "(SQL syntax / parameter mismatch)",
                sp_name,
            )
            raise PipelineFatalError(
                f"Vault SP {sp_name!r} raised ProgrammingError. Likely "
                f"caller bug: parameter type mismatch or missing required "
                f"argument.",
                metadata={"sp_name": sp_name, "attempt": attempt},
            ) from exc

        except (pyodbc.OperationalError, pyodbc.InterfaceError) as exc:
            last_exc = exc
            if attempt >= max_retries:
                logger.error(
                    "call_vault_sp SP=%s: terminal failure after %d attempts "
                    "(error_class=%s) — raising VaultUnavailable",
                    sp_name,
                    attempt,
                    type(exc).__name__,
                )
                raise VaultUnavailable(
                    f"Vault SP {sp_name!r} failed after {attempt} attempts. "
                    f"Terminal error class: {type(exc).__name__}.",
                    metadata={
                        "sp_name": sp_name,
                        "attempts": attempt,
                        "max_retries": max_retries,
                        "error_class": type(exc).__name__,
                    },
                ) from exc
            delay = min(
                base_delay_seconds * (2 ** (attempt - 1)),
                _MAX_BACKOFF_DELAY_SECONDS,
            )
            logger.warning(
                "call_vault_sp SP=%s: retryable error (error_class=%s, "
                "attempt=%d/%d). Backing off %.1fs before retry.",
                sp_name,
                type(exc).__name__,
                attempt,
                max_retries,
                delay,
            )
            time.sleep(delay)
            continue

        except pyodbc.Error as exc:
            # Catch-all for any pyodbc.Error not matching the more specific
            # subclasses above. Classify via SQL error code; retryable codes
            # (1205 deadlock, 1222 lock timeout) drive the retry loop.
            if _is_retryable(exc):
                last_exc = exc
                if attempt >= max_retries:
                    code = _extract_sql_error_code(exc)
                    logger.error(
                        "call_vault_sp SP=%s: terminal retryable error after "
                        "%d attempts (sql_code=%s) — raising VaultUnavailable",
                        sp_name,
                        attempt,
                        code,
                    )
                    raise VaultUnavailable(
                        f"Vault SP {sp_name!r} failed after {attempt} attempts. "
                        f"Terminal SQL error code: {code}.",
                        metadata={
                            "sp_name": sp_name,
                            "attempts": attempt,
                            "max_retries": max_retries,
                            "sql_error_code": code,
                        },
                    ) from exc
                code = _extract_sql_error_code(exc)
                delay = min(
                    base_delay_seconds * (2 ** (attempt - 1)),
                    _MAX_BACKOFF_DELAY_SECONDS,
                )
                logger.warning(
                    "call_vault_sp SP=%s: retryable SQL error (sql_code=%s, "
                    "attempt=%d/%d). Backing off %.1fs before retry.",
                    sp_name,
                    code,
                    attempt,
                    max_retries,
                    delay,
                )
                time.sleep(delay)
                continue
            # Non-retryable pyodbc.Error — escalate FATAL with code in metadata.
            code = _extract_sql_error_code(exc)
            logger.error(
                "call_vault_sp SP=%s: non-retryable pyodbc.Error "
                "(sql_code=%s, error_class=%s) — FATAL",
                sp_name,
                code,
                type(exc).__name__,
            )
            raise PipelineFatalError(
                f"Vault SP {sp_name!r} raised non-retryable "
                f"{type(exc).__name__} (SQL error code {code}).",
                metadata={
                    "sp_name": sp_name,
                    "sql_error_code": code,
                    "error_class": type(exc).__name__,
                    "attempt": attempt,
                },
            ) from exc

    # Unreachable: the loop body either returns or raises. Defensive guard
    # against future refactors that accidentally drop the raise / return
    # contract.
    raise VaultUnavailable(  # pragma: no cover
        f"Vault SP {sp_name!r} loop exited without return / raise — "
        f"defensive guard.",
        metadata={
            "sp_name": sp_name,
            "max_retries": max_retries,
            "last_error_class": (
                type(last_exc).__name__ if last_exc is not None else None
            ),
        },
    )


def _build_row_dict(
    row: Any,
    column_names: list[str],
    output_param_names: list[str],
) -> dict[str, Any]:
    """Convert a fetched pyodbc row to a column-name-keyed dict.

    Prefers ``column_names`` (sourced from ``cur.description`` captured BEFORE
    the cursor closed); falls back to ``output_param_names`` for the OUTPUT-
    param trailing-SELECT case; final fallback is positional ``col_0``,
    ``col_1`` etc.
    """
    if column_names and len(column_names) == len(row):
        return {name: value for name, value in zip(column_names, row)}

    if output_param_names and len(output_param_names) == len(row):
        return {name: value for name, value in zip(output_param_names, row)}

    return {f"col_{i}": value for i, value in enumerate(row)}
