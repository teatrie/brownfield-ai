from ci.lint_evals import check_evals_file


def test_lint_evals_extra_root_key(tmp_path):
    file = tmp_path / "evals.yml"
    file.write_text("""
skill_name: "test-skill"
extra_root_key: "bad"
evals:
  - case: "test_case"
    expected_output: "assert True"
""")
    errors = check_evals_file(str(file))
    assert any("Invalid root key found: 'extra_root_key'" in err for err in errors), f"Expected root key error, got: {errors}"


def test_lint_evals_extra_eval_key(tmp_path):
    file = tmp_path / "evals.yml"
    file.write_text("""
skill_name: "test-skill"
evals:
  - case: "test_case"
    eval_config:
      model_tier: smart
    expected_output: "assert True"
""")
    errors = check_evals_file(str(file))
    assert any("Invalid key 'eval_config' in eval case" in err for err in errors), f"Expected eval key error, got: {errors}"


def test_lint_evals_valid_keys(tmp_path):
    file = tmp_path / "evals.yml"
    file.write_text("""
skill_name: "test-skill"
evals:
  - case: "test_case"
    user_prompt: "hello"
    agent_prompt: "world"
    setup: "pass"
    files: []
    expected_output: "assert True"
""")
    errors = check_evals_file(str(file))
    invalid_errors = [err for err in errors if "Invalid key" in err or "Invalid root key" in err]
    assert len(invalid_errors) == 0, f"Expected no strict key errors, got: {invalid_errors}"


def test_lint_evals_requires_env_accepted(tmp_path):
    file = tmp_path / "evals.yml"
    file.write_text("""
skill_name: "test-skill"
evals:
  - case: "test_case"
    requires_env: [BROWNFIELD_ORG]
    expected_output: "assert True"
""")
    errors = check_evals_file(str(file))
    invalid_errors = [err for err in errors if "Invalid key" in err or "requires_env" in err]
    assert len(invalid_errors) == 0, f"Expected requires_env to be a valid key, got: {invalid_errors}"


def test_lint_evals_requires_env_rejects_non_list(tmp_path):
    file = tmp_path / "evals.yml"
    file.write_text("""
skill_name: "test-skill"
evals:
  - case: "test_case"
    requires_env: "BROWNFIELD_ORG"
    expected_output: "assert True"
""")
    errors = check_evals_file(str(file))
    assert any("must be a list of non-empty strings" in err for err in errors), f"Expected requires_env shape error, got: {errors}"


def test_lint_evals_ast_setup(tmp_path):
    file = tmp_path / "evals.yml"
    file.write_text("""
skill_name: "test-skill"
evals:
  - case: "test_case"
    setup: "x = 1 +"
    expected_output: "assert True"
""")
    errors = check_evals_file(str(file))
    assert any("SyntaxError in setup for case 'test_case'" in err for err in errors), f"Expected syntax error in setup, got: {errors}"


def test_lint_evals_ast_expected_output(tmp_path):
    file = tmp_path / "evals.yml"
    file.write_text("""
skill_name: "test-skill"
evals:
  - case: "test_case"
    setup: "x = 1"
    expected_output: "assert True and"
""")
    errors = check_evals_file(str(file))
    assert any("SyntaxError in expected_output for case 'test_case'" in err for err in errors), (
        f"Expected syntax error in expected_output, got: {errors}"
    )
