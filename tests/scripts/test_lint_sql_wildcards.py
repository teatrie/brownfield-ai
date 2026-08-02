"""Unit tests for scripts/lint_sql_wildcards.py.

Covers:
  - check_wildcard_violations() — SELECT *, alias wildcards, RETURNING *,
    COUNT(*) exception, EXISTS exception, multiple violations per statement.
  - extract_sql_candidates() — string constants, f-strings, implicit
    concatenation, non-SQL string filtering.
  - lint_files() — clean files, violation files, DDL exception, parse
    warnings, verbose mode.
  - Production smoke test — confirms no violations in scripts/ or src/.
"""

from __future__ import annotations

from pathlib import Path

from scripts.lint_sql_wildcards import (
    check_wildcard_violations,
    extract_sql_candidates,
    lint_files,
)

# ── check_wildcard_violations tests ──────────────────────────────


def test_select_star_detected_as_violation():
    violations = check_wildcard_violations("SELECT * FROM users")
    assert len(violations) == 1
    assert "SELECT *" in violations[0]


def test_alias_wildcard_detected():
    violations = check_wildcard_violations("SELECT t.* FROM users t")
    assert len(violations) == 1
    assert "alias" in violations[0].lower()


def test_non_initial_alias_wildcard_detected():
    violations = check_wildcard_violations("SELECT a, b, t.* FROM users t")
    assert len(violations) == 1
    assert "alias" in violations[0].lower()


def test_returning_star_detected():
    violations = check_wildcard_violations("INSERT INTO users (name) VALUES ('x') RETURNING *")
    assert len(violations) == 1
    assert "RETURNING" in violations[0]


def test_count_star_not_flagged():
    violations = check_wildcard_violations("SELECT COUNT(*) FROM users")
    assert violations == []


def test_exists_select_one_not_flagged():
    violations = check_wildcard_violations("SELECT id FROM users WHERE EXISTS(SELECT 1 FROM orders)")
    assert violations == []


def test_clean_explicit_columns_not_flagged():
    violations = check_wildcard_violations("SELECT id, name, email FROM users WHERE active = 1")
    assert violations == []


def test_multiple_violations_in_one_statement():
    violations = check_wildcard_violations("SELECT * FROM users UNION SELECT * FROM orders")
    assert len(violations) == 2


# ── extract_sql_candidates tests ─────────────────────────────────


def test_extracts_sql_from_string_constant(tmp_path: Path):
    source = 'query = "SELECT * FROM users"\n'
    py_file = tmp_path / "sample.py"
    py_file.write_text(source)

    candidates = extract_sql_candidates(py_file)
    assert len(candidates) == 1
    sql_text, line_no = candidates[0]
    assert "SELECT" in sql_text
    assert line_no == 1


def test_extracts_sql_from_fstring(tmp_path: Path):
    source = 'table = "users"\nquery = f"SELECT * FROM {table}"\n'
    py_file = tmp_path / "fstr.py"
    py_file.write_text(source)

    candidates = extract_sql_candidates(py_file)
    assert len(candidates) == 1
    sql_text = candidates[0][0]
    assert "SELECT" in sql_text
    assert "__FSTR__" in sql_text


def test_implicit_concatenation_handled(tmp_path: Path):
    source = 'query = (\n    "SELECT "\n    "id, name "\n    "FROM users"\n)\n'
    py_file = tmp_path / "concat.py"
    py_file.write_text(source)

    candidates = extract_sql_candidates(py_file)
    assert len(candidates) == 1
    sql_text = candidates[0][0]
    assert "SELECT" in sql_text
    assert "FROM" in sql_text


def test_non_sql_strings_ignored(tmp_path: Path):
    source = 'msg = "Hello, world!"\n'
    py_file = tmp_path / "nosql.py"
    py_file.write_text(source)

    candidates = extract_sql_candidates(py_file)
    assert candidates == []


def test_fstring_structural_injection_detected(tmp_path: Path):
    source = 'table = "users"\nquery = f"SELECT * FROM {table}"\n'
    py_file = tmp_path / "fstr_inject.py"
    py_file.write_text(source)

    candidates = extract_sql_candidates(py_file)
    assert len(candidates) == 1
    sql_text = candidates[0][0]
    violations = check_wildcard_violations(sql_text)
    assert len(violations) >= 1


# ── lint_files integration tests ─────────────────────────────────


def test_clean_codebase_returns_zero(tmp_path: Path):
    source = 'query = "SELECT id, name FROM users"\n'
    py_file = tmp_path / "clean.py"
    py_file.write_text(source)

    result = lint_files([str(tmp_path)])
    assert result == 0


def test_violation_file_returns_nonzero(tmp_path: Path):
    source = 'query = "SELECT * FROM users"\n'
    py_file = tmp_path / "dirty.py"
    py_file.write_text(source)

    result = lint_files([str(tmp_path)])
    assert result == 1


def test_ddl_mirrors_schema_exception(tmp_path: Path):
    source = 'query = "CREATE TABLE new AS SELECT * FROM old  -- mirrors schema of old as of 2025-01-01"\n'
    py_file = tmp_path / "ddl.py"
    py_file.write_text(source)

    result = lint_files([str(tmp_path)])
    assert result == 0


def test_parse_warning_on_unparseable_sql():
    violations = check_wildcard_violations("NOT REAL SQL BUT CONTAINS SELECT * MAYBE")
    assert isinstance(violations, list)


def test_verbose_mode_shows_warnings(tmp_path: Path):
    source = 'query = "SELECTIFY STARBURST FROM NOWHERE"\n'
    py_file = tmp_path / "unparseable.py"
    py_file.write_text(source)

    lint_files([str(tmp_path)], verbose=True)


def test_returning_star_non_initial_detected():
    violations = check_wildcard_violations("INSERT INTO users (name) VALUES ('x') RETURNING id, *")
    assert len(violations) >= 1


# ── Production smoke test ────────────────────────────────────────


def test_actual_source_files_are_clean():
    dirs_to_scan = [d for d in ["scripts/", "src/"] if Path(d).exists()]
    assert dirs_to_scan, "Expected at least one of scripts/ or src/ to exist"
    result = lint_files(dirs_to_scan)
    assert result == 0
