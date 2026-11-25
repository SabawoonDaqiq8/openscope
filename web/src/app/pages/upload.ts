import { Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';

import { ApiService, Meta, errorMessage } from '../api/api.service';
import { Notice } from '../shared/ui';

@Component({
  selector: 'os-upload',
  imports: [Notice],
  template: `
    <h1 class="text-xl font-semibold">Upload data</h1>
    <p class="text-sm text-muted mb-5">CSV files up to 10 MB. Nothing leaves this server.</p>

    @if (error()) {
      <div class="mb-4">
        <os-notice kind="critical" title="Upload failed.">{{ error() }}</os-notice>
      </div>
    }

    <div class="grid gap-4 lg:grid-cols-2">
      <form class="card p-5 space-y-3" (submit)="$event.preventDefault(); uploadActivities()">
        <h2 class="font-semibold">Activity data → inventory</h2>
        <p class="text-sm text-muted">
          Columns: <code class="text-xs">activity_id, quantity, unit, scope, factor_id</code>, plus
          optional
          <code class="text-xs">scope3_category, scope2_method, method, site, description…</code>
          Factors resolve against the server's datasets.
        </p>
        <label class="block text-sm"
          >Name
          <input
            class="input w-full mt-1"
            required
            [value]="invName()"
            (input)="invName.set($any($event.target).value)"
          />
        </label>
        <div class="flex gap-3">
          <label class="block text-sm"
            >GWP set
            <select class="input mt-1 block" (change)="gwp.set($any($event.target).value)">
              <option value="AR6">AR6</option>
              <option value="AR5">AR5</option>
            </select>
          </label>
          <label class="block text-sm"
            >Reporting year
            <input
              class="input mt-1 w-28 block"
              type="number"
              min="1990"
              max="2100"
              [value]="year()"
              (input)="year.set($any($event.target).valueAsNumber)"
            />
          </label>
        </div>
        <input
          type="file"
          accept=".csv,text/csv"
          aria-label="Activities CSV"
          required
          (change)="actFile.set($any($event.target).files?.[0] ?? null)"
        />
        <div>
          <button class="btn btn-primary" type="submit" [disabled]="busy() || !actFile()">
            Calculate inventory
          </button>
        </div>
      </form>

      <form class="card p-5 space-y-3" (submit)="$event.preventDefault(); uploadLedger()">
        <h2 class="font-semibold">Purchase ledger → Scope 3 classification</h2>
        <p class="text-sm text-muted">
          An AP / GL export. Common ERP column names are recognised (<code class="text-xs"
            >Vendor, Memo, GL Code, Net Amount, Currency…</code
          >).
        </p>
        <label class="block text-sm"
          >Name
          <input
            class="input w-full mt-1"
            required
            [value]="runName()"
            (input)="runName.set($any($event.target).value)"
          />
        </label>
        <div class="flex gap-3">
          <label class="block text-sm"
            >Auto-accept confidence
            <input
              class="input mt-1 w-28 block"
              type="number"
              min="0"
              max="1"
              step="0.05"
              [value]="threshold()"
              (input)="threshold.set($any($event.target).valueAsNumber)"
            />
          </label>
          <label class="block text-sm"
            >Currency (if no column)
            <input
              class="input mt-1 w-24 block"
              maxlength="3"
              placeholder="USD"
              (input)="currency.set($any($event.target).value.toUpperCase())"
            />
          </label>
        </div>
        <label class="flex items-center gap-2 text-sm" [class.text-muted]="!meta()?.llm_enabled">
          <input
            type="checkbox"
            [disabled]="!meta()?.llm_enabled"
            [checked]="useLlm()"
            (change)="useLlm.set($any($event.target).checked)"
          />
          Classify remaining lines with Claude
          @if (!meta()?.llm_enabled) {
            <span class="text-xs">(not enabled on this server)</span>
          }
        </label>
        <input
          type="file"
          accept=".csv,text/csv"
          aria-label="Ledger CSV"
          required
          (change)="ledgerFile.set($any($event.target).files?.[0] ?? null)"
        />
        <div>
          <button class="btn btn-primary" type="submit" [disabled]="busy() || !ledgerFile()">
            Classify ledger
          </button>
        </div>
      </form>
    </div>
  `,
})
export class UploadPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);

  protected readonly meta = signal<Meta | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal('');

  protected readonly invName = signal('My inventory');
  protected readonly gwp = signal('AR6');
  protected readonly year = signal<number | null>(new Date().getFullYear() - 1);
  protected readonly actFile = signal<File | null>(null);

  protected readonly runName = signal('Purchase ledger');
  protected readonly threshold = signal(0.85);
  protected readonly currency = signal('');
  protected readonly useLlm = signal(false);
  protected readonly ledgerFile = signal<File | null>(null);

  constructor() {
    this.api.meta().subscribe((m) => this.meta.set(m));
  }

  protected uploadActivities(): void {
    const file = this.actFile();
    if (!file) return;
    this.start();
    this.api
      .uploadInventory(file, {
        name: this.invName(),
        gwp_set: this.gwp(),
        reporting_year: this.year(),
      })
      .subscribe({
        next: (d) => this.done(['/overview', String(d.id)]),
        error: (e) => this.fail(e),
      });
  }

  protected uploadLedger(): void {
    const file = this.ledgerFile();
    if (!file) return;
    this.start();
    this.api
      .uploadLedger(file, {
        name: this.runName(),
        threshold: this.threshold(),
        use_llm: this.useLlm(),
        currency: this.currency() || undefined,
      })
      .subscribe({
        next: (r) => this.done(['/review', String(r.id)]),
        error: (e) => this.fail(e),
      });
  }

  private start(): void {
    this.busy.set(true);
    this.error.set('');
  }
  private done(route: string[]): void {
    this.busy.set(false);
    this.router.navigate(route);
  }
  private fail(e: unknown): void {
    this.busy.set(false);
    this.error.set(errorMessage(e));
  }
}
