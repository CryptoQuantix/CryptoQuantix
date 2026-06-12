# Deribit Execution, Operations and Deployment

## 1. Deribit API — Overview

### 1.1 API Structure

Deribit offers WebSocket for real-time trading and REST as an
alternative. The project's client uses REST
(`src/core/deribit_client.py`) for simplicity and reliability.

**Base URLs**:
- Testnet: `https://test.deribit.com/api/v2`
- Live: `https://www.deribit.com/api/v2`

**Authentication**: client_credentials with `client_id` and
`client_secret`. The token expires every 15 minutes; the client
auto-refreshes.

```python
def authenticate(self) -> bool:
    response = self._request("public/auth", {
        "grant_type": "client_credentials",
        "client_id": self.api_key,
        "client_secret": self.api_secret,
    })
    self._access_token = response.get("access_token")
    return bool(self._access_token)
```

### 1.2 Futures Instruments

Deribit offers two kinds of futures:
- **Perpetual** (e.g. `BTC-PERPETUAL`): no expiry, funding rate every 8h
- **Dated futures** (e.g. `BTC-28MAR25`): settle at the index price on expiry

The project uses **perpetuals exclusively** (more liquid, no rollover
risk).

**Funding rate** for perpetuals:
```
Funding_payment = Position_size * mark_price * funding_rate
funding_rate    = clamp(interest_rate - premium_rate, -0.05%, +0.05%)  per 8h
```

Example: long 0.1 BTC, mark=$64500, funding=0.01%:
```
Payment = 0.1 * 64500 * 0.0001 = $0.645 every 8 hours = $0.0806/hour
```
A marginal cost, but it accumulates on positions held for days.

### 1.3 Available Orders

```python
# Market order (taker, immediate, 0.05% fee)
client.buy(instrument="BTC-PERPETUAL", amount=0.01, order_type="market")

# Limit order (maker if it rests in the book, 0.03% fee)
client.buy(instrument="BTC-PERPETUAL", amount=0.01,
           order_type="limit", price=64000.0)

# Stop order (triggers when price touches the trigger level)
client.buy(instrument="BTC-PERPETUAL", amount=0.01,
           order_type="stop_limit", stop_price=63500.0, price=63480.0)

# Cancel a single order
client.cancel(order_id="ETH-12345")

# Cancel everything (emergency)
client.cancel_all()
```

### 1.4 Position Close

```python
# Close with a market order
client.close_position(instrument="BTC-PERPETUAL", type_="market")

# Or sell/buy an equal and opposite size
```

---

## 2. OrderManager — Execution Flow

### 2.1 execute_generic_trade()

The core method called by every strategy:

```python
def execute_generic_trade(
    self,
    instrument_name: str,
    direction: str,          # "buy" or "sell"
    quantity: float,
    entry_type: str = "market",
    price: float = None,
    stop_loss: float = None,
    take_profit: float = None,
    label: str = "",
) -> Tuple[bool, str]:

    # 1. Entry order
    # 2. Stop Loss (opposite reduce-only stop order, with retries)
    # 3. Take Profit (opposite reduce-only limit order)
    # 4. Register SL/TP in the OrderRegistry for orphan cleanup
    ...
```

The current implementation (see
[05_risk_sizing.md](05_risk_sizing.md)) enters at **market**, places the
SL as a **reduce-only stop_market with 3× retry** and, if the stop cannot
be placed, **emergency-closes** the just-opened position — a position is
never left without a stop on the venue.

### 2.2 The Orphan Order Problem and Its Solution

**The problem**: Deribit automatically executes the SL or TP when the
price reaches them. But the companion order stays open (orphaned).

Typical scenario:
```
t=0:   Buy 0.01 BTC-PERPETUAL @ 64500, SL @ 63800 (order-124), TP @ 65800 (order-125)
t=100: Price drops to 63800 → Deribit executes the SL (order-124) → position closed
t=101: order-125 (TP @ 65800) stays open ← ORPHAN
       It locks margin and risks an accidental fill if the price bounces
```

**Solution with the OrderRegistry**:
```python
# PositionMonitor._check_orphan_orders() runs every 30s

def check_orphan_orders(self, currencies=["BTC", "ETH"]):
    # 1. Currently open positions
    open_positions = self.get_open_futures_positions()
    open_trade_ids = {p["label"] for p in open_positions}

    # 2. Registered trades no longer in a position = orphans
    registered_trades = self.registry.get_all()
    for trade_id, companions in registered_trades.items():
        if trade_id not in open_trade_ids:
            # Position closed → cancel companion orders
            if companions.get("sl_id"):
                self.client.cancel(companions["sl_id"])
            if companions.get("tp_id"):
                self.client.cancel(companions["tp_id"])
            self.registry.unregister(trade_id)
```

---

## 3. PositionMonitor — Position Monitoring

### 3.1 get_open_futures_positions()

```python
def get_open_futures_positions(self) -> List[dict]:
    """
    Fetches open positions across all futures/perpetual pairs.
    Automatically filters out options (recognizable by the name format,
    e.g. BTC-28MAR25-60000-C).
    """
    positions = []
    for currency in ["BTC", "ETH"]:
        result = self.client._request("private/get_positions", {
            "currency": currency,
            "kind": "future"  # excludes options
        })
        for pos in result.get("result", []):
            if pos.get("size", 0) != 0:  # non-zero positions only
                positions.append({
                    "instrument_name": pos["instrument_name"],
                    "size":  pos["size"],         # positive=long, negative=short
                    "direction": "buy" if pos["size"] > 0 else "sell",
                    "mark_price":  pos["mark_price"],
                    "pnl": pos.get("floating_profit_loss", 0),
                    "entry_price": pos.get("average_price", 0),
                    "label": pos.get("label", ""),
                })
    return positions
```

### 3.2 Portfolio Summary

```python
def get_portfolio_summary(self) -> dict:
    positions = self.get_open_futures_positions()
    total_exposure = sum(abs(p["size"]) * p["mark_price"] for p in positions)
    total_pnl      = sum(p["pnl"] for p in positions)
    return {
        "total_positions": len(positions),
        "total_notional":  total_exposure,
        "total_pnl_usd":   total_pnl,
        "positions": positions,
    }
```

---

## 4. Monitoring and Alerting

### 4.1 TelegramAlerts

The alerting system uses a **background thread** with a queue to:
- Never block the trading loop (even if Telegram is slow/down)
- Rate-limit to avoid spam

```python
class TelegramAlerts:
    def __init__(self, bot_token, chat_id):
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        self._rate_limits = {}  # {event_type: last_sent_ts}

    def _worker(self):
        while True:
            try:
                msg_type, message = self._queue.get(timeout=1.0)
                self._send_telegram(message)
            except queue.Empty:
                continue

    def _send_telegram(self, message: str):
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        requests.post(url, json={
            "chat_id": self._chat_id,
            "text": message,
            "parse_mode": "Markdown",
        }, timeout=10)
```

**Alert types**:

| Method | Trigger | Rate limit |
|--------|---------|------------|
| `send_trade_open()` | Every trade opened | 1/trade |
| `send_trade_close()` | Every trade closed | 1/trade |
| `send_daily_pnl()` | Daily report (23:50) | 1/hour |
| `send_regime_change()` | Regime change | 1/min |
| `send_api_error()` | Deribit API error | 1/min |
| `send_emergency()` | Emergency close | Never (CRITICAL bypass) |
| `send_kill_switch()` | Kill switch activation | Never (CRITICAL bypass) |

### 4.2 Streamlit Dashboard

```bash
# Start the dashboard (separate process from the bot)
streamlit run scripts/run_dashboard.py
```

Six pages: Live trades (with order reconciliation), Risk & Exposure,
Trade history, Market context, Settings (guard-railed .env editor),
Actions (kill switch, manual closes) — details in
[01_architecture.md](01_architecture.md).

---

## 5. Deployment

### 5.1 Docker

The reference deployment uses the repository's `docker-compose.yml`:
**three services** from the same image — `bot` (async trading),
`dashboard` (Streamlit on localhost:8501, to be exposed only behind a
tunnel + authentication) and `collector` (positioning-data archive).

Key design points:
- `./data`, `./logs` and `./.env` are **bind mounts**: data survives
  container re-creation
- **no `env_file:`** in the compose — the bot reads the `.env` FILE with
  `load_dotenv()` at every start, so dashboard-editor changes take
  effect on restart
- `restart: unless-stopped` acts as the supervisor for the
  "edit .env → restart request → restart" flow

```bash
docker compose up -d           # start the 3 services
docker compose ps              # status + healthchecks
docker compose logs -f bot     # follow the bot logs
docker compose down            # stop (data stays on the host)
```

### 5.2 Pre-Live Checklist

Before switching from testnet to live, verify:

- [ ] `dry_run_strategies.py --backtest` passes without errors
- [ ] `dry_run_full.py --duration 120` generates at least 1 signal
- [ ] `.env` has `DERIBIT_ENV=prod` (not testnet)
- [ ] Live API keys created on Deribit with correct permissions (Trade, Read)
- [ ] `INITIAL_EQUITY` set to the real account balance
- [ ] `MAX_DAILY_LOSS_PCT=0.02` (2%) for the first days
- [ ] `MAX_OPEN_TRADES=1` for the first days
- [ ] Telegram bot active and receiving a test message
- [ ] Host with automatic backup of the `.env` file
- [ ] Monitoring alert: if the bot is unresponsive for >5min → manual notification

### 5.3 Historical Data Collection

To collect historical tick data (needed for real backtests):

```bash
# Collects data for 24 hours (leave running in the background)
python scripts/dry_run_data.py --duration 86400 --symbol BTCUSDT

# Data is saved to data/raw/binance_ticks.duckdb
# Roughly 50MB/day for BTCUSDT

# Verify collected data
python -c "
import duckdb
conn = duckdb.connect('data/raw/binance_ticks.duckdb')
print(conn.execute('SELECT COUNT(*) FROM agg_trades').fetchone())
print(conn.execute('SELECT MIN(timestamp_ms), MAX(timestamp_ms) FROM agg_trades').fetchone())
"
```

### 5.4 Log Management

Logs are written to `logs/` with a `RotatingFileHandler`:
- `logs/async_bot.log` (max 5MB, 5 backups)
- `logs/dry_run_full.log`
- `logs/dry_run_orderflow.log`

**Quick scan of recent errors**:
```bash
grep "ERROR\|CRITICAL" logs/async_bot.log | tail -20
```

---

## 6. Troubleshooting

| Issue | Likely cause | Fix |
|-------|--------------|-----|
| `ModuleNotFoundError: websockets` | Dependency not installed | `pip install websockets>=12.0` |
| `[OrderBook] sequence gap` | No initial REST snapshot | Normal at startup; the book stabilizes in ~60s |
| `Authentication failed` | Wrong or expired API key | Regenerate on Deribit, update `.env` |
| Kill switch active | Daily loss limit reached | Wait for midnight (automatic reset) or deactivate manually from the dashboard |
| Trades not executed | `can_open_new_position() = False` | Check the logs for the specific reason |
| Persistent orphan orders | Registry out of sync | Restart the bot; the PositionMonitor cleans up at startup |
| `UnicodeEncodeError` on Windows | cp1252 terminal | `set PYTHONIOENCODING=utf-8` before starting |
| Few signals | Scoring threshold too high | Lower `min_score_threshold` in the ScoringEngine or wait for warmup |
| Strategy always BLOCKED | Wrong regime or low score | Check the scoring state + regime status |
