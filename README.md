# Pinpoint 311 — Centralized Hosting Orchestrator

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](#license)
[![Fiscally Sponsored by Hack Club](https://img.shields.io/badge/Fiscally%20Sponsored%20by-Hack%20Club-ec3750.svg)](#fiscal-sponsorship)
[![CI](https://img.shields.io/badge/CI-backend%20%2B%20panel--ui-brightgreen.svg)](.github/workflows/ci.yml)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688.svg)](https://fastapi.tiangolo.com/)
[![React 18](https://img.shields.io/badge/React-18-61dafb.svg)](https://react.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-336791.svg)](https://www.postgresql.org/)
[![Caddy](https://img.shields.io/badge/Caddy-automatic%20HTTPS-1f88c0.svg)](https://caddyserver.com/)

The **control plane** for running many [Pinpoint 311](https://github.com/Pinpoint-311/Pinpoint-311)
town instances at once. A state, county, or agency uses it to stand up, update,
monitor, and offboard a whole fleet of municipal 311 deployments from one
place — while every town stays completely isolated and owns its own data.

## Introduction

[Pinpoint 311](https://github.com/Pinpoint-311/Pinpoint-311) is complete,
self-hosted 311 software a single town can run and own. That standalone
deployment is the default and needs nothing else. But a state or county often
wants to host 311 *for* its towns — including the small ones that could never
run a server themselves — without hand-managing dozens of boxes.

That's what this orchestrator is. It provisions a new town instance in one
click, brokers only the platform-managed secrets a town shouldn't have to think
about (infrastructure, KMS, backups, domain), rolls out new versions safely with
canary + automatic rollback, and aggregates health, uptime, and cost across the
fleet. When a town outgrows managed hosting, it can be **offloaded** to a fully
standalone self-hosted stack, data and all.

Crucially, the control plane **never touches resident data**. One instance is
one jurisdiction, with its own database, storage, encryption key, and secrets —
the same silo isolation a self-hosted town has. The panel's job is
infrastructure, platform secrets, version rollout, and PII-free aggregate
metadata; everything a town's staff and residents do stays inside that town's
own instance. It is **opt-in and a no-op when off** — with managed mode disabled,
the app is exactly the standalone single-tenant deployment.

## Table of Contents

- [Why an Orchestrator?](#why-an-orchestrator)
- [Who It's For](#who-its-for)
- [Core Features Overview](#core-features-overview)
- [The Operator Panel](#the-operator-panel)
- [Fleet Lifecycle](#fleet-lifecycle)
- [Key-Responsibility Matrix](#key-responsibility-matrix)
- [Municipality Offload (Self-Host Export)](#municipality-offload-self-host-export)
- [Security & Governance](#security--governance)
- [Technical Architecture](#technical-architecture)
- [Deployment & Setup](#deployment--setup)
- [Configuration](#configuration)
- [License](#license)

## Why an Orchestrator?

Hosting 311 for many towns by hand doesn't scale — and mixing their data would
be a compliance disaster. Here's what changes with the control plane:

| | Managing a fleet by hand | With the orchestrator |
|---|---|---|
| **Provisioning** | SSH into a box, run scripts, hope it's consistent | One idempotent pipeline: DB → keys → storage → DNS/TLS → deploy → onboarding link |
| **Isolation** | Easy to accidentally share a DB or key | One instance = one jurisdiction; separate DB, bucket, KMS key, secrets — enforced |
| **Upgrades** | Update each town, pray nothing breaks | Canary rollout gated on each town's health + DB-revision stamp, with auto-rollback |
| **Secrets** | Copy-paste API keys per box | Platform keys brokered once, encrypted at rest; town-owned keys never touch the panel |
| **Monitoring** | Log into each server to check health | Fleet dashboard: status, drift, uptime/SLA, cost, alerts |
| **Resident data** | Operator can see everything | Control plane holds **zero** resident data — metadata only |
| **Leaving** | Painful migration | One-click **offload** to a standalone self-hosted bundle |
| **Backups** | Set up per box | Configured **once for the fleet**, encrypted + isolated **per town** |

## Who It's For

One control plane, two audiences.

### 🏛️ For the hosting operator (state / county / agency)
Run a fleet without running a data-center.
- Provision & monitor many towns from one panel
- Roll out versions safely (canary → promote / rollback)
- Broker platform secrets; never see resident data
- Aggregate health, uptime, and cost

### 🏠 For the hosted town
Get a real 311 system with none of the ops.
- A fully isolated instance — your data is yours
- Platform-managed settings shown read-only ("Managed by your state")
- You still run your own services, content, and staff
- Leave anytime via a seamless self-host export

## Core Features Overview

### 🚀 One-click provisioning
An idempotent pipeline stands up a town end-to-end: allocate the database,
generate its `SECRET_KEY`, assign a per-town KMS key, allocate storage, allocate
loopback ports, configure DNS + TLS, verify the image supply chain, render the
stack, deploy it, bootstrap the app, and surface a one-time onboarding link.
Every step checks world state first and reports "skipped" when its work already
exists, so a run is always safe to repeat.

### 📦 Safe fleet-wide rollouts
Publish a versioned release (a mutable tag or an immutable `sha256:` digest),
run it as a **canary** on a small batch, watch each instance's `/api/health/quick`
version + DB-revision stamp, then **promote** the fleet or **roll back** — with
`min_db_revision` enforced so a build never lands on an incompatible schema.

### 📊 Fleet health, cost & SLA
Background polling collects PII-free telemetry from every active town and powers
a live dashboard: per-town status, version drift, uptime % + incident counts,
and estimated external-API cost split state-borne vs. town-borne via the key
matrix. Alerts fire on down / drift / cost-spike / cert-expiry / degraded
integrations, with an optional Slack-compatible webhook.

### 🔐 Secrets brokered, never leaked
The panel stores only platform-managed keys, envelope-encrypted at rest and
write-only over the API (never returned, never audited in plaintext). It refuses
to store town-owned keys (`422`), mirroring the app's managed-mode refusal to
accept platform keys — the split is enforced on both sides.

### 🧭 Isolation you can prove
Distinct DB, storage bucket, KMS key, `SECRET_KEY`, and container per town;
subdomain-routed so one town's URL can never reach another's data. Telemetry
passes an allowlist + recursive PII-key scrub before storage. Decommission
**crypto-shreds** the town's KMS key, making all its PII unrecoverable.

### 🏗️ Uniform with the app
KMS encryption, SSO, backups, audit, and edge hardening use the **same
implementation and the same environment-variable setup** as the Pinpoint 311
app, so an operator configures both identically. (See
[Security & Governance](#security--governance).)

## The Operator Panel

A React 18 + Vite + Tailwind SPA (`panel-ui/`) matching the Pinpoint app's design
system — Inter, indigo/glassmorphism, Framer Motion, Recharts — served by the
API at `/`. It covers the full operator workflow:

- **Overview** — status/version charts, drift, per-town health, one-click telemetry poll, 30s auto-refresh.
- **Municipalities** — searchable, tag-filterable fleet list + a **3-step Add-municipality wizard** (identity → contact → review), plus bulk CSV onboarding. Domain, key matrix, and secrets are configured on the town's detail page.
- **State Map** — town boundary polygons (OpenStreetMap-sourced, the same source the app uses) plotted by status; public geography only.
- **Town detail** — lifecycle actions, editable domain/contact/location, the key-responsibility matrix with inline per-town secret entry, provisioning timeline, backups, policy & legal hold, transparency, and the **offload** zone.
- **Cost & Chargeback / Uptime & SLA** — per-town rollups with CSV export.
- **Alerts** — fleet monitoring with a sidebar badge, acknowledge, and webhook.
- **Hosting Requests** — an approval inbox for towns that submit the public `/request` self-service form.
- **Releases** — publish versions (tag or digest-pinned) and drive canary → promote / rollback.
- **Settings** — program identity, shared state credentials, **SSO federation**, the **oauth2-proxy sidecar config**, and a Security card (identity/role, KMS backend, audit-chain verify, secret re-encryption).
- **Audit** — the central, hash-chained compliance trail with off-host anchoring.

Throughout: **RBAC-aware UI** (privileged actions hidden below the required
role), a ⌘K command palette, light/dark themes, per-town stack preview, and
accessible, mobile-responsive layout (labeled controls, focus-trapped modals,
skip link, keyboard-operable map, `prefers-reduced-motion`).

## Fleet Lifecycle

Four non-active states, so you never have to delete data to pause or move a town:

| State | What happens | Reversible? |
|---|---|---|
| **Suspend** (soft) | App stays up but returns read-only 503s | Yes — resume |
| **Take offline** (hard) | `docker compose stop`; stack stopped, but **every DB / Redis / uploads volume, KMS key, and secret is retained** | Yes — bring online |
| **Migrating / Migrated** | A standalone self-host bundle has been generated; the town is cutting over to its own infra (data retained read-only until decommission) | Yes — cancel |
| **Decommission** (terminal) | Crypto-shreds the KMS key → all PII unrecoverable; tears down the stack and deletes brokered secrets | No — irreversible |

## Key-Responsibility Matrix

The operator decides, per town, who provides each **assignable** API key — Maps,
AI, translation, SMTP, SMS, staff SSO, error monitoring — in one of three modes:

- **Town** → entered in the town's own instance; it never touches the panel (the per-town secret broker refuses it with `422`).
- **State · shared** → one credential entered once in the shared pool; every town set to shared plugs into the same value at provision time. Best for naturally-single endpoints (a state SSO tenant, mail relay, error-monitoring org).
- **State · per-town** → state-owned but a distinct value per town. Best where billing attribution, quota isolation, and blast radius matter (Maps, AI).

Sensible defaults tell a coherent story — **SSO and SMS default to the town**,
**Maps and AI default to per-town**, **translation / SMTP / Sentry default to
shared** — and **infrastructure keys** (`SECRET_KEY`, DB creds, KMS refs,
backups, domain) are always state-owned and shown locked.

## Municipality Offload (Self-Host Export)

Any managed town can be migrated onto its own servers, seamlessly. An approver
generates a **complete standalone bundle** — `docker-compose.yml`, `.env`
(carrying the town's own `SECRET_KEY` so existing encrypted data still
decrypts), a hardened `Caddyfile`, and a step-by-step migration runbook — plus,
when stacks are applied, a `pg_dump` data snapshot. The standalone stack runs
**un-managed** (`MANAGED_MODE=false`, its own Caddy with automatic TLS, no
provisioning token), so nothing ties it back to the control plane.

The managed instance keeps running until the town confirms cutover; data is
retained read-only on the platform until an explicit decommission, so the whole
migration is reversible. This is the guarantee that there's **no lock-in** even
in managed mode.

## Security & Governance

The panel handles sensitive government infrastructure, so its security controls
are built to match the app's and to be verifiable. The functions that exist in
both systems are **set up and operated identically** to the Pinpoint 311 app.

| Control | How it works | Env / setup (same as the app) |
|---|---|---|
| **Secret encryption** | Envelope encryption — AES-256-GCM data key wrapped by your cloud KMS/HSM, stored as a self-describing `pii2:` token; local key-derivation fallback | `KMS_PROVIDER` (google/azure/aws), `REQUIRE_KMS`, `GOOGLE_CLOUD_PROJECT`/`KMS_*`, `AWS_KMS_*`, `AZURE_KEYVAULT_*` |
| **Operator SSO** | OIDC authorization-code, RS256/JWKS verification, HttpOnly-cookie session + PKCE (a deliberate hardening over the app's bearer token for an admin surface) | `IDENTITY_PROVIDER` (auth0/entra/okta/oidc) + `AUTH0_*`/`ENTRA_*`/`OKTA_*`/`OIDC_*` |
| **RBAC** | viewer < operator < approver < admin; mutations need operator, decommission/offload need approver | `ROLES_HEADER` + `ROLE_GROUP_MAP`, or IdP group claims |
| **Backups** | `pg_dump -Fc` \| GPG AES-256 → S3, configured **once for the fleet** but **isolated per town** (distinct HKDF-derived key + own object prefix) | `BACKUP_S3_*`, `BACKUP_ENCRYPTION_KEY` |
| **Audit** | Tamper-evident hash chain + `/api/audit/verify`; daily anchor to `audit_anchors` + `[AUDIT ANCHOR]` stdout for off-host aggregation; Sentry | `SENTRY_DSN`; optional WORM/SIEM extras |
| **Edge** | App-uniform security headers + SlowAPI rate limiting on the panel API | `RATE_LIMIT_RPM` (default 500/min) |

**Panel-only hardening extras** (the app doesn't have these; opt-in): cosign
image-signature verification at provision (`COSIGN_VERIFY`), an OWASP-CRS Caddy
WAF for town sites (`WAF_ENABLED`), an oauth2-proxy MFA sidecar
(`--profile sso`), and WORM-journal / SIEM audit shipping. The WAF and edge
rate-limit directives need a Caddy built with the Coraza + ratelimit modules:

```bash
xcaddy build \
  --with github.com/corazawaf/coraza-caddy/v2 \
  --with github.com/mholt/caddy-ratelimit
```

### Restoring a backup

Each town's backup is encrypted under its **own** key, derived from the single
`BACKUP_ENCRYPTION_KEY` so one town's key never decrypts another's. To restore,
recover that town's passphrase, then `gpg --decrypt | pg_restore --clean`:

```python
# run where BACKUP_ENCRYPTION_KEY is available
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
passphrase = HKDF(algorithm=hashes.SHA256(), length=32,
                  salt=b"pinpoint311-backup-kek",
                  info=TENANT_ID.encode()).derive(BACKUP_ENCRYPTION_KEY.encode()).hex()
```

**Fail-closed by default** — every `/api/*` route requires the panel token
(constant-time compare); no token means no access. Rendered town stacks are
hosted-hardened: pinned images, `MANAGED_MODE=true`, `REQUIRE_KMS=true`, **no
Docker socket mount, no watchtower** — upgrades come only from the panel.

The table above is the posture summary. The items still owned by the deployment
before a StateRAMP/FedRAMP-style ATO are the usual wiring — cloud KEK
credentials, the IdP behind SSO, a private/mirrored image registry, durable
backup storage, and transport TLS to internal services (panel↔town, panel↔DB).

### Reporting vulnerabilities

Please **do not** file a public issue for security vulnerabilities. Use the
repository's **Security → Report a vulnerability** (private advisory). We aim to
acknowledge reports within 48 hours.

## Technical Architecture

The panel never ships app source. It deploys the app **by container image
reference** and speaks to towns over a tiny, fixed contract — the only coupling
between the two.

### The app contract (all the panel touches on a town)

| Hook | Endpoint | Used for |
|---|---|---|
| A3 | `GET /api/health/quick` → `{version, git_sha, db_revision, min_db_revision}` | canary gating + drift |
| A4 | `POST /api/provisioning/bootstrap` (`X-Provisioning-Token`) | township name/domain/admin + one-time onboarding link |
| A4 | `POST /api/provisioning/lifecycle` | suspend / resume |
| A4 | `POST /api/provisioning/managed-settings` | push state-set policy (retention, legal hold) |
| A5 | `GET /api/telemetry` (`X-Panel-Token`) | metadata-only fleet stats |

### Tech stack

| Component | Technology | Notes |
|---|---|---|
| Panel API | FastAPI (Python 3.11) | The orchestrator control plane |
| Panel UI | React 18 + TypeScript + Vite + Tailwind | Built into `orchestrator/static/`, served at `/` |
| Panel DB | SQLAlchemy 2.0 — SQLite (dev) / PostgreSQL (prod) | Fleet **metadata only**; doubles as the authorization-boundary inventory |
| Deploy driver | Docker Compose per town (`orchestrator/stack.py`) | MVP shape; the seam to swap for Helm/GitOps on Kubernetes |
| Edge | Caddy — automatic HTTPS | Host Caddy imports each rendered `tenants/_caddy/*.caddy` site block |
| Crypto | `cryptography` (AES-GCM/HKDF/Fernet) + optional `google-cloud-kms` / `boto3` | Envelope encryption uniform with the app |
| Rate limiting | SlowAPI | App-uniform per-client limits |

### Deployment shape

The panel renders one Docker Compose stack per town under `TENANT_ROOT` (plus a
Caddy site block for the host proxy) and — when `APPLY_STACKS=true` — runs
`docker compose up -d` on the managed host. The panel is the *one* trusted
component allowed to drive Docker; towns never get the socket.

## Deployment & Setup

### Prerequisites

- Docker & Docker Compose
- Python 3.11 + Node 22 (only if building/developing outside Docker)

### Quick start (from source)

```bash
pip install .[dev]
pytest -q                       # 137 tests

# build the panel UI (or rely on the Docker multi-stage build)
cd panel-ui && npm install && npm run build && cd ..

export PANEL_API_TOKEN=$(openssl rand -hex 24)
export PANEL_SECRET_KEY=$(openssl rand -hex 32)
uvicorn orchestrator.main:app --port 8100
```

Open `http://localhost:8100/` for the panel (enter the `PANEL_API_TOKEN`) and
`/docs` for the API. The Docker image builds the UI automatically (multi-stage),
so `docker compose up` ships the full panel with no separate step.

### Run with Compose

```bash
docker compose up -d            # panel + Postgres (+ oauth2-proxy under --profile sso)
```

### Provision a town end-to-end

Render-only by default; set `APPLY_STACKS=true` on a managed host with Docker to
actually run it.

```bash
H="X-Panel-Token: $PANEL_API_TOKEN"

# 1. publish a release
curl -sX POST localhost:8100/api/releases -H "$H" -H 'content-type: application/json' \
  -d '{"version":"1.4.0","db_revision":"abc123","min_db_revision":"9f8e7d"}'

# 2. register + provision the town
TID=$(curl -sX POST localhost:8100/api/tenants -H "$H" -H 'content-type: application/json' \
  -d '{"name":"Springfield, IL","slug":"springfield","contact_email":"clerk@springfield.gov"}' | jq -r .id)
curl -sX POST localhost:8100/api/tenants/$TID/provision -H "$H" | jq '.steps[] | {name, status}'

# 3. roll out a new version: canary, then promote
RID=$(curl -s localhost:8100/api/releases -H "$H" | jq -r '.[0].id')
ROLL=$(curl -sX POST localhost:8100/api/rollouts -H "$H" -H 'content-type: application/json' \
  -d "{\"release_id\":\"$RID\",\"canary_count\":1}" | jq -r .id)
curl -sX POST localhost:8100/api/rollouts/$ROLL/promote -H "$H"
```

### Host proxy

`deploy/host-Caddyfile` is the template for the managed host's front proxy: one
Caddy imports every rendered `tenants/_caddy/*.caddy` site block. Reload Caddy
after provisioning or decommissioning a town.

## Configuration

Every value is env-overridable (upper-cased name). Highlights:

| Env var | Default | Description |
|---|---|---|
| `PANEL_API_TOKEN` | *(empty — API fails closed)* | Operator auth (`X-Panel-Token`) |
| `PANEL_SECRET_KEY` | dev placeholder | Local key material for at-rest encryption + session signing |
| `PANEL_DATABASE_URL` | `sqlite:///./panel.db` | Panel DB (Postgres in production) |
| `BASE_DOMAIN` | `311.example.gov` | Towns live at `<slug>.BASE_DOMAIN` |
| `TENANT_ROOT` | `./tenants` | Where per-town Compose stacks are rendered |
| `APPLY_STACKS` | `false` | `true` = actually `docker compose up` + call town APIs |
| `TELEMETRY_POLL_SECONDS` / `ALERT_POLL_SECONDS` | `0` | Background poll / alert-eval cadence (0 disables) |
| `DEFAULT_OPERATOR_ROLE` | `admin` | Role when no groups header/SSO is present. Set `viewer` in production. |
| `ROLES_HEADER` / `ROLE_GROUP_MAP` | *(empty)* | Trusted groups header + JSON group→role map for RBAC |
| `IDENTITY_PROVIDER` + `AUTH0_*`/`ENTRA_*`/`OKTA_*`/`OIDC_*` | *(empty)* | Operator SSO — same provider catalog as the app |
| `KMS_PROVIDER` / `REQUIRE_KMS` | `google` / *(off)* | Secret-encryption KMS backend + fail-closed toggle (app-uniform) |
| `GOOGLE_CLOUD_PROJECT` / `KMS_*` / `AWS_KMS_*` / `AZURE_KEYVAULT_*` | *(empty)* | Cloud KMS config — same names as the app |
| `BACKUPS_ENABLED` + `BACKUP_S3_*` / `BACKUP_ENCRYPTION_KEY` | *(off)* | Fleet backups (pg_dump+GPG+S3, isolated per town) |
| `REQUIRE_SIGNED_IMAGES` / `COSIGN_VERIFY` | `false` | Refuse unpinned images / cosign-verify signatures at provision |
| `WAF_ENABLED` / `RATE_LIMIT_RPM` | `false` / `500` | Town-site OWASP-CRS WAF / panel API rate limit |
| `SENTRY_DSN` / `AUDIT_WORM_PATH` / `AUDIT_SIEM_URL` | *(empty)* | Error monitoring / off-host audit shipping |
| `PUBLIC_REQUESTS_ENABLED` | `false` | Enable the unauthenticated `/request` self-service intake |

Every setting is documented inline in `orchestrator/config.py`; the
[Security & Governance](#security--governance) table is the production posture.

## License

Open-source under the **MIT License**, the same as the
[Pinpoint 311](https://github.com/Pinpoint-311/Pinpoint-311) project — fork,
modify, and redistribute freely.

### Fiscal Sponsorship

Pinpoint 311 is fiscally sponsored by **The Hack Foundation** (d.b.a. Hack Club),
a 501(c)(3) public charity (EIN: 81-2908499), which lets the project receive
tax-deductible donations while the team focuses on building civic technology.

---

**Built by Pinpoint 311 for civic engagement · Fiscally sponsored by Hack Club**
