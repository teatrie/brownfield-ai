"""Ralph --- headless epic runner for automated plan execution.

Deterministic script that queries the execution ledger, constructs prompts
from Jinja2 templates, spawns ``claude -p`` sessions, and interprets
structured ``session_exit`` artifacts.

This module is the CLI entrypoint. It imports core logic from the
``brownfield_ai.tools.ralph`` package and exposes a ``defopt``-based CLI.
"""

import json
import logging
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import defopt

from brownfield_ai.tools.ralph.client import (
    get_latest_session_exit,
    ledger_filter,
    ledger_resume,
    ledger_set_prs,
    ledger_status,
    ledger_touch,
    parse_branches,
    parse_json_output,
    parse_sub_plans,
)
from brownfield_ai.tools.ralph.config import bump_floor, default_floor, get_config
from brownfield_ai.tools.ralph.git import ensure_all_branches, push_all_branches
from brownfield_ai.tools.ralph.pr import (
    close_pr,
    collect_ci_failures,
    create_all_prs,
    detect_modified_repos,
    poll_all_ci,
    pr_url_to_ref,
)
from brownfield_ai.tools.ralph.prompt import render_ci_fix_prompt, render_session_prompt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_ATTEMPTS: int = 3
"""Maximum retry attempts per sub-plan."""

_AWS_CREDS_PATH: str = "tmp/.aws-credentials.env"
"""Path to short-lived STS credentials exported by aws-vault-auth."""

_MAX_CI_FIX_ATTEMPTS: int = 3
"""Maximum CI fix retry attempts."""

_CI_POLL_INTERVAL: int = 60
"""Seconds between CI polling iterations."""

_CI_POLL_TIMEOUT: int = 1800
"""Maximum seconds to poll CI before timing out."""


# ---------------------------------------------------------------------------
# Session execution
# ---------------------------------------------------------------------------


def _load_aws_credentials() -> dict[str, str]:
    """Load AWS credentials from the credentials env file if it exists.

    Parses ``KEY=VALUE`` lines from the file at :data:`_AWS_CREDS_PATH`.

    Returns:
        Dict of environment variable key-value pairs, empty if file
        does not exist.
    """
    creds_file = Path(_AWS_CREDS_PATH)
    if not creds_file.exists():
        return {}
    env_vars: dict[str, str] = {}
    for line in creds_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            env_vars[key.strip()] = value.strip()
    return env_vars


_RATE_LIMIT_SIGNALS = ("rate limit", "rate_limit", "429", "too many requests", "overloaded")
"""Substrings in stderr that indicate a rate-limit exit."""

_RATE_LIMIT_PROBE_INTERVAL: int = 300
"""Seconds between rate-limit probe pings (5 minutes)."""


def _is_rate_limited(stderr: str) -> bool:
    """Check if stderr output indicates a rate-limit error."""
    lower = stderr.lower()
    return any(sig in lower for sig in _RATE_LIMIT_SIGNALS)


def _wait_for_rate_limit_clear(env: dict[str, str]) -> None:
    """Poll with ping probes until the rate limit lifts.

    Sends ``claude -p "ping"`` every 5 minutes. Returns as soon as
    a probe succeeds (exit 0) within 30 seconds, indicating the
    rate limit has cleared.

    Args:
        env: Environment variables (merged with os.environ).
    """
    merged = {**os.environ, **env}
    attempt = 0
    while True:
        attempt += 1
        logger.info(
            "Rate-limit gate: probe attempt %d (every %ds)...",
            attempt,
            _RATE_LIMIT_PROBE_INTERVAL,
        )
        start = time.monotonic()
        try:
            result = subprocess.run(
                ["claude", "-p", "ping"],
                env=merged,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Rate-limit probe timed out (60s). Still rate-limited.")
            time.sleep(_RATE_LIMIT_PROBE_INTERVAL)
            continue

        elapsed = time.monotonic() - start
        if result.returncode == 0 and elapsed < 30:
            logger.info(
                "Rate-limit cleared. Probe succeeded in %.1fs.",
                elapsed,
            )
            return

        if _is_rate_limited(result.stderr):
            logger.warning(
                "Rate-limit probe still blocked (%.1fs, stderr: %s). Waiting %ds.",
                elapsed,
                result.stderr[:200].strip(),
                _RATE_LIMIT_PROBE_INTERVAL,
            )
        else:
            logger.info(
                "Probe returned in %.1fs (exit %d). Proceeding.",
                elapsed,
                result.returncode,
            )
            return

        time.sleep(_RATE_LIMIT_PROBE_INTERVAL)


_EXIT_CODE_RATE_LIMIT: int = 2
"""Special return code indicating the session exited due to rate limiting."""


def run_claude_session(
    prompt: str,
    *,
    env: dict[str, str],
    timeout: int,
) -> int:
    """Spawn a ``claude -p`` headless session.

    Captures stderr to detect rate-limit exits. Returns
    ``_EXIT_CODE_RATE_LIMIT`` (2) when rate limiting caused the failure,
    allowing the caller to enter the rate-limit gate loop before retrying.

    Args:
        prompt: The full prompt string to pass to ``claude -p``.
        env: Additional environment variables for the subprocess.
        timeout: Maximum session duration in seconds.

    Returns:
        The process exit code. ``2`` signals rate-limit failure.
    """
    merged_env = {**os.environ, **env}
    prompt_file = Path("tmp/ralph_session_prompt.md")
    prompt_file.write_text(prompt, encoding="utf-8")
    logger.info("Prompt written to %s (%d bytes).", prompt_file, prompt_file.stat().st_size)
    stderr_file = Path("tmp/ralph_session_stderr.log")
    with (
        open(prompt_file, encoding="utf-8") as fh,
        open(stderr_file, "w", encoding="utf-8") as err_fh,
    ):
        process = subprocess.Popen(
            ["claude", "-p"],
            stdin=fh,
            stderr=err_fh,
            env=merged_env,
        )
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning("Session timed out after %d seconds.", timeout)
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            return 1

    exit_code = process.returncode
    if exit_code != 0:
        stderr_text = stderr_file.read_text(encoding="utf-8")
        if _is_rate_limited(stderr_text):
            logger.warning(
                "Session exited with rate-limit error (code %d): %s",
                exit_code,
                stderr_text[:300].strip(),
            )
            return _EXIT_CODE_RATE_LIMIT
        if stderr_text.strip():
            logger.warning("Session stderr (code %d): %s", exit_code, stderr_text[:500].strip())
    return exit_code


# ---------------------------------------------------------------------------
# Artifact queries
# ---------------------------------------------------------------------------


def get_failures(
    epic_id: str,
    sub_plan: dict[str, Any],
    prior_attempt: int,
) -> list[dict[str, Any]]:
    """Get failure artifacts from the prior attempt.

    Queries the ledger for ``session_exit`` artifacts matching the
    sub-plan label and prior attempt number, then extracts failure
    details.

    Args:
        epic_id: The epic identifier.
        sub_plan: Sub-plan dict with ``"label"`` and ``"waves"`` keys.
        prior_attempt: The attempt number whose failures to retrieve.

    Returns:
        List of failure dicts with keys ``wave``, ``step``,
        ``agent_model``, ``effort_variant``, ``body``, and
        ``exhausted_matrix_points``. Returns at most one element
        (the session_exit artifact for the prior attempt). The full
        session failure detail is in the artifact body, not split
        per-wave.
    """
    exit_artifact = get_latest_session_exit(
        epic_id,
        sub_plan["label"],
        prior_attempt,
    )
    if exit_artifact is None:
        return []

    metadata = exit_artifact.get("metadata", {})
    if metadata.get("verdict") != "fail":
        return []

    body = exit_artifact.get("document", "")
    return [
        {
            "wave": metadata.get("wave", "unknown"),
            "step": metadata.get("step", "unknown"),
            "agent_model": metadata.get("agent_model", "unknown"),
            "effort_variant": metadata.get("effort_variant", "base"),
            "body": body,
            "exhausted_matrix_points": metadata.get("exhausted_matrix_points", "none"),
        }
    ]


def _get_completed_waves_from_git() -> list[str]:
    """Detect completed waves by scanning git commit messages on HEAD.

    Looks for commit messages containing ``Wave N`` (case-insensitive)
    in commits ahead of ``main``. This is reliable because the session
    prompt template and agent-team skill include the wave number in
    commit messages.

    Returns:
        List of wave ID strings found in commit messages.
    """
    import re

    try:
        result = subprocess.run(
            ["git", "log", "main..HEAD", "--oneline"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        logger.warning("Could not read git log for wave detection.")
        return []
    waves: list[str] = []
    for line in result.stdout.strip().splitlines():
        matches = re.findall(r"[Ww]ave\s+(\w+)", line)
        for w in matches:
            if w not in waves:
                waves.append(w)
    return waves


def get_completed_waves(epic_id: str) -> list[str]:
    """Get list of wave IDs with passing wave_summaries.

    Queries the ledger for ``wave_summary`` artifacts and returns the
    wave IDs of those with a ``"pass"`` verdict.

    Args:
        epic_id: The epic identifier.

    Returns:
        List of completed wave ID strings.
    """
    artifacts = ledger_filter(epic_id, artifact_type="wave_summary")
    completed: list[str] = []
    for artifact in artifacts:
        metadata = artifact.get("metadata", {})
        if metadata.get("verdict", "").lower() in ("pass", "success", "green"):
            wave_id = metadata.get("wave", "")
            if wave_id and wave_id not in completed:
                completed.append(wave_id)
    return completed


# ---------------------------------------------------------------------------
# Sub-plan execution
# ---------------------------------------------------------------------------


def run_sub_plan(
    epic_id: str,
    sub_plan: dict[str, Any],
    resume: dict[str, Any],
) -> tuple[str, int]:
    """Execute a single sub-plan with up to 3 retry attempts.

    Implements the retry loop: on each attempt, renders a prompt with
    escalated model/effort floor, spawns a ``claude -p`` session, then
    reads the ``session_exit`` artifact to determine the verdict.

    Args:
        epic_id: The epic identifier.
        sub_plan: Sub-plan dict with ``"label"`` and ``"waves"`` keys.
        resume: The full resume context from the ledger.

    Returns:
        Tuple of ``(result_status, attempts_used)`` where result_status
        is ``"pass"``, ``"fail"``, or ``"blocked"``.
    """
    config = get_config()
    aws_creds = _load_aws_credentials()
    consecutive_missing: int = 0
    next_escalation_floor: str = ""
    attempt: int = 0

    while attempt < _MAX_ATTEMPTS:
        attempt += 1
        logger.info(
            "Running sub-plan '%s' attempt %d/%d for epic %s.",
            sub_plan["label"],
            attempt,
            _MAX_ATTEMPTS,
            epic_id,
        )

        # Refresh heartbeat before each attempt
        ledger_touch(epic_id)

        # Gather context for prompt rendering
        completed_waves = get_completed_waves(epic_id)
        failures: list[dict[str, Any]] = []
        escalation_floor = default_floor(sub_plan)

        if attempt > 1:
            failures = get_failures(epic_id, sub_plan, attempt - 1)
            if next_escalation_floor:
                escalation_floor = next_escalation_floor
            else:
                escalation_floor = bump_floor(attempt)

        resume_json = json.dumps(resume, indent=2)
        prompt = render_session_prompt(
            epic_id,
            sub_plan,
            attempt,
            branches=parse_branches(resume.get("plan_snapshot", {}).get("metadata", {}).get("branches", "")),
            resume_json=resume_json,
            completed_waves=completed_waves,
            failures=failures,
            escalation_floor=escalation_floor,
        )

        session_env = {
            "CI": "true",
            **aws_creds,
        }
        exit_code = run_claude_session(
            prompt,
            env=session_env,
            timeout=config["session_timeout"],
        )
        logger.info(
            "Session for sub-plan '%s' attempt %d exited with code %d.",
            sub_plan["label"],
            attempt,
            exit_code,
        )

        # Rate-limit gate: if session died from rate limiting, wait
        # for it to clear and retry WITHOUT consuming an attempt.
        if exit_code == _EXIT_CODE_RATE_LIMIT:
            logger.warning(
                "Sub-plan '%s' attempt %d hit rate limit. Entering rate-limit gate loop.",
                sub_plan["label"],
                attempt,
            )
            _wait_for_rate_limit_clear(session_env)
            attempt -= 1  # don't consume this attempt
            continue

        # Read the session_exit artifact to determine verdict
        exit_artifact = get_latest_session_exit(
            epic_id,
            sub_plan["label"],
            attempt,
        )

        if exit_artifact is None:
            consecutive_missing += 1
            logger.warning(
                "No session_exit artifact found for sub-plan '%s' attempt %d. Consecutive missing: %d.",
                sub_plan["label"],
                attempt,
                consecutive_missing,
            )
            if consecutive_missing >= 2:
                logger.error(
                    "Two consecutive missing exit artifacts for sub-plan '%s'. Transitioning to blocked.",
                    sub_plan["label"],
                )
                return ("blocked", attempt)
            if attempt == _MAX_ATTEMPTS:
                return ("fail", attempt)
            continue

        consecutive_missing = 0
        verdict = exit_artifact.get("metadata", {}).get("verdict", "fail")
        if verdict in ("pass", "success"):
            logger.info(
                "Sub-plan '%s' passed on attempt %d.",
                sub_plan["label"],
                attempt,
            )
            return ("pass", attempt)
        if verdict == "blocked":
            logger.warning(
                "Sub-plan '%s' reported blocked on attempt %d.",
                sub_plan["label"],
                attempt,
            )
            return ("blocked", attempt)

        # verdict is "fail", "retry", or unknown --- retry if attempts remain
        next_escalation_floor = exit_artifact.get("metadata", {}).get("recommended_floor", "")
        if attempt == _MAX_ATTEMPTS:
            logger.error(
                "Sub-plan '%s' exhausted all %d attempts.",
                sub_plan["label"],
                _MAX_ATTEMPTS,
            )
            return ("fail", attempt)

    return ("fail", _MAX_ATTEMPTS)


# ---------------------------------------------------------------------------
# Epic execution
# ---------------------------------------------------------------------------


def run_epic(epic_id: str) -> str:
    """Execute all sub-plans for an epic. Returns final status.

    Implements the core loop: load resume context, parse sub-plans,
    ensure branches, execute each sub-plan sequentially, push branches,
    create PRs, and monitor CI.

    Args:
        epic_id: The epic identifier.

    Returns:
        Final epic status string (``"completed"`` or ``"blocked"``).
    """
    logger.info("Starting epic execution for %s.", epic_id)
    config = get_config()

    with EpicHeartbeat(epic_id, config["heartbeat_interval"]):
        resume = ledger_resume(epic_id)
        plan_snapshot = resume.get("plan_snapshot")
        if plan_snapshot is None:
            logger.error("No plan_snapshot found for epic %s.", epic_id)
            ledger_status(epic_id, "blocked")
            return "blocked"

        sub_plans = parse_sub_plans(plan_snapshot)
        if not sub_plans:
            logger.error("No sub-plans found in plan_snapshot for epic %s.", epic_id)
            ledger_status(epic_id, "blocked")
            return "blocked"

        branches = parse_branches(plan_snapshot.get("metadata", {}).get("branches", ""))

        # Ensure all repo branches are checked out
        try:
            ensure_all_branches(branches)
        except (FileNotFoundError, RuntimeError):
            logger.exception("Branch setup failed for epic %s.", epic_id)
            ledger_status(epic_id, "blocked")
            return "blocked"

        # Detect completed waves: prefer ledger, fall back to git
        ledger_waves = get_completed_waves(epic_id)
        git_waves = _get_completed_waves_from_git()
        if ledger_waves:
            completed_waves = ledger_waves
            logger.info("Completed waves from ledger: %s", ledger_waves)
        else:
            completed_waves = git_waves
            logger.info("Completed waves from git (ledger empty): %s", git_waves)
        # Shadow-mode telemetry: log mismatch for validation, does not alter the decision above
        if ledger_waves and git_waves and set(ledger_waves) != set(git_waves):
            logger.warning(
                "Wave detection mismatch: ledger=%s git=%s",
                ledger_waves,
                git_waves,
            )

        # Execute each sub-plan sequentially, skipping already-completed ones
        for sub_plan in sub_plans:
            sub_plan_waves = sub_plan.get("waves", [])
            if sub_plan_waves and all(w in completed_waves for w in sub_plan_waves):
                logger.info(
                    "Sub-plan '%s' waves %s already completed. Skipping.",
                    sub_plan["label"],
                    sub_plan_waves,
                )
                continue
            result_status, attempts_used = run_sub_plan(epic_id, sub_plan, resume)
            logger.info(
                "Sub-plan '%s' finished with status '%s' after %d attempts.",
                sub_plan["label"],
                result_status,
                attempts_used,
            )

            if result_status == "blocked":
                ledger_status(epic_id, "blocked")
                return "blocked"
            if result_status == "fail":
                ledger_status(epic_id, "blocked")
                return "blocked"

            # Refresh resume context for the next sub-plan
            resume = ledger_resume(epic_id)

        # All sub-plans passed --- refresh claim and attempt push
        ledger_touch(epic_id)
        push_success = push_all_branches(branches)
        if not push_success:
            logger.warning(
                "Push failed for epic %s (remote may be unreachable). "
                "Skipping PR creation --- PR artifacts should be in tmp/pr-artifacts/.",
                epic_id,
            )
            ledger_status(epic_id, "blocked")
            return "blocked"

        modified = detect_modified_repos(branches)
        if not modified:
            logger.info("No modified repos for epic %s. Skipping PR creation.", epic_id)
            ledger_status(epic_id, "completed")
            return "completed"

        modified_branches = {r: b for r, b in branches.items() if r in modified}
        try:
            pr_urls = create_and_set_prs(epic_id, modified_branches, resume)
        except (RuntimeError, ValueError):
            logger.exception("PR creation failed for epic %s.", epic_id)
            ledger_status(epic_id, "blocked")
            return "blocked"
        if not pr_urls:
            ledger_status(epic_id, "blocked")
            return "blocked"

        ledger_status(epic_id, "in_review")
        ci_result = monitor_and_fix_ci(epic_id, pr_urls, branches)
        if ci_result == "all_green":
            ledger_status(epic_id, "completed")
            logger.info("Epic %s CI passed. Status: completed.", epic_id)
            return "completed"
        ledger_status(epic_id, "blocked")
        logger.info("Epic %s CI failed. Status: blocked.", epic_id)
        return "blocked"


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


class EpicHeartbeat:
    """Background heartbeat that periodically touches an epic's claim.

    Designed as a context manager for use with ``with`` statements.
    Spawns a daemon thread that calls ``ledger_touch(epic_id)`` at
    regular intervals until stopped.

    Args:
        epic_id: The epic identifier to keep alive.
        interval: Seconds between heartbeat ticks.
    """

    def __init__(self, epic_id: str, interval: float) -> None:
        self._epic_id = epic_id
        self._interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "EpicHeartbeat":
        """Start the heartbeat daemon thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"heartbeat-{self._epic_id}",
            daemon=True,
        )
        self._thread.start()
        logger.debug(
            "Heartbeat started for epic %s (interval=%ds).",
            self._epic_id,
            self._interval,
        )
        return self

    def __exit__(self, *exc: object) -> None:
        """Stop the heartbeat daemon thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        logger.debug("Heartbeat stopped for epic %s.", self._epic_id)

    def _run(self) -> None:
        """Loop body executed by the daemon thread."""
        while not self._stop_event.wait(timeout=self._interval):
            try:
                ledger_touch(self._epic_id)
                logger.debug("Heartbeat tick for epic %s.", self._epic_id)
            except Exception:
                logger.warning(
                    "Heartbeat tick failed for epic %s.",
                    self._epic_id,
                    exc_info=True,
                )


# ---------------------------------------------------------------------------
# PR creation and CI monitoring
# ---------------------------------------------------------------------------


def create_and_set_prs(
    epic_id: str,
    branches: dict[str, str],
    resume: dict[str, Any],
) -> dict[str, str]:
    """Create PRs for all modified repos and register refs in ledger.

    All-or-nothing: if any PR creation fails, previously created PRs
    are closed. If ledger_set_prs fails after PRs are created, close
    all PRs and re-raise.

    Args:
        epic_id: The epic identifier.
        branches: Repo-to-branch mapping.
        resume: The full resume context from the ledger.

    Returns:
        Dict mapping repo key to PR URL. Empty dict on failure.

    Raises:
        RuntimeError: If ledger_set_prs fails (after cleanup).
        ValueError: If pr_url_to_ref fails (after cleanup).
    """
    pr_urls: dict[str, str] = create_all_prs(epic_id, branches, resume)
    if not pr_urls:
        return {}

    try:
        refs = [pr_url_to_ref(url) for url in pr_urls.values()]
        refs_csv = ",".join(refs)
        ledger_set_prs(epic_id, refs_csv)
    except (RuntimeError, ValueError):
        logger.exception("Failed to set PR refs. Closing created PRs.")
        for url in pr_urls.values():
            close_pr(url)
        raise

    return pr_urls


def monitor_and_fix_ci(
    epic_id: str,
    pr_urls: dict[str, str],
    branches: dict[str, str],
) -> str:
    """Monitor CI checks and spawn fix sessions on failure.

    Polls CI for all PRs. On failure, collects failure details, renders
    a CI-fix prompt, spawns a single ``claude -p`` session, and re-polls.
    Max ``_MAX_CI_FIX_ATTEMPTS`` fix attempts.

    Args:
        epic_id: The epic identifier.
        pr_urls: Dict mapping repo to PR URL.
        branches: Repo-to-branch mapping.

    Returns:
        ``"all_green"`` if CI passes, ``"failed"`` if attempts exhausted.
    """
    config = get_config()

    for attempt in range(1, _MAX_CI_FIX_ATTEMPTS + 1):
        verdict, failed = poll_all_ci(
            pr_urls,
            epic_id,
            interval=_CI_POLL_INTERVAL,
            timeout=_CI_POLL_TIMEOUT,
        )
        if verdict == "all_green":
            return "all_green"

        logger.warning(
            "CI failed for epic %s (attempt %d/%d). Failed repos: %s",
            epic_id,
            attempt,
            _MAX_CI_FIX_ATTEMPTS,
            list(failed.keys()),
        )

        if attempt == _MAX_CI_FIX_ATTEMPTS:
            break

        failures = collect_ci_failures(failed)
        floor = bump_floor(attempt)
        prompt = render_ci_fix_prompt(
            epic_id,
            branches=branches,
            pr_urls=pr_urls,
            failures=failures,
            attempt=attempt,
            escalation_floor=floor,
            max_attempts=_MAX_CI_FIX_ATTEMPTS,
        )
        aws_creds = _load_aws_credentials()
        session_env = {"CI": "true", **aws_creds}
        run_claude_session(prompt, env=session_env, timeout=config["session_timeout"])
        time.sleep(_CI_POLL_INTERVAL)

    return "failed"


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------


def ralph_loop() -> None:
    """Main polling loop. Claims epics from ledger and executes them.

    Polls the ledger at the configured interval for ``in_progress``
    epics, then executes them via :func:`run_epic`. Runs indefinitely
    until interrupted.
    """
    config = get_config()
    poll_interval = config["poll_interval"]

    logger.info(
        "Ralph loop starting. Poll interval: %ds, session timeout: %ds.",
        poll_interval,
        config["session_timeout"],
    )

    while True:
        try:
            _poll_and_execute()
            time.sleep(poll_interval)
        except KeyboardInterrupt:
            logger.info("Ralph loop interrupted. Exiting.")
            break
        except Exception:
            logger.exception("Error in ralph loop iteration.")
            time.sleep(poll_interval)


def _poll_and_execute() -> None:
    """Execute one iteration of the polling loop.

    Queries the ledger for the next claimable epic and runs it.
    """
    result = subprocess.run(
        ["task", "ledger:next", "--", "--claimed-by", "ralph"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        logger.debug("No epics available for claim.")
        return

    stdout = result.stdout.strip()
    if not stdout or "No plans available" in stdout:
        logger.debug("No epics available.")
        return

    try:
        epic_data = parse_json_output(stdout)
        epic_id = epic_data.get("epic_id", "")
    except (ValueError, json.JSONDecodeError):
        logger.warning("Could not parse claimed epic data.")
        return

    if not epic_id:
        return

    logger.info("Claimed epic %s. Starting execution.", epic_id)
    run_epic(epic_id)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main(
    *,
    epic_id: str = "",
    once: bool = False,
) -> None:
    """CLI entry point for ralph headless epic runner.

    Args:
        epic_id: Run a specific epic (skip claim loop).
        once: Run one iteration then exit (no polling loop).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if epic_id:
        logger.info("Running specific epic: %s", epic_id)
        run_epic(epic_id)
        return

    if once:
        logger.info("Running single iteration (--once).")
        _poll_and_execute()
        return

    ralph_loop()


# MUST BE LAST
if __name__ == "__main__":
    defopt.run(main)
