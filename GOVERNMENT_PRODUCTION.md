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
key while still decrypting the old ones. The `KEY_PROVIDER` seam
(`orchestrator/key_provider.py`) is where `local` becomes `kms`.

Status: ✅ **at-rest encryption + versioned rotation**; ⚠️ **KMS-backed key
material (`KEY_PROVIDER=kms`) is the remaining wiring.**

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

Status: ✅ **registry is configurable and digest-pinning is supported/preferred**;
⚠️ **mirroring, signing, verification, and scanning are deployment steps, not yet
enforced by the panel.**

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

Required for production: front the panel with an **OIDC/SSO reverse proxy**
(Login.gov, Okta-for-Gov, Entra Gov) enforcing **MFA**, and map your IdP groups
to roles. The shared token alone is still not sufficient — it must sit behind
that proxy.

Status: ✅ **fail-closed token + RBAC + operator-identity capture**;
⚠️ **the OIDC/MFA proxy itself is deployment-supplied.**

---

## 4. Audit

Every provisioning, rollout, secret, key-assignment, lifecycle (incl.
take-offline), and break-glass action is recorded in `audit_log` with actor,
action, tenant, and metadata (`GET /api/audit`). Break-glass grants are
time-boxed, reason-required, and audited on both the panel and the town.

The trail is now **hash-chained** (each entry binds to the previous one's hash);
`GET /api/audit/verify` (Settings → "Verify audit chain") recomputes it and
pinpoints any insertion, edit, or deletion. For government, still add immutable
off-host shipping (WORM/SIEM) and retention aligned to the records schedule.

Status: ✅ **complete central audit + tamper-evident hash chain**;
⚠️ **WORM/SIEM shipping is deployment-supplied.**

---

## 5. Data isolation, deletion, availability

- **Isolation:** silo tenancy — one instance, DB, bucket, and KMS key per town.
  No shared tables; no cross-tenant query surface. The registry doubles as the
  authorization-boundary inventory.
- **Deletion:** decommission crypto-shreds the town's KMS wrapping key → all
  envelope-encrypted PII is unrecoverable. **Take-offline** is the reversible
  counterpart: stack stopped, *all* data/PII/keys retained.
- **Availability/DR:** backups are state-managed (the `BACKUP_*` infra keys).
  Confirm cross-region backups + a tested restore runbook per the records
  schedule before ATO.

---

## Summary checklist

| Control | Code today | Before government ATO |
|---|---|---|
| Secrets at rest | ✅ Fernet, write-only, **versioned + rotatable** (`/api/maintenance/reencrypt-secrets`) | ⚠️ point `KEY_PROVIDER=kms` at a KMS/HSM (seam in `key_provider.py`) |
| Image provenance | ✅ configurable registry, digest pinning, **`REQUIRE_SIGNED_IMAGES` gate** | ⚠️ private mirror, cosign verify at admission, scan |
| Operator authN | ✅ fail-closed token + **OIDC identity header** (`OPERATOR_HEADER`) | ⚠️ deploy the OIDC + MFA proxy |
| Operator authZ | ✅ **RBAC** (viewer/operator/approver/admin via `ROLES_HEADER`+`ROLE_GROUP_MAP`); decommission/break-glass require approver | ⚠️ map groups to roles in your IdP; consider dual-approval on decommission |
| Audit | ✅ central, break-glass, **hash-chained + `/api/audit/verify`** | ⚠️ ship to WORM/SIEM off-host |
| Tenant isolation | ✅ silo | ✅ |
| Crypto-shred deletion | ✅ | ✅ |
| Transport | deploy TLS (Caddy) | ⚠️ enforce mTLS to registry/DB |

Since the first draft, RBAC, tamper-evident audit, key rotation, and the
signed-image gate moved from "TODO" to implemented (see the ✅ column). The
remaining ⚠️ items are deployment wiring (KMS credentials, the OIDC proxy, image
signing infrastructure, WORM log storage) — the code seams for each are named
above and none require re-architecting.
