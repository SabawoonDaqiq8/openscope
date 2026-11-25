# Methodology

openscope implements the calculation logic of the
[GHG Protocol Corporate Standard](https://ghgprotocol.org/corporate-standard), the
[Scope 2 Guidance](https://ghgprotocol.org/scope-2-guidance) and the
[Corporate Value Chain (Scope 3) Standard](https://ghgprotocol.org/corporate-value-chain-scope-3-standard).

## Core equation

For every activity line:

```
emissions (kg CO2e) = Σ_gas  activity_quantity × factor_gas (kg gas / unit) × GWP_gas
```

* `activity_quantity` is first converted into the factor's unit. Conversion only happens
  within one physical dimension (energy, volume, mass, distance, freight, passenger-distance,
  count). Currencies are never converted: spend-based factors are tied to a currency **and a
  price year**, so FX and inflation adjustments must be explicit modelling steps.
* When a source publishes only an aggregated CO2e factor, it is used as-is and the trace notes
  that the GWP set is fixed by the source.

## GWP

100-year GWPs from IPCC AR5 (excluding climate-carbon feedbacks) and AR6. AR6 is the default;
`CH4` maps to fossil methane (29.8) unless `CH4_BIOGENIC` is used.

## Scope 2

Location-based and market-based results are calculated from separate activity rows and
reported separately (dual reporting). The headline total uses market-based Scope 2 when any
market-based data exists, otherwise location-based.

*Current limitation:* if market-based data exists for some sites but not others, the
market-based total does not yet fall back to residual-mix or grid-average factors for the
uncovered sites. That fallback is planned.

## Scope 3

Each Scope 3 activity must declare one of the 15 categories. Calculation method is recorded per
line: `supplier_specific`, `hybrid`, `average_data`, `spend_based` or `estimated`.

## Data quality score (1 = best, 5 = worst)

| Method | Base score |
|---|---|
| supplier_specific | 1 |
| hybrid | 2 |
| average_data | 3 |
| spend_based | 4 |
| estimated | 5 |

+1 if the factor is illustrative, +1 if the factor is more than 5 years older than the reporting
year (capped at 5). The inventory score is the emissions-weighted mean over headline results.
This is a simplified version of the GHG Protocol data-quality indicators and the PCAF score. It is
meant to rank where better data would matter most, not to replace a formal assessment.
