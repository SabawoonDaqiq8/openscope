import { DOCUMENT } from '@angular/common';
import { Injectable, computed, inject, signal } from '@angular/core';

export type ThemeChoice = 'system' | 'light' | 'dark';

export interface ChartTokens {
  surface: string;
  textPrimary: string;
  textSecondary: string;
  grid: string;
  axis: string;
  border: string;
  scope: [string, string, string];
  seq: string;
}

const STORAGE_KEY = 'openscope.theme';

function readStorage(): ThemeChoice {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system';
  }
}

/**
 * Tracks the active colour scheme and exposes the CSS design tokens as plain values,
 * because canvas charts cannot read CSS custom properties themselves.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly doc = inject(DOCUMENT);
  private readonly media = this.doc.defaultView?.matchMedia?.('(prefers-color-scheme: dark)');
  private readonly osDark = signal(this.media?.matches ?? false);

  readonly choice = signal<ThemeChoice>(readStorage());
  readonly mode = computed(() => {
    const c = this.choice();
    return c === 'system' ? (this.osDark() ? 'dark' : 'light') : c;
  });

  /** Recomputed whenever the mode changes, so charts re-render with the right palette. */
  readonly tokens = computed<ChartTokens>(() => {
    this.mode(); // dependency: re-read tokens whenever the scheme changes
    const css = this.doc.defaultView?.getComputedStyle(this.doc.documentElement);
    const v = (name: string, fallback: string) => css?.getPropertyValue(name).trim() || fallback;
    return {
      surface: v('--surface', '#ffffff'),
      textPrimary: v('--text-primary', '#191919'),
      textSecondary: v('--text-secondary', '#666666'),
      grid: v('--grid', '#e7e7e7'),
      axis: v('--axis', '#c2c2c2'),
      border: v('--border', 'rgba(11,11,11,0.1)'),
      scope: [v('--scope-1', '#257de0'), v('--scope-2', '#f47230'), v('--scope-3', '#00b894')],
      seq: v('--seq', '#257de0'),
    };
  });

  constructor() {
    this.media?.addEventListener?.('change', (e) => this.osDark.set(e.matches));
    this.apply();
  }

  set(choice: ThemeChoice): void {
    this.choice.set(choice);
    try {
      localStorage.setItem(STORAGE_KEY, choice);
    } catch {
      /* storage unavailable: keep the choice for this session only */
    }
    this.apply();
  }

  private apply(): void {
    const root = this.doc.documentElement;
    const c = this.choice();
    if (c === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', c);
  }
}
