import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

interface MeasureCatalog {
  total: number;
}

interface DrugRecallPage {
  items: Array<{
    recall_number: string | null;
    event_id: string | null;
    recalling_firm: string;
    classification: string;
  }>;
  total: number;
  limit: number;
  offset: number;
}

declare global {
  interface Window {
    __healthscopeCspViolations: string[];
  }
}

const axeTags = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"];

function watchBrowser(page: Page, baseURL: string | undefined): string[] {
  const failures: string[] = [];
  const expectedOrigin = new URL(baseURL ?? "http://127.0.0.1:18080").origin;

  page.on("console", (message) => {
    if (message.type() !== "error") {
      return;
    }
    const location = message.location().url;
    if (
      message.text().startsWith("Failed to load resource:") &&
      location &&
      new URL(location).pathname === "/api/v1/hospitals/ingestion/health"
    ) {
      return;
    }
    failures.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => failures.push(`page: ${error.message}`));
  page.on("requestfailed", (request) => {
    if (new URL(request.url()).origin === expectedOrigin) {
      failures.push(
        `request: ${request.method()} ${request.url()} (${request.failure()?.errorText ?? "unknown"})`,
      );
    }
  });
  return failures;
}

async function watchCsp(page: Page): Promise<void> {
  await page.addInitScript(() => {
    window.__healthscopeCspViolations = [];
    document.addEventListener("securitypolicyviolation", (event) => {
      window.__healthscopeCspViolations.push(
        `${event.violatedDirective}: ${event.blockedURI || "inline"}`,
      );
    });
  });
}

async function expectAccessible(page: Page): Promise<void> {
  const scan = await new AxeBuilder({ page }).withTags(axeTags).analyze();
  expect(scan.violations).toEqual([]);
}

async function expectBrowserClean(page: Page, failures: string[]): Promise<void> {
  expect(await page.evaluate(() => window.__healthscopeCspViolations)).toEqual([]);
  expect(failures).toEqual([]);
}

test("summarizes all live sources in an accessible overview", async ({ baseURL, page }) => {
  const browserFailures = watchBrowser(page, baseURL);
  await watchCsp(page);

  const healthResponsePromise = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/v1/hospitals/ingestion/health",
  );
  const catalogResponsePromise = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/v1/community-health/measures",
  );
  const recallResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === "/api/v1/drug-recalls" &&
      url.searchParams.get("limit") === "1" &&
      url.searchParams.get("offset") === "0"
    );
  });

  const documentResponse = await page.goto("/overview");
  expect(documentResponse?.status()).toBe(200);
  expect(documentResponse?.headers()["content-security-policy"]).toContain("default-src 'self'");

  const [healthResponse, catalogResponse, recallResponse] = await Promise.all([
    healthResponsePromise,
    catalogResponsePromise,
    recallResponsePromise,
  ]);
  expect([200, 503]).toContain(healthResponse.status());
  expect(catalogResponse.status()).toBe(200);
  expect(recallResponse.status()).toBe(200);

  const catalog = (await catalogResponse.json()) as MeasureCatalog;
  const recalls = (await recallResponse.json()) as DrugRecallPage;
  expect(catalog.total).toBeGreaterThan(0);
  expect(recalls.total).toBeGreaterThan(0);

  await expect(
    page.getByRole("heading", { name: "Three trusted sources, one clear starting point." }),
  ).toBeVisible();
  await expect(page.locator("article.source-overview-card")).toHaveCount(3);
  await expect(page.getByText(`${catalog.total.toLocaleString("en-US")} measures`)).toBeVisible();
  await expect(page.getByText(`${recalls.total.toLocaleString("en-US")} reports`)).toBeVisible();

  await expectAccessible(page);

  await page.keyboard.press("Tab");
  const skipLink = page.getByRole("link", { name: "Skip to main content" });
  await expect(skipLink).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Refresh all sources" })).toBeFocused();

  await expectBrowserClean(page, browserFailures);
});

test("recovers one failed overview source without reloading healthy sources", async ({ page }) => {
  await watchCsp(page);
  const requestCounts = { cms: 0, cdc: 0, fda: 0 };
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/hospitals/ingestion/health") {
      requestCounts.cms += 1;
    } else if (path === "/api/v1/community-health/measures") {
      requestCounts.cdc += 1;
    } else if (path === "/api/v1/drug-recalls") {
      requestCounts.fda += 1;
    }
  });

  let allowCatalogRecovery = false;
  await page.route("**/api/v1/community-health/measures", async (route) => {
    if (!allowCatalogRecovery) {
      await route.fulfill({
        status: 502,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Controlled CDC outage for release verification." }),
      });
      return;
    }
    await route.continue();
  });

  await page.setViewportSize({ width: 768, height: 900 });
  await page.goto("/overview");
  await expect(page.getByText("Controlled CDC outage for release verification.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry CDC" })).toBeVisible();
  await expect
    .poll(() => requestCounts.cms > 0 && requestCounts.cdc > 0 && requestCounts.fda > 0)
    .toBe(true);
  const settledCounts = { ...requestCounts };
  await expectAccessible(page);

  await page.setViewportSize({ width: 320, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await expectAccessible(page);

  const recoveredCatalogPromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/v1/community-health/measures" &&
      response.status() === 200,
  );
  allowCatalogRecovery = true;
  await page.getByRole("button", { name: "Retry CDC" }).focus();
  await page.keyboard.press("Enter");
  const recoveredCatalogResponse = await recoveredCatalogPromise;
  const recoveredCatalog = (await recoveredCatalogResponse.json()) as MeasureCatalog;
  await expect(
    page.getByText(`${recoveredCatalog.total.toLocaleString("en-US")} measures`),
  ).toBeVisible();
  await expect(
    page.locator("article.source-overview-card").filter({ hasText: "Centers for Disease Control" }),
  ).toBeFocused();
  expect(requestCounts).toEqual({
    cms: settledCounts.cms,
    cdc: settledCounts.cdc + 1,
    fda: settledCounts.fda,
  });
  await expectAccessible(page);
  expect(await page.evaluate(() => window.__healthscopeCspViolations)).toEqual([]);
});

test.describe("mobile navigation", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test("reaches and pages live FDA recalls entirely by keyboard", async ({ baseURL, page }) => {
    const browserFailures = watchBrowser(page, baseURL);
    await watchCsp(page);

    const overviewHealthPromise = page.waitForResponse(
      (response) => new URL(response.url()).pathname === "/api/v1/hospitals/ingestion/health",
    );
    const overviewCatalogPromise = page.waitForResponse(
      (response) => new URL(response.url()).pathname === "/api/v1/community-health/measures",
    );
    const overviewRecallPromise = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === "/api/v1/drug-recalls" && url.searchParams.get("limit") === "1";
    });
    await page.goto("/overview");
    const [overviewHealth, overviewCatalog, overviewRecall] = await Promise.all([
      overviewHealthPromise,
      overviewCatalogPromise,
      overviewRecallPromise,
    ]);
    expect([200, 503]).toContain(overviewHealth.status());
    expect(overviewCatalog.status()).toBe(200);
    expect(overviewRecall.status()).toBe(200);
    await expect(page.locator("article.source-overview-card")).toHaveCount(3);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    const mobileHeader = page.getByRole("banner");
    await expect(mobileHeader.getByText("HealthScope", { exact: true })).toBeVisible();
    const mobileNavigationLinks = mobileHeader
      .getByRole("navigation", { name: "Primary navigation" })
      .getByRole("link");
    const mobileNavigationLayout = await mobileNavigationLinks.evaluateAll((links) =>
      links.map((link) => {
        const bounds = link.getBoundingClientRect();
        return {
          fontSize: Number.parseFloat(window.getComputedStyle(link).fontSize),
          left: bounds.left,
          right: bounds.right,
        };
      }),
    );
    expect(mobileNavigationLayout).toHaveLength(3);
    const mobileViewportWidth = page.viewportSize()?.width ?? 0;
    expect(
      mobileNavigationLayout.every(
        ({ fontSize, left, right }) =>
          fontSize >= 13 && left >= 0 && right <= mobileViewportWidth,
      ),
    ).toBe(true);

    await page.setViewportSize({ width: 320, height: 844 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);
    const narrowNavigationLayout = await mobileNavigationLinks.evaluateAll((links) =>
      links.map((link) => {
        const bounds = link.getBoundingClientRect();
        return { left: bounds.left, right: bounds.right };
      }),
    );
    const narrowViewportWidth = await page.evaluate(
      () => document.documentElement.clientWidth,
    );
    expect(
      narrowNavigationLayout.every(
        ({ left, right }) => left >= 0 && right <= narrowViewportWidth,
      ),
    ).toBe(true);

    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "HealthScope home" })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Overview" })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Community health" })).toBeFocused();
    await page.keyboard.press("Tab");
    const recallsLink = page.getByRole("link", { name: "Drug recalls", exact: true });
    await expect(recallsLink).toBeFocused();

    const firstRecallResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === "/api/v1/drug-recalls" &&
        url.searchParams.get("limit") === "10" &&
        url.searchParams.get("offset") === "0"
      );
    });
    await page.keyboard.press("Enter");
    const firstRecallResponse = await firstRecallResponsePromise;
    expect(firstRecallResponse.status()).toBe(200);
    const firstPage = (await firstRecallResponse.json()) as DrugRecallPage;
    expect(firstPage.items.length).toBeGreaterThan(0);
    expect(firstPage.total).toBeGreaterThan(firstPage.items.length);
    const firstRecall = firstPage.items[0];
    if (!firstRecall) {
      throw new Error("FDA returned an empty first recall page.");
    }

    await expect(page).toHaveURL(/\/drug-recalls$/);
    await expect(recallsLink).toHaveAttribute("aria-current", "page");
    const firstRecallIdentifier = firstRecall.recall_number
      ? `Recall ${firstRecall.recall_number}`
      : firstRecall.event_id
        ? `Event ${firstRecall.event_id}`
        : "Recall number pending";
    const firstRecallCard = page
      .locator("article.recall-card")
      .filter({ hasText: firstRecallIdentifier });
    await expect(
      firstRecallCard.getByRole("heading", { name: firstRecall.recalling_firm }),
    ).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    expect(
      await page.locator(".recall-card-heading").evaluateAll((headings) =>
        headings.every((heading) => heading.scrollWidth <= heading.clientWidth),
      ),
    ).toBe(true);
    await expectAccessible(page);

    const classification = page.getByLabel("Hazard classification");
    await classification.focus();
    await page.keyboard.press("Tab");
    const applyButton = page.getByRole("button", { name: /Apply filter/ });
    await expect(applyButton).toBeFocused();

    await classification.selectOption("Class I");
    const filteredResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === "/api/v1/drug-recalls" &&
        url.searchParams.get("classification") === "Class I" &&
        url.searchParams.get("limit") === "10" &&
        url.searchParams.get("offset") === "0"
      );
    });
    await applyButton.click();
    const filteredResponse = await filteredResponsePromise;
    expect(filteredResponse.status()).toBe(200);
    const filteredPage = (await filteredResponse.json()) as DrugRecallPage;
    expect(filteredPage.items.length).toBeGreaterThan(0);
    expect(filteredPage.total).toBeGreaterThan(filteredPage.items.length);
    expect(filteredPage.items.every((item) => item.classification === "Class I")).toBe(true);
    await expect(page).toHaveURL(/\/drug-recalls\?classification=Class\+I$/);
    await expect(classification).toHaveValue("Class I");
    await expect(page.getByRole("heading", { name: "Class I" })).toBeVisible();

    const restoredUnfilteredResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === "/api/v1/drug-recalls" &&
        url.searchParams.get("classification") === null &&
        url.searchParams.get("offset") === "0"
      );
    });
    await page.goBack();
    const restoredUnfilteredResponse = await restoredUnfilteredResponsePromise;
    expect(restoredUnfilteredResponse.status()).toBe(200);
    expect(await restoredUnfilteredResponse.finished()).toBeNull();
    await expect(page.getByLabel("Hazard classification")).toHaveValue("");
    await expect(page.getByRole("heading", { name: "All drug recall classes" })).toBeVisible();

    const restoredFilteredResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === "/api/v1/drug-recalls" &&
        url.searchParams.get("classification") === "Class I" &&
        url.searchParams.get("offset") === "0"
      );
    });
    await page.goForward();
    const restoredFilteredResponse = await restoredFilteredResponsePromise;
    expect(restoredFilteredResponse.status()).toBe(200);
    expect(await restoredFilteredResponse.finished()).toBeNull();
    await expect(page.getByLabel("Hazard classification")).toHaveValue("Class I");
    await expect(page.getByRole("heading", { name: "Class I" })).toBeVisible();

    const nextPageResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === "/api/v1/drug-recalls" &&
        url.searchParams.get("classification") === "Class I" &&
        url.searchParams.get("offset") === String(filteredPage.limit)
      );
    });
    const nextButton = page.getByRole("button", { name: /Next/ });
    await nextButton.focus();
    await page.keyboard.press("Enter");
    const nextPageResponse = await nextPageResponsePromise;
    expect(nextPageResponse.status()).toBe(200);
    const nextPage = (await nextPageResponse.json()) as DrugRecallPage;
    expect(nextPage.offset).toBe(filteredPage.limit);
    expect(nextPage.items.every((item) => item.classification === "Class I")).toBe(true);
    await expect(page).toHaveURL(/\/drug-recalls\?classification=Class\+I&page=2$/);
    await expect(page.getByRole("heading", { name: "Class I" })).toBeFocused();

    await expectBrowserClean(page, browserFailures);
  });
});
