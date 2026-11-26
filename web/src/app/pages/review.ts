import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import {
  ApiService,
  Audit,
  Factor,
  Meta,
  ReviewIn,
  Run,
  RunLine,
  errorMessage,
} from '../api/api.service';
import { STATUS_LABELS, money, percent } from '../core/format';
import { EmptyState, Notice } from '../shared/ui';

const REVIEWER_KEY = 'openscope.reviewer';
const STATUSES = ['needs_review', 'auto_accepted', 'reviewed', 'excluded'] as const;

function storedReviewer(): string {
  try {
    return localStorage.getItem(REVIEWER_KEY) ?? '';
  } catch {
    return '';
  }
}

@Component({
  selector: 'os-review',
  imports: [RouterLink, Notice, EmptyState],
  template: `
    @if (loaded() && runs().length === 0) {
      <os-empty title="No classification runs yet">
        Upload a purchase-ledger export to classify it into Scope 3 categories, or load the demo
        ledger.
        <ng-container actions>
          <button class="btn btn-primary" (click)="loadDemo()">Load demo data</button>
          <a class="btn" routerLink="/upload">Upload ledger</a>
        </ng-container>
      </os-empty>
    } @else if (run(); as r) {
      <h1 class="text-xl font-semibold mb-3">Scope 3 review</h1>
      <div class="flex flex-wrap items-end justify-between gap-3 mb-4">
        <div class="w-full sm:w-auto">
          <label for="run" class="block text-xs text-muted mb-1">Classification run</label>
          <select
            id="run"
            class="input w-full sm:w-auto sm:min-w-72"
            [value]="r.id"
            (change)="selectRun($event)"
          >
            @for (x of runs(); track x.id) {
              <option [value]="x.id">{{ x.name }}</option>
            }
          </select>
        </div>
        <div class="flex flex-wrap items-end gap-2 w-full sm:w-auto">
          <div>
            <label for="reviewer" class="block text-xs text-muted mb-1"
              >Reviewer (for the audit log)</label
            >
            <input
              id="reviewer"
              class="input w-48"
              [value]="reviewer()"
              placeholder="Your name"
              (input)="setReviewer($any($event.target).value)"
            />
          </div>
          <button class="btn btn-primary" (click)="exportRun(r)" [disabled]="busy()">
            Export accepted → inventory
          </button>
        </div>
      </div>

      @if (error()) {
        <div class="mb-4">
          <os-notice kind="critical" title="Action failed.">{{ error() }}</os-notice>
        </div>
      }
      @if (failedBatches(r) > 0) {
        <div class="mb-4">
          <os-notice kind="warning" title="Some model batches failed.">
            Their lines were left for review rather than guessed.
          </os-notice>
        </div>
      }

      <div
        class="grid gap-3 grid-cols-2 lg:grid-cols-4 mb-4"
        role="tablist"
        aria-label="Line status"
      >
        @for (s of statuses; track s) {
          <button
            role="tab"
            class="card p-3 text-left"
            [attr.aria-selected]="status() === s"
            [class.ring-2]="status() === s"
            [class.ring-accent]="status() === s"
            (click)="status.set(s)"
          >
            <div class="text-sm text-muted">{{ label(s) }}</div>
            <div class="text-xl font-semibold num">{{ r.by_status[s] ?? 0 }}</div>
            <div class="text-xs text-muted num">{{ spendShare(r, s) }} of spend</div>
          </button>
        }
      </div>

      <div class="card overflow-x-auto mb-6">
        <table class="data">
          <thead>
            <tr>
              <th>Ledger line</th>
              <th class="text-right">Amount</th>
              <th>Proposal</th>
              <th class="text-right">Conf.</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            @for (l of lines(); track l.line_id) {
              <tr>
                <td class="max-w-sm">
                  <div class="font-medium">{{ l.supplier || '—' }}</div>
                  <div>{{ l.description }}</div>
                  <div class="text-xs text-muted">
                    {{ l.line_id }} · {{ l.account }} {{ l.account_name }}
                  </div>
                </td>
                <td class="text-right num whitespace-nowrap">{{ cash(l.amount, l.currency) }}</td>
                <td class="max-w-xs">
                  @if (l.decision === 'exclude') {
                    <div>Exclude</div>
                  } @else if (l.scope3_category) {
                    <div>Cat {{ l.scope3_category }} · {{ categoryLabel(l.scope3_category) }}</div>
                    <div class="font-mono text-xs text-muted">{{ l.factor_id || 'no factor' }}</div>
                  } @else {
                    <div class="text-muted">No proposal</div>
                  }
                  <div class="text-xs text-muted mt-0.5">{{ l.source }} · {{ l.rationale }}</div>
                </td>
                <td class="text-right num">{{ l.source === 'none' ? '–' : pct(l.confidence) }}</td>
                <td class="whitespace-nowrap">
                  @if (editing() === l.line_id) {
                    <form
                      class="flex flex-col gap-1.5 w-72"
                      (submit)="$event.preventDefault(); submitOverride(r, l)"
                    >
                      <select
                        class="input"
                        aria-label="Scope 3 category"
                        required
                        (change)="ovCategory.set($any($event.target).value)"
                      >
                        <option value="">Category…</option>
                        @for (c of meta()?.scope3_categories ?? []; track c.value) {
                          <option [value]="c.value" [selected]="String(c.value) === ovCategory()">
                            {{ c.value }}. {{ c.label }}
                          </option>
                        }
                      </select>
                      <input
                        class="input"
                        list="factor-options"
                        aria-label="Emission factor"
                        placeholder="Search factor (e.g. hotels, software)"
                        required
                        [value]="ovFactor()"
                        (input)="ovFactor.set($any($event.target).value.trim())"
                      />
                      <datalist id="factor-options">
                        @for (f of factorsFor(ovCategory()); track f.factor_id) {
                          <option [value]="f.factor_id">{{ f.name }}</option>
                        }
                      </datalist>
                      <div class="text-xs text-muted min-h-4" role="status" aria-live="polite">
                        {{ factorName(ovFactor()) }}
                      </div>
                      <input
                        class="input"
                        placeholder="Note (why)"
                        aria-label="Note"
                        (input)="ovNote.set($any($event.target).value)"
                      />
                      <div class="flex gap-1.5">
                        <button
                          class="btn btn-primary"
                          type="submit"
                          [disabled]="!ovCategory() || !ovFactor()"
                        >
                          Save
                        </button>
                        <button class="btn" type="button" (click)="editing.set(null)">
                          Cancel
                        </button>
                      </div>
                    </form>
                  } @else {
                    <div class="flex gap-1.5">
                      @if (canAccept(l)) {
                        <button class="btn" (click)="act(r, l, { action: 'accept' })">
                          Accept
                        </button>
                      }
                      <button class="btn" (click)="startOverride(l)">Override</button>
                      @if (l.decision !== 'exclude' || l.source !== 'reviewer') {
                        <button class="btn" (click)="act(r, l, { action: 'exclude' })">
                          Exclude
                        </button>
                      }
                    </div>
                  }
                </td>
              </tr>
            } @empty {
              <tr>
                <td colspan="5" class="text-center text-muted py-8">Nothing here.</td>
              </tr>
            }
          </tbody>
        </table>
      </div>

      <section class="card p-4 min-w-0">
        <h2 class="font-semibold mb-1">Audit log</h2>
        <p class="text-sm text-muted mb-3">Every reviewer decision, newest first.</p>
        <div class="overflow-x-auto">
          <table class="data">
            <thead>
              <tr>
                <th>When</th>
                <th>Reviewer</th>
                <th>Line</th>
                <th>Action</th>
                <th>Change</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              @for (a of audit(); track a.id) {
                <tr>
                  <td class="whitespace-nowrap text-xs num">
                    {{ a.timestamp.replace('T', ' ').slice(0, 19) }}
                  </td>
                  <td>{{ a.reviewer }}</td>
                  <td class="font-mono text-xs">{{ a.line_id }}</td>
                  <td>{{ a.action }}</td>
                  <td class="text-xs">
                    {{ describe(a.before) }} → <b>{{ describe(a.after) }}</b>
                  </td>
                  <td class="text-xs">{{ a.note }}</td>
                </tr>
              } @empty {
                <tr>
                  <td colspan="6" class="text-center text-muted py-6">No decisions yet.</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      </section>
    } @else {
      <p class="text-muted">Loading…</p>
    }
  `,
})
export class ReviewPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  readonly runId = input<string>();

  protected readonly statuses = STATUSES;
  protected readonly String = String;
  protected readonly runs = signal<Run[]>([]);
  protected readonly run = signal<Run | null>(null);
  protected readonly lines = signal<RunLine[]>([]);
  protected readonly audit = signal<Audit[]>([]);
  protected readonly meta = signal<Meta | null>(null);
  protected readonly spendFactors = signal<Factor[]>([]);
  protected readonly status = signal<string>('needs_review');
  protected readonly loaded = signal(false);
  protected readonly busy = signal(false);
  protected readonly error = signal('');
  protected readonly reviewer = signal(storedReviewer());

  protected readonly editing = signal<string | null>(null);
  protected readonly ovCategory = signal('');
  protected readonly ovFactor = signal('');
  protected readonly ovNote = signal('');

  private readonly categories = computed(
    () => new Map((this.meta()?.scope3_categories ?? []).map((c) => [c.value, c.label])),
  );

  protected readonly pct = percent;
  protected readonly cash = money;

  constructor() {
    this.api.meta().subscribe((m) => this.meta.set(m));
    this.api
      .factors({ spend_only: true, limit: 2000 })
      .subscribe((p) => this.spendFactors.set(p.items));
    effect(() => this.loadRuns(this.runId()));
    effect(() => {
      const r = this.run();
      const s = this.status();
      if (r) this.loadLines(r.id, s);
    });
  }

  protected label(s: string): string {
    return STATUS_LABELS[s] ?? s;
  }
  protected categoryLabel(c: number): string {
    return this.categories().get(c) ?? '';
  }
  protected spendShare(r: Run, s: string): string {
    const total = Object.values(r.spend_by_status).reduce((a, b) => a + b, 0) || 1;
    return percent((r.spend_by_status[s] ?? 0) / total);
  }
  protected failedBatches(r: Run): number {
    const f = r.llm_usage['failed_batches'];
    return Array.isArray(f) ? f.length : 0;
  }
  protected canAccept(l: RunLine): boolean {
    if (l.source === 'reviewer') return false;
    return l.decision === 'exclude' || (l.decision === 'classify' && !!l.factor_id);
  }
  protected factorName(id: string): string {
    if (!id) return '';
    return this.spendFactors().find((f) => f.factor_id === id)?.name ?? 'Unknown factor id';
  }
  protected factorsFor(category: string): Factor[] {
    const c = Number(category);
    const all = this.spendFactors();
    const matching = all.filter((f) => f.scope3_category === c);
    return matching.length ? [...matching, ...all.filter((f) => f.scope3_category !== c)] : all;
  }
  protected describe(c: Record<string, unknown>): string {
    if (c['decision'] === 'exclude') return 'exclude';
    if (c['scope3_category']) return `cat ${c['scope3_category']} · ${c['factor_id'] ?? '—'}`;
    return String(c['decision'] ?? '');
  }

  protected setReviewer(v: string): void {
    this.reviewer.set(v);
    try {
      localStorage.setItem(REVIEWER_KEY, v);
    } catch {
      /* storage unavailable */
    }
  }

  protected selectRun(ev: Event): void {
    this.router.navigate(['/review', (ev.target as HTMLSelectElement).value]);
  }

  protected startOverride(l: RunLine): void {
    this.ovCategory.set(l.scope3_category ? String(l.scope3_category) : '');
    this.ovFactor.set(l.factor_id ?? '');
    this.ovNote.set('');
    this.editing.set(l.line_id);
  }

  protected submitOverride(r: Run, l: RunLine): void {
    this.act(r, l, {
      action: 'override',
      scope3_category: Number(this.ovCategory()),
      factor_id: this.ovFactor(),
      note: this.ovNote(),
    });
  }

  protected act(
    r: Run,
    l: RunLine,
    body: Pick<ReviewIn, 'action'> & Partial<Omit<ReviewIn, 'reviewer' | 'action'>>,
  ): void {
    const reviewer = this.reviewer().trim();
    if (!reviewer) {
      this.error.set(
        'Enter your name as reviewer first: every decision is recorded in the audit log.',
      );
      return;
    }
    this.error.set('');
    this.api.review(r.id, l.line_id, { ...body, reviewer, note: body.note ?? '' }).subscribe({
      next: () => {
        this.editing.set(null);
        this.refresh(r.id);
      },
      error: (e) => this.error.set(errorMessage(e)),
    });
  }

  protected exportRun(r: Run): void {
    this.busy.set(true);
    this.api.exportRun(r.id, `${r.name} (spend-based)`).subscribe({
      next: (res) => {
        this.busy.set(false);
        this.router.navigate(['/overview', res.inventory_id]);
      },
      error: (e) => {
        this.busy.set(false);
        this.error.set(errorMessage(e));
      },
    });
  }

  protected loadDemo(): void {
    this.api.demo().subscribe({
      next: (d) => this.router.navigate(['/review', d.run_id]),
      error: (e) => this.error.set(errorMessage(e)),
    });
  }

  private loadRuns(id: string | undefined): void {
    this.api.runs().subscribe({
      next: (list) => {
        this.runs.set(list);
        this.loaded.set(true);
        const target = list.find((x) => String(x.id) === id) ?? list[0];
        if (target) this.refresh(target.id);
      },
      error: (e) => this.error.set(errorMessage(e)),
    });
  }

  private refresh(id: number): void {
    this.api.run(id).subscribe((r) => this.run.set(r));
    this.api.audit(id).subscribe((a) => this.audit.set(a));
  }

  private loadLines(id: number, status: string): void {
    this.api.runLines(id, status).subscribe({
      next: (ls) => this.lines.set(ls),
      error: (e) => this.error.set(errorMessage(e)),
    });
  }
}
