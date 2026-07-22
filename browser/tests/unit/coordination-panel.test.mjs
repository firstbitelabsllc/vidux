// @vitest-environment happy-dom
import { describe, it, expect, vi } from 'vitest';
import fs from 'node:fs';
import vm from 'node:vm';
import { resolve } from 'node:path';

const source = fs.readFileSync(
  resolve(process.cwd(), 'browser/static/coordination-panel.js'),
  'utf8',
);
let fetchImpl = () => Promise.reject(new Error('fetch stub missing'));
const context = { window, document, Date, fetch: (...args) => fetchImpl(...args) };
vm.runInNewContext(source, context);
const panel = context.window.ViduxCoordinationPanel;

describe('live work coordination panel', () => {
  it('renders four disjoint owners with checkpoint and resume truth', () => {
    const now = Date.parse('2026-07-11T19:00:00Z');
    const active = Array.from({ length: 4 }, (_, index) => ({
      owner: `demo-chat-${index + 1}`,
      task_id: `currency-${index + 1}`,
      lane: `Receipt currency lane ${index + 1}`,
      claim: `Sources/Currency${index + 1}.swift`,
      checkpoint: `Proof ${index + 1} is green`,
      resume: `git diff -- Sources/Currency${index + 1}.swift`,
      expires_at: '2026-07-11T19:12:00Z',
    }));

    const html = panel.renderActive(active, now);

    expect((html.match(/coordination-card"/g) || []).length).toBe(4);
    expect(html).toContain('demo-chat-4');
    expect(html).toContain('Proof 4 is green');
    expect(html).toContain('git diff -- Sources/Currency4.swift');
    expect(html).toContain('expires in 12m');
  });

  it('renders usage exhaustion and expiry as resumable, not completed', () => {
    const html = panel.renderHandoffs([
      { owner: 'chat-a', status: 'usage_exhausted', claim: 'currency pill', resume: 'open PLAN row 14' },
      { owner: 'chat-b', status: 'expired', claim: 'workbench overhaul', checkpoint: 'layout proof pending' },
      { owner: 'chat-d', status: 'in_progress', claim: 'receipt detail routing' },
      { owner: 'chat-c', status: 'done', claim: 'merged work' },
    ]);

    expect(html).toContain('Usage exhausted');
    expect(html).toContain('Lease expired');
    expect(html).toContain('In progress');
    expect(html).toContain('open PLAN row 14');
    expect(html).not.toContain('merged work');
  });

  it('does not replace unchanged live-work cards on a repeated poll', async () => {
    const planPath = '/repo/PLAN.md';
    const payload = {
      active: [{
        owner: 'chat-a',
        claim: 'currency pill',
        expires_at: '2099-07-11T19:10:00Z',
      }],
      handoffs: [],
    };
    fetchImpl = vi.fn(async () => ({ ok: true, json: async () => payload }));
    document.body.innerHTML = panel.render(planPath);

    await panel.refresh(planPath);
    const firstCard = document.querySelector('.coordination-card');
    await panel.refresh(planPath);

    expect(document.querySelector('.coordination-card')).toBe(firstCard);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it('escapes owner and checkpoint text and has an honest empty state', () => {
    const html = panel.renderActive([{
      owner: '<script>owner</script>',
      claim: 'Receipt & currency',
      checkpoint: '<img src=x onerror=alert(1)>',
      expires_at: '2026-07-11T19:10:00Z',
    }], Date.parse('2026-07-11T19:00:00Z'));

    expect(html).toContain('&lt;script&gt;owner&lt;/script&gt;');
    expect(html).toContain('Receipt &amp; currency');
    expect(html).not.toContain('<script>');
    expect(panel.renderActive([])).toContain('No live owner. Claim a slice before editing.');
  });
});
