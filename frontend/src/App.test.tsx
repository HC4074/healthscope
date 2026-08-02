import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { fetchCountyHealth, fetchMeasureCatalog } from "./api";
import type { CommunityHealthMeasureCatalog, CountyHealthPage } from "./types";

vi.mock("./api", () => ({
  ApiError: class ApiError extends Error {
    constructor(message: string, readonly status: number) {
      super(message);
    }
  },
  fetchMeasureCatalog: vi.fn(),
  fetchCountyHealth: vi.fn(),
}));

vi.mock("./PrevalenceChart", () => ({ default: () => <div>County comparison chart</div> }));
vi.mock("./DrugRecallExplorer", () => ({
  default: () => <h1>Follow public drug recalls, straight from FDA.</h1>,
}));

const source = {
  name: "Centers for Disease Control and Prevention",
  dataset_name: "PLACES: Local Data for Better Health, County Data, 2025 release",
  dataset_url: "https://data.cdc.gov/d/swc5-untb",
  retrieved_at: "2026-08-01T12:00:00Z",
  estimate_type: "Age-adjusted prevalence",
};

const catalog: CommunityHealthMeasureCatalog = {
  items: [
    {
      measure_id: "DIABETES",
      measure: "Diagnosed diabetes among adults",
      category: "Health Outcomes",
      latest_year: 2023,
      county_count: 2957,
    },
    {
      measure_id: "ACCESS2",
      measure: "Current lack of health insurance among adults",
      category: "Prevention",
      latest_year: 2023,
      county_count: 3143,
    },
  ],
  total: 2,
  source,
};

const countyPage: CountyHealthPage = {
  items: [
    {
      year: 2023,
      state: "AL",
      state_name: "Alabama",
      county: "Autauga",
      county_fips: "01001",
      measure_id: "DIABETES",
      measure: "Diagnosed diabetes among adults",
      category: "Health Outcomes",
      prevalence_percent: 11.4,
      low_confidence_limit: 9.8,
      high_confidence_limit: 13.2,
      population: 60342,
      adult_population: 46253,
      latitude: 32.535,
      longitude: -86.643,
    },
  ],
  total: 67,
  limit: 25,
  offset: 0,
  state: "AL",
  measure_id: "DIABETES",
  source,
};

const mockedCatalog = vi.mocked(fetchMeasureCatalog);
const mockedCounties = vi.mocked(fetchCountyHealth);

describe("community health explorer", () => {
  beforeEach(() => {
    mockedCatalog.mockResolvedValue(catalog);
    mockedCounties.mockResolvedValue(countyPage);
  });

  it("loads discoverable measures and renders live county estimates", async () => {
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Diagnosed diabetes among adults" })).toBeVisible();
    expect(screen.getAllByText("11.4%")).toHaveLength(2);
    expect(screen.getByText("9.8–13.2%")).toBeVisible();
    expect(screen.getByRole("link", { name: "View the official CDC dataset" })).toHaveAttribute(
      "href",
      source.dataset_url,
    );
    expect(mockedCounties).toHaveBeenCalledWith(
      expect.objectContaining({ state: "AL", measureId: "DIABETES", limit: 25, offset: 0 }),
    );
  });

  it("applies a new state and measure only when the user submits the filters", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "Diagnosed diabetes among adults" });

    await user.selectOptions(screen.getByLabelText("State"), "CA");
    await user.selectOptions(screen.getByLabelText("Health measure"), "ACCESS2");
    expect(mockedCounties).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: /Explore counties/ }));

    await waitFor(() =>
      expect(mockedCounties).toHaveBeenLastCalledWith(
        expect.objectContaining({ state: "CA", measureId: "ACCESS2", offset: 0 }),
      ),
    );
  });

  it("requests the next bounded page without changing active filters", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "Diagnosed diabetes among adults" });

    await user.click(screen.getByRole("button", { name: /Next/ }));

    await waitFor(() =>
      expect(mockedCounties).toHaveBeenLastCalledWith(
        expect.objectContaining({ state: "AL", measureId: "DIABETES", offset: 25 }),
      ),
    );
  });

  it("offers a retry when the county request fails", async () => {
    const user = userEvent.setup();
    mockedCounties.mockRejectedValueOnce(new Error("temporary"));
    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Something unexpected interrupted the request.",
    );
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("heading", { name: "Diagnosed diabetes among adults" })).toBeVisible();
    expect(mockedCounties).toHaveBeenCalledTimes(2);
  });

  it("switches to the lazy FDA dashboard view from primary navigation", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "Diagnosed diabetes among adults" });

    await user.click(screen.getByRole("button", { name: "Drug recalls" }));

    expect(
      await screen.findByRole("heading", { name: "Follow public drug recalls, straight from FDA." }),
    ).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Diagnosed diabetes among adults" })).not.toBeInTheDocument();
  });
});
