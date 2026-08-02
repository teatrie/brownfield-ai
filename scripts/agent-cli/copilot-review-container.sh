#!/usr/bin/env bash
# copilot-review-container.sh — invoke the copilot-review command inside the
# agent-cli container. The inner copilot-review.sh loads the reviewer template
# based on REVIEW_TYPE and builds the combined prompt file itself.
# ROUND, REVIEW_TYPE, and DIFF_FILE must be set by the caller via CLI_ARGS
# (see cli-args-to-env.sh).
set -euo pipefail

exec docker compose run --rm --user agent \
  -e COPILOT_GITHUB_TOKEN \
  -e ROUND \
  -e REVIEW_TYPE \
  -e DIFF_FILE \
  agent-cli copilot-review
