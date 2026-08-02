#!/bin/bash

# Stop on errors
set -e

echo "========================================"
echo "  Workspace Setup (setup_env.sh)       "
echo "========================================"
echo
echo "This script configures your local environment dependencies and variables (.envrc)."
echo

OS=$(uname -s 2>/dev/null || echo "Unknown")

# Minimum go-task version. Keep in sync with the pinned TASK_VERSION in
# .github/workflows/ci.yml and .github/workflows/test.yml (three call sites).
# A local `task` older than CI's pin can accept Taskfile syntax that fails on
# the runner, or reject syntax that works there - silently, until CI disagrees.
REQUIRED_TASK_VERSION="3.52.0"

# Formulae this script installs. Scopes the staleness report so it never nags
# about unrelated packages on the developer's machine.
MANAGED_BREW_PACKAGES="colima docker docker-compose go-task direnv jq gh aws-vault uv"

# Helper for checking and installing tools via brew
check_and_install() {
    local cmd_name="$1"
    local brew_pkg="$2"
    local display_name="$3"
    local manual_instructions="${4:-Please install $display_name manually (see README.md).}"

    if ! command -v "$cmd_name" >/dev/null 2>&1; then
        echo -e "⚠️  \033[33m$display_name is not installed.\033[0m"
        if [ "$OS" = "Darwin" ]; then
            if command -v brew >/dev/null 2>&1; then
                # Temporarily allow read to fail if user Ctrl+C
                set +e
                read -r -p "Do you want to install $display_name using Homebrew ('brew install $brew_pkg')? [y/N]: " PROMPT_INSTALL
                set -e
                if [[ "$PROMPT_INSTALL" =~ ^[Yy]$ ]]; then
                    echo "Installing $brew_pkg via Homebrew..."
                    brew install "$brew_pkg"
                else
                    echo "$manual_instructions"
                fi
            else
                echo "Homebrew is not installed. $manual_instructions"
            fi
        else
            echo "Non-macOS OS detected. $manual_instructions"
        fi
        echo
    else
        echo "✅ $display_name is installed."
    fi
}

# Extract the first semantic version triple from a command's output. go-task
# prints a bare "3.52.0"; the parse stays defensive so a future
# "Task version: 3.52.0" does not silently break the comparison.
read_version() {
    "$@" 2>/dev/null | sed -n 's/.*\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -n 1
}

# True when $1 sorts strictly below $2 under version ordering. `sort -V` is
# verified present on macOS/BSD sort and orders 3.5.0 < 3.48.0 < 3.52.0
# correctly, which a lexicographic compare would not.
version_lt() {
    [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n 1)" = "$1" ]
}

# Report managed Homebrew formulae that have newer versions available.
# `command -v` only answers present-or-absent, so without this a developer can
# sit on a months-old binary indefinitely and never be told.
report_stale_brew_packages() {
    if ! command -v brew >/dev/null 2>&1; then
        return 0
    fi
    local outdated stale formula base
    outdated=$(brew outdated --quiet 2>/dev/null || true)
    stale=""
    while IFS= read -r formula; do
        [ -n "$formula" ] || continue
        base="${formula##*/}"
        case " $MANAGED_BREW_PACKAGES " in
            *" $base "*) stale="$stale $base" ;;
        esac
    done <<< "$outdated"
    if [ -n "$stale" ]; then
        echo
        echo -e "ℹ️  \033[33mHomebrew has newer versions of:\033[0m$stale"
        echo "  Upgrade with: brew upgrade$stale"
    fi
}

echo "--- 1. Checking Prerequisites (Homebrew, Docker, Task) ---"
echo "These must be installed before proceeding. See README.md for details."
echo

prereqs_ok=true

if ! command -v brew >/dev/null 2>&1; then
    echo -e "⚠️  \033[33mHomebrew is not installed.\033[0m"
    echo "  Install: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    echo
    prereqs_ok=false
else
    echo "✅ Homebrew is installed."
fi

if ! command -v docker >/dev/null 2>&1; then
    echo -e "⚠️  \033[33mDocker is not installed.\033[0m"
    if command -v brew >/dev/null 2>&1; then
        echo "  Option 1 (recommended): Colima — free, lightweight, no commercial license"
        echo "  Option 2: Docker Desktop — commercial license required for large organizations"
        echo "    https://docs.docker.com/desktop/"
        set +e
        read -r -p "  Install Colima + Docker CLI via Homebrew? [y/N]: " PROMPT_DOCKER
        set -e
        if [[ "$PROMPT_DOCKER" =~ ^[Yy]$ ]]; then
            echo "  Installing colima, docker, and docker-compose via Homebrew..."
            brew install colima docker docker-compose
            echo "  Starting Colima..."
            colima start
            if ! docker info >/dev/null 2>&1; then
                echo -e "  \033[33mWarning: Docker daemon is not responding after Colima start.\033[0m"
                prereqs_ok=false
            fi
        else
            prereqs_ok=false
        fi
    else
        echo "  Install Colima (free): brew install colima docker docker-compose"
        echo "  Or Docker Desktop: https://docs.docker.com/desktop/"
        echo
        prereqs_ok=false
    fi
else
    echo "✅ Docker is installed."
fi

if ! command -v task >/dev/null 2>&1; then
    echo -e "⚠️  \033[33mTask (go-task) is not installed.\033[0m"
    if command -v brew >/dev/null 2>&1; then
        set +e
        read -r -p "  Install Task via Homebrew ('brew install go-task/tap/go-task')? [y/N]: " PROMPT_TASK
        set -e
        if [[ "$PROMPT_TASK" =~ ^[Yy]$ ]]; then
            echo "  Installing go-task via Homebrew..."
            brew install go-task/tap/go-task
        else
            prereqs_ok=false
        fi
    else
        echo "  Install: brew install go-task/tap/go-task"
        echo "  Without Homebrew: npm install -g @go-task/cli (the go-task project's own npm build)"
        echo "  Or a checksum-verified release: https://github.com/go-task/task/releases"
        echo
        prereqs_ok=false
    fi
else
    installed_task_version=$(read_version task --version)
    if [ -n "$installed_task_version" ] && version_lt "$installed_task_version" "$REQUIRED_TASK_VERSION"; then
        echo -e "⚠️  \033[33mTask (go-task) $installed_task_version is older than CI's pinned $REQUIRED_TASK_VERSION.\033[0m"
        echo "  CI installs a checksum-verified $REQUIRED_TASK_VERSION, so local runs can diverge from the runner."
        echo "  Upgrade: brew upgrade go-task"
        echo
    else
        echo "✅ Task (go-task) is installed (${installed_task_version:-version unknown})."
    fi
fi

if [ "$prereqs_ok" = false ]; then
    echo -e "\033[31mOne or more prerequisites are missing (Homebrew, Docker, Task).\033[0m"
    echo "See README.md for install instructions. Setup cannot continue."
    exit 1
fi

echo
echo "--- 2. Installing Additional Tools ---"

check_and_install "direnv" "direnv" "direnv"

# Offer to add direnv shell hook to the user's shell rc file
if command -v direnv >/dev/null 2>&1; then
    case "$SHELL" in
        */zsh)  SHELL_RC="$HOME/.zshrc";  SHELL_NAME="zsh" ;;
        */bash) SHELL_RC="$HOME/.bashrc"; SHELL_NAME="bash" ;;
        *)      SHELL_RC="" ;;
    esac
    if [ -n "$SHELL_RC" ] && [ -f "$SHELL_RC" ] && ! grep -q 'direnv hook' "$SHELL_RC" 2>/dev/null; then
        HOOK_CMD="eval \"\$(direnv hook $SHELL_NAME)\""
        echo -e "ℹ️  direnv shell hook is not in $SHELL_RC."
        set +e
        read -r -p "  Add '$HOOK_CMD' to $SHELL_RC? [y/N]: " PROMPT_DIRENV_HOOK
        set -e
        if [[ "$PROMPT_DIRENV_HOOK" =~ ^[Yy]$ ]]; then
            {
                echo ""
                echo "# direnv — auto-load .envrc environment variables"
                echo "$HOOK_CMD"
            } >> "$SHELL_RC"
            echo "  ✅ Added direnv hook to $SHELL_RC."
        fi
    fi
fi
check_and_install "jq" "jq" "jq (JSON processor)"
check_and_install "gh" "gh" "GitHub CLI (gh)"
check_and_install "aws-vault" "aws-vault" "aws-vault (Optional — required for advanced data engineering workflows)" "See the aws-vault install guide: https://github.com/99designs/aws-vault#installing"
check_and_install "uv" "uv" "uv (Optional — Python package manager; required by 'task test:setup' for local host-run tests)" "See https://docs.astral.sh/uv/getting-started/installation/ or run 'pip install uv' / 'curl -LsSf https://astral.sh/uv/install.sh | sh'. Do NOT run 'npm install -g uv' - on npm that name belongs to an unrelated UTF-8 validation library, and installing it satisfies the 'command -v uv' check here while breaking 'task test:setup'."

# Check for gh copilot extension (optional)
if command -v gh >/dev/null 2>&1; then
    if ! gh extension list 2>/dev/null | grep -q "gh-copilot"; then
        echo -e "ℹ️  GitHub Copilot CLI extension is not installed (optional)."
        echo "  Only needed if you use GitHub Copilot as your agent platform."
        set +e
        read -r -p "  Install it? [y/N]: " PROMPT_COPILOT
        set -e
        if [[ "$PROMPT_COPILOT" =~ ^[Yy]$ ]]; then
            echo "  Installing GitHub Copilot CLI..."
            gh extension install github/gh-copilot
        fi
        echo
    else
        echo "✅ GitHub Copilot CLI is installed (optional)."
    fi
fi

report_stale_brew_packages
echo

# ============================================
# 3. Agent CLI Credentials (.env)
# ============================================
echo ""
echo "--- 3. Agent CLI Credentials (.env) ---"

# Helper: write or update a key=value pair in .env
write_env_var() {
    local key="$1"
    local value="$2"
    local env_file=".env"
    if [ ! -f "$env_file" ]; then
        touch "$env_file"
        chmod 600 "$env_file"
    fi
    # Remove existing key if present, then append
    if grep -q "^${key}=" "$env_file" 2>/dev/null; then
        local tmp_file
        mkdir -p tmp
        tmp_file="tmp/.env_rewrite_$$"
        grep -v "^${key}=" "$env_file" > "$tmp_file"
        mv "$tmp_file" "$env_file"
    fi
    echo "${key}=${value}" >> "$env_file"
    chmod 600 "$env_file"
}

# --- GH_TOKEN + COPILOT_GITHUB_TOKEN ---
# Both use the same GitHub token. Fallback: env -> .env -> gh auth token
gh_token=""
if [ -n "${COPILOT_GITHUB_TOKEN:-}" ]; then
    gh_token="$COPILOT_GITHUB_TOKEN"
    echo "  GH_TOKEN / COPILOT_GITHUB_TOKEN = [Set in env]"
elif [ -n "${GH_TOKEN:-}" ]; then
    gh_token="$GH_TOKEN"
    echo "  GH_TOKEN / COPILOT_GITHUB_TOKEN = [From GH_TOKEN]"
elif grep -q "^COPILOT_GITHUB_TOKEN=" .env 2>/dev/null; then
    echo "  GH_TOKEN / COPILOT_GITHUB_TOKEN = [Set in .env]"
    read -r -p "  Refresh from gh auth token? [y/N] " refresh
    if [[ "$refresh" =~ ^[Yy] ]]; then
        gh_token=$(gh auth token 2>/dev/null)
        if [ -z "$gh_token" ]; then
            echo "  Error: gh auth token failed." >&2
        fi
    fi
else
    echo "  GH_TOKEN / COPILOT_GITHUB_TOKEN = [Not Set]"
    if ! command -v gh >/dev/null 2>&1; then
        echo -e "  \033[33mWarning: gh is not installed. Cannot extract GH_TOKEN.\033[0m"
        echo "  Install gh ('brew install gh'), run 'gh auth login', then re-run 'task setup:env'."
        echo "  Without GH_TOKEN, all 'task gh:*' commands will fail."
    else
        gh_token=$(gh auth token 2>/dev/null)
        if [ -z "$gh_token" ]; then
            echo -e "  \033[33mWarning: gh is installed but not authenticated.\033[0m"
            echo "  Run 'gh auth login' first, then re-run 'task setup:env'."
            echo "  Without GH_TOKEN, all 'task gh:*' commands will fail."
        else
            echo "  Cached from gh auth token."
        fi
    fi
fi
if [ -n "$gh_token" ]; then
    # Remove stale missing-token comment if present from a prior run
    if grep -q "^# GH_TOKEN=MISSING" .env 2>/dev/null; then
        mkdir -p tmp
        grep -v "^# GH_TOKEN=MISSING" .env > "tmp/.env_clean_$$"
        chmod 600 "tmp/.env_clean_$$"
        mv "tmp/.env_clean_$$" .env
    fi
    write_env_var "GH_TOKEN" "$gh_token"
    write_env_var "COPILOT_GITHUB_TOKEN" "$gh_token"
else
    # Purge stale token lines from a prior successful run to prevent expired tokens persisting
    if [ -f .env ]; then
        mkdir -p tmp
        grep -v -e "^GH_TOKEN=" -e "^COPILOT_GITHUB_TOKEN=" -e "^# GH_TOKEN=MISSING" .env > "tmp/.env_purge_$$"
        chmod 600 "tmp/.env_purge_$$"
        mv "tmp/.env_purge_$$" .env
    fi
    write_env_var "# GH_TOKEN" "MISSING -- run 'gh auth login' then re-run 'task setup:env'"
fi

# --- GEMINI_API_KEY (optional) ---
if [ -n "${GEMINI_API_KEY:-}" ]; then
    echo "  GEMINI_API_KEY = [Set in env] (optional)"
    write_env_var "GEMINI_API_KEY" "$GEMINI_API_KEY"
elif grep -q "^GEMINI_API_KEY=" .env 2>/dev/null; then
    echo "  GEMINI_API_KEY = [Set in .env] (optional)"
else
    echo "  GEMINI_API_KEY = [Not Set] (optional — only needed for Gemini CLI)"
    set +e
    read -r -p "  Do you have a Gemini API key? [y/N] " has_key
    set -e
    if [[ "$has_key" =~ ^[Yy] ]]; then
        read -r -p "  Enter Gemini API key: " gemini_key
        if [ -n "$gemini_key" ]; then
            write_env_var "GEMINI_API_KEY" "$gemini_key"
            echo "  Saved."
        fi
    fi
fi

# --- OPENAI_API_KEY (optional) ---
if [ -n "${OPENAI_API_KEY:-}" ]; then
    echo "  OPENAI_API_KEY = [Set in env] (optional)"
    write_env_var "OPENAI_API_KEY" "$OPENAI_API_KEY"
elif grep -q "^OPENAI_API_KEY=" .env 2>/dev/null; then
    echo "  OPENAI_API_KEY = [Set in .env] (optional)"
else
    echo "  OPENAI_API_KEY = [Not Set] (optional — only needed for Codex CLI)"
    set +e
    read -r -p "  Do you have an OpenAI API key? [y/N] " has_key
    set -e
    if [[ "$has_key" =~ ^[Yy] ]]; then
        read -r -s -p "  Enter OpenAI API key: " openai_key
        echo
        if [ -n "$openai_key" ]; then
            write_env_var "OPENAI_API_KEY" "$openai_key"
            echo "  Saved."
        fi
    fi
fi

echo ""

echo "--- 4. Environment Variables (.envrc) ---"

# Parsing AWS profiles (supplies the default for the prompt below)
profiles=""
if [ -f "$HOME/.aws/config" ]; then
    # Extract profile names without brackets
    profiles=$(grep '\[profile ' "$HOME/.aws/config" | sed 's/\[profile //' | sed 's/\]//')
fi

# Find SSO profiles
sso_profiles=$(echo "$profiles" | grep -i 'sso' || true)

# Prioritize "dev" over others
default_profile=$(echo "$sso_profiles" | grep -i 'dev' | head -n 1)

# If no "dev" profile, take the first SSO profile broadly
if [ -z "$default_profile" ]; then
    default_profile=$(echo "$sso_profiles" | head -n 1)
fi

# Fallback if nothing matched
if [ -z "$default_profile" ]; then
    default_profile="default"
fi

if [ -n "$profiles" ]; then
    echo "Found Available AWS Profiles in ~/.aws/config:"
    while IFS= read -r profile; do
        echo "  - ${profile}"
    done <<< "$profiles"
    echo
fi

# Re-enable reading safely
set +e

# 1. GitHub org or user this harness works against.
# Drives `task repos:clone` (what gets cloned into repos/) and the
# `github-search` skill (`gh search code --owner`). The harness ships pointing at
# nobody's repositories on purpose, so there is no built-in default.
default_org=""
if command -v gh >/dev/null 2>&1; then
    default_org=$(gh api user --jq .login 2>/dev/null || echo "")
fi

read -r -p "Enter your GitHub org or username (BROWNFIELD_ORG) [$default_org]: " INPUT_BROWNFIELD_ORG
BROWNFIELD_ORG=${INPUT_BROWNFIELD_ORG:-$default_org}

# 2. AWS Profile
read -r -p "Select AWS_PROFILE [$default_profile]: " INPUT_AWS_PROFILE
AWS_PROFILE=${INPUT_AWS_PROFILE:-$default_profile}

# 3. Redshift User
read -r -p "Select AWS_REDSHIFT_DB_USER (blank to skip): " INPUT_REDSHIFT_DB_USER
AWS_REDSHIFT_DB_USER=${INPUT_REDSHIFT_DB_USER:-}

# 4. Contact email
# Try to auto-detect from git config first
default_email=$(git config --global user.email 2>/dev/null || echo "")

while true; do
    read -r -p "Enter your email [$default_email]: " INPUT_USER_EMAIL
    USER_EMAIL=${INPUT_USER_EMAIL:-$default_email}

    # Structural check only — no organisation domain is enforced.
    if [[ "$USER_EMAIL" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]]; then
        break
    else
        echo -e "⚠️  \033[33mInvalid email format.\033[0m"
    fi
done

set -e

# Update .envrc
ENVRC_FILE=".envrc"
touch "$ENVRC_FILE"

# Function to replace or append env vars
update_var() {
    local key="$1"
    local val="$2"
    if [ -n "$val" ]; then
        if grep -q "^export $key=" "$ENVRC_FILE"; then
            grep -v "^export $key=" "$ENVRC_FILE" > "${ENVRC_FILE}.tmp"
            mv "${ENVRC_FILE}.tmp" "$ENVRC_FILE"
        fi
        echo "export $key=\"$val\"" >> "$ENVRC_FILE"
    fi
}

# Function to safely append literal blocks
append_block_if_missing() {
    local search_str="$1"
    local block="$2"
    if ! grep -q "$search_str" "$ENVRC_FILE"; then
        echo -e "\n$block" >> "$ENVRC_FILE"
    fi
}

# Load .env secrets (GH_TOKEN, COPILOT_GITHUB_TOKEN, GEMINI_API_KEY)
# Prepend dotenv so .envrc exports can override .env values if needed
if ! grep -qxF "dotenv" "$ENVRC_FILE"; then
    mkdir -p tmp
    echo "dotenv" > "tmp/.envrc_prepend_$$"
    cat "$ENVRC_FILE" >> "tmp/.envrc_prepend_$$"
    mv "tmp/.envrc_prepend_$$" "$ENVRC_FILE"
fi

update_var "BROWNFIELD_ORG" "$BROWNFIELD_ORG"
update_var "AWS_PROFILE" "$AWS_PROFILE"
update_var "AWS_REDSHIFT_DB_USER" "$AWS_REDSHIFT_DB_USER"
update_var "USER_EMAIL" "$USER_EMAIL"

# Ensure scripts directory is in PATH
if ! grep -q "^PATH_add scripts" "$ENVRC_FILE"; then
    echo "PATH_add scripts" >> "$ENVRC_FILE"
fi

echo
echo "✅ Successfully updated $ENVRC_FILE!"
if command -v direnv >/dev/null 2>&1; then
    direnv allow .
    echo "✅ direnv allow applied."
else
    echo "⚠️  IMPORTANT: Please run 'direnv allow' to apply these changes to your current terminal."
fi

# Final summary warnings for missing optional credentials
if ! grep -q "^GH_TOKEN=" .env 2>/dev/null; then
    echo
    echo -e "\033[33m⚠️  GH_TOKEN is not configured. All 'task gh:*' commands will fail.\033[0m"
    echo "  Fix: run 'gh auth login', then re-run 'task setup:env'."
fi

if [ -z "$BROWNFIELD_ORG" ]; then
    echo
    echo -e "\033[33m⚠️  BROWNFIELD_ORG is not set. 'task repos:clone' will refuse to run,\033[0m"
    echo -e "\033[33m   and the github-search skill will have to ask you for an org.\033[0m"
    echo "  Fix: re-run 'task setup:env', or export BROWNFIELD_ORG in .envrc."
else
    echo
    echo "Next: clone the repositories you want the agents to work on —"
    echo "  task repos:clone BROWNFIELD_REPOS=\"repo-a repo-b\""
    echo "  (BROWNFIELD_ORG=$BROWNFIELD_ORG is already set; add DRY_RUN=1 to preview.)"
fi
