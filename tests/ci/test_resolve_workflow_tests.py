"""Tests for resolve_workflow_tests() — workflow script to test file resolution."""

import os

import pytest

from ci.resolve_downstream_tests import resolve_workflow_tests


@pytest.fixture
def workflow_tree(tmp_path):
    """Build a realistic workflow/tests directory structure for testing."""
    # Skill 1: execution-ledger with two scripts
    skill1_src = tmp_path / "workflows" / "agent-memory" / "skills" / "execution-ledger" / "scripts"
    skill1_src.mkdir(parents=True)

    # todo_cli.py imports chromadb_ledger
    (skill1_src / "todo_cli.py").write_text(
        "from chromadb_ledger import save_record\ndef run(): pass\n",
        encoding="utf-8",
    )
    (skill1_src / "chromadb_ledger.py").write_text(
        "def save_record(): pass\n",
        encoding="utf-8",
    )

    # Skill 2: knowledge-checkpoint with one script
    skill2_src = tmp_path / "workflows" / "agent-memory" / "skills" / "knowledge-checkpoint" / "scripts"
    skill2_src.mkdir(parents=True)
    (skill2_src / "knowledge_checkpoint.py").write_text(
        "def checkpoint(): pass\n",
        encoding="utf-8",
    )

    # Test for skill 1
    skill1_test = tmp_path / "tests" / "workflows" / "agent-memory" / "skills" / "execution-ledger" / "scripts"
    skill1_test.mkdir(parents=True)
    (skill1_test / "test_todo_cli.py").write_text(
        "from todo_cli import run\ndef test_run(): assert run is not None\n",
        encoding="utf-8",
    )

    # Test for skill 2 — BUT imports from skill 1 (cross-skill)
    skill2_test = tmp_path / "tests" / "workflows" / "agent-memory" / "skills" / "knowledge-base" / "scripts"
    skill2_test.mkdir(parents=True)
    (skill2_test / "test_knowledge_clients.py").write_text(
        "from knowledge_checkpoint import checkpoint\nfrom chromadb_ledger import save_record\ndef test_clients(): pass\n",
        encoding="utf-8",
    )

    return tmp_path


def test_direct_dependency_finds_test(workflow_tree, capsys):
    old_cwd = os.getcwd()
    os.chdir(workflow_tree)
    try:
        resolve_workflow_tests(("workflows/agent-memory/skills/execution-ledger/scripts/todo_cli.py",))
        output = capsys.readouterr().out.strip()
        assert "test_todo_cli.py" in output
    finally:
        os.chdir(old_cwd)


def test_transitive_dependency_finds_importing_test(workflow_tree, capsys):
    old_cwd = os.getcwd()
    os.chdir(workflow_tree)
    try:
        resolve_workflow_tests(("workflows/agent-memory/skills/execution-ledger/scripts/chromadb_ledger.py",))
        output = capsys.readouterr().out.strip()
        assert "test_todo_cli.py" in output
    finally:
        os.chdir(old_cwd)


def test_no_test_exists_returns_empty(workflow_tree, capsys):
    old_cwd = os.getcwd()
    os.chdir(workflow_tree)
    try:
        # knowledge_checkpoint has no direct test in its own skill test dir,
        # but IS imported by cross-skill test. So use a truly isolated script.
        isolated_skill = workflow_tree / "workflows" / "data-eng" / "skills" / "isolated" / "scripts"
        isolated_skill.mkdir(parents=True)
        (isolated_skill / "orphan.py").write_text("def noop(): pass\n", encoding="utf-8")

        resolve_workflow_tests(("workflows/data-eng/skills/isolated/scripts/orphan.py",))
        output = capsys.readouterr().out.strip()
        assert output == ""
    finally:
        os.chdir(old_cwd)


def test_init_py_skipped(workflow_tree, capsys):
    old_cwd = os.getcwd()
    os.chdir(workflow_tree)
    try:
        skill_dir = workflow_tree / "workflows" / "agent-memory" / "skills" / "execution-ledger" / "scripts"
        (skill_dir / "__init__.py").write_text("", encoding="utf-8")

        resolve_workflow_tests(("workflows/agent-memory/skills/execution-ledger/scripts/__init__.py",))
        output = capsys.readouterr().out.strip()
        assert output == ""
    finally:
        os.chdir(old_cwd)


def test_non_scripts_path_silently_skipped(workflow_tree, capsys):
    old_cwd = os.getcwd()
    os.chdir(workflow_tree)
    try:
        resolve_workflow_tests(("workflows/agent-memory/skills/execution-ledger/prompts/foo.md",))
        output = capsys.readouterr().out.strip()
        assert output == ""
    finally:
        os.chdir(old_cwd)


def test_cross_domain_multi_skill_resolves_both(workflow_tree, capsys):
    old_cwd = os.getcwd()
    os.chdir(workflow_tree)
    try:
        resolve_workflow_tests((
            "workflows/agent-memory/skills/execution-ledger/scripts/todo_cli.py",
            "workflows/agent-memory/skills/knowledge-checkpoint/scripts/knowledge_checkpoint.py",
        ))
        output = capsys.readouterr().out.strip()
        lines = output.split("\n") if output else []
        # test_todo_cli.py imports todo_cli
        assert any("test_todo_cli.py" in line for line in lines)
        # test_knowledge_clients.py imports knowledge_checkpoint (cross-skill)
        assert any("test_knowledge_clients.py" in line for line in lines)
    finally:
        os.chdir(old_cwd)


def test_deduplication_emits_once(workflow_tree, capsys):
    old_cwd = os.getcwd()
    os.chdir(workflow_tree)
    try:
        # chromadb_ledger affects test_todo_cli (transitive) AND test_knowledge_clients (direct import)
        # Pass both chromadb_ledger and todo_cli to potentially hit test_todo_cli via two paths
        resolve_workflow_tests((
            "workflows/agent-memory/skills/execution-ledger/scripts/chromadb_ledger.py",
            "workflows/agent-memory/skills/execution-ledger/scripts/todo_cli.py",
        ))
        output = capsys.readouterr().out.strip()
        lines = output.split("\n") if output else []
        # test_todo_cli should appear exactly once
        todo_matches = [line for line in lines if "test_todo_cli.py" in line]
        assert len(todo_matches) == 1
    finally:
        os.chdir(old_cwd)


def test_claude_skills_path_raises_valueerror(workflow_tree):
    old_cwd = os.getcwd()
    os.chdir(workflow_tree)
    try:
        with pytest.raises(ValueError, match="Unsupported path family"):
            resolve_workflow_tests((".claude/skills/github-search/scripts/search.py",))
    finally:
        os.chdir(old_cwd)


def test_cross_skill_import_detected(workflow_tree, capsys):
    old_cwd = os.getcwd()
    os.chdir(workflow_tree)
    try:
        resolve_workflow_tests(("workflows/agent-memory/skills/knowledge-checkpoint/scripts/knowledge_checkpoint.py",))
        output = capsys.readouterr().out.strip()
        assert "test_knowledge_clients.py" in output
    finally:
        os.chdir(old_cwd)
