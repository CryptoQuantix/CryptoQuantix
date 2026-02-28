# coinmaker-quant

**Sistema di trading quantitativo volumetrico su futures crypto**

Dati tick-by-tick da Binance Futures (gratuiti, WebSocket) → feature engine orderflow → strategie multi-modello con scoring → esecuzione su Deribit (futures/perpetual, NO opzioni).

---

## Documentazione Completa

| File | Contenuto |
|------|-----------|
| [docs/01_architecture.md](docs/01_architecture.md) | Architettura sistema, flusso dati, componenti, concorrenza |
| [docs/02_data_microstructure.md](docs/02_data_microstructure.md) | Binance WebSocket, microstruttura mercato, order book L2 |
| [docs/03_orderflow_math.md](docs/03_orderflow_math.md) | Delta, CVD, Kyle's Lambda, VWAP — matematica e implementazione |
| [docs/04_regime_strategies.md](docs/04_regime_strategies.md) | Regime detection + 4 strategie quantitative dettagliate |
| [docs/05_risk_sizing.md](docs/05_risk_sizing.md) | Risk engine 3-factor, Kelly Criterion, kill switch |
| [docs/06_backtest_montecarlo.md](docs/06_backtest_montecarlo.md) | Backtest engine, metriche performance, Monte Carlo bootstrap |
| [docs/07_execution_ops.md](docs/07_execution_ops.md) | Esecuzione Deribit, ordini orfani, monitoring, deploy |

---

## Quick Start

### 1. Installazione

```bash
git clone https://github.com/your-repo/coinmaker-quant
cd coinmaker-quant
pip install -r requirements.txt
```

### 2. Configurazione `.env`

```env
# Deribit API
DERIBIT_API_KEY=your_key
DERIBIT_API_SECRET=your_secret
DERIBIT_ENV=testnet          # oppure: live

# Risk
INITIAL_EQUITY=10000
BASE_RISK_PCT=0.01
MAX_DAILY_LOSS_PCT=0.03
MAX_OPEN_TRADES=3

# Nuove strategie volumetriche
VB_ENABLED=true
MR_ENABLED=true
LIQ_ENABLED=true
IS_ENABLED=true

# Telegram (opzionale)
TELEGRAM_BOT_TOKEN=token
TELEGRAM_CHAT_ID=id
```

### 3. Dry Run

```bash
# Test offline (nessuna connessione richiesta)
python scripts/dry_run_strategies.py --backtest

# Test live Binance 30s
python scripts/dry_run_data.py --duration 30

# Paper trading completo 2 minuti
python scripts/dry_run_full.py --duration 120
```

### 4. Avvio Bot

```bash
# Async (raccomandato)
python -c "import asyncio; from src.async_trading_bot import AsyncTradingBot; asyncio.run(AsyncTradingBot().start())"

# Legacy sync
python main.py
```

---

## Architettura Rapida

```
BINANCE FUTURES WS                     DERIBIT REST
aggTrade / depth / forceOrder          Futures execution
         |                                    ^
         v                                    |
  BinanceDataIngestion              OrderManager + Registry
  trade_queue / depth_queue                   ^
         |                                    |
         v                    signal          |
  OrderBookEngine  ------>  Strategies ------>+
  OrderflowEngine           4 + legacy        |
  RegimeDetector            scoring gate      |
  ScoringEngine                               |
                                        RiskManager
                                        FailureHandler
```

---

## Struttura Progetto

```
coinmaker-quant/
├── src/
│   ├── core/         deribit_client, order_manager, order_registry,
│   │                 position_monitor, risk_manager, failure_handler
│   ├── data/         binance_ingestion, orderbook_engine, data_quality
│   ├── engine/       orderflow, regime, scoring
│   ├── strategies/   volume_breakout, mean_reversion, liq_squeeze,
│   │                 imbalance_scalp + legacy (iron_condor, smart_money, wm, brings)
│   ├── monitoring/   alerts (Telegram), dashboard (Streamlit)
│   ├── journal/      trade_logger (SQLite), analytics
│   ├── backtest/     backtest_engine, metrics, monte_carlo
│   ├── async_trading_bot.py   (principale)
│   └── trading_bot.py         (legacy)
├── scripts/          dry_run_*.py, run_dry_run.bat/.sh
├── data/             raw/ (DuckDB), cleaned/, features/
├── docs/             documentazione tecnica dettagliata
└── logs/
```
