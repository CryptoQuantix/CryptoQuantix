# Backtest Engine and Statistical Analysis

## 1. Backtesting Philosophy

A backtest is a validation tool, not an optimization tool. The main risks:

- **Overfitting**: fitting parameters to historical data → the model "memorizes" the past instead of learning
- **Lookahead bias**: using future information not available at signal time
- **Survivorship bias**: testing only on assets that survived
- **Transaction cost underestimation**: ignoring slippage, fees, market impact
- **Data snooping**: testing many models on the same data → at least one will be profitable by chance

Our backtest uses the **same codebase** as the live strategies: the same
`OrderflowEngine`, the same `RegimeDetector`, the same strategies. The
only mock is the `OrderManager` (which records fills instead of sending
them to Deribit).

---

## 2. BacktestEngine — Architecture

### 2.1 Execution Flow

```
BacktestEngine.run(strategy, symbol, start_date, end_date)
│
├── _load_candles() → loads from DuckDB or uses provided candle_data
│   └── _load_from_duckdb(): SQL on agg_trades table → 1m OHLCV
│
├── MockOrderManager() → replaces strategy.order_manager
│
├── For each candle_i in candle_data:
│   ├── _feed_candle_to_engine(of_engine, candle)
│   │   └── Simulates 2 aggTrades: buy_volume + sell_volume
│   │
│   ├── _check_exits(open_trades, high, low, close)
│   │   ├── LONG: if low <= sl_price → exit at sl_price ("sl")
│   │   │        if high >= tp_price → exit at tp_price ("tp")
│   │   └── SHORT: mirrored
│   │
│   └── if i % scan_interval_candles == 0 and i >= 30:
│       ├── regime_detector.detect(candle_history) → updates regime
│       └── strategy.scan() → signals
│           └── For every signal: create BacktestTrade, add to open_trades
│
└── Close all open trades at end of data ("end_of_data")
    └── BacktestMetrics.compute(trades) → performance metrics
```

### 2.2 Fill Simulation

```python
def execute_generic_trade(self, ..., price, entry_type="market", ...):
    fill_price = price
    if entry_type == "market":
        # Slippage: the market moves against you at fill time
        slippage = price * self.slippage_pct  # default 0.05%
        fill_price += slippage if direction == "buy" else -slippage
    # Deribit futures taker fee: 0.05%
    # Applied in _compute_pnl()
```

**Deribit fee structure**:
```
Taker fee (market order): 0.05% of notional
Maker fee (limit order):  0.03% of notional
Fee per trade (entry + exit): 2 * 0.05% = 0.10% (round trip)
```

On BTC-PERPETUAL at $64500 with 0.01 BTC:
```
Notional  = 64500 * 0.01 = $645
Entry fee = 645 * 0.0005 = $0.32
Exit fee  = 645 * 0.0005 = $0.32
Total fee = $0.64 per round trip
```

### 2.3 SQL for OHLCV Reconstruction from Ticks

The backtest loads historical data from DuckDB, aggregating ticks into
1-minute candles:

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

Using `FIRST()` and `LAST()` instead of `MIN(timestamp_ms)` + subqueries
is DuckDB-specific and guarantees correct open/close even with
out-of-order trades.

---

## 3. Performance Metrics

### 3.1 Return and Drawdown

**Total Return**:
```
R_total = (Equity_final - Equity_initial) / Equity_initial * 100
```

**Maximum Drawdown (MDD)**:
```
DD(t) = (Peak(t) - Equity(t)) / Peak(t) * 100
MDD = max_t DD(t)
```

where `Peak(t) = max_{s <= t} Equity(s)` (the running maximum up to t).

**Calmar Ratio** (drawdown-adjusted return):
```
Calmar = R_total (annualized) / MDD
```
Calmar > 1: annual return exceeds the maximum drawdown → good risk
management.

### 3.2 Sharpe Ratio

The **Sharpe Ratio** measures excess return per unit of risk:

```
Sharpe = (E[R] - R_f) / sigma(R)
```

In intraday trading the risk-free rate `R_f` is approximately 0 on short
timeframes. We compute the Sharpe on **R-multiples** (returns normalized
by each trade's risk):

```
R_i = (exit_price - entry_price) / |entry_price - sl_price|  (long)
R_i = (entry_price - exit_price) / |sl_price - entry_price|  (short)
```

```
Sharpe_R = mean(R_multiples) / std(R_multiples)
```

Industry benchmarks:
- Sharpe < 0.5: weak strategy
- 0.5 - 1.0: acceptable
- 1.0 - 2.0: good
- > 2.0: excellent (hard to sustain over long periods)

### 3.3 Sortino Ratio

The **Sortino Ratio** only penalizes negative volatility (downside risk):

```
Sortino = E[R] / sigma_downside(R)
```

where `sigma_downside = sqrt(E[min(R-MAR, 0)^2])` is the standard
deviation of returns below the MAR (Minimum Acceptable Return, often 0).

Sortino is preferable to Sharpe for asymmetric strategies (many small
wins, rare large losses → low Sharpe but acceptable Sortino).

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

- PF > 1.0: profitable strategy
- PF > 1.5: good
- PF > 2.0: excellent

### 3.5 Payoff Ratio and Win Rate

```
Payoff Ratio = avg_win / avg_loss  (in absolute value)
```

The fundamental relationship between WR and Payoff:
```
Break-even WR = 1 / (1 + Payoff)
```

With Payoff = 2 (avg_win = 2 * avg_loss): break-even WR = 1/3 = 33%
With Payoff = 1 (avg_win = avg_loss): break-even WR = 50%

A system can be profitable with a low WR if the Payoff is high, and vice
versa.

---

## 4. Monte Carlo Simulation — Bootstrap Resampling

### 4.1 Bootstrap Theory

The **bootstrap** method (Efron, 1979) estimates the distribution of a
statistic by sampling with replacement from historical data. In trading:

- The historical trades `{R_1, R_2, ..., R_N}` form the original sample
- Each simulation: sample N values with replacement → an alternative possible sequence
- Run 1000 simulations → distribution of possible trade sequences

**Key assumption**: trades are statistically independent (no serial
correlation). This is a simplification: trades within a correlated trend
may not be independent. However, for systems with short holding periods
(< 1 day) the assumption is reasonable.

### 4.2 Monte Carlo Algorithm

```python
def run(self, trades, initial_equity=10000, n_trades=None):
    pnls      = [t.pnl_usd for t in trades]
    r_mults   = [t.r_multiple for t in trades]
    n_trades  = n_trades or len(pnls)

    final_equities = np.zeros(self.n_simulations)
    max_drawdowns  = np.zeros(self.n_simulations)
    sharpes        = np.zeros(self.n_simulations)

    for i in range(self.n_simulations):
        # Resample with replacement
        sim_pnls = np.random.choice(pnls, size=n_trades, replace=True)
        sim_r    = np.random.choice(r_mults, size=n_trades, replace=True)

        # Equity path
        equity_path = initial_equity + np.cumsum(np.concatenate([[0], sim_pnls]))
        final_equities[i] = equity_path[-1]

        # Max drawdown for this simulation
        peak = np.maximum.accumulate(equity_path)
        dd_pct = (peak - equity_path) / peak * 100
        max_drawdowns[i] = np.max(dd_pct)

        # Sharpe for this simulation
        std_r = np.std(sim_r)
        sharpes[i] = np.mean(sim_r) / std_r if std_r > 0 else 0.0
```

### 4.3 Statistical Output

**Final equity distribution** (after N trades):

```
P5  (worst 5%):  [equity_p5]    <- pessimistic scenario
P25:             [equity_p25]
P50 (median):    [equity_p50]   <- most likely scenario
P75:             [equity_p75]
P95 (best 5%):   [equity_p95]   <- optimistic scenario
```

**Max Drawdown distribution**:

```
DD_P50 (median):   <- "normal" drawdown
DD_P75:            <- drawdown in an adverse scenario
DD_P95 (worst 5%): <- drawdown in a very adverse scenario
```

**Probability of ruin** (equity < threshold, default 50% of capital):
```
P(ruin) = n_simulations_below_threshold / total_simulations
```

**Sharpe Confidence Interval** (90%):
```
[Sharpe_P5, Sharpe_P95]
```

### 4.4 Interpreting the Results

**Example output** for a system with 100 historical trades, $10,000
equity, 1000 simulations:

```
MONTE CARLO SIMULATION (1000 runs x 100 trades)
====================================================
Initial Equity:     $10,000.00

--- Final Equity Distribution ---
  P5  (worst 5%):   $ 8,450.00    <- scenario: you can lose up to $1,550
  P25:              $ 9,800.00
  P50 (median):     $11,200.00    <- most likely: +12%
  P75:              $12,600.00
  P95 (best 5%):    $14,300.00

--- Max Drawdown Distribution ---
  P50 (median):     12.3%
  P75:              18.7%
  P95 (worst 5%):   31.2%          <- rare but possible: a $3,120 drawdown

--- Probabilities ---
  Profitable:       82.3%          <- 82% of sequences are profitable
  Ruin (50% loss):   0.2%          <- very rare with conservative sizing

--- Sharpe (90% CI) ---
  Mean:             0.842
  Range:            [0.312, 1.498]  <- wide variability: more history needed
```

### 4.5 Trade Count for Statistical Significance

**Law of Large Numbers**: the sample mean converges to the true mean as N
grows.

**Standard error of the mean**:
```
SE = sigma(R) / sqrt(N)
```

To get a 95% CI on the Sharpe with width < 0.5:
```
N > (2 * z_0.975 * sigma / 0.5)^2
```

With sigma = 1 (R-multiples with std=1), z = 1.96:
```
N > (2 * 1.96 / 0.5)^2 = 61.5
```

You need **at least 62 trades** for a statistically significant Sharpe
with ±0.25 precision. In practice, > 100 trades is recommended.

With < 30 trades any performance statistic is noise — the scoring engine
correctly applies a 0.5 default in that case.

---

## 5. Journal Analytics — Machine Learning Dataset

The `TradeLogger` saves, for every trade, the full context at entry time:

```python
@dataclass
class TradeSnapshot:
    # Identity
    trade_id: str
    strategy: str
    symbol: str
    direction: str
    timestamp_ms: int

    # Prices
    entry_price: float
    sl_price: float
    tp_price: float
    quantity: float

    # Orderflow context (ML features)
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

    # Outcome (filled at exit)
    exit_price: float = 0.0
    exit_reason: str = ""    # "tp", "sl", "manual"
    pnl_usd: float = 0.0
    r_multiple: float = 0.0
    duration_minutes: float = 0.0
    win: bool = False
```

**ML use**: after 200+ trades there is enough data to train a binary
classifier (win/loss) using the orderflow features as inputs. Possible
approaches:
- Logistic Regression (interpretable baseline)
- Gradient Boosting (XGBoost/LightGBM) to capture non-linearities
- Random Forest for feature importance

The target: predict whether a trade will win → feed the predicted winrate
into factor 3 of the risk engine.
