---
paths:
  - "**/*.py"
  - "**/*.sql"
  - "**/*.sql.j2"
  - "**/*.yaml"
  - "**/*.yml"
  - "**/*.ipynb"
  - "**/*.sh"
---

# SQL Query Agent Protocol Constraints

> **Note**: Code examples in this rule are deliberately omitted from the `.github/instructions/` mirror per the established repository convention for `.github/instructions/` mirrors. Do not "helpfully" sync them.

## Core Rule

**Never use `SELECT *`, alias wildcards (`SELECT t.*`, `SELECT users.*`), or `RETURNING *` in committed code.** Every query — whether embedded in Python, raw SQL, dbt models, Alembic migrations, or ad-hoc test fixtures — MUST enumerate the exact columns it consumes. Alias wildcards and `RETURNING *` suffer the same schema drift vulnerability as `SELECT *` and are easy evasion paths around this rule.

## Rationale

1. **Schema drift resistance.** A `SELECT *` query changes shape silently when a column is added or reordered. Downstream consumers that expect a specific row width, column order, or key set break without warning. An explicit column list makes the contract compile-time visible.
2. **Review legibility.** A reviewer can answer "which columns does this code path read?" without opening the table schema. This shortens review cycles and reduces the chance that a dependent mutation is missed.
3. **Projection narrowing.** Dashboards, HTTP handlers, and serializers rarely need every column on a row. An explicit list documents the minimum projection and surfaces over-fetching during review.
4. **Performance — secondary but real.** Narrow projections reduce bytes on the wire, page cache pressure, and serialization cost. This matters for hot-path queries but is not the primary driver of this rule.
5. **Test stability.** Tests that assert dict equality on a `SELECT *` result fail whenever a column is added to the source table, even when the test's intent is unaffected.

## Scope

This rule applies to all SQL in the repository, regardless of the dialect (SQLite, MySQL, Redshift, Postgres, Snowflake), the embedding (raw string, SQLAlchemy Core/ORM, dbt Jinja, Alembic op.execute), or the file type (`.py`, `.sql`, dbt `.sql.j2`, Alembic migration, YAML config).

A single constant holding the canonical column list is preferred over repeating the literal list at each call site. Example:

```python
_TODOS_COLUMNS_SQL = (
    "id, title, description, context_snapshot, category, "
    "secondary_categories, priority, epic_id, source_workspace, "
    "status, resolution, created_at, last_updated_at"
)

def get_todo(db: sqlite3.Connection, todo_id: int) -> dict[str, Any] | None:
    row = db.execute(
        f"SELECT {_TODOS_COLUMNS_SQL} FROM todos WHERE id = ?",
        (todo_id,),
    ).fetchone()
    return dict(row) if row else None
```

## Exceptions

The following forms are NOT `SELECT *` violations under this rule:

1. **`COUNT(*)`** — aggregates over the full row count, not a column projection.
2. **`EXISTS(SELECT 1 FROM ...)`** — the `1` is a sentinel, not a column projection.
3. **Ad-hoc exploratory queries in Jupyter notebooks or one-off SQL scratch files** — permitted for exploration but MUST be narrowed before the file is committed to the repository. This applies equally to notebook cells, scratch SQL files, and any other tracked file — no file type is exempt from the rule once it is committed.
4. **Pure DDL statements** such as `CREATE TABLE AS SELECT` during a schema migration where the target table is explicitly defined to mirror the source. The migration author MUST document the assumption via an inline comment in the format `-- mirrors schema of <source_table> as of YYYY-MM-DD`, where the date is the migration authorship date. The date-bound form makes stale assumptions visible on schema drift.

No other exceptions. In particular, `SELECT *` is NOT acceptable for "this code owns the table and will always use every column" — the next maintainer may not share that assumption, and the schema may outgrow it.

## Enforcement Guidance

- **Code review**: reviewers MUST flag any `SELECT *` in a diff and require the author to replace it with an explicit column list or cite a named exception.
- **Grep check**: a repository-wide ripgrep (`rg -U -i '(select|returning)\s+([a-zA-Z0-9_]+\.)?\*' -g '*.{py,sql,sql.j2,yaml,yml,ipynb,sh}'`) is a useful pre-PR self-check. The `-U` flag enables multiline matching (common auto-formatted `SELECT\n  *\nFROM`); the regex also catches alias wildcards (`SELECT t.*`) and `RETURNING *`. **Note**: this regex catches wildcards that immediately follow `SELECT`/`RETURNING`; non-initial wildcards in multi-column lists (e.g., `SELECT a, b, t.*`) require manual review or a proper SQL parser — the rule forbids them regardless. The grep is not a CI gate today; see the Future Work note below.
- **New code**: any new query MUST be written with explicit columns from the start. Do not introduce a `SELECT *` with the intention to narrow it later.
- **Legacy code (Boy Scout rule)**: when modifying a function that contains a `SELECT *`, narrow it as part of the modification — do not leave the violation in place.

## Future Work

A CI lint gate to enforce this rule mechanically is not yet implemented. Until it exists, this rule relies on reviewer diligence and the grep check above (with its stated limitations). When a CI gate is built, the recommended approach is:

- **`sqlfluff`** for standalone `.sql`, dbt `.sql.j2`, and Alembic migration files — proper dialect-aware parser; rule `AM04` (`ambiguous.column_count`, alias `L044`) already covers `SELECT *` and alias wildcards.
- **`sqlglot`-based custom check** for SQL embedded in Python string literals — extract strings via the `ast` module, parse with `sqlglot`, flag wildcard projections. This is the most accurate option for this codebase because most of our SQL lives inside Python modules (e.g., `chromadb_ledger.py`, `todo_cli.py`).
- **`semgrep`** as a lower-accuracy fallback — pattern-matches literal SQL strings in Python source but misses f-strings and concatenated queries.

Follow-up work is tracked in `TODO-0058`.
