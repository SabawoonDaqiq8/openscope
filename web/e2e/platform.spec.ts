import { axeViolations, expect, PAGES, test } from './fixtures';

test('public demo: deletes are blocked and security headers are sent', async ({ request }) => {
  const inventories = await (await request.get('/api/inventories')).json();
  const del = await request.delete(`/api/inventories/${inventories[0].id}`);
  expect(del.status()).toBe(403);

  const page = await request.get('/overview');
  const h = page.headers();
  expect(h['content-security-policy']).toContain("script-src 'self'");
  expect(h['x-frame-options']).toBe('DENY');
  expect(h['x-content-type-options']).toBe('nosniff');
});

test('public demo banner is shown', async ({ page }) => {
  await page.goto('/overview');
  await expect(page.getByRole('complementary', { name: 'Public demo notice' })).toBeVisible();
});

for (const scheme of ['light', 'dark'] as const) {
  for (const p of PAGES) {
    test(`accessibility (axe, ${scheme}): ${p.name}`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto(p.path);
      await p.ready(page);
      expect(await axeViolations(page)).toEqual([]);
    });
  }
}
