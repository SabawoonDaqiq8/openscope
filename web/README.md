# openscope web dashboard

Angular 22 (standalone components, signals, zoneless) + Tailwind CSS + Apache ECharts.

```bash
npm ci
npm start                  # http://localhost:4200, proxies /api to http://localhost:8000
npx ng test --watch=false  # unit tests (Vitest)
npx ng build               # production build → dist/web/browser
npm run gen:api            # regenerate src/app/api/schema.d.ts from the FastAPI spec
```

Structure: `api/` typed client · `core/` theme + formatting · `charts/` ECharts option
builders · `shared/` UI primitives · `pages/` routed views (lazy-loaded).
