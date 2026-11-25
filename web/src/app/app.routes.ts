import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'overview' },
  {
    path: 'overview',
    title: 'Overview · openscope',
    loadComponent: () => import('./pages/overview').then((m) => m.OverviewPage),
  },
  {
    path: 'overview/:id',
    title: 'Inventory · openscope',
    loadComponent: () => import('./pages/overview').then((m) => m.OverviewPage),
  },
  {
    path: 'overview/:id/lines',
    title: 'Line explorer · openscope',
    loadComponent: () => import('./pages/lines').then((m) => m.LinesPage),
  },
  {
    path: 'review',
    title: 'Scope 3 review · openscope',
    loadComponent: () => import('./pages/review').then((m) => m.ReviewPage),
  },
  {
    path: 'review/:runId',
    title: 'Scope 3 review · openscope',
    loadComponent: () => import('./pages/review').then((m) => m.ReviewPage),
  },
  {
    path: 'factors',
    title: 'Emission factors · openscope',
    loadComponent: () => import('./pages/factors').then((m) => m.FactorsPage),
  },
  {
    path: 'upload',
    title: 'Upload · openscope',
    loadComponent: () => import('./pages/upload').then((m) => m.UploadPage),
  },
  { path: '**', redirectTo: 'overview' },
];
