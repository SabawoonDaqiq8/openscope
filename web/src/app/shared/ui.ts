import { Component, computed, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

/** A headline number. Large standalone figures use proportional digits. */
@Component({
  selector: 'os-stat',
  template: `
    <div class="card p-4 h-full">
      <div class="flex items-center gap-2 text-sm text-muted">
        @if (swatch()) {
          <span class="swatch" [style.background]="swatch()"></span>
        }
        {{ label() }}
      </div>
      <div class="mt-1 text-2xl font-semibold tracking-tight">
        {{ value() }} <span class="text-sm font-normal text-muted">{{ unit() }}</span>
      </div>
      @if (hint()) {
        <div class="mt-1 text-xs text-muted">{{ hint() }}</div>
      }
    </div>
  `,
})
export class StatTile {
  readonly label = input.required<string>();
  readonly value = input.required<string>();
  readonly unit = input('');
  readonly hint = input('');
  readonly swatch = input('');
}

export type NoticeKind = 'info' | 'warning' | 'critical' | 'good';

/** Status message: colour never carries meaning alone (icon + label + text). */
@Component({
  selector: 'os-notice',
  template: `
    <div
      class="card flex items-start gap-3 px-4 py-3 text-sm"
      [attr.role]="kind() === 'critical' ? 'alert' : 'status'"
    >
      <span class="mt-0.5 font-semibold" [class]="tone()" aria-hidden="true">{{ icon() }}</span>
      <div>
        <span class="font-semibold" [class]="tone()">{{ title() }}</span>
        <span class="text-ink"> <ng-content /></span>
      </div>
    </div>
  `,
})
export class Notice {
  readonly kind = input<NoticeKind>('info');
  readonly title = input.required<string>();
  protected readonly icon = computed(
    () => ({ info: 'ⓘ', warning: '⚠', critical: '✕', good: '✓' })[this.kind()],
  );
  protected readonly tone = computed(
    () =>
      ({ info: 'text-muted', warning: 'text-warn', critical: 'text-crit', good: 'text-good' })[
        this.kind()
      ],
  );
}

/** Chart container with a title and a chart/table toggle (the accessible view). */
@Component({
  selector: 'os-chart-card',
  template: `
    <section class="card p-4 h-full flex flex-col">
      <header class="flex items-start justify-between gap-4 mb-3">
        <div>
          <h2 class="font-semibold">{{ title() }}</h2>
          @if (subtitle()) {
            <p class="text-sm text-muted">{{ subtitle() }}</p>
          }
        </div>
        <div class="flex rounded-lg border border-line text-xs overflow-hidden" role="group">
          <button
            type="button"
            class="px-2.5 py-1"
            [class.bg-surface-2]="!table()"
            [attr.aria-pressed]="!table()"
            (click)="table.set(false)"
          >
            Chart
          </button>
          <button
            type="button"
            class="px-2.5 py-1 border-l border-line"
            [class.bg-surface-2]="table()"
            [attr.aria-pressed]="table()"
            (click)="table.set(true)"
          >
            Table
          </button>
        </div>
      </header>
      <div class="flex-1 min-h-0">
        @if (table()) {
          <ng-content select="[table]" />
        } @else {
          <ng-content select="[chart]" />
        }
      </div>
    </section>
  `,
})
export class ChartCard {
  readonly title = input.required<string>();
  readonly subtitle = input('');
  protected readonly table = signal(false);
}

@Component({
  selector: 'os-empty',
  template: `
    <div class="card p-10 text-center">
      <h2 class="text-lg font-semibold">{{ title() }}</h2>
      <p class="mt-1 text-sm text-muted max-w-md mx-auto"><ng-content /></p>
      <div class="mt-5 flex justify-center gap-3"><ng-content select="[actions]" /></div>
    </div>
  `,
})
export class EmptyState {
  readonly title = input.required<string>();
}

/** The four-step workflow, shown on the overview so first-time visitors know where to go. */
@Component({
  selector: 'os-how-it-works',
  imports: [RouterLink],
  template: `
    <section aria-labelledby="how-title" class="mb-5">
      <h2 id="how-title" class="sr-only">How openscope works</h2>
      <ol class="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
        @for (s of steps(); track s.title; let i = $index) {
          <li class="card p-3 flex gap-3">
            <span
              class="shrink-0 w-6 h-6 rounded-full bg-accent-soft text-ink text-xs font-semibold grid place-items-center"
              aria-hidden="true"
              >{{ i + 1 }}</span
            >
            <div class="min-w-0">
              <div class="text-sm font-semibold">{{ s.title }}</div>
              <p class="text-xs text-muted mt-0.5">{{ s.text }}</p>
              <a class="text-xs underline mt-1 inline-block hover:text-ink" [routerLink]="s.link">{{
                s.cta
              }}</a>
            </div>
          </li>
        }
      </ol>
    </section>
  `,
})
export class HowItWorks {
  /** Link for step 1 (the current inventory's line explorer). */
  readonly linesLink = input<string | (string | number)[]>('/upload');
  protected readonly steps = computed(() => [
    {
      title: 'Measure',
      text: 'Scope 1–3 from activity data with official UK DESNZ and US EPA factors. Every number has an audit trail.',
      link: this.linesLink(),
      cta: 'Explore the calculations →',
    },
    {
      title: 'Classify',
      text: 'Purchase-ledger lines mapped to Scope 3 categories by rules, supplier memory and Claude, then human review.',
      link: '/review',
      cta: 'Open the review queue →',
    },
    {
      title: 'Plan',
      text: 'Abatement levers, a cost curve and science-based targets, with Monte Carlo uncertainty.',
      link: '/pathways',
      cta: 'Simulate a pathway →',
    },
    {
      title: 'Disclose',
      text: 'ESRS E1-6 and IFRS S2 emissions tables with readiness checks and exports.',
      link: '/disclosure',
      cta: 'Build the disclosure →',
    },
  ]);
}
