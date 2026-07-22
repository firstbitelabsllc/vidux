import { test, expect } from '@playwright/test';

// Visual regression — Linux-only by default (font hinting drift between
// macOS and Ubuntu otherwise flaps every snapshot). Gated by the `@visual`
// tag; playwright.config.ts grep-inverts the tag on local Mac runs.
//
// To regenerate snapshots locally: `PLAYWRIGHT_RUN_VISUAL=1 npm run
// test:visual:update`. In CI, snapshots run on every PR on Ubuntu.

test.describe('@visual layout snapshots', () => {
  test('desktop 1440 sidebar + empty pane', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/');
    await page.locator('#sidebar-list .plan-row').first().waitFor();
    await expect(page).toHaveScreenshot('layout-1440.png', {
      fullPage: true,
      maxDiffPixelRatio: 0.02,
    });
  });

  test('ipad portrait 800 narrow sidebar', async ({ page }) => {
    await page.setViewportSize({ width: 800, height: 1100 });
    await page.goto('/');
    await page.locator('#sidebar-list .plan-row').first().waitFor();
    await expect(page).toHaveScreenshot('layout-800.png', {
      fullPage: true,
      maxDiffPixelRatio: 0.02,
    });
  });

  test('iphone portrait 390 drawer mode', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    // Drawer mode — sidebar collapsed, toggle button visible.
    await expect(page.locator('.sidebar-toggle')).toBeVisible();
    await expect(page).toHaveScreenshot('layout-390.png', {
      fullPage: true,
      maxDiffPixelRatio: 0.02,
    });
  });
});
