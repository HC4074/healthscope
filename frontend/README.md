# HealthScope dashboard

The responsive React dashboard for exploring live HealthScope public-health
data. The first view discovers its measure options from the API and presents
paginated county estimates from CDC PLACES, including confidence intervals and
source provenance. It contains no bundled healthcare dataset.

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
