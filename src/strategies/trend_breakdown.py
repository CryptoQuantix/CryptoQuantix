"""
TrendBreakdownStrategy — two-sided trend strategy, macro-phase gated.

Quantitative basis (4 years BTCUSDT 1m, Jun 2022 - Jun 2026, covering the
2022 bear, the 2023-2025 bull and the 2025-2026 bear; costs 0.20% roundtrip,
no lookahead):

  SHORT (breakdown of the 48h low in macro BEAR):
    - Without macro gate: -24bps/trade in bull phases (bleed), +14bps in bear.
    - With macro gate (daily close < SMA200d): +14.5bps avg, PF 1.15,
      183 trades; on the 2025-26 bear segment alone +50bps/trade PF 1.8
      (validated IS/OOS on the 270d dataset).
  LONG (breakout of the 7-DAY high in macro BULL):
    - +21.9bps avg, PF 1.22, 129 trades (2023 +16%, 2024 +19%, 2025 -8%).
    - Shorter lookbacks (48h) are ~breakeven for longs; pullback-buying and
      3d-momentum longs tested NEGATIVE — only the 168h breakout survives.

  The macro gate (daily close vs SMA200) is what makes the strategy safe
  across cycles: each side is structurally inactive in its adverse phase.

Entry (evaluated once per closed 1h bar):
  SHORT: 1h close < min(low, prev 48 bars)  AND close < SMA48(1h)
         AND bar buy_ratio < flow_confirm   AND macro BEAR
  LONG : 1h close > max(high, prev 168 bars) AND close > SMA48(1h)
         AND bar buy_ratio > 1 - flow_confirm AND macro BULL

Exit:
  SHORT: SL = entry + 2.0*ATR(1h,14), TP = 2R, time exit 24h
  LONG : SL = entry - 2.0*ATR(1h,14), TP = 3R, time exit 48h

Data: 1h + daily klines via KlineProvider (injectable -> identical code in
backtest, see scripts/backtest_new_strategies.py).
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class TrendBreakdownStrategy(BaseStrategy):
    """Macro-gated trend strategy: 48h-low breakdown shorts in macro bear,
    7d-high breakout longs in macro bull."""

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
        self.lookback_h = getattr(config, "lookback_h", 48)
        self.lookback_long_h = getattr(config, "lookback_long_h", 168)
        self.sma_h = getattr(config, "sma_h", 48)
        self.atr_period = getattr(config, "atr_period", 14)
        self.sl_atr_mult = getattr(config, "sl_atr_mult", 2.0)
        self.rr_ratio = getattr(config, "rr_ratio", 2.0)
        self.rr_long = getattr(config, "rr_long", 3.0)
        self.max_hold_hours = getattr(config, "max_hold_hours", 24)
        self.max_hold_long_hours = getattr(config, "max_hold_long_hours", 48)
        self.flow_confirm = getattr(config, "flow_confirm", 0.50)
        self.enable_long = getattr(config, "enable_long", True)
        self.macro_sma_days = getattr(config, "macro_sma_days", 200)

        # One signal per closed 1h bar; one open trade at a time
        self._last_signal_bar_ts: Optional[int] = None
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
                    self.logger.debug(f"[TrendBreakdown] blocked by scoring: {reason}")
                    return []

            if self._open_trade is not None:
                return []  # one position at a time

            macro_bull = self._macro_bull()
            if macro_bull is None:
                return []  # no daily data -> stand aside

            n_bars = max(self.lookback_h, self.lookback_long_h, self.sma_h) \
                + self.atr_period + 2
            candles = self.kline_provider.get_klines(self.symbol, "1h", n_bars)
            if len(candles) < max(self.lookback_h, self.sma_h) + 2:
                return []

            last = candles[-1]
            if self._last_signal_bar_ts == last["ts_ms"]:
                return []  # already evaluated this bar

            closes = [c["close"] for c in candles]
            close = last["close"]
            sma = sum(closes[-self.sma_h:]) / self.sma_h
            atr = self._atr(candles)
            if atr <= 0 or close <= 0:
                return []

            prev_short = candles[-(self.lookback_h + 1):-1]
            breakdown_level = min(c["low"] for c in prev_short)

            # --- SHORT: 48h-low breakdown, only in macro BEAR ---
            if (not macro_bull and close < breakdown_level and close < sma
                    and last["buy_ratio"] < self.flow_confirm):
                sl = close + self.sl_atr_mult * atr
                risk = sl - close
                tp = close - risk * self.rr_ratio if self.rr_ratio > 0 else 0
                signals.append(self._build_signal(
                    "SELL", close, sl, tp, regime_str, last,
                    self.max_hold_hours))
                self.logger.info(
                    f"[TrendBreakdown] SHORT @ {close:.2f} lvl={breakdown_level:.2f} "
                    f"sma={sma:.2f} br={last['buy_ratio']:.3f} SL={sl:.2f} TP={tp:.2f}"
                )

            # --- LONG: 7d-high breakout, only in macro BULL ---
            elif (self.enable_long and macro_bull
                  and len(candles) >= self.lookback_long_h + 2):
                prev_long = candles[-(self.lookback_long_h + 1):-1]
                breakout_level = max(c["high"] for c in prev_long)
                if (close > breakout_level and close > sma
                        and last["buy_ratio"] > (1 - self.flow_confirm)):
                    sl = close - self.sl_atr_mult * atr
                    risk = close - sl
                    # rr_long=0 -> no TP: let winners run until time exit.
                    # 4y validation: noTP/168h doubles the long edge
                    # (+71bps PF 1.56 vs +22bps PF 1.22 with TP 3R/48h).
                    tp = close + risk * self.rr_long if self.rr_long > 0 else 0
                    signals.append(self._build_signal(
                        "BUY", close, sl, tp, regime_str, last,
                        self.max_hold_long_hours))
                    self.logger.info(
                        f"[TrendBreakdown] LONG @ {close:.2f} lvl={breakout_level:.2f} "
                        f"sma={sma:.2f} br={last['buy_ratio']:.3f} SL={sl:.2f} TP={tp:.2f}"
                    )

            if signals:
                self._last_signal_bar_ts = last["ts_ms"]

        except Exception as e:
            self.logger.error(f"[TrendBreakdown] scan error: {e}", exc_info=True)
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
                direction=signal["direction"].lower(),
                quantity=quantity,
                entry_type="limit",
                price=signal["price"],
                stop_loss=signal["stop_loss"],
                take_profit=signal["take_profit"],
                label=f"tb_{signal['direction'].lower()}",
            )
            if success:
                self._open_trade = {
                    "entry_ts_ms": self.kline_provider.now_ms(),
                    "direction": signal["direction"].lower(),
                    "quantity": quantity,
                    "entry_price": signal["price"],
                    "max_hold_min": signal.get("max_hold_min",
                                               self.max_hold_hours * 60),
                }
                self._log_executed(
                    signal["direction"], signal["price"],
                    signal["stop_loss"], signal["take_profit"],
                    signal.get("regime", "UNKNOWN"),
                )
            return success
        except Exception as e:
            self.logger.error(f"[TrendBreakdown] execute error: {e}", exc_info=True)
            return False

    def manage_positions(self) -> Dict[str, Any]:
        """Time-based exit per side (24h short / 48h long). SL/TP fills are
        detected via a flat venue position -> internal state reset."""
        stats = {"strategy": self.name, "time_exits": 0, "state": "idle"}
        try:
            if self._open_trade is None:
                return stats

            if self._venue_position_flat():
                self._open_trade = None
                stats["state"] = "closed_by_sl_tp"
                return stats

            held_ms = self.kline_provider.now_ms() - self._open_trade["entry_ts_ms"]
            max_hold_min = self._open_trade.get("max_hold_min",
                                                self.max_hold_hours * 60)
            if held_ms >= max_hold_min * 60 * 1000:
                if self._close_open_trade():
                    stats["time_exits"] = 1
                    stats["state"] = "time_exit"
            else:
                stats["state"] = "holding"
        except Exception as e:
            self.logger.error(f"[TrendBreakdown] manage error: {e}", exc_info=True)
        return stats

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _macro_bull(self) -> Optional[bool]:
        """True if last CLOSED daily close > SMA(macro_sma_days). None if
        insufficient data (strategy then stands aside)."""
        try:
            daily = self.kline_provider.get_klines(
                self.symbol, "1d", self.macro_sma_days + 2)
            if len(daily) < self.macro_sma_days:
                return None
            closes = [c["close"] for c in daily[-self.macro_sma_days:]]
            sma = sum(closes) / len(closes)
            return daily[-1]["close"] > sma
        except Exception as e:
            self.logger.warning(f"[TrendBreakdown] macro filter error: {e}")
            return None

    def _venue_position_flat(self) -> bool:
        """True if the instrument has no open position on the venue."""
        try:
            if self.order_manager and hasattr(self.order_manager, "get_position_details"):
                pos = self.order_manager.get_position_details(
                    self.instrument, self.instrument.split("-")[0])
                if pos is not None:
                    return abs(pos.get("size", 0)) < 1e-9
        except Exception:
            pass
        return False  # cannot verify -> assume still open

    def _close_open_trade(self) -> bool:
        """Reduce-only market order netting out our quantity (time exit).
        Residual SL/TP orders become orphans -> PositionMonitor cancels them."""
        t = self._open_trade
        try:
            opposite = "sell" if t["direction"] == "buy" else "buy"
            fn = self.client.sell if opposite == "sell" else self.client.buy
            order = fn(self.instrument, t["quantity"], type="market",
                       label="tb_time_exit", reduce_only=True)
            if order and "error" not in order:
                self.logger.info(
                    f"[TrendBreakdown] time exit: {opposite} {t['quantity']} "
                    f"{self.instrument}")
                self._open_trade = None
                return True
            self.logger.error(f"[TrendBreakdown] time exit failed: {order}")
        except Exception as e:
            self.logger.error(f"[TrendBreakdown] time exit error: {e}", exc_info=True)
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

    def _build_signal(self, direction, price, sl, tp, regime_str, bar,
                      max_hold_hours) -> Dict[str, Any]:
        return {
            "strategy": self.name,
            "type": "TrendBreakdown",
            "direction": direction,
            "price": price,
            "stop_loss": sl,
            "take_profit": tp,
            "instrument": self.instrument,
            "symbol": self.symbol,
            "regime": regime_str,
            "bar_ts_ms": bar["ts_ms"],
            "buy_ratio": bar["buy_ratio"],
            "max_hold_min": max_hold_hours * 60,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _compute_quantity(self, price: float, sl_distance: float) -> float:
        # USD amount rounded to Deribit BTC-PERPETUAL step (10 USD)
        if not self.risk_manager or sl_distance <= 0:
            return 10
        try:
            result = self.risk_manager.calculate_dynamic_size(
                instrument_name=self.instrument,
                entry_price=price,
                sl_price=price - sl_distance,
                atr_percentile=50.0,
                regime="TREND_DOWN",
                model_winrate=0.50,
            )
            qty_usd = result.get("quantity_usd", 10.0)
            return max(10, int(qty_usd / 10) * 10)
        except Exception:
            return 10
