# Guida al Contesto di Mercato — Quando Accendere e Spegnere le Strategie

> Leggi questo documento al termine dei 60 giorni di testnet.
> Contiene tutto quello che ti serve per decidere cosa fare dopo.

---

## PARTE 1 — Capire il Mercato di BTC/ETH in 5 Minuti

### Il Regime di Mercato (la cosa più importante)

Il bot rileva automaticamente il regime ogni minuto. Ma devi sapere COSA significa
per capire i risultati e prendere decisioni.

Immagina BTC come un'auto:

| Regime | Cosa sta facendo il mercato | Come riconoscerlo a occhio |
|--------|----------------------------|---------------------------|
| **TREND_UP** | Sale forte e continuamente | Ogni giorno chiude più in alto. Notizie positive. Euforia. |
| **TREND_DOWN** | Scende forte e continuamente | Ogni giorno chiude più in basso. Panico. Liquidazioni frequenti. |
| **RANGE** | Rimbalza avanti e indietro tra due livelli | "BTC è bloccato tra 60k e 65k da 2 settimane" |
| **COMPRESSION** | Movimento minimo, volume bassissimo | "BTC non si muove, nessuno sta tradando" |
| **EXPANSION** | Appena uscito dalla compressione, volatile | "BTC ha rotto il range di due settimane, movimento esplosivo" |

**Come vederlo nel bot** (dal log):
```
STATUS — Equity: $50,000 | Positions: 0 | Regime: TREND_DOWN | Strategies: 4
```

---

### I 3 Numeri Esterni che Devi Guardare

Questi non vengono dal bot — li leggi su Coinglass o TradingView ogni lunedì.

**1. Funding Rate** (su Binance Futures o Coinglass)
- Misura quanti soldi i trader long pagano ai trader short ogni 8 ore
- **Positivo alto (> +0.05%)**: troppi long → mercato surriscaldato → possibile dump
- **Negativo (< -0.01%)**: troppi short → mercato pessimista → possibile short squeeze
- **Neutro (-0.01% a +0.03%)**: equilibrio → trend più affidabili

**2. Open Interest** (su Coinglass)
- Quanti contratti futures sono aperti in totale
- **OI cresce + prezzo sale**: trend forte, soldi nuovi entrano → TREND_UP affidabile
- **OI scende + prezzo scende**: liquidazioni forzate → attenzione a LiqSqueeze
- **OI cresce + prezzo scende**: short aggressivi → possibile short squeeze

**3. Fear & Greed Index** (su alternative.me/crypto/fear-and-greed-index)
- Da 0 (paura estrema) a 100 (avidità estrema)
- **< 20 (Paura estrema)**: mercato RANGE/COMPRESSION o fine di TREND_DOWN → buono per MeanReversion
- **> 80 (Avidità estrema)**: mercato TREND_UP → attenzione, presto inversione
- **40-60 (Neutro)**: qualsiasi strategia può funzionare

---

## PARTE 2 — Playbook delle 4 Strategie

### Strategia 1: VolumeBreakout

**Cosa fa**: Entra quando il volume esplode e il prezzo rompe i massimi/minimi recenti.
È una strategia di **momentum** — scommette che il movimento continuerà.

**ACCENDI quando**:
- Regime = COMPRESSION o EXPANSION o TREND_DOWN
- Volume sopra la media (VolZ > 2.5 nel log del bot)
- OI in aumento (soldi nuovi entrano)
- Funding rate neutro o leggermente negativo

**SPEGNI quando**:
- Regime = TREND_UP (il backtest ha mostrato E=-0.40R, perde molto)
- Regime = RANGE (i breakout sono falsi, ritornano al range)
- Funding rate > +0.05% (mercato surriscaldato, breakout false)
- Dopo 3 stop loss consecutivi nella stessa settimana

**Segnali di allerta nel log**:
```
[VolumeBreakout] Regime TREND_UP — skipping breakout   ← corretto, sta ignorando
[VolumeBreakout] LONG signal @ 67,000                  ← segnale generato
```

**Come disattivarla** (nel `.env` sul Raspberry):
```
VB_ENABLED=false
```
Poi: `docker compose restart`

---

### Strategia 2: MeanReversion

**Cosa fa**: Fades le estremità — compra quando il mercato è sceso troppo velocemente,
vende quando è salito troppo. È una strategia **contrarian**.

**ACCENDI quando**:
- Regime = RANGE o COMPRESSION
- Fear & Greed < 25 (paura eccessiva) per segnali LONG
- Fear & Greed > 75 (avidità eccessiva) per segnali SHORT
- Volume basso (VolZ < 1.5) — non un breakout, solo un'estremità

**SPEGNI quando**:
- Regime = TREND_UP o TREND_DOWN (in un trend forte, le estremità continuano)
- OI in forte crescita in una direzione (il trend è reale, non temporaneo)
- Notizie macro importanti in corso (Fed, ETF, regolamentazioni)

**Segnali di allerta nel log**:
```
[MeanReversion] LONG fade @ 65,200 VWAP=66,100 z=-2.3   ← segnale generato
[MeanReversion] Regime TREND_DOWN — blocked              ← corretto, bloccato
```

**Come disattivarla**:
```
MR_ENABLED=false
```

---

### Strategia 3: LiquidationSqueeze

**Cosa fa**: Cavalca le cascate di liquidazioni forzate. Quando molti trader sono
costretti a chiudere posizioni, crea un momentum esplosivo prevedibile.

**ACCENDI quando**:
- OI scende rapidamente (-5% o più in pochi minuti) — liquidazioni in corso
- Nel log del bot vedi tante righe `[LIQUIDATION] BUY/SELL`
- Funding rate estremo (> +0.1% o < -0.05%) — molti sono esposti da un lato
- Regime = qualsiasi (le liquidazioni avvengono in tutti i regimi)

**SPEGNI quando**:
- OI stabile (nessuna liquidazione in corso)
- Mercato tranquillo, bassa volatilità
- Fear & Greed tra 40-60 (nessun eccesso)

**Come leggere le liquidazioni nel log** (segnale che la strategia può agire):
```
[LIQUIDATION] BTCUSDT BUY 0.57 @ $66,473  ← short squeezed
[LIQUIDATION] BTCUSDT BUY 0.23 @ $66,438  ← altri short squeezed
[LIQUIDATION] BTCUSDT BUY 0.15 @ $66,484  ← continuano
```
Quando vedi BUY liquidations accumularsi → short squeeze in corso → LiqSqueeze dovrebbe andare LONG.

**Come disattivarla**:
```
LIQ_ENABLED=false
```

---

### Strategia 4: ImbalanceScalp

**Cosa fa**: Scalpa brevissime inefficienze del book ordini. Quando 94% degli ordini
sono da un lato e il prezzo può muoversi facilmente, entra veloce e esce veloce.

**ACCENDI quando**:
- Regime = TREND_DOWN (il backtest live ha mostrato 50% WR, +0.14R)
- Regime = TREND_UP (E=+0.01R, quasi neutro ma non negativo)
- Book imbalance estremo (Imb > 0.85 o < 0.15 nel log)
- Volume basso-medio (non un breakout)

**SPEGNI quando**:
- Regime = COMPRESSION (troppo tranquillo, pochi segnali)
- Notizie importanti in corso (lo spread si allarga, difficile scalppare)
- Più di 5 stop loss consecutivi nella stessa sessione

**Come leggere l'imbalance nel log**:
```
STATUS: CVD1m=+25.06  Imb=0.948  VolZ=0.00
```
`Imb=0.948` = 94.8% buy side — è un segnale estremo per ImbalanceScalp LONG.

**Come disattivarla**:
```
IS_ENABLED=false
```

---

## PARTE 3 — Matrice Decisionale Rapida

Usa questa tabella ogni lunedì per decidere quali strategie tenere accese.

| Condizione di mercato | VolumeBreakout | MeanReversion | LiqSqueeze | ImbalanceScalp |
|----------------------|:--------------:|:-------------:|:----------:|:--------------:|
| TREND_UP + OI cresce | ❌ SPEGNI | ❌ SPEGNI | ⚡ SE liquidazioni | ✅ ACCENDI |
| TREND_DOWN + liquidazioni | ✅ ACCENDI | ❌ SPEGNI | ✅ ACCENDI | ✅ ACCENDI |
| RANGE + volume basso | ❌ SPEGNI | ✅ ACCENDI | ❌ SPEGNI | ⚡ CAUTELA |
| COMPRESSION | ✅ ACCENDI | ✅ ACCENDI | ❌ SPEGNI | ❌ SPEGNI |
| EXPANSION (post-breakout) | ✅ ACCENDI | ❌ SPEGNI | ⚡ SE liquidazioni | ✅ ACCENDI |
| Funding > +0.1% | ❌ SPEGNI | ✅ SHORT only | ✅ ACCENDI | ✅ SHORT only |
| Funding < -0.05% | ✅ LONG only | ✅ LONG only | ✅ ACCENDI | ✅ LONG only |

Legenda: ✅ = tienila accesa | ❌ = spegnila | ⚡ = dipende, leggi nota | ⚡ CAUTELA = riduci sizing

---

## PARTE 4 — Come Leggere i Dati SQLite al Giorno 60

### Passo 1: Scarica i file

```bash
docker cp coinmaker-bot:/app/data/signal_log.db ./signal_log.db
docker cp coinmaker-bot:/app/data/journal.db    ./journal.db
```

Mandameli in chat — faccio l'analisi e ti dico cosa fare.

### Passo 2: Cosa ci dirà l'analisi

**Da signal_log.db** — Le opportunità perse:

La domanda chiave è: *I segnali che il bot ha bloccato avrebbero guadagnato o perso?*

```
block_reason = "regime_TREND_UP"  → E(R) = +0.09R  significa: RIMUOVI quel filtro
block_reason = "regime_RANGE"     → E(R) = -0.24R  significa: filtro corretto, tienilo
```

**Da journal.db** — I trade reali:

```
Strategia        Trades  WR%   E(R)    Decisione
VolumeBreakout   89      31%   +0.12R  → SCALA (aumenta sizing)
ImbalanceScalp   34      51%   +0.15R  → SCALA
MeanReversion    8       25%   -0.18R  → SPEGNI (pochi dati, negativo)
LiqSqueeze       156     12%   -0.35R  → SPEGNI (troppo rumorosa)
```

### Passo 3: Le 3 domande che farai

1. **"Quale strategia ha E(R) > 0?"** → Tienila, scala il sizing del 50%
2. **"Il filtro regime blocca segnali buoni?"** → Se sì, allenta quel filtro
3. **"Quale ora del giorno funziona meglio?"** → Aggiungi filtro orario

---

## PARTE 5 — Il Processo Mensile (dopo i 60 giorni)

Dedica **30 minuti al mese** a questo processo. Niente di più.

### Prima settimana del mese

```
1. Guarda il regime prevalente dell'ultimo mese:
   - Sul tuo exchange preferito: BTC era in trend? In range?
   - Controlla il Fear & Greed medio del mese su alternative.me

2. Controlla le metriche del bot:
   docker exec coinmaker-bot python -c "
   from src.journal.signal_log import SignalLog
   SignalLog('data/signal_log.db').print_report()
   "

3. Prendi una decisione per ogni strategia:
   - E(R) > +0.08R → Scala il sizing del 25%
   - E(R) tra -0.08R e +0.08R → Tieni invariato
   - E(R) < -0.08R → Spegni o abbassa sizing al 50%
```

### Regola dei 3 mesi

Non cambiare i parametri di una strategia più di una volta ogni 3 mesi.
Il mercato cambia, e ogni modifica ha bisogno di tempo per essere validata.

**Unica eccezione**: Se perdi > 5% del capitale in una settimana → spegni tutto,
analisi, poi riaccendi con cautela.

---

## PARTE 6 — Glossario Rapido

| Termine | Spiegazione semplice |
|---------|---------------------|
| **E(R)** | Expectancy in R. +0.10R significa che per ogni $1 rischiate, guadagni in media $0.10. Deve essere positivo. |
| **WR%** | Win Rate. Percentuale di trade vincenti. Non basta da sola — una strategia con 30% WR e 4R di profitto medio è ottima. |
| **R** | L'unità di rischio. Se rischi $100 per trade, 1R = $100. Usi R per confrontare trade di dimensioni diverse. |
| **Funding Rate** | Costo di tenere aperta una posizione long vs short. Se positivo, i long pagano i short. |
| **OI (Open Interest)** | Quanti contratti futures aperti in totale. Cresce = nuovi soldi entrano. Scende = posizioni vengono chiuse. |
| **CVD** | Cumulative Volume Delta. Misura la pressione netta di acquisto vs vendita. Positivo = più acquisti. |
| **Imbalance** | Squilibrio del book. 0.9 = 90% degli ordini sono buy. Indica verso dove si muoverà il prezzo a breve. |
| **Vol Z-score** | Volume attuale vs media storica. 2.5 = il volume è 2.5 volte sopra la media. |
| **Regime** | Classificazione automatica del mercato (TREND/RANGE/COMPRESSION/EXPANSION). |

---

## Nota Finale

Questo documento diventa più utile man mano che accumuli dati reali.
Al giorno 60 saprai già molto di più di adesso su come si comportano
queste strategie nel tuo specifico contesto di mercato.

Il processo è semplice:
1. Leggi i dati SQLite → capisce dove c'è edge
2. Accendi le strategie con edge → spegni le altre
3. Ripeti ogni mese

Non devi essere un esperto di mercati finanziari per farlo.
Devi solo seguire i numeri.
