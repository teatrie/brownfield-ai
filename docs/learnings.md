# Agent Learnings & Gotchas

This document captures low-level "gotchas" and edge cases encountered while developing tools or debugging the platform (e.g., Docker commands failing, library version constraints).

**Note:** Do NOT document codebase flaws, legacy patterns, or refactoring opportunities here. All code-level technical debt must go in [docs/tech_debt.md](tech_debt.md). Standard operating procedures are defined in [CLAUDE.md](../CLAUDE.md) and individual `SKILL.md` files.

## Docker Configurations (Terraform & CLI)

* **AWS Authentication**: Executing AWS-dependent tools (like Terraform) or Python scripts (like Boto3 API calls) inside Docker requires AWS credentials. Use `aws-vault exec <profile> -- docker compose run --rm ...` to invoke the SSO flow interactively and cleanly inject `-e AWS_...` variables into the container.
* **Drift Detection & Unmerged State**: When running a local Terraform plan off `main`, the AWS remote state may contain resources created entirely by other open, unmerged PRs. Because these resources are missing from your local `.tf` files, Terraform will aggressively plan to **delete** them to match your local state.
  * **Solution**: Rely heavily on the Verification Gate. By exporting the plan strictly to JSON (`terraform show -json plan.out > plan.json`) and tasking an isolated reviewer agent to audit for forbidden 'Deletions' or unexpected 'Modifications', you prevent destructive silent rollbacks of concurrent ongoing deployments. Always pause to coordinate with the team if your plan is nuking unexpected production resources.
* **Docker Desktop Mac `docker.sock` Ownership**: On Docker Desktop for Mac, `/var/run/docker.sock` is owned by `root:root` (not `root:docker` as on Linux). This means a non-root container user cannot access the socket via a `docker` group membership. The `pytest-cli` Dockerfile adds GID 0 as a supplementary group (`useradd -G 0`) so the `agent` user can read the socket for sibling container orchestration (e.g., `pytest-docker`). On Colima, the socket ownership varies by configuration — GID 0 works as a portable fallback for both runtimes.

## ChromaDB & Memory

* **ChromaDB Has No Built-in Versioning**: ChromaDB is a flat document store — `upsert` overwrites, there is no changelog or rollback. If you need version history, implement it via: (1) composite IDs with timestamps so each save creates a new document, and (2) an `artifact_status` metadata field (`active`/`superseded`) with a `supersede_previous()` function that flips old versions before writing new ones.
* **ChromaDB `$and` Operator Version Dependency**: The `$and` operator in `where` filters is not available in all ChromaDB versions (requires 0.4.x+). Always implement a graceful fallback: attempt the `$and` query, catch the specific exception, fall back to a single filter + client-side post-filter.
* **Global ChromaDB Container Name Conflicts Across Workspaces**: When the `global-chromadb` container was started by a different `brownfield-ai-*` workspace (different compose project name), `docker compose up -d` from your workspace fails with "container name already in use." The container is a global singleton by design.
  * **Solution**: Check `docker ps --filter "name=global-chromadb"` before attempting to start. If already running, skip the start. This is what `task chromadb:start` implements.

### Persistent Data

* **Global Instance & Shared Workspaces**: To prevent port-collision across multiple `brownfield-ai-*` cloned workspaces, the `chromadb` vector database has been extracted from the local [docker-compose.yml](../docker-compose.yml) into a specific shared configuration: [docker-compose.chromadb.yml](../docker-compose.chromadb.yml) which deploys a globally accessible `global-chromadb` container.
  * **Volume Persistence**: Data volume mapping uses the user's home directory `~/.brownfield-ai/chroma_data:/data` so that memory persists consistently no matter which `brownfield-ai` repo instance starts the database.
  * **Network Routing**: Local client scripts connect to this global instance using `host.docker.internal` rather than standard service names. Do not append local service entries for `chromadb` back into individual repo [docker-compose.yml](../docker-compose.yml) files.

* **Data Persistence**: The official `chromadb/chroma` image stores data in `/data` inside the container by default (based on `persist_path` in logs), even if `IS_PERSISTENT=TRUE` is set.
  * **Configuration**: The global instance uses `~/.brownfield-ai/chroma_data` mapped to `/data` in [docker-compose.chromadb.yml](../docker-compose.chromadb.yml) to ensure data persists across all workspaces and sessions. Do NOT mount to `/chroma/chroma` as it will be ignored.
  * **Destructive Testing Workarounds**: Agents MUST NOT comment out or disable the host volume mapping (`- ~/.brownfield-ai/chroma_data:/data`) in [docker-compose.chromadb.yml](../docker-compose.chromadb.yml) simply to make automated tests pass or to bypass file-locking collisions. Disabling this mapping silently destroys historical memory databases when the container restarts. If a clean, ephemeral database is required for isolated testing, agents must create a newly defined test service profile rather than dismantling the primary persistence layer.
* **Metadata Constraints**: ChromaDB requires metadata to be a non-empty dictionary or `None`. Passing an empty dictionary `{}` raises a ValueError.
* **Docker Networking**: When running client scripts (like [knowledge_base.py](../workflows/agent-memory/skills/knowledge-base/scripts/knowledge_base.py)) in a separate container, use `host.docker.internal` rather than the standard service name (e.g., `chromadb`) as the host.
* **Volume Mounting**: To allow scripts to export data to the host or read files from the host, mount the project root to `/app` (or similar working directory) in [docker-compose.yml](../docker-compose.yml).
* **Client Compatibility**: The `chromadb` client library version in [requirements.txt](../requirements.txt) must be compatible with the server version running in the Docker container.

## Testing & Agent Evaluation

* **Subagent Evals & Docker-in-Docker Networking**: When writing evaluations (`evals.yml` under [tests/skills/](../tests/skills/)) for skills targeting local mock servers (like `aws-localstack-1`), do NOT allow the agent to execute scripts using `docker compose run`.
  * **The Problem**: Because the integration test runner (`pytest-cli` container) is already operating inside a Docker network, executing `docker compose run` spawns a brand new, fully isolated sibling container. This new container will have no network route back to the test environment's internal network to reach the mocked `aws-localstack-1` server.
  * **Solution**: Explicitly restrict the agent in the evaluation prompt to run scripts natively inside the current runner environment. Add a forceful constraint like: `NOTE: For this testing environment, do NOT use docker compose... Run the python script directly natively.`
* **AWS Mocking (Moto / LocalStack) & Sibling Containers**: We rely on `motoserver/moto` (via `pytest-docker`) to mock AWS endpoints locally during test runs. Because the test suite is actively invoked inside our isolated `pytest-cli` Docker container, the service actually orchestrates *sibling containers*, leveraging the host's `/var/run/docker.sock` volume mount.
* **Headless Copilot Evals & Context Isolation**: Integration tests evaluating AI skills execute the official `@github/copilot` NPM package via a headless child-process.
  * **Authentication Requirements**: The CLI rigidly requires the runtime environment to supply an active `COPILOT_GITHUB_TOKEN`. If not passed structurally, headless tests will crash instantly via interactive timeout failures waiting for browser auth.
  * **Sandbox Context Boundaries**: Because Co-Pilot automatically parses local Git context to provide answers, [tests/skills/test_evals.py](../tests/skills/test_evals.py) MUST explicitly run `git init` within the ephemeral temporary sandbox pathway to strictly bound the agent's context. Otherwise, Co-Pilot bleeds out of the `tmp/` root directory and starts referencing the parent repository context!
* **Claude Code Sandbox & Localhost Access**: `claude -p` (headless mode) runs in a sandboxed environment that blocks `127.0.0.1` connections by default. `allowedDomains: ["127.0.0.1"]` does NOT work for IP addresses. The fix is `"allowLocalBinding": true` in `~/.claude/settings.json` under `sandbox.network`. Without this, skill evals that use pytest-docker to start LocalStack on localhost will fail with "Could not connect to endpoint URL" errors.
  * **AWS_PROFILE Conflict**: The `claude -p` subprocess inherits the user's `AWS_PROFILE` env var. When LocalStack test credentials are expected (`AWS_ACCESS_KEY_ID=test`), boto3 tries to use the named profile instead, causing `ProfileNotFound` errors. Runners must strip `AWS_PROFILE` and `AWS_DEFAULT_PROFILE` from the subprocess env before invoking `claude -p`.
  * **Sandbox .git/ Cleanup Blocker**: The sandbox write-deny policy blocks deletion of `.git/` files inside `tmp/eval_sandbox_*/`. Do NOT run `git init` inside eval sandboxes — Claude Code does not need git context bounding (unlike Copilot). Stale `.git/` directories prevent sandbox cleanup on subsequent runs, causing empty sandboxes and "max turns" failures.

## CI/CD & GitHub Actions

* **Provisioning `task` on the runner**: workflows invoke targets as plain
  `task <command>`. The runner must therefore provide the `task` binary before any
  workflow step that uses it — a stock `ubuntu-latest` image does not ship one.
  * **Trade-off**: a vetted setup action is the least code; a pinned installer with
    a checksum (the pattern used for `uv` in `test.yml`) avoids adding a third-party
    action to the supply chain. Pick one deliberately — do not leave it implicit.
  * **Anti-pattern**: aliasing `task` to some other wrapper name to dodge a binary
    name conflict. It couples every workflow and every CI shell script to that
    wrapper's existence, and each one then needs a fallback branch. Invoke the tool
    by its real name.
* **OIDC permissions**: to let a workflow request an OIDC JWT ID token (e.g. for
  cloud authentication), set the workflow permissions explicitly:

  ```yaml
  permissions:
    id-token: write
    contents: read
  ```

* **Conditional Secrets Bypassing**: When workflows require external repository secrets (e.g. `COPILOT_GITHUB_TOKEN`), external PRs (from dependabot, forks, etc.) or standard users lacking service account tokens will immediately fail the pipeline.
  * **Solution**: Bind the secret to an environment property, and use a conditional check `if: ${{ env.SECRET_NAME != '' }}` on the specific job step. This organically skips the authenticated step and allows the rest of the CI suite to pass cleanly without blocking the merge.

## Agent Workflow & Protocols

* **PR Review Gate vs. Auto-Merge Race Conditions**: LLM agents using skills like `/auto-pr` or `/ship` naturally tend to chain `gh pr create` directly with `gh pr merge --auto` to save execution steps. This creates a critical race condition. If the agent proceeds to do a local subagent validation (like checking the PR format) but the GitHub Actions CI finishes first, GitHub's merge queue will automatically merge the unverified PR while the agent is still checking it locally.
  * **Solution**: Always explicitly instruct agents (using `CRITICAL` constraints in the prompt or SKILL instructions) to strictly wait for local validation loops (e.g., Step 3b PR Review) to explicitly return `GREEN` *before* executing any auto-merge commands or waiting for CI.
* **Git Clean for True Resets**: Running `git reset --hard` only resets tracked files. It leaves behind untracked artifacts (like old `mappings.json` files, compiled binaries, or agent temporary files) which can poison future agent sessions.
  * **Solution**: Always couple `git reset --hard` with `git clean -fdx` when rebuilding a clean workspace state to guarantee all untracked files and ignored directories are completely purged.
* **Pre-Flight Environment Checks**: Agents write plans assuming an ideal "clean" state. However, if the local filesystem is dirty from previous tasks, the plan execution will fail.
  * **Solution**: `task repos:reset` MUST be executed logically *before* any planning, analysis, or drift checks occur. Planners cannot trust local file states until this is guaranteed.
* **Destructive CI/Test Workarounds**: During TDD or CI bug fixing, agents must NEVER permanently disable infrastructure layers, bypass security validations, or delete fundamental configuration mounts (like database volume persistence) just to make a failing test pass. This constitutes a severe violation of the "No Faking" protocol.
  * **Solution**: If testing requires a unique state (like an ephemeral, clean database), agents must build a parallel, isolated test configuration (e.g. adding a `-test` suffix to a docker service or mock) rather than corrupting the primary application state. If a change is deemed destructive or impacts historical data, you MUST ask for explicit user consent before proceeding.
* **Artifact-Type Integration Touch Points**: When a plan adds entries to `VALID_ARTIFACT_TYPES`, the integration touch points across `src/brownfield_ai/ledger/artifacts/constants.py` (`SANITIZED_ARTIFACT_TYPES` allowlist consumed by `sanitize.py`), `src/brownfield_ai/ledger/epics/queries.py` (`get_resume_context()` category), and the dashboard frontend (`services/dashboard/frontend/src/types.ts` `ArtifactType` union + `utils/tooltips.ts` + `components/TimelineFilter.tsx`) are non-obvious and easily missed during Dual-Model Plan Review unless they are enumerated explicitly in the plan's scope-enumeration section.
  * **Solution**: Future plans introducing artifact types MUST follow the [Artifact-Type Introduction Checklist](planning_protocol.md#artifact-type-introduction-checklist) in `planning_protocol.md` §2 step 3, which enumerates the four integration touch points (`SANITIZED_ARTIFACT_TYPES` membership, `get_resume_context()` category, test mirrors for both, and dashboard frontend mirrors) as verb-led actionable directives.

## Integration Testing & Mocking

* **Containerized Testing over Mocks**: Deeply mocking external clients (e.g., `boto3`, `psycopg2`, `redis`) using `unittest.mock.MagicMock` inside `pytest` masks underlying infrastructure behavior and network logic, leading to false positives.
  * **Solution**: Avoid using `MagicMock` for external infrastructure interactions. Prioritize true containerized testing. For AWS, use the `moto_server` fixture (LocalStack). For databases like PostgreSQL or caches like Redis, add the respective service to [docker-compose.yml](../docker-compose.yml) and create a `pytest` fixture to handle setup/teardown. Tests should simulate genuine API responses and network latency whenever possible.
* **Test Sandbox Validation Integrity**: When building new verification hooks or sandboxes, early test iterations often mock final assertions (e.g., `assert True, "Pending implementation"`) without verifying underlying network connections. Always verify real state and check for hardcoded positive assertions when debugging false-positive test cases.

## PreToolUse Hook Gotchas

* **Hook Execute Bit (Silent Failure)**: Claude Code silently skips PreToolUse hook scripts that lack the execute bit (`644` instead of `755`). There is no error message — the hook simply does not fire, leaving security enforcement completely disabled. This is especially dangerous for hooks created via the Write tool, which defaults to `644`.
  * **Solution**: Always verify hook permissions after creation: `git ls-files -s .claude/hooks/`. All `.sh` files must be `100755`. Use `git update-index --chmod=+x .claude/hooks/<file>.sh` to fix in git, and `chmod +x` on disk.
* **Host Execution Block False Positives**: The `block-container-escape.sh` hook's regex matches the word `python` anywhere in the Bash command string, including inside `git commit -m` messages, `echo` arguments, and `grep` patterns. This causes false-positive denials for commands like `git commit -m "fix python3 bug"`.
  * **Solution**: Keep blocked keywords (`python`, `python3`) out of the command string. For git commits, put descriptive text in the Bash tool's `description` parameter (which is now properly isolated from command matching) rather than the `-m` message body. Alternatively, rephrase to avoid the keyword (e.g., "host execution block" instead of "python block"). This is a known limitation of regex-based command matching without full shell parsing.

## CI & Shell Scripting Gotchas

* **Bash Parameter Expansion & Word Splitting**: When passing a string of concatenated arguments (e.g., `"pytest -k \"skill1 or skill2\""`) directly to a tool like `docker compose run`, unquoted string variables (`$args`) will undergo bash word splitting. This causes arguments like `or` to be interpreted as positional directories by the underlying tool rather than parts of a single filter string.
  * **Solution**: Always use exact-match bash expansion (`"$@"`) inside wrapper functions to pass arguments securely, and double-quote the invocation: `exec "$@"`.
* **The Danger of Suppressed Linters**: Using `# shellcheck disable=SC2086` to quiet line-expansion warnings can mask critical logic bugs that only trigger under complex conditions (e.g., when a multi-word string is finally passed).
  * **Solution**: Fix linter warnings at the root cause by refactoring the bash script arrays/arguments. Do not suppress shell warnings.
* **Automating CLI Workflows**: When automating GitHub CLI operations (`gh`) within scripts, always use JSON output formats (e.g., `gh pr view --json statusCheckRollup`) rather than raw text. This explicitly prevents interactive pagers from hanging execution and reliably yields parsable structures.
* **Task Shell Aliases**: When needing shell access to containers, use the `task sh:*` aliases instead of raw `docker compose run` commands to ensure proper interactive configuration.
* **`awk -F'/'` Field Index Off-by-One**: When using `awk -F'/'` to extract path components, relative paths (e.g., `repos/analytics/src/datalake/pipelines/monetization/file.py`) start at field `$1`, not `$0`. Miscounting fields is easy when paths are deep — `$5` extracts the literal directory name `pipelines` while `$6` extracts the actual pipeline name `monetization`. Always count fields explicitly from `$1` when working with relative paths.
  * **Solution**: Write a quick test: `echo "the/path" | awk -F'/' '{print NF; for(i=1;i<=NF;i++) print i, $i}'` to verify field positions before using them in production scripts.

## Python CLI & Environment

* **Defopt Function Names and Python Builtins**: When registering CLI sub-commands via `defopt.run([...])`, function names like `next` or `index` shadow Python builtins. This causes subtle bugs if the module body calls the built-in `next()` (e.g., on an iterator) after defining the CLI function.
  * **Solution**: Follow the `list_docs_cli` naming convention from `chromadb_collection.py` — use `next_plan`, `index_epics`, etc. `defopt` automatically converts underscores to hyphens for the CLI sub-command name (`next_plan` → `next-plan`).
* **Python Defopt Keyword Mappings**: The `defopt` CLI parser translates variable names into argument flags. Refactoring Python variables to avoid built-in keyword warnings (like renaming `format_` to `output_format` to dodge `A002`) will unintentionally rename the CLI flag from `--format` to `--output-format`.
  * **Solution**: To safely handle built-in keywords while keeping the intended CLI mapping structure, natively append an underscore: use `format_` which `defopt` elegantly interprets as `--format`.
* **Luigi `> 3.5.2` Packaging Bug**: `luigi` releases after `3.5.2` ship a broken sdist/wheel that drops the `luigi.contrib` sub-packages, including `mrrunner`. Any code importing from `luigi.contrib` breaks on upgrade, and the only alternative to pinning is building luigi from source. See [spotify/luigi#3398](https://github.com/spotify/luigi/issues/3398).
  * **Why this is recorded here**: the constraint is enforced by an `ignore` block in [.github/dependabot.yml](../.github/dependabot.yml), but a config entry cannot carry the reasoning. luigi is currently a dependency in none of the four requirements files, so that block matches nothing and is inert — it is retained so the bound re-applies automatically if luigi ever returns. Note the bound suppresses security updates above `3.5.2` as well as version updates, so if luigi does return, revisit the range rather than simply re-adding the dependency.

## AWS & Moto (LocalStack) Specifics

* **Redshift Data API Execution States**: When using the `moto` server (LocalStack) to mock the `redshift-data` Boto3 client, queries executed via `execute_statement` may hang indefinitely in the `STARTED` status instead of progressing to `FINISHED`.
  * **Solution**: In local development/testing environments, when polling `describe_statement` for status updates, explicitly check for the `STARTED` status alongside a check for the `AWS_ENDPOINT_URL` environment variable. If both are true, safely break the polling loop to prevent the test suite from hanging.

### Workspace Hygiene

See [docs/maintenance_guidelines.md](maintenance_guidelines.md) for full workspace protocols regarding environment resets and tmp file management.

* **Root Directory Pollution via Bash Redirection**: When debugging or capturing command outputs (especially from Docker wrappers or shell scripts), agents frequently use native bash redirection (e.g., `> output.txt`), defaulting to the workspace root. This violates Principle 10 (Artifacts).
  * **Solution**: The Orchestrator or delegating agent must proactively instruct sub-agents to route all transient outputs to the `tmp/` directory (e.g., `> tmp/debug_logs/output.txt`). Treat the root directory as strictly read-only for temporary artifacts.

## Pytest & LocalStack Mocking

* **pytest-docker State Bleeding**: If using `pytest-docker` to spin up a mock LocalStack container (Moto server), binding the container fixture (`docker_compose_file`/`docker_ip`) to `scope="function"` will cause the Docker daemon to frantically recreate the container hundreds of times during test execution. This creates severe race conditions and `No such container` crashes.
  * **Solution**: Scope the container to `"session"` so it boots once. However, to prevent AWS mock state from bleeding across tests (e.g., Test A creating a DynamoDB table that breaks Test B), implement a `try...finally` block in the test fixture to trigger LocalStack's rest API: `requests.post(f"{url}/moto-api/reset")`. This completely resets all AWS mocks silently and instantly in 100ms.

* **Testing Global AWS Mocks**: If AWS authentication rules are changed, remember that old tests might only be mocking specific clients. If `aws_vault_auth.sh` scripts are updated, they must be tested outside of localstack mocking contexts, or the mock environments must explicitly capture STS behavior.

## Claude Code Sandbox & Headless Execution

* **Container Path vs Host Path for SQLite**: When a Docker volume mount maps `~/.brownfield-ai:/brownfield-ai`, scripts inside
  the container must use the container-side path (`/brownfield-ai/ledger_index.db`), not the host path
  (`~/.brownfield-ai/ledger_index.db`). Use the container-side mount path (e.g., `/brownfield-ai/ledger_index.db`) in scripts
  that run inside Docker, and provide an environment variable override (e.g., `LEDGER_DB_PATH`) for flexibility.
  For workspace-relative paths in other scripts, use `brownfield_ai.system.context.get_workspace_root()`.

## Testing & Environments

* **Moto Eventual Consistency (Race Conditions)**: Mocked AWS environments via background tasks (Moto/Localstack) require a fast-running sync loop. Pytest will query a database milliseconds before the Moto server registers its creation. Avoid arbitrary `time.sleep()` calls and implement Synchronous Validation Hurdles (e.g. `try/except client.get_database()` to force a block).
* **Relative Artifact Bounds (CI)**: Never script log/sandbox dumps to the OS absolute root `/tmp/` — this breaks Docker CI runners due to permission constraints. Always write dynamically to the repository root `tmp/` folder instead.
* **Subagent Eval Assertions**: Never assert exact block-formatting or multiline responses for Agent evaluations (`test:skills`). Assertions should strictly leverage `in` substring validation for core extracted facts to combat inherent LLM non-determinism.

## Gemini CLI — Auth and Model Selection

* **PREVIEW models require `GEMINI_API_KEY` auth; OAuth must use STABLE models**: Preview models (e.g., `gemini-3.1-pro-preview`, `gemini-3-flash-preview`) on the OAuth-personal consumer backend share a small server-side compute pool that frequently exhausts. The 429 *"No capacity available for model gemini-3.1-pro-preview"* error on OAuth is server-side compute exhaustion on that pool, NOT a personal quota violation. Two operator paths, pick one:
    1. **`GEMINI_API_KEY` (recommended for preview models).** Set `GEMINI_API_KEY` and run `/auth` inside the CLI, pick AI Studio. API-key requests use AI Studio's separate, larger capacity pools and 429/503 events on preview models are not observed in practice. This is the path the reviewer agents are tested against.
    2. **OAuth (Google One AI Pro) — STABLE models only.** If you stick with OAuth, use stable model names (`gemini-3.1-pro`, `gemini-3-flash`) instead of the `-preview` variants. Stable models have much larger compute allocations on the OAuth backend.
* **Flash alias `model` field MUST include `-preview` suffix when targeting preview**: In project-local `customAliases`, the `modelConfig.model` for the Flash *preview* alias must read `"gemini-3-flash-preview"`, not `"gemini-3-flash"`. The bare `gemini-3-flash` is rejected as `ModelNotFoundError` by the API. Pro preview (`gemini-3.1-pro-preview`) requires the same suffix. A wrapper-level Pro→Flash fallback that resolves to a misspelled alias will mask the original Pro failure with `ModelNotFoundError`, making diagnosis harder. Lint cannot catch this — only an integration test that exercises real alias resolution will.
* **Wrapper-level Pro→Flash 429/503 fallback is belt-and-suspenders**: With API-key auth on preview, the `gemini-3.1-pro-* → gemini-3-flash-high` single-shot fallback in `scripts/agent-cli/gemini-review.sh` rarely fires. It remains in place for residual capacity events and as the in-line recovery for any OAuth user who tries preview anyway.
* **Gemini CLI Node v8 OOM on large diffs**: The Gemini CLI Node bundle in the `agent-cli` container hits `FATAL ERROR: Ineffective mark-compacts near heap limit` when processing review payloads ≳3500 lines. Workarounds: split the diff, raise `NODE_OPTIONS=--max-old-space-size=...`, or run the review on the host (`task agent:review:gemini:local`) where heap is bounded by the host node.

## Code Generation Tools & Hacks

* **AST Unparse Destructiveness**: Using Python's native `ast.unparse()` to rewrite files after AST modification physically destroys all inline comments (`#`) and layout styling (like blank lines). It cannot be used safely for non-destructive refactoring.
* **Regex String Mutation**: Attempting to inject multi-line AST structures (like type hints `) -> None:`) via crude Regex or `.replace()` string scripts is incredibly frail, prone to duplication, and raises systemic `invalid-syntax` exceptions.
* **Solution**: When enforcing static analysis sweeps (like bulk docstring generation or structural type enforcement), do not rely on aggressive string hacking scripts. Fall back to IDE/Language Server native auto-fix flags (e.g. `ruff check --fix`) if possible, or gracefully update exclusion ranges (`extend-exclude`) in the `pyproject.toml` configuration.
