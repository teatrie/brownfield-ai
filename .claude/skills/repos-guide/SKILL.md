---
name: repos-guide
description: >-
  **Tier 1 Discovery (Protocol 12): MUST be the initial starting point.**
  Surface the relevant repository guide for an upstream repo cloned under
  `repos/`, or for a domain within one. Use when the user asks about repo
  conventions, architecture, data lineage, table or job inventories, testing
  patterns, or development workflows for a specific upstream repository
  (e.g., "how does this repo's pipeline work?", "show me the lineage for...",
  "what's the testing pattern here?"). Also use proactively during
  planning and implementation phases that target upstream repos.
---

# Repository Guide Lookup

Surfaces curated development guides for the upstream repositories cloned under
`repos/`. These guides document architecture, conventions, testing patterns,
lineage, inventories, and build tools that are specific to each repo and NOT
derivable from this workspace's own standards.

Guides are generated, not vendored — run the `repos-research` prompt
(`workflows/repository-maintenance/prompts/repos-research.prompt.md`) against a
checkout to produce one. A workspace with no guides yet is the expected initial
state, not an error.

## Generated Artifacts

A guide may ship machine-generated artifacts alongside its prose — for example an
`inventory.yml` mapping jobs to their outputs and upstream dependencies, or an
interactive HTML explorer. These carry `generated_at` timestamps and a `generator`
script path in their metadata.

Two rules when you encounter them:

- **Check freshness before trusting them.** Compare `generated_at` against the
  last-modified date of the generator's source data. See
  `docs/planning_protocol.md` for the staleness decision procedure.
- **Surface HTML explorers as a copy-pasteable `file://` URI**, not a markdown
  link — clicking a markdown link to an HTML file opens its source in the editor
  rather than rendering it. Build the absolute path from the workspace root. If
  the explorer supports hash routing, append the fragment that jumps straight to
  the node the user asked about.

## Execution Steps

1. **Scan the index**: From the workspace root, read the
   `docs/repo-guides/` directory tree to identify available guides.

   ```text
   docs/repo-guides/
   └── <repo-name>/
       ├── README.md      # Global repo directives
       ├── <domain>.md    # Domain-specific guide
       └── templates/     # Optional reference templates
   ```

2. **Match the query**: Map the user's request (repo name, domain
   keyword, or technology) to the correct guide. Matching rules:
   - Exact repo name → `docs/repo-guides/<repo>/README.md`
   - Domain keyword → scan each repo's README for domain guide links,
     then read the matching `<domain>.md`
   - Technology keyword (e.g., "PySpark", "Luigi") → grep across
     all guides for the term and present the relevant sections

3. **Present the guide**: Read and present the matched guide
   content to the user. If multiple guides match, present each
   with a brief summary and let the user choose.

4. **No guide exists**: If no guide matches the query, state that
   clearly. Do NOT fabricate conventions or infer patterns from
   unrelated repos. Fall back to Tier 2 (`github-search`) or Tier 3
   (sparse clone), and suggest the user generate a guide with the
   `repos-research` prompt if the repo is frequently referenced.

## When to Invoke Proactively

Agents SHOULD consult this skill (without user prompting) when:

- The **Planner** is designing an epic that targets an upstream
  repo — read the guide during the grilling phase to inform
  requirements and constraints.
- An **implementer subagent** is about to modify files under
  `repos/<repo>/` — the delegating agent should include the
  relevant guide content in the delegation prompt.
- A **code-review** agent is reviewing changes to upstream repo
  code — the guide documents conventions that linters may not
  enforce.
- The **workflow router** has completed domain routing — agents
  SHOULD also check cross-domain skills in
  the Cross-Domain Skills section of `workflows/INDEX.md` after
  loading a domain CONTEXT.md.

## Headless Compatibility

This skill contains no interactive gates (no user prompts,
authentication steps, or confirmation dialogs). It is safe for
headless invocation (`CI=true` or subagent delegation) with no
special handling required.
