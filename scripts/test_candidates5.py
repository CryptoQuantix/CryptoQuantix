#!/usr/bin/env python3
"""
Round 5 — fixing FundingSqueeze across the cycle.

Problem: with the simple macro gate (close < SMA200d) FS loses in the
shallow bear-dips of bull years (2024 -11%, 2025 -19%) and only wins in
deep bears (2022 +12%, 2026 +38%).

Variants tested (entries at funding settlement events, vectorized):
  A. close < SMA200d                      (current)
  B. A + SMA200d slope negative (30d)
  C. close < 0.95 * SMA200d               (5% below)
  D. SMA50d < SMA200d (death cross)
Each also tested with funding-event-only timing vs continuous entry.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

from strategy_lab import simulate, atr
from multicycle_research import (load_4y, load_funding_4y, resample,
                                 compute_phase, phase_report)


def main():
    m1 = load_4y()
    bull_daily = compute_phase(m1)
    h1 = resample(m1, "1h")
    atr1h = atr(h1, 14)
    fr = load_funding_4y()

    d1 = m1["close"].resample("1D").last().dropna()
    sma200 = d1.rolling(200).mean()
    sma50 = d1.rolling(50).mean()
    # daily values known at next day open (shift 1)
    gA = (d1 < sma200).shift(1)
    gB = ((d1 < sma200) & (sma200 < sma200.shift(30))).shift(1)
    gC = (d1 < sma200 * 0.95).shift(1)
    gD = ((d1 < sma200) & (sma50 < sma200)).shift(1)

    atr_c = atr1h.copy(); atr_c.index = atr_c.index + pd.Timedelta(hours=1)
    px_c = h1["close"].copy(); px_c.index = px_c.index + pd.Timedelta(hours=1)
    sma48 = h1["close"].rolling(48).mean()
    sma_c = sma48.copy(); sma_c.index = sma_c.index + pd.Timedelta(hours=1)

    px_at = px_c.reindex(fr.index, method="ffill")
    sma_at = sma_c.reindex(fr.index, method="ffill")
    atr_at = atr_c.reindex(fr.index, method="ffill")

    base = (fr > 0.00005) & (px_at < sma_at)

    for name, gate_daily in [("A close<SMA200", gA), ("B +slope200dn", gB),
                             ("C close<0.95xSMA200", gC), ("D death-cross", gD)]:
        gate_at = gate_daily.reindex(fr.index.floor("D")).fillna(False)
        gate_at.index = fr.index
        idx = fr[base & gate_at].index
        ev = pd.DataFrame(index=idx)
        ev["direction"] = -1
        ev["sl"] = px_at.loc[idx] + atr_at.loc[idx] * 3.0
        ev["tp"] = 0.0
        ev = ev.dropna()
        tr = simulate(m1, ev, max_hold_min=24 * 60)
        phase_report(tr, bull_daily, f"FS gate {name} (funding-event entry)")


if __name__ == "__main__":
    main()
