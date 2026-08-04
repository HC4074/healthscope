# Production deployment runbook

This runbook deploys HealthScope to a provider-neutral container host with a
managed PostgreSQL database. The production Compose file does not run a local
database: production data must live in a backed-up managed service outside the
application host.

## Release contract

- Terminate TLS at the hosting platform or a reverse proxy in front of port 80.
- Keep the API private; only the Nginx frontend publishes a host port and proxies
  same-origin `/api` requests to it.
- Use a managed PostgreSQL connection that requires TLS. Never reuse the local
  `healthscope-local-only` password.
- Apply Alembic migrations before the API accepts traffic. The API depends on a
  successful one-shot `migrate` container.
- Persist no secrets in Git, container images, command history, or scheduler
  definitions. Store `.env.production` with owner-only permissions or use the
  provider's equivalent secret injection.
- Pin deployments to a reviewed commit or immutable image digest. Do not deploy
  a moving `latest` tag.

## Secret and configuration inventory

| Variable | Requirement | Purpose |
| --- | --- | --- |
| `HEALTHSCOPE_DATABASE_URL` | Required secret | Managed PostgreSQL SQLAlchemy URL; include the provider's TLS mode. |
| `HEALTHSCOPE_ENVIRONMENT` | Required, `production` | Identifies production in health metadata. |
| `HEALTHSCOPE_DEBUG` | Required, `false` | Prevents debug responses in production. |
| `HEALTHSCOPE_FDA_API_KEY` | Optional secret | Raises the openFDA request quota. |
| CMS, CDC, and FDA URL/dataset settings | Versioned defaults | Official public source identities and request policy. Change only through a reviewed release. |
| `HEALTHSCOPE_HTTP_PORT` | Optional host setting | Published HTTP port; defaults to `80`. |
| `HEALTHSCOPE_API_IMAGE`, `HEALTHSCOPE_FRONTEND_IMAGE` | Optional host settings | Stable image names/tags when a registry supplies prebuilt images. |

Start from [`.env.production.example`](../.env.production.example). The real
`.env.production` file is ignored by Git. Restrict it to the deployment account
and prefer provider-managed secret injection when available.

## Deploy a release

From a clean checkout at the reviewed commit:

```bash
cp .env.production.example .env.production
# Edit .env.production with the managed database URL and optional FDA key.
docker compose -f compose.production.yaml config --quiet
docker compose -f compose.production.yaml build --pull
docker compose -f compose.production.yaml up -d
docker compose -f compose.production.yaml ps
```

`migrate` must exit successfully before `api` starts, and `frontend` waits for
the API readiness check. A migration failure leaves the new API unavailable
instead of serving against an older schema.

Verify process liveness, database readiness, and the browser entry point through
the public TLS URL:

```bash
curl --fail --show-error https://healthscope.example.com/api/v1/health
curl --fail --show-error https://healthscope.example.com/api/v1/ready
curl --fail --show-error https://healthscope.example.com/overview
```

`/api/v1/health` proves the process is accepting requests. `/api/v1/ready`
returns 503 when PostgreSQL cannot be reached and is the routing health check.

## Initialize and schedule CMS data

The ingestion-health probe is expected to return 503 before the first complete
CMS snapshot. Initialize production once after migrations:

```bash
docker compose -f compose.production.yaml --profile operations run --rm --no-deps ingest
curl --fail --show-error https://healthscope.example.com/api/v1/hospitals/ingestion/health
```

The command must report matching `expected`, `fetched`, and `upserted` counts and
a `succeeded` run ID. Confirm that the ingestion-health endpoint is then 200.

Schedule the same one-shot container daily. For a UTC cron host, a 06:00 UTC
example is:

```cron
0 6 * * * cd /srv/healthscope && docker compose -f compose.production.yaml --profile operations run --rm --no-deps ingest
```

Use the hosting provider's scheduled-job facility when possible. Inject the
same release image and secrets as the API, prevent overlapping runs, retain
standard output/error, and alert on a nonzero exit code. Scheduling stays
outside API startup so restarts never trigger unscheduled data writes.

## Monitoring and backups

- Poll `/api/v1/health` for process liveness and `/api/v1/ready` for database
  readiness.
- Poll `/api/v1/hospitals/ingestion/health`; alert on 503. The default 26-hour
  freshness threshold allows a daily job a two-hour delay window.
- Alert on scheduler failures and keep the structured ingestion output with the
  release identifier.
- Enable managed PostgreSQL automated backups and point-in-time recovery. Test a
  restore before launch and at regular intervals afterward.
- Monitor host disk, memory, certificate expiry, HTTP 5xx rate, and upstream CDC,
  CMS, and FDA failures separately.

## Rollback

1. Capture current container logs and the failed release identifier.
2. Confirm the last known-good application schema is compatible with the current
   database schema.
3. Redeploy the last known-good commit or immutable image digest and repeat the
   liveness/readiness checks.
4. Do not run `alembic downgrade` automatically. Several downgrades remove
   persisted data. If the schema itself must be reversed, stop writes, take a
   fresh database snapshot, review the exact downgrade SQL, and prefer restoring
   the managed backup when data loss is possible.
5. Re-run the CMS ingestion only if the status endpoint shows the previous run
   failed or the verified snapshot is stale; same-day retries are idempotent.
