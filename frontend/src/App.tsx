import { FormEvent, lazy, Suspense, useEffect, useState } from "react";

import { ApiError, fetchCountyHealth, fetchMeasureCatalog } from "./api";
import { STATES } from "./states";
import type {
  CommunityHealthMeasure,
  CommunityHealthMeasureCatalog,
  CountyHealthPage,
} from "./types";

const PAGE_SIZE = 25;
const PrevalenceChart = lazy(() => import("./PrevalenceChart"));
const DrugRecallExplorer = lazy(() => import("./DrugRecallExplorer"));

interface ActiveQuery {
  state: string;
  measureId: string;
  offset: number;
}

type RequestState<T> =
  | { status: "idle" | "loading" }
  | { status: "success"; data: T }
  | { status: "error"; message: string };

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  return "Something unexpected interrupted the request. Please try again.";
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatRetrievedAt(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(value));
}

function measureGroups(measures: CommunityHealthMeasure[]): Map<string, CommunityHealthMeasure[]> {
  const groups = new Map<string, CommunityHealthMeasure[]>();
  for (const measure of measures) {
    const group = groups.get(measure.category) ?? [];
    group.push(measure);
    groups.set(measure.category, group);
  }
  return groups;
}

function LoadingPanel() {
  return (
    <section className="results-card loading-card" aria-live="polite" aria-busy="true">
      <div className="skeleton skeleton-kicker" />
      <div className="skeleton skeleton-title" />
      <div className="skeleton skeleton-copy" />
      <div className="skeleton-grid">
        <div className="skeleton skeleton-block" />
        <div className="skeleton skeleton-block" />
        <div className="skeleton skeleton-block" />
      </div>
      <span className="sr-only">Loading live county health estimates</span>
    </section>
  );
}

function EmptyPanel({ onRetry }: { onRetry: () => void }) {
  return (
    <section className="results-card message-card">
      <span className="message-mark" aria-hidden="true">
        0
      </span>
      <p className="eyebrow">No reported estimates</p>
      <h2>No counties matched this view.</h2>
      <p>
        The CDC dataset does not currently report an available age-adjusted value for this state
        and measure combination.
      </p>
      <button className="text-button" type="button" onClick={onRetry}>
        Check the live source again <span aria-hidden="true">→</span>
      </button>
    </section>
  );
}

function ErrorPanel({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <section className="results-card message-card error-card" role="alert">
      <span className="message-mark" aria-hidden="true">
        !
      </span>
      <p className="eyebrow">Live data unavailable</p>
      <h2>We couldn’t refresh this view.</h2>
      <p>{message}</p>
      <button className="primary-button compact-button" type="button" onClick={onRetry}>
        Try again
      </button>
    </section>
  );
}

function ResultsPanel({
  page,
  measure,
  onPrevious,
  onNext,
}: {
  page: CountyHealthPage;
  measure: CommunityHealthMeasure | undefined;
  onPrevious: () => void;
  onNext: () => void;
}) {
  const prevalences = page.items
    .map((item) => item.prevalence_percent)
    .sort((left, right) => left - right);
  const middle = Math.floor(prevalences.length / 2);
  const median =
    prevalences.length % 2 === 0
      ? ((prevalences[middle - 1] ?? 0) + (prevalences[middle] ?? 0)) / 2
      : (prevalences[middle] ?? 0);
  const chartData = [...page.items]
    .sort((left, right) => right.prevalence_percent - left.prevalence_percent)
    .slice(0, 8)
    .map((item) => ({
      county: item.county,
      prevalence: item.prevalence_percent,
      confidence: [
        item.prevalence_percent - item.low_confidence_limit,
        item.high_confidence_limit - item.prevalence_percent,
      ] as [number, number],
    }));
  const firstRecord = page.offset + 1;
  const lastRecord = Math.min(page.offset + page.items.length, page.total);
  const pageNumber = Math.floor(page.offset / page.limit) + 1;
  const pageCount = Math.max(1, Math.ceil(page.total / page.limit));

  return (
    <div className="results-stack">
      <section className="results-card results-heading">
        <div>
          <p className="eyebrow">{page.items[0]?.category ?? measure?.category}</p>
          <h2>{page.items[0]?.measure ?? measure?.measure}</h2>
          <p className="results-context">
            {page.items[0]?.state_name} · {page.source.estimate_type} · {page.items[0]?.year}
          </p>
        </div>
        <div className="live-source">
          <span className="live-dot" />
          Live CDC data
        </div>
      </section>

      <section className="metric-grid" aria-label="Current page summary">
        <article className="metric-card accent-card">
          <p>Counties reported</p>
          <strong>{formatNumber(page.total)}</strong>
          <span>in the selected state</span>
        </article>
        <article className="metric-card">
          <p>Page median</p>
          <strong>{median.toFixed(1)}%</strong>
          <span>across {page.items.length} shown counties</span>
        </article>
        <article className="metric-card">
          <p>Measure coverage</p>
          <strong>{measure ? formatNumber(measure.county_count) : "—"}</strong>
          <span>counties nationwide in {measure?.latest_year ?? page.items[0]?.year}</span>
        </article>
      </section>

      <section className="results-card chart-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Quick comparison</p>
            <h3>Highest estimates on this page</h3>
          </div>
          <p>Whiskers show the CDC confidence interval.</p>
        </div>
        <div
          className="chart-frame"
          role="img"
          aria-label="Bar chart of the eight highest county prevalence estimates on this page"
        >
          <Suspense fallback={<div className="chart-loading">Preparing comparison…</div>}>
            <PrevalenceChart data={chartData} />
          </Suspense>
        </div>
      </section>

      <section className="results-card table-card">
        <div className="section-heading table-heading">
          <div>
            <p className="eyebrow">County detail</p>
            <h3>
              Showing {firstRecord}–{lastRecord} of {formatNumber(page.total)}
            </h3>
          </div>
          <span className="page-label">
            Page {pageNumber} / {pageCount}
          </span>
        </div>
        <div className="table-scroll">
          <table>
            <caption className="sr-only">
              County prevalence estimates and confidence intervals
            </caption>
            <thead>
              <tr>
                <th scope="col">County</th>
                <th scope="col">Estimate</th>
                <th scope="col">95% confidence interval</th>
                <th scope="col">Population</th>
                <th scope="col">FIPS</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((item) => (
                <tr key={item.county_fips}>
                  <th scope="row">{item.county} County</th>
                  <td className="estimate-cell">{item.prevalence_percent.toFixed(1)}%</td>
                  <td>
                    {item.low_confidence_limit.toFixed(1)}–
                    {item.high_confidence_limit.toFixed(1)}%
                  </td>
                  <td>{formatNumber(item.population)}</td>
                  <td className="fips-cell">{item.county_fips}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="pagination" aria-label="County result pages">
          <button type="button" onClick={onPrevious} disabled={page.offset === 0}>
            <span aria-hidden="true">←</span> Previous
          </button>
          <button
            type="button"
            onClick={onNext}
            disabled={page.offset + page.items.length >= page.total}
          >
            Next <span aria-hidden="true">→</span>
          </button>
        </div>
      </section>

      <aside className="source-note">
        <div className="source-icon" aria-hidden="true">
          i
        </div>
        <div>
          <strong>About this data</strong>
          <p>
            These are modeled county estimates, not individual diagnoses. Values come directly
            from the {page.source.dataset_name} and were retrieved by HealthScope on{" "}
            {formatRetrievedAt(page.source.retrieved_at)}.
          </p>
          <a href={page.source.dataset_url}>View the official CDC dataset</a>
        </div>
      </aside>
    </div>
  );
}

export default function App() {
  const [view, setView] = useState<"community" | "recalls">("community");
  const [catalog, setCatalog] = useState<RequestState<CommunityHealthMeasureCatalog>>({
    status: "loading",
  });
  const [catalogAttempt, setCatalogAttempt] = useState(0);
  const [selectedState, setSelectedState] = useState("AL");
  const [selectedMeasure, setSelectedMeasure] = useState("");
  const [activeQuery, setActiveQuery] = useState<ActiveQuery | null>(null);
  const [countyPage, setCountyPage] = useState<RequestState<CountyHealthPage>>({
    status: "idle",
  });
  const [countyAttempt, setCountyAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void fetchMeasureCatalog(controller.signal)
      .then((result) => {
        const initialMeasure =
          result.items.find((measure) => measure.measure_id === "DIABETES") ?? result.items[0];
        if (!initialMeasure) {
          setCatalog({ status: "error", message: "CDC returned an empty measure catalog." });
          return;
        }
        setCatalog({ status: "success", data: result });
        setSelectedMeasure(initialMeasure.measure_id);
        setCountyPage({ status: "loading" });
        setActiveQuery({ state: "AL", measureId: initialMeasure.measure_id, offset: 0 });
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setCatalog({ status: "error", message: errorMessage(error) });
        }
      });
    return () => controller.abort();
  }, [catalogAttempt]);

  useEffect(() => {
    if (!activeQuery) {
      return;
    }
    const controller = new AbortController();
    void fetchCountyHealth({
      state: activeQuery.state,
      measureId: activeQuery.measureId,
      limit: PAGE_SIZE,
      offset: activeQuery.offset,
      signal: controller.signal,
    })
      .then((result) => setCountyPage({ status: "success", data: result }))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setCountyPage({ status: "error", message: errorMessage(error) });
        }
      });
    return () => controller.abort();
  }, [activeQuery, countyAttempt]);

  const measures = catalog.status === "success" ? catalog.data.items : [];
  const groups = measureGroups(measures);
  const activeMeasure = measures.find(
    (measure) => measure.measure_id === activeQuery?.measureId,
  );

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selectedMeasure) {
      setCountyPage({ status: "loading" });
      setActiveQuery({ state: selectedState, measureId: selectedMeasure, offset: 0 });
    }
  }

  function changePage(offset: number) {
    setCountyPage({ status: "loading" });
    setActiveQuery((query) => (query ? { ...query, offset } : query));
    window.scrollTo({ top: 420, behavior: "smooth" });
  }

  function retryCatalog() {
    setCatalog({ status: "loading" });
    setCatalogAttempt((attempt) => attempt + 1);
  }

  function retryCounties() {
    setCountyPage({ status: "loading" });
    setCountyAttempt((attempt) => attempt + 1);
  }

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="#top" aria-label="HealthScope home">
          <span className="brand-mark" aria-hidden="true">
            <span />
            <span />
          </span>
          <span>HealthScope</span>
        </a>
        <nav aria-label="Primary navigation">
          <button
            className={view === "community" ? "active-nav" : undefined}
            type="button"
            onClick={() => setView("community")}
          >
            Community health
          </button>
          <button
            className={view === "recalls" ? "active-nav" : undefined}
            type="button"
            onClick={() => setView("recalls")}
          >
            Drug recalls
          </button>
        </nav>
        <span className="header-badge">Public data · No PHI</span>
      </header>

      <main id="top">
        {view === "community" ? (
          <>
        <section className="hero" id="explorer">
          <div className="hero-copy">
            <p className="eyebrow">Community health explorer</p>
            <h1>
              See the health of a state,
              <span> county by county.</span>
            </h1>
            <p className="hero-description">
              Compare current CDC PLACES estimates with their confidence intervals—clear public
              health context, directly from the source.
            </p>
          </div>

          <form className="filter-panel" onSubmit={applyFilters} aria-label="Community health filters">
            <div className="filter-field">
              <label htmlFor="state">State</label>
              <select
                id="state"
                value={selectedState}
                onChange={(event) => setSelectedState(event.target.value)}
              >
                {STATES.map(([code, name]) => (
                  <option key={code} value={code}>
                    {name}
                  </option>
                ))}
              </select>
            </div>
            <div className="filter-field measure-field">
              <label htmlFor="measure">Health measure</label>
              <select
                id="measure"
                value={selectedMeasure}
                disabled={catalog.status !== "success"}
                onChange={(event) => setSelectedMeasure(event.target.value)}
              >
                {catalog.status === "loading" && <option>Loading live measures…</option>}
                {catalog.status === "error" && <option>Measures unavailable</option>}
                {[...groups.entries()].map(([category, categoryMeasures]) => (
                  <optgroup key={category} label={category}>
                    {categoryMeasures.map((measure) => (
                      <option key={measure.measure_id} value={measure.measure_id}>
                        {measure.measure}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>
            <button
              className="primary-button"
              type="submit"
              disabled={catalog.status !== "success" || !selectedMeasure}
            >
              Explore counties <span aria-hidden="true">→</span>
            </button>
          </form>
          {catalog.status === "error" && (
            <div className="catalog-error" role="alert">
              <span>{catalog.message}</span>
              <button type="button" onClick={retryCatalog}>
                Retry measure catalog
              </button>
            </div>
          )}
        </section>

        <section className="content-wrap" aria-live="polite">
          {(countyPage.status === "idle" || countyPage.status === "loading") && <LoadingPanel />}
          {countyPage.status === "error" && (
            <ErrorPanel
              message={countyPage.message}
              onRetry={retryCounties}
            />
          )}
          {countyPage.status === "success" && countyPage.data.items.length === 0 && (
            <EmptyPanel onRetry={retryCounties} />
          )}
          {countyPage.status === "success" && countyPage.data.items.length > 0 && (
            <ResultsPanel
              page={countyPage.data}
              measure={activeMeasure}
              onPrevious={() => changePage(Math.max(0, countyPage.data.offset - PAGE_SIZE))}
              onNext={() => changePage(countyPage.data.offset + PAGE_SIZE)}
            />
          )}
        </section>
          </>
        ) : (
          <Suspense
            fallback={
              <section className="content-wrap lazy-view-loading" aria-live="polite">
                Loading the drug recall explorer…
              </section>
            }
          >
            <DrugRecallExplorer />
          </Suspense>
        )}
      </main>

      <footer id="source">
        <div>
          <a className="brand footer-brand" href="#top">
            HealthScope
          </a>
          <p>Public healthcare data, made easier to understand.</p>
        </div>
        <p>Built from official CDC and FDA public data. Not medical advice.</p>
      </footer>
    </div>
  );
}
