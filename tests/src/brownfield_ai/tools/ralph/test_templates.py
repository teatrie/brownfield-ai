from __future__ import annotations

import jinja2
import pytest

from brownfield_ai.tools.ralph.templates import _TEMPLATE_DIR, get_template


def test_get_template_returns_valid_template() -> None:
    """Known template returns a compiled Jinja2 Template object."""
    template = get_template("session_prompt.md.j2")
    assert isinstance(template, jinja2.Template)


def test_get_template_raises_on_missing_template() -> None:
    """Missing template name raises TemplateNotFound."""
    with pytest.raises(jinja2.TemplateNotFound):
        get_template("nonexistent_template.j2")


def test_template_dir_points_to_actual_directory() -> None:
    """_TEMPLATE_DIR resolves to the real templates/ directory."""
    assert _TEMPLATE_DIR.is_dir()
    assert (_TEMPLATE_DIR / "session_prompt.md.j2").is_file()
