import { expect, test } from '@playwright/test';

// Login (dev token) -> report an incident -> watch its investigation reach Completed (fake LLM) -> select a citation.
test('login, report an incident, investigation completes', async ({ page }) => {
  // A tenant WITH synthetic evidence (logs, runbooks, ...), so the fake-LLM investigation has findings and citations.
  const tenant = process.env.E2E_TENANT ?? 'acme';
  const title = `E2E: checkout latency after deploy ${Date.now()}`;

  await page.goto('/');
  await page.getByLabel('User').fill('e2e-user');
  await page.getByLabel('Tenant').fill(tenant);
  await page.getByLabel('Role').selectOption('RESPONDER');
  await page.getByRole('button', { name: 'Sign in' }).click();

  await expect(page.getByRole('heading', { name: 'Incidents' })).toBeVisible();
  await page.getByRole('link', { name: 'Report an incident' }).click();

  await page.getByLabel('Title').fill(title);
  await page.getByLabel(/Description/).fill('p95 latency doubled and HikariPool timeouts in the logs');
  await page.getByLabel('Severity').selectOption('HIGH');
  await page.getByLabel('Affected service').fill('payment-service');
  await page.getByRole('button', { name: 'Report incident' }).click();

  await expect(page.getByRole('heading', { name: title })).toBeVisible();
  const panel = page.getByRole('region', { name: 'AI investigation' });
  await expect(panel.getByText('Completed', { exact: true })).toBeVisible({ timeout: 90_000 });
  await expect(panel.getByRole('heading', { name: 'Root cause' })).toBeVisible();

  // Selecting a mark highlights it and exactly one piece of evidence in the rail.
  const mark = panel.getByRole('button', { name: /^Evidence \d+$/ }).first();
  await mark.click();
  await expect(mark).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('complementary', { name: 'Evidence' }).locator('[aria-current="true"]')).toHaveCount(1);

  // The new incident is listed for this tenant.
  await page.getByRole('link', { name: 'Incidents', exact: true }).click();
  await expect(page.getByRole('link', { name: title })).toBeVisible();
});
