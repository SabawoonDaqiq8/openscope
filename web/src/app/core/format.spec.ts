import { money, percent, tco2e } from './format';

describe('format', () => {
  it('formats tonnes with one decimal and thousands separators', () => {
    expect(tco2e(1234.56)).toBe('1,234.6');
    expect(tco2e(0)).toBe('0.0');
    expect(tco2e(null)).toBe('–');
  });

  it('formats percentages', () => {
    expect(percent(0.4167)).toBe('41.7%');
  });

  it('falls back gracefully for unknown currency codes', () => {
    expect(money(1000, 'USD')).toContain('1,000');
    expect(money(1000, 'XXXX')).toBe('1,000 XXXX');
  });
});
