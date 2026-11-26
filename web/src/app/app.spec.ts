import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { App } from './app';

describe('App shell', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
  });

  it('renders the brand and main navigation', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('openscope');
    const links = Array.from(el.querySelectorAll('nav a')).map((a) => a.textContent?.trim());
    expect(links).toEqual([
      'Overview',
      'Scope 3 review',
      'Pathways',
      'Disclosure',
      'Emission factors',
      'Upload',
    ]);
  });

  it('keeps the footer free of personal details and links', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const footer = (fixture.nativeElement as HTMLElement).querySelector('footer')!;
    expect(footer.textContent).toContain('open-source GHG Protocol carbon accounting');
    expect(footer.querySelectorAll('a')).toHaveLength(0);
  });

  it('shows the public-demo banner only when the server is a public demo', async () => {
    const fixture = TestBed.createComponent(App);
    const http = TestBed.inject(HttpTestingController);
    http.expectOne('/api/meta').flush({ public_demo: true });
    await fixture.whenStable();
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Public demo.');
  });
});
