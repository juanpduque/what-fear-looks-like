import { defineConfig } from '@playwright/test';

// Browser smoke tests against the production build (vite build + preview), the
// same bundle Pages serves. CI installs Playwright's Chromium; locally set
// PW_CHANNEL=chrome to reuse an installed Chrome instead of downloading one.
const PORT = 4173;

export default defineConfig({
  testDir: 'tests',
  timeout: 60_000,
  expect: { timeout: 20_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['github']] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}/what-fear-looks-like/`,
    channel: process.env.PW_CHANNEL || undefined,
    viewport: { width: 1440, height: 900 },
  },
  webServer: {
    command: `npm run build && npm run preview -- --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}/what-fear-looks-like/`,
    timeout: 180_000,
    reuseExistingServer: !process.env.CI,
  },
});
