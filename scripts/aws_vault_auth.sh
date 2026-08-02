#!/usr/bin/env bash

set -euo pipefail

if [ -z "${1:-${AWS_PROFILE:-}}" ]; then
  echo "Usage: $0 [profile]" >&2
  echo "Or set AWS_PROFILE environment variable." >&2
  exit 1
fi

PROFILE=${1:-${AWS_PROFILE}}

# Run aws-vault and capture the output, filtering for AWS_ keys needed for STS
if ! OUTPUT=$(aws-vault exec "$PROFILE" -- env); then
  echo "Error: Failed to fetch credentials. Please run 'aws-vault exec $PROFILE' manually to authenticate." >&2
  exit 1
fi

# Extract and format the specific keys
mkdir -p tmp
ENV_FILE="tmp/.aws-credentials.env"
true > "$ENV_FILE"

echo "$OUTPUT" | grep "^AWS_" | while IFS= read -r line; do
  key="${line%%=*}"
  value="${line#*=}"
  # Only export standard STS keys to keep the environment clean
  if [[ "$key" == "AWS_ACCESS_KEY_ID" || "$key" == "AWS_SECRET_ACCESS_KEY" || "$key" == "AWS_SESSION_TOKEN" || "$key" == "AWS_SECURITY_TOKEN" ]]; then
    echo "export $key='$value'" >> "$ENV_FILE"
  fi
done

echo "Successfully wrote credentials to $ENV_FILE"

