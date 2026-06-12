# Architettura di sistema

> Aggiornato: giugno 2026, dopo il ribaltamento verso le strategie
> quantitative validate (TB/FS/MC). La versione precedente di questo
> documento è in [archive/01_architecture.md](archive/01_architecture.md).

## Vista d'insieme

```
BINANCE FUTURES (dati, gratuiti)              DERIBIT (esecuzione)
  WS: aggTrade/depth/forceOrder                 REST privato
  REST: klines 1h/1d, funding                        ^
        |                |                           |
        v                v                           |
  BinanceDataIngestion  KlineProvider     OrderManager + OrderRegistry
        |                |  (iniettabile)            ^
        v                |                           |
  OrderBookEngine        |                           |
  OrderflowEngine        +-----> STRATEGIE ----------+
  RegimeDetector ---------------> TB / FS / MC       |
  ScoringEngine  ----------------^ (should_trade)    |
                                                     |
                              RiskManager (sizing + cap + kill switch)
                              PositionMonitor (orfani, riconciliazione)
                              FailureHandler (health, emergency)
                                       |
                  TradeLogger (journal.db) + SignalLog + PositionLog
                  TelegramAlerts
                                       |
              DASHBOARD STREAMLIT (processo separato, sola lettura)
```

## Processo principale: `src/async_trading_bot.py`

Bot asyncio con task concorrenti:

| Loop | Periodo | Cosa fa |
|---|---|---|
| scan loop | 15 min (`MONITORING_INTERVAL_MINUTES`) | per ogni strategia: `ScoringEngine.should_trade` → `scan()` → `execute_entry()` |
| management loop | 30 s | `manage_positions()` di ogni strategia + `check_orphan_orders` (BTC+ETH) |
| orderbook loop | continuo | snapshot depth + delta WS (protocollo: `fetch_depth_snapshots` → `apply_snapshot` PRIMA dei delta) |
| outcome tracker | 30 min | risolve WIN/LOSS dei segnali nel SignalLog |
| health loop | 5 s | `FailureHandler`: API down > 30s → emergency close |

`src/trading_bot.py` è il bot sync legacy (schedule-based): ancora
funzionante, non più sviluppato.

## Strati

### `src/core/` — venue e rischio
- **DeribitClient**: REST autenticato (testnet/prod via `DERIBIT_ENV`)
- **OrderManager**: `execute_generic_trade` = entry market + SL stop_market
  reduce-only (retry 3×, poi EMERGENCY CLOSE — mai posizioni nude) + TP
  limit reduce-only, tutto registrato nell'**OrderRegistry**
  (trade → {sl_id, tp_id}) per il cleanup orfani
- **PositionMonitor**: posizioni venue, `check_orphan_orders`
- **RiskManager**: sizing 3-factor, `MAX_GROSS_EXPOSURE`, kill switch
  (vedi [05_risk_sizing.md](05_risk_sizing.md))
- **FailureHandler**: health check e reazioni ai guasti

### `src/data/` — ingestione
- **BinanceDataIngestion**: WS tick-by-tick (trades, depth, liquidazioni)
- **OrderBookEngine**: book L2 ricostruito
- **KlineProvider** (`kline_provider.py`): klines 1h/1d CHIUSE + funding via
  REST con cache breve. **Iniettabile**: i backtest lo sostituiscono con un
  provider storico → stesso codice strategia live e in simulazione
- **DataQuality**: validazione stream

### `src/engine/` — feature e gating
- **OrderflowEngine**: `MarketSnapshot` unificato (delta, CVD multi-TF,
  imbalance, Kyle's lambda) — oggi serve principalmente il RegimeDetector
- **RegimeDetector**: TREND_UP/DOWN, RANGE, COMPRESSION, EXPANSION
- **ScoringEngine**: `should_trade(strategy, regime)` chiamato prima di OGNI
  scan; REGIME_RULES per strategia + scoring rolling persistito
  (`data/scoring_state.json`)

### `src/strategies/` — plugin
Interfaccia immutabile `BaseStrategy`: `scan()`, `execute_entry(signal)`,
`manage_positions()`. Le attive (TB/FS/MC) sono descritte in
[02_strategies.md](02_strategies.md); le legacy restano nel codice ma
disattivate da `.env`. Il multi-symbol crea un'istanza per simbolo
(`TB_SYMBOLS=BTCUSDT,ETHUSDT` → 2 istanze con strumento Deribit derivato).

### `src/journal/` + `src/monitoring/` — osservabilità
- **TradeLogger** → `data/journal.db` (SQLite): ogni trade con contesto
  completo entry/exit, P&L, R-multiple
- **SignalLog** → `data/signal_log.db`: segnali eseguiti E bloccati (col
  motivo) + outcome tracker
- **PositionLog** → `logs/positions.log` (storico umano-leggibile)
- **TelegramAlerts**: notifiche
- **dashboard_app/**: dashboard Streamlit multipagina (sotto)

## Dashboard (`src/monitoring/dashboard_app/`)

Processo **separato** dal bot: `streamlit run scripts/run_dashboard.py`.
Legge journal.db (sqlite `mode=ro`), state JSON, `.env` e Deribit via REST
(solo GET). Non importa mai il bot in esecuzione.

| Pagina | Contenuto |
|---|---|
| Trade in corso | equity, posizioni con P&L non realizzato e strategia proprietaria, ordini sul venue, **riconciliazione**: ordini orfani e posizioni senza SL in rosso |
| Rischio & Esposizione | utilizzo `MAX_GROSS_EXPOSURE`, kill switch, vol-target MC, stato macro per simbolo, matrice strategia×lato abilitato |
| Storico Operazioni | trade chiusi con importi precisi, filtri, aggregati (WR/PF/expectancy), export CSV, equity curve |

Piano completo (fasi 3-5 future: editor `.env`, azioni operative):
[../microevolutive/PLAN_DASHBOARD.md](../microevolutive/PLAN_DASHBOARD.md).

## Backtest e validazione

- `src/backtest/`: BacktestEngine (swap di `order_manager` con mock),
  metriche, Monte Carlo — vedi
  [06_backtest_montecarlo.md](06_backtest_montecarlo.md)
- La validazione delle strategie attive usa script dedicati che iniettano
  il KlineProvider storico sul **codice reale**:
  `scripts/backtest_new_strategies.py`, `scripts/backtest_macro_core.py`,
  `scripts/equity_sim.py`, `scripts/validate_symbol.py`
- Dataset nel repo: `data/research/{btc,eth}_1m_4y/` + funding 4y

## Invarianti di design

1. L'interfaccia `BaseStrategy` non si cambia — le strategie sono plugin.
2. Una posizione aperta ha SEMPRE uno stop sul venue (retry + emergency
   close in `execute_generic_trade`).
3. Il `KlineProvider` è l'unico confine dati delle strategie validate:
   iniettabile, stesso codice live/backtest.
4. La dashboard non scrive: ogni azione futura (fasi 3-4) passa da file
   che il bot rilegge, mai chiamate nel processo bot.
5. I parametri delle strategie attive sono VALIDATI: modificarli invalida
   il backtest (rivalidare con la pipeline §1 del piano).
