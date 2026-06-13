# Configurazione — il file `.env`

!!! info "Struttura"

    Il `.env` è organizzato in tre blocchi: **operativo** (API, rischio,
    monitoring), **STRATEGIE ATTIVE** (parametri validati — non toccare
    senza rivalidare) e **STRATEGIE DISATTIVATE** (bocciate coi dati, col
    verdetto in commento). Il bot legge il `.env` SOLO all'avvio: ogni
    modifica richiede un riavvio.

## Blocco operativo

```env
# Deribit
DERIBIT_API_KEY=...           # mai committare; la dashboard non li mostra
DERIBIT_API_SECRET=...
DERIBIT_ENV=test              # test | prod

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

Ogni strategia si abilita con `TB_ENABLED` / `FS_ENABLED` / `MC_ENABLED` e
ha il proprio blocco di parametri nel `.env` (prefissi `TB_`, `FS_`, `MC_`).
I default sono i valori **validati sui 4 anni**: cambiare un parametro
significa uscire dalla validazione → ripassare la pipeline prima di
fidarsi dei risultati.

### Multi-symbol
`TB_SYMBOLS` / `FS_SYMBOLS` / `MC_SYMBOLS` accettano una lista
(`BTCUSDT,ETHUSDT`): il bot crea UN'ISTANZA per simbolo con lo strumento
Deribit derivato (`ETHUSDT` → `ETH-PERPETUAL`). Ogni lato di ogni
strategia è abilitato solo sui simboli dove la validazione è positiva.

!!! warning "🔒 Parametri riservati"

    **Le tabelle complete dei parametri di strategia** (lookback, soglie,
    moltiplicatori e relativi range validati) **sono riservate** —
    disponibili con la licenza commerciale (contatto:
    lantoniotrento@gmail.com). L'editor della dashboard le espone
    comunque all'operatore con i range validati come bound.

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

- `Config.load_strategies()` (`config.py`) è l'unico punto
  che traduce il `.env` in istanze: la dashboard usa la stessa funzione,
  quindi vede esattamente le istanze del bot.
- Testnet: l'equity di sizing è cappata a $50k (i faucet testnet gonfiano
  l'equity e produrrebbero ordini fuori scala).
- Validazione config all'avvio: chiavi mancanti o `DERIBIT_ENV` non valido
  bloccano il bootstrap.
