#!/usr/bin/env python3
"""
Event-driven backtest of the REAL strategy classes (TrendBreakdown,
FundingSqueeze) on the 4-year multi-cycle dataset (bear 2022, bull
2023-2025, bear 2025-2026).

Unlike the vectorized prototypes, this drives the actual src/strategies code
through an injected HistoricalKlineProvider (1h + daily klines + funding),
validating that the implementation reproduces the researched edge:
  - scan() is called once per closed 1h bar (signals only change per bar)
  - entries fill at the next 1m open + slippage
  - SL/TP checked intrabar on 1m highs/lows (SL priority)
  - time exit when the signal's max_hold_min elapses

Usage: python scripts/backtest_new_strategies.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategy_lab import TAKER_FEE, SLIPPAGE
from multicycle_research import (load_4y, load_funding_4y, resample,
                                 compute_phase, phase_report)
from src.strategies.trend_breakdown import TrendBreakdownStrategy
from src.strategies.funding_squeeze import FundingSqueezeStrategy
from config import TrendBreakdownConfig, FundingSqueezeConfig


class HistoricalKlineProvider:
    """Serves closed 1h/1d bars + funding as of an advancing simulation clock."""

    def __init__(self, h1_candles, d1_candles, funding: pd.Series):
        self.frames = {"1h": h1_candles, "1d": d1_candles}
        self.close_ts = {
            k: np.array([c["close_ts_ms"] for c in v]) for k, v in self.frames.items()
        }
        self.funding_ts = funding.index.view("int64") // 10**6
        self.funding_rates = funding.values
        self.current_ms = 0

    def get_klines(self, symbol, interval="1h", limit=60):
        frame = self.frames.get(interval)
        if frame is None:
            return []
        i = int(np.searchsorted(self.close_ts[interval], self.current_ms, side="right"))
        return frame[max(0, i - limit):i]

    def get_funding_rate(self, symbol):
        i = int(np.searchsorted(self.funding_ts, self.current_ms, side="right"))
        return float(self.funding_rates[i - 1]) if i > 0 else None

    def now_ms(self):
        return self.current_ms


def build_candles(frame: pd.DataFrame, interval_ms: int):
    candles = []
    for ts, row in frame.iterrows():
        ts_ms = int(ts.value // 10**6)
        candles.append({
            "ts_ms": ts_ms,
            "open": row["open"], "high": row["high"],
            "low": row["low"], "close": row["close"],
            "volume": row["vol"], "buy_volume": row["buy_vol"],
            "buy_ratio": row["buy_ratio"],
            "close_ts_ms": ts_ms + interval_ms,
        })
    return candles


def run(strategy_cls, config, m1, provider, scan_every_min=60):
    deps = {
        "order_manager": None, "position_monitor": None, "risk_manager": None,
        "orderflow_engine": None, "regime_detector": None, "scoring_engine": None,
        "kline_provider": provider, "signal_log": None,
    }
    strategy = strategy_cls(client=None, config=config, dependencies=deps)

    ts_arr = m1.index.view("int64") // 10**6
    opens = m1["open"].values
    highs = m1["high"].values
    lows = m1["low"].values
    closes = m1["close"].values
    n = len(m1)

    open_tr = None
    trades = []

    for i in range(n):
        bar_close_ms = int(ts_arr[i]) + 60_000
        provider.current_ms = bar_close_ms

        # ---- manage open trade on this bar ----
        if open_tr is not None:
            d = open_tr["d"]
            exit_price, reason = None, None
            if d < 0:
                if highs[i] >= open_tr["sl"]:
                    exit_price, reason = open_tr["sl"], "sl"
                elif open_tr["tp"] > 0 and lows[i] <= open_tr["tp"]:
                    exit_price, reason = open_tr["tp"], "tp"
            else:
                if lows[i] <= open_tr["sl"]:
                    exit_price, reason = open_tr["sl"], "sl"
                elif open_tr["tp"] > 0 and highs[i] >= open_tr["tp"]:
                    exit_price, reason = open_tr["tp"], "tp"
            if exit_price is None and \
                    bar_close_ms - open_tr["entry_ms"] >= open_tr["max_hold_min"] * 60_000:
                exit_price, reason = closes[i], "time"
            if exit_price is not None:
                exit_price *= (1 - d * SLIPPAGE)
                gross = d * (exit_price - open_tr["entry"]) / open_tr["entry"]
                net = gross - 2 * TAKER_FEE
                risk = abs(open_tr["entry"] - open_tr["sl"])
                trades.append({
                    "entry_ts": pd.Timestamp(open_tr["entry_ms"], unit="ms", tz="UTC"),
                    "exit_ts": pd.Timestamp(bar_close_ms, unit="ms", tz="UTC"),
                    "direction": d, "entry": open_tr["entry"], "exit": exit_price,
                    "reason": reason, "gross_pct": gross * 100, "net_pct": net * 100,
                    "r": d * (exit_price - open_tr["entry"]) / risk if risk > 0 else 0,
                    "hold_min": (bar_close_ms - open_tr["entry_ms"]) / 60_000,
                    "sl_dist_pct": risk / open_tr["entry"] * 100,
                })
                open_tr = None
                strategy._open_trade = None   # sync internal state (SL/TP fill)

        # ---- scan once per closed 1h bar ----
        if open_tr is None and (bar_close_ms % (scan_every_min * 60_000) == 0) \
                and i + 1 < n:
            signals = strategy.scan()
            if signals:
                sig = signals[0]
                d = -1 if sig["direction"] == "SELL" else 1
                entry = opens[i + 1] * (1 + d * SLIPPAGE)
                entry_ms = int(ts_arr[i + 1])
                open_tr = {
                    "d": d, "entry": entry, "entry_ms": entry_ms,
                    "sl": sig["stop_loss"], "tp": sig.get("take_profit") or 0,
                    "max_hold_min": sig.get("max_hold_min", 24 * 60),
                }
                # mirror execute_entry() bookkeeping
                strategy._open_trade = {
                    "entry_ts_ms": entry_ms, "quantity": 10,
                    "direction": "sell" if d < 0 else "buy", "entry_price": entry,
                    "max_hold_min": open_tr["max_hold_min"],
                }
                if hasattr(strategy, "_last_entry_ts_ms"):
                    strategy._last_entry_ts_ms = entry_ms

    return pd.DataFrame(trades)


def main():
    print("Loading 4y dataset...")
    m1 = load_4y()
    bull_daily = compute_phase(m1)
    print(f"Data: {m1.index[0]:%Y-%m-%d} -> {m1.index[-1]:%Y-%m-%d}  "
          f"({len(m1):,} 1m bars)")

    h1 = resample(m1, "1h")
    d1 = resample(m1, "1D")
    h1_candles = build_candles(h1, 3_600_000)
    d1_candles = build_candles(d1, 86_400_000)
    funding = load_funding_4y()

    results = {}
    for cls, cfg in [
        (TrendBreakdownStrategy, TrendBreakdownConfig(name="Trend Breakdown")),
        (FundingSqueezeStrategy, FundingSqueezeConfig(name="Funding Squeeze")),
    ]:
        provider = HistoricalKlineProvider(h1_candles, d1_candles, funding)
        trades = run(cls, cfg, m1, provider)
        phase_report(trades, bull_daily, cfg.name)
        if len(trades):
            by_dir = trades.groupby("direction")["net_pct"].agg(["count", "mean", "sum"])
            for d, (c, m, s) in by_dir.iterrows():
                side = "LONG" if d > 0 else "SHORT"
                print(f"  {side}: N={int(c)}  avg={m*100:+.1f}bps  sum={s:+.1f}%")
        results[cfg.name] = trades

    print("\n--- COMBINED (TB+FS) ---")
    all_t = pd.concat(results.values()).sort_values("entry_ts")
    phase_report(all_t, bull_daily, "Portfolio TB+FS")

    out = {name: {
        "n": len(t),
        "avg_net_bps": round(float(t["net_pct"].mean() * 100), 1) if len(t) else 0,
        "wr": round(float((t["net_pct"] > 0).mean() * 100), 1) if len(t) else 0,
    } for name, t in results.items()}
    with open("data/research/new_strategies_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print("\nSaved data/research/new_strategies_results.json")


if __name__ == "__main__":
    main()
