#!/usr/bin/env bash
# codex-review-container.sh — invoke the container-mode codex-review.
# Reads env vars from the process environment (populated by
# cli-args-to-env.sh) and forwards them to docker compose via bare
# -e VAR flags so secrets and caller-supplied values cross the
# container boundary without appearing on the command line.
set -euo pipefail

mkdir -p ~/.brownfield-ai/agent-review agent-review

exec docker compose run --rm --user agent \
  -e OPENAI_API_KEY \
  -e ROUND \
  -e EFFORT \
  -e REVIEW_SESSION_ID \
  -e WORKSPACE \
  -e MODEL \
  -e REVIEW_TYPE \
  -e DIFF_FILE \
  -e REVIEW_MODE \
  agent-cli codex-review
