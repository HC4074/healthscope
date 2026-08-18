# HealthScope

HealthScope is a production-oriented healthcare intelligence platform for
ingesting live public datasets, preserving historical snapshots, calculating
healthcare KPIs, and exposing insights through APIs and interactive dashboards.

## Project goals

- Ingest reproducible data from public sources such as CMS, CDC, Census, and FDA.
- Build validated, observable ETL pipelines with retries and incremental loading.
- Store analytics-ready healthcare data in PostgreSQL.
- Provide typed FastAPI endpoints and a responsive React dashboard.
- Run locally with Docker and ship through tested CI/CD workflows.

## Planned stack

- Python, FastAPI, SQLAlchemy, Pandas, and Pydantic
- PostgreSQL
- React, TypeScript, Vite, Tailwind CSS, and Recharts
- Docker Compose and GitHub Actions

## Status

Phase 1 is in progress. The repository includes a typed FastAPI service, a
versioned health endpoint, a paginated live CMS Hospital General Information
endpoint, paginated live CDC PLACES county-health and measure-catalog endpoints,
and newest-first live FDA drug recall enforcement reports,
versioned PostgreSQL migrations, an idempotent daily hospital snapshot store,
verified completion metadata with state-level coverage APIs, durable ingestion run status and
monitor-ready health checks, an explicit full-dataset ingestion command,
read-only restored-database integrity verification,
automated backend quality checks, a PostgreSQL development container, and a
responsive React community-health and drug-recall explorers. The dashboard
discovers its measure filters from the live CDC catalog, presents paginated
county estimates and confidence intervals, and lazily loads newest-first FDA
recall reports with hazard-class filtering, pending-classification context,
safety disclaimers, and source provenance. Both views expose shareable URLs that
preserve submitted filters and pagination across reloads and browser history navigation. A cross-source
overview reports CMS ingestion health, CDC catalog breadth, and FDA source
freshness independently, without joining incompatible entities or reporting
years. A failed overview source has its own retry control, so recovery does not
reload healthy source cards. Superseded dashboard requests are cancelled while
late completions are ignored across the overview and both explorers, preventing
older responses from replacing newer refresh, filter, page, or history results.
The API now covers three live public sources; the first milestone also targets REST APIs,
dashboard visualizations, and architecture documentation. See the current
[architecture notes](docs/architecture.md). A provider-neutral
[production deployment runbook](docs/deployment.md) defines the container
release, migration, readiness, first-ingestion, scheduling, monitoring, backup,
and rollback contract. A provider-neutral
[production launch checklist](docs/launch-checklist.md) records the hosting,
database, ownership, budget, alerting, and restore evidence required for a
go/no-go decision before credentials are used. Deployment CI boots those
production images with an ephemeral empty PostgreSQL instance and exercises routing, migrations,
readiness failure, recovery behavior, and Chromium critical journeys through
the overview, live CDC county data, and live FDA recalls at desktop and mobile
viewports. The browser checks submit live CDC and FDA filters, restore them with
browser back/forward navigation, and fail on JavaScript errors, same-origin
request failures, content-security-policy violations, detected WCAG A/AA
accessibility violations, horizontal mobile overflow, or broken keyboard focus
and pagination.
Successful `main` builds then publish
full-commit-SHA API and frontend images to GHCR with signed provenance and SPDX
SBOM attestations. Production configuration now fails before startup,
migration, or ingestion if debug is enabled, PostgreSQL is not configured, or a
documented placeholder/default database credential remains. Production Compose
also requires both reviewed image references explicitly, and the deployment
runbook loads them from the production env file during Compose interpolation so
it cannot silently substitute locally built fallbacks. Production API
responses include a validated `X-Request-ID`, and the API emits query-free
structured completion events so operators can correlate monitor failures with
container logs without recording request parameters. A scheduled compatibility
smoke check queries bounded live samples from all three official sources each
day, catching upstream schema drift without writing healthcare records.
The public Nginx boundary also applies a restrictive same-origin content
security policy, browser hardening headers, revalidated SPA entry documents,
and immutable caching for content-hashed assets.

The packaged restore verifier checks an isolated restored database against the
release migration head, newest CMS completion marker, exact snapshot row and
state totals, and matching successful ingestion counts. It emits only aggregate
operational evidence and never writes healthcare records.

## Quick start

With Docker installed:

```bash
docker compose up --build
```

Then open `http://localhost:8000/docs` or check
`http://localhost:8000/api/v1/health`. The dashboard is available at
`http://localhost:3000`.

Production uses `compose.production.yaml` with a managed PostgreSQL database;
it intentionally does not embed the local development database or credentials.

## Data policy

Only live, publicly available healthcare datasets are used. No fabricated CSV
datasets or patient-level protected health information belong in this repository.
