from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from orchestrator import __version__
from orchestrator.api import (
    admin,
    analytics_api,
    audit_api,
    breakglass,
    fleet,
    gis,
    insights_api,
    keys,
    managed_api,
    releases,
    requests_api,
    secrets,
    state_credentials,
    status_api,
    tenants,
)
from orchestrator.db import init_db


@asynccontextmanager
async def _lifespan(app: FastAPI):
    import asyncio

    init_db()

    from orchestrator.config import settings

    task = None
    if settings.alert_poll_seconds and settings.alert_poll_seconds > 0:
        async def _alert_loop():
            from orchestrator.db import SessionLocal
            from orchestrator import insights

            while True:
                await asyncio.sleep(settings.alert_poll_seconds)
                try:
                    with SessionLocal() as db:
                        insights.evaluate_alerts(db)
                except Exception:
                    pass  # never let the background loop crash the app

        task = asyncio.create_task(_alert_loop())

    yield

    if task:
        task.cancel()


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
    app.include_router(keys.router)
    app.include_router(state_credentials.router)
    app.include_router(releases.router)
    app.include_router(fleet.router)
    app.include_router(gis.router)
    app.include_router(breakglass.router)
    app.include_router(audit_api.router)
    app.include_router(admin.router)
    app.include_router(insights_api.router)
    app.include_router(requests_api.router)
    app.include_router(managed_api.router)
    app.include_router(analytics_api.router)
    app.include_router(status_api.router)

    @app.get("/healthz", tags=["meta"])
    def healthz():
        return {"status": "ok", "version": __version__}

    @app.get("/api/panel-config", tags=["meta"])
    def panel_config():
        """Non-sensitive fleet config for the UI (base domain, mode). No auth —
        the base domain is public and the SPA needs it before the token gate."""
        from orchestrator.config import settings

        regions = [r.strip() for r in settings.regions.split(",") if r.strip()]
        return {
            "base_domain": settings.base_domain,
            "backend_image": settings.backend_image,
            "frontend_image": settings.frontend_image,
            "region_label": settings.region_label,
            "regions": regions,
            "public_requests_enabled": settings.public_requests_enabled,
            # Referrer-restricted Maps JS key for the State Map (public by design).
            "maps_api_key": settings.maps_api_key,
            "maps_map_id": settings.maps_map_id,
            "version": __version__,
        }

    # Serve the built panel SPA (panel-ui/dist) when present; otherwise fall
    # back to the minimal single-file dashboard so the panel is never blank.
    static_dir = Path(__file__).parent / "static"
    spa_index = static_dir / "index.html"
    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
    def spa(full_path: str = ""):
        # API routes are matched before this catch-all; everything else serves
        # the SPA shell so client-side routing (deep links) works on refresh.
        if full_path.startswith(("api/", "assets/", "healthz")):
            raise HTTPException(status_code=404, detail="Not found")
        if spa_index.exists():
            return spa_index.read_text()
        return (static_dir / "dashboard.html").read_text()

    return app


app = create_app()
