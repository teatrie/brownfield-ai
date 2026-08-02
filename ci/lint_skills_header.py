import glob
import sys
from pathlib import Path

import defopt
import yaml


def lint_file(file_path: str) -> bool:
    """Lint a single skill file.

    Read a skill file and ensure it has valid YAML frontmatter containing 'name' and 'description'.
    """
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return False

    if not content.startswith("---\n"):
        return False

    parts = content.split("---\n")
    if len(parts) < 3:
        return False

    frontmatter = parts[1]
    try:
        data = yaml.safe_load(frontmatter)
    except Exception:
        return False

    if not isinstance(data, dict):
        return False

    if "name" not in data or "description" not in data:
        return False

    return True


def lint_files(*paths: str) -> None:
    """Core orchestrator of the module's business logic.

    Find and lint SKILL.md files given file or directory paths or globs.
    """
    skill_files = []

    for path_str in paths:
        if not path_str:
            continue

        # Handle glob patterns explicitly
        if any(c in path_str for c in ["*", "?", "["]):
            for expanded_path in glob.glob(path_str, recursive=True):
                path = Path(expanded_path)
                if path.is_file() and path.name == "SKILL.md":
                    skill_files.append(path)
                elif path.is_dir():
                    skill_files.extend(path.rglob("SKILL.md"))
        else:
            path = Path(path_str)
            if path.is_file():
                if path.name == "SKILL.md":
                    skill_files.append(path)
            elif path.is_dir():
                skill_files.extend(path.rglob("SKILL.md"))
            else:
                if "SKILL.md" in path_str:
                    skill_files.append(path)

    # Deduplicate while preserving order
    unique_files = list(dict.fromkeys(skill_files))

    success = True
    for file_path in unique_files:
        if not lint_file(str(file_path)):
            print(f"File {file_path} failed linting.")
            success = False

    if not success:
        sys.exit(1)


def main(*paths: str) -> None:
    """CLI entry point. Do not perform core processing here.

    Args:
        paths: Files or directories to check for SKILL.md headers.

    """
    lint_files(*paths)


if __name__ == "__main__":
    defopt.run(main)
