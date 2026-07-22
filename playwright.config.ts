import { defineConfig, devices } from '@playwright/test';
import { resolve } from 'node:path';

// Playwright config for vidux-browser e2e + visual smoke. The webServer
// directive boots browser/server.py against fixture roots + an ephemeral port
// so tests are hermetic — they don't scan the contributor's real
// ~/Development/. The explicit fixture stores below make this work.
//
// Visual regression is Linux-only (font hinting diverges between macOS and
// Ubuntu; snapshots flap otherwise). Local Mac runs skip visual specs by
// default; CI on Linux runs them.

const PORT = process.env.VIDUX_TEST_PORT ?? '7291';
const isMac = process.platform === 'darwin';
const STEERING_PATH = process.env.VIDUX_TEST_STEERING_PATH
  ?? resolve('test-results', `steering-${PORT}-${process.pid}.jsonl`);
process.env.VIDUX_TEST_STEERING_PATH = STEERING_PATH;
const CLAIMS_PATH = process.env.VIDUX_TEST_CLAIMS_PATH
  ?? resolve('test-results', `claims-${PORT}-${process.pid}.jsonl`);
process.env.VIDUX_TEST_CLAIMS_PATH = CLAIMS_PATH;

// Serve an untracked live copy of the fixture root: e2e writes (INBOX notes,
// comments anchors) stay out of tracked fixtures, and the operator-brief
// Updated date is refreshed each run so the 7-day freshness window cannot rot
// the suite (a hardcoded fixture date crossed the window on 2026-07-17). The
// one-shot global setup owns every destructive fixture write. Playwright loads
// this config in worker processes too, so module evaluation must stay read-only.
const LIVE_ROOT = process.env.VIDUX_TEST_DEV_ROOT
  ?? resolve('test-results', `fake-dev-root-${PORT}-${process.pid}`);
process.env.VIDUX_TEST_DEV_ROOT = LIVE_ROOT;

export default defineConfig({
  testDir: 'browser/tests/e2e',
  globalSetup: 'browser/tests/e2e/global-setup.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  // The suite shares one fixture server and a few mutable comment fixtures.
  // Keep local runs bounded so `npm run test:e2e` does not fan out
  // to every CPU, overload the server, and close browser contexts mid-test.
  workers: process.env.CI ? 1 : 3,
  reporter: process.env.CI ? [['github'], ['html']] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'desktop-chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'ipad-portrait',
      use: { ...devices['Desktop Chrome'], viewport: { width: 800, height: 1100 } },
    },
    {
      name: 'iphone-portrait',
      use: { ...devices['iPhone 14'], viewport: { width: 390, height: 844 } },
    },
  ],
  webServer: {
    command: `python3 browser/server.py --root ${JSON.stringify(LIVE_ROOT)} --port ${PORT} --comments-path browser/tests/fixtures/comments.jsonl --steering-path ${JSON.stringify(STEERING_PATH)} --claims-path ${JSON.stringify(CLAIMS_PATH)} --artifacts-dir browser/tests/fixtures/artifacts`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    // `reuseExistingServer: !process.env.CI` only
    // verifies the health URL is *reachable* -- it never checks WHICH
    // server answered. Playwright skips running `command` entirely when
    // something already responds on the port, so any stray process bound
    // to this port (a leftover `vidux dev`, another checkout's test run)
    // gets silently adopted as "the fixture server", contradicting the
    // hermeticity this config's own header comment promises and risking
    // real ~/Development content leaking into traces/screenshots.
    // Playwright's webServer has no content-verification hook for the
    // reuse path (the check is skip-command-if-URL-responds, full stop),
    // so the only way to actually close this is to never reuse: always
    // start a fresh, fixture-scoped server for every run. The dedicated
    // test port (7291, distinct from the 7191 default) already makes a
    // same-port collision unlikely; not reusing removes it entirely.
    reuseExistingServer: false,
    timeout: 30_000,
  },
  // Visual specs are gated by env — skip on Mac (font drift), enable in CI.
  // To force visuals locally: `PLAYWRIGHT_RUN_VISUAL=1 npm run test:e2e`.
  grepInvert: (!process.env.CI && isMac && !process.env.PLAYWRIGHT_RUN_VISUAL) ? /@visual/ : undefined,
});
