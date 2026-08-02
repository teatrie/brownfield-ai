"""Lint Python source files for SQL wildcard projection violations.

Detects ``SELECT *``, ``SELECT alias.*``, and ``RETURNING *`` patterns
in Python string literals and f-strings using AST extraction and
sqlglot-based SQL parsing.  See ``.claude/rules/sql.queries.md`` for
the full rule rationale and exception list.
"""

from __future__ import annotations

import ast
import sys
import warnings
from pathlib import Path

import defopt
import sqlglot
from sqlglot import exp

# ── Constants ──────────────────────────────────────────────────────

_SQL_KEYWORD_PAIRS = (
    ("SELECT", "FROM"),
    ("INSERT", "INTO"),
    ("UPDATE", "SET"),
    ("DELETE", "FROM"),
    ("CREATE", "TABLE"),
    ("ALTER", "TABLE"),
    ("DROP", "TABLE"),
)

_DEFAULT_DIRS = ("scripts/", "src/", "services/", "ci/", "tests/", ".claude/skills/", "workflows/")

_EXCLUDE_DIRS = {"repos", "tmp", ".venv", "__pycache__", ".git", "node_modules"}

# Relative paths excluded from scanning because they contain intentional
# SQL wildcard fixtures as test inputs for SQL parsing functionality.
# Path-based (not basename-only) to avoid accidentally excluding unrelated files.
_EXCLUDE_PATHS = frozenset({
    Path("tests", "scripts", "test_lint_sql_wildcards.py"),
})


# ── Public interface ───────────────────────────────────────────────


def lint_files(
    paths: list[str],
    *,
    verbose: bool = False,
) -> int:
    """Scan Python files for SQL wildcard violations.

    Args:
        paths: File or directory paths to scan.
        verbose: Show parse warnings and per-file details.

    Returns:
        Count of files with violations (0 means clean).
    """
    py_files = _resolve_paths(paths)

    violation_count = 0
    files_with_violations = 0
    first_violation = True

    with warnings.catch_warnings():
        if not verbose:
            warnings.filterwarnings("ignore")

        for file_path in sorted(py_files):
            candidates = extract_sql_candidates(file_path)
            file_has_violation = False

            for sql_text, line_no in candidates:
                # DDL exception: ``-- mirrors schema of`` comment
                if "-- mirrors schema of" in sql_text:
                    continue

                violations = check_wildcard_violations(sql_text)
                for desc in violations:
                    if first_violation:
                        print("SQL wildcard violations detected:")
                        first_violation = False
                    print(f"{file_path}:{line_no}  {desc}")
                    violation_count += 1
                    file_has_violation = True

            if file_has_violation:
                files_with_violations += 1

    print(f"Scanned {len(py_files)} files, found {violation_count} violation(s) in {files_with_violations} file(s).")
    return files_with_violations


def extract_sql_candidates(file_path: Path) -> list[tuple[str, int]]:
    """Extract SQL string literals from a Python file using AST parsing.

    Walks the AST to find string constants and f-strings that contain
    SQL keywords.  Implicit string concatenation is handled natively
    by the ast module (resolved to a single ``ast.Constant``).

    Known limitation: explicit ``+`` operator concatenation (e.g.
    ``"SELECT " + "* FROM users"``) produces ``ast.BinOp`` nodes,
    not ``ast.Constant``, and is not detected by this extractor.

    Args:
        file_path: Path to the Python source file.

    Returns:
        List of (sql_text, line_number) tuples.
    """
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return []

    results: list[tuple[str, int]] = []

    # Collect IDs of Constant nodes that are children of JoinedStr
    # to avoid extracting them twice (once as part of the f-string
    # reconstruction, once as standalone constants).
    fstring_child_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for val in node.values:
                if isinstance(val, ast.Constant):
                    fstring_child_ids.add(id(val))

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in fstring_child_ids:
                continue
            if _is_sql_candidate(node.value):
                results.append((node.value, node.lineno))

        elif isinstance(node, ast.JoinedStr):
            reconstructed = _reconstruct_fstring(node)
            if _is_sql_candidate(reconstructed):
                results.append((reconstructed, node.lineno))

    return results


def check_wildcard_violations(sql_text: str) -> list[str]:
    """Detect wildcard projections in a SQL string using sqlglot.

    Parses the SQL with sqlglot (sqlite dialect) and checks for Star
    nodes in SELECT and RETURNING positions.  ``COUNT(*)`` is excluded.

    Args:
        sql_text: The SQL string to check.

    Returns:
        List of violation description strings.  Empty if clean.
    """
    try:
        parsed = sqlglot.parse(
            sql_text,
            dialect="sqlite",
            error_level=sqlglot.ErrorLevel.WARN,
        )
    except sqlglot.errors.SqlglotError:
        warnings.warn(
            f"sqlglot parse warning: could not parse SQL: {sql_text[:80]}...",
            stacklevel=2,
        )
        return []

    if not parsed:
        return []

    violations: list[str] = []

    for expression in parsed:
        if expression is None:
            continue
        for star_node in expression.find_all(exp.Star):
            # COUNT(*) exception
            if star_node.find_ancestor(exp.Count):
                continue

            # Determine context: RETURNING or SELECT
            if star_node.find_ancestor(exp.Returning):
                violations.append("RETURNING * violation")
                continue

            # Check for alias wildcard (SELECT t.*)
            parent = star_node.parent
            if isinstance(parent, exp.Column) and parent.table:
                alias_name = parent.table
                violations.append(f"SELECT t.* violation (alias: {alias_name})")
            else:
                violations.append("SELECT * violation")

    return violations


def main(
    files: list[str] | None = None,
    *,
    verbose: bool = False,
) -> None:
    """CLI entry point for the SQL wildcard linter.

    Args:
        files: File or directory paths to scan. Defaults to standard
            project directories when omitted.
        verbose: Show parse warnings and per-file details.
    """
    if files is not None:
        paths = list(files)
    else:
        paths = [d for d in _DEFAULT_DIRS if Path(d).exists()]

    files_with_violations = lint_files(paths, verbose=verbose)
    sys.exit(1 if files_with_violations else 0)


# ── Internal helpers ───────────────────────────────────────────────


def _resolve_paths(paths: list[str]) -> list[Path]:
    """Expand directory paths to individual ``.py`` files.

    Args:
        paths: Mix of file and directory path strings.

    Returns:
        De-duplicated, sorted list of ``.py`` file paths.
    """
    py_files: set[Path] = set()

    for raw in paths:
        p = Path(raw)
        if p.is_file() and p.suffix == ".py" and not _is_excluded_path(p):
            py_files.add(p)
        elif p.is_dir():
            for child in p.rglob("*.py"):
                if _is_excluded_path(child):
                    continue
                relative = child.relative_to(p)
                if not _is_excluded(relative):
                    py_files.add(child)

    return sorted(py_files)


def _is_excluded(path: Path) -> bool:
    """Check whether a path falls under an excluded directory.

    Args:
        path: File path to check.

    Returns:
        True if the path should be skipped.
    """
    return bool(_EXCLUDE_DIRS.intersection(path.parts))


def _is_excluded_path(path: Path) -> bool:
    """Check whether a path matches an excluded test-fixture file.

    Uses suffix matching on path parts so the check works regardless
    of whether ``path`` is absolute or relative.

    Args:
        path: File path to check.

    Returns:
        True if the path matches an excluded fixture file.
    """
    parts = path.parts
    for ep in _EXCLUDE_PATHS:
        ep_parts = ep.parts
        n = len(ep_parts)
        if len(parts) >= n and parts[-n:] == ep_parts:
            return True
    return False


def _is_sql_candidate(text: str) -> bool:
    """Pre-filter: check if text looks like a SQL statement.

    Requires at least one co-occurring SQL keyword pair (e.g.
    SELECT + FROM, INSERT + INTO) to avoid extracting docstrings
    and error messages that happen to contain a single SQL keyword.
    RETURNING is matched when co-occurring with a DML keyword.

    Args:
        text: Candidate string to check.

    Returns:
        True if the text likely contains a SQL statement.
    """
    upper = text.upper()
    for first, second in _SQL_KEYWORD_PAIRS:
        if first in upper and second in upper:
            return True
    if "RETURNING" in upper and any(kw in upper for kw in ("INSERT", "UPDATE", "DELETE")):
        return True
    return False


def _reconstruct_fstring(node: ast.JoinedStr) -> str:
    """Reconstruct an f-string AST node as a plain string.

    ``FormattedValue`` nodes are replaced with the ``__FSTR__``
    sentinel so that SQL keyword detection still works on the
    surrounding literal fragments.

    Args:
        node: The ``ast.JoinedStr`` node to reconstruct.

    Returns:
        Reconstructed string with sentinels in place of expressions.
    """
    parts: list[str] = []
    for val in node.values:
        if isinstance(val, ast.Constant):
            parts.append(str(val.value))
        elif isinstance(val, ast.FormattedValue):
            parts.append("__FSTR__")
    return "".join(parts)


if __name__ == "__main__":
    defopt.run(main)
