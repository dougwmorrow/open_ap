# UDM Blindspot Ledger — Query Protocol

**Date authored**: 2026-05-16
**Source spec**: AppLaunchpad agentic-architecture.md §12.3 (blindspot ledger pattern)
**Locked by**: D-N (TBD at next commit; tracks adoption decision per applaunchpad-udm-gap-analysis-2026-05-16.md)
**Canonical source**: `docs/migration/blindspots/ledger.yml`
**Prose source**: `docs/migration/HANDOFF.md` §8 Pitfall #9 sub-class accumulator (9.a-9.o)

---

## What this is

The blindspot ledger is the queryable + executable encoding of HANDOFF §8 Pitfall #9 sub-classes. Each entry in `ledger.yml` represents a drift pattern that has been observed enough times (typically ≥3 events per HANDOFF convention) to warrant formal detection.

**Why ledger instead of prose**:

- Prose in HANDOFF §8 requires producer SELF-CHECK at the right moment. The 5-event evidence base 2026-05-15→2026-05-16 (commits 521b68c, 3eef410, aee329c, a03a35c, 4112e92) proved producer self-check is necessary-but-insufficient.
- YAML with `detection_rule` per entry can be queried by `tools/query_blindspots.py` against a candidate artifact / commit / cohort BEFORE the work ships.
- Catch-time shrinks from 1-4 day post-hoc gap-check lag to seconds at producer-time.

---

## When to query

### Mandatory (block on FAIL):

1. **Pre-commit**: producer queries the ledger against the commit's staged files + commit message BEFORE git commit. Any p0 match BLOCKS the commit.
2. **Post-edit cascade hard rule 14 Step 2**: `udm-gap-check` skill invokes the ledger as its first check.
3. **Round close-out cascade**: `udm-round-closeout` skill invokes the ledger against all artifacts touched during the round.
4. **Pattern F audit**: `udm-cascade-auditor` invokes the ledger as Trigger H (new) — paired-judgment validates the deterministic scan.

### Recommended (warn on match):

5. **Wave-spawn brief authoring**: parent agent queries the ledger against the brief content (catches 9.l canonical-spec-signature drift before subagent spawns).
6. **D-number lock**: `udm-decision-recorder` queries against the D-N body (catches 9.a-9.h canonical-source drift).
7. **RB-N authoring**: `udm-runbook-author` queries against the runbook body (same scope).
8. **SP body authoring**: queries against the SP definition (catches 9.b-9.f schema drift).

### Optional:

9. **Spec doc edit**: any edit to `docs/migration/phase1/0X_*.md` can query the ledger against the edit's diff.

---

## How to query

### CLI usage

```bash
# Default: scan staged files + commit message against the ledger
python3 tools/query_blindspots.py

# Scan a specific file
python3 tools/query_blindspots.py --file docs/migration/03_DECISIONS.md

# Scan a commit by hash
python3 tools/query_blindspots.py --commit 4112e92

# Scan a multi-file cohort (e.g., all files modified since main)
python3 tools/query_blindspots.py --since-main

# Filter by severity (default: all)
python3 tools/query_blindspots.py --severity p0,p1

# Filter by tag (default: all)
python3 tools/query_blindspots.py --tag schema,sp-body

# Filter by class (default: all)
python3 tools/query_blindspots.py --class canonical-source-drift

# Filter by agent (default: all)
python3 tools/query_blindspots.py --agent producer

# Dry-run (default): report matches but do not block
python3 tools/query_blindspots.py --dry-run

# Live mode (exit code 2 on p0 match, blocks pre-commit hook)
python3 tools/query_blindspots.py --live
```

### Exit codes (per D74)

- `0`: SUCCESS — no matches OR all matches resolved
- `1`: WARNING — p1/p2 matches present; producer should fix but commit may proceed in `--dry-run`
- `2`: OPERATIONAL FAILURE — p0 match present; blocks in `--live` mode
- `3`: FATAL — ledger malformed / source files unreadable / CLI error

### Audit row (per D76)

Every invocation writes a `CLI_QUERY_BLINDSPOTS` event to `General.ops.PipelineEventLog` (when DB available) OR to `_session_logs/cli_query_blindspots_<date>.log` (when DB unavailable, e.g., dev workstation without SQL Server). Metadata JSON:

```json
{
  "args": ["--file", "docs/migration/03_DECISIONS.md"],
  "actor": "dougmorrow@protonmail.com",
  "ledger_version": 1,
  "ledger_entries_checked": 15,
  "matches": [
    {"entry_id": "9j-b-item-status-render-discipline", "severity": "p2", "location": "BACKLOG.md L186"}
  ],
  "exit_code": 1
}
```

---

## How to add a new entry

### Step 1: gather evidence

New entries require ≥3 empirical occurrences (HANDOFF §8 convention). Document each occurrence in HANDOFF §8 Pitfall #9 sub-class accumulator FIRST. The ledger entry is the EXECUTABLE form of the prose; prose is canonical.

### Step 2: author the entry

Add to `ledger.yml` under `entries:` in alphabetical order by `id`. Required fields:

- `id`: kebab-case unique identifier (e.g., `9p-new-pattern`)
- `class`: drift category — one of {canonical-source-drift, discipline-not-applied, render-drift, ...}
- `severity`: p0 (blocks lock) | p1 (must fix before close-out) | p2 (deferrable)
- `agents`: roles that should query (subset of {producer, reviewer, parent, any})
- `tags`: free-form labels for filter matching
- `symptom`: 1-sentence description
- `detection_rule`: pseudo-code + concrete regex (must be implementable by `query_blindspots.py`)
- `remediation`: what to do once rule fires
- `evidence_base`: count
- `evidence_first`: first occurrence reference
- `evidence_commits`: list of hashes (when applicable)
- `handoff_anchor`: line reference in HANDOFF.md §8

### Step 3: extend the CLI

If detection_rule introduces a new check pattern not yet implemented in `tools/query_blindspots.py`, extend the CLI's check functions. Add a Tier 0 test verifying the new pattern matches correctly.

### Step 4: validate self-application (per 9m)

The new entry MUST be queried against its own authoring commit. If the entry's detection_rule fires on the commit that introduced the entry, that's a recursive bug — fix before lock.

### Step 5: register

- Update `_validation_log.md` with entry-authoring event row
- Bump `ledger.yml` `version:` field
- Bump `last_updated:` date
- Open or close any related B-N items

---

## Detection-rule expression conventions

Each `detection_rule` field uses this loose pseudo-code structure:

```
For every <thing> in <scope>:
  1. <Extract phase> — usually regex or AST walk
  2. <Lookup phase>  — usually file read or schema query
  3. <Verify phase>  — assertion or comparison
  4. <Verdict phase> — FAIL / PASS / WARN with diagnostic message
```

The CLI parses these as DESCRIPTIVE only — actual check logic is implemented in `tools/query_blindspots.py` per-entry. The pseudo-code is for HUMAN reviewers to understand what the check does; the CLI doesn't execute the pseudo-code literally.

**When extending CLI**: add a Python function `check_<entry_id>()` in `tools/query_blindspots.py` that implements the pseudo-code. Register the function in the `CHECKS` dict keyed by entry id.

---

## Severity tiers

| Tier | Meaning | Cascade behavior |
|---|---|---|
| `p0` | BLOCKS lock / 🟢 status flip | `--live` mode exits 2; cascade halts |
| `p1` | Must fix before round close-out | `--live` mode exits 1; can land in commit if tracked |
| `p2` | Deferrable to backlog | Always exit 0 or 1; open B-N at minimum |

Severity is property of the BLINDSPOT entry, not the matched instance. A p0 entry firing on a minor surface still blocks; the entry's severity reflects the LATENT risk of the pattern.

---

## Update cadence

- **Per-commit**: query the ledger; act on results
- **Per round close-out**: review ledger entries for new evidence; consider promoting `evidence_base` counts; consider new entries from accumulated Pitfall #9 sub-classes
- **Per Phase boundary**: full re-validation — re-run all detection_rules against the round's artifact set; archive resolved entries (move to `_archive/blindspots-ledger-resolved-<date>.yml` if a class problem is structurally fixed)

---

## Relationship to other discipline mechanisms

| Mechanism | Role | Ledger interaction |
|---|---|---|
| HANDOFF §8 Pitfall #9 sub-classes | Canonical prose source | Ledger = executable form |
| CLAUDE.md hard rules 9 / 11 / 13 / 14 | Discipline-level requirements | Ledger is one of several checks invoked by hard rules |
| `udm-gap-check` skill | Independent reviewer | First check = ledger query |
| `udm-step-10-verifier` skill | In-flight Step 10 validation | Subset of ledger entries (9.n + 9.j subset) |
| `udm-cascade-auditor` agent (Pattern F) | Paired-judgment audit | Ledger is one of the Trigger sources (proposed Trigger H) |
| Pre-commit git hook | Pre-commit deterministic check | Calls `query_blindspots.py --live` |
| Post-build cascade Step 2 | hard rule 14 cascade | Ledger query is the first gap-analysis step |

**Composition principle**: the ledger does NOT replace the prose source. HANDOFF §8 remains canonical. The ledger is one mechanism among many — its job is to shift catch-time from post-hoc to in-flight for the patterns it CAN encode. Patterns that can't be expressed as detection_rules remain prose-only.

---

## Limitations

- **Detection rules are heuristics**: a rule may FAIL on a legitimate pattern that LOOKS like drift. Producer reviews the FAIL diagnostic + decides if it's a real match or a false positive.
- **Schema drift detection requires schema snapshots**: 9.a-9.f detection_rules reference `phase1/01_database_schema.md` — when the schema doc is being edited, false positives are likely. Producer skips the schema-related entries during schema-doc edits.
- **No NLP semantics**: detection_rules are regex + structural checks. Subtle semantic drift (e.g., "the SP body has the right column names but uses them in the wrong way") is NOT catchable by the ledger; requires human review.
- **Evidence-base counts may lag**: when a recurrence is caught, the producer should bump `evidence_base` in the same commit (per 9.m self-application).

---

## Anti-pattern to detect (within the ledger itself)

The ledger is itself a discipline tracker — per 9.m (discipline-not-applied-to-its-own-tracker), every operation on the ledger MUST be queryable against the ledger.

**Self-test**: after editing `ledger.yml`, run:

```bash
python3 tools/query_blindspots.py --file docs/migration/blindspots/ledger.yml
```

If the edit introduces drift detectable by the ledger's OWN rules, the edit is invalid — fix before commit.

---

## Roadmap

**Phase 1 (this commit)**: 15 entries (9.a-9.o); pre-commit + post-build cascade integration via CLI; HANDOFF §8 cross-reference.

**Phase 2 (deferred)**: extend `udm-gap-check` skill to invoke ledger as first check; deprecate prose-only gap-check workflow where ledger coverage exists.

**Phase 3 (deferred)**: integrate with `tools/verify_cascade.py` (Pattern F Layer 1 deterministic script) — add ledger queries as additional triggers.

**Phase 4 (deferred per D6 minimal-adoption decision)**: full AppLaunchpad orchestrator + event store + ingester adoption per `applaunchpad-udm-gap-analysis-2026-05-16.md`.

---

## Cross-references

- `docs/migration/HANDOFF.md` §8 Pitfall #9 (canonical prose source)
- `docs/migration/blindspots/ledger.yml` (canonical YAML)
- `tools/query_blindspots.py` (CLI scanner)
- `docs/migration/_research/applaunchpad-udm-gap-analysis-2026-05-16.md` (adoption rationale)
- `docs/migration/_research/agentic-orchestration-architecture-2026-05-16.md` (industry research grounding the adoption)
- `agentic-architecture.md` (AppLaunchpad source spec; repo root)
- `CLAUDE.md` hard rules 9 / 11 / 13 / 14 (discipline enforcement)
