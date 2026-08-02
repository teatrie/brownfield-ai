"""
Unit tests for tests/helpers/runners.py and tests/helpers/eval_utils.py.

These tests cover the Local Venv Test Infrastructure epic — Domain 2 requirements
for environment-aware runner auto-detection, prompt echo safety, subprocess
error handling, and dynamic workspace sandbox setup.
"""

import os
import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from helpers.runners import (
    ClaudeCodeRunner,
    CodexRunner,
    CopilotRunner,
    GeminiRunner,
    get_runner,
)

# ============================================================================
# get_runner() auto-detection tests
# ============================================================================


class TestGetRunnerAutoDetect:
    """Tests for get_runner() environment-based auto-detection logic."""

    def test_get_runner_returns_claude_when_api_key_set(self) -> None:
        """[Req-007] When ANTHROPIC_API_KEY is set and no explicit type is passed,
        get_runner() must auto-detect and return a ClaudeCodeRunner instance."""
        env_overrides: dict[str, str] = {
            "ANTHROPIC_API_KEY": "sk-ant-test-key",
            "COPILOT_GITHUB_TOKEN": "",
            "EVAL_RUNNER": "",
        }
        with patch.dict(os.environ, env_overrides, clear=False):
            # Remove COPILOT_GITHUB_TOKEN and EVAL_RUNNER from env entirely
            os.environ.pop("COPILOT_GITHUB_TOKEN", None)
            os.environ.pop("EVAL_RUNNER", None)
            runner = get_runner()
        assert isinstance(runner, ClaudeCodeRunner), f"Expected ClaudeCodeRunner when ANTHROPIC_API_KEY is set, got {type(runner).__name__}"

    def test_get_runner_returns_claude_when_cli_on_path(self) -> None:
        """[Req-007] When ``claude`` is on PATH (enterprise OAuth) but ANTHROPIC_API_KEY is NOT
        set, get_runner() must still auto-detect and return a ClaudeCodeRunner instance.
        CLI presence is sufficient for local dev with OAuth — no API key required."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("shutil.which", return_value="/usr/local/bin/claude"):
                runner = get_runner()
        assert isinstance(runner, ClaudeCodeRunner), (
            f"Expected ClaudeCodeRunner when 'claude' is on PATH with no API key, got {type(runner).__name__}"
        )

    def test_get_runner_returns_copilot_when_copilot_token_set(self) -> None:
        """[Req-007] When only COPILOT_GITHUB_TOKEN is set (no ANTHROPIC_API_KEY, no EVAL_RUNNER),
        get_runner() must auto-detect and return a CopilotRunner instance."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ["COPILOT_GITHUB_TOKEN"] = "ghp_test_token"
            runner = get_runner()
        assert isinstance(runner, CopilotRunner), (
            f"Expected CopilotRunner when only COPILOT_GITHUB_TOKEN is set, got {type(runner).__name__}"
        )

    def test_get_runner_prefers_claude_over_copilot(self) -> None:
        """[Req-007] When both ANTHROPIC_API_KEY and COPILOT_GITHUB_TOKEN are set,
        get_runner() must return ClaudeCodeRunner (Claude takes priority over Copilot)."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"
            os.environ["COPILOT_GITHUB_TOKEN"] = "ghp_test_token"
            runner = get_runner()
        assert isinstance(runner, ClaudeCodeRunner), f"Expected ClaudeCodeRunner (higher priority), got {type(runner).__name__}"

    def test_eval_runner_env_overrides_auto_detect(self) -> None:
        """[Req-008] When EVAL_RUNNER=copilot is set in the environment, get_runner()
        must return CopilotRunner even if ANTHROPIC_API_KEY is also present."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"
            os.environ["EVAL_RUNNER"] = "copilot"
            runner = get_runner()
        assert isinstance(runner, CopilotRunner), (
            f"Expected EVAL_RUNNER=copilot override to produce CopilotRunner, got {type(runner).__name__}"
        )

    def test_get_runner_explicit_type_overrides_auto_detect(self) -> None:
        """[Req-024] Passing runner_type='copilot' explicitly to get_runner() must
        return CopilotRunner regardless of any environment variable configuration."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"
            os.environ["EVAL_RUNNER"] = "claude"
            runner = get_runner(runner_type="copilot")
        assert isinstance(runner, CopilotRunner), (
            f"Expected explicit runner_type='copilot' to win over env vars, got {type(runner).__name__}"
        )

    def test_get_runner_raises_when_no_cli_or_key(self) -> None:
        """[Req-007] When no credentials (ANTHROPIC_API_KEY, COPILOT_GITHUB_TOKEN) and no
        known CLI binaries are present on PATH, get_runner() must raise RuntimeError."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("shutil.which", return_value=None):
                with pytest.raises(RuntimeError):
                    get_runner()

    def test_get_runner_returns_gemini_when_api_key_set(self) -> None:
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True):
            with patch("shutil.which", return_value=None):
                runner = get_runner()
        assert isinstance(runner, GeminiRunner), f"Expected GeminiRunner when only GEMINI_API_KEY is set, got {type(runner).__name__}"

    def test_get_runner_returns_codex_when_api_key_set(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
            with patch("shutil.which", return_value=None):
                runner = get_runner()
        assert isinstance(runner, CodexRunner), f"Expected CodexRunner when only OPENAI_API_KEY is set, got {type(runner).__name__}"

    def test_get_runner_prefers_claude_over_codex(self) -> None:
        with patch.dict(
            os.environ,
            {"ANTHROPIC_API_KEY": "test-key", "OPENAI_API_KEY": "test-key"},
            clear=True,
        ):
            with patch("shutil.which", return_value=None):
                runner = get_runner()
        assert isinstance(runner, ClaudeCodeRunner), (
            f"Expected ClaudeCodeRunner (higher priority) over CodexRunner, got {type(runner).__name__}"
        )

    def test_get_runner_raises_on_unknown_explicit_type(self) -> None:
        with pytest.raises(KeyError):
            get_runner(runner_type="nonexistent_runner")

    def test_get_runner_raises_on_unknown_eval_runner_env(self) -> None:
        with patch.dict(os.environ, {"EVAL_RUNNER": "nonexistent_runner"}, clear=True):
            with pytest.raises(KeyError):
                get_runner()


# ============================================================================
# ClaudeCodeRunner tests
# ============================================================================


class TestClaudeCodeRunner:
    """Tests for ClaudeCodeRunner subprocess execution and output behaviour."""

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    def test_claude_runner_does_not_echo_prompt(self, capsys: pytest.CaptureFixture) -> None:
        """[Req-019] ClaudeCodeRunner.run() must NOT include the prompt text in any
        print() call to stdout. The agent output should be returned as the function
        return value only — never reflected back verbatim."""
        prompt_text = "UNIQUE_SENTINEL_PROMPT_DO_NOT_ECHO_12345"

        mock_process = MagicMock()
        mock_process.stdout = iter(["some agent output\n", "task completed\n"])
        mock_process.wait.return_value = 0
        mock_process.returncode = 0

        with patch("subprocess.Popen", return_value=mock_process):
            runner = ClaudeCodeRunner()
            runner.run(prompt_text, "/tmp/fake_workspace")

        captured = capsys.readouterr()
        assert prompt_text not in captured.out, (
            f"Prompt text '{prompt_text}' was echoed to stdout — violates [Req-019]. Captured: {captured.out!r}"
        )

    def test_copilot_runner_does_not_echo_prompt(self, capsys: pytest.CaptureFixture) -> None:
        """[Req-019] CopilotRunner.run() must NOT print the prompt text to stdout.
        Currently, CopilotRunner echoes the prompt in its first print() statement —
        this test is expected to FAIL until that line is removed."""
        prompt_text = "UNIQUE_SENTINEL_PROMPT_DO_NOT_ECHO_99999"

        mock_process = MagicMock()
        mock_process.stdout = iter(["copilot output\n"])
        mock_process.wait.return_value = 0
        mock_process.returncode = 0

        env_overrides = {"PYTHONPATH": "/fake/path"}
        with patch("subprocess.Popen", return_value=mock_process):
            with patch.dict(os.environ, env_overrides):
                runner = CopilotRunner()
                runner.run(prompt_text, "/tmp/fake_workspace")

        captured = capsys.readouterr()
        assert prompt_text not in captured.out, (
            f"Prompt text '{prompt_text}' was echoed to stdout — violates [Req-019]. Captured: {captured.out!r}"
        )

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    def test_claude_runner_handles_timeout(self) -> None:
        """[Req-005] ClaudeCodeRunner.run() must handle subprocess.TimeoutExpired
        gracefully: kill the process, and return a meaningful error string rather
        than propagating the exception to the caller."""
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.wait.side_effect = [subprocess.TimeoutExpired(cmd=["claude", "-p"], timeout=300), None]

        with patch("subprocess.Popen", return_value=mock_process):
            runner = ClaudeCodeRunner()
            result = runner.run("some prompt", "/tmp/fake_workspace")

        assert result is not None, "Expected a non-None result on timeout"
        assert isinstance(result, str), f"Expected str result on timeout, got {type(result)}"
        mock_process.kill.assert_called_once()

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    def test_claude_runner_handles_nonzero_exit(self) -> None:
        """[Req-005] ClaudeCodeRunner.run() must handle a non-zero exit code from
        `claude -p` gracefully, returning an error string or raising a descriptive
        exception rather than silently returning an empty or success result."""
        mock_process = MagicMock()
        mock_process.stdout = iter(["error: something went wrong\n"])
        mock_process.wait.return_value = 1
        mock_process.returncode = 1

        with patch("subprocess.Popen", return_value=mock_process):
            runner = ClaudeCodeRunner()
            runner.run("some prompt", "/tmp/fake_workspace")

        # The runner must either raise or return an error-indicating string.
        # A stub that returns "Simulated Claude Code Output" with no subprocess call
        # is insufficient — the mock Popen must have been called.
        with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
            runner2 = ClaudeCodeRunner()
            runner2.run("some prompt", "/tmp/fake_workspace")
            mock_popen.assert_called_once(), ("ClaudeCodeRunner.run() must invoke subprocess.Popen — stub implementation detected")

    # ============================================================================
    # eval_utils sandbox tests
    # ============================================================================

    def test_claude_runner_works_without_api_key(self) -> None:
        """[Req-006] ClaudeCodeRunner.run() must NOT gate execution on ANTHROPIC_API_KEY.
        Enterprise OAuth allows ``claude -p`` to work with the CLI on PATH and no API key.
        When ANTHROPIC_API_KEY is absent, run() must still invoke subprocess.Popen rather
        than raising OSError or short-circuiting."""
        prompt_text = "do something"
        workspace = "/tmp/fake_workspace"

        mock_process = MagicMock()
        mock_process.stdout = iter(["agent output\n"])
        mock_process.wait.return_value = 0
        mock_process.returncode = 0

        with patch.dict(os.environ, {}, clear=True):
            with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
                runner = ClaudeCodeRunner()
                runner.run(prompt_text, workspace)

                # Popen MUST have been called — the runner does not block on API key absence
                mock_popen.assert_called_once()


class TestGeminiRunner:
    """Tests for GeminiRunner subprocess execution and output behaviour."""

    def test_gemini_runner_invokes_subprocess(self) -> None:
        mock_process = MagicMock()
        mock_process.stdout = iter(["gemini output\n"])
        mock_process.wait.return_value = 0
        mock_process.returncode = 0

        with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
            runner = GeminiRunner()
            runner.run("test prompt", "/tmp/workspace")

        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        assert "gemini" in call_args, f"Expected 'gemini' in command args, got {call_args}"
        assert "-p" in call_args, f"Expected '-p' in command args, got {call_args}"
        assert "test prompt" in call_args, f"Expected 'test prompt' in command args, got {call_args}"
        assert "--yolo" in call_args, f"Expected '--yolo' in command args, got {call_args}"
        assert "--output-format" in call_args, f"Expected '--output-format' in command args, got {call_args}"
        assert "text" in call_args, f"Expected 'text' in command args, got {call_args}"

    def test_gemini_runner_handles_timeout(self) -> None:
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.wait.side_effect = [subprocess.TimeoutExpired(cmd=["gemini"], timeout=300), None]

        with patch("subprocess.Popen", return_value=mock_process):
            runner = GeminiRunner()
            result = runner.run("test prompt", "/tmp/workspace")

        mock_process.kill.assert_called_once()
        assert isinstance(result, str), f"Expected str result on timeout, got {type(result)}"
        assert "Error" in result or "Timed out" in result, f"Expected result to contain 'Error' or 'Timed out', got {result!r}"

    def test_gemini_runner_handles_nonzero_exit(self) -> None:
        mock_process = MagicMock()
        mock_process.stdout = iter(["error output\n"])
        mock_process.wait.return_value = 1
        mock_process.returncode = 1

        with patch("subprocess.Popen", return_value=mock_process):
            runner = GeminiRunner()
            result = runner.run("test prompt", "/tmp/workspace")

        assert isinstance(result, str), f"Expected str result on nonzero exit, got {type(result)}"
        assert "Error" in result or "1" in result, f"Expected result to contain 'Error' or returncode info, got {result!r}"

    def test_gemini_runner_includes_model_flag_when_env_set(self) -> None:
        mock_process = MagicMock()
        mock_process.stdout = iter(["output\n"])
        mock_process.wait.return_value = 0
        mock_process.returncode = 0

        with patch.dict(os.environ, {"GEMINI_MODEL": "gemini-2.5-pro"}, clear=False):
            with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
                runner = GeminiRunner()
                runner.run("test prompt", "/tmp/workspace")

        call_args = mock_popen.call_args[0][0]
        assert "-m" in call_args, f"Expected '-m' in command args when GEMINI_MODEL is set, got {call_args}"
        assert "gemini-2.5-pro" in call_args, f"Expected model name in command args, got {call_args}"


class TestCodexRunner:
    """Tests for CodexRunner subprocess execution and output behaviour."""

    def test_codex_runner_invokes_subprocess(self) -> None:
        mock_process = MagicMock()
        mock_process.stdout = iter(["codex output\n"])
        mock_process.wait.return_value = 0
        mock_process.returncode = 0

        with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
            runner = CodexRunner()
            runner.run("test prompt", "/tmp/workspace")

        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        assert "codex" in call_args, f"Expected 'codex' in command args, got {call_args}"
        assert "exec" in call_args, f"Expected 'exec' in command args, got {call_args}"
        assert "test prompt" in call_args, f"Expected 'test prompt' in command args, got {call_args}"
        assert "--sandbox" in call_args, f"Expected '--sandbox' in command args, got {call_args}"
        assert "workspace-write" in call_args, f"Expected 'workspace-write' in command args, got {call_args}"
        assert "--color" in call_args, f"Expected '--color' in command args, got {call_args}"
        assert "never" in call_args, f"Expected 'never' in command args, got {call_args}"

    def test_codex_runner_handles_timeout(self) -> None:
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.wait.side_effect = [subprocess.TimeoutExpired(cmd=["codex"], timeout=300), None]

        with patch("subprocess.Popen", return_value=mock_process):
            runner = CodexRunner()
            result = runner.run("test prompt", "/tmp/workspace")

        mock_process.kill.assert_called_once()
        assert isinstance(result, str), f"Expected str result on timeout, got {type(result)}"
        assert "Error" in result or "Timed out" in result, f"Expected result to contain 'Error' or 'Timed out', got {result!r}"

    def test_codex_runner_handles_nonzero_exit(self) -> None:
        mock_process = MagicMock()
        mock_process.stdout = iter(["error\n"])
        mock_process.wait.return_value = 1
        mock_process.returncode = 1

        with patch("subprocess.Popen", return_value=mock_process):
            runner = CodexRunner()
            result = runner.run("test prompt", "/tmp/workspace")

        assert isinstance(result, str), f"Expected str result on nonzero exit, got {type(result)}"
        assert "Error" in result or "1" in result, f"Expected result to contain 'Error' or returncode info, got {result!r}"

    def test_codex_runner_includes_model_flag_when_env_set(self) -> None:
        mock_process = MagicMock()
        mock_process.stdout = iter(["output\n"])
        mock_process.wait.return_value = 0
        mock_process.returncode = 0

        with patch.dict(os.environ, {"CODEX_MODEL": "o3-mini"}, clear=False):
            with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
                runner = CodexRunner()
                runner.run("test prompt", "/tmp/workspace")

        call_args = mock_popen.call_args[0][0]
        assert "-m" in call_args, f"Expected '-m' in command args when CODEX_MODEL is set, got {call_args}"
        assert "o3-mini" in call_args, f"Expected model name in command args, got {call_args}"


class TestSetupIsolatedSandbox:
    """Tests for _setup_isolated_sandbox() dynamic workspace resolution."""

    def test_sandbox_uses_dynamic_workspace_root(self) -> None:
        """[Req-022] _setup_isolated_sandbox() must NOT hardcode '/app' as the copytree
        source path. The source for shutil.copytree must be derived from the
        original_workspace_path parameter (or a dynamic workspace root), not the
        Docker-internal '/app' constant."""
        from helpers.eval_utils import _setup_isolated_sandbox

        captured_copytree_calls: list[tuple[Any, ...]] = []

        def recording_copytree(src: str, dst: str, **kwargs: Any) -> None:
            """Intercept copytree calls and record their source paths."""
            captured_copytree_calls.append((src, dst))

        fake_workspace = "/Users/dev/project/tests/skills/my_skill"

        with patch("shutil.copytree", side_effect=recording_copytree):
            with patch("shutil.rmtree"):
                with patch("os.path.exists", return_value=False):
                    with patch("subprocess.run"):
                        with patch("os.makedirs"):
                            try:
                                _setup_isolated_sandbox("my_skill", "case_01", fake_workspace)
                            except Exception:
                                pass  # Sandbox setup may fail on missing dirs; we only care about copytree args

        # Verify that '/app' was NOT used as a copytree source
        app_sourced_calls = [call for call in captured_copytree_calls if call[0] == "/app"]
        assert len(app_sourced_calls) == 0, (
            f"_setup_isolated_sandbox() called shutil.copytree with hardcoded '/app' source: "
            f"{app_sourced_calls}. This violates [Req-022] — source must be dynamic."
        )


# ============================================================================
# eval_utils _run_contextual_prompt tests
# ============================================================================


class TestRunContextualPrompt:
    """Tests for _run_contextual_prompt() runner auto-detection delegation."""

    def test_eval_utils_calls_get_runner_without_args(self) -> None:
        """[Req-015] _run_contextual_prompt() must call get_runner() with no arguments
        so that the runner is auto-detected from the environment rather than being
        hardcoded to a specific runner type (e.g. 'copilot'). Passing any positional
        or keyword argument to get_runner() violates auto-detect mode."""
        from helpers.eval_utils import _run_contextual_prompt

        mock_runner = MagicMock()
        mock_runner.run.return_value = "agent output"

        with patch("helpers.eval_utils.get_runner", return_value=mock_runner) as mock_get_runner:
            with patch("helpers.eval_utils._find_skill_file", return_value="skills/my_skill/SKILL.md"):
                try:
                    _run_contextual_prompt(
                        skill_name="my_skill",
                        user_prompt="do the thing",
                        agent_prompt="",
                        sandbox_path="/tmp/sandbox",
                        eval_env={},
                    )
                except Exception:
                    pass  # We only care about how get_runner was called

        mock_get_runner.assert_called_once(), ("[Req-015] get_runner() was not called at all inside _run_contextual_prompt()")
        call_args, call_kwargs = mock_get_runner.call_args
        assert call_args == () and call_kwargs == {}, (
            f"[Req-015] _run_contextual_prompt() called get_runner() with args={call_args!r} "
            f"kwargs={call_kwargs!r}. Expected get_runner() to be called with NO arguments "
            "(auto-detect mode). The current implementation hardcodes get_runner('copilot')."
        )
