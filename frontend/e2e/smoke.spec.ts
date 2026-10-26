import { expect, test } from '@playwright/test';

// Login (dev token) -> create an incident -> watch its investigation reach COMPLETED (fake LLM) -> open a citation.
test('login, create an incident, investigation completes', async ({ page }) => {
  // A tenant WITH synthetic evidence (logs, runbooks, ...), so the fake-LLM investigation has findings and citations.
  const tenant = process.env.E2E_TENANT ?? 'acme';
  const title = `E2E: checkout latency after deploy ${Date.now()}`;

  await page.goto('/');
  await page.getByLabel('User').fill('e2e-user');
  await page.getByLabel('Tenant').fill(tenant);
  await page.getByLabel('Role').selectOption('RESPONDER');
  await page.getByRole('button', { name: 'Sign in' }).click();

  await expect(page.getByRole('heading', { name: 'Incidents' })).toBeVisible();
  await page.getByRole('link', { name: 'New incident' }).click();

  await page.getByLabel(/Title/).fill(title);
  await page.getByLabel('Description').fill('p95 latency doubled and HikariPool timeouts in the logs');
  await page.getByLabel(/Severity/).selectOption('HIGH');
  await page.getByLabel(/Affected service/).fill('payment-service');
  await page.getByRole('button', { name: 'Create incident' }).click();

  await expect(page.getByRole('heading', { name: title })).toBeVisible();
  const panel = page.getByRole('region', { name: 'AI investigation' });
  await expect(panel.getByText('COMPLETED', { exact: true })).toBeVisible({ timeout: 90_000 });
  await expect(panel.getByRole('heading', { name: 'Root cause' })).toBeVisible();

  await panel.getByRole('button', { name: /^Evidence C\d+$/ }).first().click();
  await expect(page.getByRole('complementary')).toContainText('Source id');

  // The new incident is listed for this tenant.
  await page.getByRole('link', { name: '← Incidents' }).click();
  await expect(page.getByRole('link', { name: title })).toBeVisible();
});
