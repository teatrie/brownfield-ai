import pytest
from helpers.eval_utils import get_eval_cases, run_skill_eval

# ============================================================================
# Core Testing Scopes
# ============================================================================


@pytest.mark.parametrize(
    "eval_case", get_eval_cases("github-search"), ids=lambda c: f"github-search-{c['eval_config'].get('case', 'unknown')}"
)
def test_github_search(eval_case):
    run_skill_eval(eval_case)


@pytest.mark.parametrize(
    "eval_case", get_eval_cases("aws-vault-auth"), ids=lambda c: f"aws-vault-auth-{c['eval_config'].get('case', 'unknown')}"
)
def test_aws_vault_auth(eval_case):
    run_skill_eval(eval_case)


if __name__ == "__main__":
    pytest.main(["-v", __file__])
