# Guida Setup Completa - Iron Condor Trading Bot

## 📋 Pre-requisiti

1. **Python 3.8 o superiore**
   ```bash
   python --version
   ```

2. **Account Deribit**
   - Registrati su [test.deribit.com](https://test.deribit.com) per testnet
   - Oppure [www.deribit.com](https://www.deribit.com) per production

3. **API Keys Deribit**
   - Login su Deribit
   - Vai in Account → API
   - Crea nuove API keys con permessi:
     - ✅ Read account info
     - ✅ Trade

## 🚀 Installazione Passo-Passo

### 1. Clone del repository

```bash
cd C:\Users\hp\Documents\GitHub
cd coinmaker
```

### 2. Crea ambiente virtuale (consigliato)

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**Linux/Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Installa dipendenze

```bash
pip install -r requirements.txt
```

### 4. Configura le variabili d'ambiente

Copia il file template:
```bash
copy .env.example .env
```

Modifica `.env` con un editor di testo e inserisci le tue API keys:
```env
DERIBIT_API_KEY=TUA_API_KEY_QUI
DERIBIT_API_SECRET=TUA_API_SECRET_QUI
DERIBIT_ENV=test

INITIAL_EQUITY=10000
RISK_PER_CONDOR=0.01
MAX_PORTFOLIO_RISK=0.03
```

### 5. Crea cartella logs

```bash
mkdir logs
```

## ✅ Test dell'Installazione

### Test 1: Connessione API

```bash
python test_connection.py
```

Output atteso:
```
✓ Authentication successful
✓ BTC Index Price: $95,234.50
✓ ETH Index Price: $3,456.78
✓ BTC Account Balance: 0.10000000 BTC
```

### Test 2: Verifica configurazione

```bash
python config.py
```

Controlla che tutti i parametri siano corretti.

### Test 3: Controlla opportunità

```bash
python scripts\check_opportunities.py
```

Questo script analizza il mercato e ti mostra se ci sono opportunità di trading senza aprire posizioni.

## 🎮 Primo Utilizzo

### Modalità Dry-Run (Consigliata)

Prima di attivare il bot in modalità automatica, usa questi script per familiarizzare:

1. **Visualizza posizioni attuali:**
   ```bash
   python scripts\view_positions.py
   ```

2. **Controlla opportunità:**
   ```bash
   python scripts\check_opportunities.py
   ```

3. **Monitora il mercato** per qualche giorno senza tradare

### Avvio del Bot

**IMPORTANTE**: Usa sempre il TESTNET per i primi giorni!

```bash
python -m src.trading_bot
```

Oppure usa lo script helper:

**Windows:**
```bash
run.bat
```

**Linux/Mac:**
```bash
chmod +x run.sh
./run.sh
```

## 📊 Cosa Aspettarsi

### Schedule del Bot

- **10:00 AM**: Scan giornaliero per nuove opportunità
- **Ogni 5 minuti**: Monitoraggio posizioni aperte e check TP/SL

### Log Output

Il bot logga tutte le operazioni in:
- Console (output real-time)
- `logs/trading_bot.log` (file permanente)

Esempio di log:
```
2024-12-26 10:00:00 - INFO - SCANNING FOR NEW POSITIONS
2024-12-26 10:00:05 - INFO - Checking BTC...
2024-12-26 10:00:06 - INFO - Spot price: $95,234.50
2024-12-26 10:00:07 - INFO - ATM IV: 65.23%
2024-12-26 10:00:08 - INFO - IV conditions met: IV rank 72.3%
2024-12-26 10:00:15 - INFO - Built Iron Condor: BTC_27DEC24_20241226_100015
2024-12-26 10:00:20 - INFO - ✓ Successfully opened condor
```

## ⚙️ Configurazione Avanzata

### Parametri nel .env

| Parametro | Significato | Valore Consigliato |
|-----------|-------------|-------------------|
| `RISK_PER_CONDOR` | Rischio per trade (% equity) | 0.01 (1%) |
| `MAX_PORTFOLIO_RISK` | Rischio massimo totale | 0.03 (3%) |
| `TP_RATIO` | Take profit (% credito) | 0.55 (55%) |
| `SL_MULT` | Stop loss (multiplo credito) | 1.2 (120%) |
| `MIN_DTE` | Giorni minimi a scadenza | 7 |
| `MAX_DTE` | Giorni massimi a scadenza | 10 |
| `MIN_IV_PERCENTILE` | IV percentile minimo | 30 |
| `SHORT_DELTA_TARGET` | Delta per short options | 0.12 |

### Come Modificare lo Schedule

Nel file `src/trading_bot.py`, cerca:

```python
# Schedule daily position opening (e.g., 10:00 AM)
schedule.every().day.at("10:00").do(self.run_daily_routine)

# Schedule position monitoring every 5 minutes
schedule.every(5).minutes.do(self.run_monitoring_routine)
```

Modifica gli orari secondo le tue preferenze.

## 🛠️ Troubleshooting

### Errore: "Authentication failed"

- ✅ Verifica che API key e secret siano corretti
- ✅ Controlla che `DERIBIT_ENV` sia "test" o "prod"
- ✅ Verifica che le API keys abbiano i permessi corretti

### Errore: "Could not get spot price"

- ✅ Verifica la connessione internet
- ✅ Controlla che Deribit API sia raggiungibile
- ✅ Prova a riavviare il bot

### Nessuna posizione aperta

- ✅ L'IV potrebbe essere troppo bassa (sotto soglia)
- ✅ Nessuna scadenza disponibile nel range 7-10 DTE
- ✅ Limite di rischio già raggiunto
- ✅ Controlla i log per il motivo specifico

### Bot si ferma improvvisamente

- ✅ Controlla `logs/trading_bot.log` per errori
- ✅ Verifica che l'account Deribit sia attivo
- ✅ Controlla che ci sia margine disponibile

## 📈 Passaggio a Production

**SOLO DOPO aver testato in testnet per almeno 2 settimane:**

1. Crea nuove API keys su [www.deribit.com](https://www.deribit.com)
2. Modifica `.env`:
   ```env
   DERIBIT_API_KEY=nuova_prod_key
   DERIBIT_API_SECRET=nuova_prod_secret
   DERIBIT_ENV=prod
   ```
3. **Riduci il capitale iniziale** per i primi trade:
   ```env
   INITIAL_EQUITY=1000  # Inizia con $1000 invece di $10000
   ```
4. Monitora **costantemente** i primi giorni

## 🔒 Sicurezza

### Best Practices

1. ✅ **MAI** condividere API keys
2. ✅ **MAI** committare il file `.env` su git
3. ✅ Usa sempre testnet per esperimenti
4. ✅ Monitora i log regolarmente
5. ✅ Imposta alert sul tuo account Deribit
6. ✅ Non modificare risk management senza capirlo

### Backup

Fai backup regolari di:
- File `.env` (in luogo sicuro)
- `logs/trading_bot.log`
- Database delle posizioni (se implementato)

## 📞 Supporto

In caso di problemi:

1. Controlla i log in `logs/trading_bot.log`
2. Verifica la configurazione con `python config.py`
3. Testa la connessione con `python test_connection.py`
4. Consulta la documentazione Deribit: [docs.deribit.com](https://docs.deribit.com)

## 🎓 Risorse per Approfondire

- [Deribit API Docs](https://docs.deribit.com/)
- [Iron Condor Strategy](https://www.investopedia.com/terms/i/ironcondor.asp)
- [Options Greeks](https://www.investopedia.com/options-greeks-4427781)
- [Implied Volatility](https://www.investopedia.com/terms/i/iv.asp)

## ⚠️ DISCLAIMER FINALE

- Questo è software educativo/sperimentale
- Il trading comporta rischio di perdita
- Usa solo capitale che puoi perdere
- Non è consulenza finanziaria
- Testa SEMPRE in testnet prima

---

**Buon Trading! 🚀**

*Ricorda: Patience, Discipline, Risk Management*
