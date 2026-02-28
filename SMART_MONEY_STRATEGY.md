# Smart Money Strategy 🐋

Questa strategia è progettata per seguire i flussi del "denaro intelligente" (Smart Money) e sfruttare le manipolazioni di mercato intraday.

## 🧠 La Logica

La strategia si basa sulla confluenza di 3 fattori chiave. Il bot entra in posizione SOLO se tutti e 3 i semafori sono verdi.

### 1. Time Window (Il "Quando")
**Obiettivo**: Operare solo quando c'è massima volatilità e liquidità.
- **Finestra**: Overlap Londra / New York.
- **Orario Default**: 14:00 - 17:00 (Ora Italiana/CET).
- **Perché**: È il momento in cui le banche centrali e gli hedge fund muovono i volumi maggiori. Fuori da questo orario, i segnali sono spesso falsi.

### 2. Liquidity Hunter (Il "Dove")
**Obiettivo**: Entrare dopo che gli stop loss dei retail sono stati cacciati.
- **Pattern**: "Sweep & Reclaim".
- **Bullish Sweep**:
    1. Il prezzo scende sotto un minimo recente (Low < PrevLow).
    2. Ma la candela chiude SOPRA quel minimo (Close > PrevLow).
    3. Significa che la discesa era una trappola per prendere liquidità.
- **Bearish Sweep**:
    1. Il prezzo sale sopra un massimo recente.
    2. Ma chiude SOTTO quel massimo.

### 3. Order Flow Confirmation (Il "Perché") 🆕
**Obiettivo**: Confermare che il movimento sia supportato dai volumi reali (non manipolazione).
Il bot analizza i trade tick-by-tick di Binance Spot per calcolare il **CVD (Cumulative Volume Delta)** e rilevare l'**Assorbimento**.

- **Assorbimento Bullish (Whale Wall)**:
    - I venditori aggrediscono (Delta molto negativo).
    - MA il prezzo NON scende (o sale).
    - *Significato*: Una balena sta assorbendo tutte le vendite con ordini limit.

- **Assorbimento Bearish (Iceberg)**:
    - I compratori aggrediscono (Delta molto positivo).
    - MA il prezzo NON sale (o scende).
    - *Significato*: Una balena sta bloccando la salita distribuendo posizioni.

---

## 🛡️ Gestione del Rischio (Impeccabile)

Il bot calcola la size della posizione matematicamente per ogni trade.

### Formula
$$ Size = \frac{Equity \times Rischio\%}{|EntryPrice - StopLossPrice|} $$

- **Rischio per Trade**: 1% del capitale (Default).
- **Stop Loss**: Posizionato esattamente sotto/sopra la candela di "Sweep".
- **Esecuzione**:
    1. Ordine **Market** per entrare.
    2. Ordine **Stop Market** immediato per proteggere il capitale.

---

## 🛠️ Configurazione

Aggiungi queste variabili al tuo file `.env`:

```bash
# Abilita la strategia
STRATEGY_SMART_MONEY_ENABLED=true

# Orari (UTC+1 se il server è in Italia/Europa)
SM_TIME_WINDOW_START=14
SM_TIME_WINDOW_END=17

# Order Flow (Sensibilità)
SM_BINANCE_SYMBOL=BTCUSDT
SM_ABSORPTION_MIN_VOL=10.0       # Minimo 10 BTC di volume per analizzare
SM_ABSORPTION_DELTA_RATIO=0.15   # Delta deve essere almeno il 15% del volume totale
SM_ABSORPTION_PRICE_THRESHOLD=0.01 # Prezzo deve muoversi meno dello 0.01% durante l'assorbimento
```

## 📊 Esempio di Trade

**Scenario Bullish:**
1.  **Ore 15:30**: Apre Wall Street. Siamo nella finestra temporale.
2.  **Grafico**: BTC scende rapidamente a $59.800 (sotto il minimo di $60.000), ma chiude la candela a $60.100. -> **Bullish Sweep**.
3.  **Order Flow**:
    - Volume totale ultimi 1000 trade: 50 BTC.
    - Delta: -12 BTC (Venditori aggressivi).
    - Prezzo: Fermo.
    - **Segnale**: `ABSORPTION_BUY` (Whale Wall rilevata).
4.  **Azione**:
    - Il bot calcola la size per rischiare l'1% con SL a $59.790.
    - Apre **LONG** a mercato.
    - Piazza **STOP LOSS** a $59.790.

---

## ⚠️ Note Operative

- **API Binance**: La strategia usa le API pubbliche di Binance per i dati volumetrici (nessuna API Key richiesta per questo).
- **API Deribit**: Usa le API Key configurate per l'esecuzione.
- **Latenza**: L'analisi Order Flow richiede qualche secondo. Il bot è ottimizzato per non bloccare l'esecuzione.
