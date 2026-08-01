# HealthScope architecture

HealthScope currently uses a small layered backend so public-data contracts,
application behavior, and storage can evolve independently.

## Backend flow

1. FastAPI routes validate HTTP parameters and map upstream failures to stable
   service responses.
2. Typed source clients retrieve and validate records from official public
   healthcare APIs. The CMS client uses Provider Data Catalog dataset
   `xubh-q36u`. The CDC client uses PLACES 2025 county dataset `swc5-untb` and
   exposes only available age-adjusted prevalence estimates for a validated
   state and measure. It also derives the available measure catalog directly
   from live CDC aggregates, allowing clients to discover valid measure IDs,
   labels, categories, latest years, and county coverage without hard-coding
   source metadata. No bundled or fabricated healthcare dataset is used.
3. Repository functions persist validated records through SQLAlchemy. Daily CMS
   hospital observations use PostgreSQL-native upserts and a composite key of
   source dataset, UTC snapshot date, and facility ID.
4. Alembic owns all database schema changes. Application startup does not call
   `create_all`; deployment or Docker Compose applies versioned migrations.
5. A separate one-shot ingestion command pages the complete CMS dataset, uses
   one UTC timestamp for the run, and commits idempotent pages independently so
   a failed run can be safely retried without coupling ETL to API startup. The
   command reuses one HTTP connection pool and retries transient CMS failures
   with bounded exponential backoff.
6. Every ingestion has a durable run ID and lifecycle record. Page counters are
   committed with the corresponding snapshot rows, failures retain bounded
   error detail, and completion plus succeeded status are committed atomically.
   A latest-run API also reports freshness relative to the most recent success,
   while a monitor-ready health endpoint maps failed or stale ingestion to HTTP
   503. An active refresh stays healthy when the previous snapshot is still
   fresh, avoiding false-positive alerts during scheduled runs.
7. Completion metadata is written only after the exact retrieval batch contains
   every CMS-reported record. Snapshot status reads revalidate that marker and
   aggregate state coverage from matching rows, preventing a partial same-day
   retry from being exposed as a complete snapshot.

## Current deployment boundary

Docker Compose runs the FastAPI container and PostgreSQL 17. PostgreSQL data is
kept in a named volume, the API waits for database readiness, and migrations run
before Uvicorn starts. Runtime secrets and production connection details must be
provided through environment variables rather than committed configuration.

## Next boundary

Hospital scheduling remains separate from API startup and requires a deployed
API plus database credentials. The next data increment should introduce the
milestone's third official public source, or begin the first dashboard view using
the CDC measure catalog and county response contracts.
