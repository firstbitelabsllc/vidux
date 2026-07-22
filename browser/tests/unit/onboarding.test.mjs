// @vitest-environment node
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const source = fs.readFileSync(
  fileURLToPath(new URL('../../static/onboarding.js', import.meta.url)),
  'utf8',
);
const context = { window: {} };
vm.runInNewContext(source, context);
const onboarding = context.window.ViduxOnboarding;

describe('onboarding UI', () => {
  it('renders one path-free first-run command', () => {
    const html = onboarding.renderEmpty({
      state: 'empty',
      projects_total: 0,
      init_command: 'vidux init --here',
    }, []);

    expect(html).toContain('Connect your first project');
    expect(html).toContain('<code>vidux init --here</code>');
    expect(html).toContain('data-refresh-plans');
    expect(html).not.toContain('/Users/');
  });

  it('escapes discovered project names', () => {
    const html = onboarding.renderEmpty({
      state: 'projects_found',
      projects_total: 1,
      projects: [{ name: '<script>alert(1)</script>' }],
    }, []);

    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;');
    expect(html).not.toContain('<script>');
  });

  it('renders only concrete authority conflicts and escapes their explanation', () => {
    expect(onboarding.renderAuthority({ state: 'ranked' })).toBe('');
    const html = onboarding.renderAuthority({
      state: 'conflict',
      explanation: 'Showing <beta> & waiting.',
    });

    expect(html).toContain('Current-work tie');
    expect(html).toContain('Showing &lt;beta&gt; &amp; waiting.');
    expect(html).toContain('data-open-sidebar');
  });
});
