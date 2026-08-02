"""
Lint evaluation configurations natively against repository schema constraints.

This module validates that dynamic test evaluations defined in `evals.yml`
manifests conform to exact structural parameters, without extra keys or
invalid YAML/Python configurations.
"""

import ast
import os
import sys

import defopt
import yaml


def check_evals_file(filepath: str) -> list[str]:
    """
    Parse and validate a single `evals.yml` testing manifest.

    Args:
        filepath: The relative or absolute path to the `evals.yml` file to parse.

    Returns:
        A list of string violation messages. Empty list if the file passes seamlessly.
    """
    errors = []
    try:
        with open(filepath) as f:
            data = yaml.safe_load(f)
    except Exception as e:
        return [f"YAML parse error: {e}"]

    if not isinstance(data, dict):
        return ["Root YAML structure must be a dictionary"]

    # Strict key checks
    ALLOWED_ROOT_KEYS = {"skill_name", "evals"}
    ALLOWED_EVAL_KEYS = {"case", "user_prompt", "agent_prompt", "requires_env", "setup", "expected_output", "files"}

    for key in data.keys():
        if key not in ALLOWED_ROOT_KEYS:
            errors.append(f"Invalid root key found: '{key}'. Allowed keys are: {', '.join(ALLOWED_ROOT_KEYS)}")

    skill_name = data.get("skill_name")
    if not skill_name:
        errors.append("Missing 'skill_name' key")

    evals = data.get("evals", [])
    if not isinstance(evals, list):
        errors.append("'evals' must be a list")
    else:
        for i, eval_case in enumerate(evals):
            if not isinstance(eval_case, dict):
                errors.append(f"Eval case {i} is not a dictionary")
                continue

            for key in eval_case.keys():
                if key not in ALLOWED_EVAL_KEYS:
                    errors.append(f"Invalid key '{key}' in eval case '{eval_case.get('case', i)}'. Allowed: {', '.join(ALLOWED_EVAL_KEYS)}")

            expected_output = eval_case.get("expected_output")
            if expected_output:
                try:
                    # check if the python syntax is valid
                    ast.parse(expected_output)
                except SyntaxError as e:
                    errors.append(f"SyntaxError in expected_output for case '{eval_case.get('case', i)}': {e}")
            else:
                errors.append(f"Missing 'expected_output' for case '{eval_case.get('case', i)}'")

            # requires_env names the environment variables a case interpolates
            # into its prompts or assertions. The eval harness skips the case
            # when any of them is unset, so a malformed declaration would
            # silently disable that protection rather than fail loudly.
            requires_env = eval_case.get("requires_env")
            if requires_env is not None and (
                not isinstance(requires_env, list) or not all(isinstance(name, str) and name for name in requires_env)
            ):
                errors.append(f"'requires_env' for case '{eval_case.get('case', i)}' must be a list of non-empty strings")

            setup = eval_case.get("setup")
            if setup:
                try:
                    # check if the python syntax is valid
                    ast.parse(setup)
                except SyntaxError as e:
                    errors.append(f"SyntaxError in setup for case '{eval_case.get('case', i)}': {e}")

    # Check for Orphan
    test_evals_path = None
    # We resolve from the filepath back up to tests
    # e.g., tests/workflows/data-engineering/skills/glue-catalog-schema/evals/evals.yml
    # e.g., tests/skills/aws-cli/evals/evals.yml
    # e.g., tests/skills/github-search/evals.yml

    parts = filepath.split(os.sep)
    if "tests" in parts:
        tests_idx = parts.index("tests")
        if tests_idx + 1 < len(parts):
            if parts[tests_idx + 1] == "workflows" and tests_idx + 2 < len(parts):
                domain = parts[tests_idx + 2]
                domain_clean = domain.replace("-", "_")
                test_evals_path = os.path.join(*parts[: tests_idx + 1], "workflows", domain, f"test_{domain_clean}_evals.py")
            elif parts[tests_idx + 1] == "skills":
                test_evals_path = os.path.join(*parts[: tests_idx + 1], "skills", "test_evals.py")

    # Check if we should enforce mapping based on conventions
    if not test_evals_path or not os.path.exists(test_evals_path):
        if hasattr(errors, "append"):
            errors.append(f"Orphan Detection: Associated test file not found. Expected {test_evals_path}")
    else:
        if skill_name:
            with open(test_evals_path) as f:
                content = f.read()
                expected_call1 = f"get_eval_cases('{skill_name}')"
                expected_call2 = f'get_eval_cases("{skill_name}")'

                # Check for either style of quotes, also allow variable formatting
                # We can do a string search for the base skill_name string just to be safe
                # actually we should search for `get_eval_cases` with `skill_name`
                if expected_call1 not in content and expected_call2 not in content:
                    errors.append(f"Orphan Detection: {test_evals_path} does not seem to parameterize get_eval_cases for '{skill_name}'")

    return errors


def main(*files: str) -> None:
    """
    Lint evals.yml files.

    Args:
        files: Files to lint (or the directory to scan).
    """
    paths_to_check: list[str] = list(files)
    if not paths_to_check or paths_to_check == ["."]:
        # Recursive glob to find all evals.yml files
        paths_to_check = []
        for root, _, current_files in os.walk("."):
            if ".git" in root or "repos" in root or "tmp" in root or "node_modules" in root:
                continue
            for fname in current_files:
                if "evals.yml" == fname:
                    paths_to_check.append(os.path.join(root, fname))

    # Clean up file paths (e.g. remove ./ prefix)
    paths_to_check = [os.path.normpath(f) for f in paths_to_check]
    paths_to_check = list(set([f for f in paths_to_check if f.endswith("evals.yml")]))

    all_passed = True
    for f in paths_to_check:
        if not os.path.exists(f):
            continue

        print(f"Linting {f}...")
        errors = check_evals_file(f)
        if errors:
            all_passed = False
            for err in errors:
                print(f"  ❌ {err}")
        else:
            print("  ✅ OK")

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    defopt.run(main)
