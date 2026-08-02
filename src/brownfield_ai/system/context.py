import getpass
import os
from pathlib import Path


def get_current_user() -> str:
    """
    Fetch the active application user for namespacing.

    Parses USER_EMAIL for standard identity.
    The USER_EMAIL should be set in .envrc by the scripts/setup_env.sh.
    Falls back to the executing system logname/user.
    """
    user_email = os.environ.get("USER_EMAIL", "")
    if user_email and "@" in user_email:
        return user_email.split("@")[0]

    return getpass.getuser()


def get_workspace_root() -> Path:
    """
    Find the workspace root directory.
    Walks up the directory tree looking for pyproject.toml as a root marker.
    """
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").exists() or (parent / "CLAUDE.md").exists():
            return parent
    return Path.cwd()
