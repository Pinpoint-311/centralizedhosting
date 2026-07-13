"""Panel data model.

Everything here is fleet *metadata* — town identity, resource references,
versions, job/audit records. No resident data, ever (ORCHESTRATOR_PLAN.md B1:
this registry doubles as the StateRAMP/FedRAMP authorization-boundary
inventory).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from orchestrator.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TenantStatus:
    PENDING = "pending"
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    SUSPENDED = "suspended"      # app up, read-only 503 banner (soft pause)
    OFFLINE = "offline"          # stack stopped; all data/PII/KMS retained
    FAILED = "failed"
    DECOMMISSIONED = "decommissioned"  # crypto-shred, irreversible


class Tenant(Base):
    """B1 — one row per town instance (silo tenancy: instance = jurisdiction)."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(63), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    subdomain: Mapped[str] = mapped_column(String(63), unique=True)
    custom_domain: Mapped[str | None] = mapped_column(String(255), default=None)
    region: Mapped[str] = mapped_column(String(32), default="us")
    plan: Mapped[str] = mapped_column(String(32), default="standard")
    status: Mapped[str] = mapped_column(String(24), default=TenantStatus.PENDING, index=True)

    # Primary contact for the municipality (billing / escalation / support).
    contact_name: Mapped[str | None] = mapped_column(String(255), default=None)
    contact_email: Mapped[str | None] = mapped_column(String(255), default=None)
    contact_phone: Mapped[str | None] = mapped_column(String(64), default=None)
    contact_title: Mapped[str | None] = mapped_column(String(128), default=None)
    address: Mapped[str | None] = mapped_column(Text, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    # Optional location for the state map view (decimal degrees; metadata only).
    latitude: Mapped[float | None] = mapped_column(default=None)
    longitude: Mapped[float | None] = mapped_column(default=None)

    # Who provides each assignable API key (service_id -> "state"|"town").
    # Overrides on top of key_catalog defaults; set once, honored thereafter.
    key_assignments: Mapped[dict] = mapped_column(JSON, default=dict)

    # Versions (B3). running_version is what the fleet poller last observed;
    # target_version is what the panel deployed.
    running_version: Mapped[str | None] = mapped_column(String(64), default=None)
    target_version: Mapped[str | None] = mapped_column(String(64), default=None)

    # Platform resource references (metadata only — the resources themselves
    # live in the state's cloud accounts).
    db_name: Mapped[str | None] = mapped_column(String(63), default=None)
    kms_key_ref: Mapped[str | None] = mapped_column(String(255), default=None)
    storage_bucket: Mapped[str | None] = mapped_column(String(255), default=None)
    backend_port: Mapped[int | None] = mapped_column(Integer, default=None)
    frontend_port: Mapped[int | None] = mapped_column(Integer, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    secrets: Mapped[list["PlatformSecret"]] = relationship(back_populates="tenant")

    @property
    def external_host(self) -> str:
        from orchestrator.config import settings

        return self.custom_domain or f"{self.subdomain}.{settings.base_domain}"


class ProvisionJob(Base):
    """B2 — one provisioning run. Re-runnable; steps are individually idempotent."""

    __tablename__ = "provision_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="running")  # running|succeeded|failed
    error: Mapped[str | None] = mapped_column(Text, default=None)
    onboarding_link: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    steps: Mapped[list["ProvisionStep"]] = relationship(
        back_populates="job", order_by="ProvisionStep.position"
    )


class ProvisionStep(Base):
    __tablename__ = "provision_steps"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("provision_jobs.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="pending")  # pending|done|skipped|failed
    detail: Mapped[str | None] = mapped_column(Text, default=None)

    job: Mapped[ProvisionJob] = relationship(back_populates="steps")


class PlatformSecret(Base):
    """B5 — platform-managed secrets only, encrypted at rest with the panel key.

    Tenant-managed keys (AI/translation/identity/SMTP/branding) never touch
    this table — orchestrator.secrets_policy enforces the split.
    """

    __tablename__ = "platform_secrets"
    __table_args__ = (UniqueConstraint("tenant_id", "key_name"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    key_name: Mapped[str] = mapped_column(String(128))
    encrypted_value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    tenant: Mapped[Tenant] = relationship(back_populates="secrets")


class StateCredential(Base):
    """Shared state credential pool — entered once, injected into every town
    whose key-responsibility matrix sets the owning service to ``state_shared``.
    Encrypted at rest with the panel key; write-only (never returned)."""

    __tablename__ = "state_credentials"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    key_name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    encrypted_value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Release(Base):
    """B3 — a published, versioned app image plus its DB compatibility stamp."""

    __tablename__ = "releases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    version: Mapped[str] = mapped_column(String(64), unique=True)
    backend_image: Mapped[str] = mapped_column(String(255))
    frontend_image: Mapped[str] = mapped_column(String(255))
    # Immutable content digests (sha256:...). When set, stacks pin the image by
    # digest instead of the mutable tag — the government-correct supply-chain
    # posture (verifiable, tamper-evident, no "latest" drift).
    backend_digest: Mapped[str | None] = mapped_column(String(80), default=None)
    frontend_digest: Mapped[str | None] = mapped_column(String(80), default=None)
    db_revision: Mapped[str | None] = mapped_column(String(64), default=None)
    # Oldest Alembic revision this build can run against (expand/contract rule).
    min_db_revision: Mapped[str | None] = mapped_column(String(64), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    published_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RolloutStatus:
    PENDING = "pending"
    CANARY = "canary"
    CANARY_PASSED = "canary_passed"
    PROMOTING = "promoting"
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class Rollout(Base):
    __tablename__ = "rollouts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    release_id: Mapped[str] = mapped_column(ForeignKey("releases.id"))
    status: Mapped[str] = mapped_column(String(24), default=RolloutStatus.PENDING)
    canary_count: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    release: Mapped[Release] = relationship()
    steps: Mapped[list["RolloutStep"]] = relationship(
        back_populates="rollout", order_by="RolloutStep.position"
    )


class RolloutStep(Base):
    __tablename__ = "rollout_steps"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    rollout_id: Mapped[str] = mapped_column(ForeignKey("rollouts.id"), index=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    position: Mapped[int] = mapped_column(Integer)
    phase: Mapped[str] = mapped_column(String(16))  # canary|fleet
    status: Mapped[str] = mapped_column(String(24), default="pending")
    # pending|upgrading|healthy|unverified|failed|rolled_back
    previous_version: Mapped[str | None] = mapped_column(String(64), default=None)
    detail: Mapped[str | None] = mapped_column(Text, default=None)

    rollout: Mapped[Rollout] = relationship(back_populates="steps")
    tenant: Mapped[Tenant] = relationship()


class TelemetrySnapshot(Base):
    """B4 — sanitized (PII-scrubbed, metadata-only) telemetry per poll."""

    __tablename__ = "telemetry_snapshots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reachable: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[str | None] = mapped_column(String(64), default=None)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class BreakGlassGrant(Base):
    """B6/A8 — time-boxed, audited state-ops access. Token is shown once."""

    __tablename__ = "break_glass_grants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    actor: Mapped[str] = mapped_column(String(255))
    reason: Mapped[str] = mapped_column(Text)
    token_id: Mapped[str] = mapped_column(String(32), unique=True, default=_uuid)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    """B6 — central audit of every provisioning/rollout/secret/support action."""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    actor: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(32), index=True, default=None)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
