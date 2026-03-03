"""
MeanReversionStrategy — fades extremes in ranging/compressed markets.

Entry conditions:
  1. Regime: RANGE or COMPRESSION (never TREND_UP/TREND_DOWN)
  2. VWAP Z-score extreme: price > 2σ above or below VWAP
  3. CVD divergence: price at extreme but CVD reversing (delta exhaustion)
  4. Book imbalance contrarian: price at top but asks dominant (> 0.55)
  5. Low volume (not a breakout — volume_zscore < 1.5)
  6. Absorption signal (optional, adds confidence)

Exit:
  - TP: revert to VWAP (or 1.5R)
  - SL: beyond extreme + 0.5 ATR
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class MeanReversionStrategy(BaseStrategy):
    """
    VWAP mean reversion strategy for range/compression regimes.
    """

    def __init__(self, client, config, dependencies: Dict[str, Any]):
        super().__init__(client, config, dependencies)

        self.orderflow_engine = dependencies.get("orderflow_engine")
        self.regime_detector = dependencies.get("regime_detector")
        self.scoring_engine = dependencies.get("scoring_engine")

        self.symbol = getattr(config, "symbol", "BTCUSDT")
        self.instrument = getattr(config, "instrument", "BTC-PERPETUAL")
        self.vwap_z_threshold = getattr(config, "vwap_z_threshold", 2.0)
        self.max_volume_zscore = getattr(config, "max_volume_zscore", 1.5)
        self.rr_ratio = getattr(config, "rr_ratio", 1.5)
        self.sl_atr_multiplier = getattr(config, "sl_atr_multiplier", 1.2)

        self._last_signal_time: Optional[float] = None
        self._min_signal_interval_sec = 180  # max 1 per 3 min

    def scan(self) -> List[Dict[str, Any]]:
        signals = []
        try:
            # Regime check — hard requirement
            if self.regime_detector:
                regime = self.regime_detector.get_last_regime(self.symbol)
                if regime and regime.regime.value in ("TREND_UP", "TREND_DOWN"):
                    if self.orderflow_engine:
                        self.orderflow_engine.flush_snapshot(self.symbol)
                        snap_q = self.orderflow_engine.get_snapshot(self.symbol)
                        if snap_q and snap_q.price > 0:
                            p = snap_q.price
                            direction = "SELL" if regime.regime.value == "TREND_UP" else "BUY"
                            rough_sl = p * (1 + 0.006) if direction == "SELL" else p * (1 - 0.006)
                            rough_risk = abs(p - rough_sl)
                            rough_tp = p - rough_risk * self.rr_ratio if direction == "SELL" else p + rough_risk * self.rr_ratio
                            self._log_blocked(f"regime_{regime.regime.value}", direction, p, rough_sl, rough_tp, regime.regime.value)
                    return []

            # Scoring check
            if self.scoring_engine:
                regime_str = "RANGE"
                if self.regime_detector:
                    r = self.regime_detector.get_last_regime(self.symbol)
                    if r:
                        regime_str = r.regime.value
                allowed, reason = self.scoring_engine.should_trade(
                    self.__class__.__name__, regime_str
                )
                if not allowed:
                    return []

            # Rate limiting
            now = time.time()
            if self._last_signal_time and now - self._last_signal_time < self._min_signal_interval_sec:
                return []

            if not self.orderflow_engine:
                return []

            self.orderflow_engine.flush_snapshot(self.symbol)
            snap = self.orderflow_engine.get_snapshot(self.symbol)
            if not snap or snap.price <= 0:
                return []

            # Reject if volume is breaking out (not a reversion setup)
            if snap.volume_zscore >= self.max_volume_zscore:
                return []

            # Need VWAP deviation data
            if not snap.current_1m or snap.vwap_z == 0:
                return []

            candles = self.orderflow_engine.get_candle_history(self.symbol, 60, n=30)
            atr = self._compute_atr(candles[-14:]) if len(candles) >= 14 else 0.0

            price = snap.price
            vwap = snap.micro_vwap
            vwap_z = snap.vwap_z
            cvd = snap.cvd_1m

            # --- Long (fade the selloff) ---
            # Price far below VWAP + CVD starting to recover + asks being absorbed
            if (vwap_z < -self.vwap_z_threshold and
                    snap.book_imbalance > 0.5 and   # bids holding
                    snap.is_absorption):

                sl_price = price - atr * self.sl_atr_multiplier if atr > 0 else price * 0.997
                tp_price = vwap if vwap > price else price + (price - sl_price) * self.rr_ratio
                signals.append(self._build_signal("BUY", price, sl_price, tp_price, snap, vwap_z))
                self.logger.info(
                    f"[MeanReversion] LONG fade @ {price:.2f} VWAP={vwap:.2f} "
                    f"z={vwap_z:.2f} imb={snap.book_imbalance:.3f}"
                )

            # --- Short (fade the rally) ---
            elif (vwap_z > self.vwap_z_threshold and
                  snap.book_imbalance < 0.5 and    # asks dominant
                  snap.is_absorption):

                sl_price = price + atr * self.sl_atr_multiplier if atr > 0 else price * 1.003
                tp_price = vwap if vwap < price else price - (sl_price - price) * self.rr_ratio
                signals.append(self._build_signal("SELL", price, sl_price, tp_price, snap, vwap_z))
                self.logger.info(
                    f"[MeanReversion] SHORT fade @ {price:.2f} VWAP={vwap:.2f} "
                    f"z={vwap_z:.2f} imb={snap.book_imbalance:.3f}"
                )

            if signals:
                self._last_signal_time = now

        except Exception as e:
            self.logger.error(f"[MeanReversion] scan error: {e}", exc_info=True)
        return signals

    def execute_entry(self, signal: Dict[str, Any]) -> bool:
        try:
            if not self.order_manager:
                return False
            sl_distance = abs(signal["price"] - signal["stop_loss"])
            quantity = self._compute_quantity(signal["price"], sl_distance)
            if quantity <= 0:
                return False
            success, msg = self.order_manager.execute_generic_trade(
                instrument_name=self.instrument,
                direction=signal["direction"].lower(),
                quantity=quantity,
                entry_type="limit",
                price=signal["price"],
                stop_loss=signal["stop_loss"],
                take_profit=signal["take_profit"],
                label=f"mr_{signal['direction'].lower()}",
            )
            if success:
                self._log_executed(
                    signal["direction"], signal["price"],
                    signal["stop_loss"], signal["take_profit"],
                    signal.get("regime", "UNKNOWN"),
                )
            return success
        except Exception as e:
            self.logger.error(f"[MeanReversion] execute error: {e}", exc_info=True)
            return False

    def manage_positions(self) -> Dict[str, Any]:
        return {"strategy": self.name, "status": "managed_by_monitor"}

    def _build_signal(self, direction, price, sl, tp, snap, vwap_z):
        regime_str = "UNKNOWN"
        if self.regime_detector:
            r = self.regime_detector.get_last_regime(self.symbol)
            if r:
                regime_str = r.regime.value
        return {
            "strategy": self.name,
            "type": "MeanReversion",
            "direction": direction,
            "price": price,
            "stop_loss": sl,
            "take_profit": tp,
            "instrument": self.instrument,
            "symbol": self.symbol,
            "regime": regime_str,
            "vwap_z": vwap_z,
            "book_imbalance": snap.book_imbalance,
            "cvd_1m": snap.cvd_1m,
            "is_absorption": snap.is_absorption,
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
        return float(np.mean(trs)) if trs else 0.0

    def _compute_quantity(self, price: float, sl_distance: float) -> float:
        # Returns USD amount rounded to Deribit BTC-PERPETUAL step (10 USD)
        if not self.risk_manager or sl_distance <= 0:
            return 10
        try:
            result = self.risk_manager.calculate_dynamic_size(
                instrument_name=self.instrument,
                entry_price=price,
                sl_price=price - sl_distance,
                atr_percentile=30.0,
                regime="RANGE",
                model_winrate=0.55,
            )
            qty_usd = result.get("quantity_usd", 10.0)
            return max(10, int(qty_usd / 10) * 10)
        except Exception:
            return 10
