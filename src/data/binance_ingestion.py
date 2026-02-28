"""
BinanceDataIngestion — async WebSocket multi-stream data ingestion from Binance Futures.

Streams consumed:
  - aggTrade: tick-by-tick trades with buyer_is_maker (true buy/sell volume classification)
  - depth@100ms: L2 order book incremental updates
  - forceOrder: liquidations
  - Open Interest: REST polling every 30s

Data is published to internal async queues and optionally stored in DuckDB.
Designed to run as an asyncio task alongside the trading loop.
"""
import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Optional dependency guards
try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    logger.warning("[BinanceIngestion] websockets not installed — pip install websockets>=12.0")

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class AggTrade:
    """Single aggTrade tick from Binance Futures."""
    symbol: str
    trade_id: int
    price: float
    quantity: float
    timestamp_ms: int
    is_buyer_maker: bool  # True = sell aggression, False = buy aggression

    @property
    def side(self) -> str:
        return "SELL" if self.is_buyer_maker else "BUY"

    @property
    def buy_volume(self) -> float:
        return self.quantity if not self.is_buyer_maker else 0.0

    @property
    def sell_volume(self) -> float:
        return self.quantity if self.is_buyer_maker else 0.0


@dataclass
class DepthUpdate:
    """Incremental L2 order book update."""
    symbol: str
    first_update_id: int
    final_update_id: int
    bids: List[List[float]]   # [[price, qty], ...]
    asks: List[List[float]]
    timestamp_ms: int


@dataclass
class LiquidationOrder:
    """Forced liquidation event from Binance Futures."""
    symbol: str
    side: str          # "BUY" = short squeeze, "SELL" = long squeeze
    quantity: float
    price: float
    timestamp_ms: int


@dataclass
class OpenInterestSnapshot:
    """Open Interest snapshot (REST polling)."""
    symbol: str
    oi_contracts: float
    oi_value_usd: float
    timestamp_ms: int


# ---------------------------------------------------------------------------
# Ingestion Engine
# ---------------------------------------------------------------------------

class BinanceDataIngestion:
    """
    Async multi-stream data ingestion from Binance Futures.

    Usage:
        ingestion = BinanceDataIngestion(symbols=["BTCUSDT", "ETHUSDT"])
        asyncio.create_task(ingestion.start())
        trades = ingestion.get_recent_trades("BTCUSDT", n=500)
    """

    FUTURES_WS_BASE = "wss://fstream.binance.com/stream"
    FUTURES_REST_BASE = "https://fapi.binance.com"

    def __init__(
        self,
        symbols: List[str] = None,
        storage_path: str = "data/raw",
        on_trade: Optional[Callable] = None,
        on_depth: Optional[Callable] = None,
        on_liquidation: Optional[Callable] = None,
        oi_poll_interval_sec: float = 30.0,
        max_trade_buffer: int = 50000,
        persist_to_db: bool = True,
    ):
        self.symbols = [s.upper() for s in (symbols or ["BTCUSDT", "ETHUSDT"])]
        self.storage_path = storage_path
        self.on_trade = on_trade
        self.on_depth = on_depth
        self.on_liquidation = on_liquidation
        self.oi_poll_interval_sec = oi_poll_interval_sec
        self.persist_to_db = persist_to_db and HAS_DUCKDB

        # Internal ring buffers (thread-safe via GIL on deque)
        self._trade_buffers: Dict[str, deque] = {
            sym: deque(maxlen=max_trade_buffer) for sym in self.symbols
        }
        self._liquidation_buffer: deque = deque(maxlen=500)
        self._oi_buffer: Dict[str, OpenInterestSnapshot] = {}

        # Async queues for strategy consumption
        self.trade_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self.depth_queue: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self.liquidation_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

        # Runtime state
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._db = None

        # Stats
        self.stats: Dict = {
            "trades_received": 0,
            "depth_updates_received": 0,
            "liquidations_received": 0,
            "oi_polls": 0,
            "ws_reconnects": 0,
            "errors": 0,
            "started_at": None,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Start all WebSocket streams and OI polling."""
        if self._running:
            logger.warning("[BinanceIngestion] Already running")
            return

        if not HAS_WEBSOCKETS:
            logger.error("[BinanceIngestion] Install websockets: pip install websockets>=12.0")
            return

        self._running = True
        self.stats["started_at"] = datetime.now(timezone.utc).isoformat()

        if self.persist_to_db:
            self._init_storage()

        stream_url = self._build_stream_url()

        self._tasks = [
            asyncio.create_task(self._ws_listener(stream_url), name="binance_ws"),
            asyncio.create_task(self._oi_poller(), name="oi_poller"),
        ]

        logger.info(
            f"[BinanceIngestion] Started — symbols: {self.symbols} | "
            f"OI poll: {self.oi_poll_interval_sec}s | "
            f"DB persist: {self.persist_to_db}"
        )

    async def stop(self):
        """Stop all streams and close DB."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._db:
            self._db.close()
        logger.info("[BinanceIngestion] Stopped")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_stream_url(self) -> str:
        streams = []
        for sym in self.symbols:
            sym_lower = sym.lower()
            streams.append(f"{sym_lower}@aggTrade")
            streams.append(f"{sym_lower}@depth@100ms")
            streams.append(f"{sym_lower}@forceOrder")
        return f"{self.FUTURES_WS_BASE}?streams={'/'.join(streams)}"

    def _init_storage(self):
        import os
        os.makedirs(self.storage_path, exist_ok=True)
        db_path = f"{self.storage_path}/binance_ticks.duckdb"
        self._db = duckdb.connect(db_path)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS agg_trades (
                symbol VARCHAR,
                trade_id BIGINT,
                price DOUBLE,
                quantity DOUBLE,
                timestamp_ms BIGINT,
                is_buyer_maker BOOLEAN
            )
        """)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS open_interest (
                symbol VARCHAR,
                oi_contracts DOUBLE,
                oi_value_usd DOUBLE,
                timestamp_ms BIGINT
            )
        """)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS liquidations (
                symbol VARCHAR,
                side VARCHAR,
                quantity DOUBLE,
                price DOUBLE,
                timestamp_ms BIGINT
            )
        """)
        logger.info(f"[BinanceIngestion] DuckDB initialized: {db_path}")

    # ------------------------------------------------------------------
    # WebSocket listener
    # ------------------------------------------------------------------

    async def _ws_listener(self, url: str):
        """Main WebSocket listener with exponential backoff reconnect."""
        reconnect_delay = 1
        while self._running:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=10,
                    max_size=2 ** 23,
                ) as ws:
                    logger.info("[BinanceIngestion] WebSocket connected")
                    reconnect_delay = 1
                    async for raw_msg in ws:
                        if not self._running:
                            break
                        await self._process_message(raw_msg)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.stats["errors"] += 1
                self.stats["ws_reconnects"] += 1
                logger.warning(f"[BinanceIngestion] WS error: {e} — reconnecting in {reconnect_delay}s")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)

    async def _process_message(self, raw_msg: str):
        try:
            msg = json.loads(raw_msg)
            # Combined stream: {"stream": "...", "data": {...}}
            if "stream" in msg:
                stream = msg["stream"]
                data = msg["data"]
                if "@aggTrade" in stream:
                    await self._handle_agg_trade(data)
                elif "@depth" in stream:
                    await self._handle_depth(data)
                elif "@forceOrder" in stream:
                    await self._handle_force_order(data)
            else:
                etype = msg.get("e", "")
                if etype == "aggTrade":
                    await self._handle_agg_trade(msg)
                elif etype == "depthUpdate":
                    await self._handle_depth(msg)
                elif etype == "forceOrder":
                    await self._handle_force_order(msg)
        except Exception as e:
            logger.debug(f"[BinanceIngestion] msg parse error: {e}")
            self.stats["errors"] += 1

    async def _handle_agg_trade(self, data: dict):
        try:
            trade = AggTrade(
                symbol=data["s"],
                trade_id=data["a"],
                price=float(data["p"]),
                quantity=float(data["q"]),
                timestamp_ms=data["T"],
                is_buyer_maker=data["m"],
            )
            buf = self._trade_buffers.get(trade.symbol)
            if buf is not None:
                buf.append(trade)
            self.stats["trades_received"] += 1

            try:
                self.trade_queue.put_nowait(trade)
            except asyncio.QueueFull:
                pass

            if self.on_trade:
                if asyncio.iscoroutinefunction(self.on_trade):
                    await self.on_trade(trade)
                else:
                    self.on_trade(trade)

            # Persist every 500 trades
            if self.persist_to_db and self.stats["trades_received"] % 500 == 0:
                await self._flush_trades(trade.symbol)

        except Exception as e:
            logger.debug(f"[BinanceIngestion] aggTrade error: {e}")

    async def _handle_depth(self, data: dict):
        try:
            update = DepthUpdate(
                symbol=data["s"],
                first_update_id=data["U"],
                final_update_id=data["u"],
                bids=[[float(p), float(q)] for p, q in data.get("b", [])],
                asks=[[float(p), float(q)] for p, q in data.get("a", [])],
                timestamp_ms=data.get("T", int(time.time() * 1000)),
            )
            self.stats["depth_updates_received"] += 1
            try:
                self.depth_queue.put_nowait(update)
            except asyncio.QueueFull:
                pass
            if self.on_depth:
                if asyncio.iscoroutinefunction(self.on_depth):
                    await self.on_depth(update)
                else:
                    self.on_depth(update)
        except Exception as e:
            logger.debug(f"[BinanceIngestion] depth error: {e}")

    async def _handle_force_order(self, data: dict):
        try:
            order = data.get("o", data)
            liq = LiquidationOrder(
                symbol=order["s"],
                side=order["S"],
                quantity=float(order["q"]),
                price=float(order.get("ap", order.get("p", 0))),
                timestamp_ms=order.get("T", int(time.time() * 1000)),
            )
            self._liquidation_buffer.append(liq)
            self.stats["liquidations_received"] += 1
            try:
                self.liquidation_queue.put_nowait(liq)
            except asyncio.QueueFull:
                pass
            logger.info(
                f"[LIQUIDATION] {liq.symbol} {liq.side} "
                f"{liq.quantity:.4f} @ ${liq.price:,.2f}"
            )
            if self.on_liquidation:
                if asyncio.iscoroutinefunction(self.on_liquidation):
                    await self.on_liquidation(liq)
                else:
                    self.on_liquidation(liq)
        except Exception as e:
            logger.debug(f"[BinanceIngestion] forceOrder error: {e}")

    # ------------------------------------------------------------------
    # OI Poller
    # ------------------------------------------------------------------

    async def _oi_poller(self):
        """Poll Open Interest via REST every N seconds."""
        while self._running:
            try:
                await asyncio.sleep(self.oi_poll_interval_sec)
                for symbol in self.symbols:
                    oi = await self._fetch_open_interest(symbol)
                    if oi:
                        self._oi_buffer[symbol] = oi
                        self.stats["oi_polls"] += 1
                        if self.persist_to_db and self._db:
                            self._db.execute(
                                "INSERT INTO open_interest VALUES (?, ?, ?, ?)",
                                [oi.symbol, oi.oi_contracts, oi.oi_value_usd, oi.timestamp_ms],
                            )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"[BinanceIngestion] OI poll error: {e}")

    async def _fetch_open_interest(self, symbol: str) -> Optional[OpenInterestSnapshot]:
        try:
            import urllib.request
            url = f"{self.FUTURES_REST_BASE}/fapi/v1/openInterest?symbol={symbol}"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
            oi_contracts = float(data["openInterest"])
            price_url = f"{self.FUTURES_REST_BASE}/fapi/v1/premiumIndex?symbol={symbol}"
            with urllib.request.urlopen(price_url, timeout=5) as resp:
                price_data = json.loads(resp.read())
            mark_price = float(price_data["markPrice"])
            return OpenInterestSnapshot(
                symbol=symbol,
                oi_contracts=oi_contracts,
                oi_value_usd=oi_contracts * mark_price,
                timestamp_ms=int(time.time() * 1000),
            )
        except Exception as e:
            logger.debug(f"[BinanceIngestion] OI fetch {symbol}: {e}")
            return None

    # ------------------------------------------------------------------
    # DB flush
    # ------------------------------------------------------------------

    async def _flush_trades(self, symbol: str):
        if not self._db:
            return
        try:
            buf = self._trade_buffers.get(symbol, deque())
            batch = list(buf)[-500:]
            self._db.executemany(
                "INSERT INTO agg_trades VALUES (?, ?, ?, ?, ?, ?)",
                [(t.symbol, t.trade_id, t.price, t.quantity, t.timestamp_ms, t.is_buyer_maker)
                 for t in batch],
            )
        except Exception as e:
            logger.debug(f"[BinanceIngestion] DB flush error: {e}")

    # ------------------------------------------------------------------
    # Public accessors (sync, thread-safe via GIL)
    # ------------------------------------------------------------------

    def get_recent_trades(self, symbol: str, n: int = 500) -> List[AggTrade]:
        """Return N most recent trades for a symbol."""
        buf = self._trade_buffers.get(symbol.upper(), deque())
        return list(buf)[-n:]

    def get_open_interest(self, symbol: str) -> Optional[OpenInterestSnapshot]:
        """Return latest OI snapshot for a symbol."""
        return self._oi_buffer.get(symbol.upper())

    def get_recent_liquidations(self, symbol: str, n: int = 50) -> List[LiquidationOrder]:
        """Return N most recent liquidations for a symbol."""
        return [l for l in list(self._liquidation_buffer) if l.symbol == symbol.upper()][-n:]

    def get_stats(self) -> dict:
        return dict(self.stats)
