// @vitest-environment node
import { afterEach, describe, expect, it } from 'vitest';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const originalEnv = {
  VIDUX_TEST_DEV_ROOT: process.env.VIDUX_TEST_DEV_ROOT,
  VIDUX_TEST_STEERING_PATH: process.env.VIDUX_TEST_STEERING_PATH,
  VIDUX_TEST_CLAIMS_PATH: process.env.VIDUX_TEST_CLAIMS_PATH,
};
const temporaryRoots: string[] = [];

afterEach(async () => {
  for (const [key, value] of Object.entries(originalEnv)) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
  await Promise.all(temporaryRoots.splice(0).map(path => rm(path, { recursive: true, force: true })));
});

describe('Playwright fixture setup', () => {
  it('keeps config-module evaluation read-only in every worker', async () => {
    const root = await mkdtemp(join(tmpdir(), 'vidux-config-import-'));
    temporaryRoots.push(root);
    const sentinel = join(root, 'sentinel.txt');
    writeFileSync(sentinel, 'preserve me\n');
    process.env.VIDUX_TEST_DEV_ROOT = root;
    process.env.VIDUX_TEST_STEERING_PATH = join(root, 'steering.jsonl');
    process.env.VIDUX_TEST_CLAIMS_PATH = join(root, 'claims.jsonl');

    const config = (await import('../../../playwright.config.ts?read-only-regression')).default;

    expect(readFileSync(sentinel, 'utf8')).toBe('preserve me\n');
    expect(String(config.globalSetup)).toContain('global-setup.ts');
  });

  it('prepares and refreshes the shared fixture exactly when setup runs', async () => {
    const root = await mkdtemp(join(tmpdir(), 'vidux-global-setup-'));
    temporaryRoots.push(root);
    const liveRoot = join(root, 'live');
    mkdirSync(liveRoot);
    writeFileSync(join(liveRoot, 'stale.txt'), 'remove me\n');
    process.env.VIDUX_TEST_DEV_ROOT = liveRoot;
    process.env.VIDUX_TEST_STEERING_PATH = join(root, 'steering.jsonl');
    process.env.VIDUX_TEST_CLAIMS_PATH = join(root, 'claims.jsonl');

    const setup = (await import('../e2e/global-setup.ts')).default;
    setup();

    expect(existsSync(join(liveRoot, 'stale.txt'))).toBe(false);
    const alphaPlan = readFileSync(join(liveRoot, 'proj-alpha/PLAN.md'), 'utf8');
    const recentUpdated = new Date(Date.now() - 3 * 86400000).toISOString().slice(0, 10);
    expect(alphaPlan).toContain(`- Updated: ${recentUpdated}`);
  });
});
