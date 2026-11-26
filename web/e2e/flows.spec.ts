import { expect, test } from './fixtures';

test.describe.configure({ mode: 'serial' });

test('overview shows the demo inventory with charts and the workflow strip', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/overview/);
  // tests that export inventories may have run before (e.g. on retry): pick the demo explicitly
  await page
    .getByRole('combobox', { name: 'Inventory' })
    .selectOption({ label: 'Demo: UK company 2025 (DESNZ factors)' });
  await expect(page).toHaveURL(/\/overview\/\d+/);
  await expect(page.locator('os-stat', { hasText: 'Total emissions' })).toContainText('650.0');
  await expect(page.locator('canvas').first()).toBeVisible();
  for (const step of ['Measure', 'Classify', 'Plan', 'Disclose']) {
    await expect(page.getByRole('list').getByText(step, { exact: true })).toBeVisible();
  }
  await expect(page.getByText('Scope 2 market-based fallback.')).toBeVisible();
  // chart/table toggle shows the accessible table view
  await page
    .locator('os-chart-card', { hasText: 'Emissions by scope' })
    .getByRole('button', { name: 'Table' })
    .click();
  await expect(page.getByRole('cell', { name: 'Scope 1', exact: true })).toBeVisible();
});

test('line explorer expands the audit trail of a calculation', async ({ page }) => {
  await page.goto('/overview');
  // tests that export inventories may have run before (e.g. on retry): pick the demo explicitly
  await page
    .getByRole('combobox', { name: 'Inventory' })
    .selectOption({ label: 'Demo: UK company 2025 (DESNZ factors)' });
  await expect(page).toHaveURL(/\/overview\/\d+/);
  await page.getByRole('link', { name: /Line explorer/ }).click();
  const toggle = page.getByRole('button', { name: /Audit trail for HQ boiler natural gas/ });
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByText(/CO2: 850,000 × 0\.18259 kg\/kWh/)).toBeVisible();
});

test('scope 3 review: override a line, see it in the audit log, export it', async ({ page }) => {
  await page.goto('/review');
  await expect(page.getByRole('heading', { name: 'Scope 3 review' })).toBeVisible();
  await page.getByLabel('Reviewer (for the audit log)').fill('E2E Reviewer');

  // the first line in the "Needs review" queue (idempotent: works on reruns as well)
  const first = page
    .locator('tbody tr')
    .filter({ has: page.getByRole('button', { name: 'Override' }) })
    .first();
  const lineId = (await first.locator('.text-xs.text-muted').first().innerText())
    .split(' · ')[0]
    .trim();
  // pin the row by its id: once the form opens, it no longer has an Override button
  const row = page.locator('tbody tr', { hasText: lineId });
  await row.getByRole('button', { name: 'Override' }).click();
  await row.getByLabel('Scope 3 category').selectOption('1');
  await row.getByLabel('Emission factor').fill('USEEIO-1.3-511210');
  await expect(row.getByRole('status')).toHaveText('Software Publishers (NAICS 511210)');
  await row.getByLabel('Note').fill('E2E override');
  await row.getByRole('button', { name: 'Save' }).click();

  const audit = page.locator('section', { hasText: 'Audit log' });
  const entry = audit.locator('tr', { hasText: lineId }).first();
  await expect(entry).toContainText('E2E Reviewer');
  await expect(entry).toContainText('cat 1 · USEEIO-1.3-511210');
  await expect(page.getByRole('tab', { name: /Reviewed/ })).not.toContainText(/Reviewed\s*0\b/);

  await page.getByRole('button', { name: /Export accepted/ }).click();
  await expect(page).toHaveURL(/\/overview\/\d+/);
  await expect(page.getByRole('combobox', { name: 'Inventory' })).toContainText('(spend-based)');
  // all exported lines use official EPA factors: no illustrative-factor warning
  await expect(page.getByText('Illustrative factors in use.')).toHaveCount(0);
});

test('review requires a reviewer name before recording a decision', async ({ page }) => {
  await page.goto('/review');
  await page.getByLabel('Reviewer (for the audit log)').fill('');
  await page.locator('tbody tr').first().getByRole('button', { name: 'Exclude' }).click();
  await expect(page.getByText(/Enter your name as reviewer first/)).toBeVisible();
});

test('pathways: demo scenario, Scope 3 shortfall, edit a lever and re-run', async ({ page }) => {
  await page.goto('/pathways');
  // earlier tests export new inventories; pick the demo baseline explicitly
  await page
    .getByLabel('Baseline inventory')
    .selectOption({ label: 'Demo: UK company 2025 (DESNZ factors)' });
  await expect(page).toHaveURL(/\/pathways\/\d+/);
  await page.getByRole('button', { name: 'Load demo scenario' }).click();
  const scope3 = page.locator('.card', { hasText: 'Scope 3 target' });
  await expect(scope3).toContainText('Short by 46.5 t');
  await expect(page.locator('.card', { hasText: 'Scope 1+2 target' })).toContainText('On track');
  await expect(
    page.getByRole('cell', { name: 'Travel policy: rail over short-haul, fewer long-haul trips' }),
  ).toBeVisible();

  const freight = page.locator('details', { hasText: 'Engage hauliers on low-carbon freight' });
  await freight.locator('summary').click();
  await freight.getByLabel('Cut high %').fill('80');
  await freight.getByLabel('Cut high %').dispatchEvent('change');
  await freight.getByLabel('Cut likely %').fill('60');
  await freight.getByLabel('Cut likely %').dispatchEvent('change');
  await page.getByRole('button', { name: 'Run simulation' }).click();
  await expect(scope3).toContainText('Short by 20.7 t');
});

test('disclosure: ESRS table with comparatives, download and IFRS S2 toggle', async ({ page }) => {
  await page.goto('/disclosure');
  await page
    .getByLabel('Reporting year inventory')
    .selectOption({ label: 'Demo: UK company 2025 (DESNZ factors)' });
  await page
    .getByLabel('Prior year (N-1)')
    .selectOption({ label: 'Demo: UK company 2024 (DESNZ factors)' });
  const s2m = page.locator('tr', { hasText: 'Gross market-based Scope 2 GHG emissions' });
  await expect(s2m).toContainText('159.3');
  await expect(s2m).toContainText('44.3');
  await expect(s2m).toContainText('-72.2%');
  await expect(page.getByText('No blockers')).toBeVisible();

  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('link', { name: 'Markdown' }).click(),
  ]);
  expect(download.suggestedFilename()).toBe('openscope-esrs-e1-2025.md');

  // E1-5 energy section and biogenic CO2 (outside the scopes)
  await expect(
    page.getByRole('columnheader', { name: /E1-5 · Energy consumption and mix/ }),
  ).toBeVisible();
  await expect(
    page.locator('tr', { has: page.getByRole('cell', { name: /^Total energy consumption/ }) }),
  ).toContainText('2,033.3');
  await expect(page.locator('tr', { hasText: 'Biogenic CO2 emissions' })).toContainText('103.7');
  const fossil = page.locator('tr', {
    has: page.getByRole('cell', { name: /^Total fossil energy consumption/ }),
  });
  await expect(page.getByText(/250 MWh of purchased electricity is not covered/)).toBeVisible();
  for (const [label, value] of [
    ['Fossil', '40'],
    ['Nuclear', '15'],
    ['Renewable', '45'],
  ]) {
    await page.getByLabel(label, { exact: true }).fill(value);
    await page.getByLabel(label, { exact: true }).dispatchEvent('change');
  }
  await expect(fossil).toContainText('1,283.3'); // 1,183.3 MWh fuels + 40 % of 250 MWh
  await expect(page.getByText(/250 MWh of purchased electricity is not covered/)).toHaveCount(0);

  await page.getByRole('button', { name: 'IFRS S2' }).click();
  await expect(
    page.getByRole('heading', { name: 'IFRS S2 §29(a) Greenhouse gas emissions' }),
  ).toBeVisible();
});

test('factor browser searches official datasets', async ({ page }) => {
  await page.goto('/factors');
  await page.getByLabel('Search factors').fill('electricity uk');
  await page.getByRole('button', { name: 'Search' }).click();
  await expect(page.getByText('DESNZ-2025-7_400_4000_5')).toBeVisible();
});
