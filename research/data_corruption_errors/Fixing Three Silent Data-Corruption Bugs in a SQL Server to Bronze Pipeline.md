Date: March 5, 2026
# Fixing three silent data-corruption bugs in a SQL Server to Bronze pipeline

All three issues trace to a common theme: **schema assumptions that break at the boundary between systems**. The NULL PK violation stems from treating a nullable unique index as a primary key during discovery. The ConnectorX panic is a known, unfixed gap in its SQL Server type system. The NULL inflation and dtype drift originate from concatenating DataFrames sourced from different persistence layers without schema normalization. Each has a clean, targeted fix.

---

## A nullable column is never a valid primary key

SQL Server's behavior with NULLs in unique indexes departs from the ANSI SQL standard in a critical way. While ANSI permits multiple NULLs in a unique column (since NULL ≠ NULL), **SQL Server treats NULL as a value for uniqueness enforcement — only one NULL row is allowed per unique index column**. This is precisely why the BCP load into the Bronze layer fails: the filtered unique index `UX_Active_{table} WHERE UdmActiveFlag=1` encounters a second row where the discovered "PK" column is NULL within the filtered subset, triggering the duplicate key violation `(NULL)`.

The root cause chain is straightforward. The `_discover_sqlserver_pks()` function finds no actual primary key on `CCM.BankruptcyType`, falls back to a unique index, and accepts its key column without checking nullability. That column contains NULLs in the source data. When multiple rows with `UdmActiveFlag=1` and a NULL key value hit the filtered unique index, SQL Server correctly rejects the duplicates. **A column that allows NULLs should never be accepted as a primary key surrogate** — SQL Server itself refuses to create a PRIMARY KEY constraint on a nullable column (Msg 8111).

The fix belongs inside `_discover_sqlserver_pks()`, not in a separate validation step. The fail-fast principle applies: if an invalid PK candidate escapes discovery, every downstream consumer — BCP load, index creation, deduplication — inherits the defect. The validation query should join `sys.index_columns` with `sys.columns` and reject any unique index where a key column has `is_nullable = 1`:

```sql
SELECT i.name AS index_name, i.index_id
FROM sys.tables t
JOIN sys.indexes i ON t.object_id = i.object_id
WHERE i.is_unique = 1 AND i.is_disabled = 0 AND i.has_filter = 0
  AND NOT EXISTS (
      SELECT 1 FROM sys.index_columns ic
      JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
      WHERE ic.object_id = i.object_id AND ic.index_id = i.index_id
        AND ic.is_included_column = 0 AND c.is_nullable = 1
  )
ORDER BY CASE WHEN i.is_primary_key = 1 THEN 0 ELSE 1 END, i.index_id;
```

The discovery priority should be: (1) `is_primary_key = 1` — always valid since SQL Server enforces NOT NULL; (2) `is_unique_constraint = 1` with all key columns NOT NULL and `has_filter = 0`; (3) `is_unique = 1` with the same NOT NULL and non-filtered checks; (4) if none found, log an error and flag the table for manual intervention rather than proceeding with a nullable surrogate. A lightweight post-discovery assertion provides belt-and-suspenders safety.

---

## ConnectorX will never parse XML — cast it away at the source

**ConnectorX has no XML type support for SQL Server, and no PR or version adds it.** The panic at `typesystem.rs:99` hits a Rust `unimplemented!()` macro — the same pattern seen with `MYSQL_TYPE_DECIMAL` (issue #404), `MYSQL_TYPE_TINY` (#115), and PostgreSQL `_jsonb` (#121). The official ConnectorX MSSQL type mapping lists 23 supported types; XML is absent. The maintainers' standard advice for unsupported types is to CAST in the SQL query.

The workaround is to replace `SELECT *` with an explicit SELECT that wraps XML columns in `CAST([col] AS NVARCHAR(MAX)) AS [col]`. This approach preserves all XML data content — element names, text content, attribute values, and namespace URIs — with only cosmetic serialization differences. **Insignificant whitespace, attribute ordering, namespace prefixes, and the XML declaration may change**, but these are InfoSet-equivalent transformations, not data loss. Both XML and NVARCHAR(MAX) share a **2 GB** per-value storage ceiling, so no truncation occurs.

The implementation mirrors the existing E-4 pattern in `connectorx_oracle_extractor.py`. First, query metadata to identify problematic columns:

```sql
SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = @schema AND TABLE_NAME = @table AND DATA_TYPE = 'xml'
```

Then build the explicit SELECT dynamically:

```python
def _build_safe_select(all_cols: list[str], xml_cols: set[str], schema: str, table: str) -> str:
    parts = [
        f"CAST([{c}] AS NVARCHAR(MAX)) AS [{c}]" if c in xml_cols else f"[{c}]"
        for c in all_cols
    ]
    return f"SELECT {', '.join(parts)} FROM [{schema}].[{table}]"
```

ConnectorX's `read_sql` accepts arbitrary SQL via the `query` parameter — it is designed for queries, not table names. The function wraps user-provided SQL internally for schema detection (`TOP 1`) and row counting (`COUNT(*)`), so standard SELECT statements with CAST, JOINs, and subqueries work without issues. This fix should be triggered conditionally: query metadata once per table, and only build the explicit SELECT when XML columns exist, falling through to `SELECT *` otherwise. This keeps the hot path unchanged and confines the workaround to the ~2 affected tables (`MsgAccount`, `MsgAccountCache`).

---

## Schema divergence between Bronze persistence and fresh extraction causes NULL inflation

The P0-7 NULL inflation and C-3 dtype drift share a single root cause: **`unchanged_existing` is read from the persisted Bronze table, while `df_insert_cdc` and `df_update_cdc` derive from the current extraction, and their schemas have diverged.** The three DataFrames do not come from the same source — they come from different persistence layers at different points in time. When `_safe_concat` encounters a column present in `unchanged_existing` but absent from a CDC frame (or vice versa), it fills the gap with `pl.lit(None)`, injecting thousands of NULLs. That is the P0-7 signal.

The dtype drift (C-3) follows from the same divergence. Boolean-like columns like `IsMaster` may be stored as **Int8** in the Bronze Parquet/Delta files but arrive as **Int64** or **Boolean** from a fresh SQL Server extraction. When `_resolve_common_dtype` encounters Int8 + Int64, Polars' supertype resolution correctly widens to Int64 — this is mathematically sound but semantically wrong for a Boolean column.

There is a deeper bug in `_safe_concat` itself: **`pl.lit(None)` creates a column with Polars' `Null` data type, not a typed null**. This `Null` type is a distinct bottom type in Polars' type lattice. When concatenated with a `String` column via supertype resolution, it resolves to `String` (which works), but the untyped null creates fragile intermediate states and can trigger errors with strict `vstack` or complex types.

### The fix: schema normalization before concat

The correct architecture eliminates `_safe_concat` entirely in favor of explicit schema conformance. Define a canonical target schema once — including all business columns and CDC metadata columns with exact types — then conform all three DataFrames to it before concatenation:

```python
def conform_to_schema(df: pl.DataFrame, schema: dict[str, pl.DataType]) -> pl.DataFrame:
    expressions = []
    for col_name, col_dtype in schema.items():
        if col_name in df.columns:
            expressions.append(pl.col(col_name).cast(col_dtype))
        else:
            expressions.append(pl.lit(None, dtype=col_dtype).alias(col_name))
    return df.select(expressions)

# Derive target schema from source extraction + CDC column definitions
target_schema = {**source_schema, **cdc_schema}  # e.g., {"IsMaster": pl.Int8, ...}

dfs = [conform_to_schema(df, target_schema)
       for df in [unchanged_existing, df_insert_cdc, df_update_cdc]]
result = pl.concat(dfs, how="vertical")  # strict concat is safe post-conformance
```

The key differences from the current approach are threefold. First, **`pl.lit(None, dtype=pl.String)`** creates properly typed nulls instead of untyped `Null` columns. Second, **explicit casting** (e.g., `IsMaster` → `Int8`) prevents supertype widening. Third, **`pl.concat(how="vertical")`** with strict matching catches any remaining schema misalignment as an error rather than silently promoting types.

### Alternative: Polars' built-in `diagonal_relaxed`

Polars provides `pl.concat(how="diagonal_relaxed")` which handles both missing columns and dtype mismatches natively. It fills missing columns with typed nulls and coerces overlapping columns to supertypes. This is simpler than a custom `_safe_concat` but **still widens Int8 → Int64** if not pre-cast. It is best used as a fallback, not a primary strategy, since it trades control for convenience.

Recent Polars versions also offer `DataFrame.match_to_schema()`, the official solution for exactly this problem. It reorders columns, inserts typed nulls for missing columns, and supports controlled upcasting — though it is currently marked as unstable.

### Ensuring `_add_cdc_columns` produces identical schemas

The CDC column addition step should use a shared schema definition:

```python
CDC_SCHEMA = {
    "_cdc_valid_from": pl.Datetime("us"),
    "_cdc_batch_id": pl.Int64,
    "_cdc_operation": pl.String,
    "UdmActiveFlag": pl.Int8,
}

def _add_cdc_columns(df: pl.DataFrame, operation: str, batch_id: int, valid_from) -> pl.DataFrame:
    return df.with_columns(
        pl.lit(valid_from).cast(pl.Datetime("us")).alias("_cdc_valid_from"),
        pl.lit(batch_id).cast(pl.Int64).alias("_cdc_batch_id"),
        pl.lit(operation).cast(pl.String).alias("_cdc_operation"),
        pl.lit(1).cast(pl.Int8).alias("UdmActiveFlag"),
    )
```

By casting each CDC literal to its canonical type at the point of creation, all three code paths — insert, update, unchanged — produce identical CDC column types regardless of Polars' literal inference.

---

## Conclusion

These three bugs expose a pattern common in data pipelines that span multiple systems: **implicit schema assumptions silently fail when schemas diverge across persistence boundaries**. The nullable PK bug is fixed by adding a `sys.columns.is_nullable` check inside `_discover_sqlserver_pks()` — a four-line SQL subquery that eliminates an entire class of downstream failures. The ConnectorX XML panic is an upstream limitation with no planned fix; the CAST-to-NVARCHAR(MAX) workaround is data-safe and follows the pipeline's existing Oracle extractor pattern. The NULL inflation and dtype drift are symptoms of concatenating DataFrames from different persistence eras without schema normalization; replacing `_safe_concat` with explicit `conform_to_schema()` and strict `pl.concat(how="vertical")` eliminates both problems at once and removes the `pl.lit(None)` untyped-null antipattern.

The unifying lesson: **validate schemas at every system boundary, and never let type inference substitute for explicit type declarations in production pipelines.**