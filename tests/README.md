# Skill Evaluation & Testing Conventions

This repository enforces strict conventions for developing, configuring, and executing Skill Evaluations (Evals) to ensure readability, token efficiency, and proper sandboxing.

## Evaluation Manifests (`evals.yml`)

Each skill's evaluation cases are defined in a corresponding `tests/skills/<skill_name>/evals/evals.yml` file.

### 1. Structure & Formatting

- **Multiline Strings**: Use standard YAML blocks or folded block scalars (`>`) for multiline strings (e.g., `prompt`, `expected_output`) so that text wraps naturally without hardcoded line breaks.
- **Line Length**: Lines must be conditionally wrapped at a maximum of **160 characters** to ensure readability and compliance with [../.yamllint.yml](../.yamllint.yml).

### 2. Prompt Conventions

Prompts must clearly separate simulated user input from internal sandbox instructions. This prevents prompt confusion by decoupling the "human request" from the "backend constraints".

```yaml
user_prompt: >
  The specific user persona question, task, or goal.

agent_prompt: >
  Explicit sandbox overrides, mock AWS configurations, or directory limits.
```

### 3. Setup & Assertions

Each evaluation case executes dynamic Python code using a shared sandboxed scope during runtime.

- **`setup`**: Executed *before* the agent triggers. Used to provision mock infrastructure or scaffold local files.
  - **Available Scope**:
    - `os` / `os.environ`
    - `tests.helpers.aws_env` helpers (e.g., `setup_glue_catalog`, `setup_s3_object`).
- **`expected_output`**: Executed *after* the agent finishes. Used to assert the final response correctly matches expectations.
  - **Available Scope**:
    - `output` (string): The literal agent response.
    - All custom variables initialized during `setup`.

```yaml
evals:
- case: basic_success
  setup: |-
    setup_glue_catalog(
      database_name='datalake_prod',
      table_name='events',
      columns=[{'Name': 'event_id', 'Type': 'string'}]
    )
  expected_output: |-
    assert "event_id" in output
    assert "datalake_prod" in output
```

## Pytest Integration (`test_evals.py` files)

Skill evaluations are dynamically aggregated and executed using Pytest. To register a new skill test suite, you must add a parameterized pytest block to the appropriate testing module based on the skill's location:

- **Global Skills**: Add to [tests/skills/test_evals.py](../tests/skills/test_evals.py).
- **Workflow Domain Skills**: Add to `tests/workflows/<domain_name>/test_<domain_name_underscored>_evals.py` (e.g., [tests/workflows/data-engineering/test_data_engineering_evals.py](../tests/workflows/data-engineering/test_data_engineering_evals.py)).

> **Maintenance Directive:** If all skill evaluations in a domain are migrated or removed, you MUST delete the empty `test_*_evals.py` file and its parent folder to prevent repository clutter and test loader artifacts.

```python
@pytest.mark.parametrize(
    "eval_case", get_eval_cases("glue-catalog-schema"), ids=lambda c: f"glue-catalog-schema-{c['eval_config'].get('case', 'unknown')}"
)
def test_skill_name(eval_case):
    run_skill_eval(eval_case)
```

**Mocking Environments**: If evaluation cases require mocked infrastructure (e.g., AWS), use the appropriate pytest marker to dynamically provision the sandbox. For LocalStack, decorate the test with `@pytest.mark.aws_mock` rather than manually injecting environmental fixtures:

```python
@pytest.mark.aws_mock
@pytest.mark.parametrize(...)
```

*(Reference [tests/conftest.py](tests/conftest.py) for all available environment markers).*

> **Note on Service Limitations (Moto/LocalStack):** Some mocked services have limitations. For example, the `redshift-data` API mock in Moto accepts query executions but lacks a real underlying SQL engine for testing state. It will always successfully process executions but return an empty `Records: []` result set. For such skills, `evals.yml` assertions should be relaxed to validate structural formats (e.g., `assert "Columns:" in output or "empty" in output`) rather than relying on exact data setups.

## Evaluation Runtime (`eval_utils.py`)

The standalone test runtime (`run_skill_eval`) acts sequentially to prevent cross-contamination and context-window strain:

1. `_setup_eval_environment`: Instantiates dynamic mock environments.
2. `_setup_isolated_sandbox`: Replicates the workspace into a restricted `tmp/eval_sandbox_<skill>_<case>` directory. Heavy, irrelevant directories (e.g., [docs/](../docs/), [.claude/skills/](../.claude/skills/), [.pytest_cache/](../.pytest_cache/)) are excluded to preserve LLM context limits. A fresh `git init` automatically bounds the file-reading context.
3. `_run_contextual_prompt`: Dispatches the configured prompt payload via an agent runner.
4. `_validate_agent_output`: Asserts that the output artifacts successfully align with expected state.

### Agent Runners (`runners.py`)

The `AgentRunner` base class supports connecting diverse agent tools. The following runners are available:

- **`ClaudeCodeRunner`**: Invokes Claude Code headlessly via the `claude` CLI. Uses `claude` on PATH (enterprise OAuth) or `ANTHROPIC_API_KEY`.
- **`CopilotRunner`**: Invokes GitHub Copilot via `gh copilot suggest`. Requires `COPILOT_GITHUB_TOKEN` in the environment.
- **`GeminiRunner`**: Invokes `@google/gemini-cli` for Gemini-based eval runs. Requires `GEMINI_API_KEY` in the environment.
- **`CodexRunner`**: Invokes `@openai/codex` for Codex-based eval runs. Requires `OPENAI_API_KEY` in the environment.

ClaudeCodeRunner is the primary runner; Copilot, Gemini, and Codex are secondary runners for cross-family eval coverage. The active runner is resolved at runtime via `get_runner()`, which applies the following priority order: **claude > copilot > gemini > codex**. The runner is selected based on which credentials are present in the environment. To override auto-detection, set the `EVAL_RUNNER` environment variable explicitly (e.g., `EVAL_RUNNER=copilot`).

### Test Environment Setup

Before running skill or script evaluations locally, initialize the local virtual environment:

```bash
task test:setup
```

This creates a `.venv/` in the repository root and installs all test dependencies. The `test:scripts` and `test:skills` tasks use this local `.venv/` directly — **Docker is not required** for these targets.

`task test:brownfield_ai` remains Docker-based and requires LocalStack to be running, as it exercises AWS infrastructure mocking.

> **WARNING**: Evals execute against live agents. They will consume actual tokens and API resources, and test suite lifecycles may take noticeably longer to complete.
