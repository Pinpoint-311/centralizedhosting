"""Pinpoint 311 orchestrator — the state-hosted control plane.

Implements Part B of the app repo's docs/ORCHESTRATOR_PLAN.md:

- B1 tenant registry        -> orchestrator.models.Tenant (+ /api/tenants)
- B2 provisioner            -> orchestrator.provisioner
- B3 release management     -> orchestrator.rollout (+ /api/releases, /api/rollouts)
- B4 fleet dashboard        -> orchestrator.api.fleet (+ telemetry sanitizer)
- B5 secrets brokering      -> orchestrator.secrets_policy (+ /api/tenants/*/secrets)
- B6 break-glass/compliance -> orchestrator.api.breakglass + orchestrator.audit

The panel depends on the app only by container image tag and its
provisioning/telemetry API (orchestrator.app_client) — never by source,
and it never touches resident data.
"""

__version__ = "0.1.0"
