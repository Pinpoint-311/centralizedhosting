# ---- Stage 1: build the panel SPA -------------------------------------------
FROM node:22-slim AS ui
WORKDIR /ui
COPY panel-ui/package.json panel-ui/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY panel-ui/ ./
# Vite's outDir points at ../orchestrator/static; redirect it here for the copy.
RUN npm run build -- --outDir dist --emptyOutDir

# ---- Stage 2: python runtime ------------------------------------------------
FROM python:3.11-slim

WORKDIR /panel

# Docker CLI + compose plugin so the panel can apply per-town stacks on the
# managed host (APPLY_STACKS=true). Render-only deployments can drop this.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates docker.io docker-compose-v2 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY orchestrator ./orchestrator
RUN pip install --no-cache-dir .

# Drop the built SPA into the static dir the app serves (alongside the
# committed dashboard.html fallback).
COPY --from=ui /ui/dist/ ./orchestrator/static/

EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8100/healthz || exit 1

CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8100"]
