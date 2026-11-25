const t = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const t0 = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 });
const kg = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const pct = new Intl.NumberFormat('en-GB', { style: 'percent', maximumFractionDigits: 1 });

/** Tonnes CO2e, one decimal ("1,234.5"). */
export function tco2e(v: number | null | undefined): string {
  return v === null || v === undefined ? '–' : t.format(v);
}

export function whole(v: number | null | undefined): string {
  return v === null || v === undefined ? '–' : t0.format(v);
}

export function kgco2e(v: number): string {
  return kg.format(v);
}

export function percent(v: number | null | undefined): string {
  return v === null || v === undefined ? '–' : pct.format(v);
}

export function money(v: number, currency: string): string {
  try {
    return new Intl.NumberFormat('en-GB', { style: 'currency', currency }).format(v);
  } catch {
    return `${t0.format(v)} ${currency}`;
  }
}

export const METHOD_LABELS: Record<string, string> = {
  supplier_specific: 'Supplier-specific',
  hybrid: 'Hybrid',
  average_data: 'Average-data',
  spend_based: 'Spend-based',
  estimated: 'Estimated',
};

export const STATUS_LABELS: Record<string, string> = {
  needs_review: 'Needs review',
  auto_accepted: 'Auto-accepted',
  reviewed: 'Reviewed',
  excluded: 'Excluded',
};
