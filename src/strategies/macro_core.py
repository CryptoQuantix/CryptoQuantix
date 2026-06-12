"""
MacroCoreStrategy — core long exposure while the macro trend is up.

C1 of microevolutive/PLAN_BULL_EVOLUTION.md.

Quantitative basis (4y BTCUSDT daily, Jun 2022 - Jun 2026, costs 0.10%/side):
  - Entry: daily close > SMA200d. Exit: chandelier — daily close below
    (max close since entry - 5 * ATR20d).
  - +315% vs +136% buy&hold, maxDD 24.8%, 9 trades, 2023 +109%, 2024 +102%,
    2025 -1% (the chandelier exits the blow-off top ~5 ATR below the peak,
    long before the SMA200 cross that cost -17% to the naive version).
  - Robust plateau: k in [4.5, 6] all > +314%; k=5 has the best DD profile.
  - Low trade count is inherent: this is a regime-following CORE position
    (holds for months), not a tactical strategy.

Mechanics:
  - scan() evaluates once per CLOSED daily bar; one position at a time.
  - Disaster stop on the venue at entry*(1 - disaster_sl_pct): protects a
    crash while the bot is down. The real exit is the chandelier, evaluated
    in manage_positions() on each new daily close.
  - STATE PERSISTENCE: the position lives for months across restarts —
    state is saved to JSON and reconciled with the venue at startup.

Data: daily klines via KlineProvider (injectable -> identical code in
backtest, see scripts/backtest_macro_core.py).
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class MacroCoreStrategy(BaseStrategy):
    """Macro trend-following core: long above SMA200d, chandelier exit."""

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
        self.sma_days = getattr(config, "sma_days", 200)
        self.atr_days = getattr(config, "atr_days", 20)
        self.chandelier_k = getattr(config, "chandelier_k", 5.0)
        self.disaster_sl_pct = getattr(config, "disaster_sl_pct", 0.25)
        self.exposure_fraction = getattr(config, "exposure_fraction", 1.0)
        # C4 equity sim: vol-target 30% migliora il Calmar in ogni config
        # (DD portafoglio 29.6% -> 21.5%, peggior anno -> 0%). 0 = disattivo.
        self.vol_target = getattr(config, "vol_target", 0.30)
        self.vol_lookback_days = getattr(config, "vol_lookback_days", 30)
        self.expo_step = getattr(config, "expo_step", 0.25)
        self.state_path = getattr(config, "state_path", "data/macro_core_state.json")
        self.persist_state = getattr(config, "persist_state", True)

        self._last_signal_bar_ts: Optional[int] = None
        self._last_exit_check_ts: Optional[int] = None
        self._open_trade: Optional[Dict[str, Any]] = None
        self._load_state()

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
                    self.logger.debug(f"[MacroCore] blocked by scoring: {reason}")
                    return []

            if self._open_trade is not None:
                return []

            daily = self._daily_candles()
            if daily is None:
                return []
            last = daily[-1]
            if self._last_signal_bar_ts == last["ts_ms"]:
                return []  # already evaluated this daily bar

            close = last["close"]
            sma = sum(c["close"] for c in daily[-self.sma_days:]) / self.sma_days
            if close <= 0 or close <= sma:
                return []

            sl = close * (1 - self.disaster_sl_pct)
            signals.append({
                "strategy": self.name,
                "type": "MacroCore",
                "direction": "BUY",
                "price": close,
                "stop_loss": sl,                  # disaster stop only
                "take_profit": 0,                 # exit = chandelier
                "instrument": self.instrument,
                "symbol": self.symbol,
                "regime": regime_str,
                "bar_ts_ms": last["ts_ms"],
                "sma200d": sma,
                "max_hold_min": 365 * 1440,       # no time exit
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            self._last_signal_bar_ts = last["ts_ms"]
            self.logger.info(
                f"[MacroCore] LONG @ {close:.2f} (SMA200d={sma:.2f}) "
                f"disaster_SL={sl:.2f} chandelier_k={self.chandelier_k}"
            )
        except Exception as e:
            self.logger.error(f"[MacroCore] scan error: {e}", exc_info=True)
        return signals

    def execute_entry(self, signal: Dict[str, Any]) -> bool:
        try:
            if not self.order_manager:
                return False
            expo = self._target_exposure()
            quantity = self._compute_quantity(signal["price"], expo)
            if quantity <= 0:
                return False
            signal["_qty_usd"] = quantity

            success, msg = self.order_manager.execute_generic_trade(
                instrument_name=self.instrument,
                direction="buy",
                quantity=quantity,
                entry_type="limit",
                price=signal["price"],
                stop_loss=signal["stop_loss"],
                take_profit=None,
                label="mc_buy",
            )
            if success:
                self._open_trade = {
                    "entry_ts_ms": self.kline_provider.now_ms(),
                    "entry_bar_ts_ms": signal["bar_ts_ms"],
                    "direction": "buy",
                    "quantity": quantity,
                    "entry_price": signal["price"],
                    "exposure": expo,
                }
                self._save_state()
                self._log_executed("BUY", signal["price"], signal["stop_loss"],
                                   signal["price"], signal.get("regime", "UNKNOWN"))
            return success
        except Exception as e:
            self.logger.error(f"[MacroCore] execute error: {e}", exc_info=True)
            return False

    def manage_positions(self) -> Dict[str, Any]:
        """Chandelier exit, evaluated once per new CLOSED daily bar."""
        stats = {"strategy": self.name, "exits": 0, "state": "idle"}
        try:
            if self._open_trade is None:
                return stats

            # Disaster SL (or manual close) already flattened the position?
            if self._venue_position_flat():
                self.logger.info("[MacroCore] position closed on venue — state reset")
                self._open_trade = None
                self._save_state()
                stats["state"] = "closed_on_venue"
                return stats

            daily = self._daily_candles()
            if daily is None:
                stats["state"] = "holding"
                return stats
            last = daily[-1]
            if self._last_exit_check_ts == last["ts_ms"]:
                stats["state"] = "holding"
                return stats  # this daily bar already evaluated
            self._last_exit_check_ts = last["ts_ms"]

            if self._chandelier_exit(daily):
                if self._close_open_trade():
                    stats["exits"] = 1
                    stats["state"] = "chandelier_exit"
                    return stats

            # Vol-target rebalance (daily, quantized: orders only when the
            # exposure bucket actually changes — churn stays minimal)
            rebalanced = self._rebalance_exposure()
            stats["state"] = "rebalanced" if rebalanced else "holding"
        except Exception as e:
            self.logger.error(f"[MacroCore] manage error: {e}", exc_info=True)
        return stats

    # ------------------------------------------------------------------
    # Exit logic (shared live/backtest through manage_positions)
    # ------------------------------------------------------------------

    def _chandelier_exit(self, daily: List[Dict]) -> bool:
        """True when last close < (max close since entry - k * ATR20d)."""
        entry_bar_ts = self._open_trade.get("entry_bar_ts_ms", 0)
        closes_since = [c["close"] for c in daily if c["ts_ms"] >= entry_bar_ts]
        if not closes_since:
            return False
        max_close = max(max(closes_since), self._open_trade["entry_price"])
        atr = self._atr_daily(daily)
        if atr <= 0:
            return False
        threshold = max_close - self.chandelier_k * atr
        last_close = daily[-1]["close"]
        if last_close < threshold:
            self.logger.info(
                f"[MacroCore] chandelier exit: close {last_close:.2f} < "
                f"{threshold:.2f} (max={max_close:.2f}, ATR={atr:.2f})")
            return True
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _daily_candles(self) -> Optional[List[Dict]]:
        n = self.sma_days + self.atr_days + 5
        daily = self.kline_provider.get_klines(self.symbol, "1d", n)
        if len(daily) < self.sma_days + 1:
            return None
        return daily

    def _atr_daily(self, daily: List[Dict]) -> float:
        n = self.atr_days
        if len(daily) < n + 1:
            return 0.0
        trs = []
        for i in range(len(daily) - n, len(daily)):
            c, p = daily[i], daily[i - 1]
            trs.append(max(c["high"] - c["low"],
                           abs(c["high"] - p["close"]),
                           abs(c["low"] - p["close"])))
        return sum(trs) / len(trs)

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
            order = self.client.sell(self.instrument, t["quantity"], type="market",
                                     label="mc_exit", reduce_only=True)
            if order and "error" not in order:
                self.logger.info(f"[MacroCore] exit: sell {t['quantity']} {self.instrument}")
                self._open_trade = None
                self._save_state()
                return True
            self.logger.error(f"[MacroCore] exit failed: {order}")
        except Exception as e:
            self.logger.error(f"[MacroCore] exit error: {e}", exc_info=True)
        return False

    def _current_regime(self) -> str:
        if self.regime_detector:
            r = self.regime_detector.get_last_regime(self.symbol)
            if r:
                return r.regime.value
        return "UNKNOWN"

    def _target_exposure(self) -> float:
        """Vol-targeted exposure in [expo_step, 1], quantized to expo_step.
        expo = clip(vol_target / realized_vol_30d, 0, 1). 1.0 if disabled."""
        if self.vol_target <= 0:
            return 1.0
        try:
            daily = self.kline_provider.get_klines(
                self.symbol, "1d", self.vol_lookback_days + 2)
            if len(daily) < self.vol_lookback_days + 1:
                return 1.0
            closes = [c["close"] for c in daily[-(self.vol_lookback_days + 1):]]
            rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
            realized = (var ** 0.5) * (365 ** 0.5)
            if realized <= 0:
                return 1.0
            expo = min(1.0, self.vol_target / realized)
            expo = round(expo / self.expo_step) * self.expo_step
            return max(self.expo_step, expo)
        except Exception as e:
            self.logger.warning(f"[MacroCore] vol target error: {e}")
            return 1.0

    def _rebalance_exposure(self) -> bool:
        """Adjust position size to the current vol-target bucket (daily).
        Returns True if an adjustment order was sent."""
        if self.vol_target <= 0 or self._open_trade is None:
            return False
        target = self._target_exposure()
        current = self._open_trade.get("exposure", 1.0)
        if abs(target - current) < self.expo_step:
            return False
        equity = self._equity()
        target_qty = max(10, int(equity * self.exposure_fraction * target / 10) * 10)
        current_qty = self._open_trade["quantity"]
        delta = target_qty - current_qty
        if abs(delta) < 10:
            return False
        try:
            if delta > 0:
                order = self.client.buy(self.instrument, delta, type="market",
                                        label="mc_rebal_up")
            else:
                order = self.client.sell(self.instrument, -delta, type="market",
                                         label="mc_rebal_down", reduce_only=True)
            if order and "error" not in order:
                self.logger.info(
                    f"[MacroCore] rebalance {current:.2f} -> {target:.2f} "
                    f"({'buy' if delta > 0 else 'sell'} {abs(delta)} USD)")
                self._open_trade["quantity"] = target_qty
                self._open_trade["exposure"] = target
                self._save_state()
                return True
            self.logger.error(f"[MacroCore] rebalance failed: {order}")
        except Exception as e:
            self.logger.error(f"[MacroCore] rebalance error: {e}", exc_info=True)
        return False

    def _equity(self) -> float:
        equity = 10_000.0
        try:
            if self.risk_manager and hasattr(self.risk_manager, "get_risk_summary"):
                summary = self.risk_manager.get_risk_summary()
                equity = float(summary.get("equity", equity))
        except Exception:
            pass
        return equity

    def _compute_quantity(self, price: float, expo: float = 1.0) -> float:
        """Core size = equity * exposure_fraction * vol-target expo (step 10)."""
        qty_usd = self._equity() * self.exposure_fraction * expo
        return max(10, int(qty_usd / 10) * 10)

    # ------------------------------------------------------------------
    # State persistence (position lives for months across restarts)
    # ------------------------------------------------------------------

    def _save_state(self):
        if not self.persist_state:
            return
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            with open(self.state_path, "w") as f:
                json.dump({"open_trade": self._open_trade}, f, indent=2)
        except Exception as e:
            self.logger.warning(f"[MacroCore] state save failed: {e}")

    def _load_state(self):
        if not self.persist_state:
            return
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path) as f:
                    data = json.load(f)
                self._open_trade = data.get("open_trade")
                if self._open_trade:
                    self.logger.info(
                        f"[MacroCore] state restored: {self._open_trade['direction']} "
                        f"{self._open_trade['quantity']} @ "
                        f"{self._open_trade['entry_price']:.2f} "
                        f"(reconciled with venue at first manage_positions)")
        except Exception as e:
            self.logger.warning(f"[MacroCore] state load failed: {e}")
            self._open_trade = None
