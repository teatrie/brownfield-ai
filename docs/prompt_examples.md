# Prompt Examples

How to interact with the AI agent using natural English. Each example
below shows the conversational text you can type to trigger a specific
capability. You never need to write code directly — just describe what
you need.

## Architecture: Domain-Driven Design (DDD)

Rather than overwhelming the AI context window with hundreds of scripts, this repository isolates specialized tools into Domain subfolders (`workflows/<domain>`). Universal capabilities remain global (`.claude/skills/`). You do not need to type file paths—the agent will autonomously route your prompt!

---

## 🌎 Global Primitives

*Always available regardless of domain.*

### 🛠️ Execution & Orchestration
>
> "**Run a TDD loop** for the login feature."

* **[`tdd-execute`](../.claude/skills/tdd-execute/SKILL.md)**: Orchestrates the Red-Green-Refactor subagent loop for a single feature or bug.

> "**Fix the bug** in the payment processing module."

* **[`bug-fix`](../.claude/skills/bug-fix/SKILL.md)**: Orchestrated bug/issue diagnosis and fix with cost-effective model selection and review gates.

> "**Break this epic down** into subtasks for the new user profile dashboard."

* **[`feature-epic`](../.claude/skills/feature-epic/SKILL.md)**: Acts as a Planner that decomposes a large feature into domains, waves, and an execution strategy, then delegates implementation to the agent-team skill.

> "**Review your protocols**" or "Realign with the system rules."

* **[`protocols`](../.claude/skills/protocols/SKILL.md)**: Forces the agent to explicitly refocus and realign with the repository's core protocols.

> "**Delegate this to an agent team**."

* **[`agent-team`](../.claude/skills/agent-team/SKILL.md)**: Cost-effective multi-agent orchestration with model selection by complexity.

> "**Review my changes before I ship**" or "Run diff-review."

* **[`diff-review`](../.claude/skills/diff-review/SKILL.md)**: Dual-Model code
  quality review of your diff against `main`. Catches security issues, standard
  violations, and architectural drift that tests miss.
  * *"Do a diff review"*
  * *"Review my changes against origin/develop"*
  * *"Diff review scoped to src/ only"*

### 📋 TODO & Project Tracking
>
> "**Capture a TODO** to refactor the auth middleware."

* **[`todo`](../.claude/skills/todo/SKILL.md)**: Capture, list, and triage orphaned TODOs with semantic deduplication and epic-binding workflow.
  * *"Add a todo to fix the flaky test in CI"*
  * *"Show me the todo list"*
  * *"Triage open todos"*

### 📚 Repository Guides
>
> "**What are the conventions** for the analytics repo?"

* **[`repos-guide`](../.claude/skills/repos-guide/SKILL.md)**: Surface curated development guides (conventions, architecture, testing patterns) for the upstream repositories you cloned under `repos/`.
  * *"How do the ingestion pipelines work?"*
  * *"Show me the testing pattern for analytics"*

### 🌐 AWS & Systems
>
> "**Authenticate to AWS** via vault" or "Login to AWS profile `my-profile`."

* **[`aws-vault-auth`](../.claude/skills/aws-vault-auth/SKILL.md)**: Extracts securely cached AWS temporary credentials.

### 🐙 GitHub Operations
>
> "**Search GitHub** for how we query DynamoDB in the `acme/checkout` repo."

* **[`github-search`](../.claude/skills/github-search/SKILL.md)**: Remotely search for code, files, or tables across the organization's repositories without cloning.

> "**Create a PR** for my changes."

* **[`auto-pr`](../.claude/skills/auto-pr/SKILL.md)**: End-to-end PR orchestration.

> "**Ship these changes** as sequential PRs."

* **[`ship`](../.claude/skills/ship/SKILL.md)**: Group a messy, dirty working tree into sequential, logically-cohesive PR stacks.

---

## 🛠️ Repository Maintenance

*Tools for maintaining agent infrastructure and documentation.*

> "**Do a docs review**" or "Run docs-review."

* **[`docs-review`](../workflows/repository-maintenance/skills/docs-review/SKILL.md)**: Audit, update, and clean repository documentation to extract learnings.

> "**Run a claude review**" or "Check the `.claude/` folder logic."

* **[`claude-review`](../workflows/repository-maintenance/skills/claude-review/SKILL.md)**: Reviews the internal agent logic, auth loops, and script behaviors against sandbox protocols.

> "**Create a new skill** to parse log files."

* **[`skill-creator`](../workflows/repository-maintenance/skills/third-party/skill-creator/SKILL.md)**: Fully automated generation of new Agent skills.

> "**Create a new workflow domain** for `frontend-ui`."

* **[`workflow-management`](../workflows/repository-maintenance/skills/workflow-management/SKILL.md)**: Scaffold new DDD routing domains.

> "**Pause this epic**" or "/status pause"

* **[`status-sync`](../workflows/repository-maintenance/skills/status-sync/SKILL.md)**: Pause and resume epics across machines by managing remote branches, the Execution Ledger, and `plan.md` state.

---

## 📊 Data Engineering

> **"Run an Athena query** to get the top 10 rows from the events table."

* **[`athena-query-execute`](../workflows/data-engineering/skills/athena-query-execute/SKILL.md)**: Orchestrates AWS Athena SQL querying and pagination downloading for standard analytics exploration.

*Interacting with the Data Lake, Analytics, and Warehouses.*

> "**Find the Glue table** related to 'user reading stats'."

* **[`glue-find-tables`](../workflows/data-engineering/skills/glue-find-tables/SKILL.md)**: Regex search across the AWS Glue Data Catalog to locate missing Analytics tables.

> "**Get the Glue schema** for table `sandbox_db.user_reads`."

* **[`glue-catalog-schema`](../workflows/data-engineering/skills/glue-catalog-schema/SKILL.md)**: Retrieve columns, partitions, S3 locations, and exact data-types.

> "**Read the service schema** for MySQL database `checkout-main`."

* **[`service-db-schema`](../workflows/data-engineering/skills/service-db-schema/SKILL.md)**: Extract live SQLAlchemy / Go structs representing operational database schemas.

> "**Get the Redshift schema** for physical table `analytics.daily_users`."

* **[`redshift-table-schema`](../workflows/data-engineering/skills/redshift-table-schema/SKILL.md)**: Query the physical Redshift schema.

> "**Analyze this Athena query** for performance bottlenecks."

* **[`athena-query-analysis`](../workflows/data-engineering/skills/athena-query-analysis/SKILL.md)**: Execute EXPLAIN/Analyze passes over Athena queries.

> "**Analyze this Redshift query** for missing distribution keys."

* **[`redshift-query-analysis`](../workflows/data-engineering/skills/redshift-query-analysis/SKILL.md)**: Execute EXPLAIN/Analyze passes over Redshift queries.

> "**Get the DynamoDB schema** for table `UserProfiles`."

* **[`dynamodb-table-schema`](../workflows/data-engineering/skills/dynamodb-table-schema/SKILL.md)**: Extracts the strict KeySchema.

---

## ☁️ AWS Infrastructure

*Terraform and Infrastructure as Code modules.*

> "**Generate a schema-retrieval skill** for a new AWS service resource."

* **[`aws-schema-skill`](../workflows/aws-infrastructure/prompts/aws-schema-skill.prompt.md)**: Scaffold a new skill that retrieves the schema of an AWS service resource, with Moto-based tests enforced.

---

## 🧠 Agent Memory

*Tools for Vector DB interaction.*

> "**Save this chat history**" or "Checkpoint context into ChromaDB."

* **[`knowledge-checkpoint`](../workflows/agent-memory/skills/knowledge-checkpoint/SKILL.md)**: Persist current session conversation into the knowledge base.

> "**Manage ChromaDB collections**."

* **[`knowledge-base`](../workflows/agent-memory/skills/knowledge-base/SKILL.md)**: Manage, query, and structure Vector database collections.

> "**Import documents to ChromaDB**."

* **[`knowledge-import`](../workflows/agent-memory/skills/knowledge-import/SKILL.md)**: Batch import documentation into memory embeddings.

> "**Export ChromaDB database**."

* **[`knowledge-export`](../workflows/agent-memory/skills/knowledge-export/SKILL.md)**: Export knowledge base documents for analysis.

> "**Checkpoint this plan to the ledger**" or "Resume epic ACME-2931" or "Show me the timeline for ACME-2931" or "What's the next plan to work on?"

* **[`execution-ledger`](../workflows/agent-memory/skills/execution-ledger/SKILL.md)**: Save, query, resume, and audit execution artifacts (plans, design decisions, gate verdicts, test results) across sessions. Supports ACID-safe plan claiming for bot-driven execution.

---

## 🧰 Document Utilities

*Miscellaneous parsers and translators.*

> "**Extract the text** from `docs/manual.pdf`."

* **[`extract-pdf`](../workflows/document-utilities/skills/extract-pdf/SKILL.md)**: Rip readable plaintext from non-markdown binaries.

> "**Render this Mermaid diagram** to SVG."

* **[`mermaid-to-svg`](../workflows/document-utilities/skills/mermaid-to-svg/SKILL.md)**: Convert raw markdown diagram blocks to physical image assets.
