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
automated backend quality checks, a PostgreSQL development container, and a
responsive React community-health and drug-recall explorers. The dashboard
discovers its measure filters from the live CDC catalog, presents paginated
county estimates and confidence intervals, and lazily loads newest-first FDA
recall reports with hazard-class filtering, safety disclaimers, and source
provenance. Both views expose shareable URLs that preserve submitted filters and
pagination across reloads and browser history navigation. A cross-source
overview reports CMS ingestion health, CDC catalog breadth, and FDA source
freshness independently, without joining incompatible entities or reporting
years.
The API now covers three live public sources; the first milestone also targets REST APIs,
dashboard visualizations, and architecture documentation. See the current
[architecture notes](docs/architecture.md).

## Quick start

With Docker installed:

```bash
docker compose up --build
```

Then open `http://localhost:8000/docs` or check
`http://localhost:8000/api/v1/health`. The dashboard is available at
`http://localhost:3000`.

## Data policy

Only live, publicly available healthcare datasets are used. No fabricated CSV
datasets or patient-level protected health information belong in this repository.
