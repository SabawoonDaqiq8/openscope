import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import type { components } from './schema';

/** Types generated from the FastAPI OpenAPI spec (`npm run gen:api`). */
export type Schemas = components['schemas'];
export type Meta = Schemas['Meta'];
export type FactorPage = Schemas['FactorPage'];
export type Factor = Schemas['FactorOut'];
export type InventorySummary = Schemas['InventoryOut'];
export type InventoryDetail = Schemas['InventoryDetail'];
export type Line = Schemas['LineOut'];
export type Run = Schemas['RunOut'];
export type RunLine = Schemas['RunLineOut'];
export type ReviewIn = Schemas['ReviewIn'];
export type Audit = Schemas['AuditOut'];
export type ExportOut = Schemas['ExportOut'];
export type DemoOut = Schemas['DemoOut'];

function params(values: Record<string, string | number | boolean | null | undefined>) {
  let p = new HttpParams();
  for (const [k, v] of Object.entries(values)) {
    if (v !== null && v !== undefined && v !== '') p = p.set(k, String(v));
  }
  return p;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api';

  meta(): Observable<Meta> {
    return this.http.get<Meta>(`${this.base}/meta`);
  }

  factors(q: {
    search?: string;
    scope?: number | null;
    spend_only?: boolean;
    limit?: number;
    offset?: number;
  }): Observable<FactorPage> {
    return this.http.get<FactorPage>(`${this.base}/factors`, { params: params(q) });
  }

  inventories(): Observable<InventorySummary[]> {
    return this.http.get<InventorySummary[]>(`${this.base}/inventories`);
  }

  inventory(id: number): Observable<InventoryDetail> {
    return this.http.get<InventoryDetail>(`${this.base}/inventories/${id}`);
  }

  lines(id: number, scope?: number | null): Observable<Line[]> {
    return this.http.get<Line[]>(`${this.base}/inventories/${id}/lines`, {
      params: params({ scope }),
    });
  }

  uploadInventory(
    file: File,
    form: { name: string; gwp_set: string; reporting_year?: number | null },
  ): Observable<InventoryDetail> {
    const body = new FormData();
    body.append('file', file);
    body.append('name', form.name);
    body.append('gwp_set', form.gwp_set);
    if (form.reporting_year) body.append('reporting_year', String(form.reporting_year));
    return this.http.post<InventoryDetail>(`${this.base}/inventories`, body);
  }

  deleteInventory(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/inventories/${id}`);
  }

  runs(): Observable<Run[]> {
    return this.http.get<Run[]>(`${this.base}/classification-runs`);
  }

  run(id: number): Observable<Run> {
    return this.http.get<Run>(`${this.base}/classification-runs/${id}`);
  }

  runLines(id: number, status?: string | null): Observable<RunLine[]> {
    return this.http.get<RunLine[]>(`${this.base}/classification-runs/${id}/lines`, {
      params: params({ status }),
    });
  }

  uploadLedger(
    file: File,
    form: { name: string; threshold: number; use_llm: boolean; currency?: string },
  ): Observable<Run> {
    const body = new FormData();
    body.append('file', file);
    body.append('name', form.name);
    body.append('threshold', String(form.threshold));
    body.append('use_llm', String(form.use_llm));
    if (form.currency) body.append('currency', form.currency);
    return this.http.post<Run>(`${this.base}/classification-runs`, body);
  }

  review(runId: number, lineId: string, body: ReviewIn): Observable<RunLine> {
    return this.http.post<RunLine>(
      `${this.base}/classification-runs/${runId}/lines/${encodeURIComponent(lineId)}/review`,
      body,
    );
  }

  audit(runId: number): Observable<Audit[]> {
    return this.http.get<Audit[]>(`${this.base}/classification-runs/${runId}/audit`);
  }

  exportRun(runId: number, name: string): Observable<ExportOut> {
    return this.http.post<ExportOut>(`${this.base}/classification-runs/${runId}/export`, {
      name,
    });
  }

  demo(): Observable<DemoOut> {
    return this.http.post<DemoOut>(`${this.base}/demo`, {});
  }
}

/** Pull a readable message out of an HttpErrorResponse. */
export function errorMessage(err: unknown): string {
  const e = err as { error?: { detail?: unknown }; message?: string; status?: number };
  const detail = e?.error?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg ?? String(d)).join('; ');
  if (e?.status === 0) return 'Cannot reach the openscope API. Is the server running?';
  return e?.message ?? 'Something went wrong';
}
