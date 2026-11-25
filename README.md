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

> Status: **alpha (v0.1)** — the core calculation engine. An AI-assisted Scope 3 spend
> classifier, a REST API and a web dashboard are on the [roadmap](ROADMAP.md).

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
| **Data quality** | 1–5 score per line item (GHG Protocol / PCAF-style), emissions-weighted for the inventory |

## Quick start

```bash
pip install -e ".[dev]"
openscope calculate examples/demo_activities.csv --year 2025 --trace
```

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

### Bring your own factors

```bash
openscope factors --search grid
openscope calculate my_activities.csv --factors desnz_2025.csv --factors supplier_pcfs.csv
```

Factor CSV columns are documented in [`factors/registry.py`](src/openscope/factors/registry.py).
Later files override earlier ones by `factor_id`.

## ⚠️ About the bundled factors

The sample dataset contains a few factors transcribed from the US EPA GHG Emission Factors Hub
(`status=reference`) and many **illustrative** placeholders (`status=illustrative`, ids
starting `DEMO-`). Illustrative factors exist only for demos and tests. The CLI warns when an
inventory relies on them. Always load an authoritative, current dataset before reporting.

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
