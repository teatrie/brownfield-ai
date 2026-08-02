"""Tests for scripts/agent-cli/cli-args-to-env.sh.

The shim takes a target script path as its first positional argument
and validates each remaining ``KEY=value`` token supplied via Taskfile
``{{.CLI_ARGS}}`` against two regexes:

- ``ALLOWED_KEYS_REGEX`` — a finite allowlist of keys a review task may
  receive from the caller (ROUND, EFFORT, REVIEW_SESSION_ID, WORKSPACE,
  REVIEW_TYPE, GEMINI_MODEL, GEMINI_TIMEOUT, MODEL, DIFF_FILE,
  REVIEW_MODE). The
  legacy keys ``REVIEW_PROMPT_FILE``, ``PROMPT_FILE``, and
  ``REVIEW_DIFF_FILE`` were removed in TODO-0092 Phase A — callers now
  pass ``REVIEW_TYPE`` (template enum) + ``DIFF_FILE`` (subject path)
  and the wrapper loads the committed template from a hardcoded path.
- ``VALUE_REGEX`` — ``[A-Za-z0-9._/:@+=-]*``. Rejects any value
  containing whitespace, shell metacharacters, or expansion tokens.

There is no ``--`` separator — any non-``KEY=value`` token (including
a stray ``--`` or a flag-like ``-u``) is rejected by the format check.
Dropping ``--`` closes the smuggling path where a caller-supplied
``--`` inside ``{{.CLI_ARGS}}`` could prematurely terminate the
key-parse loop and promote remaining tokens into caller-controlled
argv that ``exec env`` would run as a command.

On success the shim ``exec env``s the supplied ``KEY=value`` entries
into the target script's environment, overriding same-named inherited
values. On validation failure the shim exits 2 with a diagnostic on
stderr.

These tests invoke the shim directly via ``bash`` with ``env`` as the
target script path and inspect the target's stdout to verify which
keys propagated.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[2]
SHIM = str(WORKSPACE / "scripts" / "agent-cli" / "cli-args-to-env.sh")

ALLOWED_KEYS: tuple[str, ...] = (
    "ROUND",
    "EFFORT",
    "REVIEW_SESSION_ID",
    "WORKSPACE",
    "REVIEW_TYPE",
    "GEMINI_MODEL",
    "GEMINI_TIMEOUT",
    "MODEL",
    "DIFF_FILE",
    "REVIEW_MODE",
)

# Keys removed by TODO-0092 Phase A — explicitly asserted rejected below.
REMOVED_KEYS: tuple[str, ...] = (
    "REVIEW_PROMPT_FILE",
    "PROMPT_FILE",
    "REVIEW_DIFF_FILE",
)


def _run_shim(
    target: str,
    *kv_tokens: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the shim with a target script path and KEY=value tokens.

    The shim takes the target as its first positional argument and the
    caller's ``KEY=value`` tokens as the remaining arguments — there is
    no ``--`` separator. Returns the ``CompletedProcess`` whose
    ``stdout`` contains the target command's output (typically
    ``env``'s ``KEY=VALUE`` listing when the shim succeeds).
    """
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", SHIM, target, *kv_tokens],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


def _stdout_has_env(stdout: str, key: str, value: str) -> bool:
    """Return True if ``KEY=value`` appears on its own line in stdout."""
    return any(line == f"{key}={value}" for line in stdout.splitlines())


# ---------------------------------------------------------------------------
# Valid injection
# ---------------------------------------------------------------------------


class TestValidInjection:
    """Every allowlisted key must successfully inject into the child env."""

    @pytest.mark.parametrize("key", ALLOWED_KEYS)
    def test_allowlisted_key_propagates(self, key: str) -> None:
        """Each allowlisted key with a benign value is injected into the child."""
        value = "v1"
        result = _run_shim("env", f"{key}={value}")
        assert result.returncode == 0, f"Shim failed for key {key}: stderr={result.stderr!r}"
        assert _stdout_has_env(result.stdout, key, value), f"Key {key}={value} did not appear in child env. stdout:\n{result.stdout}"

    @pytest.mark.parametrize(
        "key,value",
        [
            ("ROUND", "3"),
            ("EFFORT", "high"),
            ("REVIEW_SESSION_ID", "abc123"),
            ("WORKSPACE", "brownfield-ai"),
            ("REVIEW_TYPE", "diff"),
            ("GEMINI_MODEL", "gemini-3.1-pro"),
            ("GEMINI_TIMEOUT", "300"),
            ("MODEL", "o3-mini"),
            ("DIFF_FILE", "tmp/diff.patch"),
        ],
    )
    def test_realistic_values_propagate(self, key: str, value: str) -> None:
        """Realistic caller-supplied values propagate verbatim."""
        result = _run_shim("env", f"{key}={value}")
        assert result.returncode == 0, f"Shim failed: stderr={result.stderr!r}"
        assert _stdout_has_env(result.stdout, key, value)

    @pytest.mark.parametrize("removed_key", REMOVED_KEYS)
    def test_removed_legacy_keys_rejected(self, removed_key: str) -> None:
        """Keys deprecated in TODO-0092 Phase A are rejected by the allowlist."""
        result = _run_shim("env", f"{removed_key}=tmp/any.txt")
        assert result.returncode == 2, f"Legacy key {removed_key!r} should be rejected, got {result.returncode}"
        assert "not allowlisted" in result.stderr


# ---------------------------------------------------------------------------
# Invalid keys
# ---------------------------------------------------------------------------


class TestInvalidKey:
    """Keys outside the allowlist must be rejected."""

    @pytest.mark.parametrize(
        "token",
        [
            "FOO=bar",
            "PATH=/evil",
            "round=3",
            "Round=3",
            "HOME=/etc",
            "LD_PRELOAD=x.so",
            "OPENAI_API_KEY=leaked",
        ],
    )
    def test_invalid_key_rejected(self, token: str) -> None:
        """Non-allowlisted keys exit 2 with an error token in stderr."""
        result = _run_shim("env", token)
        assert result.returncode == 2, f"Unexpectedly accepted: {token!r}"
        assert "not allowlisted" in result.stderr


# ---------------------------------------------------------------------------
# Invalid value characters
# ---------------------------------------------------------------------------


class TestInvalidValueChars:
    """Values containing disallowed characters must be rejected."""

    @pytest.mark.parametrize(
        "value",
        [
            "has space",
            "with$dollar",
            "semi;colon",
            "back`tick`",
            "pipe|char",
            "amper&sand",
            "gt>redirect",
            "lt<redirect",
            "new\nline",
            "quote'here",
            'quote"here',
            "paren(open",
            "star*glob",
            "brace{open",
        ],
    )
    def test_invalid_value_rejected(self, value: str) -> None:
        """Values containing disallowed metacharacters exit 2."""
        result = _run_shim("env", f"ROUND={value}")
        assert result.returncode == 2, f"Unexpectedly accepted: ROUND={value!r}"
        assert "disallowed characters" in result.stderr


# ---------------------------------------------------------------------------
# Malformed tokens
# ---------------------------------------------------------------------------


class TestMalformedTokens:
    """Tokens missing ``=`` or key/value must be rejected."""

    def test_token_without_equals_rejected(self) -> None:
        """A token with no ``=`` fails the format check."""
        result = _run_shim("env", "ROUND")
        assert result.returncode == 2
        assert "expected KEY=value" in result.stderr

    def test_empty_key_rejected(self) -> None:
        """A token starting with ``=`` has an empty key and is rejected."""
        result = _run_shim("env", "=value")
        assert result.returncode == 2
        assert "not allowlisted" in result.stderr

    def test_empty_string_token_rejected(self) -> None:
        """An empty-string token fails the ``*=*`` format check."""
        result = _run_shim("env", "")
        assert result.returncode == 2
        assert "expected KEY=value" in result.stderr


# ---------------------------------------------------------------------------
# Stray `--` and flag-like tokens
# ---------------------------------------------------------------------------


class TestStraySeparatorRejected:
    """A stray ``--`` token must be rejected.

    The shim has no ``--`` separator under the target-first signature.
    A caller that embeds ``--`` inside ``{{.CLI_ARGS}}`` (intentionally
    or by accident) must not trigger any special behavior — the shim
    treats ``--`` as a token that fails the ``KEY=value`` format check
    and exits 2. This closes the smuggling path where ``--`` could
    prematurely terminate the key-parse loop under the previous
    signature and promote remaining tokens into caller-controlled argv.
    """

    def test_bare_double_dash_rejected(self) -> None:
        """A lone ``--`` is not KEY=value form → exit 2."""
        result = _run_shim("env", "--")
        assert result.returncode == 2
        assert "expected KEY=value" in result.stderr

    def test_double_dash_between_tokens_rejected(self) -> None:
        """A ``--`` interspersed with valid tokens is rejected."""
        result = _run_shim("env", "ROUND=3", "--", "EFFORT=high")
        assert result.returncode == 2
        assert "expected KEY=value" in result.stderr


class TestFlagLikeTokenRejected:
    """Flag-like tokens (``-u``, ``--env``, ``-i``) must be rejected.

    These tokens do not contain ``=`` and therefore fail the format
    check before the key-allowlist or value-charset checks are applied.
    This prevents a caller from smuggling ``env`` flags — which could
    alter the target's environment interpretation — through
    ``{{.CLI_ARGS}}``.
    """

    @pytest.mark.parametrize("token", ["-u", "--env", "-i", "-v"])
    def test_flag_like_token_rejected(self, token: str) -> None:
        """A flag-like token that is not KEY=value exits 2."""
        result = _run_shim("env", token)
        assert result.returncode == 2
        assert "expected KEY=value" in result.stderr


# ---------------------------------------------------------------------------
# Zero KEY=value tokens
# ---------------------------------------------------------------------------


class TestZeroTokensJustTarget:
    """With no KEY=value tokens, the shim should exec the target directly."""

    def test_zero_tokens_just_target_runs_cleanly(self) -> None:
        """Invoking the shim with only a target and no tokens succeeds.

        The empty-array expansion ``${env_args[@]+"${env_args[@]}"}``
        must not tickle the bash 3.2 ``set -u`` unbound-variable error.
        """
        result = _run_shim("env")
        assert result.returncode == 0, f"Shim failed with zero tokens: stderr={result.stderr!r}"


# ---------------------------------------------------------------------------
# Multiple keys
# ---------------------------------------------------------------------------


class TestMultipleKeysAllPropagate:
    """Multiple allowlisted tokens must all reach the child env."""

    def test_three_keys_propagate(self) -> None:
        """ROUND, EFFORT and GEMINI_MODEL together propagate intact."""
        result = _run_shim(
            "env",
            "ROUND=1",
            "EFFORT=high",
            "GEMINI_MODEL=gemini-3.1-pro",
        )
        assert result.returncode == 0, f"Shim failed: stderr={result.stderr!r}"
        assert _stdout_has_env(result.stdout, "ROUND", "1")
        assert _stdout_has_env(result.stdout, "EFFORT", "high")
        assert _stdout_has_env(result.stdout, "GEMINI_MODEL", "gemini-3.1-pro")

    def test_all_allowlisted_keys_in_one_call(self) -> None:
        """Every allowlisted key may be passed in a single invocation."""
        tokens = [f"{k}=v{i}" for i, k in enumerate(ALLOWED_KEYS)]
        result = _run_shim("env", *tokens)
        assert result.returncode == 0, f"Shim failed: stderr={result.stderr!r}"
        for i, key in enumerate(ALLOWED_KEYS):
            assert _stdout_has_env(result.stdout, key, f"v{i}"), f"Key {key} missing from child env. stdout:\n{result.stdout}"


# ---------------------------------------------------------------------------
# Override inherited env
# ---------------------------------------------------------------------------


class TestOverrideInheritedEnv:
    """Shim values must override same-named inherited env vars."""

    def test_shim_value_overrides_inherited(self) -> None:
        """``ROUND=3`` via shim wins over pre-existing ``ROUND=9``."""
        result = _run_shim(
            "env",
            "ROUND=3",
            extra_env={"ROUND": "9"},
        )
        assert result.returncode == 0, f"Shim failed: stderr={result.stderr!r}"
        assert _stdout_has_env(result.stdout, "ROUND", "3")
        assert not _stdout_has_env(result.stdout, "ROUND", "9")
