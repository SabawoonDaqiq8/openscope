import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import type { Line } from '../api/api.service';
import { LinesPage } from './lines';

const line = (over: Partial<Line>): Line => ({
  activity_id: 'A1',
  description: 'Boiler gas',
  site: 'HQ',
  supplier: null,
  scope: 1,
  scope3_category: null,
  scope2_method: null,
  method: 'average_data',
  quantity: 100,
  unit: 'kWh',
  factor_id: 'F1',
  factor_source: 'DESNZ',
  factor_status: 'reference',
  gwp_set: 'AR6',
  co2e_kg: 18.3,
  data_quality_score: 3,
  trace: ['Factor F1', 'Total: 18.3 kg CO2e'],
  ...over,
});

describe('LinesPage', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [LinesPage],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
  });

  async function render() {
    const fixture = TestBed.createComponent(LinesPage);
    fixture.componentRef.setInput('id', '7');
    fixture.detectChanges();
    TestBed.inject(HttpTestingController)
      .expectOne('/api/inventories/7/lines')
      .flush([
        line({}),
        line({
          activity_id: 'B2',
          description: 'Flights',
          scope: 3,
          scope3_category: 6,
          factor_status: 'illustrative',
          trace: ['Factor X', 'WARNING: illustrative factor'],
        }),
      ]);
    await fixture.whenStable();
    fixture.detectChanges();
    return fixture;
  }

  it('lists lines, flags illustrative factors and filters by search', async () => {
    const fixture = await render();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelectorAll('tbody tr')).toHaveLength(2);
    expect(el.textContent).toContain('⚠ illustrative');

    const search = el.querySelector('input') as HTMLInputElement;
    search.value = 'flights';
    search.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    fixture.detectChanges();
    expect(el.querySelectorAll('tbody tr')).toHaveLength(1);
  });

  it('expands the audit trail of a row', async () => {
    const fixture = await render();
    const el = fixture.nativeElement as HTMLElement;
    (el.querySelector('tbody tr') as HTMLElement).click();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(el.querySelectorAll('ol li')).toHaveLength(2);
    expect(el.textContent).toContain('Total: 18.3 kg CO2e');
  });
});
