# HealthScope dashboard

The responsive React dashboard for exploring live HealthScope public-health
data. The community-health view discovers its measure options from the API and
presents paginated county estimates from CDC PLACES, including confidence
intervals and source provenance. An on-demand drug-recall view presents
newest-first FDA enforcement reports with hazard-class filtering, source
freshness, FDA terms, pagination, and prominent medical-use disclaimers. It
contains no bundled healthcare dataset.

`/overview` is the product landing page. It loads the CMS ingestion health,
CDC measure catalog, and a bounded FDA recall query independently, so one
unavailable source does not hide the others. The cards intentionally present
separate source status and freshness rather than combining incompatible
populations, entities, or reporting years into a synthetic KPI.

Both explorers are directly linkable. Submitted filters and result pages are
stored in `/community-health` or `/drug-recalls` query parameters, so shared
links and browser back/forward navigation restore the same live-data view.

The production Nginx boundary sends a restrictive same-origin content security
policy and browser hardening headers on dashboard and API responses. SPA entry
documents are revalidated on every visit, while content-hashed JavaScript and
CSS assets are cached immutably for one year.

## Local development

Run the API on port 8000, then start the Vite development server:

```bash
npm install
npm run dev
```

Vite proxies `/api` to `http://localhost:8000`. Override the development target
with `HEALTHSCOPE_API_PROXY_TARGET`. A separately hosted frontend can set
`VITE_API_BASE_URL` at build time; leaving it empty keeps requests same-origin.

## Quality checks

```bash
npm run lint
npm run test
npm run build
```

The production release harness also runs the Chromium journey against the
Compose-served application. With that stack already listening on port 18080,
install Chromium once with `npx --no-install playwright install chromium`, then
run:

```bash
npm run test:e2e
```

Set `HEALTHSCOPE_E2E_BASE_URL` when the release stack uses another origin. The
journey reads current CDC responses through the real same-origin API path and
stores traces, screenshots, and video only when a run fails.
