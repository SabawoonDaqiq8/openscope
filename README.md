# openscope

[![CI](https://github.com/SabawoonDaqiq8/openscope/actions/workflows/ci.yml/badge.svg)](https://github.com/SabawoonDaqiq8/openscope/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
![GHG Protocol](https://img.shields.io/badge/GHG%20Protocol-Scope%201%20%7C%202%20%7C%203-2e7d32)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-261230)](https://github.com/astral-sh/ruff)
![Typed: mypy strict](https://img.shields.io/badge/typed-mypy%20strict-informational)

**Open-source, auditable carbon accounting.** A Python engine for calculating GHG Protocol
Scope 1, 2 and 3 emissions, where every number can be traced back to its activity data,
emission factor, unit conversion and GWP.

> Status: **alpha (v0.2)**: core engine plus the full **UK Government (DESNZ) 2025**
> conversion-factor set (2,672 factors). An AI-assisted Scope 3 spend classifier, a REST API
> and a web dashboard are on the [roadmap](ROADMAP.md).

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
────────────────────────────────────────────────────
  Scope 1                                271.186
  Scope 2 (location-based)               150.458
  Scope 2 (market-based)                  44.252
    (grid-average fallback for: Warehouse)
  Scope 3                                334.580
    1. Purchased Goods And Service         0.612
    3. Fuel And Energy Related           106.106
    4. Upstream Transportation            52.848
    5. Waste                              11.452
    6. Business Travel                   143.535
    7. Employee Commuting                 20.027
────────────────────────────────────────────────────
  Total                                  650.019
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

### Factor datasets

```bash
openscope datasets                                   # bundled: desnz-2025, sample
openscope factors --dataset desnz-2025 --search "Hotel stay"
openscope import-desnz ghg-conversion-factors-2026-flat-format.xlsx --out desnz_2026.csv
```

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
* **`sample`** (always loaded unless `--no-bundled`): a few US EPA factors
  (`status=reference`) and **illustrative** placeholders (ids starting `DEMO-`) for demos and
  tests only. The CLI warns when an inventory relies on them.

## Methodology

See [docs/methodology.md](docs/methodology.md).

## Development

```bash
pytest              # tests
ruff check .        # lint
mypy src            # type-check
```

## License

MIT © Sabawoon Daqiq
