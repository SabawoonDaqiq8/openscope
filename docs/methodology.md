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
reported separately (dual reporting). The headline total uses market-based Scope 2.

**Market-based fallback.** The Scope 2 Guidance hierarchy runs: energy attribute
certificates or contracts → supplier-specific rate → residual mix → grid average. For any
site with location-based rows but no market-based rows, openscope uses the location-based
(grid-average) result in the market-based total and lists the site in
`scope2_market_fallback_sites`. If a residual-mix factor is available, supply market-based
rows using it, because the grid average double counts renewable attributes already claimed by
others. Sites are matched on the `site` field.

## Factor datasets and GWP basis

UK DESNZ conversion factors publish per-gas values as kg CO2e using AR5 GWPs (CH4 = 28,
N2O = 265; 2025 methodology paper §1.7). Where CO2, CH4 and N2O components are all present
and reconcile with the published total within 0.5%, openscope stores them as gas masses
(`kg CO2e of gas / GWP_AR5`), so they can be re-weighted under any GWP set. Otherwise the
total is stored with its `gwp_basis`: AR5, or AR4 for well-to-tank bioenergy (methodology
paper Table 1). Some refrigerants use AR6 GWPs where AR5 values do not exist.

## Spend-based factors

```
amount_in_factor_terms = amount × FX(spend currency → factor currency, spend year)
                                × index(factor currency, factor year) / index(…, spend year)
```

The spend year is `price_year`, or else the year of `period_end` / `period_start`. The
factor's `year` is taken as its price year. Without a normaliser, different currencies are an
error and different years produce a warning. Margins (purchaser vs basic prices) are not
adjusted.

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
