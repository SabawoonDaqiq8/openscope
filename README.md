# openscope

**[▶ Live demo](https://openscope-xi6p.onrender.com/overview)** · [Documentation](docs/methodology.md) · [Roadmap](ROADMAP.md)

[![Live demo](https://img.shields.io/badge/live%20demo-onrender.com-46e3b7)](https://openscope-xi6p.onrender.com/overview)
[![CI](https://github.com/SabawoonDaqiq8/openscope/actions/workflows/ci.yml/badge.svg)](https://github.com/SabawoonDaqiq8/openscope/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
![GHG Protocol](https://img.shields.io/badge/GHG%20Protocol-Scope%201%20%7C%202%20%7C%203-2e7d32)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-261230)](https://github.com/astral-sh/ruff)
![Typed: mypy strict](https://img.shields.io/badge/typed-mypy%20strict-informational)

**Open-source, auditable carbon accounting.** A Python engine for calculating GHG Protocol
Scope 1, 2 and 3 emissions, where every number can be traced back to its activity data,
emission factor, unit conversion and GWP.

> Status: **alpha (v0.6)**: core engine, official factor datasets (**UK DESNZ 2025**, 2,672
> factors, and **US EPA supply chain factors v1.3**, 1,016 spend-based factors), an
> **AI-assisted Scope 3 spend classifier** with human review and an audit trail, a
> **decarbonisation pathway simulator** (MACC, science-based targets, Monte Carlo), **ESRS E1-5 /
> E1-6 and IFRS S2 disclosure tables** (energy mix, biogenic CO2) with readiness checks, and a
> **web dashboard** (FastAPI + Angular).

![openscope dashboard](docs/images/dashboard-overview-light.png)

## Dashboard

**Try it: [openscope-xi6p.onrender.com](https://openscope-xi6p.onrender.com/overview)**. The public
demo loads sample data automatically. It runs on Render's free plan, so the first visit after a
quiet period can take up to a minute while the service wakes up.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/SabawoonDaqiq8/openscope)
&nbsp;See [docs/deployment.md](docs/deployment.md) for hosting notes.

```bash
docker build -t openscope .
docker run -p 8000:8000 -v openscope-data:/data openscope
# open http://localhost:8000 → "Load demo data"; API docs at /docs
```

| | |
|---|---|
| **Overview**: scope totals, Scope 2 dual reporting, Scope 3 by category, hotspots, data quality, disclosure warnings | **Line explorer**: every calculated line with its step-by-step audit trail |
| **Scope 3 review**: accept / override / exclude classified ledger lines; every decision is audit-logged and teaches supplier memory | **Pathways**: abatement levers, MACC, science-based targets and Monte Carlo uncertainty |
| **Disclosure**: ESRS E1-6 / IFRS S2 tables, readiness checks, CSV/Markdown/JSON export | **Emission factors**: search all 3,700+ factors with source and GWP basis |

![Scope 3 review queue](docs/images/dashboard-review.png)

### Decarbonisation pathways

![Pathway simulator](docs/images/dashboard-pathways.png)

Model abatement levers (heat pumps, fleet electrification, renewable electricity, supplier
engagement…) against your inventory:

* **Marginal abatement cost curve**: levers in merit order, cost per tCO2e from capex
  annualised with the capital recovery factor plus opex. Overlapping levers never abate the
  same tonne twice.
* **Science-based targets**: linear absolute contraction, set separately for Scope 1+2 and
  Scope 3 (SBTi near-term minimums by default: 4.2 %/yr and 2.5 %/yr), because a plan can hit
  the combined total while missing one of them.
* **Uncertainty**: Monte Carlo over lever effectiveness (triangular low/likely/high) and BAU
  growth, giving P10–P90 bands and the probability of meeting each target.

```bash
openscope pathway examples/uk_demo_activities.csv --scenario examples/pathway_demo_scenario.json \
    --dataset desnz-2025 --gwp AR5
```

The demo scenario's costs and reductions are **illustrative assumptions** and are flagged in the
UI.

### Climate disclosure (ESRS E1-6 · IFRS S2)

![Disclosure](docs/images/dashboard-disclosure.png)

Turns inventories into the GHG emissions table each framework asks for:

* **ESRS E1-6**: gross Scope 1 and the share under regulated ETS (§48), Scope 2 location- and
  market-based (§49), total and significant Scope 3 categories (§51), totals (§52), GHG
  intensity per net revenue (§53), with prior-year and base-year comparison.
* **ESRS E1-5 energy consumption and mix**: fossil, nuclear and renewable energy (MWh), the
  renewable share and energy intensity. Net calorific values are derived from the DESNZ
  dataset itself, and certificate-backed renewable electricity is counted once per site.
* **Biogenic CO2** reported outside the scopes, from DESNZ's outside-of-scopes factors.
* **IFRS S2 §29(a)**: absolute gross Scope 1, 2 (location-based, plus market-based for
  contractual instruments) and 3 with categories.
* **Readiness checks**: what an assurance provider would raise (illustrative factors and
  calculation errors block; non-AR6 GWPs, Scope 2 grid-average fallback, missing revenue,
  electricity or heat with an undetermined source mix and lines without energy content warn;
  unreported Scope 3 categories, biogenic CO2 and self-generated renewables are noted).
* A **basis of preparation** generated from the calculation metadata, and CSV, Markdown and
  JSON export.

```bash
openscope disclose examples/uk_demo_activities.csv --prior examples/uk_demo_activities_2024.csv \
    --dataset desnz-2025 --year 2025 --net-revenue 12500000 --currency GBP --ets-share 0 \
    --grid-mix 40,15,45   # fossil,nuclear,renewable % of electricity not covered by certificates
```

References are to ESRS Set 1 (Delegated Regulation (EU) 2023/2772) and IFRS S2. The EU Omnibus
simplification may change ESRS; check the version that applies to your reporting period.

**Stack:** FastAPI · SQLAlchemy (SQLite, Postgres-ready) · Angular 22 (standalone components,
signals, zoneless) · Tailwind CSS · Apache ECharts · TypeScript types generated from the
OpenAPI spec · one Docker image. Charts use a palette validated for colour-vision deficiency,
with direct labels, a table view for every chart, and light and dark themes.

<details><summary>Dark mode</summary>

![openscope dashboard, dark mode](docs/images/dashboard-overview-dark.png)
</details>

<details><summary>Local development (without Docker)</summary>

```bash
pip install -e ".[dev]"
uvicorn openscope.api.app:app --reload          # API on :8000 (docs at /docs)
cd web && npm ci && npm start                    # Angular on :4200, proxies /api
npm run gen:api                                  # regenerate TS types after API changes
```
Set `OPENSCOPE_LLM=1` and `ANTHROPIC_API_KEY` to enable Claude classification in the UI.
Configuration is documented in [`api/settings.py`](src/openscope/api/settings.py).
</details>

## Why

Carbon accounting is a data problem dressed up as a reporting problem. Disclosure regimes
such as the EU CSRD/ESRS E1, ISSB IFRS S2 and California SB 253 all require GHG inventories
that are **complete, consistent and assurable**. Most of the tools used today are spreadsheets
or closed SaaS products whose calculations can't be inspected.

openscope's design principles:

| Principle | How it shows up |
|---|---|
| **Traceability** | Every result carries a human-readable audit `trace` of each calculation step |
| **Factor provenance** | Factors are versioned CSV with source, year, region and a `status` (`reference` / `illustrative` / `custom`) |
| **Correct units** | Dimension-checked unit conversions; currencies are never converted implicitly |
| **GWP flexibility** | Per-gas factors are converted with IPCC AR5 or AR6 GWPs at calculation time |
| **Scope 2 dual reporting** | Location- and market-based totals are kept separate and never double-counted |
| **Real datasets** | Official DESNZ 2025 factors bundled; importer for future editions |
| **Spend normalisation** | FX + price-year deflation for spend-based (EEIO) factors, fully traced |
| **Data quality** | 1–5 score per line item (GHG Protocol / PCAF-style), emissions-weighted for the inventory |

## Quick start

```bash
pip install -e ".[dev]"

# A UK company inventory computed entirely with official DESNZ 2025 factors
openscope calculate examples/uk_demo_activities.csv --dataset desnz-2025 --gwp AR5 --year 2025
```

```text
GHG inventory summary (tCO2e)
────────────────────────────────────────────────────────────
  Scope 1                                        271.186
  Scope 2 (location-based)                       150.458
  Scope 2 (market-based)                          44.252
    (grid-average fallback for: Warehouse)
  Scope 3                                        334.580
    1. Purchased goods and services                0.612
    3. Fuel- and energy-related activities       106.106
    4. Upstream transportation and distribut      52.848
    5. Waste generated in operations              11.452
    6. Business travel                           143.535
    7. Employee commuting                         20.027
────────────────────────────────────────────────────────────
  Total                                          650.019
```

Add `--trace` to see the audit trail for every line:

```text
[S1-001]
  Factor EPA-STAT-NATGAS — Natural gas - stationary combustion [US EPA GHG Emission Factors Hub (Table 1), 2024; reference]
  Converted 12,000 therm → 1,200 MMBtu
  CO2: 1,200 × 53.06 kg/MMBtu = 63,672 kg × GWP 1 (AR6) = 63,672 kg CO2e
  CH4: 1,200 × 0.001 kg/MMBtu = 1.2 kg × GWP 29.8 (AR6) = 35.76 kg CO2e
  N2O: 1,200 × 0.0001 kg/MMBtu = 0.12 kg × GWP 273 (AR6) = 32.76 kg CO2e
  Total: 63,740.5 kg CO2e; data quality 3/5 (average_data)
```

### As a library

```python
from openscope import ActivityRecord, Calculator, Inventory, Scope

calc = Calculator(gwp_set="AR6", reporting_year=2025)
result = calc.calculate(
    ActivityRecord(
        activity_id="boiler",
        quantity=12_000,
        unit="therm",
        scope=Scope.SCOPE_1,
        factor_id="EPA-STAT-NATGAS",
    )
)
print(result.co2e_t, result.trace)

batch = calc.calculate_many(activities)  # errors are collected, not raised
print(Inventory(batch.results).summary())
```

### AI-assisted Scope 3 from your purchase ledger

```bash
pip install -e ".[ai]"            # Claude classifier (needs ANTHROPIC_API_KEY)
openscope classify ledger.csv --out review.csv --llm --factors my_spend_factors.csv
# ... review.csv in a spreadsheet: accept / override / exclude ...
openscope review-apply review.csv --reviewer "Your Name" \
    --activities-out spend.csv --audit-log audit.jsonl --memory suppliers.json
openscope calculate spend.csv --factors my_spend_factors.csv
```

The pipeline runs rules, then supplier memory, then Claude (batched, schema-constrained to your
factor list, prompt-cached), then a confidence gate, then human review. The audit log records
every reviewer decision. Run with `--labels` to measure accuracy, coverage and auto-accept
precision. See [docs/classification.md](docs/classification.md).

### Factor datasets

```bash
openscope datasets                                   # bundled: desnz-2025, useeio-1.3, sample
openscope factors --dataset desnz-2025 --search "Hotel stay"
openscope import-desnz ghg-conversion-factors-2026-flat-format.xlsx --out desnz_2026.csv
openscope import-useeio SupplyChainGHGEmissionFactors_v1.3.0_NAICS_byGHG_USD2022.csv \
    --co2e SupplyChainGHGEmissionFactors_v1.3.0_NAICS_CO2e_USD2022.csv --out useeio.csv
```

**Spend-based factors (US EPA, USEEIO).** `useeio-1.3` holds kg of each gas per 2022 USD
(purchaser price including margins) for 1,016 NAICS-6 commodities. The importer checks every
commodity's per-gas total against EPA's published CO2e: 1,005 match within rounding and can be
recalculated under AR6, and 11 fall back to the published AR5 total.

**DESNZ and GWPs.** DESNZ publishes per-gas values already converted to CO2e with AR5 GWPs.
openscope converts them back to kilograms of each gas, so DESNZ factors can be recalculated
under **AR6**. Factors published only as a CO2e total keep their `gwp_basis` (AR5, or AR4 for
well-to-tank bioenergy), and the trace warns when that differs from your inventory's GWP set.

### Spend-based factors: currency and price year

```bash
openscope calculate spend.csv --fx fx.csv --price-index deflator.csv
```

`fx.csv` holds `year,from,to,rate` and `deflator.csv` holds `currency,year,index`. Get these from
an authoritative source such as a central bank or statistics office; openscope ships no FX or
inflation data. A currency mismatch without FX rates is an error. A price-year mismatch without
an index produces a warning.

### Bring your own factors

```bash
openscope factors --search grid
openscope calculate my_activities.csv --factors desnz_2025.csv --factors supplier_pcfs.csv
```

Factor CSV columns are documented in [`factors/registry.py`](src/openscope/factors/registry.py).
Later files override earlier ones by `factor_id`.

## ⚠️ About the bundled factors

* **`desnz-2025`**: the complete UK Government GHG Conversion Factors for Company Reporting
  2025 (flat file v1), imported unmodified apart from unit and GWP handling.
  Contains public sector information licensed under the
  [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
* **`useeio-1.3`**: US EPA Supply Chain GHG Emission Factors v1.3.0 by NAICS-6
  ([DOI 10.23719/1531143](https://doi.org/10.23719/1531143)), US public domain.
* **`sample`** (always loaded unless `--no-bundled`): a few US EPA factors
  (`status=reference`) and **illustrative** placeholders (ids starting `DEMO-`) for demos and
  tests only. The CLI warns when an inventory relies on them.

## Methodology

See [docs/methodology.md](docs/methodology.md).

## Development

```bash
pytest                                    # Python tests (engine, classifier, API)
ruff check . && mypy src                  # lint + strict type-check
cd web && npx ng test --watch=false       # Angular unit tests (Vitest)
cd web && npx ng build && npx playwright test   # end-to-end tests in a real browser
```

The end-to-end suite runs against the production build in public-demo mode, the same setup as
the live demo. It covers the main flows (overview, audit trail, Scope 3 review and export,
pathways, disclosure, factor search), fails on any console error or Content-Security-Policy
violation, checks the demo protections and security headers, runs axe-core accessibility
checks on every page in light and dark mode, and checks that every page fits a phone screen.

## License

MIT © Sabawoon Daqiq
