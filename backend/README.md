# HealthScope API

The FastAPI service that powers HealthScope.

## Local development

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
alembic upgrade head
uvicorn healthscope.main:app --reload
```

The API is available at `http://localhost:8000`, with OpenAPI documentation at
`/docs` and a health probe at `/api/v1/health`.

## Live data endpoints

`GET /api/v1/hospitals` returns a validated, paginated view of the current CMS
[Hospital General Information](https://data.cms.gov/provider-data/dataset/xubh-q36u)
dataset. Use `limit` (1–100, default 25) and `offset` (default 0) to page through
results. Every response includes the CMS source URL and retrieval timestamp.

The integration has a 10-second upstream timeout by default. Its base URL,
dataset identifier, and timeout can be changed with the variables documented in
`.env.example`.

`GET /api/v1/hospitals/snapshots/latest` returns metadata for the newest
verified complete snapshot, including its retrieval timestamp, total record
count, and hospital counts by state or territory. It returns `404` until a full
ingestion has completed. Completion is validated against rows from the exact
retrieval timestamp, so partial retries are never reported as complete.

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
if the exact retrieval batch contains every expected row. It prints a JSON
summary containing expected, fetched, and upserted counts; a source, validation,
or database failure returns exit code 1 with a JSON error on standard error.
Configure page size with
`HEALTHSCOPE_CMS_INGESTION_PAGE_SIZE` (1–100, default 100). Transient CMS
timeouts and HTTP failures use bounded exponential retries; configure them with
`HEALTHSCOPE_CMS_INGESTION_MAX_ATTEMPTS` (default 3) and
`HEALTHSCOPE_CMS_INGESTION_RETRY_DELAY_SECONDS` (default 1).

## Quality checks

```bash
ruff check .
ruff format --check .
mypy src
pytest
```
