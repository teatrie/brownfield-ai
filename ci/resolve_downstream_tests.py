"""Script for resolving downstream affected python tests based on code changes."""

import ast
import glob
import os
import re
import sys
from collections import defaultdict, deque
from pathlib import Path

import defopt

_WORKFLOW_SCRIPT_PATTERN = re.compile(r"^workflows/.+/skills/.+/scripts/[^/]+\.py$")


def extract_imports(filepath: str, src_dir: str = "src") -> list[str]:
    """Extract imported module names from a given python file.

    Args:
        filepath: The path to the Python file.
        src_dir: Base source directory for resolving relative imports.
            Defaults to "src".

    Returns:
        List of imported module names.

    """
    try:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
            tree = ast.parse(content, filename=filepath)
    except (OSError, SyntaxError) as e:
        print(f"Exception: {e}", file=sys.stderr)
        return []

    imports: list[str] = []

    src_dir_path = Path(src_dir).resolve()
    try:
        rel_path = Path(filepath).resolve().relative_to(src_dir_path)
        module_parts = list(rel_path.with_suffix("").parts)
    except ValueError:
        module_parts = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                level = node.level
                base_mod = node.module
                if level > 0:
                    base = module_parts[:-level]
                    if base:
                        base_mod = f"{'.'.join(base)}.{node.module}"
                imports.append(base_mod)
                for alias in node.names:
                    imports.append(f"{base_mod}.{alias.name}")
            else:
                level = node.level
                if level > 0:
                    base = module_parts[:-level]
                    if base:
                        base_mod = ".".join(base)
                        for alias in node.names:
                            imports.append(f"{base_mod}.{alias.name}")
    return imports


def build_dependency_graph(src_dir: str = "src") -> tuple[dict[str, set[str]], dict[str, str], dict[str, str]]:
    """Build a graph of reverse module dependencies for testing.

    Args:
        src_dir: Base source directory.

    Returns:
        Tuple of (reverse_graph, module_to_file, file_to_module).

    """
    reverse_graph: dict[str, set[str]] = defaultdict(set)
    module_to_file: dict[str, str] = {}
    file_to_module: dict[str, str] = {}

    src_path = Path(src_dir)
    for root, _, files in os.walk(src_path):
        for file in files:
            if file.endswith(".py"):
                full_path = Path(root) / file
                rel_path = full_path.relative_to(src_path)
                parts = list(rel_path.with_suffix("").parts)
                if parts[-1] == "__init__":
                    parts = parts[:-1]

                if parts:
                    mod_name = ".".join(parts)
                    module_to_file[mod_name] = str(full_path)
                    file_to_module[str(full_path)] = mod_name

    for fpath in file_to_module:
        mod_name = file_to_module[fpath]
        imported_modules = extract_imports(fpath)

        for imp in imported_modules:
            imp_parts = imp.split(".")
            for i in range(len(imp_parts), 0, -1):
                sub_imp = ".".join(imp_parts[:i])
                if sub_imp in module_to_file:
                    reverse_graph[sub_imp].add(mod_name)
                    break

    return reverse_graph, module_to_file, file_to_module


def find_affected_modules(changed_files: list[str], reverse_graph: dict[str, set[str]], file_to_module: dict[str, str]) -> set[str]:
    """Identify all modules affected by a list of changed files.

    Args:
        changed_files: List of file paths changed.
        reverse_graph: Mapping of base modules to their dependents.
        file_to_module: Mapping of file paths to their module representations.

    Returns:
        Set of module names affected by the changes.

    """
    affected: set[str] = set()
    queue: deque[str] = deque()

    for cf in changed_files:
        if cf in file_to_module:
            mod_name = file_to_module[cf]
            queue.append(mod_name)
            affected.add(mod_name)

    while queue:
        current = queue.popleft()
        if current in reverse_graph:
            for dept in reverse_graph[current]:
                if dept not in affected:
                    affected.add(dept)
                    queue.append(dept)

    return affected


def module_to_test_file(mod_name: str) -> str:
    """Convert a module name to its corresponding test file path.

    Args:
        mod_name: The name of the module.

    Returns:
        The matched test file path string, or empty string.

    """
    parts = mod_name.split(".")
    if len(parts) == 0:
        return ""

    parts[-1] = f"test_{parts[-1]}"
    test_path = Path("tests") / "src" / Path(*parts).with_suffix(".py")

    return str(test_path)


def core_resolve_tests(changed_files: tuple[str, ...]) -> None:
    """Core orchestrator to resolve and print downstream affected test files.

    Args:
        changed_files: Tuple of paths to modified files.

    """
    if not changed_files:
        return

    reverse_graph, module_to_file, file_to_module = build_dependency_graph("src")
    affected_modules = find_affected_modules(list(changed_files), reverse_graph, file_to_module)

    test_files_to_run: set[str] = set()
    for mod in affected_modules:
        test_file = module_to_test_file(mod)
        if test_file and os.path.isfile(test_file):
            test_files_to_run.add(test_file)

    for cf in changed_files:
        if cf.startswith("tests/src/") and cf.endswith(".py") and os.path.isfile(cf):
            test_files_to_run.add(cf)

    for resolved_tf in sorted(test_files_to_run):
        print(resolved_tf)


def resolve_workflow_tests(changed_files: tuple[str, ...]) -> None:
    """Resolve workflow script test files affected by changes.

    Uses AST import analysis to find all test files that import (directly or
    transitively) any of the changed workflow script modules. Scans ALL
    workflow test directories to catch cross-skill imports.

    Important:
        This function matches imports by **bare module stem** (e.g., ``todo_cli``,
        not ``workflows.agent_memory.skills.execution_ledger.scripts.todo_cli``).
        This works because ``tests/conftest.py`` injects all
        ``workflows/*/skills/*/scripts`` directories into ``sys.path`` as a flat
        namespace — so both source and test files use bare imports
        (``from todo_cli import ...``). Fully-qualified absolute imports would NOT
        be detected. This is by design: the flat namespace is the established
        convention enforced by conftest, and no workflow scripts use absolute imports.

    Args:
        changed_files: Paths to modified workflow script files.

    Raises:
        ValueError: If a path with /scripts/ does not match the expected
            workflows/*/skills/*/scripts/*.py pattern.

    """
    # Step 1: Validate inputs and group changed files by skill scripts dir
    skill_scripts_to_changed: dict[str, list[str]] = defaultdict(list)
    for path in changed_files:
        if not _WORKFLOW_SCRIPT_PATTERN.match(path):
            if "/scripts/" in path:
                raise ValueError(f"Unsupported path family: {path}. Only workflows/*/skills/*/scripts/*.py paths are supported.")
            # Silently skip non-script files (e.g., prompts)
            continue
        skill_scripts_dir = str(Path(path).parent)
        skill_scripts_to_changed[skill_scripts_dir].append(path)

    if not skill_scripts_to_changed:
        return

    # Step 2: Collect affected module names using per-skill dependency graphs
    affected_module_names: set[str] = set()

    for skill_scripts_dir, skill_changed_files in skill_scripts_to_changed.items():
        # Register all bare module stems in this skill scripts dir (non-recursive)
        module_to_file: dict[str, str] = {}
        file_to_module: dict[str, str] = {}
        skill_path = Path(skill_scripts_dir)
        for py_file in skill_path.glob("*.py"):
            if py_file.stem == "__init__":
                continue
            mod_name = py_file.stem
            module_to_file[mod_name] = str(py_file)
            file_to_module[str(py_file)] = mod_name

        # Build reverse dependency graph for this skill
        reverse_graph: dict[str, set[str]] = defaultdict(set)
        for fpath, mod_name in file_to_module.items():
            imported = extract_imports(fpath, src_dir=skill_scripts_dir)
            for imp in imported:
                bare = imp.split(".")[0]
                if bare in module_to_file and bare != mod_name:
                    reverse_graph[bare].add(mod_name)

        # Seed BFS with directly changed modules.
        # Primary lookup matches str(Path(cf)) against file_to_module keys, which are
        # also str(Path(...)) from glob — both repo-relative. This works for all real
        # callers (git diff --name-only output is always repo-relative without ./ prefix).
        # Stem fallback handles edge cases where path normalization diverges (e.g., if a
        # caller passes absolute paths or ./ prefixed paths). Stem is unambiguous within
        # a single skill scripts directory.
        directly_changed: list[str] = []
        for cf in skill_changed_files:
            resolved = str(Path(cf))
            if resolved in file_to_module:
                directly_changed.append(resolved)
            else:
                stem = Path(cf).stem
                if stem in module_to_file:
                    directly_changed.append(module_to_file[stem])

        affected_in_skill = find_affected_modules(directly_changed, reverse_graph, file_to_module)
        affected_module_names |= affected_in_skill

    if not affected_module_names:
        return

    # Step 3: Scan ALL workflow test directories for test files that import affected modules.
    # Full scan is required because conftest.py injects all skill script dirs into a flat
    # namespace, so tests can import modules from ANY skill (cross-skill imports). A per-skill
    # scan would miss these. This is O(total_workflow_test_files) AST parses — currently ~15
    # files at ~ms each. If the workflow test count grows significantly, add a grep pre-filter
    # to skip files that don't contain any affected module name before incurring AST overhead.
    test_files_to_run: set[str] = set()

    all_test_dirs = glob.glob("tests/workflows/*/skills/*/scripts")
    all_test_dirs += glob.glob("tests/workflows/*/skills/*/*/scripts")

    for test_dir in all_test_dirs:
        for test_file in Path(test_dir).glob("*.py"):
            imports = extract_imports(str(test_file), src_dir=test_dir)
            bare_imports = {imp.split(".")[0] for imp in imports}
            if bare_imports & affected_module_names:
                test_files_to_run.add(str(test_file))

    # Step 4: Emit sorted, deduplicated test file paths that exist on disk
    for resolved_tf in sorted(test_files_to_run):
        if os.path.isfile(resolved_tf):
            print(resolved_tf)


def main(*files: str) -> None:
    """CLI entry point for resolving brownfield_ai downstream tests."""
    core_resolve_tests(files)


def workflow(*files: str) -> None:
    """CLI entry point for resolving workflow script downstream tests."""
    resolve_workflow_tests(files)


if __name__ == "__main__":
    defopt.run({"main": main, "workflow": workflow})
