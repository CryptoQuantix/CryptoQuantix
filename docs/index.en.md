# CryptoQuantix

**Quantitative trading engine for crypto futures/perpetuals** —
execution on **Deribit**, tick-by-tick data from **Binance Futures**.
Three strategies validated on 4 years of multi-cycle data, automatic
macro gating, portfolio-level risk management and a complete operations
dashboard.

<div class="grid cards" markdown>

-   :material-sitemap:{ .lg .middle } **Architecture**

    ---

    Asyncio bot, injectable data layer, regime & scoring engines,
    6-page dashboard, design invariants.

    [:octicons-arrow-right-24: Explore the system](01_architecture.md)

-   :material-strategy:{ .lg .middle } **Active strategies**

    ---

    Trend Breakdown, Funding Squeeze, Macro Core: what they do, the
    validation numbers, and the eight rejected strategies.

    [:octicons-arrow-right-24: The strategies](02_strategies.md)

-   :material-tune:{ .lg .middle } **Configuration**

    ---

    The `.env` file in blocks: operational, active strategies,
    disabled strategies with their verdicts.

    [:octicons-arrow-right-24: Configure](03_configuration.md)

-   :material-shield-half-full:{ .lg .middle } **Risk & Sizing**

    ---

    3-factor sizing, gross exposure cap, daily kill switch,
    vol-targeting, order lifecycle.

    [:octicons-arrow-right-24: The risk engine](05_risk_sizing.md)

</div>

## Validation numbers

!!! info "Methodology"

    Backtests on the **actual production code** (not a
    reimplementation), 4 multi-cycle years (Jun 2022 → Jun 2026: bear,
    bull, bear), 0.20% roundtrip costs, no lookahead, IS/OOS.

| | Strategy | Validation (BTC, 4 years) |
|---|---|---|
| :material-trending-down: | **Trend Breakdown** short | +22 bps/trade · PF 1.26 · 123 trades |
| :material-trending-up: | **Trend Breakdown** long | +68 bps/trade · PF 1.53 · 84 trades |
| :material-fire: | **Funding Squeeze** | +74 bps/trade · PF 2.65 · ETH +64 bps |
| :material-anchor: | **Macro Core** | +315%/4y vs +136% B&H · maxDD 24.7% |
| :material-chart-line: | **Full portfolio** | **+491%** · maxDD 21.5% · Calmar 2.61 · worst year 0.0% |

## Infrastructure

<div class="grid cards" markdown>

-   :material-database:{ .lg .middle } **[Data & Microstructure](02_data_microstructure.md)**

    Binance WebSocket, L2 order book, liquidations, data quality.

-   :material-waves:{ .lg .middle } **[Orderflow & CVD](03_orderflow_math.md)**

    Delta, multi-timeframe CVD, VWAP Z-score, Kyle's Lambda.

-   :material-test-tube:{ .lg .middle } **[Backtest & Monte Carlo](06_backtest_montecarlo.md)**

    Engine, metrics (Sharpe, Sortino, PF), bootstrap resampling.

-   :material-rocket-launch:{ .lg .middle } **[Execution & Deploy](07_execution_ops.md)**

    Deribit API, order lifecycle, alerting, Docker, pre-live checklist.

</div>

## Research and validation

The source of truth for all numbers lives in the private repository
(validation pipeline, multi-cycle reports, 4-year datasets). The public
documentation links the results; full operational specifications are
available under a commercial license — see
[Active strategies](02_strategies.md).

!!! warning "License"

    **Source-available, dual licensed**: free for noncommercial use
    (including trading your own personal capital) under PolyForm
    Noncommercial 1.0.0; **any commercial use requires a paid license**.

    :material-email: **lantoniotrento@gmail.com**

!!! danger "Disclaimer"

    Trading crypto futures involves a significant risk of loss. This
    software is provided "as is", with no guarantee of profit
    whatsoever. Use at your own risk.
