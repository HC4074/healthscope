import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Overview from "./Overview";
import {
  fetchDrugRecalls,
  fetchHospitalIngestionHealth,
  fetchMeasureCatalog,
} from "./api";

vi.mock("./api", () => ({
  ApiError: class ApiError extends Error {
    constructor(message: string, readonly status: number) {
      super(message);
    }
  },
  fetchDrugRecalls: vi.fn(),
  fetchHospitalIngestionHealth: vi.fn(),
  fetchMeasureCatalog: vi.fn(),
}));

const mockedCms = vi.mocked(fetchHospitalIngestionHealth);
const mockedCdc = vi.mocked(fetchMeasureCatalog);
const mockedFda = vi.mocked(fetchDrugRecalls);

describe("cross-source overview", () => {
  beforeEach(() => {
    mockedCms.mockResolvedValue({
      healthy: true,
      reason: "healthy",
      latest_run: {
        run_id: "b2912727-7dbc-427d-8918-6e02478038bc",
        source_dataset_id: "xubh-q36u",
        status: "succeeded",
        retrieved_at: "2026-08-03T05:00:00Z",
        started_at: "2026-08-03T05:00:00Z",
        finished_at: "2026-08-03T05:04:00Z",
        expected_count: 5432,
        fetched_count: 5432,
        upserted_count: 5432,
        pages: 55,
        request_attempts: 55,
        error_type: null,
        error_message: null,
        latest_successful_retrieved_at: "2026-08-03T05:00:00Z",
        freshness_seconds: 3600,
        stale_after_seconds: 93600,
        is_stale: false,
      },
    });
    mockedCdc.mockResolvedValue({
      items: [
        {
          measure_id: "DIABETES",
          measure: "Diagnosed diabetes among adults",
          category: "Health Outcomes",
          latest_year: 2023,
          county_count: 2957,
        },
      ],
      total: 40,
      source: {
        name: "Centers for Disease Control and Prevention",
        dataset_name: "PLACES: Local Data for Better Health, County Data, 2025 release",
        dataset_url: "https://data.cdc.gov/d/swc5-untb",
        retrieved_at: "2026-08-03T12:00:00Z",
        estimate_type: "Age-adjusted prevalence",
      },
    });
    mockedFda.mockResolvedValue({
      items: [],
      total: 17832,
      limit: 1,
      offset: 0,
      classification: null,
      source: {
        name: "U.S. Food and Drug Administration",
        dataset_name: "Drug Recall Enforcement Reports",
        dataset_url: "https://open.fda.gov/apis/drug/enforcement/",
        retrieved_at: "2026-08-03T12:00:00Z",
        last_updated: "2026-07-22",
        disclaimer: "Do not rely on openFDA to make decisions regarding medical care.",
        terms_url: "https://open.fda.gov/terms/",
        license_url: "https://open.fda.gov/license/",
      },
    });
  });

  it("shows independent source health and links into both explorers", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    render(<Overview onNavigate={onNavigate} />);

    expect(await screen.findByText("5,432")).toBeVisible();
    expect(screen.getByText("40 measures")).toBeVisible();
    expect(screen.getByText("17,832 reports")).toBeVisible();
    expect(screen.getByText(/does not merge unrelated populations/i)).toBeVisible();

    await user.click(screen.getByRole("link", { name: /Explore county health/ }));
    expect(onNavigate).toHaveBeenCalledWith({ view: "community", state: "AL", offset: 0 });
    await user.click(screen.getByRole("link", { name: /Review drug recalls/ }));
    expect(onNavigate).toHaveBeenCalledWith({ view: "recalls", offset: 0 });
  });

  it("retries one failed source without reloading healthy cards", async () => {
    const user = userEvent.setup();
    mockedCms.mockRejectedValueOnce(new Error("database unavailable"));
    render(<Overview onNavigate={vi.fn()} />);

    expect(await screen.findByText("Source temporarily unavailable")).toBeVisible();
    expect(screen.getByText("40 measures")).toBeVisible();
    expect(screen.getByText("17,832 reports")).toBeVisible();

    expect(mockedCms).toHaveBeenCalledTimes(1);
    expect(mockedCdc).toHaveBeenCalledTimes(1);
    expect(mockedFda).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Retry CMS" }));

    const recoveredMetric = await screen.findByText("5,432");
    expect(recoveredMetric).toBeVisible();
    expect(recoveredMetric.closest("article")).toHaveFocus();
    expect(mockedCms).toHaveBeenCalledTimes(2);
    expect(mockedCdc).toHaveBeenCalledTimes(1);
    expect(mockedFda).toHaveBeenCalledTimes(1);
  });
});
