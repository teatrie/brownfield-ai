---
description: Python Agent Protocol Constraints
applyTo: "**/*.py"
---

# Python Agent Protocol Constraints

**CRITICAL DIRECTIVE FOR ALL PYTHON FILES**:

- **Application Rigor Always**: All Python code -- including standalone utility
  scripts in `ci/`, `scripts/`, or root scaffolding -- must be treated with
  production application rigor. Strictly enforce S.O.L.I.D principles, `defopt`
  entrypoints, PEP-257 docstrings, and comprehensive typing across ALL
  directories without exception.

- **Formatting & Linting**: We use `ruff` for fast Python linting and
  formatting. Always ensure `task lint` passes cleanly before committing.
- **Typing**: Use comprehensive type hints (`typing`) across all Python code.
  - *Legacy Note*: Any time an agent modifies an existing function in a legacy
    file, they MUST retroactively upgrade that specific function to modern
    standards (PEP-257 docstrings and full `typing` annotations) as part of the
    "Boy Scout Rule."
- **Module-Scope Imports**: Always place imports at the top of the file (module
  scope) rather than inline inside functions. Only use inline imports when
  absolutely necessary:
  1. Functions serialized for distributed execution (e.g., Spark UDFs).
  2. Dynamic/deferred loading of heavy modules to improve startup performance.
- **Main Block Enforcement**: The `if __name__ == '__main__':` block MUST always
  remain at the **absolute bottom** of a Python file. NEVER append imports,
  functions, tests, or classes after this block.
- **CLI Parsing**: For `main()` and `if __name__ == '__main__':` execution
  blocks, you MUST use `defopt` instead of standard `argparse`.
- **Subprocess Avoidance**: Avoid `subprocess` when a Python-native alternative
  exists:

  | Use case | Alternative |
  |----------|-------------|
  | Python-to-Python script calls | `runpy.run_path()` |
  | Docker container operations | Docker SDK (`import docker`) |
  | Git operations | GitPython (`import git`) |
  | Alembic migrations | Alembic programmatic API |
  | HTTP calls | `requests` / `httpx` |

  `subprocess` IS acceptable for non-Python CLIs with no Python SDK (e.g.,
  `atlas`, `mysqladmin`, `pg_dump`).
- **No Dynamic Container Creation at Runtime**: Do not dynamically pull or
  create Docker containers as part of application or script business logic.
  Container orchestration belongs in CI pipelines, Taskfile targets, or
  `docker-compose.yml` services.
- **Dependency Minimization**: Do not introduce new runtime dependencies when
  the existing toolchain can accomplish the same goal. New entries in
  `requirements.txt` require justification.
- **Multi-line Function Signatures**: When a function has more than 3
  parameters, prefer multi-line signatures with one parameter per line.
- **Keyword-Only for Optional Parameters**: Place parameters with sensible
  defaults after a bare `*` separator to enforce keyword-only passing. Required
  parameters (no default) remain positional. CLI wrappers using `defopt` are
  exempt.
- **Modularization & Entry Points**: Keep `main()` strictly as the CLI entry
  point (handling setup/teardown and argument processing) and delegate actual
  business logic to separate "core" functions. Use `defopt.run(main)` at the
  bottom.
- **AWS Clients**: Always use the internal wrapper
  `brownfield_ai.services.aws.get_client("<service>")` instead of instantiating raw
  `boto3` clients.
- **Exception Handling**: Only catch the specific exceptions you expect. Never
  silence unexpected errors by catching the base `Exception` type alongside
  narrower types.
- **TYPE_CHECKING Guard for Annotation-Only Imports**: When a module is imported
  solely to provide type annotations (not used at runtime), place the import
  inside a `TYPE_CHECKING` guard block. Required when the imported module is
  heavy and the file uses `from __future__ import annotations`.
- **No Name Stuttering**: When a Python module name already provides namespace
  context, function and class names must not repeat it. For example, in `aws.py`
  prefer `get_config()` over `get_aws_config()`.
- **Testing**: We use `pytest`. Ensure tests encompass the new behavior and run
  cleanly (`task test`).
- **Script Location**: Substantial Python scripts should reside in `scripts/`
  for full lint and test coverage.

## Datalake Python 3.9 Constraint

The `repos/analytics/src/datalake/` module specifically targets **Python 3.9**.
Use `from typing import List, Dict` instead of `list`, `dict`, and no Python
3.10+ union pipes like `X | Y`.
