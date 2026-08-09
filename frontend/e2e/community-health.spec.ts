import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

interface MeasureCatalog {
  items: Array<{
    measure_id: string;
    measure: string;
  }>;
}

interface CountyPage {
  items: Array<{
    county: string;
    prevalence_percent: number;
  }>;
  total: number;
  limit: number;
  offset: number;
  state: string;
  measure_id: string;
}

declare global {
  interface Window {
    __healthscopeCspViolations: string[];
  }
}

test("explores live CDC county data with accessible keyboard navigation", async ({
  baseURL,
  page,
}) => {
  const browserFailures: string[] = [];
  const expectedOrigin = new URL(baseURL ?? "http://127.0.0.1:18080").origin;

  page.on("console", (message) => {
    if (message.type() === "error") {
      browserFailures.push(`console: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => browserFailures.push(`page: ${error.message}`));
  page.on("requestfailed", (request) => {
    if (new URL(request.url()).origin === expectedOrigin) {
      browserFailures.push(
        `request: ${request.method()} ${request.url()} (${request.failure()?.errorText ?? "unknown"})`,
      );
    }
  });
  await page.addInitScript(() => {
    window.__healthscopeCspViolations = [];
    document.addEventListener("securitypolicyviolation", (event) => {
      window.__healthscopeCspViolations.push(
        `${event.violatedDirective}: ${event.blockedURI || "inline"}`,
      );
    });
  });

  const catalogResponsePromise = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/v1/community-health/measures",
  );
  const countyResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === "/api/v1/community-health/counties" &&
      url.searchParams.get("state") === "AL" &&
      url.searchParams.get("measure_id") === "DIABETES" &&
      url.searchParams.get("offset") === "0"
    );
  });

  const documentResponse = await page.goto("/community-health?state=AL&measure=DIABETES");
  expect(documentResponse).not.toBeNull();
  expect(documentResponse?.status()).toBe(200);
  expect(documentResponse?.headers()["content-security-policy"]).toContain("default-src 'self'");

  const [catalogResponse, countyResponse] = await Promise.all([
    catalogResponsePromise,
    countyResponsePromise,
  ]);
  expect(catalogResponse.status()).toBe(200);
  expect(countyResponse.status()).toBe(200);

  const catalog = (await catalogResponse.json()) as MeasureCatalog;
  const diabetesMeasure = catalog.items.find((item) => item.measure_id === "DIABETES");
  if (!diabetesMeasure) {
    throw new Error("CDC no longer reports the DIABETES measure.");
  }
  const firstPage = (await countyResponse.json()) as CountyPage;
  expect(firstPage.state).toBe("AL");
  expect(firstPage.measure_id).toBe("DIABETES");
  expect(firstPage.items.length).toBeGreaterThan(0);
  expect(firstPage.total).toBeGreaterThan(firstPage.items.length);
  const firstCounty = firstPage.items[0];
  if (!firstCounty) {
    throw new Error("CDC returned an empty first county page.");
  }

  await expect(page.getByRole("heading", { name: diabetesMeasure.measure })).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(firstPage.items.length);
  await expect(page.getByRole("rowheader", { name: `${firstCounty.county} County` })).toBeVisible();
  await expect(
    page.getByRole("cell", { name: `${firstCounty.prevalence_percent.toFixed(1)}%` }),
  ).toBeVisible();

  const accessibilityScan = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"])
    .analyze();
  expect(accessibilityScan.violations).toEqual([]);

  await page.keyboard.press("Tab");
  const skipLink = page.getByRole("link", { name: "Skip to main content" });
  await expect(skipLink).toBeFocused();
  await expect(skipLink).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("State")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Health measure")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: /Explore counties/ })).toBeFocused();

  const nextPageResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === "/api/v1/community-health/counties" &&
      url.searchParams.get("offset") === String(firstPage.limit)
    );
  });
  const nextButton = page.getByRole("button", { name: /Next/ });
  await nextButton.focus();
  await page.keyboard.press("Enter");
  const nextPageResponse = await nextPageResponsePromise;
  expect(nextPageResponse.status()).toBe(200);
  const nextPage = (await nextPageResponse.json()) as CountyPage;
  expect(nextPage.offset).toBe(firstPage.limit);
  await expect(page).toHaveURL(/\/community-health\?.*page=2/);
  await expect(page.locator("tbody tr")).toHaveCount(nextPage.items.length);
  await expect(
    page.getByRole("heading", {
      name: `Showing ${nextPage.offset + 1}–${nextPage.offset + nextPage.items.length} of ${nextPage.total}`,
    }),
  ).toBeFocused();

  expect(await page.evaluate(() => window.__healthscopeCspViolations)).toEqual([]);
  expect(browserFailures).toEqual([]);
});
