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

Ciphertext is now **key-version tagged** (`v<n>:…`) and the panel supports
**rotation**: bump `PANEL_KEK_VERSION`, then `POST /api/maintenance/reencrypt-secrets`
(or Settings → "Re-encrypt secrets") rewrites every stored secret under the new
key while still decrypting the old ones.

**`KEY_PROVIDER=kms` is now implemented** (`orchestrator/key_provider.py` +
`orchestrator/kms.py`): a random 32-byte data key (DEK) is generated once,
**wrapped by a KMS/HSM key-encryption key (KEK)**, and only the wrapped DEK is
persisted (`wrapped_keys` table) — the plaintext DEK never touches disk.
Backends (`KMS_BACKEND`): `gcp` (Cloud KMS/HSM), `aws` (KMS/CloudHSM), and
`local-hsm` (a software-held KEK from `KMS_KEK_MATERIAL`, for CI/self-host —
still real envelope crypto). Destroying the KEK in the KMS crypto-shreds every
secret wrapped under it. Cloud SDKs are optional extras (`pip install
'.[kms-gcp]'` / `'.[kms-aws]'`).

Status: ✅ **at-rest encryption + versioned rotation + KMS/HSM envelope
encryption**; ⚠️ **provision the cloud KEK + credentials for your environment.**

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

The **OIDC/SSO reverse proxy with MFA is now shipped as an opt-in sidecar.**
`docker compose --profile sso up -d` brings up `oauth2-proxy` in front of the
panel; it authenticates every request against the host IdP (Login.gov,
Okta-for-Gov, Entra Gov — **MFA enforced there**) and injects
`X-Forwarded-User` / `X-Forwarded-Groups`, which the panel already maps to RBAC
roles. The proxy config is **generated from the panel's own federation
settings** (`GET /api/auth/sidecar-config`, `orchestrator/sidecar.py`) so the
two can't drift; the client secret is injected from the secret manager as an
env var and is never rendered. `allowed_groups` restricts sign-in to the groups
the panel recognizes.

Status: ✅ **fail-closed token + RBAC + operator-identity capture + oauth2-proxy
SSO/MFA sidecar (config generated from federation)**; ⚠️ **point it at your
StateRAMP/FedRAMP IdP and require MFA in the IdP policy.**

---

## 4. Audit

Every provisioning, rollout, secret, key-assignment, lifecycle (incl.
take-offline), and break-glass action is recorded in `audit_log` with actor,
action, tenant, and metadata (`GET /api/audit`). Break-glass grants are
time-boxed, reason-required, and audited on both the panel and the town.

The trail is now **hash-chained** (each entry binds to the previous one's hash);
`GET /api/audit/verify` (Settings → "Verify audit chain") recomputes it and
pinpoints any insertion, edit, or deletion.

**Off-host shipping is now built in** (`orchestrator/audit_ship.py`). Every entry
is, best-effort: appended to an **append-only WORM journal** (`AUDIT_WORM_PATH`,
NDJSON, carrying the hash chain so it's verifiable off-host — point it at an S3
Object-Lock / WORM mount) and POSTed to a **SIEM** (`AUDIT_SIEM_URL`, ECS-shaped
JSON, bearer-authed via `AUDIT_SIEM_TOKEN`). Shipping never blocks or fails an
operator action; the on-host chain stays the integrity source of truth.

Status: ✅ **complete central audit + tamper-evident hash chain + WORM/SIEM
shipping**; ⚠️ **back `AUDIT_WORM_PATH` with immutable (object-lock) storage and
set retention to your records schedule.**

---

## 5. Data isolation, deletion, availability

- **Isolation:** silo tenancy — one instance, DB, bucket, and KMS key per town.
  No shared tables; no cross-tenant query surface. The registry doubles as the
  authorization-boundary inventory.
- **Deletion:** decommission crypto-shreds the town's KMS wrapping key → all
  envelope-encrypted PII is unrecoverable. **Take-offline** is the reversible
  counterpart: stack stopped, *all* data/PII/keys retained.
- **Availability/DR:** **PITR is now built in** (`BACKUPS_ENABLED`). Town stacks
  turn on continuous **WAL archiving** to a `/backups` volume (see the `pitr`
  block in the compose template), and the panel takes periodic **base snapshots**
  (`pg_basebackup`) on the `BACKUP_POLL_SECONDS` cadence, cataloged in
  `backup_records` and pruned to `BACKUP_RETENTION_DAYS`
  (`orchestrator/backups.py`; `POST /api/tenants/{id}/backup`,
  `GET /api/tenants/{id}/backups`). Confirm the `/backups` volume is on
  cross-region durable storage and rehearse a restore before ATO.

- **Edge hardening:** with `WAF_ENABLED`, rendered town Caddy sites carry an
  OWASP CRS (Coraza) block + per-client rate limiting + hardened security
  headers (HSTS, nosniff, DENY framing) and a request-body cap. The WAF and
  rate-limit directives need a Caddy built with the `coraza-caddy` and
  `caddy-ratelimit` modules — build it with xcaddy:
  `xcaddy build --with github.com/corazawaf/coraza-caddy/v2 --with github.com/mholt/caddy-ratelimit`.

- **TLS + health alerting:** with `SSL_CHECK_ENABLED`, alert evaluation probes
  each active town's certificate and raises a `cert_expiry` alert within
  `CERT_EXPIRY_WARN_DAYS`, plus `health` alerts from unhealthy integrations in
  telemetry (`orchestrator/sslcheck.py`, `orchestrator/insights.py`).

---

## Summary checklist

| Control | Code today | Before government ATO |
|---|---|---|
| Secrets at rest | ✅ Fernet, write-only, versioned + rotatable, **KMS/HSM envelope encryption** (`KEY_PROVIDER=kms`) | ⚠️ provision the cloud KEK + credentials |
| Image provenance | ✅ configurable registry, digest pinning, `REQUIRE_SIGNED_IMAGES`, **cosign verify at provision** (`COSIGN_VERIFY`) | ⚠️ private mirror, vulnerability scan |
| Operator authN | ✅ fail-closed token + OIDC identity header + **oauth2-proxy SSO/MFA sidecar** (`--profile sso`) | ⚠️ point at your IdP, require MFA in IdP policy |
| Operator authZ | ✅ **RBAC** (viewer/operator/approver/admin via `ROLES_HEADER`+`ROLE_GROUP_MAP`); decommission/offload require approver | ⚠️ map groups to roles in your IdP; consider dual-approval on decommission |
| Audit | ✅ central, hash-chained + `/api/audit/verify`, **WORM journal + SIEM shipping** | ⚠️ back WORM with object-lock storage; set retention |
| Availability / DR | ✅ **PITR: WAL archiving + periodic base snapshots** (`BACKUPS_ENABLED`) | ⚠️ durable cross-region `/backups`, rehearse restore |
| Edge protection | ✅ **WAF (OWASP CRS) + rate limiting + security headers** at Caddy (`WAF_ENABLED`) | ⚠️ xcaddy build with coraza + ratelimit modules |
| Monitoring | ✅ down/drift/cost + **`cert_expiry` + `health`** alerts (`SSL_CHECK_ENABLED`) | ⚠️ wire alert webhook to your on-call |
| Tenant isolation | ✅ silo | ✅ |
| Crypto-shred deletion | ✅ | ✅ |
| Transport | deploy TLS (Caddy) | ⚠️ enforce mTLS to registry/DB |

Since the first draft, RBAC, tamper-evident audit, key rotation, and the
signed-image gate were joined by **KMS/HSM envelope encryption, cosign
verification, WORM/SIEM audit shipping, PITR backups, edge WAF + rate limiting,
the oauth2-proxy SSO/MFA sidecar, and TLS/health alerting** (see the ✅ column).
The remaining ⚠️ items are deployment wiring — cloud KEK credentials, the IdP
behind oauth2-proxy, a private image registry + scanner, object-lock storage for
the WORM journal, durable backup storage, and an xcaddy build with the WAF/rate
-limit modules. The code seams for each are named above; none require
re-architecting.
