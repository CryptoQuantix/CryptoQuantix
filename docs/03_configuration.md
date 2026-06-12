# Configurazione — il file `.env`

> Aggiornato: giugno 2026. Il `.env` è organizzato in tre blocchi:
> **operativo** (API, rischio, monitoring), **STRATEGIE ATTIVE** (parametri
> validati — non toccare senza rivalidare) e **STRATEGIE DISATTIVATE**
> (bocciate coi dati, col verdetto in commento). Il bot legge il `.env`
> SOLO all'avvio: ogni modifica richiede un riavvio.

## Blocco operativo

```env
# Deribit
DERIBIT_API_KEY=...           # mai committare; la dashboard non li mostra
DERIBIT_API_SECRET=...
DERIBIT_ENV=test              # test | live

# Risk management (vedi 05_risk_sizing.md)
INITIAL_EQUITY=10000
BASE_RISK_PCT=0.01            # 1% rischio per trade tattico
MAX_DAILY_LOSS_PCT=0.03       # kill switch dopo -3% giornaliero
MAX_OPEN_TRADES=3             # max posizioni aperte sul venue
MAX_GROSS_EXPOSURE=1.5        # nozionale lordo aggregato max 1.5x equity

# Monitoring
MONITORING_INTERVAL_MINUTES=15   # frequenza scan segnali
HEALTH_CHECK_INTERVAL_SEC=5
MAX_API_DOWN_SEC=30              # emergency close dopo 30s di API down
LOG_LEVEL=INFO

# Telegram (opzionale, vuoto = disabilitato)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

## Strategie attive

I parametri di default sono quelli VALIDATI sui 4 anni. I range provati e i
risultati sono nei report (`data/research/`); cambiare un parametro
significa uscire dalla validazione → ripassare la pipeline
([../microevolutive/PLAN_BULL_EVOLUTION.md](../microevolutive/PLAN_BULL_EVOLUTION.md) §1).

### Multi-symbol
`TB_SYMBOLS` / `FS_SYMBOLS` / `MC_SYMBOLS` accettano una lista
(`BTCUSDT,ETHUSDT`): il bot crea UN'ISTANZA per simbolo con lo strumento
Deribit derivato (`ETHUSDT` → `ETH-PERPETUAL`). Limitazioni validate:

- `TB_SHORT_SYMBOLS=BTCUSDT` — lo short TB su ETH è bocciato (PF 0.87)
- `MC_SYMBOLS=BTCUSDT` — MacroCore su ETH bocciata; con più simboli il
  budget di esposizione core si divide per N

### Trend Breakdown (prefisso `TB_`)

| Variabile | Default | Note |
|---|---|---|
| `TB_ENABLED` | true | |
| `TB_SYMBOLS` | BTCUSDT,ETHUSDT | un'istanza per simbolo |
| `TB_SHORT_SYMBOLS` | BTCUSDT | short solo dove validato |
| `TB_LOOKBACK_H` | 48 | Donchian low short (barre 1h) |
| `TB_LOOKBACK_LONG_H` | 168 | Donchian high long (7 giorni) |
| `TB_SMA_H` | 48 | filtro trend orario |
| `TB_SL_ATR_MULT` | 2.0 | stop = 2×ATR(1h,14) |
| `TB_RR_RATIO` | 2.0 | TP short = 2R |
| `TB_RR_LONG` | 0 | 0 = nessun TP sui long (let winners run) |
| `TB_MAX_HOLD_HOURS` | 24 | time exit short |
| `TB_MAX_HOLD_LONG_HOURS` | 168 | time exit long |
| `TB_FLOW_CONFIRM` | 0.50 | gate buy_ratio |
| `TB_MACRO_SMA_DAYS` | 200 | gate macro daily |

### Funding Squeeze (prefisso `FS_`)

| Variabile | Default | Note |
|---|---|---|
| `FS_ENABLED` | true | |
| `FS_SYMBOLS` | BTCUSDT,ETHUSDT | |
| `FS_FUNDING_THRESHOLD` | 0.0001 | 0.01%/8h = cap exchange su BTC |
| `FS_SMA_H` | 48 | prezzo sotto SMA48 oraria |
| `FS_SL_ATR_MULT` | 2.0 | |
| `FS_TP_RR` | 2.0 | |
| `FS_MAX_HOLD_HOURS` | 24 | |
| `FS_COOLDOWN_HOURS` | 8 | un trade per finestra funding |
| `FS_MACRO_SMA_DAYS` | 200 | gate bear |
| `FS_SLOPE_DAYS` | 30 | SMA200d più bassa di 30gg fa |
| `FS_ENTRY_WINDOW_MIN` | 60 | entra solo dopo il settlement (00/08/16 UTC) |

### Macro Core (prefisso `MC_`)

| Variabile | Default | Note |
|---|---|---|
| `MC_ENABLED` | true | |
| `MC_SYMBOLS` | BTCUSDT | solo BTC (ETH bocciata) |
| `MC_SMA_DAYS` | 200 | filtro macro daily |
| `MC_ATR_DAYS` | 20 | ATR per il chandelier |
| `MC_CHANDELIER_K` | 5.0 | plateau robusto 4.5-6 |
| `MC_DISASTER_SL_PCT` | 0.25 | stop venue -25% (bot offline) |
| `MC_EXPOSURE_FRACTION` | 1.0 | size core = equity × frazione |
| `MC_VOL_TARGET` | 0.30 | vol-target annualizzata (0 = off) |
| `MC_VOL_LOOKBACK_DAYS` | 30 | finestra vol realizzata |
| `MC_EXPO_STEP` | 0.25 | bucket di esposizione |
| `MC_STATE_PATH` | data/macro_core_state.json | stato persistente |

## Strategie disattivate

Tutte con `*_ENABLED=false` e il verdetto della validazione in commento nel
`.env`. **Non riattivare senza nuova validazione completa.**

```env
VB_ENABLED=false        # Volume Breakout : PF 0.42-0.74 — nessun edge
MR_ENABLED=false        # Mean Reversion  : PF 0.28-0.53
LIQ_ENABLED=false       # Liq Squeeze     : PF 0.06-0.30
IS_ENABLED=false        # Imbalance Scalp : fee-bound, PF 0.18-0.50
BRINGS_ENABLED=false    # NY Brings       : PF 0.64, negativa ogni anno
WM_ENABLED=false        # W/M Formation   : edge non strutturale
STRATEGY_SMART_MONEY_ENABLED=false
STRATEGY_IRON_CONDOR_ENABLED=false   # opzioni, fuori direzione progetto
```

## Note

- `Config.load_strategies()` ([../config.py](../config.py)) è l'unico punto
  che traduce il `.env` in istanze: la dashboard usa la stessa funzione,
  quindi vede esattamente le istanze del bot.
- Testnet: l'equity di sizing è cappata a $50k (i faucet testnet gonfiano
  l'equity e produrrebbero ordini fuori scala).
- Validazione config all'avvio: chiavi mancanti o `DERIBIT_ENV` non valido
  bloccano il bootstrap.
