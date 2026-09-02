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
   enforcement reports from openFDA, validates assigned and pending
   classifications, dates, ordering, pagination, and source metadata, normalizes
   official blank/`N/A` optional fields to null, retries bounded transient
   network/rate-limit/server failures, and preserves FDA's medical-use
   disclaimer. No bundled or fabricated healthcare dataset is used.
3. Repository functions persist validated records through SQLAlchemy. Daily CMS
   hospital observations use PostgreSQL-native upserts and a composite key of
   source dataset, UTC snapshot date, and facility ID.
4. Alembic owns all database schema changes. Application startup does not call
   `create_all`; deployment or Docker Compose applies versioned migrations.
5. A separate one-shot ingestion command pages the complete CMS dataset, uses
   one UTC timestamp for the run, and commits idempotent pages independently so
   a failed run can be safely retried without coupling ETL to API startup. The
   command reuses one HTTP connection pool and retries transient CMS failures
   with bounded exponential backoff. It holds a dataset-scoped PostgreSQL
   advisory lock for the full run, so separate scheduler processes or hosts
   cannot ingest the same source concurrently.
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
   official source dataset. If the live measure catalog is unavailable, its
   error replaces the dependent county loading state and retries the catalog
   before any county request, avoiding a contradictory perpetual busy state.
3. Browser requests stay same-origin under `/api`. Vite proxies that path during
   local development, while the production Nginx container routes it to the API
   service. This avoids enabling broad cross-origin access on the backend.
4. The FDA recall explorer and chart code are loaded on demand to keep the
   initial application bundle small. The recall view applies exact assigned FDA
   hazard classes, labels not-yet-classified reports without implying a hazard
   level, uses bounded newest-first pagination, exposes source freshness and
   terms, and keeps FDA's medical-care warning prominent. Pagination respects
   openFDA's 25,000-record skip ceiling, and stale deep links can recover to the
   first live page without losing the submitted classification. Frontend CI
   independently enforces typed builds, lint, and component and API-boundary
   tests.
5. A typed, dependency-free browser routing boundary maps the explorers to
   `/community-health` and `/drug-recalls`. Only validated filter and page state
   is serialized, and `popstate` restores submitted queries without duplicating
   or fabricating source data. Filter, pagination, retry, and history changes
   cancel pending requests and ignore abort-insensitive late completions, so an
   older CDC or FDA response cannot overwrite the active route's result.
6. `/overview` is the canonical dashboard landing route. It requests the CMS
   ingestion health contract, CDC measure catalog, and a one-record FDA page in
   parallel, isolates failures and retries by source, preserves keyboard focus
   when a retry settles, cancels pending superseded requests, ignores late
   completions from older attempts, and links into the detailed explorers.
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
Shared settings validation makes API startup, migrations, and ingestion fail
before connecting when production enables debug mode, lacks a full build-bound
release SHA, selects a non-PostgreSQL database, omits a TLS-required PostgreSQL
SSL mode, or retains a documented placeholder/default database credential.
Non-production SQLite support remains available for isolated tests.
The separate liveness probe does not query dependencies. The deployment runbook
defines first ingestion, external daily scheduling, monitoring, backups, and a
schema-safe rollback boundary; actual infrastructure provisioning and TLS
termination remain the hosting provider's responsibility.

Nginx assigns an opaque request ID at the public boundary and forwards it to the
API. The API returns that identifier in `X-Request-ID` and emits a structured
completion event containing the request method, path, status, duration,
environment, service version, and build-bound release SHA. The liveness contract
returns the same SHA, and ingestion output includes it for scheduler evidence.
Query strings and response bodies are not
logged. Nginx uses the same identifier in its own query-free structured request
event, while packaged Uvicorn commands disable the duplicate default access
line. This supplies cross-layer correlation while keeping public-data filter
values and any future sensitive parameters out of access events.

The same boundary sends a restrictive same-origin content security policy,
denies framing and unused browser capabilities, prevents MIME sniffing, and
limits referrer disclosure. Public API responses use `no-store` so a hosting
proxy, CDN, or browser cannot reuse stale readiness, ingestion-health, or live
source evidence. SPA entry documents use `no-cache` so a deployed release is
discovered promptly; content-hashed JavaScript and CSS use a one-year immutable
cache policy. Deployment CI verifies all three header classes against the
running production image.

Deployment CI also boots the production images against an ephemeral, empty
PostgreSQL instance. It verifies unsafe settings fail before startup, migration
and dependency ordering, private service networking, Nginx/API routing,
database-loss readiness behavior, request-ID propagation, database recovery,
and fail-closed migrations before a release can advance. Chromium journeys then
load the production SPA, retrieve the overview plus live CDC and FDA records,
audit the rendered views against WCAG A/AA rules, exercise visible skip links,
desktop navigation and readable two-row mobile product navigation without horizontal overflow down to the supported
320px minimum, submit live filters, restore filtered views with
browser back/forward navigation, verify filter/pagination focus order, advance
both result types, and reject horizontal mobile overflow, page errors,
same-origin request failures, or runtime content-security-policy violations.
Automated rules complement rather than
replace manual assistive-technology review.
This validates the provider-neutral runtime contract without persisting test
healthcare data. After those checks pass on `main`, separate API and frontend
images are published to GHCR under full-commit-SHA tags. OCI source metadata,
signed build provenance, and signed SPDX SBOM attestations bind each registry
digest back to the exact workflow and repository revision; production can pull
reviewed artifacts without rebuilding them on the host. The build also embeds
that revision into both images, and production API settings reject the
development placeholder. External workflow actions are pinned to full commit
SHAs, with a dedicated policy check preventing mutable action tags from entering
the CI and release path. A weekly, Actions-only Dependabot configuration keeps
those immutable pins maintainable through reviewable pull requests, while the
same policy gate rejects any proposed mutable reference. Production Compose
requires both image references and contains no build contexts. The runbook
passes the production env file at Compose interpolation time, so an omitted
release tag fails closed and a deployment host cannot locally rebuild source
under a reviewed image tag. Release CI builds its test images explicitly before
applying that pull-only runtime contract.

A separate scheduled compatibility workflow runs a bounded, read-only sample
through each production source client: one CMS hospital, the complete small CDC
measure catalog, and one newest FDA recall. It writes no database records and is
not a substitute for deployed ingestion monitoring; it detects upstream schema
or validation drift even while production provisioning remains credential-gated.

The packaged `healthscope-verify-deployment` command exercises the deployed
public HTTPS boundary after initial ingestion. It binds liveness to the approved
full release SHA, checks readiness, verifies equal ingestion and snapshot totals,
and enforces the Nginx request-ID, security-header, cache, and SPA entry-document
contract. Its output contains aggregate operational evidence only; it does not
return hospital records or access the database directly.

Backup exercises use the same reviewed API image through a separate read-only
`healthscope-verify-restore` process. It checks the restored migration revision,
newest CMS completion and exact retrieval batch, geographic totals, and matching
successful ingestion counts without migrating, ingesting, or returning facility
records. This turns restore integrity into a reproducible release contract while
keeping backup creation and restoration with the managed PostgreSQL provider.

## Next boundary

Hospital scheduling remains separate from API startup and requires a deployed
API plus database credentials. Census population and demographic context remains
a natural complement to the county explorer, but Census data queries now require
an API key. The clearly disclaimed FDA drug recall view and cross-source landing
journey are now backed by typed live API contracts. The next unblocked milestone
increment is completing the provider-neutral
[production launch checklist](launch-checklist.md), then applying the production
contract to the selected host, managed PostgreSQL instance, scheduler, and
monitor. The checklist makes provider capabilities, ownership, budget, secrets,
backup restoration, and go/no-go evidence explicit. Provisioning remains blocked
until those decisions and credentials are supplied; Census enrichment remains
queued until a Census API key is configured.
