import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str
    custom_domain: str | None = None
    region: str = "us"
    plan: str = "standard"
    contact_name: str | None = None
    contact_email: str | None = None

    @field_validator("slug")
    @classmethod
    def valid_slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not _SLUG_RE.match(v) or v.startswith("_"):
            raise ValueError("slug must be a DNS-safe label (lowercase, digits, hyphens)")
        return v


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
    db_revision: str | None = None
    min_db_revision: str | None = None
    notes: str | None = None


class ReleaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version: str
    backend_image: str
    frontend_image: str
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
    actor: str
    action: str
    tenant_id: str | None
    detail: dict
    created_at: datetime
