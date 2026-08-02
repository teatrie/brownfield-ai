FROM node:24-slim

WORKDIR /app

# Layer 1: system deps
RUN apt-get update && apt-get install -y curl gnupg git ca-certificates bash jq && \
    rm -rf /var/lib/apt/lists/*

# Layer 2: gh CLI — add GPG key + apt repo, then install
RUN install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | \
        dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] \
https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    apt-get update && apt-get install -y gh && \
    rm -rf /var/lib/apt/lists/*

# Layer 3: npm global tools (changes most frequently — kept last for cache efficiency)
RUN npm install -g @github/copilot @google/gemini-cli @openai/codex

# Layer 4: embed scripts into container, root-owned, read-only for agent
COPY scripts/agent-cli/copilot-review.sh /usr/local/bin/copilot-review.sh
COPY scripts/agent-cli/gemini-review.sh /usr/local/bin/gemini-review.sh
COPY scripts/agent-cli/codex-review.sh /usr/local/bin/codex-review.sh
COPY scripts/agent-cli/preflight.sh /usr/local/bin/preflight.sh
COPY scripts/agent-cli/_review-common.sh /usr/local/bin/_review-common.sh
COPY docker/agent-cli/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chown root:root /usr/local/bin/copilot-review.sh \
        /usr/local/bin/gemini-review.sh \
        /usr/local/bin/codex-review.sh \
        /usr/local/bin/preflight.sh \
        /usr/local/bin/_review-common.sh \
        /usr/local/bin/entrypoint.sh \
    && chmod 0755 /usr/local/bin/copilot-review.sh \
        /usr/local/bin/gemini-review.sh \
        /usr/local/bin/codex-review.sh \
        /usr/local/bin/preflight.sh \
        /usr/local/bin/entrypoint.sh \
    && chmod 0644 /usr/local/bin/_review-common.sh

# Layer 5: non-root user
RUN groupadd -r agent && useradd -r -g agent -m agent && chown agent:agent /app
ENV NPM_CONFIG_CACHE=/app/tmp/.npm
ENV HOME=/home/agent

RUN install -d -m 0755 -o agent -g agent /home/agent/.codex
COPY --chown=agent:agent docker/agent-cli/codex-config.toml /home/agent/.codex/config.toml

USER agent
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
