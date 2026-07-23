# Government production readiness

Straight answers to "is this the right way to do it for government?" — what the
control plane does today, what's still required before a StateRAMP/FedRAMP-style
production deployment, and exactly where each concern lives in the code.

Read this as: **the architecture is right; several operational controls are
deliberately left to the deployment and are not yet enforced in code.** Don't
treat the panel as authorization-to-operate-ready as-is.

---

## 1. Where are the state's secrets stored?

Two kinds of secret, both in the **panel's own database** (`PANEL_DATABASE_URL`
— SQLite in dev, Postgres in production), **encrypted at rest**:

| Secret | Table | Notes |
|---|---|---|
| Shared state credentials (one value, many towns) | `state_credentials` | `orchestrator/api/state_credentials.py` |
| Per-town brokered secrets (infra + per-town state keys) | `platform_secrets` | one row per (tenant, key) |

Encryption: Fernet (AES-128-CBC + HMAC), key derived from `PANEL_SECRET_KEY`
(`orchestrator/security.py` → `_fernet()`). Values are **write-only** over the
API — no endpoint ever returns a stored secret, and audit records key *names*
only, never values.

**Town/resident secrets are NOT here.** Each town's `SECRET_KEY`, DB, and its
own tenant-owned provider keys live in that town's isolated instance. The panel
only ever holds *platform-managed* and *state-shared/per-town brokered* keys —
never resident data.

### Is that the right way for government? Partly — the gap:

`PANEL_SECRET_KEY` is a static, env-supplied key. That's fine for dev and
acceptable for a hardened single-host deploy, but **for government production
the panel's own secrets should be envelope-encrypted by a real KMS/HSM** (the
same pattern the app already uses for resident PII), not a static env var:

- **Recommended:** store `PANEL_SECRET_KEY` in — or wrap the DEK with — a
  FedRAMP/StateRAMP-authorized KMS (GCP Cloud KMS, AWS KMS, Azure Key Vault in
  the Gov cloud). `security.py._fernet()` is the single seam to swap to an
  envelope scheme.
- **Also:** enable Postgres TDE / encrypted volumes, restrict DB network access
  to the panel only, rotate `PANEL_SECRET_KEY` with re-encryption support.

**Secret encryption is now identical to the Pinpoint 311 app** — the panel
ports the app's crypto modules (`orchestrator/encryption.py`,
`orchestrator/pii_crypto.py`, `orchestrator/aws_kms.py`,
`orchestrator/azure_keyvault.py`) so both systems are set up and operated the
same way. A random 32-byte AES-256-GCM data key (DEK) encrypts each value; the
DEK is wrapped by the configured cloud KMS and only the wrapped DEK is stored
inside the self-describing `pii2:` token (the plaintext DEK never touches disk).
Rotate by rotating the cloud key (or switching provider) and running
`POST /api/maintenance/reencrypt-secrets` (Settings → "Re-encrypt secrets"),
which re-wraps every secret under a fresh DEK; the panel's earlier `v<n>:`
Fernet values remain readable.

**Set it up exactly like the app**, with the same environment variables:

| | env vars |
|---|---|
| Selector | `KMS_PROVIDER` = `google` (default) \| `azure` \| `aws`; `REQUIRE_KMS` = fail-closed |
| Google Cloud KMS/HSM | `GOOGLE_CLOUD_PROJECT`, `KMS_LOCATION`, `KMS_KEY_RING`, `KMS_KEY_ID` (+ `GCP_SERVICE_ACCOUNT_JSON` / `GOOGLE_APPLICATION_CREDENTIALS`) |
| AWS KMS/CloudHSM | `AWS_KMS_KEY_ID`, `AWS_REGION` (+ `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`) |
| Azure Key Vault | `AZURE_KEYVAULT_URL`, `AZURE_KEYVAULT_KEY`, `AZURE_TENANT_ID`, `AZURE_KEYVAULT_CLIENT_ID`, `AZURE_KEYVAULT_CLIENT_SECRET` |

With no cloud KMS configured the DEK is wrapped by a `PANEL_SECRET_KEY`-derived
key (dev/self-host). `REQUIRE_KMS=true` makes wrapping fail closed rather than
downgrade. `active_backend()` (surfaced on `/api/whoami` and Settings) reports
which manager is actually wrapping the key (`google`/`azure`/`aws`/`local`).
Cloud SDKs are optional extras (`pip install '.[kms-gcp]'` / `'.[kms-aws]'`;
Azure uses httpx).

Status: ✅ **at-rest envelope encryption identical to the app (Google/Azure/AWS
KMS + `REQUIRE_KMS`), rotation, and legacy read-back**; ⚠️ **provision the cloud
KEK + credentials for your environment.**

---

## 2. Where does the actual Pinpoint app code come from?

The panel never ships app source. It deploys **container images by reference**.
The reference is built from:

- `BACKEND_IMAGE` / `FRONTEND_IMAGE` (config, default
  `ghcr.io/pinpoint-311/pinpoint-311-*`), plus
- a **Release**, which carries either a mutable `version` tag **or** an
  immutable `sha256:` **digest** (`Release.backend_digest` / `frontend_digest`).

`orchestrator/stack.py._image_ref()` pins by digest (`image@sha256:…`) when the
release declares one, else falls back to the tag.

### Is pulling from public GHCR right for government? No — do this instead:

Public, mutable tags from `ghcr.io` are a supply-chain risk (tag mutation,
registry availability, egress to the public internet). For government
production:

1. **Mirror into a government-controlled private registry** — Artifact Registry
   / ECR / ACR in the Gov cloud, Harbor, or DoD Iron Bank. Set `BACKEND_IMAGE` /
   `FRONTEND_IMAGE` to that registry. Nothing else changes.
2. **Pin by digest, never `latest`.** Publish every Release with
   `backend_digest`/`frontend_digest` so towns run byte-identical, verifiable
   images. The panel already supports and prefers this.
3. **Sign and verify.** Sign images with cosign/sigstore; verify signatures at
   admission (e.g. a Kyverno/Connaisseur policy on the k8s target, or a verify
   step before `docker compose up`).
4. **Scan.** Gate releases on a vulnerability scan (Trivy/Grype) and an SBOM.
5. **Air-gap the pull.** Egress-restrict managed hosts so they can only reach
   the private registry.

**cosign signature verification is now enforced in-panel.** With `COSIGN_VERIFY`
on (alongside `REQUIRE_SIGNED_IMAGES`), the provisioner's `verify_supply_chain`
step runs `cosign verify` on each pinned `image@sha256:…` before the stack is
rendered/applied and **fails the run** on a missing/invalid signature
(`orchestrator/supply_chain.py`). Keyless verification pins the signing
identity + OIDC issuer (`COSIGN_IDENTITY`/`COSIGN_ISSUER`); key-based uses
`COSIGN_KEY`.

Status: ✅ **registry is configurable, digest-pinning is preferred, and cosign
verification is enforced at provision time**; ⚠️ **mirroring into a private
registry and vulnerability scanning remain deployment steps.**

---

## 3. Operator authentication & authorization

The API is gated by a shared bearer token (`PANEL_API_TOKEN`, `X-Panel-Token`),
constant-time compared, fail-closed. On top of that there is now **RBAC**:

- **Roles** viewer < operator < approver < admin. Reads need viewer; mutations
  need operator; **decommission and break-glass issuance need approver.**
- **Effective role** comes from a trusted groups header the OIDC/SSO proxy
  injects — `ROLES_HEADER` (e.g. `X-Forwarded-Groups`) mapped via
  `ROLE_GROUP_MAP` (JSON). With no groups header, everyone gets
  `DEFAULT_OPERATOR_ROLE` (default `admin` for single-token dev; set to
  `viewer` in production and grant roles by group).
- **Operator identity** for the audit trail comes from `OPERATOR_HEADER`
  (e.g. `X-Forwarded-User`) — the real user, not a generic label.

**Operator SSO is set up the same way as the app.** The panel uses the app's
provider catalog — `IDENTITY_PROVIDER` = `auth0` | `entra` | `okta` | `oidc` —
with the identical credential env vars (`AUTH0_DOMAIN`/`AUTH0_CLIENT_ID`/
`AUTH0_CLIENT_SECRET`, `ENTRA_TENANT_ID`/`ENTRA_CLIENT_ID`/`ENTRA_CLIENT_SECRET`/
`ENTRA_AUTHORITY`, `OKTA_ISSUER`/`OKTA_CLIENT_ID`/`OKTA_CLIENT_SECRET`,
`OIDC_ISSUER`/`OIDC_CLIENT_ID`/`OIDC_CLIENT_SECRET`) and the same issuer
derivation and RS256/JWKS ID-token verification (`orchestrator/oidc.py`).
Admins can alternatively enter the same fields in the panel UI
(`FederationConfig`, client secret stored envelope-encrypted). The panel keeps
its **HttpOnly-cookie session + PKCE** — a deliberate hardening over the app's
localStorage-bearer transport, since the panel is an admin control plane where
an XSS-stealable token has a larger blast radius; the *configuration* is
identical, the session transport is stricter.

An optional **oauth2-proxy MFA sidecar** (`docker compose --profile sso up -d`)
can additionally front the panel, injecting `X-Forwarded-User`/`X-Forwarded-Groups`
into the same RBAC; its config is generated from the federation settings
(`GET /api/auth/sidecar-config`).

Status: ✅ **fail-closed token + RBAC + operator-identity capture + app-uniform
OIDC provider catalog (cookie+PKCE session) + optional oauth2-proxy MFA
sidecar**; ⚠️ **point it at your StateRAMP/FedRAMP IdP and require MFA in the IdP
policy.**

---

## 4. Audit

Every provisioning, rollout, secret, key-assignment, lifecycle (incl.
take-offline), and break-glass action is recorded in `audit_log` with actor,
action, tenant, and metadata (`GET /api/audit`). Break-glass grants are
time-boxed, reason-required, and audited on both the panel and the town.

The trail is now **hash-chained** (each entry binds to the previous one's hash);
`GET /api/audit/verify` (Settings → "Verify audit chain") recomputes it and
pinpoints any insertion, edit, or deletion.

**Off-host anchoring is uniform with the app.** Like the app's daily anchor, the
panel records the chain head + entry count into an append-only `audit_anchors`
table and emits `[AUDIT ANCHOR] head=… count=…` to stdout
(`orchestrator/audit.py`, `POST /api/audit/anchor`, background loop), so the head
lives outside the mutable DB for external log aggregation to capture. Error
monitoring uses the same `SENTRY_DSN`/`ENVIRONMENT` integration
(`send_default_pii=False`). As a panel **extra** on top of that, entries can
also be shipped to an append-only WORM journal (`AUDIT_WORM_PATH`) and/or a SIEM
collector (`AUDIT_SIEM_URL`, ECS JSON) — best-effort, never blocking an action.

Status: ✅ **central audit + tamper-evident hash chain + app-uniform anchoring
(stdout + `audit_anchors`) + Sentry, with optional WORM/SIEM shipping**;
⚠️ **ship container stdout to your log aggregator (and back `AUDIT_WORM_PATH`
with object-lock storage if used); set retention to your records schedule.**

---

## 5. Data isolation, deletion, availability

- **Isolation:** silo tenancy — one instance, DB, bucket, and KMS key per town.
  No shared tables; no cross-tenant query surface. The registry doubles as the
  authorization-boundary inventory.
- **Deletion:** decommission crypto-shreds the town's KMS wrapping key → all
  envelope-encrypted PII is unrecoverable. **Take-offline** is the reversible
  counterpart: stack stopped, *all* data/PII/keys retained.
- **Availability/DR:** backups use the **same method + env vars as the app**
  (`orchestrator/backups.py`, mirroring `backup_service.py`): `pg_dump -Fc` |
  `gpg --symmetric --cipher-algo AES256` | upload to S3-compatible storage.
  In managed hosting the town app's own backups are disabled (the state runs
  DR), so with `BACKUPS_ENABLED` the panel backs up every town on the
  `BACKUP_POLL_SECONDS` cadence, cataloged in `backup_records`, pruned to
  `BACKUP_RETENTION_DAYS` (`POST /api/tenants/{id}/backup`,
  `GET /api/tenants/{id}/backups`). **Configured once for the whole fleet** with
  the app's names — `BACKUP_S3_BUCKET`, `BACKUP_S3_ACCESS_KEY`,
  `BACKUP_S3_SECRET_KEY`, `BACKUP_ENCRYPTION_KEY`, `BACKUP_S3_ENDPOINT`,
  `BACKUP_S3_REGION` — **but every town stays isolated**, mirroring the silo
  model: each town's dump is encrypted with a **per-town key derived via
  HKDF-SHA256(`BACKUP_ENCRYPTION_KEY`, info=`tenant.id`)** and stored under its
  own `s3://bucket/<slug>/…` prefix, so one town's backup can't decrypt or be
  confused with another's (and you can scope per-town IAM/lifecycle to the
  prefix). Restore mirrors the app — recover the town's passphrase, then
  `gpg --decrypt | pg_restore --clean`:

  ```python
  # per-town restore passphrase (run where BACKUP_ENCRYPTION_KEY is available)
  from cryptography.hazmat.primitives import hashes
  from cryptography.hazmat.primitives.kdf.hkdf import HKDF
  passphrase = HKDF(algorithm=hashes.SHA256(), length=32,
                    salt=b"pinpoint311-backup-kek",
                    info=TENANT_ID.encode()).derive(BACKUP_ENCRYPTION_KEY.encode()).hex()
  ```

  Point the bucket at cross-region durable storage and rehearse a restore before
  ATO. (This is a deliberate hardening over the app's single shared passphrase,
  because the panel holds many tenants' backups in one bucket.)

- **Edge hardening:** the panel's own API carries the app's security-header set
  and **SlowAPI** per-client rate limiting (`RATE_LIMIT_RPM`, default 500/min),
  uniform with the app. Additionally (panel **extra**), with `WAF_ENABLED`
  rendered town Caddy sites carry an OWASP CRS (Coraza) block + edge rate
  limiting; those directives need a Caddy built with the `coraza-caddy` and
  `caddy-ratelimit` modules — `xcaddy build --with
  github.com/corazawaf/coraza-caddy/v2 --with github.com/mholt/caddy-ratelimit`.

- **TLS + health alerting:** with `SSL_CHECK_ENABLED`, alert evaluation probes
  each active town's certificate and raises a `cert_expiry` alert within
  `CERT_EXPIRY_WARN_DAYS`, plus `health` alerts from unhealthy integrations in
  telemetry (`orchestrator/sslcheck.py`, `orchestrator/insights.py`).

---

## Summary checklist

"Uniform with the app" below means the panel uses the **same modules, scheme,
and environment variables** as the Pinpoint 311 app, so an operator sets both up
identically.

| Control | Code today | Before government ATO |
|---|---|---|
| Secrets at rest | ✅ **envelope encryption uniform with the app** — Google/Azure/AWS KMS via `KMS_PROVIDER`+`REQUIRE_KMS`, `pii2:` tokens, rotation | ⚠️ provision the cloud KEK + credentials |
| Image provenance | ✅ configurable registry, digest pinning, `REQUIRE_SIGNED_IMAGES`, cosign verify at provision (`COSIGN_VERIFY`) *(panel extra)* | ⚠️ private mirror, vulnerability scan |
| Operator authN | ✅ fail-closed token + **app-uniform OIDC catalog** (`IDENTITY_PROVIDER`, `AUTH0_*`/`ENTRA_*`/`OKTA_*`/`OIDC_*`); cookie+PKCE; optional oauth2-proxy MFA | ⚠️ point at your IdP, require MFA in IdP policy |
| Operator authZ | ✅ **RBAC** (viewer/operator/approver/admin via `ROLE_GROUP_MAP`); decommission/offload require approver | ⚠️ map groups to roles in your IdP; consider dual-approval on decommission |
| Audit | ✅ central, hash-chained + `/api/audit/verify`, **app-uniform anchor (stdout + `audit_anchors`) + Sentry**; optional WORM/SIEM | ⚠️ ship stdout to your aggregator; set retention |
| Availability / DR | ✅ **backups uniform with the app** — `pg_dump -Fc` \| gpg AES256 → S3 (`BACKUP_S3_*`, `BACKUP_ENCRYPTION_KEY`) | ⚠️ durable cross-region bucket, rehearse restore |
| Edge protection | ✅ **app-uniform security headers + SlowAPI rate limiting** (`RATE_LIMIT_RPM`); optional Caddy WAF (`WAF_ENABLED`) | ⚠️ xcaddy build with coraza + ratelimit for the WAF extra |
| Monitoring | ✅ down/drift/cost + `cert_expiry` + `health` alerts (`SSL_CHECK_ENABLED`); Sentry (`SENTRY_DSN`) | ⚠️ wire alert webhook to your on-call |
| Tenant isolation | ✅ silo | ✅ |
| Crypto-shred deletion | ✅ | ✅ |
| Transport | deploy TLS (Caddy) | ⚠️ enforce mTLS to registry/DB |

The panel's KMS, SSO, backups, audit, and edge headers/rate-limiting now use the
**same implementation and env-var setup as the Pinpoint 311 app** (Google/Azure/
AWS KMS envelope, `IDENTITY_PROVIDER` catalog, pg_dump+GPG+S3, audit anchor +
Sentry, SlowAPI + security headers). A handful of controls are panel-only
additions the app doesn't have (cosign verification, oauth2-proxy MFA sidecar,
Caddy WAF, WORM/SIEM shipping); those remain opt-in. The remaining ⚠️ items are
deployment wiring — cloud KEK credentials, the IdP, a private image registry +
scanner, durable backup storage, log aggregation — none require re-architecting.
