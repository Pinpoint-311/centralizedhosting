# Pinpoint 311 — Centralized Hosting Orchestrator

The **control plane** for state-hosted Pinpoint 311 fleets. It provisions town
instances, injects only platform-managed secrets, rolls out new versions with
canary + rollback, and aggregates health/cost **metadata** — it **never touches
resident data**.

This repo implements **Part B** of
[`docs/ORCHESTRATOR_PLAN.md`](https://github.com/pinpoint-311/pinpoint-311/blob/main/docs/ORCHESTRATOR_PLAN.md)
in the app repo. The app itself is the per-town unit (one instance = one
jurisdiction, silo tenancy); this panel sits *above* it and depends on the app
**only by container image tag + its provisioning/telemetry API** — never by
source.

## Plan → code map

| Plan item | What it is | Where |
|---|---|---|
| **B1** Tenant registry | Town, domain, region, plan, status, running version, contacts — metadata only; doubles as the StateRAMP/FedRAMP boundary inventory | `orchestrator/models.py` (`Tenant`), `/api/tenants` |
| **B2** Provisioner | Idempotent pipeline: DB → `SECRET_KEY` → KMS key → storage bucket → DNS/TLS → deploy image @ version → app provisioning API → one-time onboarding link | `orchestrator/provisioner.py` |
| **B3** Release management | Publish versioned image → canary rollout → watch health/version stamp → auto-rollback → enforce `min_db_revision` before promoting | `orchestrator/rollout.py`, `/api/releases`, `/api/rollouts` |
| **B4** Fleet dashboard | Telemetry aggregation, drift detection, per-town status | `orchestrator/api/fleet.py` |
| **B5** Secrets brokering | Platform-managed keys only, encrypted at rest, write-only API; tenant-managed keys never touch the panel | `orchestrator/secrets_policy.py`, `orchestrator/api/secrets.py` |
| **B6** Break-glass + compliance | Time-boxed signed state-ops tokens + central audit of every action | `orchestrator/api/breakglass.py`, `orchestrator/audit.py` |
| **Key responsibility** | Per-town matrix of who provides each external API key (state brokers it, or the town owns it) — set once, honored by the broker + provisioner | `orchestrator/key_catalog.py`, `orchestrator/api/keys.py` |
| **Panel UI** | Premium React control-plane matching the Pinpoint app design (fleet dashboard, add-town wizard, key matrix, releases, audit) | `panel-ui/`, served at `/` |

## Panel UI

A React + Vite + Tailwind SPA (`panel-ui/`) matching the Pinpoint app's design
system — indigo/glassmorphism, framer-motion, recharts. It covers the full
operator workflow:

- **Fleet Overview** — status/version charts, drift, per-town health, telemetry poll.
- **Municipalities** — searchable list + a 5-step **Add municipality** wizard
  (identity → subdomain-or-custom-domain → contact → API-key matrix → review).
- **Town detail** — lifecycle (provision / suspend / resume / decommission),
  editable domain + contact, the **key-responsibility matrix** with inline
  brokered-secret entry, provisioning-job timeline, and break-glass issuance.
- **Releases** — publish versions and drive canary → promote / rollback.
- **Audit** — the central compliance trail.

The app is gated by the panel operator token (stored client-side, sent as
`X-Panel-Token`). It's built into `orchestrator/static/` and served by FastAPI
at `/`, with client-side routing on deep links; if no build is present the
minimal `dashboard.html` is served as a fallback.

```bash
cd panel-ui && npm install && npm run build   # outputs to ../orchestrator/static
# or dev with hot reload against a local panel:
npm run dev                                    # proxies /api to :8100
```

The Docker image builds the UI automatically (multi-stage), so `docker compose
up` ships the full panel with no separate step.

## Key responsibility matrix

The state decides, per town, who provides each **assignable** API key —
Maps, AI, translation, SMTP, SMS, staff SSO, error monitoring:

- **State provides** → the panel brokers the credential (encrypted at rest) and
  injects it into the town's env at provision time.
- **Town provides** → the town enters it in its own instance; it never touches
  the panel (the secret-broker endpoint refuses it with `422`).

**Infrastructure keys** (`SECRET_KEY`, DB creds, KMS refs, backups, domain) are
always state-owned and shown locked. Set the matrix once at add-town time or
edit it later; `orchestrator/key_catalog.py` holds the catalog + defaults.

Deployment shape is the plan's **MVP shortcut**: the panel renders one Docker
Compose stack per town under `TENANT_ROOT` (plus a Caddy site block for the
host proxy) and — when `APPLY_STACKS=true` — runs `docker compose up -d` on the
managed host. `orchestrator/stack.py` is the deploy-driver seam to swap for a
Helm/GitOps writer when the fleet graduates to Kubernetes.

## The app contract (what the panel calls)

Defined in `orchestrator/app_client.py`, matching the plan's Part A hooks —
these are the only endpoints the panel touches on a town:

| Hook | Endpoint | Used for |
|---|---|---|
| A3 | `GET /api/health/quick` → `{version, git_sha, db_revision, min_db_revision}` | canary gating + drift |
| A4 | `POST /api/provisioning/bootstrap` (`X-Provisioning-Token`) | township name/domain/admin + one-time onboarding link |
| A4 | `POST /api/provisioning/lifecycle` | suspend / resume |
| A5 | `GET /api/telemetry` (`X-Panel-Token`) | metadata-only fleet stats |

Rendered town stacks are hosted-hardened per plan **A2**: pinned image tags,
`MANAGED_MODE=true`, `REQUIRE_KMS=true`, **no Docker socket mount, no
watchtower** — upgrades come only from this panel.

## Quick start

```bash
pip install .[dev]
pytest                      # 46 tests

# build the panel UI (or rely on the Docker multi-stage build)
cd panel-ui && npm install && npm run build && cd ..

export PANEL_API_TOKEN=$(openssl rand -hex 24)
export PANEL_SECRET_KEY=$(openssl rand -hex 32)
uvicorn orchestrator.main:app --port 8100
```

Open `http://localhost:8100/` for the panel UI (enter the `PANEL_API_TOKEN`),
`/docs` for the API.

Provision a town end-to-end (render-only by default — set `APPLY_STACKS=true`
on a managed host with Docker to actually run it):

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

Or run the panel itself with Compose: `docker compose up -d` (see
`docker-compose.yml`; uncomment the Docker socket mount only on a managed host
where the panel applies stacks — the panel is the *one* trusted component that
may drive Docker, the towns never get the socket).

## Configuration

| Env var | Default | Description |
|---|---|---|
| `PANEL_API_TOKEN` | *(empty — API fails closed)* | Operator auth (`X-Panel-Token` header) |
| `PANEL_SECRET_KEY` | dev placeholder | Encrypts brokered secrets at rest; signs break-glass tokens |
| `PANEL_DATABASE_URL` | `sqlite:///./panel.db` | Panel DB (Postgres in production) |
| `BASE_DOMAIN` | `311.example.gov` | Towns live at `<slug>.BASE_DOMAIN` (wildcard DNS + TLS) |
| `TENANT_ROOT` | `./tenants` | Where per-town Compose stacks are rendered |
| `APPLY_STACKS` | `false` | `true` = actually `docker compose up` + call town APIs |
| `BACKEND_IMAGE` / `FRONTEND_IMAGE` | GHCR pinpoint-311 images | Default image repos for releases |
| `CANARY_COUNT` | `1` | Default canary batch size |
| `BREAK_GLASS_MAX_MINUTES` | `60` | Hard cap on break-glass grant lifetime |

## Security posture

- **Fail-closed auth** — every `/api/*` route requires the panel token
  (constant-time compare); no token configured means no access.
- **Secret split enforced on both sides** — the panel refuses to store
  tenant-managed keys (`422`), mirroring the app's managed-mode refusal to
  accept platform-managed keys. Values are write-only and Fernet-encrypted at
  rest; they are never returned by any endpoint and never audited in plaintext.
- **PII firewall on telemetry** — snapshots pass an allowlist + recursive
  PII-key scrub (`orchestrator/telemetry.py`) with regression tests.
- **Crypto-shred offboarding** — decommission destroys the town's KMS wrapping
  key reference, deletes brokered secrets, and tears down the stack; with the
  app's envelope encryption all PII becomes unrecoverable (plan A7).
- **Everything audited** — provisioning, rollouts, secrets, lifecycle,
  break-glass: `GET /api/audit`.

Break-glass tokens are HMAC-signed with the target town's own
`PROVISIONING_TOKEN` (a secret that town instance already holds), so the app
verifies them locally with no extra key distribution and a token minted for
one town is useless against another. The app-side exchange endpoint is
`POST /api/provisioning/break-glass` (managed mode only).

## Host setup

`deploy/host-Caddyfile` is the template for the managed host's front proxy:
one Caddy imports every rendered `tenants/_caddy/*.caddy` site block. Reload
Caddy after provisioning or decommissioning a town.

## Status / next steps

- The app-side Part A hooks (A1–A5, A8 + suspend/resume) are implemented in
  the app repo (`app/api/provisioning.py`, `app/api/telemetry.py`, health
  stamping, managed-mode gates); this panel speaks that contract via
  `orchestrator/app_client.py`.
- Cloud drivers (real KMS key creation, bucket creation, DNS records, email
  delivery of onboarding links) are recorded as resource references at their
  seams in `orchestrator/provisioner.py` — wire per-state providers there.
- Graduate `orchestrator/stack.py` from Compose rendering to Helm/GitOps for
  the Kubernetes target.
