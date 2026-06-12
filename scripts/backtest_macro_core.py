#!/usr/bin/env python3
"""
Event-driven backtest of the REAL MacroCoreStrategy class on the 4-year
dataset, driving scan() AND manage_positions() (chandelier exit) through an
injected HistoricalKlineProvider and a fake execution client.

Mechanics:
  - scan() once per closed daily bar; entry at next 1m open + slippage
  - manage_positions() once per closed daily bar -> chandelier exit at
    next 1m open (the real strategy code decides, not the harness)
  - disaster SL checked intrabar on 1m lows
  - equity marked-to-market daily for honest maxDD (positions last months)

Usage: python scripts/backtest_macro_core.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategy_lab import TAKER_FEE, SLIPPAGE
from multicycle_research import load_4y, resample
from backtest_new_strategies import HistoricalKlineProvider, build_candles
from src.strategies.macro_core import MacroCoreStrategy
from config import MacroCoreConfig


class FakeExecClient:
    """Records reduce-only exits issued by the real strategy code."""
    def __init__(self):
        self.exit_requested = False

    def sell(self, *a, **k):
        self.exit_requested = True
        return {"order_id": "sim"}

    def buy(self, *a, **k):
        return {"order_id": "sim"}


def main():
    print("Loading 4y dataset...")
    m1 = load_4y()
    h1 = resample(m1, "1h")
    d1 = resample(m1, "1D")
    provider = HistoricalKlineProvider(
        build_candles(h1, 3_600_000), build_candles(d1, 86_400_000),
        pd.Series([0.0], index=[m1.index[0]]),
    )

    cfg = MacroCoreConfig(name="Macro Core", persist_state=False)
    fake_client = FakeExecClient()
    deps = {k: None for k in ["order_manager", "position_monitor", "risk_manager",
                              "orderflow_engine", "regime_detector",
                              "scoring_engine", "signal_log"]}
    deps["kline_provider"] = provider
    strategy = MacroCoreStrategy(client=fake_client, config=cfg, dependencies=deps)

    ts_arr = m1.index.view("int64") // 10**6
    opens = m1["open"].values
    lows = m1["low"].values
    closes = m1["close"].values
    n = len(m1)

    open_tr = None
    pending_action = None     # "enter" | "exit" to execute at next 1m open
    pending_sig = None
    trades = []
    equity = 1.0
    eq_curve = []             # (ts, mtm equity) sampled daily

    for i in range(n):
        bar_close_ms = int(ts_arr[i]) + 60_000
        provider.current_ms = bar_close_ms

        # ---- execute pending action at this bar's open ----
        if pending_action == "enter":
            entry = opens[i] * (1 + SLIPPAGE)
            open_tr = {
                "entry": entry, "entry_ms": int(ts_arr[i]),
                "sl": pending_sig["stop_loss"],
                "bar_ts_ms": pending_sig["bar_ts_ms"],
            }
            strategy._open_trade = {
                "entry_ts_ms": int(ts_arr[i]),
                "entry_bar_ts_ms": pending_sig["bar_ts_ms"],
                "direction": "buy", "quantity": 10, "entry_price": entry,
            }
            pending_action, pending_sig = None, None
        elif pending_action == "exit" and open_tr is not None:
            exit_price = opens[i] * (1 - SLIPPAGE)
            net = (exit_price - open_tr["entry"]) / open_tr["entry"] - 2 * TAKER_FEE
            trades.append({
                "entry_ts": pd.Timestamp(open_tr["entry_ms"], unit="ms", tz="UTC"),
                "exit_ts": pd.Timestamp(int(ts_arr[i]), unit="ms", tz="UTC"),
                "net_pct": net * 100, "reason": "chandelier",
            })
            equity *= (1 + net)
            open_tr = None
            pending_action = None

        # ---- disaster SL intrabar ----
        if open_tr is not None and lows[i] <= open_tr["sl"]:
            exit_price = open_tr["sl"] * (1 - SLIPPAGE)
            net = (exit_price - open_tr["entry"]) / open_tr["entry"] - 2 * TAKER_FEE
            trades.append({
                "entry_ts": pd.Timestamp(open_tr["entry_ms"], unit="ms", tz="UTC"),
                "exit_ts": pd.Timestamp(bar_close_ms, unit="ms", tz="UTC"),
                "net_pct": net * 100, "reason": "disaster_sl",
            })
            equity *= (1 + net)
            open_tr = None
            strategy._open_trade = None

        # ---- daily boundary: real strategy logic ----
        if bar_close_ms % 86_400_000 == 0:
            # mark-to-market equity
            mtm = equity
            if open_tr is not None:
                mtm *= (closes[i] / open_tr["entry"])
            eq_curve.append((bar_close_ms, mtm))

            if open_tr is not None:
                fake_client.exit_requested = False
                stats = strategy.manage_positions()
                if fake_client.exit_requested or stats.get("exits"):
                    pending_action = "exit"
            else:
                signals = strategy.scan()
                if signals:
                    pending_sig = signals[0]
                    pending_action = "enter"

    # close residual open trade at the end
    if open_tr is not None:
        exit_price = closes[-1] * (1 - SLIPPAGE)
        net = (exit_price - open_tr["entry"]) / open_tr["entry"] - 2 * TAKER_FEE
        trades.append({
            "entry_ts": pd.Timestamp(open_tr["entry_ms"], unit="ms", tz="UTC"),
            "exit_ts": m1.index[-1], "net_pct": net * 100, "reason": "end_of_data",
        })
        equity *= (1 + net)

    t = pd.DataFrame(trades)
    eq = pd.Series([e for _, e in eq_curve],
                   index=pd.to_datetime([ts for ts, _ in eq_curve], unit="ms", utc=True))
    peak = eq.cummax()
    mdd = ((peak - eq) / peak).max() * 100

    bh = m1["close"].iloc[-1] / m1["close"].iloc[0] - 1
    print(f"\n=== MACRO CORE — codice reale, 4 anni ===")
    print(f"  Trade:    {len(t)}")
    print(f"  Equity:   {(equity-1)*100:+.1f}%   (buy&hold {bh*100:+.1f}%)")
    print(f"  maxDD:    {mdd:.1f}%  (mark-to-market giornaliero)")
    if len(t):
        wr = (t["net_pct"] > 0).mean() * 100
        print(f"  WR:       {wr:.0f}%   avg/trade: {t['net_pct'].mean():+.2f}%")
        print(f"  exits:    {t['reason'].value_counts().to_dict()}")
        yearly = eq.resample("YE").last() / eq.resample("YE").first() - 1
        print("  per anno: " + "  ".join(f"{idx.year}:{v*100:+.0f}%"
                                          for idx, v in yearly.items()))
        print("\n  Trade list:")
        for _, r in t.iterrows():
            print(f"    {r['entry_ts']:%Y-%m-%d} -> {r['exit_ts']:%Y-%m-%d}  "
                  f"{r['net_pct']:+7.2f}%  ({r['reason']})")


if __name__ == "__main__":
    main()
