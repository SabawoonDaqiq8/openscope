# Changelog

## 0.12.0
### Added
- **DESNZ 2026** conversion factors (revised flat file of 31 July 2026) and **DESNZ 2024**,
  alongside 2025: `desnz-2024`, `desnz-2025`, `desnz-2026`, and `desnz` for all three
- **Factors matched to the activity year**: an id without its year (`DESNZ-7_400_4000_5`)
  resolves to the edition for the activity's period or the reporting year, falling back to
  the latest earlier edition with a warning; the trace records the edition
- Readiness check `factor-editions` when the comparative year uses different factor editions
- A test that every DESNZ id keeps its unit and scope across editions

### Changed
- The server loads all three DESNZ editions by default
- The demo files use year-free ids, so the 2024 comparatives now use 2024 factors (2024
  total 904.2 t instead of 795.2 t); derived Category 3 lines follow the same edition, and a
  manual Category 3 line with a year-free id still prevents double counting
- The case study, README screenshots and copy describe the year-matched comparatives

## 0.11.0
### Added
- **ESRS E1-4 GHG emission reduction targets** from pathway scenarios (`openscope.targets`):
  base year and value, target values for 2030 and every 5 years after, reduction against the
  base year, scope shares of the combined Scope 1+2 target, gases covered, comparison with the
  SBTi near-term minimum rates, and lever contributions by boundary (§34(a)-(f))
- Readiness checks: missing 2030 value, base year mismatch, near-term horizon, ambition below
  the SBTi minimum, missing Scope 3 target, shortfall against the target, illustrative levers
- Pathway page: E1-4 panel with Markdown, CSV and JSON downloads; `PathwayOut.e1_4`;
  `POST /api/inventories/{id}/pathway/e1-4?format=`; CLI `openscope pathway --e1-4 md|csv|json`
- Pathway results carry per-boundary trajectories and lever contributions

### Fixed
- `openscope pathway` gave levers the descriptions of derived Category 3 lines, so a lever
  selecting "natural gas" also reaches the gas well-to-tank line, as it does in the dashboard

## 0.10.0
### Added
- **Scope 3 Category 3 derived from Scope 1 and 2**: well-to-tank emissions of fuels,
  electricity and heat, transmission and distribution losses and their upstream emissions,
  one traced line per upstream factor (`--derive-cat3`, `derive_cat3` on upload, a dashboard
  option, on by default there)
- Factors can link their upstream factors (`cat3_factor_ids`); the DESNZ importer links 552
  of the 2025 factors from their IDs
- Purchased electricity is counted once per site; upstream factors already used by a
  Category 3 line are not derived again
- Readiness checks: derived Category 3 lines (info), Scope 1/2 energy without Category 3
  (warning); the line explorer marks derived lines

### Changed
- The demo inventories derive Category 3 instead of listing it by hand; the 2025 demo now
  also includes the upstream emissions of electricity lost in the grid (the 2025 total stays
  at 650 t)

## 0.9.0
### Added
- **EU electricity factors from the AIB European Residual Mixes**: `openscope import-aib`
  converts the AIB workbook into per-country Scope 2 factors, the residual mix
  (market-based, `AIB-<year>-RM-<country>`) and the production mix (location-based,
  `AIB-<year>-PM-<country>`). The 2025 workbook gives 65 factors for 34 countries. The AIB
  data is not bundled: it is copyright of the AIB.
- Factors can carry their generation mix (`fossil_share`, `nuclear_share`,
  `renewable_share`), shown in the calculation trace
- ESRS E1-5 splits electricity without certificates automatically: the market-based factor's
  mix first, then a stated mix, then the location-based factor's mix. The readiness checks say
  which basis covered how many MWh.

### Changed
- The `energy-mix` warning is raised only for electricity no mix covers

## 0.8.0
### Added
- **ESRS E1-5 energy consumption and mix**: fossil (§37(a)), nuclear (§37(b)) and renewable
  (§37(c)(i)-(iii)) energy in MWh, total, renewable share and energy intensity, in the ESRS
  disclosure, API, CLI (`--grid-mix`) and dashboard (grid-mix inputs, section headings)
- **Biogenic CO2** reported outside the scopes, by scope, in the ESRS table
- Factors carry `energy_kwh_per_unit`, `energy_source` and `biogenic_co2_kg`; results carry
  `energy_kwh` and `biogenic_co2_kg`, with audit-trail lines
- DESNZ importer derives net calorific values from the dataset (157 factors) and links
  outside-of-scopes biogenic CO2 to in-scope factors when the match is unambiguous (54)
- `openscope.energy` module: electricity counted once per site, certificate-backed renewables
  capped at consumption, optional grid mix
- Readiness checks for undetermined electricity or heat mix, missing energy content and
  self-generated renewables

## 0.7.2
### Added
- End-to-end test suite (Playwright, 27 tests) against the production build in public-demo
  mode: main user flows, zero console/CSP errors, demo protections and security headers,
  axe-core accessibility on every page (light and dark), phone-width layout. Runs in CI.

### Fixed
- Public demo: exporting the demo ledger failed (HTTP 400) because the exported inventory's
  name starts with "Demo:". The reserved prefix now applies to ledger runs only, since demo
  inventories are protected by their source. Found by the new end-to-end tests.
- Factor search ranks results: matches in the factor name first, then the most specific
  name. "electricity uk" used to bury the UK grid factor among 154 results.

### Improved
- The chosen factor in the review override form is announced to screen readers (`role=status`)

## 0.7.1
### Security
- Public-demo mode: deletes disabled, 1 MB upload limit, per-visitor write rate limit (429
  with Retry-After), cap on stored visitor uploads (oldest removed, demo data kept), reserved
  `Demo:` names
- Security headers on every response, including a strict Content-Security-Policy; Angular's
  inline critical-CSS script is disabled so the policy needs no exceptions

### Improved
- Works on phones: the header wraps with a scrollable navigation row, dropdowns and grids fit
  the screen, and wide tables scroll inside their cards (checked on iPhone width, all pages)
- Accessibility: zero axe-core violations (WCAG 2.1 AA + best practice) on every page, light
  and dark: page headings, landmark for the demo banner, and a real button with
  `aria-expanded` for audit-trail rows
- "How it works" strip on the overview (measure, classify, plan, disclose)

## 0.7.0
### Added
- `openscope.disclosure`: ESRS E1-6 and IFRS S2 §29(a) GHG emissions tables with prior-year and
  base-year comparison, GHG intensity per net revenue, readiness checks (blocker / warning /
  info) and a generated basis of preparation; CSV, Markdown and JSON renderers
- `openscope disclose` CLI (exits non-zero when blockers exist, for use in CI pipelines)
- API: `GET /api/inventories/{id}/disclosure` and `/disclosure/export?format=csv|md|json`
- Dashboard **Disclosure** page: framework toggle, comparatives, revenue and ETS inputs,
  readiness panel, downloads
- Demo: 2024 inventory for the same fictional company (comparatives; no renewable tariff yet)

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
