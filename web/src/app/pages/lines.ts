import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiService, Line, errorMessage } from '../api/api.service';
import { METHOD_LABELS, kgco2e } from '../core/format';
import { ThemeService } from '../core/theme.service';
import { Notice } from '../shared/ui';

@Component({
  selector: 'os-lines',
  imports: [RouterLink, Notice],
  template: `
    <div class="flex flex-wrap items-end justify-between gap-3 mb-4">
      <div>
        <a class="text-sm text-muted hover:underline" [routerLink]="['/overview', id()]"
          >← Overview</a
        >
        <h1 class="text-xl font-semibold mt-1">Line explorer</h1>
        <p class="text-sm text-muted">
          Every calculated line with its full audit trail. Select a row to see how it was computed.
        </p>
      </div>
      <div class="flex gap-2">
        <input
          class="input w-64"
          placeholder="Search description, factor, site…"
          aria-label="Search lines"
          [value]="query()"
          (input)="query.set($any($event.target).value)"
        />
        <select
          class="input"
          aria-label="Filter by scope"
          (change)="scope.set($any($event.target).value)"
        >
          <option value="">All scopes</option>
          <option value="1">Scope 1</option>
          <option value="2">Scope 2</option>
          <option value="3">Scope 3</option>
        </select>
      </div>
    </div>

    @if (error()) {
      <os-notice kind="critical" title="Could not load lines.">{{ error() }}</os-notice>
    }

    <div class="card overflow-x-auto">
      <table class="data">
        <thead>
          <tr>
            <th>Line</th>
            <th>Scope</th>
            <th>Method</th>
            <th class="text-right">Quantity</th>
            <th>Factor</th>
            <th class="text-right">kgCO₂e</th>
            <th class="text-right">DQ</th>
          </tr>
        </thead>
        <tbody>
          @for (l of filtered(); track l.activity_id + (l.scope2_method ?? '')) {
            <tr class="cursor-pointer hover:bg-surface-2" (click)="toggle(l)">
              <td>
                <button
                  type="button"
                  class="text-left w-full"
                  [attr.aria-expanded]="open() === key(l)"
                  [attr.aria-label]="'Audit trail for ' + (l.description || l.activity_id)"
                  (click)="$event.stopPropagation(); toggle(l)"
                >
                  <span class="block">{{ l.description || l.activity_id }}</span>
                  <span class="block text-xs text-muted">
                    {{ l.activity_id }}{{ l.site ? ' · ' + l.site : '' }}
                  </span>
                </button>
              </td>
              <td class="whitespace-nowrap">
                <span class="swatch mr-1.5" [style.background]="tokens().scope[l.scope - 1]"></span>
                {{ l.scope }}{{ l.scope3_category ? ' · cat ' + l.scope3_category : '' }}
                @if (l.scope2_method) {
                  <div class="text-xs text-muted">
                    {{ l.scope2_method === 'market_based' ? 'market' : 'location' }}
                  </div>
                }
              </td>
              <td class="whitespace-nowrap">{{ method(l.method) }}</td>
              <td class="text-right num whitespace-nowrap">
                {{ l.quantity.toLocaleString() }} {{ l.unit }}
              </td>
              <td>
                <div class="font-mono text-xs">{{ l.factor_id }}</div>
                @if (l.factor_status === 'illustrative') {
                  <div class="text-xs text-warn">⚠ illustrative</div>
                }
              </td>
              <td class="text-right num">{{ kg(l.co2e_kg) }}</td>
              <td class="text-right num">{{ l.data_quality_score }}</td>
            </tr>
            @if (open() === key(l)) {
              <tr>
                <td colspan="7" class="bg-surface-2">
                  <div class="text-xs text-muted mb-1">
                    Audit trail · GWP {{ l.gwp_set }} · {{ l.factor_source }}
                  </div>
                  <ol class="font-mono text-xs space-y-1 list-decimal pl-5">
                    @for (step of l.trace; track $index) {
                      <li [class.text-warn]="step.startsWith('WARNING')">{{ step }}</li>
                    }
                  </ol>
                </td>
              </tr>
            }
          } @empty {
            <tr>
              <td colspan="7" class="text-center text-muted py-8">No lines match.</td>
            </tr>
          }
        </tbody>
      </table>
    </div>
  `,
})
export class LinesPage {
  private readonly api = inject(ApiService);
  protected readonly tokens = inject(ThemeService).tokens;
  readonly id = input.required<string>();

  protected readonly lines = signal<Line[]>([]);
  protected readonly error = signal('');
  protected readonly query = signal('');
  protected readonly scope = signal('');
  protected readonly open = signal<string | null>(null);

  protected readonly filtered = computed(() => {
    const q = this.query().toLowerCase().trim();
    const s = this.scope();
    return this.lines().filter(
      (l) =>
        (!s || String(l.scope) === s) &&
        (!q ||
          [l.activity_id, l.description, l.factor_id, l.site, l.supplier]
            .join(' ')
            .toLowerCase()
            .includes(q)),
    );
  });

  protected readonly kg = kgco2e;
  protected method(m: string): string {
    return METHOD_LABELS[m] ?? m;
  }
  protected key(l: Line): string {
    return l.activity_id + (l.scope2_method ?? '');
  }
  protected toggle(l: Line): void {
    this.open.update((o) => (o === this.key(l) ? null : this.key(l)));
  }

  constructor() {
    effect(() => {
      this.api.lines(Number(this.id())).subscribe({
        next: (ls) => this.lines.set(ls),
        error: (e) => this.error.set(errorMessage(e)),
      });
    });
  }
}
