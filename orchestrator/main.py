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
    platform,
    releases,
    requests_api,
    providers as providers_api,
    secrets,
    state_credentials,
    status_api,
    tenants,
    users,
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
            from orchestrator import audit, cluster, insights

            while True:
                await asyncio.sleep(settings.alert_poll_seconds)
                try:
                    with SessionLocal() as db:
                        # Exactly one process runs this pass; see cluster.py.
                        if not cluster.acquire(db, "alert_loop"):
                            continue
                        insights.evaluate_alerts(db)
                        # Tamper-anchor the audit chain to stdout for off-host
                        # aggregation (uniform with the app's periodic anchor).
                        audit.anchor_chain(db)
                        # Leading-indicator scan — surface warning/critical checks
                        # to stdout so off-host monitoring alerts early (the
                        # control-plane analogue of the app's admin email).
                        import logging

                        from orchestrator import proactive_health

                        result = proactive_health.evaluate(db)
                        for c in result["checks"]:
                            if c["status"] in ("warning", "critical"):
                                logging.getLogger("proactive").warning(
                                    "[PROACTIVE] %s %s: %s %s",
                                    c["status"].upper(), c["label"], c["message"], c["action"],
                                )
                        # Record an uptime sample so the history/stats the app's
                        # panel shows accumulate on their own, not only when an
                        # operator presses "Check Now".
                        from orchestrator.api.platform import trigger_uptime_check

                        trigger_uptime_check(db=db, _="system")
                        db.commit()
                except Exception:
                    pass  # never let the background loop crash the app

        tasks.append(asyncio.create_task(_alert_loop()))

    if settings.telemetry_poll_seconds and settings.telemetry_poll_seconds > 0:
        async def _telemetry_loop():
            from orchestrator import cluster
            from orchestrator.db import SessionLocal
            from orchestrator.api.fleet import poll_all_telemetry

            while True:
                await asyncio.sleep(settings.telemetry_poll_seconds)
                try:
                    with SessionLocal() as db:
                        if not cluster.acquire(db, "telemetry_loop"):
                            continue
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
            from orchestrator import backups, cluster

            def _run(SessionLocal):
                with SessionLocal() as db:
                    backups.backup_all(db)

            while True:
                await asyncio.sleep(settings.backup_poll_seconds)
                try:
                    with SessionLocal() as db:
                        # Without this every worker would back up every town.
                        if not cluster.acquire(db, "backup_loop"):
                            continue
                    # pg_basebackup is blocking + slow; keep it off the event loop.
                    await asyncio.to_thread(_run, SessionLocal)
                except Exception:
                    pass  # never let the background loop crash the app

        tasks.append(asyncio.create_task(_backup_loop()))

    yield

    for task in tasks:
        task.cancel()

    # Hand the leases back so another process picks the work up at once rather
    # than waiting out the TTL.
    if tasks:
        from orchestrator import cluster
        from orchestrator.db import SessionLocal

        with SessionLocal() as db:
            for lease in ("alert_loop", "telemetry_loop", "backup_loop"):
                cluster.release(db, lease)


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

    # Storage: in-memory means the ceiling is PER PROCESS, so N workers allow
    # N times the configured rate. Set REDIS_URL to share one counter across
    # workers and replicas; without it the panel must stay single-process for
    # the limit to mean what it says.
    import os as _os

    _redis_url = _os.getenv("REDIS_URL", "").strip()
    _limiter_kwargs = {"storage_uri": _redis_url} if _redis_url else {}
    limiter = Limiter(key_func=get_remote_address,
                      default_limits=[f"{_settings.rate_limit_rpm}/minute"],
                      **_limiter_kwargs)
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
    app.include_router(users.router)
    app.include_router(providers_api.router)
    app.include_router(offload.router)
    app.include_router(backups_api.router)
    app.include_router(platform.router)
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
        """Non-sensitive fleet config for the UI (base domain, mode, branding).
        No auth — the SPA needs it before the token gate, and branding shows on
        the login screen."""
        from orchestrator.config import settings
        from orchestrator.api.platform import branding
        from orchestrator.db import SessionLocal

        with SessionLocal() as db:
            brand = branding(db)

        regions = [r.strip() for r in settings.regions.split(",") if r.strip()]
        return {
            **brand,
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
