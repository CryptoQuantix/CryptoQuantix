"""
OrderflowEngine — computes all volumetric/orderflow features from aggTrade stream.

Features computed:
  - Volume Delta (buy_vol - sell_vol) per candle
  - CVD (Cumulative Volume Delta) multi-timeframe: 1m, 5m, 15m
  - Book Imbalance (from OrderBookEngine)
  - Aggression Ratio: aggr_buy_count / (aggr_buy_count + aggr_sell_count)
  - Liquidity Pressure: rate of consumption of bid/ask depth levels
  - Micro VWAP rolling + std bands
  - Liquidity Vacuum: detected from OrderBookEngine gaps
  - Absorption: negative delta + flat price (sellers absorbed by buyers)
  - Market Impact (Kyle's Lambda): price change per unit volume
  - Z-Volume: current volume vs rolling mean/std

Output: MarketSnapshot dataclass — updated at configurable intervals.
"""
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CandleFeatures:
    """Orderflow features for a single candle period."""
    timestamp_ms: int
    interval_seconds: int

    # Price
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0

    # Raw volume
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    total_volume: float = 0.0
    trade_count: int = 0

    # Delta
    delta: float = 0.0          # buy_volume - sell_volume
    delta_pct: float = 0.0      # delta / total_volume

    # CVD (filled from rolling calculation)
    cvd_1m: float = 0.0
    cvd_5m: float = 0.0
    cvd_15m: float = 0.0

    # Aggression
    aggr_buy_count: int = 0
    aggr_sell_count: int = 0
    aggression_ratio: float = 0.5   # 0.0=all sellers, 1.0=all buyers

    # VWAP
    vwap: float = 0.0
    vwap_dev: float = 0.0         # distance from VWAP in price units
    vwap_z: float = 0.0           # normalized deviation

    # Volume Z-score
    volume_zscore: float = 0.0

    # Absorption (sellers absorbed = delta < 0 but price stable/rising)
    is_absorption_buy: bool = False
    is_absorption_sell: bool = False


@dataclass
class MarketSnapshot:
    """
    Current state of all orderflow features for a symbol.
    Updated every interval by OrderflowEngine.
    Consumed by strategies via get_snapshot().
    """
    symbol: str
    timestamp_ms: int
    price: float = 0.0

    # Most recent candle features (1m)
    current_1m: Optional[CandleFeatures] = None
    current_5m: Optional[CandleFeatures] = None
    current_15m: Optional[CandleFeatures] = None

    # CVD values
    cvd_1m: float = 0.0
    cvd_5m: float = 0.0
    cvd_15m: float = 0.0

    # Book metrics (from OrderBookEngine)
    book_imbalance: float = 0.5
    bid_volume_10: float = 0.0
    ask_volume_10: float = 0.0
    has_liquidity_vacuum: bool = False
    spread_bps: float = 0.0

    # Aggression
    aggression_ratio: float = 0.5
    aggression_trend: float = 0.0  # rolling slope

    # Liquidity pressure (bid/ask consumption rate)
    bid_consumption_rate: float = 0.0  # levels consumed per second
    ask_consumption_rate: float = 0.0

    # VWAP
    micro_vwap: float = 0.0
    vwap_z: float = 0.0

    # Volume statistics
    volume_zscore: float = 0.0
    oi_change_pct: float = 0.0    # OI % change since last snapshot

    # Kyle's Lambda (market impact)
    kyle_lambda: float = 0.0

    # Signals (detected patterns)
    is_absorption: bool = False
    is_liq_vacuum: bool = False
    is_volume_spike: bool = False   # volume_zscore > 2

    # Open interest
    oi_contracts: float = 0.0
    oi_value_usd: float = 0.0

    # Recent liquidations
    liq_buy_volume_10m: float = 0.0   # BUY liquidations = short squeeze
    liq_sell_volume_10m: float = 0.0  # SELL liquidations = long squeeze


class OrderflowEngine:
    """
    Computes volumetric and orderflow features from raw market data.

    Usage:
        engine = OrderflowEngine(symbols=["BTCUSDT"])
        # Feed data from BinanceDataIngestion:
        engine.update_from_trade(trade)
        engine.update_from_book(book_snapshot)
        engine.update_from_oi(oi_snapshot)
        # Consume:
        snap = engine.get_snapshot("BTCUSDT")
    """

    def __init__(
        self,
        symbols: List[str] = None,
        vwap_window: int = 100,        # trades for micro VWAP
        volume_zscore_window: int = 20, # candles for volume Z-score
        kyle_lambda_window: int = 30,   # candles for Kyle's Lambda
        absorption_delta_threshold: float = -0.3,  # delta_pct threshold for absorption
        absorption_price_threshold: float = 0.001, # max price move % for absorption
    ):
        self.symbols = [s.upper() for s in (symbols or ["BTCUSDT", "ETHUSDT"])]
        self.vwap_window = vwap_window
        self.volume_zscore_window = volume_zscore_window
        self.kyle_lambda_window = kyle_lambda_window
        self.absorption_delta_threshold = absorption_delta_threshold
        self.absorption_price_threshold = absorption_price_threshold

        # Per-symbol candle accumulators {symbol: {interval: current_candle_dict}}
        self._current_candles: Dict[str, Dict[int, Dict]] = {
            sym: {60: {}, 300: {}, 900: {}} for sym in self.symbols
        }

        # Historical candles for each interval {symbol: {interval: deque of CandleFeatures}}
        self._candle_history: Dict[str, Dict[int, Deque]] = {
            sym: {
                60: deque(maxlen=500),
                300: deque(maxlen=200),
                900: deque(maxlen=100),
            }
            for sym in self.symbols
        }

        # CVD running totals {symbol: {interval: cvd_value}}
        self._cvd: Dict[str, Dict[int, float]] = {
            sym: {60: 0.0, 300: 0.0, 900: 0.0} for sym in self.symbols
        }

        # Micro VWAP buffers {symbol: deque of (price, vol)}
        self._vwap_buffer: Dict[str, Deque] = {
            sym: deque(maxlen=vwap_window) for sym in self.symbols
        }

        # Kyle's Lambda {symbol: deque of (delta, price_change)}
        self._kyle_buffer: Dict[str, Deque] = {
            sym: deque(maxlen=kyle_lambda_window) for sym in self.symbols
        }

        # Latest snapshots
        self._snapshots: Dict[str, MarketSnapshot] = {}

        # OI tracking
        self._last_oi: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Data ingestion
    # ------------------------------------------------------------------

    def update_from_trade(self, trade):
        """Process a single AggTrade tick."""
        sym = trade.symbol
        if sym not in self.symbols:
            return

        ts_ms = trade.timestamp_ms
        price = trade.price
        qty = trade.quantity

        # Update VWAP buffer
        self._vwap_buffer[sym].append((price, qty))

        # Update candle accumulators for each interval
        for interval in [60, 300, 900]:
            interval_ms = interval * 1000
            bucket_ts = (ts_ms // interval_ms) * interval_ms
            acc = self._current_candles[sym][interval]

            if not acc or acc.get("bucket_ts") != bucket_ts:
                # New candle started — finalize previous
                if acc:
                    self._finalize_candle(sym, interval, acc)
                # Start new candle
                self._current_candles[sym][interval] = {
                    "bucket_ts": bucket_ts,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "buy_vol": 0.0,
                    "sell_vol": 0.0,
                    "total_vol": 0.0,
                    "trade_count": 0,
                    "aggr_buy": 0,
                    "aggr_sell": 0,
                    "vwap_num": 0.0,    # sum(price * qty)
                }

            acc = self._current_candles[sym][interval]
            acc["high"] = max(acc["high"], price)
            acc["low"] = min(acc["low"], price)
            acc["close"] = price
            acc["total_vol"] += qty
            acc["vwap_num"] += price * qty
            acc["trade_count"] += 1

            if trade.is_buyer_maker:
                acc["sell_vol"] += qty
                acc["aggr_sell"] += 1
            else:
                acc["buy_vol"] += qty
                acc["aggr_buy"] += 1

        # Update Kyle's Lambda buffer (1m tracking)
        # We accumulate (order_flow_imbalance, price_change) pairs

    def update_from_book(self, book_snap):
        """Update with an OrderBookSnapshot."""
        sym = book_snap.symbol
        if sym not in self.symbols:
            return
        snap = self._get_or_create_snapshot(sym)
        snap.book_imbalance = book_snap.book_imbalance
        snap.bid_volume_10 = book_snap.bid_volume_10
        snap.ask_volume_10 = book_snap.ask_volume_10
        snap.has_liquidity_vacuum = book_snap.has_liquidity_vacuum
        snap.spread_bps = book_snap.spread_bps
        snap.is_liq_vacuum = book_snap.has_liquidity_vacuum
        snap.price = (book_snap.best_bid + book_snap.best_ask) / 2 if book_snap.best_bid > 0 else snap.price

    def update_from_oi(self, oi_snap):
        """Update with an OpenInterestSnapshot."""
        sym = oi_snap.symbol
        if sym not in self.symbols:
            return
        snap = self._get_or_create_snapshot(sym)
        last_oi = self._last_oi.get(sym, oi_snap.oi_contracts)
        snap.oi_change_pct = (
            (oi_snap.oi_contracts - last_oi) / last_oi * 100
            if last_oi > 0 else 0.0
        )
        snap.oi_contracts = oi_snap.oi_contracts
        snap.oi_value_usd = oi_snap.oi_value_usd
        self._last_oi[sym] = oi_snap.oi_contracts

    def update_from_liquidation(self, liq):
        """Update liquidation running totals."""
        sym = liq.symbol
        if sym not in self.symbols:
            return
        snap = self._get_or_create_snapshot(sym)
        # BUY liq = short squeeze (bullish pressure), SELL liq = long dump
        if liq.side == "BUY":
            snap.liq_buy_volume_10m += liq.quantity
        else:
            snap.liq_sell_volume_10m += liq.quantity

    # ------------------------------------------------------------------
    # Candle finalization
    # ------------------------------------------------------------------

    def _finalize_candle(self, sym: str, interval: int, acc: Dict):
        """Compute features for a completed candle and add to history."""
        if acc["total_vol"] == 0:
            return

        delta = acc["buy_vol"] - acc["sell_vol"]
        delta_pct = delta / acc["total_vol"] if acc["total_vol"] > 0 else 0.0
        total = acc["aggr_buy"] + acc["aggr_sell"]
        aggr_ratio = acc["aggr_buy"] / total if total > 0 else 0.5
        candle_vwap = acc["vwap_num"] / acc["total_vol"] if acc["total_vol"] > 0 else acc["close"]

        # Update CVD
        self._cvd[sym][interval] += delta

        feat = CandleFeatures(
            timestamp_ms=acc["bucket_ts"],
            interval_seconds=interval,
            open=acc["open"],
            high=acc["high"],
            low=acc["low"],
            close=acc["close"],
            buy_volume=acc["buy_vol"],
            sell_volume=acc["sell_vol"],
            total_volume=acc["total_vol"],
            trade_count=acc["trade_count"],
            delta=delta,
            delta_pct=delta_pct,
            cvd_1m=self._cvd[sym][60],
            cvd_5m=self._cvd[sym][300],
            cvd_15m=self._cvd[sym][900],
            aggr_buy_count=acc["aggr_buy"],
            aggr_sell_count=acc["aggr_sell"],
            aggression_ratio=aggr_ratio,
            vwap=candle_vwap,
        )

        # Volume Z-score
        history = self._candle_history[sym][interval]
        if len(history) >= 5:
            recent_vols = [c.total_volume for c in list(history)[-self.volume_zscore_window:]]
            mean_v = np.mean(recent_vols)
            std_v = np.std(recent_vols)
            feat.volume_zscore = (feat.total_volume - mean_v) / std_v if std_v > 0 else 0.0

        # VWAP deviation (vs micro VWAP)
        micro_vwap = self._compute_micro_vwap(sym)
        if micro_vwap > 0:
            feat.vwap_dev = feat.close - micro_vwap
            recent_devs = [c.vwap_dev for c in list(history)[-20:] if c.vwap_dev != 0]
            if len(recent_devs) >= 3:
                dev_std = np.std(recent_devs)
                feat.vwap_z = feat.vwap_dev / dev_std if dev_std > 0 else 0.0

        # Absorption detection (only 1m)
        if interval == 60 and len(history) >= 2:
            prev = list(history)[-1]
            price_change_pct = abs(feat.close - prev.close) / prev.close if prev.close > 0 else 1.0
            # Buy absorption: heavy selling (delta_pct < threshold) + price barely moved
            if (feat.delta_pct < self.absorption_delta_threshold and
                    price_change_pct < self.absorption_price_threshold):
                feat.is_absorption_buy = True
            # Sell absorption: heavy buying but price falling
            if (feat.delta_pct > -self.absorption_delta_threshold and
                    price_change_pct < self.absorption_price_threshold and
                    feat.close < prev.close):
                feat.is_absorption_sell = True

        history.append(feat)

        # Update Kyle's Lambda
        if interval == 60 and len(history) >= 2:
            prev = list(history)[-2]
            price_change = feat.close - prev.close
            order_flow = feat.delta  # net buying pressure
            self._kyle_buffer[sym].append((order_flow, price_change))

        # Update main snapshot
        self._update_snapshot_from_candle(sym, interval, feat)

    def _update_snapshot_from_candle(self, sym: str, interval: int, feat: CandleFeatures):
        snap = self._get_or_create_snapshot(sym)
        snap.timestamp_ms = feat.timestamp_ms
        snap.price = feat.close

        if interval == 60:
            snap.current_1m = feat
            snap.cvd_1m = self._cvd[sym][60]
            snap.aggression_ratio = feat.aggression_ratio
            snap.volume_zscore = feat.volume_zscore
            snap.micro_vwap = self._compute_micro_vwap(sym)
            snap.vwap_z = feat.vwap_z
            snap.is_absorption = feat.is_absorption_buy or feat.is_absorption_sell
            snap.is_volume_spike = feat.volume_zscore > 2.0
            snap.kyle_lambda = self._compute_kyle_lambda(sym)

            # Aggression trend (rolling slope)
            hist = self._candle_history[sym][60]
            if len(hist) >= 5:
                recent_aggr = [c.aggression_ratio for c in list(hist)[-5:]]
                snap.aggression_trend = float(np.polyfit(range(len(recent_aggr)), recent_aggr, 1)[0])

        elif interval == 300:
            snap.current_5m = feat
            snap.cvd_5m = self._cvd[sym][300]

        elif interval == 900:
            snap.current_15m = feat
            snap.cvd_15m = self._cvd[sym][900]

    # ------------------------------------------------------------------
    # Feature computations
    # ------------------------------------------------------------------

    def _compute_micro_vwap(self, sym: str) -> float:
        """Compute rolling micro VWAP from recent trades."""
        buf = self._vwap_buffer.get(sym, deque())
        if not buf:
            return 0.0
        price_vol = list(buf)
        total_vol = sum(v for _, v in price_vol)
        if total_vol == 0:
            return 0.0
        return sum(p * v for p, v in price_vol) / total_vol

    def _compute_kyle_lambda(self, sym: str) -> float:
        """
        Estimate Kyle's Lambda: ΔP = λ × Q_net
        λ = cov(ΔP, Q_net) / var(Q_net)
        Higher lambda = higher market impact per unit volume (thinner market).
        """
        buf = self._kyle_buffer.get(sym, deque())
        if len(buf) < 10:
            return 0.0
        data = list(buf)
        q_net = np.array([d[0] for d in data])
        dp = np.array([d[1] for d in data])
        var_q = np.var(q_net)
        if var_q == 0:
            return 0.0
        return float(np.cov(dp, q_net)[0, 1] / var_q)

    def _get_or_create_snapshot(self, sym: str) -> MarketSnapshot:
        if sym not in self._snapshots:
            self._snapshots[sym] = MarketSnapshot(
                symbol=sym,
                timestamp_ms=int(time.time() * 1000),
            )
        return self._snapshots[sym]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        """Get current MarketSnapshot for a symbol."""
        return self._snapshots.get(symbol.upper())

    def get_cvd(self, symbol: str, interval_seconds: int = 60) -> float:
        """Get current CVD for a symbol and interval."""
        sym = symbol.upper()
        return self._cvd.get(sym, {}).get(interval_seconds, 0.0)

    def get_candle_history(
        self, symbol: str, interval_seconds: int = 60, n: int = 50
    ) -> List[CandleFeatures]:
        """Get N most recent completed candles with all features."""
        sym = symbol.upper()
        history = self._candle_history.get(sym, {}).get(interval_seconds, deque())
        return list(history)[-n:]

    def get_volume_zscore(self, symbol: str) -> float:
        snap = self._snapshots.get(symbol.upper())
        return snap.volume_zscore if snap else 0.0

    def get_book_imbalance(self, symbol: str) -> float:
        snap = self._snapshots.get(symbol.upper())
        return snap.book_imbalance if snap else 0.5

    def is_absorbing_sellers(self, symbol: str) -> bool:
        """True if current candle shows seller absorption (price holding despite sell delta)."""
        snap = self._snapshots.get(symbol.upper())
        if not snap or not snap.current_1m:
            return False
        return snap.current_1m.is_absorption_buy

    def flush_snapshot(self, symbol: str):
        """Force finalization of current in-progress candles (call at strategy scan time)."""
        sym = symbol.upper()
        for interval in [60, 300, 900]:
            acc = self._current_candles.get(sym, {}).get(interval, {})
            if acc and acc.get("total_vol", 0) > 0:
                self._finalize_candle(sym, interval, acc)
