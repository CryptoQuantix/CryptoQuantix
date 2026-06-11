"""
FundingSqueezeStrategy — contrarian SHORT when longs pay funding AT THE CAP
while the macro downtrend is accelerating.

Quantitative basis:
  - 270d (Sep 2025 - Jun 2026): top-quintile funding -> next-24h returns
    -46bps IS (t=-2.1) / -102bps OOS (t=-3.4).
  - 4-YEAR multi-cycle validation (Jun 2022 - Jun 2026) exposed two failure
    modes of the naive version (funding>0.005% + close<SMA48):
      * bull phases: -23bps/trade  -> fixed by macro bear gate
      * trend transitions (2025: -20%): funding stays positive early in a
        downtrend, relief rallies hit the wide SL -> fixed by requiring
        funding AT the cap (0.01%/8h) AND SMA200d slope negative.
  - Final config on 4y: +74bps/trade, PF 3.05, WR 60% (15 trades — low
    frequency, deep-bear capitulation specialist; 2025 reduced to -1%).

Entry (SHORT, only within entry_window_min after a funding settlement,
matching the validated event timing):
  1. Funding rate >= funding_threshold (default 0.01%/8h = exchange cap)
  2. Last closed 1h close < SMA(sma_h)
  3. Macro gate: daily close < SMA200d AND SMA200d lower than slope_days ago

Exit:
  - SL = entry + sl_atr_mult * ATR(1h,14) (default 2x)
  - TP = tp_rr * risk (default 2R); time exit after max_hold_hours

Data: funding + 1h/1d klines via KlineProvider (injectable for backtest).
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class FundingSqueezeStrategy(BaseStrategy):
    """Crowded-positioning contrarian short (funding extreme + downtrend)."""

    def __init__(self, client, config, dependencies: Dict[str, Any]):
        super().__init__(client, config, dependencies)

        self.regime_detector = dependencies.get("regime_detector")
        self.scoring_engine = dependencies.get("scoring_engine")
        self.kline_provider = dependencies.get("kline_provider")
        if self.kline_provider is None:
            from src.data.kline_provider import BinanceKlineProvider
            self.kline_provider = BinanceKlineProvider()

        self.symbol = getattr(config, "symbol", "BTCUSDT")
        self.instrument = getattr(config, "instrument", "BTC-PERPETUAL")
        self.funding_threshold = getattr(config, "funding_threshold", 0.0001)
        self.sma_h = getattr(config, "sma_h", 48)
        self.atr_period = getattr(config, "atr_period", 14)
        self.sl_atr_mult = getattr(config, "sl_atr_mult", 2.0)
        self.tp_rr = getattr(config, "tp_rr", 2.0)
        self.max_hold_hours = getattr(config, "max_hold_hours", 24)
        self.cooldown_hours = getattr(config, "cooldown_hours", 8)
        # Macro gate: daily close < SMA200d AND SMA200d declining vs slope_days
        # ago. Without it FS bleeds in bull phases and trend transitions.
        self.macro_sma_days = getattr(config, "macro_sma_days", 200)
        self.slope_days = getattr(config, "slope_days", 30)
        # Enter only shortly after a funding settlement (00/08/16 UTC) —
        # the timing the edge was validated on.
        self.entry_window_min = getattr(config, "entry_window_min", 60)

        self._last_entry_ts_ms: Optional[int] = None
        self._open_trade: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # BaseStrategy interface
    # ------------------------------------------------------------------

    def scan(self) -> List[Dict[str, Any]]:
        signals: List[Dict[str, Any]] = []
        try:
            regime_str = self._current_regime()
            if self.scoring_engine:
                allowed, reason = self.scoring_engine.should_trade(
                    self.__class__.__name__, regime_str)
                if not allowed:
                    self.logger.debug(f"[FundingSqueeze] blocked by scoring: {reason}")
                    return []

            if self._open_trade is not None:
                return []

            now_ms = self.kline_provider.now_ms()
            if (self._last_entry_ts_ms is not None and
                    now_ms - self._last_entry_ts_ms <
                    self.cooldown_hours * 3600 * 1000):
                return []  # one trade per funding window

            # Funding settles every 8h at 00/08/16 UTC (epoch-aligned):
            # only enter within entry_window_min after a settlement.
            mins_since_settlement = (now_ms // 60_000) % (8 * 60)
            if mins_since_settlement > self.entry_window_min:
                return []

            funding = self.kline_provider.get_funding_rate(self.symbol)
            if funding is None or funding < self.funding_threshold:
                return []

            if not self._macro_bear_accelerating():
                return []  # deep-bear specialist: stand aside otherwise

            n_bars = self.sma_h + self.atr_period + 2
            candles = self.kline_provider.get_klines(self.symbol, "1h", n_bars)
            if len(candles) < self.sma_h + 1:
                return []

            close = candles[-1]["close"]
            sma = sum(c["close"] for c in candles[-self.sma_h:]) / self.sma_h
            atr = self._atr(candles)
            if close <= 0 or atr <= 0:
                return []

            if close >= sma:
                self._log_blocked("price_above_trend", "SELL", close,
                                  close + self.sl_atr_mult * atr,
                                  close - atr, regime_str)
                return []

            sl = close + self.sl_atr_mult * atr
            risk = sl - close
            tp = close - risk * self.tp_rr if self.tp_rr > 0 else 0
            signals.append({
                "strategy": self.name,
                "type": "FundingSqueeze",
                "direction": "SELL",
                "price": close,
                "stop_loss": sl,
                "take_profit": tp,
                "instrument": self.instrument,
                "symbol": self.symbol,
                "regime": regime_str,
                "funding_rate": funding,
                "max_hold_min": self.max_hold_hours * 60,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            self.logger.info(
                f"[FundingSqueeze] SHORT @ {close:.2f} funding={funding*100:.4f}% "
                f"sma={sma:.2f} SL={sl:.2f} hold<={self.max_hold_hours}h"
            )
        except Exception as e:
            self.logger.error(f"[FundingSqueeze] scan error: {e}", exc_info=True)
        return signals

    def execute_entry(self, signal: Dict[str, Any]) -> bool:
        try:
            if not self.order_manager:
                return False
            sl_distance = abs(signal["price"] - signal["stop_loss"])
            quantity = self._compute_quantity(signal["price"], sl_distance)
            if quantity <= 0:
                return False
            signal["_qty_usd"] = quantity

            success, msg = self.order_manager.execute_generic_trade(
                instrument_name=self.instrument,
                direction="sell",
                quantity=quantity,
                entry_type="limit",
                price=signal["price"],
                stop_loss=signal["stop_loss"],
                take_profit=signal["take_profit"] or None,
                label="fs_sell",
            )
            if success:
                now_ms = self.kline_provider.now_ms()
                self._last_entry_ts_ms = now_ms
                self._open_trade = {
                    "entry_ts_ms": now_ms,
                    "direction": "sell",
                    "quantity": quantity,
                    "entry_price": signal["price"],
                }
                self._log_executed("SELL", signal["price"], signal["stop_loss"],
                                   signal["price"], signal.get("regime", "UNKNOWN"))
            return success
        except Exception as e:
            self.logger.error(f"[FundingSqueeze] execute error: {e}", exc_info=True)
            return False

    def manage_positions(self) -> Dict[str, Any]:
        """Time exit after max_hold_hours (no TP — the winner is the drift)."""
        stats = {"strategy": self.name, "time_exits": 0, "state": "idle"}
        try:
            if self._open_trade is None:
                return stats

            if self._venue_position_flat():
                self._open_trade = None
                stats["state"] = "closed_by_sl"
                return stats

            held_ms = self.kline_provider.now_ms() - self._open_trade["entry_ts_ms"]
            if held_ms >= self.max_hold_hours * 3600 * 1000:
                if self._close_open_trade():
                    stats["time_exits"] = 1
                    stats["state"] = "time_exit"
            else:
                stats["state"] = "holding"
        except Exception as e:
            self.logger.error(f"[FundingSqueeze] manage error: {e}", exc_info=True)
        return stats

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _macro_bear_accelerating(self) -> bool:
        """True if daily close < SMA(macro_sma_days) AND that SMA is lower
        than it was slope_days ago (downtrend in force, not a shallow dip)."""
        try:
            need = self.macro_sma_days + self.slope_days + 2
            daily = self.kline_provider.get_klines(self.symbol, "1d", need)
            if len(daily) < self.macro_sma_days + self.slope_days:
                return False
            closes = [c["close"] for c in daily]
            sma_now = sum(closes[-self.macro_sma_days:]) / self.macro_sma_days
            past = closes[-(self.macro_sma_days + self.slope_days):-self.slope_days]
            sma_past = sum(past) / len(past)
            return closes[-1] < sma_now and sma_now < sma_past
        except Exception as e:
            self.logger.warning(f"[FundingSqueeze] macro filter error: {e}")
            return False

    def _venue_position_flat(self) -> bool:
        try:
            if self.order_manager and hasattr(self.order_manager, "get_position_details"):
                pos = self.order_manager.get_position_details(
                    self.instrument, self.instrument.split("-")[0])
                if pos is not None:
                    return abs(pos.get("size", 0)) < 1e-9
        except Exception:
            pass
        return False

    def _close_open_trade(self) -> bool:
        t = self._open_trade
        try:
            order = self.client.buy(self.instrument, t["quantity"], type="market",
                                    label="fs_time_exit", reduce_only=True)
            if order and "error" not in order:
                self.logger.info(
                    f"[FundingSqueeze] time exit after {self.max_hold_hours}h: "
                    f"buy {t['quantity']} {self.instrument}")
                self._open_trade = None
                return True
            self.logger.error(f"[FundingSqueeze] time exit failed: {order}")
        except Exception as e:
            self.logger.error(f"[FundingSqueeze] time exit error: {e}", exc_info=True)
        return False

    def _current_regime(self) -> str:
        if self.regime_detector:
            r = self.regime_detector.get_last_regime(self.symbol)
            if r:
                return r.regime.value
        return "UNKNOWN"

    def _atr(self, candles: List[Dict]) -> float:
        n = self.atr_period
        if len(candles) < n + 1:
            return 0.0
        trs = []
        for i in range(len(candles) - n, len(candles)):
            c, p = candles[i], candles[i - 1]
            trs.append(max(c["high"] - c["low"],
                           abs(c["high"] - p["close"]),
                           abs(c["low"] - p["close"])))
        return sum(trs) / len(trs)

    def _compute_quantity(self, price: float, sl_distance: float) -> float:
        if not self.risk_manager or sl_distance <= 0:
            return 10
        try:
            result = self.risk_manager.calculate_dynamic_size(
                instrument_name=self.instrument,
                entry_price=price,
                sl_price=price - sl_distance,
                atr_percentile=50.0,
                regime="TREND_DOWN",
                model_winrate=0.45,
            )
            qty_usd = result.get("quantity_usd", 10.0)
            return max(10, int(qty_usd / 10) * 10)
        except Exception:
            return 10
