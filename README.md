# cryptoquantix

[🇮🇹 Versione in Italiano](README_it.md)

**Quantitative trading bot for crypto futures/perpetuals** — Deribit for execution, Binance Futures for data. Features three strategies validated over 4 years of data (Jun 2022 → Jun 2026, bear + bull + bear), automatic macro-gating, portfolio risk management, and a monitoring dashboard.

> **June 2026 Pivot**: The bot started as an intraday volumetric system (4 orderflow strategies). Multi-cycle validation proved those strategies lacked a statistical edge → they were deactivated and replaced by 3 validated quantitative strategies. Historical documents can be found in [docs/archive/](docs/archive/).

---

## The 3 Active Strategies

Backtest figures are based on real code, 4 years of BTCUSDT/ETHUSDT 1m data, 0.20% roundtrip costs, and no lookahead bias. Source of truth: [microevolutive/PLAN_BULL_EVOLUTION.md](microevolutive/PLAN_BULL_EVOLUTION.md) and reports in `data/research/`.

| Strategy | Logic | Validation (BTC, 4y) |
|---|---|---|
| **Trend Breakdown** | SHORT on 48h-low breakdown in macro BEAR; LONG on 7d-high breakout in macro BULL (no TP, hold 7d) | short +22 bps PF 1.26 (123 tr) · long +68 bps PF 1.53 (84 tr) |
| **Funding Squeeze** | Contrarian SHORT when funding hits the cap AND 200d SMA is falling (deep-bear capitulation) | +74 bps PF 2.65 (15 tr) · ETH +64 bps PF 1.82 |
| **Macro Core** | Core Long above 200d SMA, chandelier exit at 5×ATR20d, 30% vol-target | +315%/4y vs +136% B&H, maxDD 24.7% (9 tr) |

Live instances: TB on BTC+ETH (shorts only on BTC — failed on ETH), FS on BTC+ETH, MC only on BTC (failed on ETH). Simulated portfolio equity (C4): +491%/4y with maxDD 21.5%, Calmar 2.61, worst year 0%.

**The bot automatically adapts to the market** on 3 levels:
1. **Macro gate** (daily 200d SMA): each side of every strategy is structurally disabled in adverse phases (e.g., no TB longs in a bear market);
2. **Hourly regime** (ScoringEngine + RegimeDetector: TREND/RANGE/COMPRESSION/EXPANSION) with strategy-specific rules;
3. **Rolling scoring**: a strategy underperforming in live trading is automatically disabled.

## Portfolio Risk Management

- **3-factor Sizing** for tactical trades: 1% base risk × volatility scalar × regime scalar × fractional Kelly (25% cap)
- **`MAX_GROSS_EXPOSURE=1.5`**: total aggregate gross notional of ALL strategies combined does not exceed 1.5× equity (anti-oversizing)
- **Daily kill switch**: -3% in a single day → stops new entries
- **No naked positions ever**: market entry, SL with 3× retry and emergency close if it fails; orphan orders cleaned every 30s
- **30% Vol-target** on Macro Core: exposure is reduced in buckets when 30d realized volatility rises

Details: [docs/05_risk_sizing.en.md](docs/05_risk_sizing.en.md).

## Quick Start

```bash
git clone <repo>
cd cryptoquantix
pip install -r requirements.txt
cp .env.example .env   # then insert your Deribit API keys
```

Minimal `.env` (active strategies have validated defaults — do not touch them without revalidating):

```env
DERIBIT_API_KEY=...
DERIBIT_API_SECRET=...
DERIBIT_ENV=test            # test | live

INITIAL_EQUITY=10000
BASE_RISK_PCT=0.01
MAX_DAILY_LOSS_PCT=0.03
MAX_OPEN_TRADES=3
MAX_GROSS_EXPOSURE=1.5
```

Startup:

```bash
python -m src.async_trading_bot        # async bot (recommended)
python main.py                         # legacy sync bot
scripts\run_dashboard.bat              # Streamlit dashboard (separate process)
```

Risk-free dry run:

```bash
scripts/run_dry_run.bat strategies     # strategy logic only, no internet
scripts/run_dry_run.bat full --duration 120   # full paper trading
```

## Dashboard

`streamlit run scripts/run_dashboard.py` — runs as a separate process:

- **Live Trades**: positions and orders on the venue, unrealized P&L, reconciliation highlighting orphan orders and positions without SL in red
- **Risk & Exposure**: gross cap utilization, kill switch, vol-target bucket, macro state per symbol, and matrix of who can trade what now
- **Trade History**: every closed trade with precise figures (USD size, $ P&L, R, exit reason), filters, aggregates, CSV export, equity curve
- **Settings**: `.env` editor with guardrails — validated ranges, diff with confirmation, automatic backup, validation with rollback; secrets never displayed; bot restart request via flag
- **Actions** (double confirmation + audit log): manual kill switch, reduce-only position close, on-demand orphan order cleanup

## Documentation

| Document | Content |
|---|---|
| [docs/01_architecture.en.md](docs/01_architecture.en.md) | Architecture: async bot, data layer, engine, strategies, monitoring |
| [docs/02_strategies.en.md](docs/02_strategies.en.md) | The 3 active strategies: logic, parameters, validation metrics |
| [docs/03_configuration.en.md](docs/03_configuration.en.md) | The `.env`: active, risk, and deactivated settings |
| [docs/05_risk_sizing.en.md](docs/05_risk_sizing.en.md) | Sizing, exposure cap, kill switch, vol-target |
| [docs/02_data_microstructure.en.md](docs/02_data_microstructure.en.md) | Binance WS Data layer (infrastructure) |
| [docs/03_orderflow_math.en.md](docs/03_orderflow_math.en.md) | Orderflow engine (feeds regime detection) |
| [docs/06_backtest_montecarlo.en.md](docs/06_backtest_montecarlo.en.md) | Backtest engine and Monte Carlo |
| [docs/07_execution_ops.en.md](docs/07_execution_ops.en.md) | Deribit execution and operations |
| [microevolutive/](microevolutive/) | Evolution plans and validation pipeline results |
| [docs/archive/](docs/archive/) | Historical documents (pre-June 2026 pivot) |

## Project Structure

```
cryptoquantix/
├── src/
│   ├── core/          deribit_client, order_manager, order_registry,
│   │                  position_monitor, risk_manager, failure_handler
│   ├── data/          binance_ingestion, orderbook_engine, kline_provider
│   ├── engine/        orderflow, regime, scoring
│   ├── strategies/    trend_breakdown, funding_squeeze, macro_core (ACTIVE)
│   │                  + deactivated legacy (vb, mr, liq, is, wm, brings, ...)
│   ├── monitoring/    alerts (Telegram), dashboard_app/ (Streamlit multi-page)
│   ├── journal/       trade_logger (SQLite), signal_log, analytics
│   ├── backtest/      backtest_engine, metrics, monte_carlo
│   └── async_trading_bot.py
├── scripts/           run_dashboard, dry_run_*, backtest_*, equity_sim
├── microevolutive/    evolution and validation plans
├── data/research/     4y BTC/ETH datasets + validation reports
└── docs/              documentation (archive/ = historical)
```

## Validation Process (Why trust the numbers)

Before deployment, every strategy passes the pipeline defined in [microevolutive/PLAN_BULL_EVOLUTION.md](microevolutive/PLAN_BULL_EVOLUTION.md): real-code backtest (no reimplementation), 4-year multi-cycle, realistic costs, IS/OOS, PF ≥ 1.2, robustness to neighboring parameters.
Live guardrails: rolling PF < 0.8 over ≥ 30 trades → deactivation; drawdown > 1.5× backtest maxDD → immediate deactivation.

Historical strategies (Volume Breakout, Mean Reversion, Liq Squeeze, Imbalance Scalp, NY Brings, W/M, Smart Money, Iron Condor) went through the same pipeline and were **rejected by the data** — they remain in the codebase but deactivated, with the verdict documented in `.env` and in reports `data/research/multicycle_report.txt` and `data/research/legacy_validation_btc.txt`.

## License

**Source-available with dual licensing** (full text in [LICENSE](LICENSE)):

- **Non-commercial use** — free under [PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/): study, modify, redistribute, and trade your **own** personal capital.
- **Commercial use** — **requires a paid license**: trading third-party capital, providing services/signals based on the software, product integration, trading on behalf of clients. The commercial license includes full operational strategy specifications and complete validation reports.

Contact: **lantoniotrento@gmail.com**
