"""Central compliance audit trail (B6): every provisioning, rollout, secret,
lifecycle, and break-glass action lands here. Detail payloads are metadata
only — never secret values, never resident data."""

from sqlalchemy.orm import Session

from orchestrator.models import AuditLog


def record(
    db: Session,
    actor: str,
    action: str,
    tenant_id: str | None = None,
    **detail,
) -> AuditLog:
    entry = AuditLog(actor=actor, action=action, tenant_id=tenant_id, detail=detail)
    db.add(entry)
    db.flush()
    return entry
