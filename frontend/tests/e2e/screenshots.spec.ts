import { test } from "@playwright/test";

/** README screenshots: SCREENSHOTS=1 pnpm exec playwright test screenshots --project=chromium */
test.skip(!process.env.SCREENSHOTS, "only when generating README screenshots (SCREENSHOTS=1)");
test.use({ viewport: { width: 1440, height: 900 } });

const SHOTS = [
  { path: "/de", file: "dashboard.png" },
  { path: "/de/outlook", file: "outlook.png" },
  { path: "/de/kiosk", file: "kiosk.png" },
  { path: "/en/status", file: "status.png" },
];

for (const shot of SHOTS) {
  test(`screenshot ${shot.file}`, async ({ page }) => {
    await page.goto(shot.path);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1500); // charts render lazily
    await page.screenshot({
      path: `../docs/screenshots/${shot.file}`,
      fullPage: shot.file === "dashboard.png",
    });
  });
}
