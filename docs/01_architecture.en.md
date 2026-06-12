# System architecture

> Updated: June 2026, after the overhaul towards the validated
> quantitative strategies (TB/FS/MC).

## Overview

```
BINANCE FUTURES (data, free)                  DERIBIT (execution)
  WS: aggTrade/depth/forceOrder                 private REST
  REST: 1h/1d klines, funding                        ^
        |                |                           |
        v                v                           |
  BinanceDataIngestion  KlineProvider     OrderManager + OrderRegistry
        |                |  (injectable)             ^
        v                |                           |
  OrderBookEngine        |                           |
  OrderflowEngine        +-----> STRATEGIES ---------+
  RegimeDetector ---------------> TB / FS / MC       |
  ScoringEngine  ----------------^ (should_trade)    |
                                                     |
                              RiskManager (sizing + caps + kill switch)
                              PositionMonitor (orphans, reconciliation)
                              FailureHandler (health, emergency)
                                       |
                  TradeLogger (journal.db) + SignalLog + PositionLog
                  TelegramAlerts
                                       |
              STREAMLIT DASHBOARD (separate process, read-only core)
```

## Main process: `src/async_trading_bot.py`

Asyncio bot with concurrent tasks:

| Loop | Period | What it does |
|---|---|---|
| scan loop | 15 min | per strategy: `ScoringEngine.should_trade` → `scan()` → `execute_entry()` |
| management loop | 30 s | `manage_positions()` for every strategy + orphan-order cleanup (BTC+ETH) + restart-request flag |
| orderbook loop | continuous | depth snapshot + WS deltas (snapshot BEFORE deltas protocol) |
| outcome tracker | 30 min | resolves WIN/LOSS for SignalLog entries |
| positioning loop | 12 h | C8 archive: positioning data Binance only exposes for ~30 days |
| health loop | 5 s | `FailureHandler`: API down too long → emergency close |

## Layers

### `src/core/` — venue and risk
- **DeribitClient**: authenticated REST (testnet/prod)
- **OrderManager**: market entry + reduce-only stop_market SL (3×
  retry, then EMERGENCY CLOSE — never naked positions) + reduce-only
  limit TP, all registered in the **OrderRegistry** for orphan cleanup
- **PositionMonitor**: venue positions, orphan-order checks
- **RiskManager**: 3-factor sizing, aggregate gross-exposure cap, daily
  kill switch (see [05_risk_sizing.md](05_risk_sizing.md))
- **FailureHandler**: health checks and failure reactions

### `src/data/` — ingestion
- **BinanceDataIngestion**: tick-by-tick WS (trades, depth, liquidations)
- **OrderBookEngine**: reconstructed L2 book
- **KlineProvider**: CLOSED 1h/1d klines + funding via REST with a short
  cache. **Injectable**: backtests swap in a historical provider → the
  same strategy code runs live and in simulation
- **PositioningCollector**: archives positioning series (top trader L/S,
  OI, taker ratio) that the exchange only exposes for ~30 days

### `src/engine/` — features and gating
- **OrderflowEngine**: unified `MarketSnapshot` (delta, multi-TF CVD,
  imbalance, Kyle's lambda)
- **RegimeDetector**: TREND_UP/DOWN, RANGE, COMPRESSION, EXPANSION
- **ScoringEngine**: `should_trade(strategy, regime)` called before EVERY
  scan; per-strategy regime rules + persisted rolling scoring

### `src/strategies/` — plugins
Immutable `BaseStrategy` interface: `scan()`, `execute_entry(signal)`,
`manage_positions()`. The active ones (TB/FS/MC) are described in
[02_strategies.md](02_strategies.md); legacy ones remain in the codebase
but disabled. Multi-symbol creates one instance per symbol.

### `src/journal/` + `src/monitoring/` — observability
- **TradeLogger** → `data/journal.db` (SQLite): every trade with full
  entry/exit context, P&L, R-multiple
- **SignalLog** → executed AND blocked signals (with the reason)
- **TelegramAlerts**: notifications
- **dashboard_app/**: multi-page Streamlit dashboard (below)

## Dashboard (`src/monitoring/dashboard_app/`)

A process **separate** from the bot. Reads journal.db (sqlite read-only),
state JSON files, `.env` and Deribit via REST.

| Page | Contents |
|---|---|
| Live trades | equity, positions with unrealized P&L and owning strategy, venue orders, **reconciliation**: orphan orders and SL-less positions highlighted in red |
| Risk & Exposure | gross-cap utilization, kill switch, vol-target bucket, per-symbol macro state, strategy×side enablement matrix |
| Trade history | closed trades with precise amounts, filters, aggregates (WR/PF/expectancy), CSV export, equity curve |
| Market context | funding history, positioning series (C8 archive), Fear & Greed, on-chain miner health + AI export snapshot |
| Settings | guard-railed `.env` editor: validated ranges as bounds, diff + confirmation, automatic backup, subprocess validation with auto-restore; secrets never displayed |
| Actions | manual kill switch, type-to-confirm position close (reduce-only), on-demand orphan cleanup — double confirmation + **audit log** |

Write actions go through **flag files** the bot re-reads in its loops —
the dashboard never calls into the bot process.

## Design invariants

1. The `BaseStrategy` interface does not change — strategies are plugins.
2. An open position ALWAYS has a stop on the venue (retry + emergency
   close at order placement).
3. The injectable data provider is the only data boundary of the
   validated strategies: identical code live/backtest.
4. The dashboard core is read-only: every action goes through files the
   bot re-reads, never direct calls into the bot process.
5. Active-strategy parameters are VALIDATED: changing them invalidates
   the backtest (re-run the validation pipeline).
