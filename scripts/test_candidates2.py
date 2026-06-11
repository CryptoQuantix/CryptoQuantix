#!/usr/bin/env python3
"""
Round 2 — refinements of surviving candidates.

S1  (winner round 1): breakdown short lb=48 sl=2xATR hold=24h
    variants: lb=72, rr={2,3}, orderflow filter (bar buy_ratio < th),
    funding filter (funding > 0)
S5  Pullback short ("short the rip"): close crosses ABOVE sma_fast while
    below sma_slow (downtrend) -> short the relief rally.
S5L Mirror long (pullback long in uptrend) — sanity check.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
from strategy_lab import (load_1m, load_funding, resample, atr, simulate,
                          report, IS_FRAC)
from test_candidates import make_events


def main():
    m1 = load_1m()
    split_ts = m1.index[int(len(m1) * IS_FRAC)]
    print(f"Data: {m1.index[0]:%Y-%m-%d} -> {m1.index[-1]:%Y-%m-%d}  split {split_ts:%Y-%m-%d}")

    h1 = resample(m1, "1h")
    atr_h1 = atr(h1, 14)
    fr = load_funding()
    # funding known at event time; ffill onto 1h close times (bar END labeled)
    fr_closed = fr.reindex(h1.index + pd.Timedelta(hours=1), method="ffill")
    fr_closed.index = h1.index  # value of last funding known at each bar close

    # ============ S1 refinements ============
    print("\n" + "#" * 70)
    print("# S1 REFINEMENTS — breakdown short, sl=2xATR hold=24h")
    print("#" * 70)
    for lb in [48, 72]:
        lo_n = h1["low"].rolling(lb).min().shift(1)
        sma = h1["close"].rolling(lb).mean()
        base = (h1["close"] < lo_n) & (h1["close"] < sma)
        variants = {
            "base": base,
            "+flow(br<0.50)": base & (h1["buy_ratio"] < 0.50),
            "+flow(br<0.45)": base & (h1["buy_ratio"] < 0.45),
            "+funding>0": base & (fr_closed > 0),
        }
        for vname, sig in variants.items():
            for rr in [2.0, 3.0]:
                ev = make_events(sig, -1, h1["close"], atr_h1 * 2.0, rr, 60)
                tr = simulate(m1, ev, max_hold_min=24 * 60)
                report(tr, f"S1 lb={lb} {vname} rr={rr}", split_ts)

    # ============ S5 pullback short ============
    print("\n" + "#" * 70)
    print("# S5 — PULLBACK SHORT (relief rally in downtrend)")
    print("#" * 70)
    for fast in [12, 24]:
        sma_f = h1["close"].rolling(fast).mean()
        for slow in [120, 168]:
            sma_s = h1["close"].rolling(slow).mean()
            cross_up = (h1["close"] > sma_f) & (h1["close"].shift(1) <= sma_f.shift(1))
            sig = cross_up & (h1["close"] < sma_s)
            for sl_mult in [1.5, 2.0]:
                for rr in [1.5, 2.0]:
                    for hold_h in [24, 48]:
                        ev = make_events(sig, -1, h1["close"], atr_h1 * sl_mult, rr, 60)
                        tr = simulate(m1, ev, max_hold_min=hold_h * 60)
                        report(tr, f"S5 f={fast} s={slow} sl={sl_mult} rr={rr} hold={hold_h}h",
                               split_ts)

    # ============ S5L mirror long ============
    print("\n" + "#" * 70)
    print("# S5L — PULLBACK LONG mirror (uptrend) — sanity")
    print("#" * 70)
    sma_f = h1["close"].rolling(24).mean()
    sma_s = h1["close"].rolling(168).mean()
    cross_dn = (h1["close"] < sma_f) & (h1["close"].shift(1) >= sma_f.shift(1))
    sig = cross_dn & (h1["close"] > sma_s)
    ev = make_events(sig, +1, h1["close"], atr_h1 * 2.0, 2.0, 60)
    tr = simulate(m1, ev, max_hold_min=24 * 60)
    report(tr, "S5L f=24 s=168 sl=2.0 rr=2.0 hold=24h", split_ts)


if __name__ == "__main__":
    main()
