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
