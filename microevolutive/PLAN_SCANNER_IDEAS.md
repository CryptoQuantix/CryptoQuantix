# Idee importate da bitcoin-quant-scanner — triage, fatte e backlog

> **Data**: 2026-06-12 · **Origine**: `microevolutive/bitcoin-quant-scanner/`
> (progetto parallelo dell'utente: terminale Streamlit discrezionale per BTC
> con dati macro/on-chain/derivati + demone alert Telegram).
> Questo documento è la memoria del triage: cosa abbiamo preso, cosa è in
> backlog con design dettagliato, cosa abbiamo respinto e PERCHÉ.

---

## Triage completo

| # | Idea | Verdetto | Stato |
|---|---|---|---|
| 1 | Collector dati posizionamento (L/S ratio, OI, taker) | presa — il tempo perso non si recupera (finestra 30gg Binance) | ✅ FATTA 12/06/2026 → [C8_POSITIONING_EXTREMES.md](C8_POSITIONING_EXTREMES.md) |
| 2 | Alert Telegram "edge proximity" | presa — design qui sotto | 🔶 BACKLOG |
| 3 | Pagina "Contesto Mercato" in dashboard | presa — read-only, zero rischio | ✅ FATTA 12/06/2026 |
| 4 | AI Export JSON | presa — costo minimo | ✅ FATTA 12/06/2026 |
| 5 | Filtri on-chain per macro gate | candidato ricerca → C9, design qui sotto | 🔶 BACKLOG (post paper-trading) |
| — | "Quant Score" 0-100 | RESPINTA | ❌ |
| — | Tab playbook strategico | RESPINTA | ❌ |
| — | Correlazioni SPY/DXY via Alpaca/yfinance | RESPINTA (nel core) | ❌ |
| — | Orderbook imbalance REST ±5% | RESPINTA | ❌ |

---

## ✅ Fatte il 12/06/2026 (riferimenti implementazione)

### Idea 1 — Collector C8
- `src/data/positioning_collector.py` — 5 metriche × 2 simboli, SQLite
  `data/positioning_history.db`, INSERT OR REPLACE idempotente, raw JSON
- Loop nel bot: `async_trading_bot._positioning_loop()` ogni 12h
  (`POSITIONING_ENABLED` nel .env)
- Ridondanza/cron: `python scripts/collect_positioning.py`
- Backfill iniziale eseguito: **31.0 giorni** catturati (serie parte dal
  ~12/05/2026)
- TUTTO il resto (ipotesi, gate, azioni a giugno 2027) →
  **[C8_POSITIONING_EXTREMES.md](C8_POSITIONING_EXTREMES.md)**

### Idea 3 — Pagina "Contesto Mercato"
`src/monitoring/dashboard_app/page_context.py`: funding storico ~333gg con
soglia FS evidenziata, serie posizionamento dall'archivio C8, Fear & Greed,
hashrate drawdown + difficulty retarget (mempool.space), pannello salute
collector con allarme staleness > 48h. SOLO contesto: nessun numero di
questa pagina tocca il trading.

### Idea 4 — AI Export
Sezione in fondo a "Contesto Mercato": snapshot JSON completo (conto,
posizioni con strategia, riconciliazione, macro state, performance 30d,
posizionamento, F&G/difficulty) da incollare in un LLM. Nessun secret.

---

## 🔶 BACKLOG — Idea 2: alert Telegram "edge proximity"

**Cosa**: notifiche quando una strategia validata si sta AVVICINANDO alla
sua finestra di ingresso. Non cambia il trading: è consapevolezza operativa
(FS fa ~4 trade/anno — sapere che è "vicina" ha valore).

**Pattern dal scanner** (`monitor.py`): check periodico → soglie → alert
Telegram → cooldown per non spammare. Già compatibile con `TelegramAlerts`
esistente.

**Design proposto** (da implementare nel monitoring loop del bot o come
task async dedicato, intervallo 15 min, riusa `KlineProvider`):

| Alert | Condizione di proximity | Cooldown |
|---|---|---|
| FS quasi pronta | macro bear accelerante OK **e** funding ≥ 0.7×soglia (0.00007) ma < soglia | 8h (una per finestra funding) |
| TB short vicino | macro bear **e** prezzo entro l'1% sopra il minimo 48h | 4h |
| TB long vicino | macro bull **e** prezzo entro l'1% sotto il massimo 7d | 4h |
| MC re-entry vicino | flat **e** close daily entro il 2% sotto SMA200d | 24h |
| MC chandelier vicino | in posizione **e** close entro 1×ATR sopra la soglia chandelier | 24h |

**Vincoli**:
- riusare ESATTAMENTE le stesse funzioni di gate delle strategie (no
  reimplementazioni → no drift): `_macro_bull()`, `_macro_bear_accelerating()`
- messaggio = stato + numeri (es. "funding 0.0085%/8h, soglia 0.01% — FS
  in finestra tra ~2h se regge")
- nessun alert = nessun problema: è un nice-to-have, mai un segnale

**Accettazione**: con soglie di test abbassate, l'alert arriva su Telegram
una sola volta per cooldown; il bot non cambia comportamento.

**Stima**: mezza giornata.

---

## 🔶 BACKLOG — Idea 5: filtri on-chain → candidato C9

**Tesi**: i dati miner/on-chain (a differenza del posizionamento) hanno
**storia lunga completa e gratuita** → backtestabili SUBITO sui 4 anni con
la pipeline esistente (PLAN_BULL_EVOLUTION.md §1).

**Fonti dati** (tutte senza chiavi):
- `mempool.space/api/v1/mining/hashrate/{3y|all}` — hashrate storico
- `mempool.space/api/v1/difficulty-adjustment` — solo corrente; lo storico
  retarget si ricava dall'hashrate o da `/api/v1/mining/difficulty-adjustments`
- Puell proxy = close / SMA365 (dal nostro dataset 1m 4y, zero fetch)
- Mayer = close / SMA200 (già nel codice come macro gate)

**Ipotesi da testare** (pre-registrate qui, prima di guardare i dati):
- **H-C9.1**: hashrate drawdown < -10% (capitolazione miner) come filtro di
  QUALITÀ sul re-entry di MacroCore → riduce i whipsaw del cross SMA200d?
- **H-C9.2**: Puell proxy < 0.6 come boost di esposizione MC (bucket +0.25)
  → migliora il Calmar senza peggiorare il maxDD?
- **H-C9.3**: difficulty retarget stimato < -3% in macro bear → le entry TB
  short successive hanno expectancy migliore o peggiore? (possibile segnale
  di FONDO → fine del bear → CONTROINDICAZIONE per gli short)

**Metodo**: identico a C1-C7 — backtest sul codice reale, costi 0.20%,
IS/OOS, PF ≥ 1.2 marginale aggiunto, robustezza alle soglie vicine.
ATTENZIONE overfitting: le soglie del scanner (-10%, 0.6, 2.5) sono
folklore di settore MAI validato — trattarle come ipotesi, non come verità.

**Quando**: dopo il paper trading delle 3 strategie attive (priorità del
backlog principale: C5/C6/SOL/paper-trading).

**Stima**: 1 sessione per H-C9.1+H-C9.2 (dataset daily già nel repo),
mezza per H-C9.3 (serve fetch storico difficulty).

---

## ❌ RESPINTE (e perché — non riaprire senza nuovi argomenti)

1. **"Quant Score" 0-100**: somma di pesi arbitrari mai validati
   (Mayer -20, F&G -15, hashrate -10...). È esattamente la classe di
   euristica che la pipeline di validazione esiste per impedire. Se un
   componente ha valore, va testato DA SOLO con la pipeline (→ C9).
2. **Tab "playbook strategico"**: consigli discrezionali multi-timeframe
   ("fai scalping ai bordi delle Bollinger") — incompatibile con un sistema
   che trada solo edge validati.
3. **Correlazioni SPY/DXY (Alpaca/yfinance) nel core**: contesto da
   terminale, non segnale validato; aggiunge chiavi API e dipendenze
   fragili (yfinance) al processo di trading. Se in futuro serve come
   contesto in dashboard, valutare una fonte senza chiavi.
4. **Orderbook imbalance REST ±5%**: abbiamo già l'OrderBookEngine L2 via
   WebSocket (superiore), e l'imbalance come segnale è già stato BOCCIATO
   dalla validazione (ImbalanceScalp, PF 0.18-0.50).
5. **Cache SQLite del scanner per le klines**: il nostro KlineProvider +
   dataset 4y nel repo coprono già il caso d'uso.

---

## Nota operativa sul progetto scanner

`microevolutive/bitcoin-quant-scanner/` è un repo git ANNIDATO e
indipendente (gitignored da coinmaker). Resta utile come terminale
discrezionale standalone (`streamlit run dashboard.py` + `monitor.py`).
Le idee valide sono state importate QUI come codice nostro — non
dipendiamo dai suoi file.
