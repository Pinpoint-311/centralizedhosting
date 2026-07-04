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

EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8100/healthz || exit 1

CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8100"]
