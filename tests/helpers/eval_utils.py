import json
import os
import re
import shutil
import subprocess
from functools import partial

import pytest
import yaml

from helpers import aws_env
from helpers.runners import get_runner

# Names never worth carrying into a sandbox from a skill's eval workspace.
_WORKSPACE_ARTIFACT_NAMES: frozenset[str] = frozenset({"tmp", "__pycache__", ".pytest_cache"})

# ============================================================================
# Eval Data Extraction
# ============================================================================


def get_eval_cases(target_skill_name: str | None = None) -> list:
    """
    Dynamically discover all evals.yml files under tests/skills/*/evals/
    and tests/workflows/*/skills/*/evals/
    and parameterize the tests based on their contents.
    Optionally filter by a specific skill name.

    Args:
        target_skill_name (str | None, optional): Explicit skill configuration to load. Defaults to None.

    Returns:
        list: A list of evaluation configuration dictionaries.
    """
    eval_cases = []

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Paths to search for skills
    search_paths = [os.path.join(base_dir, "skills")]
    workflows_dir = os.path.join(base_dir, "workflows")
    if os.path.isdir(workflows_dir):
        for domain in os.listdir(workflows_dir):
            domain_skills_dir = os.path.join(workflows_dir, domain, "skills")
            if os.path.isdir(domain_skills_dir):
                search_paths.append(domain_skills_dir)

    for skills_dir in search_paths:
        if os.path.isdir(skills_dir):
            for skill_dir in os.listdir(skills_dir):
                if target_skill_name and skill_dir != target_skill_name:
                    continue

                eval_path = os.path.join(skills_dir, skill_dir, "evals", "evals.yml")
                if os.path.isfile(eval_path):
                    with open(eval_path) as f:
                        try:
                            eval_data = yaml.safe_load(f)
                            skill_name = eval_data.get("skill_name", skill_dir)
                            for eval_item in eval_data.get("evals", []):
                                eval_cases.append({
                                    "skill_name": skill_name,
                                    "workspace_path": os.path.join(skills_dir, skill_dir),
                                    "eval_config": eval_item,
                                })
                        except yaml.YAMLError:
                            print(f"Warning: Failed to parse {eval_path}")
    return eval_cases


# ============================================================================
# Base Test Execution Sandbox
# ============================================================================


def run_skill_eval(eval_case: dict, **eval_env) -> None:
    """
    Test case invoking the LLM subagent for a given eval configuration.
    Sets up an isolated functional sandbox boundary simulating the project root.

    Args:
        eval_case (dict): Dictionary comprising 'skill_name', 'eval_config' and 'workspace_path'.
    """
    _skip_if_required_env_missing(eval_case["eval_config"])

    skill_name = eval_case["skill_name"]
    eval_case_name = eval_case["eval_config"].get("case")
    user_prompt = eval_case["eval_config"].get("user_prompt", eval_case["eval_config"].get("prompt", ""))
    agent_prompt = eval_case["eval_config"].get("agent_prompt", "")
    expected_output = eval_case["eval_config"].get("expected_output")
    original_workspace_path = eval_case["workspace_path"]

    print(f"\nEvaluating Skill: {skill_name} | Case Name: {eval_case_name}")
    print(f"Goal: {expected_output}")

    # 1. Provide an isolated workspace scope
    sandbox_path = _setup_isolated_sandbox(skill_name, eval_case_name, original_workspace_path)

    # 2. Setup environment dynamically
    os.chdir(sandbox_path)
    try:
        # Determine skill path relative to root based on its original evals workspace
        # e.g., tests/workflows/domain/skills/skill_name -> workflows/domain/skills/skill_name/SKILL.md
        # or tests/skills/skill_name -> .claude/skills/skill_name/SKILL.md
        skill_rel_dir = original_workspace_path.split("tests/", 1)[-1]

        # tests/skills/ maps to .claude/skills/
        if skill_rel_dir.startswith("skills/"):
            skill_path = os.path.join(".claude", skill_rel_dir, "SKILL.md")
        else:
            skill_path = os.path.join(skill_rel_dir, "SKILL.md")

        _setup_eval_environment(eval_case["eval_config"], eval_env)

        # 3. Invoke Subagent programmatically in the sandbox
        output = _run_contextual_prompt(skill_name, user_prompt, agent_prompt, sandbox_path, eval_env, skill_path=skill_path)

        # 4. Validate output response
        _validate_agent_output(output, expected_output)
    finally:
        os.chdir(original_workspace_path)


def _skip_if_required_env_missing(eval_config: dict) -> None:
    """
    Skip an eval case when an environment variable it declares is unset.

    Cases may interpolate deployment-specific values into their prompts
    (``{BROWNFIELD_ORG}``) and into their assertions
    (``os.environ["BROWNFIELD_ORG"]``). Without this guard an unset variable
    surfaces as a ``KeyError`` raised by ``str.format`` deep inside the runner,
    which reads like a harness bug rather than "this eval needs configuration".

    Empty values count as missing deliberately. An empty org would make an
    assertion such as ``assert os.environ["BROWNFIELD_ORG"] in output`` succeed
    against literally any output, converting a misconfiguration into a false
    pass — strictly worse than the crash this replaces.

    Args:
        eval_config: A single eval case's configuration mapping.
    """
    required = eval_config.get("requires_env") or []
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        pytest.skip(f"eval case requires unset environment variable(s): {', '.join(missing)}")


def _setup_eval_environment(eval_config: dict, eval_env: dict) -> None:
    """Evaluate pre-execution setup hooks natively in test context."""
    setup = eval_config.get("setup")
    if not setup:
        return

    env = {
        **globals(),
        **eval_env,
        "os": os,
        "json": json,
        "setup_dynamodb_table": aws_env.setup_dynamodb_table,
        "setup_glue_catalog": aws_env.setup_glue_catalog,
        "setup_rds_cluster": aws_env.setup_rds_cluster,
        "setup_s3_object": aws_env.setup_s3_object,
    }
    print(f"Executing setup:\n{setup}")
    exec(setup, env, env)


def _workspace_copy_ignore(workspace_path: str, dir_path: str, contents: list) -> list:
    """Select names to skip when copying a skill's eval workspace into the sandbox.

    ``evals`` is dropped at the workspace root only. It holds the case
    definitions, ``expected_output`` among them, so copying it would place the
    answer key inside the very sandbox the agent is evaluated in. Nested
    directories of that name are unrelated and are copied as normal.

    Args:
        workspace_path: The skill's eval workspace being copied from.
        dir_path: The directory ``shutil.copytree`` is currently visiting.
        contents: Entry names in ``dir_path``.

    Returns:
        list: The subset of ``contents`` to skip.
    """
    ignored = [c for c in contents if c in _WORKSPACE_ARTIFACT_NAMES]
    if os.path.abspath(dir_path) == os.path.abspath(workspace_path) and "evals" in contents:
        ignored.append("evals")
    return ignored


def _setup_isolated_sandbox(skill_name: str, eval_case_name: str, original_workspace_path: str) -> str:
    """Set up an isolated functional sandbox boundary simulating the project root."""
    # Determine the workspace root first (needed for sandbox path)
    # e.g. /path/to/project/tests/skills/my_skill -> /path/to/project
    workspace_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
        cwd=original_workspace_path,
    ).stdout.strip()

    sandbox_path = os.path.join(workspace_root, "tmp", f"eval_sandbox_{skill_name}_{eval_case_name}")
    if os.path.exists(sandbox_path):
        shutil.rmtree(sandbox_path)

    # Ignore .claude/skills and chroma_data when copying
    def ignore_unwanted(dir_path: str, contents: list) -> list:
        ignores = []
        if dir_path == workspace_root:
            ignores.extend([
                "chroma_data",
                ".git",
                ".github",
                ".claude",
                "CLAUDE.md",
                "plan.md",
                ".venv",
                "__pycache__",
                "repos",
                "worktrees",
                "tests",
                "docs",
                "prompts",
                "tmp",
                ".pytest_cache",
                ".envrc",
            ])
        return ignores

    shutil.copytree(workspace_root, sandbox_path, ignore=ignore_unwanted, dirs_exist_ok=True)

    # Explicitly copy ONLY the skill being evaluated
    skill_dest = os.path.join(sandbox_path, ".claude", "skills", skill_name)
    os.makedirs(skill_dest, exist_ok=True)
    skill_src = os.path.join(workspace_root, ".claude", "skills", skill_name, "SKILL.md")
    if os.path.exists(skill_src):
        shutil.copy2(skill_src, os.path.join(skill_dest, "SKILL.md"))

    skill_src_scripts = os.path.join(workspace_root, ".claude", "skills", skill_name, "scripts")
    if os.path.exists(skill_src_scripts):
        shutil.copytree(skill_src_scripts, os.path.join(skill_dest, "scripts"), dirs_exist_ok=True)

    # Copy workspace specific files over
    if os.path.exists(original_workspace_path):
        shutil.copytree(
            original_workspace_path,
            sandbox_path,
            ignore=partial(_workspace_copy_ignore, original_workspace_path),
            dirs_exist_ok=True,
        )

    # Note: git init was removed — it created .git/ files that the
    # Claude Code sandbox cannot delete, making sandbox cleanup fail
    # on subsequent runs. Claude Code does not need git context
    # bounding (unlike Copilot which auto-scans git context).

    return sandbox_path


def _find_skill_file(skill_name: str) -> str:
    """Find the SKILL.md file path relative to the workspace root."""
    claude_skill_path = os.path.join(".claude", "skills", skill_name, "SKILL.md")
    if os.path.exists(claude_skill_path):
        return claude_skill_path

    workflows_dir = "workflows"
    if os.path.exists(workflows_dir):
        for domain in os.listdir(workflows_dir):
            domain_skill_path = os.path.join(workflows_dir, domain, "skills", skill_name, "SKILL.md")
            if os.path.exists(domain_skill_path):
                return domain_skill_path

    raise FileNotFoundError(f"SKILL.md not found for skill: {skill_name}")


def _run_contextual_prompt(
    skill_name: str, user_prompt: str, agent_prompt: str, sandbox_path: str, eval_env: dict, skill_path: str | None = None
) -> str:
    """Invoke the Subagent programmatically over the target sandbox."""
    if not skill_path:
        skill_path = _find_skill_file(skill_name)

    # Provide explicit sandbox context and force a fail-fast behavior mode
    contextual_prompt_tmpl = (
        f"Using the instructions in {skill_path}, accomplish the following:\n\nUSER REQUEST:\n{user_prompt.strip()}\n\n"
    )

    if agent_prompt:
        contextual_prompt_tmpl += f"NOTE TO AGENT:\n{agent_prompt.strip()}\n\n"

    contextual_prompt_tmpl += (
        "NOTE TO AGENT: FAIL FAST. This is an automated sandbox test. "
        "Execute your single primary command ONCE. "
        "If it fails, DO NOT attempt to rewrite the code, debug the environment, find alternative tools, or install dependencies. "
        "Output the raw error/output and exit immediately."
    )

    # Inject any dynamic environment variables into the prompt template
    env = os.environ.copy()
    env.update(eval_env)
    contextual_prompt = contextual_prompt_tmpl.format(**env)

    # Prepend .venv/bin to PATH so agent scripts use project dependencies
    workspace_root = os.path.dirname(os.path.dirname(sandbox_path))
    venv_bin = os.path.join(workspace_root, ".venv", "bin")
    original_path = os.environ.get("PATH", "")
    if os.path.isdir(venv_bin):
        os.environ["PATH"] = venv_bin + os.pathsep + original_path

    # Auto-detect the runner from the environment
    try:
        runner = get_runner()

        # Invoke Subagent programmatically in the sandbox
        output = str(runner.run(contextual_prompt, sandbox_path))
    finally:
        os.environ["PATH"] = original_path
    print(f"Agent Output:\n{output}")
    return output


def _validate_agent_output(output: str, expected_output: str) -> None:
    """Validate that the agent output matches expectations."""

    # 1. Attempt to extract JSON from the output (handles markdown wrappers)
    parsed_output = None
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", output, re.DOTALL)

    try:
        if json_match:
            parsed_output = json.loads(json_match.group(1))
        else:
            # Fallback if the LLM followed instructions and didn't use markdown
            parsed_output = json.loads(output)
    except json.JSONDecodeError:
        print("Warning: Could not parse output as JSON. Falling back to raw string matching.")
        parsed_output = {}  # Empty dict so dict key assertions fail rather than crash

    # 2. Setup the environment for the assertion payload
    env = {
        "output": output,  # The raw text output
        "parsed_output": parsed_output,  # The parsed JSON dictionary
        "os": os,
        "json": json,
    }

    # 3. Execute the assertions defined in the YAML's `expected_output`
    try:
        exec(expected_output, env)
    except AssertionError as e:
        raise AssertionError(
            f"Agent output validation failed.\nRaw Output: {output}\nParsed JSON: {json.dumps(parsed_output, indent=2)}\nError: {e}"
        )
