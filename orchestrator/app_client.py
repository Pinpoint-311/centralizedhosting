"""HTTP client for a town instance's control-plane surface.

This is the ONLY coupling between panel and app: the contract endpoints from
ORCHESTRATOR_PLAN.md (the panel never imports app source):

- A3  GET  /api/health/quick        -> {version, git_sha, db_revision, min_db_revision}
- A4  POST /api/provisioning/bootstrap  (PROVISIONING_TOKEN header)
       -> sets township name/domain, creates initial admin,
          returns a one-time onboarding link
- A4  POST /api/provisioning/lifecycle  -> suspend / resume
- A5  GET  /api/telemetry           (panel token) -> metadata-only counters
"""

from typing import Any

import httpx

from orchestrator.config import settings

PROVISIONING_TOKEN_HEADER = "X-Provisioning-Token"
PANEL_TOKEN_HEADER = "X-Panel-Token"


class AppClient:
    def __init__(
        self,
        base_url: str,
        provisioning_token: str | None = None,
        panel_token: str | None = None,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.provisioning_token = provisioning_token
        self.panel_token = panel_token
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout or settings.telemetry_timeout_seconds,
            transport=transport,
        )

    # ---- A3: version/migration stamp (canary gating) -----------------------
    def health_version(self) -> dict[str, Any]:
        resp = self._client.get("/api/health/quick")
        resp.raise_for_status()
        return resp.json()

    # ---- A4: non-interactive provisioning ----------------------------------
    def bootstrap(self, township_name: str, domain: str, admin_email: str) -> dict[str, Any]:
        resp = self._client.post(
            "/api/provisioning/bootstrap",
            headers={PROVISIONING_TOKEN_HEADER: self.provisioning_token or ""},
            json={
                "township_name": township_name,
                "domain": domain,
                "admin_email": admin_email,
            },
        )
        resp.raise_for_status()
        return resp.json()  # includes {"onboarding_link": ...}

    def set_lifecycle(self, state: str) -> dict[str, Any]:
        resp = self._client.post(
            "/api/provisioning/lifecycle",
            headers={PROVISIONING_TOKEN_HEADER: self.provisioning_token or ""},
            json={"state": state},  # "suspended" | "active"
        )
        resp.raise_for_status()
        return resp.json()

    def set_managed_settings(self, settings: dict) -> dict[str, Any]:
        """Push the state-set policy (retention, legal hold, security posture)
        the town applies + shows read-only in managed mode."""
        resp = self._client.post(
            "/api/provisioning/managed-settings",
            headers={PROVISIONING_TOKEN_HEADER: self.provisioning_token or ""},
            json={"settings": settings},
        )
        resp.raise_for_status()
        return resp.json()

    # ---- A5: PII-safe telemetry ---------------------------------------------
    def telemetry(self) -> dict[str, Any]:
        resp = self._client.get(
            "/api/telemetry",
            headers={PANEL_TOKEN_HEADER: self.panel_token or ""},
        )
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        self._client.close()


def client_for_tenant(tenant, **kwargs) -> AppClient:
    """Panel reaches town backends on their loopback port of the managed host
    (MVP compose shape). Swap base_url derivation when moving to k8s."""
    base_url = f"http://127.0.0.1:{tenant.backend_port}"
    return AppClient(base_url, **kwargs)
