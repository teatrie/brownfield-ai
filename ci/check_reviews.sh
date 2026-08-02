#!/usr/bin/env bash
# Fetch PR states for in_review epics and pipe to process-reviews-cli.
# Usage: check_reviews.sh <epics_json_file> <output_json_file>
# Dependencies: gh (GitHub CLI), jq, bash
set -euo pipefail

EPICS_FILE="${1:?Usage: check_reviews.sh <epics_json_file> <output_json_file>}"
OUTPUT_FILE="${2:?Usage: check_reviews.sh <epics_json_file> <output_json_file>}"

mkdir -p tmp
ERROR_LOG="tmp/check-reviews-errors.log"
: > "$ERROR_LOG"

# Process each epic and output one JSON object per epic to stdout,
# then slurp into an array at the end.
process_epics() {
    while IFS= read -r line; do
        epic_id=$(printf '%s' "$line" | jq -r '.epic_id')
        current_prs=$(printf '%s' "$line" | jq -r '.current_prs // empty')
        [ -z "$current_prs" ] && continue

        # Collect PR states for this epic: emit one JSON object per PR,
        # then slurp into an array with jq -s for O(N) total work.
        IFS=', ' read -ra refs <<< "$current_prs"
        for ref in "${refs[@]}"; do
            [ -z "$ref" ] && continue
            repo="${ref%%#*}"
            number="${ref##*#}"
            pr_state=$(gh pr view "$number" --repo "$repo" \
                --json state,reviewDecision,mergeCommit 2>>"$ERROR_LOG" \
                || echo '{"state":"UNKNOWN","reviewDecision":null,"mergeCommit":null}')
            printf '%s' "$pr_state" | jq -c --arg r "$ref" '. + {ref: $r}'
        done | jq -sc --arg eid "$epic_id" '{epic_id: $eid, prs: .}'

    done < <(jq -c '.[]' "$EPICS_FILE")
}

process_epics | jq -s '.' > "$OUTPUT_FILE"
