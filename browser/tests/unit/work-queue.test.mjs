// @vitest-environment node
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const source = fs.readFileSync(
  fileURLToPath(new URL('../../static/work-queue.js', import.meta.url)),
  'utf8',
);
const context = { window: {} };
vm.runInNewContext(source, context);
const queue = context.window.ViduxWorkQueue;

function task(index, overrides = {}) {
  return {
    rel: `project-${index}/PLAN.md`,
    repo: `project-${index}`,
    label: `Long localized task ${index}`,
    status: 'in_progress',
    severity: 'p1',
    ...overrides,
  };
}

describe('Simple work queue', () => {
  it('shows eight ordered rows, totals, and a route to the full queue', () => {
    const inProgress = Array.from({ length: 10 }, (_, index) => task(index));
    const html = queue.render({
      next: { items: [task(20, { status: 'pending', severity: 'p0' })], total: 1 },
      in_progress: { items: inProgress, total: 10 },
      blocked: { items: [], total: 0 },
    });

    expect((html.match(/simple-queue-row/g) || []).length).toBe(9);
    expect(html).toContain('8 of 10');
    expect(html).toContain('data-view-all-work');
    expect(html).toContain('P0');
  });

  it('keeps multiple urgent rows from one project and exposes structured truth', () => {
    const rows = [
      task(1, { repo: 'checkout', rel: 'checkout/PLAN.md', owner: 'Web' }),
      task(2, {
        repo: 'checkout', rel: 'checkout/PLAN.md', blocker: 'vendor',
        validation: 'npm test', proof: 'evidence/checkout.md',
      }),
    ];
    const html = queue.render({ in_progress: { items: rows, total: 2 } });

    expect((html.match(/data-dashboard-rel="checkout\/PLAN.md"/g) || []).length).toBe(2);
    expect(html).toContain('Owner Web');
    expect(html).toContain('Blocked by vendor');
    expect(html).toContain('Check npm test');
    expect(html).toContain('Proof evidence/checkout.md');
  });

  it('excludes current-plan rows and escapes untrusted labels', () => {
    const html = queue.render({
      in_progress: {
        items: [
          task(1, { rel: 'current/PLAN.md' }),
          task(2, { label: '<script>alert(1)</script>' }),
        ],
        total: 2,
      },
    }, 'current/PLAN.md');

    expect(html).not.toContain('current/PLAN.md');
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;');
    expect(html).not.toContain('<script>');
  });

  it('uses the server-bounded cross-project slice when the full category is capped', () => {
    const html = queue.render({
      in_progress: {
        items: [task(1, { rel: 'current/PLAN.md' })],
        total: 30,
        simple_items: [task(2), task(3)],
        simple_total: 2,
      },
    }, 'current/PLAN.md');

    expect(html).toContain('2 of 2');
    expect(html).toContain('project-2/PLAN.md');
    expect(html).toContain('project-3/PLAN.md');
    expect(html).not.toContain('current/PLAN.md');
  });
});
