# Data Layer e Microstruttura del Mercato

## 1. Teoria della Microstruttura dei Mercati Finanziari

La **microstruttura** studia il processo di formazione del prezzo a livello di singole transazioni. Nei mercati crypto, questo e particolarmente rilevante perche:
- Il book e pubblico e aggiornato in real-time (nessuna dark pool)
- Le liquidazioni forzate creano cascate di prezzo prevedibili
- Il volume e classificabile (buy/sell) tramite il campo `buyer_is_maker`

### 1.1 Il Limit Order Book (LOB)

Il LOB e una struttura dati che raccoglie tutti gli ordini limite pendenti:

```
         ASKS (venditori)
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
         BIDS (compratori)
```

**Mid price**: P_mid = (64510 + 64490) / 2 = 64500 USD

**Spread in basis points**: spread_bps = (64510 - 64490) / 64500 * 10000 = 3.1 bps

**Microprice** (volume-weighted mid, piu accurato del mid price semplice):
```
P_micro = (bid_qty * ask_price + ask_qty * bid_price) / (bid_qty + ask_qty)
P_micro = (1.750 * 64510 + 2.450 * 64490) / (1.750 + 2.450)
P_micro = (112892.5 + 158000.5) / 4.200 = 64498.3 USD
```
Il microprice indica pressione lato ask (2.45 > 1.75) → propende verso 64490.

### 1.2 Classificazione degli Ordini: Maker vs Taker

| Tipo | Descrizione | Effetto sul prezzo |
|------|-------------|-------------------|
| **Market order (taker)** | Esegue immediatamente al miglior prezzo disponibile | Consuma liquidita, muove il prezzo |
| **Limit order (maker)** | Rimane in book fino all'esecuzione | Aggiunge liquidita, non muove il prezzo |

**buyer_is_maker** nel campo aggTrade di Binance:
- `buyer_is_maker = False` → il compratore ha usato un market order → **BUY aggression**
- `buyer_is_maker = True` → il venditore ha usato un market order → **SELL aggression**

Questo campo e la chiave per distinguere chi e "aggressivo" (chi sta spingendo il prezzo).

### 1.3 Order Book Imbalance (OBI)

```
           Sum(qty_i) per i in top N bids
OBI = ─────────────────────────────────────────────
       Sum(qty_i) bids + Sum(qty_i) asks  (top N)
```

Valori:
- OBI = 0.5 → equilibrio perfetto
- OBI > 0.6 → pressione buy dominante → probabile rialzo a breve
- OBI < 0.4 → pressione sell dominante → probabile ribasso a breve
- OBI = 1.0 → nessuna offerta (impossibile → libro vuoto lato ask)

**Predittivita**: studi empirici mostrano che OBI ha potere predittivo sui movimenti di prezzo nei 100-500ms successivi (correlazione ~0.3-0.5 per L1 imbalance).

Implementazione (`src/data/orderbook_engine.py`):
```python
bid_vol_10 = sum(qty for price, qty in sorted_bids[:10])
ask_vol_10 = sum(qty for price, qty in sorted_asks[:10])
book_imbalance = bid_vol_10 / (bid_vol_10 + ask_vol_10) if (bid_vol_10 + ask_vol_10) > 0 else 0.5
```

### 1.4 Adverse Selection e Market Making

Il **problema dell'adverse selection**: i market maker (che postano ordini limite) rischiano di essere sistematicamente "selezionati" da trader informati.

Esempio:
- MM posta bid a 64490 (vuole comprare)
- Un trader informato vende a 64490 (sa che il prezzo scende)
- Il prezzo scende → MM ha comprato caro

Il **bid-ask spread** compensa questo rischio:
```
Spread = 2 * (adverse_selection_component + inventory_component + order_processing_cost)
```

In crypto futures, lo spread su BTCUSDT perpetual e tipicamente 1-3 bps → mercato molto liquido.

### 1.5 Liquidazioni Forzate (forceOrder)

Quando un trader tiene una posizione futures con margine insufficiente, Binance la chiude forzatamente:

- **Long liquidation** → Binance vende (aggression SELL) → pressione short → prezzo scende
- **Short liquidation** → Binance compra (aggression BUY) → pressione long → prezzo sale

Le liquidazioni a cascata sono la causa dei movimenti piu violenti in crypto:
1. Prezzo scende → posizioni long poco marginate → liquidate
2. Liquidazioni vendono → prezzo scende ancora → altre posizioni liquidate
3. Effetto a valanga fino a esaurimento dei long fragili

La strategia **LiquidationSqueeze** (`src/strategies/liq_squeeze.py`) sfrutta questo fenomeno.

---

## 2. Binance Futures WebSocket Streams

### 2.1 URL di Connessione

```
wss://fstream.binance.com/stream?streams=btcusdt@aggTrade/btcusdt@depth@100ms/btcusdt@forceOrder
```

Formato combined stream:
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

### 2.2 Stream aggTrade

Il campo chiave e `m` (buyer_is_maker):

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

**Throughput**: BTCUSDT genera ~500-2000 aggTrade/minuto nelle ore di punta. Il ring buffer e dimensionato a 50.000 trade (~ 25-100 minuti di storia).

### 2.3 Stream depth@100ms

Aggiornamenti incrementali del book ogni 100ms. Il protocollo Binance richiede:

1. Connettiti al WebSocket depth stream
2. Richiedi snapshot REST: `GET /fapi/v1/depth?symbol=BTCUSDT&limit=500`
3. Applica snapshot: `first_update_id` dello snapshot = U
4. Per ogni update WS: se `u < U` → scarta; se `U <= U_snapshot <= u` → applica
5. Da qui in poi: ogni update deve avere `U_received == u_prev + 1`

Il nostro OrderBookEngine implementa il gap detection:
```python
if update.first_update_id != self._expected_next_id[symbol]:
    logger.warning(f"[OrderBook] {symbol} sequence gap: expected {expected}, got {got} — resetting book")
    self._reset_book(symbol)
```

Nella pratica (dry run su BTCUSDT), si vedono molti gap: il WS combined stream perde alcuni update a causa della latenza di rete. La soluzione corretta e richiedere il snapshot REST e reinizializzare. In fase alpha, il book si rinizia automaticamente e opera su dati parzialmente stabili (accettabile per feature di imbalance ma non per market making puro).

**Formato update**:
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

### 2.4 Stream forceOrder (Liquidazioni)

```json
{
  "stream": "btcusdt@forceOrder",
  "data": {
    "e": "forceOrder",
    "E": 1704067205000,
    "o": {
      "s": "BTCUSDT",
      "S": "SELL",          // SELL = liquidazione long; BUY = liquidazione short
      "o": "LIMIT",
      "f": "IOC",
      "q": "0.100",         // quantita liquidata
      "p": "64200.00",      // prezzo limite
      "ap": "64215.50",     // prezzo medio eseguito
      "X": "FILLED",
      "l": "0.100",
      "z": "0.100",
      "T": 1704067204999
    }
  }
}
```

Utilizziamo `ap` (average_price) per avere il prezzo reale di esecuzione.

### 2.5 Open Interest (REST Polling)

```
GET https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT
Response: {"symbol": "BTCUSDT", "openInterest": "87234.560", "time": 1704067200000}

GET https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT
Response: {"symbol": "BTCUSDT", "markPrice": "64500.10", ...}
```

OI in USD = openInterest_contracts * markPrice

**Interpretazione economica**:
- OI crescente + prezzo crescente = denaro nuovo entra long → trend forte
- OI decrescente + prezzo crescente = short squeeze (chiusura corti) → trend debole
- OI crescente + prezzo decrescente = denaro nuovo entra short → trend forte
- OI decrescente + prezzo decrescente = liquidazione long → trend debole

---

## 3. OrderBookEngine: Ricostruzione L2

### 3.1 Struttura Dati

```python
class OrderBookEngine:
    _bids: Dict[str, Dict[float, float]]  # {symbol: {price: qty}}
    _asks: Dict[str, Dict[float, float]]
    _last_update_id: Dict[str, int]
    _expected_next_id: Dict[str, int]
```

Scelta: `dict` Python con key float per O(1) lookup e O(N log N) per sorted snapshot.
Alternativa piu efficiente: `sortedcontainers.SortedDict` per O(log N) insertion/deletion, ma dipendenza aggiuntiva.

### 3.2 Algoritmo di Update

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

Snapshot calcolato on-demand da `get_snapshot(symbol)`:

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
    is_liq_vacuum: bool       # gap >5x average tra livelli consecutivi
```

**Liquidity Vacuum detection**:
```python
gaps = [asks[i+1] - asks[i] for i in range(min(19, len(asks)-1))]
if gaps:
    avg_gap = np.mean(gaps)
    max_gap = max(gaps)
    is_liq_vacuum = max_gap > 5 * avg_gap  # gap anomalo
```

Un vacuum sul lato ask (zona vuota di venditori) → prezzo puo muoversi rapidamente verso l'alto se arriva buy pressure.

---

## 4. Data Quality Layer

### 4.1 Problemi nei Dati Tick Crypto

| Problema | Causa | Frequenza |
|----------|-------|-----------|
| Gap (dati mancanti) | Disconnect WS, manutenzione exchange | ~1-5/giorno |
| Outlier di volume | News improvvise, grandi ordini | Raro |
| Outlier di prezzo | Flash crash, glitch exchange | Rarissimo |
| Dati stale | Book non aggiornato, stessa price ripetuta | Frequente |
| Candle corrotte | high < close, low > open | Bug dati storici |

### 4.2 Algoritmo di Validazione Candle

```python
def validate_candle(candle: dict) -> Tuple[bool, List[str]]:
    issues = []
    o, h, l, c = candle["open"], candle["high"], candle["low"], candle["close"]

    # Integrity: high deve essere il massimo
    if h < max(o, c):
        issues.append(f"high={h} < max(open={o}, close={c})")
    if l > min(o, c):
        issues.append(f"low={l} > min(open={o}, close={c})")

    # Price outlier: log-return > 5% in 1 minuto = anomalia
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
    Riempie gap di candle con carry-forward del close.
    Gap > max_gap: non riempire (troppo rischio dati artificiali).
    """
    result = []
    for i in range(1, len(candles)):
        delta_ts = (candles[i]["timestamp_ms"] - candles[i-1]["timestamp_ms"]) // 60000
        if 1 < delta_ts <= max_gap:
            # Inserisci candle sintetiche
            for j in range(1, delta_ts):
                result.append({
                    "timestamp_ms": candles[i-1]["timestamp_ms"] + j * 60000,
                    "open": candles[i-1]["close"],
                    "high": candles[i-1]["close"],
                    "low":  candles[i-1]["close"],
                    "close": candles[i-1]["close"],
                    "volume": 0.0,  # nessuna attivita reale
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

# Outlier: Z > 5 sigma (molto conservativo per non eliminare news genuine)
for i, z in enumerate(z_scores):
    if z > 5.0:
        candles[i]["volume"] = mean_vol + 5.0 * std_vol  # clip
        candles[i]["volume_outlier"] = True
```

### 4.5 Build Candle da Trade Tick

```python
def build_candles_from_trades(trades: List[AggTrade], interval_sec: int = 60) -> List[dict]:
    """
    Aggrega tick trade in candle OHLCV con buy/sell volume split.
    Utile per costruire candle da dati raw senza affidarsi a endpoint REST.
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

La separazione `buy_volume` / `sell_volume` e fondamentale per calcolare il **Delta** (vedere doc 03).
