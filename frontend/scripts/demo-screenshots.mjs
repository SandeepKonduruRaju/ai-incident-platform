// READ-ONLY screenshots of tenant "demo" for the README (run after `python -m app.seed_demo`; never creates anything).
//
//   cd frontend
//   node scripts/demo-screenshots.mjs                      # UI at http://localhost:3001 (compose)
//   $env:UI_URL = "http://localhost:5173"; node scripts/demo-screenshots.mjs
//
// Pages: the incident list, the confident investigation with a citation selected, the abstaining investigation and the
// (empty) report form, at 1440 px light and dark and 390 px light, into docs/screenshots/.
// Safety: list and detail are viewed as a VIEWER (that role cannot create, retry or change anything); only the
// report-form page signs in as a RESPONDER, and the form is never submitted.
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const BASE = (process.env.UI_URL ?? 'http://localhost:3001').replace(/\/$/, '');
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../docs/screenshots');
const CONFIDENT = 'Payment requests failing after configuration deploy';
const ABSTAINING = 'Checkout feels slow for some customers';
const VARIANTS = [
  { name: '1440-light', viewport: { width: 1440, height: 900 }, colorScheme: 'light' },
  { name: '1440-dark', viewport: { width: 1440, height: 900 }, colorScheme: 'dark' },
  { name: '390-light', viewport: { width: 390, height: 844 }, colorScheme: 'light', isMobile: true, hasTouch: true },
];
const INVESTIGATION_TIMEOUT_MS = 180_000; // a real-LLM investigation may still be running right after the seed

async function signIn(page, role) {
  await page.goto(`${BASE}/login`);
  await page.getByLabel('User').fill('demo-screenshots');
  await page.getByLabel('Tenant').fill('demo');
  await page.getByLabel('Role').selectOption(role);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.getByRole('heading', { name: 'Incidents' }).waitFor();
  await page.evaluate(() => document.fonts.ready);
}

async function openIncident(page, title) {
  await page.getByRole('link', { name: title, exact: true }).click(); // client-side: the session stays in memory
  const report = page.getByRole('region', { name: 'AI investigation' });
  await report.getByText('Completed', { exact: true }).waitFor({ timeout: INVESTIGATION_TIMEOUT_MS });
  return report;
}

async function backToList(page) {
  await page.getByRole('link', { name: 'Incidents', exact: true }).click();
  await page.getByRole('list', { name: 'Incidents' }).waitFor();
}

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
try {
  for (const { name, ...options } of VARIANTS) {
    const context = await browser.newContext(options);
    const page = await context.newPage();
    const shot = async (label, fullPage = false) => {
      if (fullPage) await page.evaluate(() => window.scrollTo(0, 0));
      const file = path.join(OUT, `${label}-${name}.png`);
      await page.screenshot({ path: file, fullPage });
      console.log(file);
    };

    await signIn(page, 'VIEWER');
    await page.getByRole('list', { name: 'Incidents' }).waitFor();
    await shot('list');

    const report = await openIncident(page, CONFIDENT);
    const mark = report.getByRole('button', { name: /^Evidence \d+$/ }).first();
    await mark.scrollIntoViewIfNeeded();
    await mark.click(); // selecting is read-only: it highlights, nothing is sent
    if (options.isMobile) await page.getByRole('dialog').waitFor();
    await page.waitForTimeout(400); // scroll / sheet animation
    await shot('investigation-confident');
    if (options.isMobile) await page.keyboard.press('Escape');

    await backToList(page);
    await openIncident(page, ABSTAINING);
    await shot('investigation-abstained', true);

    // The report form needs a RESPONDER; it is only displayed, never submitted.
    await page.getByRole('button', { name: 'Sign out' }).click();
    await signIn(page, 'RESPONDER');
    await page.getByRole('link', { name: 'Report an incident' }).first().click();
    await page.getByRole('heading', { name: 'Report an incident' }).waitFor();
    await shot('report-form', true);

    await context.close();
  }
} finally {
  await browser.close();
}
