# cryptoquantix

**Bot di trading quantitativo su futures/perpetual crypto** — Deribit per
l'esecuzione, Binance Futures per i dati. Tre strategie validate su 4 anni
di dati (giu 2022 → giu 2026, bear + bull + bear), macro-gating automatico,
risk management di portafoglio e dashboard di monitoraggio.

> **Ribaltamento giugno 2026**: il bot nasceva come sistema volumetrico
> intraday (4 strategie orderflow). La validazione multi-ciclo ha dimostrato
> che quelle strategie non hanno edge → sono state disattivate e sostituite
> da 3 strategie quantitative validate. I documenti storici sono in
> [docs/archive/](docs/archive/).

---

## Le 3 strategie attive

Numeri da backtest sul codice reale, 4 anni BTCUSDT/ETHUSDT 1m,
costi 0.20% roundtrip, nessun lookahead. Fonte di verità:
[microevolutive/PLAN_BULL_EVOLUTION.md](microevolutive/PLAN_BULL_EVOLUTION.md)
e i report in `data/research/`.

| Strategia | Logica | Validazione (BTC, 4y) |
|---|---|---|
| **Trend Breakdown** | SHORT breakdown 48h-low in macro BEAR; LONG breakout 7d-high in macro BULL (no TP, hold 7gg) | short +22 bps PF 1.26 (123 tr) · long +68 bps PF 1.53 (84 tr) |
| **Funding Squeeze** | SHORT contrarian quando il funding è al cap E la SMA200d scende (capitolazione deep-bear) | +74 bps PF 2.65 (15 tr) · ETH +64 bps PF 1.82 |
| **Macro Core** | Long core sopra SMA200d, exit chandelier 5×ATR20d, vol-target 30% | +315%/4y vs +136% B&H, maxDD 24.7% (9 tr) |

Istanze live: TB su BTC+ETH (short solo BTC — su ETH è bocciato), FS su
BTC+ETH, MC solo BTC (su ETH bocciata). Equity sim di portafoglio (C4):
+491%/4y con maxDD 21.5%, Calmar 2.61, peggior anno 0%.

**Il bot si adatta da solo al mercato**, su 3 livelli:
1. **Macro gate** (SMA200d daily): ogni lato di ogni strategia è
   strutturalmente spento nella fase avversa (es. niente long TB in bear);
2. **Regime orario** (ScoringEngine + RegimeDetector: TREND/RANGE/
   COMPRESSION/EXPANSION) con regole per strategia;
3. **Scoring rolling**: una strategia che sotto-performa live viene
   disattivata automaticamente.

## Risk management di portafoglio

- **Sizing 3-factor** per i trade tattici: rischio base 1% × scalar
  volatilità × scalar regime × Kelly frazionario (cap 25%)
- **`MAX_GROSS_EXPOSURE=1.5`**: il nozionale lordo aggregato di TUTTE le
  strategie insieme non supera 1.5× l'equity (anti-oversizing)
- **Kill switch giornaliero**: -3% in un giorno → stop nuovi ingressi
- **Mai posizioni nude**: entry market, SL con retry 3× e, se fallisce,
  chiusura di emergenza; cleanup ordini orfani ogni 30s
- **Vol-target 30%** sul Macro Core: esposizione ridotta a bucket quando la
  vol realizzata 30d sale

Dettagli: [docs/05_risk_sizing.md](docs/05_risk_sizing.md).

## Quick start

```bash
git clone <repo>
cd cryptoquantix
pip install -r requirements.txt
cp .env.example .env   # poi inserire le chiavi Deribit
```

`.env` minimo (le strategie attive hanno default validati — non toccarli
senza rivalidare):

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

Avvio:

```bash
python -m src.async_trading_bot        # bot asincrono (consigliato)
python main.py                         # bot sync legacy
scripts\run_dashboard.bat              # dashboard Streamlit (processo separato)
```

Dry run senza rischio:

```bash
scripts/run_dry_run.bat strategies     # logica strategie, no internet
scripts/run_dry_run.bat full --duration 120   # paper trading completo
```

## Dashboard

`streamlit run scripts/run_dashboard.py` — processo separato dal bot:

- **Trade in corso**: posizioni e ordini sul venue, P&L non realizzato,
  riconciliazione con evidenza in rosso di ordini orfani e posizioni senza SL
- **Rischio & Esposizione**: utilizzo del cap lordo, kill switch, bucket
  vol-target, stato macro per simbolo e matrice di chi può tradare cosa ora
- **Storico Operazioni**: ogni trade chiuso con importi precisi (size USD,
  P&L $, R, motivo uscita), filtri, aggregati, export CSV, equity curve
- **Impostazioni**: editor `.env` con guardrail — range validati, diff con
  conferma, backup automatico, validazione con ripristino; secrets mai a
  schermo; richiesta riavvio bot via flag
- **Azioni** (conferma doppia + audit log): kill switch manuale, chiusura
  posizione reduce-only, pulizia ordini orfani on-demand

## Documentazione

| Documento | Contenuto |
|---|---|
| [docs/01_architecture.md](docs/01_architecture.md) | Architettura: bot async, data layer, engine, strategie, monitoring |
| [docs/02_strategies.md](docs/02_strategies.md) | Le 3 strategie attive: logica, parametri, numeri di validazione |
| [docs/03_configuration.md](docs/03_configuration.md) | Il `.env`: attive, rischio, disattivate |
| [docs/05_risk_sizing.md](docs/05_risk_sizing.md) | Sizing, cap di esposizione, kill switch, vol-target |
| [docs/02_data_microstructure.md](docs/02_data_microstructure.md) | Data layer Binance WS (infrastruttura) |
| [docs/03_orderflow_math.md](docs/03_orderflow_math.md) | Orderflow engine (alimenta il regime detection) |
| [docs/06_backtest_montecarlo.md](docs/06_backtest_montecarlo.md) | Backtest engine e Monte Carlo |
| [docs/07_execution_ops.md](docs/07_execution_ops.md) | Esecuzione Deribit e operations |
| [microevolutive/](microevolutive/) | Piani e risultati della pipeline di validazione |
| [docs/archive/](docs/archive/) | Documenti storici (pre-ribaltamento giu 2026) |

## Struttura progetto

```
cryptoquantix/
├── src/
│   ├── core/          deribit_client, order_manager, order_registry,
│   │                  position_monitor, risk_manager, failure_handler
│   ├── data/          binance_ingestion, orderbook_engine, kline_provider
│   ├── engine/        orderflow, regime, scoring
│   ├── strategies/    trend_breakdown, funding_squeeze, macro_core (ATTIVE)
│   │                  + legacy disattivate (vb, mr, liq, is, wm, brings, ...)
│   ├── monitoring/    alerts (Telegram), dashboard_app/ (Streamlit multipagina)
│   ├── journal/       trade_logger (SQLite), signal_log, analytics
│   ├── backtest/      backtest_engine, metrics, monte_carlo
│   └── async_trading_bot.py
├── scripts/           run_dashboard, dry_run_*, backtest_*, equity_sim
├── microevolutive/    piani di evoluzione e validazione
├── data/research/     dataset 4y BTC/ETH + report di validazione
└── docs/              documentazione (archive/ = storico)
```

## Processo di validazione (perché fidarsi dei numeri)

Ogni strategia, prima del deploy, passa la pipeline definita in
[microevolutive/PLAN_BULL_EVOLUTION.md](microevolutive/PLAN_BULL_EVOLUTION.md):
backtest sul codice reale (non su una reimplementazione), 4 anni multi-ciclo,
costi realistici, IS/OOS, PF ≥ 1.2, robustezza ai parametri vicini.
Guardrail live: PF rolling < 0.8 dopo ≥ 30 trade → disattivazione;
drawdown > 1.5× il maxDD di backtest → disattivazione immediata.

Le strategie storiche (Volume Breakout, Mean Reversion, Liq Squeeze,
Imbalance Scalp, NY Brings, W/M, Smart Money, Iron Condor) sono state
validate con la stessa pipeline e **bocciate coi dati** — restano nel
codice ma disattivate, col verdetto documentato nel `.env` e nei report
`data/research/multicycle_report.txt` e `data/research/legacy_validation_btc.txt`.
