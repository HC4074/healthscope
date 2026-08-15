import { type MouseEvent, useEffect, useRef, useState } from "react";

import {
  ApiError,
  fetchDrugRecalls,
  fetchHospitalIngestionHealth,
  fetchMeasureCatalog,
} from "./api";
import { dashboardRouteUrl, type DashboardRoute } from "./routing";
import type {
  CommunityHealthMeasureCatalog,
  DrugRecallPage,
  HospitalIngestionHealth,
} from "./types";

type SourceState<T> =
  | { status: "loading" }
  | { status: "success"; data: T }
  | { status: "error"; message: string };

interface OverviewProps {
  onNavigate: (route: DashboardRoute) => void;
}

interface RecoverableCardProps {
  focusOnMount: boolean;
}

function useFocusOnMount(enabled: boolean) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (enabled) {
      ref.current?.focus();
    }
  }, [enabled]);
  return ref;
}

function messageFor(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "This source could not be refreshed. The other sources remain available.";
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(value));
}

function followLink(
  event: MouseEvent<HTMLAnchorElement>,
  route: DashboardRoute,
  onNavigate: (route: DashboardRoute) => void,
) {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return;
  }
  event.preventDefault();
  onNavigate(route);
}

function LoadingCard({ source }: { source: string }) {
  return (
    <article className="source-overview-card source-overview-loading" aria-busy="true">
      <p className="source-overview-agency">{source}</p>
      <div className="skeleton skeleton-title" />
      <div className="skeleton skeleton-copy" />
      <span className="sr-only">Loading {source} status</span>
    </article>
  );
}

function ErrorCard({
  source,
  message,
  onRetry,
  focusOnMount,
}: {
  source: string;
  message: string;
  onRetry: () => void;
} & RecoverableCardProps) {
  const cardRef = useFocusOnMount(focusOnMount);
  return (
    <article
      className="source-overview-card source-overview-error"
      ref={cardRef}
      tabIndex={focusOnMount ? -1 : undefined}
    >
      <p className="source-overview-agency">{source}</p>
      <h2>Source temporarily unavailable</h2>
      <p>{message}</p>
      <span className="source-status source-status-warning">Refresh needed</span>
      <button className="text-button source-overview-retry" type="button" onClick={onRetry}>
        Retry {source}
      </button>
    </article>
  );
}

function CmsCard({
  health,
  focusOnMount,
}: { health: HospitalIngestionHealth } & RecoverableCardProps) {
  const cardRef = useFocusOnMount(focusOnMount);
  const run = health.latest_run;
  const recordCount = run?.expected_count ?? run?.upserted_count ?? null;
  const freshness = run?.latest_successful_retrieved_at;
  const statusText = health.healthy
    ? health.reason === "ingestion_in_progress"
      ? "Refreshing"
      : "Fresh"
    : health.reason === "no_runs"
      ? "Awaiting first snapshot"
      : health.reason === "stale"
        ? "Stale"
        : "Latest run failed";

  return (
    <article
      className="source-overview-card"
      ref={cardRef}
      tabIndex={focusOnMount ? -1 : undefined}
    >
      <div className="source-overview-heading">
        <p className="source-overview-agency">Centers for Medicare & Medicaid Services</p>
        <span className={`source-status ${health.healthy ? "" : "source-status-warning"}`}>
          {statusText}
        </span>
      </div>
      <h2>Hospital coverage</h2>
      <strong className="source-overview-metric">
        {recordCount === null ? "Not available" : formatNumber(recordCount)}
      </strong>
      <p>
        {recordCount === null
          ? "No verified CMS hospital snapshot has been completed yet."
          : `Medicare-registered hospital records in the latest ingestion run${
              freshness ? `, retrieved ${formatDate(freshness)}` : ""
            }.`}
      </p>
      <a
        className="source-overview-link"
        href="https://data.cms.gov/provider-data/dataset/xubh-q36u"
      >
        View the official CMS dataset <span aria-hidden="true">↗</span>
      </a>
    </article>
  );
}

function CdcCard({
  catalog,
  onNavigate,
  focusOnMount,
}: { catalog: CommunityHealthMeasureCatalog } & OverviewProps & RecoverableCardProps) {
  const cardRef = useFocusOnMount(focusOnMount);
  const latestYear = Math.max(...catalog.items.map((measure) => measure.latest_year));
  const route: DashboardRoute = { view: "community", state: "AL", offset: 0 };
  return (
    <article
      className="source-overview-card"
      ref={cardRef}
      tabIndex={focusOnMount ? -1 : undefined}
    >
      <div className="source-overview-heading">
        <p className="source-overview-agency">Centers for Disease Control and Prevention</p>
        <span className="source-status">Live catalog</span>
      </div>
      <h2>Community health</h2>
      <strong className="source-overview-metric">{formatNumber(catalog.total)} measures</strong>
      <p>
        Age-adjusted county estimates from CDC PLACES, with the newest available measure year of {" "}
        {latestYear}.
      </p>
      <a
        className="source-overview-link"
        href={dashboardRouteUrl(route)}
        onClick={(event) => followLink(event, route, onNavigate)}
      >
        Explore county health <span aria-hidden="true">→</span>
      </a>
    </article>
  );
}

function FdaCard({
  recalls,
  onNavigate,
  focusOnMount,
}: { recalls: DrugRecallPage } & OverviewProps & RecoverableCardProps) {
  const cardRef = useFocusOnMount(focusOnMount);
  const route: DashboardRoute = { view: "recalls", offset: 0 };
  return (
    <article
      className="source-overview-card"
      ref={cardRef}
      tabIndex={focusOnMount ? -1 : undefined}
    >
      <div className="source-overview-heading">
        <p className="source-overview-agency">U.S. Food and Drug Administration</p>
        <span className="source-status">Updated {formatDate(recalls.source.last_updated)}</span>
      </div>
      <h2>Drug recalls</h2>
      <strong className="source-overview-metric">{formatNumber(recalls.total)} reports</strong>
      <p>
        Newest-first FDA enforcement reports. Recall classifications describe hazard severity and
        are not medical advice.
      </p>
      <a
        className="source-overview-link"
        href={dashboardRouteUrl(route)}
        onClick={(event) => followLink(event, route, onNavigate)}
      >
        Review drug recalls <span aria-hidden="true">→</span>
      </a>
    </article>
  );
}

export default function Overview({ onNavigate }: OverviewProps) {
  const [cmsAttempt, setCmsAttempt] = useState(0);
  const [cdcAttempt, setCdcAttempt] = useState(0);
  const [fdaAttempt, setFdaAttempt] = useState(0);
  const [focusAfterRetry, setFocusAfterRetry] = useState<"cms" | "cdc" | "fda" | null>(null);
  const [cms, setCms] = useState<SourceState<HospitalIngestionHealth>>({ status: "loading" });
  const [cdc, setCdc] = useState<SourceState<CommunityHealthMeasureCatalog>>({ status: "loading" });
  const [fda, setFda] = useState<SourceState<DrugRecallPage>>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    void fetchHospitalIngestionHealth(controller.signal)
      .then((data) => setCms({ status: "success", data }))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setCms({ status: "error", message: messageFor(error) });
        }
      });
    return () => controller.abort();
  }, [cmsAttempt]);

  useEffect(() => {
    const controller = new AbortController();
    void fetchMeasureCatalog(controller.signal)
      .then((data) => setCdc({ status: "success", data }))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setCdc({ status: "error", message: messageFor(error) });
        }
      });
    return () => controller.abort();
  }, [cdcAttempt]);

  useEffect(() => {
    const controller = new AbortController();
    void fetchDrugRecalls({ limit: 1, offset: 0, signal: controller.signal })
      .then((data) => setFda({ status: "success", data }))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setFda({ status: "error", message: messageFor(error) });
        }
      });
    return () => controller.abort();
  }, [fdaAttempt]);

  function retryCms() {
    setFocusAfterRetry("cms");
    setCms({ status: "loading" });
    setCmsAttempt((value) => value + 1);
  }

  function retryCdc() {
    setFocusAfterRetry("cdc");
    setCdc({ status: "loading" });
    setCdcAttempt((value) => value + 1);
  }

  function retryFda() {
    setFocusAfterRetry("fda");
    setFda({ status: "loading" });
    setFdaAttempt((value) => value + 1);
  }

  function retryAll() {
    setFocusAfterRetry(null);
    setCms({ status: "loading" });
    setCdc({ status: "loading" });
    setFda({ status: "loading" });
    setCmsAttempt((value) => value + 1);
    setCdcAttempt((value) => value + 1);
    setFdaAttempt((value) => value + 1);
  }

  return (
    <>
      <section className="hero overview-hero">
        <div className="hero-copy">
          <p className="eyebrow">Public healthcare intelligence</p>
          <h1>
            Three trusted sources,
            <span> one clear starting point.</span>
          </h1>
          <p className="hero-description">
            Monitor CMS hospital data, explore CDC county health, and review FDA drug recalls from
            independent live public sources.
          </p>
        </div>
        <aside className="overview-boundary">
          <strong>Read each signal in its own context.</strong>
          <span>HealthScope does not merge unrelated populations, entities, or reporting years.</span>
        </aside>
      </section>

      <section className="content-wrap overview-content" aria-live="polite">
        <div className="overview-section-heading">
          <div>
            <p className="eyebrow">Source pulse</p>
            <h2>What is available now</h2>
          </div>
          <button className="text-button" type="button" onClick={retryAll}>
            Refresh all sources
          </button>
        </div>
        <div className="source-overview-grid">
          {cms.status === "loading" && <LoadingCard source="CMS" />}
          {cms.status === "error" && (
            <ErrorCard
              source="CMS"
              message={cms.message}
              onRetry={retryCms}
              focusOnMount={focusAfterRetry === "cms"}
            />
          )}
          {cms.status === "success" && (
            <CmsCard health={cms.data} focusOnMount={focusAfterRetry === "cms"} />
          )}

          {cdc.status === "loading" && <LoadingCard source="CDC" />}
          {cdc.status === "error" && (
            <ErrorCard
              source="CDC"
              message={cdc.message}
              onRetry={retryCdc}
              focusOnMount={focusAfterRetry === "cdc"}
            />
          )}
          {cdc.status === "success" && (
            <CdcCard
              catalog={cdc.data}
              onNavigate={onNavigate}
              focusOnMount={focusAfterRetry === "cdc"}
            />
          )}

          {fda.status === "loading" && <LoadingCard source="FDA" />}
          {fda.status === "error" && (
            <ErrorCard
              source="FDA"
              message={fda.message}
              onRetry={retryFda}
              focusOnMount={focusAfterRetry === "fda"}
            />
          )}
          {fda.status === "success" && (
            <FdaCard
              recalls={fda.data}
              onNavigate={onNavigate}
              focusOnMount={focusAfterRetry === "fda"}
            />
          )}
        </div>
      </section>
    </>
  );
}
