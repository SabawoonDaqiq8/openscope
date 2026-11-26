import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { NgxEchartsDirective, provideEchartsCore } from 'ngx-echarts';
import * as echarts from 'echarts/core';
import { CustomChart, LineChart } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

import {
  ApiService,
  InventoryDetail,
  InventorySummary,
  Lever,
  PathwayOut,
  Scenario,
  errorMessage,
} from '../api/api.service';
import { macc, trajectory } from '../charts/options';
import { percent, tco2e } from '../core/format';
import { ThemeService } from '../core/theme.service';
import { ChartCard, EmptyState, Notice, StatTile } from '../shared/ui';

echarts.use([
  LineChart,
  CustomChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
]);

const STORAGE = 'openscope.scenario.';

function blankScenario(year: number): Scenario {
  return {
    name: 'My scenario',
    currency: 'USD',
    base_year: year,
    target_year: year + 10,
    bau_growth: { '1': 0, '2': 0, '3': 0 },
    bau_growth_uncertainty: 0.01,
    target_rate_scope12: 0.042,
    target_rate_scope3: 0.025,
    discount_rate: 0.08,
    levers: [],
    simulations: 1000,
    seed: 42,
  };
}

function newLever(year: number, n: number): Lever {
  return {
    id: `lever-${n}`,
    name: 'New lever',
    selector: { text: '' },
    reduction: 0.5,
    reduction_low: 0.3,
    reduction_high: 0.7,
    start_year: year + 1,
    ramp_years: 2,
    capex: 0,
    annual_opex_change: 0,
    lifetime_years: 10,
    assumptions: '',
  };
}

const list = (v: string): number[] | null => {
  const xs = v
    .split(',')
    .map((x) => Number(x.trim()))
    .filter((x) => Number.isInteger(x) && x > 0);
  return xs.length ? xs : null;
};

@Component({
  selector: 'os-pathways',
  imports: [RouterLink, NgxEchartsDirective, ChartCard, EmptyState, Notice, StatTile],
  providers: [provideEchartsCore({ echarts })],
  template: `
    @if (loaded() && inventories().length === 0) {
      <os-empty title="No inventory to plan from">
        Pathways start from a calculated inventory. Load the demo or upload activity data first.
        <ng-container actions>
          <a class="btn btn-primary" routerLink="/overview">Go to overview</a>
        </ng-container>
      </os-empty>
    } @else if (scenario(); as sc) {
      <div class="flex flex-wrap items-end justify-between gap-3 mb-4">
        <div>
          <h1 class="text-xl font-semibold">Decarbonisation pathway</h1>
          <p class="text-sm text-muted">
            Model abatement levers against a science-based target, with uncertainty.
          </p>
        </div>
        <div class="flex flex-wrap items-end gap-2 w-full sm:w-auto">
          <div class="w-full sm:w-auto">
            <label for="inv" class="block text-xs text-muted mb-1">Baseline inventory</label>
            <select
              id="inv"
              class="input w-full sm:w-auto sm:min-w-64"
              [value]="inventoryId()"
              (change)="selectInventory($event)"
            >
              @for (i of inventories(); track i.id) {
                <option [value]="i.id">{{ i.name }}</option>
              }
            </select>
          </div>
          @if (demoAvailable()) {
            <button class="btn" (click)="loadDemoScenario()">Load demo scenario</button>
          }
          <button class="btn btn-primary" (click)="runPathway()" [disabled]="busy()">
            {{ busy() ? 'Simulating…' : 'Run simulation' }}
          </button>
        </div>
      </div>

      @if (error()) {
        <div class="mb-4">
          <os-notice kind="critical" title="Simulation failed.">{{ error() }}</os-notice>
        </div>
      }
      @if (illustrative()) {
        <div class="mb-4">
          <os-notice kind="warning" title="Illustrative assumptions.">
            Some levers use placeholder costs and reductions. Replace them with project estimates
            before using the results.
          </os-notice>
        </div>
      }

      <div class="grid gap-4 xl:grid-cols-[minmax(0,26rem)_minmax(0,1fr)] items-start">
        <!-- scenario editor -->
        <section class="card p-4 space-y-4" aria-label="Scenario">
          <div class="grid grid-cols-2 gap-3 text-sm">
            <label class="col-span-2"
              >Name
              <input
                class="input w-full mt-1"
                [value]="sc.name"
                (change)="set('name', $any($event.target).value)"
              />
            </label>
            <label
              >Base year
              <input
                class="input w-full mt-1"
                type="number"
                [value]="sc.base_year"
                (change)="set('base_year', +$any($event.target).value)"
              />
            </label>
            <label
              >Target year
              <input
                class="input w-full mt-1"
                type="number"
                [value]="sc.target_year"
                (change)="set('target_year', +$any($event.target).value)"
              />
            </label>
            <label
              >Target cut, Scope 1+2 (%/yr)
              <input
                class="input w-full mt-1"
                type="number"
                step="0.1"
                [value]="pctIn(sc.target_rate_scope12)"
                (change)="set('target_rate_scope12', pctOut($event))"
              />
            </label>
            <label
              >Target cut, Scope 3 (%/yr)
              <input
                class="input w-full mt-1"
                type="number"
                step="0.1"
                [value]="pctIn(sc.target_rate_scope3)"
                (change)="set('target_rate_scope3', pctOut($event))"
              />
            </label>
            @for (s of ['1', '2', '3']; track s) {
              <label
                >BAU growth, Scope {{ s }} (%/yr)
                <input
                  class="input w-full mt-1"
                  type="number"
                  step="0.5"
                  [value]="pctIn(sc.bau_growth?.[s] ?? 0)"
                  (change)="setGrowth(s, pctOut($event))"
                />
              </label>
            }
            <label
              >Discount rate (%)
              <input
                class="input w-full mt-1"
                type="number"
                step="0.5"
                [value]="pctIn(sc.discount_rate)"
                (change)="set('discount_rate', pctOut($event))"
              />
            </label>
            <label
              >Currency
              <input
                class="input w-full mt-1"
                maxlength="3"
                [value]="sc.currency"
                (change)="set('currency', $any($event.target).value.toUpperCase())"
              />
            </label>
          </div>
          <p class="text-xs text-muted">
            Default target rates are the SBTi near-term minimum linear reductions: 4.2 %/yr for
            Scope 1+2 (1.5 °C) and 2.5 %/yr for Scope 3 (well below 2 °C).
          </p>

          <div>
            <div class="flex items-center justify-between mb-2">
              <h2 class="font-semibold">Levers</h2>
              <button class="btn text-xs" (click)="addLever()">+ Add lever</button>
            </div>
            <div class="space-y-3">
              @for (lv of sc.levers ?? []; track lv.id; let i = $index) {
                <details class="rounded-lg border border-line" [open]="lv.id === initiallyOpen()">
                  <summary class="cursor-pointer px-3 py-2 text-sm flex justify-between gap-2">
                    <span class="font-medium">{{ lv.name }}</span>
                    <span class="text-muted num"
                      >−{{ pctIn(lv.reduction) }}% from {{ lv.start_year }}</span
                    >
                  </summary>
                  <div class="grid grid-cols-3 gap-2 px-3 pb-3 text-xs">
                    <label class="col-span-3"
                      >Name
                      <input
                        class="input w-full mt-0.5"
                        [value]="lv.name"
                        (change)="setLever(i, { name: $any($event.target).value })"
                      />
                    </label>
                    <label class="col-span-3"
                      >Applies to lines matching (text)
                      <input
                        class="input w-full mt-0.5"
                        placeholder="e.g. natural gas"
                        [value]="lv.selector.text ?? ''"
                        (change)="setSelector(i, { text: $any($event.target).value || null })"
                      />
                    </label>
                    <label
                      >Scopes
                      <input
                        class="input w-full mt-0.5"
                        placeholder="1,2"
                        [value]="(lv.selector.scopes ?? []).join(',')"
                        (change)="setSelector(i, { scopes: list($any($event.target).value) })"
                      />
                    </label>
                    <label class="col-span-2"
                      >Scope 3 categories
                      <input
                        class="input w-full mt-0.5"
                        placeholder="6"
                        [value]="(lv.selector.scope3_categories ?? []).join(',')"
                        (change)="
                          setSelector(i, { scope3_categories: list($any($event.target).value) })
                        "
                      />
                    </label>
                    <label
                      >Cut low %
                      <input
                        class="input w-full mt-0.5"
                        type="number"
                        [value]="pctIn(lv.reduction_low ?? lv.reduction)"
                        (change)="setLever(i, { reduction_low: pctOut($event) })"
                      />
                    </label>
                    <label
                      >Cut likely %
                      <input
                        class="input w-full mt-0.5"
                        type="number"
                        [value]="pctIn(lv.reduction)"
                        (change)="setLever(i, { reduction: pctOut($event) })"
                      />
                    </label>
                    <label
                      >Cut high %
                      <input
                        class="input w-full mt-0.5"
                        type="number"
                        [value]="pctIn(lv.reduction_high ?? lv.reduction)"
                        (change)="setLever(i, { reduction_high: pctOut($event) })"
                      />
                    </label>
                    <label
                      >Start year
                      <input
                        class="input w-full mt-0.5"
                        type="number"
                        [value]="lv.start_year"
                        (change)="setLever(i, { start_year: +$any($event.target).value })"
                      />
                    </label>
                    <label
                      >Ramp (years)
                      <input
                        class="input w-full mt-0.5"
                        type="number"
                        min="1"
                        [value]="lv.ramp_years"
                        (change)="setLever(i, { ramp_years: +$any($event.target).value })"
                      />
                    </label>
                    <label
                      >Lifetime (years)
                      <input
                        class="input w-full mt-0.5"
                        type="number"
                        min="1"
                        [value]="lv.lifetime_years"
                        (change)="setLever(i, { lifetime_years: +$any($event.target).value })"
                      />
                    </label>
                    <label
                      >Capex ({{ sc.currency }})
                      <input
                        class="input w-full mt-0.5"
                        type="number"
                        min="0"
                        [value]="lv.capex"
                        (change)="setLever(i, { capex: +$any($event.target).value })"
                      />
                    </label>
                    <label class="col-span-2"
                      >Opex change/yr ({{ sc.currency }}, − = saving)
                      <input
                        class="input w-full mt-0.5"
                        type="number"
                        [value]="lv.annual_opex_change"
                        (change)="setLever(i, { annual_opex_change: +$any($event.target).value })"
                      />
                    </label>
                    <label class="col-span-3"
                      >Assumptions
                      <input
                        class="input w-full mt-0.5"
                        [value]="lv.assumptions ?? ''"
                        (change)="setLever(i, { assumptions: $any($event.target).value })"
                      />
                    </label>
                    <div class="col-span-3 flex justify-end">
                      <button class="btn text-xs" (click)="removeLever(i)">Remove</button>
                    </div>
                  </div>
                </details>
              } @empty {
                <p class="text-sm text-muted">No levers yet. Add one, or load the demo scenario.</p>
              }
            </div>
          </div>
        </section>

        <!-- results -->
        <div class="space-y-4 min-w-0">
          @if (result(); as r) {
            <div class="grid gap-4 grid-cols-2 lg:grid-cols-4">
              <os-stat
                [label]="sc.target_year + ' pathway'"
                [value]="fmt(r.pathway[r.pathway.length - 1])"
                unit="tCO₂e"
                [hint]="
                  'P10–P90 ' + fmt(r.p10[r.p10.length - 1]) + '–' + fmt(r.p90[r.p90.length - 1])
                "
              />
              <os-stat
                [label]="'vs ' + r.years[0]"
                [value]="change(r)"
                unit=""
                [hint]="'BAU ' + fmt(r.bau[r.bau.length - 1]) + ' tCO₂e'"
              />
              @for (g of groups(r); track g.label) {
                <div class="card p-4">
                  <div class="text-sm text-muted">{{ g.label }} target</div>
                  <div
                    class="mt-1 text-lg font-semibold"
                    [class]="g.ok ? 'text-good' : 'text-crit'"
                  >
                    <span aria-hidden="true">{{ g.ok ? '✓' : '✕' }}</span>
                    {{ g.ok ? 'On track' : 'Short by ' + fmt(g.gap) + ' t' }}
                  </div>
                  <div class="mt-1 text-xs text-muted">
                    {{ fmt(g.pathway) }} vs target {{ fmt(g.target) }} · P(meet) {{ pct(g.prob) }}
                  </div>
                </div>
              }
            </div>

            <os-chart-card
              title="Emissions trajectory"
              [subtitle]="
                'tCO₂e per year, ' +
                r.years[0] +
                '–' +
                r.years[r.years.length - 1] +
                ' · shaded band: P10–P90 of ' +
                sc.simulations +
                ' simulations'
              "
            >
              <div chart echarts [options]="trajectoryChart()" class="h-80"></div>
              <div table class="overflow-x-auto">
                <table class="data">
                  <thead>
                    <tr>
                      <th>Year</th>
                      <th class="text-right">BAU</th>
                      <th class="text-right">Pathway</th>
                      <th class="text-right">P10</th>
                      <th class="text-right">P90</th>
                      <th class="text-right">Target</th>
                    </tr>
                  </thead>
                  <tbody>
                    @for (y of r.years; track y; let i = $index) {
                      <tr>
                        <td>{{ y }}</td>
                        <td class="text-right num">{{ fmt(r.bau[i]) }}</td>
                        <td class="text-right num">{{ fmt(r.pathway[i]) }}</td>
                        <td class="text-right num">{{ fmt(r.p10[i]) }}</td>
                        <td class="text-right num">{{ fmt(r.p90[i]) }}</td>
                        <td class="text-right num">{{ fmt(r.target[i]) }}</td>
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
            </os-chart-card>

            <os-chart-card
              title="Marginal abatement cost curve"
              [subtitle]="
                'Cheapest abatement first · bar width = tCO₂e/yr, height = ' +
                r.currency +
                ' per tCO₂e · below zero saves money'
              "
            >
              <div chart echarts [options]="maccChart()" class="h-72"></div>
              <p table class="text-sm text-muted">The lever table below lists the same values.</p>
            </os-chart-card>

            <section class="card overflow-x-auto">
              <table class="data">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Lever</th>
                    <th class="text-right">Lines</th>
                    <th class="text-right">Abatement tCO₂e/yr</th>
                    <th class="text-right">In {{ sc.target_year }}</th>
                    <th class="text-right">Annualised cost</th>
                    <th class="text-right">{{ r.currency }}/tCO₂e</th>
                  </tr>
                </thead>
                <tbody>
                  @for (l of r.levers; track l.id) {
                    <tr>
                      <td class="num">{{ l.merit_rank }}</td>
                      <td>{{ l.name }}</td>
                      <td class="text-right num" [class.text-crit]="l.matched_lines === 0">
                        {{ l.matched_lines }}
                      </td>
                      <td class="text-right num">{{ fmt(l.abatement_tco2e) }}</td>
                      <td class="text-right num">{{ fmt(l.abatement_by_target_year_tco2e) }}</td>
                      <td class="text-right num">{{ whole(l.annualised_cost) }}</td>
                      <td class="text-right num">{{ l.mac === null ? '–' : whole(l.mac) }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            </section>
          } @else {
            <div class="card p-10 text-center text-sm text-muted">
              Set up the scenario and press <b>Run simulation</b>.
            </div>
          }
        </div>
      </div>
    } @else {
      <p class="text-muted">Loading…</p>
    }
  `,
})
export class PathwaysPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  protected readonly tokens = inject(ThemeService).tokens;
  readonly id = input<string>();

  protected readonly inventories = signal<InventorySummary[]>([]);
  protected readonly inventory = signal<InventoryDetail | null>(null);
  protected readonly inventoryId = computed(() => this.inventory()?.id ?? null);
  protected readonly scenario = signal<Scenario | null>(null);
  protected readonly result = signal<PathwayOut | null>(null);
  protected readonly loaded = signal(false);
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly demoAvailable = signal(false);
  /** Opened automatically when shown first or newly added; afterwards the user decides. */
  protected readonly initiallyOpen = signal<string | null>(null);

  protected readonly illustrative = computed(() =>
    (this.scenario()?.levers ?? []).some((l) => /illustrative/i.test(l.assumptions ?? '')),
  );
  protected readonly trajectoryChart = computed(() => {
    const r = this.result();
    return r ? trajectory(r, this.tokens()) : {};
  });
  protected readonly maccChart = computed(() => {
    const r = this.result();
    if (!r) return {};
    const bars = r.levers
      .filter((l) => l.mac !== null && l.abatement_tco2e > 0)
      .map((l) => ({
        rank: l.merit_rank,
        name: l.name,
        abatement: l.abatement_tco2e,
        mac: l.mac!,
      }));
    return macc(bars, this.tokens(), r.currency);
  });

  protected readonly fmt = tco2e;
  protected readonly pct = percent;
  protected readonly list = list;
  protected whole(v: number): string {
    return Math.round(v).toLocaleString('en-GB');
  }
  protected pctIn(v: number | null | undefined): number {
    return Math.round((v ?? 0) * 1000) / 10;
  }
  protected pctOut(ev: Event): number {
    return Number((ev.target as HTMLInputElement).value) / 100;
  }
  protected change(r: PathwayOut): string {
    const last = r.pathway[r.pathway.length - 1];
    return `${last <= r.base_tco2e ? '−' : '+'}${percent(Math.abs(last / r.base_tco2e - 1))}`;
  }
  protected groups(r: PathwayOut) {
    return [
      { label: 'Scope 1+2', g: r.scope12 },
      { label: 'Scope 3', g: r.scope3 },
    ].map(({ label, g }) => ({
      label,
      ok: g.gap_tco2e <= 0,
      gap: g.gap_tco2e,
      pathway: g.pathway_tco2e,
      target: g.target_tco2e,
      prob: g.probability_meets_target,
    }));
  }

  constructor() {
    this.api.meta().subscribe((m) => this.demoAvailable.set(m.demo_available));
    effect(() => this.load(this.id()));
  }

  private load(id: string | undefined): void {
    this.api.inventories().subscribe({
      next: (list) => {
        this.inventories.set(list);
        this.loaded.set(true);
        const target = id ? Number(id) : list[0]?.id;
        if (target) {
          this.api.inventory(target).subscribe((inv) => {
            this.inventory.set(inv);
            this.result.set(null);
            this.scenario.set(
              this.restore(inv) ??
                blankScenario(inv.reporting_year ?? new Date().getFullYear() - 1),
            );
          });
        }
      },
      error: (e) => this.error.set(errorMessage(e)),
    });
  }

  private restore(inv: InventoryDetail): Scenario | null {
    try {
      const raw = localStorage.getItem(STORAGE + inv.id);
      return raw ? (JSON.parse(raw) as Scenario) : null;
    } catch {
      return null;
    }
  }

  private save(sc: Scenario): void {
    const id = this.inventoryId();
    if (id === null) return;
    try {
      localStorage.setItem(STORAGE + id, JSON.stringify(sc));
    } catch {
      /* storage unavailable: the scenario lives for this session only */
    }
  }

  private update(fn: (s: Scenario) => Scenario): void {
    const s = this.scenario();
    if (!s) return;
    const next = fn(s);
    this.scenario.set(next);
    this.save(next);
  }

  protected set<K extends keyof Scenario>(key: K, value: Scenario[K]): void {
    this.update((s) => ({ ...s, [key]: value }));
  }
  protected setGrowth(scope: string, v: number): void {
    this.update((s) => ({ ...s, bau_growth: { ...(s.bau_growth ?? {}), [scope]: v } }));
  }
  protected setLever(i: number, patch: Partial<Lever>): void {
    this.update((s) => ({
      ...s,
      levers: (s.levers ?? []).map((l, j) => (j === i ? { ...l, ...patch } : l)),
    }));
  }
  protected setSelector(i: number, patch: Partial<Lever['selector']>): void {
    this.update((s) => ({
      ...s,
      levers: (s.levers ?? []).map((l, j) =>
        j === i ? { ...l, selector: { ...l.selector, ...patch } } : l,
      ),
    }));
  }
  protected addLever(): void {
    this.update((s) => {
      const levers = s.levers ?? [];
      const lever = newLever(s.base_year, levers.length + 1);
      this.initiallyOpen.set(lever.id);
      return { ...s, levers: [...levers, lever] };
    });
  }
  protected removeLever(i: number): void {
    this.update((s) => ({ ...s, levers: (s.levers ?? []).filter((_, j) => j !== i) }));
  }

  protected selectInventory(ev: Event): void {
    this.router.navigate(['/pathways', (ev.target as HTMLSelectElement).value]);
  }

  protected loadDemoScenario(): void {
    this.api.demoScenario().subscribe({
      next: (sc) => {
        this.initiallyOpen.set(sc.levers?.[0]?.id ?? null);
        this.scenario.set(sc);
        this.save(sc);
        this.runPathway();
      },
      error: (e) => this.error.set(errorMessage(e)),
    });
  }

  protected runPathway(): void {
    const id = this.inventoryId();
    const sc = this.scenario();
    if (id === null || !sc) return;
    this.busy.set(true);
    this.error.set('');
    this.api.pathway(id, sc).subscribe({
      next: (r) => {
        this.result.set(r);
        this.busy.set(false);
      },
      error: (e) => {
        this.busy.set(false);
        this.error.set(errorMessage(e));
      },
    });
  }
}
