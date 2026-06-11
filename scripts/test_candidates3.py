#!/usr/bin/env python3
"""
Round 3 — final configs + monthly breakdown + funding absolute threshold.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
from strategy_lab import (load_1m, load_funding, resample, atr, simulate,
                          report, IS_FRAC)
from test_candidates import make_events


def monthly(trades, label):
    if len(trades) == 0:
        return
    t = trades.copy()
    t["month"] = t["entry_ts"].dt.to_period("M")
    g = t.groupby("month")["net_pct"]
    print(f"  monthly {label}:")
    for m, s in g:
        print(f"    {m}  N={len(s):3d}  sum={s.sum():+6.2f}%  avg={s.mean()*100:+7.1f}bps")


def main():
    m1 = load_1m()
    split_ts = m1.index[int(len(m1) * IS_FRAC)]
    print(f"Data: {m1.index[0]:%Y-%m-%d} -> {m1.index[-1]:%Y-%m-%d}  split {split_ts:%Y-%m-%d}")

    h1 = resample(m1, "1h")
    atr_h1 = atr(h1, 14)
    fr = load_funding()
    print(f"\nFunding distribution: mean={fr.mean():.6f}  q50={fr.quantile(0.5):.6f}  "
          f"q80={fr.quantile(0.8):.6f}  q90={fr.quantile(0.9):.6f}  "
          f"q95={fr.quantile(0.95):.6f}  max={fr.max():.6f}")

    # ---- S1 FINAL: lb=48 sl=2xATR rr=2 hold=24h + flow confirm br<0.50 ----
    print("\n" + "#" * 70)
    print("# S1 FINAL — breakdown short lb=48 sl=2xATR rr=2 hold=24h +flow<0.50")
    print("#" * 70)
    lb = 48
    lo_n = h1["low"].rolling(lb).min().shift(1)
    sma = h1["close"].rolling(lb).mean()
    sig = (h1["close"] < lo_n) & (h1["close"] < sma) & (h1["buy_ratio"] < 0.50)
    ev = make_events(sig, -1, h1["close"], atr_h1 * 2.0, 2.0, 60)
    tr = simulate(m1, ev, max_hold_min=24 * 60)
    report(tr, "S1 FINAL", split_ts)
    monthly(tr, "S1 FINAL")

    # ---- S7: weekly breakdown lb=168 ----
    print("\n" + "#" * 70)
    print("# S7 — weekly breakdown short lb=168")
    print("#" * 70)
    lo_n = h1["low"].rolling(168).min().shift(1)
    sma = h1["close"].rolling(168).mean()
    sig7 = (h1["close"] < lo_n) & (h1["close"] < sma)
    for sl_mult in [2.0, 3.0]:
        for hold_h in [24, 48]:
            ev = make_events(sig7, -1, h1["close"], atr_h1 * sl_mult, 2.0, 60)
            tr = simulate(m1, ev, max_hold_min=hold_h * 60)
            report(tr, f"S7 lb=168 sl={sl_mult} rr=2 hold={hold_h}h", split_ts)

    # ---- S6: funding absolute threshold + trend filter ----
    print("\n" + "#" * 70)
    print("# S6 — funding absolute threshold SHORT (sl=3xATR no-tp hold=24h)")
    print("#" * 70)
    atr_closed = atr_h1.copy(); atr_closed.index = atr_closed.index + pd.Timedelta(hours=1)
    px_closed = h1["close"].copy(); px_closed.index = px_closed.index + pd.Timedelta(hours=1)
    sma_closed = h1["close"].rolling(48).mean()
    sma_closed.index = sma_closed.index + pd.Timedelta(hours=1)

    for ab in [0.00005, 0.0001, 0.0002]:
        for use_trend in [False, True]:
            sig_idx = fr[fr > ab].index
            if use_trend:
                px_at_all = px_closed.reindex(sig_idx, method="ffill")
                sma_at_all = sma_closed.reindex(sig_idx, method="ffill")
                sig_idx = sig_idx[(px_at_all < sma_at_all).values]
            ev = pd.DataFrame(index=sig_idx)
            ev["direction"] = -1
            ev["sl"] = (px_closed.reindex(sig_idx, method="ffill")
                        + atr_closed.reindex(sig_idx, method="ffill") * 3.0)
            ev["tp"] = 0.0
            ev = ev.dropna()
            tr = simulate(m1, ev, max_hold_min=24 * 60)
            report(tr, f"S6 abs>{ab*100:.3f}% trend={use_trend}", split_ts)
            if use_trend and ab == 0.0001 and len(tr):
                monthly(tr, "S6 0.01%+trend")


if __name__ == "__main__":
    main()
