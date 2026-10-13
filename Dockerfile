# syntax=docker/dockerfile:1
# The atlas as one image: the API and the built page, and no data.
# The store is mounted read-only at /store; see docker-compose.prod.yml.

FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY atlas ./atlas
RUN uv pip install --system --no-cache .
COPY --from=web /web/dist ./web/dist
RUN useradd --system --uid 1001 atlas && mkdir -p /var/lib/atlas && chown atlas /var/lib/atlas
USER atlas
ENV ATLAS_STORE=/store \
    ATLAS_WEB_DIST=/app/web/dist \
    ATLAS_USAGE_DB=/var/lib/atlas/ask_usage.sqlite \
    PYTHONUNBUFFERED=1
EXPOSE 8099
# /api/meta reads the store, so a missing or broken mount reads as unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8099/api/meta', timeout=4)"
# One process: the API's DuckDB instance and hit-profile cache are per process by design.
CMD ["uvicorn", "atlas.serve:app", "--host", "0.0.0.0", "--port", "8099"]
