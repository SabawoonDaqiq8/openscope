import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end tests against the production build: FastAPI serves the built Angular app in
 * public-demo mode with a fresh SQLite database, exactly like the deployed demo.
 *
 *   npx ng build && npx playwright test
 */
const port = Number(process.env['E2E_PORT'] ?? 8765);
const db = join(tmpdir(), `openscope-e2e-${process.pid}.db`);

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // the flows share one demo database
  workers: 1,
  retries: process.env['CI'] ? 1 : 0,
  reporter: process.env['CI'] ? [['list'], ['html', { open: 'never' }]] : 'list',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: `http://localhost:${port}`,
    trace: 'off',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: `cd .. && python -m uvicorn openscope.api.app:app --port ${port} --log-level warning`,
    url: `http://localhost:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      OPENSCOPE_PUBLIC_DEMO: '1',
      OPENSCOPE_DB_URL: `sqlite:///${db}`,
      OPENSCOPE_STATIC_DIR: 'web/dist/web/browser',
      OPENSCOPE_DEMO_WRITE_LIMIT: '500',
    },
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] }, testIgnore: /mobile\.spec/ },
    {
      name: 'mobile',
      use: { ...devices['iPhone 13'], browserName: 'chromium' },
      testMatch: /mobile\.spec/,
    },
  ],
});
