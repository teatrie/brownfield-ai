import os
from pathlib import Path

from ci.resolve_downstream_tests import (
    build_dependency_graph,
    extract_imports,
    find_affected_modules,
    module_to_test_file,
)


def test_extract_imports(tmp_path):
    p = tmp_path / "foo.py"
    p.write_text("import os\nimport sys\nfrom brownfield_ai.bar import baz\nfrom . import local_mod\n", encoding="utf-8")

    # Needs to be mocked relative to "src"
    # Wait, extract_imports expects paths like `src/brownfield_ai/foo.py` to figure out relative module
    src_dir = tmp_path / "src"
    mod_dir = src_dir / "brownfield_ai"
    mod_dir.mkdir(parents=True)
    foo_file = mod_dir / "foo.py"

    foo_file.write_text("import sys\nfrom . import baz\n", encoding="utf-8")

    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        imports = extract_imports(str(foo_file))
        assert "sys" in imports
        assert "brownfield_ai.baz" in imports
    finally:
        os.chdir(old_cwd)


def test_module_to_test_file():
    mod_name = "brownfield_ai.services.aws"
    test_file = module_to_test_file(mod_name)
    assert test_file == str(Path("tests/src/brownfield_ai/services/test_aws.py"))


def test_build_dependency_graph_reverse_mapping(tmp_path):
    """
    Test that modifying an upstream module correctly flags downstream modules that
    imported it via fully-qualified ImportFrom syntax (e.g. `from brownfield_ai.services import aws`).
    """
    src_dir = tmp_path / "src"
    services_dir = src_dir / "brownfield_ai" / "services"
    other_dir = src_dir / "brownfield_ai" / "other_package"
    services_dir.mkdir(parents=True)
    other_dir.mkdir(parents=True)

    # Upstream: src/brownfield_ai/services/aws.py
    aws_file = services_dir / "aws.py"
    aws_file.write_text("def do_aws(): pass\n", encoding="utf-8")

    # Downstream: src/brownfield_ai/other_package/some_module.py (imports aws)
    some_file = other_dir / "some_module.py"
    some_file.write_text("from brownfield_ai.services import aws\ndef use_aws(): aws.do_aws()\n", encoding="utf-8")

    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        # Check extraction first
        imports = extract_imports(str(some_file))
        assert "brownfield_ai.services.aws" in imports

        # Verify dependency graph construction
        reverse_graph, module_to_file, file_to_module = build_dependency_graph("src")

        # Test reverse mapping identifies downstream module
        downstream_module = "brownfield_ai.other_package.some_module"
        upstream_module = "brownfield_ai.services.aws"
        assert downstream_module in reverse_graph[upstream_module]

        # Verify affected modules logic maps test properly
        # The find_affected_modules uses the string keys present in `file_to_module`,
        # which are relative 'src/...' strings returned by the graph builder
        relative_aws_path = "src/brownfield_ai/services/aws.py"
        affected = find_affected_modules([relative_aws_path], reverse_graph, file_to_module)
        assert upstream_module in affected
        assert downstream_module in affected
    finally:
        os.chdir(old_cwd)
