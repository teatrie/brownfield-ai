---
name: workflow-management
description: Orchestrates the creation of new workspace workflow domains and the integration of new skills into those workflows. Use when you need to define a new architectural domain, manage an existing domain's structure, or correctly initialize scaffolding when integrating skills using the skill-creator.
---

# Workflow Management

This skill dictates the organizational protocol for maintaining the Domain-Driven Design (DDD) layout within the `/workflows/` directory. It coordinates setting up domains and acts as a gateway before utilizing the `skill-creator`.

## 1. Creating a Workflow Domain

When a user requests a new workflow domain (e.g., `data-analytics` or `frontend-app`):

1. **Create the Domain Folder:** `workflows/<domain-name>/`
2. **Generate the Router File:** Create `workflows/<domain-name>/CONTEXT.md`
   - **Crucial:** You must write a detailed, multi-paragraph description of the domain's purpose, its responsibilities, and its technical scope. A one-liner is not sufficient!
   - Include a section placeholder for `## Available Skills`.
3. **Register in Master Router:** Update the main list in `workflows/INDEX.md` to add `- [Domain Title](<domain-name>/CONTEXT.md)`.
4. **Scaffold the Test Harness:** Create `tests/workflows/<domain-name>/__init__.py`.
5. **Add the Skills Directory:** Create `workflows/<domain-name>/skills/` storing skills locally.

## 2. Adding a New Skill to a Workflow

The system must ensure that new skills strictly reside within an appropriately scoped domain branch.

1. **Select or Create the Domain:** Validate that the target domain exists in `workflows/INDEX.md`. If not, perform "Creating a Workflow Domain" first.
2. **Adhere to `skill-creator` and `tdd-execute` Rules:**
   - You MUST utilize or adhere to the exact processes set out by the [skill-creator](../third-party/skill-creator/SKILL.md) skill (writing the draft, running evaluation prompts, creating a `SKILL.md` in `workflows/<domain-name>/skills/<new-skill>/SKILL.md`, and its localized `scripts/` folder).
   - Any Python scripts, logic implementations, AND skill evaluation tests added MUST be developed using standard [tdd-execute](../../../../.claude/skills/tdd-execute/SKILL.md) loop protocols (Red-Green-Refactor). This ensures that both the logic in `scripts/` and the evaluation harnesses in `tests/workflows/` remain robustly verified before merging.
3. **Update Domain Documentation:**
   - Automatically inject a local reference link to the new skill into the `## Available Skills` index inside `workflows/<domain-name>/CONTEXT.md`.
4. **Wire Pytest Environments:**
   - Add the new parameterized pytest block to the aggregated domain testing module at `tests/workflows/<domain-name>/test_<domain-name-underscored>_evals.py` (e.g., `tests/workflows/data-engineering/test_data_engineering_evals.py`).
   - If this file does not exist because this is the first evaluation suite for the domain, you must create it.
   - **Crucial:** You MUST strictly adhere to the evaluation formats defined in [tests/README.md](../../../../tests/README.md) and execute evaluation designs according to the [skill-creator](../third-party/skill-creator/SKILL.md) directives.

## Operational Checks

- **Never** create global skills in `.claude/skills/`. All new agent tools must be domain-driven.
- **Never** put scripts into the old `/scripts/`. They must live local to the skill: `workflows/<domain-name>/skills/<new-skill>/scripts/`.
