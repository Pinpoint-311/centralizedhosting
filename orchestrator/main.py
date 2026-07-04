from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from orchestrator import __version__
from orchestrator.api import audit_api, breakglass, fleet, releases, secrets, tenants
from orchestrator.db import init_db


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Pinpoint 311 Orchestrator",
        description=(
            "Control plane for centrally hosted Pinpoint 311 fleets. Provisions "
            "towns, brokers platform-managed secrets, rolls out releases, and "
            "aggregates health metadata. Never touches resident data."
        ),
        version=__version__,
        lifespan=_lifespan,
    )

    app.include_router(tenants.router)
    app.include_router(secrets.router)
    app.include_router(releases.router)
    app.include_router(fleet.router)
    app.include_router(breakglass.router)
    app.include_router(audit_api.router)

    @app.get("/healthz", tags=["meta"])
    def healthz():
        return {"status": "ok", "version": __version__}

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard():
        return (Path(__file__).parent / "static" / "dashboard.html").read_text()

    return app


app = create_app()
