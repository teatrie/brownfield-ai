---
name: aws-vault-auth
description: Extracts securely cached AWS temporary credentials (STS tokens) into a cleanly formatted env file without exposing secrets to context. MUST be used before spawning sub-agents or Docker containers requiring AWS.
---

# aws-vault-auth

## Description

Extracts securely cached AWS temporary credentials (STS tokens) into a git-ignored file (`tmp/.aws-credentials.env`) without wrapping or executing secondary commands, keeping your context and payload secure.

## When to Use

MUST be used **before** spinning up any sub-agent or Docker container that requires AWS access (as mandated by Pre-flight Authentication protocols). Whenever a user asks you to interact with AWS or start a skill that requires AWS credentials, and you don't already have an active credentials file, call this skill first.

## Execution

Run the following script directly in the terminal:

```bash
scripts/aws_vault_auth.sh <profile_name>
```

*(Note: Determine the correct `<profile_name>` first by checking the
user's `$AWS_PROFILE` environment variable or asking them directly
if it is not provided).*

**Protocol Requirements:**

1. Wait for the script to finish. It will securely write to
   `tmp/.aws-credentials.env`.
2. DO NOT attempt to read `tmp/.aws-credentials.env` into your
   context using JSON/file-reading tools. The secrets must remain
   hidden.
3. When you subsequently spawn a sub-agent or launch a Docker
   container, seamlessly inject that environment file source into
   their target command.
   - *Sub-agent injection*:
     `source tmp/.aws-credentials.env && <target_command>`
   - *Docker injection*:
     `source tmp/.aws-credentials.env && docker compose run -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN <service> <command>`

### Restricted Platform Fallback (SSO Blocked)

Some agent platforms (e.g., remote Claude Code sessions) may block
access to the AWS SSO authentication URL, causing the script to fail
at the `aws-vault exec` step. When this happens:

**Detect**: The script exits non-zero with an error message indicating
authentication failure. Then branch on session mode:

**Headless mode** (detected via `CI=true` env var or a headless signal
from the calling pipeline):

1. Check whether `tmp/.aws-credentials.env` already exists and is
   non-empty (a prior session may have populated it). If valid cached
   credentials exist, proceed.
2. If not, HALT immediately -- do NOT attempt to prompt for user
   intervention. The calling orchestrator MUST checkpoint a
   `step_result` artifact to the Execution Ledger with
   `{"verdict": "fail", "reason": "AWS SSO auth failed in headless mode
   and no cached credentials available"}` and stop execution.

**Interactive mode** (default -- no headless signal):

1. **Instruct the user**: Display the following message:

   > AWS SSO authentication is restricted on this platform. Please
   > run the following command in a **separate terminal** where you
   > have browser access:
   >
   > ```bash
   > scripts/aws_vault_auth.sh <profile_name>
   > ```
   >
   > Once complete, type "credentials updated" to resume.

2. **Wait**: Pause execution until the user confirms credentials
   have been refreshed.
3. **Verify**: Confirm `tmp/.aws-credentials.env` exists and is
   non-empty, then resume the original task.

### Expiration & Retry Loop (Lazy Auth)

AWS STS tokens eventually expire (typically after 1 hour). **If any
delegated AWS or Task task subsequently fails with an
`ExpiredToken`, `UnrecognizedClientException`, or `AccessDenied`
error:**

1. Attempt to re-run `scripts/aws_vault_auth.sh` to overwrite
   `tmp/.aws-credentials.env` with fresh tokens.
2. If the script succeeds, automatically retry the failed task.
3. If the script fails (SSO restricted), follow the **Restricted
   Platform Fallback** flow above (which includes headless-specific
   handling).

### Error Handling & Fallback

If the script fails due to an unknown or missing profile/role, you
MUST NOT hallucinate alternatives.

**Headless mode** (`CI=true` or headless signal): Read
`~/.aws/config` to identify available profiles. If exactly one
profile exists, retry with that profile automatically. If zero or
multiple profiles exist, HALT immediately -- the calling orchestrator
MUST checkpoint a `step_result` artifact to the Execution Ledger
with `{"verdict": "fail", "reason": "AWS profile ambiguous or missing
in headless mode"}` and stop execution.

**Interactive mode** (default):

1. Read the user's local `~/.aws/config` file to extract available
   profiles.
2. Display this list to the user and ask them to make a selection.
3. Re-run the script using the newly correct profile.
