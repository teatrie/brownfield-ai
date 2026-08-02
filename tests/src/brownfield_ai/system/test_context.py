"""
Tests for the system context module.
"""

from unittest.mock import patch

from brownfield_ai.system import context


def test_get_current_user_with_user_email():
    """
    Test that USER_EMAIL overrides local user when present.
    """
    with patch("os.environ.get", return_value="user@example.com"):
        assert context.get_current_user() == "user"


def test_get_current_user_with_malformed_email():
    """
    Test fallback to getuser if USER_EMAIL does not contain an @.
    """
    with patch("os.environ.get", return_value="userexample.com"), patch("getpass.getuser", return_value="local_fallback"):
        assert context.get_current_user() == "local_fallback"


def test_get_current_user_no_env_var():
    """
    Test fallback to local user when no USER_EMAIL is present.
    """
    with patch("os.environ.get", return_value=""), patch("getpass.getuser", return_value="local_fallback"):
        assert context.get_current_user() == "local_fallback"
