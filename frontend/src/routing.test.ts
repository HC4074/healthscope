import { describe, expect, it } from "vitest";

import { dashboardRouteUrl, readDashboardRoute } from "./routing";

describe("dashboard routing", () => {
  it("canonicalizes the root landing page to the overview route", () => {
    expect(readDashboardRoute({ pathname: "/", search: "?ignored=true" })).toEqual({
      view: "overview",
    });
    expect(dashboardRouteUrl({ view: "overview" })).toBe("/overview");
  });

  it("reads and writes community-health filters and pagination", () => {
    const route = readDashboardRoute({
      pathname: "/community-health",
      search: "?state=CA&measure=ACCESS2&page=3",
    });

    expect(route).toEqual({
      view: "community",
      state: "CA",
      measureId: "ACCESS2",
      offset: 50,
    });
    expect(dashboardRouteUrl(route)).toBe(
      "/community-health?state=CA&measure=ACCESS2&page=3",
    );
  });

  it("reads and writes drug-recall filters and pagination", () => {
    const route = readDashboardRoute({
      pathname: "/drug-recalls/",
      search: "?classification=Class+I&page=2",
    });

    expect(route).toEqual({ view: "recalls", classification: "Class I", offset: 10 });
    expect(dashboardRouteUrl(route)).toBe(
      "/drug-recalls?classification=Class+I&page=2",
    );
  });

  it("falls back safely when a deep link contains unsupported filters", () => {
    expect(
      readDashboardRoute({
        pathname: "/community-health",
        search: "?state=XX&measure=not-valid&page=-1",
      }),
    ).toEqual({ view: "community", state: "AL", measureId: undefined, offset: 0 });
    expect(
      readDashboardRoute({
        pathname: "/drug-recalls",
        search: "?classification=Critical&page=999999999999999999999",
      }),
    ).toEqual({ view: "recalls", classification: undefined, offset: 0 });
  });
});
