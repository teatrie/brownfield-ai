# Workflow Index

This is the master router mapping user requests to specific execution domains.

## 1. Greetings & Initialization

When a user says "hello", "hi", or uses a general greeting for the *very first time* in a session, you MUST bypass standard domain routing and explicitly execute the initialization checklist defined in [greeting.md](greeting.md).

## 2. Domain Routing

For all actionable requests, map the user's intent to one of the following architectural domains. Read the corresponding `CONTEXT.md` file to load the specific tools, skills, and constraints for that domain before execution.

- **[Repository Maintenance](repository-maintenance/CONTEXT.md)**: PR generation, workflow management, docs reviews, and codebase hygiene.
- **[Data Engineering](data-engineering/CONTEXT.md)**: Athena/Redshift/Glue queries, table schema discovery, and data pipeline execution.
- **[AWS Infrastructure](aws-infrastructure/CONTEXT.md)**: Infrastructure architecture, AWS RDS management, and DMS task configurations.
- **[Agent Memory](agent-memory/CONTEXT.md)**: State management, knowledge base interactions, and persistent context ingestion.
- **[Document Utilities](document-utilities/CONTEXT.md)**: PDF parsing, Mermaid diagrams, and structured report styling.

## 3. Cross-Domain Skills

These skills are not scoped to a single domain and may be invoked
from any context:

- **[repos-guide](../.claude/skills/repos-guide/SKILL.md)**: Surface
  curated development guides (conventions, architecture, testing
  patterns) for upstream repositories cloned under `repos/`. Guides live in
  [docs/repo-guides/](../docs/repo-guides/). Invoke when asking
  about or implementing changes targeting repositories with guides in
  `docs/repo-guides/`.
- **[todo](../.claude/skills/todo/SKILL.md)**: Capture, list, and
  triage orphaned TODOs with semantic deduplication and epic-binding
  workflow. Triggered by `/todo`, "capture a todo", "todo list",
  "todo triage".

## 4. Skill Structure & Conventions

- **Standard Skills**: Housed internally as `workflows/<domain>/skills/<skill>/`.
- **Third-Party Skills**: Must be hosted in an isolated namespace to prevent linting and test suite collisions: `workflows/<domain>/skills/third-party/<skill>/`. This directory structure natively excludes external dependencies from the repository's strict standard checks and warns meta-review tools to avoid automated logic mutations.
- **Cross-Domain Skills**: Skills not scoped to a single domain
  are housed at `.claude/skills/<skill>/` and indexed in §3 above.

## Execution Protocol

- ALWAYS default to systematically consulting the `CONTEXT.md` of the matched domain as your very first step. Do not guess or hallucinate available execution workflows.
