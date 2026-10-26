import { defineConfig, devices } from '@playwright/test';

// E2E smoke against a RUNNING stack (not started here): the compose UI on http://localhost:3001 by default
// (docker compose up -d --build; LLM_PROVIDER=fake). Override with E2E_BASE_URL, e.g. http://localhost:5173 for npm run dev.
export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 10_000 },
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:3001',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
