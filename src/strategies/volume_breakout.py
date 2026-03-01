"""
VolumeBreakoutStrategy — breakout on expanding volume + positive delta + OI increase.

Entry conditions (all must be true):
  1. Volume Z-score > 2.0 (above-average volume)
  2. Delta positive/negative (direction of breakout)
  3. OI increasing (new money entering, not just liquidations)
  4. Regime: EXPANSION, TREND_UP, or TREND_DOWN (not RANGE/COMPRESSION)
  5. Price breaking recent high/low (N-candle breakout level)
  6. Book imbalance confirming direction (> 0.55 for long, < 0.45 for short)

Exit management:
  - Stop loss: below breakout level (long) / above (short)
  - Take profit: 2.5R from entry
  - Trailing stop: activate after 1R profit
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class VolumeBreakoutStrategy(BaseStrategy):
    """
    Volumetric breakout strategy.
    Requires OrderflowEngine + RegimeDetector for signal generation.
    """

    def __init__(self, client, config, dependencies: Dict[str, Any]):
        super().__init__(client, config, dependencies)

        # Get optional volumetric engines from dependencies
        self.orderflow_engine = dependencies.get("orderflow_engine")
        self.regime_detector = dependencies.get("regime_detector")
        self.scoring_engine = dependencies.get("scoring_engine")
        self.data_ingestion = dependencies.get("data_ingestion")

        # Config params with defaults
        self.symbol = getattr(config, "symbol", "BTCUSDT")
        self.instrument = getattr(config, "instrument", "BTC-PERPETUAL")
        self.volume_zscore_threshold = getattr(config, "volume_zscore_threshold", 2.0)
        self.imbalance_threshold = getattr(config, "imbalance_threshold", 0.55)
        self.breakout_lookback = getattr(config, "breakout_lookback", 20)
        self.rr_ratio = getattr(config, "rr_ratio", 2.5)
        self.sl_atr_multiplier = getattr(config, "sl_atr_multiplier", 1.5)

        self._last_signal_time: Optional[float] = None
        self._min_signal_interval_sec = 300  # max 1 signal per 5 min

    # ------------------------------------------------------------------
    # BaseStrategy interface
    # ------------------------------------------------------------------

    def scan(self) -> List[Dict[str, Any]]:
        """Scan for volume breakout signals."""
        signals = []

        try:
            # Check scoring engine
            if self.scoring_engine:
                regime_str = "UNKNOWN"
                if self.regime_detector:
                    r = self.regime_detector.get_last_regime(self.symbol)
                    if r:
                        regime_str = r.regime.value

                allowed, reason = self.scoring_engine.should_trade(
                    self.__class__.__name__, regime_str
                )
                if not allowed:
                    self.logger.debug(f"Scoring engine blocked: {reason}")
                    return []

            # Rate limiting
            import time
            now = time.time()
            if (self._last_signal_time and
                    now - self._last_signal_time < self._min_signal_interval_sec):
                return []

            # Need orderflow engine
            if not self.orderflow_engine:
                self.logger.debug("No orderflow engine — cannot generate signals")
                return []

            # Force finalization of current candles
            self.orderflow_engine.flush_snapshot(self.symbol)
            snap = self.orderflow_engine.get_snapshot(self.symbol)
            if not snap or snap.price <= 0:
                return []

            # Check regime — skip RANGE (no momentum) and TREND_UP (bull traps, E=-0.40R)
            if self.regime_detector:
                regime = self.regime_detector.get_last_regime(self.symbol)
                if regime and regime.regime.value in ("RANGE", "TREND_UP"):
                    self.logger.debug(f"Regime {regime.regime.value} — skipping breakout")
                    # Log opportunita' persa (SL/TP stimati dal config)
                    price = snap.price
                    direction = "BUY" if snap.cvd_1m >= 0 else "SELL"
                    rough_sl = price * (1 - 0.008) if direction == "BUY" else price * (1 + 0.008)
                    rough_risk = abs(price - rough_sl)
                    rough_tp = price + rough_risk * self.rr_ratio if direction == "BUY" else price - rough_risk * self.rr_ratio
                    self._log_blocked(f"regime_{regime.regime.value}", direction, price, rough_sl, rough_tp, regime.regime.value)
                    return []

            # Get candle history for breakout level
            candles = self.orderflow_engine.get_candle_history(
                self.symbol, interval_seconds=300, n=self.breakout_lookback + 5
            )
            if len(candles) < self.breakout_lookback:
                return []

            current_candle = snap.current_5m
            if not current_candle:
                return []

            # Compute breakout levels
            recent_highs = [c.high for c in candles[-self.breakout_lookback:-1]]
            recent_lows = [c.low for c in candles[-self.breakout_lookback:-1]]
            if not recent_highs:
                return []

            breakout_high = max(recent_highs)
            breakout_low = min(recent_lows)
            current_price = snap.price

            # ATR for stop sizing
            atr = self._compute_atr(candles[-20:])

            # --- Long breakout ---
            if (current_price > breakout_high and
                    snap.volume_zscore >= self.volume_zscore_threshold and
                    current_candle.delta > 0 and
                    snap.book_imbalance > self.imbalance_threshold and
                    snap.oi_change_pct >= 0):

                sl_price = breakout_high - atr * self.sl_atr_multiplier
                risk = current_price - sl_price
                if risk > 0:
                    tp_price = current_price + risk * self.rr_ratio
                    signal = self._build_signal("BUY", current_price, sl_price, tp_price, snap)
                    signals.append(signal)
                    self.logger.info(
                        f"[VolumeBreakout] LONG signal @ {current_price:.2f} "
                        f"SL={sl_price:.2f} TP={tp_price:.2f} "
                        f"vol_z={snap.volume_zscore:.2f} imb={snap.book_imbalance:.3f}"
                    )

            # --- Short breakout ---
            elif (current_price < breakout_low and
                  snap.volume_zscore >= self.volume_zscore_threshold and
                  current_candle.delta < 0 and
                  snap.book_imbalance < (1 - self.imbalance_threshold) and
                  snap.oi_change_pct >= 0):

                sl_price = breakout_low + atr * self.sl_atr_multiplier
                risk = sl_price - current_price
                if risk > 0:
                    tp_price = current_price - risk * self.rr_ratio
                    signal = self._build_signal("SELL", current_price, sl_price, tp_price, snap)
                    signals.append(signal)
                    self.logger.info(
                        f"[VolumeBreakout] SHORT signal @ {current_price:.2f} "
                        f"SL={sl_price:.2f} TP={tp_price:.2f} "
                        f"vol_z={snap.volume_zscore:.2f} imb={snap.book_imbalance:.3f}"
                    )

            if signals:
                self._last_signal_time = now

        except Exception as e:
            self.logger.error(f"[VolumeBreakout] scan error: {e}", exc_info=True)

        return signals

    def execute_entry(self, signal: Dict[str, Any]) -> bool:
        """Execute a volume breakout entry."""
        try:
            if not self.order_manager:
                self.logger.error("No order_manager")
                return False

            self._log_executed(
                signal["direction"], signal["price"],
                signal["stop_loss"], signal["take_profit"],
                signal.get("regime", "UNKNOWN"),
            )

            # Dynamic position sizing
            sl_distance = abs(signal["price"] - signal["stop_loss"])
            quantity = self._compute_quantity(signal["price"], sl_distance)

            if quantity <= 0:
                self.logger.warning("Quantity too small — skipping")
                return False

            success, msg = self.order_manager.execute_generic_trade(
                instrument_name=self.instrument,
                direction=signal["direction"].lower(),
                quantity=quantity,
                entry_type="limit",
                price=signal["price"],
                stop_loss=signal["stop_loss"],
                take_profit=signal["take_profit"],
                label=f"vb_{signal['direction'].lower()}_{signal['price']:.0f}",
            )
            if success:
                self.logger.info(f"[VolumeBreakout] Entry executed: {msg}")
            return success

        except Exception as e:
            self.logger.error(f"[VolumeBreakout] execute error: {e}", exc_info=True)
            return False

    def manage_positions(self) -> Dict[str, Any]:
        """Managed by position_monitor + order_registry — nothing extra needed here."""
        return {"strategy": self.name, "status": "managed_by_monitor"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_signal(
        self, direction: str, price: float, sl: float, tp: float, snap
    ) -> Dict[str, Any]:
        regime_str = "UNKNOWN"
        if self.regime_detector:
            r = self.regime_detector.get_last_regime(self.symbol)
            if r:
                regime_str = r.regime.value

        return {
            "strategy": self.name,
            "type": "VolumeBreakout",
            "direction": direction,
            "price": price,
            "stop_loss": sl,
            "take_profit": tp,
            "instrument": self.instrument,
            "symbol": self.symbol,
            "regime": regime_str,
            "volume_zscore": snap.volume_zscore,
            "book_imbalance": snap.book_imbalance,
            "cvd_5m": snap.cvd_5m,
            "oi_change_pct": snap.oi_change_pct,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _compute_atr(self, candles: List) -> float:
        if len(candles) < 2:
            return 0.0
        import numpy as np
        trs = [
            max(c.high - c.low, abs(c.high - candles[i - 1].close), abs(c.low - candles[i - 1].close))
            for i, c in enumerate(candles[1:], 1)
        ]
        return float(np.mean(trs[-14:])) if trs else 0.0

    def _compute_quantity(self, price: float, sl_distance: float) -> float:
        if not self.risk_manager or sl_distance <= 0:
            return 0.001  # minimum fallback
        try:
            result = self.risk_manager.calculate_dynamic_size(
                instrument_name=self.instrument,
                entry_price=price,
                sl_price=price - sl_distance,
                atr_percentile=50.0,
                regime="EXPANSION",
                model_winrate=0.5,
            )
            return result.get("quantity", 0.001)
        except Exception:
            return 0.001
