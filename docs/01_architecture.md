# Architettura di Sistema — coinmaker-quant

## 1. Filosofia di Design

Il sistema è costruito attorno a tre principi:

1. **Separazione dei layer**: dati → feature → segnale → esecuzione sono pipeline distinte, testabili indipendentemente
2. **Invarianza dell'interfaccia strategia**: `scan() / execute_entry() / manage_positions()` non cambiano mai; le strategie sono plugin intercambiabili
3. **Graceful degradation**: ogni modulo opzionale (Telegram, Streamlit, DuckDB) ha un fallback se non installato

---

## 2. Diagramma Architettura Completa

```
+------------------+     WebSocket wss://fstream.binance.com
|  Binance Futures |---> aggTrade  (tick-by-tick, buyer_is_maker)
|                  |---> depth@100ms  (L2 incrementale)
|                  |---> forceOrder   (liquidazioni forzate)
|                  |--REST OI poll (ogni 30s)
+------------------+
         |
         v
+---------------------+     asyncio Queue (maxsize=10000 trades)
| BinanceDataIngestion|---> trade_queue
|  _ws_listener()     |---> depth_queue
|  _oi_poller()       |---> liquidation_queue
|  ring buffers       |     (deque per symbol, maxlen=50000)
+---------------------+
         |
         | asyncio task: _data_route_loop() [5ms sleep]
         v
+------------------+        +---------------------+
| OrderBookEngine  |        | OrderflowEngine     |
| apply_update()   |------> | update_from_book()  |
| L2 bids/asks     |        | update_from_trade() |
| OrderBookSnapshot|        | MarketSnapshot      |
+------------------+        +---------------------+
                                      |
                    asyncio task: _regime_loop() [60s]
                                      |
                                      v
                            +---------------------+
                            | RegimeDetector      |
                            | detect(candles, ...) |
                            | MarketRegime        |
                            | TREND/RANGE/COMP    |
                            +---------------------+
                                      |
                    asyncio task: _scan_loop() [config min]
                                      |
                                      v
                            +---------------------+
                            | ScoringEngine       |
                            | should_trade(name,  |
                            |   regime) -> bool   |
                            +---------------------+
                                      |
                                      v
                    +-------------------------------+
                    | Strategies (plugin)           |
                    | VolumeBreakout                |
                    | MeanReversion                 |
                    | LiquidationSqueeze            |
                    | ImbalanceScalp                |
                    | SmartMoney / WM / Brings      |
                    | strategy.scan() -> [signal]   |
                    +-------------------------------+
                                      |
                                      v
                            +---------------------+
                            | RiskManager         |
                            | calculate_dynamic_  |
                            | size() -> quantity  |
                            | can_open_position() |
                            +---------------------+
                                      |
                                      v
                            +---------------------+     REST https://www.deribit.com
                            | OrderManager        |---> /private/buy
                            | execute_generic_    |---> /private/sell
                            | trade()             |---> /private/cancel
                            | OrderRegistry       |
                            | {trade_id->{sl,tp}} |
                            +---------------------+
                                      |
                            asyncio task: _management_loop() [30s]
                                      |
                                      v
                            +---------------------+
                            | PositionMonitor     |
                            | get_open_positions()|
                            | check_orphan_orders |
                            +---------------------+

Background threads:
  FailureHandler (daemon): ping Deribit ogni 5s
                           se down >30s → emergency_close_all()
  TelegramAlerts (daemon): Queue consumer, rate-limited
```

---

## 3. Componenti Core

### 3.1 AsyncTradingBot (`src/async_trading_bot.py`)

Il bot principale usa `asyncio` per gestire 6 task concorrenti senza threading esplicito.

```python
async def start(self):
    await asyncio.gather(
        self._data_route_loop(),      # 5ms sleep  — routing dati
        self._orderbook_loop(),        # continuo   — aggiorna L2 book
        self._regime_loop(),           # 60s        — classifica regime
        self._scan_loop(),             # N minuti   — scansione strategie
        self._management_loop(),       # 30s        — gestione posizioni
        self._monitoring_loop(),       # 60s        — alert + dashboard
    )
```

**Perche asyncio e non threading?**
- Le operazioni I/O (WebSocket, REST) sono naturalmente async
- Con threading: race condition su strutture dati condivise, GIL overhead
- Con asyncio: single-threaded, cooperativo, no lock su dict/deque condivisi
- Il codice sync delle strategie viene delegato a `run_in_executor(None, fn)` per non bloccare il loop

**Task priorities**:
| Task | Intervallo | Priorità |
|------|-----------|----------|
| `_data_route_loop` | 5ms | Critica — dati in tempo reale |
| `_orderbook_loop` | continuo | Alta — book sempre aggiornato |
| `_regime_loop` | 60s | Media — regime cambia lentamente |
| `_scan_loop` | 5-15min | Media — segnali non time-critical |
| `_management_loop` | 30s | Alta — orphan cleanup |
| `_monitoring_loop` | 60s | Bassa — alert informativi |

### 3.2 OrderRegistry (`src/core/order_registry.py`)

Risolve il bug critico degli **ordini orfani**: quando un'order SL o TP viene triggerato da Deribit, l'altro ordine (companion) rimane aperto a consumare margine.

```python
# Struttura interna
_registry: Dict[str, Dict] = {
    "trade-001": {
        "entry_id":  "deribit-order-123",
        "sl_id":     "deribit-order-124",
        "tp_id":     "deribit-order-125",
        "trail_id":  None,
        "instrument": "BTC-PERPETUAL",
        "direction":  "buy",
        "opened_at":  "2024-01-01T10:00:00Z"
    }
}
```

**Flusso orphan fix**:
1. `OrderManager.execute_generic_trade()` → piazza entry + SL + TP → chiama `registry.register(trade_id, sl_id, tp_id)`
2. `PositionMonitor._management_loop()` ogni 30s → `get_open_futures_positions()` da Deribit
3. Se `trade_id` non è più aperto → `registry.get_companions(trade_id)` → `client.cancel(sl_id)` + `client.cancel(tp_id)`
4. `registry.unregister(trade_id)` → pulisce la mappa

### 3.3 FailureHandler (`src/core/failure_handler.py`)

Thread daemon separato che monitora la salute dell'API.

```
FailureHandler thread:
  while True:
    sleep(check_interval_sec=5)
    try:
      client.get_account_summary("BTC")  # lightweight ping
      consecutive_failures = 0
    except:
      consecutive_failures += 1
      if consecutive_failures * 5s > max_api_down_sec (30s):
        if position_monitor.get_open_positions():  # posizioni aperte?
          emergency_close_fn()  # chiude tutto
          break
```

**Perche un thread separato e non un task asyncio?**
Il FailureHandler deve funzionare anche se l'event loop asyncio si blocca (es. bug in una strategy che fa loop infinito). Un thread OS è indipendente dall'event loop Python.

### 3.4 BaseStrategy Interface

Contratto immutabile che tutte le strategie implementano:

```python
class BaseStrategy:
    def __init__(self, client: DeribitClient, config: StrategyConfig, deps: dict):
        self.client = client
        self.config = config
        self.order_manager  = deps["order_manager"]
        self.position_monitor = deps["position_monitor"]
        self.risk_manager   = deps["risk_manager"]
        # Opzionali (nuove strategie)
        self.orderflow_engine = deps.get("orderflow_engine")
        self.regime_detector  = deps.get("regime_detector")
        self.scoring_engine   = deps.get("scoring_engine")

    def scan(self) -> List[dict]:
        """Scansiona il mercato e restituisce lista di segnali."""
        raise NotImplementedError

    def execute_entry(self, signal: dict) -> bool:
        """Esegue un'entrata dato un segnale. Ritorna True se eseguita."""
        raise NotImplementedError

    def manage_positions(self) -> dict:
        """Gestisce posizioni aperte (trailing stop, target parziale, ecc.)."""
        raise NotImplementedError
```

**Formato segnale standard**:
```python
signal = {
    "type":        "VOLUME_BREAKOUT",   # identificatore tipo segnale
    "direction":   "buy",               # "buy" o "sell"
    "price":       64500.0,             # prezzo entry stimato
    "stop_loss":   63800.0,             # prezzo SL
    "take_profit": 65800.0,             # prezzo TP
    "quantity":    0.001,               # quantita (BTC)
    "instrument":  "BTC-PERPETUAL",    # strumento Deribit
    "regime":      "TREND_UP",          # regime al momento del segnale
    "confidence":  0.78,                # confidenza [0,1]
    "r_ratio":     1.97,                # (TP-entry)/(entry-SL) ratio
    "label":       "vb-001",            # label per identificazione
}
```

---

## 4. Flusso Dati Completo (Sequence)

```
t=0ms    Binance WS → raw JSON message
t=0.1ms  _process_message() → parse → AggTrade dataclass
t=0.1ms  trade_queue.put_nowait(trade)
t=5ms    _data_route_loop() wakes → trade_queue.get_nowait()
t=5.1ms  orderflow.update_from_trade(trade) → accumulator update
t=100ms  Binance WS → depth update (100ms stream)
t=100.1ms _handle_depth() → DepthUpdate dataclass
t=100.1ms depth_queue.put_nowait(depth)
t=105ms  _data_route_loop() → depth_queue.get_nowait()
t=105.1ms orderbook.apply_update(depth) → bids/asks dict updated
t=105.2ms snap = orderbook.get_snapshot() → OrderBookSnapshot
t=105.3ms orderflow.update_from_book(snap) → imbalance updated
t=60s    _regime_loop() wakes
         candles = orderflow.get_candle_history(symbol, 60, n=50)
         regime = regime_detector.detect(candles, cvd, imbalance)
         _last_regime[sym] = regime
t=900s   _scan_loop() wakes (15min default)
         allowed, reason = scoring.should_trade(strategy_name, regime)
         if allowed:
           signals = strategy.scan()
           for sig in signals:
             qty = risk_manager.calculate_dynamic_size(...)
             sig["quantity"] = qty["quantity"]
             strategy.execute_entry(sig)
             → order_manager.execute_generic_trade(...)
             → deribit_client.buy/sell(...)
             → order_registry.register(...)
t=930s   _management_loop() wakes
         positions = position_monitor.get_open_futures_positions()
         orphan_stats = position_monitor.check_orphan_orders()
```

---

## 5. Sistema di Configurazione

Tutto in `config.py` tramite dataclass + variabili d'ambiente:

```python
@dataclass
class VolumeBreakoutConfig:
    name: str = "VolumeBreakout"
    enabled: bool = True
    symbol: str = "BTCUSDT"           # simbolo Binance (dati)
    instrument: str = "BTC-PERPETUAL" # strumento Deribit (esecuzione)
    breakout_lookback: int = 20        # n candles per high/low
    volume_z_threshold: float = 2.0   # soglia Z-score volume
    min_delta_pct: float = 0.6        # min delta% per conferma
    min_book_imbalance: float = 0.55  # min OBI per long
    max_book_imbalance: float = 0.45  # max OBI per short
    stop_loss_atr_mult: float = 1.5   # SL = entry - 1.5*ATR
    take_profit_rr: float = 2.0       # TP = entry + 2.0 * rischio

    @staticmethod
    def from_env():
        return VolumeBreakoutConfig(
            enabled=os.getenv("VB_ENABLED", "true").lower() == "true",
            symbol=os.getenv("VB_SYMBOL", "BTCUSDT"),
            ...
        )
```

`Config.load_strategies()` istanzia tutte le config abilitati e li passa al TradingBot.

---

## 6. Deployment

### Docker (raccomandato per VPS)

```bash
docker-compose up -d
docker logs -f coinmaker-quant
```

### VPS Linux diretto

```bash
# Installa dipendenze
pip install -r requirements.txt

# Avvia con nohup (persiste dopo logout)
nohup python -c "
import asyncio, logging
logging.basicConfig(level=logging.INFO)
from src.async_trading_bot import AsyncTradingBot
asyncio.run(AsyncTradingBot().start())
" > logs/bot.log 2>&1 &
```

### Requisiti minimi VPS
- CPU: 1 vCPU (il bot e single-threaded via asyncio)
- RAM: 512MB (il maggior consumo e il ring buffer trades: 50000 * ~200B = ~10MB per symbol)
- Storage: 10GB SSD (DuckDB tick data cresce ~50MB/giorno per BTCUSDT)
- Rete: latenza <100ms verso Binance e Deribit

---

## 7. Considerazioni di Sicurezza

| Rischio | Mitigazione |
|---------|-------------|
| API key exposure | Variabili d'ambiente, mai in codice |
| Ordini orfani | OrderRegistry + PositionMonitor.check_orphan_orders() |
| API down | FailureHandler: emergency close dopo 30s |
| Perdite eccessive | KillSwitch in RiskManager (MAX_DAILY_LOSS_PCT) |
| Bug strategie | Ogni strategy.scan() in try/except; errore non blocca le altre |
| Memory leak | Ring buffer con maxlen fisso; no crescita illimitata |
