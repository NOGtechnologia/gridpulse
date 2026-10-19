import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const PAGES = [
  { path: "/de", heading: "Lage" },
  { path: "/de/outlook", heading: "Ausblick" },
  { path: "/de/countries", heading: "Ländervergleich" },
  { path: "/de/events", heading: "Ereignisse" },
  { path: "/de/history", heading: "Historie" },
  { path: "/de/status", heading: "Datenqualität" },
  { path: "/en", heading: "Situation" },
];

async function expectNoSeriousA11yViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const serious = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(serious.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`)).toEqual([]);
}

for (const { path, heading } of PAGES) {
  test(`${path} renders and is accessible`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expectNoSeriousA11yViolations(page);
  });
}

test("situation shows numbers with unit, source and data age", async ({ page }) => {
  await page.goto("/de");
  const load = page.locator("section", { has: page.getByRole("heading", { name: "Netzlast" }) });
  await expect(load.getByTestId("big-number")).toContainText("MW");
  await expect(load.getByText(/Quelle:/)).toBeVisible();
  await expect(load.getByText(/Datenstand:/)).toBeVisible();
  await expect(page.getByRole("note")).toContainText("ersetzt keine zertifizierten Leitsysteme");
});

test("country comparison shows zones or explains the missing ENTSO-E token", async ({ page }) => {
  await page.goto("/de/countries");
  // Without GRIDPULSE_ENTSOE_TOKEN (demo stack, forks) the page must explain why it is empty.
  // Zone tiles are already rendered (as skeletons) while loading, so wait for content
  // that only exists once the data has arrived: the token hint or a tile footer.
  const tokenHint = page.getByText(/GRIDPULSE_ENTSOE_TOKEN/);
  const france = page.locator("section", {
    has: page.getByRole("heading", { name: "Frankreich (FR)" }),
  });
  const franceSource = france.getByText(/Quelle:/);
  await expect(tokenHint.or(franceSource)).toBeVisible();
  if (await tokenHint.isVisible()) {
    await expect(page.getByRole("heading", { name: "Keine ENTSO-E-Daten" })).toBeVisible();
  } else {
    await expect(france.getByTestId("big-number").first()).toContainText("MW");
  }
});

test("keyboard navigation reaches the main menu via skip link", async ({ page }) => {
  await page.goto("/de");
  await page.keyboard.press("Tab");
  await expect(page.getByText("Zum Inhalt springen")).toBeFocused();
  // skip link -> logo -> "Lage" -> "Ausblick"
  for (let i = 0; i < 3; i++) await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/de\/outlook$/);
});

test("language switch keeps the page", async ({ page }) => {
  await page.goto("/de/status");
  await page.getByRole("link", { name: "en", exact: true }).click();
  await expect(page).toHaveURL(/\/en\/status$/);
  await expect(page.getByRole("heading", { level: 1, name: "Data quality" })).toBeVisible();
});

test("theme toggle switches to light", async ({ page }) => {
  await page.goto("/de");
  await page.getByRole("button", { name: /Farbschema/ }).click();
  await expect(page.locator("html")).toHaveClass(/light/);
  await expectNoSeriousA11yViolations(page);
});

test("history export link carries query and format", async ({ page }) => {
  await page.goto("/de/history");
  const href = await page.getByRole("link", { name: "CSV exportieren" }).getAttribute("href");
  expect(href).toContain("/api/v1/export?");
  expect(href).toContain("format=csv");
  const response = await page.request.get(href ?? "");
  expect(response.ok()).toBeTruthy();
  expect(await response.text()).toContain("# license:");
});

test("kiosk is full screen without navigation", async ({ page }) => {
  await page.goto("/de/kiosk");
  await expect(page.getByRole("navigation", { name: "Hauptnavigation" })).toHaveCount(0);
  await expect(page.locator("html")).toHaveClass(/kiosk/);
  await expectNoSeriousA11yViolations(page);
});

test.describe("visual regression", () => {
  // Live numbers and charts are masked; layout, typography and colours are compared.
  const masks = (page: Page) => [
    page.getByTestId("big-number"),
    page.getByRole("img"),
    page.locator("time"),
    page.locator("table"),
    page.locator("[aria-live]"),
  ];

  test("dashboard (dark)", async ({ page }) => {
    await page.goto("/de");
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveScreenshot("dashboard-dark.png", {
      fullPage: true,
      mask: masks(page),
    });
  });

  test("dashboard (light)", async ({ page }) => {
    await page.goto("/de");
    await page.getByRole("button", { name: /Farbschema/ }).click();
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveScreenshot("dashboard-light.png", {
      fullPage: true,
      mask: masks(page),
    });
  });

  test("kiosk", async ({ page }) => {
    await page.goto("/de/kiosk");
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveScreenshot("kiosk.png", { fullPage: true, mask: masks(page) });
  });
});
