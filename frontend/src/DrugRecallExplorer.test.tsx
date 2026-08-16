import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DrugRecallExplorer from "./DrugRecallExplorer";
import { fetchDrugRecalls } from "./api";
import type { RecallRoute } from "./routing";
import type { DrugRecallPage } from "./types";

vi.mock("./api", () => ({
  ApiError: class ApiError extends Error {
    constructor(message: string, readonly status: number) {
      super(message);
    }
  },
  fetchDrugRecalls: vi.fn(),
}));

const recallPage: DrugRecallPage = {
  items: [
    {
      recall_number: "D-0689-2026",
      event_id: "99376",
      classification: "Class II",
      status: "Ongoing",
      recalling_firm: "Chiesi USA, Inc.",
      city: "Cary",
      state: "NC",
      country: "United States",
      product_description: "CLEVIPREX (clevidipine injectable emulsion), Rx Only",
      reason_for_recall: "Lack of Assurance of Sterility",
      voluntary_mandated: "Voluntary: Firm initiated",
      distribution_pattern: "Nationwide within the United States",
      product_quantity: "44280 vials",
      recall_initiation_date: "2026-07-06",
      report_date: "2026-07-22",
    },
  ],
  total: 17832,
  limit: 10,
  offset: 0,
  classification: null,
  source: {
    name: "U.S. Food and Drug Administration",
    dataset_name: "Drug Recall Enforcement Reports",
    dataset_url: "https://open.fda.gov/apis/drug/enforcement/",
    retrieved_at: "2026-08-02T12:00:00Z",
    last_updated: "2026-07-22",
    disclaimer: "Do not rely on openFDA to make decisions regarding medical care.",
    terms_url: "https://open.fda.gov/terms/",
    license_url: "https://open.fda.gov/license/",
  },
};
const capturedRecall = recallPage.items[0];
if (!capturedRecall) {
  throw new Error("The captured FDA page must include one recall.");
}

const mockedRecalls = vi.mocked(fetchDrugRecalls);
const defaultRoute: RecallRoute = { view: "recalls", offset: 0 };

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

function renderExplorer(
  route: RecallRoute = defaultRoute,
  onNavigate = vi.fn(),
) {
  return {
    onNavigate,
    ...render(<DrugRecallExplorer route={route} onNavigate={onNavigate} />),
  };
}

describe("drug recall explorer", () => {
  beforeEach(() => {
    mockedRecalls.mockResolvedValue(recallPage);
  });

  it("renders current FDA reports, provenance, and medical-use warnings", async () => {
    renderExplorer();

    expect(await screen.findByRole("heading", { name: "Chiesi USA, Inc." })).toBeVisible();
    expect(screen.getAllByText("Class II")).toHaveLength(2);
    expect(screen.getByText("Lack of Assurance of Sterility")).toBeVisible();
    expect(screen.getByText(/Do not change or stop medication/)).toBeVisible();
    expect(screen.getByText(recallPage.source.disclaimer)).toBeVisible();
    expect(screen.getByRole("link", { name: "View the official FDA dataset" })).toHaveAttribute(
      "href",
      recallPage.source.dataset_url,
    );
    expect(mockedRecalls).toHaveBeenCalledWith(
      expect.objectContaining({ classification: undefined, limit: 10, offset: 0 }),
    );
  });

  it("labels a current FDA recall that is still pending classification", async () => {
    mockedRecalls.mockResolvedValue({
      ...recallPage,
      items: [
        {
          ...capturedRecall,
          recall_number: null,
          event_id: "99388",
          classification: "Not Yet Classified",
          recalling_firm: "Precision Dose Inc.",
        },
      ],
    });

    renderExplorer();

    expect(await screen.findByText("Not Yet Classified")).toBeVisible();
    expect(screen.getByText("Recall number pending · Event 99388")).toBeVisible();
    expect(screen.getByText(/recalls FDA has not yet classified/i)).toBeVisible();
  });

  it("applies an exact hazard-class filter", async () => {
    const user = userEvent.setup();
    const { onNavigate } = renderExplorer();
    await screen.findByRole("heading", { name: "Chiesi USA, Inc." });

    await user.selectOptions(screen.getByLabelText("Hazard classification"), "Class I");
    await user.click(screen.getByRole("button", { name: /Apply filter/ }));

    expect(onNavigate).toHaveBeenCalledWith({
      view: "recalls",
      classification: "Class I",
      offset: 0,
    });
  });

  it("requests the next bounded page while preserving the active filter", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    const route: RecallRoute = { view: "recalls", classification: "Class II", offset: 0 };
    renderExplorer(route, onNavigate);
    await screen.findByRole("heading", { name: "Chiesi USA, Inc." });

    await user.click(screen.getByRole("button", { name: /Next/ }));

    expect(onNavigate).toHaveBeenCalledWith({
      view: "recalls",
      classification: "Class II",
      offset: 10,
    });
  });

  it("ignores a superseded FDA result after a newer page succeeds", async () => {
    const initialPage = deferred<DrugRecallPage>();
    let initialSignal: AbortSignal | undefined;
    mockedRecalls.mockImplementationOnce((query) => {
      initialSignal = query.signal;
      return initialPage.promise;
    });
    mockedRecalls.mockResolvedValueOnce({
      ...recallPage,
      offset: 10,
      items: [{ ...capturedRecall, recalling_firm: "Current page firm" }],
    });
    const { onNavigate, rerender } = renderExplorer();

    expect(mockedRecalls).toHaveBeenCalledTimes(1);
    rerender(
      <DrugRecallExplorer
        route={{ view: "recalls", offset: 10 }}
        onNavigate={onNavigate}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Current page firm" })).toBeVisible();
    expect(initialSignal?.aborted).toBe(true);

    await act(() => {
      initialPage.resolve(recallPage);
      return Promise.resolve();
    });

    expect(screen.getByRole("heading", { name: "Current page firm" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Chiesi USA, Inc." })).not.toBeInTheDocument();
  });

  it("moves focus to the results summary after keyboard pagination", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    const { rerender } = renderExplorer(defaultRoute, onNavigate);
    await screen.findByRole("heading", { name: "Chiesi USA, Inc." });

    await user.tab();
    await user.click(screen.getByRole("button", { name: /Next/ }));
    const nextPage = { ...recallPage, offset: 10 };
    mockedRecalls.mockResolvedValueOnce(nextPage);
    rerender(
      <DrugRecallExplorer
        route={{ view: "recalls", offset: 10 }}
        onNavigate={onNavigate}
      />,
    );

    expect(
      await screen.findByRole("heading", { name: "All drug recall classes" }),
    ).toHaveFocus();
  });

  it("offers a retry after an FDA request fails", async () => {
    const user = userEvent.setup();
    mockedRecalls.mockRejectedValueOnce(new Error("temporary"));
    renderExplorer();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Something unexpected interrupted the request.",
    );
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("heading", { name: "Chiesi USA, Inc." })).toBeVisible();
    expect(mockedRecalls).toHaveBeenCalledTimes(2);
  });

  it("recovers an out-of-range FDA page without dropping its active filter", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    const route: RecallRoute = { view: "recalls", classification: "Class I", offset: 25_000 };
    mockedRecalls.mockRejectedValueOnce(new Error("page is beyond the current live result set"));
    renderExplorer(route, onNavigate);

    expect(await screen.findByRole("alert")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Return to first page" }));

    expect(onNavigate).toHaveBeenCalledWith({
      view: "recalls",
      classification: "Class I",
      offset: 0,
    });
    expect(screen.getByText("Loading live FDA drug recall reports")).toBeInTheDocument();
  });

  it("renders an explicit empty state for an official response with no matches", async () => {
    mockedRecalls.mockResolvedValue({ ...recallPage, items: [], total: 0 });

    renderExplorer();

    expect(
      await screen.findByRole("heading", { name: "No reports matched this filter." }),
    ).toBeVisible();
    expect(screen.getByText(/FDA does not currently return reports/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Check the live source again" })).toBeVisible();
  });
});
