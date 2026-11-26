import AxeBuilder from '@axe-core/playwright';
import { expect, test as base, type Page } from '@playwright/test';

/**
 * Every test fails if the page logs a console error, throws, or hits a Content-Security-Policy
 * violation, so runtime regressions surface even in tests that check something else.
 */
export const test = base.extend<{ errors: string[] }>({
  errors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on('console', (m) => {
        if (m.type() === 'error') errors.push(m.text());
      });
      page.on('pageerror', (e) => errors.push(e.message));
      await use(errors);
      expect(errors, 'console errors / CSP violations').toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

/** Run axe-core (WCAG 2.1 AA + best practice) and return a readable list of violations. */
export async function axeViolations(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'best-practice'])
    .analyze();
  return results.violations.map(
    (v) =>
      `${v.id} (${v.impact}): ${v.help} → ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`,
  );
}

export const PAGES: { name: string; path: string; ready: (p: Page) => Promise<unknown> }[] = [
  { name: 'overview', path: '/overview', ready: (p) => p.locator('canvas').first().waitFor() },
  {
    name: 'review',
    path: '/review',
    ready: (p) => p.locator('table.data tbody tr').first().waitFor(),
  },
  {
    name: 'pathways',
    path: '/pathways',
    ready: async (p) => {
      await p.getByRole('button', { name: 'Load demo scenario' }).click();
      await p.locator('canvas').first().waitFor();
    },
  },
  {
    name: 'disclosure',
    path: '/disclosure',
    ready: (p) => p.locator('table.data tbody tr').first().waitFor(),
  },
  {
    name: 'factors',
    path: '/factors',
    ready: (p) => p.locator('table.data tbody tr').first().waitFor(),
  },
  { name: 'upload', path: '/upload', ready: (p) => p.locator('form').first().waitFor() },
];
