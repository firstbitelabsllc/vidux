import { test, expect, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { createServer } from 'node:http';
import { resolve } from 'node:path';

async function openDrawerIfNeeded(page: Page) {
  const toggle = page.locator('#sidebar-toggle');
  if (await toggle.isVisible() && await toggle.getAttribute('aria-expanded') !== 'true') {
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  }
}

async function expandGroup(page: Page, name: string) {
  await openDrawerIfNeeded(page);
  const button = page.locator('.repo-disclosure', { hasText: name }).first();
  await button.waitFor();
  if (await button.getAttribute('aria-expanded') !== 'true') {
    await button.click();
  }
  await expect(page.locator('.repo-disclosure', { hasText: name }).first()).toHaveAttribute('aria-expanded', 'true');
}

async function expandProjectGroups(page: Page) {
  await openDrawerIfNeeded(page);
  const names = await page.locator('.repo-disclosure').allTextContents();
  for (const raw of names) {
    const name = raw.replace(/[▾▸]/g, '').replace(/\d+\s*$/, '').trim();
    if (name && name !== 'artifacts' && name !== 'recently viewed') {
      await expandGroup(page, name);
    }
  }
}

async function toggleAdvanced(page: Page) {
  const topbar = page.locator('#mode-toggle');
  if (await topbar.isVisible()) {
    await topbar.click();
  } else {
    await openDrawerIfNeeded(page);
    await page.locator('#sidebar-mode-toggle').click();
  }
  await expect(page.locator('html')).toHaveClass(/advanced-mode/);
}

async function visibleThemeToggle(page: Page) {
  const topbar = page.locator('#theme-toggle');
  if (await topbar.isVisible()) return topbar;
  await openDrawerIfNeeded(page);
  return page.locator('#sidebar-theme-toggle');
}

// Hermetic smoke specs — talk to the fixture-root server booted by
// playwright.config.ts. They prove: server boots, html renders, sidebar
// populates from fixtures, filter narrows results, sidebar sort/chips persist,
// theme toggle works, and the accessibility attrs added in commits 6d9066b
// + 4f7edde are present in the live DOM.

test.describe('vidux-browse smoke', () => {
  test('server health returns ok', async ({ request }) => {
    const res = await request.get('/api/health');
    expect(res.ok()).toBeTruthy();
  });

  test('GET / renders topbar', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.topbar h1')).toHaveText('Vidux');
  });

  test('clean first run gives one public setup command and rescans', async ({ page }) => {
    let planRequests = 0;
    await page.route('**/api/plans', async route => {
      planRequests += 1;
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          plans: [],
          summary: { plans: 0, repos: 0 },
          dashboard: {
            plans_scanned: 0,
            repos: 0,
            mission_control: {
              briefs_total: 0,
              selected: null,
              authority: { state: 'missing', claims_total: 0, tied_total: 0 },
            },
            onboarding: {
              state: 'empty',
              projects_total: 0,
              plans_total: 0,
              connected_projects: 0,
              unconnected_projects: 0,
              briefs_total: 0,
              missing_briefs_total: 0,
              projects: [],
              init_command: 'vidux init --here',
            },
            categories: {},
          },
          dev_root: '/private/fixture-root-that-must-not-render',
        }),
      });
    });
    await page.route('**/api/artifacts', async route => {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ artifacts: [] }) });
    });

    await page.goto('/');

    const setup = page.locator('.mission-control.is-empty');
    await expect(setup.locator('h2')).toHaveText('Connect your first project');
    await expect(setup.locator('code')).toHaveText('vidux init --here');
    await expect(setup).toContainText('Open a terminal in your project');
    await expect(page.locator('#sidebar-list')).toContainText('vidux init --here');
    await expect(page.locator('body')).not.toContainText('/private/fixture-root-that-must-not-render');
    await setup.locator('[data-refresh-plans]').click();
    await expect.poll(() => planRequests).toBeGreaterThan(1);

    const widths = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      content: document.documentElement.scrollWidth,
    }));
    expect(widths.content).toBeLessThanOrEqual(widths.viewport);
  });

  test('tied current-work claims are explicit and inspectable', async ({ page }) => {
    const planPath = '/tmp/vidux-onboarding/beta/PLAN.md';
    const planRel = 'beta/PLAN.md';
    await page.route('**/api/plans', async route => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          plans: [{
            repo: 'beta', slug: '_root_', rel: planRel, path: planPath,
            status: 'hot', age_days: 0, size: 256, siblings: [], investigations: [],
            evidence: [], child_rels: [], task_stats: { total: 1, counts: { pending: 1 } },
            aggregate_stats: { total: 1, descendants: 0, counts: { pending: 1 } },
          }],
          dashboard: {
            mission_control: {
              briefs_total: 2,
              selected: {
                repo: 'beta', rel: planRel, path: planPath, status: 'watching', priority: 80,
                outcome: 'Ship beta with proof.', next: 'Run the proof.',
                why: 'Two projects claim the same priority.', validation: 'Inspect the receipt.',
                cost: 'No paid runtime.', evidence_target: { state: 'needed' }, scorecard: [],
                freshness: { status: 'fresh', age_days: 0 }, updated: '2026-07-10',
                selection_reason: 'priority 80 · newest of 2 tied current goals',
              },
              authority: {
                state: 'conflict', claims_total: 2, tied_total: 2, priority: 80,
                tied_projects: ['alpha', 'beta'],
                explanation: '2 plans share priority 80. Showing beta by latest plan change, then plan name. Change Priority in one Operator Brief to choose the default.',
              },
            },
            onboarding: { state: 'authority_conflict' },
            categories: {},
          },
        }),
      });
    });
    await page.route('**/api/artifacts', async route => {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ artifacts: [] }) });
    });

    await page.goto('/');

    const conflict = page.locator('.mission-authority-note');
    await expect(conflict).toBeVisible();
    await expect(conflict).toContainText('Current-work tie');
    await expect(conflict).toContainText('2 plans share priority 80');
    await expect(conflict).toContainText('Showing beta');
    await conflict.locator('[data-open-sidebar]').click();
    const drawerToggle = page.locator('#sidebar-toggle');
    if (await drawerToggle.isVisible()) {
      await expect(drawerToggle).toHaveAttribute('aria-expanded', 'true');
    } else {
      await expect(page.locator('#sidebar')).toBeVisible();
    }
  });

  test('simple mode leads with inspectable mission proof and opens its plan', async ({ page }) => {
    await page.goto('/');

    const mission = page.locator('.mission-control');
    await expect(mission).toBeVisible();
    await expect(mission.locator('h2')).toHaveText(
      'Prove the browser leads with one evidence-backed mission.',
    );
    await expect(mission.locator('.mission-metric.status-winning')).toHaveCount(1);
    await expect(mission.locator('.mission-metric.status-losing')).toHaveCount(1);
    await expect(mission.locator('.mission-scorecard-tally')).toHaveAttribute(
      'aria-label',
      '1 winning, 1 losing, 0 unproven',
    );
    await expect(mission.locator('.mission-metric .mission-proof-link')).toHaveCount(2);
    await expect(mission.locator('.mission-details .mission-proof-link')).toHaveCount(1);
    await expect(mission.locator('.freshness-fresh')).toContainText('fresh');
    await expect(page.locator('.dashboard-panel')).toHaveCount(0);

    const widths = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      content: document.documentElement.scrollWidth,
    }));
    expect(widths.content).toBeLessThanOrEqual(widths.viewport);

    await mission.locator('.mission-open-plan').click();
    await expect(page).toHaveURL(/plan=proj-alpha%2FPLAN\.md/);
    await expect(page.locator('.pane-header h2')).toHaveText('proj-alpha');
  });

  test('30-issue work queue stays truthful and usable at desktop and 320px', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const controlRel = 'control/PLAN.md';
    const planFor = (repo: string) => ({
      repo,
      slug: '_root_',
      rel: `${repo}/PLAN.md`,
      path: `/tmp/vidux-work-queue/${repo}/PLAN.md`,
      status: 'hot',
      age_days: 0,
      size: 256,
      siblings: [],
      investigations: [],
      evidence: [],
      child_rels: [],
      task_stats: { total: 5, counts: { pending: 1, in_progress: 2, blocked: 2 } },
      aggregate_stats: { total: 5, descendants: 0, counts: { pending: 1, in_progress: 2, blocked: 2 } },
    });
    const workItems = (status: 'pending' | 'in_progress' | 'blocked', prefix: string) =>
      Array.from({ length: 10 }, (_, index) => {
        const repo = `project-${index % 6}`;
        return {
          kind: 'task',
          repo,
          rel: `${repo}/PLAN.md`,
          path: `/tmp/vidux-work-queue/${repo}/PLAN.md`,
          source_rel: `${repo}/PLAN.md`,
          tab: 'PLAN.md',
          line: index + 10,
          status,
          severity: index % 3 === 0 ? 'p0' : 'p1',
          label: `${prefix} Kundenabrechnung mit internationalisierten Steuerbelegen und einer langen eindeutigen Fehlerbeschreibung ${index}`,
          owner: `team-${index % 3}`,
          blocker: status === 'blocked' ? `dependency-${index}` : undefined,
          validation: `npm test queue-${index}`,
          proof: `evidence/queue-${index}.md`,
        };
      });
    const categories = {
      next: { label: 'Next', items: workItems('pending', 'Next'), total: 10, truncated: false, limit: 200 },
      in_progress: { label: 'In Progress', items: workItems('in_progress', 'Resume'), total: 10, truncated: false, limit: 200 },
      blocked: { label: 'Blocked', items: workItems('blocked', 'Blocked'), total: 10, truncated: false, limit: 200 },
    };

    await page.route('**/api/plans', async route => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          plans: [planFor('control'), ...Array.from({ length: 6 }, (_, index) => planFor(`project-${index}`))],
          summary: { plans: 7, repos: 7 },
          dashboard: {
            plans_scanned: 7,
            repos: 7,
            mission_control: {
              briefs_total: 1,
              selected: {
                repo: 'control', rel: controlRel, path: '/tmp/vidux-work-queue/control/PLAN.md',
                status: 'shipping', priority: 100, outcome: 'Resolve the highest-value work across projects.',
                next: 'Start with the first urgent item.', why: 'Severity and proof decide the queue.',
                validation: 'Inspect all 30 issues.', cost: 'No model call required.',
                evidence_target: { state: 'needed' }, scorecard: [], scorecard_total: 0,
                scorecard_truncated: false, freshness: { status: 'fresh', age_days: 0 },
                updated: '2026-07-10', selection_reason: 'only declared current goal',
              },
              authority: { state: 'selected', claims_total: 1, tied_total: 1 },
            },
            onboarding: { state: 'ready' },
            categories,
          },
        }),
      });
    });
    await page.route('**/api/artifacts', async route => {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ artifacts: [] }) });
    });

    await page.goto('/');
    const queue = page.locator('.simple-queue');
    await expect(queue).toBeVisible();
    await expect(queue.locator('.simple-queue-list')).toHaveCount(3);
    await expect(queue.locator('.simple-queue-row')).toHaveCount(24);
    await expect(queue.getByText('8 of 10', { exact: true })).toHaveCount(3);
    await expect(queue.locator('.simple-queue-list').nth(1).locator('.simple-queue-project', { hasText: 'project-0' })).toHaveCount(2);
    await expect(queue).toContainText('Owner team-0');
    await expect(queue).toContainText('Check npm test queue-0');
    await expect(queue).toContainText('Proof evidence/queue-0.md');

    const desktopWidths = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      content: document.documentElement.scrollWidth,
    }));
    expect(desktopWidths.content).toBeLessThanOrEqual(desktopWidths.viewport);

    await page.setViewportSize({ width: 320, height: 760 });
    const firstLabel = queue.locator('.simple-queue-row strong').first();
    const labelMetrics = await firstLabel.evaluate(element => {
      const style = getComputedStyle(element);
      return {
        height: element.getBoundingClientRect().height,
        lineHeight: Number.parseFloat(style.lineHeight),
        whiteSpace: style.whiteSpace,
      };
    });
    expect(labelMetrics.whiteSpace).toBe('normal');
    expect(labelMetrics.height).toBeGreaterThan(labelMetrics.lineHeight * 1.5);
    const mobileWidths = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      content: document.documentElement.scrollWidth,
    }));
    expect(mobileWidths.content).toBeLessThanOrEqual(mobileWidths.viewport);

    await queue.locator('[data-view-all-work]').first().click();
    await expect(page.locator('html')).toHaveClass(/advanced-mode/);
    await expect(page.locator('.dashboard-panel')).toBeVisible();
    await expect(page.locator('.dashboard-list-next .dashboard-item')).toHaveCount(10);
  });

  test('mission proof opens the validated evidence file', async ({ page }) => {
    await page.goto('/');
    await page.locator('.mission-proof-link').first().click();
    await expect(page).toHaveURL(/tab=EVD%3A/);
    await expect(page.locator('.pane-header h2')).toHaveText('proj-alpha');
    await expect(page.locator('#md-body')).toContainText('Mission Control Proof');
  });

  test('live work shows four disjoint owners and a usage-exhausted resume', async ({ page }) => {
    await page.route('**/api/coordination**', async route => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          active: Array.from({ length: 4 }, (_, index) => ({
            owner: `demo-chat-${index + 1}`,
            lane: `currency-${index + 1}`,
            task_id: `row-${index + 1}`,
            claim: `Sources/Currency${index + 1}.swift`,
            checkpoint: { summary: `proof ${index + 1} green`, resume: `open row ${index + 1}` },
            expires_at: '2099-07-11T19:12:00Z',
          })),
          handoffs: [{
            owner: 'demo-chat-old',
            claim: 'Sources/Workbench.swift',
            status: 'usage_exhausted',
            checkpoint: { summary: 'layout proof pending', resume: 'run workbench tests' },
          }],
        }),
      });
    });

    await page.goto('/?plan=proj-alpha%2FPLAN.md');
    const panel = page.locator('[data-coordination-panel]');
    await expect(panel).toBeVisible();
    await expect(panel.locator('.coordination-card')).toHaveCount(4);
    await expect(panel).toContainText('demo-chat-4');
    await expect(panel).toContainText('proof 4 green');
    await expect(panel).toContainText('Usage exhausted');
    await expect(panel).toContainText('run workbench tests');
    await expect(panel.locator('[data-coordination-count]')).toHaveText('4 live');

    await page.setViewportSize({ width: 320, height: 760 });
    const widths = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      content: document.documentElement.scrollWidth,
    }));
    expect(widths.content).toBeLessThanOrEqual(widths.viewport);
  });

  test('one-shot steering stays local, survives exhaustion, and disappears after acknowledgement', async ({ page }) => {
    let items: Array<Record<string, unknown>> = [];
    let enqueuePosts = 0;
    await page.route('**/api/steering**', async route => {
      const request = route.request();
      if (request.method() === 'POST') {
        const payload = request.postDataJSON() as Record<string, string>;
        if (payload.action === 'enqueue') {
          enqueuePosts += 1;
          await new Promise(resolveDelay => setTimeout(resolveDelay, 100));
          items = [{
            id: 'steer-1',
            message: payload.message,
            status: 'queued',
            created_at: '2026-07-11T18:45:00Z',
          }];
        } else if (payload.action === 'retry') {
          items = items.map(item => item.id === payload.id
            ? { ...item, status: 'queued', failure_code: null }
            : item);
        } else if (payload.action === 'dismiss') {
          items = items.filter(item => item.id !== payload.id);
        }
        await route.fulfill({
          contentType: 'application/json',
          body: JSON.stringify({ ok: true }),
        });
        return;
      }
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, capacity: 8, items }),
      });
    });

    await page.goto('/?plan=proj-alpha%2FPLAN.md');
    const inbox = page.locator('[data-steering-inbox]');
    await expect(inbox).toBeVisible();
    await expect(inbox).toContainText('This does not send a chat message');
    await inbox.locator('textarea').fill('Use the intermediate plan, then re-rank the next safe slice.');
    await inbox.locator('textarea').evaluate(element => {
      const event = { key: 'Enter', code: 'Enter', ctrlKey: true, bubbles: true, cancelable: true };
      element.dispatchEvent(new KeyboardEvent('keydown', event));
      element.dispatchEvent(new KeyboardEvent('keydown', event));
    });
    await expect(inbox.locator('.steering-item.is-queued')).toContainText('Use the intermediate plan');
    await expect(inbox.locator('[data-steering-write-status]')).toContainText('Queued for the next safe boundary');
    expect(enqueuePosts).toBe(1);

    items = items.map(item => ({ ...item, status: 'claimed' }));
    await page.reload();
    await expect(page.locator('.steering-item.is-claimed')).toContainText('Being handled');

    items = items.map(item => ({ ...item, status: 'retryable', failure_code: 'usage_exhausted' }));
    await page.reload();
    const retryable = page.locator('.steering-item.is-retryable');
    await expect(retryable).toContainText('Usage window exhausted');
    await expect(retryable).toContainText('was not delivered');
    await retryable.locator('[data-steering-action="retry"]').click();
    await expect(page.locator('.steering-item.is-queued')).toBeVisible();

    // Simulate the outer host callback acknowledging only after its response.
    items = [];
    await page.reload();
    await expect(page.locator('.steering-item')).toHaveCount(0);
    await expect(page.locator('.steering-empty')).toContainText('No steer waiting');

    await page.setViewportSize({ width: 320, height: 760 });
    const widths = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      content: document.documentElement.scrollWidth,
    }));
    expect(widths.content).toBeLessThanOrEqual(widths.viewport);
  });

  test('real GUI and host CLI share one retryable one-shot journal', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop-chromium', 'one shared-store lifecycle is sufficient');

    const devRoot = process.env.VIDUX_TEST_DEV_ROOT
      ?? resolve('browser/tests/fixtures/fake-dev-root');
    const planPath = resolve(devRoot, 'proj-alpha/PLAN.md');
    const storePath = process.env.VIDUX_TEST_STEERING_PATH;
    if (!storePath) throw new Error('VIDUX_TEST_STEERING_PATH was not inherited from Playwright config');
    const steerCli = resolve('scripts/vidux-steer.py');
    const runSteer = (args: string[], input?: Record<string, unknown>) => {
      const output = execFileSync(
        'python3',
        [steerCli, ...args, '--store', storePath, '--root', devRoot, '--json'],
        {
          encoding: 'utf8',
          input: input ? JSON.stringify(input) : undefined,
          env: { ...process.env, VIDUX_DEV_ROOT: devRoot, VIDUX_BROWSER_STEERING_FILE: storePath },
        },
      );
      return JSON.parse(output) as Record<string, any>;
    };

    await page.goto('/?plan=proj-alpha%2FPLAN.md');
    const inbox = page.locator('[data-steering-inbox]');
    const message = `Playwright host handoff ${testInfo.workerIndex}-${Date.now()}`;
    await inbox.locator('textarea').fill(message);
    await inbox.locator('button[type="submit"]').click();
    await expect(inbox.locator('.steering-item.is-queued')).toContainText(message);

    const firstLease = runSteer([
      'lease', '--plan', planPath, '--consumer', 'playwright-host', '--lease-seconds', '60',
    ]).item;
    expect(firstLease.body).toBe(message);
    expect(firstLease.lease_token).toBeTruthy();
    await page.reload();
    await expect(page.locator('.steering-item.is-claimed')).toContainText(message);

    runSteer(['fail', '--stdin-json'], {
      id: firstLease.id,
      lease_token: firstLease.lease_token,
      code: 'usage_exhausted',
    });
    await page.reload();
    const retryable = page.locator('.steering-item.is-retryable');
    await expect(retryable).toContainText('Usage window exhausted');
    await expect(retryable).toContainText('was not delivered');

    await retryable.locator('[data-steering-action="retry"]').click();
    await expect(page.locator('.steering-item.is-queued')).toContainText(message);
    const secondLease = runSteer([
      'lease', '--plan', planPath, '--consumer', 'playwright-host', '--lease-seconds', '60',
    ]).item;
    expect(secondLease.id).toBe(firstLease.id);
    runSteer(['ack', '--stdin-json'], {
      id: secondLease.id,
      lease_token: secondLease.lease_token,
    });

    await page.reload();
    await expect(page.locator('.steering-item')).toHaveCount(0);
    await expect(page.locator('.steering-empty')).toContainText('No steer waiting');
  });

  test('core app zones remain present without FAB/player chrome', async ({ page }) => {
    await page.goto('/');
    const sidebarToggle = page.locator('#sidebar-toggle');
    await openDrawerIfNeeded(page);
    await page.locator('#sidebar-list .plan-row[data-kind="plan"]').first().click();
    if (await sidebarToggle.isVisible()) {
      await expect(sidebarToggle).toHaveAttribute('aria-expanded', 'false');
    }
    await expect(page.locator('[data-vidux-zone="status-header"]')).toBeVisible();
    await expect(page.locator('[data-vidux-zone="content-pane"]')).toBeVisible();
    await expect(page.locator('[data-vidux-zone="mode-detail"]')).toBeVisible();
    // Deleted from main shell (2026-07).
    await expect(page.locator('#root-annotation-toggle')).toHaveCount(0);
    await expect(page.locator('#readaloud-player')).toHaveCount(0);
    await expect(page.locator('[data-vidux-zone="floating-action"]')).toHaveCount(0);
    await expect(page.locator('[data-vidux-zone="footer-player"]')).toHaveCount(0);

    const zones = await page.evaluate(() => {
      const root = getComputedStyle(document.documentElement);
      return {
        header: root.getPropertyValue('--z-header').trim(),
        popover: root.getPropertyValue('--z-mode-popover').trim(),
      };
    });
    expect(Number(zones.header)).toBeLessThan(Number(zones.popover));

    const boxes = await page.evaluate(() => {
      function box(selector: string) {
        const el = document.querySelector(selector);
        if (!el) throw new Error(`missing ${selector}`);
        const rect = el.getBoundingClientRect();
        return {
          top: rect.top,
          right: rect.right,
          bottom: rect.bottom,
          left: rect.left,
          width: rect.width,
          height: rect.height,
        };
      }
      return {
        header: box('[data-vidux-zone="status-header"]'),
        pane: box('[data-vidux-zone="content-pane"]'),
        bodyWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      };
    });
    expect(boxes.pane.bottom).toBeGreaterThan(boxes.header.bottom);
    expect(boxes.scrollWidth).toBeLessThanOrEqual(boxes.bodyWidth);
  });

  test('Cmd/Ctrl+Shift+C starts annotation capture without FAB', async ({ page }) => {
    await page.goto('/');
    const sidebarToggle = page.locator('#sidebar-toggle');
    await openDrawerIfNeeded(page);
    await page.locator('#sidebar-list .plan-row[data-kind="plan"]').first().click();
    if (await sidebarToggle.isVisible()) {
      await expect(sidebarToggle).toHaveAttribute('aria-expanded', 'false');
    }
    await expect(page.locator('[data-comment-empty]')).toContainText('Cmd/Ctrl+Shift+C');
    await page.keyboard.press('Control+Shift+C');
    await expect(page.locator('body')).toHaveClass(/is-annotation-mode/);
    await page.locator('.pane-header h2').click();
    await expect(page.locator('#annotation-popover')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('#annotation-popover')).toHaveCount(0);
    await expect(page.locator('body')).not.toHaveClass(/is-annotation-mode/);
  });

  test('project navigator indexes fixture plans and expands them on demand', async ({ page }) => {
    await page.goto('/');
    await openDrawerIfNeeded(page);
    await expect(page.locator('#sidebar-list .repo-disclosure')).toHaveCount(3);
    await expect(page.locator('.plan-row[title="proj-alpha/PLAN.md"]')).toBeVisible();
    await expect(page.locator('.plan-row[title="proj-beta/PLAN.md"]')).toHaveCount(0);

    await expandGroup(page, 'proj-beta');
    await expect(page.locator('.plan-row[title="proj-beta/PLAN.md"]')).toBeVisible();
  });

  test('filter narrows the sidebar', async ({ page }) => {
    await page.goto('/');
    await openDrawerIfNeeded(page);
    await page.locator('#sidebar-list .repo-disclosure').first().waitFor();
    const before = await page.locator('#sidebar-list .repo-disclosure').count();
    await page.locator('#filter').fill('alpha');
    // give the filter a beat to re-render
    await page.waitForTimeout(150);
    const after = await page.locator('#sidebar-list .repo-disclosure').count();
    expect(after).toBeLessThan(before);
    expect(after).toBeGreaterThanOrEqual(1);
  });

  test('sidebar sort menu orders by ETA and persists', async ({ page }) => {
    await page.goto('/');
    await page.locator('#sidebar-list .plan-row[data-kind="plan"]').first().waitFor();
    await expect(page.locator('#sort')).toBeHidden();
    await toggleAdvanced(page);
    await expect(page.locator('#sort')).toBeVisible();
    await expect(page.locator('#sort')).toHaveValue('mtime');
    await page.locator('#sort').selectOption('eta');
    await expect(page.locator('#sidebar-list .repo-disclosure').first()).toContainText('proj-beta');
    await expect(page.locator('#sort')).toHaveValue('eta');
    await expect(page.locator('#sort option')).toHaveText(['Recently updated', 'ETA', 'Status']);

    await page.reload();
    await expect(page.locator('#sort')).toHaveValue('eta');
    await expect(page.locator('#sidebar-list .repo-disclosure').first()).toContainText('proj-beta');
    expect(await page.evaluate(() => localStorage.getItem('vidux:sidebar-sort'))).toBe('eta');
  });

  test('filter chips narrow by ETA and persist', async ({ page }) => {
    await page.goto('/');
    await toggleAdvanced(page);
    const groups = page.locator('#sidebar-list .repo-disclosure');
    await groups.first().waitFor();
    const before = await groups.count();
    expect(before).toBeGreaterThanOrEqual(3);

    const etaChip = page.locator('[data-filter-chip="eta"]');
    await etaChip.click();
    await expect(etaChip).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('.repo-disclosure', { hasText: 'proj-gamma' })).toHaveCount(0);
    const after = await groups.count();
    expect(after).toBeLessThan(before);
    expect(after).toBeGreaterThanOrEqual(1);

    await page.reload();
    await expect(page.locator('[data-filter-chip="eta"]')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('.repo-disclosure', { hasText: 'proj-gamma' })).toHaveCount(0);
    expect(await page.evaluate(() => localStorage.getItem('vidux:sidebar-filter-chips'))).toBe('["eta"]');
  });

  test('plan rows are native links with useful accessible names', async ({ page }) => {
    await page.goto('/');
    const first = page.locator('#sidebar-list .plan-row[data-kind="plan"]').first();
    await first.waitFor();
    expect(await first.evaluate(el => el.tagName)).toBe('A');
    await expect(first).toHaveAttribute('href', /plan=/);
    await expect(first).not.toHaveAttribute('role', 'option');
    const aria = await first.getAttribute('aria-label');
    expect(aria).toBeTruthy();
    expect(aria!.length).toBeGreaterThan(5);
  });

  test('project navigator uses native nav semantics instead of a mixed listbox', async ({ page }) => {
    await page.goto('/');
    const nav = page.locator('#sidebar-list');
    await nav.locator('.plan-row').first().waitFor();
    expect(await nav.evaluate(el => el.tagName)).toBe('NAV');
    await expect(nav).not.toHaveAttribute('role', 'listbox');
    await expect(nav.locator('[role="option"]')).toHaveCount(0);
  });

  test('collapse-group headers are keyboard-operable (WCAG 2.1.1)', async ({ page }) => {
    // The "repo-group" collapse/expand headers were mouse-only -- no tabindex,
    // no role, no keydown handler -- despite toggling visible content.
    await page.goto('/');
    await openDrawerIfNeeded(page);
    const header = page.locator('#sidebar-list .repo-disclosure').first();
    await header.waitFor();
    expect(await header.evaluate(el => el.tagName)).toBe('BUTTON');
    const expandedBefore = await header.getAttribute('aria-expanded');
    await header.focus();
    await page.keyboard.press('Enter');
    // renderSidebar() rebuilds the list on toggle, so re-query rather than
    // reuse the stale `header` locator handle.
    const headerAfter = page.locator('#sidebar-list .repo-disclosure').first();
    await expect(headerAfter).toHaveAttribute('aria-expanded', expandedBefore === 'true' ? 'false' : 'true');
  });

  test('skip-link is present and anchors to #pane', async ({ page }) => {
    await page.goto('/');
    const link = page.locator('a.skip-link');
    await expect(link).toHaveText('Skip to content');
    await expect(link).toHaveAttribute('href', '#pane');
  });

  test('theme toggle cycles light/dark and persists', async ({ page, context }) => {
    await page.goto('/');
    const btn = await visibleThemeToggle(page);
    await btn.waitFor();
    await btn.click();
    const themeAfter1 = await page.evaluate(() => localStorage.getItem('vidux:theme'));
    expect(['light', 'dark']).toContain(themeAfter1);
    await btn.click();
    const themeAfter2 = await page.evaluate(() => localStorage.getItem('vidux:theme'));
    expect(themeAfter2).not.toBe(themeAfter1);
  });
});

test.describe('keyboard navigation', () => {
  test('ArrowDown/ArrowUp move focus across plan-rows', async ({ page }) => {
    await page.goto('/');
    await expandProjectGroups(page);
    const rows = page.locator('#sidebar-list .plan-row');
    await rows.first().waitFor();
    await rows.first().focus();
    await page.keyboard.press('ArrowDown');
    // The second row should be focused now (assuming at least 2 fixtures).
    const focusedAriaLabel = await page.evaluate(() => document.activeElement?.getAttribute('aria-label'));
    const firstAriaLabel = await rows.first().getAttribute('aria-label');
    expect(focusedAriaLabel).not.toBe(firstAriaLabel);
  });

  test('Home/End jump to first/last', async ({ page }) => {
    await page.goto('/');
    await expandProjectGroups(page);
    const rows = page.locator('#sidebar-list .plan-row');
    await rows.first().waitFor();
    const total = await rows.count();
    await rows.first().focus();
    await page.keyboard.press('End');
    const endAria = await page.evaluate(() => document.activeElement?.getAttribute('aria-label'));
    const lastAria = await rows.nth(total - 1).getAttribute('aria-label');
    expect(endAria).toBe(lastAria);
    await page.keyboard.press('Home');
    const homeAria = await page.evaluate(() => document.activeElement?.getAttribute('aria-label'));
    const firstAria = await rows.first().getAttribute('aria-label');
    expect(homeAria).toBe(firstAria);
  });
});

test.describe('auto-refresh polling', () => {
  test('polls comments, task stats, and artifact content without losing selection', async ({ page }) => {
    // A 200ms interval made this reliably flaky
    // under Playwright's fullyParallel:true (all 3 projects contending for
    // CPU) -- the comment-marker click below adds a transient
    // .is-anchor-highlight class synchronously, but AUTO_REFRESH_INTERVAL_MS
    // is read once at module load and drives an unconditional
    // window.setInterval(autoRefreshTick, ...) with no busy/interaction
    // guard, so any poll tick that lands between the click and the
    // assertion re-renders .pane-header h2 from scratch and wipes the
    // class. 1000ms gives the click a far wider safe gap to be observed in
    // (Playwright's own assertion polling is near-instant) while still
    // comfortably firing within the propagation checks' timeouts below.
    await page.addInitScript(() => {
      (window as any).__VIDUX_AUTO_REFRESH_INTERVAL_MS = 1000;
    });

    let completedTasks = 0;
    let artifactBody = '<!doctype html><html><body><main><h1 id="artifact-title">artifact version A</h1><button id="artifact-action">Inspect</button></main></body></html>';
    let comments: Array<Record<string, unknown>> = [];

    const planPath = '/tmp/vidux-auto-refresh/PLAN.md';
    const inboxPath = '/tmp/vidux-auto-refresh/INBOX.md';
    const artifactPath = '/tmp/vidux-auto-refresh/artifact.html';

    await page.route('**/api/plans', async route => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          plans: [{
            repo: 'fixture',
            slug: 'auto-refresh',
            rel: 'fixture/auto-refresh/PLAN.md',
            path: planPath,
            status: 'active',
            age_days: 0,
            size: 512,
            siblings: ['INBOX.md'],
            investigations: [],
            children: [],
            task_stats: {
              total: 2,
              counts: { completed: completedTasks, pending: 2 - completedTasks },
            },
            aggregate_stats: {
              total: 2,
              descendants: 0,
              counts: { completed: completedTasks, pending: 2 - completedTasks },
            },
          }],
        }),
      });
    });

    await page.route('**/api/artifacts', async route => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          artifacts: [{
            slug: 'live-artifact',
            title: 'Live Artifact',
            path: artifactPath,
            age_days: 0,
            size: artifactBody.length,
          }],
          artifacts_dir: '/tmp/vidux-auto-refresh',
        }),
      });
    });

    await page.route('**/api/file**', async route => {
      const url = new URL(route.request().url());
      const target = url.searchParams.get('path');
      if (target === artifactPath) {
        await route.fulfill({ contentType: 'text/html', body: artifactBody });
        return;
      }
      if (target === inboxPath) {
        await route.fulfill({ contentType: 'text/plain', body: '# Inbox\n\nAuto-refresh tab fixture.' });
        return;
      }
      await route.fulfill({
        contentType: 'text/plain',
        body: `# Auto Refresh\n\n## Tasks\n- [completed] Done ${completedTasks}\n- [pending] Pending\n`,
      });
    });

    await page.route('**/api/comments**', async route => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ comments }),
      });
    });

    await page.goto('/?plan=fixture%2Fauto-refresh%2FPLAN.md&tab=INBOX.md');
    await expect(page.locator('.pane-tabs button.is-active')).toHaveText('INBOX.md');
    await expect(page.locator('.pane-progress .ratio')).toHaveText('0 of 2 tasks');
    await expect(page.locator('#comments-panel')).toHaveAttribute('data-comment-scope', 'current-view');
    await expect(page.locator('#comments-panel')).toHaveAttribute('data-comment-state', 'ready');
    await expect(page.locator('#comments-panel')).toHaveAttribute('data-comment-count', '0');
    await expect(page.locator('[data-comment-empty]')).toContainText('No comments yet.');
    await expect(page.locator('[data-comment-filter="all"]')).toHaveClass(/is-active/);
    await expect(page.locator('#comment-target-map')).toHaveAttribute('data-comment-target-count', '0');

    completedTasks = 1;
    comments = [
      {
        id: 'c1',
        author: 'Test',
        body: 'poll-loaded comment',
        created_at: '2026-05-24T12:00:00Z',
        anchor: { label: 'Inbox heading', selector: '.pane-header h2' },
      },
      {
        id: 'c2',
        author: 'Test',
        body: 'same target comment',
        created_at: '2026-05-24T12:01:00Z',
        anchor: { label: 'Inbox heading', selector: '.pane-header h2' },
      },
      {
        id: 'c3',
        author: 'Test',
        body: 'tab target comment',
        created_at: '2026-05-24T12:02:00Z',
        anchor: { label: 'Tab strip', selector: '.pane-tabs' },
      },
    ];

    await expect(page.locator('.pane-progress .ratio')).toHaveText('1 of 2 tasks', { timeout: 5_000 });
    await expect(page.locator('#comments-panel')).toHaveClass(/has-comments/);
    await expect(page.locator('#comments-panel')).toHaveAttribute('data-comment-count', '3');
    await expect(page.locator('#comments-panel')).toHaveAttribute('data-comment-target-count', '2');
    await expect(page.locator('#comment-count')).toHaveText('3 comments');
    await expect(page.locator('#comment-list')).toContainText('poll-loaded comment');
    await expect(page.locator('#comment-list')).toContainText('same target comment');
    await expect(page.locator('#comment-target-map')).toHaveAttribute('data-comment-target-count', '2');
    await expect(page.locator('#comment-target-map')).toContainText('Inbox heading');
    await expect(page.locator('[data-comment-marker][data-comment-marker-count="2"]')).toBeVisible();
    await expect(page.locator('[data-comment-marker][data-comment-marker-count="1"]')).toBeVisible();
    await page.locator('[data-comment-marker][data-comment-marker-count="2"]').hover();
    await expect(page.locator('.pane-header h2')).toHaveClass(/is-anchor-preview/);
    await page.locator('[data-comment-marker][data-comment-marker-count="2"]').click();
    await expect(page.locator('.pane-header h2')).toHaveClass(/is-anchor-highlight/);
    await page.waitForTimeout(1_600);
    await page.locator('[data-comment-jump="c1"]').click();
    await page.waitForTimeout(800);
    await expect(page.locator('.pane-header h2')).toHaveClass(/is-anchor-highlight/);
    await page.locator('#comment-markers-toggle').click();
    await expect(page.locator('#comments-panel')).toHaveAttribute('data-comment-markers-hidden', 'true');
    await expect(page.locator('[data-comment-marker]')).toHaveCount(0);
    await expect(page.locator('#comment-markers-toggle')).toHaveText('Show');
    await page.locator('#comment-markers-toggle').click();
    await expect(page.locator('#comments-panel')).toHaveAttribute('data-comment-markers-hidden', 'false');
    await expect(page.locator('[data-comment-marker][data-comment-marker-count="2"]')).toBeVisible();
    await page.locator('[data-comment-jump="c1"]').click();
    await expect(page.locator('.pane-header h2')).toHaveClass(/is-anchor-highlight/);
    await expect(page.locator('.pane-tabs button.is-active')).toHaveText('INBOX.md');

    comments = [{
      id: 'a1',
      author: 'Test',
      body: 'artifact target comment',
      created_at: '2026-05-24T12:03:00Z',
      anchor: { label: 'Artifact title', selector: '#artifact-title' },
    }];

    const sidebarToggle = page.locator('#sidebar-toggle');
    await expandGroup(page, 'artifacts');
    const artifactRow = page.locator('#sidebar-list .plan-row[data-kind="artifact"]').first();
    await artifactRow.click();
    const activeArtifactRow = page.locator('#sidebar-list .plan-row[data-kind="artifact"].is-active').first();
    await expect(activeArtifactRow).toHaveClass(/is-active/);
    if (await sidebarToggle.isVisible()) {
      await expect(sidebarToggle).toHaveAttribute('aria-expanded', 'false');
    }
    await expect(page.frameLocator('iframe.artifact-frame').locator('body')).toContainText('artifact version A');
    await expect(page.locator('#comments-panel')).toHaveAttribute('data-comment-target-count', '1');
    await expect(page.locator('#comment-target-map')).toContainText('Artifact title');
    await expect(page.locator('[data-comment-marker][data-comment-marker-count="1"]')).toBeVisible();
    await page.locator('[data-comment-marker][data-comment-marker-count="1"]').click();
    await expect(page.frameLocator('iframe.artifact-frame').locator('#artifact-title')).toHaveClass(/is-anchor-highlight/);

    artifactBody = '<!doctype html><html><body><main><h1 id="artifact-title">artifact version B</h1><button id="artifact-action">Inspect</button></main></body></html>';

    await expect(page.frameLocator('iframe.artifact-frame').locator('body')).toContainText('artifact version B', { timeout: 5_000 });
    await expect(page.locator('#sidebar-list .plan-row[data-kind="artifact"].is-active').first()).toBeVisible();
  });
});

test.describe('artifact styling', () => {
  test('slow artifact base style cannot overwrite a newer plan selection', async ({ page }) => {
    const artifactPath = '/tmp/vidux-artifact-view-revision/probe.html';
    const artifactBody = '<!doctype html><html><head><link rel="stylesheet" href="../static/artifact-base.css" data-vidux-artifact-base></head><body><h1>stale artifact</h1></body></html>';
    let markBaseRequested!: () => void;
    let releaseBaseStyle!: () => void;
    const baseRequested = new Promise<void>(resolve => { markBaseRequested = resolve; });
    const baseStyleGate = new Promise<void>(resolve => { releaseBaseStyle = resolve; });

    await page.route('**/static/artifact-base.css', async route => {
      markBaseRequested();
      await baseStyleGate;
      await route.fulfill({ contentType: 'text/css', body: ':root { color-scheme: light dark; }' });
    });
    await page.route('**/api/artifacts', async route => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          artifacts: [{
            slug: 'revision-probe',
            title: 'Revision Probe',
            path: artifactPath,
            age_days: 0,
            size: artifactBody.length,
          }],
          artifacts_dir: '/tmp/vidux-artifact-view-revision',
        }),
      });
    });
    await page.route('**/api/file**', async route => {
      const url = new URL(route.request().url());
      if (url.searchParams.get('path') === artifactPath) {
        await route.fulfill({ contentType: 'text/html', body: artifactBody });
        return;
      }
      await route.fallback();
    });
    await page.route('**/api/comments**', async route => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ comments: [] }),
      });
    });

    await page.goto('/');
    await expandGroup(page, 'artifacts');
    await page.locator('#sidebar-list .plan-row[data-kind="artifact"]').click();
    await baseRequested;
    await expandGroup(page, 'proj-alpha');
    await page.locator('#sidebar-list .plan-row[data-kind="plan"]').filter({ hasText: 'proj-alpha' }).click();
    await expect(page).toHaveURL(/plan=proj-alpha%2FPLAN\.md/);
    releaseBaseStyle();

    await expect(page.locator('#pane')).toContainText('Proj Alpha');
    await expect(page.locator('iframe.artifact-frame')).toHaveCount(0);
  });

  test('artifact rendering makes no outbound network requests', async ({ page }) => {
    const requests: string[] = [];
    const sink = createServer((req, res) => {
      requests.push(req.url || '/');
      res.writeHead(204, { Connection: 'close' });
      res.end();
    });
    await new Promise<void>((resolve, reject) => {
      sink.once('error', reject);
      sink.listen(0, '127.0.0.1', () => resolve());
    });
    const address = sink.address();
    if (!address || typeof address === 'string') throw new Error('artifact sink did not bind');

    const artifactPath = '/tmp/vidux-artifact-network-isolation/probe.html';
    const sinkOrigin = `http://127.0.0.1:${address.port}`;
    const artifactBody = `<!doctype html>
<html>
<head>
  <meta http-equiv="refresh" content="1;url=${sinkOrigin}/refresh">
  <link rel="stylesheet" href="${sinkOrigin}/style.css">
  <link rel="stylesheet" href="/artifact-same-origin.css">
  <style>
    @import url('/artifact-inline-import.css');
    body { background-image: url('/artifact-inline-background'); }
  </style>
</head>
<body>
  <h1 id="artifact-title">isolated artifact</h1>
  <img src="${sinkOrigin}/passive-image?private=1" alt="">
  <iframe src="${sinkOrigin}/nested-frame"></iframe>
  <a id="external-link" href="${sinkOrigin}/clicked">external link</a>
  <svg viewBox="0 0 200 30" width="200" height="30">
    <a id="svg-external-link" href="${sinkOrigin}/svg-clicked">
      <text x="0" y="20">external SVG link</text>
    </a>
  </svg>
</body>
</html>`;

    try {
      const sameOriginNetworkRequests: string[] = [];
      await page.route(/\/artifact-(?:same-origin|inline-)/, async route => {
        sameOriginNetworkRequests.push(new URL(route.request().url()).pathname);
        await route.fulfill({ status: 204, body: '' });
      });
      await page.route('**/api/artifacts', async route => {
        await route.fulfill({
          contentType: 'application/json',
          body: JSON.stringify({
            artifacts: [{
              slug: 'network-probe',
              title: 'Network Probe',
              path: artifactPath,
              age_days: 0,
              size: artifactBody.length,
            }],
            artifacts_dir: '/tmp/vidux-artifact-network-isolation',
          }),
        });
      });
      await page.route('**/api/file**', async route => {
        const url = new URL(route.request().url());
        if (url.searchParams.get('path') === artifactPath) {
          await route.fulfill({
            contentType: 'text/html',
            headers: {
              'Content-Security-Policy': "default-src 'none'; frame-ancestors 'self'; style-src 'unsafe-inline'",
            },
            body: artifactBody,
          });
          return;
        }
        await route.fallback();
      });
      await page.route('**/api/comments**', async route => {
        await route.fulfill({
          contentType: 'application/json',
          body: JSON.stringify({ comments: [] }),
        });
      });

      await page.goto('/?artifact=network-probe');
      const frame = page.frameLocator('iframe.artifact-frame');
      await expect(frame.locator('body')).toContainText('isolated artifact');
      await frame.locator('#external-link').click();
      await frame.locator('#svg-external-link').click();
      await page.waitForTimeout(1_200);

      expect(requests).toEqual([]);
      expect(sameOriginNetworkRequests).toEqual([]);
      await expect(frame.locator('meta[http-equiv="Content-Security-Policy"]')).not.toHaveAttribute(
        'content',
        /frame-ancestors/i,
      );
      await expect(page.locator('iframe.artifact-frame')).toHaveAttribute(
        'sandbox',
        'allow-same-origin',
      );
      await expect(page.locator('iframe.artifact-frame')).toHaveAttribute(
        'referrerpolicy',
        'no-referrer',
      );
    } finally {
      await new Promise<void>(resolve => sink.close(() => resolve()));
    }
  });

  test('shared artifact base css applies in dark iframe render', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });

    const artifactPath = '/tmp/vidux-artifact-base-css/a/very/long/local/artifact/path/that/should/wrap/in/the/pane/header/instead/of/forcing/mobile-horizontal-overflow/artifact.html';
    const artifactBody = `<!doctype html>
<html>
<head>
  <style>
    :root { --paper: #faf8f5; --ink: #2d231c; }
    body { margin: 0; background: var(--paper); color: var(--ink); }
  </style>
  <link rel="stylesheet" href="../static/artifact-base.css" data-vidux-artifact-base>
</head>
<body><main>shared artifact theme</main></body>
</html>`;

    await page.route('**/api/artifacts', async route => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          artifacts: [{
            slug: 'shared-theme-artifact',
            title: 'Shared Theme Artifact',
            path: artifactPath,
            age_days: 0,
            size: artifactBody.length,
          }],
          artifacts_dir: '/tmp/vidux-artifact-base-css',
        }),
      });
    });

    await page.route('**/api/file**', async route => {
      const url = new URL(route.request().url());
      if (url.searchParams.get('path') === artifactPath) {
        await route.fulfill({ contentType: 'text/html', body: artifactBody });
        return;
      }
      await route.fallback();
    });

    await page.route('**/api/comments**', async route => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ comments: [] }),
      });
    });

    await page.goto('/');
    await expandGroup(page, 'artifacts');
    await page.locator('#sidebar-list .plan-row[data-kind="artifact"]').click();
    const body = page.frameLocator('iframe.artifact-frame').locator('body');
    await expect(body).toContainText('shared artifact theme');
    await expect(page.frameLocator('iframe.artifact-frame').locator('link')).toHaveCount(0);
    await expect(
      page.frameLocator('iframe.artifact-frame').locator('style[data-vidux-artifact-base]'),
    ).toHaveCount(1);
    await expect.poll(async () => (
      body.evaluate(el => getComputedStyle(el).backgroundColor)
    )).toBe('rgb(29, 25, 22)');
    const paneMetrics = await page.locator('#pane').evaluate(el => ({
      scrollWidth: el.scrollWidth,
      clientWidth: el.clientWidth,
    }));
    expect(paneMetrics.scrollWidth).toBeLessThanOrEqual(paneMetrics.clientWidth);
  });

  for (const width of [320, 375, 390, 414]) {
    test(`mobile shell stays one row at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.goto('/');
      const topbar = await page.locator('.topbar').boundingBox();
      expect(topbar).not.toBeNull();
      expect(topbar!.height).toBeLessThanOrEqual(64);
      await expect(page.locator('#mode-toggle')).toBeHidden();
      await expect(page.locator('#theme-toggle')).toBeHidden();
      await expect(page.locator('#sidebar-toggle')).toBeVisible();
      await expect(page.locator('#refresh')).toBeVisible();
    });
  }

  // The topbar-wrap fix above made .topbar
  // grow taller at <=540px (up to 3 wrapped rows), but .sidebar's mobile
  // drawer kept a hardcoded `top: 77px` sized for the old single-row height
  // -- so opening the drawer at these widths rendered its own search/sort/
  // filter controls completely hidden underneath the topbar. Fixed via a
  // ResizeObserver-synced --topbar-rendered-height custom property instead of
  // another hardcoded constant (a magic-number offset here has now broken
  // twice from unrelated topbar content changes). Covers widths where the
  // topbar wraps differently (3 rows, 2 rows, 1 row) to catch the offset
  // going stale at any of them, not just the narrowest.
  for (const width of [375, 414, 540, 768]) {
    test(`mobile drawer search input is not hidden under the topbar at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.goto('/');
      const toggle = page.locator('#sidebar-toggle');
      if (await toggle.isVisible()) {
        await toggle.click();
      }
      const topbarBox = await page.locator('.topbar').boundingBox();
      const searchBox = await page.locator('#filter').boundingBox();
      expect(topbarBox).not.toBeNull();
      expect(searchBox).not.toBeNull();
      if (topbarBox && searchBox) {
        expect(searchBox.y).toBeGreaterThanOrEqual(topbarBox.y + topbarBox.height);
      }
    });
  }

  test('mobile drawer is inert while closed and restores focus on Escape', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    const toggle = page.locator('#sidebar-toggle');
    const sidebar = page.locator('#sidebar');

    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(sidebar).toHaveAttribute('aria-hidden', 'true');
    await expect(sidebar).toHaveAttribute('inert', '');

    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(sidebar).toHaveAttribute('aria-hidden', 'false');
    await expect(page.locator('#filter')).toBeFocused();

    await page.keyboard.press('Escape');
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(sidebar).toHaveAttribute('inert', '');
    await expect(toggle).toBeFocused();
  });

  test('mobile selection closes the drawer and keeps mission proof first', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    const toggle = page.locator('#sidebar-toggle');
    await toggle.click();
    await page.locator('#sidebar-list .plan-row[data-kind="plan"]').first().click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(page.locator('#sidebar')).toHaveAttribute('inert', '');

    await page.goto('/');
    await expect(page.locator('.mission-control')).toBeVisible();
    await expect(page.locator('.mission-next')).toBeVisible();
    await expect(page.locator('.mission-scorecard')).toBeVisible();
    await expect(page.locator('.mission-details')).toBeVisible();
    const positions = await page.evaluate(() => {
      const top = (selector: string) => document.querySelector(selector)!.getBoundingClientRect().top;
      return {
        next: top('.mission-next'),
        results: top('.mission-scorecard'),
        details: top('.mission-details'),
      };
    });
    expect(positions.next).toBeLessThan(positions.results);
    expect(positions.results).toBeLessThan(positions.details);
  });
});

test.describe('subplan row keyboard navigation', () => {
  // Rounds 8/9/10: tests/test_browser_server.py's
  // test_subplan_row_is_keyboard_and_screen_reader_accessible only greps
  // app.js source text for role="button"/tabindex="0"/aria-label/keydown --
  // it never opens a page, focuses a node, or dispatches a keypress, so it
  // would not catch a broken/misattached handler. Reuses this file's own
  // proven idioms: the page.route() mocking pattern from "auto-refresh
  // polling"/"artifact styling" (never touches the shared fixture root,
  // which several count/sort/filter tests elsewhere depend on staying flat
  // at exactly 3 plans) and the focus()+keyboard.press('Enter') pattern
  // from "collapse-group headers are keyboard-operable" above. Mocks one
  // parent plan with one child (mirrors real attach_children()/child_rels
  // wiring: the child is both a flat state.plans entry and named in the
  // parent's child_rels, which hydratePlanChildren() on the client resolves
  // into plan.children for renderPaneSubplans()).
  test('Enter on a focused .subplan-row navigates to the child plan', async ({ page }) => {
    const parentPath = '/tmp/vidux-subplan-nav/parent/PLAN.md';
    const childPath = '/tmp/vidux-subplan-nav/child/PLAN.md';
    const parentRel = 'fixture/subplan-parent/PLAN.md';
    const childRel = 'fixture/subplan-child/PLAN.md';

    const planFor = (over: Record<string, unknown>) => ({
      repo: 'fixture',
      status: 'active',
      age_days: 0,
      size: 256,
      siblings: [],
      investigations: [],
      evidence: [],
      child_rels: [],
      task_stats: { total: 1, counts: { completed: 0, pending: 1 } },
      aggregate_stats: { total: 1, descendants: 0, counts: { completed: 0, pending: 1 } },
      ...over,
    });

    await page.route('**/api/plans', async route => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          plans: [
            planFor({
              slug: 'subplan-parent', rel: parentRel, path: parentPath,
              child_rels: [childRel],
            }),
            planFor({ slug: 'subplan-child', rel: childRel, path: childPath }),
          ],
        }),
      });
    });

    await page.route('**/api/artifacts', async route => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ artifacts: [], artifacts_dir: '/tmp/vidux-subplan-nav' }),
      });
    });

    await page.route('**/api/file**', async route => {
      const url = new URL(route.request().url());
      const target = url.searchParams.get('path');
      const label = target === childPath ? 'Child' : 'Parent';
      await route.fulfill({
        contentType: 'text/plain',
        body: `# ${label}\n\n## Tasks\n- [pending] Do: something\n`,
      });
    });

    await page.route('**/api/comments**', async route => {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ comments: [] }) });
    });

    await page.goto(`/?plan=${encodeURIComponent(parentRel)}`);
    const row = page.locator('.subplan-row[data-subplan-rel="' + childRel + '"]');
    await expect(row).toHaveAttribute('role', 'button');
    await expect(row).toHaveAttribute('tabindex', '0');
    await row.focus();
    await page.keyboard.press('Enter');

    await expect(page).toHaveURL(new RegExp(`plan=${encodeURIComponent(childRel).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`));
    await expect(page.locator('.pane-header h2')).toHaveText('fixture · subplan-child');
    await expect(page.locator('#sidebar-list .plan-row[data-path="' + childPath + '"].is-active').first()).toBeVisible();
  });

  test('sensitive plan state stays explicit without exposing the replaced value', async ({ page }) => {
    const planPath = '/tmp/vidux-sensitive/PLAN.md';
    const planRel = 'fixture/sensitive/PLAN.md';
    const syntheticSecret = 'sk-' + 'A1b2C3d4'.repeat(6);

    await page.route('**/api/plans', async route => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          plans: [{
            repo: 'fixture',
            slug: 'sensitive',
            rel: planRel,
            path: planPath,
            status: 'active',
            age_days: 0,
            size: 256,
            siblings: [],
            investigations: [],
            evidence: [],
            child_rels: [],
            content_redacted: true,
            sensitive_redactions: 2,
            task_stats: { total: 1, counts: { in_progress: 1 } },
            aggregate_stats: { total: 1, descendants: 0, counts: { in_progress: 1 } },
          }],
        }),
      });
    });
    await page.route('**/api/artifacts', async route => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ artifacts: [], artifacts_dir: '/tmp/vidux-sensitive' }),
      });
    });
    await page.route('**/api/file**', async route => {
      await route.fulfill({
        contentType: 'text/plain',
        body: '# Sensitive fixture\n\n## Tasks\n- [in_progress] Rotate [REDACTED:secret]\n',
      });
    });
    await page.route('**/api/comments**', async route => {
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ comments: [] }) });
    });

    await page.goto(`/?plan=${encodeURIComponent(planRel)}`);

    const notice = page.locator('.sensitive-content-notice');
    await expect(notice).toBeVisible();
    await expect(notice).toContainText('Sensitive values hidden');
    await expect(notice).toContainText('2 high-confidence values replaced before display.');
    await expect(notice).toHaveAttribute('data-sensitive-redactions', '2');
    await expect(page.locator('#md-body')).toContainText('[REDACTED:secret]');
    await expect(page.locator('body')).not.toContainText(syntheticSecret);

    await openDrawerIfNeeded(page);
    await expect(page.locator('.plan-row-sensitive')).toContainText('hidden');
    const widths = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      content: document.documentElement.scrollWidth,
    }));
    expect(widths.content).toBeLessThanOrEqual(widths.viewport);
  });
});
