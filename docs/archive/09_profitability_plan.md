# Piano di Validazione e Profittabilita

## Obiettivo

Determinare se e quale strategia ha edge reale, poi scalare solo quella.
Orizzonte: **90 giorni** strutturati in 3 fasi.

---

## 1. Il Numero che Conta

Prima di tutto il resto: l'unica metrica che importa e l'**Expectancy in R**.

```
E(R) = (WR% x avg_win_R) - ((1 - WR%) x 1.0)
```

| Valore E(R) | Significato | Azione |
|-------------|-------------|--------|
| `> +0.10R` | Edge solido | Scala il sizing |
| `+0.01R` → `+0.10R` | Edge marginale | Ottimizza prima di scalare |
| `-0.08R` → `0.00R` | Breakeven con fees | Analizza le opportunita perse |
| `< -0.08R` | Nessun edge | Disattiva e riprogetta |

!!! info "Target minimo per coprire le fees Deribit"
    `E(R) > +0.08R` con almeno 30 trade/mese per strategia.
    Le fees Deribit sono ~0.10% round-trip (taker).

---

## 2. Fase 1 — Validazione Testnet (Giorni 1-60)

### 2.1 Workflow: zero lavoro manuale

Il bot raccoglie tutto automaticamente in due file SQLite sul Raspberry:

| File | Contenuto |
|------|-----------|
| `data/signal_log.db` | Ogni segnale generato (eseguito + bloccato) con esito WIN/LOSS calcolato ogni 30 min |
| `data/journal.db` | Ogni trade realmente eseguito con P&L in USD |

**Nessuna azione settimanale richiesta.** Il bot gira, i dati si accumulano.

### 2.2 Al giorno 60: scarica i file

```bash
# Dal Raspberry Pi
docker cp coinmaker-bot:/app/data/signal_log.db ./signal_log.db
docker cp coinmaker-bot:/app/data/journal.db    ./journal.db
```

### 2.3 Analisi dei file

**Da `journal.db`** — i trade reali:

| Domanda | Risposta |
|---------|----------|
| Quale strategia e profittevole netta di fees? | P&L totale per strategia sui 60 giorni |
| Esiste un drawdown eccessivo? | Curva equity giornaliera |
| Quale regime produce i trade migliori? | Expectancy per regime |
| Quale ora del giorno funziona? | Breakdown per fascia oraria UTC |

**Da `signal_log.db`** — le opportunita perse:

| Domanda | Risposta |
|---------|----------|
| Il filtro `TREND_UP` su VolumeBreakout e corretto? | `E(R)` dei segnali bloccati da `regime_TREND_UP` |
| Lo scoring blocca segnali buoni? | Confronto WR% eseguiti vs bloccati |
| Il rate limit e troppo conservativo? | `E(R)` dei segnali bloccati da `rate_limit` |

**Esempio output**:
```
SIGNAL LOG — 60 giorni
======================================================================
Strategia        Tipo       Motivo           N    WR%    E(R)
----------------------------------------------------------------------
Volume Breakout  BLOCCATO   regime_TREND_UP  142  31.2%  +0.087R  <- rimuovi filtro!
Volume Breakout  BLOCCATO   regime_RANGE      89  18.4%  -0.241R  <- filtro corretto
Volume Breakout  ESEGUITO   —                198  29.4%  -0.063R
Imbalance Scalp  ESEGUITO   —                 67  52.2%  +0.142R  <- scala questa!
======================================================================
```

### 2.4 Soglia minima per analisi valida

**30 trade per cella** (strategia x tipo). Sotto quella soglia i numeri non sono affidabili.
Con le 4 strategie attive, 60 giorni dovrebbero produrre 300-600 righe totali.

### 2.5 Criteri di uscita dalla Fase 1

| Condizione | Azione immediata |
|------------|-----------------|
| Strategia con `E(R) > +0.10R` dopo 50+ trades | Promuovi a Fase 2 live |
| Strategia con `E(R) < -0.20R` dopo 30+ trades | Disattiva via `.env` |
| Segnali bloccati con `E(R)` > segnali eseguiti | Rivedi quel filtro |
| Nessuna strategia sopra 0 dopo 60 giorni | Analisi approfondita — vedi Fase 3 |

---

## 3. Journal delle Opportunita Perse — Architettura

Il sistema e gia attivo nel bot. Funziona cosi:

```
Strategia genera segnale candidato
         |
   Filtro regime/scoring
         |
  +------+------+
  |             |
BLOCCATO     ESEGUITO
  |             |
  +---> signal_log.db <---+
         |
  Outcome Tracker (ogni 30 min)
  controlla se prezzo ha toccato
  TP o SL del segnale bloccato
         |
  Aggiorna WIN / LOSS / pending
```

### 3.1 Cosa viene registrato

**Segnali bloccati** (con motivo):

- `regime_TREND_UP` — VolumeBreakout bloccato perche mercato sale forte
- `regime_TREND_DOWN` — MeanReversion bloccata perche mercato scende forte
- SL e TP stimati dal prezzo corrente + config default

**Segnali eseguiti**:

- Tutti i trade reali con SL e TP esatti

### 3.2 Controllo rapido in qualsiasi momento

```bash
docker exec coinmaker-bot python -c "
from src.journal.signal_log import SignalLog
SignalLog('data/signal_log.db').print_report()
"
```

### 3.3 Schema SQLite

```sql
CREATE TABLE signal_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT    NOT NULL,
    strategy     TEXT    NOT NULL,
    direction    TEXT    NOT NULL,   -- BUY / SELL
    price        REAL    NOT NULL,
    sl           REAL    NOT NULL,
    tp           REAL    NOT NULL,
    regime       TEXT    DEFAULT 'UNKNOWN',
    executed     INTEGER NOT NULL DEFAULT 0,  -- 0=bloccato, 1=eseguito
    block_reason TEXT,               -- NULL se eseguito
    outcome      TEXT,               -- WIN / LOSS / NULL (pending)
    exit_price   REAL,
    pnl_r        REAL,
    checked_at   TEXT
);
```

---

## 4. Backtest — Come Interpretare i Risultati

### 4.1 Contesto Fondamentale

I risultati del backtest dipendono dal **regime di mercato prevalente nel periodo testato**.
Una strategia che perde nel backtest in bear market potrebbe essere ottima in bull market.

!!! warning "Backtest trovati su 2025-12-31 → 2026-03-01 (BTC -24.1%)"
    Tutti e 4 le strategie hanno mostrato `E(R)` negativo.
    In un bear market severo, quasi tutte le strategie momentum perdono.
    Il bot pero ha perso solo $53 su $10,000 vs BTC che perdeva $2,410.

### 4.2 Risultati Attuali (periodo bear market)

| Strategia | Trades | WR% | E(R) | Note |
|-----------|--------|-----|------|------|
| VolumeBreakout | 319 | 27% | -0.217R | Migliora a z=2.5, imb=0.50 |
| MeanReversion | 14 | 7% | — | Troppo pochi — proxy absorption troppo strict |
| LiqSqueeze | 424 | 0.5% | -0.35R | Proxy liquidazioni troppo rumoroso in backtest |
| ImbalanceScalp | 135 | 41% | -0.07R | **TREND_DOWN**: 50% WR, +0.14R |

**ImbalanceScalp in `TREND_DOWN`** e l'unica con edge positivo nel periodo testato.

### 4.3 VolumeBreakout — Sweep Parametri

Sweep su 45 combinazioni (z=1.5/2.0/2.5, imb=0.45/0.50/0.55, rr=1.5/2.0/2.5):

| Parametri | Trades | WR% | E(R) |
|-----------|--------|-----|------|
| z=2.5, imb=0.50, rr=2.5 | 280 | 29% | -0.154R | **Migliore** |
| z=2.0, imb=0.55, rr=2.5 | 319 | 27% | -0.217R | Default originale |

Pattern: `vol_z` alto + `imb` basso + `rr=2.5` e consistentemente migliore.
`COMPRESSION` e il regime migliore (-0.07R); `TREND_UP` e il peggiore (-0.40R).

### 4.4 Come Eseguire il Backtest

```bash
# Backtest completo
python scripts/real_backtest.py

# Sweep parametri VolumeBreakout
python scripts/sweep_vb.py

# Dry run paper trading (120 secondi)
scripts/run_dry_run.bat full --duration 120
```

---

## 5. Fase 2 — Live con Capitale Minimo (Giorni 61-90)

Solo se almeno una strategia ha mostrato `E(R) > 0` in testnet.

- **Capitale iniziale live**: €500-1,000 massimo
- **Rischio per trade**: 0.5% del capitale (non 1%)
- **Obiettivo**: verificare che slippage, latenza e fees reali non azzerino l'edge
- **Stop loss totale**: se perdi >15% del capitale live, torni in testnet

Basta cambiare nel `.env` sul Raspberry:
```
DERIBIT_TESTNET=false
DERIBIT_API_KEY=<chiave_live>
DERIBIT_API_SECRET=<secret_live>
```

Poi: `docker compose restart`

---

## 6. Fase 3 — Scala o Pivota

Dopo 90 giorni hai dati reali. Tre scenari:

=== "Scenario A — Edge Trovato"
    Una strategia e profittevole.

    - Concentra il capitale su quella
    - Aumenta sizing gradualmente (+25% al mese)
    - Disattiva le strategie negative: `VB_ENABLED=false` nel `.env`

=== "Scenario B — Edge nei Segnali Bloccati"
    Nessuna strategia profittevole MA i segnali bloccati si.

    - I filtri erano troppo aggressivi
    - Revisione parametri di regime/scoring
    - Nuovo ciclo di 30 giorni con filtri allentati

=== "Scenario C — Nessun Edge"
    Nessun edge da nessuna parte.

    - Il problema e la strategia, non i filtri
    - Nuovo sweep su parametri diversi
    - Oppure considera una strategia completamente diversa (es. market making su spread)

---

## 7. Position Log — Tracciamento Posizioni

Ogni trade viene scritto in `logs/positions.log` in formato human-readable:

```
============================================================
POSIZIONE APERTA   2026-03-01 09:15:00 UTC
------------------------------------------------------------
Strategia   : VolumeBreakout
Strumento   : BTC-PERPETUAL
Direzione   : LONG

  Prezzo BTC  : $67,120.00
  Size        : 0.043000 BTC  =  $2,886.16
  Entry       : $67,120.00
  Stop Loss   : $66,800.00  |  rischio: $13.76  (0.00020500 BTC)
  Take Profit : $67,920.00  |  target: +$34.40  (+0.00051257 BTC)  R/R 2.5x

  Regime      : EXPANSION

  Conto prima : $10,000.00  (0.149000 BTC)
============================================================

============================================================
POSIZIONE CHIUSA   2026-03-01 09:47:22 UTC
------------------------------------------------------------
Strumento   : BTC-PERPETUAL  LONG
Durata      : 32 min

  Entry       : $67,120.00
  Exit        : $67,920.00
  Motivo      : TP raggiunto

  P&L         : +$34.40  (+0.00042700 BTC)  +0.34%

  Conto prima : $10,000.00  (0.149000 BTC)
  Conto dopo  : $10,034.40  (0.149512 BTC)
============================================================
```

Il file viene scritto automaticamente da `TradeLogger` → `PositionLog`
ogni volta che una strategia apre o chiude una posizione.
