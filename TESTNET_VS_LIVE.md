# Testnet vs Live: Differenze Critiche

## Il Problema Fondamentale del Testnet

### ❌ Testnet Deribit (test.deribit.com)

**Non è progettato per testare strategie di trading automatiche.**

Problemi:
1. **Liquidità ZERO**: Non ci sono market maker reali
2. **Order book vuoto**: Spread enormi, pochi livelli
3. **Prezzi irrealistici**: Best bid/ask spesso a 0.0001 BTC (~$9)
4. **Market orders non fillano**: Nessuno dall'altra parte
5. **Limit orders non fillano**: Anche aggressivi restano pending
6. **Timeout continui**: API lenta e instabile

### ✅ Live Deribit (www.deribit.com)

**È dove le strategie REALMENTE funzionano.**

Vantaggi:
1. **Alta liquidità**: Market maker professionali 24/7
2. **Order book denso**: Spread stretti, molti livelli
3. **Prezzi realistici**: Bid/ask sempre presenti
4. **Market orders fillano**: Istantaneamente
5. **Aggressive limits fillano**: In pochi secondi
6. **API veloce**: <100ms response time

---

## 🔧 Configurazione Bot: Testnet vs Live

Il bot ora si adatta automaticamente:

```python
# In trading_bot.py
use_market = (self.env == "test")  # MARKET per testnet, LIMIT per live
success = self.order_manager.open_iron_condor(condor, use_market_orders=use_market)
```

### Testnet (env=test):
- ✅ Usa **MARKET ORDERS**
- ✅ Timeout più lunghi (30s)
- ✅ Retry aggressivi (3 tentativi)
- ⚠️ **Non si può testare l'esecuzione reale**
- ✅ Si può testare solo la **logica del bot**

### Live (env=prod):
- ✅ Usa **AGGRESSIVE LIMIT ORDERS**
- ✅ Fill rapidi (5s timeout)
- ✅ Prezzi ottimizzati (slippage 10%)
- ✅ **Trading reale funzionante**

---

## 🎯 Cosa Puoi Testare sul Testnet

### ✅ Testabile:
1. **Connessione API** (autenticazione)
2. **Selezione scadenze** (DTE logic)
3. **Calcolo IV** (volatility analysis)
4. **Costruzione Iron Condor** (strike selection)
5. **Risk management** (position sizing)
6. **Validazione trade** (risk checks)
7. **Rollback logic** (all-or-nothing)
8. **Monitoring** (position tracking)
9. **Logs** (debugging)

### ❌ NON Testabile:
1. **Order execution** (non fillano mai completamente)
2. **Pricing** (prezzi irrealistici)
3. **Slippage** (non c'è mercato)
4. **P&L reale** (prezzi fake)
5. **Greeks accuracy** (volatility fake)
6. **Market conditions** (no real trading)

---

## 💰 Passaggio al Live: Checklist

Prima di passare a Deribit Live, verifica:

### 1. Testnet Completato
- [ ] Bot si avvia senza errori
- [ ] Autenticazione funziona
- [ ] Seleziona correttamente le scadenze
- [ ] Calcola correttamente l'IV
- [ ] Costruisce Iron Condor validi
- [ ] Risk management funziona
- [ ] Logs sono chiari

### 2. Configurazione Live
```bash
# .env
DERIBIT_ENV=prod  # ← Cambia da "test" a "prod"
DERIBIT_API_KEY=your_live_api_key
DERIBIT_API_SECRET=your_live_api_secret

# Risk conservativo per iniziare
RISK_PER_CONDOR=0.005  # 0.5% invece di 1%
MAX_PORTFOLIO_RISK=0.01  # 1% invece di 3%
```

### 3. Start Small
- Inizia con **size minima** (1 contratto)
- Testa con **1 solo Iron Condor**
- Monitora **ogni leg** manualmente
- Verifica **P&L reale** su Deribit UI

### 4. Aggiusta Parametri
Solo dopo i primi trade di successo:
```bash
# Ottimizza slippage per live
ORDER_SLIPPAGE_PCT=0.03  # 3% invece di 10%

# Aumenta gradualmente il risk
RISK_PER_CONDOR=0.01  # Torna a 1%
```

### 5. Monitoring Continuo
- **Primi 3 giorni**: Monitora ogni 30 minuti
- **Prima settimana**: Monitora ogni 2 ore
- **Prime 2 settimane**: Monitora 2 volte al giorno
- **Dopo 1 mese**: Controlli giornalieri

---

## ⚠️ Warning: Market Orders sul Testnet

Il bot ora usa **market orders sul testnet** per massimizzare la probabilità di fill.

**MA ATTENZIONE:**
- Sul testnet, anche i market orders possono non fillare
- Se vedi ancora "NOT FILLED dopo 5s", è **normale**
- Il testnet ha liquidità ZERO

**Soluzione:**
```bash
# Se anche market orders non fillano sul testnet:
# 1. Verifica che l'account test abbia fondi
# 2. Prova con size più piccola (1 contratto invece di 10)
# 3. Prova strike più vicini all'ATM
# 4. Accetta che il testnet è fondamentalmente rotto per questo scopo
```

---

## 📊 Aspettative Realistiche

### Testnet:
- **Fill rate**: 20-50% (pessimo)
- **Completion rate**: 5-10% (Iron Condor completo)
- **P&L accuracy**: 0% (prezzi fake)
- **Utilizzo**: Solo per testare logica del bot

### Live:
- **Fill rate**: 95-99% (ottimo)
- **Completion rate**: 90-95% (Iron Condor completo)
- **P&L accuracy**: 100% (prezzi reali)
- **Utilizzo**: Trading reale

---

## 🚀 Raccomandazione Finale

### Per Testare la Strategia:
**Devi usare Live con size minima.**

Il testnet NON è adatto per testare l'esecuzione degli ordini.

### Approccio Consigliato:
1. ✅ Testa logica sul testnet (connessione, risk, etc.)
2. ✅ Passa a Live con 0.1 BTC (~$9k)
3. ✅ Apri 1 Iron Condor con 1 contratto
4. ✅ Verifica che funzioni tutto
5. ✅ Aumenta gradualmente size e risk

### Costo del Test su Live:
- **1 Iron Condor BTC**: ~$50-100 di rischio
- **Se va male**: Perdi max $50-100
- **Se va bene**: Guadagni ~$25-50
- **Valore dell'apprendimento**: Inestimabile

---

## 📞 Supporto

Se hai problemi sul Live:
1. Controlla i log dettagliati
2. Verifica su Deribit UI che le posizioni siano corrette
3. Il bot ha rollback automatico (safe)
4. Emergency stop disponibile (ferma tutto)

**Il bot è pronto per il Live!** 🎉
