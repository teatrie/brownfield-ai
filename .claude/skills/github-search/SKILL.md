---
name: github-search
description: "**Tier 2 Discovery (Protocol 12):** Use as a fallback for queries outside `repos-guides` or as an enrichment tool. Use the GitHub CLI (`gh`) to remotely search for code, files, or tables across the organization's repositories. Make sure to use this skill when a specific table, code file, or feature is located across the organization AND no `repo-guide` exists (or to enrich a known guide). Additionally, trigger this skill when the user is researching cross-organization integrations, finding all instances a library is imported, or investigating systems without dedicated `repos-guides` docs. Prioritizes remote searching before falling back to locally cloning new repositories."
---

# GitHub Code Search and Exploration

**TIER 2 DISCOVERY PROTOCOL:** The `github-search` skill MUST be used as the **secondary** starting point (after `repos-guide`) to broad inquiries, research tasks, and troubleshooting scenarios across the organization before moving to cloning or more specialized tools.

This skill outlines the strict "Just-in-Time" (JIT) protocol for searching and exploring external repositories.

Whenever you are tasked with finding where a table is generated, locating code that does not currently exist in the local [repos/](../../../repos) workspace, or enriching data lineage traces after reading a `repo-guide`, **you must use remote search first** to avoid unnecessary, massive repository clones.

Additionally, you MUST utilize this workflow when a user prompt indicates:

- **System Research**: Researching how things work across the organization.
- **Service Architecture**: Investigating relationships between services (e.g., APIs, data contracts, dependencies).
- **Feature Planning**: Seeking advice on how to build a feature and analyzing its implications across multiple domains or repositories.
- **Cross-System Debugging**: Diagnosing and fixing bugs, especially complex bugs that span or affect multiple systems.
- **Deep Analytics & Auditing**: Tracking organization-wide library adoption metrics, scoping the blast radius of API deprecations, or executing sweeping security vulnerability checks across all services.

## Search Phase (Remote)

Use the GitHub CLI to search the organization's codebase. Execute this in your terminal.

1. **Authentication & Prerequisites:**
   - The `gh` CLI runs inside the `repo-cli` Docker container. No local installation is required.
   - `GH_TOKEN` must be set in the host environment. Run `export GH_TOKEN=$(gh auth token)` or use `scripts/setup_env.sh`.
   - **DO NOT install system packages directly or fall back to the GitHub MCP server or other tools.** The GitHub MCP server is explicitly disabled by company policy.

2. **Basic Code Search:**

   ```bash
   task gh:search -- "<query>" --owner <org>
   ```

   - Replace `<query>` with the precise table name, function, or target keyword.
   - **Resolving `<org>`** — in this order:
     1. An org or `<org>/<repo>` named explicitly in the user's prompt.
     2. `$BROWNFIELD_ORG` — the same user-supplied variable `task repos:clone`
        uses, so the repos you search are the repos you clone. Set it in
        `.envrc`/`.env`; see [repos/README.md](../../../repos/README.md).
     3. The owner of an existing checkout under `repos/`, if the question is
        clearly about one of them.

     If none of these resolve, **ask the user which org to search**. Do not guess
     an org, and do not fall back to the org this harness was published under —
     `teatrie/brownfield-ai` is where the harness comes from, not where the
     user's code lives.
   - **Search the org, not a single repository.** `--owner <org>` covers every
     repo under it, which is the point of Tier 2 discovery: you usually do not
     know which repo holds the answer. Only narrow to `--repo <org>/<name>` once
     a prior search has told you where to look.
   - `$GH_TOKEN` must be able to read the org. For a personal account, `<org>` is
     your username. Private repos require a token with `repo` scope; without it
     `gh search code` silently returns only public matches.

3. **Parsing the Output:**
   - Review the search results carefully to identify which repository and exact file path contains the match. Often, the snippet provided in the `gh search` output contains enough information to answer simple questions (like defining immediate upstream dependencies).
   - If the answer is self-contained in the remote search snippet, stop here and synthesize your answer for the user.

## Cloning Phase (Local Deep Dive)

If the remote code search indicates that a thorough codebase read-through or a multi-step lineage trace is required (e.g., following imports, tracing Airflow DAGs, or running robust regular expressions across the whole logic chain), you should escalate to cloning the specific repository.

1. Navigate to the local `repos/` workspace.
2. **Prefer sparse checkout** when the search phase has already identified the target path(s):

   ```bash
   task gh:sparse-clone -- <org>/<repo> <path/to/directory>
   ```

   Fall back to a full clone only when broad analysis across the entire repo is required:

   ```bash
   task gh:repo -- clone <org>/<repository_name>
   ```

3. Once cloned, you may utilize your platform's search and file-reading tools to conduct a deep analysis of that local repository.

### Rules of Engagement

- **Do not guess or hallucinate:** If `gh search code` returns no results, do not make up a repository name or assume a table originates from a standard location. Communicate the missing data to the user.
- **Limit cloning:** Only clone a repository if you cannot determine the answer from the initial `gh` code search snippets.
- **Maintain hygiene:** Remember that if a repo is ALREADY cloned in `repos/`, your general protocols dictate running `task repos:reset` before planning/analyzing it locally.
