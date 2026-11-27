import { Component, computed, input, output } from '@angular/core';

import type { Schemas } from '../api/api.service';
import { percent, tco2e } from '../core/format';

type TargetsOut = Schemas['TargetsOut'];
export type TargetsFormat = 'md' | 'csv' | 'json';

/** ESRS E1-4 GHG emission reduction targets, derived from the pathway scenario. */
@Component({
  selector: 'os-targets-panel',
  template: `
    @let d = data();
    <section class="card overflow-x-auto" aria-labelledby="e14-title">
      <header class="flex flex-wrap items-start justify-between gap-2 px-4 pt-4 pb-2">
        <div>
          <h2 id="e14-title" class="font-semibold">ESRS E1-4 GHG emission reduction targets</h2>
          <p class="text-sm text-muted">
            From this scenario: linear absolute reduction from {{ d.base_year }} to
            {{ d.target_year }}, gross (no removals or credits), Scope 2 {{ d.scope2_basis }}.
          </p>
        </div>
        <div class="flex gap-1.5">
          @for (f of formats; track f.value) {
            <button type="button" class="btn text-xs" (click)="download.emit(f.value)">
              {{ f.label }}
            </button>
          }
        </div>
      </header>
      <table class="data">
        <thead>
          <tr>
            <th>Boundary</th>
            <th class="text-right">Base {{ d.base_year }}</th>
            <th class="text-right">Year</th>
            <th class="text-right">Target tCO₂e</th>
            <th class="text-right">vs base</th>
            <th class="text-right">With levers</th>
            <th class="text-right">Gap</th>
          </tr>
        </thead>
        <tbody>
          @for (t of d.targets; track t.key) {
            @for (m of t.milestones; track m.year; let first = $first) {
              <tr>
                <td>{{ first ? t.boundary : '' }}</td>
                <td class="text-right num">{{ first ? fmt(t.base_tco2e) : '' }}</td>
                <td class="text-right num">{{ m.year }}</td>
                <td class="text-right num">{{ fmt(m.target_tco2e) }}</td>
                <td class="text-right num">−{{ pct(m.reduction_vs_base) }}</td>
                <td class="text-right num">{{ fmt(m.expected_tco2e) }}</td>
                <td class="text-right num" [class]="m.gap_tco2e > 0.05 ? 'text-crit' : 'text-good'">
                  {{ m.gap_tco2e > 0.05 ? '+' + fmt(m.gap_tco2e) : 'on track' }}
                </td>
              </tr>
            }
          }
        </tbody>
      </table>

      <ul class="px-4 py-3 space-y-1 text-sm">
        @for (t of d.targets; track t.key) {
          <li>
            <span class="font-semibold">{{ t.boundary + ': ' }}</span>
            <span class="text-muted">{{ t.ambition }}</span>
          </li>
        }
      </ul>

      <h3 class="px-4 pt-2 text-sm font-semibold">
        Decarbonisation levers in {{ d.target_year }} (§34(f))
      </h3>
      <table class="data">
        <thead>
          <tr>
            <th>Lever</th>
            <th class="text-right">Scope 1+2 tCO₂e</th>
            <th class="text-right">Share</th>
            <th class="text-right">Scope 3 tCO₂e</th>
            <th class="text-right">Share</th>
          </tr>
        </thead>
        <tbody>
          @for (l of d.levers; track l.id) {
            <tr>
              <td>{{ l.name }}</td>
              <td class="text-right num">{{ fmt(l.scope12_tco2e) }}</td>
              <td class="text-right num">{{ pct(l.share_of_scope12_reduction) }}</td>
              <td class="text-right num">{{ fmt(l.scope3_tco2e) }}</td>
              <td class="text-right num">{{ pct(l.share_of_scope3_reduction) }}</td>
            </tr>
          }
        </tbody>
      </table>

      <div class="px-4 py-3 text-sm" aria-label="E1-4 readiness checks" role="group">
        <h3 class="font-semibold mb-2">
          Readiness:
          {{
            blockers() === 0
              ? 'no blockers'
              : blockers() + ' blocker' + (blockers() === 1 ? '' : 's')
          }}
        </h3>
        <ul class="space-y-2">
          @for (c of d.checks; track c.code) {
            <li class="flex gap-2">
              <span class="font-semibold shrink-0" [class]="tone(c.level)" aria-hidden="true">{{
                icon(c.level)
              }}</span>
              <span>
                <span class="font-semibold" [class]="tone(c.level)">{{ label(c.level) }}.</span>
                {{ c.message }}
              </span>
            </li>
          }
        </ul>
      </div>
    </section>
  `,
})
export class TargetsPanel {
  readonly data = input.required<TargetsOut>();
  readonly download = output<TargetsFormat>();

  protected readonly formats: { value: TargetsFormat; label: string }[] = [
    { value: 'md', label: 'Markdown' },
    { value: 'csv', label: 'CSV' },
    { value: 'json', label: 'JSON' },
  ];
  protected readonly blockers = computed(
    () => this.data().checks.filter((c) => c.level === 'blocker').length,
  );
  protected readonly fmt = tco2e;
  protected readonly pct = percent;

  protected icon(level: string): string {
    return { blocker: '✕', warning: '⚠', info: 'ⓘ' }[level] ?? '•';
  }
  protected tone(level: string): string {
    return { blocker: 'text-crit', warning: 'text-warn', info: 'text-muted' }[level] ?? '';
  }
  protected label(level: string): string {
    return { blocker: 'Blocker', warning: 'Warning', info: 'Note' }[level] ?? level;
  }
}
