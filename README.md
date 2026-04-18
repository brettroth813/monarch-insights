# Monarch Insights

A modular Python library for turning [Monarch Money](https://www.monarchmoney.com/) account data into actionable insights, forecasts, and tax-prep artifacts — and a Home Assistant custom component that exposes those insights as sensors, services, and notifications.

> **Status:** scaffolding / pre-credentials. The library can be exercised against fixture data; no live Monarch token is wired up yet.

## What it does

| Layer | Responsibilities |
| --- | --- |
| **`client/`** | Async GraphQL client targeting `https://api.monarch.com/graphql` with token + MFA auth, encrypted session cache, and exponential backoff retries. |
| **`models/`** | Pydantic v2 models for accounts, holdings, transactions, categories, budgets, goals, cashflow, recurring streams, snapshots. |
| **`storage/`** | SQLite-backed cache for Monarch responses (so we can run insights offline) plus a time-series snapshot store. |
| **`supplements/`** | Local store for data Monarch doesn't have: cost basis, paystubs, RSU vesting, K-1 income, manual investment history, document references. |
| **`insights/`** | Net worth, cashflow, spending, investments, anomaly detection, peer/benchmark comparisons. |
| **`forecast/`** | Cashflow projections, net-worth growth (deterministic + Monte Carlo), retirement modeling, goal completion ETA. |
| **`tax/`** | Annual income aggregation, deduction categorization, capital-gains realization, estimated-tax tracking, year-end packets. |
| **`gaps/`** | Detects what's missing for richer answers (cost basis, paystub counterparts, untagged investment income, etc.) and surfaces "additional information wanted" items. |
| **`ha/`** | Home Assistant sensor producers, notification helpers, and an optional FastAPI surface. |
| **`custom_components/monarch_insights/`** | Drop-in HA integration scaffolding (config flow, coordinator, sensor platform). |

## Design tenets

1. **Monarch is the source of truth where it can be**, but real households have data Monarch doesn't (cost basis history, RSU lots, child-support, side-business K-1s). The supplements store fills that gap and lets every insight pivot to "answer with both."
2. **Everything async + cached**, so HA sensors stay snappy even when Monarch is slow.
3. **Pure-Python core + thin HA shim**, so the same code works from a CLI, a Jupyter notebook, or HA.
4. **Every insight names its data dependencies**, so the gap detector can tell you exactly what's missing for a given report (e.g. "Cannot compute long-term gains for AAPL until you provide cost basis for lots before 2018-03").

## Layout

```
monarch_insights/
├── client/          # GraphQL client + queries + auth
├── models/          # Pydantic models
├── storage/         # Local cache + snapshots
├── supplements/     # Manual data store (cost basis, paystubs…)
├── insights/        # Read-only analytics
├── forecast/        # Forward-looking projections
├── tax/             # Tax prep helpers
├── gaps/            # Missing-data detector
├── ha/              # HA-facing helpers
└── cli/             # `monarch-insights` CLI entry point

custom_components/monarch_insights/   # HA integration shim
tests/                                # pytest suite
scripts/                              # bootstrap + sync utilities
```

## Tomorrow's wiring checklist (when credentials land)

1. `monarch-insights auth login` → stores encrypted token at `~/.config/monarch-insights/session`.
2. `monarch-insights sync --full` → snapshots accounts, holdings, transactions to local cache.
3. `monarch-insights gaps list` → first pass at "what to provide manually."
4. Add custom component to `/config/custom_components/`, restart HA, configure via UI.

## References

- [hammem/monarchmoney](https://github.com/hammem/monarchmoney) — original Python client (auth flow + query catalog)
- [keithah/monarchmoney-enhanced](https://github.com/keithah/monarchmoney-enhanced) — fork with holdings, goals, recurring stream classification
- [monarch-graphql.ajzbc.com](https://monarch-graphql.ajzbc.com/) — community-introspected GraphQL schema
- Public-status note (Jan 2026): GraphQL endpoint moved from `api.monarchmoney.com` to `api.monarch.com`.
