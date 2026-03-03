"""
ImbalanceScalpStrategy — scalps order book imbalance with thin liquidity.

Entry conditions:
  1. Book imbalance extreme: > 0.65 (long) or < 0.35 (short)
  2. Liquidity vacuum: gap in the book → price can move quickly
  3. CVD confirming direction
  4. Aggression ratio confirming (> 0.6 for long, < 0.4 for short)
  5. Volume not spiking (not a breakout — keep tight SL)

Exit:
  - Very tight TP: 0.5% move
  - Tight SL: 0.3% or 0.5 ATR
  - Time-based exit: close after 10 minutes if neither hit
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class ImbalanceScalpStrategy(BaseStrategy):
    """
    Order book imbalance scalping strategy.
    Active in all regimes — very short-duration trades.
    """

    def __init__(self, client, config, dependencies: Dict[str, Any]):
        super().__init__(client, config, dependencies)

        self.orderflow_engine = dependencies.get("orderflow_engine")
        self.regime_detector = dependencies.get("regime_detector")
        self.scoring_engine = dependencies.get("scoring_engine")

        self.symbol = getattr(config, "symbol", "BTCUSDT")
        self.instrument = getattr(config, "instrument", "BTC-PERPETUAL")
        self.imbalance_threshold_long = getattr(config, "imbalance_threshold_long", 0.65)
        self.imbalance_threshold_short = getattr(config, "imbalance_threshold_short", 0.35)
        self.aggression_threshold = getattr(config, "aggression_threshold", 0.60)
        self.tp_pct = getattr(config, "tp_pct", 0.005)   # 0.5%
        self.sl_pct = getattr(config, "sl_pct", 0.003)   # 0.3%
        self.max_volume_zscore = getattr(config, "max_volume_zscore", 1.8)

        self._last_signal_time: Optional[float] = None
        self._min_signal_interval_sec = 60  # 1 signal per minute max

    def scan(self) -> List[Dict[str, Any]]:
        signals = []
        try:
            if self.scoring_engine:
                regime_str = "RANGE"
                if self.regime_detector:
                    r = self.regime_detector.get_last_regime(self.symbol)
                    if r:
                        regime_str = r.regime.value
                allowed, _ = self.scoring_engine.should_trade(self.__class__.__name__, regime_str)
                if not allowed:
                    return []

            now = time.time()
            if self._last_signal_time and now - self._last_signal_time < self._min_signal_interval_sec:
                return []

            if not self.orderflow_engine:
                return []

            self.orderflow_engine.flush_snapshot(self.symbol)
            snap = self.orderflow_engine.get_snapshot(self.symbol)
            if not snap or snap.price <= 0:
                return []

            # Skip if volume is breaking out (not a scalp setup)
            if snap.volume_zscore >= self.max_volume_zscore:
                return []

            price = snap.price
            imbalance = snap.book_imbalance
            aggr = snap.aggression_ratio
            cvd = snap.cvd_1m

            # --- Long imbalance scalp ---
            if (imbalance > self.imbalance_threshold_long and
                    aggr > self.aggression_threshold and
                    cvd >= 0 and
                    snap.is_liq_vacuum):

                sl_price = price * (1 - self.sl_pct)
                tp_price = price * (1 + self.tp_pct)
                signals.append(self._build_signal("BUY", price, sl_price, tp_price, snap))
                self.logger.info(
                    f"[ImbalanceScalp] LONG @ {price:.2f} "
                    f"imb={imbalance:.3f} aggr={aggr:.3f} vacuum={snap.is_liq_vacuum}"
                )

            # --- Short imbalance scalp ---
            elif (imbalance < self.imbalance_threshold_short and
                  aggr < (1 - self.aggression_threshold) and
                  cvd <= 0 and
                  snap.is_liq_vacuum):

                sl_price = price * (1 + self.sl_pct)
                tp_price = price * (1 - self.tp_pct)
                signals.append(self._build_signal("SELL", price, sl_price, tp_price, snap))
                self.logger.info(
                    f"[ImbalanceScalp] SHORT @ {price:.2f} "
                    f"imb={imbalance:.3f} aggr={aggr:.3f} vacuum={snap.is_liq_vacuum}"
                )

            if signals:
                self._last_signal_time = now

        except Exception as e:
            self.logger.error(f"[ImbalanceScalp] scan error: {e}", exc_info=True)
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
                label=f"is_{signal['direction'].lower()}",
            )
            if success:
                self._log_executed(
                    signal["direction"], signal["price"],
                    signal["stop_loss"], signal["take_profit"],
                    signal.get("regime", "UNKNOWN"),
                )
            return success
        except Exception as e:
            self.logger.error(f"[ImbalanceScalp] execute error: {e}", exc_info=True)
            return False

    def manage_positions(self) -> Dict[str, Any]:
        return {"strategy": self.name, "status": "managed_by_monitor"}

    def _build_signal(self, direction, price, sl, tp, snap):
        regime_str = "UNKNOWN"
        if self.regime_detector:
            r = self.regime_detector.get_last_regime(self.symbol)
            if r:
                regime_str = r.regime.value
        return {
            "strategy": self.name,
            "type": "ImbalanceScalp",
            "direction": direction,
            "price": price,
            "stop_loss": sl,
            "take_profit": tp,
            "instrument": self.instrument,
            "symbol": self.symbol,
            "regime": regime_str,
            "book_imbalance": snap.book_imbalance,
            "aggression_ratio": snap.aggression_ratio,
            "cvd_1m": snap.cvd_1m,
            "liq_vacuum": snap.is_liq_vacuum,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _compute_quantity(self, price: float, sl_distance: float) -> float:
        # Returns USD amount rounded to Deribit BTC-PERPETUAL step (10 USD)
        if not self.risk_manager or sl_distance <= 0:
            return 10
        try:
            result = self.risk_manager.calculate_dynamic_size(
                instrument_name=self.instrument,
                entry_price=price,
                sl_price=price - sl_distance,
                atr_percentile=50.0,
                regime="RANGE",
                model_winrate=0.52,
            )
            # Scale down for scalps (50% of normal size)
            qty_usd = result.get("quantity_usd", 20.0) * 0.5
            return max(10, int(qty_usd / 10) * 10)
        except Exception:
            return 10
