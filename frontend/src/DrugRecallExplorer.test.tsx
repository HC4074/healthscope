import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DrugRecallExplorer from "./DrugRecallExplorer";
import { fetchDrugRecalls } from "./api";
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

const mockedRecalls = vi.mocked(fetchDrugRecalls);

describe("drug recall explorer", () => {
  beforeEach(() => {
    mockedRecalls.mockResolvedValue(recallPage);
  });

  it("renders current FDA reports, provenance, and medical-use warnings", async () => {
    render(<DrugRecallExplorer />);

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

  it("applies an exact hazard-class filter", async () => {
    const user = userEvent.setup();
    render(<DrugRecallExplorer />);
    await screen.findByRole("heading", { name: "Chiesi USA, Inc." });

    await user.selectOptions(screen.getByLabelText("Hazard classification"), "Class I");
    await user.click(screen.getByRole("button", { name: /Apply filter/ }));

    await waitFor(() =>
      expect(mockedRecalls).toHaveBeenLastCalledWith(
        expect.objectContaining({ classification: "Class I", limit: 10, offset: 0 }),
      ),
    );
  });

  it("requests the next bounded page while preserving the active filter", async () => {
    const user = userEvent.setup();
    render(<DrugRecallExplorer />);
    await screen.findByRole("heading", { name: "Chiesi USA, Inc." });

    await user.click(screen.getByRole("button", { name: /Next/ }));

    await waitFor(() =>
      expect(mockedRecalls).toHaveBeenLastCalledWith(
        expect.objectContaining({ limit: 10, offset: 10 }),
      ),
    );
  });

  it("offers a retry after an FDA request fails", async () => {
    const user = userEvent.setup();
    mockedRecalls.mockRejectedValueOnce(new Error("temporary"));
    render(<DrugRecallExplorer />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Something unexpected interrupted the request.",
    );
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("heading", { name: "Chiesi USA, Inc." })).toBeVisible();
    expect(mockedRecalls).toHaveBeenCalledTimes(2);
  });

  it("renders an explicit empty state for an official response with no matches", async () => {
    mockedRecalls.mockResolvedValue({ ...recallPage, items: [], total: 0 });

    render(<DrugRecallExplorer />);

    expect(
      await screen.findByRole("heading", { name: "No reports matched this filter." }),
    ).toBeVisible();
    expect(screen.getByText(/FDA does not currently return reports/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Check the live source again" })).toBeVisible();
  });
});
