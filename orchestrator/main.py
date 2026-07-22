from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

from orchestrator import __version__
from orchestrator.api import (
    admin,
    analytics_api,
    audit_api,
    auth_sso,
    backups as backups_api,
    fleet,
    gis,
    insights_api,
    offload,
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

    tasks: list = []
    if settings.alert_poll_seconds and settings.alert_poll_seconds > 0:
        async def _alert_loop():
            from orchestrator.db import SessionLocal
            from orchestrator import audit, insights

            while True:
                await asyncio.sleep(settings.alert_poll_seconds)
                try:
                    with SessionLocal() as db:
                        insights.evaluate_alerts(db)
                        # Tamper-anchor the audit chain to stdout for off-host
                        # aggregation (uniform with the app's periodic anchor).
                        audit.anchor_chain(db)
                        db.commit()
                except Exception:
                    pass  # never let the background loop crash the app

        tasks.append(asyncio.create_task(_alert_loop()))

    if settings.telemetry_poll_seconds and settings.telemetry_poll_seconds > 0:
        async def _telemetry_loop():
            from orchestrator.db import SessionLocal
            from orchestrator.api.fleet import poll_all_telemetry

            while True:
                await asyncio.sleep(settings.telemetry_poll_seconds)
                try:
                    # Poll in a worker thread so the blocking HTTP calls don't
                    # stall the event loop.
                    await asyncio.to_thread(_run_telemetry_poll, SessionLocal)
                except Exception:
                    pass  # never let the background loop crash the app

        def _run_telemetry_poll(SessionLocal):
            with SessionLocal() as db:
                poll_all_telemetry(db)

        tasks.append(asyncio.create_task(_telemetry_loop()))

    if settings.backups_enabled and settings.backup_poll_seconds and settings.backup_poll_seconds > 0:
        async def _backup_loop():
            from orchestrator.db import SessionLocal
            from orchestrator import backups

            def _run(SessionLocal):
                with SessionLocal() as db:
                    backups.backup_all(db)

            while True:
                await asyncio.sleep(settings.backup_poll_seconds)
                try:
                    # pg_basebackup is blocking + slow; keep it off the event loop.
                    await asyncio.to_thread(_run, SessionLocal)
                except Exception:
                    pass  # never let the background loop crash the app

        tasks.append(asyncio.create_task(_backup_loop()))

    yield

    for task in tasks:
        task.cancel()


def _init_sentry() -> None:
    """Optional error monitoring — uniform with the app (SENTRY_DSN, ENVIRONMENT;
    send_default_pii=False). No-op if the DSN or SDK is absent."""
    import os

    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=dsn, environment=os.getenv("ENVIRONMENT", "production"),
                        send_default_pii=False, traces_sample_rate=0.1)
    except Exception:  # noqa: BLE001 — never let monitoring setup break startup
        pass


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline security response headers — same set as the app's middleware."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith(("/api/docs", "/api/redoc", "/docs", "/redoc")):
            return response
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(self), camera=(), microphone=(), payment=(), usb=()")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store, max-age=0")
        return response


def create_app() -> FastAPI:
    _init_sentry()

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

    # Rate limiting — uniform with the app (SlowAPI, per-client). RATE_LIMIT_RPM
    # tunes the per-minute ceiling.
    from orchestrator.config import settings as _settings

    limiter = Limiter(key_func=get_remote_address,
                      default_limits=[f"{_settings.rate_limit_rpm}/minute"])
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    app.include_router(tenants.router)
    app.include_router(secrets.router)
    app.include_router(keys.router)
    app.include_router(state_credentials.router)
    app.include_router(releases.router)
    app.include_router(fleet.router)
    app.include_router(gis.router)
    app.include_router(auth_sso.router)
    app.include_router(offload.router)
    app.include_router(backups_api.router)
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
