import { STATES } from "./states";
import type { RecallClassification } from "./types";

export const COMMUNITY_PAGE_SIZE = 25;
export const RECALL_PAGE_SIZE = 10;
export const RECALL_MAX_OFFSET = 25_000;

export interface OverviewRoute {
  view: "overview";
}

export interface CommunityRoute {
  view: "community";
  state: string;
  measureId?: string;
  offset: number;
}

export interface RecallRoute {
  view: "recalls";
  classification?: RecallClassification;
  offset: number;
}

export type DashboardRoute = OverviewRoute | CommunityRoute | RecallRoute;

const stateCodes = new Set<string>(STATES.map(([code]) => code));
const classifications = new Set<RecallClassification>(["Class I", "Class II", "Class III"]);
const measurePattern = /^[A-Z0-9_]{2,32}$/;

function pageOffset(params: URLSearchParams, pageSize: number, maximumOffset?: number): number {
  const rawPage = params.get("page");
  if (!rawPage || !/^\d+$/.test(rawPage)) {
    return 0;
  }
  const page = Number(rawPage);
  const offset = (page - 1) * pageSize;
  if (!Number.isSafeInteger(offset) || offset < 0 || (maximumOffset !== undefined && offset > maximumOffset)) {
    return 0;
  }
  return offset;
}

export function readDashboardRoute(location: Pick<Location, "pathname" | "search">): DashboardRoute {
  const params = new URLSearchParams(location.search);
  const pathname = location.pathname.replace(/\/$/, "") || "/";
  if (pathname === "/" || pathname === "/overview") {
    return { view: "overview" };
  }
  if (pathname === "/drug-recalls") {
    const classification = params.get("classification");
    return {
      view: "recalls",
      classification:
        classification && classifications.has(classification as RecallClassification)
          ? (classification as RecallClassification)
          : undefined,
      offset: pageOffset(params, RECALL_PAGE_SIZE, RECALL_MAX_OFFSET),
    };
  }

  const requestedState = params.get("state");
  const requestedMeasure = params.get("measure");
  return {
    view: "community",
    state: requestedState && stateCodes.has(requestedState) ? requestedState : "AL",
    measureId:
      requestedMeasure && measurePattern.test(requestedMeasure) ? requestedMeasure : undefined,
    offset: pageOffset(params, COMMUNITY_PAGE_SIZE),
  };
}

export function dashboardRouteUrl(route: DashboardRoute): string {
  if (route.view === "overview") {
    return "/overview";
  }
  const params = new URLSearchParams();
  if (route.view === "recalls") {
    if (route.classification) {
      params.set("classification", route.classification);
    }
    if (route.offset > 0) {
      params.set("page", String(Math.floor(route.offset / RECALL_PAGE_SIZE) + 1));
    }
    const query = params.toString();
    return `/drug-recalls${query ? `?${query}` : ""}`;
  }

  params.set("state", route.state);
  if (route.measureId) {
    params.set("measure", route.measureId);
  }
  if (route.offset > 0) {
    params.set("page", String(Math.floor(route.offset / COMMUNITY_PAGE_SIZE) + 1));
  }
  return `/community-health?${params.toString()}`;
}
