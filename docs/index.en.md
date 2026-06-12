# CryptoQuantix — Documentation

Quantitative trading bot for crypto futures/perpetuals: execution on
**Deribit**, data from **Binance Futures**. Three strategies validated on
4 years of multi-cycle data, automatic macro gating, portfolio-level risk
management and an operations dashboard.

> Updated: June 2026 (complete overhaul: from intraday volumetric
> strategies to the validated quantitative strategies).

## Current documents

| Document | Contents |
|---|---|
| [01_architecture.md](01_architecture.md) | Architecture: async bot, layers, dashboard, invariants |
| [02_strategies.md](02_strategies.md) | Trend Breakdown, Funding Squeeze, Macro Core + rejected strategies |
| [03_configuration.md](03_configuration.md) | The `.env` file: operational, active, disabled |
| [05_risk_sizing.md](05_risk_sizing.md) | 3-factor sizing, gross cap, kill switch, vol-targeting |

## Infrastructure

| Document | Contents |
|---|---|
| [02_data_microstructure.md](02_data_microstructure.md) | Binance WS, L2 order book, microstructure |
| [03_orderflow_math.md](03_orderflow_math.md) | Delta, CVD, Kyle's Lambda (feeding regime detection) |
| [06_backtest_montecarlo.md](06_backtest_montecarlo.md) | Backtest engine, metrics, Monte Carlo |
| [07_execution_ops.md](07_execution_ops.md) | Deribit API, orders, deployment |

## Research and validation

The source of truth for all numbers lives in the private repository
(validation pipeline, multi-cycle reports, 4-year datasets). The public
documentation links the results; full operational specifications are
available under a commercial license — see
[Active strategies](02_strategies.md).

## License

**Source-available, dual licensed**: free for noncommercial use
(including trading your own personal capital) under PolyForm
Noncommercial 1.0.0; **any commercial use requires a paid license**.
Contact: **lantoniotrento@gmail.com**
