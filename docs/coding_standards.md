# Coding Standards

## General Standards

- **Vertical Formatting & Line Limits**: All code must pass the project's configured linters. Line length limits are enforced per-language by each linter's config file — do not hardcode assumptions about limits. Any text, string arrays, or shell commands inside YAML or configuration files that exceed the configured limit must use multiline folded block styles (e.g., `>`) to enforce vertical wrapping instead of horizontal scrolling.
- **Terse Syntax in Tooling**: Opt for terseness and built-in functions of current tools. For example, in Taskfile (`go-task`), rely on native sprig templating (e.g., `{{.CLI_ARGS | default "tests/"}}`) rather than verbose, multi-block if-else conditions.
- **S.O.L.I.D Principles**: Agents should strictly adhere to [S.O.L.I.D software engineering principles](https://en.wikipedia.org/wiki/SOLID) to maintain clean, maintainable, and modular code.
- **Functions Over Classes**: Prefer using standalone functions over classes. Classes should *only* be used when:
  1. A class is required to maintain application state.
  2. It serves as a base class that will be inherited (for example: `AgentRunner -> PlatformRunner`).
- **Top to Bottom**: Code should flow logically from top to bottom. Start with imports at the top, followed by constants. Next, define the public classes and functions that implement the module's core interface or primary purpose. After that, place any internal or private helper functions, and finally, put the main execution logic at the very bottom.
- **File Structure**: Keep scripts focused and modular. If a script exceeds simple responsibilities, consider refactoring it into smaller modules.
- **Coding Style & Conventions**: Adhere strictly to the coding style, conventions, and standards of the particular language being used. All code must pass the project's configured linters and type checkers.

## Documentation Standards

Agents MUST enforce language-specific documentation conventions across the repository:

1. **Modules & Classes**: **Always Required**. Any new file or class must have a top-level block explaining its purpose, state management, and primary entry points.
2. **Public Functions / Skill Methods**: **Always Required**. Specifically document parameters, expected return formats, and potential exceptions (e.g., standard PEP-257 format for Python, JSDoc for TypeScript/Node).
3. **Internal Helpers (Private Methods)**: **Optional**. Only required if the logic is complex. If it is a short helper with explicit Type Hints, the types and clear naming usually suffice.
4. **Test Functions**: **Omitted**. Test functions should be behaviorally named (e.g., `test_aws_cli_evals_fails_without_credentials()`) making docstrings redundant, unless the test requires a complex mocking setup that needs explanation.
5. **Workflow Context Links**: **Always Required**. Whenever a new Skill or Prompt is added to a `workflows/<domain>/` directory, its entry under `## Available Skills` or `## Available Prompts` in `CONTEXT.md` MUST include a single-line, intent-rich description alongside the file link (e.g., `- [dms-task](prompts/dms-task.prompt.md): Boilerplate for generating AWS DMS tasks`). Do not leave links bare.

## Python Standards

Python-specific standards are scoped via `.claude/rules/lang.python.md` (loaded automatically when editing `**/*.py` files). See that file for formatting, typing, CLI parsing, subprocess avoidance, modularization, and all other Python constraints.

## SQL Standards

SQL-specific standards are scoped via `.claude/rules/sql.queries.md` (loaded automatically when editing `**/*.py`, `**/*.sql`, `**/*.sql.j2`, `**/*.yaml`/`**/*.yml`, `**/*.ipynb`, or `**/*.sh` files). The core rule: **never use `SELECT *` in committed code**. Every query — embedded Python string, raw SQL, dbt Jinja template, Alembic migration, notebook cell, or shell heredoc — must enumerate the exact columns it consumes. See that file for the rationale, the four named exceptions, and enforcement guidance.

## Markdown & Link Standards

- **Avoid Linkification**: Never format Git branch names (e.g., `origin/main`, `ship/branch-name`) or untracked/ignored temporary file artifacts (e.g., `plan.md`, `mappings.json`, `.gitignore`) as Markdown hyperlinks (e.g., `[origin/main](origin/main)`). Keep them represented strictly as inline code blocks with backticks.

- **Link Validity & Relative Paths**: When linking to existing workspace documents in Markdown files, you MUST ensure the target is a valid, relative file path from the currently modified document (e.g., `[delegation_protocol.md](delegation_protocol.md)`). Do not blindly wrap file names in markdown links (e.g., `[file.md](file.md)`) without verifying directory depth. If you are unsure of the exact relative path or if the file may not exist, represent the reference as an inline code block with backticks (e.g., `` `delegation_protocol.md` ``) instead of creating a broken link.
