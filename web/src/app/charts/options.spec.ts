import type { ChartTokens } from '../core/theme.service';
import { macc, orderedColumns, rankedBars, scopeComposition, trajectory } from './options';

const tokens: ChartTokens = {
  surface: '#ffffff',
  textPrimary: '#191919',
  textSecondary: '#666666',
  grid: '#e7e7e7',
  axis: '#c2c2c2',
  border: 'rgba(0,0,0,.1)',
  scope: ['#257de0', '#f47230', '#00b894'],
  seq: '#257de0',
};

type AnyOpt = any;

describe('chart options', () => {
  it('scope composition: one stacked series per scope, fixed colour order, surface gaps', () => {
    const opt = scopeComposition(
      [
        { label: 'Scope 1', value: 10 },
        { label: 'Scope 2', value: 5 },
        { label: 'Scope 3', value: 85 },
      ],
      tokens,
    ) as AnyOpt;
    expect(opt.series).toHaveLength(3);
    expect(opt.series.map((s: AnyOpt) => s.itemStyle.color)).toEqual(tokens.scope);
    expect(opt.series.every((s: AnyOpt) => s.stack === 'total')).toBe(true);
    expect(opt.series[0].itemStyle.borderColor).toBe(tokens.surface);
    // rounded only at the outer ends of the bar
    expect(opt.series[0].itemStyle.borderRadius).toEqual([4, 0, 0, 4]);
    expect(opt.series[2].itemStyle.borderRadius).toEqual([0, 4, 4, 0]);
    // tiny segments are not labelled inside the bar
    expect(opt.series[1].label.show).toBe(false);
  });

  it('ranked bars: single hue, largest drawn at the top, value labels on', () => {
    const opt = rankedBars(
      [
        { label: 'A', value: 1 },
        { label: 'B', value: 9 },
        { label: 'C', value: 4 },
      ],
      tokens,
    ) as AnyOpt;
    expect(opt.yAxis.data).toEqual(['A', 'C', 'B']); // ECharts draws categories bottom-up
    expect(opt.series[0].itemStyle.color).toBe(tokens.seq);
    expect(opt.series[0].label.show).toBe(true);
  });

  it('ordered columns keep the given order', () => {
    const opt = orderedColumns(
      [1, 2, 3].map((n) => ({ label: String(n), value: n })),
      tokens,
    ) as AnyOpt;
    expect(opt.xAxis.data).toEqual(['1', '2', '3']);
  });
});

describe('pathway charts', () => {
  it('trajectory: band is stacked P10 + (P90 - P10); target dashed; BAU neutral', () => {
    const opt = trajectory(
      {
        years: [2025, 2026],
        bau: [100, 102],
        pathway: [100, 80],
        p10: [100, 70],
        p90: [100, 90],
        target: [100, 95],
      },
      tokens,
    ) as AnyOpt;
    const byName = Object.fromEntries(opt.series.map((s: AnyOpt) => [s.name, s]));
    expect(byName['P10–P90'].data).toEqual([0, 20]);
    expect(byName['band-base'].stack).toBe(byName['P10–P90'].stack);
    expect(byName['Target'].lineStyle.type).toEqual([6, 4]);
    expect(byName['Business as usual'].lineStyle.color).toBe(tokens.textSecondary);
    expect(opt.yAxis.name).toBeUndefined(); // unit lives in the subtitle
  });

  it('macc: bars laid out cumulatively in the given order', () => {
    const opt = macc(
      [
        { rank: 1, name: 'A', abatement: 10, mac: -50 },
        { rank: 2, name: 'B', abatement: 30, mac: 120 },
      ],
      tokens,
      'GBP',
    ) as AnyOpt;
    expect(opt.series[0].data).toEqual([
      [0, 10, -50, 1, 'A', 10],
      [10, 40, 120, 2, 'B', 30],
    ]);
    expect(opt.xAxis.max).toBe(40);
    expect(opt.yAxis.name).toBe('GBP / tCO₂e');
  });
});
