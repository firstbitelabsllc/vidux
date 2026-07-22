// @vitest-environment happy-dom
import { describe, it, expect, vi } from 'vitest';
import fs from 'node:fs';
import vm from 'node:vm';
import { resolve } from 'node:path';

const source = fs.readFileSync(
  resolve(process.cwd(), 'browser/static/steering-inbox.js'),
  'utf8',
);
let fetchImpl = () => Promise.reject(new Error('fetch stub missing'));
const context = { window, document, Date, fetch: (...args) => fetchImpl(...args) };
vm.runInNewContext(source, context);
const inbox = context.window.ViduxSteeringInbox;

describe('one-shot steering inbox', () => {
  it('keeps the focused action button when an unchanged poll arrives', async () => {
    const planPath = '/repo/PLAN.md';
    const payload = {
      capacity: 8,
      items: [{
        id: 'steer-1',
        message: 'Keep the currency pill work scoped.',
        status: 'retryable',
        failure_code: 'usage_exhausted',
        created_at: '2026-07-11T18:45:00Z',
      }],
    };
    fetchImpl = vi.fn(async () => ({ ok: true, json: async () => payload }));
    document.body.innerHTML = inbox.render(planPath);

    await inbox.refresh(planPath);
    const retry = document.querySelector('[data-steering-action="retry"]');
    retry.focus();
    await inbox.refresh(planPath);

    expect(document.querySelector('[data-steering-action="retry"]')).toBe(retry);
    expect(document.activeElement).toBe(retry);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });
});
