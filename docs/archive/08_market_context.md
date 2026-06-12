# Contesto di Mercato — Quando Accendere e Spegnere le Strategie

!!! info "Quando leggere questo documento"
    Leggilo al termine dei 60 giorni di testnet, oppure ogni volta che vuoi capire
    perche una strategia sta perdendo e se conviene disattivarla.

---

## 1. Regime di Mercato

Il bot rileva il regime automaticamente ogni minuto (`RegimeDetector`).
Devi sapere cosa significa per interpretare i risultati.

### 1.1 Tassonomia

| Regime | Cosa fa il mercato | Come riconoscerlo |
|--------|--------------------|-------------------|
| `TREND_UP` | Sale forte e continuamente | Ogni giorno chiude piu in alto. Euforia. Notizie positive. |
| `TREND_DOWN` | Scende forte e continuamente | Ogni giorno chiude piu in basso. Liquidazioni frequenti. |
| `RANGE` | Rimbalza tra due livelli | "BTC e bloccato tra 60k e 65k da 2 settimane" |
| `COMPRESSION` | Movimento minimo, volume bassissimo | "BTC non si muove, nessuno sta tradando" |
| `EXPANSION` | Appena uscito dalla compressione | "BTC ha rotto il range — movimento esplosivo" |

### 1.2 Come Vederlo nel Log

```
STATUS — Equity: $50,000 | Positions: 0 | Regime: TREND_DOWN | Strategies: 4
```

---

## 2. Indicatori Esterni da Monitorare

Questi non vengono dal bot — si leggono su Coinglass o TradingView ogni lunedi.

### 2.1 Funding Rate

Si trova su Binance Futures o [Coinglass](https://coinglass.com).

| Valore | Interpretazione |
|--------|----------------|
| `> +0.05%` | Troppi long → mercato surriscaldato → possibile dump |
| `< -0.01%` | Troppi short → mercato pessimista → possibile short squeeze |
| `-0.01%` a `+0.03%` | Equilibrio → trend piu affidabili |

### 2.2 Open Interest

Si trova su Coinglass.

| Scenario | Significato |
|----------|-------------|
| OI cresce + prezzo sale | Trend forte, soldi nuovi entrano → `TREND_UP` affidabile |
| OI scende + prezzo scende | Liquidazioni forzate → attenzione a LiqSqueeze |
| OI cresce + prezzo scende | Short aggressivi → possibile short squeeze |

### 2.3 Fear & Greed Index

Si trova su [alternative.me](https://alternative.me/crypto/fear-and-greed-index).
Scala 0 (paura estrema) → 100 (avidita estrema).

| Valore | Interpretazione |
|--------|----------------|
| `< 20` | `RANGE`/`COMPRESSION` o fine di `TREND_DOWN` — buono per MeanReversion |
| `> 80` | `TREND_UP` — attenzione, presto inversione |
| `40-60` | Neutro — qualsiasi strategia puo funzionare |

---

## 3. Playbook delle 4 Strategie

### 3.1 VolumeBreakout

**Logica**: entra quando il volume esplode e il prezzo rompe i massimi/minimi recenti.
Strategia di **momentum** — scommette che il movimento continuera.

??? success "Accendi quando"
    - Regime = `COMPRESSION` o `EXPANSION` o `TREND_DOWN`
    - Volume sopra la media (`VolZ > 2.5` nel log)
    - OI in aumento (soldi nuovi entrano)
    - Funding rate neutro o leggermente negativo

??? danger "Spegni quando"
    - Regime = `TREND_UP` (backtest: `E=-0.40R` — perde molto)
    - Regime = `RANGE` (i breakout sono falsi, ritornano al range)
    - Funding rate `> +0.05%` (mercato surriscaldato, breakout falsi)
    - Dopo 3 stop loss consecutivi nella stessa settimana

**Segnali nel log**:
```
[VolumeBreakout] Regime TREND_UP — skipping breakout   <- corretto, sta ignorando
[VolumeBreakout] LONG signal @ 67,000                  <- segnale generato
```

**Disattivazione** (file `.env`):
```
VB_ENABLED=false
```

---

### 3.2 MeanReversion

**Logica**: fades le estremita — compra quando il mercato e sceso troppo velocemente.
Strategia **contrarian**.

??? success "Accendi quando"
    - Regime = `RANGE` o `COMPRESSION`
    - Fear & Greed `< 25` per segnali LONG
    - Fear & Greed `> 75` per segnali SHORT
    - Volume basso (`VolZ < 1.5`) — non e un breakout, solo un'estremita

??? danger "Spegni quando"
    - Regime = `TREND_UP` o `TREND_DOWN` (in un trend forte le estremita continuano)
    - OI in forte crescita in una direzione (il trend e reale, non temporaneo)
    - Notizie macro importanti in corso (Fed, ETF, regolamentazioni)

**Segnali nel log**:
```
[MeanReversion] LONG fade @ 65,200 VWAP=66,100 z=-2.3   <- segnale generato
[MeanReversion] Regime TREND_DOWN — blocked              <- corretto, bloccato
```

**Disattivazione**:
```
MR_ENABLED=false
```

---

### 3.3 LiquidationSqueeze

**Logica**: cavalca le cascate di liquidazioni forzate. Il momentum e esplosivo e prevedibile.

??? success "Accendi quando"
    - OI scende rapidamente (-5% o piu in pochi minuti)
    - Nel log vedi righe `[LIQUIDATION] BUY/SELL` in sequenza
    - Funding rate estremo (`> +0.1%` o `< -0.05%`)
    - Regime = qualsiasi (le liquidazioni avvengono in tutti i regimi)

??? danger "Spegni quando"
    - OI stabile (nessuna liquidazione in corso)
    - Mercato tranquillo, bassa volatilita
    - Fear & Greed tra 40-60 (nessun eccesso)

**Come leggere le liquidazioni nel log**:
```
[LIQUIDATION] BTCUSDT BUY 0.57 @ $66,473  <- short squeezed
[LIQUIDATION] BTCUSDT BUY 0.23 @ $66,438  <- altri short squeezed
[LIQUIDATION] BTCUSDT BUY 0.15 @ $66,484  <- continuano
```
BUY liquidations accumulate → short squeeze in corso → LiqSqueeze va LONG.

**Disattivazione**:
```
LIQ_ENABLED=false
```

---

### 3.4 ImbalanceScalp

**Logica**: scalpa brevissime inefficienze del book ordini quando il 94% degli ordini
e da un lato e il prezzo puo muoversi facilmente.

??? success "Accendi quando"
    - Regime = `TREND_DOWN` (backtest: 50% WR, `+0.14R`)
    - Regime = `TREND_UP` (`E=+0.01R`, quasi neutro ma non negativo)
    - Book imbalance estremo (`Imb > 0.85` o `< 0.15` nel log)
    - Volume basso-medio (non un breakout)

??? danger "Spegni quando"
    - Regime = `COMPRESSION` (troppo tranquillo, pochi segnali)
    - Notizie importanti in corso (lo spread si allarga)
    - Piu di 5 stop loss consecutivi nella stessa sessione

**Come leggere l'imbalance nel log**:
```
STATUS: CVD1m=+25.06  Imb=0.948  VolZ=0.00
```
`Imb=0.948` = 94.8% buy side — segnale estremo per ImbalanceScalp LONG.

**Disattivazione**:
```
IS_ENABLED=false
```

---

## 4. Matrice Decisionale

Usa questa tabella ogni lunedi per decidere quali strategie tenere accese.

| Condizione | VolumeBreakout | MeanReversion | LiqSqueeze | ImbalanceScalp |
|------------|:--------------:|:-------------:|:----------:|:--------------:|
| `TREND_UP` + OI cresce | OFF | OFF | SE liquidazioni | ON |
| `TREND_DOWN` + liquidazioni | ON | OFF | ON | ON |
| `RANGE` + volume basso | OFF | ON | OFF | CAUTELA |
| `COMPRESSION` | ON | ON | OFF | OFF |
| `EXPANSION` (post-breakout) | ON | OFF | SE liquidazioni | ON |
| Funding `> +0.1%` | OFF | SHORT only | ON | SHORT only |
| Funding `< -0.05%` | LONG only | LONG only | ON | LONG only |

!!! tip "Legenda"
    - **ON** — tienila accesa
    - **OFF** — spegnila
    - **SE liquidazioni** — solo se `[LIQUIDATION]` appare spesso nel log
    - **CAUTELA** — riduci sizing del 50%

---

## 5. Processo di Revisione Mensile

Dedica **30 minuti al mese** a questo processo.

### Prima settimana del mese

```
1. Identifica il regime prevalente dell'ultimo mese:
   - BTC era in trend? In range?
   - Qual era il Fear & Greed medio su alternative.me?

2. Controlla le metriche del bot:
   docker exec coinmaker-bot python -c "
   from src.journal.signal_log import SignalLog
   SignalLog('data/signal_log.db').print_report()
   "

3. Prendi una decisione per ogni strategia:
   - E(R) > +0.08R  ->  scala sizing del 25%
   - E(R) tra -0.08R e +0.08R  ->  tieni invariato
   - E(R) < -0.08R  ->  spegni o abbassa sizing al 50%
```

!!! warning "Regola dei 3 mesi"
    Non cambiare i parametri di una strategia piu di una volta ogni 3 mesi.
    Ogni modifica ha bisogno di tempo per essere validata.

    **Unica eccezione**: se perdi >5% del capitale in una settimana — spegni tutto,
    analizza, poi riaccendi con cautela.

---

## 6. Glossario

| Termine | Spiegazione |
|---------|-------------|
| `E(R)` | Expectancy in R. `+0.10R` significa: per ogni $1 rischiato guadagni $0.10 in media. |
| `WR%` | Win Rate. Percentuale di trade vincenti. Una strategia con 30% WR e 4R di profitto medio e ottima. |
| `R` | Unita di rischio. Se rischi $100 per trade, 1R = $100. |
| Funding Rate | Costo di tenere aperta una posizione long vs short. Se positivo, i long pagano i short. |
| OI | Open Interest. Quanti contratti futures aperti in totale. Cresce = nuovi soldi entrano. |
| CVD | Cumulative Volume Delta. Misura la pressione netta di acquisto vs vendita. |
| Imbalance | Squilibrio del book. 0.9 = 90% degli ordini sono buy. |
| Vol Z-score | Volume attuale vs media storica. 2.5 = volume 2.5x sopra la media. |
