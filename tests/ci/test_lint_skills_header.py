from ci.lint_skills_header import lint_file


def test_lint_file_valid_structure(tmp_path):
    file = tmp_path / "valid.md"
    file.write_text("---\nname: my-skill\ndescription: my description\n---\n# Content")
    assert lint_file(str(file)) is True


def test_lint_file_missing_opening_dashes(tmp_path):
    file = tmp_path / "missing_open.md"
    file.write_text("name: my-skill\ndescription: my description\n---\n# Content")
    assert lint_file(str(file)) is False


def test_lint_file_missing_closing_dashes(tmp_path):
    file = tmp_path / "missing_close.md"
    file.write_text("---\nname: my-skill\ndescription: my description\n# Content")
    assert lint_file(str(file)) is False


def test_lint_file_invalid_yaml(tmp_path):
    file = tmp_path / "invalid_yaml.md"
    file.write_text("---\nname: my-skill\n  invalid_indent: - [\ndescription: my description\n---\n# Content")
    assert lint_file(str(file)) is False


def test_lint_file_missing_name(tmp_path):
    file = tmp_path / "missing_name.md"
    file.write_text("---\ndescription: my description\n---\n# Content")
    assert lint_file(str(file)) is False


def test_lint_file_missing_description(tmp_path):
    file = tmp_path / "missing_description.md"
    file.write_text("---\nname: my-skill\n---\n# Content")
    assert lint_file(str(file)) is False
