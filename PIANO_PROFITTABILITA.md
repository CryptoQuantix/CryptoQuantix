# Piano Operativo — Dalla Validazione alla Profittabilità

## Obiettivo
Determinare se e quale strategia ha edge reale, poi scalare solo quella.
Orizzonte: 90 giorni strutturati in 3 fasi.

---

## FASE 1 — Validazione Testnet (Giorni 1-60)

### Workflow: zero lavoro manuale durante i 60 giorni

Il bot raccoglie tutto automaticamente in due file SQLite sul Raspberry:

| File | Contenuto |
|------|-----------|
| `data/signal_log.db` | Ogni segnale generato (eseguito + bloccato) con esito WIN/LOSS calcolato ogni 30 min |
| `data/journal.db` | Ogni trade realmente eseguito con P&L in USD |

**Nessuna azione settimanale richiesta.** Il bot gira, i dati si accumulano.

### Al giorno 60: scarica i file e mandameli

```bash
# Dal Raspberry Pi
docker cp coinmaker-bot:/app/data/signal_log.db ./signal_log.db
docker cp coinmaker-bot:/app/data/journal.db    ./journal.db
```

Poi allega entrambi i file in chat. Faccio l'analisi completa e ti do le risposte.

### Cosa ricevi dall'analisi

**Dalle strategie eseguite** (`journal.db`):

| Domanda | Risposta |
|---------|----------|
| Quale strategia è profittevole netta di fees? | P&L totale per strategia sui 60 giorni |
| Esiste un drawdown eccessivo? | Curva equity giornaliera |
| Quale regime produce i trade migliori? | Expectancy per regime (TREND_UP/DOWN/RANGE/COMPRESSION) |
| Quale ora del giorno funziona? | Breakdown per fascia oraria UTC |

**Dalle opportunità perse** (`signal_log.db`):

| Domanda | Risposta |
|---------|----------|
| Il filtro TREND_UP su VolumeBreakout è corretto? | E(R) media dei segnali bloccati da `regime_TREND_UP` |
| Lo scoring engine blocca segnali buoni? | Confronto WR% eseguiti vs bloccati dallo scoring |
| Il rate limit è troppo conservativo? | E(R) dei segnali bloccati da `rate_limit` |

**Esempio output analisi**:
```
SIGNAL LOG — 60 giorni
======================================================================
Strategia        Tipo       Motivo           N    WR%    E(R)
----------------------------------------------------------------------
Volume Breakout  BLOCCATO   regime_TREND_UP  142  31.2%  +0.087R  ← rimuovi filtro!
Volume Breakout  BLOCCATO   regime_RANGE      89  18.4%  -0.241R  ← filtro corretto
Volume Breakout  ESEGUITO   —                198  29.4%  -0.063R
Imbalance Scalp  ESEGUITO   —                 67  52.2%  +0.142R  ← scala questa!
======================================================================
```

### Soglia minima per analisi valida

**30 trade per cella** (strategia × tipo). Sotto quella soglia i numeri non sono affidabili.
Con le 4 strategie attive, 60 giorni dovrebbero produrre 300-600 righe totali.

### Criteri di uscita dalla Fase 1

| Condizione | Azione immediata |
|------------|-----------------|
| Strategia con E(R) > +0.10R dopo 50+ trades | Promuovi a Fase 2 live |
| Strategia con E(R) < -0.20R dopo 30+ trades | Disattiva subito via `.env` |
| Segnali bloccati con E(R) > eseguiti | Rivedi quel filtro |
| Nessuna strategia sopra 0 dopo 60 giorni | Analisi approfondita (vedi Fase 3) |

---

## FASE 2 — Live con Capitale Minimo (Giorni 61-90)

Solo se almeno una strategia ha mostrato E(R) > 0 in testnet.

- **Capitale iniziale live**: €500-1,000 massimo
- **Rischio per trade**: 0.5% del capitale (non 1%)
- **Obiettivo**: verificare che l'esecuzione reale (slippage, latenza, fees vere) non azzeri l'edge
- **Stop loss totale**: se perdi >15% del capitale live, torni in testnet

Basta cambiare nel `.env` sul Raspberry:
```
DERIBIT_TESTNET=false
DERIBIT_API_KEY=<chiave_live>
DERIBIT_API_SECRET=<secret_live>
```
E riavviare: `docker compose restart`

---

## FASE 3 — Scala o Pivota

Dopo 90 giorni hai dati reali. Tre scenari:

**Scenario A — Una strategia è profittevole**
→ Concentra il capitale su quella. Aumenta sizing gradualmente (+25% al mese).
→ Disattiva le strategie negative nel `.env` (`VB_ENABLED=false` ecc.).

**Scenario B — Nessuna strategia è profittevole MA i segnali bloccati sì**
→ I filtri erano troppo aggressivi. Rivediamo i parametri di regime/scoring.
→ Nuovo ciclo di 30 giorni con filtri allentati.

**Scenario C — Nessun edge da nessuna parte**
→ Il problema è la strategia, non i filtri. Nuovo sweep su parametri diversi.
→ Oppure considera una strategia completamente diversa (es. market making su spread).

---

## Journal delle Opportunità Perse — Come funziona ora

### Architettura implementata

Il sistema è già attivo nel bot. Funziona così:

```
Strategia genera segnale candidato
         ↓
   Filtro regime/scoring
         ↓
  ┌──────┴──────┐
  │             │
BLOCCATO     ESEGUITO
  │             │
  └──→ signal_log.db ←─┘
         ↓
  Outcome Tracker (ogni 30 min)
  controlla se prezzo ha toccato
  TP o SL del segnale bloccato
         ↓
  Aggiorna WIN / LOSS / pending
```

### Cosa viene registrato

**Segnali bloccati** (con motivo):
- `regime_TREND_UP` — VolumeBreakout bloccato perché mercato sale forte
- `regime_TREND_DOWN` — MeanReversion bloccata perché mercato scende forte
- SL e TP stimati dal prezzo corrente + config default (abbastanza precisi per l'analisi)

**Segnali eseguiti**:
- Tutti i trade reali con SL e TP esatti

### Controllo rapido in qualsiasi momento

Se vuoi un'occhiata prima dei 60 giorni (dal Raspberry o da qui con il file):

```bash
docker exec coinmaker-bot python -c "
from src.journal.signal_log import SignalLog
SignalLog('data/signal_log.db').print_report()
"
```

Oppure mandami il file `.db` e lo leggo io.

---

## Il Numero che Conta

Alla fine di ogni settimana (o quando vuoi), questo è l'unico numero che importa:

```
Expectancy = (WR% × avg_win_R) - ((1 - WR%) × 1.0)
```

| Valore | Significato |
|--------|-------------|
| > +0.10R | Edge solido — scala |
| +0.01R → +0.10R | Edge marginale — ottimizza prima di scalare |
| -0.08R → 0.00R | Breakeven con fees — analizza le opportunità perse |
| < -0.08R | Nessun edge — disattiva e riprogetta |

**Target minimo per coprire le fees Deribit** (~0.10% round-trip):
- E(R) > +0.08R
- Almeno 30 trade/mese per strategia

---

## Nota Finale

La profittabilità non si costruisce ottimizzando parametri — si trova capendo
**quando il mercato dà segnali affidabili** e **quando non tradare**.

Il Journal delle Opportunità Perse risponde esattamente a questa domanda
con dati reali, non simulati. Dopo 60 giorni sapremo con certezza cosa
funziona e cosa no — non per intuizione, ma per evidenza statistica.
