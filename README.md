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
endpoint, a paginated live CDC PLACES county-health endpoint, versioned PostgreSQL
migrations, an idempotent daily hospital snapshot store, verified completion
metadata with state-level coverage APIs, durable ingestion run status and
monitor-ready health checks, an explicit full-dataset ingestion command,
automated backend quality checks, and a PostgreSQL development container.
The first milestone targets three live healthcare data sources, REST APIs,
dashboard visualizations, and architecture documentation. See the current
[architecture notes](docs/architecture.md).

## Quick start

With Docker installed:

```bash
docker compose up --build
```

Then open `http://localhost:8000/docs` or check
`http://localhost:8000/api/v1/health`.

## Data policy

Only live, publicly available healthcare datasets are used. No fabricated CSV
datasets or patient-level protected health information belong in this repository.
