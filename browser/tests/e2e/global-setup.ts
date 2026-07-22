import { cpSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

/** Prepare the one shared fixture root before Playwright starts its workers. */
export default function globalSetup() {
  const port = process.env.VIDUX_TEST_PORT ?? '7291';
  const liveRoot = process.env.VIDUX_TEST_DEV_ROOT;
  if (!liveRoot) {
    throw new Error('VIDUX_TEST_DEV_ROOT must be set by playwright.config.ts');
  }

  const steeringPath = process.env.VIDUX_TEST_STEERING_PATH
    ?? resolve('test-results', `steering-${port}-${process.pid}.jsonl`);
  const claimsPath = process.env.VIDUX_TEST_CLAIMS_PATH
    ?? resolve('test-results', `claims-${port}-${process.pid}.jsonl`);
  for (const path of [
    steeringPath,
    `${steeringPath}.lock`,
    claimsPath,
    `${claimsPath}.lock`,
  ]) {
    rmSync(path, { force: true });
  }

  const fixtureRoot = resolve('browser/tests/fixtures/fake-dev-root');
  rmSync(liveRoot, { recursive: true, force: true });
  cpSync(fixtureRoot, liveRoot, { recursive: true });

  const alphaPlan = resolve(liveRoot, 'proj-alpha/PLAN.md');
  const recentUpdated = new Date(Date.now() - 3 * 86400000).toISOString().slice(0, 10);
  writeFileSync(
    alphaPlan,
    readFileSync(alphaPlan, 'utf8').replace(/^- Updated: .*$/m, `- Updated: ${recentUpdated}`),
  );
}
