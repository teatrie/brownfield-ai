import pytest
from helpers.eval_utils import get_eval_cases, run_skill_eval


@pytest.mark.aws_mock
@pytest.mark.parametrize(
    "eval_case", get_eval_cases("glue-catalog-schema"), ids=lambda c: f"glue-catalog-schema-{c['eval_config'].get('case', 'unknown')}"
)
def test_glue_catalog_schema(eval_case):
    run_skill_eval(eval_case)


@pytest.mark.aws_mock
@pytest.mark.parametrize(
    "eval_case", get_eval_cases("redshift-table-schema"), ids=lambda c: f"redshift-table-schema-{c['eval_config'].get('case', 'unknown')}"
)
def test_redshift_table_schema(eval_case):
    run_skill_eval(eval_case)


@pytest.mark.aws_mock
@pytest.mark.parametrize(
    "eval_case", get_eval_cases("dynamodb-table-schema"), ids=lambda c: f"dynamodb-table-schema-{c['eval_config'].get('case', 'unknown')}"
)
def test_dynamodb_table_schema(eval_case):
    run_skill_eval(eval_case)


@pytest.mark.aws_mock
@pytest.mark.parametrize(
    "eval_case", get_eval_cases("athena-query-analysis"), ids=lambda c: f"athena-query-analysis-{c['eval_config'].get('case', 'unknown')}"
)
def test_athena_query_analysis(eval_case):
    run_skill_eval(eval_case)


@pytest.mark.aws_mock
@pytest.mark.parametrize(
    "eval_case", get_eval_cases("glue-find-tables"), ids=lambda c: f"glue-find-tables-{c['eval_config'].get('case', 'unknown')}"
)
def test_glue_find_tables(eval_case):
    run_skill_eval(eval_case)


@pytest.mark.aws_mock
@pytest.mark.parametrize(
    "eval_case",
    get_eval_cases("redshift-query-analysis"),
    ids=lambda c: f"redshift-query-analysis-{c['eval_config'].get('case', 'unknown')}",
)
def test_redshift_query_analysis(eval_case):
    run_skill_eval(eval_case)


@pytest.mark.aws_mock
@pytest.mark.parametrize(
    "eval_case", get_eval_cases("athena-query-execute"), ids=lambda c: f"athena-query-execute-{c['eval_config'].get('case', 'unknown')}"
)
def test_athena_query_execute(eval_case):
    run_skill_eval(eval_case)


if __name__ == "__main__":
    pytest.main(["-v", __file__])
