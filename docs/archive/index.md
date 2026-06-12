# Coinmaker Quant

Bot di trading futures volumetrico su **Deribit** con dati tick-by-tick da **Binance Futures**.

---

## Architettura

- [Overview Sistema](01_architecture.md) — componenti core, asyncio tasks, pipeline
- [Dati & Microstruttura](02_data_microstructure.md) — BinanceDataIngestion, OrderBookEngine
- [Orderflow & CVD](03_orderflow_math.md) — Delta, CVD multi-timeframe, Kyle's Lambda

## Strategie

- [Regime & Strategie Quantitative](04_regime_strategies.md) — RegimeDetector, 4 strategie
- [Contesto di Mercato — Quando Accendere](08_market_context.md) — playbook attivazione/disattivazione

## Risk & Backtest

- [Risk & Sizing](05_risk_sizing.md) — RiskManager 3-factor, position sizing
- [Backtest Engine & Monte Carlo](06_backtest_montecarlo.md) — architettura backtest
- [Piano di Validazione & Profittabilita](09_profitability_plan.md) — 60gg testnet, Signal Log, analisi SQLite

## Deployment

- [Esecuzione & Ops](07_execution_ops.md) — Deribit API, Docker, Raspberry Pi

---

## Quick Start

```bash
# 1. Configura le credenziali
cp .env.example .env
# Edita .env con API keys Deribit

# 2. Avvia con Docker
./docker-start.sh

# 3. Controlla i log
docker logs -f coinmaker-bot
```

## Comandi Utili

```bash
# Stato del Signal Log (opportunita perse)
docker exec coinmaker-bot python -c "
from src.journal.signal_log import SignalLog
SignalLog('data/signal_log.db').print_report()
"

# Scarica i database per analisi (al giorno 60)
docker cp coinmaker-bot:/app/data/signal_log.db ./signal_log.db
docker cp coinmaker-bot:/app/data/journal.db    ./journal.db

# Chiudi tutte le posizioni (emergenza)
python close_all_positions.py
```

## Documentazione Locale

```bash
pip install mkdocs-material
mkdocs serve
```

Poi apri `http://127.0.0.1:8000`.
