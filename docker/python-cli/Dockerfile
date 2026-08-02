FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy scripts for default availability
COPY scripts/ /app/scripts/

# Install Git CLI (no gh CLI — python-cli is strictly Python-gated)
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set python path
ENV PYTHONPATH=/app:/app/src

# Non-root agent user
RUN groupadd -r agent && useradd -r -g agent -m agent \
    && chown agent:agent /app \
    && git config --system --add safe.directory '*'

# Restricted entrypoint (root-owned, 0755 — agent cannot overwrite)
COPY docker/shared/python-gate-entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chown root:root /usr/local/bin/entrypoint.sh \
    && chmod 0755 /usr/local/bin/entrypoint.sh

ENV RUFF_CACHE_DIR=/tmp/.ruff_cache
ENV PYTHONPYCACHEPREFIX=/app/tmp/.pycache
USER agent
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
