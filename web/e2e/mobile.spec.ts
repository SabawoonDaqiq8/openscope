import { expect, PAGES, test } from './fixtures';

for (const p of PAGES) {
  test(`fits a phone screen without horizontal scrolling: ${p.name}`, async ({ page }) => {
    await page.goto(p.path);
    await p.ready(page);
    const { layout, screen } = await page.evaluate(() => ({
      layout: window.innerWidth,
      screen: document.documentElement.clientWidth,
    }));
    const viewport = page.viewportSize()!.width;
    expect(layout, 'page wider than the screen (browser zoomed out)').toBe(viewport);
    expect(screen).toBeLessThanOrEqual(viewport);
    // navigation stays usable on phones
    await expect(
      page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Overview' }),
    ).toBeVisible();
  });
}
