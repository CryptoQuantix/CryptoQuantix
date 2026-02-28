# Risk Engine — Sizing Dinamico e Gestione del Rischio

## 1. Principi di Gestione del Rischio in Trading Quantitativo

Il risk management e la componente piu critica di qualsiasi sistema di trading. Un sistema con edge positivo ma risk management sbagliato porta inevitabilmente alla rovina. I tre principi fondamentali:

1. **Ruin prevention** (sopravvivenza): non perdere mai abbastanza da non poter recuperare
2. **Drawdown control**: limitare le perdite consecutive che degradano il capitale psicologico e finanziario
3. **Optimal sizing**: massimizzare la crescita del capitale nel lungo termine (Kelly Criterion)

---

## 2. Kelly Criterion — Teoria Matematica

### 2.1 Formula di Kelly (Caso Binario)

John L. Kelly (1956, "A New Interpretation of Information Rate", *Bell System Technical Journal*) ha derivato la formula ottimale per dimensionare le scommesse in sistemi con edge positivo:

```
f* = (p * b - q) / b  =  (p * b - (1-p)) / b
```

dove:
- `f*` = frazione del capitale da rischiare (Kelly fraction)
- `p` = probabilita di vincita (win rate)
- `q = 1 - p` = probabilita di perdita
- `b` = odds nette = (guadagno medio) / (perdita media)

**Esempio**: WR = 50%, avg_win = 2R, avg_loss = 1R
```
b = 2/1 = 2
f* = (0.5 * 2 - 0.5) / 2 = (1.0 - 0.5) / 2 = 0.5 / 2 = 0.25
```
Kelly dice: rischia il 25% del capitale per trade. Nella pratica, questo e troppo aggressivo.

### 2.2 Generalizzazione con R-Multiples

Per sistemi di trading con distribuzioni asimmetriche, la formula si generalizza:

```
f* = E[R] / E[R^2]
```

dove `E[R]` = expectancy e `E[R^2]` = secondo momento (mean squared return).

Per una distribuzione binomiale (vincita +W, perdita -L):
```
E[R] = p*W - (1-p)*L
E[R^2] = p*W^2 + (1-p)*L^2
f* = (p*W - (1-p)*L) / (p*W^2 + (1-p)*L^2)
```

### 2.3 Fractional Kelly (Pratica)

Il Kelly pieno e spesso troppo aggressivo perche:
1. Le stime di p e b sono imprecise
2. Il Kelly pieno massimizza il tasso di crescita geometrica ma produce drawdown enormi (DD ~50% in scenari avversi)
3. I mercati cambiano → l'edge stimato su dati passati non e stabile

**Standard del settore**: usare Half-Kelly o Quarter-Kelly:
```
f_practical = f* * kelly_fraction    (kelly_fraction = 0.25 - 0.5)
```

Nel nostro sistema:
```python
kelly_fraction = 0.25  # Quarter Kelly (molto conservativo)
kelly_size = equity * kelly_fraction * (expectancy / expected_r_squared)
final_size = min(kelly_size, base_risk_size)  # mai superare base_risk_pct
```

---

## 3. Risk Engine 3-Factor

Il sistema calcola la size dell'ordine tramite tre fattori moltiplicativi:

```
quantity = base_quantity * F1_volatility * F2_regime * F3_scoring
```

dove `base_quantity` e la size calcolata con rischio fisso (1% del capitale).

### 3.1 Factor 1: Volatilita (ATR Percentile)

L'idea: in mercati piu volatili, la stessa size in BTC espone a piu rischio in USD → ridurre la size quando la volatilita e alta.

```python
def _compute_volatility_scalar(self, atr_percentile: float) -> float:
    """
    atr_percentile: percentile dell'ATR corrente nella distribuzione storica
                    (0 = ATR minimo storico, 100 = ATR massimo storico)
    """
    if atr_percentile < 30:
        return 1.00   # bassa vol → size piena
    elif atr_percentile < 70:
        return 0.75   # vol media → -25%
    else:
        return 0.50   # alta vol → -50%
```

**Calcolo del percentile ATR**:
```python
from scipy.stats import percentileofscore
atr_history = self._atr_history[-252:]  # ultimo anno di dati (252 sessioni)
atr_percentile = percentileofscore(atr_history, current_atr)
```

### 3.2 Factor 2: Regime di Mercato

Differenti regimi hanno differente prevedibilita → adattiamo la size:

```python
def _compute_regime_scalar(self, regime: str) -> float:
    scalars = {
        "TREND_UP":   1.00,   # trend → massima confidenza
        "TREND_DOWN": 1.00,
        "RANGE":      0.80,   # range → confidenza media
        "COMPRESSION":0.60,   # attesa → size ridotta (segnali di breakout falsi)
        "EXPANSION":  0.70,   # alta vol → potenziale, ma anche rumore
        "UNKNOWN":    0.70,   # incertezza → conservativo
    }
    return scalars.get(regime, 0.70)
```

### 3.3 Factor 3: Scoring della Strategia

Il modello winrate entra nel sizing: strategie con winrate piu alto ottengono size maggiori.

```python
def _compute_scoring_scalar(self, model_winrate: float) -> float:
    """
    model_winrate: win rate stimato dalla strategia/scoring engine [0,1]
    """
    if model_winrate < 0.40:
        return 0.50   # winrate basso → molti stop hit → size piccola
    elif model_winrate < 0.55:
        return 0.75
    elif model_winrate < 0.65:
        return 1.00   # normal case
    else:
        return 1.20   # winrate alto → slight size increase (max +20%)
```

### 3.4 Formula Completa

```python
def calculate_dynamic_size(
    self,
    instrument_name: str,
    entry_price: float,
    sl_price: float,
    atr_percentile: float = 50.0,
    regime: str = "UNKNOWN",
    model_winrate: float = 0.5,
) -> dict:
    # Rischio base in USD
    risk_usd = self._equity * self.base_risk_pct  # es. $100 su $10k

    # Fattori moltiplicativi
    f1 = self._compute_volatility_scalar(atr_percentile)
    f2 = self._compute_regime_scalar(regime)
    f3 = self._compute_scoring_scalar(model_winrate)

    # Rischio aggiustato
    adj_risk_usd = risk_usd * f1 * f2 * f3

    # Quantita: rischio / (entry - SL)
    price_risk = abs(entry_price - sl_price)
    if price_risk <= 0:
        return {"quantity": 0.0, "adj_risk_usd": 0.0}

    quantity = adj_risk_usd / price_risk

    # Minimo: 0.001 BTC (Deribit minimum)
    quantity = max(0.001, round(quantity, 4))

    return {"quantity": quantity, "adj_risk_usd": adj_risk_usd}
```

**Esempio numerico**:
- Equity: $10,000 | Base risk: 1% → $100
- ATR percentile 75 → F1 = 0.50
- Regime RANGE → F2 = 0.80
- WinRate 52% → F3 = 0.75
- Adj risk = $100 * 0.50 * 0.80 * 0.75 = $30
- Entry $64500, SL $63800 → price risk $700
- Quantity = $30 / $700 = 0.0429 BTC ≈ 0.043 BTC

---

## 4. Controlli di Portfolio

### 4.1 Can Open New Position

Prima di ogni trade, vengono verificati diversi limiti:

```python
def can_open_new_position(self) -> Tuple[bool, str]:
    # 1. Kill switch attivo?
    if self._kill_switch_active:
        return False, "Kill switch attivo — trading sospeso"

    # 2. Daily loss limit?
    daily_pnl = self._compute_daily_pnl()
    if daily_pnl < -self._equity * self.max_daily_loss_pct:
        self._activate_kill_switch("daily_loss_limit")
        return False, f"Daily loss limit raggiunto: {daily_pnl:,.2f}"

    # 3. Max open trades?
    open_positions = self.position_monitor.get_open_futures_positions()
    if len(open_positions) >= self.max_open_trades:
        return False, f"Max {self.max_open_trades} trades aperti"

    # 4. Max portfolio risk?
    total_risk = self._compute_total_risk(open_positions)
    if total_risk > self._equity * self.max_portfolio_risk:
        return False, f"Portfolio risk {total_risk:.0f} > max {self._equity * self.max_portfolio_risk:.0f}"

    return True, "OK"
```

### 4.2 Risk Utilization

```python
def get_risk_summary(self) -> dict:
    open_pos = self.position_monitor.get_open_futures_positions()
    total_notional = sum(
        abs(p.get("size", 0)) * p.get("mark_price", 0)
        for p in open_pos
    )
    risk_utilization = total_notional / self._equity * 100

    return {
        "equity": self._equity,
        "risk_utilization_pct": risk_utilization,
        "daily_pnl": self._compute_daily_pnl(),
        "open_positions": len(open_pos),
        "kill_switch_active": self._kill_switch_active,
    }
```

### 4.3 Kill Switch

Il kill switch viene attivato automaticamente in due scenari:

1. **Daily loss limit**: perdite giornaliere superano `MAX_DAILY_LOSS_PCT` (default 3%)
2. **FailureHandler**: API down per >30s con posizioni aperte

```python
def _activate_kill_switch(self, reason: str):
    self._kill_switch_active = True
    logger.critical(f"[KILL SWITCH] Attivato: {reason}")
    # Notifica Telegram
    if self._alerts:
        self._alerts.send_kill_switch(reason, daily_pnl=self._compute_daily_pnl())
    # Reset automatico a mezzanotte (daily PnL azzerato)
```

---

## 5. Position Sizing — Matematica Completa

### 5.1 Rischio Fisso vs Percentuale del Capitale

**Rischio fisso** ($100/trade): intuitivo ma non si adatta alla crescita del conto.
**Rischio percentuale** (1%/trade): si adatta automaticamente → crescita geometrica del conto.

Con rischio percentuale `r` per trade e expectancy `E[R]`:
```
Capital(n) = Capital(0) * prod_{i=1}^{n} (1 + r * R_i)
```

In media (approssimazione logaritmica):
```
E[log(Capital(n)/Capital(0))] ≈ n * (r * E[R] - r^2/2 * E[R^2])
```

Il termine `r^2/2 * E[R^2]` e la penalita per la varianza (drag della volatilita). Massimizzare questa espressione rispetto a `r` da:
```
r_optimal = E[R] / E[R^2]  = Kelly fraction
```

### 5.2 Drawdown Atteso con Kelly

Con Kelly pieno in un sistema binomiale (WR=p, win=bR, loss=-R):

- **Probabilita di drawdown del 50%** ≈ `q/p` = (1-WR)/WR
- **Massimo drawdown atteso** prima di un nuovo massimo ≈ `1/b` = 1/odds

Con Quarter Kelly, il drawdown si riduce di ~4x (il DD e quadratico nel fraction Kelly).

### 5.3 Sequenza di Perdite Consecutive

La probabilita di N perdite consecutive con WR = p:
```
P(N consecutive losses) = (1-p)^N
```

Con WR = 50%:
- 5 perdite consecutive: (0.5)^5 = 3.1% → succede ogni ~32 trade
- 10 perdite consecutive: (0.5)^10 = 0.1% → ogni ~1000 trade

Con WR = 40% (sistema piu speculativo):
- 5 perdite: (0.6)^5 = 7.8%
- 10 perdite: (0.6)^10 = 0.6%

Il **max consecutive loss** misurato dal `JournalAnalytics` serve a verificare se il sistema e statisticamente in linea con le aspettative o se c'e qualcosa di rotto.

---

## 6. Correlazione tra Strategie

Quando si eseguono N strategie simultaneamente, il rischio di portfolio non e la somma dei rischi individuali se le strategie sono correlate.

**Portfolio risk** con N strategie:
```
sigma_portfolio = sqrt(w' * Sigma * w)
```
dove `w` = vettore dei pesi (rischi per strategia), `Sigma` = matrice di correlazione dei rendimenti.

**Nel nostro caso**: le 4 nuove strategie operano su segnali diversi (breakout vs mean reversion vs liquidazioni vs imbalance) → correlazione bassa → beneficio di diversificazione.

Approssimazione conservativa: le strategie in regime diverso sono ortogonali (VolumeBreakout in EXPANSION, MeanReversion in RANGE → non operano mai insieme → correlazione ≈ 0).

Questo giustifica `MAX_PORTFOLIO_RISK = 3%` come somma dei rischi individuali (nessuno sconto di correlazione applicato per sicurezza).
