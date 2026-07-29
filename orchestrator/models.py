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
    MIGRATING = "migrating"      # self-host bundle generated; town cutting over
    MIGRATED = "migrated"        # town live on its own infra; managed stack retired
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

    # Public municipal boundary as a GeoJSON FeatureCollection, sourced from
    # OpenStreetMap/Nominatim (same flow the app's admin console uses). Public
    # geography, never resident data — drawn as the town's polygon on the map.
    boundary: Mapped[dict | None] = mapped_column(JSON, default=None)

    # Free-form operator tags (cohort, pilot, …) for filtering.
    tags: Mapped[list] = mapped_column(JSON, default=list)

    # Region/county grouping (generic — the label is configurable via
    # REGION_LABEL; used to aggregate what towns are allowed to see about each
    # other at the region level rather than town-by-town).
    county: Mapped[str | None] = mapped_column(String(120), default=None, index=True)

    # State-set policy the town runs under in managed mode (retention, legal
    # hold, security posture, …). Keys defined in managed_settings.CATALOG.
    managed_settings: Mapped[dict] = mapped_column(JSON, default=dict)

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


class SystemSetting(Base):
    """Global key/value store for hosting-platform configuration — mirrors the
    Pinpoint 311 app's SystemSecret. Holds the selected cloud service providers
    (AI / translation / identity) and their credentials. Every value is envelope-
    encrypted at rest with the panel key; ``is_secret`` marks values that are
    never returned to the browser (only their "set" state is)."""

    __tablename__ = "system_settings"

    key_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_encrypted: Mapped[str] = mapped_column(Text)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


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


class TownRequest(Base):
    """Self-service hosting request from a municipality. Lands in a pending
    queue; an operator approves (→ creates a Tenant) or rejects. Public intake
    is opt-in via PUBLIC_REQUESTS_ENABLED."""

    __tablename__ = "town_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    ref_code: Mapped[str | None] = mapped_column(String(16), unique=True, default=None)
    name: Mapped[str] = mapped_column(String(255))
    requested_slug: Mapped[str | None] = mapped_column(String(63), default=None)
    county: Mapped[str | None] = mapped_column(String(120), default=None)
    contact_name: Mapped[str | None] = mapped_column(String(255), default=None)
    contact_email: Mapped[str | None] = mapped_column(String(255), default=None)
    contact_phone: Mapped[str | None] = mapped_column(String(64), default=None)
    message: Mapped[str | None] = mapped_column(Text, default=None)
    # Everything else the richer intake collects (population, technical contact,
    # current system, timeline, desired modules, key preferences, migration
    # needs, records/accessibility contact, terms acknowledgment).
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    key_preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(32), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    decided_by: Mapped[str | None] = mapped_column(String(150), default=None)


class ServiceCategory(Base):
    """Canonical, cross-town service taxonomy (seeded from Open311 codes).
    Local town categories map to these so analytics can roll up comparably."""

    __tablename__ = "service_categories"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(160))
    group: Mapped[str | None] = mapped_column(String(80), default=None)


class CategoryMapping(Base):
    """Maps a town's local category (code or name) to a canonical code."""

    __tablename__ = "category_mappings"
    __table_args__ = (UniqueConstraint("tenant_id", "local_key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    local_key: Mapped[str] = mapped_column(String(160))
    canonical_code: Mapped[str] = mapped_column(String(64))


class Announcement(Base):
    """Operator broadcast: maintenance windows / incidents shown on the public
    status page and (optionally) fleet-wide."""

    __tablename__ = "announcements"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text, default=None)
    severity: Mapped[str] = mapped_column(String(16), default="info")  # info|maintenance|incident
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(150), default=None)


class Alert(Base):
    """A fired monitoring alert (town down, version drift, cost spike, …).
    Open until acknowledged; the evaluator won't duplicate an open alert of the
    same (tenant, kind)."""

    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str | None] = mapped_column(String(32), index=True, default=None)
    tenant_slug: Mapped[str | None] = mapped_column(String(63), default=None)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # down|drift|cost_spike|cert_expiry
    severity: Mapped[str] = mapped_column(String(16), default="warning")  # info|warning|critical
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    acknowledged_by: Mapped[str | None] = mapped_column(String(150), default=None)


class AuditLog(Base):
    """B6 — central audit of every provisioning/rollout/secret/support action."""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    seq: Mapped[int] = mapped_column(Integer, index=True, default=0)
    actor: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(32), index=True, default=None)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    # Tamper-evident hash chain (each entry binds to the previous one).
    previous_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    entry_hash: Mapped[str] = mapped_column(String(64), default="")


class BackupRecord(Base):
    """Catalog of a town database backup (encrypted pg_dump → S3), uniform with
    the app's backup_service. Holds only the artifact's location, size, and
    status metadata — never resident data."""

    __tablename__ = "backup_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="dump")  # dump
    status: Mapped[str] = mapped_column(String(16), default="planned")  # planned|completed|failed
    path: Mapped[str | None] = mapped_column(Text, default=None)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class PlatformConfig(Base):
    """Singleton identity for the hosting provider itself — the entity running
    this control plane (a state, county, city, university, or agency). Branding
    + organization metadata only; never resident data. Distinct from a Tenant
    (a hosted municipality)."""

    __tablename__ = "platform_config"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="default")

    # Branding (how the panel presents itself).
    platform_name: Mapped[str | None] = mapped_column(String(120), default=None)
    tagline: Mapped[str | None] = mapped_column(String(160), default=None)
    logo_url: Mapped[str | None] = mapped_column(Text, default=None)
    primary_color: Mapped[str | None] = mapped_column(String(9), default=None)  # #RRGGBB
    support_email: Mapped[str | None] = mapped_column(String(255), default=None)

    # Organization (who the hosting provider is).
    org_legal_name: Mapped[str | None] = mapped_column(String(255), default=None)
    org_type: Mapped[str] = mapped_column(String(32), default="agency")  # state|county|city|university|agency|other
    jurisdiction: Mapped[str | None] = mapped_column(String(160), default=None)
    contact_name: Mapped[str | None] = mapped_column(String(255), default=None)
    contact_email: Mapped[str | None] = mapped_column(String(255), default=None)
    contact_phone: Mapped[str | None] = mapped_column(String(64), default=None)
    address: Mapped[str | None] = mapped_column(Text, default=None)
    website: Mapped[str | None] = mapped_column(String(255), default=None)

    # Document-retention configuration — same three fields as the app's
    # SystemSettings. Here they are the *state's* default policy, which seeds
    # the managed policy pushed down to each hosted town.
    retention_state_code: Mapped[str] = mapped_column(String(2), default="NJ")
    retention_days_override: Mapped[int | None] = mapped_column(Integer, default=None)
    retention_mode: Mapped[str] = mapped_column(String(20), default="anonymize")  # anonymize|delete

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(150), default=None)


class AuditAnchor(Base):
    """Periodic tamper-anchor of the audit hash chain — uniform with the app.

    Records the chain head (last entry_hash) + entry count at a point in time.
    The same head is also emitted to stdout as ``[AUDIT ANCHOR] head=… count=…``
    so external log aggregation captures it off-host, matching the app's daily
    anchor task."""

    __tablename__ = "audit_anchors"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    head: Mapped[str] = mapped_column(String(64))
    count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class FederationConfig(Base):
    """Singleton OIDC/SSO federation config for panel operator sign-in.

    The host enters their IdP credentials once (issuer, client id/secret) and
    maps IdP groups/roles to panel roles. The client secret is stored encrypted
    at rest via the panel's secret manager (security.encrypt_value → envelope
    encryption, KMS-wrapped or local). Non-secret fields are stored plainly.
    """

    __tablename__ = "federation_config"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="default")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String(40), default="oidc")  # label only
    issuer: Mapped[str | None] = mapped_column(String(512), default=None)  # OIDC discovery base
    client_id: Mapped[str | None] = mapped_column(String(255), default=None)
    client_secret_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
    # Which ID-token claim carries the operator's groups/roles.
    groups_claim: Mapped[str] = mapped_column(String(80), default="groups")
    # {group_value: panel_role}; highest matching role wins.
    group_role_map: Mapped[dict] = mapped_column(JSON, default=dict)
    # Role for an authenticated operator whose groups map to nothing.
    default_role: Mapped[str] = mapped_column(String(20), default="viewer")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(150), default=None)


class UptimeRecord(Base):
    """Records health check results over time for uptime monitoring dashboard.

    Ported from the app's UptimeRecord. The app tracks its own dependencies
    (auth0, KMS, Vertex…); the control plane tracks the components it actually
    owns — its database, secret encryption, and audit chain.
    """

    __tablename__ = "uptime_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_name: Mapped[str] = mapped_column(String(50), index=True)  # database, secret_encryption, …
    status: Mapped[str] = mapped_column(String(20))  # healthy, degraded, down
    response_time_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    error_message: Mapped[str | None] = mapped_column(String(500), default=None)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class User(Base):
    """A panel operator. Mirrors the Pinpoint 311 app's User model, adapted to
    the control plane: identity comes from SSO (matched by email) and mints the
    app-style JWT bearer, or — for the first admin / break-fix — a password.

    Per the operator's choice there is a single access level: every active user
    is admin-equivalent (``role`` defaults to ``admin`` and isn't user-editable),
    so the panel's existing RBAC guards all pass for any real user. The table
    exists so access is managed explicitly (add/remove operators) rather than
    auto-granted from IdP group membership.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255), default=None)
    hashed_password: Mapped[str | None] = mapped_column(String(255), default=None)  # None for SSO-only
    role: Mapped[str] = mapped_column(String(20), default="admin")  # single role
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    oidc_sub: Mapped[str | None] = mapped_column(String(255), unique=True, default=None)  # IdP subject
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
