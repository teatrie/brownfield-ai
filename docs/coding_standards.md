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
6. **No Historical / Tracking Comments in Code**: Comments carry the code's *current-state* rationale, never the change history that produced it. Strip dates, deployment status, evolution narrative, and PR/ticket cross-references — `git blame`, the PR description, and the Execution Ledger already hold them, and in code they rot. Stripped history MUST be relocated to a durable home, never silently dropped. Authoritative source: [.claude/rules/comments.history.md](../.claude/rules/comments.history.md).
7. **Minimal, Reader-Directed Comments & Docstrings**: The *audience/redundancy* companion to §6. Comment only non-obvious rationale specific to *this* code that cannot be recovered from the code, its base class, its type signature, or a linked guide. Delete generic restatements of framework contracts, scaffolding that narrates the agent's own reasoning, and speculation about paths the code does not take. Authoritative source: [.claude/rules/comments.conciseness.md](../.claude/rules/comments.conciseness.md).

## Guidance Over Exhaustive Rules

Agent-facing docs (e.g. skills, protocols, agent definitions, rules, `CLAUDE.md`) give an agent enough guidance to reason to the best decision. They do not define a rule for every case: that is impossible, and each precise behavioural claim invites the next reviewer to find an exception. In plans, it covers doc text the plan proposes and prose describing existing behaviour; it does not relax the Requirements Traceability Map, where requirements, edge cases and architectural rules for what the plan builds stay explicit. Code docstrings follow Documentation Standards above.

- **Keep what an agent cannot easily derive**: e.g. the command or flag form, the non-obvious step, the trap, where the source of truth lives.
- **Point, do not restate**: link the code, a command's `--help` or a schema instead of copying its behaviour into prose that drifts. Exception: a copy another rule requires and audits (e.g. the `.github/instructions/` mirrors of `.claude/rules/`, which `claude-review`'s **Content parity** check audits).
- **State intent and decision criteria**, not a decision table. Mark examples "e.g."; a list that reads as complete is a bug once one case is missing. Avoid enumerating runtime behaviour (e.g. exit codes, streams, state transitions) unless an agent acts on it.
- **Fixing an "incomplete claim" finding**: cut or generalise to intent plus a pointer. That is valid when what remains is true, actionable and keeps the traps; a wrong claim is corrected or cut, never generalised around. Add a case only for a trap an agent cannot find in the pointed-to source. Do not reject a cut because more enumeration was possible. A cut or generalisation that changes what a normative rule (e.g. MUST/NEVER, a gate criterion) requires is a conceptual change: flag it to the user, do not apply it unilaterally. With no user to ask (headless), leave it unapplied and record it in the run's checkpoint or report.
- **Draw mechanics, don't narrate them**: when a doc defines a procedure with states, loops, ordering or several exits (e.g. a review gate's fold loop, a step's verify → checkpoint → commit order), give it as a state or flow diagram (Mermaid) or short decision-level pseudocode, and make that the normative form; prose gives intent, decision criteria and traps. Draw only mechanics the doc owns. For behaviour owned by code or a tool, point to the source instead (e.g. ledger transitions in [src/brownfield_ai/ledger/epics/constants.py](../src/brownfield_ai/ledger/epics/constants.py)).

Cut: "Cleared by `release`, by stale auto-release, and by any transition to `approved`, `pending` or `blocked`." (Execution Ledger `claimed_by`) becomes "`release` and stale auto-release clear it; some status changes do too. Check [src/brownfield_ai/ledger/epics/lifecycle.py](../src/brownfield_ai/ledger/epics/lifecycle.py) and [src/brownfield_ai/ledger/epics/claims.py](../src/brownfield_ai/ledger/epics/claims.py) if the exact rule matters."

Keep: "run `task ledger:touch -- <epic_id>` periodically on a long-running claim" is a non-derivable trap; "checkpoint periodically" would not reliably refresh the claim.

## Python Standards

Python-specific standards are scoped via `.claude/rules/lang.python.md` (loaded automatically when editing `**/*.py` files). See that file for formatting, typing, CLI parsing, subprocess avoidance, modularization, and all other Python constraints.

## SQL Standards

SQL-specific standards are scoped via `.claude/rules/sql.queries.md` (loaded automatically when editing `**/*.py`, `**/*.sql`, `**/*.sql.j2`, `**/*.yaml`/`**/*.yml`, `**/*.ipynb`, or `**/*.sh` files). The core rule: **never use `SELECT *` in committed code**. Every query — embedded Python string, raw SQL, dbt Jinja template, Alembic migration, notebook cell, or shell heredoc — must enumerate the exact columns it consumes. See that file for the rationale, the four named exceptions, and enforcement guidance.

## Markdown & Link Standards

- **Avoid Linkification**: Never format Git branch names (e.g., `origin/main`, `ship/branch-name`) or untracked/ignored temporary file artifacts (e.g., `plan.md`, `mappings.json`, `.gitignore`) as Markdown hyperlinks (e.g., `[origin/main](origin/main)`). Keep them represented strictly as inline code blocks with backticks.

- **Link Validity & Relative Paths**: When linking to existing workspace documents in Markdown files, you MUST ensure the target is a valid, relative file path from the currently modified document (e.g., `[delegation_protocol.md](delegation_protocol.md)`). Do not blindly wrap file names in markdown links (e.g., `[file.md](file.md)`) without verifying directory depth. If you are unsure of the exact relative path or if the file may not exist, represent the reference as an inline code block with backticks (e.g., `` `delegation_protocol.md` ``) instead of creating a broken link.

- **Cite by Path or Heading, Never by Line Number**: In committed Markdown (e.g., docs, agent definitions, skills), point a reader at a file by its path (a relative link, or a repo-root path in backticks) and at a section by its heading (an anchor link such as `[coding_standards.md](coding_standards.md#guidance-over-exhaustive-rules)`, or the quoted heading text); inside a section, add a symbol name or quoted phrase a reader can search for. Cite the live tree by path and heading, never by line number (e.g., `file.md:42`, or a `blob/main/...#L42` link): any edit above the cited line moves it, so the citation silently points at the wrong text. When the reader needs the text as it was rather than as it is (e.g., a review finding, a plan's baseline), pin the citation to a commit the reader can fetch (e.g., one on `main`, or one a PR references), never a local-only commit; line numbers are then fine. Illustrative examples are not citations.
