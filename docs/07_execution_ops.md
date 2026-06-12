# Esecuzione Deribit, Operazioni e Deployment

## 1. Deribit API — Panoramica

### 1.1 Struttura API

Deribit usa WebSocket per trading real-time e REST come alternativa. Il client nel progetto usa REST (`src/core/deribit_client.py`) per semplicita e affidabilita.

**Base URL**:
- Testnet: `https://test.deribit.com/api/v2`
- Live: `https://www.deribit.com/api/v2`

**Autenticazione**: client_credentials con `client_id` e `client_secret`. Il token scade ogni 15 minuti; il client fa auto-refresh.

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

### 1.2 Strumenti Futures

Su Deribit esistono due tipi di futures:
- **Perpetual** (es. `BTC-PERPETUAL`): nessuna scadenza, funding rate ogni 8h
- **Future a scadenza** (es. `BTC-28MAR25`): scade al prezzo indice alla data

Il progetto usa esclusivamente **perpetual** (piu liquidi, nessun rischio rollover).

**Funding rate** per perpetual:
```
Funding_payment = Position_size * mark_price * funding_rate
funding_rate    = clamp(interest_rate - premium_rate, -0.05%, +0.05%)  per 8h
```

Esempio: long 0.1 BTC, mark=$64500, funding=0.01%:
```
Payment = 0.1 * 64500 * 0.0001 = $0.645 ogni 8 ore = $0.0806/ora
```
Costo marginale, ma si accumula su posizioni lunghe tenute giorni.

### 1.3 Ordini Disponibili

```python
# Market order (taker, immediato, fee 0.05%)
client.buy(instrument="BTC-PERPETUAL", amount=0.01, order_type="market")

# Limit order (maker se va in book, fee 0.03%)
client.buy(instrument="BTC-PERPETUAL", amount=0.01,
           order_type="limit", price=64000.0)

# Stop limit (diventa limit quando prezzo tocca trigger)
client.buy(instrument="BTC-PERPETUAL", amount=0.01,
           order_type="stop_limit", stop_price=63500.0, price=63480.0)

# Cancel singolo
client.cancel(order_id="ETH-12345")

# Cancel tutti (emergency)
client.cancel_all()
```

### 1.4 Position Close

```python
# Close with market order
client.close_position(instrument="BTC-PERPETUAL", type_="market")

# Oppure sell/buy size uguale e opposta
```

---

## 2. OrderManager — Flusso di Esecuzione

### 2.1 execute_generic_trade()

Il metodo core che viene chiamato da tutte le strategie:

```python
def execute_generic_trade(
    self,
    instrument_name: str,
    direction: str,          # "buy" o "sell"
    quantity: float,         # in BTC
    entry_type: str = "market",
    price: float = None,
    stop_loss: float = None,
    take_profit: float = None,
    label: str = "",
) -> Tuple[bool, str]:

    # 1. Entry order
    if direction == "buy":
        ok, entry_id = self.client.buy(
            instrument_name, quantity, entry_type, price, label=label
        )
    else:
        ok, entry_id = self.client.sell(
            instrument_name, quantity, entry_type, price, label=label
        )

    if not ok:
        return False, ""

    trade_id = f"{label}-{entry_id}"

    # 2. Stop Loss (ordine opposto a stop_limit)
    sl_id = None
    if stop_loss:
        sl_direction = "sell" if direction == "buy" else "buy"
        ok_sl, sl_id = self.client.place_stop_limit(
            instrument_name, sl_direction, quantity,
            stop_price=stop_loss,
            price=stop_loss * (0.999 if sl_direction == "sell" else 1.001),
            label=f"{label}-sl",
        )

    # 3. Take Profit (ordine opposto a limit)
    tp_id = None
    if take_profit:
        tp_direction = "sell" if direction == "buy" else "buy"
        ok_tp, tp_id = self.client.buy_or_sell(
            instrument_name, tp_direction, quantity,
            order_type="limit", price=take_profit,
            label=f"{label}-tp",
        )

    # 4. Registra nel registry
    if self.registry:
        self.registry.register(trade_id, sl_id=sl_id, tp_id=tp_id,
                               instrument=instrument_name, direction=direction)

    return True, trade_id
```

### 2.2 Orphan Order Problem e Soluzione

**Il problema**: Deribit esegue automaticamente SL o TP quando il prezzo li raggiunge. Ma l'altro ordine rimane aperto (orfano).

Scenario tipico:
```
t=0: Buy 0.01 BTC-PERPETUAL @ 64500, SL @ 63800 (order-124), TP @ 65800 (order-125)
t=100: Prezzo scende a 63800 → Deribit esegue SL (order-124) → posizione chiusa
t=101: order-125 (TP @ 65800) rimane aperto ← ORFANO
       Blocca margine, rischio accidentale fill se prezzo rimbalza
```

**Soluzione con OrderRegistry**:
```python
# PositionMonitor._check_orphan_orders() eseguito ogni 30s

def check_orphan_orders(self, currencies=["BTC", "ETH"]):
    # 1. Posizioni attualmente aperte
    open_positions = self.get_open_futures_positions()
    open_trade_ids = {p["label"] for p in open_positions}

    # 2. Trade registrati ma non piu in posizione = orfani
    registered_trades = self.registry.get_all()
    for trade_id, companions in registered_trades.items():
        if trade_id not in open_trade_ids:
            # Posizione chiusa → cancella companion orders
            if companions.get("sl_id"):
                self.client.cancel(companions["sl_id"])
            if companions.get("tp_id"):
                self.client.cancel(companions["tp_id"])
            self.registry.unregister(trade_id)
```

---

## 3. PositionMonitor — Monitoraggio Posizioni

### 3.1 get_open_futures_positions()

```python
def get_open_futures_positions(self) -> List[dict]:
    """
    Recupera posizioni aperte su tutte le coppie futures/perpetual.
    Filtra automaticamente opzioni (riconoscibili dal formato nome, es. BTC-28MAR25-60000-C).
    """
    positions = []
    for currency in ["BTC", "ETH"]:
        result = self.client._request("private/get_positions", {
            "currency": currency,
            "kind": "future"  # esclude opzioni
        })
        for pos in result.get("result", []):
            if pos.get("size", 0) != 0:  # solo posizioni non-zero
                positions.append({
                    "instrument_name": pos["instrument_name"],
                    "size":  pos["size"],         # positivo=long, negativo=short
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

## 4. Monitoring e Alerting

### 4.1 TelegramAlerts

Il sistema di alerting usa un **background thread** con una coda per:
- Non bloccare mai il trading loop (anche se Telegram e lento/down)
- Rate limiting per evitare spam

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

**Tipi di alert**:

| Metodo | Trigger | Rate limit |
|--------|---------|------------|
| `send_trade_open()` | Apertura ogni trade | 1/trade |
| `send_trade_close()` | Chiusura ogni trade | 1/trade |
| `send_daily_pnl()` | Daily report (23:50) | 1/ora |
| `send_regime_change()` | Cambio regime | 1/min |
| `send_api_error()` | Errore API Deribit | 1/min |
| `send_emergency()` | Emergency close | Mai (CRITICAL bypass) |
| `send_kill_switch()` | Attivazione kill switch | Mai (CRITICAL bypass) |

### 4.2 Dashboard Streamlit

```bash
# Avvio dashboard (in finestra separata)
streamlit run src/monitoring/dashboard.py -- --bot-module src.async_trading_bot
```

Panel disponibili:
1. **Equity Curve**: grafico rendimento in tempo reale
2. **Regime corrente**: TREND/RANGE con confidenza
3. **Orderflow live**: CVD, imbalance, aggression ratio, Kyle's Lambda
4. **Posizioni aperte**: strumento, direzione, size, P&L float
5. **Scoring strategie**: punteggio per ogni strategia
6. **Trade log**: ultimi 20 trade con dettagli

---

## 5. Deployment

### 5.1 Docker

```dockerfile
# Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "-c", "import asyncio; from src.async_trading_bot import AsyncTradingBot; asyncio.run(AsyncTradingBot().start())"]
```

```yaml
# docker-compose.yml
version: "3.8"
services:
  cryptoquantix:
    build: .
    env_file: .env
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "5"
```

```bash
docker-compose up -d                    # avvia in background
docker-compose logs -f cryptoquantix  # segui i log
docker-compose down                     # stop
```

### 5.2 Checklist Pre-Live

Prima di passare da testnet a live, verificare:

- [ ] `dry_run_strategies.py --backtest` passa senza errori
- [ ] `dry_run_full.py --duration 120` genera almeno 1 segnale
- [ ] `.env` ha `DERIBIT_ENV=live` (non testnet)
- [ ] API keys live create su Deribit con permessi corretti (Trade, Read)
- [ ] `INITIAL_EQUITY` impostato al saldo reale del conto
- [ ] `MAX_DAILY_LOSS_PCT=0.02` (2%) per i primi giorni
- [ ] `MAX_OPEN_TRADES=1` per i primi giorni
- [ ] Telegram bot attivo e riceve test message
- [ ] VPS con backup automatico del file `.env`
- [ ] Monitoring alert: se bot non risponde per >5min → notifica manuale

### 5.3 Raccolta Dati Storici

Per raccogliere tick data storici (necessari per backtest reale):

```bash
# Raccoglie dati per 24 ore (lasciare girare in background)
python scripts/dry_run_data.py --duration 86400 --symbol BTCUSDT

# I dati vengono salvati in data/raw/binance_ticks.duckdb
# Circa 50MB/giorno per BTCUSDT

# Verifica dati raccolti
python -c "
import duckdb
conn = duckdb.connect('data/raw/binance_ticks.duckdb')
print(conn.execute('SELECT COUNT(*) FROM agg_trades').fetchone())
print(conn.execute('SELECT MIN(timestamp_ms), MAX(timestamp_ms) FROM agg_trades').fetchone())
"
```

### 5.4 Log Management

I log sono scritti in `logs/` con `RotatingFileHandler`:
- `logs/trading_bot.log` (max 5MB, 5 backup)
- `logs/dry_run_full.log`
- `logs/dry_run_orderflow.log`

**Lettura rapida ultimi errori**:
```bash
grep "ERROR\|CRITICAL" logs/trading_bot.log | tail -20
```

---

## 6. Troubleshooting

| Problema | Causa probabile | Soluzione |
|----------|----------------|-----------|
| `ModuleNotFoundError: websockets` | Dipendenza non installata | `pip install websockets>=12.0` |
| `[OrderBook] sequence gap` | No snapshot REST iniziale | Normale all'avvio; book si stabilizza in ~60s |
| `Authentication failed` | API key errata o scaduta | Rigenerare su Deribit, aggiornare `.env` |
| `Kill switch attivo` | Daily loss limit raggiunto | Aspettare mezzanotte (reset automatico) o disabilitare manualmente |
| Trade non eseguiti | `can_open_new_position() = False` | Verificare log per motivo specifico |
| Ordini orfani persistenti | Registry non sincronizzato | Restart bot; PositionMonitor pulisce all'avvio |
| `UnicodeEncodeError` Windows | Terminal cp1252 | `set PYTHONIOENCODING=utf-8` prima di avviare |
| Pochi segnali | Soglia scoring troppo alta | Ridurre `min_score_threshold` in ScoringEngine o aspettare warmup |
| Strategia sempre BLOCKED | Regime sbagliato o score basso | Verificare `scoring.json` + `dry_run_orderflow.py` per stato regime |
