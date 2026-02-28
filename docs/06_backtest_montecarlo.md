# Backtest Engine e Analisi Statistica

## 1. Filosofia del Backtesting

Il backtest e uno strumento di validazione, non di ottimizzazione. I rischi principali:

- **Overfitting**: adattare i parametri ai dati storici → il modello "memorizza" il passato invece di imparare
- **Lookahead bias**: usare informazioni future non disponibili al momento del segnale
- **Survivorship bias**: testare solo su asset che sono sopravvissuti
- **Transaction cost underestimation**: ignorare slippage, fee, impatto mercato
- **Data snooping**: testare molti modelli sugli stessi dati → almeno uno sara profittevole per caso

Il nostro backtest usa la **stessa codebase** delle strategie live: lo stesso `OrderflowEngine`, lo stesso `RegimeDetector`, le stesse strategie. L'unico mock e l'`OrderManager` (che registra fills invece di inviarli a Deribit).

---

## 2. BacktestEngine — Architettura

### 2.1 Flusso di Esecuzione

```
BacktestEngine.run(strategy, symbol, start_date, end_date)
│
├── _load_candles() → carica da DuckDB o usa candle_data fornito
│   └── _load_from_duckdb(): SQL su tabella agg_trades → OHLCV 1m
│
├── MockOrderManager() → replace strategy.order_manager
│
├── For each candle_i in candle_data:
│   ├── _feed_candle_to_engine(of_engine, candle)
│   │   └── Simula 2 aggTrade: buy_volume + sell_volume
│   │
│   ├── _check_exits(open_trades, high, low, close)
│   │   ├── LONG: se low <= sl_price → exit at sl_price ("sl")
│   │   │        se high >= tp_price → exit at tp_price ("tp")
│   │   └── SHORT: speculare
│   │
│   └── if i % scan_interval_candles == 0 and i >= 30:
│       ├── regime_detector.detect(candle_history) → aggiorna regime
│       └── strategy.scan() → signals
│           └── Per ogni signal: crea BacktestTrade, aggiungi a open_trades
│
└── Chiudi tutti i trade aperti a fine dati ("end_of_data")
    └── BacktestMetrics.compute(trades) → metriche performance
```

### 2.2 Simulazione dei Fill

```python
def execute_generic_trade(self, ..., price, entry_type="market", ...):
    fill_price = price
    if entry_type == "market":
        # Slippage: mercato si muove contro di te al fill
        slippage = price * self.slippage_pct  # default 0.05%
        fill_price += slippage if direction == "buy" else -slippage
    # Fee Deribit futures taker: 0.05%
    # Applicata in _compute_pnl()
```

**Struttura fee Deribit**:
```
Taker fee (market order): 0.05% del nozionale
Maker fee (limit order):   0.03% del nozionale
Fee per trade (entry + exit): 2 * 0.05% = 0.10% (andata + ritorno)
```

Su BTC-PERPETUAL a $64500 con 0.01 BTC:
```
Nozionale = 64500 * 0.01 = $645
Fee entry  = 645 * 0.0005 = $0.32
Fee exit   = 645 * 0.0005 = $0.32
Total fee  = $0.64 per round trip
```

### 2.3 SQL per Ricostruzione OHLCV da Tick

Il backtest carica dati storici dal DuckDB aggregando i tick in candle 1 minuto:

```sql
SELECT
    (timestamp_ms / 60000) * 60000 as bucket_ts,
    FIRST(price ORDER BY timestamp_ms) as open,
    MAX(price) as high,
    MIN(price) as low,
    LAST(price ORDER BY timestamp_ms) as close,
    SUM(quantity) as volume,
    SUM(CASE WHEN NOT is_buyer_maker THEN quantity ELSE 0 END) as buy_volume,
    SUM(CASE WHEN is_buyer_maker THEN quantity ELSE 0 END) as sell_volume,
    COUNT(*) as trade_count
FROM agg_trades
WHERE symbol = 'BTCUSDT'
  AND timestamp_ms BETWEEN ? AND ?
GROUP BY bucket_ts
ORDER BY bucket_ts
```

L'uso di `FIRST()` e `LAST()` invece di `MIN(timestamp_ms)` + subquery e specifico di DuckDB e garantisce open/close corretto anche con trade fuori ordine.

---

## 3. Metriche di Performance

### 3.1 Rendimento e Drawdown

**Total Return**:
```
R_total = (Equity_final - Equity_initial) / Equity_initial * 100
```

**Maximum Drawdown (MDD)**:
```
DD(t) = (Peak(t) - Equity(t)) / Peak(t) * 100
MDD = max_t DD(t)
```

dove `Peak(t) = max_{s <= t} Equity(s)` (massimo storico fino a t).

**Calmar Ratio** (rendimento aggiustato per drawdown):
```
Calmar = R_total (annualizzato) / MDD
```
Calmar > 1: rendimento annuale supera il drawdown massimo → buona gestione del rischio.

### 3.2 Sharpe Ratio

Il **Sharpe Ratio** misura il rendimento excess per unita di rischio:

```
Sharpe = (E[R] - R_f) / sigma(R)
```

Nel trading intraday, il risk-free rate `R_f` e approssimativamente 0 su timeframe brevi. Calcoliamo lo Sharpe sui **R-multiples** (rendimenti normalizzati per il rischio di ogni trade):

```
R_i = (exit_price - entry_price) / |entry_price - sl_price|  (long)
R_i = (entry_price - exit_price) / |sl_price - entry_price|  (short)
```

```
Sharpe_R = mean(R_multiples) / std(R_multiples)
```

Benchmarks del settore:
- Sharpe < 0.5: strategia debole
- 0.5 - 1.0: accettabile
- 1.0 - 2.0: buono
- > 2.0: eccellente (difficile da mantenere su lunghi periodi)

### 3.3 Sortino Ratio

Il **Sortino Ratio** penalizza solo la volatilita negativa (downside risk):

```
Sortino = E[R] / sigma_downside(R)
```

dove `sigma_downside = sqrt(E[min(R-MAR, 0)^2])` e la deviazione standard dei rendimenti sotto il MAR (Minimum Acceptable Return, spesso = 0).

Il Sortino e preferibile al Sharpe per strategie asimmetriche (molte piccole vincite, rare grandi perdite → Sharpe basso ma Sortino accettabile).

```python
@staticmethod
def sortino_ratio(r_multiples: List[float], mar: float = 0.0) -> float:
    returns = np.array(r_multiples)
    downside = returns[returns < mar] - mar
    if len(downside) == 0:
        return float("inf")
    sigma_down = np.sqrt(np.mean(downside ** 2))
    return float(np.mean(returns) / sigma_down) if sigma_down > 0 else 0.0
```

### 3.4 Profit Factor

```
Profit Factor = Sum(winning_trades_PnL) / |Sum(losing_trades_PnL)|
```

- PF > 1.0: strategia profittevole
- PF > 1.5: buono
- PF > 2.0: eccellente

### 3.5 Payoff Ratio e Win Rate

```
Payoff Ratio = avg_win / avg_loss  (in valore assoluto)
```

La relazione fondamentale tra WR e Payoff:
```
Break-even WR = 1 / (1 + Payoff)
```

Con Payoff = 2 (avg_win = 2 * avg_loss): break-even WR = 1/3 = 33%
Con Payoff = 1 (avg_win = avg_loss): break-even WR = 50%

Un sistema puo essere profittevole con WR basso se il Payoff e alto, e viceversa.

---

## 4. Monte Carlo Simulation — Bootstrap Resampling

### 4.1 Teoria del Bootstrap

Il metodo **bootstrap** (Efron, 1979) stima la distribuzione di una statistica campionando con rimpiazzo dai dati storici. Nel trading:

- I trade storici `{R_1, R_2, ..., R_N}` costituiscono il campione originale
- Ogni simulazione: campiona N valori con rimpiazzo → sequenza alternativa possibile
- Eseguire 1000 simulazioni → distribuzione delle possibili sequenze di trade

**Assunzione chiave**: i trade sono statisticamente indipendenti (no correlazione seriale). Questa e una semplificazione: trade in trend correlato possono non essere indipendenti. Tuttavia, per sistemi con holding period brevi (< 1 giorno), l'assunzione e ragionevole.

### 4.2 Algoritmo Monte Carlo

```python
def run(self, trades, initial_equity=10000, n_trades=None):
    pnls      = [t.pnl_usd for t in trades]
    r_mults   = [t.r_multiple for t in trades]
    n_trades  = n_trades or len(pnls)

    final_equities = np.zeros(self.n_simulations)
    max_drawdowns  = np.zeros(self.n_simulations)
    sharpes        = np.zeros(self.n_simulations)

    for i in range(self.n_simulations):
        # Resample con rimpiazzo
        sim_pnls = np.random.choice(pnls, size=n_trades, replace=True)
        sim_r    = np.random.choice(r_mults, size=n_trades, replace=True)

        # Equity path
        equity_path = initial_equity + np.cumsum(np.concatenate([[0], sim_pnls]))
        final_equities[i] = equity_path[-1]

        # Max drawdown per questa simulazione
        peak = np.maximum.accumulate(equity_path)
        dd_pct = (peak - equity_path) / peak * 100
        max_drawdowns[i] = np.max(dd_pct)

        # Sharpe per questa simulazione
        std_r = np.std(sim_r)
        sharpes[i] = np.mean(sim_r) / std_r if std_r > 0 else 0.0
```

### 4.3 Output Statistico

**Distribuzione del capitale finale** (dopo N trade):

```
P5  (worst 5%):  [equity_p5]    <- scenario pessimistico
P25:             [equity_p25]
P50 (median):    [equity_p50]   <- scenario piu probabile
P75:             [equity_p75]
P95 (best 5%):   [equity_p95]   <- scenario ottimistico
```

**Distribuzione del Max Drawdown**:

```
DD_P50 (median):   <- drawdown "normale"
DD_P75:            <- drawdown in scenario avverso
DD_P95 (worst 5%): <- drawdown in scenario molto avverso
```

**Probabilita di rovina** (equity < threshold, default 50% del capitale):
```
P(ruin) = n_simulations_below_threshold / total_simulations
```

**Sharpe Confidence Interval** (90%):
```
[Sharpe_P5, Sharpe_P95]
```

### 4.4 Interpretazione dei Risultati

**Esempio output** per sistema con 100 trade storici, $10,000 equity, 1000 simulazioni:

```
MONTE CARLO SIMULATION (1000 runs x 100 trades)
====================================================
Initial Equity:     $10,000.00

--- Final Equity Distribution ---
  P5  (worst 5%):   $ 8,450.00    <- scenario: puoi perdere fino a $1,550
  P25:              $ 9,800.00
  P50 (median):     $11,200.00    <- piu probabile: +12%
  P75:              $12,600.00
  P95 (best 5%):    $14,300.00

--- Max Drawdown Distribution ---
  P50 (median):     12.3%
  P75:              18.7%
  P95 (worst 5%):   31.2%          <- raro ma possibile: drawdown di $3,120

--- Probabilities ---
  Profitable:       82.3%          <- 82% delle sequenze sono profittevoli
  Ruin (50% loss):   0.2%          <- molto raro con sizing conservativo

--- Sharpe (90% CI) ---
  Mean:             0.842
  Range:            [0.312, 1.498]  <- ampia variabilita: serve piu storia
```

### 4.5 Numero di Trade per Significativita Statistica

**Legge dei Grandi Numeri**: la media campionaria converge alla media vera all'aumentare di N.

**Errore standard della media**:
```
SE = sigma(R) / sqrt(N)
```

Per avere CI al 95% del Sharpe con larghezza < 0.5:
```
N > (2 * z_0.975 * sigma / 0.5)^2
```

Con sigma = 1 (R-multiples con std=1), z = 1.96:
```
N > (2 * 1.96 / 0.5)^2 = 61.5
```

Servono **almeno 62 trade** per avere un Sharpe statisticamente significativo con precisione ±0.25. Per la pratica, raccomandato > 100 trade.

Con < 30 trade, qualsiasi statistica di performance e rumore — lo scoring engine applica correttamente il default di 0.5 in questo caso.

---

## 5. Journal Analytics — Dataset per Machine Learning

Il `TradeLogger` salva per ogni trade il contesto completo al momento dell'ingresso:

```python
@dataclass
class TradeSnapshot:
    # Identificazione
    trade_id: str
    strategy: str
    symbol: str
    direction: str
    timestamp_ms: int

    # Prezzi
    entry_price: float
    sl_price: float
    tp_price: float
    quantity: float

    # Contesto orderflow (feature per ML)
    regime: str
    cvd_1m: float
    cvd_5m: float
    cvd_15m: float
    book_imbalance: float
    aggression_ratio: float
    volume_zscore: float
    vwap_z: float
    oi_change_pct: float
    kyle_lambda: float
    is_absorption: bool
    is_liq_vacuum: bool

    # Esito (riempito all'uscita)
    exit_price: float = 0.0
    exit_reason: str = ""    # "tp", "sl", "manual"
    pnl_usd: float = 0.0
    r_multiple: float = 0.0
    duration_minutes: float = 0.0
    win: bool = False
```

**Uso per ML**: dopo 200+ trade si hanno abbastanza dati per addestrare un classificatore binario (win/loss) usando le feature di orderflow come input. Approcci possibili:
- Logistic Regression (baseline interpretabile)
- Gradient Boosting (XGBoost/LightGBM) per catturare non-linearita
- Random Forest per importanza delle feature

Il target: predire se un trade sara vincente → usare il winrate predetto nel F3 del risk engine.
