#!/bin/bash
set -e

# Script: test_staged.sh
# Description: Determines which staged files have changed (scripts or skills) and runs
#              only the corresponding tests for staged files.

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

CHANGED_FILES=$(git diff --name-only --cached || echo "")

run_pytest_docker() {
    if [ $# -eq 0 ] || [ -z "$1" ]; then
        echo "No changed tests to run."
        return 0
    fi
    trap 'rm -f "tmp/.python-gate-pass"' RETURN
    ./docker/shared/python-security-gate.sh test "$@"
    echo "Running pytest (Docker) with $*"
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
    CHANGED_SCRIPTS=$(echo "$CHANGED_FILES" | grep -E "^(scripts/|tests/scripts/|ci/|tests/ci/|tests/helpers/|tests/lint/|\.claude/hooks/|tests/hooks/|\.claude/agents/|tests/agents/|\.claude/prompts/reviewer/|\.claude/skills/diff-review/|\.codex/|docker/shared/|\.claude/settings(\.local)?\.json)" || true)

    if [ -n "$CHANGED_SCRIPTS" ]; then
        declare -a TEST_TARGETS_ARRAY=()
        for file in $CHANGED_SCRIPTS; do
            if [[ "$file" == tests/scripts/* ]] || [[ "$file" == tests/ci/* ]] || [[ "$file" == tests/lint/* ]] || [[ "$file" == tests/hooks/* ]] || [[ "$file" == tests/agents/* ]]; then
                # Include test files directly if they are Python files and still exist
                if [[ "$file" == *.py ]] && [ -f "$file" ]; then
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
            elif [[ "$file" == .claude/prompts/reviewer/* ]] || [[ "$file" == .claude/skills/diff-review/* ]] || [[ "$file" == scripts/lint_reviewer_templates.py ]] || [[ "$file" == .codex/config.toml ]] || [[ "$file" == docker/agent-cli/codex-config.toml ]]; then
                # The reviewer-template parity check compares a rubric
                # mirrored across several sources. Four of the five
                # patterns above route here. The fifth,
                # docker/agent-cli/codex-config.toml, reaches this branch
                # in neither router; its parity is gated instead by
                # `task lint:reviewer-templates`, which both lint routers
                # fire on it. Dropping that pattern from one router alone
                # would fail this branch's byte-identity check.
                # Most of these paths have no derivable test name at all,
                # and the checker would otherwise fall through to the
                # scripts/* derivation below, which builds
                # tests/scripts/test_lint_reviewer_templates.py — a name
                # that does not exist, silently routing the parity guard's
                # own checker to zero tests.
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
                # routes a security-boundary change to zero tests.
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
                # surfaces here.
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
        while IFS= read -r line; do [ -n "$line" ] && RESOLVED_TESTS_ARRAY+=("$line"); done < <(python ci/resolve_downstream_tests.py main "${PY_BROWNFIELD_AI_ARRAY[@]}" 2>tmp/resolve_brownfield_ai.log || true)

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
        # We need to run pytest against tests/skills/ and tests/workflows/
        # and parameterize to only changed skills via the -k filter.
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
            while IFS= read -r line; do UNIQUE_SKILLS+=("$line"); done < <(printf "%s\n" "${SKILL_NAMES_ARRAY[@]}" | sort -u)

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
            run_pytest_venv tests/skills/ tests/workflows/ -k "$k_filter" "${DESELECT_ARGS[@]}"

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
