"""Pinpoint 311 orchestrator — the state-hosted control plane.

Implements Part B of the app repo's docs/ORCHESTRATOR_PLAN.md:

- B1 tenant registry        -> orchestrator.models.Tenant (+ /api/tenants)
- B2 provisioner            -> orchestrator.provisioner
- B3 release management     -> orchestrator.rollout (+ /api/releases, /api/rollouts)
- B4 fleet dashboard        -> orchestrator.api.fleet (+ telemetry sanitizer)
- B5 secrets brokering      -> orchestrator.secrets_policy (+ /api/tenants/*/secrets)
- B6 compliance/audit       -> orchestrator.audit (tamper-evident hash chain)

The panel depends on the app only by container image tag and its
provisioning/telemetry API (orchestrator.app_client) — never by source.
It is air-gapped from resident data: it holds only metadata, and there is
no break-glass or any other path into a town's instance.
"""

__version__ = "0.1.0"
