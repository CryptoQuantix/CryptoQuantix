# C8 — Positioning Extremes (raccolta dati in corso, validazione ≥ giugno 2027)

> **Stato**: 🟡 COLLECTING — archivio avviato il **2026-06-12**, primo dato
> in archivio **~2026-05-12** (backfill dei 31 giorni disponibili).
> **Validazione**: NON prima di **giugno 2027** (≥ 12 mesi di serie, che
> includano almeno un cambio di fase macro).
> **Questo documento è la memoria completa del candidato**: perché esiste,
> cosa raccogliamo esattamente, come verificare la salute dell'archivio,
> le ipotesi PRE-REGISTRATE e la checklist delle azioni a giugno 2027.

---

## 1. La tesi (perché questo candidato esiste)

Il posizionamento aggregato dei derivati — chi è long, quanto, con quanta
leva — è un segnale di **crowding**: quando "tutti" sono dallo stesso lato,
il carburante per continuare il movimento si esaurisce e il rischio di
squeeze contrario cresce. È la stessa famiglia logica di **FundingSqueeze**
(la nostra strategia validata: funding al cap + macro bear → short, +74bps
PF 2.65), che però usa il SOLO funding. I dati di posizionamento Binance
sono potenzialmente più ricchi:

- **Top Trader L/S Position Ratio**: posizionamento delle balene PER SIZE
  (non per numero di account) — il più vicino a "smart money"
- **Top Trader L/S Account Ratio**: stesse balene, per numero di account
- **Global L/S Account Ratio**: tutti gli account (retail incluso) —
  utile come CONTRASTO col top trader (divergenza retail vs balene)
- **Open Interest**: leva aggregata nel sistema; spike rapidi = mercato
  iper-indebitato
- **Taker Buy/Sell Ratio**: aggressione netta a mercato (proxy CVD)

## 2. Il vincolo che giustifica tutto: la finestra dei 30 giorni

Gli endpoint Binance `futures/data/*` ritornano **SOLO gli ultimi ~30
giorni**. Non esiste storia pubblica gratuita più lunga. Conseguenze:

1. **Oggi è IMPOSSIBILE validare** queste serie con la pipeline multi-ciclo
   (4 anni): qualunque backtest su 30 giorni è rumore.
2. **Ogni giorno senza collector è un giorno perso PER SEMPRE.**
3. La serie proprietaria che stiamo costruendo diventa un asset che nessun
   backtest pubblico può replicare.

Per questo il collector è partito SUBITO (12/06/2026), prima di qualunque
ipotesi di utilizzo.

## 3. Cosa raccogliamo, esattamente

### Endpoint e metriche (tutti pubblici, nessuna chiave)

| metric (in DB) | Endpoint Binance | Campo headline (`value`) | Altri campi nel raw |
|---|---|---|---|
| `top_ls_positions` | `/futures/data/topLongShortPositionRatio` | longShortRatio | longAccount, shortAccount |
| `top_ls_accounts` | `/futures/data/topLongShortAccountRatio` | longShortRatio | longAccount, shortAccount |
| `global_ls_accounts` | `/futures/data/globalLongShortAccountRatio` | longShortRatio | longAccount, shortAccount |
| `open_interest` | `/futures/data/openInterestHist` | sumOpenInterestValue (USD) | sumOpenInterest (coin) |
| `taker_ratio` | `/futures/data/takerlongshortRatio` | buySellRatio | buyVol, sellVol |

- **Simboli**: BTCUSDT, ETHUSDT (i due tradati)
- **Granularità**: `period=1h` (500 punti/fetch ≈ 20.8 giorni)
- **Record raw completo** salvato in JSON nella colonna `raw` (schema-proof:
  se Binance aggiunge campi, non perdiamo nulla)

### Storage

- **File**: `data/positioning_history.db` (SQLite, gitignored: vive sulla
  macchina del bot — vedi §5 per il backup)
- **Schema**:
  ```sql
  CREATE TABLE positioning (
      symbol TEXT NOT NULL,
      metric TEXT NOT NULL,
      ts_ms  INTEGER NOT NULL,   -- timestamp Binance del punto (ms, UTC)
      value  REAL,               -- valore headline (vedi tabella sopra)
      raw    TEXT,               -- record completo JSON
      PRIMARY KEY (symbol, metric, ts_ms)
  )
  ```
- **Idempotenza**: `INSERT OR REPLACE` sulla PK → run sovrapposti non
  duplicano mai; il collector può girare quanto spesso si vuole.

### Processi di raccolta (ridondanza doppia)

1. **Bot async** — `src/async_trading_bot.py::_positioning_loop()`:
   una passata ogni **12h**, partenza 60s dopo il boot. Disattivabile con
   `POSITIONING_ENABLED=false` nel .env. Ogni errore è un warning: non
   tocca MAI il trading.
2. **Script standalone** — `python scripts/collect_positioning.py`:
   stesso codice, per cron/Task Scheduler e check manuali
   (`--status` per la sola copertura).

> **RACCOMANDAZIONE OPERATIVA**: configurare un'attività giornaliera di
> Windows Task Scheduler che lancia lo script. Con il solo bot, un downtime
> > ~20 giorni (vacanze, macchina rotta, migrazione) crea un **buco
> permanente** nella serie. Il job ridondante su un'altra macchina o un
> task schedulato lo previene a costo zero.

### Matematica della continuità

Fetch da 500 punti × 1h = 20.8 giorni di finestra. Con una passata ogni
12h l'overlap è ~20 giorni: per perdere dati servono **>20 giorni
consecutivi** senza NESSUNA passata (né bot né cron). La staleness è
visibile nella dashboard (pagina "Contesto Mercato", pannello C8) con
allarme rosso oltre 48h.

## 4. Ipotesi PRE-REGISTRATE (scritte ORA, prima di vedere i dati)

> Pre-registrare le ipotesi prima di avere i dati è la difesa principale
> contro il data snooping: a giugno 2027 si testano QUESTE, così come sono
> scritte. Aggiungere ipotesi nuove è permesso, ma vanno etichettate come
> esplorative e validate su dati successivi alla loro formulazione.

- **H-C8.1 (FS enhancement)**: aggiungere a FundingSqueeze il filtro
  "top_ls_positions nel decile ESTREMO long (rolling 90d)" migliora
  l'expectancy per trade senza ridurre i trade sotto ~10/anno?
  *Razionale: funding al cap + balene long-crowded = squeeze più probabile.*
- **H-C8.2 (divergenza retail/balene)**: quando `global_ls_accounts` è
  estremo long E `top_ls_positions` è < 1 (balene short), il rendimento
  forward 24-72h è negativo? (segnale short standalone in macro bear)
- **H-C8.3 (OI spike)**: un aumento dell'OI > +X% in 24h (X da percentile
  storico, NON cherry-picked) seguito da funding positivo predice drawdown
  a 24h superiori alla baseline? (filtro di rischio: ridurre size tattica)
- **H-C8.4 (taker exhaustion)**: taker_ratio estremo (>P90 rolling) con
  prezzo che NON sale (divergenza aggressione/prezzo) precede reversal?
- **H-C8.5 (controllo)**: le versioni "account" e "position" del top trader
  ratio danno segnali diversi? Se sì, usare SOLO position ratio (più
  vicino al capitale reale) e documentare.

**Gate di promozione** (identici alla pipeline, PLAN_BULL_EVOLUTION.md §1):
backtest sul codice reale, costi 0.20% roundtrip, IS/OOS temporale,
PF ≥ 1.2 sul campione completo, miglioramento marginale REALE rispetto
alla strategia senza il filtro, robustezza alle soglie vicine (niente
"P90 sì ma P85 no"), minimo ~30 trade o motivazione esplicita per
accettarne meno (come FS).

**Verdetto possibile e accettabile**: TUTTO BOCCIATO. Il costo della
raccolta è ~zero; l'assenza di edge sarebbe comunque un risultato
(chiude la famiglia di ipotesi e libera attenzione).

## 5. Manutenzione della serie (da OGGI a giugno 2027)

### Check trimestrali (settembre 2026, dicembre 2026, marzo 2027)

Eseguire e annotare QUI sotto l'esito:

```bash
python scripts/collect_positioning.py --status
```

Verifiche:
1. `days_covered` cresce di ~90 giorni per trimestre (nessun buco)
2. `stale_hours` < 48 per tutte le 10 serie (5 metriche × 2 simboli)
3. dimensione `data/positioning_history.db` cresce (~1.5 MB/anno attesi)
4. **backup**: copiare `data/positioning_history.db` su storage esterno
   (il file è gitignored — il repo NON lo protegge)

| Check | Data | Esito | Note |
|---|---|---|---|
| Q3 2026 | __ set 2026 | ⬜ | |
| Q4 2026 | __ dic 2026 | ⬜ | |
| Q1 2027 | __ mar 2027 | ⬜ | |

### Se si trova un buco
Documentarlo qui (date inizio/fine) e NON tentare di "riempirlo" con dati
sintetici: i test del 2027 escluderanno gli intervalli mancanti.

| Buco | Da | A | Causa |
|---|---|---|---|
| — | | | |

## 6. ✅ CHECKLIST AZIONI — GIUGNO 2027

1. ⬜ **Copertura**: `--status` → ≥ 350 giorni continui per tutte le serie;
   buchi documentati in §5 ed esclusi dai test
2. ⬜ **Contesto macro attraversato**: la serie include almeno una
   transizione di fase (giugno 2026 = bear; cosa è successo dopo?).
   Se il regime è stato UNO solo per 12 mesi, valutare di estendere la
   raccolta altri 6-12 mesi prima di testare le ipotesi direzionali.
3. ⬜ **Export dataset di ricerca**: estrarre da SQLite a parquet/csv in
   `data/research/positioning_1y/` (così la pipeline di ricerca non tocca
   il DB live)
4. ⬜ **Allineamento**: join con klines 1h e funding del periodo (fonti già
   nel repo/KlineProvider) su timestamp UTC; ATTENZIONE al solito bug
   resample/left-label documentato in quant-research-2026-06
5. ⬜ **Testare H-C8.1 → H-C8.5** così come pre-registrate in §4, una alla
   volta, IS/OOS; annotare l'esito di OGNUNA qui sotto
6. ⬜ **Verdetto**: promozione (→ implementazione nel codice strategia con
   nuova validazione completa) oppure bocciatura motivata
7. ⬜ **In ogni caso**: aggiornare questo file, PLAN_SCANNER_IDEAS.md e la
   memoria di progetto; decidere se la raccolta continua (sì se promosso o
   se serve più storia; no se la famiglia di ipotesi è chiusa)

### Esiti test (compilare nel 2027)

| Ipotesi | Esito | Numeri | Note |
|---|---|---|---|
| H-C8.1 | ⬜ | | |
| H-C8.2 | ⬜ | | |
| H-C8.3 | ⬜ | | |
| H-C8.4 | ⬜ | | |
| H-C8.5 | ⬜ | | |

## 7. Rischi e caveat noti (annotati ora per onestà futura)

- **Multiple testing**: 5 ipotesi × 2 simboli × varie soglie = alto rischio
  di falsi positivi. Mitigazione: ipotesi pre-registrate, soglie da
  percentili rolling (non ottimizzate), richiesta di robustezza.
- **Regime singolo**: 12 mesi potrebbero coprire una sola fase macro →
  qualunque edge trovato sarebbe condizionato alla fase. Mitigazione:
  punto 2 della checklist (estendere se necessario).
- **Cambi di schema/endpoint Binance**: il raw JSON protegge dai campi
  nuovi; se un endpoint viene DEPRECATO, aggiornare `METRICS` in
  `positioning_collector.py` e annotare qui la data di switch.
- **Bias di sopravvivenza dell'idea**: l'intuizione viene da un terminale
  discrezionale (bitcoin-quant-scanner) e dal folklore di settore
  ("smart money ratio"). Il fatto che FS (stessa famiglia) sia validata è
  incoraggiante ma NON è evidenza per queste serie.
- **Il DB è fuori dal git**: senza i backup trimestrali (§5), un disco
  rotto azzera 12 mesi di lavoro.

## 8. Puntatori

- Codice: [../src/data/positioning_collector.py](../src/data/positioning_collector.py)
- Loop bot: `src/async_trading_bot.py::_positioning_loop`
- Script/cron: [../scripts/collect_positioning.py](../scripts/collect_positioning.py)
- Pannello salute: dashboard → "Contesto Mercato" → "Archivio C8"
- Triage origine: [PLAN_SCANNER_IDEAS.md](PLAN_SCANNER_IDEAS.md)
- Pipeline di validazione: [PLAN_BULL_EVOLUTION.md](PLAN_BULL_EVOLUTION.md) §1
