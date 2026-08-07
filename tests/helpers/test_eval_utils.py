"""Tests for the eval harness's environment-requirement gate and sandbox copy filter."""

import os

import pytest

from helpers.eval_utils import _skip_if_required_env_missing, _workspace_copy_ignore


def test_no_requires_env_does_not_skip():
    _skip_if_required_env_missing({"case": "example"})


def test_empty_requires_env_does_not_skip():
    _skip_if_required_env_missing({"case": "example", "requires_env": []})


def test_satisfied_requires_env_does_not_skip(monkeypatch):
    monkeypatch.setenv("BROWNFIELD_ORG", "acme")

    _skip_if_required_env_missing({"case": "example", "requires_env": ["BROWNFIELD_ORG"]})


def test_unset_requires_env_skips(monkeypatch):
    monkeypatch.delenv("BROWNFIELD_ORG", raising=False)

    with pytest.raises(pytest.skip.Exception, match="BROWNFIELD_ORG"):
        _skip_if_required_env_missing({"case": "example", "requires_env": ["BROWNFIELD_ORG"]})


def test_empty_value_counts_as_missing(monkeypatch):
    """An empty value must skip, not run.

    Assertions in these cases take the form
    ``assert os.environ["BROWNFIELD_ORG"] in output``. With an empty string
    that succeeds against any output at all, so treating empty as present
    would convert a misconfiguration into a false pass.
    """
    monkeypatch.setenv("BROWNFIELD_ORG", "")

    with pytest.raises(pytest.skip.Exception, match="BROWNFIELD_ORG"):
        _skip_if_required_env_missing({"case": "example", "requires_env": ["BROWNFIELD_ORG"]})


def test_reports_every_missing_variable(monkeypatch):
    monkeypatch.delenv("BROWNFIELD_ORG", raising=False)
    monkeypatch.delenv("BROWNFIELD_INFRA_REPO", raising=False)

    with pytest.raises(pytest.skip.Exception) as excinfo:
        _skip_if_required_env_missing({
            "case": "example",
            "requires_env": ["BROWNFIELD_ORG", "BROWNFIELD_INFRA_REPO"],
        })

    assert "BROWNFIELD_ORG" in str(excinfo.value)
    assert "BROWNFIELD_INFRA_REPO" in str(excinfo.value)


def test_root_evals_directory_is_not_copied_into_the_sandbox():
    """The case definitions carry ``expected_output`` — the agent must not see them."""
    workspace = os.path.join("tests", "skills", "auto-pr")

    ignored = _workspace_copy_ignore(workspace, workspace, ["evals", "scripts", "README.md"])

    assert "evals" in ignored
    assert "scripts" not in ignored
    assert "README.md" not in ignored


def test_nested_evals_directory_is_copied():
    workspace = os.path.join("tests", "skills", "auto-pr")
    nested = os.path.join(workspace, "scripts")

    assert _workspace_copy_ignore(workspace, nested, ["evals", "helper.py"]) == []


def test_workspace_artifacts_are_ignored_at_every_depth():
    workspace = os.path.join("tests", "skills", "auto-pr")
    nested = os.path.join(workspace, "scripts")

    assert set(_workspace_copy_ignore(workspace, workspace, ["tmp", "__pycache__", ".pytest_cache"])) == {
        "tmp",
        "__pycache__",
        ".pytest_cache",
    }
    assert _workspace_copy_ignore(workspace, nested, ["__pycache__"]) == ["__pycache__"]


def test_absent_names_are_not_reported_as_ignored():
    """``copytree`` tolerates unknown names, but reporting them would mislead a reader."""
    workspace = os.path.join("tests", "skills", "github-search")

    assert _workspace_copy_ignore(workspace, workspace, ["SKILL.md"]) == []
