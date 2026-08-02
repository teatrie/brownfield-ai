FROM python:3.12-slim

WORKDIR /app

# Install system deps, Node.js 24, Docker CLI + Compose Plugin, gh CLI
RUN apt-get update && \
    apt-get install -y curl gnupg git ca-certificates awscli jq && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL \
      https://download.docker.com/linux/debian/gpg \
      -o /etc/apt/keyrings/docker.asc && \
    chmod a+r /etc/apt/keyrings/docker.asc && \
    echo \
      "deb [arch=$(dpkg --print-architecture) \
      signed-by=/etc/apt/keyrings/docker.asc] \
      https://download.docker.com/linux/debian/ \
      $(. /etc/os-release && echo "$VERSION_CODENAME") \
      stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null && \
    curl -fsSL \
      https://cli.github.com/packages/githubcli-archive-keyring.gpg | \
      dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    chmod go+r \
      /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo \
      "deb [arch=$(dpkg --print-architecture) \
      signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] \
      https://cli.github.com/packages stable main" | \
      tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    curl -fsSL https://deb.nodesource.com/setup_24.x | bash - && \
    apt-get update && \
    apt-get install -y nodejs docker-ce-cli docker-compose-plugin gh && \
    rm -rf /var/lib/apt/lists/*

# Install agent CLIs (copilot, gemini) via npm
RUN npm install -g \
    @github/copilot \
    @google/gemini-cli

# Install base script dependencies
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install testing dependencies
COPY tests/requirements.txt ./tests/requirements.txt
RUN pip install --no-cache-dir -r tests/requirements.txt

ENV PYTHONPATH=/app:/app/src

# Non-root agent user (GID 0 supplementary group for docker.sock access
# on Docker Desktop where the socket is owned by root:root)
RUN groupadd -r agent \
    && useradd -r -g agent -G 0 -m agent \
    && chown agent:agent /app

# Restricted entrypoint (root-owned, 0755 — agent cannot overwrite)
COPY docker/shared/python-gate-entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chown root:root /usr/local/bin/entrypoint.sh \
    && chmod 0755 /usr/local/bin/entrypoint.sh

ENV RUFF_CACHE_DIR=/tmp/.ruff_cache
ENV PYTHONPYCACHEPREFIX=/app/tmp/.pycache
USER agent
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["pytest", "--help"]
