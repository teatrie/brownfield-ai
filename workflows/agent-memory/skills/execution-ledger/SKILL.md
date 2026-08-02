---
name: execution-ledger
description: >-
  Checkpoint and query execution artifacts (plans, design decisions,
  gate verdicts, test results) for epic resumability and audit trails.
  Triggered by "checkpoint plan", "ledger save", "resume epic", "audit
  trail".
---

# Execution Ledger

Checkpoint and query execution artifacts (plans, design decisions, gate
verdicts, test results) for epic resumability and audit trails. Backed by
dual-store architecture: ChromaDB for rich document content and semantic
search, SQLite for ACID-safe plan lifecycle management.

## Usage

All commands use `task ledger:*` aliases which route through `python-cli`
for correct environment and networking.

### 0. Start ChromaDB

Before running any command, ensure ChromaDB service is running.

```bash
task chromadb:start
```

### 1. Save

Save an execution artifact (plan, design decision, gate verdict, test
result, wave summary, requirement map) to the ledger.

Content is supplied keyword-only via exactly one of `--content` (short
inline bodies) or `--content-file` (large markdown bodies). There is no
positional content argument.

```bash
# Save a large markdown artifact (Write tool -> tmp/foo.md -> ledger)
# 1. Write the body to tmp/ with the Write tool (avoids shell-quoting +
#    the heredoc sandbox restriction in CLAUDE.md §10)
# 2. Reference it via --content-file:
task ledger:save -- \
  --content-file tmp/plan-snapshot.md \
  --fields '{"epic_id": "ACME-2932", "artifact_type":
  "plan_snapshot", "agent_model": "claude-opus-4"}' \
  --metadata '{"domain": "planning"}'

# Save a plan snapshot with full metadata
# Large body — written to tmp/plan-snapshot.md via the Write tool, then
# referenced here (e.g. "Epic plan: implement Dual-Model Review Gate...").
task ledger:save -- \
  --content-file tmp/plan-snapshot.md \
  --fields '{"epic_id": "ACME-2932", "artifact_type":
  "plan_snapshot", "agent_model": "claude-opus-4"}' \
  --metadata '{"wave": "", "domain": "planning", "step": "0",
  "agent_role": "planner", "verdict": "", "version": 1,
  "parent_id": "", "epic_status": "pending", "title": "Execution
  Ledger", "priority": 3, "depends_on": "[\"ACME-2930\"]"}'

# Save a design decision
# Multi-line rationale — written to tmp/design-decision.md via the Write
# tool (e.g. "Rationale: pipe delimiter chosen for IDs to avoid collision
# with ISO-8601 colons...").
task ledger:save -- \
  --content-file tmp/design-decision.md \
  --fields '{"epic_id": "ACME-2932", "artifact_type":
  "design_decision", "agent_model": "claude-opus-4"}' \
  --metadata '{"domain": "architecture"}'

# Save a gate verdict (from reviewer)
# Short body — inline via --content.
task ledger:save -- \
  --content "Plan review: all requirements met, no blocking issues. Dependency resolution validated." \
  --fields '{"epic_id": "ACME-2932", "artifact_type":
  "gate_verdict", "agent_model": "claude-sonnet-4"}' \
  --metadata '{"wave": "1", "verdict": "GREEN", "agent_role":
  "dual-model-reviewer"}'

# Save a step result (test output)
# Captured output — written to tmp/step-result.md via the Write tool
# (e.g. the "$ task lint:staged ... Passed 2/2 checks" log).
task ledger:save -- \
  --content-file tmp/step-result.md \
  --fields '{"epic_id": "ACME-2932", "artifact_type":
  "step_result", "agent_model": "claude-opus-4"}' \
  --metadata '{"domain": "Domain B", "step": "lint",
  "verdict": "pass"}'

# Save a wave summary
# Large body — written to tmp/wave-summary.md via the Write tool (e.g.
# "Wave 1 completed: Domain A and Domain C both passed post-wave gate...").
task ledger:save -- \
  --content-file tmp/wave-summary.md \
  --fields '{"epic_id": "ACME-2932", "artifact_type":
  "wave_summary", "agent_model": "claude-opus-4"}' \
  --metadata '{"wave": "1"}'
```

### 2. Query

Search ledger artifacts by semantic query with optional filters on epic
ID and artifact type.

```bash
# Semantic search across all artifacts
task ledger:query -- \
  "plan lifecycle status machine design" \
  --filters '{"n": 5}'

# Search within a specific epic
task ledger:query -- \
  "gate verdict blocking issues" \
  --filters '{"epic_id": "ACME-2932", "n": 10}'

# Search specific artifact type across all epics
task ledger:query -- \
  "test failure output" \
  --filters '{"artifact_type": "step_result", "n": 3}'

# Combined filter: epic + artifact type
task ledger:query -- \
  "dependencies ACID transaction" \
  --filters '{"epic_id": "ACME-2932", "artifact_type":
  "design_decision", "n": 5}'
```

### 3. Timeline

List all artifacts for an epic in chronological order (sorted by
document ID).

```bash
# All artifacts for an epic
task ledger:timeline -- ACME-2932

# Filter timeline by artifact type
task ledger:timeline -- ACME-2932 \
  --artifact_type plan_snapshot

# Custom limit (default 50)
task ledger:timeline -- ACME-2932 --limit 100
```

### 4. Get

Retrieve a single artifact by exact document ID.

```bash
task ledger:get -- \
  "ACME-2932|2026-03-20T14:30:45.123456|plan_snapshot|claude-opus-4||0"
```

### 5. Resume

Fetch full execution context for an epic (plan + decisions + results +
summaries + verdicts) to bootstrap session state.

```bash
task ledger:resume -- ACME-2932

# Output includes:
# {
#   "plan_snapshot": {...},
#   "design_decisions": [...],
#   "step_results": [...],
#   "wave_summaries": [...],
#   "gate_verdicts": [...],
#   "requirement_map": {...},
#   "pr_created": [...],
#   "pr_merged": [...],
#   "session_exit": [...]
# }
```

### 6. Next

Claim the next eligible plan for execution with ACID-safe transaction.
Auto-releases stale claims (default 24 hours). Validates dependencies
before claiming.

```bash
# Claim next plan for a bot or agent
task ledger:next -- \
  --claimed_by "bot-wave1-orchestrator"

# Custom stale timeout (hours)
task ledger:next -- \
  --claimed_by "bot-wave1-orchestrator" --stale_hours 12

# Output: JSON epic row or "No plans available."
```

Note: `claimed_by` must be a bot/agent identifier (e.g.
`bot-orchestrator`, `claude-opus-4`, `human-reviewer`), never PII.

### 7. Release

Release a claimed plan back to available pool. Used when a bot fails or
operator wants to reassign.

```bash
task ledger:release -- ACME-2932
```

### 8. Status

Update an epic's lifecycle status with transition validation. Allowed
transitions: `pending → approved → in_progress → completed|abandoned`.
Also: `in_progress → approved` (reset stale) or `in_progress → pending`
(full reset). Also: `in_progress → blocked`, `blocked → approved|abandoned`,
`in_review → blocked`.

```bash
# Approve a plan (pending → approved)
task ledger:status -- ACME-2932 \
  --new_status approved

# Mark complete
task ledger:status -- ACME-2932 \
  --new_status completed

# Reset stale plan
task ledger:status -- ACME-2932 \
  --new_status approved
```

### 9. Index

List all epics from the SQLite registry with optional status filter.

```bash
# All epics sorted by priority
task ledger:index --

# Filter by status
task ledger:index -- --status_filter approved

# Verbose output (all fields)
task ledger:index -- --verbose
```

### 10. Create

Create a new epic in the ledger with `backlog` initial status.
Auto-initializes SQLite index entry. Useful for bottom-up epic
creation from TODOs or user input (as opposed to plan-driven
creation via `save`).

```bash
# Create a new epic with defaults
task ledger:create -- --epic-id ACME-1234 \
  --title "My Epic" --epic-status backlog

# With custom priority and dependencies
task ledger:create -- --epic-id ACME-1234 \
  --title "My Epic" --epic-status backlog \
  --priority 2 --depends-on '["ACME-1233"]'
```

Returns `true` (inserted) or `false` (epic already exists).

### 11. Check-Reviews

Check PR status for all `in_review` epics and process transitions.
Orchestrated via `task ledger:check-reviews` which calls `gh pr view`
on the host, then pipes results to `process-reviews-cli` for state
transitions.

```bash
task ledger:check-reviews
```

### 12. Set-PRs

Set current PR refs for an epic.

```bash
task ledger:set-prs -- <epic_id> --pr-refs "<refs>"
```

Example:

```bash
task ledger:set-prs -- ACME-2931 --pr-refs "acme/analytics#245, acme/web#100"
```

### Clear PR References

To clear all PR references for an epic (set `current_prs` to NULL):

```bash
task ledger:set-prs -- <epic_id> --pr-refs ""
```

### 13. Touch

Update an epic's last_updated_at timestamp without changing status or
creating artifacts. Used as a heartbeat for claim refresh during
long-running multi-sub-plan execution.

```bash
task ledger:touch -- ACME-2932
```

## Metadata Schema

### ChromaDB Fields (16)

All artifacts stored in the `execution_ledger` collection carry these
queryable metadata fields:

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `epic_id` | string | `ACME-2932` | Epic identifier (JIRA key or custom ID) |
| `artifact_type` | string | `plan_snapshot` | See Artifact Types section below |
| `wave` | string | `1` | Wave number (empty string for non-wave artifacts) |
| `domain` | string | `Domain B` | Domain/component area |
| `step` | string | `lint` | Step name or task identifier |
| `agent_role` | string | `dual-model-reviewer` | Agent role: planner, executor, reviewer, etc. |
| `agent_model` | string | `claude-opus-4` | Agent model name |
| `verdict` | string | `GREEN` | Gate verdict: PASS, FAIL, GREEN, RED, BLOCKED, etc. |
| `timestamp` | string | `2026-03-20T14:30:45.123456` | ISO-8601 creation timestamp |
| `version` | int (as string) | `1` | Artifact version (plan_snapshot mainly) |
| `parent_id` | string | `ACME-2931` | ID of parent/prerequisite artifact |
| `epic_status` | string | `pending` | Epic lifecycle: pending, approved, in_progress, completed, abandoned |
| `artifact_status` | string | `active` | Artifact state: active, superseded |
| `sub_plan` | string | `A` | Sub-plan label (empty string for non-sub-plan artifacts) |
| `attempt` | string | `2` | Retry attempt number (empty string when not applicable) |
| `branches` | string | `brownfield-ai:feat/X\|repo:feat/Y` | Pipe-delimited repo-to-branch mapping (plan_snapshot only) |

### SQLite Index Columns (10)

The `epics` table (at `~/.brownfield-ai/ledger_index.db`) tracks plan
lifecycle with ACID guarantees:

| Column | Type | Default | Notes |
|--------|------|---------|-------|
| `epic_id` | TEXT | — | Primary key |
| `status` | TEXT | `pending` | Lifecycle state: backlog, pending, approved, in_progress, completed, abandoned, in_review |
| `priority` | INTEGER | `5` | 0–9 where 0=highest, 5=default, 9=lowest |
| `depends_on` | TEXT | `[]` | JSON array of upstream epic IDs, e.g. `["ACME-2930","ACME-2931"]` |
| `claimed_by` | TEXT | `` | Agent/bot identifier that claimed the plan (empty if unclaimed) |
| `claimed_at` | TEXT | `` | ISO-8601 timestamp of claim (empty if unclaimed) |
| `title` | TEXT | `` | Epic title or short description |
| `created_at` | TEXT | — | ISO-8601 creation timestamp |
| `last_updated_at` | TEXT | — | ISO-8601 timestamp of most recent update (claim, release, status change, checkpoint) |
| `current_prs` | TEXT | `NULL` | Comma-separated PR refs in `{owner}/{repo}#{number}` format. Set when an epic enters `in_review`; cleared on all transitions out of `in_review`. Blocks completion when non-null. |

## Document ID Format

Document IDs are composite strings enabling lexicographic chronological
sort without a database-level `order_by` clause:

```text
{epic_id}|{timestamp}|{artifact_type}|{agent_model}|{wave}|{step}
```

Example:

```text
ACME-2932|2026-03-20T14:30:45.123456|plan_snapshot|claude-opus-4||0
```

All field values are sanitized by replacing `|` with `-` before
composition, preventing delimiter injection.

**Lexicographic sort**: The composite ID ensures that when artifacts are
sorted alphabetically, they naturally order by epic, then by timestamp,
then by type. This enables clients to iterate artifacts chronologically
without repeated database queries.

**Agent model in ID**: The 4th segment (`agent_model`) prevents silent
overwrites when parallel Dual-Model reviewers checkpoint `gate_verdict`
artifacts in the same second (same epic, type, timestamp).

## Plan Lifecycle

### State Machine

An epic progresses through lifecycle states, tracked in SQLite with
ACID-safe transitions:

```text
backlog ──→ pending ──→ approved ──→ in_progress ──→ in_review ──→ completed
   │                                    ↓    ↓          ↓
   └──────────────── approved ──────────┘  blocked    backlog
   (fast-path)                             ↓    ↓       ↓
                                       approved  abandoned
                                       abandoned

(also: in_progress → blocked, blocked → approved|abandoned, in_review → blocked,
in_progress ↔ approved for reset, in_progress → pending for full reset)
```

### Status Descriptions

| Status | Meaning | When | Next |
|--------|---------|------|------|
| `backlog` | Bottom-up epic, awaiting triage | Created via `create` command or TODO promotion | `pending`, `approved` (fast-path) |
| `pending` | Just created, awaiting review | Default on save | `approved` or discard |
| `approved` | Dual-Model reviewed, ready to execute | After gate passes | `in_progress` |
| `in_progress` | Claimed by agent, actively executing | After `next-plan` claim | `completed`, `abandoned`, or reset to `approved` |
| `in_review` | Epic has active PRs under human review | Entered after PR creation (via `auto-pr` or `ship`) | `completed` (all PRs merged), `backlog` (changes requested), or `abandoned` (PRs closed) |
| `blocked` | Automated execution cannot proceed; human triage required | Ralph transitions when Exit Review Gate verdict is "blocked" or retries exhausted | `approved` (human re-approves), `abandoned` |
| `completed` | Execution finished successfully | Manual status update | Terminal (no transitions) |
| `abandoned` | Execution aborted or skipped | Manual status update | Terminal (no transitions) |

### Claiming and Stale Release

The `next-plan` command returns the highest-priority (`priority ASC`)
plan in `approved` status whose dependencies are all `completed`. Before
the eligibility scan, any plan with `status = 'in_progress'` and
`last_updated_at` older than 24 hours (configurable via
`--stale_hours`) is auto-released back to `approved`. This prevents
deadlocks from crashed bots or abandoned work.

`claimed_by` field: populated with a bot/agent identifier (never PII)
when `next-plan` claims a plan. Cleared when plan is released or
transitions to `completed`/`abandoned`.

### Dependency Resolution

The `depends_on` field stores a JSON array of upstream epic IDs (e.g.,
`["ACME-2930","ACME-2931"]`). The `next-plan` command validates that all
listed epics have `status = 'completed'` before allowing a plan to be
claimed. This ensures epics execute in correct order.

### Versioning and Supersession

ChromaDB has no built-in versioning — it is a flat document store where
`upsert` overwrites and there is no changelog or rollback. The ledger
implements versioning through two mechanisms:

**1. Composite IDs make every save unique.** Because the document ID
includes a timestamp (`{epic_id}|{timestamp}|...`), every `save` call
creates a new document. An updated plan does not overwrite the previous
one — it creates a new document alongside it. Nothing is ever deleted.

**2. `artifact_status` marks old versions as superseded.** When a new
artifact is saved for the same `(epic_id, artifact_type)` pair, the
`save` command calls `supersede_previous()` which queries all existing
documents matching that pair with `artifact_status = 'active'` and
flips them to `superseded`. The new document gets `active`.

Example version history for a plan that evolved over three revisions:

```text
ACME-2931|..T10:00:00|plan_snapshot|opus||  → superseded, version: 1
ACME-2931|..T14:30:00|plan_snapshot|opus||  → superseded, version: 2
ACME-2931|..T09:00:00|plan_snapshot|opus||  → active,     version: 3
```

How commands interact with versions:

- `resume` filters on `artifact_status: active` — returns only the
  current version (v3 above)
- `timeline` returns all versions — full history visible for audit
- `timeline --artifact-type plan_snapshot` shows the plan's evolution
- `get <doc-id>` retrieves any specific version by its exact ID

The `version` metadata field (integer, default 1) is an informational
counter for human readability. The actual versioning is driven by
timestamps and `artifact_status` — not the `version` number.

**Scope of supersession:** `supersede_previous()` only triggers within
the same `(epic_id, artifact_type)` pair. A `design_decision` does not
supersede a `plan_snapshot`. Design decisions, gate verdicts, step
results, and wave summaries accumulate — only plans and requirement
maps get superseded on update.

### Staleness and Updates

Every checkpoint (`save`), status transition, claim, or release updates
the `last_updated_at` column in SQLite. The `next-plan` command checks
this timestamp to detect stale claims (older than `stale_hours`). Agents
should checkpoint artifacts periodically (e.g., after each gate) to
prevent their claims from being auto-released.

## Architecture

### Dual-Store Design

**ChromaDB** (distributed, document-rich):

- Stores full artifact bodies (plans, decisions, verdicts, test output)
- Provides semantic search across artifact content
- Lazy-loaded via HTTP from Docker container
- Optimized for content retrieval and natural-language queries

**SQLite** (`~/.brownfield-ai/ledger_index.db`, lightweight, transactional):

- Stores only lightweight plan index and lifecycle metadata
- Enables ACID-safe claiming (no race conditions between bots)
- Local file accessed via container volume mount
- Optimized for plan scheduling and dependency resolution

**Dual-write on `save`** (for `plan_snapshot` only):

1. Write to SQLite first (transactional) — epic's index entry
2. Write to ChromaDB second (idempotent upsert) — full document

This ordering minimizes orphan states: if ChromaDB fails after SQLite
succeeds, the epic appears in `index`/`next` but `resume` finds no
content (detectable and recoverable by retrying `save`).

### Service-Layer Design

All business logic lives in pure functions (`save_artifact()`,
`claim_next()`, `release_epic()`, `update_status()`, etc.) that accept
`sqlite3.Connection` and `chromadb.Collection` as parameters. The
`defopt` CLI sub-commands are thin wrappers. This architecture enables
future FastAPI service to import and reuse the same functions — routes
just bind HTTP protocols over the service layer. No need to rewrite core
logic.

### Content Sanitization

The `save` command automatically sanitizes `step_result` artifacts to
prevent credential leaks:

1. **Redaction**: Strip AWS credentials (`AKIA...`, `AWS_*=`), PII
   (emails, IPs, password/token/secret key-value pairs). Replace matches
   with `[REDACTED]`.
2. **Truncation**: If content exceeds 5000 chars, keep first 2500 +
   marker + last 2500 (preserves diagnostic boundaries while discarding
   verbose middle). Insert `\n... [TRUNCATED {N} chars] ...\n` marker.

Other artifact types are stored as-is (no sanitization).

### Schema Validation & Artifact Types

- `artifact_type` must be one of: `plan_snapshot`, `design_decision`,
  `gate_verdict`, `step_result`, `wave_summary`, `requirement_map`,
  `pr_created`, `pr_merged`, `todo_linked`, `ci_resolution`,
  `pr_changes_required`, `session_exit`. Invalid types rejected with non-zero
  exit.

**Artifact type descriptions**:

- `plan_snapshot`: Epic plan with full metadata (versioned).
- `design_decision`: Architectural rationale and decision records.
- `gate_verdict`: Post-review gate outcome (PASS/FAIL/GREEN/RED).
- `step_result`: Test, lint, or task execution output.
- `wave_summary`: Wave completion summary with duration and blockers.
- `requirement_map`: Requirements traceability matrix (versioned).
- `pr_created`: Pull request creation event.
- `pr_merged`: Pull request merge event.
- `todo_linked`: Checkpointed when a TODO is associated with an epic,
  creating an audit trail in the epic's timeline.
- `ci_resolution`: CI failure triage and resolution record.
- `pr_changes_required`: Changes-requested review event on a PR.
- `session_exit`: Session exit assessment from headless orchestrator (verdict, failure analysis, recommended escalation floor).
- `epic_status` must be one of: `backlog`, `pending`, `approved`,
  `in_progress`, `in_review`, `completed`, `abandoned`, `blocked`. Invalid
  statuses rejected with non-zero exit.
- Status transitions validated against allowed state machine (see
  "Status Descriptions" above).

### Error Handling

All commands exit with code 0 on success, non-zero on error. Errors are
printed to stdout for capture in logs. Critical failures (ChromaDB
unavailable, SQLite corrupted) cause immediate `sys.exit(1)`.

## Notes

- To ensure data persistence across sessions, ensure ChromaDB service
  continues running and `~/.brownfield-ai/chroma_data/` volume is mounted.
- SQLite database at `~/.brownfield-ai/ledger_index.db` persists locally
  unless the `python-cli` container is destroyed with `docker volume rm`.
- All timestamps are ISO-8601 format; clients must parse accordingly.
- Metadata values must be scalar (string or int); JSON complex objects
  not supported in ChromaDB metadata.
- `claimed_by` must never contain PII; use agent identifiers like
  `bot-orchestrator`, `claude-opus-4`, `human-reviewer`, etc.
