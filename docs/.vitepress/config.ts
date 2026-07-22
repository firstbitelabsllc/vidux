const sidebar = [
  {
    text: 'Getting Started',
    items: [
      { text: 'What is Vidux?', link: '/guide/' },
      { text: 'Installation', link: '/guide/installation' },
      { text: 'Quick Start', link: '/guide/quickstart' },
    ],
  },
  {
    text: 'Core Concepts',
    items: [
      { text: 'Overview', link: '/concepts/' },
      { text: 'Five Principles', link: '/concepts/principles' },
      { text: 'The Cycle', link: '/concepts/cycle' },
      { text: 'PLAN.md Structure', link: '/concepts/plan-structure' },
      { text: 'The Store', link: '/concepts/store' },
      { text: 'Extensions', link: '/concepts/extensions' },
    ],
  },
  {
    text: 'Fleet',
    items: [
      { text: 'Overview', link: '/fleet/' },
      { text: 'Claude Lifecycle', link: '/fleet/claude-lifecycle' },
      { text: 'Codex Lifecycle', link: '/fleet/codex-lifecycle' },
      { text: 'Codex Setup', link: '/fleet/codex-setup' },
      { text: 'Platform Comparison', link: '/fleet/platforms' },
      { text: 'Harness Authoring', link: '/fleet/harness' },
      { text: 'Fleet Operations', link: '/fleet/operations' },
      { text: 'Recipe Catalog', link: '/fleet/recipes' },
    ],
  },
  {
    text: 'Reference',
    items: [
      { text: 'Overview', link: '/reference/' },
      { text: 'PLAN.md Fields', link: '/reference/plan-fields' },
      { text: 'Prompt Template', link: '/reference/prompt-template' },
      { text: 'Commands', link: '/reference/commands' },
      { text: 'Scripts', link: '/reference/scripts' },
      { text: 'Browser UI', link: '/reference/browser' },
      { text: 'Hooks', link: '/reference/hooks' },
      { text: 'Configuration', link: '/reference/config' },
    ],
  },
  {
    text: 'Examples',
    items: [
      { text: 'Overview', link: '/examples/' },
    ],
  },
]

export default {
  title: 'Vidux',
  description: 'Plan first, code second. A plan-first control plane for AI coding work that spans multiple sessions, agents, or days.',
  base: process.env.DOCS_BASE || '/',
  cleanUrls: true,

  themeConfig: {
    siteTitle: 'Vidux',

    nav: [
      { text: 'Guide', link: '/guide/' },
      { text: 'Concepts', link: '/concepts/' },
      { text: 'Fleet', link: '/fleet/' },
      { text: 'Reference', link: '/reference/' },
      { text: 'Examples', link: '/examples/' },
    ],

    sidebar: {
      '/': sidebar,
      '/guide/': sidebar,
      '/concepts/': sidebar,
      '/fleet/': sidebar,
      '/reference/': sidebar,
      '/examples/': sidebar,
    },

    outline: {
      level: [2, 3],
      label: 'On this page',
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/firstbitelabsllc/vidux' },
    ],

    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Copyright © 2026-present First Bite Labs LLC',
    },

    editLink: {
      pattern: 'https://github.com/firstbitelabsllc/vidux/edit/main/docs/:path',
      text: 'Edit this page on GitHub',
    },

    search: {
      provider: 'local',
    },
  },
}
