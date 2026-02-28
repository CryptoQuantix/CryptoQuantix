# Struttura del Progetto Coinmaker

## 📁 Panoramica

```
coinmaker/
├── 📄 README.md                    # Documentazione principale
├── 📄 SETUP_GUIDE.md               # Guida setup dettagliata
├── 📄 PROJECT_STRUCTURE.md         # Questo file
├── 📄 SMART_MONEY_STRATEGY.md      # Dettagli strategia Smart Money
├── 📄 idea-progetto.md             # Documento strategia originale
├── 📄 strategia-dettagliata.md     # Dettagli strategia Iron Condor
│
├── 📄 requirements.txt             # Dipendenze Python
├── 📄 .env.example                 # Template configurazione
├── 📄 .gitignore                   # File da ignorare in git
├── 📄 config.py                    # Modulo configurazione
│
├── 🚀 run.bat                      # Script avvio Windows
├── 🚀 run.sh                       # Script avvio Linux/Mac
├── 🧪 test_connection.py           # Test connessione API
│
├── 📂 src/                         # Codice sorgente principale
│   ├── __init__.py
│   ├── 🤖 trading_bot.py           # Bot principale
│   │
│   ├── 📂 core/                    # Moduli core
│   │   ├── __init__.py
│   │   ├── deribit_client.py       # Client API Deribit
│   │   ├── order_manager.py        # Gestione ordini
│   │   ├── position_monitor.py     # Monitoraggio posizioni
│   │   └── risk_manager.py         # Risk management
│   │
│   ├── 📂 strategies/              # Strategie di trading
│   │   ├── __init__.py
│   │   ├── base_strategy.py        # Interfaccia base strategie
│   │   ├── iron_condor.py          # Strategia Iron Condor
│   │   └── smart_money.py          # Strategia Smart Money
│   │
│   └── 📂 utils/                   # Utilità
│       ├── __init__.py
│       └── volatility.py           # Analisi volatilità
│
├── 📂 scripts/                     # Script utility
│   ├── check_opportunities.py      # Controlla opportunità
│   └── view_positions.py           # Visualizza posizioni
│
├── 📂 logs/                        # File di log
│   └── trading_bot.log             # Log del bot
│
├── 📂 data/                        # Dati storici/cache
│
└── 📂 tests/                       # Test unitari (da implementare)
```

## 🔍 Dettaglio dei Moduli

### 📄 File di Configurazione

#### `.env` (da creare)
Contiene le credenziali e configurazione:
- API keys Deribit
- Parametri di trading
- Parametri di rischio

#### `config.py`
Modulo Python che carica e valida la configurazione da `.env`:
- Classe `Config` con tutti i parametri
- Metodo `validate()` per check validità
- Metodo `display()` per visualizzare config

### 🤖 Bot Principale

#### `src/trading_bot.py`
Il cuore del sistema:
- Classe `TradingBot`
- Inizializza tutti i componenti
- Gestisce lo scheduling:
  - Scan giornaliero (10:00 AM)
  - Monitoraggio ogni 5 minuti
- Loop principale con gestione interruzioni

**Funzioni principali:**
- `scan_and_open_positions()`: Cerca e apre nuove posizioni
- `manage_open_positions()`: Monitora e gestisce posizioni aperte
- `start()`: Avvia il bot
- `stop()`: Ferma il bot in modo sicuro

### 🔌 Core Modules

#### `src/core/deribit_client.py`
Client per API Deribit:
- Autenticazione con API keys
- Gestione token e refresh
- Endpoint pubblici (prezzi, strumenti, volatilità)
- Endpoint privati (account, posizioni, ordini)

**Metodi principali:**
- `authenticate()`: Login
- `get_index_price()`: Prezzo spot
- `get_instruments()`: Lista opzioni
- `get_account_summary()`: Saldo account
- `buy()` / `sell()`: Ordini
- `close_position()`: Chiudi posizione

#### `src/core/order_manager.py`
Gestisce l'esecuzione degli ordini:
- Apertura Iron Condor (4 leg)
- Chiusura Iron Condor
- Rollback in caso di errori
- Retry automatici

**Metodi principali:**
- `open_iron_condor()`: Apre tutti i 4 leg
- `close_iron_condor()`: Chiude tutti i 4 leg
- `_execute_leg()`: Esegue singolo leg
- `_rollback_orders()`: Annulla ordini in caso di errore

#### `src/core/position_monitor.py`
Monitora posizioni e gestisce TP/SL:
- Calcolo P&L real-time
- Check condizioni di uscita
- Esecuzione automatica chiusure
- Statistiche portafoglio

**Metodi principali:**
- `add_condor()`: Aggiungi condor al monitoring
- `get_condor_pnl()`: Calcola P&L corrente
- `check_exit_conditions()`: Verifica TP/SL/scadenza
- `monitor_positions()`: Loop principale monitoring
- `get_portfolio_summary()`: Statistiche portafoglio

#### `src/core/risk_manager.py`
Gestione rischio e sizing:
- Calcolo equity corrente
- Sizing dinamico con compounding
- **Futures Sizing**: Calcolo size basato su Stop Loss
- Validazione trade
- Limiti di rischio portafoglio

**Metodi principali:**
- `get_current_equity()`: Equity da Deribit
- `calculate_position_size()`: Calcola size per Iron Condor
- `calculate_futures_quantity()`: Calcola size per Futures (Risk/SL)
- `can_open_new_position()`: Check se possiamo aprire
- `validate_trade()`: Valida trade prima dell'esecuzione

### 📊 Strategies

#### `src/strategies/base_strategy.py`
Classe astratta che definisce l'interfaccia comune per tutte le strategie:
- `scan()`: Cerca segnali di ingresso
- `execute_entry()`: Esegue l'ordine di ingresso
- `manage_positions()`: Gestisce le posizioni aperte

#### `src/strategies/iron_condor.py`
Implementazione strategia Iron Condor (Opzioni):
- Costruzione struttura a 4 gambe
- Selezione strike basata su Delta
- Gestione rischio definita

#### `src/strategies/smart_money.py`
Implementazione strategia Smart Money (Futures):
- **Time Window**: Filtro orario (London/NY overlap)
- **Liquidity Hunter**: Rilevamento pattern Sweep & Reclaim
- **Advanced Flow Analyzer**: Analisi CVD e Assorbimento (Binance Data)

**Classi:**
- `SmartMoneyStrategy`: Logica principale
- `AdvancedFlowAnalyzer`: Motore analisi Order Flow (CCXT)

### 🛠️ Utils

#### `src/utils/volatility.py`
Analisi volatilità:
- Calcolo IV rank
- Calcolo IV percentile
- Filtri per entry
- Storico IV

**Classe `VolatilityAnalyzer`:**
- `calculate_iv_rank()`: IV rank (0-100%)
- `calculate_iv_percentile()`: IV percentile
- `get_atm_iv()`: IV at-the-money
- `should_enter_position()`: Check condizioni IV
- `update_iv_history()`: Aggiorna storico

### 🧪 Scripts di Test

#### `test_connection.py`
Test connessione e autenticazione:
- Verifica API keys
- Test endpoint pubblici
- Test endpoint privati
- Visualizza saldo account

#### `scripts/check_opportunities.py`
Analizza mercato senza tradare:
- Trova scadenze suitable
- Calcola IV corrente
- Tenta build condor
- Mostra opportunità disponibili

#### `scripts/view_positions.py`
Visualizza posizioni aperte:
- Saldo account per currency
- Lista posizioni con dettagli
- Greeks delle posizioni
- P&L totale

## 🔄 Flusso Operativo

### 1. Inizializzazione
```
trading_bot.py
  ↓
Config (carica .env)
  ↓
DeribitClient (autentica)
  ↓
OrderManager, PositionMonitor, RiskManager, IronCondorBuilder, VolatilityAnalyzer
```

### 2. Scan Giornaliero (10:00 AM)
```
scan_and_open_positions()
  ↓
Per ogni currency (BTC, ETH):
  ↓
  1. Get spot price
  2. Find suitable expiration (7-10 DTE)
  3. Get options chain
  4. Calculate ATM IV
  5. Check IV conditions
  6. Build Iron Condor
  7. Validate trade (risk)
  8. Open position
```

### 3. Monitoraggio Continuo (ogni 5 min)
```
manage_open_positions()
  ↓
Per ogni condor aperto:
  ↓
  1. Calculate P&L
  2. Check TP (55% credit)
  3. Check SL (120% credit)
  4. Check time to expiry (24h)
  5. Close if condition met
```

### 4. Chiusura Posizione
```
PositionMonitor.check_exit_conditions()
  ↓ (TP/SL/Expiry)
OrderManager.close_iron_condor()
  ↓
Close 4 legs (buy/sell)
  ↓
Update statistics
Remove from monitoring
```

## 📊 Data Flow

### Apertura Trade
```
Market Data → VolatilityAnalyzer → IronCondorBuilder → RiskManager → OrderManager → Deribit API
```

### Monitoraggio
```
Deribit API → PositionMonitor → Check P&L → Check Exit Conditions → OrderManager (if close)
```

### Risk Management
```
Account Equity → RiskManager → Position Size → Validate Trade → Allow/Deny
```

## 🗂️ File Generati in Runtime

### `logs/trading_bot.log`
Log completo di tutte le operazioni:
- Timestamp
- Level (INFO, WARNING, ERROR)
- Messaggio dettagliato

### `data/` (opzionale, per future implementazioni)
Potenziale uso:
- Cache IV history
- Database posizioni
- Export statistiche CSV

## 🔐 File da NON Committare

Già inclusi in `.gitignore`:
- `.env` (credenziali)
- `logs/*.log` (log files)
- `data/*.csv` (dati)
- `__pycache__/` (cache Python)
- `venv/` (ambiente virtuale)

## 🚀 Entry Points

### Produzione
```bash
python -m src.trading_bot
# oppure
run.bat (Windows)
run.sh (Linux/Mac)
```

### Test/Debug
```bash
python test_connection.py
python scripts/check_opportunities.py
python scripts/view_positions.py
python config.py
```

## 📈 Metriche e KPI

Il bot traccia:
- **Equity**: Capitale corrente
- **P&L**: Profitto/perdita per trade e totale
- **Risk Utilization**: % del rischio massimo utilizzato
- **Win Rate**: % trade chiusi in TP vs SL
- **IV Rank**: Livello volatilità al momento entry
- **DTE**: Giorni a scadenza per ogni posizione

## 🔧 Estensibilità

Aree per future implementazioni:

1. **Database**: Salvare storico trade
2. **Backtesting**: Testare strategia su dati storici
3. **Web UI**: Dashboard di monitoring
4. **Notifications**: Alert via email/telegram
5. **Multiple Strategies**: Altre strategie oltre Iron Condor
6. **ML Integration**: Predizione IV, ottimizzazione parametri
7. **Portfolio Diversification**: Multi-strategy allocation

## 📚 Dipendenze Principali

Vedi `requirements.txt` per versioni esatte:

- `requests`: HTTP client per API
- `websocket-client`: WebSocket per real-time data
- `python-dotenv`: Caricamento .env
- `pandas`: Analisi dati
- `numpy`: Calcoli numerici
- `schedule`: Job scheduling
- `scipy`: Calcoli statistici avanzati

---

**Struttura Progetto Completa e Funzionale! 🎉**
