import pytest
from helpers.eval_utils import get_eval_cases, run_skill_eval


@pytest.mark.parametrize(
    "eval_case",
    get_eval_cases("knowledge-checkpoint"),
    ids=lambda c: f"knowledge-checkpoint-{c['eval_config'].get('case', 'unknown')}",
)
def test_knowledge_checkpoint(eval_case):
    run_skill_eval(eval_case)


@pytest.mark.parametrize(
    "eval_case",
    get_eval_cases("execution-ledger"),
    ids=lambda c: f"execution-ledger-{c['eval_config'].get('case', 'unknown')}",
)
def test_execution_ledger(eval_case):
    run_skill_eval(eval_case)


if __name__ == "__main__":
    pytest.main(["-v", __file__])
