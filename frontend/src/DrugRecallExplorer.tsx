import { FormEvent, type RefObject, useEffect, useRef, useState } from "react";

import { ApiError, fetchDrugRecalls } from "./api";
import { RECALL_PAGE_SIZE, type RecallRoute } from "./routing";
import type { DrugRecall, DrugRecallPage, RecallClassification } from "./types";

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

function classificationClass(recall: DrugRecall): string {
  return recall.classification === "Not Yet Classified"
    ? "pending-classification"
    : `class-${recall.classification.replace("Class ", "").toLowerCase()}`;
}

function recallKey(recall: DrugRecall): string {
  return [
    recall.recall_number ?? "pending",
    recall.event_id ?? "no-event",
    recall.product_description,
  ].join(":");
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
  onReturnToFirstPage,
}: {
  kind: "empty" | "error";
  message: string;
  onRetry: () => void;
  onReturnToFirstPage?: () => void;
}) {
  const retryLabel = kind === "error" ? "Try again" : "Check the live source again";
  return (
    <section
      className={`results-card message-card ${kind === "error" ? "error-card" : ""}`}
      role={kind === "error" ? "alert" : undefined}
    >
      <span className="message-mark" aria-hidden="true">{kind === "error" ? "!" : "0"}</span>
      <p className="eyebrow">{kind === "error" ? "Live data unavailable" : "No recall reports"}</p>
      <h2>{kind === "error" ? "We couldn’t refresh FDA reports." : "No reports matched this filter."}</h2>
      <p>{message}</p>
      <div className="message-actions">
        {onReturnToFirstPage && (
          <button
            className="primary-button compact-button"
            type="button"
            onClick={onReturnToFirstPage}
          >
            Return to first page
          </button>
        )}
        <button
          className={
            onReturnToFirstPage || kind === "empty"
              ? "text-button"
              : "primary-button compact-button"
          }
          type="button"
          onClick={onRetry}
        >
          {onReturnToFirstPage ? "Try this page again" : retryLabel}
        </button>
      </div>
    </section>
  );
}

function RecallResults({
  page,
  onPrevious,
  onNext,
  pageHeadingRef,
}: {
  page: DrugRecallPage;
  onPrevious: () => void;
  onNext: () => void;
  pageHeadingRef: RefObject<HTMLHeadingElement | null>;
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
          <h2 ref={pageHeadingRef} tabIndex={-1}>
            {page.classification ?? "All drug recall classes"}
          </h2>
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
          <article className="results-card recall-card" key={recallKey(recall)}>
            <div className="recall-card-heading">
              <div>
                <span className={`classification-badge ${classificationClass(recall)}`}>
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
            <p className="recall-id">
              {recall.recall_number ? `Recall ${recall.recall_number}` : "Recall number pending"}
              {recall.event_id ? ` · Event ${recall.event_id}` : ""}
            </p>
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

interface DrugRecallExplorerProps {
  route: RecallRoute;
  onNavigate: (route: RecallRoute) => void;
}

export default function DrugRecallExplorer({ route, onNavigate }: DrugRecallExplorerProps) {
  const [selectedClassification, setSelectedClassification] = useState<RecallClassification | "">(
    route.classification ?? "",
  );
  const [attempt, setAttempt] = useState(0);
  const [page, setPage] = useState<RequestState>({ status: "loading" });
  const pendingPageFocus = useRef<number | null>(null);
  const pageHeadingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    let isPending = true;
    void fetchDrugRecalls({
      classification: route.classification,
      limit: RECALL_PAGE_SIZE,
      offset: route.offset,
      signal: controller.signal,
    })
      .then((result) => {
        isPending = false;
        setPage({ status: "success", data: result });
      })
      .catch((error: unknown) => {
        isPending = false;
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setPage({ status: "error", message: errorMessage(error) });
        }
      });
    return () => {
      if (isPending) {
        controller.abort();
      }
    };
  }, [route.classification, route.offset, attempt]);

  useEffect(() => {
    if (page.status === "success" && page.data.offset === pendingPageFocus.current) {
      pageHeadingRef.current?.focus();
      pendingPageFocus.current = null;
    }
  }, [page]);

  function applyFilter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage({ status: "loading" });
    onNavigate({
      view: "recalls",
      classification: selectedClassification || undefined,
      offset: 0,
    });
    setAttempt((value) => value + 1);
  }

  function changePage(nextOffset: number) {
    pendingPageFocus.current = nextOffset;
    setPage({ status: "loading" });
    onNavigate({ ...route, offset: nextOffset });
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
          <p>
            Class I has the highest potential health risk. Unfiltered results can also include
            recalls FDA has not yet classified.
          </p>
          <button className="primary-button" type="submit">Apply filter <span aria-hidden="true">→</span></button>
        </form>
      </section>

      <section className="content-wrap" aria-live="polite">
        {page.status === "loading" && <RecallLoading />}
        {page.status === "error" && (
          <RecallMessage
            kind="error"
            message={page.message}
            onRetry={retry}
            onReturnToFirstPage={route.offset > 0 ? () => changePage(0) : undefined}
          />
        )}
        {page.status === "success" && page.data.items.length === 0 && (
          <RecallMessage
            kind="empty"
            message="FDA does not currently return reports for this selection."
            onRetry={retry}
            onReturnToFirstPage={route.offset > 0 ? () => changePage(0) : undefined}
          />
        )}
        {page.status === "success" && page.data.items.length > 0 && (
          <RecallResults
            page={page.data}
            onPrevious={() => changePage(Math.max(0, page.data.offset - RECALL_PAGE_SIZE))}
            onNext={() => changePage(page.data.offset + RECALL_PAGE_SIZE)}
            pageHeadingRef={pageHeadingRef}
          />
        )}
      </section>
    </>
  );
}
