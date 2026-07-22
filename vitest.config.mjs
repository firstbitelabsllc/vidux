import { defineConfig } from 'vitest/config';

// Vitest config for vidux-browser pure-helper unit tests. Uses happy-dom
// (2-3x faster than jsdom, zero native deps) — enough for the small DOM
// shim our helpers need. Tests live under `browser/tests/unit/`.
export default defineConfig({
  test: {
    environment: 'happy-dom',
    include: ['browser/tests/unit/**/*.test.{js,mjs,ts}'],
    coverage: {
      reporter: ['text', 'lcov'],
      include: ['browser/static/**/*.{js,mjs}'],
    },
  },
});
