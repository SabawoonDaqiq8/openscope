import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { NgxEchartsDirective, provideEchartsCore } from 'ngx-echarts';
import * as echarts from 'echarts/core';
import { BarChart } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

import { ApiService, InventoryDetail, InventorySummary, errorMessage } from '../api/api.service';
import { orderedColumns, rankedBars, scopeComposition } from '../charts/options';
import { METHOD_LABELS, percent, tco2e } from '../core/format';
import { ThemeService } from '../core/theme.service';
import { ChartCard, EmptyState, HowItWorks, Notice, StatTile } from '../shared/ui';

echarts.use([BarChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

@Component({
  selector: 'os-overview',
  imports: [RouterLink, NgxEchartsDirective, StatTile, Notice, ChartCard, EmptyState, HowItWorks],
  providers: [provideEchartsCore({ echarts })],
  template: `
    @if (error()) {
      <os-notice kind="critical" title="Could not load data.">{{ error() }}</os-notice>
    } @else if (loaded() && inventories().length === 0) {
      <os-empty title="No inventories yet">
        Upload activity data or load the demo: a UK company's 2025 inventory calculated with
        official DESNZ factors, plus a 40-line purchase ledger to classify.
        <ng-container actions>
          <button class="btn btn-primary" (click)="loadDemo()" [disabled]="busy()">
            {{ busy() ? 'Loading…' : 'Load demo data' }}
          </button>
          <a class="btn" routerLink="/upload">Upload CSV</a>
        </ng-container>
      </os-empty>
    } @else if (inv(); as d) {
      <h1 class="sr-only">Emissions overview</h1>
      <os-how-it-works [linesLink]="['/overview', d.id, 'lines']" />
      <div class="flex flex-wrap items-end justify-between gap-3 mb-5">
        <div class="w-full sm:w-auto">
          <label for="inv" class="block text-xs text-muted mb-1">Inventory</label>
          <select
            id="inv"
            class="input w-full sm:w-auto sm:min-w-72"
            [value]="d.id"
            (change)="select($event)"
          >
            @for (i of inventories(); track i.id) {
              <option [value]="i.id">{{ i.name }}</option>
            }
          </select>
        </div>
        <div class="flex flex-wrap items-center gap-3 text-sm text-muted">
          <span>GWP {{ d.gwp_set }}</span>
          @if (d.reporting_year) {
            <span>· Reporting year {{ d.reporting_year }}</span>
          }
          <a class="btn" [routerLink]="['/overview', d.id, 'lines']">Line explorer →</a>
        </div>
      </div>

      <div class="space-y-3 mb-5">
        @if (t().illustrative_factor_share > 0) {
          <os-notice kind="warning" title="Illustrative factors in use.">
            {{ pct(t().illustrative_factor_share) }} of emissions rely on placeholder factors, so
            this inventory is not suitable for disclosure.
          </os-notice>
        }
        @if (t().scope2_market_fallback_sites.length) {
          <os-notice kind="info" title="Scope 2 market-based fallback.">
            No contractual data for {{ t().scope2_market_fallback_sites.join(', ') }}; the
            grid-average factor is used in the market-based total.
          </os-notice>
        }
        @if (d.error_count) {
          <os-notice kind="critical" title="{{ d.error_count }} lines could not be calculated.">
            @for (e of d.analytics.errors; track e.activity_id) {
              <span class="block">{{ e.activity_id }}: {{ e.message }}</span>
            }
          </os-notice>
        }
      </div>

      <div class="grid gap-4 grid-cols-2 lg:grid-cols-5 mb-4">
        <os-stat
          label="Total emissions"
          [value]="fmt(t().total_tco2e)"
          unit="tCO₂e"
          hint="Scope 2 market-based"
        />
        <os-stat
          label="Scope 1"
          [value]="fmt(t().scope1_tco2e)"
          unit="tCO₂e"
          [swatch]="tokens().scope[0]"
          hint="Direct emissions"
        />
        <os-stat
          label="Scope 2"
          [value]="fmt(t().scope2_market_tco2e)"
          unit="tCO₂e"
          [swatch]="tokens().scope[1]"
          [hint]="'Location-based: ' + fmt(t().scope2_location_tco2e)"
        />
        <os-stat
          label="Scope 3"
          [value]="fmt(t().scope3_tco2e)"
          unit="tCO₂e"
          [swatch]="tokens().scope[2]"
          hint="Value chain"
        />
        <os-stat
          label="Data quality"
          [value]="t().data_quality_score?.toFixed(1) ?? '–'"
          unit="/ 5"
          hint="Emissions-weighted · 1 = best"
        />
      </div>

      <div class="grid gap-4 grid-cols-1 lg:grid-cols-2 items-start mb-4">
        <os-chart-card title="Emissions by scope" subtitle="Share of total, tCO₂e">
          <div chart>
            <div echarts [options]="scopeChart()" class="h-24"></div>
            <ul class="mt-3 grid grid-cols-3 gap-3 text-sm">
              @for (p of scopeParts(); track p.label; let i = $index) {
                <li>
                  <div class="flex items-center gap-1.5 text-muted">
                    <span class="swatch" [style.background]="tokens().scope[i]"></span>{{ p.label }}
                  </div>
                  <div class="num font-medium">
                    {{ fmt(p.value) }}
                    <span class="text-muted font-normal"
                      >· {{ pct(p.value / (t().total_tco2e || 1)) }}</span
                    >
                  </div>
                </li>
              }
            </ul>
          </div>
          <table table class="data">
            <thead>
              <tr>
                <th>Scope</th>
                <th class="text-right">tCO₂e</th>
                <th class="text-right">Share</th>
              </tr>
            </thead>
            <tbody>
              @for (p of scopeParts(); track p.label) {
                <tr>
                  <td>{{ p.label }}</td>
                  <td class="text-right num">{{ fmt(p.value) }}</td>
                  <td class="text-right num">{{ pct(p.value / (t().total_tco2e || 1)) }}</td>
                </tr>
              }
            </tbody>
          </table>
        </os-chart-card>

        <os-chart-card
          title="Data quality"
          subtitle="tCO₂e by score · 1 = supplier-specific, 5 = estimated"
        >
          <div chart echarts [options]="qualityChart()" class="h-48"></div>
          <table table class="data">
            <thead>
              <tr>
                <th>Score</th>
                <th class="text-right">Lines</th>
                <th class="text-right">tCO₂e</th>
              </tr>
            </thead>
            <tbody>
              @for (q of d.analytics.data_quality; track q.score) {
                <tr>
                  <td>{{ q.score }}</td>
                  <td class="text-right num">{{ q.lines }}</td>
                  <td class="text-right num">{{ fmt(q.tco2e) }}</td>
                </tr>
              }
            </tbody>
          </table>
        </os-chart-card>
      </div>

      <div class="grid gap-4 grid-cols-1 lg:grid-cols-2 items-start">
        <os-chart-card title="Scope 3 by category" subtitle="tCO₂e, GHG Protocol categories">
          @if (d.analytics.totals.scope3_by_category.length) {
            <div
              chart
              echarts
              [options]="categoryChart()"
              [style.height.px]="categoryHeight()"
            ></div>
          } @else {
            <p chart class="text-sm text-muted">No Scope 3 data in this inventory.</p>
          }
          <table table class="data">
            <thead>
              <tr>
                <th>Category</th>
                <th class="text-right">tCO₂e</th>
              </tr>
            </thead>
            <tbody>
              @for (c of d.analytics.totals.scope3_by_category; track c.category) {
                <tr>
                  <td>{{ c.category }}. {{ c.label }}</td>
                  <td class="text-right num">{{ fmt(c.tco2e) }}</td>
                </tr>
              }
            </tbody>
          </table>
        </os-chart-card>

        <section class="card p-4">
          <h2 class="font-semibold">Hotspots</h2>
          <p class="text-sm text-muted mb-3">Largest line items in the headline total</p>
          <div class="overflow-x-auto">
            <table class="data">
              <thead>
                <tr>
                  <th>Line</th>
                  <th>Scope</th>
                  <th class="text-right">tCO₂e</th>
                  <th class="text-right">Share</th>
                </tr>
              </thead>
              <tbody>
                @for (h of d.analytics.hotspots; track h.activity_id) {
                  <tr>
                    <td>
                      <div>{{ h.description || h.activity_id }}</div>
                      <div class="text-xs text-muted">{{ h.activity_id }}</div>
                    </td>
                    <td class="whitespace-nowrap">
                      <span
                        class="swatch mr-1.5"
                        [style.background]="tokens().scope[h.scope - 1]"
                      ></span>
                      {{ h.scope }}{{ h.scope3_category ? ' · cat ' + h.scope3_category : '' }}
                    </td>
                    <td class="text-right num">{{ fmt(h.tco2e) }}</td>
                    <td class="text-right num">{{ pct(h.share) }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
          <h3 class="font-semibold mt-5 mb-2 text-sm">By calculation method</h3>
          <div class="overflow-x-auto">
            <table class="data">
              <tbody>
                @for (m of d.analytics.by_method; track m.method) {
                  <tr>
                    <td>{{ methodLabel(m.method) }}</td>
                    <td class="text-right num">{{ fmt(m.tco2e) }} tCO₂e</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </section>
      </div>
    } @else {
      <p class="text-muted">Loading…</p>
    }
  `,
})
export class OverviewPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  protected readonly tokens = inject(ThemeService).tokens;

  /** Route parameter (`/inventories/:id`); empty on `/overview` → latest inventory. */
  readonly id = input<string>();

  protected readonly inventories = signal<InventorySummary[]>([]);
  protected readonly inv = signal<InventoryDetail | null>(null);
  protected readonly loaded = signal(false);
  protected readonly busy = signal(false);
  protected readonly error = signal('');

  protected readonly t = computed(() => this.inv()!.analytics.totals);
  protected readonly scopeParts = computed(() => [
    { label: 'Scope 1', value: this.t().scope1_tco2e },
    { label: 'Scope 2 (market)', value: this.t().scope2_market_tco2e },
    { label: 'Scope 3', value: this.t().scope3_tco2e },
  ]);
  protected readonly scopeChart = computed(() =>
    scopeComposition(this.scopeParts(), this.tokens()),
  );
  protected readonly categoryChart = computed(() =>
    rankedBars(
      this.t().scope3_by_category.map((c) => ({
        label: `${c.category}. ${c.label}`,
        value: c.tco2e,
      })),
      this.tokens(),
      { color: this.tokens().scope[2] },
    ),
  );
  protected readonly categoryHeight = computed(() => 24 + 34 * this.t().scope3_by_category.length);
  protected readonly qualityChart = computed(() => {
    const byScore = new Map(this.inv()!.analytics.data_quality.map((q) => [q.score, q.tco2e]));
    return orderedColumns(
      [1, 2, 3, 4, 5].map((s) => ({ label: String(s), value: byScore.get(s) ?? 0 })),
      this.tokens(),
    );
  });

  protected readonly fmt = tco2e;
  protected readonly pct = percent;
  protected methodLabel(m: string): string {
    return METHOD_LABELS[m] ?? m;
  }

  constructor() {
    effect(() => this.load(this.id()));
  }

  private load(id: string | undefined): void {
    this.api.inventories().subscribe({
      next: (list) => {
        this.inventories.set(list);
        this.loaded.set(true);
        const target = id ? Number(id) : list[0]?.id;
        if (target) this.fetch(target);
      },
      error: (e) => this.error.set(errorMessage(e)),
    });
  }

  private fetch(id: number): void {
    this.api.inventory(id).subscribe({
      next: (d) => this.inv.set(d),
      error: (e) => this.error.set(errorMessage(e)),
    });
  }

  protected select(ev: Event): void {
    const id = (ev.target as HTMLSelectElement).value;
    this.router.navigate(['/overview', id]);
  }

  protected loadDemo(): void {
    this.busy.set(true);
    this.api.demo().subscribe({
      next: (r) => {
        this.busy.set(false);
        this.router.navigate(['/overview', r.inventory_id]);
      },
      error: (e) => {
        this.busy.set(false);
        this.error.set(errorMessage(e));
      },
    });
  }
}
