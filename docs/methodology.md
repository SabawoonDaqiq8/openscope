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

### US EPA supply chain factors (USEEIO)

`useeio-1.3` is imported from EPA's per-gas file, with margins, in 2022 USD purchaser prices.
Each commodity's AR5 total is reconciled against EPA's published CO2e file (EPA uses AR5 with
CH4 = 28). Within 0.0006 kg/USD or 0.5%, the per-gas masses are kept (1,005 commodities). The
other 11 differ by 0.5–0.7% because of the 3-significant-figure rounding of the per-gas values,
and use the published total. EPA's "HFCs and PFCs, unspecified" group is published only as CO2e
and is kept as a fixed `CO2E` component. Methane is not split into fossil and biogenic, so it is
treated as fossil under AR6, which is conservative.

### GWP values

AR5 values are IPCC AR5 WG1 Table 8.A.1 (no climate-carbon feedbacks); AR6 values are IPCC AR6
WG1 Table 7.15 (CH4 fossil 29.8 / non-fossil 27.0) and Table 7.SM.7 for the other gases. The
table was cross-checked against openclimatedata/globalwarmingpotentials, which reads the IPCC
supplementary data. The AR5 values also reproduce EPA's published CO2e factors.

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

## Decarbonisation pathways

Implemented in `openscope.pathway` (see the module docstring for the full method).

* **Baseline**: the headline inventory lines (market-based Scope 2), projected with a
  business-as-usual growth rate per scope.
* **Levers** match inventory lines by scope, Scope 3 category, activity id or keyword. In year
  *y* a lever removes `reduction × ramp(y)` of the remaining emissions of each matched line.
  The ramp is linear from `start_year` over `ramp_years`.
* **Merit order and interactions**: levers are ranked by stand-alone cost per tonne and applied
  in that order to what remains, so overlapping levers do not double count. The reported
  abatement is the marginal, interaction-adjusted value at full implementation and base-year
  activity.
* **Cost**: `capex × CRF(r, lifetime) + annual opex change`, with
  `CRF = r(1+r)^n / ((1+r)^n − 1)`. MAC = annualised cost / annual abatement.
* **Targets**: linear absolute contraction from the base year, separately for Scope 1+2 and
  Scope 3. The defaults are the SBTi near-term minimum annual linear reduction rates (4.2 %/yr,
  1.5 °C-aligned, for Scope 1+2; 2.5 %/yr, well-below 2 °C, for Scope 3). They are
  parameters: check them against the SBTi criteria version that applies to you.
* **Uncertainty**: Monte Carlo (seeded) over lever reduction (triangular low/mode/high) and BAU
  growth (uniform ± a set range). The model reports P10/P50/P90 per year and the share of runs
  at or below each target in the target year.

Limitations: levers are independent multiplicative cuts (no physical coupling, e.g. heat pumps
adding Scope 2 must be netted into the reduction); there is no grid decarbonisation path and
no cost uncertainty yet.

## Disclosure tables

`openscope.disclosure` maps inventory metrics onto ESRS E1-6 and IFRS S2 §29(a):

| Metric | ESRS E1-6 | IFRS S2 |
|---|---|---|
| Gross Scope 1 | §48(a) | §29(a)(i)(1) |
| Share of Scope 1 under regulated ETS | §48(b) (user input) | – |
| Scope 2 location-based | §49(a) | §29(a)(i)(2), (v) |
| Scope 2 market-based | §49(b) | §29(a)(v) (contractual instruments) |
| Scope 3 total and categories | §51, AR 46 | §29(a)(i)(3), (vi) |
| Totals (location / market) | §52(a)/(b) | – |
| GHG intensity per net revenue | §53 (tCO2e per million currency units) | – |

Readiness levels: **blocker** (illustrative factors, calculation errors), **warning** (non-AR6
GWPs, Scope 2 market-based fallback, missing net revenue), **info** (unreported Scope 3
categories, missing comparatives or ETS share, biogenic CO2 not calculated, a high spend-based
share). Not covered: E1-4 targets, E1-5 energy, E1-7 removals and credits, consolidation scope
(§50), and XBRL tagging.
