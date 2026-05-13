---
name: udm-execution-classifier
description: Records execution metadata for every newly-authored executable artifact (script / tool / migration / runbook procedure / CLI command) — classifies along (Manual vs Scheduled trigger) × (One-time vs Recurring frequency) axes; routes each entry to the correct tracker. Surfaces "is this manual or scheduled? one-time or recurring?" answers explicitly so operators + engineers always know what to run + when. Invoke after authoring any executable artifact OR during design-review / round close-out cascade to verify classification is recorded.
---

# UDM Execution Classifier

Records HOW a newly-built executable artifact gets invoked operationally. Per user-direction 2026-05-12 ("I'll need to be aware of any one off scripts. If a tool need to be run once, I'll need to know"), every executable artifact must be classified along TWO axes + routed to the correct canonical tracker.

## When to invoke

- **After authoring** any new script / tool / migration / runbook procedure / CLI command with executable side effects (file writes, DB writes, network calls, process invocations)
- **During design-review** as a Gate 1 cross-reference sub-check (verify classification recorded; advisory finding if not)
- **During round close-out cascade** before round 🟢 lock (verify all this-round artifacts have classification)
- **When opening a new B-N in BACKLOG.md** that creates an executable artifact (record classification at backlog-entry time so future authors inherit it)

## When NOT to invoke

- For pure documentation edits (no executable side effect)
- For spec-doc authoring (specs describe; they don't execute — the IMPLEMENTATION later needs classification)
- For internal library code only invoked by other code (e.g., `data_load/parity_baseline_capture.py` module function wrapped by `tools/capture_parity_baseline.py` CLI — the CLI gets classified; the module function inherits)
- For tests (tests are dev-time; not operational artifacts)

## Canonical Context Load (CCL) per D62

- **Stage 1** (mandatory, 4 reads): `NORTH_STAR.md`, `HANDOFF.md`, `CURRENT_STATE.md`, `CHECKS_AND_BALANCES.md`
- **Stage 2** (mandatory): `RISKS.md`, `BACKLOG.md`, `_validation_log.md`
- **Stage 2.5** (mandatory for this skill — the two canonical trackers being routed to):
  - `docs/migration/ONE_OFF_SCRIPTS.md` — one-time + ad-hoc operator tools
  - `docs/migration/phase1/02_configuration.md` § 5.1 + Round 7 § 6.2 frozen-N Automic inventory — scheduled-recurring
- **Stage 3** (task-specific): the artifact being classified + the canonical spec source the artifact implements
- **Stage 4** (reference-on-demand): grep `BACKLOG.md` for the B-N entry the artifact closes (if any); existing entries in ONE_OFF_SCRIPTS.md for analogous artifact patterns

## Classification matrix

Every executable artifact has TWO axes:

| Axis 1 — Trigger | Axis 2 — Frequency | Routing destination |
|---|---|---|
| **Manual** (operator-invoked via CLI) | **One-time** (per-server / per-CSV / per-spike) | `ONE_OFF_SCRIPTS.md` — "Active items" → appropriate sub-table |
| **Manual** | **Recurring (ad-hoc)** (operator decides when; no fixed schedule) | `ONE_OFF_SCRIPTS.md` — "Ad-hoc operator tools" sub-section |
| **Scheduled** (Automic / cron / systemd timer) | **One-time** (rare — one-shot Automic job that gets disabled after) | `ONE_OFF_SCRIPTS.md` Active items + cross-ref to phase1/02 § 5.1 Automic inventory entry marked one-shot |
| **Scheduled** | **Recurring** (e.g., `JOB_PIPELINE_AM` weekday 02:00) | `phase1/02_configuration.md` § 5.1 frozen-N Automic inventory + Round 7 § 6.2 schedule additions; NOT in ONE_OFF_SCRIPTS.md |

## Procedure

1. **Read** the artifact source + its canonical spec
2. **Determine Axis 1 (Trigger)**:
   - Is there an Automic job definition? → Scheduled
   - Is there a cron / systemd timer reference? → Scheduled
   - Is it invoked only via CLI by an operator? → Manual
   - Look for: `#JOB_*` Automic annotation, systemd unit reference, schedule comment in docstring, scheduled-tool registry mention
3. **Determine Axis 2 (Frequency)**:
   - One-time signals: idempotent `IF NOT EXISTS`-guarded migration; per-server setup; per-CSV import; spike code in `_spike_*` dirs; one-shot data fix
   - Recurring signals: hourly/daily/weekly/monthly schedule; per-pipeline-cycle invocation; operator-runs-as-needed reconciliation
4. **Route the entry**:
   - **One-time (any trigger)**: append entry to `ONE_OFF_SCRIPTS.md` "Active items" appropriate sub-table with: status (🟡 Build pending / 🟢 Build complete / ✅ Run / ⚫ Archived) + script path + purpose + owner + trigger
   - **Manual-recurring (ad-hoc)**: append to `ONE_OFF_SCRIPTS.md` "Ad-hoc operator tools" sub-section with cadence note
   - **Scheduled-recurring**: append to `phase1/02_configuration.md` § 5.1 frozen-N Automic inventory (additive per D92 — additive ALTER + SchemaContract row if a new persistent table is involved) + cite in artifact docstring
5. **Verify the artifact's own docstring** documents:
   - Whether it's idempotent on re-run (for one-time scripts; mandatory per D15)
   - The trigger mechanism (CLI command / Automic job name / cron entry)
   - The frequency expected (one-time per server / weekly / etc.)
   - The audit-row family it writes to (per D76 — `MIGRATION_*` / `CLI_*` / `STARTUP_*` / `DEPLOYMENT_*`)

## Output / artifact

- ONE entry in the appropriate tracker (`ONE_OFF_SCRIPTS.md` OR `phase1/02_configuration.md` § 5.1)
- Brief summary returned to the parent agent: `<artifact path> classified as <Trigger × Frequency>; entry written to <tracker>:<section>; docstring verified to include {idempotency, trigger, frequency, audit-row family}`
- If the artifact's docstring is missing any of the 4 verification items, surface as a 🟡 advisory for inline fix

## Anti-patterns

- ❌ **Skipping classification** because "it's obvious" — the user explicitly wants visibility on every executable artifact. No exceptions for "obvious migration scripts" — classify all of them.
- ❌ **Classifying based on script name alone** (e.g., `migrations/*.py` is not always one-time; check the actual invocation pattern. Some migration-pattern scripts run periodically — e.g., recurring data fixes.)
- ❌ **Recording in BOTH trackers** for the same artifact (one canonical home per artifact; cross-ref between them is fine via "see also" pointer)
- ❌ **Inventing new classification axes** — these 2 axes cover all cases. If a fifth combination feels needed, propose a new skill rather than overload this one.
- ❌ **Forgetting to verify the artifact's docstring** documents idempotency + trigger + frequency + audit-row family — docstring is operator-facing; missing context = operator confusion at execution time.

## Related skills / agents

- `udm-test-author` — invoke this skill after authoring tests for any tool/migration to ensure the tooled artifact has classification
- `udm-design-reviewer` — invoke this skill as a Gate 1 cross-reference sub-check during review (verify classification recorded)
- `udm-runbook-author` — invoke this skill for any new RB-N runbook that includes one-time operational procedures
- `udm-round-closeout` — round close-out cascade should verify all this-round artifacts have classification (becomes a new Section 11 checklist item at next skill-evolution cycle)
- `udm-checks-and-balances` — Gate 1 cross-reference checks may surface "classification missing" 🟡 findings; this skill is the canonical reference for the fix

## Decision citations

- D113 (POLISH_QUEUE.md cosmetic tracker discipline — analogous pattern; this skill applies the same operational-tracker discipline to executable artifacts at one level higher than cosmetic items)
- D55 5-gate validation Gate 1 cross-reference (classification IS a cross-reference requirement — does the artifact appear in the right canonical tracker?)
- D62 Canonical Context Load (mandatory reads before invocation)
- D76 audit-row contract (recorded artifacts produce audit rows when executed; classification informs which audit-row family applies — `CLI_*` for manual; `MIGRATION_*` for migrations; `DEPLOYMENT_*` for deploys; etc.)
- D92 forward-only schema evolution (additive entries to trackers; never edit/remove existing entries — supersession via new entry pointing back to predecessor)
- D15 idempotency mandatory (one-time scripts MUST be safe to re-run; classification verifies the docstring documents this)
- B-tracking discipline: substantive classification work surfaces as B-N in BACKLOG.md; cosmetic classification corrections as P-N in POLISH_QUEUE.md per D113

## Examples

### Example 1: B193 `migrations/lateness_columns.py` (just authored)
- **Axis 1**: Manual (operator runs `python migrations/lateness_columns.py --actor ... --server ...`)
- **Axis 2**: One-time per server (idempotent `IF NOT EXISTS` guards; runs once on each of dev / test / prod during R1b)
- **Route**: `ONE_OFF_SCRIPTS.md` → "Active items" → "Migration scripts" sub-table
- **Docstring verification**: ✅ idempotency documented + ✅ CLI trigger + ✅ "once per server" frequency + ✅ `MIGRATION_LATENESS_COLUMNS` audit row

### Example 2: B188 `tools/measure_lateness.py` (Tool 14 — when implementation lands)
- **Axis 1**: Scheduled (`JOB_LATENESS_MEASURE` weekly Automic job per phase1/04b § 6)
- **Axis 2**: Recurring (weekly)
- **Route**: `phase1/02_configuration.md` § 5.1 frozen-N inventory + Round 7 § 6.2 Automic schedule additions; NOT in `ONE_OFF_SCRIPTS.md`

### Example 3: B189 `tools/import_pii_inventory.py` (Tool 15 — when implementation lands)
- **Axis 1**: Manual (operator-driven CSV import per phase1/04b § 4)
- **Axis 2**: One-time per CSV (rare — possibly 1-3 times per source over project lifetime when compliance review surfaces new PII categories)
- **Route**: `ONE_OFF_SCRIPTS.md` → "Active items" → "One-time operator tools" sub-table

### Example 4: `cdc/reconciliation.py` (existing — partial classification)
- **Top-level reconciliation functions**: Manual + Recurring (ad-hoc) — operator runs when reconciliation drift detected → "Ad-hoc operator tools" sub-section in ONE_OFF_SCRIPTS.md
- **Scheduled wrappers** (if any): Scheduled + Recurring → `phase1/02_configuration.md` § 5.1 inventory
- **Note**: hybrid artifacts may have BOTH classifications recorded (one entry per wrapper)

### Example 5: R02 `_spike_round_0_5/` (deferred per user)
- **Axis 1**: Manual (engineer runs ad-hoc)
- **Axis 2**: One-time (throwaway code; archive after spike completes; no production deployment ever)
- **Route**: `ONE_OFF_SCRIPTS.md` → "Active items" → "Spike code" sub-table

### Example 6: Existing `migrations/b1_hash_varchar64.py` (already run)
- **Axis 1**: Manual
- **Axis 2**: One-time per server
- **Route**: `ONE_OFF_SCRIPTS.md` → "Completed items" → "Migration scripts already run" sub-table (✅ Run status)

## Hard rule

🟢 Lock status on any artifact (spec doc OR built code) WITHOUT a classification entry in `ONE_OFF_SCRIPTS.md` OR `phase1/02_configuration.md` § 5.1 is a status mismatch and must be corrected. Same severity as the existing "🟢 Locked WITHOUT `_validation_log.md` entry" hard rule per CLAUDE.md § Validation discipline.
