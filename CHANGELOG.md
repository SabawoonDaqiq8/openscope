# Changelog

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
