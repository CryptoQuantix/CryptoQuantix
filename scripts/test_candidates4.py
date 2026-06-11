#!/usr/bin/env python3
"""
Round 4 — macro-phase gating + bull-side long candidates (4y dataset).

1. TB short  + macro BEAR gate (daily close < SMA200d) — bleed removal
2. FS short  + macro BEAR gate
3. LONG candidates gated macro BULL:
   a. Donchian long lb=168h (7d high) / lb=480h (20d high)
   b. Pullback long: 1h close crosses below SMA24 in macro bull
   c. 3d momentum: close > close 72 bars ago
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

from strategy_lab import simulate, atr
from multicycle_research import (load_4y, load_funding_4y, resample,
                                 compute_phase, phase_report, make_events)


def main():
    m1 = load_4y()
    bull_daily = compute_phase(m1)
    h1 = resample(m1, "1h")
    atr1h = atr(h1, 14)

    # macro phase aligned to 1h bars (bull_daily already shifted 1 day)
    bull_at_h1 = bull_daily.reindex(h1.index.floor("D")).fillna(False).values
    bull_at_h1 = pd.Series(bull_at_h1, index=h1.index)

    sma48 = h1["close"].rolling(48).mean()
    print(f"Data: {h1.index[0]:%Y-%m-%d} -> {h1.index[-1]:%Y-%m-%d}  "
          f"macro-bull bars: {bull_at_h1.mean()*100:.0f}%")

    # ============ 1. TB short with macro gate ============
    print("\n" + "#" * 72)
    print("# TB SHORT + macro BEAR gate")
    print("#" * 72)
    lo48 = h1["low"].rolling(48).min().shift(1)
    sig_s = (h1["close"] < lo48) & (h1["close"] < sma48) & (h1["buy_ratio"] < 0.50)
    for macro_gate in [False, True]:
        s = sig_s & (~bull_at_h1) if macro_gate else sig_s
        ev = make_events(s, -1, h1["close"], atr1h * 2.0, 2.0, 60)
        tr = simulate(m1, ev, max_hold_min=24 * 60)
        phase_report(tr, bull_daily, f"TB SHORT macro_gate={macro_gate}")

    # ============ 2. FS short with macro gate ============
    print("\n" + "#" * 72)
    print("# FS SHORT + macro BEAR gate")
    print("#" * 72)
    fr = load_funding_4y()
    atr_c = atr1h.copy(); atr_c.index = atr_c.index + pd.Timedelta(hours=1)
    px_c = h1["close"].copy(); px_c.index = px_c.index + pd.Timedelta(hours=1)
    sma_c = sma48.copy(); sma_c.index = sma_c.index + pd.Timedelta(hours=1)
    bull_c = bull_at_h1.copy(); bull_c.index = bull_c.index + pd.Timedelta(hours=1)
    px_at = px_c.reindex(fr.index, method="ffill")
    sma_at = sma_c.reindex(fr.index, method="ffill")
    atr_at = atr_c.reindex(fr.index, method="ffill")
    bull_at = bull_c.reindex(fr.index, method="ffill").fillna(False)
    for macro_gate in [False, True]:
        mask = (fr > 0.00005) & (px_at < sma_at)
        if macro_gate:
            mask &= ~bull_at
        idx = fr[mask].index
        ev = pd.DataFrame(index=idx)
        ev["direction"] = -1
        ev["sl"] = px_at.loc[idx] + atr_at.loc[idx] * 3.0
        ev["tp"] = 0.0
        ev = ev.dropna()
        tr = simulate(m1, ev, max_hold_min=24 * 60)
        phase_report(tr, bull_daily, f"FS SHORT macro_gate={macro_gate}")

    # ============ 3. LONG candidates (macro BULL gated) ============
    print("\n" + "#" * 72)
    print("# LONG candidates — macro BULL gate")
    print("#" * 72)

    # 3a. Donchian long, longer lookbacks
    for lb, hold_h in [(168, 48), (480, 72)]:
        hi_n = h1["high"].rolling(lb).max().shift(1)
        sig = (h1["close"] > hi_n) & (h1["close"] > sma48) & bull_at_h1 \
              & (h1["buy_ratio"] > 0.50)
        for rr in [3.0, 0]:
            ev = make_events(sig, +1, h1["close"], atr1h * 2.0, rr, 60)
            tr = simulate(m1, ev, max_hold_min=hold_h * 60)
            phase_report(tr, bull_daily, f"DonchianLONG lb={lb}h rr={rr} hold={hold_h}h")

    # 3b. Pullback long in macro bull
    sma24 = h1["close"].rolling(24).mean()
    cross_dn = (h1["close"] < sma24) & (h1["close"].shift(1) >= sma24.shift(1))
    for sl_mult, rr, hold_h in [(2.0, 2.0, 48), (1.5, 3.0, 48)]:
        sig = cross_dn & bull_at_h1
        ev = make_events(sig, +1, h1["close"], atr1h * sl_mult, rr, 60)
        tr = simulate(m1, ev, max_hold_min=hold_h * 60)
        phase_report(tr, bull_daily, f"PullbackLONG sl={sl_mult} rr={rr} hold={hold_h}h")

    # 3c. 3d momentum long
    mom = h1["close"] > h1["close"].shift(72)
    sig = mom & ~mom.shift(1).fillna(False) & bull_at_h1   # fresh momentum flip
    for rr, hold_h in [(2.0, 24), (0, 48)]:
        ev = make_events(sig, +1, h1["close"], atr1h * 2.0, rr, 60)
        tr = simulate(m1, ev, max_hold_min=hold_h * 60)
        phase_report(tr, bull_daily, f"Mom3dLONG rr={rr} hold={hold_h}h")


if __name__ == "__main__":
    main()
