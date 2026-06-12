# Data Layer and Market Microstructure

## 1. Financial Market Microstructure Theory

**Microstructure** studies the price-formation process at the level of
individual transactions. In crypto markets this is especially relevant
because:
- The book is public and updated in real time (no dark pools)
- Forced liquidations create predictable price cascades
- Volume can be classified (buy/sell) via the `buyer_is_maker` field

### 1.1 The Limit Order Book (LOB)

The LOB is a data structure collecting all pending limit orders:

```
         ASKS (sellers)
  Price  |  Quantity
  64510  |  2.450 BTC   <- best ask
  64520  |  1.200 BTC
  64530  |  0.800 BTC
  64550  |  3.100 BTC
  -------+------------- spread = 64510 - 64490 = 20 USD (3.1 bps)
  64490  |  1.750 BTC   <- best bid
  64480  |  0.500 BTC
  64460  |  4.200 BTC
  64440  |  2.900 BTC
         BIDS (buyers)
```

**Mid price**: P_mid = (64510 + 64490) / 2 = 64500 USD

**Spread in basis points**: spread_bps = (64510 - 64490) / 64500 * 10000 = 3.1 bps

**Microprice** (volume-weighted mid, more accurate than the simple mid):
```
P_micro = (bid_qty * ask_price + ask_qty * bid_price) / (bid_qty + ask_qty)
P_micro = (1.750 * 64510 + 2.450 * 64490) / (1.750 + 2.450)
P_micro = (112892.5 + 158000.5) / 4.200 = 64498.3 USD
```
The microprice signals ask-side pressure (2.45 > 1.75) → it leans towards 64490.

### 1.2 Order Classification: Maker vs Taker

| Type | Description | Price impact |
|------|-------------|--------------|
| **Market order (taker)** | Executes immediately at the best available price | Consumes liquidity, moves the price |
| **Limit order (maker)** | Sits in the book until executed | Adds liquidity, does not move the price |

**buyer_is_maker** in Binance's aggTrade field:
- `buyer_is_maker = False` → the buyer used a market order → **BUY aggression**
- `buyer_is_maker = True` → the seller used a market order → **SELL aggression**

This field is the key to telling who is "aggressive" (who is pushing the price).

### 1.3 Order Book Imbalance (OBI)

```
           Sum(qty_i) for i in top N bids
OBI = ─────────────────────────────────────────────
       Sum(qty_i) bids + Sum(qty_i) asks  (top N)
```

Values:
- OBI = 0.5 → perfect balance
- OBI > 0.6 → dominant buy pressure → likely short-term upside
- OBI < 0.4 → dominant sell pressure → likely short-term downside
- OBI = 1.0 → no offers (impossible → empty ask side)

**Predictive power**: empirical studies show OBI has predictive power on
price moves over the following 100-500ms (~0.3-0.5 correlation for L1
imbalance).

Implementation (`src/data/orderbook_engine.py`):
```python
bid_vol_10 = sum(qty for price, qty in sorted_bids[:10])
ask_vol_10 = sum(qty for price, qty in sorted_asks[:10])
book_imbalance = bid_vol_10 / (bid_vol_10 + ask_vol_10) if (bid_vol_10 + ask_vol_10) > 0 else 0.5
```

### 1.4 Adverse Selection and Market Making

The **adverse selection problem**: market makers (who post limit orders)
risk being systematically "picked off" by informed traders.

Example:
- MM posts a bid at 64490 (wants to buy)
- An informed trader sells at 64490 (knows the price is going down)
- The price drops → the MM bought expensive

The **bid-ask spread** compensates for this risk:
```
Spread = 2 * (adverse_selection_component + inventory_component + order_processing_cost)
```

In crypto futures, the BTCUSDT perpetual spread is typically 1-3 bps → a
very liquid market.

### 1.5 Forced Liquidations (forceOrder)

When a trader holds a futures position with insufficient margin, Binance
force-closes it:

- **Long liquidation** → Binance sells (SELL aggression) → short pressure → price falls
- **Short liquidation** → Binance buys (BUY aggression) → long pressure → price rises

Cascading liquidations cause the most violent moves in crypto:
1. Price falls → under-margined long positions → liquidated
2. Liquidations sell → price falls further → more positions liquidated
3. Avalanche effect until the fragile longs are exhausted

---

## 2. Binance Futures WebSocket Streams

### 2.1 Connection URL

```
wss://fstream.binance.com/stream?streams=btcusdt@aggTrade/btcusdt@depth@100ms/btcusdt@forceOrder
```

Combined stream format:
```json
{
  "stream": "btcusdt@aggTrade",
  "data": {
    "e": "aggTrade",
    "E": 1704067200000,  // event time ms
    "s": "BTCUSDT",      // symbol
    "a": 12345678,        // aggTrade ID
    "p": "64500.10",      // price
    "q": "0.015",         // quantity BTC
    "T": 1704067199998,   // trade time ms
    "m": false,           // buyer_is_maker
    "M": true             // is best price match (ignore)
  }
}
```

### 2.2 aggTrade Stream

The key field is `m` (buyer_is_maker):

```python
@dataclass
class AggTrade:
    symbol: str
    trade_id: int
    price: float
    quantity: float
    timestamp_ms: int
    is_buyer_maker: bool

    @property
    def buy_volume(self) -> float:
        return self.quantity if not self.is_buyer_maker else 0.0

    @property
    def sell_volume(self) -> float:
        return self.quantity if self.is_buyer_maker else 0.0
```

**Throughput**: BTCUSDT generates ~500-2000 aggTrades/minute at peak
hours. The ring buffer is sized at 50,000 trades (~25-100 minutes of
history).

### 2.3 depth@100ms Stream

Incremental book updates every 100ms. The Binance protocol requires:

1. Connect to the depth WebSocket stream
2. Request the REST snapshot: `GET /fapi/v1/depth?symbol=BTCUSDT&limit=500`
3. Apply the snapshot: snapshot `first_update_id` = U
4. For each WS update: if `u < U` → discard; if `U <= U_snapshot <= u` → apply
5. From then on: every update must have `U_received == u_prev + 1`

Our OrderBookEngine implements gap detection:
```python
if update.first_update_id != self._expected_next_id[symbol]:
    logger.warning(f"[OrderBook] {symbol} sequence gap: expected {expected}, got {got} — resetting book")
    self._reset_book(symbol)
```

In practice (dry runs on BTCUSDT) gaps are frequent: the combined WS
stream drops some updates due to network latency. The correct remedy is
to request the REST snapshot and re-initialize. The book resets itself
automatically and operates on partially stable data (acceptable for
imbalance features, not for pure market making).

**Update format**:
```json
{
  "stream": "btcusdt@depth@100ms",
  "data": {
    "e": "depthUpdate",
    "E": 1704067200100,
    "s": "BTCUSDT",
    "U": 10006975508985,  // first update ID in event
    "u": 10006975509100,  // last update ID in event
    "b": [["64490.00", "1.750"], ["64480.00", "0.000"]],  // bids: qty=0 -> delete
    "a": [["64510.00", "2.450"], ["64520.00", "1.200"]]   // asks
  }
}
```

### 2.4 forceOrder Stream (Liquidations)

```json
{
  "stream": "btcusdt@forceOrder",
  "data": {
    "e": "forceOrder",
    "E": 1704067205000,
    "o": {
      "s": "BTCUSDT",
      "S": "SELL",          // SELL = long liquidation; BUY = short liquidation
      "o": "LIMIT",
      "f": "IOC",
      "q": "0.100",         // liquidated quantity
      "p": "64200.00",      // limit price
      "ap": "64215.50",     // average executed price
      "X": "FILLED",
      "l": "0.100",
      "z": "0.100",
      "T": 1704067204999
    }
  }
}
```

We use `ap` (average_price) to get the real execution price.

### 2.5 Open Interest (REST Polling)

```
GET https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT
Response: {"symbol": "BTCUSDT", "openInterest": "87234.560", "time": 1704067200000}

GET https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT
Response: {"symbol": "BTCUSDT", "markPrice": "64500.10", ...}
```

OI in USD = openInterest_contracts * markPrice

**Economic interpretation**:
- Rising OI + rising price = new money entering long → strong trend
- Falling OI + rising price = short squeeze (shorts closing) → weak trend
- Rising OI + falling price = new money entering short → strong trend
- Falling OI + falling price = long liquidation → weak trend

---

## 3. OrderBookEngine: L2 Reconstruction

### 3.1 Data Structure

```python
class OrderBookEngine:
    _bids: Dict[str, Dict[float, float]]  # {symbol: {price: qty}}
    _asks: Dict[str, Dict[float, float]]
    _last_update_id: Dict[str, int]
    _expected_next_id: Dict[str, int]
```

Choice: Python `dict` with float keys for O(1) lookups and O(N log N)
sorted snapshots. A more efficient alternative is
`sortedcontainers.SortedDict` for O(log N) insertion/deletion, at the
cost of an extra dependency.

### 3.2 Update Algorithm

```python
def apply_update(self, update: DepthUpdate):
    symbol = update.symbol
    # Gap detection
    if symbol in self._expected_next_id:
        if update.first_update_id != self._expected_next_id[symbol]:
            self._reset_book(symbol)
            return
    # Apply bids
    for price, qty in update.bids:
        if qty == 0:
            self._bids[symbol].pop(price, None)  # delete level
        else:
            self._bids[symbol][price] = qty
    # Apply asks
    for price, qty in update.asks:
        if qty == 0:
            self._asks[symbol].pop(price, None)
        else:
            self._asks[symbol][price] = qty
    # Update sequence tracker
    self._expected_next_id[symbol] = update.final_update_id + 1
```

### 3.3 OrderBookSnapshot

Snapshot computed on demand by `get_snapshot(symbol)`:

```python
@dataclass
class OrderBookSnapshot:
    symbol: str
    timestamp_ms: int
    best_bid: float
    best_ask: float
    mid_price: float
    spread_bps: float
    bid_volume_10: float      # sum top 10 bids (BTC)
    ask_volume_10: float      # sum top 10 asks (BTC)
    bid_volume_20: float
    ask_volume_20: float
    book_imbalance: float     # OBI top 10
    book_imbalance_20: float  # OBI top 20
    is_liq_vacuum: bool       # gap >5x average between consecutive levels
```

**Liquidity vacuum detection**:
```python
gaps = [asks[i+1] - asks[i] for i in range(min(19, len(asks)-1))]
if gaps:
    avg_gap = np.mean(gaps)
    max_gap = max(gaps)
    is_liq_vacuum = max_gap > 5 * avg_gap  # anomalous gap
```

A vacuum on the ask side (a zone empty of sellers) → the price can move
up quickly if buy pressure arrives.

---

## 4. Data Quality Layer

### 4.1 Issues in Crypto Tick Data

| Issue | Cause | Frequency |
|-------|-------|-----------|
| Gaps (missing data) | WS disconnects, exchange maintenance | ~1-5/day |
| Volume outliers | Sudden news, large orders | Rare |
| Price outliers | Flash crashes, exchange glitches | Very rare |
| Stale data | Book not updating, repeated identical price | Frequent |
| Corrupted candles | high < close, low > open | Historical data bugs |

### 4.2 Candle Validation Algorithm

```python
def validate_candle(candle: dict) -> Tuple[bool, List[str]]:
    issues = []
    o, h, l, c = candle["open"], candle["high"], candle["low"], candle["close"]

    # Integrity: high must be the maximum
    if h < max(o, c):
        issues.append(f"high={h} < max(open={o}, close={c})")
    if l > min(o, c):
        issues.append(f"low={l} > min(open={o}, close={c})")

    # Price outlier: log-return > 5% in 1 minute = anomaly
    if "prev_close" in candle:
        log_ret = abs(math.log(c / candle["prev_close"]))
        if log_ret > 0.05:
            issues.append(f"log_return={log_ret:.4f} > 5% threshold")

    return len(issues) == 0, issues
```

### 4.3 Gap Fill

```python
def fill_gaps(candles: List[dict], max_gap: int = 5) -> List[dict]:
    """
    Fills candle gaps with carry-forward of the close.
    Gaps > max_gap: do not fill (too much risk of artificial data).
    """
    result = []
    for i in range(1, len(candles)):
        delta_ts = (candles[i]["timestamp_ms"] - candles[i-1]["timestamp_ms"]) // 60000
        if 1 < delta_ts <= max_gap:
            # Insert synthetic candles
            for j in range(1, delta_ts):
                result.append({
                    "timestamp_ms": candles[i-1]["timestamp_ms"] + j * 60000,
                    "open": candles[i-1]["close"],
                    "high": candles[i-1]["close"],
                    "low":  candles[i-1]["close"],
                    "close": candles[i-1]["close"],
                    "volume": 0.0,  # no real activity
                    "synthetic": True
                })
        result.append(candles[i])
    return result
```

### 4.4 Volume Outlier Removal

```python
volumes = np.array([c["volume"] for c in candles])
mean_vol = np.mean(volumes)
std_vol  = np.std(volumes)
z_scores = (volumes - mean_vol) / std_vol

# Outlier: Z > 5 sigma (very conservative, avoids removing genuine news)
for i, z in enumerate(z_scores):
    if z > 5.0:
        candles[i]["volume"] = mean_vol + 5.0 * std_vol  # clip
        candles[i]["volume_outlier"] = True
```

### 4.5 Building Candles from Trade Ticks

```python
def build_candles_from_trades(trades: List[AggTrade], interval_sec: int = 60) -> List[dict]:
    """
    Aggregates trade ticks into OHLCV candles with buy/sell volume split.
    Useful to build candles from raw data without relying on REST endpoints.
    """
    buckets = defaultdict(list)
    for trade in trades:
        bucket_ts = (trade.timestamp_ms // (interval_sec * 1000)) * (interval_sec * 1000)
        buckets[bucket_ts].append(trade)

    candles = []
    for ts in sorted(buckets.keys()):
        bucket = buckets[ts]
        prices = [t.price for t in bucket]
        candles.append({
            "timestamp_ms": ts,
            "open":       bucket[0].price,
            "high":       max(prices),
            "low":        min(prices),
            "close":      bucket[-1].price,
            "volume":     sum(t.quantity for t in bucket),
            "buy_volume": sum(t.buy_volume for t in bucket),
            "sell_volume": sum(t.sell_volume for t in bucket),
            "trade_count": len(bucket),
        })
    return candles
```

The `buy_volume` / `sell_volume` split is fundamental to compute the
**Delta** (see doc 03).
