---
paths:
  - "**/*.py"
---

# Python Agent Protocol Constraints

## Standards

**CRITICAL DIRECTIVE FOR ALL PYTHON FILES**:

- **Application Rigor Always**: All Python code—including entirely standalone utility scripts in `ci/`, `scripts/`, or root scaffolding—must be treated with production application rigor. You must strictly enforce S.O.L.I.D principles, `defopt` entrypoints, PEP-257 docstrings, and comprehensive typing across ALL directories without exception.

- **Formatting & Linting**: We use `ruff` for fast Python linting and formatting. Always ensure `task lint` passes cleanly before committing.
- **Typing**: Use comprehensive type hints (`typing`) across all Python code to ensure clarity and catch errors earlier.
  - *Legacy Note*: The repository contains legacy files without types or docstrings. However, any time an agent modifies an existing function in a legacy file, they MUST retroactively upgrade that specific function to modern standards (PEP-257 docstrings and full `typing` annotations) as part of the "Boy Scout Rule" (leave it better than you found it).
- **Module-Scope Imports**: Always place imports at the top of the file (module scope) rather than inline inside functions. This ensures tools and static analysis can detect missing dependencies immediately without requiring runtime execution. Only use inline imports when absolutely necessary, such as:
  1. Functions that will be serialized for distributed execution (e.g., Spark RDD functions, PySpark UDFs).
  2. Dynamic/deferred loading of unexpectedly heavy modules to significantly improve application startup or runtime performance.
- **Main Block Enforcement**: The `if __name__ == '__main__':` block MUST always remain at the **absolute bottom** of a Python file. NEVER append imports, functions, tests, or classes after this block. When adding new code or using file append tools (`cat >>`), you must insert the code *above* the main execution block to avoid breaking standard module conventions.
- **CLI Parsing**: For `main()` and `if __name__ == '__main__':` execution blocks in Python scripts, you MUST use `defopt` instead of standard `argparse`.
- **Subprocess Avoidance**: Avoid `subprocess` when a Python-native alternative exists. Use:

  | Use case | Alternative | Example |
  |----------|-------------|---------|
  | Python-to-Python script calls | `runpy.run_path()` | Instead of `subprocess.run(["python3", "script.py", arg])` |
  | Docker container operations | Docker SDK (`import docker`) | Instead of `subprocess.run(["docker", "run", ...])` |
  | Git operations | GitPython (`import git`) | Instead of `subprocess.run(["git", "branch", ...])` |
  | Alembic migrations | Alembic programmatic API | Instead of `subprocess.run(["alembic", "upgrade", ...])` |
  | HTTP calls | `requests` / `httpx` | Instead of `subprocess.run(["curl", ...])` |

  When `subprocess` IS acceptable: Non-Python CLIs with no Python SDK (e.g., `atlas`, `mysqladmin`, `pg_dump`).
- **No Dynamic Container Creation at Runtime**: Do not dynamically pull or create Docker containers as part of application or script business logic. Runtime code must not depend on Docker daemon availability. Container orchestration belongs in CI pipelines, Taskfile targets, or `docker-compose.yml` services — not in Python scripts. If a script needs a database, it should connect to a pre-existing service, not spin one up. Existing violations (e.g., `ephemeral_db.py`, `get_service_db_schema.py`) are tracked as tech debt and should be refactored to use static infrastructure (pre-built containers via `docker-compose.yml` or Taskfile service targets).
- **Dependency Minimization**: Do not introduce new runtime dependencies when the existing toolchain can accomplish the same goal. New entries in `requirements.txt` require justification — prefer using APIs already available in the environment. Every new dependency adds image size, supply-chain risk, and version management burden.
- **Multi-line Function Signatures**: When a function has more than 3 parameters, prefer multi-line signatures with one parameter per line for readability. `ruff format` enforces this automatically when the single-line form exceeds the line length limit, but agents should proactively use multi-line form for any function with 4+ parameters regardless of line length.
- **Keyword-Only for Optional Parameters**: When a function has parameters with sensible defaults that callers may omit, place them after a bare `*` separator to enforce keyword-only passing. This prevents silent positional misrouting when signatures evolve — callers that pass empty strings or `None` as positional placeholders are a latent reorder bug. Required parameters (no default) remain positional. CLI wrappers using `defopt` are exempt since `defopt` manages parameter mapping from CLI flags. Example:

  ```python
  def create_record(
      db: sqlite3.Connection,
      collection: Any,
      title: str,
      *,
      category: str = "",
      priority: int = 5,
      description: str = "",
      metadata: Optional[dict[str, Any]] = None,
  ) -> int:
  ```

- **Modularization & Entry Points**: Break down large `main()` functions or monolithic blocks into smaller, logical helper functions. Keep `main()` strictly as the CLI entry point (handling setup/teardown and argument processing) and delegate actual business logic to separate "core" functions. Use the following template:

  ```python
  import defopt

  def core_func(*args, **kwargs):
      """Core orchestrator of the module's business logic.

      Per the Top-to-Bottom rule, define this primary interface before internal helpers.
      Note: Rename this placeholder to reflect its actual purpose.
      """
      ...

  def main(*args, **kwargs):
      """CLI entry point. Do not perform core processing here."""
      # SETUP: process args and prepare them for core_func()
      ...
      try:
          core_func(*args, **kwargs)
      finally:
          # TEARDOWN: cleanup resources
          ...

  # MUST BE LAST in the module
  if __name__ == '__main__':
      defopt.run(main)
  ```

- **AWS Clients**: Always use the internal wrapper `brownfield_ai.services.aws.get_client("<service>")` instead of instantiating raw `boto3` clients to ensure proper SSO credential handling is strictly centralized.
- **Exception Handling**: Only catch the specific exceptions you expect. Never silence unexpected errors by catching the base `Exception` type alongside narrower types (e.g., `except (ValueError, TypeError, Exception)` is equivalent to `except Exception` and masks real failures). Catch only the exceptions the called API is documented to raise for the condition you are handling; let all others propagate.
- **TYPE_CHECKING Guard for Annotation-Only Imports**: When a module is imported solely to provide type annotations (not used at runtime), place the import inside a `TYPE_CHECKING` guard block to avoid unnecessary runtime dependencies and import cycles. This pattern is required when:
  1. The imported module is heavy (e.g., `chromadb`, `pandas`, `pyspark`) and not otherwise needed at runtime in that file.
  2. The file uses `from __future__ import annotations` (PEP 563), which makes all annotations lazy strings — enabling TYPE_CHECKING guards without runtime `NameError`.

  ```python
  from __future__ import annotations

  from typing import TYPE_CHECKING

  if TYPE_CHECKING:
      import chromadb

  def get_collection() -> chromadb.Collection:
      ...
  ```

  **Exception**: If the module is already imported at runtime for other purposes (e.g., `chromadb` is used to create a client), annotate directly — no guard needed.
- **No Name Stuttering**: When a Python module name already provides
  namespace context, function and class names must not repeat it. For
  example, in `aws.py` prefer `get_config()` over `get_aws_config()` —
  callers already write `aws.get_config()`. This applies to modules,
  classes, and public functions.
- **Testing**: We use `pytest` as our testing framework. Ensure tests encompass the new behavior and run cleanly (`task test`).
- **Script Location**: Substantial Python scripts (with tests, type annotations, and business logic) should reside in `scripts/` for full lint and test coverage. `.claude/skills/` may contain lightweight scripts but is not exempt from linting.

## Datalake Python 3.9 Constraint

The `repos/analytics/src/datalake/` module specifically targets **Python 3.9**. AI Agents must use Python 3.9 compatible logic (e.g. `from typing import List, Dict` instead of `list`, `dict`, and no Python 3.10+ union pipes like `X | Y`). See also `.claude/rules/repos.analytics.datalake.md` for additional datalake-specific constraints.
