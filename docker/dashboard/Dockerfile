# Stage 1: Build frontend SPA
FROM node:22-alpine AS frontend-build
WORKDIR /build
COPY services/dashboard/frontend/package.json services/dashboard/frontend/package-lock.json* ./
RUN npm ci
COPY services/dashboard/frontend/ .
RUN npm run build

# Stage 2: Python runtime
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 1000 agent && \
    useradd --uid 1000 --gid agent --create-home agent

WORKDIR /app

COPY requirements.txt /app/requirements.txt
COPY services/dashboard/requirements.txt /app/services/dashboard/requirements.txt
RUN pip install --no-cache-dir -r /app/services/dashboard/requirements.txt

COPY src/ /app/src/
COPY services/ /app/services/
COPY workflows/ /app/workflows/

COPY --from=frontend-build /static /app/services/dashboard/static

ENV PYTHONPATH=/app:/app/src:/app/workflows/agent-memory/skills/execution-ledger/scripts

EXPOSE 8484

COPY docker/dashboard/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER agent

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "services.dashboard.app:app", "--host", "0.0.0.0", "--port", "8484"]
