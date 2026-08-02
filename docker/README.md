# Docker Images

This directory contains the Dockerfiles and build contexts for the various isolated environments used by the `brownfield-ai` project.

As per our agent guidelines (Environment Isolation), we rely heavily on Docker and [docker-compose.yml](../docker-compose.yml) to prevent local environment corruption, ensure reproducibility in CI, and prevent agents from executing commands directly on the host MacOS/Linux machine.

## CLI Services (Docker Compose)

These images are defined as services in the root [docker-compose.yml](../docker-compose.yml) and are heavily used by the Task orchestrator ([Taskfile.yml](../Taskfile.yml)) and subagents for safe execution.

### `python-cli/`

- **Dockerfile**: [docker/python-cli/Dockerfile](python-cli/Dockerfile)
- **Compose Service**: `python-cli`
- **Purpose**: A comprehensive Python execution environment that also includes the AWS CLI. Used for running automation scripts located in [scripts/](../scripts/), parsing files, executing formatters/linters, and loading/checkpointing memory into ChromaDB.

### `pytest-cli/`

- **Dockerfile**: [docker/pytest-cli/Dockerfile](pytest-cli/Dockerfile)
- **Compose Service**: `pytest-cli`
- **Purpose**: Dedicated test runner environment. Contains dependencies for `pytest`, AWS mocking (`moto`), and interacts with Localstack. It maps the host's Docker socket (`/var/run/docker.sock`) so that the test suite can spin up sub-containers and execute Docker-in-Docker flows for end-to-end evaluation testing.

### `agent-cli/`

- **Dockerfile**: [docker/agent-cli/Dockerfile](agent-cli/Dockerfile)
- **Compose Service**: `agent-cli`
- **Purpose**: Cross-family agent CLI container for bridge reviews. Contains GitHub Copilot CLI, Google Gemini CLI, and GitHub CLI (`gh`). Used by `task agent:review:copilot` and `task agent:review:gemini` to run code reviews from non-Claude AI families inside Docker, bypassing host sandbox restrictions.

## Task Builders (`builders/`)

These Dockerfiles are built and invoked on-the-fly by specific Go-Task definitions (located in [taskfiles/](../taskfiles/)) rather than being kept alive as Compose services.

### `Dockerfile.infra-lint`

- **Purpose**: Creates an isolated environment containing linters (`ruff`, `yamllint`, `markdownlint`). Invoked during `task lint` to validate the cleanliness of Python, YAML, and Markdown files across the codebase.

### `Dockerfile.infra-terraform`

- **Purpose**: An isolated Terraform execution environment containing the `terraform` CLI and AWS dependencies. Uses a restricted `tf-safe.sh` entrypoint that only permits `init`, `fmt`, `plan`, and `show` commands, preventing accidental `apply` or `destroy` from agent sessions. Chain multiple commands with `--` separators (e.g., `init -- plan -out=plan.out`). Used by tasks that provision infrastructure (e.g., `dms_infra_task.py`) to keep Terraform module caching and operations isolated.

#### Security Hardening (Defense-in-Depth)

The infra-terraform image implements a 4-layer defense model to prevent sub-agents from executing destructive Terraform commands:

1. **OS File Permissions**: The real terraform binary (`/bin/_tf_exec_internal`) is `chmod 0700` root-owned, preventing direct execution by non-root users. Note: Docker Desktop for Mac's container runtime may bypass this check on direct `--entrypoint` invocation; the remaining layers provide fallback coverage.
2. **Non-root User**: The Dockerfile sets `USER agent` as the default. The `tf-safe.sh` wrapper is `chown root:root && chmod 0755` to prevent the agent user from overwriting it.
3. **Scoped Sudoers**: A sudoers file (`/etc/sudoers.d/tf-safe`) grants the `agent` user passwordless `sudo` only for allowed subcommands (`init`, `fmt`, `plan`, `show`) with argument pass-through. Unlisted subcommands (e.g., `sudo /bin/_tf_exec_internal apply`) are denied by sudoers.
4. **Claude Code Deny Rules**: Permission deny rules in `.claude/settings.json` block sub-agents from constructing `--entrypoint` bypass, direct `_tf_exec_internal` invocation, or `--user root` commands targeting the infra-terraform image.

**Pre-flight requirement**: Sub-agents require AWS credentials injected via the `aws-vault-auth` skill (`source tmp/.aws-credentials.env` before invocation).

**Accepted risk**: No machine-enforced lint rule validates `--user agent` in consumer `docker run` commands. Enforcement relies on SKILL.md templates, deny rules, and the delegation protocol. A grep-based CI check is a future improvement candidate.
