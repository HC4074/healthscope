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
   source metadata. A separate FDA client retrieves newest-first drug recall
   enforcement reports from openFDA, validates hazard classes, dates, ordering,
   pagination, and source metadata, and preserves FDA's medical-use disclaimer.
   No bundled or fabricated healthcare dataset is used.
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

## Frontend flow

1. A React, TypeScript, Vite, Tailwind CSS, and Recharts application provides
   interactive community-health and drug-recall views. It requests the CDC
   measure catalog at runtime, so available healthcare measures and labels are
   never fabricated or frozen into the browser bundle.
2. State and measure filters query the typed county endpoint in bounded pages.
   The view shows current-page comparisons, explicit confidence intervals,
   population context, loading/error/empty states, and a link to the exact
   official source dataset.
3. Browser requests stay same-origin under `/api`. Vite proxies that path during
   local development, while the production Nginx container routes it to the API
   service. This avoids enabling broad cross-origin access on the backend.
4. The FDA recall explorer and chart code are loaded on demand to keep the
   initial application bundle small. The recall view applies exact FDA hazard
   classes, uses bounded newest-first pagination, exposes source freshness and
   terms, and keeps FDA's medical-care warning prominent. Frontend CI
   independently enforces typed builds, lint, and component and API-boundary
   tests.
5. A typed, dependency-free browser routing boundary maps the explorers to
   `/community-health` and `/drug-recalls`. Only validated filter and page state
   is serialized, and `popstate` restores submitted queries without duplicating
   or fabricating source data.
6. `/overview` is the canonical dashboard landing route. It requests the CMS
   ingestion health contract, CDC measure catalog, and a one-record FDA page in
   parallel, isolates failures by source, and links into the detailed explorers.
   These cards retain their own provenance and freshness; they are not joined
   across incompatible entities or vintages.

## Current deployment boundary

Docker Compose runs the Nginx-served dashboard, FastAPI container, and PostgreSQL
17. PostgreSQL data is kept in a named volume, the API waits for database
readiness, the dashboard waits for the API health probe, and migrations run
before Uvicorn starts. Runtime secrets and production connection details must be
provided through environment variables rather than committed configuration.

The provider-neutral production Compose contract replaces the local database
with managed PostgreSQL, exposes only Nginx, runs migrations as a required
one-shot service, and gates traffic on a database-backed API readiness probe.
The separate liveness probe does not query dependencies. The deployment runbook
defines first ingestion, external daily scheduling, monitoring, backups, and a
schema-safe rollback boundary; actual infrastructure provisioning and TLS
termination remain the hosting provider's responsibility.

Deployment CI also boots the production images against an ephemeral, empty
PostgreSQL instance. It verifies migration and dependency ordering, private
service networking, Nginx/API routing, database-loss readiness behavior,
database recovery, and fail-closed migrations before a release can advance.
This validates the provider-neutral runtime contract without persisting test
healthcare data.

## Next boundary

Hospital scheduling remains separate from API startup and requires a deployed
API plus database credentials. Census population and demographic context remains
a natural complement to the county explorer, but Census data queries now require
an API key. The clearly disclaimed FDA drug recall view and cross-source landing
journey are now backed by typed live API contracts. The next unblocked milestone
increment is applying the production contract to a selected host, managed
PostgreSQL instance, scheduler, and monitor. That provisioning remains blocked
until a provider and credentials are supplied; Census enrichment remains queued
until a Census API key is configured.
