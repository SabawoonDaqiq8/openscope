import { Component, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { ApiService } from './api/api.service';
import { ThemeChoice, ThemeService } from './core/theme.service';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <a href="#main" class="sr-only focus:not-sr-only focus:absolute focus:p-2">Skip to content</a>
    <header class="border-b border-line bg-surface">
      <div
        class="mx-auto max-w-7xl px-4 py-2 md:py-0 md:h-14 flex flex-wrap md:flex-nowrap items-center gap-x-6 gap-y-2"
      >
        <a routerLink="/" class="flex items-center gap-2 font-semibold tracking-tight">
          <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="10" fill="none" stroke="var(--accent)" stroke-width="2" />
            <circle cx="12" cy="12" r="5.5" fill="none" stroke="var(--accent)" stroke-width="2" />
            <circle cx="12" cy="12" r="1.8" fill="var(--accent)" />
          </svg>
          openscope
        </a>
        <div class="ml-auto md:order-last flex items-center gap-2">
          <label for="theme" class="sr-only">Theme</label>
          <select
            id="theme"
            class="input text-xs py-1"
            [value]="theme.choice()"
            (change)="theme.set($any($event.target).value)"
          >
            @for (c of themes; track c) {
              <option [value]="c">
                {{ c === 'system' ? 'Auto' : c === 'light' ? 'Light' : 'Dark' }}
              </option>
            }
          </select>
          <a class="btn text-xs py-1 whitespace-nowrap" href="/docs" target="_blank" rel="noopener"
            ><span>API<span class="hidden sm:inline">&nbsp;docs</span></span></a
          >
        </div>
        <nav
          class="w-full md:w-auto order-last md:order-none flex gap-1 text-sm overflow-x-auto -mx-1 px-1 pb-1 md:pb-0"
          aria-label="Main"
        >
          @for (item of nav; track item.path) {
            <a
              [routerLink]="item.path"
              routerLinkActive="bg-accent-soft text-ink font-medium"
              [routerLinkActiveOptions]="{ exact: false }"
              class="px-3 py-1.5 rounded-md text-muted hover:text-ink whitespace-nowrap"
              >{{ item.label }}</a
            >
          }
        </nav>
      </div>
    </header>
    @if (publicDemo()) {
      <aside class="border-b border-line bg-accent-soft text-sm" aria-label="Public demo notice">
        <div class="mx-auto max-w-7xl px-4 py-2">
          <b>Public demo.</b> Anyone can see what is uploaded here and data resets regularly. Do not
          upload confidential data.
          <a
            class="underline"
            href="https://github.com/SabawoonDaqiq8/openscope"
            target="_blank"
            rel="noopener"
            >Source on GitHub</a
          >
        </div>
      </aside>
    }
    <main id="main" class="mx-auto max-w-7xl px-4 py-6">
      <router-outlet />
    </main>
    <footer class="mx-auto max-w-7xl px-4 pb-8 text-xs text-muted">
      openscope · open-source GHG Protocol carbon accounting · MIT License
    </footer>
  `,
})
export class App {
  protected readonly theme = inject(ThemeService);
  protected readonly repo = 'https://github.com/SabawoonDaqiq8/openscope';
  protected readonly publicDemo = signal(false);

  constructor() {
    inject(ApiService)
      .meta()
      .subscribe({ next: (m) => this.publicDemo.set(m.public_demo), error: () => undefined });
  }
  protected readonly themes: ThemeChoice[] = ['system', 'light', 'dark'];
  protected readonly nav = [
    { path: '/overview', label: 'Overview' },
    { path: '/review', label: 'Scope 3 review' },
    { path: '/pathways', label: 'Pathways' },
    { path: '/disclosure', label: 'Disclosure' },
    { path: '/factors', label: 'Emission factors' },
    { path: '/upload', label: 'Upload' },
  ];
}
