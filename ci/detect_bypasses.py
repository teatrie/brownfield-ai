import sys
from pathlib import Path


def detect():
    targets = sys.argv[1:] if len(sys.argv) > 1 else ["."]
    targets = [t for t in targets if t and t.strip()]
    if not targets:
        targets = ["."]

    files = []
    for t in targets:
        p = Path(t)
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files.extend(p.rglob("*"))

    violations = []
    patterns = ["noqa", "type: ignore", "shellcheck disable", "eslint-disable"]
    exclude_files = ["noqa_fixer.py", "detect_bypasses.py", "test_detect_bypasses.py"]
    # tests/fixtures is excluded because fixtures are test payloads — they
    # may intentionally embed the very patterns the detector forbids in real
    # code (e.g., a `# noqa` inside a prompt-injection probe fixture consumed
    # by the diff-review smoke test).
    # agent-review is excluded for the same reason as tmp: it is git-ignored
    # scratch holding reviewer-agent transcripts, and those transcripts quote
    # the very patterns this detector forbids as part of their review criteria.
    # It never reaches CI, so the false positives are local-only — but this
    # harness runs reviewer agents routinely, so without this `task lint` goes
    # red on a developer's machine for output that is not project code.
    exclude_dirs = {
        ".git",
        ".venv",
        "tmp",
        "agent-review",
        "repos",
        "__pycache__",
        "third-party",
        "node_modules",
        "tests/fixtures",
    }
    workspace_root = Path(__file__).resolve().parent.parent
    exclude_paths = [workspace_root / d for d in exclude_dirs]

    for f in files:
        if not f.is_file() or f.name in exclude_files or f.suffix == ".md":
            continue
        if any(f.resolve().is_relative_to(ep) for ep in exclude_paths if ep.exists()):
            continue
        # Skip any *_cache or node_modules directories at any depth
        if any(part.endswith("_cache") or part == "node_modules" for part in f.resolve().parts):
            continue
        try:
            with open(f, encoding="utf-8") as file:
                for i, line in enumerate(file, 1):
                    line_lower = line.lower()
                    if any(p in line_lower for p in patterns):
                        violations.append(f"{f}:{i} - {line.strip()}")
                        break
        except (UnicodeDecodeError, PermissionError):
            pass

    if violations:
        print(
            "❌ ERROR: Linter bypass detected. Agents MUST NOT use noqa, type: ignore, "
            "shellcheck disable, or eslint-disable.\n"
            "The orchestrator must re-enter the implementation phase to resolve the underlying lint issue."
        )
        for v in violations:
            print(v)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    detect()
