# HealthScope API

The FastAPI service that powers HealthScope.

## Local development

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
alembic upgrade head
uvicorn healthscope.main:app --reload --no-access-log
```

The API is available at `http://localhost:8000`, with OpenAPI documentation at
`/docs` and a health probe at `/api/v1/health`.

`GET /api/v1/ready` additionally verifies database connectivity. It returns
`503` without exposing connection details when PostgreSQL is unavailable and is
the correct container-orchestrator traffic readiness probe. Liveness remains
separate so operators can distinguish a running process from a database outage.

Every API response includes `X-Request-ID`. The production Nginx proxy assigns
a fresh 32-character request ID before forwarding the request; direct API calls
may supply a safe 1-128 character identifier using letters, digits, `.`, `_`,
`:`, or `-`. Unsafe values are replaced with a UUID. The API logs one JSON
completion event with the same ID, method, path, status, duration, environment,
service version, and build-bound release SHA. The liveness response exposes the
same SHA for deployment evidence. Query strings are deliberately omitted so filters, future
credentials, and other request parameters do not enter access logs.
Packaged and Compose launch commands disable Uvicorn's duplicate access line,
which otherwise includes the query string.

## Live data endpoints

`GET /api/v1/hospitals` returns a validated, paginated view of the current CMS
[Hospital General Information](https://data.cms.gov/provider-data/dataset/xubh-q36u)
dataset. Use `limit` (1–100, default 25) and `offset` (default 0) to page through
results. Every response includes the CMS source URL and retrieval timestamp.

The integration has a 10-second upstream timeout by default. Its base URL,
dataset identifier, and timeout can be changed with the variables documented in
`.env.example`.

`GET /api/v1/community-health/counties` returns current county-level prevalence
estimates from the official CDC
[PLACES 2025 county dataset](https://data.cdc.gov/d/swc5-untb). The required
`state` parameter is an uppercase two-letter code and `measure_id` is a CDC
measure identifier such as `DIABETES`, `OBESITY`, or `ACCESS2`. Use `limit`
(1-100, default 25) and `offset` (default 0) to page through matching counties.
For comparable county KPIs, HealthScope requests age-adjusted prevalence rows
with available values and returns CDC confidence intervals, population context,
coordinates, provenance, and the filtered total. Invalid filters are rejected
before they reach the upstream query.

`GET /api/v1/community-health/measures` discovers the age-adjusted prevalence
measures currently available in that live dataset. Each measure includes its CDC
identifier, label, category, latest data year, and number of counties with an
available value, so clients can build filters without a hard-coded catalog.
The response is grouped and derived by CDC at request time and includes the same
source provenance as county estimates.

The CDC base URL, dataset identifier, and 10-second request timeout can be
changed with `HEALTHSCOPE_CDC_DATA_BASE_URL`,
`HEALTHSCOPE_CDC_PLACES_COUNTY_DATASET_ID`, and
`HEALTHSCOPE_CDC_REQUEST_TIMEOUT_SECONDS`.

`GET /api/v1/drug-recalls` returns newest-first publicly releasable drug recall
enforcement reports from the official FDA Recall Enterprise System through
openFDA. Use `classification` (`Class I`, `Class II`, or `Class III`) to apply an
exact health-hazard class filter, and `limit` (1-100, default 25) plus `offset`
(0-25,900) for bounded paging. Responses include FDA's dataset update date,
disclaimer, terms, license, and retrieval timestamp. Recall reports are public
context only: FDA explicitly warns against using openFDA for medical-care
decisions, public alerts, or recall lifecycle tracking.
Optional legacy fields that openFDA reports as blank or `N/A` are normalized to
`null`, including foreign recalling-firm state values and the not-yet-assigned
recall number on pending classifications. Unfiltered pages accept FDA's official
`Not Yet Classified` value while keeping the query filter limited to assigned
health-hazard classes.

The FDA base URL and 10-second request timeout can be changed with
`HEALTHSCOPE_FDA_API_BASE_URL` and `HEALTHSCOPE_FDA_REQUEST_TIMEOUT_SECONDS`.
Anonymous requests use openFDA's public quota. Set the optional secret
`HEALTHSCOPE_FDA_API_KEY` to use the larger authenticated daily quota; the key is
passed only to FDA and is never returned by HealthScope.

`GET /api/v1/hospitals/snapshots/latest` returns metadata for the newest
verified complete snapshot, including its retrieval timestamp, total record
count, and hospital counts by state or territory. It returns `404` until a full
ingestion has completed. Completion is validated against rows from the exact
retrieval timestamp, so partial retries are never reported as complete.

`GET /api/v1/hospitals/ingestion/latest` returns the latest ingestion run's
started, succeeded, or failed state, progress counters, bounded failure detail,
and the age of the most recent successful snapshot. It reports `is_stale` when
no run has succeeded or the latest successful retrieval exceeds
`HEALTHSCOPE_CMS_INGESTION_STALE_AFTER_HOURS` (default 26 hours), making the
endpoint suitable for an external scheduler or monitor.

`GET /api/v1/hospitals/ingestion/health` is the monitor-ready counterpart. It
returns `200` while the latest complete snapshot is fresh, including while a new
refresh is in progress. It returns `503` with a machine-readable reason when no
run exists, the latest run failed, or the last complete snapshot is stale.
External uptime monitors can alert on the HTTP status without parsing freshness
fields.

## Database and migrations

PostgreSQL stores daily CMS hospital snapshots. The snapshot key combines the
CMS dataset ID, UTC retrieval date, and facility ID, so rerunning a refresh on
the same day updates the observation without creating duplicates. A refresh on
a later day preserves a new historical observation.

Set `HEALTHSCOPE_DATABASE_URL` for the target PostgreSQL instance and apply
migrations before starting the API:

```bash
alembic upgrade head
```

Docker Compose supplies the container database URL and applies pending
migrations automatically when the API container starts.

When `HEALTHSCOPE_ENVIRONMENT=production`, settings validation fails before API
startup, migration, or ingestion if debug mode is enabled, the image does not
provide a full 40-character `HEALTHSCOPE_RELEASE_SHA`, the database URL is
not PostgreSQL, does not require TLS with `sslmode=require`, `verify-ca`, or
`verify-full`, or retains a documented placeholder/default database host or
password. Development and test environments keep SQLite support for isolated
tests. See the production deployment runbook for the managed-database contract.

## Public-source compatibility check

Run the bounded, read-only compatibility check for every current official data
source without requiring a database:

```bash
healthscope-check-public-sources
```

The command retrieves one CMS hospital, the current CDC PLACES measure catalog,
and one newest FDA drug recall through the same typed clients used by the API.
It emits a JSON summary and exits nonzero on transport, validation, or empty-CMS
failures. GitHub Actions runs this check daily and also supports manual dispatch;
it never persists the retrieved records.

## Hospital snapshot ingestion

After applying migrations, run the explicit one-shot command to retrieve every
current record from the official CMS Hospital General Information dataset:

```bash
healthscope-ingest-hospitals
```

With Docker Compose, start PostgreSQL and run the same packaged command:

```bash
docker compose up -d database
docker compose run --rm api healthscope-ingest-hospitals
```

The command uses one UTC retrieval timestamp for the entire snapshot, validates
that CMS pagination remains consistent, and commits pages in bounded batches.
Same-day reruns are idempotent and can safely resume a partially completed run.
After the last page is persisted, the command records a completion marker only
if the exact retrieval batch contains every expected row. Every invocation also
persists a durable run ID, lifecycle state, progress counts, and bounded failure
detail. A terminated process remains in `started` state so monitoring can detect
an abandoned run. The command prints a JSON summary containing the run ID plus
expected, fetched, and upserted counts; a source, validation, or database failure
returns exit code 1 with a JSON error on standard error.
On PostgreSQL, the command acquires a dataset-scoped advisory lock before it
opens the CMS client. A concurrent invocation performs no source requests and
exits nonzero with `HospitalIngestionAlreadyRunningError`, allowing the
scheduler to alert without duplicating a full ingestion.
Success and operational-error JSON include the image's release SHA so retained
scheduler output can be tied to the deployed artifact.
Configure page size with
`HEALTHSCOPE_CMS_INGESTION_PAGE_SIZE` (1–100, default 100). Transient CMS
timeouts and HTTP failures use bounded exponential retries; configure them with
`HEALTHSCOPE_CMS_INGESTION_MAX_ATTEMPTS` (default 3) and
`HEALTHSCOPE_CMS_INGESTION_RETRY_DELAY_SECONDS` (default 1).

## Restored database verification

Run the packaged read-only verifier against an isolated restored database before
launch and after every restore exercise:

```bash
healthscope-verify-restore
```

The command requires the configured database to be at this release's exact
Alembic head. It validates the newest CMS completion marker against rows from
the same retrieval batch and state totals, then requires a matching successful
ingestion run whose expected, fetched, and upserted counts all equal the
snapshot count. Successful output contains only the schema revision, dataset
ID, retrieval and completion timestamps, aggregate counts, and run ID. It does
not return hospital records. Any missing or inconsistent evidence exits with
status 1 and structured JSON on standard error.

## Quality checks

```bash
ruff check .
ruff format --check .
mypy src
pytest
```
