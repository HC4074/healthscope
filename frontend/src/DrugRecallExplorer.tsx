import { FormEvent, useEffect, useState } from "react";

import { ApiError, fetchDrugRecalls } from "./api";
import type { DrugRecall, DrugRecallPage, RecallClassification } from "./types";

const PAGE_SIZE = 10;
const CLASSIFICATIONS: RecallClassification[] = ["Class I", "Class II", "Class III"];

type RequestState =
  | { status: "loading" }
  | { status: "success"; data: DrugRecallPage }
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

function formatDate(value: string | null): string {
  if (!value) {
    return "Not reported";
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T00:00:00Z`));
}

function recallLocation(recall: DrugRecall): string {
  return [recall.city, recall.state, recall.country].filter(Boolean).join(", ") || "Not reported";
}

function RecallLoading() {
  return (
    <section className="results-card loading-card" aria-live="polite" aria-busy="true">
      <div className="skeleton skeleton-kicker" />
      <div className="skeleton skeleton-title" />
      <div className="skeleton skeleton-copy" />
      <div className="recall-loading-grid">
        <div className="skeleton skeleton-recall" />
        <div className="skeleton skeleton-recall" />
      </div>
      <span className="sr-only">Loading live FDA drug recall reports</span>
    </section>
  );
}

function RecallMessage({
  kind,
  message,
  onRetry,
}: {
  kind: "empty" | "error";
  message: string;
  onRetry: () => void;
}) {
  return (
    <section className={`results-card message-card ${kind === "error" ? "error-card" : ""}`} role={kind === "error" ? "alert" : undefined}>
      <span className="message-mark" aria-hidden="true">{kind === "error" ? "!" : "0"}</span>
      <p className="eyebrow">{kind === "error" ? "Live data unavailable" : "No recall reports"}</p>
      <h2>{kind === "error" ? "We couldn’t refresh FDA reports." : "No reports matched this filter."}</h2>
      <p>{message}</p>
      <button className={kind === "error" ? "primary-button compact-button" : "text-button"} type="button" onClick={onRetry}>
        {kind === "error" ? "Try again" : "Check the live source again"}
      </button>
    </section>
  );
}

function RecallResults({
  page,
  onPrevious,
  onNext,
}: {
  page: DrugRecallPage;
  onPrevious: () => void;
  onNext: () => void;
}) {
  const firstRecord = page.offset + 1;
  const lastRecord = Math.min(page.offset + page.items.length, page.total);
  const pageNumber = Math.floor(page.offset / page.limit) + 1;
  const pageCount = Math.max(1, Math.ceil(page.total / page.limit));

  return (
    <div className="results-stack">
      <section className="results-card recall-summary">
        <div>
          <p className="eyebrow">FDA enforcement reports</p>
          <h2>{page.classification ?? "All drug recall classes"}</h2>
          <p>
            Showing {formatNumber(firstRecord)}–{formatNumber(lastRecord)} of {formatNumber(page.total)} newest-first reports.
          </p>
        </div>
        <div className="recall-freshness">
          <span>Source updated</span>
          <strong>{formatDate(page.source.last_updated)}</strong>
        </div>
      </section>

      <section className="recall-list" aria-label="Drug recall reports">
        {page.items.map((recall) => (
          <article className="results-card recall-card" key={recall.recall_number}>
            <div className="recall-card-heading">
              <div>
                <span className={`classification-badge class-${recall.classification.replace("Class ", "").toLowerCase()}`}>
                  {recall.classification}
                </span>
                {recall.status && <span className="status-badge">{recall.status}</span>}
              </div>
              <time dateTime={recall.report_date}>Reported {formatDate(recall.report_date)}</time>
            </div>
            <h3>{recall.recalling_firm}</h3>
            <p className="recall-product">{recall.product_description}</p>
            <dl className="recall-detail-grid">
              <div>
                <dt>Reason for recall</dt>
                <dd>{recall.reason_for_recall}</dd>
              </div>
              <div>
                <dt>Distribution</dt>
                <dd>{recall.distribution_pattern}</dd>
              </div>
              <div>
                <dt>Firm location</dt>
                <dd>{recallLocation(recall)}</dd>
              </div>
              <div>
                <dt>Recall initiated</dt>
                <dd>{formatDate(recall.recall_initiation_date)}</dd>
              </div>
            </dl>
            <p className="recall-id">Recall {recall.recall_number}{recall.event_id ? ` · Event ${recall.event_id}` : ""}</p>
          </article>
        ))}
      </section>

      <section className="results-card recall-pagination">
        <span>Page {pageNumber} / {pageCount}</span>
        <div className="pagination" aria-label="Drug recall result pages">
          <button type="button" onClick={onPrevious} disabled={page.offset === 0}>← Previous</button>
          <button type="button" onClick={onNext} disabled={page.offset + page.items.length >= page.total}>Next →</button>
        </div>
      </section>

      <aside className="source-note recall-source-note">
        <div className="source-icon" aria-hidden="true">i</div>
        <div>
          <strong>FDA source and use notice</strong>
          <p>{page.source.disclaimer}</p>
          <p>
            Enforcement reports describe FDA-regulated recalls and may change as investigations progress. They are not a complete list of public alerts and do not replace guidance from FDA or a healthcare professional.
          </p>
          <div className="source-links">
            <a href={page.source.dataset_url}>View the official FDA dataset</a>
            <a href={page.source.terms_url}>FDA terms</a>
            <a href={page.source.license_url}>FDA license</a>
          </div>
        </div>
      </aside>
    </div>
  );
}

export default function DrugRecallExplorer() {
  const [selectedClassification, setSelectedClassification] = useState<RecallClassification | "">("");
  const [activeClassification, setActiveClassification] = useState<RecallClassification | undefined>();
  const [offset, setOffset] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [page, setPage] = useState<RequestState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    void fetchDrugRecalls({
      classification: activeClassification,
      limit: PAGE_SIZE,
      offset,
      signal: controller.signal,
    })
      .then((result) => setPage({ status: "success", data: result }))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setPage({ status: "error", message: errorMessage(error) });
        }
      });
    return () => controller.abort();
  }, [activeClassification, offset, attempt]);

  function applyFilter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage({ status: "loading" });
    setOffset(0);
    setActiveClassification(selectedClassification || undefined);
    setAttempt((value) => value + 1);
  }

  function changePage(nextOffset: number) {
    setPage({ status: "loading" });
    setOffset(nextOffset);
    window.scrollTo({ top: 420, behavior: "smooth" });
  }

  function retry() {
    setPage({ status: "loading" });
    setAttempt((value) => value + 1);
  }

  return (
    <>
      <section className="hero recall-hero" id="recalls">
        <div className="hero-copy">
          <p className="eyebrow">Drug recall explorer</p>
          <h1>Follow public drug recalls,<span> straight from FDA.</span></h1>
          <p className="hero-description">
            Review newest-first FDA enforcement reports, including the product, recall reason, distribution, and hazard classification.
          </p>
        </div>

        <aside className="recall-warning" aria-label="Medical safety notice">
          <strong>Do not change or stop medication based on this dashboard.</strong>
          <span>Confirm the product and recall with FDA, then contact a pharmacist or clinician for personal guidance.</span>
        </aside>

        <form className="filter-panel recall-filter" onSubmit={applyFilter} aria-label="Drug recall filters">
          <div className="filter-field">
            <label htmlFor="classification">Hazard classification</label>
            <select id="classification" value={selectedClassification} onChange={(event) => setSelectedClassification(event.target.value as RecallClassification | "")}>
              <option value="">All classifications</option>
              {CLASSIFICATIONS.map((classification) => <option key={classification}>{classification}</option>)}
            </select>
          </div>
          <p>Class I has the highest potential health risk; classification is assigned by FDA.</p>
          <button className="primary-button" type="submit">Apply filter <span aria-hidden="true">→</span></button>
        </form>
      </section>

      <section className="content-wrap" aria-live="polite">
        {page.status === "loading" && <RecallLoading />}
        {page.status === "error" && <RecallMessage kind="error" message={page.message} onRetry={retry} />}
        {page.status === "success" && page.data.items.length === 0 && (
          <RecallMessage kind="empty" message="FDA does not currently return reports for this selection." onRetry={retry} />
        )}
        {page.status === "success" && page.data.items.length > 0 && (
          <RecallResults
            page={page.data}
            onPrevious={() => changePage(Math.max(0, page.data.offset - PAGE_SIZE))}
            onNext={() => changePage(page.data.offset + PAGE_SIZE)}
          />
        )}
      </section>
    </>
  );
}
