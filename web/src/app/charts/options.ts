import type { EChartsCoreOption } from 'echarts/core';

import type { ChartTokens } from '../core/theme.service';
import { tco2e } from '../core/format';

/**
 * ECharts option builders. Mark specs (from the data-viz guidance):
 * thin bars, 4px rounded data-end, 2px surface gap between fills, hairline grid,
 * recessive axes, text in text tokens (never the series colour), hover tooltip on
 * every mark, direct value labels (required: two light-mode scope colours are < 3:1).
 */

function tooltip(t: ChartTokens) {
  return {
    trigger: 'item' as const,
    backgroundColor: t.surface,
    borderColor: t.border,
    borderWidth: 1,
    padding: [6, 10],
    textStyle: { color: t.textPrimary, fontSize: 12 },
    extraCssText: 'box-shadow: 0 4px 16px rgba(0,0,0,.12); border-radius: 8px;',
  };
}

const font = { fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif' };

export interface ScopePart {
  label: string;
  value: number;
}

/** Part-to-whole: one horizontal stacked bar, Scope 1 / 2 / 3, legend + direct labels. */
export function scopeComposition(parts: ScopePart[], t: ChartTokens): EChartsCoreOption {
  const total = parts.reduce((s, p) => s + p.value, 0) || 1;
  const last = parts.length - 1;
  return {
    textStyle: font,
    animationDuration: 300,
    tooltip: {
      ...tooltip(t),
      formatter: (p: { seriesName: string; value: number; marker: string }) =>
        `${p.marker}${p.seriesName}<br/><b>${tco2e(p.value)}</b> tCO₂e · ${Math.round(
          (p.value / total) * 100,
        )}%`,
    },
    legend: {
      top: 0,
      left: 0,
      icon: 'roundRect',
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: t.textSecondary, fontSize: 12 },
    },
    grid: { left: 0, right: 0, top: 32, bottom: 0, containLabel: false },
    xAxis: { type: 'value', max: total, show: false },
    yAxis: { type: 'category', data: ['Total'], show: false },
    series: parts.map((p, i) => ({
      name: p.label,
      type: 'bar',
      stack: 'total',
      barWidth: 36,
      data: [p.value],
      itemStyle: {
        color: t.scope[i],
        borderColor: t.surface,
        borderWidth: 1, // 1px each side = 2px surface gap between segments
        borderRadius: i === 0 ? [4, 0, 0, 4] : i === last ? [0, 4, 4, 0] : 0,
      },
      label: {
        show: p.value / total >= 0.08,
        position: 'inside',
        color: '#ffffff',
        fontSize: 12,
        fontWeight: 600,
        formatter: () => `${Math.round((p.value / total) * 100)}%`,
      },
      emphasis: { focus: 'series' },
    })),
  };
}

export interface BarDatum {
  label: string;
  value: number;
}

/** Ranked magnitude: single-hue horizontal bars, largest first, value at the bar end. */
export function rankedBars(
  data: BarDatum[],
  t: ChartTokens,
  opts: { color?: string; unit?: string } = {},
): EChartsCoreOption {
  const sorted = [...data].sort((a, b) => a.value - b.value); // ECharts draws bottom-up
  const unit = opts.unit ?? 'tCO₂e';
  return {
    textStyle: font,
    animationDuration: 300,
    tooltip: {
      ...tooltip(t),
      formatter: (p: { name: string; value: number }) =>
        `${p.name}<br/><b>${tco2e(p.value)}</b> ${unit}`,
    },
    grid: { left: 8, right: 64, top: 4, bottom: 4, containLabel: true },
    xAxis: {
      type: 'value',
      axisLabel: { show: false },
      splitLine: { lineStyle: { color: t.grid, width: 1 } },
    },
    yAxis: {
      type: 'category',
      data: sorted.map((d) => d.label),
      axisLine: { lineStyle: { color: t.axis } },
      axisTick: { show: false },
      axisLabel: { color: t.textSecondary, fontSize: 12, width: 190, overflow: 'truncate' },
    },
    series: [
      {
        type: 'bar',
        data: sorted.map((d) => d.value),
        barMaxWidth: 18,
        barCategoryGap: '30%',
        itemStyle: { color: opts.color ?? t.seq, borderRadius: [0, 4, 4, 0] },
        label: {
          show: true,
          position: 'right',
          color: t.textPrimary,
          fontSize: 12,
          formatter: (p: { value: number }) => tco2e(p.value),
        },
        emphasis: { itemStyle: { opacity: 0.85 } },
      },
    ],
  };
}

/** Ordered categories (data-quality score 1-5): vertical single-hue bars. */
export function orderedColumns(
  data: BarDatum[],
  t: ChartTokens,
  opts: { color?: string; xTitle?: string } = {},
): EChartsCoreOption {
  return {
    textStyle: font,
    animationDuration: 300,
    tooltip: {
      ...tooltip(t),
      formatter: (p: { name: string; value: number }) =>
        `Score ${p.name}<br/><b>${tco2e(p.value)}</b> tCO₂e`,
    },
    grid: { left: 8, right: 8, top: 24, bottom: 28, containLabel: true },
    xAxis: {
      type: 'category',
      data: data.map((d) => d.label),
      name: opts.xTitle,
      nameLocation: 'middle',
      nameGap: 28,
      nameTextStyle: { color: t.textSecondary, fontSize: 12 },
      axisLine: { lineStyle: { color: t.axis } },
      axisTick: { show: false },
      axisLabel: { color: t.textSecondary, fontSize: 12 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: t.textSecondary, fontSize: 11 },
      splitLine: { lineStyle: { color: t.grid } },
    },
    series: [
      {
        type: 'bar',
        data: data.map((d) => d.value),
        barMaxWidth: 28,
        itemStyle: { color: opts.color ?? t.seq, borderRadius: [4, 4, 0, 0] },
        label: {
          show: true,
          position: 'top',
          color: t.textPrimary,
          fontSize: 12,
          formatter: (p: { value: number }) => (p.value > 0 ? tco2e(p.value) : ''),
        },
      },
    ],
  };
}
