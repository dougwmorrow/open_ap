---
name: udm-post-build-verify
description: Runs QA + unit + regression pytest verification (Tier 0 + Tier 1) after authoring or modifying executable code. Invoke after any Pattern B1/B2 build cycle Wave 3 inline fixes land. Identifies the just-built artifact's test files, runs pytest with verbose output + short tracebacks, runs regression set (Tier 0 + Tier 1 for any module importing the changed module), reports PASS/FAIL with specific failure details. Required precondition — project venv active with pytest + project dependencies installed via `uv venv` + `uv pip install` (project uses `uv` exclusively per user-direction 2026-05-12; do NOT use `pip` directly). NOT for Tier 2+ integration tests requiring live infrastructure (Docker, RHEL servers — those run in CI).
---

# UDM Post-Build Verify

Runs QA + unit + regression tests after authoring or modifying executable code. Invoke after Pattern B1/B2 cycle Wave 3 inline fixes complete to verify the build before marking the unit 🟢 Build complete in `ONE_OFF_SCRIPTS.md` (per `udm-execution-classifier` discipline) or before flipping any 🟢 status flag in `BACKLOG.md` for a B-N closing on built code.

## When to invoke

- After any Pattern B1 or B2 build cycle Wave 3 inline fixes land (or Wave 2 returns clean if no Wave 3 needed)
- Before flipping a build-unit status to 🟢 Build complete in `ONE_OFF_SCRIPTS.md`
- After ANY code edit to an existing module (verify no regression on the touched module's tests AND any module importing it)
- During engineer-side validation prior to deployment

## When NOT to invoke

- For spec-doc edits (no executable code; skill scope is code-only)
- For runbook edits (documentation; no test surface)
- For Tier 2+ tests requiring live infrastructure (Docker / RHEL servers; those run in CI per `phase1/05_tests.md` § Tier 2-5)
- When project venv is not active OR pytest is not installed — fix venv FIRST per `uv` conventions (see § Preconditions)

## Preconditions

1. Project venv exists at `.venv/` at repo root (per `uv venv` setup)
2. Project dependencies installed via `uv pip install --python .venv/Scripts/python.exe pytest polars polars-hash connectorx oracledb pyodbc` (Windows) OR equivalent Linux/macOS path
3. `pytest` installed in the venv
4. Working directory = project root (so `tests/` is discoverable + `sys.path` includes module dirs)

If preconditions are NOT met, the skill cannot proceed. Surface the missing precondition + how to fix per `uv` conventions (NOT `pip` — project uses `uv` exclusively for venv + package management per user-direction 2026-05-12).

## CCL per D62

- **Stage 0**: `docs/migration/INDEX.md` (routing manifest; recommended-not-mandatory; added 2026-05-15 per D62 amendment + D.2 INDEX.md per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.3; read FIRST when uncertain which downstream Stage 1+2+3 docs your task needs; skip when you already know).
- **Stage 1** (mandatory, 4 reads): `NORTH_STAR.md`, `HANDOFF.md`, `CURRENT_STATE.md`, `CHECKS_AND_BALANCES.md`
- **Stage 2** (mandatory): `RISKS.md`, `BACKLOG.md`, `_validation_log.md`
- **Stage 3** (task-specific): `phase1/05_tests.md` (testing discipline — Tier 0 + Tier 1 sections; D67 + D77 canonical assertions); the just-built artifact + its corresponding `tests/tier0/test_<name>.py` + `tests/tier1/test_<name>.py`
- **Stage 4**: grep for upstream consumers of the changed module (regression-set determination)

## Procedure

### Step 1 — QA pass (syntax + import)

```bash
.venv/Scripts/python.exe -c "import ast; ast.parse(open('<artifact_path>').read()); print('SYNTAX_OK')"
```

If syntax fails → HALT + report the syntax error. No further steps run.

### Step 2 — Identify test files

For artifact at `<module_path>/<name>.py`:
- Tier 0 test: `tests/tier0/test_<name>.py`
- Tier 1 test: `tests/tier1/test_<name>.py`

If either is missing → 🟡 ADVISORY (test author may not have written that tier; if Tier 0 missing, this is BLOCKING for build-complete state per D67).

### Step 3 — Run Tier 0 smoke

```bash
.venv/Scripts/python.exe -m pytest tests/tier0/test_<name>.py -v --tb=short --no-header
```

**Acceptance**: all tests PASS; total runtime < 5s per D67. Tier 0 with FAIL → 🔴 BLOCKING.

### Step 4 — Run Tier 1 unit

```bash
.venv/Scripts/python.exe -m pytest tests/tier1/test_<name>.py -v --tb=short --no-header
```

**Acceptance**: all tests PASS; runtime typically < 30s. Tier 1 with FAIL → 🔴 BLOCKING.

### Step 5 — Run regression set

Identify modules importing the changed module:
```bash
grep -rn "from <module_relative_path> import\|import <module_relative_path>" --include="*.py" .
```

For each upstream consumer module, find its test files + run Tier 0 + Tier 1:
```bash
.venv/Scripts/python.exe -m pytest tests/tier0/test_<consumer>.py tests/tier1/test_<consumer>.py -v --tb=short
```

**Acceptance**: all regression tests PASS (no breakage on upstream consumers).

For NEW modules with no consumers yet (e.g., a fresh migration script for a feature not yet wired up), skip Step 5 with note "no upstream consumers; regression N/A".

### Step 6 — Report

Format the output per the Output section below. Always include the verdict line.

## Output

```
# Post-build verify — <artifact_path>

## QA pass (Step 1)
✅ syntax OK
(OR ❌ syntax FAIL: <error excerpt>)

## Test file presence (Step 2)
✅ Tier 0 + Tier 1 both present
(OR 🟡 Tier 0 missing | 🟡 Tier 1 missing | 🔴 Both missing)

## Tier 0 smoke (Step 3)
✅ N tests PASS in T seconds
(OR ❌ N tests FAIL:
- test_<name>: <error excerpt first 5 lines>)

## Tier 1 unit (Step 4)
✅ N tests PASS in T seconds
(OR ❌ N tests FAIL:
- test_<name>: <error excerpt>)

## Regression set (Step 5)
- <upstream_module_1>: ✅ N PASS / ❌ M FAIL
- <upstream_module_2>: ✅
- ...
(OR "No upstream consumers detected; regression N/A")

## Verdict
🟢 PASS: <artifact> ready for 🟢 Build complete state
🟡 PARTIAL: <details — what's missing or advisory-class>
🔴 FAIL: <details — what's blocking>

## Next action
- If PASS: update ONE_OFF_SCRIPTS.md to 🟢 Build complete; commit; cascade per udm-execution-classifier
- If FAIL: surface failures to author agent for iteration via Pattern B1 Wave 3 inline fix
```

## One-time uv setup (per workstation)

If venv doesn't exist OR if `uv` itself is missing:

### Install uv (one-time per workstation)

```powershell
# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
# OR bootstrap via existing pip (acceptable one-time):
python -m pip install uv
```

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Create venv + install deps (per project clone)

```bash
# From project root:
uv venv .venv
# Activate (optional; uv commands work without activation):
.\.venv\Scripts\activate   # Windows
source .venv/bin/activate  # macOS / Linux

# Install pipeline + test dependencies (use uv pip, NOT regular pip):
uv pip install --python .venv/Scripts/python.exe pytest polars polars-hash connectorx oracledb pyodbc

# Verify:
.venv/Scripts/python.exe -m pytest --version
```

**Do NOT use `pip install` directly** — project uses `uv` exclusively for venv + package management per user-direction 2026-05-12. The one acceptable `pip` usage is bootstrapping `uv` itself via `python -m pip install uv` if `uv`'s install script can't run (corporate proxy / firewall).

## Anti-patterns

- ❌ Running pytest without venv activated (uses system Python; wrong package versions)
- ❌ Using `pip install` after the venv is bootstrapped (defeats venv consistency)
- ❌ Skipping Step 5 regression set on edits to existing modules (silent breakage on upstream consumers)
- ❌ Declaring 🟢 Build complete in `ONE_OFF_SCRIPTS.md` without running this skill (Hard rule per `udm-execution-classifier` SKILL.md analogue — same severity as missing `_validation_log.md` entry)
- ❌ Invoking this skill on spec-doc edits (no test surface; wastes cycles)
- ❌ Marking Tier 0 PASS if runtime > 5s (violates D67 build-time-smoke contract)

## Related skills / agents

- `udm-test-author` — produces the Tier 0 + Tier 1 test files this skill executes (Pattern B1/B2 Wave 1 parallel-author)
- `udm-design-reviewer` — Pattern B1/B2 Wave 2; reviews code + tests BEFORE this skill runs
- `udm-execution-classifier` — classifies the built artifact AFTER this skill confirms PASS; routes to `ONE_OFF_SCRIPTS.md` OR `phase1/02_configuration.md` § 5.1
- `udm-round-closeout` — invokes this skill on every code change in the closing round (extends close-out checklist with post-build verification step)
- `udm-checks-and-balances` — Gate 4 (edge case validation) + Gate 5 (idempotency / regression) at spec doc level; this skill is the code-level analog at the test-execution level

## Decision citations

- D67 (Tier 0 build-time smoke; canonical 6 assertions; <5s runtime)
- D77 (Tier 0 scaffold pattern — 6 assertions)
- D15 (idempotency mandatory — regression set verifies)
- D55 5-gate validation Gate 4 (edge case validation at test level) + Gate 5 (idempotency / regression)
- D56 mandatory second-pass after 🔴 (this skill's 🔴 output triggers Wave 3 author-rework cycle)
- D74 (CLI exit-code contract — pytest exit codes 0 / 1 map to PASS / FAIL)
- D92 (forward-only — when an existing module is modified, regression set is mandatory per D92 spirit: additive changes must not break upstream consumers)

## Examples

### Example 1: B193 build verify
- Artifact: `migrations/lateness_columns.py`
- Tier 0: `tests/tier0/test_lateness_columns.py` (6 tests)
- Tier 1: `tests/tier1/test_lateness_columns.py` (10 tests post-B202 inline fix)
- Regression: no upstream consumers yet (Tool 14 `measure_lateness.py` would import this when built; not present yet)
- Expected: ✅ PASS; runtime < 5s Tier 0 + < 30s Tier 1

### Example 2: B194 build verify (post-cycle-1-fixes)
- Artifact: `migrations/pii_inventory_audit_log.py`
- Tier 0: 6 tests
- Tier 1: 14 tests (post-B204 + B205 inline fixes)
- Regression: no upstream consumers yet (Tool 15 `import_pii_inventory.py` would import this when built)
- Expected: ✅ PASS; FIRST_APPLY_DDL_COUNT = 2 assertions now match implementation

### Example 3: Edit to existing `data_load/bcp_csv.py` (regression scenario)
- Artifact: `data_load/bcp_csv.py` (existing module; modified)
- Tier 0: `tests/tier0/test_bcp_csv.py` (if exists)
- Tier 1: `tests/tier1/test_bcp_csv.py` (if exists)
- Regression: grep finds `cdc/engine.py`, `scd2/engine.py`, `extract/connectorx_oracle_extractor.py` all import bcp_csv → run their test files
- Expected: ✅ PASS on all 4 modules' test files OR 🔴 if regression caught

## Hard rule

🟢 Build complete status on any code artifact WITHOUT this skill's PASS verdict in operator notes OR validation log is a status mismatch — same severity as the existing "🟢 Locked WITHOUT `_validation_log.md` entry" hard rule per CLAUDE.md § Validation discipline bullets 7 + 8.

## Integration with udm-execution-classifier

Workflow at Pattern B1/B2 build-cycle completion:
1. Wave 1 (author + test-author) returns
2. Wave 2 (design-reviewer) returns; iterate Wave 3 inline fixes if needed
3. **Invoke `udm-post-build-verify`** ← THIS SKILL
4. If PASS → invoke `udm-execution-classifier` to record entry in `ONE_OFF_SCRIPTS.md` OR `phase1/02_configuration.md` § 5.1
5. If PASS → flip `BACKLOG.md` B-N status to 🟢 Build complete
6. Engineer commits + deploys to dev/test/prod RHEL per D86 cadence
