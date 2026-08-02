"""Tests for the eval harness's environment-requirement gate."""

import pytest

from helpers.eval_utils import _skip_if_required_env_missing


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
