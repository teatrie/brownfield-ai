import subprocess
from pathlib import Path

import pytest


def run_detect_bypasses(file_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python", "ci/detect_bypasses.py", str(file_path)],
        capture_output=True,
        text=True,
    )


def test_detect_bypasses_clean_file(tmp_path: Path):
    test_file = tmp_path / "clean_code.py"
    test_file.write_text("def hello():\n    print('world')\n")

    result = run_detect_bypasses(test_file)

    assert result.returncode == 0


@pytest.mark.parametrize(
    "content, bypass_type",
    [
        ("def hello():\n    print('world')  # noqa: E501\n", "noqa"),
        ("def hello():\n    print('world')  # type: ignore\n", "type: ignore"),
        ("# shellcheck disable=SC2086\necho \\$VAR", "shellcheck"),
    ],
)
def test_detect_bypasses_forbidden_comments(tmp_path: Path, content: str, bypass_type: str):
    test_file = tmp_path / f"dirty_code_{bypass_type.replace(':', '').replace(' ', '_')}.txt"
    test_file.write_text(content)

    result = run_detect_bypasses(test_file)

    assert result.returncode != 0


def test_detect_bypasses_fixtures_dir_excluded() -> None:
    """Files under tests/fixtures/ that contain bypass patterns do not trip the detector.

    Fixture files are test payloads — they may deliberately include the
    exact patterns real code is forbidden from using (e.g., diff-review
    prompt-injection probes). The detector excludes ``tests/fixtures`` by
    path so a real fixture at that location does not block CI.
    """
    workspace_root = Path(__file__).resolve().parents[2]
    fixture_path = workspace_root / "tests" / "fixtures" / "diff-review" / "synthetic-violation.diff"
    if not fixture_path.exists():
        pytest.skip(f"fixture absent: {fixture_path}")
    result = run_detect_bypasses(fixture_path)
    assert result.returncode == 0, (
        f"Expected tests/fixtures/ to be excluded from bypass detection; stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
