# brownfield-ai

**Add agentic capabilities to the repositories you already have — without
touching them.**

Most AI-coding tooling assumes a greenfield repo, or asks you to commit agent
configuration into every service you own. `brownfield-ai` inverts that. It is a
standalone harness that clones your existing ("brownfield") repositories as
nested checkouts under [repos/](repos/) and layers skills, agents, protocols, and
long-term memory *on top of them*. Your upstream repos stay exactly as they are:
no `CLAUDE.md` to merge, no `.claude/` directory to review, no PR to a codebase
whose owners never asked for one.

## Start here: the AI Coding Readiness Assessment

The first thing to run against a repository you have just added is the
readiness assessment inside the
[`repos-research`](workflows/repository-maintenance/prompts/repos-research.prompt.md)
prompt. It reads the repo the way a new senior engineer would — build and test
entry points, dependency freshness, conventions, documentation gaps, the parts
that are hostile to automated change — and writes a durable guide to
[docs/repo-guides/](docs/repo-guides/) plus matching rule files under
`.claude/rules/` and `.github/instructions/`. Every later agent invocation reads
those guides first, so the assessment is what converts "an LLM guessing at your
codebase" into "an agent that knows it".

## What is in the box

- **Skills** ([.claude/skills/](.claude/skills/) and `workflows/*/skills/`) —
  scoped, reusable capabilities: AWS schema retrieval, GitHub-wide code search,
  PR shipping, repository research.
- **Protocols** ([CLAUDE.md](CLAUDE.md) and [docs/](docs/)) — delegation,
  planning, and verification rules that keep an agent from self-approving its
  own work.
- **An execution ledger** — durable epic/plan/checkpoint state so multi-session
  work survives context loss.
- **Long-term memory** — a local ChromaDB instance shared across your workspaces.
- **A hardened execution boundary** — containerized tooling plus PreToolUse
  hooks, so agent-run commands cannot escape the sandbox.

## Point it at your repositories

The harness ships with **no organisation and no repository list** — it works
against whatever you point it at. Two variables control this:

| Variable | Meaning | Set by |
|----------|---------|--------|
| `BROWNFIELD_ORG` | The GitHub org or username that owns your repos | [The setup script](#step-3-run-the-setup-script) prompts for it |
| `BROWNFIELD_REPOS` | Space-separated repo names to clone | Passed per invocation |

`BROWNFIELD_ORG` is the one answer the harness cannot work without: it decides
which repositories `task repos:clone` fetches *and* which org the
[`github-search`](.claude/skills/github-search/SKILL.md) skill queries with
`gh search code --owner`. The setup script asks for it first and writes it to
`.envrc`, defaulting to your `gh` login when the GitHub CLI is available. If you
skip it, `task repos:clone` refuses to run rather than silently doing nothing,
and `github-search` asks you which org to search.

Then clone the repositories you want the agents to work on:

```bash
task repos:clone BROWNFIELD_REPOS="api web analytics"

# …or override the org for a one-off, without touching .envrc:
task repos:clone BROWNFIELD_ORG=acme BROWNFIELD_REPOS="api web"
```

Add `DRY_RUN=1` to preview without touching the network. `repos:clone` clones
what is absent and fetches what is present, so it is safe to re-run. See
[repos/README.md](repos/README.md) for the nested-checkout convention.

> **Note:** `BROWNFIELD_ORG` is *your* org — it has nothing to do with
> `teatrie`, which is only where this harness is published.

## Prerequisites

> **Already have Homebrew, Git, and Task?**
> [Clone the repository](#step-2-get-the-repository), then skip to
> [Step 3: Run the setup script](#step-3-run-the-setup-script).
>
> **Have Homebrew but missing tools?** Run this one-liner:
>
> ```bash
> brew install git gh jq go-task/tap/go-task
> ```
>
> Then [clone the repository](#step-2-get-the-repository) and skip
> to [Step 3](#step-3-run-the-setup-script).

### Step 1: Install Homebrew

[Homebrew](https://brew.sh/) is the package manager used to install
all other dependencies:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### Step 2: Get the repository

Choose one of the following options:

#### Option A: Clone with Git (recommended)

Most developers already have `git` installed. If not, install it
first:

```bash
brew install git

# Or via Xcode Command Line Tools (includes git)
xcode-select --install
```

Then clone and enter the repository:

```bash
git clone https://github.com/teatrie/brownfield-ai.git
cd brownfield-ai
```

#### Option B: Clone with GitHub CLI (`gh`)

If you have the [GitHub CLI](https://cli.github.com/) installed,
this option also satisfies the `gh` dependency used later by the
[setup script](#what-the-setup-script-installs) to generate your
`GH_TOKEN`:

```bash
# Install gh via Homebrew (if not already installed)
brew install gh

gh repo clone teatrie/brownfield-ai
cd brownfield-ai
```

> **Don't have `gh` yet?** No worries — the setup script in Step 3
> will detect it is missing and offer to install it via Homebrew.

#### Option C: Download as ZIP (no Git required)

If you do not have `git` or `gh` and prefer not to install them
yet, you can download the repository as a ZIP archive:

1. Open
   <https://github.com/teatrie/brownfield-ai/archive/refs/heads/main.zip>
   in your browser (or use `curl`):

   ```bash
   curl -L -o brownfield-ai.zip https://github.com/teatrie/brownfield-ai/archive/refs/heads/main.zip
   ```

2. Extract the archive and enter the directory:

   ```bash
   unzip brownfield-ai.zip
   cd brownfield-ai-main
   ```

> **Note:** The ZIP download is a snapshot — it does not include Git
> history. You will not be able to create branches or push changes
> until you initialize a Git repository (`git init`) and add the
> remote. Options A or B are recommended for active development.

### Step 3: Run the setup script

The setup script will check for missing tools, offer to install
them via Homebrew, and configure your environment variables:

```bash
bash scripts/setup_env.sh
```

> If you already have Task installed, you can run `task setup:env`
instead.

### What the setup script asks you

After the tool-installation prompts, the script writes `.envrc` and asks for:

1. **`BROWNFIELD_ORG`** — the GitHub org or username whose repositories you want
   the agents to work on. Defaults to your `gh` login if the GitHub CLI is
   installed. This is the variable that makes the harness *yours*; see
   [Point it at your repositories](#point-it-at-your-repositories).
2. **`AWS_PROFILE`** — optional, only needed for the AWS schema skills. The
   script lists the profiles it finds in `~/.aws/config`.
3. **`AWS_REDSHIFT_DB_USER`** — optional, blank to skip.
4. **`USER_EMAIL`** — used to namespace your scratch output (e.g. Athena result
   prefixes). Defaults to your `git config --global user.email`.

`GH_TOKEN` is extracted automatically via `gh auth token`. Re-run the script any
time to change an answer; it rewrites the matching `.envrc` line in place.

### What the setup script installs

The script will detect and prompt to install the following:

- **Docker** — the script will offer to install
  **[Colima](https://github.com/abiosoft/colima)** + Docker CLI, a
  free, open-source, lightweight container runtime that requires no
  commercial license.

  > Alternatively, you can decline and manually
  install
  [Docker Desktop for Mac](https://docs.docker.com/desktop/install/mac-install/)
  instead — Docker Desktop requires a commercial license. Speak with
  your manager about obtaining one.

- **[Task](https://taskfile.dev/)** (`go-task`) — build tool used
  for linting, testing, and orchestration. Once installed, you can
  run `task setup:env` instead of `bash scripts/setup_env.sh` for
  future setup runs. The script also compares your `task` against
  the version CI pins and warns when you are behind: a local Task
  older than the runner's can accept Taskfile syntax that fails in
  CI, or reject syntax that works there. If you do not use
  Homebrew, `npm install -g @go-task/cli` is the go-task project's
  own npm build and tracks upstream releases.
- **[direnv](https://direnv.net/)** — manages environment variables.
  The setup script will offer to add the shell hook to your shell
  rc file (`~/.zshrc` or `~/.bashrc`) and runs `direnv allow .`
  automatically after configuring your environment.
- **[jq](https://jqlang.github.io/jq/)** — lightweight command-line
  JSON processor used by security hooks and agent CLI scripts for
  robust JSON parsing.
- **[GitHub CLI](https://cli.github.com/)** (`gh`) — used to
  authenticate and generate a `GH_TOKEN` for repository operations.
  The setup script extracts the token automatically via
  `gh auth token`.

### Keeping your tools current

Once the tool checks have run, the script reports any of the
formulae it manages that Homebrew has a newer version of, and
prints the `brew upgrade` command that fixes them.

This exists because a `command -v` check only answers
present-or-absent, never "current" — so it is entirely possible to
sit on a months-old binary for a long time without noticing. If
Homebrew looks out of date to you, check `brew info <formula>`
before switching package managers: the arrow in
`go-task: 3.48.0 → stable 3.52.0` is telling you an upgrade is
available locally, not that the formula itself is behind upstream.

### Optional: aws-vault

Some advanced data engineering skills and workflows require AWS
access. If you need these capabilities, the setup script will offer
to install **aws-vault** via Homebrew. After installation, follow
the [aws-vault README](https://github.com/99designs/aws-vault#usage)
to configure your SSO profiles.

### Optional: uv

If you plan to run the test suite locally via `task test:setup` /
`task test:staged`, the setup script will offer to install
**[uv](https://docs.astral.sh/uv/)** via Homebrew. `uv` is Astral's
Rust-based Python package manager — it provisions Python 3.12 and
creates the `.venv/` used by host-run tests (the host-side
exceptions are listed with their reasons in
[CLAUDE.md](CLAUDE.md) §11). If you only consume this repo's
skills and prompts without running the test suite locally, you
can skip this tool.

> **Do not install `uv` from npm.** On the npm registry that name
> belongs to an unrelated UTF-8 validation library, not Astral's
> Python package manager. Installing it would satisfy the setup
> script's `command -v uv` check and then fail confusingly later
> inside `task test:setup`. Use Homebrew, `pip install uv`, or
> Astral's own installer.

### Required: Agent

You will need an agent! This repository has been tested with:

- **[Claude Code](https://claude.com/product/claude-code)** (Anthropic CLI — primary, recommended)
- **[Visual Studio Code](https://code.visualstudio.com/)** with **GitHub Copilot**
- **GitHub Copilot CLI** ([Install Guide](https://docs.github.com/en/copilot/github-copilot-cli))
- **Codex CLI** (`@openai/codex`): `npm install -g @openai/codex` — OpenAI code review bridge

See [docs/local_development.md](docs/local_development.md) for setup
details.

## 🤖 AI Platform Architecture

This repository is **platform-neutral** and supports multiple agent
platforms. Skills, agents, and protocols are written to work across
Claude Code, GitHub Copilot, Gemini CLI, and Codex CLI without
platform-specific hardcoding.

### Tested Platforms

| Platform | Status | Model Selection | Parallel Subagents |
|----------|--------|----------------|--------------------|
| **Claude Code** | Primary | Per-subagent (`haiku`/`sonnet`/`opus`) | Yes |
| **GitHub Copilot** (VS Code & CLI) | Supported | Session-level model picker | No |
| **Gemini CLI** | Supported | Session-level (`--model` / `auto`) | No |
| **Codex CLI** | Supported | Profile-defined (`~/.codex/config.toml`) | No |

### Agent Configuration

- **Skills**: [.claude/skills/](.claude/skills/) — registered skills
  invokable via `/skill-name` on Claude Code. Other platforms can
  load these on-demand via file path.
- **Agents**: [.claude/agents/](.claude/agents/) — role definitions
  with `model_tier` metadata for cost-effective delegation.
- **Rules**: [.claude/rules/](.claude/rules/) — repo-specific
  constraints matched by `paths:` glob patterns (Claude Code).
  Copilot equivalents live in `.github/instructions/`.
- **Workflow Skills**: `workflows/*/skills/` — deferred skills not
  loaded into context until explicitly read. Keeps context lean.
  To invoke a workflow skill in Claude Code, type `@` followed by
  the skill name (e.g., `@claude-review`) to find and load it via
  the file picker. Alternatively, use natural language and
  explicitly name the skill (e.g., "run workflow skill
  `claude-review` on the current changes").

See the [agent-team skill](.claude/skills/agent-team/SKILL.md) for
the tier-to-model resolution protocol across platforms.

## 🚀 Get Started (Quick Start)

1. **Follow the [Prerequisites](#prerequisites)** to clone the repo,
   install Homebrew, and run the setup script.

2. **Launch your agent** inside the `brownfield-ai` folder:
   - **Claude Code terminal** (recommended): Run `claude` in your
     terminal.
   - **Claude Code in VS Code**: Install the
     [Claude Code extension](https://marketplace.visualstudio.com/items?itemName=anthropic.claude-code)
     and open the Claude panel.
   - **VS Code Copilot**: Open the folder in VS Code and start a
     *New Copilot Chat*.
   - **Copilot CLI**: Run `gh copilot` in your terminal.

3. **Trigger the welcome screen** to verify your setup by saying
   `hello!` in the chat.
4. **Start prompting away!** See the `workflows/<domain>/prompts/` directories for templates and [.claude/skills/](.claude/skills/) for ideas on what the agent can do.
5. **Have fun! 🎉** Share your creations, experiment with new agents and models, and enjoy the AI journey!

### Advanced: Agent Teams with tmux (Claude Code)

Claude Code supports
[Agent Teams](https://code.claude.com/docs/en/agent-teams) —
multiple Claude instances coordinating via shared task lists and
direct messaging. One session acts as the team lead, spawning
teammates that work independently in parallel.

**1. Enable agent teams** in `~/.claude/settings.json`:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  },
  "teammateMode": "tmux"
}
```

Setting `teammateMode` to `"tmux"` gives each teammate its own
split pane. The default `"auto"` uses split panes if already inside
tmux, otherwise runs in-process. Use `"in-process"` to keep
everything in a single terminal (cycle with Shift+Down).

**2. Install tmux** (required for split-pane mode):

```bash
brew install tmux    # macOS
```

**3. Launch and create a team**:

```bash
tmux new-session -s agents
claude
```

Then ask Claude to create a team:

```text
Create an agent team with 3 teammates to handle this refactor:
one for implementation, one for tests, one for review.
```

Claude spawns teammates in separate tmux panes. Click a pane to
interact with that teammate directly.

**Key features:**

- Teammates share a task list and message each other directly
- The lead coordinates, assigns tasks, and synthesizes results
- Each teammate loads `CLAUDE.md`, skills, and MCP servers
  automatically
- Use `--teammate-mode in-process` to override for a single session

For full documentation, see the
[Claude Code Agent Teams guide](https://code.claude.com/docs/en/agent-teams).
New to tmux? See the
[tmux Getting Started Guide](https://github.com/tmux/tmux/wiki/Getting-Started).

## 🧠 Agent Skills

Skills are located in [.claude/skills/](.claude/skills/) and provide specialized capabilities to the agent.

> **📚 Read the [Prompt Examples](./docs/prompt_examples.md)** for a full list of capabilities and how to trigger them using natural English.

> **💡 Best Practice - Combating Context Drift:**
> Large Language Models naturally suffer from *recency bias* in long conversations, causing them to "forget" strict repository rules located in system prompts like [CLAUDE.md](CLAUDE.md). If you notice your agent skipping protocols (e.g., hallucinating, faking success, or committing code directly to main), use one of the following prompts to immediately halt the agent and force it to reload the core rules:
>
> > *"align"*
> > *"refocus"*
> > *"refresh rules"*
>
> *(Triggers the `protocols` skill)*

---

## 💾 Local Memory Infrastructure

The project includes a local **[ChromaDB](https://www.trychroma.com/)** instance to serve as long-term memory for agents. ChromaDB is an open-source AI-native vector database that embeds text into vector representations, allowing agents to perform semantic searches and recall relevant context from previous sessions.

> **Note:** This memory is **local and independent** for each developer. It is completely optional—you decide what context to store. Your memory database is not committed to the repository, so your agent's long-term context remains private to your machine.

### Data Persistence

The ChromaDB vector database persists data globally in the `~/.brownfield-ai/chroma_data/` directory. By storing memory globally in your user directory instead of the project folder, the ChromaDB instance serves as a central knowledge base shared across all your development workspaces.

> **⚠️ WARNING:** Do **NOT** delete the `~/.brownfield-ai/chroma_data/` directory. It contains your global knowledge base. If you delete this directory, you will permanently lose all stored agent memories and context.

### Quick Start

The AI agent will **automatically start the database** on its first memory usage. However, you can also manage it manually if needed.

1. **Start the global database** (Optional):

    ```bash
    docker compose -f docker-compose.chromadb.yml up -d
    ```

    - **Global ChromaDB**: `http://localhost:8000`

2. **Verify**:

    ```bash
    docker compose -f docker-compose.chromadb.yml ps
    ```

See [taskfiles/chromadb.yml](taskfiles/chromadb.yml) for all
available ChromaDB tasks. See
[Prompt Examples — Agent Memory](./docs/prompt_examples.md#-agent-memory) for how to trigger
memory operations via natural language.

---

## 🛡️ Core Protocols

To ensure quality and prevent hallucinations, this repository enforces strict agentic protocols:

- **[Verification Protocol](./docs/verification_protocol.md)**: Orchestrators must delegate testing/linting to sub-agents and require a second reviewer agent to validate results.
- **[Planning Protocol](./docs/planning_protocol.md)**: The Planner and Orchestrator must not write code directly. Plans drafted by the Planner must be reviewed by a different model family before the Orchestrator executes them.
- **[Delegation Protocol](./docs/delegation_protocol.md)**: Agents must use the least-privileged toolset (e.g., `explore` before `task`) and escalate only when necessary.
- **[Tech Debt](./docs/tech_debt.md)**: Track all shortcuts and refactoring needs here.

### Securing the Repository for Claude Code

Claude Code runs with broad filesystem and shell access by default.
This repository ships a hardened settings configuration and a
verification workflow to lock down the agent's execution boundary.

**Setup steps:**

1. **Copy the reference settings** from
   [`docs/reference-settings/`](docs/reference-settings/) to your
   local environment. The README in that directory explains the
   three-layer settings hierarchy (global, project-shared,
   project-local) and what belongs in each layer.
2. **Review the container security model** at
   [`docs/container_security.md`](docs/container_security.md) to
   understand the 4-layer defense-in-depth architecture (settings
   gating, PreToolUse hooks, host-side gate scripts, container
   entrypoint validation) that enforces execution isolation.
3. **Run the security verification prompt** to audit your settings
   and confirm all layers are functioning:

   ```text
   @workflows/repository-maintenance/prompts/security-verification.prompt.md
   ```

**Key security features:**

- **Three-tier permission model** (allow / ask / deny) — scoped
  directory allows for routine work, interactive prompts for
  infrastructure changes, hard denies for security-critical files.
- **Sandbox configuration** — filesystem read/write boundaries,
  network isolation, restricted destructive commands.
- **PreToolUse hooks** — block direct Python execution, Terraform
  escapes, and Docker container escapes before they reach the shell.
- **Credential protection** — deny rules for agent sessions, OAuth
  tokens, AWS credentials, and SSH keys across all settings layers.

See [`docs/reference-settings/README.md`](docs/reference-settings/README.md)
for the full settings architecture and reference files.

### Recommended Workflow Prompts

The repository contains dedicated `workflows/<domain>/prompts/` folders which house reusable Markdown templates for common operations (e.g., auto-piloting tools or initializing multi-agent teams). You can pass these templates directly into your chat or CLI interfaces.

#### Multi-Agent Team Execution

To properly enforce the Triangle of Verification and Multi-Agent Orchestration protocols out of the gate, utilize the following template to initialize your multi-agent session:

> Initialize a multi-agent team to handle a `[INSERT SKILL OR TASK HERE]` request for the "[INSERT SERVICE]" service.
>
> Please adhere strictly to our core protocols and delegate responsibilities using the following agent roles:
>
> 1. **Planner**: Begin by analyzing the requirements, reviewing [docs/planning_protocol.md](docs/planning_protocol.md), and drafting the implementation plan. You must request a cross-family review before proceeding.
> 2. **Orchestrator**: Once the plan is approved, take over execution. Do not write code or run CLI tools yourself. Delegate tasks following the Delegation (Least Privilege) and Verification protocols.
> 3. **Executors**: Implement the code and run necessary task commands (e.g., `task lint` or `terraform plan`).
> 4. **Reviewers**: Validate the outputs from the Executors.
>
> Please begin with the Planner drafting the plan and invoking the cross-family reviewer.

**Relevant References:**

- [Planner Agent](.claude/agents/planner.md)
- [Orchestrator Agent](.claude/agents/orchestrator.md)
- [Planning Protocol](docs/planning_protocol.md)
- [Delegation Protocol](docs/delegation_protocol.md)
- [Verification Protocol](docs/verification_protocol.md)

#### Standard / Single-Agent Execution

For everyday requests that may not require a full multi-agent orchestration team, it is still crucial to ensure the LLM does not take dangerous shortcuts. You should append an explicit reminder to follow the protocols to any standard prompt:

> Please handle the following task: [INSERT TASK DESCRIPTION]
>
> Please adhere strictly to our core protocols (CLAUDE.md). Prioritize correctness and protocol adherence over speed, and do not skip mandatory steps (like repos:reset, strict verification, or tmp/ branch usage).

## 🛠️ Development

### Local Testing & Agent Evaluation

We use Pytest. `test:scripts` and `test:brownfield_ai` run in the `pytest-cli` Docker container; a small set of exceptions runs host-side in a local `.venv/`, listed with their reasons in [CLAUDE.md](CLAUDE.md) §11. Skills are evaluated headlessly against your configured agent (Claude Code, Copilot, or Gemini).
**For full instructions on setting up agent credentials and running the evaluation pipeline, please see [docs/local_development.md](./docs/local_development.md).**

### Directory Structure

- [.claude/agents/](.claude/agents/): Custom agent role definitions and specialized instructions.
- [.claude/skills/](.claude/skills/): Agent skill definitions (YAML/Markdown docs).
- [.github/](.github/): GitHub Actions workflows and IDE-specific agent instructions.
- [ci/](ci/): Continuous Integration scripts (e.g., `lint_changed.sh`, `test_changed.sh`).
- [docker/](docker/): Dockerfiles for isolated agent execution and CI/CD utility services (see [Docker Configuration](./docker/README.md) for details).
- [docs/](docs/): Core protocols, learnings, and architecture documentation.
- `workflows/<domain>/prompts/`: Reusable Markdown prompt templates for interacting with agents.
- [repos/](repos/): Cloned repositories workspace for exploration and modifications.
- [scripts/](scripts/): Python scripts for memory management, schema extraction, and automation.
- [src/](src/): Python source code and shared utilities (e.g., the execution ledger).
- [taskfiles/](taskfiles/): Taskfile definitions for linting, testing, and maintenance.
- [tests/](tests/): Unit tests and evaluator test cases for all Python features and agent skills.
- [workflows/](workflows/): Domain-Driven Design (DDD) agent skills routing structure.
- [services/](services/): Internal application services (e.g., dashboard).
- `tmp/`: Temporary directory for artifacts and agent working states.
- [AGENT.md](AGENT.md): Cross-platform agent entry point — redirects to `CLAUDE.md`.
- [CLAUDE.md](CLAUDE.md): Main Agent Guidelines and Core Protocols.
- [GEMINI.md](GEMINI.md): Gemini CLI agent entry point — redirects to `CLAUDE.md`.
- [Taskfile.yml](Taskfile.yml): Root go-task definitions.
- [pyproject.toml](pyproject.toml): Python project configuration (ruff, pytest, mypy).
- [pytest.ini](pytest.ini): Pytest configuration.
- [requirements.txt](requirements.txt): Python dependency pins.
- [docker-compose.yml](docker-compose.yml): Infrastructure definition for agent containers (`python-cli`, `pytest-cli`, `agent-cli`).
- [docker-compose.chromadb.yml](docker-compose.chromadb.yml): Infrastructure configuration for the global conversation memory system.
- `todo-plan.md`: User-facing TODO scratchpad for follow-up tasks (gitignored).

### Linting

We enforce strict linting for all code and documentation. You can instruct your agent to handle these checks for you:

- *"Run the linter on the files I just changed."* (`task lint:changed`)
- *"Fix all formatting and linting issues in the python scripts."* (`task lint:fix`)
- *"Run all linting checks across the entire repository."* (`task lint`)

Alternatively, you can run the commands manually:

```bash
task lint          # Run all linters (Markdown, YAML, Python, Shell, Docker)
task lint:changed  # Run linters only on changed files (Recommended)
task lint:fix      # Auto-fix issues
task lint:python   # Run ruff on Python scripts
task lint:yaml     # Run yamllint on YAML files
task lint:markdown # Run markdownlint on Markdown files
task lint:shell    # Run shellcheck on Shell scripts
task lint:docker   # Run hadolint on Dockerfiles
task lint:json     # Run jsonlint on JSON files
```

> **Note:** You **MUST** run `task lint:changed` before pushing your branch. The CI gate ([ci/lint_changed.sh](ci/lint_changed.sh)) will reject any lint failures.

### Testing

Tests are executed headlessly. Most targets — including `test:scripts` and `test:brownfield_ai` — run in the `pytest-cli` Docker container; a small set of exceptions runs host-side in a local `.venv/`, listed with their reasons in [CLAUDE.md](CLAUDE.md) §11. Run `task test:setup` once to initialize the venv before your first run. You can instruct your agent to run these for you:

- *"Run the tests for the files I just changed."* (`task test:changed`)
- *"Run the complete test suite."* (`task test`)
- *"Run all the python script tests."* (`task test:scripts`)

Alternatively, you can run the commands manually:

```bash
task test                  # Run all suites in the Taskfile.yml test: aggregate
task test:changed          # Run tests only for changed files (Recommended)
task test:skills           # Run tests for all skills
task test:scripts          # Run tests for all python scripts
task test:brownfield_ai    # Run brownfield_ai tests (Docker/LocalStack)
```

> **Note (CI):** The GitHub Actions pipeline automatically runs `test:scripts`. However, `test:skills` is currently configured to conditionally skip tests if no agent credentials (`ANTHROPIC_API_KEY`, `COPILOT_GITHUB_TOKEN`, `GEMINI_API_KEY`, or `OPENAI_API_KEY`) are present. Once a dedicated service account credential is provisioned for CI, this bypass will be removed to enforce strict PR validations for agent evals.

### Pull Requests & Shipping

This repository provides two primary skills to automate your deployment workflow and enforce code review checkpoints before finalizing changes.

#### `auto-pr` (Single Changeset)

> *"I am done with my changes, please package them into a PR."*
> *"Push these updates to a new branch, run tests, and open a PR."*
*(Triggers the `auto-pr` skill: Use when you have been working on a single cohesive feature or fix and are ready to create a branch, commit your working tree, wait for validation tests, and open a Pull Request).*

#### `ship` (Grouped Sequential Changesets)

> *"I have a lot of dirty files. Split my working directory up into logical PRs."*
> *"Run the ship command to group my changed files."*
*(Triggers the `ship` skill: Use when your working tree contains multiple disparate concepts — e.g., you refactored an infrastructure module, wrote a new python script, and updated some documentation. The agent will logically split your changes, create a sequence of isolated branches, and open an individual Pull Request for each group).*

### Continuous Integration & Merge Queue

This repository enforces a **Merge Queue** (Merge Group) via GitHub Actions. When you click "Merge" on an approved Pull Request:

1. The PR is placed into a queue rather than merging directly into `main`.
2. A temporary branch is created combining your PR with the latest `main`.
3. The CI suite ([`.github/workflows/ci.yml`](.github/workflows/ci.yml) and [`.github/workflows/test.yml`](.github/workflows/test.yml)) runs one final time.
4. Only if all checks pass will the code be pushed to `main`.

Always ensure `task lint` and `task test` pass locally before pushing to avoid tying up the queue with failures.

#### Enabling Actions on your own clone or fork

Both workflows are built to run with **no repository secrets and no
OIDC**, so you can enable Actions without any credential setup:

- Neither workflow requests `id-token` permission or configures a
  cloud identity provider — there is no OIDC trust relationship to
  establish.
- Both declare `permissions: contents: read`.
- Neither uses `pull_request_target`, so pull requests from forks
  never execute with access to secrets.
- The only `secrets.*` references are two **optional** agent
  credentials on the `test-skills` job.

`test-skills` short-circuits every step when both `ANTHROPIC_API_KEY`
and `COPILOT_GITHUB_TOKEN` are absent, so it is safe on a public fork
and on Dependabot pull requests. Be aware that it then reports
**success rather than skipped**, because the gate sits at step level
rather than job level. Do not make `test-skills` a required status
check unless you have configured credentials — the comments in
[`test.yml`](.github/workflows/test.yml) describe how to promote the
gate to a job-level `preflight` if branch protection needs to
distinguish "ran and passed" from "skipped".

Optional secrets, needed only if you want skill evals to run in CI:

| Secret | Enables |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude Code skill evals |
| `COPILOT_PAT_TOKEN` | GitHub Copilot CLI skill evals |

If you configure either one, the `github-search` evals additionally
require a `BROWNFIELD_ORG` value in the job environment — they are
org-parameterized by design so that they never assert against this
harness's own repository.

### Repository Cleanup

Use these tasks to reset or clean your local environment:

```bash
task clean         # Removes local temporary artifacts, IDE caches, and Git worktrees
task repos:reset   # Hard-resets all checked-out repositories in repos/ back to origin/main
task repos:clean   # Destructively deletes all cloned repositories in repos/ to force fresh downloads
```

### Docker Execution & Inspection

You can easily spin up an interactive bash shell mapped with current codebase contexts into our specific infrastructure containers using the following shortcuts:

```bash
task sh:python-cli  # General python execution environment
task sh:pytest-cli # Testing & CI execution environment
task sh:chromadb   # Inspector for the Vector Database environment
```

## Learnings Documentation

- **Development & Coding Learnings:** See [docs/learnings.md](docs/learnings.md) for technical implementation details, gotchas, and edge cases encountered during tool development, debugging, and code-level work.
- **Workflow & Operational Learnings:** See [docs/workflow_learnings.md](docs/workflow_learnings.md) for process, hygiene, delegation, container orchestration, and bulk import procedures. This file captures operational protocols and workflow best practices, separate from code-level learnings.
