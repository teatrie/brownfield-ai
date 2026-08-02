"""Unit tests for the aws_vault_auth.sh script."""

import os
import subprocess
from pathlib import Path


def test_aws_vault_auth_success(tmp_path: Path) -> None:
    """Test that the script correctly parses and formats AWS credentials."""
    # Create a mock aws-vault executable
    mock_bin = tmp_path / "aws-vault"
    mock_bin.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = "exec" ] && [ "$3" = "--" ] && [ "$4" = "env" ]; then\n'
        "  echo 'AWS_ACCESS_KEY_ID=mock_key_id'\n"
        "  echo 'AWS_SECRET_ACCESS_KEY=mock_secret'\n"
        "  echo 'AWS_SESSION_TOKEN=mock_session'\n"
        "  echo 'AWS_REGION=us-east-1'\n"
        "  echo 'OTHER_VAR=ignore_me'\n"
        "else\n"
        "  exit 1\n"
        "fi\n"
    )
    mock_bin.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env.get('PATH', '')}"

    script_path = Path("scripts/aws_vault_auth.sh").absolute()

    result = subprocess.run(
        [str(script_path), "dummy_profile"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(tmp_path),
    )

    assert result.returncode == 0
    assert "Successfully wrote credentials to tmp/.aws-credentials.env" in result.stdout

    # Read the output file
    output_file = tmp_path / "tmp" / ".aws-credentials.env"
    assert output_file.exists()
    content = output_file.read_text()

    assert "export AWS_ACCESS_KEY_ID='mock_key_id'" in content
    assert "export AWS_SECRET_ACCESS_KEY='mock_secret'" in content
    assert "export AWS_SESSION_TOKEN='mock_session'" in content

    # We should only export STS keys, not region or other vars
    assert "export AWS_REGION" not in content
    assert "OTHER_VAR" not in content


def test_aws_vault_auth_failure(tmp_path: Path) -> None:
    """Test that the script exits with an error message when aws-vault fails."""
    mock_bin = tmp_path / "aws-vault"
    mock_bin.write_text("#!/bin/bash\necho 'Enter token:' >&2\nexit 1\n")
    mock_bin.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env.get('PATH', '')}"

    script_path = Path("scripts/aws_vault_auth.sh").absolute()

    result = subprocess.run(
        [str(script_path), "dummy_profile"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Error: Failed to fetch credentials" in result.stderr
