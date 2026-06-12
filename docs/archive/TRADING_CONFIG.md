# Trading Bot Configuration

## Order Execution Strategy

### Aggressive Limit Orders (Current Default)

Il bot ora usa **aggressive limit orders** invece di market orders per garantire fills anche su testnet con bassa liquidità.

#### Come funziona:

1. **BUY orders**:
   - Prende `best_ask_price` dal order book
   - Aggiunge 10% di slippage: `best_ask * 1.10`
   - Questo garantisce fill immediato come un market order

2. **SELL orders**:
   - Prende `best_bid_price` dal order book
   - Sottrae 10% di slippage: `best_bid * 0.90`
   - Questo garantisce fill immediato

#### Parametri configurabili:

```python
OrderManager(
    client=client,
    max_retries=3,              # Numero di tentativi per leg
    retry_delay=1.0,            # Secondi tra tentativi
    use_aggressive_limits=True, # Usa aggressive limits
    slippage_pct=0.10          # 10% slippage per garantire fill
)
```

#### Timeout:

- **Fill verification**: 5 secondi (ridotto da 10)
- **Max retries**: 3 tentativi per leg
- **Total timeout per leg**: ~15-20 secondi

## Iron Condor Logic: All-or-Nothing

### Regola fondamentale:

**O tutte e 4 le leg, o niente.**

Il bot NON lascerà mai posizioni parziali aperte.

### Cosa succede:

1. Tenta di aprire leg #1 (long put)
2. Se **FILLED** → prosegue
3. Se **NOT FILLED** dopo 3 tentativi → ABORT

4. Tenta leg #2 (short put)
5. Se **NOT FILLED** → **ROLLBACK**: chiude leg #1

6. E così via per tutte le 4 leg

### Rollback automatico:

Se una qualsiasi leg fallisce:
- ✅ Cancella ordini pendenti
- ✅ Chiude immediatamente le leg già aperte (a market)
- ✅ Il condor NON viene aggiunto al portfolio
- ✅ Log dettagliato del fallimento

## Logging Migliorato

Ogni ordine ora logga:

```
Executing leg: SELL put @ 85000.0 (BTC-5DEC25-85000-P)
Using AGGRESSIVE LIMIT 0.003456 for BTC-5DEC25-85000-P
Order placed: 72385033706, state: open
Order 72385033706 state: filled, filled: 10.0
Order 72385033706 FILLED successfully
  ✓ SELL put @ 85000.0 - FILLED
```

Se fallisce:

```
Order 72385033706 NOT filled, attempt 1/3
Waiting 1s before retry...
Order 72385048592 NOT filled, attempt 2/3
Order 72385064119 NOT filled, attempt 3/3
  ✗ Failed to sell put @ 85000.0 - NOT FILLED
Rolling back 1 opened legs...
```

## Testnet vs Live

### Testnet (test.deribit.com):

- ❌ Liquidità molto bassa
- ❌ Spread larghi
- ✅ Aggressive limits funzionano meglio
- ✅ Slippage 10% accettabile per test

### Live (www.deribit.com):

- ✅ Alta liquidità
- ✅ Spread stretti
- ⚠️ Ridurre slippage a 2-3% per ottimizzare prezzi
- ⚠️ Valutare price improvement loop

## Prossimi miglioramenti (per Live):

1. **Dynamic slippage**: Riduci slippage se liquidità alta
2. **Price improvement loop**:
   - Start aggressive
   - Move gradually verso mid price
   - Timeout dopo N step
3. **Partial fill handling**: Gestione fills parziali
4. **Smart retry**: Aumenta aggressività ad ogni retry

## Variabili ambiente

Aggiungi al `.env` per customizzare:

```bash
# Order execution
ORDER_MAX_RETRIES=3
ORDER_RETRY_DELAY=1.0
ORDER_AGGRESSIVE_LIMITS=true
ORDER_SLIPPAGE_PCT=0.10  # 10% per testnet, 0.03 per live
## Smart Money Configuration

Variabili specifiche per la strategia Smart Money:

```bash
# Smart Money
STRATEGY_SMART_MONEY_ENABLED=true
SM_TIME_WINDOW_START=14
SM_TIME_WINDOW_END=17
SM_BINANCE_SYMBOL=BTCUSDT

# Order Flow / Absorption
SM_ABSORPTION_MIN_VOL=10.0       # Volume minimo per analisi (BTC)
SM_ABSORPTION_DELTA_RATIO=0.15   # Ratio Delta/TotalVol (0.15 = 15%)
SM_ABSORPTION_PRICE_THRESHOLD=0.01 # Soglia movimento prezzo (0.01%)
```

- **SM_ABSORPTION_MIN_VOL**: Alza questo valore se vuoi analizzare solo blocchi di volume significativi.
- **SM_ABSORPTION_DELTA_RATIO**: Determina quanto deve essere "sbilanciato" il volume (Buy vs Sell) per segnalare assorbimento.
- **SM_ABSORPTION_PRICE_THRESHOLD**: Definisce quanto il prezzo deve rimanere "fermo" nonostante la pressione per confermare l'assorbimento.
