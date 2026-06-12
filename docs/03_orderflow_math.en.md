# Orderflow Engine — Math and Implementation

## 1. Introduction to Orderflow Analysis

**Orderflow** is the study of the net flow of aggressive orders in the
market. Unlike classic technical analysis (which only looks at OHLCV),
orderflow splits volume into:
- **Buy volume** (market BUY orders consuming liquidity on the ask side)
- **Sell volume** (market SELL orders consuming liquidity on the bid side)

This distinction reveals who is aggressive and in which direction —
information that candlesticks and classic indicators do not capture.

---

## 2. Delta and Cumulative Volume Delta (CVD)

### 2.1 Per-Candle Delta

A candle's **Delta** is the difference between aggressive buy and sell
volume within the interval:

```
Delta = Sum(buy_volume_i) - Sum(sell_volume_i)   for every trade i in the candle
```

where:
- `buy_volume_i = quantity_i` if `is_buyer_maker = False` (BUY aggression)
- `sell_volume_i = quantity_i` if `is_buyer_maker = True`  (SELL aggression)

**Interpretation**:
- Delta > 0 → more volume bought aggressively → bullish pressure
- Delta < 0 → more volume sold aggressively → bearish pressure
- Delta = 0 → perfect balance (rare)

**Percentage delta** (normalized by total volume):
```
Delta% = Delta / (buy_volume + sell_volume) * 100
Delta% in [-100%, +100%]
```

Delta% > 60% → strong buy dominance; Delta% < -60% → strong sell dominance.

### 2.2 Cumulative Volume Delta (CVD)

The **CVD** accumulates Delta over time, producing a curve that shows the
net orderflow trend:

```
CVD(t) = Sum_{i=0}^{t} Delta_i
```

CVD is computed on multiple timeframes (1m, 5m, 15m) via sliding time
windows:

```python
# Pseudo-code (implementation in orderflow.py)
class Accumulator:
    def __init__(self, window_sec: int):
        self.window_sec = window_sec
        self.buffer = deque()  # (timestamp_ms, delta)
        self.cvd = 0.0

    def update(self, timestamp_ms: int, buy_vol: float, sell_vol: float):
        delta = buy_vol - sell_vol
        self.buffer.append((timestamp_ms, delta))
        self.cvd += delta
        # Drop events outside the window
        cutoff = timestamp_ms - self.window_sec * 1000
        while self.buffer and self.buffer[0][0] < cutoff:
            _, old_delta = self.buffer.popleft()
            self.cvd -= old_delta
```

**Implemented timeframes**:
- `cvd_1m` : CVD over the last minute (very short-term momentum signal)
- `cvd_5m` : CVD over the last 5 minutes (trend confirmation)
- `cvd_15m`: CVD over the last 15 minutes (structural context)

**CVD/Price divergence** — an important signal:
- Price rises, CVD falls → the rally is not supported by flow → possible reversal
- Price falls, CVD rises → the decline is not supported by flow → possible bounce

---

## 3. Volume Weighted Average Price (VWAP) and VWAP Z-Score

### 3.1 Intraday VWAP

The VWAP is the volume-weighted average price of the current session:

```
VWAP = Sum(price_i * volume_i) / Sum(volume_i)
```

where i is every single trade. Implemented with running sums:

```
VWAP(t) = (Sum_{i=0}^{t} P_i * Q_i) / (Sum_{i=0}^{t} Q_i)
         = (PQ_cumulative) / (V_cumulative)
```

The VWAP is the **institutional equilibrium price**: large players
(funds, prop desks) often use the VWAP as the benchmark for their orders
(VWAP execution algorithms). Price >> VWAP → the market bought expensive
relative to the average.

### 3.2 Micro-VWAP (5-minute rolling)

The **Micro-VWAP** is a VWAP over a recent moving window, more sensitive
to short-term variations:

```python
micro_vwap_window = deque(maxlen=300)  # last 300 trades (~5 minutes on BTCUSDT)
for trade in micro_vwap_window:
    pq_sum += trade.price * trade.quantity
    vol_sum += trade.quantity
micro_vwap = pq_sum / vol_sum
```

### 3.3 VWAP Z-Score

The **VWAP Z-Score** measures how far the current price is from the VWAP
in standard-deviation terms:

```
vwap_z = (P_current - VWAP) / std(P_i - VWAP_i  over the last N trades)
```

Typical values for BTCUSDT futures:
- |vwap_z| < 1.0 → price near the VWAP (neutral zone)
- 1.0 < |vwap_z| < 2.0 → moderate extension
- |vwap_z| > 2.0 → significant extension → potential mean reversion

---

## 4. Aggression Ratio and Absorption

### 4.1 Aggression Ratio

```
Aggression Ratio = buy_volume_N / (buy_volume_N + sell_volume_N)
```

computed over the last N seconds (default 300s = 5 minutes).

- AR > 0.6 → aggressive buy dominance → sustained bullish pressure
- AR < 0.4 → aggressive sell dominance → sustained bearish pressure
- AR ~0.5 → balance → market waiting

Difference vs OBI:
- OBI measures intention (limit orders in the book)
- AR measures action (orders executed aggressively)

They often diverge: high OBI + low AR → a liquidity wall on the bid is
absorbing sells. An accumulation scenario.

### 4.2 Absorption (Reversal Signal)

**Absorption** happens when one side of the book absorbs large amounts of
aggressive orders without the price moving proportionally. It signals
that sized players (often institutional) are buying/selling against the
retail flow.

**Detection algorithm**:
```python
def _detect_absorption(self, candle) -> bool:
    """
    Buy absorption: strongly negative delta (heavy selling) but close >= open
    (the price did not fall)
    -> buyers absorbed all the selling without giving ground
    """
    delta_pct = candle.delta / candle.volume if candle.volume > 0 else 0
    price_change = (candle.close - candle.open) / candle.open

    # Case 1: heavy sell flow but price holds (bull absorption)
    if delta_pct < -0.3 and price_change >= -0.001:  # -30% delta, max -0.1% price
        return True

    # Case 2: heavy buy flow but price does not rise (bear absorption — top)
    if delta_pct > 0.3 and price_change <= 0.001:
        return True

    return False
```

Absorption is one of the most reliable microstructure signals because it
reveals an "invisible wall" in the book that does not appear in the L2
data but shows up in the flow.

---

## 5. Kyle's Lambda — Price Impact

### 5.1 Theory

**Kyle's Lambda** (from Albert Kyle, 1985, "Continuous Auctions and
Insider Trading", *Econometrica*) measures the **price impact per unit of
net volume**:

```
Delta_P = lambda * Q_net + epsilon
```

where:
- `Delta_P` = price change
- `Q_net` = net volume (buy - sell) in the period
- `lambda` = price impact coefficient (Kyle's Lambda)
- `epsilon` = random component

High lambda → illiquid market → every additional unit of volume moves the
price a lot. Low lambda → liquid market → large volume needed to move the
price.

### 5.2 OLS Estimation on a Rolling Window

We estimate Lambda via OLS (Ordinary Least Squares) over a window of N
candles:

```
Lambda_hat = Cov(Delta_P, Q_net) / Var(Q_net)
```

which is the regression coefficient of Delta_P on Q_net (regression
through the origin).

**Implementation** (`src/engine/orderflow.py`):
```python
def _compute_kyle_lambda(self, symbol: str) -> float:
    """
    Estimates Kyle's Lambda on a rolling window of 1m candles.
    Lambda = Cov(dP, Q_net) / Var(Q_net)
    """
    history = self._kyle_buffer.get(symbol, deque(maxlen=100))
    if len(history) < 20:
        return 0.0

    dp   = np.array([h["price_change"] for h in history])   # Delta P
    qnet = np.array([h["net_volume"] for h in history])      # Q_net = buy_vol - sell_vol

    var_q = np.var(qnet)
    if var_q < 1e-10:  # degenerate: no volume variation
        return 0.0

    cov_dpq = np.cov(dp, qnet)[0, 1]
    return cov_dpq / var_q  # OLS estimate
```

**Buffer updated** on every finalized candle:
```python
self._kyle_buffer[symbol].append({
    "price_change": close - open,       # Delta P in USD
    "net_volume":   buy_vol - sell_vol  # Q_net in BTC
})
```

### 5.3 Operational Interpretation

| Kyle's Lambda | Interpretation | Action |
|---------------|----------------|--------|
| < 0.001 | Excellent liquidity, low impact | Normal position size |
| 0.001 - 0.005 | Normal liquidity | Normal position size |
| 0.005 - 0.01 | Reduced liquidity | Reduce size |
| > 0.01 | Illiquid market | Avoid market orders, use limits |

Negative lambda: rare, indicates price mean-reverting relative to flow
(typical of very liquid markets with aggressive market makers).

**Inverse formula** — expected slippage for an order of quantity Q:
```
Expected_slippage = Lambda * Q  (in USD per BTC)
```

Example: Lambda = 0.003, 5 BTC order → expected slippage = 0.003 * 5 =
0.015 USD/BTC = $0.015 on a $64500 price ≈ 0.023 bps (negligible for
BTCUSDT perpetual).

---

## 6. Volume Z-Score

The **Volume Z-Score** measures how anomalous a candle's volume is
relative to recent history:

```
volume_z = (V_current - mean(V_{t-N:t})) / std(V_{t-N:t})
```

computed over a rolling window of N candles (default 50).

Uses:
- `volume_z > 2` → volume spike → potentially genuine breakout
- `volume_z < -1` → low volume → unreliable signals (reduced liquidity)

---

## 7. MarketSnapshot — Unified Output

The `OrderflowEngine` produces a `MarketSnapshot` on request, aggregating
every computed metric:

```python
@dataclass
class MarketSnapshot:
    symbol: str
    timestamp_ms: int
    price: float                   # last price

    # Multi-timeframe CVD
    cvd_1m: float                  # CVD last minute
    cvd_5m: float                  # CVD last 5 minutes
    cvd_15m: float                 # CVD last 15 minutes

    # Order book
    book_imbalance: float          # OBI top 10 [0,1]

    # Flow metrics
    aggression_ratio: float        # AR 5 minutes [0,1]
    volume_zscore: float           # volume Z-score (rolling 50 candles)
    vwap_z: float                  # VWAP Z-score
    micro_vwap: float              # 5-minute Micro-VWAP

    # Open Interest
    oi_change_pct: float           # OI% change vs previous snapshot

    # Microstructure
    kyle_lambda: float             # price impact coefficient
    is_absorption: bool            # absorption signal
    is_liq_vacuum: bool            # liquidity vacuum in the book
    is_volume_spike: bool          # volume_zscore > 2.5

    # Aggregated liquidations, 10 minutes
    liq_buy_volume_10m: float      # short-liquidation volume (short squeeze)
    liq_sell_volume_10m: float     # long-liquidation volume (long dump)
```

The snapshot is the interface contract between the data layer and the
strategies. Each strategy reads only the fields it needs.

---

## 8. Computational Complexity

| Operation | Complexity | Notes |
|-----------|------------|-------|
| `update_from_trade()` | O(1) | Append on deque only |
| `update_from_book()` | O(1) | Snapshot copy |
| `_finalize_candle()` | O(K) | K = candle history size (50) for Z-score |
| `_compute_kyle_lambda()` | O(N) | N = buffer size (100), run per candle |
| `get_snapshot()` | O(1) | Returns last cached snapshot |
| `get_candle_history()` | O(N) | N = number of requested candles |
| `flush_snapshot()` | O(K) | Forces finalization of the incomplete candle |

The bottleneck is not the math (all O(N) with small N) but JSON parsing
from the WebSocket. For extreme volumes (>10k msg/s) msgpack or protocol
buffers could be used.
