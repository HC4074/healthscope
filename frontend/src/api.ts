import type { CommunityHealthMeasureCatalog, CountyHealthPage } from "./types";

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim().replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${configuredBaseUrl}${path}`, {
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError("HealthScope could not reach the data service.", 0);
  }

  if (!response.ok) {
    let detail = "The data service returned an unexpected response.";
    try {
      const payload: unknown = await response.json();
      if (
        typeof payload === "object" &&
        payload !== null &&
        "detail" in payload &&
        typeof payload.detail === "string"
      ) {
        detail = payload.detail;
      }
    } catch {
      // Keep the stable fallback when an upstream proxy returns a non-JSON error page.
    }
    throw new ApiError(detail, response.status);
  }

  return (await response.json()) as T;
}

export function fetchMeasureCatalog(signal?: AbortSignal): Promise<CommunityHealthMeasureCatalog> {
  return request("/api/v1/community-health/measures", signal);
}

interface CountyQuery {
  state: string;
  measureId: string;
  limit: number;
  offset: number;
  signal?: AbortSignal;
}

export function fetchCountyHealth({
  state,
  measureId,
  limit,
  offset,
  signal,
}: CountyQuery): Promise<CountyHealthPage> {
  const query = new URLSearchParams({
    state,
    measure_id: measureId,
    limit: String(limit),
    offset: String(offset),
  });
  return request(`/api/v1/community-health/counties?${query.toString()}`, signal);
}
