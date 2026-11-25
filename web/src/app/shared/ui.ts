import { Component, computed, input, signal } from '@angular/core';

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
