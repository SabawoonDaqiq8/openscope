import { Component, inject, signal } from '@angular/core';

import { ApiService, Factor, errorMessage } from '../api/api.service';
import { Notice } from '../shared/ui';

const PAGE = 50;

@Component({
  selector: 'os-factors',
  imports: [Notice],
  template: `
    <h1 class="text-xl font-semibold">Emission factors</h1>
    <p class="text-sm text-muted mb-4">
      Every factor the server can use, with its source and provenance. Per-gas factors can be
      recalculated under any IPCC GWP set.
    </p>

    <form class="flex flex-wrap gap-2 mb-4" (submit)="$event.preventDefault(); search(0)">
      <input
        class="input w-80"
        placeholder="e.g. electricity uk, hotel, diesel"
        aria-label="Search factors"
        [value]="q()"
        (input)="q.set($any($event.target).value)"
      />
      <select class="input" aria-label="Scope" (change)="scope.set($any($event.target).value)">
        <option value="">All scopes</option>
        <option value="1">Scope 1</option>
        <option value="2">Scope 2</option>
        <option value="3">Scope 3</option>
      </select>
      <button class="btn btn-primary" type="submit">Search</button>
      <span class="self-center text-sm text-muted ml-2"
        >{{ total().toLocaleString() }} factors</span
      >
    </form>

    @if (error()) {
      <os-notice kind="critical" title="Search failed.">{{ error() }}</os-notice>
    }

    <div class="card overflow-x-auto">
      <table class="data">
        <thead>
          <tr>
            <th>Factor</th>
            <th>Per</th>
            <th class="text-right">Value</th>
            <th>Scope</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          @for (f of items(); track f.factor_id) {
            <tr>
              <td>
                <div>{{ f.name }}</div>
                <div class="font-mono text-xs text-muted">{{ f.factor_id }}</div>
              </td>
              <td class="whitespace-nowrap">{{ f.activity_unit }}</td>
              <td class="text-right num whitespace-nowrap">
                @if (f.co2e_kg !== null) {
                  {{ f.co2e_kg }} kgCO₂e
                  @if (f.gwp_basis) {
                    <div class="text-xs text-muted">GWP {{ f.gwp_basis }}</div>
                  }
                } @else {
                  @for (g of gases(f); track g[0]) {
                    <div class="text-xs">{{ g[0] }} {{ g[1].toPrecision(4) }} kg</div>
                  }
                }
              </td>
              <td>
                {{ f.scope ?? '–' }}{{ f.scope3_category ? ' · cat ' + f.scope3_category : '' }}
              </td>
              <td class="text-xs">
                {{ f.source }}
                @if (f.status === 'illustrative') {
                  <div class="text-warn">⚠ illustrative</div>
                }
              </td>
            </tr>
          } @empty {
            <tr>
              <td colspan="5" class="text-center text-muted py-8">No factors match.</td>
            </tr>
          }
        </tbody>
      </table>
    </div>

    <div class="flex justify-between items-center mt-3 text-sm">
      <button class="btn" [disabled]="offset() === 0" (click)="search(offset() - PAGE)">
        ← Previous
      </button>
      <span class="text-muted">{{ offset() + 1 }}–{{ offset() + items().length }}</span>
      <button class="btn" [disabled]="offset() + PAGE >= total()" (click)="search(offset() + PAGE)">
        Next →
      </button>
    </div>
  `,
})
export class FactorsPage {
  private readonly api = inject(ApiService);
  protected readonly PAGE = PAGE;
  protected readonly q = signal('');
  protected readonly scope = signal('');
  protected readonly items = signal<Factor[]>([]);
  protected readonly total = signal(0);
  protected readonly offset = signal(0);
  protected readonly error = signal('');

  constructor() {
    this.search(0);
  }

  protected gases(f: Factor): [string, number][] {
    return Object.entries(f.gases);
  }

  protected search(offset: number): void {
    this.api
      .factors({
        search: this.q(),
        scope: this.scope() ? Number(this.scope()) : null,
        limit: PAGE,
        offset,
      })
      .subscribe({
        next: (p) => {
          this.items.set(p.items);
          this.total.set(p.total);
          this.offset.set(offset);
          this.error.set('');
        },
        error: (e) => this.error.set(errorMessage(e)),
      });
  }
}
