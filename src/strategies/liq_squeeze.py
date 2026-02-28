"""
LiquidationSqueezeStrategy — rides liquidation cascades.

Logic:
  - Detects when significant forced liquidations create directional order flow
  - A short squeeze (BUY liquidations) creates upward momentum
  - A long dump (SELL liquidations) creates downward momentum

Entry conditions:
  1. Recent liquidation volume spike (e.g. 5x normal in last 5 min)
  2. Delta spike confirming direction
  3. OI decrease (positions being force-closed)
  4. Regime: COMPRESSION or EXPANSION preferred (not needed to be strict)
  5. Liquidity vacuum detected (rapid price move possible)

Exit:
  - Fast trade: TP at 1.5R, SL tight (0.8 ATR)
  - Trail after 1R
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class LiquidationSqueezeStrategy(BaseStrategy):
    """
    Liquidation cascade strategy — rides forced position unwinds.
    """

    def __init__(self, client, config, dependencies: Dict[str, Any]):
        super().__init__(client, config, dependencies)

        self.orderflow_engine = dependencies.get("orderflow_engine")
        self.regime_detector = dependencies.get("regime_detector")
        self.scoring_engine = dependencies.get("scoring_engine")
        self.data_ingestion = dependencies.get("data_ingestion")

        self.symbol = getattr(config, "symbol", "BTCUSDT")
        self.instrument = getattr(config, "instrument", "BTC-PERPETUAL")
        self.liq_volume_threshold = getattr(config, "liq_volume_threshold", 50.0)  # USD/BTC contracts
        self.delta_threshold = getattr(config, "delta_threshold", 0.3)
        self.rr_ratio = getattr(config, "rr_ratio", 1.5)
        self.sl_atr_multiplier = getattr(config, "sl_atr_multiplier", 0.8)

        self._last_signal_time: Optional[float] = None
        self._min_signal_interval_sec = 120  # fast strategy — 2 min min interval
        self._liq_baseline: float = 0.0  # running average liq volume

    def scan(self) -> List[Dict[str, Any]]:
        signals = []
        try:
            if self.scoring_engine:
                regime_str = "COMPRESSION"
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

            buy_liq = snap.liq_buy_volume_10m
            sell_liq = snap.liq_sell_volume_10m

            candles = self.orderflow_engine.get_candle_history(self.symbol, 60, n=20)
            atr = self._compute_atr(candles[-14:]) if len(candles) >= 14 else 0.0
            price = snap.price

            # --- Short squeeze (BUY liquidations) → go long ---
            if (buy_liq > self.liq_volume_threshold and
                    buy_liq > sell_liq * 2 and
                    snap.current_1m and snap.current_1m.delta_pct > self.delta_threshold and
                    snap.oi_change_pct < 0):  # OI falling = forced closes

                sl_price = price - atr * self.sl_atr_multiplier if atr > 0 else price * 0.995
                risk = price - sl_price
                tp_price = price + risk * self.rr_ratio
                signals.append(self._build_signal(
                    "BUY", price, sl_price, tp_price, snap,
                    liq_buy=buy_liq, liq_sell=sell_liq
                ))
                self.logger.info(
                    f"[LiqSqueeze] SHORT SQUEEZE @ {price:.2f} "
                    f"liq_buy={buy_liq:.2f} delta_pct={snap.current_1m.delta_pct:.3f}"
                )

            # --- Long dump (SELL liquidations) → go short ---
            elif (sell_liq > self.liq_volume_threshold and
                  sell_liq > buy_liq * 2 and
                  snap.current_1m and snap.current_1m.delta_pct < -self.delta_threshold and
                  snap.oi_change_pct < 0):

                sl_price = price + atr * self.sl_atr_multiplier if atr > 0 else price * 1.005
                risk = sl_price - price
                tp_price = price - risk * self.rr_ratio
                signals.append(self._build_signal(
                    "SELL", price, sl_price, tp_price, snap,
                    liq_buy=buy_liq, liq_sell=sell_liq
                ))
                self.logger.info(
                    f"[LiqSqueeze] LONG DUMP @ {price:.2f} "
                    f"liq_sell={sell_liq:.2f} delta_pct={snap.current_1m.delta_pct:.3f}"
                )

            if signals:
                self._last_signal_time = now

        except Exception as e:
            self.logger.error(f"[LiqSqueeze] scan error: {e}", exc_info=True)
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
                entry_type="market",  # liquidation squeezes need fast fill
                stop_loss=signal["stop_loss"],
                take_profit=signal["take_profit"],
                label=f"liq_{signal['direction'].lower()}",
            )
            return success
        except Exception as e:
            self.logger.error(f"[LiqSqueeze] execute error: {e}", exc_info=True)
            return False

    def manage_positions(self) -> Dict[str, Any]:
        return {"strategy": self.name, "status": "managed_by_monitor"}

    def _build_signal(self, direction, price, sl, tp, snap, liq_buy=0, liq_sell=0):
        regime_str = "UNKNOWN"
        if self.regime_detector:
            r = self.regime_detector.get_last_regime(self.symbol)
            if r:
                regime_str = r.regime.value
        return {
            "strategy": self.name,
            "type": "LiquidationSqueeze",
            "direction": direction,
            "price": price,
            "stop_loss": sl,
            "take_profit": tp,
            "instrument": self.instrument,
            "symbol": self.symbol,
            "regime": regime_str,
            "liq_buy_volume": liq_buy,
            "liq_sell_volume": liq_sell,
            "oi_change_pct": snap.oi_change_pct,
            "cvd_1m": snap.cvd_1m,
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
        if not self.risk_manager or sl_distance <= 0:
            return 0.001
        try:
            result = self.risk_manager.calculate_dynamic_size(
                instrument_name=self.instrument,
                entry_price=price,
                sl_price=price - sl_distance,
                atr_percentile=70.0,
                regime="EXPANSION",
                model_winrate=0.48,
            )
            return result.get("quantity", 0.001)
        except Exception:
            return 0.001
