import pytest
from helpers.eval_utils import get_eval_cases, run_skill_eval


@pytest.mark.parametrize("eval_case", get_eval_cases("status-sync"), ids=lambda c: f"status-sync-{c['eval_config'].get('case', 'unknown')}")
def test_status_sync(eval_case):
    run_skill_eval(eval_case)


if __name__ == "__main__":
    pytest.main(["-v", __file__])
