import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import {
  ApiService,
  DisclosureOut,
  DisclosureQuery,
  InventorySummary,
  errorMessage,
} from '../api/api.service';
import { EmptyState, Notice } from '../shared/ui';

type Framework = 'esrs' | 'issb';
type GridKey = 'grid_fossil' | 'grid_nuclear' | 'grid_renewable';

const n1 = new Intl.NumberFormat('en-GB', { minimumFractionDigits: 1, maximumFractionDigits: 1 });

@Component({
  selector: 'os-disclosure',
  imports: [RouterLink, Notice, EmptyState],
  template: `
    @if (loaded() && inventories().length === 0) {
      <os-empty title="Nothing to disclose yet">
        Disclosure tables are built from calculated inventories. Load the demo or upload activity
        data first.
        <ng-container actions>
          <a class="btn btn-primary" routerLink="/overview">Go to overview</a>
        </ng-container>
      </os-empty>
    } @else {
      <div class="flex flex-wrap items-end justify-between gap-3 mb-4">
        <div>
          <h1 class="text-xl font-semibold">Climate disclosure</h1>
          <p class="text-sm text-muted">
            GHG emissions tables for ESRS E1-6 and IFRS S2 §29(a), with readiness checks.
          </p>
        </div>
        <div
          class="flex rounded-lg border border-line overflow-hidden text-sm"
          role="group"
          aria-label="Framework"
        >
          @for (f of frameworks; track f.value) {
            <button
              type="button"
              class="px-3 py-1.5"
              [class.bg-accent]="framework() === f.value"
              [class.text-accent-ink]="framework() === f.value"
              [attr.aria-pressed]="framework() === f.value"
              (click)="framework.set(f.value)"
            >
              {{ f.label }}
            </button>
          }
        </div>
      </div>

      <section
        class="card p-4 mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-6 text-sm"
        aria-label="Inputs"
      >
        <label class="lg:col-span-2"
          >Reporting year inventory
          <select
            class="input w-full mt-1"
            [value]="inventoryId()"
            (change)="selectInventory($event)"
          >
            @for (i of inventories(); track i.id) {
              <option [value]="i.id">
                {{ i.name }}
              </option>
            }
          </select>
        </label>
        <label
          >Prior year (N-1)
          <select class="input w-full mt-1" (change)="priorId.set(toId($event))">
            <option value="">None</option>
            @for (i of others(); track i.id) {
              <option [value]="i.id" [selected]="priorId() === i.id">{{ i.name }}</option>
            }
          </select>
        </label>
        <label
          >Base year
          <select class="input w-full mt-1" (change)="baseId.set(toId($event))">
            <option value="">None</option>
            @for (i of others(); track i.id) {
              <option [value]="i.id" [selected]="baseId() === i.id">{{ i.name }}</option>
            }
          </select>
        </label>
        @if (framework() === 'esrs') {
          <label
            >Net revenue
            <span class="flex gap-1 mt-1">
              <input
                class="input w-full"
                type="number"
                min="0"
                placeholder="e.g. 12500000"
                [value]="netRevenue() ?? ''"
                (change)="netRevenue.set(toNum($event))"
              />
              <input
                class="input w-16"
                maxlength="3"
                aria-label="Currency"
                [value]="currency()"
                (change)="currency.set($any($event.target).value.toUpperCase())"
              />
            </span>
          </label>
          <label
            >Scope 1 under EU ETS (%)
            <input
              class="input w-full mt-1"
              type="number"
              min="0"
              max="100"
              placeholder="0"
              [value]="etsShare() ?? ''"
              (change)="etsShare.set(toNum($event))"
            />
          </label>
          <fieldset class="sm:col-span-2 lg:col-span-6">
            <legend class="text-sm">
              Mix of purchased electricity not covered by renewable certificates (%, for E1-5)
            </legend>
            <div class="mt-1 grid grid-cols-3 gap-2 max-w-md">
              @for (g of gridFields; track g.key) {
                <label class="text-xs text-muted"
                  >{{ g.label }}
                  <input
                    class="input w-full mt-0.5"
                    type="number"
                    min="0"
                    max="100"
                    [placeholder]="g.placeholder"
                    [value]="grid()[g.key] ?? ''"
                    (change)="setGrid(g.key, toNum($event))"
                  />
                </label>
              }
            </div>
          </fieldset>
        }
      </section>

      @if (error()) {
        <div class="mb-4">
          <os-notice kind="critical" title="Could not build the disclosure.">{{
            error()
          }}</os-notice>
        </div>
      }

      @if (d(); as d) {
        <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] items-start">
          <section class="card overflow-x-auto">
            <header class="flex flex-wrap items-center justify-between gap-2 px-4 pt-4 pb-2">
              <h2 class="font-semibold">{{ d.title }}</h2>
              <div class="flex gap-1.5">
                @for (f of formats; track f.value) {
                  <a class="btn text-xs" [href]="exportUrl(f.value)" [attr.download]="''">{{
                    f.label
                  }}</a>
                }
              </div>
            </header>
            <table class="data">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Reference</th>
                  <th class="text-right">{{ d.base_year ?? 'Base year' }}</th>
                  <th class="text-right">{{ d.prior_year ?? 'N-1' }}</th>
                  <th class="text-right">{{ d.reporting_year ?? 'N' }}</th>
                  <th class="text-right">% N / N-1</th>
                  <th class="text-right">% N / base</th>
                </tr>
              </thead>
              <tbody>
                @for (r of d.rows; track r.key; let i = $index) {
                  @if (i === 0 || d.rows[i - 1].section !== r.section) {
                    <tr>
                      <th colspan="7" scope="colgroup" class="bg-surface-2 text-ink">
                        {{ sectionTitle(r.section) }}
                      </th>
                    </tr>
                  }
                  <tr [class.font-semibold]="isTotal(r.key)">
                    <td [style.padding-left.rem]="0.75 + r.indent * 1.25">
                      {{ r.label }}
                      <div class="text-xs text-muted font-normal">{{ r.unit }}</div>
                    </td>
                    <td class="text-xs text-muted whitespace-nowrap font-normal">
                      {{ r.reference }}
                    </td>
                    <td class="text-right num">{{ num(r.base) }}</td>
                    <td class="text-right num">{{ num(r.prior) }}</td>
                    <td class="text-right num">{{ num(r.current) }}</td>
                    <td class="text-right num">{{ change(r.change_vs_prior) }}</td>
                    <td class="text-right num">{{ change(r.change_vs_base) }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </section>

          <div class="space-y-4">
            <section class="card p-4" aria-label="Readiness">
              <div class="flex items-center gap-2 mb-3">
                <span
                  class="text-lg"
                  [class]="d.ready ? 'text-good' : 'text-crit'"
                  aria-hidden="true"
                  >{{ d.ready ? '✓' : '✕' }}</span
                >
                <h2 class="font-semibold" [class]="d.ready ? 'text-good' : 'text-crit'">
                  {{
                    d.ready
                      ? 'No blockers'
                      : blockers() + ' blocker' + (blockers() === 1 ? '' : 's')
                  }}
                </h2>
              </div>
              <ul class="space-y-2.5 text-sm">
                @for (c of d.checks; track c.code) {
                  <li class="flex gap-2">
                    <span
                      class="font-semibold shrink-0"
                      [class]="tone(c.level)"
                      aria-hidden="true"
                      >{{ icon(c.level) }}</span
                    >
                    <span>
                      <span class="font-semibold" [class]="tone(c.level)"
                        >{{ levelLabel(c.level) }}.</span
                      >
                      {{ c.message }}
                    </span>
                  </li>
                }
              </ul>
            </section>
            <section class="card p-4 text-sm" aria-label="Basis of preparation">
              <h2 class="font-semibold mb-2">Basis of preparation</h2>
              <ul class="list-disc pl-5 space-y-1.5 text-muted">
                @for (p of d.basis; track $index) {
                  <li>{{ p }}</li>
                }
              </ul>
            </section>
            <p class="text-xs text-muted">
              References are to ESRS Set 1 (Delegated Regulation (EU) 2023/2772) and IFRS S2. The EU
              Omnibus simplification may change ESRS requirements; check the version that applies to
              your reporting period.
            </p>
          </div>
        </div>
      } @else if (!error()) {
        <p class="text-muted">Loading…</p>
      }
    }
  `,
})
export class DisclosurePage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  readonly id = input<string>();

  protected readonly frameworks: { value: Framework; label: string }[] = [
    { value: 'esrs', label: 'ESRS E1' },
    { value: 'issb', label: 'IFRS S2' },
  ];
  protected readonly formats: { value: 'csv' | 'md' | 'json'; label: string }[] = [
    { value: 'csv', label: 'CSV' },
    { value: 'md', label: 'Markdown' },
    { value: 'json', label: 'JSON' },
  ];

  protected readonly inventories = signal<InventorySummary[]>([]);
  protected readonly inventoryId = signal<number | null>(null);
  protected readonly loaded = signal(false);
  protected readonly error = signal('');
  protected readonly d = signal<DisclosureOut | null>(null);

  protected readonly framework = signal<Framework>('esrs');
  protected readonly priorId = signal<number | null>(null);
  protected readonly baseId = signal<number | null>(null);
  protected readonly netRevenue = signal<number | null>(null);
  protected readonly currency = signal('EUR');
  protected readonly etsShare = signal<number | null>(null);
  protected readonly grid = signal<Record<GridKey, number | null>>({
    grid_fossil: null,
    grid_nuclear: null,
    grid_renewable: null,
  });
  protected readonly gridFields: { key: GridKey; label: string; placeholder: string }[] = [
    { key: 'grid_fossil', label: 'Fossil', placeholder: 'e.g. 40' },
    { key: 'grid_nuclear', label: 'Nuclear', placeholder: 'e.g. 15' },
    { key: 'grid_renewable', label: 'Renewable', placeholder: 'e.g. 45' },
  ];

  protected readonly others = computed(() =>
    this.inventories().filter((i) => i.id !== this.inventoryId()),
  );
  protected readonly query = computed<DisclosureQuery>(() => ({
    framework: this.framework(),
    prior_id: this.priorId(),
    base_id: this.baseId(),
    net_revenue: this.framework() === 'esrs' ? this.netRevenue() : null,
    revenue_currency: this.framework() === 'esrs' && this.netRevenue() ? this.currency() : null,
    ets_share: this.framework() === 'esrs' ? this.etsShare() : null,
    ...(this.framework() === 'esrs' && Object.values(this.grid()).every((v) => v !== null)
      ? this.grid()
      : {}),
  }));
  protected readonly blockers = computed(
    () => this.d()?.checks.filter((c) => c.level === 'blocker').length ?? 0,
  );

  constructor() {
    effect(() => this.loadInventories(this.id()));
    effect(() => {
      const id = this.inventoryId();
      const q = this.query();
      if (id === null) return;
      this.api.disclosure(id, q).subscribe({
        next: (d) => {
          this.d.set(d);
          this.error.set('');
        },
        error: (e) => this.error.set(errorMessage(e)),
      });
    });
  }

  private loadInventories(id: string | undefined): void {
    this.api.inventories().subscribe({
      next: (list) => {
        this.inventories.set(list);
        this.loaded.set(true);
        this.inventoryId.set(id ? Number(id) : (list[0]?.id ?? null));
      },
      error: (e) => this.error.set(errorMessage(e)),
    });
  }

  protected selectInventory(ev: Event): void {
    this.priorId.set(null);
    this.baseId.set(null);
    this.router.navigate(['/disclosure', (ev.target as HTMLSelectElement).value]);
  }

  protected exportUrl(format: 'csv' | 'md' | 'json'): string {
    const id = this.inventoryId();
    return id === null ? '#' : this.api.disclosureExportUrl(id, this.query(), format);
  }

  protected toId(ev: Event): number | null {
    const v = (ev.target as HTMLSelectElement).value;
    return v ? Number(v) : null;
  }
  protected toNum(ev: Event): number | null {
    const v = (ev.target as HTMLInputElement).value;
    return v === '' ? null : Number(v);
  }
  protected num(v: number | null | undefined): string {
    return v === null || v === undefined ? '' : n1.format(v);
  }
  protected change(v: number | null | undefined): string {
    if (v === null || v === undefined) return '';
    return `${v > 0 ? '+' : ''}${(v * 100).toFixed(1)}%`;
  }
  protected isTotal(key: string): boolean {
    return key.startsWith('total_') || key === 'energy_total';
  }
  protected setGrid(key: GridKey, value: number | null): void {
    this.grid.update((g) => ({ ...g, [key]: value }));
  }
  protected sectionTitle(section: string): string {
    return (
      {
        'E1-6': 'E1-6 · Gross Scopes 1, 2, 3 and total GHG emissions',
        'E1-5': 'E1-5 · Energy consumption and mix',
        S2: 'IFRS S2 §29(a) · Greenhouse gas emissions',
      }[section] ?? section
    );
  }
  protected icon(level: string): string {
    return { blocker: '✕', warning: '⚠', info: 'ⓘ' }[level] ?? '•';
  }
  protected tone(level: string): string {
    return { blocker: 'text-crit', warning: 'text-warn', info: 'text-muted' }[level] ?? '';
  }
  protected levelLabel(level: string): string {
    return { blocker: 'Blocker', warning: 'Warning', info: 'Note' }[level] ?? level;
  }
}
