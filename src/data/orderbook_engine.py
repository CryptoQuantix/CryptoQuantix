"""
OrderBookEngine — L2 order book reconstruction from Binance Futures depth stream.

Maintains the full bid/ask price levels in memory using sorted structures.
Processes incremental depth updates from BinanceDataIngestion.

Key outputs (per symbol):
  - best_bid, best_ask, spread
  - bid_volume(N levels), ask_volume(N levels)
  - book_imbalance: bid_vol / (bid_vol + ask_vol)
  - top_of_book_ratio: top-3 bid vs ask volume
  - liquidity_vacuum: gap detection in price ladder
"""
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class OrderBookSnapshot:
    """Point-in-time snapshot of one symbol's order book."""
    symbol: str
    timestamp_ms: int

    best_bid: float = 0.0
    best_ask: float = 0.0
    spread: float = 0.0
    spread_bps: float = 0.0

    # Volume at N levels (default: top 10)
    bid_volume_10: float = 0.0
    ask_volume_10: float = 0.0
    bid_volume_20: float = 0.0
    ask_volume_20: float = 0.0

    # Imbalance metrics
    book_imbalance: float = 0.5   # 0.0=all asks, 1.0=all bids; 0.5=balanced
    imbalance_10: float = 0.5
    imbalance_20: float = 0.5

    # Depth quality
    bid_levels: int = 0
    ask_levels: int = 0

    # Liquidity vacuum (largest price gap in top 20 levels)
    max_bid_gap: float = 0.0
    max_ask_gap: float = 0.0
    has_liquidity_vacuum: bool = False  # gap > 5x avg gap

    # Kyle's Lambda proxy (updated externally by OrderflowEngine)
    kyle_lambda: float = 0.0


class OrderBookEngine:
    """
    Reconstructs and maintains L2 order books from incremental Binance depth updates.

    Usage:
        engine = OrderBookEngine(symbols=["BTCUSDT"])
        # Feed updates from BinanceDataIngestion:
        engine.apply_update(depth_update)
        # Get snapshot:
        snap = engine.get_snapshot("BTCUSDT")
    """

    def __init__(
        self,
        symbols: List[str] = None,
        depth_levels: int = 100,
        vacuum_threshold_multiplier: float = 5.0,
    ):
        self.symbols = [s.upper() for s in (symbols or [])]
        self.depth_levels = depth_levels
        self.vacuum_threshold_multiplier = vacuum_threshold_multiplier

        # {symbol: {price: qty}} — sorted handled at snapshot time
        self._bids: Dict[str, Dict[float, float]] = defaultdict(dict)
        self._asks: Dict[str, Dict[float, float]] = defaultdict(dict)
        self._last_update_id: Dict[str, int] = defaultdict(int)
        self._last_snapshot_ts: Dict[str, int] = defaultdict(int)

        self._stats = {
            "updates_processed": 0,
            "updates_dropped": 0,
            "snapshots_generated": 0,
        }

    # ------------------------------------------------------------------
    # Update processing
    # ------------------------------------------------------------------

    def apply_update(self, update) -> bool:
        """
        Apply a DepthUpdate to the internal book.
        Handles sequence gap detection (drops out-of-order updates).

        Args:
            update: DepthUpdate dataclass from BinanceDataIngestion

        Returns:
            True if applied successfully, False if dropped
        """
        symbol = update.symbol

        # Sequence validation
        last_id = self._last_update_id.get(symbol, 0)
        if last_id > 0 and update.first_update_id > last_id + 1:
            logger.warning(
                f"[OrderBook] {symbol} sequence gap: "
                f"expected {last_id + 1}, got {update.first_update_id} — resetting book"
            )
            self._bids[symbol].clear()
            self._asks[symbol].clear()
            self._last_update_id[symbol] = 0
            self._stats["updates_dropped"] += 1

        # Apply bid updates
        for price, qty in update.bids:
            if qty == 0.0:
                self._bids[symbol].pop(price, None)
            else:
                self._bids[symbol][price] = qty

        # Apply ask updates
        for price, qty in update.asks:
            if qty == 0.0:
                self._asks[symbol].pop(price, None)
            else:
                self._asks[symbol][price] = qty

        self._last_update_id[symbol] = update.final_update_id
        self._last_snapshot_ts[symbol] = update.timestamp_ms
        self._stats["updates_processed"] += 1
        return True

    def apply_snapshot(self, symbol: str, bids: List[List[float]], asks: List[List[float]]):
        """
        Apply a full order book snapshot (resets the book).
        Used for initial state or after sequence gap.
        """
        symbol = symbol.upper()
        self._bids[symbol] = {float(p): float(q) for p, q in bids if float(q) > 0}
        self._asks[symbol] = {float(p): float(q) for p, q in asks if float(q) > 0}
        logger.info(
            f"[OrderBook] {symbol} snapshot applied — "
            f"bids: {len(self._bids[symbol])} levels, "
            f"asks: {len(self._asks[symbol])} levels"
        )

    # ------------------------------------------------------------------
    # Snapshot generation
    # ------------------------------------------------------------------

    def get_snapshot(self, symbol: str, levels: int = None) -> Optional[OrderBookSnapshot]:
        """
        Generate a point-in-time snapshot of the order book for a symbol.

        Args:
            symbol: e.g. "BTCUSDT"
            levels: number of price levels to include (default: self.depth_levels)

        Returns:
            OrderBookSnapshot or None if no data
        """
        symbol = symbol.upper()
        if symbol not in self._bids or not self._bids[symbol]:
            return None

        levels = levels or self.depth_levels
        ts = self._last_snapshot_ts.get(symbol, int(time.time() * 1000))

        # Sorted bids (descending) and asks (ascending)
        sorted_bids = sorted(self._bids[symbol].items(), key=lambda x: -x[0])
        sorted_asks = sorted(self._asks[symbol].items(), key=lambda x: x[0])

        if not sorted_bids or not sorted_asks:
            return None

        best_bid = sorted_bids[0][0]
        best_ask = sorted_asks[0][0]
        spread = best_ask - best_bid
        spread_bps = (spread / best_bid * 10000) if best_bid > 0 else 0.0

        # Compute volume sums at 10 and 20 levels
        bid_vol_10 = sum(q for _, q in sorted_bids[:10])
        ask_vol_10 = sum(q for _, q in sorted_asks[:10])
        bid_vol_20 = sum(q for _, q in sorted_bids[:20])
        ask_vol_20 = sum(q for _, q in sorted_asks[:20])

        imbalance_10 = bid_vol_10 / (bid_vol_10 + ask_vol_10) if (bid_vol_10 + ask_vol_10) > 0 else 0.5
        imbalance_20 = bid_vol_20 / (bid_vol_20 + ask_vol_20) if (bid_vol_20 + ask_vol_20) > 0 else 0.5

        # Liquidity vacuum detection in top 20 levels
        max_bid_gap, max_ask_gap, has_vacuum = self._detect_vacuum(
            sorted_bids[:20], sorted_asks[:20]
        )

        snap = OrderBookSnapshot(
            symbol=symbol,
            timestamp_ms=ts,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            spread_bps=spread_bps,
            bid_volume_10=bid_vol_10,
            ask_volume_10=ask_vol_10,
            bid_volume_20=bid_vol_20,
            ask_volume_20=ask_vol_20,
            book_imbalance=imbalance_20,
            imbalance_10=imbalance_10,
            imbalance_20=imbalance_20,
            bid_levels=len(sorted_bids),
            ask_levels=len(sorted_asks),
            max_bid_gap=max_bid_gap,
            max_ask_gap=max_ask_gap,
            has_liquidity_vacuum=has_vacuum,
        )

        self._stats["snapshots_generated"] += 1
        return snap

    def _detect_vacuum(
        self,
        sorted_bids: List[Tuple[float, float]],
        sorted_asks: List[Tuple[float, float]],
    ) -> Tuple[float, float, bool]:
        """
        Detect liquidity vacuums (abnormally large gaps between price levels).
        A vacuum is where price could move quickly with little resistance.
        """
        max_bid_gap = 0.0
        max_ask_gap = 0.0

        if len(sorted_bids) >= 2:
            bid_prices = [p for p, _ in sorted_bids]
            bid_gaps = [bid_prices[i] - bid_prices[i + 1] for i in range(len(bid_prices) - 1)]
            if bid_gaps:
                avg_bid_gap = sum(bid_gaps) / len(bid_gaps)
                max_bid_gap = max(bid_gaps)

        if len(sorted_asks) >= 2:
            ask_prices = [p for p, _ in sorted_asks]
            ask_gaps = [ask_prices[i + 1] - ask_prices[i] for i in range(len(ask_prices) - 1)]
            if ask_gaps:
                avg_ask_gap = sum(ask_gaps) / len(ask_gaps)
                max_ask_gap = max(ask_gaps)
                has_vacuum = (max_ask_gap > avg_ask_gap * self.vacuum_threshold_multiplier or
                              max_bid_gap > (
                                  sum([sorted_bids[i][0] - sorted_bids[i + 1][0]
                                       for i in range(len(sorted_bids) - 1)]) /
                                  max(len(sorted_bids) - 1, 1)
                              ) * self.vacuum_threshold_multiplier)
                return max_bid_gap, max_ask_gap, has_vacuum

        return max_bid_gap, max_ask_gap, False

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    def get_best_bid(self, symbol: str) -> float:
        bids = self._bids.get(symbol.upper(), {})
        return max(bids.keys()) if bids else 0.0

    def get_best_ask(self, symbol: str) -> float:
        asks = self._asks.get(symbol.upper(), {})
        return min(asks.keys()) if asks else 0.0

    def get_mid_price(self, symbol: str) -> float:
        bid = self.get_best_bid(symbol)
        ask = self.get_best_ask(symbol)
        return (bid + ask) / 2 if bid > 0 and ask > 0 else 0.0

    def get_book_imbalance(self, symbol: str, levels: int = 10) -> float:
        """
        Quick imbalance: bid_vol / (bid_vol + ask_vol) at N levels.
        Returns 0.5 if no data.
        """
        symbol = symbol.upper()
        bids = sorted(self._bids.get(symbol, {}).items(), key=lambda x: -x[0])[:levels]
        asks = sorted(self._asks.get(symbol, {}).items(), key=lambda x: x[0])[:levels]
        bid_vol = sum(q for _, q in bids)
        ask_vol = sum(q for _, q in asks)
        total = bid_vol + ask_vol
        return bid_vol / total if total > 0 else 0.5

    def has_data(self, symbol: str) -> bool:
        sym = symbol.upper()
        return bool(self._bids.get(sym)) and bool(self._asks.get(sym))

    def get_stats(self) -> dict:
        return dict(self._stats)
