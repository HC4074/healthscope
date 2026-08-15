# HealthScope dashboard

The responsive React dashboard for exploring live HealthScope public-health
data. The community-health view discovers its measure options from the API and
presents paginated county estimates from CDC PLACES, including confidence
intervals and source provenance. An on-demand drug-recall view presents
newest-first FDA enforcement reports with hazard-class filtering, explicit
pending-classification labels, source freshness, FDA terms, pagination, and
prominent medical-use disclaimers. It contains no bundled healthcare dataset.

`/overview` is the product landing page. It loads the CMS ingestion health,
CDC measure catalog, and a bounded FDA recall query independently, so one
unavailable source does not hide the others. The cards intentionally present
separate source status and freshness rather than combining incompatible
populations, entities, or reporting years into a synthetic KPI. Each failed
card can retry only its own source without reloading healthy cards; the overview
also retains an explicit refresh-all action. Keyboard focus moves to the settled
source card after an individual retry. Refreshing cancels requests that remain
pending and ignores any superseded completion that arrives after the newer
source result.

Both explorers are directly linkable. Submitted filters and result pages are
stored in `/community-health` or `/drug-recalls` query parameters, so shared
links and browser back/forward navigation restore the same live-data view.
Recall pagination is bounded to openFDA's official 25,000-record skip ceiling;
if a saved page falls beyond the changing live result set, the error or empty
state can return to page one without dropping the submitted hazard filter.

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
journeys read current CDC and FDA responses through the real same-origin API
path and audit the overview and explorer pages against WCAG A/AA rules. They also
verify the visible skip link, readable two-row mobile product navigation, mobile overflow
at the 320px supported minimum, submitted CDC/FDA filters, browser back/forward restoration, filter focus order,
and keyboard-operated pagination with focus recovery. They store traces,
screenshots, and video only when a run fails. The automated audit is a
regression gate, not a claim of complete accessibility or a replacement for
manual assistive-technology testing.

Component coverage also verifies that an unavailable CDC measure catalog
replaces the county loading state with one actionable error and retries the
catalog request before any county query is attempted. Overview coverage forces
an older request to settle after refresh and verifies that it cannot replace the
current source card.
