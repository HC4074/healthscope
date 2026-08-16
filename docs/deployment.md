# Production deployment runbook

This runbook deploys HealthScope to a provider-neutral container host with a
managed PostgreSQL database. The production Compose file does not run a local
database: production data must live in a backed-up managed service outside the
application host.

## Release contract

- Terminate TLS at the hosting platform or a reverse proxy in front of port 80.
- Keep the API private; only the Nginx frontend publishes a host port and proxies
  same-origin `/api` requests to it.
- Preserve the Nginx browser-security and cache headers at any upstream CDN or
  TLS proxy. SPA documents must revalidate; hashed assets may remain immutable.
- Use a managed PostgreSQL connection that requires TLS. Never reuse the local
  `healthscope-local-only` password.
- Production settings fail before startup, migration, or ingestion when debug is
  enabled, the database URL is not PostgreSQL, or a documented placeholder or
  default database credential remains.
- Apply Alembic migrations before the API accepts traffic. The API depends on a
  successful one-shot `migrate` container.
- Persist no secrets in Git, container images, command history, or scheduler
  definitions. Store `.env.production` with owner-only permissions or use the
  provider's equivalent secret injection.
- Pin deployments to a reviewed commit or immutable image digest. Do not deploy
  a moving `latest` tag.
- Set both production image variables explicitly. Production Compose rejects a
  missing API or frontend image instead of silently building a local fallback.
- Successful `main` builds publish separate API and frontend images to GHCR with
  a `sha-<full-commit-sha>` tag. Publishing starts only after the container-level
  production release checks pass. Each digest has signed GitHub build-provenance
  and SPDX SBOM attestations.

## Secret and configuration inventory

| Variable | Requirement | Purpose |
| --- | --- | --- |
| `HEALTHSCOPE_DATABASE_URL` | Required secret | Managed PostgreSQL SQLAlchemy URL; include the provider's TLS mode. |
| `HEALTHSCOPE_ENVIRONMENT` | Required, `production` | Identifies production in health metadata. |
| `HEALTHSCOPE_DEBUG` | Required, `false` | Prevents debug responses in production. |
| `HEALTHSCOPE_FDA_API_KEY` | Optional secret | Raises the openFDA request quota. |
| CMS, CDC, and FDA URL/dataset settings | Versioned defaults | Official public source identities and request policy. Change only through a reviewed release. |
| `HEALTHSCOPE_HTTP_PORT` | Optional host setting | Published HTTP port; defaults to `80`. |
| `HEALTHSCOPE_API_IMAGE`, `HEALTHSCOPE_FRONTEND_IMAGE` | Required for prebuilt deployment | Full-SHA GHCR tags or recorded immutable digests from the same release. |

Start from [`.env.production.example`](../.env.production.example). The real
`.env.production` file is ignored by Git. Restrict it to the deployment account
and prefer provider-managed secret injection when available.

## Deploy a release

Choose the exact reviewed commit and configure both images from that same
release. A full SHA tag is immutable by convention; resolve and record each
registry digest before deployment for the strongest pin:

After the first successful publication, choose the package access policy in
GitHub for both `healthscope-api` and `healthscope-frontend`. Public packages can
be pulled anonymously. For private packages, store a classic personal access
token with only `read:packages` in the hosting provider's secret store and log
the deployment host in without exposing that token to the application:

```bash
printf '%s' "${GHCR_READ_TOKEN}" | \
  docker login ghcr.io --username HC4074 --password-stdin
```

Do not place `GHCR_READ_TOKEN` in `.env.production`; it is a host registry
credential, not application configuration.

```bash
release_sha=replace-with-full-40-character-commit-sha
export HEALTHSCOPE_API_IMAGE="ghcr.io/hc4074/healthscope-api:sha-${release_sha}"
export HEALTHSCOPE_FRONTEND_IMAGE="ghcr.io/hc4074/healthscope-frontend:sha-${release_sha}"
docker pull "${HEALTHSCOPE_API_IMAGE}"
docker pull "${HEALTHSCOPE_FRONTEND_IMAGE}"
docker inspect --format='{{index .RepoDigests 0}}' "${HEALTHSCOPE_API_IMAGE}"
docker inspect --format='{{index .RepoDigests 0}}' "${HEALTHSCOPE_FRONTEND_IMAGE}"
```

Verify that each artifact was built by this repository. Repeat both commands
with `healthscope-frontend` for the dashboard image:

```bash
gh attestation verify \
  "oci://ghcr.io/hc4074/healthscope-api:sha-${release_sha}" \
  --repo HC4074/healthscope
gh attestation verify \
  "oci://ghcr.io/hc4074/healthscope-api:sha-${release_sha}" \
  --repo HC4074/healthscope \
  --predicate-type https://spdx.dev/Document/v2.3
```

From a clean checkout at the reviewed commit:

```bash
cp .env.production.example .env.production
# Edit .env.production with the managed database URL, both release image tags,
# and optional FDA key.
docker compose --env-file .env.production -f compose.production.yaml config --quiet
docker compose --env-file .env.production -f compose.production.yaml pull
docker compose --env-file .env.production -f compose.production.yaml up -d
docker compose --env-file .env.production -f compose.production.yaml ps
```

`--env-file .env.production` is required here because Compose resolves image
references before a container's `env_file` is applied. Omitting it can ignore
the release tags stored in that file. Missing image variables now fail during
`config`, before any build, pull, migration, or startup occurs.

`migrate` must exit successfully before `api` starts, and `frontend` waits for
the API readiness check. A migration failure leaves the new API unavailable
instead of serving against an older schema.

The settings guard is intentionally tied to
`HEALTHSCOPE_ENVIRONMENT=production`, so SQLite remains available for isolated
tests while every production entry point shares the stricter PostgreSQL and
placeholder checks. A rejected setting is reported on standard error before a
database connection is attempted.

Verify process liveness, database readiness, and the browser entry point through
the public TLS URL:

```bash
curl --fail --show-error https://healthscope.example.com/api/v1/health
curl --fail --show-error https://healthscope.example.com/api/v1/ready
curl --fail --show-error https://healthscope.example.com/overview
```

`/api/v1/health` proves the process is accepting requests. `/api/v1/ready`
returns 503 when PostgreSQL cannot be reached and is the routing health check.

## Verify the release contract

Deployment CI builds the production images and runs the production Compose file
with `compose.release-test.yaml`. The overlay supplies an ephemeral PostgreSQL
instance containing only empty migrated tables; it never loads or fabricates
healthcare records. Only a successful push build advances to GHCR publication.
Run the same check from a Docker-equipped development host:

```bash
cp .env.production.example .env.production
export HEALTHSCOPE_API_IMAGE=healthscope-api:production
export HEALTHSCOPE_FRONTEND_IMAGE=healthscope-frontend:production
npm --prefix frontend ci
(cd frontend && npx --no-install playwright install --with-deps chromium)
docker compose --env-file .env.production -f compose.production.yaml build
bash scripts/test-production-release.sh
```

The check verifies unsafe production settings fail before startup, migration
ordering, private API/database networking, same-origin Nginx routing,
production liveness and readiness responses, the SPA fallback, and the current
Alembic head. It also checks the restrictive browser headers, `no-cache` SPA
documents, and immutable content-hashed assets. Chromium then follows the
cross-source overview plus live CDC county-data and FDA recall journeys through
the same-origin production route at desktop and mobile viewports. It fails on
page errors, request failures, CSP violations, detected WCAG A/AA violations,
horizontal mobile overflow, broken submitted-filter or browser-history
restoration, or broken keyboard skip/navigation/filter/pagination behavior and
focus recovery; CI retains its trace, screenshot, video, and HTML report only on
failure. This automated coverage is
not a substitute for manual screen-reader and usability testing. The harness
then stops PostgreSQL and requires readiness to return its safe 503 contract, restarts
PostgreSQL and requires recovery, and proves migrations fail closed against an
unreachable database. The script always removes its containers and ephemeral
database on exit.

## Initialize and schedule CMS data

The ingestion-health probe is expected to return 503 before the first complete
CMS snapshot. Initialize production once after migrations:

```bash
docker compose --env-file .env.production -f compose.production.yaml --profile operations run --rm --no-deps ingest
curl --fail --show-error https://healthscope.example.com/api/v1/hospitals/ingestion/health
```

The command must report matching `expected`, `fetched`, and `upserted` counts and
a `succeeded` run ID. Confirm that the ingestion-health endpoint is then 200.

Schedule the same one-shot container daily. For a UTC cron host, a 06:00 UTC
example is:

```cron
0 6 * * * cd /srv/healthscope && docker compose --env-file .env.production -f compose.production.yaml --profile operations run --rm --no-deps ingest
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
- Keep the scheduled `Public Data Smoke` GitHub Actions workflow enabled. It
  checks bounded live CMS, CDC, and FDA responses daily without writing records,
  providing early warning of upstream contract drift before deployment or
  between application releases.
- Capture the `X-Request-ID` response header in monitor alerts and use it to
  locate the matching `http_request_completed` API log event. Those structured
  events include method, path, status, duration, environment, and release
  version. The Nginx `proxy_request_completed` event uses the same ID. Both
  deliberately omit query strings and response bodies.
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
3. Redeploy both last known-good images from the same commit, preferably pinned
   by their recorded immutable digests, and repeat the liveness/readiness checks.
4. Do not run `alembic downgrade` automatically. Several downgrades remove
   persisted data. If the schema itself must be reversed, stop writes, take a
   fresh database snapshot, review the exact downgrade SQL, and prefer restoring
   the managed backup when data loss is possible.
5. Re-run the CMS ingestion only if the status endpoint shows the previous run
   failed or the verified snapshot is stale; same-day retries are idempotent.
