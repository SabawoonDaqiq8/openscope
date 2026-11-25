# Roadmap

## v0.1 — Core engine ✅
- Unit-safe activity × factor calculations with per-gas GWP (AR5/AR6)
- Versioned CSV factor registry with provenance and status
- Scope 2 dual reporting, Scope 3 categories, data-quality scoring
- CLI + audit trail, CI, tests

## v0.2 — Real factor datasets
- Importers for UK DESNZ/DEFRA conversion factors, US EPA Emission Factors Hub, USEEIO
- Spend-based factor helpers: currency + price-year normalisation (FX, inflation/deflators)
- Market-based Scope 2 fallback to residual mix for uncovered sites

## v0.3 — AI-assisted Scope 3 spend classifier (flagship)
- Upload a general-ledger export → map each line to a Scope 3 category and factor
- LLM + rules hybrid, with confidence scores and a human review queue
- Every override is logged (who, when, why) for assurance

## v0.4 — API & dashboard
- FastAPI service + PostgreSQL
- Web dashboard: scope breakdown, hotspots, data-quality heatmap, supplier engagement list

## v0.5 — Decarbonization pathways
- Abatement levers, marginal abatement cost curve, Monte Carlo uncertainty
- Target trajectories (absolute contraction) vs. baseline

## Later
- ESRS E1 / IFRS S2 disclosure exports
- PCAF financed-emissions module
