"""Shared Jinja2 template loading for ralph headless session and CI-fix prompt rendering."""

from pathlib import Path

import jinja2

_TEMPLATE_DIR: Path = Path(__file__).resolve().parent / "templates"
"""Absolute path to the ``templates/`` directory adjacent to this module."""

_ENV: jinja2.Environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    keep_trailing_newline=True,
    undefined=jinja2.StrictUndefined,
)
"""Module-level singleton Jinja2 environment, cached at import time."""


def get_template(name: str) -> jinja2.Template:
    """Return the named Jinja2 template from the shared environment.

    Args:
        name: Template filename (e.g. ``"session_prompt.md.j2"``).

    Returns:
        The compiled Jinja2 template.

    Raises:
        jinja2.TemplateNotFound: If the named template does not exist.
    """
    return _ENV.get_template(name)
