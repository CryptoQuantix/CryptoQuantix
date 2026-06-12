# Regime Detection e Strategie Quantitative

## 1. Market Regime — Teoria

Il **regime di mercato** descrive lo stato strutturale del mercato in un dato momento. Le strategie che funzionano in trend non funzionano in range, e viceversa. Ignorare il regime e la causa principale di drawdown evitabili.

### 1.1 Tassonomia dei Regimi

| Regime | Descrizione | Caratteristiche tecniche |
|--------|-------------|--------------------------|
| TREND_UP | Rialzo sostenuto | ADX > 25, MA50 > MA200, CVD crescente |
| TREND_DOWN | Ribasso sostenuto | ADX > 25, MA50 < MA200, CVD decrescente |
| RANGE | Laterale tra supporto/resistenza | ADX < 20, range stretto, OBI oscillante |
| COMPRESSION | Range che si restringe | Volatilita decrescente, ATR < percentile 20 |
| EXPANSION | Breakout da compressione | Volatilita esplode, volume spike |
| UNKNOWN | Dati insufficienti | < 30 candle o segnali contrastanti |

### 1.2 Regime e Profittabilita delle Strategie

```
Strategia          | TREND_UP | TREND_DOWN | RANGE | COMPR. | EXPANS.
-------------------+----------+------------+-------+--------+---------
VolumeBreakout     |  Bassa   |   Bassa    |  No   | Alta   |  Alta
MeanReversion      |  **NO**  |   **NO**   | Alta  | Media  |  Bassa
LiquidationSqueeze |  Media   |   Media    | Bassa | Bassa  |  Alta
ImbalanceScalp     |  Media   |   Media    | Alta  | Alta   |  Bassa
```

**Nota**: MeanReversion e disabilitata HARD in TREND (non solo penalizzata dallo score, ma bloccata prima ancora dal check di regime nella strategia stessa).

---

## 2. RegimeDetector — Algoritmo

### 2.1 Indicatori Calcolati

**Input**: lista di N candle OHLCV (min 30, tipicamente 50 di 1 minuto)

**Step 1: ATR (Average True Range)**

```
TR_i = max(H_i - L_i, |H_i - C_{i-1}|, |L_i - C_{i-1}|)
ATR_14 = EMA(TR, period=14)
```

L'ATR misura la volatilita "vera" includendo i gap overnight (rilevanti per crypto 24/7).

```python
def _compute_atr(self, candles: List[dict], period: int = 14) -> float:
    trs = []
    for i in range(1, len(candles)):
        h, l, c_prev = candles[i]["high"], candles[i]["low"], candles[i-1]["close"]
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        trs.append(tr)
    if len(trs) < period:
        return np.mean(trs) if trs else 0.0
    # Wilder's EMA (smoothing = 1/period)
    atr = np.mean(trs[:period])
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr
```

**Step 2: ADX Proxy (Direction Index)**

Il vero ADX richiede DI+ e DI- completi. Usiamo un proxy semplificato basato sulla correlazione della sequenza di close:

```python
def _adx_proxy(self, closes: np.ndarray, period: int = 14) -> float:
    """
    Proxy dell'ADX: stddev dei return normalizzata per la variazione totale.
    Valori vicini a 1 = trend forte; vicini a 0 = mercato caotico.
    """
    returns = np.diff(np.log(closes[-period:]))
    if len(returns) < 2:
        return 0.0
    # Sequenza di trend: mean(|r|) / std(r), normalizzato in [0,1]
    mean_abs = np.mean(np.abs(returns))
    std_r = np.std(returns)
    if std_r < 1e-10:
        return 0.0
    return min(1.0, mean_abs / std_r * 0.5)  # normalizzazione empirica
```

**Step 3: MA Alignment**

```python
ma_fast = np.mean(closes[-10:])   # MA10
ma_slow = np.mean(closes[-30:])   # MA30
ma_alignment = (ma_fast - ma_slow) / ma_slow  # > 0 = bullish, < 0 = bearish
```

**Step 4: Realized Volatility**

```python
log_returns = np.diff(np.log(closes[-20:]))
realized_vol = np.std(log_returns) * np.sqrt(60 * 24)  # annualizzata (da 1m a daily)
```

### 2.2 Algoritmo di Classificazione

Per ogni regime calcola un "score" [0,1] e prende il regime con score massimo:

```python
def _classify(self, adx, ma_alignment, realized_vol, atr, cvd, book_imbalance):
    scores = {}

    # --- TREND_UP ---
    trend_up_score = 0.0
    if adx > 0.4:           trend_up_score += 0.30  # ADX forte
    if ma_alignment > 0.005: trend_up_score += 0.25  # MA bullish
    if cvd > 0:             trend_up_score += 0.25  # CVD positivo
    if book_imbalance > 0.55: trend_up_score += 0.20  # book imbalance bullish
    scores["TREND_UP"] = trend_up_score

    # --- TREND_DOWN ---
    trend_down_score = 0.0
    if adx > 0.4:            trend_down_score += 0.30
    if ma_alignment < -0.005: trend_down_score += 0.25
    if cvd < 0:              trend_down_score += 0.25
    if book_imbalance < 0.45: trend_down_score += 0.20
    scores["TREND_DOWN"] = trend_down_score

    # --- RANGE ---
    range_score = 0.0
    if adx < 0.25:           range_score += 0.35  # ADX debole
    if abs(ma_alignment) < 0.003: range_score += 0.35  # MA piatte
    if 0.45 < book_imbalance < 0.55: range_score += 0.30  # OBI neutro
    scores["RANGE"] = range_score

    # --- COMPRESSION ---
    vol_percentile = percentileofscore(self._vol_history, realized_vol)
    compr_score = max(0.0, 1.0 - vol_percentile / 100 * 2)  # vol bassa
    if adx < 0.2: compr_score += 0.3
    scores["COMPRESSION"] = min(1.0, compr_score)

    # --- EXPANSION ---
    exp_score = max(0.0, vol_percentile / 100 * 2 - 1.0)  # vol alta
    scores["EXPANSION"] = min(1.0, exp_score)

    best_regime = max(scores, key=scores.get)
    confidence = scores[best_regime]
    return Regime[best_regime], confidence, scores
```

### 2.3 MarketRegime Output

```python
@dataclass
class MarketRegime:
    regime: Regime           # enum: TREND_UP, TREND_DOWN, RANGE, COMPRESSION, EXPANSION
    confidence: float        # [0,1] — confidenza nella classificazione
    adx: float               # proxy ADX
    realized_vol: float      # volatilita realizzata annualizzata
    ma_alignment: float      # (MA_fast - MA_slow) / MA_slow
    atr: float               # Average True Range
    favorable_strategies: List[str]  # strategie consigliate per questo regime
```

---

## 3. ScoringEngine — Algoritmo di Valutazione

### 3.1 Filosofia

Il sistema di scoring serve a:
1. **Disabilitare strategie in sottoperformance** (regime avverso o edge esaurito)
2. **Modulare l'exposure** verso le strategie migliori
3. **Adattarsi nel tempo** senza intervento manuale

### 3.2 Metrica di Score

```
Score(S) = WinRate(S) * max(0, Expectancy(S)) * (1 + Sharpe_norm(S))
```

dove tutte le metriche sono calcolate sugli ultimi 30 giorni di trade della strategia S.

**WinRate**: proporzione di trade profittevoli
```
WR = N_wins / N_total     in [0, 1]
```

**Expectancy** (in R-multiple):
```
E[R] = WR * avg_win_R - (1 - WR) * avg_loss_R
```
dove R = profitto / rischio per trade. E[R] > 0 = edge statistico positivo.

**Sharpe normalizzato** (su R-multiples):
```
Sharpe_R = E[R] / std(R)        (Sharpe ratio su R-multiples)
Sharpe_norm = clip(Sharpe_R / 3.0, 0, 1)    # normalizza in [0,1] assumendo Sharpe 3 = eccellente
```

**Score totale**: in [0, 1] con interpretazione:
- Score 0.0 → strategia non ha edge (disabilitata)
- Score 0.5 → performance nella media
- Score 1.0 → eccellente (WR=70%, E[R]=1.5R, Sharpe=3)

**Soglia minima**: < 5 trade → score default 0.5 (benefit of the doubt, non abbastanza dati)

### 3.3 Regime Gate

```python
REGIME_RULES = {
    "VolumeBreakoutStrategy": {
        "favorable": [Regime.EXPANSION, Regime.TREND_UP, Regime.TREND_DOWN],
        "disabled":  [Regime.RANGE],
    },
    "MeanReversionStrategy": {
        "favorable": [Regime.RANGE, Regime.COMPRESSION],
        "disabled":  [Regime.TREND_UP, Regime.TREND_DOWN],  # HARD BLOCK
    },
    "LiquidationSqueezeStrategy": {
        "favorable": [Regime.EXPANSION],
        "disabled":  [],
    },
    "ImbalanceScalpStrategy": {
        "favorable": [Regime.RANGE, Regime.COMPRESSION],
        "disabled":  [Regime.EXPANSION],
    },
}

def should_trade(self, strategy_name: str, current_regime: str) -> Tuple[bool, str]:
    rules = REGIME_RULES.get(strategy_name, {})
    # Hard block
    if current_regime in [r.value for r in rules.get("disabled", [])]:
        return False, f"regime {current_regime} disabled for {strategy_name}"
    # Score gate
    score = self._scores.get(strategy_name, StrategyScore(strategy_name)).score
    if score < self.min_score_threshold:  # default 0.3
        return False, f"score {score:.3f} below threshold"
    return True, "OK"
```

---

## 4. Strategie Quantitative

### 4.1 VolumeBreakout — Breakout Volumetrico

**Edge teorico**: I breakout genuini da zone di consolidamento sono accompagnati da spike di volume e delta fortemente direzionali. I falsi breakout tendono ad avere volume basso o delta contrario.

**Condizioni di ingresso LONG** (tutti devono essere soddisfatti):
1. `price > max(close_{t-N:t-1})` — breakout su N-candle high (default N=20)
2. `volume_zscore > 2.0` — spike di volume (>2 sigma dalla media)
3. `cvd_1m > 0` e `delta_pct > 60%` — flow conferma direzione
4. `book_imbalance > 0.55` — OBI bullish
5. `oi_change_pct > -0.5%` — OI non in calo netto (esclude squeeze chiusura)
6. `scoring.should_trade("VolumeBreakout", regime)` — gate di scoring

**Condizioni SHORT** (speculari con min invece di max, imbalance < 0.45).

**Sizing**:
```python
atr = compute_atr(candle_history, 14)
stop_loss = entry_price - 1.5 * atr   # 1.5 ATR sotto entry
risk_per_trade = equity * base_risk_pct   # es. $100 su $10000
quantity = risk_per_trade / abs(entry - sl)
take_profit = entry + 2.0 * abs(entry - sl)  # 2R target
```

**Rate limiting**: max 1 segnale ogni 5 minuti per prevenire overtrading in gap fill.

**Gestione posizione**: delegata a `PositionMonitor` (SL/TP fissi sull'ordine Deribit).

---

### 4.2 MeanReversion — Regressione alla Media VWAP

**Edge teorico**: In regimi di range, il prezzo tende a tornare al VWAP (prezzo di equilibrio istituzionale) quando si estende troppo. Questo e un'espressione del concetto di *mean reversion* in finanza quantitativa.

**Processo stocastico sottostante**: il prezzo in range si comporta approssimativamente come un processo di Ornstein-Uhlenbeck:
```
dP_t = theta * (mu - P_t) * dt + sigma * dW_t
```
dove `theta` = velocita di mean reversion, `mu` = VWAP (livello di equilibrio), `sigma` = volatilita, `dW_t` = moto browniano.

**Condizioni di ingresso SHORT** (prezzo esteso sopra VWAP):
1. `regime in [RANGE, COMPRESSION]` — HARD BLOCK in trend
2. `vwap_z > 2.0` — prezzo >2 sigma sopra VWAP (estremo statistico)
3. `book_imbalance < 0.50` — OBI non confermante il rialzo (segnale contrastante)
4. `is_absorption` — segnale di assorbimento buy (muro di venditori invisibile)
5. `volume_zscore < 1.5` — volume non eccessivo (esclude breakout genuini)
6. `aggression_ratio < 0.55` — flusso non dominato dai compratori

**Take Profit**: VWAP (price target = ritorno al VWAP)
**Stop Loss**: entry + ATR * 1.0 (stop stretto — se non rientra velocemente, invalido)

**Ratio R/R tipico**: 1.5-2.5 (TP = VWAP, SL = 1 ATR)

---

### 4.3 LiquidationSqueeze — Cascade da Liquidazioni

**Edge teorico**: Le liquidazioni forzate creano squilibri di flow temporanei e prevedibili. Un cluster di liquidazioni short (BUY liquidations) indica che molti trader short vengono chiusi a market → pressione buy temporanea → prezzo sale → altre liquidazioni short → cascade auto-alimentante.

**Pattern Short Squeeze**:
1. Grande liquidazione short (`liq_buy_volume_10m > threshold`, default 50 BTC)
2. Buy liq >> sell liq (`liq_buy_volume_10m > 2 * liq_sell_volume_10m`)
3. CVD confirma direzione (`cvd_1m > 0`)
4. OI scende (`oi_change_pct < -0.5%`) — conferma chiusura di posizioni short

**Pattern Long Dump** (speculare):
1. Grande liquidazione long (`liq_sell_volume_10m > threshold`)
2. Sell liq >> buy liq
3. CVD negativo
4. OI scende

**Timing**: le cascade durano 30-300 secondi. Entry immediato con market order (latenza e critica). TP aggressivo (0.3-0.5%) perche la spinta si esaurisce.

**Rischio**: le liquidazioni possono invertirsi bruscamente se c'e un "whale" che vende nell'opposta direzione. SL stretto (0.2%).

---

### 4.4 ImbalanceScalp — Scalp su Order Book Imbalance

**Edge teorico**: Grandi imbalance nell'order book (OBI > 0.65 o < 0.35) con presenza di liquidity vacuum creano situazioni in cui il prezzo si muove rapidamente verso la zona a minor resistenza. Questo e un'applicazione diretta della microstrutttura classica.

**Condizioni LONG**:
1. `book_imbalance > 0.65` — forte squilibrio buy nel book (top 10 livelli)
2. `aggression_ratio > 0.55` — flow aggressivo confirma (non solo orders passivi)
3. `cvd_1m > 0` — flow recent positivo
4. `is_liq_vacuum` — vacuum lato ask (poco resistenza sopra)
5. `spread_bps < 5` — spread accettabile (non mercato illiquido)

**Sizing**: 50% del normale (scalp ad alto turnover, position size ridotta per gestire velocita di esecuzione).

**Target**: 0.5% (TP) con 0.3% stop → R/R = 1.67. Su decine di scalp al giorno, l'edge si accumula.

**Durata attesa**: 30 secondi - 5 minuti. La condizione di imbalance si esaurisce rapidamente.

---

## 5. Confronto Strategie — Parametri Chiave

| Parametro | VolumeBreakout | MeanReversion | LiqSqueeze | ImbalanceScalp |
|-----------|---------------|---------------|------------|----------------|
| **Timeframe** | 15-60 min | 15-60 min | 1-10 min | 1-10 min |
| **Target (TP)** | 2-3 R | ritorno VWAP | 0.3-0.5% | 0.5% |
| **Stop (SL)** | 1.5 ATR | 1.0 ATR | 0.2% | 0.3% |
| **R/R minimo** | 2:1 | 1.5:1 | 1.5:1 | 1.67:1 |
| **Win rate attesa** | 40-55% | 55-65% | 45-60% | 50-60% |
| **Regime ottimale** | TREND/EXPANSION | RANGE | EXPANSION | RANGE |
| **Frequenza segnali** | Bassa (1-3/giorno) | Media (3-8/giorno) | Bassa-Media | Alta (5-20/giorno) |
| **Size relativa** | 100% | 100% | 100% | 50% |

### 5.1 Expectancy Attesa

Con la formula `E[R] = WR * avg_win_R - (1-WR) * avg_loss_R` e i parametri sopra (con avg_win = TP/R e avg_loss = 1R):

**VolumeBreakout** (WR=45%, avg_win=2R, avg_loss=1R):
```
E[R] = 0.45 * 2 - 0.55 * 1 = 0.90 - 0.55 = +0.35R per trade
```

**MeanReversion** (WR=60%, avg_win=1.5R, avg_loss=1R):
```
E[R] = 0.60 * 1.5 - 0.40 * 1 = 0.90 - 0.40 = +0.50R per trade
```

**LiqSqueeze** (WR=50%, avg_win=1.5R, avg_loss=1R):
```
E[R] = 0.50 * 1.5 - 0.50 * 1 = 0.75 - 0.50 = +0.25R per trade
```

**ImbalanceScalp** (WR=55%, avg_win=1.67R, avg_loss=1R, size 50%):
```
E[R] = 0.55 * 1.67 - 0.45 * 1 = 0.919 - 0.45 = +0.47R per trade
     * 0.5 size = +0.235R effettivo
```

Valori puramente teorici — il backtest e Monte Carlo (doc 06) quantificano la variabilita.
