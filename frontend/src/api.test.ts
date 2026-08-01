import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, fetchCountyHealth, fetchMeasureCatalog } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("community health API client", () => {
  it("requests the live measure catalog from the configured API boundary", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0, source: {} }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await fetchMeasureCatalog();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/community-health/measures",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("encodes county filters and pagination", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await fetchCountyHealth({ state: "CA", measureId: "ACCESS2", limit: 25, offset: 50 });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/community-health/counties?state=CA&measure_id=ACCESS2&limit=25&offset=50",
      expect.any(Object),
    );
  });

  it("surfaces the stable API detail for unsuccessful responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "CDC PLACES data is temporarily unavailable." }), {
          status: 502,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(fetchMeasureCatalog()).rejects.toEqual(
      new ApiError("CDC PLACES data is temporarily unavailable.", 502),
    );
  });

  it("normalizes connection failures without exposing transport internals", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("socket closed")));

    await expect(fetchMeasureCatalog()).rejects.toEqual(
      new ApiError("HealthScope could not reach the data service.", 0),
    );
  });
});
