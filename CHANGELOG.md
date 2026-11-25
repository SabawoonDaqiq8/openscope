# Changelog

## 0.6.0
### Added
- `openscope.pathway`: decarbonisation pathway simulator with abatement levers (selectors,
  ramps, capex/opex/lifetime), merit-ordered marginal abatement cost curve without double
  counting, science-based target trajectories set separately for Scope 1+2 and Scope 3, and
  Monte Carlo uncertainty (P10/P50/P90, probability of meeting each target)
- `openscope pathway` CLI command; demo scenario `examples/pathway_demo_scenario.json`
  (illustrative assumptions)
- API: `POST /api/inventories/{id}/pathway`, `GET /api/pathway/demo-scenario`
- Dashboard **Pathways** page: scenario and lever editor (saved per inventory in the browser),
  target status tiles, trajectory chart with uncertainty band, MACC, lever table

## 0.5.0
### Added
- Bundled `useeio-1.3` dataset: US EPA Supply Chain GHG Emission Factors v1.3.0 (1,016 NAICS-6
  spend-based factors, kg per gas per 2022 USD), reconciled against EPA's published CO2e
- `openscope import-useeio` importer
- GWPs for all gases in the EPA dataset (HFC-23, HFC-143a, HFC-236fa, CF4, C2F6, C3F8, c-C4F8,
  C4F10, C6F14) and a `CO2E` pseudo-gas for components published only as CO2e
- The API serves `desnz-2025` and `useeio-1.3` by default; the demo's classification rules use
  real EPA factors, so the demo no longer depends on illustrative spend factors
- Searchable factor picker in the review queue; gzip responses

### Fixed
- SF6 AR6 GWP corrected from 24,300 to 25,200 (IPCC AR6 WG1 Table 7.SM.7)

### Changed
- The classifier's response schema lists factor ids as an enum only for catalogues of up to 200
  factors; larger catalogues use a string, still validated against the registry

## 0.4.1
### Added
- Public demo mode (`OPENSCOPE_PUBLIC_DEMO=1`): demo data loaded at startup, banner warning
  that data is public and temporary
- `render.yaml` Blueprint and deployment guide; "Deploy to Render" button
- Docker image listens on `$PORT`; CI smoke-tests the image with Render's settings

## 0.4.0
### Added
- REST API (`openscope.api`, FastAPI): inventories, line-level results with audit trails,
  factor search, classification runs, per-line review with audit log and supplier memory,
  export of reviewed spend to an inventory, demo loader; OpenAPI docs at `/docs`
- Persistence with SQLAlchemy (SQLite by default)
- Angular 22 dashboard (`web/`): overview with KPI tiles and charts, line explorer,
  Scope 3 review queue, factor browser, uploads; light/dark themes; chart/table toggles
- TypeScript client types generated from the OpenAPI spec (`npm run gen:api`), checked in CI
- Dockerfile (single image serving API + dashboard); CI builds and smoke-tests it
- Optional extra `openscope[api]`

### Changed
- Scope 3 category labels use the official GHG Protocol names

## 0.3.0
### Added
- `openscope classify`: hybrid ledger classification. Rules and supplier memory run first,
  then Claude (structured output limited to registry factor ids, batched, prompt-cached,
  low effort, server-side refusal fallbacks), then a confidence gate
- `openscope review-apply`: review CSV round-trip with validation, append-only JSONL audit
  log, supplier-memory learning, export to spend-based activities
- Bundled exclusion rules (payroll, tax, depreciation, finance, intercompany, donations, refunds)
- Evaluation (`--labels`): accuracy, coverage, auto-accept precision, per-category P/R
- Example 40-line ledger with labels, example rules, illustrative spend factors
- Optional extra `openscope[ai]`

## 0.2.0
### Added
- `openscope import-desnz`: importer for the UK DESNZ flat-format conversion factors workbook
- Bundled `desnz-2025` dataset (2,672 factors); `--dataset` option and `openscope datasets`
- Per-gas DESNZ factors are converted back to gas mass, so they can be recalculated under AR6
- `gwp_basis` on pre-aggregated factors, with a trace warning on mismatch
- Spend normalisation (`--fx`, `--price-index`): currency conversion + price-year deflation
- `price_year` on activities; `site` on results
- Market-based Scope 2 grid-average fallback for sites without market-based data
- UK demo inventory using only reference factors; units `fte_hour`, `million_litres`
- `FactorRegistry.to_csv`, `FactorRegistry.dataset`

### Changed
- `Inventory.total_t()` and the summary always report market-based Scope 2 (with fallback)
- Hotel nights are their own unit dimension (`night`) instead of a generic count

## 0.1.0
- Initial core engine: units, GWPs, factor registry, Scope 1/2/3, data quality, CLI
