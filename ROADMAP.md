# Roadmap

## v0.1 — Core engine ✅
- Unit-safe activity × factor calculations with per-gas GWP (AR5/AR6)
- Versioned CSV factor registry with provenance and status
- Scope 2 dual reporting, Scope 3 categories, data-quality scoring
- CLI + audit trail, CI, tests

## v0.2 — Real factor datasets ✅
- DESNZ flat-file importer + bundled DESNZ 2025 dataset (2,672 factors, AR6-recalculable)
- Spend normalisation: FX + price-year deflation with full trace
- Market-based Scope 2 fallback to grid average for uncovered sites
- UK demo inventory built only on reference factors

## v0.3 — AI-assisted Scope 3 spend classifier (flagship) ✅
- Ledger import with ERP column aliases
- Rules → supplier memory → Claude (schema-constrained, batched, prompt-cached) → review
- Confidence gate, review CSV round-trip, JSONL audit log, supplier memory learning
- Evaluation: accuracy, coverage, auto-accept precision on a labelled ledger

## v0.3.x
- Live benchmark on a larger labelled ledger; threshold calibration report
- Message Batches API for large ledgers (50% cost)

## v0.4 — API & dashboard ✅
- FastAPI service (OpenAPI docs), SQLAlchemy persistence (SQLite; Postgres-ready)
- Angular dashboard: overview, line explorer with audit trail, Scope 3 review queue, factor browser, upload
- Single Docker image; CI builds and smoke-tests it

## v0.4.x
- Public demo deployment
- Authentication and multi-tenant workspaces
- Supplier engagement view (top suppliers by emissions, data-quality upgrade targets)

## v0.5 — US EPA spend-based factors ✅
- USEEIO v1.3 supply chain factors (1,016 NAICS-6 commodities), per gas, reconciled with EPA
- Complete AR5/AR6 GWP table for the gases in the dataset

## v0.6 — Decarbonisation pathways ✅
- Abatement levers, marginal abatement cost curve, Monte Carlo uncertainty
- Science-based target trajectories per Scope 1+2 and Scope 3

## v0.6.x
- Grid decarbonisation path for Scope 2; cost uncertainty; saved scenarios on the server

## Later datasets
- US EPA GHG Emission Factors Hub (full), residual-mix factors (AIB, Green-e)

## Later
- ESRS E1 / IFRS S2 disclosure exports
- PCAF financed-emissions module
