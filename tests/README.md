# CDC Test Suite

Validation, regression, and UAT tests for the UDM CDC pipeline.

## Layout

| Directory | What runs there | DB needed? |
|---|---|---|
| `tests/unit/` | Pure-Polars tests for individual CDC primitives (hashing, NULL PK filter, dedup, change detection, CDC column shape). Fast, no I/O. | No |
| `tests/regression/` | Tests that reproduce specific incidents and document expected behavior. Pure Polars. | No |
| `tests/uat/` | Live SQL Server tests against the real Stage and Bronze tables. Surface drift, multi-current rows, mass-resurrection patterns. | Yes |

## Running

```bash
# Everything that doesn't need a DB
python3 -m pytest tests/ -v --log-cli-level=INFO

# Just the unit tests
python3 -m pytest tests/unit/ -v --log-cli-level=INFO

# Regression tests with full debug
python3 -m pytest tests/regression/ -v --log-cli-level=DEBUG

# UAT against the live environment (.env at /debi/.env)
CDC_UAT_ENABLED=1 python3 -m pytest tests/uat/ -v --log-cli-level=INFO

# Single test
python3 -m pytest tests/regression/test_resurrection_pattern.py::test_pk_resurrection_emits_insert -v --log-cli-level=INFO
```

UAT tests are auto-skipped unless `CDC_UAT_ENABLED=1` is exported. This
keeps the unit suite runnable from a dev workstation that has no SQL
Server access.

## Reading test output

Every test logs:

* **Setup** — what the synthetic input looked like (PK columns, row count, hash values)
* **Action** — which CDC function was invoked and with what shape of input
* **Expectation** — what the invariant under test guarantees
* **Result** — the observed counts / classifications, alongside the expected ones

When a test fails, the surrounding INFO log gives you the input + invariant + actual outcome without re-running with `pdb`.

## What's covered

### `tests/unit/test_hash_determinism.py`

* Same input, same hash — across two `add_row_hash()` calls
* Different input, different hash
* IEEE 754 normalization (W-3): NaN, ±Inf, ±0 all stable
* NULL sentinel uses `\x1F` not `\x00` (W-2)
* Categorical columns hash by logical value, not physical encoding (E-20)
* `exclude_from_hash` honors the column list (SCD2-R10.2)
* Oracle empty-string normalization (E-1)
* RTRIM applied to all string columns (E-4)

### `tests/unit/test_pk_filtering.py`

* P0-4: rows with NULL in any PK column are dropped before CDC
* P0-4b: empty-string PK values coerced to `<BLANK>` sentinel
* `null_pk_rows` count tracked on `CDCResult`

### `tests/unit/test_change_detection.py`

* All-insert path (empty `df_existing`)
* All-update path (PK matches, hash differs)
* All-unchanged path (PK matches, hash matches)
* All-delete path (PK in existing, missing from fresh)
* Mixed scenario with all four classes
* P0-12 count invariant: `inserts + updates + unchanged == len(df_fresh)`

### `tests/unit/test_cdc_columns.py`

* `_add_cdc_columns()` adds the six required columns
* `_cdc_is_current` is `Int8` (BCP requirement — never Boolean)
* `_cdc_operation` carries the supplied label verbatim

### `tests/regression/test_resurrection_pattern.py`

The original bug report: `ACCT.ACCTNBR=205` shows alternating `I` and `U`
in `_cdc_operation` rather than a single `I` followed by `U`s. These tests
**document the engine's by-design behavior** so the user can decide whether
the observed pattern indicates an upstream issue (source flapping) or a
genuine engine bug.

* A PK that is closed (delete detection or windowed close) and then
  reappears in source extraction is classified as `I` again — the engine
  has no concept of "previously seen this PK" once it's no longer current.
  Resurrection-as-`R` lives in SCD2/Bronze, not in Stage.
* For a PK that is **continuously present in source**, the only `I` row
  is the very first; every subsequent change is `U`.
* For a PK that **flaps in/out of source extraction**, every reappearance
  produces a new `I` row. This is what the user is observing for `ACCT 205`.

### `tests/uat/test_stage_invariants.py`

DB-backed checks against the live Stage table. Pinpoints whether the user's
observation for `ACCTNBR=205` is a one-off (suggests source flapping or
extraction gap) or a systematic pipeline issue.

* No PK has more than one `_cdc_is_current=1` row (single-current invariant)
* For each PK, `_cdc_valid_from` strictly increases across rows
* List the top-N PKs by `I`-row count — if `ACCTNBR=205` is alone,
  it's an isolated source flap; if many PKs follow the same pattern,
  the extraction itself is intermittent
* Look for PKs whose latest row is `_cdc_operation='D'` AND
  `_cdc_is_current=1` (should never happen — `D` means closed)

## Adding new tests

1. Pick the right directory:
   * Pure logic test, no DB → `unit/`
   * Reproduces a specific reported incident → `regression/`
   * Needs Stage/Bronze SQL Server connection → `uat/` (and add `pytestmark = pytest.mark.uat` at the top)
2. Use `make_table_config` from `conftest.py` for synthetic `TableConfig` objects.
3. Log at INFO level: input shape, invariant, expected vs actual.
4. Keep one logical assertion per test — easier to read failures.
