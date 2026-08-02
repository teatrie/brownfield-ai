FROM debian:bookworm-slim

WORKDIR /app

# Install git and GitHub CLI via official apt repository
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        openssh-client \
        git \
        curl \
        gpg \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Non-root agent user
RUN groupadd -r agent && useradd -r -g agent -m agent \
    && chown agent:agent /app

# Security-critical entrypoint and sparse-clone helper (root-owned, 0755)
COPY docker/repo-cli/entrypoint.sh /entrypoint.sh
COPY docker/repo-cli/sparse-clone.sh /usr/local/bin/sparse-clone.sh
RUN chown root:root /entrypoint.sh /usr/local/bin/sparse-clone.sh \
    && chmod 0755 /entrypoint.sh /usr/local/bin/sparse-clone.sh

USER agent
ENTRYPOINT ["/entrypoint.sh"]
