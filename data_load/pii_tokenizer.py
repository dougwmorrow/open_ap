"""M4 — Per-row PII tokenization via SP-1 + provenance audit per Round 3 § 2.1.

Replaces plaintext cells in PII columns with deterministic tokens minted by
``General.ops.PiiVault_GetOrCreateToken`` (SP-1) per D6 + D15. Appends
first-observation rows to ``General.ops.PiiTokenProvenance`` (D26 append-only)
and one batch-summary row to ``General.ops.PiiTokenizationBatch`` per
(BatchId, SourceName, ObjectName, ColumnName).

Canonical references
====================

- Round 3 ``phase1/03_core_modules.md`` § 2.1 (re-read at build time per
  Pitfall #9.l) — public function name, args, error modes, side effects
- Round 1 ``phase1/01_database_schema.md`` —
    * SP-1 ``PiiVault_GetOrCreateToken`` (L1314-1397): inputs
      (``@Plaintext``, ``@PiiType``, ``@SourceName``) + OUTPUT params
      (``@Token``, ``@WasNew``); the legal-hold corner case at the
      "Status interaction" note (per CLAUDE.md SP-1 legal_hold_only Status
      paragraph + Round 1 v3 D45.6) mints fresh active tokens — caller
      treats it like any other tokenization success.
    * ``PiiTokenProvenance`` (L929-974): clustered columnstore;
      UX UNIQUE on ``(Token, SourceName, ObjectName, ColumnName, FilePath)``;
      INSERT may no-op on UNIQUE violation per D26 append-only contract.
    * ``PiiTokenizationBatch`` (L981-1016): UNIQUE on
      ``(BatchId, SourceName, ObjectName, ColumnName)``; one row per batch
      × column tokenized.
- Round 2 ``phase1/02_configuration.md`` § 1.2.2 ``PiiColumnList``: CSV column
  name list driving which columns to tokenize per D63.
- M6 sibling ``data_load/vault_client.py`` — composes
  :func:`call_vault_sp` (``"PiiVault_GetOrCreateToken"``) for every SP-1
  invocation. M6 handles retry + error translation per B-7 + D68.
- M14 sibling ``observability/sensitive_data_filter.py`` — defense-in-depth
  redactor. This module does NOT rely on the filter as primary safety —
  log lines emit NAMES + counts only, never plaintext VALUES.
- ``utils/errors.py`` canonical exception classes (per B228 lesson — DO NOT
  define local classes for ``VaultUnavailable`` / ``PiiColumnNotFound``).

Decision references
===================

- D6 — in-house tokenization vault (deterministic per source)
- D15 — idempotency (same plaintext + same source → same token)
- D26 — append-only PII audit trail (PiiTokenProvenance + PiiTokenizationBatch
  never DELETE)
- D63 — ``UdmTablesList.PiiColumnList`` drives which columns to tokenize
- D67 — Tier 0 smoke discipline (module import side-effect-free)
- D68 — canonical error hierarchy (PipelineFatalError / PipelineRetryableError)
- D92 — forward-only additive (new module; no rename / removal of existing API)
- D103 — Claude Code security model: NEVER log plaintext values; only column
  NAMES + counts. This module touches PLAINTEXT PII before tokenization.

B-number cross-references
=========================

- Closes the M4 entry on the build tracker per parent orchestrator instructions.
- Consumes B85 (utils/errors.py canonical hierarchy — closed).
- Consumes M6 (vault_client wrapper — already built; closed by sibling build).
- Consumes M14 (sensitive_data_filter — used as defense-in-depth only).

Performance considerations
==========================

SP-1 is a SINGLE-ROW stored procedure. For N rows × M PII columns, that's
N × M round-trips to SQL Server. The canonical Round 3 § 2.1 spec mandates
per-row invocation (no batch SP). Production performance characterization is
deferred to Round 5 Tier 3 integration tests (see spec ambiguity note in the
agent report — candidate B-N for a future batch SP-1 enhancement). Idempotency
of SP-1 via ``UPDLOCK + HOLDLOCK`` (Round 1 v3) makes re-tokenizing the same
plaintext safely return the same token without additional INSERTs.

Security discipline (D103 + P5)
================================

This module is the LAST mile before plaintext gets tokenized. Discipline:

* The plaintext lives in a Polars cell, gets passed to ``call_vault_sp``
  via ``sp_args={"Plaintext": cell_value, ...}``, and gets immediately
  overwritten in the DataFrame with the returned token. The plaintext is
  never logged, never written to disk, never serialized.
* Log lines emit:
    - source_name, object_name, column_list, file_path, batch_id
      (all are operator-supplied metadata, never plaintext)
    - per-column NewTokensGenerated / ExistingTokensReused / TotalRowsTokenized
      counts (aggregates only, never per-row values)
    - column NAMES inside DataFrame iteration loops, never cell values
* The ``observability.sensitive_data_filter`` is a defense-in-depth backstop
  for accidental leaks; this module does NOT rely on it for primary safety.
* The module never logs an exception's ``__cause__`` from a vault SP call
  because pyodbc errors may carry argument values in their repr.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Callable, Iterator

import polars as pl

from utils.errors import (
    PiiColumnNotFound,
    VaultUnavailable,
)

logger = logging.getLogger(__name__)

__all__ = [
    "tokenize_pii_columns",
]


# ---------------------------------------------------------------------------
# SP-1 PiiType default per Round 1 § PiiVault CHECK constraint
# ---------------------------------------------------------------------------

# SP-1 accepts a CHECK-constrained ``@PiiType`` value from the 8-value enum
# (per phase1/01_database_schema.md L885-886). Round 3 § 2.1 spec does NOT
# carry a per-column PiiType mapping — ``UdmTablesList.PiiColumnList`` is
# just a CSV of column names. We default every tokenized column to
# ``'OTHER'`` (one of the 8 valid CHECK values) so the schema constraint is
# always satisfied. A future enhancement could thread per-column PiiType
# through ``UdmTablesColumnsList`` or a sibling table; tracked as spec
# ambiguity in the agent report (candidate B-N for column→PiiType mapping).
_DEFAULT_PII_TYPE: str = "OTHER"

# Per-call constants describing the canonical PiiTokenProvenance shape — used
# by :func:`_insert_provenance_row`. The UNIQUE index on
# (Token, SourceName, ObjectName, ColumnName, FilePath) makes the INSERT
# idempotent at the SQL layer (re-tokenization of the same observation
# context no-ops with a UNIQUE violation that we swallow per D26).
_PROVENANCE_INSERT_SQL = """
INSERT INTO General.ops.PiiTokenProvenance
    (Token, SourceName, SourceObjectType, ObjectName, ColumnName, FilePath,
     FirstObservedBatchId)
VALUES (?, ?, ?, ?, ?, ?, ?);
"""

# Per-call PiiTokenizationBatch shape — written ONCE per
# (BatchId, SourceName, ObjectName, ColumnName) after the per-row loop
# completes. The UNIQUE index makes re-invocation idempotent; we swallow
# the UNIQUE violation (intentional — re-runs of the same batch are
# expected to be no-ops per D15 + D26).
_BATCH_INSERT_SQL = """
INSERT INTO General.ops.PiiTokenizationBatch
    (BatchId, SourceName, ObjectName, ColumnName,
     NewTokensGenerated, ExistingTokensReused, TotalRowsTokenized, DurationMs)
VALUES (?, ?, ?, ?, ?, ?, ?, ?);
"""

# SQL Server native error codes for UNIQUE / PK violation — swallowed for
# both PiiTokenProvenance and PiiTokenizationBatch INSERTs per D26 append-only
# semantics. Matches the constant in vault_client._UNIQUE_VIOLATION_CODES.
_UNIQUE_VIOLATION_CODES = frozenset({2627, 2601})


def _is_unique_violation(exc: BaseException) -> bool:
    """Return True iff the pyodbc error is a UNIQUE/PK violation.

    Both ObjectType columns + the UX_PiiTokenProvenance_FirstObs index can
    fire a 2627 / 2601 on duplicate INSERT. Per D26 the duplicate is the
    intended outcome (observation already recorded). Swallow + continue.
    """
    args = getattr(exc, "args", ()) or ()
    for arg in args:
        if isinstance(arg, int) and arg in _UNIQUE_VIOLATION_CODES:
            return True
        if isinstance(arg, tuple):
            for elt in arg:
                if isinstance(elt, int) and elt in _UNIQUE_VIOLATION_CODES:
                    return True
        if isinstance(arg, str):
            for code in ("2627", "2601"):
                if code in arg:
                    return True
    return False


# ---------------------------------------------------------------------------
# General-DB cursor injection point — mockable for tests
# ---------------------------------------------------------------------------


def _default_general_cursor_factory() -> Any:
    """Return the canonical ``utils.connections.cursor_for('General')``
    context manager.

    Lazy import shields module import from the heavyweight ``configuration``
    + ``pyodbc`` chain inside ``utils.connections``. Per D67 — module import
    must be side-effect-free; Tier 0 smoke must not require a live SQL
    Server. Tests inject their own context-manager factory via the
    ``general_cursor_factory`` kwarg, bypassing this default entirely.
    """
    # Local import only — keeps Tier 0 smoke side-effect-free.
    from utils.connections import cursor_for

    return cursor_for("General")


# ---------------------------------------------------------------------------
# Provenance + batch writers — composed under one cursor per call
# ---------------------------------------------------------------------------


def _insert_provenance_row(
    cur: Any,
    *,
    token: str,
    source_name: str,
    object_name: str,
    column_name: str,
    file_path: str,
    batch_id: int,
) -> bool:
    """INSERT one PiiTokenProvenance row; swallow UNIQUE violation per D26.

    The SourceObjectType column has a CHECK constraint
    (``'TABLE'``, ``'VIEW'``, ``'FILE'``); per § 2.1 we infer:
    ``file_path != ''`` → ``'FILE'``, else ``'TABLE'``. Views aren't
    distinguished here — operator can hand-classify in audit-time queries
    (low value to attempt heuristic detection from a column-name CSV).

    Returns True iff a new row was inserted (i.e. first observation);
    False iff the row already existed (UNIQUE violation swallowed). Caller
    uses this for the NewTokensGenerated metric — but note: the metric
    measures NEW vault rows (``@WasNew = 1``), not new provenance rows
    (provenance can be FIRST observation for an EXISTING token).
    """
    source_object_type = "FILE" if file_path else "TABLE"
    try:
        cur.execute(
            _PROVENANCE_INSERT_SQL,
            token,
            source_name,
            source_object_type,
            object_name,
            column_name,
            file_path,
            batch_id,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — narrow check below
        if _is_unique_violation(exc):
            # Intentional no-op per D26; observation already recorded.
            logger.debug(
                "PiiTokenProvenance UNIQUE on (Token=<redacted>, "
                "SourceName=%s, ObjectName=%s, ColumnName=%s, FilePath=%r) "
                "— first-observation already recorded, swallowing per D26.",
                source_name,
                object_name,
                column_name,
                file_path,
            )
            return False
        # Non-UNIQUE error — bubble up FAST so the operator sees the
        # actual cause. The caller's `with cursor_factory:` block will
        # propagate; the per-cell loop catches VaultUnavailable separately.
        raise


def _insert_batch_summary(
    cur: Any,
    *,
    batch_id: int,
    source_name: str,
    object_name: str,
    column_name: str,
    new_tokens_generated: int,
    existing_tokens_reused: int,
    total_rows_tokenized: int,
    duration_ms: int,
) -> None:
    """INSERT one PiiTokenizationBatch summary row; swallow UNIQUE per D15.

    UNIQUE on (BatchId, SourceName, ObjectName, ColumnName) per the
    UX_PiiTokenizationBatch_Identity v2 fix (per Round 1 § 18). Re-runs of
    the same batch produce a UNIQUE violation; we swallow it because the
    same batch tokenizing the same column twice MUST be a no-op per D15.
    """
    try:
        cur.execute(
            _BATCH_INSERT_SQL,
            batch_id,
            source_name,
            object_name,
            column_name,
            new_tokens_generated,
            existing_tokens_reused,
            total_rows_tokenized,
            duration_ms,
        )
    except Exception as exc:  # noqa: BLE001 — narrow check below
        if _is_unique_violation(exc):
            logger.debug(
                "PiiTokenizationBatch UNIQUE on (BatchId=%d, SourceName=%s, "
                "ObjectName=%s, ColumnName=%s) — re-run idempotent no-op "
                "per D15, swallowing.",
                batch_id,
                source_name,
                object_name,
                column_name,
            )
            return
        raise


# ---------------------------------------------------------------------------
# Per-cell tokenization — composes M6 call_vault_sp
# ---------------------------------------------------------------------------


def _tokenize_cell(
    plaintext: str,
    *,
    pii_type: str,
    source_name: str,
    call_vault_sp_fn: Callable[..., dict[str, Any]],
) -> tuple[str, bool]:
    """Tokenize a single plaintext cell via M6 ``call_vault_sp``.

    Returns ``(token, was_new)`` per SP-1 OUTPUT params.

    Per CLAUDE.md SP-1 legal_hold_only Status corner case + Round 1 v3
    D45.6: when the only existing vault row for this plaintext has
    ``Status = 'legal_hold_only'``, SP-1 mints a FRESH active token
    (separate from the legal-hold row preserved for litigation). The
    caller does NOT need to handle this specially — SP-1's contract is
    "always return a token tied to an active row"; the legal-hold-only
    row is preserved separately.

    :raises VaultUnavailable: bubbled from M6 (SP-1 connection failure or
        transient lock timeout). Caller's per-cell loop lets this
        propagate so the table-level tokenization aborts cleanly.
    """
    result = call_vault_sp_fn(
        "PiiVault_GetOrCreateToken",
        sp_args={
            "Plaintext": plaintext,
            "PiiType": pii_type,
            "SourceName": source_name,
        },
    )
    # SP-1 result-set fields per Round 1 § SP-1 L1397 trailing SELECT —
    # column-name-keyed dict per M6 _build_row_dict.
    token = result.get("Token")
    was_new_raw = result.get("WasNew", 0)
    # pyodbc returns BIT columns as int or bool; normalize to bool.
    was_new = bool(was_new_raw)
    if not isinstance(token, str) or not token:
        # SP-1 must always return a token; an empty / non-string is a
        # contract violation worth surfacing FAST (operator must investigate).
        # Treat as retryable since SP body could have hit a transient internal
        # error; M6 already retries on retryable cases so by the time we get
        # here we've exhausted retries — raise VaultUnavailable.
        raise VaultUnavailable(
            "SP-1 returned empty / non-string Token; SP-1 contract violation "
            "(expected VARCHAR(40)).",
            metadata={
                "sp_name": "PiiVault_GetOrCreateToken",
                "source_name": source_name,
                "pii_type": pii_type,
                "returned_token_type": type(token).__name__,
            },
        )
    return token, was_new


# ---------------------------------------------------------------------------
# Time helper — clock injected for tests
# ---------------------------------------------------------------------------


def _default_now_ms() -> int:
    """Return current epoch milliseconds (monotonic-ish).

    Wrapped so tests can pin a clock without touching ``time.monotonic``
    or ``time.time`` globally (which would race with the pytest engine's
    own timestamping). The production default uses ``time.monotonic()``
    so the duration math survives system clock skew.
    """
    import time as _time

    return int(_time.monotonic() * 1000)


# ---------------------------------------------------------------------------
# Public entry-point — Round 3 § 2.1 canonical signature
# ---------------------------------------------------------------------------


def tokenize_pii_columns(
    df: pl.DataFrame,
    *,
    source_name: str,
    object_name: str,
    column_list: list[str] | None = None,
    file_path: str = "",
    batch_id: int,
    pii_type: str = _DEFAULT_PII_TYPE,
    call_vault_sp_fn: Callable[..., dict[str, Any]] | None = None,
    general_cursor_factory: Callable[[], Any] | None = None,
    now_ms_fn: Callable[[], int] | None = None,
) -> pl.DataFrame:
    """Replace plaintext values in ``column_list`` columns with vault tokens.

    Per Round 3 § 2.1 — invokes SP-1 once per cell via the M6
    :func:`call_vault_sp` wrapper, appends a first-observation row to
    ``PiiTokenProvenance`` per (Token, SourceName, ObjectName, ColumnName,
    FilePath), and writes one ``PiiTokenizationBatch`` summary row per
    (BatchId, SourceName, ObjectName, ColumnName). Returns a Polars
    DataFrame with the same schema (column types unchanged) and the same
    row count; PII column values are replaced by token strings.

    :param df: DataFrame with plaintext PII cells. Non-PII columns are
        pass-through unchanged. Must contain every name in ``column_list``.
    :param source_name: e.g. ``'DNA'``. Drives per-source vault isolation
        per D6 + P9. Surfaces in ``PiiTokenProvenance.SourceName`` and
        ``PiiTokenizationBatch.SourceName``.
    :param object_name: source table or file name. Surfaces in
        ``PiiTokenProvenance.ObjectName`` for V7 audit.
    :param column_list: list of PII column names. ``None`` is treated as
        ``[]`` (no tokenization — returns ``df`` unchanged with no SP-1
        calls). Empty list short-circuits before any DB I/O. Per § 2.1
        canonical spec: caller is expected to thread the CSV-parsed list
        from ``UdmTablesList.PiiColumnList``.
    :param file_path: empty string for DB-sourced data; full Hive snapshot
        path for file-sourced data. Captured in
        ``PiiTokenProvenance.FilePath``. Drives ``SourceObjectType``
        inference (``'FILE'`` if non-empty, ``'TABLE'`` otherwise).
    :param batch_id: from ``General.ops.PipelineBatchSequence``. Surfaces
        in both ``PiiTokenProvenance.FirstObservedBatchId`` and
        ``PiiTokenizationBatch.BatchId``.
    :param pii_type: SP-1 ``@PiiType`` enum value. Defaults to ``'OTHER'``
        per the constraint (one of SSN/EIN/EMAIL/NAME/ACCOUNT/PHONE/
        ADDRESS/OTHER per Round 1 § PiiVault CHECK constraint L885-886).
        Round 3 § 2.1 does not specify per-column type derivation; the
        default ``'OTHER'`` satisfies the CHECK constraint deterministically.
        Caller can override for tables with a known single-type PII column
        set (e.g. ``pii_type='SSN'`` for a tokenize call against an SSN-only
        column list). Future enhancement: per-column type mapping via
        ``UdmTablesColumnsList`` (tracked as spec ambiguity in agent report).
    :param call_vault_sp_fn: injection point for the M6 ``call_vault_sp``
        wrapper. ``None`` → import-and-bind the canonical
        :func:`data_load.vault_client.call_vault_sp`. Tests inject a mock.
    :param general_cursor_factory: zero-arg callable returning a context
        manager that yields a pyodbc cursor against ``General``. ``None``
        → :func:`_default_general_cursor_factory` (which lazy-imports
        ``utils.connections.cursor_for``). Tests inject a mock.
    :param now_ms_fn: zero-arg callable returning epoch milliseconds.
        ``None`` → :func:`_default_now_ms` (``time.monotonic``-based).
        Tests inject a pinned clock for deterministic ``DurationMs``.

    :returns: A new DataFrame with PII columns replaced. Schema unchanged;
        row count unchanged; non-PII columns unchanged.

    :raises PiiColumnNotFound: a name in ``column_list`` is absent from
        ``df.columns``. FATAL per D68; operator must reconcile
        ``UdmTablesList.PiiColumnList`` against the source schema.
    :raises VaultUnavailable: SP-1 connection drop, transient lock timeout,
        or retry exhaustion per M6. RETRYABLE per B-7; caller may
        re-invoke after backoff.

    Side effects (per row × per PII column):
        - SP-1 INSERT-or-lookup against ``General.ops.PiiVault``
          (deterministic per D6 + D15)
        - INSERT-or-no-op against ``General.ops.PiiTokenProvenance``
          (UNIQUE violation swallowed per D26 append-only)

    Side effects (per column tokenized):
        - INSERT-or-no-op against ``General.ops.PiiTokenizationBatch``
          (UNIQUE on (BatchId, SourceName, ObjectName, ColumnName) per
          UX_PiiTokenizationBatch_Identity v2 fix)

    Empty-string vs NULL handling:
        - NULL: passed through unchanged (no SP-1 call). The token-position
          in the output DataFrame is NULL.
        - ``''``: tokenized normally. For Oracle sources, E-1 normalization
          upstream of this module converts ``''`` → NULL before reaching
          here; SQL Server sources may legitimately pass empty strings
          through.

    Idempotency (per D15):
        - SP-1's UPDLOCK+HOLDLOCK guarantees same plaintext → same token
        - Provenance INSERT UNIQUE-swallowed on re-observation
        - Batch summary INSERT UNIQUE-swallowed on re-run
        Re-tokenizing the same DataFrame produces an identical output
        DataFrame.

    Security (D103):
        - NEVER logs plaintext cell values
        - Logs column names, source_name, object_name, batch_id, counts
        - The :mod:`observability.sensitive_data_filter` is a backstop
          (defense-in-depth); this module does NOT rely on it for primary
          safety.
    """
    # Per § 2.1 spec — None / empty short-circuit before any I/O.
    if column_list is None or not column_list:
        logger.debug(
            "tokenize_pii_columns invoked with empty column_list "
            "(source_name=%s, object_name=%s, batch_id=%d) — no-op "
            "(no SP-1 calls, no provenance writes).",
            source_name,
            object_name,
            batch_id,
        )
        return df

    # Validate every column exists BEFORE any SP-1 call — fail-fast on
    # configuration drift per § 2.1 PiiColumnNotFound semantics.
    df_columns = set(df.columns)
    missing = [name for name in column_list if name not in df_columns]
    if missing:
        raise PiiColumnNotFound(
            f"PII column(s) {sorted(missing)} not present in DataFrame "
            f"schema (source_name={source_name!r}, "
            f"object_name={object_name!r}, df_columns={sorted(df_columns)}). "
            f"Reconcile UdmTablesList.PiiColumnList against the source schema.",
            metadata={
                "source_name": source_name,
                "object_name": object_name,
                "batch_id": batch_id,
                "missing_columns": sorted(missing),
                "df_columns": sorted(df_columns),
            },
        )

    # Bind injection points — lazy so module import doesn't pull in pyodbc /
    # configuration / vault_client (Tier 0 smoke discipline per D67).
    if call_vault_sp_fn is None:
        from data_load.vault_client import call_vault_sp as _csp

        call_vault_sp_fn = _csp
    if general_cursor_factory is None:
        general_cursor_factory = _default_general_cursor_factory
    if now_ms_fn is None:
        now_ms_fn = _default_now_ms

    logger.info(
        "tokenize_pii_columns starting: source_name=%s object_name=%s "
        "column_count=%d row_count=%d batch_id=%d file_path=%r",
        source_name,
        object_name,
        len(column_list),
        df.height,
        batch_id,
        file_path,
    )

    # Build per-column working state. We process columns one at a time —
    # each column is a complete tokenization cycle with its own batch row.
    # Column order matches column_list (operator-supplied; deterministic).
    output_df = df

    # Single cursor for all provenance + batch writes — per § 2.1
    # "cursor_for('General') per call; vault connection only" but in
    # practice the provenance + batch tables ALSO live in General so we
    # reuse one cursor. The vault connection itself is owned by M6.
    cursor_cm = general_cursor_factory()
    with cursor_cm as cur:
        for column_name in column_list:
            started_ms = now_ms_fn()
            # Counters per § 2.1 — surface in batch summary row.
            new_tokens_generated = 0
            existing_tokens_reused = 0
            total_rows_tokenized = 0

            # Pull the column out of the DataFrame; we'll write a fresh
            # column back in once per-cell tokenization completes.
            original_col = output_df[column_name]
            new_values: list[str | None] = []

            for cell in original_col.to_list():
                if cell is None:
                    # NULL pass-through per § 2.1 — no SP-1 call, no
                    # provenance row.
                    new_values.append(None)
                    continue

                # Coerce non-string cells to string before SP-1. Polars may
                # carry numeric / temporal types in a column we're being
                # asked to tokenize; SP-1 ``@Plaintext NVARCHAR(MAX)``
                # accepts strings. This is a defensive cast — the caller
                # is expected to pass string-typed PII columns per § 2.1
                # ("Schema unchanged (columns are still string type)").
                plaintext = cell if isinstance(cell, str) else str(cell)

                token, was_new = _tokenize_cell(
                    plaintext,
                    pii_type=pii_type,
                    source_name=source_name,
                    call_vault_sp_fn=call_vault_sp_fn,
                )

                # Provenance row — UNIQUE swallowed on re-observation.
                _insert_provenance_row(
                    cur,
                    token=token,
                    source_name=source_name,
                    object_name=object_name,
                    column_name=column_name,
                    file_path=file_path,
                    batch_id=batch_id,
                )

                new_values.append(token)
                total_rows_tokenized += 1
                if was_new:
                    new_tokens_generated += 1
                else:
                    existing_tokens_reused += 1

            # Replace the column in the DataFrame with the token column.
            # Per Polars: ``df.with_columns(...)`` is non-mutating; returns
            # a new DataFrame. We accumulate column-by-column.
            output_df = output_df.with_columns(
                pl.Series(name=column_name, values=new_values, dtype=pl.Utf8)
            )

            duration_ms = max(0, now_ms_fn() - started_ms)
            _insert_batch_summary(
                cur,
                batch_id=batch_id,
                source_name=source_name,
                object_name=object_name,
                column_name=column_name,
                new_tokens_generated=new_tokens_generated,
                existing_tokens_reused=existing_tokens_reused,
                total_rows_tokenized=total_rows_tokenized,
                duration_ms=duration_ms,
            )

            logger.info(
                "tokenize_pii_columns column=%s tokenized: "
                "new_tokens=%d reused_tokens=%d total_rows=%d "
                "duration_ms=%d (source_name=%s object_name=%s batch_id=%d)",
                column_name,
                new_tokens_generated,
                existing_tokens_reused,
                total_rows_tokenized,
                duration_ms,
                source_name,
                object_name,
                batch_id,
            )

    logger.info(
        "tokenize_pii_columns completed: source_name=%s object_name=%s "
        "columns_tokenized=%d total_rows=%d batch_id=%d",
        source_name,
        object_name,
        len(column_list),
        df.height,
        batch_id,
    )

    return output_df
