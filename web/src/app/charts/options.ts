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

export interface TrajectoryInput {
  years: number[];
  bau: number[];
  pathway: number[];
  p10: number[];
  p90: number[];
  target: number[];
}

/**
 * Emissions trajectory: BAU (neutral reference), pathway (slot 1, with P10–P90 band) and the
 * target (dashed primary ink). One y-axis; lines labelled at their end; crosshair tooltip.
 */
export function trajectory(d: TrajectoryInput, t: ChartTokens): EChartsCoreOption {
  const years = d.years.map(String);
  const band = d.p90.map((v, i) => v - d.p10[i]);
  const endLabel = (name: string, color: string) => ({
    show: true,
    formatter: () => name,
    color,
    fontSize: 12,
    distance: 6,
  });
  return {
    textStyle: font,
    animationDuration: 300,
    tooltip: {
      ...tooltip(t),
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: t.axis } },
      formatter: (ps: { axisValue: string; dataIndex: number }[]) => {
        const i = ps[0].dataIndex;
        return [
          `<b>${ps[0].axisValue}</b>`,
          `Pathway ${tco2e(d.pathway[i])} (P10–P90 ${tco2e(d.p10[i])}–${tco2e(d.p90[i])})`,
          `Target ${tco2e(d.target[i])}`,
          `Business as usual ${tco2e(d.bau[i])}`,
        ].join('<br/>');
      },
    },
    legend: {
      top: 0,
      left: 0,
      data: ['Pathway', 'Target', 'Business as usual'],
      textStyle: { color: t.textSecondary, fontSize: 12 },
      itemWidth: 16,
      itemHeight: 2,
    },
    grid: { left: 8, right: 110, top: 36, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: years,
      boundaryGap: false,
      axisLine: { lineStyle: { color: t.axis } },
      axisTick: { show: false },
      axisLabel: { color: t.textSecondary, fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: t.textSecondary, fontSize: 11 },
      splitLine: { lineStyle: { color: t.grid } },
    },
    series: [
      {
        name: 'band-base',
        type: 'line',
        data: d.p10,
        stack: 'band',
        symbol: 'none',
        lineStyle: { opacity: 0 },
        silent: true,
        tooltip: { show: false },
      },
      {
        name: 'P10–P90',
        type: 'line',
        data: band,
        stack: 'band',
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { color: t.seq, opacity: 0.16 },
        silent: true,
      },
      {
        name: 'Business as usual',
        type: 'line',
        data: d.bau,
        symbol: 'none',
        lineStyle: { color: t.textSecondary, width: 2 },
        itemStyle: { color: t.textSecondary },
        endLabel: endLabel('Business as usual', t.textSecondary),
      },
      {
        name: 'Target',
        type: 'line',
        data: d.target,
        symbol: 'none',
        lineStyle: { color: t.textPrimary, width: 2, type: [6, 4] },
        itemStyle: { color: t.textPrimary },
        endLabel: endLabel('Target', t.textPrimary),
      },
      {
        name: 'Pathway',
        type: 'line',
        data: d.pathway,
        symbol: 'circle',
        symbolSize: 8,
        showSymbol: false,
        lineStyle: { color: t.seq, width: 2 },
        itemStyle: { color: t.seq, borderColor: t.surface, borderWidth: 2 },
        endLabel: endLabel('Pathway', t.textPrimary),
      },
    ],
  };
}

export interface MaccBar {
  rank: number;
  name: string;
  abatement: number; // tCO2e per year (bar width)
  mac: number; // currency per tCO2e (bar height)
}

/**
 * Marginal abatement cost curve: variable-width bars in merit order. Width = annual
 * abatement, height = cost per tonne; bars below zero save money. Single hue, rank labels.
 */
export function macc(bars: MaccBar[], t: ChartTokens, currency: string): EChartsCoreOption {
  let x = 0;
  const data = bars.map((b) => {
    const row = [x, x + b.abatement, b.mac, b.rank, b.name, b.abatement];
    x += b.abatement;
    return row;
  });
  const total = x || 1;
  return {
    textStyle: font,
    animationDuration: 300,
    tooltip: {
      ...tooltip(t),
      formatter: (p: { value: (number | string)[] }) => {
        const [, , mac, rank, name, ab] = p.value;
        return `${rank}. ${name}<br/><b>${Math.round(Number(mac)).toLocaleString()}</b> ${currency}/tCO₂e · ${tco2e(Number(ab))} tCO₂e/yr`;
      },
    },
    grid: { left: 8, right: 16, top: 32, bottom: 36, containLabel: true },
    xAxis: {
      type: 'value',
      max: Math.ceil(total),
      name: 'Abatement, tCO₂e per year (cumulative)',
      nameLocation: 'middle',
      nameGap: 26,
      nameTextStyle: { color: t.textSecondary, fontSize: 11 },
      axisLine: { lineStyle: { color: t.axis } },
      axisLabel: {
        color: t.textSecondary,
        fontSize: 11,
        showMaxLabel: false,
        formatter: (v: number) => Math.round(v).toLocaleString('en-GB'),
      },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      name: `${currency} / tCO₂e`,
      nameTextStyle: { color: t.textSecondary, fontSize: 11, align: 'left' },
      axisLabel: {
        color: t.textSecondary,
        fontSize: 11,
        formatter: (v: number) => Math.round(v).toLocaleString('en-GB'),
      },
      splitLine: { lineStyle: { color: t.grid } },
      axisLine: { show: true, onZero: true, lineStyle: { color: t.axis } },
    },
    series: [
      {
        type: 'custom',
        data,
        encode: { x: [0, 1], y: 2 },
        renderItem: (
          _params: unknown,
          api: {
            value: (i: number) => number;
            coord: (v: number[]) => number[];
          },
        ) => {
          const [x0, y0] = api.coord([api.value(0), 0]);
          const [x1, y1] = api.coord([api.value(1), api.value(2)]);
          const top = Math.min(y0, y1);
          const height = Math.max(Math.abs(y1 - y0), 1);
          const negative = api.value(2) < 0;
          return {
            type: 'group',
            children: [
              {
                type: 'rect',
                shape: {
                  x: x0 + 1, // 2px surface gap between neighbours
                  y: top,
                  width: Math.max(x1 - x0 - 2, 1),
                  height,
                  r: negative ? [0, 0, 4, 4] : [4, 4, 0, 0],
                },
                style: { fill: t.seq },
              },
              {
                type: 'text',
                style: {
                  text: String(api.value(3)),
                  x: (x0 + x1) / 2,
                  y: negative ? top + height + 4 : top - 4,
                  align: 'center',
                  verticalAlign: negative ? 'top' : 'bottom',
                  fill: t.textPrimary,
                  fontSize: 12,
                  fontWeight: 600,
                },
              },
            ],
          };
        },
      },
    ],
  };
}
