import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class TenantContact(BaseModel):
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    contact_title: str | None = None
    address: str | None = None
    notes: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class TenantCreate(TenantContact):
    name: str = Field(min_length=1, max_length=255)
    slug: str
    custom_domain: str | None = None
    region: str = "us"
    plan: str = "standard"
    tags: list[str] = Field(default_factory=list)
    # Optional initial key-responsibility overrides (service_id -> state|town)
    key_assignments: dict[str, str] = Field(default_factory=dict)

    @field_validator("slug")
    @classmethod
    def valid_slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not _SLUG_RE.match(v) or v.startswith("_"):
            raise ValueError("slug must be a DNS-safe label (lowercase, digits, hyphens)")
        return v


class TenantUpdate(TenantContact):
    """Editable metadata after creation (domain + contacts)."""

    name: str | None = Field(default=None, max_length=255)
    custom_domain: str | None = None
    region: str | None = None
    plan: str | None = None
    tags: list[str] | None = None


class BulkTenantCreate(BaseModel):
    tenants: list[TenantCreate]


class BulkResultRow(BaseModel):
    slug: str
    ok: bool
    id: str | None = None
    error: str | None = None


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str | None
    tenant_slug: str | None
    kind: str
    severity: str
    message: str
    created_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: str | None


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    subdomain: str
    custom_domain: str | None
    region: str
    plan: str
    status: str
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    contact_title: str | None
    address: str | None
    notes: str | None
    latitude: float | None
    longitude: float | None
    tags: list = []
    key_assignments: dict = {}
    running_version: str | None
    target_version: str | None
    db_name: str | None
    kms_key_ref: str | None
    storage_bucket: str | None
    backend_port: int | None
    frontend_port: int | None
    created_at: datetime
    updated_at: datetime


class ProvisionStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int
    name: str
    status: str
    detail: str | None


class ProvisionJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    status: str
    error: str | None
    onboarding_link: str | None
    created_at: datetime
    finished_at: datetime | None
    steps: list[ProvisionStepOut] = []


class KeyCatalogOut(BaseModel):
    assignable: list[dict]
    infrastructure: list[str]
    infrastructure_prefixes: list[str]
    owners: list[str]


class TenantKeyAssignments(BaseModel):
    assignments: dict[str, str]


class KeyAssignmentUpdate(BaseModel):
    assignments: dict[str, str]


class SecretWrite(BaseModel):
    value: str = Field(min_length=1)


class SecretOut(BaseModel):
    """Write-only brokering: the panel never returns secret values."""

    key_name: str
    updated_at: datetime


class ReleaseCreate(BaseModel):
    version: str = Field(min_length=1, max_length=64)
    backend_image: str | None = None
    frontend_image: str | None = None
    backend_digest: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    frontend_digest: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    db_revision: str | None = None
    min_db_revision: str | None = None
    notes: str | None = None


class ReleaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version: str
    backend_image: str
    frontend_image: str
    backend_digest: str | None
    frontend_digest: str | None
    db_revision: str | None
    min_db_revision: str | None
    notes: str | None
    published_at: datetime


class RolloutCreate(BaseModel):
    release_id: str
    canary_count: int | None = Field(default=None, ge=1)


class RolloutStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: str
    position: int
    phase: str
    status: str
    previous_version: str | None
    detail: str | None


class RolloutOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    release_id: str
    status: str
    canary_count: int
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    steps: list[RolloutStepOut] = []


class BreakGlassRequest(BaseModel):
    tenant_id: str
    actor: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=10)  # a real justification, audited
    minutes: int = Field(default=30, ge=1)


class BreakGlassOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    actor: str
    reason: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


class BreakGlassIssued(BreakGlassOut):
    token: str  # returned exactly once, never stored in plaintext


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    seq: int
    actor: str
    action: str
    tenant_id: str | None
    detail: dict
    created_at: datetime
    entry_hash: str
