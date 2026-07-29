# Running the control plane in production

Operational notes for the panel itself. Fleet/tenant procedures live in
`ORCHESTRATOR_PLAN.md`.

## Database schema

Alembic owns the schema. `init_db()` runs at startup and handles three cases:

| Situation | What happens |
| --- | --- |
| Fresh database | Tables created from the models, stamped at head |
| Existing database, no `alembic_version` | Missing tables and additive columns are reconciled, then adopted at head |
| Tracked database | `alembic upgrade head` |

Adoption is deliberately conservative. If a pre-Alembic database is missing a
NOT NULL column with no scalar default, startup **fails** and names the column
rather than stamping head — stamping would record a false baseline and every
later migration would build on a schema that isn't what Alembic believes it is.

Adding a column:

```bash
alembic revision --autogenerate -m "what changed"
# review the generated file, then commit it
```

Never hand-edit a released revision; add a new one.

## Scaling beyond one process

The image runs a single uvicorn worker. That is the supported shape today.
Before adding `--workers` or a second replica, know what each piece needs:

| Concern | State | Ready for multiple processes? |
| --- | --- | --- |
| OIDC login state | `login_states` table | Yes |
| Periodic loops (telemetry, alerts, backups) | `cluster_locks` lease | Yes — one holder runs each pass, failover within one TTL |
| Rate limiting | SlowAPI, in-memory by default | **Only with `REDIS_URL`** — otherwise the ceiling is per process, so N workers allow N× the configured rate |
| Provisioning / rollout concurrency | `cluster_locks` lease (`jobs.py`) | Yes — the lease is renewed while a job runs and released when it ends; a crashed worker frees the town within one TTL |

## Provisioning

Runs in the background. `POST /api/tenants/{id}/provision` returns **202** with
a job; poll `GET /api/tenants/{id}/jobs` for step-by-step progress. A second run
against a town that is already provisioning is refused with 409 — the guard is a
database lease, so this holds across workers, not just within one process.

Rollouts work the same way: `POST /api/rollouts` and
`POST /api/rollouts/{id}/promote` return **202** and advance in the background;
poll `GET /api/rollouts`. Only one rollout is in flight fleet-wide at a time.

The pipeline is idempotent — every step checks world state first and reports
`skipped`. Re-running after a failure is the normal repair path.

## Pulling app updates

The panel watches one tag (`UPSTREAM_CHANNEL`, default `latest`) on the two
images in `BACKEND_IMAGE` / `FRONTEND_IMAGE`. It cannot be pointed anywhere
else — no endpoint accepts a URL, host, or image name, so discovery has no
reachable surface for an operator mistake or an SSRF to steer.

A build reaches a town only after **three** separate human decisions:

1. **Approve the candidate** (Releases → App updates). Publishes a `Release`.
2. **Start a rollout.** Deploys to the canary towns only.
3. **Promote.** Deploys to the rest of the fleet.

Checking is safe to automate (`UPSTREAM_CHECK_SECONDS`) precisely because it is
separate from deploying: the worst outcome of an unattended check is a row
waiting for review. There is no auto-deploy path and no setting that creates one.

What the panel verifies before a candidate can be approved:

| Check | Behaviour |
| --- | --- |
| Tag → digest | Resolved to `sha256:…` at discovery; the digest is what gets deployed, never the tag |
| cosign signature | Re-verified **at approval**, not trusted from discovery — a candidate can sit for days |
| Migration stamp | `db_revision`/`min_db_revision` read from the image's own OCI labels; an unstamped build cannot be approved without the operator stating the window |
| Duplicate version | Refused if that version is already published |

`COSIGN_VERIFY=false` reports "signing not enforced" rather than a pass. A green
check the deployment did not earn is worse than no check.

## What an upgrade does to a town

Per town, in this order — see `orchestrator/migrator.py`:

1. **Back up** (`BACKUP_BEFORE_MIGRATE`, needs `BACKUPS_ENABLED`). Taken while
   the old schema is intact. If backups are on and the snapshot fails, the
   upgrade **stops** — migrating without a restore point is how a bad migration
   becomes permanent data loss.
2. **Pull** the pinned images, before anything is stopped, so a registry outage
   costs nothing.
3. **Migrate** — `alembic upgrade head` in a one-shot container built from the
   *new* image, against the running database, before the new build serves.
4. **Recreate** — `docker compose up -d --wait --remove-orphans`. Backend,
   worker and frontend come up on the new images; Postgres and Redis keep
   serving. `--remove-orphans` clears containers for services a release dropped.
5. **Verify** — the town must report the release's version *and* `db_revision`,
   or the step fails and the phase rolls back.

**Data and configuration persist.** The upgrade path never issues `down` and
never `--volumes`, so named volumes (the town database) survive by construction;
there is a test asserting no destructive compose command appears anywhere in it.
Re-rendering the stack reproduces the same secrets from the panel's store rather
than minting new ones — a rotated `SECRET_KEY` would invalidate every session and
make the town's encrypted data unreadable, so that is also pinned by a test.

The host front proxy is reloaded via `CADDY_RELOAD_COMMAND` if set. A failed
reload is logged, not fatal: a stale proxy config is a routing problem, not a
reason to fail an otherwise healthy upgrade.

## Schema adoption (read this before the first migrating release)

The app builds its tables with `Base.metadata.create_all` at startup and keeps a
**supplemental** Alembic chain whose base revision only adds a translations
table. So a town can have a complete schema and no `alembic_version` row, and
`alembic upgrade head` would collide with columns that already exist.

`GET /api/tenants/{id}/schema` reports which case a town is in:

| State | Meaning | Action |
| --- | --- | --- |
| `tracked` | `alembic_version` present | Upgrades run normally |
| `empty` | No tables yet | Nothing to do; the app creates them on first boot |
| `untracked` | Tables exist, Alembic never ran | **Adopt it** before an upgrade carrying a migration |

Adoption is `POST /api/tenants/{id}/schema/adopt` with the revision the schema
already matches plus a slug confirmation. It is deliberately manual: stamping
asserts "the schema equals this revision", and every later migration builds on
that claim, so a wrong revision silently corrupts the town's upgrade path. The
rollout refuses and names the town rather than guessing.

The durable fix is on the app side — make Alembic the only schema authority
(a baseline revision that creates everything, `create_all` removed). Until then,
every town provisioned by the current app needs one adoption.

## APPLY_STACKS

Defaults to `false`, which means provisioning **renders** compose files but never
starts anything. Towns will look provisioned while nothing is running. This is
surfaced as a warning under Setup → System Settings → Security posture. Set
`APPLY_STACKS=true` when the host is ready to actually deploy.

## Monitoring

- `GET /healthz` — liveness (the container `HEALTHCHECK` uses it).
- Leading-indicator checks (disk, memory, database, backup freshness, audit
  chain) run each alert pass. Crossings open fleet alerts with
  `kind = proactive:<check>` and clear themselves on recovery, so they appear on
  the Alerts page rather than only in container logs.
- `GET /api/system/uptime/stats` — 24h/7d/30d availability of the control
  plane's own components.

## Backups

`BACKUPS_ENABLED` plus `BACKUP_S3_*`. With either missing, the backup loop
records why it is skipping rather than failing silently. Verify restores
periodically — an untested backup is not a backup.
