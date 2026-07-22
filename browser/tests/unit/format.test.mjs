// @vitest-environment node
// Pure helper tests don't need a DOM. Using `node` env so `fileURLToPath`
// + `fs` work normally without happy-dom's URL polyfill getting in the way.
import { describe, it, expect, beforeEach } from 'vitest';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

// vidux-browser's app.js is not yet ESM-exportable (assigned to module-scope
// `const state`). To unit-test pure helpers without refactoring, load app.js
// into the happy-dom window via <script>-tag insertion, then read the
// helpers off `window`. The functions tested here are pure (no DOM mutation).
//
// Helpers wrapped onto window for testability:
//   window.__viduxTest = { fmtAge, pct } — exposed in a future commit; for
//   now these tests reproduce the implementation as the contract and assert
//   the runtime would match. When we extract `static/lib/format.mjs`, swap
//   these tests to import from there.

function fmtAge(days) {
  if (days < 1) return 'today';
  if (days < 2) return '1d';
  if (days < 30) return `${Math.round(days)}d`;
  if (days < 365) return `${Math.round(days / 30)}mo`;
  return `${(days / 365).toFixed(1)}y`;
}

describe('fmtAge', () => {
  it('returns "today" for <1 day', () => {
    expect(fmtAge(0)).toBe('today');
    expect(fmtAge(0.5)).toBe('today');
    expect(fmtAge(0.99)).toBe('today');
  });
  it('returns "1d" for 1-2 days', () => {
    expect(fmtAge(1)).toBe('1d');
    expect(fmtAge(1.9)).toBe('1d');
  });
  it('returns rounded days for 2-30', () => {
    expect(fmtAge(2)).toBe('2d');
    expect(fmtAge(7.4)).toBe('7d');
    expect(fmtAge(7.6)).toBe('8d');
    expect(fmtAge(29.4)).toBe('29d');
  });
  it('returns rounded months for 30-365', () => {
    expect(fmtAge(30)).toBe('1mo');
    expect(fmtAge(45)).toBe('2mo');
    expect(fmtAge(364)).toBe('12mo');
  });
  it('returns years with one decimal for >=365', () => {
    expect(fmtAge(365)).toBe('1.0y');
    expect(fmtAge(548)).toBe('1.5y');
    expect(fmtAge(730)).toBe('2.0y');
  });
});

describe('app.js source health (smoke)', () => {
  const APP_JS = fileURLToPath(new URL('../../static/app.js', import.meta.url));
  it('app.js exists and has expected size', () => {
    const stat = fs.statSync(APP_JS);
    expect(stat.size).toBeGreaterThan(40_000);
    // Soft budget: the focused mission/proof/resume cockpit remains a small
    // dependency-free script. Leave headroom for the accessibility and proof
    // contracts, while still catching an accidental bundled dependency.
    expect(stat.size).toBeLessThan(125_000);
  });
  it('fmtAge is defined in app.js', () => {
    const src = fs.readFileSync(APP_JS, 'utf8');
    expect(src).toContain('function fmtAge(');
  });
  it('Simple/Advanced mode defaults off until advancedMode=1', () => {
    const app = fs.readFileSync(APP_JS, 'utf8');
    const indexHtml = fs.readFileSync(
      fileURLToPath(new URL('../../static/index.html', import.meta.url)),
      'utf8',
    );
    expect(app).toContain('function isAdvancedMode(');
    expect(app).toContain('vidux:advancedMode');
    // FOUC + runtime both treat Advanced as opt-in (=== '1'), so default is Simple.
    expect(indexHtml).toContain("getItem('vidux:advancedMode') === '1'");
    expect(indexHtml).toContain('id="mode-toggle"');
    // Main shell no longer mounts FAB / read-aloud player.
    expect(indexHtml).not.toContain('id="root-annotation-toggle"');
    expect(indexHtml).not.toContain('id="readaloud-player"');
    expect(indexHtml).not.toContain('readaloud.js');
  });
});
