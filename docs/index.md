# coinmaker-quant — Documentazione

Bot di trading quantitativo su futures/perpetual: esecuzione **Deribit**,
dati **Binance Futures**. Tre strategie validate su 4 anni multi-ciclo,
macro-gating automatico, risk management di portafoglio, dashboard.

> Aggiornato: giugno 2026 (ribaltamento completo: dalle strategie
> volumetriche intraday alle quantitative validate TB/FS/MC).

## Documenti correnti

| Documento | Contenuto |
|---|---|
| [01_architecture.md](01_architecture.md) | Architettura: bot async, layer, dashboard, invarianti |
| [02_strategies.md](02_strategies.md) | Trend Breakdown, Funding Squeeze, Macro Core + bocciate |
| [03_configuration.md](03_configuration.md) | Il `.env` completo: operativo, attive, disattivate |
| [05_risk_sizing.md](05_risk_sizing.md) | Sizing 3-factor, gross cap, kill switch, vol-target |

## Infrastruttura (validi, pre-ribaltamento)

| Documento | Contenuto |
|---|---|
| [02_data_microstructure.md](02_data_microstructure.md) | Binance WS, order book L2, microstruttura |
| [03_orderflow_math.md](03_orderflow_math.md) | Delta, CVD, Kyle's Lambda (alimentano il regime) |
| [06_backtest_montecarlo.md](06_backtest_montecarlo.md) | BacktestEngine, metriche, Monte Carlo |
| [07_execution_ops.md](07_execution_ops.md) | API Deribit, ordini, deploy |

## Ricerca e validazione (fonte di verità per i numeri)

| Risorsa | Contenuto |
|---|---|
| [../microevolutive/PLAN_BULL_EVOLUTION.md](../microevolutive/PLAN_BULL_EVOLUTION.md) | Pipeline di validazione + risultati C1-C7 |
| [../microevolutive/PLAN_DASHBOARD.md](../microevolutive/PLAN_DASHBOARD.md) | Piano dashboard (fasi 1-2 fatte, 3-5 future) |
| `../data/research/multicycle_report.txt` | Validazione 4y delle strategie |
| `../data/research/eth_validation.txt` | Multi-symbol ETH (C3) |
| `../data/research/legacy_validation_btc.txt` | Bocciatura legacy (C7) |

## Storico

[archive/](archive/) contiene i documenti superati dal ribaltamento di
giugno 2026 (vecchia architettura, strategie volumetriche, smart money,
piani di profittabilità, guide setup originali). Utili solo come storia
del progetto.
