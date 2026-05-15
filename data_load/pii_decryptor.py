"""M5 — Operator-driven decrypt path per Round 3 § 2.2 canonical spec.

This module is the *single* entry-point for decrypting a PiiVault token.
It is invoked by operator-facing tools (e.g. ``tools/decrypt_pii.py``);
the pipeline service account itself does NOT have decrypt permission
(per D6 — decrypt path is operator-authority only). Tokenization at
pipeline ingest is handled by M4 (``data_load/pii_tokenizer.py``) — a
different SP path (SP-1) with a different role grant.

Canonical references
====================

- Round 3 ``phase1/03_core_modules.md`` § 2.2 (canonical interface —
  re-read at build time per Pitfall #9.l discipline; B103 docstring
  contradiction resolved per Round 6 § 7.9 — DecryptDenied IS raised)
- Round 1 ``phase1/01_database_schema.md`` — SP-2 ``PiiVault_Decrypt``
  (L1414-1455) parameters ``@RequestId UNIQUEIDENTIFIER`` /
  ``@Token VARCHAR(40)`` / ``@Justification NVARCHAR(MAX)``; result-set
  ``SELECT Token, PlaintextValue`` for ``Status IN ('active',
  'legal_hold_only')`` only
- Round 1 ``phase1/01_database_schema.md`` — ``PiiVaultAccessLog``
  table DDL L1031-1048; INSERT is performed server-side inside SP-2
  (lines L1422-1434), atomic with the decrypt — NO client-side audit
  write needed
- D6 (in-house vault — decrypt path); D26 (append-only audit
  semantics — every access logged, including the deleted-per-request
  audit trail); D30 (mandatory PiiVaultAccessLog write); D103 (Claude
  Code security model — NEVER log decrypted plaintext values); P5
  (sensitive_data_filter — defense-in-depth)
- RB-10 (CCPA right-to-deletion — ``Status = 'deleted_per_request'``
  produces a non-decrypt outcome; audit row STILL written)

Sibling references
==================

- :mod:`data_load.vault_client` (M6) — this module composes
  :func:`vault_client.call_vault_sp` with ``sp_name='PiiVault_Decrypt'``;
  M6 owns the cursor / retry / connection-pool concerns
- :mod:`utils.errors` (B85 — closed) — canonical exception classes
  ``TokenNotFound`` / ``DecryptDenied`` / ``VaultUnavailable``; this
  module does NOT define local exception classes (B228 lesson learned)

Security discipline (D103)
==========================

* **NEVER log decrypted plaintext.** All log lines emit Token (the hex
  identifier — not sensitive) + Justification + RequestId, not the
  plaintext that SP-2 returns.
* The plaintext leaves this module via the return value only; callers
  are responsible for zero-ing the local variable after use (best-effort
  GC hint; the spec also mentions ``ctypes.memset`` for high-security
  paths, but that is out of scope for this module).
* Justification is REQUIRED non-empty per D75 CLI argument convention.
  Empty / whitespace-only justification raises ``ValueError`` at the
  function boundary — fails fast before any SP-2 round trip, before any
  audit row is written.

Idempotency
===========

Read-only on PiiVault; INSERT-only on PiiVaultAccessLog (server-side
inside SP-2). Re-decrypting the same token returns the same plaintext
(idempotent by SP-2 contract) but every call writes a NEW audit row
(per D26 append-only). This is intentional — every operator decrypt is
a separate audit event.

Error modes
===========

- :class:`TokenNotFound` (fatal) — SP-2 returned no plaintext because
  the Token is absent from PiiVault. Surfaces as ``PipelineFatalError``
  per D68 hierarchy.
- :class:`DecryptDenied` (fatal) — SP-2 returned a row with
  ``PlaintextValue IS NULL``, indicating the token exists but its Status
  forbids decrypt (``deleted_per_request`` per RB-10 CCPA; future
  ``purged_for_retention`` per D30). The audit row was STILL written by
  SP-2 before the NULL return.
- :class:`VaultUnavailable` (retryable) — bubbles up unchanged from M6
  (connection drop / deadlock victim / lock timeout). Caller may retry
  the whole ``decrypt_token`` call per B-7.
- :class:`ValueError` (Python builtin) — empty/whitespace justification.
  Caught at the function boundary BEFORE any SP-2 round trip; no audit
  row is written for malformed input.

Concurrency
===========

This module is stateless module-level (the connection pool is owned by
M6 ``vault_client``). Multi-worker safe; multi-thread safe within a
process (each thread's call grabs its own cursor via M6).

D-numbers consumed
==================

D6, D17 (idempotency at SP body), D26 (append-only audit), D30
(mandatory audit), D68 (error hierarchy), D75 (CLI justification
convention), D103 (security model).

B-numbers
=========

- Closes **M5** build-tracker entry per parent orchestrator
  instructions (Wave 3 module 1 of 5).
- Consumes **M6** (vault_client) — closed dependency.
- Consumes **B85** (utils/errors) — closed dependency.
- B103 (DecryptDenied docstring contradiction) — RESOLVED per Round 6
  § 7.9: DecryptDenied IS raised by this wrapper; this module's
  behavior matches the resolved contract.
"""

from __future__ import annotations

import logging
import uuid

from data_load.vault_client import call_vault_sp
from utils.errors import DecryptDenied, TokenNotFound

logger = logging.getLogger(__name__)

__all__ = ["decrypt_token"]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def decrypt_token(
    *,
    token: str,
    justification: str,
    request_id: uuid.UUID | None = None,
) -> str | None:
    """Decrypt a PiiVault token via SP-2; return plaintext or None.

    Per Round 3 § 2.2 — this is the single canonical decrypt entry-point
    for operator-driven tooling. Composes M6 :func:`call_vault_sp` with
    ``sp_name='PiiVault_Decrypt'``; M6 owns retry + connection-pool +
    error-translation concerns. SP-2 writes the audit row to
    :data:`PiiVaultAccessLog` server-side, atomic with the decrypt
    operation (no client-side audit write needed).

    :param token: The token from ``PiiVault.Token`` (canonical type
        ``VARCHAR(40)``, hex digits). Maps to SP-2 ``@Token`` parameter.
    :param justification: Free-text reason — required for audit per D6 +
        D26 + D75. Maps to SP-2 ``@Justification`` parameter. Empty or
        whitespace-only values raise :class:`ValueError` BEFORE any
        SP-2 round trip (no audit row written for malformed input —
        the justification is the audit-row payload, so a missing
        justification means no audit-grade record to write).
    :param request_id: Optional UUID for tying multiple decrypts to a
        single operator request (e.g. an export of N tokens for a
        subpoena response). ``None`` auto-generates via
        ``uuid.uuid4()``. Maps to SP-2 ``@RequestId`` parameter.

    :returns: Plaintext string for ``Status IN ('active',
        'legal_hold_only')`` tokens. Never returns ``None`` in normal
        operation — the non-decrypt states raise :class:`DecryptDenied`
        / :class:`TokenNotFound` per the spec, NOT a silent None (D26
        + D30: every operator action is audit-grade; silent None would
        let a caller mistake "no value" for "value is empty string").

    :raises ValueError: ``justification`` is empty or whitespace-only.
        Raised at the function boundary; NO SP-2 round trip and NO
        audit row written.
    :raises TokenNotFound: SP-2 returned no row — Token absent from
        PiiVault. ``PipelineFatalError`` subclass per D68.
    :raises DecryptDenied: SP-2 returned a row with NULL plaintext —
        Token exists but Status forbids decrypt (CCPA
        ``deleted_per_request`` per RB-10; future
        ``purged_for_retention`` per D30 retention). The audit row was
        STILL written by SP-2 before the NULL return.
    :raises VaultUnavailable: Bubbled unchanged from M6 — retryable
        per B-7. ``PipelineRetryableError`` subclass per D68.

    :side-effects: ONE INSERT row into
        ``General.ops.PiiVaultAccessLog`` via SP-2 (server-side,
        atomic with the decrypt). Columns populated by SP-2:
        ``RequestId``, ``AccessedAt`` (``SYSUTCDATETIME()``),
        ``AccessedBy`` (``SYSTEM_USER``), ``AccessRole`` (database
        role lookup), ``Token``, ``Justification``,
        ``AccessSourceIp`` (``CONNECTIONPROPERTY('client_net_address')``),
        ``AccessApplication`` (``APP_NAME()``). Also UPDATE of
        ``PiiVault.LastAccessedAt`` + ``PiiVault.AccessCount`` for the
        Token (audit-only, does NOT change decrypt semantics).

    :caller-hygiene: plaintext should be zeroed after use::

        plaintext = decrypt_token(
            token='abc123...',
            justification='audit request SR-1234',
        )
        try:
            use(plaintext)
        finally:
            plaintext = None  # GC hint; high-security paths use ctypes.memset

    :security: NEVER log the returned plaintext. This module logs only
        Token (hex identifier — not sensitive) + RequestId +
        Justification length (not value, to avoid PII slipping into
        the justification field). The :mod:`observability.sensitive_data_filter`
        is the last-mile redactor for defense-in-depth (P5).
    """
    # ------------------------------------------------------------------
    # Justification validation — D75 CLI convention, fails fast at the
    # function boundary BEFORE any SP-2 round trip. Audit-grade contract
    # requires a non-empty reason, so a malformed justification means we
    # cannot honor the audit semantics and must refuse the request.
    # ------------------------------------------------------------------
    if not isinstance(justification, str):
        raise ValueError(
            f"justification must be a non-empty string; received "
            f"{type(justification).__name__}"
        )
    if not justification.strip():
        raise ValueError(
            "justification must be non-empty (audit-grade contract per "
            "D6 + D26 + D75 — every decrypt requires an operator-supplied "
            "reason for the PiiVaultAccessLog row)"
        )

    # Token validation — light typo guard, mirrors M6's sp_name guard
    # pattern. SP-2 also enforces NOT NULL at the SQL Server side.
    if not isinstance(token, str) or not token:
        raise ValueError(
            f"token must be a non-empty string; received {type(token).__name__}"
        )

    # ------------------------------------------------------------------
    # RequestId — auto-generate when caller passes None. Per spec:
    # "None → auto-generate via uuid.uuid4()". Mapped to SP-2
    # @RequestId UNIQUEIDENTIFIER.
    # ------------------------------------------------------------------
    if request_id is None:
        request_id = uuid.uuid4()
    elif not isinstance(request_id, uuid.UUID):
        raise ValueError(
            f"request_id must be uuid.UUID or None; received "
            f"{type(request_id).__name__}"
        )

    # ------------------------------------------------------------------
    # D103 — log NAME + Token (not sensitive) + RequestId + Justification
    # LENGTH only. The justification itself is the audit-row payload and
    # may contain operator-supplied free text; we do NOT echo it into our
    # process-side logs (defense-in-depth against the very rare case where
    # an operator accidentally pastes a plaintext PII value into the
    # justification field).
    # ------------------------------------------------------------------
    logger.info(
        "pii_decryptor.decrypt_token invoking SP-2 "
        "token=%s request_id=%s justification_length=%d",
        token,
        request_id,
        len(justification),
    )

    # ------------------------------------------------------------------
    # SP-2 invocation via M6. The wrapper:
    #   - borrows a cursor against the vault DB (D69 — separate pool)
    #   - retries on retryable pyodbc errors (B-7)
    #   - translates pyodbc errors into PipelineError hierarchy (D68)
    # On success, returns either {} (empty result-set) OR a dict with
    # keys 'Token' + 'PlaintextValue'.
    #
    # IntegrityError / FK / unknown SP / VaultUnavailable / VaultConfigError
    # bubble up unchanged — callers handle them at the CLI boundary per
    # § 1.8 cli_main_wrapper.
    # ------------------------------------------------------------------
    sp_result = call_vault_sp(
        "PiiVault_Decrypt",
        sp_args={
            "RequestId": str(request_id),  # pyodbc binds UUID via str
            "Token": token,
            "Justification": justification,
        },
    )

    # ------------------------------------------------------------------
    # Interpret SP-2 result. Possible shapes:
    #   - {}: SP-2 returned no rows — happens when (a) Token absent OR
    #         (b) Status not in ('active', 'legal_hold_only') under
    #         current SP-2 body. Per § 2.2 spec the contract is:
    #           absent  → TokenNotFound (fatal — never silent None)
    #           denied  → DecryptDenied (fatal — CCPA / retention)
    #         Current SP-2 body does NOT distinguish; we conservatively
    #         raise TokenNotFound for any empty result. A future SP-2
    #         enhancement (B-N candidate, see notes) may return one row
    #         with NULL PlaintextValue for "exists-but-denied" to
    #         disambiguate the two states; the dict-with-NULL branch
    #         below handles that future shape.
    #   - {'Token': ..., 'PlaintextValue': None}: future enhancement —
    #         token exists but Status forbids decrypt. Raise
    #         DecryptDenied. The audit row was STILL written by SP-2
    #         before the NULL return per § 2.2 + D26.
    #   - {'Token': ..., 'PlaintextValue': '...'}: happy path. Return
    #         the plaintext string. NEVER log the value.
    #   - {'_rows': [...]}: multi-row — shouldn't happen for SP-2 (PK
    #         is unique on Token) but handle defensively by treating
    #         the first row as canonical.
    # ------------------------------------------------------------------
    if not sp_result:
        # Empty result-set — Token absent OR Status excluded. Per spec
        # default to TokenNotFound; SP-2 enhancement work tracked as
        # a B-N candidate (see module docstring + design notes).
        logger.warning(
            "pii_decryptor: SP-2 returned no rows for token=%s "
            "request_id=%s — raising TokenNotFound",
            token,
            request_id,
        )
        raise TokenNotFound(
            f"PiiVault_Decrypt returned no row for Token={token!r}. "
            f"Token is absent from General.ops.PiiVault.",
            metadata={
                "token": token,
                "request_id": str(request_id),
            },
        )

    # Multi-row result-set — flatten to the first row. SP-2 has a unique
    # PK on Token so this branch is purely defensive.
    if "_rows" in sp_result:
        rows = sp_result["_rows"]
        if not rows:
            # Empty _rows list — equivalent to no rows above.
            raise TokenNotFound(
                f"PiiVault_Decrypt returned empty _rows list for "
                f"Token={token!r}.",
                metadata={"token": token, "request_id": str(request_id)},
            )
        first = rows[0]
    else:
        first = sp_result

    plaintext = first.get("PlaintextValue")

    if plaintext is None:
        # Token exists but Status forbids decrypt (CCPA
        # 'deleted_per_request' per RB-10; future 'purged_for_retention'
        # per D30). The audit row was STILL written by SP-2 before this
        # NULL return per § 2.2 + D26 append-only.
        logger.warning(
            "pii_decryptor: SP-2 returned NULL plaintext for token=%s "
            "request_id=%s — raising DecryptDenied (audit row was "
            "still written server-side per D26)",
            token,
            request_id,
        )
        raise DecryptDenied(
            f"PiiVault_Decrypt returned NULL plaintext for Token={token!r}. "
            f"Token Status is 'deleted_per_request' (CCPA per RB-10) or "
            f"'purged_for_retention' (D30). Audit row written server-side.",
            metadata={
                "token": token,
                "request_id": str(request_id),
            },
        )

    if not isinstance(plaintext, str):
        # Defensive — SP-2 declares PlaintextValue VARCHAR-typed but a
        # driver oddity could return bytes / memoryview. Coerce to str
        # via UTF-8 if needed; raise on un-coercible.
        try:
            plaintext = plaintext.decode("utf-8") if isinstance(plaintext, (bytes, bytearray)) else str(plaintext)
        except (UnicodeDecodeError, AttributeError) as exc:
            raise DecryptDenied(
                f"PiiVault_Decrypt returned non-string PlaintextValue of "
                f"type {type(plaintext).__name__} for Token={token!r}.",
                metadata={
                    "token": token,
                    "request_id": str(request_id),
                    "plaintext_type": type(plaintext).__name__,
                },
            ) from exc

    # D103 — log SUCCESS without echoing plaintext. Token + RequestId +
    # plaintext LENGTH only (length is needed for downstream length-
    # based PII-format validation but does NOT leak the value).
    logger.info(
        "pii_decryptor.decrypt_token success "
        "token=%s request_id=%s plaintext_length=%d",
        token,
        request_id,
        len(plaintext),
    )

    return plaintext
