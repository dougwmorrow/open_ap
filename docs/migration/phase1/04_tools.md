# Phase 1, Round 4 — Tools

**Status**: 🟢 Locked via D72 architectural-review acceptance path (D73 precedent applied) — see `_validation_log.md` 2026-05-10 Round 4 D72 cycles 1-8 entry. Eight-cycle validation campaign (cycle 1 first-pass + cycles 2-3 D56 second/third-pass + cycle 4 Pattern E 5-agent deep validation + cycles 5-8 single-agent stress-test cadence) consumed 12 reviewer-agent passes and caught 19 cumulative 🔴 (4 cycle-1 + 4 cycle-2 + 3 cycle-3 + 4 cycle-4 + 0 cycle-5 + 2 cycle-6 + 0 cycle-7 + 2 cycle-8). Math infeasibility for 3-consecutive-clean convergence reached at cycle 8 (2 cycles remaining; need 3 streak) — per D72 escalation rule, architectural-review acceptance with explicit 🟡 BACKLOG carryover (B77-B107, 30 active items after B92 closed-in-cycle = 29 active for Round 5 close-out triage) is the realistic exit path mirroring Round 3 D73. Carryover items B95-B107 are 13 new Pitfall #9 sub-classes + clerical + framing items that survived multi-cycle review; they represent backlog-eligible polish, not structural defects. Constituent decisions D74-D77 lock with the spec doc.

This document is the operator-facing CLI surface specification for the UDM pipeline build. It freezes the argument parsers, exit-code contracts, invocation patterns, and Tier 0 smoke-test scaffolds for the eleven CLI scripts that wrap Round 3's module interfaces. **Implementation is deferred to Round 6 deployment** — this round produces CLI specs only.

Round 4 is the operator-experience freeze that Round 6's deployment scripts implement against. Round 5's test suite is authored against these CLI signatures (test-first per Round 5 scope). Per `02_configuration.md` § 0 and `phase1/03_core_modules.md` § 0 scope: this round consumes the module interfaces locked by Round 3 (`§ 1` – `§ 7` modules) without re-specifying their internals.

## Read order for this round (per D62 Canonical Context Load)

Agents and skills working on Round 4 perform CCL Stage 1+2 first per `MULTI_AGENT_GUIDE.md` § Canonical Context Load (D62). Reading order specific to Round 4:

1. `docs/migration/CURRENT_STATE.md` — confirm Round 4 is in flight; Rounds 1+2+3 just locked
2. `docs/migration/HANDOFF.md` — locked vs in-flight; Pitfall #9 (5 sub-classes, cross-table-column-lift) still applies; Pitfall #10 (Tier 0 sketch ≠ comprehensive test) still applies
3. `docs/migration/NORTH_STAR.md` — pillar priority; Round 4 primarily advances **Operationally stable** (operator-facing CLIs ARE the operations surface) + **Audit-grade** (every CLI invocation produces a `PipelineEventLog` audit row) + **Traceability** (BatchId + actor surfaces in event metadata) pillars
4. `docs/migration/CHECKS_AND_BALANCES.md` — 5-gate validation discipline + CCL preamble
5. `docs/migration/RISKS.md` — R03 (single-engineer Python expertise) is mitigation evidence; R19 (Tier 0 drift) extends to tools; R21 (Round 3 carryover) reminder that Round 5 owes the systematic B47-B74 revisit
6. `docs/migration/BACKLOG.md` — Round 4-adjacent items: B47-B74 (Round 3 carryover — Round 5 close-out triage); B75 + B76 (Round 2 cycle 1 Pattern E framing refinements — D64 wording + D71 in-memory keyring); B12 + B13 (Phase 0 deliv 0.11 + 0.12 — verify_server_parity / credentials_loader implementations)
7. `docs/migration/_validation_log.md` — past validation findings; Round 2 cycle 1 Pattern E entry is the most recent lesson (all 4 blocking reviewers ✅ on first cycle)
8. **This document**
9. `docs/migration/phase1/03_core_modules.md` (Round 3 — REQUIRED for Round 4): every tool in § 3 below wraps one or more Round 3 modules. Each tool spec cites the wrapped module's § path; readers consult Round 3 for the module's internal contract
10. `docs/migration/phase1/02_configuration.md` (Round 2): § 5 Automic job inventory — tools that fold into a scheduled job (gap_detector, verify_server_parity, enforce_retention, log_retention_cleanup) are invoked via the Automic job pattern per D66; § 2 `.env` keys consumed by every tool
11. `docs/migration/phase1/01_database_schema.md` (Round 1) — every SP this round's tools invoke; every table written to (PipelineEventLog, PipelineLog, ParquetSnapshotRegistry status flips, etc.); canonical DDL is the source of truth per **Pitfall #9**
12. `docs/migration/03_DECISIONS.md` (search by D-number) — D2/D5/D6/D11/D17/D22/D26/D29/D30/D33 are foundational; D62/D63/D64/D65/D66/D67/D68/D69/D70/D71/D72/D73 just locked
13. `CLAUDE.md` (project root) — existing `tools/` script convention reference (inspect_cdc_pk.py, validate_cdc.py, validate_scd2.py, repair_scd2.py, sweep_modified.py, backfill.py, detect_scd2_config.py); BCP CSV Contract; Do-NOT rules

## Scope

**In scope** (this document):

- **§ 1**: Cross-cutting CLI conventions — exit codes, dry-run defaults, argument naming, logging, Tier 0 scaffolding, invocation patterns (operator / Automic / pipeline-programmatic)
- **§ 2**: Foundational decisions (Round 4 dependencies — D-numbers + Round 3 modules wrapped)
- **§ 3**: Eleven CLI specs (per Phase 1 plan `PHASE_1_DEEP_DIVE_PLAN.md` § Round 4):
   - § 3.1 `tools/parquet_tier_review.py` — registry status transition walker (created → verified → replicated → archived → purged)
   - § 3.2 `tools/parquet_verify.py` — invoke `parquet_registry_client.verify_parquet_snapshot()` for a registry_id (operator retest)
   - § 3.3 `tools/lateness_profile.py` — CLI wrapper for `cdc/lateness_profiler.py` (ad-hoc operator analysis)
   - § 3.4 `tools/decrypt_pii.py` — CLI wrapper for `data_load/pii_decryptor.py` (justified operator decrypt path per P8)
   - § 3.5 `tools/detect_extraction_gaps.py` — CLI shim for `tools/gap_detector.py` (Round 3 § 5.3 — Round 4 specifies the CLI surface, Round 3 specifies the module)
   - § 3.6 `tools/promote_test_to_prod.py` — failover acknowledgment per D29 + D33 cooperative cancellation
   - § 3.7 `tools/verify_server_parity.py` — CLI shim for the module specified at Round 3 § 3.2 (Round 4 specifies operator-facing arg parser + exit codes; Round 3 specifies the verifier)
   - § 3.8 `tools/enforce_retention.py` — invoke SP-10 `EnforceRetention` per D30 (retention sweep across vault + provenance + log tables)
   - § 3.9 `tools/process_ccpa_deletion.py` — invoke the CCPA deletion SP (B01) per D30 + RB-10
   - § 3.10 `tools/log_retention_cleanup.py` — purge old `PipelineLog` rows per retention policy
   - § 3.11 `tools/alert_dispatcher.py` — operator notification fanout. The ops-channel client (Slack / PagerDuty / email / SMTP) is currently UNSCOPED in Phase 0 (canonical 02_PHASES.md L48 defines 0.10 as "2x/day pipeline schedule windows"; there is NO Phase 0 deliverable for ops-channel routing). B82 tracks proposing a new Phase 0 deliverable + implementing the client at Round 6 deployment
- **§ 4**: Edge case mapping — M / S / I / N / P / G / D / F / V series walk against Round 4 CLI behaviors
- **§ 5**: Validation gates self-check (Gate 1 + Gate 5 + handoff to `udm-design-reviewer` for Gate 2)
- **§ 6**: Round 4 acceptance criteria checklist (run at close-out)

**Out of scope** (deferred):

- Python implementation bodies — Round 6 deploy + Round 5 test-first authoring
- Module-level interface changes — Round 3 locked; this round consumes them as-is. If a tool surfaces a missing module method, the gap goes to BACKLOG (B-number) and Round 6 deployment chooses whether to extend the module
- Tier 1/2/3 test code for tools — Round 5 (Tests); Tier 0 sketches in this doc are the build-time contract per D67
- Snowflake account setup — Phase 0 deliv 0.6
- Schema evolution governance procedure — Round 7
- Operator runbook narrative — `05_RUNBOOKS.md` already references some tools (RB-4 audit access, RB-7 failover drill, RB-8 Bronze rebuild, RB-10 CCPA deletion); Round 4 specs are referenced from those RBs (cross-link only)
- New Automic job inventory — Round 2 § 5.1 froze 8 jobs; if a Round 4 tool needs a new job, the request goes to BACKLOG (B-number) and Round 6 deployment chooses whether to amend the job set

## Foundational decisions (Round 4 dependencies)

| # | Decision | Round 4 dependency |
|---|---|---|
| D2 | Stage dropped; Parquet snapshots replace it | § 3.1 parquet_tier_review / § 3.2 parquet_verify (registry status state machine) |
| D5 | Snowflake-managed Iceberg | § 3.1 parquet_tier_review (replicated → archived transitions reference Snowflake mirror) |
| D6 | In-house tokenization vault | § 3.4 decrypt_pii (vault decrypt path; PiiVaultAccessLog audit) |
| D11 | Empirical L_99 lookback | § 3.3 lateness_profile (CLI wrapper for lateness_profiler) |
| D17 | Idempotency ledger pattern | Every CLI that performs side effects routes the side effect through `ledger_step()` from Round 3 § 4.1 — guarantees re-invocation safety |
| D22 | Hourly gap detector | § 3.5 detect_extraction_gaps (CLI shim) |
| D26 | Append-only PiiTokenProvenance / append-only audit trail | § 3.4 decrypt_pii MUST write PiiVaultAccessLog row; § 3.9 process_ccpa_deletion MUST write OrphanedTokenLog (per B01) |
| D27 | Cross-server parity contract | § 3.7 verify_server_parity (CLI shim) |
| D29 | Automic-driven AM/PM coordination + failover | § 3.6 promote_test_to_prod (failover acknowledgment per D29 revised); also impacts § 3.8 / 3.9 / 3.10 invocation patterns (Automic jobs vs operator) |
| D30 | 7-year retention with legal-hold override | § 3.8 enforce_retention (SP-10 wrapper); § 3.9 process_ccpa_deletion; § 3.10 log_retention_cleanup |
| D33 | Cooperative cancellation via gate flag | § 3.6 promote_test_to_prod (acknowledge cancellation per D33); every long-running tool periodically polls for cancellation request |
| D55 | 5-gate validation discipline | This round's status flip 🟡 → 🟢 requires `_validation_log.md` entry |
| D56 | Mandatory second-pass after 🔴 | Iterative validation cycles per D72 ceiling |
| D62 | CCL doctrine | § 0 "Read order" exists because of D62 |
| D65 | Parity drift severity classification | § 3.7 verify_server_parity exit-code contract (0 pass, 1 warn, 2 fatal) maps to D65 severity tiers |
| D66 | Automic job inventory + gate-table contract | § 3.5 / 3.7 / 3.8 are CLI surfaces invoked by the canonical frozen-8 jobs `JOB_GAP_DETECT` / `JOB_PARITY_VERIFY` / `JOB_RETENTION_MONTHLY` per Round 2 § 5.1 L1042-1050. § 3.10 (log_retention_cleanup) is NOT in frozen-8 — proposed `JOB_LOG_CLEANUP` tracked as B80 |
| D67 | Tier 0 build-time smoke test discipline | Every tool spec below includes a Tier 0 sketch with mocked subprocess + cursor; tests/smoke/test_tools_<name>.py |
| D68 | Error class hierarchy | Tools translate `PipelineFatalError` → exit code 2; `PipelineRetryableError` → exit code 1 (operator can retry) |
| D69 | Cursor ownership pattern | Every tool's CLI script is a single-process invocation; `cursor_for(db_name)` per call; no shared cursors |
| D70 | Test fixture strategy / 6-tier pyramid | Every § 3 tool's Tier 0 smoke + Test surface (Round 5) sections honor D70's tier definitions (Tier 0 build-time mandatory per D67; Tier 1 unit; Tier 2 property; Tier 3 Docker integration; Tier 4 crash injection; Tier 5 manual). Round 5 (Tests) consumes D70's strategy directly |
| D71 | Snowflake auth flow (ephemeral RSA key) | § 3.1 parquet_tier_review's `mark_replicated` callouts depend on Snowflake mirror status, but the tool itself does NOT decrypt the RSA key — that's done inside the wrapped module (`snowflake_uploader` § 7.1 from Round 3) |
| D72 | Validation cycle termination rule | This round's validation campaign respects the 10-cycle ceiling; Pattern E available if first-pass surfaces 🔴 in a structural class |
| D73 | Round 3 architectural-review carryover | Round 5 (Tests) MUST systematically revisit B47-B74; Round 4 does NOT re-litigate Round 3 issues — tools wrap Round 3 modules as-locked |

## New decisions anticipated in this round

These will be captured via `udm-decision-recorder` (per D62 — recorder reads `NORTH_STAR.md` to confirm canonical pillar names case-sensitively):

| Proposed | Topic | Pillar(s) served (canonical from NORTH_STAR.md) |
|---|---|---|
| D74 | CLI exit-code contract — `0 = success / 0-rows-affected (idempotent no-op or dry-run preview)`, `1 = expected operational failure (e.g. nothing to process / dry-run found drift / Automic should re-run after operator intervention)`, `2 = fatal error (config missing, auth failure, unhandled exception, FATAL exception class)`. Codifies the operator's "is this normal?" mental model: 0 = always normal; 1 = something to look at but not an emergency; 2 = page someone | **Operationally stable**, **Audit-grade** |
| D75 | CLI argument naming + default semantics — `--source` / `--table` for filters; `--apply` opt-in for side-effecting tools (default = dry-run); `--all` to override filters (must be paired with `--apply` for side-effecting tools to prevent accidental fan-out); `--batch-id` accepted for tools the pipeline calls programmatically (skip auto-allocation from `PipelineBatchSequence`); `--actor` defaults to `'operator'` when interactive (TTY), `'automic'` when run by Automic (env var heuristic), `'pipeline'` when called programmatically; `--justification` required for any decrypt or override path per D6 + P8 audit semantics | **Operationally stable**, **Audit-grade**, **Traceability** |
| D76 | CLI audit-row contract — every CLI invocation writes ONE `PipelineEventLog` row with `EventType='CLI_<TOOL_NAME>'` (canonical naming) + `Metadata` JSON containing `argv`, `actor`, `dry_run`, `apply`, plus tool-specific fields (registry_id, source_filter, etc.). Sensitive fields redacted by `SensitiveDataFilter` from Round 3 § 6.1 before write. Pipeline-programmatic invocations (where the caller already has a BatchId + EventLog row) skip the CLI audit row to avoid duplicate events — controlled by `--no-audit-event` flag (default off; ON when `--actor pipeline`) | **Audit-grade**, **Traceability** |
| D77 | CLI Tier 0 scaffold pattern — `tests/smoke/test_tools_<name>.py` runs in <5s with mocked subprocess + mocked cursor; checks (a) `python3 tools/<name>.py --help` exits 0 with non-empty stdout; (b) arg parser accepts canonical argument set; (c) `--dry-run` (or default-dry-run mode) does not call any side-effecting cursor; (d) `--apply` invokes the wrapped module's main function (mocked) with expected positional+keyword args; (e) exception → expected exit code mapping per D74. Provides a uniform Tier 0 contract across all 11 CLIs | **Operationally stable**, **Audit-grade** |

If a tool surface uncovers additional choice points (e.g. structured-output `--json` for machine consumers, batch-vs-streaming semantics for retention sweeps), more D-numbers will follow with full pillar mapping.

---

## § 1. Cross-cutting CLI conventions

This section codifies the operator-experience invariants that every Round 4 tool obeys. Tool specs in § 3 cite this section by sub-number; the sub-numbers are normative.

### § 1.1 Exit-code contract (per D74 proposed)

| Code | Meaning | Operator action |
|---|---|---|
| **0** | Success. Side effects completed (or dry-run preview produced; or idempotent no-op short-circuit). Tool output (stdout) is the authoritative summary. PipelineEventLog row written with `Status='SUCCESS'`. | None — normal completion |
| **1** | Expected operational failure. Examples: nothing to process (idempotent no-op intentional); dry-run found drift requiring `--apply`; Automic should re-run after operator intervention (e.g. parity drift in `warning` tier per D65). Stdout describes the reason. PipelineEventLog row with `Status='FAILED'` + `ErrorMessage` populated. | Operator review; not page-able |
| **2** | Fatal error. Examples: config missing, GPG envelope decrypt failure, vault auth failure, FATAL exception class per D68 (`PipelineFatalError` subclasses). Stack trace in stderr; `PipelineEventLog` row with `Status='FAILED'` + full error context. | Page; operator must intervene |

**Implementation pattern** (per D74):

```python
import sys
from typing import NoReturn

EXIT_SUCCESS = 0
EXIT_OPERATIONAL_FAILURE = 1
EXIT_FATAL = 2

def exit_with_audit(code: int, *, event_state, message: str = "") -> NoReturn:
    """Write the final audit row, flush observability buffers, exit with code.
    event_state is the EventState yielded by event_tracker.track() context manager
    (Round 3 § 6.3). Caller has populated metadata fields by now."""
    # event_tracker context-manager exit handles the Status flip via Round 3 § 6.3
    sys.exit(code)
```

**Pitfall**: NEVER exit with code `0` if the wrapped module raised a `PipelineFatalError` — even if the operator-facing message reads "no rows to process", a FATAL underneath is a code-2 situation. Tier 0 (per § 1.6) asserts this mapping explicitly.

### § 1.2 Dry-run default (per D75 proposed)

Tools that perform side effects on PROD-state data (`mark_replicated`, `mark_archived`, `mark_purged`, vault decrypts, retention purges, CCPA deletes, gate flag flips) default to **dry-run mode**. Operator must pass `--apply` to actually mutate state.

Tools that are **read-only by design** (`lateness_profile`, `detect_extraction_gaps`, `verify_server_parity`) do NOT have an `--apply` flag — they always run, and they always produce a report. A failed parity check exits 1 (or 2 if fatal tier) but does not "apply" anything because there's nothing to apply.

**Decision rule**: if the tool calls a module function whose docstring says "Side effects: ..." with any write to DB or filesystem, the tool needs `--apply`. If the docstring says "Returns: report" with no writes, the tool does not need `--apply`.

### § 1.3 `--help` text contract (per D75 + D77 proposed)

Every CLI script's `argparse.ArgumentParser` is constructed with `description=__doc__.splitlines()[0]` (per the existing `tools/` convention — see `tools/inspect_cdc_pk.py`, `tools/repair_scd2.py`). The script's module-level docstring is the canonical `--help` body and contains:

1. **One-line summary** at the very top — what the tool does
2. **Usage examples** block — at least 2 invocations covering: read-only / dry-run / apply (where applicable)
3. **What it does** narrative — 3-5 sentences expanding the summary
4. **Side effects** section — DB tables / files / Snowflake operations / network notifications written
5. **Read-only or dry-run-default declaration** — explicit sentence about whether `--apply` is required
6. **Exit-code reference** — per § 1.1 contract; tool-specific codes (e.g. parity verifier exit 1 = warning tier, exit 2 = fatal tier) documented
7. **Cross-references** — Round 3 § path of the wrapped module; relevant runbook (RB-N)

Example skeleton:

```python
"""<one-line summary>.

Usage::

    # Dry-run (default for side-effecting tools)
    python3 tools/<name>.py --source DNA --table ACCT

    # Apply
    python3 tools/<name>.py --source DNA --table ACCT --apply

What it does
------------

<3-5 sentences>

Side effects (when --apply)
----------------------------

* INSERT to General.ops.PipelineEventLog with EventType='CLI_<NAME>'
* <wrapped module side effects>

Default is dry-run; --apply is required to mutate state.

Exit codes
----------

* 0: success (or dry-run preview)
* 1: expected operational failure (nothing to do / dry-run found drift)
* 2: fatal error (config / auth / FATAL exception)

References
----------

* Wraps Round 3 § <X.Y> (`<module>.py`)
* RB-N (relevant runbook)
"""
```

### § 1.4 Argument naming conventions (per D75 proposed)

Canonical argument names — every tool MUST use these names where applicable:

| Argument | Type | Default | Semantics |
|---|---|---|---|
| `--source` | str | None | Filter by `SourceName` (`UdmTablesList.SourceName`). Examples: `DNA`, `CCM`, `EPICOR`. None = no filter |
| `--table` | str | None | Filter by `TableName` / `SourceObjectName`. None = no filter |
| `--all` | flag | False | Override filter ABSENCE — required when no `--source` / `--table` given AND tool would otherwise refuse to run on the unfiltered set. Must pair with `--apply` for side-effecting tools |
| `--apply` | flag | False | Opt-in to side-effecting mutations. Default is dry-run for tools that have one |
| `--dry-run` | flag | True for side-effecting tools | Explicit dry-run opt-in (redundant for tools that default to dry-run; useful for documentation / scripting clarity) |
| `--batch-id` | int | None | Provide a pre-allocated BatchId (skips `PipelineBatchSequence` auto-allocate). Used by pipeline-programmatic callers |
| `--actor` | str | TTY heuristic | One of `'operator'` / `'automic'` / `'pipeline'` / `'reconciliation'`. Surfaces in `PipelineEventLog.Metadata.actor` for audit |
| `--justification` | str | None | Required for any decrypt or override path (per D6 + P8). Free-text; surfaces in audit row |
| `--no-audit-event` | flag | False | Skip writing the CLI invocation's own `PipelineEventLog` row. Pipeline-programmatic callers set this when the parent operation has its own audit row (avoid duplicate events) |
| `--verbose` / `-v` | count | 0 | Logging level: 0=INFO, 1=DEBUG, 2=DEBUG + extra detail |
| `--quiet` / `-q` | flag | False | Suppress stdout summary; only exit code communicates result. Useful in Automic where stdout is dropped |
| `--json` | flag | False | Emit machine-readable JSON to stdout instead of human-readable text. Compatible with `jq` |

Tool-specific arguments (`--registry-id`, `--retention-days`, `--token`, etc.) use lower-kebab-case consistent with the canonical names.

### § 1.5 Logging — PipelineLog + stdout (per D67 + D76 proposed)

Every CLI invocation produces logs on two channels:

1. **PipelineLog** (via `SqlServerLogHandler` from Round 3 § 6.2) — structured rows for all severity levels; `SensitiveDataFilter` from § 6.1 redacts plaintext before write. Triggered by standard `logger.info()` / `logger.warning()` etc. calls inside the tool
2. **stdout** — human-readable summary at end of invocation; suppressed by `--quiet`; replaced with JSON by `--json`. NEVER includes plaintext PII (sensitive_data_filter runs on stdout writes too — implementation detail per § 1.7)

Log level defaults to INFO (override via `-v` / `-vv` per § 1.4). Tool-specific WARNING / ERROR conditions documented per tool in § 3.

### § 1.6 Tier 0 smoke per tool (per D67 + D77 proposed)

Every tool in § 3 includes a Tier 0 smoke test at `tests/smoke/test_tools_<name>.py` that:

- Runs in **<5 seconds** with NO external dependencies (no Docker, no real DB, no network)
- Asserts (a) module imports without error; (b) `python3 tools/<name>.py --help` returns exit 0 with non-empty stdout; (c) arg parser accepts the canonical argument set without raising; (d) `--dry-run` / default-dry-run does NOT call any side-effecting cursor (verified by asserting on mock cursor `execute` count); (e) `--apply` invokes the wrapped module function (mocked) with the expected positional + keyword args; (f) exception → expected exit code mapping per § 1.1 — `PipelineFatalError` → exit 2; `PipelineRetryableError` → exit 1; success → exit 0
- Per **Pitfall #10** (HANDOFF § 8): Tier 0 is the smoke screen, NOT the comprehensive test. Tier 1 tests in Round 5 cover the real behavioral surface

The Tier 0 sketch is normative — Round 5 may extend it but may not weaken it. Per D67: Tier 0 must pass before any commit that touches the tool.

### § 1.7 Invocation patterns (per D75 proposed)

Every tool supports **three invocation patterns** with overlapping but distinct semantics:

| Pattern | Trigger | `--actor` default | `--no-audit-event` default | Notes |
|---|---|---|---|---|
| **Operator** (interactive) | Human runs `python3 tools/<name>.py` in a terminal | `'operator'` (TTY detected via `sys.stdin.isatty()`) | False (audit event written) | Default mode. Stdout shown to operator |
| **Automic** (scheduled) | Automic job calls the tool with explicit args; no TTY | `'automic'` (env var `AUTOMIC_RUN_ID` or absence-of-TTY heuristic) | False (audit event written) | Stdout captured to Automic's job log + PipelineLog. Cancellation flag polled every N seconds per D33 |
| **Pipeline** (programmatic) | A Round 3 module imports and calls the tool's `main()` function directly | `'pipeline'` (caller passes `--actor pipeline` explicitly) | True (parent has audit row) | Tool's stdout suppressed; result returned via Python return value (where supported) |

Heuristic for `--actor` default:
1. If `--actor` explicitly passed → honor it
2. Else if `AUTOMIC_RUN_ID` env var set → `'automic'`
3. Else if `sys.stdin.isatty()` → `'operator'`
4. Else → `'pipeline'` (defensive default — programmatic callers should pass explicitly anyway)

### § 1.8 Error handling — exception → exit code (per D74 + D68)

Per D68 hierarchy (Round 3 § 8.1):

```python
from utils.errors import (  # to be created — Round 6 deployment task per D68
    PipelineError,
    PipelineFatalError,
    PipelineRetryableError,
)

def cli_main_wrapper(main_fn) -> int:
    """Standard CLI exception-handling wrapper. Wraps every tool's main()."""
    try:
        return main_fn()
    except PipelineFatalError as exc:
        logger.critical("FATAL: %s", exc, exc_info=True)
        return EXIT_FATAL  # 2
    except PipelineRetryableError as exc:
        logger.warning("Operational failure: %s", exc)
        return EXIT_OPERATIONAL_FAILURE  # 1
    except KeyboardInterrupt:
        logger.warning("Interrupted by operator")
        return EXIT_OPERATIONAL_FAILURE  # 1
    except Exception:  # pylint: disable=broad-except
        logger.critical("Unexpected exception", exc_info=True)
        return EXIT_FATAL  # 2
```

**Pitfall**: bare `except Exception:` MUST be `logger.critical(...)` + return code 2 — never silently swallow. Tier 0 asserts the mapping holds.

### § 1.9 Boilerplate template (every tool follows)

Each CLI script in § 3 has this shape:

```python
"""<one-line summary>.

<full --help body per § 1.3>
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Imports of Round 3 modules being wrapped:
from data_load.<wrapped_module> import <main_fn>  # noqa: E402
# ... etc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # Canonical args per § 1.4:
    parser.add_argument("--source", help="Filter by SourceName.")
    parser.add_argument("--table", help="Filter by TableName.")
    parser.add_argument("--all", action="store_true", help="No filter; must pair with --apply for side-effecting tools.")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Default: dry-run.")
    parser.add_argument("--actor", default=None, help="One of operator/automic/pipeline/reconciliation. Auto-detected by default.")
    parser.add_argument("--no-audit-event", action="store_true", help="Skip CLI-level PipelineEventLog write (pipeline-programmatic callers).")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout.")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress stdout summary.")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase log verbosity.")
    # Tool-specific args per § 3.x:
    # parser.add_argument("--registry-id", type=int, ...)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    # Resolve actor per § 1.7 heuristic
    actor = args.actor or _detect_actor()
    # Set log verbosity per § 1.5
    if args.verbose >= 1:
        logging.getLogger().setLevel(logging.DEBUG)
    # Per § 1.8 exception handling
    try:
        return _run(args, actor=actor)
    except PipelineFatalError as exc:
        logger.critical("FATAL: %s", exc, exc_info=True)
        return EXIT_FATAL
    except PipelineRetryableError as exc:
        logger.warning("Operational failure: %s", exc)
        return EXIT_OPERATIONAL_FAILURE
    except Exception:  # pylint: disable=broad-except
        logger.critical("Unexpected exception", exc_info=True)
        return EXIT_FATAL


def _run(args, *, actor: str) -> int:
    """Tool-specific logic. Returns exit code per § 1.1."""
    # ...
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
```

This template is normative — every § 3 tool conforms.

### § 1.10 Pitfall #9 compliance (every tool spec)

Per HANDOFF Pitfall #9 (all 5 sub-classes — column name, parameter name, enum value, type widths, Unicode-vs-ASCII, cross-table column-name lift), every CLI tool spec in § 3 that references a Round 1 column name, SP parameter, enum value, OR Round 3 module function/argument name MUST cite the exact canonical source (`file:line` or `file § X.Y`). The producer Gate 1 self-check (§ 5.1) AND the Gate 2 independent reviewer both verify EVERY such reference against the canonical source. **No invented column names. No invented parameter names. No invented enum values. No invented module function names.** Round 2 + Round 3 collectively found 17 🔴 across this exact failure mode — Round 4 explicitly defends via the citation requirement.

---

## § 2. Tool specs — preamble

Tool specs in § 3 follow this template (per `udm-data-engineer-review` skill's interface review pattern + § 1.3 + § 1.9):

```markdown
### § 3.N tools/<name>.py

**Purpose**: <one-sentence what this tool does for the operator>
**Wraps**: <Round 3 § X.Y module path> + <other modules>
**Consumes**: <D-numbers; Round 1 SPs / tables; Round 2 columns / env keys; canonical references per Pitfall #9>
**Produces**: <stdout summary; PipelineEventLog row; side effects on target table/file>
**Invocation patterns** (per § 1.7): <operator / Automic / pipeline mix>
**Idempotency** (per D15 + D17): <how same-input re-invocation is safe>
**Error modes** (per D68 + § 1.8): <which Round 3 exceptions propagate; exit-code mapping per § 1.1>
**Concurrency** (per D69): <serial / parallel safety; sp_getapplock if applicable>

**CLI interface**:

```bash
python3 tools/<name>.py [canonical args per § 1.4] [tool-specific args]
```

**Tool-specific arguments**: <table of args + types + defaults + semantics>

**Stdout** (success): <one-paragraph description of the human-readable output>
**Stdout** (`--json`): <description of JSON schema>

**Exit codes** (per § 1.1 + tool-specific): <0/1/2 + tool-specific cases>

**Tier 0 smoke test** (per § 1.6 + D67): <`tests/smoke/test_tools_<name>.py` — specific assertion list>

**Test surface (Round 5)**: <Tier 1 unit; Tier 2 property; Tier 3 integration sketches>

**Cross-doc references**: <Round 3 § path; Round 2 § path; Round 1 § path; runbook RB-N; edge case series>
```

This template is normative — every § 3 tool conforms.

---

## § 3. Tool specs (11 tools)

### § 3.1 `tools/parquet_tier_review.py`

**Purpose**: Walk all `ParquetSnapshotRegistry` rows in a given Status; report ages, sizes, and recommended next transition (created → verified, verified → replicated, replicated → archived, archived → purged per D30 retention). Operator-facing aid for the registry status state machine documented at Round 3 § 1.3.

**Wraps**: Round 3 § 1.3 `data_load/parquet_registry_client.py` (`query_snapshot` for read; `mark_replicated` / `mark_archived` / `mark_purged` for write when `--apply`).

**Consumes**:
- Decisions: D2, D5 (replicated → archived references Snowflake mirror), D25 (registry as canonical Parquet index), D30 (retention semantics), D67, D74-D77 (proposed)
- Round 1: `ParquetSnapshotRegistry` (status enum: `created`, `verified`, `replicated`, `archived`, `missing`, `purged`, `replication_failed` — 7 states per Round 3 § 1.3 `ParquetSnapshotStatus` StrEnum; verified against `01_database_schema.md` ParquetSnapshotRegistry DDL per Pitfall #9)
- Round 3 § 1.3 keyword-only signatures (canonical per L452-475): `query_snapshot(*, source_name, table_name, business_date, batch_id)`, `mark_replicated(*, registry_id, replica_target)`, `mark_archived(*, registry_id, archive_location)`, `mark_purged(*, registry_id, retention_batch_id)`
- Round 2: `02_configuration.md` § 5.1 `JOB_RETENTION_MONTHLY` (which calls this tool in `--apply` mode for the archived → purged step per D30)

**Produces**:
- stdout: table of registry rows in the chosen Status with columns `(RegistryId, SourceName, TableName, BusinessDate, BatchId, AgeDays, CompressedMB, RecommendedAction)` — same column set + same order in both human and JSON modes. `CompressedMB` is computed `CompressedBytes / 1024 / 1024` for operator readability; canonical column is `ParquetSnapshotRegistry.CompressedBytes BIGINT NOT NULL` per `01_database_schema.md` L492. (The registry also stores `UncompressedBytes` per L491 for compression-ratio diagnostics; tool exposes compressed size by default since that's the on-disk number operators care about for storage planning. Add `--include-uncompressed` flag if both are needed — close-out polish.)
- (dry-run): NO writes to `ParquetSnapshotRegistry`; ONE `PipelineEventLog` row with `EventType='CLI_PARQUET_TIER_REVIEW'` for the CLI invocation itself
- (`--apply`): per-row UPDATE on `ParquetSnapshotRegistry.Status` via Round 3 § 1.3 transition functions; one `PipelineEventLog` row per transition (event_tracker per Round 3 § 6.3); operator-visible progress on stdout. Per-row transition events have `EventType` matching the wrapped Round 3 function's event-emit pattern (e.g. `PARQUET_REPLICATE` for `mark_replicated`); the CLI-invocation event is separate and uses `EventType='CLI_PARQUET_TIER_REVIEW'`. D76 is honored at the CLI level; the per-row events are Round 3 module events, not CLI events

**Invocation patterns** (per § 1.7):
- **Operator**: ad-hoc review (`--from-status verified --to-status replicated --dry-run`)
- **Automic**: `JOB_RETENTION_MONTHLY` calls this tool with `--from-status archived --to-status purged --apply --age-days 2555` (7 years) at month-end
- **Pipeline**: NOT a typical pipeline-programmatic path (pipeline writes are via `parquet_writer` § 1.1 + `verify_parquet_snapshot` § 1.3 directly, not through this CLI)

**Idempotency** (per D15 + D17 + Round 3 § 1.3 status-flip idempotency):
- Round 3 § 1.3 transition functions are idempotent at the row level (re-flip `verified` → `verified` is a no-op)
- Re-running the tool on the same Status set returns identical recommendation list (read-only path)
- `--apply` re-run: rows already in target Status are no-ops (filtered out by predecessor-Status SELECT); no double-INSERT to event log

**Error modes** (per D68 + § 1.8):
- `RegistryStatusInvalid` from Round 3 § 1.3 → exit 2 (FATAL: bug, should never happen if predecessor SELECT filters correctly)
- `RegistryFileNotFound` from Round 3 § 1.3 (when transitioning out of `verified` or `replicated`) → exit 2; recommend re-run after `mark_missing` invocation
- Connection failure → `PipelineRetryableError` per Round 3 § 1.3 retry pattern → exit 1
- No rows matched the Status filter → exit 0 (idempotent no-op — operator may interpret as "nothing to do, normal")

**Concurrency** (per D69):
- Single-process; `cursor_for('General')` per call
- `--workers` not supported (this is operator-facing; serial is fine; per-row WRITEs are independent + UNIQUE-guarded at the registry level)
- Concurrent runs of this tool: same row may be touched twice; second tool's predecessor-Status filter naturally skips it; no race

**CLI interface**:

```bash
# Read-only review of all 'verified' rows ready for replication
python3 tools/parquet_tier_review.py --from-status verified --dry-run

# Apply: archive all 'replicated' rows older than 30 days
python3 tools/parquet_tier_review.py --from-status replicated --to-status archived \
    --age-days 30 --archive-location 's3://offsite-bucket/udm-archive/' --apply

# Apply: purge all 'archived' rows older than 7 years (Automic-driven)
python3 tools/parquet_tier_review.py --from-status archived --to-status purged \
    --age-days 2555 --apply
```

**Tool-specific arguments**:

| Argument | Type | Default | Semantics |
|---|---|---|---|
| `--from-status` | str (StrEnum value) | `'verified'` | Source Status filter. One of `created`, `verified`, `replicated`, `archived`, `missing`, `purged`, `replication_failed` (Round 3 § 1.3 ParquetSnapshotStatus StrEnum). Has a sensible default (`'verified'` — the most common operator review surface); operator can override |
| `--to-status` | str (StrEnum value) | None | Target Status for `--apply` mode. None = report-only. Validated against status-machine state graph (created → verified → replicated → archived → purged is the canonical chain) |
| `--age-days` | int | None | Filter rows where `LastVerifiedAt` (or `CreatedAt` for `created`) is older than N days. None = no age filter |
| `--archive-location` | str | None | Required when `--to-status archived`. Maps to Round 3 § 1.3 `mark_archived(archive_location)` argument |
| `--replica-target` | str | None | Required when `--to-status replicated`. Maps to Round 3 § 1.3 `mark_replicated(replica_target)` argument (typical: `'snowflake:UDM_BRONZE_MIRROR'` per Round 3 § 1.3 example) |
| `--retention-batch-id` | int | None | Required when `--to-status purged`. Ties the purge to a `JOB_RETENTION_MONTHLY` event row per Round 3 § 1.3 `mark_purged(retention_batch_id)` |

**Stdout** (success, dry-run): tab-separated table with columns `RegistryId SourceName TableName BusinessDate BatchId AgeDays CompressedMB RecommendedAction` followed by a one-line summary `N rows matched; would transition to <to-status>`. (`CompressedMB` is computed from canonical `ParquetSnapshotRegistry.CompressedBytes` per L492 — see Produces section above.)

**Stdout** (`--json`): list of dicts with the above keys + `error_message` (NULL on success rows).

**Exit codes** (per § 1.1):
- 0: success (rows transitioned successfully OR dry-run completed OR no rows matched filter)
- 1: at least one row failed transition with a retryable error; operator can re-run
- 2: fatal — config missing, registry unreachable, invalid predecessor (bug class)

**Tier 0 smoke test** (per § 1.6 + D67): `tests/smoke/test_tools_parquet_tier_review.py` — runs in <5s, NO real DB. Asserts: (a) module imports; (b) `--help` exits 0 with non-empty stdout; (c) `parser.parse_args(['--from-status', 'verified', '--dry-run'])` returns expected Namespace; (d) `--apply` without `--to-status` raises arg-parse error (exit 2); (e) mocked cursor with 3 synthetic `verified` rows + `--dry-run` returns exit 0, calls `query_snapshot` exactly 3 times, calls NO `mark_*` function; (f) mocked `mark_replicated` raising `RegistryStatusInvalid` returns exit 2; (g) mocked successful `--apply` calls `mark_replicated` exactly 3 times (matching row count).

**Test surface (Round 5)**:
- Tier 1: each status transition path (created → verified, verified → replicated, replicated → archived, archived → purged) — happy path + invalid predecessor + age filter
- Tier 1: `--age-days 30` filter — rows newer than 30 days NOT touched
- Tier 1: per-error-path coverage (missing file, connection drop, status invalid)
- Tier 2 property: status-machine state graph — never transitions to an invalid predecessor; never skips a state
- Tier 3 integration: real registry table with synthetic rows; full transition chain end-to-end

**Cross-doc references**: Round 3 § 1.3; Round 1 ParquetSnapshotRegistry DDL; D2, D5, D25, D30; Round 2 § 5.1 `JOB_RETENTION_MONTHLY`; RB-8 (Bronze rebuild may consult this tool's output for available snapshots).

---

### § 3.2 `tools/parquet_verify.py`

**Purpose**: Invoke `parquet_registry_client.verify_parquet_snapshot()` (Round 3 § 1.3) for a specific `registry_id` (or batch of `registry_ids`); flip Status `created` → `verified` after independent SHA-256 + row-count check. Operator-facing retest aid (post-crash recovery; post-doubt audit).

**Wraps**: Round 3 § 1.3 `verify_parquet_snapshot(*, registry_id, actor)` keyword-only signature (canonical per Round 3 § 1.3 L441-445).

**Consumes**:
- Decisions: D2, D4 (network drive Parquet), D16 (inflight-rename pattern — verify catches files with rename completed but registry not flipped), D67, D74-D77 (proposed)
- Round 1: `ParquetSnapshotRegistry` (read full row to confirm `Status='created'` and load file path / row count / SHA from registry)
- Round 3 § 1.3: `verify_parquet_snapshot(*, registry_id, actor)` keyword-only signature, returning `ParquetVerifyResult` with canonical fields `(registry_id, file_path, sha256_verified, row_count_verified, last_verified_at, status)`

**Produces**:
- stdout: per-`registry_id` line `RegistryId <id> <file_path> <result>` where result ∈ `{VERIFIED, MISSING, HASH_MISMATCH, STATUS_INVALID, ERROR}`; summary line at end
- (`--apply` OR default — this tool is the verifier itself; "dry-run" mode reads the file + computes SHA but does NOT flip the registry Status; "apply" mode flips Status `created` → `verified` on success)
- per-verified row: ONE `PipelineEventLog` event via event_tracker (Round 3 § 6.3) with `EventType='CLI_PARQUET_VERIFY'`
- per-missing/mismatch row: stderr stack trace + `PipelineEventLog` with `Status='FAILED'`

**Invocation patterns** (per § 1.7):
- **Operator**: re-verify a suspect file after a crash (`--registry-id 12345 --apply`)
- **Automic**: `JOB_PARQUET_VERIFY` (NEW — proposed; not in Round 2 § 5.1 frozen-8 inventory; goes to BACKLOG B-number if Round 4 close-out adds it. Round 6 deployment chooses whether to amend the Automic job set per scope-exclusion above) — alternative: this is invoked inline by parquet_writer's caller orchestrator; the standalone CLI is for operator post-hoc retest only
- **Pipeline**: typical pipeline path invokes `verify_parquet_snapshot()` directly from the orchestrator after `write_parquet_snapshot()` — does NOT shell-out to this CLI

**Idempotency** (per D15 + Round 3 § 1.3 idempotency):
- Re-call on a row already at `Status='verified'`: Round 3 § 1.3 docstring states "Idempotent: re-call after success is a no-op". Tool returns exit 0 with `SKIPPED_ALREADY_VERIFIED`
- Re-call on a row with `Status='missing'` or `'purged'`: `RegistryStatusInvalid` → exit 2

**Error modes** (per D68 + § 1.8):
- `RegistryStatusInvalid` → exit 2 (FATAL — caller passed a registry_id in the wrong state; operator must investigate)
- `RegistryFileNotFound` → exit 1 (file is missing; operator should call separate `mark_missing` workflow — surfaced via `tools/parquet_tier_review.py --to-status missing` not yet built; this is a BACKLOG candidate for Round 6 deployment)
- `RegistryHashMismatch` → exit 2 (FATAL — file corruption; escalate per RB-6 / RB-8 + alert via `tools/alert_dispatcher.py` § 3.11 — ops-channel client is B82-tracked, see § 3.11)

**Concurrency** (per D69):
- `cursor_for('General')` per call
- Concurrent verifies of DIFFERENT registry_ids are independent; concurrent verifies of the SAME registry_id are serialized by SQL Server row locking (Round 3 § 1.3 concurrency note)
- `--workers N` supported via thread pool for multi-row batch invocation; each thread has its own cursor

**CLI interface**:

```bash
# Verify one specific registry row
python3 tools/parquet_verify.py --registry-id 12345 --apply

# Verify all 'created' rows for DNA.ACCT in a date range
python3 tools/parquet_verify.py --source DNA --table ACCT \
    --business-date-from 2026-04-01 --business-date-to 2026-04-30 --apply

# Dry-run: compute SHA + check file existence but do NOT flip Status
python3 tools/parquet_verify.py --source DNA --table ACCT --dry-run
```

**Tool-specific arguments**:

| Argument | Type | Default | Semantics |
|---|---|---|---|
| `--registry-id` | int (repeatable) | None | Specific `ParquetSnapshotRegistry.RegistryId` to verify. Mutually exclusive with `--source` / `--table` filters |
| `--business-date-from` | date (ISO-8601) | None | Range filter lower bound on `BusinessDate` |
| `--business-date-to` | date (ISO-8601) | None | Range filter upper bound on `BusinessDate` |
| `--workers` | int | 1 | Concurrency for batch invocations. 1 = serial; >1 = thread pool. Per § 1.7 invocation pattern, pipeline-programmatic callers usually pass 1 |
| `--continue-on-error` | flag | False | Don't abort on the first failed row; continue through all rows, then exit with code 1 if any failed. Useful for Automic batch invocations |

**Stdout** (success, `--apply`): one line per registry_id `RegistryId <id> <file_path> VERIFIED`; final summary `N verified / M failed / K skipped (already verified)`.

**Stdout** (`--dry-run`): one line per registry_id `RegistryId <id> <file_path> WOULD_VERIFY (sha=<sha256> rows=<count>)`.

**Stdout** (`--json`): list of dicts with canonical `ParquetVerifyResult` fields plus tool-level diagnostic fields — `{"registry_id": N, "file_path": "...", "sha256_verified": "<64-char-hex>", "row_count_verified": N, "last_verified_at": "<ISO-8601>", "status": "verified|missing|hash_mismatch|status_invalid|error", "error_message": null|"..."}`. `sha256_verified` matches the registry SHA-256 on success; on hash-mismatch failure the `error_message` includes both the computed and expected SHAs for operator diagnosis (the tool emits this diagnostic detail; the canonical dataclass does not — when mismatch is detected, `verify_parquet_snapshot` raises `RegistryHashMismatch` and the CLI catches + extracts the diagnostic from the exception).

**Exit codes** (per § 1.1):
- 0: all rows verified successfully (or skipped because already verified)
- 1: at least one row failed with `RegistryFileNotFound` or non-fatal verify error; operator can investigate and retry
- 2: fatal — `RegistryStatusInvalid` (caller error) or `RegistryHashMismatch` (corruption) or config / connection

**Tier 0 smoke test** (per § 1.6): `tests/smoke/test_tools_parquet_verify.py` — runs in <5s, NO real DB / filesystem. Asserts: (a) module imports; (b) `--help` exits 0; (c) `--registry-id 12345` parses; (d) `--registry-id` + `--source` together raises arg-parse error (mutual exclusion); (e) mocked `verify_parquet_snapshot` returning a successful `ParquetVerifyResult` → tool returns exit 0; (f) mocked `verify_parquet_snapshot` raising `RegistryStatusInvalid` → exit 2; (g) mocked `verify_parquet_snapshot` raising `RegistryFileNotFound` → exit 1; (h) `--dry-run` does NOT call `verify_parquet_snapshot` (verifies via mocked SHA-256 + file existence only, then exits).

**Test surface (Round 5)**:
- Tier 1: per-error-path coverage; happy path; `--dry-run` semantics
- Tier 1: `--continue-on-error` — second row's failure doesn't abort first/third row's success
- Tier 1: idempotent re-call returns `SKIPPED_ALREADY_VERIFIED`
- Tier 2 property: `verify_parquet_snapshot(write_parquet_snapshot(df))` is always `VERIFIED` (round-trip + verify identity)
- Tier 3 integration: real Parquet file on disk + real registry; happy path + induced corruption (truncate file by 1 byte) + induced row-count mismatch

**Cross-doc references**: Round 3 § 1.3; Round 1 ParquetSnapshotRegistry DDL; D2, D4, D16; RB-6 (vault recovery — for corruption escalation); RB-8 (Bronze rebuild via replay); B-1 (full SHA-256 hex).

---

### § 3.3 `tools/lateness_profile.py`

**Purpose**: CLI wrapper for `cdc/lateness_profiler.py` (Round 3 § 5.2). Operator runs this ad-hoc to measure empirical L_99 lateness (per D11) for a given `(source, table)`; the report drives `UdmTablesList.LookbackDays` operator-set configuration.

**Wraps**: Round 3 § 5.2 `profile_lateness(*, source_name, table_name, window_days, min_sample_days)` keyword-only signature (canonical per Round 3 § 5.2 L1143-1148), returning `LatenessReport`.

**Consumes**:
- Decisions: D11 (empirical L_99), D67, D74-D77 (proposed)
- Round 1: `PipelineExtraction` (SUCCESS rows historical), `PipelineEventLog` (extraction-start timestamps)
- Round 3 § 5.2: `profile_lateness()` returning `LatenessReport(source_name, table_name, window_start, window_end, sample_count, p50_days, p90_days, p95_days, p99_days, max_observed_days)`
- Round 2: `UdmTablesList.LookbackDays` (the report informs this value; operator sets manually based on `LookbackDays = ceil(p99) + safety_margin` per Round 3 § 5.2 docstring)

**Produces**:
- stdout: tabular report with `(SourceName, TableName, WindowStart, WindowEnd, SampleCount, p50, p90, p95, p99, MaxObserved)`; recommended `LookbackDays` value = `ceil(p99) + 1`
- ONE `PipelineEventLog` event row with `EventType='CLI_LATENESS_PROFILE'` and `Metadata` JSON containing the report (per § 1.5)
- Optional: row in `General.ops.LatenessProfile` (canonical Round 1 table per Round 3 § 5.2; verified per Pitfall #9 cross-table column-name-lift sub-class — earlier draft invented `LatenessProfileLog`, corrected at Round 3 cycle 4)

**Invocation patterns**:
- **Operator**: ad-hoc — "what's the L_99 for DNA.ACCT?" (`--source DNA --table ACCT`)
- **Automic**: NOT in Round 2 § 5.1 frozen-8 inventory. Could be added as `JOB_LATENESS_PROFILE_WEEKLY` in Round 6 (BACKLOG candidate)
- **Pipeline**: typical pipeline does NOT shell-out; it imports `profile_lateness()` directly

**Idempotency**:
- Read-only on historical data (Round 3 § 5.2 docstring: "read-only on historical data; report is reproducible from same input window")
- Multi-call returns identical `LatenessReport` for identical inputs
- Optional `LatenessProfile` row write is append-only (INSERT) per D26 audit posture; multi-invocations produce multiple history rows (intentional — trend tracking)

**Error modes**:
- `InsufficientHistory` (Round 3 § 5.2 — `PipelineFatalError` when sample count < `min_sample_days`) → exit 2 with stderr message "needs more history; run when ≥ N days of SUCCESS data available"
- Connection failure → exit 1 (retryable)

**Concurrency**: stateless read-only; multi-worker safe per Round 3 § 5.2.

**CLI interface**:

```bash
# Default 90-day window
python3 tools/lateness_profile.py --source DNA --table ACCT

# Custom window for large tables with longer history
python3 tools/lateness_profile.py --source DNA --table CARDTXN --window-days 180

# Force run with lower minimum sample threshold (operator override)
python3 tools/lateness_profile.py --source DNA --table NEWLOOKBACK --min-sample-days 14
```

**Tool-specific arguments**:

| Argument | Type | Default | Semantics |
|---|---|---|---|
| `--window-days` | int | 90 | Maps to Round 3 § 5.2 `window_days` parameter |
| `--min-sample-days` | int | 30 | Maps to Round 3 § 5.2 `min_sample_days` parameter. Override to lower threshold (operator can decide acceptable percentile reliability) |
| `--persist` | flag | True | Write a row to `General.ops.LatenessProfile` for trend tracking. Default ON; `--no-persist` suppresses |
| `--recommend-lookback` | flag | True | Include "recommended LookbackDays = ceil(p99) + 1" in stdout. Default ON |

**Stdout** (success): tabular report + recommended LookbackDays. Example:

```
Lateness profile for DNA.ACCT (window: 2026-02-09 → 2026-05-10, 90 days, 87 samples)
  p50  : 0.2 days
  p90  : 0.8 days
  p95  : 1.3 days
  p99  : 2.7 days
  max  : 4.1 days
Recommended UdmTablesList.LookbackDays = 4 (ceil(p99) + 1 safety margin)
```

**Stdout** (`--json`): `{"source_name": "...", "table_name": "...", "window_start": "...", "window_end": "...", "sample_count": N, "p50_days": X, ..., "recommended_lookback_days": Y}`.

**Exit codes**:
- 0: report produced successfully
- 1: connection / vault retryable error during query (operator can re-run; not page-able)
- 2: fatal — `InsufficientHistory` (Round 3 § 5.2 `PipelineFatalError` per § 1.8 mapping; operator should re-run when more data accumulates AND `min_sample_days` threshold met), config / connection setup failure, unexpected exception

**Tier 0 smoke test** (per § 1.6): `tests/smoke/test_tools_lateness_profile.py` — runs in <5s. Asserts: (a) module imports; (b) `--help` exits 0; (c) `--source DNA --table ACCT` parses; (d) mocked `profile_lateness` returning a `LatenessReport` with valid percentiles → tool returns exit 0 with stdout containing "p99"; (e) mocked `profile_lateness` raising `InsufficientHistory` (PipelineFatalError) → tool returns exit 2 per § 1.8 mapping; (f) `--json` produces parseable JSON; (g) `--no-persist` does NOT call any DB write.

**Test surface (Round 5)**:
- Tier 1: monotonic ordering p50 ≤ p90 ≤ p95 ≤ p99 ≤ max in stdout
- Tier 1: insufficient history → exit 2 + helpful message
- Tier 1: `--json` schema stable
- Tier 1: `--persist` writes `LatenessProfile` row; `--no-persist` does not
- Tier 3 integration: real `PipelineExtraction` data with synthetic delay distribution; verify percentile computation against a known answer

**Cross-doc references**: Round 3 § 5.2; Round 1 PipelineExtraction + LatenessProfile DDL; D11; Round 2 § 1.1.1 (LookbackDays column).

---

### § 3.4 `tools/decrypt_pii.py`

**Purpose**: Operator-driven CLI wrapper for `data_load/pii_decryptor.py` (Round 3 § 2.2). Decrypt a token (or batch of tokens) with mandatory `--justification`; write audit row to `PiiVaultAccessLog` per P8 + D6. **Operator authority assumed** — pipeline service account does NOT have decrypt permission per D6 (the CLI script's RBAC is at the OS / SQL Server credential layer, not the script itself).

**Wraps**: Round 3 § 2.2 `decrypt_token(*, token, justification, request_id)` keyword-only signature (canonical per Round 3 § 2.2 L608-613), returning `str | None`.

**Consumes**:
- Decisions: D6 (vault decrypt path), D26 (append-only audit), D30 (CCPA-deleted tokens return None), P5 (no plaintext in logs), P8 (audit every decrypt), D67, D74-D77 (proposed)
- Round 1: SP-2 `PiiVault_Decrypt`; `PiiVaultAccessLog` table (canonical columns per Round 3 § 2.2 + `01_database_schema.md` L1033-1048)
- Round 3 § 2.2: `decrypt_token(*, token: str, justification: str, request_id: uuid.UUID | None)` keyword-only signature; returns `str | None`
- Round 3 § 6.1: `SensitiveDataFilter` for log output (CRITICAL — must prevent plaintext leak per P5)

**Produces**:
- stdout (per token): one line `<token-hint> -> <plaintext>` for normal decrypts; `<token-hint> -> <NULL> (CCPA-deleted)` for retention-purged tokens; `<token-hint> -> NOT_FOUND` for missing tokens (followed by exit 2 per Error modes; NOT_FOUND output appears on stderr/stdout but exit code distinguishes from success). The `<token-hint>` is first 4 chars + `<...>` + last 4 chars. **stdout MUST NOT be logged via SqlServerLogHandler** — plaintext to stdout is the intended operator output, but P5 forbids plaintext in `PipelineLog` rows. Implementation: stdout writes via `print()` direct; logging goes through filtered handler
- ONE `PiiVaultAccessLog` row per token per SP-2 invocation (audit per D6 + D26)
- ONE `PipelineEventLog` event row per CLI invocation (`EventType='CLI_DECRYPT_PII'`); `Metadata` JSON includes `actor`, `justification`, `request_id`, `token_count`, `null_count` (CCPA-deleted); NOT plaintext
- Stderr (on failure): exception message + stack trace; NEVER includes plaintext

**Invocation patterns**:
- **Operator**: by far the most common — operator with elevated SQL Server credential runs this to support an audit / compliance request
- **Automic**: NOT scheduled (no automation should decrypt PII on a schedule per D6 + P8)
- **Pipeline**: NEVER (per D6 — pipeline service account doesn't have decrypt permission)

**Idempotency** (per D26 append-only audit):
- Each invocation writes a new `PiiVaultAccessLog` row (intentional — every access is a separate audit event)
- Re-decrypting the same token N times produces N audit rows (NOT N=1 — multiple operator accesses are MULTIPLE audit events per D26)
- The "idempotency" claim here is at the SP level: SP-2's read-only decrypt produces the same plaintext deterministically — no behavioral nondeterminism

**Error modes** (per D68 + § 1.8):
- `TokenNotFound` (Round 3 § 2.2 — `PipelineFatalError`) → exit 2; stderr message names the token's hint (first 4 chars + masked tail); audit row NOT written (no token = no audit semantics)
- `DecryptDenied` from § 2.2 (token Status='deleted_per_request' or 'purged_for_retention' — SP-2 returns NULL plaintext) → NOT an exception per § 2.2; tool returns exit 0 with stdout `<NULL> (CCPA-deleted)` — audit row IS written
- `VaultUnavailable` (PipelineRetryableError) → exit 1
- Missing `--justification` (empty string) → arg-parse error → exit 2; SP-2 NOT NULL constraint would have rejected anyway

**Concurrency**:
- Single-process; serial token-by-token through SP-2
- `--workers` NOT supported (audit semantics require serial; rate-limiting is desirable)
- Multiple operator concurrent decrypts: serialized at the audit-log INSERT level per Round 3 § 2.2 (IDENTITY PK; no contention)

**CLI interface**:

```bash
# Single token (justification required)
python3 tools/decrypt_pii.py --token <token-hex> \
    --justification 'Audit ticket #12345 — operator review'

# Batch from file (one token per line)
python3 tools/decrypt_pii.py --token-file /path/to/tokens.txt \
    --justification 'CCPA right-to-know request #6789 — Q2 2026'

# JSON output for downstream consumption
python3 tools/decrypt_pii.py --token <token-hex> \
    --justification 'audit' --json
```

**Tool-specific arguments**:

| Argument | Type | Default | Semantics |
|---|---|---|---|
| `--token` | str (repeatable) | None | Token hex string (VARCHAR(40) per Round 3 § 2.2 + SP-2 `@Token VARCHAR(40)` parameter at `01_database_schema.md` L1416 per Pitfall #9 — canonical type is ASCII VARCHAR not NVARCHAR). Repeatable for small batches |
| `--token-file` | path | None | Path to file containing one token per line. Mutually exclusive with `--token` |
| `--justification` | str | None | REQUIRED. Free-text reason; written to `PiiVaultAccessLog.Justification` per SP-2 `@Justification NVARCHAR(MAX)` (L1417). Empty string rejected by arg-parse |
| `--request-id` | UUID | auto-generate | Maps to Round 3 § 2.2 `request_id` parameter / SP-2 `@RequestId UNIQUEIDENTIFIER` (L1415). Optional; ties multiple decrypts to one operator request for audit grouping |
| `--mask-output` | flag | False | Show plaintext only as last-4-chars + redaction prefix in stdout (still writes plaintext to caller's stdout pipe — operator should redirect stdout to a file if even masked display is too sensitive) |

**Stdout** (success): one line per token. Format: `<token-hint> -> <plaintext>` for normal decrypts; `<token-hint> -> <NULL> (CCPA-deleted)` for retention-purged tokens; `<token-hint> -> NOT_FOUND` for missing tokens. The `<token-hint>` is first 4 chars of the hex token + `<...>` + last 4 chars (e.g. `a3f1<...>9c2d`).

**Stdout** (`--json`): list of dicts `[{"token_hint": "...", "plaintext": "...", "status": "decrypted|ccpa_deleted|not_found", "request_id": "...", "audit_log_id": N}]` where `plaintext` is the actual decrypted string. JSON to stdout flows through unbuffered `print(json.dumps(...))` — operator responsible for redirecting to secure storage.

**Exit codes**:
- 0: all tokens processed successfully (including CCPA-deleted with NULL plaintext)
- 1: at least one token failed with retryable error; operator can re-run
- 2: fatal — at least one `TokenNotFound`, or vault unreachable, or missing justification

**Tier 0 smoke test** (per § 1.6): `tests/smoke/test_tools_decrypt_pii.py` — runs in <5s, NO real vault. Asserts: (a) module imports; (b) `--help` exits 0 + contains the word `justification`; (c) missing `--justification` raises arg-parse error → exit 2; (d) `--token <hex>` + `--justification 'audit'` with mocked `decrypt_token` returning plaintext `'foo'` → tool returns exit 0 + stdout contains `'foo'`; (e) mocked `decrypt_token` returning `None` → exit 0 + stdout contains `CCPA-deleted`; (f) mocked `decrypt_token` raising `TokenNotFound` → exit 2; (g) `--mask-output` masks plaintext to `<...>` form in stdout.

**Test surface (Round 5)**:
- Tier 1: justification required (missing → arg-parse error)
- Tier 1: per-token-status (decrypted, CCPA-deleted, not found) — each produces expected stdout + audit row
- Tier 1: `--token-file` reads file correctly; one-token-per-line; comment lines (`#`) skipped
- Tier 1: P5 verification — log lines from this tool (DEBUG / INFO / WARNING) NEVER contain plaintext; SensitiveDataFilter applied
- Tier 5 manual: quarterly audit drill — confirm `PiiVaultAccessLog` rows match expected operator usage

**Cross-doc references**: Round 3 § 2.2 + § 6.1 (SensitiveDataFilter); Round 1 SP-2 + PiiVaultAccessLog; D6, D26, D30, P5, P8; RB-4 (audit access runbook).

---

### § 3.5 `tools/detect_extraction_gaps.py`

**Purpose**: CLI shim for `tools/gap_detector.py` specified at Round 3 § 5.3. Detect missing business_date rows in `PipelineExtraction` per (source, large-table); produce `GapReport` per D22. **Round 3 specifies the module body; this round specifies the operator-facing arg parser + Automic invocation pattern.**

**Wraps**: Round 3 § 5.3 `detect_extraction_gaps(*, source_filter, as_of_date)` keyword-only signature (canonical per Round 3 § 5.3 L1199-1203), returning `list[GapReport]`.

**Consumes**:
- Decisions: D22 (hourly gap detector), D67, D74-D77 (proposed)
- Round 1: `PipelineExtraction`
- Round 2: `UdmTablesList.FirstLoadDate`, `LookbackDays`, `LastModifiedColumn` (decide expected extraction range)
- Round 3 § 5.3: `detect_extraction_gaps()` returning `list[GapReport(source_name, table_name, expected_range, missing_dates, recommended_action)]`
- Round 2 § 5.1: `JOB_GAP_DETECT` (hourly Automic job)

**Produces**:
- stdout: per-affected-table block listing `(source.table)`, expected range, missing dates list, recommended action (`'backfill'` / `'investigate-source'` / `'within-lookback-no-action'`)
- ONE `PipelineEventLog` event row per CLI invocation: `EventType='CLI_DETECT_EXTRACTION_GAPS'` (per D76 CLI naming convention). The wrapped Round 3 § 5.3 module separately writes `EventType='GAP_DETECT'` (per Round 3 § 5.3 narrative) when called — so a single CLI invocation produces two event rows: the CLI envelope event + the underlying module event. This preserves both D76 (CLI EventType naming) and Round 3 § 5.3's existing event-emit contract
- Alert dispatch via `tools/alert_dispatcher.py` (§ 3.11) IF any gap detected and `--alert` flag set (default ON when `--actor automic`). The ops-channel client itself (Slack / PagerDuty / etc.) is B82-tracked — see § 3.11 for the unscoped-Phase-0-deliverable framing

**Invocation patterns**:
- **Automic** (primary): `JOB_GAP_DETECT` hourly per Round 2 § 5.1; auto-alerts on any gap
- **Operator** (ad-hoc): "what gaps exist right now?" — read-only, no alerts (operator interactively reviews)
- **Pipeline**: rarely; `large_tables.py` orchestrator may call `detect_extraction_gaps()` directly at end of run

**Idempotency**: read-only; same as Round 3 § 5.3 — multi-call returns identical reports for unchanged historical data.

**Error modes** (per D68 + § 1.8):
- `GapDetectorTimeout` (Round 3 § 5.3 — `PipelineRetryableError` on > 60s query) → exit 1
- Connection failure → exit 1
- Config missing → exit 2

**Concurrency**:
- Single hourly run per server per Round 3 § 5.3
- No `sp_getapplock` (concurrent runs are safe; report is reproducible)
- `--workers` not supported (single-pass query against `PipelineExtraction`)

**CLI interface**:

```bash
# Hourly Automic job invocation
python3 tools/detect_extraction_gaps.py --actor automic --alert

# Operator ad-hoc, all sources, no alerts
python3 tools/detect_extraction_gaps.py

# Filter to one source
python3 tools/detect_extraction_gaps.py --source DNA
```

**Tool-specific arguments**:

| Argument | Type | Default | Semantics |
|---|---|---|---|
| `--as-of-date` | date | today | Maps to Round 3 § 5.3 `as_of_date`. Useful for backfill scenarios ("what would the gap report have said on 2026-04-15?") |
| `--alert` | flag | True when `--actor automic`, False otherwise | If any gap detected and flag set, call `tools/alert_dispatcher.py` (§ 3.11) to fire ops-channel alert |
| `--include-recommendation` | flag | True | Include `recommended_action` per gap in stdout. Default ON; `--no-include-recommendation` suppresses |

**Stdout** (success, no gaps): `No gaps detected (N tables checked).`

**Stdout** (success, gaps): per-table block:

```
DNA.ACCT
  Expected: 2026-02-09 .. 2026-05-08 (90 days)
  Missing : 2026-03-15, 2026-03-16 (2 days)
  Action  : backfill via tools/backfill.py --source DNA --table ACCT --from 2026-03-15 --to 2026-03-16
```

**Stdout** (`--json`): `[{"source_name": "...", "table_name": "...", "expected_range": [...], "missing_dates": [...], "recommended_action": "..."}]`.

**Exit codes**:
- 0: no gaps detected (clean state)
- 1: gaps detected (operator should review; Automic should alert) — distinct from 0 to make Automic notification simple (`if exit==1 then alert`)
- 2: fatal — config missing, connection unreachable, unexpected exception

**Tier 0 smoke test** (per § 1.6): `tests/smoke/test_tools_detect_extraction_gaps.py` — runs in <5s. Asserts: (a) module imports; (b) `--help` exits 0; (c) mocked `detect_extraction_gaps` returning empty list → exit 0 + stdout contains `No gaps`; (d) mocked returning one GapReport with missing_dates non-empty → exit 1 + stdout contains the source.table label; (e) `--alert` + `--actor automic` + non-empty gaps → mocked `alert_dispatcher` invoked once; (f) `--json` produces parseable JSON.

**Test surface (Round 5)**:
- Tier 1: no-gaps / single-gap / multiple-source gaps reporting
- Tier 1: `--as-of-date` historical view consistency
- Tier 1: `--alert` invocation gating
- Tier 3 integration: real `PipelineExtraction` with synthetic gap injected; verify report

**Cross-doc references**: Round 3 § 5.3; Round 1 PipelineExtraction; Round 2 § 5.1 `JOB_GAP_DETECT`; D22; G-series edge cases (`04_EDGE_CASES.md`); RB-9 (operations); § 3.11 below (alert_dispatcher).

---

### § 3.6 `tools/promote_test_to_prod.py`

**Purpose**: Failover acknowledgment per D29 (revised) + D33 (cooperative cancellation). When the prod server is unhealthy, the test server's pipeline can be promoted to take over a cycle (AM or PM). This tool acknowledges the failover within the gate-table contract (per Round 2 § 5.3.5) and writes the audit trail.

**Wraps**: Round 1 SP-4 `PipelineExecutionGate_AcquireTest` + SP-3 `PipelineExecutionGate_AcquireProd` (gate-acquire flow per Round 2 § 5.3.1-5.3.3); Round 3 § 6.3 `event_tracker.track()` for the cycle-cancellation audit row.

**Consumes**:
- Decisions: D27 (cross-server parity — test server must already match prod parity baseline), D29 revised (Automic-driven AM/PM coordination), D33 (cooperative cancellation), D67, D74-D77 (proposed)
- Round 1 SPs: SP-3 (`PipelineExecutionGate_AcquireProd`), SP-4 (`PipelineExecutionGate_AcquireTest`), SP-5 (`PipelineExecutionGate_RequestCancellation`), SP-6 (`PipelineExecutionGate_AcknowledgeCancellation`). SP-4's `@Action NVARCHAR(30) OUTPUT` parameter returns one of three canonical values per `01_database_schema.md` L1546: **`'EXIT_SUCCEEDED'`** (prod already handled this cycle), **`'EXIT_RUNNING_HEALTHY'`** (prod still running with recent heartbeat — test exits cleanly), **`'PROCEED_FAILOVER'`** (prod failed/timed-out/never-started — claim gate as test). Pitfall #9 verified against canonical DDL — earlier draft of this doc used `('exit', 'failover')` and collapsed three states to two; corrected at first-pass validation 2026-05-10
- Round 1: `PipelineExecutionGate` table — Status enum (`CK_PipelineExecutionGate_Status` per `01_database_schema.md` L328-330 — verified at Round 3); columns including `CycleType`, `CycleDate`, `ExecutingServer` (canonical per L310 — `NVARCHAR(20)`, constrained to `('production', 'test')` per L331-332; earlier draft of this doc used `ServerRole` — that column lives on `PipelineEventLog` L139, NOT on `PipelineExecutionGate` — Pitfall #9 cross-table column-name lift caught at first-pass validation 2026-05-10), `CancellationRequested`, `CancellationAcknowledgedAt`, `BatchId`
- Round 2: § 5.4 (failover behavior narrative AM/PM only per D29 revised + D33 — describes the WHEN; this tool implements the HOW). Earlier draft of this doc cited § 5.3.5 ("Per-AM/PM-cycle column matrix") which is structurally distinct from the failover narrative — corrected at cycle 8 validation per Pitfall #9 wrong-section-cite sub-class
- Round 3 § 6.3: `event_tracker.track()` for `EventType='CYCLE_CANCELLED'` / `EventType='CYCLE_FAILED_OVER'` audit rows

**Produces**:
- (`--apply`): SP-4 invocation; if SP-4 returns `@Action='PROCEED_FAILOVER'`, this tool's main path acknowledges it via SP-6 + writes `event_tracker.track(event_type='CYCLE_FAILED_OVER', ...)` audit row + flips the gate to test server's BatchId. If `@Action='EXIT_SUCCEEDED'` or `@Action='EXIT_RUNNING_HEALTHY'`, no failover is performed — these are the "prod was healthy, don't promote" outcomes
- (default dry-run): SP-4 invocation with `@AcknowledgmentOnly=1` parameter (NEW — proposed; not yet in Round 1 SP-4 signature; this tool documents the requirement which feeds into Round 1 schema-evolution governance Round 7 OR a B-number for Round 6 amendment). Returns the SP-4 verdict without modifying gate state
- ONE `PipelineEventLog` event row with `EventType='CLI_PROMOTE_TEST_TO_PROD'`; `Metadata` JSON includes the SP-4 verdict, cycle context, operator justification (per `--justification` mandatory)

**Invocation patterns**:
- **Operator** (primary): operator-initiated failover; mandatory `--justification` (audit trail); typically invoked from RB-7 DR drill or RB-9 operations response
- **Automic** (secondary): rare — Automic can detect prod heartbeat absence and self-trigger; mandatory `--actor automic --justification 'auto-detected prod heartbeat absence'`
- **Pipeline**: NEVER — pipeline running on test server doesn't promote itself; the orchestration layer (Automic) makes the decision

**Idempotency**:
- SP-4 with `@AcknowledgmentOnly=1` is read-only (proposed parameter)
- SP-4 / SP-6 in `--apply` mode: re-invocation on an already-acknowledged failover is a no-op (gate row's `CancellationAcknowledgedAt` not NULL on second call; SP raises a documented warning, NOT an exception)
- `event_tracker.track()` writes one event row per invocation — multiple promotions produce multiple audit rows (intentional per D26)

**Error modes**:
- `@Action='EXIT_SUCCEEDED'` (prod already completed this cycle) → exit 0 with stdout `prod already succeeded; no failover needed` — NOT an error, informational outcome. The cycle was a successful prod run; test was about to take over unnecessarily
- `@Action='EXIT_RUNNING_HEALTHY'` (prod still running with recent heartbeat) → exit 1 with stdout `prod is healthy and running; no failover needed`. Distinct from `EXIT_SUCCEEDED` (cycle done) — this is the "operator misread the heartbeat dashboard" case (per § 4.2 F (next)); informational, not an emergency
- `ParityFatalError` (PipelineFatalError per Round 3 § 3.2) — test server's parity check has fatal-tier drift; CANNOT promote until parity restored; exit 2
- Missing `--justification` → arg-parse error → exit 2

**Concurrency**:
- Single-process; gate-acquire SPs SP-3 / SP-4 use `sp_getapplock` with resource string `'pipeline_gate_' + @CycleType + '_' + CONVERT(VARCHAR(10), @CycleDate, 23)` per Round 1 canonical: SP-3 declares the resource at L1467-1468 + invokes lock at L1472-1476 (full EXEC stanza); SP-4 redeclares with the identical expression at L1552-1553 + invokes lock at L1560-1564. Both use `@LockMode = 'Exclusive'`, `@LockOwner = 'Session'`, `@LockTimeout = 5000`
- Concurrent invocations of this tool: serialized by `sp_getapplock` at the SP level; second invocation gets `GateNotAcquirable` after first completes (gate is now in promoted-to-test state)

**CLI interface**:

```bash
# Operator-initiated failover during morning cycle
python3 tools/promote_test_to_prod.py --cycle AM --cycle-date 2026-05-10 \
    --justification 'Prod server unreachable since 02:15; ops verified' --apply

# Dry-run: would this be acceptable RIGHT NOW?
python3 tools/promote_test_to_prod.py --cycle AM --cycle-date 2026-05-10 \
    --justification 'check failover preconditions' --dry-run
```

**Tool-specific arguments**:

| Argument | Type | Default | Semantics |
|---|---|---|---|
| `--cycle` | str | None | REQUIRED. One of `'AM'` / `'PM'` per canonical `CK_PipelineExecutionGate_CycleType CHECK (CycleType IN ('AM', 'PM'))` at `01_database_schema.md` L326-327 (verified at cycle 3 column-walk) |
| `--cycle-date` | date | today | Maps to `PipelineExecutionGate.CycleDate` |
| `--justification` | str | None | REQUIRED. Free-text audit reason; surfaces in `PipelineEventLog.Metadata.justification` and (via event_tracker) the audit row's standard fields |
| `--skip-parity-check` | flag | False | Override the test-server parity precheck. **DANGEROUS — operator MUST justify in `--justification`.** Logged at CRITICAL |

**Stdout** (success, `--apply`, `@Action='PROCEED_FAILOVER'`):

```
Failover acknowledgment: AM 2026-05-10
  Pre-check: test server parity verified ✓
  SP-4 verdict: PROCEED_FAILOVER (prod heartbeat absent > 30 minutes)
  SP-6 acknowledged at: 2026-05-10 02:45:13 UTC
  Test server now owns this cycle (ExecutingServer='test'). BatchId: 1042
  PipelineEventLog row: 88123 (EventType='CYCLE_FAILED_OVER')
```

**Stdout** (`--dry-run`):

```
Dry-run: failover acknowledgment would proceed
  Pre-check: test server parity verified ✓
  SP-4 verdict: PROCEED_FAILOVER (prod heartbeat absent > 30 minutes)
  Would acknowledge via SP-6. Re-run with --apply to commit.
```

**Stdout** (success, `@Action='EXIT_SUCCEEDED'`, no failover needed):

```
No failover needed — prod cycle already succeeded.
  SP-4 verdict: EXIT_SUCCEEDED (prod Status='SUCCEEDED' for AM 2026-05-10)
  Test server exits cleanly. No gate change.
```

**Stdout** (success, `@Action='EXIT_RUNNING_HEALTHY'`, no failover needed):

```
No failover needed — prod cycle is currently running with healthy heartbeat.
  SP-4 verdict: EXIT_RUNNING_HEALTHY (prod LastHeartbeatAt within heartbeat tolerance)
  Test server exits cleanly. Operator should re-check prod dashboard before next attempt.
```

**Stdout** (`--json`): `{"cycle": "AM", "cycle_date": "...", "verdict": "PROCEED_FAILOVER|EXIT_SUCCEEDED|EXIT_RUNNING_HEALTHY", "test_parity_status": "pass|warn|fail", "applied": true/false, "batch_id": N|null, "audit_event_id": N}`. `batch_id` populated on `PROCEED_FAILOVER` (the new BatchId test server acquired); null for `EXIT_*` verdicts (no gate state change).

**Exit codes**:
- 0: failover successfully acknowledged (or dry-run preview produced) OR `@Action='EXIT_SUCCEEDED'` (prod already done — clean informational outcome)
- 1: `@Action='EXIT_RUNNING_HEALTHY'` (prod is healthy and running; no failover needed — operator review, not page) — informational
- 2: fatal — parity check failed, gate not acquirable, missing justification, vault config error

**Tier 0 smoke test** (per § 1.6): `tests/smoke/test_tools_promote_test_to_prod.py` — runs in <5s. Asserts: (a) module imports; (b) `--help` exits 0; (c) missing `--cycle` / `--justification` → arg-parse error → exit 2; (d) mocked SP-4 returning `@Action='PROCEED_FAILOVER'` + mocked parity-pass → exit 0 with stdout containing `'PROCEED_FAILOVER'`; (e) mocked SP-4 returning `@Action='EXIT_SUCCEEDED'` → exit 0; (f) mocked SP-4 returning `@Action='EXIT_RUNNING_HEALTHY'` → exit 1; (g) mocked `ParityFatalError` from parity-precheck → exit 2; (h) `--skip-parity-check` allows proceeding past the parity-fail mock (with CRITICAL log emitted).

**Test surface (Round 5)**:
- Tier 1: per-verdict path (failover / no-failover-needed / parity-fail)
- Tier 1: `--skip-parity-check` requires `--justification` text containing rationale (Tier 1 can validate semantically via keyword check; Tier 5 manual review verifies appropriateness)
- Tier 3 integration: real `PipelineExecutionGate` table with synthetic missing-heartbeat row + real SP-3/4/5/6 invocation chain
- Tier 4 crash injection: kill the tool between SP-4 verdict and SP-6 acknowledgment — verify state is recoverable (next invocation finds gate in expected intermediate state)

**Cross-doc references**: Round 1 SP-3, SP-4, SP-5, SP-6 + `PipelineExecutionGate` DDL; Round 2 § 5.3.5 (failover acknowledgment narrative); Round 3 § 3.2 (parity verifier precheck) + § 6.3 (event_tracker audit); D27, D29 revised, D33; RB-7 (DR drill), RB-9 (operations response).

---

### § 3.7 `tools/verify_server_parity.py`

**Purpose**: CLI shim for the `verify_server_parity()` function specified at Round 3 § 3.2. Operator-facing arg parser + exit-code mapping per D65 severity tiers. Round 3 freezes the module body; Round 4 freezes the operator surface.

**Wraps**: Round 3 § 3.2 `verify_server_parity(baseline_path, server_name, fail_on_warning)` returning `ParityReport` (canonical signature per `02_configuration.md` L957-961; earlier draft of this doc dropped the `server_name` parameter — Pitfall #9 caught at first-pass validation 2026-05-10).

**Consumes**:
- Decisions: D27 (parity contract), D65 (drift severity classification — fatal / warning / informational / match), D67, D74-D77 (proposed)
- Round 2: `02_configuration.md` § 4.1 (baseline JSON schema), § 4.2 (verifier interface canonical — Round 4 does NOT re-specify the interface; it cites Round 2 § 4.2 as the source of truth per Pitfall #9), § 4.3 (severity classification)
- Round 3 § 3.2: `verify_server_parity()` returning `ParityReport(server_name, baseline_name, baseline_pinned_at, checks, fatal_count, warning_count, informational_count, match_count, overall)` per `02_configuration.md` L946-955 canonical dataclass (earlier draft cited invented fields `generated_at` + `baseline_sha256` — Pitfall #9 fifth sub-class caught at first-pass validation 2026-05-10)

**Produces**:
- stdout: per-check status table (`<severity_emoji> <check_name> : <actual> vs <expected>`); summary line `Overall: <pass|warn|fail>` per Round 2 § 4.2 `ParityReport.overall`
- ONE `PARITY_VERIFY` event row in `PipelineEventLog` per Round 3 § 3.2 (event_tracker writes); `Metadata` JSON contains the full report
- On fatal: alert via `tools/alert_dispatcher.py` (§ 3.11) when `--alert` flag set; default ON when `--actor automic` or `--actor pipeline`

**Invocation patterns**:
- **Automic** (primary): `JOB_PARITY_VERIFY` daily AM/PM pre-cycle per Round 2 § 5.1 — Automic invokes with `--actor automic --alert`; exit code drives Automic decision (0 = proceed; 1 = warn but proceed; 2 = abort cycle)
- **Pipeline** (secondary): pipeline orchestrator (`main_*.py`) calls this at process start as a hard precondition; exit 2 = `sys.exit(1)` for pipeline (per Round 3 § 3.2 docstring)
- **Operator** (ad-hoc): "is this server parity-clean right now?" — read-only, no side effects beyond audit row

**Idempotency**: read-only on filesystem; INSERT-only on `PipelineEventLog`. Per Round 3 § 3.2 — "re-invocation produces a NEW report row (intentional — each pipeline startup is its own audit moment)".

**Error modes** (per D68 + § 1.8):
- `ParityFatalError` (Round 3 § 3.2 — `PipelineFatalError`) → exit 2; alert if `--alert`
- `ParityBaselineMissing` → exit 2; stderr message "baseline JSON missing or malformed"
- `ParityProbeError` (system probe failed) → exit 2
- Warning-tier drift WITHOUT fatal → exit 1 (operator review; not page-able); alert if `--alert`
- All match → exit 0

**Concurrency**: synchronous prerequisite at process start per Round 3 § 3.2; single-threaded.

**CLI interface**:

```bash
# Automic-invoked pre-cycle parity verify
python3 tools/verify_server_parity.py --actor automic --alert

# Operator ad-hoc
python3 tools/verify_server_parity.py

# Verify against an alternate baseline (e.g. pre-deployment check)
python3 tools/verify_server_parity.py --baseline-path /tmp/new_baseline.json
```

**Tool-specific arguments**:

| Argument | Type | Default | Semantics |
|---|---|---|---|
| `--baseline-path` | path | `/etc/pipeline/parity_baseline.json` (per Round 2 § 4.1) | Override the baseline JSON path. Useful for pre-deployment baseline validation |
| `--fail-on-warning` | flag | False | Map warning-tier to fatal — useful for strict pre-deployment validation. Default OFF (warning is informational + alert-only) |
| `--alert` | flag | True when `--actor automic` or `--actor pipeline`, False otherwise | Fire ops-channel alert via `tools/alert_dispatcher.py` on warning or fatal drift |

**Stdout** (success, all match): `Parity: all N checks pass.` (where N is the actual check count from the baseline JSON; exemplar baseline as of Round 2 § 4.1 has ~14 checks but is configurable)

**Stdout** (success, warnings or failures): per-check block + summary:

```
Parity report — server: udm-prod-1 — baseline: /etc/pipeline/parity_baseline.json
  ✓ python_version           : 3.12.11
  ✓ malloc_arena_max         : 2
  ⚠ library_sha:polars       : 1.5.0 (baseline: 1.4.0)  [WARNING tier per D65]
  ✗ envelope_sha256          : <actual> (baseline: <expected>)  [FATAL tier per D65]
Overall: fail
1 fatal, 1 warning, 12 match
```

**Stdout** (`--json`): canonical `ParityReport` dataclass serialized verbatim per `02_configuration.md` L946-955 — `{"server_name": "...", "baseline_name": "...", "baseline_pinned_at": "...", "checks": [{"key": "...", "expected": "...", "actual": "...", "severity": "fatal|warning|informational|match", "exception_match": null|true|false, "note": "..."}], "fatal_count": N, "warning_count": N, "informational_count": N, "match_count": N, "overall": "pass|warn|fail"}`. No invented fields; no canonical field dropped. `ParityCheck` items use canonical `key` field name (NOT `name`) per `02_configuration.md` ParityCheck dataclass.

**Exit codes** (per D65 severity mapping — three tiers in canonical D65 map to three exit codes):
- 0: all `match` OR only `informational`-tier drift (per § 1.1 "0 = always normal"; informational drift is logged + alerted but is NOT an expected failure — pipeline proceeds without operator intervention)
- 1: `warning`-tier drift (per § 1.1 "expected operational failure"; pipeline can proceed; operator review required)
- 2: `fatal`-tier drift OR `ParityBaselineMissing` / `ParityProbeError` (per § 1.1 "fatal"; pipeline MUST NOT proceed)

**Tier 0 smoke test** (per § 1.6): `tests/smoke/test_tools_verify_server_parity.py` — runs in <5s, mocked subprocess probes + mocked baseline JSON. Asserts: (a) module imports; (b) `--help` exits 0; (c) mocked `verify_server_parity` returning `overall='pass'` → exit 0; (d) mocked returning `overall='warn'` → exit 1; (e) mocked returning `overall='fail'` → exit 2; (f) mocked `ParityBaselineMissing` → exit 2; (g) `--alert` + `fatal` → mocked `alert_dispatcher` invoked once; (h) `--fail-on-warning` + `overall='warn'` → exit 2 (mapped up to fatal).

**Test surface (Round 5)**:
- Tier 1: per-severity tier exit-code mapping
- Tier 1: per-check coverage (Python version, library SHA, env var, filesystem layout, systemd unit, TPM2 PCR, envelope SHA)
- Tier 1: `documented_exceptions` honored (`expires_at > today` = accepted; expired = rejected per Round 2 § 4.3 + F22 edge case)
- Tier 3 integration: Docker fixture with intentional drifts at each severity tier

**Cross-doc references**: Round 3 § 3.2; Round 2 § 4 (full spec); D27, D65; B12 (Phase 0 deliv 0.11 implementation — Round 6 deploys this CLI alongside the module); F22 + F23 (parity edge cases); R08 (parity drift risk).

---

### § 3.8 `tools/enforce_retention.py`

**Purpose**: Invoke Round 1 SP-10 `EnforceRetention` (and any future retention-related SPs from B01) per D30. Sweeps `PiiVault` rows where `RetentionExpiresAt < SYSUTCDATETIME() AND LegalHold = 0 AND Status = 'active'` (per canonical SP-10 body `01_database_schema.md` L1965-1968) — flips qualifying rows to `Status='purged_for_retention'`. Driven by `JOB_RETENTION_MONTHLY` per Round 2 § 5.1.

**Wraps**: Round 1 SP-10 `EnforceRetention(@DryRun BIT = 1)` per canonical signature at `01_database_schema.md` L1953-1954 (verified at first-pass validation 2026-05-10 against canonical — earlier draft of this doc invented `@RetentionDate` and `@ActorName` parameters that don't exist; Pitfall #9 invented-parameter drift caught + corrected. The retention cutoff is INTERNAL to SP-10 via the `RetentionExpiresAt` column on `PiiVault`, NOT an SP parameter); Round 3 § 2.3 `vault_client.call_vault_sp()` for the SP invocation; Round 3 § 6.3 `event_tracker.track()` for the audit row.

**Consumes**:
- Decisions: D6 (vault), D26 (append-only audit), D30 (7-year retention + legal-hold override), CCPA / CPRA alignment, D67, D74-D77 (proposed)
- Round 1 SP-10 `EnforceRetention(@DryRun BIT = 1)` — single parameter; cutoff is column-driven (per `PiiVault.RetentionExpiresAt`), not parameter-driven; legal-hold honored via `PiiVault.LegalHold = 0` predicate in SP body
- Round 1: `PiiVault.Status` enum transitions (`active` → `purged_for_retention` per D30); `PiiVault.RetentionExpiresAt` column drives the cutoff; `PiiVault.LegalHold` BIT excludes hold rows; `PiiTokenProvenance` cascade (provenance follows token Status); `OrphanedTokenLog` (B01-tracked; wired into SP-10 per B01)
- Round 2 § 5.1: `JOB_RETENTION_MONTHLY` (the canonical Automic invocation)
- Round 3 § 2.3: `vault_client.call_vault_sp(sp_name='EnforceRetention', sp_args={'DryRun': 0 or 1})`

**Produces**:
- stdout: per-category retention report (`PiiVault rows purged: N`, `PiiTokenProvenance rows reflected: M`, `OrphanedTokenLog rows created: Q`); summary line. Note: `PipelineLog` retention is NOT in SP-10's scope — it's handled by § 3.10 `log_retention_cleanup` (separate tool, separate cadence, separate retention policy per CLAUDE.md)
- (`--apply`): SP-10 invocation with `@DryRun=0`; per-row UPDATEs to `PiiVault.Status='purged_for_retention'` where `RetentionExpiresAt < SYSUTCDATETIME() AND LegalHold = 0 AND Status = 'active'`; INSERTs to `OrphanedTokenLog` per B01
- (default dry-run): SP-10 invocation with `@DryRun=1`; SP-10's body returns the `WouldBeFlipped` count (per L1964) without modifying
- ONE `PipelineEventLog` event row (`EventType='CLI_ENFORCE_RETENTION'`); `Metadata` JSON includes the per-category counts + dry-run flag + actor (the actor surfaces via PipelineEventLog audit row metadata, not via an SP parameter)

**Invocation patterns**:
- **Automic** (primary): `JOB_RETENTION_MONTHLY` at month-end per Round 2 § 5.1 with `--apply`
- **Operator** (occasional): ad-hoc dry-run to preview "what would the next month-end purge?"; pre-CCPA-deletion review
- **Pipeline**: NEVER (retention is its own scheduled concern, not pipeline-step)

**Idempotency** (per D15 + D26):
- SP-10's `@DryRun=1` is read-only
- SP-10's `@DryRun=0` is idempotent at the row level — `PiiVault.Status` flip from `purged_for_retention` → `purged_for_retention` is a no-op
- Multi-invocation in the same month produces multiple audit rows (intentional) but identical row-state outcome

**Error modes** (per D68):
- `VaultUnavailable` (Round 3 § 2.3 via `vault_client.call_vault_sp`) → exit 1 (retryable)
- `VaultConfigError` (Round 3 § 2.3 — missing/unreachable vault DB env keys at startup) → exit 2
- Legal-hold rows are silently skipped at the row level (SP-10 body's WHERE clause includes `LegalHold = 0` per `01_database_schema.md` L1967 — rows with `PiiVault.LegalHold = 1` are filtered out, NOT raised as an exception). Operator confirms via row-count delta (rows-eligible vs rows-purged). If the operator EXPECTS specific tokens to purge but they don't, they consult `RB-11` (legal-hold runbook) to investigate per-row LegalHold flags

**Concurrency**:
- `sp_getapplock @Resource = N'job_RETENTION_MONTHLY_<month-start>', @LockMode = 'Exclusive', @LockOwner = 'Session', @LockTimeout = 5000` per Round 2 § 5.1 L1047 + § 5.3.6 L1181 (same canonical idiom as `orchestration/table_lock.py` per W-8 — Session-owned lock auto-release on disconnect). Resource string format is `job_<JOB_NAME>_<cycle_date>` per L1181; `<month-start>` is the canonical `<cycle_date>` for monthly jobs
- `--workers` not supported (retention is a single SP execution; serial is correct)

**CLI interface**:

```bash
# Automic-invoked monthly retention sweep (apply mode)
python3 tools/enforce_retention.py --actor automic --apply

# Operator dry-run
python3 tools/enforce_retention.py

# Apply with verbose progress
python3 tools/enforce_retention.py --apply -v
```

**Tool-specific arguments**:

| Argument | Type | Default | Semantics |
|---|---|---|---|
| `--apply` | flag | False | Map to SP-10 `@DryRun=0` (per canonical signature L1954). Default off → `@DryRun=1` (read-only count) per § 1.2 dry-run-default rule. The cutoff date is NOT a CLI argument — SP-10's body uses `PiiVault.RetentionExpiresAt < SYSUTCDATETIME()` as the predicate (operator can pre-set rows' retention expiry via SP-1 + retention-policy logic at tokenization time). If operator wants to force-purge an earlier cutoff, they must (a) UPDATE the per-row `RetentionExpiresAt` first (with audit), then (b) run this CLI — covered by RB-10/RB-11 narratives |

**Schema-evolution notes** (per Pitfall #9 + § 5.2 close-out tasks):
- **B-number proposed** (B93 — see § 5.2): SP-10 evolution to accept `@CutoffOverride DATETIME2(3) = NULL` parameter for operator-driven override-without-row-mutation. Tracked as Round 7 schema-evolution governance request (same pattern as SP-4 `@AcknowledgmentOnly` per B79 in § 3.6). Round 4 CLI currently has no `--retention-date` arg because canonical SP-10 doesn't accept one — invented parameters are exactly the Pitfall #9 failure mode
- **B-number proposed** (B94 — see § 5.2): SP-10 evolution to accept `@CategoryFilter NVARCHAR(MAX) = 'all'` parameter so the `--categories` operator-level filter has a corresponding SP-level filter. Currently dropped from CLI surface (was invented); tracked for Round 7 governance

**Stdout** (success, dry-run, SP-10 `@DryRun=1`):

```
Retention enforcement — dry run
  Cutoff source: PiiVault.RetentionExpiresAt column (per-row; D30 retention policy)
  PiiVault rows eligible for purge        : 124,567 (RetentionExpiresAt < now AND LegalHold = 0 AND Status='active')
  PiiTokenProvenance rows reflecting      : 891,234
  OrphanedTokenLog rows that would create: 0
Would flip 124,567 PiiVault rows to Status='purged_for_retention'. Re-run with --apply to commit.
```

**Stdout** (success, `--apply`): same shape with `purged` instead of `eligible for purge`; final line `Purge complete. Audit event: PipelineEventLog row 88234.`

**Stdout** (`--json`): `{"dry_run": true|false, "counts": {"vault": N, "provenance": M, "orphanedtokenlog": Q}, "audit_event_id": N}`. Note: no `retention_date` key — cutoff is per-row via `RetentionExpiresAt`, not a single CLI parameter.

**Exit codes**:
- 0: retention enforcement completed (or dry-run preview); includes the case where 0 rows qualified (legal-hold rows silently filtered + no expired-retention rows — operationally normal)
- 1: vault connection drop mid-statement OR retryable error during SP-10 invocation; operator can re-run (SP-10 is a single-statement transactional UPDATE — partial-row-state cannot occur; either the whole UPDATE commits or none of it does)
- 2: fatal — `VaultConfigError` (env keys missing/unreachable at startup per Round 3 § 2.3) or unexpected exception. **NOT a legal-hold-conflict exit code** — SP-10 silently skips `LegalHold = 1` rows per the canonical body's WHERE clause `LegalHold = 0` filter at L1967; no exception is raised on legal-hold encounter

**Tier 0 smoke test** (per § 1.6): `tests/smoke/test_tools_enforce_retention.py` — runs in <5s, mocked SP-10 cursor. Asserts: (a) module imports; (b) `--help` exits 0; (c) `python3 tools/enforce_retention.py` (no args = dry-run default per § 1.2) invokable; (d) mocked SP-10 returning `WouldBeFlipped` count → tool returns exit 0 + stdout matches count; (e) `--apply` calls SP-10 with `@DryRun=0`; (f) mocked SP-10 returning a `WouldBeFlipped` count of 0 (all rows filtered by `LegalHold = 0` predicate OR by `RetentionExpiresAt`) → tool returns exit 0 (legal-hold is silently filtered, NOT raised); (g) mocked `VaultConfigError` raised → exit 2; (h) confirms NO invented args (`--retention-date`, `--actor-name`, `--categories`) are accepted — arg-parse rejects them (forward-incompat guard against re-introducing the Pitfall #9 invented-parameter drift).

**Test surface (Round 5)**:
- Tier 1: dry-run vs apply behavior; LegalHold respect (rows with LegalHold=1 NOT purged)
- Tier 1: SP-10 returns the canonical `WouldBeFlipped` count on `@DryRun=1`; tool stdout reflects it accurately
- Tier 3 integration: real SP-10 against fixture vault with synthetic rows having `RetentionExpiresAt < now`

**Cross-doc references**: Round 1 SP-10; Round 3 § 2.3; Round 2 § 5.1 `JOB_RETENTION_MONTHLY`; D6, D26, D30; B01 (OrphanedTokenLog wiring — Round 1 follow-up); RB-10 (CCPA flow); RB-11 (legal hold).

---

### § 3.9 `tools/process_ccpa_deletion.py`

**Purpose**: Invoke the CCPA deletion SP (currently B01-tracked; not yet authored — Round 1 follow-up) per D30 + RB-10. Operator-driven, NOT scheduled. Mandatory `--justification` + `--request-id` for audit. Marks specific tokens (by token-list OR by data-subject identity criteria) as `Status='deleted_per_request'`.

**Wraps**: (anticipated, NOT YET AUTHORED) Round 1 CCPA deletion SP per B01 — SP signature is **deferred to B01 author**; this CLI spec does NOT pre-invent the parameter list (per § 1.10 Pitfall #9 "no invented parameter names" rule). When B01 lands, this section will be updated to cite the canonical signature. Until then, `vault_client.call_vault_sp()` (Round 3 § 2.3) is the abstract invocation surface; concrete `sp_name` + `sp_args` are pending B01.

**Consumes**:
- Decisions: D6, D26, D30 (CCPA right-to-deletion), D67, D74-D77 (proposed)
- Round 1: (anticipated, NOT YET AUTHORED) CCPA deletion SP per B01; `PiiVault.Status='deleted_per_request'` enum value (canonical Status values per `01_database_schema.md` per Round 1 v3 schema follow-ups — exact existence of `'deleted_per_request'` as a CHECK-constrained value is itself a B01 dependency); `CcpaDeletionLog` table (per Round 1 schema)
- Round 3 § 2.3: `vault_client.call_vault_sp()`

**Produces**:
- stdout: per-token / per-subject deletion report; final summary
- (`--apply`): SP invocation; `PiiVault.Status` flips to `deleted_per_request`; INSERTs to `CcpaDeletionLog`
- ONE `PipelineEventLog` event row (`EventType='CLI_PROCESS_CCPA_DELETION'`)
- Optional: alert via `tools/alert_dispatcher.py` to compliance officer

**Invocation patterns**:
- **Operator** (sole pattern): CCPA / CPRA / GDPR request handling. Required `--justification` includes the legal request reference
- **Automic / Pipeline**: NEVER (per D6 + D30 — only operator-authority paths can trigger deletion)

**Idempotency**:
- Re-deletion of an already-deleted token is a no-op at the row level
- `CcpaDeletionLog` is append-only — multi-invocation produces multiple audit rows (intentional per D26)

**Error modes**:
- `TokenNotFound` (per Round 3 § 2.3 vault_client error translation) → exit 1 (specific token not found; operator may have a stale list)
- `DeletionAlreadyApplied` (SP raises informational warning, not exception, on idempotent re-call) → exit 0 with stdout noting "already deleted"
- `LegalHoldConflict` — CCPA deletion attempted on a token that is under legal hold. Two distinct hold mechanisms apply per Round 1 + Round 2 design: **(a)** `PiiVault.LegalHold = 1` (per-row hold; canonical column at `01_database_schema.md` L1965 + filter at L1967) — CCPA SP MUST check this per-row and refuse deletion on `LegalHold=1` rows; **(b)** `UdmTablesList.LegalHoldOnly = 1` (table-level hold per D63 Round 2 § 1.2.6) — applies to retention/CCPA flows for any token sourced from a hold-flagged table. Anticipated CCPA SP (per B01) should check BOTH and raise `LegalHoldConflict` on either match → exit 2; operator must escalate to legal first

**Concurrency**: single SP invocation; `sp_getapplock` on `(subject_id, request_id)` prevents double-processing of a single request.

**CLI interface**:

```bash
# Delete by specific token list (file with one token per line)
python3 tools/process_ccpa_deletion.py --token-file /tmp/request-12345-tokens.txt \
    --request-id 12345 \
    --justification 'CCPA right-to-deletion #12345 — verified by privacy officer' \
    --apply

# Delete by subject identity (vault SP queries for the subject's tokens)
python3 tools/process_ccpa_deletion.py --subject-id SSN:123-45-6789 \
    --request-id 12345 \
    --justification 'CCPA #12345' \
    --apply

# Dry-run
python3 tools/process_ccpa_deletion.py --token-file /tmp/request-12345-tokens.txt \
    --request-id 12345 \
    --justification 'CCPA #12345 — preview before commit'
```

**Tool-specific arguments**:

| Argument | Type | Default | Semantics |
|---|---|---|---|
| `--token-file` | path | None | Path to file with tokens (one per line). Mutually exclusive with `--subject-id` |
| `--subject-id` | str | None | Subject identity (e.g. `SSN:<hashed>` or operator-supplied identifier). SP looks up the subject's tokens. Mutually exclusive with `--token-file` |
| `--request-id` | int / str | None | REQUIRED. Ties this deletion to a specific legal request. Maps to SP `@RequestId` |
| `--justification` | str | None | REQUIRED. Free-text — legal request reference + privacy-officer verification |

**Stdout** (success, `--apply`):

```
CCPA deletion — request 12345
  Tokens deleted              : 47
  Already deleted (no-op)      : 3
  Tokens not found             : 0
  Legal-hold conflicts         : 0
  CcpaDeletionLog rows written : 47
  PipelineEventLog row         : 88345
```

**Stdout** (`--json`): `{"request_id": "...", "subject_id": "...", "deleted": N, "already_deleted": M, "not_found": K, "legal_hold_conflicts": Q, "audit_event_id": N}`.

**Exit codes**:
- 0: deletion completed (including legal idempotent no-ops)
- 1: some tokens were not found (operator may have a stale or partial list)
- 2: fatal — legal-hold conflict, missing required args, vault unreachable

**Tier 0 smoke test** (per § 1.6): `tests/smoke/test_tools_process_ccpa_deletion.py` — runs in <5s, mocked SP. Asserts: (a) module imports; (b) `--help` exits 0; (c) missing `--request-id` or `--justification` → arg-parse error → exit 2; (d) `--token-file` + `--subject-id` together → arg-parse error (mutual exclusion); (e) mocked SP returning deletion counts → tool exit 0; (f) mocked SP raising `LegalHoldConflict` → exit 2.

**Test surface (Round 5)**:
- Tier 1: per-error path (token-not-found, already-deleted, legal-hold-conflict)
- Tier 5 manual quarterly audit drill: confirm `CcpaDeletionLog` rows match expected operator interactions

**Cross-doc references**: Round 3 § 2.3; Round 2 § 1.2.6 (LegalHoldOnly); D6, D26, D30; B01 (SP-10 retention + CCPA SP wiring — Round 1 follow-up); RB-10 (CCPA flow); RB-11 (legal hold).

---

### § 3.10 `tools/log_retention_cleanup.py`

**Purpose**: Purge old `PipelineLog` rows per the retention policy documented in CLAUDE.md (`30 days of DEBUG/INFO, 90 days of WARNING+, indefinite for ERROR/CRITICAL`). Independent of `enforce_retention.py` (§ 3.8) which handles vault / provenance / CCPA categories. This tool is `PipelineLog`-specific because log purge cadence differs from vault retention cadence.

**Wraps**: Direct SQL invocations against `General.ops.PipelineLog` via `cursor_for('General')`; no Round 3 module wrap (lightweight enough that a dedicated module isn't needed — Round 6 deployment may choose to extract a `log_retention.py` module per a BACKLOG candidate).

**Consumes**:
- Decisions: D26 (append-only — but log retention is a deliberate exception per CLAUDE.md retention policy; rows older than 30/90 days are deleted, ERRORs preserved indefinitely), D31 (PowerBI consumes PipelineLog — purge does not affect ERROR/CRITICAL which power dashboards), D67, D74-D77 (proposed)
- Round 1: `PipelineLog` (canonical columns + `LogLevel NVARCHAR(10)` per L202; `CK_PipelineLog_LogLevel CHECK LogLevel IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')` per L215-216 — verified at cycle 3 column-walk)
- CLAUDE.md retention policy section (`Log retention policy: Keep 30 days of DEBUG/INFO, 90 days of WARNING+, indefinite for ERROR/CRITICAL.`)

**Produces**:
- stdout: per-level row counts purged + remaining; total purged
- (`--apply`): `DELETE FROM General.ops.PipelineLog WHERE LogLevel IN ('DEBUG','INFO') AND CreatedAt < @cutoff_30_days` + `DELETE FROM General.ops.PipelineLog WHERE LogLevel = 'WARNING' AND CreatedAt < @cutoff_90_days`. ERROR/CRITICAL never deleted by this tool
- ONE `PipelineEventLog` event row (`EventType='CLI_LOG_RETENTION_CLEANUP'`); `Metadata` includes per-level counts

**Invocation patterns**:
- **Automic** (primary): `JOB_LOG_CLEANUP` (currently not in Round 2 § 5.1 frozen-8 inventory — BACKLOG candidate for Round 6 deployment to amend the job set; daily or weekly is plausible cadence)
- **Operator** (occasional): "PipelineLog is too big; what would the purge clean?" dry-run review
- **Pipeline**: post-pipeline-step inline call is plausible but inefficient (better via Automic daily)

**Idempotency**:
- Re-invocation produces zero rows purged (already purged; nothing < cutoff)
- DELETE is atomic; partial-purge crash leaves a deterministic state (next run completes the purge)

**Error modes** (per D68 + § 1.8):
- Connection failure → exit 1
- Lock timeout on `PipelineLog` (Power BI dashboard query holding read lock) → exit 1 with retry-after-N-minutes recommendation in stderr
- Config missing → exit 2

**Concurrency**:
- `sp_getapplock` on `('log_retention_cleanup',)` ensures one cleanup at a time
- `--workers` not supported (single batch DELETE; serial is correct)
- DELETE batch size capped at 50k rows per batch (Polars+SQL Server lock-escalation concern — B-2 lessons; mirrors CLAUDE.md gotcha about SCD2_UPDATE_BATCH_SIZE)

**CLI interface**:

```bash
# Daily Automic cleanup
python3 tools/log_retention_cleanup.py --actor automic --apply

# Operator dry-run
python3 tools/log_retention_cleanup.py

# Override retention windows (testing only)
python3 tools/log_retention_cleanup.py --debug-info-days 7 --warning-days 30 --apply
```

**Tool-specific arguments**:

| Argument | Type | Default | Semantics |
|---|---|---|---|
| `--debug-info-days` | int | 30 (CLAUDE.md policy) | Days to retain DEBUG + INFO. Override for testing or policy change |
| `--warning-days` | int | 90 (CLAUDE.md policy) | Days to retain WARNING. ERROR / CRITICAL never purged by this tool |
| `--batch-size` | int | 50000 | Per-batch DELETE row count cap. Lower to avoid lock escalation (B-2 lesson — 50k is conservative) |

**Stdout** (success, dry-run):

```
PipelineLog retention cleanup — dry run
  DEBUG  rows older than 30 days : 4,521,234 (eligible to purge)
  INFO   rows older than 30 days : 1,235,891 (eligible to purge)
  WARNING rows older than 90 days: 18,234 (eligible to purge)
  ERROR  rows                    : 12,456 (retained — indefinite per policy)
  CRITICAL rows                  : 234 (retained — indefinite per policy)
Would purge 5,775,359 rows. Re-run with --apply to commit.
```

**Stdout** (success, apply): same with `purged` instead of `eligible to purge`; final line `Cleanup complete. Audit event: PipelineEventLog row 88456.`

**Stdout** (`--json`): `{"dry_run": true|false, "purged": {"DEBUG": N, "INFO": M, "WARNING": K}, "retained": {"ERROR": N, "CRITICAL": M}, "audit_event_id": N}`.

**Exit codes**:
- 0: cleanup completed (or dry-run preview produced)
- 1: lock contention / partial-batch error; operator can re-run later
- 2: fatal — config / connection / unexpected

**Tier 0 smoke test** (per § 1.6): `tests/smoke/test_tools_log_retention_cleanup.py` — runs in <5s, mocked cursor. Asserts: (a) module imports; (b) `--help` exits 0; (c) `--dry-run` does NOT call DELETE; (d) `--apply` invokes per-level DELETE statements (verified by mock execute count); (e) ERROR / CRITICAL never appears in DELETE WHERE clause; (f) `--batch-size 10000` reflected in the DELETE statement.

**Test surface (Round 5)**:
- Tier 1: per-level retention rule (DEBUG/INFO 30d; WARNING 90d; ERROR/CRITICAL never purged)
- Tier 1: batch-size honored
- Tier 1: lock timeout → exit 1
- Tier 3 integration: real `PipelineLog` with synthetic old + new rows; verify only-old purged

**Cross-doc references**: Round 1 PipelineLog DDL; CLAUDE.md "Log retention policy"; D26, D31; B-2 (lock escalation lessons).

---

### § 3.11 `tools/alert_dispatcher.py`

**Purpose**: Operator notification fanout. Centralizes alert emission so other tools (gap_detector § 3.5, verify_server_parity § 3.7, retention enforcement § 3.8 in fatal cases) call this one CLI rather than implementing alert plumbing themselves. **Note**: the underlying ops-channel routing (Slack / PagerDuty / email / SMTP) is currently UNSCOPED in Phase 0 — canonical 02_PHASES.md L48 defines deliv 0.10 as "2x/day pipeline schedule windows agreed", NOT ops-channel routing. B82 tracks proposing a NEW Phase 0 deliverable for the ops-channel client + implementing it at Round 6 deployment. Round 4 freezes the CLI contract; Round 6 implements the client.

**Wraps**: ops-channel client (NOT YET IMPLEMENTED — module body deferred to Round 6 deployment per B82 dependency; this tool spec freezes the CLI contract that Round 6 implements against).

**Consumes**:
- Decisions: D67, D74-D77 (proposed). **Dependency**: B82 (proposed new Phase 0 deliverable for ops-channel routing — Slack / PagerDuty / email / SMTP); B-number tracked under § 5.2, not a decision per se
- Configuration: `.env` keys `OPS_CHANNEL_*` — NEW proposed sub-section under Round 2 § 2.1 (canonical Round 2 § 2.1 currently has sub-sections § 2.1.1 through § 2.1.8 per `02_configuration.md`; § 2.1.10 does NOT exist — earlier draft of this doc invented that section number; corrected at cycle 8 validation per Pitfall #9 invented-section-number sub-class). Round 2 amendment tracked via B82 (ops-channel client deliverable)
- Round 3 § 6.1: `SensitiveDataFilter` (CRITICAL — alerts are an external channel; plaintext leak is a worse outcome than internal log)

**Produces**:
- stdout: per-channel dispatch status (e.g. `slack: ok`, `pagerduty: ok`, `email: skipped (severity below threshold)`)
- ONE `PipelineEventLog` event row (`EventType='CLI_ALERT_DISPATCH'`); `Metadata` includes severity, channels-attempted, channels-succeeded, alert-body-hash (NOT body content if it contains anything sensitive)

**Invocation patterns**:
- **Tool-to-tool** (primary): other Round 4 tools (gap_detector, verify_server_parity, retention) call this when they need to fan out an alert. They populate `--severity`, `--source-tool`, `--message`, `--details-json`
- **Operator** (occasional): manually test an alert channel; verify routing works
- **Automic**: rare — Automic itself has separate alerting; this CLI is for pipeline-content alerts (data quality, parity drift, etc.)

**Idempotency**:
- Each invocation is a separate notification (operator typically DOES want notification of the second occurrence of a problem)
- `--dedupe-key` argument can be set to a stable identifier — channels with dedupe support (PagerDuty incident-key) collapse repeat alerts; without it, alerts fan out every time

**Error modes**:
- Channel auth failure → log at WARNING; continue to other channels; tool exits 0 if at least one channel succeeded, 1 if all failed
- `--severity fatal` + zero channels available → exit 2 (the alert is high-priority and the channel is broken; this is itself an alertable event but it'd be circular — escalate to log-only audit)
- Missing required args → arg-parse error → exit 2

**Concurrency**: stateless; multi-call safe; channels themselves handle their own rate-limiting.

**CLI interface**:

```bash
# Tool-to-tool invocation example (from gap_detector finding gaps)
python3 tools/alert_dispatcher.py --severity warning \
    --source-tool gap_detector \
    --message 'Extraction gaps detected in DNA.ACCT (2 dates)' \
    --details-json '{"source":"DNA","table":"ACCT","missing":["2026-03-15","2026-03-16"]}' \
    --dedupe-key 'gap-dna-acct-2026-03'

# Operator test
python3 tools/alert_dispatcher.py --severity informational \
    --source-tool manual-test \
    --message 'Alert dispatcher test from operator'
```

**Tool-specific arguments**:

| Argument | Type | Default | Semantics |
|---|---|---|---|
| `--severity` | str | None | REQUIRED. One of `'informational'` / `'warning'` / `'fatal'`. Drives channel selection (e.g. PagerDuty only for `fatal`; Slack for all) |
| `--source-tool` | str | None | REQUIRED. Name of the calling tool (e.g. `gap_detector`, `verify_server_parity`, `enforce_retention`). Surfaces in alert subject |
| `--message` | str | None | REQUIRED. Human-readable alert body (1-3 sentences). Must NOT contain plaintext PII per P5 (SensitiveDataFilter applied to the message before dispatch) |
| `--details-json` | str | None | Optional structured payload (JSON). Channels that support rich content (Slack blocks, PagerDuty custom fields) consume; channels that don't (SMS) ignore |
| `--channels` | str (comma-separated) | derived from severity | Override channel set. Example: `--channels slack,email`. Default: severity → channel map (`fatal` → `pagerduty,slack,email`; `warning` → `slack,email`; `informational` → `slack`) |
| `--dedupe-key` | str | None | Stable identifier for deduplication. PagerDuty uses this as `incident_key`. Without it, every alert is a new event |

**Stdout** (success): `Alert dispatched (severity=<sev>): N channels ok / M failed.` followed by per-channel one-liner status.

**Stdout** (`--json`): `{"severity": "...", "source_tool": "...", "channels_attempted": [...], "channels_succeeded": [...], "channels_failed": [{"name": "...", "error": "..."}], "audit_event_id": N, "dedupe_key": "..."}`.

**Exit codes**:
- 0: at least one channel succeeded
- 1: all channels failed (logged + audit-logged; operator must check channel health)
- 2: arg-parse error or `--severity fatal` + zero channels-available config

**Tier 0 smoke test** (per § 1.6): `tests/smoke/test_tools_alert_dispatcher.py` — runs in <5s, mocked channel clients. Asserts: (a) module imports; (b) `--help` exits 0; (c) missing `--severity` / `--source-tool` / `--message` → arg-parse error → exit 2; (d) mocked successful channel dispatch → exit 0; (e) mocked all-channel failure → exit 1; (f) `--severity warning` + default channels → mocked Slack invoked, mocked PagerDuty NOT invoked; (g) `--details-json '{invalid json'` → arg-parse error.

**Test surface (Round 5)**:
- Tier 1: severity-to-channel mapping (informational → Slack only; warning → Slack + email; fatal → Slack + email + PagerDuty)
- Tier 1: dedupe-key passed through to PagerDuty payload
- Tier 1: SensitiveDataFilter applied to message before dispatch
- Tier 3 integration: real channel clients (Slack test workspace, PagerDuty sandbox, test email) — fire alert, verify receipt

**Cross-doc references**: B82 (proposed new Phase 0 deliverable for ops-channel routing); Round 3 § 6.1 (SensitiveDataFilter); D26 (audit trail); RB-9 (operations response). **NOT** Phase 0 deliv 0.10 (that deliverable is "2x/day pipeline schedule windows" per 02_PHASES.md L48 — earlier draft of this doc mis-cited it 7 times as the ops-channel deliverable; corrected at cycle 4 validation per R4C4-2 cross-reference finding).

---

## § 4. Edge case mapping (Gate 3 input)

Round 4 is operator-CLI design — most pipeline-correctness edge cases are addressed at the runtime layer where Round 3 modules carry them. This section marks which series Round 4 addresses at the CLI level, which it enables for downstream rounds, and which it surfaces as new.

### § 4.1 M / S / I / N / P / G / D / F / V series walk against Round 4 CLIs

| Series | Round 4 status | Specifics |
|---|---|---|
| **M** (math / lookback / lateness) | ✅ Addressed | § 3.3 `lateness_profile` is the operator-facing CLI for M-series tuning (LookbackDays setting per D11) |
| **S** (SCD2 reliability) | ⚪ Referenced | Round 4 tools don't change SCD2 semantics — those live in pre-Phase-1 `scd2/engine.py`; pre-existing `tools/validate_scd2.py` + `tools/repair_scd2.py` already cover S-series operator surfaces |
| **I** (idempotency) | ✅ Addressed | I-series mitigation at the Round 4 layer is two-tier: **(a) at-the-target idempotency**: every wrapped Round 3 module enforces idempotency at its side effect (e.g. § 1.3 `verify_parquet_snapshot` row-locked + Status-machine idempotent; SP-10 `EnforceRetention` body idempotent; SP-2 audit-log INSERT idempotent), so each Round 4 CLI inherits the idempotency of the function it wraps. **(b) at-the-CLI audit-event level**: every CLI's `EventType='CLI_<TOOL_NAME>'` `PipelineEventLog` row is append-only per D26 — multi-invocation produces multiple audit rows (each invocation is a distinct audit event by design), and the tool's side-effect re-run safety derives from (a). § 3.2 `parquet_verify` short-circuit on `SKIPPED_ALREADY_VERIFIED` is the canonical I-series CLI surface example. Round 3 § 4.1 `ledger_step()` is the idempotency-gate primitive that tools CAN compose if they need step-level gating; § 3 currently relies on the wrapped module's intrinsic idempotency rather than imposing an extra ledger row per CLI invocation. (Pre-cycle-4 reviewer flagged the "every § 3 tool routes through idempotency_ledger" overgeneralization — narrowed here.) |
| **N** (network drive / Parquet) | ✅ Addressed | § 3.1 `parquet_tier_review` + § 3.2 `parquet_verify` are the operator-facing surfaces for N-series: file-missing detection (`mark_missing` workflow), hash-mismatch detection, status-state-machine recovery |
| **P** (PII / encryption) | ✅ Addressed | § 3.4 `decrypt_pii` is the canonical operator decrypt path per D6 + P8 (justification mandatory; PiiVaultAccessLog audit). § 3.9 `process_ccpa_deletion` is the right-to-deletion path per D30 |
| **G** (gap detection / outage recovery) | ✅ Addressed | § 3.5 `detect_extraction_gaps` is the canonical G-series surface per D22; integrates with § 3.11 `alert_dispatcher` for operator notification |
| **D** (2x/day cadence) | ✅ Addressed (failover) | § 3.6 `promote_test_to_prod` is the D-series failover-acknowledgment surface per D29 + D33 |
| **F** (failover / cross-server parity) | ✅ Addressed at CLI surface; ➡️ underlying parity-check mechanism in Round 3 § 3.2 | § 3.6 `promote_test_to_prod` is the F-series operator CLI for failover acknowledgment. § 3.7 `verify_server_parity` is the CLI shim — the actual parity-check mechanism that addresses F21-F23 (added at Round 2 close-out) lives in Round 3 § 3.2 verifier; Round 4 § 3.7 exposes it via operator-facing CLI with D65 severity → exit-code mapping |
| **V** (vault provenance) | ✅ Addressed | § 3.4 `decrypt_pii` writes PiiVaultAccessLog per D26 + P8; § 3.8 `enforce_retention` covers V-series purge boundary (active → purged_for_retention); § 3.9 covers V-series CCPA (active → deleted_per_request) |

### § 4.2 New edge cases surfaced by Round 4

Three candidates for `04_EDGE_CASES.md` additions at Round 4 close-out:

| Proposed | Description | Mitigation in Round 4 |
|---|---|---|
| F (next) | `promote_test_to_prod` invoked WHILE prod is actually healthy or already done. Two distinct sub-cases per canonical SP-4 (L1546 `@Action ∈ ('EXIT_SUCCEEDED', 'EXIT_RUNNING_HEALTHY', 'PROCEED_FAILOVER')`): **(a)** prod cycle already succeeded (`@Action='EXIT_SUCCEEDED'`) — must NOT promote; tool exits 0 (clean informational outcome); **(b)** prod still running with recent heartbeat (`@Action='EXIT_RUNNING_HEALTHY'`) — must NOT promote; tool exits 1 (informational, operator should re-check heartbeat dashboard). The two sub-states have distinct operator semantics; treating them as one would conflate "prod done" with "operator misread dashboard" | § 3.6 explicit handling: SP-4 returns `@Action='EXIT_SUCCEEDED'` → tool exits 0 with descriptive stdout; SP-4 returns `@Action='EXIT_RUNNING_HEALTHY'` → tool exits 1 with descriptive stdout; only `@Action='PROCEED_FAILOVER'` invokes SP-6 acknowledgment + gate flip |
| P (next) | `decrypt_pii` invoked against a token AFTER `process_ccpa_deletion` has run on it — should return `None` with `<NULL> (CCPA-deleted)` message AND still write audit row per D26 | § 3.4 explicit handling: `DecryptDenied` is NOT an exception per Round 3 § 2.2; tool returns exit 0 with `<NULL> (CCPA-deleted)` stdout; audit row IS written |
| I (next) | `parquet_verify` invoked concurrently against the same registry_id from two operator sessions — second one MUST NOT short-circuit pre-write (race window); should serialize via row lock; both audit rows written | § 3.2 + Round 3 § 1.3 concurrency note: concurrent verifies of the SAME registry_id are serialized by SQL Server row locking; both invocations produce audit rows but only one performs the Status flip (second invocation observes `Status='verified'` already and returns `SKIPPED_ALREADY_VERIFIED`) |

Close-out task tracked as **B78** (per § 5.2 backlog proposals): append three rows to `04_EDGE_CASES.md`; operator computes IDs via `grep "^| F[0-9]" 04_EDGE_CASES.md | tail -1` then increment.

---

## § 5. Validation gates (Round 4 producer self-check)

Per D55 + D62, this § is the producer self-check before invoking Gate 2 independent review. **Per Pitfall #9 + Round 2's + Round 3's three-pass + nine-cycle precedents**, this self-check pays explicit attention to EVERY CLI argument that maps to a Round 1 SP parameter, Round 1 column, Round 2 column, or Round 3 module function/parameter against canonical sources.

### § 5.1 Gate 1 self-check — Cross-reference

For each D-number cited in this doc:
- D2, D4, D5, D6, D11, D15, D16, D17, D22, D25, D26, D27, D29, D30, D31, D33, D55, D56, D61, D62, D63, D64, D65, D66, D67, D68, D69, D70, D71, D72, D73, D74-D77 (proposed): all resolve per `03_DECISIONS.md` (D74-D77 are proposed-this-round)
- B-numbers cited (existing in `BACKLOG.md`): B01, B12-B14, B47-B74 (Round 3 carryover per D73), B75-B76 (Round 2 cycle 1 Pattern E framing items per `_validation_log.md` 2026-05-10 entry)
- B-numbers proposed in body + § 5.2 this round (NOT YET in `BACKLOG.md` — close-out task per § 5.4): B77, B78, B79, B80, B81, B82, B83, B84, B85, B86, B87, B88, B89, B90, B91, B93, B94, B95, B96, B97, B98, B99, B100, B101, B102 (25 active; B92 closed in-cycle at first-pass validation) — all defined in § 5.2 with COD/JS/WSJF scoring

For Round 1 SP / table / enum references (Pitfall #9 critical surface — **VERIFIED against canonical DDL at first-pass validation cycle, NOT hedged for later verification**):
- SP-3, SP-4, SP-5, SP-6 (`PipelineExecutionGate_AcquireProd`, `_AcquireTest`, `_RequestCancellation`, `_AcknowledgeCancellation`) — cited per § 3.6. **SP-4's `@Action NVARCHAR(30) OUTPUT` parameter returns one of three canonical values** per `01_database_schema.md` L1546: `'EXIT_SUCCEEDED'` / `'EXIT_RUNNING_HEALTHY'` / `'PROCEED_FAILOVER'`. First-pass validation caught two-state collapse drift (`'exit'` / `'failover'`); corrected.
- SP-10 `EnforceRetention(@DryRun BIT = 1)` — cited per § 3.8. **Single-parameter canonical signature** per L1953-1954. First-pass validation caught invented `@RetentionDate` + `@ActorName` parameters; corrected. Cutoff is per-row column-driven (`PiiVault.RetentionExpiresAt < SYSUTCDATETIME()`), not SP-parameter-driven.
- (anticipated) SP for CCPA deletion — cited per § 3.9 as B01-tracked; not yet authored; cross-reference flagged as 🟡 (anticipated, not yet canonical)
- `PipelineExecutionGate.CycleType` enum (`'AM' / 'PM'`) — cited per § 3.6; **verified against L326-327** (`CK_PipelineExecutionGate_CycleType CHECK (CycleType IN ('AM', 'PM'))`)
- `PipelineExecutionGate.ExecutingServer` column (NVARCHAR(20), constrained to `('production', 'test')`) — cited per § 3.6. First-pass validation caught cross-table column-name lift (`ServerRole` is on `PipelineEventLog` L139, NOT on `PipelineExecutionGate`); corrected to canonical `ExecutingServer` per L310 + L331-332.
- `PipelineLog.LogLevel` enum (`'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'`) — cited per § 3.10; **verified against L215-216** (`CK_PipelineLog_LogLevel CHECK (LogLevel IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'))`)
- SP-2 `PiiVault_Decrypt(@RequestId UNIQUEIDENTIFIER, @Token VARCHAR(40), @Justification NVARCHAR(MAX))` — cited per § 3.4; **verified against L1414-1417**
- `ParquetSnapshotRegistry.Status` enum (7-state per Round 3 § 1.3 `ParquetSnapshotStatus` StrEnum) — cited per § 3.1 + § 3.2; verified against Round 3 § 1.3 + CLAUDE.md narrative

For Round 2 dataclass references (Pitfall #9 fifth sub-class — argument/field-name lift surface):
- `ParityReport` canonical fields: `(server_name, baseline_name, baseline_pinned_at, checks, fatal_count, warning_count, informational_count, match_count, overall)` per `02_configuration.md` L946-955. First-pass validation caught invented `generated_at` + `baseline_sha256` fields; corrected. **§ 3.7 cites Round 2 canonical signature verbatim.**
- `verify_server_parity(baseline_path, server_name, fail_on_warning)` canonical signature per `02_configuration.md` L957-961. First-pass validation caught dropped `server_name` parameter; corrected.

For Round 2 references:
- All § 2 / § 3 / § 4 / § 5 references in `02_configuration.md` resolve

For Round 3 references:
- § 1.1 / § 1.2 / § 1.3 / § 2.1 / § 2.2 / § 2.3 / § 3.1 / § 3.2 / § 4.1 / § 4.2 / § 5.1 / § 5.2 / § 5.3 / § 6.1 / § 6.2 / § 6.3 / § 7.1 — every cross-reference resolves
- Wrapped function signatures: `verify_parquet_snapshot`, `mark_replicated`, `mark_archived`, `mark_purged`, `mark_missing`, `query_snapshot`, `replay_parquet_snapshot`, `tokenize_pii_columns`, `decrypt_token`, `call_vault_sp`, `profile_lateness`, `detect_extraction_gaps`, `verify_server_parity`, `track`, `ledger_step` — all verified against Round 3 § 1-7 signatures

**Status**: ✅ producer self-check completed. Mandatory Gate 2 independent review per D55+D56+D62.

### § 5.2 Gate 5 self-check — Risk delta + Backlog surfacing (per D61)

**Per D62 Pitfall #8** (added at Round 2 close-out): every risk-delta line in this § MUST be verified against `RISKS.md` BEFORE Round 4 locks.

**Risks introduced / addressed**:

```
RISKS (per D61):
- 🆕 NEW PROPOSAL: R22 — CLI exit-code drift (Automic interprets exit codes per § 1.1 contract;
       if a future tool author returns a non-canonical code, Automic mis-categorizes the result —
       could escalate or under-escalate). Likelihood Low × Impact Medium = 3 ⚪.
       Mitigation: Tier 0 smoke (§ 1.6) asserts the mapping. Round 5 Tier 1 extends with
       per-exception-class exit-code property tests.
       Status: NOT YET ADDED to RISKS.md — close-out task per Pitfall #8.

- ⬇️ DE-ESCALATED (pending substantiation): R03 (single-engineer Python expertise) — Round 4 CLI
       specs reduce tribal knowledge further (operator-experience now formally documented).
       Hedge per Pitfall #8: do NOT reduce score until first ~3 Round 4 tools ship with operator
       drill validation.

- ⬇️ DE-ESCALATED (pending): R19 (Tier 0 drift) — Round 4 explicitly extends Tier 0 contract to
       CLIs via D77 proposed. Hedge per Pitfall #8: do not reduce score until first Round 4
       Tier 0 batch exists and demonstrates the contract.
```

**Backlog proposals** (per D61 — current max in BACKLOG.md after Round 2 cycle 1 Pattern E is **B76**; NEXT_AVAILABLE = **B77**):

```
BACKLOG (per D61):
- 🟡 B77: Add R22 to RISKS.md (CLI exit-code drift) at Round 4 close-out (Pitfall #8 discipline)
       COD 2, JS 1, WSJF=2.0
- 🟡 B78: Append three new edge cases (F-next / P-next / I-next per § 4.2) to
       04_EDGE_CASES.md at Round 4 close-out; COD 2, JS 1, WSJF=2.0
- 🟡 B79: Round 1 schema evolution governance Round 7 OR Round 6 amendment scope: add
       @AcknowledgmentOnly parameter to SP-4 PipelineExecutionGate_AcquireTest so § 3.6
       promote_test_to_prod dry-run mode can preview without modifying gate state; OR
       document that dry-run mode invokes SP-4 with @ExecutingServer='preview' (a sentinel
       value SP-4 understands as read-only). Choice of mechanism deferred to Round 6/7
       architectural review. COD 4, JS 2, WSJF=2.0
- 🟡 B80: Add JOB_PARQUET_VERIFY + JOB_LOG_CLEANUP to Round 2 § 5.1 frozen-8 Automic inventory
       (current count 8 → 10). Requires Round 7 governance touch or Round 6 amendment.
       COD 3, JS 2, WSJF=1.5
- 🟡 B81: Author the CCPA deletion SP (currently B01-tracked) so § 3.9 process_ccpa_deletion
       has a real SP to wrap. COD 5, JS 2, WSJF=2.5
- 🟡 B82: Propose new Phase 0 deliverable for ops-channel client (Slack / PagerDuty / email / SMTP target identified) + author the `OPS_CHANNEL_*` env keys + implement the ops-channel client itself at Round 6 deployment so § 3.11
       alert_dispatcher has a real implementation target. COD 4, JS 3, WSJF=1.3
- 🟡 B83: Backfill Tier 0 smoke tests for all 11 Round 4 tools at Round 6 deployment time
       (Round 4 specs include sketches; Round 6 implements them). COD 4, JS 2, WSJF=2.0
- 🟡 B84: Update `udm-test-author` agent template to author Tier 0 sketches for CLI tools
       alongside Tier 1 (D67 + D77 extension); COD 2, JS 1, WSJF=2.0
- 🟡 B85: Author `utils/errors.py` with `PipelineError` / `PipelineFatalError` /
       `PipelineRetryableError` base classes (per D68); needed by every Round 4 tool wrapper
       per § 1.8. COD 3, JS 2, WSJF=1.5
- 🟡 B86: Add CLI_* EventType family to CLAUDE.md Architecture Decisions section + Round 6
       deployment doc. D76 audit-row contract introduces 11 new EventType values en masse
       (`CLI_PARQUET_TIER_REVIEW`, `CLI_PARQUET_VERIFY`, `CLI_LATENESS_PROFILE`,
       `CLI_DECRYPT_PII`, `CLI_DETECT_EXTRACTION_GAPS`, `CLI_PROMOTE_TEST_TO_PROD`,
       `CLI_VERIFY_SERVER_PARITY`, `CLI_ENFORCE_RETENTION`, `CLI_PROCESS_CCPA_DELETION`,
       `CLI_LOG_RETENTION_CLEANUP`, `CLI_ALERT_DISPATCH`); CLAUDE.md should enumerate.
       COD 2, JS 1, WSJF=2.0
- 🟡 B87: D74 / § 1.8 exception-handling — decide whether `KeyboardInterrupt` maps to Unix-
       conventional exit 130 (128+SIGINT) instead of operator-convention exit 1. Project-wide
       convention call; document in CLAUDE.md. COD 1, JS 1, WSJF=1.0
- 🟡 B88: D75 `--dry-run` AND `--apply` together — clarify mutual exclusion (likely
       `--apply --dry-run` together → arg-parse error). § 1.4 wording polish.
       COD 1, JS 1, WSJF=1.0
- 🟡 B89: D77 in § 2 enumerates 5 Tier 0 assertions (a-e); § 1.6 enumerates 6 (a-f, adding
       exception → exit code mapping). Reconcile to a single canonical list (probably 6).
       COD 1, JS 1, WSJF=1.0
- 🟡 B90: § 1.7 invocation-pattern heuristic — explicitly enumerate the
       `AUTOMIC_RUN_ID set AND isatty() True` edge case (operator debugging in Automic's
       debug mode). Current heuristic resolves to 'automic'; document the choice.
       COD 1, JS 1, WSJF=1.0
- 🟡 B91: § 4.2 "F (next)" edge case description — when 🔴 #1 was fixed (SP-4 enum drift),
       the corrected text covers both `'EXIT_SUCCEEDED'` and `'EXIT_RUNNING_HEALTHY'` as
       distinct prod-healthy states. Update 04_EDGE_CASES.md F (next) entry to reflect both
       sub-states explicitly when B78 lands. COD 1, JS 1, WSJF=1.0
- 🟡 B92: Closed at first-pass validation 2026-05-10 — verify_server_parity signature in
       § 3.7 corrected to include `server_name` parameter per Round 2 canonical L959. Listed
       for traceability of first-pass findings.
- 🟡 B93: Round 1 schema evolution governance Round 7 OR Round 6 amendment scope: add
       @CutoffOverride DATETIME2(3) = NULL parameter to SP-10 EnforceRetention so operator-
       driven override-without-row-mutation is supported (current canonical SP-10 takes only
       @DryRun; cutoff is column-driven via PiiVault.RetentionExpiresAt). Same pattern as
       B79 (@AcknowledgmentOnly on SP-4). COD 3, JS 2, WSJF=1.5
- 🟡 B94: Round 1 schema evolution governance Round 7 OR Round 6 amendment scope: add
       @CategoryFilter NVARCHAR(MAX) = 'all' parameter to SP-10 EnforceRetention so the
       `--categories` operator-level filter has a corresponding SP-level filter (was invented
       in 04_tools.md first draft; dropped from CLI surface at first-pass validation).
       COD 2, JS 1, WSJF=2.0
- 🟡 B95: Strengthen HANDOFF Pitfall #9 first sub-class wording to explicitly cover Python
       PEP 3102 `*,` keyword-only marker drift in spec citations. Cycle 3 + cycle 4 column-walks
       found 6+ instances; researcher (R4C4-5) recommends single-sub-class extension over a
       new 6th sub-class. COD 1, JS 1, WSJF=1.0
- 🟡 B96: Add SIGINT/exit-130 rationale note to § 1.8 — operator-convention exit 1 chosen over
       Unix-conventional exit 130 (128+SIGINT). Researcher (R4C4-5) finds this defensible
       (UDM tools aren't shell-composed) but worth a one-line rationale. COD 1, JS 1, WSJF=1.0
- 🟡 B97: Add SnowSQL cross-reference note to § 1.1 — Snowflake's own CLI uses a 6-code scheme
       (0/1/2/3/4/5); UDM 3-code grain wraps at higher orchestration layer. Researcher (R4C4-5)
       suggests adjacent-precedent citation. COD 1, JS 1, WSJF=1.0
- 🟡 B98: New edge case F-next-2 (proposed F25): alert dispatcher invoked with severity=fatal
       AND zero channels available → tool exits 2 + log-only audit trail + operator escalation
       path documented. Add to 04_EDGE_CASES.md at close-out (paired with B78). COD 2, JS 1, WSJF=2.0
- 🟡 B99: Document SP-4↔SP-6 race window (between SP-4 verdict and SP-6 acknowledgment) as
       F4-extension in § 4.2 OR as Round 5 Tier 4 crash-injection test scenario explicitly.
       R4C4-4 cycle 4 finding. COD 2, JS 1, WSJF=2.0
- 🟡 B100: Re-label § 5.2 (Round 4) and § 10.2 (Round 3) to surface Gate 5 invariant walk
       explicitly — current label conflates Gate 5 (idempotency/regression) with D61 risk-delta
       meta-check. R4C4-4 cycle 4 finding (Round 3 set the precedent; both rounds have the same
       label structure). Either re-label both OR split into Gate 5a (invariant) + Gate 5b
       (risk-delta). COD 2, JS 1, WSJF=2.0
- 🟡 B101: RB-11 framing — `05_RUNBOOKS.md` canonical title is "7-Year Retention Enforcement";
       Round 4 § 3.8 + § 3.9 mislabel it as "legal-hold runbook" (L1124, L1156, L1215). Legal-hold
       is a sub-feature of retention, not a standalone runbook. R4C4-2 cycle 4 finding. Either
       rename RB-11 title to "Retention + Legal Hold" OR correct Round 4's framing. COD 1, JS 1, WSJF=1.0
- 🟡 B102: § 0 Read order (L13-19) reorders the canonical CCL Stage 1 list (puts CURRENT_STATE
       before NORTH_STAR; MULTI_AGENT_GUIDE L189-194 has NORTH_STAR first). All 4 Stage 1 docs
       are covered, but order doesn't match canonical. R4C4-2 cycle 4 finding. Either correct
       Round 4's order OR update MULTI_AGENT_GUIDE to allow round-specific re-ordering with
       justification. COD 1, JS 1, WSJF=1.0
- 🟡 B103: Round 3 § 2.2 `decrypt_token` has an internal contradiction — Error modes L597-598
       declares `DecryptDenied (PipelineFatalError)` for purged tokens, but docstring L626-628
       says "returns None for deleted_per_request / purged_for_retention tokens". Round 4
       § 3.4 propagates the docstring-consistent path (returns None) but doesn't surface the
       upstream contradiction. R4C8 cycle 8 finding. Either: (a) fix Round 3 § 2.2 to remove
       the `DecryptDenied` exception class, OR (b) fix Round 3 § 2.2 docstring to say "raises
       DecryptDenied". COD 2, JS 1, WSJF=2.0
- 🟡 B104: § 3.10 log_retention_cleanup `--batch-size` default of 50000 contradicts the B-2
       lesson cited in the same line ("Lower to avoid lock escalation"). B-2 actually warns
       at 5000 locks; 50K rows × 1 lock-per-row = 50K locks, 10x the threshold. R4C8 cycle 8
       finding. Recommend reducing default to 4000 (mirroring `config.SCD2_UPDATE_BATCH_SIZE`).
       COD 1, JS 1, WSJF=1.0
- 🟡 B105: § 3.6 introduces `EventType='CYCLE_FAILED_OVER'` (L851, L905) as a new event-type
       name not covered by B86 (which proposes `CLI_*` family). Either add CYCLE_* to B86 OR
       create a sibling B-number for the CYCLE_FAILED_OVER + CYCLE_CANCELLED additions.
       R4C8 cycle 8 finding. COD 1, JS 1, WSJF=1.0
- 🟡 B106: B101 line citations are off-by-one — claims RB-11 mislabel at "L1124, L1156, L1215"
       but actual lines are L1069, L1125, L1216 post-fixes. The backlog self-cite has stale
       lines. R4C8 cycle 8 finding. Trivial fix: correct B101's line citations during close-out.
       COD 1, JS 1, WSJF=1.0
- 🟡 B107: HANDOFF Pitfall #9 sixth sub-class addition — "wrong section number with invented
       section description" — cycle 8 found 2 instances (§ 5.3.5 vs § 5.4 + invented § 2.1.10).
       Pattern: producer cites a specific § X.Y.Z that doesn't exist OR cites the wrong section
       with an invented narrative description. Add to HANDOFF § 8 Pitfall #9 sub-class list at
       Round 4 close-out (pairs with B95 for keyword-only marker sub-class).
       COD 2, JS 1, WSJF=2.0
```

### § 5.3 Gate 2 — Independent review (NEXT STEP at Round 4 close-out)

Invocation pattern per `udm-design-reviewer` agent + D62 CCL:

> Per `MULTI_AGENT_GUIDE.md` § Canonical Context Load (D62), perform CCL before reviewing. First content-substantive `Read` MUST be on a Stage 1 doc. Review `phase1/04_tools.md` for: (1) Gate 1 cross-reference — every D-number cited resolves; every Round 1 SP / table / enum reference matches canonical DDL per Pitfall #9; every Round 3 module function/parameter signature matches Round 3 spec (THIS IS THE HIGH-RISK SURFACE — Round 2 + Round 3 hit this 17 times total); (2) Gate 2 design soundness — D74-D77 sub-decisions sound; CLI conventions in § 1 internally consistent; (3) Gate 3 edge case coverage in § 4; (4) Gate 4 verification — each ✅ in § 4.1 has tangible mechanism; (5) Gate 5 idempotency / regression — D55-D73 invariants preserved; risk-delta claims in § 5.2 match `RISKS.md` per Pitfall #8.

Expected output: 5-gate validation report; **mandatory second-pass per D56 if 🔴; D72 ceiling applies; Pattern E (5-agent deep validation with research grounding) available if structural drift surfaced**.

### § 5.4 Round 4 acceptance criteria checklist (will run at close-out)

- [ ] Intro (Read order / Scope / Foundational decisions / New decisions anticipated) through § 5 all present and self-consistent
- [ ] D74 – D77 captured in `03_DECISIONS.md` (CLI exit-code contract / argument naming / audit-row contract / Tier 0 scaffold)
- [ ] `udm-design-reviewer` independent first-pass returned no 🔴 (mandatory second-pass + further cycles per D56 + D72 if 🔴)
- [ ] `_validation_log.md` entry appended documenting all validation passes (cycle count + verdict per cycle)
- [ ] Cross-doc updates landed: 04_EDGE_CASES.md (B78 — 3 new cases); CLAUDE.md (one-line pointer in Architecture Decisions to `04_tools.md`); 05_RUNBOOKS.md cross-links for RB-7 / RB-8 / RB-9 / RB-10 → relevant § 3 tools
- [ ] BACKLOG.md updated with B77 – B102 (26 proposed: B77-B94 from initial draft + B95-B102 from cycle 4 advisory/findings; minus B92 closed in-cycle = 25 active) + any further cycle-introduced 🟡s
- [ ] RISKS.md updated with R22 (per B77)
- [ ] HANDOFF.md §3 + §12 + §14 updated via `udm-round-closeout`
- [ ] CURRENT_STATE.md "Recently completed" + "Recent rounds" + "Last updated" + "Next concrete step" updated (Next concrete step flips to Round 5 — Tests)
- [ ] NORTH_STAR.md Phase 1 row already shows pillars (no change expected — Round 4 advances **Operationally stable** + **Audit-grade** + **Traceability** as expected)
- [ ] Doc status flip: `phase1/04_tools.md` "🟡 Drafting" → "🟢 Locked" (after validation passes)

---

## End of Round 4 — Tools

**Status when this checklist completes**: 🟢 Locked, ready for Round 5 (Tests) to consume the operator-CLI surface and Round 3 module-interface contracts to write Tier 1/2/3/4 tests, **AND** Round 5 owes the systematic B47-B94 (Round 3 carryover B47-B74 per D73 + Round 4 carryover B75-B94) triage close-out. Round 6 (Deployment) implements module bodies + tool CLIs against these specs.
