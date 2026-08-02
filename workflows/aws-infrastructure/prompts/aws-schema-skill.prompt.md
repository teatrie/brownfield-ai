---
name: aws-schema-skill
description: "Generates a new skill to retrieve the schema of a specific AWS service resource. Enforces Moto testing."
---

# Generate AWS Schema Skill

**Use Case**: You need to create a new skill to query and retrieve the schema/structure of a specific AWS resource (e.g., DynamoDB tables, RDS schemas, DocumentDB collections).

> **🤖 Agent Instructions:**
> If the user has not provided the arguments below, HALT and ask for them before proceeding.
>
> **Arguments:**
>
> - `<aws-service>`: The AWS service name (e.g., "DynamoDB", "RDS").
> - `<aws-resource>`: The specific resource type (e.g., "table", "cluster").

I want to add a new skill using `/skill-creator` to query and retrieve the schema of an AWS `<aws-service>` `<aws-resource>`.

This skill MUST adhere to the core protocols and standards (`.claude/skills/protocols/SKILL.md`).
This skill MUST follow the structural patterns of the `glue-catalog-schema` and `redshift-table-schema` skills in its operation and CRITICAL directives.

**Planning & Orchestration Directives:**

1. **Plan Structure:** Your generated plan MUST be explicitly separated into TDD phases (e.g., "Phase 1: TDD Setup & Tests (Red)", "Phase 2: Implementation (Green)", "Phase 3: Refactor & Skill Definition").
2. **Explicit Delegation:** In the plan, explicitly annotate which steps will be delegated to subagents versus done by the orchestrator. Do NOT implement the code directly as a monolithic agent; act as the Orchestrator/Planner.
3. **Skill-Level Delegation:** The target `SKILL.md` you design MUST explicitly instruct future agents to delegate to a subagent via the platform's native mechanism (with `docker compose`) for executing commands, rather than running terminal commands directly.

**Testing Constraints:**

- Add the skills test according to [tests/skills/test_evals.py](../../../tests/skills/test_evals.py) and [tests/README.md](../../../tests/README.md).
- DO NOT use Python mocking frameworks (like `unittest.mock`).
- ONLY use the `moto` server (localhost) as defined in [docker-compose.yml](../../../docker-compose.yml) for tests.
- Provide a `setup_<aws-service>_<aws-resource>` helper in [tests/helpers/aws_env.py](../../../tests/helpers/aws_env.py) to seed the fake Moto environment.
- Create an evaluation manifest at `tests/skills/<service>-<resource>-schema/evals/evals.yml`.
- Execute tests to verify correctness.
