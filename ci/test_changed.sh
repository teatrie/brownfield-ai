#!/bin/bash
set -e

# Script: test_changed.sh
# Description: Determines which files have changed (scripts or skills) and runs 
#              only the corresponding tests natively.

usage() {
    echo "Usage: $0 [scripts|skills|brownfield_ai]"
    exit 1
}

if [ -z "$1" ]; then
    usage
fi

TARGET=$1

# Determine changes
CHANGED_FILES=""

if [ "$GITHUB_EVENT_NAME" == "pull_request" ]; then
    echo "Running in PR context"
    # Fetch base ref
    git fetch origin "${GITHUB_BASE_REF:-main}" --depth=1 || true
    BASE_SHA=$(git rev-parse "origin/${GITHUB_BASE_REF:-main}" 2>/dev/null || echo "origin/main")
    echo "Diffing against base $BASE_SHA"
    CHANGED_FILES=$(git diff --name-only "$BASE_SHA" HEAD || echo "")
elif [ "$GITHUB_EVENT_NAME" == "push" ]; then
    echo "Running in Push context"
    # A root commit has no parent, so HEAD^ does not resolve, the diff comes
    # back empty, and this script would report success having run no tests.
    # Treat every tracked file as changed — the honest reading of "every file
    # is new".
    if git rev-parse --verify HEAD^ >/dev/null 2>&1; then
        CHANGED_FILES=$(git diff --name-only HEAD^ HEAD || echo "")
    else
        echo "Root commit detected (no parent) — treating all tracked files as changed."
        CHANGED_FILES=$(git ls-files)
    fi
else
    echo "Running locally or unknown context"
    if git rev-parse --verify origin/main >/dev/null 2>&1; then
        BASE_BRANCH="origin/main"
    elif git rev-parse --verify main >/dev/null 2>&1; then
        BASE_BRANCH="main"
    fi

    if [ -n "$BASE_BRANCH" ]; then
        COMMITTED=$(git diff --name-only "$BASE_BRANCH" HEAD || true)
    else
        COMMITTED=""
    fi
    STAGED=$(git diff --name-only --cached || true)
    UNSTAGED=$(git diff --name-only || true)
    UNTRACKED=$(git ls-files --others --exclude-standard || true)

    CHANGED_FILES=$(echo -e "${COMMITTED}\n${STAGED}\n${UNSTAGED}\n${UNTRACKED}" | sort -u | grep -v '^$')
fi

run_pytest_docker() {
    if [ $# -eq 0 ] || [ -z "$1" ]; then
        echo "No changed tests to run."
        return 0
    fi
    trap 'rm -f "tmp/.python-gate-pass"' RETURN
    ./docker/shared/python-security-gate.sh test "$@"
    echo "Running pytest (Docker) with $*"
    mkdir -p tmp && chmod 777 tmp
    docker compose build pytest-cli
    set +e
    docker compose run --rm --user agent \
        -v "$(pwd)/tmp/.python-gate-pass:/tmp/.python-gate-pass:ro" \
        pytest-cli pytest "$@" -s --junitxml="tmp/junit_${TARGET}.xml"
    EXIT_CODE=$?
    set -e
    if [ "$EXIT_CODE" -eq 5 ]; then
        echo "Pytest returned 5 (No tests collected). Treating as success."
        return 0
    elif [ "$EXIT_CODE" -ne 0 ]; then
        echo "Pytest failed with exit code $EXIT_CODE"
        exit "$EXIT_CODE"
    fi
}

run_pytest_venv() {
    if [ $# -eq 0 ] || [ -z "$1" ]; then
        echo "No changed tests to run."
        return 0
    fi
    echo "Running pytest (venv) with $*"
    if [ ! -f .venv/bin/pytest ]; then
        echo "ERROR: .venv not found. Run 'task test:setup' first."
        exit 1
    fi
    set +e
    .venv/bin/pytest "$@" -s --junitxml="tmp/junit_${TARGET}.xml"
    EXIT_CODE=$?
    set -e
    if [ "$EXIT_CODE" -eq 5 ]; then
        echo "Pytest returned 5 (No tests collected). Treating as success."
        return 0
    elif [ "$EXIT_CODE" -ne 0 ]; then
        echo "Pytest failed with exit code $EXIT_CODE"
        exit "$EXIT_CODE"
    fi
}

if [ "$TARGET" == "scripts" ]; then
    CHANGED_SCRIPTS=$(echo "$CHANGED_FILES" | grep -E "^(scripts/|tests/scripts/|ci/|tests/ci/|tests/helpers/|tests/lint/|\.claude/hooks/|tests/hooks/|\.claude/agents/|tests/agents/|\.claude/prompts/reviewer/|\.claude/skills/diff-review/|\.codex/|docker/shared/|docker/agent-cli/|\.claude/settings(\.local)?\.json)" || true)

    if [ -n "$CHANGED_SCRIPTS" ]; then
        declare -a TEST_TARGETS_ARRAY=()
        for file in $CHANGED_SCRIPTS; do
            if [[ "$file" == tests/scripts/* ]] || [[ "$file" == tests/ci/* ]] || [[ "$file" == tests/lint/* ]] || [[ "$file" == tests/hooks/* ]] || [[ "$file" == tests/agents/* ]]; then
                # Include only actual test files (test_*.py), skip fixtures
                if [ -f "$file" ] && [[ "$(basename "$file")" == test_*.py ]]; then
                    TEST_TARGETS_ARRAY+=("$file")
                fi
            elif [[ "$file" == tests/helpers/* ]]; then
                # tests/helpers/ is a helper *package*, not a leaf suite: its
                # modules are imported by other suites rather than exercised in
                # place. It matched no branch here at all, so every test under
                # it ran only in the full `task test:scripts` and never in the
                # staged or pre-push gate. A changed test file routes to itself
                # as in the branch above; a changed helper module routes to the
                # whole helpers suite plus tests/ci/, whose router contracts
                # import helpers.router_harness and would otherwise be blind to
                # it. Deriving tests/helpers/test_<basename>.py instead would
                # resolve for eval_utils and runners but silently route
                # router_harness.py and aws_env.py to nothing — the same
                # un-routing this branch exists to close. Known limit: the
                # skills suite also imports helpers.eval_utils and
                # helpers.runners, but it is routed by the `skills` target and
                # each of its cases spends a live agent call, so helper edits
                # are deliberately not fanned into it.
                if [ -f "$file" ] && [[ "$(basename "$file")" == test_*.py ]]; then
                    TEST_TARGETS_ARRAY+=("$file")
                else
                    TEST_TARGETS_ARRAY+=("tests/helpers/" "tests/ci/")
                fi
            elif [[ "$file" == scripts/agent-cli/* ]] || [[ "$file" == docker/agent-cli/* ]]; then
                # Agent-cli files route to flat tests/scripts/ via one of two
                # naming conventions; try both and add each match:
                #   (a) flat:     tests/scripts/test_<basename>.py
                #                 (e.g. test_codex_review.py, test_gemini_review.py,
                #                  test_cli_args_to_env.py, test_wrapper_sanitation.py)
                #   (b) prefixed: tests/scripts/test_agent_cli_<basename>.py
                #                 (e.g. test_agent_cli_entrypoint.py,
                #                  test_agent_cli_preflight.py, test_agent_cli_taskfile.py,
                #                  test_agent_cli_container_review.py)
                # The basename strips dashes → underscores and drops any trailing
                # extension (.sh, .toml, etc.); Dockerfile has no extension and
                # passes through unchanged. Both candidates are checked — a source
                # file may have a flat test even when an agent-cli-prefixed test
                # also exists. De-duplication downstream via `sort -u`.
                basename=$(basename "$file")
                basename=${basename%.*}
                basename=${basename//-/_}
                for candidate in \
                    "tests/scripts/test_${basename}.py" \
                    "tests/scripts/test_agent_cli_${basename}.py"; do
                    if [ -f "$candidate" ]; then
                        TEST_TARGETS_ARRAY+=("$candidate")
                    fi
                done
            elif [[ "$file" == .claude/prompts/reviewer/* ]] || [[ "$file" == .claude/skills/diff-review/* ]] || [[ "$file" == scripts/lint_reviewer_templates.py ]] || [[ "$file" == .codex/config.toml ]] || [[ "$file" == docker/agent-cli/codex-config.toml ]]; then
                # The reviewer-template parity check compares a rubric that
                # is mirrored across several sources. Every one of them, and
                # the checker itself, routes here. The condition above is the
                # enumeration — repeating it in prose would be a second copy
                # to keep current.
                # Explicit rather than derivation-driven: most of these paths
                # have no derivable test name at all, and the checker would
                # otherwise fall through to the scripts/* derivation below,
                # which builds tests/scripts/test_lint_reviewer_templates.py
                # — a name that does not exist, silently routing the parity
                # guard's own checker to zero tests.
                test_file="tests/scripts/test_reviewer_templates.py"
                if [ -f "$test_file" ]; then
                    TEST_TARGETS_ARRAY+=("$test_file")
                fi
            elif [[ "$file" == scripts/* ]] || [[ "$file" == ci/* ]]; then
                # Map script to its test file. Strip the source extension and
                # append .py: tests are Python, so keeping the original suffix
                # would build tests/ci/test_lint_changed.sh — a name that can
                # never exist, silently un-routing every shell script here.
                # Mirrors the .claude/hooks/* and docker/shared/* branches.
                basename=$(basename "$file")
                basename=${basename%.*}
                basename=${basename//-/_}
                dirname=$(dirname "$file")
                test_file="tests/${dirname}/test_${basename}.py"
                if [ -f "$test_file" ]; then
                    TEST_TARGETS_ARRAY+=("$test_file")
                fi
            elif [[ "$file" == .claude/hooks/* ]]; then
                # Route to the whole suite rather than deriving a test name.
                # Hooks are dash-named, their tests underscore-named with a
                # _hook suffix, and block-container-escape.sh /
                # test_block_container_hook.py share no stem at all — so no
                # derivation rule resolves every hook, and a miss silently
                # routes a security-boundary change to zero tests. Mirrors the
                # same routing in test_staged.sh so hook edits are gated on
                # both the staged and pre-push paths.
                TEST_TARGETS_ARRAY+=("tests/hooks/")
            elif [[ "$file" == .claude/settings*.json ]]; then
                # The permission-baseline and hook-registration-integrity
                # tests live in tests/hooks/ and are the only gate on this
                # file.
                TEST_TARGETS_ARRAY+=("tests/hooks/")
            elif [[ "$file" == .claude/agents/* ]]; then
                # Any agent .md change re-runs the variant-parity contract.
                # The test walks .claude/agents/*-{high,xhigh,max}.md and
                # asserts byte-parity with the base agent's body — drift
                # caused by editing a base without syncing its variants
                # surfaces here. Mirrors the same routing in test_staged.sh
                # so the contract fires on both staged and pre-push gates.
                test_file="tests/agents/test_variant_parity.py"
                if [ -f "$test_file" ]; then
                    TEST_TARGETS_ARRAY+=("$test_file")
                fi
            elif [[ "$file" == docker/shared/* ]]; then
                # Map gate scripts to their test files in tests/scripts/
                basename=$(basename "$file" .sh)
                basename=${basename//-/_}
                test_file="tests/scripts/test_${basename}.py"
                if [ -f "$test_file" ]; then
                    TEST_TARGETS_ARRAY+=("$test_file")
                fi
            fi
        done

        # Unique list
        if [ ${#TEST_TARGETS_ARRAY[@]} -gt 0 ]; then
            UNIQUE_TARGETS=()
            while IFS= read -r line; do UNIQUE_TARGETS+=("$line"); done < <(printf "%s\n" "${TEST_TARGETS_ARRAY[@]}" | sort -u)
            run_pytest_docker "${UNIQUE_TARGETS[@]}"
        else
            echo "No testable scripts found."
        fi

        # Agent-cli paths require container-integration coverage host-side.
        # The default pytest-cli dispatch triggers INSIDE_CONTAINER skip in
        # test_agent_cli_container_review.py, yielding a silent false-green.
        # Re-run the test via the host-side task target whenever any file
        # that ships inside the agent-cli image changes. The scripts/agent-cli
        # enumeration mirrors the COPY directives in docker/agent-cli/Dockerfile
        # exactly — keep the two lists in sync. Host-side scripts under
        # scripts/agent-cli/ that are NOT COPYed into the image (e.g. preflight-
        # tiered wrappers, *-review-container.sh, cli-args-to-env.sh) do not
        # affect the container-integration test and are deliberately excluded.
        AGENT_CLI_RELEVANT=$(echo "$CHANGED_SCRIPTS" | grep -E "^(docker/agent-cli/|scripts/agent-cli/(copilot-review|gemini-review|codex-review|preflight|_review-common)\.sh|tests/scripts/test_agent_cli_container_review\.py)" || true)
        if [ -n "$AGENT_CLI_RELEVANT" ]; then
            echo "Agent-cli paths changed — running task test:container-integration host-side"
            task test:container-integration
        fi
    else
        echo "No scripts or script tests changed."
    fi

elif [ "$TARGET" == "brownfield_ai" ]; then
    CHANGED_PY_BROWNFIELD_AI=$(echo "$CHANGED_FILES" | grep -E "^(src/brownfield_ai/|tests/src/brownfield_ai/)" || true)

    if [ -n "$CHANGED_PY_BROWNFIELD_AI" ]; then
        # Use python script to resolve dependencies and find all affected tests
        RESOLVED_TESTS_ARRAY=()
        PY_BROWNFIELD_AI_ARRAY=()
        while IFS= read -r line; do [ -n "$line" ] && PY_BROWNFIELD_AI_ARRAY+=("$line"); done <<< "$CHANGED_PY_BROWNFIELD_AI"
        while IFS= read -r line; do RESOLVED_TESTS_ARRAY+=("$line"); done < <(python ci/resolve_downstream_tests.py main "${PY_BROWNFIELD_AI_ARRAY[@]}" 2>/dev/null || true)

        TEST_TARGETS_ARRAY=("${RESOLVED_TESTS_ARRAY[@]}")

        # If the python script outputs nothing but we have source file changes, fallback to running all
        if [ ${#TEST_TARGETS_ARRAY[@]} -eq 0 ] && [ -n "$CHANGED_PY_BROWNFIELD_AI" ]; then
            echo "Could not find specific mapped test files for brownfield_ai changes, running all brownfield_ai tests as fallback."
            TEST_TARGETS_ARRAY=("tests/src/brownfield_ai/")
        fi

        if [ ${#TEST_TARGETS_ARRAY[@]} -gt 0 ]; then
            UNIQUE_TARGETS=()
            while IFS= read -r line; do UNIQUE_TARGETS+=("$line"); done < <(printf "%s\n" "${TEST_TARGETS_ARRAY[@]}" | sort -u)
            run_pytest_docker "${UNIQUE_TARGETS[@]}"
        else
            echo "No testable brownfield_ai changes found."
        fi
    else
        echo "No brownfield_ai files or tests changed."
    fi

elif [ "$TARGET" == "skills" ]; then
    CHANGED_SKILLS=$(echo "$CHANGED_FILES" | grep -E "^(\.claude/skills/|tests/skills/|workflows/[^/]+/skills/|tests/workflows/[^/]+/skills/)" || true)

    if [ -n "$CHANGED_SKILLS" ]; then
        # We need to run pytest tests/ and parameterize to only changed skills
        # Pytest allows running specific parameterized tests using -k.
        declare -a SKILL_NAMES_ARRAY=()
        for file in $CHANGED_SKILLS; do
            if [[ "$file" == .claude/skills/* ]]; then
                skill=$(echo "$file" | cut -d'/' -f3)
                SKILL_NAMES_ARRAY+=("$skill")
            elif [[ "$file" == tests/skills/* ]]; then
                skill=$(echo "$file" | cut -d'/' -f3)
                SKILL_NAMES_ARRAY+=("$skill")
            elif [[ "$file" =~ ^workflows/[^/]+/skills/([^/]+) ]]; then
                SKILL_NAMES_ARRAY+=("${BASH_REMATCH[1]}")
            elif [[ "$file" =~ ^tests/workflows/[^/]+/skills/([^/]+) ]]; then
                SKILL_NAMES_ARRAY+=("${BASH_REMATCH[1]}")
            fi
        done

        if [ ${#SKILL_NAMES_ARRAY[@]} -gt 0 ]; then
            UNIQUE_SKILLS=()
            while IFS= read -r skill; do
                UNIQUE_SKILLS+=("$skill")
            done < <(printf "%s\n" "${SKILL_NAMES_ARRAY[@]}" | sort -u)

            # Construct Pytest -k filter, e.g., -k "skill1 or skill2"
            k_filter=""
            for skill in "${UNIQUE_SKILLS[@]}"; do
                if [ -z "$k_filter" ]; then
                    k_filter="$skill"
                else
                    k_filter="$k_filter or $skill"
                fi
            done

            # Resolve workflow script test files via AST import analysis
            WORKFLOW_SCRIPTS=$(echo "$CHANGED_SKILLS" | grep -E '^workflows/.*\.py$' | grep -v '__init__\.py' || true)
            WORKFLOW_TESTS=()
            if [ -n "$WORKFLOW_SCRIPTS" ]; then
                WORKFLOW_SCRIPTS_ARRAY=()
                while IFS= read -r line; do [ -n "$line" ] && WORKFLOW_SCRIPTS_ARRAY+=("$line"); done <<< "$WORKFLOW_SCRIPTS"
                while IFS= read -r line; do WORKFLOW_TESTS+=("$line"); done \
                    < <(python ci/resolve_downstream_tests.py workflow "${WORKFLOW_SCRIPTS_ARRAY[@]}" 2>tmp/resolve_workflow.log || true)
            fi

            # Build --deselect args to prevent duplicate execution
            DESELECT_ARGS=()
            if [ ${#WORKFLOW_TESTS[@]} -gt 0 ]; then
                for tf in "${WORKFLOW_TESTS[@]}"; do
                    DESELECT_ARGS+=("--deselect" "$tf")
                done
            fi

            # Invocation 1: parameterized skill evals (deselecting resolved workflow tests)
            run_pytest_venv tests/ -k "$k_filter" "${DESELECT_ARGS[@]}"

            # Invocation 2: resolved workflow test files
            if [ ${#WORKFLOW_TESTS[@]} -gt 0 ]; then
                TARGET="skills_workflow" run_pytest_venv "${WORKFLOW_TESTS[@]}"
            fi
        else
            echo "No testable skills changed."
        fi
    else
        echo "No skills or skill tests changed."
    fi
elif [ "$TARGET" == "dashboard" ]; then
    CHANGED_DASHBOARD=$(echo "$CHANGED_FILES" | grep -E "^(services/dashboard/|tests/services/dashboard/)" || true)

    if [ -n "$CHANGED_DASHBOARD" ]; then
        # Collect changed test files for selective execution
        CHANGED_TESTS=$(echo "$CHANGED_DASHBOARD" | grep -E "^tests/services/dashboard/test_.*\.py$" || true)
        CHANGED_SOURCE=$(echo "$CHANGED_DASHBOARD" | grep -E "^services/dashboard/" || true)

        if [ -n "$CHANGED_SOURCE" ] || [ -z "$CHANGED_TESTS" ]; then
            # Source changes or conftest-only: run full suite (any source
            # change can affect any test)
            echo "Dashboard source changes detected, running full dashboard:test"
            task test:dashboard
        else
            # Only test files changed: run just those files
            echo "Dashboard test-only changes detected, running selective tests"
            TEST_ARRAY=()
            while IFS= read -r line; do [ -n "$line" ] && TEST_ARRAY+=("$line"); done <<< "$CHANGED_TESTS"
            docker compose run --rm --entrypoint "" \
                pytest-cli \
                sh -c 'pip install --quiet -r services/dashboard/requirements-dev.txt && pytest "$@" -v' -- "${TEST_ARRAY[@]}"
        fi
    else
        echo "No dashboard files changed."
    fi
else
    echo "Unknown target: $TARGET"
    exit 1
fi
